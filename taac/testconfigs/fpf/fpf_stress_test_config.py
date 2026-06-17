#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""FPF BGP Prefix Stress Test — TC1: Stable State Validation (comprehensive run).

Full collector-validation + generic-health-check configuration. Five long-lived
collectors run continuously and are each validated by exactly one postcheck, and
the generic SSH/device-shell checks run as both pre- and post-checks.

  Collector              ->  Validating health check
  ---------------------      --------------------------------------------
  fsdb (ribMap)          ->  create_fpf_fsdb_ribmap_convergence_check
  bgp  (RIB)             ->  create_fpf_bgp_rib_convergence_check
  hrt  (bulk)            ->  create_fpf_hrt_bulk_convergence_check
  hrt_remote_failure     ->  create_fpf_hrt_remote_failure_convergence_check
  prod_hrt_prefix        ->  create_fpf_prod_hrt_prefix_stability_check
  (ODS) HRT sys memory   ->  create_fpf_hrt_system_memory_check
  (ODS) HRT driver conn  ->  create_fpf_hrt_driver_disconnect_check

Generic SSH/device-shell checks ENABLED (skip_ssh_dependent_checks=False):
systemctl active-state, unclean-exit, (device) core dumps, port state, BGP
session establish, BGP RIB/FIB consistency, memory/CPU utilization, HRT FSDB
session, the ODS discard/congestion counters, and the core-dumps snapshot. This
requires device SSH access to the GTSW/STSW DUTs. RDMA data-plane traffic
(ib_write_bw) is brought up + ODS-validated as a setup task before collectors.

Scale is intentionally tiny (1,000 injected prefixes) for a fast run. Prefix
injection and the collectors use BGP++/HRT/FSDB thrift. The stabilization (bake)
window is kept at 5 min — do not shrink further.

Usage:
  buck2 run neteng/netcastle:netcastle_taac -- \\
    --team taac --test-config fpf_stress_test_config \\
    --dev --skip-basset-reservation --skip-testbed-isolation \\
    --debug --continue-on-precheck-failure --skip-fboss-rsyslog
"""

from taac.libs.fpf.fpf_prod_prefix_map import get_prefix
from taac.playbooks.playbook_definitions import (
    create_fpf_hardening_playbook_v2,
)
from taac.task_definitions import (
    create_fpf_start_collectors_task,
    create_fpf_start_ib_traffic_task,
    create_fpf_stop_collectors_task,
    create_fpf_stop_ib_traffic_task,
)
from taac.testconfigs.fpf.fpf_hardening_common import (
    create_fpf_endpoints,
    DEFAULT_COMMUNITY_LIST,
    DEFAULT_SUBNET_PREFIX,
    FSDB_COLLECTOR_MODE,
    GPU_HOSTS,
    OBSERVER_GTSWS,
    skip_ssh_dependencies,
    TRIGGER_STSWS,
)
from taac.test_as_a_config.types import TestConfig

# Tiny scale for a fast minimal run.
PREFIX_COUNT = 1000
# Bake/stability window — keep at 5 min (do not reduce below).
STABILIZATION_DELAY_SEC = 300

# Production VF prefix monitored by the fifth (prod_hrt_prefix) collector and
# validated by FpfProdHrtPrefixStabilityHealthCheck. Steady-state production
# reachability exists independent of the injected stress prefixes. The prefix is
# resolved from the single source-of-truth host->device->prefix map
# (libs/fpf/fpf_prod_prefix_map.py) — never hardcode the prefix string here.
PROD_PREFIX_HOST = GPU_HOSTS[0]
PROD_PREFIX_DEVICE_ID = 0
PROD_PREFIXES = [get_prefix(PROD_PREFIX_HOST, PROD_PREFIX_DEVICE_ID)]

# RTP test hosts whose HRT service is asserted via ODS (distinct from
# GPU_HOSTS): system memory (<= 8 GiB max) by FpfHrtSystemMemoryHealthCheck and
# driver connectivity (hrt.driver.created == 1) by
# FpfHrtDriverDisconnectHealthCheck.
HRT_MEMORY_HOSTS = ["rtptest1555.mwg2", "rtptest1575.mwg2"]

# RDMA data-plane traffic: ib_write_bw between a pair of GPU hosts. Started as a
# setup task (before collectors, so baseline already sees load) and validated
# in-task via ODS beth tx egress (>10 Gbps/host); torn down in teardown.
IB_TRAFFIC_SERVER = GPU_HOSTS[0]
IB_TRAFFIC_CLIENTS = [GPU_HOSTS[1]]

# Hosts whose per-lane RDMA egress fairness (beth0-3) is asserted by
# FpfHostSprayHealthCheck — the ib_write_bw traffic pair.
SPRAY_HOSTS = [IB_TRAFFIC_SERVER, *IB_TRAFFIC_CLIENTS]


def create_fpf_stress_test_config() -> TestConfig:
    # When SSH dependencies are skipped (e.g. headless/agent run without a
    # Kerberos/SSH cert), drop the ib_write_bw traffic task (it SSHes to the RTP
    # hosts) and the host-spray check (which needs that traffic), and skip the
    # generic device-shell SSH checks — leaving the thrift/ODS collector +
    # convergence/stability checks, which run end-to-end without an SSH cert.
    skip_ssh = skip_ssh_dependencies()

    playbook = create_fpf_hardening_playbook_v2(
        gtsws=OBSERVER_GTSWS,
        hosts=GPU_HOSTS,
        trigger_stsws=TRIGGER_STSWS,
        soak_duration_sec=0,
        stabilization_delay_sec=STABILIZATION_DELAY_SEC,
        prefix_count=PREFIX_COUNT,
        community_list=DEFAULT_COMMUNITY_LIST,
        playbook_name="fpf_stable_state",
        prod_prefixes=PROD_PREFIXES,
        skip_ssh_dependent_checks=skip_ssh,
        hrt_memory_hosts=HRT_MEMORY_HOSTS,
        hrt_driver_hosts=HRT_MEMORY_HOSTS,
        spray_hosts=None if skip_ssh else SPRAY_HOSTS,
    )

    setup_tasks = []
    teardown_tasks = []
    if not skip_ssh:
        # Bring up + validate RDMA traffic first, so the collectors' baseline
        # window already sees data-plane load.
        setup_tasks.append(
            create_fpf_start_ib_traffic_task(
                server=IB_TRAFFIC_SERVER,
                clients=IB_TRAFFIC_CLIENTS,
            )
        )
        teardown_tasks.append(
            create_fpf_stop_ib_traffic_task(
                server=IB_TRAFFIC_SERVER,
                clients=IB_TRAFFIC_CLIENTS,
            )
        )
    setup_tasks.append(
        create_fpf_start_collectors_task(
            gtsws=OBSERVER_GTSWS,
            hosts=GPU_HOSTS,
            subnet_prefix=DEFAULT_SUBNET_PREFIX,
            prod_prefixes=PROD_PREFIXES,
            prod_prefix_host=PROD_PREFIX_HOST,
            prod_prefix_device_id=PROD_PREFIX_DEVICE_ID,
            fsdb_mode=FSDB_COLLECTOR_MODE,
        )
    )
    teardown_tasks.append(
        create_fpf_stop_collectors_task(
            trigger_stsws=TRIGGER_STSWS,
            prefix_count=PREFIX_COUNT,
            community_list=DEFAULT_COMMUNITY_LIST,
        )
    )

    return TestConfig(
        name="fpf_stress_test_config",
        endpoints=create_fpf_endpoints(),
        setup_tasks=setup_tasks,
        teardown_tasks=teardown_tasks,
        playbooks=[playbook],
    )


TEST_CONFIG = create_fpf_stress_test_config()
