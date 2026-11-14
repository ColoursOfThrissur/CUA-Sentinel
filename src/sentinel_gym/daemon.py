"""Sentinel Autonomous 5-Hour Gymnasium Daemon.
Orchestrates continuous background self-play, empirical sensory inspection,
critic evaluation, and skill plasticity. Supports graceful stop tokens, thermal breathing,
and automated snapshot cache pruning.
"""
from __future__ import annotations

import logging
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from sentinel_gym.sensor_rig import BlenderSensorRig, CSVSensorRig
from sentinel_gym.critic import HarshCritic, CriticScorecard
from sentinel_gym.curriculum import CurriculumGenerator, CurriculumChallenge
from sentinel_gym.auto_refiner import AutoRefiner, RefinementOutcome
from sentinel_ui.telemetry_stream import broadcaster

logger = logging.getLogger("SentinelGymDaemon")


@dataclass
class GymCycleRecord:
    cycle_index: int
    challenge_id: str
    goal: str
    domain: str
    score: float
    passed: bool
    critique: str
    action_taken: str
    skill_or_mistake: str | None
    timestamp: float
    snapshots: dict[str, str] = field(default_factory=dict)


class GymnasiumDaemon:
    """Autonomous self-play training loop that runs for up to N hours or until operator stop."""

    def __init__(
        self,
        sensor_rig: BlenderSensorRig,
        critic: HarshCritic,
        curriculum: CurriculumGenerator,
        auto_refiner: AutoRefiner,
        task_executor_fn: Callable[[str, str, str], dict[str, Any]],
        workspaces_dir: Path | str,
        inter_cycle_delay_sec: float = 3.0,
    ):
        self.sensor_rig = sensor_rig
        self.critic = critic
        self.curriculum = curriculum
        self.auto_refiner = auto_refiner
        self.task_executor_fn = task_executor_fn
        self.workspaces_dir = Path(workspaces_dir).resolve()
        self.inter_cycle_delay_sec = inter_cycle_delay_sec

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._is_running = False
        self._start_time: float = 0.0
        self._max_duration_sec: float = 5.0 * 3600.0  # 5 hours default

        self.completed_cycles: list[GymCycleRecord] = []
        self.skills_evolved_count = 0
        self.anti_patterns_recorded_count = 0
        self.current_cycle_info: dict[str, Any] | None = None

    @property
    def is_running(self) -> bool:
        return self._is_running and (self._thread is not None and self._thread.is_alive())

    def get_status(self) -> dict[str, Any]:
        elapsed = (time.time() - self._start_time) if self._is_running else 0.0
        remaining = max(0.0, self._max_duration_sec - elapsed) if self._is_running else 0.0
        avg_score = (
            sum(c.score for c in self.completed_cycles) / len(self.completed_cycles)
            if self.completed_cycles
            else 0.0
        )
        return {
            "is_running": self.is_running,
            "elapsed_seconds": round(elapsed, 1),
            "remaining_seconds": round(remaining, 1),
            "total_cycles_completed": len(self.completed_cycles),
            "skills_evolved_count": self.skills_evolved_count,
            "anti_patterns_recorded_count": self.anti_patterns_recorded_count,
            "average_score": round(avg_score, 3),
            "current_cycle": self.current_cycle_info,
            "recent_cycles": [
                {
                    "cycle": c.cycle_index,
                    "goal": c.goal,
                    "domain": c.domain,
                    "score": c.score,
                    "passed": c.passed,
                    "action": c.action_taken,
                    "critique": c.critique,
                    "snapshots": c.snapshots,
                }
                for c in self.completed_cycles[-5:]
            ],
        }

    def start(self, max_duration_hours: float = 5.0):
        if self.is_running:
            logger.warning("GymnasiumDaemon is already active.")
            return

        self._stop_event.clear()
        self._max_duration_sec = max_duration_hours * 3600.0
        self._start_time = time.time()
        self._is_running = True

        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="SentinelGymDaemon")
        self._thread.start()
        logger.info("GymnasiumDaemon started for max %.1f hours.", max_duration_hours)
        broadcaster.emit("gym_status", {"state": "STARTED", "max_hours": max_duration_hours})

    def stop(self):
        if not self._is_running:
            return
        logger.info("Stopping GymnasiumDaemon on operator request...")
        self._stop_event.set()
        self._is_running = False
        broadcaster.emit("gym_status", {"state": "STOPPED"})

    def _run_loop(self):
        cycle_idx = 0
        try:
            while not self._stop_event.is_set():
                elapsed = time.time() - self._start_time
                if elapsed >= self._max_duration_sec:
                    logger.info("GymnasiumDaemon reached duration limit (%.1fs). Ending self-play.", elapsed)
                    break

                cycle_idx += 1
                self._run_single_cycle(cycle_idx)

                # Thermal breathing delay
                if not self._stop_event.is_set():
                    time.sleep(self.inter_cycle_delay_sec)

        except Exception as e:
            logger.error("GymnasiumDaemon encountered loop error: %s", e, exc_info=True)
        finally:
            self._is_running = False
            self.current_cycle_info = None
            logger.info("GymnasiumDaemon stopped. Completed %d cycles.", len(self.completed_cycles))
            broadcaster.emit("gym_status", {"state": "TERMINATED", "cycles": len(self.completed_cycles)})

    def _run_single_cycle(self, cycle_idx: int):
        # 1. Generate challenge from curiosity frontier
        challenge = self.curriculum.generate_next_challenge(domain="3d")
        self.current_cycle_info = {
            "cycle": cycle_idx,
            "goal": challenge.goal,
            "domain": challenge.domain,
            "category": challenge.category,
            "started_at": time.time(),
        }
        broadcaster.emit("gym_cycle_start", self.current_cycle_info)

        task_id = f"gym_t{cycle_idx}_{int(time.time())}"
        attempt_id = f"att_{task_id}_1"

        try:
            # 2. Execute Task in Sandboxed Runtime
            exec_res = self.task_executor_fn(task_id, challenge.goal, challenge.domain)
            artifact_path = exec_res.get("artifact_path")
            synthesized_code = exec_res.get("synthesized_code", "")

            # 3. Empirical Multi-Modal Inspection
            scorecard: CriticScorecard
            snapshots: dict[str, str] = {}

            if challenge.domain == "3d" and artifact_path and Path(artifact_path).exists():
                insp = self.sensor_rig.inspect_model(artifact_path)
                snapshots = insp.snapshots
                scorecard = self.critic.evaluate_3d_model(challenge.goal, insp)
            elif challenge.domain == "data" and artifact_path and Path(artifact_path).exists():
                csv_insp = CSVSensorRig.inspect_csv(artifact_path)
                scorecard = self.critic.evaluate_csv_dataset(challenge.goal, csv_insp)
            else:
                scorecard = CriticScorecard(
                    score=0.10,
                    passed=False,
                    structural_integrity=0,
                    feature_specificity=0,
                    material_separation=0,
                    proportion_realism=0,
                    critique="Task failed to produce any valid artifact file on disk.",
                    remediation_advice="Ensure execution writes target file.",
                    anti_pattern_signature="MISSING_OUTPUT_ARTIFACT",
                    evaluation_mode="degenerate_bypass",
                )

            # 4. Auto-Refinement: Distill or Record Anti-Pattern
            refinement = self.auto_refiner.process_evaluation(
                task_id=task_id,
                attempt_id=attempt_id,
                goal=challenge.goal,
                domain=challenge.domain,
                code_or_script=synthesized_code,
                scorecard=scorecard,
                artifact_path=artifact_path,
            )

            if refinement.action_taken == "SKILL_DISTILLED":
                self.skills_evolved_count += 1
            elif refinement.action_taken == "ANTI_PATTERN_RECORDED":
                self.anti_patterns_recorded_count += 1

            # 5. Record Cycle Completion
            rec = GymCycleRecord(
                cycle_index=cycle_idx,
                challenge_id=challenge.challenge_id,
                goal=challenge.goal,
                domain=challenge.domain,
                score=scorecard.score,
                passed=scorecard.passed,
                critique=scorecard.critique,
                action_taken=refinement.action_taken,
                skill_or_mistake=refinement.skill_name or (f"Mistake #{refinement.mistake_id}" if refinement.mistake_id else None),
                timestamp=time.time(),
                snapshots=snapshots,
            )
            self.completed_cycles.append(rec)

            broadcaster.emit("gym_cycle_completed", {
                "cycle": cycle_idx,
                "goal": challenge.goal,
                "score": scorecard.score,
                "passed": scorecard.passed,
                "action": refinement.action_taken,
                "summary": refinement.summary,
                "critique": scorecard.critique,
                "remediation": scorecard.remediation_advice,
                "snapshots": snapshots,
            })

            # Disk Health: Prune intermediate failed renders if not passed
            if not scorecard.passed and artifact_path:
                try:
                    insp_dir = Path(artifact_path).parent / f"{Path(artifact_path).stem}_inspection"
                    if insp_dir.exists():
                        shutil.rmtree(insp_dir, ignore_errors=True)
                except Exception:
                    pass

        except Exception as e:
            logger.warning("Error during Gym Cycle %d: %s", cycle_idx, e)
            broadcaster.emit("gym_cycle_error", {"cycle": cycle_idx, "error": str(e)})
