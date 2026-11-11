---
name: skill_task_1794337298
description: Auto-synthesized skill for: crweate a human doll 3d
version: 1
verified_at: 1794337360.3950818
effect_class: READ_ONLY
---
# skill_task_1794337298 (v1)
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

# Create human doll 3D model

# Head
head = bpy.ops.mesh.primitive_uv_sphere_add(radius=0.15, location=(0, 0, 0.8), segments=32, ring_count=16)

# Neck (cylinder connecting head to body)
neck = bpy.ops.mesh.primitive_cylinder_add(radius=0.07, depth=0.1, location=(0, 0, 0.5))

# Torso/Body
torso = bpy.ops.mesh.primitive_cylinder_add(radius=0.12, depth=0.4, location=(0, 0, -0.2), rotation=(math.radians(90), 0, 0))

# Left Arm
left_arm = bpy.ops.mesh.primitive_cylinder_add(radius=0.05, depth=0.3, location=(-0.18, 0, -0.1), rotation=(math.radians(90), math.radians(-45), 0))

# Right Arm
right_arm = bpy.ops.mesh.primitive_cylinder_add(radius=0.05, depth=0.3, location=(0.18, 0, -0.1), rotation=(math.radians(90), math.radians(45), 0))

# Left Leg
left_leg = bpy.ops.mesh.primitive_cylinder_add(radius=0.06, depth=0.35, location=(-0.07, 0, -0.7), rotation=(math.radians(90), 0, 0))

# Right Leg
right_leg = bpy.ops.mesh.primitive_cylinder_add(radius=0.06, depth=0.35, location=(0.07, 0, -0.7), rotation=(math.radians(90), 0, 0))

# Add simple facial features (eyes)
left_eye = bpy.ops.mesh.primitive_uv_sphere_add(radius=0.015, location=(-0.04, 0.03, 0.82), segments=8, ring_count=4)
right_eye = bpy.ops.mesh.primitive_uv_sphere_add(radius=0.015, location=(0.04, 0.03, 0.82), segments=8, ring_count=4)

# Nose (small cylinder)
nose = bpy.ops.mesh.primitive_cone_add(radius1=0.01, radius2=0.005, depth=0.03, location=(0, 0.01, 0.75))

# Mouth (torus for lips)
mouth = bpy.ops.mesh.primitive_torus_add(major_radius=0.02, minor_radius=0.008, location=(0, -0.04, 0.75), rotation=(math.radians(90), 0, 0))

# Add material for doll appearance
for obj in bpy.data.objects:
    if obj.type == 'MESH':
        mat = bpy.data.materials.new(name="doll_material")
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get('BSDF Surface')
        if bsdf:
            bsdf.inputs['Base Color'].default_value = (0.8, 0.7, 0.65, 1)
            bsdf.inputs['Roughness'].default_value = 0.3
            obj.data.materials.append(mat)

# Apply scale to prevent zero-size warnings
for obj in bpy.data.objects:
    obj.scale = (1, 1, 1)

# Export to OBJ
bpy.ops.wm.obj_export(filepath=r"C:/Users/derik/Desktop/Derik/Projects/Sentinel/workspaces/task_1794337298.obj")
print("SENTINEL_3D_MODEL_EXPORTED_OK")
```
