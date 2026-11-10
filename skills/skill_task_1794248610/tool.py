import bpy
from math import radians

# Reset scene to empty
bpy.ops.wm.read_factory_settings(use_empty=True)

import math

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

# Export Wavefront OBJ
bpy.ops.wm.obj_export(filepath=r"C:\\Users\\derik\\Desktop\\Derik\\Projects\\Sentinel\\workspaces\\task_1794248610.obj")
print("SENTINEL_3D_MODEL_EXPORTED_OK")
