#!/bin/sh
# Copyright (C) 2026 Arena contributors. GPLv2+; see COPYING.txt.
set -eu

arena_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(dirname "$arena_dir")
native_client=${ARENA_NATIVE_PARITY_CLIENT:-$repo_dir/build/native-parity/amd64/armagetronad}
input_manifest=${ARENA_PARITY_INPUT_MANIFEST:-$repo_dir/build/parity-inputs/INPUT-MANIFEST.json}
trial_command=${ARENA_PARITY_TRIAL_COMMAND:-$arena_dir/native-browser-parity-trial.sh}
shard_index=${ARENA_PARITY_SHARD_INDEX:-0}
shard_count=${ARENA_PARITY_SHARD_COUNT:-1}

test -x "$native_client" || {
    echo "native graphical parity client missing: $native_client" >&2
    exit 1
}
test -x "$trial_command" || {
    echo "native/browser parity trial command missing: $trial_command" >&2
    exit 1
}
test "${ARENA_NATIVE_PARITY_IMAGE:-}" != '' || {
    echo "ARENA_NATIVE_PARITY_IMAGE must identify the pinned native parity image" >&2
    exit 1
}
native_file_sha=$(sha256sum "$native_client" | awk '{print $1}')
native_image_sha=$(docker run --rm --entrypoint sha256sum \
    "$ARENA_NATIVE_PARITY_IMAGE" /usr/local/bin/armagetronad | awk '{print $1}')
server_file_sha=$(sha256sum "$repo_dir/build/native/amd64/armagetronad-dedicated" | awk '{print $1}')
server_image_sha=$(docker run --rm --entrypoint sha256sum \
    arena-native-runtime:parity /usr/local/bin/armagetronad-dedicated | awk '{print $1}')
test "$native_file_sha" = "$native_image_sha" || {
    echo "native graphical image binary differs from the verified artifact" >&2
    exit 1
}
test "$server_file_sha" = "$server_image_sha" || {
    echo "native server image binary differs from the verified artifact" >&2
    exit 1
}

export ARENA_NATIVE_PARITY_CLIENT=$native_client
export ARENA_PARITY_INPUT_MANIFEST=$input_manifest
export ARENA_NATIVE_PARITY_IMAGE
exec python3 "$arena_dir/parity.py" \
    --evidence-dir "$repo_dir/build/parity/evidence" \
    --runtime-dir "$repo_dir/build/parity/runtime" \
    --trials 100 --shard-index "$shard_index" --shard-count "$shard_count" --timeout 3300 \
    --input-manifest "$input_manifest" \
    --source-commit "$(git -C "$repo_dir" rev-parse HEAD)" -- \
    "$trial_command"
