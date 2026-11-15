import bpy
import math

bpy.ops.wm.read_factory_settings(use_empty=True)

# Function to create a spur gear with given parameters
def create_spur_gear(teeth, radius, depth):
    bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=depth)
    obj = bpy.context.active_object
    mod = obj.modifiers.new(name='Bevel', type='BEVEL')
    mod.width = 0.1
    mod.segments = teeth
    bpy.context.view_layer.objects.active = obj
    if 'Bevel' in bpy.context.active_object.modifiers:
        if bpy.context.active_object and 'Bevel' in bpy.context.active_object.modifiers:
            bpy.ops.object.modifier_apply(modifier='Bevel')
# Function to create a shaft with given parameters
def create_shaft(radius, length):
    bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=length)
    obj = bpy.context.active_object

# Create input drive shaft
create_shaft(0.5, 10)
drive_shaft = bpy.context.active_object
drive_shaft.location = (0, -5, 0)

# Create central pinion gear with 12 teeth
create_spur_gear(12, 3, 4)
central_pinion = bpy.context.active_object
central_pinion.location = (0, 0, 0)

# Create outer ring gear with 36 teeth
create_spur_gear(36, 5, 8)
ring_gear = bpy.context.active_object
ring_gear.location = (0, 5, 0)

# Create mounting flange collar
bpy.ops.mesh.primitive_cylinder_add(radius=7, depth=1, location=(0, 0, -4))
flange_collar = bpy.context.active_object

# Assign materials to parts
def assign_material(obj, color, metallic, roughness):
    mat = bpy.data.materials.new(name=f'{obj.name}_Mat')
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = color
    bsdf.inputs['Metallic'].default_value = metallic
    bsdf.inputs['Roughness'].default_value = roughness
    obj.data.materials.append(mat)

assign_material(drive_shaft, (0.5, 0.5, 0.5, 1.0), 0.9, 0.2)
assign_material(central_pinion, (0.8, 0.8, 0.8, 1.0), 0.9, 0.2)
assign_material(ring_gear, (0.7, 0.7, 0.7, 1.0), 0.9, 0.2)
assign_material(flange_collar, (0.6, 0.6, 0.6, 1.0), 0.9, 0.2)

# Export the scene to OBJ
bpy.ops.wm.obj_export(filepath=r"G:/Sentinel_Workspace/gym_t15_1794676955.obj")
print("SENTINEL_3D_MODEL_EXPORTED_OK")