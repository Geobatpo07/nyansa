"""Entry point: `python -m src.main`."""

import asyncio
import logging
import os
import sys

import httpx
import uvicorn

from .app import build_app
from .clients import OllamaEmbedder, QdrantStore
from .config import load_config
from .ingest import Ingestor
from .jobs import IngestJobs, JobStore

_LOG_LEVELS = {
    "fatal": logging.CRITICAL,
    "error": logging.ERROR,
    "warn": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
    "trace": logging.DEBUG,
    "silent": logging.CRITICAL + 1,
}


async def main() -> None:
    try:
        config = load_config(os.environ)
    except ValueError as err:
        sys.exit(str(err))
    logging.basicConfig(
        level=_LOG_LEVELS[config.LOG_LEVEL], format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stdout
    )
    # httpx logs every Ollama and Qdrant request at INFO: one line per batch of chunks.
    logging.getLogger("httpx").setLevel(max(logging.WARNING, _LOG_LEVELS[config.LOG_LEVEL]))

    async with httpx.AsyncClient() as client:
        embedder = OllamaEmbedder(client, config.OLLAMA_URL, config.EMBEDDING_MODEL)
        store = QdrantStore(client, config.QDRANT_URL, config.QDRANT_API_KEY, config.QDRANT_COLLECTION)
        ingestor = Ingestor(config.VAULT_PATH, embedder, store, config.CHUNK_MAX_CHARS)
        history = JobStore(config.STATE_PATH)
        jobs = IngestJobs(ingestor, history)
        app = build_app(config.MEMORY_API_TOKEN, jobs, history, embedder, store)
        # uvicorn stops gracefully on SIGINT and SIGTERM. Its access log never
        # contains headers, so the bearer token is not logged.
        server = uvicorn.Server(
            uvicorn.Config(app, host=config.MEMORY_API_HOST, port=config.MEMORY_API_PORT, log_config=None)
        )
        try:
            await server.serve()
        finally:
            # A running ingestion is recorded as interrupted before the process exits.
            await jobs.stop()
            history.close()


if __name__ == "__main__":
    asyncio.run(main())
