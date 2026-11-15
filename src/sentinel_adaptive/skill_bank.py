"""Sentinel Skill Bank (Plasticity, Synthesis & Compound Composition).
Distills verified attempt artifacts into modular, reusable skills, supports semantic discovery,
and registers skills into the dynamic Tool Registry for compound agent execution.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from sentinel_core.db import SentinelDB
from sentinel_core.side_effects import EffectClass
from sentinel_broker.tool_registry import ToolRegistry
from sentinel_core.vector_index import VectorIndex

logger = logging.getLogger("SentinelSkillBank")


def derive_semantic_slug(goal: str, domain: str = "") -> str:
    """Generates a clean, canonical semantic slug from a user goal for compound skill reuse."""
    text = goal.lower()
    # Remove filler prompt prefixes and common fluff
    fillers = [
        "write python code implementing an", "write python code implementing a",
        "write a python script that", "write python code implementing",
        "write python code for", "write python script for", "write python",
        "implement an", "implement a", "implementing an", "implementing a",
        "synthesize a 3d", "synthesize 3d", "synthesize an", "synthesize a", "synthesize and verify",
        "create a 3d", "create 3d", "create an", "create a", "build a 3d", "build a", "build an",
        "generate a synthetic", "generate a", "generate an", "generate",
        "in blender", "using blender", "with get and put methods", "data structure",
        "and assert tests", "and test cases"
    ]
    for f in fillers:
        text = text.replace(f, " ")

    # Tokenize and filter stop words
    raw_tokens = re.findall(r"[a-z0-9]+", text)
    stop_words = {
        "the", "of", "and", "or", "for", "with", "to", "in", "on", "at", "by", "from",
        "an", "a", "is", "it", "this", "that", "all", "its", "are", "as", "3d"
    }
    tokens = [t for t in raw_tokens if len(t) > 1 and t not in stop_words]

    slug_core = "_".join(tokens[:4])
    if not slug_core:
        slug_core = f"{domain or 'custom'}_{int(time.time()) % 10000}"

    return f"skill_{slug_core}"


class SkillBank:
    """Manages persistent skills, semantic catalog discovery, and dynamic broker execution."""

    def __init__(
        self,
        db: SentinelDB,
        skills_dir: Path | str | None = None,
        tool_registry: ToolRegistry | None = None,
        vector_index: VectorIndex | None = None,
    ):
        self.db = db
        self.skills_dir = Path(skills_dir) if skills_dir else Path("skills").resolve()
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.tool_registry = tool_registry
        self.vector_index = vector_index or VectorIndex()
        self._hydrate_vector_index()

    def _hydrate_vector_index(self):
        try:
            for s in self.list_skills():
                meta_str = s.get("metadata", "{}")
                text = f"{s.get('name', '')} {s.get('description', '')} {s.get('code', '')[:200]}"
                self.vector_index.upsert(s["name"], text, metadata=s)
        except Exception as e:
            logger.debug("Skill vector index hydration skipped: %s", e)

    def purge_empty_skills(self) -> int:
        """Purges corrupted 0-byte or trivial skills (<50 bytes) from catalog and vector memory."""
        rows = self.db.execute_read("SELECT name, code FROM skills WHERE length(trim(code)) < 50")
        purged_count = 0
        with self.db.transaction() as c:
            for r in rows:
                c.execute("DELETE FROM skills WHERE name = ?", (r["name"],))
                folder = self.skills_dir / r["name"]
                if folder.exists():
                    shutil.rmtree(folder, ignore_errors=True)
                purged_count += 1

        if purged_count > 0:
            logger.info("Purged %d corrupted/empty skills from SkillBank.", purged_count)
            self._hydrate_vector_index()
        return purged_count

    def distill_skill(
        self,
        name: str,
        description: str,
        code: str,
        domain: str = "",
        effect_class: EffectClass | str = EffectClass.READ_ONLY,
        parameters_schema: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        registry: ToolRegistry | None = None,
    ) -> dict[str, Any]:
        """Saves a verified attempt code/artifact as a distilled reusable skill."""
        cleaned_code = (code or "").strip()
        if not cleaned_code:
            raise ValueError(f"Cannot distill skill '{name}': code payload cannot be empty")

        eff_str = effect_class.value if isinstance(effect_class, EffectClass) else effect_class
        schema = parameters_schema or {}
        meta = metadata or {}
        meta["domain"] = domain
        meta["effect_class"] = eff_str
        meta["parameters_schema"] = schema
        meta_str = json.dumps(meta)
        now = time.time()
        skill_id = f"skill_{name}_{int(now)}"

        # 1. Persist to SQLite
        with self.db.transaction() as c:
            c.execute(
                """
                INSERT INTO skills (id, name, description, code, version, verified_at, metadata)
                VALUES (?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    code = excluded.code,
                    version = skills.version + 1,
                    verified_at = excluded.verified_at,
                    metadata = excluded.metadata
                """,
                (skill_id, name, description, cleaned_code, now, meta_str),
            )

        # Get updated version number
        row = self.db.execute_one("SELECT version FROM skills WHERE name = ?", (name,))
        v_num = row["version"] if row else 1

        # 2. Persist to filesystem as skill folder with SKILL.md
        skill_folder = self.skills_dir / name
        skill_folder.mkdir(parents=True, exist_ok=True)

        blueprint_section = ""
        if "spatial_blueprint" in meta and meta["spatial_blueprint"]:
            blueprint_section = f"\n## Spatial Blueprint\n```json\n{json.dumps(meta['spatial_blueprint'], indent=2)}\n```\n"

        md_doc = f"""---
name: {name}
description: {description}
domain: {domain}
version: {v_num}
verified_at: {now}
effect_class: {eff_str}
---
# {name} (v{v_num})
{description}

## Parameters
```json
{json.dumps(schema, indent=2)}
```
{blueprint_section}
## Implementation
```python
{cleaned_code}
```
"""
        (skill_folder / "SKILL.md").write_text(md_doc, encoding="utf-8")
        (skill_folder / "tool.py").write_text(cleaned_code, encoding="utf-8")

        skill_record = {
            "id": skill_id,
            "name": name,
            "version": v_num,
            "domain": domain,
            "description": description,
            "effect_class": eff_str,
            "folder": str(skill_folder),
            "code": code,
            "metadata": meta_str,
        }

        # 3. Dynamically sync into broker tool registry if available
        target_reg = registry or self.tool_registry
        if target_reg:
            self.register_single_skill_into_registry(skill_record, target_reg)

        # 4. Index in semantic vector memory
        try:
            vec_text = f"{name} {description} {domain} {code[:200]}"
            self.vector_index.upsert(name, vec_text, metadata=skill_record)
        except Exception as e:
            logger.debug("Failed to index skill in vector index: %s", e)

        logger.info("Distilled skill '%s' (v%d) into SkillBank.", name, v_num)
        return skill_record

    def get_skill(self, name: str) -> dict[str, Any] | None:
        """Retrieves skill record by name."""
        row = self.db.execute_one("SELECT * FROM skills WHERE name = ?", (name,))
        if not row:
            return None
        return dict(row)

    def list_skills(self) -> list[dict[str, Any]]:
        """Lists all distilled skills in the catalog."""
        rows = self.db.execute_read("SELECT * FROM skills ORDER BY name ASC")
        return [dict(r) for r in rows]

    def find_relevant_skills(
        self,
        query: str,
        domain: str | None = None,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        """
        Searches Skill Bank for previously verified skills matching the query or domain.
        Used by the prompt scaffolder for compound plasticity and agent skill composition.
        """
        all_skills = self.list_skills()
        if not all_skills:
            return []

        clean_query = query.lower()
        stop_words = {
            "a", "an", "the", "and", "or", "in", "on", "at", "to", "for", "with", "of",
            "write", "create", "build", "implement", "implementing", "synthesize", "generate",
            "python", "code", "script", "blender", "3d", "data", "model", "methods", "structure"
        }
        raw_words = re.findall(r"[a-z0-9_]+", clean_query)
        keywords = [w for w in raw_words if len(w) > 2 and w not in stop_words]

        # Semantic vector similarity scores
        vector_scores: dict[str, float] = {}
        if self.vector_index.count() > 0:
            v_matches = self.vector_index.query(clean_query, top_k=len(all_skills))
            for vm in v_matches:
                vector_scores[vm["id"]] = vm["score"]

        scored: list[tuple[float, dict[str, Any]]] = []
        for s in all_skills:
            score = 0.0
            s_name = s["name"].lower()
            s_desc = s["description"].lower()
            s_code = s["code"].lower()
            meta = {}
            try:
                meta = json.loads(s.get("metadata", "{}"))
            except Exception:
                pass
            s_domain = meta.get("domain", "")

            # Strict domain filtering if domain parameter is specified
            if domain:
                if s_domain and s_domain != domain:
                    continue
                score += 3.0

            kw_score = 0.0
            for kw in keywords:
                if kw in s_name:
                    kw_score += 8.0
                if kw in s_desc:
                    kw_score += 4.0
                if kw in s_code:
                    kw_score += 1.5

            v_sim = vector_scores.get(s["name"], 0.0)

            # Require keyword match or semantic cosine similarity above threshold
            if keywords and kw_score == 0.0 and v_sim < 0.12:
                continue

            score += kw_score + (max(0.0, v_sim) * 10.0)

            if score > 0:
                s_copy = dict(s)
                s_copy["domain"] = s_domain
                s_copy["score"] = round(score, 3)
                s_copy["vector_similarity"] = round(v_sim, 4)
                s_copy["folder"] = str(self.skills_dir / s["name"])
                scored.append((score, s_copy))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored[:limit]]

    def execute_skill(
        self,
        name: str,
        params: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Executes a previously distilled skill safely in a controlled environment.
        Supports 3D Blender mesh synthesis, data CSV generation, and Python code/tests.
        """
        skill = self.get_skill(name)
        if not skill:
            raise KeyError(f"Skill '{name}' not found in SkillBank.")

        params = params or {}
        ctx = context or {}
        code = skill["code"]
        meta = {}
        try:
            meta = json.loads(skill.get("metadata", "{}"))
        except Exception:
            pass
        domain = meta.get("domain", "")

        # 1. 3D Blender Mesh Skill
        if domain == "3d" or "bpy" in code:
            from sentinel_broker.organs.blender import _run_blender_script, find_blender_executable
            output_obj = params.get("output_obj_path") or params.get("output_path") or f"workspaces/{name}.obj"
            run_code = code
            if "bpy.ops.wm.obj_export" in run_code and output_obj:
                escaped_out = str(Path(output_obj).resolve()).replace("\\", "/")
                run_code = re.sub(
                    r'bpy\.ops\.wm\.obj_export\(filepath=r?["\'].*?["\']\)',
                    f'bpy.ops.wm.obj_export(filepath=r"{escaped_out}")',
                    run_code,
                )
            blender_exe = find_blender_executable()
            res = _run_blender_script(blender_exe, run_code, output_obj, timeout=60.0)
            return {
                "success": res.get("exit_code") == 0,
                "tool_result": res,
                "artifact_path": output_obj,
            }

        # 2. Data / CSV Generation Skill
        elif domain == "data":
            output_path = params.get("output_artifact_path") or params.get("output_path") or f"workspaces/{name}.csv"
            with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as tf:
                tf.write(code)
                tmp_p = tf.name
            try:
                proc = subprocess.run([sys.executable, tmp_p], capture_output=True, text=True, timeout=20.0)
                art_exists = Path(output_path).exists()
                if not art_exists and proc.stdout and "," in proc.stdout:
                    Path(output_path).write_text(proc.stdout.strip(), encoding="utf-8")
                    art_exists = True
                return {
                    "success": proc.returncode == 0,
                    "stdout": proc.stdout,
                    "stderr": proc.stderr,
                    "artifact_path": output_path if art_exists else None,
                }
            finally:
                Path(tmp_p).unlink(missing_ok=True)

        # 3. Code / Algorithm / Module Skill
        else:
            # Check for in-memory execution first (backward compatibility with lightweight scripts setting 'result')
            local_scope = {"params": params, "ctx": ctx, "result": None}
            try:
                exec(code, {}, local_scope)
                if local_scope.get("result") is not None:
                    return {
                        "success": True,
                        "result": local_scope["result"],
                        "stdout": "Executed in in-memory scope",
                        "exit_code": 0,
                    }
            except Exception:
                pass

            with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as tf:
                run_code = code
                if params.get("invoke_class") and params.get("invoke_args"):
                    run_code += f"\ninst = {params['invoke_class']}(**{params['invoke_args']})\n"
                tf.write(run_code)
                tmp_p = tf.name
            try:
                proc = subprocess.run([sys.executable, tmp_p], capture_output=True, text=True, timeout=20.0)
                return {
                    "success": proc.returncode == 0,
                    "result": proc.stdout.strip() or "Executed successfully",
                    "stdout": proc.stdout,
                    "stderr": proc.stderr,
                    "exit_code": proc.returncode,
                }
            finally:
                Path(tmp_p).unlink(missing_ok=True)

    def register_single_skill_into_registry(self, skill: dict[str, Any], registry: ToolRegistry):
        """Binds an individual distilled skill into the Execution Broker tool registry."""
        name = skill["name"]
        meta = {}
        try:
            meta = json.loads(skill.get("metadata", "{}"))
        except Exception:
            pass

        eff_class = meta.get("effect_class", EffectClass.READ_ONLY.value)
        schema = meta.get("parameters_schema", {
            "output_path": "str | None (target artifact path)",
            "invoke_args": "dict | None (parameters to pass to skill function/class)",
        })

        def skill_handler(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
            return self.execute_skill(name, params, ctx)

        registry.register(
            name=name,
            description=skill.get("description", f"Distilled skill: {name}"),
            effect_class=eff_class,
            parameters_schema=schema,
        )(skill_handler)
        logger.debug("Bound dynamic skill '%s' to ToolRegistry.", name)

    def register_distilled_skills_into_broker(self, registry: ToolRegistry):
        """
        Scans all distilled skills in the Skill Bank, binds them individually into the broker,
        and registers the universal 'execute_skill' organ for compound composition.
        """
        skills = self.list_skills()
        for s in skills:
            self.register_single_skill_into_registry(s, registry)

        # Register Universal Organ: execute_skill
        @registry.register(
            name="execute_skill",
            description="Executes a previously verified skill from Sentinel's Skill Bank with parameter bindings.",
            effect_class=EffectClass.NON_IDEMPOTENT_WRITE,
            parameters_schema={
                "skill_name": "str (name of skill to invoke, e.g. skill_lru_cache)",
                "params": "dict (parameters and artifact path overrides)",
            },
        )
        def handle_execute_skill(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
            skill_name = params.get("skill_name", "")
            skill_params = params.get("params", {})
            return self.execute_skill(skill_name, skill_params, ctx)

        self.tool_registry = registry
        logger.info("Bound %d distilled skills + 'execute_skill' organ into Broker ToolRegistry.", len(skills))
