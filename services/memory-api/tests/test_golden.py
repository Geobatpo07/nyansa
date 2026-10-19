"""Parity with the first (TypeScript) implementation of memory-api.

golden/golden.json was produced by the TypeScript service from the notes in
golden/vault. Point ids, index_version, note hashes, titles, tags, links and
chunks must match, so an index built by the TypeScript service stays valid:
nothing is reindexed after the port.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from memory_api.ingest import CHUNKER_VERSION, embedding_text, point_id
from memory_api.markdown import chunk_note, parse_note
from memory_api.vault import read_vault, sha256

GOLDEN = Path(__file__).parent / "golden"
EXPECTED: dict[str, Any] = json.loads((GOLDEN / "golden.json").read_text(encoding="utf-8"))
NOTES = {note.path: note for note in read_vault(GOLDEN / "vault")}


def test_same_index_version() -> None:
    model = "nomic-embed-text"
    assert sha256(f"{CHUNKER_VERSION}|{model}|{EXPECTED['max_chars']}")[:12] == EXPECTED["index_version"]


def test_same_notes() -> None:
    assert sorted(NOTES) == sorted(note["path"] for note in EXPECTED["notes"])


@pytest.mark.parametrize("expected", EXPECTED["notes"], ids=lambda note: note["path"])
def test_same_note(expected: dict[str, Any]) -> None:
    file = NOTES[expected["path"]]
    note = parse_note(file.path, file.content)
    chunks = chunk_note(note.body, note.title, EXPECTED["max_chars"])

    assert (file.hash, file.encoding) == (expected["hash"], expected["encoding"])
    assert note.title == expected["title"]
    assert sorted(note.tags) == sorted(expected["tags"])
    assert [(link.target, link.embed, link.heading, link.alias) for link in note.links] == [
        (link["target"], link["embed"], link.get("heading"), link.get("alias")) for link in expected["links"]
    ]
    assert (note.frontmatter_error is not None) == expected["frontmatter_error"]
    assert [
        {
            "id": point_id(file.path, chunk.index),
            "section": chunk.section,
            "text": chunk.text,
            "embedding_text": embedding_text(note.title, chunk.section, chunk.text),
        }
        for chunk in chunks
    ] == expected["chunks"]
