# ADR-0003: Local models through Ollama, sized for CPU-only servers

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

Nyansa's notes, models and data must stay on infrastructure its owner
controls. The server may have no GPU and limited RAM. The starter kit ran
`llama3.2` in Ollama.

## Decision

All inference runs locally in Ollama: `qwen2.5:3b` answers in the chat and
`nomic-embed-text` embeds the notes and the questions. Ollama runs in a
`cpu`, `gpu-nvidia` or `gpu-amd` Compose profile, always under the name
`nyansa-ollama`.

## Alternatives considered

- **A hosted model API**: the notes would leave the server.
- **`llama3.2`, the starter kit's model**: replaced by `qwen2.5:3b`;
  Rationale to be confirmed.
- **`qwen2.5:7b`**: considered in phase 3 if the RAM allows it;
  `qwen2.5:3b` was kept.

## Consequences

- A CPU-only server embeds about 2 chunks per second: a first full
  ingestion of 500 notes takes about 17 minutes; incremental runs only embed
  changed notes.
- `qwen2.5:3b` follows citation instructions poorly. The chat compensates:
  sources are built from data, notes are wrapped in `<note>` tags, the
  prompt ends with a reminder and the temperature is 0.1 (ADR-0015).
- `nomic-embed-text` is trained mostly on English: French notes are found
  with a less precise ranking, and the relevance threshold of `/context` was
  measured on a French vault (0.65). `EMBEDDING_MODEL` can be changed, which
  reindexes every note.
- Ollama has no authentication of its own and relies on network isolation
  (ADR-0004).

## References

- `bfd2c90` (models of the Nyansa stack), `872b904`, `9d4030c`, `bba0217`.
- `docker-compose.yml` (`nyansa-ollama-*`, `nyansa-ollama-pull-model`),
  README sections "Features" and "Tech stack",
  `services/memory-api/README.md` ("Known limits").
