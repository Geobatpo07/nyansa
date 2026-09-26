#!/usr/bin/env bash
# Installs the versioned Git hooks.
#
#   scripts/install-hooks.sh
#       Development machine: points core.hooksPath at hooks/, which enables
#       hooks/pre-push for this clone.
#
#   scripts/install-hooks.sh --remote <ssh-host> [<bare-repo-path>]
#       Copies hooks/post-receive into the bare repository on the server
#       (default path: nyansa.git in the remote user's home). Run it again
#       after changing hooks/post-receive.
set -Eeuo pipefail

# shellcheck source=scripts/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

case "${1:-}" in
"")
	git -C "$root" config core.hooksPath hooks
	log "core.hooksPath = hooks (pre-push enabled for $root)"
	;;
--remote)
	host=${2:?usage: $0 --remote <ssh-host> [<bare-repo-path>]}
	repo=${3:-nyansa.git}
	require_cmd scp ssh
	scp "$root/hooks/post-receive" "$host:$repo/hooks/post-receive"
	# shellcheck disable=SC2029 # $repo is meant to expand on this side
	ssh "$host" "chmod 755 '$repo/hooks/post-receive'"
	log "post-receive installed in $host:$repo"
	;;
*)
	echo "usage: $0 [--remote <ssh-host> [<bare-repo-path>]]" >&2
	exit 2
	;;
esac
