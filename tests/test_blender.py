"""Tests for Real Blender 4.5 Motor Organ — including Material & Modifier organs (v0.3.1)."""
import pytest
from pathlib import Path
import tempfile
import shutil

from sentinel_broker.tool_registry import ToolRegistry
from sentinel_broker.organs.blender import register_blender_organs, find_blender_executable


def test_find_blender_executable():
    exe = find_blender_executable()
    assert Path(exe).exists()
    assert "blender.exe" in exe.lower()


def test_blender_create_3d_mesh_execution():
    registry = ToolRegistry()
    register_blender_organs(registry)

    temp_dir = Path(tempfile.mkdtemp())
    out_obj = temp_dir / "test_cube.obj"

    script = f"""
import bpy
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=2.0)
bpy.ops.wm.obj_export(filepath=r"{str(out_obj)}")
"""
    try:
        res = registry.execute_tool("blender_run_python", {
            "script_code": script,
            "output_obj_path": str(out_obj),
        })

        assert res["exit_code"] == 0
        assert out_obj.exists()
        assert out_obj.stat().st_size > 50  # Real 3D OBJ file has vertices and faces
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_blender_list_scene_objects():
    """blender_list_scene_objects parses an OBJ file without calling Blender."""
    registry = ToolRegistry()
    register_blender_organs(registry)

    temp_dir = Path(tempfile.mkdtemp())
    obj_file = temp_dir / "test_scene.obj"

    # Write a minimal OBJ with two named objects
    obj_file.write_text(
        "o Cube\n"
        "v 1.0 1.0 1.0\n"
        "v -1.0 1.0 1.0\n"
        "v -1.0 -1.0 1.0\n"
        "f 1 2 3\n"
        "o Sphere\n"
        "v 0.5 0.5 0.5\n"
        "v -0.5 0.5 0.5\n"
        "f 4 5\n",
        encoding="utf-8",
    )
    try:
        res = registry.execute_tool("blender_list_scene_objects", {
            "artifact_obj_path": str(obj_file),
        })
        assert res["total_objects"] == 2
        names = [o["name"] for o in res["objects"]]
        assert "Cube" in names
        assert "Sphere" in names
        cube = next(o for o in res["objects"] if o["name"] == "Cube")
        assert cube["vertices"] == 3
        assert cube["faces"] == 1
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_blender_list_scene_objects_missing_file():
    """blender_list_scene_objects returns a helpful error for missing files."""
    registry = ToolRegistry()
    register_blender_organs(registry)

    res = registry.execute_tool("blender_list_scene_objects", {
        "artifact_obj_path": "/nonexistent/path/model.obj",
    })
    assert "error" in res
    assert res["objects"] == []


def test_blender_set_material_color_runs():
    """blender_set_material_color executes Blender headless and re-exports OBJ."""
    registry = ToolRegistry()
    register_blender_organs(registry)

    temp_dir = Path(tempfile.mkdtemp())
    out_obj = temp_dir / "colored_cube.obj"

    # First create a simple cube OBJ via blender_run_python
    script = f"""
import bpy
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=2.0)
bpy.ops.wm.obj_export(filepath=r"{str(out_obj).replace(chr(92), '/')}")
"""
    res_create = registry.execute_tool("blender_run_python", {
        "script_code": script,
        "output_obj_path": str(out_obj),
    })
    assert res_create["exit_code"] == 0
    assert out_obj.exists()

    # Now apply a color
    res_color = registry.execute_tool("blender_set_material_color", {
        "artifact_obj_path": str(out_obj),
        "hex_color": "#ff5500",
        "metalness": 0.8,
        "roughness": 0.2,
        "emission_strength": 0.0,
        "output_obj_path": str(out_obj),
    })
    assert res_color["exit_code"] == 0, f"Blender stderr: {res_color.get('stderr', '')}"
    assert out_obj.exists()
    assert out_obj.stat().st_size > 50


def test_blender_add_modifier_runs():
    """blender_add_modifier applies subdivision and re-exports OBJ with more vertices."""
    registry = ToolRegistry()
    register_blender_organs(registry)

    temp_dir = Path(tempfile.mkdtemp())
    out_obj = temp_dir / "subdivided_cube.obj"

    # Create base cube
    base_script = f"""
import bpy
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=2.0)
bpy.ops.wm.obj_export(filepath=r"{str(out_obj).replace(chr(92), '/')}")
"""
    res_create = registry.execute_tool("blender_run_python", {
        "script_code": base_script,
        "output_obj_path": str(out_obj),
    })
    assert res_create["exit_code"] == 0
    base_size = out_obj.stat().st_size

    # Apply subdivision modifier
    res_mod = registry.execute_tool("blender_add_modifier", {
        "artifact_obj_path": str(out_obj),
        "modifier_type": "subdivision",
        "strength": 1,
        "output_obj_path": str(out_obj),
    })
    assert res_mod["exit_code"] == 0, f"stderr: {res_mod.get('stderr', '')}"
    # Subdivided mesh should have more data than base cube
    assert out_obj.stat().st_size > base_size
