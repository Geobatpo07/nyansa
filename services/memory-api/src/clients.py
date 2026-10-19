"""Ollama and Qdrant adapters over a shared httpx client."""

from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from domain import ChunkPoint, IndexedNote, SearchHit, Service, UpstreamError

# Fields of the payload indexed by Qdrant for filtering.
_PAYLOAD_INDEXES = {"path": "keyword", "tags": "keyword", "chunk_index": "integer"}


async def request_json(
    client: httpx.AsyncClient,
    service: Service,
    method: str,
    url: str,
    timeout_s: float,
    body: object = None,
    headers: dict[str, str] | None = None,
) -> Any:
    """Sends a JSON request and returns the parsed JSON response; any failure becomes an UpstreamError."""
    path = urlsplit(url).path
    try:
        response = await client.request(method, url, json=body, headers=headers, timeout=timeout_s)
    except httpx.HTTPError as err:
        raise UpstreamError(service, f"request to {path} failed: {str(err) or type(err).__name__}") from err
    if response.is_error:
        raise UpstreamError(
            service, f"HTTP {response.status_code} on {path}: {response.text[:300]}", response.status_code
        )
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError as err:
        raise UpstreamError(service, f"invalid JSON from {path}", response.status_code) from err


class OllamaEmbedder:
    def __init__(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        model: str,
        batch_size: int = 32,
        timeout: float = 120,
        # nomic-embed-text is trained with these task prefixes; other models may need none.
        document_prefix: str = "search_document: ",
        query_prefix: str = "search_query: ",
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self.model = model
        self._batch_size = batch_size
        self._timeout = timeout
        self._document_prefix = document_prefix
        self._query_prefix = query_prefix

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            vectors += await self._embed([self._document_prefix + text for text in batch])
        return vectors

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed([self._query_prefix + text]))[0]

    async def health(self) -> None:
        await request_json(self._client, "ollama", "GET", f"{self._base_url}/api/version", timeout_s=5)

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        body = await request_json(
            self._client,
            "ollama",
            "POST",
            f"{self._base_url}/api/embed",
            timeout_s=self._timeout,
            # truncate: inputs longer than the model context are cut instead of failing.
            body={"model": self.model, "input": texts, "truncate": True},
        )
        embeddings = body.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            received = len(embeddings) if isinstance(embeddings, list) else "none"
            raise UpstreamError("ollama", f"expected {len(texts)} embeddings, received {received}")
        return embeddings


class QdrantStore:
    def __init__(
        self, client: httpx.AsyncClient, base_url: str, api_key: str, collection: str, timeout: float = 30
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._collection = collection
        self._collection_url = f"{self._base_url}/collections/{quote(collection, safe='')}"
        self._headers = {"api-key": api_key}
        self._timeout = timeout

    async def ensure_collection(self, dimensions: int) -> None:
        if (await self._call("GET", f"{self._collection_url}/exists"))["result"]["exists"]:
            info = await self._call("GET", self._collection_url)
            size = info["result"]["config"]["params"]["vectors"].get("size")
            if size != dimensions:
                raise UpstreamError(
                    "qdrant",
                    f"collection {self._collection} has vectors of size {size}, the embedding model produces "
                    f"{dimensions}; delete the collection or set another QDRANT_COLLECTION",
                )
            return
        await self._call("PUT", self._collection_url, {"vectors": {"size": dimensions, "distance": "Cosine"}})
        for name, schema in _PAYLOAD_INDEXES.items():
            await self._call(
                "PUT", f"{self._collection_url}/index?wait=true", {"field_name": name, "field_schema": schema}
            )

    async def list_indexed_notes(self) -> list[IndexedNote]:
        notes: list[IndexedNote] = []
        offset: object = None
        while True:
            body: dict[str, object] = {
                # The first chunk of each note carries what incremental indexing needs.
                "filter": {"must": [{"key": "chunk_index", "match": {"value": 0}}]},
                "with_payload": ["path", "note_hash", "index_version"],
                "with_vector": False,
                "limit": 256,
            }
            if offset is not None:
                body["offset"] = offset
            result = (await self._call("POST", f"{self._collection_url}/points/scroll", body))["result"]
            for point in result["points"]:
                payload = point.get("payload") or {}
                if all(key in payload for key in ("path", "note_hash", "index_version")):
                    notes.append(IndexedNote(payload["path"], payload["note_hash"], payload["index_version"]))
            offset = result.get("next_page_offset")
            if offset is None:
                return notes

    async def upsert_chunks(self, points: list[ChunkPoint]) -> None:
        if points:
            body = {"points": [{"id": p.id, "vector": p.vector, "payload": p.payload} for p in points]}
            await self._call("PUT", f"{self._collection_url}/points?wait=true", body)

    async def delete_note(self, path: str, from_chunk_index: int = 0) -> None:
        must: list[object] = [{"key": "path", "match": {"value": path}}]
        if from_chunk_index > 0:
            must.append({"key": "chunk_index", "range": {"gte": from_chunk_index}})
        await self._call("POST", f"{self._collection_url}/points/delete?wait=true", {"filter": {"must": must}})

    async def search(
        self, vector: list[float], limit: int, tags: list[str] | None = None, min_score: float | None = None
    ) -> list[SearchHit]:
        body: dict[str, object] = {"query": vector, "limit": limit, "with_payload": True}
        if min_score is not None:
            body["score_threshold"] = min_score
        if tags:
            body["filter"] = {"must": [{"key": "tags", "match": {"any": tags}}]}
        try:
            result = (await self._call("POST", f"{self._collection_url}/points/query", body))["result"]
        except UpstreamError as err:
            # Nothing ingested yet: no collection means no result, not an error.
            if err.status == 404:
                return []
            raise
        return [SearchHit(p["score"], p["payload"]) for p in result["points"] if p.get("payload")]

    async def health(self) -> None:
        # /collections needs the API key, so this also checks the credentials.
        await self._call("GET", f"{self._base_url}/collections", timeout_s=5)

    async def _call(self, method: str, url: str, body: object = None, timeout_s: float | None = None) -> Any:
        return await request_json(
            self._client, "qdrant", method, url, timeout_s or self._timeout, body=body, headers=self._headers
        )
