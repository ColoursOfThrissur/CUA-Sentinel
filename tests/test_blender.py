"""Tests for Real Blender 4.5 Motor Organ."""
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
