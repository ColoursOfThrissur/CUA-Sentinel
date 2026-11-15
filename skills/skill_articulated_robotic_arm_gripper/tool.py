import bpy
import math

bpy.ops.wm.read_factory_settings(use_empty=True)

# Create the base hub for the servo mechanism
bpy.ops.mesh.primitive_cylinder_add(radius=0.5, depth=1, location=(0, 0, 0), rotation=(math.radians(90), 0, 0))
hub = bpy.context.active_object
mat_hub = bpy.data.materials.new(name='HubMat')
mat_hub.use_nodes = True
bsdf_hub = mat_hub.node_tree.nodes.get('Principled BSDF')
bsdf_hub.inputs['Base Color'].default_value = (0.5, 0.5, 0.5, 1.0)
hub.data.materials.append(mat_hub)

# Create the dual opposing claw fingers
for i in range(2):
    bpy.ops.mesh.primitive_cube_add(size=1, location=(i * 3 - 1.5, 0, 1), rotation=(math.radians(-90), 0, math.radians(i * 180)))
    finger = bpy.context.active_object
    mat_finger = bpy.data.materials.new(name='FingerMat')
    mat_finger.use_nodes = True
    bsdf_finger = mat_finger.node_tree.nodes.get('Principled BSDF')
    bsdf_finger.inputs['Base Color'].default_value = (0.2, 0.8, 0.2, 1.0)
    finger.data.materials.append(mat_finger)

# Create the rubber grip pads
for i in range(2):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.5, location=(i * 3 - 1.5, 0, 1.5))
    pad = bpy.context.active_object
    mat_pad = bpy.data.materials.new(name='PadMat')
    mat_pad.use_nodes = True
    bsdf_pad = mat_pad.node_tree.nodes.get('Principled BSDF')
    bsdf_pad.inputs['Base Color'].default_value = (0.8, 0.2, 0.2, 1.0)
    pad.data.materials.append(mat_pad)

# Export the scene to OBJ
bpy.ops.wm.obj_export(filepath=r"G:/Sentinel_Workspace/task_1794672112.obj")
print("SENTINEL_3D_MODEL_EXPORTED_OK")