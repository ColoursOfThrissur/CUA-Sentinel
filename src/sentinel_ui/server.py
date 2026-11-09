"""Sentinel Control UI & REST API Server (FastAPI).
Serves real-time telemetry, configuration management, mistake inspection, and skill bank execution.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
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
pilot = AdaptivePilotController(state_machine, verification_gate, mistake_memory, skill_bank)


class ConfigUpdateRequest(BaseModel):
    max_attempts: int | None = None
    attempt_timeout_sec: float | None = None
    memory_limit_mb: int | None = None
    cpu_rate_percent: float | None = None
    use_appcontainer: bool | None = None
    allow_irreversible: bool | None = None


class CreateTaskRequest(BaseModel):
    task_id: str
    goal: str
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


@app.post("/api/skills/execute")
def execute_skill(req: ExecuteSkillRequest):
    skill = skill_bank.get_skill(req.skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    local_scope = {"params": req.params, "ctx": {}, "result": None}
    try:
        exec(skill["code"], {}, local_scope)
        return {"status": "SUCCESS", "skill": req.skill_name, "result": local_scope.get("result")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Execution error: {e}")


@app.post("/api/tasks/run_demo")
def run_demo_task():
    """Runs a simulated adaptive learning task demonstrating Attempt 1 fail -> Attempt 2 pass."""
    import time
    task_id = f"task_ui_{int(time.time())}"
    goal = "Synthesize and verify 3D asset"
    target_path = Path("workspaces") / f"{task_id}.obj"
    target_path.parent.mkdir(parents=True, exist_ok=True)

    def executor(g, attempt_num, anti_patterns):
        if attempt_num == 1:
            target_path.write_text("", encoding="utf-8")
            return {"path": str(target_path)}
        else:
            obj_data = "v 0.0 0.0 0.0\nv 1.0 1.0 1.0\nf 1 2\n"
            target_path.write_text(obj_data, encoding="utf-8")
            return {
                "path": str(target_path),
                "synthesized_code": f"result = {{'mesh_created': '{str(target_path)}'}}",
            }

    def verifier(output):
        return verification_gate.verify_file_exists(target_path, min_bytes=10)

    res = pilot.run_task(
        task_id=task_id,
        goal=goal,
        worker_executor=executor,
        verifier=verifier,
        skill_distillation_name=f"skill_cube_{int(time.time()) % 1000}",
        max_attempts=config.iteration_limits.max_attempts,
    )

    return {
        "task_id": res.task.id,
        "final_state": res.task.state.value,
        "attempts_taken": res.attempts_taken,
        "success": res.success,
        "mistakes_encountered": res.mistakes_encountered,
        "distilled_skill": res.distilled_skill,
    }


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Sentinel Control Plane</title>
  <script src="https://www.gstatic.com/antigravity/web/dev/tailwindcss.min.js"></script>
  <style>
    :root {
      --background: #0f172a;
      --card: #1e293b;
      --border: #334155;
      --foreground: #f8fafc;
      --muted: #94a3b8;
      --primary: #38bdf8;
      --primary-hover: #0284c7;
      --success: #34d399;
      --danger: #f87171;
    }
  </style>
</head>
<body class="bg-[#0f172a] text-slate-100 min-h-screen p-6 font-sans">
  <div class="max-w-7xl mx-auto space-y-6">

    <!-- Header -->
    <header class="flex items-center justify-between border-b border-slate-700 pb-4">
      <div>
        <h1 class="text-2xl font-bold tracking-tight text-sky-400 flex items-center gap-2">
          <span>🛡️</span> Sentinel Control Plane & Organ Monitor
        </h1>
        <p class="text-xs text-slate-400 mt-1">Biological Autonomous Agent Harness · Windows 11 AppContainer Baseline</p>
      </div>
      <div class="flex items-center gap-3">
        <button onclick="runDemoTask()" class="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-xs font-semibold rounded-lg shadow transition flex items-center gap-1.5">
          <span>⚡</span> Run Adaptive Task
        </button>
        <button onclick="refreshAll()" class="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 border border-slate-600 text-xs font-semibold rounded-lg transition">
          🔄 Refresh
        </button>
      </div>
    </header>

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

    <!-- Main Navigation Tabs -->
    <div class="border-b border-slate-700 flex gap-4 text-xs font-semibold text-slate-400">
      <button onclick="switchTab('tab-config')" class="tab-btn pb-2 border-b-2 border-sky-400 text-sky-400" id="btn-config">⚙️ Iteration & Quota Config</button>
      <button onclick="switchTab('tab-tasks')" class="tab-btn pb-2 hover:text-slate-200" id="btn-tasks">📋 Task Lifecycle & Transitions</button>
      <button onclick="switchTab('tab-mistakes')" class="tab-btn pb-2 hover:text-slate-200" id="btn-mistakes">🧠 Episodic Mistake Memory</button>
      <button onclick="switchTab('tab-skills')" class="tab-btn pb-2 hover:text-slate-200" id="btn-skills">✨ Skill Bank Catalog</button>
      <button onclick="switchTab('tab-effects')" class="tab-btn pb-2 hover:text-slate-200" id="btn-effects">📜 Side-Effect Ledger (AT-B-08/09)</button>
    </div>

    <!-- Tab 1: Configuration -->
    <div id="tab-config" class="tab-content bg-slate-800/60 border border-slate-700 rounded-xl p-5 space-y-4">
      <h2 class="text-base font-bold text-slate-100 flex items-center gap-2">Control Solution Iterations & Resource Quotas</h2>
      <p class="text-xs text-slate-400">Adjust the biological bounded loop parameters, AppContainer resource quotas, and safety policies live.</p>
      
      <div class="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2">
        <div class="space-y-1">
          <label class="text-xs font-medium text-slate-300">Max Attempts (Iteration Level)</label>
          <input type="number" id="cfg-max-attempts" min="1" max="10" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-100 focus:border-sky-500 outline-none">
          <p class="text-[11px] text-slate-500">Bounded attempt count per task (default: 3)</p>
        </div>
        <div class="space-y-1">
          <label class="text-xs font-medium text-slate-300">Attempt Timeout (Seconds)</label>
          <input type="number" id="cfg-timeout" min="5" max="300" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-100 focus:border-sky-500 outline-none">
          <p class="text-[11px] text-slate-500">Wall-clock limit before Job Object kill</p>
        </div>
        <div class="space-y-1">
          <label class="text-xs font-medium text-slate-300">Memory Cap (MB per Worker)</label>
          <input type="number" id="cfg-memory" min="50" max="1024" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-100 focus:border-sky-500 outline-none">
          <p class="text-[11px] text-slate-500">Native Windows Job Object RAM ceiling</p>
        </div>
        <div class="space-y-1">
          <label class="text-xs font-medium text-slate-300">CPU Hard Cap (%)</label>
          <input type="number" step="0.5" id="cfg-cpu" min="5" max="100" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-100 focus:border-sky-500 outline-none">
          <p class="text-[11px] text-slate-500">Hardware CPU rate control (default: 12.5%)</p>
        </div>
        <div class="space-y-1">
          <label class="text-xs font-medium text-slate-300">AppContainer Runtime Isolation</label>
          <select id="cfg-isolation" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-100 focus:border-sky-500 outline-none">
            <option value="true">Enabled (Windows 11 AppContainer)</option>
            <option value="false">Disabled (Host Simulation Mode)</option>
          </select>
          <p class="text-[11px] text-slate-500">Enforces zero-capability sandbox</p>
        </div>
        <div class="space-y-1">
          <label class="text-xs font-medium text-slate-300">Allow Irreversible Side Effects</label>
          <select id="cfg-irreversible" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-100 focus:border-sky-500 outline-none">
            <option value="false">Denied (Fail-Closed Policy)</option>
            <option value="true">Permitted (Operator Clearance)</option>
          </select>
          <p class="text-[11px] text-slate-500">PDP gate for permanent actions</p>
        </div>
      </div>

      <div class="pt-3">
        <button onclick="saveConfig()" class="px-4 py-2 bg-sky-600 hover:bg-sky-500 text-xs font-semibold text-white rounded-lg transition shadow">
          💾 Save Configuration
        </button>
        <span id="cfg-status" class="ml-3 text-xs text-emerald-400 font-medium"></span>
      </div>
    </div>

    <!-- Tab 2: Task Lifecycle -->
    <div id="tab-tasks" class="tab-content hidden bg-slate-800/60 border border-slate-700 rounded-xl p-5 space-y-3">
      <h2 class="text-base font-bold text-slate-100">Tasks & State Transitions</h2>
      <div class="overflow-x-auto">
        <table class="w-full text-left text-xs">
          <thead class="bg-slate-900/60 text-slate-400 border-b border-slate-700">
            <tr>
              <th class="p-2.5">Task ID</th>
              <th class="p-2.5">Title</th>
              <th class="p-2.5">State</th>
              <th class="p-2.5">Attempts</th>
              <th class="p-2.5">Failure Reason</th>
            </tr>
          </thead>
          <tbody id="tasks-table-body" class="divide-y divide-slate-700/60">
            <tr><td colspan="5" class="p-4 text-center text-slate-500">Loading tasks...</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Tab 3: Mistake Memory -->
    <div id="tab-mistakes" class="tab-content hidden bg-slate-800/60 border border-slate-700 rounded-xl p-5 space-y-3">
      <h2 class="text-base font-bold text-slate-100">Episodic Mistake Memory & Lessons Learned</h2>
      <p class="text-xs text-slate-400">Biological anti-pattern ledger. Failed attempt signatures injected as negative prompt constraints on retries.</p>
      <div id="mistakes-container" class="space-y-2 pt-2">
        <p class="text-xs text-slate-500">Loading mistake ledger...</p>
      </div>
    </div>

    <!-- Tab 4: Skill Bank -->
    <div id="tab-skills" class="tab-content hidden bg-slate-800/60 border border-slate-700 rounded-xl p-5 space-y-3">
      <h2 class="text-base font-bold text-slate-100">Skill Bank & Synthesized Tools</h2>
      <p class="text-xs text-slate-400">Verified code artifacts crystallized into dynamic skills, registered in the broker for zero-shot re-use.</p>
      <div id="skills-container" class="grid grid-cols-1 md:grid-cols-2 gap-3 pt-2">
        <p class="text-xs text-slate-500">Loading skills...</p>
      </div>
    </div>

    <!-- Tab 5: Side Effects -->
    <div id="tab-effects" class="tab-content hidden bg-slate-800/60 border border-slate-700 rounded-xl p-5 space-y-3">
      <h2 class="text-base font-bold text-slate-100">Side-Effect Replay Ledger (AT-B-08, AT-B-09)</h2>
      <div class="overflow-x-auto">
        <table class="w-full text-left text-xs">
          <thead class="bg-slate-900/60 text-slate-400 border-b border-slate-700">
            <tr>
              <th class="p-2.5">ID</th>
              <th class="p-2.5">Attempt ID</th>
              <th class="p-2.5">Tool</th>
              <th class="p-2.5">Class</th>
              <th class="p-2.5">Status</th>
              <th class="p-2.5">Intent / Outcome</th>
            </tr>
          </thead>
          <tbody id="effects-table-body" class="divide-y divide-slate-700/60">
            <tr><td colspan="6" class="p-4 text-center text-slate-500">Loading effects...</td></tr>
          </tbody>
        </table>
      </div>
    </div>

  </div>

  <script>
    function switchTab(tabId) {
      document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));
      document.querySelectorAll('.tab-btn').forEach(el => {
        el.classList.remove('border-b-2', 'border-sky-400', 'text-sky-400');
        el.classList.add('hover:text-slate-200');
      });
      document.getElementById(tabId).classList.remove('hidden');
      const btnId = 'btn-' + tabId.replace('tab-', '');
      const btn = document.getElementById(btnId);
      if (btn) {
        btn.classList.add('border-b-2', 'border-sky-400', 'text-sky-400');
      }
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
            <td class="p-2.5 text-slate-400">${t.failure_reason || 'None'}</td>
          </tr>
        `;
      }).join('');
    }

    async function loadMistakes() {
      const res = await fetch('/api/mistakes');
      const list = await res.json();
      const c = document.getElementById('mistakes-container');
      if (list.length === 0) {
        c.innerHTML = '<p class="text-xs text-slate-500">No mistakes logged yet. System running cleanly.</p>';
        return;
      }
      c.innerHTML = list.map(m => `
        <div class="bg-slate-900/70 border border-amber-500/20 rounded-lg p-3 space-y-1">
          <div class="flex items-center justify-between">
            <span class="text-amber-400 font-semibold text-xs">[${m.error_category}] ${m.error_signature}</span>
            <span class="text-[10px] text-slate-500 font-mono">${m.task_id}</span>
          </div>
          <p class="text-xs text-slate-300 font-medium">Lesson Learned: <span class="text-slate-200 font-normal">${m.lesson_learned}</span></p>
          <p class="text-[11px] text-slate-500 font-mono">Context: ${m.context}</p>
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
          <pre class="bg-slate-950 p-2 rounded text-[10px] font-mono text-emerald-400 overflow-x-auto">${s.code}</pre>
        </div>
      `).join('');
    }

    async function loadSideEffects() {
      const res = await fetch('/api/side_effects');
      const list = await res.json();
      const tbody = document.getElementById('effects-table-body');
      if (list.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="p-4 text-center text-slate-500">No side-effects logged.</td></tr>';
        return;
      }
      tbody.innerHTML = list.map(e => `
        <tr class="hover:bg-slate-700/30">
          <td class="p-2.5 font-mono text-slate-400">${e.id}</td>
          <td class="p-2.5 font-mono text-slate-300 text-[11px]">${e.attempt_id}</td>
          <td class="p-2.5 font-semibold text-sky-400">${e.tool_name}</td>
          <td class="p-2.5"><span class="px-1.5 py-0.5 bg-slate-800 border border-slate-700 text-[10px] rounded text-slate-300">${e.effect_class}</span></td>
          <td class="p-2.5 text-xs text-emerald-400">${e.status}</td>
          <td class="p-2.5 font-mono text-[10px] text-slate-400 truncate max-w-xs">${e.outcome_payload || e.intent_payload}</td>
        </tr>
      `).join('');
    }

    async function runDemoTask() {
      const btn = event.target;
      btn.disabled = true;
      btn.innerText = '⏳ Executing...';
      try {
        const res = await fetch('/api/tasks/run_demo', { method: 'POST' });
        const result = await res.json();
        alert(`Task ${result.task_id} completed: ${result.final_state} (Took ${result.attempts_taken} attempts)`);
        refreshAll();
      } catch (e) {
        alert('Task error: ' + e);
      } finally {
        btn.disabled = false;
        btn.innerText = '⚡ Run Adaptive Task';
      }
    }

    function refreshAll() {
      loadTelemetry();
      loadTasks();
      loadMistakes();
      loadSkills();
      loadSideEffects();
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
