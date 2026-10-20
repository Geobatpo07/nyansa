# Architecture decision records

Each file records one architecture decision of Nyansa: its context, the
decision, the alternatives considered and the consequences
([ADR-0001](0001-record-architecture-decisions.md) explains how they are
kept). New records start from [template.md](template.md).

| ADR | Title | Status |
|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-fork-the-n8n-self-hosted-ai-starter-kit.md) | Start from the n8n self-hosted AI starter kit | Accepted |
| [0003](0003-local-models-sized-for-cpu.md) | Local models through Ollama, sized for CPU-only servers | Accepted |
| [0004](0004-exposure-enforced-in-compose.md) | Port exposure is enforced in Compose and checked by a script | Accepted |
| [0005](0005-n8n-secrets-injected-from-env.md) | n8n credentials carry no secret; secrets come from `.env` | Accepted |
| [0006](0006-caddy-as-the-only-entry-point.md) | Caddy is the only entry point, without an API gateway | Accepted |
| [0007](0007-deployment-through-git-hooks.md) | Deploy with Git hooks and immutable release folders | Accepted |
| [0008](0008-memory-api-in-typescript.md) | memory-api in TypeScript | Superseded by [ADR-0011](0011-memory-api-in-python.md) |
| [0010](0010-read-only-vault.md) | The vault is read-only for Nyansa | Accepted |
| [0011](0011-memory-api-in-python.md) | Python is the project's programming language | Accepted |
| [0012](0012-asynchronous-ingestion-with-persisted-state.md) | Asynchronous ingestion with its state in SQLite | Accepted |
| [0013](0013-memory-api-as-the-single-facade.md) | memory-api is the only component that touches the memory stores | Accepted |
| [0015](0015-chat-through-an-open-webui-pipe.md) | Chat through an Open WebUI pipe, with sources built from data | Accepted |
| [0016](0016-conversation-history-stays-in-open-webui.md) | The conversation history stays in Open WebUI | Accepted |
| [0017](0017-ladybugdb-for-the-graph.md) | LadybugDB for the graph of the vault | Accepted |
| [0018](0018-related-notes-are-shown-not-given-to-the-model.md) | Linked notes are shown to the user, not given to the model | Accepted |
| [0019](0019-back-up-only-what-cannot-be-rebuilt.md) | Back up only what cannot be rebuilt | Accepted |
| [0020](0020-conventions-for-services.md) | Conventions for the services in `services/` | Accepted — implementation pending |
| [0021](0021-pdf-extraction-in-an-isolated-service.md) | PDF extraction in an isolated service, doc-extractor | Accepted — implementation pending |
