from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from lifeops.rag.types import KnowledgeDocument


_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def parse_frontmatter(markdown: str) -> tuple[dict[str, Any], str]:
    match = _FRONTMATTER_RE.match(markdown)
    if not match:
        return {}, markdown

    raw = match.group(1)
    body = markdown[match.end() :]
    metadata: dict[str, Any] = {}
    try:
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if ":" not in stripped:
                raise ValueError("invalid frontmatter line")
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                raise ValueError("empty frontmatter key")
            metadata[key] = _parse_scalar_or_list(value)
    except ValueError:
        return {}, body

    return metadata, body


def load_markdown_document(path: Path, root: Path) -> KnowledgeDocument:
    content = path.read_text(encoding="utf-8", errors="replace")
    metadata, body = parse_frontmatter(content)
    relative_path = path.relative_to(root).as_posix()
    title = str(metadata.get("title") or path.stem)
    parts = Path(relative_path).parts
    domain = str(metadata.get("domain") or (parts[0] if len(parts) > 1 else "knowledge"))
    tags = metadata.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]

    return KnowledgeDocument(
        doc_id=hashlib.sha1(relative_path.encode("utf-8")).hexdigest(),
        path=relative_path,
        title=title,
        domain=domain,
        category=_optional_str(metadata.get("category")),
        tags=[str(tag) for tag in tags],
        source=_optional_str(metadata.get("source")),
        updated_at=_optional_str(metadata.get("updated_at")),
        content=body,
        content_hash=hashlib.sha1(body.strip().encode("utf-8")).hexdigest(),
    )


def load_markdown_documents(data_dirs: list[Path]) -> list[KnowledgeDocument]:
    documents: list[KnowledgeDocument] = []
    for root in data_dirs:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.md")):
            if path.is_file():
                documents.append(load_markdown_document(path, root))
    return documents


def _optional_str(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _parse_scalar_or_list(value: str) -> Any:
    if value.startswith("["):
        if not value.endswith("]"):
            raise ValueError("invalid list value")
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_strip_quotes(item.strip()) for item in inner.split(",")]
    if value.startswith(("'", '"')):
        return _strip_quotes(value)
    return value


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
