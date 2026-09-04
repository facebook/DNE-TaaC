# pyre-unsafe
"""OTG hardening profile: malformed BGP UPDATE handling.

See ``otg_hardening_restarts_test_config.py`` for why the conveyor is split, and
``taac/otg/HARDENING_SETUP.md`` for the DUT side.

Budget — interfaces bind before sessions:

  device group                   addresses   peers
  NO_PACKET_LOSS_EXPECTED_PORT1  v4   (1)    v4  (1)
  NO_PACKET_LOSS_EXPECTED_PORT2  v4   (1)    --  (0)
  MALFORMED_BGP_PORT1            v4   (1)    v4  (1)   enable=False, held down
                                 3 of 4      2 of 4

v4 only, matching the malformations — they are legacy NEXT_HOP / AS_PATH / ORIGIN
violations, i.e. IPv4 BGP.  The port-1 measured peer is what the flap assertion
observes: the claim is that the DUT does not tear down an UNRELATED session over
one peer's malformed input, so such a session has to exist.  Port 2 carries
addressing only.

Two flows: ``NO_PACKET_LOSS_EXPECTED_V4`` over connected routes as a liveness
probe, and ``GOOD_PREFIX_V4`` addressed INTO the prefix port 1 advertises by
NORMAL BGP.  The second is the collateral-damage assertion — loss there means the
DUT let one peer's bad input damage routing learned from another.

This profile has the most headroom of the three, so extend it here if you add
malformations needing their own speaker.
"""

from taac.otg.otg_hardening_builders import (
    build_hardening_test_config,
    COMMUNITY_EDITION_MAX_BGP_SESSIONS,
    COMMUNITY_EDITION_MAX_CP_INTERFACES,
    malformed_peer_prefix,
    MEASURED_DG_INDEX,
)
from taac.otg.otg_hardening_playbooks import (
    create_otg_bgp_malformed_packet_test_playbook,
)
from taac.runner.testbed_topology import ConfigTopology, topology_aware
from taac.test_as_a_config.types import TestConfig


@topology_aware
def test_config(topology: ConfigTopology) -> TestConfig:
    return build_hardening_test_config(
        topology,
        name="OTG_HARDENING_MALFORMED_BGP",
        playbooks=[
            create_otg_bgp_malformed_packet_test_playbook(
                # The playbook toggles this peer DOWN at the end of every
                # iteration, so it is absent from the post snapshot and
                # BGP_SESSION_CHECK would flag it as deleted.  Its own state is
                # not the assertion — UNRELATED sessions surviving is.
                rogue_parent_prefixes_to_ignore=[malformed_peer_prefix(0)],
            )
        ],
        measured_afs_per_port=(("v4",), ("v4",)),
        measured_bgp_afs_per_port=(("v4",), ()),
        malformed_ports=(0,),
        prefix_targeted_flows=(
            # name, af, src port, dst port, dst device group, dst network group
            ("GOOD_PREFIX_V4", "v4", 1, 0, MEASURED_DG_INDEX, 0),
        ),
        max_cp_interfaces=COMMUNITY_EDITION_MAX_CP_INTERFACES,
        max_bgp_sessions=COMMUNITY_EDITION_MAX_BGP_SESSIONS,
    )
