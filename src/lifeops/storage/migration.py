"""JSONL 到 SQLite 的迁移工具，在 Web API 启动时自动执行。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from lifeops.storage.sqlite_store import ConversationHistoryStoreSQLite

logger = logging.getLogger(__name__)

REQUIRED_RECORD_KEYS = {"conversation_id", "source", "role", "content", "created_at"}


def migrate_jsonl_to_sqlite(
    jsonl_path: str | Path,
    db_path: str | Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    """将 JSONL 历史文件中的记录迁移到 SQLite 数据库。

    Args:
        jsonl_path: JSONL 文件路径。
        db_path: SQLite 数据库文件路径。
        dry_run: 如果为 True，只验证和计数，不实际写入。

    Returns:
        包含 total、success、failed、errors 的统计字典。
    """
    jsonl_path = Path(jsonl_path).expanduser()
    db_path = Path(db_path).expanduser()

    stats: dict[str, Any] = {"total": 0, "success": 0, "failed": 0, "errors": []}

    if not jsonl_path.exists():
        logger.info("JSONL 文件不存在，跳过迁移: %s", jsonl_path)
        return stats

    logger.info("开始迁移 JSONL → SQLite: %s → %s", jsonl_path, db_path)

    store: ConversationHistoryStoreSQLite | None = None
    if not dry_run:
        store = ConversationHistoryStoreSQLite(db_path)

    try:
        with jsonl_path.open("r", encoding="utf-8") as f:
            for line_number, raw_line in enumerate(f, start=1):
                line = raw_line.strip()
                if not line:
                    continue

                stats["total"] += 1

                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    msg = f"第 {line_number} 行 JSON 解析失败: {exc}"
                    logger.warning(msg)
                    stats["failed"] += 1
                    stats["errors"].append(msg)
                    continue

                if not _is_valid_record(record):
                    msg = f"第 {line_number} 行缺少必要字段，跳过"
                    logger.warning(msg)
                    stats["failed"] += 1
                    stats["errors"].append(msg)
                    continue

                if dry_run:
                    stats["success"] += 1
                    continue

                assert store is not None
                try:
                    _insert_record(store, record)
                    stats["success"] += 1
                except Exception as exc:
                    msg = f"第 {line_number} 行写入失败: {exc}"
                    logger.warning(msg)
                    stats["failed"] += 1
                    stats["errors"].append(msg)

                if stats["success"] > 0 and stats["success"] % 100 == 0:
                    logger.info("迁移进度: 已处理 %d 条", stats["success"])

    finally:
        if store is not None:
            store.close()

    logger.info(
        "迁移完成: 总计 %d 条, 成功 %d 条, 失败 %d 条",
        stats["total"],
        stats["success"],
        stats["failed"],
    )
    return stats


def should_migrate(jsonl_path: str | Path, db_path: str | Path) -> bool:
    """判断是否需要执行 JSONL → SQLite 迁移。

    当 JSONL 文件存在，且 SQLite 文件不存在或数据库中没有消息时返回 True。
    """
    jsonl_path = Path(jsonl_path).expanduser()
    db_path = Path(db_path).expanduser()

    if not jsonl_path.exists():
        return False

    if not db_path.exists():
        return True

    try:
        store = ConversationHistoryStoreSQLite(db_path)
        try:
            messages = store.list_records()
            return len(messages) == 0
        finally:
            store.close()
    except Exception:
        logger.warning("无法读取已有 SQLite 数据库，将尝试迁移: %s", db_path)
        return True


def auto_migrate(jsonl_path: str | Path, db_path: str | Path) -> dict[str, Any] | None:
    """自动检测并执行 JSONL → SQLite 迁移。

    迁移失败时不会抛出异常，仅记录日志。

    Returns:
        迁移统计字典，如果无需迁移则返回 None。
    """
    try:
        if not should_migrate(jsonl_path, db_path):
            logger.info("无需迁移: JSONL 数据已存在于 SQLite 中")
            return None

        logger.info("检测到 JSONL 数据需要迁移到 SQLite")
        result = migrate_jsonl_to_sqlite(jsonl_path, db_path)
        logger.info("迁移结果: %s", result)
        return result
    except Exception as exc:
        logger.error("迁移过程中发生错误，应用将继续启动: %s", exc, exc_info=True)
        return None


def _is_valid_record(record: Any) -> bool:
    if not isinstance(record, dict):
        return False
    if not REQUIRED_RECORD_KEYS.issubset(record.keys()):
        return False
    return all(isinstance(record[key], str) for key in REQUIRED_RECORD_KEYS)


def _insert_record(store: ConversationHistoryStoreSQLite, record: dict[str, Any]) -> None:
    conversation_id = record["conversation_id"]
    source = record["source"]
    role = record["role"]
    content = record["content"]
    created_at = record["created_at"]

    if record.get("record_type") == "conversation_title":
        store.append_conversation_title(
            conversation_id=conversation_id,
            source=source,
            title=content,
            created_at=created_at,
        )
        return

    tool_calls = record.get("tool_calls")
    store.append_message(
        conversation_id=conversation_id,
        source=source,
        role=role,
        content=content,
        created_at=created_at,
        tool_name=record.get("tool_name"),
        tool_call_id=record.get("tool_call_id"),
        tool_calls=tool_calls if tool_calls else None,
        intermediate=bool(record.get("intermediate", False)),
    )