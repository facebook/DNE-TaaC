#!/bin/bash

set -euo pipefail

if [[ $# -lt 6 || $# -gt 7 ]]; then
    echo "Usage: $0 <deps|taac> <taac-src-dir> <scratch-dir> <deps-prefix> <python-prefix> <jobs> [lfs-cache-dir]" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/versions.sh"

PHASE="$1"
TAAC_SRC="$2"
SCRATCH="$3"
DEPS="$4"
PYTHON_PREFIX="$5"
JOBS="$6"
LFS_CACHE="${7:-}"

case "$PHASE" in
    deps) phase_flag=--only-deps ;;
    taac) phase_flag=--no-deps ;;
    *)
        echo "Unknown phase '$PHASE': expected deps or taac" >&2
        exit 1
        ;;
esac

SCCACHE_PORT_BASE=20000
SCCACHE_PORT_RANGE=20000
export SCCACHE_SERVER_PORT="${SCCACHE_SERVER_PORT:-$((SCCACHE_PORT_BASE + $$ % SCCACHE_PORT_RANGE))}"

PYTHON_BINARY="$PYTHON_PREFIX/bin/python$CPYTHON_ABI"
GETDEPS="$TAAC_SRC/build/fbcode_builder/getdeps.py"
TOP_LEVEL_PROJECT=taac

PYTHON_SYMBOLS_FROM_INTERPRETER="$PYTHON_PREFIX/lib/python$CPYTHON_ABI/config-static/$PYTHON_INTERPRETER_SYMBOLS_STUB"

cmake_defines="$("$PYTHON_BINARY" - "$PYTHON_BINARY" "$PYTHON_PREFIX" "$DEPS" "$PYTHON_SYMBOLS_FROM_INTERPRETER" <<'EOF'
import json
import sys

python_binary, python_prefix, deps, python_library = sys.argv[1:]
print(json.dumps({
    "Python3_LIBRARY": python_library,
    "BUILD_SHARED_LIBS": "OFF",
    "CMAKE_POSITION_INDEPENDENT_CODE": "ON",
    "enable_tests": "OFF",
    "Python3_EXECUTABLE": python_binary,
    "Python3_ROOT_DIR": python_prefix,
    "Python3_FIND_STRATEGY": "LOCATION",
    "OPENSSL_ROOT_DIR": deps,
    "OPENSSL_USE_STATIC_LIBS": "TRUE",
}))
EOF
)"

fbthrift_build_tools="$PYTHON_PREFIX/lib/fbthrift-build-tools"
"$PYTHON_BINARY" -m pip install --no-cache-dir --require-hashes --only-binary :all: \
    --upgrade --target "$fbthrift_build_tools" \
    -r "$SCRIPT_DIR/build-requirements-fbthrift.txt"
export PYTHONPATH="$fbthrift_build_tools${PYTHONPATH:+:$PYTHONPATH}"

getdeps_args=(--scratch-path "$SCRATCH")
if [[ -n "$LFS_CACHE" ]]; then
    getdeps_args+=(--lfs-path "$LFS_CACHE")
fi

mkdir -p "$TAAC_SRC/.git"
echo taac > "$TAAC_SRC/.projectid"

cd "$TAAC_SRC"
python3 "$GETDEPS" "${getdeps_args[@]}" \
    --extra-cmake-defines="$cmake_defines" \
    build --no-tests --num-jobs "$JOBS" "$phase_flag" \
    --src-dir="$TOP_LEVEL_PROJECT:$TAAC_SRC" \
    "$TOP_LEVEL_PROJECT"
