"""HTTP API. Dependencies are injected so tests can replace them."""

import asyncio
import hmac
import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated, Literal

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .domain import Embedder, UpstreamError, VectorStore
from .jobs import IngestJobs, Job, JobInProgressError, JobStore

MAX_BODY_BYTES = 64 * 1024


class IngestBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    mode: Literal["full", "incremental"] = "incremental"


class SearchBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    limit: Annotated[int, Field(ge=1, le=50)] = 5
    tags: Annotated[list[Annotated[str, StringConstraints(min_length=1)]], Field(max_length=20)] | None = None
    min_score: Annotated[float | None, Field(ge=-1, le=1, alias="minScore")] = None


def build_app(token: str, jobs: IngestJobs, history: JobStore, embedder: Embedder, store: VectorStore) -> FastAPI:
    app = FastAPI(title="Nyansa memory-api", docs_url=None, redoc_url=None)
    expected = token.encode()

    # Every route except /health needs `Authorization: Bearer <MEMORY_API_TOKEN>`.
    # Checked before the body is read, so an anonymous caller learns nothing else.
    @app.middleware("http")
    async def require_token(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if request.url.path != "/health":
            header = request.headers.get("authorization", "")
            provided = header.removeprefix("Bearer ").encode() if header.startswith("Bearer ") else b""
            if not hmac.compare_digest(provided, expected):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        if int(request.headers.get("content-length") or 0) > MAX_BODY_BYTES:
            return JSONResponse({"error": "request body too large"}, status_code=413)
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, err: RequestValidationError) -> Response:
        issues = [
            {"path": ".".join(str(part) for part in issue["loc"][1:]), "message": issue["msg"]}
            for issue in err.errors()
        ]
        return JSONResponse({"error": "invalid request", "issues": issues}, status_code=400)

    @app.exception_handler(JobInProgressError)
    async def ingest_in_progress(_request: Request, err: JobInProgressError) -> Response:
        return JSONResponse(
            {"error": str(err), "current": {"id": err.job.id, "status": err.job.status}},
            status_code=409,
            headers={"location": _location(err.job)},
        )

    @app.exception_handler(UpstreamError)
    async def upstream_failure(_request: Request, err: UpstreamError) -> Response:
        return JSONResponse(
            {"error": "upstream service failure", "service": err.service, "detail": str(err)}, status_code=502
        )

    @app.get("/health")
    async def health(response: Response) -> dict[str, object]:
        ollama, qdrant = await asyncio.gather(_check(embedder.health), _check(store.health))
        ok = ollama == qdrant == "ok"
        response.status_code = 200 if ok else 503
        return {
            "status": "ok" if ok else "degraded",
            "checks": {"ollama": ollama, "qdrant": qdrant},
            "ingesting": jobs.current is not None,
        }

    # Starts an ingestion in the background; its state is at the Location URL.
    @app.post("/ingest", status_code=202)
    async def ingest(response: Response, body: IngestBody | None = None) -> Job:
        job = jobs.start((body or IngestBody()).mode)
        response.headers["location"] = _location(job)
        return job

    @app.get("/ingest/status")
    async def ingest_status() -> dict[str, object]:
        return {"current": jobs.current, "recent": history.recent()}

    @app.get("/ingest/status/{job_id}", response_model=None)
    async def ingest_job(job_id: uuid.UUID) -> Job | JSONResponse:
        job = history.get(str(job_id))
        return job if job is not None else JSONResponse({"error": "unknown ingestion"}, status_code=404)

    @app.post("/search")
    async def search(body: SearchBody) -> dict[str, object]:
        vector = await embedder.embed_query(body.query)
        tags = [tag.removeprefix("#").lower() for tag in body.tags] if body.tags is not None else None
        hits = await store.search(vector, body.limit, tags, body.min_score)
        results = [
            {
                "score": hit.score,
                "path": hit.payload["path"],
                "title": hit.payload["title"],
                "section": hit.payload["section"],
                "tags": hit.payload["tags"],
                "chunkIndex": hit.payload["chunk_index"],
                "text": hit.payload["text"],
            }
            for hit in hits
        ]
        return {"query": body.query, "results": results}

    return app


def _location(job: Job) -> str:
    return f"/ingest/status/{job.id}"


async def _check(probe: Callable[[], Awaitable[None]]) -> str:
    try:
        await probe()
    except Exception as err:
        return str(err)
    return "ok"
