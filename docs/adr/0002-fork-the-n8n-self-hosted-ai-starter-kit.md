# ADR-0002: Start from the n8n self-hosted AI starter kit

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

Nyansa needed a Docker Compose stack of local models, a vector store and a
workflow engine. The
[n8n self-hosted AI starter kit](https://github.com/n8n-io/self-hosted-ai-starter-kit)
already wired n8n, Ollama, Qdrant and PostgreSQL in Compose, with CPU and
GPU profiles, under the Apache License 2.0.

## Decision

Nyansa is a fork of the starter kit. Its history is kept in the repository,
its `LICENSE` file is kept unchanged, and the README credits it and lists
what Nyansa changed.

## Alternatives considered

- **Start from an empty repository**: the starter kit is a working,
  recognised base where n8n, Ollama, Qdrant and PostgreSQL are already
  integrated. Starting from it puts the effort on what makes Nyansa's value
  (security, deployment, the RAG service), and the fork keeps the history and
  the credits of the original project.

## Consequences

- The base Compose layout, the GPU profiles and the first-boot import of n8n
  come from the starter kit.
- Most of it was replaced since: services, volumes and network renamed under
  `nyansa`; ports no longer published; Caddy, Open WebUI, memory-api, backups
  and the deployment pipeline added; the demo workflow and credentials
  replaced by the Nyansa ones (`856381a`).
- The Apache License 2.0 requires recipients to receive a copy of the license and
  modified files to carry prominent notices stating they were changed; README
  credits provide attribution but do not replace those notices.

## References

- First Nyansa commits: `bfd2c90`, `2dce40c` (2026-09-26); upstream history
  before them.
- `LICENSE`, README section "Credits".
