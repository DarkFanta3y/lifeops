from __future__ import annotations

from typing import Any

from lifeops.core.config import MemoryConfig
from lifeops.core.context_manager import ContextLayer, ContextManager
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
    ) -> None:
        self.store = store
        self.llm = llm
        self.config = config
        self.summarizer = ConversationSummarizer(llm)
        self.extractor = MemoryExtractor()
        self.retriever = MemoryRetriever(store)

    async def bootstrap_context(
        self,
        user_input: str,
        conversation_id: str,
        context: ContextManager,
    ) -> None:
        if not self.config.enabled:
            return
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
        except Exception:
            logger.exception("长期记忆上下文注入失败")

    async def finalize_conversation(self, conversation_id: str) -> None:
        if not self.config.enabled:
            return
        try:
            if self.store.get_conversation_summary(conversation_id) is not None:
                return
            messages = self.store.get_messages(conversation_id)
            if not isinstance(messages, list) or not messages:
                return
            visible_messages = [
                item for item in messages if not item.get("intermediate") and item.get("role") != "tool"
            ]
            if not visible_messages:
                return
            payload = await self.summarizer.summarize(visible_messages)
            summary_text = str(payload.get("summary") or "").strip()
            if not summary_text:
                return
            self.store.insert_or_update_conversation_summary(
                {
                    "conversation_id": conversation_id,
                    "summary": summary_text,
                    "key_decisions": self._string_list(payload.get("key_decisions")),
                    "action_items": self._string_list(payload.get("action_items")),
                    "topics": self._string_list(payload.get("topics")),
                    "tone": payload.get("tone"),
                }
            )
            self.store.upsert_user_preferences(self.extractor.normalize_preferences(payload))
            self.store.upsert_knowledge_entities(self.extractor.normalize_entities(payload))
            self.store.upsert_knowledge_relations(self.extractor.normalize_relations(payload))
        except Exception:
            logger.exception("长期记忆学习失败")

    def stats(self) -> dict[str, int]:
        return self.store.get_memory_stats()

    def user_profile(self) -> dict[str, Any]:
        return {"preferences": self.store.get_user_preferences()}

    def knowledge_graph(self) -> dict[str, list[dict[str, Any]]]:
        return self.store.get_knowledge_graph()

    def summaries(self, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
        return self.store.list_conversation_summaries(limit=limit, offset=offset)

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

    def _string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if item is not None]
