"""Tests for Execution Broker, Dynamic Tool Registry, and PDP (CD-01, CD-06)."""
import pytest
from pathlib import Path
import tempfile
import shutil

from sentinel_core.db import SentinelDB
from sentinel_core.leases import LeaseManager
from sentinel_core.side_effects import SideEffectLedger, EffectClass
from sentinel_broker.tool_registry import ToolRegistry
from sentinel_broker.pdp import PolicyDecisionPoint
from sentinel_broker.broker import ExecutionBroker


@pytest.fixture
def broker_setup():
    temp_dir = Path(tempfile.mkdtemp())
    db = SentinelDB(temp_dir / "test_broker.db")
    leases = LeaseManager(db)
    side_effects = SideEffectLedger(db)
    registry = ToolRegistry()
    pdp = PolicyDecisionPoint(leases, registry)
    broker = ExecutionBroker(pdp, registry, side_effects)

    # Register sample tools
    @registry.register("calculate_area", "Calculates rectangle area", EffectClass.READ_ONLY)
    def calc_area(params, ctx):
        return {"area": params["w"] * params["h"]}

    @registry.register("danger_delete", "Deletes database", EffectClass.IRREVERSIBLE)
    def danger(params, ctx):
        return {"deleted": True}

    yield db, leases, broker, temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_broker_authorized_tool_execution(broker_setup):
    db, leases, broker, _ = broker_setup

    # Allocate attempt
    with db.transaction() as c:
        c.execute("INSERT INTO tasks (id, title, state, created_at, updated_at) VALUES ('t_b1', 'T', 'Running', 0, 0)")
    lease = leases.allocate_next_lease("t_b1", 1)

    # Dispatch tool call
    res = broker.dispatch_call(
        attempt_id=lease.attempt_id,
        lease_token=lease.lease_token,
        tool_name="calculate_area",
        params={"w": 5, "h": 10},
    )

    assert res["status"] == "SUCCESS"
    assert res["result"]["area"] == 50

    # Verify side effect ledger
    effects = db.execute_read("SELECT * FROM side_effect_ledger WHERE attempt_id = ?", (lease.attempt_id,))
    assert len(effects) == 1
    assert effects[0]["tool_name"] == "calculate_area"
    assert effects[0]["status"] == "OUTCOME_RECORDED"


def test_broker_rejects_stale_lease(broker_setup):
    _, _, broker, _ = broker_setup

    res = broker.dispatch_call(
        attempt_id="fake_attempt",
        lease_token=999,
        tool_name="calculate_area",
        params={"w": 2, "h": 2},
    )

    assert res["allowed"] is False
    assert res["status"] == "REJECTED_STALE_LEASE"


def test_broker_rejects_unauthorized_irreversible_tool(broker_setup):
    db, leases, broker, _ = broker_setup

    with db.transaction() as c:
        c.execute("INSERT INTO tasks (id, title, state, created_at, updated_at) VALUES ('t_b2', 'T', 'Running', 0, 0)")
    lease = leases.allocate_next_lease("t_b2", 1)

    # Without allow_irreversible
    res1 = broker.dispatch_call(
        attempt_id=lease.attempt_id,
        lease_token=lease.lease_token,
        tool_name="danger_delete",
        params={},
    )
    assert res1["allowed"] is False
    assert res1["status"] == "REJECTED_IRREVERSIBLE_DENIED"

    # With allow_irreversible clearance
    res2 = broker.dispatch_call(
        attempt_id=lease.attempt_id,
        lease_token=lease.lease_token,
        tool_name="danger_delete",
        params={},
        context={"allow_irreversible": True},
    )
    assert res2["allowed"] is True
    assert res2["status"] == "SUCCESS"
