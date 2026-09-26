#!/usr/bin/env bash
# Builds a self-contained release folder from a commit. Production runs from
# such a folder, never from a working tree.
#
#   1. Exports the commit with `git archive` (uncommitted files never leak in).
#   2. Copies only what is needed at runtime (RUNTIME_PATHS below): no docs,
#      tests, hooks or development files.
#   3. Writes RELEASE (commit, branch, dates).
#   4. Validates the result: `docker compose config` and check-exposure.sh
#      run against the release folder itself, with the commit's .env.example.
#
# Works in a normal clone and in a bare repository (the post-receive hook).
#
# Usage: scripts/build-publish.sh [--output DIR] [--branch NAME] [--no-validate] <commit>
#   --output   destination (default: <repo>/publish; required in a bare repo)
#   --branch   branch name written to RELEASE (default: guessed from refs)
set -Eeuo pipefail

# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

# Paths copied from the commit into the release. Directories are copied
# whole. services/memory-api (phase 2) will be added here with its build
# output only.
RUNTIME_PATHS=(
	docker-compose.yml
	caddy
	n8n
	scripts/lib.sh
	scripts/backup.sh
	scripts/restore.sh
	scripts/check-exposure.sh
	scripts/wait-healthy.sh
)

usage() {
	echo "usage: $0 [--output DIR] [--branch NAME] [--no-validate] <commit>" >&2
	exit 2
}

output=
branch=
validate=1
commit=
while (($# > 0)); do
	case "$1" in
	--output) output=$2; shift 2 ;;
	--branch) branch=$2; shift 2 ;;
	--no-validate) validate=0; shift ;;
	-*) usage ;;
	*) [[ -z "$commit" ]] || usage; commit=$1; shift ;;
	esac
done
[[ -n "$commit" ]] || usage

require_cmd git tar
sha=$(git rev-parse --verify --quiet "$commit^{commit}") || die "unknown commit: $commit"

if [[ -z "$output" ]]; then
	[[ "$(git rev-parse --is-bare-repository)" == "false" ]] || die "--output is required in a bare repository"
	output=$(git rev-parse --show-toplevel)/publish
fi
if [[ -z "$branch" ]]; then
	branch=$(git name-rev --name-only --no-undefined --refs='refs/heads/*' "$sha" 2>/dev/null || echo unknown)
	branch=${branch%%[~^]*}
fi

# Only replace a folder that is empty or a previous release, never an
# arbitrary directory passed by mistake.
if [[ -e "$output" ]]; then
	if [[ -f "$output/RELEASE" ]] || [[ -d "$output" && -z "$(ls -A "$output")" ]]; then
		rm -rf "$output"
	else
		die "$output exists and is not a release folder; refusing to overwrite it"
	fi
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

log "exporting ${sha:0:12} ($branch)"
mkdir "$work/src"
git archive --format=tar "$sha" | tar -x -C "$work/src"

mkdir -p "$output"
for path in "${RUNTIME_PATHS[@]}"; do
	[[ -e "$work/src/$path" ]] || die "missing runtime path in commit: $path"
	mkdir -p "$output/$(dirname "$path")"
	cp -R "$work/src/$path" "$output/$path"
done
chmod +x "$output"/scripts/*.sh

cat >"$output/RELEASE" <<EOF
commit=$sha
short=${sha:0:12}
branch=$branch
commit_date=$(git show -s --format=%cI "$sha")
built_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF

# A release must never carry an environment file.
if leaked=$(find "$output" -name '.env*' -print -quit) && [[ -n "$leaked" ]]; then
	die "release contains an environment file: $leaked"
fi

if ((validate)); then
	[[ -f "$work/src/.env.example" ]] || die ".env.example is missing from the commit"
	log "validating the release folder"
	bash "$output/scripts/check-exposure.sh" \
		--file "$output/docker-compose.yml" \
		--env-file "$work/src/.env.example"
fi

log "release ${sha:0:12} ready in $output ($(find "$output" -type f | wc -l | tr -d ' ') files)"
