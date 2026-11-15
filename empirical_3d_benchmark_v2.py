import sys
import os
import json
import base64
import time
from pathlib import Path

sys.path.insert(0, "src")

from sentinel_core.llm_gateway import LLMGateway
from sentinel_gym.sensor_rig import BlenderSensorRig
from sentinel_gym.critic import HarshCritic
from sentinel_broker.organs.blender import find_blender_executable, _run_blender_script

NEW_TEST_CASES = [
    {
        "tier": "Level 1 (Simple)",
        "name": "Bolted_Pipe_Flange",
        "goal": "Synthesize a 3D industrial bolted pipe flange assembly with a central hollow pipe cylinder, a thick circular flange collar ring with 6 hexagonal mounting bolts radially distributed around the collar, and a contrasting rubber gasket ring with matte dark rubber and polished steel metallic shaders.",
        "filename": "bench2_l1_pipe_flange.obj",
    },
    {
        "tier": "Level 2 (Intermediate)",
        "name": "Articulated_Robotic_Gripper",
        "goal": "Synthesize a 3D articulated two-finger robotic gripper featuring a central rectangular servo chassis body, two counter-opposed articulated claw fingers pivoting from the chassis front, and high-friction rubber grip pads on the inner finger tips, using metallic gold brass for the chassis and matte black for the claws and pads.",
        "filename": "bench2_l2_gripper.obj",
    },
    {
        "tier": "Level 3 (Complex)",
        "name": "Rocket_Engine_Gimbal",
        "goal": "Synthesize a 3D aerospace rocket engine gimbal assembly with a conical bell exhaust nozzle tilted at 20 degrees, an outer circular gimbal ring cradle supporting the nozzle pivot, four overhead fuel turbopump feed pipes entering the injector dome, and heat-resistant titanium alloy and copper combustion chamber shaders.",
        "filename": "bench2_l3_rocket_gimbal.obj",
    },
]

def run_benchmark():
    out_dir = Path("workspaces/empirical_benchmarks_v2").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    gw = LLMGateway(endpoint="http://127.0.0.1:11434", default_model="qwen2.5-coder:14b")
    rig = BlenderSensorRig(blender_path=find_blender_executable())
    critic = HarshCritic(llm_gateway=gw, passing_threshold=0.82, vision_model="qwen3-vl:8b")

    results = []

    print("=" * 80)
    print("EMPIRICAL 3D BENCHMARK V2: NEW SET WITH ARCHITECTURAL PARENTING GUIDANCE")
    print("=" * 80)

    for tc in NEW_TEST_CASES:
        tier = tc["tier"]
        name = tc["name"]
        goal = tc["goal"]
        obj_file = out_dir / tc["filename"]

        print(f"\n[{tier}] Synthesizing: {name}")
        print(f"Goal: {goal}")

        t0 = time.time()

        # 1. Synthesize Code via Upgraded Hierarchical Spatial Pipeline
        print("  -> Generating Spatial Blueprint & Blender 4.5 Python Script...")
        code = gw.generate_blender_code(goal=goal, output_obj_path=str(obj_file))
        code_file = out_dir / f"{name}_script.py"
        code_file.write_text(code, encoding="utf-8")
        print(f"  -> Script generated ({len(code)} bytes). Running in headless Blender...")

        # 2. Run Blender to build model
        blender_res = _run_blender_script(rig.blender_path, code, str(obj_file), timeout=45.0)
        blender_ok = blender_res.get("exit_code") == 0 and obj_file.exists()

        if not blender_ok:
            print(f"  [!] Blender Execution Failed! Stderr: {blender_res.get('stderr', '')[:200]}")
            results.append({
                "tier": tier,
                "name": name,
                "goal": goal,
                "success": False,
                "error": blender_res.get("stderr") or "Blender failure",
                "code": code,
            })
            continue

        print(f"  -> Blender built OBJ successfully ({obj_file.stat().st_size} bytes).")

        # 3. Empirical Sensor Rig: Compute Topology & Render 4 Perspectives
        print("  -> Sensor Rig rendering 4 snapshots (iso, front, top, detail) and extracting metrics...")
        insp_dir = out_dir / f"{name}_inspection"
        insp = rig.inspect_model(obj_file, output_dir=insp_dir)

        bbox = insp.metrics.get("bounding_box", {})
        parts = insp.metrics.get("part_names", [])
        mats = insp.metrics.get("materials", [])
        ground_z = bbox.get("ground_z")
        ground_spread = bbox.get("ground_spread")

        print(f"  -> Metrics: {len(parts)} parts, {insp.metrics.get('vertex_count')} verts, {insp.metrics.get('non_manifold_edges')} non-manifold")
        print(f"  -> Parts list: {', '.join(parts[:8])}")
        print(f"  -> Materials ({len(mats)}): {', '.join(mats[:6])}")
        print(f"  -> Bounding Box: dx={bbox.get('dx')}, dy={bbox.get('dy')}, dz={bbox.get('dz')} (Volume: {bbox.get('volume')})")
        print(f"  -> Ground Plane: min_z={ground_z}, ground_spread={ground_spread}")
        print(f"  -> Snapshots generated: {list(insp.snapshots.keys())}")

        # 4. Vision Critic: Multimodal Evaluation via qwen3-vl:8b
        print("  -> Running Vision Critic (qwen3-vl:8b) on iso.png render...")
        scorecard = critic.evaluate_3d_model(goal, insp)

        elapsed = time.time() - t0
        print(f"  -> Vision Scorecard: Score={scorecard.score:.2f} ({int(scorecard.score*100)}%), Mode={scorecard.evaluation_mode}")
        print(f"     * Structural Integrity: {scorecard.structural_integrity}/25")
        print(f"     * Feature Specificity:  {scorecard.feature_specificity}/25")
        print(f"     * Material Separation:  {scorecard.material_separation}/25")
        print(f"     * Proportion Realism:   {scorecard.proportion_realism}/25")
        print(f"     * Critique: {scorecard.critique}")
        print(f"     * Remediation: {scorecard.remediation_advice}")
        print(f"  -> Completed in {elapsed:.1f}s")

        results.append({
            "tier": tier,
            "name": name,
            "goal": goal,
            "success": True,
            "obj_path": str(obj_file),
            "script_path": str(code_file),
            "snapshots": insp.snapshots,
            "metrics": insp.metrics,
            "scorecard": {
                "score": scorecard.score,
                "passed": scorecard.passed,
                "mode": scorecard.evaluation_mode,
                "structural_integrity": scorecard.structural_integrity,
                "feature_specificity": scorecard.feature_specificity,
                "material_separation": scorecard.material_separation,
                "proportion_realism": scorecard.proportion_realism,
                "critique": scorecard.critique,
                "remediation": scorecard.remediation_advice,
                "anti_pattern": scorecard.anti_pattern_signature,
            },
            "elapsed_sec": round(elapsed, 1),
        })

    summary_file = out_dir / "benchmark_summary.json"
    summary_file.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("\n" + "=" * 80)
    print(f"BENCHMARK V2 COMPLETE. Summary saved to {summary_file}")
    print("=" * 80)

if __name__ == "__main__":
    run_benchmark()
