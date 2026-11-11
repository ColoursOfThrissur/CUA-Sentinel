"""Sentinel Prompt Scaffolding System.
Provides tiered prompt engineering, domain guardrails, and context injection
to maximize LLM autonomy and minimize human/system hand-holding.
"""
from __future__ import annotations

from enum import Enum
from typing import Any


class ScaffoldingLevel(str, Enum):
    """Degrees of system hand-holding provided to the LLM."""
    LEVEL_0_RAW = "raw"              # Zero hand-holding: direct user goal only
    LEVEL_1_FORMAT = "format"        # Output format & role contract
    LEVEL_2_GUARDED = "guarded"      # Domain API guardrails, constraints & pitfalls
    LEVEL_3_ADAPTIVE = "adaptive"    # Semantic anti-pattern injection & cross-task memory


# Domain-specific API constraints and cheat-sheets for local LLMs
DOMAIN_GUARDRAILS = {
    "3d": (
        "BLENDER 4.5 LTS API CONSTRAINTS:\n"
        "1. Initialization: ALWAYS call bpy.ops.wm.read_factory_settings(use_empty=True) first.\n"
        "2. Export: Blender 4.0+ uses bpy.ops.wm.obj_export(filepath=r'...') - DO NOT use bpy.ops.export_scene.obj.\n"
        "3. Materials: Principled BSDF in Blender 4.0+ renamed inputs. DO NOT access .inputs['Specular'] as a float. "
        "Use inputs['Roughness'].default_value and inputs['Base Color'].default_value.\n"
        "4. Geometry: Build multi-primitive geometry with non-zero dimensions using mesh operators (cylinder, cube, sphere, torus).\n"
        "5. Output: Return ONLY executable Python inside a ```python ``` block. No markdown explanation."
    ),
    "code": (
        "PYTHON ALGORITHM & CODE CONTRACT:\n"
        "1. Self-Contained: Use standard library only (e.g. collections.OrderedDict, heapq, typing). No external pip dependencies.\n"
        "2. Core Implementation: Implement ONLY the requested class and methods (e.g. LRUCache with get and put).\n"
        "3. Eviction Semantics: popitem(last=False) removes the LRU item cleanly. DO NOT call del cache[key] after popitem().\n"
        "4. No Self-Tests Needed: DO NOT write lengthy or contradictory self-tests. Sentinel verifies your code with an independent external contract harness.\n"
        "5. Output: Return ONLY executable Python code inside a ```python ``` block."
    ),
    "data": (
        "CSV & DATASET CONTRACT:\n"
        "1. Format: RFC 4180 compliant CSV (comma-delimited, double quotes for strings with commas).\n"
        "2. Structure: Row 1 MUST be headers. Include at least 4 descriptive columns (e.g. id/date, category, quantity, monetary/rate).\n"
        "3. Substantive: Provide at least 5 realistic data rows with valid numeric distributions.\n"
        "4. Clean Output: Output raw CSV data directly without introductory or trailing prose."
    ),
    "report": (
        "STRUCTURED ANALYSIS CONTRACT:\n"
        "1. Structure: Use clear Markdown hierarchy (# Title, ## Executive Summary, ## Findings, ## Recommendations).\n"
        "2. Depth: Provide substantive analysis (minimum 100 words), with bullet points and comparison tables where applicable.\n"
        "3. Tone: Direct, technical, and objective."
    ),
}


class PromptScaffolder:
    """Builds structured prompt envelopes based on domain and hand-holding level."""

    @staticmethod
    def build_system_prompt(domain: str, level: ScaffoldingLevel = ScaffoldingLevel.LEVEL_2_GUARDED) -> str:
        """Constructs system instruction reflecting the desired scaffolding degree."""
        if level == ScaffoldingLevel.LEVEL_0_RAW:
            return ""

        base_roles = {
            "3d": "You are Sentinel's Autonomous 3D Artisan for Blender 4.5.",
            "code": "You are Sentinel's Autonomous Senior Software Engineer.",
            "data": "You are Sentinel's Autonomous Data Analyst.",
            "report": "You are Sentinel's Autonomous Systems Analyst.",
        }
        role = base_roles.get(domain, "You are Sentinel's Autonomous Task Worker.")

        if level == ScaffoldingLevel.LEVEL_1_FORMAT:
            return f"{role} Output clean, precise results solving the goal. Format code inside ```python ``` blocks."

        # LEVEL_2_GUARDED and LEVEL_3_ADAPTIVE include domain guardrails
        guardrail = DOMAIN_GUARDRAILS.get(domain, "")
        return f"{role}\n\n{guardrail}"

    @staticmethod
    def build_user_prompt(
        goal: str,
        domain: str,
        artifact_path: str = "",
        anti_patterns: str = "",
        historic_lessons: list[str] | None = None,
        relevant_skills: list[dict[str, Any]] | None = None,
        level: ScaffoldingLevel = ScaffoldingLevel.LEVEL_2_GUARDED,
    ) -> str:
        """Enriches the user prompt with path targets, compound skills, and adaptive feedback."""
        if level == ScaffoldingLevel.LEVEL_0_RAW:
            return goal

        escaped_path = artifact_path.replace("\\", "/") if artifact_path else ""
        prompt_parts = [f"Goal: {goal}"]

        if escaped_path:
            prompt_parts.append(f"Target Output Path: '{escaped_path}'")

        # Compound Skill Bank: inject previously verified skills for reuse
        if relevant_skills:
            skill_lines = []
            for s in relevant_skills[:3]:
                s_name = s.get("name", "")
                s_desc = s.get("description", "")
                s_dom = s.get("domain", "")
                skill_lines.append(
                    f"• `{s_name}` ({s_dom}): {s_desc} (Module: skills/{s_name}/tool.py)"
                )
            prompt_parts.append(
                f"\n[COMPOUND SKILL BANK - REUSABLE VERIFIED SKILLS]:\n"
                f"Sentinel has previously verified the following skills relevant to this goal:\n"
                + "\n".join(skill_lines) + "\n"
                f"You can import directly from these modules or invoke them to accelerate your solution."
            )

        # In Level 3 (Adaptive), inject previous defects and cross-task memory
        if level == ScaffoldingLevel.LEVEL_3_ADAPTIVE:
            if historic_lessons:
                # Bounded cross-task memory: top 2 only, capped
                lessons_block = "\n".join(f"- {h[:120]}" for h in historic_lessons[:2])
                prompt_parts.append(
                    f"\n[ORGAN MEMORY - PREVIOUS DOMAIN LESSONS (MAX 2)]:\n{lessons_block}"
                )

            if anti_patterns:
                # Upgrade C: Surgical Anchoring
                tb_lines = [l.strip() for l in anti_patterns.splitlines() if l.strip()]
                last_err = tb_lines[-1] if tb_lines else "Unknown error"
                prompt_parts.append(
                    f"\n[SURGICAL REPAIR REQUIRED - DO NOT REGENERATE WORKING PARTS]:\n"
                    f"The previous attempt failed with defect: '{last_err}'\n"
                    f"Traceback details:\n```\n{anti_patterns}\n```\n"
                    f"Preserve all working logic and apply a surgical fix resolving '{last_err}' directly."
                )

        return "\n".join(prompt_parts)
