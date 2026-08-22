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
    linux/amd64)
        bootstrap_image=$NATIVE_IMAGE_LINUX_AMD64
        emsdk_image=$EMSDK_IMAGE_LINUX_AMD64
        ;;
    linux/arm64)
        bootstrap_image=$NATIVE_IMAGE_LINUX_ARM64
        emsdk_image=$EMSDK_IMAGE_LINUX_ARM64
        ;;
    *) echo "unsupported platform: $platform" >&2; exit 2 ;;
esac

test "$(git -C "$repo_dir" rev-parse 'v0.2.9.3.0^{}')" = "$ARENA_SOURCE_COMMIT"
git -C "$repo_dir" merge-base --is-ancestor "$ARENA_SOURCE_COMMIT" HEAD

artifact_dir="$repo_dir/build/web"
rm -rf "$artifact_dir"
mkdir -p "$artifact_dir"

docker_build() {
    if test "${ARENA_DOCKER_NO_CACHE:-0}" = 1; then
        docker build --no-cache "$@"
    else
        docker build "$@"
    fi
}

docker_build \
    --progress=plain \
    --platform "$platform" \
    --file "$arena_dir/docker/Dockerfile.web" \
    --target artifact \
    --output "type=local,dest=$artifact_dir" \
    --build-arg "BOOTSTRAP_IMAGE=$bootstrap_image" \
    --build-arg "EMSDK_IMAGE=$emsdk_image" \
    --build-arg "DEBIAN_SNAPSHOT=$DEBIAN_SNAPSHOT" \
    --build-arg "AUTOCONF_VERSION=$AUTOCONF_VERSION" \
    --build-arg "AUTOMAKE_VERSION=$AUTOMAKE_VERSION" \
    --build-arg "GXX_VERSION=$GXX_VERSION" \
    --build-arg "LIBTOOL_VERSION=$LIBTOOL_VERSION" \
    --build-arg "MAKE_VERSION=$MAKE_VERSION" \
    --build-arg "PKG_CONFIG_VERSION=$PKG_CONFIG_VERSION" \
    --build-arg "PYTHON3_VERSION=$PYTHON3_VERSION" \
    --build-arg "ARENA_SOURCE_DATE_EPOCH=$ARENA_SOURCE_DATE_EPOCH" \
    --build-arg "ARENA_SOURCE_TAG=$ARENA_SOURCE_TAG" \
    --build-arg "LIBXML2_VERSION=$LIBXML2_VERSION" \
    --build-arg "LIBXML2_URL=$LIBXML2_URL" \
    --build-arg "LIBXML2_SHA256=$LIBXML2_SHA256" \
    "$repo_dir"

(
    cd "$artifact_dir"
    sha256sum armagetronad_main* COPYING.txt > SHA256SUMS
)
cat "$artifact_dir/SHA256SUMS"
