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
#   FBOSS_IMAGE_SRC   Where to clone/find facebook/fboss for the base image
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
FBOSS_IMAGE_SRC="${FBOSS_IMAGE_SRC:-$HOME/.taac-fboss-image-src}"
FBOSS_PUBLIC_URL="https://github.com/facebook/fboss.git"

# Reuse the fboss pin from the fboss-thrift-defs manifest as the base image
# recipe: one fboss commit supplies both the build environment and the thrift
# defs, and there is a single place to bump. An unpinned clone would rebuild
# the base from whatever fboss main happened to be that day.
FBOSS_REV=$(grep -E '^rev[[:space:]]*=' "$REPO_ROOT/getdeps/manifests/fboss-thrift-defs" \
    | head -1 | awk -F'=' '{print $2}' | tr -d ' ')
if [[ -z "$FBOSS_REV" ]]; then
    echo "ERROR: could not parse fboss rev from getdeps/manifests/fboss-thrift-defs" >&2
    exit 1
fi

# Tag carries the rev, so bumping the pin produces a different tag and the
# `docker image inspect` guard below misses -- forcing a rebuild instead of
# silently reusing a base image built from an older fboss.
BASE_IMAGE="fboss-build-env:centos-${FBOSS_REV:0:12}"

# Build the FBOSS base image when it is missing, or unconditionally under
# --rebuild-base-image. The base is also stage 2 of Dockerfile.taac (the shipped
# runtime), so its system packages are part of what we ship: rebuilding
# re-runs `FROM quay.io/centos/centos:stream9` and the base image's own dnf
# installs against live repos, which is how those packages get refreshed.
# Nothing else in this repo pins or refreshes them.
BASE_REASON=""
if [[ "$REBUILD_BASE_IMAGE" -eq 1 ]]; then
    BASE_REASON="--rebuild-base-image requested"
elif ! docker image inspect "$BASE_IMAGE" >/dev/null 2>&1; then
    BASE_REASON="not present locally"
fi

if [[ -n "$BASE_REASON" ]]; then
    echo "Building base image $BASE_IMAGE ($BASE_REASON; slow, ~4 GB)..."
    # Fetch the pinned rev specifically; unlike a bare clone this also
    # re-points an existing checkout when the pin moves.
    if [[ ! -d "$FBOSS_IMAGE_SRC/.git" ]]; then
        echo "Initializing $FBOSS_IMAGE_SRC ..."
        git init -q "$FBOSS_IMAGE_SRC"
    fi
    echo "Fetching fboss $FBOSS_REV (shallow) ..."
    git -C "$FBOSS_IMAGE_SRC" fetch --depth 1 "$FBOSS_PUBLIC_URL" "$FBOSS_REV"
    # -f: this is a managed cache dir, not a working checkout; a
    # stray edit there should not wedge the build.
    git -C "$FBOSS_IMAGE_SRC" checkout -qf FETCH_HEAD
    if [[ -n "${TAAC_FBCODE_DIR:-}" ]]; then
        FBCODE_FBOSS_DOCKER_DIR="$TAAC_FBCODE_DIR/fboss/oss/docker"
        if [[ ! -d "$FBCODE_FBOSS_DOCKER_DIR" ]]; then
            echo "ERROR: missing FBOSS Docker source: $FBCODE_FBOSS_DOCKER_DIR" >&2
            exit 1
        fi
        # The internal CI target watches these files, so its build must exercise
        # their current contents rather than only the pinned public revision.
        cp -a "$FBCODE_FBOSS_DOCKER_DIR/." "$FBOSS_IMAGE_SRC/fboss/oss/docker/"
    fi
    BASE_BUILD_ARGS=()
    if [[ "$REBUILD_BASE_IMAGE" -eq 1 ]]; then
        BASE_BUILD_ARGS+=(--no-cache)
    fi
    # USE_CLANG=false: on CentOS, this makes glog and friends link
    # against system libunwind.so.8 instead of LLVM's libunwind.so.1,
    # which isn't on the runtime search path and breaks auditwheel
    # during fbthrift-python wheel repair.
    docker build "${BASE_BUILD_ARGS[@]}" --build-arg USE_CLANG=false \
        -t "$BASE_IMAGE" \
        -f "$FBOSS_IMAGE_SRC/fboss/oss/docker/Dockerfile" \
        "$FBOSS_IMAGE_SRC"
    echo "Built $BASE_IMAGE"
else
    echo "Using cached base image $BASE_IMAGE"
fi

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
