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
    format_predecessor_artifacts,
)
from sentinel_core.dag_planner import DAGPlanner


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


def test_concurrent_wave_execution(test_db):
    import time
    orch = DAGOrchestrator(test_db)

    # Diamond workflow: A -> (B, C) -> D
    steps = [
        DAGStepDefinition("step_a", "Generate Input", "data_analyst", "data"),
        DAGStepDefinition("step_b", "Branch B", "code_engineer", "code", dependencies=["step_a"]),
        DAGStepDefinition("step_c", "Branch C", "code_engineer", "code", dependencies=["step_a"]),
        DAGStepDefinition("step_d", "Merge Result", "systems_reporter", "analysis", dependencies=["step_b", "step_c"]),
    ]
    dag_id = orch.create_dag("Diamond Concurrent Test", "Testing parallel waves", steps)

    execution_log = []

    def mock_concurrent_executor(step, pred_artifacts):
        s_id = step["step_id"]
        execution_log.append(f"start_{s_id}")
        time.sleep(0.05)
        execution_log.append(f"finish_{s_id}")
        return {
            "success": True,
            "task_id": f"task_{s_id}",
            "artifact_path": f"/workspaces/{s_id}.out",
        }

    res = orch.execute_dag(dag_id, mock_concurrent_executor, concurrent=True, max_workers=4)
    assert res["state"] == DAGState.SUCCEEDED.value

    # Verify that all steps succeeded
    updated = orch.get_dag(dag_id)
    assert all(s["state"] == DAGStepState.SUCCEEDED.value for s in updated["steps"])

    # Step A must start and finish first
    assert execution_log[0] == "start_step_a"
    assert execution_log[1] == "finish_step_a"

    # Step D must finish last
    assert execution_log[-1] == "finish_step_d"


def test_pipeline_template_catalog(test_db):
    orch = DAGOrchestrator(test_db)
    templates = orch.get_pipeline_templates()
    assert len(templates) >= 4

    template_ids = [t["id"] for t in templates]
    assert "analytics" in template_ids
    assert "3d_engineering" in template_ids
    assert "system_audit" in template_ids
    assert "code_verification" in template_ids

    # Instantiate each and verify valid DAG
    for tid in template_ids:
        dag_id = orch.instantiate_template(tid)
        dag = orch.get_dag(dag_id)
        assert dag is not None
        assert len(dag["steps"]) >= 2
        assert dag["state"] == DAGState.PENDING.value


def test_format_predecessor_artifacts(tmp_path):
    # 1. Mock OBJ 3D Mesh
    obj_p = tmp_path / "mesh.obj"
    obj_p.write_text("v 0.0 0.0 0.0\nv 1.0 0.0 0.0\nv 0.0 1.0 0.0\nf 1 2 3\n", encoding="utf-8")

    # 2. Mock CSV
    csv_p = tmp_path / "data.csv"
    csv_p.write_text("server_id,cpu,memory\nsrv_1,45.2,1024\nsrv_2,55.0,2048\n", encoding="utf-8")

    # 3. Mock Python Code
    py_p = tmp_path / "logic.py"
    py_p.write_text("class AnomalyDetector:\n    def detect(self):\n        pass\n", encoding="utf-8")

    ctx = format_predecessor_artifacts({
        "step_1": str(obj_p),
        "step_2": str(csv_p),
        "step_3": str(py_p),
    })

    assert "3 vertices, 1 polygon faces" in ctx
    assert "Columns (3): server_id, cpu, memory" in ctx
    assert "class AnomalyDetector" in ctx


def test_dag_planner_heuristic():
    # 1. 3D Goal
    name_3d, _, steps_3d = DAGPlanner.decompose_goal("Create a futuristic warhammer 3d model in blender and audit topology")
    assert any(s.agent_id == "blender_artisan" for s in steps_3d)
    assert any(s.agent_id == "code_engineer" for s in steps_3d)
    assert any(s.agent_id == "systems_reporter" for s in steps_3d)

    # 2. Data Goal
    name_data, _, steps_data = DAGPlanner.decompose_goal("Generate server telemetry metrics dataset and find anomalies")
    assert steps_data[0].agent_id == "data_analyst"
    assert steps_data[1].agent_id == "code_engineer"

    # 3. Code Goal
    name_code, _, steps_code = DAGPlanner.decompose_goal("Write a thread-safe LRU cache algorithm in python with unit test suite")
    assert steps_code[0].domain == "code"
    assert steps_code[1].agent_id == "code_engineer"

