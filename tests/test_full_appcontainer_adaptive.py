"""End-to-End Integration Test: Adaptive Pilot with real Windows AppContainer isolation."""
import pytest
from pathlib import Path
import tempfile
import shutil

from sentinel_core.db import SentinelDB
from sentinel_core.state_machine import StateMachine, TaskState
from sentinel_core.verification_gate import VerificationGate, VerificationResult
from sentinel_core.side_effects import SideEffectLedger, EffectClass
from sentinel_broker.tool_registry import ToolRegistry
from sentinel_broker.pdp import PolicyDecisionPoint
from sentinel_broker.broker import ExecutionBroker
from sentinel_adaptive.mistake_ledger import MistakeMemory
from sentinel_adaptive.skill_bank import SkillBank
from sentinel_adaptive.pilot_controller import AdaptivePilotController
from sentinel_runner.appcontainer_host import AppContainerHost


@pytest.fixture
def full_system():
    temp_dir = Path(tempfile.mkdtemp())
    db = SentinelDB(temp_dir / "full_system.db")
    sm = StateMachine(db)
    gate = VerificationGate(db)
    side_effects = SideEffectLedger(db)
    memory = MistakeMemory(db)
    skills_dir = temp_dir / "skills"
    workspaces_dir = temp_dir / "workspaces"
    skill_bank = SkillBank(db, skills_dir)
    
    # Tool Registry & Broker
    registry = ToolRegistry()
    @registry.register("echo_verify", "Echoes nonce for verification", EffectClass.READ_ONLY)
    def echo_verify(params, ctx):
        return {"nonce": params.get("nonce", "none"), "verified": True}

    pdp = PolicyDecisionPoint(sm.leases, registry)
    broker = ExecutionBroker(pdp, registry, side_effects)

    staging_runtime = Path(r"c:\Users\derik\Desktop\Derik\Projects\Sentinel\spikes\s1_isolation_win11\staging_runtime")
    host = AppContainerHost(staging_runtime, workspaces_dir)
    pilot = AdaptivePilotController(sm, gate, memory, skill_bank)

    yield pilot, host, broker, gate, temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_full_appcontainer_adaptive_learning_cycle(full_system):
    pilot, host, broker, gate, temp_dir = full_system

    task_id = "task_e2e_appcontainer"
    goal = "Create verified artifact with host nonce verification"

    # Define worker executor connecting the pilot to AppContainerHost
    def appcontainer_executor(task_goal: str, attempt_num: int, anti_patterns: str) -> dict:
        # Retrieve the currently active attempt record
        active_attempt = pilot.state_machine.db.execute_one(
            "SELECT id, lease_token FROM attempts WHERE task_id = ? AND status = 'Active'",
            (task_id,),
        )
        assert active_attempt is not None
        att_id = active_attempt["id"]
        lease = active_attempt["lease_token"]

        return host.run_worker_attempt(
            task_id=task_id,
            attempt_id=att_id,
            lease_token=lease,
            goal=task_goal,
            attempt_num=attempt_num,
            anti_patterns=anti_patterns,
            broker=broker,
            timeout_sec=15.0,
        )

    # Verification Gate: Checks that artifact exists and contains valid data
    def artifact_verifier(worker_output: dict) -> VerificationResult:
        p = Path(worker_output.get("artifact_path", ""))
        return gate.verify_file_exists(p, min_bytes=20)

    # Run the adaptive pilot loop
    result = pilot.run_task(
        task_id=task_id,
        goal=goal,
        worker_executor=appcontainer_executor,
        verifier=artifact_verifier,
        skill_distillation_name="verified_artifact_generator",
        max_attempts=3,
    )

    # Assertions
    assert result.success is True
    assert result.attempts_taken == 2  # Attempt 1 failed; Attempt 2 adapted & passed!
    assert result.task.state == TaskState.SUCCEEDED
    assert len(result.mistakes_encountered) == 1
    assert result.mistakes_encountered[0]["error_category"] == "EMPTY_ARTIFACT"
    assert result.distilled_skill is not None
    assert result.distilled_skill["name"] == "verified_artifact_generator"
