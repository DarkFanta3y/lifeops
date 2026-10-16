"""业务数据仓储，支持 MySQL 与旧 SQLite 数据读取。"""

from lifeops.storage.factory import create_history_store
from lifeops.storage.migration import auto_migrate, migrate_jsonl_to_sqlite, should_migrate
from lifeops.storage.schema import CREATE_TABLES_SQL, SCHEMA_VERSION
from lifeops.storage.sqlite_store import ConversationHistoryStoreSQLite

__all__ = [
    "create_history_store",
    "ConversationHistoryStoreSQLite",
    "SCHEMA_VERSION",
    "CREATE_TABLES_SQL",
    "auto_migrate",
    "migrate_jsonl_to_sqlite",
    "should_migrate",
]
