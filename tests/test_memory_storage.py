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

    assert SCHEMA_VERSION == 3
    assert version == 3
    assert "conversation_summaries" in tables
    assert "user_preferences" in tables
    assert "knowledge_graph_entities" in tables
    assert "knowledge_graph_relations" in tables
    assert "message_embeddings" in tables
    assert "message_offload_metadata" in tables
    assert "compression_events" in tables


def test_v3_schema_exposes_quality_and_observability_columns(tmp_path):
    db_path = tmp_path / "memory.db"
    store = ConversationHistoryStoreSQLite(db_path)
    store.close()

    conn = sqlite3.connect(db_path)
    summary_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(conversation_summaries)")
    }
    preference_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(user_preferences)")
    }
    entity_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(knowledge_graph_entities)")
    }
    relation_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(knowledge_graph_relations)")
    }
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    conn.close()

    assert {"importance_score", "last_accessed_at", "access_count", "message_count"} <= summary_columns
    assert {
        "preference_type",
        "source_conversation_id",
        "last_observed_at",
        "is_active",
    } <= preference_columns
    assert {"entity_id", "mention_count", "last_mentioned_at", "is_active"} <= entity_columns
    assert {"strength", "mention_count", "last_observed_at", "is_active"} <= relation_columns
    assert "tool_usage_stats" in tables
    assert "memory_config_snapshots" in tables


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
    assert preferences[0]["preference_type"] == "general"
    assert graph["entities"][0]["attributes"] == {"time": "morning"}
    assert graph["entities"][0]["mention_count"] == 1
    assert graph["relations"][0]["relation_type"] == "likes"
    assert graph["relations"][0]["strength"] == 0.9
    assert embedding == [0.4, 0.5]
    assert stats["summaries"] == 1
    assert stats["preferences"] == 1


def test_memory_storage_normalizes_text_confidence_labels(tmp_path):
    store = ConversationHistoryStoreSQLite(tmp_path / "memory.db")

    store.upsert_user_preferences(
        [
            {"key": "exercise_time", "value": "早上", "confidence": "高"},
            {"key": "uncertain", "value": "x", "confidence": "很确定"},
        ]
    )
    store.upsert_knowledge_relations(
        [
            {
                "source": "用户",
                "target": "晨跑",
                "relation_type": "plans",
                "confidence": "中",
            }
        ]
    )

    preferences = store.get_user_preferences()
    graph = store.get_knowledge_graph()
    store.close()

    preferences_by_key = {item["key"]: item for item in preferences}
    assert preferences_by_key["exercise_time"]["confidence"] == 0.9
    assert preferences_by_key["uncertain"]["confidence"] == 0.0
    assert graph["relations"][0]["confidence"] == 0.5
    assert graph["relations"][0]["strength"] == 0.5


def test_memory_observability_and_forget_dry_run(tmp_path):
    store = ConversationHistoryStoreSQLite(tmp_path / "memory.db")
    store.record_skill_usage("weekly-review", activation_type="explicit", success=True)
    store.record_skill_usage("weekly-review", activation_type="implicit", success=False)
    store.record_tool_usage("bash", success=True, duration_ms=12.5)
    store.record_tool_usage("bash", success=False, duration_ms=3.0, error="失败")
    store.record_compression_event("conv-1", "pressure", 0, "上下文达到 70% 压力")
    store.upsert_user_preferences(
        [{"key": "temporary", "value": "x", "confidence": 0.1}]
    )

    dry_run = store.forget_low_value_memories(dry_run=True, preference_confidence_below=0.2)
    skill_usage = store.list_skill_usage()
    tool_stats = store.list_tool_usage_stats()
    events = store.list_compression_events()
    stats_before = store.get_memory_stats()
    real_run = store.forget_low_value_memories(dry_run=False, preference_confidence_below=0.2)
    stats_after = store.get_memory_stats()
    store.close()

    assert dry_run["preferences"] == 1
    assert real_run["preferences"] == 1
    assert stats_before["preferences"] == 1
    assert stats_after["preferences"] == 0
    assert skill_usage[0]["activation_count"] == 2
    assert skill_usage[0]["explicit_activation_count"] == 1
    assert skill_usage[0]["implicit_activation_count"] == 1
    assert skill_usage[0]["success_count"] == 1
    assert skill_usage[0]["failure_count"] == 1
    assert tool_stats[0]["tool_name"] == "bash"
    assert tool_stats[0]["success_count"] == 1
    assert tool_stats[0]["failure_count"] == 1
    assert events[0]["phase"] == "pressure"


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
