#!/usr/bin/env bash
# Tests scripts/backup.sh then scripts/restore.sh on the memory-api state
# volume: the ingestion history is backed up and restored, the graph is not.
#
# The scripts work on fixed names (nyansa-memory-api, nyansa_memory_api_state),
# so this test creates throwaway containers and volumes with those names. It
# refuses to run when any nyansa container or volume already exists, so it
# never touches a real stack: run it in CI or in a clean Docker daemon.
#
# Usage: scripts/tests/backup-restore.test.sh
set -Eeuo pipefail

# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/../lib.sh"

require_cmd docker tar
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
helper=${BACKUP_HELPER_IMAGE:-alpine:3.24.2}
volume=nyansa_memory_api_state

if [[ -n "$(docker ps -aq --filter name=nyansa)" || -n "$(docker volume ls -q --filter name=nyansa)" ]]; then
	die "nyansa containers or volumes exist on this Docker daemon; refusing to run (the test would back them up and overwrite them)"
fi

work=$(mktemp -d)
cleanup() {
	docker rm -f nyansa-memory-api nyansa-postgres >/dev/null 2>&1 || true
	docker volume rm "$volume" >/dev/null 2>&1 || true
	rm -rf "$work"
}
trap cleanup EXIT

failures=0
expect() {
	local label=$1 actual=$2 expected=$3
	if [[ "$actual" == "$expected" ]]; then
		echo "ok   $label"
	else
		echo "FAIL $label: expected '$expected', got '$actual'" >&2
		failures=$((failures + 1))
	fi
}
in_volume() { docker run --rm -v "$volume:/state:ro" "$helper" sh -c "$1"; }

# A memory-api state volume with its history and a graph, owned by the
# service user, mounted in a running container; restore.sh needs
# nyansa-postgres to exist (stopped here, so backup.sh does not dump it).
docker volume create "$volume" >/dev/null
docker run --rm -v "$volume:/state" "$helper" sh -c \
	'echo history-1 >/state/memory-api.db && echo graph >/state/graph.lbug && echo log >/state/graph.lbug.wal &&
	chown -R 65532:65532 /state'
label=(--label "com.docker.compose.project=$NYANSA_PROJECT")
docker run -d --name nyansa-memory-api "${label[@]}" -v "$volume:/state" "$helper" sleep 600 >/dev/null
docker create --name nyansa-postgres "${label[@]}" "$helper" sleep 600 >/dev/null

BACKUP_DIR=$work/backups BACKUP_HELPER_IMAGE=$helper bash "$root/scripts/backup.sh" >"$work/backup.log" 2>&1 ||
	{ indent <"$work/backup.log" >&2; die "backup.sh failed"; }
backup=$(find "$work/backups" -mindepth 1 -maxdepth 1 -type d)
archive=$backup/$volume.tar.gz

expect "the history is in the backup" "$(tar -tzf "$archive" | grep -c '^\./memory-api\.db$')" 1
expect "the graph is not in the backup" "$(tar -tzf "$archive" | grep -c 'graph\.lbug' || true)" 0
expect "memory-api was stopped for the copy" "$(grep -c 'stopping nyansa-memory-api' "$work/backup.log")" 1
expect "memory-api runs again after the backup" "$(docker inspect -f '{{.State.Running}}' nyansa-memory-api)" true

# Later state, then the restore.
docker run --rm -v "$volume:/state" "$helper" sh -c 'echo history-2 >/state/memory-api.db'
bash "$root/scripts/restore.sh" "$backup" --yes >"$work/restore.log" 2>&1 ||
	{ indent <"$work/restore.log" >&2; die "restore.sh failed"; }

expect "the history is restored" "$(in_volume 'cat /state/memory-api.db')" history-1
expect "it still belongs to the service user" "$(in_volume 'stat -c %u:%g /state/memory-api.db')" 65532:65532
expect "no graph comes back (memory-api rebuilds it)" "$(in_volume 'ls /state | grep -c graph || true')" 0
expect "memory-api runs again after the restore" "$(docker inspect -f '{{.State.Running}}' nyansa-memory-api)" true

((failures == 0)) || die "$failures backup-restore test(s) failed"
log "backup-restore tests passed"
