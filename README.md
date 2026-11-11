<div align="center">

# 🛡️ CUA-Sentinel
### High-Assurance Autonomous Execution Platform for Computer-Use Agents (CUA)
**Windows 11 Runtime · AppContainer Sandbox · Policy Decision Point · Monotonic Lease Fencing · Multi-Agent DAG**

[![Test Suite](https://img.shields.io/badge/tests-87%20passed%20(100%25)-10b981.svg)](#test-suite)
[![Python](https://img.shields.io/badge/python-3.12-38bdf8.svg)](https://python.org)
[![Platform](https://img.shields.io/badge/platform-Windows%2011%20Home%2FPro-6366f1.svg)](#architecture)
[![UI](https://img.shields.io/badge/frontend-Pure%20CSS%20(Zero%20Tailwind)-f43f5e.svg)](#spatial-canvas-ui)
[![Hardware](https://img.shields.io/badge/inference-Local%20GPU%20(Qwen%203.5)-a855f7.svg)](#local-inference)

</div>

---

## 📖 Overview

**Sentinel** is an autonomous operating platform engineered specifically for **Computer-Use Agents (CUA)** running on Windows 11. It bridges local small language models (SLMs like `qwen3.5:9b`) with high-privilege operating system environments without risking runaway process loops, filesystem corruption, or unverified side effects.

Rather than running AI agents with unconstrained host shell access, Sentinel enforces strict **OS-level isolation boundaries**:
* **Windows AppContainer Sandboxing**: Every worker executes in an isolated low-integrity token with a dedicated DACL-gated Named Pipe.
* **Deterministic Policy Decision Point (PDP)**: All privileged sensory and motor organ invocations are evaluated outside the agent against strict monotonic leases (`AT-B-10`).
* **Multi-Agent Topological DAG Engine**: Decomposes complex multi-stage objectives into concurrent dependency waves with structured artifact contracts.
* **Autonomous ReAct Reasoning Loop**: Multi-turn *Reason $\rightarrow$ Act $\rightarrow$ Observe $\rightarrow$ Reason* loop with dynamic mistake self-healing.
* **Native Desktop Computer-Use Organs**: Sub-millisecond desktop vision capture via Win32 GDI `BitBlt` and guarded mouse/keyboard motor organs.

---

## 🏛️ System Architecture Topology

```
                                  [Operator UI / CLI Console]
                                               │
                                               ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        SENTINEL CONTROL PLANE (Host Process)                           │
├────────────────────────────────┬───────────────────────────────────────────────────────┤
│  FastAPI REST Server (:8000)   │  Authoritative StateMachine (SQLite with Leases)      │
│  Multi-Agent DAG Orchestrator  │  ReAct Multi-Turn Reasoning Controller                │
│  Semantic Mistake Memory       │  Dynamic Skill Bank (Reusable distilled tools)        │
└────────────────────────────────┴───────────────────────────────────────────────────────┘
                                               │
                         ┌─────────────────────┴─────────────────────┐
                         ▼                                           ▼
┌─────────────────────────────────────────────┐ ┌────────────────────────────────────────┐
│      EXECUTION BROKER & POLICY DECISION     │ │        MODEL GATEWAY & HOST GPU        │
│  • AT-B-10 Monotonic Lease Fencing          │ │  • Local Ollama (qwen3.5:9b)           │
│  • AT-B-05 Process Tree Drain & Cancel      │ │  • PreFlightLinter (AST Sanitizer)     │
│  • Write Fence: G:\Sentinel_Workspace       │ │  • Contract Library (Test Harnesses)   │
│  • Network Egress Domain Whitelisting       │ │  • Prompt Scaffolder (Levels 1 to 3)   │
└─────────────────────────────────────────────┘ └────────────────────────────────────────┘
                         │
        ┌────────────────┼────────────────────┬────────────────────┐
        ▼                ▼                    ▼                    ▼
[Sensory Organs]  [Motor Organs]       [Desktop CUA Organs]  [Isolated Workers]
System Filesystem Mouse/Keyboard       Win32 GDI BitBlt      Windows AppContainer
Inspect & Drives  Windows Command/CLI  Vision Screenshot     DACL Named Pipe IPC
```

---

## ⚡ Core Engineering Capabilities

### 1. Monotonic Lease Fencing (`AT-B-10`) & Cancellation (`AT-B-05`)
Every execution attempt generates an incrementing, monotonic lease counter in SQLite. When a task times out or is cancelled by the operator:
* The lease token is immediately revoked.
* Any zombie or runaway background worker attempting to invoke tools or commit files receives `REJECTED_STALE_LEASE` and fails closed.
* Sentinel traverses the operating system process tree via `psutil` and recursively drains all orphaned child processes within 2.0s.

### 2. Multi-Agent DAG Wave Orchestration
* **Topological Wave Execution**: Uses Kahn's algorithm to analyze dependency graphs, grouping independent steps into parallel execution waves (`ThreadPoolExecutor`).
* **Artifact Contracts**: Successor steps receive structured, typed inputs from predecessor outputs (`.csv` statistics, `.obj` dimensions, `.py` exports).
* **Pre-Built Pipelines**:
  1. `analytics`: Edge IoT Telemetry $\rightarrow$ Anomaly Detector $\rightarrow$ Executive Briefing.
  2. `3d_engineering`: Procedural 3D Mesh Synthesis $\rightarrow$ Syntax Linting $\rightarrow$ Real Blender 4.5 OBJ Export.
  3. `system_audit`: Host Storage Audit $\rightarrow$ Drive Health Analysis $\rightarrow$ Systems Report.
  4. `code_verification`: Python Generation $\rightarrow$ AppContainer Execution $\rightarrow$ Contract Verification Gate.
* **Visual Pipeline Builder**: Build and execute custom multi-agent DAGs directly inside the dashboard.

### 3. Native Computer-Use Desktop Organs
* **Sensory (Vision)**: `screen_capture` uses native Windows GDI `BitBlt` to grab full-resolution desktop screenshots directly into memory, saving PNGs in sub-millisecond time.
* **Sensory (Perception)**: `desktop_get_cursor_position` queries real-time cursor localization and hardware display resolution.
* **Guarded Motor Actuation**:
  * `desktop_mouse_action`: Moves, clicks, double-clicks, or right-clicks, strictly fenced by display boundaries (`0 <= x < width`, `0 <= y < height`).
  * `desktop_keyboard_type`: Native Unicode keystroke typing with a security filter that rejects dangerous OS combos (`Alt+F4`, `Ctrl+Alt+Del`, `Win+L`, `Ctrl+Shift+Esc`).

### 4. Adaptive Self-Healing & Semantic Mistake Memory
When code execution or geometry generation fails:
1. The **Verification Gate** captures the traceback and broken AST line.
2. An LLM diagnostician analyzes the defect and synthesizes an imperative lesson into the **Mistake Memory** SQLite ledger.
3. On Attempt 2, Sentinel injects the synthesized anti-pattern into the prompt scaffold to avoid repeating known defects.

---

## 🎨 Spatial Canvas UI (Zero Tailwind)

The Sentinel control interface is built with **Pure Vanilla CSS** (strictly no Tailwind, no rigid boxy tables) using native ES Modules:
* **Theme Tokens**: Obsidian canvas palette (`#080b10`), frosted-glass surfaces (`backdrop-filter: blur(18px)`), glowing semantic status badges.
* **Fullscreen Edge-to-Edge Grid**: Fully responsive layout without artificial max-width constraints.
* **Integrated Viewports**:
  * **3D Viewport**: Real-time Three.js viewer with lighting and OrbitControls for generated `.obj` meshes.
  * **CSV Viewport**: Tabular grid with real-time search, sorting, and row filtering.
  * **Code Viewport**: Formatted code container for `.py` and `.json` artifacts with one-click copy.
  * **Markdown Reader**: Clean reader for executive reports and ReAct trajectories.

---

## 🚀 Quickstart

### 1. Requirements
* Windows 11 (Home or Pro)
* Python 3.12+
* Local Ollama with `qwen3.5:9b` (or preferred model)
* Blender 4.5 LTS (optional, for real 3D mesh rendering)

### 2. Setup
```powershell
# Clone the repository
git clone https://github.com/your-username/Sentinel.git
cd Sentinel

# Create virtual environment & install dependencies
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. Launching Sentinel
```powershell
# Start local Ollama daemon (in one terminal)
ollama run qwen3.5:9b

# Launch the Sentinel Control Plane & Dashboard
python src/sentinel_ui/server.py
```
Open **[http://localhost:8000](http://localhost:8000)** in your browser.

### 4. Running the Test Suite
```powershell
pytest
```
*Current test suite: **87 of 87 unit and integration tests passing (100% green)**.*

---

## 📂 Repository Structure

```
Sentinel/
├── config.yaml                     # Primary runtime quotas, network egress & storage config
├── docs/
│   └── baseline/                   # Architecture specs & decision closures (v0.3.0 baseline)
├── src/
│   ├── sentinel_broker/            # Policy Decision Point (PDP), leases & organ registries
│   │   ├── organs/                 # Sensory, motor, blender, data, web, and desktop organs
│   ├── sentinel_core/              # State machine, DAG engine, DB, verification gates, LLM gateway
│   ├── sentinel_adaptive/          # ReAct controller, mistake memory, dynamic skill bank
│   ├── sentinel_runner/            # Windows AppContainer host & DACL named pipe infrastructure
│   ├── sentinel_ui/                # FastAPI control server & pure-CSS spatial React dashboard
│   │   └── static/                 # Pure CSS tokens, components, viewports, and ES modules
│   └── sentinel_worker/            # Isolated attempt worker harness
└── tests/                          # 87 automated unit & integration test suites
```

---

## 📜 License
Apache-2.0 License. Built for secure, verifiable, and observable autonomous agent execution.
