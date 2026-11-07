# CUA-Sentinel Architecture Pack v0.2.3 — Consolidated Baseline
**Version:** 0.2.3 · 7 November 2026 · **Status:** Draft for review / Updated Baseline  
**Supersedes:** v0.1 (CS-00 to CS-06), v0.2, v0.2.1, v0.2.2

---

## 1. How to Read This Document
* **Consolidated Baseline**: Replaces legacy CS-00 through CS-06 files with one reviewable architecture baseline.
* **Status Vocabulary**: `Accepted`, `Proposed`, `Open`, `Deferred`, `Rejected`, `Superseded`. ('Accepted in principle' is retired; principles and mechanisms are split).
* **Evidence Labels**:
  * `D` = Confirmed in primary documentation.
  * `S` = Reported consistently by several secondary sources.
  * `V` = Single-source or vendor claim.
  * `I` = Inference / unverified assumption.

---

## 2. Core Constraints and Scope
* **Hardware & OS (Planning Constraints)**:
  * CPU: Intel Core i5-14400F
  * GPU: NVIDIA GeForce RTX 3060 12 GB
  * RAM: 16 GB DDR4 (Hard planning limit for concurrent sandboxes, SQLite, and local LLM runtime)
  * Storage: 1 TB NVMe SSD
  * OS: **Windows 11 Home** (Confirmed 7 Nov 2026; official Windows Sandbox and Client Hyper-V are unavailable)
* **Scope (V1)**:
  * **Local-first**: No mandatory cloud dependencies. Cloud providers are optional adapters, disabled by default, governed by strict per-release permissions and data-egress policies.
  * **Single local operator**: Authentication is local operator credential. Multi-user and multi-tenant are Deferred, but identity fields remain explicit.
  * **T0 Trust Tier Only**: V1 admits first-party, operator-approved builds with recorded provenance/hash. Untrusted code (T1/T2) is refused at registration.
  * **Platform Focus**: V1 delivers the autonomous execution platform that computer-use agents (CUA) run on, not raw computer-use desktop control itself.

---

## 3. Boundary Rules (R1 to R19)
* **R1–R10**: Core ground-truth, immutable release snapshotting, separated authoritative vs telemetry tiers, and single-writer control plane.
* **R11**: Authorization is enforced by a deterministic Policy Decision Point (PDP) outside the agent, evaluated before each tool call, failing closed.
* **R12**: Credentials are held by the host Execution Broker and injected outside the sandbox boundary. Sandboxes never hold long-lived secrets.
* **R13 (Lethal Trifecta Check)**: A release must not hold private-data access, untrusted-content exposure, and an egress channel together without explicit operator approval bound to that exact release and capability set.
* **R14**: Model inference runs on host GPU outside sandboxes as a host service reached exclusively through the Model Gateway. Sandboxes receive no GPU in V1.
* **R15**: External protocol task handles (MCP, A2A) are references only. Sentinel's task state machine is the sole authority.
* **R16**: Protocol revisions and telemetry conventions are pinned behind mapping layers.
* **R17**: Sandbox network egress is **default-deny**, enforced outside the agent by the OS/hypervisor. The only reachable host destinations are the Broker and Model Gateway.
* **R18**: No agent implementation code runs in the control-plane or trusted-harness process.
* **R19**: Network authorization and data-egress authorization are separate decisions.

---

## 4. Execution Topology
* **Control Plane (Host)**: Single writer for authoritative SQLite state; manages registry, scheduler, and orchestrator.
* **Execution Broker (Host)**: Validates schemas and leases, evaluates PDP, manages credentials, and executes privileged host tools.
* **Model Gateway (Host Service)**: Single path to local (Ollama/vLLM) and cloud models; enforces data classifications and egress rules.
* **Trusted Harness (Host)**: Drives attempt lifecycle, records intent/outcome in session logs, communicates over IPC.
* **Attempt Worker (Isolated Sandbox)**: Disposable single-attempt process (Windows AppContainer) holding agent code, adapter, and low-risk workspace tools.

---

## 5. Acceptance Test Matrix (48 Tests)
*Status: 47 Mandatory, 1 Conditional (`AT-D-06`).*

| Test ID | Gate Item | Requirements | Invariant / Target |
| :--- | :--- | :--- | :--- |
| **AT-A-01** | Gate A (Lifecycle) | FR-001, FR-002 | Register a custom agent from a valid manifest. |
| **AT-A-02** | Gate A (Lifecycle) | FR-001 | Reject invalid manifests with actionable diagnostics. |
| **AT-A-03** | Gate A (Lifecycle) | FR-003, FR-004 | Publish a release and retain its immutable snapshot. |
| **AT-A-04** | Gate A (Lifecycle) | FR-003, FR-004, FR-015 | Change configuration, test draft, publish new release. |
| **AT-A-05** | Gate A (Lifecycle) | FR-004 | Older runs remain bound to their historical release snapshot. |
| **AT-A-06** | Gate A (Lifecycle) | FR-023 | Disable and retire an agent or release without deleting history. |
| **AT-B-01** | Gate B (Execution) | FR-005, FR-014 | Execute a multi-step task on a real isolated worker. |
| **AT-B-02** | Gate B (Execution) | FR-006, FR-008 | Capture start, step progress, tool activity, completion, and failure. |
| **AT-B-03** | Gate B (Execution) | FR-009 | Kill or restart worker mid-task. |
| **AT-B-04** | Gate B (Execution) | FR-009, FR-029 | Reconcile as resumable, retryable, failed, or outcome-unknown by policy. |
| **AT-B-05** | Gate B (Execution) | FR-005 | Cancellation and timeout handling with graceful drain. |
| **AT-B-06** | Gate B (Execution) | FR-027 | Duplicate delivery causes no duplicate side effects (idempotency keys). |
| **AT-B-07** | Gate B (Execution) | FR-006, FR-009 | Kill control plane mid-transition; state reconciles cleanly on reboot. |
| **AT-B-08** | Gate B (Execution) | FR-027, FR-035 | Intent logged without outcome becomes `Unknown` and is never auto-replayed. |
| **AT-B-09** | Gate B (Execution) | FR-029, FR-035 | Task with an `Unknown` non-idempotent effect halts in `NeedsReconciliation`. |
| **AT-B-10** | Gate B (Execution) | FR-005, FR-009 | Stale lease token call is rejected by broker; $\le 1$ active worker per task. |
| **AT-C-01** | Gate C (Governance) | FR-007 | Ungranted capability call is denied by PDP, even with crafted request. |
| **AT-C-02** | Gate C (Governance) | FR-007, FR-014 | Filesystem access outside workspace is denied. |
| **AT-C-03** | Gate C (Governance) | FR-017 | Protected action cannot proceed without a valid bound approval record. |
| **AT-C-04** | Gate C (Governance) | FR-026 | Secret values never appear in raw logs, traces, or session records. |
| **AT-C-05** | Gate C (Governance) | FR-007 | PDP denies ungranted calls and fails closed on error/crash. |
| **AT-C-06** | Gate C (Governance) | FR-026 | Credentials and long-lived API tokens are not readable inside the sandbox. |
| **AT-C-07** | Gate C (Governance) | FR-032 | Release holding all 3 trifecta tags is blocked without explicit bound approval. |
| **AT-C-08** | Gate C (Governance) | FR-034 | Direct sandbox network egress is default-deny across TCP, UDP, DNS, proxy, IPv6. |
| **AT-C-09** | Gate C (Governance) | FR-036 | Agent without T0 provenance is refused even if manifest claims T0. |
| **AT-C-10** | Gate C (Governance) | FR-037 | Gateway refuses restricted data bound for cloud model if release lacks cloud egress. |
| **AT-C-11** | Gate C (Governance) | FR-014 | Worker process cannot open, read, or write core store database files. |
| **AT-C-12** | Gate C (Governance) | FR-036 | Build modified after approval or artifact swapped before launch is refused. |
| **AT-C-13** | Gate C (Governance) | FR-026 | Canary secret never appears in store, environment, worker files, or traces. |
| **AT-C-14** | Gate C (Governance) | FR-007, FR-037 | File written by private task inherits private label; unlabelled source refused. |
| **AT-D-01** | Gate D (Data) | FR-012 | Fresh install initializes the expected authoritative schema. |
| **AT-D-02** | Gate D (Data) | FR-012 | Upgrade from previous supported schema version preserves state. |
| **AT-D-03** | Gate D (Data) | FR-012 | Backup and restore retains full integrity across core, session log, and audit. |
| **AT-D-04** | Gate D (Data) | FR-012 | Database integrity checks (`PRAGMA integrity_check`) pass after crash recovery. |
| **AT-D-05** | Gate D (Data) | FR-018a | Telemetry growth does not expand authoritative core tables. |
| **AT-D-06** | Gate D (Data) | Conditional | A derived index can be deleted and rebuilt without data loss. |
| **AT-D-07** | Gate D (Data) | FR-018a | Outbox rows are pruned after confirmed delivery. |
| **AT-D-08** | Gate D (Data) | FR-006, FR-009 | Kill between transition and session-log write leaves no state gap (atomic commit). |
| **AT-E-01** | Gate E (Observability) | FR-008, FR-024 | Follow a run from request through agent, tool calls, and validation. |
| **AT-E-02** | Gate E (Observability) | FR-008 | Errors expose the failing component and correlation IDs. |
| **AT-E-03** | Gate E (Observability) | FR-008, FR-030 | Metrics captured for duration, retries, token usage, and resources. |
| **AT-E-04** | Gate E (Observability) | FR-018a, FR-026 | Retention cleanup and redaction rules behave as configured. |
| **AT-E-05** | Gate E (Observability) | FR-008 | Canonical events export through OTLP via mapping layer. |
| **AT-E-06** | Gate E (Observability) | FR-025 | Security actions leave durable audit records untouched by routine pruning. |
| **AT-F-01** | Gate F (Usability) | FR-010, FR-011, FR-016, FR-023 | Operator completes full agent lifecycle from UI/API without editing core code. |
| **AT-F-02** | Gate F (Usability) | FR-011 | UI accurately reflects backend authoritative state. |
| **AT-F-03** | Gate F (Usability) | FR-010, FR-011 | API and UI report system and task failures accurately. |
| **AT-F-04** | Gate F (Usability) | FR-028 | API and UI endpoints require operator authentication. |

---

## 6. ADR Register (v0.2.3 Status)

| ADR | Topic | Status | Position |
| :--- | :--- | :--- | :--- |
| **001** | Product direction | **Accepted** | Local-first autonomous execution platform. |
| **002** | Agent extensibility | **Accepted (principle)**; contracts Open | Common contract + adapters; no framework becomes canonical. |
| **003** | Agent editing | **Accepted (principle)**; format Open | Three tiers: configuration, workflow, and developer code. |
| **004** | Observability | **Accepted** | Observability as a first-class control plane capability. |
| **005** | Ground-truth protection | **Accepted** | Authoritative state, telemetry, and derived data strictly separated. |
| **006** | Database topology | **Open** | Single-writer SQLite WAL vs. Postgres. Closes jointly with 008 via S7. |
| **007** | Runtime isolation | **Open** (T0-only principle Accepted) | Principle: V1 admits T0 only. Mechanism on Win 11 Home decided by S1. |
| **008** | Workflow & durability | **Accepted (spec)**; engine Open | State machine, leases, fencing, effect classes, and replay contract fixed. Engine decided by S2. |
| **009** | Telemetry backend | **Open** | Canonical schema + mapping layer to OTel agent spans. Spike S5. |
| **010** | Framework strategy | **Open** | Adapters via proof-of-integration. No framework in control plane. |
| **011** | Visual builder | **Accepted (direction)**; Deferred | Visual builder sits on declarative definitions; deferred post-V1. |
| **012** | Deployment topology | **Proposed** | Modular monolith control plane + isolated attempt workers. |
| **013** | Policy engine (PDP) | **Accepted (principle)**; engine Open | Deterministic host-side PDP failing closed. Engine decided by S3. |
| **014** | Protocol pinning | **Proposed** | Pin MCP and A2A specs; broker owns clients and task references. Spike S4. |
| **015** | Secrets injection | **Accepted (principle)**; backend Open | Broker injects secrets outside sandbox; agents hold only references. |
| **016** | Model gateway | **Accepted (principle)**; engine Open | All model access through gateway; local inference on host GPU outside sandboxes. Spike S6. |
| **017** | Storage & session log | **Accepted** (subject to AT-D-08, S7) | Core, session log, and audit commit in one transactional DB file; session archived on completion. |
| **018** | Operator auth | **Proposed** | Single local operator in V1. Auth mechanism open. |
