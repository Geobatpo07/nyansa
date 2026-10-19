"""Runs the ingestion against a real Qdrant (the embeddings stay fake).

Skipped unless QDRANT_TEST_URL is set, e.g.:
  docker run -d --rm -p 127.0.0.1:6399:6333 -e QDRANT__SERVICE__API_KEY=test qdrant/qdrant:v1.19.1
  QDRANT_TEST_URL=http://127.0.0.1:6399 QDRANT_TEST_API_KEY=test uv run pytest
"""

import os
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest

from clients import QdrantStore
from domain import UpstreamError
from fakes import FakeEmbedder, Vault
from ingest import Ingestor, point_id

URL = os.environ.get("QDRANT_TEST_URL")
API_KEY = os.environ.get("QDRANT_TEST_API_KEY", "")

pytestmark = pytest.mark.skipif(URL is None, reason="QDRANT_TEST_URL is not set")


@pytest.fixture
async def qdrant() -> AsyncIterator[tuple[httpx.AsyncClient, QdrantStore]]:
    collection = f"test_{uuid.uuid4().hex}"
    async with httpx.AsyncClient(base_url=URL or "", headers={"api-key": API_KEY}) as client:
        yield client, QdrantStore(client, URL or "", API_KEY, collection)
        await client.delete(f"/collections/{collection}")


async def points_by_path(client: httpx.AsyncClient, store: QdrantStore) -> dict[str, list[str]]:
    """Chunk ids stored in Qdrant, per note path."""
    response = await client.post(
        f"{store._collection_url}/points/scroll", json={"limit": 1000, "with_payload": ["path"], "with_vector": False}
    )
    by_path: dict[str, list[str]] = {}
    for point in response.json()["result"]["points"]:
        by_path.setdefault(point["payload"]["path"], []).append(point["id"])
    return by_path


async def test_ingestion_lifecycle(
    qdrant: tuple[httpx.AsyncClient, QdrantStore], vault: Vault, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store = qdrant

    def ingestor(embedder: FakeEmbedder | None = None) -> Ingestor:
        return Ingestor(str(vault.root), embedder or FakeEmbedder(), store, 200)

    # Indexes the vault.
    vault.write("Long.md", f"# Long\n{'First part. ' * 15}\n## Two\n{'Second part. ' * 15}\n## Three\nEnd.")
    vault.write("Keep.md", "# Keep\nStays.")
    vault.write("Gone.md", f"# Gone\n{'Deleted soon. ' * 20}")
    vault.write("Old name.md", "# Moving\nThis note will be renamed.")
    report = await ingestor().run("incremental")
    assert (report.notes.indexed, report.notes.failed) == (4, 0)
    before = await points_by_path(client, store)
    assert len(before["Long.md"]) >= 3
    assert len(before["Gone.md"]) >= 2

    # Removes the stale chunks of shortened, deleted and renamed notes.
    vault.write("Long.md", "# Long\nNow short.")
    vault.remove("Gone.md")
    vault.remove("Old name.md")
    vault.write("New name.md", "# Moving\nThis note will be renamed.")
    report = await ingestor().run("incremental")
    notes = report.notes
    assert (notes.indexed, notes.deleted, notes.unchanged, notes.failed) == (2, 2, 1, 0)
    after = await points_by_path(client, store)
    assert after["Long.md"] == [point_id("Long.md", 0)]
    assert "Gone.md" not in after
    assert "Old name.md" not in after
    assert after["New name.md"] == [point_id("New name.md", 0)]
    assert after["Keep.md"] == before["Keep.md"]

    # Records no hash for notes skipped after an aborted run.
    keep_hash = {n.path: n.hash for n in await store.list_indexed_notes()}["Keep.md"]
    embedder = FakeEmbedder()
    failing = ingestor(embedder)
    # Nothing changed: lets this ingestor check the collection while the embedder still answers.
    assert (await failing.run("incremental")).notes.indexed == 0
    vault.write("Keep.md", "# Keep\nEdited during the outage.")
    for i in range(5):
        vault.write(f"outage/n{i}.md", f"# Outage {i}\ntext {i}")

    async def ollama_down(texts: list[str]) -> list[list[float]]:
        raise UpstreamError("ollama", "ConnectError")

    monkeypatch.setattr(embedder, "embed_documents", ollama_down)
    report = await failing.run("incremental")

    assert report.aborted is not None
    assert report.notes.failed + report.notes.skipped == 6
    indexed = {n.path: n.hash for n in await store.list_indexed_notes()}
    assert not [path for path in indexed if path.startswith("outage/")]
    assert indexed["Keep.md"] == keep_hash

    retry = await ingestor().run("incremental")
    assert (retry.notes.indexed, retry.notes.failed, retry.notes.skipped) == (6, 0, 0)
    assert len([path for path in await points_by_path(client, store) if path.startswith("outage/")]) == 5
