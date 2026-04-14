from __future__ import annotations

from typing import TYPE_CHECKING

from openai import AsyncOpenAI

from lifeops.llm.types import ChatResponse, Message
from lifeops.utils.logging import get_logger

if TYPE_CHECKING:
    from lifeops.tools.base import ToolDefinition

logger = get_logger(__name__)


class LLMClient:
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        api_base: str = "https://api.openai.com/v1",
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ):
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._client = AsyncOpenAI(api_key=api_key, base_url=api_base)

    def _build_tool_schemas(self, tools: list["ToolDefinition"]) -> list[dict]:
        schemas = []
        for t in tools:
            props: dict[str, object] = {}
            required: list[str] = []
            for p in t.parameters:
                props[p.name] = {"type": p.type, "description": p.description}
                if p.required:
                    required.append(p.name)
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": {
                            "type": "object",
                            "properties": props,
                            "required": required,
                        },
                    },
                }
            )
        return schemas

    async def chat(
        self,
        messages: list[Message],
        tools: list["ToolDefinition"] | None = None,
        **kwargs: object,
    ) -> ChatResponse:
        msg_dicts = [m.to_dict() for m in messages]
        request_kwargs: dict[str, object] = {
            "model": self.model,
            "messages": msg_dicts,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            **kwargs,
        }
        if tools:
            request_kwargs["tools"] = self._build_tool_schemas(tools)

        logger.debug(f"LLM request: {len(messages)} messages, {len(tools or [])} tools")

        response = await self._client.chat.completions.create(**request_kwargs)

        tc_count = len(response.choices[0].message.tool_calls) if response.choices[0].message.tool_calls else 0
        logger.debug(f"LLM response: content={'yes' if response.choices[0].message.content else 'no'}, tool_calls={tc_count}")

        return ChatResponse.from_openai_response(response)