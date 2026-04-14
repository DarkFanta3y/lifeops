from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine


ToolHandler = Callable[[dict[str, Any]], Coroutine[Any, Any, "ToolResult"]]


@dataclass
class ToolParameter:
    name: str
    type: str
    description: str
    required: bool = False
    default: Any = None


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: list[ToolParameter] = field(default_factory=list)
    category: str = "builtin"


@dataclass
class ToolResult:
    success: bool
    output: str
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)