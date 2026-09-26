#!/usr/bin/env bash
# Backs up Nyansa state into a timestamped folder:
#   - postgres.dump        logical dump of the n8n database (pg_dump, live)
#   - <volume>.tar.gz      archive of each stateful volume (cold copy)
#   - MANIFEST, SHA256SUMS images in use and checksums
#
# Containers that write to the archived volumes are stopped for the copy so
# SQLite files (Open WebUI) and Qdrant segments are consistent, then
# restarted. Ollama models are not backed up: they are downloaded again.
# The .env file is NOT included; keep a copy of it (and N8N_ENCRYPTION_KEY)
# somewhere else, or the n8n credentials cannot be decrypted after a restore.
#
# Usage: scripts/backup.sh
# Environment:
#   BACKUP_DIR             destination root (default: ./backups)
#   BACKUP_RETENTION_DAYS  delete backups older than this (default: 14, 0 = keep all)
#   BACKUP_HELPER_IMAGE    image used to read volumes (default: alpine:3.24.2)
set -Eeuo pipefail

# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

BACKUP_DIR=${BACKUP_DIR:-./backups}
RETENTION_DAYS=${BACKUP_RETENTION_DAYS:-14}
HELPER_IMAGE=${BACKUP_HELPER_IMAGE:-alpine:3.24.2}

# Stateful volumes archived as tarballs. nyansa_postgres_storage is only
# archived when PostgreSQL is not running; otherwise pg_dump is used.
VOLUMES=(
	nyansa_n8n_storage
	nyansa_qdrant_storage
	nyansa_openwebui_storage
	nyansa_caddy_data
	nyansa_tailscale_state
)
# Containers writing to those volumes, in stop order (proxies first).
# They are restarted in reverse order.
WRITERS=(
	nyansa-caddy-public
	nyansa-caddy-tailscale
	nyansa-n8n
	nyansa-open-webui
	nyansa-qdrant
	nyansa-tailscale
)

require_cmd docker sha256sum

stopped=()
restart_writers() {
	local i
	for ((i = ${#stopped[@]} - 1; i >= 0; i--)); do
		log "starting ${stopped[i]}"
		docker start "${stopped[i]}" >/dev/null || warn "could not restart ${stopped[i]}"
	done
	stopped=()
}
trap restart_writers EXIT

umask 077
stamp=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$BACKUP_DIR"
target=$(cd "$BACKUP_DIR" && pwd)/$stamp
mkdir "$target"
log "backup to $target"

archived=0

# 1. PostgreSQL: logical dump while running, so n8n keeps its database.
if container_running nyansa-postgres; then
	log "dumping PostgreSQL"
	# shellcheck disable=SC2016 # variables are expanded inside the container
	docker exec nyansa-postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' \
		>"$target/postgres.dump"
	archived=$((archived + 1))
elif volume_exists nyansa_postgres_storage; then
	warn "nyansa-postgres is not running; archiving its volume instead of dumping"
	VOLUMES+=(nyansa_postgres_storage)
fi

# 2. Stop the writers that are running.
for name in "${WRITERS[@]}"; do
	if container_running "$name"; then
		log "stopping $name"
		docker stop "$name" >/dev/null
		stopped+=("$name")
	fi
done

# 3. Archive each existing volume from a read-only mount.
for volume in "${VOLUMES[@]}"; do
	volume_exists "$volume" || continue
	log "archiving volume $volume"
	docker run --rm \
		-v "$volume:/source:ro" \
		-v "$target:/backup" \
		"$HELPER_IMAGE" tar -czf "/backup/$volume.tar.gz" -C /source .
	archived=$((archived + 1))
done

restart_writers

if ((archived == 0)); then
	rmdir "$target"
	log "nothing to back up (no Nyansa container or volume found)"
	exit 0
fi

# 4. Manifest and checksums.
{
	echo "created_at=$stamp"
	echo "host=$(hostname)"
	docker ps -a --filter "label=com.docker.compose.project=$NYANSA_PROJECT" --format 'image {{.Names}} {{.Image}}'
} >"$target/MANIFEST"
(
	cd "$target"
	shopt -s nullglob
	files=(*.dump *.tar.gz)
	sha256sum -- "${files[@]}" >SHA256SUMS
)

log "backup complete: $(du -sh "$target" | cut -f1)"

# 5. Retention.
if ((RETENTION_DAYS > 0)); then
	find "$(dirname "$target")" -mindepth 1 -maxdepth 1 -type d -name '20*Z' -mtime "+$RETENTION_DAYS" -print \
		-exec rm -rf {} + | sed 's/^/removed old backup: /'
fi
