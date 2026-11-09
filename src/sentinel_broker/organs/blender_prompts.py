"""Sentinel 3D Model Synthesizer for Blender 4.5.
Synthesizes procedural 3D meshes (swords, mugs, spaceships, trees, furniture, etc.) in Blender Python (bpy).
"""
from __future__ import annotations


def synthesize_blender_script(goal: str, output_obj_path: str) -> str:
    """Generates real Blender 4.5 Python code to create the requested 3D model."""
    g = goal.lower()
    escaped_path = output_obj_path.replace("\\", "\\\\")

    header = f"""import bpy
from math import radians

# Reset scene to empty
bpy.ops.wm.read_factory_settings(use_empty=True)
"""

    footer = f"""
# Export Wavefront OBJ
bpy.ops.wm.obj_export(filepath=r"{escaped_path}")
print("SENTINEL_3D_MODEL_EXPORTED_OK")
"""

    if "sword" in g or "blade" in g or "dagger" in g:
        mesh_code = """
# 1. Blade
bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 1.5))
blade = bpy.context.active_object
blade.name = "Blade"
blade.scale = (0.05, 0.25, 2.0)
bpy.ops.object.transform_apply(scale=True)

# 2. Crossguard
bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 0.45))
guard = bpy.context.active_object
guard.name = "Crossguard"
guard.scale = (0.12, 1.0, 0.1)
bpy.ops.object.transform_apply(scale=True)

# 3. Grip / Handle
bpy.ops.mesh.primitive_cylinder_add(radius=0.08, depth=0.8, location=(0, 0, 0.0))
grip = bpy.context.active_object
grip.name = "Handle"

# 4. Pommel
bpy.ops.mesh.primitive_uv_sphere_add(radius=0.15, location=(0, 0, -0.45))
pommel = bpy.context.active_object
pommel.name = "Pommel"
"""
    elif "mug" in g or "cup" in g:
        mesh_code = """
# 1. Mug Body
bpy.ops.mesh.primitive_cylinder_add(radius=1.0, depth=2.0, location=(0, 0, 1.0))
mug = bpy.context.active_object
mug.name = "Mug"

# Hollow out with Solidify
sol = mug.modifiers.new(name="Solidify", type='SOLIDIFY')
sol.thickness = 0.15

# 2. Handle (Torus segment)
bpy.ops.mesh.primitive_torus_add(major_radius=0.7, minor_radius=0.15, location=(1.1, 0, 1.0), rotation=(radians(90), 0, 0))
handle = bpy.context.active_object
handle.name = "Handle"
handle.scale = (0.7, 0.7, 1.0)
bpy.ops.object.transform_apply(scale=True)
"""
    elif "spaceship" in g or "space" in g or "ship" in g or "drone" in g:
        mesh_code = """
# 1. Fuselage
bpy.ops.mesh.primitive_cone_add(radius1=0.8, depth=3.0, location=(0, 0, 1.5), rotation=(radians(90), 0, 0))
fuselage = bpy.context.active_object
fuselage.name = "Fuselage"
fuselage.scale = (1.0, 1.8, 0.6)
bpy.ops.object.transform_apply(scale=True)

# 2. Left Wing
bpy.ops.mesh.primitive_cube_add(size=1.0, location=(1.5, -0.5, 1.3))
l_wing = bpy.context.active_object
l_wing.name = "LeftWing"
l_wing.scale = (1.8, 0.8, 0.05)
bpy.ops.object.transform_apply(scale=True)

# 3. Right Wing
bpy.ops.mesh.primitive_cube_add(size=1.0, location=(-1.5, -0.5, 1.3))
r_wing = bpy.context.active_object
r_wing.name = "RightWing"
r_wing.scale = (1.8, 0.8, 0.05)
bpy.ops.object.transform_apply(scale=True)

# 4. Engine Thrusters
bpy.ops.mesh.primitive_cylinder_add(radius=0.3, depth=1.0, location=(0.6, -1.8, 1.3), rotation=(radians(90), 0, 0))
bpy.ops.mesh.primitive_cylinder_add(radius=0.3, depth=1.0, location=(-0.6, -1.8, 1.3), rotation=(radians(90), 0, 0))
"""
    elif "tree" in g or "plant" in g:
        mesh_code = """
# 1. Trunk
bpy.ops.mesh.primitive_cylinder_add(radius=0.3, depth=2.5, location=(0, 0, 1.25))
trunk = bpy.context.active_object
trunk.name = "Trunk"

# 2. Foliage layers (Cones)
bpy.ops.mesh.primitive_cone_add(radius1=1.8, depth=2.0, location=(0, 0, 2.5))
bpy.ops.mesh.primitive_cone_add(radius1=1.4, depth=1.8, location=(0, 0, 3.5))
bpy.ops.mesh.primitive_cone_add(radius1=1.0, depth=1.5, location=(0, 0, 4.3))
"""
    elif "chair" in g or "stool" in g or "furniture" in g:
        mesh_code = """
# 1. Seat
bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 1.0))
seat = bpy.context.active_object
seat.name = "Seat"
seat.scale = (1.0, 1.0, 0.1)
bpy.ops.object.transform_apply(scale=True)

# 2. Backrest
bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, -0.45, 1.6))
back = bpy.context.active_object
back.name = "Backrest"
back.scale = (1.0, 0.1, 1.2)
bpy.ops.object.transform_apply(scale=True)

# 3. Four Legs
for lx, ly in [(-0.4, -0.4), (0.4, -0.4), (-0.4, 0.4), (0.4, 0.4)]:
    bpy.ops.mesh.primitive_cylinder_add(radius=0.06, depth=1.0, location=(lx, ly, 0.5))
"""
    elif "monkey" in g or "suzanne" in g:
        mesh_code = """
# Suzanne Monkey Head
bpy.ops.mesh.primitive_monkey_add(size=2.0, location=(0, 0, 1.0))
obj = bpy.context.active_object
mod = obj.modifiers.new(name="Subsurf", type='SUBSURF')
mod.levels = 1
"""
    else:
        # Generic procedural 3D model: Beveled Geometric Sculpture with multiple primitives
        mesh_code = f"""
# Procedural 3D model for: {goal}
bpy.ops.mesh.primitive_uv_sphere_add(radius=1.2, location=(0, 0, 1.5))
sphere = bpy.context.active_object
bpy.ops.mesh.primitive_torus_add(major_radius=2.0, minor_radius=0.2, location=(0, 0, 1.5))
torus = bpy.context.active_object
torus.rotation_euler = (radians(45), radians(30), 0)
bpy.ops.mesh.primitive_cylinder_add(radius=1.5, depth=0.3, location=(0, 0, 0.15))
"""

    return header + mesh_code + footer
