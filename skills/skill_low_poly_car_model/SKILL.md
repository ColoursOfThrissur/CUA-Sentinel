---
name: skill_low_poly_car_model
description: Auto-synthesized skill for: create a low poly car 3d model
domain: 3d
version: 1
verified_at: 1794463617.6022332
effect_class: READ_ONLY
---
# skill_low_poly_car_model (v1)
Auto-synthesized skill for: create a low poly car 3d model

## Parameters
```json
{}
```

## Implementation
```python
import bpy
import math
from math import radians

# Reset scene to empty
bpy.ops.wm.read_factory_settings(use_empty=True)

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

# Export Wavefront OBJ
bpy.ops.wm.obj_export(filepath=r"G:/Sentinel_Workspace/task_1794463401.obj")
print("SENTINEL_3D_MODEL_EXPORTED_OK")

```
