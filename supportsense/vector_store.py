from __future__ import annotations

import hashlib
import logging
import math
from collections.abc import Callable, Sequence
from typing import Any, Protocol
from urllib.parse import urlparse

import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer

from supportsense.config import settings
from supportsense.guardrails import redact_pii
from supportsense.observability import VECTOR_STORE_OPERATIONS
from supportsense.retrieval import KnowledgeDocument

LOGGER = logging.getLogger("supportsense.vector_store")


class Embedder(Protocol):
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class LocalHashingEmbedder:
    """Stateless local vector fallback with fixed dimensions and no model download."""

    def __init__(self, dimensions: int = 384) -> None:
        self.vectorizer = HashingVectorizer(
            n_features=dimensions,
            alternate_sign=False,
            norm="l2",
            stop_words="english",
            ngram_range=(1, 2),
        )

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self.vectorizer.transform(texts).toarray().astype(float).tolist()

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


class GeminiEmbedder:
    def __init__(self, api_key: str, model: str) -> None:
        from google import genai

        self.client = genai.Client(api_key=api_key)
        self.model = model

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        from google.genai import types

        vectors: list[list[float]] = []
        for start in range(0, len(texts), 100):
            response = self.client.models.embed_content(
                model=self.model,
                contents=list(texts[start : start + 100]),
                config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
            )
            vectors.extend(
                _normalize(list(embedding.values))
                for embedding in response.embeddings
            )
        return vectors

    def embed_query(self, text: str) -> list[float]:
        from google.genai import types

        response = self.client.models.embed_content(
            model=self.model,
            contents=[text],
            config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY"),
        )
        return _normalize(list(response.embeddings[0].values))


class OpenAIEmbedder:
    def __init__(self, api_key: str, model: str) -> None:
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key)
        self.model = model

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        response = self.client.embeddings.create(
            model=self.model,
            input=list(texts),
        )
        return [_normalize(list(item.embedding)) for item in response.data]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


class NullVectorStore:
    enabled = False

    def index_documents(
        self,
        tenant_id: str,
        namespace: str,
        documents: Sequence[KnowledgeDocument],
    ) -> bool:
        return False

    def search(
        self,
        tenant_id: str,
        namespace: str,
        query: str,
        documents: Sequence[KnowledgeDocument],
        limit: int,
    ) -> dict[str, float]:
        return {}

    def ready(self) -> bool:
        return True


class ChromaVectorStore:
    enabled = True

    def __init__(
        self,
        client: Any | None,
        embedder: Embedder,
        *,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._client = client
        self._client_factory = client_factory
        self.embedder = embedder

    def index_documents(
        self,
        tenant_id: str,
        namespace: str,
        documents: Sequence[KnowledgeDocument],
    ) -> bool:
        if not documents:
            return True
        try:
            collection = self._collection(tenant_id)
            for start in range(0, len(documents), 100):
                batch = list(documents[start : start + 100])
                texts = [
                    redact_pii(f"{item.title}\n{item.content}")
                    for item in batch
                ]
                collection.upsert(
                    ids=[
                        _storage_id(namespace, document.document_id)
                        for document in batch
                    ],
                    embeddings=self.embedder.embed_documents(texts),
                    documents=texts,
                    metadatas=[
                        _metadata(namespace, document)
                        for document in batch
                    ],
                )
            VECTOR_STORE_OPERATIONS.labels("index", "success").inc()
            return True
        except Exception:
            VECTOR_STORE_OPERATIONS.labels("index", "error").inc()
            LOGGER.exception(
                "Vector indexing failed; PostgreSQL retrieval remains available"
            )
            return False

    def search(
        self,
        tenant_id: str,
        namespace: str,
        query: str,
        documents: Sequence[KnowledgeDocument],
        limit: int,
    ) -> dict[str, float]:
        if not documents:
            return {}
        allowed = list(dict.fromkeys(document.document_id for document in documents))
        try:
            results = self._collection(tenant_id).query(
                query_embeddings=[self.embedder.embed_query(query)],
                n_results=min(max(1, limit), len(allowed)),
                where={
                    "$and": [
                        {"namespace": namespace},
                        {"document_id": {"$in": allowed}},
                    ]
                },
                include=["metadatas", "distances"],
            )
            metadatas = (results.get("metadatas") or [[]])[0]
            distances = (results.get("distances") or [[]])[0]
            scores: dict[str, float] = {}
            for metadata, distance in zip(metadatas, distances, strict=False):
                if not metadata or not metadata.get("document_id"):
                    continue
                document_id = str(metadata["document_id"])
                score = 1 / (1 + max(0, float(distance)))
                scores[document_id] = max(scores.get(document_id, 0), score)
            VECTOR_STORE_OPERATIONS.labels("search", "success").inc()
            return scores
        except Exception:
            VECTOR_STORE_OPERATIONS.labels("search", "error").inc()
            LOGGER.exception(
                "Vector search failed; falling back to in-process semantic scoring"
            )
            return {}

    def ready(self) -> bool:
        try:
            self._client_instance().heartbeat()
            return True
        except Exception:
            return False

    def _collection(self, tenant_id: str):
        tenant_hash = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:24]
        return self._client_instance().get_or_create_collection(
            name=f"supportsense-{tenant_hash}",
            metadata={"tenant_hash": tenant_hash},
            # SupportSense always supplies embeddings. Explicitly disabling the
            # Chroma embedding function also prevents a poisoned collection
            # configuration from loading executable model code in this client.
            embedding_function=None,
        )

    def _client_instance(self):
        if self._client is None:
            if self._client_factory is None:
                raise RuntimeError("Chroma client is not configured")
            self._client = self._client_factory()
        return self._client


def build_embedder() -> Embedder:
    if settings.embedding_provider == "gemini":
        return GeminiEmbedder(
            settings.gemini_api_key or "",
            settings.gemini_embedding_model,
        )
    if settings.embedding_provider == "openai":
        return OpenAIEmbedder(
            settings.openai_api_key or "",
            settings.openai_embedding_model,
        )
    return LocalHashingEmbedder()


def build_vector_store() -> NullVectorStore | ChromaVectorStore:
    if not settings.chroma_url:
        return NullVectorStore()
    parsed = urlparse(settings.chroma_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RuntimeError("CHROMA_URL must be an HTTP or HTTPS URL")

    def client_factory():
        import chromadb

        return chromadb.HttpClient(
            host=parsed.hostname,
            port=parsed.port or (443 if parsed.scheme == "https" else 8000),
            ssl=parsed.scheme == "https",
        )

    return ChromaVectorStore(
        None,
        build_embedder(),
        client_factory=client_factory,
    )


def _storage_id(namespace: str, document_id: str) -> str:
    return hashlib.sha256(
        f"{namespace}\0{document_id}".encode("utf-8")
    ).hexdigest()


def _metadata(namespace: str, document: KnowledgeDocument) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "namespace": namespace,
        "document_id": document.document_id,
        "title": redact_pii(document.title[:500]),
    }
    metadata.update(
        {
            key: value
            for key, value in document.metadata.items()
            if isinstance(value, (str, int, float, bool))
            and not (isinstance(value, float) and math.isnan(value))
        }
    )
    return {
        key: redact_pii(value) if isinstance(value, str) else value
        for key, value in metadata.items()
    }


def _normalize(vector: list[float]) -> list[float]:
    values = np.asarray(vector, dtype=float)
    norm = float(np.linalg.norm(values))
    return (values / norm).tolist() if norm else values.tolist()


vector_store = build_vector_store()
