from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any
from uuid import uuid4

from lifeops.runtime.types import AgentRun, RunStatus, TraceEvent, TraceEventType


class RuntimeStore:
    def __init__(self, sqlite_store: Any, trace_max_payload_chars: int = 12000) -> None:
        self.sqlite_store = sqlite_store
        self.trace_max_payload_chars = max(1000, trace_max_payload_chars)

    @property
    def _conn(self) -> sqlite3.Connection:
        return self.sqlite_store._conn

    def create_run(
        self,
        conversation_id: str,
        source: str,
        user_input: str,
        *,
        run_id: str | None = None,
    ) -> AgentRun:
        rid = run_id or uuid4().hex
        now = self._now()
        if hasattr(self.sqlite_store, "_get_or_create_conversation"):
            self.sqlite_store._get_or_create_conversation(conversation_id, source)
        self._conn.execute(
            "INSERT INTO agent_runs "
            "(run_id, conversation_id, source, status, user_input, started_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (rid, conversation_id, source, RunStatus.RUNNING.value, user_input, now),
        )
        self._conn.commit()
        return AgentRun(
            run_id=rid,
            conversation_id=conversation_id,
            source=source,
            status=RunStatus.RUNNING,
            user_input=user_input,
            started_at=now,
        )

    def update_run_status(
        self,
        run_id: str,
        status: RunStatus | str,
        *,
        final_output: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        status_value = status.value if isinstance(status, RunStatus) else str(status)
        ended_at = self._now() if status_value in {RunStatus.COMPLETED.value, RunStatus.FAILED.value} else None
        self._conn.execute(
            "UPDATE agent_runs SET status = ?, final_output = COALESCE(?, final_output), "
            "error_type = COALESCE(?, error_type), error_message = COALESCE(?, error_message), "
            "ended_at = COALESCE(?, ended_at) WHERE run_id = ?",
            (status_value, final_output, error_type, error_message, ended_at, run_id),
        )
        self._conn.commit()

    def append_event(
        self,
        run_id: str,
        event_type: TraceEventType | str,
        payload: dict[str, Any] | None = None,
    ) -> TraceEvent:
        event_value = event_type.value if isinstance(event_type, TraceEventType) else str(event_type)
        payload_dict = self._truncate_payload(payload or {})
        payload_json = json.dumps(payload_dict, ensure_ascii=False, sort_keys=True)
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT COALESCE(MAX(sequence), -1) + 1 FROM agent_trace_events WHERE run_id = ?",
            (run_id,),
        )
        sequence = int(cursor.fetchone()[0])
        event_id = uuid4().hex
        created_at = self._now()
        cursor.execute(
            "INSERT INTO agent_trace_events "
            "(event_id, run_id, event_type, sequence, payload_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (event_id, run_id, event_value, sequence, payload_json, created_at),
        )
        self._conn.commit()
        return TraceEvent(
            event_id=event_id,
            run_id=run_id,
            event_type=TraceEventType(event_value),
            sequence=sequence,
            payload=payload_dict,
            created_at=created_at,
        )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        cursor = self._conn.execute("SELECT * FROM agent_runs WHERE run_id = ?", (run_id,))
        row = cursor.fetchone()
        return self._row_to_dict(row) if row else None

    def list_run_events(self, run_id: str) -> list[dict[str, Any]]:
        cursor = self._conn.execute(
            "SELECT * FROM agent_trace_events WHERE run_id = ? ORDER BY sequence ASC",
            (run_id,),
        )
        return [self._event_row_to_dict(row) for row in cursor.fetchall()]

    def list_conversation_runs(self, conversation_id: str) -> list[dict[str, Any]]:
        cursor = self._conn.execute(
            "SELECT * FROM agent_runs WHERE conversation_id = ? ORDER BY started_at DESC, run_id DESC",
            (conversation_id,),
        )
        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def _truncate_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if len(payload_json) <= self.trace_max_payload_chars:
            return payload
        return {
            "truncated": True,
            "original_length": len(payload_json),
            "preview": payload_json[: self.trace_max_payload_chars],
        }

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {key: row[key] for key in row.keys()}

    def _event_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        result = self._row_to_dict(row)
        try:
            result["payload"] = json.loads(result["payload_json"])
        except json.JSONDecodeError:
            result["payload"] = {}
        return result

    def _now(self) -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")
