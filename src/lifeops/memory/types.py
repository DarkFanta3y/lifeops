from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ConversationSummary:
    conversation_id: str
    summary: str
    key_decisions: list[str] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    tone: str | None = None
    embedding: list[float] | None = None


@dataclass(frozen=True)
class UserPreference:
    key: str
    value: str
    confidence: float = 0
    evidence: str | None = None


@dataclass(frozen=True)
class KnowledgeEntity:
    name: str
    entity_type: str = "unknown"
    attributes: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeRelation:
    source: str
    target: str
    relation_type: str
    confidence: float = 0
    attributes: dict[str, object] = field(default_factory=dict)
