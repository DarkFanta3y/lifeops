"""一次 LLM 请求的上下文构成：把系统提示分段、工具 schema、消息拆成带类别与 token 估算的元素。

类别沿用 dsh-context 的七分法：system / tools / user / inject / skill / assistant / tool。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from lifeops.core.context_manager import ContextLayer
from lifeops.llm.types import Message, MessageRole
from lifeops.tools.base import ToolDefinition
from lifeops.tools.schema import openai_tool_schema

CATEGORIES = ("system", "tools", "user", "inject", "skill", "assistant", "tool")

NAME_MAX_CHARS = 80


@dataclass
class ContextElement:
    cat: str
    name: str
    tokens: int
    content: dict[str, Any]
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SystemPart:
    """系统消息中的一段：基础提示、当前信息、上下文条目、任务计划等。"""

    cat: str
    name: str
    text: str


def entry_category(key: str, layer: ContextLayer) -> str:
    if key == "skills_catalog" or key.startswith("skill:"):
        return "skill"
    if layer == ContextLayer.L3:
        return "tool"
    return "inject"


def _excerpt(text: str | None) -> str:
    normalized = " ".join((text or "").split())
    return normalized[:NAME_MAX_CHARS]


def _message_element(message: Message, index: int, estimate_message: Callable[[Message], int]) -> ContextElement:
    content: dict[str, Any] = {"text": message.content or ""}
    meta: dict[str, Any] = {"index": index}
    if message.reasoning_content:
        content["reasoning"] = message.reasoning_content
    if message.role == MessageRole.USER:
        return ContextElement("user", _excerpt(message.content) or "用户消息", estimate_message(message), content, meta)
    if message.role == MessageRole.TOOL:
        if message.tool_call_id:
            content["tool_call_id"] = message.tool_call_id
            meta["call"] = message.tool_call_id
        name = message.name or "工具结果"
        meta["tool"] = name
        return ContextElement("tool", name, estimate_message(message), content, meta)
    calls = []
    for call in message.tool_calls or []:
        # 主 Agent 用 OpenAI 结构，子 Agent 直接平铺 name/arguments
        function = call.get("function") or call
        calls.append({
            "id": call.get("id"),
            "name": function.get("name") or "",
            "arguments": function.get("arguments") or "",
        })
    if calls:
        content["calls"] = calls
        meta["calls"] = [call["name"] for call in calls][:3]
    name = _excerpt(message.content) or ("调用 " + "、".join(meta.get("calls", [])) if calls else "助手回复")
    kinds = [kind for kind, present in (
        ("thinking", bool(message.reasoning_content)),
        ("tools", bool(calls)),
        ("answer", bool(message.content)),
    ) if present]
    if kinds:
        meta["kinds"] = kinds
    return ContextElement("assistant", name, estimate_message(message), content, meta)


def build_composition(
    *,
    system_parts: list[SystemPart],
    messages: list[Message],
    tools: list[ToolDefinition] | None,
    estimate: Callable[[str], int],
    estimate_message: Callable[[Message], int],
) -> list[ContextElement]:
    """messages 为实际发送的消息（已去掉首条系统消息、已按预算裁剪）。"""
    elements = [
        ContextElement(part.cat, part.name, estimate(part.text), {"text": part.text})
        for part in system_parts
        if part.text
    ]
    for tool in tools or []:
        schema = openai_tool_schema(tool)
        text = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        elements.append(ContextElement(
            "tools",
            tool.name,
            estimate(text),
            {"text": json.dumps(schema, ensure_ascii=False, indent=2)},
            {"source": tool.category or "builtin"},
        ))
    for index, message in enumerate(messages):
        if message.role == MessageRole.SYSTEM:
            continue
        elements.append(_message_element(message, index, estimate_message))
    return elements


def category_totals(elements: list[ContextElement]) -> dict[str, int]:
    totals = dict.fromkeys(CATEGORIES, 0)
    for element in elements:
        totals[element.cat] = totals.get(element.cat, 0) + element.tokens
    return totals
