#!/bin/bash

set -euo pipefail

if [[ $# -ne 5 ]]; then
    echo "Usage: $0 <downloads-dir> <work-dir> <deps-prefix> <python-prefix> <jobs>" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/versions.sh"
source "$SCRIPT_DIR/common.sh"

DOWNLOADS="$1"
WORK="$2"
DEPS="$3"
PREFIX="$4"
JOBS="$5"

MODULES_LINKING_SYSTEM_SHARED_LIBS=(
    _crypt
    _curses
    _curses_panel
    _dbm
    _gdbm
    _sqlite3
    _tkinter
    _uuid
    nis
    readline
)

archive="$DOWNLOADS/Python-$CPYTHON_VERSION.tar.xz"
mkdir -p "$DOWNLOADS" "$WORK"
fetch_verified "$CPYTHON_URL" "$CPYTHON_SHA256" "$archive"
extract_fresh "$archive" "$WORK" "Python-$CPYTHON_VERSION"

disabled_module_vars=()
for module in "${MODULES_LINKING_SYSTEM_SHARED_LIBS[@]}"; do
    disabled_module_vars+=("py_cv_module_${module}=n/a")
done

cd "$WORK/Python-$CPYTHON_VERSION"
env "${disabled_module_vars[@]}" \
    MODULE_BUILDTYPE=static \
    PKG_CONFIG_PATH="$DEPS/lib/pkgconfig" \
    CPPFLAGS="-I$DEPS/include" \
    LDFLAGS="-L$DEPS/lib" \
    CFLAGS="-fPIC" \
    ./configure \
    --prefix="$PREFIX" \
    --disable-shared \
    --disable-test-modules \
    --without-ensurepip \
    --with-openssl="$DEPS" \
    --with-openssl-rpath=no
make -j"$JOBS"
make install

static_link_dir="$PREFIX/lib/python$CPYTHON_ABI/config-static"
mkdir -p "$static_link_dir"
cp Modules/expat/libexpat.a Modules/_decimal/libmpdec/libmpdec.a \
    Modules/_hacl/libHacl_Hash_SHA2.a "$static_link_dir/"
rm -f "$static_link_dir/$PYTHON_INTERPRETER_SYMBOLS_STUB"
gcc -shared -o "$static_link_dir/$PYTHON_INTERPRETER_SYMBOLS_STUB" -x c /dev/null

print_link_makefile=
rc=
for sig in 1 2 3 13 15; do eval "trap 'exit $((sig + 128))' $sig"; done
trap 'rc=$?; set +e; rm -f "$print_link_makefile"; exit $rc' EXIT
print_link_makefile="$(mktemp)"
printf 'print-link-flags:\n\t@echo $(MODLIBS) $(LIBS) $(SYSLIBS)\n' > "$print_link_makefile"
make -s -f Makefile -f "$print_link_makefile" print-link-flags \
    | sed -E "s#Modules/[^ ]*/(lib[^ /]*\\.a)#$static_link_dir/\\1#g" \
    > "$static_link_dir/link-flags"

python_binary="$PREFIX/bin/python$CPYTHON_ABI"
missing_modules="$("$python_binary" - <<'EOF'
import sys
required = ("_ssl", "_hashlib", "_ctypes", "zlib", "_bz2", "_lzma", "_decimal", "_asyncio", "select", "_socket")
print(" ".join(name for name in required if name not in sys.builtin_module_names))
EOF
)"
if [[ -n "$missing_modules" ]]; then
    echo "Stdlib modules not built in statically: $missing_modules" >&2
    exit 1
fi

pip_wheel="$DOWNLOADS/$PIP_WHEEL"
fetch_verified "$PIP_URL" "$PIP_SHA256" "$pip_wheel"
"$python_binary" "$pip_wheel/pip" install --no-cache-dir --require-hashes \
    --only-binary :all: -r "$SCRIPT_DIR/build-requirements.txt"
CFLAGS="-I$DEPS/include" LDFLAGS="-L$DEPS/lib" \
    "$python_binary" -m pip install --no-cache-dir --require-hashes \
    --no-binary :all: --no-build-isolation \
    -r "$SCRIPT_DIR/build-requirements-source.txt"

dynamic_libraries="$(ldd "$python_binary" | awk '{print $1}')"
for library in $dynamic_libraries; do
    case "$library" in
        linux-vdso.so.*|libc.so.*|libm.so.*|libpthread.so.*|libdl.so.*|libutil.so.*|librt.so.*|/lib64/ld-linux-x86-64.so.*) ;;
        *)
            echo "$python_binary links a non-glibc shared library: $library" >&2
            exit 1
            ;;
    esac
done
