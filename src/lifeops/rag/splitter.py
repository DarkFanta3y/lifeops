from __future__ import annotations

import hashlib
import re

from lifeops.rag.types import KnowledgeChunk


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def split_markdown(
    *,
    doc_id: str,
    path: str,
    title: str,
    domain: str,
    category: str | None,
    tags: list[str],
    content: str,
    parent_content_hash: str | None = None,
    target_chars: int = 900,
    overlap_chars: int = 150,
) -> list[KnowledgeChunk]:
    sections = _split_sections(content, title)
    chunks: list[KnowledgeChunk] = []
    parent_hash = parent_content_hash or hashlib.sha1(content.strip().encode("utf-8")).hexdigest()

    for breadcrumb, section_text in sections:
        for part in _split_long_section(section_text, target_chars, overlap_chars):
            if not part.strip():
                continue
            chunk_id = f"{doc_id}:{len(chunks)}"
            chunks.append(
                KnowledgeChunk(
                    doc_id=doc_id,
                    chunk_id=chunk_id,
                    path=path,
                    title=title,
                    domain=domain,
                    category=category,
                    tags=list(tags),
                    heading_breadcrumb=breadcrumb,
                    content=part.strip(),
                    content_hash=hashlib.sha1(part.strip().encode("utf-8")).hexdigest(),
                    parent_id=doc_id,
                    parent_path=path,
                    parent_title=title,
                    parent_content_hash=parent_hash,
                )
            )

    if not chunks and content.strip():
        chunks.append(
            KnowledgeChunk(
                doc_id=doc_id,
                chunk_id=f"{doc_id}:0",
                path=path,
                title=title,
                domain=domain,
                category=category,
                tags=list(tags),
                heading_breadcrumb=title,
                content=content.strip(),
                content_hash=hashlib.sha1(content.strip().encode("utf-8")).hexdigest(),
                parent_id=doc_id,
                parent_path=path,
                parent_title=title,
                parent_content_hash=parent_hash,
            )
        )
    return chunks


def _split_sections(content: str, fallback_title: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    heading_stack: list[tuple[int, str]] = []
    current_lines: list[str] = []
    current_breadcrumb = fallback_title

    for line in content.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            if current_lines:
                sections.append((current_breadcrumb, "\n".join(current_lines).strip()))
                current_lines = []
            level = len(match.group(1))
            heading = match.group(2).strip()
            heading_stack = [
                (heading_level, heading_text)
                for heading_level, heading_text in heading_stack
                if heading_level < level
            ]
            heading_stack.append((level, heading))
            current_breadcrumb = " > ".join(h for _, h in heading_stack) or fallback_title
            current_lines.append(line)
            continue
        current_lines.append(line)

    if current_lines:
        sections.append((current_breadcrumb, "\n".join(current_lines).strip()))
    return sections


def _split_long_section(text: str, target_chars: int, overlap_chars: int) -> list[str]:
    if len(text) <= target_chars:
        return [text]

    paragraphs = [part for part in re.split(r"\n\s*\n", text) if part.strip()]
    parts: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= target_chars:
            current = candidate
            continue
        if current:
            parts.append(current)
            current = _overlap_suffix(current, overlap_chars)
        if len(paragraph) > target_chars:
            parts.extend(_split_by_chars(paragraph, target_chars, overlap_chars))
            current = ""
        else:
            current = f"{current}\n\n{paragraph}".strip() if current else paragraph
    if current:
        parts.append(current)
    return parts


def _split_by_chars(text: str, target_chars: int, overlap_chars: int) -> list[str]:
    result: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + target_chars)
        result.append(text[start:end])
        if end == len(text):
            break
        start = max(end - overlap_chars, start + 1)
    return result


def _overlap_suffix(text: str, overlap_chars: int) -> str:
    if overlap_chars <= 0 or len(text) <= overlap_chars:
        return ""
    return text[-overlap_chars:]
