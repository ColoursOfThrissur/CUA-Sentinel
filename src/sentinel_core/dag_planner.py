"""Sentinel Autonomous DAG Planner.
Decomposes complex, multi-agent objectives into structured, acyclic task graphs (DAGs)
with domain assignments, capability bindings, and topological dependency relationships.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from sentinel_core.dag_orchestrator import DAGStepDefinition, validate_and_sort_dag, DAGValidationError
from sentinel_core.llm_gateway import LLMGateway

logger = logging.getLogger("sentinel.dag_planner")


class DAGPlanner:
    """Decomposes natural language goals into validated multi-agent DAG pipelines."""

    REGISTERED_AGENTS = {
        "blender_artisan": {"domain": "3d", "desc": "Synthesizes procedural 3D meshes, shaders, and animations in Blender 4.5 LTS"},
        "data_analyst": {"domain": "data", "desc": "Analyzes CSV datasets, computes aggregations, and extracts tabular telemetry"},
        "code_engineer": {"domain": "code", "desc": "Synthesizes Python scripts, modules, algorithms, and executes sandboxed code"},
        "systems_reporter": {"domain": "report", "desc": "Synthesizes executive markdown reports and system health briefings"},
    }

    @classmethod
    def decompose_goal(
        cls,
        goal: str,
        gateway: LLMGateway | None = None,
        model: str | None = None,
    ) -> tuple[str, str, list[DAGStepDefinition]]:
        """
        Decomposes a user goal into (pipeline_name, pipeline_description, steps).
        Attempts LLM-driven structured planning first, with automatic fallback to
        deterministic heuristic domain decomposition if unavailable or invalid.
        """
        clean_goal = goal.strip()
        if not clean_goal:
            raise DAGValidationError("Goal cannot be empty.")

        # 1. Try LLM Structured Planning if gateway provided
        if gateway:
            try:
                plan = cls._plan_via_llm(clean_goal, gateway, model)
                if plan:
                    return plan
            except Exception as e:
                logger.warning("LLM DAG planning failed, falling back to heuristic planner: %s", e)

        # 2. Deterministic Heuristic Decomposition Fallback
        return cls._plan_via_heuristic(clean_goal)

    @classmethod
    def _plan_via_llm(
        cls,
        goal: str,
        gateway: LLMGateway,
        model: str | None = None,
    ) -> tuple[str, str, list[DAGStepDefinition]] | None:
        agent_catalog = "\n".join([
            f"- `{aid}` (domain: '{info['domain']}'): {info['desc']}"
            for aid, info in cls.REGISTERED_AGENTS.items()
        ])

        system_prompt = (
            "You are Sentinel's Autonomous Multi-Agent DAG Planner. Your role is to break down complex goals into "
            "a sequential or parallel Directed Acyclic Graph (DAG) of 2 to 4 discrete sub-tasks executed by specialized agents.\n\n"
            f"Available Agents:\n{agent_catalog}\n\n"
            "Output ONLY valid JSON matching this schema:\n"
            "{\n"
            '  "pipeline_name": "Short Name",\n'
            '  "pipeline_description": "Description of the workflow",\n'
            '  "steps": [\n'
            '    {\n'
            '      "step_id": "step_1",\n'
            '      "goal": "Specific actionable sub-task goal",\n'
            '      "agent_id": "one of the available agent_ids",\n'
            '      "domain": "one of 3d, data, code, report",\n'
            '      "dependencies": []\n'
            '    },\n'
            '    {\n'
            '      "step_id": "step_2",\n'
            '      "goal": "Next sub-task goal using output of step_1",\n'
            '      "agent_id": "agent_id",\n'
            '      "domain": "domain",\n'
            '      "dependencies": ["step_1"]\n'
            '    }\n'
            '  ]\n'
            "}"
        )

        user_prompt = f"Goal to decompose into a collaborative multi-agent pipeline:\n'{goal}'"
        raw_text = gateway.generate(prompt=user_prompt, system=system_prompt, model=model, temperature=0.1)

        # Strip <think>...</think> blocks if present so internal monologues don't break JSON parsing
        cleaned_text = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL).strip()
        if not cleaned_text:
            cleaned_text = raw_text

        # Extract JSON block
        json_match = re.search(r"\{.*\}", cleaned_text, re.DOTALL)
        if not json_match:
            return None

        data = json.loads(json_match.group(0))
        name = data.get("pipeline_name", "Autonomous Multi-Agent Pipeline")
        description = data.get("pipeline_description", goal)
        raw_steps = data.get("steps", [])
        if not raw_steps or not isinstance(raw_steps, list):
            return None

        step_defs: list[DAGStepDefinition] = []
        for s in raw_steps:
            sid = str(s.get("step_id", "")).strip()
            sgoal = str(s.get("goal", "")).strip()
            aid = str(s.get("agent_id", "systems_reporter")).strip()
            if aid not in cls.REGISTERED_AGENTS:
                aid = "systems_reporter"
            dom = str(s.get("domain", cls.REGISTERED_AGENTS[aid]["domain"])).strip()
            deps = [str(d).strip() for d in s.get("dependencies", [])]

            if not sid or not sgoal:
                return None

            step_defs.append(DAGStepDefinition(
                step_id=sid,
                goal=sgoal,
                agent_id=aid,
                domain=dom,
                dependencies=deps,
            ))

        # Validate topology
        validate_and_sort_dag(step_defs)
        return name, description, step_defs

    @classmethod
    def _plan_via_heuristic(cls, goal: str) -> tuple[str, str, list[DAGStepDefinition]]:
        """Fallback rule-based heuristic planner based on domain keywords."""
        lower_g = goal.lower()

        # 1. 3D Asset Engineering & QA Pattern
        if any(w in lower_g for w in ["3d", "blender", "mesh", "model", "sword", "turret", "asset", "render"]):
            name = "Procedural 3D Asset & QA Pipeline"
            description = f"Autonomous 3D modeling and geometric QA pipeline for: {goal}"
            steps = [
                DAGStepDefinition(
                    step_id="step_1_3d_synthesis",
                    goal=f"Synthesize high-detail 3D geometry in Blender 4.5 for: {goal}",
                    agent_id="blender_artisan",
                    domain="3d",
                ),
                DAGStepDefinition(
                    step_id="step_2_geometry_audit",
                    goal=f"Write a Python script that loads the synthesized 3D mesh, inspects vertex/face counts, checks watertightness, and verifies bounding box scale",
                    agent_id="code_engineer",
                    domain="code",
                    dependencies=["step_1_3d_synthesis"],
                ),
                DAGStepDefinition(
                    step_id="step_3_asset_briefing",
                    goal=f"Compile a comprehensive Technical 3D Asset Inspection Sheet markdown document summarizing geometric specs, topology benchmarks, and rendering guidelines",
                    agent_id="systems_reporter",
                    domain="report",
                    dependencies=["step_1_3d_synthesis", "step_2_geometry_audit"],
                ),
            ]
            validate_and_sort_dag(steps)
            return name, description, steps

        # 2. Tabular Data & Anomaly Analytics Pattern
        if any(w in lower_g for w in ["csv", "data", "dataset", "telemetry", "table", "sales", "metrics", "analytics"]):
            name = "Data Telemetry & Statistical Analysis Pipeline"
            description = f"Autonomous tabular generation, anomaly detection, and executive report for: {goal}"
            steps = [
                DAGStepDefinition(
                    step_id="step_1_dataset_generation",
                    goal=f"Generate a structured CSV dataset satisfying: {goal}",
                    agent_id="data_analyst",
                    domain="data",
                ),
                DAGStepDefinition(
                    step_id="step_2_statistical_analysis",
                    goal=f"Write a Python script that loads the generated CSV dataset, calculates aggregations, correlations, or anomalies, and outputs key metrics",
                    agent_id="code_engineer",
                    domain="code",
                    dependencies=["step_1_dataset_generation"],
                ),
                DAGStepDefinition(
                    step_id="step_3_executive_briefing",
                    goal=f"Compile an Executive Briefing markdown report summarizing tabular trends, statistical findings, and actionable recommendations",
                    agent_id="systems_reporter",
                    domain="report",
                    dependencies=["step_1_dataset_generation", "step_2_statistical_analysis"],
                ),
            ]
            validate_and_sort_dag(steps)
            return name, description, steps

        # 3. Code Engineering & Rigorous Unit Test Bench Pattern
        if any(w in lower_g for w in ["code", "python", "algorithm", "class", "function", "cache", "lru", "script"]):
            name = "Software Engineering & Test Bench Pipeline"
            description = f"Autonomous code implementation, unit test bench, and technical audit for: {goal}"
            steps = [
                DAGStepDefinition(
                    step_id="step_1_implementation",
                    goal=f"Synthesize a robust, modular Python implementation solving: {goal}",
                    agent_id="code_engineer",
                    domain="code",
                ),
                DAGStepDefinition(
                    step_id="step_2_test_bench",
                    goal=f"Synthesize and execute a rigorous Python unit test bench testing edge cases, boundary conditions, and performance contracts",
                    agent_id="code_engineer",
                    domain="code",
                    dependencies=["step_1_implementation"],
                ),
                DAGStepDefinition(
                    step_id="step_3_engineering_report",
                    goal=f"Compile a Software Engineering QA & Benchmark Audit markdown report detailing architecture, test coverage, and asymptotic complexity",
                    agent_id="systems_reporter",
                    domain="report",
                    dependencies=["step_1_implementation", "step_2_test_bench"],
                ),
            ]
            validate_and_sort_dag(steps)
            return name, description, steps

        # 4. Default Host & System Health Audit Pattern
        name = "System Telemetry & Health Audit Pipeline"
        description = f"Collaborative multi-agent system inspection and report for: {goal}"
        steps = [
            DAGStepDefinition(
                step_id="step_1_telemetry_gathering",
                goal=f"Gather live system telemetry or metrics relevant to: {goal}",
                agent_id="data_analyst",
                domain="data",
            ),
            DAGStepDefinition(
                step_id="step_2_executive_synthesis",
                goal=f"Compile a comprehensive executive markdown briefing addressing: {goal}",
                agent_id="systems_reporter",
                domain="report",
                dependencies=["step_1_telemetry_gathering"],
            ),
        ]
        validate_and_sort_dag(steps)
        return name, description, steps
