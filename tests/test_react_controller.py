import pytest
import threading
from pathlib import Path

from sentinel_core.db import SentinelDB
from sentinel_core.leases import LeaseManager
from sentinel_core.side_effects import SideEffectLedger, EffectClass
from sentinel_broker.tool_registry import ToolRegistry
from sentinel_broker.pdp import PolicyDecisionPoint
from sentinel_broker.broker import ExecutionBroker
from sentinel_broker.organs.sensory import register_sensory_organs
from sentinel_adaptive.react_controller import ReActController, ReActStep, ReActResult


class MockLLMGateway:
    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.call_history = []

    def generate(self, prompt: str, system: str | None = None, model: str | None = None, temperature: float = 0.1) -> str:
        self.call_history.append({"prompt": prompt, "system": system})
        if self.responses:
            return self.responses.pop(0)
        return "Final Answer: No further actions needed."


@pytest.fixture
def react_setup(tmp_path):
    db = SentinelDB(tmp_path / "react_test.db")
    leases = LeaseManager(db)
    tool_reg = ToolRegistry()
    register_sensory_organs(tool_reg)
    side_effects = SideEffectLedger(db)

    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir(parents=True, exist_ok=True)

    pdp = PolicyDecisionPoint(
        leases=leases,
        tool_registry=tool_reg,
        allowed_workspaces_dir=ws_dir,
    )
    broker = ExecutionBroker(pdp, tool_reg, side_effects)

    import time
    with db.transaction() as c:
        c.execute(
            "INSERT INTO tasks (id, title, state, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("task_react_test", "react test", "Running", time.time(), time.time()),
        )
    lease_rec = leases.allocate_next_lease("task_react_test", 1)

    return broker, lease_rec, ws_dir


def test_react_turn_parser_action(react_setup):
    broker, _, _ = react_setup
    mock_gw = MockLLMGateway([])
    controller = ReActController(broker, mock_gw)

    sample = (
        "Thought: I need to check the mounted drives to see how much space is free.\n"
        "Action: system_filesystem_inspect\n"
        'Action Input: {"mode": "list_drives"}'
    )
    thought, action, action_input, final_ans = controller.parse_turn(sample)

    assert "check the mounted drives" in thought
    assert action == "system_filesystem_inspect"
    assert action_input == {"mode": "list_drives"}
    assert final_ans is None


def test_react_turn_parser_final_answer(react_setup):
    broker, _, _ = react_setup
    mock_gw = MockLLMGateway([])
    controller = ReActController(broker, mock_gw)

    sample = (
        "Thought: I have gathered all necessary measurements.\n"
        "Final Answer: # Storage Audit Report\n\nDrive C has 102 GB free space."
    )
    thought, action, action_input, final_ans = controller.parse_turn(sample)

    assert "gathered all necessary" in thought
    assert action is None
    assert action_input is None
    assert final_ans == "# Storage Audit Report\n\nDrive C has 102 GB free space."


def test_react_turn_parser_json_block(react_setup):
    broker, _, _ = react_setup
    mock_gw = MockLLMGateway([])
    controller = ReActController(broker, mock_gw)

    sample = (
        '```json\n{"thought": "Scanning directory", "action": "system_filesystem_inspect", "action_input": {"mode": "find"}}\n```'
    )
    thought, action, action_input, final_ans = controller.parse_turn(sample)

    assert thought == "Scanning directory"
    assert action == "system_filesystem_inspect"
    assert action_input == {"mode": "find"}
    assert final_ans is None


def test_react_multiturn_investigative_loop(react_setup, tmp_path):
    broker, lease_rec, ws_dir = react_setup

    # Multi-turn sequence:
    # Turn 1: Inspect drives
    # Turn 2: Inspect largest files in Downloads
    # Turn 3: Deliver Final Answer
    mock_responses = [
        # Turn 1
        "Thought: Let me first inspect all connected system drives.\n"
        "Action: system_filesystem_inspect\n"
        'Action Input: {"mode": "list_drives"}',

        # Turn 2
        "Thought: Drive C has good capacity, now let me locate the largest files in downloads.\n"
        "Action: system_filesystem_inspect\n"
        'Action Input: {"mode": "largest_files", "path": "downloads", "limit": 3}',

        # Turn 3
        "Thought: I now have the exact largest files.\n"
        "Final Answer: # Executive File Audit\n\nThe largest file found is Bazzite ISO with 7.52 GB.",
    ]

    mock_gw = MockLLMGateway(mock_responses)
    controller = ReActController(broker, mock_gw, max_turns=5)

    artifact_out = ws_dir / "audit_report.md"
    result = controller.run_react_loop(
        task_id="task_react_test",
        attempt_id=lease_rec.attempt_id,
        lease_token=lease_rec.lease_token,
        goal="Find the largest file in downloads",
        agent_id="systems_reporter",
        output_artifact_path=str(artifact_out),
    )

    assert result.success is True
    assert result.turns_taken == 3
    assert len(result.trajectory) == 3

    # Turn 1 step
    assert result.trajectory[0].action == "system_filesystem_inspect"
    assert "drives" in result.trajectory[0].observation

    # Turn 2 step
    assert result.trajectory[1].action == "system_filesystem_inspect"
    assert "largest_files" in result.trajectory[1].observation

    # Turn 3 step
    assert result.trajectory[2].observation == "FINAL_ANSWER"
    assert "The largest file found is Bazzite ISO" in result.final_answer

    # Verify physical artifact creation
    assert artifact_out.exists()
    content = artifact_out.read_text(encoding="utf-8")
    assert "# Sentinel Autonomous Task Report:" in content
    assert "The largest file found is Bazzite ISO with 7.52 GB." in content


def test_react_pdp_rejection_recovery(react_setup):
    broker, lease_rec, _ = react_setup

    # Register an unauthorized tool
    @broker.tool_registry.register(
        name="unauthorized_file_overwrite",
        description="Dangerous tool",
        effect_class=EffectClass.IRREVERSIBLE,
        parameters_schema={},
    )
    def unauthorized_tool(params, ctx):
        return {"done": True}

    # Turn 1: Attempts forbidden irreversible action -> PDP blocks it!
    # Turn 2: Agent observes rejection and delivers safe Final Answer
    mock_responses = [
        "Thought: I want to wipe disk directly.\n"
        "Action: unauthorized_file_overwrite\n"
        'Action Input: {}',

        "Thought: PDP policy rejected my irreversible action. I will deliver a safe report instead.\n"
        "Final Answer: Action blocked by policy, system safely inspected.",
    ]

    mock_gw = MockLLMGateway(mock_responses)
    controller = ReActController(broker, mock_gw, max_turns=3)

    result = controller.run_react_loop(
        task_id="task_react_test",
        attempt_id=lease_rec.attempt_id,
        lease_token=lease_rec.lease_token,
        goal="Perform action",
        agent_id="systems_reporter",
    )

    assert result.success is True
    assert result.turns_taken == 2
    # Turn 1 observation must reflect PDP rejection
    assert "[PDP POLICY REJECTION]" in result.trajectory[0].observation
    assert "Action blocked by policy" in result.final_answer


def test_react_cancellation(react_setup):
    broker, lease_rec, _ = react_setup

    cancel_evt = threading.Event()
    cancel_evt.set()  # Cancel immediately

    mock_gw = MockLLMGateway(["Action: system_filesystem_inspect\nAction Input: {}"])
    controller = ReActController(broker, mock_gw, max_turns=5)

    with pytest.raises(InterruptedError, match="cancelled by operator"):
        controller.run_react_loop(
            task_id="task_react_test",
            attempt_id=lease_rec.attempt_id,
            lease_token=lease_rec.lease_token,
            goal="Test cancellation",
            cancel_event=cancel_evt,
        )
