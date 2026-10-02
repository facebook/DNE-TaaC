# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""Wedge800 (W800) NPI snake TestConfigs.

Single-DUT loopback qualification for the W800 NPI program, covering all
eight snake testbeds in ash6 (suite 12, row O, rack 14) -- four
WEDGE800CACT (Cisco/Leaba GRAPHENE202X) and four WEDGE800BACT
(Broadcom), one of each at 100G, 200G, 400G and 800G.

Every bed is cabled as ONE continuous serpentine rather than the
per-subport chains the Minipack3/Kodiak3 snakes use, so each config
declares a single ``SnakeConfig`` instead of two. The chain shape
differs only by speed:

* 100G/200G/400G -- ``eth1/N/5`` is jumpered to ``eth1/(N+1)/1`` and each
  OSFP cage forwards ``/1`` to ``/5`` internally, so one chain walks all
  64 ports (32 cages x 2 subports) and ends at ``eth1/32/5``.
* 800G -- one port per cage, so the chain is 32 ports and ends at
  ``eth1/32/1``.

Those orderings are fixed by the landed static topologies
``static_topologies/fboss3387263{54,58,72,75}_ash6.cconf`` and
``static_topologies/fboss3388264{79,94}_ash6.cconf`` /
``fboss338826{570,578}_ash6.cconf``.

Each bed gets two configs: a core one scoped to
``_W800_NPI_CORE_PLAYBOOKS``, and a full-suite one that takes everything
``gen_snake_playbooks`` emits. IXIA endpoints are discovered over LLDP
(every bed presents exactly two clean IXIA neighbours), so no config
needs explicit ``direct_ixia_connections``.

``W800_NPI_SNAKE_TEST_CONFIGS`` is collected by
``testconfigs/internal/all.py``.
"""

import typing as t

from ixia.ixia import types as ixia_types
from taac.testconfigs.snake.test_test_config import (
    gen_snake_test_config,
)
from taac.test_as_a_config import types as taac_types


# Everything gen_snake_playbooks emits except the FSDB disruptions,
# test_72hr_longevity (3-day soak, run on its own once the short soaks are clean),
# and the three system-reboot playbooks (need BMC reachability from the test
# host). Spelled as an allowlist rather than playbooks_to_skip because
# gen_snake_test_config validates playbooks_to_include against the generated set
# and raises on an unknown name.
_W800_NPI_CORE_PLAYBOOKS = [
    "test_one_min_longevity",
    "test_ten_min_longevity",
    "test_one_hour_longevity",
    "test_snake_interface_toggle_with_thrift_api",
    "test_snake_half_interface_toggle_with_thrift_api",
    "test_snake_interface_toggle_with_qsfp_util_disable",
    "test_snake_interface_toggle_with_qsfp_util_low_power",
    "test_snake_interface_reset_with_qsfp_reset",
    "test_snake_agent_warmboot",
    "test_snake_agent_coldboot",
    "test_snake_agent_crash",
    "test_snake_qsfp_service_restart",
    "test_snake_qsfp_service_crash",
]

# FR4 optics on these beds do not relink within a single postcheck sample after a
# hard disruption, so the default single-shot port-state and flap-recovery checks
# race the recovery. 6 retries at the 10s default delay gives ~60s of headroom,
# matching what the shipped Icepack FR4 snake configs use.
_W800_RECOVERY_RETRY_COUNT = 6

# Chain end for the 64-port beds (32 cages x /1 + /5) and for the 32-port 800G
# beds (one port per cage).
_SNAKE_END_64_PORT = "eth1/32/5"
_SNAKE_END_32_PORT = "eth1/32/1"

# The 800G beds carry the IMIX profile every other 800G snake in the tree uses,
# rather than the IXIA default frame size the slower W800 beds run.
_W800_800G_IMIX = ixia_types.FrameSize(
    type=ixia_types.FrameSizeType.CUSTOM_IMIX,
    imix_weight={94: 1, 96: 18, 192: 3, 512: 1, 1200: 1, 4600: 76},
)


def _gen_w800_snake_test_config(
    name: str,
    hostname: str,
    destination_interface: str,
    playbooks_to_include: t.Optional[t.List[str]] = None,
    frame_size_settings: t.Optional[ixia_types.FrameSize] = None,
) -> taac_types.TestConfig:
    """Build one W800 snake TestConfig.

    Every W800 bed shares the same snake shape, addressing, line rate and
    recovery headroom; only the hostname, the chain's far end, the playbook
    scope and the frame size vary. Collapsing the rest here keeps each config
    below stating just what differs.

    Args:
        name: Name registered in ``TestConfig.name``.
        hostname: The DUT, which is also the sole IXIA-connected endpoint.
        destination_interface: Far end of the serpentine -- ``eth1/32/5`` on the
            64-port beds, ``eth1/32/1`` on the 32-port 800G beds.
        playbooks_to_include: Allowlist of generated playbook names. ``None``
            keeps everything ``gen_snake_playbooks`` emits (the full suite).
        frame_size_settings: IXIA frame-size policy; ``None`` uses the IXIA
            default.

    Returns:
        A ``TestConfig`` for ``W800_NPI_SNAKE_TEST_CONFIGS``.
    """
    return gen_snake_test_config(
        name=name,
        basset_pool="dne.standalone",
        snake_configs=[
            taac_types.SnakeConfig(
                source=f"{hostname}:eth1/1/1",
                destination=f"{hostname}:{destination_interface}",
                source_ip="5000:1::1/64",
                destination_ip="5000:1::2/64",
            ),
        ],
        hostname=hostname,
        line_rate=99,
        playbooks_to_include=playbooks_to_include,
        frame_size_settings=frame_size_settings,
        postcheck_port_state_retry_count=_W800_RECOVERY_RETRY_COUNT,
        flap_recovery_check_retry_count=_W800_RECOVERY_RETRY_COUNT,
    )


# ---------------------------------------------------------------------------
# Core configs -- scoped to _W800_NPI_CORE_PLAYBOOKS.
# ---------------------------------------------------------------------------

WEDGE800CACT_NPI_SNAKE_TEST_CONFIG_100G = _gen_w800_snake_test_config(
    name="WEDGE800CACT_NPI_SNAKE_TEST_CONFIG_100G",
    hostname="fboss338726354.ash6",
    destination_interface=_SNAKE_END_64_PORT,
    playbooks_to_include=_W800_NPI_CORE_PLAYBOOKS,
)


WEDGE800CACT_NPI_SNAKE_TEST_CONFIG_200G = _gen_w800_snake_test_config(
    name="WEDGE800CACT_NPI_SNAKE_TEST_CONFIG_200G",
    hostname="fboss338726372.ash6",
    destination_interface=_SNAKE_END_64_PORT,
    playbooks_to_include=_W800_NPI_CORE_PLAYBOOKS,
)


WEDGE800CACT_NPI_SNAKE_TEST_CONFIG_400G = _gen_w800_snake_test_config(
    name="WEDGE800CACT_NPI_SNAKE_TEST_CONFIG_400G",
    hostname="fboss338726358.ash6",
    destination_interface=_SNAKE_END_64_PORT,
    playbooks_to_include=_W800_NPI_CORE_PLAYBOOKS,
)


WEDGE800CACT_NPI_SNAKE_TEST_CONFIG_800G = _gen_w800_snake_test_config(
    name="WEDGE800CACT_NPI_SNAKE_TEST_CONFIG_800G",
    hostname="fboss338726375.ash6",
    destination_interface=_SNAKE_END_32_PORT,
    playbooks_to_include=_W800_NPI_CORE_PLAYBOOKS,
    frame_size_settings=_W800_800G_IMIX,
)


WEDGE800BACT_NPI_SNAKE_TEST_CONFIG_100G = _gen_w800_snake_test_config(
    name="WEDGE800BACT_NPI_SNAKE_TEST_CONFIG_100G",
    hostname="fboss338826494.ash6",
    destination_interface=_SNAKE_END_64_PORT,
    playbooks_to_include=_W800_NPI_CORE_PLAYBOOKS,
)


WEDGE800BACT_NPI_SNAKE_TEST_CONFIG_200G = _gen_w800_snake_test_config(
    name="WEDGE800BACT_NPI_SNAKE_TEST_CONFIG_200G",
    hostname="fboss338826578.ash6",
    destination_interface=_SNAKE_END_64_PORT,
    playbooks_to_include=_W800_NPI_CORE_PLAYBOOKS,
)


WEDGE800BACT_NPI_SNAKE_TEST_CONFIG_400G = _gen_w800_snake_test_config(
    name="WEDGE800BACT_NPI_SNAKE_TEST_CONFIG_400G",
    hostname="fboss338826479.ash6",
    destination_interface=_SNAKE_END_64_PORT,
    playbooks_to_include=_W800_NPI_CORE_PLAYBOOKS,
)


WEDGE800BACT_NPI_SNAKE_TEST_CONFIG_800G = _gen_w800_snake_test_config(
    name="WEDGE800BACT_NPI_SNAKE_TEST_CONFIG_800G",
    hostname="fboss338826570.ash6",
    destination_interface=_SNAKE_END_32_PORT,
    playbooks_to_include=_W800_NPI_CORE_PLAYBOOKS,
    frame_size_settings=_W800_800G_IMIX,
)


# ---------------------------------------------------------------------------
# Full-suite configs -- no playbooks_to_include, so gen_snake_playbooks emits
# its whole default set: the 15 core playbooks plus test_72hr_longevity and the
# three system-reboot playbooks. The 72-hour soak alone puts a complete run at
# roughly 3.5 days, and the reboot playbooks need BMC reachability from the test
# host, which is why these live as separate TestConfigs rather than replacing
# the core ones. Select a subset at run time with --regex.
# ---------------------------------------------------------------------------

WEDGE800CACT_NPI_SNAKE_FULL_SUITE_TEST_CONFIG_100G = _gen_w800_snake_test_config(
    name="WEDGE800CACT_NPI_SNAKE_FULL_SUITE_TEST_CONFIG_100G",
    hostname="fboss338726354.ash6",
    destination_interface=_SNAKE_END_64_PORT,
)


WEDGE800CACT_NPI_SNAKE_FULL_SUITE_TEST_CONFIG_200G = _gen_w800_snake_test_config(
    name="WEDGE800CACT_NPI_SNAKE_FULL_SUITE_TEST_CONFIG_200G",
    hostname="fboss338726372.ash6",
    destination_interface=_SNAKE_END_64_PORT,
)


WEDGE800CACT_NPI_SNAKE_FULL_SUITE_TEST_CONFIG_400G = _gen_w800_snake_test_config(
    name="WEDGE800CACT_NPI_SNAKE_FULL_SUITE_TEST_CONFIG_400G",
    hostname="fboss338726358.ash6",
    destination_interface=_SNAKE_END_64_PORT,
)


WEDGE800CACT_NPI_SNAKE_FULL_SUITE_TEST_CONFIG_800G = _gen_w800_snake_test_config(
    name="WEDGE800CACT_NPI_SNAKE_FULL_SUITE_TEST_CONFIG_800G",
    hostname="fboss338726375.ash6",
    destination_interface=_SNAKE_END_32_PORT,
    frame_size_settings=_W800_800G_IMIX,
)


WEDGE800BACT_NPI_SNAKE_FULL_SUITE_TEST_CONFIG_100G = _gen_w800_snake_test_config(
    name="WEDGE800BACT_NPI_SNAKE_FULL_SUITE_TEST_CONFIG_100G",
    hostname="fboss338826494.ash6",
    destination_interface=_SNAKE_END_64_PORT,
)


WEDGE800BACT_NPI_SNAKE_FULL_SUITE_TEST_CONFIG_200G = _gen_w800_snake_test_config(
    name="WEDGE800BACT_NPI_SNAKE_FULL_SUITE_TEST_CONFIG_200G",
    hostname="fboss338826578.ash6",
    destination_interface=_SNAKE_END_64_PORT,
)


WEDGE800BACT_NPI_SNAKE_FULL_SUITE_TEST_CONFIG_400G = _gen_w800_snake_test_config(
    name="WEDGE800BACT_NPI_SNAKE_FULL_SUITE_TEST_CONFIG_400G",
    hostname="fboss338826479.ash6",
    destination_interface=_SNAKE_END_64_PORT,
)


WEDGE800BACT_NPI_SNAKE_FULL_SUITE_TEST_CONFIG_800G = _gen_w800_snake_test_config(
    name="WEDGE800BACT_NPI_SNAKE_FULL_SUITE_TEST_CONFIG_800G",
    hostname="fboss338826570.ash6",
    destination_interface=_SNAKE_END_32_PORT,
    frame_size_settings=_W800_800G_IMIX,
)


W800_NPI_SNAKE_TEST_CONFIGS = [
    WEDGE800CACT_NPI_SNAKE_TEST_CONFIG_100G,
    WEDGE800CACT_NPI_SNAKE_TEST_CONFIG_200G,
    WEDGE800CACT_NPI_SNAKE_TEST_CONFIG_400G,
    WEDGE800CACT_NPI_SNAKE_TEST_CONFIG_800G,
    WEDGE800BACT_NPI_SNAKE_TEST_CONFIG_100G,
    WEDGE800BACT_NPI_SNAKE_TEST_CONFIG_200G,
    WEDGE800BACT_NPI_SNAKE_TEST_CONFIG_400G,
    WEDGE800BACT_NPI_SNAKE_TEST_CONFIG_800G,
    WEDGE800CACT_NPI_SNAKE_FULL_SUITE_TEST_CONFIG_100G,
    WEDGE800CACT_NPI_SNAKE_FULL_SUITE_TEST_CONFIG_200G,
    WEDGE800CACT_NPI_SNAKE_FULL_SUITE_TEST_CONFIG_400G,
    WEDGE800CACT_NPI_SNAKE_FULL_SUITE_TEST_CONFIG_800G,
    WEDGE800BACT_NPI_SNAKE_FULL_SUITE_TEST_CONFIG_100G,
    WEDGE800BACT_NPI_SNAKE_FULL_SUITE_TEST_CONFIG_200G,
    WEDGE800BACT_NPI_SNAKE_FULL_SUITE_TEST_CONFIG_400G,
    WEDGE800BACT_NPI_SNAKE_FULL_SUITE_TEST_CONFIG_800G,
]
