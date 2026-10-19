---
title: Docker setup
tags: [Infra, "#Self-Hosted"]
aliases: [compose]
---
Intro with #homelab and [[Tailscale]].

# Setup
Install Docker.

## Compose
Run `docker compose up` with profiles. See [[Caddy#TLS|the proxy]].

```bash
# not a heading
docker compose --profile cpu up -d
```

## Backups
Nightly, see ![[backup.png]].
