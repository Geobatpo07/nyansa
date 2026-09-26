# Shared helpers for Nyansa scripts. Source it, do not execute it.
# shellcheck shell=bash

# Compose project name. Fixed so every release drives the same containers
# and volumes (docker-compose.yml also sets `name: nyansa`).
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

# Reads KEY from a dotenv file without executing it. Strips one level of
# surrounding single or double quotes. Prints the default when absent.
env_value() {
	local file=$1 key=$2 default=${3-} line value
	line=$(grep -E "^${key}=" "$file" 2>/dev/null | tail -n 1 || true)
	if [[ -z "$line" ]]; then
		printf '%s' "$default"
		return
	fi
	value=${line#*=}
	value=${value%$'\r'}
	if [[ "$value" =~ ^\"(.*)\"$ || "$value" =~ ^\'(.*)\'$ ]]; then
		value=${BASH_REMATCH[1]}
	fi
	printf '%s' "$value"
}

# Turns "cpu public" or "cpu,public" into: --profile cpu --profile public
profile_args() {
	local profile
	for profile in ${1//,/ }; do
		printf -- '--profile\n%s\n' "$profile"
	done
}
