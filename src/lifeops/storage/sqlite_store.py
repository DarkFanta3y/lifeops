"""SQLite-based conversation history store, replacing JSONL storage."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from lifeops.storage.schema import CREATE_TABLES_SQL, SCHEMA_VERSION
from lifeops.utils.text import sanitize_unicode_data, sanitize_unicode_text

TITLE_RECORD_TYPE = "conversation_title"


class ConversationHistoryStoreSQLite:

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._connect()
        self._init_db()

    def _connect(self) -> None:
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")

    def _init_db(self) -> None:
        cursor = self._conn.cursor()
        cursor.executescript(CREATE_TABLES_SQL)
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)"
        )
        cursor.execute(
            "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
            (SCHEMA_VERSION,),
        )
        self._conn.commit()

    def _ensure_schema(self) -> None:
        cursor = self._conn.cursor()
        cursor.execute("SELECT version FROM schema_version")
        row = cursor.fetchone()
        if row and row[0] != SCHEMA_VERSION:
            raise ValueError(
                f"Schema version mismatch: expected {SCHEMA_VERSION}, got {row[0]}"
            )

    def _now(self) -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    def _sanitize_unicode_text(self, value: str) -> str:
        return sanitize_unicode_text(value)

    def _sanitize_unicode_data(self, value: Any) -> Any:
        return sanitize_unicode_data(value)

    def _get_or_create_conversation(self, conversation_id: str, source: str) -> None:
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT conversation_id FROM conversations WHERE conversation_id = ?",
            (conversation_id,),
        )
        if cursor.fetchone() is None:
            now = self._now()
            cursor.execute(
                "INSERT INTO conversations (conversation_id, source, created_at, "
                "updated_at) VALUES (?, ?, ?, ?)",
                (conversation_id, source, now, now),
            )
            self._conn.commit()

    def _row_to_record(self, row: sqlite3.Row, tool_calls: list[dict] | None = None) -> dict[str, Any]:
        record: dict[str, Any] = {
            "conversation_id": row["conversation_id"],
            "source": row["source"],
            "role": row["role"],
            "content": row["content"],
            "created_at": row["created_at"],
        }
        if row["tool_name"] is not None:
            record["tool_name"] = row["tool_name"]
        if row["tool_call_id"] is not None:
            record["tool_call_id"] = row["tool_call_id"]
        if tool_calls is not None:
            record["tool_calls"] = tool_calls
        if row["intermediate"]:
            record["intermediate"] = True
        if row["record_type"] is not None:
            record["record_type"] = row["record_type"]
        return record

    def append_message(
        self,
        conversation_id: str,
        source: str,
        role: str,
        content: str,
        created_at: str | None = None,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        intermediate: bool = False,
    ) -> dict[str, Any]:
        ts = created_at or self._now()
        sanitized_content = self._sanitize_unicode_text(content)

        self._get_or_create_conversation(conversation_id, source)

        cursor = self._conn.cursor()
        cursor.execute(
            "INSERT INTO messages "
            "(conversation_id, role, content, created_at, intermediate, "
            "tool_name, tool_call_id, record_type) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                conversation_id,
                role,
                sanitized_content,
                ts,
                1 if intermediate else 0,
                self._sanitize_unicode_text(tool_name) if tool_name else None,
                self._sanitize_unicode_text(tool_call_id) if tool_call_id else None,
                None,
            ),
        )
        message_id = cursor.lastrowid

        if tool_calls is not None:
            for tc in tool_calls:
                sanitized_tc = self._sanitize_unicode_data(tc)
                tc_id = sanitized_tc.get("id", "")
                fn = sanitized_tc.get("function", {})
                tc_name = fn.get("name", "")
                tc_args = fn.get("arguments", "{}")
                if not isinstance(tc_args, str):
                    tc_args = json.dumps(tc_args, ensure_ascii=False)
                cursor.execute(
                    "INSERT OR IGNORE INTO tool_calls "
                    "(message_id, tool_call_id, tool_name, arguments, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (message_id, tc_id, tc_name, tc_args, ts),
                )

        is_intermediate = 1 if intermediate else 0
        cursor.execute(
            "UPDATE conversations "
            "SET message_count = message_count + (1 - ?), "
            "    last_message = ?, "
            "    updated_at = ? "
            "WHERE conversation_id = ?",
            (is_intermediate, sanitized_content, ts, conversation_id),
        )
        self._conn.commit()

        record: dict[str, Any] = {
            "conversation_id": conversation_id,
            "source": source,
            "role": role,
            "content": sanitized_content,
            "created_at": ts,
        }
        if tool_name:
            record["tool_name"] = self._sanitize_unicode_text(tool_name)
        if tool_call_id:
            record["tool_call_id"] = self._sanitize_unicode_text(tool_call_id)
        if tool_calls is not None:
            record["tool_calls"] = self._sanitize_unicode_data(tool_calls)
        if intermediate:
            record["intermediate"] = True
        return record

    def append_conversation_title(
        self,
        conversation_id: str,
        source: str,
        title: str,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        ts = created_at or self._now()
        sanitized_title = self._sanitize_unicode_text(title)

        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT conversation_id FROM conversations WHERE conversation_id = ?",
            (conversation_id,),
        )
        if cursor.fetchone() is None:
            cursor.execute(
                "INSERT INTO conversations (conversation_id, source, created_at, "
                "updated_at, title) VALUES (?, ?, ?, ?, ?)",
                (conversation_id, source, ts, ts, sanitized_title),
            )
        else:
            cursor.execute(
                "UPDATE conversations SET title = ? "
                "WHERE conversation_id = ?",
                (sanitized_title, conversation_id),
            )

        cursor.execute(
            "INSERT INTO messages "
            "(conversation_id, role, content, created_at, intermediate, "
            "tool_name, tool_call_id, record_type) "
            "VALUES (?, ?, ?, ?, 0, NULL, NULL, ?)",
            (conversation_id, "system", sanitized_title, ts, TITLE_RECORD_TYPE),
        )
        self._conn.commit()

        return {
            "conversation_id": conversation_id,
            "source": source,
            "role": "system",
            "content": sanitized_title,
            "created_at": ts,
            "record_type": TITLE_RECORD_TYPE,
        }

    def list_records(self) -> list[dict[str, Any]]:
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT m.id, m.conversation_id, c.source, m.role, m.content, "
            "m.created_at, m.tool_name, m.tool_call_id, m.intermediate, "
            "m.record_type "
            "FROM messages m "
            "JOIN conversations c ON m.conversation_id = c.conversation_id "
            "ORDER BY m.created_at ASC, m.id ASC"
        )
        rows = cursor.fetchall()
        records: list[dict[str, Any]] = []
        for row in rows:
            tc_list = self._fetch_tool_calls(cursor, row["id"])
            record = self._row_to_record(row, tool_calls=tc_list if tc_list else None)
            records.append(record)
        return records

    def list_conversations(self, query: str | None = None) -> list[dict[str, Any]]:
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT conversation_id, source, message_count, title, "
            "last_message, created_at, updated_at "
            "FROM conversations "
            "ORDER BY updated_at DESC"
        )
        rows = cursor.fetchall()
        summaries: list[dict[str, Any]] = []
        for row in rows:
            conv_id = row["conversation_id"]
            title = row["title"]

            if not title:
                title = self._get_first_user_content(cursor, conv_id) or "未命名对话"

            if query and query.strip():
                normalized_query = query.strip().casefold()
                if not self._title_matches_query(cursor, conv_id, normalized_query):
                    continue

            summaries.append({
                "conversation_id": conv_id,
                "source": row["source"],
                "message_count": row["message_count"],
                "title": title[:80] if title else "未命名对话",
                "last_message": row["last_message"] or "",
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            })
        return summaries

    def get_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT m.id, m.conversation_id, c.source, m.role, m.content, "
            "m.created_at, m.tool_name, m.tool_call_id, m.intermediate, "
            "m.record_type "
            "FROM messages m "
            "JOIN conversations c ON m.conversation_id = c.conversation_id "
            "WHERE m.conversation_id = ? "
            "AND (m.record_type IS NULL OR m.record_type != ?) "
            "ORDER BY m.created_at ASC, m.id ASC",
            (conversation_id, TITLE_RECORD_TYPE),
        )
        rows = cursor.fetchall()
        messages: list[dict[str, Any]] = []
        for row in rows:
            tc_list = self._fetch_tool_calls(cursor, row["id"])
            record = self._row_to_record(row, tool_calls=tc_list if tc_list else None)
            messages.append(record)
        return messages

    def get_first_user_message(self, conversation_id: str) -> str | None:
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT content FROM messages "
            "WHERE conversation_id = ? AND role = 'user' "
            "AND (record_type IS NULL OR record_type != ?) "
            "ORDER BY created_at ASC, id ASC LIMIT 1",
            (conversation_id, TITLE_RECORD_TYPE),
        )
        row = cursor.fetchone()
        return row["content"] if row else None

    def has_conversation_title(self, conversation_id: str) -> bool:
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT 1 FROM messages "
            "WHERE conversation_id = ? AND record_type = ? "
            "LIMIT 1",
            (conversation_id, TITLE_RECORD_TYPE),
        )
        return cursor.fetchone() is not None

    def delete_conversation(self, conversation_id: str) -> int:
        cursor = self._conn.cursor()

        cursor.execute(
            "SELECT id FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        )
        message_ids = [row[0] for row in cursor.fetchall()]

        if not message_ids:
            return 0

        placeholders = ",".join("?" * len(message_ids))
        cursor.execute(
            f"DELETE FROM tool_results WHERE tool_call_id IN ("
            f"SELECT tool_call_id FROM tool_calls WHERE message_id IN ({placeholders})"
            f")",
            message_ids,
        )

        cursor.execute(
            f"DELETE FROM tool_calls WHERE message_id IN ({placeholders})",
            message_ids,
        )

        cursor.execute(
            "SELECT COUNT(*) FROM messages "
            "WHERE conversation_id = ? "
            "AND (record_type IS NULL OR record_type != ?)",
            (conversation_id, TITLE_RECORD_TYPE),
        )
        deleted_count = cursor.fetchone()[0]

        cursor.execute(
            "DELETE FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        )

        cursor.execute(
            "DELETE FROM conversations WHERE conversation_id = ?",
            (conversation_id,),
        )

        self._conn.commit()
        return deleted_count

    def _fetch_tool_calls(self, cursor: sqlite3.Cursor, message_id: int) -> list[dict]:
        cursor.execute(
            "SELECT tool_call_id, tool_name, arguments FROM tool_calls "
            "WHERE message_id = ? ORDER BY id ASC",
            (message_id,),
        )
        rows = cursor.fetchall()
        if not rows:
            return []
        result: list[dict] = []
        for row in rows:
            result.append({
                "id": row["tool_call_id"],
                "type": "function",
                "function": {
                    "name": row["tool_name"],
                    "arguments": row["arguments"],
                },
            })
        return result

    def _get_first_user_content(self, cursor: sqlite3.Cursor, conversation_id: str) -> str | None:
        cursor.execute(
            "SELECT content FROM messages "
            "WHERE conversation_id = ? AND role = 'user' "
            "AND (record_type IS NULL OR record_type != ?) "
            "ORDER BY created_at ASC, id ASC LIMIT 1",
            (conversation_id, TITLE_RECORD_TYPE),
        )
        row = cursor.fetchone()
        return row["content"] if row else None

    def _title_matches_query(
        self, cursor: sqlite3.Cursor, conversation_id: str, normalized_query: str
    ) -> bool:
        cursor.execute(
            "SELECT content FROM messages "
            "WHERE conversation_id = ? AND record_type = ? "
            "LIMIT 1",
            (conversation_id, TITLE_RECORD_TYPE),
        )
        row = cursor.fetchone()
        if row is None:
            return False
        return normalized_query in row["content"].casefold()

    # -- Connection lifecycle --

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> ConversationHistoryStoreSQLite:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
