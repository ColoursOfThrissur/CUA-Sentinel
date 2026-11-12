"""Sentinel Blender 3D Motor Organ.
Integrates real Blender 4.5 execution (both headless scripting and interactive GUI automation).

Extended capabilities (v0.3.1):
  - blender_add_modifier: Apply subdivision, bevel, solidify, wireframe, displace, decimate modifiers
  - blender_set_material_color: Assign Principled BSDF color / metalness / roughness / emission to any object
  - blender_apply_modifiers: Apply all pending modifiers to the scene and re-export OBJ
  - blender_list_scene_objects: List all mesh objects currently in the scene file
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from sentinel_core.side_effects import EffectClass
from sentinel_broker.tool_registry import ToolRegistry

BLENDER_DEFAULT_PATH = r"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe"


def find_blender_executable() -> str:
    """Finds installed blender.exe on the host."""
    if Path(BLENDER_DEFAULT_PATH).exists():
        return BLENDER_DEFAULT_PATH
    found = shutil.which("blender")
    if found:
        return found
    common_paths = [
        Path(r"C:\Program Files\Blender Foundation"),
        Path(r"C:\Program Files (x86)\Blender Foundation"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Blender Foundation",
    ]
    for p in common_paths:
        if p.exists():
            for b in p.rglob("blender.exe"):
                return str(b)
    raise FileNotFoundError("Blender executable not found on host system.")


def register_blender_organs(registry: ToolRegistry):

    @registry.register(
        name="blender_run_python",
        description="Executes a Python script inside real Blender 4.5 to create, modify, or export 3D geometry.",
        effect_class=EffectClass.NON_IDEMPOTENT_WRITE,
        parameters_schema={
            "script_code": "str (Python bpy code to run inside Blender)",
            "output_obj_path": "str (optional path to expected 3D OBJ output)",
            "timeout_sec": "float (default 60.0)",
        },
    )
    def blender_run_python(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        blender_exe = find_blender_executable()
        script_code = params.get("script_code", "")
        timeout = float(params.get("timeout_sec", 60.0))
        output_obj = params.get("output_obj_path")

        # Write script to temporary file
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(script_code)
            script_file = Path(f.name)

        try:
            cmd = [
                blender_exe,
                "--background",
                "--python",
                str(script_file),
            ]
            start_t = time.time()
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            dur = time.time() - start_t

            result = {
                "exit_code": proc.returncode,
                "duration_sec": round(dur, 2),
                "blender_path": blender_exe,
                "stdout": proc.stdout[-2000:],
                "stderr": proc.stderr[-1000:],
                "artifact_created": False,
            }

            if output_obj:
                p = Path(output_obj)
                if p.exists() and p.stat().st_size > 0:
                    result["artifact_created"] = True
                    result["artifact_bytes"] = p.stat().st_size
                    result["artifact_path"] = str(p.resolve())

            return result
        finally:
            try:
                script_file.unlink(missing_ok=True)
            except Exception:
                pass

    @registry.register(
        name="blender_launch_gui",
        description="Launches Blender 4.5 in interactive GUI mode on the user's desktop so the 3D viewport opens.",
        effect_class=EffectClass.NON_IDEMPOTENT_WRITE,
        parameters_schema={
            "file_to_open": "str (optional .blend file path to open)",
        },
    )
    def blender_launch_gui(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        blender_exe = find_blender_executable()
        file_to_open = params.get("file_to_open")

        cmd = [blender_exe]
        if file_to_open and Path(file_to_open).exists():
            cmd.append(str(Path(file_to_open).resolve()))

        # Spawn non-blocking GUI process
        proc = subprocess.Popen(cmd)
        return {
            "status": "LAUNCHED",
            "pid": proc.pid,
            "blender_path": blender_exe,
            "file_opened": file_to_open,
        }

    # -------------------------------------------------------------------------
    # Material & Modifier Organs (v0.3.1)
    # -------------------------------------------------------------------------

    @registry.register(
        name="blender_set_material_color",
        description=(
            "Assigns a Principled BSDF material (color, metalness, roughness, emission) "
            "to all or named objects in an existing OBJ/blend scene, then re-exports the OBJ."
        ),
        effect_class=EffectClass.NON_IDEMPOTENT_WRITE,
        parameters_schema={
            "artifact_obj_path": "str (path to the .obj file to modify)",
            "hex_color": "str (hex color like '#ff5500' applied as Base Color)",
            "metalness": "float 0.0–1.0 (default 0.1)",
            "roughness": "float 0.0–1.0 (default 0.4)",
            "emission_strength": "float (0.0 = no emission, >0 glows; default 0.0)",
            "object_name": "str (optional: target specific mesh name, leave empty for all)",
            "output_obj_path": "str (optional: where to write modified OBJ; defaults to same file)",
            "timeout_sec": "float (default 60.0)",
        },
    )
    def blender_set_material_color(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        blender_exe = find_blender_executable()
        artifact = params.get("artifact_obj_path", "")
        hex_color = params.get("hex_color", "#7ec8e3")
        metalness = float(params.get("metalness", 0.1))
        roughness = float(params.get("roughness", 0.4))
        emission_strength = float(params.get("emission_strength", 0.0))
        object_name = params.get("object_name", "")
        output_obj = params.get("output_obj_path") or artifact
        timeout = float(params.get("timeout_sec", 60.0))

        # Parse hex to RGB floats
        h = hex_color.lstrip("#")
        if len(h) == 6:
            r = int(h[0:2], 16) / 255.0
            g = int(h[2:4], 16) / 255.0
            b = int(h[4:6], 16) / 255.0
        else:
            r, g, b = 0.49, 0.78, 0.89  # fallback sky-blue

        escaped_input = str(Path(artifact).resolve()).replace("\\", "/")
        escaped_output = str(Path(output_obj).resolve()).replace("\\", "/")
        obj_filter = f'"{object_name}"' if object_name else '""'

        script = f"""
import bpy

bpy.ops.wm.read_factory_settings(use_empty=True)

# Import OBJ
bpy.ops.wm.obj_import(filepath=r"{escaped_input}")

target_name = {obj_filter}

for obj in bpy.context.scene.objects:
    if obj.type != 'MESH':
        continue
    if target_name and obj.name != target_name:
        continue

    mat = bpy.data.materials.new(name="Sentinel_Mat_" + obj.name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = ({r:.4f}, {g:.4f}, {b:.4f}, 1.0)
        bsdf.inputs["Metallic"].default_value = {metalness:.4f}
        bsdf.inputs["Roughness"].default_value = {roughness:.4f}
        if {emission_strength:.4f} > 0:
            bsdf.inputs["Emission Strength"].default_value = {emission_strength:.4f}
            bsdf.inputs["Emission Color"].default_value = ({r:.4f}, {g:.4f}, {b:.4f}, 1.0)
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)

bpy.ops.wm.obj_export(filepath=r"{escaped_output}")
print("SENTINEL_MATERIAL_APPLIED_OK")
"""
        return _run_blender_script(blender_exe, script, output_obj, timeout)

    @registry.register(
        name="blender_add_modifier",
        description=(
            "Applies a Blender modifier (subdivision, bevel, solidify, wireframe, decimate, displace) "
            "to all or named mesh objects in an OBJ scene, then re-exports the OBJ."
        ),
        effect_class=EffectClass.NON_IDEMPOTENT_WRITE,
        parameters_schema={
            "artifact_obj_path": "str (path to .obj to modify)",
            "modifier_type": "str: 'subdivision'|'bevel'|'solidify'|'wireframe'|'decimate'|'displace'",
            "strength": "float (level/thickness/ratio depending on modifier; default varies)",
            "object_name": "str (optional: target specific mesh, empty = all meshes)",
            "output_obj_path": "str (optional output path; defaults to same file)",
            "timeout_sec": "float (default 90.0)",
        },
    )
    def blender_add_modifier(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        blender_exe = find_blender_executable()
        artifact = params.get("artifact_obj_path", "")
        modifier_type = params.get("modifier_type", "subdivision").lower()
        strength = float(params.get("strength", 1.0))
        object_name = params.get("object_name", "")
        output_obj = params.get("output_obj_path") or artifact
        timeout = float(params.get("timeout_sec", 90.0))

        escaped_input = str(Path(artifact).resolve()).replace("\\", "/")
        escaped_output = str(Path(output_obj).resolve()).replace("\\", "/")
        obj_filter = f'"{object_name}"' if object_name else '""'

        MOD_CODE = {
            "subdivision": f"""
    mod = obj.modifiers.new(name="Subdivision", type="SUBSURF")
    mod.levels = max(1, min(int({strength}), 4))
    mod.render_levels = max(1, min(int({strength}), 4))
""",
            "bevel": f"""
    mod = obj.modifiers.new(name="Bevel", type="BEVEL")
    mod.width = {strength}
    mod.segments = 3
""",
            "solidify": f"""
    mod = obj.modifiers.new(name="Solidify", type="SOLIDIFY")
    mod.thickness = {strength}
""",
            "wireframe": f"""
    mod = obj.modifiers.new(name="Wireframe", type="WIREFRAME")
    mod.thickness = max(0.005, {strength})
""",
            "decimate": f"""
    mod = obj.modifiers.new(name="Decimate", type="DECIMATE")
    mod.ratio = max(0.05, min({strength}, 1.0))
""",
            "displace": f"""
    tex = bpy.data.textures.new("Sentinel_Displace_Tex", "CLOUDS")
    tex.noise_scale = 1.5
    mod = obj.modifiers.new(name="Displace", type="DISPLACE")
    mod.texture = tex
    mod.strength = {strength}
""",
        }.get(modifier_type, f"""
    mod = obj.modifiers.new(name="Subdivision", type="SUBSURF")
    mod.levels = 1
""")

        script = f"""
import bpy

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.obj_import(filepath=r"{escaped_input}")

target_name = {obj_filter}

for obj in bpy.context.scene.objects:
    if obj.type != 'MESH':
        continue
    if target_name and obj.name != target_name:
        continue
    bpy.context.view_layer.objects.active = obj
    {MOD_CODE.strip()}

# Apply all modifiers on all meshes before export
for obj in bpy.context.scene.objects:
    if obj.type != 'MESH':
        continue
    bpy.context.view_layer.objects.active = obj
    for mod in list(obj.modifiers):
        try:
            bpy.ops.object.modifier_apply(modifier=mod.name)
        except Exception as e:
            print(f"Could not apply {{mod.name}}: {{e}}")

bpy.ops.wm.obj_export(filepath=r"{escaped_output}")
print("SENTINEL_MODIFIER_APPLIED_OK")
"""
        return _run_blender_script(blender_exe, script, output_obj, timeout)

    @registry.register(
        name="blender_apply_modifiers",
        description=(
            "Applies (collapses) all pending modifiers on every mesh object in an OBJ scene "
            "and re-exports a clean, modifier-baked OBJ."
        ),
        effect_class=EffectClass.NON_IDEMPOTENT_WRITE,
        parameters_schema={
            "artifact_obj_path": "str (path to .obj to process)",
            "output_obj_path": "str (optional output path; defaults to same file)",
            "timeout_sec": "float (default 60.0)",
        },
    )
    def blender_apply_modifiers(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        blender_exe = find_blender_executable()
        artifact = params.get("artifact_obj_path", "")
        output_obj = params.get("output_obj_path") or artifact
        timeout = float(params.get("timeout_sec", 60.0))
        escaped_input = str(Path(artifact).resolve()).replace("\\", "/")
        escaped_output = str(Path(output_obj).resolve()).replace("\\", "/")

        script = f"""
import bpy

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.obj_import(filepath=r"{escaped_input}")

for obj in bpy.context.scene.objects:
    if obj.type != 'MESH':
        continue
    bpy.context.view_layer.objects.active = obj
    for mod in list(obj.modifiers):
        try:
            bpy.ops.object.modifier_apply(modifier=mod.name)
        except Exception as e:
            print(f"Skipped {{mod.name}}: {{e}}")

bpy.ops.wm.obj_export(filepath=r"{escaped_output}")
print("SENTINEL_MODIFIERS_BAKED_OK")
"""
        return _run_blender_script(blender_exe, script, output_obj, timeout)

    @registry.register(
        name="blender_list_scene_objects",
        description="Lists all mesh objects (names, vertex counts, dimensions) present in an exported OBJ file.",
        effect_class=EffectClass.READ_ONLY,
        parameters_schema={
            "artifact_obj_path": "str (path to .obj file to inspect)",
        },
    )
    def blender_list_scene_objects(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        """Parse the OBJ file directly — no Blender subprocess needed."""
        artifact = params.get("artifact_obj_path", "")
        p = Path(artifact)
        if not p.exists():
            return {"error": f"File not found: {artifact}", "objects": []}

        objects = []
        current_name = "Unnamed"
        vertex_count = 0
        face_count = 0
        vertices_x, vertices_y, vertices_z = [], [], []

        def flush():
            nonlocal current_name, vertex_count, face_count, vertices_x, vertices_y, vertices_z
            if vertex_count > 0:
                dims = ""
                if vertices_x:
                    dx = max(vertices_x) - min(vertices_x)
                    dy = max(vertices_y) - min(vertices_y)
                    dz = max(vertices_z) - min(vertices_z)
                    dims = f"{dx:.2f} × {dy:.2f} × {dz:.2f}"
                objects.append({
                    "name": current_name,
                    "vertices": vertex_count,
                    "faces": face_count,
                    "dimensions": dims,
                })
            vertex_count = 0
            face_count = 0
            vertices_x, vertices_y, vertices_z = [], [], []

        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line.startswith("o "):
                    flush()
                    current_name = line[2:].strip()
                elif line.startswith("v ") and not line.startswith("vt") and not line.startswith("vn"):
                    parts = line.split()
                    if len(parts) >= 4:
                        try:
                            vertices_x.append(float(parts[1]))
                            vertices_y.append(float(parts[2]))
                            vertices_z.append(float(parts[3]))
                        except ValueError:
                            pass
                        vertex_count += 1
                elif line.startswith("f "):
                    face_count += 1

        flush()

        total_v = sum(o["vertices"] for o in objects)
        total_f = sum(o["faces"] for o in objects)
        return {
            "file": str(p.resolve()),
            "file_size_bytes": p.stat().st_size,
            "total_objects": len(objects),
            "total_vertices": total_v,
            "total_faces": total_f,
            "objects": objects,
        }


def _run_blender_script(blender_exe: str, script_code: str, output_obj: str, timeout: float) -> dict[str, Any]:
    """Helper: write script to temp file, run Blender headless, return result dict."""
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(script_code)
        script_file = Path(f.name)

    try:
        cmd = [blender_exe, "--background", "--python", str(script_file)]
        start_t = time.time()
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        dur = time.time() - start_t

        result = {
            "exit_code": proc.returncode,
            "duration_sec": round(dur, 2),
            "blender_path": blender_exe,
            "stdout": proc.stdout[-2000:],
            "stderr": proc.stderr[-1000:],
            "artifact_created": False,
        }
        if output_obj:
            p = Path(output_obj)
            if p.exists() and p.stat().st_size > 0:
                result["artifact_created"] = True
                result["artifact_bytes"] = p.stat().st_size
                result["artifact_path"] = str(p.resolve())
        return result
    finally:
        script_file.unlink(missing_ok=True)
