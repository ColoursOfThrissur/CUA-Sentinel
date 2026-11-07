# Spike S1 Addendum: Revised Execution Plan
**Version:** 1.0 · **Timestamp:** 2026-11-07T22:49:00+05:30 · **Status:** Frozen for execution  
**Governs:** CD-03 / ADR-007 (Runtime Isolation on Windows 11 Home)  
**Baseline:** Architecture Pack v0.2.3, Decision Closure v0.2, S1 Initial Results of 7 Nov 2026

This plan replaces the earlier addendum outline. It repairs the probes that produced invalid evidence, adds the checks that were never run, and fixes the rules for what counts as a pass before any code executes.

---

## 1. Frozen Parameters Before Running

The following parameters are frozen on record prior to the execution of Phase A0:

| Item | Frozen Value | Metric / Tooling | Status |
| :--- | :--- | :--- | :--- |
| **RAM Floor** | $\ge 2.5\text{ GB}$ available at peak | Windows `Available MBytes` counter (`psutil.virtual_memory().available`) | **Frozen** |
| **Kill Window** | All descendants terminated within $2.0\text{ s}$; none alive at $30\text{ s}$ | PIDs and process creation times checked against OS process table | **Frozen** |
| **CPU Target** | $12.5\%$ of total system CPU | Hardware has 16 logical processors (i5-14400F); $12.5\%$ corresponds to 2 logical threads | **Frozen** |
| **CPU Tolerance** | Measured CPU within $\pm 10\%$ of target ($11.25\% - 13.75\%$) | Sampled over a 30-second sustained worker load window | **Frozen** |
| **Repeats** | $\ge 3$ consecutive executions per vector | Deterministic repeatability across attempts | **Frozen** |

---

## 2. What Counts as a Pass (The 3-Condition Invariant)

A vector is classified as **Pass** if and only if all three conditions are satisfied:
1. **Unrestricted Control**: The unisolated control runs the identical payload from the same runtime copy/location and is verified **ALLOWED**.
2. **Positive Control**: A positive control inside the AppContainer proves the capability functions when explicitly granted (e.g., granting `internetClient` enables outbound connection; granting read ACE to the container SID on the canary file enables reading).
3. **Candidate 1b (Blocked)**: Candidate 1b (zero capabilities, DACL-confined workspace) is verified **BLOCKED** with a distinguishable OS error (e.g., `WinError 10013` or `WinError 5`), distinct from environment failure or timeout.

If any condition fails:
* If the control is blocked or fails: **Invalid probe**.
* If a vector cannot be constructed due to OS constraints (e.g., symlinks requiring ungranted privileges): **Not testable**.
* Timeouts count as a block **only** if the identical timeout configuration against a live canary listener in the control succeeds.

*Note on Controls:*
* **Control (Unrestricted)**: Plain host process running payload from the staging runtime.
* **1a-prime (Low-Integrity)**: Spawned with a low-integrity token to document baseline read leakage.

---

## 3. Execution Phases

| Phase | Title & Scope | Pass Criteria |
| :--- | :--- | :--- |
| **A0** | **Harness & Probe Repair**<br>Deploy live host listeners: Loopback TCP (`127.0.0.1:<port>`), Host LAN IP TCP (`<LAN_IP>:<port>`, non-0.0.0.0), UDP echo, and local HTTP proxy. Add ICMP, IPv6, and `HTTP_PROXY` env vars. Plant canary files for direct read, traversal (`..\`), directory junctions (`mklink /J`), and symlinks. Implement hard crash (`faulthandler._sigsegv()`). Implement PID-tracked children. | Control ALLOWED on every vector.<br>Positive control ALLOWED on every vector.<br>Candidate 1b BLOCKED on every vector.<br>Zero descendants alive after kill. Crash identified by NTSTATUS exit code. |
| **A1** | **Dedicated Staging Runtime (M8 / CD-02)**<br>Deploy a dedicated Python runtime copy in an immutable staging directory. Hash-verify runtime at launch. Grant read/execute access solely to the specific container SID (never `S-1-15-2-1`). | Verified runtime launches inside container with working TLS support. A 1-byte modification of the runtime binary is refused at launch (`AT-C-12`). |
| **A2** | **TLS and DoH Vectors**<br>Execute HTTPS and DNS-over-HTTPS probes using the verified TLS-enabled runtime. | Control and positive control succeed; Candidate 1b is BLOCKED. |
| **A3** | **DACL Named Pipe Transport**<br>Create a native Windows Named Pipe (`\\.\pipe\sentinel-worker-<attempt_id>`) with `FILE_FLAG_FIRST_PIPE_INSTANCE`, `PIPE_REJECT_REMOTE_CLIENTS`, and a DACL granting access solely to that attempt's container SID. Implement minimal RPC protocol (heartbeat, echo, tool call stub with lease token). Verify inherited handles. | Assigned worker connects.<br>Worker from another container is DENIED.<br>Non-AppContainer process of the same user is DENIED.<br>Disconnect mid-message and oversize payloads handled cleanly.<br>Zero unexpected handles inherited. |
| **A4** | **Resource Quotas & Teardown (M3 & M4)**<br>Enforce 12.5% CPU hard cap, unhandled memory bomb, process count limit, and wall-clock timeout. Test child process `CREATE_BREAKAWAY_FROM_JOB`. Execute hard crash (0xC0000005). | Memory cap enforced without process cooperation.<br>CPU within $\pm 10\%$ over 30s.<br>Breakaway child captured/killed.<br>Teardown within 2.0s; 0 alive at 30s. |
| **A5** | **Windows Channel Boundaries**<br>Probe Windows desktop/session channels: Clipboard access (`OpenClipboard`), Registry (`HKCU` read/write), Window messages (`FindWindow`, `PostMessage`), `OpenProcess` on harness PID, named kernel object namespace (`Global\`, `Local\`), and environment variable leakage. | Each attempt is BLOCKED or explicitly cataloged as an architectural finding. |
| **A6** | **Profile Churn & Artifact Leak Audit (M7)**<br>Execute 50 consecutive `create -> run -> destroy` cycles. Compare ephemeral per-attempt profiles against a single reused profile. Audit registry (`AppContainer\Storage`), leftover directory ACEs, named pipes, and orphan processes. | Zero leftover profiles or handles.<br>Workspace disk returns to baseline within $1\text{ MB}$.<br>Zero virtual disks. |
| **A7** | **Full Envelope Telemetry (M6)**<br>Run 10-minute sustained load with full envelope: Control Plane stub + SQLite in WAL mode + Model Gateway stub / Ollama loaded with quantized 7B model + 1 active worker under load. | Available physical RAM stays $\ge 2.5\text{ GB}$ at peak.<br>Zero sustained pagefile growth. |
| **A8** | **Candidate 1c & Final Report**<br>Document 1c loopback elevation requirement. Compile final matrix: `Vector`, `Control`, `Positive Control`, `Candidate 1b`, `Result` (`Pass` / `Fail` / `Invalid probe` / `Not testable`). | Comprehensive evidence report closing CD-03. |

---

## 4. Resource and Teardown Details (A4)
* **Memory**: Unhandled exponential allocation loop (does not catch `MemoryError`). Job Object limit applied prior to execution. Control must run safely up to a configured test ceiling.
* **CPU Rate Control**: Hard cap set to $12.5\%$ ($1250$ in `JOB_OBJECT_CPU_RATE_CONTROL_INFORMATION`). Measured with Windows performance counters over 30 seconds.
* **Hard Crash**: Deliberate native crash via `faulthandler._sigsegv()` or stack recursion without exception handling. Verifies harness captures exit code `0xC0000005` (or NTSTATUS `0xC000xxxx`).
* **Process Tracking**: Children spawn with 300s sleep. Manifest logs PID and process creation timestamp (`psutil.Process(pid).create_time()`). Harness asserts that no process with matching PID and creation time exists after the 2.0s kill window. Job object limits do not permit breakaway.

---

## 5. Rules for the M6 Result
* Isolation and worker memory overhead must be separated from model footprint.
* If available RAM falls below $2.5\text{ GB}$ because the host OS plus the loaded 7B model alone consume the budget before worker launch, that is recorded as a **System Hardware Constraint**, not an isolation failure.
* Baseline physical RAM is logged immediately prior to model load and prior to worker launch.

---

## 6. Process Safeguards
* **Process Management**: Terminate strictly by PID or Job Object Handle. Global process kill commands (e.g. `Stop-Process -Name python`) are prohibited.
* **Canary Files**: All filesystem tests target synthetic files in designated canary directories. No user data is targeted.
* **DACL Scoping**: Permissions are granted strictly to the specific AppContainer SID. Use of `S-1-15-2-1` (`ALL APPLICATION PACKAGES`) is prohibited.
* **No Global Mutations**: Zero persistent modifications to system directories or global Python installations. Any temporary test change outside the spike root must have an automated revert script and audit log.
* **Raw Artifacts**: All test run outputs (passing and failing) are preserved in `spikes/s1_isolation_win11/results/`.
* **Unprivileged Execution**: If any harness component requires Administrator elevation, execution halts and reports.

---

## 7. Decision Closure Rules
* **Acceptance**: If Phases A0 through A7 pass with valid controls, Candidate 1b is formally proposed for acceptance to close **CD-03 / ADR-007**.
* **Immediate Fallback**: If M1 (Network), M2 (Filesystem), or M5 (Host Survival) fail, halt and trigger the Fallback Ladder (WSL2 / Docker Sandboxes).
* **Fix & Retry**: If M3, M4, M6 (isolation-attributable), M7, or M8 fail, allow exactly one fix-and-retry cycle before triggering the fallback ladder.
* **Timebox**: Two focused execution sessions. If Phase A0 cannot produce valid controls, halt and report.
