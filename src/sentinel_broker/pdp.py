"""Sentinel Policy Decision Point (CD-06, AT-C-01, AT-C-14, AT-B-10).
Fails closed outside the worker boundary, enforcing monotonic lease tokens and authorization rules.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sentinel_core.leases import LeaseManager
from sentinel_broker.tool_registry import ToolRegistry
from sentinel_core.agent_registry import AgentRegistry


@dataclass
class AuthorizationDecision:
    allowed: bool
    status_code: str
    reason: str
    requires_approval: bool = False


class PolicyDecisionPoint:
    def __init__(
        self,
        leases: LeaseManager,
        tool_registry: ToolRegistry,
        agent_registry: AgentRegistry | None = None,
        allowed_domains: list[str] | None = None,
        allowed_workspaces_dir: str | Path | None = None,
    ):
        self.leases = leases
        self.tool_registry = tool_registry
        self.agent_registry = agent_registry
        self.allowed_domains = allowed_domains
        self.allowed_workspaces_dir = Path(allowed_workspaces_dir).resolve() if allowed_workspaces_dir else None

    def evaluate(
        self,
        attempt_id: str,
        lease_token: int,
        tool_name: str,
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> AuthorizationDecision:
        # 1. Monotonic Lease Check (AT-B-10)
        if not self.leases.is_lease_valid(attempt_id, lease_token):
            return AuthorizationDecision(
                allowed=False,
                status_code="REJECTED_STALE_LEASE",
                reason=f"Lease token {lease_token} for attempt {attempt_id} is stale, fenced out, or terminated.",
            )

        # 2. Tool Existence Check
        tool = self.tool_registry.get_tool(tool_name)
        if not tool:
            return AuthorizationDecision(
                allowed=False,
                status_code="REJECTED_UNKNOWN_TOOL",
                reason=f"Tool '{tool_name}' is not registered in the broker tool catalog.",
            )

        ctx = context or {}
        is_irreversible = tool.effect_class.value == "IRREVERSIBLE"

        # 3. Gate A: Agent Capability & Manifest Check (AT-A-05)
        agent_id = ctx.get("agent_id")
        if agent_id and self.agent_registry:
            authorized, reason = self.agent_registry.validate_capability(
                agent_id=agent_id,
                tool_name=tool_name,
                is_irreversible=is_irreversible,
            )
            if not authorized:
                return AuthorizationDecision(
                    allowed=False,
                    status_code="REJECTED_CAPABILITY_NOT_GRANTED",
                    reason=reason,
                )

        # 4. Policy Rule: IRREVERSIBLE tool authorization
        if is_irreversible and not ctx.get("allow_irreversible", False):
            if ctx.get("enable_hitl", False):
                return AuthorizationDecision(
                    allowed=False,
                    status_code="REQUIRES_APPROVAL",
                    reason=f"Irreversible tool '{tool_name}' requires operator approval.",
                    requires_approval=True,
                )
            return AuthorizationDecision(
                allowed=False,
                status_code="REJECTED_IRREVERSIBLE_DENIED",
                reason=f"Irreversible tool '{tool_name}' requires explicit operator or context clearance.",
            )

        # 5. Network Egress Policy Check (R17, R19)
        if tool_name == "broker_http_get" and self.allowed_domains is not None:
            import fnmatch
            import urllib.parse
            url = params.get("url", "")
            hostname = (urllib.parse.urlparse(url).hostname or "").lower()
            allowed = False
            for pat in self.allowed_domains:
                p = pat.lower()
                if p == "*" or p == "*.*" or fnmatch.fnmatch(hostname, p):
                    allowed = True
                    break
                if p.startswith("*.") and hostname == p[2:]:
                    allowed = True
                    break
            if not allowed:
                return AuthorizationDecision(
                    allowed=False,
                    status_code="REJECTED_DOMAIN_NOT_ALLOWED",
                    reason=f"PDP Egress Policy: Domain '{hostname}' is not in allowed_domains list.",
                )

        # 6. Workspace Path Isolation Check (Fail-closed outside workspace for writes)
        if self.allowed_workspaces_dir is not None:
            write_path_keys = [
                "output_path",
                "output_obj_path",
                "output_csv_path",
                "output_artifact_path",
                "target_path",
                "dest_path",
                "destination",
            ]
            tool = self.tool_registry.get_tool(tool_name)
            is_write_tool = tool and tool.effect_class.value != "READ_ONLY"
            if is_write_tool:
                for key in write_path_keys:
                    val = params.get(key)
                    if val and isinstance(val, (str, Path)):
                        try:
                            resolved_val = Path(val).resolve()
                            if not (resolved_val == self.allowed_workspaces_dir or self.allowed_workspaces_dir in resolved_val.parents):
                                return AuthorizationDecision(
                                    allowed=False,
                                    status_code="REJECTED_WRITE_OUTSIDE_WORKSPACE",
                                    reason=f"PDP Storage Boundary: Target write path '{val}' resolves outside permitted workspace '{self.allowed_workspaces_dir}'.",
                                )
                        except Exception as e:
                            return AuthorizationDecision(
                                allowed=False,
                                status_code="REJECTED_INVALID_PATH",
                                reason=f"PDP Storage Boundary: Invalid path format '{val}': {e}",
                            )

        return AuthorizationDecision(
            allowed=True,
            status_code="APPROVED",
            reason="Tool invocation authorized by policy.",
        )
