#!/bin/bash
# Build the vendor-shippable TAAC Docker image (fboss-taac).
#
# Builds the FBOSS base image if missing, then runs
# docker/Dockerfile.taac to produce the final image.
#
# Usage:
#   ./docker/build-taac-image.sh                       # default tag, default parallelism
#   ./docker/build-taac-image.sh --tag my-taac:v1      # custom tag
#   ./docker/build-taac-image.sh --rebuild-base-image  # rebuild the compiler/runtime base
#   ./docker/build-taac-image.sh --rebuild-taac-image  # rebuild only TAAC without layer cache
#   ./docker/build-taac-image.sh --no-cache            # legacy alias: rebuild both images
#   ./docker/build-taac-image.sh --num-jobs 4          # cap getdeps parallelism
#
# The revision-tagged FBOSS base image is reused by default. If it is missing,
# it is built automatically. --rebuild-base-image forces a clean rebuild to
# refresh the compiler and CentOS packages that also ship in the runtime stage.
#
# Parallelism note: the fbthrift / cc1plus compile phase is the main
# memory hog (~5 GiB per worker). On memory-constrained hosts (<~6 GiB
# per worker) the OOM killer will reap workers — and often sshd along
# with them — long before disk or CPU saturates. Default leaves
# getdeps' own default in place (= nproc); pass `--num-jobs N` to cap
# when you've seen the OOM killer fire. Rule of thumb: N = min(nproc,
# floor(RAM_GiB / 5)).
#
# Env overrides:
#   FBOSS_IMAGE_SRC   Where to clone/find meta/fboss for the base image
#                     build context (default: ~/.taac-fboss-image-src)
#   TAAC_FBCODE_DIR   Internal fbcode checkout whose current FBOSS Docker files
#                     should be validated instead of the pinned public copies

set -euo pipefail

TAG="fboss-taac"
REBUILD_BASE_IMAGE=0
REBUILD_TAAC_IMAGE=0
NUM_JOBS=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --tag)
            if [[ $# -lt 2 || -z "${2:-}" ]]; then
                echo "Error: --tag requires a value" >&2
                exit 1
            fi
            TAG="$2"
            shift 2
            ;;
        --rebuild-base-image)
            REBUILD_BASE_IMAGE=1
            shift
            ;;
        --rebuild-taac-image)
            REBUILD_TAAC_IMAGE=1
            shift
            ;;
        --no-cache)
            REBUILD_BASE_IMAGE=1
            REBUILD_TAAC_IMAGE=1
            shift
            ;;
        --num-jobs)
            if [[ $# -lt 2 || -z "${2:-}" ]]; then
                echo "Error: --num-jobs requires a value" >&2
                exit 1
            fi
            if ! [[ "$2" =~ ^[1-9][0-9]*$ ]]; then
                echo "Error: --num-jobs must be a positive integer, got: $2" >&2
                exit 1
            fi
            NUM_JOBS="$2"
            shift 2
            ;;
        *)
            echo "Error: unknown argument: $1" >&2
            echo "Usage: $0 [--tag <name>] [--rebuild-base-image] [--rebuild-taac-image] [--no-cache] [--num-jobs <N>]" >&2
            exit 1
            ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENSURE_BASE_ARGS=()
if [[ "$REBUILD_BASE_IMAGE" -eq 1 ]]; then
    ENSURE_BASE_ARGS+=(--rebuild)
fi
BASE_IMAGE="$("$SCRIPT_DIR/ensure-base-image.sh" "${ENSURE_BASE_ARGS[@]}")"

DOCKER_BUILD_ARGS=()
if [[ "$REBUILD_TAAC_IMAGE" -eq 1 ]]; then
    DOCKER_BUILD_ARGS+=(--no-cache)
fi
# Empty NUM_JOBS arg lets Dockerfile.taac fall through to getdeps'
# nproc default; only forward when the caller set --num-jobs N.
if [[ -n "$NUM_JOBS" ]]; then
    DOCKER_BUILD_ARGS+=(--build-arg "NUM_JOBS=$NUM_JOBS")
    echo "Capping getdeps parallelism at $NUM_JOBS"
fi

echo "Building $TAG from docker/Dockerfile.taac (base: $BASE_IMAGE) ..."
docker build \
    "${DOCKER_BUILD_ARGS[@]}" \
    --build-arg "BASE_IMAGE=$BASE_IMAGE" \
    -f "$REPO_ROOT/docker/Dockerfile.taac" \
    -t "$TAG" \
    "$REPO_ROOT"

echo "Done: $TAG"
