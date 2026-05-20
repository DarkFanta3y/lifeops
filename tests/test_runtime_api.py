from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from lifeops.core.config import AppConfig, LLMConfig, SkillsConfig, ToolPolicyConfig
from lifeops.llm.types import ChatResponse
from lifeops.web.api import create_app


def make_config(tmp_path, policy_mode: str = "balanced") -> AppConfig:
    return AppConfig(
        llm=LLMConfig(api_key="test-key", model="gpt-4o"),
        skills=SkillsConfig(
            enabled=True,
            project_dir=str(tmp_path / "project-skills"),
            user_dir=str(tmp_path / "user-skills"),
            implicit_match_enabled=False,
        ),
        tool_policy=ToolPolicyConfig(mode=policy_mode),
        db_path=str(tmp_path / "conversations.db"),
        history_path=str(tmp_path / "history.jsonl"),
    )


async def request(app, method: str, url: str, **kwargs):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, url, **kwargs)


def collect_sse_events(response: httpx.Response) -> list[dict]:
    events = []
    for line in response.text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


@pytest.mark.asyncio
async def test_chat_done_includes_run_id_and_run_api_returns_events(tmp_path):
    config = make_config(tmp_path)

    async def mock_chat(messages, tools=None, **kwargs):
        if not hasattr(mock_chat, "called"):
            mock_chat.called = True
            return ChatResponse(
                content='{"should_use_rag": false, "should_use_web": false, '
                '"rag_query": null, "web_query": null, "reason": "无需检索"}',
                tool_calls=None,
            )
        return ChatResponse(content="你好", tool_calls=None)

    with (
        patch("lifeops.agent.LLMClient") as MockLLM,
        patch("lifeops.web.api.summarize_conversation_title", new=AsyncMock(return_value="标题")),
    ):
        mock_llm_instance = AsyncMock()
        mock_llm_instance.chat = AsyncMock(side_effect=mock_chat)
        MockLLM.return_value = mock_llm_instance
        app = create_app(config)

        response = await request(app, "POST", "/api/chat", json={"message": "你好"})

    done = [event for event in collect_sse_events(response) if event["type"] == "done"][0]
    run_id = done["data"]["run_id"]
    assert done["data"]["status"] == "completed"

    run_response = await request(app, "GET", f"/api/runs/{run_id}")
    assert run_response.status_code == 200
    payload = run_response.json()
    assert payload["run"]["run_id"] == run_id
    assert "run_started" in [event["event_type"] for event in payload["events"]]
    assert "run_completed" in [event["event_type"] for event in payload["events"]]

    runs_response = await request(
        app, "GET", f"/api/conversations/{done['data']['conversation_id']}/runs"
    )
    assert runs_response.status_code == 200
    assert runs_response.json()["runs"][0]["run_id"] == run_id


@pytest.mark.asyncio
async def test_missing_run_returns_404_and_policy_api_is_public_summary(tmp_path):
    app = create_app(make_config(tmp_path, policy_mode="strict"))

    missing = await request(app, "GET", "/api/runs/missing")
    assert missing.status_code == 404

    policy = await request(app, "GET", "/api/tools/policy")
    assert policy.status_code == 200
    payload = policy.json()
    assert payload["mode"] == "strict"
    assert "allow_tools" in payload
    assert "test-key" not in str(payload)
