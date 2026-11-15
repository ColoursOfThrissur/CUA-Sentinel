---
name: skill_bevel_gear_pinion_16
description: Auto-synthesized skill for: Synthesize a 3D bevel gear pinion with 16 tapered teeth, central shaft hole, and brass material.
domain: 3d
version: 1
verified_at: 1794672112.682884
effect_class: READ_ONLY
---
# skill_bevel_gear_pinion_16 (v1)
Auto-synthesized skill for: Synthesize a 3D bevel gear pinion with 16 tapered teeth, central shaft hole, and brass material.

## Parameters
```json
{}
```

## Implementation
```python
import bpy
import math

bpy.ops.wm.read_factory_settings(use_empty=True)

# Create central shaft hole
bpy.ops.mesh.primitive_cylinder_add(radius=0.5, depth=10, location=(0, 0, 0), rotation=(math.radians(90), 0, 0))
shaft = bpy.context.active_object

mat = bpy.data.materials.new(name='BrassMat')
mat.use_nodes = True
bsdf = mat.node_tree.nodes.get('Principled BSDF')
bsdf.inputs['Base Color'].default_value = (1.0, 0.85, 0.64, 1.0)  # Brass color
bsdf.inputs['Metallic'].default_value = 0.7
bsdf.inputs['Roughness'].default_value = 0.2
shaft.data.materials.append(mat)

# Create gear pinion with 16 tapered teeth
bpy.ops.mesh.primitive_cylinder_add(radius=3, depth=5, location=(0, 0, 0))
pinion = bpy.context.active_object

mat = bpy.data.materials.new(name='BrassMat')
mat.use_nodes = True
bsdf = mat.node_tree.nodes.get('Principled BSDF')
bsdf.inputs['Base Color'].default_value = (1.0, 0.85, 0.64, 1.0)  # Brass color
bsdf.inputs['Metallic'].default_value = 0.7
bsdf.inputs['Roughness'].default_value = 0.2
pinion.data.materials.append(mat)

# Add bevel modifier to create tapered teeth
mod = pinion.modifiers.new(name='Bevel', type='BEVEL')
mod.width = 0.1
mod.segments = 3
bpy.context.view_layer.objects.active = pinion
if bpy.context.active_object and 'Bevel' in bpy.context.active_object.modifiers:
    bpy.ops.object.modifier_apply(modifier='Bevel')
# Add boolean difference modifier to cut out the central shaft hole
pinion.select_set(True)
shaft.select_set(True)
bpy.context.view_layer.objects.active = pinion

mod = pinion.modifiers.new(name='Boolean', type='BOOLEAN')
mod.operation = 'DIFFERENCE'
mod.object = shaft
if bpy.context.active_object and 'Boolean' in bpy.context.active_object.modifiers:
    bpy.ops.object.modifier_apply(modifier='Boolean')
# Export the scene to OBJ
bpy.ops.wm.obj_export(filepath=r"G:/Sentinel_Workspace/task_1794672066.obj")
print("SENTINEL_3D_MODEL_EXPORTED_OK")
```
