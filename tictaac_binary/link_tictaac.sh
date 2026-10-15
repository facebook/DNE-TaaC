#!/bin/bash

set -euo pipefail

if [[ $# -ne 7 ]]; then
    echo "Usage: $0 <python-prefix> <deps-prefix> <cpp-stack-install-root> <builtins-root> <payload-zip> <work-dir> <output-binary>" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/versions.sh"

PYTHON_PREFIX="$1"
DEPS="$2"
CPP_INSTALL_ROOT="$3"
BUILTINS_ROOT="$4"
PAYLOAD_ZIP="$5"
WORK="$6"
OUTPUT="$7"

PYTHON_INCLUDE="$PYTHON_PREFIX/include/python$CPYTHON_ABI"
PYTHON_STATIC_DIR="$PYTHON_PREFIX/lib/python$CPYTHON_ABI/config-static"
LIBPYTHON="$PYTHON_PREFIX/lib/libpython$CPYTHON_ABI.a"

ARCHIVES_NOT_LINKED=(
    libgtest.a
    libgtest_main.a
    libgmock.a
    libgmock_main.a
    libbenchmark.a
    libbenchmark_main.a
    libfolly_test_util.a
    libfollybenchmark.a
    libfolly_benchmark_util.a
    libfizz_test_support.a
    'libcompiler*.a'
    libwhisker.a
)

GLIBC_LIBRARIES_PATTERN='^(linux-vdso\.so\.[0-9]+|libc\.so\.6|libm\.so\.6|libpthread\.so\.0|libdl\.so\.2|librt\.so\.1|libutil\.so\.1|/lib64/ld-linux-x86-64\.so\.2)$'

generate_inittab() {
    local registry="$1"
    local source="$2"

    local duplicates
    duplicates="$(cut -f1 "$registry" | sort | uniq -d)"
    if [[ -n "$duplicates" ]]; then
        echo "Builtin modules registered more than once: $duplicates" >&2
        return 1
    fi

    {
        echo '#include <Python.h>'
        cut -f2 "$registry" | sed 's/.*/extern PyObject *&(void);/'
        echo 'struct _inittab tictaac_builtin_modules[] = {'
        awk -F'\t' '{printf "    {\"%s\", %s},\n", $1, $2}' "$registry"
        echo '    {NULL, NULL},'
        echo '};'
    } > "$source"
}

collect_archives() {
    local -A seen=()
    local archive name skipped
    for archive in "$DEPS"/lib/*.a "$CPP_INSTALL_ROOT"/*/lib/*.a "$CPP_INSTALL_ROOT"/*/lib64/*.a; do
        [[ -f "$archive" ]] || continue
        name="$(basename "$archive")"
        skipped=0
        for excluded in "${ARCHIVES_NOT_LINKED[@]}"; do
            # shellcheck disable=SC2053
            [[ "$name" == $excluded ]] && skipped=1
        done
        if [[ "$skipped" -eq 0 && -z "${seen[$name]:-}" ]]; then
            seen[$name]=1
            echo "$archive"
        fi
    done
}

rm -rf "$WORK"
mkdir -p "$WORK" "$(dirname "$OUTPUT")"

registry="$WORK/modules.tsv"
cat "$BUILTINS_ROOT"/*/modules.tsv > "$registry"
generate_inittab "$registry" "$WORK/builtins.c"

gcc -O2 -fPIC -I"$PYTHON_INCLUDE" -c "$SCRIPT_DIR/launcher.c" -o "$WORK/launcher.o"
gcc -O2 -fPIC -I"$PYTHON_INCLUDE" -c "$WORK/builtins.c" -o "$WORK/builtins.o"

mapfile -t builtin_objects < <(cut -f3 "$registry")
extra_inputs=()
for inputs_file in "$BUILTINS_ROOT"/*/link-inputs.txt; do
    [[ -f "$inputs_file" ]] || continue
    mapfile -t -O "${#extra_inputs[@]}" extra_inputs < "$inputs_file"
done
mapfile -t archives < <(collect_archives)
extra_objects=()
for input in "${extra_inputs[@]}"; do
    if [[ "$input" == *.a ]]; then
        archives=("$input" "${archives[@]}")
    else
        extra_objects+=("$input")
    fi
done
read -r -a python_link_flags < "$PYTHON_STATIC_DIR/link-flags"

g++ -o "$WORK/tictaac" \
    "$WORK/launcher.o" "$WORK/builtins.o" \
    "${builtin_objects[@]}" \
    "${extra_objects[@]}" \
    -Wl,--start-group "${archives[@]}" "$LIBPYTHON" "${python_link_flags[@]}" -liberty -Wl,--end-group \
    -static-libstdc++ -static-libgcc \
    -Wl,--export-dynamic \
    -lpthread -ldl -lrt -lutil -lm

strip --strip-debug "$WORK/tictaac"

while read -r library; do
    if [[ ! "$library" =~ $GLIBC_LIBRARIES_PATTERN ]]; then
        echo "tictaac links a non-glibc shared library: $library" >&2
        exit 1
    fi
done < <(ldd "$WORK/tictaac" | awk '{print $1}')

cat "$WORK/tictaac" "$PAYLOAD_ZIP" > "$OUTPUT"
zip -q -A "$OUTPUT"
chmod 0755 "$OUTPUT"
