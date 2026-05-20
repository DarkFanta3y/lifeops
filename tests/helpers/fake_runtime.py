from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from lifeops.llm.types import ChatResponse
from lifeops.tools.base import ToolResult


class ScriptedLLMClient:
    def __init__(self, responses: list[ChatResponse]) -> None:
        self.responses = list(responses)
        self.call_count = 0

    async def chat(self, messages, tools=None, **kwargs):
        self.call_count += 1
        if self.responses:
            return self.responses.pop(0)
        return ChatResponse(content="你好", tool_calls=None)

    async def chat_stream(self, messages, tools=None, **kwargs) -> AsyncIterator[dict[str, Any]]:
        response = await self.chat(messages, tools=tools, **kwargs)
        if response.content:
            yield {"type": "token", "data": response.content}


class FakeToolHandlerFactory:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def success(self, output: str):
        async def handler(params: dict[str, Any]) -> ToolResult:
            self.calls.append(params)
            return ToolResult(success=True, output=output)

        return handler

    def failure(self, error: str):
        async def handler(params: dict[str, Any]) -> ToolResult:
            self.calls.append(params)
            return ToolResult(success=False, output="", error=error)

        return handler
