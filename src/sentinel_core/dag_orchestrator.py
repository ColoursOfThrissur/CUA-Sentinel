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
    ) -> dict[str, Any]:
        """
        Executes all steps of a DAG in topological order.
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

        for step_id in order:
            # Check if entire DAG was cancelled asynchronously
            current_dag = self.get_dag(dag_id)
            if current_dag and current_dag.get("state") == DAGState.CANCELLED.value:
                logger.info("DAG '%s' was cancelled; aborting remaining steps.", dag_id)
                has_failure = True
                break

            step = steps_dict[step_id]
            deps = step["dependencies"]

            # Check if any dependency failed or was skipped
            prereq_failed = any(
                steps_dict[d]["state"] in (DAGStepState.FAILED.value, DAGStepState.SKIPPED.value)
                for d in deps
            )
            if prereq_failed:
                logger.warning("Step '%s' skipped because a prerequisite dependency failed.", step_id)
                self.update_step_state(dag_id, step_id, DAGStepState.SKIPPED, error="Prerequisite step failed")
                steps_dict[step_id]["state"] = DAGStepState.SKIPPED.value
                has_failure = True
                continue

            # Assemble predecessor artifacts for context
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

        curr = self.get_dag(dag_id)
        if curr and curr.get("state") != DAGState.CANCELLED.value:
            final_state = DAGState.FAILED if has_failure else DAGState.SUCCEEDED
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
    def create_predefined_analytics_pipeline(cls, orchestrator: DAGOrchestrator) -> str:
        """
        Creates an end-to-end 3-step analytical & intelligence pipeline:
        1. Data Analyst (data): Synthesize edge telemetry sensor CSV dataset.
        2. Code Engineer (code): Synthesize Python statistical anomaly detection script.
        3. Systems Reporter (analysis): Compile comprehensive executive markdown briefing.
        """
        steps = [
            DAGStepDefinition(
                step_id="step_1_telemetry",
                goal="Generate an edge IoT device server metrics CSV dataset with 12 hourly readings including timestamp, server_id, cpu_utilization, memory_mb, and packet_loss_rate",
                agent_id="data_analyst",
                domain="data",
            ),
            DAGStepDefinition(
                step_id="step_2_anomaly_detector",
                goal="Write a Python script that loads the telemetry dataset, calculates mean and z-score spikes for cpu_utilization and packet_loss_rate, and prints an anomaly breakdown",
                agent_id="code_engineer",
                domain="code",
                dependencies=["step_1_telemetry"],
            ),
            DAGStepDefinition(
                step_id="step_3_executive_report",
                goal="Compile a formal Executive Systems Health & Anomaly Briefing markdown report summarizing telemetry stability, detected anomalies, and operational mitigation recommendations",
                agent_id="systems_reporter",
                domain="analysis",
                dependencies=["step_1_telemetry", "step_2_anomaly_detector"],
            ),
        ]
        return orchestrator.create_dag(
            name="Edge IoT Telemetry & Anomaly Analysis Pipeline",
            description="Collaborative 3-agent pipeline: Data Analyst → Code Engineer → Systems Reporter",
            steps=steps,
        )
