"""Sentinel Data and Code Execution Organs.
Provides sandboxed Python script execution, CSV data processing, and structured report synthesis.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from sentinel_core.side_effects import EffectClass
from sentinel_broker.tool_registry import ToolRegistry
from sentinel_core.llm_gateway import LLMGateway

logger = logging.getLogger("SentinelDataOrgan")


def register_data_organs(registry: ToolRegistry, llm_gateway: LLMGateway | None = None):
    gw = llm_gateway or LLMGateway()

    @registry.register(
        name="python_sandbox_run",
        description="Safely executes an isolated Python script in a controlled process and captures outputs/artifacts.",
        effect_class=EffectClass.NON_IDEMPOTENT_WRITE,
        parameters_schema={
            "script_code": "str (executable python code)",
            "output_artifact_path": "str | None (path to expected output artifact)",
            "timeout_sec": "float (maximum execution timeout)",
        },
    )
    def python_sandbox_run(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        script_code = params.get("script_code", "")
        output_artifact = params.get("output_artifact_path")
        timeout = float(params.get("timeout_sec", 20.0))

        if not script_code.strip():
            return {"error": "script_code cannot be empty", "exit_code": 1}

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(script_code)
            tmp_script = f.name

        try:
            start_t = time.time()
            proc = subprocess.run(
                [sys.executable, tmp_script],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            duration = time.time() - start_t
            artifact_exists = Path(output_artifact).exists() if output_artifact else False
            artifact_size = Path(output_artifact).stat().st_size if artifact_exists else 0

            return {
                "exit_code": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "duration_sec": round(duration, 3),
                "artifact_path": output_artifact,
                "artifact_exists": artifact_exists,
                "artifact_size_bytes": artifact_size,
            }
        except subprocess.TimeoutExpired:
            return {"error": f"Script execution timed out after {timeout}s", "exit_code": -1}
        finally:
            if os.path.exists(tmp_script):
                try:
                    os.unlink(tmp_script)
                except OSError:
                    pass

    @registry.register(
        name="csv_analyze_and_report",
        description="Analyzes tabular CSV data and synthesizes a structured Markdown report with statistics.",
        effect_class=EffectClass.NON_IDEMPOTENT_WRITE,
        parameters_schema={
            "csv_path_or_content": "str (file path or inline CSV text)",
            "analysis_goal": "str (specific questions or insights to compute)",
            "output_report_path": "str (target path for .md report)",
        },
    )
    def csv_analyze_and_report(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        csv_input = params.get("csv_path_or_content", "")
        goal = params.get("analysis_goal", "Summarize columns, row count, and distributions.")
        output_path = params.get("output_report_path", "workspace_report.md")

        # Read sample data
        sample_rows = []
        if os.path.exists(csv_input):
            with open(csv_input, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                for _ in range(15):
                    row = next(reader, None)
                    if row is None:
                        break
                    sample_rows.append(row)
        else:
            reader = csv.reader(io.StringIO(csv_input))
            for _ in range(15):
                row = next(reader, None)
                if row is None:
                    break
                sample_rows.append(row)

        sample_str = "\n".join([",".join(r) for r in sample_rows])

        system_instruction = (
            "You are Sentinel's Data Analysis Organ. Synthesize clean Python 3 code using ONLY the standard library "
            "(csv, math, statistics, collections, json) to analyze the provided dataset and write a comprehensive "
            f"Markdown report to '{output_path}'.\n"
            "Output ONLY executable Python code inside a ```python ``` block."
        )

        prompt = (
            f"Analysis Goal: {goal}\n"
            f"Target Markdown Report File: {output_path}\n"
            f"Sample Data:\n```csv\n{sample_str}\n```\n"
            f"Write the complete Python script that computes metrics and writes '{output_path}'."
        )

        code_response = gw.generate(prompt=prompt, system=system_instruction)
        py_code = gw.extract_python_code(code_response)

        # Run synthesized python code
        res = python_sandbox_run(
            {"script_code": py_code, "output_artifact_path": output_path, "timeout_sec": 30.0},
            ctx,
        )
        return {
            "result": res,
            "synthesized_code": py_code,
            "report_path": output_path,
        }

    @registry.register(
        name="file_transform",
        description="Transforms file formats (e.g. CSV to JSON, JSON to Markdown).",
        effect_class=EffectClass.NON_IDEMPOTENT_WRITE,
        parameters_schema={
            "source_path": "str (source file path)",
            "target_path": "str (destination file path)",
            "format": "str ('csv_to_json', 'json_to_csv')",
        },
    )
    def file_transform(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        src = Path(params["source_path"])
        dst = Path(params["target_path"])
        fmt = params.get("format", "csv_to_json").lower()

        if not src.exists():
            return {"error": f"Source file does not exist: {src}", "success": False}

        if fmt == "csv_to_json":
            rows = []
            with open(src, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        elif fmt == "json_to_csv":
            data = json.loads(src.read_text(encoding="utf-8"))
            if not isinstance(data, list) or not data:
                return {"error": "JSON data must be a non-empty list of objects", "success": False}
            headers = list(data[0].keys())
            dst.parent.mkdir(parents=True, exist_ok=True)
            with open(dst, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writeheader()
                writer.writerows(data)
        else:
            return {"error": f"Unsupported format: {fmt}", "success": False}

        return {
            "success": True,
            "source": str(src),
            "target": str(dst),
            "target_bytes": dst.stat().st_size,
        }
