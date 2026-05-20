"""SQLite 数据库 schema 定义：对话历史存储的 DDL 与版本常量。"""

SCHEMA_VERSION = 4

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
    tool_name       TEXT,                          -- 工具结果消息的工具名（可空）
    tool_call_id    TEXT,                          -- 工具结果消息的调用 ID（可空）
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

CREATE INDEX IF NOT EXISTS idx_messages_tool_call_id
    ON messages(tool_call_id);

CREATE INDEX IF NOT EXISTS idx_tool_results_tool_call_id
    ON tool_results(tool_call_id);

-- conversation_summaries: 跨会话长期摘要
CREATE TABLE IF NOT EXISTS conversation_summaries (
    conversation_id TEXT PRIMARY KEY,
    summary         TEXT NOT NULL,
    key_decisions   TEXT NOT NULL DEFAULT '[]',
    action_items    TEXT NOT NULL DEFAULT '[]',
    topics          TEXT NOT NULL DEFAULT '[]',
    tone            TEXT,
    embedding       BLOB,
    importance_score REAL NOT NULL DEFAULT 0,
    last_accessed_at TEXT,
    access_count    INTEGER NOT NULL DEFAULT 0,
    message_count   INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
);

-- user_preferences: 全局用户偏好画像
CREATE TABLE IF NOT EXISTS user_preferences (
    preference_id    TEXT NOT NULL DEFAULT '',
    preference_type  TEXT NOT NULL DEFAULT 'general',
    key               TEXT PRIMARY KEY,
    value             TEXT NOT NULL,
    confidence        REAL NOT NULL DEFAULT 0,
    evidence          TEXT,
    source_conversation_id TEXT,
    observation_count INTEGER NOT NULL DEFAULT 1,
    last_observed_at  TEXT,
    is_active         INTEGER NOT NULL DEFAULT 1,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

-- skill_usage_stats: Skill 使用统计
CREATE TABLE IF NOT EXISTS skill_usage_stats (
    skill_name      TEXT PRIMARY KEY,
    activation_count INTEGER NOT NULL DEFAULT 0,
    explicit_activation_count INTEGER NOT NULL DEFAULT 0,
    implicit_activation_count INTEGER NOT NULL DEFAULT 0,
    success_count   INTEGER NOT NULL DEFAULT 0,
    failure_count   INTEGER NOT NULL DEFAULT 0,
    last_used_at    TEXT,
    metadata        TEXT NOT NULL DEFAULT '{}'
);

-- tool_usage_stats: 工具执行统计
CREATE TABLE IF NOT EXISTS tool_usage_stats (
    tool_name       TEXT PRIMARY KEY,
    call_count      INTEGER NOT NULL DEFAULT 0,
    success_count   INTEGER NOT NULL DEFAULT 0,
    failure_count   INTEGER NOT NULL DEFAULT 0,
    total_duration_ms REAL NOT NULL DEFAULT 0,
    last_used_at    TEXT,
    last_error      TEXT,
    metadata        TEXT NOT NULL DEFAULT '{}'
);

-- knowledge_graph_entities: 全局知识图谱实体
CREATE TABLE IF NOT EXISTS knowledge_graph_entities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id   TEXT NOT NULL DEFAULT '',
    name        TEXT NOT NULL,
    normalized_name TEXT NOT NULL DEFAULT '',
    entity_type TEXT NOT NULL,
    attributes  TEXT NOT NULL DEFAULT '{}',
    mention_count INTEGER NOT NULL DEFAULT 1,
    last_mentioned_at TEXT,
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE(name, entity_type)
);

-- knowledge_graph_relations: 全局知识图谱关系
CREATE TABLE IF NOT EXISTS knowledge_graph_relations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source        TEXT NOT NULL,
    target        TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    confidence    REAL NOT NULL DEFAULT 0,
    strength      REAL NOT NULL DEFAULT 0,
    mention_count INTEGER NOT NULL DEFAULT 1,
    last_observed_at TEXT,
    is_active     INTEGER NOT NULL DEFAULT 1,
    attributes    TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    UNIQUE(source, target, relation_type)
);

-- memory_config_snapshots: 记忆配置快照，便于排查运行时行为
CREATE TABLE IF NOT EXISTS memory_config_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot    TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

-- message_embeddings: 消息向量缓存
CREATE TABLE IF NOT EXISTS message_embeddings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    message_id      INTEGER NOT NULL,
    embedding       BLOB NOT NULL,
    created_at      TEXT NOT NULL,
    UNIQUE(message_id),
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
);

-- message_offload_metadata: L3 工具结果卸载记录
CREATE TABLE IF NOT EXISTS message_offload_metadata (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    context_key     TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    original_tokens INTEGER NOT NULL DEFAULT 0,
    summary         TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    UNIQUE(conversation_id, context_key),
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
);

-- compression_events: 上下文压缩事件
CREATE TABLE IF NOT EXISTS compression_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT,
    run_id          TEXT,
    phase           TEXT NOT NULL,
    freed_tokens    INTEGER NOT NULL DEFAULT 0,
    reason          TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
);

-- agent_runs: 单次 Agent 请求运行记录
CREATE TABLE IF NOT EXISTS agent_runs (
    run_id          TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    source          TEXT NOT NULL,
    status          TEXT NOT NULL,
    user_input      TEXT NOT NULL,
    final_output    TEXT,
    error_type      TEXT,
    error_message   TEXT,
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
);

-- agent_trace_events: 结构化运行轨迹
CREATE TABLE IF NOT EXISTS agent_trace_events (
    event_id        TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    sequence        INTEGER NOT NULL,
    payload_json    TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES agent_runs(run_id) ON DELETE CASCADE
);

-- tool_usage_events: 工具使用明细
CREATE TABLE IF NOT EXISTS tool_usage_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT,
    tool_name       TEXT NOT NULL,
    success         INTEGER NOT NULL,
    duration_ms     REAL NOT NULL DEFAULT 0,
    error           TEXT,
    created_at      TEXT NOT NULL
);

-- skill_usage_events: Skill 使用明细
CREATE TABLE IF NOT EXISTS skill_usage_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT,
    skill_name      TEXT NOT NULL,
    activation_type TEXT NOT NULL,
    success         INTEGER,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conversation_summaries_updated
    ON conversation_summaries(updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_user_preferences_confidence
    ON user_preferences(confidence DESC);

CREATE INDEX IF NOT EXISTS idx_knowledge_entities_name
    ON knowledge_graph_entities(name);

CREATE INDEX IF NOT EXISTS idx_knowledge_relations_source
    ON knowledge_graph_relations(source);

CREATE INDEX IF NOT EXISTS idx_compression_events_conversation
    ON compression_events(conversation_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_trace_events_run_sequence
    ON agent_trace_events(run_id, sequence);

CREATE INDEX IF NOT EXISTS idx_agent_runs_conversation_started
    ON agent_runs(conversation_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_tool_usage_events_run
    ON tool_usage_events(run_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_skill_usage_events_run
    ON skill_usage_events(run_id, created_at DESC);

-- FTS5 同步触发器：插入消息时自动更新全文索引
CREATE TRIGGER IF NOT EXISTS messages_fts_ai AFTER INSERT ON messages BEGIN
    INSERT INTO full_text_search(rowid, content) VALUES (new.id, new.content);
END;

-- FTS5 同步触发器：删除消息时自动清理全文索引
CREATE TRIGGER IF NOT EXISTS messages_fts_ad AFTER DELETE ON messages BEGIN
    INSERT INTO full_text_search(full_text_search, rowid, content) VALUES ('delete', old.id, old.content);
END;
"""
# fmt: on
