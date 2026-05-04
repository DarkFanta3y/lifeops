"""SQLite-based conversation history storage module."""

from lifeops.storage.migration import auto_migrate, migrate_jsonl_to_sqlite, should_migrate
from lifeops.storage.schema import CREATE_TABLES_SQL, SCHEMA_VERSION
from lifeops.storage.sqlite_store import ConversationHistoryStoreSQLite

__all__ = [
    "ConversationHistoryStoreSQLite",
    "SCHEMA_VERSION",
    "CREATE_TABLES_SQL",
    "auto_migrate",
    "migrate_jsonl_to_sqlite",
    "should_migrate",
]
