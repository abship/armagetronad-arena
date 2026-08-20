#!/bin/sh
# Copyright (C) 2026 Arena contributors. GPLv2+; see COPYING.txt.
set -eu

arena_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(dirname "$arena_dir")
. "$arena_dir/pins.env"

platform=${ARENA_BUILD_PLATFORM:-$ARENA_DEFAULT_PLATFORM}
tag=${ARENA_RUNTIME_TAG:-arena-native-runtime:local}
if test "$#" -gt 0; then
    test "$#" -eq 2 && test "$1" = "--platform" || {
        echo "usage: $0 [--platform linux/amd64|linux/arm64]" >&2
        exit 2
    }
    platform=$2
fi

case "$platform" in
    linux/amd64) native_image=$NATIVE_IMAGE_LINUX_AMD64 ;;
    linux/arm64) native_image=$NATIVE_IMAGE_LINUX_ARM64 ;;
    *) echo "unsupported platform: $platform" >&2; exit 2 ;;
esac

test "$(git -C "$repo_dir" rev-parse 'v0.2.9.3.0^{}')" = "$ARENA_SOURCE_COMMIT"
git -C "$repo_dir" merge-base --is-ancestor "$ARENA_SOURCE_COMMIT" HEAD

docker build \
    --quiet \
    --platform "$platform" \
    --file "$arena_dir/docker/Dockerfile.native" \
    --target runtime \
    --tag "$tag" \
    --build-arg "NATIVE_IMAGE=$native_image" \
    --build-arg "DEBIAN_SNAPSHOT=$DEBIAN_SNAPSHOT" \
    --build-arg "AUTOCONF_VERSION=$AUTOCONF_VERSION" \
    --build-arg "AUTOMAKE_VERSION=$AUTOMAKE_VERSION" \
    --build-arg "GXX_VERSION=$GXX_VERSION" \
    --build-arg "LIBTOOL_VERSION=$LIBTOOL_VERSION" \
    --build-arg "LIBXML2_DEV_VERSION=$LIBXML2_DEV_VERSION" \
    --build-arg "LIBXML2_RUNTIME_VERSION=$LIBXML2_RUNTIME_VERSION" \
    --build-arg "MAKE_VERSION=$MAKE_VERSION" \
    --build-arg "PKG_CONFIG_VERSION=$PKG_CONFIG_VERSION" \
    --build-arg "PYTHON3_VERSION=$PYTHON3_VERSION" \
    --build-arg "ARENA_SOURCE_DATE_EPOCH=$ARENA_SOURCE_DATE_EPOCH" \
    --build-arg "ARENA_SOURCE_TAG=$ARENA_SOURCE_TAG" \
    "$repo_dir"
