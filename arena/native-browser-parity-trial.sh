#!/bin/sh
# Copyright (C) 2026 Arena contributors. GPLv2+; see COPYING.txt.
# One shard of separate fresh-server native and browser parity matches.
set -eu

arena_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(dirname "$arena_dir")
. "$arena_dir/pins.env"
test "$#" -eq 6 && test "$1" = --matches && test "$2" = 100 && \
    test "$3" = --shard-index && test "$5" = --shard-count || exit 2
shard_index=$4
shard_count=$6
case "$shard_index:$shard_count" in *[!0-9:]*|*:*:*) exit 2;; esac
test "$shard_count" -gt 0 && test "$shard_index" -lt "$shard_count"
test -n "${ARENA_PARITY_EVIDENCE_DIR:-}" && test -n "${ARENA_PARITY_RUNTIME_DIR:-}"
test -x "${ARENA_NATIVE_PARITY_CLIENT:?}"
test -f "${ARENA_PARITY_INPUT_MANIFEST:?}"

evidence_dir=$ARENA_PARITY_EVIDENCE_DIR
runtime_root=$ARENA_PARITY_RUNTIME_DIR
source_commit=$(git -C "$repo_dir" rev-parse HEAD)
python3 "$arena_dir/parity.py" --verify-input-manifest "$ARENA_PARITY_INPUT_MANIFEST" \
    --source-commit "$source_commit"
current_index=

cleanup() {
    status=$?
    test -n "$current_index" || return "$status"
    if test "$status" -ne 0; then
        echo "parity trial $current_index failed; bounded container diagnostics follow" >&2
        for name in \
            "arena-parity-native-role1-$current_index" \
            "arena-parity-native-role2-$current_index" \
            "arena-parity-native-server-$current_index" \
            "arena-parity-browser-server-$current_index" \
            "arena-parity-static-$current_index" \
            "arena-parity-relay-$current_index" \
            "arena-parity-webdriver-$current_index"; do
            if docker container inspect "$name" >/dev/null 2>&1; then
                echo "container log: $name" >&2
                docker logs --tail 200 "$name" >&2 || true
            fi
        done
    fi
    docker rm -f \
        "arena-parity-native-role1-$current_index" \
        "arena-parity-native-role2-$current_index" \
        "arena-parity-native-server-$current_index" \
        "arena-parity-browser-server-$current_index" \
        "arena-parity-static-$current_index" \
        "arena-parity-relay-$current_index" \
        "arena-parity-webdriver-$current_index" >/dev/null 2>&1 || true
    return "$status"
}
trap cleanup EXIT HUP INT TERM

wait_log() {
    log=$1 pattern=$2
    for attempt in $(seq 1 180); do
        test -f "$log" && grep -q "$pattern" "$log" && return 0
        sleep 0.25
    done
    echo "timed out waiting for $pattern in $log" >&2
    test ! -f "$log" || tail -n 100 "$log" >&2
    return 1
}

write_record() {
    index=$1 browser=$2 native_dir=$3 browser_dir=$4
    native_log=$native_dir/server/ladderlog.txt
    browser_log=$browser_dir/server/ladderlog.txt
    native_rec=$native_dir/server/match.aarec
    browser_rec=$browser_dir/server/match.aarec
    raw_dir=$evidence_dir/raw/trial-$(printf %03d "$index")
    mkdir -p "$raw_dir/native" "$raw_dir/browser"
    cp "$native_log" "$raw_dir/native/ladderlog.txt"
    cp "$native_rec" "$raw_dir/native/match.aarec"
    cp "$browser_log" "$raw_dir/browser/ladderlog.txt"
    cp "$browser_rec" "$raw_dir/browser/match.aarec"
    cp "$browser_dir/evidence/$browser-states.json" "$raw_dir/browser/states.json"
    cp "$browser_dir/evidence/relay.jsonl" "$raw_dir/browser/relay.jsonl"
    cp "$native_dir/role1/input-evidence.log" "$raw_dir/native/input-role1.log"
    cp "$native_dir/role2/input-evidence.log" "$raw_dir/native/input-role2.log"
    python3 - "$evidence_dir/trials/trial-$(printf %03d "$index").json" \
        "$index" "$browser" "$source_commit" "$ARENA_PARITY_INPUT_MANIFEST" \
        "$raw_dir/native/ladderlog.txt" "$raw_dir/native/match.aarec" \
        "$raw_dir/browser/ladderlog.txt" "$raw_dir/browser/match.aarec" \
        "$raw_dir/native/input-role1.log" "$raw_dir/native/input-role2.log" \
        "$raw_dir/browser/states.json" "$raw_dir/browser/relay.jsonl" <<'PY'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
index = int(sys.argv[2])

def canonical(log_path):
    lines = pathlib.Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()
    entered = [(index, line.split()[1]) for index, line in enumerate(lines)
               if line.startswith("PLAYER_ENTERED ")]
    winners = [(index, line.split()[1]) for index, line in enumerate(lines)
               if line.startswith("MATCH_WINNER ")]
    suicides = [(index, line.split()[1]) for index, line in enumerate(lines)
                if line.startswith("DEATH_SUICIDE ")]
    game_ends = [index for index, line in enumerate(lines) if line.startswith("GAME_END ")]
    if sorted(player for _index, player in entered) != ["role1", "role2"]:
        raise SystemExit("authoritative PLAYER_ENTERED set is not exact")
    if ([player for _index, player in suicides] != ["role1"] or
            [player for _index, player in winners] != ["role2"] or len(game_ends) != 1):
        raise SystemExit("authoritative role2 winner/GAME_END is not exact")
    if not (max(index for index, _player in entered) < suicides[0][0] <
            winners[0][0] < game_ends[0]):
        raise SystemExit("authoritative event order is not exact")
    return {"events": ["PLAYER_ENTERED", "PLAYER_ENTERED", "DEATH_SUICIDE",
                       "MATCH_WINNER", "GAME_END"],
            "loser": "role1", "winner": "role2"}

def digest(file_name):
    import hashlib
    value = hashlib.sha256()
    with pathlib.Path(file_name).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()

manifest = json.loads(pathlib.Path(sys.argv[5]).read_text(encoding="utf-8"))
native_log, native_recording = sys.argv[6], sys.argv[7]
browser_log, browser_recording = sys.argv[8], sys.argv[9]
native_input1, native_input2 = sys.argv[10], sys.argv[11]
browser_states, browser_relay = sys.argv[12], sys.argv[13]
raw = {
    "native/ladderlog.txt": native_log,
    "native/match.aarec": native_recording,
    "native/input-role1.log": native_input1,
    "native/input-role2.log": native_input2,
    "browser/ladderlog.txt": browser_log,
    "browser/match.aarec": browser_recording,
    "browser/states.json": browser_states,
    "browser/relay.jsonl": browser_relay,
}
record = {"schema": "arena-native-browser-parity-v1", "trial": index,
          "browser": sys.argv[3], "sourceCommit": sys.argv[4],
          "attempt": 1,
          "buildSha256": manifest["buildSha256"],
          "configSha256": manifest["configSha256"],
          "inputSchedule": manifest["inputSchedule"],
          "inputScheduleSha256": manifest["inputScheduleSha256"],
          "nativeInput": {"role1KeyDown": 3, "role1KeyUp": 3,
                          "role1AcceptedTurns": 3, "role2AcceptedTurns": 0},
          "rawSha256": {name: digest(path) for name, path in raw.items()},
          "nativeCanonical": canonical(native_log),
          "browserCanonical": canonical(browser_log),
          "nativeServer": {"fresh": True, "gameEnd": True,
                           "logSha256": digest(native_log),
                           "recordingSha256": digest(native_recording)},
          "browserServer": {"fresh": True, "gameEnd": True,
                            "logSha256": digest(browser_log),
                            "recordingSha256": digest(browser_recording)}}
path.write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")
PY
}

run_native() {
    index=$1 dir=$2
    mkdir -p "$dir/server" "$dir/role1" "$dir/role2"
    chmod 0777 "$dir/server" "$dir/role1" "$dir/role2"
    for role in 1 2; do
        cp "$arena_dir/config/native-parity.cfg" "$dir/role$role/user.cfg"
        printf '%s\n' "PLAYER_1 role$role" >>"$dir/role$role/user.cfg"
        : >"$dir/role$role/input-evidence.log"
    done
    docker run -d --name "arena-parity-native-server-$index" --network host \
        -v "$dir/server:/arena/var" \
        -v "$arena_dir/config/parity-server.cfg:/arena/data/config/parity-server.cfg:ro" \
        arena-native-runtime:parity \
        --datadir /arena/data --configdir /arena/data/config --userconfigdir /arena/var \
        --vardir /arena/var --resourcedir /arena/data/resource \
        --autoresourcedir /arena/var/resource-cache --record /arena/var/match.aarec \
        --extraconfig parity-server.cfg >/dev/null
    for role in 1 2; do
        display=:$((98 + role))
        docker run -d --name "arena-parity-native-role$role-$index" --network host --entrypoint /bin/sh \
            -e DISPLAY="$display" \
            -e ARENA_PARITY_HOST=127.0.0.1 -e ARENA_PARITY_PORT=4534 \
            -e ARENA_PARITY_INPUT_EVIDENCE=/arena/var/input-evidence.log \
            -v "$dir/role$role:/arena/var" "$ARENA_NATIVE_PARITY_IMAGE" \
            -ec 'Xvfb "$DISPLAY" -screen 0 800x600x24 & xvfb=$!; sleep 1; kill -0 "$xvfb"; exec /usr/local/bin/armagetronad -w --datadir /arena/data --configdir /arena/data/config --userconfigdir /arena/var --vardir /arena/var --resourcedir /arena/data/resource --autoresourcedir /arena/var/resource-cache' >/dev/null
    done
    wait_log "$dir/server/ladderlog.txt" '^PLAYER_ENTERED role1'
    wait_log "$dir/server/ladderlog.txt" '^PLAYER_ENTERED role2'
    wait_log "$dir/role1/input-evidence.log" '^READY$'
    wait_log "$dir/role2/input-evidence.log" '^READY$'
    sleep 0.20
    docker exec "arena-parity-native-role1-$index" sh -ec '
        window=$(xdotool search --onlyvisible --name Armagetron | head -n 1)
        xdotool windowfocus "$window"
        xdotool keydown a; sleep 0.12; xdotool keyup a
        xdotool keydown a; sleep 0.12; xdotool keyup a
        xdotool keydown a; sleep 0.12; xdotool keyup a
    '
    python3 - "$dir/role1/input-evidence.log" "$dir/role2/input-evidence.log" <<'PY'
import pathlib, sys, time

def counts(path):
    lines = pathlib.Path(path).read_text(encoding="ascii", errors="strict").splitlines()
    return (
        sum(line == "KEY 1 97 0 1" for line in lines),
        sum(line == "KEY 0 97 0 1" for line in lines),
        sum(line.startswith("ACTION CYCLE_TURN_LEFT 1 ") and
            float(line.split()[3]) > 0 and line.split()[4] == "1" for line in lines),
    )

deadline = time.monotonic() + 5
while time.monotonic() < deadline:
    if counts(sys.argv[1]) == (3, 3, 3) and counts(sys.argv[2]) == (0, 0, 0):
        break
    time.sleep(0.05)
else:
    raise SystemExit("native SDL/accepted-action evidence is not exact")
PY
    wait_log "$dir/server/ladderlog.txt" 'MATCH_WINNER.*role2'
    docker stop -t 10 "arena-parity-native-role1-$index" "arena-parity-native-role2-$index" "arena-parity-native-server-$index" >/dev/null
    docker rm -f "arena-parity-native-role1-$index" "arena-parity-native-role2-$index" "arena-parity-native-server-$index" >/dev/null
}

run_browser() {
    index=$1 browser=$2 dir=$3 image=$4
    mkdir -p "$dir/server" "$dir/evidence" "$dir/roster"
    chmod 0777 "$dir/server" "$dir/evidence" "$dir/roster"
    export ARENA_RELAY_SECRET=ci-only-ephemeral-relay-secret-material
    docker run -d --name "arena-parity-browser-server-$index" --network host \
        -e ARENA_ROSTER_DIR=/arena/roster -v "$dir/server:/arena/var" -v "$dir/roster:/arena/roster:ro" \
        -v "$arena_dir/config/parity-server.cfg:/arena/data/config/parity-server.cfg:ro" \
        arena-native-runtime:parity \
        --datadir /arena/data --configdir /arena/data/config --userconfigdir /arena/var \
        --vardir /arena/var --resourcedir /arena/data/resource \
        --autoresourcedir /arena/var/resource-cache --record /arena/var/match.aarec \
        --extraconfig parity-server.cfg >/dev/null
    docker run -d --name "arena-parity-static-$index" --network host -v "$repo_dir:/src:ro" -v "$repo_dir/build/web:/web:ro" -w /src \
        "$EMSDK_IMAGE_LINUX_AMD64" python3 arena/static_server.py --port 8000 --host 127.0.0.1 --directory /web >/dev/null
    docker run -d --name "arena-parity-relay-$index" --network host -e ARENA_RELAY_SECRET -v "$repo_dir:/src:ro" -v "$dir/evidence:/evidence" -v "$dir/roster:/roster" -w /src \
        "$EMSDK_IMAGE_LINUX_AMD64" python3 arena/relay.py --allow-origin http://127.0.0.1:8000 --roster-dir /roster --evidence /evidence/relay.jsonl >/dev/null
    docker run -d --name "arena-parity-webdriver-$index" --platform linux/amd64 --network host --shm-size 2g -e SE_NODE_MAX_SESSIONS=2 -e SE_NODE_OVERRIDE_MAX_SESSIONS=true "$image" >/dev/null
    for attempt in $(seq 1 120); do
        docker run --rm --network host "$EMSDK_IMAGE_LINUX_AMD64" python3 -c "import json,urllib.request; assert json.load(urllib.request.urlopen('http://127.0.0.1:4444/status',timeout=2))['value']['ready']" >/dev/null 2>&1 && break
        test "$attempt" -lt 120 || return 1
        sleep 1
    done
    for attempt in $(seq 1 30); do
        docker run --rm --network host "$EMSDK_IMAGE_LINUX_AMD64" python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/armagetronad_main.html',timeout=2)" >/dev/null 2>&1 && break
        test "$attempt" -lt 30 || return 1
        sleep 1
    done
    docker run --rm --network host -e ARENA_RELAY_SECRET -v "$repo_dir:/src" -w /src "$EMSDK_IMAGE_LINUX_AMD64" \
        python3 arena/tests/test_browser.py --browser "$browser" --server-log /src/build/parity/runtime/trial-$(printf %03d "$index")/browser/server/ladderlog.txt --evidence-dir /src/build/parity/runtime/trial-$(printf %03d "$index")/browser/evidence --parity-role-schedule
    wait_log "$dir/server/ladderlog.txt" 'MATCH_WINNER.*role2'
    docker stop -t 10 "arena-parity-browser-server-$index" >/dev/null
    docker rm -f "arena-parity-browser-server-$index" "arena-parity-static-$index" "arena-parity-relay-$index" "arena-parity-webdriver-$index" >/dev/null
}

for index in $(seq "$shard_index" "$shard_count" 99); do
    current_index=$index
    cleanup
    trial_dir="$runtime_root/trial-$(printf %03d "$index")"
    rm -rf "$trial_dir"
    mkdir -p "$trial_dir"
    run_native "$index" "$trial_dir/native"
    browser=chrome; image=$SELENIUM_CHROME_LINUX_AMD64
    test $((index % 2)) -eq 0 || { browser=firefox; image=$SELENIUM_FIREFOX_LINUX_AMD64; }
    run_browser "$index" "$browser" "$trial_dir/browser" "$image"
    wait_log "$trial_dir/native/server/ladderlog.txt" '^GAME_END '
    wait_log "$trial_dir/browser/server/ladderlog.txt" '^GAME_END '
    write_record "$index" "$browser" "$trial_dir/native" "$trial_dir/browser"
done
current_index=
trap - EXIT HUP INT TERM
