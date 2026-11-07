"""Telemetry collector for M6 (RAM) and M7 (Disk) measurement in Spike S1."""
from __future__ import annotations

import os
import psutil
from pathlib import Path


def get_system_ram_snapshot() -> dict:
    mem = psutil.virtual_memory()
    return {
        "total_gb": round(mem.total / (1024 ** 3), 2),
        "available_gb": round(mem.available / (1024 ** 3), 2),
        "used_gb": round(mem.used / (1024 ** 3), 2),
        "percent": mem.percent,
    }


def get_process_memory(pid: int) -> dict:
    try:
        p = psutil.Process(pid)
        mem = p.memory_info()
        return {
            "rss_mb": round(mem.rss / (1024 ** 2), 2),
            "vms_mb": round(mem.vms / (1024 ** 2), 2),
        }
    except Exception:
        return {"rss_mb": 0.0, "vms_mb": 0.0}


def get_directory_size_mb(path: Path) -> float:
    total_bytes = 0
    if not path.exists():
        return 0.0
    for root, dirs, files in os.walk(path):
        for f in files:
            fp = os.path.join(root, f)
            try:
                total_bytes += os.path.getsize(fp)
            except OSError:
                pass
    return round(total_bytes / (1024 ** 2), 3)
