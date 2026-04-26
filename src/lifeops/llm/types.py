from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from lifeops.utils.text import sanitize_unicode_data, sanitize_unicode_text


class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class ToolCallResult:
    id: str
    name: str
    arguments: str
    type: str = "function"


@dataclass
class ChatResponse:
    content: str | None
    tool_calls: list[ToolCallResult] | None
    usage: dict[str, int] | None = None

    @classmethod
    def from_openai_response(cls, response: Any) -> "ChatResponse":
        choice = response.choices[0]
        content = choice.message.content
        tool_calls = None
        if choice.message.tool_calls:
            tool_calls = [
                ToolCallResult(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=tc.function.arguments,
                    type=tc.type,
                )
                for tc in choice.message.tool_calls
            ]
        usage = None
        if hasattr(response, "usage") and response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
        return cls(content=content, tool_calls=tool_calls, usage=usage)


@dataclass
class Message:
    role: MessageRole
    content: str | None = None
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"role": self.role.value}
        if self.content is not None:
            d["content"] = sanitize_unicode_text(self.content)
        if self.tool_calls is not None:
            d["tool_calls"] = sanitize_unicode_data(self.tool_calls)
        if self.tool_call_id is not None:
            d["tool_call_id"] = sanitize_unicode_text(self.tool_call_id)
        if self.name is not None:
            d["name"] = sanitize_unicode_text(self.name)
        return d
