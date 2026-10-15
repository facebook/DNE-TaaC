#!/bin/bash

set -euo pipefail

if [[ $# -ne 7 ]]; then
    echo "Usage: $0 <downloads-dir> <work-dir> <deps-prefix> <libsodium-prefix> <python-prefix> <output-dir> <jobs>" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/versions.sh"
source "$SCRIPT_DIR/common.sh"

DOWNLOADS="$1"
WORK="$2"
DEPS="$3"
LIBSODIUM="$4"
PYTHON_PREFIX="$5"
OUTPUT="$6"
JOBS="$7"

PYTHON_BINARY="$PYTHON_PREFIX/bin/python$CPYTHON_ABI"
REGISTRY="$OUTPUT/modules.tsv"

build_setuptools_builtin() {
    local distribution="$1"
    local version="$2"
    local sha256="$3"
    local original_init_symbol="$4"
    local module="$5"
    shift 5

    local archive="$DOWNLOADS/$distribution-$version.tar.gz"
    fetch_verified "$(pypi_sdist_url "$distribution" "$version")" "$sha256" "$archive"
    extract_fresh "$archive" "$WORK" "$distribution-$version"

    local source_dir="$WORK/$distribution-$version"
    local build_temp="$WORK/$distribution-$version-objects"
    (
        cd "$source_dir"
        env "$@" \
            CFLAGS="-O2 -fPIC -I$DEPS/include -I$LIBSODIUM/include" \
            LDFLAGS="-L$DEPS/lib -L$LIBSODIUM/lib" \
            "$PYTHON_BINARY" setup.py build_ext \
            --build-temp "$build_temp" \
            --build-lib "$WORK/$distribution-$version-lib" \
            --parallel "$JOBS"
    )

    local objects=()
    mapfile -t objects < <(find "$build_temp" -name '*.o' | sort)
    if [[ ${#objects[@]} -eq 0 ]]; then
        echo "setuptools produced no objects for $distribution" >&2
        return 1
    fi

    local object="$OUTPUT/$module.o"
    isolate_builtin_object "$object" "$original_init_symbol" "$module" "${objects[@]}"
    register_builtin "$REGISTRY" "$module" "$object"
}

rm -rf "$OUTPUT"
mkdir -p "$OUTPUT" "$WORK" "$DOWNLOADS"
: > "$REGISTRY"

build_setuptools_builtin cffi "$CFFI_VERSION" "$CFFI_SHA256" \
    PyInit__cffi_backend _cffi_backend
build_setuptools_builtin pynacl "$PYNACL_VERSION" "$PYNACL_SHA256" \
    PyInit__sodium nacl._sodium \
    SODIUM_INSTALL=system
build_setuptools_builtin grpcio "$GRPCIO_VERSION" "$GRPCIO_SHA256" \
    PyInit_cygrpc grpc._cython.cygrpc \
    GRPC_PYTHON_BUILD_SYSTEM_OPENSSL=1 \
    GRPC_PYTHON_BUILD_SYSTEM_ZLIB=1 \
    GRPC_PYTHON_BUILD_EXT_COMPILER_JOBS="$JOBS" \
    GRPC_BUILD_WITH_BORING_SSL_ASM=0
