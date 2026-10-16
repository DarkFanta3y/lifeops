"""MySQL 8.4 业务表结构；全文检索改用原始消息表，不复制 SQLite 派生索引。"""

MYSQL_SCHEMA_VERSION = 8

MYSQL_TABLES = ['conversations', 'rag_sources', 'messages', 'tool_calls', 'tool_results', 'conversation_summaries', 'user_preferences', 'skill_usage_stats', 'tool_usage_stats', 'knowledge_graph_entities', 'knowledge_graph_relations', 'memory_config_snapshots', 'message_embeddings', 'message_offload_metadata', 'compression_events', 'agent_runs', 'agent_trace_events', 'context_snapshots', 'context_blobs', 'tool_usage_events', 'skill_usage_events', 'schema_version']

MYSQL_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS `conversations` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `conversation_id` VARCHAR(128) NOT NULL,
  `source` LONGTEXT NOT NULL,
  `title` LONGTEXT,
  `message_count` BIGINT NOT NULL DEFAULT 0,
  `last_message` LONGTEXT,
  `plan_mode` BIGINT NOT NULL DEFAULT 0,
  `created_at` VARCHAR(40) NOT NULL,
  `updated_at` VARCHAR(40) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_conversations_updated_at` (`updated_at`),
  UNIQUE KEY `uq_conversations_0` (`conversation_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;

CREATE TABLE IF NOT EXISTS `rag_sources` (
  `source_id` VARCHAR(128) NOT NULL,
  `name` LONGTEXT NOT NULL,
  `description` LONGTEXT NOT NULL,
  `call_when` LONGTEXT NOT NULL,
  `path_prefix` VARCHAR(512) NOT NULL,
  `enabled` BIGINT NOT NULL DEFAULT 1 CHECK (`enabled` IN (0, 1)),
  `chunk_strategy` LONGTEXT NOT NULL DEFAULT ('heading'),
  `chunk_size` BIGINT NOT NULL DEFAULT 900,
  `created_at` VARCHAR(40) NOT NULL,
  `updated_at` VARCHAR(40) NOT NULL,
  PRIMARY KEY (`source_id`),
  UNIQUE KEY `uq_rag_sources_0` (`path_prefix`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;

CREATE TABLE IF NOT EXISTS `messages` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `conversation_id` VARCHAR(128) NOT NULL,
  `role` LONGTEXT NOT NULL,
  `content` LONGTEXT NOT NULL,
  `created_at` VARCHAR(40) NOT NULL,
  `intermediate` BIGINT NOT NULL DEFAULT 0,
  `tool_name` VARCHAR(256),
  `tool_call_id` VARCHAR(256),
  `reasoning_content` LONGTEXT,
  `record_type` LONGTEXT,
  PRIMARY KEY (`id`),
  KEY `idx_messages_tool_call_id` (`tool_call_id`),
  KEY `idx_messages_intermediate` (`intermediate`),
  KEY `idx_messages_conversation_created` (`conversation_id`, `created_at`),
  CONSTRAINT `fk_messages_0` FOREIGN KEY (`conversation_id`) REFERENCES `conversations` (`conversation_id`) ON DELETE NO ACTION
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;

CREATE TABLE IF NOT EXISTS `tool_calls` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `message_id` BIGINT NOT NULL,
  `tool_call_id` VARCHAR(256) NOT NULL,
  `tool_name` VARCHAR(256) NOT NULL,
  `arguments` LONGTEXT NOT NULL,
  `created_at` VARCHAR(40) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_tool_calls_message_id` (`message_id`),
  UNIQUE KEY `uq_tool_calls_0` (`tool_call_id`),
  CONSTRAINT `fk_tool_calls_0` FOREIGN KEY (`message_id`) REFERENCES `messages` (`id`) ON DELETE NO ACTION
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;

CREATE TABLE IF NOT EXISTS `tool_results` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `tool_call_id` VARCHAR(256) NOT NULL,
  `result` LONGTEXT NOT NULL,
  `created_at` VARCHAR(40) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_tool_results_tool_call_id` (`tool_call_id`),
  CONSTRAINT `fk_tool_results_0` FOREIGN KEY (`tool_call_id`) REFERENCES `tool_calls` (`tool_call_id`) ON DELETE NO ACTION
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;

CREATE TABLE IF NOT EXISTS `conversation_summaries` (
  `conversation_id` VARCHAR(128) NOT NULL,
  `summary` LONGTEXT NOT NULL,
  `key_decisions` LONGTEXT NOT NULL DEFAULT ('[]'),
  `action_items` LONGTEXT NOT NULL DEFAULT ('[]'),
  `topics` LONGTEXT NOT NULL DEFAULT ('[]'),
  `tone` LONGTEXT,
  `embedding` LONGBLOB,
  `importance_score` DOUBLE NOT NULL DEFAULT 0,
  `last_accessed_at` VARCHAR(40),
  `access_count` BIGINT NOT NULL DEFAULT 0,
  `message_count` BIGINT NOT NULL DEFAULT 0,
  `created_at` VARCHAR(40) NOT NULL,
  `updated_at` VARCHAR(40) NOT NULL,
  PRIMARY KEY (`conversation_id`),
  KEY `idx_conversation_summaries_updated` (`updated_at`),
  CONSTRAINT `fk_conversation_summaries_0` FOREIGN KEY (`conversation_id`) REFERENCES `conversations` (`conversation_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;

CREATE TABLE IF NOT EXISTS `user_preferences` (
  `preference_id` LONGTEXT NOT NULL DEFAULT (''),
  `preference_type` LONGTEXT NOT NULL DEFAULT ('general'),
  `key` VARCHAR(512) NOT NULL,
  `value` LONGTEXT NOT NULL,
  `confidence` DOUBLE NOT NULL DEFAULT 0,
  `evidence` LONGTEXT,
  `source_conversation_id` LONGTEXT,
  `observation_count` BIGINT NOT NULL DEFAULT 1,
  `last_observed_at` VARCHAR(40),
  `is_active` BIGINT NOT NULL DEFAULT 1,
  `created_at` VARCHAR(40) NOT NULL,
  `updated_at` VARCHAR(40) NOT NULL,
  PRIMARY KEY (`key`),
  KEY `idx_user_preferences_confidence` (`confidence`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;

CREATE TABLE IF NOT EXISTS `skill_usage_stats` (
  `skill_name` VARCHAR(256) NOT NULL,
  `activation_count` BIGINT NOT NULL DEFAULT 0,
  `explicit_activation_count` BIGINT NOT NULL DEFAULT 0,
  `implicit_activation_count` BIGINT NOT NULL DEFAULT 0,
  `success_count` BIGINT NOT NULL DEFAULT 0,
  `failure_count` BIGINT NOT NULL DEFAULT 0,
  `last_used_at` VARCHAR(40),
  `metadata` LONGTEXT NOT NULL DEFAULT ('{}'),
  PRIMARY KEY (`skill_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;

CREATE TABLE IF NOT EXISTS `tool_usage_stats` (
  `tool_name` VARCHAR(256) NOT NULL,
  `call_count` BIGINT NOT NULL DEFAULT 0,
  `success_count` BIGINT NOT NULL DEFAULT 0,
  `failure_count` BIGINT NOT NULL DEFAULT 0,
  `total_duration_ms` DOUBLE NOT NULL DEFAULT 0,
  `last_used_at` VARCHAR(40),
  `last_error` LONGTEXT,
  `metadata` LONGTEXT NOT NULL DEFAULT ('{}'),
  PRIMARY KEY (`tool_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;

CREATE TABLE IF NOT EXISTS `knowledge_graph_entities` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `entity_id` LONGTEXT NOT NULL DEFAULT (''),
  `name` VARCHAR(512) NOT NULL,
  `normalized_name` LONGTEXT NOT NULL DEFAULT (''),
  `entity_type` VARCHAR(128) NOT NULL,
  `attributes` LONGTEXT NOT NULL DEFAULT ('{}'),
  `mention_count` BIGINT NOT NULL DEFAULT 1,
  `last_mentioned_at` VARCHAR(40),
  `is_active` BIGINT NOT NULL DEFAULT 1,
  `created_at` VARCHAR(40) NOT NULL,
  `updated_at` VARCHAR(40) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_knowledge_entities_name` (`name`),
  UNIQUE KEY `uq_knowledge_graph_entities_0` (`name`, `entity_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;

CREATE TABLE IF NOT EXISTS `knowledge_graph_relations` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `source` VARCHAR(256) NOT NULL,
  `target` VARCHAR(256) NOT NULL,
  `relation_type` VARCHAR(128) NOT NULL,
  `confidence` DOUBLE NOT NULL DEFAULT 0,
  `strength` DOUBLE NOT NULL DEFAULT 0,
  `mention_count` BIGINT NOT NULL DEFAULT 1,
  `last_observed_at` VARCHAR(40),
  `is_active` BIGINT NOT NULL DEFAULT 1,
  `attributes` LONGTEXT NOT NULL DEFAULT ('{}'),
  `created_at` VARCHAR(40) NOT NULL,
  `updated_at` VARCHAR(40) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_knowledge_relations_source` (`source`),
  UNIQUE KEY `uq_knowledge_graph_relations_0` (`source`, `target`, `relation_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;

CREATE TABLE IF NOT EXISTS `memory_config_snapshots` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `snapshot` LONGTEXT NOT NULL,
  `created_at` VARCHAR(40) NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;

CREATE TABLE IF NOT EXISTS `message_embeddings` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `conversation_id` VARCHAR(128) NOT NULL,
  `message_id` BIGINT NOT NULL,
  `embedding` LONGBLOB NOT NULL,
  `created_at` VARCHAR(40) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_message_embeddings_0` (`message_id`),
  CONSTRAINT `fk_message_embeddings_0` FOREIGN KEY (`message_id`) REFERENCES `messages` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_message_embeddings_1` FOREIGN KEY (`conversation_id`) REFERENCES `conversations` (`conversation_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;

CREATE TABLE IF NOT EXISTS `message_offload_metadata` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `conversation_id` VARCHAR(128) NOT NULL,
  `context_key` VARCHAR(512) NOT NULL,
  `file_path` LONGTEXT NOT NULL,
  `original_tokens` BIGINT NOT NULL DEFAULT 0,
  `summary` LONGTEXT NOT NULL,
  `created_at` VARCHAR(40) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_message_offload_metadata_0` (`conversation_id`, `context_key`),
  CONSTRAINT `fk_message_offload_metadata_0` FOREIGN KEY (`conversation_id`) REFERENCES `conversations` (`conversation_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;

CREATE TABLE IF NOT EXISTS `compression_events` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `conversation_id` VARCHAR(128),
  `run_id` VARCHAR(128),
  `phase` LONGTEXT NOT NULL,
  `freed_tokens` BIGINT NOT NULL DEFAULT 0,
  `reason` LONGTEXT NOT NULL,
  `created_at` VARCHAR(40) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_compression_events_conversation` (`conversation_id`, `created_at`),
  CONSTRAINT `fk_compression_events_0` FOREIGN KEY (`conversation_id`) REFERENCES `conversations` (`conversation_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;

CREATE TABLE IF NOT EXISTS `agent_runs` (
  `run_id` VARCHAR(128) NOT NULL,
  `conversation_id` VARCHAR(128) NOT NULL,
  `source` LONGTEXT NOT NULL,
  `status` LONGTEXT NOT NULL,
  `user_input` LONGTEXT NOT NULL,
  `final_output` LONGTEXT,
  `error_type` LONGTEXT,
  `error_message` LONGTEXT,
  `started_at` VARCHAR(40) NOT NULL,
  `ended_at` VARCHAR(40),
  PRIMARY KEY (`run_id`),
  KEY `idx_agent_runs_conversation_started` (`conversation_id`, `started_at`),
  CONSTRAINT `fk_agent_runs_0` FOREIGN KEY (`conversation_id`) REFERENCES `conversations` (`conversation_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;

CREATE TABLE IF NOT EXISTS `agent_trace_events` (
  `event_id` VARCHAR(128) NOT NULL,
  `run_id` VARCHAR(128) NOT NULL,
  `event_type` LONGTEXT NOT NULL,
  `sequence` BIGINT NOT NULL,
  `payload_json` LONGTEXT NOT NULL,
  `created_at` VARCHAR(40) NOT NULL,
  PRIMARY KEY (`event_id`),
  KEY `idx_agent_trace_events_run_sequence` (`run_id`, `sequence`),
  CONSTRAINT `fk_agent_trace_events_0` FOREIGN KEY (`run_id`) REFERENCES `agent_runs` (`run_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;

CREATE TABLE IF NOT EXISTS `context_snapshots` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `run_id` VARCHAR(128) NOT NULL,
  `conversation_id` VARCHAR(128) NOT NULL,
  `agent_id` LONGTEXT NOT NULL DEFAULT ('main'),
  `parent_agent_id` LONGTEXT,
  `iteration` BIGINT NOT NULL DEFAULT 0,
  `model` LONGTEXT,
  `budget` BIGINT NOT NULL DEFAULT 0,
  `reserve_ratio` DOUBLE NOT NULL DEFAULT 0,
  `estimated_tokens` BIGINT NOT NULL DEFAULT 0,
  `categories_json` LONGTEXT NOT NULL,
  `elements_json` LONGTEXT NOT NULL,
  `usage_json` LONGTEXT,
  `response_json` LONGTEXT,
  `trimmed_count` BIGINT NOT NULL DEFAULT 0,
  `truncated_count` BIGINT NOT NULL DEFAULT 0,
  `started_at_ms` BIGINT NOT NULL,
  `ttft_ms` BIGINT,
  `duration_ms` BIGINT,
  `created_at` VARCHAR(40) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_context_snapshots_run` (`run_id`, `id`),
  KEY `idx_context_snapshots_conversation` (`conversation_id`, `id`),
  CONSTRAINT `fk_context_snapshots_0` FOREIGN KEY (`run_id`) REFERENCES `agent_runs` (`run_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;

CREATE TABLE IF NOT EXISTS `context_blobs` (
  `hash` VARCHAR(64) NOT NULL,
  `content` LONGTEXT NOT NULL,
  PRIMARY KEY (`hash`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;

CREATE TABLE IF NOT EXISTS `tool_usage_events` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `run_id` VARCHAR(128),
  `tool_name` VARCHAR(256) NOT NULL,
  `success` BIGINT NOT NULL,
  `duration_ms` DOUBLE NOT NULL DEFAULT 0,
  `error` LONGTEXT,
  `created_at` VARCHAR(40) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_tool_usage_events_run` (`run_id`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;

CREATE TABLE IF NOT EXISTS `skill_usage_events` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `run_id` VARCHAR(128),
  `skill_name` VARCHAR(256) NOT NULL,
  `activation_type` LONGTEXT NOT NULL,
  `success` BIGINT,
  `created_at` VARCHAR(40) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_skill_usage_events_run` (`run_id`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;

CREATE TABLE IF NOT EXISTS `schema_version` (
  `version` BIGINT NOT NULL,
  PRIMARY KEY (`version`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
"""
