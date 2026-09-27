#!/usr/bin/env bash
# Restores a backup made by scripts/backup.sh.
#
# The stack must have been created once (docker compose ... up -d) so the
# containers exist. Every Nyansa container is stopped, the volumes found in
# the backup are replaced, the PostgreSQL dump is restored, then the
# containers that were running are started again.
#
# The .env in use must hold the same N8N_ENCRYPTION_KEY as when the backup
# was taken, or n8n cannot decrypt the restored credentials.
#
# Usage: scripts/restore.sh <backup-folder> --yes
# Environment:
#   BACKUP_HELPER_IMAGE  image used to write volumes (default: alpine:3.24.2)
set -Eeuo pipefail

# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

HELPER_IMAGE=${BACKUP_HELPER_IMAGE:-alpine:3.24.2}
# Start order after the restore. Tailscale must run before the Caddy that
# shares its network namespace.
START_ORDER=(
	nyansa-postgres
	nyansa-qdrant
	nyansa-ollama
	nyansa-tailscale
	nyansa-n8n
	nyansa-open-webui
	nyansa-caddy-public
	nyansa-caddy-tailscale
)

usage() {
	echo "usage: $0 <backup-folder> --yes" >&2
	exit 2
}

[[ $# -eq 2 && "$2" == "--yes" ]] || usage
source_dir=$(cd "$1" && pwd) || die "backup folder not found: $1"
[[ -f "$source_dir/SHA256SUMS" ]] || die "$source_dir has no SHA256SUMS; not a Nyansa backup"

require_cmd docker sha256sum

log "verifying checksums"
(cd "$source_dir" && sha256sum --check --quiet SHA256SUMS) || die "checksum mismatch in $source_dir"

container_exists nyansa-postgres ||
	die "nyansa-postgres does not exist; create the stack first (docker compose ... up -d)"

# 1. Stop every running Nyansa container and remember which ones ran.
mapfile -t running < <(docker ps --filter "label=com.docker.compose.project=$NYANSA_PROJECT" --format '{{.Names}}')
if ((${#running[@]} > 0)); then
	log "stopping: ${running[*]}"
	docker stop "${running[@]}" >/dev/null
fi

# 2. Replace the content of each archived volume.
shopt -s nullglob
for archive in "$source_dir"/*.tar.gz; do
	volume=$(basename "$archive" .tar.gz)
	log "restoring volume $volume"
	docker volume create "$volume" >/dev/null
	docker run --rm \
		-v "$volume:/target" \
		-v "$source_dir:/backup:ro" \
		"$HELPER_IMAGE" sh -c "find /target -mindepth 1 -delete && tar -xzf '/backup/$volume.tar.gz' -C /target"
done

# 3. Restore the PostgreSQL dump into a running PostgreSQL, n8n still stopped.
docker start nyansa-postgres >/dev/null
if [[ -f "$source_dir/postgres.dump" ]]; then
	log "waiting for PostgreSQL"
	for _ in $(seq 1 30); do
		# shellcheck disable=SC2016 # variables are expanded inside the container
		docker exec nyansa-postgres sh -c 'pg_isready -q -U "$POSTGRES_USER" -d "$POSTGRES_DB"' && break
		sleep 2
	done
	log "restoring PostgreSQL dump"
	# shellcheck disable=SC2016
	docker exec -i nyansa-postgres sh -c \
		'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --single-transaction' \
		<"$source_dir/postgres.dump"
fi

# 4. Start again the containers that were running before.
for name in "${START_ORDER[@]}"; do
	[[ "$name" == nyansa-postgres ]] && continue
	if printf '%s\n' "${running[@]}" | grep -qx "$name"; then
		log "starting $name"
		docker start "$name" >/dev/null
	fi
done

log "restore complete from $source_dir"
