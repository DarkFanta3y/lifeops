from __future__ import annotations

import json
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from lifeops.core.config import PROJECT_ROOT
from lifeops.utils.logging import get_logger
from lifeops.utils.text import sanitize_unicode_text

logger = get_logger(__name__)

HistorySource = Literal["cli", "web"]
HistoryRole = Literal["user", "assistant", "tool"]

REQUIRED_RECORD_KEYS = {"conversation_id", "source", "role", "content", "created_at"}


class ConversationHistoryStore:
    """JSONL-backed conversation history for the local Web API."""

    def __init__(self, path: str | Path):
        self.path = self._resolve_path(path)

    def append_message(
        self,
        conversation_id: str,
        source: HistorySource,
        role: HistoryRole,
        content: str,
        created_at: str | None = None,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
    ) -> dict[str, Any]:
        record: dict[str, Any] = {
            "conversation_id": conversation_id,
            "source": source,
            "role": role,
            "content": sanitize_unicode_text(content),
            "created_at": created_at or self._now(),
        }
        if tool_name:
            record["tool_name"] = sanitize_unicode_text(tool_name)
        if tool_call_id:
            record["tool_call_id"] = sanitize_unicode_text(tool_call_id)

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def list_records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []

        records: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as file:
            for line_number, raw_line in enumerate(file, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning(f"跳过损坏的历史记录行: {self.path}:{line_number}")
                    continue
                if not self._is_valid_record(record):
                    logger.warning(f"跳过字段不完整的历史记录行: {self.path}:{line_number}")
                    continue
                records.append(record)
        return records

    def list_conversations(self) -> list[dict[str, Any]]:
        grouped: OrderedDict[str, dict[str, Any]] = OrderedDict()
        for record in self.list_records():
            conversation_id = record["conversation_id"]
            summary = grouped.setdefault(
                conversation_id,
                {
                    "conversation_id": conversation_id,
                    "source": record["source"],
                    "message_count": 0,
                    "title": self._title_from_record(record),
                    "last_message": "",
                    "created_at": record["created_at"],
                    "updated_at": record["created_at"],
                },
            )
            summary["message_count"] += 1
            summary["last_message"] = record["content"]
            summary["updated_at"] = record["created_at"]
            if record["role"] == "user" and not summary["title"]:
                summary["title"] = self._title_from_record(record)

        return sorted(grouped.values(), key=lambda item: item["updated_at"], reverse=True)

    def get_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        return [
            record
            for record in self.list_records()
            if record["conversation_id"] == conversation_id
        ]

    def _resolve_path(self, path: str | Path) -> Path:
        resolved = Path(path).expanduser()
        if not resolved.is_absolute():
            resolved = PROJECT_ROOT / resolved
        return resolved

    def _is_valid_record(self, value: Any) -> bool:
        if not isinstance(value, dict):
            return False
        if not REQUIRED_RECORD_KEYS.issubset(value.keys()):
            return False
        return all(isinstance(value[key], str) for key in REQUIRED_RECORD_KEYS)

    def _title_from_record(self, record: dict[str, Any]) -> str:
        content = record["content"].strip()
        if not content:
            return "未命名对话"
        return content[:80]

    def _now(self) -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")
