#!/usr/bin/env bash
# Run the OSS RBB SRv6 qualification from adopter-owned local files.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEFAULT_CONFIG_DIR="$REPO_ROOT/.taac"

validate_config_location() {
    local resolved_path="$1"
    case "$resolved_path" in
        "$REPO_ROOT/.taac"|"$REPO_ROOT/.taac/"*)
            ;;
        "$REPO_ROOT"|"$REPO_ROOT/"*)
            echo "Error: an in-repository config directory must be under .taac/" >&2
            echo "Use the default .taac/ directory or a path outside the checkout." >&2
            exit 1
            ;;
    esac
}

print_init_hint() {
    if [[ "$CONFIG_DIR" == "$DEFAULT_CONFIG_DIR" ]]; then
        echo "Initialize it with: ./scripts/run-rbb-srv6.sh --init" >&2
    else
        echo "Initialize it with: ./scripts/run-rbb-srv6.sh --config-dir '$CONFIG_DIR' --init" >&2
    fi
}

usage() {
    cat <<'EOF'
Usage: ./scripts/run-rbb-srv6.sh [OPTIONS] [-- RUNNER_ARGS...]

  no options          Validate the SRv6 device path without reserving IXIA.
  --init              Create a local configuration from the OSS templates.
  --check             Validate inputs in the built image without lab access.
  --config-dir PATH   Use PATH instead of the checkout-local .taac directory.
  --setup-duts        Temporarily bootstrap core ports, OpenR, iBGP, and SRv6.
  --with-traffic      Run the complete SRv6 qualification with live IXIA traffic.
  --setup-dut-edges
                      Temporarily configure the DUT side of selected IXIA links.
  --                  Pass remaining arguments to the OSS TAAC runner.

Examples:
  ./scripts/run-rbb-srv6.sh --init
  ./scripts/run-rbb-srv6.sh --check
  ./scripts/run-rbb-srv6.sh --setup-duts
  ./scripts/run-rbb-srv6.sh --with-traffic
  ./scripts/run-rbb-srv6.sh --setup-duts --with-traffic --setup-dut-edges
  ./scripts/run-rbb-srv6.sh --config-dir /secure/rbb-lab --with-traffic
EOF
}

INIT_ONLY=0
CHECK_ONLY=0
WITH_TRAFFIC=0
CONFIGURE_EDGES=0
SETUP_DUTS=0
CONFIG_DIR="$DEFAULT_CONFIG_DIR"
RUNNER_ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --init)
            INIT_ONLY=1
            shift
            ;;
        --check)
            CHECK_ONLY=1
            shift
            ;;
        --config-dir)
            if [[ $# -lt 2 || -z "${2:-}" ]]; then
                echo "Error: --config-dir requires a path" >&2
                exit 2
            fi
            CONFIG_DIR="$2"
            shift 2
            ;;
        --with-traffic)
            WITH_TRAFFIC=1
            shift
            ;;
        --setup-duts)
            SETUP_DUTS=1
            shift
            ;;
        --setup-dut-edges)
            CONFIGURE_EDGES=1
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        --)
            shift
            RUNNER_ARGS=("$@")
            break
            ;;
        *)
            echo "Error: unknown argument '$1'" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ "$CONFIGURE_EDGES" -eq 1 && "$WITH_TRAFFIC" -ne 1 ]]; then
    echo "Error: --setup-dut-edges requires --with-traffic" >&2
    exit 2
fi
if [[ "$SETUP_DUTS" -eq 1 && "$WITH_TRAFFIC" -eq 1 && \
    "$CONFIGURE_EDGES" -ne 1 ]]; then
    echo "Error: fresh-image traffic requires --setup-dut-edges" >&2
    exit 2
fi
if [[ "$CONFIG_DIR" == *:* ]]; then
    echo "Error: configuration directory cannot contain ':' for a Docker mount" >&2
    exit 1
fi
if [[ "$CHECK_ONLY" -eq 1 && ${#RUNNER_ARGS[@]} -gt 0 ]]; then
    echo "Error: runner arguments after '--' are not used with --check" >&2
    exit 2
fi

if [[ "$INIT_ONLY" -eq 1 ]]; then
    if [[ "$CHECK_ONLY" -eq 1 || "$WITH_TRAFFIC" -eq 1 || \
        "$CONFIGURE_EDGES" -eq 1 || "$SETUP_DUTS" -eq 1 || \
        ${#RUNNER_ARGS[@]} -gt 0 ]]; then
        echo "Error: --init may be combined only with --config-dir" >&2
        exit 2
    fi
    if [[ -e "$CONFIG_DIR" && ! -d "$CONFIG_DIR" ]]; then
        echo "Error: configuration path is not a directory: $CONFIG_DIR" >&2
        exit 1
    fi
    if [[ ! -d "$CONFIG_DIR" ]]; then
        mkdir -p "$CONFIG_DIR"
        chmod 700 "$CONFIG_DIR"
        echo "Created configuration directory: $CONFIG_DIR"
    fi
    CONFIG_DIR="$(cd "$CONFIG_DIR" && pwd -P)"
    validate_config_location "$CONFIG_DIR"

    install_template() {
        local source_path="$1"
        local destination_name="$2"
        local file_mode="$3"
        local destination_path="$CONFIG_DIR/$destination_name"
        if [[ -e "$destination_path" || -L "$destination_path" ]]; then
            echo "Kept existing file: $destination_path"
            return
        fi
        install -m "$file_mode" "$source_path" "$destination_path"
        echo "Created: $destination_path"
    }

    install_template "$REPO_ROOT/examples/topology/rbb_device_info.csv" \
        device_info.csv 644
    install_template "$REPO_ROOT/examples/topology/rbb_circuit_info.csv" \
        circuit_info.csv 644
    install_template "$REPO_ROOT/examples/rbb_srv6_profile.env.example" rbb.env 644
    install_template "$REPO_ROOT/examples/taac_secrets.json.example" secrets.json 600

    echo
    echo "Edit the four files above, then run:"
    if [[ "$CONFIG_DIR" == "$DEFAULT_CONFIG_DIR" ]]; then
        echo "  ./scripts/run-rbb-srv6.sh --check"
    else
        echo "  ./scripts/run-rbb-srv6.sh --config-dir '$CONFIG_DIR' --check"
    fi
    exit 0
fi

if [[ ! -d "$CONFIG_DIR" ]]; then
    echo "Error: configuration directory does not exist: $CONFIG_DIR" >&2
    print_init_hint
    exit 1
fi
LOCAL_DIR="$(cd "$CONFIG_DIR" && pwd -P)"
validate_config_location "$LOCAL_DIR"
if [[ "$LOCAL_DIR" == *:* ]]; then
    echo "Error: resolved configuration directory cannot contain ':'" >&2
    exit 1
fi
for required_file in rbb.env secrets.json device_info.csv circuit_info.csv; do
    if [[ ! -f "$LOCAL_DIR/$required_file" ]]; then
        echo "Error: missing $LOCAL_DIR/$required_file" >&2
        print_init_hint
        exit 1
    fi
done

# CLI mode is authoritative even if the caller's shell contains stale TAAC_*
# values from an earlier run. The Docker helper forwards these variables after
# the profile, so these explicit 0/1 values take precedence.
export TAAC_RBB_INCLUDE_TRAFFIC="$WITH_TRAFFIC"
export TAAC_RBB_EDGE_EBGP="$CONFIGURE_EDGES"
export TAAC_RBB_SETUP_DUTS="$SETUP_DUTS"

if [[ "$CHECK_ONLY" -eq 1 ]]; then
    CHECK_ARGS=(
        python3 -m taac.runner.rbb_preflight
        --config-dir /workspace/.taac
    )
    if [[ "$WITH_TRAFFIC" -eq 1 ]]; then
        CHECK_ARGS+=(--with-traffic)
    fi
    if [[ "$SETUP_DUTS" -eq 1 ]]; then
        CHECK_ARGS+=(--setup-duts)
    fi
    if [[ "$CONFIGURE_EDGES" -eq 1 ]]; then
        CHECK_ARGS+=(--setup-dut-edges)
    fi
    exec "$REPO_ROOT/docker/run_taac_docker.sh" \
        --env-file "$LOCAL_DIR/rbb.env" \
        --volume "$LOCAL_DIR:/workspace/.taac:ro" \
        run "${CHECK_ARGS[@]}"
fi

# The single-quoted program must expand TAAC_* inside the container, not here.
# shellcheck disable=SC2016
exec "$REPO_ROOT/docker/run_taac_docker.sh" \
    --env-file "$LOCAL_DIR/rbb.env" \
    --volume "$LOCAL_DIR:/workspace/.taac:ro" \
    run bash -c '
        set -euo pipefail
        preflight=(
            python3 -m taac.runner.rbb_preflight
            --config-dir /workspace/.taac
        )
        if [[ "${TAAC_RBB_INCLUDE_TRAFFIC:-0}" == "1" ]]; then
            preflight+=(--with-traffic)
        fi
        if [[ "${TAAC_RBB_SETUP_DUTS:-0}" == "1" ]]; then
            preflight+=(--setup-duts)
        fi
        if [[ "${TAAC_RBB_EDGE_EBGP:-0}" == "1" ]]; then
            preflight+=(--setup-dut-edges)
        fi
        "${preflight[@]}"

        runner=(
            python3 -m taac.runner.oss_entry_point
            --test-configs /workspace/examples/rbb_srv6_3_usids_config.py
            --secrets-file /workspace/.taac/secrets.json
            --device-info-csv /workspace/.taac/device_info.csv
            --circuit-info-csv /workspace/.taac/circuit_info.csv
            --dut "$TAAC_RBB_R1_HOST" "$TAAC_RBB_R2_HOST"
            --playbook bgp_rbb_srv6_3_usids
        )
        if [[ "${TAAC_RBB_INCLUDE_TRAFFIC:-0}" == "1" ]]; then
            : "${TAAC_IXIA_API_SERVER:?Set TAAC_IXIA_API_SERVER in .taac/rbb.env}"
            runner+=(--ixia-api-server "$TAAC_IXIA_API_SERVER")
        fi
        exec "${runner[@]}" "$@"
    ' _ "${RUNNER_ARGS[@]}"
