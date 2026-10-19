"""Domain types and the boundaries of the service.

The ingestion and search logic only depend on the Embedder and VectorStore
protocols; the Ollama and Qdrant adapters implement them, and tests use
in-memory fakes.
"""

from dataclasses import dataclass
from typing import Literal, Protocol, TypedDict

type Service = Literal["ollama", "qdrant"]


@dataclass(frozen=True)
class WikiLink:
    """A `[[wikilink]]` or `![[embed]]` found in a note."""

    # Linked note, as written, without the `.md` extension.
    target: str
    # True for `![[...]]` embeds.
    embed: bool = False
    # Heading or block reference after `#`, if any.
    heading: str | None = None
    # Display text after `|`, if any.
    alias: str | None = None


@dataclass
class ParsedNote:
    # Vault-relative POSIX path, e.g. `projects/nyansa.md`.
    path: str
    title: str
    frontmatter: dict[object, object]
    # Lower-cased, without `#`, deduplicated, sorted.
    tags: list[str]
    links: list[WikiLink]
    # Markdown content without the frontmatter block.
    body: str
    # Set when the frontmatter could not be parsed; the note is still indexed.
    frontmatter_error: str | None = None


@dataclass(frozen=True)
class Chunk:
    # Position of the chunk in the note, starting at 0.
    index: int
    # Heading path of the section, e.g. `Setup > Docker`; empty before the first heading.
    section: str
    headings: list[str]
    text: str


class ChunkPayload(TypedDict):
    """Payload stored with every vector in Qdrant."""

    path: str
    title: str
    tags: list[str]
    # Distinct wikilink targets of the whole note (used by the graph in phase 4).
    links: list[str]
    section: str
    chunk_index: int
    chunk_count: int
    text: str
    # SHA-256 of the raw note file; drives incremental indexing.
    note_hash: str
    # Changes when the chunking or the embedding model changes.
    index_version: str
    indexed_at: str


@dataclass(frozen=True)
class ChunkPoint:
    id: str
    vector: list[float]
    payload: ChunkPayload


@dataclass(frozen=True)
class IndexedNote:
    """What the index knows about a note (read from its first chunk)."""

    path: str
    hash: str
    version: str


@dataclass(frozen=True)
class SearchHit:
    score: float
    payload: ChunkPayload


class UpstreamError(Exception):
    """Raised when Ollama or Qdrant fails or is unreachable."""

    def __init__(self, service: Service, message: str, status: int | None = None) -> None:
        super().__init__(f"{service}: {message}")
        self.service = service
        self.status = status


class Embedder(Protocol):
    @property
    def model(self) -> str: ...

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embeds note chunks (document side of the retrieval task)."""
        ...

    async def embed_query(self, text: str) -> list[float]:
        """Embeds a user question (query side of the retrieval task)."""
        ...

    async def health(self) -> None:
        """Returns when the embedding service is reachable."""
        ...


class VectorStore(Protocol):
    async def ensure_collection(self, dimensions: int) -> None:
        """Creates the collection and payload indexes if missing; fails on a dimension mismatch."""
        ...

    async def list_indexed_notes(self) -> list[IndexedNote]: ...

    async def upsert_chunks(self, points: list[ChunkPoint]) -> None: ...

    async def delete_note(self, path: str, from_chunk_index: int = 0) -> None:
        """Deletes the chunks of a note whose index is >= from_chunk_index (all chunks by default)."""
        ...

    async def search(
        self, vector: list[float], limit: int, tags: list[str] | None = None, min_score: float | None = None
    ) -> list[SearchHit]: ...

    async def health(self) -> None:
        """Returns when the store is reachable and accepts the credentials."""
        ...
