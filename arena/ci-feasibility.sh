#!/bin/sh
# Copyright (C) 2026 Arena contributors. GPLv2+; see COPYING.txt.
set -eu

arena_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(dirname "$arena_dir")
. "$arena_dir/pins.env"

test "$(uname -m)" = x86_64 || {
    echo "authoritative runtime feasibility requires a linux/amd64 runner" >&2
    exit 1
}

runtime_dir="$repo_dir/build/runtime"
rm -rf "$runtime_dir"
mkdir -p "$runtime_dir/server" "$runtime_dir/evidence"
chmod 0777 "$runtime_dir/server" "$runtime_dir/evidence"

export ARENA_RUNTIME_TAG=arena-native-runtime:ci
export ARENA_RELAY_SECRET=ci-only-ephemeral-relay-secret-material

cleanup() {
    docker logs arena-native >"$runtime_dir/evidence/native.log" 2>&1 || true
    docker logs arena-relay >"$runtime_dir/evidence/relay.log" 2>&1 || true
    docker logs arena-static >"$runtime_dir/evidence/static.log" 2>&1 || true
    docker rm -f arena-native arena-relay arena-static \
        arena-webdriver-chrome arena-webdriver-firefox >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

"$arena_dir/build-runtime.sh" --platform linux/amd64

docker run -d \
    --name arena-native \
    --platform linux/amd64 \
    --network host \
    -v "$runtime_dir/server:/arena/var" \
    "$ARENA_RUNTIME_TAG" >/dev/null

docker run -d \
    --name arena-static \
    --platform linux/amd64 \
    --network host \
    -v "$repo_dir:/src:ro" \
    -v "$repo_dir/build/web:/web:ro" \
    -w /src \
    "$EMSDK_IMAGE_LINUX_AMD64" \
    python3 arena/static_server.py --port 8000 --host 127.0.0.1 --directory /web >/dev/null

docker run -d \
    --name arena-relay \
    --platform linux/amd64 \
    --network host \
    -e ARENA_RELAY_SECRET \
    -v "$repo_dir:/src:ro" \
    -v "$runtime_dir/evidence:/evidence" \
    -w /src \
    "$EMSDK_IMAGE_LINUX_AMD64" \
    python3 arena/relay.py \
        --allow-origin http://127.0.0.1:8000 \
        --evidence /evidence/relay.jsonl >/dev/null

for attempt in $(seq 1 30); do
    if docker run --rm --platform linux/amd64 --network host \
        "$EMSDK_IMAGE_LINUX_AMD64" \
        python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/armagetronad_main.html', timeout=2)"; then
        break
    fi
    test "$attempt" -lt 30 || exit 1
    sleep 1
done

"$arena_dir/test-browser.sh" --browsers chrome,firefox

docker stop -t 10 arena-native >/dev/null
docker wait arena-native >/dev/null 2>&1 || true

(
    cd "$runtime_dir"
    find server evidence -type f -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
)

trap - EXIT INT TERM
cleanup
