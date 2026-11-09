"""Worker Named Pipe client payload for Phase A3 using native Python file I/O.
Requires zero external C-types or DLLs, fully compatible with AppContainer security policies.
"""
from __future__ import annotations

import json
import sys
import time


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"status": "ERROR", "error": "Missing pipe name argument"}))
        return

    pipe_name = sys.argv[1]
    pipe_path = f"\\\\.\\pipe\\{pipe_name}"

    results = {}
    f = None

    # Connect to pipe with retries
    t_start = time.time()
    while time.time() - t_start < 5.0:
        try:
            f = open(pipe_path, "r+b", buffering=0)
            results["connection"] = "SUCCESS"
            break
        except (FileNotFoundError, PermissionError) as e:
            if isinstance(e, PermissionError):
                results["connection"] = "DENIED"
                results["error"] = f"PermissionError: {e}"
                print("PIPE_PROBE_START")
                print(json.dumps(results, indent=2))
                print("PIPE_PROBE_END")
                return
            time.sleep(0.05)
        except Exception as e:
            time.sleep(0.05)

    if not f:
        results["connection"] = "TIMEOUT"
        results["error"] = "Connection timed out"
        print("PIPE_PROBE_START")
        print(json.dumps(results, indent=2))
        print("PIPE_PROBE_END")
        return

    try:
        # 1. Heartbeat
        msg_hb = json.dumps({"type": "heartbeat", "timestamp": time.time()}).encode("utf-8")
        f.write(msg_hb)
        raw_resp = f.read(4096)
        results["heartbeat"] = json.loads(raw_resp.decode("utf-8"))

        # 2. Tool Call with Lease Token
        msg_tool = json.dumps({
            "type": "tool_call",
            "lease_token": "lease_valid_12345",
            "tool_name": "calc_bounds",
            "args": {"shape": "cube", "dimensions": [1, 1, 1]}
        }).encode("utf-8")
        f.write(msg_tool)
        raw_tool_resp = f.read(4096)
        results["tool_call"] = json.loads(raw_tool_resp.decode("utf-8"))

    except Exception as e:
        results["rpc_error"] = f"{type(e).__name__}: {e}"
    finally:
        f.close()

    print("PIPE_PROBE_START")
    print(json.dumps(results, indent=2))
    print("PIPE_PROBE_END")


if __name__ == "__main__":
    main()
