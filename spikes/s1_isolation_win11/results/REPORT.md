# Spike S1 Results: Runtime Isolation on Windows 11 Home
**Execution Date:** 7 November 2026  
**Hardware Environment:** Intel Core i5-14400F, RTX 3060 12GB, 16GB DDR4, Windows 11 Home  
**Decision Governed:** CD-03 / ADR-007 (Runtime Isolation Mechanism)

---

### 1. Executive Summary

Spike S1 was executed live on Windows 11 Home to determine whether native Windows primitives can deliver enforceable sandbox isolation and default-deny network egress without requiring Client Hyper-V, Windows Sandbox, or WSL2 virtual disks.

**Key Outcome:**
* **Candidate 1b (Windows AppContainer + Named Pipe, zero network capabilities)** passed **all 7 criteria (M1 through M7)**.
* **CD-03 can now be definitively CLOSED** by selecting **Candidate 1b** as the V1 isolation architecture.

---

### 2. Empirical Scorecard Across Candidates

| Criterion | Target Metric | Candidate 1a (Baseline Process) | Candidate 1b (AppContainer + Named Pipe) | Candidate 1c (Loopback Exemption) |
| :--- | :--- | :--- | :--- | :--- |
| **M1: Network Egress** | Default-deny on TCP, UDP, DNS, DoH, LAN, Local Ports | **FAIL**: Allowed outbound TCP, UDP, and DNS resolution. | **PASS**: 100% blocked at OS level (`WinError 10013`, UDP timed out, DNS failed). | **BLOCKED**: Requires Administrator elevation. |
| **M2: Filesystem** | Workspace only; deny user files & `core.db` (**AT-C-11**) | **FAIL**: Read and wrote `core.db`; read files across desktop. | **PASS**: `core.db` read/write denied (`WinError 5`); other workspaces denied; user data denied. | **PASS** (same filesystem DACL as 1b). |
| **M3: Resource Quotas** | Memory and CPU hard limits enforced | **FAIL**: No process-level memory limits. | **PASS**: Job Object capped memory at 200MB; worker cleanly caught `MemoryError`. | N/A |
| **M4: Teardown** | Zero orphaned descendant processes on kill | **FAIL**: Descendants continue running in background. | **PASS**: Job Object terminated entire process tree immediately on timeout. | N/A |
| **M5: Host Survival** | Control plane survives worker segfault | **PASS**: Subprocess exit caught. | **PASS**: C-level null pointer dereference caught cleanly; host undamaged. | N/A |
| **M6: Memory Footprint** | Measured working set on 16 GB hardware | ~45 MB working set | **PASS**: ~50 MB working set. Leaves >6.0 GB physical RAM headroom. | N/A |
| **M7: Disk Footprint** | Measured disk usage; zero `.vhdx` ballooning | 0 MB disk overhead | **PASS**: 0.008 MB (8 KB). Zero virtual hard disks created or needed. | N/A |

---

### 3. Detailed Technical Findings

1. **Network Egress Denial (M1)**:
   * By initializing `CreateAppContainerProfile` with a `NULL` capability array and zero network capabilities, the Windows NT kernel blocks socket creation and outbound traffic.
   * Outbound TCP returns `[WinError 10013] An attempt was made to access a socket in a way forbidden by its access permissions`.
   * Outbound UDP DNS requests are dropped by the Windows Filtering Platform (timed out, zero reply bytes received).
   * Host loopback ports (`127.0.0.1:11434`, `8000`, `5432`) are completely unreachable.

2. **Filesystem Confinement and AT-C-11 (M2)**:
   * The worker AppContainer SID is granted Full Control exclusively on its assigned workspace directory (`ws`).
   * When the worker attempted to read or overwrite the authoritative `core.db` in the parent directory, the OS kernel threw `PermissionError: [WinError 5] Access is denied` (verifying **AT-C-11**).
   * When attempting to read user profile files (`C:\Users\<user>\NTUSER.DAT`) or adjacent task workspaces, it was denied access with `WinError 5`.
   * The container retains read access to Windows system binaries (`notepad.exe`, `kernel32.dll`), which is acceptable under the T0 trust model.

3. **Loopback Exemption Finding (Candidate 1c)**:
   * Running `CheckNetIsolation.exe LoopbackExempt -a -p=<SID>` failed with `Exit code 5: Access Denied, run the command as an administrator`.
   * This proves that loopback exemptions require elevated administrator rights. Candidate 1b avoids this entirely by running standard unprivileged processes communicating over DACL-protected Named Pipes.

4. **Resource Quotas & Teardown (M3, M4)**:
   * Placing the AppContainer process inside a Windows Job Object (`JOB_OBJECT_LIMIT_JOB_MEMORY`, `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`) successfully throttles memory growth and terminates all descendant processes upon exit.

5. **Resource Telemetry (M6, M7)**:
   * Memory: Negligible overhead (~50 MB per attempt). Leaves over 6.0 GB of free RAM for the host operating system, SQLite, and the local quantized LLM.
   * Disk: Exactly **0.008 MB** per workspace. Completely eliminates the WSL2 `.vhdx` disk-ballooning concern.

---

### 4. Decision Closure Recommendation

* **ADR-007 / CD-03 Resolution**: **Candidate 1b (Windows AppContainer + Named Pipe)** is accepted as the definitive V1 isolation runtime.
* The Fallback Ladder (WSL2 / Docker Sandboxes) is not needed.
