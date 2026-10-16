"""导出已有向量并迁入空 Chroma 服务，不重新计算 embedding。"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import struct
from pathlib import Path

import chromadb


def _records(collection):
    for offset in range(0, collection.count(), 256):
        batch = collection.get(
            limit=256, offset=offset, include=["embeddings", "documents", "metadatas", "uris"]
        )
        for index, record_id in enumerate(batch["ids"]):
            yield {
                "id": record_id,
                "embedding": batch["embeddings"][index].tolist(),
                "document": batch["documents"][index],
                "metadata": batch["metadatas"][index],
                "uri": batch["uris"][index],
            }


def _record_hash(record):
    digest = hashlib.sha256()
    digest.update(json.dumps(
        {key: value for key, value in record.items() if key != "embedding"},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode())
    vector = record["embedding"]
    digest.update(struct.pack(f"<{len(vector)}f", *vector))
    return digest.hexdigest()


def _fingerprint(records):
    rows = sorted((record["id"], _record_hash(record)) for record in records)
    return {
        "count": len(rows),
        "sha256": hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest(),
    }


def collection_fingerprint(collection):
    """比较 ID、文档、元数据、URI 和每个 float32 向量值。"""
    return _fingerprint(_records(collection))


def export_collection(collection, path: Path):
    header = {
        "schema_version": 1,
        "name": collection.name,
        "metadata": collection.metadata,
        # embedding 由应用生成；只复制服务的索引参数，避免触发默认模型下载。
        "configuration": {
            key: value for key, value in collection.configuration.items()
            if key in {"hnsw", "spann"} and value is not None
        },
    }
    records = list(_records(collection))
    header.update(_fingerprint(records))
    with gzip.open(path, "xt", encoding="utf-8") as output:
        output.write(json.dumps(header, ensure_ascii=False) + "\n")
        for record in records:
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
    return header


def restore_collection(client, path: Path, *, name: str | None = None):
    with gzip.open(path, "rt", encoding="utf-8") as source:
        header = json.loads(next(source))
        records = [json.loads(line) for line in source]
    if header["schema_version"] != 1 or _fingerprint(records) != {
        key: header[key] for key in ["count", "sha256"]
    }:
        raise ValueError("Chroma 导出文件内容校验失败")
    collection = client.create_collection(
        name or header["name"], metadata=header["metadata"],
        configuration=header["configuration"], embedding_function=None,
    )
    batch_size = min(256, client.get_max_batch_size())
    for offset in range(0, len(records), batch_size):
        # 可选字段为 None 时逐条省略，保留原数据的 NULL 语义。
        batch = records[offset : offset + batch_size]
        for fields in range(8):
            group = [record for record in batch if sum(
                (1 << bit) for bit, key in enumerate(["document", "metadata", "uri"])
                if record[key] is not None
            ) == fields]
            if not group:
                continue
            optional = {
                plural: [record[singular] for record in group]
                for bit, (singular, plural) in enumerate([
                    ("document", "documents"), ("metadata", "metadatas"), ("uri", "uris")
                ]) if fields & (1 << bit)
            }
            collection.add(
                ids=[record["id"] for record in group],
                embeddings=[record["embedding"] for record in group], **optional,
            )
    actual = collection_fingerprint(collection)
    if actual != {key: header[key] for key in ["count", "sha256"]}:
        raise ValueError(f"Chroma 迁移后数据不一致：{collection.name}")
    if collection.metadata != header["metadata"]:
        raise ValueError(f"Chroma 迁移后集合元数据不一致：{collection.name}")
    if any(collection.configuration[key] != value
           for key, value in header["configuration"].items()):
        raise ValueError(f"Chroma 迁移后索引参数不一致：{collection.name}")
    return {"name": collection.name, **actual, "verified": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--source", type=Path, help="已停止写入的旧 Chroma 目录")
    mode.add_argument("--restore", type=Path, help="已有导出备份目录")
    parser.add_argument("--backup-dir", type=Path, help="新建导出备份目录")
    parser.add_argument("--host", default="chroma")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    os.umask(0o077)
    target = chromadb.HttpClient(host=args.host, port=args.port)
    if target.list_collections():
        parser.error("目标 Chroma 必须为空，拒绝覆盖已有集合")
    if args.source:
        if not args.backup_dir or not (args.source / "chroma.sqlite3").is_file():
            parser.error("需要有效旧 Chroma 目录和 --backup-dir")
        args.backup_dir.mkdir(parents=True, exist_ok=False)
        source = chromadb.PersistentClient(path=str(args.source))
        files = []
        for index, collection in enumerate(source.list_collections()):
            path = args.backup_dir / f"collection-{index:03d}.jsonl.gz"
            export_collection(source.get_collection(collection.name, embedding_function=None), path)
            files.append(path)
        backup_dir = args.backup_dir
    else:
        backup_dir = args.restore
        files = sorted(backup_dir.glob("collection-*.jsonl.gz"))
    if not files:
        parser.error("未找到可迁移的 Chroma 集合")
    report = [restore_collection(target, path) for path in files]
    (backup_dir / "migration-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
