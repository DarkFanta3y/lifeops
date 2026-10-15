"""上下文洞察：记录每次 LLM 请求的上下文构成，并提供会话与跨会话的观测数据（改编自 dsh-context）。"""

from lifeops.context_insight.composition import ContextElement, SystemPart, build_composition
from lifeops.context_insight.store import ContextSnapshotStore

__all__ = ["ContextElement", "ContextSnapshotStore", "SystemPart", "build_composition"]
