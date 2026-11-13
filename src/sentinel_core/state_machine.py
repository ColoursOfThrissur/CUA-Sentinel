"""Sentinel Task State Machine (CD-04, AT-B-03 to AT-B-10, AT-D-08).
Enforces deterministic lifecycle transitions, monotonic attempt fencing, and atomic commits.
"""
from __future__ import annotations

import json
import sqlite3
import time
from enum import Enum
from typing import Any, NamedTuple

from sentinel_core.db import SentinelDB
from sentinel_core.leases import LeaseManager, LeaseRecord
from sentinel_core.side_effects import SideEffectLedger


class TaskState(str, Enum):
    QUEUED = "Queued"
    RUNNING = "Running"
    WAITING_FOR_APPROVAL = "WaitingForApproval"
    VERIFYING = "Verifying"
    SUCCEEDED = "Succeeded"
    FAILED = "Failed"
    NEEDS_RECONCILIATION = "NeedsReconciliation"
    CANCELLED = "Cancelled"


LEGAL_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.QUEUED: {TaskState.RUNNING, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.RUNNING: {TaskState.WAITING_FOR_APPROVAL, TaskState.VERIFYING, TaskState.FAILED, TaskState.NEEDS_RECONCILIATION, TaskState.CANCELLED},
    TaskState.WAITING_FOR_APPROVAL: {TaskState.RUNNING, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.VERIFYING: {TaskState.SUCCEEDED, TaskState.RUNNING, TaskState.FAILED, TaskState.NEEDS_RECONCILIATION, TaskState.CANCELLED},
    TaskState.NEEDS_RECONCILIATION: {TaskState.QUEUED, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.SUCCEEDED: set(),  # Terminal
    TaskState.FAILED: set(),     # Terminal
    TaskState.CANCELLED: set(),  # Terminal
}


class InvalidTransitionError(Exception):
    pass


class StaleLeaseError(Exception):
    pass


class TaskRecord(NamedTuple):
    id: str
    title: str
    description: str | None
    state: TaskState
    attempt_count: int
    max_attempts: int
    created_at: float
    updated_at: float
    failure_reason: str | None


class StateMachine:
    def __init__(self, db: SentinelDB):
        self.db = db
        self.leases = LeaseManager(db)
        self.side_effects = SideEffectLedger(db)

    def create_task(self, task_id: str, title: str, description: str = "", max_attempts: int = 3) -> TaskRecord:
        now = time.time()
        with self.db.transaction() as c:
            c.execute(
                """
                INSERT INTO tasks (id, title, description, state, attempt_count, max_attempts, created_at, updated_at)
                VALUES (?, ?, ?, 'Queued', 0, ?, ?, ?)
                """,
                (task_id, title, description, max_attempts, now, now),
            )
            c.execute(
                """
                INSERT INTO task_transitions (task_id, from_state, to_state, reason, transition_ts)
                VALUES (?, 'None', 'Queued', 'Task created', ?)
                """,
                (task_id, now),
            )
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> TaskRecord | None:
        row = self.db.execute_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
        if not row:
            return None
        return TaskRecord(
            id=row["id"],
            title=row["title"],
            description=row["description"],
            state=TaskState(row["state"]),
            attempt_count=row["attempt_count"],
            max_attempts=row["max_attempts"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            failure_reason=row["failure_reason"],
        )

    def start_next_attempt(self, task_id: str) -> tuple[TaskRecord, LeaseRecord]:
        """Transitions task from Queued or Verifying into Running, allocating a new monotonic lease token."""
        now = time.time()
        with self.db.transaction() as c:
            c.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            row = c.fetchone()
            if not row:
                raise ValueError(f"Task {task_id} not found")

            current_state = TaskState(row["state"])
            if current_state not in (TaskState.QUEUED, TaskState.VERIFYING):
                raise InvalidTransitionError(f"Cannot start attempt from state {current_state}")

            new_attempt_count = row["attempt_count"] + 1
            if new_attempt_count > row["max_attempts"]:
                raise ValueError(f"Max attempts ({row['max_attempts']}) exceeded for task {task_id}")

            # 1. Update task state
            c.execute(
                """
                UPDATE tasks
                SET state = 'Running', attempt_count = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_attempt_count, now, task_id),
            )

            # 2. Record transition
            c.execute(
                """
                INSERT INTO task_transitions (task_id, from_state, to_state, reason, transition_ts)
                VALUES (?, ?, 'Running', ?, ?)
                """,
                (task_id, current_state.value, f"Attempt {new_attempt_count} started", now),
            )

            # 3. Monotonic lease allocation (AT-B-10)
            lease = self.leases.allocate_next_lease(task_id, new_attempt_count, cursor=c)

        return self.get_task(task_id), lease

    def transition_to_approval(
        self,
        task_id: str,
        attempt_id: str,
        lease_token: int,
        pending_action: dict[str, Any] | None = None,
        reason: str = "Operator authorization required",
    ) -> TaskRecord:
        """Transitions task from Running -> WaitingForApproval (HITL Checkpoint)."""
        now = time.time()
        with self.db.transaction() as c:
            if not self.leases.is_lease_valid(attempt_id, lease_token):
                raise StaleLeaseError(f"Attempt {attempt_id} with lease {lease_token} is stale or invalid")
            action_desc = f": {json.dumps(pending_action)}" if pending_action else ""
            task = self._assert_transition(
                c, task_id, TaskState.WAITING_FOR_APPROVAL, f"{reason}{action_desc}", now
            )
        return task

    def transition_from_approval(
        self,
        task_id: str,
        attempt_id: str,
        lease_token: int,
        approved: bool = True,
        operator: str = "operator",
        reason: str = "Operator resolved checkpoint",
    ) -> TaskRecord:
        """Transitions task from WaitingForApproval -> Running (if approved) or Failed (if denied)."""
        now = time.time()
        target_state = TaskState.RUNNING if approved else TaskState.FAILED
        with self.db.transaction() as c:
            if not self.leases.is_lease_valid(attempt_id, lease_token):
                raise StaleLeaseError(f"Attempt {attempt_id} with lease {lease_token} is stale or invalid")
            task = self._assert_transition(
                c, task_id, target_state, f"[{operator}] {reason}", now
            )
        return task

    def transition_to_verifying(self, task_id: str, attempt_id: str, lease_token: int) -> TaskRecord:
        """Transitions Running -> Verifying once worker finishes its work payload."""
        now = time.time()
        with self.db.transaction() as c:
            # Validate lease
            if not self.leases.is_lease_valid(attempt_id, lease_token):
                raise StaleLeaseError(f"Attempt {attempt_id} with lease {lease_token} is stale or invalid")

            task = self._assert_transition(c, task_id, TaskState.VERIFYING, "Worker completed execution payload", now)
        return task

    def commit_success(self, task_id: str, attempt_id: str, lease_token: int) -> TaskRecord:
        """Transitions Verifying -> Succeeded (AT-D-08: Atomic commit)."""
        now = time.time()
        with self.db.transaction() as c:
            if not self.leases.is_lease_valid(attempt_id, lease_token):
                raise StaleLeaseError(f"Attempt {attempt_id} with lease {lease_token} is stale or invalid")

            # 1. Update task
            task = self._assert_transition(c, task_id, TaskState.SUCCEEDED, "Verification gate passed", now)

            # 2. Mark attempt committed
            self.leases.mark_attempt_finished(attempt_id, "Committed", cursor=c)

        return task

    def handle_verification_failure(
        self,
        task_id: str,
        attempt_id: str,
        lease_token: int,
        reason: str,
    ) -> tuple[TaskRecord, bool]:
        """Handles a verification failure. Returns (task, can_retry)."""
        now = time.time()
        can_retry = False
        with self.db.transaction() as c:
            if not self.leases.is_lease_valid(attempt_id, lease_token):
                raise StaleLeaseError(f"Attempt {attempt_id} with lease {lease_token} is stale or invalid")

            # Mark attempt aborted
            self.leases.mark_attempt_finished(attempt_id, "Aborted", cursor=c)

            c.execute("SELECT attempt_count, max_attempts FROM tasks WHERE id = ?", (task_id,))
            row = c.fetchone()
            attempt_count = row["attempt_count"]
            max_attempts = row["max_attempts"]

            if attempt_count < max_attempts:
                can_retry = True
                # Can retry: task stays in Verifying temporarily until start_next_attempt is called
                c.execute(
                    """
                    INSERT INTO task_transitions (task_id, from_state, to_state, reason, transition_ts)
                    VALUES (?, 'Verifying', 'Verifying', ?, ?)
                    """,
                    (task_id, f"Attempt {attempt_count} failed verification: {reason}. Scheduling retry.", now),
                )
            else:
                can_retry = False
                # Terminal Failure
                c.execute(
                    """
                    UPDATE tasks
                    SET state = 'Failed', failure_reason = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (reason, now, task_id),
                )
                c.execute(
                    """
                    INSERT INTO task_transitions (task_id, from_state, to_state, reason, transition_ts)
                    VALUES (?, 'Verifying', 'Failed', ?, ?)
                    """,
                    (task_id, f"Max attempts exhausted. Last failure: {reason}", now),
                )

        return self.get_task(task_id), can_retry

    def recover_interrupted_tasks(self) -> list[str]:
        """AT-B-07: Crash recovery. Scans for tasks left in Running or Verifying and recovers them."""
        recovered = []
        now = time.time()
        with self.db.transaction() as c:
            c.execute("SELECT id, state, attempt_count, max_attempts FROM tasks WHERE state IN ('Running', 'Verifying', 'WaitingForApproval')")
            rows = c.fetchall()
            for r in rows:
                task_id = r["id"]
                state = TaskState(r["state"])

                # Check if there are unresolved IRREVERSIBLE intents
                c.execute(
                    """
                    SELECT COUNT(*) as cnt FROM side_effect_ledger se
                    JOIN attempts a ON se.attempt_id = a.id
                    WHERE a.task_id = ? AND se.effect_class = 'IRREVERSIBLE' AND se.status = 'INTENT_RECORDED'
                    """,
                    (task_id,),
                )
                irreversible_count = c.fetchone()["cnt"]

                # Fence out any active attempts
                c.execute(
                    "UPDATE attempts SET status = 'FencedOut', finished_at = ? WHERE task_id = ? AND status = 'Active'",
                    (now, task_id),
                )

                if irreversible_count > 0:
                    # Require operator reconciliation
                    c.execute(
                        "UPDATE tasks SET state = 'NeedsReconciliation', failure_reason = 'Crashed with open irreversible intent', updated_at = ? WHERE id = ?",
                        (now, task_id),
                    )
                    c.execute(
                        "INSERT INTO task_transitions (task_id, from_state, to_state, reason, transition_ts) VALUES (?, ?, 'NeedsReconciliation', 'Crash recovery fence', ?)",
                        (task_id, state.value, now),
                    )
                else:
                    # Safe to fail or retry
                    if r["attempt_count"] < r["max_attempts"]:
                        c.execute(
                            "UPDATE tasks SET state = 'Queued', updated_at = ? WHERE id = ?",
                            (now, task_id),
                        )
                        c.execute(
                            "INSERT INTO task_transitions (task_id, from_state, to_state, reason, transition_ts) VALUES (?, ?, 'Queued', 'Crash recovery reset', ?)",
                            (task_id, state.value, now),
                        )
                    else:
                        c.execute(
                            "UPDATE tasks SET state = 'Failed', failure_reason = 'Crashed during final attempt', updated_at = ? WHERE id = ?",
                            (now, task_id),
                        )
                        c.execute(
                            "INSERT INTO task_transitions (task_id, from_state, to_state, reason, transition_ts) VALUES (?, ?, 'Failed', 'Crash recovery terminal fail', ?)",
                            (task_id, state.value, now),
                        )
                recovered.append(task_id)
        return recovered

    def cancel_task(self, task_id: str, reason: str = "Operator cancelled task") -> TaskRecord:
        """
        AT-B-05: Cancels an active or queued task, fences out any active attempt leases,
        and transitions the task state to CANCELLED.
        """
        now = time.time()
        with self.db.transaction() as c:
            c.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            row = c.fetchone()
            if not row:
                raise ValueError(f"Task '{task_id}' not found.")

            current_state = TaskState(row["state"])
            if current_state in (TaskState.SUCCEEDED, TaskState.FAILED, TaskState.CANCELLED):
                # Already terminal
                return self.get_task(task_id)

            # 1. Fence out any active attempts for this task to revoke their leases
            c.execute(
                "UPDATE attempts SET status = 'FencedOut', finished_at = ? WHERE task_id = ? AND status = 'Active'",
                (now, task_id),
            )

            # 2. Update task state to Cancelled
            c.execute(
                "UPDATE tasks SET state = 'Cancelled', failure_reason = ?, updated_at = ? WHERE id = ?",
                (reason, now, task_id),
            )
            c.execute(
                "INSERT INTO task_transitions (task_id, from_state, to_state, reason, transition_ts) VALUES (?, ?, 'Cancelled', ?, ?)",
                (task_id, current_state.value, reason, now),
            )

            c.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            r = c.fetchone()
            return TaskRecord(
                id=r["id"],
                title=r["title"],
                description=r["description"],
                state=TaskState(r["state"]),
                attempt_count=r["attempt_count"],
                max_attempts=r["max_attempts"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
                failure_reason=r["failure_reason"],
            )

    def _assert_transition(self, cursor: sqlite3.Cursor, task_id: str, target_state: TaskState, reason: str, now: float) -> TaskRecord:
        cursor.execute("SELECT state FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Task {task_id} not found")
        current_state = TaskState(row["state"])
        if target_state not in LEGAL_TRANSITIONS.get(current_state, set()):
            raise InvalidTransitionError(f"Illegal transition from {current_state} to {target_state}")

        cursor.execute(
            "UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?",
            (target_state.value, now, task_id),
        )
        cursor.execute(
            "INSERT INTO task_transitions (task_id, from_state, to_state, reason, transition_ts) VALUES (?, ?, ?, ?, ?)",
            (task_id, current_state.value, target_state.value, reason, now),
        )
        cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        r = cursor.fetchone()
        return TaskRecord(
            id=r["id"],
            title=r["title"],
            description=r["description"],
            state=TaskState(r["state"]),
            attempt_count=r["attempt_count"],
            max_attempts=r["max_attempts"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
            failure_reason=r["failure_reason"],
        )
