"""模型提供商注册表：本地 JSON 持久化、密钥脱敏与当前模型解析。

提供商配置独立于 `.env` 存放，便于在 Web 控制台中管理多家兼容
OpenAI / Anthropic 协议的网关；API 密钥只在本地文件与运行时使用，
接口响应永远不返回明文。
"""

from __future__ import annotations

import json
import os
import shutil
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from lifeops.utils.logging import get_logger

logger = get_logger(__name__)

ModelProtocol = Literal["openai_chat", "openai_responses", "anthropic_messages"]

PROTOCOL_LABELS: dict[str, str] = {
    "openai_chat": "OpenAI Chat Completions",
    "openai_responses": "OpenAI Responses",
    "anthropic_messages": "Anthropic Messages",
}

PROVIDER_ID_PATTERN = r"^[a-z][a-z0-9_-]{0,63}$"


class ModelRegistryError(Exception):
    """注册表业务错误，status_code 供 API 直接映射为 HTTP 状态码。"""

    def __init__(self, message: str, status_code: int = 422) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class ModelEntry(BaseModel):
    model_id: str = Field(max_length=200)
    name: str = Field(default="", max_length=200)
    context_window: int | None = Field(default=None, ge=1, le=10_000_000)
    max_output_tokens: int | None = Field(default=None, ge=1, le=1_000_000)

    model_config = {"str_strip_whitespace": True}

    @field_validator("model_id")
    @classmethod
    def validate_model_id(cls, value: str) -> str:
        if not value:
            raise ValueError("模型 ID 不能为空")
        if any(char.isspace() for char in value):
            raise ValueError("模型 ID 不能包含空白字符")
        return value

    @model_validator(mode="after")
    def fill_display_name(self) -> "ModelEntry":
        if not self.name:
            self.name = self.model_id
        return self


class ProviderDraft(BaseModel):
    provider_id: str
    name: str = Field(max_length=100)
    api_base: str = Field(max_length=2000)
    protocol: ModelProtocol = "openai_chat"
    api_key: str = Field(default="", max_length=10000)
    models: list[ModelEntry] = Field(default_factory=list)

    model_config = {"str_strip_whitespace": True}

    @field_validator("provider_id")
    @classmethod
    def validate_provider_id(cls, value: str) -> str:
        import re

        if not re.fullmatch(PROVIDER_ID_PATTERN, value):
            raise ValueError("Provider ID 必须以小写字母开头，且只含小写字母、数字、下划线或连字符")
        return value

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value:
            raise ValueError("显示名称不能为空")
        return value

    @field_validator("api_base")
    @classmethod
    def validate_api_base(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("API 地址必须是 http(s) 开头的完整地址")
        return value

    @field_validator("api_key")
    @classmethod
    def trim_api_key(cls, value: str) -> str:
        return value.strip()


class ProviderRecord(ProviderDraft):
    created_at: str = ""
    updated_at: str = ""


class ActiveModel(BaseModel):
    provider_id: str
    model_id: str


class RegistryState(BaseModel):
    version: int = 1
    providers: list[ProviderRecord] = Field(default_factory=list)
    active: ActiveModel | None = None


@dataclass(frozen=True)
class ResolvedModel:
    provider_id: str
    provider_name: str
    protocol: ModelProtocol
    api_base: str
    api_key: str
    model_id: str
    model_name: str
    context_window: int | None = None
    max_output_tokens: int | None = None


def api_key_hint(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) >= 8:
        return f"••••{api_key[-4:]}"
    return "••••"


class ModelRegistry:
    """线程安全的模型提供商存储。所有写操作都会原子替换本地 JSON。"""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).expanduser()
        self._lock = threading.RLock()
        self._state: RegistryState | None = None

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> RegistryState:
        with self._lock:
            if self._state is not None:
                return self._state
            if not self._path.exists():
                self._state = RegistryState()
                return self._state
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                self._state = RegistryState.model_validate(raw)
            except (OSError, json.JSONDecodeError, ValidationError) as exc:
                backup = self._path.with_name(
                    f"{self._path.name}.corrupt-{datetime.now():%Y%m%d%H%M%S}"
                )
                try:
                    shutil.copy2(self._path, backup)
                except OSError:
                    backup = None
                logger.error("模型配置文件无法解析，已使用空配置：%s（备份：%s）", exc, backup)
                self._state = RegistryState()
            return self._state

    def _save(self, state: RegistryState) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(f".{self._path.name}.{os.getpid()}.tmp")
        payload = json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
        temporary.write_text(payload, encoding="utf-8")
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, self._path)
        self._state = state

    @staticmethod
    def _public_provider(provider: ProviderRecord) -> dict[str, Any]:
        data = provider.model_dump(exclude={"api_key"})
        data["has_api_key"] = bool(provider.api_key)
        data["api_key_hint"] = api_key_hint(provider.api_key)
        return data

    def list_providers(self) -> list[dict[str, Any]]:
        with self._lock:
            state = self._load()
            providers = sorted(state.providers, key=lambda item: item.created_at)
            return [self._public_provider(provider) for provider in providers]

    def get_provider(self, provider_id: str) -> ProviderRecord | None:
        with self._lock:
            state = self._load()
            return next(
                (provider for provider in state.providers if provider.provider_id == provider_id),
                None,
            )

    def public_provider(self, provider_id: str) -> dict[str, Any] | None:
        with self._lock:
            provider = self.get_provider(provider_id)
            return self._public_provider(provider) if provider is not None else None

    def create_provider(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            draft = ProviderDraft.model_validate(payload)
        except ValidationError as exc:
            raise ModelRegistryError(_validation_message(exc)) from exc
        with self._lock:
            state = self._load()
            if any(item.provider_id == draft.provider_id for item in state.providers):
                raise ModelRegistryError(f"提供商 '{draft.provider_id}' 已存在", status_code=409)
            now = _now()
            record = ProviderRecord(**draft.model_dump(), created_at=now, updated_at=now)
            state = state.model_copy(update={"providers": [*state.providers, record]})
            self._save(state)
            return self._public_provider(record)

    def update_provider(self, provider_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            state = self._load()
            index = next(
                (
                    position
                    for position, provider in enumerate(state.providers)
                    if provider.provider_id == provider_id
                ),
                None,
            )
            if index is None:
                raise ModelRegistryError("提供商不存在", status_code=404)
            current = state.providers[index]
            merged = current.model_dump()
            for key, value in payload.items():
                if key in {"provider_id", "created_at", "updated_at"}:
                    continue
                if value is None:
                    continue
                merged[key] = value
            try:
                draft = ProviderDraft.model_validate(merged)
            except ValidationError as exc:
                raise ModelRegistryError(_validation_message(exc)) from exc
            updated = ProviderRecord(
                **draft.model_dump(),
                created_at=current.created_at,
                updated_at=_now(),
            )
            providers = [*state.providers]
            providers[index] = updated
            active = state.active
            if active is not None and active.provider_id == provider_id:
                if not any(model.model_id == active.model_id for model in updated.models):
                    active = None
            self._save(state.model_copy(update={"providers": providers, "active": active}))
            return self._public_provider(updated)

    def delete_provider(self, provider_id: str) -> bool:
        with self._lock:
            state = self._load()
            providers = [
                provider for provider in state.providers if provider.provider_id != provider_id
            ]
            if len(providers) == len(state.providers):
                return False
            active = state.active
            if active is not None and active.provider_id == provider_id:
                active = None
            self._save(state.model_copy(update={"providers": providers, "active": active}))
            return True

    def active_public(self) -> dict[str, Any] | None:
        with self._lock:
            state = self._load()
            if state.active is None:
                return None
            provider = self._provider_by_id(state, state.active.provider_id)
            if provider is None:
                return None
            model = next(
                (item for item in provider.models if item.model_id == state.active.model_id), None
            )
            if model is None:
                return None
            return {
                "provider_id": provider.provider_id,
                "provider_name": provider.name,
                "model_id": model.model_id,
                "model_name": model.name,
                "protocol": provider.protocol,
                "context_window": model.context_window,
                "max_output_tokens": model.max_output_tokens,
            }

    @staticmethod
    def _provider_by_id(state: RegistryState, provider_id: str) -> ProviderRecord | None:
        return next(
            (provider for provider in state.providers if provider.provider_id == provider_id),
            None,
        )

    def set_active(self, provider_id: str, model_id: str) -> dict[str, Any]:
        with self._lock:
            state = self._load()
            provider = self._provider_by_id(state, provider_id)
            if provider is None:
                raise ModelRegistryError("提供商不存在", status_code=404)
            if not any(model.model_id == model_id for model in provider.models):
                raise ModelRegistryError("模型不在该提供商的模型目录中", status_code=422)
            active = ActiveModel(provider_id=provider_id, model_id=model_id)
            self._save(state.model_copy(update={"active": active}))
            return self.active_public() or {}

    def clear_active(self) -> None:
        with self._lock:
            state = self._load()
            if state.active is not None:
                self._save(state.model_copy(update={"active": None}))

    def resolve_active(self) -> ResolvedModel | None:
        with self._lock:
            state = self._load()
            if state.active is None:
                return None
            provider = self._provider_by_id(state, state.active.provider_id)
            if provider is None:
                return None
            model = next(
                (item for item in provider.models if item.model_id == state.active.model_id), None
            )
            if model is None:
                return None
            return ResolvedModel(
                provider_id=provider.provider_id,
                provider_name=provider.name,
                protocol=provider.protocol,
                api_base=provider.api_base,
                api_key=provider.api_key,
                model_id=model.model_id,
                model_name=model.name,
                context_window=model.context_window,
                max_output_tokens=model.max_output_tokens,
            )


def _validation_message(error: ValidationError) -> str:
    messages = []
    for item in error.errors():
        message = str(item.get("msg") or "配置无效")
        if message.startswith("Value error, "):
            message = message[len("Value error, ") :]
        messages.append(message)
    return "；".join(dict.fromkeys(messages)) or "配置无效"
