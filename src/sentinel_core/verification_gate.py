"""Sentinel Objective Verification Gate (FR-024).
Validates task outcomes before commit. If verification fails, records defect into episodic mistake memory.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from sentinel_core.db import SentinelDB


@dataclass
class VerificationResult:
    passed: bool
    error_category: str | None = None
    error_signature: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    lesson: str | None = None


class VerificationGate:
    def __init__(self, db: SentinelDB):
        self.db = db

    def verify_file_exists(self, file_path: str | Path, min_bytes: int = 1) -> VerificationResult:
        p = Path(file_path)
        if not p.exists():
            return VerificationResult(
                passed=False,
                error_category="MISSING_ARTIFACT",
                error_signature=f"FileNotFound:{p.name}",
                details={"path": str(p), "reason": "Expected artifact file was not created"},
                lesson=f"Worker must ensure output file {p.name} is written to disk before signaling completion.",
            )
        sz = p.stat().st_size
        if sz < min_bytes:
            return VerificationResult(
                passed=False,
                error_category="EMPTY_ARTIFACT",
                error_signature=f"EmptyFile:{p.name}",
                details={"path": str(p), "size_bytes": sz, "min_expected": min_bytes},
                lesson=f"Worker wrote empty or truncated file {p.name} ({sz} bytes). Ensure data is flushed.",
            )
        return VerificationResult(passed=True, details={"path": str(p), "size_bytes": sz})

    def verify_json_schema(self, json_data: str | dict, required_keys: set[str]) -> VerificationResult:
        try:
            data = json.loads(json_data) if isinstance(json_data, str) else json_data
            if not isinstance(data, dict):
                return VerificationResult(
                    passed=False,
                    error_category="SCHEMA_MISMATCH",
                    error_signature="RootNotADict",
                    details={"type": type(data).__name__},
                    lesson="Payload root must be a JSON dictionary.",
                )
            missing = required_keys - set(data.keys())
            if missing:
                return VerificationResult(
                    passed=False,
                    error_category="MISSING_KEYS",
                    error_signature=f"MissingKeys:{','.join(sorted(missing))}",
                    details={"missing_keys": list(missing)},
                    lesson=f"Worker response omitted required keys: {sorted(missing)}.",
                )
            return VerificationResult(passed=True, details={"keys_present": list(data.keys())})
        except Exception as e:
            return VerificationResult(
                passed=False,
                error_category="JSON_DECODE_ERROR",
                error_signature=f"JsonParseError:{type(e).__name__}",
                details={"error": str(e)},
                lesson="Worker output was not valid JSON.",
            )

    def verify_predicate(
        self,
        predicate: Callable[[], bool | tuple[bool, str]],
        name: str = "custom_predicate",
    ) -> VerificationResult:
        try:
            res = predicate()
            if isinstance(res, tuple):
                ok, reason = res
            else:
                ok, reason = bool(res), "Predicate returned false"

            if ok:
                return VerificationResult(passed=True, details={"check": name})
            else:
                return VerificationResult(
                    passed=False,
                    error_category="PREDICATE_FAILED",
                    error_signature=f"FailedPredicate:{name}",
                    details={"check": name, "reason": reason},
                    lesson=f"Verification rule '{name}' failed: {reason}",
                )
        except Exception as e:
            return VerificationResult(
                passed=False,
                error_category="PREDICATE_EXCEPTION",
                error_signature=f"PredicateException:{type(e).__name__}",
                details={"check": name, "error": str(e)},
                lesson=f"Verification rule '{name}' threw exception: {e}",
            )

    def record_mistake_if_failed(
        self,
        task_id: str,
        attempt_id: str,
        result: VerificationResult,
    ):
        """Records defect into SQLite episodic mistake ledger."""
        if result.passed:
            return
        now = time.time()
        with self.db.transaction() as c:
            c.execute(
                """
                INSERT INTO mistake_ledger (task_id, attempt_id, error_category, error_signature, context, lesson_learned, ts)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    attempt_id,
                    result.error_category or "UNKNOWN_ERROR",
                    result.error_signature or "UnknownSignature",
                    json.dumps(result.details),
                    result.lesson or "No explicit lesson recorded.",
                    now,
                ),
            )
