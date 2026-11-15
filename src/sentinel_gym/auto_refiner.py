"""Sentinel Auto-Refiner & Plasticity Engine.
Consumes empirical critic reviews to evolve Sentinel's capability boundary:
- Distills high-fidelity artifacts (score >= 0.82) into compound skills in SkillBank and VectorIndex.
- Records rigorous anti-pattern heuristics (score < 0.82) in MistakeLedger to prevent recurring defects.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sentinel_adaptive.skill_bank import SkillBank, derive_semantic_slug
from sentinel_adaptive.mistake_ledger import MistakeMemory
from sentinel_broker.tool_registry import ToolRegistry
from sentinel_gym.critic import CriticScorecard

logger = logging.getLogger("SentinelAutoRefiner")


@dataclass
class RefinementOutcome:
    action_taken: str  # "SKILL_DISTILLED" | "ANTI_PATTERN_RECORDED" | "DISCARDED"
    skill_name: str | None = None
    skill_path: str | None = None
    mistake_id: int | None = None
    summary: str = ""


class AutoRefiner:
    """Closes the feedback loop between physical sensory reality and code/tool improvement."""

    def __init__(
        self,
        skill_bank: SkillBank,
        mistake_memory: MistakeMemory,
        tool_registry: ToolRegistry | None = None,
    ):
        self.skill_bank = skill_bank
        self.mistake_memory = mistake_memory
        self.tool_registry = tool_registry

    def process_evaluation(
        self,
        task_id: str,
        attempt_id: str,
        goal: str,
        domain: str,
        code_or_script: str,
        scorecard: CriticScorecard,
        artifact_path: str | Path | None = None,
    ) -> RefinementOutcome:
        """Translates empirical evaluation into permanent capability upgrades or anti-patterns."""
        # 1. High-Fidelity Promotion to Skill Bank (Score >= 0.82)
        if scorecard.passed:
            # Fallback code recovery if empty string was passed
            resolved_code = code_or_script.strip()
            if not resolved_code and artifact_path and Path(artifact_path).exists():
                art_p = Path(artifact_path)
                if art_p.suffix in [".py", ".sh", ".sql", ".csv"]:
                    try:
                        resolved_code = art_p.read_text(encoding="utf-8", errors="ignore").strip()
                    except Exception:
                        pass

            if not resolved_code:
                logger.warning("AutoRefiner skipping skill distillation: synthesized code payload is empty")
                return RefinementOutcome(
                    action_taken="DISCARDED",
                    summary="Artifact passed evaluation but code payload was empty.",
                )

            slug = derive_semantic_slug(goal, domain=domain)
            desc = f"Verified high-fidelity {domain} procedural skill for: {goal}. Critic Score: {scorecard.score:.2f}/1.0."
            try:
                skill_rec = self.skill_bank.distill_skill(
                    name=slug,
                    description=desc,
                    code=resolved_code,
                    domain=domain,
                    parameters_schema={"goal": "str", "output_path": "str"},
                    metadata={"critic_score": scorecard.score, "features": scorecard.critique},
                    registry=self.tool_registry,
                )
                logger.info("AutoRefiner PROMOTED artifact to SkillBank: %s (Score: %.2f)", slug, scorecard.score)
                return RefinementOutcome(
                    action_taken="SKILL_DISTILLED",
                    skill_name=slug,
                    skill_path=skill_rec.get("folder"),
                    summary=f"Evolved new verified skill '{slug}' (Score: {scorecard.score:.2f})",
                )
            except Exception as e:
                logger.error("Failed to distill skill in AutoRefiner: %s", e)
                return RefinementOutcome(
                    action_taken="ERROR",
                    summary=f"Failed to distill skill: {e}",
                )

        # 2. Defect Remediation: Record Anti-Pattern in Episodic Memory
        cat = scorecard.anti_pattern_signature or "EMPIRICAL_DEFECT"
        sig = scorecard.critique[:80].replace("'", "").replace('"', "")
        lesson = scorecard.remediation_advice

        try:
            mid = self.mistake_memory.record_mistake(
                task_id=task_id,
                attempt_id=attempt_id,
                error_category=cat,
                error_signature=sig,
                context={"domain": domain, "score": scorecard.score, "goal": goal},
                lesson_learned=lesson,
            )
            logger.info("AutoRefiner RECORDED anti-pattern #%d [%s]: %s", mid, cat, lesson)
            return RefinementOutcome(
                action_taken="ANTI_PATTERN_RECORDED",
                mistake_id=mid,
                summary=f"Recorded preventative lesson in episodic memory: {lesson[:100]}",
            )
        except Exception as e:
            logger.warning("Failed to record mistake in AutoRefiner: %s", e)
            return RefinementOutcome(
                action_taken="DISCARDED",
                summary=f"Sub-par output discarded (Score: {scorecard.score:.2f})",
            )
