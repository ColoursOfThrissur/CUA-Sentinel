"""Sentinel Blender 3D Motor Organ.
Integrates real Blender 4.5 execution (both headless scripting and interactive GUI automation).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from sentinel_core.side_effects import EffectClass
from sentinel_broker.tool_registry import ToolRegistry

BLENDER_DEFAULT_PATH = r"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe"


def find_blender_executable() -> str:
    """Finds installed blender.exe on the host."""
    if Path(BLENDER_DEFAULT_PATH).exists():
        return BLENDER_DEFAULT_PATH
    found = shutil.which("blender")
    if found:
        return found
    common_paths = [
        Path(r"C:\Program Files\Blender Foundation"),
        Path(r"C:\Program Files (x86)\Blender Foundation"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Blender Foundation",
    ]
    for p in common_paths:
        if p.exists():
            for b in p.rglob("blender.exe"):
                return str(b)
    raise FileNotFoundError("Blender executable not found on host system.")


def register_blender_organs(registry: ToolRegistry):

    @registry.register(
        name="blender_run_python",
        description="Executes a Python script inside real Blender 4.5 to create, modify, or export 3D geometry.",
        effect_class=EffectClass.NON_IDEMPOTENT_WRITE,
        parameters_schema={
            "script_code": "str (Python bpy code to run inside Blender)",
            "output_obj_path": "str (optional path to expected 3D OBJ output)",
            "timeout_sec": "float (default 60.0)",
        },
    )
    def blender_run_python(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        blender_exe = find_blender_executable()
        script_code = params.get("script_code", "")
        timeout = float(params.get("timeout_sec", 60.0))
        output_obj = params.get("output_obj_path")

        # Write script to temporary file
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(script_code)
            script_file = Path(f.name)

        try:
            cmd = [
                blender_exe,
                "--background",
                "--python",
                str(script_file),
            ]
            start_t = time.time()
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            dur = time.time() - start_t

            result = {
                "exit_code": proc.returncode,
                "duration_sec": round(dur, 2),
                "blender_path": blender_exe,
                "stdout": proc.stdout[-2000:],
                "stderr": proc.stderr[-1000:],
                "artifact_created": False,
            }

            if output_obj:
                p = Path(output_obj)
                if p.exists() and p.stat().st_size > 0:
                    result["artifact_created"] = True
                    result["artifact_bytes"] = p.stat().st_size
                    result["artifact_path"] = str(p.resolve())

            return result
        finally:
            try:
                script_file.unlink(missing_ok=True)
            except Exception:
                pass

    @registry.register(
        name="blender_launch_gui",
        description="Launches Blender 4.5 in interactive GUI mode on the user's desktop so the 3D viewport opens.",
        effect_class=EffectClass.NON_IDEMPOTENT_WRITE,
        parameters_schema={
            "file_to_open": "str (optional .blend file path to open)",
        },
    )
    def blender_launch_gui(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        blender_exe = find_blender_executable()
        file_to_open = params.get("file_to_open")

        cmd = [blender_exe]
        if file_to_open and Path(file_to_open).exists():
            cmd.append(str(Path(file_to_open).resolve()))

        # Spawn non-blocking GUI process
        proc = subprocess.Popen(cmd)
        return {
            "status": "LAUNCHED",
            "pid": proc.pid,
            "blender_path": blender_exe,
            "file_opened": file_to_open,
        }
