"""Tests for Gate A Agent Registration Lifecycle (AT-A-01 to AT-A-06)."""
from pathlib import Path
import pytest

from sentinel_core.db import SentinelDB
from sentinel_core.leases import LeaseManager
from sentinel_core.side_effects import EffectClass
from sentinel_broker.tool_registry import ToolRegistry
from sentinel_broker.pdp import PolicyDecisionPoint
from sentinel_core.agent_registry import (
    AgentRegistry,
    AgentManifest,
    AgentState,
    AgentLifecycleError,
    compute_provenance_hash,
)


@pytest.fixture
def test_db(tmp_path: Path):
    db_file = tmp_path / "test_agents.db"
    return SentinelDB(str(db_file))


def test_agent_manifest_registration_and_provenance(test_db):
    reg = AgentRegistry(test_db)

    manifest = AgentManifest(
        agent_id="data_analyst",
        name="Data Analysis Specialist",
        version="1.0.0",
        description="Analyzes CSVs and generates reports",
        author="Sentinel Team",
        capabilities=["data:csv", "data:report"],
        allowed_organs=["python_sandbox_run", "csv_analyze_and_report"],
        denied_tools=["mouse_action", "keyboard_action"],
    )

    # 1. Register Draft (AT-A-01)
    registered = reg.register_draft(manifest)
    assert registered.agent_id == "data_analyst"

    rec = reg.get_agent_record("data_analyst")
    assert rec["status"] == AgentState.DRAFT.value

    # 2. Provenance Hash Determinism (AT-A-02)
    hash1 = compute_provenance_hash(manifest, code_payload="print('hello')")
    hash2 = compute_provenance_hash(manifest, code_payload="print('hello')")
    assert hash1 == hash2
    assert len(hash1) == 64


def test_immutable_release_snapshots_and_lifecycle(test_db):
    reg = AgentRegistry(test_db)

    manifest = AgentManifest(
        agent_id="blender_artist",
        name="3D Modeling Artisan",
        version="1.0.0",
        allowed_organs=["blender_run_python", "blender_launch_gui"],
    )
    reg.register_draft(manifest)

    # Publish Release v1.0.0 (AT-A-03, AT-A-04)
    rel = reg.publish_release(
        agent_id="blender_artist",
        version="1.0.0",
        code_payload="# Blender 4.5 Worker v1",
        publisher="derik",
    )
    assert rel.version == "1.0.0"
    assert rel.provenance_hash is not None

    agent_rec = reg.get_agent_record("blender_artist")
    assert agent_rec["status"] == AgentState.PUBLISHED.value
    assert agent_rec["current_version"] == "1.0.0"

    # AT-A-03: Attempting to overwrite existing release must raise error
    with pytest.raises(AgentLifecycleError, match="already exists and is immutable"):
        reg.publish_release("blender_artist", "1.0.0", code_payload="overwritten")

    # Publishing a new version v1.1.0 succeeds
    rel2 = reg.publish_release("blender_artist", "1.1.0", code_payload="# Blender Worker v2")
    assert rel2.version == "1.1.0"


def test_pdp_capability_enforcement_at_a_05(test_db):
    reg = AgentRegistry(test_db)
    leases = LeaseManager(test_db)
    tools = ToolRegistry()

    # Register tools
    @tools.register("csv_analyze_and_report", "CSV Tool", EffectClass.NON_IDEMPOTENT_WRITE)
    def dummy_csv(p, c): return {}

    @tools.register("blender_run_python", "Blender Tool", EffectClass.NON_IDEMPOTENT_WRITE)
    def dummy_blender(p, c): return {}

    pdp = PolicyDecisionPoint(leases, tools, agent_registry=reg)

    # Create dummy active lease
    with test_db.transaction() as c:
        c.execute("INSERT INTO tasks (id, title, state, created_at, updated_at) VALUES ('t1', 'Task', 'Running', 0, 0)")
        c.execute("INSERT INTO attempts (id, task_id, attempt_number, lease_token, status, started_at) VALUES ('att1', 't1', 1, 100, 'Active', 0)")

    # 1. Register and Publish data_analyst with only CSV capabilities
    manifest = AgentManifest(
        agent_id="data_analyst",
        name="Data Analyst",
        version="1.0.0",
        allowed_organs=["csv_analyze_and_report"],
        denied_tools=["blender_run_python"],
    )
    reg.register_draft(manifest)
    reg.publish_release("data_analyst", "1.0.0")

    # 2. Invoke allowed tool -> APPROVED
    dec1 = pdp.evaluate(
        attempt_id="att1",
        lease_token=100,
        tool_name="csv_analyze_and_report",
        params={},
        context={"agent_id": "data_analyst"},
    )
    assert dec1.allowed is True
    assert dec1.status_code == "APPROVED"

    # 3. Invoke unauthorized tool (AT-A-05) -> REJECTED_CAPABILITY_NOT_GRANTED
    dec2 = pdp.evaluate(
        attempt_id="att1",
        lease_token=100,
        tool_name="blender_run_python",
        params={},
        context={"agent_id": "data_analyst"},
    )
    assert dec2.allowed is False
    assert dec2.status_code == "REJECTED_CAPABILITY_NOT_GRANTED"
    assert "not in allowed_organs" in dec2.reason or "explicitly denied" in dec2.reason
