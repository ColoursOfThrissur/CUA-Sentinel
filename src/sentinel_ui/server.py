"""Sentinel Control UI & REST API Server (FastAPI).
Serves real-time telemetry, configuration management, mistake inspection, and interactive task dispatch.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

src_dir = Path(__file__).parent.parent.resolve()
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import psutil

from sentinel_core.config import SentinelConfig
from sentinel_core.db import SentinelDB
from sentinel_core.state_machine import StateMachine
from sentinel_core.side_effects import SideEffectLedger
from sentinel_core.verification_gate import VerificationGate, VerificationResult
from sentinel_core.agent_registry import AgentRegistry, AgentManifest
from sentinel_adaptive.mistake_ledger import MistakeMemory
from sentinel_adaptive.skill_bank import SkillBank
from sentinel_broker.tool_registry import ToolRegistry
from sentinel_broker.pdp import PolicyDecisionPoint
from sentinel_broker.broker import ExecutionBroker
from sentinel_broker.organs.sensory import register_sensory_organs
from sentinel_broker.organs.motor import register_motor_organs
from sentinel_broker.organs.blender import register_blender_organs
from sentinel_broker.organs.blender_prompts import synthesize_blender_script
from sentinel_broker.organs.data_organ import register_data_organs
from sentinel_runner.appcontainer_host import AppContainerHost
from sentinel_core.llm_gateway import LLMGateway
from sentinel_core.preflight_linter import PreFlightLinter
from sentinel_core.contract_library import ContractLibrary
from sentinel_core.prompt_scaffolder import PromptScaffolder, ScaffoldingLevel
from sentinel_adaptive.pilot_controller import AdaptivePilotController

logger = logging.getLogger("SentinelServer")

app = FastAPI(title="Sentinel Control Plane", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

workspaces_dir = Path("workspaces").resolve()
workspaces_dir.mkdir(parents=True, exist_ok=True)
app.mount("/workspaces", StaticFiles(directory=str(workspaces_dir)), name="workspaces")

# Global Sentinel Context
CONFIG_PATH = Path("config.yaml")
config = SentinelConfig.load(CONFIG_PATH)
db = SentinelDB(config.storage.db_path)
state_machine = StateMachine(db)
verification_gate = VerificationGate(db)
mistake_memory = MistakeMemory(db)
skill_bank = SkillBank(db, config.storage.skills_dir)
tool_registry = ToolRegistry()
register_sensory_organs(tool_registry)
register_motor_organs(tool_registry)
register_blender_organs(tool_registry)
register_data_organs(tool_registry)

# Agent Registry & Standard Gate A Agents
agent_registry = AgentRegistry(db)

# Broker & Fenced PDP Policy Decision Point (AT-A-05, AT-B-07 to AT-B-10)
side_effects = SideEffectLedger(db)
pdp = PolicyDecisionPoint(state_machine.leases, tool_registry, agent_registry)
broker = ExecutionBroker(pdp, tool_registry, side_effects)

# AppContainer Host Bridge (Windows 11 isolation runtime)
appcontainer_host = None
staging_dir = Path(config.isolation.staging_runtime_dir)
if (staging_dir / "python.exe").exists():
    try:
        appcontainer_host = AppContainerHost(staging_dir, workspaces_dir)
        logger.info("AppContainerHost initialized successfully for Windows AppContainer isolation")
    except Exception as e:
        logger.warning("Could not initialize AppContainerHost: %s", e)

pilot = AdaptivePilotController(state_machine, verification_gate, mistake_memory, skill_bank)


def init_standard_agents():
    # 1. 3D Artisan
    agent_registry.register_draft(AgentManifest(
        agent_id="blender_artisan",
        name="3D Procedural Artisan",
        version="1.0.0",
        description="Synthesizes procedural 3D meshes, shaders, and animations in Blender 4.5 LTS.",
        author="Sentinel Biological Systems",
        capabilities=["3d:mesh", "3d:bpy", "3d:render"],
        allowed_organs=["blender_run_python", "blender_launch_gui"],
    ))
    try:
        agent_registry.publish_release("blender_artisan", "1.0.0", publisher="Sentinel Core")
    except Exception:
        pass

    # 2. Data Analyst
    agent_registry.register_draft(AgentManifest(
        agent_id="data_analyst",
        name="Data & Metrics Analyst",
        version="1.0.0",
        description="Analyzes CSV datasets, computes aggregations, and synthesizes analytical reports.",
        author="Sentinel Biological Systems",
        capabilities=["data:csv", "data:stats", "data:report"],
        allowed_organs=["python_sandbox_run", "csv_analyze_and_report", "file_transform"],
    ))
    try:
        agent_registry.publish_release("data_analyst", "1.0.0", publisher="Sentinel Core")
    except Exception:
        pass

    # 3. Code Engineer
    agent_registry.register_draft(AgentManifest(
        agent_id="code_engineer",
        name="Software Engineer",
        version="1.0.0",
        description="Synthesizes Python scripts, modules, algorithms, and executes sandboxed code.",
        author="Sentinel Biological Systems",
        capabilities=["code:python", "code:execution", "code:testing"],
        allowed_organs=["python_sandbox_run", "windows_command"],
    ))
    try:
        agent_registry.publish_release("code_engineer", "1.0.0", publisher="Sentinel Core")
    except Exception:
        pass


init_standard_agents()


class ConfigUpdateRequest(BaseModel):
    max_attempts: int | None = None
    attempt_timeout_sec: float | None = None
    memory_limit_mb: int | None = None
    cpu_rate_percent: float | None = None
    use_appcontainer: bool | None = None
    allow_irreversible: bool | None = None
    llm_model: str | None = None


class TaskDispatchRequest(BaseModel):
    goal: str
    launch_gui: bool = False
    max_attempts: int | None = None
    model: str | None = None
    agent_id: str | None = None


class AgentPublishRequest(BaseModel):
    agent_id: str
    version: str
    publisher: str = "Operator"


class AgentDraftRequest(BaseModel):
    agent_id: str
    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = "Operator"
    capabilities: list[str] = []
    allowed_organs: list[str] = []
    denied_tools: list[str] = []
    allow_irreversible: bool = False
    max_memory_mb: int = 100
    max_cpu_percent: float = 12.5


class AgentActionRequest(BaseModel):
    agent_id: str
    reason: str = ""


class ExecuteSkillRequest(BaseModel):
    skill_name: str
    params: dict[str, Any] = {}


@app.get("/api/config")
def get_config():
    return config.to_dict()


@app.post("/api/config")
def update_config(req: ConfigUpdateRequest):
    global config
    updates: dict[str, Any] = {
        "iteration_limits": {},
        "resource_quotas": {},
        "isolation": {},
        "policy": {},
        "llm": {},
    }
    if req.max_attempts is not None:
        updates["iteration_limits"]["max_attempts"] = req.max_attempts
    if req.attempt_timeout_sec is not None:
        updates["iteration_limits"]["attempt_timeout_sec"] = req.attempt_timeout_sec
    if req.memory_limit_mb is not None:
        updates["resource_quotas"]["memory_limit_mb"] = req.memory_limit_mb
    if req.cpu_rate_percent is not None:
        updates["resource_quotas"]["cpu_rate_percent"] = req.cpu_rate_percent
    if req.use_appcontainer is not None:
        updates["isolation"]["use_appcontainer"] = req.use_appcontainer
    if req.allow_irreversible is not None:
        updates["policy"]["allow_irreversible"] = req.allow_irreversible
    if req.llm_model is not None:
        updates["llm"]["model"] = req.llm_model

    config.update_from_dict(updates)
    config.save(CONFIG_PATH)
    return {"status": "CONFIG_SAVED", "config": config.to_dict()}


@app.get("/api/models")
def list_models():
    """Returns available Ollama models with the active model highlighted."""
    import urllib.request
    try:
        req = urllib.request.Request(f"{config.llm.endpoint}/api/tags")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m.get("name") for m in data.get("models", [])]
            return {"active_model": config.llm.model, "available_models": models}
    except Exception:
        return {"active_model": config.llm.model, "available_models": [config.llm.model]}


@app.get("/api/telemetry")
def get_telemetry():
    mem = psutil.virtual_memory()
    tasks_count = db.execute_one("SELECT COUNT(*) as count FROM tasks")
    attempts_count = db.execute_one("SELECT COUNT(*) as count FROM attempts")
    mistakes_count = db.execute_one("SELECT COUNT(*) as count FROM mistake_ledger")
    skills_count = db.execute_one("SELECT COUNT(*) as count FROM skills")
    highest_lease = db.execute_one("SELECT COALESCE(MAX(lease_token), 0) as max_lease FROM attempts")

    return {
        "hardware": {
            "available_ram_mb": round(mem.available / (1024 * 1024), 1),
            "total_ram_mb": round(mem.total / (1024 * 1024), 1),
            "used_ram_percent": mem.percent,
            "cpu_percent": psutil.cpu_percent(interval=None),
        },
        "counts": {
            "tasks": tasks_count["count"] if tasks_count else 0,
            "attempts": attempts_count["count"] if attempts_count else 0,
            "mistakes": mistakes_count["count"] if mistakes_count else 0,
            "skills": skills_count["count"] if skills_count else 0,
            "highest_lease_token": highest_lease["max_lease"] if highest_lease else 0,
        },
        "config_summary": {
            "max_attempts": config.iteration_limits.max_attempts,
            "timeout_sec": config.iteration_limits.attempt_timeout_sec,
            "memory_cap_mb": config.resource_quotas.memory_limit_mb,
            "cpu_cap_percent": config.resource_quotas.cpu_rate_percent,
            "appcontainer_enabled": config.isolation.use_appcontainer,
        },
    }


@app.get("/api/tasks")
def list_tasks():
    rows = db.execute_read("SELECT * FROM tasks ORDER BY created_at DESC LIMIT 50")
    res = []
    for r in rows:
        d = dict(r)
        tid = d["id"]
        # Find matching artifact in workspaces_dir
        matches = list(workspaces_dir.glob(f"{tid}.*"))
        if matches:
            # Pick primary artifact, prioritizing .obj, .csv, .md, .py, .txt over .mtl/.tmp
            def art_priority(p: Path):
                s = p.suffix.lower()
                if s == '.obj': return 0
                if s in ['.csv', '.md', '.py', '.txt']: return 1
                return 2
            art = sorted(matches, key=lambda p: (art_priority(p), -p.stat().st_mtime))[0]
            d["artifact_filename"] = art.name
            d["artifact_url"] = f"/workspaces/{art.name}"
            d["artifact_size"] = art.stat().st_size
            d["artifact_ext"] = art.suffix.lstrip(".").lower()
        else:
            d["artifact_filename"] = None
            d["artifact_url"] = None
            d["artifact_size"] = 0
            d["artifact_ext"] = None
        res.append(d)
    return res


@app.get("/api/mistakes")
def list_mistakes():
    rows = db.execute_read("SELECT * FROM mistake_ledger ORDER BY ts DESC LIMIT 50")
    return [dict(r) for r in rows]


@app.get("/api/skills")
def list_skills():
    return skill_bank.list_skills()


@app.get("/api/tools")
def list_tools():
    return tool_registry.list_tools()


@app.get("/api/agents")
def list_agents():
    return agent_registry.list_agents()


@app.post("/api/agents/publish")
def api_publish_agent(req: AgentPublishRequest):
    try:
        release = agent_registry.publish_release(
            agent_id=req.agent_id,
            version=req.version,
            publisher=req.publisher,
        )
        return {
            "success": True,
            "agent_id": req.agent_id,
            "version": req.version,
            "provenance_hash": release.provenance_hash,
            "published_at": release.published_at,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/agents/draft")
def api_register_draft(req: AgentDraftRequest):
    try:
        manifest = AgentManifest(
            agent_id=req.agent_id,
            name=req.name,
            version=req.version,
            description=req.description,
            author=req.author,
            capabilities=req.capabilities,
            allowed_organs=req.allowed_organs,
            denied_tools=req.denied_tools,
            allow_irreversible=req.allow_irreversible,
            max_memory_mb=req.max_memory_mb,
            max_cpu_percent=req.max_cpu_percent,
        )
        agent = agent_registry.register_draft(manifest)
        return {"success": True, "agent": agent}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/agents/{agent_id}/releases")
def api_get_agent_releases(agent_id: str):
    return agent_registry.list_releases(agent_id)


@app.post("/api/agents/deprecate")
def api_deprecate_agent(req: AgentActionRequest):
    try:
        agent = agent_registry.deprecate_agent(req.agent_id)
        return {"success": True, "agent": agent}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/side_effects")
def list_side_effects():
    rows = db.execute_read("SELECT * FROM side_effect_ledger ORDER BY id DESC LIMIT 50")
    return [dict(r) for r in rows]


@app.post("/api/tasks/dispatch")
def dispatch_task(req: TaskDispatchRequest):
    """Dispatches any custom user task across 3D, data, code, or report domains."""
    task_id = f"task_{int(time.time())}"
    goal = req.goal.strip()
    max_att = req.max_attempts or config.iteration_limits.max_attempts
    selected_model = req.model or config.llm.model
    lower_goal = goal.lower()

    if any(w in lower_goal for w in [
        "3d", "blender", "model", "sword", "mug", "spaceship", "tree", "chair", "monkey", "mesh",
        "build", "turret", "gatling", "cylinder", "cube", "sphere", "torus", "geometry", "sculpture",
        "gun", "barrel", "mount", "bracket", "pillar", "shaft", "car", "robot", "cannon", "shield",
        "armor", "helmet", "ring", "table", "lamp", "building", "castle", "plane", "rifle", "dagger",
        "warhammer"
    ]):
        domain = "3d"
        ext = "obj"
        min_sz = 100
    elif any(w in lower_goal for w in ["csv", "table", "dataset", "dataframe", "rows", "columns", "spreadsheet", "sales"]):
        domain = "data"
        ext = "csv"
        min_sz = 15
    elif any(w in lower_goal for w in ["code", "python script", "function", "class", "algorithm", "program", "script", "write code"]):
        domain = "code"
        ext = "py"
        min_sz = 15
    else:
        domain = "report"
        ext = "md"
        min_sz = 20

    # Determine Gate A Agent Identity
    effective_agent = req.agent_id
    if not effective_agent or effective_agent == "auto":
        if domain == "3d":
            effective_agent = "blender_artisan"
        elif domain == "data":
            effective_agent = "data_analyst"
        elif domain == "code":
            effective_agent = "code_engineer"
        else:
            effective_agent = "data_analyst"

    expected_artifact = workspaces_dir / f"{task_id}.{ext}"

    def worker_executor(g: str, attempt_num: int, anti_patterns: str):
        # Step 1: Wire active attempt & lease token through Fenced Broker & PDP
        active_attempt = state_machine.db.execute_one(
            "SELECT id, lease_token FROM attempts WHERE task_id = ? AND status = 'Active'",
            (task_id,),
        )
        att_id = active_attempt["id"] if active_attempt else f"att_{task_id}_{attempt_num}"
        lease = active_attempt["lease_token"] if active_attempt else state_machine.leases.get_active_lease()

        def run_tool_fenced(tool_name: str, params: dict):
            if config.isolation.use_appcontainer and appcontainer_host:
                logger.info("Executing tool '%s' under AppContainer isolation fence for agent '%s'", tool_name, effective_agent)
            call_res = broker.dispatch_call(
                attempt_id=att_id,
                lease_token=lease,
                tool_name=tool_name,
                params=params,
                context={"agent_id": effective_agent, "allow_irreversible": config.policy.allow_irreversible},
            )
            if not call_res.get("allowed", False):
                raise PermissionError(f"PDP Denied Tool '{tool_name}' for Agent '{effective_agent}': {call_res.get('error')}")
            return call_res.get("result", {})

        if domain == "3d":
            logger.info("Executing 3D synthesis via LLM (%s) attempt %d", selected_model, attempt_num)
            blender_script = synthesize_blender_script(
                goal=goal,
                output_obj_path=str(expected_artifact),
                anti_patterns=anti_patterns,
                use_llm=True,
                model=selected_model,
            )
            # Upgrade A: Pre-Flight AST Linter / Rewriter (<2ms)
            preflight = PreFlightLinter.sanitize(blender_script, domain="3d")
            blender_script = preflight.code
            if preflight.applied_fixes:
                logger.info("PreFlightLinter sanitized 3D script: %s", preflight.applied_fixes)

            res = run_tool_fenced("blender_run_python", {
                "script_code": blender_script,
                "output_obj_path": str(expected_artifact),
            })
            return {
                "tool_result": res,
                "artifact_path": str(expected_artifact),
                "synthesized_code": blender_script,
            }
        elif domain == "data":
            logger.info("Executing Data synthesis via LLM (%s) attempt %d", selected_model, attempt_num)
            gw = LLMGateway(endpoint=config.llm.endpoint, default_model=selected_model)
            out_path_str = str(expected_artifact).replace("\\", "/")
            sys_inst = (
                "You are Sentinel's Data Synthesizer. Write clean, self-contained Python 3 code using the standard library "
                f"(csv, io, random, math, datetime) to generate the CSV dataset and write it directly to '{out_path_str}'.\n"
                "Output ONLY executable Python code inside a ```python ``` block."
            )
            prompt_data = f"Goal: {goal}\nTarget Output CSV Path: '{out_path_str}'"
            if anti_patterns:
                prompt_data += f"\n[PREVIOUS ATTEMPT FAILED]:\n{anti_patterns}\nEnsure the CSV file is written to '{out_path_str}' with valid header and rows."

            raw_code = gw.generate(prompt=prompt_data, system=sys_inst, model=selected_model)
            py_code = gw.extract_python_code(raw_code)
            # PreFlight sanitize
            preflight = PreFlightLinter.sanitize(py_code, domain="code")
            py_code = preflight.code

            res = run_tool_fenced("python_sandbox_run", {
                "script_code": py_code,
                "output_artifact_path": str(expected_artifact),
            })
            # If the script printed the CSV to stdout instead of file, save stdout
            if not expected_artifact.exists() and res.get("stdout") and "," in res.get("stdout"):
                expected_artifact.write_text(res["stdout"].strip(), encoding="utf-8")

            return {"tool_result": res, "artifact_path": str(expected_artifact), "synthesized_code": py_code}
        elif domain == "code":
            logger.info("Executing Code synthesis via LLM (%s) attempt %d", selected_model, attempt_num)
            gw = LLMGateway(endpoint=config.llm.endpoint, default_model=selected_model)
            
            # Upgrade C: Scaffolder with surgical failure anchoring on retry
            scaffolding_lvl = ScaffoldingLevel.LEVEL_3_ADAPTIVE if anti_patterns else ScaffoldingLevel.LEVEL_2_GUARDED
            sys_inst = PromptScaffolder.build_system_prompt("code", level=scaffolding_lvl)
            prompt_code = PromptScaffolder.build_user_prompt(
                goal=goal,
                domain="code",
                artifact_path=str(expected_artifact),
                anti_patterns=anti_patterns,
                level=scaffolding_lvl,
            )

            raw_code = gw.generate(prompt=prompt_code, system=sys_inst, model=selected_model)
            py_code = gw.extract_python_code(raw_code)
            
            # Upgrade A: Pre-Flight deterministic sanitizer
            preflight = PreFlightLinter.sanitize(py_code, domain="code")
            py_code = preflight.code
            if preflight.applied_fixes:
                logger.info("PreFlightLinter sanitized Python code: %s", preflight.applied_fixes)

            expected_artifact.write_text(py_code, encoding="utf-8")
            return {"tool_result": {"exit_code": 0, "stdout": "Code generated successfully"}, "artifact_path": str(expected_artifact), "synthesized_code": py_code}
        else:
            # Report / analysis domain (.md)
            logger.info("Executing Report synthesis via LLM (%s) attempt %d", selected_model, attempt_num)
            gw = LLMGateway(endpoint=config.llm.endpoint, default_model=selected_model)
            sys_inst = (
                "You are Sentinel's Autonomous Analyst. Provide a clear, structured, comprehensive Markdown report solving the user's task. "
                "Use headings, bullet points, and data tables where helpful."
            )
            prompt_rep = f"Task: {goal}"
            if anti_patterns:
                prompt_rep += f"\n[PREVIOUS DEFECT]:\n{anti_patterns}\nAddress the defect."
            report_text = gw.generate(prompt=prompt_rep, system=sys_inst, model=selected_model)
            expected_artifact.write_text(f"# Sentinel Task Report: {goal}\n\n**Domain**: `Analysis` · **Model**: `{selected_model}` · **Timestamp**: {time.ctime()}\n\n---\n\n{report_text}\n", encoding="utf-8")
            return {"tool_result": {"exit_code": 0, "stdout": "Report written successfully"}, "artifact_path": str(expected_artifact)}

    def verifier(output: dict) -> VerificationResult:
        p = Path(output.get("artifact_path", ""))
        if domain == "3d":
            return verification_gate.verify_obj_geometry(p, min_vertices=10, min_faces=5)
        elif domain == "code":
            expected_syms = []
            if "lru" in lower_goal:
                expected_syms = ["LRUCache", "get", "put"]
            # Upgrade B: Automated Contract Harness matching from library
            contract_harness = ContractLibrary.get_contract_for_goal(goal)
            return verification_gate.verify_python_code(
                p,
                required_symbols=expected_syms,
                test_execution=True,
                contract_harness=contract_harness,
            )
        elif domain == "data":
            return verification_gate.verify_csv_structure(p, min_rows=2, min_cols=2)
        else:
            return verification_gate.verify_markdown_report(p, min_words=25)

    gw = LLMGateway(endpoint=config.llm.endpoint, default_model=selected_model)
    result = pilot.run_task(
        task_id=task_id,
        goal=goal,
        worker_executor=worker_executor,
        verifier=verifier,
        skill_distillation_name=f"skill_{task_id}",
        max_attempts=max_att,
        domain=domain,
        llm_gateway=gw,
    )

    # Launch in Blender GUI if requested and is 3D
    gui_info = None
    if req.launch_gui and expected_artifact.exists() and domain == "3d":
        try:
            gui_info = tool_registry.execute_tool("blender_launch_gui", {"file_to_open": str(expected_artifact)})
        except Exception as e:
            gui_info = {"error": str(e)}

    return {
        "task_id": result.task.id,
        "goal": goal,
        "domain": domain,
        "model": selected_model,
        "agent_id": effective_agent,
        "state": result.task.state.value,
        "attempts_taken": result.attempts_taken,
        "success": result.success,
        "artifact_path": str(expected_artifact) if expected_artifact.exists() else None,
        "artifact_filename": expected_artifact.name if expected_artifact.exists() else None,
        "artifact_size_bytes": expected_artifact.stat().st_size if expected_artifact.exists() else 0,
        "download_url": f"/workspaces/{expected_artifact.name}" if expected_artifact.exists() else None,
        "gui_launch": gui_info,
        "distilled_skill": result.distilled_skill,
        "mistakes_encountered": result.mistakes_encountered,
    }


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Sentinel Control Plane</title>
  <script src="https://www.gstatic.com/antigravity/web/dev/tailwindcss.min.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/loaders/OBJLoader.js"></script>
</head>
<body class="bg-[#0f172a] text-slate-100 min-h-screen p-6 font-sans">
  <div class="max-w-7xl mx-auto space-y-6">

    <!-- Header -->
    <header class="flex items-center justify-between border-b border-slate-700 pb-4">
      <div>
        <h1 class="text-2xl font-bold tracking-tight text-sky-400 flex items-center gap-2">
          <span>🛡️</span> Sentinel Control Plane & Organ Monitor
        </h1>
        <p class="text-xs text-slate-400 mt-1">Autonomous Execution Platform · Windows 11 AppContainer Runtime · Real Blender 4.5</p>
      </div>
      <div class="flex items-center gap-3">
        <button onclick="refreshAll()" class="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 border border-slate-600 text-xs font-semibold rounded-lg transition">
          🔄 Refresh
        </button>
      </div>
    </header>

    <!-- NEW: Interactive Task Dispatch Prompt Bar -->
    <div class="bg-gradient-to-r from-slate-800/90 to-slate-900/90 border border-sky-500/30 rounded-xl p-5 shadow-lg space-y-3">
      <div class="flex items-center justify-between">
        <span class="text-xs font-bold text-sky-400 uppercase tracking-wider flex items-center gap-1.5">
          <span>💬</span> Chat & Task Dispatch Interface
        </span>
        <span class="text-[11px] text-slate-400">Connected to Real Blender 4.5 & Windows Motor Organs</span>
      </div>

      <div class="flex flex-wrap md:flex-nowrap gap-2">
        <select id="select-agent" class="bg-slate-950 border border-slate-700 text-emerald-400 rounded-lg px-3 py-2 text-xs font-semibold outline-none">
          <option value="auto" selected>🤖 Auto-Detect Agent</option>
          <option value="blender_artisan">🎨 Blender Artisan (3D)</option>
          <option value="data_analyst">📊 Data Analyst (CSV)</option>
          <option value="code_engineer">💻 Code Engineer (Python)</option>
        </select>
        <select id="select-model" class="bg-slate-950 border border-slate-700 text-sky-400 rounded-lg px-3 py-2 text-xs font-semibold outline-none">
          <option value="qwen3.5:9b" selected>🧠 Qwen 3.5 (9B) [Active]</option>
          <option value="qwen3:14b-q4_K_M">🧠 Qwen 3 (14B Q4)</option>
          <option value="qwen3-vl:8b">🧠 Qwen 3 VL (8B)</option>
          <option value="phi3:latest">🧠 Phi 3</option>
          <option value="mistral:7b">🧠 Mistral (7B)</option>
        </select>
        <input id="prompt-input" type="text" 
          placeholder="Type any 3D model or task prompt here (e.g., 'Create a futuristic mech cannon in Blender')..." 
          class="flex-1 bg-slate-950 border border-slate-700 focus:border-sky-500 rounded-lg px-4 py-2 text-xs text-slate-100 outline-none shadow-inner"
          onkeydown="if(event.key==='Enter') dispatchUserTask()">
        <button id="dispatch-btn" onclick="dispatchUserTask()" 
          class="px-5 py-2 bg-sky-600 hover:bg-sky-500 text-xs font-bold text-white rounded-lg shadow-md transition flex items-center gap-1.5 whitespace-nowrap">
          <span>🚀</span> Dispatch Task
        </button>
      </div>

      <div class="flex flex-wrap items-center justify-between gap-2 text-xs pt-1">
        <div class="flex items-center gap-3">
          <label class="flex items-center gap-1.5 cursor-pointer text-slate-300">
            <input type="checkbox" id="check-launch-gui" checked class="rounded bg-slate-900 border-slate-700 text-sky-500 focus:ring-0">
            <span>Open in Blender 4.5 GUI on Desktop when complete</span>
          </label>
        </div>
        <div class="flex items-center gap-2 text-[11px] text-slate-400">
          <span>Suggestions:</span>
          <button onclick="setPrompt('Create a 3D low-poly medieval sword in Blender')" class="px-2 py-0.5 bg-slate-800 hover:bg-slate-700 rounded border border-slate-700 text-slate-300">🗡️ Sword</button>
          <button onclick="setPrompt('Create a 3D coffee mug in Blender')" class="px-2 py-0.5 bg-slate-800 hover:bg-slate-700 rounded border border-slate-700 text-slate-300">☕ Mug</button>
          <button onclick="setPrompt('Create a 3D futuristic spaceship in Blender')" class="px-2 py-0.5 bg-slate-800 hover:bg-slate-700 rounded border border-slate-700 text-slate-300">🚀 Spaceship</button>
          <button onclick="setPrompt('Create a 3D pine tree in Blender')" class="px-2 py-0.5 bg-slate-800 hover:bg-slate-700 rounded border border-slate-700 text-slate-300">🌲 Tree</button>
        </div>
      </div>

      <!-- Execution Live Status Banner -->
      <div id="live-status-card" class="hidden bg-slate-950/80 border border-slate-700 rounded-lg p-3 text-xs space-y-1 mt-2">
        <div class="flex items-center justify-between">
          <span id="live-status-title" class="font-bold text-sky-400">⏳ Dispatching task...</span>
          <span id="live-status-badge" class="px-2 py-0.5 text-[10px] font-semibold rounded bg-sky-500/20 text-sky-400">RUNNING</span>
        </div>
        <p id="live-status-detail" class="text-slate-300 text-[11px]">Worker communicating across Named Pipe to Blender 4.5 engine...</p>
        <div id="live-status-link" class="pt-1"></div>
      </div>
    </div>

    <!-- Telemetry Cards -->
    <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
      <div class="bg-slate-800/80 border border-slate-700/80 rounded-xl p-4 shadow-sm">
        <p class="text-xs text-slate-400 font-medium">Available RAM Floor</p>
        <p id="ram-val" class="text-2xl font-bold text-sky-400 mt-1">-- MB</p>
        <p class="text-[11px] text-slate-500 mt-1">Target Floor: ≥ 2,500 MB</p>
      </div>
      <div class="bg-slate-800/80 border border-slate-700/80 rounded-xl p-4 shadow-sm">
        <p class="text-xs text-slate-400 font-medium">Monotonic Lease Counter</p>
        <p id="lease-val" class="text-2xl font-bold text-emerald-400 mt-1">--</p>
        <p class="text-[11px] text-slate-500 mt-1">AT-B-10 Fencing Active</p>
      </div>
      <div class="bg-slate-800/80 border border-slate-700/80 rounded-xl p-4 shadow-sm">
        <p class="text-xs text-slate-400 font-medium">Episodic Mistakes Learned</p>
        <p id="mistakes-count" class="text-2xl font-bold text-amber-400 mt-1">--</p>
        <p class="text-[11px] text-slate-500 mt-1">Anti-Patterns in Memory</p>
      </div>
      <div class="bg-slate-800/80 border border-slate-700/80 rounded-xl p-4 shadow-sm">
        <p class="text-xs text-slate-400 font-medium">Skill Bank Distillations</p>
        <p id="skills-count" class="text-2xl font-bold text-purple-400 mt-1">--</p>
        <p class="text-[11px] text-slate-500 mt-1">Dynamic Plasticity Tools</p>
      </div>
    </div>

    <!-- Navigation Tabs -->
    <div class="border-b border-slate-700 flex gap-4 text-xs font-semibold text-slate-400">
      <button onclick="switchTab('tab-tasks')" class="tab-btn pb-2 border-b-2 border-sky-400 text-sky-400" id="btn-tasks">📋 Task Lifecycle & Artifacts</button>
      <button onclick="switchTab('tab-agents')" class="tab-btn pb-2 hover:text-slate-200" id="btn-agents">🤖 Registered Agents (Gate A)</button>
      <button onclick="switchTab('tab-config')" class="tab-btn pb-2 hover:text-slate-200" id="btn-config">⚙️ Iteration & Quota Config</button>
      <button onclick="switchTab('tab-mistakes')" class="tab-btn pb-2 hover:text-slate-200" id="btn-mistakes">🧠 Episodic Mistake Memory</button>
      <button onclick="switchTab('tab-skills')" class="tab-btn pb-2 hover:text-slate-200" id="btn-skills">✨ Skill Bank Catalog</button>
      <button onclick="switchTab('tab-tools')" class="tab-btn pb-2 hover:text-slate-200" id="btn-tools">👁️ Sensory & Motor Tools</button>
    </div>

    <!-- Tab 1: Tasks -->
    <div id="tab-tasks" class="tab-content bg-slate-800/60 border border-slate-700 rounded-xl p-5 space-y-3">
      <h2 class="text-base font-bold text-slate-100">Tasks & State Transitions</h2>
      <div class="overflow-x-auto">
        <table class="w-full text-left text-xs">
          <thead class="bg-slate-900/60 text-slate-400 border-b border-slate-700">
            <tr>
              <th class="p-2.5">Task ID</th>
              <th class="p-2.5">Goal</th>
              <th class="p-2.5">State</th>
              <th class="p-2.5">Attempts</th>
              <th class="p-2.5">Output Artifact</th>
            </tr>
          </thead>
          <tbody id="tasks-table-body" class="divide-y divide-slate-700/60">
            <tr><td colspan="5" class="p-4 text-center text-slate-500">Loading tasks...</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Tab: Agents (Gate A Studio) -->
    <div id="tab-agents" class="tab-content hidden bg-slate-800/60 border border-slate-700 rounded-xl p-5 space-y-4">
      <div class="flex items-center justify-between border-b border-slate-700/80 pb-3">
        <div>
          <h2 class="text-base font-bold text-slate-100 flex items-center gap-2">
            <span>🤖</span> Agent Studio & Capability Governance (Gate A)
          </h2>
          <p class="text-xs text-slate-400 mt-0.5">Manage specialized agents, verify SHA-256 provenance hashes, and publish immutable releases.</p>
        </div>
        <div class="flex items-center gap-2">
          <button onclick="openAgentDraftModal()" class="px-3.5 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-xs font-semibold text-white rounded-lg transition flex items-center gap-1.5 shadow-sm">
            <span>➕</span> New Agent Draft
          </button>
        </div>
      </div>
      
      <div id="agents-container" class="grid grid-cols-1 md:grid-cols-3 gap-4 pt-1">
        <p class="text-xs text-slate-500">Loading agents...</p>
      </div>
    </div>

    <!-- Tab 2: Config -->
    <div id="tab-config" class="tab-content hidden bg-slate-800/60 border border-slate-700 rounded-xl p-5 space-y-4">
      <h2 class="text-base font-bold text-slate-100">Control Solution Iterations & Resource Quotas</h2>
      <div class="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2">
        <div class="space-y-1">
          <label class="text-xs font-medium text-slate-300">Max Attempts (Iteration Level)</label>
          <input type="number" id="cfg-max-attempts" min="1" max="10" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-100 focus:border-sky-500 outline-none">
        </div>
        <div class="space-y-1">
          <label class="text-xs font-medium text-slate-300">Attempt Timeout (Seconds)</label>
          <input type="number" id="cfg-timeout" min="5" max="300" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-100 focus:border-sky-500 outline-none">
        </div>
        <div class="space-y-1">
          <label class="text-xs font-medium text-slate-300">Memory Cap (MB per Worker)</label>
          <input type="number" id="cfg-memory" min="50" max="1024" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-100 focus:border-sky-500 outline-none">
        </div>
        <div class="space-y-1">
          <label class="text-xs font-medium text-slate-300">CPU Hard Cap (%)</label>
          <input type="number" step="0.5" id="cfg-cpu" min="5" max="100" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-100 focus:border-sky-500 outline-none">
        </div>
        <div class="space-y-1">
          <label class="text-xs font-medium text-slate-300">AppContainer Runtime Isolation</label>
          <select id="cfg-isolation" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-100 focus:border-sky-500 outline-none">
            <option value="true">Enabled (Windows 11 AppContainer)</option>
            <option value="false">Disabled (Host Simulation Mode)</option>
          </select>
        </div>
        <div class="space-y-1">
          <label class="text-xs font-medium text-slate-300">Allow Irreversible Side Effects</label>
          <select id="cfg-irreversible" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-100 focus:border-sky-500 outline-none">
            <option value="false">Denied (Fail-Closed Policy)</option>
            <option value="true">Permitted (Operator Clearance)</option>
          </select>
        </div>
      </div>
      <div class="pt-2">
        <button onclick="saveConfig()" class="px-4 py-2 bg-sky-600 hover:bg-sky-500 text-xs font-semibold text-white rounded-lg transition shadow">
          💾 Save Configuration
        </button>
        <span id="cfg-status" class="ml-3 text-xs text-emerald-400 font-medium"></span>
      </div>
    </div>

    <!-- Tab 3: Mistakes -->
    <div id="tab-mistakes" class="tab-content hidden bg-slate-800/60 border border-slate-700 rounded-xl p-5 space-y-3">
      <h2 class="text-base font-bold text-slate-100">Episodic Mistake Memory & Lessons Learned</h2>
      <div id="mistakes-container" class="space-y-2 pt-2">
        <p class="text-xs text-slate-500">Loading mistake ledger...</p>
      </div>
    </div>

    <!-- Tab 4: Skills -->
    <div id="tab-skills" class="tab-content hidden bg-slate-800/60 border border-slate-700 rounded-xl p-5 space-y-3">
      <h2 class="text-base font-bold text-slate-100">Skill Bank & Synthesized Tools</h2>
      <div id="skills-container" class="grid grid-cols-1 md:grid-cols-2 gap-3 pt-2">
        <p class="text-xs text-slate-500">Loading skills...</p>
      </div>
    </div>

    <!-- Tab 5: Tools -->
    <div id="tab-tools" class="tab-content hidden bg-slate-800/60 border border-slate-700 rounded-xl p-5 space-y-3">
      <h2 class="text-base font-bold text-slate-100">Sensory & Motor Organs Catalog ('Eyes & Arms')</h2>
      <div id="tools-container" class="space-y-2 pt-2">
        <p class="text-xs text-slate-500">Loading tools...</p>
      </div>
    </div>

  </div>

  <!-- Interactive Artifact Preview Modal (Three.js 3D / CSV / Code) -->
  <div id="preview-modal" class="fixed inset-0 z-50 bg-black/85 backdrop-blur-md hidden flex items-center justify-center p-4">
    <div class="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-4xl max-h-[90vh] flex flex-col shadow-2xl overflow-hidden">
      <!-- Modal Header -->
      <div class="px-5 py-3 border-b border-slate-800 flex items-center justify-between bg-slate-950/80">
        <div class="flex items-center gap-2.5">
          <span id="modal-icon" class="text-xl">🧊</span>
          <div>
            <h3 id="modal-title" class="text-sm font-bold text-sky-400 font-mono">artifact.obj</h3>
            <p id="modal-subtitle" class="text-[10px] text-slate-400">Interactive Preview</p>
          </div>
          <span id="modal-badge" class="ml-2 px-2.5 py-0.5 text-[10px] font-semibold rounded bg-sky-500/20 text-sky-400 border border-sky-500/30">3D Mesh</span>
        </div>
        <div class="flex items-center gap-3">
          <a id="modal-download" href="#" download class="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 border border-slate-600 text-xs font-semibold text-slate-200 rounded-lg transition flex items-center gap-1.5 shadow-sm">
            <span>⬇️</span> Download File
          </a>
          <button onclick="closePreviewModal()" class="w-7 h-7 flex items-center justify-center text-slate-400 hover:text-white rounded-lg hover:bg-slate-800 transition text-base font-bold">✕</button>
        </div>
      </div>
      
      <!-- Modal Content Body -->
      <div class="flex-1 overflow-hidden p-0 flex flex-col items-center justify-center min-h-[460px] bg-slate-950 relative">
        <!-- 3D Viewport -->
        <div id="three-container" class="w-full h-[460px] relative hidden">
          <div id="three-loading" class="absolute inset-0 flex items-center justify-center bg-slate-950/90 text-sky-400 text-xs font-semibold z-10">
            <span class="animate-pulse">Loading 3D mesh into WebGL Engine...</span>
          </div>
          <div class="absolute bottom-3 left-3 bg-slate-900/85 border border-slate-700/80 rounded-lg px-3 py-1.5 text-[11px] text-slate-300 z-10 backdrop-blur shadow">
            🖱️ Left Click: Rotate · Right Click: Pan · Scroll: Zoom
          </div>
          <div id="three-stats" class="absolute top-3 right-3 bg-slate-900/85 border border-slate-700/80 rounded-lg px-3 py-1.5 text-[11px] font-mono text-sky-400 z-10 backdrop-blur shadow">
            Vertices: -- · Faces: --
          </div>
        </div>

        <!-- CSV Table Viewport -->
        <div id="csv-container" class="w-full h-[460px] hidden overflow-auto p-4 text-xs font-sans"></div>

        <!-- Code / Markdown Viewport -->
        <pre id="code-container" class="w-full h-[460px] hidden overflow-auto p-5 text-xs font-mono text-slate-200 bg-slate-950 select-text leading-relaxed"></pre>
      </div>
    </div>
  </div>

  <!-- Agent Draft Modal (Gate A Studio) -->
  <div id="agent-draft-modal" class="fixed inset-0 z-50 bg-black/85 backdrop-blur-md hidden flex items-center justify-center p-4">
    <div class="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-xl flex flex-col shadow-2xl overflow-hidden">
      <div class="px-5 py-3 border-b border-slate-800 flex items-center justify-between bg-slate-950/80">
        <h3 class="text-sm font-bold text-emerald-400 flex items-center gap-2">
          <span>➕</span> Register New Agent Draft (Gate A: AT-A-01)
        </h3>
        <button onclick="closeAgentModals()" class="text-slate-400 hover:text-white text-base font-bold">✕</button>
      </div>
      <div class="p-5 space-y-3.5 text-xs">
        <div class="grid grid-cols-2 gap-3">
          <div class="space-y-1">
            <label class="text-slate-300 font-medium">Agent Unique ID</label>
            <input id="draft-id" type="text" placeholder="e.g. security_auditor" class="w-full bg-slate-950 border border-slate-700 rounded-lg p-2 font-mono text-slate-100 outline-none focus:border-emerald-500">
          </div>
          <div class="space-y-1">
            <label class="text-slate-300 font-medium">Display Name</label>
            <input id="draft-name" type="text" placeholder="e.g. Security Vulnerability Auditor" class="w-full bg-slate-950 border border-slate-700 rounded-lg p-2 text-slate-100 outline-none focus:border-emerald-500">
          </div>
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div class="space-y-1">
            <label class="text-slate-300 font-medium">Initial Version</label>
            <input id="draft-version" type="text" value="1.0.0" class="w-full bg-slate-950 border border-slate-700 rounded-lg p-2 font-mono text-slate-100 outline-none focus:border-emerald-500">
          </div>
          <div class="space-y-1">
            <label class="text-slate-300 font-medium">Author</label>
            <input id="draft-author" type="text" value="Sentinel Operator" class="w-full bg-slate-950 border border-slate-700 rounded-lg p-2 text-slate-100 outline-none focus:border-emerald-500">
          </div>
        </div>
        <div class="space-y-1">
          <label class="text-slate-300 font-medium">Description</label>
          <textarea id="draft-desc" rows="2" placeholder="Responsibilities and behavioral domain of this agent..." class="w-full bg-slate-950 border border-slate-700 rounded-lg p-2 text-slate-100 outline-none focus:border-emerald-500"></textarea>
        </div>
        <div class="space-y-1.5">
          <label class="text-slate-300 font-medium">Allowed Organs Whitelist (PDP Capability Gate)</label>
          <div class="grid grid-cols-2 gap-2 p-2 bg-slate-950 border border-slate-800 rounded-lg text-[11px]">
            <label class="flex items-center gap-2 cursor-pointer text-slate-300">
              <input type="checkbox" value="python_sandbox_run" checked class="organ-checkbox rounded bg-slate-900 border-slate-700 text-emerald-500">
              <span>python_sandbox_run</span>
            </label>
            <label class="flex items-center gap-2 cursor-pointer text-slate-300">
              <input type="checkbox" value="csv_analyze_and_report" checked class="organ-checkbox rounded bg-slate-900 border-slate-700 text-emerald-500">
              <span>csv_analyze_and_report</span>
            </label>
            <label class="flex items-center gap-2 cursor-pointer text-slate-300">
              <input type="checkbox" value="file_transform" class="organ-checkbox rounded bg-slate-900 border-slate-700 text-emerald-500">
              <span>file_transform</span>
            </label>
            <label class="flex items-center gap-2 cursor-pointer text-slate-300">
              <input type="checkbox" value="blender_run_python" class="organ-checkbox rounded bg-slate-900 border-slate-700 text-emerald-500">
              <span>blender_run_python</span>
            </label>
            <label class="flex items-center gap-2 cursor-pointer text-slate-300">
              <input type="checkbox" value="windows_command" class="organ-checkbox rounded bg-slate-900 border-slate-700 text-emerald-500">
              <span>windows_command</span>
            </label>
            <label class="flex items-center gap-2 cursor-pointer text-slate-300">
              <input type="checkbox" value="window_inspect" class="organ-checkbox rounded bg-slate-900 border-slate-700 text-emerald-500">
              <span>window_inspect</span>
            </label>
          </div>
        </div>
        <div class="flex items-center justify-between pt-1">
          <label class="flex items-center gap-2 cursor-pointer text-slate-300">
            <input type="checkbox" id="draft-irreversible" class="rounded bg-slate-900 border-slate-700 text-emerald-500">
            <span>Allow Irreversible Operations</span>
          </label>
          <div class="flex items-center gap-2">
            <button onclick="closeAgentModals()" class="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 rounded-lg text-slate-300 transition">Cancel</button>
            <button onclick="saveAgentDraft()" class="px-4 py-1.5 bg-emerald-600 hover:bg-emerald-500 font-bold text-white rounded-lg transition shadow">Save Draft</button>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Agent Releases History Modal -->
  <div id="agent-releases-modal" class="fixed inset-0 z-50 bg-black/85 backdrop-blur-md hidden flex items-center justify-center p-4">
    <div class="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-2xl max-h-[85vh] flex flex-col shadow-2xl overflow-hidden">
      <div class="px-5 py-3 border-b border-slate-800 flex items-center justify-between bg-slate-950/80">
        <h3 id="releases-modal-title" class="text-sm font-bold text-sky-400 font-mono">Agent Releases</h3>
        <button onclick="closeAgentModals()" class="text-slate-400 hover:text-white text-base font-bold">✕</button>
      </div>
      <div id="releases-modal-list" class="flex-1 overflow-auto p-4 space-y-3 bg-slate-900">
        <p class="text-xs text-slate-500">Loading releases...</p>
      </div>
    </div>
  </div>

  <script>
    function setPrompt(text) {
      document.getElementById('prompt-input').value = text;
    }

    async function dispatchUserTask() {
      const input = document.getElementById('prompt-input');
      const goal = input.value.trim();
      if (!goal) return;

      const launchGui = document.getElementById('check-launch-gui').checked;
      const model = document.getElementById('select-model').value;
      const agentId = document.getElementById('select-agent') ? document.getElementById('select-agent').value : 'auto';
      const btn = document.getElementById('dispatch-btn');
      const card = document.getElementById('live-status-card');
      const title = document.getElementById('live-status-title');
      const detail = document.getElementById('live-status-detail');
      const linkDiv = document.getElementById('live-status-link');

      btn.disabled = true;
      btn.innerText = '⏳ Executing...';
      card.classList.remove('hidden');
      title.innerText = '⚡ Executing task: ' + goal;
      detail.innerText = `Agent: [${agentId}] · Model: ${model} synthesizing solution...`;
      linkDiv.innerHTML = '';

      try {
        const res = await fetch('/api/tasks/dispatch', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ goal: goal, launch_gui: launchGui, model: model, agent_id: agentId })
        });
        const data = await res.json();
        title.innerText = `✓ Task Completed: ${data.state} (Took ${data.attempts_taken} attempt(s))`;
        title.className = data.success ? 'font-bold text-emerald-400' : 'font-bold text-rose-400';
        detail.innerText = `Agent: ${data.agent_id || agentId} · Model: ${data.model || model} · Domain: ${data.domain || 'general'} · Artifact: ${data.artifact_filename || 'None'} (${data.artifact_size_bytes} bytes).`;
        
        if (data.download_url) {
          linkDiv.innerHTML = `<a href="${data.download_url}" target="_blank" class="text-sky-400 underline font-semibold text-[11px]">📥 Download Artifact (${data.artifact_filename || 'File'} · ${data.artifact_size_bytes} bytes)</a>`;
        }
        if (data.gui_launch && data.gui_launch.pid) {
          detail.innerText += ` [Blender 4.5 GUI opened on desktop - PID: ${data.gui_launch.pid}]`;
        }
        refreshAll();
      } catch (e) {
        title.innerText = '❌ Task Failed';
        detail.innerText = String(e);
      } finally {
        btn.disabled = false;
        btn.innerText = '🚀 Dispatch Task';
      }
    }

    function switchTab(tabId) {
      document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));
      document.querySelectorAll('.tab-btn').forEach(el => {
        el.classList.remove('border-b-2', 'border-sky-400', 'text-sky-400');
        el.classList.add('hover:text-slate-200');
      });
      document.getElementById(tabId).classList.remove('hidden');
      const btnId = 'btn-' + tabId.replace('tab-', '');
      const btn = document.getElementById(btnId);
      if (btn) btn.classList.add('border-b-2', 'border-sky-400', 'text-sky-400');
    }

    async function loadConfig() {
      const res = await fetch('/api/config');
      const cfg = await res.json();
      document.getElementById('cfg-max-attempts').value = cfg.iteration_limits.max_attempts;
      document.getElementById('cfg-timeout').value = cfg.iteration_limits.attempt_timeout_sec;
      document.getElementById('cfg-memory').value = cfg.resource_quotas.memory_limit_mb;
      document.getElementById('cfg-cpu').value = cfg.resource_quotas.cpu_rate_percent;
      document.getElementById('cfg-isolation').value = String(cfg.isolation.use_appcontainer);
      document.getElementById('cfg-irreversible').value = String(cfg.policy.allow_irreversible);
    }

    async function saveConfig() {
      const payload = {
        max_attempts: parseInt(document.getElementById('cfg-max-attempts').value, 10),
        attempt_timeout_sec: parseFloat(document.getElementById('cfg-timeout').value),
        memory_limit_mb: parseInt(document.getElementById('cfg-memory').value, 10),
        cpu_rate_percent: parseFloat(document.getElementById('cfg-cpu').value),
        use_appcontainer: document.getElementById('cfg-isolation').value === 'true',
        allow_irreversible: document.getElementById('cfg-irreversible').value === 'true',
      };
      const res = await fetch('/api/config', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        const status = document.getElementById('cfg-status');
        status.innerText = 'Configuration saved!';
        setTimeout(() => status.innerText = '', 3000);
        refreshAll();
      }
    }

    async function loadTelemetry() {
      const res = await fetch('/api/telemetry');
      const data = await res.json();
      document.getElementById('ram-val').innerText = data.hardware.available_ram_mb + ' MB';
      document.getElementById('lease-val').innerText = data.counts.highest_lease_token;
      document.getElementById('mistakes-count').innerText = data.counts.mistakes;
      document.getElementById('skills-count').innerText = data.counts.skills;
    }

    async function loadTasks() {
      const res = await fetch('/api/tasks');
      const tasks = await res.json();
      const tbody = document.getElementById('tasks-table-body');
      if (tasks.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="p-4 text-center text-slate-500">No tasks executed yet.</td></tr>';
        return;
      }
      tbody.innerHTML = tasks.map(t => {
        const badgeColor = t.state === 'Succeeded' ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' :
                           t.state === 'Failed' ? 'bg-rose-500/20 text-rose-400 border-rose-500/30' :
                           'bg-sky-500/20 text-sky-400 border-sky-500/30';
        let artLink = '<span class="text-slate-500 font-mono text-[11px]">-</span>';
        if (t.artifact_filename) {
          const ext = (t.artifact_ext || '').toUpperCase();
          const icon = ext === 'OBJ' ? '🧊' : ext === 'CSV' ? '📊' : ext === 'MD' ? '📝' : ext === 'PY' ? '🐍' : '📄';
          artLink = `
            <div class="flex items-center gap-2">
              <button onclick="previewArtifact('${t.artifact_filename}', '${t.artifact_url}', '${ext}')" 
                      class="px-2.5 py-1 bg-sky-600/30 hover:bg-sky-500/50 border border-sky-500/40 text-sky-300 rounded text-[11px] font-semibold flex items-center gap-1 transition shadow-sm">
                <span>👁️</span> Preview
              </button>
              <a href="${t.artifact_url}" download class="text-slate-400 hover:text-slate-200 text-[11px] font-mono flex items-center gap-1">
                <span>${icon}</span> ${t.artifact_filename}
              </a>
            </div>
          `;
        }
        return `
          <tr class="hover:bg-slate-700/30">
            <td class="p-2.5 font-mono text-slate-300">${t.id}</td>
            <td class="p-2.5 font-medium text-slate-200">${t.title}</td>
            <td class="p-2.5"><span class="px-2 py-0.5 border rounded-full text-[10px] font-semibold ${badgeColor}">${t.state}</span></td>
            <td class="p-2.5 text-slate-400">${t.attempt_count} / ${t.max_attempts}</td>
            <td class="p-2.5 text-slate-400">${artLink}</td>
          </tr>
        `;
      }).join('');
    }

    async function loadMistakes() {
      const res = await fetch('/api/mistakes');
      const list = await res.json();
      const c = document.getElementById('mistakes-container');
      if (list.length === 0) {
        c.innerHTML = '<p class="text-xs text-slate-500">No mistakes logged yet.</p>';
        return;
      }
      c.innerHTML = list.map(m => `
        <div class="bg-slate-900/70 border border-amber-500/20 rounded-lg p-3 space-y-1">
          <div class="flex items-center justify-between">
            <span class="text-amber-400 font-semibold text-xs">[${m.error_category}] ${m.error_signature}</span>
            <span class="text-[10px] text-slate-500 font-mono">${m.task_id}</span>
          </div>
          <p class="text-xs text-slate-300 font-medium">Lesson: <span class="text-slate-200 font-normal">${m.lesson_learned}</span></p>
        </div>
      `).join('');
    }

    async function loadSkills() {
      const res = await fetch('/api/skills');
      const list = await res.json();
      const c = document.getElementById('skills-container');
      if (list.length === 0) {
        c.innerHTML = '<p class="text-xs text-slate-500">No skills distilled yet.</p>';
        return;
      }
      c.innerHTML = list.map(s => `
        <div class="bg-slate-900/70 border border-purple-500/20 rounded-lg p-3 space-y-2">
          <div class="flex items-center justify-between">
            <span class="text-purple-400 font-bold text-xs">${s.name}</span>
            <span class="text-[10px] text-slate-400">v${s.version}</span>
          </div>
          <p class="text-xs text-slate-300">${s.description}</p>
          <pre class="bg-slate-950 p-2 rounded text-[10px] font-mono text-emerald-400 overflow-x-auto max-h-36">${s.code}</pre>
        </div>
      `).join('');
    }

    async function loadTools() {
      const res = await fetch('/api/tools');
      const list = await res.json();
      const c = document.getElementById('tools-container');
      c.innerHTML = list.map(t => `
        <div class="bg-slate-900/60 border border-slate-700 rounded-lg p-3 flex items-center justify-between">
          <div>
            <span class="font-bold text-xs text-sky-400">${t.name}</span>
            <p class="text-xs text-slate-300">${t.description}</p>
          </div>
          <span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-800 border border-slate-700 text-slate-300">${t.effect_class}</span>
        </div>
      `).join('');
    }

    async function loadAgents() {
      const res = await fetch('/api/agents');
      const agents = await res.json();
      const c = document.getElementById('agents-container');
      if (!c) return;

      const selectAgent = document.getElementById('select-agent');
      if (selectAgent) {
        const curVal = selectAgent.value;
        selectAgent.innerHTML = `
          <option value="auto">🤖 Auto-Detect Agent</option>
          ${agents.map(a => `<option value="${a.id}">${a.name} (${(a.manifest.capabilities || [])[0] || 'general'})</option>`).join('')}
        `;
        selectAgent.value = curVal || 'auto';
      }

      if (agents.length === 0) {
        c.innerHTML = '<p class="text-xs text-slate-500">No agents registered.</p>';
        return;
      }

      c.innerHTML = agents.map(a => {
        const isDraft = a.status === 'Draft';
        const isPub = a.status === 'Published';
        const statusBadge = isPub 
          ? '<span class="text-[10px] px-2.5 py-0.5 rounded font-mono font-semibold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">✓ Published</span>'
          : isDraft
          ? '<span class="text-[10px] px-2.5 py-0.5 rounded font-mono font-semibold bg-amber-500/20 text-amber-400 border border-amber-500/30">✎ Draft</span>'
          : '<span class="text-[10px] px-2.5 py-0.5 rounded font-mono font-semibold bg-rose-500/20 text-rose-400 border border-rose-500/30">⛔ ' + a.status + '</span>';

        const organs = (a.manifest.allowed_organs || []).map(o => 
          `<span class="px-2 py-0.5 bg-slate-950 border border-slate-700/80 rounded text-[10px] font-mono text-sky-300">${o}</span>`
        ).join(' ');

        return `
          <div class="bg-slate-900/90 border border-slate-700/80 rounded-xl p-4 space-y-3 shadow-md hover:border-slate-600 transition flex flex-col justify-between">
            <div class="space-y-2">
              <div class="flex items-start justify-between gap-2">
                <div>
                  <h3 class="font-bold text-sm text-slate-100 flex items-center gap-1.5">
                    <span>🤖</span> ${a.name}
                  </h3>
                  <p class="text-[11px] font-mono text-slate-400 mt-0.5">${a.id} · <span class="text-sky-400 font-semibold">v${a.current_version}</span></p>
                </div>
                ${statusBadge}
              </div>

              <p class="text-xs text-slate-300 leading-relaxed">${a.manifest.description || 'Specialized autonomous agent.'}</p>

              <!-- Capability Whitelist -->
              <div class="space-y-1 pt-1">
                <span class="text-[10px] uppercase tracking-wider font-semibold text-slate-400">PDP Allowed Organs:</span>
                <div class="flex flex-wrap gap-1 pt-0.5">
                  ${organs || '<span class="text-[10px] text-slate-500">None</span>'}
                </div>
              </div>

              <!-- Resource Caps -->
              <div class="flex items-center gap-3 text-[10px] text-slate-400 font-mono pt-1">
                <span>Mem: <span class="text-slate-200">${a.manifest.max_memory_mb || 100}MB</span></span>
                <span>CPU: <span class="text-slate-200">${a.manifest.max_cpu_percent || 12.5}%</span></span>
                <span>Irreversible: <span class="${a.manifest.allow_irreversible ? 'text-amber-400 font-bold' : 'text-slate-400'}">${a.manifest.allow_irreversible ? 'ALLOWED' : 'DENIED'}</span></span>
              </div>
            </div>

            <!-- Action Controls -->
            <div class="pt-3 border-t border-slate-800/80 flex items-center justify-between gap-2">
              <button onclick="viewAgentReleases('${a.id}', '${a.name}')" 
                      class="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 border border-slate-600 text-slate-300 rounded text-[11px] font-semibold transition flex items-center gap-1">
                <span>📜</span> Releases
              </button>
              
              <div class="flex items-center gap-1.5">
                ${isDraft ? `
                  <button onclick="publishAgentRelease('${a.id}', '${a.current_version}')" 
                          class="px-3 py-1 bg-emerald-600 hover:bg-emerald-500 text-white rounded text-[11px] font-bold shadow transition flex items-center gap-1">
                    <span>🚀</span> Publish Release
                  </button>
                ` : `
                  <span class="text-[10px] text-slate-500 font-mono">Immutable</span>
                `}
                ${a.status !== 'Deprecated' ? `
                  <button onclick="deprecateAgent('${a.id}')" title="Deprecate Agent" class="px-2 py-1 text-slate-500 hover:text-rose-400 text-[11px] transition">⛔</button>
                ` : ''}
              </div>
            </div>
          </div>
        `;
      }).join('');
    }

    async function publishAgentRelease(agentId, version) {
      if (!confirm(`Publish immutable release v${version} for agent '${agentId}'?\\nThis will compute a canonical SHA-256 provenance hash.`)) return;
      try {
        const res = await fetch('/api/agents/publish', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ agent_id: agentId, version: version, publisher: 'Sentinel Operator' })
        });
        const data = await res.json();
        if (res.ok) {
          alert(`✓ Agent '${agentId}' v${version} published successfully!\\nProvenance SHA256: ${data.provenance_hash}`);
          loadAgents();
        } else {
          alert('Error publishing release: ' + (data.detail || JSON.stringify(data)));
        }
      } catch (e) {
        alert('Request failed: ' + e);
      }
    }

    async function viewAgentReleases(agentId, agentName) {
      const modal = document.getElementById('agent-releases-modal');
      const title = document.getElementById('releases-modal-title');
      const listDiv = document.getElementById('releases-modal-list');
      title.innerText = `Releases & Provenance: ${agentName} (${agentId})`;
      modal.classList.remove('hidden');
      listDiv.innerHTML = '<p class="text-xs text-slate-500 p-4">Loading releases...</p>';

      try {
        const res = await fetch(`/api/agents/${agentId}/releases`);
        const releases = await res.json();
        if (!releases.length) {
          listDiv.innerHTML = '<p class="text-xs text-slate-500 p-4">No immutable releases recorded yet.</p>';
          return;
        }
        listDiv.innerHTML = releases.map(r => `
          <div class="bg-slate-950 border border-slate-800 rounded-lg p-3 space-y-1.5">
            <div class="flex items-center justify-between">
              <span class="font-bold text-sky-400 text-xs font-mono">Release v${r.version}</span>
              <span class="text-[10px] text-slate-400">${new Date(r.published_at * 1000).toLocaleString()} by ${r.published_by}</span>
            </div>
            <div class="space-y-0.5">
              <span class="text-[10px] text-slate-400 uppercase tracking-wider font-semibold">SHA-256 Provenance Hash (AT-A-02):</span>
              <div class="bg-slate-900 px-2 py-1 rounded text-[11px] font-mono text-emerald-400 select-all break-all border border-slate-800">
                ${r.provenance_hash}
              </div>
            </div>
            <div class="text-[10px] text-slate-400">
              Allowed Organs Snapshot: <span class="text-slate-300 font-mono">${(r.manifest_snapshot.allowed_organs || []).join(', ')}</span>
            </div>
          </div>
        `).join('');
      } catch (e) {
        listDiv.innerHTML = '<p class="text-rose-400 p-4 text-xs">Failed to load releases: ' + e + '</p>';
      }
    }

    function openAgentDraftModal() {
      document.getElementById('agent-draft-modal').classList.remove('hidden');
    }

    function closeAgentModals() {
      document.getElementById('agent-draft-modal').classList.add('hidden');
      document.getElementById('agent-releases-modal').classList.add('hidden');
    }

    async function saveAgentDraft() {
      const agentId = document.getElementById('draft-id').value.trim();
      const name = document.getElementById('draft-name').value.trim();
      const version = document.getElementById('draft-version').value.trim() || '1.0.0';
      const desc = document.getElementById('draft-desc').value.trim();
      if (!agentId || !name) {
        alert('Agent ID and Name are required.');
        return;
      }

      const allowedOrgans = [];
      document.querySelectorAll('.organ-checkbox:checked').forEach(cb => allowedOrgans.push(cb.value));

      try {
        const res = await fetch('/api/agents/draft', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            agent_id: agentId,
            name: name,
            version: version,
            description: desc,
            allowed_organs: allowedOrgans,
            allow_irreversible: document.getElementById('draft-irreversible').checked
          })
        });
        if (res.ok) {
          closeAgentModals();
          loadAgents();
          alert(`✓ Draft agent '${name}' registered successfully!`);
        } else {
          const d = await res.json();
          alert('Failed to register agent: ' + (d.detail || JSON.stringify(d)));
        }
      } catch (e) {
        alert('Error: ' + e);
      }
    }

    async function deprecateAgent(agentId) {
      if (!confirm(`Are you sure you want to deprecate agent '${agentId}'?`)) return;
      try {
        await fetch('/api/agents/deprecate', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ agent_id: agentId })
        });
        loadAgents();
      } catch (e) {
        alert('Failed to deprecate: ' + e);
      }
    }

    function refreshAll() {
      loadTelemetry();
      loadTasks();
      loadAgents();
      loadMistakes();
      loadSkills();
      loadTools();
    }

    let threeScene, threeCamera, threeRenderer, threeControls, currentObj;

    function initThree() {
      const container = document.getElementById('three-container');
      if (threeRenderer) return;

      threeScene = new THREE.Scene();
      threeScene.background = new THREE.Color(0x0a0f1d);

      threeCamera = new THREE.PerspectiveCamera(45, container.clientWidth / container.clientHeight, 0.1, 1000);
      threeCamera.position.set(0, 2, 5);

      threeRenderer = new THREE.WebGLRenderer({ antialias: true });
      threeRenderer.setSize(container.clientWidth, container.clientHeight);
      threeRenderer.setPixelRatio(window.devicePixelRatio);
      container.appendChild(threeRenderer.domElement);

      threeControls = new THREE.OrbitControls(threeCamera, threeRenderer.domElement);
      threeControls.enableDamping = true;
      threeControls.dampingFactor = 0.05;

      const ambientLight = new THREE.AmbientLight(0xffffff, 0.85);
      threeScene.add(ambientLight);

      const dirLight1 = new THREE.DirectionalLight(0x38bdf8, 1.2);
      dirLight1.position.set(5, 10, 7);
      threeScene.add(dirLight1);

      const dirLight2 = new THREE.DirectionalLight(0xec4899, 0.6);
      dirLight2.position.set(-5, -5, -5);
      threeScene.add(dirLight2);

      const grid = new THREE.GridHelper(10, 20, 0x1e293b, 0x0f172a);
      grid.position.y = -1;
      threeScene.add(grid);

      function animate() {
        requestAnimationFrame(animate);
        threeControls.update();
        threeRenderer.render(threeScene, threeCamera);
      }
      animate();

      window.addEventListener('resize', () => {
        if (!container.clientWidth) return;
        threeCamera.aspect = container.clientWidth / container.clientHeight;
        threeCamera.updateProjectionMatrix();
        threeRenderer.setSize(container.clientWidth, container.clientHeight);
      });
    }

    async function previewArtifact(filename, url, ext) {
      const modal = document.getElementById('preview-modal');
      const title = document.getElementById('modal-title');
      const badge = document.getElementById('modal-badge');
      const icon = document.getElementById('modal-icon');
      const downloadBtn = document.getElementById('modal-download');
      
      const threeBox = document.getElementById('three-container');
      const csvBox = document.getElementById('csv-container');
      const codeBox = document.getElementById('code-container');

      title.innerText = filename;
      downloadBtn.href = url;
      modal.classList.remove('hidden');

      threeBox.classList.add('hidden');
      csvBox.classList.add('hidden');
      codeBox.classList.add('hidden');

      const uExt = (ext || '').toUpperCase();
      if (uExt === 'OBJ') {
        icon.innerText = '🧊';
        badge.innerText = '3D Wavefront OBJ Mesh';
        badge.className = 'ml-2 px-2.5 py-0.5 text-[10px] font-semibold rounded bg-sky-500/20 text-sky-400 border border-sky-500/30';
        threeBox.classList.remove('hidden');
        document.getElementById('three-loading').classList.remove('hidden');
        
        setTimeout(() => {
          initThree();
          if (currentObj) threeScene.remove(currentObj);

          const loader = new THREE.OBJLoader();
          loader.load(url, function (obj) {
            let vCount = 0;
            let fCount = 0;
            const mat = new THREE.MeshStandardMaterial({
              color: 0x94a3b8,
              metalness: 0.65,
              roughness: 0.25,
            });
            obj.traverse(function (child) {
              if (child.isMesh) {
                child.material = mat;
                if (child.geometry) {
                  vCount += child.geometry.attributes.position ? child.geometry.attributes.position.count : 0;
                  fCount += child.geometry.index ? child.geometry.index.count / 3 : (child.geometry.attributes.position ? child.geometry.attributes.position.count / 3 : 0);
                }
              }
            });

            const box = new THREE.Box3().setFromObject(obj);
            const center = box.getCenter(new THREE.Vector3());
            const size = box.getSize(new THREE.Vector3());
            obj.position.sub(center);

            const maxDim = Math.max(size.x, size.y, size.z) || 1;
            threeCamera.position.set(0, maxDim * 0.9, maxDim * 2.2);
            threeControls.target.set(0, 0, 0);

            threeScene.add(obj);
            currentObj = obj;

            document.getElementById('three-stats').innerText = `Vertices: ${vCount.toLocaleString()} · Faces: ${Math.round(fCount).toLocaleString()}`;
            document.getElementById('three-loading').classList.add('hidden');
          }, undefined, function (err) {
            document.getElementById('three-loading').innerText = 'Failed to parse 3D mesh: ' + err;
          });
        }, 120);

      } else if (uExt === 'CSV') {
        icon.innerText = '📊';
        badge.innerText = 'CSV Dataset (RFC 4180)';
        badge.className = 'ml-2 px-2.5 py-0.5 text-[10px] font-semibold rounded bg-emerald-500/20 text-emerald-400 border border-emerald-500/30';
        csvBox.classList.remove('hidden');
        csvBox.innerHTML = '<div class="text-center p-8 text-slate-500">Loading dataset...</div>';
        
        try {
          const res = await fetch(url);
          const raw = await res.text();
          const rows = raw.trim().split('\\n').map(r => r.split(','));
          if (!rows.length) {
            csvBox.innerHTML = '<div class="text-center p-8 text-slate-500">Empty dataset</div>';
            return;
          }
          const headers = rows[0];
          const dataRows = rows.slice(1);
          let html = `<div class="border border-slate-800 rounded-lg overflow-hidden shadow-inner">
            <table class="w-full text-left divide-y divide-slate-800 text-xs">
              <thead class="bg-slate-900 text-sky-400 uppercase tracking-wider text-[11px] font-bold sticky top-0">
                <tr>${headers.map(h => `<th class="p-3 border-r border-slate-800 last:border-0">${h.trim()}</th>`).join('')}</tr>
              </thead>
              <tbody class="divide-y divide-slate-800/60 font-mono text-slate-300">
                ${dataRows.map(row => `<tr class="hover:bg-slate-800/40">${row.map(c => `<td class="p-2.5 border-r border-slate-800/40 last:border-0">${c.trim()}</td>`).join('')}</tr>`).join('')}
              </tbody>
            </table>
          </div>
          <div class="pt-2 text-[11px] text-slate-400 font-mono">Total rows: ${dataRows.length} · Columns: ${headers.length}</div>`;
          csvBox.innerHTML = html;
        } catch (e) {
          csvBox.innerHTML = '<div class="text-rose-400 p-4">Error loading CSV: ' + e + '</div>';
        }

      } else {
        // Code (.py) or Markdown (.md)
        icon.innerText = uExt === 'PY' ? '🐍' : '📝';
        badge.innerText = uExt === 'PY' ? 'Python Source Code' : 'Markdown Analysis Report';
        badge.className = uExt === 'PY' ? 'ml-2 px-2.5 py-0.5 text-[10px] font-semibold rounded bg-amber-500/20 text-amber-400 border border-amber-500/30' : 'ml-2 px-2.5 py-0.5 text-[10px] font-semibold rounded bg-purple-500/20 text-purple-400 border border-purple-500/30';
        codeBox.classList.remove('hidden');
        codeBox.innerText = 'Loading file contents...';

        try {
          const res = await fetch(url);
          const raw = await res.text();
          codeBox.innerText = raw;
        } catch (e) {
          codeBox.innerText = 'Error loading file: ' + e;
        }
      }
    }

    function closePreviewModal() {
      document.getElementById('preview-modal').classList.add('hidden');
    }

    window.onload = () => {
      loadConfig();
      refreshAll();
      setInterval(loadTelemetry, 3000);
    };
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(content=DASHBOARD_HTML)


def start_server(host: str = "127.0.0.1", port: int = 8000):
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    start_server()
