from __future__ import annotations

from typing import Any


def sanitize_unicode_text(value: str) -> str:
    """规范化 surrogate 字符，确保返回值可安全 UTF-8 编码。"""
    return value.encode("utf-16", "surrogatepass").decode("utf-16", "replace")


def sanitize_unicode_data(value: Any) -> Any:
    """递归清洗容器中的字符串，避免外部 JSON 数据携带非法 surrogate。"""
    if isinstance(value, str):
        return sanitize_unicode_text(value)
    if isinstance(value, list):
        return [sanitize_unicode_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_unicode_data(item) for item in value)
    if isinstance(value, dict):
        return {
            sanitize_unicode_data(key): sanitize_unicode_data(item)
            for key, item in value.items()
        }
    return value
