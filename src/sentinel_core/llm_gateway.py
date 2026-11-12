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
        default_model: str = "qwen3.5:9b",
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
        """Extracts python code from markdown blocks or plain text with automatic dedenting."""
        # 1. Match ```python ... ```
        m = re.search(r"```python\s*(.*?)\s*```", raw_text, re.DOTALL | re.IGNORECASE)
        if m:
            return textwrap.dedent(m.group(1)).strip()
        # 2. Match generic ``` ... ```
        m2 = re.search(r"```\s*(.*?)\s*```", raw_text, re.DOTALL)
        if m2:
            return textwrap.dedent(m2.group(1)).strip()
        # 3. Handle unclosed ```python block
        m3 = re.search(r"```(?:python)?\s*(.*)", raw_text, re.DOTALL | re.IGNORECASE)
        if m3 and ("def " in raw_text or "import " in raw_text or "class " in raw_text):
            cleaned = m3.group(1).strip()
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()
            return textwrap.dedent(cleaned).strip()
        # 4. Clean up raw text if lines resemble python
        lines = []
        for line in raw_text.splitlines():
            # Filter out non-code commentary if outside code blocks
            if line.strip().startswith(("Here is", "Sure,", "I have", "Note:")):
                continue
            lines.append(line)
        return textwrap.dedent("\n".join(lines)).strip()

    def generate_blender_code(
        self,
        goal: str,
        output_obj_path: str,
        anti_patterns: str = "",
        model: str | None = None,
        relevant_skills: list[dict] | None = None,
    ) -> str:
        """Generates Blender 4.5 Python (bpy) script using qwen3.5:9b with error-aware self-healing."""
        escaped_path = output_obj_path.replace("\\", "/")

        system_instruction = (
            "You are Sentinel's 3D Model Synthesizer. You produce strictly valid Python code for Blender 4.5 LTS (bpy).\n"
            "CRITICAL INSTRUCTIONS:\n"
            "1. Output ONLY executable Python code inside a ```python ``` block. No explanations, no introductory or concluding text.\n"
            "2. Always start with:\n"
            "   import bpy\n"
            "   import math\n"
            "   bpy.ops.wm.read_factory_settings(use_empty=True)\n"
            "3. Construct realistic, well-proportioned 3D geometry matching the user's prompt using standard Blender 4.5 operators:\n"
            "   - bpy.ops.mesh.primitive_cylinder_add(radius=..., depth=..., location=..., rotation=...)\n"
            "   - bpy.ops.mesh.primitive_cube_add(size=..., location=..., rotation=...)\n"
            "   - bpy.ops.mesh.primitive_uv_sphere_add(radius=..., location=...)\n"
            "   - bpy.ops.mesh.primitive_torus_add(major_radius=..., minor_radius=..., location=...)\n"
            "   - bpy.ops.mesh.primitive_cone_add(radius1=..., depth=..., location=...)\n"
            "   CRITICAL RULES FOR OBJECT CREATION:\n"
            "   - The primitive operators automatically create and link the object into the scene.\n"
            "   - DO NOT call bpy.data.objects.new() or collection.link()! Just call primitive_*_add and grab obj = bpy.context.active_object.\n"
            "   - Rotations must be 3 floats: rotation=(math.radians(90), 0, 0). Never nest extra parentheses.\n"
            "4. ALWAYS assign a Principled BSDF material with a thematic base color to each object:\n"
            "   mat = bpy.data.materials.new(name='MyMat')\n"
            "   mat.use_nodes = True\n"
            "   bsdf = mat.node_tree.nodes.get('Principled BSDF')\n"
            "   bsdf.inputs['Base Color'].default_value = (R, G, B, 1.0)  # floats 0-1\n"
            "   bsdf.inputs['Metallic'].default_value = 0.0  # 0=plastic, 1=metal\n"
            "   bsdf.inputs['Roughness'].default_value = 0.5\n"
            "   obj.data.materials.append(mat)\n"
            "5. For interesting results, optionally add modifiers BEFORE the export (apply them first):\n"
            "   mod = obj.modifiers.new(name='Bevel', type='BEVEL'); mod.width=0.05; mod.segments=2\n"
            "   bpy.context.view_layer.objects.active = obj; bpy.ops.object.modifier_apply(modifier='Bevel')\n"
            "6. End the script with exporting the scene to OBJ:\n"
            f'   bpy.ops.wm.obj_export(filepath=r"{escaped_path}")\n'
            '   print("SENTINEL_3D_MODEL_EXPORTED_OK")\n'
        )

        prompt_body = f"User Request: Synthesize a 3D model for: '{goal}'\nTarget OBJ export path: '{escaped_path}'"

        if relevant_skills:
            skill_lines = [
                f"• `{s.get('name')}`: {s.get('description')} (Module: skills/{s.get('name')}/tool.py)"
                for s in relevant_skills[:3]
            ]
            prompt_body += (
                f"\n\n[COMPOUND SKILL BANK - REUSABLE 3D TECHNIQUES]:\n"
                f"Sentinel has previously verified these 3D skills:\n"
                + "\n".join(skill_lines) + "\n"
                f"You can borrow modeling structure, transform sequences, or naming patterns from them."
            )

        if anti_patterns:
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
        )

        extracted_code = self.extract_python_code(raw_response)

        # Safety verification of code structure: ensure export command is present
        if "obj_export" not in extracted_code:
            extracted_code += f'\n\n# Ensure OBJ export\nbpy.ops.wm.obj_export(filepath=r"{escaped_path}")\nprint("SENTINEL_3D_MODEL_EXPORTED_OK")\n'

        return extracted_code
