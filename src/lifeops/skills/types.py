from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class SkillSource(str, Enum):
    PROJECT = "project"
    USER = "user"


@dataclass(frozen=True)
class SkillMetadata:
    name: str
    description: str
    path: Path
    directory: Path
    source: SkillSource
    raw_frontmatter: dict[str, Any]
    short_description: str | None = None
    allowed_tools: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    allow_implicit_invocation: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SkillDefinition:
    metadata: SkillMetadata
    content: str


@dataclass(frozen=True)
class SkillMatch:
    name: str
    reason: str
    explicit: bool = False


@dataclass(frozen=True)
class SkillMatchResult:
    matches: list[SkillMatch]
    unknown_names: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SkillCatalog:
    skills: dict[str, SkillMetadata]
    warnings: list[str] = field(default_factory=list)
