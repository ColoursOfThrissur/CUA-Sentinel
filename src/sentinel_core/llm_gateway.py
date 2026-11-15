"""Sentinel LLM Gateway.
Provides dynamic code and reasoning generation using local Ollama models (e.g., qwen3.5:9b).
Supports zero-shot 3D Blender 4.5 bpy code synthesis, error-recovery adaptation, and generic task reasoning.
"""
from __future__ import annotations

import json
import logging
import re
import textwrap
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

logger = logging.getLogger("SentinelLLMGateway")


class LLMGateway:
    """Gateway for local LLM inference via Ollama."""
    gateway_type: str = "local"

    def __init__(
        self,
        endpoint: str = "http://127.0.0.1:11434",
        default_model: str = "qwen2.5-coder:14b",
        timeout_sec: float = 120.0,
        temperature: float = 0.2,
        repeat_penalty: float = 1.15,
        max_tokens: int = 2048,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.default_model = default_model
        self.timeout_sec = timeout_sec
        self.temperature = temperature
        self.repeat_penalty = repeat_penalty
        self.max_tokens = max_tokens

    def is_available(self) -> bool:
        """Check if Ollama service is reachable."""
        try:
            req = urllib.request.Request(f"{self.endpoint}/api/tags")
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                return resp.status == 200
        except Exception:
            return False

    def generate(
        self,
        prompt: str,
        system: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        repeat_penalty: float | None = None,
        strip_thinking: bool = True,
        images: list[str] | None = None,
    ) -> str:
        """Generate text response from local Ollama model with repetition penalties and anti-looping options."""
        target_model = model or self.default_model
        use_temp = self.temperature if temperature is None else temperature
        use_tokens = self.max_tokens if max_tokens is None else max_tokens
        use_repeat_penalty = self.repeat_penalty if repeat_penalty is None else repeat_penalty

        payload: dict[str, Any] = {
            "model": target_model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": use_temp,
                "top_p": 0.9,
                "repeat_penalty": use_repeat_penalty,
                "repeat_last_n": 64,
                "num_predict": use_tokens,
            },
        }
        if system:
            payload["system"] = system
        if images:
            payload["images"] = images

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.endpoint}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                res_json = json.loads(resp.read().decode("utf-8"))
                resp_text = res_json.get("response", "").strip()
                # If response was starved by reasoning token budget, fall back to thinking
                if not resp_text and res_json.get("thinking"):
                    logger.warning("LLM response field empty; extracting content from thinking field")
                    raw_thinking = res_json.get("thinking", "").strip()
                    # Strip leading "Thinking Process:" if followed by actual markdown content
                    resp_text = re.sub(r"^Thinking Process:.*?(?=# |\*\*|## )", "", raw_thinking, flags=re.DOTALL).strip()
                    if not resp_text:
                        resp_text = raw_thinking

                # Strip <think>...</think> blocks if requested to prevent thinking loops
                if strip_thinking and "<think>" in resp_text:
                    post_think = re.sub(r"^.*?<\/think>\s*", "", resp_text, flags=re.DOTALL).strip()
                    if post_think:
                        resp_text = post_think
                    else:
                        resp_text = re.sub(r"<\/?think>", "", resp_text).strip()

                return resp_text
        except urllib.error.URLError as e:
            logger.error("LLM generation failed: %s", e)
            raise RuntimeError(f"Ollama connection error ({target_model}): {e}") from e

    def extract_python_code(self, raw_text: str) -> str:
        """Extracts python code from markdown blocks or plain text with automatic dedenting and truncation healing."""
        # 1. Match ```python ... ```
        m = re.search(r"```python\s*(.*?)\s*```", raw_text, re.DOTALL | re.IGNORECASE)
        code = None
        if m:
            code = textwrap.dedent(m.group(1)).strip()
        elif (m2 := re.search(r"```\s*(.*?)\s*```", raw_text, re.DOTALL)):
            code = textwrap.dedent(m2.group(1)).strip()
        elif (m3 := re.search(r"```(?:python)?\s*(.*)", raw_text, re.DOTALL | re.IGNORECASE)) and ("def " in raw_text or "import " in raw_text or "class " in raw_text):
            cleaned = m3.group(1).strip()
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()
            code = textwrap.dedent(cleaned).strip()
        else:
            lines = []
            for line in raw_text.splitlines():
                if line.strip().startswith(("Here is", "Sure,", "I have", "Note:")):
                    continue
                lines.append(line)
            code = textwrap.dedent("\n".join(lines)).strip()

        # AST-guided trailing truncation self-repair:
        # If output was cut off mid-line by token exhaustion, trim trailing incomplete lines
        if code:
            lines = code.splitlines()
            import ast
            while len(lines) > 3:
                try:
                    ast.parse("\n".join(lines))
                    break
                except SyntaxError:
                    lines.pop()
            if len(lines) > 3:
                code = "\n".join(lines).strip()

        return code or ""

    def plan_3d_assembly(
        self,
        goal: str,
        anti_patterns: str = "",
        model: str | None = None,
    ) -> str:
        """Stage 1: Senior Mechanical Assembly Architect plans the physical coordinate hierarchy and metric proportions."""
        system_planner = (
            "You are Sentinel's Senior Mechanical Assembly Architect.\n"
            "Before 3D code is written, you design the physical assembly hierarchy, coordinate budgets, and realistic proportions.\n\n"
            "CRITICAL PHYSICAL ASSEMBLY RULES:\n"
            "1. Ground Plane is Z = 0: All stands, tripods, ground bases, or wheels must rest on or touch the ground (Z=0).\n"
            "   * BLENDER CENTERING RULE: Blender primitives (cylinders, cubes, cones) are centered at their midpoint! If a part has height H and rests on ground Z=0, its center Z is H/2, NOT 0. Putting center Z=0 buries half underground.\n"
            "   * If tripod legs support a mount at height Z_mount, leg midpoint Z must be Z_mount/2 and depth must span Z_mount.\n"
            "2. Structural Hierarchy & Parent Chaining:\n"
            "   - Base/Stand spans from ground Z=0 up to central mount hub.\n"
            "   - Main body (optical tube, actuator cylinder, gear shaft) anchors to mount hub.\n"
            "   - Sub-features (dew shields, eyepieces, focus knobs, fluid fittings, piston rods) attach directly to parent surfaces. ZERO floating disconnected parts.\n"
            "3. Telescoping & Protrusion (Visibility Rule):\n"
            "   - Internal moving parts (piston rods, hydraulic rams, rotating inner shafts) must PROTRUDE visibly outside their outer barrels or housings.\n"
            "   - Mount fittings (clevis lugs, pivot brackets) attach at the extreme opposite ends of assemblies (e.g. base of barrel and tip of extended rod), never in the middle.\n"
            "4. Realistic Articulation & Orientation:\n"
            "   - Point directional bodies naturally (e.g. telescope optical tube tilted at 35°-45° viewing angle; robotic claws counter-opposed).\n"
            "   - Splay tripod legs outward symmetrically from the mount hub down to Z=0 with both pitch tilt and radial yaw (ground footprint radius >= 0.4 * height, 120° apart).\n"
            "5. Proportions & Materials:\n"
            "   - Sizing must be physically plausible in meters.\n"
            "   - Assign distinct contrasting Principled BSDF materials across functional components (e.g. chrome vs matte paint, brass vs dark iron).\n\n"
            "Output strictly a clean JSON assembly blueprint with keys:\n"
            '{"root_part": "...", "overall_height": <float>, "parts": [{"name": "...", "primitive": "cylinder|cube|cone|torus|sphere", '
            '"location": [x, y, z], "dimensions": {"radius": <float>, "depth": <float>}, "rotation_deg": [rx, ry, rz], '
            '"material": {"name": "...", "color": [r, g, b], "metallic": <float>, "roughness": <float>}}]}'
        )
        prompt = f"Goal: {goal}"
        if anti_patterns:
            prompt += f"\n\n[AVOID DEFECT FROM PREVIOUS ATTEMPT]:\n{anti_patterns}"

        try:
            raw_blueprint = self.generate(
                prompt=prompt,
                system=system_planner,
                model=model or self.default_model,
                temperature=0.1,
                max_tokens=1024,
            )
            clean = raw_blueprint.strip()
            if "```json" in clean:
                clean = clean.split("```json")[1].split("```")[0].strip()
            elif "```" in clean:
                clean = clean.split("```")[1].split("```")[0].strip()
            return clean
        except Exception as e:
            logger.warning("Stage 1 Spatial Assembly Planning failed (%s); proceeding without blueprint", e)
            return ""

    def generate_blender_code(
        self,
        goal: str,
        output_obj_path: str,
        anti_patterns: str = "",
        model: str | None = None,
        relevant_skills: list[dict] | None = None,
        previous_code: str | None = None,
        error_feedback: str | None = None,
        spatial_blueprint: str | None = None,
    ) -> str:
        """Generates Blender 4.5 Python (bpy) script with two-stage hierarchical spatial planning."""
        escaped_path = output_obj_path.replace("\\", "/")

        # Stage 1: Generate Spatial Assembly Blueprint if not provided
        if not spatial_blueprint:
            spatial_blueprint = self.plan_3d_assembly(
                goal=goal,
                anti_patterns=error_feedback or anti_patterns,
                model=model,
            )

        system_instruction = (
            "You are Sentinel's 3D Model Synthesizer. You produce strictly valid Python code for Blender 4.5 LTS (bpy).\n"
            "CRITICAL INSTRUCTIONS:\n"
            "1. Output ONLY executable Python code inside a ```python ``` block. No explanations, no introductory or concluding text.\n"
            "2. Always start with:\n"
            "   import bpy\n"
            "   import math\n"
            "   bpy.ops.wm.read_factory_settings(use_empty=True)\n"
            "3. OBJECT CREATION & NAMING:\n"
            "   - Grab active object immediately: `obj = bpy.context.active_object`.\n"
            "   - Name every object clearly: `obj.name = 'Descriptive_Part_Name'` (e.g. 'Outer_Barrel', 'Piston_Rod', 'Mount_Hub', 'Tripod_Leg_1').\n"
            "   - DO NOT call bpy.data.objects.new() or collection.link()! Just call primitive_*_add and grab obj = bpy.context.active_object.\n"
            "4. PARENT-CHILD CHAINING & LOCAL COORDINATES:\n"
            "   - For attached sub-components (dew shields, nozzles, knobs, brackets): assign `child.parent = parent`!\n"
            "   - When parented, `child.location` is LOCAL to parent and automatically inherits the parent's tilt and rotation!\n"
            "     * E.g. To place a dew shield at the front aperture of a tube of length L: `shield.parent = tube; shield.location = (0, 0, L/2)`.\n"
            "     * E.g. To place a focus knob on the side of a tube: `knob.parent = tube; knob.location = (radius + 0.05, 0, -L/3)`.\n"
            "5. SPATIAL ADJACENCY & ANTI-DRIFT RULES:\n"
            "   - BLENDER CENTERING RULE: All standard primitives (cylinders, cubes, cones) are centered at their midpoint! An object of height H resting on ground Z=0 MUST have location Z = H/2, NOT 0. Putting location Z=0 buries half the object underground!\n"
            "   - TELESCOPING & PROTRUSION (VISIBILITY): Internal moving parts (piston rods, hydraulic rams) must extend visibly OUTSIDE the barrel so they are not hidden inside! Clevis mount lugs go at the two extreme tips (base of barrel and tip of extended rod).\n"
            "   - TRIPOD SPLAYING: Tripod legs must splay outward with both pitch tilt and radial yaw from the central mount hub down to ground Z=0.\n"
            "   - MOUNTING HOLES & BOLTS: For flange/plate bolt holes, add small hexagonal bolt heads (`primitive_cylinder_add(vertices=6, depth=0.03, ...)`).\n"
            "6. ALWAYS assign a Principled BSDF material with contrasting color and texture to each object:\n"
            "   mat = bpy.data.materials.new(name='MyPart_Mat')\n"
            "   mat.use_nodes = True\n"
            "   bsdf = mat.node_tree.nodes.get('Principled BSDF')\n"
            "   bsdf.inputs['Base Color'].default_value = (R, G, B, 1.0)  # floats 0-1\n"
            "   bsdf.inputs['Metallic'].default_value = 0.9  # 0.9=metal, 0.0=matte/rubber\n"
            "   bsdf.inputs['Roughness'].default_value = 0.3\n"
            "   obj.data.materials.append(mat)\n"
            "   - Differentiate materials across components: pair polished metals (Metallic=1.0, Roughness=0.1) with dark matte structural parts (Metallic=0.0, Roughness=0.7) for high visual fidelity.\n"
            "7. End the script with exporting the scene to OBJ:\n"
            f'   bpy.ops.wm.obj_export(filepath=r"{escaped_path}")\n'
            '   print("SENTINEL_3D_MODEL_EXPORTED_OK")\n'
        )

        prompt_body = f"User Request: Synthesize a 3D model for: '{goal}'\nTarget OBJ export path: '{escaped_path}'"

        if spatial_blueprint:
            prompt_body += (
                f"\n\n[APPROVED HIERARCHICAL MECHANICAL BLUEPRINT]:\n"
                f"```json\n{spatial_blueprint}\n```\n\n"
                f"BLUEPRINT EXECUTION DIRECTIVE:\n"
                f"Instantiate every part defined in the blueprint above at its specified location and rotation.\n"
                f"Apply the planned materials to each part. Do not place objects at (0,0,0) if the blueprint specifies offsets."
            )

        if relevant_skills:
            skill_blocks = []
            for s in relevant_skills[:2]:
                code_snip = s.get("code") or ""
                lines = [ln for ln in code_snip.splitlines() if not ln.startswith("import") and "read_factory_settings" not in ln]
                trimmed = "\n".join(lines[:22]).strip()
                if trimmed:
                    skill_blocks.append(
                        f"### Verified Recipe: `{s.get('name')}` ({s.get('description')}):\n```python\n{trimmed}\n```"
                    )
            if skill_blocks:
                prompt_body += (
                    f"\n\n[PROVEN HIGH-SCORE PROCEDURAL RECIPES FROM SKILL BANK]:\n"
                    f"Borrow these verified geometric structuring, naming, and material patterns:\n\n"
                    + "\n\n".join(skill_blocks) + "\n"
                )

        if previous_code and error_feedback:
            prompt_body += (
                f"\n\n[PREVIOUS ATTEMPT EXECUTION FAILURE - REFLECTIVE DEBUGGING]:\n"
                f"Your previous script crashed inside Blender with the following error:\n"
                f"--------------------------------------------------\n"
                f"{error_feedback}\n"
                f"--------------------------------------------------\n\n"
                f"PREVIOUS SCRIPT:\n"
                f"```python\n{previous_code}\n```\n\n"
                f"DEBUGGING DIRECTIVE:\n"
                f"1. Read the error message carefully. Understand why it failed.\n"
                f"2. Rewrite the code to fix the root cause.\n"
                f"3. Make sure all variables are defined and objects have real vertices.\n"
                f"4. Generate a complete, corrected script."
            )
        elif anti_patterns:
            prompt_body += (
                f"\n\n[CRITICAL LESSON FROM PREVIOUS FAILED ATTEMPT]:\n"
                f"The previous script failed execution with the following error/anti-pattern:\n"
                f"```\n{anti_patterns}\n```\n"
                f"DO NOT repeat this error. Fix the syntax/operator usage and generate a corrected script."
            )

        raw_response = self.generate(
            prompt=prompt_body,
            system=system_instruction,
            model=model or self.default_model,
            temperature=0.2,
            max_tokens=4096,
        )

        extracted_code = self.extract_python_code(raw_response)

        # Safety verification of code structure: ensure export command is present
        if "obj_export" not in extracted_code:
            extracted_code += f'\n\n# Ensure OBJ export\nbpy.ops.wm.obj_export(filepath=r"{escaped_path}")\nprint("SENTINEL_3D_MODEL_EXPORTED_OK")\n'

        return extracted_code
