from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from pydantic import BaseModel


class ToolParams(BaseModel):
    """所有工具参数的基类。"""

    model_config = {"extra": "forbid"}


ToolHandler = Callable[[dict[str, Any]], Coroutine[Any, Any, "ToolResult"]]


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters_model: type[ToolParams]
    category: str = "builtin"


@dataclass
class ToolResult:
    success: bool
    output: str
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
