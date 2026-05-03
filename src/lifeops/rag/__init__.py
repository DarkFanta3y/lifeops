__all__ = ["RAGIndexer", "RAGRetriever"]


def __getattr__(name: str):
    if name == "RAGIndexer":
        from lifeops.rag.indexer import RAGIndexer

        return RAGIndexer
    if name == "RAGRetriever":
        from lifeops.rag.retriever import RAGRetriever

        return RAGRetriever
    raise AttributeError(name)
