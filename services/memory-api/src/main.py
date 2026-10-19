"""Entry point: `python main.py` (from src/)."""

import asyncio
import logging
import os
import sys

import httpx
import uvicorn

from app import build_app
from clients import OllamaEmbedder, QdrantStore
from config import load_config
from ingest import Ingestor

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

    async with httpx.AsyncClient() as client:
        embedder = OllamaEmbedder(client, config.OLLAMA_URL, config.EMBEDDING_MODEL)
        store = QdrantStore(client, config.QDRANT_URL, config.QDRANT_API_KEY, config.QDRANT_COLLECTION)
        ingestor = Ingestor(config.VAULT_PATH, embedder, store, config.CHUNK_MAX_CHARS)
        app = build_app(config.MEMORY_API_TOKEN, ingestor, embedder, store)
        # uvicorn stops gracefully on SIGINT and SIGTERM. Its access log never
        # contains headers, so the bearer token is not logged.
        server = uvicorn.Server(
            uvicorn.Config(app, host=config.MEMORY_API_HOST, port=config.MEMORY_API_PORT, log_config=None)
        )
        await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
