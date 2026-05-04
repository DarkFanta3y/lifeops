from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from lifeops.core.config import RAGConfig
from lifeops.rag.loader import load_markdown_document
from lifeops.rag.types import KnowledgeDocument, RAGDataType, RAGRoutePlan

_ALIASES: dict[str, tuple[str, ...]] = {
    "breakfast": ("早餐", "早饭", "早点", "早上", "明早"),
    "meat_dish": ("肉菜", "肉类", "猪肉", "牛肉", "羊肉", "鸡肉", "荤菜"),
    "aquatic": ("水产", "鱼", "虾", "蟹", "海鲜", "鳝"),
    "dessert": ("甜品", "甜点", "蛋糕", "糕点"),
    "condiment": ("酱料", "调料", "蘸料", "汁"),
    "vegetable_dish": ("素菜", "蔬菜", "青菜"),
}


def discover_rag_data_types(config: RAGConfig) -> list[RAGDataType]:
    documents = _load_documents(config)
    grouped: dict[str, list[KnowledgeDocument]] = defaultdict(list)
    for document in documents:
        parts = Path(document.path).parts
        if len(parts) <= 1:
            continue
        for depth in range(1, len(parts)):
            data_type_id = "/".join(parts[:depth])
            grouped[data_type_id].append(document)

    data_types = [
        _build_data_type(data_type_id, grouped[data_type_id])
        for data_type_id in sorted(grouped)
    ]
    return data_types


def route_rag_query(
    query: str,
    data_types: list[RAGDataType],
    *,
    data_type: str | None = None,
) -> RAGRoutePlan:
    by_id = {item.id: item for item in data_types}
    normalized_data_type = (data_type or "").strip().strip("/")
    if normalized_data_type and normalized_data_type in by_id:
        selected = by_id[normalized_data_type]
        return _plan_from_type(query, selected, reason="显式 data_type 命中")

    query_lower = query.lower()
    scored: list[tuple[int, int, RAGDataType]] = []
    for item in data_types:
        terms = _terms_for_data_type(item)
        score = sum(1 for term in terms if term and term.lower() in query_lower)
        if score > 0:
            scored.append((score, item.id.count("/"), item))

    if scored:
        _, _, selected = sorted(scored, key=lambda entry: (entry[0], entry[1]), reverse=True)[0]
        return _plan_from_type(query, selected, reason="目录关键词命中")

    return RAGRoutePlan(
        query=query,
        data_type=None,
        domain=None,
        category=None,
        path_prefix=None,
        reason="低置信，回退全库混合检索",
    )


def format_data_type_catalog(data_types: list[RAGDataType]) -> str:
    if not data_types:
        return "当前未发现可用数据类型。"

    lines = ["当前可用数据类型："]
    for item in data_types:
        examples = "、".join(item.examples) if item.examples else "无示例"
        lines.append(f"- {item.id}: {item.document_count} 篇；示例：{examples}")
    return "\n".join(lines)


def _load_documents(config: RAGConfig) -> list[KnowledgeDocument]:
    documents: list[KnowledgeDocument] = []
    for raw_dir in config.data_dirs_list:
        root = Path(raw_dir).expanduser()
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.md")):
            if path.is_file():
                documents.append(load_markdown_document(path, root))
    return documents


def _build_data_type(data_type_id: str, documents: list[KnowledgeDocument]) -> RAGDataType:
    domains = sorted({document.domain for document in documents if document.domain})
    domain = domains[0] if len(domains) == 1 else None
    examples = [document.title for document in documents[:3]]
    return RAGDataType(
        id=data_type_id,
        label=data_type_id.replace("_", " / ").replace("/", " / "),
        domain=domain,
        path_prefix=f"{data_type_id}/",
        document_count=len(documents),
        examples=examples,
    )


def _plan_from_type(query: str, selected: RAGDataType, *, reason: str) -> RAGRoutePlan:
    return RAGRoutePlan(
        query=query,
        data_type=selected.id,
        domain=selected.domain,
        category=None,
        path_prefix=selected.path_prefix,
        reason=reason,
    )


def _terms_for_data_type(data_type: RAGDataType) -> set[str]:
    segments = data_type.id.split("/")
    terms = set(segments)
    terms.add(data_type.id)
    terms.update(segment.replace("_", "") for segment in segments)
    for segment in segments:
        terms.update(_ALIASES.get(segment, ()))
    return terms
