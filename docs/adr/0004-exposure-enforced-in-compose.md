# ADR-0004: Port exposure is enforced in Compose and checked by a script

- **Status:** Accepted
- **Date:** 2026-09-26

## Context

The starter kit published the ports of n8n, Ollama, Qdrant and PostgreSQL
on all interfaces. Docker writes its own iptables rules: a port published by
a container is reachable even when UFW denies it, so a host firewall cannot
be relied on to hide a published port. The stack has 9 combinations of
hardware profile (`cpu`, `gpu-nvidia`, `gpu-amd`) and access profile (none,
`public`, `tailscale`).

## Decision

Exposure is decided in `docker-compose.yml`: only the public Caddy publishes
ports on all interfaces (80 and 443), n8n and Open WebUI bind to
`127.0.0.1`, and PostgreSQL, Qdrant, Ollama and memory-api publish none.
`scripts/check-exposure.sh` verifies these rules on the rendered Compose
configuration of every profile combination.

## Alternatives considered

- **Rely on UFW**: Docker bypasses it for published ports.
- **Review the Compose file by hand**: a profile combination is easy to
  miss; the check runs on the configuration Compose actually renders.

## Consequences

- The check runs on every release folder (`build-publish.sh`), so it runs in
  the `pre-push` hook and in every deployment.
- It also refuses privileged containers and the host network, and holds
  other rules on the rendered configuration: the vault mounted read-only by
  memory-api only (ADR-0010), and a single memory-api container (ADR-0017).
- UFW still protects the rest of the host (SSH, 80 and 443 in the public
  profile); n8n and Open WebUI are reached from outside only through Caddy
  (ADR-0006), or through an SSH tunnel to `127.0.0.1`.

## References

- `4d9b578`, `6439473`, `227b441`, `c757990`, `0656291`.
- `scripts/check-exposure.sh`, `docker-compose.yml`, `docs/DEPLOY.md`
  (section 6, "Firewall"), README section "Security".
