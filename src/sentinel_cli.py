"""Sentinel CLI: Command-Line Interface for Dispatching Tasks and Managing Organs.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Add src to sys.path
src_dir = Path(__file__).parent.resolve()
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from sentinel_core.config import SentinelConfig
from sentinel_core.db import SentinelDB
from sentinel_core.state_machine import StateMachine
from sentinel_core.verification_gate import VerificationGate, VerificationResult
from sentinel_adaptive.mistake_ledger import MistakeMemory
from sentinel_adaptive.skill_bank import SkillBank
from sentinel_broker.tool_registry import ToolRegistry
from sentinel_broker.organs.sensory import register_sensory_organs
from sentinel_broker.organs.motor import register_motor_organs
from sentinel_adaptive.pilot_controller import AdaptivePilotController


def cmd_run(args):
    config = SentinelConfig.load()
    max_attempts = args.max_attempts or config.iteration_limits.max_attempts
    task_id = args.task_id or f"task_cli_{int(time.time())}"
    goal = args.goal

    print("======================================================================")
    print("                    SENTINEL TASK DISPATCH                            ")
    print("======================================================================")
    print(f"Task ID:          {task_id}")
    print(f"Goal:             {goal}")
    print(f"Max Attempts:     {max_attempts}")
    print(f"Sandbox Mode:     {'AppContainer' if config.isolation.use_appcontainer else 'Host Simulation'}")
    print("----------------------------------------------------------------------")

    db = SentinelDB(config.storage.db_path)
    state_machine = StateMachine(db)
    verification_gate = VerificationGate(db)
    mistake_memory = MistakeMemory(db)
    skill_bank = SkillBank(db, config.storage.skills_dir)
    pilot = AdaptivePilotController(state_machine, verification_gate, mistake_memory, skill_bank)

    # Simulated worker demonstrating learning
    target_path = Path("workspaces") / f"{task_id}.txt"
    target_path.parent.mkdir(parents=True, exist_ok=True)

    def worker_logic(g, attempt_num, anti_patterns):
        print(f"\n[Worker Attempt {attempt_num}] Running...")
        if attempt_num == 1:
            print("  Attempt 1: Generating naive output (triggering verification check)...")
            target_path.write_text("", encoding="utf-8")
            return {"file": str(target_path)}
        else:
            print(f"  Attempt 2: Adapting based on anti-pattern feedback!")
            target_path.write_text(f"TASK_GOAL: {goal}\nSTATUS: VERIFIED_SUCCESSFUL\n", encoding="utf-8")
            synthesized_code = (
                f"# Skill synthesized for {goal}\n"
                f"result = {{'executed': True, 'goal': '{goal}'}}\n"
            )
            return {
                "file": str(target_path),
                "synthesized_code": synthesized_code,
            }

    def verifier(output):
        return verification_gate.verify_file_exists(target_path, min_bytes=10)

    result = pilot.run_task(
        task_id=task_id,
        goal=goal,
        worker_executor=worker_logic,
        verifier=verifier,
        skill_distillation_name=f"skill_{task_id}",
        max_attempts=max_attempts,
    )

    print("\n----------------------------------------------------------------------")
    print(f"Task Finished:    {result.task.state.value}")
    print(f"Attempts Taken:   {result.attempts_taken}")
    print(f"Mistakes Learned: {len(result.mistakes_encountered)}")
    if result.distilled_skill:
        print(f"Skill Distilled:  {result.distilled_skill['name']} ({result.distilled_skill['folder']})")
    print("======================================================================\n")


def cmd_tasks(args):
    config = SentinelConfig.load()
    db = SentinelDB(config.storage.db_path)
    rows = db.execute_read("SELECT id, title, state, attempt_count, max_attempts FROM tasks ORDER BY created_at DESC LIMIT 20")
    print("\n=== Recent Tasks ===")
    for r in rows:
        print(f"[{r['state']:<10}] {r['id']:<25} Attempts: {r['attempt_count']}/{r['max_attempts']} | {r['title']}")
    print()


def cmd_tools(args):
    registry = ToolRegistry()
    register_sensory_organs(registry)
    register_motor_organs(registry)
    tools = registry.list_tools()
    print("\n=== Registered Sensory & Motor Tools ('Eyes & Arms') ===")
    for t in tools:
        print(f"• {t['name']:<22} [{t['effect_class']:<18}] {t['description']}")
    print()


def cmd_mistakes(args):
    config = SentinelConfig.load()
    db = SentinelDB(config.storage.db_path)
    rows = db.execute_read("SELECT task_id, error_category, error_signature, lesson_learned FROM mistake_ledger ORDER BY ts DESC LIMIT 20")
    print("\n=== Episodic Mistake Memory (Anti-Patterns) ===")
    for r in rows:
        print(f"• [{r['error_category']}] {r['error_signature']}")
        print(f"  Lesson: {r['lesson_learned']} (Task: {r['task_id']})")
    print()


def cmd_skills(args):
    config = SentinelConfig.load()
    db = SentinelDB(config.storage.db_path)
    skill_bank = SkillBank(db, config.storage.skills_dir)
    skills = skill_bank.list_skills()
    print("\n=== Distilled Skill Bank (Plasticity) ===")
    for s in skills:
        print(f"• {s['name']} (v{s['version']})")
        print(f"  {s['description']}")
    print()


def cmd_ui(args):
    from sentinel_ui.server import start_server
    print(f"Starting Sentinel Web UI on http://{args.host}:{args.port} ...")
    start_server(host=args.host, port=args.port)


def main():
    parser = argparse.ArgumentParser(description="Sentinel CLI: Autonomous Agent Control")
    subparsers = parser.add_subparsers(dest="command")

    # run command
    p_run = subparsers.add_parser("run", help="Dispatch a task")
    p_run.add_argument("goal", type=str, help="Goal or prompt for the task")
    p_run.add_argument("--task-id", type=str, default=None, help="Custom task ID")
    p_run.add_argument("--max-attempts", type=int, default=None, help="Max retry attempts")

    # list commands
    subparsers.add_parser("tasks", help="List recent tasks")
    subparsers.add_parser("tools", help="List sensory & motor tools")
    subparsers.add_parser("mistakes", help="List episodic mistakes")
    subparsers.add_parser("skills", help="List distilled skills")

    # ui command
    p_ui = subparsers.add_parser("ui", help="Launch local Web UI")
    p_ui.add_argument("--host", type=str, default="127.0.0.1")
    p_ui.add_argument("--port", type=int, default=8000)

    args = parser.parse_args()
    if args.command == "run":
        cmd_run(args)
    elif args.command == "tasks":
        cmd_tasks(args)
    elif args.command == "tools":
        cmd_tools(args)
    elif args.command == "mistakes":
        cmd_mistakes(args)
    elif args.command == "skills":
        cmd_skills(args)
    elif args.command == "ui":
        cmd_ui(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
