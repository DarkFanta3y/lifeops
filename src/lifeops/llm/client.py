from __future__ import annotations

import json

import httpx
from httpx import Timeout
from openai import APIConnectionError, APITimeoutError, AsyncOpenAI

from lifeops.llm.types import ChatResponse, LLMError, LLMErrorInfo, Message
from lifeops.tools.base import ToolDefinition
from lifeops.tools.schema import openai_tool_schema, select_llm_tools
from lifeops.utils.logging import get_logger
from lifeops.utils.text import sanitize_unicode_data


logger = get_logger(__name__)


def _status_code(error: BaseException) -> int | None:
    status_code = getattr(error, "status_code", None)
    return status_code if isinstance(status_code, int) else None


def _classify_error(error: BaseException) -> LLMErrorInfo:
    status_code = _status_code(error)
    message = str(error)
    normalized_message = message.lower()
    protocol_error = "reasoning_content" in normalized_message or "reasoning content" in normalized_message
    transient_error = isinstance(
        error,
        (APIConnectionError, APITimeoutError, httpx.RequestError, TimeoutError, ConnectionError),
    )
    retryable = not protocol_error and (
        transient_error or status_code == 429 or (status_code is not None and status_code >= 500)
    )
    return LLMErrorInfo(
        message=message,
        retryable=retryable,
        status_code=status_code,
    )


def _error_event(info: LLMErrorInfo) -> dict[str, object]:
    return {"type": "error", "data": info.to_dict()}


class LLMClient:
    def __init__(
        self,
        api_key: str,
        model: str = "glm-4-flash",
        api_base: str = "https://open.bigmodel.cn/api/paas/v4",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: float = 60.0,
    ):
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=api_base,
            timeout=Timeout(connect=10.0, read=timeout, write=timeout, pool=timeout),
        )

    def _build_tool_schemas(self, tools: list[ToolDefinition]) -> list[dict]:
        selected_tools = select_llm_tools(tools)
        return [openai_tool_schema(tool_def) for tool_def in selected_tools]

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        **kwargs: object,
    ) -> ChatResponse:
        try:
            msg_dicts = sanitize_unicode_data([m.to_dict() for m in messages])
            request_kwargs: dict[str, object] = {
                "model": self.model,
                "messages": msg_dicts,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                **kwargs,
            }
            if tools:
                request_kwargs["tools"] = self._build_tool_schemas(tools)
        except Exception as error:
            raise LLMError(_classify_error(error)) from error

        logger.debug(f"LLM request: {len(messages)} messages, {len(tools or [])} tools")

        for attempt in range(2):
            try:
                response = await self._client.chat.completions.create(**request_kwargs)

                tc_count = (
                    len(response.choices[0].message.tool_calls)
                    if response.choices[0].message.tool_calls
                    else 0
                )
                logger.debug(
                    f"LLM response: content={'yes' if response.choices[0].message.content else 'no'}, tool_calls={tc_count}"
                )

                return ChatResponse.from_openai_response(response)
            except Exception as error:
                info = _classify_error(error)
                if info.retryable and attempt == 0:
                    logger.warning("Transient LLM error; retrying once: %s", info.message)
                    continue
                raise LLMError(info) from error

        raise AssertionError("unreachable")

    async def chat_stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        **kwargs: object,
    ):
        try:
            msg_dicts = sanitize_unicode_data([m.to_dict() for m in messages])
            request_kwargs: dict[str, object] = {
                "model": self.model,
                "messages": msg_dicts,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "stream": True,
                **kwargs,
            }
            if tools:
                request_kwargs["tools"] = self._build_tool_schemas(tools)

            logger.debug(
                f"LLM stream request: {len(messages)} messages, {len(tools or [])} tools"
            )

            response = await self._client.chat.completions.create(**request_kwargs)
            buffers: dict[int, dict[str, str]] = {}
            started_indexes: set[int] = set()
            ready_indexes: set[int] = set()
            reasoning_parts: list[str] = []
            async for chunk in response:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta

                reasoning_delta = getattr(delta, "reasoning_content", None)
                if isinstance(reasoning_delta, str) and reasoning_delta:
                    reasoning_parts.append(reasoning_delta)

                if delta.content:
                    yield {"type": "token", "data": delta.content}

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in buffers:
                            buffers[idx] = {"name": "", "arguments": ""}
                        if tc.id:
                            buffers[idx]["id"] = tc.id
                        if tc.function.name:
                            buffers[idx]["name"] = tc.function.name
                            if idx not in started_indexes:
                                started_indexes.add(idx)
                                yield {
                                    "type": "tool_call_start",
                                    "data": {
                                        "id": buffers[idx].get("id"),
                                        "index": idx,
                                        "name": buffers[idx]["name"],
                                    },
                                }
                        if tc.function.arguments:
                            buffers[idx]["arguments"] += tc.function.arguments

                        buf = buffers[idx]
                        if (
                            idx not in ready_indexes
                            and buf.get("name")
                            and buf.get("arguments")
                        ):
                            try:
                                parsed_args = json.loads(buf["arguments"])
                            except json.JSONDecodeError:
                                parsed_args = None
                            if isinstance(parsed_args, dict):
                                ready_indexes.add(idx)
                                yield {
                                    "type": "tool_call_ready",
                                    "data": {
                                        "id": buf.get("id"),
                                        "index": idx,
                                        "name": buf["name"],
                                        "args": parsed_args,
                                    },
                                }

            for idx in sorted(buffers):
                buf = buffers[idx]
                try:
                    args = json.loads(buf["arguments"]) if buf["arguments"] else {}
                except json.JSONDecodeError:
                    yield _error_event(
                        LLMErrorInfo(
                            message="工具调用参数 JSON 无效",
                            retryable=False,
                        )
                    )
                    return
                yield {
                    "type": "tool_call",
                    "data": {
                        "id": buf.get("id"),
                        "index": idx,
                        "name": buf["name"],
                        "args": args,
                    },
                }
            if reasoning_parts:
                yield {"type": "reasoning_content", "data": "".join(reasoning_parts)}
        except Exception as error:
            yield _error_event(_classify_error(error))
