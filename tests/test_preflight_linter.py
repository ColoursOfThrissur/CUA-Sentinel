"""Unit tests for Sentinel Pre-Flight AST Linter / Rewriter (Upgrade A)."""
import pytest
from sentinel_core.preflight_linter import PreFlightLinter


def test_blender_export_scene_rewrite():
    old_code = (
        "import bpy\n"
        "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
        "bpy.ops.mesh.primitive_cube_add(size=2.0)\n"
        "bpy.ops.export_scene.obj(filepath=r'test.obj')\n"
    )
    res = PreFlightLinter.sanitize(old_code, domain="3d")
    assert res.modified is True
    assert "bpy.ops.wm.obj_export(filepath=r'test.obj')" in res.code
    assert "bpy.ops.export_scene.obj" not in res.code


def test_blender_principled_bsdf_specular_sanitization():
    code_with_specular = (
        "import bpy\n"
        "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
        "mat = bpy.data.materials.new(name='Wood')\n"
        "principled = mat.node_tree.nodes['Principled BSDF']\n"
        "principled.inputs['Specular'].default_value = 0.5\n"
    )
    res = PreFlightLinter.sanitize(code_with_specular, domain="3d")
    assert res.modified is True
    assert "# principled.inputs['Specular'].default_value = 0.5" in res.code


def test_blender_scene_reset_injection():
    code_without_reset = (
        "import bpy\n"
        "bpy.ops.mesh.primitive_cube_add(size=2.0)\n"
        "bpy.ops.wm.obj_export(filepath=r'test.obj')\n"
    )
    res = PreFlightLinter.sanitize(code_without_reset, domain="3d")
    assert res.modified is True
    assert "bpy.ops.wm.read_factory_settings(use_empty=True)" in res.code


def test_python_redundant_del_removal():
    buggy_lru_snippet = (
        "class LRUCache:\n"
        "    def put(self, key, value):\n"
        "        if len(self.cache) > self.cap:\n"
        "            oldest, _ = self.cache.popitem(last=False)\n"
        "            del self.cache[oldest]\n"
    )
    res = PreFlightLinter.sanitize(buggy_lru_snippet, domain="code")
    assert res.modified is True
    assert "oldest, _ = self.cache.popitem(last=False)" in res.code
    assert "del self.cache[oldest]" not in res.code


def test_preflight_syntax_error_fast_fail():
    broken_code = "class Broken(:\n    def foo(): pass"
    res = PreFlightLinter.sanitize(broken_code, domain="code")
    assert res.fatal_error is not None


def test_blender_object_creation_not_commented_out_when_linked():
    code_with_objects_link = (
        "import bpy\n"
        "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
        "tube = bpy.data.objects.new('Telescope_Tube', None)\n"
        "obj_tube = bpy.context.collection.objects.link(tube)\n"
        "bpy.ops.wm.obj_export(filepath=r'test.obj')\n"
    )
    res = PreFlightLinter.sanitize(code_with_objects_link, domain="3d")
    assert "tube = bpy.data.objects.new('Telescope_Tube', None)" in res.code
    assert "# tube = " not in res.code
    assert "Auto-disabled" not in res.code


def test_blender_object_creation_auto_linked_when_unlinked():
    code_unlinked = (
        "import bpy\n"
        "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
        "tube = bpy.data.objects.new('Telescope_Tube', None)\n"
        "bpy.ops.wm.obj_export(filepath=r'test.obj')\n"
    )
    res = PreFlightLinter.sanitize(code_unlinked, domain="3d")
    assert "tube = bpy.data.objects.new('Telescope_Tube', None)" in res.code
    assert "bpy.context.collection.objects.link(tube)" in res.code
    assert "# tube = " not in res.code
