"""Sentinel Core Database Schema.
Defines tables for state transitions, monotonic lease fencing, effect ledgers, and episodic memories.
"""
from __future__ import annotations

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    state TEXT NOT NULL CHECK(state IN ('Queued', 'Running', 'WaitingForApproval', 'Verifying', 'Succeeded', 'Failed', 'NeedsReconciliation', 'Cancelled')),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    failure_reason TEXT
);

CREATE TABLE IF NOT EXISTS task_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    reason TEXT NOT NULL,
    transition_ts REAL NOT NULL,
    FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS attempts (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    attempt_number INTEGER NOT NULL,
    lease_token INTEGER NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK(status IN ('Active', 'Committed', 'Aborted', 'FencedOut')),
    started_at REAL NOT NULL,
    finished_at REAL,
    FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS side_effect_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id TEXT NOT NULL,
    effect_class TEXT NOT NULL CHECK(effect_class IN ('READ_ONLY', 'IDEMPOTENT_WRITE', 'NON_IDEMPOTENT_WRITE', 'IRREVERSIBLE')),
    tool_name TEXT NOT NULL,
    intent_payload TEXT NOT NULL,
    outcome_payload TEXT,
    status TEXT NOT NULL CHECK(status IN ('INTENT_RECORDED', 'OUTCOME_RECORDED', 'FAILED')),
    created_at REAL NOT NULL,
    updated_at REAL,
    FOREIGN KEY(attempt_id) REFERENCES attempts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT,
    attempt_id TEXT,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    ts REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS mistake_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    attempt_id TEXT,
    error_category TEXT NOT NULL,
    error_signature TEXT NOT NULL,
    context TEXT NOT NULL,
    lesson_learned TEXT NOT NULL,
    ts REAL NOT NULL,
    FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS skills (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    code TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    verified_at REAL NOT NULL,
    metadata TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    current_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('Draft', 'Validating', 'Published', 'Deprecated', 'Revoked')),
    manifest_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_releases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    version TEXT NOT NULL,
    provenance_hash TEXT NOT NULL,
    manifest_snapshot TEXT NOT NULL,
    code_payload TEXT,
    published_at REAL NOT NULL,
    published_by TEXT NOT NULL,
    UNIQUE(agent_id, version),
    FOREIGN KEY(agent_id) REFERENCES agents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS dag_runs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    state TEXT NOT NULL CHECK(state IN ('Pending', 'Running', 'Succeeded', 'Failed', 'Cancelled')),
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    completed_at REAL,
    error TEXT
);

CREATE TABLE IF NOT EXISTS dag_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dag_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    goal TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    dependencies_json TEXT NOT NULL DEFAULT '[]',
    state TEXT NOT NULL CHECK(state IN ('Pending', 'Running', 'Succeeded', 'Failed', 'Skipped', 'Cancelled')),
    task_id TEXT,
    output_artifact TEXT,
    error TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(dag_id, step_id),
    FOREIGN KEY(dag_id) REFERENCES dag_runs(id) ON DELETE CASCADE
);

-- Indexes for rapid recovery and fencing queries
CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks(state);
CREATE INDEX IF NOT EXISTS idx_attempts_task_id ON attempts(task_id);
CREATE INDEX IF NOT EXISTS idx_attempts_lease ON attempts(lease_token);
CREATE INDEX IF NOT EXISTS idx_side_effects_attempt ON side_effect_ledger(attempt_id);
CREATE INDEX IF NOT EXISTS idx_mistakes_signature ON mistake_ledger(error_signature);
CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);
CREATE INDEX IF NOT EXISTS idx_agent_releases_agent ON agent_releases(agent_id, version);
CREATE INDEX IF NOT EXISTS idx_dag_steps_dag_id ON dag_steps(dag_id);
"""
