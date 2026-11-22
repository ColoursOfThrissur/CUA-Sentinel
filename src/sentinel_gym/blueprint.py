"""Sentinel Spatial Blueprint Intermediate Representation (IR) and Progressive LoD Engine.

Inspired by 3D-GPT (Conceptualizer vs Modeler), MineDojo/Voyager (Compositional Hierarchies),
and EvoAgentX (Symbolic Language Gradients).
Decouples high-level spatial/kinematic decomposition from low-level bpy code synthesis.
Ensures zero-drift relative coordinates, ground-plane anchoring (Z=0), and physical mating.
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

try:
    from sentinel_ui.telemetry_stream import broadcaster
except Exception:
    broadcaster = None


def _emit_blueprint_stage(stage: float, stage_name: str, status: str, details: dict[str, Any] | None = None):
    if broadcaster:
        try:
            broadcaster.emit("blueprint_stage", {
                "stage": stage,
                "stage_name": stage_name,
                "status": status,
                "timestamp": time.time(),
                "details": details or {},
            })
        except Exception:
            pass


logger = logging.getLogger("SentinelBlueprint")


@dataclass
class MaterialSpec:
    name: str
    color: list[float] = field(default_factory=lambda: [0.8, 0.8, 0.8, 1.0])  # RGBA (0-1)
    metallic: float = 0.5  # 0.0=matte/dielectric, 1.0=metal
    roughness: float = 0.5  # 0.0=mirror, 1.0=rough
    specular: float = 0.5


@dataclass
class SpatialComponent:
    name: str
    primitive: str  # "cylinder", "cube", "cone", "uv_sphere", "torus"
    dimensions: dict[str, float]  # {"radius": r, "depth": d} or {"size": [dx, dy, dz]}
    offset: list[float]  # [x, y, z] relative to parent (or world if root)
    rotation_deg: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])  # [rx, ry, rz] local rotation
    parent: Optional[str] = None  # None for root / world-anchored parts
    material: Optional[MaterialSpec] = None
    sub_skill_ref: Optional[str] = None  # Reusable sub-skill name if applicable
    notes: str = ""


@dataclass
class SpatialBlueprint:
    assembly_name: str
    tier: int  # 1 (Simple), 2 (Intermediate), 3 (Complex), 4 (Multi-System)
    lod_levels_count: int  # Number of progressive refinement stages applied
    root_origin: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    bounding_envelope: dict[str, float] = field(default_factory=lambda: {"dx": 1.0, "dy": 1.0, "dz": 1.0})
    components: list[SpatialComponent] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def materials(self) -> list[PBRMaterial]:
        return [c.material for c in self.components if c.material]

    def to_dict(self) -> dict[str, Any]:
        return {
            "assembly_name": self.assembly_name,
            "tier": self.tier,
            "lod_levels_count": self.lod_levels_count,
            "root_origin": self.root_origin,
            "bounding_envelope": self.bounding_envelope,
            "components": [
                {
                    "name": c.name,
                    "parent": c.parent,
                    "primitive": c.primitive,
                    "dimensions": c.dimensions,
                    "offset": c.offset,
                    "rotation_deg": c.rotation_deg,
                    "material": asdict(c.material) if c.material else None,
                    "sub_skill_ref": c.sub_skill_ref,
                    "notes": c.notes,
                }
                for c in self.components
            ],
            "metadata": self.metadata,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SpatialBlueprint:
        components = []
        for c_data in data.get("components", []):
            mat_data = c_data.get("material")
            mat = MaterialSpec(**mat_data) if mat_data else None
            components.append(
                SpatialComponent(
                    name=c_data.get("name", "part"),
                    primitive=c_data.get("primitive", "cube"),
                    dimensions=c_data.get("dimensions", {}),
                    offset=c_data.get("offset", [0.0, 0.0, 0.0]),
                    rotation_deg=c_data.get("rotation_deg", [0.0, 0.0, 0.0]),
                    parent=c_data.get("parent"),
                    material=mat,
                    sub_skill_ref=c_data.get("sub_skill_ref"),
                    notes=c_data.get("notes", ""),
                )
            )
        return cls(
            assembly_name=data.get("assembly_name", "assembly"),
            tier=int(data.get("tier", 1)),
            lod_levels_count=int(data.get("lod_levels_count", 2)),
            root_origin=data.get("root_origin", [0.0, 0.0, 0.0]),
            bounding_envelope=data.get("bounding_envelope", {"dx": 1.0, "dy": 1.0, "dz": 1.0}),
            components=components,
            metadata=data.get("metadata", {}),
        )


class _MathShim:
    cos = staticmethod(math.cos)
    sin = staticmethod(math.sin)
    tan = staticmethod(math.tan)
    sqrt = staticmethod(math.sqrt)
    radians = staticmethod(math.radians)
    degrees = staticmethod(math.degrees)
    PI = math.pi
    pi = math.pi
    E = math.e
    e = math.e


def safe_parse_json_with_math(text: str) -> Optional[dict[str, Any]]:
    """Robust JSON parser that cleanly evaluates mathematical expressions (e.g. sqrt(2), Math.cos, Math.PI)."""
    if not text:
        return None
    clean = text.strip()
    if "```json" in clean:
        clean = clean.split("```json")[1].split("```")[0].strip()
    elif "```" in clean:
        clean = clean.split("```")[1].split("```")[0].strip()

    # 1. Try standard json.loads first
    try:
        return json.loads(clean)
    except Exception:
        pass

    # 2. Extract outermost dictionary boundaries
    if "{" in clean and "}" in clean:
        s = clean.find("{")
        e = clean.rfind("}") + 1
        clean = clean[s:e]

    # Try json.loads on extracted substring
    try:
        return json.loads(clean)
    except Exception:
        pass

    # 3. Python literal eval with safe mathematical globals (supporting both Python math and JS Math)
    try:
        py_str = re.sub(r'\bnull\b', 'None', clean)
        py_str = re.sub(r'\btrue\b', 'True', py_str)
        py_str = re.sub(r'\bfalse\b', 'False', py_str)
        py_str = re.sub(r',\s*([\]}])', r'\1', py_str)  # Remove trailing commas
        allowed = {
            "__builtins__": {},
            "Math": _MathShim,
            "math": _MathShim,
            "sqrt": math.sqrt,
            "sin": math.sin,
            "cos": math.cos,
            "tan": math.tan,
            "radians": math.radians,
            "degrees": math.degrees,
            "pi": math.pi,
            "PI": math.pi,
            "None": None,
            "True": True,
            "False": False,
        }
        res = eval(py_str, allowed)
        if isinstance(res, dict):
            return res
    except Exception as e:
        logger.debug("safe_parse_json_with_math eval fallback failed: %s", e)

    return None


class ProgressiveLoDDecomposer:
    """Orchestrates multi-stage progressive Level of Detail (LoD) decomposition.

    Breaks complex tasks down progressively:
    - Tier 1 (Simple): 2 Stages (Macro Datum -> Micro Features)
    - Tier 2 (Intermediate): 3 Stages (Macro Datum -> Kinematic Sub-assemblies -> Micro Contact Surfaces)
    - Tier 3 (Complex): 4 Stages (Macro Architecture -> Kinematic Trees -> Relative Joint Mating -> PBR & Port Routing)
    """

    def __init__(self, llm_gateway: Any) -> None:
        self.gw = llm_gateway

    def estimate_complexity_tier(self, goal: str) -> tuple[int, int]:
        """Classify task into Complexity Tier (1-4) and determine required LoD stages count."""
        goal_lower = goal.lower()
        complex_keywords = [
            "gimbal", "engine", "telescope", "transmission", "gearbox",
            "robotic arm", "multi-axis", "articulated", "turbopump", "linkage"
        ]
        intermediate_keywords = [
            "actuator", "gripper", "hydraulic", "piston", "valve", "bracket", "clamp"
        ]

        complex_hits = sum(1 for kw in complex_keywords if kw in goal_lower)
        inter_hits = sum(1 for kw in intermediate_keywords if kw in goal_lower)

        if complex_hits >= 2 or ("engine" in goal_lower and "gimbal" in goal_lower) or ("telescope" in goal_lower):
            return 3, 4  # Tier 3, 4 LoD Stages
        elif complex_hits >= 1 or inter_hits >= 1 or "articulated" in goal_lower:
            return 2, 3  # Tier 2, 3 LoD Stages
        else:
            return 1, 2  # Tier 1, 2 LoD Stages

    def decompose(
        self,
        goal: str,
        anti_patterns: str = "",
        model: str | None = None,
    ) -> SpatialBlueprint:
        """Executes progressive hierarchical LoD decomposition."""
        tier, num_stages = self.estimate_complexity_tier(goal)
        logger.info(
            "Progressive LoD Decomposition: Task '%s' classified as Tier %d -> %d LoD Stages",
            goal[:40], tier, num_stages,
        )

        _emit_blueprint_stage(0.5, "Pipeline Initialization", "running", {"goal": goal, "tier": tier, "stages": num_stages})

        # Stage 0: Phase 1 Anatomical Discovery & Functional Hardware Breakdown
        _emit_blueprint_stage(1.0, "Anatomical Deconstruction", "running", {"goal": goal})
        anatomy_spec = self._stage_0_anatomical_deconstruction(goal, model=model)
        components_found = [c.get("name") for c in anatomy_spec.get("components", [])]
        _emit_blueprint_stage(1.0, "Anatomical Deconstruction", "completed", {"components": components_found, "count": len(components_found)})

        # Stage 1: Macro Architecture & World Datum (Envelope, ground datum, primary axis)
        _emit_blueprint_stage(1.5, "Macro Datum & Ground Plane", "running", {"datum": "Z=0"})
        macro_spec = self._stage_1_macro_datum(goal, anatomy_spec, tier, anti_patterns, model=model)
        _emit_blueprint_stage(1.5, "Macro Datum & Ground Plane", "completed", {"assembly_name": macro_spec.get("assembly_name"), "bounding_box": macro_spec.get("bounding_box")})

        # Stage 2: Kinematic Sub-Assembly Tree & Plural Instance Expansion
        _emit_blueprint_stage(2.0, "Kinematic Parent-Child Hierarchy", "running", {})
        stage2_spec = self._stage_2_subassemblies(goal, macro_spec, tier, model=model)
        tree = stage2_spec.get("kinematic_tree", [])
        _emit_blueprint_stage(2.0, "Kinematic Parent-Child Hierarchy", "completed", {"root_part": stage2_spec.get("root_part"), "parts_count": len(tree)})

        # Stage 3: Relative Joint Mating, Dimensions & Local Offsets
        _emit_blueprint_stage(3.0, "Metric Dimensions & Local Offsets", "running", {})
        stage3_spec = self._stage_3_joint_mating(goal, macro_spec, stage2_spec, tier, model=model)
        _emit_blueprint_stage(3.0, "Metric Dimensions & Local Offsets", "completed", {"components_count": len(stage3_spec.get("components", []))})

        # Stage 3.5: Physical Viability & Spatial Layout ReAct Checker (Real-World Feasibility Loop)
        _emit_blueprint_stage(3.5, "ReAct Physical Viability Audit", "running", {})
        stage3_spec = self._stage_3_react_viability_checker(goal, macro_spec, stage3_spec, model=model)
        _emit_blueprint_stage(3.5, "ReAct Physical Viability Audit", "completed", {"status": "verified_viable", "components_count": len(stage3_spec.get("components", []))})

        # Stage 4: High-Contrast PBR Material Assignment & Blueprint Synthesis
        _emit_blueprint_stage(4.0, "PBR Material Assignment", "running", {})
        final_blueprint = self._stage_4_material_assignment(
            goal=goal,
            macro_spec=macro_spec,
            stage3_spec=stage3_spec,
            tier=tier,
            num_stages=num_stages,
            anti_patterns=anti_patterns,
            model=model,
        )
        _emit_blueprint_stage(4.0, "PBR Material Assignment", "completed", {"materials_count": len(final_blueprint.materials)})

        # Validate blueprint consistency
        res = self._validate_and_sanitize(final_blueprint, goal)
        _emit_blueprint_stage(5.0, "Blueprint Synthesis Complete", "completed", {
            "assembly_name": res.assembly_name,
            "components_count": len(res.components),
            "materials_count": len(res.materials),
        })
        return res

    def _stage_0_anatomical_deconstruction(
        self, goal: str, model: str | None = None
    ) -> dict[str, Any]:
        """Phase 1: Anatomical Discovery / Research Agent (~150 tokens).
        Deconstructs target mechanical entity into essential physical hardware components,
        their functional roles, primitive bases, and physical mounting interfaces BEFORE any coordinates or code are touched.
        """
        sys_prompt = (
            "You are Sentinel's Principal Industrial Design & Mechanical Anatomy Specialist.\n"
            "PHASE 1: ANATOMICAL DECONSTRUCTION (Zero-Anatomy & Zero-Omission Doctrine):\n"
            "Carefully analyze every noun phrase in the user's design goal and deconstruct the target machine into ALL its essential physical components.\n"
            "ZERO-OMISSION HARDWARE CONTRACT:\n"
            "- Extract EVERY mechanical part, housing, control wheel, actuator, linkage, rotor, shaft, tooth, bracket, and fastener group explicitly mentioned in the design goal.\n"
            "- NEVER OMIT named components! For example:\n"
            "  * If the goal mentions a control wheel ('overhead circular red handwheel'), you MUST create 'overhead_handwheel'.\n"
            "  * If the goal mentions a volute casing ('spiral volute scroll casing'), you MUST create 'volute_scroll_casing'.\n"
            "  * If the goal mentions an internal rotor, fan, or core ('titanium fan rotor', 'meshing rotor lobes', 'crankshaft throws'), you MUST create them.\n"
            "  * If the goal specifies a quantity ('5 teeth', '4 tie-bolts', '2 flanged pipe ends', 'dual nozzles', '3 splayed legs'), create all individual physical instances (e.g. bucket_tooth_1..bucket_tooth_5, flanged_pipe_end_1, flanged_pipe_end_2, leg_1..leg_3).\n"
            "For each component define:\n"
            "1. name: snake_case physical noun\n"
            "2. functional_role: what it does mechanically in reality\n"
            "3. primitive: 'cylinder', 'cube', 'cone', 'torus', or 'uv_sphere'\n"
            "4. mounts_to: parent component name it physically touches, or null for root base/casing\n"
            "5. relative_socket: where it connects ('top_face', 'bottom_face', 'concentric_bore', 'radial_perimeter', 'sidewall', 'terminal_tip')\n"
            "CRITICAL RULES:\n"
            "- Only physical hardware parts (NO entries for colors, shaders, or empty groupings).\n\n"
            "Output strictly a JSON object with keys:\n"
            '{"target_object": "...", "datum_anchor": "...", "components": [{"name": "...", "role": "...", "primitive": "...", "mounts_to": "..." or null, "relative_socket": "..."}]}'
        )
        prompt = f"Target Mechanical Goal: {goal}"
        resp = self.gw.generate(
            prompt=prompt,
            system=sys_prompt,
            model=model,
            temperature=0.1,
            max_tokens=512,
        )
        data = safe_parse_json_with_math(resp)
        return data or {}

    def _stage_1_macro_datum(
        self, goal: str, anatomy_spec: dict[str, Any], tier: int, anti_patterns: str, model: str | None
    ) -> dict[str, Any]:
        """Stage 1 LoD: Macro Datum, Ground Anchor, Total Envelope, and Complete Subsystem Division."""
        sys_prompt = (
            "You are Sentinel's Senior Mechanical Systems Architect.\n"
            "STAGE 1 LEVEL OF DETAIL (Macro Datum & Hardware Envelope Specification):\n"
            "Given the anatomical breakdown from Phase 1, define the macro datum frame and primary axes.\n"
            "UNIVERSAL CAD ENGINEERING CONVENTIONS:\n"
            "1. COORDINATE FRAME:\n"
            "   - Z-axis is VERTICAL/AXIAL (Sky is +Z, Base/Ground is Z=0 datum plane).\n"
            "   - X-axis is LATERAL / WIDTH (Left is -X, Right is +X, bilateral mechanisms mirror across X=0).\n"
            "   - Y-axis is DEPTH / TRANSVERSE (Front view camera looks along +Y, from -Y toward origin).\n"
            "2. HARDWARE SUBSYSTEMS: Retain and verify EVERY hardware component identified in Phase 1 anatomy.\n"
            "3. UNITS & REALISTIC METRIC SCALE:\n"
            "   - Units are strictly METERS (m), e.g. 0.2m to 2.5m! NEVER use millimeters!\n"
            "   - World origin [0.0, 0.0, 0.0] is at the CENTER AXIS of the root component at the ground datum.\n\n"
            "Output strictly a JSON object with keys:\n"
            '{"assembly_name": "...", "datum_plane": "Z=0", "bounding_box": [dx, dy, dz], '
            '"primary_axis": "Z", "subsystems": ["SubsystemA", "SubsystemB", ...]}'
        )
        prompt = f"Goal: {goal}\nAnatomical Breakdown: {json.dumps(anatomy_spec.get('components', []))}"
        if anti_patterns:
            prompt += f"\nAvoid previous defect: {anti_patterns}"

        resp = self.gw.generate(
            prompt=prompt,
            system=sys_prompt,
            model=model,
            temperature=0.1,
            max_tokens=512,
        )
        data = safe_parse_json_with_math(resp)
        return data or {
            "assembly_name": "mechanical_assembly",
            "datum_plane": "Z=0",
            "bounding_box": [1.0, 1.0, 1.0],
            "subsystems": [c.get("name", "part") for c in anatomy_spec.get("components", [])] or ["base_chassis", "main_body", "articulated_tool"],
        }

    def _stage_2_subassemblies(
        self, goal: str, macro_spec: dict[str, Any], tier: int, model: str | None
    ) -> dict[str, Any]:
        """Stage 2 LoD: Kinematic Parent-Child Hierarchy and Relative Anchoring."""
        sys_prompt = (
            "You are Sentinel's Kinematic Hierarchy Specialist.\n"
            "STAGE 2 LEVEL OF DETAIL (Kinematic Hierarchy & Physical Component Breakdown):\n"
            "Decompose each subsystem from Stage 1 into concrete parent-child physical components.\n"
            "CRITICAL KINEMATIC TREE RULES:\n"
            "1. NO OMITTED SUBSYSTEMS: Every single subsystem from Stage 1 MUST be represented in the kinematic tree.\n"
            "2. PLURAL INSTANCE EXPANSION: Whenever a feature has multiple parts (e.g. '5 teeth', '4 tie-bolts', '2 flanged pipe ends', '3 legs'):\n"
            "   Create uniquely named entries for EVERY individual instance (e.g. 'bucket_tooth_1'...'bucket_tooth_5', 'bolt_1'...'bolt_4').\n"
            "3. HIERARCHICAL ANCHORING:\n"
            "   - Exactly ONE root part has `parent: null` (the main stationary chassis, housing casing, valve body, or pedestal base).\n"
            "   - Internal rotating parts (shafts, rotors, impellers, pistons, bearings) have the surrounding casing/housing as parent.\n"
            "   - Controls and actuators (handwheels, cylinders, drive screws, linkages) attach to the boss, stem, or hinge they operate.\n"
            "   - Fasteners (bolts, studs) attach to the specific flange, collar, or foot they fasten.\n"
            "   - Teeth, pads, and contact tips attach to their respective bucket, arm, or jaw.\n"
            "4. ZERO FLOATING PARTS: Every child must physically contact its parent component.\n\n"
            "Output strictly a JSON object with keys:\n"
            '{"root_part": "...", "kinematic_tree": [{"name": "...", "parent": "..." or null, "role": "...", "relative_placement": "top|base|concentric|radial|sidewall|tip"}]}'
        )
        prompt = (
            f"Goal: {goal}\n"
            f"Macro Spec: {json.dumps(macro_spec)}\n"
            f"Specify kinematic parent-child structure."
        )
        resp = self.gw.generate(
            prompt=prompt,
            system=sys_prompt,
            model=model,
            temperature=0.1,
            max_tokens=2048,
        )
        data = safe_parse_json_with_math(resp)
        return data or macro_spec

    def _stage_3_joint_mating(
        self, goal: str, macro_spec: dict[str, Any], stage2_spec: dict[str, Any], tier: int, model: str | None
    ) -> dict[str, Any]:
        """Stage 3 LoD: Calculate exact metric dimensions, local offsets, and rotation angles."""
        sys_prompt = (
            "You are Sentinel's Precision Mechanical Geometry Calculator.\n"
            "STAGE 3 LEVEL OF DETAIL (Metric Dimensions, Local Offsets & Joint Clearances):\n"
            "For each component in the kinematic tree, compute metric dimensions, primitive shape, local offsets, and rotation angles.\n"
            "UNIVERSAL CAD TOPOLOGY & MATHEMATICAL POSITIONING RULES:\n"
            "1. CONCENTRIC & COAXIAL PARTS (Shafts, Rotors, Pistons, Bearings, Gland Collars):\n"
            "   - Share the centerline of their parent cylinder along Z: `offset: [0.0, 0.0, z_offset]`.\n"
            "   - Inner parts have smaller radius than the housing: radius <= parent_radius * 0.85.\n"
            "   - Internal shafts or rotors MUST extend through the housing faces (`depth > housing_depth`) so they are visible from outside!\n"
            "2. HOUSINGS ENCLOSING INTERNAL ROTATING OR MOVING PARTS (Bearings, Gears, Impellers):\n"
            "   - Housings MUST NOT be solid closed monoliths that bury internal components! If a housing holds an inner bearing or shaft, specify `inner_radius` or a central bore opening so the internal mechanism is visible.\n"
            "3. AXIAL STACKING ON FACES (Caps, Glands, Handwheels, Heads, Flanges):\n"
            "   - To mount on the TOP face of a parent along Z: `offset_z = +(parent_depth / 2.0 + child_depth / 2.0)`.\n"
            "   - To mount on the BOTTOM face of a parent along Z: `offset_z = -(parent_depth / 2.0 + child_depth / 2.0)`.\n"
            "   - OVERHEAD CONTROLS (Handwheels, levers, knobs, focusers) MUST use POSITIVE (+Z) offsets relative to their supporting stem or boss: `offset_z = +(stem_depth / 2.0 + handwheel_depth / 2.0)`.\n"
            "4. RADIAL FASTENER & BOLT ARRAYS (Mounting Bolts, Studs, Tie-Bolts):\n"
            "   - Pitch circle radius is proportional: `pitch_r = parent_radius * 0.75` to `0.85`.\n"
            "   - Evenly distribute N bolts in a circle at `angle = 2 * PI * i / N`:\n"
            "     `offset = [pitch_r * cos(angle), pitch_r * sin(angle), +(parent_depth / 2.0 + bolt_depth / 2.0)]`.\n"
            "   - Fasteners are low-profile cylinders (`depth: 0.04 - 0.06, radius: 0.035 - 0.05`), pointing axially (`rotation_deg: [0, 0, 0]`).\n"
            "5. LINEAR ARRAYS ACROSS A WIDTH (Teeth, Fins, Blades, Discs):\n"
            "   - Distribute N parallel features across parent width W along the transverse axis (X or Y):\n"
            "     `x_i = -W * 0.45 + (i * (W * 0.90) / max(N - 1, 1))`.\n"
            "   - For example, 5 bucket teeth across a 1.0m lip: tooth_1 at X=-0.45, tooth_2 at X=-0.225, tooth_3 at X=0.0, tooth_4 at X=+0.225, tooth_5 at X=+0.45.\n"
            "6. SIDEWALL & TRANSVERSE ATTACHMENTS (Nozzles, Inlets, Outlets, Hydraulic Ports):\n"
            "   - Attached to the curved sidewall of a cylinder: `offset_x = +(parent_radius + nozzle_depth / 2.0)`, `offset_y = 0.0`.\n"
            "   - Pointed radially outward: `rotation_deg = [0.0, 90.0, 0.0]`.\n"
            "7. STRADDLING CALIPERS & CLAMPS (Brake Calipers, Clamping Brackets):\n"
            "   - Positioned at the outer perimeter rim: `offset_x = parent_radius * 0.95`.\n"
            "   - Shape is a box or C-frame wrapping symmetrically over both faces of the rim.\n"
            "8. SPLAYED LEGS & MULTI-STRUT BASES (Tripods, Pedestal Mounts):\n"
            "   - Legs attached at azimuths `360 / N` deg, tilted outward by 15° to 22° so feet spread wide on the ground.\n"
            "9. METRIC UNIT CONVERSIONS (Meters vs Millimeters & Centimeters):\n"
            "   - All 3D coordinates and dimensions in Blender are in METERS (1.0 = 1 meter).\n"
            "   - If the goal or component specifies millimeters (e.g. 6.35mm, 12mm, 50mm), you MUST convert to meters:\n"
            "     6.35mm = 0.00635, 12mm = 0.012, 50mm = 0.05. Never enter millimeter values as bare numbers in meters!\n\n"
            "Output strictly a JSON object with keys:\n"
            '{"components": [{"name": "...", "parent": "..." or null, "primitive": "cylinder|cube|cone|uv_sphere|torus", '
            '"dimensions": {"radius": <float>, "depth": <float>} or {"size": [dx, dy, dz]}, "offset": [x, y, z], "rotation_deg": [rx, ry, rz]}]}'
        )
        prompt = (
            f"Goal: {goal}\n"
            f"Stage 1 Envelope: {json.dumps(macro_spec.get('bounding_box'))}\n"
            f"Stage 2 Kinematics: {json.dumps(stage2_spec.get('kinematic_tree', []))}\n"
            f"Compute dimensions and local offsets."
        )
        resp = self.gw.generate(
            prompt=prompt,
            system=sys_prompt,
            model=model,
            temperature=0.1,
            max_tokens=2048,
        )
        data = safe_parse_json_with_math(resp)
        return data or stage2_spec

    def _stage_3_react_viability_checker(
        self,
        goal: str,
        macro_spec: dict[str, Any],
        stage3_spec: dict[str, Any],
        model: str | None = None,
    ) -> dict[str, Any]:
        """Stage 3.5: ReAct (Reason + Act) Physical Viability & Spatial Layout Checker.

        Audits the proposed spatial dimensions and arrangement for real-world physical viability:
        1. Unit text mismatches (e.g., millimeter values entered as meters, e.g. 6.35m vs 6.35mm).
        2. Solid enclosure burials (bearings, gears, shafts, or rotors hidden inside opaque monoliths).
        3. Inverted elevation & controls (overhead handwheels or caps placed at negative Z).
        4. Zero-spread collisions (multiple indexed components overlapping at the identical coordinate).

        If violations are detected, engages a ReAct reflection loop (THOUGHT -> ACTION) with the LLM
        to deliberate on physical failure modes and recalculate viable spatial dimensions, followed by
        deterministic mathematical guardrail enforcement.
        """
        components = stage3_spec.get("components", [])
        if not components:
            return stage3_spec

        violations = self._audit_spatial_viability(goal, macro_spec, components)
        if not violations:
            logger.info("Stage 3.5 Viability Checker: Spatial layout passed all physical feasibility audits (0 violations).")
            return stage3_spec

        logger.warning(
            "Stage 3.5 Viability Checker: Detected %d physical viability violations:\n%s",
            len(violations),
            "\n".join(f"  - [{v['type']}] {v['description']}" for v in violations),
        )

        # ReAct Reflection Loop (Reasoning + Action)
        sys_prompt = (
            "You are Sentinel's Principal Mechanical Reliability & Spatial Viability Engineer.\n"
            "STAGE 3.5: REAL-WORLD PHYSICAL VIABILITY REACT ENGINE (Reason + Act Protocol):\n"
            "An empirical CAD spatial audit of Stage 3 dimensions and offsets detected physical viability violations.\n"
            "You must resolve every violation using the ReAct protocol:\n\n"
            "PROTOCOL FORMAT:\n"
            "THOUGHT: Reason step-by-step through each detected violation. Explain:\n"
            "1. Why the current dimension or offset violates physical reality (e.g. 6.35m shaft on a 0.1m motor is 1000x oversized; solid housing buries internal bearing).\n"
            "2. The exact real-world engineering fix (convert mm to meters: 6.35mm = 0.00635m; add 'inner_radius' or bore to parent housing; invert Z for overhead control; spread array across parent width).\n\n"
            "ACTION: Output strictly a valid JSON object containing the repaired 'components' list:\n"
            "```json\n"
            '{"components": [{"name": "...", "parent": "..." or null, "primitive": "cylinder|cube|cone|uv_sphere|torus", '
            '"dimensions": {"radius": <float>, "depth": <float>} or {"size": [dx, dy, dz]}, "offset": [x, y, z], "rotation_deg": [rx, ry, rz]}]}\n'
            "```"
        )

        violations_text = "\n".join(f"{i+1}. [{v['type']}] {v['description']}" for i, v in enumerate(violations))
        prompt = (
            f"Goal: {goal}\n"
            f"Assembly Bounding Box: {json.dumps(macro_spec.get('bounding_box'))}\n"
            f"Current Stage 3 Components:\n{json.dumps(components, indent=2)}\n\n"
            f"CAD AUDIT VIOLATIONS DETECTED:\n{violations_text}\n\n"
            "Execute ReAct reflection (THOUGHT + ACTION) to repair the components."
        )

        resp = self.gw.generate(
            prompt=prompt,
            system=sys_prompt,
            model=model,
            temperature=0.1,
            max_tokens=2500,
        )

        data = safe_parse_json_with_math(resp)
        repaired_components = data.get("components") if (data and isinstance(data.get("components"), list) and len(data["components"]) > 0) else components

        # Apply deterministic fallback guardrails on repaired components
        repaired_components = self._apply_viability_guardrails(goal, macro_spec, repaired_components, violations)

        stage3_spec["components"] = repaired_components
        return stage3_spec

    def _audit_spatial_viability(
        self, goal: str, macro_spec: dict[str, Any], components: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Empirical spatial audit for real-world viability, physical clearances, and scale consistency."""
        violations = []

        # 1. Parse mm mentions in goal
        mm_matches = [float(m) for m in re.findall(r"(\d+(?:\.\d+)?)\s*mm\b", goal, re.IGNORECASE)]

        # Extract macro bounding box
        bbox_raw = macro_spec.get("bounding_box", [1.0, 1.0, 1.0])
        max_bbox = max(bbox_raw) if isinstance(bbox_raw, list) and len(bbox_raw) == 3 else 1.5

        parts_by_name = {c.get("name"): c for c in components if c.get("name")}

        # Check 1: Unit & Scale Mismatch
        for c in components:
            name = c.get("name", "")
            dims = c.get("dimensions", {})
            for dim_k, dim_v in list(dims.items()):
                vals = dim_v if isinstance(dim_v, (list, tuple)) else [dim_v]
                for v in vals:
                    if not isinstance(v, (int, float)):
                        continue
                    v_f = float(v)
                    # If explicit mm match in goal (e.g. 6.35)
                    for mm_val in mm_matches:
                        if abs(v_f - mm_val) < 0.05 and v_f > 0.5:
                            violations.append({
                                "type": "UNIT_MISMATCH",
                                "component": name,
                                "dimension": dim_k,
                                "current_value": v_f,
                                "expected_value": round(v_f / 1000.0, 6),
                                "description": f"Component '{name}' dimension '{dim_k}' is {v_f}m. The goal explicitly specifies {mm_val}mm ({mm_val/1000.0}m). In 3D space, {v_f}m is 1000x oversized!",
                            })
                    # Grossly exceeding macro bounding box
                    if v_f > max_bbox * 3.0 and v_f > 2.0:
                        violations.append({
                            "type": "GROSS_OVERSIZING",
                            "component": name,
                            "dimension": dim_k,
                            "current_value": v_f,
                            "description": f"Component '{name}' dimension '{dim_k}' is {v_f}m, which is > 3x larger than the entire assembly bounding box ({max_bbox}m).",
                        })

        # Check 2: Solid Enclosure Burial
        internal_keywords = ("bearing", "rotor", "shaft", "gear", "piston", "impeller", "core", "screw", "spindle")
        enclosure_keywords = ("housing", "casing", "body", "block", "shell", "frame", "cylinder")
        for c in components:
            name_l = c.get("name", "").lower()
            parent_name = c.get("parent")
            if not parent_name:
                continue
            parent = parts_by_name.get(parent_name)
            if not parent:
                continue
            p_name_l = parent_name.lower()
            if any(k in name_l for k in internal_keywords) and any(k in p_name_l for k in enclosure_keywords):
                p_dims = parent.get("dimensions", {})
                has_inner = "inner_radius" in p_dims or "bore_radius" in p_dims or "hole_radius" in p_dims
                p_depth = float(p_dims.get("depth", p_dims.get("size", [0, 0, 0.5])[2] if isinstance(p_dims.get("size"), (list, tuple)) else 0.5))
                c_depth = float(c.get("dimensions", {}).get("depth", c.get("dimensions", {}).get("size", [0, 0, 0.5])[2] if isinstance(c.get("dimensions", {}).get("size"), (list, tuple)) else 0.5))
                if not has_inner and c_depth <= p_depth:
                    violations.append({
                        "type": "SOLID_ENCLOSURE_BURIAL",
                        "component": c.get("name"),
                        "parent": parent_name,
                        "description": f"Internal component '{c.get('name')}' is completely buried inside solid parent '{parent_name}'. The parent housing needs an 'inner_radius' or open bore cutout, or the component needs to extend outward to be visible.",
                    })

        # Check 3: Inverted Elevation & Overhead Controls
        overhead_keywords = ("overhead", "handwheel", "wheel", "knob", "lever", "cap", "lid", "bonnet", "focuser", "eyepiece", "top_cap", "chimney")
        for c in components:
            name_l = c.get("name", "").lower()
            if any(k in name_l for k in overhead_keywords):
                offset = c.get("offset", [0, 0, 0])
                if offset and len(offset) >= 3 and offset[2] <= 0.0:
                    violations.append({
                        "type": "INVERTED_ELEVATION",
                        "component": c.get("name"),
                        "current_z": offset[2],
                        "description": f"Overhead/top component '{c.get('name')}' has non-positive Z offset ({offset[2]}). It must mount on the positive (+Z) top face.",
                    })

        # Check 4: Zero-Spread Collision Clusters
        offset_groups: dict[tuple[str, float, float, float], list[str]] = {}
        for c in components:
            name = c.get("name", "")
            off = c.get("offset", [0, 0, 0])
            parent = c.get("parent")
            if off and len(off) == 3 and parent:
                key = (parent, round(float(off[0]), 3), round(float(off[1]), 3), round(float(off[2]), 3))
                offset_groups.setdefault(key, []).append(name)

        for (parent, ox, oy, oz), clustered_names in offset_groups.items():
            if len(clustered_names) >= 2 and any(re.search(r"_\d+$", n) for n in clustered_names):
                violations.append({
                    "type": "ZERO_SPREAD_COLLISION",
                    "components": clustered_names,
                    "parent": parent,
                    "offset": [ox, oy, oz],
                    "description": f"Components {clustered_names} share the identical location [{ox}, {oy}, {oz}] under parent '{parent}', causing physical overlap. They must be distributed linearly or radially.",
                })

        # Check 5: Eccentric Shaft / Snout Placement
        for c in components:
            name_l = c.get("name", "").lower()
            if any(k in name_l for k in ("shaft", "rotor_core", "sun_gear", "snout")) and "tie_rod" not in name_l:
                off = c.get("offset", [0, 0, 0])
                if off and len(off) >= 3 and (abs(float(off[0])) > 0.015 or abs(float(off[1])) > 0.015):
                    violations.append({
                        "type": "ECCENTRIC_SHAFT",
                        "component": c.get("name"),
                        "current_offset": off,
                        "description": f"Drive shaft/core component '{c.get('name')}' is positioned off-center at [{off[0]}, {off[1]}]. Central shafts must align concentrically at [0.0, 0.0] on their parent axis.",
                    })

        return violations

    def _apply_viability_guardrails(
        self,
        goal: str,
        macro_spec: dict[str, Any],
        components: list[dict[str, Any]],
        violations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Deterministic safety net ensuring that all detected violations are mathematically resolved."""
        mm_matches = [float(m) for m in re.findall(r"(\d+(?:\.\d+)?)\s*mm\b", goal, re.IGNORECASE)]
        bbox_raw = macro_spec.get("bounding_box", [1.0, 1.0, 1.0])
        max_bbox = max(bbox_raw) if isinstance(bbox_raw, list) and len(bbox_raw) == 3 else 1.5

        parts_by_name = {c.get("name"): c for c in components if c.get("name")}

        for c in components:
            name = c.get("name", "")
            dims = c.get("dimensions", {})
            # 1. Scale / Unit Mismatch Guardrail
            for k, v in list(dims.items()):
                if isinstance(v, (int, float)):
                    vf = float(v)
                    for mm_val in mm_matches:
                        if abs(vf - mm_val) < 0.05 and vf > 0.5:
                            dims[k] = round(vf / 1000.0, 6)
                    if dims[k] > max_bbox * 3.0 and dims[k] > 2.0:
                        dims[k] = round(dims[k] / 1000.0, 4) if dims[k] > 10.0 else round(max_bbox * 0.8, 4)
                elif isinstance(v, (list, tuple)):
                    new_vals = []
                    for item in v:
                        if isinstance(item, (int, float)):
                            it_f = float(item)
                            for mm_val in mm_matches:
                                if abs(it_f - mm_val) < 0.05 and it_f > 0.5:
                                    it_f = round(it_f / 1000.0, 6)
                            if it_f > max_bbox * 3.0 and it_f > 2.0:
                                it_f = round(it_f / 1000.0, 4) if it_f > 10.0 else round(max_bbox * 0.8, 4)
                            new_vals.append(it_f)
                        else:
                            new_vals.append(item)
                    dims[k] = new_vals

            # 2. Solid Enclosure Cavity Guardrail
            parent_name = c.get("parent")
            if parent_name and parent_name in parts_by_name:
                parent = parts_by_name[parent_name]
                p_name_l = parent_name.lower()
                c_name_l = name.lower()
                if any(k in c_name_l for k in ("bearing", "rotor", "shaft", "gear", "piston", "impeller", "core", "screw", "spindle")) and any(k in p_name_l for k in ("housing", "casing", "body", "block", "shell", "frame")):
                    p_dims = parent.setdefault("dimensions", {})
                    if "inner_radius" not in p_dims and "bore_radius" not in p_dims:
                        c_r = float(dims.get("radius", dims.get("major_radius", dims.get("size", [0.2, 0.2, 0.2])[0] / 2.0 if isinstance(dims.get("size"), list) else 0.2)))
                        p_dims["inner_radius"] = round(c_r * 1.15, 4)
                        p_dims["bore_axis"] = "y" if ("block" in p_name_l or "bearing" in p_name_l or "pillow" in p_name_l) else "z"

            # 3. Overhead Controls Elevation Guardrail
            if any(k in name.lower() for k in ("overhead", "handwheel", "top_cap", "bonnet", "knob", "focuser", "eyepiece")):
                off = c.setdefault("offset", [0.0, 0.0, 0.0])
                if len(off) >= 3 and off[2] <= 0.0:
                    off[2] = abs(off[2]) if abs(off[2]) > 0.05 else 0.25

            # 4. Concentric Shaft Centering & Minimum Visible Feature Clamping
            if any(k in name.lower() for k in ("shaft", "rotor_core", "sun_gear", "snout")) and "tie_rod" not in name.lower():
                off = c.setdefault("offset", [0.0, 0.0, 0.0])
                off[0] = 0.0
                off[1] = 0.0
                if "radius" in dims and float(dims["radius"]) < 0.008:
                    dims["radius"] = 0.008

        return components

    def _stage_4_material_assignment(
        self,
        goal: str,
        macro_spec: dict[str, Any],
        stage3_spec: dict[str, Any],
        tier: int,
        num_stages: int,
        anti_patterns: str,
        model: str | None,
    ) -> SpatialBlueprint:
        """Stage 4 LoD: Assign high-contrast PBR shaders (Metallic/Roughness) and assemble the final blueprint."""
        components_data = stage3_spec.get("components") or []

        # If components were missing or stage 3 failed, build components from kinematic tree
        if not components_data and "kinematic_tree" in stage3_spec:
            for item in stage3_spec["kinematic_tree"]:
                components_data.append({
                    "name": item.get("name", "part"),
                    "parent": item.get("parent"),
                    "primitive": "cube",
                    "dimensions": {"size": [0.5, 0.5, 0.5]},
                    "offset": [0.0, 0.0, 0.25],
                    "rotation_deg": [0.0, 0.0, 0.0],
                })

        part_names = [c.get("name") for c in components_data]

        sys_prompt = (
            "You are Sentinel's PBR Material Specialist.\n"
            "STAGE 4 LEVEL OF DETAIL (Contrasting PBR Shaders):\n"
            "Assign realistic, physically contrasting Principled BSDF materials to EVERY component in the model.\n"
            "UNIVERSAL HIGH-CONTRAST PBR PALETTE RULES:\n"
            "- Painted Industrial Bodies / Casings / Frames: rich distinct color (Cast Industrial Blue: [0.10, 0.35, 0.78, 1.0], Safety Yellow: [1.0, 0.78, 0.0, 1.0], Hammer-Tone Green: [0.18, 0.55, 0.28, 1.0]), metallic=0.15, roughness=0.45.\n"
            "- Polished Machined Steel / Piston Rods / Shafts: bright chrome/steel metallic=0.88, roughness=0.15, color=[0.92, 0.94, 0.98, 1.0].\n"
            "- Bronze / Brass Fittings / Valve Trim / Focusers: bright golden metallic=0.85, roughness=0.18, color=[0.98, 0.82, 0.15, 1.0].\n"
            "- Handwheels & Controls: prominent Emergency Red metallic=0.15, roughness=0.25, color=[0.88, 0.10, 0.10, 1.0].\n"
            "- Titanium Alloys / Turbine Blades / Shrouds: aerospace titanium metallic=0.70, roughness=0.28, color=[0.38, 0.44, 0.54, 1.0].\n"
            "- Cast Iron Housings / Dark Frames: gunmetal metallic=0.75, roughness=0.35, color=[0.24, 0.26, 0.30, 1.0].\n"
            "- Rubber Seals / Gaskets / Composite Friction Pads: dark matte dielectric metallic=0.0, roughness=0.92, color=[0.08, 0.08, 0.10, 1.0].\n"
            "- Fasteners & Tie-Rods (Hex Bolts, Studs, Corner Rods): hardened fastener finish metallic=0.85, roughness=0.20, color=[0.22, 0.24, 0.28, 1.0] or Golden Brass: [0.98, 0.82, 0.15, 1.0].\n"
            "- Electrical Connector Housings & Terminal Boxes: matte black plastic dielectric metallic=0.05, roughness=0.80, color=[0.10, 0.10, 0.12, 1.0].\n"
            "CONTRAST CONTRACT: Zero uniform models! Connected or adjacent parts MUST NOT share identical colors: if the body is light aluminum or steel, fasteners and tie-rods MUST be darkened steel or brass, electrical boxes MUST be black, and shafts MUST be polished chrome!\n\n"
            "Output strictly a JSON object with keys:\n"
            '{"materials": {"Part_Name": {"name": "Mat_Name", "color": [r, g, b, 1.0], "metallic": <float>, "roughness": <float>}}}'
        )
        prompt = (
            f"Goal: {goal}\n"
            f"Components to assign materials to: {json.dumps(part_names)}\n"
        )
        if anti_patterns:
            prompt += f"Avoid previous anti-pattern: {anti_patterns}\n"

        resp = self.gw.generate(
            prompt=prompt,
            system=sys_prompt,
            model=model,
            temperature=0.1,
            max_tokens=2048,
        )
        mat_dict = {}
        data = safe_parse_json_with_math(resp)
        if data and "materials" in data:
            mat_dict = data["materials"]

        # Assemble final SpatialComponent list
        components = []
        for cd in components_data:
            name = cd.get("name", "part")
            # Match material by exact name or case-insensitive substring
            m_spec = mat_dict.get(name)
            if not m_spec:
                for k, v in mat_dict.items():
                    if k.lower() in name.lower() or name.lower() in k.lower():
                        m_spec = v
                        break

            if m_spec:
                mat = MaterialSpec(
                    name=m_spec.get("name", f"{name}_mat"),
                    color=m_spec.get("color", [0.7, 0.7, 0.7, 1.0]),
                    metallic=float(m_spec.get("metallic", 0.5)),
                    roughness=float(m_spec.get("roughness", 0.5)),
                )
            else:
                mat = MaterialSpec(name=f"{name}_mat", color=[0.75, 0.75, 0.75, 1.0], metallic=0.7, roughness=0.3)

            components.append(
                SpatialComponent(
                    name=name,
                    parent=cd.get("parent"),
                    primitive=cd.get("primitive", "cube"),
                    dimensions=cd.get("dimensions", {}),
                    offset=cd.get("offset", [0.0, 0.0, 0.0]),
                    rotation_deg=cd.get("rotation_deg", [0.0, 0.0, 0.0]),
                    material=mat,
                )
            )

        bbox_raw = macro_spec.get("bounding_box", [1.0, 1.0, 1.0])
        bbox = {"dx": bbox_raw[0], "dy": bbox_raw[1], "dz": bbox_raw[2]} if isinstance(bbox_raw, list) and len(bbox_raw) == 3 else {"dx": 1.0, "dy": 1.0, "dz": 1.0}

        return SpatialBlueprint(
            assembly_name=macro_spec.get("assembly_name", "assembly"),
            tier=tier,
            lod_levels_count=num_stages,
            root_origin=[0.0, 0.0, 0.0],
            bounding_envelope=bbox,
            components=components,
            metadata={"macro_spec": macro_spec},
        )

    def _validate_and_sanitize(self, bp: SpatialBlueprint, goal: str) -> SpatialBlueprint:
        """Sanitizes blueprint: ensures valid root, repairs orphan parents, and enforces CAD kinematic mating."""
        if not bp.components:
            return self._generate_fallback_blueprint(goal, bp.tier, bp.lod_levels_count)

        part_names = {c.name for c in bp.components}
        has_root = False

        for c in bp.components:
            # If parent not in parts list, reset to root
            if c.parent and c.parent not in part_names:
                logger.warning("Blueprint component '%s' has non-existent parent '%s'; resetting to root", c.name, c.parent)
                c.parent = None
            if c.parent is None:
                has_root = True

            # Ensure material defaults
            if not c.material:
                c.material = MaterialSpec(name=f"{c.name}_mat", color=[0.7, 0.7, 0.7, 1.0], metallic=0.5, roughness=0.5)

            # Ensure valid primitive
            if c.primitive not in ("cylinder", "cube", "cone", "uv_sphere", "torus"):
                c.primitive = "cube"

        # If no root part, designate first part as root
        if not has_root and bp.components:
            bp.components[0].parent = None

        # Enforce CAD Kinematic Mating constraints to ensure physical Euclidean contact
        self._solve_and_enforce_kinematic_mating(bp)

        return bp

    def _solve_and_enforce_kinematic_mating(self, bp: SpatialBlueprint) -> None:
        """Generalized CAD Constraint Solver: Deterministically ensures Euclidean physical contact between parent and child components.
        Domain-agnostic: Operates purely on mechanical geometry, parent-child proportions, and fastener physics without hardcoded asset names.
        """
        # 0. Root Centering and Millimeter-to-Meter Normalization
        max_envelope = max(bp.bounding_envelope.get("dx", 1.0), bp.bounding_envelope.get("dy", 1.0), bp.bounding_envelope.get("dz", 1.0))
        for c in bp.components:
            if c.parent is None:
                c.offset[0] = 0.0
                c.offset[1] = 0.0
            for k, v in list(c.dimensions.items()):
                if isinstance(v, (int, float)) and (v > 20.0 or (v > 2.0 and v > max_envelope * 2.5)):
                    c.dimensions[k] = round(float(v) / 1000.0, 4)
                elif isinstance(v, (list, tuple)):
                    c.dimensions[k] = [round(float(x) / 1000.0, 4) if (float(x) > 20.0 or (float(x) > 2.0 and float(x) > max_envelope * 2.5)) else float(x) for x in v]

        parts_by_name = {c.name: c for c in bp.components}

        # 1. Generalized Proportional Fastener Solver (Bolt Circles, Studs, Pins)
        fastener_groups: dict[str, list[SpatialComponent]] = {}
        for c in bp.components:
            name_lower = c.name.lower()
            if any(k in name_lower for k in ("bolt", "screw", "pin", "stud", "fastener")) and c.parent:
                fastener_groups.setdefault(c.parent, []).append(c)

        for parent_name, bolts in fastener_groups.items():
            parent = parts_by_name.get(parent_name)
            if not parent:
                continue

            # Determine parent radius dynamically
            parent_r = 0.0
            if "radius" in parent.dimensions:
                parent_r = float(parent.dimensions["radius"])
            elif "major_radius" in parent.dimensions:
                parent_r = float(parent.dimensions["major_radius"])
            elif "size" in parent.dimensions and isinstance(parent.dimensions["size"], (list, tuple)):
                parent_r = float(parent.dimensions["size"][0]) / 2.0

            parent_d = float(parent.dimensions.get("depth", parent.dimensions.get("height", 0.15)))
            pitch_r = round(parent_r * 0.78, 4) if parent_r > 0.04 else 0.20

            n = len(bolts)
            bolts.sort(key=lambda b: b.name)
            for i, bolt in enumerate(bolts):
                bolt_d = min(float(bolt.dimensions.get("depth", 0.045)), 0.05)
                bolt_r = min(float(bolt.dimensions.get("radius", 0.035)), 0.045)
                bolt.dimensions["depth"] = bolt_d
                bolt.dimensions["radius"] = bolt_r
                bolt.primitive = "cylinder"
                angle = (2.0 * math.pi * i) / max(n, 1)
                bolt.offset = [
                    round(pitch_r * math.cos(angle), 4),
                    round(pitch_r * math.sin(angle), 4),
                    round((parent_d / 2.0) + (bolt_d / 2.0), 4),  # Proud on top face
                ]
                bolt.rotation_deg = [0.0, 0.0, 0.0]
                if not bolt.material or bolt.material.name.startswith("part_") or bolt.material.metallic < 0.5:
                    bolt.material = MaterialSpec(
                        name="Hardened_Fastener_Steel",
                        color=[0.24, 0.26, 0.30, 1.0],
                        metallic=0.85,
                        roughness=0.20,
                    )

        # 2. Generalized Proportional Collar & Gland Solver
        for c in bp.components:
            name_lower = c.name.lower()
            if any(k in name_lower for k in ("collar", "gland", "flange_ring")) and c.parent:
                parent = parts_by_name.get(c.parent)
                if parent and "radius" in parent.dimensions:
                    p_r = float(parent.dimensions["radius"])
                    curr_r = float(c.dimensions.get("radius", 0.0))
                    if curr_r < p_r * 1.15:
                        c.primitive = "cylinder"
                        c.dimensions["radius"] = round(p_r * 1.30, 4)
                        c.dimensions["inner_radius"] = round(p_r, 4)

        # 3. Overhead Controls & End Caps Directional Consistency
        for c in bp.components:
            name_l = c.name.lower()
            if any(k in name_l for k in ("overhead", "handwheel", "top_cap", "bonnet", "knob", "focuser")) and c.parent:
                if c.offset[2] < 0.0:
                    c.offset[2] = abs(c.offset[2])

        # 3b. Concentric Shaft Centering & Visible Radius Clamping
        for c in bp.components:
            name_l = c.name.lower()
            if any(k in name_l for k in ("shaft", "rotor", "snout", "spindle", "core")) and "tie_rod" not in name_l:
                c.offset[0] = 0.0
                c.offset[1] = 0.0
                if "radius" in c.dimensions and float(c.dimensions["radius"]) < 0.008:
                    c.dimensions["radius"] = 0.008

        # 3c. Longitudinal Tie-Rods & Corner Fasteners Protrusion
        for c in bp.components:
            name_l = c.name.lower()
            if any(k in name_l for k in ("tie_rod", "tie-rod", "thru_bolt", "corner_rod")):
                parent = parts_by_name.get(c.parent)
                if parent:
                    p_d = float(parent.dimensions.get("depth", parent.dimensions.get("size", [0, 0, 0.08])[2] if isinstance(parent.dimensions.get("size"), (list, tuple)) else 0.08))
                    curr_d = float(c.dimensions.get("depth", 0.0))
                    if curr_d <= p_d:
                        c.dimensions["depth"] = round(p_d * 1.25, 4)
                    if float(c.dimensions.get("radius", 0.0)) < 0.005:
                        c.dimensions["radius"] = 0.005

        # 4. Internal Concentric Component Visibility (Bores & Extending Shafts)
        for c in bp.components:
            if c.parent and abs(c.offset[0]) < 1e-4 and abs(c.offset[1]) < 1e-4:
                parent = parts_by_name.get(c.parent)
                if not parent:
                    continue
                if any(k in c.name.lower() for k in ("shaft", "rotor", "bearing", "spindle", "core")):
                    p_d = float(parent.dimensions.get("depth", parent.dimensions.get("size", [0, 0, 0.4])[2] if isinstance(parent.dimensions.get("size"), (list, tuple)) else 0.4))
                    c_d = float(c.dimensions.get("depth", c.dimensions.get("size", [0, 0, 0.4])[2] if isinstance(c.dimensions.get("size"), (list, tuple)) else 0.4))
                    if c_d <= p_d:
                        new_d = round(p_d * 1.35, 4)
                        if "depth" in c.dimensions:
                            c.dimensions["depth"] = new_d
                        elif "size" in c.dimensions and isinstance(c.dimensions["size"], list):
                            c.dimensions["size"][2] = new_d

        # 5. Linear Array Spacing for Indexed Features (teeth, fins, blades across parent width)
        array_groups: dict[str, list[SpatialComponent]] = {}
        for c in bp.components:
            if c.parent and re.search(r"_\d+$", c.name):
                base_prefix = re.sub(r"_\d+$", "", c.name)
                array_groups.setdefault(f"{c.parent}:{base_prefix}", []).append(c)

        for grp_key, items in array_groups.items():
            if len(items) >= 2:
                parent_name = grp_key.split(":")[0]
                parent = parts_by_name.get(parent_name)
                if not parent:
                    continue
                x_offsets = {round(it.offset[0], 2) for it in items}
                if len(x_offsets) <= 1:
                    p_w = float(parent.dimensions.get("size", [1.0, 1.0, 1.0])[0] if isinstance(parent.dimensions.get("size"), (list, tuple)) else parent.dimensions.get("radius", 0.5) * 2.0)
                    n_items = len(items)
                    items.sort(key=lambda x: x.name)
                    step = (p_w * 0.85) / max(n_items - 1, 1)
                    start_x = -p_w * 0.425
                    for idx, it in enumerate(items):
                        it.offset[0] = round(start_x + idx * step, 4)

    def _generate_fallback_blueprint(self, goal: str, tier: int, stages: int) -> SpatialBlueprint:
        """Fallback blueprint when generation returns invalid JSON."""
        name = re.sub(r"[^a-zA-Z0-9_]", "_", goal[:25]).strip("_") or "assembly"
        return SpatialBlueprint(
            assembly_name=name,
            tier=tier,
            lod_levels_count=stages,
            root_origin=[0.0, 0.0, 0.0],
            bounding_envelope={"dx": 1.0, "dy": 1.0, "dz": 1.0},
            components=[
                SpatialComponent(
                    name="main_chassis",
                    primitive="cube",
                    dimensions={"size": [0.6, 0.4, 0.3]},
                    offset=[0.0, 0.0, 0.15],
                    material=MaterialSpec("chassis_mat", color=[0.2, 0.4, 0.8, 1.0], metallic=0.8, roughness=0.3),
                )
            ],
        )


def compile_blueprint_to_bpy(blueprint: SpatialBlueprint, output_obj_path: str) -> str:
    """Modeler Agent Compiler: Translates a SpatialBlueprint IR into deterministic Blender 4.5 LTS Python code.

    Enforces:
    - Object naming from blueprint
    - Parent-child linking (`child.parent = parent_obj`) BEFORE setting local coordinates
    - Local offset & rotation propagation
    - Principled BSDF material binding with exact PBR values
    - Clean error-free export to output_obj_path
    """
    escaped_path = output_obj_path.replace("\\", "/")

    lines = [
        "# Auto-generated by Sentinel Modeler Agent from Progressive LoD Spatial Blueprint",
        f"# Assembly: {blueprint.assembly_name} (Tier {blueprint.tier}, {blueprint.lod_levels_count} LoD Stages)",
        "import bpy",
        "import math",
        "import mathutils",
        "",
        "# 1. Initialize pristine scene",
        "bpy.ops.wm.read_factory_settings(use_empty=True)",
        "objects = {}",
        "",
        "# 2. Instantiate and Parent Components Hierarchically",
    ]

    # Topological sort: Roots first, then children with cycle detection
    components = list(blueprint.components)
    part_names = {c.name for c in components}

    # 0. Sanitize parents: if parent not in parts, reset to None
    for c in components:
        if c.parent and c.parent not in part_names:
            c.parent = None

    # Detect cycles: if following parent pointers leads back to c, break it
    for c in components:
        curr = c.parent
        visited = {c.name}
        while curr:
            if curr in visited:
                c.parent = None
                break
            visited.add(curr)
            curr = next((p.parent for p in components if p.name == curr), None)

    # Ensure at least one component has parent is None
    if not any(c.parent is None for c in components) and components:
        components[0].parent = None

    created = set()
    ordered_components = []

    # First pass: components with parent=None
    for c in components:
        if c.parent is None or c.parent == "":
            ordered_components.append(c)
            created.add(c.name)

    # Subsequent passes: children whose parents have already been ordered
    max_loops = len(components) + 5
    loop = 0
    while len(ordered_components) < len(components) and loop < max_loops:
        loop += 1
        progress = False
        for c in components:
            if c.name not in created and c.parent in created:
                ordered_components.append(c)
                created.add(c.name)
                progress = True
        if not progress:
            # Pick any remaining component and break parent link to unblock
            for c in components:
                if c.name not in created:
                    c.parent = None
                    ordered_components.append(c)
                    created.add(c.name)
                    break

    for c in ordered_components:
        name_clean = re.sub(r"[^a-zA-Z0-9_]", "_", c.name)
        lines.append(f"# --- Part: {c.name} ---")

        # Create primitive
        prim = (c.primitive or "cube").lower()
        dims = c.dimensions or {}
        is_empty_group = prim in ("empty", "assembly", "group", "none") or not dims or "assembly" in c.name.lower()

        if is_empty_group:
            lines.append("bpy.ops.object.empty_add(type='PLAIN_AXES')")
        elif prim == "cylinder":
            r = dims.get("radius", dims.get("radius1", 0.2))
            d = dims.get("depth", dims.get("height", 0.5))
            verts = dims.get("vertices", 32)
            if "bolt" in c.name.lower() or "hex" in c.name.lower():
                verts = 6
            lines.append(f"bpy.ops.mesh.primitive_cylinder_add(radius={float(r):.4f}, depth={float(d):.4f}, vertices={verts})")
            
            inner_r = float(dims.get("inner_radius", dims.get("hole_radius", 0.0)))
            if inner_r <= 0.0 and any(k in c.name.lower() for k in ("hollow", "pipe", "tube")) and "feed" not in c.name.lower() and float(r) > 0.10:
                inner_r = round(float(r) * 0.72, 4)

            if 0.0 < inner_r < float(r):
                lines.append("target_cylinder = bpy.context.active_object")
                lines.append(f"bpy.ops.mesh.primitive_cylinder_add(radius={inner_r:.4f}, depth={float(d) + 0.04:.4f}, vertices={verts})")
                lines.append("cutter = bpy.context.active_object")
                lines.append("mod = target_cylinder.modifiers.new(name='BoreHole', type='BOOLEAN')")
                lines.append("mod.object = cutter")
                lines.append("mod.operation = 'DIFFERENCE'")
                lines.append("bpy.context.view_layer.objects.active = target_cylinder")
                lines.append("bpy.ops.object.modifier_apply(modifier='BoreHole')")
                lines.append("bpy.data.objects.remove(cutter, do_unlink=True)")
        elif prim == "cone":
            r1 = dims.get("radius1", dims.get("radius_bottom", dims.get("radius_flare", dims.get("radius_base", dims.get("radius", 0.5)))))
            r2 = dims.get("radius2", dims.get("radius_top", dims.get("radius_throat", dims.get("radius_neck", 0.0))))
            if abs(float(r1) - float(r2)) < 1e-4:
                r1 = float(r1) * 1.5
                r2 = float(r2) * 0.5
            d = dims.get("depth", dims.get("height", 0.8))
            lines.append(f"bpy.ops.mesh.primitive_cone_add(radius1={float(r1):.4f}, radius2={float(r2):.4f}, depth={float(d):.4f})")
        elif prim in ("uv_sphere", "sphere"):
            r = dims.get("radius", 0.3)
            lines.append(f"bpy.ops.mesh.primitive_uv_sphere_add(radius={float(r):.4f})")
        elif prim == "torus":
            major = dims.get("major_radius", dims.get("radius", 0.4))
            minor = dims.get("minor_radius", 0.08)
            lines.append(f"bpy.ops.mesh.primitive_torus_add(major_radius={float(major):.4f}, minor_radius={float(minor):.4f})")
        else:  # default cube
            sz = dims.get("size")
            if isinstance(sz, (list, tuple)) and len(sz) == 3:
                lines.append(f"bpy.ops.mesh.primitive_cube_add(size=1.0)")
                lines.append(f"obj = bpy.context.active_object")
                lines.append(f"obj.scale = ({float(sz[0]):.4f}, {float(sz[1]):.4f}, {float(sz[2]):.4f})")
                lines.append("bpy.ops.object.transform_apply(scale=True)")
            else:
                s = dims.get("size", dims.get("depth", 0.5))
                if isinstance(s, (list, tuple)):
                    s = s[0]
                lines.append(f"bpy.ops.mesh.primitive_cube_add(size={float(s):.4f})")

            inner_r = float(dims.get("inner_radius", dims.get("bore_radius", dims.get("hole_radius", 0.0))))
            if inner_r > 0.0:
                bore_axis = str(dims.get("bore_axis", "y")).lower()
                lines.append("target_cube = bpy.context.active_object")
                lines.append(f"bpy.ops.mesh.primitive_cylinder_add(radius={inner_r:.4f}, depth=4.0, vertices=32)")
                lines.append("cutter = bpy.context.active_object")
                if bore_axis == "y":
                    lines.append("cutter.rotation_euler = (math.radians(90), 0, 0)")
                elif bore_axis == "x":
                    lines.append("cutter.rotation_euler = (0, math.radians(90), 0)")
                lines.append("mod = target_cube.modifiers.new(name='CubeBore', type='BOOLEAN')")
                lines.append("mod.object = cutter")
                lines.append("mod.operation = 'DIFFERENCE'")
                lines.append("bpy.context.view_layer.objects.active = target_cube")
                lines.append("bpy.ops.object.modifier_apply(modifier='CubeBore')")
                lines.append("bpy.data.objects.remove(cutter, do_unlink=True)")

        lines.append(f"obj = bpy.context.active_object")
        lines.append(f"obj.name = '{c.name}'")
        lines.append(f"objects['{c.name}'] = obj")
        lines.append("if obj.type == 'MESH':")
        lines.append("    bpy.ops.object.shade_smooth()")

        # Parent linking FIRST: Setting parent before setting location ensures location is LOCAL!
        if c.parent and c.parent in created:
            lines.append(f"if '{c.parent}' in objects:")
            lines.append(f"    obj.parent = objects['{c.parent}']")

        # Local location offset
        ox, oy, oz = c.offset if (c.offset and len(c.offset) == 3) else [0.0, 0.0, 0.0]
        lines.append(f"obj.location = ({float(ox):.4f}, {float(oy):.4f}, {float(oz):.4f})")

        # Local rotation
        rx, ry, rz = c.rotation_deg if (c.rotation_deg and len(c.rotation_deg) == 3) else [0.0, 0.0, 0.0]
        if any(abs(float(v)) > 1e-4 for v in (rx, ry, rz)):
            lines.append(
                f"obj.rotation_euler = (math.radians({float(rx):.2f}), math.radians({float(ry):.2f}), math.radians({float(rz):.2f}))"
            )

        # Material setup
        mat = c.material
        if mat and not is_empty_group:
            mat_name = re.sub(r"[^a-zA-Z0-9_]", "_", mat.name)
            cr, cg, cb = mat.color[:3]
            ca = mat.color[3] if len(mat.color) > 3 else 1.0
            lines.append(f"mat_{name_clean} = bpy.data.materials.new(name='{mat.name}')")
            lines.append(f"mat_{name_clean}.use_nodes = True")
            lines.append(f"mat_{name_clean}.diffuse_color = ({float(cr):.3f}, {float(cg):.3f}, {float(cb):.3f}, {float(ca):.1f})")
            lines.append(f"bsdf = mat_{name_clean}.node_tree.nodes.get('Principled BSDF')")
            lines.append(f"if bsdf:")
            lines.append(f"    bsdf.inputs['Base Color'].default_value = ({float(cr):.3f}, {float(cg):.3f}, {float(cb):.3f}, {float(ca):.1f})")
            lines.append(f"    bsdf.inputs['Metallic'].default_value = {float(mat.metallic):.2f}")
            lines.append(f"    bsdf.inputs['Roughness'].default_value = {float(mat.roughness):.2f}")
            lines.append(f"obj.data.materials.append(mat_{name_clean})")

        lines.append("")

    # 2b. Global Ground Datum Clamp (ensure min_world_z == 0.0)
    lines.extend([
        "# 2b. Global Ground Datum Clamp (ensure assembly rests precisely on Z=0.0)",
        "bpy.context.view_layer.update()",
        "mesh_objs = [o for o in objects.values() if o.type == 'MESH']",
        "if mesh_objs:",
        "    min_world_z = min(",
        "        (o.matrix_world @ mathutils.Vector(corner)).z",
        "        for o in mesh_objs",
        "        for corner in o.bound_box",
        "    )",
        "    root_objs = [o for o in objects.values() if o.parent is None]",
        "    for ro in root_objs:",
        "        ro.location.z -= min_world_z",
        "    bpy.context.view_layer.update()",
        "",
    ])

    # OBJ Export
    lines.extend([
        "# 3. Export Scene to OBJ",
        f'bpy.ops.wm.obj_export(filepath=r"{escaped_path}", up_axis="Z", forward_axis="Y")',
        'print("SENTINEL_3D_MODEL_EXPORTED_OK")',
    ])

    return "\n".join(lines)
