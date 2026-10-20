# ADR-0019: Back up only what cannot be rebuilt

- **Status:** Accepted
- **Date:** 2026-10-20 (models excluded since 2026-09-26)

## Context

`backup.sh` runs before every deployment and can run nightly; containers
writing to the archived volumes are stopped during the copy. Some state can
be recreated: the Ollama models and Open WebUI's model cache (downloaded
again, about 1 GB) and, since phase 4, the graph (rebuilt from the vault).
memory-api's state volume also holds `memory-api.db`, the history of the
100 latest ingestions, which cannot be rebuilt.

## Decision

Backups contain what cannot be rebuilt: the PostgreSQL dump, the n8n,
Open WebUI, Caddy and Tailscale volumes, and the memory-api state volume
without the graph files (`graph.lbug*`); plus Qdrant, which is slow to
rebuild. Downloaded models and the graph are left out.

## Alternatives considered

- **Leave the memory-api state volume out entirely**: the first phase 4
  documentation did so; the ingestion history would have been lost on a
  restore.
- **Archive the graph too**: it is derived from the vault and rebuilt at
  startup, so it would only add size.

## Consequences

- memory-api is stopped for a few seconds during a backup; an ingestion
  running then is recorded as interrupted, and the next run completes it.
- After a restore, memory-api starts without a graph and builds it from the
  vault; downloaded models are fetched again, which needs internet access.
- Qdrant stays in the backups as a recovery optimisation, not a protection
  against data loss: its content is rebuilt from the vault, but that
  recomputes every embedding on the CPU (17 minutes for 500 notes in
  testing), and restoring it shortens the return to service.
- `scripts/tests/backup-restore.test.sh` runs a backup then a restore on
  throwaway containers and refuses to run when any Nyansa container or
  volume exists.

## References

- `3d299cb`, `7e5ab83`, `dff83db`, `e39c162`.
- `scripts/backup.sh`, `scripts/restore.sh`, `docs/DEPLOY.md` (Backups,
  Restore).
