# ADR-0005: n8n credentials carry no secret; secrets come from `.env`

- **Status:** Accepted
- **Date:** 2026-09-26 (Qdrant key); extended on 2026-10-20 (memory-api
  token, webhook secret, SMTP)

## Context

The starter kit's demo credentials were encrypted with a key the owner did
not have, and n8n stores credentials encrypted in its database. Workflows
and credentials are versioned in the repository (ADR-0014), which must hold
no secret, and the stack must work on its first start.

## Decision

The versioned n8n credentials hold no secret value. n8n receives the
secrets from `.env` through `CREDENTIALS_OVERWRITE_DATA`, which fills them
at runtime by credential type: the memory-api bearer token, one webhook
secret (`N8N_WEBHOOK_TOKEN`, header `X-Nyansa-Token`) shared by every
webhook, and the SMTP settings.

## Alternatives considered

- **One secret per webhook, entered in the n8n editor**: it would be stored
  encrypted in the n8n database and not reproducible from `.env`.
- **Credentials with their secrets in the repository**: forbidden by the
  repository rules.

## Consequences

- The secrets are in neither the n8n database nor the exported workflows;
  `check-n8n-workflows.sh` refuses a credential file holding a value.
- The overwrite applies to every credential of these types: a credential of
  the owner's own of type Header Auth, Bearer Auth or SMTP would receive the
  Nyansa secrets, so other services use another type (Custom Auth).
- Secrets injected as JSON must be hex (no `$`, quotes or `/`), and the SMTP
  password must not contain `"` or a backslash.
- Since phase 3, n8n has no Qdrant credential at all (ADR-0013); n8n gets an
  explicit list of variables, not the whole `.env`.

## References

- `5aae129`, `9928302`, `856381a`.
- `docker-compose.yml` (`CREDENTIALS_OVERWRITE_DATA`), `n8n/credentials/`,
  `scripts/check-n8n-workflows.sh`, `docs/DEPLOY.md` (section 4), README
  section "Security".
