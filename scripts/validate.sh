#!/usr/bin/env bash
set -euo pipefail

IMAGE="${TAAC_TEST_IMAGE:-fboss-taac}"

usage() {
    echo "Usage: $0 [--build | --pull] [--image IMAGE] [--no-cache] [--num-jobs N]"
    echo "          [--skip-tests] [--skip-smoke] [--regen-thrift] [--dry-run]"
    echo "          [-- PYTEST_ARGS...]"
    echo ""
    echo "Build (or pull) a TAAC image and run its tests. With no arguments, builds"
    echo "the image locally and runs the full unit test + smoke suite."
    echo ""
    echo "Options:"
    echo "  --build           Build the image locally (default)"
    echo "  --pull            Pull the image instead of building it"
    echo "  --image IMAGE     Image to build or pull (default: \$TAAC_TEST_IMAGE or fboss-taac)"
    echo "  --no-cache        Build without Docker layer cache (--build only)"
    echo "  --num-jobs N      Cap build parallelism (--build only)"
    echo "  --skip-tests      Acquire the image but do not test it"
    echo "  --skip-smoke      Skip the dry-run smoke test"
    echo "  --regen-thrift    Regenerate thrift bindings before running tests"
    echo "  --dry-run         Print the commands that would run, without running them"
    echo ""
    echo "Everything after '--' is forwarded to pytest."
    echo ""
    echo "Examples:"
    echo "  $0                                         # build, then test everything"
    echo "  $0 --skip-smoke                            # build, unit tests only"
    echo "  $0 --pull --image ghcr.io/org/taac:latest  # test a prebuilt image"
    echo "  $0 -- -k retry                             # build, run a test subset"
    exit 1
}

MODE=""
SKIP_TESTS=0
DRY_RUN=0
BUILD_ARGS=()
TEST_ARGS=()
PYTEST_ARGS=()

set_mode() {
    if [[ -n "$MODE" && "$MODE" != "$1" ]]; then
        echo "Error: --build and --pull are mutually exclusive" >&2
        exit 2
    fi
    MODE="$1"
}

require_value() {
    if [[ $2 -lt 2 || -z "${3:-}" ]]; then
        echo "Error: $1 requires a value" >&2
        exit 1
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --build)
            set_mode build
            shift
            ;;
        --pull)
            set_mode pull
            shift
            ;;
        --image)
            require_value --image $# "${2:-}"
            IMAGE="$2"
            shift 2
            ;;
        --no-cache)
            BUILD_ARGS+=(--no-cache)
            shift
            ;;
        --num-jobs)
            require_value --num-jobs $# "${2:-}"
            BUILD_ARGS+=(--num-jobs "$2")
            shift 2
            ;;
        --skip-tests)
            SKIP_TESTS=1
            shift
            ;;
        --skip-smoke)
            TEST_ARGS+=(--skip-smoke)
            shift
            ;;
        --regen-thrift)
            TEST_ARGS+=(--regen-thrift)
            shift
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        --help|-h)
            usage
            ;;
        --)
            shift
            PYTEST_ARGS=("$@")
            break
            ;;
        *)
            echo "Error: unknown option $1" >&2
            usage
            ;;
    esac
done

# Default to building; --pull is the opt-in.
MODE="${MODE:-build}"

if [[ "$MODE" == "pull" && ${#BUILD_ARGS[@]} -gt 0 ]]; then
    echo "Error: ${BUILD_ARGS[0]} is only valid with --build" >&2
    exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Echo every command so --dry-run output is the real command line, not a summary.
run() {
    echo "+ $*"
    if [[ "$DRY_RUN" -eq 0 ]]; then
        "$@"
    fi
}

if [[ "$MODE" == "build" ]]; then
    echo "==> Building image: $IMAGE"
    build_invocation=(--tag "$IMAGE")
    if [[ ${#BUILD_ARGS[@]} -gt 0 ]]; then
        build_invocation+=("${BUILD_ARGS[@]}")
    fi
    run "$REPO_ROOT/docker/build-taac-image.sh" "${build_invocation[@]}"
else
    echo "==> Pulling image: $IMAGE"
    run docker pull "$IMAGE"
fi

if [[ "$SKIP_TESTS" -eq 1 ]]; then
    echo "==> Skipping tests (--skip-tests)"
    exit 0
fi

echo ""
echo "==> Validating image: $IMAGE"
test_invocation=(--image "$IMAGE")
if [[ ${#TEST_ARGS[@]} -gt 0 ]]; then
    test_invocation+=("${TEST_ARGS[@]}")
fi
if [[ ${#PYTEST_ARGS[@]} -gt 0 ]]; then
    test_invocation+=(-- "${PYTEST_ARGS[@]}")
fi
run "$REPO_ROOT/scripts/run_tests.sh" "${test_invocation[@]}"

echo ""
echo "Validation passed"
