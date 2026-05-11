"""长期记忆系统。"""

from typing import Any

__all__ = ["MemoryService"]


def __getattr__(name: str) -> Any:
    if name == "MemoryService":
        from lifeops.memory.service import MemoryService

        return MemoryService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
