"""Tests for Sentinel Real-Time Telemetry Event Broadcaster (SSE) - Pillar 1."""
import asyncio
import pytest

from sentinel_ui.telemetry_stream import TelemetryBroadcaster


@pytest.mark.asyncio
async def test_telemetry_broadcaster_subscribe_and_emit():
    broadcaster = TelemetryBroadcaster(history_maxlen=50)
    loop = asyncio.get_running_loop()
    broadcaster.set_loop(loop)

    q_global = broadcaster.subscribe(None)
    q_task = broadcaster.subscribe("task_123")
    q_other = broadcaster.subscribe("task_999")

    # Emit global event
    broadcaster.emit("system_alert", {"msg": "Server started"}, task_id=None)
    # Emit task-specific event
    broadcaster.emit("tool_call", {"tool": "blender_run_python"}, task_id="task_123")

    # Check global receiver got both (or global queue receives all)
    ev1 = await asyncio.wait_for(q_global.get(), timeout=1.0)
    assert ev1["type"] == "system_alert"
    ev2 = await asyncio.wait_for(q_global.get(), timeout=1.0)
    assert ev2["type"] == "tool_call"
    assert ev2["task_id"] == "task_123"

    # Check task_123 receiver got tool_call
    ev_task = await asyncio.wait_for(q_task.get(), timeout=1.0)
    assert ev_task["type"] == "tool_call"
    assert ev_task["data"]["tool"] == "blender_run_python"

    # Check task_999 did not receive task_123's event
    assert q_other.empty()

    # Test history retrieval
    hist = broadcaster.get_recent_history("task_123", limit=5)
    assert len(hist) == 1
    assert hist[0]["data"]["tool"] == "blender_run_python"

    # Unsubscribe
    broadcaster.unsubscribe(q_global, None)
    broadcaster.unsubscribe(q_task, "task_123")
    broadcaster.unsubscribe(q_other, "task_999")
