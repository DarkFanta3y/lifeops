from __future__ import annotations

import logging
import os
import warnings
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)

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


class SkillsConfig(BaseSettings):
    enabled: bool = True
    project_dir: str = ".lifeops/skills"
    user_dir: str = "~/.lifeops/skills"
    implicit_match_enabled: bool = True
    max_active: int = 3

    model_config = {
        "env_prefix": "LIFEOPS_SKILLS_",
        "env_file": _ENV_FILE,
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


class RAGConfig(BaseSettings):
    enabled: bool = True
    data_dirs: str = ".lifeops/knowledge"
    chroma_path: str = ".lifeops/chroma"
    collection: str = "lifeops_knowledge"
    model_cache_dir: str = "models"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    vector_top_k: int = 10
    bm25_top_k: int = 10
    rrf_top_k: int = 10
    reranker_model: str = "BAAI/bge-reranker-base"
    final_top_files: int = 3
    rrf_k: int = 60

    model_config = {
        "env_prefix": "LIFEOPS_RAG_",
        "env_file": _ENV_FILE,
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @property
    def data_dirs_list(self) -> list[str]:
        return [item.strip() for item in self.data_dirs.split(",") if item.strip()]

    @property
    def model_cache_path(self) -> str:
        path = Path(self.model_cache_dir).expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return str(path)


class MemoryConfig(BaseSettings):
    enabled: bool = True
    summary_top_k: int = 3
    preference_min_confidence: float = 0.7
    offload_dir: str = ".lifeops/offload"

    model_config = {
        "env_prefix": "LIFEOPS_MEMORY_",
        "env_file": _ENV_FILE,
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


class AppConfig(BaseSettings):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    serpapi: SerpApiConfig = Field(default_factory=SerpApiConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    rag: RAGConfig = Field(default_factory=RAGConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    history_path: str = ".lifeops/conversations.jsonl"
    db_path: str = ".lifeops/conversations.db"
    debug: bool = False
    log_level: str = "INFO"

    model_config = {
        "env_prefix": "LIFEOPS_",
        "env_file": _ENV_FILE,
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    def __getattribute__(self, name: str) -> object:
        if name == "history_path":
            warnings.warn(
                "history_path is deprecated, use db_path instead",
                DeprecationWarning,
                stacklevel=2,
            )
            logger.warning("history_path is deprecated, use db_path instead")
        return super().__getattribute__(name)
