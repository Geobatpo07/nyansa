import hashlib
import subprocess
import sys
import unicodedata
from collections.abc import Iterator
from pathlib import Path

import pytest

from src.graph import Graph, GraphUnavailableError, build_graph
from src.markdown import parse_note


def graph_of(notes: dict[str, str]) -> tuple[set[tuple[str, str]], set[str]]:
    """(links, ghost notes) of a vault given as path -> content."""
    data = build_graph([parse_note(path, content) for path, content in notes.items()])
    return {(link["source"], link["target"]) for link in data.links}, {n["path"] for n in data.notes if n["ghost"]}


def test_resolves_wikilinks_like_obsidian() -> None:
    links, ghosts = graph_of(
        {
            "Index.md": "[[beta]] [[Projets/Alpha|the alpha]] [[Gamma#Setup]] ![[Delta]] [[Index]] [[#Local]]",
            "Projets/Alpha.md": "",
            "Projets/Beta.md": "",
            "Archives/Old/Beta.md": "",
            "Notes/Gamma.md": "",
            "Delta.md": "",
        }
    )
    assert links == {
        # Shortest path among the notes named Beta, case-insensitive.
        ("Index.md", "Projets/Beta.md"),
        ("Index.md", "Projets/Alpha.md"),
        ("Index.md", "Notes/Gamma.md"),
        # An embedded note is a link; a link to itself or to a heading of itself is not.
        ("Index.md", "Delta.md"),
    }
    assert ghosts == set()


def test_a_partial_path_targets_the_shortest_note_ending_with_it() -> None:
    links, _ = graph_of({"a.md": "[[Old/Beta]]", "Archives/Old/Beta.md": "", "Deep/Archives/Old/Beta.md": ""})
    assert links == {("a.md", "Archives/Old/Beta.md")}


def test_missing_notes_become_ghosts_but_attachments_do_not() -> None:
    links, ghosts = graph_of(
        {
            "a.md": (
                "[[Idée future]] [[idée FUTURE]] [[Dossier/Plus tard]] [[Version 2.0]]\n"
                "![[photo.png]] ![[doc.pdf]] [[schema.excalidraw]] [[Dossier/Plan.canvas]]"
            )
        }
    )
    assert ghosts == {"Idée future.md", "Dossier/Plus tard.md", "Version 2.0.md"}
    assert links == {("a.md", ghost) for ghost in ghosts}


def test_links_in_code_are_ignored() -> None:
    links, ghosts = graph_of(
        {"a.md": "`[[b]]` and `[x](b.md)`\n```\n[[b]] [x](b.md)\n```\n    [[c]]\n", "b.md": "", "c.md": ""}
    )
    # Indented code is not detected: Obsidian vaults rarely use it, the parser only knows fences.
    assert (links, ghosts) == ({("a.md", "c.md")}, set())


def test_resolves_markdown_links() -> None:
    links, ghosts = graph_of(
        {
            "Projets/Index.md": (
                "[relative](Nyansa.md) [up](../Recettes/Pain%20au%20levain.md) [spaces](<../Sport/Course à pied.md>)\n"
                '[root](/Voyages/Lisbonne.md "title") [by name](Lisbonne.md#Jour 1) [missing](Plus%20tard.md)\n'
                "[web](https://example.org/a.md) [mail](mailto:x@example.org) [anchor](#Top) [image](photo.png)"
            ),
            "Projets/Nyansa.md": "",
            "Recettes/Pain au levain.md": "",
            "Sport/Course à pied.md": "",
            "Voyages/Lisbonne.md": "",
        }
    )
    assert links == {
        ("Projets/Index.md", "Projets/Nyansa.md"),
        ("Projets/Index.md", "Recettes/Pain au levain.md"),
        ("Projets/Index.md", "Sport/Course à pied.md"),
        ("Projets/Index.md", "Voyages/Lisbonne.md"),
        ("Projets/Index.md", "Projets/Plus tard.md"),
    }
    assert ghosts == {"Projets/Plus tard.md"}


def test_accents_match_whatever_their_unicode_form() -> None:
    nfd = unicodedata.normalize("NFD", "Sport/Course à pied.md")
    links, ghosts = graph_of({nfd: "[[Idée]]", "Idée.md": "[[course à pied]]"})
    assert links == {("Sport/Course à pied.md", "Idée.md"), ("Idée.md", "Sport/Course à pied.md")}
    assert ghosts == set()


def test_nested_tags_link_to_their_parents() -> None:
    data = build_graph([parse_note("a.md", "#projet/nyansa/api #perso")])
    assert data.tags == ["perso", "projet", "projet/nyansa", "projet/nyansa/api"]
    assert data.subtags == [
        {"tag": "projet/nyansa", "parent": "projet"},
        {"tag": "projet/nyansa/api", "parent": "projet/nyansa"},
    ]
    assert data.tagged == [{"note": "a.md", "tag": "perso"}, {"note": "a.md", "tag": "projet/nyansa/api"}]


VAULT = {
    "Projets/Nyansa.md": "---\ntags: [projet/nyansa]\n---\n# Nyansa\n[[Docker]] [[Backup]] [[Plus tard]]",
    "Infra/Docker.md": "# Docker\n#infra [[Backup]]",
    "Infra/Backup.md": "# Backup\n#infra #projet",
    "Sport/Course à pied.md": "# Course à pied\n#projet/sport",
    "Seule.md": "# Seule",
}


@pytest.fixture
def graph(tmp_path: Path) -> Iterator[Graph]:
    graph = Graph(tmp_path / "state" / "graph.lbug")
    graph.replace(build_graph([parse_note(path, content) for path, content in VAULT.items()]))
    yield graph
    graph.close()


def test_a_note_with_its_links_backlinks_tags_and_related_notes(graph: Graph) -> None:
    assert graph.note("Infra/Backup.md") == {
        "path": "Infra/Backup.md",
        "title": "Backup",
        "ghost": False,
        "tags": ["infra", "projet"],
        "links": [],
        "backlinks": [
            {"path": "Infra/Docker.md", "title": "Docker", "ghost": False},
            {"path": "Projets/Nyansa.md", "title": "Nyansa", "ghost": False},
        ],
        "related": [
            {"path": "Infra/Docker.md", "title": "Docker", "sharedTags": ["infra"]},
            {"path": "Projets/Nyansa.md", "title": "Nyansa", "sharedTags": ["projet"]},
            {"path": "Sport/Course à pied.md", "title": "Course à pied", "sharedTags": ["projet"]},
        ],
    }
    nyansa = graph.note(unicodedata.normalize("NFD", "Projets/Nyansa.md"))
    assert nyansa is not None
    assert [(n["path"], n["ghost"]) for n in nyansa["links"]] == [
        ("Infra/Backup.md", False),
        ("Infra/Docker.md", False),
        ("Plus tard.md", True),
    ]
    assert graph.note("Course à pied.md") is None


def test_neighbors_within_one_or_two_links(graph: Graph) -> None:
    one = graph.neighbors("Infra/Docker.md", 1)
    assert one is not None
    assert [n["path"] for n in one["nodes"]] == ["Infra/Backup.md", "Infra/Docker.md", "Projets/Nyansa.md"]
    two = graph.neighbors("Infra/Docker.md", 2)
    assert two is not None
    assert {n["path"] for n in two["nodes"]} == {n["path"] for n in one["nodes"]} | {"Plus tard.md"}
    assert {"source": "Projets/Nyansa.md", "target": "Plus tard.md"} in two["edges"]
    assert graph.neighbors("Inconnue.md", 1) is None


def test_stats(graph: Graph) -> None:
    assert graph.stats() == {"notes": 5, "ghosts": 1, "links": 4, "tags": 4, "orphans": 2}


def test_linked_notes_of_the_chat_sources(graph: Graph) -> None:
    assert graph.linked({"Infra/Docker.md": 1, "Infra/Backup.md": 2}, limit=5) == [
        {"path": "Projets/Nyansa.md", "title": "Nyansa", "linkedTo": [1, 2]}
    ]
    assert graph.linked({"Seule.md": 1}, limit=5) == []


def test_a_rebuild_follows_a_renamed_note(graph: Graph) -> None:
    renamed = {**VAULT, "Infra/Sauvegarde.md": VAULT["Infra/Backup.md"]}
    del renamed["Infra/Backup.md"]
    graph.replace(build_graph([parse_note(path, content) for path, content in renamed.items()]))

    assert graph.note("Infra/Backup.md") is None
    assert [n["path"] for n in graph.note("Infra/Docker.md")["links"]] == ["Backup.md"]  # type: ignore[index]
    assert graph.stats()["ghosts"] == 2


def test_a_failed_rebuild_keeps_the_previous_graph(graph: Graph) -> None:
    data = build_graph([parse_note("a.md", "[[b]]")])
    data.notes.append(data.notes[0])  # duplicated primary key: fails inside the transaction
    with pytest.raises(RuntimeError):
        graph.replace(data)
    assert graph.stats()["notes"] == 5


# Opening the graph from another process, as a second memory-api would.
HOLDER = """
import sys, time, ladybug
db = ladybug.Database(sys.argv[1])
conn = ladybug.Connection(db)
conn.execute("CREATE NODE TABLE IF NOT EXISTS Note(path STRING PRIMARY KEY, title STRING, ghost BOOL)")
conn.execute("MERGE (:Note {path: 'held.md', title: 'Held', ghost: false})")
print("ready", flush=True)
time.sleep(60)
"""


def hold(path: Path) -> subprocess.Popen[str]:
    holder = subprocess.Popen([sys.executable, "-c", HOLDER, str(path)], stdout=subprocess.PIPE, text=True)  # noqa: S603
    assert holder.stdout is not None
    assert holder.stdout.readline().strip() == "ready"
    return holder


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_graph_locked_by_another_process_is_never_deleted(tmp_path: Path) -> None:
    path = tmp_path / "graph.lbug"
    holder = hold(path)
    try:
        before = digest(path)
        graph = Graph(path)
        with pytest.raises(GraphUnavailableError, match="Could not set lock"):
            graph.open()
        with pytest.raises(GraphUnavailableError):
            graph.stats()
        assert digest(path) == before
    finally:
        holder.kill()
        holder.wait()
    # Released: the next call opens it, with the other process's data.
    assert graph.note("held.md") is not None
    graph.close()


def test_a_killed_owner_does_not_block_the_next_one(tmp_path: Path) -> None:
    path = tmp_path / "graph.lbug"
    holder = hold(path)
    holder.kill()  # SIGKILL on Linux, TerminateProcess on Windows: no cleanup runs.
    holder.wait()
    graph = Graph(path)
    assert graph.note("held.md") is not None
    graph.close()


def test_an_unreadable_graph_is_rebuilt_and_nothing_else_is_touched(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    (state / "graph.lbug").write_bytes(b"not a graph" * 1000)
    (state / "memory-api.db").write_bytes(b"jobs")
    (state / "graph.lbug.backup").write_bytes(b"kept")

    graph = Graph(state / "graph.lbug")
    assert graph.stats()["notes"] == 0
    graph.close()
    assert (state / "memory-api.db").read_bytes() == b"jobs"
    assert (state / "graph.lbug.backup").read_bytes() == b"kept"


def test_an_unknown_failure_keeps_the_file(tmp_path: Path) -> None:
    # A directory where the graph file should be: not a damaged graph, so not deleted.
    (tmp_path / "graph.lbug").mkdir()
    (tmp_path / "graph.lbug" / "data").write_bytes(b"x")
    with pytest.raises(GraphUnavailableError, match="cannot open"):
        Graph(tmp_path / "graph.lbug").open()
    assert (tmp_path / "graph.lbug" / "data").exists()
