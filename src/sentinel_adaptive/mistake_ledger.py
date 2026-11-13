"""Sentinel Episodic Mistake Memory with Cross-Task Semantic Retrieval.
Captures failure signatures, provides LLM-driven root-cause classification,
and aggregates cross-task heuristics to prime new attempts against historic defects.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from typing import Any

from sentinel_core.db import SentinelDB
from sentinel_core.vector_index import VectorIndex

logger = logging.getLogger("SentinelMistakeMemory")


class MistakeMemory:
    def __init__(self, db: SentinelDB, vector_index: VectorIndex | None = None):
        self.db = db
        self.vector_index = vector_index or VectorIndex()
        self._hydrate_vector_index()

    def _hydrate_vector_index(self):
        try:
            rows = self.db.execute_read(
                "SELECT id, task_id, error_category, error_signature, context, lesson_learned FROM mistake_ledger ORDER BY id DESC LIMIT 200"
            )
            for r in rows:
                meta = dict(r)
                text = f"{r.get('error_category', '')} {r.get('error_signature', '')} {r.get('lesson_learned', '')} {r.get('context', '')}"
                self.vector_index.upsert(str(r["id"]), text, metadata=meta)
        except Exception as e:
            logger.debug("Mistake vector index hydration skipped: %s", e)

    def record_mistake(
        self,
        task_id: str,
        attempt_id: str,
        error_category: str,
        error_signature: str,
        context: dict[str, Any] | str,
        lesson_learned: str,
    ) -> int:
        ctx_str = json.dumps(context) if isinstance(context, dict) else str(context)
        now = time.time()
        with self.db.transaction() as c:
            c.execute(
                """
                INSERT INTO mistake_ledger (task_id, attempt_id, error_category, error_signature, context, lesson_learned, ts)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (task_id, attempt_id, error_category, error_signature, ctx_str, lesson_learned, now),
            )
            row_id = c.lastrowid

        # Index in semantic vector memory
        try:
            self.vector_index.upsert(
                str(row_id),
                f"{error_category} {error_signature} {lesson_learned} {ctx_str}",
                metadata={
                    "id": row_id,
                    "task_id": task_id,
                    "error_category": error_category,
                    "error_signature": error_signature,
                    "lesson_learned": lesson_learned,
                    "domain": context.get("domain", "") if isinstance(context, dict) else "",
                },
            )
        except Exception as e:
            logger.debug("Failed to index mistake in vector index: %s", e)

        return row_id

    def classify_and_record_semantic_mistake(
        self,
        task_id: str,
        attempt_id: str,
        raw_traceback: str,
        llm_gateway: Any | None = None,
        domain: str = "general",
    ) -> int:
        """Uses LLM reasoning to classify failure modes into structured semantic taxonomy."""
        category = "EXECUTION_DEFECT"
        lesson = raw_traceback[:300]

        if llm_gateway and raw_traceback.strip():
            try:
                system_prompt = (
                    "You are Sentinel's Root-Cause Diagnostician. Analyze the following software/tool traceback. "
                    "Output EXACTLY two lines:\n"
                    "CATEGORY: <One of: DEPRECATED_API, MISSING_ATTRIBUTE, SYNTAX_DEFECT, IMPORT_ERROR, RESOURCE_EXHAUSTION, LOGIC_ERROR>\n"
                    "LESSON: <One clear, imperative sentence stating what code change must be made to fix it>\n"
                )
                analysis = llm_gateway.generate(
                    prompt=f"Traceback:\n```\n{raw_traceback[:1500]}\n```",
                    system=system_prompt,
                    temperature=0.1,
                    max_tokens=256,
                )
                for line in analysis.splitlines():
                    if line.startswith("CATEGORY:"):
                        category = line.replace("CATEGORY:", "").strip()
                    elif line.startswith("LESSON:"):
                        lesson = line.replace("LESSON:", "").strip()
            except Exception as e:
                logger.warning("Semantic classification failed (%s), using raw traceback", e)

        # Signature extraction from traceback
        lines = [ln.strip() for ln in raw_traceback.splitlines() if ln.strip()]
        last_line = lines[-1] if lines else "ErrorOccurred"
        sig = last_line[:80].replace("'", "").replace('"', "")

        return self.record_mistake(
            task_id=task_id,
            attempt_id=attempt_id,
            error_category=category,
            error_signature=sig,
            context={"traceback_excerpt": raw_traceback[:500], "domain": domain},
            lesson_learned=lesson,
        )

    def get_task_mistakes(self, task_id: str) -> list[dict[str, Any]]:
        rows = self.db.execute_read(
            "SELECT * FROM mistake_ledger WHERE task_id = ? ORDER BY id ASC",
            (task_id,),
        )
        return [dict(r) for r in rows]

    def get_cross_task_lessons(self, domain: str = "", limit: int = 2, query: str = "") -> list[dict[str, Any]]:
        """Retrieves bounded, deduplicated lessons learned across past tasks in the same domain.
        Uses semantic vector similarity if query is provided, otherwise falls back to frequency SQL.
        Strictly capped at top entries and bounded token footprint.
        """
        if query and self.vector_index.count() > 0:
            def _filter(meta: dict[str, Any]) -> bool:
                if not domain:
                    return True
                return domain.lower() in str(meta.get("domain", "")).lower() or not meta.get("domain")

            matches = self.vector_index.query(query, top_k=limit, filter_fn=_filter)
            if matches:
                bounded = []
                for m in matches:
                    meta = m.get("metadata", {})
                    raw_lesson = (meta.get("lesson_learned") or m.get("text", "")).strip().replace("\n", " ")
                    bounded.append({
                        "error_category": meta.get("error_category", "SEMANTIC_HEURISTIC"),
                        "error_signature": meta.get("error_signature", ""),
                        "lesson_learned": raw_lesson[:120] + ("..." if len(raw_lesson) > 120 else ""),
                    })
                return bounded

        # Fallback to frequency SQL retrieval
        if domain:
            kw = f"%{domain}%"
            rows = self.db.execute_read(
                "SELECT error_category, error_signature, lesson_learned, COUNT(*) as freq "
                "FROM mistake_ledger "
                "WHERE context LIKE ? OR lesson_learned LIKE ? "
                "GROUP BY error_category, error_signature "
                "ORDER BY freq DESC, id DESC LIMIT ?",
                (kw, kw, limit),
            )
        else:
            rows = self.db.execute_read(
                "SELECT error_category, error_signature, lesson_learned, COUNT(*) as freq "
                "FROM mistake_ledger "
                "GROUP BY error_category, error_signature "
                "ORDER BY freq DESC, id DESC LIMIT ?",
                (limit,),
            )
        bounded = []
        for r in rows:
            d = dict(r)
            raw_lesson = (d.get("lesson_learned") or "").strip().replace("\n", " ")
            d["lesson_learned"] = raw_lesson[:120] + ("..." if len(raw_lesson) > 120 else "")
            bounded.append(d)
        return bounded

    def format_anti_pattern_prompt(self, task_id: str, domain: str = "", query: str = "") -> str:
        """Combines task-specific anti-patterns with strictly bounded cross-task memory."""
        task_mistakes = self.get_task_mistakes(task_id)
        # Bounded cross-task memory: max 2 items, retrieved semantically if query is given
        cross_lessons = self.get_cross_task_lessons(domain, limit=2, query=query)

        if not task_mistakes and not cross_lessons:
            return ""

        lines = [
            "### ADAPTIVE EPISODIC MEMORY (ANTI-PATTERNS & PREVENTATIVE LESSONS)",
        ]

        # Prioritize immediate attempt failures
        if task_mistakes:
            lines.append("Immediate Task Defect Feedback:")
            for idx, m in enumerate(task_mistakes, 1):
                clean_sig = str(m.get("error_signature", ""))[:80]
                clean_les = str(m.get("lesson_learned", ""))[:140].replace("\n", " ")
                lines.append(f"  {idx}. [{m['error_category']}] Signature: {clean_sig}")
                lines.append(f"     Lesson: {clean_les}")

        # Append cross-task historic wisdom (capped to 2)
        if cross_lessons:
            lines.append("\nCross-Task Historic Heuristics (Do NOT repeat):")
            for c in cross_lessons[:2]:
                lines.append(f"  - [{c.get('error_category', 'ERROR')}] {c.get('lesson_learned', '')}")

        lines.append("\nCRITICAL: Satisfy all required adaptations above on this attempt.")
        return "\n".join(lines)
