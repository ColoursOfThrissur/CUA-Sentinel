"""Sentinel Side-Effect Ledger (AT-B-08, AT-B-09).
Tracks tool call intent before execution and outcome after execution to support deterministic replay and recovery.
"""
from __future__ import annotations

import json
import sqlite3
import time
from enum import Enum
from typing import Any

from sentinel_core.db import SentinelDB


class EffectClass(str, Enum):
    READ_ONLY = "READ_ONLY"
    IDEMPOTENT_WRITE = "IDEMPOTENT_WRITE"
    NON_IDEMPOTENT_WRITE = "NON_IDEMPOTENT_WRITE"
    IRREVERSIBLE = "IRREVERSIBLE"


class SideEffectLedger:
    def __init__(self, db: SentinelDB):
        self.db = db

    def record_intent(
        self,
        attempt_id: str,
        tool_name: str,
        effect_class: EffectClass | str,
        intent_payload: dict[str, Any],
        cursor: sqlite3.Cursor | None = None,
    ) -> int:
        """Records the tool execution intent BEFORE dispatching the tool call."""
        effect_str = effect_class.value if isinstance(effect_class, EffectClass) else effect_class
        payload_str = json.dumps(intent_payload)
        now = time.time()

        sql = """
        INSERT INTO side_effect_ledger (attempt_id, effect_class, tool_name, intent_payload, status, created_at)
        VALUES (?, ?, ?, ?, 'INTENT_RECORDED', ?)
        """

        if cursor is not None:
            cursor.execute(sql, (attempt_id, effect_str, tool_name, payload_str, now))
            return cursor.lastrowid
        else:
            with self.db.transaction() as c:
                c.execute(sql, (attempt_id, effect_str, tool_name, payload_str, now))
                return c.lastrowid

    def record_outcome(
        self,
        ledger_id: int,
        outcome_payload: dict[str, Any],
        success: bool = True,
        cursor: sqlite3.Cursor | None = None,
    ):
        """Records the outcome AFTER tool execution finishes."""
        status = "OUTCOME_RECORDED" if success else "FAILED"
        payload_str = json.dumps(outcome_payload)
        now = time.time()

        sql = """
        UPDATE side_effect_ledger
        SET outcome_payload = ?, status = ?, updated_at = ?
        WHERE id = ?
        """

        if cursor is not None:
            cursor.execute(sql, (payload_str, status, now, ledger_id))
        else:
            with self.db.transaction() as c:
                c.execute(sql, (payload_str, status, now, ledger_id))

    def get_attempt_effects(self, attempt_id: str) -> list[dict[str, Any]]:
        rows = self.db.execute_read(
            "SELECT * FROM side_effect_ledger WHERE attempt_id = ? ORDER BY id ASC",
            (attempt_id,),
        )
        return [dict(r) for r in rows]

    def get_unresolved_intents(self, attempt_id: str) -> list[dict[str, Any]]:
        rows = self.db.execute_read(
            "SELECT * FROM side_effect_ledger WHERE attempt_id = ? AND status = 'INTENT_RECORDED'",
            (attempt_id,),
        )
        return [dict(r) for r in rows]
