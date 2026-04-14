from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings


class LLMConfig(BaseSettings):
    model: str = "gpt-4o"
    api_key: str = ""
    api_base: str = "https://api.openai.com/v1"
    max_tokens: int = 4096
    temperature: float = 0.7

    model_config = {"env_prefix": "LLM_", "env_file": ".env", "env_file_encoding": "utf-8"}


class ContextConfig(BaseSettings):
    max_context_tokens: int = 200000
    l1_budget_ratio: float = 0.10
    l2_budget_ratio: float = 0.60
    l3_budget_ratio: float = 0.20
    reserve_ratio: float = 0.10

    model_config = {"env_prefix": "LIFEOPS_CONTEXT_", "env_file": ".env", "env_file_encoding": "utf-8"}


class AppConfig(BaseSettings):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    debug: bool = False
    log_level: str = "INFO"

    model_config = {"env_prefix": "LIFEOPS_", "env_file": ".env", "env_file_encoding": "utf-8"}

    @classmethod
    def from_yaml(cls, path: str | Path) -> "AppConfig":
        p = Path(path)
        if not p.exists():
            return cls()
        with open(p) as f:
            data = yaml.safe_load(f) or {}
        llm_data = data.pop("llm", {})
        context_data = data.pop("context", {})
        return cls(
            llm=LLMConfig(**llm_data),
            context=ContextConfig(**context_data),
            **data,
        )