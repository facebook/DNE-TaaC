"""OSS wrapper for RBB SRv6 TC1 (3-uSID chain + TE_AGENT direct-route lifecycle).

Builds only the TC1 ``test_config`` so the OSS entry point can load it directly
without eagerly constructing unrelated qualification cases:

    python -m taac.runner.oss_entry_point \\
        --test-configs examples/rbb_srv6_3_usids_config.py \\
        --device-info-csv examples/topology/rbb_device_info.csv \\
        --circuit-info-csv examples/topology/rbb_circuit_info.csv \\
        --dut "$TAAC_RBB_R1_HOST" "$TAAC_RBB_R2_HOST"

Bind the lab (hostnames, IXIA chassis) via TAAC_RBB_* and SSH creds via
the OSS runner's ``--secrets-file`` JSON input — nothing is hardcoded.
"""

from taac.testconfigs.routing.factories.qual_rbb.rbb_srv6_test_config import (
    create_rbb_srv6_3_usids_test_config,
)

test_config = create_rbb_srv6_3_usids_test_config()
