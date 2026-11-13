"""Tests for Human-in-the-Loop (HITL) Interactive Checkpoints - Pillar 2."""
from pathlib import Path
import pytest

from sentinel_core.db import SentinelDB
from sentinel_core.leases import LeaseManager
from sentinel_core.state_machine import StateMachine, TaskState
from sentinel_broker.tool_registry import ToolRegistry, EffectClass
from sentinel_broker.pdp import PolicyDecisionPoint
from sentinel_broker.broker import ExecutionBroker
from sentinel_core.side_effects import SideEffectLedger


@pytest.fixture
def hitl_env(tmp_path: Path):
    db_file = tmp_path / "test_hitl.db"
    db = SentinelDB(str(db_file))
    state_machine = StateMachine(db)
    leases = state_machine.leases
    tool_reg = ToolRegistry()
    side_effects = SideEffectLedger(db)

    # Register an irreversible write tool
    @tool_reg.register("danger_format_drive", "Irreversible destructive action", EffectClass.IRREVERSIBLE)
    def danger_format_drive(params, ctx):
        return {"formatted": params.get("target")}

    pdp = PolicyDecisionPoint(leases=leases, tool_registry=tool_reg)
    broker = ExecutionBroker(pdp=pdp, tool_registry=tool_reg, side_effects=side_effects)

    return db, state_machine, leases, broker


def test_hitl_pdp_triggers_requires_approval(hitl_env):
    db, sm, leases, broker = hitl_env

    # 1. Create and start a task
    with db.transaction() as c:
        c.execute("INSERT INTO tasks (id, title, state, attempt_count, max_attempts, created_at, updated_at) VALUES ('task_hitl_1', 'Format Drive', 'Queued', 0, 3, 0, 0)")
    task, lease = sm.start_next_attempt("task_hitl_1")

    # 2. Call irreversible tool with enable_hitl=True
    res = broker.dispatch_call(
        attempt_id=lease.attempt_id,
        lease_token=lease.lease_token,
        tool_name="danger_format_drive",
        params={"target": "C:\\"},
        context={"enable_hitl": True, "allow_irreversible": False},
    )

    assert res["allowed"] is False
    assert res["status"] == "REQUIRES_APPROVAL"
    assert "requires operator approval" in res["error"].lower()


def test_hitl_state_machine_approval_resolution(hitl_env):
    db, sm, leases, broker = hitl_env

    with db.transaction() as c:
        c.execute("INSERT INTO tasks (id, title, state, attempt_count, max_attempts, created_at, updated_at) VALUES ('task_hitl_2', 'Delete Files', 'Queued', 0, 3, 0, 0)")
    task, lease = sm.start_next_attempt("task_hitl_2")

    # Transition to WaitingForApproval
    t_waiting = sm.transition_to_approval(
        task_id="task_hitl_2",
        attempt_id=lease.attempt_id,
        lease_token=lease.lease_token,
        pending_action={"tool": "danger_format_drive"},
        reason="Operator clearance needed",
    )
    assert t_waiting.state == TaskState.WAITING_FOR_APPROVAL

    # Operator approves -> Transitions back to Running
    t_resumed = sm.transition_from_approval(
        task_id="task_hitl_2",
        attempt_id=lease.attempt_id,
        lease_token=lease.lease_token,
        approved=True,
        operator="SuperAdmin",
        reason="Verified safe staging environment",
    )
    assert t_resumed.state == TaskState.RUNNING

    # Subsequent call with allow_irreversible=True succeeds
    res_ok = broker.dispatch_call(
        attempt_id=lease.attempt_id,
        lease_token=lease.lease_token,
        tool_name="danger_format_drive",
        params={"target": "D:\\"},
        context={"allow_irreversible": True},
    )
    assert res_ok["allowed"] is True
    assert res_ok["status"] == "SUCCESS"


def test_hitl_state_machine_denial_resolution(hitl_env):
    db, sm, leases, broker = hitl_env

    with db.transaction() as c:
        c.execute("INSERT INTO tasks (id, title, state, attempt_count, max_attempts, created_at, updated_at) VALUES ('task_hitl_3', 'Dangerous Act', 'Queued', 0, 3, 0, 0)")
    task, lease = sm.start_next_attempt("task_hitl_3")

    # Transition to WaitingForApproval
    sm.transition_to_approval(
        task_id="task_hitl_3",
        attempt_id=lease.attempt_id,
        lease_token=lease.lease_token,
    )

    # Operator denies -> Transitions to Failed
    t_failed = sm.transition_from_approval(
        task_id="task_hitl_3",
        attempt_id=lease.attempt_id,
        lease_token=lease.lease_token,
        approved=False,
        operator="SecurityAuditor",
        reason="Action denied by policy",
    )
    assert t_failed.state == TaskState.FAILED
