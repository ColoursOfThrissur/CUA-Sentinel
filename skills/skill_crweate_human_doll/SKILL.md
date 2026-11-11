---
name: skill_crweate_human_doll
description: Auto-synthesized skill for: crweate a human doll 3d
domain: 3d
version: 1
verified_at: 1794376209.415899
effect_class: READ_ONLY
---
# skill_crweate_human_doll (v1)
Auto-synthesized skill for: crweate a human doll 3d

## Parameters
```json
{}
```

## Implementation
```python
import bpy
import math
bpy.ops.wm.read_factory_settings(use_empty=True)

# Clear any existing objects
for obj in bpy.data.objects:
    bpy.data.objects.remove(obj, do_unlink=True)

# Create head (sphere)
head = bpy.ops.mesh.primitive_uv_sphere_add(radius=0.15, location=(0, 0, 0.6), segments=32, ring_count=16)
bpy.context.object.name = "doll_head"
bpy.context.object.rotation_euler = (math.radians(90), 0, 0)

# Create neck (small cylinder)
neck = bpy.ops.mesh.primitive_cylinder_add(radius=0.08, depth=0.1, location=(0, 0, 0.45))
bpy.context.object.name = "doll_neck"

# Create torso (cylinder)
torso = bpy.ops.mesh.primitive_cylinder_add(radius=0.12, depth=0.35, location=(0, 0, 0.1))
bpy.context.object.name = "doll_torso"

# Create left arm (cylinder)
left_arm = bpy.ops.mesh.primitive_cylinder_add(radius=0.04, depth=0.25, location=(-0.18, 0, 0.3))
bpy.context.object.name = "doll_left_arm"
bpy.context.object.rotation_euler = (math.radians(45), math.radians(-30), 0)

# Create right arm (cylinder)
right_arm = bpy.ops.mesh.primitive_cylinder_add(radius=0.04, depth=0.25, location=(0.18, 0, 0.3))
bpy.context.object.name = "doll_right_arm"
bpy.context.object.rotation_euler = (math.radians(45), math.radians(30), 0)

# Create left leg (cylinder)
left_leg = bpy.ops.mesh.primitive_cylinder_add(radius=0.06, depth=0.28, location=(-0.07, -0.15, 0))
bpy.context.object.name = "doll_left_leg"
bpy.context.object.rotation_euler = (math.radians(-10), math.radians(5), 0)

# Create right leg (cylinder)
right_leg = bpy.ops.mesh.primitive_cylinder_add(radius=0.06, depth=0.28, location=(0.07, -0.15, 0))
bpy.context.object.name = "doll_right_leg"
bpy.context.object.rotation_euler = (math.radians(-10), math.radians(-5), 0)

# Create hair (small cylinders on top of head)
hair_left = bpy.ops.mesh.primitive_cylinder_add(radius=0.03, depth=0.08, location=(-0.06, 0.02, 0.65))
bpy.context.object.name = "doll_hair_left"
bpy.context.object.rotation_euler = (math.radians(90), math.radians(-45), 0)

hair_right = bpy.ops.mesh.primitive_cylinder_add(radius=0.03, depth=0.08, location=(0.06, 0.02, 0.65))
bpy.context.object.name = "doll_hair_right"
bpy.context.object.rotation_euler = (math.radians(90), math.radians(45), 0)

hair_back = bpy.ops.mesh.primitive_cylinder_add(radius=0.03, depth=0.1, location=(0, -0.02, 0.6))
bpy.context.object.name = "doll_hair_back"
bpy.context.object.rotation_euler = (math.radians(90), math.radians(-15), 0)

# Create eyes (small spheres)
eye_left = bpy.ops.mesh.primitive_uv_sphere_add(radius=0.02, location=(-0.04, 0.03, 0.6))
bpy.context.object.name = "doll_eye_left"

eye_right = bpy.ops.mesh.primitive_uv_sphere_add(radius=0.02, location=(0.04, 0.03, 0.6))
bpy.context.object.name = "doll_eye_right"

# Create mouth (small cylinder)
mouth = bpy.ops.mesh.primitive_cylinder_add(radius=0.015, depth=0.01, location=(0, -0.02, 0.58))
bpy.context.object.name = "doll_mouth"

# Create ears (small cylinders on sides of head)
ear_left = bpy.ops.mesh.primitive_cylinder_add(radius=0.03, depth=0.06, location=(-0.14, -0.02, 0.58))
bpy.context.object.name = "doll_ear_left"
bpy.context.object.rotation_euler = (math.radians(90), math.radians(-90), 0)

ear_right = bpy.ops.mesh.primitive_cylinder_add(radius=0.03, depth=0.06, location=(0.14, -0.02, 0.58))
bpy.context.object.name = "doll_ear_right"
bpy.context.object.rotation_euler = (math.radians(90), math.radians(-90), 0)

# Apply scale to all objects
for obj in bpy.data.objects:
    obj.scale = (1, 1, 1)

# Add material for doll
doll_mat = bpy.data.materials.new(name="doll_material")
doll_mat.use_nodes = True
bsdf = doll_mat.node_tree.nodes.get("BSDF Surface")
if bsdf:
    bsdf.inputs['Base Color'].default_value = (0.8, 0.75, 0.7, 1)

# Assign material to all objects
for obj in bpy.data.objects:
    if obj.type == 'MESH':
        obj.data.materials.append(doll_mat)

bpy.ops.wm.obj_export(filepath=r"C:/Users/derik/Desktop/Derik/Projects/Sentinel/workspaces/task_1794376155.obj")
print("SENTINEL_3D_MODEL_EXPORTED_OK")
```
