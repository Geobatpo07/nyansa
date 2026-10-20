# Architecture decision records

Each file records one architecture decision of Nyansa: its context, the
decision, the alternatives considered and the consequences
([ADR-0001](0001-record-architecture-decisions.md) explains how they are
kept). New records start from [template.md](template.md).

| ADR | Title | Status |
|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-fork-the-n8n-self-hosted-ai-starter-kit.md) | Start from the n8n self-hosted AI starter kit | Accepted |
| [0003](0003-read-only-vault.md) | The vault is read-only for Nyansa | Accepted |
| [0004](0004-caddy-as-the-only-entry-point.md) | Caddy is the only entry point, without an API gateway | Accepted |
| [0005](0005-deployment-through-git-hooks.md) | Deploy with Git hooks and immutable release folders | Accepted |
| [0006](0006-memory-api-in-typescript.md) | memory-api in TypeScript | Superseded by [ADR-0007](0007-memory-api-in-python.md) |
| [0007](0007-memory-api-in-python.md) | Python is the project's programming language | Accepted |
| [0008](0008-asynchronous-ingestion-with-persisted-state.md) | Asynchronous ingestion with its state in SQLite | Accepted |
| [0009](0009-memory-api-as-the-single-facade.md) | memory-api is the only component that touches the memory stores | Accepted |
| [0010](0010-chat-through-an-open-webui-pipe.md) | Chat through an Open WebUI pipe, with sources built from data | Accepted |
| [0011](0011-conversation-history-stays-in-open-webui.md) | The conversation history stays in Open WebUI | Accepted |
| [0012](0012-ladybugdb-for-the-graph.md) | LadybugDB for the graph of the vault | Accepted |
| [0013](0013-related-notes-are-shown-not-given-to-the-model.md) | Linked notes are shown to the user, not given to the model | Accepted |
| [0014](0014-back-up-only-what-cannot-be-rebuilt.md) | Back up only what cannot be rebuilt | Accepted |
