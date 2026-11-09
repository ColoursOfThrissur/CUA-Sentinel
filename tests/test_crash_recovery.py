"""Tests for Crash and Interrupted Task Recovery (AT-B-07)."""
import pytest
from pathlib import Path
import tempfile
import shutil

from sentinel_core.db import SentinelDB
from sentinel_core.state_machine import StateMachine, TaskState
from sentinel_core.side_effects import SideEffectLedger, EffectClass


@pytest.fixture
def test_db():
    temp_dir = Path(tempfile.mkdtemp())
    db_path = temp_dir / "test_recovery.db"
    db = SentinelDB(db_path)
    yield db
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_crash_recovery_resets_safe_tasks(test_db):
    sm = StateMachine(test_db)
    task = sm.create_task("task_crash_safe", "Safe Crash Task", max_attempts=3)
    task, lease = sm.start_next_attempt("task_crash_safe")
    assert task.state == TaskState.RUNNING

    # Simulate power cut / crash: control plane restarts
    sm_restarted = StateMachine(test_db)
    recovered = sm_restarted.recover_interrupted_tasks()
    assert "task_crash_safe" in recovered

    reloaded = sm_restarted.get_task("task_crash_safe")
    # Recovered safely to Queued for retry because attempts < max_attempts and no irreversible intent
    assert reloaded.state == TaskState.QUEUED


def test_crash_recovery_flags_irreversible_intents(test_db):
    sm = StateMachine(test_db)
    task = sm.create_task("task_crash_irrev", "Irreversible Crash Task", max_attempts=3)
    task, lease = sm.start_next_attempt("task_crash_irrev")

    # Record open IRREVERSIBLE intent
    ledger = SideEffectLedger(test_db)
    ledger.record_intent(
        attempt_id=lease.attempt_id,
        tool_name="git_push",
        effect_class=EffectClass.IRREVERSIBLE,
        intent_payload={"branch": "main"},
    )

    # Crash occurs before outcome is recorded
    sm_restarted = StateMachine(test_db)
    recovered = sm_restarted.recover_interrupted_tasks()
    assert "task_crash_irrev" in recovered

    reloaded = sm_restarted.get_task("task_crash_irrev")
    # Must transition to NeedsReconciliation because of open irreversible intent
    assert reloaded.state == TaskState.NEEDS_RECONCILIATION
    assert "irreversible" in reloaded.failure_reason.lower()
