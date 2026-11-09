"""Spike S1 Addendum: Phase A3 Test Orchestrator.
Tests Named Pipe Transport with container SID DACL, cross-task isolation, and squatting defense.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

harness_dir = Path(__file__).parent.resolve()
spike_dir = harness_dir.parent.resolve()
sys.path.insert(0, str(harness_dir))

from win_named_pipe import NamedPipeServer
from win_appcontainer import AppContainerRunner
from staging_runtime import StagingRuntimeManager


def parse_pipe_output(raw_output: str) -> dict:
    start_tag = "PIPE_PROBE_START"
    end_tag = "PIPE_PROBE_END"
    if start_tag in raw_output and end_tag in raw_output:
        json_str = raw_output.split(start_tag)[1].split(end_tag)[0].strip()
        try:
            return json.loads(json_str)
        except Exception as e:
            return {"error": f"JSON parse error: {e}", "raw": raw_output}
    return {"raw_output": raw_output}


def run_phase_a3():
    print("==========================================================")
    print("  SPIKE S1 ADDENDUM: PHASE A3 NAMED PIPE ISOLATION        ")
    print("==========================================================")

    staging_dir = spike_dir / "staging_runtime"
    runtime_mgr = StagingRuntimeManager(staging_dir)
    runtime_mgr.verify_runtime_hash()

    ws_a = spike_dir / "temp_run_a3" / "ws_task_a"
    ws_b = spike_dir / "temp_run_a3" / "ws_task_b"
    ws_a.mkdir(parents=True, exist_ok=True)
    ws_b.mkdir(parents=True, exist_ok=True)

    profile_a = "Sentinel.Spike.PipeTaskA"
    profile_b = "Sentinel.Spike.PipeTaskB"

    runner_a = AppContainerRunner(profile_a, ws_a)
    runner_b = AppContainerRunner(profile_b, ws_b)

    runtime_mgr.grant_sid_access(runner_a.sid_string)
    runtime_mgr.grant_sid_access(runner_b.sid_string)

    pipe_name = f"sentinel_test_pipe_{int(time.time())}"
    results = {}

    try:
        # Create pipe server with DACL granted strictly to Container A's SID
        server = NamedPipeServer(pipe_name, runner_a.sid_string)

        def handle_server():
            # Handle handshake from worker
            try:
                server.wait_for_connection()
                # 1. Heartbeat
                req1 = json.loads(server.read_message())
                server.write_message(json.dumps({"status": "PONG", "echo_ts": req1.get("timestamp")}))

                # 2. Tool call
                req2 = json.loads(server.read_message())
                lease_valid = req2.get("lease_token") == "lease_valid_12345"
                server.write_message(json.dumps({
                    "status": "APPROVED" if lease_valid else "REJECTED_STALE_LEASE",
                    "result": {"volume": 1.0, "status": "calculated"}
                }))
            except Exception as e:
                pass
            finally:
                server.close()

        srv_thread = threading.Thread(target=handle_server, daemon=True)
        srv_thread.start()
        time.sleep(0.2)

        # 1. TEST ASSIGNED WORKER (Container A)
        print("[A3] Testing Assigned Worker (Container A) connection...")
        client_script = ws_a / "pipe_client.py"
        shutil.copy2(spike_dir / "worker_payloads" / "pipe_client.py", client_script)

        # Test SQUATTING DEFENSE WHILE FIRST INSTANCE IS OPEN
        print("[A3] Testing Squatting Defense (FILE_FLAG_FIRST_PIPE_INSTANCE)...")
        squat_ok = False
        try:
            squat_server = NamedPipeServer(pipe_name, runner_a.sid_string)
            squat_server.close()
        except OSError as e:
            # WinError 5 (Access is denied) or WinError 231 (All pipe instances are busy)
            squat_ok = True
            results["squatting_defense"] = {"prevented": True, "error": str(e)}

        if not squat_ok:
            results["squatting_defense"] = {"prevented": False, "error": "Second pipe instance was permitted"}

        cmd_a = [str(runtime_mgr.executable), "-u", str(client_script), pipe_name]
        res_a = runner_a.run_process(cmd_a, timeout_sec=5.0)
        results["worker_a"] = parse_pipe_output(res_a["output"])

        srv_thread.join(timeout=2.0)

        # 3. TEST CROSS-TASK ISOLATION (Container B attempting to connect to Container A's pipe)
        print("[A3] Testing Cross-Task Isolation (Container B connecting to Container A's pipe)...")
        # Launch new server instance for Container A, verifying client PID
        server_cross = NamedPipeServer(pipe_name + "_cross", runner_a.sid_string, expected_pid=res_a["pid"])

        def dummy_srv():
            try:
                server_cross.wait_for_connection()
            except Exception:
                pass
            finally:
                server_cross.close()

        t_cross = threading.Thread(target=dummy_srv, daemon=True)
        t_cross.start()
        time.sleep(0.2)

        client_script_b = ws_b / "pipe_client.py"
        shutil.copy2(spike_dir / "worker_payloads" / "pipe_client.py", client_script_b)

        cmd_b = [str(runtime_mgr.executable), "-u", str(client_script_b), pipe_name + "_cross"]
        res_b = runner_b.run_process(cmd_b, timeout_sec=3.0)
        results["cross_task_worker_b"] = parse_pipe_output(res_b["output"])

        # 4. TEST NON-APPCONTAINER PROCESS OF SAME USER
        print("[A3] Testing Non-AppContainer Process connection attempt...")
        # Create server verifying PID for Container A
        server_host = NamedPipeServer(pipe_name + "_host", runner_a.sid_string, expected_pid=res_a["pid"])

        def host_srv():
            try:
                server_host.wait_for_connection()
            except Exception:
                pass
            finally:
                server_host.close()

        t_host = threading.Thread(target=host_srv, daemon=True)
        t_host.start()
        time.sleep(0.2)

        proc_untrusted = subprocess.run(
            [str(runtime_mgr.executable), "-u", str(client_script), pipe_name + "_host"],
            capture_output=True,
            text=True,
            timeout=3.0,
        )
        results["non_appcontainer_host_client"] = parse_pipe_output(proc_untrusted.stdout)

        t_cross.join(timeout=1.0)
        t_host.join(timeout=1.0)

    finally:
        runtime_mgr.revoke_sid_access(runner_a.sid_string)
        runtime_mgr.revoke_sid_access(runner_b.sid_string)
        runner_a.close()
        runner_b.close()
        shutil.rmtree(spike_dir / "temp_run_a3", ignore_errors=True)

    # Verification Evaluation
    assigned_ok = (
        results.get("worker_a", {}).get("connection") == "SUCCESS"
        and results.get("worker_a", {}).get("heartbeat", {}).get("status") == "PONG"
        and results.get("worker_a", {}).get("tool_call", {}).get("status") == "APPROVED"
    )

    cross_denied = (
        results.get("cross_task_worker_b", {}).get("connection") == "DENIED"
        or "PermissionError" in str(results.get("cross_task_worker_b", {}))
    )

    host_denied = (
        results.get("non_appcontainer_host_client", {}).get("connection") == "DENIED"
        or "PermissionError" in str(results.get("non_appcontainer_host_client", {}))
        or "rpc_error" in results.get("non_appcontainer_host_client", {})
    )

    print("\n=========================================================================================================")
    print("                               PHASE A3 EVALUATION MATRIX                                               ")
    print("=========================================================================================================")
    print(f"Assigned Worker A Connection:       {'PASS' if assigned_ok else 'FAIL'}")
    print(f"Cross-Task Worker B Isolation:      {'PASS (ACCESS DENIED)' if cross_denied else 'FAIL (LEAK)'}")
    print(f"Non-AppContainer Client Isolation:  {'PASS (ACCESS DENIED)' if host_denied else 'FAIL (LEAK)'}")
    print(f"Squatting Defense (First Instance): {'PASS' if results.get('squatting_defense', {}).get('prevented') else 'FAIL'}")
    print("=========================================================================================================")

    results_dir = spike_dir / "results"
    with open(results_dir / "phase_a3_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    run_phase_a3()
