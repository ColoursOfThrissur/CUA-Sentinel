"""Sentinel AppContainer Host Runner (Production Bridge).
Orchestrates isolated worker execution inside Windows AppContainer over Named Pipe with Job Object resource limits.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from sentinel_runner.win_container import AppContainerRunner
from sentinel_runner.win_pipe import NamedPipeServer
from sentinel_runner.win_job import JobObject
from sentinel_broker.broker import ExecutionBroker

logger = logging.getLogger("AppContainerHost")


class AppContainerHost:
    def __init__(self, staging_runtime_dir: Path | str, base_workspaces_dir: Path | str | None = None):
        self.staging_runtime_dir = Path(staging_runtime_dir).resolve()
        self.executable = self.staging_runtime_dir / "python.exe"
        if not self.executable.exists():
            raise FileNotFoundError(f"Staging runtime executable not found at: {self.executable}")

        self.workspaces_dir = Path(base_workspaces_dir) if base_workspaces_dir else Path("workspaces").resolve()
        self.workspaces_dir.mkdir(parents=True, exist_ok=True)

    def grant_runtime_sid(self, sid_string: str):
        """Grants read/execute on the staging runtime solely to this container SID."""
        cmd = f'icacls "{self.staging_runtime_dir}" /grant "*{sid_string}:(OI)(CI)RX" /T /Q'
        subprocess.run(cmd, shell=True, check=True)

    def revoke_runtime_sid(self, sid_string: str):
        """Revokes container SID from staging runtime."""
        cmd = f'icacls "{self.staging_runtime_dir}" /remove "*{sid_string}" /T /Q'
        subprocess.run(cmd, shell=True, check=False)

    def run_worker_attempt(
        self,
        task_id: str,
        attempt_id: str,
        lease_token: int,
        goal: str,
        attempt_num: int,
        anti_patterns: str,
        broker: ExecutionBroker,
        timeout_sec: float = 20.0,
    ) -> dict[str, Any]:
        """Runs one worker attempt inside a fresh ephemeral AppContainer."""
        profile_name = f"Sentinel.Attempt.{attempt_id.replace('-', '_')}"
        ws = self.workspaces_dir / attempt_id
        ws.mkdir(parents=True, exist_ok=True)

        # Copy worker script to workspace
        worker_src = Path(__file__).parent.parent / "sentinel_worker" / "worker_main.py"
        worker_dst = ws / "worker_main.py"
        shutil.copy2(worker_src, worker_dst)

        pipe_simple_name = f"sentinel_pipe_{attempt_id.replace('-', '_')}"
        full_pipe_path = f"\\\\.\\pipe\\{pipe_simple_name}"

        worker_final_result = {"status": "TIMEOUT", "output": None}
        pipe_server = None

        try:
            with AppContainerRunner(profile_name, ws) as runner:
                self.grant_runtime_sid(runner.sid_string)

                # Initialize DACL Named Pipe Server
                pipe_server = NamedPipeServer(pipe_simple_name, runner.sid_string)

                def broker_bridge_thread():
                    try:
                        pipe_server.wait_for_connection()
                        # Send initial envelope
                        envelope = {
                            "goal": goal,
                            "attempt_num": attempt_num,
                            "lease_token": lease_token,
                            "anti_patterns": anti_patterns,
                        }
                        pipe_server.write_message(json.dumps(envelope) + "\n")

                        # Handle worker requests
                        while True:
                            msg_str = pipe_server.read_message()
                            if not msg_str:
                                break
                            msg = json.loads(msg_str.strip())
                            msg_type = msg.get("type")

                            if msg_type == "TOOL_CALL":
                                call_res = broker.dispatch_call(
                                    attempt_id=attempt_id,
                                    lease_token=msg.get("lease_token", lease_token),
                                    tool_name=msg.get("tool_name"),
                                    params=msg.get("params", {}),
                                )
                                pipe_server.write_message(json.dumps(call_res) + "\n")

                            elif msg_type == "TASK_COMPLETE":
                                worker_final_result.update(msg)
                                break
                    except Exception as e:
                        logger.error(f"Pipe bridge error: {e}")
                    finally:
                        if pipe_server:
                            pipe_server.close()

                bridge_t = threading.Thread(target=broker_bridge_thread, daemon=True)
                bridge_t.start()

                # Set up Job Object with resource caps
                job = JobObject(
                    name=f"Job_{attempt_id.replace('-', '_')}",
                    memory_limit_mb=100,
                    cpu_rate_percent=12.5,
                    kill_on_close=True,
                )

                # Run process inside AppContainer
                cmd = [str(self.executable), "-u", "worker_main.py", full_pipe_path]
                res = runner.run_process(cmd, timeout_sec=timeout_sec, job_object=job, sanitize_env=True)
                bridge_t.join(timeout=2.0)
                worker_final_result["process_exit_code"] = res.get("exit_code")
                worker_final_result["raw_stdout"] = res.get("output")

        finally:
            self.revoke_runtime_sid(runner.sid_string)
            if pipe_server:
                pipe_server.close()

        return worker_final_result
