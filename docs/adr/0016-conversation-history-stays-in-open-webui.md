# ADR-0016: The conversation history stays in Open WebUI

- **Status:** Accepted
- **Date:** 2026-10-20

## Context

With the chat through an Open WebUI pipe (ADR-0015), Open WebUI stores each
conversation, as it does for any model, in its own database. memory-api
stores the notes' chunks, the ingestion tasks and the graph, but no
conversation.

## Decision

No separate decision was made: the conversation history stays where the
chat interface keeps it, in Open WebUI, and no other component stores it.

## Alternatives considered

- None recorded: a structured history in memory-api was never decided.

## Consequences

- The history is backed up with Open WebUI's volume (`backup.sh`), and the
  conversations remain visible in Open WebUI.
- The pipe sends only the last user message to n8n: answers do not use the
  previous turns of a conversation, and no component links an answer to the
  notes it cited after the fact (the citations are only in Open WebUI's
  messages).
- The episodic memory planned for phase 6 needs a structured history of the
  conversations with their cited notes, which does not exist yet: building
  it is part of that phase.

## References

- `open-webui/src/nyansa_pipe.py` (`last_user_message`), `scripts/backup.sh`
  (`nyansa_openwebui_storage`), README section "Roadmap".
