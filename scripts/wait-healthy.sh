#!/usr/bin/env bash
# Waits until every container of the Nyansa Compose project is ready:
#   - running containers with a healthcheck are "healthy";
#   - running containers without a healthcheck count as ready;
#   - one-shot containers (model pull, n8n import) exited with code 0.
# Fails immediately when a container exits with a non-zero code or is in a
# crash loop (not ready after CRASH_LOOP_RESTARTS restarts), and after the
# timeout when something is still starting or unhealthy.
#
# Usage: scripts/wait-healthy.sh [timeout-seconds]   (default: 300)
set -Eeuo pipefail

# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

timeout=${1:-300}
# Restarts by the restart policy after which a container that is still not
# ready is considered broken. Restarts of a container that is ready now
# (older incidents) are ignored.
CRASH_LOOP_RESTARTS=3
require_cmd docker

deadline=$((SECONDS + timeout))
while :; do
	mapfile -t ids < <(docker ps -aq --filter "label=com.docker.compose.project=$NYANSA_PROJECT")
	((${#ids[@]} > 0)) || die "no container found for project $NYANSA_PROJECT"

	pending=()
	failed=()
	while read -r name state health code restarts; do
		name=${name#/}
		if [[ "$state" == "running" && ("$health" == "-" || "$health" == "healthy") ]]; then
			continue
		fi
		if [[ "$state" == "exited" && "$code" == "0" ]]; then
			continue
		fi
		if [[ "$state" == "exited" || "$state" == "dead" ]]; then
			failed+=("$name (exit code $code)")
		elif ((restarts >= CRASH_LOOP_RESTARTS)); then
			failed+=("$name (crash loop: $restarts restarts)")
		elif [[ "$health" == "-" ]]; then
			pending+=("$name ($state)")
		else
			pending+=("$name ($health)")
		fi
	done < <(docker inspect --format \
		'{{.Name}} {{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}-{{end}} {{.State.ExitCode}} {{.RestartCount}}' \
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
