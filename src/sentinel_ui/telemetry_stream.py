"""Sentinel Real-Time Telemetry Event Broadcaster (SSE).
Provides thread-safe event pub/sub for real-time task progress, thought streaming, tool execution, and lifecycle transitions.
"""
from __future__ import annotations

import asyncio
import collections
import json
import logging
import time
from typing import Any

logger = logging.getLogger("SentinelTelemetryStream")


class TelemetryBroadcaster:
    """Thread-safe event broadcast hub supporting global and per-task Server-Sent Events (SSE)."""

    def __init__(self, history_maxlen: int = 150):
        self._listeners: list[asyncio.Queue] = []
        self._task_listeners: dict[str, list[asyncio.Queue]] = {}
        self._history: collections.deque = collections.deque(maxlen=history_maxlen)
        self._main_loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self._main_loop = loop

    def subscribe(self, task_id: str | None = None) -> asyncio.Queue:
        """Subscribes an asyncio Queue to receive events (global or task-filtered)."""
        q = asyncio.Queue(maxsize=200)
        if task_id:
            self._task_listeners.setdefault(task_id, []).append(q)
        else:
            self._listeners.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue, task_id: str | None = None):
        """Unsubscribes a queue when client disconnects."""
        if task_id and task_id in self._task_listeners:
            if q in self._task_listeners[task_id]:
                self._task_listeners[task_id].remove(q)
            if not self._task_listeners[task_id]:
                self._task_listeners.pop(task_id, None)
        if q in self._listeners:
            self._listeners.remove(q)

    def get_recent_history(self, task_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """Returns recent buffered events for re-hydration on client connect."""
        events = list(self._history)
        if task_id:
            events = [e for e in events if e.get("task_id") == task_id]
        return events[-limit:]

    def emit(self, event_type: str, data: dict[str, Any], task_id: str | None = None):
        """Thread-safe emit method callable from any worker thread."""
        payload = {
            "type": event_type,
            "task_id": task_id,
            "timestamp": time.time(),
            "data": data,
        }
        self._history.append(payload)

        # Notify active queues
        queues_to_notify: list[asyncio.Queue] = []
        if task_id and task_id in self._task_listeners:
            queues_to_notify.extend(self._task_listeners[task_id])
        queues_to_notify.extend(self._listeners)

        def _enqueue():
            for q in queues_to_notify:
                try:
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    pass

        if self._main_loop and self._main_loop.is_running():
            self._main_loop.call_soon_threadsafe(_enqueue)
        else:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.call_soon_threadsafe(_enqueue)
            except RuntimeError:
                pass


# Global singleton instance
broadcaster = TelemetryBroadcaster()
