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
    ) -> CurriculumChallenge:
        """Selects or dynamically synthesizes the next training task."""
        now_ts = int(time.time() * 1000)
        challenge_id = f"gym_task_{now_ts % 1000000}"

        # 1. Filter standard library challenges matching domain
        matching = [c for c in FOUNDATIONAL_CHALLENGES if c["domain"] == domain]
        unseen = [c for c in matching if c["goal"] not in self._history]
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
