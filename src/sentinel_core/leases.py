"""Sentinel Monotonic Lease Manager (AT-B-10).
Guarantees strictly increasing lease tokens per attempt to fence out zombie or delayed worker processes.
"""
from __future__ import annotations

import sqlite3
import time
from typing import NamedTuple

from sentinel_core.db import SentinelDB


class LeaseRecord(NamedTuple):
    attempt_id: str
    task_id: str
    attempt_number: int
    lease_token: int
    status: str


class LeaseManager:
    def __init__(self, db: SentinelDB):
        self.db = db

    def allocate_next_lease(self, task_id: str, attempt_number: int, cursor: sqlite3.Cursor | None = None) -> LeaseRecord:
        """Atomically allocates a new attempt with a strictly monotonic lease token."""
        attempt_id = f"att_{task_id}_{attempt_number}_{int(time.time() * 1000)}"

        def _do_allocate(c: sqlite3.Cursor) -> LeaseRecord:
            # 1. Fence out any existing Active attempts for this task
            c.execute(
                "UPDATE attempts SET status = 'FencedOut', finished_at = ? WHERE task_id = ? AND status = 'Active'",
                (time.time(), task_id),
            )

            # 2. Find the highest existing lease token globally
            c.execute("SELECT COALESCE(MAX(lease_token), 0) + 1 AS next_lease FROM attempts")
            next_lease = c.fetchone()["next_lease"]

            # 3. Insert the new active attempt
            now = time.time()
            c.execute(
                """
                INSERT INTO attempts (id, task_id, attempt_number, lease_token, status, started_at)
                VALUES (?, ?, ?, ?, 'Active', ?)
                """,
                (attempt_id, task_id, attempt_number, next_lease, now),
            )
            return LeaseRecord(
                attempt_id=attempt_id,
                task_id=task_id,
                attempt_number=attempt_number,
                lease_token=next_lease,
                status="Active",
            )

        if cursor is not None:
            return _do_allocate(cursor)
        else:
            with self.db.transaction() as c:
                return _do_allocate(c)

    def is_lease_valid(self, attempt_id: str, lease_token: int) -> bool:
        """Validates that the provided lease token is currently Active and matches the attempt."""
        row = self.db.execute_one(
            "SELECT id, status, lease_token FROM attempts WHERE id = ? AND lease_token = ?",
            (attempt_id, lease_token),
        )
        if not row:
            return False
        return row["status"] == "Active"

    def mark_attempt_finished(self, attempt_id: str, status: str, cursor: sqlite3.Cursor | None = None):
        """Marks an attempt as Committed or Aborted."""
        assert status in ("Committed", "Aborted", "FencedOut")
        now = time.time()
        sql = "UPDATE attempts SET status = ?, finished_at = ? WHERE id = ?"
        if cursor is not None:
            cursor.execute(sql, (status, now, attempt_id))
        else:
            with self.db.transaction() as c:
                c.execute(sql, (status, now, attempt_id))
