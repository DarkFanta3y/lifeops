"""只读读取 SQLite，事务迁移业务表，并逐表校验全部字段的 SHA-256。"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sqlite3
from graphlib import TopologicalSorter
from pathlib import Path
from typing import Any

from lifeops.core.config import AppConfig
from lifeops.storage.mysql_schema import MYSQL_SCHEMA_VERSION, MYSQL_TABLES
from lifeops.storage.mysql_store import ConversationHistoryStoreMySQL


def _value(value: Any):
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"blob": base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, float):
        return {"float": value.hex()}
    return value


def table_signature(connection, table: str, columns: list[str]) -> dict:
    if table not in MYSQL_TABLES:
        raise ValueError("不允许访问未知业务表")
    names = ",".join(f"`{name}`" for name in columns)
    rows = connection.execute(f"SELECT {names} FROM `{table}`").fetchall()
    serialized = sorted(
        json.dumps([_value(row[name]) for name in columns], ensure_ascii=False,
                   separators=(",", ":"), allow_nan=False)
        for row in rows
    )
    digest = hashlib.sha256()
    for row in serialized:
        payload = row.encode("utf-8")
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return {"rows": len(rows), "sha256": digest.hexdigest(), "columns": columns}


def verify_mysql(connection, manifest: dict) -> None:
    for table, expected in manifest.items():
        actual = table_signature(connection, table, expected["columns"])
        if actual != expected:
            raise ValueError(f"迁移校验失败：{table} 的行数或内容不一致")


def migrate_sqlite_to_mysql(source_path: Path, url: str, report_path: Path) -> dict:
    """调用前必须停止旧后端；目标只能是本次迁移创建的空业务数据库。"""
    if not source_path.is_file():
        raise FileNotFoundError("找不到待迁移 SQLite 数据库")
    source = sqlite3.connect(source_path.resolve().as_uri() + "?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    source.execute("PRAGMA query_only=ON")
    source.execute("BEGIN")
    target = None
    try:
        version = source.execute("SELECT version FROM schema_version").fetchone()[0]
        if version != MYSQL_SCHEMA_VERSION:
            raise ValueError("源数据库版本不匹配，请先升级旧后端结构")
        source_tables = {row[0] for row in source.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'full_text_search%'"
        )}
        if source_tables != set(MYSQL_TABLES):
            raise ValueError("源数据库业务表与迁移定义不一致，停止迁移")
        if source.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("源数据库存在外键异常，停止迁移")
        columns = {
            table: [row[1] for row in source.execute(f"PRAGMA table_info(`{table}`)")]
            for table in MYSQL_TABLES
        }
        manifest = {table: table_signature(source, table, columns[table])
                    for table in MYSQL_TABLES}
        target = ConversationHistoryStoreMySQL(url, seed_defaults=False)
        connection = target._conn
        # 已完成的同内容迁移可以复核；不同内容不能覆盖任何现有业务记录。
        nonempty = [table for table in MYSQL_TABLES
                    if table != "schema_version"
                    and connection.execute(f"SELECT COUNT(*) FROM `{table}`").fetchone()[0]]
        if nonempty:
            verify_mysql(connection, manifest)
        else:
            dependencies = {
                table: {row[2] for row in source.execute(f"PRAGMA foreign_key_list(`{table}`)")}
                for table in MYSQL_TABLES
            }
            connection.execute("DELETE FROM schema_version")
            for table in TopologicalSorter(dependencies).static_order():
                names = ",".join(f"`{name}`" for name in columns[table])
                placeholders = ",".join("?" for _ in columns[table])
                rows = source.execute(f"SELECT {names} FROM `{table}`").fetchall()
                if rows:
                    connection.cursor().executemany(
                        f"INSERT INTO `{table}` ({names}) VALUES ({placeholders})",
                        [tuple(row[name] for name in columns[table]) for row in rows],
                    )
            verify_mysql(connection, manifest)
            connection.commit()
        # 提交后新建连接再次复核，避免仅检查到未提交的事务内容。
        target.close()
        target = ConversationHistoryStoreMySQL(url)
        verify_mysql(target._conn, manifest)
        report = {"status": "verified", "source": str(source_path.resolve()),
                  "table_count": len(manifest), "tables": manifest}
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        report_path.chmod(0o600)
        return report
    except Exception:
        if target is not None:
            target._conn.rollback()
        raise
    finally:
        if target is not None:
            target.close()
        source.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    config = AppConfig()
    if not config.database_url:
        parser.error("请设置 LIFEOPS_DATABASE_URL")
    result = migrate_sqlite_to_mysql(args.sqlite, config.database_url, args.report)
    print(f"迁移完成：{result['table_count']} 张业务表的行数及全部字段哈希一致")


if __name__ == "__main__":
    main()
