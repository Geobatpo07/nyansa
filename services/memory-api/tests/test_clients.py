"""The adapters are tested against a stubbed transport: no Ollama or Qdrant runs."""

import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest

from src.clients import OllamaEmbedder, QdrantStore
from src.domain import IndexedNote, SearchHit, UpstreamError

type Reply = tuple[int, object]


class Stub:
    """Records every request and answers with the replies given in order."""

    def __init__(self) -> None:
        self.replies: list[Reply] = []
        self.requests: list[httpx.Request] = []
        self.client = httpx.AsyncClient(transport=httpx.MockTransport(self._handle))

    def reply(self, *replies: Reply) -> Stub:
        self.replies += replies
        return self

    def bodies(self) -> list[Any]:
        return [json.loads(r.content) if r.content else None for r in self.requests]

    def calls(self) -> list[str]:
        return [f"{r.method} {r.url}" for r in self.requests]

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status, body = self.replies.pop(0) if self.replies else (200, {})
        return httpx.Response(status, json=body)


@pytest.fixture
async def stub() -> AsyncIterator[Stub]:
    stub = Stub()
    async with stub.client:
        yield stub


class TestOllamaEmbedder:
    async def test_batches_documents_and_adds_the_document_prefix(self, stub: Stub) -> None:
        stub.reply((200, {"embeddings": [[1], [2]]}), (200, {"embeddings": [[3]]}))
        embedder = OllamaEmbedder(stub.client, "http://ollama:11434/", "nomic-embed-text", batch_size=2)

        assert await embedder.embed_documents(["a", "b", "c"]) == [[1], [2], [3]]
        assert stub.calls() == ["POST http://ollama:11434/api/embed"] * 2
        assert stub.bodies()[0] == {
            "model": "nomic-embed-text",
            "input": ["search_document: a", "search_document: b"],
            "truncate": True,
        }

    async def test_adds_the_query_prefix_to_questions(self, stub: Stub) -> None:
        stub.reply((200, {"embeddings": [[0.5]]}))
        assert await OllamaEmbedder(stub.client, "http://ollama:11434", "m").embed_query("why?") == [0.5]
        assert stub.bodies()[0]["input"] == ["search_query: why?"]

    async def test_turns_http_errors_and_malformed_answers_into_upstream_error(self, stub: Stub) -> None:
        embedder = OllamaEmbedder(stub.client, "http://ollama:11434", "m")
        stub.reply((404, {"error": "model not found"}))
        with pytest.raises(UpstreamError) as raised:
            await embedder.embed_documents(["x"])
        assert (raised.value.service, raised.value.status) == ("ollama", 404)

        stub.reply((200, {"embeddings": []}))
        with pytest.raises(UpstreamError, match="expected 1 embeddings, received 0"):
            await embedder.embed_documents(["x"])

    async def test_reports_an_unreachable_service(self) -> None:
        def refuse(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(refuse)) as client:
            with pytest.raises(UpstreamError, match="ollama: request to /api/version failed: connection refused"):
                await OllamaEmbedder(client, "http://ollama:11434", "m").health()


class TestQdrantStore:
    @pytest.fixture
    def store_for(self, stub: Stub) -> Callable[..., QdrantStore]:
        return lambda *replies: QdrantStore(stub.reply(*replies).client, "http://qdrant:6333", "secret", "notes")

    async def test_creates_a_missing_collection_with_its_payload_indexes(
        self, stub: Stub, store_for: Callable[..., QdrantStore]
    ) -> None:
        await store_for((200, {"result": {"exists": False}})).ensure_collection(768)

        index = "PUT http://qdrant:6333/collections/notes/index?wait=true"
        assert stub.calls() == [
            "GET http://qdrant:6333/collections/notes/exists",
            "PUT http://qdrant:6333/collections/notes",
            index,
            index,
            index,
        ]
        assert stub.bodies()[1:] == [
            {"vectors": {"size": 768, "distance": "Cosine"}},
            {"field_name": "path", "field_schema": "keyword"},
            {"field_name": "tags", "field_schema": "keyword"},
            {"field_name": "chunk_index", "field_schema": "integer"},
        ]
        assert all(r.headers["api-key"] == "secret" for r in stub.requests)

    async def test_refuses_an_existing_collection_with_another_vector_size(
        self, store_for: Callable[..., QdrantStore]
    ) -> None:
        store = store_for(
            (200, {"result": {"exists": True}}), (200, {"result": {"config": {"params": {"vectors": {"size": 384}}}}})
        )
        with pytest.raises(UpstreamError, match=r"size 384.*produces 768"):
            await store.ensure_collection(768)

    async def test_pages_through_the_first_chunks_to_list_indexed_notes(
        self, stub: Stub, store_for: Callable[..., QdrantStore]
    ) -> None:
        store = store_for(
            (200, {"result": {"points": [{"payload": {"path": "a.md", "note_hash": "h1", "index_version": "v"}}],
                              "next_page_offset": "next-id"}}),
            (200, {"result": {"points": [{"payload": {"path": "b.md", "note_hash": "h2", "index_version": "v"}}],
                              "next_page_offset": None}}),
        )  # fmt: skip

        assert await store.list_indexed_notes() == [IndexedNote("a.md", "h1", "v"), IndexedNote("b.md", "h2", "v")]
        first, second = stub.bodies()
        assert first["filter"] == {"must": [{"key": "chunk_index", "match": {"value": 0}}]}
        assert first["with_vector"] is False
        assert second["offset"] == "next-id"

    async def test_deletes_a_whole_note_or_only_its_tail_chunks(
        self, stub: Stub, store_for: Callable[..., QdrantStore]
    ) -> None:
        store = store_for()
        await store.delete_note("a.md")
        await store.delete_note("a.md", 3)

        path = {"key": "path", "match": {"value": "a.md"}}
        assert stub.bodies() == [
            {"filter": {"must": [path]}},
            {"filter": {"must": [path, {"key": "chunk_index", "range": {"gte": 3}}]}},
        ]

    async def test_searches_with_tag_filter_and_score_threshold(
        self, stub: Stub, store_for: Callable[..., QdrantStore]
    ) -> None:
        payload = {"path": "a.md", "title": "A"}
        store = store_for((200, {"result": {"points": [{"score": 0.9, "payload": payload}]}}))

        assert await store.search([0.1, 0.2], 3, tags=["ai"], min_score=0.5) == [SearchHit(0.9, payload)]  # type: ignore[arg-type]
        assert stub.calls() == ["POST http://qdrant:6333/collections/notes/points/query"]
        assert stub.bodies() == [
            {
                "query": [0.1, 0.2],
                "limit": 3,
                "with_payload": True,
                "score_threshold": 0.5,
                "filter": {"must": [{"key": "tags", "match": {"any": ["ai"]}}]},
            }
        ]

    async def test_returns_no_result_before_the_first_ingestion(self, store_for: Callable[..., QdrantStore]) -> None:
        assert await store_for((404, {"status": {"error": "Not found"}})).search([1], 5) == []

    async def test_surfaces_authentication_failures(self, store_for: Callable[..., QdrantStore]) -> None:
        with pytest.raises(UpstreamError):
            await store_for((401, "Invalid API key")).health()
