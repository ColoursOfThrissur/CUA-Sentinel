"""Tests for Monotonic Lease Fencing (AT-B-10)."""
import pytest
from pathlib import Path
import tempfile
import shutil

from sentinel_core.db import SentinelDB
from sentinel_core.state_machine import StateMachine, StaleLeaseError


@pytest.fixture
def test_db():
    temp_dir = Path(tempfile.mkdtemp())
    db_path = temp_dir / "test_leases.db"
    db = SentinelDB(db_path)
    yield db
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_monotonic_lease_increment_and_fencing(test_db):
    sm = StateMachine(test_db)
    sm.create_task("task_fence", "Fencing Test", max_attempts=3)

    # Attempt 1
    _, lease1 = sm.start_next_attempt("task_fence")
    assert lease1.lease_token == 1

    # Transition Attempt 1 to Verifying fails, then start Attempt 2
    sm.transition_to_verifying("task_fence", lease1.attempt_id, lease1.lease_token)
    sm.handle_verification_failure("task_fence", lease1.attempt_id, lease1.lease_token, "First attempt failed")

    # Attempt 2 allocated
    _, lease2 = sm.start_next_attempt("task_fence")
    assert lease2.lease_token == 2
    assert lease2.lease_token > lease1.lease_token

    # Zombie Attempt 1 attempts to commit or transition -> MUST BE REJECTED (Fenced Out)
    with pytest.raises(StaleLeaseError):
        sm.commit_success("task_fence", lease1.attempt_id, lease1.lease_token)

    # Active Attempt 2 transitions cleanly
    sm.transition_to_verifying("task_fence", lease2.attempt_id, lease2.lease_token)
    task = sm.commit_success("task_fence", lease2.attempt_id, lease2.lease_token)
    assert task.state.value == "Succeeded"
