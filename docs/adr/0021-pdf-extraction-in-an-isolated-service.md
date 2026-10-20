# ADR-0021: PDF extraction in an isolated service, doc-extractor

- **Status:** Accepted — implementation pending
- **Date:** 2026-10-21

## Context

Only Markdown notes are ingested; PDFs in the vault are ignored. Parsing a
PDF means running a parser on files that may be malformed or hostile, and a
parse can hang or exhaust memory. memory-api owns the graph file lock
(ADR-0017) and an extraction run in one of its threads could not be
interrupted.

## Decision

A separate, stateless Python service, `doc-extractor`, extracts the text of
a PDF that memory-api sends it over HTTP: pypdf behind an extractor
interface, each extraction in a child process killed past a time limit and
capped in memory, on an internal network shared only with memory-api, with
no outbound access and no published port.

## Alternatives considered

- **Extraction inside memory-api**: a thread cannot be interrupted, and
  memory-api owns the graph.
- **Docling now**: heavy; considered later, behind the same interface.
- **PyMuPDF**: AGPL license, which does not fit an Apache 2.0 project.
- **OCR of scanned PDFs**: not now; pages without text are reported.

## Consequences

- The container is hardened (non-root, read-only, no capabilities,
  `no-new-privileges`) and limited (1 GB, 1 CPU, 64 processes); per
  extraction: 60 s, 512 MB, at most 50 MB and 1,000 pages, one at a time,
  with a bounded queue answering `503`. The memory limit is checked against a
  large but healthy PDF.
- API: `POST /extract` (bearer `DOC_EXTRACTOR_TOKEN`) returns the pages, the
  warnings, a plausible title and the extractor's name and version, or
  `413`, `422` (`corrupt`, `encrypted`, `no_text`, `too_complex`, or no
  `%PDF` signature) or `504`.
- memory-api indexes PDFs page by page (`kind`, physical `page`) and cites
  them as `[[path.pdf#page=N]]`; the extractor's name and version are part
  of the reindexing decision. PDFs that fail for good are remembered in
  `memory-api.db` and still reported; when the service is down, PDFs are
  skipped and retried, and notes are indexed anyway.
- The graph gets `Document` nodes and `EMBEDS` relations from notes.
- One more service to build, deploy and monitor (ADR-0020).

## References

- Phase 4b plan, validated on 2026-10-21; phase 4b branch to come
  (`feat/pdf-ingestion`).
