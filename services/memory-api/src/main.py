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
from .graph import Graph
from .ingest import Ingestor
from .jobs import IngestJobs, JobStore

log = logging.getLogger(__name__)

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
        # One process owns the graph file (LadybugDB locks it): uvicorn runs
        # in this process, never with workers, and Compose runs one container.
        graph = Graph(config.GRAPH_PATH)
        ingestor = Ingestor(config.VAULT_PATH, embedder, store, config.CHUNK_MAX_CHARS, graph)

        async def build_graph() -> None:
            """Opens the graph and, when it is new or empty, builds it now from the vault."""
            try:
                built = await ingestor.build_graph_if_empty()
            except Exception as err:
                # /search and /context work without it; the next use retries.
                log.error("graph not built at startup: %s", err)
                return
            if built is not None:
                log.info("graph built at startup: %s", built.model_dump_json())

        # In the background: the API answers while a large vault is read.
        graph_task = asyncio.create_task(build_graph())
        history = JobStore(config.STATE_PATH)
        jobs = IngestJobs(ingestor, history)
        app = build_app(
            config.MEMORY_API_TOKEN,
            jobs,
            history,
            embedder,
            store,
            graph,
            config.CONTEXT_MIN_SCORE,
            config.CONTEXT_MAX_CHARS,
        )
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
            await asyncio.gather(graph_task, return_exceptions=True)
            # Releases the lock for the next container (deployment, rollback).
            graph.close()


if __name__ == "__main__":
    asyncio.run(main())
