import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest

from src.app import build_app
from src.domain import UpstreamError
from src.ingest import Ingestor
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
async def client(vault: Vault, embedder: FakeEmbedder, store: InMemoryStore) -> AsyncIterator[httpx.AsyncClient]:
    vault.write(
        "Docker.md", "---\ntags: [infra]\n---\n# Docker\n## Compose\nDocker compose runs the stack with profiles."
    )
    vault.write("Cooking.md", "# Cooking\nA recipe for bread with flour and water.")
    app = build_app(TOKEN, Ingestor(str(vault.root), embedder, store, 500), embedder, store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://memory-api") as client:
        yield client


@pytest.mark.parametrize(
    "headers",
    [{}, {"authorization": f"Bearer {'x' * 32}"}, {"authorization": f"Basic {TOKEN}"}],
    ids=["no header", "wrong token", "wrong scheme"],
)
async def test_rejects_requests_without_the_token(client: httpx.AsyncClient, headers: dict[str, str]) -> None:
    for method, url in [("POST", "/search"), ("POST", "/ingest"), ("GET", "/openapi.json"), ("GET", "/unknown")]:
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


async def test_ingest_runs_an_incremental_ingestion_by_default(client: httpx.AsyncClient) -> None:
    response = await client.post("/ingest", headers=AUTH)
    assert response.status_code == 200
    report = response.json()
    assert report["mode"] == "incremental"
    assert (report["notes"]["scanned"], report["notes"]["indexed"]) == (2, 2)
    assert {"startedAt", "durationMs"} <= report.keys()
    assert "aborted" not in report

    again = (await client.post("/ingest", headers=AUTH, json={"mode": "full"})).json()
    assert (again["mode"], again["notes"]["indexed"], again["notes"]["unchanged"]) == ("full", 2, 0)


async def test_ingest_accepts_a_json_content_type_with_an_empty_body(client: httpx.AsyncClient) -> None:
    response = await client.post("/ingest", headers={**AUTH, "content-type": "application/json"})
    assert (response.status_code, response.json()["mode"]) == (200, "incremental")


async def test_ingest_validates_the_mode(client: httpx.AsyncClient) -> None:
    response = await client.post("/ingest", headers=AUTH, json={"mode": "everything"})
    assert response.status_code == 400
    assert response.json()["error"] == "invalid request"
    assert [issue["path"] for issue in response.json()["issues"]] == ["mode"]


async def test_ingest_answers_409_while_an_ingestion_runs(client: httpx.AsyncClient) -> None:
    responses = await asyncio.gather(client.post("/ingest", headers=AUTH), client.post("/ingest", headers=AUTH))
    assert sorted(r.status_code for r in responses) == [200, 409]


async def test_search_returns_ranked_chunks_with_their_source_note(client: httpx.AsyncClient) -> None:
    await client.post("/ingest", headers=AUTH)

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
    await client.post("/ingest", headers=AUTH)
    response = await client.post("/search", headers=AUTH, json={"query": "bread recipe", "tags": ["#INFRA"]})
    assert [r["path"] for r in response.json()["results"]] == ["Docker.md"]


async def test_search_accepts_a_score_threshold(client: httpx.AsyncClient) -> None:
    await client.post("/ingest", headers=AUTH)
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
