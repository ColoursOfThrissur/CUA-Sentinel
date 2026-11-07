"""M2 Filesystem Confinement Probe Payload for Spike S1.
Attempts to read and write files inside and outside the assigned workspace.
Specifically tests AT-C-11 (core.db cannot be opened or read).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def try_write(path: Path, content: str = "sentinel_test") -> dict:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        read_back = path.read_text(encoding="utf-8")
        return {"allowed": True, "error": None, "verified": read_back == content}
    except Exception as e:
        return {"allowed": False, "error": f"{type(e).__name__}: {e}", "verified": False}


def try_read(path: Path) -> dict:
    try:
        if not path.exists():
            return {"allowed": False, "exists": False, "error": "FileNotFound"}
        content = path.read_bytes()[:64]
        return {"allowed": True, "exists": True, "bytes_read": len(content), "error": None}
    except Exception as e:
        return {"allowed": False, "exists": True, "bytes_read": 0, "error": f"{type(e).__name__}: {e}"}


def main():
    if len(sys.argv) < 3:
        workspace_dir = Path(os.getcwd())
        core_db_path = workspace_dir.parent / "core.db"
    else:
        workspace_dir = Path(sys.argv[1]).resolve()
        core_db_path = Path(sys.argv[2]).resolve()

    user_home = Path(os.environ.get("USERPROFILE", "C:\\Users\\Default"))
    system_root = Path(os.environ.get("SYSTEMROOT", "C:\\Windows"))
    other_workspace = workspace_dir.parent / "other_task_workspace" / "secret.txt"

    report = {
        "test": "M2_FILESYSTEM_CONFINEMENT",
        "workspace_write": try_write(workspace_dir / "worker_output.txt"),
        "workspace_read": try_read(workspace_dir / "worker_output.txt"),
        "at_c_11_core_db_read": try_read(core_db_path),
        "at_c_11_core_db_write": try_write(core_db_path, "malicious_overwrite"),
        "other_workspace_read": try_read(other_workspace),
        "user_profile_read": try_read(user_home / "NTUSER.DAT"),
        "system_binary_read": try_read(system_root / "System32" / "notepad.exe"),
        "traversal_read": try_read(workspace_dir / ".." / ".." / "sensitive.txt"),
    }

    print("PROBE_RESULT_START")
    print(json.dumps(report, indent=2))
    print("PROBE_RESULT_END")


if __name__ == "__main__":
    main()
