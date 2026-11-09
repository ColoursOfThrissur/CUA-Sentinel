"""Spike S1 Addendum: Phase A7 Full Envelope Telemetry (M6).
Simulates full Sentinel runtime envelope:
1. Control Plane stub with SQLite WAL engine (concurrent transactions)
2. Model Gateway memory footprint (simulated 3.5 GB 7B Q4 allocation)
3. Active worker process running inside Windows AppContainer communicating over Named Pipe
Samples physical RAM and pagefile metrics to assert RAM floor >= 2.5 GB.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import threading
import time
from pathlib import Path

import psutil

harness_dir = Path(__file__).parent.resolve()
spike_dir = harness_dir.parent.resolve()
sys.path.insert(0, str(harness_dir))

from staging_runtime import StagingRuntimeManager
from win_appcontainer import AppContainerRunner
from win_named_pipe import NamedPipeServer


def run_phase_a7(duration_sec: float = 30.0):
    print("==========================================================")
    print("  SPIKE S1 ADDENDUM: PHASE A7 FULL ENVELOPE TELEMETRY     ")
    print("==========================================================")

    staging_dir = spike_dir / "staging_runtime"
    runtime_mgr = StagingRuntimeManager(staging_dir)
    runtime_mgr.verify_runtime_hash()

    ws = spike_dir / "temp_envelope_ws"
    ws.mkdir(parents=True, exist_ok=True)
    db_path = spike_dir / "temp_envelope_core.db"

    # 1. Initialize SQLite in WAL mode
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY, ts REAL, data TEXT);")
    conn.commit()
    conn.close()

    db_running = threading.Event()
    db_running.set()

    def db_writer_thread():
        c = sqlite3.connect(str(db_path))
        while db_running.is_set():
            c.execute("INSERT INTO audit_log (ts, data) VALUES (?, ?);", (time.time(), "envelope_audit_event_record"))
            c.commit()
            time.sleep(0.05)
        c.close()

    db_thread = threading.Thread(target=db_writer_thread, daemon=True)
    db_thread.start()

    # 2. Model Gateway: Allocate 3.5 GB simulated model weights
    print("Allocating simulated 3.5 GB 7B Q4 Model Gateway footprint...")
    model_chunks = []
    chunk_size = 64 * 1024 * 1024  # 64 MB
    num_chunks = int(3.5 * 1024 / 64)
    try:
        for _ in range(num_chunks):
            chunk = bytearray(b"M" * chunk_size)
            model_chunks.append(chunk)
        print(f"Model Gateway active: {len(model_chunks) * 64} MB committed in physical memory.")
    except MemoryError:
        print("Notice: System memory bounded, allocated maximal available model chunks.")

    # 3. Telemetry Sampler
    telemetry_samples = []
    sample_running = threading.Event()
    sample_running.set()

    def telemetry_thread():
        while sample_running.is_set():
            mem = psutil.virtual_memory()
            swap = psutil.swap_memory()
            telemetry_samples.append({
                "ts": time.time(),
                "available_mb": mem.available / (1024 * 1024),
                "total_mb": mem.total / (1024 * 1024),
                "used_percent": mem.percent,
                "swap_used_mb": swap.used / (1024 * 1024),
            })
            time.sleep(0.5)

    sampler = threading.Thread(target=telemetry_thread, daemon=True)
    sampler.start()

    # 4. AppContainer Worker & Named Pipe Server
    profile_name = "Sentinel.Spike.Envelope"
    pipe_simple_name = f"sentinel_envelope_pipe_{int(time.time())}"

    worker_code = f"""
import json
import time

pipe_path = r"\\\\.\\pipe\\{pipe_simple_name}"
with open(pipe_path, "r+b", buffering=0) as pipe:
    for i in range(15):
        req = json.dumps({{"step": i, "status": "COMPUTE"}}).encode() + b"\\n"
        pipe.write(req)
        resp = pipe.readline().decode()
        time.sleep(0.4)
    pipe.write(b"DONE\\n")

print("WORKER_ENVELOPE_SUCCESS")
"""

    worker_file = ws / "worker_envelope.py"
    worker_file.write_text(worker_code, encoding="utf-8")

    try:
        with AppContainerRunner(profile_name, ws) as runner:
            runtime_mgr.grant_sid_access(runner.sid_string)
            server = NamedPipeServer(pipe_simple_name, runner.sid_string)

            def pipe_server_thread():
                try:
                    server.wait_for_connection()
                    for _ in range(15):
                        msg = server.read_message()
                        if not msg:
                            break
                        server.write_message(json.dumps({"ack": True, "ts": time.time()}))
                except Exception as e:
                    print(f"Server pipe exception: {e}")
                finally:
                    server.close()

            srv_thread = threading.Thread(target=pipe_server_thread, daemon=True)
            srv_thread.start()

            # Execute worker process
            res = runner.run_process(
                [str(runtime_mgr.executable), "-u", str(worker_file)],
                timeout_sec=duration_sec,
                sanitize_env=True,
            )
            print("Worker output:", res["output"].strip())
            srv_thread.join(timeout=2.0)
    finally:
        runtime_mgr.revoke_sid_access(runner.sid_string)
        db_running.clear()
        db_thread.join(timeout=2.0)
        sample_running.clear()
        sampler.join(timeout=2.0)
        model_chunks.clear()  # Free model memory
        shutil.rmtree(ws, ignore_errors=True)
        for ext in ["", "-wal", "-shm"]:
            p = Path(f"{db_path}{ext}")
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass

    # Analyze telemetry
    avail_readings = [s["available_mb"] for s in telemetry_samples]
    min_avail_mb = min(avail_readings) if avail_readings else 0
    avg_avail_mb = sum(avail_readings) / len(avail_readings) if avail_readings else 0
    max_swap_mb = max(s["swap_used_mb"] for s in telemetry_samples) if telemetry_samples else 0
    min_swap_mb = min(s["swap_used_mb"] for s in telemetry_samples) if telemetry_samples else 0
    swap_delta_mb = max_swap_mb - min_swap_mb

    report = {
        "duration_sec": duration_sec,
        "sample_count": len(telemetry_samples),
        "min_available_mb": round(min_avail_mb, 1),
        "avg_available_mb": round(avg_avail_mb, 1),
        "swap_delta_mb": round(swap_delta_mb, 1),
        "ram_floor_target_mb": 2500.0,
        "ram_floor_maintained": min_avail_mb >= 2500.0,
        "zero_sustained_pagefile_growth": swap_delta_mb < 500.0,
        "pass": min_avail_mb >= 2500.0 and swap_delta_mb < 500.0,
    }

    print("\n=========================================================================================================")
    print("                               PHASE A7 EVALUATION MATRIX (M6)                                          ")
    print("=========================================================================================================")
    print(f"Minimum Available Physical RAM: {report['min_available_mb']} MB (Frozen Target Floor: >= 2500.0 MB)")
    print(f"Average Available Physical RAM: {report['avg_available_mb']} MB")
    print(f"Peak Pagefile Swap Delta:       {report['swap_delta_mb']} MB (Target: < 500.0 MB)")
    print(f"OVERALL PHASE A7 RESULT:        {'PASS' if report['pass'] else 'FAIL'}")
    print("=========================================================================================================")

    results_dir = spike_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    with open(results_dir / "phase_a7_results.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)


if __name__ == "__main__":
    run_phase_a7(30.0)
