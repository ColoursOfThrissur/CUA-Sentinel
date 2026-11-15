"""Sentinel Self-Upgrade & Sensory Reflection Organs.
Provides autonomous agents with direct empirical perception tools:
- sensory_inspect_artifact: inspects physical geometry, CSV tabular structure, or Python AST.
- sensory_evaluate_critic: evaluates artifacts with HarshCritic (and qwen3-vl vision critic) for immediate scorecard and remediation.
- skill_search_and_compose: semantically retrieves verified procedural skills and spatial blueprints from SkillBank.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sentinel_core.side_effects import EffectClass
from sentinel_broker.tool_registry import ToolRegistry
from sentinel_gym.sensor_rig import BlenderSensorRig, CSVSensorRig, CodeSensorRig
from sentinel_gym.critic import HarshCritic
from sentinel_adaptive.skill_bank import SkillBank

logger = logging.getLogger("SentinelSelfUpgradeOrgans")


def register_self_upgrade_organs(
    registry: ToolRegistry,
    sensor_rig: BlenderSensorRig | None = None,
    harsh_critic: HarshCritic | None = None,
    skill_bank: SkillBank | None = None,
):
    """Registers self-upgrade, empirical perception, and skill reflection tools."""
    rig = sensor_rig or BlenderSensorRig()
    critic = harsh_critic or HarshCritic()

    @registry.register(
        name="sensory_inspect_artifact",
        description="Inspects an artifact (3D OBJ, CSV dataset, or Python code) using empirical sensor rigs. Returns topology, dimensions, and render snapshot paths.",
        effect_class=EffectClass.READ_ONLY,
        parameters_schema={
            "artifact_path": "str (absolute or workspace path to the artifact file)",
            "domain": "str (3d | data | code, default 3d)",
        },
    )
    def handle_sensory_inspect(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        artifact_path = params.get("artifact_path", "")
        domain = params.get("domain", "3d").lower()
        p = Path(artifact_path)
        if not p.exists():
            return {"success": False, "error": f"Artifact not found on disk: {artifact_path}"}

        if domain == "3d" or p.suffix.lower() == ".obj":
            insp = rig.inspect_model(p)
            return {
                "success": insp.success,
                "is_degenerate": insp.is_degenerate,
                "degenerate_reason": insp.degenerate_reason,
                "metrics": insp.metrics,
                "snapshots": insp.snapshots,
            }
        elif domain == "data" or p.suffix.lower() == ".csv":
            insp_csv = CSVSensorRig.inspect_csv(p)
            return {
                "success": insp_csv.success,
                "row_count": insp_csv.row_count,
                "col_count": insp_csv.col_count,
                "headers": insp_csv.headers,
                "null_ratio": insp_csv.null_ratio,
                "numeric_columns": insp_csv.numeric_columns,
                "is_degenerate": insp_csv.is_degenerate,
                "degenerate_reason": insp_csv.degenerate_reason,
            }
        else:
            insp_code = CodeSensorRig.inspect_code(p)
            return {
                "success": insp_code.success,
                "syntax_valid": insp_code.syntax_valid,
                "ast_nodes_count": insp_code.ast_nodes_count,
                "defined_classes": insp_code.defined_classes,
                "defined_functions": insp_code.defined_functions,
                "is_degenerate": insp_code.is_degenerate,
                "degenerate_reason": insp_code.degenerate_reason,
            }

    @registry.register(
        name="sensory_evaluate_critic",
        description="Evaluates an artifact against a goal using HarshCritic (includes qwen3-vl visual review for 3D). Returns objective scores (0-100), critique, and specific remediation advice.",
        effect_class=EffectClass.READ_ONLY,
        parameters_schema={
            "goal": "str (the user or engineering goal to evaluate against)",
            "artifact_path": "str (path to the artifact file)",
            "domain": "str (3d | data | code, default 3d)",
        },
    )
    def handle_sensory_evaluate(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        goal = params.get("goal", "")
        artifact_path = params.get("artifact_path", "")
        domain = params.get("domain", "3d").lower()
        p = Path(artifact_path)
        if not p.exists():
            return {"success": False, "error": f"Artifact not found on disk: {artifact_path}"}

        if domain == "3d" or p.suffix.lower() == ".obj":
            insp = rig.inspect_model(p)
            card = critic.evaluate_3d_model(goal, insp)
        elif domain == "data" or p.suffix.lower() == ".csv":
            insp_csv = CSVSensorRig.inspect_csv(p)
            card = critic.evaluate_csv_dataset(goal, insp_csv)
        else:
            return {"success": False, "error": f"Unsupported critic domain: {domain}"}

        return {
            "success": True,
            "score": card.score,
            "passed": card.passed,
            "evaluation_mode": card.evaluation_mode,
            "structural_integrity": card.structural_integrity,
            "feature_specificity": card.feature_specificity,
            "material_separation": card.material_separation,
            "proportion_realism": card.proportion_realism,
            "critique": card.critique,
            "remediation_advice": card.remediation_advice,
            "anti_pattern_signature": card.anti_pattern_signature,
        }

    @registry.register(
        name="skill_search_and_compose",
        description="Semantically searches Sentinel's Skill Bank for previously verified procedural skills, spatial blueprints, and code templates matching the query.",
        effect_class=EffectClass.READ_ONLY,
        parameters_schema={
            "query": "str (search terms or goal description, e.g. 'telescope tripod' or 'spur gear')",
            "domain": "str | None (optional domain filter: 3d | data | code)",
            "limit": "int (max skills to return, default 3)",
        },
    )
    def handle_skill_search(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        if not skill_bank:
            return {"success": False, "error": "SkillBank not initialized on this broker"}

        query = params.get("query", "")
        domain = params.get("domain")
        limit = int(params.get("limit", 3))

        matches = skill_bank.find_relevant_skills(query, domain=domain, limit=limit)
        results = []
        for m in matches:
            results.append({
                "name": m.get("name"),
                "description": m.get("description"),
                "domain": m.get("domain"),
                "score": m.get("score"),
                "code_snippet": m.get("code", "")[:400],
            })

        return {
            "success": True,
            "match_count": len(results),
            "skills": results,
        }

    logger.info("Registered 3 Self-Upgrade & Sensory Reflection Organs into ToolRegistry.")
