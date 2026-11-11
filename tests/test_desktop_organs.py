"""Tests for Desktop Computer-Use Organs (Vision & Motor)."""
from pathlib import Path
import pytest

from sentinel_broker.tool_registry import ToolRegistry
from sentinel_broker.organs.desktop_organ import (
    register_desktop_organs,
    get_screen_resolution,
)


def test_get_screen_resolution():
    w, h = get_screen_resolution()
    assert w > 0
    assert h > 0
    assert w >= 800
    assert h >= 600


def test_screen_capture_tool(tmp_path):
    registry = ToolRegistry()
    register_desktop_organs(registry)

    out_file = tmp_path / "test_shot.png"
    res = registry.execute_tool(
        "screen_capture",
        {"output_path": str(out_file)},
        {"task_id": "test_cua", "attempt_id": "att_1"},
    )
    assert res["success"] is True
    assert res["width"] > 0
    assert res["height"] > 0
    assert Path(res["file_path"]).exists()
    assert out_file.stat().st_size > 1000


def test_desktop_cursor_position():
    registry = ToolRegistry()
    register_desktop_organs(registry)

    res = registry.execute_tool(
        "desktop_get_cursor_position",
        {},
        {"task_id": "test_cua", "attempt_id": "att_1"},
    )
    assert "x" in res
    assert "y" in res
    assert res["screen_width"] > 0
    assert res["screen_height"] > 0


def test_desktop_mouse_action_boundary_check():
    registry = ToolRegistry()
    register_desktop_organs(registry)

    # Valid in-bounds move
    res = registry.execute_tool(
        "desktop_mouse_action",
        {"action": "move", "x": 100, "y": 100},
        {"task_id": "test_cua", "attempt_id": "att_1"},
    )
    assert res["success"] is True
    assert res["x"] == 100
    assert res["y"] == 100

    # Out of bounds rejected
    with pytest.raises(ValueError, match="exceed display boundary"):
        registry.execute_tool(
            "desktop_mouse_action",
            {"action": "move", "x": 99999, "y": 99999},
            {"task_id": "test_cua", "attempt_id": "att_1"},
        )


def test_desktop_keyboard_security_filter():
    registry = ToolRegistry()
    register_desktop_organs(registry)

    # Forbidden combo rejected
    with pytest.raises(PermissionError, match="Security policy forbids"):
        registry.execute_tool(
            "desktop_keyboard_type",
            {"text": "", "special_key": "alt+f4"},
            {"task_id": "test_cua", "attempt_id": "att_1"},
        )
