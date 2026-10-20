"""Graph of the vault: notes, links and tags, in an embedded LadybugDB file.

The graph is derived from the vault and rebuilt whole at the end of every
ingestion, so an unreadable file can be deleted and rebuilt without losing
anything. LadybugDB takes an exclusive lock on the file: only one process
(this service, with a single worker) opens it.
"""

import logging
import posixpath
import re
import threading
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote

import ladybug

from .domain import ParsedNote

log = logging.getLogger(__name__)

_SCHEMA = [
    # ghost: target of a link to a note that does not exist (yet).
    "CREATE NODE TABLE IF NOT EXISTS Note(path STRING PRIMARY KEY, title STRING, ghost BOOL)",
    "CREATE NODE TABLE IF NOT EXISTS Tag(name STRING PRIMARY KEY)",
    "CREATE REL TABLE IF NOT EXISTS LINKS_TO(FROM Note TO Note)",
    "CREATE REL TABLE IF NOT EXISTS TAGGED(FROM Note TO Tag)",
    # `projet/nyansa` -> `projet`.
    "CREATE REL TABLE IF NOT EXISTS SUBTAG_OF(FROM Tag TO Tag)",
]
# ponytail: no schema migration. A change to _SCHEMA must drop the old tables
# (or rename the file); the next ingestion fills the new ones.

# LadybugDB raises RuntimeError for everything; the message tells why. Only
# these messages mean the file itself is unreadable and may be deleted. Any
# other failure, the lock held by another process first, leaves it untouched.
_LOCKED = "Could not set lock on file"
_UNREADABLE = re.compile(
    r"not a valid Lbug database file|may be corrupted|is corrupted|Corrupted wal|"
    r"WAL replay encountered|Cannot read checkpoint|with a different version|please recreate it"
)
# Files LadybugDB keeps next to the database file.
_SIDE_FILES = (".wal", ".shadow")


class GraphUnavailableError(Exception):
    """The graph cannot be opened (held by another process, permissions, unknown error)."""


@dataclass
class GraphData:
    """Rows to load: the whole graph, built from the parsed notes."""

    notes: list[dict[str, Any]] = field(default_factory=list)
    links: list[dict[str, str]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    tagged: list[dict[str, str]] = field(default_factory=list)
    subtags: list[dict[str, str]] = field(default_factory=list)


def note_key(path: str) -> str:
    """Key of a note in the graph: its vault path in NFC, as macOS may write file names in NFD."""
    return unicodedata.normalize("NFC", path)


def build_graph(notes: list[ParsedNote]) -> GraphData:
    """Resolves the links of every note, like Obsidian, and lists the graph rows.

    - `[[Name]]` targets the note `Name.md` wherever it is, case-insensitively;
      when several notes share the name, the shortest path wins.
    - `[[folder/Name]]` targets that path, or the shortest path ending with it.
    - `[text](folder/Name.md)` is resolved from the note's folder, then from
      the vault root, then by name. URLs and links to other files are ignored.
    - A link to a missing note creates a ghost note; a link to an attachment
      (`![[image.png]]`, any target with a file extension) creates nothing.
    """
    keys = {note.path: note_key(note.path) for note in notes}
    by_path = {_stem(key).lower(): key for key in keys.values()}
    by_name: dict[str, list[str]] = {}
    for key in sorted(keys.values(), key=lambda key: (len(key), key)):
        by_name.setdefault(PurePosixPath(_stem(key)).name.lower(), []).append(key)

    def resolve(target: str) -> str | None:
        wanted = note_key(target).strip("/").lower()
        if wanted in by_path:
            return by_path[wanted]
        if "/" not in wanted:
            return next(iter(by_name.get(wanted, [])), None)
        suffix = "/" + wanted
        return min((key for stem, key in by_path.items() if stem.endswith(suffix)), key=len, default=None)

    data = GraphData(notes=[{"path": keys[n.path], "title": n.title, "ghost": False} for n in notes])
    ghosts: dict[str, str] = {}
    links: set[tuple[str, str]] = set()
    for note in notes:
        source = keys[note.path]
        for target, ghost in _targets(note, resolve):
            if target is None:
                if ghost is None:
                    continue
                target = ghosts.setdefault(ghost.lower(), ghost + ".md")
            if target != source:
                links.add((source, target))
        for tag in note.tags:
            data.tagged.append({"note": source, "tag": tag})

    data.notes += [{"path": path, "title": _stem(PurePosixPath(path).name), "ghost": True} for path in ghosts.values()]
    data.links = [{"source": source, "target": target} for source, target in sorted(links)]
    tags: set[str] = set()
    subtags: set[tuple[str, str]] = set()
    for tag in {tag for note in notes for tag in note.tags}:
        tags.add(tag)
        while (parent := tag.rpartition("/")[0]) != "":
            subtags.add((tag, parent))
            tags.add(parent)
            tag = parent
    data.tags = sorted(tags)
    data.subtags = [{"tag": tag, "parent": parent} for tag, parent in sorted(subtags)]
    return data


def _targets(note: ParsedNote, resolve: Callable[[str], str | None]) -> list[tuple[str | None, str | None]]:
    """(resolved note key, or None and the ghost to create, or None and None to ignore) per link."""
    targets: list[tuple[str | None, str | None]] = []
    for link in note.links:
        resolved = resolve(link.target)
        targets.append((resolved, None if resolved or _is_file(link.target) else note_key(link.target).strip("/")))
    folder = posixpath.dirname(note_key(note.path))
    for href in note.markdown_links:
        target = _markdown_target(href)
        if target is None:
            continue
        relative = posixpath.normpath(posixpath.join(folder, target))
        resolved = (None if relative.startswith("../") else resolve(relative)) or resolve(target)
        if resolved is None and "/" not in target:
            resolved = resolve(PurePosixPath(target).name)
        targets.append((resolved, None if resolved else (target if relative.startswith("../") else relative)))
    return targets


def _markdown_target(href: str) -> str | None:
    """The note a Markdown link points to, without `.md`; None for URLs, anchors and other files."""
    if re.match(r"[A-Za-z][\w+.-]*:", href):
        return None
    path = unquote(re.split(r"[#?]", href, maxsplit=1)[0])
    if not path.lower().endswith(".md"):
        return None
    return _stem(path) or None


def _is_file(target: str) -> bool:
    """True for `image.png`, `doc.pdf`: a target with a file extension is not a note."""
    extension = PurePosixPath(target).suffix[1:]
    return 0 < len(extension) <= 10 and extension.isalnum() and not extension.isdigit()


def _stem(path: str) -> str:
    return path[:-3] if path.lower().endswith(".md") else path


class Graph:
    """The graph file, opened lazily and kept open.

    Every call runs under one lock: LadybugDB calls block, so the API runs
    them in a worker thread, one at a time.
    """

    # ponytail: one lock for reads and the rebuild; reads wait for a rebuild
    # (1.2 s for 2,000 notes and 6,000 links). A read-only connection if that matters.

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._db: ladybug.Database | None = None
        self._conn: ladybug.Connection | None = None

    def open(self) -> None:
        """Opens the graph now; raises GraphUnavailableError like every other call."""
        with self._lock:
            self._connection()

    def close(self) -> None:
        """Releases the file and its lock."""
        with self._lock:
            self._close()

    def replace(self, data: GraphData) -> None:
        """Replaces the whole graph in one transaction: readers see the old or the new graph."""
        with self._lock:
            conn = self._connection()
            conn.execute("BEGIN TRANSACTION")
            try:
                conn.execute("MATCH (n) DETACH DELETE n")
                conn.execute(
                    "UNWIND $rows AS r CREATE (:Note {path: r.path, title: r.title, ghost: r.ghost})",
                    {"rows": data.notes},
                )
                conn.execute("UNWIND $rows AS r CREATE (:Tag {name: r})", {"rows": data.tags})
                conn.execute(
                    "UNWIND $rows AS r MATCH (a:Note {path: r.source}), (b:Note {path: r.target}) "
                    "CREATE (a)-[:LINKS_TO]->(b)",
                    {"rows": data.links},
                )
                conn.execute(
                    "UNWIND $rows AS r MATCH (n:Note {path: r.note}), (t:Tag {name: r.tag}) CREATE (n)-[:TAGGED]->(t)",
                    {"rows": data.tagged},
                )
                conn.execute(
                    "UNWIND $rows AS r MATCH (t:Tag {name: r.tag}), (p:Tag {name: r.parent}) "
                    "CREATE (t)-[:SUBTAG_OF]->(p)",
                    {"rows": data.subtags},
                )
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    def note(self, path: str) -> dict[str, Any] | None:
        """A note with its links, backlinks, tags and the notes that share its tags; None if unknown."""
        key = note_key(path)
        with self._lock:
            rows = self._rows("MATCH (n:Note {path: $p}) RETURN n.path, n.title, n.ghost", p=key)
            if not rows:
                return None
            [(path, title, ghost)] = rows
            return {
                "path": path,
                "title": title,
                "ghost": ghost,
                "tags": [tag for (tag,) in self._rows("MATCH (:Note {path: $p})-[:TAGGED]->(t) RETURN t.name", p=key)],
                "links": _notes(
                    self._rows("MATCH (:Note {path: $p})-[:LINKS_TO]->(o) RETURN o.path, o.title, o.ghost", p=key)
                ),
                "backlinks": _notes(
                    self._rows("MATCH (:Note {path: $p})<-[:LINKS_TO]-(o) RETURN o.path, o.title, o.ghost", p=key)
                ),
                # Tags count with their parents: `projet/a` and `projet/b` share `projet`.
                "related": [
                    {"path": path, "title": title, "sharedTags": sorted(shared)}
                    for path, title, shared in self._rows(
                        "MATCH (n:Note {path: $p})-[:TAGGED]->(:Tag)-[:SUBTAG_OF*0..10]->(t:Tag)"
                        "<-[:SUBTAG_OF*0..10]-(:Tag)<-[:TAGGED]-(o:Note) WHERE o.path <> n.path "
                        "WITH o, collect(DISTINCT t.name) AS shared "
                        "RETURN o.path, o.title, shared ORDER BY size(shared) DESC, o.path LIMIT 10",
                        p=key,
                    )
                ],
            }

    def neighbors(self, path: str, depth: int) -> dict[str, Any] | None:
        """The notes within `depth` links of a note (either direction) and the links between them."""
        if depth not in (1, 2):
            raise ValueError("depth must be 1 or 2")
        key = note_key(path)
        with self._lock:
            if not self._rows("MATCH (n:Note {path: $p}) RETURN n.path", p=key):
                return None
            around = self._rows(
                f"MATCH (n:Note {{path: $p}})-[:LINKS_TO*1..{depth}]-(o:Note) RETURN DISTINCT o.path", p=key
            )
            paths = [key, *(other for (other,) in around if other != key)]
            nodes = self._rows("MATCH (n:Note) WHERE n.path IN $paths RETURN n.path, n.title, n.ghost", paths=paths)
            edges = self._rows(
                "MATCH (a:Note)-[:LINKS_TO]->(b:Note) WHERE a.path IN $paths AND b.path IN $paths "
                "RETURN a.path, b.path ORDER BY a.path, b.path",
                paths=paths,
            )
            return {
                "path": key,
                "depth": depth,
                "nodes": _notes(nodes),
                "edges": [{"source": source, "target": target} for source, target in edges],
            }

    def stats(self) -> dict[str, int]:
        with self._lock:
            [(notes, ghosts)] = self._rows(
                "MATCH (n:Note) RETURN count(CASE WHEN NOT n.ghost THEN 1 END), count(CASE WHEN n.ghost THEN 1 END)"
            )
            [(links,)] = self._rows("MATCH ()-[l:LINKS_TO]->() RETURN count(l)")
            [(tags,)] = self._rows("MATCH (t:Tag) RETURN count(t)")
            [(orphans,)] = self._rows(
                "MATCH (n:Note) WHERE NOT n.ghost AND NOT EXISTS { MATCH (n)-[:LINKS_TO]-() } RETURN count(n)"
            )
            return {"notes": notes, "ghosts": ghosts, "links": links, "tags": tags, "orphans": orphans}

    def linked(self, sources: dict[str, int], limit: int) -> list[dict[str, Any]]:
        """Existing notes linked to or from the given notes (path -> source number), the given ones excluded.

        Ranked by the number of given notes they are linked with, then by the best of those.
        """
        keys = {note_key(path): n for path, n in sources.items()}
        with self._lock:
            rows = self._rows(
                "MATCH (s:Note)-[:LINKS_TO]-(o:Note) WHERE s.path IN $keys AND NOT o.ghost AND NOT o.path IN $keys "
                "RETURN o.path, o.title, collect(DISTINCT s.path)",
                keys=list(keys),
            )
        found = [
            {"path": path, "title": title, "linkedTo": sorted(keys[s] for s in linked)} for path, title, linked in rows
        ]
        found.sort(key=lambda note: (-len(note["linkedTo"]), note["linkedTo"][0], note["path"]))
        return found[:limit]

    def _rows(self, query: str, **parameters: Any) -> list[list[Any]]:
        result = self._connection().execute(query, parameters)
        assert isinstance(result, ladybug.QueryResult)  # noqa: S101 # one statement, one result
        return [row for row in result.get_all() if isinstance(row, list)]

    def _connection(self) -> ladybug.Connection:
        if self._conn is not None:
            return self._conn
        try:
            return self._connect()
        except RuntimeError as err:
            message = str(err)
            if _LOCKED in message or not _UNREADABLE.search(message):
                raise GraphUnavailableError(f"cannot open the graph {self._path}: {message}") from None
            log.warning("the graph %s is unreadable (%s): deleting it, the next ingestion rebuilds it", self._path, err)
        # Only the graph file and its own side files, never the rest of the folder.
        for file in [self._path, *(self._path.with_name(self._path.name + side) for side in _SIDE_FILES)]:
            file.unlink(missing_ok=True)
        try:
            return self._connect()
        except RuntimeError as err:
            raise GraphUnavailableError(f"cannot recreate the graph {self._path}: {err}") from None

    def _connect(self) -> ladybug.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._db = ladybug.Database(str(self._path))
        try:
            self._conn = ladybug.Connection(self._db)
            for statement in _SCHEMA:
                self._conn.execute(statement)
            # Reads the data pages: some damage only shows on the first read.
            self._conn.execute("MATCH (n:Note) RETURN count(n)")
        except BaseException:
            self._close()
            raise
        return self._conn

    def _close(self) -> None:
        if self._conn is not None:
            self._conn.close()
        if self._db is not None:
            self._db.close()
        self._conn = self._db = None


def _notes(rows: list[list[Any]]) -> list[dict[str, Any]]:
    return sorted(({"path": path, "title": title, "ghost": ghost} for path, title, ghost in rows), key=_by_path)


def _by_path(note: dict[str, Any]) -> str:
    return str(note["path"])
