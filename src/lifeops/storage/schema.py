"""SQLite 数据库 schema 定义：对话历史存储的 DDL 与版本常量。"""

SCHEMA_VERSION = 1

# fmt: off
CREATE_TABLES_SQL = """
-- conversations: 会话元数据
CREATE TABLE IF NOT EXISTS conversations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT    NOT NULL UNIQUE,
    source          TEXT    NOT NULL,              -- "web" | "cli"
    title           TEXT,                          -- 会话标题（可空）
    message_count   INTEGER NOT NULL DEFAULT 0,
    last_message    TEXT,                          -- 最后一条消息预览（可空）
    created_at      TEXT    NOT NULL,              -- ISO 8601
    updated_at      TEXT    NOT NULL               -- ISO 8601
);

-- messages: 消息记录
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT    NOT NULL,
    role            TEXT    NOT NULL,              -- "user" | "assistant" | "tool" | "system"
    content         TEXT    NOT NULL,
    created_at      TEXT    NOT NULL,              -- ISO 8601
    intermediate    INTEGER NOT NULL DEFAULT 0,   -- 0=false, 1=true
    record_type     TEXT,                          -- 例: "conversation_title"
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id)
);

-- tool_calls: 工具调用记录
CREATE TABLE IF NOT EXISTS tool_calls (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id    INTEGER NOT NULL,
    tool_call_id  TEXT    NOT NULL UNIQUE,
    tool_name     TEXT    NOT NULL,
    arguments     TEXT    NOT NULL,                -- JSON 字符串
    created_at    TEXT    NOT NULL,
    FOREIGN KEY (message_id) REFERENCES messages(id)
);

-- tool_results: 工具执行结果
CREATE TABLE IF NOT EXISTS tool_results (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_call_id  TEXT    NOT NULL,
    result        TEXT    NOT NULL,                -- JSON 字符串
    created_at    TEXT    NOT NULL,
    FOREIGN KEY (tool_call_id) REFERENCES tool_calls(tool_call_id)
);

-- full_text_search: FTS5 全文检索虚拟表
CREATE VIRTUAL TABLE IF NOT EXISTS full_text_search
    USING fts5(
        content,
        content=messages,
        content_rowid=id
    );

-- 索引
CREATE INDEX IF NOT EXISTS idx_conversations_updated_at
    ON conversations(updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_created
    ON messages(conversation_id, created_at);

CREATE INDEX IF NOT EXISTS idx_messages_intermediate
    ON messages(intermediate);

CREATE INDEX IF NOT EXISTS idx_tool_calls_message_id
    ON tool_calls(message_id);

CREATE INDEX IF NOT EXISTS idx_tool_results_tool_call_id
    ON tool_results(tool_call_id);
"""
# fmt: on
