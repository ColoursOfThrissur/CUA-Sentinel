"""Empirical LLM Capability & Scaffolding Probe.
Measures the percentage of hand-holding required for qwen3.5:9b to achieve tasks
across different domains and scaffolding tiers.
"""
from __future__ import annotations

import ast
import csv
import io
import json
import subprocess
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sentinel_core.llm_gateway import LLMGateway
from sentinel_core.prompt_scaffolder import PromptScaffolder, ScaffoldingLevel


def run_probe_matrix():
    gw = LLMGateway()
    if not gw.is_available():
        print("ERROR: Ollama is not available at http://127.0.0.1:11434")
        return

    workspaces = Path("workspaces")
    workspaces.mkdir(exist_ok=True)

    test_cases = [
        {
            "domain": "code",
            "goal": "Write Python code implementing an LRU Cache data structure with get and put methods",
            "verifier": "verify_lru",
        },
        {
            "domain": "data",
            "goal": "Generate a CSV dataset of monthly cloud server downtime and incident severity for 2026",
            "verifier": "verify_csv",
        },
        {
            "domain": "3d",
            "goal": "Create a 3D medieval warhammer with spiked head in Blender 4.5",
            "verifier": "verify_blender_code",
        },
    ]

    scaffolding_tiers = [
        (ScaffoldingLevel.LEVEL_0_RAW, "0% Hand-Holding (Raw Prompt)"),
        (ScaffoldingLevel.LEVEL_1_FORMAT, "25% Hand-Holding (Format Only)"),
        (ScaffoldingLevel.LEVEL_2_GUARDED, "65% Hand-Holding (Domain Guardrails)"),
    ]

    results = []

    print("=" * 80)
    print("STARTING EMPIRICAL LLM CAPABILITY PROBES ON qwen3.5:9b")
    print("=" * 80)

    for tc in test_cases:
        domain = tc["domain"]
        goal = tc["goal"]
        vfn = tc["verifier"]

        print(f"\n--- Testing Domain: [{domain.upper()}] ---")
        print(f"Goal: {goal}")

        for level, label in scaffolding_tiers:
            sys_prompt = PromptScaffolder.build_system_prompt(domain, level)
            user_prompt = PromptScaffolder.build_user_prompt(
                goal=goal,
                domain=domain,
                artifact_path=str(workspaces / f"probe_{domain}_{level.value}.out"),
                level=level,
            )

            print(f"\n> Tier: {label}")
            t0 = time.time()
            try:
                raw_out = gw.generate(
                    prompt=user_prompt,
                    system=sys_prompt if sys_prompt else None,
                    max_tokens=3072,
                    temperature=0.2,
                )
                dt = time.time() - t0
                print(f"  Generated in {dt:.2f}s ({len(raw_out)} chars)")

                # Run domain verification
                passed, reason = evaluate_output(domain, vfn, raw_out)
                status_str = "PASS" if passed else "FAIL"
                print(f"  Result: [{status_str}] - Reason: {reason}")

                results.append({
                    "domain": domain,
                    "tier": label,
                    "level": level.value,
                    "passed": passed,
                    "reason": reason,
                    "duration_sec": round(dt, 2),
                })
            except Exception as e:
                print(f"  Result: [ERROR] - {e}")
                results.append({
                    "domain": domain,
                    "tier": label,
                    "level": level.value,
                    "passed": False,
                    "reason": f"Exception: {e}",
                    "duration_sec": 0,
                })

    print("\n" + "=" * 80)
    print("SUMMARY RESULTS MATRIX:")
    print("=" * 80)
    print(f"{'Domain':<10} | {'Scaffolding Tier':<40} | {'Status':<6} | {'Reason':<30}")
    print("-" * 90)
    for r in results:
        stat = "PASS" if r["passed"] else "FAIL"
        print(f"{r['domain']:<10} | {r['tier']:<40} | {stat:<6} | {r['reason'][:30]:<30}")

    # Save summary report to JSON
    with open("workspaces/probe_summary.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)


def evaluate_output(domain: str, verifier: str, raw_text: str) -> tuple[bool, str]:
    """Domain-specific evaluation of raw LLM outputs."""
    gw = LLMGateway()

    if domain == "code":
        code = gw.extract_python_code(raw_text)
        if not code or len(code) < 30:
            return False, "Failed to extract Python code block"
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, f"SyntaxError: {e.msg} line {e.lineno}"

        defined = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
        if "LRUCache" not in defined:
            return False, f"Missing LRUCache class, defined: {list(defined)}"

        # Test execution & assertions
        try:
            test_harness = """
import sys
# Run contract test
cache = target_module.LRUCache(2)
cache.put(1, 100)
cache.put(2, 200)
assert cache.get(1) == 100, "Should get 100"
cache.put(3, 300) # evicts 2
assert cache.get(2) in (-1, None), f"Key 2 should be evicted, got {cache.get(2)}"
assert cache.get(1) == 100, "Key 1 should still exist"
assert cache.get(3) == 300, "Key 3 should exist"
"""
            probe_file = Path("workspaces/temp_probe_code.py")
            probe_file.write_text(code, encoding="utf-8")

            runner_cmd = [
                sys.executable,
                "-c",
                f"import sys; sys.path.insert(0, 'workspaces'); import temp_probe_code as target_module; {test_harness}"
            ]
            res = subprocess.run(runner_cmd, capture_output=True, text=True, timeout=5)
            if res.returncode != 0:
                err = res.stderr.strip().splitlines()[-1] if res.stderr.strip() else f"Code {res.returncode}"
                return False, f"Contract failed: {err}"
            return True, "Code is valid, passes all contract assertions"
        except Exception as e:
            return False, f"Execution runner error: {e}"

    elif domain == "data":
        # Extract CSV
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        # Strip code fences if model wrapped in ```csv ... ```
        clean_lines = [l for l in lines if not l.startswith("```")]
        csv_text = "\n".join(clean_lines)

        try:
            reader = list(csv.reader(io.StringIO(csv_text)))
            if len(reader) < 3:
                return False, f"Too few rows ({len(reader)} rows, need >= 3)"
            if len(reader[0]) < 3:
                return False, f"Too few columns ({len(reader[0])} cols, need >= 3)"
            return True, f"Valid CSV: {len(reader)} rows, {len(reader[0])} columns"
        except Exception as e:
            return False, f"CSV Parse error: {e}"

    elif domain == "3d":
        code = gw.extract_python_code(raw_text)
        if not code or len(code) < 30:
            return False, "Failed to extract Python script"

        # Check for Blender 4.5 deprecated API traps
        if "bpy.ops.export_scene.obj" in code:
            return False, "Deprecated API: bpy.ops.export_scene.obj removed in Blender 4.0+"
        if ".inputs['Specular']" in code or '.inputs["Specular"]' in code:
            return False, "Deprecated API: Principled BSDF Specular float input removed in 4.0+"
        if "bpy.ops.wm.read_factory_settings" not in code:
            return False, "Missing scene initialization (read_factory_settings)"
        if "obj_export" not in code:
            return False, "Missing obj_export operator call"

        return True, "Script strictly obeys Blender 4.5 LTS API constraints"

    return False, "Unknown domain"


if __name__ == "__main__":
    run_probe_matrix()
