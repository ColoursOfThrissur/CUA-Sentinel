"""Sentinel Web & HTTP Organs (R17, R19, R13).
Exposes safe broker-mediated web access tools to authorized agents with strict SSRF defense.
"""
from __future__ import annotations

import logging
from typing import Any

from sentinel_core.side_effects import EffectClass, SideEffectLedger
from sentinel_broker.tool_registry import ToolRegistry
from sentinel_broker.safe_http import SafeHTTPClient, SSRFViolationError, DomainAccessDeniedError

logger = logging.getLogger("SentinelWebOrgan")


def register_web_organs(
    registry: ToolRegistry,
    allowed_domains: list[str] | None = None,
    block_private_ips: bool = True,
    ledger: SideEffectLedger | None = None,
):
    """Binds broker_http_get tool into the Execution Broker tool registry."""
    client = SafeHTTPClient(
        allowed_domains=allowed_domains,
        block_private_ips=block_private_ips,
    )

    @registry.register(
        name="broker_http_get",
        description=(
            "Safely fetches public web resources (HTTP GET) with SSRF shielding, domain allowlisting, "
            "and bounded response buffers. Direct agent network access is denied; all requests route through the broker."
        ),
        effect_class=EffectClass.READ_ONLY,
        parameters_schema={
            "url": "str (fully-qualified http/https URL)",
            "headers": "dict | None (optional HTTP request headers)",
            "timeout_sec": "float | None (request timeout in seconds, default 10.0)",
            "max_bytes": "int | None (maximum bytes to read, default 2MB)",
        },
    )
    def broker_http_get(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        url = params.get("url", "")
        headers = params.get("headers")
        timeout = params.get("timeout_sec")
        max_bytes = params.get("max_bytes")

        if timeout is not None:
            try:
                timeout = float(timeout)
            except (ValueError, TypeError):
                timeout = 10.0

        if max_bytes is not None:
            try:
                max_bytes = int(max_bytes)
            except (ValueError, TypeError):
                max_bytes = 2_000_000

        try:
            res = client.get(
                url=url,
                headers=headers,
                timeout_sec=timeout,
                max_bytes=max_bytes,
            )

            # Record in side effect ledger if available
            if ledger and ctx.get("attempt_id"):
                try:
                    ledger.record_intent(
                        task_id=ctx.get("task_id", "unknown"),
                        attempt_id=ctx["attempt_id"],
                        effect_class=EffectClass.READ_ONLY,
                        tool_name="broker_http_get",
                        params={"url": url, "status_code": res.get("status_code")},
                        status="COMPLETED",
                    )
                except Exception as log_err:
                    logger.debug("Failed recording side effect for web get: %s", log_err)

            return res

        except (SSRFViolationError, DomainAccessDeniedError) as sec_err:
            logger.warning("Safe HTTP security block: %s", sec_err)
            return {
                "success": False,
                "status_code": 403,
                "url": url,
                "error": str(sec_err),
                "security_denied": True,
            }
        except Exception as e:
            logger.error("Safe HTTP error fetching '%s': %s", url, e)
            return {
                "success": False,
                "status_code": 0,
                "url": url,
                "error": str(e),
            }
