"""Unit and Integration Tests for Sentinel Autonomous Gymnasium & Self-Evolution Engine."""
from __future__ import annotations

import tempfile
import time
from pathlib import Path
import pytest

from sentinel_core.db import SentinelDB
from sentinel_adaptive.skill_bank import SkillBank
from sentinel_adaptive.mistake_ledger import MistakeMemory
from sentinel_broker.tool_registry import ToolRegistry
from sentinel_gym.sensor_rig import (
    BlenderSensorRig,
    CSVSensorRig,
    CodeSensorRig,
    ModelInspectionResult,
)
from sentinel_gym.critic import HarshCritic, CriticScorecard
from sentinel_gym.curriculum import CurriculumGenerator
from sentinel_gym.auto_refiner import AutoRefiner
from sentinel_gym.daemon import GymnasiumDaemon


@pytest.fixture
def gym_env(tmp_path: Path):
    db_file = tmp_path / "test_gym.db"
    db = SentinelDB(str(db_file))
    with db.transaction() as c:
        c.execute("INSERT INTO tasks (id, title, state, created_at, updated_at) VALUES ('t_gym', 'Gym Task', 'Running', 0, 0)")
        c.execute("INSERT INTO attempts (id, task_id, attempt_number, lease_token, status, started_at) VALUES ('att_t_gym_1', 't_gym', 1, 999999, 'Active', 0)")

    tool_reg = ToolRegistry()
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    skill_bank = SkillBank(db, skills_dir=skills_dir, tool_registry=tool_reg)
    mistake_mem = MistakeMemory(db)

    return db, skill_bank, mistake_mem, tool_reg, tmp_path


def test_csv_sensor_rig_evaluates_structure(tmp_path: Path):
    csv_file = tmp_path / "test_data.csv"
    # Valid CSV
    csv_file.write_text("id,val,category\n1,10.5,A\n2,20.2,B\n3,30.1,A\n4,40.0,C\n", encoding="utf-8")
    res = CSVSensorRig.inspect_csv(csv_file)
    assert res.success is True
    assert res.row_count == 4
    assert res.col_count == 3
    assert res.is_degenerate is False
    assert "val" in res.numeric_columns

    # Degenerate CSV
    degen_file = tmp_path / "empty.csv"
    degen_file.write_text("header_only\n", encoding="utf-8")
    res_degen = CSVSensorRig.inspect_csv(degen_file)
    assert res_degen.is_degenerate is True


def test_code_sensor_rig_ast_inspection(tmp_path: Path):
    py_file = tmp_path / "module.py"
    py_file.write_text("class RoboticArm:\n    def grip(self):\n        return True\n", encoding="utf-8")
    res = CodeSensorRig.inspect_code(py_file)
    assert res.success is True
    assert "RoboticArm" in res.defined_classes
    assert "grip" in res.defined_functions
    assert res.is_degenerate is False


def test_harsh_critic_mathematical_pre_gate_on_degenerate_mesh():
    critic = HarshCritic(llm_gateway=None, passing_threshold=0.82)
    degen_insp = ModelInspectionResult(
        success=True,
        metrics={"vertex_count": 8, "face_count": 6, "object_count": 1, "bounding_box": {"volume": 0.0001}},
        is_degenerate=True,
        degenerate_reason="Single primitive assembly (1 object, 8 vertices)",
    )

    card = critic.evaluate_3d_model("Build an articulated telescope", degen_insp)
    assert card.passed is False
    assert card.score <= 0.30
    assert card.evaluation_mode == "degenerate_bypass"
    assert "FAILED MATHEMATICAL TOPOLOGY PRE-GATE" in card.critique


def test_harsh_critic_programmatic_rubric_evaluation():
    critic = HarshCritic(llm_gateway=None, passing_threshold=0.82)
    # High-quality multi-part assembly
    good_insp = ModelInspectionResult(
        success=True,
        metrics={
            "object_count": 5,
            "part_names": ["Optical_Tube", "Dew_Shield", "Eyepiece", "Mount_Hub", "Tripod_Legs"],
            "vertex_count": 1200,
            "face_count": 850,
            "non_manifold_edges": 0,
            "material_count": 3,
            "materials": ["Bronze", "Blue_Enamel", "Matte_Black"],
            "bounding_box": {"dx": 1.5, "dy": 1.2, "dz": 2.0, "volume": 3.6},
        },
        is_degenerate=False,
    )

    card = critic.evaluate_3d_model("Build an articulated equatorial telescope with brass mount", good_insp)
    assert card.score >= 0.82
    assert card.passed is True
    assert card.structural_integrity == 20
    assert card.feature_specificity == 25
    assert card.material_separation == 24


def test_harsh_critic_rejects_generic_primitive_clusters():
    critic = HarshCritic(llm_gateway=None, passing_threshold=0.82)
    # Generic unarticulated primitives with default names
    junk_insp = ModelInspectionResult(
        success=True,
        metrics={
            "object_count": 5,
            "part_names": ["Cone", "Cone.001", "Cylinder", "Cylinder.001", "Sphere"],
            "vertex_count": 800,
            "face_count": 600,
            "non_manifold_edges": 0,
            "material_count": 5,
            "materials": ["Mat1", "Mat2", "Mat3", "Mat4", "Mat5"],
            "bounding_box": {"dx": 1.5, "dy": 1.2, "dz": 2.0, "volume": 3.6},
        },
        is_degenerate=False,
    )

    card = critic.evaluate_3d_model("Build an articulated equatorial telescope with brass mount", junk_insp)
    assert card.passed is False
    assert card.score < 0.82
    assert card.anti_pattern_signature == "GENERIC_PRIMITIVE_CLUSTER"
    assert "generic primitives" in card.critique


def test_harsh_critic_vision_evaluation_flow(tmp_path: Path):
    class MockGateway:
        default_model = "qwen2.5-coder:14b"
        def is_available(self): return True
        def generate(self, **kwargs):
            assert kwargs.get("model") == "qwen3-vl:8b"
            assert "images" in kwargs and len(kwargs["images"]) == 1
            return '{"visual_resemblance": 4, "component_alignment": 3, "material_contrast": 8, "functional_proportion": 2, "critique": "Floating sphere and unattached primitives.", "remediation_advice": "Attach optical tube to tripod mount.", "anti_pattern": "FLOATING_PRIMITIVES"}'

    dummy_png = tmp_path / "iso.png"
    dummy_png.write_bytes(b"\x89PNG\r\n\x1a\nfake_image_bytes")

    insp = ModelInspectionResult(
        success=True,
        metrics={"object_count": 4, "part_names": ["Tube", "Shield", "Leg1", "Leg2"]},
        snapshots={"iso": str(dummy_png)},
        is_degenerate=False,
    )

    critic = HarshCritic(llm_gateway=MockGateway(), passing_threshold=0.82)
    card = critic.evaluate_3d_model("Build an equatorial telescope", insp)
    assert card.evaluation_mode == "vision"
    assert card.passed is False
    assert card.score == 0.17
    assert card.structural_integrity == 3
    assert card.feature_specificity == 4
    assert card.anti_pattern_signature == "FLOATING_PRIMITIVES"


def test_curriculum_generator_produces_challenges():
    curriculum = CurriculumGenerator()
    c1 = curriculum.generate_next_challenge(domain="3d")
    assert c1.domain == "3d"
    assert len(c1.expected_features) > 0
    assert c1.difficulty_tier >= 1


def test_auto_refiner_promotes_gold_standard_skill(gym_env):
    db, skill_bank, mistake_mem, tool_reg, tmp_path = gym_env
    refiner = AutoRefiner(skill_bank, mistake_mem, tool_reg)

    high_card = CriticScorecard(
        score=0.90,
        passed=True,
        structural_integrity=23,
        feature_specificity=24,
        material_separation=22,
        proportion_realism=21,
        critique="Excellent multi-part articulation and distinct materials.",
        remediation_advice="None",
    )

    outcome = refiner.process_evaluation(
        task_id="t_gym",
        attempt_id="att_t_gym_1",
        goal="Synthesize a 3D equatorial telescope assembly",
        domain="3d",
        code_or_script="import bpy\n# telescope code\n",
        scorecard=high_card,
    )

    assert outcome.action_taken == "SKILL_DISTILLED"
    assert outcome.skill_name is not None
    assert skill_bank.get_skill(outcome.skill_name) is not None


def test_auto_refiner_records_flawed_anti_pattern(gym_env):
    db, skill_bank, mistake_mem, tool_reg, tmp_path = gym_env
    refiner = AutoRefiner(skill_bank, mistake_mem, tool_reg)

    low_card = CriticScorecard(
        score=0.45,
        passed=False,
        structural_integrity=10,
        feature_specificity=10,
        material_separation=5,
        proportion_realism=10,
        critique="Uniform gray material slapped across all objects with no separation.",
        remediation_advice="Assign distinct Principled BSDF materials per vertex group.",
        anti_pattern_signature="UNIFORM_GRAY_SLAP",
    )

    outcome = refiner.process_evaluation(
        task_id="t_gym",
        attempt_id="att_t_gym_1",
        goal="Synthesize robotic gripper",
        domain="3d",
        code_or_script="# flawed code",
        scorecard=low_card,
    )

    assert outcome.action_taken == "ANTI_PATTERN_RECORDED"
    assert outcome.mistake_id is not None
    mistakes = mistake_mem.get_task_mistakes("t_gym")
    assert len(mistakes) == 1
    assert "UNIFORM_GRAY_SLAP" in mistakes[0]["error_category"]


def test_gymnasium_daemon_start_cycle_and_stop(gym_env):
    db, skill_bank, mistake_mem, tool_reg, tmp_path = gym_env
    sensor_rig = BlenderSensorRig(blender_path=None)  # Sensor rig mock fallback
    critic = HarshCritic(llm_gateway=None, passing_threshold=0.82)
    curriculum = CurriculumGenerator(skill_bank, mistake_mem)
    refiner = AutoRefiner(skill_bank, mistake_mem, tool_reg)

    mock_executed = []

    def mock_executor(tid, goal, domain):
        mock_executed.append((tid, goal))
        return {
            "artifact_path": str(tmp_path / "mock.obj"),
            "synthesized_code": "# code",
        }

    daemon = GymnasiumDaemon(
        sensor_rig=sensor_rig,
        critic=critic,
        curriculum=curriculum,
        auto_refiner=refiner,
        task_executor_fn=mock_executor,
        workspaces_dir=tmp_path,
        inter_cycle_delay_sec=0.05,
    )

    assert daemon.is_running is False
    daemon.start(max_duration_hours=0.01)  # Run short
    assert daemon.is_running is True

    # Allow 1 cycle to execute
    time.sleep(0.3)
    status = daemon.get_status()
    assert status["is_running"] is True
    assert status["total_cycles_completed"] >= 1

    daemon.stop()
    time.sleep(0.1)
    assert daemon.is_running is False
