#!/bin/bash

set -euo pipefail

if [[ $# -ne 6 ]]; then
    echo "Usage: $0 <downloads-dir> <work-dir> <deps-prefix> <python-prefix> <rust-home> <output-dir>" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/versions.sh"
source "$SCRIPT_DIR/common.sh"

DOWNLOADS="$1"
WORK="$2"
DEPS="$3"
PYTHON_PREFIX="$4"
RUST_HOME="$5"
OUTPUT="$6"

export RUSTUP_HOME="$RUST_HOME/rustup"
export CARGO_HOME="$RUST_HOME/cargo"
export PATH="$CARGO_HOME/bin:$PATH"
export PYO3_PYTHON="$PYTHON_PREFIX/bin/python$CPYTHON_ABI"
export PYO3_BUILD_EXTENSION_MODULE=1
export OPENSSL_DIR="$DEPS"
export OPENSSL_STATIC=0
export CFLAGS="-O2 -fPIC"

REGISTRY="$OUTPUT/modules.tsv"

install_rust_toolchain() {
    if [[ -x "$CARGO_HOME/bin/cargo" ]] && "$CARGO_HOME/bin/rustc" --version | grep -q "^rustc $RUST_TOOLCHAIN "; then
        return
    fi
    local rustup_init="$DOWNLOADS/rustup-init-$RUST_TOOLCHAIN"
    fetch_verified "$RUSTUP_INIT_URL" "$RUSTUP_INIT_SHA256" "$rustup_init"
    chmod +x "$rustup_init"
    "$rustup_init" -y --no-modify-path --profile minimal --default-toolchain "$RUST_TOOLCHAIN"
}

build_rust_builtin() {
    local distribution="$1"
    local version="$2"
    local sha256="$3"
    local manifest_relative="$4"
    local library_name="$5"
    local original_init_symbol="$6"
    local module="$7"

    local archive="$DOWNLOADS/$distribution-$version.tar.gz"
    fetch_verified "$(pypi_sdist_url "$distribution" "$version")" "$sha256" "$archive"
    extract_fresh "$archive" "$WORK" "$distribution-$version"

    local source_dir="$WORK/$distribution-$version"
    local target_dir="$WORK/$distribution-$version-target"
    cargo rustc --locked --release --lib \
        --manifest-path "$source_dir/$manifest_relative" \
        --target-dir "$target_dir" \
        --crate-type staticlib

    local object="$OUTPUT/$module.o"
    isolate_builtin_object "$object" "$original_init_symbol" "$module" \
        "$target_dir/release/lib$library_name.a"
    register_builtin "$REGISTRY" "$module" "$object"
}

install_rust_toolchain
rm -rf "$OUTPUT"
mkdir -p "$OUTPUT" "$WORK" "$DOWNLOADS"
: > "$REGISTRY"

build_rust_builtin pydantic_core "$PYDANTIC_CORE_VERSION" "$PYDANTIC_CORE_SHA256" \
    Cargo.toml _pydantic_core PyInit__pydantic_core pydantic_core._pydantic_core
build_rust_builtin cryptography "$CRYPTOGRAPHY_VERSION" "$CRYPTOGRAPHY_SHA256" \
    src/rust/Cargo.toml cryptography_rust PyInit__rust cryptography.hazmat.bindings._rust
build_rust_builtin bcrypt "$BCRYPT_VERSION" "$BCRYPT_SHA256" \
    src/_bcrypt/Cargo.toml bcrypt_rust PyInit__bcrypt bcrypt._bcrypt
