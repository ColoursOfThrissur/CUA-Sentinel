"""Unit tests for Self-Upgrade & Sensory Perception Organs and Curriculum Frontier."""
from pathlib import Path
import pytest

from sentinel_core.db import SentinelDB
from sentinel_broker.tool_registry import ToolRegistry
from sentinel_adaptive.skill_bank import SkillBank
from sentinel_adaptive.mistake_ledger import MistakeMemory
from sentinel_gym.sensor_rig import BlenderSensorRig
from sentinel_gym.critic import HarshCritic
from sentinel_gym.curriculum import CurriculumGenerator
from sentinel_broker.organs.self_upgrade import register_self_upgrade_organs


@pytest.fixture
def test_env(tmp_path: Path):
    db_file = tmp_path / "test_upgrade.db"
    db = SentinelDB(str(db_file))
    reg = ToolRegistry()
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    bank = SkillBank(db=db, skills_dir=skills_dir, tool_registry=reg)
    mistake_mem = MistakeMemory(db=db)
    critic = HarshCritic(llm_gateway=None, passing_threshold=0.82)
    rig = BlenderSensorRig(blender_path=None)

    register_self_upgrade_organs(
        registry=reg,
        sensor_rig=rig,
        harsh_critic=critic,
        skill_bank=bank,
    )
    return db, reg, bank, mistake_mem, tmp_path


def test_sensory_inspect_csv_and_code(test_env):
    db, reg, bank, mistake_mem, tmp_path = test_env

    # 1. Inspect CSV
    csv_file = tmp_path / "data.csv"
    csv_file.write_text("timestamp,metric_a,metric_b\n2026-01-01,10.5,20.0\n", encoding="utf-8")
    res_csv = reg.execute_tool("sensory_inspect_artifact", {"artifact_path": str(csv_file), "domain": "data"})
    assert res_csv["success"] is True
    assert res_csv["row_count"] == 1
    assert "metric_a" in res_csv["numeric_columns"]

    # 2. Inspect Python code
    py_file = tmp_path / "algo.py"
    py_file.write_text("class RobotArm:\n    def actuate(self):\n        return True\n", encoding="utf-8")
    res_code = reg.execute_tool("sensory_inspect_artifact", {"artifact_path": str(py_file), "domain": "code"})
    assert res_code["success"] is True
    assert res_code["syntax_valid"] is True
    assert "RobotArm" in res_code["defined_classes"]


def test_sensory_evaluate_critic_organ(test_env):
    db, reg, bank, mistake_mem, tmp_path = test_env

    csv_file = tmp_path / "telemetry.csv"
    csv_file.write_text("time,val1,val2,val3\n1,10,20,30\n2,11,21,31\n3,12,22,32\n4,13,23,33\n", encoding="utf-8")
    res = reg.execute_tool("sensory_evaluate_critic", {
        "goal": "Generate telemetry dataset with 4 readings",
        "artifact_path": str(csv_file),
        "domain": "data",
    })
    assert res["success"] is True
    assert res["score"] > 0.0
    assert "critique" in res


def test_skill_search_and_compose_organ(test_env):
    db, reg, bank, mistake_mem, tmp_path = test_env

    bank.distill_skill(
        name="skill_spur_gear_generator",
        description="Generates 3D spur gear transmission with pinion and ring gear",
        code="import bpy\n# procedural gear\n",
        domain="3d",
    )

    res = reg.execute_tool("skill_search_and_compose", {"query": "spur gear pinion", "domain": "3d"})
    assert res["success"] is True
    assert res["match_count"] >= 1
    assert res["skills"][0]["name"] == "skill_spur_gear_generator"


def test_curriculum_dynamic_frontier_synthesis(test_env):
    db, reg, bank, mistake_mem, tmp_path = test_env

    class MockCurriculumGateway:
        def generate(self, **kwargs):
            return '{"goal": "Synthesize a 3D dual-rotor turbofan engine with titanium blades", "difficulty_tier": 4, "category": "aerospace", "expected_features": ["rotor_hub", "blades", "housing", "nozzle"]}'

    curriculum = CurriculumGenerator(
        skill_bank=bank,
        mistake_memory=mistake_mem,
        llm_gateway=MockCurriculumGateway(),
    )

    challenge = curriculum.generate_next_challenge(domain="3d", force_frontier=True)
    assert challenge.difficulty_tier == 4
    assert "turbofan" in challenge.goal
    assert challenge.category == "aerospace"
