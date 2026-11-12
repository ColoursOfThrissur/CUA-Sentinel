"""Tests for Sentinel Hybrid Model Gateway and Rule R14 / AT-C-10 Privacy Fence."""
import pytest
from unittest.mock import MagicMock, patch

from sentinel_core.config import HybridGatewayConfig
from sentinel_core.hybrid_gateway import HybridModelGateway
from sentinel_core.llm_gateway import LLMGateway


def test_is_private_task_detects_file_paths():
    gw = HybridModelGateway()
    assert gw.is_private_task("Inspect G:\\Sentinel_Workspace\\output.csv") is True
    assert gw.is_private_task("Read c:/users/derik/secret.txt") is True
    assert gw.is_private_task("Parse script.py and format data.json") is True
    assert gw.is_private_task("Write output to ../workspaces/test.obj") is True


def test_is_private_task_detects_system_keywords():
    gw = HybridModelGateway()
    assert gw.is_private_task("Inspect all system processes using top ram") is True
    assert gw.is_private_task("Audit workspace storage drives") is True
    assert gw.is_private_task("Connect to 127.0.0.1 port 8000") is True
    assert gw.is_private_task("Check localhost health via psutil") is True


def test_is_private_task_returns_false_for_general_abstract_prompts():
    gw = HybridModelGateway()
    assert gw.is_private_task("Explain the mathematical proof of Euler's formula") is False
    assert gw.is_private_task("Write a poem about quantum entanglement") is False
    assert gw.is_private_task("What is the capital of Australia") is False


def test_local_routing_always_local_when_mode_local():
    gw = HybridModelGateway(cloud_api_key="mock_key")
    decision = gw.get_routing_decision(
        goal="Explain quantum mechanics",
        mode="local",
    )
    assert decision["decision"] == "local"
    assert "LOCAL_FIRST" in decision["reason"]
    assert decision["fence_triggered"] is False


def test_privacy_fence_blocks_cloud_on_private_goal():
    """Even if mode='cloud' and cloud API key is present, Rule R14 locks private data to local GPU."""
    gw = HybridModelGateway(cloud_api_key="mock_key")
    decision = gw.get_routing_decision(
        goal="Extract names from G:\\Sentinel_Workspace\\users.csv and analyze them",
        mode="cloud",
    )
    assert decision["decision"] == "local"
    assert decision["fence_triggered"] is True
    assert decision["is_private"] is True
    assert "PRIVACY_FENCE_ENFORCED" in decision["reason"]


def test_privacy_fence_allows_cloud_on_public_goal():
    """When task is public and cloud is requested with API key, egress is permitted."""
    gw = HybridModelGateway(cloud_api_key="mock_key")
    decision = gw.get_routing_decision(
        goal="Synthesize an essay on algorithmic game theory",
        mode="cloud",
    )
    assert decision["decision"] == "cloud"
    assert decision["fence_triggered"] is False
    assert decision["is_private"] is False
    assert "OPERATOR_CLOUD_REQUEST" in decision["reason"]


def test_cloud_unavailable_falls_back_to_local():
    """When cloud requested but no API key configured, safely fall back to local GPU."""
    gw = HybridModelGateway(cloud_api_key="")
    assert gw.is_cloud_available() is False
    decision = gw.get_routing_decision(
        goal="Calculate the fibonacci series in constant space",
        mode="cloud",
    )
    assert decision["decision"] == "local"
    assert "CLOUD_UNAVAILABLE_FALLBACK" in decision["reason"]


def test_get_routing_decision_returns_correct_fields():
    gw = HybridModelGateway()
    decision = gw.get_routing_decision("General test goal")
    assert "decision" in decision
    assert "reason" in decision
    assert "is_private" in decision
    assert "fence_triggered" in decision
    assert "cloud_available" in decision
    assert "mode" in decision
    assert "model" in decision


def test_hybrid_generate_dispatches_to_local_by_default():
    mock_local = MagicMock(spec=LLMGateway)
    mock_local.default_model = "qwen3.5:9b"
    mock_local.generate.return_value = "Sovereign local answer."

    gw = HybridModelGateway(local_gateway=mock_local)
    result = gw.generate(prompt="What is recursion?")
    assert result == "Sovereign local answer."
    mock_local.generate.assert_called_once()


def test_hybrid_generate_falls_back_to_local_if_cloud_fails():
    mock_local = MagicMock(spec=LLMGateway)
    mock_local.default_model = "qwen3.5:9b"
    mock_local.generate.return_value = "Local fallback answer."

    gw = HybridModelGateway(local_gateway=mock_local, cloud_api_key="test_key")
    with patch.object(gw, "_generate_cloud", side_effect=RuntimeError("Cloud API error")):
        result = gw.generate(prompt="General public question", mode="cloud")
        assert result == "Local fallback answer."
        mock_local.generate.assert_called_once()
