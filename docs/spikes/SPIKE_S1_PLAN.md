# Stage 0 Plan — Spike S1: Native Windows Runtime Isolation (AppContainer)
**Version:** 1.0 · 7 November 2026 · **Status:** Draft for execution  
**Baseline:** Architecture Pack v0.2.3, Decision Closure v0.2 (CD-03)

---

### 1. Problem and Scope
Windows 11 Home lacks official support for Windows Sandbox and Client Hyper-V. Furthermore, virtualized environments (WSL2 / Docker Desktop) introduce disk footprint and image-ballooning concerns. 

Spike S1 tests whether native Windows isolation primitives—specifically **Windows AppContainers** communicating over a DACL-restricted **Named Pipe**—can satisfy the V1 isolation requirements on the target hardware (i5-14400F, RTX 3060 12 GB, 16 GB DDR4, Windows 11 Home) without virtual machine overhead or disk growth.

#### Residual Risk and Trust Boundary (CD-01 / CD-03)
AppContainers share the host NT kernel. A kernel vulnerability or unpatched driver exploit could allow sandbox escape. This is an explicitly accepted residual risk for **T0-only V1 execution** (first-party approved code with recorded provenance). If T1 (reviewed external) or T2 (untrusted third-party) code is ever admitted in future milestones, a VM-grade hypervisor boundary becomes mandatory.

---

### 2. Candidates Under Evaluation
1. **Candidate 1a (Low-Integrity Baseline)**:
   * Low Integrity Token + Windows Job Object.
   * Purpose: Confirm baseline read-leakage flaw (cannot write to Medium/High, but can read host files).
2. **Candidate 1b (AppContainer + Named Pipe - Primary)**:
   * AppContainer profile (`CreateAppContainerProfile`) with zero network capabilities (`NULL` capability array).
   * DACL-restricted workspace folder.
   * IPC via Windows Named Pipe (`\\.\pipe\sentinel-worker-<attempt_id>`) with container SID DACL.
   * Zero network sockets inside container; loopback closed.
3. **Candidate 1c (AppContainer + Loopback Exemption - Comparative)**:
   * Same as 1b, but with `CheckNetIsolation.exe LoopbackExempt` enabled.
   * Purpose: Demonstrate loopback exposure to local services (model gateway, DB listeners, dev servers).
4. **Fallback Ladder (WSL2 & Docker Sandboxes)**:
   * Evaluated only if Candidate 1b fails M1, M2, or M5.
   * Evaluates sparse VHDX flags (`wsl --manage <Distro> --set-sparse true`) to test disk containment.

---

### 3. Evaluation Criteria (M1 through M7)
* **M1: Default-Deny Egress**: Outbound TCP, UDP, DNS (53), DoH (443), ICMP, IPv6, proxy env vars, RFC 1918 LAN, and unauthorized local host ports. (Pass: all fail/drop).
* **M2: Filesystem Confinement**: Access to user profile data, other task workspaces, traversal (`..\..\`), junctions/symlinks, and **AT-C-11** (`core.db`). (Pass: access denied outside workspace).
* **M3: Resource Quotas**: Memory allocation leak loop, 100% CPU on all cores, wall-clock timeout. (Pass: Job Object caps enforced cleanly).
* **M4: Clean Teardown**: Worker spawns stubborn child processes and holds locks. (Pass: Job Object kills entire process tree cleanly).
* **M5: Control Plane Survival**: Worker segfaults, memory bombs, or aborts. (Pass: Host harness survives intact).
* **M6: Measured Memory Footprint**: Empirically measure working set RAM across idle, loaded model, and active worker. (Pass: Leaves stable physical RAM buffer on 16 GB hardware).
* **M7: Measured Disk Footprint**: Measure base install size, per-task workspace overhead, and disk growth over 50 cycles. (Pass: No multi-gigabyte virtual disks).
