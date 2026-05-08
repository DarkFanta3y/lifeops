from __future__ import annotations

from pathlib import Path
from typing import Protocol


class EmbeddingProvider(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class SentenceTransformerEmbeddingProvider:
    _model_cache = {}

    def __init__(self, model_name: str, cache_folder: str | None = None):
        self.model_name = resolve_sentence_transformer_model(model_name, cache_folder)
        self.cache_folder = cache_folder
        self._model = self._model_cache.get((self.model_name, self.cache_folder))

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name, cache_folder=self.cache_folder)
            self._model_cache[(self.model_name, self.cache_folder)] = self._model
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts, normalize_embeddings=True).tolist()

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def resolve_sentence_transformer_model(model_name: str, cache_folder: str | None) -> str:
    if not cache_folder:
        return model_name

    local_path = Path(cache_folder).expanduser() / _local_model_path(model_name)
    if local_path.exists():
        return str(local_path)
    return model_name


def _local_model_path(model_name: str) -> Path:
    return Path(*[part.replace(".", "___") for part in model_name.split("/")])
