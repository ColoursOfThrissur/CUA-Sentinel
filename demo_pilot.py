"""Sentinel End-to-End Pilot Demonstration.
Demonstrates the full biological adaptation cycle:
1. Brainstem / State Machine & Monotonic Fencing
2. Outside PDP & Execution Broker
3. Attempt 1 Failure -> Verification Gate Rejection -> Episodic Mistake Ledger
4. Attempt 2 Adaptation -> Anti-Pattern Injection -> Verification Gate Pass
5. Plasticity -> Skill Bank Distillation & Dynamic Re-registration
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
import sys

src_dir = Path(__file__).parent / "src"
sys.path.insert(0, str(src_dir))

from sentinel_core.db import SentinelDB
from sentinel_core.state_machine import StateMachine
from sentinel_core.verification_gate import VerificationGate, VerificationResult
from sentinel_core.side_effects import SideEffectLedger, EffectClass
from sentinel_broker.tool_registry import ToolRegistry
from sentinel_broker.pdp import PolicyDecisionPoint
from sentinel_broker.broker import ExecutionBroker
from sentinel_adaptive.mistake_ledger import MistakeMemory
from sentinel_adaptive.skill_bank import SkillBank
from sentinel_adaptive.pilot_controller import AdaptivePilotController


def run_demo():
    print("======================================================================")
    print("        SENTINEL AUTONOMOUS PILOT: END-TO-END DEMO                    ")
    print("======================================================================")

    demo_root = Path("demo_workspace").resolve()
    shutil.rmtree(demo_root, ignore_errors=True)
    demo_root.mkdir(parents=True, exist_ok=True)

    db_path = demo_root / "sentinel_demo_core.db"
    skills_dir = demo_root / "skills"
    output_obj = demo_root / "mesh_cube.obj"

    # 1. Initialize Organs
    print("\n[Organ Init] Initializing Brainstem, Memory, and Motor Organs...")
    db = SentinelDB(db_path)
    state_machine = StateMachine(db)
    side_effects = SideEffectLedger(db)
    tool_registry = ToolRegistry()
    pdp = PolicyDecisionPoint(state_machine.leases, tool_registry)
    broker = ExecutionBroker(pdp, tool_registry, side_effects)
    verification_gate = VerificationGate(db)
    mistake_memory = MistakeMemory(db)
    skill_bank = SkillBank(db, skills_dir)
    pilot = AdaptivePilotController(state_machine, verification_gate, mistake_memory, skill_bank)

    # 2. Register Host Tools into Tool Catalog
    @tool_registry.register("write_asset", "Writes 3D mesh data to disk", EffectClass.IDEMPOTENT_WRITE)
    def tool_write_asset(params, ctx):
        p = Path(params["path"])
        p.write_text(params["content"], encoding="utf-8")
        return {"status": "WRITTEN", "bytes": len(params["content"])}

    print(f"[Tool Catalog] Registered tools: {[t['name'] for t in tool_registry.list_tools()]}")

    # 3. Define Simulated Worker with Biological Learning Behavior
    def worker_logic(goal: str, attempt_num: int, anti_patterns: str) -> dict:
        print(f"\n--- [Worker Attempt {attempt_num}] Starting execution ---")
        if attempt_num == 1:
            print("[Worker Attempt 1] Naive execution: Generates malformed/empty mesh.")
            # Mistake on Attempt 1: writes empty file (0 bytes)
            output_obj.write_text("", encoding="utf-8")
            return {
                "asset_path": str(output_obj),
                "attempt": 1,
            }
        else:
            print("[Worker Attempt 2] Adapting execution from Episodic Mistake Memory!")
            print(f"[Worker Attempt 2] Received Constraints:\n{anti_patterns}")
            # Adapts on Attempt 2: Generates valid Wavefront OBJ with vertices & faces
            obj_content = (
                "# Valid 3D Cube Mesh\n"
                "v 0.0 0.0 0.0\nv 1.0 0.0 0.0\nv 1.0 1.0 0.0\nv 0.0 1.0 0.0\n"
                "v 0.0 0.0 1.0\nv 1.0 0.0 1.0\nv 1.0 1.0 1.0\nv 0.0 1.0 1.0\n"
                "f 1 2 3 4\nf 5 6 7 8\nf 1 2 6 5\nf 2 3 7 6\nf 3 4 8 7\nf 4 1 5 8\n"
            )
            output_obj.write_text(obj_content, encoding="utf-8")
            synthesized_skill_code = (
                "path = params.get('path', 'mesh.obj')\n"
                "with open(path, 'w') as f:\n"
                "    f.write('" + obj_content.replace("\n", "\\n") + "')\n"
                "result = {'written': True, 'mesh': path}\n"
            )
            return {
                "asset_path": str(output_obj),
                "attempt": 2,
                "synthesized_code": synthesized_skill_code,
                "parameters_schema": {"path": "str"},
            }

    # 4. Objective Verifier Rule (FR-024)
    def verify_3d_asset(worker_output: dict) -> VerificationResult:
        p = Path(worker_output.get("asset_path", ""))
        # Check 1: File must exist and be non-empty (at least 20 bytes)
        file_check = verification_gate.verify_file_exists(p, min_bytes=20)
        if not file_check.passed:
            return file_check

        # Check 2: Must contain vertex lines ('v ') and face lines ('f ')
        content = p.read_text(encoding="utf-8")
        if "v " not in content or "f " not in content:
            return VerificationResult(
                passed=False,
                error_category="INVALID_GEOMETRY",
                error_signature="MissingVertexOrFaceDef",
                details={"file": str(p), "preview": content[:50]},
                lesson="3D Wavefront OBJ file must declare vertices ('v x y z') and polygon faces ('f v1 v2 v3').",
            )
        return VerificationResult(passed=True, details={"bytes": len(content), "valid_obj": True})

    # 5. Run the Pilot Loop
    task_id = "task_demo_3d_cube"
    goal = "Create a verified 3D cube mesh asset"
    print(f"\n[Pilot Dispatch] Starting Task: {task_id} ('{goal}')")

    result = pilot.run_task(
        task_id=task_id,
        goal=goal,
        worker_executor=worker_logic,
        verifier=verify_3d_asset,
        skill_distillation_name="generate_3d_cube",
        max_attempts=3,
    )

    print("\n======================================================================")
    print("                    PILOT EXECUTION SUMMARY                           ")
    print("======================================================================")
    print(f"Task ID:               {result.task.id}")
    print(f"Final State:           {result.task.state.value} (Terminal)")
    print(f"Attempts Taken:        {result.attempts_taken} (Success on Attempt 2 via adaptation)")
    print(f"Mistakes Encountered:  {len(result.mistakes_encountered)}")
    for m in result.mistakes_encountered:
        print(f"  - [{m['error_category']}] {m['error_signature']} -> Lesson: {m['lesson_learned']}")
    print(f"Distilled Skill:       {result.distilled_skill['name'] if result.distilled_skill else None}")
    if result.distilled_skill:
        print(f"Skill Folder Path:     {result.distilled_skill['folder']}")

    # 6. Test Plasticity: Dynamically Register Distilled Skill and Run It
    print("\n[Plasticity Check] Registering newly distilled skill into Execution Broker...")
    skill_bank.register_distilled_skills_into_broker(tool_registry)
    new_tool = tool_registry.get_tool("generate_3d_cube")
    print(f"[Tool Catalog] Tool available dynamically: {new_tool.name} ('{new_tool.description}')")

    re_exec = tool_registry.execute_tool("generate_3d_cube", {"path": str(demo_root / "distilled_cube.obj")})
    print(f"[Tool Execution] Result from newly acquired skill: {re_exec}")
    print(f"[Verification] File created by distilled skill: {Path(demo_root / 'distilled_cube.obj').exists()}")
    print("======================================================================\n")

    # Clean up demo folder
    shutil.rmtree(demo_root, ignore_errors=True)


if __name__ == "__main__":
    run_demo()
