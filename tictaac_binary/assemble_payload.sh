#!/bin/bash

set -euo pipefail

if [[ $# -ne 5 ]]; then
    echo "Usage: $0 <taac-src-dir> <python-prefix> <cpp-stack-install-root> <work-dir> <output-zip>" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/versions.sh"

TAAC_SRC="$1"
PYTHON_PREFIX="$2"
CPP_INSTALL_ROOT="$3"
WORK="$4"
OUTPUT_ZIP="$5"

PYTHON_BINARY="$PYTHON_PREFIX/bin/python$CPYTHON_ABI"
STDLIB="$PYTHON_PREFIX/lib/python$CPYTHON_ABI"
STAGE="$WORK/payload"

STDLIB_EXCLUDES=(
    "./test"
    "./idlelib"
    "./tkinter"
    "./turtledemo"
    "./ensurepip"
    "./site-packages"
    "./lib-dynload"
    "./config-*"
    "*/__pycache__"
)

THRIFT_RUNTIME_PACKAGES=(thrift folly apache)
THRIFT_WHEEL_GLOB="fbthrift-python*/share/thrift/wheels/thrift-*.whl"

copy_tree_without_native_code() {
    local source="$1"
    local destination="$2"
    mkdir -p "$destination"
    tar -C "$source" \
        --exclude='*.so' --exclude='*.so.*' --exclude='__pycache__' \
        --exclude='*.pyx' --exclude='*.pxd' --exclude='*.cpp' --exclude='*.h' \
        -cf - . | tar -C "$destination" -xf -
}

stage_stdlib() {
    local exclude_args=()
    for pattern in "${STDLIB_EXCLUDES[@]}"; do
        exclude_args+=(--exclude="$pattern")
    done
    tar -C "$STDLIB" "${exclude_args[@]}" -cf - . | tar -C "$STAGE" -xf -
}

stage_runtime_wheels() {
    local wheel_target="$WORK/wheels"
    rm -rf "$wheel_target"
    "$PYTHON_BINARY" -m pip install --no-cache-dir --no-deps --require-hashes \
        --only-binary :all: \
        --implementation cp --python-version "$CPYTHON_ABI" \
        --abi "cp${CPYTHON_ABI/./}" --abi abi3 --abi none \
        --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 \
        --platform manylinux_2_28_x86_64 --platform any \
        --target "$wheel_target" \
        -r "$SCRIPT_DIR/runtime-requirements.txt"
    rm -rf "${wheel_target:?}/bin"
    find "$wheel_target" -maxdepth 1 -name '*.libs' -exec rm -rf {} +
    copy_tree_without_native_code "$wheel_target" "$STAGE"
}

stage_taac_sources() {
    copy_tree_without_native_code "$TAAC_SRC/taac" "$STAGE/taac"
}

stage_generated_thrift() {
    local site_packages
    for site_packages in "$CPP_INSTALL_ROOT"/taac-*/lib/python3/site-packages; do
        copy_tree_without_native_code "$site_packages" "$STAGE"
    done
}

stage_thrift_runtime() {
    local wheels=()
    mapfile -t wheels < <(compgen -G "$CPP_INSTALL_ROOT/$THRIFT_WHEEL_GLOB")
    if [[ ${#wheels[@]} -ne 1 ]]; then
        echo "Expected one thrift wheel matching $CPP_INSTALL_ROOT/$THRIFT_WHEEL_GLOB, found ${#wheels[@]}" >&2
        return 1
    fi
    local unpacked="$WORK/thrift-wheel"
    rm -rf "$unpacked"
    mkdir -p "$unpacked"
    unzip -q "${wheels[0]}" -d "$unpacked"
    find "$unpacked" -maxdepth 1 -name '*.libs' -exec rm -rf {} +
    local package
    for package in "${THRIFT_RUNTIME_PACKAGES[@]}"; do
        if [[ ! -d "$unpacked/$package" ]]; then
            echo "Thrift wheel ${wheels[0]} has no $package package" >&2
            return 1
        fi
    done
    copy_tree_without_native_code "$unpacked" "$STAGE"
}

rm -rf "$STAGE"
mkdir -p "$STAGE" "$(dirname "$OUTPUT_ZIP")"

stage_stdlib
stage_runtime_wheels
stage_thrift_runtime
stage_generated_thrift
stage_taac_sources

leftover_native="$(find "$STAGE" -name '*.so' -o -name '*.so.*')"
if [[ -n "$leftover_native" ]]; then
    echo "Native code leaked into the payload:" >&2
    echo "$leftover_native" >&2
    exit 1
fi

"$PYTHON_BINARY" -m compileall -q -j 0 -b \
    --invalidation-mode unchecked-hash "$STAGE" >/dev/null

rm -f "$OUTPUT_ZIP"
(
    cd "$STAGE"
    find . -mindepth 1 | LC_ALL=C sort | sed 's#^\./##' | zip -q -X -@ "$OUTPUT_ZIP"
)
