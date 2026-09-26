# Shared helpers for Nyansa scripts. Source it, do not execute it.
# shellcheck shell=bash

# Compose project name. Fixed so every release drives the same containers
# and volumes (docker-compose.yml also sets `name: nyansa`).
# shellcheck disable=SC2034 # used by the scripts that source this file
NYANSA_PROJECT=nyansa

log() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
warn() { printf '[%s] WARNING: %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; }
die() { printf '[%s] ERROR: %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; exit 1; }

require_cmd() {
	local cmd
	for cmd in "$@"; do
		command -v "$cmd" >/dev/null 2>&1 || die "required command not found: $cmd"
	done
}

container_exists() { docker container inspect "$1" >/dev/null 2>&1; }
container_running() { [[ "$(docker container inspect -f '{{.State.Running}}' "$1" 2>/dev/null)" == "true" ]]; }
volume_exists() { docker volume inspect "$1" >/dev/null 2>&1; }

# Prefixes each line of stdin with "  - " (used for lists of problems).
indent() { sed 's/^/  - /'; }
