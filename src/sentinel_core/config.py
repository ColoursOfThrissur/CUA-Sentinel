"""Sentinel Configuration Management.
Provides structured configuration models, file persistence (YAML/JSON), and live updates.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class IterationLimits:
    max_attempts: int = 3
    attempt_timeout_sec: float = 25.0
    kill_window_sec: float = 2.0


@dataclass
class ResourceQuotas:
    memory_limit_mb: int = 100
    cpu_rate_percent: float = 12.5
    ram_floor_mb: int = 2500


@dataclass
class IsolationConfig:
    use_appcontainer: bool = True
    staging_runtime_dir: str = "spikes/s1_isolation_win11/staging_runtime"
    profile_prefix: str = "Sentinel.Attempt"


@dataclass
class StorageConfig:
    db_path: str = "data/sentinel_core.db"
    skills_dir: str = "skills"
    workspaces_dir: str = "workspaces"


@dataclass
class PolicyConfig:
    allow_irreversible: bool = False
    fail_closed_pdp: bool = True


@dataclass
class NetworkPolicyConfig:
    enabled: bool = True
    allowed_domains: list[str] = field(default_factory=lambda: [
        "*.github.com",
        "*.githubusercontent.com",
        "api.weather.gov",
        "*.weather.gov",
        "huggingface.co",
        "*.huggingface.co",
        "en.wikipedia.org",
        "*.wikipedia.org",
        "pypi.org",
        "*.pypi.org",
        "httpbin.org",
    ])
    block_private_ips: bool = True
    max_response_bytes: int = 2_000_000
    default_timeout_sec: float = 10.0


@dataclass
class LLMConfig:
    provider: str = "ollama"
    model: str = "qwen3.5:9b"
    endpoint: str = "http://127.0.0.1:11434"
    timeout_sec: float = 120.0
    temperature: float = 0.2
    repeat_penalty: float = 1.15
    num_predict: int = 1024


@dataclass
class SentinelConfig:
    environment: str = "development"
    log_level: str = "INFO"
    iteration_limits: IterationLimits = field(default_factory=IterationLimits)
    resource_quotas: ResourceQuotas = field(default_factory=ResourceQuotas)
    isolation: IsolationConfig = field(default_factory=IsolationConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    policy: PolicyConfig = field(default_factory=PolicyConfig)
    network_policy: NetworkPolicyConfig = field(default_factory=NetworkPolicyConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> SentinelConfig:
        p = Path(config_path) if config_path else Path("config.yaml")
        if not p.exists():
            return cls()

        content = p.read_text(encoding="utf-8")
        data = yaml.safe_load(content) or {}

        limits_data = data.get("iteration_limits", {})
        quotas_data = data.get("resource_quotas", {})
        iso_data = data.get("isolation", {})
        storage_data = data.get("storage", {})
        policy_data = data.get("policy", {})
        net_data = data.get("network_policy", {})
        llm_data = data.get("llm", {})

        return cls(
            environment=data.get("system", {}).get("environment", "development"),
            log_level=data.get("system", {}).get("log_level", "INFO"),
            iteration_limits=IterationLimits(**limits_data),
            resource_quotas=ResourceQuotas(**quotas_data),
            isolation=IsolationConfig(**iso_data),
            storage=StorageConfig(**storage_data),
            policy=PolicyConfig(**policy_data),
            network_policy=NetworkPolicyConfig(**net_data),
            llm=LLMConfig(**llm_data),
        )

    def save(self, config_path: str | Path | None = None):
        p = Path(config_path) if config_path else Path("config.yaml")
        data = {
            "system": {
                "environment": self.environment,
                "log_level": self.log_level,
            },
            "iteration_limits": asdict(self.iteration_limits),
            "resource_quotas": asdict(self.resource_quotas),
            "isolation": asdict(self.isolation),
            "storage": asdict(self.storage),
            "policy": asdict(self.policy),
            "network_policy": asdict(self.network_policy),
            "llm": asdict(self.llm),
        }
        p.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    def to_dict(self) -> dict[str, Any]:
        return {
            "environment": self.environment,
            "log_level": self.log_level,
            "iteration_limits": asdict(self.iteration_limits),
            "resource_quotas": asdict(self.resource_quotas),
            "isolation": asdict(self.isolation),
            "storage": asdict(self.storage),
            "policy": asdict(self.policy),
            "network_policy": asdict(self.network_policy),
            "llm": asdict(self.llm),
        }

    def update_from_dict(self, data: dict[str, Any]):
        if "iteration_limits" in data:
            for k, v in data["iteration_limits"].items():
                if hasattr(self.iteration_limits, k):
                    setattr(self.iteration_limits, k, v)
        if "resource_quotas" in data:
            for k, v in data["resource_quotas"].items():
                if hasattr(self.resource_quotas, k):
                    setattr(self.resource_quotas, k, v)
        if "isolation" in data:
            for k, v in data["isolation"].items():
                if hasattr(self.isolation, k):
                    setattr(self.isolation, k, v)
        if "policy" in data:
            for k, v in data["policy"].items():
                if hasattr(self.policy, k):
                    setattr(self.policy, k, v)
        if "network_policy" in data:
            for k, v in data["network_policy"].items():
                if hasattr(self.network_policy, k):
                    setattr(self.network_policy, k, v)
        if "llm" in data:
            for k, v in data["llm"].items():
                if hasattr(self.llm, k):
                    setattr(self.llm, k, v)
