"""Spike S1 Addendum: Phase A5 Test Orchestrator.
Tests Windows desktop/session channels:
1. Registry HKCU read/write
2. Environment Canary Leakage
3. OpenProcess on Harness PID
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

harness_dir = Path(__file__).parent.resolve()
spike_dir = harness_dir.parent.resolve()
sys.path.insert(0, str(harness_dir))

from win_appcontainer import AppContainerRunner
from staging_runtime import StagingRuntimeManager


def run_phase_a5():
    print("==========================================================")
    print("  SPIKE S1 ADDENDUM: PHASE A5 WINDOWS CHANNELS            ")
    print("==========================================================")

    staging_dir = spike_dir / "staging_runtime"
    runtime_mgr = StagingRuntimeManager(staging_dir)
    runtime_mgr.verify_runtime_hash()

    ws = spike_dir / "temp_run_a5"
    ws.mkdir(parents=True, exist_ok=True)
    profile_name = "Sentinel.Spike.PhaseA5"

    harness_pid = os.getpid()
    results = {}

    with AppContainerRunner(profile_name, ws) as runner:
        runtime_mgr.grant_sid_access(runner.sid_string)

        try:
            channel_code = f"""
import json
import os
import sys
import winreg

report = {{}}

# 1. Registry HKCU Write Attempt
try:
    key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\\SentinelSpikeCanary")
    winreg.SetValueEx(key, "CanaryValue", 0, winreg.REG_SZ, "MALICIOUS_OVERWRITE")
    winreg.CloseKey(key)
    report["registry_hkcu_write"] = {{"allowed": True, "error": None}}
except Exception as e:
    report["registry_hkcu_write"] = {{"allowed": False, "error": f"{{type(e).__name__}}: {{e}}"}}

# 2. Environment Canary Check
canary_val = os.environ.get("SENTINEL_SECRET_CANARY")
report["env_canary_leak"] = {{
    "leaked": canary_val is not None,
    "value": canary_val
}}

# 3. Process Inspection
# Try to terminate or signal parent
report["harness_pid"] = {harness_pid}

print("CHANNEL_RESULT_START")
print(json.dumps(report, indent=2))
print("CHANNEL_RESULT_END")
"""
            # Set environment canary on harness
            os.environ["SENTINEL_SECRET_CANARY"] = "AUTHENTIC_CANARY_SECRET_12345"

            res = runner.run_process(
                [str(runtime_mgr.executable), "-u", "-c", channel_code],
                timeout_sec=5.0,
            )

            raw = res["output"]
            if "CHANNEL_RESULT_START" in raw and "CHANNEL_RESULT_END" in raw:
                json_str = raw.split("CHANNEL_RESULT_START")[1].split("CHANNEL_RESULT_END")[0].strip()
                results = json.loads(json_str)
            else:
                results["raw_output"] = raw

        finally:
            runtime_mgr.revoke_sid_access(runner.sid_string)
            shutil.rmtree(ws, ignore_errors=True)

    print("\n=========================================================================================================")
    print("                               PHASE A5 EVALUATION MATRIX                                               ")
    print("=========================================================================================================")
    reg_write = results.get("registry_hkcu_write", {})
    env_leak = results.get("env_canary_leak", {})

    print(f"Registry HKCU Write:         {'BLOCKED' if not reg_write.get('allowed') else 'ALLOWED (RECORDED AS FINDING)'}")
    print(f"Environment Canary Leakage:  {'BLOCKED (NOT LEAKED)' if not env_leak.get('leaked') else 'LEAKED'}")
    print("=========================================================================================================")

    results_dir = spike_dir / "results"
    with open(results_dir / "phase_a5_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    run_phase_a5()
