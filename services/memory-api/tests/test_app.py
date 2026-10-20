import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from src.app import build_app
from src.domain import UpstreamError
from src.ingest import Ingestor
from src.jobs import IngestJobs, JobStore
from tests.fakes import FakeEmbedder, InMemoryStore, Vault

TOKEN = "t" * 32
AUTH = {"authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


@pytest.fixture
async def client(
    vault: Vault, embedder: FakeEmbedder, store: InMemoryStore, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    vault.write(
        "Docker.md", "---\ntags: [infra]\n---\n# Docker\n## Compose\nDocker compose runs the stack with profiles."
    )
    vault.write("Cooking.md", "# Cooking\nA recipe for bread with flour and water.")
    history = JobStore(tmp_path / "state" / "jobs.db")
    jobs = IngestJobs(Ingestor(str(vault.root), embedder, store, 500), history)
    app = build_app(TOKEN, jobs, history, embedder, store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://memory-api") as client:
        yield client
    await jobs.stop()
    history.close()


async def finished(client: httpx.AsyncClient, location: str) -> dict[str, Any]:
    """Polls an ingestion until it is no longer running."""
    for _ in range(500):
        job: dict[str, Any] = (await client.get(location, headers=AUTH)).json()
        if job["status"] != "running":
            return job
        await asyncio.sleep(0.01)
    raise AssertionError(f"ingestion still running: {job}")


async def ingest(client: httpx.AsyncClient, mode: str = "incremental") -> dict[str, Any]:
    response = await client.post("/ingest", headers=AUTH, json={"mode": mode})
    assert response.status_code == 202
    return await finished(client, response.headers["location"])


@pytest.mark.parametrize(
    "headers",
    [{}, {"authorization": f"Bearer {'x' * 32}"}, {"authorization": f"Basic {TOKEN}"}],
    ids=["no header", "wrong token", "wrong scheme"],
)
async def test_rejects_requests_without_the_token(client: httpx.AsyncClient, headers: dict[str, str]) -> None:
    for method, url in [
        ("POST", "/search"),
        ("POST", "/context"),
        ("POST", "/ingest"),
        ("GET", "/ingest/status"),
        ("GET", "/ingest/status/00000000-0000-4000-8000-000000000000"),
        ("GET", "/openapi.json"),
        ("GET", "/unknown"),
    ]:
        response = await client.request(method, url, headers=headers, json={"query": "x"})
        assert (response.status_code, response.json()) == (401, {"error": "unauthorized"}), url


async def test_rejects_malformed_json_without_the_token_as_unauthorized(client: httpx.AsyncClient) -> None:
    response = await client.post("/search", content=b'{"query":', headers={"content-type": "application/json"})
    assert response.status_code == 401


async def test_health_is_open_and_reports_each_dependency(client: httpx.AsyncClient) -> None:
    response = await client.get("/health", params={"probe": 1})
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"ollama": "ok", "qdrant": "ok"}, "ingesting": False}


async def test_health_is_503_when_a_dependency_is_down(
    client: httpx.AsyncClient, store: InMemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def down() -> None:
        raise UpstreamError("qdrant", "HTTP 401 on /collections")

    monkeypatch.setattr(store, "health", down)
    response = await client.get("/health")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["checks"] == {"ollama": "ok", "qdrant": "qdrant: HTTP 401 on /collections"}


async def test_ingest_starts_a_background_ingestion_and_points_to_its_state(client: httpx.AsyncClient) -> None:
    response = await client.post("/ingest", headers=AUTH)

    assert response.status_code == 202
    job = response.json()
    assert (job["mode"], job["status"], job["finishedAt"], job["report"]) == ("incremental", "running", None, None)
    assert response.headers["location"] == f"/ingest/status/{job['id']}"

    done = await finished(client, response.headers["location"])
    assert (done["status"], done["error"]) == ("completed", None)
    assert done["progress"] == {"total": 2, "done": 2}
    assert (done["report"]["notes"]["scanned"], done["report"]["notes"]["indexed"]) == (2, 2)
    assert done["finishedAt"] is not None

    again = await ingest(client, "full")
    assert (again["mode"], again["report"]["notes"]["indexed"], again["report"]["notes"]["unchanged"]) == ("full", 2, 0)


async def test_ingest_accepts_a_json_content_type_with_an_empty_body(client: httpx.AsyncClient) -> None:
    response = await client.post("/ingest", headers={**AUTH, "content-type": "application/json"})
    assert (response.status_code, response.json()["mode"]) == (202, "incremental")
    await finished(client, response.headers["location"])


async def test_ingest_validates_the_mode(client: httpx.AsyncClient) -> None:
    response = await client.post("/ingest", headers=AUTH, json={"mode": "everything"})
    assert response.status_code == 400
    assert response.json()["error"] == "invalid request"
    assert [issue["path"] for issue in response.json()["issues"]] == ["mode"]


async def test_ingest_answers_409_with_the_running_ingestion(client: httpx.AsyncClient) -> None:
    first = await client.post("/ingest", headers=AUTH)
    second = await client.post("/ingest", headers=AUTH)

    assert second.status_code == 409
    assert second.json() == {
        "error": "an ingestion is already running",
        "current": {"id": first.json()["id"], "status": "running"},
    }
    assert second.headers["location"] == first.headers["location"]
    await finished(client, first.headers["location"])
    assert (await client.post("/ingest", headers=AUTH)).status_code == 202


async def test_ingest_status_lists_the_current_and_recent_ingestions(client: httpx.AsyncClient) -> None:
    done = await ingest(client)
    running = (await client.post("/ingest", headers=AUTH)).json()

    status = (await client.get("/ingest/status", headers=AUTH)).json()

    assert status["current"]["id"] == running["id"]
    assert [job["id"] for job in status["recent"]] == [running["id"], done["id"]]
    await finished(client, f"/ingest/status/{running['id']}")
    assert (await client.get("/ingest/status", headers=AUTH)).json()["current"] is None


async def test_ingest_status_of_an_unknown_or_invalid_id(client: httpx.AsyncClient) -> None:
    unknown = await client.get("/ingest/status/00000000-0000-4000-8000-000000000000", headers=AUTH)
    assert (unknown.status_code, unknown.json()) == (404, {"error": "unknown ingestion"})
    assert (await client.get("/ingest/status/not-an-id", headers=AUTH)).status_code == 400


async def test_a_failed_ingestion_is_reported(
    client: httpx.AsyncClient, store: InMemoryStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def qdrant_down() -> list[object]:
        raise UpstreamError("qdrant", "request to /points/scroll failed: ConnectError")

    monkeypatch.setattr(store, "list_indexed_notes", qdrant_down)
    job = await ingest(client)
    assert (job["status"], job["report"]) == ("failed", None)
    assert job["error"] == "qdrant: request to /points/scroll failed: ConnectError"


async def test_search_returns_ranked_chunks_with_their_source_note(client: httpx.AsyncClient) -> None:
    await ingest(client)

    response = await client.post("/search", headers=AUTH, json={"query": "docker compose stack", "limit": 1})

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "docker compose stack"
    [result] = body["results"]
    assert result.pop("score") > 0
    assert result == {
        "path": "Docker.md",
        "title": "Docker",
        "section": "Docker > Compose",
        "tags": ["infra"],
        "chunkIndex": 0,
        "text": "Docker compose runs the stack with profiles.",
    }


async def test_search_filters_by_tag_with_or_without_hash(client: httpx.AsyncClient) -> None:
    await ingest(client)
    response = await client.post("/search", headers=AUTH, json={"query": "bread recipe", "tags": ["#INFRA"]})
    assert [r["path"] for r in response.json()["results"]] == ["Docker.md"]


async def test_search_accepts_a_score_threshold(client: httpx.AsyncClient) -> None:
    await ingest(client)
    response = await client.post("/search", headers=AUTH, json={"query": "bread recipe", "minScore": 1})
    assert (response.status_code, response.json()["results"]) == (200, [])


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"query": "   "},
        {"query": "x", "limit": 0},
        {"query": "x", "limit": 51},
        {"query": "x", "limit": "5"},
        {"query": "x", "extra": True},
        {"query": "x", "min_score": 0.5},
        {"query": "x", "minScore": 2},
        {"query": "x", "tags": [""]},
    ],
)
async def test_search_validates_its_body(client: httpx.AsyncClient, body: dict[str, object]) -> None:
    assert (await client.post("/search", headers=AUTH, json=body)).status_code == 400


async def test_rejects_malformed_json_with_400(client: httpx.AsyncClient) -> None:
    headers = {**AUTH, "content-type": "application/json"}
    assert (await client.post("/search", headers=headers, content=b'{"query":')).status_code == 400


async def test_rejects_a_body_over_64_kib(client: httpx.AsyncClient) -> None:
    response = await client.post("/search", headers=AUTH, json={"query": "x" * 70_000})
    assert response.status_code == 413


async def test_maps_upstream_failures_to_502(
    client: httpx.AsyncClient, embedder: FakeEmbedder, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def model_missing(text: str) -> list[float]:
        raise UpstreamError("ollama", "HTTP 404 on /api/embed: model not found", 404)

    monkeypatch.setattr(embedder, "embed_query", model_missing)
    response = await client.post("/search", headers=AUTH, json={"query": "x"})
    assert response.status_code == 502
    assert response.json()["service"] == "ollama"


async def test_context_returns_numbered_sources_and_the_text_to_quote(client: httpx.AsyncClient) -> None:
    await ingest(client)

    response = await client.post("/context", headers=AUTH, json={"query": "docker compose stack profiles"})

    assert response.status_code == 200
    body = response.json()
    assert body["found"] is True
    first = body["sources"][0]
    assert (first["n"], first["path"], first["title"], first["sections"]) == (
        1,
        "Docker.md",
        "Docker",
        ["Docker > Compose"],
    )
    assert body["context"].startswith("[1] Docker (Docker.md)\nSection: Docker > Compose\nDocker compose runs")


async def test_context_is_not_found_below_the_relevance_threshold(client: httpx.AsyncClient) -> None:
    await ingest(client)
    # The fake embedder shares no word with this question: every score is 0, under the default 0.5.
    response = await client.post("/context", headers=AUTH, json={"query": "quantum chromodynamics"})
    assert response.json() == {"query": "quantum chromodynamics", "found": False, "sources": [], "context": ""}

    relaxed = await client.post("/context", headers=AUTH, json={"query": "quantum chromodynamics", "minScore": -1})
    assert relaxed.json()["found"] is True


async def test_context_validates_its_body(client: httpx.AsyncClient) -> None:
    for body in ({}, {"query": "x", "limit": 21}, {"query": "x", "extra": 1}):
        assert (await client.post("/context", headers=AUTH, json=body)).status_code == 400
