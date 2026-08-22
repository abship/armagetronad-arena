#!/bin/sh
# Copyright (C) 2026 Arena contributors. GPLv2+; see COPYING.txt.
set -eu

arena_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(dirname "$arena_dir")
. "$arena_dir/pins.env"

platform=${ARENA_BUILD_PLATFORM:-$ARENA_DEFAULT_PLATFORM}
if test "$#" -gt 0; then
    test "$#" -eq 2 && test "$1" = "--platform" || {
        echo "usage: $0 [--platform linux/amd64|linux/arm64]" >&2
        exit 2
    }
    platform=$2
fi
case "$platform" in
    linux/amd64|linux/arm64) ;;
    *) echo "unsupported platform: $platform" >&2; exit 2 ;;
esac
architecture=${platform#linux/}

head=$(git -C "$repo_dir" rev-parse HEAD)
git -C "$repo_dir" diff --quiet
git -C "$repo_dir" diff --cached --quiet
test "$(git -C "$repo_dir" rev-parse "$ARENA_SOURCE_TAG^{}")" = "$ARENA_SOURCE_COMMIT"
git -C "$repo_dir" merge-base --is-ancestor "$ARENA_SOURCE_COMMIT" "$head"
test ! -L "$repo_dir/build" && test ! -L "$repo_dir/build/reproducibility" || {
    echo "refusing symlinked build directory" >&2
    exit 1
}

result_dir="$repo_dir/build/reproducibility/$architecture"
release_dir="$repo_dir/build/release"
rm -rf "$result_dir" "$release_dir"
mkdir -p "$result_dir"

temporary_dir=$(mktemp -d "${TMPDIR:-/tmp}/arena-reproducibility.XXXXXX")
worktree_a="$temporary_dir/a"
worktree_b="$temporary_dir/b"
cleanup() {
    git -C "$repo_dir" worktree remove --force "$worktree_a" >/dev/null 2>&1 || true
    git -C "$repo_dir" worktree remove --force "$worktree_b" >/dev/null 2>&1 || true
    rmdir "$temporary_dir" >/dev/null 2>&1 || true
}
trap cleanup EXIT HUP INT TERM

git -C "$repo_dir" worktree add --detach "$worktree_a" "$head"
git -C "$repo_dir" worktree add --detach "$worktree_b" "$head"

run_build() {
    label=$1
    worktree=$2
    (
        cd "$worktree"
        ARENA_DOCKER_NO_CACHE=1 ./arena/build-native.sh --platform "$platform"
        ARENA_DOCKER_NO_CACHE=1 ./arena/build-web.sh --platform "$platform"
        ./arena/package-release.sh --platform "$platform"
        mkdir -p "$result_dir/$label"
        cp "build/native/$architecture/SHA256SUMS" "$result_dir/$label/native.SHA256SUMS"
        cp "build/web/SHA256SUMS" "$result_dir/$label/web.SHA256SUMS"
        cp "build/release/SHA256SUMS" "$result_dir/$label/release.SHA256SUMS"
        cp -R build/release "$result_dir/$label/package"
    )
}

run_build a "$worktree_a"
run_build b "$worktree_b"

cmp "$result_dir/a/native.SHA256SUMS" "$result_dir/b/native.SHA256SUMS"
cmp "$result_dir/a/web.SHA256SUMS" "$result_dir/b/web.SHA256SUMS"
cmp "$result_dir/a/release.SHA256SUMS" "$result_dir/b/release.SHA256SUMS"
diff -ru "$result_dir/a/package" "$result_dir/b/package"
cp -R "$result_dir/b/package" "$release_dir"

{
    printf 'source_commit=%s\n' "$head"
    printf 'platform=%s\n' "$platform"
    printf '%s\n' 'clean_builds=2'
    printf '%s\n' 'native_match=true'
    printf '%s\n' 'web_match=true'
    printf '%s\n' 'release_match=true'
} > "$result_dir/RESULT.txt"
printf 'reproducibility PASS: two clean %s builds match byte for byte\n' "$platform"
