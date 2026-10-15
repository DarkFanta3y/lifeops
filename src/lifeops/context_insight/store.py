"""上下文快照的写入：每次 LLM 请求一行快照，元素内容按哈希去重存入 context_blobs。"""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime
from hashlib import sha1
from typing import Any

from lifeops.context_insight.composition import ContextElement, category_totals
from lifeops.utils.logging import get_logger

logger = get_logger(__name__)

RESPONSE_TEXT_MAX_CHARS = 200


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class ContextSnapshotStore:
    def __init__(self, sqlite_store: Any) -> None:
        self.sqlite_store = sqlite_store

    @property
    def _conn(self) -> sqlite3.Connection:
        return self.sqlite_store._conn

    def capture(
        self,
        *,
        run_id: str,
        conversation_id: str,
        elements: list[ContextElement],
        agent_id: str = "main",
        parent_agent_id: str | None = None,
        iteration: int = 0,
        model: str | None = None,
        budget: int = 0,
        reserve_ratio: float = 0.0,
        estimated_tokens: int | None = None,
        trimmed_count: int = 0,
        truncated_count: int = 0,
    ) -> int | None:
        """写入快照并返回 id；任何异常只记日志，不影响 Agent 主流程。"""
        try:
            rows = []
            blobs: dict[str, str] = {}
            for element in elements:
                content = _dumps(element.content)
                digest = sha1(content.encode("utf-8")).hexdigest()
                blobs[digest] = content
                rows.append({
                    "cat": element.cat,
                    "name": element.name,
                    "tokens": element.tokens,
                    "hash": digest,
                    **element.meta,
                })
            totals = category_totals(elements)
            cursor = self._conn.cursor()
            cursor.executemany(
                "INSERT OR IGNORE INTO context_blobs (hash, content) VALUES (?, ?)",
                list(blobs.items()),
            )
            cursor.execute(
                "INSERT INTO context_snapshots (run_id, conversation_id, agent_id, parent_agent_id, "
                "iteration, model, budget, reserve_ratio, estimated_tokens, categories_json, "
                "elements_json, trimmed_count, truncated_count, started_at_ms, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    conversation_id,
                    agent_id,
                    parent_agent_id,
                    iteration,
                    model,
                    budget,
                    reserve_ratio,
                    estimated_tokens if estimated_tokens is not None else sum(totals.values()),
                    _dumps(totals),
                    _dumps(rows),
                    trimmed_count,
                    truncated_count,
                    int(time.time() * 1000),
                    datetime.now().astimezone().isoformat(timespec="seconds"),
                ),
            )
            self._conn.commit()
            return cursor.lastrowid
        except Exception:
            logger.exception("写入上下文快照失败")
            return None

    def finish(
        self,
        snapshot_id: int | None,
        *,
        usage: dict[str, int] | None = None,
        ttft_ms: float | None = None,
        duration_ms: float | None = None,
        text: str | None = None,
        calls: list[str] | None = None,
    ) -> None:
        if snapshot_id is None:
            return
        response: dict[str, Any] = {}
        if text:
            response["text"] = " ".join(text.split())[:RESPONSE_TEXT_MAX_CHARS]
        if calls:
            response["calls"] = calls
        try:
            self._conn.execute(
                "UPDATE context_snapshots SET usage_json = ?, response_json = ?, ttft_ms = ?, "
                "duration_ms = ? WHERE id = ?",
                (
                    _dumps(usage) if usage else None,
                    _dumps(response) if response else None,
                    round(ttft_ms) if ttft_ms is not None else None,
                    round(duration_ms) if duration_ms is not None else None,
                    snapshot_id,
                ),
            )
            self._conn.commit()
        except Exception:
            logger.exception("更新上下文快照失败")
