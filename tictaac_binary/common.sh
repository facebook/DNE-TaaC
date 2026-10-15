#!/bin/bash

fetch_verified() {
    local url="$1"
    local expected_sha256="$2"
    local destination="$3"

    if [[ ! -f "$destination" ]]; then
        curl --fail --silent --show-error --location --retry 3 \
            --output "$destination.partial" "$url"
        mv "$destination.partial" "$destination"
    fi

    local actual_sha256
    actual_sha256="$(sha256sum "$destination" | cut -d' ' -f1)"
    if [[ "$actual_sha256" != "$expected_sha256" ]]; then
        echo "SHA-256 mismatch for $url: expected $expected_sha256, got $actual_sha256" >&2
        rm -f "$destination"
        return 1
    fi
}

pypi_sdist_url() {
    local name="$1"
    local version="$2"
    echo "https://files.pythonhosted.org/packages/source/${name:0:1}/$name/$name-$version.tar.gz"
}

builtin_init_symbol() {
    local module="$1"
    echo "PyInit_${module//./_DOT_}"
}

register_builtin() {
    local registry="$1"
    local module="$2"
    local object="$3"
    printf '%s\t%s\t%s\n' "$module" "$(builtin_init_symbol "$module")" "$object" >> "$registry"
}

isolate_builtin_object() {
    local output="$1"
    local original_init_symbol="$2"
    local module="$3"
    shift 3

    ld -r -o "$output.partial" --whole-archive "$@" --no-whole-archive
    {
        echo "$original_init_symbol"
        nm --defined-only --extern-only "$output.partial" | awk '$2 ~ /^[WVu]$/ {print $3}'
    } > "$output.globals"
    objcopy --strip-debug --keep-global-symbols="$output.globals" \
        "$output.partial" "$output.localized"
    rm -f "$output.globals"
    objcopy --redefine-sym "$original_init_symbol=$(builtin_init_symbol "$module")" \
        "$output.localized" "$output"
    rm -f "$output.partial" "$output.localized"

    local init_symbol
    init_symbol="$(builtin_init_symbol "$module")"
    if [[ -z "$(nm --defined-only --extern-only "$output" | awk -v symbol="$init_symbol" '$2 == "T" && $3 == symbol')" ]]; then
        echo "$output does not export $init_symbol" >&2
        return 1
    fi
    if [[ -n "$(nm --defined-only "$output" | awk '$3 == "_PyRuntime" && $2 ~ /^[bBdD]$/')" ]]; then
        echo "$output embeds its own copy of the CPython runtime" >&2
        return 1
    fi
}

extract_fresh() {
    local archive="$1"
    local parent="$2"
    local directory="$3"

    rm -rf "${parent:?}/$directory"
    tar -xf "$archive" -C "$parent"
    if [[ ! -d "$parent/$directory" ]]; then
        echo "Archive $archive did not produce $parent/$directory" >&2
        return 1
    fi
}
