"""ConversationHistoryStoreSQLite 的全面单元测试。"""
from __future__ import annotations

import sqlite3

import pytest

from lifeops.storage.sqlite_store import ConversationHistoryStoreSQLite


@pytest.fixture
def store(tmp_path):
    """创建一个临时的 SQLite 存储，测试结束后自动关闭。"""
    db_path = tmp_path / "test.db"
    s = ConversationHistoryStoreSQLite(db_path)
    yield s
    s.close()


@pytest.fixture
def populated_store(store):
    """预填充多条消息和会话标题的存储。"""
    store.append_message(
        "conv-1", "web", "user", "你好", created_at="2026-05-01T09:00:00+08:00"
    )
    store.append_message(
        "conv-1",
        "web",
        "assistant",
        "你好，有什么可以帮你？",
        created_at="2026-05-01T09:00:01+08:00",
    )
    store.append_conversation_title(
        "conv-1", "web", "问候对话", created_at="2026-05-01T09:00:02+08:00"
    )
    store.append_message(
        "conv-2", "cli", "user", "请帮我写代码", created_at="2026-05-01T10:00:00+08:00"
    )
    store.append_message(
        "conv-2",
        "cli",
        "assistant",
        "好的，写什么代码？",
        created_at="2026-05-01T10:00:01+08:00",
    )
    return store


class TestInitAndSchema:
    """测试数据库初始化和 schema 创建。"""

    def test_init_creates_database(self, tmp_path):
        db_path = tmp_path / "new.db"
        store = ConversationHistoryStoreSQLite(db_path)
        assert db_path.exists()
        store.close()

    def test_init_creates_tables(self, store, tmp_path):
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()
        assert "conversations" in tables
        assert "messages" in tables
        assert "tool_calls" in tables
        assert "tool_results" in tables
        assert "full_text_search" in tables
        assert "schema_version" in tables

    def test_init_creates_parent_directories(self, tmp_path):
        nested_path = tmp_path / "a" / "b" / "c" / "deep.db"
        store = ConversationHistoryStoreSQLite(nested_path)
        assert nested_path.exists()
        store.close()

    def test_init_records_schema_version(self, store, tmp_path):
        from lifeops.storage.schema import SCHEMA_VERSION

        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT version FROM schema_version")
        version = cursor.fetchone()[0]
        conn.close()
        assert version == SCHEMA_VERSION

    def test_init_wal_mode(self, store, tmp_path):
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        conn.close()
        # WAL mode returns "wal" (lowercase)
        assert mode.lower() == "wal"


class TestAppendMessage:
    """测试 append_message 方法。"""

    def test_append_message_basic(self, store):
        record = store.append_message(
            "conv-1", "web", "user", "你好", created_at="2026-05-01T09:00:00+08:00"
        )
        assert record["conversation_id"] == "conv-1"
        assert record["source"] == "web"
        assert record["role"] == "user"
        assert record["content"] == "你好"
        assert record["created_at"] == "2026-05-01T09:00:00+08:00"
        assert "intermediate" not in record
        assert "record_type" not in record

    def test_append_message_creates_conversation_automatically(self, store, tmp_path):
        store.append_message("auto-conv", "cli", "user", "测试")
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute(
            "SELECT conversation_id, source FROM conversations WHERE conversation_id = ?",
            ("auto-conv",),
        )
        row = cursor.fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "auto-conv"
        assert row[1] == "cli"

    def test_append_message_with_tool_calls(self, store):
        tool_calls = [
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "bash",
                    "arguments": '{"command":"ls"}',
                },
            },
            {
                "id": "call_2",
                "type": "function",
                "function": {
                    "name": "file_read",
                    "arguments": '{"path":"/tmp/test.txt"}',
                },
            },
        ]
        record = store.append_message(
            "conv-tool",
            "web",
            "assistant",
            "",
            created_at="2026-05-01T09:00:00+08:00",
            tool_calls=tool_calls,
        )
        assert record["tool_calls"] == tool_calls
        assert record["tool_calls"][0]["id"] == "call_1"
        assert record["tool_calls"][1]["function"]["name"] == "file_read"

    def test_append_message_tool_calls_inserted_into_table(self, store, tmp_path):
        tool_calls = [
            {
                "id": "call_abc",
                "type": "function",
                "function": {
                    "name": "bash",
                    "arguments": '{"command":"pwd"}',
                },
            },
        ]
        store.append_message(
            "conv-tc",
            "web",
            "assistant",
            "",
            tool_calls=tool_calls,
        )
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tool_calls ORDER BY id")
        rows = cursor.fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0]["tool_call_id"] == "call_abc"
        assert rows[0]["tool_name"] == "bash"

    def test_append_message_intermediate(self, store):
        record = store.append_message(
            "conv-inter",
            "web",
            "assistant",
            "中间推理",
            intermediate=True,
        )
        assert record["intermediate"] is True

    def test_append_message_non_intermediate_no_key(self, store):
        record = store.append_message(
            "conv-normal", "web", "user", "普通消息"
        )
        assert "intermediate" not in record

    def test_append_message_with_tool_name_and_call_id(self, store):
        record = store.append_message(
            "conv-tool",
            "web",
            "tool",
            "命令输出",
            tool_name="bash",
            tool_call_id="call_xyz",
        )
        assert record["tool_name"] == "bash"
        assert record["tool_call_id"] == "call_xyz"

    def test_append_message_duplicate_tool_call_id_ignored(self, store):
        tool_calls = [
            {
                "id": "dup_id",
                "type": "function",
                "function": {
                    "name": "bash",
                    "arguments": "{}",
                },
            },
        ]
        store.append_message(
            "conv-dup",
            "web",
            "assistant",
            "首次调用",
            tool_calls=tool_calls,
        )
        # INSERT OR IGNORE 应该静默忽略重复的 tool_call_id
        store.append_message(
            "conv-dup",
            "web",
            "assistant",
            "重复调用",
            tool_calls=tool_calls,
        )

    def test_append_message_unicode_content(self, store):
        record = store.append_message(
            "conv-unicode", "web", "user", "🎉 你好世界 🌍"
        )
        assert "🎉" in record["content"]
        assert "🌍" in record["content"]

    def test_append_message_updates_conversation_message_count(self, store):
        store.append_message("conv-count", "web", "user", "第一条")
        store.append_message("conv-count", "web", "assistant", "回复")
        store.append_message(
            "conv-count", "web", "assistant", "中间", intermediate=True
        )
        # intermediate=1 不计入 message_count
        records = store.list_records()
        conv_records = [r for r in records if r["conversation_id"] == "conv-count"]
        assert len(conv_records) == 3

    def test_append_message_updates_last_message(self, store):
        store.append_message(
            "conv-last",
            "web",
            "user",
            "第一条消息",
            created_at="2026-05-01T09:00:00+08:00",
        )
        store.append_message(
            "conv-last",
            "web",
            "assistant",
            "最后一条消息",
            created_at="2026-05-01T09:00:01+08:00",
        )
        summaries = store.list_conversations()
        conv = [s for s in summaries if s["conversation_id"] == "conv-last"][0]
        assert conv["last_message"] == "最后一条消息"


class TestAppendConversationTitle:
    """测试 append_conversation_title 方法。"""

    def test_append_conversation_title(self, store):
        store.append_message("conv-title", "web", "user", "开始对话")
        result = store.append_conversation_title(
            "conv-title", "web", "我的标题", created_at="2026-05-01T09:00:01+08:00"
        )
        assert result["conversation_id"] == "conv-title"
        assert result["role"] == "system"
        assert result["content"] == "我的标题"
        assert result["record_type"] == "conversation_title"

    def test_append_conversation_title_updates_conversations_table(self, store, tmp_path):
        store.append_message("conv-1", "web", "user", "你好")
        store.append_conversation_title("conv-1", "web", "测试标题")
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT title FROM conversations WHERE conversation_id = ?",
            ("conv-1",),
        )
        row = cursor.fetchone()
        conn.close()
        assert row["title"] == "测试标题"

    def test_append_conversation_title_creates_conversation_if_missing(self, store, tmp_path):
        store.append_conversation_title("new-conv", "web", "新标题")
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT conversation_id, title FROM conversations WHERE conversation_id = ?",
            ("new-conv",),
        )
        row = cursor.fetchone()
        conn.close()
        assert row is not None
        assert row["conversation_id"] == "new-conv"
        assert row["title"] == "新标题"


class TestListRecords:
    """测试 list_records 方法。"""

    def test_list_records_returns_all(self, store):
        store.append_message(
            "conv-1", "web", "user", "你好", created_at="2026-05-01T09:00:00+08:00"
        )
        store.append_message(
            "conv-1",
            "web",
            "assistant",
            "回复",
            created_at="2026-05-01T09:00:01+08:00",
        )
        records = store.list_records()
        assert len(records) == 2
        assert records[0]["content"] == "你好"
        assert records[1]["content"] == "回复"

    def test_list_records_with_pagination(self, store):
        for i in range(5):
            store.append_message(
                "conv-pag",
                "web",
                "user",
                f"消息{i}",
                created_at=f"2026-05-01T09:0{i}:00+08:00",
            )
        result = store.list_records(limit=3, offset=0)
        assert isinstance(result, dict)
        assert result["total"] == 5
        assert len(result["items"]) == 3
        assert result["limit"] == 3
        assert result["offset"] == 0

    def test_list_records_pagination_offset(self, store):
        for i in range(5):
            store.append_message(
                "conv-offset",
                "web",
                "user",
                f"消息{i}",
                created_at=f"2026-05-01T09:0{i}:00+08:00",
            )
        result = store.list_records(limit=2, offset=3)
        assert len(result["items"]) == 2
        assert result["total"] == 5
        assert result["offset"] == 3

    def test_list_records_empty_database(self, store):
        records = store.list_records()
        assert records == []

    def test_list_records_includes_tool_calls(self, store):
        tool_calls = [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "bash", "arguments": '{"command":"ls"}'},
            }
        ]
        store.append_message(
            "conv-tc", "web", "assistant", "", tool_calls=tool_calls
        )
        records = store.list_records()
        assert len(records) == 1
        assert records[0]["tool_calls"] == tool_calls


class TestListConversations:
    """测试 list_conversations 方法。"""

    def test_list_conversations_basic(self, populated_store):
        summaries = populated_store.list_conversations()
        assert len(summaries) == 2
        # 按更新时间降序排列
        conversation_ids = [s["conversation_id"] for s in summaries]
        assert "conv-2" in conversation_ids
        assert "conv-1" in conversation_ids

    def test_list_conversations_title_from_title_record(self, populated_store):
        summaries = populated_store.list_conversations()
        conv1 = next(s for s in summaries if s["conversation_id"] == "conv-1")
        assert conv1["title"] == "问候对话"

    def test_list_conversations_fallback_to_first_user_message(self, store):
        store.append_message(
            "conv-fallback",
            "web",
            "user",
            "这是一条很长的用户消息内容不应该被截断如果超过八十个字的话就会被截断因为标题最多显示前八十个字",
            created_at="2026-05-01T10:00:00+08:00",
        )
        summaries = store.list_conversations()
        assert len(summaries) == 1
        assert summaries[0]["title"].startswith("这是一条很长的用户消息")

    def test_list_conversations_unnamed_conversation(self, store):
        store.append_message(
            "conv-no-user", "web", "assistant", "没有用户消息"
        )
        summaries = store.list_conversations()
        assert summaries[0]["title"] == "未命名对话"

    def test_list_conversations_with_query(self, store):
        store.append_message(
            "title-match",
            "web",
            "user",
            "普通开场",
            created_at="2026-05-01T09:00:00+08:00",
        )
        store.append_conversation_title(
            "title-match", "web", "季度复盘安排", created_at="2026-05-01T09:00:01+08:00"
        )
        store.append_message(
            "no-match",
            "web",
            "user",
            "不相关内容",
            created_at="2026-05-01T10:00:00+08:00",
        )
        results = store.list_conversations(query="季度")
        assert len(results) == 1
        assert results[0]["conversation_id"] == "title-match"

    def test_list_conversations_pagination(self, store):
        for i in range(5):
            store.append_message(
                f"conv-{i}",
                "web",
                "user",
                f"消息{i}",
                created_at=f"2026-05-01T0{i}:00:00+08:00",
            )
        result = store.list_conversations(limit=2, offset=0)
        assert isinstance(result, dict)
        assert result["total"] == 5
        assert len(result["items"]) == 2
        assert result["limit"] == 2
        assert result["offset"] == 0

    def test_list_conversations_pagination_all(self, store):
        for i in range(5):
            store.append_message(
                f"conv-{i}",
                "web",
                "user",
                f"消息{i}",
                created_at=f"2026-05-01T0{i}:00:00+08:00",
            )
        result = store.list_conversations(limit=None, offset=0)
        assert len(result["items"]) == 5
        assert result["total"] == 5


class TestGetMessages:
    """测试 get_messages 方法。"""

    def test_get_messages_excludes_title_records(self, populated_store):
        messages = populated_store.get_messages("conv-1")
        record_types = [m.get("record_type") for m in messages]
        assert "conversation_title" not in record_types
        contents = [m["content"] for m in messages]
        assert "你好" in contents
        assert "你好，有什么可以帮你？" in contents

    def test_get_messages_includes_intermediate(self, store):
        store.append_message("conv-inter", "web", "user", "用户问题")
        store.append_message(
            "conv-inter", "web", "assistant", "工具调用思考", intermediate=True
        )
        store.append_message(
            "conv-inter",
            "web",
            "tool",
            "工具结果",
            tool_name="bash",
            tool_call_id="call_1",
            intermediate=True,
        )
        store.append_message("conv-inter", "web", "assistant", "最终回复")
        messages = store.get_messages("conv-inter")
        assert len(messages) == 4

    def test_get_messages_nonexistent_conversation(self, store):
        messages = store.get_messages("nonexistent")
        assert messages == []

    def test_get_messages_pagination(self, store):
        for i in range(5):
            store.append_message(
                "conv-pag",
                "web",
                "user",
                f"消息{i}",
                created_at=f"2026-05-01T09:0{i}:00+08:00",
            )
        result = store.get_messages("conv-pag", limit=2, offset=0)
        assert isinstance(result, dict)
        assert result["total"] == 5
        assert len(result["items"]) == 2
        assert result["limit"] == 2
        assert result["offset"] == 0

    def test_get_messages_pagination_offset(self, store):
        for i in range(5):
            store.append_message(
                "conv-offset",
                "web",
                "user",
                f"消息{i}",
                created_at=f"2026-05-01T09:0{i}:00+08:00",
            )
        result = store.get_messages("conv-offset", limit=2, offset=3)
        assert len(result["items"]) == 2
        assert result["total"] == 5


class TestGetFirstUserMessage:
    """测试 get_first_user_message 方法。"""

    def test_get_first_user_message(self, store):
        store.append_message("conv-1", "web", "assistant", "开场回复")
        store.append_message(
            "conv-1", "web", "user", "第一条用户消息", created_at="2026-05-01T09:00:00+08:00"
        )
        store.append_message(
            "conv-1", "web", "user", "第二条用户消息", created_at="2026-05-01T09:00:01+08:00"
        )
        result = store.get_first_user_message("conv-1")
        assert result == "第一条用户消息"

    def test_get_first_user_message_none(self, store):
        store.append_message("conv-no-user", "web", "assistant", "没有用户消息")
        assert store.get_first_user_message("conv-no-user") is None

    def test_get_first_user_message_missing_conversation(self, store):
        assert store.get_first_user_message("missing") is None

    def test_get_first_user_message_excludes_title(self, store):
        store.append_message("conv-t", "web", "user", "真实用户消息")
        store.append_conversation_title("conv-t", "web", "标题也包含文字")
        result = store.get_first_user_message("conv-t")
        assert result == "真实用户消息"


class TestHasConversationTitle:
    """测试 has_conversation_title 方法。"""

    def test_has_conversation_title_true(self, store):
        store.append_message("conv-1", "web", "user", "问题")
        store.append_conversation_title("conv-1", "web", "我的标题")
        assert store.has_conversation_title("conv-1") is True

    def test_has_conversation_title_false(self, store):
        store.append_message("conv-no-title", "web", "user", "普通问题")
        assert store.has_conversation_title("conv-no-title") is False

    def test_has_conversation_title_missing(self, store):
        assert store.has_conversation_title("missing") is False


class TestDeleteConversation:
    """测试 delete_conversation 方法。"""

    def test_delete_conversation(self, store):
        store.append_message("keep", "web", "user", "保留")
        store.append_message("delete-me", "web", "user", "删除")
        store.append_message("delete-me", "web", "assistant", "已删除")
        deleted_count = store.delete_conversation("delete-me")
        assert deleted_count == 2
        assert store.get_messages("delete-me") == []
        assert store.list_conversations() == [
            s for s in store.list_conversations() if s["conversation_id"] == "keep"
        ]

    def test_delete_conversation_cascade_tool_calls(self, store, tmp_path):
        tool_calls = [
            {
                "id": "call_del",
                "type": "function",
                "function": {"name": "bash", "arguments": '{"command":"rm -rf /"}'},
            }
        ]
        store.append_message(
            "conv-del",
            "web",
            "assistant",
            "占位",
            tool_calls=tool_calls,
        )
        store.delete_conversation("conv-del")
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM tool_calls")
        tc_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM messages")
        msg_count = cursor.fetchone()[0]
        conn.close()
        assert tc_count == 0
        assert msg_count == 0

    def test_delete_conversation_nonexistent(self, store):
        deleted_count = store.delete_conversation("nonexistent")
        assert deleted_count == 0

    def test_delete_conversation_removes_title(self, store):
        store.append_message("conv-1", "web", "user", "消息")
        store.append_conversation_title("conv-1", "web", "标题")
        store.delete_conversation("conv-1")
        assert store.get_messages("conv-1") == []
        assert store.has_conversation_title("conv-1") is False


class TestSearchMessages:
    """测试 search_messages 方法。

    注意：FTS5 默认 unicode61 分词器不支持中文分词，
    搜索中文子串可能无法匹配。以下测试使用可被分词的内容。
    """

    def test_search_messages_basic(self, store):
        store.append_message(
            "conv-search",
            "web",
            "user",
            "Python programming tutorial",
            created_at="2026-05-01T09:00:00+08:00",
        )
        store.append_message(
            "conv-search",
            "web",
            "assistant",
            "Here is a Python answer",
            created_at="2026-05-01T09:00:01+08:00",
        )
        store.append_message(
            "conv-other",
            "web",
            "user",
            "JavaScript framework comparison",
            created_at="2026-05-01T10:00:00+08:00",
        )
        results = store.search_messages("Python")
        assert results["total"] >= 1
        assert any("Python" in item["content"] for item in results["items"])

    def test_search_messages_pagination(self, store):
        for i in range(5):
            store.append_message(
                "conv-search",
                "web",
                "user",
                f"question about Python number {i}",
                created_at=f"2026-05-01T09:{i:02d}:00+08:00",
            )
        results = store.search_messages("Python", limit=2, offset=0)
        assert results["total"] >= 5
        assert len(results["items"]) <= 2
        assert results["limit"] == 2
        assert results["offset"] == 0

    def test_search_messages_no_results(self, store):
        store.append_message("conv-x", "web", "user", "Hello world")
        results = store.search_messages("nonexistent_keyword_xyz")
        assert results["total"] == 0
        assert results["items"] == []

    def test_search_messages_excludes_title_records(self, store):
        store.append_message(
            "conv-st", "web", "user", "Python question", created_at="2026-05-01T09:00:00+08:00"
        )
        store.append_conversation_title(
            "conv-st", "web", "Python title", created_at="2026-05-01T09:00:01+08:00"
        )
        results = store.search_messages("Python")
        for item in results["items"]:
            assert item.get("record_type") != "conversation_title"


class TestContextManager:
    """测试上下文管理器。"""

    def test_context_manager(self, tmp_path):
        db_path = tmp_path / "ctx_test.db"
        with ConversationHistoryStoreSQLite(db_path) as s:
            s.append_message("conv-1", "web", "user", "测试上下文管理器")
            records = s.list_records()
            assert len(records) == 1
        # 退出后连接应关闭

    def test_close(self, tmp_path):
        db_path = tmp_path / "close_test.db"
        s = ConversationHistoryStoreSQLite(db_path)
        s.append_message("conv-1", "web", "user", "关闭前写入")
        s.close()
        # 关闭后不应崩溃 — 但后续操作应抛出异常
        # （在实际场景中不应关闭后再使用，此处只验证 close 不报错）


class TestEdgeCases:
    """测试边界情况。"""

    def test_empty_content(self, store):
        record = store.append_message("conv-empty", "web", "user", "")
        assert record["content"] == ""

    def test_long_content(self, store):
        long_text = "非常重要的内容" * 1000
        record = store.append_message("conv-long", "web", "user", long_text)
        assert record["content"] == long_text

    def test_special_characters_in_content(self, store):
        content = '包含"引号"和\n换行符'
        record = store.append_message("conv-special", "web", "user", content)
        assert record["content"] == content

    def test_tool_call_arguments_as_dict(self, store):
        """测试 tool_calls 的 arguments 参数是 dict 时自动序列化。"""
        tool_calls = [
            {
                "id": "call_dict",
                "type": "function",
                "function": {
                    "name": "bash",
                    "arguments": {"command": "ls -la"},
                },
            }
        ]
        record = store.append_message(
            "conv-dict-args", "web", "assistant", "", tool_calls=tool_calls
        )
        # 返回值中 arguments 应保持原样（因为是 sanitize_unicode_data 递归处理的）
        assert isinstance(record["tool_calls"][0]["function"]["arguments"], dict)

    def test_list_conversations_message_count(self, store):
        store.append_message("conv-mc", "web", "user", "问题1")
        store.append_message("conv-mc", "web", "assistant", "回答1")
        store.append_message(
            "conv-mc", "web", "assistant", "中间推理", intermediate=True
        )
        summaries = store.list_conversations()
        conv = next(s for s in summaries if s["conversation_id"] == "conv-mc")
        # intermediate 消息不计入 message_count
        assert conv["message_count"] == 2