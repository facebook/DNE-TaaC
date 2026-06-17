# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe

"""TAAC ``snake`` (loopback) standalone TestConfig builders.

This module assembles the ``SNAKE_TEST_CONFIGS`` list — a family of
single-DUT ``TestConfig`` objects that loop physical ports of a Minipack3
or Kodiak3 chassis back into themselves via fiber jumpers (a "snake"
topology). Each ``SnakeConfig`` declares one source/destination port pair
on the same DUT plus point-to-point IPv6 addressing; the framework
generates IXIA traffic across the loop and runs PTP + a suite of snake
playbooks (link toggles, FSDB restart/crash, etc.) plus the standard
``gen_common_hcs`` health-check set.

Each module-level constant (``MINIPACK3_STANDALONE_*``,
``KODIAK3_STANDALONE_*``) exercises a different speed grade
(100/200/400/800G, ZR4 800G, mixed 200G+400G); ``SNAKE_TEST_CONFIGS``
collects them for ``testconfigs/internal/all.py``.

Note: despite the ``test_*`` filename prefix this is a TAAC test-config
definition file, not a unit test (per the TAAC repo convention).
"""

import typing as t

from ixia.ixia import types as ixia_types
from taac.playbooks.playbook_definitions import (
    gen_common_hcs,
    gen_snake_playbooks,
)
from taac.test_as_a_config import types as taac_types


def gen_basic_traffic_item_configs(
    snake_configs: t.List[taac_types.SnakeConfig],
    line_rate: int,
    name: t.Optional[str] = None,
    frame_size_settings: t.Optional[ixia_types.FrameSize] = None,
) -> t.List[taac_types.BasicTrafficItemConfig]:
    """Build one IPv6 IXIA traffic item per ``SnakeConfig``.

    Each generated ``BasicTrafficItemConfig`` runs from
    ``snake_config.source`` to ``snake_config.destination`` (both on the
    same DUT — the "snake" loop) at ``line_rate`` percent line rate.

    Args:
        snake_configs: Loop topology entries; each contributes one
            traffic item.
        line_rate: Per-traffic-item line rate as a percentage (0-100).
        name: Optional shared name applied to every generated traffic
            item. When ``None`` the name field is left unset and the
            framework auto-derives it.
        frame_size_settings: Optional IXIA frame-size policy (e.g.
            ``CUSTOM_IMIX``); when ``None`` the IXIA default is used.

    Returns:
        ``list[BasicTrafficItemConfig]`` of length ``len(snake_configs)``.
    """
    basic_traffic_item_configs = [
        taac_types.BasicTrafficItemConfig(
            name=name,
            src_endpoints=[
                taac_types.TrafficEndpoint(
                    name=snake_config.source,
                    device_group_index=0,
                )
            ],
            dest_endpoints=[
                taac_types.TrafficEndpoint(
                    name=snake_config.destination,
                    device_group_index=0,
                )
            ],
            traffic_type=ixia_types.TrafficType.IPV6,
            line_rate=line_rate,
            frame_size_settings=frame_size_settings,
        )
        for snake_config in snake_configs
    ]

    return basic_traffic_item_configs


def gen_snake_test_config(
    name: str,
    hostname: str,
    basset_pool: str,
    snake_configs: t.List[taac_types.SnakeConfig],
    direct_ixia_connections: t.Optional[t.List[taac_types.DirectIxiaConnection]] = None,
    skip_lldp_check: bool = False,
    line_rate: int = 50,
    iteration: int = 10,
    traffic_item_name: t.Optional[str] = None,
    frame_size_settings: t.Optional[ixia_types.FrameSize] = None,
    playbooks_to_skip: t.Optional[t.List[str]] = None,
    include_link_flap_longevity: bool = False,
    manual_test_interfaces: t.Optional[t.List[str]] = None,
) -> taac_types.TestConfig:
    """Build a single-DUT snake/loopback ``TestConfig``.

    Generates IXIA traffic items + per-loop PTP unicast (two-step)
    configs from the supplied ``snake_configs``, then composes the full
    snake playbook suite via ``gen_snake_playbooks`` (with common
    health checks shared between prechecks and postchecks).

    Args:
        name: Name registered in ``TestConfig.name``.
        hostname: Single DUT hostname (e.g. ``"fboss150.99.snc1"``).
        basset_pool: Basset reservation pool (typically
            ``"dne.standalone"``).
        snake_configs: Source/destination loop pairs on the DUT plus
            their /64 IPv6 addressing.

        IXIA + endpoint shape:
            direct_ixia_connections: Optional explicit IXIA wiring;
                when omitted, topology discovery (LLDP / optical
                switch) is used.
            skip_lldp_check: When True, drop the LLDP health check from
                ``gen_common_hcs``.

        Traffic shape:
            line_rate: Per-traffic-item line rate as percent (default
                50%).
            traffic_item_name: Optional shared traffic-item name.
            frame_size_settings: Optional IXIA frame-size policy
                (``RANDOM`` / ``CUSTOM_IMIX`` / ...).

        Playbook control:
            iteration: Iterations passed to ``gen_snake_playbooks``
                (default 10).
            playbooks_to_skip: Test-case names to drop from the
                generated playbook list.
            include_link_flap_longevity: When True, include the long
                link-flap longevity playbook variant.
            manual_test_interfaces: Optional explicit interface list
                forwarded to ``gen_snake_playbooks`` for tests that
                need an operator-pinned target set.

    Returns:
        A ``TestConfig`` ready to slot into ``SNAKE_TEST_CONFIGS``.

    Example:
        >>> gen_snake_test_config(
        ...     name="MINIPACK3_STANDALONE",
        ...     hostname="fboss150.99.snc1",
        ...     basset_pool="dne.standalone",
        ...     snake_configs=[SnakeConfig(...)],
        ...     line_rate=99,
        ...     traffic_item_name="MP3_800G_IMIX",
        ... )
    """
    basic_traffic_item_configs = gen_basic_traffic_item_configs(
        snake_configs, line_rate, traffic_item_name, frame_size_settings
    )

    common_hcs = gen_common_hcs(skip_lldp_check)

    ptp_configs = [
        ixia_types.PTPConfig(
            server_endpoint=ixia_types.PTPEndpoint(
                name=snake_config.source,
                device_group_index=0,
            ),
            client_endpoints=[
                ixia_types.PTPEndpoint(
                    name=snake_config.destination,
                    device_group_index=0,
                ),
            ],
            communication_mode=ixia_types.PTPCommunicationMode.UNICAST,
            step_mode=ixia_types.PTPStepMode.TWO_STEP,
        )
        for snake_config in snake_configs
    ]

    return taac_types.TestConfig(
        name=name,
        basset_pool=basset_pool,
        snake_configs=snake_configs,
        basic_traffic_item_configs=basic_traffic_item_configs,
        ptp_configs=ptp_configs,
        endpoints=[
            taac_types.Endpoint(
                name=hostname,
                dut=True,
                ixia_needed=True,
                direct_ixia_connections=direct_ixia_connections or [],
            ),
        ],
        # Deprecated - define at playbook level
        # postchecks=common_hcs,
        # Deprecated - define at playbook level
        # prechecks=common_hcs,
        playbooks=gen_snake_playbooks(
            hostname,
            iteration,
            playbooks_to_skip,
            include_link_flap_longevity,
            common_prechecks=common_hcs,
            common_postchecks=common_hcs,
            manual_test_interfaces=manual_test_interfaces,
        ),
        # Opt out of the two-tier IXIA topology cache (default-on per D107780401).
        # Snake tests do single-DUT loopback bring-up that exercises
        # `create_basic_setup` itself (per-loop SnakeConfig + PTP unicast
        # endpoints) — caching the post-setup ixncfg would obscure regressions
        # in that very code path. Every snake run pays the cold cost on
        # purpose so any drift in topology assembly surfaces immediately.
        ixia_config_cache=taac_types.IxiaConfigCache(enabled=False),
    )


MINIPACK3_STANDALONE_TEST_CONFIG = gen_snake_test_config(
    name="MINIPACK3_STANDALONE",
    basset_pool="dne.standalone",
    snake_configs=[
        taac_types.SnakeConfig(
            source="fboss123.99.snc1:eth9/15/1",
            destination="fboss123.99.snc1:eth2/1/1",
            source_ip="5000:1::1/64",
            destination_ip="5000:1::2/64",
        ),
    ],
    hostname="fboss123.99.snc1",
)


MINIPACK3_STANDALONE_TEST_CONFIG_100G = gen_snake_test_config(
    name="MINIPACK3_STANDALONE_TEST_CONFIG_100G",
    basset_pool="dne.standalone",
    snake_configs=[
        taac_types.SnakeConfig(
            source="fboss150.99.snc1:eth1/1/1",
            destination="fboss150.99.snc1:eth1/64/1",
            source_ip="5000:1::1/64",
            destination_ip="5000:1::2/64",
        ),
        taac_types.SnakeConfig(
            source="fboss150.99.snc1:eth1/1/5",
            destination="fboss150.99.snc1:eth1/64/5",
            source_ip="4000:1::1/64",
            destination_ip="4000:1::2/64",
        ),
    ],
    hostname="fboss150.99.snc1",
)

MINIPACK3_STANDALONE_TEST_CONFIG_200G = gen_snake_test_config(
    name="MINIPACK3_STANDALONE_TEST_CONFIG_200G",
    basset_pool="dne.standalone",
    snake_configs=[
        taac_types.SnakeConfig(
            source="fboss151.99.snc1:eth1/1/1",
            destination="fboss151.99.snc1:eth1/64/1",
            source_ip="5000:1::1/64",
            destination_ip="5000:1::2/64",
        ),
        taac_types.SnakeConfig(
            source="fboss151.99.snc1:eth1/1/5",
            destination="fboss151.99.snc1:eth1/64/5",
            source_ip="4000:1::1/64",
            destination_ip="4000:1::2/64",
        ),
    ],
    hostname="fboss151.99.snc1",
)


MINIPACK3_STANDALONE_TEST_CONFIG_400G = gen_snake_test_config(
    name="MINIPACK3_STANDALONE_TEST_CONFIG_400G",
    basset_pool="dne.standalone",
    snake_configs=[
        taac_types.SnakeConfig(
            source="fboss152.99.snc1:eth1/1/1",
            destination="fboss152.99.snc1:eth1/64/1",
            source_ip="5000:1::1/64",
            destination_ip="5000:1::2/64",
        ),
        taac_types.SnakeConfig(
            source="fboss152.99.snc1:eth1/1/5",
            destination="fboss152.99.snc1:eth1/64/5",
            source_ip="4000:1::1/64",
            destination_ip="4000:1::2/64",
        ),
    ],
    hostname="fboss152.99.snc1",
)


MINIPACK3_STANDALONE_TEST_CONFIG_200G_400G = gen_snake_test_config(
    name="MINIPACK3_STANDALONE_TEST_CONFIG_200G_400G",
    basset_pool="dne.standalone",
    snake_configs=[
        taac_types.SnakeConfig(
            source="fboss153.99.snc1:eth1/1/1",
            destination="fboss153.99.snc1:eth1/64/1",
            source_ip="5000:1::1/64",
            destination_ip="5000:1::2/64",
        ),
        taac_types.SnakeConfig(
            source="fboss153.99.snc1:eth1/1/5",
            destination="fboss153.99.snc1:eth1/64/5",
            source_ip="4000:1::1/64",
            destination_ip="4000:1::2/64",
        ),
    ],
    hostname="fboss153.99.snc1",
)

MINIPACK3_STANDALONE_TEST_CONFIG_800G = gen_snake_test_config(
    name="MINIPACK3_STANDALONE_TEST_CONFIG_800G",
    basset_pool="dne.standalone",
    snake_configs=[
        taac_types.SnakeConfig(
            source="fboss161.99.snc1:eth1/1/1",
            destination="fboss161.99.snc1:eth1/64/1",
            source_ip="5000:1::1/64",
            destination_ip="5000:1::2/64",
        ),
    ],
    hostname="fboss161.99.snc1",
    # TODO: Use 100% line rate once T227297634 is resolved
    line_rate=99,
    traffic_item_name="MP3_800G_IMIX",
    frame_size_settings=ixia_types.FrameSize(
        type=ixia_types.FrameSizeType.CUSTOM_IMIX,
        imix_weight={94: 1, 96: 18, 192: 3, 512: 1, 1200: 1, 4600: 76},
    ),
    playbooks_to_skip=["test_snake_half_interface_toggle_with_thrift_api"],
    # Specify the number of iterations required for the endurance testing (e.g., 100) rather than the default below
    iteration=10,
)

MINIPACK3_STANDALONE_TEST_CONFIG_ZR4_800G = gen_snake_test_config(
    name="MINIPACK3_STANDALONE_TEST_CONFIG_ZR4_800G",
    basset_pool="dne.standalone",
    snake_configs=[
        taac_types.SnakeConfig(
            source="fboss151.99.ash7:eth1/2/1",
            destination="fboss151.99.ash7:eth1/64/1",
            source_ip="5000:1::1/64",
            destination_ip="5000:1::2/64",
        ),
    ],
    hostname="fboss151.99.ash7",
    line_rate=99,
    traffic_item_name="MP3_800G_IMIX",
    frame_size_settings=ixia_types.FrameSize(
        type=ixia_types.FrameSizeType.CUSTOM_IMIX,
        imix_weight={94: 1, 96: 18, 192: 3, 512: 1, 1200: 1, 4600: 76, 9000: 76},
    ),
    playbooks_to_skip=[
        "test_snake_fsdb_restart",
        "test_snake_fsdb_crash",
    ],
    iteration=10,
    include_link_flap_longevity=True,
)

KODIAK3_STANDALONE_TEST_CONFIG_100G = gen_snake_test_config(
    name="KODIAK3_STANDALONE_TEST_CONFIG_100G",
    basset_pool="dne.standalone",
    snake_configs=[
        taac_types.SnakeConfig(
            source="fboss156.99.qzr1:eth1/1/1",
            destination="fboss156.99.qzr1:eth1/64/1",
            source_ip="5000:1::1/64",
            destination_ip="5000:1::2/64",
        ),
        taac_types.SnakeConfig(
            source="fboss156.99.qzr1:eth1/1/5",
            destination="fboss156.99.qzr1:eth1/64/5",
            source_ip="4000:1::1/64",
            destination_ip="4000:1::2/64",
        ),
    ],
    hostname="fboss156.99.qzr1",
    line_rate=20,
)

KODIAK3_STANDALONE_TEST_CONFIG_200G = gen_snake_test_config(
    name="KODIAK3_STANDALONE_TEST_CONFIG_200G",
    basset_pool="dne.standalone",
    snake_configs=[
        taac_types.SnakeConfig(
            source="fboss157.99.qzr1:eth1/1/1",
            destination="fboss157.99.qzr1:eth1/64/1",
            source_ip="5000:1::1/64",
            destination_ip="5000:1::2/64",
        ),
        taac_types.SnakeConfig(
            source="fboss157.99.qzr1:eth1/1/5",
            destination="fboss157.99.qzr1:eth1/64/5",
            source_ip="4000:1::1/64",
            destination_ip="4000:1::2/64",
        ),
    ],
    hostname="fboss157.99.qzr1",
    line_rate=25,
)

KODIAK3_STANDALONE_TEST_CONFIG_400G = gen_snake_test_config(
    name="KODIAK3_STANDALONE_TEST_CONFIG_400G",
    basset_pool="dne.standalone",
    snake_configs=[
        taac_types.SnakeConfig(
            source="fboss158.99.qzr1:eth1/1/1",
            destination="fboss158.99.qzr1:eth1/64/1",
            source_ip="5000:1::1/64",
            destination_ip="5000:1::2/64",
        ),
        taac_types.SnakeConfig(
            source="fboss158.99.qzr1:eth1/1/5",
            destination="fboss158.99.qzr1:eth1/64/5",
            source_ip="4000:1::1/64",
            destination_ip="4000:1::2/64",
        ),
    ],
    hostname="fboss158.99.qzr1",
    line_rate=50,
)

KODIAK3_STANDALONE_TEST_CONFIG_200G_400G = gen_snake_test_config(
    name="KODIAK3_STANDALONE_TEST_CONFIG_200G_400G",
    basset_pool="dne.standalone",
    snake_configs=[
        taac_types.SnakeConfig(
            source="fboss159.99.qzr1:eth1/1/1",
            destination="fboss159.99.qzr1:eth1/64/1",
            source_ip="5000:1::1/64",
            destination_ip="5000:1::2/64",
        ),
        taac_types.SnakeConfig(
            source="fboss159.99.qzr1:eth1/1/5",
            destination="fboss159.99.qzr1:eth1/64/5",
            source_ip="4000:1::1/64",
            destination_ip="4000:1::2/64",
        ),
    ],
    hostname="fboss159.99.qzr1",
    line_rate=30,
)

KODIAK3_STANDALONE_TEST_CONFIG_400G_200G = gen_snake_test_config(
    name="KODIAK3_STANDALONE_TEST_CONFIG_400G_200G",
    basset_pool="dne.standalone",
    snake_configs=[
        taac_types.SnakeConfig(
            source="fboss160.99.qzr1:eth1/1/1",
            destination="fboss160.99.qzr1:eth1/64/1",
            source_ip="5000:1::1/64",
            destination_ip="5000:1::2/64",
        ),
        taac_types.SnakeConfig(
            source="fboss160.99.qzr1:eth1/1/5",
            destination="fboss160.99.qzr1:eth1/64/5",
            source_ip="4000:1::1/64",
            destination_ip="4000:1::2/64",
        ),
    ],
    hostname="fboss160.99.qzr1",
    line_rate=10,
)

KODIAK3_STANDALONE_TEST_CONFIG_ZR4_800G = gen_snake_test_config(
    name="KODIAK3_STANDALONE_TEST_CONFIG_ZR4_800G",
    basset_pool="dne.standalone",
    snake_configs=[
        taac_types.SnakeConfig(
            source="fboss152.99.ash7:eth1/2/1",
            destination="fboss152.99.ash7:eth1/64/1",
            source_ip="5000:1::1/64",
            destination_ip="5000:1::2/64",
        ),
    ],
    hostname="fboss152.99.ash7",
    line_rate=99,
    traffic_item_name="MP3_800G_IMIX",
    frame_size_settings=ixia_types.FrameSize(
        type=ixia_types.FrameSizeType.CUSTOM_IMIX,
        imix_weight={94: 1, 96: 18, 192: 3, 512: 1, 1200: 1, 4600: 76, 9000: 76},
    ),
    playbooks_to_skip=[
        "test_snake_fsdb_restart",
        "test_snake_fsdb_crash",
    ],
    iteration=10,
    include_link_flap_longevity=True,
)


SNAKE_TEST_CONFIGS = [
    MINIPACK3_STANDALONE_TEST_CONFIG,
    MINIPACK3_STANDALONE_TEST_CONFIG_100G,
    MINIPACK3_STANDALONE_TEST_CONFIG_200G,
    MINIPACK3_STANDALONE_TEST_CONFIG_400G,
    MINIPACK3_STANDALONE_TEST_CONFIG_200G_400G,
    MINIPACK3_STANDALONE_TEST_CONFIG_800G,
    MINIPACK3_STANDALONE_TEST_CONFIG_ZR4_800G,
    KODIAK3_STANDALONE_TEST_CONFIG_100G,
    KODIAK3_STANDALONE_TEST_CONFIG_400G,
    KODIAK3_STANDALONE_TEST_CONFIG_200G_400G,
    KODIAK3_STANDALONE_TEST_CONFIG_400G_200G,
    KODIAK3_STANDALONE_TEST_CONFIG_200G,
    KODIAK3_STANDALONE_TEST_CONFIG_ZR4_800G,
]
