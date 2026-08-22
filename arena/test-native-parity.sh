#!/bin/sh
# Copyright (C) 2026 Arena contributors. GPLv2+; see COPYING.txt.
# Public 100-match native-authority/browser parity entry point.
set -eu

test "$#" -ge 2 && test "$1" = "--matches" && test "$2" = 100 || {
    echo "usage: $0 --matches 100 [--shard-index N --shard-count N]" >&2
    exit 2
}
shift 2
shard_index=${ARENA_PARITY_SHARD_INDEX:-0}
shard_count=${ARENA_PARITY_SHARD_COUNT:-1}
while test "$#" -gt 0; do
    test "$#" -ge 2 || exit 2
    case "$1" in
        --shard-index) shard_index=$2 ;;
        --shard-count) shard_count=$2 ;;
        *) echo "unsupported parity argument: $1" >&2; exit 2 ;;
    esac
    shift 2
done
export ARENA_PARITY_SHARD_INDEX=$shard_index ARENA_PARITY_SHARD_COUNT=$shard_count
exec "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/ci-native-browser-parity.sh"
