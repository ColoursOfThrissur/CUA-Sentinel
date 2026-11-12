---
name: skill_wooden_crate_corner_brackets
description: Auto-synthesized skill for: Create a 3D wooden crate with corner brackets in Blender
domain: 3d
version: 1
verified_at: 1794459915.4419513
effect_class: READ_ONLY
---
# skill_wooden_crate_corner_brackets (v1)
Auto-synthesized skill for: Create a 3D wooden crate with corner brackets in Blender

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

bpy.ops.mesh.primitive_cube_add(size=1.8, location=(0, 0, 0.9))
crate = bpy.context.active_object
crate.name = "Crate_Body"

# Corner brackets
for x in [-0.9, 0.9]:
    for y in [-0.9, 0.9]:
        bpy.ops.mesh.primitive_cube_add(size=0.2, location=(x, y, 0.9))
        bracket = bpy.context.active_object
        bracket.scale = (1.0, 1.0, 9.0)
        bpy.ops.object.transform_apply(scale=True)

# Export Wavefront OBJ
bpy.ops.wm.obj_export(filepath=r"G:/Sentinel_Workspace/task_1794459838.obj")
print("SENTINEL_3D_MODEL_EXPORTED_OK")
```
