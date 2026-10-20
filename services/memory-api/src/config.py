"""Configuration from environment variables, validated at startup."""

from collections.abc import Mapping
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, Field, ValidationError


def _url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("must be an http(s) URL")
    return value.rstrip("/")


type Url = Annotated[str, AfterValidator(_url)]


class Config(BaseModel):
    MEMORY_API_HOST: str = "0.0.0.0"  # noqa: S104 # the container's own interface, published nowhere
    MEMORY_API_PORT: int = Field(8080, ge=1, le=65535)
    # Bearer token required on every route except /health.
    MEMORY_API_TOKEN: str = Field(min_length=32)
    VAULT_PATH: str = Field("/vault", min_length=1)
    # SQLite file of the ingestion tasks, in a writable volume.
    STATE_PATH: str = Field("/state/memory-api.db", min_length=1)
    # LadybugDB file of the graph, in the same volume. Derived from the vault:
    # deleted and rebuilt when unreadable.
    GRAPH_PATH: str = Field("/state/graph.lbug", min_length=1)
    OLLAMA_URL: Url = "http://nyansa-ollama:11434"
    EMBEDDING_MODEL: str = Field("nomic-embed-text", min_length=1)
    QDRANT_URL: Url = "http://nyansa-qdrant:6333"
    QDRANT_API_KEY: str = Field(min_length=1)
    QDRANT_COLLECTION: str = Field("obsidian_notes", pattern=r"^[\w-]+$")
    CHUNK_MAX_CHARS: int = Field(1500, ge=200, le=8000)
    # /context: minimum similarity of a relevant chunk, and size of the context given to the model.
    CONTEXT_MIN_SCORE: float = Field(0.65, ge=-1, le=1)
    CONTEXT_MAX_CHARS: int = Field(6000, ge=500, le=50000)
    LOG_LEVEL: Literal["fatal", "error", "warn", "info", "debug", "trace", "silent"] = "info"


def load_config(env: Mapping[str, str]) -> Config:
    """Reads and validates the configuration; raises ValueError listing every problem."""
    try:
        return Config.model_validate({name: env[name] for name in Config.model_fields if name in env})
    except ValidationError as err:
        problems = "\n  - ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in err.errors())
        raise ValueError(f"invalid configuration:\n  - {problems}") from None
