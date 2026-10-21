# ADR-0008: memory-api in TypeScript

- **Status:** Superseded by [ADR-0011](0011-memory-api-in-python.md)
- **Date:** 2026-09-26 (merged with phase 2 on 2026-09-28)

## Context

Phase 2 added a RAG service of its own, `services/memory-api`: parse the
Obsidian notes (frontmatter, tags, wikilinks), split them along their
headings, embed them with `nomic-embed-text` through Ollama and store them
in Qdrant, incrementally, behind `/ingest`, `/search` and `/health`. The
phase plan asked for TypeScript (Node.js, Fastify or Hono, strict typing)
and Vitest tests with Ollama and Qdrant mocked.

## Decision

memory-api was written in TypeScript on Node 24, with Fastify, Zod and
Vitest, strict compiler options (`noUncheckedIndexedAccess`,
`exactOptionalPropertyTypes`), and every dependency pinned.

## Alternatives considered

- **Hono instead of Fastify, or another language**: not compared in depth.
  TypeScript and Fastify were chosen by default at implementation time: the
  Node environment was available and the project was at the proof-of-concept
  stage.

## Consequences

- The ingestion design of this version is still the one in use: chunks
  along headings, incremental indexing from content hashes, state in the
  first chunk of each note, deterministic point ids, a stop after 3
  consecutive upstream failures.
- Its point ids and index version were recorded as reference values
  (`tests/golden`) before the code was removed, so the Python port kept the
  existing Qdrant index.
- Superseded on 2026-10-19 by ADR-0011: the TypeScript code was removed
  (`9c4fee7`). Releases built before that date still run their TypeScript
  image on a rollback.

## References

- `636dcc5`, `e3dfd23` to `654090e`, `fc59190`; phase 2 merged in `b610103`.
- `services/memory-api/tests/golden`, `services/memory-api/README.md`.
