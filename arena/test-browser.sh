#!/bin/sh
# Copyright (C) 2026 Arena contributors. GPLv2+; see COPYING.txt.
set -eu

arena_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(dirname "$arena_dir")
. "$arena_dir/pins.env"

test "$#" -eq 2 && test "$1" = "--browsers" || {
    echo "usage: $0 --browsers chrome,firefox,safari" >&2
    exit 2
}

old_ifs=$IFS
IFS=,
set -- $2
IFS=$old_ifs

for browser in "$@"; do
    case "$browser" in
        chrome) image=$SELENIUM_CHROME_LINUX_AMD64 ;;
        firefox) image=$SELENIUM_FIREFOX_LINUX_AMD64 ;;
        safari)
            test -n "${ARENA_SAFARI_WEBDRIVER_URL:-}" || {
                echo "Safari requires ARENA_SAFARI_WEBDRIVER_URL on a macOS runner." >&2
                exit 1
            }
            ARENA_BROWSER_WEBDRIVER_URL=$ARENA_SAFARI_WEBDRIVER_URL \
                python3 "$arena_dir/tests/test_browser.py" \
                    --browser safari \
                    --webdriver-url "$ARENA_SAFARI_WEBDRIVER_URL" \
                    --server-log "$repo_dir/build/runtime/server/ladderlog.txt" \
                    --evidence-dir "$repo_dir/build/runtime/evidence"
            continue
            ;;
        *) echo "unsupported browser: $browser" >&2; exit 2 ;;
    esac

    container="arena-webdriver-$browser"
    docker rm -f "$container" >/dev/null 2>&1 || true
    docker run -d --rm \
        --name "$container" \
        --platform linux/amd64 \
        --network host \
        --shm-size 2g \
        -e SE_NODE_MAX_SESSIONS=2 \
        -e SE_NODE_OVERRIDE_MAX_SESSIONS=true \
        "$image" >/dev/null

    ready=false
    for attempt in $(seq 1 60); do
        if test "$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$container")" = healthy; then
            ready=true
            break
        fi
        sleep 1
    done
    if test "$ready" != true; then
        docker logs "$container" >&2 || true
        docker rm -f "$container" >/dev/null 2>&1 || true
        exit 1
    fi

    if ! docker run --rm \
        --platform linux/amd64 \
        --network host \
        -e ARENA_RELAY_SECRET \
        -v "$repo_dir:/src" \
        -w /src \
        "$EMSDK_IMAGE_LINUX_AMD64" \
        python3 arena/tests/test_browser.py \
            --browser "$browser" \
            --server-log /src/build/runtime/server/ladderlog.txt \
            --evidence-dir /src/build/runtime/evidence; then
        docker logs "$container" >&2 || true
        docker rm -f "$container" >/dev/null 2>&1 || true
        exit 1
    fi
    docker rm -f "$container" >/dev/null 2>&1 || true
done
