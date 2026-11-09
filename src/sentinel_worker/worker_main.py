"""Sentinel Isolated Worker Main (runs inside Windows AppContainer).
Communicates with the host Execution Broker strictly over DACL Named Pipe.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


class WorkerPipeClient:
    def __init__(self, pipe_path: str):
        self.pipe_path = pipe_path
        self._pipe = open(pipe_path, "r+b", buffering=0)

    def read_message(self) -> dict:
        line = self._pipe.readline()
        if not line:
            raise EOFError("Named pipe was closed by host")
        return json.loads(line.decode("utf-8").strip())

    def send_message(self, msg: dict):
        line = json.dumps(msg).encode("utf-8") + b"\n"
        self._pipe.write(line)
        self._pipe.flush()

    def call_tool(self, tool_name: str, params: dict, lease_token: int) -> dict:
        req = {
            "type": "TOOL_CALL",
            "tool_name": tool_name,
            "params": params,
            "lease_token": lease_token,
        }
        self.send_message(req)
        resp = self.read_message()
        return resp

    def close(self):
        try:
            self._pipe.close()
        except Exception:
            pass


def execute_agent_logic(client: WorkerPipeClient, task_envelope: dict):
    goal = task_envelope.get("goal", "")
    attempt_num = task_envelope.get("attempt_num", 1)
    lease_token = task_envelope.get("lease_token", 0)
    anti_patterns = task_envelope.get("anti_patterns", "")
    workspace = Path(".").resolve()

    # The agent inspects anti-patterns to adapt
    output_filename = "result_artifact.txt"
    target_file = workspace / output_filename

    if attempt_num == 1 and not anti_patterns:
        # Simulation: Attempt 1 makes a common defect (writes empty file)
        target_file.write_text("", encoding="utf-8")
        client.send_message({
            "type": "TASK_COMPLETE",
            "artifact_path": str(target_file),
            "status": "COMPLETED_ATTEMPT_1",
        })
    else:
        # Adaptation: Attempt 2 reads anti-patterns and writes valid content
        # Also invokes a host tool to demonstrate intercommunication
        tool_res = client.call_tool("echo_verify", {"nonce": "sentinel_nonce_123"}, lease_token)
        
        valid_content = f"VALID_ARTIFACT_DATA\nNonce: {tool_res.get('result', {}).get('nonce')}\n"
        target_file.write_text(valid_content, encoding="utf-8")

        synthesized_code = (
            "path = params.get('path', 'output.txt')\n"
            "with open(path, 'w') as f: f.write('VALID_ARTIFACT_DATA\\n')\n"
            "result = {'written': True, 'path': path}\n"
        )

        client.send_message({
            "type": "TASK_COMPLETE",
            "artifact_path": str(target_file),
            "status": "COMPLETED_ATTEMPT_2",
            "synthesized_code": synthesized_code,
            "parameters_schema": {"path": "str"},
        })


def main():
    if len(sys.argv) < 2:
        print("Usage: python worker_main.py <pipe_path>", file=sys.stderr)
        sys.exit(1)

    pipe_path = sys.argv[1]
    client = WorkerPipeClient(pipe_path)
    try:
        # 1. Read initial task envelope from host
        envelope = client.read_message()
        # 2. Run agent execution
        execute_agent_logic(client, envelope)
    finally:
        client.close()


if __name__ == "__main__":
    main()
