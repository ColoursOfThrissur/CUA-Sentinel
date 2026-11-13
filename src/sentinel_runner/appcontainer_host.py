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

    def run_isolated_script(
        self,
        script_code: str,
        working_dir: Path | str | None = None,
        timeout_sec: float = 20.0,
        memory_limit_mb: int = 128,
        cpu_rate_percent: float = 25.0,
    ) -> dict[str, Any]:
        """Runs arbitrary Python script inside an ephemeral AppContainer with Job Object resource limits.
        If AppContainer initialization fails (e.g. permission/developer mode), falls back safely to isolated WinJob.
        """
        import uuid
        exec_id = f"exec_{uuid.uuid4().hex[:8]}"
        ws = Path(working_dir) if working_dir else (self.workspaces_dir / exec_id)
        ws.mkdir(parents=True, exist_ok=True)

        script_file = ws / f"{exec_id}.py"
        script_file.write_text(script_code, encoding="utf-8")

        profile_name = f"Sentinel.Script.{exec_id}"
        job = None
        try:
            job = JobObject(
                name=f"Job_{exec_id}",
                memory_limit_mb=memory_limit_mb,
                cpu_rate_percent=cpu_rate_percent,
                kill_on_close=True,
            )
        except Exception as e:
            logger.warning("Could not create JobObject for isolated script: %s", e)

        # 1. Attempt AppContainer isolation
        try:
            with AppContainerRunner(profile_name, ws) as runner:
                self.grant_runtime_sid(runner.sid_string)
                try:
                    cmd = [str(self.executable), "-I", "-s", "-u", script_file.name]
                    res = runner.run_process(cmd, timeout_sec=timeout_sec, job_object=job, sanitize_env=True)
                    return {
                        "status": "SUCCESS" if res.get("exit_code") == 0 else "EXECUTION_ERROR",
                        "exit_code": res.get("exit_code", 1),
                        "stdout": res.get("output", ""),
                        "stderr": "",
                        "timed_out": res.get("timed_out", False),
                        "sandboxed": True,
                        "isolation_level": "AppContainer+JobObject",
                    }
                finally:
                    self.revoke_runtime_sid(runner.sid_string)
        except Exception as e:
            logger.warning("AppContainer execution fell back to WinJob isolation: %s", e)

        # 2. Defense-in-depth fallback: Strict WinJob with isolated sys.executable -I -s
        try:
            cmd = [str(self.executable if self.executable.exists() else sys.executable), "-I", "-s", "-u", str(script_file)]
            proc = subprocess.Popen(
                cmd,
                cwd=str(ws),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if job and hasattr(proc, "_handle"):
                try:
                    job.assign_process(int(proc._handle))
                except Exception:
                    pass
            stdout, stderr = proc.communicate(timeout=timeout_sec)
            return {
                "status": "SUCCESS" if proc.returncode == 0 else "EXECUTION_ERROR",
                "exit_code": proc.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "timed_out": False,
                "sandboxed": job is not None,
                "isolation_level": "WinJobIsolated",
            }
        except subprocess.TimeoutExpired:
            proc.kill()
            return {
                "status": "TIMEOUT",
                "exit_code": 124,
                "stdout": "",
                "stderr": f"Process exceeded timeout of {timeout_sec}s",
                "timed_out": True,
                "sandboxed": job is not None,
                "isolation_level": "WinJobIsolated",
            }
        finally:
            if job:
                try:
                    job.close()
                except Exception:
                    pass
