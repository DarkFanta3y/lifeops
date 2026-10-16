"""统一选择 Chroma 服务；未配置服务时保留本地开发兼容。"""

from lifeops.core.config import RAGConfig


def create_chroma_client(config: RAGConfig):
    import chromadb

    if config.chroma_host.strip():
        return chromadb.HttpClient(host=config.chroma_host, port=config.chroma_port)
    return chromadb.PersistentClient(path=config.chroma_path)
