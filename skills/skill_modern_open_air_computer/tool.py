import bpy
import math

bpy.ops.wm.read_factory_settings(use_empty=True)

# Base Plate
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0))
base_plate = bpy.context.active_object
base_plate.name = "Base_Plate"
base_plate.scale = (2.0, 2.0, 0.3)
bpy.ops.object.transform_apply(scale=True)

# Standoff 1
bpy.ops.mesh.primitive_cylinder_add(radius=0.1, depth=0.3, location=(-1.9, -1.9, 0.15))
standoff_1 = bpy.context.active_object
standoff_1.name = "Standoff_1"

# Standoff 2
bpy.ops.mesh.primitive_cylinder_add(radius=0.1, depth=0.3, location=(-1.9, 1.9, 0.15))
standoff_2 = bpy.context.active_object
standoff_2.name = "Standoff_2"

# Standoff 3
bpy.ops.mesh.primitive_cylinder_add(radius=0.1, depth=0.3, location=(1.9, -1.9, 0.15))
standoff_3 = bpy.context.active_object
standoff_3.name = "Standoff_3"

# Standoff 4
bpy.ops.mesh.primitive_cylinder_add(radius=0.1, depth=0.3, location=(1.9, 1.9, 0.15))
standoff_4 = bpy.context.active_object
standoff_4.name = "Standoff_4"

# Top Plate
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0.45))
top_plate = bpy.context.active_object
top_plate.name = "Top_Plate"
top_plate.scale = (2.0, 2.0, 0.1)
bpy.ops.object.transform_apply(scale=True)

# Vertical Block Left
bpy.ops.mesh.primitive_cube_add(size=1, location=(-2.1, -0.5, 0.6))
vertical_block_left = bpy.context.active_object
vertical_block_left.name = "Vertical_Block_Left"
vertical_block_left.scale = (0.3, 0.3, 1.0)
bpy.ops.object.transform_apply(scale=True)

# Square Block Right
bpy.ops.mesh.primitive_cube_add(size=1, location=(1.6, -0.5, 0.7))
square_block_right = bpy.context.active_object
square_block_right.name = "Square_Block_Right"
square_block_right.scale = (0.4, 0.4, 0.2)
bpy.ops.object.transform_apply(scale=True)

# Materials

def create_material(name, color, metallic, roughness):
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = (*color, 1.0)
    bsdf.inputs['Metallic'].default_value = metallic
    bsdf.inputs['Roughness'].default_value = roughness
    return mat

mat_base_plate = create_material("Matte Paint", (0.5, 0.5, 0.5), 0, 0.8)
base_plate.data.materials.append(mat_base_plate)

mat_standoff = create_material("Chrome", (0.8, 0.8, 0.8), 1, 0.2)
standoff_1.data.materials.append(mat_standoff)
standoff_2.data.materials.append(mat_standoff)
standoff_3.data.materials.append(mat_standoff)
standoff_4.data.materials.append(mat_standoff)

mat_top_plate = create_material("Matte Paint", (0.7, 0.7, 0.7), 0, 0.8)
top_plate.data.materials.append(mat_top_plate)

mat_vertical_block_left = create_material("Brass", (0.9, 0.5, 0.2), 0.8, 0.3)
vertical_block_left.data.materials.append(mat_vertical_block_left)

mat_square_block_right = create_material("Dark Iron", (0.3, 0.3, 0.3), 1, 0.5)
square_block_right.data.materials.append(mat_square_block_right)

# Export the scene
bpy.ops.wm.obj_export(filepath=r"G:/Sentinel_Workspace/task_1794768235.obj")
print("SENTINEL_3D_MODEL_EXPORTED_OK")