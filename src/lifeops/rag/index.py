from __future__ import annotations

import argparse

from lifeops.core.config import AppConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="重建 LifeOps 本地 RAG 索引")
    parser.add_argument("--rebuild", action="store_true", help="全量重建索引")
    args = parser.parse_args()
    if not args.rebuild:
        parser.error("当前仅支持 --rebuild")

    from lifeops.rag.indexer import RAGIndexer

    config = AppConfig()
    summary = RAGIndexer(config.rag).rebuild()
    print(f"RAG 索引重建完成：{summary['documents']} 篇文档，{summary['chunks']} 个分块")


if __name__ == "__main__":
    main()
