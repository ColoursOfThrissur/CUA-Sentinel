"""Tests for Objective Verification Gate (FR-024)."""
import pytest
from pathlib import Path
import tempfile
import shutil
import json

from sentinel_core.db import SentinelDB
from sentinel_core.verification_gate import VerificationGate


@pytest.fixture
def test_setup():
    temp_dir = Path(tempfile.mkdtemp())
    db_path = temp_dir / "test_verif.db"
    db = SentinelDB(db_path)
    gate = VerificationGate(db)
    yield db, gate, temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_file_exists_verification_pass_and_fail(test_setup):
    db, gate, temp_dir = test_setup
    
    # Missing file
    missing_file = temp_dir / "missing.obj"
    res1 = gate.verify_file_exists(missing_file)
    assert res1.passed is False
    assert res1.error_category == "MISSING_ARTIFACT"
    
    # Record mistake
    with db.transaction() as c:
        c.execute("INSERT INTO tasks (id, title, state, created_at, updated_at) VALUES ('t_verif', 'T', 'Running', 0, 0)")
    gate.record_mistake_if_failed("t_verif", "att_v1", res1)

    mistakes = db.execute_read("SELECT * FROM mistake_ledger WHERE task_id = 't_verif'")
    assert len(mistakes) == 1
    assert mistakes[0]["error_category"] == "MISSING_ARTIFACT"
    assert "missing.obj" in mistakes[0]["error_signature"]

    # Passing file
    valid_file = temp_dir / "output.obj"
    valid_file.write_text("v 0.0 0.0 0.0\nv 1.0 1.0 1.0\nf 1 2", encoding="utf-8")
    res2 = gate.verify_file_exists(valid_file, min_bytes=10)
    assert res2.passed is True


def test_json_schema_verification(test_setup):
    _, gate, _ = test_setup
    
    # Missing key
    bad_json = json.dumps({"status": "ok"})
    res1 = gate.verify_json_schema(bad_json, required_keys={"status", "artifact_path"})
    assert res1.passed is False
    assert res1.error_category == "MISSING_KEYS"

    # Good JSON
    good_json = json.dumps({"status": "ok", "artifact_path": "/tmp/out.png"})
    res2 = gate.verify_json_schema(good_json, required_keys={"status", "artifact_path"})
    assert res2.passed is True
