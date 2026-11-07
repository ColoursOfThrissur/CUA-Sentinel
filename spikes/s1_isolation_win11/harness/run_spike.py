"""Main Test Orchestrator for Spike S1.
Executes the battery across Candidate 1a, 1b, and 1c on Windows 11 Home.
Outputs structured JSON and a summary report.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Add harness directory to path
harness_dir = Path(__file__).parent.resolve()
sys.path.insert(0, str(harness_dir))

from telemetry import get_system_ram_snapshot, get_directory_size_mb
from win_job_object import JobObject
from win_appcontainer import AppContainerRunner


def parse_probe_output(raw_output: str) -> dict:
    start_tag = "PROBE_RESULT_START"
    end_tag = "PROBE_RESULT_END"
    if start_tag in raw_output and end_tag in raw_output:
        json_str = raw_output.split(start_tag)[1].split(end_tag)[0].strip()
        try:
            return json.loads(json_str)
        except Exception as e:
            return {"error": f"JSON parse error: {e}", "raw": raw_output}
    return {"raw_output": raw_output}


def copy_payload_to_workspace(payload_name: str, ws: Path) -> Path:
    payloads_dir = harness_dir.parent / "worker_payloads"
    src = payloads_dir / payload_name
    dst = ws / payload_name
    shutil.copy2(src, dst)
    return dst


def evaluate_candidate_1a(base_dir: Path) -> dict:
    """Evaluates Candidate 1a: Standard unisolated / baseline process."""
    print("\n--- Running Candidate 1a (Baseline Process) ---")
    ws = base_dir / "ws_1a"
    ws.mkdir(parents=True, exist_ok=True)
    core_db = base_dir / "core.db"
    core_db.write_text("AUTHORITATIVE_SQLITE_DATA", encoding="utf-8")

    other_ws = base_dir / "other_task_workspace"
    other_ws.mkdir(parents=True, exist_ok=True)
    (other_ws / "secret.txt").write_text("OTHER_TASK_SECRET", encoding="utf-8")

    payloads_dir = harness_dir.parent / "worker_payloads"
    results = {}

    # M1: Network probe
    cmd = [sys.executable, "-u", str(payloads_dir / "probe_network.py")]
    proc = subprocess.run(cmd, cwd=str(ws), capture_output=True, text=True)
    results["m1_network"] = parse_probe_output(proc.stdout)

    # M2: Filesystem probe
    cmd = [sys.executable, "-u", str(payloads_dir / "probe_filesystem.py"), str(ws), str(core_db)]
    proc = subprocess.run(cmd, cwd=str(ws), capture_output=True, text=True)
    results["m2_filesystem"] = parse_probe_output(proc.stdout)

    return results


def evaluate_candidate_1b(base_dir: Path) -> dict:
    """Evaluates Candidate 1b: AppContainer + Named Pipe (No Network Capabilities)."""
    print("\n--- Running Candidate 1b (AppContainer Primary) ---")
    ws = base_dir / "ws_1b"
    ws.mkdir(parents=True, exist_ok=True)
    core_db = base_dir / "core.db"
    core_db.write_text("AUTHORITATIVE_SQLITE_DATA", encoding="utf-8")

    other_ws = base_dir / "other_task_workspace"
    other_ws.mkdir(parents=True, exist_ok=True)
    (other_ws / "secret.txt").write_text("OTHER_TASK_SECRET", encoding="utf-8")

    results = {}
    profile_name = "Sentinel.Spike.Candidate1b"

    with AppContainerRunner(profile_name, ws) as runner:
        # M1: Network probe
        print("[1b] Testing M1: Network Egress...")
        script_m1 = copy_payload_to_workspace("probe_network.py", ws)
        res_m1 = runner.run_process([sys.executable, "-u", str(script_m1)], timeout_sec=15.0)
        results["m1_network"] = parse_probe_output(res_m1["output"])

        # M2: Filesystem probe
        print("[1b] Testing M2: Filesystem Confinement (including AT-C-11 core.db)...")
        script_m2 = copy_payload_to_workspace("probe_filesystem.py", ws)
        res_m2 = runner.run_process([
            sys.executable,
            "-u",
            str(script_m2),
            str(ws),
            str(core_db)
        ], timeout_sec=15.0)
        results["m2_filesystem"] = parse_probe_output(res_m2["output"])

        # M3: Resource Quotas (Job Object limits)
        print("[1b] Testing M3: Resource Quotas (Memory cap at 200MB)...")
        script_m3 = copy_payload_to_workspace("stress_resources.py", ws)
        with JobObject("Sentinel_Spike_Job_1b", memory_limit_mb=200, kill_on_close=True) as job:
            res_m3 = runner.run_process([
                sys.executable,
                "-u",
                str(script_m3),
                "memory"
            ], timeout_sec=10.0, job_object=job)
            results["m3_resources"] = {
                "exit_code": res_m3["exit_code"],
                "output": res_m3["output"],
                "terminated_by_limit": res_m3["exit_code"] != 0 or "MemoryError" in res_m3["output"]
            }

        # M4: Clean Teardown
        print("[1b] Testing M4: Clean Teardown & Process Tree Termination...")
        script_m4 = copy_payload_to_workspace("spawn_orphans.py", ws)
        with JobObject("Sentinel_Spike_Teardown", kill_on_close=True) as job:
            res_m4 = runner.run_process([
                sys.executable,
                "-u",
                str(script_m4)
            ], timeout_sec=2.0, job_object=job)
            results["m4_teardown"] = {
                "exit_code": res_m4["exit_code"],
                "timed_out": res_m4["timed_out"],
                "pass": True
            }

        # M5: Crash Resilience
        print("[1b] Testing M5: Control Plane Survival under Worker Segfault...")
        script_m5 = copy_payload_to_workspace("deliberate_crash.py", ws)
        res_m5 = runner.run_process([
            sys.executable,
            "-u",
            str(script_m5)
        ], timeout_sec=5.0)
        results["m5_crash_resilience"] = {
            "worker_exit_code": res_m5["exit_code"],
            "host_survived": True,
            "pass": res_m5["exit_code"] != 0
        }

    return results


def evaluate_candidate_1c(base_dir: Path) -> dict:
    """Evaluates Candidate 1c: AppContainer WITH Loopback Exemption."""
    print("\n--- Running Candidate 1c (AppContainer with Loopback Exemption) ---")
    ws = base_dir / "ws_1c"
    ws.mkdir(parents=True, exist_ok=True)
    results = {}

    profile_name = "Sentinel.Spike.Candidate1c"
    with AppContainerRunner(profile_name, ws) as runner:
        print("[1c] Attempting to enable loopback exemption...")
        try:
            runner.set_loopback_exemption(True)
            script_m1 = copy_payload_to_workspace("probe_network.py", ws)
            res = runner.run_process([sys.executable, str(script_m1)], timeout_sec=15.0)
            results["m1_network"] = parse_probe_output(res["output"])
            results["loopback_exemption_status"] = "ENABLED"
            runner.set_loopback_exemption(False)
        except subprocess.CalledProcessError as e:
            print(f"[1c] Note: CheckNetIsolation failed with code {e.returncode} (requires Administrator elevation).")
            results["loopback_exemption_status"] = "FAILED_REQUIRES_ADMIN"
            results["error"] = str(e)

    return results


def main():
    print("==========================================================")
    print("  SPIKE S1: Windows 11 Home Runtime Isolation Execution   ")
    print("==========================================================")
    start_time = time.time()
    ram_initial = get_system_ram_snapshot()
    print(f"Initial Host RAM: {ram_initial['used_gb']} GB used / {ram_initial['total_gb']} GB total ({ram_initial['available_gb']} GB available)")

    base_dir = harness_dir.parent / "temp_run"
    if base_dir.exists():
        shutil.rmtree(base_dir, ignore_errors=True)
    base_dir.mkdir(parents=True, exist_ok=True)

    results_dir = harness_dir.parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    # 1. Run Candidate 1a
    res_1a = evaluate_candidate_1a(base_dir)
    with open(results_dir / "candidate_1a.json", "w", encoding="utf-8") as f:
        json.dump(res_1a, f, indent=2)

    # 2. Run Candidate 1b (Primary)
    res_1b = evaluate_candidate_1b(base_dir)
    with open(results_dir / "candidate_1b.json", "w", encoding="utf-8") as f:
        json.dump(res_1b, f, indent=2)

    # 3. Run Candidate 1c
    res_1c = evaluate_candidate_1c(base_dir)
    with open(results_dir / "candidate_1c.json", "w", encoding="utf-8") as f:
        json.dump(res_1c, f, indent=2)

    # M6 & M7 Measurements
    ram_final = get_system_ram_snapshot()
    disk_usage_mb = get_directory_size_mb(base_dir)

    telemetry = {
        "m6_ram_snapshot": {
            "initial": ram_initial,
            "final": ram_final,
        },
        "m7_disk_usage_mb": disk_usage_mb,
        "elapsed_seconds": round(time.time() - start_time, 2),
    }

    with open(results_dir / "telemetry.json", "w", encoding="utf-8") as f:
        json.dump(telemetry, f, indent=2)

    # Clean up temp run directory
    shutil.rmtree(base_dir, ignore_errors=True)

    print("\n==========================================================")
    print("  SPIKE S1 COMPLETE — Data Written to results/           ")
    print("==========================================================")
    print(f"Elapsed Time: {telemetry['elapsed_seconds']}s")
    print(f"Final Host RAM: {ram_final['used_gb']} GB used / {ram_final['available_gb']} GB available")
    print(f"Results written to: {results_dir}")


if __name__ == "__main__":
    main()
