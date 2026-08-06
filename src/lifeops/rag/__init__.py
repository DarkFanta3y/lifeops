__all__ = ["RAGIndexer", "RAGRetriever", "RAGRouter", "RecipeRetriever"]


def __getattr__(name: str):
    if name == "RAGIndexer":
        from lifeops.rag.indexer import RAGIndexer

        return RAGIndexer
    if name == "RAGRetriever":
        from lifeops.rag.retriever import RAGRetriever

        return RAGRetriever
    if name in {"RAGRouter", "RecipeRetriever"}:
        from lifeops.rag.router import RAGRouter, RecipeRetriever

        return {"RAGRouter": RAGRouter, "RecipeRetriever": RecipeRetriever}[name]
    raise AttributeError(name)
