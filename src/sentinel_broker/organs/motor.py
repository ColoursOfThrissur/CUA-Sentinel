"""Sentinel Motor Organs ('Arms' & 'Hands' - Action Execution).
Provides mouse cursor movement, clicking, keyboard input, and Windows command execution.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import subprocess
import time
from typing import Any

from sentinel_core.side_effects import EffectClass
from sentinel_broker.tool_registry import ToolRegistry

user32 = ctypes.WinDLL("user32", use_last_error=True)

# Mouse event constants
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000


def register_motor_organs(registry: ToolRegistry):

    @registry.register(
        name="mouse_action",
        description="Controls host mouse cursor: move to (x, y), click, double-click, right-click, or scroll.",
        effect_class=EffectClass.NON_IDEMPOTENT_WRITE,
        parameters_schema={
            "action": "str: 'move', 'click', 'double_click', 'right_click', 'scroll'",
            "x": "int (x screen coordinate)",
            "y": "int (y screen coordinate)",
            "scroll_amount": "int (positive for up, negative for down)",
        },
    )
    def mouse_action(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        action = params.get("action", "click").lower()
        x = params.get("x")
        y = params.get("y")

        if x is not None and y is not None:
            user32.SetCursorPos(int(x), int(y))
            time.sleep(0.05)

        if action == "move":
            pass
        elif action == "click":
            user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.02)
            user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        elif action == "double_click":
            user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.02)
            user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            time.sleep(0.08)
            user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.02)
            user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        elif action == "right_click":
            user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
            time.sleep(0.02)
            user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
        elif action == "scroll":
            delta = int(params.get("scroll_amount", 120))
            user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, delta, 0)

        # Query final cursor position
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))

        return {
            "action": action,
            "cursor_pos": {"x": pt.x, "y": pt.y},
            "status": "COMPLETED",
        }

    @registry.register(
        name="keyboard_action",
        description="Types text or sends keyboard shortcuts (Enter, Esc, Tab, Ctrl, Alt).",
        effect_class=EffectClass.NON_IDEMPOTENT_WRITE,
        parameters_schema={
            "action": "str: 'type' or 'send_keys'",
            "text": "str (text to type)",
            "keys": "str (e.g., '{ENTER}', '^(c)', '%{TAB}')",
        },
    )
    def keyboard_action(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        action = params.get("action", "type")
        payload = params.get("text") or params.get("keys", "")

        # Use PowerShell SendKeys for robust input handling across Windows UI
        escaped = payload.replace("'", "''")
        ps_script = (
            f"[Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; "
            f"[System.Windows.Forms.SendKeys]::SendWait('{escaped}');"
        )
        res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], capture_output=True, text=True)
        return {
            "action": action,
            "keys_sent": payload,
            "success": res.returncode == 0,
        }

    @registry.register(
        name="windows_command",
        description="Executes a Windows PowerShell or CMD command on the host outside the sandbox.",
        effect_class=EffectClass.NON_IDEMPOTENT_WRITE,
        parameters_schema={
            "command": "str (PowerShell or CMD command)",
            "shell": "str ('powershell' or 'cmd')",
            "timeout_sec": "float (default 30.0)",
        },
    )
    def windows_command(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        cmd_str = params.get("command", "")
        shell = params.get("shell", "powershell").lower()
        timeout = float(params.get("timeout_sec", 30.0))

        if shell == "cmd":
            exec_args = ["cmd.exe", "/c", cmd_str]
        else:
            exec_args = ["powershell.exe", "-NoProfile", "-Command", cmd_str]

        proc = subprocess.run(exec_args, capture_output=True, text=True, timeout=timeout)
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout[:4000],
            "stderr": proc.stderr[:2000],
            "command": cmd_str,
        }
