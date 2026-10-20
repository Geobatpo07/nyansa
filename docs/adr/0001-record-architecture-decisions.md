# ADR-0001: Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-10-21

## Context

By the end of phase 4, Nyansa had gone through four phases with structuring
choices: a fork as the base, Caddy as the only entry point, Git-hook
deployment, a TypeScript service ported to Python, SQLite and LadybugDB for
the state, a chat through Open WebUI. Their reasons lived in commit messages,
phase plans and the READMEs, but nowhere side by side. Phase 4b (PDF
ingestion in a separate service) was about to add more.

## Decision

Each architecture decision is recorded in `docs/adr/` as one numbered
Markdown file, in English, following [template.md](template.md), and listed
in [README.md](README.md) with its status.

## Alternatives considered

- **Keep the reasons in commit messages and READMEs only**: they describe
  what a change does, rarely the options set aside, and are hard to find
  later.
- **One design document for the whole project**: harder to keep current,
  and it does not show when and why each decision changed.

## Consequences

- An ADR describes what was decided and exists in the repository, not an
  earlier plan; when the implementation differs from a plan, the ADR says so.
- No rationale is invented: when the reason is not written anywhere, the ADR
  says "Rationale to be confirmed" until the maintainer completes it.
- A decision that is not implemented yet has the status "Accepted —
  implementation pending". A decision replaced by another one keeps its
  file, with the status "Superseded by ADR-XXXX".
- The first records (0002 to 0016) were written after the fact, from the Git
  history, the documentation and the phase plans; their dates are those of
  the decisions, not of the records.
- ADRs follow the repository rules: no secret, domain, IP address, local
  path or personal information.

## References

- [docs/adr/README.md](README.md), [docs/adr/template.md](template.md)
