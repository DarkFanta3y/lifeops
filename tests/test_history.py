from __future__ import annotations

import json

from lifeops.history import ConversationHistoryStore


def test_history_store_reads_empty_missing_file(tmp_path):
    store = ConversationHistoryStore(tmp_path / "missing.jsonl")

    assert store.list_records() == []
    assert store.list_conversations() == []


def test_history_store_appends_and_reads_records(tmp_path):
    store = ConversationHistoryStore(tmp_path / "history.jsonl")

    first = store.append_message(
        conversation_id="conv-1",
        source="cli",
        role="user",
        content="你好",
        created_at="2026-05-01T10:00:00+08:00",
    )
    second = store.append_message(
        conversation_id="conv-1",
        source="cli",
        role="assistant",
        content="你好，有什么可以帮你？",
        created_at="2026-05-01T10:00:01+08:00",
    )

    records = store.list_records()
    assert records == [first, second]
    assert records[0]["conversation_id"] == "conv-1"
    assert records[0]["source"] == "cli"
    assert records[0]["role"] == "user"
    assert records[0]["content"] == "你好"


def test_history_store_skips_damaged_jsonl_lines(tmp_path):
    path = tmp_path / "history.jsonl"
    path.write_text(
        "\n".join(
            [
                "{broken",
                json.dumps(
                    {
                        "conversation_id": "conv-1",
                        "source": "web",
                        "role": "assistant",
                        "content": "ok",
                        "created_at": "2026-05-01T10:00:00+08:00",
                    },
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )

    store = ConversationHistoryStore(path)

    assert len(store.list_records()) == 1
    assert store.list_records()[0]["content"] == "ok"


def test_history_store_groups_conversation_summaries(tmp_path):
    store = ConversationHistoryStore(tmp_path / "history.jsonl")
    store.append_message(
        conversation_id="older",
        source="cli",
        role="user",
        content="旧对话",
        created_at="2026-05-01T09:00:00+08:00",
    )
    store.append_message(
        conversation_id="newer",
        source="web",
        role="user",
        content="新对话问题",
        created_at="2026-05-01T10:00:00+08:00",
    )
    store.append_message(
        conversation_id="newer",
        source="web",
        role="assistant",
        content="新对话回答",
        created_at="2026-05-01T10:00:01+08:00",
    )

    summaries = store.list_conversations()

    assert [summary["conversation_id"] for summary in summaries] == ["newer", "older"]
    assert summaries[0]["source"] == "web"
    assert summaries[0]["message_count"] == 2
    assert summaries[0]["last_message"] == "新对话回答"
    assert summaries[0]["updated_at"] == "2026-05-01T10:00:01+08:00"


def test_history_store_filters_messages_by_conversation(tmp_path):
    store = ConversationHistoryStore(tmp_path / "history.jsonl")
    store.append_message("conv-1", "cli", "user", "one")
    store.append_message("conv-2", "web", "user", "two")

    messages = store.get_messages("conv-2")

    assert len(messages) == 1
    assert messages[0]["content"] == "two"
