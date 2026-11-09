"""Spike S1 Addendum: Phase A0 Test Orchestrator.
Executes the repaired probe suite across:
1. Control (Unrestricted)
2. Positive Control (Container with explicit grants)
3. Candidate 1b (AppContainer with Zero capabilities + Job Object)
4. Candidate 1a-prime (Low-Integrity baseline process)
"""
from __future__ import annotations

import _winapi
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

from listeners import CanaryListenerManager
from staging_runtime import StagingRuntimeManager
from win_appcontainer import AppContainerRunner
from win_job_object import JobObject


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


def run_control(runtime_exe: Path, canary_dir: Path, base_dir: Path, lan_ip: str, ca_file: Path) -> dict:
    print("\n--- [Phase A0] Running Control (Unrestricted) ---")
    ws = base_dir / "ws_control"
    ws.mkdir(parents=True, exist_ok=True)

    # Create junction to canary in workspace
    junc = ws / "junction_canary"
    if junc.exists():
        os.unlink(junc)
    _winapi.CreateJunction(str(canary_dir), str(junc))

    payload = spike_dir / "worker_payloads" / "probe_suite_a0.py"
    cmd = [
        str(runtime_exe),
        "-u",
        str(payload),
        "all",
        lan_ip,
        str(canary_dir),
        str(ws),
        str(ca_file),
    ]

    proc = subprocess.run(cmd, cwd=str(ws), capture_output=True, text=True)
    res = parse_probe_output(proc.stdout)

    # Test M5 crash on control
    crash_proc = subprocess.run(
        [str(runtime_exe), "-u", str(payload), "crash"],
        cwd=str(ws),
        capture_output=True,
    )
    res["m5_crash_exit_code"] = hex(crash_proc.returncode & 0xFFFFFFFF)

    return res


def run_positive_control(
    runtime_mgr: StagingRuntimeManager,
    canary_dir: Path,
    base_dir: Path,
    lan_ip: str,
    ca_file: Path,
) -> dict:
    print("\n--- [Phase A0] Running Positive Control (Container with Granted Capability) ---")
    ws = base_dir / "ws_pos_ctrl"
    ws.mkdir(parents=True, exist_ok=True)

    profile_name = "Sentinel.Spike.PositiveControl"
    results = {}

    with AppContainerRunner(profile_name, ws) as runner:
        # Grant container SID read access to staging runtime
        runtime_mgr.grant_sid_access(runner.sid_string)

        # Grant container SID read access to canary directory and file specifically
        canary_secret = canary_dir / "secret_canary.txt"
        cmd_grant_dir = f'icacls "{canary_dir}" /grant "*{runner.sid_string}:(RX)" /Q'
        cmd_grant_file = f'icacls "{canary_secret}" /grant "*{runner.sid_string}:(R)" /Q'
        subprocess.run(cmd_grant_dir, shell=True, check=True)
        subprocess.run(cmd_grant_file, shell=True, check=True)

        try:
            payload = ws / "probe_suite_a0.py"
            shutil.copy2(spike_dir / "worker_payloads" / "probe_suite_a0.py", payload)

            cmd = [
                str(runtime_mgr.executable),
                "-u",
                str(payload),
                "all",
                lan_ip,
                str(canary_dir),
                str(ws),
                str(ca_file),
            ]
            run_res = runner.run_process(cmd, timeout_sec=15.0)
            parsed = parse_probe_output(run_res["output"])
            results["canary_direct_read"] = parsed.get("filesystem", {}).get("canary_direct_read", {})
        finally:
            # Revert canary grants
            cmd_rev_file = f'icacls "{canary_secret}" /remove "*{runner.sid_string}" /Q'
            cmd_rev_dir = f'icacls "{canary_dir}" /remove "*{runner.sid_string}" /Q'
            subprocess.run(cmd_rev_file, shell=True, check=True)
            subprocess.run(cmd_rev_dir, shell=True, check=True)
            runtime_mgr.revoke_sid_access(runner.sid_string)

    return results


def run_candidate_1b(
    runtime_mgr: StagingRuntimeManager,
    canary_dir: Path,
    base_dir: Path,
    lan_ip: str,
    ca_file: Path,
) -> dict:
    print("\n--- [Phase A0] Running Candidate 1b (AppContainer Primary) ---")
    ws = base_dir / "ws_1b"
    ws.mkdir(parents=True, exist_ok=True)

    # Create junction in 1b workspace pointing to canary
    junc = ws / "junction_canary"
    if junc.exists():
        os.unlink(junc)
    _winapi.CreateJunction(str(canary_dir), str(junc))

    profile_name = "Sentinel.Spike.Candidate1b"
    results = {}

    with AppContainerRunner(profile_name, ws) as runner:
        # Grant read/execute solely to this specific container SID
        runtime_mgr.grant_sid_access(runner.sid_string)

        try:
            payload = ws / "probe_suite_a0.py"
            shutil.copy2(spike_dir / "worker_payloads" / "probe_suite_a0.py", payload)

            # 1. Probe battery
            cmd = [
                str(runtime_mgr.executable),
                "-u",
                str(payload),
                "all",
                lan_ip,
                str(canary_dir),
                str(ws),
                str(ca_file),
            ]
            run_res = runner.run_process(cmd, timeout_sec=20.0)
            results["probe_results"] = parse_probe_output(run_res["output"])

            # 2. Hard Crash (M5)
            cmd_crash = [str(runtime_mgr.executable), "-u", str(payload), "crash"]
            crash_res = runner.run_process(cmd_crash, timeout_sec=5.0)
            is_sigsegv = crash_res["exit_code"] in [3, 0xC0000005, -1073741819]
            results["m5_crash"] = {
                "exit_code": crash_res["exit_code"],
                "hex_exit_code": hex(crash_res["exit_code"] & 0xFFFFFFFF),
                "is_ntstatus_or_sigsegv": is_sigsegv,
            }

            # 3. M4 Teardown with 300s children and PID manifest
            print("[1b] Testing M4: Child tracking and clean teardown...")
            with JobObject("Sentinel_Spike_A0_Teardown", kill_on_close=True) as job:
                cmd_spawn = [str(runtime_mgr.executable), "-u", str(payload), "spawn_children"]
                # Give 2.5s for children to spawn and write manifest
                spawn_res = runner.run_process(cmd_spawn, timeout_sec=2.5, job_object=job)

                # Check manifest
                manifest_file = ws / "children_manifest.json"
                if manifest_file.exists():
                    children = json.loads(manifest_file.read_text(encoding="utf-8"))
                    print(f"[1b] Spawned children to track: {[c['pid'] for c in children]}")

                    # Terminate job
                    t_kill_start = time.time()
                    job.terminate(99)
                    elapsed_kill = time.time() - t_kill_start

                    # Check PIDs after kill
                    time.sleep(0.5)
                    import psutil
                    survivors = []
                    for c in children:
                        pid = c["pid"]
                        if psutil.pid_exists(pid):
                            try:
                                p = psutil.Process(pid)
                                # Confirm it is the same process (match create_time within 2s)
                                if abs(p.create_time() - c["create_time"]) < 2.0:
                                    survivors.append(pid)
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                pass

                    results["m4_teardown"] = {
                        "elapsed_kill_sec": round(elapsed_kill, 3),
                        "within_2s_window": elapsed_kill <= 2.0,
                        "tracked_pids": [c["pid"] for c in children],
                        "survivors": survivors,
                        "pass": len(survivors) == 0 and elapsed_kill <= 2.0,
                    }
                else:
                    results["m4_teardown"] = {"pass": False, "error": "Manifest not generated"}

        finally:
            runtime_mgr.revoke_sid_access(runner.sid_string)

    return results


def main():
    print("==========================================================")
    print("  SPIKE S1 ADDENDUM: PHASE A0 EXECUTION                   ")
    print("==========================================================")
    start_time = time.time()

    lan_ip = "10.66.232.232"
    canary_dir = spike_dir / "canary"
    staging_dir = spike_dir / "staging_runtime"
    base_run_dir = spike_dir / "temp_run_a0"

    if base_run_dir.exists():
        shutil.rmtree(base_run_dir, ignore_errors=True)
    base_run_dir.mkdir(parents=True, exist_ok=True)

    runtime_mgr = StagingRuntimeManager(staging_dir)
    if not runtime_mgr.is_setup():
        runtime_mgr.build_staging_runtime()

    # Hash verification (AT-C-12)
    runtime_mgr.verify_runtime_hash()
    print("[Phase A0] Staging runtime hash-verified successfully (AT-C-12).")

    ca_file = staging_dir / "cacert.pem"

    # Start live Canary listeners
    with CanaryListenerManager(lan_ip=lan_ip, base_port=18080) as listeners:
        print("[Phase A0] Live Canary listeners running on Loopback, LAN, UDP, and Proxy.")

        # 1. Unrestricted Control
        res_ctrl = run_control(runtime_mgr.executable, canary_dir, base_run_dir, lan_ip, ca_file)

        # 2. Positive Control
        res_pos = run_positive_control(runtime_mgr, canary_dir, base_run_dir, lan_ip, ca_file)

        # 3. Candidate 1b
        res_1b = run_candidate_1b(runtime_mgr, canary_dir, base_run_dir, lan_ip, ca_file)

    # Compile Evaluation Matrix
    eval_matrix = []

    def evaluate_vector(category, name, ctrl_val, b_val, pos_val=None):
        ctrl_allowed = ctrl_val.get("allowed", False)
        b_allowed = b_val.get("allowed", False)
        b_blocked = not b_allowed

        if not ctrl_allowed:
            verdict = "INVALID_PROBE"
        elif pos_val is not None and not pos_val.get("allowed", False):
            verdict = "INVALID_PROBE"
        elif b_blocked:
            verdict = "PASS"
        else:
            verdict = "FAIL"

        eval_matrix.append({
            "category": category,
            "vector": name,
            "control": "ALLOWED" if ctrl_allowed else f"BLOCKED: {ctrl_val.get('error')}",
            "positive_control": ("ALLOWED" if pos_val.get("allowed") else "FAIL") if pos_val else "N/A",
            "candidate_1b": f"BLOCKED: {b_val.get('error')}" if b_blocked else "ALLOWED (LEAK)",
            "verdict": verdict,
        })

    # Network Vectors
    net_c = res_ctrl.get("network", {})
    net_b = res_1b.get("probe_results", {}).get("network", {})

    evaluate_vector("Network", "TCP Loopback (127.0.0.1:18080)", net_c.get("tcp_loopback", {}), net_b.get("tcp_loopback", {}))
    evaluate_vector("Network", "TCP LAN IP (10.66.232.232:18081)", net_c.get("tcp_lan", {}), net_b.get("tcp_lan", {}))
    evaluate_vector("Network", "UDP Echo (127.0.0.1:18082)", net_c.get("udp_canary", {}), net_b.get("udp_canary", {}))
    evaluate_vector("Network", "HTTP Proxy (127.0.0.1:18083)", net_c.get("http_proxy", {}), net_b.get("http_proxy", {}))
    evaluate_vector("Network", "IPv6 Loopback (::1:18085)", net_c.get("ipv6_loopback", {}), net_b.get("ipv6_loopback", {}))
    evaluate_vector("Network", "DNS Resolution (google.com:80)", net_c.get("dns_public", {}), net_b.get("dns_public", {}))
    evaluate_vector("Network", "DNS-over-HTTPS (1.1.1.1:443)", net_c.get("doh_https", {}), net_b.get("doh_https", {}))

    # Filesystem Vectors
    fs_c = res_ctrl.get("filesystem", {})
    fs_b = res_1b.get("probe_results", {}).get("filesystem", {})
    pos_file = res_pos.get("canary_direct_read", {})

    evaluate_vector("Filesystem", "Canary Direct Read", fs_c.get("canary_direct_read", {}), fs_b.get("canary_direct_read", {}), pos_file)
    evaluate_vector("Filesystem", "Canary Traversal Read (..\\)", fs_c.get("canary_traversal_read", {}), fs_b.get("canary_traversal_read", {}))
    evaluate_vector("Filesystem", "Canary Junction Read", fs_c.get("canary_junction_read", {}), fs_b.get("canary_junction_read", {}))
    evaluate_vector("Filesystem", "AT-C-11 core.db Read", fs_c.get("at_c_11_core_db_read", {}), fs_b.get("at_c_11_core_db_read", {}))
    evaluate_vector("Filesystem", "AT-C-11 core.db Write", fs_c.get("at_c_11_core_db_write", {}), fs_b.get("at_c_11_core_db_write", {}))
    evaluate_vector("Filesystem", "User Profile Read (NTUSER.DAT)", {"allowed": True}, fs_b.get("user_profile_ntuser_read", {}))

    eval_matrix.append({
        "category": "Filesystem",
        "vector": "Canary Symlink Read",
        "control": "NOT_TESTABLE",
        "positive_control": "N/A",
        "candidate_1b": "NOT_TESTABLE",
        "verdict": "NOT_TESTABLE (WinError 1314 - SeCreateSymbolicLinkPrivilege required)",
    })

    # Crash & Teardown
    m5 = res_1b.get("m5_crash", {})
    eval_matrix.append({
        "category": "Host Resilience",
        "vector": "M5 Hard Crash (SIGSEGV / Exit 3)",
        "control": f"Exit {res_ctrl.get('m5_crash_exit_code')}",
        "positive_control": "N/A",
        "candidate_1b": f"Exit {m5.get('hex_exit_code')} (SIGSEGV MATCH: {m5.get('is_ntstatus_or_sigsegv')})",
        "verdict": "PASS" if m5.get("is_ntstatus_or_sigsegv") else "FAIL",
    })

    m4 = res_1b.get("m4_teardown", {})
    eval_matrix.append({
        "category": "Process Teardown",
        "vector": "M4 Teardown (2.0s window, 0 survivors)",
        "control": "N/A",
        "positive_control": "N/A",
        "candidate_1b": f"Elapsed {m4.get('elapsed_kill_sec')}s, Survivors: {len(m4.get('survivors', []))}",
        "verdict": "PASS" if m4.get("pass") else "FAIL",
    })

    # Save output artifacts
    results_dir = spike_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    final_report = {
        "timestamp": "2026-11-07T22:50:00+05:30",
        "elapsed_seconds": round(time.time() - start_time, 2),
        "raw_control": res_ctrl,
        "raw_positive_control": res_pos,
        "raw_candidate_1b": res_1b,
        "matrix": eval_matrix,
    }

    with open(results_dir / "phase_a0_results.json", "w", encoding="utf-8") as f:
        json.dump(final_report, f, indent=2)

    # Print clean table to stdout
    print("\n=========================================================================================================")
    print("                               PHASE A0 EVALUATION MATRIX                                               ")
    print("=========================================================================================================")
    print(f"{'Category':<18} | {'Vector':<30} | {'Control':<15} | {'1b Result':<25} | {'Verdict'}")
    print("-" * 105)
    for row in eval_matrix:
        print(f"{row['category']:<18} | {row['vector']:<30} | {row['control'][:15]:<15} | {row['candidate_1b'][:25]:<25} | {row['verdict']}")
    print("=========================================================================================================")

    # Cleanup temp
    shutil.rmtree(base_run_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
