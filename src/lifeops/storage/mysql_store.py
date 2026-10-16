"""MySQL 仓储：沿用业务读写规则，替换连接、建表和消息搜索。"""

from __future__ import annotations

from lifeops.storage.mysql_connection import MySQLConnection
from lifeops.storage.mysql_schema import MYSQL_SCHEMA_SQL, MYSQL_SCHEMA_VERSION
from lifeops.storage.sqlite_store import TITLE_RECORD_TYPE, ConversationHistoryStoreSQLite


class ConversationHistoryStoreMySQL(ConversationHistoryStoreSQLite):
    def __init__(self, url: str, *, seed_defaults: bool = True):
        # 不调用 SQLite 构造函数，不创建本地数据库文件。
        self._conn = MySQLConnection(url)
        try:
            for statement in MYSQL_SCHEMA_SQL.split(";"):
                if statement.strip():
                    self._conn.execute(statement.strip())
            row = self._conn.execute("SELECT version FROM schema_version").fetchone()
            if row and row[0] != MYSQL_SCHEMA_VERSION:
                raise ValueError("MySQL 数据库版本不匹配，请先执行对应的结构迁移")
            if not row:
                self._conn.execute(
                    "INSERT INTO schema_version(version) VALUES (?)", (MYSQL_SCHEMA_VERSION,)
                )
                if seed_defaults:
                    self._migrate_schema_v6(self._conn.cursor(), None)
            self._conn.commit()
        except Exception:
            self._conn.close()
            raise

    def search_messages(self, query: str, limit: int = 20, offset: int = 0) -> dict:
        """消息规模较小时使用字面子串查询，保留中文、单字和标点搜索。"""
        if not query.strip():
            return {"items": [], "total": 0, "limit": limit, "offset": offset}
        where = (
            "WHERE INSTR(LOWER(m.content), LOWER(?)) > 0 "
            "AND (m.record_type IS NULL OR m.record_type != ?) "
        )
        params = (query, TITLE_RECORD_TYPE)
        total = self._conn.execute(
            "SELECT COUNT(*) FROM messages m " + where, params
        ).fetchone()[0]
        cursor = self._conn.execute(
            "SELECT m.*, c.source FROM messages m "
            "JOIN conversations c ON c.conversation_id = m.conversation_id "
            + where + "ORDER BY m.created_at DESC, m.id DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )
        records = []
        for row in cursor.fetchall():
            tool_calls = self._fetch_tool_calls(self._conn.cursor(), row["id"])
            record = self._row_to_record(row, tool_calls=tool_calls or None)
            record["rank"] = 0.0
            records.append(record)
        return {"items": records, "total": total, "limit": limit, "offset": offset}
