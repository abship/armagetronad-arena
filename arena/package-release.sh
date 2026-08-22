#!/bin/sh
# Copyright (C) 2026 Arena contributors. GPLv2+; see COPYING.txt.
set -eu

arena_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(dirname "$arena_dir")
. "$arena_dir/pins.env"

platform=${ARENA_BUILD_PLATFORM:-$ARENA_DEFAULT_PLATFORM}
output_dir="$repo_dir/build/release"
if test "$#" -gt 0; then
    test "$#" -eq 2 && test "$1" = "--platform" || {
        echo "usage: $0 [--platform linux/amd64|linux/arm64]" >&2
        exit 2
    }
    platform=$2
fi

case "$platform" in
    linux/amd64)
        native_builder=$NATIVE_IMAGE_LINUX_AMD64
        emsdk_builder=$EMSDK_IMAGE_LINUX_AMD64
        ;;
    linux/arm64)
        native_builder=$NATIVE_IMAGE_LINUX_ARM64
        emsdk_builder=$EMSDK_IMAGE_LINUX_ARM64
        ;;
    *) echo "unsupported platform: $platform" >&2; exit 2 ;;
esac
architecture=${platform#linux/}

head=$(git -C "$repo_dir" rev-parse HEAD)
tree=$(git -C "$repo_dir" rev-parse 'HEAD^{tree}')
test "$(git -C "$repo_dir" rev-parse "$ARENA_SOURCE_TAG^{}")" = "$ARENA_SOURCE_COMMIT"
test "$(git -C "$repo_dir" rev-parse "$ARENA_PARENT_RELEASE_TAG^{}")" = "$ARENA_PARENT_RELEASE_COMMIT"
git -C "$repo_dir" merge-base --is-ancestor "$ARENA_PARENT_RELEASE_COMMIT" "$head"
test -z "$(git -C "$repo_dir" status --porcelain --untracked-files=all)" || {
    echo "source tree has tracked or untracked changes" >&2
    exit 1
}
ignored_inputs=$(git -C "$repo_dir" ls-files --others --ignored --exclude-standard \
    | sed '\#^build/#d')
test -z "$ignored_inputs" || {
    echo "source tree has ignored inputs outside build/" >&2
    printf '%s\n' "$ignored_inputs" >&2
    exit 1
}
native_dir="$repo_dir/build/native/$architecture"
web_dir="$repo_dir/build/web"
test ! -L "$repo_dir/build" \
    && test ! -L "$repo_dir/build/native" \
    && test ! -L "$native_dir" \
    && test ! -L "$web_dir" \
    && test ! -L "$output_dir" || {
    echo "refusing symlinked release path" >&2
    exit 1
}

test -x "$native_dir/armagetronad-dedicated"
test -f "$native_dir/SHA256SUMS"
test -f "$web_dir/SHA256SUMS"
(cd "$native_dir" && sha256sum -c SHA256SUMS)
(cd "$web_dir" && sha256sum -c SHA256SUMS)

rm -rf "$output_dir"
mkdir -p "$output_dir/native-linux-$architecture" "$output_dir/web"

cp "$native_dir/armagetronad-dedicated" "$output_dir/native-linux-$architecture/"
cp "$repo_dir/COPYING.txt" "$output_dir/native-linux-$architecture/COPYING.txt"
cp "$native_dir/SHA256SUMS" "$output_dir/native-linux-$architecture/"
for file in \
    armagetronad_main.data \
    armagetronad_main.html \
    armagetronad_main.js \
    armagetronad_main.wasm \
    armagetronad_main.html.symbols \
    COPYING.txt \
    SHA256SUMS
do
    test -f "$web_dir/$file"
    cp "$web_dir/$file" "$output_dir/web/"
done

source_archive="armagetronad-arena-src-$head.tar.gz"
git -C "$repo_dir" archive --format=tar --prefix="armagetronad-arena-$head/" "$head" \
    | gzip -n > "$output_dir/$source_archive"
(cd "$output_dir" && sha256sum "$source_archive" > "$source_archive.sha256")
git -C "$repo_dir" ls-tree -r --full-tree -l "$head" > "$output_dir/SOURCE-FILES.txt"

pins_sha=$(sha256sum "$arena_dir/pins.env" | awk '{print $1}')
native_dockerfile_sha=$(sha256sum "$arena_dir/docker/Dockerfile.native" | awk '{print $1}')
web_dockerfile_sha=$(sha256sum "$arena_dir/docker/Dockerfile.web" | awk '{print $1}')
source_archive_sha=$(awk '{print $1}' "$output_dir/$source_archive.sha256")
{
    printf '%s\n' 'format=arena-arm1-provenance-v1'
    printf 'repository=%s\n' 'https://github.com/abship/armagetronad-arena'
    printf 'source_commit=%s\n' "$head"
    printf 'source_tree=%s\n' "$tree"
    printf 'stable_tag=%s\n' "$ARENA_SOURCE_TAG"
    printf 'stable_commit=%s\n' "$ARENA_SOURCE_COMMIT"
    printf 'parent_release_tag=%s\n' "$ARENA_PARENT_RELEASE_TAG"
    printf 'parent_release_commit=%s\n' "$ARENA_PARENT_RELEASE_COMMIT"
    printf 'source_date_epoch=%s\n' "$ARENA_SOURCE_DATE_EPOCH"
    printf 'platform=%s\n' "$platform"
    printf 'source_archive=%s\n' "$source_archive"
    printf 'source_archive_sha256=%s\n' "$source_archive_sha"
    printf 'pins_sha256=%s\n' "$pins_sha"
    printf 'native_dockerfile_sha256=%s\n' "$native_dockerfile_sha"
    printf 'web_dockerfile_sha256=%s\n' "$web_dockerfile_sha"
    printf 'native_builder=%s\n' "$native_builder"
    printf 'emsdk_version=%s\n' "$EMSDK_VERSION"
    printf 'emsdk_builder=%s\n' "$emsdk_builder"
    printf '%s\n' 'reproducibility_command=./arena/reproducibility-check.sh'
} > "$output_dir/SOURCE-MANIFEST.txt"

(
    cd "$output_dir"
    find . -type f ! -name SHA256SUMS -print0 \
        | LC_ALL=C sort -z \
        | xargs -0 sha256sum > SHA256SUMS
    sha256sum -c SHA256SUMS
)
printf 'release package: %s\n' "$output_dir"
