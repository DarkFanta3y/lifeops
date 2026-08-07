__all__ = [
    "RAGIndexer",
    "RAGRetriever",
    "RAGRouter",
    "RecipeRetriever",
    "DirectoryRetriever",
    "build_default_rag_router",
]


def __getattr__(name: str):
    if name == "RAGIndexer":
        from lifeops.rag.indexer import RAGIndexer

        return RAGIndexer
    if name == "RAGRetriever":
        from lifeops.rag.retriever import RAGRetriever

        return RAGRetriever
    if name in {"RAGRouter", "RecipeRetriever", "DirectoryRetriever", "build_default_rag_router"}:
        from lifeops.rag.router import (
            DirectoryRetriever,
            RAGRouter,
            RecipeRetriever,
            build_default_rag_router,
        )

        return {
            "RAGRouter": RAGRouter,
            "RecipeRetriever": RecipeRetriever,
            "DirectoryRetriever": DirectoryRetriever,
            "build_default_rag_router": build_default_rag_router,
        }[name]
    raise AttributeError(name)
