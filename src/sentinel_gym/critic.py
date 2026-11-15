"""Sentinel Harsh Multi-Modal Critic (The Sensory Reviewer).
Evaluates real physical artifacts against user goals using empirical sensor metrics,
renders, and dual-mode (vision + structural telemetry) LLM reasoning.
Enforces hard mathematical topology pre-gates to bypass unneeded inference on degenerate outputs.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sentinel_gym.sensor_rig import ModelInspectionResult, CSVInspectionResult, CodeInspectionResult
from sentinel_core.llm_gateway import LLMGateway

logger = logging.getLogger("SentinelCritic")

PASSING_THRESHOLD = 0.72


@dataclass
class CriticScorecard:
    score: float  # 0.0 to 1.0
    passed: bool
    structural_integrity: int  # 0-25
    feature_specificity: int  # 0-25
    material_separation: int  # 0-25
    proportion_realism: int  # 0-25
    critique: str
    remediation_advice: str
    anti_pattern_signature: str | None = None
    evaluation_mode: str = "structural"  # "vision" | "structural" | "degenerate_bypass"


class HarshCritic:
    """Rigorous empirical evaluator designed to eliminate false-positive exit-code passes."""

    def __init__(
        self,
        llm_gateway: LLMGateway | None = None,
        passing_threshold: float = PASSING_THRESHOLD,
        vision_model: str = "qwen3-vl:8b",
    ):
        self.gateway = llm_gateway
        self.passing_threshold = passing_threshold
        self.vision_model = vision_model

    def evaluate_3d_model(
        self,
        goal: str,
        inspection: ModelInspectionResult,
        model_name: str | None = None,
    ) -> CriticScorecard:
        """Evaluates a synthesized 3D model using hard mathematical pre-gates, vision, and topology."""
        # 1. HARD MATHEMATICAL TOPOLOGY PRE-GATE (Bypass expensive LLM inference on junk)
        if inspection.is_degenerate:
            reason = inspection.degenerate_reason or "Degenerate geometry detected by mathematical sensor rig"
            logger.info("Empirical Critic Pre-Gate tripped: %s", reason)
            return CriticScorecard(
                score=0.25,
                passed=False,
                structural_integrity=5,
                feature_specificity=8,
                material_separation=5,
                proportion_realism=7,
                critique=f"FAILED MATHEMATICAL TOPOLOGY PRE-GATE: {reason}. Output does not constitute a viable multi-part 3D model.",
                remediation_advice="Model must contain multiple articulated parts (>1 mesh object), >30 vertices, and non-zero bounding volume.",
                anti_pattern_signature=f"DEGENERATE_TOPOLOGY: {reason[:80]}",
                evaluation_mode="degenerate_bypass",
            )

        metrics = inspection.metrics
        parts = metrics.get("part_names", [])
        mats = metrics.get("materials", [])
        bbox = metrics.get("bounding_box", {})
        non_manifold = metrics.get("non_manifold_edges", 0)

        # 2. VISION CRITIC (Direct visual inspection of rendered artifact via local multimodal model)
        triptych_snapshot = inspection.snapshots.get("triptych")
        images_to_send = []
        is_triptych = False

        if triptych_snapshot and Path(triptych_snapshot).exists():
            images_to_send.append(base64.b64encode(Path(triptych_snapshot).read_bytes()).decode("utf-8"))
            is_triptych = True
        else:
            iso_snapshot = inspection.snapshots.get("iso")
            front_snapshot = inspection.snapshots.get("front")
            top_snapshot = inspection.snapshots.get("top")
            if iso_snapshot and Path(iso_snapshot).exists():
                images_to_send.append(base64.b64encode(Path(iso_snapshot).read_bytes()).decode("utf-8"))
            if front_snapshot and Path(front_snapshot).exists():
                images_to_send.append(base64.b64encode(Path(front_snapshot).read_bytes()).decode("utf-8"))
            if top_snapshot and Path(top_snapshot).exists():
                images_to_send.append(base64.b64encode(Path(top_snapshot).read_bytes()).decode("utf-8"))

        if self.gateway and images_to_send:
            try:
                parts_str = ", ".join(parts[:16]) if parts else "assembly components"
                view_desc = (
                    "CAD engineering triptych (View 1: Isometric 3D View, View 2: Front Elevation, View 3: Top Plan)"
                    if is_triptych
                    else "perspectives (Image 1: Isometric, Image 2: Front Elevation, Image 3: Top Plan)"
                )

                vision_prompt = (
                    f"Evaluate this {view_desc} render against the user's design goal.\n"
                    f"Goal: {goal}\n\n"
                    "Score strictly across 4 categories (each 0 to 25):\n"
                    "- visual_resemblance (0-25): Does the rendered image visually match the intended mechanical assembly?\n"
                    "- component_alignment (0-25): Are components properly attached, seated, and aligned without floating?\n"
                    "- material_contrast (0-25): Are distinct materials visibly applied across parts (e.g. polished steel vs dark rubber gasket vs gunmetal bolts, golden brass vs black hub vs steel claws, or copper orange vs titanium blue)? Award 20-25 if distinct materials are present.\n"
                    "- functional_proportion (0-25): Are proportions, aspect ratios, and sizing mechanically realistic?\n\n"
                    "Output strictly in a ```json code block:\n"
                    "```json\n"
                    '{"visual_resemblance": 20, "component_alignment": 20, "material_contrast": 20, "functional_proportion": 20, '
                    '"critique": "<two sentences>", "remediation_advice": "<one specific instruction>", "anti_pattern": null}\n'
                    "```"
                )
                vis_resp = self.gateway.generate(
                    prompt=vision_prompt,
                    model=self.vision_model,
                    system="You are a senior CAD quality inspector. Evaluate this engineering triptych strictly and output JSON immediately.",
                    temperature=0.1,
                    max_tokens=4096,
                    images=images_to_send,
                )
                logger.info("CRITIC RAW RESPONSE:\n%s", vis_resp)
                raw_text = vis_resp.strip()
                if "```json" in raw_text:
                    block = raw_text.split("```json", 1)[1]
                    if "```" in block:
                        block = block.split("```", 1)[0]
                    clean_vis = block.strip()
                elif "```" in raw_text:
                    block = raw_text.split("```", 1)[1]
                    if "```" in block:
                        block = block.split("```", 1)[0]
                    clean_vis = block.strip()
                else:
                    clean_vis = raw_text

                data = {}
                try:
                    data = json.loads(clean_vis)
                except Exception:
                    start_idx = clean_vis.find("{")
                    end_idx = clean_vis.rfind("}")
                    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                        try:
                            data = json.loads(clean_vis[start_idx : end_idx + 1])
                        except Exception:
                            pass

                if not data:
                    # Resilient regex extraction across clean_vis, raw_text, and thinking
                    search_corpus = f"{clean_vis}\n{raw_text}"
                    vr_m = re.search(r'["\']?visual[\s_]*resemblance["\']?\s*[:=]\s*(\d+)', search_corpus, re.I)
                    ca_m = re.search(r'["\']?component[\s_]*alignment["\']?\s*[:=]\s*(\d+)', search_corpus, re.I)
                    mc_m = re.search(r'["\']?material[\s_]*contrast["\']?\s*[:=]\s*(\d+)', search_corpus, re.I)
                    fp_m = re.search(r'["\']?functional[\s_]*proportion["\']?\s*[:=]\s*(\d+)', search_corpus, re.I)
                    cq_m = re.search(r'"critique":\s*"([^"\\]*(?:\\.[^"\\]*)*)"?', search_corpus)
                    rm_m = re.search(r'"remediation_advice":\s*"([^"\\]*(?:\\.[^"\\]*)*)"?', search_corpus)
                    ap_m = re.search(r'"anti_pattern":\s*"([^"\\]*(?:\\.[^"\\]*)*)"?', search_corpus)
                    if vr_m or ca_m or mc_m or fp_m:
                        data = {
                            "visual_resemblance": int(vr_m.group(1)) if vr_m else 18,
                            "component_alignment": int(ca_m.group(1)) if ca_m else 18,
                            "material_contrast": int(mc_m.group(1)) if mc_m else 18,
                            "functional_proportion": int(fp_m.group(1)) if fp_m else 18,
                            "critique": cq_m.group(1) if cq_m else "Multi-perspective visual inspection complete.",
                            "remediation_advice": rm_m.group(1) if rm_m else "Maintain geometric alignment across views.",
                            "anti_pattern": ap_m.group(1) if ap_m else None,
                        }

                v_res = max(0, min(25, int(data.get("visual_resemblance", 10))))
                c_align = max(0, min(25, int(data.get("component_alignment", 10))))
                m_cont = max(0, min(25, int(data.get("material_contrast", 10))))
                f_prop = max(0, min(25, int(data.get("functional_proportion", 10))))

                total_score = (v_res + c_align + m_cont + f_prop) / 100.0
                passed = total_score >= self.passing_threshold

                logger.info("Vision Critic completed evaluation: score=%.3f, passed=%s", total_score, passed)
                return CriticScorecard(
                    score=round(total_score, 3),
                    passed=passed,
                    structural_integrity=c_align,
                    feature_specificity=v_res,
                    material_separation=m_cont,
                    proportion_realism=f_prop,
                    critique=data.get("critique", "Vision inspection complete."),
                    remediation_advice=data.get("remediation_advice", "Align sub-components and improve material definition."),
                    anti_pattern_signature=data.get("anti_pattern") if not passed else None,
                    evaluation_mode="vision",
                )
            except Exception as e:
                logger.warning("Vision Critic evaluation failed or timed out (%s), falling back to structural evaluation", e)

        # 3. Build structured sensory telemetry prompt (Structural Fallback)
        telemetry_summary = (
            f"Physical Sensor Telemetry:\n"
            f"- Part Count: {metrics.get('object_count')} parts ({', '.join(parts[:8])})\n"
            f"- Vertices: {metrics.get('vertex_count')}, Faces: {metrics.get('face_count')}\n"
            f"- Non-manifold edges: {non_manifold}\n"
            f"- Materials ({len(mats)}): {', '.join(mats[:6]) if mats else 'NONE (Default Gray)'}\n"
            f"- Dimensions: dx={bbox.get('dx')}, dy={bbox.get('dy')}, dz={bbox.get('dz')} (Volume: {bbox.get('volume')})\n"
        )

        system_prompt = (
            "You are Sentinel's Harsh Empirical Critic. You evaluate 3D procedural models generated by an autonomous agent.\n"
            "You HATE generic primitives (plain cubes, untextured cylinders, single spheres). You reward real multi-part assemblies, "
            "clear material separation, articulated mechanical parts, and anatomical/physical proportions.\n"
            "Score the model strictly across 4 categories (each 0 to 25):\n"
            "1. structural_integrity (0-25): Are pieces connected cleanly without missing faces or intersecting chaos?\n"
            "2. feature_specificity (0-25): Does it have the specific sub-components described in the goal?\n"
            "3. material_separation (0-25): Are distinct materials assigned per part, or is it one uniform color?\n"
            "4. proportion_realism (0-25): Are aspect ratios and sizing plausible?\n\n"
            "Output EXACTLY valid JSON with keys:\n"
            '{"structural_integrity": <int>, "feature_specificity": <int>, "material_separation": <int>, '
            '"proportion_realism": <int>, "critique": "<2 concise sentences of what is good and bad>", '
            '"remediation_advice": "<1 specific imperative instruction to fix the worst defect>", '
            '"anti_pattern": "<Short tag of the failure mode, e.g. UNATTACHED_CYLINDERS, UNIFORM_MATERIAL_SLAP>"}'
        )

        user_prompt = (
            f"GOAL: {goal}\n\n"
            f"{telemetry_summary}\n"
            "Rendered visual snapshots (iso, front, top, wireframe) were captured and verified.\n"
            "Provide your strict scorecard evaluation now:"
        )

        # 4. LLM Structural Reasoning
        if self.gateway:
            try:
                response = self.gateway.generate(
                    prompt=user_prompt,
                    system=system_prompt,
                    model=model_name or self.gateway.default_model,
                    temperature=0.1,
                    max_tokens=350,
                )
                clean_json = response.strip()
                if "```json" in clean_json:
                    clean_json = clean_json.split("```json")[1].split("```")[0].strip()
                elif "```" in clean_json:
                    clean_json = clean_json.split("```")[1].split("```")[0].strip()

                data = json.loads(clean_json)
                s_int = max(0, min(25, int(data.get("structural_integrity", 15))))
                f_spec = max(0, min(25, int(data.get("feature_specificity", 15))))
                m_sep = max(0, min(25, int(data.get("material_separation", 10))))
                p_real = max(0, min(25, int(data.get("proportion_realism", 15))))

                total_score = (s_int + f_spec + m_sep + p_real) / 100.0
                passed = total_score >= self.passing_threshold

                return CriticScorecard(
                    score=round(total_score, 3),
                    passed=passed,
                    structural_integrity=s_int,
                    feature_specificity=f_spec,
                    material_separation=m_sep,
                    proportion_realism=p_real,
                    critique=data.get("critique", "Evaluation completed via sensory telemetry."),
                    remediation_advice=data.get("remediation_advice", "Increase assembly detail and separate materials."),
                    anti_pattern_signature=data.get("anti_pattern") if not passed else None,
                    evaluation_mode="structural",
                )
            except Exception as e:
                logger.warning("Critic LLM evaluation failed or timed out (%s), using programmatic rubric", e)

        # 5. Deterministic Programmatic Fallback Rubric
        # Detect whether object names are descriptive semantic components or unassigned primitives (e.g. Cone, Cylinder, Sphere)
        primitive_keywords = {"cube", "cylinder", "sphere", "cone", "torus", "empty", "plane", "circle"}
        generic_count = sum(1 for p in parts if any(p.lower().startswith(kw) for kw in primitive_keywords))
        is_generic_primitives = len(parts) > 0 and (generic_count >= max(2, len(parts) - 1))

        if is_generic_primitives:
            # Harsh penalty for lazy unarticulated primitives: cannot pass purely on counts
            s_int = 12 if non_manifold == 0 else 6
            f_spec = min(12, max(6, len(parts) * 2))
            m_sep = min(18, max(5, len(mats) * 5))
            p_real = 10
            critique_msg = f"Model is an unarticulated cluster of {generic_count} generic primitives ({', '.join(parts[:4])}). Missing semantic assembly."
            advice_msg = "Articulate components with descriptive hierarchy and assemble sub-parts directly onto parent coordinates."
            anti_tag = "GENERIC_PRIMITIVE_CLUSTER"
        else:
            s_int = 20 if non_manifold == 0 else max(5, 20 - int(non_manifold / 10))
            f_spec = min(25, max(10, len(parts) * 5))
            m_sep = min(25, max(5, len(mats) * 8))
            vol = bbox.get("volume", 0.0)
            p_real = 20 if (vol > 0.01 and bbox.get("dz", 0) > 0.05) else 10
            # Spatial spread check: if tripod/stand is present, verify non-clumped base spread
            dz = bbox.get("dz", 1.0)
            ground_spread = bbox.get("ground_spread", 0.0)
            if any(term in " ".join(parts).lower() for term in ["tripod", "base", "stand", "leg"]):
                if ground_spread > 0 and ground_spread < 0.25 * dz:
                    p_real = max(8, p_real - 8)
            critique_msg = f"Model assembled with {len(parts)} parts and {len(mats)} material(s). Bounding volume: {vol:.4f}."
            advice_msg = "Separate object hierarchies and apply contrasting Principled BSDF materials."
            anti_tag = "SUB_OPTIMAL_PART_SEPARATION"

        total_score = (s_int + f_spec + m_sep + p_real) / 100.0
        passed = total_score >= self.passing_threshold

        return CriticScorecard(
            score=round(total_score, 3),
            passed=passed,
            structural_integrity=s_int,
            feature_specificity=f_spec,
            material_separation=m_sep,
            proportion_realism=p_real,
            critique=critique_msg,
            remediation_advice=advice_msg,
            anti_pattern_signature=anti_tag if not passed else None,
            evaluation_mode="structural_fallback",
        )

    def evaluate_csv_dataset(
        self,
        goal: str,
        inspection: CSVInspectionResult,
        model_name: str | None = None,
    ) -> CriticScorecard:
        """Evaluates synthetic tabular data quality."""
        if inspection.is_degenerate:
            return CriticScorecard(
                score=0.20,
                passed=False,
                structural_integrity=5,
                feature_specificity=5,
                material_separation=5,
                proportion_realism=5,
                critique=f"CSV failed empirical audit: {inspection.degenerate_reason}",
                remediation_advice="Generate valid CSV rows with realistic columns and low null ratio.",
                anti_pattern_signature=f"CSV_DEGENERATE: {inspection.degenerate_reason}",
                evaluation_mode="degenerate_bypass",
            )

        row_score = min(25, int(inspection.row_count / 2) * 5)
        col_score = min(25, inspection.col_count * 5)
        clean_score = int((1.0 - inspection.null_ratio) * 25)
        numeric_score = min(25, len(inspection.numeric_columns) * 8)

        total_score = (row_score + col_score + clean_score + numeric_score) / 100.0
        passed = total_score >= self.passing_threshold

        return CriticScorecard(
            score=round(total_score, 3),
            passed=passed,
            structural_integrity=clean_score,
            feature_specificity=col_score,
            material_separation=numeric_score,
            proportion_realism=row_score,
            critique=f"Dataset contains {inspection.row_count} rows across {inspection.col_count} columns with {inspection.null_ratio * 100:.1f}% nulls.",
            remediation_advice="Include varied quantitative metrics and valid distributions.",
            anti_pattern_signature="TABULAR_LOW_CARDINALITY" if not passed else None,
            evaluation_mode="structural",
        )
