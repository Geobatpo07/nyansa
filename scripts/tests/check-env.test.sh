#!/usr/bin/env bash
# Tests scripts/check-env.sh on temporary env files: missing names fail,
# unknown names warn, optional (commented) settings are not required, and
# no value ever appears in the output.
#
# Usage: scripts/tests/check-env.test.sh
set -Eeuo pipefail

# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/../lib.sh"

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
checker=$root/scripts/check-env.sh
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

cat >"$work/example" <<'ENV'
# Comment
POSTGRES_PASSWORD=change_me
MEMORY_API_TOKEN=change_me
SMTP_HOST=
# CONTEXT_MIN_SCORE=0.65
ENV

failures=0
# check LABEL ENV_CONTENT EXPECTED_STATUS EXPECTED_TEXT...: runs the checker on
# an env file, then expects the exit status, each text in the output, and no
# value of the file in the output.
check() {
	local label=$1 content=$2 expected_status=$3 status=0 output text ok=1
	shift 3
	printf '%s' "$content" >"$work/env"
	output=$(bash "$checker" "$work/env" --example "$work/example" 2>&1) || status=$?
	((status == expected_status)) || ok=0
	for text in "$@"; do
		[[ "$output" == *"$text"* ]] || ok=0
	done
	[[ "$output" != *secret-value* ]] || ok=0
	if ((ok)); then
		echo "ok   $label"
	else
		echo "FAIL $label (exit $status)" >&2
		indent <<<"$output" >&2
		failures=$((failures + 1))
	fi
}

check "a complete file passes" \
	$'POSTGRES_PASSWORD=secret-value\nMEMORY_API_TOKEN="secret-value"\r\nSMTP_HOST=\n' 0 "defines every variable"
check "missing names are listed and fail" \
	$'POSTGRES_PASSWORD=secret-value\n# MEMORY_API_TOKEN=secret-value\n' 1 "MEMORY_API_TOKEN" "SMTP_HOST" "2 variable(s) missing"
check "unknown names only warn" \
	$'POSTGRES_PASSWORD=secret-value\nMEMORY_API_TOKEN=secret-value\nSMTP_HOST=x\nMEMORY_API_TOKN=secret-value\n' 0 \
	"WARNING" "MEMORY_API_TOKN"
check "export and spaces are understood" \
	$'export POSTGRES_PASSWORD=secret-value\n  MEMORY_API_TOKEN=secret-value\nSMTP_HOST=\n' 0 "defines every variable"
check "the repository's .env.example is complete" "$(cat "$root/.env.example")" 0 "defines every variable"

((failures == 0)) || die "$failures check-env test(s) failed"
log "check-env tests passed"
