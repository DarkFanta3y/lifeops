from __future__ import annotations

import json
from typing import Any

from lifeops.llm.types import Message, MessageRole


class ConversationSummarizer:
    def __init__(self, llm: Any) -> None:
        self.llm = llm

    async def summarize(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        transcript = "\n".join(
            f"{item.get('role')}: {item.get('content')}" for item in messages if item.get("content")
        )
        prompt = (
            "请从以下对话中提取长期记忆。只输出 JSON 对象，不要 Markdown。\n"
            "字段：summary(string), key_decisions(array), action_items(array), "
            "topics(array), tone(string|null), preferences(array), entities(array), relations(array)。\n"
            "preferences 元素字段：key,value,confidence,evidence。\n"
            "entities 元素字段：name,entity_type,attributes。\n"
            "relations 元素字段：source,target,relation_type,confidence,attributes。\n\n"
            f"对话：\n{transcript}"
        )
        response = await self.llm.chat([Message(role=MessageRole.USER, content=prompt)], tools=None)
        return self._parse_payload(response.content)

    def _parse_payload(self, content: str | None) -> dict[str, Any]:
        if not content:
            return {}
        text = content.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}
