from __future__ import annotations

import httpx
import pytest

from lifeops.core.config import AppConfig, LLMConfig, SkillsConfig
from lifeops.storage.sqlite_store import ConversationHistoryStoreSQLite
from lifeops.web.api import create_app


def test_conversation_pagination_and_title_search_run_in_sql(tmp_path):
    store = ConversationHistoryStoreSQLite(tmp_path / "history.db")
    try:
        for index in range(4):
            conversation_id = f"conv-{index}"
            store.append_message(
                conversation_id,
                "web",
                "user",
                f"主题 {index}",
                created_at=f"2026-01-01T00:00:0{index}+00:00",
            )

        first_page = store.list_conversations(limit=2, offset=0)
        second_page = store.list_conversations(limit=2, offset=2)
        empty_page = store.list_conversations(limit=2, offset=99)
        unpaged = store.list_conversations()
        search = store.list_conversations(query="主题 2", limit=20, offset=0)

        assert first_page["total"] == 4
        assert isinstance(unpaged, list)
        assert len(unpaged) == 4
        assert len(first_page["items"]) == 2
        assert len(second_page["items"]) == 2
        assert empty_page["items"] == []
        assert empty_page["total"] == 4
        assert {
            item["conversation_id"] for item in first_page["items"] + second_page["items"]
        } == {f"conv-{index}" for index in range(4)}
        assert [item["conversation_id"] for item in search["items"]] == ["conv-2"]

        store.delete_conversation("conv-0")
        tail = store.list_conversations(limit=2, offset=2)
        assert tail["total"] == 3
        assert len(tail["items"]) == 1
    finally:
        store.close()


def test_message_cursor_is_stable_when_new_messages_arrive(tmp_path):
    store = ConversationHistoryStoreSQLite(tmp_path / "history.db")
    try:
        for index in range(6):
            store.append_message("conv", "web", "user", f"message-{index}")

        latest = store.get_messages_cursor("conv", limit=3)
        assert [item["content"] for item in latest["items"]] == [
            "message-3",
            "message-4",
            "message-5",
        ]
        assert latest["has_more"] is True
        before_id = latest["next_before_id"]

        store.append_message("conv", "web", "assistant", "new-message")
        older = store.get_messages_cursor("conv", limit=3, before_id=before_id)

        assert [item["content"] for item in older["items"]] == [
            "message-0",
            "message-1",
            "message-2",
        ]
        assert older["has_more"] is False
        assert not {
            item["message_id"] for item in latest["items"]
        }.intersection(item["message_id"] for item in older["items"])
    finally:
        store.close()


@pytest.mark.asyncio
async def test_conversation_cursor_api_splits_visible_and_intermediate_messages(tmp_path):
    config = AppConfig(
        llm=LLMConfig(api_key="test-key"),
        skills=SkillsConfig(enabled=False),
        db_path=str(tmp_path / "history.db"),
        history_path=str(tmp_path / "history.jsonl"),
    )
    app = create_app(config)
    store = app.state.history_store
    store.append_message("conv", "web", "user", "hello")
    store.append_message("conv", "web", "assistant", "tool call", intermediate=True)
    store.append_message(
        "conv",
        "web",
        "tool",
        "tool result",
        tool_name="demo",
        tool_call_id="tc-1",
        intermediate=True,
    )
    store.append_message("conv", "web", "assistant", "done")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/conversations/conv?latest=true&limit=3")
        invalid = await client.get(
            "/api/conversations/conv?latest=true&limit=3&offset=0"
        )

    assert response.status_code == 200
    payload = response.json()
    assert [item["content"] for item in payload["messages"]] == ["done"]
    assert [item["content"] for item in payload["intermediate_messages"]] == [
        "tool call",
        "tool result",
    ]
    assert payload["has_more"] is True
    assert payload["next_before_id"] is not None
    assert all("message_id" in item for item in [
        *payload["messages"],
        *payload["intermediate_messages"],
    ])
    assert invalid.status_code == 422
    store.close()
