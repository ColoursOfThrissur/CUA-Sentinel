import os
import pytest
from pathlib import Path

from sentinel_core.db import SentinelDB
from sentinel_core.leases import LeaseManager
from sentinel_broker.tool_registry import ToolRegistry
from sentinel_broker.pdp import PolicyDecisionPoint
from sentinel_broker.organs.sensory import register_sensory_organs
from sentinel_broker.organs.motor import register_motor_organs
from sentinel_core.side_effects import EffectClass


@pytest.fixture
def test_setup(tmp_path):
    db = SentinelDB(tmp_path / "test.db")
    leases = LeaseManager(db)
    registry = ToolRegistry()
    register_sensory_organs(registry)
    register_motor_organs(registry)

    workspace_dir = tmp_path / "Sentinel_Workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)

    pdp = PolicyDecisionPoint(
        leases=leases,
        tool_registry=registry,
        allowed_workspaces_dir=workspace_dir,
    )
    return leases, registry, pdp, workspace_dir, db


def test_system_filesystem_inspect_tool_registered(test_setup):
    _, registry, _, _, _ = test_setup
    tool = registry.get_tool("system_filesystem_inspect")
    assert tool is not None
    assert tool.effect_class == EffectClass.READ_ONLY
    assert "mode" in tool.parameters_schema


def test_system_filesystem_inspect_list_drives(test_setup):
    _, registry, _, _, _ = test_setup
    res = registry.execute_tool("system_filesystem_inspect", {"mode": "list_drives"})
    assert res.get("success") is True
    assert "drives" in res
    assert len(res["drives"]) >= 1

    # Check for C:\ partition
    c_drive = next((d for d in res["drives"] if d.get("drive", "").upper().startswith("C")), None)
    assert c_drive is not None
    assert c_drive["total_gb"] > 0
    assert c_drive["free_gb"] > 0


def test_system_filesystem_inspect_largest_folders(test_setup):
    _, registry, _, _, _ = test_setup
    res = registry.execute_tool(
        "system_filesystem_inspect",
        {"mode": "largest_folders", "path": "G:\\", "limit": 5},
    )
    assert res.get("success") is True
    assert "top_folders" in res
    assert len(res["top_folders"]) > 0
    # Folders must be sorted descending by size
    sizes = [f["size_bytes"] for f in res["top_folders"]]
    assert sizes == sorted(sizes, reverse=True)


def test_system_filesystem_inspect_largest_files_downloads(test_setup):
    _, registry, _, _, _ = test_setup
    res = registry.execute_tool(
        "system_filesystem_inspect",
        {"mode": "largest_files", "path": "downloads", "limit": 5},
    )
    assert res.get("success") is True
    assert "top_files" in res
    assert len(res["top_files"]) > 0
    # Files must be sorted descending by size
    sizes = [f["size_bytes"] for f in res["top_files"]]
    assert sizes == sorted(sizes, reverse=True)
    # Check that paths resolved to Downloads
    assert any("downloads" in f["path"].lower() for f in res["top_files"])


def test_system_filesystem_inspect_find(test_setup):
    _, registry, _, _, _ = test_setup
    res = registry.execute_tool(
        "system_filesystem_inspect",
        {"mode": "find", "path": "G:\\", "pattern": "*games*", "limit": 10},
    )
    assert res.get("success") is True
    assert "matches" in res
    # Should find G:\Games
    paths = [m["path"].lower() for m in res["matches"]]
    assert any("games" in p for p in paths)


def test_system_filesystem_inspect_read_file(test_setup, tmp_path):
    _, registry, _, _, _ = test_setup
    sample_file = tmp_path / "sample.txt"
    sample_file.write_text("Sentinel Ground Truth Filesystem Inspection Content", encoding="utf-8")

    res = registry.execute_tool(
        "system_filesystem_inspect",
        {"mode": "read_file", "path": str(sample_file)},
    )
    assert res.get("success") is True
    assert "preview" in res
    assert "Sentinel Ground Truth" in res["preview"]


def test_pdp_allows_sensory_read_across_system(test_setup):
    leases, _, pdp, _, db = test_setup
    import time
    with db.transaction() as c:
        c.execute(
            "INSERT INTO tasks (id, title, state, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("task_read", "read test", "Running", time.time(), time.time()),
        )
    lease_rec = leases.allocate_next_lease("task_read", 1)

    # Reading system drive path with read-only sensory tool is allowed
    decision = pdp.evaluate(
        attempt_id=lease_rec.attempt_id,
        lease_token=lease_rec.lease_token,
        tool_name="system_filesystem_inspect",
        params={"mode": "list_drives", "path": "C:\\"},
    )
    assert decision.allowed is True
    assert decision.status_code == "APPROVED"


def test_pdp_enforces_workspace_write_boundary(test_setup):
    leases, registry, pdp, workspace_dir, db = test_setup
    import time
    with db.transaction() as c:
        c.execute(
            "INSERT INTO tasks (id, title, state, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("task_write", "write test", "Running", time.time(), time.time()),
        )
    lease_rec = leases.allocate_next_lease("task_write", 1)

    # Register a mock write tool
    @registry.register(
        name="mock_file_writer",
        description="Writes a file",
        effect_class=EffectClass.IDEMPOTENT_WRITE,
        parameters_schema={"output_path": "str"},
    )
    def mock_file_writer(params, ctx):
        return {"written": True}

    # 1. Allowed write inside workspace
    valid_path = str(workspace_dir / "report.md")
    decision_allowed = pdp.evaluate(
        attempt_id=lease_rec.attempt_id,
        lease_token=lease_rec.lease_token,
        tool_name="mock_file_writer",
        params={"output_path": valid_path},
    )
    assert decision_allowed.allowed is True
    assert decision_allowed.status_code == "APPROVED"

    # 2. Rejected write outside workspace (e.g. C:\Windows or C:\bad.txt)
    invalid_path = "C:\\Windows\\System32\\unauthorized.txt"
    decision_denied = pdp.evaluate(
        attempt_id=lease_rec.attempt_id,
        lease_token=lease_rec.lease_token,
        tool_name="mock_file_writer",
        params={"output_path": invalid_path},
    )
    assert decision_denied.allowed is False
    assert decision_denied.status_code == "REJECTED_WRITE_OUTSIDE_WORKSPACE"
    assert "resolves outside permitted workspace" in decision_denied.reason
