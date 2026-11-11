"""Sentinel Native Desktop Vision & Input Organs (Windows 11 CUA).
Provides high-assurance computer-use capabilities:
1. Sensory (Vision): screen_capture (via Win32 GDI BitBlt)
2. Motor (Mouse): desktop_mouse_action (with boundary verification and PDP gating)
3. Motor (Keyboard): desktop_keyboard_type (with dangerous combo blocking)
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import os
from pathlib import Path
import time
from typing import Any

from PIL import Image

from sentinel_broker.tool_registry import ToolRegistry, EffectClass
from sentinel_core.side_effects import SideEffectLedger

logger = logging.getLogger("SentinelDesktopOrgan")

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

SRCCOPY = 0x00CC0020
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

FORBIDDEN_KEY_COMBOS = {"alt+f4", "ctrl+alt+del", "win+l", "ctrl+shift+esc"}


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ('biSize', wintypes.DWORD),
        ('biWidth', wintypes.LONG),
        ('biHeight', wintypes.LONG),
        ('biPlanes', wintypes.WORD),
        ('biBitCount', wintypes.WORD),
        ('biCompression', wintypes.DWORD),
        ('biSizeImage', wintypes.DWORD),
        ('biXPelsPerMeter', wintypes.LONG),
        ('biYPelsPerMeter', wintypes.LONG),
        ('biClrUsed', wintypes.DWORD),
        ('biClrImportant', wintypes.DWORD)
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


def get_screen_resolution() -> tuple[int, int]:
    w = user32.GetSystemMetrics(0)
    h = user32.GetSystemMetrics(1)
    return w, h


def capture_desktop_gdi() -> Image.Image:
    w, h = get_screen_resolution()
    hdc_screen = user32.GetDC(0)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    hbm = gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
    gdi32.SelectObject(hdc_mem, hbm)

    gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_screen, 0, 0, SRCCOPY)

    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = w
    bmi.biHeight = -h  # top-down DIB
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0

    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(hdc_mem, hbm, 0, h, buf, ctypes.byref(bmi), 0)

    user32.ReleaseDC(0, hdc_screen)
    gdi32.DeleteDC(hdc_mem)
    gdi32.DeleteObject(hbm)

    img = Image.frombuffer('RGBA', (w, h), buf, 'raw', 'BGRA', 0, 1)
    return img.convert('RGB')


def register_desktop_organs(registry: ToolRegistry, ledger: SideEffectLedger | None = None):
    """Registers computer-use vision sensory organs and motor actuation organs."""

    @registry.register(
        name="screen_capture",
        description="Captures a high-resolution screenshot of the host desktop using native Windows GDI BitBlt.",
        effect_class=EffectClass.READ_ONLY,
        parameters_schema={
            "output_path": {"type": "string", "description": "Optional destination filepath for PNG. Default in workspace.", "default": ""},
        },
    )
    def screen_capture(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        dest_str = params.get("output_path", "").strip()
        ts = int(time.time())
        if not dest_str:
            dest_dir = Path("G:/Sentinel_Workspace") if Path("G:/Sentinel_Workspace").exists() else Path(".")
            dest = dest_dir / f"screenshot_{ts}.png"
        else:
            dest = Path(dest_str)

        dest.parent.mkdir(parents=True, exist_ok=True)
        img = capture_desktop_gdi()
        img.save(str(dest), format="PNG")
        sz = dest.stat().st_size

        logger.info("Captured desktop screenshot: %s (%dx%d, %d bytes)", dest, img.width, img.height, sz)
        return {
            "success": True,
            "file_path": str(dest.resolve()),
            "width": img.width,
            "height": img.height,
            "size_bytes": sz,
            "timestamp": ts,
        }

    @registry.register(
        name="desktop_get_cursor_position",
        description="Returns the current hardware mouse cursor position and display resolution.",
        effect_class=EffectClass.READ_ONLY,
        parameters_schema={},
    )
    def desktop_get_cursor_position(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        w, h = get_screen_resolution()
        return {
            "x": pt.x,
            "y": pt.y,
            "screen_width": w,
            "screen_height": h,
        }

    @registry.register(
        name="desktop_mouse_action",
        description="Guarded motor organ: moves cursor and performs click actions with boundary validation.",
        effect_class=EffectClass.NON_IDEMPOTENT_WRITE,
        parameters_schema={
            "action": {"type": "string", "description": "'move', 'click', 'double_click', or 'right_click'"},
            "x": {"type": "integer", "description": "X coordinate in screen pixels"},
            "y": {"type": "integer", "description": "Y coordinate in screen pixels"},
        },
    )
    def desktop_mouse_action(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        action = params.get("action", "click").lower()
        x = int(params.get("x", 0))
        y = int(params.get("y", 0))

        w, h = get_screen_resolution()
        if not (0 <= x < w and 0 <= y < h):
            raise ValueError(f"Target coordinates ({x}, {y}) exceed display boundary (0..{w-1}, 0..{h-1}).")

        # Move cursor
        user32.SetCursorPos(x, y)
        time.sleep(0.02)

        if action == "click":
            user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.03)
            user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        elif action == "double_click":
            user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.02)
            user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            time.sleep(0.05)
            user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.02)
            user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        elif action == "right_click":
            user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
            time.sleep(0.03)
            user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
        elif action == "move":
            pass
        else:
            raise ValueError(f"Unsupported mouse action '{action}'. Use 'move', 'click', 'double_click', 'right_click'.")

        if ledger:
            ledger.record_effect(
                task_id=ctx.get("task_id", "desktop_cua"),
                attempt_id=ctx.get("attempt_id", "att_1"),
                effect_type="DESKTOP_MOUSE_ACTION",
                target=f"{action}@{x},{y}",
                is_irreversible=False,
            )

        logger.info("Executed desktop mouse action: %s at (%d, %d)", action, x, y)
        return {"success": True, "action": action, "x": x, "y": y}

    @registry.register(
        name="desktop_keyboard_type",
        description="Guarded motor organ: sends keystrokes or types text into the focused window with safety filter.",
        effect_class=EffectClass.NON_IDEMPOTENT_WRITE,
        parameters_schema={
            "text": {"type": "string", "description": "Text to type into focused window", "default": ""},
            "press_enter": {"type": "boolean", "description": "Whether to hit Enter after typing", "default": False},
            "special_key": {"type": "string", "description": "Optional single key like 'tab', 'escape', 'backspace'", "default": ""},
        },
    )
    def desktop_keyboard_type(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        text = params.get("text", "")
        press_enter = bool(params.get("press_enter", False))
        special = (params.get("special_key") or "").lower().strip()

        # Security Fence Check
        if any(bad in special for bad in FORBIDDEN_KEY_COMBOS):
            raise PermissionError(f"Security policy forbids dangerous key combination: '{special}'")

        typed_chars = 0
        for char in text:
            # Send Unicode char using SendInput
            code = ord(char)
            user32.keybd_event(0, code, KEYEVENTF_UNICODE, 0)
            user32.keybd_event(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0)
            typed_chars += 1
            time.sleep(0.01)

        VK_CODES = {
            "enter": 0x0D,
            "return": 0x0D,
            "tab": 0x09,
            "escape": 0x1B,
            "esc": 0x1B,
            "backspace": 0x08,
            "space": 0x20,
            "up": 0x26,
            "down": 0x28,
            "left": 0x25,
            "right": 0x27,
        }

        if special and special in VK_CODES:
            vk = VK_CODES[special]
            user32.keybd_event(vk, 0, 0, 0)
            time.sleep(0.02)
            user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)

        if press_enter:
            user32.keybd_event(0x0D, 0, 0, 0)
            time.sleep(0.02)
            user32.keybd_event(0x0D, 0, KEYEVENTF_KEYUP, 0)

        if ledger:
            ledger.record_effect(
                task_id=ctx.get("task_id", "desktop_cua"),
                attempt_id=ctx.get("attempt_id", "att_1"),
                effect_type="DESKTOP_KEYBOARD_INPUT",
                target=f"typed_{typed_chars}_chars",
                is_irreversible=False,
            )

        logger.info("Executed keyboard input: typed %d chars (special: %s, enter: %s)", typed_chars, special, press_enter)
        return {"success": True, "typed_characters": typed_chars, "special_key": special, "pressed_enter": press_enter}
