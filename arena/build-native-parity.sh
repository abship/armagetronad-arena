#!/bin/sh
# Copyright (C) 2026 Arena contributors. GPLv2+; see COPYING.txt.
# Interoperability-only graphical client; production remains native linux/amd64.
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
    linux/amd64) native_image=$NATIVE_IMAGE_LINUX_AMD64 ;;
    linux/arm64) native_image=$NATIVE_IMAGE_LINUX_ARM64 ;;
    *)
        echo "unsupported platform: $platform" >&2
        exit 2
        ;;
esac
architecture=${platform#linux/}

test "$(git -C "$repo_dir" rev-parse 'v0.2.9.3.0^{}')" = "$ARENA_SOURCE_COMMIT"
git -C "$repo_dir" merge-base --is-ancestor "$ARENA_SOURCE_COMMIT" HEAD
test -z "$(git -C "$repo_dir" diff --name-only "$ARENA_SOURCE_COMMIT" -- \
    src/engine/eGrid.cpp src/engine/eWall.cpp src/engine/eLagCompensation.cpp \
    src/tron/gArena.cpp src/tron/gCycle.cpp src/tron/gCycleMovement.cpp \
    src/tron/gSpawn.cpp src/tron/gWall.cpp)"
test ! -L "$repo_dir/build" && test ! -L "$repo_dir/build/native-parity" || {
    echo "refusing symlinked build directory" >&2
    exit 1
}

image=armagetronad-arena-native-parity:arm-1-$architecture
docker_build() {
    if test "${ARENA_DOCKER_NO_CACHE:-0}" = 1; then
        docker build --no-cache "$@"
    else
        docker build "$@"
    fi
}

docker_build \
    --quiet \
    --platform "$platform" \
    --file "$arena_dir/docker/Dockerfile.native-parity" \
    --target runtime \
    --tag "$image" \
    --build-arg "NATIVE_IMAGE=$native_image" \
    --build-arg "DEBIAN_SNAPSHOT=$DEBIAN_SNAPSHOT" \
    --build-arg "AUTOCONF_VERSION=$AUTOCONF_VERSION" \
    --build-arg "AUTOMAKE_VERSION=$AUTOMAKE_VERSION" \
    --build-arg "GXX_VERSION=$GXX_VERSION" \
    --build-arg "LIBTOOL_VERSION=$LIBTOOL_VERSION" \
    --build-arg "LIBXML2_DEV_VERSION=$LIBXML2_DEV_VERSION" \
    --build-arg "LIBXML2_RUNTIME_VERSION=$LIBXML2_RUNTIME_VERSION" \
    --build-arg "LIBGL_DEV_VERSION=$LIBGL_DEV_VERSION" \
    --build-arg "LIBGL1_VERSION=$LIBGL1_VERSION" \
    --build-arg "LIBGL1_MESA_DRI_VERSION=$LIBGL1_MESA_DRI_VERSION" \
    --build-arg "LIBGLX_MESA0_VERSION=$LIBGLX_MESA0_VERSION" \
    --build-arg "LIBGLU1_MESA_DEV_VERSION=$LIBGLU1_MESA_DEV_VERSION" \
    --build-arg "LIBGLU1_MESA_VERSION=$LIBGLU1_MESA_VERSION" \
    --build-arg "LIBPNG_DEV_VERSION=$LIBPNG_DEV_VERSION" \
    --build-arg "LIBSDL1_2_DEV_VERSION=$LIBSDL1_2_DEV_VERSION" \
    --build-arg "LIBSDL1_2_VERSION=$LIBSDL1_2_VERSION" \
    --build-arg "LIBSDL_IMAGE1_2_DEV_VERSION=$LIBSDL_IMAGE1_2_DEV_VERSION" \
    --build-arg "LIBSDL_IMAGE1_2_VERSION=$LIBSDL_IMAGE1_2_VERSION" \
    --build-arg "XAUTH_VERSION=$XAUTH_VERSION" \
    --build-arg "XDTOOL_VERSION=$XDTOOL_VERSION" \
    --build-arg "XVFB_VERSION=$XVFB_VERSION" \
    --build-arg "MAKE_VERSION=$MAKE_VERSION" \
    --build-arg "PKG_CONFIG_VERSION=$PKG_CONFIG_VERSION" \
    --build-arg "PYTHON3_VERSION=$PYTHON3_VERSION" \
    --build-arg "ARENA_SOURCE_DATE_EPOCH=$ARENA_SOURCE_DATE_EPOCH" \
    --build-arg "ARENA_SOURCE_TAG=$ARENA_SOURCE_TAG" \
    "$repo_dir"

artifact_dir="$repo_dir/build/native-parity/$architecture"
rm -rf "$artifact_dir"
mkdir -p "$artifact_dir"
container=$(docker create "$image" --version)
trap 'docker rm -f "$container" >/dev/null 2>&1 || true' EXIT HUP INT TERM
docker cp "$container:/usr/local/bin/armagetronad" "$artifact_dir/armagetronad"
docker rm "$container" >/dev/null
trap - EXIT HUP INT TERM

docker image inspect "$image" --format '{{.Id}}' > "$artifact_dir/image.id"
(
    cd "$artifact_dir"
    sha256sum armagetronad > SHA256SUMS
)
cat "$artifact_dir/SHA256SUMS"
