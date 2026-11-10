import bpy
from math import radians

# Reset scene to empty
bpy.ops.wm.read_factory_settings(use_empty=True)

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

# Export Wavefront OBJ
bpy.ops.wm.obj_export(filepath=r"C:\\Users\\derik\\Desktop\\Derik\\Projects\\Sentinel\\workspaces\\task_1794248142.obj")
print("SENTINEL_3D_MODEL_EXPORTED_OK")
