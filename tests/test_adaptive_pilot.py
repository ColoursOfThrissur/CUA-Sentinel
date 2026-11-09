"""Tests for Bounded Adaptive Pilot Loop, Mistake Ledger, and Skill Distillation."""
import pytest
from pathlib import Path
import tempfile
import shutil

from sentinel_core.db import SentinelDB
from sentinel_core.state_machine import StateMachine, TaskState
from sentinel_core.verification_gate import VerificationGate, VerificationResult
from sentinel_broker.tool_registry import ToolRegistry
from sentinel_adaptive.mistake_ledger import MistakeMemory
from sentinel_adaptive.skill_bank import SkillBank
from sentinel_adaptive.pilot_controller import AdaptivePilotController


@pytest.fixture
def pilot_setup():
    temp_dir = Path(tempfile.mkdtemp())
    db = SentinelDB(temp_dir / "test_pilot.db")
    sm = StateMachine(db)
    gate = VerificationGate(db)
    memory = MistakeMemory(db)
    skills_dir = temp_dir / "skills"
    skill_bank = SkillBank(db, skills_dir)
    controller = AdaptivePilotController(sm, gate, memory, skill_bank)
    
    yield controller, skill_bank, temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_pilot_first_attempt_success(pilot_setup):
    controller, skill_bank, _ = pilot_setup

    def worker_executor(goal, attempt_num, anti_patterns):
        return {
            "output_data": "valid_output",
            "synthesized_code": "result = {'status': 'processed', 'val': params.get('val', 0) * 2}",
            "parameters_schema": {"val": "int"},
        }

    def verifier(output):
        return VerificationResult(passed=True)

    result = controller.run_task(
        task_id="task_pilot_01",
        goal="Generate multiplier skill",
        worker_executor=worker_executor,
        verifier=verifier,
        skill_distillation_name="multiplier_skill",
    )

    assert result.success is True
    assert result.attempts_taken == 1
    assert result.task.state == TaskState.SUCCEEDED
    assert result.distilled_skill is not None
    assert result.distilled_skill["name"] == "multiplier_skill"

    # Verify skill is saved in skill bank
    stored = skill_bank.get_skill("multiplier_skill")
    assert stored is not None
    assert "result =" in stored["code"]


def test_pilot_adaptive_attempt_learning(pilot_setup):
    """Proves: Attempt 1 fails -> Mistake recorded -> Attempt 2 adapts based on anti-pattern -> Verification passes."""
    controller, skill_bank, temp_dir = pilot_setup
    target_file = temp_dir / "geometry.obj"

    # Worker simulates learning:
    # On attempt 1, it forgets to write the file (or writes empty).
    # On attempt 2, it sees the anti-pattern warning and writes valid geometry data.
    def worker_executor(goal, attempt_num, anti_patterns):
        if attempt_num == 1:
            # Mistake: forgets to write file
            return {"file_created": False}
        else:
            # Adaptation: Saw anti-pattern warning!
            assert "MISSING_ARTIFACT" in anti_patterns
            target_file.write_text("v 0.0 0.0 0.0\nv 1.0 1.0 1.0\nf 1 2\n", encoding="utf-8")
            return {
                "file_created": True,
                "synthesized_code": "result = {'geometry_generated': True}",
            }

    def verifier(output):
        if not target_file.exists():
            return VerificationResult(
                passed=False,
                error_category="MISSING_ARTIFACT",
                error_signature="FileNotFound:geometry.obj",
                details={"expected": str(target_file)},
                lesson="Worker must write valid geometry.obj before signaling completion.",
            )
        return VerificationResult(passed=True)

    result = controller.run_task(
        task_id="task_pilot_02",
        goal="Generate 3D geometry asset",
        worker_executor=worker_executor,
        verifier=verifier,
        skill_distillation_name="generate_geometry",
        max_attempts=3,
    )

    # Assertions
    assert result.success is True
    assert result.attempts_taken == 2  # Proved adaptation on attempt 2!
    assert result.task.state == TaskState.SUCCEEDED
    assert len(result.mistakes_encountered) == 1
    assert result.mistakes_encountered[0]["error_category"] == "MISSING_ARTIFACT"

    # Prove dynamic plasticity: Register distilled skill into ToolRegistry and execute it
    registry = ToolRegistry()
    skill_bank.register_distilled_skills_into_broker(registry)
    tool = registry.get_tool("generate_geometry")
    assert tool is not None
    exec_res = registry.execute_tool("generate_geometry", {})
    assert exec_res["result"]["geometry_generated"] is True


def test_pilot_exhaustion_on_unrecoverable_task(pilot_setup):
    controller, _, _ = pilot_setup

    def stubborn_worker(goal, attempt_num, anti_patterns):
        return {"always_bad": True}

    def strict_verifier(output):
        return VerificationResult(
            passed=False,
            error_category="FATAL_REJECT",
            error_signature="NeverAccept",
            lesson="Will never pass.",
        )

    result = controller.run_task(
        task_id="task_pilot_03",
        goal="Impossible Task",
        worker_executor=stubborn_worker,
        verifier=strict_verifier,
        max_attempts=3,
    )

    assert result.success is False
    assert result.attempts_taken == 3
    assert result.task.state == TaskState.FAILED
    assert len(result.mistakes_encountered) == 3
