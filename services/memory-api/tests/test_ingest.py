import asyncio
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import ClassVar

import pytest

from src.domain import IndexedNote, UpstreamError
from src.graph import Graph
from src.ingest import GraphCounts, IngestInProgressError, Ingestor, embedding_text, plan_ingest, point_id
from tests.fakes import FakeEmbedder, InMemoryStore, Vault
from tests.test_graph import hold


class TestPlanIngest:
    V = "v1"
    VAULT: ClassVar = {"new.md": "n", "same.md": "s", "edited.md": "e2", "old-version.md": "o"}
    INDEXED: ClassVar = [
        IndexedNote("same.md", "s", V),
        IndexedNote("edited.md", "e1", V),
        IndexedNote("old-version.md", "o", "v0"),
        IndexedNote("deleted.md", "d", V),
    ]

    def test_incremental_indexes_new_modified_and_outdated_notes_only(self) -> None:
        plan = plan_ingest(self.VAULT, self.INDEXED, "incremental", self.V)
        assert plan.to_index == ["new.md", "edited.md", "old-version.md"]
        assert plan.unchanged == ["same.md"]
        assert plan.to_delete == ["deleted.md"]

    def test_full_indexes_every_note_and_still_removes_deleted_ones(self) -> None:
        plan = plan_ingest(self.VAULT, self.INDEXED, "full", self.V)
        assert plan.to_index == ["new.md", "same.md", "edited.md", "old-version.md"]
        assert (plan.unchanged, plan.to_delete) == ([], ["deleted.md"])

    def test_empty_index_everything_is_new(self) -> None:
        assert len(plan_ingest(self.VAULT, [], "incremental", self.V).to_index) == 4

    def test_empty_vault_everything_indexed_is_deleted(self) -> None:
        plan = plan_ingest({}, self.INDEXED, "incremental", self.V)
        assert (plan.to_index, plan.unchanged) == ([], [])
        assert plan.to_delete == ["deleted.md", "edited.md", "old-version.md", "same.md"]


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


@pytest.fixture
def ingestor(vault: Vault, embedder: FakeEmbedder, store: InMemoryStore) -> Ingestor:
    vault.write(
        "Alpha.md", "---\ntags: [project]\n---\n# Alpha\nAlpha links to [[Beta]].\n## Details\nMore about alpha."
    )
    vault.write("notes/Beta.md", "# Beta\nBeta content #idea")
    vault.write(".obsidian/workspace.md", "ignored")
    vault.write("attachment.png", "not a note")
    return Ingestor(str(vault.root), embedder, store, 200, now=lambda: datetime(2026, 9, 26, 12, tzinfo=UTC))


async def test_indexes_every_note_of_an_empty_index_with_metadata(ingestor: Ingestor, store: InMemoryStore) -> None:
    report = await ingestor.run("incremental")

    assert report.notes.model_dump() == {
        "scanned": 2,
        "indexed": 2,
        "unchanged": 0,
        "deleted": 0,
        "failed": 0,
        "skipped": 0,
    }
    assert report.chunks.upserted == 3
    assert store.notes() == {"Alpha.md": 2, "notes/Beta.md": 1}
    payload = store.points[point_id("Alpha.md", 1)].payload
    assert re.fullmatch(r"[0-9a-f]{64}", payload.pop("note_hash"))  # type: ignore[misc]
    assert payload == {
        "path": "Alpha.md",
        "title": "Alpha",
        "tags": ["project"],
        "links": ["Beta"],
        "section": "Alpha > Details",
        "chunk_index": 1,
        "chunk_count": 2,
        "text": "More about alpha.",
        "index_version": ingestor.index_version,
        "indexed_at": "2026-09-26T12:00:00.000Z",
    }


async def test_skips_unchanged_notes_on_the_next_incremental_run(ingestor: Ingestor, embedder: FakeEmbedder) -> None:
    await ingestor.run("incremental")
    embedded_before = embedder.documents_embedded

    report = await ingestor.run("incremental")

    assert (report.notes.indexed, report.notes.unchanged, report.notes.deleted) == (0, 2, 0)
    assert embedder.documents_embedded == embedded_before


async def test_reindexes_a_shortened_note_and_drops_the_chunks_it_no_longer_has(
    ingestor: Ingestor, store: InMemoryStore, vault: Vault
) -> None:
    await ingestor.run("incremental")
    assert point_id("Alpha.md", 1) in store.points
    vault.write("Alpha.md", "# Alpha\nShorter now.")

    report = await ingestor.run("incremental")

    assert (report.notes.indexed, report.notes.unchanged) == (1, 1)
    assert store.notes() == {"Alpha.md": 1, "notes/Beta.md": 1}
    first = store.points[point_id("Alpha.md", 0)].payload
    assert (first["text"], first["chunk_count"]) == ("Shorter now.", 1)


async def test_a_note_interrupted_before_its_first_chunk_is_indexed_again(
    ingestor: Ingestor, store: InMemoryStore, vault: Vault, monkeypatch: pytest.MonkeyPatch
) -> None:
    await ingestor.run("incremental")
    old_hash = {n.path: n.hash for n in await store.list_indexed_notes()}["Alpha.md"]
    vault.write("Alpha.md", "# Alpha\nShorter now.")

    # Qdrant fails while the stale chunks of the shortened note are deleted.
    async def qdrant_down(path: str, from_chunk_index: int = 0) -> None:
        raise UpstreamError("qdrant", "request to /points/delete failed: ConnectError")

    with monkeypatch.context() as patch:
        patch.setattr(store, "delete_note", qdrant_down)
        assert (await ingestor.run("incremental")).notes.failed == 1

    # The note still has its old hash, so the next run indexes it again.
    assert {n.path: n.hash for n in await store.list_indexed_notes()}["Alpha.md"] == old_hash
    assert (await ingestor.run("incremental")).notes.indexed == 1
    assert store.notes()["Alpha.md"] == 1
    assert store.points[point_id("Alpha.md", 0)].payload["text"] == "Shorter now."


async def test_removes_every_chunk_of_a_deleted_note(ingestor: Ingestor, store: InMemoryStore, vault: Vault) -> None:
    vault.write("Long.md", f"# Long\n{'First part. ' * 20}\n## Two\n{'Second part. ' * 20}")
    await ingestor.run("incremental")
    long_ids = [point_id("Long.md", i) for i in range(3) if point_id("Long.md", i) in store.points]
    assert len(long_ids) > 1
    vault.remove("Long.md")

    report = await ingestor.run("incremental")

    assert (report.notes.scanned, report.notes.deleted) == (2, 1)
    assert not any(id_ in store.points for id_ in long_ids)
    assert store.notes() == {"Alpha.md": 2, "notes/Beta.md": 1}


async def test_moves_a_renamed_note(ingestor: Ingestor, store: InMemoryStore, vault: Vault) -> None:
    await ingestor.run("incremental")
    vault.remove("notes/Beta.md")
    vault.write("archive/Beta renamed.md", "# Beta\nBeta content #idea")

    report = await ingestor.run("incremental")

    assert (report.notes.indexed, report.notes.deleted, report.notes.unchanged) == (1, 1, 1)
    assert point_id("notes/Beta.md", 0) not in store.points
    assert store.notes() == {"Alpha.md": 2, "archive/Beta renamed.md": 1}


async def test_reindexes_everything_in_full_mode(ingestor: Ingestor) -> None:
    await ingestor.run("incremental")
    report = await ingestor.run("full")
    assert (report.notes.indexed, report.notes.unchanged) == (2, 0)


async def test_reindexes_notes_indexed_with_another_version(
    ingestor: Ingestor, vault: Vault, embedder: FakeEmbedder, store: InMemoryStore
) -> None:
    await ingestor.run("incremental")
    other = Ingestor(str(vault.root), embedder, store, 500)
    assert other.index_version != ingestor.index_version
    assert (await other.run("incremental")).notes.indexed == 2


async def test_keeps_the_previous_version_of_a_note_when_its_embedding_fails(
    ingestor: Ingestor, embedder: FakeEmbedder, store: InMemoryStore, vault: Vault
) -> None:
    await ingestor.run("incremental")
    vault.write("notes/Beta.md", "# Beta\nPOISON")
    embedder.fail_on = lambda text: "POISON" in text

    report = await ingestor.run("incremental")

    assert (report.notes.indexed, report.notes.failed) == (0, 1)
    assert [error.model_dump() for error in report.errors] == [{"path": "notes/Beta.md", "message": "embedding failed"}]
    assert store.points[point_id("notes/Beta.md", 0)].payload["text"] == "Beta content #idea"
    # A later run retries it because its hash still differs.
    embedder.fail_on = None
    assert (await ingestor.run("incremental")).notes.indexed == 1


async def test_stops_early_when_the_embedding_service_is_down_and_resumes_next_run(
    ingestor: Ingestor, embedder: FakeEmbedder, store: InMemoryStore, vault: Vault, monkeypatch: pytest.MonkeyPatch
) -> None:
    await ingestor.run("incremental")
    alpha_hash = {n.path: n.hash for n in await store.list_indexed_notes()}["Alpha.md"]
    # Sorted before the new notes, so it is among the failed ones.
    vault.write("Alpha.md", "# Alpha\nEdited while Ollama is down.")
    for i in range(6):
        vault.write(f"batch/note-{i}.md", f"# Note {i}\ncontent {i}")

    async def ollama_down(texts: list[str]) -> list[list[float]]:
        raise UpstreamError("ollama", "request to /api/embed failed: ConnectError")

    with monkeypatch.context() as patch:
        patch.setattr(embedder, "embed_documents", ollama_down)
        report = await ingestor.run("incremental")

    notes = report.notes
    assert (notes.indexed, notes.failed, notes.skipped, notes.unchanged) == (0, 3, 4, 1)
    assert report.aborted == "3 consecutive failures of ollama; 4 notes skipped, retried on the next run"
    # No hash is recorded for the notes that failed or were skipped: new notes
    # are absent from the index, the edited note keeps its old hash.
    indexed = {n.path: n.hash for n in await store.list_indexed_notes()}
    assert not [path for path in indexed if path.startswith("batch/")]
    assert indexed["Alpha.md"] == alpha_hash

    retry = await ingestor.run("incremental")
    assert (retry.notes.indexed, retry.notes.failed, retry.notes.skipped, retry.notes.unchanged) == (7, 0, 0, 1)
    assert retry.aborted is None
    assert store.points[point_id("Alpha.md", 0)].payload["text"] == "Edited while Ollama is down."
    assert len([path for path in store.notes() if path.startswith("batch/")]) == 6


async def test_does_not_stop_on_failures_specific_to_each_note(
    ingestor: Ingestor, embedder: FakeEmbedder, vault: Vault
) -> None:
    await ingestor.run("incremental")
    for i in range(5):
        vault.write(f"bad/note-{i}.md", f"# Bad {i}\nPOISON")
    embedder.fail_on = lambda text: "POISON" in text

    report = await ingestor.run("incremental")

    assert (report.notes.failed, report.notes.skipped, report.aborted) == (5, 0, None)


async def test_refuses_a_second_run_while_one_is_in_progress(ingestor: Ingestor) -> None:
    first = asyncio.create_task(ingestor.run("full"))
    await asyncio.sleep(0)
    with pytest.raises(IngestInProgressError):
        await ingestor.run("full")
    await first
    assert not ingestor.is_running


def test_point_id_is_a_deterministic_rfc4122_uuid_per_path_and_chunk() -> None:
    id_ = point_id("a.md", 0)
    assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", id_)
    assert point_id("a.md", 0) == id_
    assert id_ not in (point_id("a.md", 1), point_id("b.md", 0))


def test_embedding_text_prefixes_the_chunk_with_its_title_and_section() -> None:
    assert embedding_text("Note", "A > B", "text") == "Note > A > B\n\ntext"
    assert embedding_text("Note", "", "text") == "Note\n\ntext"


@pytest.fixture
def graph(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Graph]:
    graph = Graph(tmp_path_factory.mktemp("state") / "graph.lbug")
    yield graph
    graph.close()


async def test_rebuilds_the_graph_of_the_whole_vault_on_every_run(
    vault: Vault, embedder: FakeEmbedder, store: InMemoryStore, graph: Graph
) -> None:
    vault.write("Alpha.md", "# Alpha\n[[Beta]] [[Gamma]] ![[photo.png]] #projet/nyansa")
    vault.write("notes/Beta.md", "# Beta")
    ingestor = Ingestor(str(vault.root), embedder, store, 200, graph)

    report = await ingestor.run("incremental")
    assert report.graph == GraphCounts(notes=2, ghosts=1, links=2, tags=2)
    assert report.graph_error is None

    # Nothing to reindex, but the graph follows the vault: Gamma now exists.
    vault.write("Gamma.md", "# Gamma")
    embedder.fail_on = lambda text: True
    report = await ingestor.run("incremental")
    assert (report.notes.failed, report.graph) == (1, GraphCounts(notes=3, ghosts=0, links=2, tags=2))
    assert [link["path"] for link in graph.note("Alpha.md")["links"]] == ["Gamma.md", "notes/Beta.md"]  # type: ignore[index]


async def test_indexes_the_notes_when_the_graph_is_unavailable(
    vault: Vault, embedder: FakeEmbedder, store: InMemoryStore, tmp_path_factory: pytest.TempPathFactory
) -> None:
    vault.write("Alpha.md", "# Alpha\n[[Beta]]")
    path = tmp_path_factory.mktemp("state") / "graph.lbug"
    holder = hold(path)
    try:
        report = await Ingestor(str(vault.root), embedder, store, 200, Graph(path)).run("incremental")
    finally:
        holder.kill()
        holder.wait()
    assert (report.notes.indexed, report.graph) == (1, None)
    assert report.graph_error is not None
    assert "Could not set lock" in report.graph_error


async def test_builds_a_missing_or_empty_graph_at_startup_without_ollama_or_qdrant(
    vault: Vault, embedder: FakeEmbedder, store: InMemoryStore, graph: Graph
) -> None:
    vault.write("Alpha.md", "# Alpha\n[[Beta]] #projet")
    vault.write("notes/Beta.md", "# Beta")
    ingestor = Ingestor(str(vault.root), embedder, store, 200, graph)

    # No graph file yet: built from the vault alone, nothing embedded or stored.
    assert await ingestor.build_graph_if_empty() == GraphCounts(notes=2, ghosts=0, links=1, tags=1)
    assert (embedder.documents_embedded, store.points) == (0, {})

    # Already built: left as it is, even if the vault changed since.
    vault.write("Gamma.md", "# Gamma")
    assert await ingestor.build_graph_if_empty() is None
    assert graph.stats()["notes"] == 2


async def test_builds_the_graph_at_startup_after_an_unreadable_file_was_recreated(
    vault: Vault, embedder: FakeEmbedder, store: InMemoryStore, tmp_path_factory: pytest.TempPathFactory
) -> None:
    vault.write("Alpha.md", "# Alpha")
    path = tmp_path_factory.mktemp("state") / "graph.lbug"
    path.write_bytes(b"not a graph" * 1000)
    graph = Graph(path)
    try:
        built = await Ingestor(str(vault.root), embedder, store, 200, graph).build_graph_if_empty()
        assert built == GraphCounts(notes=1, ghosts=0, links=0, tags=0)
    finally:
        graph.close()
