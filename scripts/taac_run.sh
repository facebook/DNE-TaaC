#!/bin/bash
# Short wrapper around the OSS TAAC boilerplate invocation.
#
# Usage:
#   ./scripts/taac_run.sh <dut> [playbook ...] [oss_entry_point flags ...]
#
# Examples:
#   ./scripts/taac_run.sh <dut> test_snake_agent_coldboot
#   ./scripts/taac_run.sh <dut> test_snake_warmboot --ixia-session-id 58 --skip-ixia-cleanup
#   ./scripts/taac_run.sh <dut> --list-tests
#
# The first positional argument is the DUT. Following bare words (not
# starting with '-') are playbooks. Everything from the first '-'-prefixed
# argument onward is passed through verbatim to taac.runner.oss_entry_point.
#
# Defaults (only added when the corresponding flag is absent from the
# pass-through arguments):
#   --test-configs     $TAAC_TEST_CONFIG      (default: OSS snake config)
#   --ixia-api-server  $TAAC_IXIA_API_SERVER  (required unless passed)
#   --circuit-info-csv /workspace/taac/oss_topology_info/circuit_info.csv
#   --device-info-csv  /workspace/taac/oss_topology_info/device_info.csv
#
# TAAC_SSH_USER / TAAC_SSH_PASSWORD default to root/root when unset; export
# them (e.g. via ~/.taac-secrets) to override. See docker/README.md.
# TAAC_ITERATION defaults to 2 (snake triage); unset/override for full runs.

set -euo pipefail

usage() {
    grep '^#' "$0" | sed -n '2,15p' | sed 's/^# \{0,1\}//' >&2
    exit 1
}

[[ $# -ge 1 ]] || usage
case "$1" in -*|-h|--help) usage ;; esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

DUT="$1"
shift

PLAYBOOKS=()
while [[ $# -gt 0 && "$1" != -* ]]; do
    PLAYBOOKS+=("$1")
    shift
done
PASSTHROUGH=("$@")

has_flag() {
    local flag="$1" arg
    for arg in "${PASSTHROUGH[@]}"; do
        [[ "$arg" == "$flag" || "$arg" == "$flag"=* ]] && return 0
    done
    return 1
}

CMD=(python3 -m taac.runner.oss_entry_point --dut "$DUT")
[[ ${#PLAYBOOKS[@]} -gt 0 ]] && CMD+=(--playbook "${PLAYBOOKS[@]}")

has_flag --test-configs \
    || CMD+=(--test-configs "${TAAC_TEST_CONFIG:-/workspace/taac/testconfigs/oss/snake_config.py}")
has_flag --ixia-api-server \
    || CMD+=(--ixia-api-server "${TAAC_IXIA_API_SERVER:?set TAAC_IXIA_API_SERVER}")
has_flag --circuit-info-csv \
    || CMD+=(--circuit-info-csv /workspace/taac/oss_topology_info/circuit_info.csv)
has_flag --device-info-csv \
    || CMD+=(--device-info-csv /workspace/taac/oss_topology_info/device_info.csv)

CMD+=("${PASSTHROUGH[@]}")

export TAAC_OSS=1
export TAAC_SSH_USER="${TAAC_SSH_USER:-root}"
export TAAC_SSH_PASSWORD="${TAAC_SSH_PASSWORD:-root}"
# Triage default for configs that read TAAC_ITERATION (today: oss snake).
export TAAC_ITERATION="${TAAC_ITERATION:-2}"

echo "TAAC_OSS=1 TAAC_ITERATION=${TAAC_ITERATION} TAAC_SSH_USER=${TAAC_SSH_USER} TAAC_SSH_PASSWORD=<redacted> \\" >&2
echo "  ${REPO_ROOT}/docker/run_taac_docker.sh run ${CMD[*]}" >&2

exec "${REPO_ROOT}/docker/run_taac_docker.sh" run "${CMD[@]}"
