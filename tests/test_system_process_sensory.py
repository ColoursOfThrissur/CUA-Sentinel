"""Tests for System Process & RAM Sensory Organ."""
import pytest
from sentinel_broker.tool_registry import ToolRegistry
from sentinel_broker.organs.sensory import register_sensory_organs


def test_system_process_inspect_top_ram():
    registry = ToolRegistry()
    register_sensory_organs(registry)

    res = registry.execute_tool(
        "system_process_inspect",
        {"mode": "top_ram", "limit": 10},
        {"task_id": "t1", "attempt_id": "a1"},
    )
    assert res["success"] is True
    assert res["mode"] == "top_ram"
    assert "system" in res
    assert res["system"]["total_ram_mb"] > 0
    assert res["system"]["available_ram_mb"] > 0
    assert len(res["processes"]) > 0

    # Ensure processes are sorted descending by memory_mb
    mems = [p["memory_mb"] for p in res["processes"]]
    assert mems == sorted(mems, reverse=True)


def test_system_process_inspect_top_cpu():
    registry = ToolRegistry()
    register_sensory_organs(registry)

    res = registry.execute_tool(
        "system_process_inspect",
        {"mode": "top_cpu", "limit": 5},
        {"task_id": "t1", "attempt_id": "a1"},
    )
    assert res["success"] is True
    assert res["mode"] == "top_cpu"
    assert len(res["processes"]) <= 5


def test_system_process_inspect_summary():
    registry = ToolRegistry()
    register_sensory_organs(registry)

    res = registry.execute_tool(
        "system_process_inspect",
        {"mode": "summary"},
        {"task_id": "t1", "attempt_id": "a1"},
    )
    assert res["success"] is True
    assert "total_ram_mb" in res["system"]
    assert "available_ram_mb" in res["system"]
    assert "used_ram_percent" in res["system"]
