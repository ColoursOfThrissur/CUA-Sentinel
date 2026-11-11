"""Sentinel Sensory Organs ('Eyes' & Perception).
Provides visual screenshot capture, active window inspection, and DOM/page text extraction.
"""
from __future__ import annotations

import fnmatch
import os
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

import psutil
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

    @registry.register(
        name="system_filesystem_inspect",
        description=(
            "Provides safe, read-only perception of the local Windows filesystem across all mounted drives (C:, G:, etc.). "
            "Supports listing drive metrics, discovering largest folders, finding directories by pattern, and reading file previews."
        ),
        effect_class=EffectClass.READ_ONLY,
        parameters_schema={
            "mode": "str (one of 'list_drives', 'largest_folders', 'find', 'read_file')",
            "path": "str | None (drive or folder path, e.g. 'C:\\', 'G:\\', or 'all')",
            "pattern": "str | None (search pattern, e.g. '*games*', '*project*')",
            "limit": "int | None (maximum results, default 5)",
        },
    )
    def system_filesystem_inspect(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        mode = (params.get("mode") or "list_drives").lower()
        target_path = params.get("path") or "all"
        pattern = params.get("pattern") or "*games*"
        limit = int(params.get("limit") or 5)

        # 1. List Drives & Partition Space
        if mode == "list_drives":
            drives_info = []
            try:
                for part in psutil.disk_partitions(all=False):
                    d = part.mountpoint
                    try:
                        u = psutil.disk_usage(d)
                        top_dirs = []
                        try:
                            for entry in os.scandir(d):
                                if entry.is_dir() and not entry.name.startswith("$") and entry.name != "System Volume Information":
                                    top_dirs.append(entry.name)
                        except Exception:
                            pass
                        drives_info.append({
                            "drive": d,
                            "fstype": part.fstype,
                            "total_gb": round(u.total / (1024**3), 2),
                            "used_gb": round(u.used / (1024**3), 2),
                            "free_gb": round(u.free / (1024**3), 2),
                            "percent_used": u.percent,
                            "top_level_folders": sorted(top_dirs)[:15],
                        })
                    except Exception as err:
                        drives_info.append({"drive": d, "error": str(err)})
            except Exception as e:
                return {"success": False, "error": str(e)}
            return {"success": True, "mode": "list_drives", "drives": drives_info}

        # 2. Largest Folders Analysis
        elif mode == "largest_folders":
            search_roots = []
            if target_path == "all" or not target_path:
                for part in psutil.disk_partitions(all=False):
                    search_roots.append(part.mountpoint)
            else:
                search_roots.append(target_path)

            folder_stats = []

            def calc_dir_size(dp: str, max_files: int = 30000) -> int:
                total_sz = 0
                f_count = 0
                try:
                    for root, dirs, files in os.walk(dp):
                        for f in files:
                            f_count += 1
                            if f_count > max_files:
                                break
                            try:
                                total_sz += os.path.getsize(os.path.join(root, f))
                            except Exception:
                                pass
                        if f_count > max_files:
                            break
                except Exception:
                    pass
                return total_sz

            for root_drive in search_roots:
                try:
                    for entry in os.scandir(root_drive):
                        if entry.is_dir() and not entry.name.startswith("$") and entry.name != "System Volume Information":
                            sz = calc_dir_size(entry.path)
                            folder_stats.append({
                                "path": entry.path,
                                "name": entry.name,
                                "size_bytes": sz,
                                "size_gb": round(sz / (1024**3), 2),
                                "size_mb": round(sz / (1024**2), 1),
                            })
                except Exception:
                    pass

            folder_stats.sort(key=lambda x: x["size_bytes"], reverse=True)
            return {
                "success": True,
                "mode": "largest_folders",
                "target_path": target_path,
                "count": len(folder_stats),
                "top_folders": folder_stats[:limit],
            }

        # 3. Find Folders / Files by Pattern
        elif mode in ("find", "search"):
            pat = pattern.lower().strip()
            if not pat.startswith("*"):
                pat = f"*{pat}"
            if not pat.endswith("*"):
                pat = f"{pat}*"

            search_roots = []
            if target_path == "all" or not target_path:
                for part in psutil.disk_partitions(all=False):
                    search_roots.append(part.mountpoint)
            else:
                search_roots.append(target_path)

            matches = []
            for root_drive in search_roots:
                try:
                    for root, dirs, files in os.walk(root_drive):
                        depth = root[len(root_drive):].count(os.sep)
                        if depth > 3:
                            del dirs[:]
                            continue
                        for d in list(dirs):
                            if d.startswith("$") or d == "System Volume Information":
                                dirs.remove(d)
                                continue
                            if fnmatch.fnmatch(d.lower(), pat):
                                full_p = os.path.join(root, d)
                                matches.append({"type": "directory", "path": full_p, "name": d})
                                if len(matches) >= limit:
                                    break
                        if len(matches) >= limit:
                            break
                        for f in files:
                            if fnmatch.fnmatch(f.lower(), pat):
                                full_p = os.path.join(root, f)
                                matches.append({"type": "file", "path": full_p, "name": f})
                                if len(matches) >= limit:
                                    break
                        if len(matches) >= limit:
                            break
                except Exception:
                    pass

            return {
                "success": True,
                "mode": "search",
                "pattern": pattern,
                "matches": matches[:limit],
            }

        # 4. Read File Content Preview
        elif mode == "read_file":
            fp = Path(target_path)
            if not fp.exists() or not fp.is_file():
                return {"success": False, "error": f"File '{target_path}' not found."}
            try:
                content = fp.read_text(encoding="utf-8", errors="replace")[:10000]
                return {
                    "success": True,
                    "mode": "read_file",
                    "path": str(fp),
                    "size_bytes": fp.stat().st_size,
                    "preview": content,
                }
            except Exception as e:
                return {"success": False, "error": str(e)}

        else:
            return {"success": False, "error": f"Unknown mode '{mode}'."}
