# ADR-0009: The incremental indexing state lives in Qdrant itself

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

Phase 2 required incremental indexing: reindex only the notes whose content
changed (by hash), and remove the points of deleted notes. Embedding is the
slow step (about 2 chunks per second on a CPU), so an unchanged note must
not be embedded again, including after a change of chunk size or embedding
model, which must reindex everything.

## Decision

The index records its own state: every chunk's payload carries its note's
content hash and an `index_version` (derived from the chunker version, the
embedding model and the chunk size), and each run compares the vault with
the first chunk of every indexed note. Point ids are UUIDs derived from the
note path and the chunk index.

## Alternatives considered

- **A separate state store (file or database) of indexed notes**: a second
  database to keep in sync with Qdrant.

## Consequences

- Reindexing a note overwrites its points (same ids); chunks beyond the new
  count are deleted afterwards, so the note is never missing from the index.
- The first chunk, which carries the hash, is written last (`b0fb263`): a
  run stopped in the middle of a note leaves its old hash, and the next run
  indexes it again.
- Changing `EMBEDDING_MODEL` or `CHUNK_MAX_CHARS` changes `index_version`
  and reindexes every note.
- The ids and `index_version` became a compatibility contract: the Python
  port reproduces them exactly, checked by golden tests (ADR-0011).
- The ingestion tasks' history is a separate matter, kept in SQLite
  (ADR-0012). Phase 4b adds the extractor's name and version to the
  reindexing decision for PDFs (ADR-0021).

## References

- `a5ede3f`, `2296c87`, `fc59190`, `b0fb263`.
- `services/memory-api/src/ingest.py` (`plan_ingest`, `point_id`),
  `services/memory-api/README.md` (section "How it works").
