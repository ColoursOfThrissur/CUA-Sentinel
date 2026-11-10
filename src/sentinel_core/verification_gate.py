"""Sentinel Objective Verification Gate (FR-024).
Provides deep syntactic, geometric, tabular, and execution validation.
Tasks are only committed if their output strictly passes structural and behavioral constraints.
"""
from __future__ import annotations

import ast
import csv
import io
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from sentinel_core.db import SentinelDB

logger = logging.getLogger("SentinelVerificationGate")


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

    def record_mistake_if_failed(
        self,
        task_id: str,
        attempt_id: str,
        result: VerificationResult,
    ) -> int | None:
        if result.passed:
            return None
        now = time.time()
        ctx_str = json.dumps(result.details)
        with self.db.transaction() as c:
            c.execute(
                """
                INSERT INTO mistake_ledger (task_id, attempt_id, error_category, error_signature, context, lesson_learned, ts)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (task_id, attempt_id, result.error_category or "UNKNOWN", result.error_signature or "UNKNOWN", ctx_str, result.lesson or "", now),
            )
            return c.lastrowid

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

    def verify_python_code(
        self,
        file_path: str | Path,
        required_symbols: list[str] | None = None,
        test_execution: bool = True,
        contract_harness: str | None = None,
    ) -> VerificationResult:
        """Deep verification of Python scripts: syntax (AST), completeness, test execution, and contract assertions."""
        base_res = self.verify_file_exists(file_path, min_bytes=20)
        if not base_res.passed:
            return base_res

        p = Path(file_path)
        code_text = p.read_text(encoding="utf-8")

        # 1. AST Syntax Validation
        try:
            tree = ast.parse(code_text, filename=str(p))
        except SyntaxError as e:
            return VerificationResult(
                passed=False,
                error_category="SYNTAX_ERROR",
                error_signature=f"SyntaxError:{type(e).__name__}",
                details={"line": e.lineno, "offset": e.offset, "msg": e.msg, "text": e.text},
                lesson=f"Python code has syntax error on line {e.lineno}: {e.msg}. Ensure code is complete and closed.",
            )

        # 2. Check for required symbols / completeness
        if required_symbols:
            defined_names = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    defined_names.add(node.name)
            
            missing = [s for s in required_symbols if s not in defined_names]
            if missing:
                return VerificationResult(
                    passed=False,
                    error_category="INCOMPLETE_CODE",
                    error_signature=f"MissingSymbols:{','.join(missing)}",
                    details={"missing_symbols": missing, "defined": list(defined_names)},
                    lesson=f"Code is incomplete; missing required classes/methods: {missing}. Implement all requested components.",
                )

        # 3. Execution / Runtime Test
        if test_execution:
            try:
                compile(code_text, filename=str(p), mode="exec")
            except Exception as e:
                return VerificationResult(
                    passed=False,
                    error_category="COMPILATION_ERROR",
                    error_signature=f"CompileError:{type(e).__name__}",
                    details={"error": str(e)},
                    lesson=f"Code compilation failed: {e}. Fix definitions.",
                )

            # Subprocess execution test (ephemeral run to test imports, top-level code, and tests)
            try:
                env = os.environ.copy()
                env["PYTHONPATH"] = str(p.parent)

                # 1. Run the script directly as __main__
                res_main = subprocess.run(
                    [sys.executable, str(p)],
                    capture_output=True,
                    text=True,
                    timeout=8,
                    env=env,
                )
                if res_main.returncode != 0:
                    err_msg = res_main.stderr.strip() or res_main.stdout.strip()
                    tb_lines = [line.strip() for line in err_msg.splitlines() if line.strip()]
                    last_err = tb_lines[-1] if tb_lines else f"NonZeroExit:{res_main.returncode}"
                    category = "CONTRACT_TEST_FAILED" if "AssertionError" in err_msg else "RUNTIME_ERROR"
                    return VerificationResult(
                        passed=False,
                        error_category=category,
                        error_signature=last_err[:100],
                        details={"exit_code": res_main.returncode, "stderr": err_msg},
                        lesson=f"Python execution failed with {last_err}. Fix logic defect and ensure all methods run without error.",
                    )

                # 2. Check for explicit test functions or contract harness
                top_functions = {
                    node.name for node in tree.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                }
                has_test_fns = any(fn.startswith("test_") for fn in top_functions) or ("main" in top_functions)

                if contract_harness or has_test_fns:
                    test_script = (
                        f"import sys\n"
                        f"sys.path.insert(0, r'{p.parent}')\n"
                        f"import {p.stem} as target_module\n"
                    )
                    if "main" in top_functions:
                        test_script += "target_module.main()\n"
                    for fn in sorted(top_functions):
                        if fn.startswith("test_"):
                            test_script += f"target_module.{fn}()\n"

                    if contract_harness:
                        test_script += "\n" + contract_harness.format(module="target_module") + "\n"

                    res_test = subprocess.run(
                        [sys.executable, "-c", test_script],
                        capture_output=True,
                        text=True,
                        timeout=10,
                        env=env,
                    )
                    if res_test.returncode != 0:
                        err_msg = res_test.stderr.strip() or res_test.stdout.strip()
                        tb_lines = [line.strip() for line in err_msg.splitlines() if line.strip()]
                        last_err = tb_lines[-1] if tb_lines else f"NonZeroExit:{res_test.returncode}"
                        category = "CONTRACT_TEST_FAILED" if "AssertionError" in err_msg else "RUNTIME_ERROR"
                        return VerificationResult(
                            passed=False,
                            error_category=category,
                            error_signature=last_err[:100],
                            details={"exit_code": res_test.returncode, "stderr": err_msg},
                            lesson=f"Verification test execution failed: {last_err}. Fix logic defects and ensure all edge cases work.",
                        )
            except subprocess.TimeoutExpired:
                return VerificationResult(
                    passed=False,
                    error_category="RUNTIME_TIMEOUT",
                    error_signature="ExecutionTimeout:10s",
                    details={"timeout": 10},
                    lesson="Script hung or timed out during execution. Ensure algorithms terminate without infinite loops.",
                )
            except Exception as e:
                return VerificationResult(
                    passed=False,
                    error_category="EXECUTION_TEST_FAILED",
                    error_signature=f"SubprocessError:{type(e).__name__}",
                    details={"error": str(e)},
                    lesson=f"Execution test runner failed: {e}",
                )

        return VerificationResult(passed=True, details={"path": str(p), "ast_nodes": len(tree.body)})

    def verify_obj_geometry(
        self,
        file_path: str | Path,
        min_vertices: int = 10,
        min_faces: int = 5,
    ) -> VerificationResult:
        """Deep verification of 3D Wavefront OBJ models: vertex count, face count, and bounding box volume."""
        base_res = self.verify_file_exists(file_path, min_bytes=50)
        if not base_res.passed:
            return base_res

        p = Path(file_path)
        vertices = []
        faces_count = 0

        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                parts = line.strip().split()
                if not parts:
                    continue
                if parts[0] == "v" and len(parts) >= 4:
                    try:
                        vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
                    except ValueError:
                        pass
                elif parts[0] == "f":
                    faces_count += 1

        v_count = len(vertices)
        if v_count < min_vertices:
            return VerificationResult(
                passed=False,
                error_category="DEGENERATE_GEOMETRY",
                error_signature=f"InsufficientVertices:{v_count}",
                details={"vertices": v_count, "min_required": min_vertices},
                lesson=f"3D OBJ model has only {v_count} vertices (expected >= {min_vertices}). Ensure real 3D mesh is constructed.",
            )

        if faces_count < min_faces:
            return VerificationResult(
                passed=False,
                error_category="DEGENERATE_GEOMETRY",
                error_signature=f"InsufficientFaces:{faces_count}",
                details={"faces": faces_count, "min_required": min_faces},
                lesson=f"3D OBJ model has only {faces_count} polygon faces (expected >= {min_faces}). Construct polygonal geometry.",
            )

        # Check Bounding Box volume
        xs = [v[0] for v in vertices]
        ys = [v[1] for v in vertices]
        zs = [v[2] for v in vertices]
        dx = max(xs) - min(xs)
        dy = max(ys) - min(ys)
        dz = max(zs) - min(zs)

        if dx <= 0.0001 and dy <= 0.0001 and dz <= 0.0001:
            return VerificationResult(
                passed=False,
                error_category="ZERO_VOLUME_GEOMETRY",
                error_signature="ZeroVolumeBoundingBox",
                details={"dimensions": [dx, dy, dz]},
                lesson="3D Model has zero spatial volume (all vertices collapse to a point). Expand mesh bounds.",
            )

        return VerificationResult(
            passed=True,
            details={"vertices": v_count, "faces": faces_count, "bbox_size": [round(dx, 2), round(dy, 2), round(dz, 2)]},
        )

    def verify_csv_structure(
        self,
        file_path: str | Path,
        min_rows: int = 2,
        min_cols: int = 2,
    ) -> VerificationResult:
        """Validates CSV formatting, column counts, and non-empty rows."""
        base_res = self.verify_file_exists(file_path, min_bytes=10)
        if not base_res.passed:
            return base_res

        p = Path(file_path)
        try:
            with open(p, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = [r for r in reader if r]

            if len(rows) < min_rows:
                return VerificationResult(
                    passed=False,
                    error_category="INSUFFICIENT_DATA",
                    error_signature=f"RowCountTooLow:{len(rows)}",
                    details={"rows": len(rows), "min_required": min_rows},
                    lesson=f"CSV dataset has only {len(rows)} rows. Must contain header plus data rows.",
                )

            col_count = len(rows[0])
            if col_count < min_cols:
                return VerificationResult(
                    passed=False,
                    error_category="INSUFFICIENT_COLUMNS",
                    error_signature=f"ColCountTooLow:{col_count}",
                    details={"cols": col_count, "min_required": min_cols},
                    lesson=f"CSV dataset has only {col_count} columns (expected >= {min_cols}). Include multiple metrics.",
                )

            return VerificationResult(passed=True, details={"rows": len(rows), "cols": col_count, "header": rows[0]})
        except Exception as e:
            return VerificationResult(
                passed=False,
                error_category="CSV_PARSE_ERROR",
                error_signature=f"CsvFormatError:{type(e).__name__}",
                details={"error": str(e)},
                lesson=f"CSV format error: {e}. Output must be RFC 4180 compliant CSV.",
            )

    def verify_markdown_report(
        self,
        file_path: str | Path,
        min_words: int = 40,
    ) -> VerificationResult:
        """Validates Markdown report structure, headings, and substantive length."""
        base_res = self.verify_file_exists(file_path, min_bytes=30)
        if not base_res.passed:
            return base_res

        p = Path(file_path)
        content = p.read_text(encoding="utf-8")
        words = content.split()

        if len(words) < min_words:
            return VerificationResult(
                passed=False,
                error_category="SUPERFICIAL_REPORT",
                error_signature=f"WordCountTooLow:{len(words)}",
                details={"words": len(words), "min_expected": min_words},
                lesson=f"Report contains only {len(words)} words (expected >= {min_words}). Provide thorough analysis.",
            )

        has_headings = any(line.strip().startswith("#") for line in content.splitlines())
        if not has_headings:
            return VerificationResult(
                passed=False,
                error_category="MISSING_STRUCTURE",
                error_signature="NoMarkdownHeadings",
                details={"content_preview": content[:100]},
                lesson="Report lacks structured Markdown headers (#, ##). Format with clear sections.",
            )

        return VerificationResult(passed=True, details={"word_count": len(words), "has_headings": True})

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
                error_category="VERIFIER_CRASH",
                error_signature=f"VerifierException:{type(e).__name__}",
                details={"check": name, "error": str(e)},
                lesson=f"Verifier encountered an unhandled exception: {e}",
            )
