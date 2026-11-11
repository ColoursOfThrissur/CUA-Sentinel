"""Sentinel Bounded 3-Attempt Adaptive Pilot Controller.
Coordinates episodic mistake learning, feedback injection, and skill distillation.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from sentinel_core.state_machine import StateMachine, TaskRecord, TaskState
from sentinel_core.verification_gate import VerificationGate, VerificationResult
from sentinel_adaptive.mistake_ledger import MistakeMemory
from sentinel_adaptive.skill_bank import SkillBank

logger = logging.getLogger("SentinelPilot")


@dataclass
class PilotExecutionResult:
    task: TaskRecord
    attempts_taken: int
    success: bool
    distilled_skill: dict[str, Any] | None
    mistakes_encountered: list[dict[str, Any]]


class AdaptivePilotController:
    def __init__(
        self,
        state_machine: StateMachine,
        verification_gate: VerificationGate,
        mistake_memory: MistakeMemory,
        skill_bank: SkillBank,
    ):
        self.state_machine = state_machine
        self.verification_gate = verification_gate
        self.mistake_memory = mistake_memory
        self.skill_bank = skill_bank

    def run_task(
        self,
        task_id: str,
        goal: str,
        worker_executor: Callable[[str, int, str], dict[str, Any]],
        verifier: Callable[[dict[str, Any]], VerificationResult],
        skill_distillation_name: str | None = None,
        max_attempts: int = 3,
        domain: str = "",
        llm_gateway: Any | None = None,
    ) -> PilotExecutionResult:
        """Executes a bounded pilot loop with automatic mistake capture and adaptive re-planning."""
        # 1. Initialize Task in State Machine
        self.state_machine.create_task(task_id, title=goal, max_attempts=max_attempts)
        attempts_taken = 0
        distilled = None

        while True:
            # 2. Check if we have previous mistakes or cross-task heuristics to formulate negative prompt constraints
            anti_patterns = self.mistake_memory.format_anti_pattern_prompt(task_id, domain=domain)

            # 3. Start Next Attempt (allocates monotonic lease)
            task, lease = self.state_machine.start_next_attempt(task_id)
            attempts_taken = task.attempt_count

            # 4. Invoke Worker with Goal + Adaptive Anti-Pattern Constraints
            worker_output = worker_executor(goal, attempts_taken, anti_patterns)

            # 5. Transition to Verifying State
            self.state_machine.transition_to_verifying(task_id, lease.attempt_id, lease.lease_token)

            # 6. Objective Verification Gate (FR-024)
            v_res = verifier(worker_output)

            if v_res.passed:
                # 7a. Verification Passed -> Atomic Success Commit (AT-D-08)
                task = self.state_machine.commit_success(task_id, lease.attempt_id, lease.lease_token)

                # Plasticity: Distill successful pattern into Skill Bank
                if skill_distillation_name and "synthesized_code" in worker_output:
                    distilled = self.skill_bank.distill_skill(
                        name=skill_distillation_name,
                        description=f"Auto-synthesized skill for: {goal}",
                        code=worker_output["synthesized_code"],
                        domain=domain or "",
                        parameters_schema=worker_output.get("parameters_schema", {}),
                    )

                return PilotExecutionResult(
                    task=task,
                    attempts_taken=attempts_taken,
                    success=True,
                    distilled_skill=distilled,
                    mistakes_encountered=self.mistake_memory.get_task_mistakes(task_id),
                )
            else:
                # 7b. Verification Failed -> Record Defect to Episodic Memory (with semantic LLM classification if available)
                stderr_text = v_res.details.get("stderr") if isinstance(v_res.details, dict) else ""
                if llm_gateway and stderr_text:
                    self.mistake_memory.classify_and_record_semantic_mistake(
                        task_id=task_id,
                        attempt_id=lease.attempt_id,
                        raw_traceback=stderr_text,
                        llm_gateway=llm_gateway,
                        domain=domain,
                    )
                else:
                    self.mistake_memory.record_mistake(
                        task_id=task_id,
                        attempt_id=lease.attempt_id,
                        error_category=v_res.error_category or "VERIFICATION_FAILURE",
                        error_signature=v_res.error_signature or "UnknownDefect",
                        context=v_res.details,
                        lesson_learned=v_res.lesson or "Fix the defect according to verification rule.",
                    )

                # State Machine handles retry transition or terminal failure
                task, can_retry = self.state_machine.handle_verification_failure(
                    task_id=task_id,
                    attempt_id=lease.attempt_id,
                    lease_token=lease.lease_token,
                    reason=f"Verification failed: {v_res.error_signature}",
                )

                if not can_retry:
                    # Max attempts exhausted
                    return PilotExecutionResult(
                        task=task,
                        attempts_taken=attempts_taken,
                        success=False,
                        distilled_skill=None,
                        mistakes_encountered=self.mistake_memory.get_task_mistakes(task_id),
                    )
