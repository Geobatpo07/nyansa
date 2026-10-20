#!/usr/bin/env bash
# Exports workflows edited in the n8n editor back to n8n/workflows, in the
# versioned format: only id, name, active, nodes, connections and settings are
# kept (no dates, versions, sharing or pinned data), and the alert e-mail
# addresses of the env file are replaced by their placeholders. The result is
# then checked with check-n8n-workflows.sh. Meant for a development instance.
#
# Usage: scripts/n8n-export.sh [--container nyansa-n8n] [--env-file .env] [--output DIR] [ID...]
#   ID       workflows to export (default: those already in n8n/workflows)
#   --output destination folder (default: n8n/workflows)
set -Eeuo pipefail

# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
container=nyansa-n8n
env_file=$root/.env
output=$root/n8n/workflows
ids=()
while (($# > 0)); do
	case "$1" in
	--container) container=$2; shift 2 ;;
	--env-file) env_file=$2; shift 2 ;;
	--output) output=$2; shift 2 ;;
	-*) echo "usage: $0 [--container NAME] [--env-file FILE] [--output DIR] [ID...]" >&2; exit 2 ;;
	*) ids+=("$1"); shift ;;
	esac
done
require_cmd docker jq
container_running "$container" || die "container $container is not running"
if ((${#ids[@]} == 0)); then
	for file in "$root"/n8n/workflows/*.json; do
		ids+=("$(basename "$file" .json)")
	done
fi

# Alert addresses, turned back into placeholders.
env_value() { [[ -f "$env_file" ]] && grep -E "^$1=" "$env_file" | tail -1 | cut -d= -f2- | tr -d "'\"" || true; }
from=$(env_value ALERT_EMAIL_FROM)
to=$(env_value ALERT_EMAIL_TO)

mkdir -p "$output"
for id in "${ids[@]}"; do
	[[ "$id" =~ ^[A-Za-z0-9]{16}$ ]] || die "invalid workflow id: $id"
	# The paths are inside the container: kept away from Git Bash path conversion.
	export=$(docker exec "$container" sh -c \
		'n8n export:workflow --id="$1" --output=/tmp/nyansa-export.json >/dev/null 2>&1 && cat /tmp/nyansa-export.json; rm -f /tmp/nyansa-export.json' \
		_ "$id") || die "workflow $id not found in $container"
	jq --arg from "$from" --arg to "$to" '
		.[0]
		| {id, name, active, nodes, connections, settings, pinData: {}, tags: []}
		| walk(if type == "string" and . != "" and (. == $from or . == $to)
			then (if . == $from then "__ALERT_EMAIL_FROM__" else "__ALERT_EMAIL_TO__" end) else . end)' \
		<<<"$export" >"$output/$id.json"
	log "exported $id to $output/$id.json"
done

if [[ "$output" == "$root/n8n/workflows" ]]; then
	bash "$root/scripts/check-n8n-workflows.sh"
fi
