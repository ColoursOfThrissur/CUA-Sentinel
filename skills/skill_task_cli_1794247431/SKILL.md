---
name: skill_task_cli_1794247431
description: Auto-synthesized skill for: Create a 3D monkey model in Blender
version: 1
verified_at: 1794247434.8260486
effect_class: READ_ONLY
---
# skill_task_cli_1794247431
Auto-synthesized skill for: Create a 3D monkey model in Blender

## Parameters
```json
{}
```

## Implementation
```python

import bpy
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_monkey_add(size=2.0, location=(0, 0, 0))
obj = bpy.context.active_object
mod = obj.modifiers.new(name="Subsurf", type='SUBSURF')
mod.levels = 1
bpy.ops.wm.obj_export(filepath=r"C:\Users\derik\Desktop\Derik\Projects\Sentinel\workspaces\task_cli_1794247431.obj")
print("REAL_BLENDER_EXPORT_COMPLETED")

```
