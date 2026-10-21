# ADR-0017: LadybugDB for the graph of the vault

- **Status:** Accepted
- **Date:** 2026-10-20 (merged with phase 4 in `c3a29f3`)

## Context

Phase 4 asked for a graph of the notes (notes and tags as nodes; wikilinks,
backlinks and shared tags as edges), stored in the embedded LadybugDB if
viable, otherwise in PostgreSQL tables, with the trade-offs presented before
coding. A spike showed LadybugDB 0.21.2 (MIT, a fork of Kùzu) working
in memory-api's Python 3.14 image, as a non-root user, in the state volume,
with Cypher traversals. It also showed two constraints: an exclusive lock
on the file (one process at a time) and a 0.x storage format.

## Decision

The graph is an embedded LadybugDB file (`/state/graph.lbug`) owned by
memory-api, derived from the vault: rebuilt whole in one transaction at the
end of every ingestion, and at startup when missing or empty. Only messages
that identify damage lead to deleting it (the graph file and its own side
files); a held lock or any other error leaves it in place and makes only the
`/graph` routes answer `503`.

## Alternatives considered

- **PostgreSQL tables**: the fallback named by the phase plan, kept as such
  if LadybugDB updates cause problems.
- **Incremental updates of the graph**: a renamed or deleted note changes the
  resolution of every link pointing to it; rebuilding (1.2 s for 2,000 notes
  and 6,000 links) is simpler and always right.

## Consequences

- One process owns the file: a single uvicorn process (no workers), a single
  container (`check-exposure.sh` refuses a scaled service), the graph closed
  on shutdown. Deployments, rollbacks and a SIGKILL were tested with the real
  deployment hook on a simulated server: the old container always dies
  before the new one starts, and the kernel releases the lock with the
  process.
- A storage format the next LadybugDB version cannot read is handled as a
  damaged file: deleted and rebuilt from the vault. `/search` and `/context`
  never depend on the graph.
- Links are resolved like Obsidian; links to missing notes become ghost
  notes, links to attachments create nothing; nested tags link to their
  parent.
- Differences from the phase plan: the routes take `?path=` (spaces,
  accents, folders), not `?note=`, and `/search` is not enriched with graph
  neighbours (ADR-0018).

## References

- `9493b08` to `e39c162`; PR #3 merged in `c3a29f3`.
- `services/memory-api/src/graph.py`, `services/memory-api/README.md`
  (section "Graph"), `docs/DEPLOY.md` (Rollback).
