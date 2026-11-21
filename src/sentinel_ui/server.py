"""Sentinel Control UI & REST API Server (FastAPI).
Serves real-time telemetry, configuration management, mistake inspection, and interactive task dispatch.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

src_dir = Path(__file__).parent.parent.resolve()
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import psutil

from sentinel_core.config import SentinelConfig, RetentionConfig
from sentinel_core.pruner import StoragePruner
from sentinel_core.db import SentinelDB
from sentinel_core.state_machine import StateMachine
from sentinel_core.side_effects import SideEffectLedger
from sentinel_core.verification_gate import VerificationGate, VerificationResult
from sentinel_core.agent_registry import AgentRegistry, AgentManifest
from sentinel_core.dag_orchestrator import (
    DAGOrchestrator,
    DAGStepDefinition,
    DAGState,
    DAGStepState,
    format_predecessor_artifacts,
)
from sentinel_core.dag_planner import DAGPlanner
from sentinel_adaptive.mistake_ledger import MistakeMemory
from sentinel_adaptive.skill_bank import SkillBank, derive_semantic_slug
from sentinel_broker.tool_registry import ToolRegistry
from sentinel_broker.pdp import PolicyDecisionPoint
from sentinel_broker.broker import ExecutionBroker
from sentinel_broker.organs.sensory import register_sensory_organs
from sentinel_broker.organs.motor import register_motor_organs
from sentinel_broker.organs.blender import register_blender_organs
from sentinel_broker.organs.blender_prompts import synthesize_blender_script, synthesize_procedural_fallback
from sentinel_broker.organs.data_organ import register_data_organs
from sentinel_broker.organs.web_organ import register_web_organs
from sentinel_broker.organs.desktop_organ import register_desktop_organs
from sentinel_runner.appcontainer_host import AppContainerHost
from sentinel_core.llm_gateway import LLMGateway
from sentinel_core.hybrid_gateway import HybridModelGateway
from sentinel_core.preflight_linter import PreFlightLinter
from sentinel_core.contract_library import ContractLibrary
from sentinel_core.prompt_scaffolder import PromptScaffolder, ScaffoldingLevel
from sentinel_adaptive.pilot_controller import AdaptivePilotController
from sentinel_adaptive.react_controller import ReActController
from sentinel_ui.telemetry_stream import broadcaster
from sentinel_gym.sensor_rig import BlenderSensorRig, CSVSensorRig
from sentinel_gym.critic import HarshCritic
from sentinel_gym.curriculum import CurriculumGenerator
from sentinel_gym.auto_refiner import AutoRefiner
from sentinel_gym.daemon import GymnasiumDaemon
from sentinel_gym.blueprint import ProgressiveLoDDecomposer, compile_blueprint_to_bpy

logger = logging.getLogger("SentinelServer")

app = FastAPI(title="Sentinel Control Plane", version="1.0.0")


@app.on_event("startup")
async def on_startup():
    try:
        broadcaster.set_loop(asyncio.get_running_loop())
    except Exception as e:
        logger.debug("TelemetryBroadcaster loop registration: %s", e)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_no_cache_header(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static") or path == "/" or path.startswith("/workspaces"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# Global Sentinel Context
CONFIG_PATH = Path("config.yaml")
config = SentinelConfig.load(CONFIG_PATH)

workspaces_dir = Path(config.storage.workspaces_dir).resolve()
workspaces_dir.mkdir(parents=True, exist_ok=True)
repo_workspaces_dir = (Path(__file__).parent.parent.parent / "workspaces").resolve()
repo_workspaces_dir.mkdir(parents=True, exist_ok=True)


def find_artifact_file(filename_or_path: str) -> Path | None:
    """Finds an artifact file across the primary workspace directory and repository workspaces directory."""
    if not filename_or_path:
        return None
    name = Path(filename_or_path).name

    # 1. Check primary configured workspace dir
    p1 = workspaces_dir / name
    if p1.is_file():
        return p1

    # 2. Check repo workspaces directory
    p2 = repo_workspaces_dir / name
    if p2.is_file():
        return p2

    # 3. Direct path check if absolute or relative exists
    try:
        p3 = Path(filename_or_path).resolve()
        if p3.is_file():
            return p3
    except Exception:
        pass

    return None


@app.get("/workspaces/{filename:path}")
def get_workspace_artifact(filename: str):
    found = find_artifact_file(filename)
    if not found or not found.is_file():
        raise HTTPException(status_code=404, detail=f"Artifact '{filename}' not found")

    ext = found.suffix.lower()
    media_types = {
        ".obj": "model/obj",
        ".mtl": "text/plain",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
        ".bmp": "image/bmp",
        ".ico": "image/x-icon",
        ".csv": "text/csv; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".md": "text/markdown; charset=utf-8",
        ".py": "text/x-python; charset=utf-8",
        ".txt": "text/plain; charset=utf-8",
        ".html": "text/html; charset=utf-8",
    }
    media_type = media_types.get(ext, "application/octet-stream")
    return FileResponse(path=str(found), media_type=media_type, filename=found.name, headers={"Cache-Control": "no-cache"})

static_dir = (Path(__file__).parent / "static").resolve()
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

db = SentinelDB(config.storage.db_path)
state_machine = StateMachine(db)
verification_gate = VerificationGate(db)
mistake_memory = MistakeMemory(db)
tool_registry = ToolRegistry()
side_effects = SideEffectLedger(db)
register_sensory_organs(tool_registry)
register_motor_organs(tool_registry)
register_desktop_organs(tool_registry, ledger=side_effects)
register_blender_organs(tool_registry)
register_data_organs(tool_registry)
register_web_organs(
    tool_registry,
    allowed_domains=config.network_policy.allowed_domains,
    block_private_ips=config.network_policy.block_private_ips,
    ledger=side_effects,
)
register_desktop_organs(tool_registry, ledger=side_effects)
skill_bank = SkillBank(db, config.storage.skills_dir, tool_registry=tool_registry)
skill_bank.register_distilled_skills_into_broker(tool_registry)

# Empirical Sensor Rig and Vision-Aware Harsh Critic
blender_sensor_rig = BlenderSensorRig()
harsh_critic = HarshCritic(
    llm_gateway=LLMGateway(endpoint=config.llm.endpoint, default_model=config.llm.model),
    passing_threshold=0.82,
)

# Register Self-Upgrade, Sensory Perception & Skill Composition Organs
from sentinel_broker.organs.self_upgrade import register_self_upgrade_organs
register_self_upgrade_organs(
    tool_registry,
    sensor_rig=blender_sensor_rig,
    harsh_critic=harsh_critic,
    skill_bank=skill_bank,
)

# Agent Registry & Standard Gate A Agents
agent_registry = AgentRegistry(db)

# Broker & Fenced PDP Policy Decision Point (AT-A-05, AT-B-07 to AT-B-10, R17, R19)
pdp = PolicyDecisionPoint(
    state_machine.leases,
    tool_registry,
    agent_registry,
    allowed_domains=config.network_policy.allowed_domains,
    allowed_workspaces_dir=workspaces_dir,
)
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
hybrid_gateway = HybridModelGateway(
    local_gateway=LLMGateway(endpoint=config.llm.endpoint, default_model=config.llm.model),
    config=config.hybrid_gateway,
)
active_cancellation_tokens: dict[str, threading.Event] = {}
active_running_pids: dict[str, int] = {}
pending_approvals: dict[str, dict[str, Any]] = {}


def init_standard_agents():
    std_agents = [
        AgentManifest(
            agent_id="blender_artisan",
            name="3D Procedural Artisan",
            version="1.0.0",
            description="Synthesizes procedural 3D meshes, shaders, and animations in Blender 4.5 LTS.",
            author="Sentinel Biological Systems",
            capabilities=["3d:mesh", "3d:bpy", "3d:render", "skill:compose"],
            allowed_organs=["blender_run_python", "blender_launch_gui", "blender_set_material_color", "blender_add_modifier", "blender_apply_modifiers", "blender_list_scene_objects", "execute_skill", "skill_*"],
        ),
        AgentManifest(
            agent_id="data_analyst",
            name="Data & Metrics Analyst",
            version="1.0.0",
            description="Analyzes CSV datasets, computes aggregations, and synthesizes analytical reports.",
            author="Sentinel Biological Systems",
            capabilities=["data:csv", "data:stats", "data:report", "skill:compose"],
            allowed_organs=["python_sandbox_run", "csv_analyze_and_report", "file_transform", "execute_skill", "skill_*", "broker_http_get", "system_filesystem_inspect", "system_process_inspect", "screen_capture"],
        ),
        AgentManifest(
            agent_id="code_engineer",
            name="Software Engineer",
            version="1.0.0",
            description="Synthesizes Python scripts, modules, algorithms, and executes sandboxed code.",
            author="Sentinel Biological Systems",
            capabilities=["code:python", "code:execution", "code:testing", "skill:compose"],
            allowed_organs=["python_sandbox_run", "windows_command", "execute_skill", "skill_*", "broker_http_get", "system_filesystem_inspect", "system_process_inspect", "screen_capture"],
        ),
        AgentManifest(
            agent_id="systems_reporter",
            name="Systems Executive Reporter",
            version="1.0.0",
            description="Synthesizes executive markdown reports and system health briefings.",
            author="Sentinel Biological Systems",
            capabilities=["analysis:markdown", "reporting:executive", "skill:compose"],
            allowed_organs=["python_sandbox_run", "file_transform", "execute_skill", "skill_*", "broker_http_get", "system_filesystem_inspect", "system_process_inspect", "screen_capture"],
        ),
    ]

    for m in std_agents:
        existing = agent_registry.get_agent_record(m.agent_id)
        if not existing:
            agent_registry.register_draft(m)
            try:
                agent_registry.publish_release(m.agent_id, m.version, publisher="Sentinel Core")
            except Exception:
                pass
        else:
            # Sync allowed_organs to include execute_skill, skill_*, broker_http_get, system_filesystem_inspect, system_process_inspect, screen_capture
            curr_manifest = json.loads(existing["manifest_json"])
            organs = curr_manifest.get("allowed_organs", [])
            updated = False
            for req_org in ["execute_skill", "skill_*", "broker_http_get", "system_filesystem_inspect", "system_process_inspect", "screen_capture"]:
                if req_org not in organs:
                    organs.append(req_org)
                    updated = True
            if updated or existing["status"] != "Published":
                curr_manifest["allowed_organs"] = organs
                with db.transaction() as c:
                    c.execute(
                        "UPDATE agents SET manifest_json = ?, status = 'Published' WHERE id = ?",
                        (json.dumps(curr_manifest), m.agent_id),
                    )


init_standard_agents()
dag_orchestrator = DAGOrchestrator(db)


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
    domain: str | None = None
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


class DAGDispatchRequest(BaseModel):
    template: str | None = None
    goal: str | None = None
    name: str | None = None
    description: str | None = None
    steps: list[dict[str, Any]] | None = None
    model: str | None = None
    concurrent: bool = True


class DAGPlanRequest(BaseModel):
    goal: str
    model: str | None = None


class AgentReActRequest(BaseModel):
    goal: str
    agent_id: str = "systems_reporter"
    model: str | None = None
    max_turns: int = 6


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


@app.get("/api/workspace/path")
def get_workspace_path():
    """Returns dynamic workspace directory paths for UI components."""
    return {
        "workspace_dir": str(workspaces_dir.resolve()).replace("\\", "/"),
        "repo_workspace_dir": str(repo_workspaces_dir.resolve()).replace("\\", "/"),
    }


# --- Real-Time Telemetry & Event Streaming (Pillar 1) ---

@app.get("/api/events")
async def event_stream_global(request: Request):
    """Global SSE stream broadcasting real-time task states, tool invocations, and approvals."""
    async def event_generator():
        q = broadcaster.subscribe(None)
        for item in broadcaster.get_recent_history(None, limit=20):
            yield f"data: {json.dumps(item)}\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {json.dumps(payload)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            broadcaster.unsubscribe(q, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/tasks/{task_id}/events")
async def event_stream_task(task_id: str, request: Request):
    """Task-specific SSE stream for live agent thought/tool execution trace."""
    async def event_generator():
        q = broadcaster.subscribe(task_id)
        for item in broadcaster.get_recent_history(task_id, limit=20):
            yield f"data: {json.dumps(item)}\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {json.dumps(payload)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            broadcaster.unsubscribe(q, task_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --- Human-in-the-Loop (HITL) Interactive Checkpoints (Pillar 2) ---

class ApprovalResolutionRequest(BaseModel):
    operator: str = "Operator"
    reason: str = ""


@app.get("/api/approvals")
def list_pending_approvals():
    """Lists all active tool approval checkpoints awaiting human clearance."""
    items = []
    for k, v in pending_approvals.items():
        items.append({
            "approval_id": v["approval_id"],
            "task_id": v["task_id"],
            "tool_name": v["tool_name"],
            "params": v["params"],
            "reason": v["reason"],
            "created_at": v["created_at"],
        })
    return items


@app.post("/api/approvals/{approval_id}/approve")
def approve_pending_action(approval_id: str, req: ApprovalResolutionRequest | None = None):
    """Operator approves a paused irreversible tool invocation."""
    op = req.operator if req else "Operator"
    rec = pending_approvals.get(approval_id)
    if not rec:
        for v in pending_approvals.values():
            if v["task_id"] == approval_id:
                rec = v
                break
    if not rec:
        raise HTTPException(status_code=404, detail="No pending approval matching ID")

    rec["decision"] = "APPROVED"
    rec["operator"] = op
    rec["event"].set()
    logger.info("HITL Checkpoint %s approved by %s", rec["approval_id"], op)
    return {"status": "APPROVED", "approval_id": rec["approval_id"], "task_id": rec["task_id"]}


@app.post("/api/approvals/{approval_id}/deny")
def deny_pending_action(approval_id: str, req: ApprovalResolutionRequest | None = None):
    """Operator denies a paused irreversible tool invocation."""
    op = req.operator if req else "Operator"
    rec = pending_approvals.get(approval_id)
    if not rec:
        for v in pending_approvals.values():
            if v["task_id"] == approval_id:
                rec = v
                break
    if not rec:
        raise HTTPException(status_code=404, detail="No pending approval matching ID")

    rec["decision"] = "DENIED"
    rec["operator"] = op
    rec["event"].set()
    logger.info("HITL Checkpoint %s denied by %s", rec["approval_id"], op)
    return {"status": "DENIED", "approval_id": rec["approval_id"], "task_id": rec["task_id"]}


class HybridRouteRequest(BaseModel):
    goal: str
    context: str = ""
    mode: str | None = None


@app.get("/api/hybrid/status")
def get_hybrid_status():
    """Returns operational status of local GPU and cloud gateways with privacy fence policy."""
    return {
        "cloud_available": hybrid_gateway.is_cloud_available(),
        "local_available": hybrid_gateway.is_local_available(),
        "default_mode": hybrid_gateway.default_mode,
        "privacy_fence_enabled": hybrid_gateway.privacy_fence_enabled,
        "cloud_model": hybrid_gateway.cfg.cloud_model,
        "local_model": config.llm.model,
    }


@app.post("/api/hybrid/route")
def route_hybrid_task(req: HybridRouteRequest):
    """Evaluates Rule R14 / AT-C-10 Privacy Fence to determine whether a goal can egress to cloud."""
    return hybrid_gateway.get_routing_decision(
        goal=req.goal,
        context=req.context,
        mode=req.mode,
    )


@app.get("/api/telemetry")
def get_telemetry():
    mem = psutil.virtual_memory()
    tasks_count = db.execute_one("SELECT COUNT(*) as count FROM tasks")
    attempts_count = db.execute_one("SELECT COUNT(*) as count FROM attempts")
    mistakes_count = db.execute_one("SELECT COUNT(*) as count FROM mistake_ledger")
    skills_count = db.execute_one("SELECT COUNT(*) as count FROM skills")
    highest_lease = db.execute_one("SELECT COALESCE(MAX(lease_token), 0) as max_lease FROM attempts")
    db_file = Path(db.db_path)

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
        "storage": {
            "retention_enabled": config.retention.enabled,
            "max_task_age_days": config.retention.max_task_age_days,
            "max_tasks_count": config.retention.max_tasks_count,
            "db_size_mb": round((db_file.stat().st_size if db_file.exists() else 0) / (1024 * 1024), 2),
        },
    }


@app.get("/api/observability/storage")
def get_storage_stats():
    return StoragePruner.get_storage_summary(db, repo_workspaces_dir)


class PruneRequest(BaseModel):
    max_task_age_days: int | None = None
    max_tasks_count: int | None = None
    prune_workspaces: bool | None = None
    deduplicate_mistakes: bool | None = None
    vacuum: bool | None = None


@app.post("/api/observability/prune")
def prune_storage_endpoint(req: PruneRequest = None):
    req_dict = req.dict() if req else {}
    max_age = req_dict.get("max_task_age_days") if req_dict.get("max_task_age_days") is not None else config.retention.max_task_age_days
    max_tasks = req_dict.get("max_tasks_count") if req_dict.get("max_tasks_count") is not None else config.retention.max_tasks_count
    prune_ws = req_dict.get("prune_workspaces") if req_dict.get("prune_workspaces") is not None else config.retention.prune_orphan_workspaces
    dedup = req_dict.get("deduplicate_mistakes") if req_dict.get("deduplicate_mistakes") is not None else config.retention.deduplicate_mistakes
    vacuum = req_dict.get("vacuum") if req_dict.get("vacuum") is not None else config.retention.vacuum_db_on_prune

    cfg = RetentionConfig(
        enabled=True,
        max_task_age_days=max_age,
        max_tasks_count=max_tasks,
        prune_orphan_workspaces=prune_ws,
        deduplicate_mistakes=dedup,
        vacuum_db_on_prune=vacuum,
    )
    result = StoragePruner.prune_all(db, repo_workspaces_dir, cfg)
    broadcaster.emit("storage_pruned", result.to_dict())
    return {"status": "success", "result": result.to_dict()}


@app.get("/api/tasks")
def list_tasks():
    rows = db.execute_read("SELECT * FROM tasks ORDER BY created_at DESC LIMIT 50")
    res = []
    for r in rows:
        d = dict(r)
        tid = d["id"]
        # Find matching artifact in workspaces_dir or repo_workspaces_dir
        matches = list(workspaces_dir.glob(f"{tid}.*"))
        if not matches and repo_workspaces_dir.exists():
            matches = list(repo_workspaces_dir.glob(f"{tid}.*"))
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


@app.get("/api/tasks/{task_id}/trace")
def get_task_trace(task_id: str):
    task = db.execute_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

    task_dict = dict(task)

    # 1. State machine transitions
    transitions = db.execute_read(
        "SELECT from_state, to_state, reason, transition_ts FROM task_transitions WHERE task_id = ? ORDER BY transition_ts ASC",
        (task_id,),
    )

    # 2. Attempts & Side Effect Tool Executions
    attempts = db.execute_read(
        "SELECT id, attempt_number, lease_token, status, started_at, finished_at FROM attempts WHERE task_id = ? ORDER BY attempt_number ASC",
        (task_id,),
    )

    steps = []
    for tr in transitions:
        steps.append({
            "type": "transition",
            "from_state": tr["from_state"],
            "to_state": tr["to_state"],
            "reason": tr["reason"],
            "ts": tr["transition_ts"],
        })

    for att in attempts:
        effects = db.execute_read(
            "SELECT id, effect_class, tool_name, intent_payload, outcome_payload, status, created_at FROM side_effect_ledger WHERE attempt_id = ? ORDER BY created_at ASC",
            (att["id"],),
        )
        for eff in effects:
            try:
                intent = json.loads(eff["intent_payload"])
            except Exception:
                intent = eff["intent_payload"]
            try:
                outcome = json.loads(eff["outcome_payload"]) if eff["outcome_payload"] else None
            except Exception:
                outcome = eff["outcome_payload"]
            steps.append({
                "type": "tool_execution",
                "attempt": att["attempt_number"],
                "lease_token": att["lease_token"],
                "tool_name": eff["tool_name"],
                "effect_class": eff["effect_class"],
                "intent": intent,
                "outcome": outcome,
                "status": eff["status"],
                "ts": eff["created_at"],
            })

    # 3. Mistakes
    mistakes = db.execute_read(
        "SELECT error_category, error_signature, context, lesson_learned, ts FROM mistake_ledger WHERE task_id = ? ORDER BY ts ASC",
        (task_id,),
    )
    for m in mistakes:
        steps.append({
            "type": "mistake",
            "category": m["error_category"],
            "signature": m["error_signature"],
            "lesson": m["lesson_learned"],
            "ts": m["ts"],
        })

    steps.sort(key=lambda s: s.get("ts") or 0)

    # Artifact info (prioritizing .obj, .csv, .md, .py over .mtl or other companion files)
    matches = list(workspaces_dir.glob(f"{task_id}.*"))
    if not matches and repo_workspaces_dir.exists():
        matches = list(repo_workspaces_dir.glob(f"{task_id}.*"))
    artifact_url = None
    artifact_filename = None
    if matches:
        def art_priority(p: Path):
            s = p.suffix.lower()
            if s == '.obj': return 0
            if s in ['.csv', '.md', '.py', '.txt']: return 1
            return 2
        art = sorted(matches, key=lambda p: (art_priority(p), -p.stat().st_mtime))[0]
        artifact_filename = art.name
        artifact_url = f"/workspaces/{art.name}"

    return {
        "task_id": task_id,
        "title": task_dict.get("title"),
        "state": task_dict.get("state"),
        "attempt_count": task_dict.get("attempt_count"),
        "max_attempts": task_dict.get("max_attempts"),
        "created_at": task_dict.get("created_at"),
        "updated_at": task_dict.get("updated_at"),
        "failure_reason": task_dict.get("failure_reason"),
        "artifact_filename": artifact_filename,
        "artifact_url": artifact_url,
        "steps": steps,
    }


@app.post("/api/tasks/{task_id}/cancel")
def cancel_task_endpoint(task_id: str):
    logger.info("Cancellation requested for task '%s' (AT-B-05)", task_id)
    # Signal cancellation event
    evt = active_cancellation_tokens.get(task_id)
    if evt:
        evt.set()

    # Terminate process tree if recorded
    pid = active_running_pids.get(task_id)
    if pid:
        try:
            p = psutil.Process(pid)
            for child in p.children(recursive=True):
                try:
                    child.kill()
                except Exception:
                    pass
            p.kill()
            logger.info("Terminated worker process PID %d for task '%s'", pid, task_id)
        except Exception as e:
            logger.debug("Process kill exception (process may have completed): %s", e)

    try:
        updated = state_machine.cancel_task(task_id, reason="Cancelled by operator (AT-B-05)")
        return {"success": True, "task_id": task_id, "state": updated.state.value}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/dag/{dag_id}/cancel")
def cancel_dag_endpoint(dag_id: str):
    logger.info("Cancellation requested for DAG '%s' (AT-B-05)", dag_id)
    dag = dag_orchestrator.cancel_dag(dag_id, reason="Pipeline cancelled by operator (AT-B-05)")

    for step in dag.get("steps", []):
        st_task_id = f"task_{dag_id}_{step['step_id']}"
        evt = active_cancellation_tokens.get(st_task_id)
        if evt:
            evt.set()
        pid = active_running_pids.get(st_task_id)
        if pid:
            try:
                p = psutil.Process(pid)
                for child in p.children(recursive=True):
                    try:
                        child.kill()
                    except Exception:
                        pass
                p.kill()
            except Exception:
                pass
        try:
            state_machine.cancel_task(st_task_id, reason="DAG cancelled by operator")
        except Exception:
            pass

    return {"success": True, "dag_id": dag_id, "state": dag.get("state")}


@app.get("/api/mistakes")
def list_mistakes():
    rows = db.execute_read("SELECT * FROM mistake_ledger ORDER BY ts DESC LIMIT 50")
    return [dict(r) for r in rows]


@app.get("/api/skills")
def list_skills():
    return skill_bank.list_skills()


@app.get("/api/skills/search")
def search_skills(q: str, domain: str | None = None, limit: int = 5):
    return skill_bank.find_relevant_skills(q, domain=domain, limit=limit)


@app.get("/api/skills/{skill_name}")
def get_skill_details(skill_name: str):
    s = skill_bank.get_skill(skill_name)
    if not s:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")
    return s


@app.post("/api/skills/execute")
def api_execute_skill(req: ExecuteSkillRequest):
    try:
        res = skill_bank.execute_skill(req.skill_name, req.params)
        return {"success": True, "skill_name": req.skill_name, "result": res}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


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


# ---------------------------------------------------------------------------
# Blender Material & Modifier API  (v0.3.1)
# ---------------------------------------------------------------------------

class BlenderModifyRequest(BaseModel):
    artifact_obj_path: str
    action: str  # 'set_color' | 'add_modifier' | 'apply_modifiers' | 'list_objects'
    # set_color params
    hex_color: str = "#7ec8e3"
    metalness: float = 0.1
    roughness: float = 0.4
    emission_strength: float = 0.0
    # add_modifier params
    modifier_type: str = "subdivision"
    strength: float = 1.0
    # common
    object_name: str = ""
    output_obj_path: str = ""
    timeout_sec: float = 90.0


@app.post("/api/blender/modify")
def blender_modify(req: BlenderModifyRequest):
    """Apply material colors or modifiers to an existing OBJ artifact via Blender headless."""
    action = req.action.lower()
    
    # Dynamically resolve artifact path (supports basename, relative path, or absolute path)
    resolved_file = find_artifact_file(req.artifact_obj_path)
    target_path = str(resolved_file.resolve()) if resolved_file else req.artifact_obj_path
    output_path = req.output_obj_path or target_path

    if action == "list_objects":
        result = tool_registry.execute_tool("blender_list_scene_objects", {
            "artifact_obj_path": target_path,
        })
        return {"action": "list_objects", "result": result}

    elif action == "set_color":
        result = tool_registry.execute_tool("blender_set_material_color", {
            "artifact_obj_path": target_path,
            "hex_color": req.hex_color,
            "metalness": req.metalness,
            "roughness": req.roughness,
            "emission_strength": req.emission_strength,
            "object_name": req.object_name,
            "output_obj_path": output_path,
            "timeout_sec": req.timeout_sec,
        })
        return {
            "action": "set_color",
            "hex_color": req.hex_color,
            "artifact_obj_path": output_path,
            "result": result,
        }

    elif action == "add_modifier":
        result = tool_registry.execute_tool("blender_add_modifier", {
            "artifact_obj_path": target_path,
            "modifier_type": req.modifier_type,
            "strength": req.strength,
            "object_name": req.object_name,
            "output_obj_path": output_path,
            "timeout_sec": req.timeout_sec,
        })
        return {
            "action": "add_modifier",
            "modifier_type": req.modifier_type,
            "artifact_obj_path": output_path,
            "result": result,
        }

    elif action == "apply_modifiers":
        result = tool_registry.execute_tool("blender_apply_modifiers", {
            "artifact_obj_path": target_path,
            "output_obj_path": output_path,
            "timeout_sec": req.timeout_sec,
        })
        return {
            "action": "apply_modifiers",
            "artifact_obj_path": output_path,
            "result": result,
        }

    else:
        return {"error": f"Unknown action '{action}'. Use: set_color | add_modifier | apply_modifiers | list_objects"}


def execute_domain_step(
    task_id: str,
    goal: str,
    domain: str,
    effective_agent: str,
    selected_model: str,
    max_attempts: int = 3,
    predecessor_artifacts: dict[str, str] | None = None,
    launch_gui: bool = False,
) -> dict[str, Any]:
    cancel_evt = threading.Event()
    active_cancellation_tokens[task_id] = cancel_evt
    broadcaster.emit("task_state", {
        "task_id": task_id,
        "state": "Running",
        "goal": goal,
        "domain": domain,
        "agent": effective_agent,
    }, task_id=task_id)

    lower_goal = goal.lower()
    if domain == "3d":
        ext = "obj"
        min_sz = 100
    elif domain == "data":
        ext = "csv"
        min_sz = 15
    elif domain == "code":
        ext = "py"
        min_sz = 15
    else:
        domain = "report"
        ext = "md"
        min_sz = 20

    expected_artifact = workspaces_dir / f"{task_id}.{ext}"

    # Assemble contextual inputs from upstream pipeline steps if running in a DAG
    pred_context = format_predecessor_artifacts(predecessor_artifacts or {})
    attempt_history: list[dict[str, Any]] = []

    def worker_executor(g: str, attempt_num: int, anti_patterns: str):
        if cancel_evt.is_set():
            raise InterruptedError(f"Task '{task_id}' was cancelled by operator.")

        active_attempt = state_machine.db.execute_one(
            "SELECT id, lease_token FROM attempts WHERE task_id = ? AND status = 'Active'",
            (task_id,),
        )
        att_id = active_attempt["id"] if active_attempt else f"att_{task_id}_{attempt_num}"
        lease = active_attempt["lease_token"] if active_attempt else state_machine.leases.get_active_lease()

        def run_tool_fenced(tool_name: str, params: dict):
            if cancel_evt.is_set():
                raise InterruptedError(f"Task '{task_id}' was cancelled by operator.")
            broadcaster.emit("tool_call", {"tool_name": tool_name, "params": params}, task_id=task_id)
            if config.isolation.use_appcontainer and appcontainer_host:
                logger.info("Executing tool '%s' under AppContainer isolation fence for agent '%s'", tool_name, effective_agent)
            call_res = broker.dispatch_call(
                attempt_id=att_id,
                lease_token=lease,
                tool_name=tool_name,
                params=params,
                context={
                    "agent_id": effective_agent,
                    "allow_irreversible": config.policy.allow_irreversible,
                    "enable_hitl": True,
                    "appcontainer_host": appcontainer_host,
                },
            )

            # Interactive Human-In-The-Loop Checkpoint (Pillar 2)
            if call_res.get("status") == "REQUIRES_APPROVAL":
                approval_id = f"appr_{uuid.uuid4().hex[:8]}"
                appr_evt = threading.Event()
                appr_rec = {
                    "approval_id": approval_id,
                    "task_id": task_id,
                    "attempt_id": att_id,
                    "lease_token": lease,
                    "tool_name": tool_name,
                    "params": params,
                    "reason": call_res.get("error", f"Irreversible tool '{tool_name}' requires explicit operator clearance"),
                    "event": appr_evt,
                    "decision": None,
                    "operator": None,
                    "created_at": time.time(),
                }
                pending_approvals[approval_id] = appr_rec
                try:
                    state_machine.transition_to_approval(
                        task_id, att_id, lease,
                        pending_action={"approval_id": approval_id, "tool_name": tool_name, "params": params},
                        reason=appr_rec["reason"],
                    )
                except Exception as e:
                    logger.warning("Could not transition to WaitingForApproval state: %s", e)

                broadcaster.emit("hitl_requested", {
                    "approval_id": approval_id,
                    "task_id": task_id,
                    "tool_name": tool_name,
                    "params": params,
                    "reason": appr_rec["reason"],
                }, task_id=task_id)

                # Await operator approval or task cancellation
                waited = 0.0
                while waited < 300.0:
                    if cancel_evt.is_set():
                        appr_rec["decision"] = "DENIED"
                        break
                    if appr_evt.wait(timeout=1.0):
                        break
                    waited += 1.0

                pending_approvals.pop(approval_id, None)

                if appr_rec.get("decision") == "APPROVED":
                    try:
                        state_machine.transition_from_approval(
                            task_id, att_id, lease,
                            approved=True,
                            operator=appr_rec.get("operator", "Operator"),
                            reason="Operator granted irreversible execution clearance",
                        )
                    except Exception as e:
                        logger.warning("State machine transition_from_approval error: %s", e)

                    broadcaster.emit("hitl_resolved", {"approval_id": approval_id, "approved": True}, task_id=task_id)
                    call_res = broker.dispatch_call(
                        attempt_id=att_id,
                        lease_token=lease,
                        tool_name=tool_name,
                        params=params,
                        context={"agent_id": effective_agent, "allow_irreversible": True, "appcontainer_host": appcontainer_host},
                    )
                else:
                    try:
                        state_machine.transition_from_approval(
                            task_id, att_id, lease,
                            approved=False,
                            operator=appr_rec.get("operator", "Operator"),
                            reason="Operator denied irreversible tool invocation",
                        )
                    except Exception as e:
                        logger.warning("State machine transition_from_approval error: %s", e)

                    broadcaster.emit("hitl_resolved", {"approval_id": approval_id, "approved": False}, task_id=task_id)
                    raise PermissionError(f"Operator Denied Tool '{tool_name}' for Agent '{effective_agent}'")

            if not call_res.get("allowed", False):
                broadcaster.emit("tool_error", {"tool_name": tool_name, "error": call_res.get("error")}, task_id=task_id)
                raise PermissionError(f"PDP Denied Tool '{tool_name}' for Agent '{effective_agent}': {call_res.get('error')}")

            broadcaster.emit("tool_result", {"tool_name": tool_name, "status": call_res.get("status")}, task_id=task_id)
            return call_res.get("result", {})

        if domain == "3d":
            logger.info("Executing 3D synthesis via Progressive LoD Decomposer (%s) attempt %d/%d", selected_model, attempt_num, max_attempts)
            gw = LLMGateway(endpoint=config.llm.endpoint, default_model=selected_model)
            decomposer = ProgressiveLoDDecomposer(llm_gateway=gw)

            try:
                blueprint = decomposer.decompose(
                    goal=goal,
                    anti_patterns=anti_patterns,
                    model=selected_model,
                )
                blender_script = compile_blueprint_to_bpy(blueprint, str(expected_artifact))

                # Save blueprint json alongside the artifact for UI inspection
                bp_json_path = expected_artifact.with_suffix(".json")
                try:
                    bp_json_path.write_text(blueprint.to_json(indent=2), encoding="utf-8")
                except Exception:
                    pass
            except Exception as e:
                logger.error("Progressive LoD Decomposition failed (%s); invoking procedural fallback", e)
                rel_skills = skill_bank.find_relevant_skills(goal, domain="3d", limit=3)
                prev_code = attempt_history[-1]["script"] if attempt_history else None
                prev_error = attempt_history[-1]["error"] if attempt_history else None
                blender_script = synthesize_blender_script(
                    goal=goal,
                    output_obj_path=str(expected_artifact),
                    anti_patterns=anti_patterns,
                    use_llm=True,
                    model=selected_model,
                    relevant_skills=rel_skills,
                    attempt_num=attempt_num,
                    max_attempts=max_attempts,
                    previous_code=prev_code,
                    error_feedback=prev_error,
                )
            preflight = PreFlightLinter.sanitize(blender_script, domain="3d")
            if preflight.fatal_error:
                logger.warning("PreFlightLinter fatal error in 3D script (%s) on attempt %d/%d.", preflight.fatal_error, attempt_num, max_attempts)
                blender_script = preflight.code
            else:
                blender_script = preflight.code
                if preflight.applied_fixes:
                    logger.info("PreFlightLinter sanitized 3D script: %s", preflight.applied_fixes)

            res = run_tool_fenced("blender_run_python", {
                "script_code": blender_script,
                "output_obj_path": str(expected_artifact),
            })

            # Record attempt outcome to history for reflective debugging on subsequent attempt
            if res.get("exit_code") != 0 or not expected_artifact.exists() or expected_artifact.stat().st_size < 100:
                err_detail = res.get("stderr") or res.get("stdout") or "Exported OBJ file was missing or degenerate (0 vertices)"
                logger.warning("Blender execution failed (exit %s) or artifact degenerate on attempt %d/%d: %s", res.get("exit_code"), attempt_num, max_attempts, err_detail[:200])
                attempt_history.append({
                    "attempt_num": attempt_num,
                    "script": blender_script,
                    "error": err_detail,
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
            rel_skills = skill_bank.find_relevant_skills(goal, domain="data", limit=3)
            skill_context = ""
            if rel_skills:
                skill_lines = [
                    f"• `{s.get('name')}`: {s.get('description')} (Module: skills/{s.get('name')}/tool.py)"
                    for s in rel_skills
                ]
                skill_context = (
                    "\n\n[COMPOUND SKILL BANK - REUSABLE DATA GENERATORS]:\n"
                    "Sentinel has previously verified these tabular generation skills:\n"
                    + "\n".join(skill_lines) + "\n"
                    "You can reference their generator patterns or structure where applicable."
                )

            prompt_data = f"Goal: {goal}\nTarget Output CSV Path: '{out_path_str}'{pred_context}{skill_context}"
            if anti_patterns:
                prompt_data += f"\n[PREVIOUS ATTEMPT FAILED]:\n{anti_patterns}\nEnsure the CSV file is written to '{out_path_str}' with valid header and rows."

            raw_code = gw.generate(prompt=prompt_data, system=sys_inst, model=selected_model)
            py_code = gw.extract_python_code(raw_code)
            preflight = PreFlightLinter.sanitize(py_code, domain="code")
            py_code = preflight.code

            res = run_tool_fenced("python_sandbox_run", {
                "script_code": py_code,
                "output_artifact_path": str(expected_artifact),
            })
            if not expected_artifact.exists() and res.get("stdout") and "," in res.get("stdout"):
                expected_artifact.write_text(res["stdout"].strip(), encoding="utf-8")

            return {"tool_result": res, "artifact_path": str(expected_artifact), "synthesized_code": py_code}
        elif domain == "code":
            logger.info("Executing Code synthesis via LLM (%s) attempt %d", selected_model, attempt_num)
            gw = LLMGateway(endpoint=config.llm.endpoint, default_model=selected_model)
            scaffolding_lvl = ScaffoldingLevel.LEVEL_3_ADAPTIVE if anti_patterns else ScaffoldingLevel.LEVEL_2_GUARDED
            sys_inst = PromptScaffolder.build_system_prompt("code", level=scaffolding_lvl)
            rel_skills = skill_bank.find_relevant_skills(goal, domain="code", limit=3)
            prompt_code = PromptScaffolder.build_user_prompt(
                goal=goal,
                domain="code",
                artifact_path=str(expected_artifact),
                anti_patterns=anti_patterns,
                level=scaffolding_lvl,
                relevant_skills=rel_skills,
            ) + pred_context

            raw_code = gw.generate(prompt=prompt_code, system=sys_inst, model=selected_model)
            py_code = gw.extract_python_code(raw_code)
            preflight = PreFlightLinter.sanitize(py_code, domain="code")
            py_code = preflight.code
            if preflight.applied_fixes:
                logger.info("PreFlightLinter sanitized Python code: %s", preflight.applied_fixes)

            expected_artifact.write_text(py_code, encoding="utf-8")
            return {"tool_result": {"exit_code": 0, "stdout": "Code generated successfully"}, "artifact_path": str(expected_artifact), "synthesized_code": py_code}
        else:
            logger.info("Executing Autonomous ReAct Investigation loop via LLM (%s) attempt %d", selected_model, attempt_num)
            gw = LLMGateway(endpoint=config.llm.endpoint, default_model=selected_model)
            react_ctrl = ReActController(broker=broker, llm_gateway=gw, max_turns=6)
            goal_with_pred = goal + (f"\n\n{pred_context}" if pred_context else "")
            if anti_patterns:
                goal_with_pred += f"\n\n[PREVIOUS DEFECT TO AVOID]:\n{anti_patterns}"

            react_res = react_ctrl.run_react_loop(
                task_id=task_id,
                attempt_id=att_id,
                lease_token=lease,
                goal=goal_with_pred,
                agent_id=effective_agent,
                output_artifact_path=str(expected_artifact),
                model=selected_model,
                cancel_event=cancel_evt,
            )
            return {
                "tool_result": {
                    "exit_code": 0 if react_res.success else 1,
                    "stdout": f"ReAct investigation completed in {react_res.turns_taken} turn(s)",
                },
                "artifact_path": str(expected_artifact),
                "react_trajectory": [s.to_dict() for s in react_res.trajectory],
            }

    def verifier(output: dict) -> VerificationResult:
        p = Path(output.get("artifact_path", ""))
        if domain == "3d":
            v_res = verification_gate.verify_obj_geometry(p, min_vertices=20, min_faces=10)
            if not v_res.passed:
                return v_res
            # Deep empirical evaluation via sensor rig & vision critic
            try:
                insp = blender_sensor_rig.inspect_model(p)
                if insp.is_degenerate:
                    return VerificationResult(
                        passed=False,
                        error_category="DEGENERATE_3D_GEOMETRY",
                        error_signature=f"DegenerateGeometry: {insp.degenerate_reason}",
                        details={"inspection": insp.metrics},
                        lesson=f"The 3D model failed physical topology inspection: {insp.degenerate_reason}. Build a multi-part assembly with articulated components.",
                    )
                card = harsh_critic.evaluate_3d_model(goal, insp)
                if not card.passed:
                    return VerificationResult(
                        passed=False,
                        error_category="CRITIC_REJECTED",
                        error_signature=card.anti_pattern_signature or "SubStandard3DModel",
                        details={"score": card.score, "mode": card.evaluation_mode, "critique": card.critique},
                        lesson=f"Empirical Critic scored model {card.score * 100:.1f}% (threshold: {harsh_critic.passing_threshold * 100:.0f}%). {card.critique} Remediation: {card.remediation_advice}",
                    )
            except Exception as ex:
                logger.warning("Harsh Critic validation check error: %s", ex)
            return v_res
        elif domain == "code":
            expected_syms = []
            if "lru" in lower_goal:
                expected_syms = ["LRUCache", "get", "put"]
            contract_harness = ContractLibrary.get_contract_for_goal(goal)
            return verification_gate.verify_python_code(
                p,
                required_symbols=expected_syms,
                test_execution=True,
                contract_harness=contract_harness,
            )
        elif domain == "data":
            v_res = verification_gate.verify_csv_structure(p, min_rows=2, min_cols=2)
            if not v_res.passed:
                return v_res
            try:
                csv_insp = CSVSensorRig.inspect_csv(p)
                card = harsh_critic.evaluate_csv_dataset(goal, csv_insp)
                if not card.passed:
                    return VerificationResult(
                        passed=False,
                        error_category="DATA_QUALITY_REJECTED",
                        error_signature=card.anti_pattern_signature or "LowQualityCSV",
                        details={"score": card.score, "critique": card.critique},
                        lesson=f"Dataset quality scored {card.score * 100:.1f}%. {card.critique} Remediation: {card.remediation_advice}",
                    )
            except Exception as ex:
                logger.warning("Data Critic validation error: %s", ex)
            return v_res
        else:
            return verification_gate.verify_markdown_report(p, min_words=25)

    try:
        gw = LLMGateway(endpoint=config.llm.endpoint, default_model=selected_model)
        semantic_slug = derive_semantic_slug(goal, domain=domain)
        result = pilot.run_task(
            task_id=task_id,
            goal=goal,
            worker_executor=worker_executor,
            verifier=verifier,
            skill_distillation_name=semantic_slug,
            max_attempts=max_attempts,
            domain=domain,
            llm_gateway=gw,
            cancellation_event=cancel_evt,
        )
    finally:
        active_cancellation_tokens.pop(task_id, None)
        active_running_pids.pop(task_id, None)

    gui_info = None
    if launch_gui and expected_artifact.exists() and domain == "3d":
        try:
            gui_info = tool_registry.execute_tool("blender_launch_gui", {"file_to_open": str(expected_artifact)})
        except Exception as e:
            gui_info = {"error": str(e)}

    broadcaster.emit("task_state", {
        "task_id": result.task.id,
        "state": result.task.state.value,
        "success": result.success,
        "attempts_taken": result.attempts_taken,
        "artifact_path": str(expected_artifact) if expected_artifact.exists() else None,
    }, task_id=result.task.id)

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
        "synthesized_code": result.synthesized_code,
    }


# --- Sentinel Autonomous Gymnasium Setup (Closed-Loop Empirical Self-Evolution) ---

curriculum_gen = CurriculumGenerator(
    skill_bank=skill_bank,
    mistake_memory=mistake_memory,
    llm_gateway=LLMGateway(endpoint=config.llm.endpoint, default_model=config.llm.model),
)
auto_refiner = AutoRefiner(
    skill_bank=skill_bank,
    mistake_memory=mistake_memory,
    tool_registry=tool_registry,
)


def gym_task_executor(task_id: str, goal: str, domain: str) -> dict[str, Any]:
    return execute_domain_step(
        task_id=task_id,
        goal=goal,
        domain=domain,
        effective_agent="blender_artisan" if domain == "3d" else "data_analyst",
        selected_model=config.llm.model,
        max_attempts=2,
        launch_gui=False,
    )


gym_daemon = GymnasiumDaemon(
    sensor_rig=blender_sensor_rig,
    critic=harsh_critic,
    curriculum=curriculum_gen,
    auto_refiner=auto_refiner,
    task_executor_fn=gym_task_executor,
    workspaces_dir=workspaces_dir,
    inter_cycle_delay_sec=3.0,
)


class GymStartRequest(BaseModel):
    max_hours: float = 5.0
    domain: str = "3d"


@app.post("/api/gym/start")
def start_gymnasium(req: GymStartRequest | None = None):
    """Starts the 5-hour autonomous self-evolution training loop."""
    hrs = req.max_hours if req else 5.0
    if gym_daemon.is_running:
        return {"status": "ALREADY_RUNNING", "gym": gym_daemon.get_status()}
    gym_daemon.start(max_duration_hours=hrs)
    return {"status": "STARTED", "gym": gym_daemon.get_status()}


@app.post("/api/gym/stop")
def stop_gymnasium():
    """Stops the autonomous self-evolution training loop on operator command."""
    gym_daemon.stop()
    return {"status": "STOPPING", "gym": gym_daemon.get_status()}


@app.get("/api/gym/status")
def get_gymnasium_status():
    """Returns real-time telemetry, completed cycle scores, and snapshot paths from the Gymnasium."""
    return gym_daemon.get_status()


@app.post("/api/tasks/dispatch")
def dispatch_task(req: TaskDispatchRequest):
    """Dispatches any custom user task across 3D, data, code, or report domains."""
    task_id = f"task_{int(time.time())}"
    goal = req.goal.strip()
    max_att = req.max_attempts or config.iteration_limits.max_attempts
    selected_model = req.model or config.llm.model
    lower_goal = goal.lower()

    effective_agent = req.agent_id
    domain = req.domain
    manifest = agent_registry.get_manifest(effective_agent) if effective_agent and effective_agent != "auto" else None
    if not manifest:
        effective_agent = None

    if not domain and manifest and manifest.capabilities:
        cap = manifest.capabilities[0]
        if "3d" in cap:
            domain = "3d"
        elif "data" in cap:
            domain = "data"
        elif "code" in cap:
            domain = "code"
        elif "report" in cap or "analysis" in cap:
            domain = "report"

    # Infer domain with word boundaries to avoid substring collision (e.g. 'ring' in 'bearing')
    if not domain:
        import re
        words_3d = [
            "3d", "blender", "model", "sword", "mug", "spaceship", "tree", "chair", "monkey", "mesh",
            "build", "turret", "gatling", "cylinder", "cube", "sphere", "torus", "geometry", "sculpture",
            "gun", "barrel", "mount", "bracket", "pillar", "shaft", "car", "robot", "cannon", "shield",
            "armor", "helmet", "ring", "table", "lamp", "building", "castle", "plane", "rifle", "dagger",
            "warhammer", "gear", "gimbal", "nozzle", "telescope", "gripper"
        ]
        words_data = ["csv", "table", "dataset", "dataframe", "rows", "columns", "spreadsheet", "sales", "telemetry"]
        words_code = ["code", "python script", "function", "class", "algorithm", "program", "script", "write code"]

        is_data_goal = any(re.search(rf"\b{re.escape(w)}\b", lower_goal) for w in words_data)
        is_3d_goal = any(re.search(rf"\b{re.escape(w)}\b", lower_goal) for w in words_3d)

        if is_data_goal and not any(re.search(rf"\b{re.escape(w)}\b", lower_goal) for w in ["3d", "blender", "obj"]):
            domain = "data"
        elif is_3d_goal:
            domain = "3d"
        elif any(re.search(rf"\b{re.escape(w)}\b", lower_goal) for w in words_code):
            domain = "code"
        else:
            domain = "report"

    if not effective_agent or effective_agent == "auto":
        if domain == "3d":
            effective_agent = "blender_artisan"
        elif domain == "data":
            effective_agent = "data_analyst"
        elif domain == "code":
            effective_agent = "code_engineer"
        else:
            effective_agent = "systems_reporter"

    return execute_domain_step(
        task_id=task_id,
        goal=goal,
        domain=domain,
        effective_agent=effective_agent,
        selected_model=selected_model,
        max_attempts=max_att,
        launch_gui=req.launch_gui,
    )


def dag_step_executor(step: dict[str, Any], predecessor_artifacts: dict[str, str]) -> dict[str, Any]:
    step_task_id = f"task_{step['dag_id']}_{step['step_id']}"
    res = execute_domain_step(
        task_id=step_task_id,
        goal=step["goal"],
        domain=step.get("domain", "report"),
        effective_agent=step.get("agent_id", "data_analyst"),
        selected_model=config.llm.model,
        max_attempts=config.iteration_limits.max_attempts,
        predecessor_artifacts=predecessor_artifacts,
        launch_gui=False,
    )
    return {
        "success": res.get("success", False),
        "task_id": res.get("task_id"),
        "artifact_path": res.get("artifact_path"),
        "error": "Step verification failed or retries exhausted" if not res.get("success") else None,
    }


@app.get("/api/dag/runs")
def list_dag_runs():
    return dag_orchestrator.list_dags()


@app.get("/api/dag/templates")
def get_dag_templates():
    return dag_orchestrator.get_pipeline_templates()


@app.get("/api/dag/{dag_id}")
def get_dag_run(dag_id: str):
    dag = dag_orchestrator.get_dag(dag_id)
    if not dag:
        raise HTTPException(status_code=404, detail=f"DAG '{dag_id}' not found")
    # Enrich steps with artifact metadata and URLs for frontend viewports
    for step in dag.get("steps", []):
        art_path = step.get("output_artifact")
        if art_path:
            found = find_artifact_file(art_path)
            p = found or Path(art_path)
            step["artifact_filename"] = p.name
            step["artifact_url"] = f"/workspaces/{p.name}"
            step["artifact_exists"] = p.is_file()
            if p.is_file():
                step["artifact_size"] = p.stat().st_size
    return dag


@app.post("/api/dag/plan")
def plan_dag(req: DAGPlanRequest):
    try:
        gw = LLMGateway(endpoint=config.llm.endpoint, default_model=req.model or config.llm.model)
        name, desc, step_defs = DAGPlanner.decompose_goal(req.goal, gateway=gw, model=req.model or config.llm.model)
        return {
            "success": True,
            "pipeline_name": name,
            "pipeline_description": desc,
            "steps": [s.to_dict() for s in step_defs],
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"DAG Planning Failed: {e}")


@app.post("/api/dag/dispatch")
def dispatch_dag(req: DAGDispatchRequest):
    try:
        if req.template:
            dag_id = dag_orchestrator.instantiate_template(req.template)
        elif req.goal:
            gw = LLMGateway(endpoint=config.llm.endpoint, default_model=req.model or config.llm.model)
            name, desc, step_defs = DAGPlanner.decompose_goal(req.goal, gateway=gw, model=req.model or config.llm.model)
            dag_id = dag_orchestrator.create_dag(
                name=req.name or name,
                description=req.description or desc,
                steps=step_defs,
            )
        elif req.steps:
            step_defs = [
                DAGStepDefinition(
                    step_id=s["step_id"],
                    goal=s["goal"],
                    agent_id=s["agent_id"],
                    domain=s["domain"],
                    dependencies=s.get("dependencies", []),
                )
                for s in req.steps
            ]
            dag_id = dag_orchestrator.create_dag(
                name=req.name or "Custom Pipeline",
                description=req.description or "Operator defined pipeline",
                steps=step_defs,
            )
        else:
            raise HTTPException(status_code=400, detail="Must provide 'template', 'goal', or 'steps'.")

        def run_in_bg():
            try:
                dag_orchestrator.execute_dag(dag_id, dag_step_executor, concurrent=req.concurrent)
            except Exception as e:
                logger.exception("DAG background execution encountered error: %s", e)

        threading.Thread(target=run_in_bg, daemon=True).start()
        return dag_orchestrator.get_dag_status(dag_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/agent/react")
def run_agent_react(req: AgentReActRequest):
    """Executes a live multi-turn ReAct reasoning loop with monotonic lease fencing."""
    try:
        task_id = f"react_{int(time.time())}"
        state_machine.create_task(task_id, title=req.goal, max_attempts=1)
        task, lease_rec = state_machine.start_next_attempt(task_id)
        gw = LLMGateway(endpoint=config.llm.endpoint, default_model=req.model or config.llm.model)
        react_ctrl = ReActController(broker=broker, llm_gateway=gw, max_turns=req.max_turns)
        out_art = workspaces_dir / f"{task_id}.md"
        res = react_ctrl.run_react_loop(
            task_id=task_id,
            attempt_id=lease_rec.attempt_id,
            lease_token=lease_rec.lease_token,
            goal=req.goal,
            agent_id=req.agent_id,
            output_artifact_path=str(out_art),
            model=req.model or config.llm.model,
        )
        if res.success:
            state_machine.transition_to_verifying(task_id, lease_rec.attempt_id, lease_rec.lease_token)
            state_machine.commit_success(task_id, lease_rec.attempt_id, lease_rec.lease_token)
        else:
            state_machine.handle_verification_failure(task_id, lease_rec.attempt_id, lease_rec.lease_token, res.error or "ReAct loop failed")
        return res.to_dict()
    except Exception as e:
        logger.exception("ReAct endpoint error: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


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
          <option value="qwen2.5-coder:14b" selected>🧠 Qwen 2.5 Coder (14B) [Active]</option>
          <option value="qwen3:14b-q4_K_M">🧠 Qwen 3 (14B Q4)</option>
          <option value="qwen3.5:9b">🧠 Qwen 3.5 (9B)</option>
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
      <button onclick="switchTab('tab-dag')" class="tab-btn pb-2 hover:text-slate-200" id="btn-dag">⚡ Multi-Agent Pipelines (DAG)</button>
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

    <!-- Tab: Multi-Agent Pipelines (DAG) -->
    <div id="tab-dag" class="tab-content hidden bg-slate-800/60 border border-slate-700 rounded-xl p-5 space-y-4">
      <div class="flex items-center justify-between border-b border-slate-700/80 pb-3">
        <div>
          <h2 class="text-base font-bold text-slate-100 flex items-center gap-2">
            <span>⚡</span> Multi-Agent Choreography & Pipelines (DAG)
          </h2>
          <p class="text-xs text-slate-400 mt-0.5">Topological multi-stage task execution across Gate A specialized agents with automated artifact piping.</p>
        </div>
        <div class="flex items-center gap-2">
          <button onclick="launchAnalyticsPipeline()" id="btn-launch-pipeline" class="px-3.5 py-1.5 bg-gradient-to-r from-sky-600 to-indigo-600 hover:from-sky-500 hover:to-indigo-500 text-xs font-bold text-white rounded-lg transition flex items-center gap-1.5 shadow-md">
            <span>🚀</span> Launch 3-Agent Analytics Pipeline
          </button>
        </div>
      </div>

      <!-- Live Pipeline Execution Banner -->
      <div id="dag-live-banner" class="hidden bg-slate-950/80 border border-indigo-500/40 rounded-lg p-3 text-xs space-y-1">
        <div class="flex items-center justify-between">
          <span id="dag-live-title" class="font-bold text-indigo-400">⏳ Pipeline Running...</span>
          <div class="flex items-center gap-2">
            <span id="dag-live-badge" class="px-2 py-0.5 text-[10px] font-semibold rounded bg-indigo-500/20 text-indigo-400 border border-indigo-500/30">RUNNING</span>
            <button id="btn-cancel-dag" onclick="cancelCurrentDAG()" class="px-2.5 py-1 bg-rose-600/30 hover:bg-rose-600 text-rose-300 hover:text-white rounded border border-rose-500/40 text-[10px] font-bold transition">⏹ Cancel Pipeline</button>
          </div>
        </div>
        <p id="dag-live-detail" class="text-slate-300 text-[11px]">Choreographing agents across pipeline steps...</p>
      </div>

      <!-- DAG Runs Container -->
      <div id="dag-runs-container" class="space-y-4 pt-1">
        <p class="text-xs text-slate-500">Loading pipeline runs...</p>
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
    <div id="tab-skills" class="tab-content hidden bg-slate-800/60 border border-slate-700 rounded-xl p-5 space-y-4">
      <div class="flex flex-wrap items-center justify-between gap-3 border-b border-slate-700/80 pb-3">
        <div>
          <h2 class="text-base font-bold text-slate-100 flex items-center gap-2">
            <span>🧠</span> Reusable Compound Skill Bank
          </h2>
          <p class="text-xs text-slate-400">Synthesized verified capabilities dynamically discoverable and invocable by agents.</p>
        </div>
        <div class="flex items-center gap-2">
          <div class="relative">
            <input type="text" id="skill-search-input" oninput="filterSkillsUI()" placeholder="Search skills by keyword..." 
                   class="bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 pl-8 text-xs text-slate-100 placeholder-slate-500 focus:border-purple-500 outline-none w-64 shadow-inner">
            <span class="absolute left-2.5 top-2 text-xs text-slate-500">🔍</span>
          </div>
          <select id="skill-domain-filter" onchange="filterSkillsUI()" class="bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 focus:border-purple-500 outline-none">
            <option value="all">All Domains</option>
            <option value="code">Python Code</option>
            <option value="3d">3D Blender</option>
            <option value="data">Data CSV</option>
            <option value="report">Markdown Report</option>
          </select>
        </div>
      </div>
      <div id="skills-container" class="grid grid-cols-1 md:grid-cols-2 gap-3.5 pt-1">
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
            <label class="flex items-center gap-2 cursor-pointer text-slate-300">
              <input type="checkbox" value="broker_http_get" checked class="organ-checkbox rounded bg-slate-900 border-slate-700 text-emerald-500">
              <span>broker_http_get</span>
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
      if (tabId === 'tab-dag') loadDAGRuns();
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
                           t.state === 'Cancelled' ? 'bg-amber-500/20 text-amber-400 border-amber-500/30' :
                           'bg-sky-500/20 text-sky-400 border-sky-500/30 animate-pulse';
        const isCancellable = ['Running', 'Queued', 'Verifying'].includes(t.state);
        const cancelBtn = isCancellable
          ? `<button onclick="cancelTask('${t.id}')" title="Cancel execution and revoke leases" class="ml-2 px-2 py-0.5 bg-rose-600/30 hover:bg-rose-600 border border-rose-500/40 text-rose-300 hover:text-white rounded text-[10px] font-bold transition">⏹ Cancel</button>`
          : '';

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
            <td class="p-2.5">
              <span class="px-2 py-0.5 border rounded-full text-[10px] font-semibold ${badgeColor}">${t.state}</span>
              ${cancelBtn}
            </td>
            <td class="p-2.5 text-slate-400">${t.attempt_count} / ${t.max_attempts}</td>
            <td class="p-2.5 text-slate-400">${artLink}</td>
          </tr>
        `;
      }).join('');
    }

    async function cancelTask(taskId) {
      if (!confirm(`Cancel task '${taskId}' and revoke its leases immediately?`)) return;
      try {
        const res = await fetch(`/api/tasks/${taskId}/cancel`, { method: 'POST' });
        const data = await res.json();
        if (res.ok) {
          loadTasks();
        } else {
          alert('Failed to cancel task: ' + (data.detail || JSON.stringify(data)));
        }
      } catch (e) {
        alert('Error cancelling task: ' + e);
      }
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

    let allSkillsCache = [];

    async function loadSkills() {
      try {
        const res = await fetch('/api/skills');
        allSkillsCache = await res.json();
        renderSkills(allSkillsCache);
      } catch (e) {
        const c = document.getElementById('skills-container');
        if (c) c.innerHTML = '<p class="text-xs text-rose-400">Failed to load skills: ' + e + '</p>';
      }
    }

    function filterSkillsUI() {
      const q = (document.getElementById('skill-search-input')?.value || '').toLowerCase().trim();
      const dom = document.getElementById('skill-domain-filter')?.value || 'all';
      const filtered = allSkillsCache.filter(s => {
        let meta = {};
        try { meta = JSON.parse(s.metadata || '{}'); } catch(e){}
        const sDom = meta.domain || (s.code.includes('bpy') ? '3d' : 'code');
        const matchesDom = (dom === 'all') || (sDom === dom);
        const matchesQ = !q || s.name.toLowerCase().includes(q) || (s.description || '').toLowerCase().includes(q) || s.code.toLowerCase().includes(q);
        return matchesDom && matchesQ;
      });
      renderSkills(filtered);
    }

    function renderSkills(list) {
      const c = document.getElementById('skills-container');
      if (!c) return;
      if (!list || list.length === 0) {
        c.innerHTML = '<p class="text-xs text-slate-500 col-span-2 p-6 text-center">No skills match the query.</p>';
        return;
      }
      c.innerHTML = list.map(s => {
        let meta = {};
        try { meta = JSON.parse(s.metadata || '{}'); } catch(e){}
        const domain = meta.domain || (s.code.includes('bpy') ? '3d' : 'code');
        const domainBadge = domain === '3d' ? 'bg-sky-500/20 text-sky-400 border-sky-500/30' :
                            domain === 'data' ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' :
                            domain === 'report' ? 'bg-amber-500/20 text-amber-400 border-amber-500/30' :
                            'bg-purple-500/20 text-purple-400 border-purple-500/30';
        const domainIcon = domain === '3d' ? '🧊 3D' : domain === 'data' ? '📊 Data' : domain === 'report' ? '📝 Report' : '💻 Code';

        return `
          <div class="bg-slate-900/90 border border-purple-500/20 hover:border-purple-500/40 rounded-xl p-4 space-y-3 shadow-md flex flex-col justify-between transition">
            <div class="space-y-2">
              <div class="flex items-center justify-between gap-2">
                <div class="flex items-center gap-2">
                  <span class="px-2 py-0.5 text-[10px] font-mono font-bold rounded border ${domainBadge}">${domainIcon}</span>
                  <span class="text-purple-300 font-bold text-xs font-mono">${s.name}</span>
                </div>
                <span class="text-[10px] text-slate-400 font-mono">v${s.version}</span>
              </div>
              <p class="text-xs text-slate-300 leading-relaxed">${s.description || 'Verified reusable autonomous skill.'}</p>
              <details class="cursor-pointer">
                <summary class="text-[11px] text-slate-400 hover:text-slate-200 select-none font-mono">View Implementation Code ▾</summary>
                <pre class="mt-2 bg-slate-950 border border-slate-800 p-2.5 rounded text-[10px] font-mono text-emerald-400 overflow-x-auto max-h-40 select-text leading-relaxed">${s.code.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</pre>
              </details>
            </div>
            <div class="pt-2 border-t border-slate-800/80 flex items-center justify-between gap-2">
              <span class="text-[10px] text-slate-500 font-mono">Module: skills/${s.name}/tool.py</span>
              <button onclick="runSkillInteractive('${s.name}')" class="px-3 py-1 bg-purple-600 hover:bg-purple-500 text-white rounded text-[11px] font-semibold transition flex items-center gap-1.5 shadow">
                <span>⚡</span> Run Skill
              </button>
            </div>
          </div>
        `;
      }).join('');
    }

    async function runSkillInteractive(skillName) {
      if (!confirm(`Execute verified skill '${skillName}' in isolated broker sandbox?`)) return;
      try {
        const res = await fetch('/api/skills/execute', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ skill_name: skillName, params: {} })
        });
        const d = await res.json();
        if (res.ok) {
          const art = d.result?.artifact_path;
          let msg = `✓ Skill '${skillName}' executed successfully!`;
          if (art) {
            msg += `\\nArtifact created: ${art}`;
          }
          if (d.result?.stdout) {
            msg += `\\nOutput:\\n${d.result.stdout.slice(0, 300)}`;
          }
          alert(msg);
          loadTasks();
        } else {
          alert('Execution error: ' + (d.detail || JSON.stringify(d)));
        }
      } catch (e) {
        alert('Skill execution failed: ' + e);
      }
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
      loadDAGRuns();
      loadAgents();
      loadMistakes();
      loadSkills();
      loadTools();
    }

    let currentRunningDagId = null;

    async function cancelCurrentDAG() {
      if (!currentRunningDagId) return;
      if (!confirm(`Cancel active pipeline '${currentRunningDagId}' and drain all active steps?`)) return;
      try {
        const res = await fetch(`/api/dag/${currentRunningDagId}/cancel`, { method: 'POST' });
        const d = await res.json();
        if (res.ok) {
          document.getElementById('dag-live-title').innerText = `⏹ Pipeline Cancelled (${currentRunningDagId})`;
          document.getElementById('dag-live-badge').innerText = 'CANCELLED';
          document.getElementById('dag-live-badge').className = 'px-2 py-0.5 text-[10px] font-semibold rounded bg-amber-500/20 text-amber-400 border border-amber-500/30';
          document.getElementById('dag-live-detail').innerText = 'Pipeline was stopped by operator. Active steps drained.';
          document.getElementById('btn-cancel-dag').classList.add('hidden');
          document.getElementById('btn-launch-pipeline').disabled = false;
          document.getElementById('btn-launch-pipeline').classList.remove('opacity-50');
          loadDAGRuns();
          loadTasks();
        } else {
          alert('Failed to cancel pipeline: ' + (d.detail || JSON.stringify(d)));
        }
      } catch (e) {
        alert('Error: ' + e);
      }
    }

    async function launchAnalyticsPipeline() {
      const btn = document.getElementById('btn-launch-pipeline');
      const banner = document.getElementById('dag-live-banner');
      const title = document.getElementById('dag-live-title');
      const detail = document.getElementById('dag-live-detail');
      const badge = document.getElementById('dag-live-badge');
      const cancelBtn = document.getElementById('btn-cancel-dag');

      btn.disabled = true;
      btn.classList.add('opacity-50');
      banner.classList.remove('hidden');
      if (cancelBtn) cancelBtn.classList.remove('hidden');
      title.innerText = '🚀 Launching Analytics Pipeline...';
      badge.innerText = 'DISPATCHING';
      badge.className = 'px-2 py-0.5 text-[10px] font-semibold rounded bg-sky-500/20 text-sky-400 border border-sky-500/30';
      detail.innerText = 'Initializing 3-Agent Collaborative Workflow: Data Analyst → Code Engineer → Systems Reporter';

      try {
        const res = await fetch('/api/dag/dispatch', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ template: 'analytics' })
        });
        const data = await res.json();
        if (res.ok) {
          currentRunningDagId = data.dag_id;
          title.innerText = `⏳ Pipeline Executing (${data.dag_id})`;
          badge.innerText = 'RUNNING';
          detail.innerText = 'Agents executing topological steps with strict capability fencing & verification gates...';
          loadDAGRuns();
          const pollInterval = setInterval(async () => {
            const r = await fetch(`/api/dag/${data.dag_id}`);
            const d = await r.json();
            loadDAGRuns();
            loadTasks();
            if (d.state === 'Succeeded' || d.state === 'Failed' || d.state === 'Cancelled') {
              clearInterval(pollInterval);
              btn.disabled = false;
              btn.classList.remove('opacity-50');
              if (cancelBtn) cancelBtn.classList.add('hidden');
              if (d.state === 'Succeeded') {
                title.innerText = `✓ Pipeline Succeeded (${data.dag_id})`;
                badge.innerText = 'SUCCEEDED';
                badge.className = 'px-2 py-0.5 text-[10px] font-semibold rounded bg-emerald-500/20 text-emerald-400 border border-emerald-500/30';
                detail.innerText = 'All 3 agents successfully completed and verified their pipeline steps!';
              } else if (d.state === 'Cancelled') {
                title.innerText = `⏹ Pipeline Cancelled (${data.dag_id})`;
                badge.innerText = 'CANCELLED';
                badge.className = 'px-2 py-0.5 text-[10px] font-semibold rounded bg-amber-500/20 text-amber-400 border border-amber-500/30';
                detail.innerText = 'Pipeline was stopped by operator. Active steps drained.';
              } else {
                title.innerText = `❌ Pipeline Failed (${data.dag_id})`;
                badge.innerText = 'FAILED';
                badge.className = 'px-2 py-0.5 text-[10px] font-semibold rounded bg-rose-500/20 text-rose-400 border border-rose-500/30';
                detail.innerText = d.error || 'One or more pipeline steps failed verification.';
              }
            }
          }, 3000);
        } else {
          alert('Failed to dispatch pipeline: ' + (data.detail || JSON.stringify(data)));
          btn.disabled = false;
          btn.classList.remove('opacity-50');
          banner.classList.add('hidden');
        }
      } catch (e) {
        alert('Request failed: ' + e);
        btn.disabled = false;
        btn.classList.remove('opacity-50');
        banner.classList.add('hidden');
      }
    }

    async function loadDAGRuns() {
      const container = document.getElementById('dag-runs-container');
      if (!container) return;
      try {
        const res = await fetch('/api/dag/runs');
        const runs = await res.json();
        if (!runs.length) {
          container.innerHTML = '<p class="text-xs text-slate-500 p-4">No multi-agent pipeline runs recorded yet. Click "Launch 3-Agent Analytics Pipeline" above to run one!</p>';
          return;
        }

        const detailedRuns = await Promise.all(runs.map(async r => {
          try {
            const dRes = await fetch(`/api/dag/${r.id}`);
            return await dRes.json();
          } catch {
            return r;
          }
        }));

        container.innerHTML = detailedRuns.map(dag => {
          const stateBadge = dag.state === 'Succeeded' ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' :
                             dag.state === 'Failed' ? 'bg-rose-500/20 text-rose-400 border-rose-500/30' :
                             dag.state === 'Cancelled' ? 'bg-amber-500/20 text-amber-400 border-amber-500/30' :
                             'bg-sky-500/20 text-sky-400 border-sky-500/30 animate-pulse';
          const steps = dag.steps || [];
          const completedCount = steps.filter(s => s.state === 'Succeeded').length;
          const totalCount = steps.length || 1;
          const pct = Math.round((completedCount / totalCount) * 100);

          return `
            <div class="bg-slate-900 border border-slate-700/80 rounded-xl p-4 space-y-3.5 shadow-md">
              <div class="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-2.5">
                <div class="space-y-0.5">
                  <div class="flex items-center gap-2">
                    <span class="text-sm font-bold text-slate-100">${dag.name}</span>
                    <span class="px-2 py-0.5 text-[10px] font-bold font-mono rounded border ${stateBadge}">${dag.state.toUpperCase()}</span>
                  </div>
                  <p class="text-[11px] text-slate-400">${dag.description || ''}</p>
                </div>
                <div class="text-right text-[11px] font-mono text-slate-400">
                  <span>ID: <span class="text-slate-300">${dag.id}</span></span>
                  <div class="text-[10px] text-slate-500">${new Date(dag.created_at * 1000).toLocaleTimeString()}</div>
                </div>
              </div>

              <!-- Progress bar -->
              <div class="space-y-1">
                <div class="flex justify-between text-[10px] font-mono text-slate-400">
                  <span>Pipeline Progress: ${completedCount}/${totalCount} Steps Completed</span>
                  <span class="font-bold text-sky-400">${pct}%</span>
                </div>
                <div class="w-full bg-slate-950 h-1.5 rounded-full overflow-hidden border border-slate-800">
                  <div class="bg-gradient-to-r from-sky-500 to-emerald-500 h-full transition-all duration-500" style="width: ${pct}%"></div>
                </div>
              </div>

              <!-- Step Pipeline Flow -->
              <div class="grid grid-cols-1 md:grid-cols-${Math.min(steps.length, 3)} gap-3 pt-1">
                ${steps.map((st, idx) => {
                  const sBadge = st.state === 'Succeeded' ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' :
                                 st.state === 'Running' ? 'bg-sky-500/20 text-sky-400 border-sky-500/30 animate-pulse' :
                                 st.state === 'Failed' ? 'bg-rose-500/20 text-rose-400 border-rose-500/30' :
                                 st.state === 'Cancelled' ? 'bg-amber-500/20 text-amber-400 border-amber-500/30' :
                                 st.state === 'Skipped' ? 'bg-slate-800 text-slate-500 border-slate-700' :
                                 'bg-slate-800/60 text-slate-400 border-slate-700';
                  const domainIcon = st.domain === 'data' ? '📊' : st.domain === 'code' ? '💻' : st.domain === '3d' ? '🧊' : '📝';
                  let artBtn = '';
                  if (st.output_artifact) {
                    const artName = st.output_artifact.split(/[\\\\/]/).pop();
                    const artExt = artName.split('.').pop().toUpperCase();
                    artBtn = `
                      <button onclick="previewArtifact('${artName}', '/workspaces/${artName}', '${artExt}')"
                              class="mt-2 w-full py-1 px-2 bg-slate-800 hover:bg-slate-700 border border-slate-700 hover:border-slate-600 rounded text-[10px] font-mono text-sky-300 flex items-center justify-center gap-1.5 transition">
                        <span>👁️</span> Inspect ${artName}
                      </button>
                    `;
                  }
                  return `
                    <div class="bg-slate-950/70 border border-slate-800 rounded-lg p-3 flex flex-col justify-between space-y-2 relative">
                      <div class="space-y-1.5">
                        <div class="flex items-center justify-between">
                          <span class="text-[10px] font-mono font-bold text-slate-400">Step ${idx + 1}</span>
                          <span class="px-1.5 py-0.5 text-[9px] font-bold font-mono rounded border ${sBadge}">${st.state}</span>
                        </div>
                        <div class="flex items-center gap-1.5 text-xs font-semibold text-slate-200">
                          <span>${domainIcon}</span>
                          <span class="truncate">${st.agent_id}</span>
                        </div>
                        <p class="text-[11px] text-slate-400 line-clamp-2 leading-relaxed" title="${st.goal}">${st.goal}</p>
                      </div>
                      ${artBtn}
                    </div>
                  `;
                }).join('')}
              </div>
            </div>
          `;
        }).join('');
      } catch (e) {
        container.innerHTML = '<p class="text-rose-400 p-4 text-xs">Failed to load DAG runs: ' + e + '</p>';
      }
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
    index_file = Path(__file__).parent / "static" / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
    rendered = DASHBOARD_HTML.replace('value="qwen3.5:9b" selected>🧠 Qwen 3.5 (9B) [Active]', f'value="{config.llm.model}" selected>🧠 {config.llm.model} [Active]')
    return HTMLResponse(content=rendered)


def start_server(host: str = "127.0.0.1", port: int = 8000):
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    start_server()
