from __future__ import annotations

import json
import re
from typing import Any

from lifeops.llm.client import LLMClient
from lifeops.llm.types import Message, MessageRole
from lifeops.skills.types import SkillMatch, SkillMatchResult, SkillMetadata
from lifeops.utils.logging import get_logger

logger = get_logger(__name__)

EXPLICIT_SKILL_PATTERN = re.compile(r"\$([A-Za-z0-9][A-Za-z0-9_.-]*)")


class SkillMatcher:
    def __init__(self, llm: LLMClient | None):
        self.llm = llm

    def match_explicit(
        self, user_input: str, skills: dict[str, SkillMetadata]
    ) -> SkillMatchResult:
        names = list(dict.fromkeys(EXPLICIT_SKILL_PATTERN.findall(user_input)))
        matches = [
            SkillMatch(name=name, reason="用户显式调用", explicit=True)
            for name in names
            if name in skills
        ]
        unknown_names = [name for name in names if name not in skills]
        return SkillMatchResult(matches=matches, unknown_names=unknown_names)

    async def match_implicit(
        self, user_input: str, skills: dict[str, SkillMetadata]
    ) -> SkillMatchResult:
        candidates = {
            name: skill for name, skill in skills.items() if skill.allow_implicit_invocation
        }
        if not candidates or self.llm is None:
            return SkillMatchResult(matches=[])

        prompt = _build_match_prompt(user_input, candidates)
        response = await self.llm.chat(
            [
                Message(
                    role=MessageRole.SYSTEM,
                    content=(
                        "你是 LifeOps Skill 匹配器。只返回 JSON 字符串数组，"
                        "数组元素必须来自候选 Skill 名称；不需要解释。"
                    ),
                ),
                Message(role=MessageRole.USER, content=prompt),
            ],
            tools=None,
        )
        names = _parse_name_array(response.content)
        matches = [
            SkillMatch(name=name, reason="LLM 隐式匹配", explicit=False)
            for name in names
            if name in candidates
        ]
        return SkillMatchResult(matches=matches)


def _build_match_prompt(user_input: str, candidates: dict[str, SkillMetadata]) -> str:
    skill_lines = "\n".join(
        f"- {skill.name}: {skill.description}" for skill in candidates.values()
    )
    return (
        "根据用户输入判断是否需要激活 0 到多个 Skill。\n"
        "只有当 Skill 描述明确适合当前请求时才返回名称。\n\n"
        f"用户输入:\n{user_input}\n\n候选 Skills:\n{skill_lines}\n\n"
        '返回示例: ["weekly-review"] 或 []'
    )


def _parse_name_array(content: str | None) -> list[str]:
    if not content:
        return []
    try:
        parsed: Any = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("Skill matcher 返回了无效 JSON，已降级为空匹配")
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, str)]
