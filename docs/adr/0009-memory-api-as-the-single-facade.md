# ADR-0009: memory-api is the only component that touches the memory stores

- **Status:** Accepted
- **Date:** 2026-10-20

## Context

In the starter kit and after phase 1, n8n held a Qdrant credential (its key
injected since `9928302`) and mounted the vault. Phase 3 added the chat
workflow and the scheduled ingestion, both in n8n; the phase 3 plan wanted
the sensitive logic (grouping and numbering the sources, the relevance
threshold) in memory-api, where it is tested.

## Decision

memory-api is the only component that reads the vault and talks to Qdrant,
to the ingestion state and, since phase 4, to the graph; n8n and the other
services go through its HTTP API, with a bearer token, on the internal
network.

## Alternatives considered

- **Keep the Qdrant nodes and credential in n8n**: the chat would have built
  its context in workflow nodes, untested, and n8n would have kept
  `QDRANT_API_KEY`.

## Consequences

- n8n no longer has a Qdrant credential or `QDRANT_API_KEY`: one secret less
  in n8n; the Qdrant key is known only to memory-api.
- The chat calls `POST /context`, which returns numbered sources and
  `found: false` below the threshold, tested with pytest.
- The chat and the ingestion both depend on memory-api being up; its
  `/health` also reports Ollama and Qdrant.
- A new memory store (the graph, ADR-0012) is added behind memory-api
  without changing its clients.

## References

- `872b904`, `856381a`, `9396e10`; phase 3 merged in `a1aca86`.
- `docker-compose.yml`, `n8n/workflows/`, `services/memory-api/README.md`,
  `scripts/check-n8n-workflows.sh` (memory-api only called on its internal
  URL).
