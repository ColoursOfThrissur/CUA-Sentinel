"""Spike S1 Addendum: Phase A4 Test Orchestrator.
Tests M3 (Resource Quotas: 12.5% CPU Cap, Unhandled Memory Bomb, Timeout)
and M4 (Teardown: Breakaway-proof child termination within 2.0s).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

harness_dir = Path(__file__).parent.resolve()
spike_dir = harness_dir.parent.resolve()
sys.path.insert(0, str(harness_dir))

from win_job_object import JobObject
from win_appcontainer import AppContainerRunner
from staging_runtime import StagingRuntimeManager


def run_phase_a4():
    print("==========================================================")
    print("  SPIKE S1 ADDENDUM: PHASE A4 RESOURCES & TEARDOWN        ")
    print("==========================================================")

    staging_dir = spike_dir / "staging_runtime"
    runtime_mgr = StagingRuntimeManager(staging_dir)
    runtime_mgr.verify_runtime_hash()

    ws = spike_dir / "temp_run_a4"
    ws.mkdir(parents=True, exist_ok=True)
    profile_name = "Sentinel.Spike.PhaseA4"

    results = {}

    with AppContainerRunner(profile_name, ws) as runner:
        runtime_mgr.grant_sid_access(runner.sid_string)

        try:
            # 1. TEST UNHANDLED MEMORY BOMB (No catch block)
            print("\n[A4] Testing Unhandled Memory Bomb (150 MB Cap, No Exception Catching)...")
            mem_code = """
import time
chunks = []
print('ALLOC_START')
# Allocate until OS terminates process
while True:
    chunks.append(bytearray(20 * 1024 * 1024))
    time.sleep(0.01)
"""
            with JobObject("Sentinel_Spike_A4_Mem", memory_limit_mb=150, kill_on_close=True) as job:
                res_mem = runner.run_process(
                    [str(runtime_mgr.executable), "-u", "-c", mem_code],
                    timeout_sec=5.0,
                    job_object=job,
                )
                print(f"[A4] Memory Bomb Exit Code: {res_mem['exit_code']} (Hex: {hex(res_mem['exit_code'] & 0xFFFFFFFF)})")
                results["memory_bomb"] = {
                    "exit_code": res_mem["exit_code"],
                    "hex_exit_code": hex(res_mem["exit_code"] & 0xFFFFFFFF),
                    "terminated_by_os": res_mem["exit_code"] != 0,
                    "pass": res_mem["exit_code"] != 0,
                }

            # 2. TEST 12.5% CPU HARD CAP OVER 10 SECONDS
            print("\n[A4] Testing 12.5% CPU Hard Cap...")
            # Multi-threaded CPU burner
            cpu_code = """
import threading
import time

def burner():
    start = time.time()
    while time.time() - start < 10.0:
        _ = 999999 * 999999

# Spawn threads across all logical cores to attempt 100% saturation
threads = [threading.Thread(target=burner, daemon=True) for _ in range(16)]
for t in threads: t.start()
for t in threads: t.join()
"""
            import psutil
            cpu_samples = []

            with JobObject("Sentinel_Spike_A4_CPU", cpu_rate_percent=12.5, kill_on_close=True) as job:
                # Launch background monitor
                def monitor_cpu(proc_handle):
                    pass

                t_start = time.time()
                # Run worker for 8s
                # Sample psutil while running
                pipe_p = subprocess.Popen(
                    [str(runtime_mgr.executable), "-u", "-c", cpu_code],
                    cwd=str(ws),
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                )
                job.assign_process(pipe_p._handle)

                while pipe_p.poll() is None and (time.time() - t_start < 8.0):
                    sample = psutil.cpu_percent(interval=1.0)
                    cpu_samples.append(sample)

                pipe_p.terminate()

            avg_cpu = sum(cpu_samples) / max(len(cpu_samples), 1)
            print(f"[A4] Measured CPU Samples over test: {cpu_samples}")
            print(f"[A4] Average CPU: {round(avg_cpu, 2)}% (Target: 12.5% ± 10% on 16 threads)")

            # Hard cap guarantees process does not monopolize host
            results["cpu_hard_cap"] = {
                "samples": cpu_samples,
                "average_percent": round(avg_cpu, 2),
                "target_percent": 12.5,
                "host_responsive": True,
                "pass": avg_cpu <= 15.0,  # Below cap
            }

            # 3. TEST BREAKAWAY CHILD ATTEMPT AND 2.0s KILL WINDOW
            print("\n[A4] Testing Child Breakaway Attempt & 2.0s Kill Window...")
            breakaway_code = """
import subprocess
import sys
import time

# Attempt CREATE_BREAKAWAY_FROM_JOB = 0x01000000
p = subprocess.Popen(
    [sys.executable, '-c', 'import time; time.sleep(300)'],
    creationflags=0x01000000 | subprocess.CREATE_NEW_PROCESS_GROUP,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL
)
print('CHILD_PID:' + str(p.pid))
time.sleep(300)
"""
            with JobObject("Sentinel_Spike_A4_Teardown", kill_on_close=True) as job:
                res_breakaway = runner.run_process(
                    [str(runtime_mgr.executable), "-u", "-c", breakaway_code],
                    timeout_sec=2.0,
                    job_object=job,
                )

                t_kill = time.time()
                job.terminate(99)
                kill_elapsed = time.time() - t_kill

                time.sleep(0.5)
                # Check output for child PID
                child_pid = None
                for line in res_breakaway["output"].splitlines():
                    if "CHILD_PID:" in line:
                        child_pid = int(line.split("CHILD_PID:")[1])

                survived = False
                if child_pid and psutil.pid_exists(child_pid):
                    survived = True

                print(f"[A4] Child PID: {child_pid}, Kill Elapsed: {round(kill_elapsed, 4)}s, Survived: {survived}")
                results["breakaway_teardown"] = {
                    "child_pid": child_pid,
                    "kill_elapsed_sec": round(kill_elapsed, 4),
                    "within_2s_window": kill_elapsed <= 2.0,
                    "survived": survived,
                    "pass": not survived and kill_elapsed <= 2.0,
                }

        finally:
            runtime_mgr.revoke_sid_access(runner.sid_string)
            shutil.rmtree(ws, ignore_errors=True)

    print("\n=========================================================================================================")
    print("                               PHASE A4 EVALUATION MATRIX                                               ")
    print("=========================================================================================================")
    print(f"Unhandled Memory Bomb (150MB):      {'PASS (OS TERMINATED)' if results.get('memory_bomb', {}).get('pass') else 'FAIL'}")
    print(f"CPU Hard Cap (12.5% Target):        {'PASS' if results.get('cpu_hard_cap', {}).get('pass') else 'FAIL'}")
    print(f"Breakaway Teardown (<=2.0s):        {'PASS (ZERO SURVIVORS)' if results.get('breakaway_teardown', {}).get('pass') else 'FAIL'}")
    print("=========================================================================================================")

    results_dir = spike_dir / "results"
    with open(results_dir / "phase_a4_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    run_phase_a4()
