# ADR-0018: Linked notes are shown to the user, not given to the model

- **Status:** Accepted
- **Date:** 2026-10-20

## Context

The phase 4 plan asked to enrich `/search` with the notes linked to its
results (one-hop neighbours), with a documented weighting. With the graph
in place, two ways to use it in the chat were possible: (a) list the notes
linked to the sources under the answer, or (b) add them to the context given
to the model. There was no set of reference questions to measure the effect
of (b) on the answers.

## Decision

Option (a): `/context` returns `related`, the notes the graph links to or
from the sources, and the chat lists them under "Notes liées"; they are
never given to the model. Option (b) is deferred until its effect can be
measured on a set of reference questions.

## Alternatives considered

- **(b) Expand the context with the linked notes**: deferred; its effect on
  answer quality could not be measured yet.
- **Enrich `/search` with weighted neighbours, as planned**: not done;
  `/search` returns vector results only.

## Consequences

- The list is deterministic and cannot make the model invent: it only adds
  links for the reader.
- Without the graph, `related` is empty and the answer is unchanged.
- The deferral is in the README roadmap ("Graph-expanded context"); the set
  of reference questions is part of the planned phase 6.

## References

- `d4eb4e1`; PR #3 merged in `c3a29f3`.
- `services/memory-api/src/context.py`, `n8n/workflows/nyChatWithNotes1.json`,
  `services/memory-api/README.md` (`POST /context`), README section
  "Roadmap".
