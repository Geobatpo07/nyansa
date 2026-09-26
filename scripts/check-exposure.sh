#!/usr/bin/env bash
# Verifies the network exposure rules of docker-compose.yml for every
# combination of hardware profile (cpu, gpu-nvidia, gpu-amd) and access
# profile (none, public, tailscale):
#   - only nyansa-caddy-public may publish ports on all interfaces, and only
#     80 and 443;
#   - every other published port is bound to 127.0.0.1;
#   - PostgreSQL, Qdrant and Ollama publish no port at all;
#   - no container is privileged or uses the host network.
# Each combination must also pass `docker compose config`.
#
# Usage: scripts/check-exposure.sh [--file docker-compose.yml] [--env-file .env]
# Defaults: the Compose file next to this script's folder, and its .env
# (falls back to .env.example).
set -Eeuo pipefail

# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
compose_file=$root/docker-compose.yml
env_file=

while (($# > 0)); do
	case "$1" in
	--file) compose_file=$2; shift 2 ;;
	--env-file) env_file=$2; shift 2 ;;
	*) echo "usage: $0 [--file FILE] [--env-file FILE]" >&2; exit 2 ;;
	esac
done

if [[ -z "$env_file" ]]; then
	env_file=$(dirname "$compose_file")/.env
	[[ -f "$env_file" ]] || env_file=$(dirname "$compose_file")/.env.example
fi
[[ -f "$compose_file" ]] || die "compose file not found: $compose_file"
[[ -f "$env_file" ]] || die "env file not found: $env_file"

require_cmd docker jq

# One line per violation; empty output means the configuration is compliant.
read -r -d '' RULES <<'JQ' || true
.services | to_entries[] | .key as $name | .value as $svc |
(
  ($svc.ports // [])[]
  | select(.host_ip != "127.0.0.1")
  | select(($name == "nyansa-caddy-public" and (.target == 80 or .target == 443)) | not)
  | "\($name): port \(.published)->\(.target) is published on \(.host_ip // "all interfaces")"
),
(
  select(($name | test("^nyansa-(postgres|qdrant|ollama)")) and (($svc.ports // []) | length > 0))
  | "\($name): must not publish any port"
),
( select($svc.privileged == true) | "\($name): runs privileged" ),
( select($svc.network_mode == "host") | "\($name): uses the host network" )
JQ

failures=0
checked=0
for hardware in cpu gpu-nvidia gpu-amd; do
	for access in "" public tailscale; do
		label="$hardware${access:+ + $access}"
		args=(--env-file "$env_file" -f "$compose_file" --profile "$hardware")
		[[ -n "$access" ]] && args+=(--profile "$access")

		if ! json=$(docker compose "${args[@]}" config --format json 2>&1); then
			echo "FAIL [$label] docker compose config: $json" >&2
			failures=$((failures + 1))
			continue
		fi
		violations=$(jq -r "$RULES" <<<"$json")
		if [[ -n "$violations" ]]; then
			echo "FAIL [$label]" >&2
			sed 's/^/  - /' <<<"$violations" >&2
			failures=$((failures + 1))
		else
			echo "ok   [$label]"
		fi
		checked=$((checked + 1))
	done
done

((failures == 0)) || die "$failures profile combination(s) violate the exposure rules"
log "exposure rules satisfied for $checked profile combinations"
