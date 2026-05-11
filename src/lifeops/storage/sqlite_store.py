"""SQLite-based conversation history store, replacing JSONL storage."""
from __future__ import annotations

import json
import shutil
import sqlite3
from hashlib import sha1
from array import array
from datetime import datetime
from pathlib import Path
from typing import Any

from lifeops.memory.confidence import normalize_confidence
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
        current_version = self._get_schema_version(cursor)
        if current_version is not None and current_version < SCHEMA_VERSION:
            self._backup_before_schema_upgrade(current_version)
        cursor.executescript(CREATE_TABLES_SQL)
        self._migrate_schema_v3(cursor)
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)"
        )
        cursor.execute("DELETE FROM schema_version")
        cursor.execute(
            "INSERT INTO schema_version (version) VALUES (?)",
            (SCHEMA_VERSION,),
        )
        # 重建 FTS5 索引以确保与已有消息数据一致
        try:
            cursor.execute("INSERT INTO full_text_search(full_text_search) VALUES ('rebuild')")
        except sqlite3.OperationalError:
            pass
        self._conn.commit()

    def _migrate_schema_v3(self, cursor: sqlite3.Cursor) -> None:
        self._add_column_if_missing(
            cursor, "conversation_summaries", "importance_score",
            "REAL NOT NULL DEFAULT 0",
        )
        self._add_column_if_missing(
            cursor, "conversation_summaries", "last_accessed_at", "TEXT"
        )
        self._add_column_if_missing(
            cursor, "conversation_summaries", "access_count", "INTEGER NOT NULL DEFAULT 0"
        )
        self._add_column_if_missing(
            cursor, "conversation_summaries", "message_count", "INTEGER NOT NULL DEFAULT 0"
        )
        self._add_column_if_missing(
            cursor, "user_preferences", "preference_id", "TEXT NOT NULL DEFAULT ''"
        )
        self._add_column_if_missing(
            cursor, "user_preferences", "preference_type", "TEXT NOT NULL DEFAULT 'general'"
        )
        self._add_column_if_missing(
            cursor, "user_preferences", "source_conversation_id", "TEXT"
        )
        self._add_column_if_missing(
            cursor, "user_preferences", "last_observed_at", "TEXT"
        )
        self._add_column_if_missing(
            cursor, "user_preferences", "is_active", "INTEGER NOT NULL DEFAULT 1"
        )
        self._add_column_if_missing(
            cursor, "skill_usage_stats", "explicit_activation_count",
            "INTEGER NOT NULL DEFAULT 0",
        )
        self._add_column_if_missing(
            cursor, "skill_usage_stats", "implicit_activation_count",
            "INTEGER NOT NULL DEFAULT 0",
        )
        self._add_column_if_missing(
            cursor, "skill_usage_stats", "success_count", "INTEGER NOT NULL DEFAULT 0"
        )
        self._add_column_if_missing(
            cursor, "skill_usage_stats", "failure_count", "INTEGER NOT NULL DEFAULT 0"
        )
        self._add_column_if_missing(
            cursor, "knowledge_graph_entities", "entity_id", "TEXT NOT NULL DEFAULT ''"
        )
        self._add_column_if_missing(
            cursor, "knowledge_graph_entities", "normalized_name",
            "TEXT NOT NULL DEFAULT ''",
        )
        self._add_column_if_missing(
            cursor, "knowledge_graph_entities", "mention_count",
            "INTEGER NOT NULL DEFAULT 1",
        )
        self._add_column_if_missing(
            cursor, "knowledge_graph_entities", "last_mentioned_at", "TEXT"
        )
        self._add_column_if_missing(
            cursor, "knowledge_graph_entities", "is_active", "INTEGER NOT NULL DEFAULT 1"
        )
        self._add_column_if_missing(
            cursor, "knowledge_graph_relations", "strength", "REAL NOT NULL DEFAULT 0"
        )
        self._add_column_if_missing(
            cursor, "knowledge_graph_relations", "mention_count",
            "INTEGER NOT NULL DEFAULT 1",
        )
        self._add_column_if_missing(
            cursor, "knowledge_graph_relations", "last_observed_at", "TEXT"
        )
        self._add_column_if_missing(
            cursor, "knowledge_graph_relations", "is_active", "INTEGER NOT NULL DEFAULT 1"
        )
        now = self._now()
        cursor.execute(
            "UPDATE user_preferences SET preference_id = "
            "'pref_' || lower(hex(randomblob(8))) WHERE preference_id = ''"
        )
        cursor.execute(
            "UPDATE user_preferences SET last_observed_at = COALESCE(last_observed_at, updated_at, ?)",
            (now,),
        )
        cursor.execute(
            "UPDATE knowledge_graph_entities SET normalized_name = lower(name) "
            "WHERE normalized_name = ''"
        )
        cursor.execute(
            "UPDATE knowledge_graph_entities SET entity_id = "
            "'ent_' || lower(hex(randomblob(8))) WHERE entity_id = ''"
        )
        cursor.execute(
            "UPDATE knowledge_graph_entities SET last_mentioned_at = "
            "COALESCE(last_mentioned_at, updated_at, ?)",
            (now,),
        )
        cursor.execute(
            "UPDATE knowledge_graph_relations SET strength = confidence WHERE strength = 0"
        )
        cursor.execute(
            "UPDATE knowledge_graph_relations SET last_observed_at = "
            "COALESCE(last_observed_at, updated_at, ?)",
            (now,),
        )

    def _add_column_if_missing(
        self, cursor: sqlite3.Cursor, table: str, column: str, definition: str
    ) -> None:
        cursor.execute(f"PRAGMA table_info({table})")
        columns = {row[1] for row in cursor.fetchall()}
        if column not in columns:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _ensure_schema(self) -> None:
        cursor = self._conn.cursor()
        cursor.execute("SELECT version FROM schema_version")
        row = cursor.fetchone()
        if row and row[0] != SCHEMA_VERSION:
            raise ValueError(
                f"Schema version mismatch: expected {SCHEMA_VERSION}, got {row[0]}"
            )

    def _get_schema_version(self, cursor: sqlite3.Cursor) -> int | None:
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        )
        if cursor.fetchone() is None:
            return None
        cursor.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
        row = cursor.fetchone()
        return int(row[0]) if row else None

    def _backup_before_schema_upgrade(self, current_version: int) -> None:
        if not self._path.exists():
            return
        backup_path = self._path.with_name(f"{self._path.name}.v{current_version}.backup")
        if backup_path.exists():
            return
        shutil.copy2(self._path, backup_path)

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

    def list_records(
        self,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        _REC_JOIN_SQL = (
            "SELECT m.id, m.conversation_id, c.source, m.role, m.content, "
            "m.created_at, m.tool_name, m.tool_call_id, m.intermediate, "
            "m.record_type "
            "FROM messages m "
            "JOIN conversations c ON m.conversation_id = c.conversation_id "
            "ORDER BY m.created_at ASC, m.id ASC"
        )
        cursor = self._conn.cursor()

        if limit is None and offset is None:
            cursor.execute(_REC_JOIN_SQL)
            rows = cursor.fetchall()
            records: list[dict[str, Any]] = []
            for row in rows:
                tc_list = self._fetch_tool_calls(cursor, row["id"])
                record = self._row_to_record(row, tool_calls=tc_list if tc_list else None)
                records.append(record)
            return records

        cursor.execute("SELECT COUNT(*) FROM messages")
        total = cursor.fetchone()[0]

        effective_offset = offset or 0
        sql_limit = limit if limit is not None else -1
        cursor.execute(
            _REC_JOIN_SQL + " LIMIT ? OFFSET ?",
            (sql_limit, effective_offset),
        )
        rows = cursor.fetchall()
        records: list[dict[str, Any]] = []
        for row in rows:
            tc_list = self._fetch_tool_calls(cursor, row["id"])
            record = self._row_to_record(row, tool_calls=tc_list if tc_list else None)
            records.append(record)

        return {
            "items": records,
            "total": total,
            "limit": limit,
            "offset": effective_offset,
        }

    def list_conversations(
        self,
        query: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]] | dict[str, Any]:
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

        if limit is None and offset is None:
            return summaries

        total = len(summaries)
        effective_offset = offset or 0
        if limit is not None:
            items = summaries[effective_offset:effective_offset + limit]
        else:
            items = summaries[effective_offset:]
        return {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": effective_offset,
        }

    def get_messages(
        self,
        conversation_id: str,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        _MSG_JOIN_SQL = (
            "SELECT m.id, m.conversation_id, c.source, m.role, m.content, "
            "m.created_at, m.tool_name, m.tool_call_id, m.intermediate, "
            "m.record_type "
            "FROM messages m "
            "JOIN conversations c ON m.conversation_id = c.conversation_id "
            "WHERE m.conversation_id = ? "
            "AND (m.record_type IS NULL OR m.record_type != ?) "
            "ORDER BY m.created_at ASC, m.id ASC"
        )
        cursor = self._conn.cursor()

        if limit is None and offset is None:
            cursor.execute(_MSG_JOIN_SQL, (conversation_id, TITLE_RECORD_TYPE))
            rows = cursor.fetchall()
            messages: list[dict[str, Any]] = []
            for row in rows:
                tc_list = self._fetch_tool_calls(cursor, row["id"])
                record = self._row_to_record(row, tool_calls=tc_list if tc_list else None)
                messages.append(record)
            return messages

        cursor.execute(
            "SELECT COUNT(*) FROM messages "
            "WHERE conversation_id = ? "
            "AND (record_type IS NULL OR record_type != ?)",
            (conversation_id, TITLE_RECORD_TYPE),
        )
        total = cursor.fetchone()[0]

        effective_offset = offset or 0
        sql_limit = limit if limit is not None else -1
        cursor.execute(
            _MSG_JOIN_SQL + " LIMIT ? OFFSET ?",
            (conversation_id, TITLE_RECORD_TYPE, sql_limit, effective_offset),
        )
        rows = cursor.fetchall()
        messages: list[dict[str, Any]] = []
        for row in rows:
            tc_list = self._fetch_tool_calls(cursor, row["id"])
            record = self._row_to_record(row, tool_calls=tc_list if tc_list else None)
            messages.append(record)

        return {
            "items": messages,
            "total": total,
            "limit": limit,
            "offset": effective_offset,
        }

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

    def search_messages(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Search messages using FTS5 full-text search.

        Returns: {items: [message_dicts], total: N, limit: int, offset: int}
        """
        cursor = self._conn.cursor()

        escaped_query = query.replace('"', '""')
        fts_query = f'"{escaped_query}"'

        cursor.execute(
            "SELECT rowid, rank FROM full_text_search "
            "WHERE full_text_search MATCH ? ORDER BY rank",
            (fts_query,),
        )
        all_matches = cursor.fetchall()
        total = len(all_matches)
        matches = all_matches[offset:offset + limit]

        if not matches:
            return {"items": [], "total": total, "limit": limit, "offset": offset}

        id_to_rank = {m[0]: m[1] for m in matches}
        message_ids = list(id_to_rank.keys())

        placeholders = ",".join("?" * len(message_ids))
        cursor.execute(
            f"SELECT m.id, m.conversation_id, c.source, m.role, m.content, "
            f"m.created_at, m.tool_name, m.tool_call_id, m.intermediate, "
            f"m.record_type "
            f"FROM messages m "
            f"JOIN conversations c ON m.conversation_id = c.conversation_id "
            f"WHERE m.id IN ({placeholders}) "
            f"AND (m.record_type IS NULL OR m.record_type != ?)",
            (*message_ids, TITLE_RECORD_TYPE),
        )

        ordered_ids = list(id_to_rank.keys())
        records_by_id: dict[int, dict[str, Any]] = {}
        for row in cursor.fetchall():
            msg_id = row["id"]
            if msg_id not in id_to_rank:
                continue
            tc_list = self._fetch_tool_calls(cursor, msg_id)
            record = self._row_to_record(row, tool_calls=tc_list if tc_list else None)
            record["rank"] = id_to_rank[msg_id]
            records_by_id[msg_id] = record

        result_messages = [records_by_id[mid] for mid in ordered_ids if mid in records_by_id]

        return {
            "items": result_messages,
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def insert_or_update_conversation_summary(self, summary: dict[str, Any]) -> None:
        conversation_id = str(summary["conversation_id"])
        self._get_or_create_conversation(conversation_id, "web")
        now = self._now()
        embedding = summary.get("embedding")
        message_count = int(summary.get("message_count") or self._visible_message_count(conversation_id))
        cursor = self._conn.cursor()
        cursor.execute(
            "INSERT INTO conversation_summaries "
            "(conversation_id, summary, key_decisions, action_items, topics, tone, "
            "embedding, importance_score, last_accessed_at, access_count, message_count, "
            "created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(conversation_id) DO UPDATE SET "
            "summary = excluded.summary, key_decisions = excluded.key_decisions, "
            "action_items = excluded.action_items, topics = excluded.topics, "
            "tone = excluded.tone, embedding = excluded.embedding, "
            "importance_score = excluded.importance_score, "
            "message_count = excluded.message_count, updated_at = excluded.updated_at",
            (
                conversation_id,
                self._sanitize_unicode_text(str(summary.get("summary") or "")),
                self._json_dumps(summary.get("key_decisions", [])),
                self._json_dumps(summary.get("action_items", [])),
                self._json_dumps(summary.get("topics", [])),
                self._sanitize_unicode_text(str(summary.get("tone") or ""))
                if summary.get("tone") is not None
                else None,
                self._embedding_to_blob(embedding) if embedding is not None else None,
                normalize_confidence(summary.get("importance_score")),
                summary.get("last_accessed_at"),
                int(summary.get("access_count") or 0),
                message_count,
                now,
                now,
            ),
        )
        self._conn.commit()

    def list_conversation_summaries(
        self,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        cursor = self._conn.cursor()
        sql = (
            "SELECT conversation_id, summary, key_decisions, action_items, topics, "
            "tone, embedding, importance_score, last_accessed_at, access_count, "
            "message_count, created_at, updated_at "
            "FROM conversation_summaries ORDER BY updated_at DESC"
        )
        params: tuple[Any, ...] = ()
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params = (limit, offset)
        cursor.execute(sql, params)
        return [self._summary_row_to_dict(row) for row in cursor.fetchall()]

    def get_conversation_summary(self, conversation_id: str) -> dict[str, Any] | None:
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT conversation_id, summary, key_decisions, action_items, topics, "
            "tone, embedding, importance_score, last_accessed_at, access_count, "
            "message_count, created_at, updated_at "
            "FROM conversation_summaries WHERE conversation_id = ?",
            (conversation_id,),
        )
        row = cursor.fetchone()
        return self._summary_row_to_dict(row) if row else None

    def mark_summary_accessed(self, conversation_id: str) -> None:
        cursor = self._conn.cursor()
        cursor.execute(
            "UPDATE conversation_summaries SET access_count = access_count + 1, "
            "last_accessed_at = ? WHERE conversation_id = ?",
            (self._now(), conversation_id),
        )
        self._conn.commit()

    def upsert_user_preferences(self, preferences: list[dict[str, Any]]) -> None:
        if not preferences:
            return
        now = self._now()
        cursor = self._conn.cursor()
        for pref in preferences:
            key = self._sanitize_unicode_text(str(pref.get("key") or "")).strip()
            if not key:
                continue
            preference_type = self._sanitize_unicode_text(
                str(pref.get("preference_type") or pref.get("type") or "general")
            ).strip() or "general"
            value = self._sanitize_unicode_text(str(pref.get("value") or ""))
            confidence = normalize_confidence(pref.get("confidence"))
            evidence = pref.get("evidence")
            source_conversation_id = pref.get("source_conversation_id")
            preference_id = pref.get("preference_id") or self._stable_id(
                "pref", f"{preference_type}:{key}"
            )
            cursor.execute(
                "INSERT INTO user_preferences "
                "(preference_id, preference_type, key, value, confidence, evidence, "
                "source_conversation_id, observation_count, last_observed_at, is_active, "
                "created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, 1, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET "
                "preference_type = excluded.preference_type, "
                "value = CASE "
                "WHEN excluded.confidence >= user_preferences.confidence THEN excluded.value "
                "ELSE user_preferences.value END, "
                "confidence = MAX(user_preferences.confidence, excluded.confidence), "
                "evidence = COALESCE(excluded.evidence, user_preferences.evidence), "
                "source_conversation_id = COALESCE(excluded.source_conversation_id, "
                "user_preferences.source_conversation_id), "
                "observation_count = user_preferences.observation_count + 1, "
                "last_observed_at = excluded.last_observed_at, "
                "is_active = 1, "
                "updated_at = excluded.updated_at",
                (
                    preference_id,
                    preference_type,
                    key,
                    value,
                    confidence,
                    self._sanitize_unicode_text(str(evidence)) if evidence is not None else None,
                    self._sanitize_unicode_text(str(source_conversation_id))
                    if source_conversation_id is not None
                    else None,
                    now,
                    now,
                    now,
                ),
            )
        self._conn.commit()

    def get_user_preferences(self, min_confidence: float = 0.0) -> list[dict[str, Any]]:
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT preference_id, preference_type, key, value, confidence, evidence, "
            "source_conversation_id, observation_count, last_observed_at, is_active, "
            "created_at, updated_at "
            "FROM user_preferences WHERE confidence >= ? AND is_active = 1 "
            "ORDER BY confidence DESC, key ASC",
            (min_confidence,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def upsert_knowledge_entities(self, entities: list[dict[str, Any]]) -> None:
        if not entities:
            return
        now = self._now()
        cursor = self._conn.cursor()
        for entity in entities:
            name = self._sanitize_unicode_text(str(entity.get("name") or "")).strip()
            entity_type = self._sanitize_unicode_text(
                str(entity.get("entity_type") or "unknown")
            ).strip()
            if not name:
                continue
            normalized_name = name.casefold()
            entity_id = entity.get("entity_id") or self._stable_id(
                "ent", f"{entity_type}:{normalized_name}"
            )
            cursor.execute(
                "INSERT INTO knowledge_graph_entities "
                "(entity_id, name, normalized_name, entity_type, attributes, mention_count, "
                "last_mentioned_at, is_active, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 1, ?, 1, ?, ?) "
                "ON CONFLICT(name, entity_type) DO UPDATE SET "
                "normalized_name = excluded.normalized_name, "
                "attributes = excluded.attributes, "
                "mention_count = knowledge_graph_entities.mention_count + 1, "
                "last_mentioned_at = excluded.last_mentioned_at, is_active = 1, "
                "updated_at = excluded.updated_at",
                (
                    entity_id,
                    name,
                    normalized_name,
                    entity_type,
                    self._json_dumps(entity.get("attributes", {})),
                    now,
                    now,
                    now,
                ),
            )
        self._conn.commit()

    def upsert_knowledge_relations(self, relations: list[dict[str, Any]]) -> None:
        if not relations:
            return
        now = self._now()
        cursor = self._conn.cursor()
        for relation in relations:
            source = self._sanitize_unicode_text(str(relation.get("source") or "")).strip()
            target = self._sanitize_unicode_text(str(relation.get("target") or "")).strip()
            relation_type = self._sanitize_unicode_text(
                str(relation.get("relation_type") or "")
            ).strip()
            if not source or not target or not relation_type:
                continue
            confidence = normalize_confidence(
                relation.get("confidence")
                if relation.get("confidence") is not None
                else relation.get("strength")
            )
            cursor.execute(
                "INSERT INTO knowledge_graph_relations "
                "(source, target, relation_type, confidence, strength, mention_count, "
                "last_observed_at, is_active, attributes, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 1, ?, 1, ?, ?, ?) "
                "ON CONFLICT(source, target, relation_type) DO UPDATE SET "
                "confidence = MAX(knowledge_graph_relations.confidence, excluded.confidence), "
                "strength = MAX(knowledge_graph_relations.strength, excluded.strength), "
                "mention_count = knowledge_graph_relations.mention_count + 1, "
                "last_observed_at = excluded.last_observed_at, is_active = 1, "
                "attributes = excluded.attributes, updated_at = excluded.updated_at",
                (
                    source,
                    target,
                    relation_type,
                    confidence,
                    confidence,
                    now,
                    self._json_dumps(relation.get("attributes", {})),
                    now,
                    now,
                ),
            )
        self._conn.commit()

    def get_knowledge_graph(self) -> dict[str, list[dict[str, Any]]]:
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT entity_id, name, normalized_name, entity_type, attributes, "
            "mention_count, last_mentioned_at, is_active, created_at, updated_at "
            "FROM knowledge_graph_entities WHERE is_active = 1 ORDER BY name ASC"
        )
        entities = []
        for row in cursor.fetchall():
            item = dict(row)
            item["attributes"] = self._json_loads(item["attributes"], {})
            entities.append(item)
        cursor.execute(
            "SELECT source, target, relation_type, confidence, strength, mention_count, "
            "last_observed_at, is_active, attributes, created_at, updated_at "
            "FROM knowledge_graph_relations WHERE is_active = 1 ORDER BY source ASC, target ASC"
        )
        relations = []
        for row in cursor.fetchall():
            item = dict(row)
            item["attributes"] = self._json_loads(item["attributes"], {})
            relations.append(item)
        return {"entities": entities, "relations": relations}

    def record_message_embedding(
        self, conversation_id: str, message_id: int, embedding: list[float]
    ) -> None:
        now = self._now()
        cursor = self._conn.cursor()
        cursor.execute(
            "INSERT INTO message_embeddings "
            "(conversation_id, message_id, embedding, created_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(message_id) DO UPDATE SET "
            "embedding = excluded.embedding, created_at = excluded.created_at",
            (conversation_id, message_id, self._embedding_to_blob(embedding), now),
        )
        self._conn.commit()

    def get_message_embedding(self, message_id: int) -> list[float] | None:
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT embedding FROM message_embeddings WHERE message_id = ?",
            (message_id,),
        )
        row = cursor.fetchone()
        return self._blob_to_embedding(row["embedding"]) if row else None

    def record_offload_metadata(
        self,
        conversation_id: str,
        context_key: str,
        file_path: str,
        original_tokens: int,
        summary: str,
    ) -> None:
        self._get_or_create_conversation(conversation_id, "web")
        now = self._now()
        cursor = self._conn.cursor()
        cursor.execute(
            "INSERT INTO message_offload_metadata "
            "(conversation_id, context_key, file_path, original_tokens, summary, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(conversation_id, context_key) DO UPDATE SET "
            "file_path = excluded.file_path, original_tokens = excluded.original_tokens, "
            "summary = excluded.summary, created_at = excluded.created_at",
            (
                conversation_id,
                context_key,
                file_path,
                original_tokens,
                self._sanitize_unicode_text(summary),
                now,
            ),
        )
        self._conn.commit()

    def record_compression_event(
        self,
        conversation_id: str | None,
        phase: str,
        freed_tokens: int,
        reason: str,
    ) -> None:
        if conversation_id:
            self._get_or_create_conversation(conversation_id, "web")
        cursor = self._conn.cursor()
        cursor.execute(
            "INSERT INTO compression_events "
            "(conversation_id, phase, freed_tokens, reason, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                conversation_id,
                self._sanitize_unicode_text(phase),
                int(freed_tokens),
                self._sanitize_unicode_text(reason),
                self._now(),
            ),
        )
        self._conn.commit()

    def list_compression_events(
        self, limit: int | None = None, offset: int = 0
    ) -> list[dict[str, Any]]:
        cursor = self._conn.cursor()
        sql = (
            "SELECT id, conversation_id, phase, freed_tokens, reason, created_at "
            "FROM compression_events ORDER BY created_at DESC, id DESC"
        )
        params: tuple[Any, ...] = ()
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params = (limit, offset)
        cursor.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]

    def record_skill_usage(
        self,
        skill_name: str,
        *,
        activation_type: str = "implicit",
        success: bool | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        name = self._sanitize_unicode_text(skill_name).strip()
        if not name:
            return
        now = self._now()
        explicit_inc = 1 if activation_type == "explicit" else 0
        implicit_inc = 1 if activation_type != "explicit" else 0
        success_inc = 1 if success is True else 0
        failure_inc = 1 if success is False else 0
        cursor = self._conn.cursor()
        cursor.execute(
            "INSERT INTO skill_usage_stats "
            "(skill_name, activation_count, explicit_activation_count, "
            "implicit_activation_count, success_count, failure_count, last_used_at, metadata) "
            "VALUES (?, 1, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(skill_name) DO UPDATE SET "
            "activation_count = skill_usage_stats.activation_count + 1, "
            "explicit_activation_count = skill_usage_stats.explicit_activation_count + ?, "
            "implicit_activation_count = skill_usage_stats.implicit_activation_count + ?, "
            "success_count = skill_usage_stats.success_count + ?, "
            "failure_count = skill_usage_stats.failure_count + ?, "
            "last_used_at = excluded.last_used_at, metadata = excluded.metadata",
            (
                name,
                explicit_inc,
                implicit_inc,
                success_inc,
                failure_inc,
                now,
                self._json_dumps(metadata or {}),
                explicit_inc,
                implicit_inc,
                success_inc,
                failure_inc,
            ),
        )
        self._conn.commit()

    def list_skill_usage(self) -> list[dict[str, Any]]:
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT skill_name, activation_count, explicit_activation_count, "
            "implicit_activation_count, success_count, failure_count, last_used_at, metadata "
            "FROM skill_usage_stats ORDER BY activation_count DESC, skill_name ASC"
        )
        rows = []
        for row in cursor.fetchall():
            item = dict(row)
            item["metadata"] = self._json_loads(item["metadata"], {})
            rows.append(item)
        return rows

    def record_tool_usage(
        self,
        tool_name: str,
        *,
        success: bool,
        duration_ms: float = 0,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        name = self._sanitize_unicode_text(tool_name).strip()
        if not name:
            return
        now = self._now()
        success_inc = 1 if success else 0
        failure_inc = 0 if success else 1
        cursor = self._conn.cursor()
        cursor.execute(
            "INSERT INTO tool_usage_stats "
            "(tool_name, call_count, success_count, failure_count, total_duration_ms, "
            "last_used_at, last_error, metadata) "
            "VALUES (?, 1, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(tool_name) DO UPDATE SET "
            "call_count = tool_usage_stats.call_count + 1, "
            "success_count = tool_usage_stats.success_count + ?, "
            "failure_count = tool_usage_stats.failure_count + ?, "
            "total_duration_ms = tool_usage_stats.total_duration_ms + ?, "
            "last_used_at = excluded.last_used_at, "
            "last_error = COALESCE(excluded.last_error, tool_usage_stats.last_error), "
            "metadata = excluded.metadata",
            (
                name,
                success_inc,
                failure_inc,
                float(duration_ms),
                now,
                self._sanitize_unicode_text(error) if error else None,
                self._json_dumps(metadata or {}),
                success_inc,
                failure_inc,
                float(duration_ms),
            ),
        )
        self._conn.commit()

    def list_tool_usage_stats(self) -> list[dict[str, Any]]:
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT tool_name, call_count, success_count, failure_count, "
            "total_duration_ms, last_used_at, last_error, metadata "
            "FROM tool_usage_stats ORDER BY call_count DESC, tool_name ASC"
        )
        rows = []
        for row in cursor.fetchall():
            item = dict(row)
            item["metadata"] = self._json_loads(item["metadata"], {})
            if item["call_count"]:
                item["average_duration_ms"] = item["total_duration_ms"] / item["call_count"]
            else:
                item["average_duration_ms"] = 0
            rows.append(item)
        return rows

    def record_memory_config_snapshot(self, snapshot: dict[str, Any]) -> None:
        cursor = self._conn.cursor()
        cursor.execute(
            "INSERT INTO memory_config_snapshots (snapshot, created_at) VALUES (?, ?)",
            (self._json_dumps(snapshot), self._now()),
        )
        self._conn.commit()

    def delete_user_preference(self, preference_id: str) -> bool:
        cursor = self._conn.cursor()
        cursor.execute(
            "DELETE FROM user_preferences WHERE preference_id = ? OR key = ?",
            (preference_id, preference_id),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def delete_knowledge_entity(self, entity_id: str) -> bool:
        cursor = self._conn.cursor()
        cursor.execute(
            "DELETE FROM knowledge_graph_entities WHERE entity_id = ? OR name = ?",
            (entity_id, entity_id),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def search_knowledge_entities(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        query_text = query.casefold().strip()
        if not query_text:
            return self.get_knowledge_graph()["entities"][:limit]
        entities = self.get_knowledge_graph()["entities"]
        scored = []
        for item in entities:
            haystack = f"{item.get('name', '')} {item.get('entity_type', '')} {item.get('attributes', '')}".casefold()
            score = 1 if query_text in haystack else 0
            score += sum(1 for term in query_text.split() if term and term in haystack)
            if score > 0:
                scored.append((score, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in scored[:limit]]

    def forget_low_value_memories(
        self,
        *,
        dry_run: bool = True,
        preference_confidence_below: float = 0.2,
        relation_strength_below: float = 0.2,
    ) -> dict[str, int | bool]:
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM user_preferences WHERE confidence < ?",
            (preference_confidence_below,),
        )
        preferences = int(cursor.fetchone()[0])
        cursor.execute(
            "SELECT COUNT(*) FROM knowledge_graph_relations WHERE strength < ?",
            (relation_strength_below,),
        )
        relations = int(cursor.fetchone()[0])
        if not dry_run:
            cursor.execute(
                "DELETE FROM user_preferences WHERE confidence < ?",
                (preference_confidence_below,),
            )
            cursor.execute(
                "DELETE FROM knowledge_graph_relations WHERE strength < ?",
                (relation_strength_below,),
            )
            self._conn.commit()
        return {"dry_run": dry_run, "preferences": preferences, "relations": relations}

    def get_memory_stats(self) -> dict[str, int]:
        cursor = self._conn.cursor()
        names = {
            "conversations": "conversations",
            "messages": "messages",
            "summaries": "conversation_summaries",
            "entities": "knowledge_graph_entities",
            "relations": "knowledge_graph_relations",
            "preferences": "user_preferences",
            "compression_events": "compression_events",
            "skills": "skill_usage_stats",
            "tools": "tool_usage_stats",
        }
        stats: dict[str, int] = {}
        for key, table in names.items():
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            stats[key] = int(cursor.fetchone()[0])
        return stats

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
            f"DELETE FROM message_embeddings WHERE message_id IN ({placeholders})",
            message_ids,
        )
        cursor.execute(
            "DELETE FROM message_offload_metadata WHERE conversation_id = ?",
            (conversation_id,),
        )
        cursor.execute(
            "DELETE FROM compression_events WHERE conversation_id = ?",
            (conversation_id,),
        )
        cursor.execute(
            "DELETE FROM conversation_summaries WHERE conversation_id = ?",
            (conversation_id,),
        )
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

    def _json_dumps(self, value: Any) -> str:
        return json.dumps(self._sanitize_unicode_data(value), ensure_ascii=False)

    def _json_loads(self, value: str | None, default: Any) -> Any:
        if value is None:
            return default
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default

    def _embedding_to_blob(self, embedding: Any) -> bytes:
        values = [float(item) for item in (embedding or [])]
        return array("f", values).tobytes()

    def _blob_to_embedding(self, blob: bytes | memoryview | None) -> list[float] | None:
        if blob is None:
            return None
        values = array("f")
        values.frombytes(bytes(blob))
        return [round(float(item), 7) for item in values]

    def _summary_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "conversation_id": row["conversation_id"],
            "summary": row["summary"],
            "key_decisions": self._json_loads(row["key_decisions"], []),
            "action_items": self._json_loads(row["action_items"], []),
            "topics": self._json_loads(row["topics"], []),
            "tone": row["tone"],
            "embedding": self._blob_to_embedding(row["embedding"]),
            "importance_score": row["importance_score"],
            "last_accessed_at": row["last_accessed_at"],
            "access_count": row["access_count"],
            "message_count": row["message_count"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _visible_message_count(self, conversation_id: str) -> int:
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM messages WHERE conversation_id = ? "
            "AND intermediate = 0 AND role != 'tool' "
            "AND (record_type IS NULL OR record_type != ?)",
            (conversation_id, TITLE_RECORD_TYPE),
        )
        return int(cursor.fetchone()[0])

    def _stable_id(self, prefix: str, value: str) -> str:
        digest = sha1(value.encode("utf-8")).hexdigest()[:16]
        return f"{prefix}_{digest}"

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
