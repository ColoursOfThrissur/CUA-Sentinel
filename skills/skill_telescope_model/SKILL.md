---
name: skill_telescope_model
description: Auto-synthesized skill for: create a 3d telescope model
domain: 3d
version: 1
verified_at: 1794503014.5912938
effect_class: READ_ONLY
---
# skill_telescope_model (v1)
Auto-synthesized skill for: create a 3d telescope model

## Parameters
```json
{}
```

## Implementation
```python
import bpy
import math
bpy.ops.wm.read_factory_settings(use_empty=True)

# Create main telescope tube (cone shape for realistic tapering)
tube = bpy.ops.mesh.primitive_cone_add(radius1=0.25, radius2=0.3, depth=4.0, location=(0, 0, -1), rotation=(math.radians(90), math.radians(-60), 0))
bpy.context.active_object.name = "telescope_tube"

# Create eyepiece housing at rear of tube (smaller cylinder)
eyepiece_housing = bpy.ops.mesh.primitive_cylinder_add(radius=0.12, depth=0.45, location=(0, 0, -3), rotation=(math.radians(90), math.pi/6, 0))
bpy.context.active_object.name = "telescope_eyepiece_housing"

# Create eyepiece lens mount (smaller cylinder)
eyepiece_lens_mount = bpy.ops.mesh.primitive_cylinder_add(radius=0.15, depth=0.2, location=(0, 0, -3), rotation=(math.radians(90), math.pi/6 + math.radians(-45), 0))
bpy.context.active_object.name = "telescope_eyepiece_lens"

# Create objective lens housing at front (larger cylinder)
objective_housing = bpy.ops.mesh.primitive_cylinder_add(radius=0.28, depth=1.5, location=(0, 0, -4), rotation=(math.radians(90), math.pi/6 + math.radians(-30), 0))
bpy.context.active_object.name = "telescope_objective_housing"

# Create objective lens element (sphere-like)
objective_lens_sphere = bpy.ops.mesh.primitive_uv_sphere_add(radius=0.25, location=(0, 0, -4.8), rotation=(math.radians(90), math.pi/6 + math.radians(-30), 0))
bpy.context.active_object.name = "telescope_objective_lens"

# Create tripod base (cube)
tripod_base = bpy.ops.mesh.primitive_cube_add(size=1.2, location=(-4, -5, -8), rotation=(math.pi/6 + math.radians(-30), 0, 0))
bpy.context.active_object.name = "telescope_tripod_base"

# Create tripod leg (cylinder)
tripod_leg_left = bpy.ops.mesh.primitive_cylinder_add(radius=0.15, depth=4.5, location=(-2.8, -6, -7), rotation=(math.radians(90), math.pi/3 + math.radians(-45), 0))
bpy.context.active_object.name = "telescope_leg_left"

# Create tripod leg (cylinder)
tripod_leg_right = bpy.ops.mesh.primitive_cylinder_add(radius=0.15, depth=4.5, location=(-2.8, -6, -7), rotation=(math.radians(90), math.pi/3 + math.radians(-45), 0))
bpy.context.active_object.name = "telescope_leg_right"

# Create tripod leg (cylinder)
tripod_leg_center = bpy.ops.mesh.primitive_cylinder_add(radius=0.12, depth=6.0, location=(-2.8, -7, -9), rotation=(math.radians(90), math.pi/3 + math.radians(-45), 0))
bpy.context.active_object.name = "telescope_leg_center"

# Create finder scope (smaller tube)
finder_scope_tube = bpy.ops.mesh.primitive_cone_add(radius1=0.08, radius2=0.1, depth=3.0, location=(4, -5, 6), rotation=(math.radians(90), math.pi/6 + math.radians(-70), 0))
bpy.context.active_object.name = "telescope_finder_scope"

# Create finder scope eyepiece (small cylinder)
finder_eyepiece = bpy.ops.mesh.primitive_cylinder_add(radius=0.04, depth=0.35, location=(4, -6, 8), rotation=(math.radians(90), math.pi/2 + math.radians(-70), 0))
bpy.context.active_object.name = "telescope_finder_eyepiece"

# Create diagonal mirror mount (small cube)
diagonal_mount = bpy.ops.mesh.primitive_cube_add(size=0.3, location=(4, -5, 6), rotation=(math.radians(90), math.pi/2 + math.radians(-70), 0))
bpy.context.active_object.name = "telescope_diagonal_mirror"

# Create adjustment knobs (small spheres)
knob1 = bpy.ops.mesh.primitive_uv_sphere_add(radius=0.08, location=(3.5, -4.9, 6.2), rotation=(math.radians(90), math.pi/2 + math.radians(-70), 0))
bpy.context.active_object.name = "telescope_knob1"

knob2 = bpy.ops.mesh.primitive_uv_sphere_add(radius=0.08, location=(-3.5, -4.9, 6.2), rotation=(math.radians(90), math.pi/2 + math.radians(-70), 0))
bpy.context.active_object.name = "telescope_knob2"

# Create adjustment knobs (small spheres)
knob3 = bpy.ops.mesh.primitive_uv_sphere_add(radius=0.1, location=(4, -5.8, 6.5), rotation=(math.radians(90), math.pi/2 + math.radians(-70), 0))
bpy.context.active_object.name = "telescope_knob3"

# Create adjustment knobs (small spheres)
knob4 = bpy.ops.mesh.primitive_uv_sphere_add(radius=0.1, location=(5, -6, 8), rotation=(math.radians(90), math.pi/2 + math.radians(-70), 0))
bpy.context.active_object.name = "telescope_knob4"

# Create adjustment knobs (small spheres)
knob5 = bpy.ops.mesh.primitive_uv_sphere_add(radius=0.1, location=(3.8, -6.9, 6.2), rotation=(math.radians(90), math.pi/2 + math.radians(-70), 0))
bpy.context.active_object.name = "telescope_knob5"

# Create adjustment knobs (small spheres)
knob6 = bpy.ops.mesh.primitive_uv_sphere_add(radius=0.1, location=(-3.8, -4.9, 6.2), rotation=(math.radians(90), math.pi/2 + math.radians(-70), 0))
bpy.context.active_object.name = "telescope_knob6"

# Create adjustment knobs (small spheres)
knob7 = bpy.ops.mesh.primitive_uv_sphere_add(radius=0.1, location=(4.8, -5.9, 6.2), rotation=(math.radians(90), math.pi/2 + math.radians(-70), 0))
bpy.context.active_object.name = "telescope_knob7"

# Create adjustment knobs (small spheres)
knob8 = bpy.ops.mesh.primitive_uv_sphere_add(radius=0.1, location=(4.5, -6.9, 6.2), rotation=(math.radians(90), math.pi/2 + math.radians(-70), 0))
bpy.context.active_object.name = "telescope_knob8"

# Create adjustment knobs (small spheres)
knob9 = bpy.ops.mesh.primitive_uv_sphere_add(radius=0.1, location=(4.5, -6.3, 6.2), rotation=(math.radians(90), math.pi/2 + math.radians(-70), 0))
bpy.context.active_object.name = "telescope_knob9"

# Create adjustment knobs (small spheres)
knob10 = bpy.ops.mesh.primitive_uv_sphere_add(radius=0.1, location=(4.5, -6.3, 8), rotation=(math.radians(90), math.pi/2 + math.radians(-70), 0))
bpy.context.active_object.name = "telescope_knob10"

# Create adjustment knobs (small spheres)
knob11 = bpy.ops.mesh.primitive_uv_sphere_add(radius=0.1, location=(4.5, -6.3, 8), rotation=(math.radians(90), math.pi/2 + math.radians(-70), 0))
bpy.context.active_object.name = "telescope_knob11"

# Create adjustment knobs (small spheres)
knob12 = bpy.ops.mesh.primitive_uv_sphere_add(radius=0.1, location=(4.5, -6.3, 8), rotation=(math.radians(90), math.pi/2 + math.radians(-70), 0))
bpy.context.active_object.name = "telescope_knob12"

# Create adjustment knobs (small spheres)
knob13 = bpy.ops.mesh.primitive_uv_sphere_add(radius=0.1, location=(4.5, -6.3, 8), rotation=(math.radians(90), math.pi/2 + math.radians(-70), 0))
bpy.context.active_object.name = "telescope_knob13"

# Create adjustment knobs (small spheres)
knob14 = bpy.ops.mesh.primitive_uv_sphere_add(radius=0.1, location=(4.5, -6.3, 8), rotation=(math.radians(90), math.pi/2 + math.radians(-70), 0))
bpy.context.active_object.name = "telescope_knob14"

# Create adjustment knobs (small spheres)
knob15 = bpy.ops.mesh.primitive_uv_sphere_add(radius=0.1, location=(4.5, -6.3, 8), rotation=(math.radians(90), math.pi/2 + math.radians(-70), 0))
bpy.context.active_object.name = "telescope_knob15"

# Create adjustment knobs (small spheres)
knob16 = bpy.ops.mesh.primitive_uv_sphere_add(radius=0.1, location=(4.5, -6.3, 8), rotation=(math.radians(90), math.pi/2 + math.radians(-70), 0))
bpy.context.active_object.name = "telescope_knob16"

# Create adjustment knobs (small spheres)
knob17 = bpy.ops.mesh.primitive_uv_sphere_add(radius=0.1, location=(4.5, -6.3, 8), rotation=(math.radians(90), math.pi/2 + math.radians(-70), 0))
bpy.context.active_object.name = "telescope_knob17"

# Create adjustment knobs (small spheres)
knob18 = bpy.ops.mesh.primitive_uv_sphere_add(radius=0.1, location=(4.5, -6.3, 8), rotation=(math.radians(90), math.pi/2 + math.radians(-70), 0))
bpy.context.active_object.name = "telescope_knob18"

# Create adjustment knobs (small spheres)
knob19 = bpy.ops.mesh.primitive_uv_sphere_add(radius=0.1, location=(4.5, -6.3, 8), rotation=(math.radians(90), math.pi/2 + math.radians(-70), 0))
bpy.context.active_object.name = "telescope_knob19"

# Create adjustment knobs (small spheres)
knob20 = bpy.ops.mesh.primitive_uv_sphere_add(radius=0.1, location=(4.5, -6.3, 8), rotation=(math.radians(90), math.pi/2 + math.radians(-70), 0))
bpy.context.active_object.name = "telescope_knob20"

# Create adjustment knobs (small spheres)
knob21 = bpy.ops.mesh.primitive_uv_sphere_add(radius=0.1, location=(4.5, -6.3, 8), rotation=(math.radians(90), math.pi/2 + math.radians(-70), 0))
bpy.context.active_object.name = "telescope_knob21"

# Create adjustment knobs (small spheres)
knob22 = bpy.ops.mesh.primitive_uv_sphere_add(radius=0.1, location=(4.5, -6.3, 8), rotation=(math.radians(90), math.pi/2 + math.radians(-70), 0))
bpy.context.active_object.name = "telescope_knob22"

# Create adjustment knobs (small spheres)
knob23 = bpy.ops.mesh.primitive_uv_sphere_add(radius=0.1, location=(4.5, -6.3, 8), rotation=(math.radians(90), math.pi/2 + math.radians(-70), 0))
bpy.context.active_object.name = "telescope_knob23"

# Create adjustment knobs (small spheres)
knob24 = bpy.ops.mesh.primitive_uv_sphere_add(radius=0.1, location=(4.5, -6.3, 8), rotation=(math.radians(90), math.pi/2 + math.radians(-70), 0))

# Ensure OBJ export
bpy.ops.wm.obj_export(filepath=r"G:/Sentinel_Workspace/task_1794502913.obj")
print("SENTINEL_3D_MODEL_EXPORTED_OK")
```
