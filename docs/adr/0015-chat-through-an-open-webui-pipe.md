# ADR-0015: Chat through an Open WebUI pipe, with sources built from data

- **Status:** Accepted
- **Date:** 2026-10-20

## Context

Phase 3 required a chat that answers from the notes and cites each source
(path and title), and says so when no note is relevant instead of
inventing. The chat model, `qwen2.5:3b` (sized for CPU-only servers),
follows citation instructions poorly. Open WebUI was already the chat
interface of the stack, on every device.

## Decision

The chat is an Open WebUI function of type "pipe" (Python), pasted once in
the admin panel, which sends the question to an n8n webhook; the workflow
asks memory-api's `/context` for numbered notes, asks Ollama to answer
citing `[n]`, then keeps only valid numbers and lists the cited notes from
the `/context` data. When no note passes the relevance threshold, the
answer is a fixed sentence and the model is not called.

## Alternatives considered

- **Open WebUI connected to n8n as an OpenAI-compatible API**: the OpenAI
  API, streaming included, would have to be emulated by webhooks, and
  `ENABLE_OPENAI_API` re-enabled.
- **The n8n chat**: the editor's panel is for the editor only, and the public
  Chat Trigger offers no Header Auth.
- **Installing the pipe through Open WebUI's API**: needs an admin API key;
  pasted by hand instead.

## Consequences

- Paths and titles shown as sources never come from the model's text;
  numbers the model invents are removed, and when it cites nothing, the notes
  given to it are listed as "consulted, not cited".
- Each note is given to the model in a `<note number="n">` tag:
  `qwen2.5:3b` copied numbered headers into its answers, not tags.
- The webhook has its own Header Auth (`X-Nyansa-Token`, injected from `.env`
  through `CREDENTIALS_OVERWRITE_DATA`) and Caddy refuses it from outside
  (404): only the pipe calls it, on the internal network.
- The pipe's code lives in Open WebUI's database: an update of
  `open-webui/src/nyansa_pipe.py` must be pasted again. It targets Python
  3.11, the version Open WebUI runs.
- The pipe sends only the last user message: each question is answered on
  its own (see ADR-0016).

## References

- `872b904`, `9d4030c`, `bba0217`, `856381a`, `4c15632`, `d4675e7`; phase 3
  merged in `a1aca86`.
- `open-webui/`, `n8n/workflows/nyChatWithNotes1.json`,
  `services/memory-api/README.md` (`POST /context`), `docs/DEPLOY.md`.
