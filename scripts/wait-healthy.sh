#!/usr/bin/env bash
# Waits until every container of the Nyansa Compose project is ready:
#   - running containers with a healthcheck are "healthy";
#   - running containers without a healthcheck count as ready;
#   - one-shot containers (model pull, n8n import) exited with code 0.
# Fails immediately when a container exits with a non-zero code, and after
# the timeout when something is still starting, restarting or unhealthy.
#
# Usage: scripts/wait-healthy.sh [timeout-seconds]   (default: 300)
set -Eeuo pipefail

# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

timeout=${1:-300}
require_cmd docker

deadline=$((SECONDS + timeout))
while :; do
	mapfile -t ids < <(docker ps -aq --filter "label=com.docker.compose.project=$NYANSA_PROJECT")
	((${#ids[@]} > 0)) || die "no container found for project $NYANSA_PROJECT"

	pending=()
	failed=()
	while read -r name state health code; do
		name=${name#/}
		case "$state" in
		running) [[ "$health" == "-" || "$health" == "healthy" ]] || pending+=("$name ($health)") ;;
		exited) [[ "$code" == "0" ]] || failed+=("$name (exit code $code)") ;;
		*) pending+=("$name ($state)") ;;
		esac
	done < <(docker inspect --format \
		'{{.Name}} {{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}-{{end}} {{.State.ExitCode}}' \
		"${ids[@]}")

	if ((${#failed[@]} > 0)); then
		die "container(s) failed: ${failed[*]}"
	fi
	if ((${#pending[@]} == 0)); then
		log "all ${#ids[@]} containers are ready"
		exit 0
	fi
	if ((SECONDS >= deadline)); then
		die "timeout after ${timeout}s, not ready: ${pending[*]}"
	fi
	log "waiting for: ${pending[*]}"
	sleep 5
done
