"""Tests for Sentinel Data and Code Organs (Pillar 1)."""
import json
from pathlib import Path
import pytest

from sentinel_broker.tool_registry import ToolRegistry
from sentinel_broker.organs.data_organ import register_data_organs


def test_python_sandbox_run_success(tmp_path: Path):
    registry = ToolRegistry()
    register_data_organs(registry)

    target_file = tmp_path / "output.txt"
    script = f"""
with open(r"{target_file}", "w") as f:
    f.write("SANDBOX_SUCCESS\\n")
print("FINISHED")
"""
    res = registry.execute_tool("python_sandbox_run", {
        "script_code": script,
        "output_artifact_path": str(target_file),
    })

    assert res["exit_code"] == 0
    assert "FINISHED" in res["stdout"]
    assert res["artifact_exists"] is True
    assert target_file.read_text().strip() == "SANDBOX_SUCCESS"


def test_python_sandbox_run_timeout():
    registry = ToolRegistry()
    register_data_organs(registry)

    infinite_script = "import time\ntime.sleep(5)\n"
    res = registry.execute_tool("python_sandbox_run", {
        "script_code": infinite_script,
        "timeout_sec": 0.5,
    })

    assert res.get("exit_code") == -1
    assert "timed out" in res.get("error", "").lower()


def test_file_transform_csv_to_json(tmp_path: Path):
    registry = ToolRegistry()
    register_data_organs(registry)

    csv_file = tmp_path / "test.csv"
    csv_file.write_text("name,metric,val\nAlpha,CPU,85\nBeta,RAM,120\n", encoding="utf-8")
    json_file = tmp_path / "test.json"

    res = registry.execute_tool("file_transform", {
        "source_path": str(csv_file),
        "target_path": str(json_file),
        "format": "csv_to_json",
    })

    assert res["success"] is True
    data = json.loads(json_file.read_text(encoding="utf-8"))
    assert len(data) == 2
    assert data[0]["name"] == "Alpha"
    assert data[1]["val"] == "120"
