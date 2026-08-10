# pyre-unsafe
"""OTG hardening profile: ECMP group and member overload.

See ``otg_hardening_restarts_test_config.py`` for why the conveyor is split, and
``taac/otg/HARDENING_SETUP.md`` for the DUT side.

Budget — interfaces bind before sessions:

  device group                   addresses   peers
  NO_PACKET_LOSS_EXPECTED_PORT1  v6   (1)    --  (0)
  NO_PACKET_LOSS_EXPECTED_PORT2  v6   (1)    --  (0)
  ECMP_1_PORT1                   v6   (1)    v6  (1)
  ECMP_2_PORT1                   v6   (1)    v6  (1)   enable=False, held down
                                 4 of 4      2 of 4

All v6, because the ECMP aggregate is v6 and traffic exercising it must match.
The measured groups need addresses only — they source traffic and give the DUT a
connected route back, neither of which needs peering.  ECMP is on port 1 alone;
both ports would cost 4 interfaces by themselves.

``enable=False`` on ECMP_2 is honoured: it is built but held down at setup, so each
playbook's toggle-up genuinely adds its next-hops to the shared aggregate while the
test is watching.  What remains bounded is the *size* of that step —
``ecmp_multipliers`` is pinned to (1, 1) by the licence, so the aggregate goes from
1 to 2 next-hops.  That exercises path selection, not a platform limit.  See the
known gaps in ``HARDENING_SETUP.md``.

Two flows: ``NO_PACKET_LOSS_EXPECTED_V6`` over connected routes as a liveness
probe, and ``ECMP_FORWARDING_V6`` addressed INTO the aggregate so the DUT must
resolve it through the multipath BGP route.  The second is what upstream gets from
its ``_DIRECTIONAL_`` items; without it nothing addresses the ECMP-routed
prefixes, leaving wrong next-hop selection invisible.

``ECMP_FORWARDING_V6`` sweeps its destination across the aggregate rather than
using one address, so the DUT's hash distributes it over the available next-hops;
a single src/dst pair would pin every frame to one member and prove only that one
path resolves.  With ``ecmp_multipliers`` at (1, 1) there are just two next-hops
to distribute over, so this shows selection works, not that it holds up at scale.
"""

from taac.otg.otg_hardening_builders import (
    build_hardening_test_config,
    COMMUNITY_EDITION_MAX_BGP_SESSIONS,
    COMMUNITY_EDITION_MAX_CP_INTERFACES,
    ECMP_1_DG_INDEX,
)
from taac.otg.otg_hardening_playbooks import (
    create_otg_ecmp_group_overload_limit_playbook,
    create_otg_ecmp_member_overload_limit_playbook,
)
from taac.runner.testbed_topology import ConfigTopology, topology_aware
from taac.test_as_a_config.types import TestConfig

# Simulated devices per ECMP group.  Each is one peer advertising the shared
# aggregate, so it contributes one next-hop per prefix; members are
# prefix_count x total next-hops.
#
# (1, 1) is all the budget above allows, so ECMP_2 coming up adds ONE next-hop —
# enough to exercise path selection, not enough to approach a platform limit.
ECMP_MULTIPLIERS = (1, 1)

# For a licensed deployment: 500 prefixes x (8 + 24) next-hops = 16000 members
# once ECMP_2 is up, versus 4000 before, with group count flat at 500.  That
# separation is what distinguishes the member test from the group test.  Costs 34
# interfaces.
LICENSED_ECMP_MULTIPLIERS = (8, 24)


@topology_aware
def test_config(topology: ConfigTopology) -> TestConfig:
    return build_hardening_test_config(
        topology,
        name="OTG_HARDENING_ECMP",
        playbooks=[
            create_otg_ecmp_group_overload_limit_playbook(),
            create_otg_ecmp_member_overload_limit_playbook(),
        ],
        measured_afs_per_port=(("v6",), ("v6",)),
        measured_bgp_afs_per_port=((), ()),
        ecmp_ports=(0,),
        ecmp_multipliers=ECMP_MULTIPLIERS,
        prefix_targeted_flows=(
            # name, af, src port, dst port, dst device group, dst network group
            ("ECMP_FORWARDING_V6", "v6", 1, 0, ECMP_1_DG_INDEX, 0),
        ),
        max_cp_interfaces=COMMUNITY_EDITION_MAX_CP_INTERFACES,
        max_bgp_sessions=COMMUNITY_EDITION_MAX_BGP_SESSIONS,
    )
