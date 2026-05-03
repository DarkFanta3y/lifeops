from __future__ import annotations

import re

try:
    import jieba
except Exception:  # pragma: no cover - 依赖缺失时的降级路径
    jieba = None


_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fff]+")


def tokenize(text: str) -> list[str]:
    lowered = text.lower()
    tokens: list[str] = []
    if jieba is not None:
        tokens.extend(token.strip().lower() for token in jieba.cut(lowered) if token.strip())

    for match in _TOKEN_RE.findall(lowered):
        tokens.append(match)
        if _is_cjk(match):
            tokens.extend(match[index : index + 2] for index in range(max(0, len(match) - 1)))

    return [token for token in tokens if token]


def _is_cjk(value: str) -> bool:
    return bool(value) and all("\u4e00" <= char <= "\u9fff" for char in value)
