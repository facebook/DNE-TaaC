#!/bin/bash

set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <tictaac-binary>" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BINARY="$(realpath "$1")"
SETUP_ONLY_CONFIG="$SCRIPT_DIR/smoke/setup_only_config.json"
EXPECTED_SUMMARY="oss_smoke_setup_only: ran 0 playbook(s) on 0 DUT(s) ()"
UNREACHABLE_DUT_CONFIG="$SCRIPT_DIR/smoke/unreachable_dut_config.json"
UNREACHABLE_DEVICE_INFO="$SCRIPT_DIR/smoke/unreachable_device_info.csv"
INFRA_FAILURE_EXIT_CODE=128

run_isolated() {
    env -i HOME="$sandbox" PATH=/usr/bin:/bin TMPDIR="$sandbox" "$BINARY" "$@"
}

sandbox=
rc=
for sig in 1 2 3 13 15; do eval "trap 'exit $((sig + 128))' $sig"; done
trap 'rc=$?; set +e; rm -rf "$sandbox"; exit $rc' EXIT
sandbox="$(mktemp -d)"

run_isolated --version > "$sandbox/version.json"
grep -q '"program": "tictaac"' "$sandbox/version.json"
echo "PASS: --version"

run_isolated run --test-config-json "$SETUP_ONLY_CONFIG" --setup-only \
    --skip-ixia-setup --skip-testbed-isolation --skip-fboss-rsyslog \
    --skip-package-update > "$sandbox/setup_only.out" 2> "$sandbox/setup_only.err"
if ! grep -qxF "$EXPECTED_SUMMARY" "$sandbox/setup_only.out"; then
    echo "FAIL: setup-only run did not print '$EXPECTED_SUMMARY'" >&2
    tail -20 "$sandbox/setup_only.err" >&2
    exit 1
fi
echo "PASS: setup-only run"

echo '{not json' > "$sandbox/invalid.json"
invalid_rc=0
run_isolated run --test-config-json "$sandbox/invalid.json" > /dev/null 2>&1 || invalid_rc=$?
if [[ "$invalid_rc" -ne 1 ]]; then
    echo "FAIL: invalid config exited $invalid_rc, expected 1" >&2
    exit 1
fi
echo "PASS: invalid config rejected"

infra_rc=0
run_isolated run --test-config-json "$UNREACHABLE_DUT_CONFIG" \
    --device-info-csv "$UNREACHABLE_DEVICE_INFO" \
    --skip-ixia-setup --skip-testbed-isolation --skip-fboss-rsyslog \
    --skip-package-update > /dev/null 2>&1 || infra_rc=$?
if [[ "$infra_rc" -ne "$INFRA_FAILURE_EXIT_CODE" ]]; then
    echo "FAIL: unreachable DUT exited $infra_rc, expected $INFRA_FAILURE_EXIT_CODE" >&2
    exit 1
fi
echo "PASS: infra failure exits $INFRA_FAILURE_EXIT_CODE"
