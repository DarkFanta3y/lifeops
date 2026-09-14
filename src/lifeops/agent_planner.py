from __future__ import annotations

import json
from typing import Any

from lifeops.llm.client import LLMClient
from lifeops.llm.types import Message, MessageRole
from lifeops.utils.logging import get_logger

logger = get_logger(__name__)

COMPLEXITY_SYSTEM_PROMPT = (
    "你是 LifeOps 的任务复杂度分类器。只返回一个 JSON 对象："
    '{"complexity": "simple"} 或 {"complexity": "complex"}；不需要解释。\n\n'
    "判定标准：\n"
    "- simple：一次回答即可完成；或只需 0-1 个工具调用就能给出结论"
    "（如常识问答、闲聊、单一事实查询、改写润色）。\n"
    "- complex：需要多个工具步骤按顺序完成才能达成目标"
    "（如创建/修改多个文件、执行命令并根据结果继续操作、"
    "先探索再修改、批量处理或多阶段任务）。"
)


async def classify_task_complexity(llm: LLMClient, user_input: str) -> bool:
    """判定任务是否为需要计划的多步骤任务。

    返回 True 表示 complex（要求先 todo_write 列计划）；
    任何失败（无效 JSON、LLM 错误）都降级为 False（simple），不阻塞主流程。
    """
    try:
        response = await llm.chat(
            [
                Message(role=MessageRole.SYSTEM, content=COMPLEXITY_SYSTEM_PROMPT),
                Message(role=MessageRole.USER, content=user_input),
            ],
            tools=None,
            temperature=0.1,
        )
    except Exception as exc:
        logger.warning(f"任务复杂度判定失败，降级为 simple: {exc}")
        return False
    return _parse_complexity(response.content)


def _parse_complexity(content: str | None) -> bool:
    if not content:
        return False
    try:
        parsed: Any = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("任务复杂度分类器返回了无效 JSON，已降级为 simple")
        return False
    if not isinstance(parsed, dict):
        return False
    return parsed.get("complexity") == "complex"
