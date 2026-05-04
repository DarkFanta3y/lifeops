"""SQLite 存储层性能基准测试。"""
from __future__ import annotations

import time

import pytest

from lifeops.storage.sqlite_store import ConversationHistoryStoreSQLite


@pytest.fixture
def store(tmp_path):
    s = ConversationHistoryStoreSQLite(tmp_path / "perf.db")
    yield s
    s.close()


def _insert_messages(store, count, conversation_id="perf-conv", source="web"):
    ts_template = "2026-05-01T09:{:02d}:{:02d}+08:00"
    for i in range(count):
        role = "user" if i % 2 == 0 else "assistant"
        store.append_message(
            conversation_id,
            source,
            role,
            f"消息内容{i}",
            created_at=ts_template.format(i % 60, i % 60),
        )


class TestPerformance:
    """性能基准：确保常见查询在合理时间内完成。"""

    def test_list_conversations_performance(self, store):
        for conv_idx in range(100):
            conv_id = f"perf-conv-{conv_idx:03d}"
            ts = f"2026-05-01T{conv_idx % 24:02d}:{conv_idx % 60:02d}:00+08:00"
            store.append_message(conv_id, "web", "user", f"对话{conv_idx}", created_at=ts)
            for msg_idx in range(10):
                store.append_message(
                    conv_id,
                    "web",
                    "assistant" if msg_idx % 2 else "user",
                    f"内容{conv_idx}-{msg_idx}",
                    created_at=ts,
                )

        start = time.perf_counter()
        result = store.list_conversations()
        elapsed = time.perf_counter() - start

        assert len(result) == 100
        assert elapsed < 0.5, f"list_conversations 耗时 {elapsed:.3f}s，超过 500ms 阈值"

    def test_list_conversations_with_query_performance(self, store):
        for conv_idx in range(50):
            conv_id = f"perf-search-{conv_idx:03d}"
            ts = f"2026-05-01T{conv_idx % 24:02d}:00:00+08:00"
            store.append_message(conv_id, "web", "user", f"查询{conv_idx}", created_at=ts)
            if conv_idx % 5 == 0:
                store.append_conversation_title(conv_id, "web", f"绩效{conv_idx}", created_at=ts)

        start = time.perf_counter()
        result = store.list_conversations(query="绩效")
        elapsed = time.perf_counter() - start

        assert len(result) > 0
        assert elapsed < 0.5, f"list_conversations(query) 耗时 {elapsed:.3f}s，超过 500ms 阈值"

    def test_search_messages_performance(self, store):
        for i in range(100):
            store.append_message(
                "perf-search",
                "web",
                "user" if i % 2 == 0 else "assistant",
                f"Python programming content {i}",
                created_at=f"2026-05-01T09:{i // 60:02d}:{i % 60:02d}+08:00",
            )

        start = time.perf_counter()
        result = store.search_messages("Python", limit=20, offset=0)
        elapsed = time.perf_counter() - start

        assert result["total"] >= 100
        assert elapsed < 0.5, f"search_messages 耗时 {elapsed:.3f}s，超过 500ms 阈值"

    def test_pagination_performance(self, store):
        for i in range(200):
            store.append_message(
                "perf-pag",
                "web",
                "user" if i % 2 == 0 else "assistant",
                f"分页消息{i}",
                created_at=f"2026-05-01T{i // 3600:02d}:{(i // 60) % 60:02d}:{i % 60:02d}+08:00",
            )

        for offset in range(0, 200, 50):
            start = time.perf_counter()
            result = store.get_messages("perf-pag", limit=10, offset=offset)
            elapsed = time.perf_counter() - start
            assert elapsed < 0.1, f"get_messages(offset={offset}) 耗时 {elapsed:.3f}s，超过 100ms 阈值"
            assert result["total"] == 200

    def test_get_messages_performance(self, store):
        for i in range(100):
            store.append_message(
                "perf-msgs",
                "web",
                "user" if i % 2 == 0 else "assistant",
                f"消息{i}",
                created_at=f"2026-05-01T09:{i // 60:02d}:{i % 60:02d}+08:00",
            )

        start = time.perf_counter()
        messages = store.get_messages("perf-msgs")
        elapsed = time.perf_counter() - start

        assert len(messages) == 100
        assert elapsed < 0.5, f"get_messages 耗时 {elapsed:.3f}s，超过 500ms 阈值"

    def test_delete_conversation_performance(self, store):
        for conv_idx in range(10):
            conv_id = f"perf-del-{conv_idx:03d}"
            for msg_idx in range(100):
                store.append_message(
                    conv_id,
                    "web",
                    "user" if msg_idx % 2 == 0 else "assistant",
                    f"内容{msg_idx}",
                    created_at=f"2026-05-01T09:{msg_idx % 60:02d}:{msg_idx // 60:02d}+08:00",
                )

        start = time.perf_counter()
        store.delete_conversation("perf-del-005")
        elapsed = time.perf_counter() - start

        assert elapsed < 0.5, f"delete_conversation 耗时 {elapsed:.3f}s，超过 500ms 阈值"
        remaining = store.list_conversations()
        assert len(remaining) == 9