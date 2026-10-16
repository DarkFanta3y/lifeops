"""根据配置选择业务数据库；MySQL 不回退写入 SQLite。"""

from __future__ import annotations

from lifeops.core.config import AppConfig
from lifeops.storage.sqlite_store import ConversationHistoryStoreSQLite


def create_history_store(config: AppConfig) -> ConversationHistoryStoreSQLite:
    if config.database_url.strip():
        from lifeops.storage.mysql_store import ConversationHistoryStoreMySQL

        return ConversationHistoryStoreMySQL(config.database_url)
    return ConversationHistoryStoreSQLite(config.db_path)
