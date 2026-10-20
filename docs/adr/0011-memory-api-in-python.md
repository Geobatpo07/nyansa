# ADR-0011: Python is the project's programming language

- **Status:** Accepted
- **Date:** 2026-10-19 (merged in `2ec02cc`)

## Context

After phase 2, memory-api was a TypeScript service (ADR-0008) merged in
`main`. The phase 3 plan, not yet started, added more code: asynchronous
ingestion, a `/context` route for the chat and, as the recommended chat
option, an Open WebUI pipe, which Open WebUI runs in Python. The Qdrant index
of the TypeScript version was in use. The reasons for moving to Python:

- the data and AI ecosystem;
- the libraries of the next phases, LadybugDB for the phase 4 graph in
  particular;
- one language for every service;
- consistency with the maintainer's data background;
- portability;
- uv, which makes managing dependencies and environments flexible and fast.

## Decision

Python is the programming language of the project. memory-api was ported
entirely to Python 3.14, with the same API, behaviour and index, using
asyncio, FastAPI, Pydantic and httpx, with pytest, ruff and mypy (strict),
and dependencies locked with uv; the TypeScript code was removed.

## Alternatives considered

- **Keep memory-api in TypeScript and write new code in Python**: offered;
  the repository would have kept two application languages.
- **Starlette and httpx only**: fewer dependencies, but validation and the
  OpenAPI schema written by hand.
- **pip and `requirements.txt`**: no lock file with hashes without extra
  tools.

## Consequences

- The port reproduces the point ids and `index_version` of the TypeScript
  version, checked by golden tests: the existing index was kept and nothing
  was reindexed.
- One application language for memory-api and the Open WebUI pipe.
- The standard library's `sqlite3` became available for the ingestion state
  (ADR-0012).
- FastAPI has no body size limit by default: a 64 KiB limit was added to keep
  the behaviour of Fastify.
- The CI planned for phase 5 uses ruff, mypy and pytest instead of ESLint
  and Vitest. Developers need `uv`.
- The choice was borne out later by phase 4b (pypdf now, Docling considered
  later), which was not a reason for the decision of 2026-10-19.

## References

- `367dd17` to `86580eb`, `9c4fee7`; PR #1 merged in `2ec02cc`.
- `services/memory-api/pyproject.toml`, `uv.lock`, `tests/test_golden.py`,
  `services/memory-api/README.md` (section "Development").
