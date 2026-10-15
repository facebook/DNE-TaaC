#!/bin/bash
# Build the standalone tictaac executable.
#
# Usage:
#   ./scripts/build_tictaac_binary.sh                   # writes dist/tictaac
#   ./scripts/build_tictaac_binary.sh --output-dir DIR  # writes DIR/tictaac
#   ./scripts/build_tictaac_binary.sh --jobs 8          # cap build parallelism
#
# Requires Docker. Builds the FBOSS base image first if it is missing.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BUILDER_IMAGE="tictaac-binary-builder"
BINARY_IN_IMAGE="/opt/tictaac/dist/tictaac"
GIB_PER_COMPILE_JOB=5

usage() {
    grep '^#' "$0" | sed -n '2,9p' | sed 's/^# \{0,1\}//' >&2
    exit 1
}

default_jobs() {
    local cpus memory_gib by_memory
    cpus="$(nproc)"
    memory_gib="$(awk '/^MemTotal:/ {print int($2 / 1048576)}' /proc/meminfo)"
    by_memory=$((memory_gib / GIB_PER_COMPILE_JOB))
    ((by_memory < 1)) && by_memory=1
    echo $((cpus < by_memory ? cpus : by_memory))
}

OUTPUT_DIR="$REPO_ROOT/dist"
JOBS="$(default_jobs)"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir)
            [[ $# -ge 2 && -n "$2" ]] || usage
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --jobs)
            [[ $# -ge 2 && "$2" =~ ^[1-9][0-9]*$ ]] || usage
            JOBS="$2"
            shift 2
            ;;
        *) usage ;;
    esac
done

BASE_IMAGE="$("$REPO_ROOT/docker/ensure-base-image.sh")"

echo "Building tictaac with $JOBS parallel jobs ..." >&2
docker build \
    --build-arg "BASE_IMAGE=$BASE_IMAGE" \
    --build-arg "NUM_JOBS=$JOBS" \
    -f "$REPO_ROOT/docker/Dockerfile.tictaac-binary" \
    -t "$BUILDER_IMAGE" \
    "$REPO_ROOT"

container=
rc=
for sig in 1 2 3 13 15; do eval "trap 'exit $((sig + 128))' $sig"; done
trap 'rc=$?; set +e; [[ -n "$container" ]] && docker rm -f "$container" >/dev/null; exit $rc' EXIT
container="$(docker create "$BUILDER_IMAGE")"

mkdir -p "$OUTPUT_DIR"
docker cp "$container:$BINARY_IN_IMAGE" "$OUTPUT_DIR/tictaac"
echo "Built $OUTPUT_DIR/tictaac"
