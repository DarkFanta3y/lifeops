from __future__ import annotations

import sqlite3

from lifeops.storage.schema import SCHEMA_VERSION
from lifeops.storage.sqlite_store import ConversationHistoryStoreSQLite


def test_v2_schema_creates_memory_tables(tmp_path):
    db_path = tmp_path / "memory.db"
    store = ConversationHistoryStoreSQLite(db_path)
    store.close()

    conn = sqlite3.connect(db_path)
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
    conn.close()

    assert SCHEMA_VERSION == 2
    assert version == 2
    assert "conversation_summaries" in tables
    assert "user_preferences" in tables
    assert "knowledge_graph_entities" in tables
    assert "knowledge_graph_relations" in tables
    assert "message_embeddings" in tables
    assert "message_offload_metadata" in tables
    assert "compression_events" in tables


def test_memory_crud_upserts_and_embedding_roundtrip(tmp_path):
    store = ConversationHistoryStoreSQLite(tmp_path / "memory.db")
    store.append_message("conv-1", "web", "user", "我喜欢早上跑步")

    store.insert_or_update_conversation_summary(
        {
            "conversation_id": "conv-1",
            "summary": "用户喜欢早上跑步。",
            "key_decisions": ["保留晨跑习惯"],
            "action_items": ["安排跑步计划"],
            "topics": ["健康"],
            "tone": "务实",
            "embedding": [0.1, 0.2, 0.3],
        }
    )
    store.upsert_user_preferences(
        [
            {
                "key": "exercise_time",
                "value": "早上",
                "confidence": 0.8,
                "evidence": "用户说喜欢早上跑步",
            }
        ]
    )
    store.upsert_knowledge_entities(
        [{"name": "跑步", "entity_type": "habit", "attributes": {"time": "morning"}}]
    )
    store.upsert_knowledge_relations(
        [{"source": "用户", "target": "跑步", "relation_type": "likes", "confidence": 0.9}]
    )
    store.record_message_embedding("conv-1", 1, [0.4, 0.5])

    store.insert_or_update_conversation_summary(
        {
            "conversation_id": "conv-1",
            "summary": "用户偏好晨跑。",
            "key_decisions": [],
            "action_items": [],
            "topics": ["健康", "习惯"],
            "tone": "简洁",
            "embedding": [0.1, 0.2, 0.4],
        }
    )

    summaries = store.list_conversation_summaries()
    preferences = store.get_user_preferences(min_confidence=0.7)
    graph = store.get_knowledge_graph()
    embedding = store.get_message_embedding(1)
    stats = store.get_memory_stats()
    store.close()

    assert len(summaries) == 1
    assert summaries[0]["summary"] == "用户偏好晨跑。"
    assert summaries[0]["topics"] == ["健康", "习惯"]
    assert summaries[0]["embedding"] == [0.1, 0.2, 0.4]
    assert preferences[0]["observation_count"] == 1
    assert graph["entities"][0]["attributes"] == {"time": "morning"}
    assert graph["relations"][0]["relation_type"] == "likes"
    assert embedding == [0.4, 0.5]
    assert stats["summaries"] == 1
    assert stats["preferences"] == 1


def test_delete_conversation_cascades_memory_rows_but_keeps_global_profile(tmp_path):
    store = ConversationHistoryStoreSQLite(tmp_path / "memory.db")
    store.append_message("conv-1", "web", "user", "测试")
    store.insert_or_update_conversation_summary(
        {"conversation_id": "conv-1", "summary": "摘要"}
    )
    store.record_message_embedding("conv-1", 1, [0.1])
    store.record_offload_metadata("conv-1", "tool_1", "/tmp/tool.txt", 10, "摘要")
    store.record_compression_event(
        conversation_id="conv-1",
        phase="critical",
        freed_tokens=10,
        reason="测试",
    )
    store.upsert_user_preferences(
        [{"key": "language", "value": "中文", "confidence": 0.9}]
    )
    store.upsert_knowledge_entities([{"name": "中文", "entity_type": "preference"}])

    assert store.delete_conversation("conv-1") == 1

    stats = store.get_memory_stats()
    store.close()
    assert stats["summaries"] == 0
    assert stats["compression_events"] == 0
    assert stats["preferences"] == 1
    assert stats["entities"] == 1
