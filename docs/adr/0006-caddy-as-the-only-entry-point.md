# ADR-0006: Caddy is the only entry point, without an API gateway

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

The starter kit published the ports of n8n, Ollama, Qdrant and PostgreSQL on
the host. Nyansa runs on a single-owner server reachable from the internet,
and Docker bypasses UFW for published ports. The phase 1 requirements: keep
internal services on the Docker network, and expose only Open WebUI and the
n8n editor, over automatic HTTPS, with authentication. The owner wanted two
access modes: a public domain, and a Tailscale tailnet with no public port.

## Decision

A Caddy reverse proxy is the only service reachable from outside, in one of
two Compose profiles: `public` (ports 80 and 443, Let's Encrypt, basic auth
in front of the n8n editor) or `tailscale` (a Tailscale sidecar, no port
published on the host). Every other service publishes no port, or binds to
`127.0.0.1` for SSH tunnels.

## Alternatives considered

- **A dedicated API gateway (Kong, Traefik...)**: not needed while external
  access is limited to authenticated n8n webhooks; if broader API access is
  needed, Caddy will be extended first (as stated by the maintainer when recording this ADR).
- **One access mode only**: the owner chose to support both, as profiles.

## Consequences

- Which ports are published is enforced in Compose and checked by a script
  ([ADR-0004](0004-exposure-enforced-in-compose.md)).
- Caddy adds the security headers (HSTS, `nosniff`, `frame-ancestors`), also
  on error responses.
- Webhook paths (`/webhook*`) pass without basic auth, so every n8n webhook
  needs its own Header Auth, checked by `check-n8n-workflows.sh`; the chat
  webhook, only called from inside, is refused by Caddy (404).
- memory-api, Qdrant and Ollama have no route from outside; a client outside
  the server cannot call memory-api today.

## References

- `4d9b578`, `9a1c9c6`, `d9e1ce5`, `6439473`, `6bead87`, `4c15632`;
  phase 1 merged in `f191246`.
- `caddy/`, `docker-compose.yml`, `scripts/check-exposure.sh`,
  `scripts/check-n8n-workflows.sh`, README section "Security",
  `docs/DEPLOY.md` section 5.
