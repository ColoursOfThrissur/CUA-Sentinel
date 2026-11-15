---
name: skill_astronomical_telescope_45_degree
description: Auto-synthesized skill for: Synthesize a 3D astronomical telescope with 45-degree angled tube, front dew shield, eyepiece focus knob, and 3 angled tripod legs.
domain: 3d
version: 1
verified_at: 1794672181.9528348
effect_class: READ_ONLY
---
# skill_astronomical_telescope_45_degree (v1)
Auto-synthesized skill for: Synthesize a 3D astronomical telescope with 45-degree angled tube, front dew shield, eyepiece focus knob, and 3 angled tripod legs.

## Parameters
```json
{}
```

## Implementation
```python
import bpy
import math

bpy.ops.wm.read_factory_settings(use_empty=True)

# Create the main tube of the telescope
obj = bpy.ops.mesh.primitive_cylinder_add(radius=0.5, depth=10, location=(0, 0, 0), rotation=(math.radians(45), 0, 0))
tube = bpy.context.active_object

mat_tube = bpy.data.materials.new(name='TelescopeTubeMat')
mat_tube.use_nodes = True
bsdf = mat_tube.node_tree.nodes.get('Principled BSDF')
bsdf.inputs['Base Color'].default_value = (0.5, 0.5, 0.5, 1.0)  # Gray color
tube.data.materials.append(mat_tube)

# Create the front dew shield
obj = bpy.ops.mesh.primitive_uv_sphere_add(radius=2, location=(0, -6, 3))
dew_shield = bpy.context.active_object

mat_dew_shield = bpy.data.materials.new(name='DewShieldMat')
mat_dew_shield.use_nodes = True
bsdf = mat_dew_shield.node_tree.nodes.get('Principled BSDF')
bsdf.inputs['Base Color'].default_value = (0.1, 0.8, 0.1, 1.0)  # Green color
dew_shield.data.materials.append(mat_dew_shield)

# Create the eyepiece focus knob
obj = bpy.ops.mesh.primitive_cylinder_add(radius=0.2, depth=1, location=(0, -6, 5), rotation=(math.radians(90), 0, 0))
focus_knob = bpy.context.active_object

mat_focus_knob = bpy.data.materials.new(name='FocusKnobMat')
mat_focus_knob.use_nodes = True
bsdf = mat_focus_knob.node_tree.nodes.get('Principled BSDF')
bsdf.inputs['Base Color'].default_value = (0.8, 0.1, 0.1, 1.0)  # Red color
focus_knob.data.materials.append(mat_focus_knob)

# Create the tripod legs
for i in range(3):
    angle = math.radians(i * 120)
    x = 4 * math.cos(angle)
    y = 4 * math.sin(angle)

    obj = bpy.ops.mesh.primitive_cone_add(radius1=0.1, radius2=0.1, depth=5, location=(x, y, -2), rotation=(math.radians(90), 0, angle))
    leg = bpy.context.active_object

    mat_leg = bpy.data.materials.new(name='TripodLegMat')
    mat_leg.use_nodes = True
    bsdf = mat_leg.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = (0.5, 0.3, 0.1, 1.0)  # Brown color
    leg.data.materials.append(mat_leg)

# Export the scene to OBJ
bpy.ops.wm.obj_export(filepath=r"G:/Sentinel_Workspace/task_1794672157.obj")
print("SENTINEL_3D_MODEL_EXPORTED_OK")
```
