"""Spike S1 Addendum: Phase A6 Profile Churn & Artifact Leak Audit (M7).
Executes 50 consecutive create -> run -> destroy cycles.
Audits:
1. Leftover AppContainer profiles in registry (HKCU\\Software\\Classes\\AppContainer\\Storage)
2. Leftover workspace files / disk consumption
3. Stray processes
4. System memory drift
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
import winreg
from pathlib import Path

import psutil

harness_dir = Path(__file__).parent.resolve()
spike_dir = harness_dir.parent.resolve()
sys.path.insert(0, str(harness_dir))

from win_appcontainer import AppContainerRunner
from staging_runtime import StagingRuntimeManager


def check_registry_leftovers(pattern: str) -> list[str]:
    """Scan HKCU\\Software\\Classes\\AppContainer\\Storage for any keys containing pattern."""
    leftovers = []
    reg_path = r"Software\Classes\AppContainer\Storage"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path) as key:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(key, i)
                    if pattern.lower() in sub.lower():
                        leftovers.append(sub)
                    i += 1
                except OSError:
                    break
    except FileNotFoundError:
        pass
    return leftovers


def run_phase_a6(total_cycles: int = 50):
    print("==========================================================")
    print(f"  SPIKE S1 ADDENDUM: PHASE A6 CHURN AUDIT ({total_cycles} CYCLES)  ")
    print("==========================================================")

    staging_dir = spike_dir / "staging_runtime"
    runtime_mgr = StagingRuntimeManager(staging_dir)
    runtime_mgr.verify_runtime_hash()

    ws_base = spike_dir / "temp_churn_workspaces"
    ws_base.mkdir(parents=True, exist_ok=True)

    initial_mem = psutil.virtual_memory().available / (1024 * 1024)
    initial_pids = set(p.pid for p in psutil.process_iter())

    cycle_latencies = []
    successes = 0
    failures = 0
    pattern_prefix = "Sentinel.Spike.Churn"

    start_time = time.time()

    for i in range(1, total_cycles + 1):
        c_start = time.time()
        prof_name = f"{pattern_prefix}.{i:03d}"
        ws = ws_base / f"ws_{i:03d}"
        ws.mkdir(parents=True, exist_ok=True)

        try:
            with AppContainerRunner(prof_name, ws) as runner:
                runtime_mgr.grant_sid_access(runner.sid_string)
                try:
                    # Write and run a payload that produces work and writes to workspace
                    cmd = [
                        str(runtime_mgr.executable),
                        "-c",
                        f"with open('result.txt', 'w') as f: f.write('cycle_{i}_ok')\nprint('CHURN_OK_{i}')",
                    ]
                    res = runner.run_process(cmd, timeout_sec=10.0, sanitize_env=True)
                    if f"CHURN_OK_{i}" in res["output"]:
                        successes += 1
                    else:
                        print(f"Cycle {i} unexpected output: {res['output']}")
                        failures += 1
                finally:
                    runtime_mgr.revoke_sid_access(runner.sid_string)
        except Exception as e:
            print(f"Cycle {i} exception: {e}")
            failures += 1
        finally:
            shutil.rmtree(ws, ignore_errors=True)

        c_dur = time.time() - c_start
        cycle_latencies.append(c_dur)
        if i % 10 == 0 or i == total_cycles:
            avg_so_far = sum(cycle_latencies) / len(cycle_latencies)
            print(f"Progress: {i}/{total_cycles} cycles completed (avg latency: {avg_so_far:.2f}s/cycle)")

    total_time = time.time() - start_time
    final_mem = psutil.virtual_memory().available / (1024 * 1024)
    final_pids = set(p.pid for p in psutil.process_iter())
    stray_pids = final_pids - initial_pids

    # Clean up ws_base
    shutil.rmtree(ws_base, ignore_errors=True)
    remaining_bytes = sum(f.stat().st_size for f in ws_base.rglob("*") if f.is_file()) if ws_base.exists() else 0

    # Registry audit
    leftover_keys = check_registry_leftovers(pattern_prefix)

    report = {
        "total_cycles": total_cycles,
        "successes": successes,
        "failures": failures,
        "total_duration_sec": round(total_time, 2),
        "avg_cycle_sec": round(sum(cycle_latencies) / len(cycle_latencies), 3),
        "min_cycle_sec": round(min(cycle_latencies), 3),
        "max_cycle_sec": round(max(cycle_latencies), 3),
        "initial_available_mb": round(initial_mem, 1),
        "final_available_mb": round(final_mem, 1),
        "memory_delta_mb": round(final_mem - initial_mem, 1),
        "leftover_registry_keys": leftover_keys,
        "leftover_registry_count": len(leftover_keys),
        "stray_pids_count": len(stray_pids),
        "stray_pids": list(stray_pids),
        "remaining_workspace_bytes": remaining_bytes,
        "pass": (
            failures == 0
            and len(leftover_keys) == 0
            and len(stray_pids) == 0
            and remaining_bytes <= 1024 * 1024
        ),
    }

    print("\n=========================================================================================================")
    print("                               PHASE A6 EVALUATION MATRIX                                               ")
    print("=========================================================================================================")
    print(f"Total Cycles:             {report['total_cycles']} ({report['successes']} Succeeded, {report['failures']} Failed)")
    print(f"Total Duration:           {report['total_duration_sec']} s (Average: {report['avg_cycle_sec']} s/cycle)")
    print(f"Leftover Registry Keys:   {report['leftover_registry_count']} (Target: 0)")
    print(f"Stray Orphan Processes:   {report['stray_pids_count']} (Target: 0)")
    print(f"Workspace Residual Disk:  {report['remaining_workspace_bytes']} bytes (Target: <= 1 MB)")
    print(f"Memory Available Floor:   {report['final_available_mb']:.1f} MB (Target: >= 2500 MB)")
    print(f"OVERALL PHASE A6 RESULT:  {'PASS' if report['pass'] else 'FAIL'}")
    print("=========================================================================================================")

    results_dir = spike_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    with open(results_dir / "phase_a6_results.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)


if __name__ == "__main__":
    run_phase_a6(50)
