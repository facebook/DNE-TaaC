#!/bin/bash
# Make sure the revision-tagged FBOSS base image exists, building it if needed,
# and print its tag on stdout. Everything else goes to stderr.
#
# Usage:
#   ./docker/ensure-base-image.sh             # reuse the local image if present
#   ./docker/ensure-base-image.sh --rebuild   # rebuild without layer cache
#
# Env overrides:
#   FBOSS_IMAGE_SRC   Where to clone/find facebook/fboss for the base image
#                     build context (default: ~/.taac-fboss-image-src)
#   TAAC_FBCODE_DIR   Internal fbcode checkout whose current FBOSS Docker files
#                     should be validated instead of the pinned public copies

set -euo pipefail

REBUILD_BASE_IMAGE=0
case "${1:-}" in
    "") ;;
    --rebuild) REBUILD_BASE_IMAGE=1 ;;
    *)
        echo "Usage: $0 [--rebuild]" >&2
        exit 1
        ;;
esac

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
# --rebuild. The base is also stage 2 of Dockerfile.taac (the shipped
# runtime), so its system packages are part of what we ship: rebuilding
# re-runs `FROM quay.io/centos/centos:stream9` and the base image's own dnf
# installs against live repos, which is how those packages get refreshed.
# Nothing else in this repo pins or refreshes them.
BASE_REASON=""
if [[ "$REBUILD_BASE_IMAGE" -eq 1 ]]; then
    BASE_REASON="rebuild requested"
elif ! docker image inspect "$BASE_IMAGE" >/dev/null 2>&1; then
    BASE_REASON="not present locally"
fi

if [[ -n "$BASE_REASON" ]]; then
    echo "Building base image $BASE_IMAGE ($BASE_REASON; slow, ~4 GB)..." >&2
    # Fetch the pinned rev specifically; unlike a bare clone this also
    # re-points an existing checkout when the pin moves.
    if [[ ! -d "$FBOSS_IMAGE_SRC/.git" ]]; then
        echo "Initializing $FBOSS_IMAGE_SRC ..." >&2
        git init -q "$FBOSS_IMAGE_SRC"
    fi
    echo "Fetching fboss $FBOSS_REV (shallow) ..." >&2
    git -C "$FBOSS_IMAGE_SRC" fetch --depth 1 "$FBOSS_PUBLIC_URL" "$FBOSS_REV" >&2
    # -f: this is a managed cache dir, not a working checkout; a
    # stray edit there should not wedge the build.
    git -C "$FBOSS_IMAGE_SRC" checkout -qf FETCH_HEAD >&2
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
        "$FBOSS_IMAGE_SRC" >&2
    echo "Built $BASE_IMAGE" >&2
else
    echo "Using cached base image $BASE_IMAGE" >&2
fi

echo "$BASE_IMAGE"
