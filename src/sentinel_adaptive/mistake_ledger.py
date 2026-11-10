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

logger = logging.getLogger("SentinelMistakeMemory")


class MistakeMemory:
    def __init__(self, db: SentinelDB):
        self.db = db

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
            return c.lastrowid

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

    def get_cross_task_lessons(self, domain: str = "", limit: int = 3) -> list[dict[str, Any]]:
        """Retrieves lessons learned across past tasks in the same domain."""
        if domain:
            kw = f"%{domain}%"
            rows = self.db.execute_read(
                "SELECT * FROM mistake_ledger WHERE context LIKE ? OR lesson_learned LIKE ? ORDER BY id DESC LIMIT ?",
                (kw, kw, limit),
            )
        else:
            rows = self.db.execute_read(
                "SELECT * FROM mistake_ledger ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        return [dict(r) for r in rows]

    def format_anti_pattern_prompt(self, task_id: str, domain: str = "") -> str:
        """Combines task-specific anti-patterns with historical cross-task lessons."""
        task_mistakes = self.get_task_mistakes(task_id)
        cross_lessons = self.get_cross_task_lessons(domain, limit=3)

        if not task_mistakes and not cross_lessons:
            return ""

        lines = [
            "### ADAPTIVE EPISODIC MEMORY (ANTI-PATTERNS & PREVENTATIVE LESSONS)",
        ]

        # Prioritize immediate attempt failures
        if task_mistakes:
            lines.append("Immediate Task Defect Feedback:")
            for idx, m in enumerate(task_mistakes, 1):
                lines.append(f"  {idx}. [{m['error_category']}] Signature: {m['error_signature']}")
                lines.append(f"     Lesson: {m['lesson_learned']}")

        # Append cross-task historic wisdom
        if cross_lessons:
            lines.append("\nCross-Task Historic Heuristics (Do NOT repeat these past mistakes):")
            for idx, c in enumerate(cross_lessons, 1):
                lines.append(f"  - Lesson: {c['lesson_learned']}")

        lines.append("\nCRITICAL: Satisfy all required adaptations above on this attempt.")
        return "\n".join(lines)
