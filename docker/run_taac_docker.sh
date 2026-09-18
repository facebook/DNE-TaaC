#!/bin/bash
# Run commands or an interactive shell inside the TAAC container.
#
# The repo (or --workspace path) is always bind-mounted at /workspace and
# used as the working directory, so local edits override the baked-in
# /taac source. PYTHONPATH is set so `import taac.*` resolves from the
# workspace. Use --regen to regenerate thrift bindings on entry.
#
# Usage:
#   ./docker/run_taac_docker.sh                          # interactive shell
#   ./docker/run_taac_docker.sh --regen                  # regen thrift, then shell
#   ./docker/run_taac_docker.sh --image <image>          # use a specific image
#   ./docker/run_taac_docker.sh --workspace <path>       # mount a different directory
#   ./docker/run_taac_docker.sh --env-file <path>        # load KEY=value settings (repeatable)
#   ./docker/run_taac_docker.sh -v /host:/ctr            # extra volume mount (repeatable)
#   ./docker/run_taac_docker.sh run <cmd>                # run a command (non-interactive)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

IMAGE="fboss-taac"
WORKSPACE="$REPO_ROOT"
REGEN=0
SUBCMD=shell
EXTRA_VOLUMES=()
ENV_FILES=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --regen)
            REGEN=1
            shift
            ;;
        --image)
            if [[ $# -lt 2 || -z "${2:-}" ]]; then
                echo "Error: --image requires a value" >&2
                exit 1
            fi
            IMAGE="$2"
            shift 2
            ;;
        --workspace)
            if [[ $# -lt 2 || -z "${2:-}" ]]; then
                echo "Error: --workspace requires a value" >&2
                exit 1
            fi
            WORKSPACE="$(cd "$2" && pwd)"
            shift 2
            ;;
        --env-file)
            if [[ $# -lt 2 || -z "${2:-}" ]]; then
                echo "Error: --env-file requires a value" >&2
                exit 1
            fi
            if [[ ! -f "$2" ]]; then
                echo "Error: env file '$2' does not exist or is not a regular file" >&2
                exit 1
            fi
            ENV_FILES+=("$2")
            shift 2
            ;;
        -v|--volume)
            if [[ $# -lt 2 || -z "${2:-}" ]]; then
                echo "Error: -v/--volume requires a value" >&2
                exit 1
            fi
            EXTRA_VOLUMES+=(-v "$2")
            shift 2
            ;;
        run)
            SUBCMD=run
            shift
            break
            ;;
        *)
            echo "Usage: $0 [--regen] [--image <name>] [--workspace <path>] [--env-file <path>] [-v <mount>] [run <cmd...>]" >&2
            exit 1
            ;;
    esac
done

if ! docker image inspect "$IMAGE" &>/dev/null; then
    echo "Error: Docker image '$IMAGE' not found locally." >&2
    echo "Build it first or specify a valid image with --image." >&2
    exit 1
fi

DOCKER_ARGS=(
    --rm -i --network host
    -v "$WORKSPACE":/workspace
    -v /tmp:/tmp
    "${EXTRA_VOLUMES[@]}"
)

# Let Docker parse non-secret profile files so values are data, not shell code.
# Multiple files are applied in command-line order. Explicitly exported TAAC_*
# variables are appended below with `-e` and therefore remain the
# highest-precedence, one-run override. The OSS runner accepts credentials via
# its separate --secrets-file input.
for _taac_env_file in "${ENV_FILES[@]}"; do
    DOCKER_ARGS+=(--env-file "$_taac_env_file")
done
if [[ "$SUBCMD" != "run" ]]; then
    DOCKER_ARGS+=(-t)
fi

# Auto-forward TAAC_* env vars (TAAC_OSS, TAAC_SSH_USER, TAAC_SSH_PASSWORD,
# TAAC_DEVICE_INFO_PATH, etc.) so callers can `export TAAC_FOO=bar` on the
# host and have it visible in the container — keeps secrets like
# TAAC_SSH_PASSWORD out of `bash -c '...'` strings + shell history.
while IFS= read -r _taac_var; do
    DOCKER_ARGS+=(-e "$_taac_var")
done < <(env | grep '^TAAC_' | cut -d= -f1)

if [[ "$REGEN" -eq 1 ]]; then
    INIT='taac-regen-thrift --quiet /workspace/taac/thrift /tmp/regen && export PYTHONPATH=/workspace:/tmp/regen/gen-python:$PYTHONPATH && cd /workspace'
else
    INIT='export PYTHONPATH=/workspace:$PYTHONPATH && cd /workspace'
fi

echo "Using image: $IMAGE" >&2

if [[ "$SUBCMD" = "run" ]]; then
    # Hybrid quoting so command args survive intact: INIT expands at
    # the outer shell (its body uses single-quoted '$PYTHONPATH' to
    # defer to the inner bash); 'exec "$@"' stays literal and is
    # resolved by the inner bash from the positional args we append.
    exec docker run "${DOCKER_ARGS[@]}" "$IMAGE" \
        bash -c "$INIT"' && exec "$@"' _ "$@"
else
    exec docker run "${DOCKER_ARGS[@]}" "$IMAGE" bash -c "$INIT && exec bash"
fi
