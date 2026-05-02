from __future__ import annotations

import re
from typing import Any

from lifeops.llm.types import Message, MessageRole
from lifeops.utils.logging import get_logger
from lifeops.utils.text import sanitize_unicode_text

logger = get_logger(__name__)

TITLE_SUMMARY_SYSTEM_PROMPT = """你是 LifeOps 的对话标题生成器。

请根据用户第一条消息生成一个中文短标题。
要求：
- 只输出标题，不要解释
- 不要使用引号、冒号、句号或列表符号
- 6 到 16 个中文字符为佳
- 保留用户意图，不要添加未出现的信息"""

MAX_TITLE_LENGTH = 32


async def summarize_conversation_title(llm: Any, query: str) -> str:
    """Generate a short title for a new web conversation."""
    fallback = fallback_conversation_title(query)
    try:
        response = await llm.chat(
            [
                Message(role=MessageRole.SYSTEM, content=TITLE_SUMMARY_SYSTEM_PROMPT),
                Message(role=MessageRole.USER, content=query),
            ],
            tools=None,
        )
    except Exception:
        logger.exception("生成对话标题失败，使用用户输入回退")
        return fallback

    return normalize_conversation_title(response.content or "", fallback=fallback)


def fallback_conversation_title(query: str) -> str:
    return normalize_conversation_title(query, fallback="未命名对话")


def normalize_conversation_title(raw_title: str, fallback: str = "未命名对话") -> str:
    first_line = sanitize_unicode_text(raw_title).strip().splitlines()[0:1]
    title = first_line[0].strip() if first_line else ""
    title = title.strip(" \t\r\n\"'“”‘’`")
    title = re.sub(r"^[#\-*>\d.、\s]+", "", title)
    title = re.sub(r"[。！？!?:：；;，,、\s]+$", "", title).strip()
    if not title:
        title = fallback.strip() or "未命名对话"
    if len(title) > MAX_TITLE_LENGTH:
        title = title[:MAX_TITLE_LENGTH].rstrip("。！？!?:：；;，,、 ")
    return title or "未命名对话"
