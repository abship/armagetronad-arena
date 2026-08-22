#!/bin/sh
# Copyright (C) 2026 Arena contributors. GPLv2+; see COPYING.txt.
# Generate autotools inputs for Safari CI inside the pinned Linux builder.
set -eu

arena_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(dirname "$arena_dir")
. "$arena_dir/pins.env"

test "$(git -C "$repo_dir" rev-parse "$ARENA_SOURCE_TAG^{}")" = "$ARENA_SOURCE_COMMIT"
git -C "$repo_dir" merge-base --is-ancestor "$ARENA_SOURCE_COMMIT" HEAD
test ! -L "$repo_dir/build" && test ! -L "$repo_dir/build/macos-source" || {
    echo "refusing symlinked macOS source path" >&2
    exit 1
}

output_dir="$repo_dir/build/macos-source"
rm -rf "$output_dir"
mkdir -p "$output_dir"
docker build \
    --platform linux/amd64 \
    --file "$arena_dir/docker/Dockerfile.native" \
    --target macos-source \
    --output "type=local,dest=$output_dir" \
    --build-arg "NATIVE_IMAGE=$NATIVE_IMAGE_LINUX_AMD64" \
    --build-arg "DEBIAN_SNAPSHOT=$DEBIAN_SNAPSHOT" \
    --build-arg "AUTOCONF_VERSION=$AUTOCONF_VERSION" \
    --build-arg "AUTOMAKE_VERSION=$AUTOMAKE_VERSION" \
    --build-arg "GXX_VERSION=$GXX_VERSION" \
    --build-arg "LIBTOOL_VERSION=$LIBTOOL_VERSION" \
    --build-arg "LIBXML2_DEV_VERSION=$LIBXML2_DEV_VERSION" \
    --build-arg "MAKE_VERSION=$MAKE_VERSION" \
    --build-arg "PKG_CONFIG_VERSION=$PKG_CONFIG_VERSION" \
    --build-arg "PYTHON3_VERSION=$PYTHON3_VERSION" \
    --build-arg "ARENA_SOURCE_DATE_EPOCH=$ARENA_SOURCE_DATE_EPOCH" \
    --build-arg "ARENA_SOURCE_TAG=$ARENA_SOURCE_TAG" \
    "$repo_dir"

git -C "$repo_dir" rev-parse HEAD > "$output_dir/SOURCE-COMMIT"
test -x "$output_dir/configure"
for file in compile config.guess config.sub depcomp install-sh missing; do
    test -f "$output_dir/$file" && test ! -L "$output_dir/$file"
done
