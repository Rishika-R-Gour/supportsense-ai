from __future__ import annotations

from supportsense.retrieval import KnowledgeDocument
from supportsense.vector_store import ChromaVectorStore, LocalHashingEmbedder


class _Embedder:
    def embed_documents(self, texts):
        return [[float(index + 1), 0.0] for index, _ in enumerate(texts)]

    def embed_query(self, text):
        return [1.0, 0.0]


class _Collection:
    def __init__(self) -> None:
        self.upserts = []
        self.queries = []

    def upsert(self, **kwargs) -> None:
        self.upserts.append(kwargs)

    def query(self, **kwargs):
        self.queries.append(kwargs)
        return {
            "metadatas": [[
                {"document_id": "KB-2"},
                {"document_id": "KB-1"},
            ]],
            "distances": [[0.1, 0.7]],
        }


class _Client:
    def __init__(self) -> None:
        self.collections = {}
        self.heartbeats = 0
        self.collection_calls = []

    def get_or_create_collection(self, name, metadata, embedding_function):
        self.collection_calls.append(
            {
                "name": name,
                "metadata": metadata,
                "embedding_function": embedding_function,
            }
        )
        self.collections.setdefault(name, _Collection())
        return self.collections[name]

    def heartbeat(self):
        self.heartbeats += 1
        return 1


DOCUMENTS = [
    KnowledgeDocument(
        "KB-1",
        "Authentication",
        "Use bearer authentication.",
        {"topic": "api_auth"},
    ),
    KnowledgeDocument(
        "KB-2",
        "Key rotation",
        "Rotate exposed API keys immediately.",
        {"topic": "api_auth"},
    ),
]


def test_chroma_store_indexes_and_queries_a_tenant_namespace() -> None:
    client = _Client()
    store = ChromaVectorStore(client, _Embedder())

    assert store.index_documents("tenant-a", "knowledge", DOCUMENTS)
    scores = store.search(
        "tenant-a",
        "knowledge",
        "How do I rotate an API key?",
        DOCUMENTS,
        5,
    )

    assert scores["KB-2"] > scores["KB-1"]
    assert len(client.collections) == 1
    assert client.collection_calls[0]["embedding_function"] is None
    collection = next(iter(client.collections.values()))
    assert collection.upserts[0]["metadatas"][0]["namespace"] == "knowledge"
    assert collection.queries[0]["where"]["$and"][0] == {
        "namespace": "knowledge"
    }
    assert collection.queries[0]["where"]["$and"][1]["document_id"]["$in"] == [
        "KB-1",
        "KB-2",
    ]
    assert store.ready()


def test_chroma_store_uses_separate_collections_per_tenant() -> None:
    client = _Client()
    store = ChromaVectorStore(client, _Embedder())

    store.index_documents("tenant-a", "knowledge", DOCUMENTS)
    store.index_documents("tenant-b", "knowledge", DOCUMENTS)

    assert len(client.collections) == 2


def test_local_embeddings_are_fixed_dimension_and_normalized() -> None:
    embedder = LocalHashingEmbedder(dimensions=64)

    documents = embedder.embed_documents(["billing invoice", "API authentication"])
    query = embedder.embed_query("invoice")

    assert len(documents) == 2
    assert len(documents[0]) == len(query) == 64
    assert abs(sum(value * value for value in query) - 1) < 1e-9


def test_vector_store_redacts_sensitive_document_text_before_upsert() -> None:
    client = _Client()
    store = ChromaVectorStore(client, _Embedder())
    documents = [
        KnowledgeDocument(
            "KB-SENSITIVE",
            "Customer card",
            "Card 4242 4242 4242 4242 belongs to owner@example.com.",
        )
    ]

    assert store.index_documents("tenant-a", "knowledge", documents)

    stored = next(iter(client.collections.values())).upserts[0]["documents"][0]
    assert "4242 4242 4242 4242" not in stored
    assert "owner@example.com" not in stored
