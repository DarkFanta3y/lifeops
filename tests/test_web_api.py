from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from lifeops.core.config import AppConfig, LLMConfig, SkillsConfig
from lifeops.llm.types import ChatResponse
from lifeops.web.api import create_app


def make_web_config(tmp_path, api_key: str = "test-key") -> AppConfig:
    return AppConfig(
        llm=LLMConfig(api_key=api_key, model="gpt-4o"),
        skills=SkillsConfig(
            enabled=True,
            project_dir=str(tmp_path / "project-skills"),
            user_dir=str(tmp_path / "user-skills"),
            implicit_match_enabled=False,
        ),
        history_path=str(tmp_path / "history.jsonl"),
    )


async def request(app, method: str, url: str, **kwargs):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, url, **kwargs)


@pytest.mark.asyncio
async def test_api_lists_conversations_and_detail(tmp_path):
    config = make_web_config(tmp_path)
    app = create_app(config)
    app.state.history_store.append_message("conv-1", "cli", "user", "你好")

    conversations_response = await request(app, "GET", "/api/conversations")
    detail_response = await request(app, "GET", "/api/conversations/conv-1")

    assert conversations_response.status_code == 200
    assert conversations_response.json()["conversations"][0]["conversation_id"] == "conv-1"
    assert detail_response.status_code == 200
    assert detail_response.json()["messages"][0]["content"] == "你好"


@pytest.mark.asyncio
async def test_api_lists_skills(tmp_path):
    skill_dir = tmp_path / "project-skills" / "weekly-review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: weekly-review
description: 整理本周记录。
---

# Weekly Review
""",
        encoding="utf-8",
    )
    app = create_app(make_web_config(tmp_path))

    response = await request(app, "GET", "/api/skills")

    assert response.status_code == 200
    assert response.json()["skills"][0]["name"] == "weekly-review"
    assert response.json()["skills"][0]["description"] == "整理本周记录。"


@pytest.mark.asyncio
async def test_api_lists_tools(tmp_path):
    app = create_app(make_web_config(tmp_path))

    response = await request(app, "GET", "/api/tools")

    assert response.status_code == 200
    tools = response.json()["tools"]
    bash = next(tool for tool in tools if tool["name"] == "bash")
    assert bash["description"]
    assert "command" in bash["parameters"]["properties"]


@pytest.mark.asyncio
async def test_api_chat_returns_agent_response_and_persists_web_history(tmp_path):
    config = make_web_config(tmp_path)

    with patch("lifeops.agent.LLMClient") as MockLLM:
        mock_llm_instance = AsyncMock()
        mock_llm_instance.chat = AsyncMock(return_value=ChatResponse(content="Web 回复", tool_calls=None))
        MockLLM.return_value = mock_llm_instance
        app = create_app(config)

        response = await request(app, "POST", "/api/chat", json={"message": "Web 问题"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["reply"] == "Web 回复"
    assert payload["conversation_id"]
    records = app.state.history_store.list_records()
    assert [record["source"] for record in records] == ["web", "web"]
    assert [record["content"] for record in records] == ["Web 问题", "Web 回复"]


@pytest.mark.asyncio
async def test_api_chat_reports_missing_llm_api_key_without_crashing(tmp_path):
    app = create_app(make_web_config(tmp_path, api_key=""))

    response = await request(app, "POST", "/api/chat", json={"message": "你好"})

    assert response.status_code == 400
    assert "LLM_API_KEY" in response.json()["detail"]
