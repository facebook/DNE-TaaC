#!/bin/bash

set -euo pipefail

if [[ $# -ne 4 ]]; then
    echo "Usage: $0 <downloads-dir> <work-dir> <prefix> <jobs>" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/versions.sh"
source "$SCRIPT_DIR/common.sh"

DOWNLOADS="$1"
WORK="$2"
PREFIX="$3"
JOBS="$4"

mkdir -p "$DOWNLOADS" "$WORK" "$PREFIX"
export CFLAGS="-O2 -fPIC"
export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig"

build_zlib() {
    local archive="$DOWNLOADS/zlib-$ZLIB_VERSION.tar.gz"
    fetch_verified "$ZLIB_URL" "$ZLIB_SHA256" "$archive"
    extract_fresh "$archive" "$WORK" "zlib-$ZLIB_VERSION"
    (
        cd "$WORK/zlib-$ZLIB_VERSION"
        ./configure --prefix="$PREFIX" --static
        make -j"$JOBS"
        make install
    )
}

build_bzip2() {
    local archive="$DOWNLOADS/bzip2-$BZIP2_VERSION.tar.gz"
    fetch_verified "$BZIP2_URL" "$BZIP2_SHA256" "$archive"
    extract_fresh "$archive" "$WORK" "bzip2-$BZIP2_VERSION"
    (
        cd "$WORK/bzip2-$BZIP2_VERSION"
        make -j"$JOBS" libbz2.a CFLAGS="$CFLAGS -D_FILE_OFFSET_BITS=64"
        install -D -m 0644 libbz2.a "$PREFIX/lib/libbz2.a"
        install -D -m 0644 bzlib.h "$PREFIX/include/bzlib.h"
    )
}

build_autoconf_static() {
    local name="$1"
    local version="$2"
    local url="$3"
    local sha256="$4"
    shift 4
    local archive="$DOWNLOADS/$name-$version.tar.gz"
    fetch_verified "$url" "$sha256" "$archive"
    extract_fresh "$archive" "$WORK" "$name-$version"
    (
        cd "$WORK/$name-$version"
        ./configure --prefix="$PREFIX" --libdir="$PREFIX/lib" \
            --enable-static --disable-shared --with-pic "$@"
        make -j"$JOBS"
        make install
    )
}

build_openssl() {
    local archive="$DOWNLOADS/openssl-$OPENSSL_VERSION.tar.gz"
    fetch_verified "$OPENSSL_URL" "$OPENSSL_SHA256" "$archive"
    extract_fresh "$archive" "$WORK" "openssl-$OPENSSL_VERSION"
    (
        cd "$WORK/openssl-$OPENSSL_VERSION"
        ./Configure linux-x86_64 no-shared no-module no-tests no-docs no-apps \
            --prefix="$PREFIX" --libdir=lib --openssldir=/etc/ssl \
            -fPIC
        make -j"$JOBS"
        make install_sw
    )
}

build_zlib
build_bzip2
build_autoconf_static xz "$XZ_VERSION" "$XZ_URL" "$XZ_SHA256" \
    --disable-xz --disable-xzdec --disable-lzmadec --disable-lzmainfo \
    --disable-scripts --disable-doc --disable-nls
build_autoconf_static libffi "$LIBFFI_VERSION" "$LIBFFI_URL" "$LIBFFI_SHA256" \
    --disable-docs --disable-multi-os-directory
build_openssl

if find "$PREFIX/lib" -name '*.so*' | grep -q .; then
    echo "Shared libraries leaked into $PREFIX/lib:" >&2
    find "$PREFIX/lib" -name '*.so*' >&2
    exit 1
fi
