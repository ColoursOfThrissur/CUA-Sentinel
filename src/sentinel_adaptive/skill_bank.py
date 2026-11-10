"""Sentinel Skill Bank (Plasticity & Synthesis).
Distills verified attempt artifacts into modular, reusable skills and registers them into the dynamic Tool Registry.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from sentinel_core.db import SentinelDB
from sentinel_core.side_effects import EffectClass
from sentinel_broker.tool_registry import ToolRegistry


class SkillBank:
    def __init__(self, db: SentinelDB, skills_dir: Path | str | None = None):
        self.db = db
        self.skills_dir = Path(skills_dir) if skills_dir else Path("skills").resolve()
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    def distill_skill(
        self,
        name: str,
        description: str,
        code: str,
        effect_class: EffectClass | str = EffectClass.READ_ONLY,
        parameters_schema: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Saves a verified attempt code/artifact as a distilled reusable skill."""
        eff_str = effect_class.value if isinstance(effect_class, EffectClass) else effect_class
        schema = parameters_schema or {}
        meta = metadata or {}
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
                (skill_id, name, description, code, now, meta_str),
            )

        # Get updated version number
        row = self.db.execute_one("SELECT version FROM skills WHERE name = ?", (name,))
        v_num = row["version"] if row else 1

        # 2. Persist to filesystem as skill folder with SKILL.md
        skill_folder = self.skills_dir / name
        skill_folder.mkdir(parents=True, exist_ok=True)
        
        md_doc = f"""---
name: {name}
description: {description}
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

## Implementation
```python
{code}
```
"""
        (skill_folder / "SKILL.md").write_text(md_doc, encoding="utf-8")
        (skill_folder / "tool.py").write_text(code, encoding="utf-8")

        return {
            "id": skill_id,
            "name": name,
            "version": v_num,
            "description": description,
            "effect_class": eff_str,
            "folder": str(skill_folder),
        }

    def get_skill(self, name: str) -> dict[str, Any] | None:
        row = self.db.execute_one("SELECT * FROM skills WHERE name = ?", (name,))
        if not row:
            return None
        return dict(row)

    def list_skills(self) -> list[dict[str, Any]]:
        rows = self.db.execute_read("SELECT * FROM skills ORDER BY name ASC")
        return [dict(r) for r in rows]

    def register_distilled_skills_into_broker(self, registry: ToolRegistry):
        """Scans distilled skills and dynamically binds them to the Execution Broker."""
        skills = self.list_skills()
        for s in skills:
            meta = json.loads(s["metadata"])
            eff_class = meta.get("effect_class", EffectClass.READ_ONLY.value)
            schema = meta.get("parameters_schema", {})
            name = s["name"]
            code = s["code"]

            # Create dynamic execution scope
            def make_handler(skill_code: str):
                def handler(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
                    local_scope = {"params": params, "ctx": ctx, "result": None}
                    exec(skill_code, {}, local_scope)
                    return {"result": local_scope.get("result", "Skill executed successfully")}
                return handler

            registry.register(
                name=name,
                description=s["description"],
                effect_class=eff_class,
                parameters_schema=schema,
            )(make_handler(code))
