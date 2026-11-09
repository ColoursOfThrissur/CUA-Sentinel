import bpy
from math import radians

# Reset scene to empty
bpy.ops.wm.read_factory_settings(use_empty=True)

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

# Export Wavefront OBJ
bpy.ops.wm.obj_export(filepath=r"C:\\Users\\derik\\Desktop\\Derik\\Projects\\Sentinel\\workspaces\\task_1794247945.obj")
print("SENTINEL_3D_MODEL_EXPORTED_OK")
