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
        try:
            from sentinel_core.config import SentinelConfig
            from pathlib import Path
            cfg = SentinelConfig.load(Path("config.yaml"))
            _llm_gateway = LLMGateway(endpoint=cfg.llm.endpoint, default_model=cfg.llm.model)
        except Exception:
            _llm_gateway = LLMGateway()
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

    if "gatling" in g or "turret" in g or ("gun" in g and "barrel" in g):
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
    elif "barrel" in g or "keg" in g or "drum" in g:
        mesh_code = """
# 1. Main Barrel Body (cylinder with slight bevel/subdivision)
bpy.ops.mesh.primitive_cylinder_add(radius=1.0, depth=2.4, location=(0, 0, 1.2), vertices=16)
barrel = bpy.context.active_object
barrel.name = "Barrel_Body"

# Bevel modifier for wooden slats
mod = barrel.modifiers.new(name="Bevel", type='BEVEL')
mod.width = 0.06
mod.segments = 2
bpy.ops.object.modifier_apply(modifier="Bevel")

# 2. Reinforcement Metal Hoops (4 rings)
for z_pos in [0.4, 0.85, 1.55, 2.0]:
    bpy.ops.mesh.primitive_torus_add(major_radius=1.03, minor_radius=0.035, location=(0, 0, z_pos))
    hoop = bpy.context.active_object
    hoop.name = f"Metal_Hoop_{z_pos}"

# 3. Top and Bottom Lids
bpy.ops.mesh.primitive_cylinder_add(radius=0.92, depth=0.1, location=(0, 0, 2.35), vertices=16)
lid_top = bpy.context.active_object
lid_top.name = "Barrel_Lid_Top"

bpy.ops.mesh.primitive_cylinder_add(radius=0.92, depth=0.1, location=(0, 0, 0.05), vertices=16)
lid_bottom = bpy.context.active_object
lid_bottom.name = "Barrel_Lid_Bottom"

# Materials: Oak wood and forged metal
mat_wood = bpy.data.materials.new(name="Barrel_Wood")
mat_wood.use_nodes = True
bsdf_w = mat_wood.node_tree.nodes.get("Principled BSDF")
if bsdf_w:
    bsdf_w.inputs["Base Color"].default_value = (0.55, 0.35, 0.18, 1.0)
    bsdf_w.inputs["Roughness"].default_value = 0.6

mat_metal = bpy.data.materials.new(name="Barrel_Metal")
mat_metal.use_nodes = True
bsdf_m = mat_metal.node_tree.nodes.get("Principled BSDF")
if bsdf_m:
    bsdf_m.inputs["Base Color"].default_value = (0.22, 0.22, 0.25, 1.0)
    bsdf_m.inputs["Metallic"].default_value = 0.9
    bsdf_m.inputs["Roughness"].default_value = 0.3

barrel.data.materials.append(mat_wood)
lid_top.data.materials.append(mat_wood)
lid_bottom.data.materials.append(mat_wood)
for obj in bpy.context.scene.objects:
    if "Metal_Hoop" in obj.name:
        obj.data.materials.append(mat_metal)
"""
    elif "crate" in g or "chest" in g or "box" in g:
        mesh_code = """
bpy.ops.mesh.primitive_cube_add(size=1.8, location=(0, 0, 0.9))
crate = bpy.context.active_object
crate.name = "Crate_Body"

# Corner brackets
for x in [-0.9, 0.9]:
    for y in [-0.9, 0.9]:
        bpy.ops.mesh.primitive_cube_add(size=0.2, location=(x, y, 0.9))
        bracket = bpy.context.active_object
        bracket.scale = (1.0, 1.0, 9.0)
        bpy.ops.object.transform_apply(scale=True)
"""
    elif "tree" in g or "pine" in g or "plant" in g:
        mesh_code = """
# Trunk
bpy.ops.mesh.primitive_cylinder_add(radius=0.25, depth=1.6, location=(0, 0, 0.8))
trunk = bpy.context.active_object
trunk.name = "Tree_Trunk"

# Foliage Cones
for i, z in enumerate([1.6, 2.4, 3.1]):
    r = 1.3 - (i * 0.3)
    bpy.ops.mesh.primitive_cone_add(radius1=r, depth=1.4, location=(0, 0, z))
    cone = bpy.context.active_object
    cone.name = f"Foliage_Layer_{i+1}"
"""
    elif "chair" in g or "stool" in g:
        mesh_code = """
# Seat
bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 1.0))
seat = bpy.context.active_object
seat.scale = (1.0, 1.0, 0.1)
bpy.ops.object.transform_apply(scale=True)

# 4 Legs
for x in [-0.4, 0.4]:
    for y in [-0.4, 0.4]:
        bpy.ops.mesh.primitive_cylinder_add(radius=0.04, depth=1.0, location=(x, y, 0.5))

# Backrest
bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, -0.45, 1.6))
back = bpy.context.active_object
back.scale = (0.9, 0.08, 0.6)
bpy.ops.object.transform_apply(scale=True)
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
    elif any(k in g for k in ["car", "vehicle", "automobile", "truck", "van", "jeep", "sedan", "coupe"]):
        mesh_code = """
# 1. Car Chassis
bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 0.6))
body = bpy.context.active_object
body.name = "Car_Chassis"
body.scale = (1.8, 3.6, 0.6)
bpy.ops.object.transform_apply(scale=True)

# 2. Car Cabin / Roof
bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, -0.2, 1.25))
cabin = bpy.context.active_object
cabin.name = "Car_Cabin"
cabin.scale = (1.5, 1.8, 0.7)
bpy.ops.object.transform_apply(scale=True)

# 3. Bumpers
bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 1.85, 0.4))
fbump = bpy.context.active_object
fbump.name = "Bumper_Front"
fbump.scale = (1.9, 0.25, 0.25)
bpy.ops.object.transform_apply(scale=True)

bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, -1.85, 0.4))
rbump = bpy.context.active_object
rbump.name = "Bumper_Rear"
rbump.scale = (1.9, 0.25, 0.25)
bpy.ops.object.transform_apply(scale=True)

# 4. 4 Wheels & Rims
for x, y in [(-1.0, 1.1), (1.0, 1.1), (-1.0, -1.1), (1.0, -1.1)]:
    bpy.ops.mesh.primitive_cylinder_add(radius=0.45, depth=0.35, location=(x, y, 0.45), rotation=(0, math.radians(90), 0))
    wheel = bpy.context.active_object
    wheel.name = f"Wheel_{'L' if x < 0 else 'R'}_{'F' if y > 0 else 'R'}"

    bpy.ops.mesh.primitive_cylinder_add(radius=0.25, depth=0.38, location=(x, y, 0.45), rotation=(0, math.radians(90), 0))
    rim = bpy.context.active_object
    rim.name = f"Rim_{'L' if x < 0 else 'R'}_{'F' if y > 0 else 'R'}"

# 5. Headlights
for x in [-0.6, 0.6]:
    bpy.ops.mesh.primitive_cylinder_add(radius=0.15, depth=0.1, location=(x, 1.82, 0.7), rotation=(math.radians(90), 0, 0))
    hl = bpy.context.active_object
    hl.name = f"Headlight_{'L' if x < 0 else 'R'}"

# 6. Taillights
for x in [-0.6, 0.6]:
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(x, -1.82, 0.7))
    tl = bpy.context.active_object
    tl.name = f"Taillight_{'L' if x < 0 else 'R'}"
    tl.scale = (0.3, 0.08, 0.15)
    bpy.ops.object.transform_apply(scale=True)

# 7. Materials
def make_mat(name, color, metal=0.0, rough=0.5, emit=0.0):
    m = bpy.data.materials.new(name=name)
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    if b:
        b.inputs["Base Color"].default_value = color
        b.inputs["Metallic"].default_value = metal
        b.inputs["Roughness"].default_value = rough
        if emit > 0:
            b.inputs["Emission Strength"].default_value = emit
            b.inputs["Emission Color"].default_value = color
    return m

mat_paint = make_mat("Car_Paint", (0.85, 0.12, 0.12, 1.0), metal=0.7, rough=0.25)
mat_glass = make_mat("Car_Glass", (0.1, 0.15, 0.25, 1.0), metal=0.1, rough=0.1)
mat_tire = make_mat("Car_Tire", (0.08, 0.08, 0.08, 1.0), metal=0.0, rough=0.85)
mat_rim = make_mat("Car_Rim", (0.75, 0.75, 0.78, 1.0), metal=0.9, rough=0.2)
mat_bumper = make_mat("Car_Trim", (0.2, 0.2, 0.22, 1.0), metal=0.2, rough=0.5)
mat_hl = make_mat("Car_Headlight", (1.0, 0.95, 0.8, 1.0), emit=3.0)
mat_tl = make_mat("Car_Taillight", (0.9, 0.05, 0.05, 1.0), emit=2.5)

body.data.materials.append(mat_paint)
cabin.data.materials.append(mat_glass)
fbump.data.materials.append(mat_bumper)
rbump.data.materials.append(mat_bumper)

for obj in bpy.context.scene.objects:
    if obj.name.startswith("Wheel_"):
        obj.data.materials.append(mat_tire)
    elif obj.name.startswith("Rim_"):
        obj.data.materials.append(mat_rim)
    elif obj.name.startswith("Headlight_"):
        obj.data.materials.append(mat_hl)
    elif obj.name.startswith("Taillight_"):
        obj.data.materials.append(mat_tl)
"""
    elif any(k in g for k in ["table", "desk"]):
        mesh_code = """
bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 1.4))
top = bpy.context.active_object
top.name = "Tabletop"
top.scale = (2.4, 1.4, 0.08)
bpy.ops.object.transform_apply(scale=True)

for x in [-1.0, 1.0]:
    for y in [-0.5, 0.5]:
        bpy.ops.mesh.primitive_cylinder_add(radius=0.06, depth=1.4, location=(x, y, 0.7))
        leg = bpy.context.active_object
        leg.name = f"Leg_{x}_{y}"
"""
    elif any(k in g for k in ["plane", "airplane", "aircraft", "jet"]):
        mesh_code = """
bpy.ops.mesh.primitive_cylinder_add(radius=0.6, depth=4.0, location=(0, 0, 1.0), rotation=(math.radians(90), 0, 0))
fuselage = bpy.context.active_object
fuselage.name = "Fuselage"

bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0.3, 1.0))
wings = bpy.context.active_object
wings.name = "Main_Wings"
wings.scale = (5.2, 0.8, 0.06)
bpy.ops.object.transform_apply(scale=True)

bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, -1.8, 1.4))
fin = bpy.context.active_object
fin.name = "Vertical_Stabilizer"
fin.scale = (0.06, 0.6, 0.8)
bpy.ops.object.transform_apply(scale=True)
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
    model: str | None = None,
    relevant_skills: list[dict] | None = None,
    attempt_num: int = 1,
    max_attempts: int = 3,
) -> str:
    """Generates Blender 4.5 Python script.
    Primary pathway: local LLM generating creative, customized 3D meshes.
    Fallback pathway: procedural geometric mesh if LLM service is offline or on final attempt exhaustion.
    """
    if use_llm:
        try:
            gw = get_llm_gateway()
            target_model = model or gw.default_model
            if gw.is_available():
                logger.info("Synthesizing 3D model with LLM (%s) for prompt: %s (attempt %d/%d)", target_model, goal, attempt_num, max_attempts)
                code = gw.generate_blender_code(
                    goal=goal,
                    output_obj_path=output_obj_path,
                    anti_patterns=anti_patterns,
                    model=target_model,
                    relevant_skills=relevant_skills,
                )
                import ast
                try:
                    ast.parse(code)
                    return code
                except SyntaxError as syn_err:
                    logger.warning("LLM generated invalid Python syntax (%s) on attempt %d/%d.", syn_err, attempt_num, max_attempts)
                    if attempt_num < max_attempts:
                        # Allow adaptive self-healing loop in pilot_controller to record syntax defect and retry
                        return code
            else:
                logger.warning("Ollama unavailable at endpoint. Engaging procedural synthesis.")
        except Exception as e:
            logger.warning("LLM synthesis error (%s) on attempt %d/%d.", e, attempt_num, max_attempts)
            if attempt_num < max_attempts:
                raise e

    return synthesize_procedural_fallback(goal, output_obj_path)
