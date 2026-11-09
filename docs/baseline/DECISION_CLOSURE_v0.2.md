# CUA-Sentinel V1 Architecture Decision Closure
**Version:** 0.3 · 9 November 2026 · **Status:** All Blocking Decisions Accepted (CD-01 through CD-07) · **Baseline:** Architecture Pack v0.2.3

This document closes, or fixes the exact procedure for closing, the decisions that block Stage 1. It adds no features and chooses no frameworks.

---

## 1. Decision Status Register

| ID | Decision | Status | Closes via | Proving Tests |
| :--- | :--- | :--- | :--- | :--- |
| **CD-01** | Execution topology and trust boundaries | **Accepted** | Approved 7 Nov 2026 | AT-B-01, AT-C-02, AT-C-08, AT-C-11 |
| **CD-02** | Agent code provenance and T0 enforcement | **Accepted** | Approved 7 Nov 2026 | AT-C-09, AT-C-12 |
| **CD-03** | Runtime isolation on Windows 11 Home | **Accepted** | Spike S1 Addendum (Candidate 1b) | AT-C-02, AT-C-08, failure-mode battery (M1–M8) |
| **CD-04** | Task state machine and effect/replay semantics | **Accepted (S2 to confirm)** | Approved 7 Nov 2026, then S2 | AT-B-03 to AT-B-10 |
| **CD-05** | Core store, session log and audit storage | **Accepted (S7 to confirm engine)** | Approved 7 Nov 2026, then S7 | AT-D-03, AT-D-08, AT-E-06 |
| **CD-06** | PDP, broker and model-gateway authorization | **Accepted (engine Open)** | Approved 7 Nov 2026, then S3 | AT-C-01, 05, 07, 10, AT-C-14 |
| **CD-07** | Secrets and credential injection | **Accepted (backend Open)** | Approved 7 Nov 2026 | AT-C-04, AT-C-06, AT-C-13 |

---

## 2. Summary of Key Invariants

1. **CD-01 (Option B)**: One isolated worker per attempt holding the agent implementation, its adapter, and low-risk tools. Privileged tools execute host-side through the Execution Broker.
2. **CD-02 (T0 Provenance)**: T0 code provenance is anchored on operator approval of the build record (source revision, packaged artifact hash, and dependency lockfile hash). Hash is re-verified at worker launch. Runtime downloads are prohibited.
3. **CD-03 (Isolation on Win 11 Home)**: Accepted. Windows AppContainer with DACL Named Pipe communication (`\\.\pipe\sentinel-worker-<attempt_id>`), no loopback exemption. Validated across M1–M8 in Spike S1 Addendum.
4. **CD-04 (Effect Classes & Replay)**: Explicit effect classes (Read-only, Idempotent write, Non-idempotent write, Irreversible). Intent logged before, outcome after. Monotonic lease tokens fencing out expired workers.
5. **CD-05 (Single Store File)**: Single SQLite file in WAL mode for core state, session log, and audit, enabling atomic transitions (`AT-D-08`). Single-writer control plane.
6. **CD-06 (Authorization & Sticky Labels)**: Outside PDP failing closed. Task labels are sticky; outputs inherit labels (`AT-C-14`); unlabelled sources refused.
7. **CD-07 (Broker-Side Secret Injection)**: Zero secrets in worker sandboxes or logs; canary tests (`AT-C-13`).
