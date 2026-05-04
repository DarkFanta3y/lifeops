"""SQLite-based conversation history store, replacing JSONL storage."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from lifeops.storage.schema import CREATE_TABLES_SQL, SCHEMA_VERSION


class ConversationHistoryStoreSQLite:

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._connect()
        self._init_db()

    def _connect(self) -> None:
        self._conn = sqlite3.connect(str(self._path))
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

    # -- Public method stubs (to be implemented in later tasks) --

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
        raise NotImplementedError("append_message not yet implemented")

    def append_conversation_title(
        self,
        conversation_id: str,
        source: str,
        title: str,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError("append_conversation_title not yet implemented")

    def list_records(self) -> list[dict[str, Any]]:
        raise NotImplementedError("list_records not yet implemented")

    def list_conversations(self, query: str | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError("list_conversations not yet implemented")

    def get_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError("get_messages not yet implemented")

    def get_first_user_message(self, conversation_id: str) -> str | None:
        raise NotImplementedError("get_first_user_message not yet implemented")

    def has_conversation_title(self, conversation_id: str) -> bool:
        raise NotImplementedError("has_conversation_title not yet implemented")

    def delete_conversation(self, conversation_id: str) -> int:
        raise NotImplementedError("delete_conversation not yet implemented")

    # -- Connection lifecycle --

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> ConversationHistoryStoreSQLite:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
