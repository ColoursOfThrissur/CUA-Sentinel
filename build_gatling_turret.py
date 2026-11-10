import bpy
import math
from pathlib import Path

# Reset scene to empty
bpy.ops.wm.read_factory_settings(use_empty=True)

# 1. Mount Base: Wide, flat cylinder resting on the ground (Z=0 at bottom)
# Cylinder default height=2, radius=1. We scale radius=2.5, height=0.4.
bpy.ops.mesh.primitive_cylinder_add(radius=2.5, depth=0.4, location=(0, 0, 0.2))
base = bpy.context.active_object
base.name = "Mount_Base"

# 2. Yoke Bracket: Thick rectangular block flush on top center of the base (Z=0.4)
# Block dimensions: width(X)=2.2, depth(Y)=1.2, height(Z)=0.4 -> Z location = 0.4 + 0.2 = 0.6
bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 0.6))
yoke_base = bpy.context.active_object
yoke_base.name = "Yoke_Base_Block"
yoke_base.scale = (2.2, 1.2, 0.4)
bpy.ops.object.transform_apply(scale=True)

# Two tall vertical rectangular pillars on extreme left and right top edges
# Left pillar (X = -0.95), Right pillar (X = 0.95)
# Height = 2.0, starting from Z=0.8 to Z=2.8 -> Center Z = 1.8
for sign, side in [(-1, "Left"), (1, "Right")]:
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(sign * 0.95, 0, 1.8))
    pillar = bpy.context.active_object
    pillar.name = f"Yoke_Pillar_{side}"
    pillar.scale = (0.3, 1.0, 2.0)
    bpy.ops.object.transform_apply(scale=True)

# 3. Main Receiver: Large horizontal cylinder perfectly centered in the space between the pillars
# Space width between pillars = 1.6. Receiver radius = 0.6, depth(along Y axis) = 2.0. Center = (0, 0, 1.8)
bpy.ops.mesh.primitive_cylinder_add(radius=0.6, depth=2.0, location=(0, 0, 1.8), rotation=(math.radians(90), 0, 0))
receiver = bpy.context.active_object
receiver.name = "Main_Receiver"

# 4. Central Shaft: Long thin cylinder extending straight out from exact center of receiver's front face
# Front face of receiver is at Y = 1.0. Shaft radius = 0.1, length = 3.5.
# Extends from Y=1.0 to Y=4.5 -> Center Y = 2.75
bpy.ops.mesh.primitive_cylinder_add(radius=0.1, depth=3.5, location=(0, 2.75, 1.8), rotation=(math.radians(90), 0, 0))
shaft = bpy.context.active_object
shaft.name = "Central_Shaft"

# 5. Barrel Array: Exactly six long, thin cylinders in a circle around central shaft
# Array radius = 0.35 around (X=0, Z=1.8), extending from Y=1.0 to Y=4.5 (depth=3.5)
barrel_radius = 0.05
array_radius = 0.35
barrel_depth = 3.5

for i in range(6):
    angle = i * (2 * math.pi / 6)
    bx = array_radius * math.cos(angle)
    bz = 1.8 + array_radius * math.sin(angle)
    bpy.ops.mesh.primitive_cylinder_add(radius=barrel_radius, depth=barrel_depth, location=(bx, 2.75, bz), rotation=(math.radians(90), 0, 0))
    barrel = bpy.context.active_object
    barrel.name = f"Barrel_{i+1}"

# 6. Barrel Braces: Thin, hollow torus positioned exactly halfway down barrel array length
# Barrels run Y=1.0 to Y=4.5 -> Halfway Y = 1.0 + 1.75 = 2.75.
# Torus rotated so its ring lies in X-Z plane, enclosing all 6 barrels.
bpy.ops.mesh.primitive_torus_add(
    major_radius=array_radius + 0.06,
    minor_radius=0.03,
    location=(0, 2.75, 1.8),
    rotation=(math.radians(90), 0, 0)
)
brace = bpy.context.active_object
brace.name = "Barrel_Brace_Ring"

# Export to OBJ
out_path = Path("workspaces/real_gatling_turret.obj").resolve()
bpy.ops.wm.obj_export(filepath=str(out_path))
print(f"GATLING_TURRET_EXPORT_SUCCESS: {out_path} ({out_path.stat().st_size} bytes)")
