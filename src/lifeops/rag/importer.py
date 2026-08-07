from __future__ import annotations

import io
import stat
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import BinaryIO, Any

from lifeops.rag.splitter import split_markdown

MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_EXTRACTED_BYTES = 500 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 2000
ALLOWED_EXTENSIONS = {".md", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"}


def extract_zip_archive(archive: BinaryIO | bytes | Path, destination: Path) -> dict[str, Any]:
    """Safely extract supported knowledge files into a fresh directory."""
    if isinstance(archive, Path):
        if archive.stat().st_size > MAX_ARCHIVE_BYTES:
            raise ValueError("压缩包超过 100MB 限制")
        archive_source: BinaryIO | str = str(archive)
    elif isinstance(archive, bytes):
        if len(archive) > MAX_ARCHIVE_BYTES:
            raise ValueError("压缩包超过 100MB 限制")
        archive_source = io.BytesIO(archive)
    else:
        archive_source = archive

    destination = destination.resolve()
    if destination.exists():
        raise ValueError("解压目标已存在")
    destination.mkdir(parents=True)

    try:
        with zipfile.ZipFile(archive_source) as handle:
            members = handle.infolist()
            if len(members) > MAX_ARCHIVE_ENTRIES:
                raise ValueError("压缩包文件数量超过 2000 条限制")

            extracted_size = 0
            valid_members: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
            seen_paths: set[str] = set()
            for member in members:
                relative = _validate_member(member)
                normalized_key = relative.as_posix().casefold()
                if normalized_key in seen_paths:
                    raise ValueError("压缩包包含重复路径")
                seen_paths.add(normalized_key)
                extracted_size += member.file_size
                if extracted_size > MAX_EXTRACTED_BYTES:
                    raise ValueError("解压后内容超过 500MB 限制")
                if member.is_dir() or relative.suffix.lower() not in ALLOWED_EXTENSIONS:
                    continue
                valid_members.append((member, relative))

            markdown_members = [
                relative for _, relative in valid_members if relative.suffix.lower() == ".md"
            ]
            if not markdown_members:
                raise ValueError("压缩包中没有 Markdown 文件")

            collapse_root = _single_root(valid_members)
            for member, relative in valid_members:
                output_relative = (
                    PurePosixPath(*relative.parts[1:]) if collapse_root else relative
                )
                output_path = (destination / Path(*output_relative.parts)).resolve()
                if not output_path.is_relative_to(destination):
                    raise ValueError("压缩包路径无效")
                output_path.parent.mkdir(parents=True, exist_ok=True)
                if member.is_dir():
                    continue
                with handle.open(member) as source, output_path.open("wb") as target:
                    while chunk := source.read(1024 * 1024):
                        target.write(chunk)

            files = sorted(
                path.relative_to(destination).as_posix()
                for path in destination.rglob("*")
                if path.is_file()
            )
            markdown_files = [path for path in files if Path(path).suffix.lower() == ".md"]
            return {
                "files": files,
                "markdown_files": markdown_files,
                "ignored_files": len(members) - len(valid_members),
                "total_bytes": extracted_size,
            }
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError("无法读取有效 ZIP 压缩包") from exc


def preview_markdown(path: Path, *, strategy: str, chunk_size: int) -> dict[str, Any]:
    chunk_size = _validate_chunk_size(chunk_size)
    overlap = max(1, chunk_size // 6)
    chunks = split_markdown(
        doc_id="preview",
        path=path.name,
        title=path.stem,
        domain="knowledge",
        category=None,
        tags=[],
        content=path.read_text(encoding="utf-8", errors="replace"),
        target_chars=900 if strategy == "heading" else chunk_size,
        overlap_chars=150 if strategy == "heading" else overlap,
        strategy=strategy,
    )
    return {
        "path": path.name,
        "content": path.read_text(encoding="utf-8", errors="replace"),
        "chunks": [
            {
                "heading_breadcrumb": chunk.heading_breadcrumb,
                "content": chunk.content,
            }
            for chunk in chunks
        ],
    }


def _validate_chunk_size(value: int) -> int:
    if value < 150 or value > 900:
        raise ValueError("固定切片大小必须在 150 到 900 之间")
    return value


def _validate_member(member: zipfile.ZipInfo) -> PurePosixPath:
    name = member.filename
    if not name or "\x00" in name or "\\" in name or PureWindowsPath(name).drive:
        raise ValueError("压缩包包含非法路径")
    relative = PurePosixPath(name)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("压缩包包含路径穿越")
    mode = (member.external_attr >> 16) & 0xFFFF
    if stat.S_ISLNK(mode):
        raise ValueError("压缩包不允许包含符号链接")
    if member.flag_bits & 0x1:
        raise ValueError("不支持加密 ZIP")
    return relative


def _single_root(members: list[tuple[zipfile.ZipInfo, PurePosixPath]]) -> bool:
    roots = {relative.parts[0] for _, relative in members if len(relative.parts) > 1}
    has_root_file = any(len(relative.parts) == 1 for _, relative in members)
    return len(roots) == 1 and not has_root_file
