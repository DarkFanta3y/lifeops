"""按当前提供商配置构建 LLM 客户端，并提供模型目录探测。"""

from __future__ import annotations

from typing import Any

import httpx

from lifeops.core.config import AppConfig
from lifeops.llm.anthropic_messages import AnthropicMessagesClient
from lifeops.llm.client import LLMClient
from lifeops.llm.openai_responses import OpenAIResponsesClient
from lifeops.model_registry import ModelRegistryError, ResolvedModel
from lifeops.utils.logging import get_logger

logger = get_logger(__name__)

_PROTOCOL_CLIENTS = {
    "openai_chat": LLMClient,
    "openai_responses": OpenAIResponsesClient,
    "anthropic_messages": AnthropicMessagesClient,
}


def build_llm_client(config: AppConfig, resolved: ResolvedModel | None = None) -> Any:
    """有当前模型时使用注册表配置，否则回退到 `.env` 中的 LLM_* 配置。"""
    if resolved is None:
        return LLMClient(
            api_key=config.llm.api_key,
            model=config.llm.model,
            api_base=config.llm.api_base,
            max_tokens=config.llm.max_tokens,
            temperature=config.llm.temperature,
            timeout=config.llm.timeout,
            stream_usage=config.llm.stream_usage,
        )
    client_class = _PROTOCOL_CLIENTS.get(resolved.protocol)
    if client_class is None:
        raise ModelRegistryError(f"暂不支持协议：{resolved.protocol}", status_code=422)
    return client_class(
        api_key=resolved.api_key or "not-needed",
        model=resolved.model_id,
        api_base=resolved.api_base,
        max_tokens=resolved.max_output_tokens or config.llm.max_tokens,
        temperature=config.llm.temperature,
        timeout=config.llm.timeout,
        stream_usage=config.llm.stream_usage,
    )


async def fetch_available_models(
    api_base: str, protocol: str, api_key: str = ""
) -> list[dict[str, Any]]:
    """请求提供商的模型目录。兼容 OpenAI 的 `/models` 与 Anthropic 的 `/v1/models`。"""
    base = api_base.rstrip("/")
    urls = _candidate_model_urls(base)
    headers = {"Accept": "application/json"}
    if protocol == "anthropic_messages":
        headers["anthropic-version"] = "2023-06-01"
        if api_key:
            headers["x-api-key"] = api_key
    elif api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    last_error = ""
    async with httpx.AsyncClient(timeout=20.0) as client:
        for url in urls:
            try:
                response = await client.get(url, headers=headers)
            except httpx.RequestError as exc:
                last_error = f"无法连接 {url}：{exc}"
                continue
            if response.status_code >= 400:
                last_error = f"HTTP {response.status_code}：{_response_detail(response)}"
                continue
            try:
                payload = response.json()
            except ValueError:
                last_error = f"{url} 返回的不是 JSON"
                continue
            models = _parse_models(payload)
            if models:
                return models
            last_error = "模型目录为空"
    raise ModelRegistryError(
        f"获取可用模型失败：{last_error or '提供商没有返回模型'}", status_code=502
    )


def _candidate_model_urls(base: str) -> list[str]:
    if base.endswith("/models"):
        return [base]
    if base.endswith("/v1"):
        return [f"{base}/models"]
    return [f"{base}/v1/models", f"{base}/models"]


def _response_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:300] or response.reason_phrase
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
        if payload.get("detail"):
            return str(payload["detail"])
        if payload.get("message"):
            return str(payload["message"])
    return response.text[:300] or response.reason_phrase


def _parse_models(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = (
            payload.get("data")
            or payload.get("models")
            or payload.get("items")
            or payload.get("result")
        )
    else:
        items = None
    if not isinstance(items, list):
        return []

    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, str):
            model_id, name, context_window, max_output = item, item, None, None
        elif isinstance(item, dict):
            model_id = (
                item.get("id")
                or item.get("model")
                or item.get("name")
                or item.get("model_id")
            )
            if not isinstance(model_id, str) or not model_id.strip():
                continue
            name = (
                item.get("display_name")
                or item.get("displayName")
                or item.get("name")
                or model_id
            )
            context_window = _positive_int(
                item.get("context_window")
                or item.get("context_length")
                or item.get("max_context_length")
                or item.get("max_input_tokens")
            )
            max_output = _positive_int(
                item.get("max_output_tokens")
                or item.get("max_tokens")
                or item.get("max_completion_tokens")
            )
        else:
            continue
        model_id = model_id.strip()
        if model_id in seen:
            continue
        seen.add(model_id)
        result.append(
            {
                "model_id": model_id,
                "name": str(name or model_id)[:200],
                "context_window": context_window,
                "max_output_tokens": max_output,
            }
        )
    result.sort(key=lambda entry: entry["model_id"].lower())
    return result


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, float) and value > 0:
        return int(value)
    return None
