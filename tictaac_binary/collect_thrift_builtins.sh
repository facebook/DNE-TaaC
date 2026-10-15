#!/bin/bash

set -euo pipefail

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 <getdeps-scratch-dir> <output-dir>" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

SCRATCH="$1"
OUTPUT="$2"

REGISTRY="$OUTPUT/modules.tsv"
LINK_INPUTS="$OUTPUT/link-inputs.txt"
OBJECTS_INTERPOSING_DYNAMIC_LIBSTDCXX=(ExceptionTracerLib.cpp.o)

archive_shared_library_objects() {
    local project="$1"
    local ninja_target="$2"
    local archive="$3"

    local ninja
    ninja="$(compgen -G "$SCRATCH/installed/ninja-*/bin/ninja" | head -1)"
    local build_dir="$SCRATCH/build/$project"
    local link_command
    link_command="$(cd "$build_dir" && "$ninja" -t commands "$ninja_target" | awk '/ -shared / {line = $0} END {print line}')"

    local objects=()
    local excluded_pattern
    excluded_pattern="$(printf '/%s$|' "${OBJECTS_INTERPOSING_DYNAMIC_LIBSTDCXX[@]}")"
    mapfile -t objects < <(tr ' ' '\n' <<< "$link_command" | grep '\.o$' \
        | grep -Ev "${excluded_pattern%|}" | sed "s#^#$build_dir/#")
    if [[ ${#objects[@]} -eq 0 ]]; then
        echo "No objects in the link command for $project:$ninja_target" >&2
        return 1
    fi
    rm -f "$archive"
    ar rcs "$archive" "${objects[@]}"
    echo "$archive" >> "$LINK_INPUTS"
}

defined_init_symbol() {
    nm --defined-only "$1" | awk '$2 == "T" && $3 ~ /^PyInit_/ {print $3}'
}

collect_cython_project() {
    local project="$1"
    local helper_target="$2"

    local build_dir
    build_dir="$(ls -d "$SCRATCH/build/$project" 2>/dev/null || ls -d "$SCRATCH/build/$project"-* | head -1)"
    local setuptools_temp
    setuptools_temp="$(find "$build_dir" -type d -path '*/cybld/build/temp.*' | head -1)"
    if [[ -z "$setuptools_temp" ]]; then
        echo "No setuptools build directory under $build_dir" >&2
        return 1
    fi

    local helper_dir="$OUTPUT/$project-$helper_target"
    mkdir -p "$helper_dir"
    local -A helper_sources=()
    local object name
    while read -r object; do
        name="$(basename "$object" .cpp.o)"
        helper_sources[$name]=1
        cp "$object" "$helper_dir/$name.o"
        echo "$helper_dir/$name.o" >> "$LINK_INPUTS"
    done < <(find "$build_dir" -path "*/CMakeFiles/$helper_target.dir/*" -name '*.cpp.o' | sort)
    if [[ ${#helper_sources[@]} -eq 0 ]]; then
        echo "No $helper_target objects under $build_dir" >&2
        return 1
    fi

    local relative init_symbol module destination
    while read -r object; do
        relative="${object#"$setuptools_temp"/}"
        init_symbol="$(defined_init_symbol "$object")"
        if [[ -z "$init_symbol" ]]; then
            name="$(basename "$object" .o)"
            if [[ -z "${helper_sources[$name]:-}" ]]; then
                destination="$helper_dir/extension-helper-$name.o"
                cp "$object" "$destination"
                echo "$destination" >> "$LINK_INPUTS"
            fi
            continue
        fi
        relative="${relative#generated/}"
        module="$(dirname "$relative" | tr '/' '.').${init_symbol#PyInit_}"
        destination="$OUTPUT/$module.o"
        {
            echo "$init_symbol $(builtin_init_symbol "$module")"
            readelf -W -s "$object" 2>/dev/null \
                | awk -v prefix="tictaac_${module//./_DOT_}_" \
                    '$5 ~ /^(LOCAL|WEAK|UNIQUE)$/ && $7 != "UND" && $8 ~ /__pyx/ {print $8, prefix $8}' \
                | sort -u
        } > "$destination.renames"
        objcopy --redefine-syms="$destination.renames" "$object" "$destination"
        rm -f "$destination.renames"
        register_builtin "$REGISTRY" "$module" "$destination"
    done < <(find "$setuptools_temp" -name '*.o' -not -path '*/test/*' | sort)
}

rm -rf "$OUTPUT"
mkdir -p "$OUTPUT"
: > "$REGISTRY"
: > "$LINK_INPUTS"

archive_shared_library_objects folly-python folly "$OUTPUT/libfolly.a"
collect_cython_project folly-python folly_python_cpp
collect_cython_project fbthrift-python thrift_python_cpp
