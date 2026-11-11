"""Tests for Priority 2: Skill Composition & Reusable Compound Skill Bank."""
from pathlib import Path
import pytest

from sentinel_core.db import SentinelDB
from sentinel_core.agent_registry import (
    AgentRegistry,
    AgentManifest,
)
from sentinel_broker.tool_registry import ToolRegistry
from sentinel_broker.pdp import PolicyDecisionPoint
from sentinel_broker.broker import ExecutionBroker
from sentinel_core.leases import LeaseManager
from sentinel_core.side_effects import SideEffectLedger, EffectClass
from sentinel_adaptive.skill_bank import SkillBank, derive_semantic_slug
from sentinel_core.prompt_scaffolder import PromptScaffolder, ScaffoldingLevel


@pytest.fixture
def test_db(tmp_path: Path):
    db_file = tmp_path / "test_skills.db"
    return SentinelDB(str(db_file))


def test_derive_semantic_slug():
    # 1. Clean code slug from verbose prompt
    slug1 = derive_semantic_slug(
        "Write Python code implementing an LRU Cache data structure with get and put methods",
        domain="code",
    )
    assert slug1 == "skill_lru_cache"

    # 2. 3D slug
    slug2 = derive_semantic_slug(
        "Synthesize a 3D Gatling Turret model in Blender",
        domain="3d",
    )
    assert slug2 == "skill_gatling_turret_model"

    # 3. Data CSV slug
    slug3 = derive_semantic_slug(
        "Generate a synthetic telemetry dataset CSV with timestamp and cpu metrics",
        domain="data",
    )
    assert "telemetry" in slug3

    # 4. Fallback slug
    slug4 = derive_semantic_slug("", domain="code")
    assert slug4.startswith("skill_code_")


def test_find_relevant_skills(test_db, tmp_path):
    skills_dir = tmp_path / "skills"
    bank = SkillBank(db=test_db, skills_dir=skills_dir)

    bank.distill_skill(
        name="skill_lru_cache",
        description="Fast LRU Cache with OrderedDict backing",
        code="class LRUCache:\n    pass\n",
        domain="code",
    )
    bank.distill_skill(
        name="skill_telemetry_csv",
        description="Generates synthetic IoT server telemetry CSV data",
        code="import csv\n",
        domain="data",
    )
    bank.distill_skill(
        name="skill_gatling_turret",
        description="Blender 4.5 3D procedural gatling turret mesh",
        code="import bpy\n",
        domain="3d",
    )

    # Keyword search
    res = bank.find_relevant_skills("implement an lru cache with put and get")
    assert len(res) >= 1
    assert res[0]["name"] == "skill_lru_cache"

    # Domain filtered search
    res_data = bank.find_relevant_skills("telemetry IoT metrics", domain="data")
    assert len(res_data) == 1
    assert res_data[0]["name"] == "skill_telemetry_csv"

    # Irrelevant domain filter
    res_none = bank.find_relevant_skills("telemetry", domain="3d")
    assert len(res_none) == 0


def test_wildcard_prefix_capability_matching(test_db):
    reg = AgentRegistry(test_db)

    manifest = AgentManifest(
        agent_id="code_engineer",
        name="Code Engineer",
        version="1.0.0",
        description="Autonomous algorithm developer",
        author="Sentinel Team",
        capabilities=["code:python"],
        allowed_organs=["python_sandbox_run", "skill_*"],  # Wildcard prefix
        denied_tools=[],
    )
    reg.register_draft(manifest)
    reg.publish_release("code_engineer", "1.0.0")

    # Direct allowed organ
    ok, msg = reg.validate_capability("code_engineer", "python_sandbox_run")
    assert ok is True
    assert msg == "AUTHORIZED"

    # Wildcard prefix matching
    ok, msg = reg.validate_capability("code_engineer", "skill_lru_cache")
    assert ok is True
    assert msg == "AUTHORIZED"

    ok, msg = reg.validate_capability("code_engineer", "skill_anomaly_detector")
    assert ok is True
    assert msg == "AUTHORIZED"

    # Denied organ
    ok, err = reg.validate_capability("code_engineer", "blender_run_python")
    assert ok is False
    assert "not in allowed_organs" in err


def test_dynamic_tool_registration_and_execution(test_db, tmp_path):
    skills_dir = tmp_path / "skills"
    tool_reg = ToolRegistry()
    bank = SkillBank(db=test_db, skills_dir=skills_dir, tool_registry=tool_reg)

    # Distill code skill
    code = (
        "def compute_factorial(n):\n"
        "    return 1 if n <= 1 else n * compute_factorial(n - 1)\n\n"
        "assert compute_factorial(5) == 120\n"
        "print('FACTORIAL_OK_120')\n"
    )
    meta = bank.distill_skill(
        name="skill_factorial_calc",
        description="Computes factorial recursively with assertion tests",
        code=code,
        domain="code",
    )
    assert meta["name"] == "skill_factorial_calc"

    # Verify tool was dynamically registered into ToolRegistry
    tool_entry = tool_reg.get_tool("skill_factorial_calc")
    assert tool_entry is not None
    assert "recursive" in tool_entry.description

    # Execute skill directly via skill_bank
    exec_res = bank.execute_skill("skill_factorial_calc")
    assert exec_res["success"] is True
    assert "FACTORIAL_OK_120" in exec_res["stdout"]

    # Verify universal execute_skill organ
    bank.register_distilled_skills_into_broker(tool_reg)
    exec_tool = tool_reg.get_tool("execute_skill")
    assert exec_tool is not None

    universal_res = tool_reg.execute_tool(
        "execute_skill",
        {"skill_name": "skill_factorial_calc", "params": {}},
    )
    assert universal_res["success"] is True
    assert "FACTORIAL_OK_120" in universal_res["stdout"]


def test_compound_prompt_injection():
    relevant_skills = [
        {
            "name": "skill_lru_cache",
            "domain": "code",
            "description": "High performance LRU Cache with O(1) eviction",
        }
    ]

    prompt = PromptScaffolder.build_user_prompt(
        goal="Build an MRU cache variant",
        domain="code",
        artifact_path="workspaces/test.py",
        level=ScaffoldingLevel.LEVEL_2_GUARDED,
        relevant_skills=relevant_skills,
    )

    assert "[COMPOUND SKILL BANK - REUSABLE VERIFIED SKILLS]" in prompt
    assert "skill_lru_cache" in prompt
    assert "skills/skill_lru_cache/tool.py" in prompt
