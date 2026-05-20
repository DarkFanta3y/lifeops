from __future__ import annotations

from typing import Any

from lifeops.core.config import MemoryConfig
from lifeops.core.context_manager import ContextLayer, ContextManager
from lifeops.memory.confidence import normalize_confidence
from lifeops.memory.extractor import MemoryExtractor
from lifeops.memory.retriever import MemoryRetriever
from lifeops.memory.summarizer import ConversationSummarizer
from lifeops.storage.sqlite_store import ConversationHistoryStoreSQLite
from lifeops.utils.logging import get_logger

logger = get_logger(__name__)


class MemoryService:
    def __init__(
        self,
        store: ConversationHistoryStoreSQLite,
        llm: Any,
        config: MemoryConfig,
        embedding_provider: Any | None = None,
    ) -> None:
        self.store = store
        self.llm = llm
        self.config = config
        self.summarizer = ConversationSummarizer(llm)
        self.extractor = MemoryExtractor()
        self.retriever = MemoryRetriever(store, embedding_provider=embedding_provider)
        self._record_config_snapshot()

    async def bootstrap_context(
        self,
        user_input: str,
        conversation_id: str,
        context: ContextManager,
        run_id: str | None = None,
        trace_recorder: Any | None = None,
    ) -> None:
        if not self.config.enabled:
            return
        self._record_trace(
            trace_recorder,
            "memory_bootstrap_started",
            {
                "conversation_id": conversation_id,
                "query_length": len(user_input),
                "summary_top_k": self.config.summary_top_k,
            },
            run_id,
        )
        try:
            summaries = [
                item
                for item in self.retriever.retrieve(user_input, self.config.summary_top_k)
                if item.get("conversation_id") != conversation_id
            ]
            for item in summaries[: self.config.summary_top_k]:
                key = f"memory:summary:{item['conversation_id']}"
                content = self._format_summary(item)
                context.add_content(key, content, ContextLayer.L2, token_count=len(content) // 4)

            preferences = self.store.get_user_preferences(
                min_confidence=self.config.preference_min_confidence
            )
            if preferences:
                content = self._format_preferences(preferences)
                context.add_content(
                    "memory:user_preferences",
                    content,
                    ContextLayer.L2,
                    token_count=len(content) // 4,
                )
            entities = self.store.search_knowledge_entities(user_input, limit=5)
            if entities:
                content = self._format_entities(entities)
                context.add_content(
                    "memory:knowledge_graph",
                    content,
                    ContextLayer.L2,
                    token_count=len(content) // 4,
                )
            self._record_trace(
                trace_recorder,
                "memory_bootstrap_finished",
                {
                    "summaries_count": len(summaries),
                    "preferences_count": len(preferences),
                    "entities_count": len(entities),
                },
                run_id,
            )
        except Exception:
            logger.exception("长期记忆上下文注入失败")
            self._record_trace(
                trace_recorder,
                "memory_bootstrap_failed",
                {"error": "长期记忆上下文注入失败"},
                run_id,
            )

    async def finalize_conversation(
        self,
        conversation_id: str,
        run_id: str | None = None,
        trace_recorder: Any | None = None,
    ) -> None:
        if not self.config.enabled:
            return
        self._record_trace(
            trace_recorder,
            "memory_finalize_started",
            {"conversation_id": conversation_id},
            run_id,
        )
        try:
            messages = self.store.get_messages(conversation_id)
            if not isinstance(messages, list) or not messages:
                return
            visible_messages = [
                item for item in messages if not item.get("intermediate") and item.get("role") != "tool"
            ]
            if not visible_messages:
                return
            existing_summary = self.store.get_conversation_summary(conversation_id)
            if existing_summary is not None and existing_summary.get("message_count") == len(
                visible_messages
            ):
                self._record_trace(
                    trace_recorder,
                    "memory_finalize_skipped",
                    {"reason": "message_count_unchanged"},
                    run_id,
                )
                return
            payload = await self.summarizer.summarize(visible_messages)
            summary_text = str(payload.get("summary") or "").strip()
            if not summary_text:
                return
            embedding = self._embed_summary(summary_text)
            self.store.insert_or_update_conversation_summary(
                {
                    "conversation_id": conversation_id,
                    "summary": summary_text,
                    "key_decisions": self._string_list(payload.get("key_decisions")),
                    "action_items": self._string_list(payload.get("action_items")),
                    "topics": self._string_list(payload.get("topics")),
                    "tone": payload.get("tone"),
                    "embedding": embedding,
                    "importance_score": normalize_confidence(payload.get("importance_score")),
                    "message_count": len(visible_messages),
                }
            )
            preferences = self.extractor.normalize_preferences(payload)
            for item in preferences:
                item.setdefault("source_conversation_id", conversation_id)
            entities = self.extractor.normalize_entities(payload)
            relations = self.extractor.normalize_relations(payload)
            self.store.upsert_user_preferences(preferences)
            self.store.upsert_knowledge_entities(entities)
            self.store.upsert_knowledge_relations(relations)
            self._record_trace(
                trace_recorder,
                "memory_finalize_finished",
                {
                    "summary_updated": True,
                    "preferences_count": len(preferences),
                    "entities_count": len(entities),
                    "relations_count": len(relations),
                },
                run_id,
            )
        except Exception:
            logger.exception("长期记忆学习失败")
            self._record_trace(
                trace_recorder,
                "memory_finalize_failed",
                {"error": "长期记忆学习失败"},
                run_id,
            )

    def stats(self) -> dict[str, int]:
        return self.store.get_memory_stats()

    def user_profile(self) -> dict[str, Any]:
        return {"preferences": self.store.get_user_preferences()}

    def knowledge_graph(self) -> dict[str, list[dict[str, Any]]]:
        return self.store.get_knowledge_graph()

    def summaries(self, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
        return self.store.list_conversation_summaries(limit=limit, offset=offset)

    def compression_events(
        self, limit: int | None = None, offset: int = 0
    ) -> list[dict[str, Any]]:
        return self.store.list_compression_events(limit=limit, offset=offset)

    def skill_usage(self) -> list[dict[str, Any]]:
        return self.store.list_skill_usage()

    def tool_stats(self) -> list[dict[str, Any]]:
        return self.store.list_tool_usage_stats()

    def search(self, query: str, top_k: int | None = None) -> dict[str, Any]:
        effective_top_k = top_k or self.config.summary_top_k
        return {
            "summaries": self.retriever.retrieve(query, effective_top_k),
            "preferences": self.store.get_user_preferences(
                min_confidence=self.config.preference_min_confidence
            ),
            "entities": self.store.search_knowledge_entities(query, limit=5),
        }

    def delete_preference(self, preference_id: str) -> bool:
        return self.store.delete_user_preference(preference_id)

    def delete_entity(self, entity_id: str) -> bool:
        return self.store.delete_knowledge_entity(entity_id)

    def forget(
        self,
        *,
        dry_run: bool = True,
        preference_confidence_below: float = 0.2,
        relation_strength_below: float = 0.2,
    ) -> dict[str, Any]:
        return self.store.forget_low_value_memories(
            dry_run=dry_run,
            preference_confidence_below=preference_confidence_below,
            relation_strength_below=relation_strength_below,
        )

    def record_tool_usage(
        self,
        tool_name: str,
        *,
        success: bool,
        duration_ms: float,
        error: str | None = None,
        run_id: str | None = None,
    ) -> None:
        self.store.record_tool_usage(
            tool_name,
            success=success,
            duration_ms=duration_ms,
            error=error,
            run_id=run_id,
        )

    def record_skill_usage(
        self,
        skill_name: str,
        *,
        activation_type: str,
        success: bool | None = None,
        run_id: str | None = None,
    ) -> None:
        self.store.record_skill_usage(
            skill_name,
            activation_type=activation_type,
            success=success,
            run_id=run_id,
        )

    def _record_trace(
        self,
        trace_recorder: Any | None,
        event_type: str,
        payload: dict[str, Any],
        run_id: str | None,
    ) -> None:
        if trace_recorder is None:
            return
        try:
            trace_recorder.record(event_type, payload, run_id=run_id)
        except Exception:
            logger.exception("记录长期记忆 trace 失败")

    def _format_summary(self, item: dict[str, Any]) -> str:
        topics = "、".join(item.get("topics") or [])
        return (
            "## 跨会话记忆摘要\n"
            f"会话: {item.get('conversation_id')}\n"
            f"主题: {topics}\n"
            f"摘要: {item.get('summary')}"
        )

    def _format_preferences(self, preferences: list[dict[str, Any]]) -> str:
        lines = ["## 高置信用户偏好"]
        for item in preferences:
            lines.append(
                f"- {item['key']}: {item['value']} "
                f"(confidence={item['confidence']:.2f})"
            )
        return "\n".join(lines)

    def _format_entities(self, entities: list[dict[str, Any]]) -> str:
        lines = ["## 相关知识图谱背景"]
        for item in entities:
            lines.append(f"- {item.get('name')} ({item.get('entity_type')})")
        return "\n".join(lines)

    def _string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if item is not None]

    def _embed_summary(self, summary: str) -> list[float] | None:
        provider = self.retriever.embedding_provider
        if provider is None:
            return None
        try:
            return provider.embed_query(summary)
        except Exception:
            logger.warning("摘要 embedding 生成失败，降级为 BM25 检索", exc_info=True)
            return None

    def _record_config_snapshot(self) -> None:
        if not hasattr(self.store, "record_memory_config_snapshot"):
            return
        try:
            snapshot = (
                self.config.model_dump()
                if hasattr(self.config, "model_dump")
                else dict(self.config)
            )
            self.store.record_memory_config_snapshot(snapshot)
        except Exception:
            logger.warning("记录记忆配置快照失败", exc_info=True)
