"""In-memory stand-ins for Ollama and Qdrant, and a temporary vault.

The fakes follow the same protocols as the real adapters, so the ingestion
and search logic run unchanged.
"""

import math
import re
from collections.abc import Callable
from pathlib import Path

import pytest

from memory_api.domain import ChunkPoint, IndexedNote, SearchHit

DIMENSIONS = 64


class FakeEmbedder:
    """Bag-of-words embedding: each word lands in one of 64 buckets.

    Texts that share words get similar vectors, which is enough to test ranking.
    """

    model = "fake-embed"

    def __init__(self) -> None:
        self.documents_embedded = 0
        self.fail_on: Callable[[str], bool] | None = None

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.documents_embedded += len(texts)
        if self.fail_on and any(self.fail_on(text) for text in texts):
            raise RuntimeError("embedding failed")
        return [_embed(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        return _embed(text)

    async def health(self) -> None:
        pass


def _embed(text: str) -> list[float]:
    vector = [0.0] * DIMENSIONS
    for word in re.findall(r"[^\W_]+", text.lower()):
        word_hash = 0
        for char in word:
            word_hash = (word_hash * 31 + ord(char)) & 0xFFFFFFFF
        vector[word_hash % DIMENSIONS] += 1
    return vector


class InMemoryStore:
    def __init__(self) -> None:
        self.points: dict[str, ChunkPoint] = {}
        self.dimensions: int | None = None

    async def ensure_collection(self, dimensions: int) -> None:
        if self.dimensions not in (None, dimensions):
            raise RuntimeError("dimension mismatch")
        self.dimensions = dimensions

    async def list_indexed_notes(self) -> list[IndexedNote]:
        return [
            IndexedNote(p.payload["path"], p.payload["note_hash"], p.payload["index_version"])
            for p in self.points.values()
            if p.payload["chunk_index"] == 0
        ]

    async def upsert_chunks(self, points: list[ChunkPoint]) -> None:
        self.points.update((point.id, point) for point in points)

    async def delete_note(self, path: str, from_chunk_index: int = 0) -> None:
        self.points = {
            id_: p
            for id_, p in self.points.items()
            if not (p.payload["path"] == path and p.payload["chunk_index"] >= from_chunk_index)
        }

    async def search(
        self, vector: list[float], limit: int, tags: list[str] | None = None, min_score: float | None = None
    ) -> list[SearchHit]:
        hits = [
            SearchHit(_cosine(vector, p.vector), p.payload)
            for p in self.points.values()
            if tags is None or any(tag in p.payload["tags"] for tag in tags)
        ]
        hits = [hit for hit in hits if min_score is None or hit.score >= min_score]
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:limit]

    async def health(self) -> None:
        pass

    def notes(self) -> dict[str, int]:
        """Paths currently indexed, with their chunk count."""
        counts: dict[str, int] = {}
        for point in self.points.values():
            counts[point.payload["path"]] = counts.get(point.payload["path"], 0) + 1
        return counts


def _cosine(a: list[float], b: list[float]) -> float:
    norm = math.hypot(*a) * math.hypot(*b)
    return sum(x * y for x, y in zip(a, b, strict=True)) / norm if norm else 0.0


class Vault:
    """Temporary vault on disk."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def write(self, path: str, content: str) -> None:
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content, encoding="utf-8", newline="")

    def remove(self, path: str) -> None:
        (self.root / path).unlink()


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    return Vault(tmp_path)
