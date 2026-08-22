#!/bin/sh
# Copyright (C) 2026 Arena contributors. GPLv2+; see COPYING.txt.
# Safari interoperability only; production native authority remains linux/amd64.
set -eu

arena_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(dirname "$arena_dir")
. "$arena_dir/pins.env"

test "$(uname -s)" = Darwin && test "$(uname -m)" = x86_64 || {
    echo "Safari interoperability requires an Intel macOS runner" >&2
    exit 1
}
test "${ImageVersion-}" = "$MACOS_INTEROP_IMAGE_VERSION"
safari_version=$(defaults read /Applications/Safari.app/Contents/Info CFBundleShortVersionString)
test "$safari_version" = "$SAFARI_INTEROP_VERSION" || {
    echo "expected Safari $SAFARI_INTEROP_VERSION, got $safari_version" >&2
    exit 1
}

stage_dir="$repo_dir/build/native-macos-interoperability/stage"
runtime_dir="$repo_dir/build/runtime"
test -x "$stage_dir/armagetronad-dedicated"
test -f "$repo_dir/build/web/SHA256SUMS"
(cd "$repo_dir/build/web" && shasum -a 256 -c SHA256SUMS)
test ! -L "$repo_dir/build" && test ! -L "$runtime_dir" || {
    echo "refusing symlinked runtime path" >&2
    exit 1
}
rm -rf "$runtime_dir"
mkdir -p "$runtime_dir/server" "$runtime_dir/evidence" "$runtime_dir/python"

wheel="$runtime_dir/python/websockets-15.0.1-py3-none-any.whl"
curl --fail --location --silent --show-error "$WEBSOCKETS_WHEEL_URL" -o "$wheel"
printf '%s  %s\n' "$WEBSOCKETS_WHEEL_SHA256" "$wheel" | shasum -a 256 -c -
python3 -m pip install --disable-pip-version-check --no-deps --no-index \
    --target "$runtime_dir/python" "$wheel"
export PYTHONPATH="$runtime_dir/python"
export ARENA_RELAY_SECRET=ci-only-ephemeral-relay-secret-material
export ARENA_SAFARI_WEBDRIVER_URL=http://127.0.0.1:4444

native_pid=
static_pid=
relay_pid=
webdriver_pid=
stop_process() {
    pid=$1
    test -n "$pid" || return 0
    kill "$pid" >/dev/null 2>&1 || true
    wait "$pid" >/dev/null 2>&1 || true
}
cleanup() {
    stop_process "$webdriver_pid"
    stop_process "$relay_pid"
    stop_process "$static_pid"
    stop_process "$native_pid"
}
trap cleanup EXIT HUP INT TERM

"$stage_dir/armagetronad-dedicated" \
    --datadir "$stage_dir/data" \
    --configdir "$stage_dir/data/config" \
    --userconfigdir "$runtime_dir/server" \
    --vardir "$runtime_dir/server" \
    --resourcedir "$stage_dir/data/resource" \
    --autoresourcedir "$runtime_dir/server/resource-cache" \
    --record "$runtime_dir/server/match.aarec" \
    --extraconfig arena.cfg \
    >"$runtime_dir/evidence/native.log" 2>&1 &
native_pid=$!

python3 "$arena_dir/static_server.py" \
    --port 8000 --host 127.0.0.1 --directory "$repo_dir/build/web" \
    >"$runtime_dir/evidence/static.log" 2>&1 &
static_pid=$!

python3 "$arena_dir/relay.py" \
    --allow-origin http://127.0.0.1:8000 \
    --evidence "$runtime_dir/evidence/relay.jsonl" \
    >"$runtime_dir/evidence/relay.log" 2>&1 &
relay_pid=$!

sudo /usr/bin/safaridriver --enable
/usr/bin/safaridriver --port 4444 >"$runtime_dir/evidence/safaridriver.log" 2>&1 &
webdriver_pid=$!

ready=false
for attempt in $(seq 1 120); do
    if python3 -c \
        "import json,urllib.request; assert json.load(urllib.request.urlopen('http://127.0.0.1:4444/status',timeout=2))['value']['ready']" \
        >/dev/null 2>&1 && \
       python3 -c \
        "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/armagetronad_main.html',timeout=2)" \
        >/dev/null 2>&1 && kill -0 "$native_pid" && kill -0 "$relay_pid"; then
        ready=true
        break
    fi
    sleep 1
done
test "$ready" = true || {
    echo "Safari runtime did not become ready" >&2
    exit 1
}

"$arena_dir/test-browser.sh" --browsers safari

released=false
for attempt in $(seq 1 60); do
    if grep -q '^PLAYER_LEFT safari1 ' "$runtime_dir/server/ladderlog.txt" && \
       grep -q '^PLAYER_LEFT safari2 ' "$runtime_dir/server/ladderlog.txt"; then
        released=true
        break
    fi
    sleep 1
done
test "$released" = true || {
    echo "Safari clients did not leave the native server" >&2
    exit 1
}

kill -TERM "$native_pid"
wait "$native_pid" >/dev/null 2>&1 || true
native_pid=
grep '^GAME_END ' "$runtime_dir/server/ladderlog.txt" > "$runtime_dir/evidence/game-end.log"
{
    printf 'safari=%s\n' "$safari_version"
    /usr/bin/safaridriver --version
    printf 'source_commit=%s\n' "$(git -C "$repo_dir" rev-parse HEAD)"
    printf 'image_version=%s\n' "$ImageVersion"
} > "$runtime_dir/evidence/safari-versions.txt"
(
    cd "$runtime_dir"
    find server evidence -type f -print0 | LC_ALL=C sort -z | xargs -0 shasum -a 256 > SHA256SUMS
)

trap - EXIT HUP INT TERM
cleanup
