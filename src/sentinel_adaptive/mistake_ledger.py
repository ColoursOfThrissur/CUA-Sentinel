"""Sentinel Episodic Mistake Memory.
Captures failure signatures and formats dynamic negative constraints (anti-patterns) for subsequent attempts.
"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

from sentinel_core.db import SentinelDB


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

    def get_task_mistakes(self, task_id: str) -> list[dict[str, Any]]:
        rows = self.db.execute_read(
            "SELECT * FROM mistake_ledger WHERE task_id = ? ORDER BY id ASC",
            (task_id,),
        )
        return [dict(r) for r in rows]

    def format_anti_pattern_prompt(self, task_id: str) -> str:
        mistakes = self.get_task_mistakes(task_id)
        if not mistakes:
            return ""

        lines = [
            "### ADAPTIVE FEEDBACK: PREVIOUS ATTEMPTS FAILED WITH DEFECTS",
            "Review the failure modes below and adapt your execution to avoid repeating them:",
        ]
        for idx, m in enumerate(mistakes, 1):
            lines.append(f"{idx}. Defect: [{m['error_category']}] Signature: {m['error_signature']}")
            lines.append(f"   Root Cause Context: {m['context']}")
            lines.append(f"   Required Adaptation (Lesson): {m['lesson_learned']}")
        lines.append("CRITICAL: You must satisfy the required adaptations above on this attempt.")
        return "\n".join(lines)
