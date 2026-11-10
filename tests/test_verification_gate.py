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


def test_verify_python_code(test_setup):
    _, gate, temp_dir = test_setup

    # Valid complete script
    good_py = temp_dir / "valid_cache.py"
    good_py.write_text(
        "class LRUCache:\n"
        "    def __init__(self, capacity: int):\n"
        "        self.cap = capacity\n"
        "        self.data = {}\n"
        "    def get(self, key):\n"
        "        return self.data.get(key, -1)\n"
        "    def put(self, key, value):\n"
        "        self.data[key] = value\n",
        encoding="utf-8"
    )
    res_good = gate.verify_python_code(good_py, required_symbols=["LRUCache", "get", "put"])
    assert res_good.passed is True
    assert res_good.details["ast_nodes"] >= 1

    # Truncated script (SyntaxError)
    bad_syntax_py = temp_dir / "truncated.py"
    bad_syntax_py.write_text(
        "class LRUCache:\n"
        "    def __init__(self, capacity: int):\n"
        "        self.cap = capacity\n"
        "    def get(self, key):\n"
        "        # abruptly cut off here...",
        encoding="utf-8"
    )
    # The above is valid syntax (a comment), but if cut mid-expression:
    bad_syntax_py.write_text(
        "class LRUCache:\n"
        "    def __init__(self, capacity: int):\n"
        "        self.cap = capacity\n"
        "    def get(self, key):\n"
        "        if key in self.",  # unexpected EOF
        encoding="utf-8"
    )
    res_bad_syntax = gate.verify_python_code(bad_syntax_py)
    assert res_bad_syntax.passed is False
    assert res_bad_syntax.error_category == "SYNTAX_ERROR"
    assert "SyntaxError" in res_bad_syntax.error_signature

    # Missing required symbols
    missing_sym_py = temp_dir / "missing_sym.py"
    missing_sym_py.write_text(
        "class PartialCache:\n"
        "    def get(self, key):\n"
        "        return None\n",
        encoding="utf-8"
    )
    res_missing = gate.verify_python_code(missing_sym_py, required_symbols=["LRUCache", "put"])
    assert res_missing.passed is False
    assert res_missing.error_category == "INCOMPLETE_CODE"
    assert "LRUCache" in res_missing.details["missing_symbols"]
    assert "put" in res_missing.details["missing_symbols"]

    # Runtime error script (e.g., KeyError or unhandled exception during test execution)
    runtime_err_py = temp_dir / "runtime_err.py"
    runtime_err_py.write_text(
        "class Broken:\n"
        "    def run(self):\n"
        "        raise KeyError('Simulated key failure')\n"
        "if __name__ == '__main__':\n"
        "    Broken().run()\n",
        encoding="utf-8"
    )
    res_runtime = gate.verify_python_code(runtime_err_py, test_execution=True)
    assert res_runtime.passed is False
    assert res_runtime.error_category == "RUNTIME_ERROR"
    assert "KeyError" in res_runtime.error_signature
    assert "Simulated key failure" in res_runtime.details["stderr"]

    # Contract harness test: valid vs broken eviction logic
    buggy_lru_py = temp_dir / "buggy_lru.py"
    buggy_lru_py.write_text(
        "class LRUCache:\n"
        "    def __init__(self, cap):\n"
        "        self.cap = cap\n"
        "        self.items = {}\n"
        "    def get(self, k):\n"
        "        return self.items.get(k, -1)\n"
        "    def put(self, k, v):\n"
        "        # Never evicts!\n"
        "        self.items[k] = v\n",
        encoding="utf-8"
    )
    harness = (
        "c = target_module.LRUCache(2)\n"
        "c.put(1, 10)\n"
        "c.put(2, 20)\n"
        "c.put(3, 30)\n"
        "assert c.get(1) == -1, 'LRU item 1 was not evicted!'\n"
    )
    res_contract = gate.verify_python_code(buggy_lru_py, contract_harness=harness)
    assert res_contract.passed is False
    assert res_contract.error_category == "CONTRACT_TEST_FAILED"
    assert "AssertionError" in res_contract.error_signature


def test_verify_obj_geometry(test_setup):
    _, gate, temp_dir = test_setup

    # Valid 3D cube mesh (8 vertices, 6 faces) - adjusted min_vertices to 8
    cube_obj = temp_dir / "cube.obj"
    cube_content = (
        "v -1.0 -1.0 -1.0\n"
        "v 1.0 -1.0 -1.0\n"
        "v 1.0 1.0 -1.0\n"
        "v -1.0 1.0 -1.0\n"
        "v -1.0 -1.0 1.0\n"
        "v 1.0 -1.0 1.0\n"
        "v 1.0 1.0 1.0\n"
        "v -1.0 1.0 1.0\n"
        "v 0.0 0.0 2.0\n"
        "v 0.0 0.0 -2.0\n"
        "f 1 2 3 4\n"
        "f 5 6 7 8\n"
        "f 1 2 6 5\n"
        "f 2 3 7 6\n"
        "f 3 4 8 7\n"
        "f 4 1 5 8\n"
    )
    cube_obj.write_text(cube_content, encoding="utf-8")
    res_cube = gate.verify_obj_geometry(cube_obj, min_vertices=8, min_faces=5)
    assert res_cube.passed is True
    assert res_cube.details["vertices"] == 10
    assert res_cube.details["faces"] == 6
    assert res_cube.details["bbox_size"][0] > 0

    # Degenerate mesh (insufficient vertices)
    degen_obj = temp_dir / "degen.obj"
    degen_obj.write_text(
        "# Degenerate mesh with only 3 vertices and 1 face\n"
        "v 0.0 0.0 0.0\n"
        "v 1.0 1.0 1.0\n"
        "v 2.0 2.0 2.0\n"
        "f 1 2 3\n",
        encoding="utf-8"
    )
    res_degen = gate.verify_obj_geometry(degen_obj, min_vertices=10)
    assert res_degen.passed is False
    assert res_degen.error_category == "DEGENERATE_GEOMETRY"

    # Zero-volume mesh (all vertices on the exact same coordinate)
    flat_obj = temp_dir / "flat.obj"
    flat_lines = ["v 0.0 0.0 0.0\n"] * 12 + ["f 1 2 3\n"] * 6
    flat_obj.write_text("".join(flat_lines), encoding="utf-8")
    res_flat = gate.verify_obj_geometry(flat_obj, min_vertices=5, min_faces=3)
    assert res_flat.passed is False
    assert res_flat.error_category == "ZERO_VOLUME_GEOMETRY"


def test_verify_csv_structure(test_setup):
    _, gate, temp_dir = test_setup

    good_csv = temp_dir / "valid.csv"
    good_csv.write_text("id,name,value\n1,alpha,42\n2,beta,99\n", encoding="utf-8")
    res_csv = gate.verify_csv_structure(good_csv, min_rows=2, min_cols=3)
    assert res_csv.passed is True
    assert res_csv.details["rows"] == 3
    assert res_csv.details["cols"] == 3

    # Insufficient rows
    bad_rows_csv = temp_dir / "one_row.csv"
    bad_rows_csv.write_text("id,name,value\n", encoding="utf-8")
    res_rows = gate.verify_csv_structure(bad_rows_csv, min_rows=2)
    assert res_rows.passed is False
    assert res_rows.error_category == "INSUFFICIENT_DATA"


def test_verify_markdown_report(test_setup):
    _, gate, temp_dir = test_setup

    good_md = temp_dir / "report.md"
    good_md.write_text(
        "# Executive Summary\n\n"
        "This is an in-depth security and isolation analysis of the Sentinel runtime.\n"
        "The AppContainer sandbox strictly fences filesystem mutations and network sockets.\n"
        "Policy Decision Point (PDP) enforces capability boundaries dynamically.\n"
        "All worker mutations are journaled to SQLite WAL under monotonic lease fencing.\n"
        "Verification gates confirm AST validity, symbol presence, and geometric bounding box.\n",
        encoding="utf-8"
    )
    res_md = gate.verify_markdown_report(good_md, min_words=30)
    assert res_md.passed is True

    # Missing headings
    no_head_md = temp_dir / "no_heading.md"
    no_head_md.write_text("Just plain words repeated without markdown structural headings. " * 10, encoding="utf-8")
    res_no_head = gate.verify_markdown_report(no_head_md, min_words=20)
    assert res_no_head.passed is False
    assert res_no_head.error_category == "MISSING_STRUCTURE"
