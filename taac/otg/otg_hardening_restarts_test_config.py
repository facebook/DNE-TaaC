# pyre-unsafe
"""OTG hardening profile: process restarts + CPU-queue overload.

ixia-c community edition caps control-plane interfaces and sessions at 4 each,
and the full hardening set needs far more — it is rejected with an opaque HTTP 500
at set_config.  So the conveyor ships as three profiles sharing the builders in
``taac/otg/otg_hardening_builders.py``, each independently runnable:

  otg_hardening_restarts_test_config.py    4 interfaces / 4 sessions  <- this file
  otg_hardening_ecmp_test_config.py        4 / 2
  otg_hardening_malformed_test_config.py   3 / 2

Budget here is full on both counts:

  device group                   addresses      peers
  NO_PACKET_LOSS_EXPECTED_PORT1  v4 + v6 (2)    v4 + v6 (2)
  NO_PACKET_LOSS_EXPECTED_PORT2  v4 + v6 (2)    v4 + v6 (2)
                                 4 of 4         4 of 4

This is the only profile that can afford a dual-stack measured path, and the right
place to spend it — these playbooks' assertions lean most on BGP convergence, and
none of them needs an ECMP or malformed speaker.

Playbooks: test_agent_warmboot, test_bgpd_restart, test_qsfp_service_restart,
test_fsdb_restart, test_cpu_high_priority_queue_overload.

DUT side: ``taac/otg/HARDENING_SETUP.md``.
"""

from taac.otg.otg_hardening_builders import (
    build_hardening_test_config,
    COMMUNITY_EDITION_MAX_BGP_SESSIONS,
    COMMUNITY_EDITION_MAX_CP_INTERFACES,
)
from taac.otg.otg_hardening_playbooks import (
    create_otg_agent_warmboot_playbook,
    create_otg_bgpd_restart_playbook,
    create_otg_cpu_high_priority_queue_overload_playbook,
    create_otg_fsdb_restart_playbook,
    create_otg_qsfp_service_restart_playbook,
)
from taac.runner.testbed_topology import ConfigTopology, topology_aware
from taac.test_as_a_config.types import TestConfig

PROCESS_RESTART_ITERATIONS = 5

# systemd units SERVICE_RESTART_CHECK asserts stayed ACTIVE while the target
# restarted.  None means DEFAULT_MONITORED_SERVICES (fboss_sw_agent, bgpd, fsdb,
# qsfp_service) minus whichever unit each playbook restarts.  Set your DUT's real
# units if they differ — an absent or disabled unit fails the check with
# "Services not in ACTIVE state: <name> (status: INACTIVE)".
MONITORED_SERVICES = None


@topology_aware
def test_config(topology: ConfigTopology) -> TestConfig:
    restart_playbooks = [
        factory(
            iteration=PROCESS_RESTART_ITERATIONS,
            monitored_services=MONITORED_SERVICES,
        )
        for factory in (
            create_otg_agent_warmboot_playbook,
            create_otg_bgpd_restart_playbook,
            create_otg_qsfp_service_restart_playbook,
            create_otg_fsdb_restart_playbook,
        )
    ]
    return build_hardening_test_config(
        topology,
        name="OTG_HARDENING_RESTARTS",
        playbooks=[
            *restart_playbooks,
            create_otg_cpu_high_priority_queue_overload_playbook(),
        ],
        measured_afs_per_port=(("v4", "v6"), ("v4", "v6")),
        measured_bgp_afs_per_port=(("v4", "v6"), ("v4", "v6")),
        include_cp_flow=True,
        max_cp_interfaces=COMMUNITY_EDITION_MAX_CP_INTERFACES,
        max_bgp_sessions=COMMUNITY_EDITION_MAX_BGP_SESSIONS,
    )
