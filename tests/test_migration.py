"""JSONL → SQLite 迁移和 Web API 集成测试。"""
from __future__ import annotations

import json
from pathlib import Path
import httpx
import pytest

from lifeops.core.config import AppConfig, LLMConfig, SkillsConfig
from lifeops.storage.migration import (
    auto_migrate,
    migrate_jsonl_to_sqlite,
    should_migrate,
)
from lifeops.storage.sqlite_store import ConversationHistoryStoreSQLite
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
        db_path=str(tmp_path / "conversations.db"),
    )


def write_jsonl_lines(path: Path, lines: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")


class TestMigrateJsonlToSqlite:
    """测试 migrate_jsonl_to_sqlite 函数。"""

    def test_migrate_jsonl_to_sqlite_basic(self, tmp_path):
        jsonl_path = tmp_path / "history.jsonl"
        db_path = tmp_path / "conversations.db"
        lines = [
            {
                "conversation_id": "conv-1",
                "source": "web",
                "role": "user",
                "content": "你好",
                "created_at": "2026-05-01T09:00:00+08:00",
            },
            {
                "conversation_id": "conv-1",
                "source": "web",
                "role": "assistant",
                "content": "你好，有什么可以帮你？",
                "created_at": "2026-05-01T09:00:01+08:00",
            },
        ]
        write_jsonl_lines(jsonl_path, lines)

        result = migrate_jsonl_to_sqlite(jsonl_path, db_path)

        assert result["total"] == 2
        assert result["success"] == 2
        assert result["failed"] == 0
        store = ConversationHistoryStoreSQLite(db_path)
        records = store.list_records()
        assert len(records) == 2
        assert records[0]["content"] == "你好"
        assert records[1]["content"] == "你好，有什么可以帮你？"
        store.close()

    def test_migrate_jsonl_with_title_record(self, tmp_path):
        jsonl_path = tmp_path / "history.jsonl"
        db_path = tmp_path / "conversations.db"
        lines = [
            {
                "conversation_id": "conv-1",
                "source": "web",
                "role": "user",
                "content": "开始对话",
                "created_at": "2026-05-01T09:00:00+08:00",
            },
            {
                "conversation_id": "conv-1",
                "source": "web",
                "role": "system",
                "content": "我的标题",
                "created_at": "2026-05-01T09:00:01+08:00",
                "record_type": "conversation_title",
            },
        ]
        write_jsonl_lines(jsonl_path, lines)

        result = migrate_jsonl_to_sqlite(jsonl_path, db_path)

        assert result["success"] == 2
        store = ConversationHistoryStoreSQLite(db_path)
        assert store.has_conversation_title("conv-1")
        summaries = store.list_conversations()
        conv = next(s for s in summaries if s["conversation_id"] == "conv-1")
        assert conv["title"] == "我的标题"
        store.close()

    def test_migrate_jsonl_with_tool_calls(self, tmp_path):
        jsonl_path = tmp_path / "history.jsonl"
        db_path = tmp_path / "conversations.db"
        lines = [
            {
                "conversation_id": "conv-tool",
                "source": "web",
                "role": "user",
                "content": "运行命令",
                "created_at": "2026-05-01T09:00:00+08:00",
            },
            {
                "conversation_id": "conv-tool",
                "source": "web",
                "role": "assistant",
                "content": "",
                "created_at": "2026-05-01T09:00:01+08:00",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "bash",
                            "arguments": '{"command":"ls"}',
                        },
                    }
                ],
                "intermediate": True,
            },
        ]
        write_jsonl_lines(jsonl_path, lines)

        result = migrate_jsonl_to_sqlite(jsonl_path, db_path)

        assert result["success"] == 2
        store = ConversationHistoryStoreSQLite(db_path)
        records = store.list_records()
        assert records[1]["intermediate"] is True
        assert records[1]["tool_calls"][0]["id"] == "call_1"
        store.close()

    def test_migrate_jsonl_with_intermediate_record(self, tmp_path):
        jsonl_path = tmp_path / "history.jsonl"
        db_path = tmp_path / "conversations.db"
        lines = [
            {
                "conversation_id": "conv-inter",
                "source": "web",
                "role": "user",
                "content": "问题",
                "created_at": "2026-05-01T09:00:00+08:00",
            },
            {
                "conversation_id": "conv-inter",
                "source": "web",
                "role": "assistant",
                "content": "中间思考",
                "created_at": "2026-05-01T09:00:01+08:00",
                "intermediate": True,
            },
        ]
        write_jsonl_lines(jsonl_path, lines)

        result = migrate_jsonl_to_sqlite(jsonl_path, db_path)

        assert result["success"] == 2
        store = ConversationHistoryStoreSQLite(db_path)
        records = store.list_records()
        assert "intermediate" not in records[0]
        assert records[1]["intermediate"] is True
        store.close()

    def test_migrate_jsonl_dry_run(self, tmp_path):
        jsonl_path = tmp_path / "history.jsonl"
        db_path = tmp_path / "conversations.db"
        lines = [
            {
                "conversation_id": "conv-1",
                "source": "web",
                "role": "user",
                "content": "你好",
                "created_at": "2026-05-01T09:00:00+08:00",
            },
        ]
        write_jsonl_lines(jsonl_path, lines)

        result = migrate_jsonl_to_sqlite(jsonl_path, db_path, dry_run=True)

        assert result["total"] == 1
        assert result["success"] == 1
        assert result["failed"] == 0
        assert not db_path.exists()

    def test_migrate_jsonl_with_invalid_lines(self, tmp_path):
        jsonl_path = tmp_path / "history.jsonl"
        db_path = tmp_path / "conversations.db"
        lines = [
            {
                "conversation_id": "conv-1",
                "source": "web",
                "role": "user",
                "content": "有效消息",
                "created_at": "2026-05-01T09:00:00+08:00",
            },
            {"broken": "data"},
            {
                "conversation_id": "conv-1",
                "source": "web",
                "role": "assistant",
                "content": "有效回复",
                "created_at": "2026-05-01T09:00:01+08:00",
            },
        ]
        write_jsonl_lines(jsonl_path, lines)

        result = migrate_jsonl_to_sqlite(jsonl_path, db_path)

        assert result["total"] == 3
        assert result["success"] == 2
        assert result["failed"] == 1
        assert len(result["errors"]) == 1

    def test_migrate_jsonl_with_malformed_json(self, tmp_path):
        jsonl_path = tmp_path / "history.jsonl"
        db_path = tmp_path / "conversations.db"
        jsonl_path.write_text(
            '{not valid json}\n'
            '{"conversation_id":"c1","source":"web","role":"user","content":"ok","created_at":"2026-05-01T09:00:00+08:00"}\n',
            encoding="utf-8",
        )

        result = migrate_jsonl_to_sqlite(jsonl_path, db_path)

        assert result["total"] == 2
        assert result["success"] == 1
        assert result["failed"] == 1

    def test_migrate_jsonl_missing_jsonl_file(self, tmp_path):
        jsonl_path = tmp_path / "nonexistent.jsonl"
        db_path = tmp_path / "conversations.db"

        result = migrate_jsonl_to_sqlite(jsonl_path, db_path)

        assert result["total"] == 0
        assert result["success"] == 0
        assert result["failed"] == 0

    def test_migrate_jsonl_empty_lines_skipped(self, tmp_path):
        jsonl_path = tmp_path / "history.jsonl"
        db_path = tmp_path / "conversations.db"
        jsonl_path.write_text(
            '\n'
            '{"conversation_id":"c1","source":"web","role":"user","content":"ok","created_at":"2026-05-01T09:00:00+08:00"}\n'
            '\n',
            encoding="utf-8",
        )

        result = migrate_jsonl_to_sqlite(jsonl_path, db_path)

        assert result["total"] == 1
        assert result["success"] == 1
        assert result["failed"] == 0

    def test_migrate_jsonl_with_tool_name_and_call_id(self, tmp_path):
        jsonl_path = tmp_path / "history.jsonl"
        db_path = tmp_path / "conversations.db"
        lines = [
            {
                "conversation_id": "conv-leg",
                "source": "web",
                "role": "user",
                "content": "运行命令",
                "created_at": "2026-05-01T09:00:00+08:00",
            },
            {
                "conversation_id": "conv-leg",
                "source": "web",
                "role": "tool",
                "content": "命令输出",
                "created_at": "2026-05-01T09:00:01+08:00",
                "tool_name": "bash",
                "tool_call_id": "call_legacy",
            },
        ]
        write_jsonl_lines(jsonl_path, lines)

        result = migrate_jsonl_to_sqlite(jsonl_path, db_path)

        assert result["success"] == 2
        store = ConversationHistoryStoreSQLite(db_path)
        records = store.list_records()
        assert records[1]["tool_name"] == "bash"
        assert records[1]["tool_call_id"] == "call_legacy"
        store.close()


class TestShouldMigrate:
    """测试 should_migrate 函数。"""

    def test_should_migrate_true_jsonl_exists_db_missing(self, tmp_path):
        jsonl_path = tmp_path / "history.jsonl"
        db_path = tmp_path / "conversations.db"
        jsonl_path.write_text("some data", encoding="utf-8")

        assert should_migrate(jsonl_path, db_path) is True

    def test_should_migrate_false_db_exists_with_data(self, tmp_path):
        jsonl_path = tmp_path / "history.jsonl"
        db_path = tmp_path / "conversations.db"
        jsonl_path.write_text("some data", encoding="utf-8")
        store = ConversationHistoryStoreSQLite(db_path)
        store.append_message("conv-1", "web", "user", "已有数据")
        store.close()

        assert should_migrate(jsonl_path, db_path) is False

    def test_should_migrate_true_db_exists_but_empty(self, tmp_path):
        jsonl_path = tmp_path / "history.jsonl"
        db_path = tmp_path / "conversations.db"
        jsonl_path.write_text("some data", encoding="utf-8")
        ConversationHistoryStoreSQLite(db_path).close()

        assert should_migrate(jsonl_path, db_path) is True

    def test_should_migrate_false_jsonl_missing(self, tmp_path):
        jsonl_path = tmp_path / "nonexistent.jsonl"
        db_path = tmp_path / "conversations.db"

        assert should_migrate(jsonl_path, db_path) is False

    def test_should_migrate_true_db_corrupted(self, tmp_path):
        jsonl_path = tmp_path / "history.jsonl"
        db_path = tmp_path / "conversations.db"
        jsonl_path.write_text("some data", encoding="utf-8")
        db_path.write_text("not a database", encoding="utf-8")

        assert should_migrate(jsonl_path, db_path) is True


class TestAutoMigrate:
    """测试 auto_migrate 函数。"""

    def test_auto_migrate_success(self, tmp_path):
        jsonl_path = tmp_path / "history.jsonl"
        db_path = tmp_path / "conversations.db"
        lines = [
            {
                "conversation_id": "conv-1",
                "source": "web",
                "role": "user",
                "content": "迁移测试",
                "created_at": "2026-05-01T09:00:00+08:00",
            },
        ]
        write_jsonl_lines(jsonl_path, lines)

        result = auto_migrate(jsonl_path, db_path)

        assert result is not None
        assert result["success"] == 1
        store = ConversationHistoryStoreSQLite(db_path)
        records = store.list_records()
        assert len(records) == 1
        assert records[0]["content"] == "迁移测试"
        store.close()

    def test_auto_migrate_idempotent(self, tmp_path):
        jsonl_path = tmp_path / "history.jsonl"
        db_path = tmp_path / "conversations.db"
        lines = [
            {
                "conversation_id": "conv-1",
                "source": "web",
                "role": "user",
                "content": "幂等测试",
                "created_at": "2026-05-01T09:00:00+08:00",
            },
        ]
        write_jsonl_lines(jsonl_path, lines)

        first_result = auto_migrate(jsonl_path, db_path)
        assert first_result is not None
        assert first_result["success"] == 1

        second_result = auto_migrate(jsonl_path, db_path)
        assert second_result is None

        store = ConversationHistoryStoreSQLite(db_path)
        records = store.list_records()
        assert len(records) == 1
        store.close()

    def test_auto_migrate_no_jsonl_file(self, tmp_path):
        jsonl_path = tmp_path / "nonexistent.jsonl"
        db_path = tmp_path / "conversations.db"

        result = auto_migrate(jsonl_path, db_path)

        assert result is None

    def test_auto_migrate_with_jsonl_errors(self, tmp_path):
        jsonl_path = tmp_path / "history.jsonl"
        db_path = tmp_path / "conversations.db"
        jsonl_path.write_text(
            "invalid json line\n"
            '{"conversation_id":"c1","source":"web","role":"user","content":"ok","created_at":"2026-05-01T09:00:00+08:00"}\n',
            encoding="utf-8",
        )

        result = auto_migrate(jsonl_path, db_path)

        assert result is not None
        assert result["success"] == 1
        assert result["failed"] == 1


class TestMigrationApiIntegration:
    """测试迁移与 Web API 的集成。

    注意：httpx.AsyncClient 不触发 ASGI lifespan 事件，
    因此需要手动执行 auto_migrate 来模拟 Web 启动时的迁移行为。
    """

    async def request(self, app, method: str, url: str, **kwargs):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, url, **kwargs)

    @pytest.mark.asyncio
    async def test_lifespan_auto_migrates_jsonl_on_startup(self, tmp_path):
        jsonl_path = tmp_path / "history.jsonl"
        db_path = tmp_path / "conversations.db"
        lines = [
            {
                "conversation_id": "conv-migrated",
                "source": "web",
                "role": "user",
                "content": "迁移后加载",
                "created_at": "2026-05-01T09:00:00+08:00",
            },
        ]
        write_jsonl_lines(jsonl_path, lines)

        auto_migrate(jsonl_path, db_path)

        config = AppConfig(
            llm=LLMConfig(api_key="test-key", model="gpt-4o"),
            skills=SkillsConfig(
                enabled=True,
                project_dir=str(tmp_path / "project-skills"),
                user_dir=str(tmp_path / "user-skills"),
                implicit_match_enabled=False,
            ),
            history_path=str(jsonl_path),
            db_path=str(db_path),
        )
        app = create_app(config)

        response = await self.request(app, "GET", "/api/conversations")
        assert response.status_code == 200
        conversations = response.json()["conversations"]
        assert any(c["conversation_id"] == "conv-migrated" for c in conversations)

    @pytest.mark.asyncio
    async def test_api_endpoints_after_migration(self, tmp_path):
        jsonl_path = tmp_path / "history.jsonl"
        db_path = tmp_path / "conversations.db"
        lines = [
            {
                "conversation_id": "conv-api",
                "source": "web",
                "role": "user",
                "content": "API集成测试",
                "created_at": "2026-05-01T09:00:00+08:00",
            },
            {
                "conversation_id": "conv-api",
                "source": "web",
                "role": "assistant",
                "content": "API集成回复",
                "created_at": "2026-05-01T09:00:01+08:00",
            },
            {
                "conversation_id": "conv-api",
                "source": "web",
                "role": "system",
                "content": "集成测试标题",
                "created_at": "2026-05-01T09:00:02+08:00",
                "record_type": "conversation_title",
            },
        ]
        write_jsonl_lines(jsonl_path, lines)

        auto_migrate(jsonl_path, db_path)

        config = AppConfig(
            llm=LLMConfig(api_key="test-key", model="gpt-4o"),
            skills=SkillsConfig(
                enabled=True,
                project_dir=str(tmp_path / "project-skills"),
                user_dir=str(tmp_path / "user-skills"),
                implicit_match_enabled=False,
            ),
            history_path=str(jsonl_path),
            db_path=str(db_path),
        )
        app = create_app(config)

        detail_response = await self.request(app, "GET", "/api/conversations/conv-api")
        assert detail_response.status_code == 200
        body = detail_response.json()
        contents = [m["content"] for m in body["messages"]]
        assert "API集成测试" in contents
        assert "API集成回复" in contents
        assert "集成测试标题" not in contents

    @pytest.mark.asyncio
    async def test_migration_preserves_web_api_functionality(self, tmp_path):
        jsonl_path = tmp_path / "history.jsonl"
        db_path = tmp_path / "conversations.db"
        lines = [
            {
                "conversation_id": "conv-preserve",
                "source": "web",
                "role": "user",
                "content": "保留数据",
                "created_at": "2026-05-01T09:00:00+08:00",
            },
        ]
        write_jsonl_lines(jsonl_path, lines)

        auto_migrate(jsonl_path, db_path)

        config = make_web_config(tmp_path)
        config.history_path = str(jsonl_path)
        config.db_path = str(db_path)
        app = create_app(config)

        app.state.history_store.append_message("conv-new", "web", "user", "迁移后新增")

        response = await self.request(app, "GET", "/api/conversations")
        assert response.status_code == 200
        conv_ids = [c["conversation_id"] for c in response.json()["conversations"]]
        assert "conv-preserve" in conv_ids
        assert "conv-new" in conv_ids