"""Sentinel 3D Model Synthesizer for Blender 4.5.
Dynamically synthesizes Blender Python (bpy) scripts using local LLM (qwen3.5:9b) with procedural fallback.
"""
from __future__ import annotations

import logging
from pathlib import Path

from sentinel_core.llm_gateway import LLMGateway

logger = logging.getLogger("SentinelBlenderPrompts")

# Global LLM gateway instance
_llm_gateway: LLMGateway | None = None


def get_llm_gateway() -> LLMGateway:
    global _llm_gateway
    if _llm_gateway is None:
        _llm_gateway = LLMGateway(default_model="qwen3.5:9b")
    return _llm_gateway


def synthesize_procedural_fallback(goal: str, output_obj_path: str) -> str:
    """Procedural fallback if LLM is offline."""
    g = goal.lower()
    escaped_path = output_obj_path.replace("\\", "/")

    header = f"""import bpy
import math
from math import radians

# Reset scene to empty
bpy.ops.wm.read_factory_settings(use_empty=True)
"""

    footer = f"""
# Export Wavefront OBJ
bpy.ops.wm.obj_export(filepath=r"{escaped_path}")
print("SENTINEL_3D_MODEL_EXPORTED_OK")
"""

    if "gatling" in g or "turret" in g or "gun" in g or "barrel" in g:
        mesh_code = """
# 1. Mount Base
bpy.ops.mesh.primitive_cylinder_add(radius=2.5, depth=0.4, location=(0, 0, 0.2))
base = bpy.context.active_object
base.name = "Mount_Base"

# 2. Yoke Bracket
bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 0.6))
yoke_base = bpy.context.active_object
yoke_base.name = "Yoke_Base_Block"
yoke_base.scale = (2.2, 1.2, 0.4)
bpy.ops.object.transform_apply(scale=True)

for sign, side in [(-1, "Left"), (1, "Right")]:
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(sign * 0.95, 0, 1.8))
    pillar = bpy.context.active_object
    pillar.name = f"Yoke_Pillar_{side}"
    pillar.scale = (0.3, 1.0, 2.0)
    bpy.ops.object.transform_apply(scale=True)

# 3. Main Receiver
bpy.ops.mesh.primitive_cylinder_add(radius=0.6, depth=2.0, location=(0, 0, 1.8), rotation=(math.radians(90), 0, 0))
receiver = bpy.context.active_object
receiver.name = "Main_Receiver"

# 4. Central Shaft
bpy.ops.mesh.primitive_cylinder_add(radius=0.1, depth=3.5, location=(0, 2.75, 1.8), rotation=(math.radians(90), 0, 0))
shaft = bpy.context.active_object
shaft.name = "Central_Shaft"

# 5. Barrel Array (6 barrels in circle)
array_radius = 0.35
for i in range(6):
    angle = i * (2 * math.pi / 6)
    bx = array_radius * math.cos(angle)
    bz = 1.8 + array_radius * math.sin(angle)
    bpy.ops.mesh.primitive_cylinder_add(radius=0.05, depth=3.5, location=(bx, 2.75, bz), rotation=(math.radians(90), 0, 0))

# 6. Barrel Braces (Torus halfway down)
bpy.ops.mesh.primitive_torus_add(major_radius=0.42, minor_radius=0.03, location=(0, 2.75, 1.8), rotation=(math.radians(90), 0, 0))
"""
    elif "sword" in g or "blade" in g or "dagger" in g:
        mesh_code = """
bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 1.5))
blade = bpy.context.active_object
blade.name = "Blade"
blade.scale = (0.05, 0.25, 2.0)
bpy.ops.object.transform_apply(scale=True)

bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 0.45))
guard = bpy.context.active_object
guard.name = "Crossguard"
guard.scale = (0.12, 1.0, 0.1)
bpy.ops.object.transform_apply(scale=True)

bpy.ops.mesh.primitive_cylinder_add(radius=0.08, depth=0.8, location=(0, 0, 0.0))
grip = bpy.context.active_object
grip.name = "Handle"

bpy.ops.mesh.primitive_uv_sphere_add(radius=0.15, location=(0, 0, -0.45))
pommel = bpy.context.active_object
pommel.name = "Pommel"
"""
    elif "mug" in g or "cup" in g:
        mesh_code = """
bpy.ops.mesh.primitive_cylinder_add(radius=1.0, depth=2.0, location=(0, 0, 1.0))
mug = bpy.context.active_object
mug.name = "Mug"

bpy.ops.mesh.primitive_torus_add(major_radius=0.6, minor_radius=0.12, location=(1.0, 0, 1.0), rotation=(math.radians(90), 0, 0))
handle = bpy.context.active_object
handle.name = "Handle"
"""
    elif "spaceship" in g or "fighter" in g or "shuttle" in g:
        mesh_code = """
bpy.ops.mesh.primitive_cone_add(radius1=1.2, depth=3.5, location=(0, 1.0, 0.5), rotation=(math.radians(90), 0, 0))
hull = bpy.context.active_object
hull.name = "Hull"

bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 0.5))
wings = bpy.context.active_object
wings.name = "Wings"
wings.scale = (4.0, 1.2, 0.1)
bpy.ops.object.transform_apply(scale=True)

for x_pos in [-0.8, 0.8]:
    bpy.ops.mesh.primitive_cylinder_add(radius=0.3, depth=1.5, location=(x_pos, -1.2, 0.5), rotation=(math.radians(90), 0, 0))
"""
    else:
        # Default procedural abstract entity
        mesh_code = f"""
bpy.ops.mesh.primitive_cylinder_add(radius=1.5, depth=0.3, location=(0, 0, 0.15))
bpy.ops.mesh.primitive_cube_add(size=1.2, location=(0, 0, 0.9))
bpy.ops.mesh.primitive_uv_sphere_add(radius=0.8, location=(0, 0, 2.0))
"""

    return header + mesh_code + footer


def synthesize_blender_script(
    goal: str,
    output_obj_path: str,
    anti_patterns: str = "",
    use_llm: bool = True,
    model: str = "qwen3.5:9b",
    relevant_skills: list[dict] | None = None,
) -> str:
    """Generates Blender 4.5 Python script.
    Primary pathway: local Qwen (qwen3.5:9b) generating creative, customized 3D meshes.
    Fallback pathway: procedural geometric mesh if LLM service is offline.
    """
    if use_llm:
        try:
            gw = get_llm_gateway()
            if gw.is_available():
                logger.info("Synthesizing 3D model with LLM (%s) for prompt: %s", model, goal)
                code = gw.generate_blender_code(
                    goal=goal,
                    output_obj_path=output_obj_path,
                    anti_patterns=anti_patterns,
                    model=model,
                    relevant_skills=relevant_skills,
                )
                return code
            else:
                logger.warning("Ollama unavailable at endpoint. Falling back to procedural synthesis.")
        except Exception as e:
            logger.warning("LLM synthesis error (%s). Falling back to procedural synthesis.", e)

    return synthesize_procedural_fallback(goal, output_obj_path)
