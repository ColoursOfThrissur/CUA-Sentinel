"""Sentinel Hybrid Model Gateway & Privacy Fence (R14 / AT-C-10).
Choreographs local-first GPU inference (Ollama) with guarded cloud escalation (Gemini),
hardware-locking private system tasks to local execution at the Policy Decision Point gate.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any

from sentinel_core.config import HybridGatewayConfig
from sentinel_core.llm_gateway import LLMGateway

logger = logging.getLogger("SentinelHybridGateway")


class HybridModelGateway:
    """Hybrid Model Gateway with an impermeable Privacy Fence."""
    gateway_type: str = "hybrid"

    # Regex patterns for detecting private host paths, system resources, and credentials
    PATH_PATTERNS = [
        re.compile(r"[A-Za-z]:[\\/]", re.IGNORECASE),  # C:\, G:/
        re.compile(r"(?:^|[\s\"'])(\.\.?[\\/]|/[a-zA-Z0-9_\.\-]+)", re.IGNORECASE),
        re.compile(r"\b(?:workspaces|appdata|temp|windows|system32|users|program files)\b", re.IGNORECASE),
        re.compile(r"\.(?:py|csv|json|md|obj|blend|exe|dll|db|sqlite|log|env|yaml|yml|bak|key|pem|secret)\b", re.IGNORECASE),
    ]

    NETWORK_PATTERNS = [
        re.compile(r"\b127\.0\.0\.1\b"),
        re.compile(r"\blocalhost\b", re.IGNORECASE),
        re.compile(r"\b192\.168\.\d+\.\d+\b"),
        re.compile(r"\b10\.\d+\.\d+\d+\b"),
        re.compile(r"\b172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+\b"),
    ]

    SYSTEM_KEYWORDS = [
        "my file", "my drive", "workspace", "local drive", "system drive",
        "c drive", "g drive", "process", "processes", "top ram", "top cpu",
        "task manager", "psutil", "system health", "appcontainer", "registry",
        "named pipe", "desktop organ", "mouse click", "keyboard type", "screen capture",
    ]

    def __init__(
        self,
        local_gateway: LLMGateway | None = None,
        config: HybridGatewayConfig | None = None,
        cloud_api_key: str | None = None,
    ) -> None:
        self.local = local_gateway or LLMGateway()
        self.cfg = config or HybridGatewayConfig()
        self.cloud_api_key = cloud_api_key or os.environ.get("GEMINI_API_KEY", "")

    @property
    def privacy_fence_enabled(self) -> bool:
        return self.cfg.privacy_fence_enabled

    @property
    def default_mode(self) -> str:
        return self.cfg.default_mode

    def is_cloud_available(self) -> bool:
        """Returns True if cloud API key is present."""
        return bool(self.cloud_api_key and self.cloud_api_key.strip())

    def is_local_available(self) -> bool:
        """Returns True if local Ollama daemon is reachable."""
        return self.local.is_available()

    def is_private_task(self, goal: str, context: str = "") -> bool:
        """Rule R14 / AT-C-10 Privacy Fence.
        Returns True if the goal or contextual data touches private files, host drives,
        local IP addresses, or system telemetry.
        """
        combined = f"{goal} {context}".lower()

        # 1. Drive letter and path checks
        for pat in self.PATH_PATTERNS:
            if pat.search(combined):
                return True

        # 2. Local network address checks
        for pat in self.NETWORK_PATTERNS:
            if pat.search(combined):
                return True

        # 3. System resource & host telemetry keywords
        for kw in self.SYSTEM_KEYWORDS:
            if kw in combined:
                return True

        return False

    def get_routing_decision(
        self,
        goal: str,
        context: str = "",
        mode: str | None = None,
    ) -> dict[str, Any]:
        """Evaluates Privacy Fence and returns explicit routing decision."""
        effective_mode = (mode or self.default_mode).lower()
        is_private = self.is_private_task(goal, context)
        cloud_avail = self.is_cloud_available()

        if is_private and self.privacy_fence_enabled:
            return {
                "decision": "local",
                "reason": "PRIVACY_FENCE_ENFORCED: Task touches private system data or host workspace. Cloud egress locked.",
                "is_private": True,
                "fence_triggered": True,
                "cloud_available": cloud_avail,
                "mode": effective_mode,
                "model": self.local.default_model,
            }

        if effective_mode == "cloud":
            if cloud_avail:
                return {
                    "decision": "cloud",
                    "reason": "OPERATOR_CLOUD_REQUEST: Explicit cloud mode requested and permitted by Privacy Fence.",
                    "is_private": False,
                    "fence_triggered": False,
                    "cloud_available": True,
                    "mode": "cloud",
                    "model": self.cfg.cloud_model,
                }
            else:
                return {
                    "decision": "local",
                    "reason": "CLOUD_UNAVAILABLE_FALLBACK: Cloud was requested but GEMINI_API_KEY is not configured.",
                    "is_private": False,
                    "fence_triggered": False,
                    "cloud_available": False,
                    "mode": "local",
                    "model": self.local.default_model,
                }

        if effective_mode == "auto":
            return {
                "decision": "local",
                "reason": "AUTO_HYBRID: Local-first GPU execution with speculative cloud escalation on failure.",
                "is_private": False,
                "fence_triggered": False,
                "cloud_available": cloud_avail,
                "mode": "auto",
                "model": self.local.default_model,
            }

        # Default local
        return {
            "decision": "local",
            "reason": "LOCAL_FIRST_DEFAULT: Sovereign execution via local GPU.",
            "is_private": is_private,
            "fence_triggered": False,
            "cloud_available": cloud_avail,
            "mode": "local",
            "model": self.local.default_model,
        }

    def generate(
        self,
        prompt: str,
        system: str | None = None,
        model: str | None = None,
        context: str = "",
        mode: str | None = None,
        temperature: float | None = None,
    ) -> str:
        """Executes generation through the routed provider with automatic fallback."""
        decision = self.get_routing_decision(prompt, context=context, mode=mode)

        if decision["decision"] == "cloud":
            try:
                logger.info("Executing via Cloud Gateway (%s)", self.cfg.cloud_model)
                return self._generate_cloud(prompt=prompt, system=system, model=self.cfg.cloud_model, temperature=temperature)
            except Exception as e:
                logger.warning("Cloud generation failed (%s). Falling back to local GPU.", e)
                return self.local.generate(prompt=prompt, system=system, model=model or self.local.default_model, temperature=temperature)

        # Local execution
        local_res = self.local.generate(prompt=prompt, system=system, model=model or self.local.default_model, temperature=temperature)

        # Auto-escalation check for complex prompts if cloud is permitted & available
        if (
            decision["mode"] == "auto"
            and not decision["fence_triggered"]
            and self.is_cloud_available()
            and len(prompt) > 80
            and len(local_res.strip()) < self.cfg.escalation_threshold_chars
        ):
            logger.info("Local response deficient (%d chars). Auto-escalating to cloud provider.", len(local_res))
            try:
                return self._generate_cloud(prompt=prompt, system=system, model=self.cfg.cloud_model, temperature=temperature)
            except Exception as e:
                logger.warning("Cloud auto-escalation failed: %s", e)

        return local_res

    def _generate_cloud(
        self,
        prompt: str,
        system: str | None = None,
        model: str = "gemini-1.5-flash",
        temperature: float | None = None,
    ) -> str:
        """Dispatches prompt to Google Gemini."""
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.cloud_api_key)
            gen_model = genai.GenerativeModel(
                model_name=model,
                system_instruction=system if system else None,
            )
            resp = gen_model.generate_content(
                prompt,
                generation_config={"temperature": temperature if temperature is not None else 0.2},
            )
            return resp.text.strip()
        except ImportError:
            raise RuntimeError("google-generativeai package is not installed.")
        except Exception as e:
            raise RuntimeError(f"Cloud generation error: {e}") from e
