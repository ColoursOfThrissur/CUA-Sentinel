"""Sentinel Sensory Organs ('Eyes' & Perception).
Provides visual screenshot capture, active window inspection, and DOM/page text extraction.
"""
from __future__ import annotations

import subprocess
import urllib.request
from pathlib import Path
from typing import Any

import win32gui
import win32process

from sentinel_core.side_effects import EffectClass
from sentinel_broker.tool_registry import ToolRegistry


def register_sensory_organs(registry: ToolRegistry):

    @registry.register(
        name="window_inspect",
        description="Inspects active foreground window and lists visible top-level Windows applications.",
        effect_class=EffectClass.READ_ONLY,
        parameters_schema={"filter_title": "str (optional)"},
    )
    def window_inspect(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        fg_hwnd = win32gui.GetForegroundWindow()
        fg_title = win32gui.GetWindowText(fg_hwnd) if fg_hwnd else ""
        fg_rect = {"left": 0, "top": 0, "right": 0, "bottom": 0}
        fg_pid = 0

        if fg_hwnd:
            try:
                rect = win32gui.GetWindowRect(fg_hwnd)
                fg_rect = {"left": rect[0], "top": rect[1], "right": rect[2], "bottom": rect[3]}
                _, fg_pid = win32process.GetWindowThreadProcessId(fg_hwnd)
            except Exception:
                pass

        visible_windows = []
        filter_str = params.get("filter_title", "").lower()

        def enum_cb(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd).strip()
                if title and (not filter_str or filter_str in title.lower()):
                    rect = win32gui.GetWindowRect(hwnd)
                    visible_windows.append({
                        "hwnd": hwnd,
                        "title": title,
                        "rect": {"left": rect[0], "top": rect[1], "right": rect[2], "bottom": rect[3]},
                    })

        win32gui.EnumWindows(enum_cb, None)
        return {
            "foreground_window": {
                "hwnd": fg_hwnd,
                "title": fg_title,
                "pid": fg_pid,
                "rect": fg_rect,
            },
            "visible_windows": visible_windows[:30],
        }

    @registry.register(
        name="screen_capture",
        description="Takes a screenshot of the Windows desktop and saves it to a file.",
        effect_class=EffectClass.READ_ONLY,
        parameters_schema={"output_path": "str (path to save PNG)"},
    )
    def screen_capture(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        out_path = Path(params.get("output_path", "screenshot.png")).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # Use PowerShell Windows Forms Screen Capture (works reliably on modern Windows 11)
        ps_cmd = (
            f"[Reflection.Assembly]::LoadWithPartialName('System.Drawing') | Out-Null; "
            f"[Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; "
            f"$bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
            f"$bmp = New-Object Drawing.Bitmap $bounds.Width, $bounds.Height; "
            f"$graphics = [Drawing.Graphics]::FromImage($bmp); "
            f"$graphics.CopyFromScreen($bounds.Location, [Drawing.Point]::Empty, $bounds.Size); "
            f"$bmp.Save('{str(out_path)}'); "
            f"$graphics.Dispose(); $bmp.Dispose();"
        )
        res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True)
        if out_path.exists() and out_path.stat().st_size > 0:
            return {
                "success": True,
                "path": str(out_path),
                "size_bytes": out_path.stat().st_size,
            }
        return {
            "success": False,
            "error": res.stderr or "Screenshot output file not generated",
        }

    @registry.register(
        name="browser_inspect_url",
        description="Fetches raw DOM/HTML structure and text content from a specified URL.",
        effect_class=EffectClass.READ_ONLY,
        parameters_schema={"url": "str"},
    )
    def browser_inspect_url(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        url = params.get("url", "")
        req = urllib.request.Request(url, headers={"User-Agent": "Sentinel-Perception/1.0"})
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            content = resp.read().decode("utf-8", errors="replace")
            return {
                "url": url,
                "status_code": resp.status,
                "length_chars": len(content),
                "preview": content[:1500],
            }
