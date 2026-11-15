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
from sentinel_broker.organs.blender import find_blender_executable

TEST_CASES = [
    {
        "tier": "Level 1 (Simple)",
        "name": "Pillow_Block_Bearing",
        "goal": "Synthesize a 3D industrial flanged pillow block bearing featuring a flat rectangular base plate with mounting bolt holes, a semi-cylindrical central bearing housing, and an inner cylindrical rotating shaft collar with contrasting polished steel and matte cast-iron finishes.",
        "filename": "bench_l1_bearing.obj",
    },
    {
        "tier": "Level 2 (Intermediate)",
        "name": "Hydraulic_Actuator",
        "goal": "Synthesize a 3D heavy-duty hydraulic actuator with a cylindrical outer barrel, chrome-plated extending piston rod, pivot clevis mounting lugs at both ends, and two hydraulic fluid port fittings.",
        "filename": "bench_l2_actuator.obj",
    },
    {
        "tier": "Level 3 (Complex)",
        "name": "Astronomical_Telescope",
        "goal": "Synthesize a 3D astronomical telescope assembly featuring an optical tube tilted upward at 35 degrees, a front cylindrical dew shield, an eyepiece focus knob, a central equatorial mount hub at height Z=1.0m, and three splayed tripod legs extending outward from the hub down to ground level Z=0 with a wide triangular base spread, featuring polished bronze and deep enameled blue finishes.",
        "filename": "bench_l3_telescope.obj",
    },
]

def run_benchmark():
    out_dir = Path("workspaces/empirical_benchmarks").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    gw = LLMGateway(endpoint="http://127.0.0.1:11434", default_model="qwen2.5-coder:14b")
    rig = BlenderSensorRig(blender_path=find_blender_executable())
    critic = HarshCritic(llm_gateway=gw, passing_threshold=0.82, vision_model="qwen3-vl:8b")

    results = []

    print("=" * 80)
    print("STARTING EMPIRICAL 3D BENCHMARK: SIMPLE -> INTERMEDIATE -> COMPLEX")
    print("=" * 80)

    for tc in TEST_CASES:
        tier = tc["tier"]
        name = tc["name"]
        goal = tc["goal"]
        obj_file = out_dir / tc["filename"]

        print(f"\n[{tier}] Synthesizing: {name}")
        print(f"Goal: {goal}")

        t0 = time.time()

        # 1. Synthesize Code via 2-Stage Hierarchical Spatial Pipeline
        print("  -> Generating Spatial Blueprint & Blender 4.5 Python Script...")
        code = gw.generate_blender_code(goal=goal, output_obj_path=str(obj_file))
        code_file = out_dir / f"{name}_script.py"
        code_file.write_text(code, encoding="utf-8")
        print(f"  -> Script generated ({len(code)} bytes). Running in headless Blender...")

        # 2. Run Blender to build model
        from sentinel_broker.organs.blender import _run_blender_script
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
    print(f"BENCHMARK COMPLETE. Summary saved to {summary_file}")
    print("=" * 80)

if __name__ == "__main__":
    run_benchmark()
