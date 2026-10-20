# ADR-0003: The vault is read-only for Nyansa

- **Status:** Accepted
- **Date:** 2026-09-26 (memory-api mounts it read-only); completed on
  2026-10-20 (no other container mounts it)

## Context

The Obsidian vault is written by its owner, in Obsidian. In the starter kit,
n8n mounted a shared folder read-write, and the first Nyansa stack mounted
the vault read-write in n8n. Everything Nyansa computes from the notes
(chunks and embeddings, ingestion state, graph) needs a place to live.

## Decision

Nyansa reads the vault and never writes to it: only memory-api mounts it,
read-only, and everything derived from the notes lives in Nyansa's own
stores (Qdrant, the memory-api state volume).

## Alternatives considered

- **Keep the vault mounted in n8n, read-write or read-only**: offered in the
  phase 3 plan (to write notes from n8n later); the owner chose to remove
  the mount. n8n reads the notes through memory-api.
- **Let Nyansa write to the vault**: the vault is the source of truth,
  written by its owner, and no bug or model must be able to alter it. With
  the sync between devices planned for phase 5, a corruption would spread to
  every device. Keeping the two apart always tells what the owner wrote from
  what Nyansa derives, and a compromised container cannot modify the notes.

## Consequences

- No container can modify a note; `check-exposure.sh` fails if memory-api
  mounts `/vault` writable or if any other service mounts the vault folder,
  for every profile combination.
- Derived data can be deleted and rebuilt from the vault (ADR-0012,
  ADR-0014).
- Writing to the vault, if it is ever needed, requires a new decision. The
  planned phase 6 keeps the vault read-only and limits writes to approved
  items, in one inbox folder, by a single component.

## References

- `0c2a638` (read-only mount in memory-api), `227b441` (check),
  `9396e10` (n8n mount removed), `c757990` (no other service may mount it).
- `docker-compose.yml`, `scripts/check-exposure.sh`, README section
  "Security".
