"""Tests for Side-Effect Ledger (AT-B-08, AT-B-09)."""
import pytest
from pathlib import Path
import tempfile
import shutil

from sentinel_core.db import SentinelDB
from sentinel_core.side_effects import SideEffectLedger, EffectClass


@pytest.fixture
def test_db():
    temp_dir = Path(tempfile.mkdtemp())
    db_path = temp_dir / "test_effects.db"
    db = SentinelDB(db_path)
    yield db
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_intent_before_outcome_after_cycle(test_db):
    ledger = SideEffectLedger(test_db)
    
    # Create fake attempt
    with test_db.transaction() as c:
        c.execute("INSERT INTO tasks (id, title, state, created_at, updated_at) VALUES ('t1', 'T', 'Running', 0, 0)")
        c.execute("INSERT INTO attempts (id, task_id, attempt_number, lease_token, status, started_at) VALUES ('att_1', 't1', 1, 1, 'Active', 0)")

    # 1. Log Intent BEFORE execution
    ledger_id = ledger.record_intent(
        attempt_id="att_1",
        tool_name="write_file",
        effect_class=EffectClass.NON_IDEMPOTENT_WRITE,
        intent_payload={"path": "out.txt", "content": "hello world"},
    )
    assert ledger_id > 0

    # Verify intent recorded and unresolved
    unresolved = ledger.get_unresolved_intents("att_1")
    assert len(unresolved) == 1
    assert unresolved[0]["status"] == "INTENT_RECORDED"

    # 2. Log Outcome AFTER execution
    ledger.record_outcome(
        ledger_id=ledger_id,
        outcome_payload={"bytes_written": 11, "checksum": "abc1234"},
        success=True,
    )

    # Verify resolved
    unresolved_after = ledger.get_unresolved_intents("att_1")
    assert len(unresolved_after) == 0

    effects = ledger.get_attempt_effects("att_1")
    assert len(effects) == 1
    assert effects[0]["status"] == "OUTCOME_RECORDED"
    assert "abc1234" in effects[0]["outcome_payload"]
