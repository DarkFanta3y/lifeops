from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from lifeops.core.config import MemoryConfig, PROJECT_ROOT
from lifeops.core.context_manager import ContextEntry, ContextLayer, ContextManager
from lifeops.storage.sqlite_store import ConversationHistoryStoreSQLite
from lifeops.utils.logging import get_logger

logger = get_logger(__name__)


class CompressionPipeline:
    def __init__(
        self,
        context: ContextManager,
        store: ConversationHistoryStoreSQLite | None,
        config: MemoryConfig,
    ) -> None:
        self.context = context
        self.store = store
        self.config = config

    def execute(self, conversation_id: str | None = None) -> dict[str, int | str]:
        suggestion = self.context.suggest_compression()
        phase = str(suggestion["phase"])
        if phase == "none":
            return {"phase": "none", "freed_tokens": 0, "reason": "上下文压力正常"}
        if phase == "pressure":
            return self._record(conversation_id, "pressure", 0, "上下文达到 70% 压力")
        if phase == "offload":
            return self._offload_large_l3(conversation_id)
        if phase == "trim":
            return self._trim_old_l3(conversation_id)
        if phase == "summarize":
            return self._dedupe_and_summarize(conversation_id)
        return self._critical_cleanup(conversation_id)

    def _offload_large_l3(self, conversation_id: str | None) -> dict[str, int | str]:
        entries = sorted(
            self.context.get_l3_content(),
            key=lambda entry: entry.token_count,
            reverse=True,
        )
        if not entries:
            return self._record(conversation_id, "offload", 0, "没有可卸载的 L3 内容")

        target = entries[0]
        offload_dir = self._offload_dir()
        offload_dir.mkdir(parents=True, exist_ok=True)
        file_path = offload_dir / f"{conversation_id or 'context'}-{uuid4().hex}.txt"
        file_path.write_text(target.content, encoding="utf-8")
        summary = self._summarize_entry(target)
        new_tokens = max(1, len(summary) // 4)
        self.context.add_content(target.key, summary, ContextLayer.L3, token_count=new_tokens)
        freed = max(0, target.token_count - new_tokens)
        if self.store is not None and conversation_id is not None:
            self.store.record_offload_metadata(
                conversation_id,
                target.key,
                str(file_path),
                target.token_count,
                summary,
            )
        return self._record(conversation_id, "offload", freed, "大型 L3 工具结果已卸载")

    def _trim_old_l3(self, conversation_id: str | None) -> dict[str, int | str]:
        entries = sorted(self.context.get_l3_content(), key=lambda entry: entry.key)
        removable = entries[:-2] if len(entries) > 2 else entries[:1]
        freed = 0
        for entry in removable:
            freed += entry.token_count
            self.context.remove_content(entry.key)
        return self._record(conversation_id, "trim", freed, "修剪旧 L3 工具结果")

    def _dedupe_and_summarize(self, conversation_id: str | None) -> dict[str, int | str]:
        seen: dict[str, str] = {}
        freed = 0
        for entry in list(self.context.get_l3_content()):
            fingerprint = entry.content.strip()
            if fingerprint in seen:
                freed += entry.token_count
                self.context.remove_content(entry.key)
                continue
            seen[fingerprint] = entry.key
            if entry.token_count > 20:
                summary = self._summarize_entry(entry)
                new_tokens = max(1, len(summary) // 4)
                if new_tokens < entry.token_count:
                    self.context.add_content(entry.key, summary, ContextLayer.L3, new_tokens)
                    freed += entry.token_count - new_tokens
        return self._record(conversation_id, "summarize", freed, "L3 去重和摘要压缩")

    def _critical_cleanup(self, conversation_id: str | None) -> dict[str, int | str]:
        freed = 0
        for entry in sorted(
            self.context.get_l3_content(),
            key=lambda item: item.token_count,
            reverse=True,
        ):
            if self.context.used_tokens / self.context.max_tokens < 0.90:
                break
            freed += entry.token_count
            self.context.remove_content(entry.key)
        for entry in sorted(
            self.context.get_l2_content(),
            key=lambda item: item.token_count,
            reverse=True,
        ):
            if self.context.used_tokens / self.context.max_tokens < 0.90:
                break
            freed += entry.token_count
            self.context.remove_content(entry.key)
        return self._record(conversation_id, "critical", freed, "critical 清理最旧 L2/L3")

    def _record(
        self,
        conversation_id: str | None,
        phase: str,
        freed_tokens: int,
        reason: str,
    ) -> dict[str, int | str]:
        self.context.log_compression_event(phase, freed_tokens, reason, conversation_id)
        if self.store is not None:
            try:
                self.store.record_compression_event(conversation_id, phase, freed_tokens, reason)
            except Exception:
                logger.exception("记录压缩事件失败")
        return {"phase": phase, "freed_tokens": freed_tokens, "reason": reason}

    def _offload_dir(self) -> Path:
        path = Path(self.config.offload_dir).expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path

    def _summarize_entry(self, entry: ContextEntry) -> str:
        preview = entry.content.strip().replace("\n", " ")
        if len(preview) > 240:
            preview = preview[:240] + "..."
        return (
            f"[已卸载/压缩的工具结果]\n"
            f"key: {entry.key}\n"
            f"原始 token 估算: {entry.token_count}\n"
            f"摘要: {preview}"
        )
