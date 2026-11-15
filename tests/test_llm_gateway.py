"""Tests for LLMGateway."""
import pytest
from sentinel_core.llm_gateway import LLMGateway


def test_llm_gateway_extract_python_code():
    gw = LLMGateway()
    raw = """Here is the Blender script:
```python
import bpy
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cylinder_add(radius=1.0, depth=2.0)
bpy.ops.wm.obj_export(filepath=r"test.obj")
```
Hope this helps!"""

    code = gw.extract_python_code(raw)
    assert code.startswith("import bpy")
    assert 'bpy.ops.wm.obj_export(filepath=r"test.obj")' in code
    assert "Here is" not in code
    assert "Hope this helps" not in code


def test_llm_gateway_prompt_formatting():
    gw = LLMGateway()
    # Test fallback or availability check
    avail = gw.is_available()
    assert isinstance(avail, bool)


def test_synthesize_blender_script_fallback():
    from sentinel_broker.organs.blender_prompts import synthesize_blender_script
    # Force procedural fallback
    code = synthesize_blender_script("a medieval battle sword", "test_sword.obj", use_llm=False)
    assert "import bpy" in code
    assert "test_sword.obj" in code
    assert "obj_export" in code


def test_llm_gateway_two_stage_blueprint_pipeline():
    class MockGateway(LLMGateway):
        def generate(self, **kwargs):
            prompt = kwargs.get("prompt", "")
            system = kwargs.get("system", "")
            if "Senior Mechanical Assembly Architect" in system:
                return '{"root_part": "Base", "overall_height": 1.2, "parts": [{"name": "Base", "location": [0,0,0.5]}]}'
            elif "3D Model Synthesizer" in system:
                return '```python\nimport bpy\n# synthesized from blueprint\nbpy.ops.mesh.primitive_cylinder_add(location=(0,0,0.5))\nbpy.ops.wm.obj_export(filepath=r"out.obj")\n```'
            return ""

    gw = MockGateway()
    plan = gw.plan_3d_assembly("telescope")
    assert "root_part" in plan
    code = gw.generate_blender_code("telescope", "out.obj")
    assert "import bpy" in code
    assert "primitive_cylinder_add" in code
    assert "out.obj" in code
