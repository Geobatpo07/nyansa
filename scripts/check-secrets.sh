#!/usr/bin/env bash
# Refuses a revision that tracks secrets:
#   - files: .env and .env.* (except .env.example), private keys and
#     keystores;
#   - content: private key blocks, Tailscale auth keys, bcrypt hashes,
#     GitHub tokens and AWS access keys.
# Placeholders in .env.example are written so that they never match.
#
# Usage: scripts/check-secrets.sh [revision]   (default: HEAD)
set -Eeuo pipefail

# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

rev=${1:-HEAD}
require_cmd git
git rev-parse --verify --quiet "$rev^{commit}" >/dev/null || die "unknown revision: $rev"

FILE_PATTERN='(^|/)\.env(\..+)?$|\.(pem|key|p12|pfx|jks|kdbx)$|(^|/)id_(rsa|dsa|ecdsa|ed25519)$'
ALLOWED_FILES='(^|/)\.env\.example$'

CONTENT_PATTERNS=(
	'-----BEGIN [A-Z ]*PRIVATE KEY-----'
	'tskey-[a-z]+-[A-Za-z0-9]{8,}-[A-Za-z0-9]{16,}'
	'\$2[aby]\$[0-9]{2}\$[./A-Za-z0-9]{53}([^./A-Za-z0-9]|$)'
	'gh[pousr]_[A-Za-z0-9]{36}'
	'AKIA[0-9A-Z]{16}'
)

found=0

files=$(git ls-tree -r --name-only "$rev" | grep -E "$FILE_PATTERN" | grep -Ev "$ALLOWED_FILES" || true)
if [[ -n "$files" ]]; then
	echo "Secret files tracked in $rev:" >&2
	sed 's/^/  - /' <<<"$files" >&2
	found=1
fi

grep_args=()
for pattern in "${CONTENT_PATTERNS[@]}"; do
	grep_args+=(-e "$pattern")
done
# This script contains the patterns themselves.
matches=$(git grep -I -n -E "${grep_args[@]}" "$rev" -- . ':!scripts/check-secrets.sh' || true)
if [[ -n "$matches" ]]; then
	echo "Possible secrets in tracked content of $rev:" >&2
	sed 's/^/  - /' <<<"$matches" >&2
	found=1
fi

((found == 0)) || die "remove the secrets from history before pushing"
log "no tracked secret found in $rev"
