from __future__ import annotations

from typing import Any

_CONFIDENCE_LABELS = {
    "高": 0.9,
    "中": 0.5,
    "低": 0.2,
    "high": 0.9,
    "medium": 0.5,
    "low": 0.2,
}


def normalize_confidence(value: Any, *, default: float = 0.0) -> float:
    """将 LLM 输出的置信度归一化为 0.0 到 1.0 之间的浮点数。"""
    if value is None:
        return _clamp(default)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return _clamp(default)
        label = _CONFIDENCE_LABELS.get(text.casefold())
        if label is not None:
            return label
        value = text
    try:
        return _clamp(float(value))
    except (TypeError, ValueError):
        return _clamp(default)


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, float(value)))
