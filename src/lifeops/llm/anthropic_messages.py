"""Anthropic Messages API 适配器。

使用 httpx 直接调用 `POST {base}/v1/messages`，把 Anthropic 的
content block / 流式事件转换为 LifeOps Agent 使用的统一事件协议。
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from httpx import Timeout

from lifeops.llm.client import _classify_error, _error_event
from lifeops.llm.types import (
    ChatResponse,
    LLMError,
    Message,
    MessageRole,
    ToolCallResult,
)
from lifeops.tools.base import ToolDefinition
from lifeops.tools.schema import openai_tool_schema, select_llm_tools


class AnthropicMessagesClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        api_base: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: float = 60.0,
        stream_usage: bool = True,
    ) -> None:
        self.model = model
        self.stream_usage = stream_usage
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self._timeout = Timeout(connect=10.0, read=timeout, write=timeout, pool=timeout)

    def _request_kwargs(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None,
        **kwargs: object,
    ) -> dict[str, Any]:
        system, converted = _convert_messages(messages)
        request: dict[str, Any] = {
            "model": self.model,
            "messages": converted,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            **kwargs,
        }
        if system:
            request["system"] = system
        if tools:
            request["tools"] = [_anthropic_tool_schema(tool) for tool in select_llm_tools(tools)]
        return request

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key or "not-needed",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    @property
    def _url(self) -> str:
        if self.api_base.endswith("/messages"):
            return self.api_base
        if self.api_base.endswith("/v1"):
            return f"{self.api_base}/messages"
        return f"{self.api_base}/v1/messages"

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        **kwargs: object,
    ) -> ChatResponse:
        try:
            payload = self._request_kwargs(messages, tools, **kwargs)
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(self._url, headers=self._headers, json=payload)
                if response.status_code >= 400:
                    raise _AnthropicError(_error_detail(response), response.status_code)
                data = response.json()
            return _parse_response(data)
        except Exception as error:
            raise LLMError(_classify_error(error)) from error

    async def chat_stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        **kwargs: object,
    ):
        try:
            payload = self._request_kwargs(messages, tools, stream=True, **kwargs)
            tool_buffers: dict[int, dict[str, Any]] = {}
            reasoning_parts: list[str] = []
            usage: dict[str, int] = {}
            next_tool_index = 0
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                async with client.stream(
                    "POST", self._url, headers=self._headers, json=payload
                ) as response:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode("utf-8", errors="replace")
                        raise _AnthropicError(_body_error(body), response.status_code)
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if not raw or raw == "[DONE]":
                            continue
                        try:
                            event = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        event_type = event.get("type", "")
                        if event_type == "message_start":
                            message = event.get("message") or {}
                            _merge_usage(usage, message.get("usage"))
                        elif event_type == "content_block_start":
                            block = event.get("content_block") or {}
                            if block.get("type") == "tool_use":
                                index = next_tool_index
                                next_tool_index += 1
                                tool_buffers[index] = {
                                    "id": block.get("id") or f"tool_{index}",
                                    "name": block.get("name") or "",
                                    "arguments": "",
                                    "input": block.get("input") or {},
                                    "block_index": event.get("index"),
                                    "index": index,
                                }
                                yield {
                                    "type": "tool_call_start",
                                    "data": {
                                        "id": tool_buffers[index]["id"],
                                        "index": index,
                                        "name": tool_buffers[index]["name"],
                                    },
                                }
                            elif block.get("type") == "thinking" and block.get("thinking"):
                                reasoning_parts.append(str(block["thinking"]))
                        elif event_type == "content_block_delta":
                            delta = event.get("delta") or {}
                            delta_type = delta.get("type")
                            block_index = event.get("index")
                            if delta_type == "text_delta" and delta.get("text"):
                                yield {"type": "token", "data": delta["text"]}
                            elif delta_type == "thinking_delta" and delta.get("thinking"):
                                reasoning_parts.append(str(delta["thinking"]))
                            elif delta_type == "input_json_delta":
                                buffer = _buffer_for_block(tool_buffers, block_index)
                                if buffer is not None:
                                    partial = delta.get("partial_json") or ""
                                    buffer["arguments"] += partial
                                    if partial:
                                        yield {
                                            "type": "tool_call_delta",
                                            "data": {
                                                "index": buffer["index"],
                                                "name": buffer["name"],
                                                "arguments": partial,
                                            },
                                        }
                        elif event_type == "content_block_stop":
                            buffer = _buffer_for_block(tool_buffers, event.get("index"))
                            if buffer is not None:
                                parsed = _parse_arguments(buffer)
                                if parsed is not None:
                                    yield {
                                        "type": "tool_call_ready",
                                        "data": {
                                            "id": buffer["id"],
                                            "index": buffer["index"],
                                            "name": buffer["name"],
                                            "args": parsed,
                                        },
                                    }
                        elif event_type == "message_delta":
                            _merge_usage(usage, event.get("usage"))
                        elif event_type == "message_stop":
                            for buffer in sorted(
                                tool_buffers.values(), key=lambda item: item["index"]
                            ):
                                parsed = _parse_arguments(buffer)
                                if parsed is None:
                                    yield _error_event(
                                        _classify_error(
                                            _AnthropicError("工具调用参数 JSON 无效", 400)
                                        )
                                    )
                                    return
                                yield {
                                    "type": "tool_call",
                                    "data": {
                                        "id": buffer["id"],
                                        "index": buffer["index"],
                                        "name": buffer["name"],
                                        "args": parsed,
                                    },
                                }
                            if reasoning_parts:
                                yield {
                                    "type": "reasoning_content",
                                    "data": "".join(reasoning_parts),
                                }
                            normalized = _normalize_usage(usage)
                            if normalized:
                                yield {"type": "usage", "data": normalized}
                        elif event_type == "error":
                            error = event.get("error") or {}
                            message = error.get("message") or "Anthropic Messages 调用失败"
                            yield _error_event(
                                _classify_error(
                                    _AnthropicError(message, _anthropic_error_status(error))
                                )
                            )
                            return
        except Exception as error:
            yield _error_event(_classify_error(error))


class _AnthropicError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)


def _convert_messages(messages: list[Message]) -> tuple[str, list[dict[str, Any]]]:
    system_parts: list[str] = []
    converted: list[dict[str, Any]] = []
    for message in messages:
        if message.role == MessageRole.SYSTEM:
            if message.content:
                system_parts.append(message.content)
            continue
        if message.role == MessageRole.TOOL:
            blocks = [
                {
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id or "",
                    "content": message.content or "",
                }
            ]
            _append_message(converted, "user", blocks)
            continue
        if message.role == MessageRole.ASSISTANT:
            blocks: list[dict[str, Any]] = []
            if message.content:
                blocks.append({"type": "text", "text": message.content})
            for call in message.tool_calls or []:
                function = call.get("function") or {}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call.get("id") or "",
                        "name": function.get("name") or "",
                        "input": _json_object(function.get("arguments")),
                    }
                )
            if blocks:
                _append_message(converted, "assistant", blocks)
            continue
        _append_message(
            converted,
            "user",
            [{"type": "text", "text": message.content or ""}],
        )
    return "\n\n".join(system_parts), converted


def _append_message(
    messages: list[dict[str, Any]], role: str, blocks: list[dict[str, Any]]
) -> None:
    if messages and messages[-1]["role"] == role:
        messages[-1]["content"].extend(blocks)
        return
    messages.append({"role": role, "content": blocks})


def _anthropic_tool_schema(tool: ToolDefinition) -> dict[str, Any]:
    schema = openai_tool_schema(tool)
    function = schema.get("function", {})
    parameters = function.get("parameters") or {"type": "object", "properties": {}}
    if "type" not in parameters:
        parameters = {**parameters, "type": "object"}
    return {
        "name": function.get("name", ""),
        "description": function.get("description", ""),
        "input_schema": parameters,
    }


def _json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        value = json.loads(str(raw))
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _parse_arguments(buffer: dict[str, Any]) -> dict[str, Any] | None:
    if buffer.get("arguments"):
        try:
            parsed = json.loads(buffer["arguments"])
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    initial = buffer.get("input")
    return initial if isinstance(initial, dict) else {}


def _buffer_for_block(
    buffers: dict[int, dict[str, Any]], block_index: Any
) -> dict[str, Any] | None:
    if isinstance(block_index, int):
        for buffer in buffers.values():
            if buffer.get("block_index") == block_index:
                return buffer
        return None
    return next(iter(buffers.values())) if len(buffers) == 1 else None


def _merge_usage(usage: dict[str, int], raw: Any) -> None:
    if not isinstance(raw, dict):
        return
    for source, target in (
        ("input_tokens", "input_tokens"),
        ("output_tokens", "output_tokens"),
        ("cache_read_input_tokens", "cache_read_input_tokens"),
        ("cache_creation_input_tokens", "cache_creation_input_tokens"),
    ):
        value = raw.get(source)
        if isinstance(value, int):
            usage[target] = value


def _normalize_usage(usage: dict[str, int]) -> dict[str, int] | None:
    if not usage:
        return None
    result: dict[str, int] = {}
    if "input_tokens" in usage:
        result["prompt_tokens"] = usage["input_tokens"]
    if "output_tokens" in usage:
        result["completion_tokens"] = usage["output_tokens"]
    if "cache_read_input_tokens" in usage:
        result["cached_tokens"] = usage["cache_read_input_tokens"]
    if "prompt_tokens" in result or "completion_tokens" in result:
        result["total_tokens"] = result.get("prompt_tokens", 0) + result.get("completion_tokens", 0)
    return result or None


def _parse_response(data: dict[str, Any]) -> ChatResponse:
    content_parts: list[str] = []
    tool_calls: list[ToolCallResult] = []
    reasoning_parts: list[str] = []
    for block in data.get("content") or []:
        block_type = block.get("type")
        if block_type == "text":
            content_parts.append(block.get("text") or "")
        elif block_type == "thinking":
            reasoning_parts.append(block.get("thinking") or "")
        elif block_type == "tool_use":
            tool_calls.append(
                ToolCallResult(
                    id=block.get("id") or "",
                    name=block.get("name") or "",
                    arguments=json.dumps(block.get("input") or {}, ensure_ascii=False),
                )
            )
    raw_usage = data.get("usage") or {}
    usage = _normalize_usage(
        {
            key: value
            for key, value in raw_usage.items()
            if isinstance(value, int)
        }
    )
    return ChatResponse(
        content="".join(content_parts) or None,
        tool_calls=tool_calls or None,
        usage=usage,
        reasoning_content="".join(reasoning_parts) or None,
    )


def _anthropic_error_status(error: dict[str, Any]) -> int:
    error_type = error.get("type", "")
    if error_type in {"authentication_error", "permission_error"}:
        return 401
    if error_type == "not_found_error":
        return 404
    if error_type == "rate_limit_error":
        return 429
    if error_type in {"api_error", "overloaded_error"}:
        return 500
    return 400


def _error_detail(response: httpx.Response) -> str:
    return _body_error(response.text)


def _body_error(body: str) -> str:
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return body[:500] or "Anthropic Messages 调用失败"
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])
    return body[:500] or "Anthropic Messages 调用失败"
