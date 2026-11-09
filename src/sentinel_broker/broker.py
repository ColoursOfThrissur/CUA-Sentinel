"""Sentinel Execution Broker (CD-01, Option B).
Connects the worker IPC boundary to the Tool Registry, enforcing PDP policies and side-effect logging.
"""
from __future__ import annotations

import logging
from typing import Any

from sentinel_core.side_effects import SideEffectLedger
from sentinel_broker.pdp import PolicyDecisionPoint
from sentinel_broker.tool_registry import ToolRegistry

logger = logging.getLogger("SentinelBroker")


class ExecutionBroker:
    def __init__(
        self,
        pdp: PolicyDecisionPoint,
        tool_registry: ToolRegistry,
        side_effects: SideEffectLedger,
    ):
        self.pdp = pdp
        self.tool_registry = tool_registry
        self.side_effects = side_effects

    def dispatch_call(
        self,
        attempt_id: str,
        lease_token: int,
        tool_name: str,
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Dispatches an incoming worker tool call through the PDP and side-effect ledger."""
        ctx = context or {}

        # 1. PDP Authorization Gate
        decision = self.pdp.evaluate(attempt_id, lease_token, tool_name, params, ctx)
        if not decision.allowed:
            return {
                "status": decision.status_code,
                "allowed": False,
                "error": decision.reason,
                "result": None,
            }

        tool = self.tool_registry.get_tool(tool_name)
        assert tool is not None

        # 2. Record Intent BEFORE execution (AT-B-08)
        ledger_id = self.side_effects.record_intent(
            attempt_id=attempt_id,
            tool_name=tool_name,
            effect_class=tool.effect_class,
            intent_payload=params,
        )

        # 3. Execute Tool Host-Side
        try:
            result = self.tool_registry.execute_tool(tool_name, params, ctx)
            # 4. Record Outcome AFTER successful execution (AT-B-09)
            self.side_effects.record_outcome(ledger_id, result, success=True)
            return {
                "status": "SUCCESS",
                "allowed": True,
                "ledger_id": ledger_id,
                "result": result,
                "error": None,
            }
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            self.side_effects.record_outcome(ledger_id, {"error": error_msg}, success=False)
            return {
                "status": "TOOL_EXECUTION_ERROR",
                "allowed": True,
                "ledger_id": ledger_id,
                "result": None,
                "error": error_msg,
            }
