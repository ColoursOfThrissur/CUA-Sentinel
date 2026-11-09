"""Tests for Sentinel Core State Machine & Atomic Commits (AT-B-03 to AT-B-06, AT-D-08)."""
import pytest
from pathlib import Path
import tempfile
import shutil

from sentinel_core.db import SentinelDB
from sentinel_core.state_machine import StateMachine, TaskState, InvalidTransitionError, StaleLeaseError


@pytest.fixture
def test_db():
    temp_dir = Path(tempfile.mkdtemp())
    db_path = temp_dir / "test_core.db"
    db = SentinelDB(db_path)
    yield db
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_task_creation_and_lifecycle(test_db):
    sm = StateMachine(test_db)
    task = sm.create_task("task_001", "Build 3D Model", "Generate obj asset", max_attempts=3)
    assert task.id == "task_001"
    assert task.state == TaskState.QUEUED
    assert task.attempt_count == 0

    # Start Attempt 1
    task, lease1 = sm.start_next_attempt("task_001")
    assert task.state == TaskState.RUNNING
    assert task.attempt_count == 1
    assert lease1.lease_token >= 1

    # Transition to Verifying
    task = sm.transition_to_verifying("task_001", lease1.attempt_id, lease1.lease_token)
    assert task.state == TaskState.VERIFYING

    # Commit Success (Atomic)
    task = sm.commit_success("task_001", lease1.attempt_id, lease1.lease_token)
    assert task.state == TaskState.SUCCEEDED


def test_illegal_transition_rejection(test_db):
    sm = StateMachine(test_db)
    task = sm.create_task("task_002", "Invalid Transition Task")
    task, lease = sm.start_next_attempt("task_002")
    assert task.state == TaskState.RUNNING
    
    # Direct jump from Running to Succeeded (bypassing Verifying) must fail
    with pytest.raises(InvalidTransitionError):
        sm.commit_success("task_002", lease.attempt_id, lease.lease_token)


def test_retry_on_verification_failure(test_db):
    sm = StateMachine(test_db)
    task = sm.create_task("task_003", "Retry Task", max_attempts=2)

    # Attempt 1
    task, lease1 = sm.start_next_attempt("task_003")
    sm.transition_to_verifying("task_003", lease1.attempt_id, lease1.lease_token)
    task, can_retry = sm.handle_verification_failure("task_003", lease1.attempt_id, lease1.lease_token, "Missing file")
    assert can_retry is True
    assert task.state == TaskState.VERIFYING

    # Attempt 2 (Retry)
    task, lease2 = sm.start_next_attempt("task_003")
    assert task.attempt_count == 2
    assert lease2.lease_token > lease1.lease_token
    sm.transition_to_verifying("task_003", lease2.attempt_id, lease2.lease_token)

    # Attempt 2 fails -> max attempts reached
    task, can_retry = sm.handle_verification_failure("task_003", lease2.attempt_id, lease2.lease_token, "Still missing")
    assert can_retry is False
    assert task.state == TaskState.FAILED
    assert "Still missing" in task.failure_reason
