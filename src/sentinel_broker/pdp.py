"""Sentinel Policy Decision Point (CD-06, AT-C-01, AT-C-14, AT-B-10).
Fails closed outside the worker boundary, enforcing monotonic lease tokens and authorization rules.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sentinel_core.leases import LeaseManager
from sentinel_broker.tool_registry import ToolRegistry


@dataclass
class AuthorizationDecision:
    allowed: bool
    status_code: str
    reason: str


class PolicyDecisionPoint:
    def __init__(self, leases: LeaseManager, tool_registry: ToolRegistry):
        self.leases = leases
        self.tool_registry = tool_registry

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

        # 3. Policy Rule: IRREVERSIBLE tool authorization
        # By default, irreversible tools require an explicit flag in context
        ctx = context or {}
        if tool.effect_class.value == "IRREVERSIBLE" and not ctx.get("allow_irreversible", False):
            return AuthorizationDecision(
                allowed=False,
                status_code="REJECTED_IRREVERSIBLE_DENIED",
                reason=f"Irreversible tool '{tool_name}' requires explicit operator or context clearance.",
            )

        return AuthorizationDecision(
            allowed=True,
            status_code="APPROVED",
            reason="Tool invocation authorized by policy.",
        )
