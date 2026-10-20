#!/usr/bin/env bash
# Compares the variable names of an env file with those of .env.example:
#   - names of .env.example missing from the file: error;
#   - names of the file unknown to .env.example (a typo?): warning.
# Only names are read and printed, never a value. Commented lines of
# .env.example (optional settings) are not required.
#
# Usage: scripts/check-env.sh <env-file> [--example FILE]
# Example, on the server before deploying:
#   scripts/check-env.sh /opt/nyansa/shared/.env
set -Eeuo pipefail

# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

example=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/.env.example
env_file=

while (($# > 0)); do
	case "$1" in
	--example) example=$2; shift 2 ;;
	-*) echo "usage: $0 <env-file> [--example FILE]" >&2; exit 2 ;;
	*) [[ -z "$env_file" ]] || { echo "usage: $0 <env-file> [--example FILE]" >&2; exit 2; }; env_file=$1; shift ;;
	esac
done
[[ -n "$env_file" ]] || { echo "usage: $0 <env-file> [--example FILE]" >&2; exit 2; }
[[ -f "$env_file" ]] || die "env file not found: $env_file"
[[ -f "$example" ]] || die "example file not found: $example"

# Variable names assigned on uncommented lines, sorted and unique.
names() { sed -nE 's/^[[:space:]]*(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)=.*/\2/p' "$1" | sort -u; }

missing=$(comm -23 <(names "$example") <(names "$env_file"))
unknown=$(comm -13 <(names "$example") <(names "$env_file"))

if [[ -n "$unknown" ]]; then
	warn "not in $(basename "$example") (typo or leftover?):"
	indent <<<"$unknown" >&2
fi
if [[ -n "$missing" ]]; then
	echo "missing from $env_file:" >&2
	indent <<<"$missing" >&2
	die "$(wc -l <<<"$missing") variable(s) missing"
fi
log "$env_file defines every variable of $(basename "$example")"
