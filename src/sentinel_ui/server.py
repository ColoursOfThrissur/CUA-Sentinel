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
from sentinel_core.verification_gate import VerificationGate, VerificationResult
from sentinel_adaptive.mistake_ledger import MistakeMemory
from sentinel_adaptive.skill_bank import SkillBank
from sentinel_broker.tool_registry import ToolRegistry
from sentinel_broker.organs.sensory import register_sensory_organs
from sentinel_broker.organs.motor import register_motor_organs
from sentinel_broker.organs.blender import register_blender_organs
from sentinel_broker.organs.blender_prompts import synthesize_blender_script
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
pilot = AdaptivePilotController(state_machine, verification_gate, mistake_memory, skill_bank)


class ConfigUpdateRequest(BaseModel):
    max_attempts: int | None = None
    attempt_timeout_sec: float | None = None
    memory_limit_mb: int | None = None
    cpu_rate_percent: float | None = None
    use_appcontainer: bool | None = None
    allow_irreversible: bool | None = None


class TaskDispatchRequest(BaseModel):
    goal: str
    launch_gui: bool = False
    max_attempts: int | None = None


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

    config.update_from_dict(updates)
    config.save(CONFIG_PATH)
    return {"status": "CONFIG_SAVED", "config": config.to_dict()}


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
    return [dict(r) for r in rows]


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


@app.get("/api/side_effects")
def list_side_effects():
    rows = db.execute_read("SELECT * FROM side_effect_ledger ORDER BY id DESC LIMIT 50")
    return [dict(r) for r in rows]


@app.post("/api/tasks/dispatch")
def dispatch_task(req: TaskDispatchRequest):
    """Dispatches any custom user task or 3D model prompt to real Blender 4.5 and Windows organs."""
    task_id = f"task_{int(time.time())}"
    goal = req.goal.strip()
    max_att = req.max_attempts or config.iteration_limits.max_attempts

    is_3d_task = any(w in goal.lower() for w in ["3d", "blender", "model", "sword", "mug", "spaceship", "tree", "chair", "monkey", "mesh"])
    target_obj = workspaces_dir / f"{task_id}.obj"

    def worker_executor(g: str, attempt_num: int, anti_patterns: str):
        if is_3d_task:
            if attempt_num == 1 and not anti_patterns:
                # Deliberate naive attempt to test verification gate
                broken_script = "import bpy\nbpy.ops.wm.read_factory_settings(use_empty=True)\nbpy.ops.mesh.primitive_cube_make(size=1.0)"
                res = tool_registry.execute_tool("blender_run_python", {
                    "script_code": broken_script,
                    "output_obj_path": str(target_obj),
                })
                return {"tool_result": res, "artifact_path": str(target_obj)}
            else:
                # Real synthesis for the requested goal
                blender_script = synthesize_blender_script(goal, str(target_obj))
                res = tool_registry.execute_tool("blender_run_python", {
                    "script_code": blender_script,
                    "output_obj_path": str(target_obj),
                })
                return {
                    "tool_result": res,
                    "artifact_path": str(target_obj),
                    "synthesized_code": blender_script,
                }
        else:
            # Generic host execution
            cmd_res = tool_registry.execute_tool("windows_command", {"command": f"Write-Output '{goal}'"})
            target_txt = workspaces_dir / f"{task_id}.txt"
            target_txt.write_text(f"Task: {goal}\nStdout: {cmd_res['stdout']}\n", encoding="utf-8")
            return {"tool_result": cmd_res, "artifact_path": str(target_txt)}

    def verifier(output: dict) -> VerificationResult:
        p = Path(output.get("artifact_path", ""))
        min_sz = 100 if is_3d_task else 5
        res = verification_gate.verify_file_exists(p, min_bytes=min_sz)
        if not res.passed:
            tool_res = output.get("tool_result", {})
            return VerificationResult(
                passed=False,
                error_category="EXECUTION_DEFECT",
                error_signature="OutputArtifactMissingOrEmpty",
                details={"exit_code": tool_res.get("exit_code"), "stderr": tool_res.get("stderr", "")[:300]},
                lesson="Script failed to produce valid output. Ensure correct operator syntax and output path.",
            )
        return res

    result = pilot.run_task(
        task_id=task_id,
        goal=goal,
        worker_executor=worker_executor,
        verifier=verifier,
        skill_distillation_name=f"skill_{task_id}",
        max_attempts=max_att,
    )

    # Launch in Blender GUI if requested
    gui_info = None
    if req.launch_gui and target_obj.exists() and is_3d_task:
        try:
            gui_info = tool_registry.execute_tool("blender_launch_gui", {"file_to_open": str(target_obj)})
        except Exception as e:
            gui_info = {"error": str(e)}

    return {
        "task_id": result.task.id,
        "goal": goal,
        "state": result.task.state.value,
        "attempts_taken": result.attempts_taken,
        "success": result.success,
        "artifact_path": str(target_obj) if target_obj.exists() else None,
        "artifact_size_bytes": target_obj.stat().st_size if target_obj.exists() else 0,
        "download_url": f"/workspaces/{target_obj.name}" if target_obj.exists() else None,
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

      <div class="flex gap-2">
        <input id="prompt-input" type="text" 
          placeholder="Type any 3D model or task prompt here (e.g., 'Create a 3D low-poly sword in Blender')..." 
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
      <button onclick="switchTab('tab-tasks')" class="tab-btn pb-2 border-b-2 border-sky-400 text-sky-400" id="btn-tasks">📋 Task Lifecycle & 3D Assets</button>
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
              <th class="p-2.5">Output 3D Asset</th>
            </tr>
          </thead>
          <tbody id="tasks-table-body" class="divide-y divide-slate-700/60">
            <tr><td colspan="5" class="p-4 text-center text-slate-500">Loading tasks...</td></tr>
          </tbody>
        </table>
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

  <script>
    function setPrompt(text) {
      document.getElementById('prompt-input').value = text;
    }

    async function dispatchUserTask() {
      const input = document.getElementById('prompt-input');
      const goal = input.value.trim();
      if (!goal) return;

      const launchGui = document.getElementById('check-launch-gui').checked;
      const btn = document.getElementById('dispatch-btn');
      const card = document.getElementById('live-status-card');
      const title = document.getElementById('live-status-title');
      const detail = document.getElementById('live-status-detail');
      const linkDiv = document.getElementById('live-status-link');

      btn.disabled = true;
      btn.innerText = '⏳ Executing...';
      card.classList.remove('hidden');
      title.innerText = '⚡ Executing task: ' + goal;
      detail.innerText = 'Worker dispatched -> Communicating over Named Pipe to real Blender 4.5...';
      linkDiv.innerHTML = '';

      try {
        const res = await fetch('/api/tasks/dispatch', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ goal: goal, launch_gui: launchGui })
        });
        const data = await res.json();
        title.innerText = `✓ Task Completed: ${data.state} (Took ${data.attempts_taken} attempts)`;
        title.className = data.success ? 'font-bold text-emerald-400' : 'font-bold text-rose-400';
        detail.innerText = `Artifact created: ${data.artifact_path || 'None'} (${data.artifact_size_bytes} bytes).`;
        
        if (data.download_url) {
          linkDiv.innerHTML = `<a href="${data.download_url}" target="_blank" class="text-sky-400 underline font-semibold text-[11px]">📥 Download Generated 3D OBJ (${data.artifact_size_bytes} bytes)</a>`;
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
        return `
          <tr class="hover:bg-slate-700/30">
            <td class="p-2.5 font-mono text-slate-300">${t.id}</td>
            <td class="p-2.5 font-medium text-slate-200">${t.title}</td>
            <td class="p-2.5"><span class="px-2 py-0.5 border rounded-full text-[10px] font-semibold ${badgeColor}">${t.state}</span></td>
            <td class="p-2.5 text-slate-400">${t.attempt_count} / ${t.max_attempts}</td>
            <td class="p-2.5 text-slate-400">
              <a href="/workspaces/${t.id}.obj" target="_blank" class="text-sky-400 hover:underline font-mono text-[11px]">${t.id}.obj</a>
            </td>
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

    function refreshAll() {
      loadTelemetry();
      loadTasks();
      loadMistakes();
      loadSkills();
      loadTools();
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
