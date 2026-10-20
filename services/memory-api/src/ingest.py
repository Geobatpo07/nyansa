"""Ingestion: plans what changed in the vault and indexes it into the vector store."""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from .domain import ChunkPayload, ChunkPoint, Embedder, IndexedNote, UpstreamError, VectorStore
from .graph import Graph, build_graph
from .markdown import chunk_note, parse_note
from .vault import NoteFile, read_vault, sha256

type IngestMode = Literal["full", "incremental"]

# Bump when the chunking or payload format changes: every note is then
# reindexed by the next incremental run.
CHUNKER_VERSION = "chunker-v1"

# After this many notes in a row fail on Ollama or Qdrant, the run stops:
# the service is down or misconfigured, and every other note would fail the
# same way. Skipped notes keep their old hash and are retried next run.
MAX_CONSECUTIVE_UPSTREAM_FAILURES = 3

log = logging.getLogger(__name__)


class CamelModel(BaseModel):
    """Serialized with camelCase keys, the JSON convention of the HTTP API."""

    model_config = ConfigDict(alias_generator=to_camel, validate_by_name=True, serialize_by_alias=True)


class NoteCounts(CamelModel):
    scanned: int = 0
    indexed: int = 0
    unchanged: int = 0
    deleted: int = 0
    failed: int = 0
    # Not attempted because the run was aborted.
    skipped: int = 0


class ChunkCounts(CamelModel):
    upserted: int = 0


class GraphCounts(CamelModel):
    notes: int
    ghosts: int
    links: int
    tags: int


class NoteError(CamelModel):
    path: str
    message: str


class IngestReport(CamelModel):
    mode: IngestMode
    started_at: str
    duration_ms: int = 0
    notes: NoteCounts
    chunks: ChunkCounts = Field(default_factory=ChunkCounts)
    errors: list[NoteError] = Field(default_factory=list)
    # Set when the run stopped early (upstream service unavailable).
    aborted: str | None = None
    # The graph rebuilt from the whole vault, or why it could not be: the
    # notes are indexed either way.
    graph: GraphCounts | None = None
    graph_error: str | None = None


class IngestInProgressError(Exception):
    def __init__(self) -> None:
        super().__init__("an ingestion is already running")


@dataclass
class IngestPlan:
    # Notes to (re)index: new, modified, or indexed with another index version.
    to_index: list[str] = field(default_factory=list)
    # Notes whose content and index version did not change.
    unchanged: list[str] = field(default_factory=list)
    # Notes present in the index but no longer in the vault.
    to_delete: list[str] = field(default_factory=list)


def plan_ingest(vault: dict[str, str], indexed: list[IndexedNote], mode: IngestMode, index_version: str) -> IngestPlan:
    """Decides what an ingestion run must do, from the vault (path -> hash) and the index.

    - full: every vault note is reindexed.
    - incremental: only notes whose hash or index version differ from the
      index are reindexed.
    In both modes, notes deleted from the vault are removed from the index.
    """
    known = {note.path: note for note in indexed}
    plan = IngestPlan(to_delete=sorted(path for path in known if path not in vault))
    for path, note_hash in vault.items():
        previous = known.get(path)
        up_to_date = previous is not None and previous.hash == note_hash and previous.version == index_version
        (plan.unchanged if mode == "incremental" and up_to_date else plan.to_index).append(path)
    return plan


class Ingestor:
    def __init__(
        self,
        vault_path: str,
        embedder: Embedder,
        store: VectorStore,
        max_chars: int,
        graph: Graph | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._graph = graph
        self._vault_path = vault_path
        self._embedder = embedder
        self._store = store
        self._max_chars = max_chars
        self._now = now
        self._running = False
        self._collection_ready = False
        self.index_version = sha256(f"{CHUNKER_VERSION}|{embedder.model}|{max_chars}")[:12]

    @property
    def is_running(self) -> bool:
        return self._running

    async def run(self, mode: IngestMode, on_progress: Callable[[int, int], None] | None = None) -> IngestReport:
        """Runs one ingestion. Only one run at a time; a concurrent call fails fast.

        on_progress(done, total) is called once the run is planned, then after
        each note to index.
        """
        if self._running:
            raise IngestInProgressError
        self._running = True
        try:
            return await self._execute(mode, on_progress or (lambda done, total: None))
        finally:
            self._running = False

    async def _execute(self, mode: IngestMode, on_progress: Callable[[int, int], None]) -> IngestReport:
        started = self._now()
        await self._ensure_collection()

        notes = {note.path: note for note in await asyncio.to_thread(read_vault, self._vault_path)}
        for note in notes.values():
            if note.encoding != "utf-8":
                log.warning("note %s is not valid UTF-8, decoded as Windows-1252", note.path)

        plan = plan_ingest(
            {path: note.hash for path, note in notes.items()},
            await self._store.list_indexed_notes(),
            mode,
            self.index_version,
        )
        report = IngestReport(
            mode=mode,
            started_at=iso(started),
            notes=NoteCounts(scanned=len(notes), unchanged=len(plan.unchanged)),
        )

        on_progress(0, len(plan.to_index))
        consecutive_upstream_failures = 0
        for position, path in enumerate(plan.to_index):
            note = notes[path]
            try:
                report.chunks.upserted += await self._index_note(path, note.content, note.hash)
                report.notes.indexed += 1
                consecutive_upstream_failures = 0
            except Exception as err:
                report.notes.failed += 1
                report.errors.append(NoteError(path=path, message=str(err)))
                log.warning("indexing %s failed: %s", path, err)

                consecutive_upstream_failures = (
                    consecutive_upstream_failures + 1 if isinstance(err, UpstreamError) else 0
                )
                if consecutive_upstream_failures >= MAX_CONSECUTIVE_UPSTREAM_FAILURES:
                    service = err.service if isinstance(err, UpstreamError) else "an upstream service"
                    report.notes.skipped = len(plan.to_index) - position - 1
                    report.aborted = (
                        f"{consecutive_upstream_failures} consecutive failures of {service}; "
                        f"{report.notes.skipped} notes skipped, retried on the next run"
                    )
                    log.error(report.aborted)
                    break
            on_progress(position + 1, len(plan.to_index))

        for path in plan.to_delete:
            try:
                await self._store.delete_note(path)
                report.notes.deleted += 1
            except Exception as err:
                report.errors.append(NoteError(path=path, message=str(err)))

        if self._graph is not None:
            await self._rebuild_graph(self._graph, list(notes.values()), report)

        report.duration_ms = int((self._now() - started).total_seconds() * 1000)
        log.info("ingestion finished: %s", report.model_dump_json(include={"mode", "notes", "chunks"}))
        return report

    async def _index_note(self, path: str, content: str, note_hash: str) -> int:
        """Indexes one note and returns the number of chunks written."""
        note = parse_note(path, content)
        if note.frontmatter_error is not None:
            log.warning("invalid frontmatter of %s ignored: %s", path, note.frontmatter_error)
        chunks = chunk_note(note.body, note.title, self._max_chars)
        vectors = await self._embedder.embed_documents(
            [embedding_text(note.title, chunk.section, chunk.text) for chunk in chunks]
        )
        if len(vectors) != len(chunks):
            raise ValueError(f"expected {len(chunks)} embeddings, received {len(vectors)}")

        indexed_at = iso(self._now())
        links = sorted({link.target for link in note.links})
        points = [
            ChunkPoint(
                id=point_id(path, chunk.index),
                vector=vector,
                payload=ChunkPayload(
                    path=path,
                    title=note.title,
                    tags=note.tags,
                    links=links,
                    section=chunk.section,
                    chunk_index=chunk.index,
                    chunk_count=len(chunks),
                    text=chunk.text,
                    note_hash=note_hash,
                    index_version=self.index_version,
                    indexed_at=indexed_at,
                ),
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        # Upsert first (same ids overwrite the previous version), then drop the
        # chunks the note no longer has: the note is never absent from the index.
        # The first chunk carries the note hash that marks the note as indexed,
        # so it is written last: if anything before fails or the service stops,
        # the note keeps its old hash and the next run indexes it again.
        await self._store.upsert_chunks(points[1:])
        await self._store.delete_note(path, len(chunks))
        await self._store.upsert_chunks(points[:1])
        return len(points)

    async def _rebuild_graph(self, graph: Graph, notes: list[NoteFile], report: IngestReport) -> None:
        """Rebuilds the graph from every note of the vault, whatever the indexing did."""

        def rebuild() -> GraphCounts:
            data = build_graph([parse_note(note.path, note.content) for note in notes])
            graph.replace(data)
            ghosts = sum(note["ghost"] for note in data.notes)
            return GraphCounts(
                notes=len(data.notes) - ghosts, ghosts=ghosts, links=len(data.links), tags=len(data.tags)
            )

        try:
            report.graph = await asyncio.to_thread(rebuild)
        except Exception as err:
            report.graph_error = str(err)
            log.warning("the graph was not rebuilt: %s", err)

    async def _ensure_collection(self) -> None:
        if self._collection_ready:
            return
        probe = (await self._embedder.embed_documents(["dimension probe"]))[0]
        if not probe:
            raise ValueError("the embedding model returned an empty vector")
        await self._store.ensure_collection(len(probe))
        self._collection_ready = True


def embedding_text(title: str, section: str, text: str) -> str:
    """Text sent to the embedding model: the note title and section give each chunk its context."""
    return f"{title} > {section}\n\n{text}" if section else f"{title}\n\n{text}"


def point_id(path: str, chunk_index: int) -> str:
    """Deterministic UUID for a chunk, so reindexing a note overwrites its points."""
    digits = list(sha256(f"{path}\0{chunk_index}")[:32])
    digits[12] = "5"  # version nibble
    digits[16] = format((int(digits[16], 16) & 0x3) | 0x8, "x")  # RFC 4122 variant
    h = "".join(digits)
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def iso(moment: datetime) -> str:
    """ISO 8601 in UTC with milliseconds, e.g. `2026-09-26T12:00:00.000Z`."""
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
