# ADR-0014: Versioned n8n workflows, imported only when missing

- **Status:** Accepted
- **Date:** 2026-10-20

## Context

Phase 3 required the n8n workflows to be versioned as JSON in
`n8n/workflows/` and imported at startup. The starter kit imported its demo
data on first start only (`83727c7` made it skip instances that already had
workflows). The owner also edits workflows in the n8n editor, and those
edits must not be lost on a deployment.

## Decision

Workflows and credentials live in `n8n/workflows/` and `n8n/credentials/`
with fixed ids, without any secret; at each start, the import adds those
whose id is not in n8n yet, publishes the ones marked active, and never
overwrites an existing one. `scripts/n8n-export.sh` brings editor changes
back into the repository.

## Alternatives considered

- **Import on first start only**: a workflow added later never reaches an
  existing instance.
- **The repository wins (reimport at every deployment)**: edits made in the
  editor and not exported would be lost.

## Consequences

- A new workflow arrives with the deployment that adds it; updating an
  existing one is an explicit step (`docs/DEPLOY.md`, "Update a workflow").
- `scripts/check-n8n-workflows.sh` checks the files: every webhook has Header
  Auth, no public chat trigger, no pinned data, every credential exists with
  its type, no secret value, memory-api called on its internal URL only.
- Alert addresses are placeholders, replaced at import time from `.env`.
- n8n 2.40 cannot import the active state outside queue mode, so the import
  publishes the active workflows with `n8n publish:workflow`.

## References

- `856381a`, `24b37d6`; phase 3 merged in `a1aca86`.
- `n8n/`, `docker-compose.yml` (`nyansa-n8n-import`), `scripts/n8n-export.sh`,
  `scripts/check-n8n-workflows.sh`, `docs/DEPLOY.md`, README section
  "Editing the workflows".
