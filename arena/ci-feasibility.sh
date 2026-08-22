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
mkdir -p "$runtime_dir/server" "$runtime_dir/evidence" "$runtime_dir/roster"
chmod 0777 "$runtime_dir/server" "$runtime_dir/evidence" "$runtime_dir/roster"

export ARENA_RUNTIME_TAG=arena-native-runtime:ci
export ARENA_RELAY_SECRET=ci-only-ephemeral-relay-secret-material
shape_loss_every=${ARENA_SHAPE_LOSS_EVERY:-0}
case "$shape_loss_every" in
    0|*[!0-9]*) test "$shape_loss_every" = 0 || {
        echo "ARENA_SHAPE_LOSS_EVERY must be 0 or an integer of at least 2" >&2
        exit 1
    } ;;
    1) echo "ARENA_SHAPE_LOSS_EVERY must be 0 or an integer of at least 2" >&2; exit 1 ;;
esac
set --
if test "$shape_loss_every" -ge 2; then
    set -- \
        --drop-browser-to-native-every "$shape_loss_every" \
        --drop-native-to-browser-every "$shape_loss_every"
fi

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
    -e ARENA_ROSTER_DIR=/arena/roster \
    -v "$runtime_dir/server:/arena/var" \
    -v "$runtime_dir/roster:/arena/roster:ro" \
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
    -v "$runtime_dir/roster:/roster" \
    -w /src \
    "$EMSDK_IMAGE_LINUX_AMD64" \
    python3 arena/relay.py \
        --allow-origin http://127.0.0.1:8000 \
        --roster-dir /roster \
        --evidence /evidence/relay.jsonl \
        "$@" >/dev/null

printf '{"dropBrowserToNativeEvery":%s,"dropNativeToBrowserEvery":%s}\n' \
    "$shape_loss_every" "$shape_loss_every" >"$runtime_dir/evidence/profile.json"

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

python3 - "$runtime_dir/evidence/relay.jsonl" "$shape_loss_every" <<'PY'
import collections
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
loss_every = int(sys.argv[2])
directions = collections.Counter()
sessions = {}
for line in path.read_text(encoding="utf-8").splitlines():
    entry = json.loads(line)
    assert 0 <= entry["size"] <= 2048
    directions[entry["direction"]] += 1
    sessions.setdefault(entry["session"], collections.Counter())[entry["direction"]] += 1
if loss_every:
    for session in ("chrome-1v1", "firefox-1v1"):
        assert sessions[session]["browser_to_native_dropped"] > 0
        assert sessions[session]["native_to_browser_dropped"] > 0
summary = {
    session: dict(sorted(counts.items()))
    for session, counts in sorted(sessions.items())
}
(path.parent / "shape-summary.json").write_text(
    json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(json.dumps(summary, sort_keys=True))
PY

docker stop -t 10 arena-native >/dev/null
docker wait arena-native >/dev/null 2>&1 || true
grep '^GAME_END ' "$runtime_dir/server/ladderlog.txt" >"$runtime_dir/evidence/game-end.log"

(
    cd "$runtime_dir"
    find server evidence -type f -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
)

trap - EXIT INT TERM
cleanup
