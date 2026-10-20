#!/usr/bin/env bash
# Checks the n8n workflows and credentials of the repository:
#   - every webhook requires Header Auth (Caddy lets /webhook* through
#     without basic auth), and no chat trigger is used (it has no Header Auth);
#   - no pinned data is exported with a workflow;
#   - every credential a node uses is versioned in n8n/credentials, with the
#     same type, and no credential file holds a secret (secrets come from
#     .env through CREDENTIALS_OVERWRITE_DATA);
#   - the alert e-mail addresses are placeholders, replaced at import time;
#   - memory-api is only called on the internal network;
#   - each file is named after the 16-character id it contains.
#
# Usage: scripts/check-n8n-workflows.sh [--dir n8n]
set -Eeuo pipefail

# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/n8n
while (($# > 0)); do
	case "$1" in
	--dir) dir=$2; shift 2 ;;
	*) echo "usage: $0 [--dir DIR]" >&2; exit 2 ;;
	esac
done
[[ -d "$dir/workflows" && -d "$dir/credentials" ]] || die "no workflows/ and credentials/ in $dir"
require_cmd jq

# Credential types by id, from the versioned credential files.
credentials=$(jq -s 'map({(.id): .type}) | add // {}' "$dir"/credentials/*.json)

# One line per violation; empty output means the file is compliant.
read -r -d '' WORKFLOW_RULES <<'JQ' || true
. as $wf | .nodes[] | . as $node | "\($wf.name) > \($node.name)" as $where |
(
  select($node.type == "n8n-nodes-base.webhook")
  | select($node.parameters.authentication != "headerAuth" or $node.credentials.httpHeaderAuth == null)
  | "\($where): webhook without Header Auth"
),
( select($node.type | endswith(".chatTrigger")) | "\($where): chat trigger (no Header Auth possible), use a webhook" ),
(
  ($node.credentials // {}) | to_entries[]
  | select($credentials[.value.id] != .key)
  | "\($where): credential \(.value.id) (\(.key)) is not in n8n/credentials with this type"
),
(
  select($node.type == "n8n-nodes-base.emailSend")
  | ([$node.parameters.fromEmail, $node.parameters.toEmail] - ["__ALERT_EMAIL_FROM__", "__ALERT_EMAIL_TO__"])[]
  | "\($where): e-mail address \(.) must be a placeholder (__ALERT_EMAIL_FROM__ or __ALERT_EMAIL_TO__)"
),
(
  $node.parameters.url? // empty | strings
  | select(test("memory-api") and (startswith("http://nyansa-memory-api:8080/") or startswith("=http://nyansa-memory-api:8080/") | not))
  | "\($where): memory-api must be called at http://nyansa-memory-api:8080"
)
JQ

failures=0
report() { # report FILE VIOLATIONS
	if [[ -n "$2" ]]; then
		echo "FAIL $1" >&2
		indent <<<"$2" >&2
		failures=$((failures + 1))
	else
		echo "ok   $1"
	fi
}

for file in "$dir"/workflows/*.json; do
	name=$(basename "$file" .json)
	violations=$(jq -r --argjson credentials "$credentials" --arg name "$name" "
		(select(.id != \$name or (.id | test(\"^[A-Za-z0-9]{16}\$\") | not)) | \"file name must be the 16-character id (\(.id))\"),
		(select((.pinData // {}) != {}) | \"pinned data must not be exported\"),
		($WORKFLOW_RULES)" "$file")
	report "workflows/$name.json" "$violations"
done

for file in "$dir"/credentials/*.json; do
	name=$(basename "$file" .json)
	violations=$(jq -r --arg name "$name" '
		(select(.id != $name) | "file name must be the credential id (\(.id))"),
		((.data // {}) | keys[] | select(test("token|value|password|secret|key|user"; "i"))
			| "field \(.) looks like a secret: it must come from .env (CREDENTIALS_OVERWRITE_DATA)")' "$file")
	report "credentials/$name.json" "$violations"
done

((failures == 0)) || die "$failures n8n file(s) break the rules"
log "n8n workflows and credentials satisfy the rules"
