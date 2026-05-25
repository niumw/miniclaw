"""配置加载 — 读 miniclaw.toml"""

import os
import tomllib
from dataclasses import dataclass


@dataclass
class ProviderConfig:
    api_key: str = ""
    base_url: str = ""

    def get_api_key(self) -> str:
        return self.api_key or ""


@dataclass
class SystemConfig:
    prompt: str = ""


@dataclass
class MemoryConfig:
    db_path: str = "data/miniclaw.db"
    max_retrieve: int = 3
    token_budget: int = 1500


@dataclass
class ModelConfig:
    primary: str = ""  # 由 load_config 从 toml 或环境变量填充
    providers: dict[str, ProviderConfig] = None
    system: SystemConfig = None
    memory: MemoryConfig = None

    def __post_init__(self):
        if self.providers is None:
            self.providers = {}
        if self.system is None:
            self.system = SystemConfig()
        if self.memory is None:
            self.memory = MemoryConfig()

    def resolve(self, model_ref: str | None = None) -> tuple[str, str, ProviderConfig]:
        """'openai/glm-5.1' → ('openai', 'glm-5.1', provider_config)"""
        ref = model_ref or self.primary
        provider_id, model_id = ref.split("/", 1) if "/" in ref else (self.primary.split("/", 1)[0], ref)
        cfg = self.providers.get(provider_id, ProviderConfig())
        return provider_id, model_id, cfg


def load_config(path: str = "miniclaw.toml") -> ModelConfig:
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except FileNotFoundError:
        return ModelConfig()

    model_raw = raw.get("model", {})
    providers_raw = model_raw.pop("providers", {})

    providers = {}
    for name, vals in providers_raw.items():
        providers[name] = ProviderConfig(
            api_key=vals.get("api_key", ""),
            base_url=vals.get("base_url", ""),
        )

    # primary: toml > 环境变量 > 默认
    primary = model_raw.get("primary", "") or os.environ.get("MINICLAW_MODEL", "openai/glm-5.1")
    system_raw = raw.get("system", {})
    system_cfg = SystemConfig(
        prompt=system_raw.get("prompt", ""),
    )

    # 加载 [memory] 段
    memory_raw = raw.get("memory", {})
    memory_cfg = MemoryConfig(
        db_path=memory_raw.get("db_path", "data/miniclaw.db"),
        max_retrieve=memory_raw.get("max_retrieve", 3),
        token_budget=memory_raw.get("token_budget", 1500),
    )

    return ModelConfig(
        primary=primary,
        providers=providers,
        system=system_cfg,
        memory=memory_cfg,
    )
