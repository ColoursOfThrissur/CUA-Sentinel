"""Sentinel Multi-Step Task DAG Orchestrator.
Choreographs multi-agent workflows as Directed Acyclic Graphs (DAGs) with capability fencing,
dependency tracking, and artifact passing between specialized agents.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import threading

from sentinel_core.db import SentinelDB

logger = logging.getLogger("sentinel.dag")


class DAGState(str, Enum):
    PENDING = "Pending"
    RUNNING = "Running"
    SUCCEEDED = "Succeeded"
    FAILED = "Failed"
    CANCELLED = "Cancelled"


class DAGStepState(str, Enum):
    PENDING = "Pending"
    RUNNING = "Running"
    SUCCEEDED = "Succeeded"
    FAILED = "Failed"
    SKIPPED = "Skipped"
    CANCELLED = "Cancelled"


class DAGValidationError(Exception):
    """Raised when a DAG definition is invalid (cycles, missing dependencies, etc.)."""
    pass


@dataclass
class DAGStepDefinition:
    step_id: str
    goal: str
    agent_id: str
    domain: str  # "data", "code", "3d", "analysis"
    dependencies: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "goal": self.goal,
            "agent_id": self.agent_id,
            "domain": self.domain,
            "dependencies": list(self.dependencies),
        }


def validate_and_sort_dag(steps: list[DAGStepDefinition]) -> list[str]:
    """Validates DAG structure (no missing dependencies, no cycles) and returns topological sort order."""
    step_map = {s.step_id: s for s in steps}
    if len(step_map) != len(steps):
        raise DAGValidationError("Duplicate step_id detected in DAG specification.")

    # Check for missing dependencies
    for s in steps:
        for dep in s.dependencies:
            if dep not in step_map:
                raise DAGValidationError(f"Step '{s.step_id}' references non-existent dependency '{dep}'.")
            if dep == s.step_id:
                raise DAGValidationError(f"Step '{s.step_id}' cannot depend on itself.")

    # Kahn's algorithm for topological sorting and cycle detection
    in_degree = {s.step_id: 0 for s in steps}
    adj: dict[str, list[str]] = {s.step_id: [] for s in steps}

    for s in steps:
        for dep in s.dependencies:
            adj[dep].append(s.step_id)
            in_degree[s.step_id] += 1

    queue = [s_id for s_id, deg in in_degree.items() if deg == 0]
    order = []

    while queue:
        curr = queue.pop(0)
        order.append(curr)
        for neighbor in adj[curr]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(order) != len(steps):
        raise DAGValidationError("Cycle detected in DAG dependencies! Graph must be acyclic.")

    return order


def format_predecessor_artifacts(predecessor_artifacts: dict[str, str]) -> str:
    """Extracts rich, structured semantic metadata from upstream artifacts for downstream agents."""
    if not predecessor_artifacts:
        return ""

    context_lines = ["\n[UPSTREAM PIPELINE ARTIFACTS IN THIS WORKFLOW]:"]
    for p_id, p_path in predecessor_artifacts.items():
        pp = Path(p_path)
        if not pp.exists():
            context_lines.append(f"• Predecessor step '{p_id}': generated artifact '{p_path}' (file pending or not on disk)")
            continue

        sz = pp.stat().st_size
        suf = pp.suffix.lower()

        # 1. 3D OBJ Mesh Artifact
        if suf == ".obj":
            try:
                lines = pp.read_text(encoding="utf-8", errors="ignore").splitlines()
                v_count = sum(1 for l in lines if l.startswith("v "))
                f_count = sum(1 for l in lines if l.startswith("f "))
                context_lines.append(
                    f"• Predecessor step '{p_id}' generated 3D Mesh: '{p_path}' ({round(sz/1024, 1)} KB)\n"
                    f"  - Geometry: {v_count} vertices, {f_count} polygon faces\n"
                    f"  - Format: Wavefront OBJ 3D Model"
                )
            except Exception:
                context_lines.append(f"• Predecessor step '{p_id}' generated 3D Mesh: '{p_path}' ({sz} bytes)")

        # 2. Tabular CSV Dataset
        elif suf == ".csv":
            try:
                import csv
                with open(pp, mode="r", encoding="utf-8", errors="replace") as f:
                    reader = csv.reader(f)
                    header = next(reader, [])
                    rows = list(reader)
                row_count = len(rows)
                sample = "\n    ".join([", ".join(r[:6]) for r in rows[:3]])
                context_lines.append(
                    f"• Predecessor step '{p_id}' generated Tabular Dataset: '{p_path}' ({round(sz/1024, 1)} KB)\n"
                    f"  - Columns ({len(header)}): {', '.join(header)}\n"
                    f"  - Records: {row_count} rows\n"
                    f"  - Sample Rows:\n    {sample}"
                )
            except Exception:
                context_lines.append(f"• Predecessor step '{p_id}' generated CSV: '{p_path}' ({sz} bytes)")

        # 3. Python Source Code Module
        elif suf == ".py":
            try:
                code_text = pp.read_text(encoding="utf-8", errors="replace")
                defs = [line.strip() for line in code_text.splitlines() if line.startswith(("def ", "class "))][:5]
                preview = "\n  ".join(defs) if defs else code_text[:300]
                context_lines.append(
                    f"• Predecessor step '{p_id}' generated Python Module: '{p_path}' ({round(sz/1024, 1)} KB)\n"
                    f"  - Defined Symbols:\n  {preview}"
                )
            except Exception:
                context_lines.append(f"• Predecessor step '{p_id}' generated Python code: '{p_path}' ({sz} bytes)")

        # 4. Markdown Report / Text
        elif suf in (".md", ".txt"):
            try:
                text = pp.read_text(encoding="utf-8", errors="replace")
                words = len(text.split())
                headings = [line.strip() for line in text.splitlines() if line.startswith("#")][:4]
                context_lines.append(
                    f"• Predecessor step '{p_id}' generated Report: '{p_path}' ({words} words)\n"
                    f"  - Headings: {', '.join(headings) if headings else 'N/A'}"
                )
            except Exception:
                context_lines.append(f"• Predecessor step '{p_id}' generated Report: '{p_path}' ({sz} bytes)")

        else:
            context_lines.append(f"• Predecessor step '{p_id}' generated Artifact: '{p_path}' ({sz} bytes)")

    return "\n".join(context_lines) + "\n"


class DAGOrchestrator:
    """Orchestrates execution of multi-step task DAGs across Gate A specialized agents."""

    def __init__(self, db: SentinelDB):
        self.db = db

    def create_dag(
        self,
        name: str,
        description: str,
        steps: list[DAGStepDefinition],
    ) -> str:
        """Validates and persists a new DAG definition to the database."""
        if not steps:
            raise DAGValidationError("A DAG must contain at least one step.")

        # Validate topology
        validate_and_sort_dag(steps)

        dag_id = f"dag_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        now = time.time()

        with self.db.transaction() as c:
            c.execute(
                """
                INSERT INTO dag_runs (id, name, description, state, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (dag_id, name, description, DAGState.PENDING.value, now, now),
            )

            for step in steps:
                c.execute(
                    """
                    INSERT INTO dag_steps (
                        dag_id, step_id, goal, agent_id, domain,
                        dependencies_json, state, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        dag_id,
                        step.step_id,
                        step.goal,
                        step.agent_id,
                        step.domain,
                        json.dumps(step.dependencies),
                        DAGStepState.PENDING.value,
                        now,
                        now,
                    ),
                )

        logger.info("Created DAG '%s' ('%s') with %d steps.", dag_id, name, len(steps))
        return dag_id

    def get_dag(self, dag_id: str) -> dict[str, Any] | None:
        """Retrieves DAG run details and all constituent steps."""
        run_row = self.db.execute_one("SELECT * FROM dag_runs WHERE id = ?", (dag_id,))
        if not run_row:
            return None

        dag_dict = dict(run_row)
        step_rows = self.db.execute_read(
            "SELECT * FROM dag_steps WHERE dag_id = ? ORDER BY id ASC",
            (dag_id,),
        )
        steps = []
        for r in step_rows:
            sd = dict(r)
            sd["dependencies"] = json.loads(sd.get("dependencies_json", "[]"))
            steps.append(sd)
        dag_dict["steps"] = steps
        return dag_dict

    def list_dags(self, limit: int = 50) -> list[dict[str, Any]]:
        """Lists recent DAG runs with high-level progress summaries."""
        runs = self.db.execute_read(
            "SELECT * FROM dag_runs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        result = []
        for r in runs:
            d = dict(r)
            counts = self.db.execute_read(
                "SELECT state, COUNT(*) as cnt FROM dag_steps WHERE dag_id = ? GROUP BY state",
                (d["id"],),
            )
            d["step_counts"] = {c["state"]: c["cnt"] for c in counts}
            total_steps = sum(d["step_counts"].values())
            d["total_steps"] = total_steps
            d["succeeded_steps"] = d["step_counts"].get("Succeeded", 0)
            result.append(d)
        return result

    def update_step_state(
        self,
        dag_id: str,
        step_id: str,
        state: DAGStepState,
        task_id: str | None = None,
        output_artifact: str | None = None,
        error: str | None = None,
    ):
        """Updates execution state of an individual DAG step."""
        now = time.time()
        with self.db.transaction() as c:
            c.execute(
                """
                UPDATE dag_steps
                SET state = ?, task_id = COALESCE(?, task_id),
                    output_artifact = COALESCE(?, output_artifact),
                    error = ?, updated_at = ?
                WHERE dag_id = ? AND step_id = ?
                """,
                (state.value, task_id, output_artifact, error, now, dag_id, step_id),
            )

    def update_dag_state(
        self,
        dag_id: str,
        state: DAGState,
        error: str | None = None,
    ):
        """Updates overall DAG execution state."""
        now = time.time()
        completed_at = now if state in (DAGState.SUCCEEDED, DAGState.FAILED) else None
        with self.db.transaction() as c:
            c.execute(
                """
                UPDATE dag_runs
                SET state = ?, error = ?, updated_at = ?, completed_at = COALESCE(?, completed_at)
                WHERE id = ?
                """,
                (state.value, error, now, completed_at, dag_id),
            )

    def execute_dag(
        self,
        dag_id: str,
        step_executor: Callable[[dict[str, Any], dict[str, str]], dict[str, Any]],
        concurrent: bool = True,
        max_workers: int = 4,
    ) -> dict[str, Any]:
        """
        Executes all steps of a DAG honoring topological dependencies.
        When concurrent=True, independent branches run in parallel waves via ThreadPoolExecutor.
        step_executor is a callable: (step_dict, predecessor_artifacts_map) -> {"success": bool, "task_id": str, "artifact_path": str, "error": str}
        """
        dag = self.get_dag(dag_id)
        if not dag:
            raise ValueError(f"DAG '{dag_id}' not found.")

        if dag.get("state") in (DAGState.CANCELLED.value, DAGState.FAILED.value, DAGState.SUCCEEDED.value):
            logger.info("DAG '%s' is in terminal state '%s'; skipping execution.", dag_id, dag.get("state"))
            return dag

        steps_dict = {s["step_id"]: s for s in dag["steps"]}
        step_defs = [
            DAGStepDefinition(
                step_id=s["step_id"],
                goal=s["goal"],
                agent_id=s["agent_id"],
                domain=s["domain"],
                dependencies=s["dependencies"],
            )
            for s in dag["steps"]
        ]

        order = validate_and_sort_dag(step_defs)
        self.update_dag_state(dag_id, DAGState.RUNNING)

        artifacts_by_step: dict[str, str] = {}
        has_failure = False

        if not concurrent or len(order) <= 1:
            for step_id in order:
                current_dag = self.get_dag(dag_id)
                if current_dag and current_dag.get("state") == DAGState.CANCELLED.value:
                    logger.info("DAG '%s' was cancelled; aborting remaining steps.", dag_id)
                    has_failure = True
                    break

                step = steps_dict[step_id]
                deps = step["dependencies"]

                prereq_failed = any(
                    steps_dict[d]["state"] in (DAGStepState.FAILED.value, DAGStepState.SKIPPED.value, DAGStepState.CANCELLED.value)
                    for d in deps
                )
                if prereq_failed:
                    logger.warning("Step '%s' skipped because a prerequisite dependency failed.", step_id)
                    self.update_step_state(dag_id, step_id, DAGStepState.SKIPPED, error="Prerequisite step failed")
                    steps_dict[step_id]["state"] = DAGStepState.SKIPPED.value
                    has_failure = True
                    continue

                predecessor_artifacts = {
                    d: artifacts_by_step[d]
                    for d in deps
                    if d in artifacts_by_step
                }

                self.update_step_state(dag_id, step_id, DAGStepState.RUNNING)
                steps_dict[step_id]["state"] = DAGStepState.RUNNING.value
                logger.info("Executing DAG step '%s' via agent '%s'...", step_id, step["agent_id"])

                try:
                    result = step_executor(step, predecessor_artifacts)
                    success = result.get("success", False)
                    task_id = result.get("task_id")
                    artifact_path = result.get("artifact_path")
                    err_msg = result.get("error")

                    if success:
                        if artifact_path:
                            artifacts_by_step[step_id] = artifact_path
                        self.update_step_state(
                            dag_id,
                            step_id,
                            DAGStepState.SUCCEEDED,
                            task_id=task_id,
                            output_artifact=artifact_path,
                        )
                        steps_dict[step_id]["state"] = DAGStepState.SUCCEEDED.value
                        logger.info("DAG step '%s' SUCCEEDED (artifact: %s)", step_id, artifact_path)
                    else:
                        has_failure = True
                        self.update_step_state(
                            dag_id,
                            step_id,
                            DAGStepState.FAILED,
                            task_id=task_id,
                            output_artifact=artifact_path,
                            error=err_msg or "Step verification failed",
                        )
                        steps_dict[step_id]["state"] = DAGStepState.FAILED.value
                        logger.error("DAG step '%s' FAILED: %s", step_id, err_msg)
                except Exception as e:
                    has_failure = True
                    err_str = str(e)
                    logger.exception("DAG step '%s' raised exception: %s", step_id, err_str)
                    self.update_step_state(
                        dag_id,
                        step_id,
                        DAGStepState.FAILED,
                        error=err_str,
                    )
                    steps_dict[step_id]["state"] = DAGStepState.FAILED.value
        else:
            # Concurrent Wave Topological Execution
            in_degree = {s["step_id"]: len(s["dependencies"]) for s in dag["steps"]}
            adj: dict[str, list[str]] = {s["step_id"]: [] for s in dag["steps"]}
            for s in dag["steps"]:
                for dep in s["dependencies"]:
                    adj[dep].append(s["step_id"])

            state_lock = threading.Lock()
            completed_count = 0
            total_steps = len(dag["steps"])

            def execute_single_step(s_id: str):
                nonlocal has_failure, completed_count
                step = steps_dict[s_id]

                with state_lock:
                    curr_dag = self.get_dag(dag_id)
                    if curr_dag and curr_dag.get("state") == DAGState.CANCELLED.value:
                        return False
                    if has_failure:
                        self.update_step_state(dag_id, s_id, DAGStepState.SKIPPED, error="Prerequisite step failed")
                        steps_dict[s_id]["state"] = DAGStepState.SKIPPED.value
                        completed_count += 1
                        return False

                    deps = step["dependencies"]
                    prereq_failed = any(
                        steps_dict[d]["state"] in (DAGStepState.FAILED.value, DAGStepState.SKIPPED.value, DAGStepState.CANCELLED.value)
                        for d in deps
                    )
                    if prereq_failed:
                        self.update_step_state(dag_id, s_id, DAGStepState.SKIPPED, error="Prerequisite step failed")
                        steps_dict[s_id]["state"] = DAGStepState.SKIPPED.value
                        has_failure = True
                        completed_count += 1
                        return False

                    pred_artifacts = {d: artifacts_by_step[d] for d in deps if d in artifacts_by_step}
                    self.update_step_state(dag_id, s_id, DAGStepState.RUNNING)
                    steps_dict[s_id]["state"] = DAGStepState.RUNNING.value

                logger.info("Executing concurrent DAG step '%s' via agent '%s'...", s_id, step["agent_id"])
                try:
                    res = step_executor(step, pred_artifacts)
                    success = res.get("success", False)
                    task_id = res.get("task_id")
                    art_path = res.get("artifact_path")
                    err_msg = res.get("error")

                    with state_lock:
                        if success:
                            if art_path:
                                artifacts_by_step[s_id] = art_path
                            self.update_step_state(
                                dag_id,
                                s_id,
                                DAGStepState.SUCCEEDED,
                                task_id=task_id,
                                output_artifact=art_path,
                            )
                            steps_dict[s_id]["state"] = DAGStepState.SUCCEEDED.value
                            logger.info("DAG step '%s' SUCCEEDED (artifact: %s)", s_id, art_path)
                        else:
                            has_failure = True
                            self.update_step_state(
                                dag_id,
                                s_id,
                                DAGStepState.FAILED,
                                task_id=task_id,
                                output_artifact=art_path,
                                error=err_msg or "Step verification failed",
                            )
                            steps_dict[s_id]["state"] = DAGStepState.FAILED.value
                            logger.error("DAG step '%s' FAILED: %s", s_id, err_msg)
                        completed_count += 1
                        return success
                except Exception as ex:
                    with state_lock:
                        has_failure = True
                        self.update_step_state(dag_id, s_id, DAGStepState.FAILED, error=str(ex))
                        steps_dict[s_id]["state"] = DAGStepState.FAILED.value
                        completed_count += 1
                        return False

            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                submitted = set()
                futures: dict[Any, str] = {}

                while completed_count < total_steps:
                    with state_lock:
                        curr_dag = self.get_dag(dag_id)
                        if curr_dag and curr_dag.get("state") == DAGState.CANCELLED.value:
                            break

                        ready = [
                            s_id for s_id, deg in in_degree.items()
                            if deg == 0 and s_id not in submitted
                        ]
                        for r_id in ready:
                            submitted.add(r_id)
                            fut = pool.submit(execute_single_step, r_id)
                            futures[fut] = r_id

                    if not futures:
                        break

                    done, _ = wait(futures.keys(), return_when=FIRST_COMPLETED)
                    for f in done:
                        finished_id = futures.pop(f)
                        step_succeeded = f.result()
                        with state_lock:
                            if step_succeeded:
                                for neighbor in adj[finished_id]:
                                    in_degree[neighbor] -= 1
                            else:
                                for neighbor in adj[finished_id]:
                                    in_degree[neighbor] = -999  # unreachable

        curr = self.get_dag(dag_id)
        if curr and curr.get("state") != DAGState.CANCELLED.value:
            final_state = DAGState.FAILED if has_failure else DAGState.SUCCEEDED
            if has_failure:
                with self.db.transaction() as c:
                    c.execute(
                        "UPDATE dag_steps SET state = 'Skipped', error = 'Prerequisite step failed', updated_at = ? WHERE dag_id = ? AND state = 'Pending'",
                        (time.time(), dag_id),
                    )
            self.update_dag_state(dag_id, final_state)
            logger.info("DAG run '%s' completed with final state: %s", dag_id, final_state.value)
        return self.get_dag(dag_id)  # type: ignore

    def cancel_dag(self, dag_id: str, reason: str = "Operator cancelled DAG") -> dict[str, Any]:
        """Cancels a running or pending DAG and all uncompleted steps."""
        now = time.time()
        with self.db.transaction() as c:
            c.execute("SELECT state FROM dag_runs WHERE id = ?", (dag_id,))
            row = c.fetchone()
            if not row:
                raise ValueError(f"DAG '{dag_id}' not found.")
            if row["state"] in (DAGState.SUCCEEDED.value, DAGState.FAILED.value, DAGState.CANCELLED.value):
                return self.get_dag(dag_id)  # type: ignore

            c.execute(
                "UPDATE dag_steps SET state = 'Cancelled', error = ?, updated_at = ? WHERE dag_id = ? AND state IN ('Pending', 'Running')",
                (reason, now, dag_id),
            )
            c.execute(
                "UPDATE dag_runs SET state = 'Cancelled', error = ?, updated_at = ? WHERE id = ?",
                (reason, now, dag_id),
            )
        logger.info("DAG '%s' cancelled: %s", dag_id, reason)
        return self.get_dag(dag_id)  # type: ignore

    @classmethod
    def get_pipeline_templates(cls) -> list[dict[str, Any]]:
        """Returns the library of predefined first-class multi-agent pipeline templates."""
        return [
            {
                "id": "analytics",
                "name": "Edge IoT Telemetry & Anomaly Analysis",
                "description": "Collaborative 3-agent pipeline: Data Analyst → Code Engineer → Systems Reporter",
                "steps": [
                    {
                        "step_id": "step_1_telemetry",
                        "goal": "Generate an edge IoT device server metrics CSV dataset with 12 hourly readings including timestamp, server_id, cpu_utilization, memory_mb, and packet_loss_rate",
                        "agent_id": "data_analyst",
                        "domain": "data",
                        "dependencies": [],
                    },
                    {
                        "step_id": "step_2_anomaly_detector",
                        "goal": "Write a Python script that loads the telemetry dataset, calculates mean and z-score spikes for cpu_utilization and packet_loss_rate, and prints an anomaly breakdown",
                        "agent_id": "code_engineer",
                        "domain": "code",
                        "dependencies": ["step_1_telemetry"],
                    },
                    {
                        "step_id": "step_3_executive_report",
                        "goal": "Compile a formal Executive Systems Health & Anomaly Briefing markdown report summarizing telemetry stability, detected anomalies, and operational mitigation recommendations",
                        "agent_id": "systems_reporter",
                        "domain": "report",
                        "dependencies": ["step_1_telemetry", "step_2_anomaly_detector"],
                    },
                ],
            },
            {
                "id": "3d_engineering",
                "name": "Procedural 3D Asset & Quality Assurance",
                "description": "Collaborative 3-agent pipeline: Blender Artisan → Code Engineer (QA) → Systems Reporter",
                "steps": [
                    {
                        "step_id": "step_1_mesh_synthesis",
                        "goal": "Synthesize a high-precision procedural sci-fi battle turret with rotating dual barrels and armored base mount in Blender 4.5",
                        "agent_id": "blender_artisan",
                        "domain": "3d",
                        "dependencies": [],
                    },
                    {
                        "step_id": "step_2_geometry_verification",
                        "goal": "Write a Python script that loads and verifies the 3D OBJ mesh file, computes bounding box dimensions, and verifies polygon topology",
                        "agent_id": "code_engineer",
                        "domain": "code",
                        "dependencies": ["step_1_mesh_synthesis"],
                    },
                    {
                        "step_id": "step_3_asset_briefing",
                        "goal": "Compile a formal Technical 3D Asset Inspection Sheet markdown document summarizing geometric specs, verification benchmarks, and rendering guidelines",
                        "agent_id": "systems_reporter",
                        "domain": "report",
                        "dependencies": ["step_1_mesh_synthesis", "step_2_geometry_verification"],
                    },
                ],
            },
            {
                "id": "system_audit",
                "name": "Host Filesystem & Infrastructure Audit",
                "description": "Collaborative 3-agent pipeline: Sensory Explorer → Code Engineer → Systems Reporter",
                "steps": [
                    {
                        "step_id": "step_1_disk_telemetry",
                        "goal": "Use sensory inspection to query host partition usage and export a structured disk consumption metrics CSV dataset",
                        "agent_id": "data_analyst",
                        "domain": "data",
                        "dependencies": [],
                    },
                    {
                        "step_id": "step_2_storage_analysis",
                        "goal": "Write a Python script to analyze storage trends, calculate free space risk thresholds, and rank top storage consumer directories",
                        "agent_id": "code_engineer",
                        "domain": "code",
                        "dependencies": ["step_1_disk_telemetry"],
                    },
                    {
                        "step_id": "step_3_executive_audit",
                        "goal": "Compile an Executive Infrastructure Storage & System Health Audit report with capacity forecasts and cleanup recommendations",
                        "agent_id": "systems_reporter",
                        "domain": "report",
                        "dependencies": ["step_1_disk_telemetry", "step_2_storage_analysis"],
                    },
                ],
            },
            {
                "id": "code_verification",
                "name": "Algorithm Synthesis & Rigorous Test Bench",
                "description": "Collaborative 3-agent pipeline: Code Engineer → Test Engineer → Systems Reporter",
                "steps": [
                    {
                        "step_id": "step_1_implementation",
                        "goal": "Synthesize a high-performance thread-safe LRU Cache with TTL expiration and clean exception handling in Python",
                        "agent_id": "code_engineer",
                        "domain": "code",
                        "dependencies": [],
                    },
                    {
                        "step_id": "step_2_test_bench",
                        "goal": "Synthesize a comprehensive unit test suite testing concurrent thread access, TTL eviction, and capacity edge cases",
                        "agent_id": "code_engineer",
                        "domain": "code",
                        "dependencies": ["step_1_implementation"],
                    },
                    {
                        "step_id": "step_3_qa_audit",
                        "goal": "Compile a Software Engineering QA & Benchmark Audit report detailing test coverage, performance characteristics, and algorithmic complexity",
                        "agent_id": "systems_reporter",
                        "domain": "report",
                        "dependencies": ["step_1_implementation", "step_2_test_bench"],
                    },
                ],
            },
        ]

    def instantiate_template(self, template_id: str) -> str:
        """Instantiates a pipeline from a known template ID."""
        templates = {t["id"]: t for t in self.get_pipeline_templates()}
        if template_id not in templates:
            raise ValueError(f"Unknown template ID '{template_id}'. Available: {list(templates.keys())}")

        tmpl = templates[template_id]
        step_defs = [
            DAGStepDefinition(
                step_id=s["step_id"],
                goal=s["goal"],
                agent_id=s["agent_id"],
                domain=s["domain"],
                dependencies=s.get("dependencies", []),
            )
            for s in tmpl["steps"]
        ]
        return self.create_dag(
            name=tmpl["name"],
            description=tmpl["description"],
            steps=step_defs,
        )

    @classmethod
    def create_predefined_analytics_pipeline(cls, orchestrator: DAGOrchestrator) -> str:
        """Backward-compatible helper creating the IoT analytics pipeline."""
        return orchestrator.instantiate_template("analytics")
