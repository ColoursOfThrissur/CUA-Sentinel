"""Sentinel Curiosity Frontier Generator (Curriculum Engine).
Inspects the current SkillBank catalog and past episodic failures to generate novel,
progressive challenge tasks at the edge of Sentinel's capability frontier.
"""
from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any

from sentinel_adaptive.skill_bank import SkillBank
from sentinel_adaptive.mistake_ledger import MistakeMemory
from sentinel_core.llm_gateway import LLMGateway

logger = logging.getLogger("SentinelCurriculum")


@dataclass
class CurriculumChallenge:
    challenge_id: str
    goal: str
    domain: str  # "3d" | "data" | "code"
    difficulty_tier: int  # 1 (Foundation) to 5 (Mastery)
    expected_features: list[str]
    category: str


# Progressive challenge library across domains
FOUNDATIONAL_CHALLENGES = [
    # 3D Mechanical & Optical Frontier
    {
        "domain": "3d",
        "category": "mechanics",
        "difficulty": 2,
        "goal": "Synthesize a 3D articulated robotic gripper with a servo mount hub, two counter-opposed dual-finger claws, and rubber grip pads with metallic brass and matte black shaders.",
        "expected_features": ["mount_hub", "left_claw", "right_claw", "finger_pads", "materials"],
    },
    {
        "domain": "3d",
        "category": "optics",
        "difficulty": 3,
        "goal": "Synthesize a 3D equatorial telescope assembly with an optical tube, front dew shield, eyepiece focus knob, and a triangular tripod base with polished bronze and deep enameled blue finishes.",
        "expected_features": ["optical_tube", "dew_shield", "focus_knob", "tripod_legs", "materials"],
    },
    {
        "domain": "3d",
        "category": "hydraulics",
        "difficulty": 3,
        "goal": "Synthesize a 3D heavy-duty hydraulic actuator with a cylindrical outer barrel, chrome-plated extending piston rod, pivot clevis mounting lugs, and hydraulic fluid port fittings.",
        "expected_features": ["cylinder_barrel", "piston_rod", "mounting_clevis", "fluid_ports", "materials"],
    },
    {
        "domain": "3d",
        "category": "transmission",
        "difficulty": 4,
        "goal": "Synthesize a 3D spur gear transmission assembly featuring an input drive shaft, 12-tooth central pinion gear, outer 36-tooth ring gear, and mounting flange collar.",
        "expected_features": ["drive_shaft", "pinion_gear", "ring_gear", "flange_collar", "materials"],
    },
    {
        "domain": "3d",
        "category": "aerospace",
        "difficulty": 4,
        "goal": "Synthesize a 3D aerospace reaction engine gimbal with a conical bell exhaust nozzle, gimbal ring cradle, fuel intake manifolds, and high-temperature alloy materials.",
        "expected_features": ["exhaust_nozzle", "gimbal_ring", "fuel_manifolds", "nozzle_throat", "materials"],
    },
    # Tabular Data Frontier
    {
        "domain": "data",
        "category": "cybersecurity",
        "difficulty": 2,
        "goal": "Generate a synthetic cybersecurity intrusion detection dataset with 200 rows containing timestamp, source_ip, destination_port, protocol, packet_size_bytes, anomaly_score, and threat_verdict.",
        "expected_features": ["realistic_ips", "port_distribution", "anomaly_variance"],
    },
    {
        "domain": "data",
        "category": "renewable_energy",
        "difficulty": 3,
        "goal": "Generate a synthetic solar farm power generation telemetry dataset covering 24 hourly intervals across 10 inverters with solar_irradiance, ambient_temp_c, panel_temp_c, dc_input_kw, and ac_output_kw.",
        "expected_features": ["diurnal_cycle", "efficiency_ratio", "temperature_correlation"],
    },
]


class CurriculumGenerator:
    """Proposes novel, edge-of-frontier challenges to train the agent autonomously."""

    def __init__(
        self,
        skill_bank: SkillBank | None = None,
        mistake_memory: MistakeMemory | None = None,
        llm_gateway: LLMGateway | None = None,
    ):
        self.skill_bank = skill_bank
        self.mistake_memory = mistake_memory
        self.gateway = llm_gateway
        self._history: list[str] = []

    def generate_next_challenge(
        self,
        domain: str = "3d",
        prefer_frontier: bool = True,
        force_frontier: bool = False,
    ) -> CurriculumChallenge:
        """Selects or dynamically synthesizes the next training task."""
        now_ts = int(time.time() * 1000)
        challenge_id = f"gym_task_{now_ts % 1000000}"

        matching = [c for c in FOUNDATIONAL_CHALLENGES if c["domain"] == domain]
        unseen = [c for c in matching if c["goal"] not in self._history]

        # 1. Dynamic Frontier Synthesis via LLM if available and preferred
        if (force_frontier or (prefer_frontier and (not unseen or random.random() < 0.50))) and self.gateway:
            dynamic = self._synthesize_frontier_challenge(domain, challenge_id)
            if dynamic:
                self._history.append(dynamic.goal)
                return dynamic

        # 2. Select from foundational challenges pool
        pool = unseen if unseen else matching
        if pool:
            chosen = random.choice(pool)
            self._history.append(chosen["goal"])
            return CurriculumChallenge(
                challenge_id=challenge_id,
                goal=chosen["goal"],
                domain=chosen["domain"],
                difficulty_tier=chosen["difficulty"],
                expected_features=chosen["expected_features"],
                category=chosen["category"],
            )

        # Fallback default
        default_goal = "Synthesize an articulated multi-component mechanical assembly with distinct materials in Blender."
        return CurriculumChallenge(
            challenge_id=challenge_id,
            goal=default_goal,
            domain="3d",
            difficulty_tier=2,
            expected_features=["base", "shaft", "joint", "materials"],
            category="mechanics",
        )

    def _synthesize_frontier_challenge(self, domain: str, challenge_id: str) -> CurriculumChallenge | None:
        """Synthesizes a novel, frontier challenge targeting recent agent mistakes and mastered skills."""
        mastered = []
        if self.skill_bank:
            mastered = [s["name"] for s in self.skill_bank.list_skills()[:6]]

        recent_defects = []
        if self.mistake_memory:
            try:
                rows = self.mistake_memory.db.execute_read(
                    "SELECT error_category, error_signature, lesson_learned FROM mistake_ledger ORDER BY ts DESC LIMIT 4"
                )
                recent_defects = [f"{r['error_category']}: {r['lesson_learned'][:70]}" for r in rows]
            except Exception:
                pass

        sys_prompt = (
            "You are Sentinel's Curriculum Architect for autonomous agent training.\n"
            "Your job is to generate a novel, specific engineering task that pushes the agent's capability frontier.\n"
            "Requirements:\n"
            "- 3D tasks must specify multi-part articulated components, distinct physical materials (metals, enamels, rubber), and clear spatial structure.\n"
            "- Data tasks must specify realistic columns, constraints, and statistical distributions.\n"
            "Output strictly valid JSON with keys: goal, difficulty_tier (1-5), category, expected_features (list of 4-6 strings)."
        )

        user_prompt = (
            f"Generate a novel training challenge for domain: {domain.upper()}.\n"
            f"Agent has already mastered: {', '.join(mastered) if mastered else 'basic primitives'}.\n"
            f"Agent recently struggled with: {'; '.join(recent_defects) if recent_defects else 'none'}.\n"
            "Challenge should be concrete, descriptive, and avoid repetition."
        )

        try:
            resp = self.gateway.generate(
                prompt=user_prompt,
                system=sys_prompt,
                temperature=0.7,
                max_tokens=300,
            )
            clean = resp.strip()
            if "```json" in clean:
                clean = clean.split("```json")[1].split("```")[0].strip()
            elif "```" in clean:
                clean = clean.split("```")[1].split("```")[0].strip()

            data = json.loads(clean)
            goal_text = data.get("goal", "").strip()
            if goal_text and len(goal_text) > 30 and goal_text not in self._history:
                logger.info("Curriculum synthesized dynamic frontier challenge: %s", goal_text[:80])
                return CurriculumChallenge(
                    challenge_id=challenge_id,
                    goal=goal_text,
                    domain=domain,
                    difficulty_tier=max(1, min(5, int(data.get("difficulty_tier", 3)))),
                    expected_features=data.get("expected_features", ["component_assembly", "contrasting_materials"]),
                    category=data.get("category", "frontier_synthesis"),
                )
        except Exception as e:
            logger.debug("Curriculum dynamic frontier synthesis fallback: %s", e)

        return None
