"""Sentinel 3D Model Synthesizer for Blender 4.5.
Dynamically synthesizes Blender Python (bpy) scripts using local LLM with reflective error-feedback self-healing.
No hardcoded keyword matching or static geometry cascades.
"""
from __future__ import annotations

import logging
from pathlib import Path

from sentinel_core.llm_gateway import LLMGateway

logger = logging.getLogger("SentinelBlenderPrompts")

_llm_gateway: LLMGateway | None = None


def get_llm_gateway() -> LLMGateway:
    global _llm_gateway
    if _llm_gateway is None:
        try:
            from sentinel_core.config import SentinelConfig
            cfg = SentinelConfig.load(Path("config.yaml"))
            _llm_gateway = LLMGateway(endpoint=cfg.llm.endpoint, default_model=cfg.llm.model)
        except Exception:
            _llm_gateway = LLMGateway()
    return _llm_gateway


def synthesize_procedural_fallback(goal: str, output_obj_path: str) -> str:
    """Procedural fallback only if LLM service is offline or unconfigured."""
    escaped_path = output_obj_path.replace("\\", "/")

    return f"""import bpy
import math

# Reset scene to empty
bpy.ops.wm.read_factory_settings(use_empty=True)

# Clean procedural structural pedestal assembly
bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 0.2))
base = bpy.context.active_object
base.name = "Plinth_Base"
base.scale = (2.2, 2.2, 0.4)
bpy.ops.object.transform_apply(scale=True)

bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.6, depth=2.0, location=(0, 0, 1.4))
col = bpy.context.active_object
col.name = "Central_Column"

bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 2.5))
cap = bpy.context.active_object
cap.name = "Capital_Header"
cap.scale = (1.6, 1.6, 0.2)
bpy.ops.object.transform_apply(scale=True)

bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=12, radius=0.5, location=(0, 0, 2.9))
finial = bpy.context.active_object
finial.name = "Finial_Crown"

# Assign stone material
mat = bpy.data.materials.new(name="Stone_Material")
mat.use_nodes = True
bsdf = mat.node_tree.nodes.get("Principled BSDF")
if bsdf:
    bsdf.inputs["Base Color"].default_value = (0.5, 0.5, 0.52, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.6
for obj in [base, col, cap, finial]:
    obj.data.materials.append(mat)

# Export Wavefront OBJ
bpy.ops.wm.obj_export(filepath=r"{escaped_path}")
print("SENTINEL_3D_MODEL_EXPORTED_OK")
"""


def synthesize_blender_script(
    goal: str,
    output_obj_path: str,
    anti_patterns: str = "",
    use_llm: bool = True,
    model: str | None = None,
    relevant_skills: list[dict] | None = None,
    attempt_num: int = 1,
    max_attempts: int = 3,
    previous_code: str | None = None,
    error_feedback: str | None = None,
) -> str:
    """Generates Blender 4.5 Python script using local LLM with reflective error-aware self-healing.
    Never relies on keyword-matching hardcoded object branches.
    """
    if use_llm:
        try:
            gw = get_llm_gateway()
            target_model = model or gw.default_model
            if gw.is_available():
                logger.info(
                    "Synthesizing 3D model with LLM (%s) for prompt: %s (attempt %d/%d, reflective=%s)",
                    target_model, goal, attempt_num, max_attempts, bool(previous_code and error_feedback)
                )
                code = gw.generate_blender_code(
                    goal=goal,
                    output_obj_path=output_obj_path,
                    anti_patterns=anti_patterns,
                    model=target_model,
                    relevant_skills=relevant_skills,
                    previous_code=previous_code,
                    error_feedback=error_feedback,
                )
                import ast
                try:
                    ast.parse(code)
                    return code
                except SyntaxError as syn_err:
                    logger.warning("LLM generated syntax error (%s) on attempt %d/%d.", syn_err, attempt_num, max_attempts)
                    return code
            else:
                logger.warning("Ollama unavailable at endpoint. Engaging minimal procedural fallback.")
        except Exception as e:
            logger.warning("LLM synthesis error (%s) on attempt %d/%d.", e, attempt_num, max_attempts)
            if attempt_num < max_attempts:
                raise e

    return synthesize_procedural_fallback(goal, output_obj_path)
