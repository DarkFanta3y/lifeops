from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

_ENV_FILE = str(PROJECT_ROOT / ".env")

# 需要在启动时清除的代理环境变量，避免国内 API 被代理拦截
_PROXY_ENV_VARS = [
    "http_proxy",
    "https_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "all_proxy",
    "no_proxy",
    "NO_PROXY",
]


def clear_proxy_env() -> None:
    """清除代理环境变量，避免国内 API 被代理拦截导致 403 错误。"""
    for var in _PROXY_ENV_VARS:
        os.environ.pop(var, None)


class LLMConfig(BaseSettings):
    model: str = "glm-4-flash"
    api_key: str = ""
    api_base: str = "https://open.bigmodel.cn/api/paas/v4"
    max_tokens: int = 4096
    temperature: float = 0.7
    timeout: float = 60.0

    model_config = {
        "env_prefix": "LLM_",
        "env_file": _ENV_FILE,
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


class ContextConfig(BaseSettings):
    max_context_tokens: int = 200000
    l1_budget_ratio: float = 0.10
    l2_budget_ratio: float = 0.60
    l3_budget_ratio: float = 0.20
    reserve_ratio: float = 0.10

    model_config = {
        "env_prefix": "LIFEOPS_CONTEXT_",
        "env_file": _ENV_FILE,
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


class SerpApiConfig(BaseSettings):
    api_key: str = ""

    model_config = {
        "env_prefix": "SERPAPI_",
        "env_file": _ENV_FILE,
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


class MCPConfig(BaseSettings):
    enabled: bool = True
    default_transport: str = "stdio"
    servers: str = ""

    model_config = {
        "env_prefix": "LIFEOPS_MCP_",
        "env_file": _ENV_FILE,
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


class AppConfig(BaseSettings):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    serpapi: SerpApiConfig = Field(default_factory=SerpApiConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    debug: bool = False
    log_level: str = "INFO"

    model_config = {
        "env_prefix": "LIFEOPS_",
        "env_file": _ENV_FILE,
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }
