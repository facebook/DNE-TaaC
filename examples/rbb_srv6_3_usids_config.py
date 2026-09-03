"""OSS wrapper for RBB SRv6 TC1 (3-uSID chain + TE_AGENT direct-route lifecycle).

Exposes the ``qual_rbb`` lifecycle constant as ``test_config`` so the OSS entry
point can load it directly:

    python -m taac.runner.oss_entry_point \\
        --test-configs examples/rbb_srv6_3_usids_config.py \\
        --device-info-csv examples/topology/rbb_device_info.csv \\
        --circuit-info-csv examples/topology/rbb_circuit_info.csv \\
        --dut "$TAAC_RBB_R1_HOST" "$TAAC_RBB_R2_HOST"

Bind the lab (hostnames, IXIA chassis) via TAAC_RBB_* and SSH creds via
TAAC_SSH_USER / TAAC_SSH_PASSWORD (or ~/.taac-secrets) — nothing hardcoded.
"""

from taac.testconfigs.routing.qual_rbb import RBB_SRV6_3_USIDS_TEST_CONFIG

test_config = RBB_SRV6_3_USIDS_TEST_CONFIG
