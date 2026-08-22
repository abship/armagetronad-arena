#!/bin/sh
# Copyright (C) 2026 Arena contributors. GPLv2+; see COPYING.txt.
#
# Safari CI interoperability evidence only. Production native builds remain
# pinned linux/amd64 builds from build-native.sh.
set -eu

arena_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(dirname "$arena_dir")
. "$arena_dir/pins.env"
source_dir=${ARENA_MACOS_SOURCE_DIR:-$repo_dir}

export SOURCE_DATE_EPOCH=$ARENA_SOURCE_DATE_EPOCH

expected_xcode="Xcode $MACOS_INTEROP_XCODE_VERSION"
expected_xcode_build="Build version $MACOS_INTEROP_XCODE_BUILD"
developer_dir=/Applications/Xcode_$MACOS_INTEROP_XCODE_VERSION.app/Contents/Developer

fail() {
    echo "arena macOS interoperability build: $*" >&2
    exit 1
}

test "$(uname -s)" = Darwin || fail 'requires macOS'
test "$(uname -m)" = x86_64 || fail 'requires the macos-15-intel runner'
test "${ImageOS-}" = "$MACOS_INTEROP_IMAGE_OS" || \
    fail "expected ImageOS=$MACOS_INTEROP_IMAGE_OS, got ${ImageOS-unset}"
test "${ImageVersion-}" = "$MACOS_INTEROP_IMAGE_VERSION" || \
    fail "expected ImageVersion=$MACOS_INTEROP_IMAGE_VERSION, got ${ImageVersion-unset}"
test -d "$developer_dir" || fail "missing $developer_dir"

export DEVELOPER_DIR=$developer_dir
test "$(xcodebuild -version | sed -n '1p')" = "$expected_xcode" || fail 'unexpected Xcode version'
test "$(xcodebuild -version | sed -n '2p')" = "$expected_xcode_build" || fail 'unexpected Xcode build'

for tool in make ar ranlib pkgconf; do
    command -v "$tool" >/dev/null 2>&1 || fail "missing required tool: $tool"
done
test "$(pkgconf --version)" = "$MACOS_INTEROP_PKGCONF_VERSION" || \
    fail "expected pkgconf $MACOS_INTEROP_PKGCONF_VERSION, got $(pkgconf --version)"
test "$(python3 -c 'import platform; print(platform.python_version())')" = \
    "$MACOS_INTEROP_PYTHON_VERSION" || fail 'unexpected Python version'

sdk_root=$(xcrun --sdk macosx --show-sdk-path)
cc=$(xcrun --sdk macosx --find clang)
cxx=$(xcrun --sdk macosx --find clang++)
xml_version_header=$sdk_root/usr/include/libxml2/libxml/xmlversion.h
test -r "$xml_version_header" || fail 'SDK libxml2 headers are missing'
test -r "$sdk_root/usr/lib/libxml2.tbd" || fail 'SDK libxml2 library is missing'

sdk_xml_version=$(sed -n 's/^#define LIBXML_DOTTED_VERSION "\([^"]*\)"/\1/p' \
    "$xml_version_header")
test "$sdk_xml_version" = "$MACOS_INTEROP_LIBXML2_VERSION" || \
    fail "expected SDK libxml2 $MACOS_INTEROP_LIBXML2_VERSION, got ${sdk_xml_version-unset}"

test "$(git -C "$repo_dir" rev-parse 'v0.2.9.3.0^{}')" = "$ARENA_SOURCE_COMMIT"
git -C "$repo_dir" merge-base --is-ancestor "$ARENA_SOURCE_COMMIT" HEAD
test -x "$source_dir/configure" || fail 'prepared configure script is missing'
test -f "$source_dir/SOURCE-COMMIT" || fail 'prepared source commit is missing'
test "$(cat "$source_dir/SOURCE-COMMIT")" = "$(git -C "$repo_dir" rev-parse HEAD)" || \
    fail 'prepared source does not match the checked-out candidate'

output_dir=$repo_dir/build/native-macos-interoperability
build_dir=$output_dir/build
stage_dir=$output_dir/stage
evidence_dir=$output_dir/evidence
test ! -L "$repo_dir/build" && test ! -L "$output_dir" || \
    fail 'refusing symlinked build path'
rm -rf "$output_dir"
mkdir -p "$build_dir" "$stage_dir/data/config" "$stage_dir/data/language" \
    "$stage_dir/data/resource/AATeam" "$stage_dir/data/resource/Z-Man/fortress" \
    "$stage_dir/var" "$evidence_dir"

temporary_dir=$(mktemp -d "$output_dir/tmp.XXXXXX")
trap 'rm -rf "$temporary_dir"' EXIT HUP INT TERM
pc_dir=$temporary_dir/pkgconfig
mkdir "$pc_dir"
cat >"$pc_dir/libxml-2.0.pc" <<EOF
prefix=$sdk_root/usr
exec_prefix=\${prefix}
libdir=\${exec_prefix}/lib
includedir=\${prefix}/include

Name: libxml-2.0
Description: Apple SDK libxml2
Version: $sdk_xml_version
Libs: -L\${libdir} -lxml2
Cflags: -I\${includedir}/libxml2
EOF

export PKG_CONFIG=pkgconf
export PKG_CONFIG_LIBDIR=$pc_dir
export PKG_CONFIG_PATH=$pc_dir
pkgconf --exists 'libxml-2.0 >= 2.6.11' || fail 'SDK libxml2 pkg-config probe failed'

printf '%s\n' '#include <libxml/parser.h>' 'int main(void) { xmlCheckVersion(LIBXML_VERSION); return 0; }' | \
    "$cc" -isysroot "$sdk_root" $(pkgconf --cflags libxml-2.0) -x c - \
    $(pkgconf --libs libxml-2.0) -o "$temporary_dir/libxml2-probe"
"$temporary_dir/libxml2-probe"

(
    cd "$build_dir"
    CFLAGS="-O2 -g0 -ffile-prefix-map=$source_dir=. -ffile-prefix-map=$build_dir=." \
    CXXFLAGS="-O2 -g0 -ffile-prefix-map=$source_dir=. -ffile-prefix-map=$build_dir=." \
    CPPFLAGS="-isysroot $sdk_root" \
    LDFLAGS="-isysroot $sdk_root" \
    CC="$cc" CXX="$cxx" \
    "$source_dir/configure" \
        --prefix=/usr/local \
        --enable-dedicated \
        --disable-authentication \
        --disable-curl \
        --disable-desktop \
        --disable-etc \
        --disable-games \
        --disable-initscripts \
        --disable-master \
        --disable-memmanager \
        --disable-migratestate \
        --disable-music \
        --disable-restoreold \
        --disable-sysinstall \
        --disable-uninstall \
        --disable-useradd
    make -j2
)

cp "$build_dir/src/armagetronad-dedicated" "$stage_dir/armagetronad-dedicated"
cp -R "$source_dir/config/." "$stage_dir/data/config/"
cp "$source_dir/arena/config/arena.cfg" "$stage_dir/data/config/arena.cfg"
cp -R "$source_dir/language/." "$stage_dir/data/language/"
cp "$build_dir/language/languages.txt" "$stage_dir/data/language/languages.txt"
cp "$source_dir/resource/proto/AATeam/map-0.2.8.0_rc4.dtd" \
    "$stage_dir/data/resource/AATeam/map-0.2.8.0_rc4.dtd"
cp "$source_dir/resource/proto/Z-Man/sumo_4x4.aamap.xml" \
    "$stage_dir/data/resource/Z-Man/fortress/sumo_4x4-0.1.1.aamap.xml"

{
    echo 'purpose=Safari CI interoperability only; not the linux/amd64 production native build'
    echo "image_os=$ImageOS"
    echo "image_version=$ImageVersion"
    echo "developer_dir=$DEVELOPER_DIR"
    xcodebuild -version
    echo "sdk_root=$sdk_root"
    echo "sdk_version=$(xcrun --sdk macosx --show-sdk-version)"
    echo "sdk_libxml2=$sdk_xml_version"
    echo "pkgconf=$(pkgconf --version)"
    "$cc" --version | sed -n '1p'
    "$cxx" --version | sed -n '1p'
    make --version | sed -n '1p'
    echo "source_date_epoch=$SOURCE_DATE_EPOCH"
    echo "source_base=$ARENA_SOURCE_COMMIT"
    git -C "$repo_dir" rev-parse HEAD
    echo "prepared_source=$source_dir"
} >"$evidence_dir/toolchain.txt"

(
    cd "$output_dir"
    find stage evidence -type f -exec shasum -a 256 {} \; | LC_ALL=C sort > SHA256SUMS
)

echo "Safari interoperability build staged at $stage_dir"
echo "Run: $stage_dir/armagetronad-dedicated --datadir $stage_dir/data --configdir $stage_dir/data/config --userconfigdir $stage_dir/var --vardir $stage_dir/var --resourcedir $stage_dir/data/resource --autoresourcedir $stage_dir/var/resource-cache --record $stage_dir/var/match.aarec --extraconfig arena.cfg"
