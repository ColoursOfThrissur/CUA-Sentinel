import bpy
import math
bpy.ops.wm.read_factory_settings(use_empty=True)

# Create warhammer handle (cylinder)
bpy.ops.mesh.primitive_cylinder_add(radius=0.1, depth=1.2, location=(0, 0, -0.5), rotation=(math.radians(90), 0, 0))
handle = bpy.context.active_object

# Create warhammer head base (sphere)
bpy.ops.mesh.primitive_uv_sphere_add(radius=0.3, location=(0, 0, 0.6), segments=16, ring_count=16)
head_base = bpy.context.active_object

# Add spikes to the head
for i in range(8):
    spike_angle = math.radians(i * (360 / 8))
    spike_x = math.cos(spike_angle) * 0.25
    spike_z = math.sin(spike_angle) * 0.25
    
    bpy.ops.mesh.primitive_cone_add(radius1=0.04, radius2=0.01, depth=0.3, location=(spike_x, 0.6 + spike_z, 0), rotation=(math.radians(90), 0, 0))
    spike = bpy.context.active_object
    spike.rotation_euler[0] = math.radians(-45)

# Add central spike (larger)
bpy.ops.mesh.primitive_cone_add(radius1=0.06, radius2=0.01, depth=0.4, location=(0, 0.7, 0), rotation=(math.radians(90), 0, 0))
central_spike = bpy.context.active_object
central_spike.rotation_euler[0] = math.radians(-60)

# Add crossguard (two small cylinders on sides)
bpy.ops.mesh.primitive_cylinder_add(radius=0.03, depth=0.15, location=(-0.2, 0.4, 0), rotation=(math.radians(90), 0, math.radians(90)))
crossguard_left = bpy.context.active_object

bpy.ops.mesh.primitive_cylinder_add(radius=0.03, depth=0.15, location=(0.2, 0.4, 0), rotation=(math.radians(90), 0, math.radians(90)))
crossguard_right = bpy.context.active_object

# Add simple material to all objects
for obj in bpy.data.objects:
    if obj.type == 'MESH':
        mat = bpy.data.materials.new(name=f"{obj.name}_mat")
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        nodes.clear()
        
        bsdf_node = nodes.new(type='ShaderNodeBsdfPrincipled')
        output_node = nodes.new(type='ShaderNodeOutputMaterial')
        
        links = mat.node_tree.links
        links.new(bsdf_node.outputs['BSDF'], output_node.inputs['Surface'])
        
        bsdf_node.inputs['Base Color'].default_value = (0.3, 0.25, 0.18, 1)
        bsdf_node.inputs['Roughness'].default_value = 0.7
        bsdf_node.inputs['Metallic'].default_value = 0.6
        
        obj.data.materials.append(mat)

# Select all objects for export
for obj in bpy.data.objects:
    obj.select_set(True)
bpy.context.view_layer.objects.active = handle

bpy.ops.wm.obj_export(filepath=r"C:/Users/derik/Desktop/Derik/Projects/Sentinel/workspaces/task_1794325018.obj")
print("SENTINEL_3D_MODEL_EXPORTED_OK")