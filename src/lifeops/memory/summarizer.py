from __future__ import annotations

import json
from typing import Any

from lifeops.llm.types import Message, MessageRole
from lifeops.utils.logging import get_logger

logger = get_logger(__name__)

_MAX_SUMMARY_CHARS = 8000
_MAX_SUMMARY_MESSAGES = 20


class ConversationSummarizer:
    def __init__(self, llm: Any) -> None:
        self.llm = llm

    async def summarize(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        transcript = "\n".join(
            f"{item.get('role')}: {item.get('content')}"
            for item in messages[-_MAX_SUMMARY_MESSAGES:]
            if item.get("content")
        )
        if len(transcript) > _MAX_SUMMARY_CHARS:
            tail = transcript[-_MAX_SUMMARY_CHARS:]
            transcript = tail[tail.find("\n") + 1 :] or tail
        prompt = (
            "请从以下对话中提取长期记忆。只输出 JSON 对象，不要 Markdown。\n"
            "只提取对话中实际出现的内容，不要臆造或补全缺失信息。\n"
            "字段：summary(string), key_decisions(array), action_items(array), "
            "topics(array), tone(string|null), preferences(array), entities(array), relations(array)。\n"
            "preferences 元素字段：key,value,confidence,evidence。\n"
            "entities 元素字段：name,entity_type,attributes。\n"
            "relations 元素字段：source,target,relation_type,confidence,attributes。\n\n"
            f"对话：\n{transcript}"
        )
        response = await self.llm.chat(
            [Message(role=MessageRole.USER, content=prompt)],
            tools=None,
            temperature=0.1,
        )
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
            logger.warning("记忆提取 JSON 解析失败，内容长度=%s", len(text))
            return {}
        return payload if isinstance(payload, dict) else {}
