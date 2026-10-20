#!/usr/bin/env bash
# Tests scripts/check-n8n-workflows.sh: the repository's n8n files pass, and
# each rule catches its violation. Every case runs on a temporary copy of n8n/.
#
# Usage: scripts/tests/check-n8n-workflows.test.sh
set -Eeuo pipefail

# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/../lib.sh"

require_cmd jq
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
checker=$root/scripts/check-n8n-workflows.sh
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

failures=0
# check LABEL FILE JQ_EDIT EXPECTED: applies the edit to FILE (relative to n8n/)
# in a fresh copy, then expects the checker to pass (EXPECTED empty) or to
# fail with EXPECTED in its output.
check() {
	local label=$1 file=$2 edit=$3 expected=$4 status=0 output
	rm -rf "$work/n8n"
	cp -r "$root/n8n" "$work/n8n"
	if [[ -n "$edit" ]]; then
		jq "$edit" "$work/n8n/$file" >"$work/edited.json"
		mv "$work/edited.json" "$work/n8n/$file"
	fi
	output=$(bash "$checker" --dir "$work/n8n" 2>&1) || status=$?
	if { [[ -z "$expected" ]] && ((status == 0)); } || { [[ -n "$expected" ]] && ((status != 0)) && [[ "$output" == *"$expected"* ]]; }; then
		echo "ok   $label"
	else
		echo "FAIL $label (exit $status)" >&2
		indent <<<"$output" >&2
		failures=$((failures + 1))
	fi
}

chat=workflows/nyChatWithNotes1.json
ingest=workflows/nyIngestSchedule.json
alerts=workflows/nyAlertsOnError1.json

check "the repository's files pass" "$chat" "" ""
check "a webhook without Header Auth" "$chat" \
	'(.nodes[] | select(.type == "n8n-nodes-base.webhook") | .parameters.authentication) = "none"' "webhook without Header Auth"
check "a chat trigger" "$chat" \
	'.nodes += [{"name": "Chat", "type": "@n8n/n8n-nodes-langchain.chatTrigger", "parameters": {"public": true}}]' "chat trigger"
check "pinned data" "$chat" '.pinData = {"Question": [{"json": {"question": "x"}}]}' "pinned data"
check "an unknown credential" "$ingest" \
	'(.nodes[] | select(.name == "Start the ingestion") | .credentials.httpBearerAuth.id) = "unknownCredId123"' "unknownCredId123"
check "a credential used with another type" "$ingest" \
	'(.nodes[] | select(.name == "Start the ingestion") | .credentials) = {"httpHeaderAuth": {"id": "nyMemoryApiCred1"}}' \
	"is not in n8n/credentials with this type"
check "a real e-mail address" "$alerts" \
	'(.nodes[] | select(.type == "n8n-nodes-base.emailSend") | .parameters.toEmail) = "someone@example.org"' \
	"must be a placeholder"
check "memory-api through a public URL" "$ingest" \
	'(.nodes[] | select(.name == "Start the ingestion") | .parameters.url) = "https://memory-api.example.org/ingest"' \
	"must be called at http://nyansa-memory-api:8080"
check "a file not named after its id" "$alerts" '.id = "otherId1234567890"' "file name must be the 16-character id"
check "a secret in a credential file" credentials/nyWebhookToken01.json '.data.value = "a-real-token"' \
	"field value looks like a secret"

((failures == 0)) || die "$failures check-n8n-workflows test(s) failed"
log "check-n8n-workflows tests passed"
