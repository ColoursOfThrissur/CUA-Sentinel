"""Sentinel Agent Registration and Lifecycle Management (Gate A: AT-A-01 to AT-A-06).
Governs agent manifest registration, provenance hashing, immutable release snapshots,
and fine-grained PDP capability enforcement.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from sentinel_core.db import SentinelDB

logger = logging.getLogger("SentinelAgentRegistry")


class AgentState(str, Enum):
    DRAFT = "Draft"
    VALIDATING = "Validating"
    PUBLISHED = "Published"
    DEPRECATED = "Deprecated"
    REVOKED = "Revoked"


class AgentLifecycleError(Exception):
    """Raised when an illegal agent lifecycle operation is attempted."""


class CapabilityViolationError(Exception):
    """Raised when an agent attempts to execute an unauthorized tool (AT-A-05)."""


@dataclass
class AgentManifest:
    """Agent Manifest defining identity, capabilities, and sandbox constraints (AT-A-01)."""
    agent_id: str
    name: str
    version: str
    description: str = ""
    author: str = "Sentinel Core"
    capabilities: list[str] = field(default_factory=list)
    allowed_organs: list[str] = field(default_factory=list)
    denied_tools: list[str] = field(default_factory=list)
    allow_irreversible: bool = False
    max_memory_mb: int = 100
    max_cpu_percent: float = 12.5

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentManifest:
        return cls(
            agent_id=data["agent_id"],
            name=data["name"],
            version=data["version"],
            description=data.get("description", ""),
            author=data.get("author", "Sentinel Core"),
            capabilities=data.get("capabilities", []),
            allowed_organs=data.get("allowed_organs", []),
            denied_tools=data.get("denied_tools", []),
            allow_irreversible=data.get("allow_irreversible", False),
            max_memory_mb=data.get("max_memory_mb", 100),
            max_cpu_percent=data.get("max_cpu_percent", 12.5),
        )

    def canonical_json(self) -> str:
        """Returns deterministic canonical JSON representation for hashing."""
        return json.dumps(self.to_dict(), sort_keys=True)


@dataclass
class AgentRelease:
    """Immutable release snapshot of a published agent (AT-A-03)."""
    id: int
    agent_id: str
    version: str
    provenance_hash: str
    manifest_snapshot: dict[str, Any]
    code_payload: str
    published_at: float
    published_by: str


def compute_provenance_hash(manifest: AgentManifest, code_payload: str = "") -> str:
    """Computes SHA256 canonical provenance hash over manifest and code (AT-A-02)."""
    hasher = hashlib.sha256()
    hasher.update(manifest.canonical_json().encode("utf-8"))
    if code_payload:
        hasher.update(b"\n---CODE---\n")
        hasher.update(code_payload.encode("utf-8"))
    return hasher.hexdigest()


class AgentRegistry:
    """Registry managing agent drafts, releases, and capability verification."""

    def __init__(self, db: SentinelDB):
        self.db = db

    def register_draft(self, manifest: AgentManifest) -> AgentManifest:
        """Registers a new agent draft or updates an existing draft (AT-A-01)."""
        now = time.time()
        existing = self.get_agent_record(manifest.agent_id)
        if existing and existing["status"] == AgentState.REVOKED.value:
            raise AgentLifecycleError(f"Cannot register draft for revoked agent '{manifest.agent_id}'")

        manifest_json = manifest.canonical_json()
        with self.db.transaction() as c:
            c.execute(
                """
                INSERT INTO agents (id, name, current_version, status, manifest_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    current_version = excluded.current_version,
                    status = CASE WHEN status = 'Published' THEN 'Draft' ELSE status END,
                    manifest_json = excluded.manifest_json,
                    updated_at = excluded.updated_at
                """,
                (manifest.agent_id, manifest.name, manifest.version, AgentState.DRAFT.value, manifest_json, now, now),
            )
        logger.info("Registered draft for agent '%s' v%s", manifest.agent_id, manifest.version)
        return manifest

    def publish_release(
        self,
        agent_id: str,
        version: str,
        code_payload: str = "",
        publisher: str = "operator",
    ) -> AgentRelease:
        """Publishes an immutable snapshot of an agent release (AT-A-02, AT-A-03, AT-A-04)."""
        existing = self.get_agent_record(agent_id)
        if not existing:
            raise AgentLifecycleError(f"Agent '{agent_id}' not found in registry")
        if existing["status"] == AgentState.REVOKED.value:
            raise AgentLifecycleError(f"Cannot publish release for revoked agent '{agent_id}'")

        # Check for duplicate immutable release (AT-A-03)
        existing_rel = self.get_release(agent_id, version)
        if existing_rel:
            raise AgentLifecycleError(f"Release '{agent_id}' v{version} already exists and is immutable (AT-A-03)")

        manifest = AgentManifest.from_dict(json.loads(existing["manifest_json"]))
        manifest.version = version
        prov_hash = compute_provenance_hash(manifest, code_payload)
        now = time.time()

        with self.db.transaction() as c:
            # 1. Record immutable release snapshot
            c.execute(
                """
                INSERT INTO agent_releases (agent_id, version, provenance_hash, manifest_snapshot, code_payload, published_at, published_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (agent_id, version, prov_hash, manifest.canonical_json(), code_payload, now, publisher),
            )
            rel_id = c.lastrowid

            # 2. Transition agent state to Published
            c.execute(
                """
                UPDATE agents
                SET current_version = ?, status = ?, manifest_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (version, AgentState.PUBLISHED.value, manifest.canonical_json(), now, agent_id),
            )

        logger.info("Published immutable release '%s' v%s (SHA256: %s)", agent_id, version, prov_hash[:12])
        return AgentRelease(
            id=rel_id,
            agent_id=agent_id,
            version=version,
            provenance_hash=prov_hash,
            manifest_snapshot=manifest.to_dict(),
            code_payload=code_payload,
            published_at=now,
            published_by=publisher,
        )

    def deprecate_agent(self, agent_id: str, reason: str = ""):
        """Marks an agent as deprecated."""
        now = time.time()
        with self.db.transaction() as c:
            c.execute("UPDATE agents SET status = ?, updated_at = ? WHERE id = ?", (AgentState.DEPRECATED.value, now, agent_id))
        logger.info("Agent '%s' deprecated: %s", agent_id, reason)

    def revoke_agent(self, agent_id: str, reason: str = ""):
        """Immediately revokes an agent, disallowing any further execution."""
        now = time.time()
        with self.db.transaction() as c:
            c.execute("UPDATE agents SET status = ?, updated_at = ? WHERE id = ?", (AgentState.REVOKED.value, now, agent_id))
        logger.warning("Agent '%s' REVOKED: %s", agent_id, reason)

    def get_agent_record(self, agent_id: str) -> dict[str, Any] | None:
        row = self.db.execute_one("SELECT * FROM agents WHERE id = ?", (agent_id,))
        return dict(row) if row else None

    def get_manifest(self, agent_id: str) -> AgentManifest | None:
        rec = self.get_agent_record(agent_id)
        if not rec:
            return None
        return AgentManifest.from_dict(json.loads(rec["manifest_json"]))

    def get(self, agent_id: str) -> AgentManifest | None:
        """Alias for get_manifest for dictionary-like access."""
        return self.get_manifest(agent_id)

    def get_release(self, agent_id: str, version: str) -> AgentRelease | None:
        row = self.db.execute_one(
            "SELECT * FROM agent_releases WHERE agent_id = ? AND version = ?",
            (agent_id, version),
        )
        if not row:
            return None
        return AgentRelease(
            id=row["id"],
            agent_id=row["agent_id"],
            version=row["version"],
            provenance_hash=row["provenance_hash"],
            manifest_snapshot=json.loads(row["manifest_snapshot"]),
            code_payload=row["code_payload"] or "",
            published_at=row["published_at"],
            published_by=row["published_by"],
        )

    def list_releases(self, agent_id: str) -> list[dict[str, Any]]:
        """Lists all immutable releases for a given agent ordered by published_at DESC."""
        rows = self.db.execute_read(
            "SELECT * FROM agent_releases WHERE agent_id = ? ORDER BY published_at DESC",
            (agent_id,),
        )
        result = []
        for r in rows:
            d = dict(r)
            if isinstance(d.get("manifest_snapshot"), str):
                try:
                    d["manifest_snapshot"] = json.loads(d["manifest_snapshot"])
                except Exception:
                    pass
            result.append(d)
        return result

    def list_agents(self, status: AgentState | None = None) -> list[dict[str, Any]]:
        """Lists registered agents with manifest and status (AT-A-06)."""
        if status:
            rows = self.db.execute_read("SELECT * FROM agents WHERE status = ? ORDER BY id ASC", (status.value,))
        else:
            rows = self.db.execute_read("SELECT * FROM agents ORDER BY id ASC")
        result = []
        for r in rows:
            d = dict(r)
            d["manifest"] = json.loads(d["manifest_json"])
            result.append(d)
        return result

    def validate_capability(
        self,
        agent_id: str,
        tool_name: str,
        is_irreversible: bool = False,
    ) -> tuple[bool, str]:
        """PDP outside gate check: verifies agent has authorization to invoke tool (AT-A-05)."""
        rec = self.get_agent_record(agent_id)
        if not rec:
            return False, f"Agent '{agent_id}' is not registered in Sentinel."

        if rec["status"] != AgentState.PUBLISHED.value:
            return False, f"Agent '{agent_id}' is in status '{rec['status']}'. Only 'Published' agents can invoke organs."

        manifest = AgentManifest.from_dict(json.loads(rec["manifest_json"]))

        # Check explicit denylist
        if tool_name in manifest.denied_tools:
            return False, f"Tool '{tool_name}' is explicitly denied in agent '{agent_id}' manifest."

        # Check allowed organs (allow wildcard '*', explicit tool name, or prefix wildcard like 'skill_*')
        allowed = False
        if "*" in manifest.allowed_organs:
            allowed = True
        elif tool_name in manifest.allowed_organs:
            allowed = True
        else:
            for pat in manifest.allowed_organs:
                if pat.endswith("*") and tool_name.startswith(pat[:-1]):
                    allowed = True
                    break

        if not allowed:
            return False, f"Tool '{tool_name}' is not in allowed_organs for agent '{agent_id}' (AT-A-05)."

        # Check irreversible permission
        if is_irreversible and not manifest.allow_irreversible:
            return False, f"Agent '{agent_id}' does not have allow_irreversible permission."

        return True, "AUTHORIZED"
