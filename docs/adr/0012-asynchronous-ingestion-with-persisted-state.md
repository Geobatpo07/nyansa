# ADR-0012: Asynchronous ingestion with its state in SQLite

- **Status:** Accepted
- **Date:** 2026-10-20 (storage chosen on 2026-10-19)

## Context

`POST /ingest` answered when the run was over, and a first full ingestion
on a CPU-only server takes minutes (17 minutes for 500 notes in testing).
The phase 3 requirements: start a run with `202`, follow it with a status
route, refuse a second run with `409`, and keep each task's state across a
restart of the read-only memory-api container (deployments restart it).

## Decision

`POST /ingest` answers `202` with a task and its `Location`
(`/ingest/status/{id}`), or `409` while a task runs. Tasks are kept in a
SQLite file on the memory-api state volume (`memory-api.db`, the 100
latest). A task stopped by the service or found `running` at startup becomes
`interrupted` and is not resumed.

## Alternatives considered

- **A JSON file in a volume**: no dependency, but a single instance, no
  queries, and atomic writes to handle by hand.
- **A PostgreSQL table**: transactional and already backed up, but a new
  database, role, secret and migrations, an idempotent init service (the
  production volume already existed), and memory-api depending on
  PostgreSQL's health.
- SQLite was chosen on 2026-10-19, with the move to Python: it is in the
  standard library, transactional, and needs no extra service.
- **Resume an interrupted task at startup**: restarting a heavy ingestion
  would load Ollama during the health checks of deployments and rollbacks;
  incremental ingestion is idempotent, so the next run redoes only what was
  not recorded.

## Consequences

- The note hash is written last (`b0fb263`), so an interrupted note keeps
  its old hash and is indexed again by the next run.
- memory-api has a writable volume, its only writable path; it is backed up
  since `dff83db` (ADR-0019).
- One task at a time; the n8n workflow polls the status every minute, for 2
  hours at most, and alerts by e-mail on failure.

## References

- `b0fb263`, `77043af`; phase 3 merged in `a1aca86`.
- `services/memory-api/src/jobs.py`, `services/memory-api/README.md`
  (`POST /ingest`, `GET /ingest/status`), `n8n/workflows/nyIngestSchedule.json`.
