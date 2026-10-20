from src.context import build_context
from src.domain import ChunkPayload, SearchHit


def hit(path: str, chunk_index: int, score: float, text: str, section: str = "") -> SearchHit:
    payload = ChunkPayload(
        path=path,
        title=path.removesuffix(".md").title(),
        tags=[],
        links=[],
        section=section,
        chunk_index=chunk_index,
        chunk_count=3,
        text=text,
        note_hash="h",
        index_version="v",
        indexed_at="2026-10-20T00:00:00.000Z",
    )
    return SearchHit(score, payload)


def test_numbers_notes_by_their_best_hit_and_groups_their_chunks() -> None:
    hits = [
        hit("docker.md", 2, 0.9, "Compose runs the stack.", "Docker > Compose"),
        hit("backup.md", 0, 0.8, "Backups run nightly."),
        hit("docker.md", 0, 0.7, "Docker is installed.", "Docker"),
    ]

    context = build_context("how do I run the stack?", hits, max_chars=1000)

    assert context.found
    assert [(s.n, s.path, s.title, s.sections, s.score) for s in context.sources] == [
        (1, "docker.md", "Docker", ["Docker > Compose", "Docker"], 0.9),
        (2, "backup.md", "Backup", [""], 0.8),
    ]
    # Chunks of a note are quoted in their order in the note.
    assert context.context == (
        '<note number="1">\n'
        "Section: Docker\nDocker is installed.\n\n"
        "Section: Docker > Compose\nCompose runs the stack.\n"
        "</note>\n"
        '<note number="2">\n'
        "Backups run nightly.\n"
        "</note>"
    )


def test_stays_under_the_size_limit_but_keeps_the_best_chunk() -> None:
    hits = [hit("a.md", 0, 0.9, "a" * 300), hit("b.md", 0, 0.8, "b" * 300), hit("c.md", 0, 0.7, "c" * 100)]

    context = build_context("q", hits, max_chars=450)

    assert [s.path for s in context.sources] == ["a.md", "c.md"]
    assert [s.n for s in context.sources] == [1, 2]
    assert build_context("q", [hit("big.md", 0, 0.9, "x" * 900)], max_chars=450).found


def test_nothing_relevant_means_not_found() -> None:
    context = build_context("q", [], max_chars=1000)
    assert (context.found, context.sources, context.context) == (False, [], "")
