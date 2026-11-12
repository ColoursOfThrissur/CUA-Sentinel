---
name: skill_low_poly_barrel
description: Auto-synthesized skill for: Create a 3D low-poly barrel in Blender
domain: 3d
version: 2
verified_at: 1794460646.8320453
effect_class: READ_ONLY
---
# skill_low_poly_barrel (v2)
Auto-synthesized skill for: Create a 3D low-poly barrel in Blender

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

# Export Wavefront OBJ
bpy.ops.wm.obj_export(filepath=r"G:/Sentinel_Workspace/task_1794460585.obj")
print("SENTINEL_3D_MODEL_EXPORTED_OK")
```
