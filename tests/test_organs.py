"""Tests for Sensory ('Eyes') and Motor ('Arms & Hands') Organs."""
import pytest
from pathlib import Path
import tempfile
import shutil

from sentinel_broker.tool_registry import ToolRegistry
from sentinel_broker.organs.sensory import register_sensory_organs
from sentinel_broker.organs.motor import register_motor_organs


@pytest.fixture
def organs_registry():
    registry = ToolRegistry()
    register_sensory_organs(registry)
    register_motor_organs(registry)
    return registry


def test_registered_sensory_and_motor_tools(organs_registry):
    tools = {t["name"] for t in organs_registry.list_tools()}
    assert "window_inspect" in tools
    assert "screen_capture" in tools
    assert "browser_inspect_url" in tools
    assert "mouse_action" in tools
    assert "keyboard_action" in tools
    assert "windows_command" in tools


def test_window_inspect_organ(organs_registry):
    res = organs_registry.execute_tool("window_inspect", {})
    assert "foreground_window" in res
    assert "visible_windows" in res
    assert isinstance(res["visible_windows"], list)


def test_windows_command_motor_organ(organs_registry):
    res = organs_registry.execute_tool("windows_command", {
        "command": "Write-Output 'SENTINEL_MOTOR_OK'",
        "shell": "powershell",
    })
    assert res["exit_code"] == 0
    assert "SENTINEL_MOTOR_OK" in res["stdout"]


def test_mouse_motor_organ(organs_registry):
    res = organs_registry.execute_tool("mouse_action", {
        "action": "move",
        "x": 100,
        "y": 100,
    })
    assert res["status"] == "COMPLETED"
    assert "cursor_pos" in res
