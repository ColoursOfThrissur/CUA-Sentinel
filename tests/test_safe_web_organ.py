"""Tests for Safe Web Organ & SSRF Defense Shield (R17, R19, R13)."""
import io
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock

from sentinel_core.db import SentinelDB
from sentinel_core.leases import LeaseManager
from sentinel_core.side_effects import SideEffectLedger, EffectClass
from sentinel_core.agent_registry import AgentRegistry, AgentManifest
from sentinel_broker.tool_registry import ToolRegistry
from sentinel_broker.pdp import PolicyDecisionPoint
from sentinel_broker.broker import ExecutionBroker
from sentinel_broker.safe_http import (
    SafeHTTPClient,
    SSRFViolationError,
    DomainAccessDeniedError,
)
from sentinel_broker.organs.web_organ import register_web_organs


@pytest.fixture
def test_db(tmp_path: Path):
    db_file = tmp_path / "test_web.db"
    return SentinelDB(str(db_file))


def test_ssrf_blocks_loopback_and_metadata_ips():
    client = SafeHTTPClient(allowed_domains=["*"])

    # 1. Loopback IPs
    with pytest.raises(SSRFViolationError) as exc_info:
        client.validate_url("http://127.0.0.1:8000/api/config")
    assert "loopback" in str(exc_info.value).lower()

    with pytest.raises(SSRFViolationError) as exc_info:
        client.validate_url("http://localhost:11434/api/tags")
    assert "loopback" in str(exc_info.value).lower()

    # 2. Cloud Metadata IP (169.254.169.254)
    with pytest.raises(SSRFViolationError) as exc_info:
        client.validate_url("http://169.254.169.254/latest/meta-data/")
    assert "link-local" in str(exc_info.value).lower() or "metadata" in str(exc_info.value).lower()

    # 3. Private RFC-1918 IPs
    with pytest.raises(SSRFViolationError) as exc_info:
        client.validate_url("http://192.168.1.1/admin")
    assert "private" in str(exc_info.value).lower()

    with pytest.raises(SSRFViolationError) as exc_info:
        client.validate_url("http://10.0.0.5:9000/metrics")
    assert "private" in str(exc_info.value).lower()


def test_domain_allowlist_enforcement():
    client = SafeHTTPClient(
        allowed_domains=["*.github.com", "api.weather.gov", "en.wikipedia.org"],
        block_private_ips=False,  # Test domain gate independently
    )

    # Allowed domains
    scheme, host, port = client.validate_url("https://api.github.com/repos/google/gemini")
    assert host == "api.github.com"

    scheme, host, port = client.validate_url("https://api.weather.gov/points/39.7456,-97.0892")
    assert host == "api.weather.gov"

    # Disallowed domains
    with pytest.raises(DomainAccessDeniedError) as exc_info:
        client.validate_url("https://malicious-exfiltration.xyz/leak")
    assert "not in the Sentinel network egress allowlist" in str(exc_info.value)

    with pytest.raises(DomainAccessDeniedError) as exc_info:
        client.validate_url("https://internal.corp/admin")
    assert "not in the Sentinel network egress allowlist" in str(exc_info.value)


def test_pdp_egress_and_capability_enforcement(test_db):
    leases = LeaseManager(test_db)
    tool_reg = ToolRegistry()
    agent_reg = AgentRegistry(test_db)
    ledger = SideEffectLedger(test_db)

    allowed_domains = ["*.github.com", "api.weather.gov"]
    register_web_organs(tool_reg, allowed_domains=allowed_domains, ledger=ledger)

    pdp = PolicyDecisionPoint(
        leases=leases,
        tool_registry=tool_reg,
        agent_registry=agent_reg,
        allowed_domains=allowed_domains,
    )

    # Register an agent with NO web organ permission
    restricted_manifest = AgentManifest(
        agent_id="local_worker",
        name="Local Worker",
        version="1.0.0",
        description="Local processing worker",
        author="Sentinel Team",
        capabilities=["local:process"],
        allowed_organs=["python_sandbox_run"],
    )
    agent_reg.register_draft(restricted_manifest)
    agent_reg.publish_release("local_worker", "1.0.0")

    # Register an agent WITH web organ permission
    web_manifest = AgentManifest(
        agent_id="researcher",
        name="Research Agent",
        version="1.0.0",
        description="Web research agent",
        author="Sentinel Team",
        capabilities=["web:research"],
        allowed_organs=["broker_http_get"],
    )
    agent_reg.register_draft(web_manifest)
    agent_reg.publish_release("researcher", "1.0.0")

    # Setup attempt lease
    with test_db.transaction() as cur:
        cur.execute(
            "INSERT INTO tasks (id, title, state, created_at, updated_at) VALUES ('task_w1', 'web test', 'Running', 0, 0)"
        )
    lease_rec = leases.allocate_next_lease("task_w1", 1)

    # 1. Restricted agent attempts web get -> Gate A denies capability
    dec1 = pdp.evaluate(
        attempt_id=lease_rec.attempt_id,
        lease_token=lease_rec.lease_token,
        tool_name="broker_http_get",
        params={"url": "https://api.github.com/status"},
        context={"agent_id": "local_worker"},
    )
    assert dec1.allowed is False
    assert dec1.status_code == "REJECTED_CAPABILITY_NOT_GRANTED"

    # 2. Authorized agent requests DISALLOWED domain -> PDP denies egress
    dec2 = pdp.evaluate(
        attempt_id=lease_rec.attempt_id,
        lease_token=lease_rec.lease_token,
        tool_name="broker_http_get",
        params={"url": "https://evil-data.com/api"},
        context={"agent_id": "researcher"},
    )
    assert dec2.allowed is False
    assert dec2.status_code == "REJECTED_DOMAIN_NOT_ALLOWED"

    # 3. Authorized agent requests ALLOWED domain -> PDP approves
    dec3 = pdp.evaluate(
        attempt_id=lease_rec.attempt_id,
        lease_token=lease_rec.lease_token,
        tool_name="broker_http_get",
        params={"url": "https://api.github.com/status"},
        context={"agent_id": "researcher"},
    )
    assert dec3.allowed is True
    assert dec3.status_code == "APPROVED"


def test_broker_http_get_execution_and_side_effects(test_db):
    leases = LeaseManager(test_db)
    tool_reg = ToolRegistry()
    agent_reg = AgentRegistry(test_db)
    ledger = SideEffectLedger(test_db)

    allowed_domains = ["*.github.com"]
    register_web_organs(
        tool_reg,
        allowed_domains=allowed_domains,
        block_private_ips=False,  # Mock network call
        ledger=ledger,
    )
    pdp = PolicyDecisionPoint(leases, tool_reg, agent_reg, allowed_domains=allowed_domains)
    broker = ExecutionBroker(pdp, tool_reg, ledger)

    manifest = AgentManifest(
        agent_id="data_analyst",
        name="Data Analyst",
        version="1.0.0",
        description="Analyst",
        author="Sentinel Team",
        capabilities=["data"],
        allowed_organs=["broker_http_get"],
    )
    agent_reg.register_draft(manifest)
    agent_reg.publish_release("data_analyst", "1.0.0")

    with test_db.transaction() as cur:
        cur.execute(
            "INSERT INTO tasks (id, title, state, created_at, updated_at) VALUES ('task_w2', 'web test', 'Running', 0, 0)"
        )
    lease_rec = leases.allocate_next_lease("task_w2", 1)

    # Mock urllib response
    mock_headers = MagicMock()
    mock_headers.items.return_value = [("Content-Type", "application/json")]
    mock_headers.get.return_value = "application/json"
    mock_headers.get_content_charset.return_value = "utf-8"

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.headers = mock_headers
    mock_resp.read.side_effect = [b'{"sentinel_status": "ONLINE"}', b""]

    with patch("urllib.request.build_opener") as mock_opener_cls:
        mock_opener = MagicMock()
        mock_opener.open.return_value.__enter__.return_value = mock_resp
        mock_opener_cls.return_value = mock_opener

        call_res = broker.dispatch_call(
            attempt_id=lease_rec.attempt_id,
            lease_token=lease_rec.lease_token,
            tool_name="broker_http_get",
            params={"url": "https://api.github.com/zen"},
            context={"agent_id": "data_analyst", "task_id": "task_w2"},
        )

    assert call_res["allowed"] is True
    result = call_res["result"]
    assert result["success"] is True
    assert result["status_code"] == 200
    assert '{"sentinel_status": "ONLINE"}' in result["body"]

    # Verify side effect was recorded in ledger
    records = ledger.get_attempt_effects(lease_rec.attempt_id)
    assert len(records) >= 1
    assert records[0]["tool_name"] == "broker_http_get"
    assert records[0]["effect_class"] == EffectClass.READ_ONLY.value
