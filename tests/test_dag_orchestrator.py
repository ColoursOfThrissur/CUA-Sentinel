import pytest
from pathlib import Path
from sentinel_core.db import SentinelDB
from sentinel_core.dag_orchestrator import (
    DAGOrchestrator,
    DAGStepDefinition,
    DAGValidationError,
    validate_and_sort_dag,
    DAGState,
    DAGStepState,
)


@pytest.fixture
def test_db(tmp_path: Path):
    db_file = tmp_path / "test_sentinel_dag.db"
    return SentinelDB(db_file)


def test_topological_sort_valid():
    steps = [
        DAGStepDefinition("step_c", "Report", "systems_reporter", "analysis", dependencies=["step_b"]),
        DAGStepDefinition("step_a", "Data", "data_analyst", "data"),
        DAGStepDefinition("step_b", "Code", "code_engineer", "code", dependencies=["step_a"]),
    ]
    order = validate_and_sort_dag(steps)
    assert order == ["step_a", "step_b", "step_c"]


def test_topological_sort_diamond():
    # Diamond graph:
    #      A
    #     / \
    #    B   C
    #     \ /
    #      D
    steps = [
        DAGStepDefinition("step_d", "Final", "systems_reporter", "analysis", dependencies=["step_b", "step_c"]),
        DAGStepDefinition("step_a", "Start", "data_analyst", "data"),
        DAGStepDefinition("step_b", "Branch 1", "code_engineer", "code", dependencies=["step_a"]),
        DAGStepDefinition("step_c", "Branch 2", "code_engineer", "code", dependencies=["step_a"]),
    ]
    order = validate_and_sort_dag(steps)
    assert order[0] == "step_a"
    assert set(order[1:3]) == {"step_b", "step_c"}
    assert order[3] == "step_d"


def test_topological_sort_cycle():
    steps = [
        DAGStepDefinition("step_a", "Step A", "data_analyst", "data", dependencies=["step_b"]),
        DAGStepDefinition("step_b", "Step B", "code_engineer", "code", dependencies=["step_a"]),
    ]
    with pytest.raises(DAGValidationError, match="Cycle detected"):
        validate_and_sort_dag(steps)


def test_topological_sort_missing_dependency():
    steps = [
        DAGStepDefinition("step_a", "Step A", "data_analyst", "data", dependencies=["non_existent_step"]),
    ]
    with pytest.raises(DAGValidationError, match="non-existent dependency"):
        validate_and_sort_dag(steps)


def test_topological_sort_self_dependency():
    steps = [
        DAGStepDefinition("step_a", "Step A", "data_analyst", "data", dependencies=["step_a"]),
    ]
    with pytest.raises(DAGValidationError, match="cannot depend on itself"):
        validate_and_sort_dag(steps)


def test_dag_orchestrator_lifecycle(test_db):
    orch = DAGOrchestrator(test_db)

    steps = [
        DAGStepDefinition("step_1", "Generate data", "data_analyst", "data"),
        DAGStepDefinition("step_2", "Analyze data", "code_engineer", "code", dependencies=["step_1"]),
    ]

    dag_id = orch.create_dag("Pipeline Alpha", "Test DAG", steps)
    assert dag_id.startswith("dag_")

    dag = orch.get_dag(dag_id)
    assert dag is not None
    assert dag["name"] == "Pipeline Alpha"
    assert dag["state"] == DAGState.PENDING.value
    assert len(dag["steps"]) == 2

    # Execute DAG with mock executor
    captured_predecessors = {}

    def mock_executor(step, pred_artifacts):
        s_id = step["step_id"]
        captured_predecessors[s_id] = pred_artifacts
        return {
            "success": True,
            "task_id": f"task_{s_id}",
            "artifact_path": f"/workspaces/{s_id}.out",
        }

    res = orch.execute_dag(dag_id, mock_executor)
    assert res["state"] == DAGState.SUCCEEDED.value
    assert captured_predecessors["step_1"] == {}
    assert captured_predecessors["step_2"] == {"step_1": "/workspaces/step_1.out"}

    updated_dag = orch.get_dag(dag_id)
    assert all(s["state"] == DAGStepState.SUCCEEDED.value for s in updated_dag["steps"])


def test_dag_orchestrator_failure_cascades(test_db):
    orch = DAGOrchestrator(test_db)

    steps = [
        DAGStepDefinition("step_1", "Step 1", "data_analyst", "data"),
        DAGStepDefinition("step_2", "Step 2", "code_engineer", "code", dependencies=["step_1"]),
        DAGStepDefinition("step_3", "Step 3", "systems_reporter", "analysis", dependencies=["step_2"]),
    ]

    dag_id = orch.create_dag("Failing Pipeline", "Testing skips", steps)

    def mock_failing_executor(step, pred_artifacts):
        if step["step_id"] == "step_1":
            return {"success": False, "error": "Verification timeout"}
        return {"success": True, "artifact_path": "dummy.txt"}

    res = orch.execute_dag(dag_id, mock_failing_executor)
    assert res["state"] == DAGState.FAILED.value

    updated_dag = orch.get_dag(dag_id)
    steps_map = {s["step_id"]: s for s in updated_dag["steps"]}
    assert steps_map["step_1"]["state"] == DAGStepState.FAILED.value
    assert steps_map["step_2"]["state"] == DAGStepState.SKIPPED.value
    assert steps_map["step_3"]["state"] == DAGStepState.SKIPPED.value


def test_predefined_analytics_pipeline(test_db):
    orch = DAGOrchestrator(test_db)
    dag_id = DAGOrchestrator.create_predefined_analytics_pipeline(orch)
    dag = orch.get_dag(dag_id)
    assert dag is not None
    assert len(dag["steps"]) == 3
    assert dag["steps"][0]["agent_id"] == "data_analyst"
    assert dag["steps"][1]["agent_id"] == "code_engineer"
    assert dag["steps"][2]["agent_id"] == "systems_reporter"
