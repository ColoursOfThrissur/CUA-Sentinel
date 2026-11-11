"""Tests for Task Cancellation & Graceful Drain (AT-B-05)."""
from pathlib import Path
import threading
import time
import pytest

from sentinel_core.db import SentinelDB
from sentinel_core.leases import LeaseManager
from sentinel_core.state_machine import StateMachine, TaskState
from sentinel_core.verification_gate import VerificationGate, VerificationResult
from sentinel_core.dag_orchestrator import (
    DAGOrchestrator,
    DAGStepDefinition,
    DAGState,
    DAGStepState,
)
from sentinel_broker.tool_registry import ToolRegistry
from sentinel_broker.pdp import PolicyDecisionPoint
from sentinel_broker.broker import ExecutionBroker
from sentinel_core.side_effects import SideEffectLedger, EffectClass
from sentinel_adaptive.pilot_controller import AdaptivePilotController
from sentinel_adaptive.mistake_ledger import MistakeMemory
from sentinel_adaptive.skill_bank import SkillBank


@pytest.fixture
def test_db(tmp_path: Path):
    db_file = tmp_path / "test_cancel.db"
    return SentinelDB(str(db_file))


def test_state_machine_cancel_task(test_db):
    sm = StateMachine(test_db)

    # 1. Cancel queued task
    t1 = sm.create_task("task_c1", "Test Queued Cancellation")
    assert t1.state == TaskState.QUEUED

    cancelled_t1 = sm.cancel_task("task_c1", reason="Operator requested cancellation")
    assert cancelled_t1.state == TaskState.CANCELLED
    assert cancelled_t1.failure_reason == "Operator requested cancellation"

    # Verify task transition record
    trans = test_db.execute_read("SELECT * FROM task_transitions WHERE task_id = 'task_c1' ORDER BY id DESC LIMIT 1")
    assert len(trans) == 1
    assert trans[0]["to_state"] == "Cancelled"

    # 2. Cancel running task with active lease
    sm.create_task("task_c2", "Test Running Cancellation")
    t2, lease = sm.start_next_attempt("task_c2")
    assert t2.state == TaskState.RUNNING
    assert sm.leases.is_lease_valid(lease.attempt_id, lease.lease_token) is True

    cancelled_t2 = sm.cancel_task("task_c2", reason="Subprocess runaway loop detected")
    assert cancelled_t2.state == TaskState.CANCELLED

    # Monotonic lease MUST be revoked/fenced out immediately (AT-B-10)
    assert sm.leases.is_lease_valid(lease.attempt_id, lease.lease_token) is False

    # Stale attempt status verification
    att_row = test_db.execute_one("SELECT status FROM attempts WHERE id = ?", (lease.attempt_id,))
    assert att_row["status"] == "FencedOut"


def test_fenced_lease_rejected_by_pdp_post_cancellation(test_db):
    sm = StateMachine(test_db)
    tool_reg = ToolRegistry()
    ledger = SideEffectLedger(test_db)
    pdp = PolicyDecisionPoint(sm.leases, tool_reg)
    broker = ExecutionBroker(pdp, tool_reg, ledger)

    @tool_reg.register("safe_read", "Read organ", EffectClass.READ_ONLY)
    def safe_read(p, ctx):
        return {"read": True}

    sm.create_task("task_c3", "Lease test")
    t3, lease = sm.start_next_attempt("task_c3")

    # While running, call is authorized
    res1 = broker.dispatch_call(lease.attempt_id, lease.lease_token, "safe_read", {})
    assert res1["allowed"] is True

    # Operator cancels task
    sm.cancel_task("task_c3")

    # Post-cancellation call MUST be rejected with stale lease
    res2 = broker.dispatch_call(lease.attempt_id, lease.lease_token, "safe_read", {})
    assert res2["allowed"] is False
    assert res2["status"] == "REJECTED_STALE_LEASE"


def test_dag_orchestrator_cancel_dag(test_db):
    dag_orch = DAGOrchestrator(test_db)

    steps = [
        DAGStepDefinition("step_1", "Generate data", "data_analyst", "data"),
        DAGStepDefinition("step_2", "Process data", "code_engineer", "code", dependencies=["step_1"]),
        DAGStepDefinition("step_3", "Report summary", "systems_reporter", "analysis", dependencies=["step_2"]),
    ]
    dag_id = dag_orch.create_dag("Pipeline Cancel Test", "Test DAG cancel", steps)

    # Cancel DAG before or during execution
    cancelled_dag = dag_orch.cancel_dag(dag_id, reason="Operator aborted whole workflow")
    assert cancelled_dag["state"] == DAGState.CANCELLED.value
    assert cancelled_dag["error"] == "Operator aborted whole workflow"

    # All uncompleted steps must be Cancelled
    for s in cancelled_dag["steps"]:
        assert s["state"] == DAGStepState.CANCELLED.value

    # Re-executing cancelled DAG halts immediately
    executed = dag_orch.execute_dag(dag_id, lambda s, p: {"success": True})
    assert executed["state"] == DAGState.CANCELLED.value


def test_pilot_controller_cooperative_cancellation(test_db, tmp_path):
    sm = StateMachine(test_db)
    v_gate = VerificationGate(test_db)
    m_mem = MistakeMemory(test_db)
    s_bank = SkillBank(test_db, skills_dir=tmp_path / "skills")
    pilot = AdaptivePilotController(sm, v_gate, m_mem, s_bank)

    cancel_evt = threading.Event()
    worker_called = 0

    def slow_worker(goal, attempt, anti):
        nonlocal worker_called
        worker_called += 1
        # Worker simulates checking or responding to cancellation event
        cancel_evt.set()  # Signal cancellation mid-attempt
        return {"output": "slow"}

    def strict_verifier(out):
        return VerificationResult(passed=False, error_category="NOT_PASSED")

    result = pilot.run_task(
        task_id="task_pilot_cancel",
        goal="Test pilot cooperative cancellation",
        worker_executor=slow_worker,
        verifier=strict_verifier,
        max_attempts=5,
        cancellation_event=cancel_evt,
    )

    # Must be cancelled after 1st attempt without burning all 5 attempts!
    assert result.task.state == TaskState.CANCELLED
    assert result.success is False
    assert worker_called == 1
    assert result.attempts_taken == 1
