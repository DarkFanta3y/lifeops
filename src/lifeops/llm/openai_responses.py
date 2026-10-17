"""OpenAI Responses API 适配器。

LifeOps 的 Agent 只依赖 `chat` / `chat_stream` 与统一事件协议；
这里把 Responses API 的输入项、函数调用和流式事件转换成同一套结构。
"""

from __future__ import annotations

import json
from typing import Any

from httpx import Timeout
from openai import AsyncOpenAI

from lifeops.llm.client import _classify_error, _error_event
from lifeops.llm.types import ChatResponse, LLMError, Message, MessageRole, ToolCallResult
from lifeops.tools.base import ToolDefinition
from lifeops.tools.schema import openai_tool_schema, select_llm_tools


class OpenAIResponsesClient:
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
        self._client = AsyncOpenAI(
            api_key=api_key or "not-needed",
            base_url=api_base,
            timeout=Timeout(connect=10.0, read=timeout, write=timeout, pool=timeout),
        )

    def _request_kwargs(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None,
        **kwargs: object,
    ) -> dict[str, Any]:
        instructions: list[str] = []
        items: list[dict[str, Any]] = []
        for message in messages:
            data = message.to_dict()
            if message.role == MessageRole.SYSTEM:
                if data.get("content"):
                    instructions.append(str(data["content"]))
                continue
            if message.role == MessageRole.TOOL:
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": data.get("tool_call_id") or "",
                        "output": data.get("content") or "",
                    }
                )
                continue
            if message.role == MessageRole.ASSISTANT:
                if data.get("content"):
                    items.append({"role": "assistant", "content": data["content"]})
                for call in data.get("tool_calls") or []:
                    function = call.get("function") or {}
                    items.append(
                        {
                            "type": "function_call",
                            "call_id": call.get("id") or "",
                            "name": function.get("name") or "",
                            "arguments": function.get("arguments") or "{}",
                        }
                    )
                continue
            items.append({"role": "user", "content": data.get("content") or ""})

        request: dict[str, Any] = {
            "model": self.model,
            "input": items,
            "max_output_tokens": self.max_tokens,
            "temperature": self.temperature,
            **kwargs,
        }
        if instructions:
            request["instructions"] = "\n\n".join(instructions)
        if tools:
            request["tools"] = [_responses_tool_schema(tool) for tool in select_llm_tools(tools)]
        return request

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        **kwargs: object,
    ) -> ChatResponse:
        try:
            request = self._request_kwargs(messages, tools, **kwargs)
            response = await self._client.responses.create(**request)
            return _parse_response(response)
        except Exception as error:
            raise LLMError(_classify_error(error)) from error

    async def chat_stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        **kwargs: object,
    ):
        try:
            request = self._request_kwargs(messages, tools, stream=True, **kwargs)
            stream = await self._client.responses.create(**request)
            buffers: dict[str, dict[str, Any]] = {}
            reasoning_parts: list[str] = []
            streamed_text = False
            completed = None
            next_index = 0
            async for event in stream:
                event_type = getattr(event, "type", "")
                if event_type == "response.output_text.delta":
                    delta = getattr(event, "delta", "")
                    if delta:
                        streamed_text = True
                        yield {"type": "token", "data": delta}
                elif event_type == "response.reasoning_summary_text.delta":
                    delta = getattr(event, "delta", "")
                    if delta:
                        reasoning_parts.append(delta)
                elif event_type == "response.output_item.added":
                    item = getattr(event, "item", None)
                    if getattr(item, "type", "") == "function_call":
                        item_id = getattr(item, "id", "") or f"item_{next_index}"
                        buffers[item_id] = {
                            "id": getattr(item, "call_id", "") or item_id,
                            "name": getattr(item, "name", "") or "",
                            "arguments": getattr(item, "arguments", "") or "",
                            "index": next_index,
                        }
                        next_index += 1
                        yield {
                            "type": "tool_call_start",
                            "data": {
                                "id": buffers[item_id]["id"],
                                "index": buffers[item_id]["index"],
                                "name": buffers[item_id]["name"],
                            },
                        }
                elif event_type == "response.function_call_arguments.delta":
                    item_id = getattr(event, "item_id", "")
                    buffer = buffers.get(item_id)
                    delta = getattr(event, "delta", "")
                    if buffer is not None and delta:
                        buffer["arguments"] += delta
                        yield {
                            "type": "tool_call_delta",
                            "data": {
                                "index": buffer["index"],
                                "name": buffer["name"],
                                "arguments": delta,
                            },
                        }
                elif event_type == "response.function_call_arguments.done":
                    item_id = getattr(event, "item_id", "")
                    buffer = buffers.get(item_id)
                    if buffer is not None:
                        arguments = getattr(event, "arguments", "") or buffer["arguments"]
                        buffer["arguments"] = arguments
                        parsed = _parse_arguments(arguments)
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
                elif event_type == "response.completed":
                    completed = getattr(event, "response", None)
                elif event_type in {"response.failed", "response.error"}:
                    response = getattr(event, "response", None)
                    error = getattr(response, "error", None) or getattr(event, "error", None) or event
                    message = getattr(error, "message", None) or str(error) or "OpenAI Responses 调用失败"
                    yield _error_event(
                        _classify_error(
                            LLMResponseError(str(message), getattr(error, "code", None))
                        )
                    )
                    return

            if completed is not None:
                parsed = _parse_response(completed)
                if not streamed_text and parsed.content:
                    yield {"type": "token", "data": parsed.content}
                if not reasoning_parts and parsed.reasoning_content:
                    reasoning_parts.append(parsed.reasoning_content)
                for index, call in enumerate(parsed.tool_calls or []):
                    yield {
                        "type": "tool_call",
                        "data": {
                            "id": call.id,
                            "index": index,
                            "name": call.name,
                            "args": _parse_arguments(call.arguments) or {},
                        },
                    }
                if parsed.usage:
                    yield {"type": "usage", "data": parsed.usage}
            else:
                for buffer in sorted(buffers.values(), key=lambda item: item["index"]):
                    parsed = _parse_arguments(buffer["arguments"])
                    if parsed is None:
                        yield _error_event(
                            _classify_error(LLMResponseError("工具调用参数 JSON 无效", "invalid_json"))
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
                yield {"type": "reasoning_content", "data": "".join(reasoning_parts)}
        except Exception as error:
            yield _error_event(_classify_error(error))


class LLMResponseError(Exception):
    """携带 Responses API 错误码的轻量异常，便于复用统一错误分类。"""

    def __init__(self, message: str, code: str | None = None) -> None:
        self.code = code or ""
        normalized = self.code.lower()
        if "auth" in normalized or "api_key" in normalized:
            self.status_code = 401
        elif "rate" in normalized:
            self.status_code = 429
        elif "invalid" in normalized:
            self.status_code = 400
        else:
            self.status_code = 500
        super().__init__(message)


def _responses_tool_schema(tool: ToolDefinition) -> dict[str, Any]:
    schema = openai_tool_schema(tool)
    function = schema.get("function", {})
    return {
        "type": "function",
        "name": function.get("name", ""),
        "description": function.get("description", ""),
        "parameters": function.get("parameters", {"type": "object", "properties": {}}),
    }


def _parse_arguments(arguments: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(arguments) if arguments else {}
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _usage(response: Any) -> dict[str, int] | None:
    raw = getattr(response, "usage", None)
    if raw is None:
        return None
    result: dict[str, int] = {}
    input_tokens = getattr(raw, "input_tokens", None)
    output_tokens = getattr(raw, "output_tokens", None)
    total_tokens = getattr(raw, "total_tokens", None)
    if isinstance(input_tokens, int):
        result["prompt_tokens"] = input_tokens
    if isinstance(output_tokens, int):
        result["completion_tokens"] = output_tokens
    if isinstance(total_tokens, int):
        result["total_tokens"] = total_tokens
    details = getattr(raw, "input_tokens_details", None)
    cached = getattr(details, "cached_tokens", None)
    if isinstance(cached, int):
        result["cached_tokens"] = cached
    details_out = getattr(raw, "output_tokens_details", None)
    reasoning = getattr(details_out, "reasoning_tokens", None)
    if isinstance(reasoning, int):
        result["reasoning_tokens"] = reasoning
    if "total_tokens" not in result and ("prompt_tokens" in result or "completion_tokens" in result):
        result["total_tokens"] = result.get("prompt_tokens", 0) + result.get("completion_tokens", 0)
    return result or None


def _parse_response(response: Any) -> ChatResponse:
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_calls: list[ToolCallResult] = []
    for item in getattr(response, "output", None) or []:
        item_type = getattr(item, "type", "")
        if item_type == "message":
            for part in getattr(item, "content", None) or []:
                part_type = getattr(part, "type", "")
                if part_type in {"output_text", "text"}:
                    text = getattr(part, "text", None)
                    if text:
                        content_parts.append(text)
        elif item_type == "reasoning":
            for summary in getattr(item, "summary", None) or []:
                text = getattr(summary, "text", None)
                if text:
                    reasoning_parts.append(text)
        elif item_type == "function_call":
            tool_calls.append(
                ToolCallResult(
                    id=getattr(item, "call_id", None) or getattr(item, "id", ""),
                    name=getattr(item, "name", ""),
                    arguments=getattr(item, "arguments", "") or "{}",
                )
            )
    content = "".join(content_parts)
    output_text = getattr(response, "output_text", None)
    if not content and isinstance(output_text, str):
        content = output_text
    return ChatResponse(
        content=content or None,
        tool_calls=tool_calls or None,
        usage=_usage(response),
        reasoning_content="".join(reasoning_parts) or None,
    )
