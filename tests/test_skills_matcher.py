from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from lifeops.llm.types import ChatResponse
from lifeops.skills.matcher import SkillMatcher
from lifeops.skills.types import SkillMetadata, SkillSource


def make_skill(name: str, *, allow_implicit_invocation: bool = True) -> SkillMetadata:
    return SkillMetadata(
        name=name,
        description=f"{name} description",
        path=Path(f"/tmp/{name}/SKILL.md"),
        directory=Path(f"/tmp/{name}"),
        source=SkillSource.PROJECT,
        raw_frontmatter={},
        allow_implicit_invocation=allow_implicit_invocation,
    )


def test_matcher_finds_explicit_skill_invocations():
    matcher = SkillMatcher(llm=None)
    skills = {
        "weekly-review": make_skill("weekly-review"),
        "meal-plan": make_skill("meal-plan"),
    }

    result = matcher.match_explicit("请用 $weekly-review 总结一下", skills)

    assert [match.name for match in result.matches] == ["weekly-review"]
    assert result.unknown_names == []


def test_matcher_reports_unknown_explicit_skill_names():
    matcher = SkillMatcher(llm=None)
    skills = {"weekly-review": make_skill("weekly-review")}

    result = matcher.match_explicit("请用 $unknown-skill", skills)

    assert result.matches == []
    assert result.unknown_names == ["unknown-skill"]


@pytest.mark.asyncio
async def test_matcher_excludes_skills_that_disallow_implicit_invocation():
    llm = AsyncMock()
    llm.chat = AsyncMock(return_value=ChatResponse(content='["private-skill"]', tool_calls=None))
    matcher = SkillMatcher(llm=llm)
    skills = {
        "private-skill": make_skill("private-skill", allow_implicit_invocation=False),
    }

    result = await matcher.match_implicit("帮我处理这个任务", skills)

    assert result.matches == []
    llm.chat.assert_not_called()


@pytest.mark.asyncio
async def test_matcher_uses_llm_json_array_for_implicit_matches():
    llm = AsyncMock()
    llm.chat = AsyncMock(return_value=ChatResponse(content='["weekly-review"]', tool_calls=None))
    matcher = SkillMatcher(llm=llm)
    skills = {"weekly-review": make_skill("weekly-review")}

    result = await matcher.match_implicit("复盘这周", skills)

    assert [match.name for match in result.matches] == ["weekly-review"]


@pytest.mark.asyncio
async def test_matcher_returns_empty_matches_when_llm_returns_invalid_json():
    llm = AsyncMock()
    llm.chat = AsyncMock(return_value=ChatResponse(content="weekly-review", tool_calls=None))
    matcher = SkillMatcher(llm=llm)
    skills = {"weekly-review": make_skill("weekly-review")}

    result = await matcher.match_implicit("复盘这周", skills)

    assert result.matches == []
