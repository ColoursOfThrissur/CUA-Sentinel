import bpy
import math

# Clear existing data
bpy.ops.wm.read_factory_settings(use_empty=True)

# Create the gimbal ring cradle
bpy.ops.mesh.primitive_cylinder_add(radius=1, depth=0.2, location=(0, 0, 0), rotation=(math.radians(90), 0, 0))
gimbal_ring = bpy.context.active_object

# Assign material to gimbal ring
mat_gimbal = bpy.data.materials.new(name='GimbalRingMat')
mat_gimbal.use_nodes = True
bsdf_gimbal = mat_gimbal.node_tree.nodes.get('Principled BSDF')
bsdf_gimbal.inputs['Base Color'].default_value = (0.5, 0.5, 0.5, 1.0)
gimbal_ring.data.materials.append(mat_gimbal)

# Create the conical bell nozzle
bpy.ops.mesh.primitive_cone_add(radius1=0.2, radius2=0.1, depth=1, location=(0, 0, -0.5), rotation=(math.radians(90), 0, 0))
nozzle = bpy.context.active_object

# Assign material to nozzle
mat_nozzle = bpy.data.materials.new(name='NozzleMat')
mat_nozzle.use_nodes = True
bsdf_nozzle = mat_nozzle.node_tree.nodes.get('Principled BSDF')
bsdf_nozzle.inputs['Base Color'].default_value = (0.8, 0.2, 0.1, 1.0)
nozzle.data.materials.append(mat_nozzle)

# Create the fuel manifolds
bpy.ops.mesh.primitive_cylinder_add(radius=0.1, depth=0.5, location=(-1, 0, -0.7), rotation=(math.radians(90), 0, 0))
fuel_manifold_left = bpy.context.active_object

# Assign material to fuel manifold left
mat_fuel_left = bpy.data.materials.new(name='FuelManifoldLeftMat')
mat_fuel_left.use_nodes = True
bsdf_fuel_left = mat_fuel_left.node_tree.nodes.get('Principled BSDF')
bsdf_fuel_left.inputs['Base Color'].default_value = (0.1, 0.2, 0.8, 1.0)
fuel_manifold_left.data.materials.append(mat_fuel_left)

bpy.ops.mesh.primitive_cylinder_add(radius=0.1, depth=0.5, location=(1, 0, -0.7), rotation=(math.radians(90), 0, 0))
fuel_manifold_right = bpy.context.active_object

# Assign material to fuel manifold right
mat_fuel_right = bpy.data.materials.new(name='FuelManifoldRightMat')
mat_fuel_right.use_nodes = True
bsdf_fuel_right = mat_fuel_right.node_tree.nodes.get('Principled BSDF')
bsdf_fuel_right.inputs['Base Color'].default_value = (0.1, 0.2, 0.8, 1.0)
fuel_manifold_right.data.materials.append(mat_fuel_right)

# Export the scene to OBJ
bpy.ops.wm.obj_export(filepath=r"G:/Sentinel_Workspace/task_1794672131.obj")
print("SENTINEL_3D_MODEL_EXPORTED_OK")