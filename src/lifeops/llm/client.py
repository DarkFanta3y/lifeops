from __future__ import annotations

from httpx import Timeout
from openai import AsyncOpenAI

from lifeops.llm.types import ChatResponse, Message
from lifeops.tools.base import ToolDefinition
from lifeops.utils.logging import get_logger


logger = get_logger(__name__)


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
        schemas = []
        for t in tools:
            json_schema = t.parameters_model.model_json_schema()
            parameters = {
                "type": "object",
                "properties": json_schema.get("properties", {}),
                "required": json_schema.get("required", []),
            }
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": parameters,
                    },
                }
            )
        return schemas

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
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

        tc_count = (
            len(response.choices[0].message.tool_calls)
            if response.choices[0].message.tool_calls
            else 0
        )
        logger.debug(
            f"LLM response: content={'yes' if response.choices[0].message.content else 'no'}, tool_calls={tc_count}"
        )

        return ChatResponse.from_openai_response(response)
