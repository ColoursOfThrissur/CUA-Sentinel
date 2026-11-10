---
name: skill_task_1794248142
description: Auto-synthesized skill for: Build a highly detailed ergonomic office swivel chair. 1. Base Hub: Start with a short vertical cylinder at the origin to act as the central base hub. 2. Star Base: Radially distribute exactly five horizontal cylinders extending outward from the center of this hub at 72-degree intervals. 3. Casters: Attach a small sphere directly underneath the extreme outer tip of each of the five horizontal cylinders to act as wheels. 4. Gas Lift: Attach a tall vertical cylinder so its bottom sits perfectly flush on the exact top center of the base hub. 5. Seat Pan: Place a wide, flattened rectangular block sitting perfectly flush on top of the gas lift cylinder. 6. Armrests: On the extreme left and right outer edges of the seat pan's top surface, attach two short vertical rectangular pillars. On top of each pillar, attach a flattened horizontal cylinder pointing forward to act as the arm pads. 7. Backrest Spine: Attach a thick rectangular pillar extending upward and slightly backward from the exact bottom-rear center edge of the seat pan. 8. Backrest Cushion: Attach a large, tall rectangular block resting flush against the upper front face of the backrest spine.
version: 1
verified_at: 1794248145.2458193
effect_class: READ_ONLY
---
# skill_task_1794248142
Auto-synthesized skill for: Build a highly detailed ergonomic office swivel chair. 1. Base Hub: Start with a short vertical cylinder at the origin to act as the central base hub. 2. Star Base: Radially distribute exactly five horizontal cylinders extending outward from the center of this hub at 72-degree intervals. 3. Casters: Attach a small sphere directly underneath the extreme outer tip of each of the five horizontal cylinders to act as wheels. 4. Gas Lift: Attach a tall vertical cylinder so its bottom sits perfectly flush on the exact top center of the base hub. 5. Seat Pan: Place a wide, flattened rectangular block sitting perfectly flush on top of the gas lift cylinder. 6. Armrests: On the extreme left and right outer edges of the seat pan's top surface, attach two short vertical rectangular pillars. On top of each pillar, attach a flattened horizontal cylinder pointing forward to act as the arm pads. 7. Backrest Spine: Attach a thick rectangular pillar extending upward and slightly backward from the exact bottom-rear center edge of the seat pan. 8. Backrest Cushion: Attach a large, tall rectangular block resting flush against the upper front face of the backrest spine.

## Parameters
```json
{}
```

## Implementation
```python
import bpy
from math import radians

# Reset scene to empty
bpy.ops.wm.read_factory_settings(use_empty=True)

# 1. Seat
bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 1.0))
seat = bpy.context.active_object
seat.name = "Seat"
seat.scale = (1.0, 1.0, 0.1)
bpy.ops.object.transform_apply(scale=True)

# 2. Backrest
bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, -0.45, 1.6))
back = bpy.context.active_object
back.name = "Backrest"
back.scale = (1.0, 0.1, 1.2)
bpy.ops.object.transform_apply(scale=True)

# 3. Four Legs
for lx, ly in [(-0.4, -0.4), (0.4, -0.4), (-0.4, 0.4), (0.4, 0.4)]:
    bpy.ops.mesh.primitive_cylinder_add(radius=0.06, depth=1.0, location=(lx, ly, 0.5))

# Export Wavefront OBJ
bpy.ops.wm.obj_export(filepath=r"C:\\Users\\derik\\Desktop\\Derik\\Projects\\Sentinel\\workspaces\\task_1794248142.obj")
print("SENTINEL_3D_MODEL_EXPORTED_OK")

```
