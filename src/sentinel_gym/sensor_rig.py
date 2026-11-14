"""Sentinel Empirical Sensor Rig.
Ground-truth multi-modal sensory inspection: renders 4-angle physical snapshots,
calculates physical mesh topology metrics (manifoldness, non-zero volume, material distribution),
and enforces mathematical pre-flight gates to eliminate false-positive exit-code passes.
"""
from __future__ import annotations

import ast
import csv
import json
import logging
import math
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sentinel_broker.organs.blender import find_blender_executable

logger = logging.getLogger("SentinelSensorRig")


@dataclass
class ModelInspectionResult:
    success: bool
    metrics: dict[str, Any]
    snapshots: dict[str, str] = field(default_factory=dict)
    is_degenerate: bool = False
    degenerate_reason: str | None = None
    raw_error: str | None = None


@dataclass
class CSVInspectionResult:
    success: bool
    row_count: int
    col_count: int
    headers: list[str]
    null_ratio: float
    numeric_columns: list[str]
    is_degenerate: bool = False
    degenerate_reason: str | None = None


@dataclass
class CodeInspectionResult:
    success: bool
    syntax_valid: bool
    ast_nodes_count: int
    defined_classes: list[str]
    defined_functions: list[str]
    is_degenerate: bool = False
    degenerate_reason: str | None = None


# Script executed inside headless Blender to extract metrics and render 4 views
BLENDER_RIG_SCRIPT = '''
import bpy
import bmesh
import math
import os
import sys
import json
from mathutils import Vector

obj_path = r"{OBJ_PATH}"
output_dir = r"{OUTPUT_DIR}"

os.makedirs(output_dir, exist_ok=True)
meta_path = os.path.join(output_dir, "metrics.json")

# 1. Reset Scene
bpy.ops.wm.read_factory_settings(use_empty=True)

# 2. Import OBJ
imported_objs = []
try:
    if hasattr(bpy.ops.wm, "obj_import"):
        bpy.ops.wm.obj_import(filepath=obj_path)
    else:
        bpy.ops.import_scene.obj(filepath=obj_path)
    imported_objs = [o for o in bpy.context.scene.objects if o.type == 'MESH']
except Exception as e:
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({{"error": f"Import failed: {{e}}", "success": False}}, f)
    sys.exit(0)

if not imported_objs:
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({{"error": "No mesh objects found in OBJ", "success": False, "object_count": 0}}, f)
    sys.exit(0)

# 3. Compute Ground-Truth Topology Metrics
total_verts = 0
total_faces = 0
total_edges = 0
non_manifold_edges = 0
materials_set = set()
part_names = []

min_coord = [float('inf')] * 3
max_coord = [float('-inf')] * 3

for obj in imported_objs:
    part_names.append(obj.name)
    me = obj.data
    total_verts += len(me.vertices)
    total_faces += len(me.polygons)
    total_edges += len(me.edges)

    for mat_slot in obj.material_slots:
        if mat_slot.material:
            materials_set.add(mat_slot.material.name)

    # Check non-manifold geometry via bmesh
    bm = bmesh.new()
    bm.from_mesh(me)
    for edge in bm.edges:
        if not edge.is_manifold:
            non_manifold_edges += 1
    bm.free()

    # Bounding box in world coordinates
    for corner in obj.bound_box:
        w_corner = obj.matrix_world @ Vector(corner)
        for i in range(3):
            if w_corner[i] < min_coord[i]: min_coord[i] = w_corner[i]
            if w_corner[i] > max_coord[i]: max_coord[i] = w_corner[i]

dx = max(0.0, max_coord[0] - min_coord[0])
dy = max(0.0, max_coord[1] - min_coord[1])
dz = max(0.0, max_coord[2] - min_coord[2])
volume = dx * dy * dz
center = [(min_coord[i] + max_coord[i]) / 2.0 for i in range(3)]
radius = max(dx, dy, dz, 0.5)

metrics = {{
    "success": True,
    "object_count": len(imported_objs),
    "part_names": part_names,
    "vertex_count": total_verts,
    "face_count": total_faces,
    "edge_count": total_edges,
    "non_manifold_edges": non_manifold_edges,
    "material_count": len(materials_set),
    "materials": list(materials_set),
    "bounding_box": {{
        "dx": round(dx, 4),
        "dy": round(dy, 4),
        "dz": round(dz, 4),
        "volume": round(volume, 6),
    }},
    "center": [round(c, 4) for c in center],
}}

# 4. Set up Camera and Studio Lighting for 4-angle visual rendering
scene = bpy.context.scene
scene.render.resolution_x = 512
scene.render.resolution_y = 512
scene.render.resolution_percentage = 100
scene.render.engine = 'BLENDER_WORKBENCH'
if hasattr(scene.display, "shading"):
    scene.display.shading.color_type = 'MATERIAL'
    scene.display.shading.light = 'STUDIO'

# Add Light
light_data = bpy.data.lights.new(name="StudioSun", type='SUN')
light_data.energy = 3.0
light_obj = bpy.data.objects.new(name="StudioSun", object_data=light_data)
scene.collection.objects.link(light_obj)
light_obj.rotation_euler = (math.radians(45), math.radians(30), math.radians(60))

# Add Camera
cam_data = bpy.data.cameras.new(name="InspectCam")
cam_obj = bpy.data.objects.new(name="InspectCam", object_data=cam_data)
scene.collection.objects.link(cam_obj)
scene.camera = cam_obj

# Camera tracking constraint to look at model center
empty_target = bpy.data.objects.new("Target", None)
scene.collection.objects.link(empty_target)
empty_target.location = Vector(center)

track = cam_obj.constraints.new(type='TRACK_TO')
track.target = empty_target
track.track_axis = 'TRACK_NEGATIVE_Z'
track.up_axis = 'UP_Y'

# Helper to position camera and render
def render_view(filename, dist_mult, elevation_deg, azimuth_deg, wireframe=False):
    elev = math.radians(elevation_deg)
    azim = math.radians(azimuth_deg)
    dist = radius * dist_mult

    cx = center[0] + dist * math.cos(elev) * math.cos(azim)
    cy = center[1] + dist * math.cos(elev) * math.sin(azim)
    cz = center[2] + dist * math.sin(elev)
    cam_obj.location = Vector((cx, cy, cz))

    if wireframe and hasattr(scene.display, "shading"):
        scene.display.shading.show_cavity = True
        scene.display.shading.type = 'SOLID'
        scene.display.shading.wireframe_color_type = 'OBJECT'

    bpy.context.view_layer.update()
    scene.render.filepath = os.path.join(output_dir, filename)
    bpy.ops.render.render(write_still=True)

# Render 4 Perspectives
try:
    render_view("iso.png", dist_mult=2.4, elevation_deg=35, azimuth_deg=45)
    render_view("front.png", dist_mult=2.2, elevation_deg=5, azimuth_deg=0)
    render_view("top.png", dist_mult=2.6, elevation_deg=89, azimuth_deg=0)
    render_view("detail.png", dist_mult=1.6, elevation_deg=20, azimuth_deg=135, wireframe=True)
except Exception as e:
    metrics["render_error"] = str(e)

with open(meta_path, "w", encoding="utf-8") as f:
    json.dump(metrics, f, indent=2)
'''


class BlenderSensorRig:
    """Multi-modal inspection rig for 3D procedural models."""

    def __init__(self, blender_path: str | None = None):
        try:
            self.blender_path = blender_path or find_blender_executable()
        except Exception:
            self.blender_path = None

    def inspect_model(
        self,
        obj_path: Path | str,
        output_dir: Path | str | None = None,
        timeout_sec: float = 30.0,
    ) -> ModelInspectionResult:
        """Renders 4 snapshots and computes topological ground truth metrics."""
        obj_p = Path(obj_path).resolve()
        if not obj_p.exists():
            return ModelInspectionResult(
                success=False,
                metrics={},
                is_degenerate=True,
                degenerate_reason=f"Artifact file not found: {obj_p}",
            )

        if not self.blender_path or not Path(self.blender_path).exists():
            return ModelInspectionResult(
                success=False,
                metrics={},
                is_degenerate=True,
                degenerate_reason="Blender executable unavailable for empirical inspection",
            )

        out_dir = Path(output_dir).resolve() if output_dir else (obj_p.parent / f"{obj_p.stem}_inspection")
        out_dir.mkdir(parents=True, exist_ok=True)

        # Build execution script
        script_content = BLENDER_RIG_SCRIPT.replace("{OBJ_PATH}", str(obj_p).replace("\\", "/")).replace(
            "{OUTPUT_DIR}", str(out_dir).replace("\\", "/")
        )

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(script_content)
            tmp_py = f.name

        try:
            cmd = [self.blender_path, "-b", "--python", tmp_py]
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout_sec,
            )

            meta_file = out_dir / "metrics.json"
            if not meta_file.exists():
                return ModelInspectionResult(
                    success=False,
                    metrics={},
                    is_degenerate=True,
                    degenerate_reason=f"Blender failed to emit metrics.json. Stderr: {proc.stderr[:300]}",
                    raw_error=proc.stderr,
                )

            metrics = json.loads(meta_file.read_text(encoding="utf-8"))
            if not metrics.get("success", False):
                return ModelInspectionResult(
                    success=False,
                    metrics=metrics,
                    is_degenerate=True,
                    degenerate_reason=metrics.get("error", "Blender import error"),
                )

            # Snapshots map
            snapshots = {
                "iso": str(out_dir / "iso.png"),
                "front": str(out_dir / "front.png"),
                "top": str(out_dir / "top.png"),
                "detail": str(out_dir / "detail.png"),
            }
            # Verify which snapshot files actually exist
            existing_snapshots = {k: v for k, v in snapshots.items() if Path(v).exists()}

            # --- HARD MATHEMATICAL TOPOLOGY GATE (Pre-Critic Filter) ---
            vc = metrics.get("vertex_count", 0)
            fc = metrics.get("face_count", 0)
            oc = metrics.get("object_count", 0)
            vol = metrics.get("bounding_box", {}).get("volume", 0.0)
            mats = metrics.get("material_count", 0)

            is_degenerate = False
            degenerate_reasons = []

            if vc < 30:
                is_degenerate = True
                degenerate_reasons.append(f"Vertex count too low ({vc} < 30 threshold)")
            if fc < 10:
                is_degenerate = True
                degenerate_reasons.append(f"Face count too low ({fc} < 10 threshold)")
            if vol < 1e-4:
                is_degenerate = True
                degenerate_reasons.append(f"Bounding volume degenerate ({vol} ~= 0)")
            if oc < 2:
                # Flag as single-primitive alert unless vertex density is very high (sculpture)
                if vc < 200:
                    is_degenerate = True
                    degenerate_reasons.append(f"Single primitive assembly ({oc} object, {vc} vertices)")

            return ModelInspectionResult(
                success=True,
                metrics=metrics,
                snapshots=existing_snapshots,
                is_degenerate=is_degenerate,
                degenerate_reason="; ".join(degenerate_reasons) if is_degenerate else None,
            )

        except subprocess.TimeoutExpired:
            return ModelInspectionResult(
                success=False,
                metrics={},
                is_degenerate=True,
                degenerate_reason=f"Blender sensor rig timed out after {timeout_sec}s",
            )
        except Exception as e:
            return ModelInspectionResult(
                success=False,
                metrics={},
                is_degenerate=True,
                degenerate_reason=f"Inspection exception: {e}",
                raw_error=str(e),
            )
        finally:
            try:
                Path(tmp_py).unlink(missing_ok=True)
            except Exception:
                pass


class CSVSensorRig:
    """Ground-truth empirical inspection for tabular dataset synthesis."""

    @staticmethod
    def inspect_csv(csv_path: Path | str) -> CSVInspectionResult:
        p = Path(csv_path)
        if not p.exists() or p.stat().st_size == 0:
            return CSVInspectionResult(
                success=False,
                row_count=0,
                col_count=0,
                headers=[],
                null_ratio=1.0,
                numeric_columns=[],
                is_degenerate=True,
                degenerate_reason="File missing or 0 bytes",
            )

        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.reader(f)
                rows = [r for r in reader if r]

            if len(rows) < 2:
                return CSVInspectionResult(
                    success=False,
                    row_count=len(rows),
                    col_count=0,
                    headers=[],
                    null_ratio=1.0,
                    numeric_columns=[],
                    is_degenerate=True,
                    degenerate_reason="Less than 2 rows in CSV",
                )

            headers = [h.strip() for h in rows[0]]
            data_rows = rows[1:]
            total_cells = len(data_rows) * len(headers)
            null_count = 0
            numeric_cols = []

            for col_idx, col_name in enumerate(headers):
                numeric_count = 0
                for r in data_rows:
                    val = r[col_idx].strip() if col_idx < len(r) else ""
                    if not val:
                        null_count += 1
                    else:
                        try:
                            float(val)
                            numeric_count += 1
                        except ValueError:
                            pass
                if len(data_rows) > 0 and (numeric_count / len(data_rows)) > 0.8:
                    numeric_cols.append(col_name)

            null_ratio = null_count / total_cells if total_cells > 0 else 1.0
            is_degenerate = len(data_rows) < 3 or len(headers) < 2 or null_ratio > 0.4

            return CSVInspectionResult(
                success=True,
                row_count=len(data_rows),
                col_count=len(headers),
                headers=headers,
                null_ratio=round(null_ratio, 3),
                numeric_columns=numeric_cols,
                is_degenerate=is_degenerate,
                degenerate_reason="Empty dataset or excessive null values" if is_degenerate else None,
            )
        except Exception as e:
            return CSVInspectionResult(
                success=False,
                row_count=0,
                col_count=0,
                headers=[],
                null_ratio=1.0,
                numeric_columns=[],
                is_degenerate=True,
                degenerate_reason=f"CSV parse error: {e}",
            )


class CodeSensorRig:
    """Empirical AST inspection for generated Python modules."""

    @staticmethod
    def inspect_code(py_path: Path | str) -> CodeInspectionResult:
        p = Path(py_path)
        if not p.exists() or p.stat().st_size == 0:
            return CodeInspectionResult(
                success=False,
                syntax_valid=False,
                ast_nodes_count=0,
                defined_classes=[],
                defined_functions=[],
                is_degenerate=True,
                degenerate_reason="File missing or 0 bytes",
            )

        content = p.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(content)
            classes = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
            functions = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
            nodes = sum(1 for _ in ast.walk(tree))

            is_degenerate = nodes < 5 or (len(classes) == 0 and len(functions) == 0)
            return CodeInspectionResult(
                success=True,
                syntax_valid=True,
                ast_nodes_count=nodes,
                defined_classes=classes,
                defined_functions=functions,
                is_degenerate=is_degenerate,
                degenerate_reason="Trivial script with no functions or classes" if is_degenerate else None,
            )
        except SyntaxError as e:
            return CodeInspectionResult(
                success=False,
                syntax_valid=False,
                ast_nodes_count=0,
                defined_classes=[],
                defined_functions=[],
                is_degenerate=True,
                degenerate_reason=f"SyntaxError: {e}",
            )
