"""Sentinel Multi-Turn ReAct (Reason-Act-Observe-Reason) Controller.
Enables agents to interactively probe the environment, reason over real-time sensory/tool observations,
and execute multi-turn investigative workflows with monotonic lease fencing.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sentinel_broker.broker import ExecutionBroker
from sentinel_core.llm_gateway import LLMGateway

logger = logging.getLogger("sentinel.react")


@dataclass
class ReActStep:
    turn: int
    thought: str
    action: str | None = None
    action_input: dict[str, Any] | None = None
    observation: Any = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn": self.turn,
            "thought": self.thought,
            "action": self.action,
            "action_input": self.action_input,
            "observation": self.observation,
            "timestamp": self.timestamp,
        }


@dataclass
class ReActResult:
    success: bool
    final_answer: str
    turns_taken: int
    trajectory: list[ReActStep] = field(default_factory=list)
    artifact_path: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "final_answer": self.final_answer,
            "turns_taken": self.turns_taken,
            "trajectory": [s.to_dict() for s in self.trajectory],
            "artifact_path": self.artifact_path,
            "error": self.error,
        }


class ReActController:
    """Orchestrates an interactive Reason-Act-Observe-Reason loop with the host broker."""

    def __init__(
        self,
        broker: ExecutionBroker,
        llm_gateway: LLMGateway,
        max_turns: int = 8,
    ):
        self.broker = broker
        self.gateway = llm_gateway
        self.max_turns = max_turns

    def build_tool_catalog_prompt(self, agent_id: str | None = None) -> str:
        """Constructs tool catalog documentation formatted for ReAct agents."""
        import fnmatch
        tools = self.broker.tool_registry.list_tools()

        # If agent_id is provided, filter tools strictly to those granted in the agent manifest
        if agent_id and getattr(self.broker, "pdp", None) and getattr(self.broker.pdp, "agent_registry", None):
            manifest = self.broker.pdp.agent_registry.get_manifest(agent_id)
            if manifest and manifest.allowed_organs:
                allowed_set = set(manifest.allowed_organs)
                tools = [
                    t for t in tools
                    if any(pat == t["name"] or fnmatch.fnmatch(t["name"], pat) for pat in allowed_set)
                ]

        lines = ["You have access to the following host organs/tools:"]
        for t in tools:
            lines.append(f"\n- **`{t['name']}`**:")
            lines.append(f"  Description: {t['description']}")
            lines.append(f"  Parameters: {json.dumps(t['parameters_schema'])}")
            lines.append(f"  Effect: {t['effect_class']}")
        return "\n".join(lines)

    @staticmethod
    def _truncate_thought(thought: str, max_chars: int = 300) -> str:
        """Keeps thought concise so previous turns do not saturate context window."""
        t = thought.strip()
        if len(t) <= max_chars:
            return t
        period_idx = t.find(". ")
        if 20 <= period_idx <= max_chars:
            return t[:period_idx + 1]
        return t[:max_chars].rstrip() + "..."

    def parse_turn(self, text: str) -> tuple[str, str | None, dict[str, Any] | None, str | None]:
        """
        Parses agent output into (thought, action, action_input, final_answer).
        Handles:
        1. Final Answer: ...
        2. Action: <tool> \n Action Input: <json>
        3. Embedded JSON blocks: {"action": "...", "action_input": {...}}
        """
        clean_text = text.strip()

        # Strip <think>...</think> blocks if present to eliminate thinking loops
        if "<think>" in clean_text:
            post_think = re.sub(r"^.*?<\/think>\s*", "", clean_text, flags=re.DOTALL).strip()
            if post_think:
                clean_text = post_think
            else:
                clean_text = re.sub(r"<\/?think>", "", clean_text).strip()

        # Check for Final Answer first
        fa_match = re.search(r"Final Answer:\s*(.*)", clean_text, re.DOTALL | re.IGNORECASE)
        if fa_match:
            thought_part = clean_text[:fa_match.start()].strip()
            final_ans = fa_match.group(1).strip()
            # Clean "Thought:" prefix if present
            thought = re.sub(r"^Thought:\s*", "", thought_part, flags=re.IGNORECASE).strip()
            return self._truncate_thought(thought), None, None, final_ans

        # Check for standard ReAct: Action: <tool> \n Action Input: <json>
        action_match = re.search(r"Action:\s*([a-zA-Z0-9_\-]+)", clean_text, re.IGNORECASE)
        if action_match:
            action = action_match.group(1).strip()
            thought = clean_text[:action_match.start()].strip()
            thought = re.sub(r"^Thought:\s*", "", thought, flags=re.IGNORECASE).strip()

            # Find Action Input
            input_part = clean_text[action_match.end():].strip()
            input_match = re.search(r"Action Input:\s*(.*)", input_part, re.DOTALL | re.IGNORECASE)
            raw_input_str = input_match.group(1).strip() if input_match else input_part

            # Parse JSON from raw input string
            action_input = self._extract_json_dict(raw_input_str)
            return self._truncate_thought(thought), action, action_input, None

        # Check for JSON action payload: {"action": "...", "action_input": {...}}
        json_dict = self._extract_json_dict(clean_text)
        if json_dict and "action" in json_dict:
            action = str(json_dict["action"]).strip()
            action_input = json_dict.get("action_input", {})
            thought = json_dict.get("thought", "Executing requested tool action.")
            return self._truncate_thought(thought), action, action_input, None

        # If no action detected and no explicit Final Answer prefix, treat entire text as Final Answer
        return "", None, None, clean_text

    def _extract_json_dict(self, s: str) -> dict[str, Any]:
        """Safely extracts a JSON dictionary from string."""
        s = s.strip()
        # Look for ```json ... ```
        code_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", s, re.DOTALL)
        if code_block:
            try:
                return json.loads(code_block.group(1))
            except Exception:
                pass

        # Look for raw { ... }
        brace_block = re.search(r"(\{.*\})", s, re.DOTALL)
        if brace_block:
            try:
                return json.loads(brace_block.group(1))
            except Exception:
                pass

        # Fallback empty
        return {}

    def run_react_loop(
        self,
        task_id: str,
        attempt_id: str,
        lease_token: int,
        goal: str,
        agent_id: str = "systems_reporter",
        output_artifact_path: str | None = None,
        model: str | None = None,
        cancel_event: threading.Event | None = None,
    ) -> ReActResult:
        """
        Executes the multi-turn ReAct reasoning loop.
        Every tool invocation is strictly checked against the monotonic lease and PDP.
        """
        tool_catalog = self.build_tool_catalog_prompt(agent_id)

        system_instruction = (
            f"You are Sentinel Autonomous Agent '{agent_id}'.\n"
            "You solve problems interactively by Reasoning, Acting, and Observing real-time results.\n\n"
            f"{tool_catalog}\n\n"
            "PROTOCOL INSTRUCTIONS:\n"
            "For each turn, you must think briefly and either call an available tool OR deliver the Final Answer.\n"
            "Format your response EXACTLY as follows:\n\n"
            "To take an action:\n"
            "Thought: <at most 1-2 concise sentences stating the immediate tool needed and why>\n"
            "Action: <exact_tool_name>\n"
            "Action Input: {\"param_name\": \"value\"}\n\n"
            "When you have collected sufficient information to answer or complete the task:\n"
            "Thought: <1 concise sentence conclusion>\n"
            "Final Answer: <your full, detailed, professional Markdown report answering the user's goal>\n\n"
            "CRITICAL THINKING BUDGET & ANTI-LOOPING RULES:\n"
            "- Only call tools listed above.\n"
            "- Keep 'Thought:' strictly to 1 or 2 concise sentences. NEVER write long speculative monologues or simulate answers.\n"
            "- Ground truth comes from tool observations, not internal speculation.\n"
            "- Do NOT assume file system contents or invent data; inspect using sensory organs first.\n"
            "- Do NOT repeat past queries or loops. Once you have the facts, provide the comprehensive 'Final Answer:' immediately."
        )

        conversation_history = [
            f"User Goal: {goal}\nBegin your investigation. Take your first Action or deliver Final Answer."
        ]
        trajectory: list[ReActStep] = []

        logger.info("Starting ReAct loop for task '%s' (Agent: %s, Max Turns: %d)", task_id, agent_id, self.max_turns)

        for turn in range(1, self.max_turns + 1):
            if cancel_event and cancel_event.is_set():
                logger.warning("ReAct loop cancelled by operator for task '%s' at turn %d", task_id, turn)
                raise InterruptedError(f"Task '{task_id}' was cancelled by operator.")

            full_prompt = "\n\n".join(conversation_history)

            try:
                raw_response = self.gateway.generate(
                    prompt=full_prompt,
                    system=system_instruction,
                    model=model,
                    temperature=0.1,
                )
            except Exception as e:
                logger.error("LLM generation error on ReAct turn %d: %s", turn, e)
                return ReActResult(
                    success=False,
                    final_answer="",
                    turns_taken=turn,
                    trajectory=trajectory,
                    error=f"LLM generation failed: {e}",
                )

            thought, action, action_input, final_answer = self.parse_turn(raw_response)

            # Case 1: Agent has arrived at Final Answer
            if final_answer is not None:
                logger.info("ReAct agent concluded at turn %d with Final Answer (%d chars)", turn, len(final_answer))
                step = ReActStep(turn=turn, thought=thought or "Task objective achieved.", observation="FINAL_ANSWER")
                trajectory.append(step)

                if output_artifact_path:
                    try:
                        p = Path(output_artifact_path)
                        p.parent.mkdir(parents=True, exist_ok=True)
                        header = f"# Sentinel Autonomous Task Report: {goal}\n\n**Agent**: `{agent_id}` · **Turns**: {turn} · **Timestamp**: {time.ctime()}\n\n---\n\n"
                        p.write_text(header + final_answer + "\n", encoding="utf-8")
                        logger.info("ReAct final artifact written to: %s", output_artifact_path)
                    except Exception as err:
                        logger.warning("Failed to write ReAct final artifact: %s", err)

                return ReActResult(
                    success=True,
                    final_answer=final_answer,
                    turns_taken=turn,
                    trajectory=trajectory,
                    artifact_path=output_artifact_path,
                )

            # Case 2: Agent emitted an Action to execute
            if action:
                logger.info("Turn %d Action: '%s' with input: %s", turn, action, action_input)
                params = action_input or {}

                # Fenced Dispatch via Outside PDP
                call_res = self.broker.dispatch_call(
                    attempt_id=attempt_id,
                    lease_token=lease_token,
                    tool_name=action,
                    params=params,
                    context={"agent_id": agent_id, "allow_irreversible": False},
                )

                if not call_res.get("allowed", False):
                    observation = f"[PDP POLICY REJECTION]: {call_res.get('error', 'Action denied by security policy')}"
                elif call_res.get("status") == "TOOL_EXECUTION_ERROR":
                    observation = f"[TOOL EXECUTION ERROR]: {call_res.get('error')}"
                else:
                    observation_data = call_res.get("result", {})
                    # Bound observation size to prevent context saturation and thinking degeneration
                    obs_str = json.dumps(observation_data, default=str)
                    if len(obs_str) > 1200:
                        obs_str = obs_str[:1200] + f"... [TRUNCATED TELEMETRY: {len(obs_str) - 1200} chars omitted]"
                    observation = obs_str

                step = ReActStep(
                    turn=turn,
                    thought=thought,
                    action=action,
                    action_input=params,
                    observation=observation,
                )
                trajectory.append(step)

                # Feed thought, action, and observation back into conversation history
                turn_transcript = (
                    f"Thought: {thought}\n"
                    f"Action: {action}\n"
                    f"Action Input: {json.dumps(params)}\n"
                    f"Observation: {observation}"
                )
                conversation_history.append(turn_transcript)

            else:
                # If neither action nor clean final answer, remind model of protocol
                conversation_history.append(
                    f"Thought: {thought}\n"
                    "Observation: Invalid response format. You must specify either 'Action: <tool>\\nAction Input: {...}' or 'Final Answer: <markdown>'."
                )

        # Max Turns Exceeded: Force final synthesis
        logger.warning("ReAct loop reached turn budget (%d). Requesting synthesis...", self.max_turns)
        summary_prompt = (
            f"{full_prompt}\n\n"
            "SYSTEM NOTICE: Turn budget reached. Based on all the observations above, provide your 'Final Answer:' now."
        )
        try:
            forced_resp = self.gateway.generate(prompt=summary_prompt, system=system_instruction, model=model)
            _, _, _, forced_answer = self.parse_turn(forced_resp)
            final_text = forced_answer or forced_resp
        except Exception:
            final_text = "Task concluded after reaching turn budget. Observations collected in trajectory."

        if output_artifact_path:
            try:
                p = Path(output_artifact_path)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(f"# Sentinel Task Report (Max Turns): {goal}\n\n{final_text}\n", encoding="utf-8")
            except Exception:
                pass

        return ReActResult(
            success=True,
            final_answer=final_text,
            turns_taken=self.max_turns,
            trajectory=trajectory,
            artifact_path=output_artifact_path,
        )
