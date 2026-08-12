# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe

"""TAAC ``snake`` (loopback) standalone TestConfig builders.

This module assembles the ``SNAKE_TEST_CONFIGS`` list -- a family of
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
from taac.health_checks.healthcheck_definitions import (
    create_ixia_packet_loss_check,
)
from taac.playbooks.playbook_definitions import (
    gen_common_hcs,
    gen_snake_playbooks,
    SNAKE_BENCHMARK_PACKET_SIZES,
)
from taac.health_check.health_check import types as hc_types
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
    same DUT -- the "snake" loop) at ``line_rate`` percent line rate.

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


def gen_benchmark_traffic_item_configs(
    snake_configs: t.List[taac_types.SnakeConfig],
    packet_sizes: t.List[int],
    line_rate: int = 100,
) -> t.Tuple[t.List[taac_types.BasicTrafficItemConfig], t.Dict[int, str]]:
    """Build one FIXED-frame-size traffic item per benchmark packet size.

    IXIA frame size is pinned on the traffic item when the config is built,
    so a packet-size sweep needs one traffic item per size rather than a
    runtime resize. Each item is named ``SNAKE_BENCHMARK_<size>B`` and the
    returned map feeds ``gen_snake_playbooks`` so every benchmark playbook
    starts only its own size.

    Args:
        snake_configs: Loop topology entries; each contributes one traffic
            item per packet size.
        packet_sizes: Frame sizes in bytes.
        line_rate: Per-traffic-item line rate as a percentage.

    Returns:
        ``(traffic_item_configs, {packet_size: traffic_item_name})``.
    """
    traffic_item_configs: t.List[taac_types.BasicTrafficItemConfig] = []
    name_by_packet_size: t.Dict[int, str] = {}
    for packet_size in packet_sizes:
        traffic_item_name = f"SNAKE_BENCHMARK_{packet_size}B"
        name_by_packet_size[packet_size] = traffic_item_name
        traffic_item_configs.extend(
            gen_basic_traffic_item_configs(
                snake_configs,
                line_rate,
                name=traffic_item_name,
                frame_size_settings=ixia_types.FrameSize(
                    type=ixia_types.FrameSizeType.FIXED,
                    fixed_size=packet_size,
                ),
            )
        )
    return traffic_item_configs, name_by_packet_size


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
    link_flap_longevity_iterations: int = 33,
    link_flap_longevity_disable_delay_s: int = 30,
    link_flap_longevity_enable_delay_s: int = 300,
    link_flap_longevity_recovery_wait_s: int = 300,
    link_flap_longevity_soak_s: int = 3600,
    link_flap_longevity_interface_slice: t.Optional[str] = None,
    manual_test_interfaces: t.Optional[t.List[str]] = None,
    ixia_ports: t.Optional[t.List[str]] = None,
    precheck_packet_loss_clear_stats: bool = False,
    packet_loss_sleep_time: int = 10,
    include_benchmark: bool = False,
    benchmark_packet_sizes: t.Optional[t.List[int]] = None,
    benchmark_line_rate: int = 100,
    use_ipv6_ping: bool = True,
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
            ixia_ports: Optional allowlist of local DUT interfaces (bare
                names, e.g. ``["eth1/1/1", "eth1/64/1"]``) to use as the
                IXIA endpoints. When set, LLDP-discovered IXIA ports not
                in this list are ignored (``select_ixia_assets``). Use
                when the device is cabled to more IXIA ports than the
                snake actually traverses.

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
            link_flap_longevity_iterations / _disable_delay_s /
                _enable_delay_s / _recovery_wait_s / _soak_s /
                _interface_slice: Tuning knobs for that playbook (only
                meaningful when ``include_link_flap_longevity=True``).
                Defaults reproduce the original hardcoded behavior (33
                cycles over all interfaces, 30s/300s flap delays, 5-min
                recovery wait, 1-hour soak). ``_interface_slice`` is a
                positional slice expression (e.g. ``":3"`` = first 3
                interfaces) to flap a subset; ``None`` flaps all.
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

    # Benchmark sweep: one extra FIXED-frame-size traffic item per packet size.
    # They are configured but not started by the standard playbooks -- each
    # benchmark playbook selects its own via `traffic_items_to_start`.
    benchmark_name_by_packet_size = None
    if include_benchmark:
        benchmark_traffic_item_configs, benchmark_name_by_packet_size = (
            gen_benchmark_traffic_item_configs(
                snake_configs,
                benchmark_packet_sizes or SNAKE_BENCHMARK_PACKET_SIZES,
                benchmark_line_rate,
            )
        )
        basic_traffic_item_configs = (
            basic_traffic_item_configs + benchmark_traffic_item_configs
        )

    common_hcs = gen_common_hcs(skip_lldp_check)

    # Optionally override the IXIA_PACKET_LOSS_CHECK on pre/post checks:
    #  * precheck_packet_loss_clear_stats: clear IXIA stats first so the PRE-check
    #    measures STEADY-STATE loss (excludes the NDP/MAC startup transient).
    #    This is ONLY ever applied to the pre-check. The post-check is ALWAYS
    #    clear_traffic_stats=False -- clearing it would discard exactly the
    #    test/disruption-window loss the post-check exists to catch.
    #  * packet_loss_sleep_time: seconds between stop_traffic and sampling stats
    #    (the in-flight drain window); a longer drain lets all in-flight frames
    #    arrive before measuring. Applies to both pre and post checks.
    def _override_packet_loss(hcs, clear_traffic_stats):
        return [
            (
                create_ixia_packet_loss_check(
                    clear_traffic_stats=clear_traffic_stats,
                    sleep_time=packet_loss_sleep_time,
                )
                if hc.name == hc_types.CheckName.IXIA_PACKET_LOSS_CHECK
                else hc
            )
            for hc in hcs
        ]

    common_prechecks = common_hcs
    common_postchecks = common_hcs
    if precheck_packet_loss_clear_stats or packet_loss_sleep_time != 10:
        common_prechecks = _override_packet_loss(
            common_hcs, clear_traffic_stats=precheck_packet_loss_clear_stats
        )
    if packet_loss_sleep_time != 10:
        # post-check: keep clear_traffic_stats=False, only adjust the drain window
        common_postchecks = _override_packet_loss(common_hcs, clear_traffic_stats=False)

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

    test_config = taac_types.TestConfig(
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
                ixia_ports=ixia_ports,
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
            link_flap_longevity_iterations=link_flap_longevity_iterations,
            link_flap_longevity_disable_delay_s=link_flap_longevity_disable_delay_s,
            link_flap_longevity_enable_delay_s=link_flap_longevity_enable_delay_s,
            link_flap_longevity_recovery_wait_s=link_flap_longevity_recovery_wait_s,
            link_flap_longevity_soak_s=link_flap_longevity_soak_s,
            link_flap_longevity_interface_slice=link_flap_longevity_interface_slice,
            common_prechecks=common_prechecks,
            common_postchecks=common_postchecks,
            manual_test_interfaces=manual_test_interfaces,
            benchmark_traffic_item_name_by_packet_size=benchmark_name_by_packet_size,
            use_ipv6_ping=use_ipv6_ping,
        ),
        # Opt out of the two-tier IXIA topology cache (default-on per D107780401).
        # Snake tests do single-DUT loopback bring-up that exercises
        # `create_basic_setup` itself (per-loop SnakeConfig + PTP unicast
        # endpoints) -- caching the post-setup ixncfg would obscure regressions
        # in that very code path. Every snake run pays the cold cost on
        # purpose so any drift in topology assembly surfaces immediately.
        ixia_config_cache=taac_types.IxiaConfigCache(enabled=False),
    )
    return test_config


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
    # NOTE: test_snake_half_interface_toggle_with_thrift_api is no longer skipped.
    # It used to be skipped because the old positional ::4/2::4 slicing split a
    # jumper's two ends across waves and forced a circuit's partner DOWN while the
    # check still expected it UP -- a guaranteed false failure on a loopback snake.
    # The playbook now selects whole snake circuits and disables only the A-end, so
    # disabling "even circuits" downs exactly the even circuits and the check passes.
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


# fboss159.99.ash6 -- Minipack3 (montblanc) 800G DR4 gearbox serpentine snake
# (NPI T267419633): 2x400G DR4 optics per module driven through the gearbox (800G/module).
# The on-box config is a SINGLE serpentine chain with exactly
# two clean IXIA endpoints (verified via VLAN membership on /etc/coop/agent/current):
#   ingress eth1/1/1 (VLAN 2000, bridged with first hop eth1/2/1)
#   egress  eth1/64/1 (VLAN 2094, bridged with last hop eth1/63/7)
# The device is also cabled to eth1/1/5 and eth1/64/5, but those two IXIA taps dangle
# (not part of the snake chain), so we pin ixia_ports to the two real endpoints and let
# select_ixia_assets ignore the extra LLDP-discovered taps. No topology/device change.
# Scoped to the stable-state baseline only (test_one_min_longevity).
MINIPACK3_STANDALONE_TEST_CONFIG_FBOSS159_800G_DR4_GEARBOX = gen_snake_test_config(
    name="MINIPACK3_STANDALONE_TEST_CONFIG_FBOSS159_800G_DR4_GEARBOX",
    basset_pool="dne.standalone",
    snake_configs=[
        taac_types.SnakeConfig(
            source="fboss159.99.ash6:eth1/1/1",
            destination="fboss159.99.ash6:eth1/64/1",
            source_ip="5000:1::1/64",
            destination_ip="5000:1::2/64",
        ),
    ],
    hostname="fboss159.99.ash6",
    # 45% is the qualified lossless operating point for these DR4 gearbox optics at 400B
    # frames. Repeatable 0% loss requires all three of: the FIXED 400B frame (below),
    # isolating the dangling eth1/1/5 tap out of snake VLAN 2004 (configerator
    # fboss159_99_ash6 fix -- removes a flood sink), and a warmed snake (MACs learned so
    # traffic is unicast, not flooded). With those in place, 45% is lossless; lower rates
    # do NOT help the residual loss (it was flood/convergence, not a congestion cap).
    line_rate=45,
    # Pin a FIXED 400B frame -- the qualified DR4-gearbox operating point. Without an
    # explicit setting, frame_size_settings=None lets IXIA fall back to a small
    # control-plane frame size (UseControlPlaneFrameSize=True), whose ~6x higher packet
    # rate at 45% line rate overruns the gearbox pipeline (which is pps-limited) and
    # tail-drops ~46% of frames as ingress discards distributed around the loop
    # (Input Discards >> 0, Input Errors = 0 -- congestion, not optics). Pinning 400B
    # restores the lossless packet rate characterized in the June baseline.
    frame_size_settings=ixia_types.FrameSize(
        type=ixia_types.FrameSizeType.FIXED,
        fixed_size=400,
    ),
    # Use only the two clean IXIA endpoints; ignore the dangling eth1/1/5, eth1/64/5 taps.
    ixia_ports=["eth1/1/1", "eth1/64/1"],
    # Bypass IXIA LLDP asset discovery (IXIA LLDP is not a meaningful signal for this
    # snake NPI, and it drops after any ixnetworkweb restart on this hand-brought-up box).
    # Pin the tap->chassis/port mapping explicitly so setup never depends on IXIA LLDP;
    # the snake device-to-device circuits are unaffected. ixia16.netcastle.ash6.
    direct_ixia_connections=[
        taac_types.DirectIxiaConnection(
            interface="eth1/1/1",
            ixia_chassis_ip="2401:db00:2066:304b::3004",
            ixia_port="1/21",
        ),
        taac_types.DirectIxiaConnection(
            interface="eth1/64/1",
            ixia_chassis_ip="2401:db00:2066:304b::3004",
            ixia_port="1/23",
        ),
    ],
    # LLDP_CHECK enabled: D109171150 (eth1/34<->eth1/35 lane-swap) has LANDED, so the
    # check's expected neighbor (read from the landed static topology) now matches the
    # real swapped cabling. LLDP is validated, not skipped.
    skip_lldp_check=False,
    # Measure STEADY-STATE packet loss (clear IXIA stats after convergence) so the precheck
    # doesn't fail on the harmless NDP/MAC startup transient.
    precheck_packet_loss_clear_stats=True,
    # Wait 30s (not the default 10s) between stop_traffic and sampling stats, so all
    # in-flight frames fully drain on this 96-hop snake before the loss measurement.
    packet_loss_sleep_time=30,
    # Enabled: Phase 1 (test_one_min_longevity) + Phase 3 (link-event/lane re-sync) +
    # Enabled: Phase 3 (link-event) + Phase 4 (service resilience) -- "all non-longevity"
    # that can run on this box. Skipped, with reason:
    #  * test_ten_min_longevity: ENABLED as a steady-state soak with the port-state
    #    collector (gen_snake_longevity_playbook collect_port_state=True). It polls every
    #    port every 5s for 10 min and FAILS on any flap -- surfacing the spontaneous
    #    ~60s gearbox link flaps (T283020514) instead of riding through them.
    #  * remaining longevity (1m/1h/72h): out of scope for this run.
    #  * fsdb restart/crash: fsdb is not deployed on this manually brought-up box (no
    #    fsdb.service), so they time out on fsdb-thrift -- an environment gap, not a bug.
    #  * transceiver/fiber removal: require physical optic/fiber manipulation at the rack.
    #  * system reboots (bmc/userver): run separately/last (heavy; box is hand-deployed).
    playbooks_to_skip=[
        "test_one_min_longevity",
        "test_one_hour_longevity",
        "test_72hr_longevity",
        "test_snake_system_reboot_bmc_full",
        "test_snake_system_reboot_bmc_microserver",
        "test_snake_system_reboot_microserver",
        "test_snake_transceiver_removal",
        "test_snake_fiber_removal",
        "test_snake_fsdb_restart",
        "test_snake_fsdb_crash",
    ],
    # iteration=1 for the first full Phase 3/4 sweep (validate each disruption once);
    # bump later once a clean single-iteration sweep is confirmed.
    iteration=1,
    # test_snake_link_flap_with_longevity: enabled as a SMALL first-pass to assess the
    # test-case quality on this box before running the full-scale timeline. Scaled down
    # from the defaults (33 iters, all interfaces, 300s enable delay, 5m recovery, 1h
    # soak) to a quick ~8-minute run: 1 flap cycle over just the first 3 interfaces
    # (30s spacing each way), 2-minute recovery wait, 2-minute longevity soak. Bump
    # these to the production timeline once the small run looks clean.
    include_link_flap_longevity=True,
    link_flap_longevity_iterations=1,
    link_flap_longevity_interface_slice=":3",
    link_flap_longevity_disable_delay_s=30,
    link_flap_longevity_enable_delay_s=30,
    link_flap_longevity_recovery_wait_s=120,
    link_flap_longevity_soak_s=120,
)


ICEPACK_STANDALONE_TEST_CONFIG_FR4_800G = gen_snake_test_config(
    name="ICEPACK_STANDALONE_TEST_CONFIG_FR4_800G",
    basset_pool="dne.standalone",
    snake_configs=[
        taac_types.SnakeConfig(
            source="fboss335776657.ash6:eth1/1/1",
            destination="fboss335776657.ash6:eth1/64/5",
            source_ip="5000:1::1/64",
            destination_ip="5000:1::2/64",
        ),
    ],
    direct_ixia_connections=[
        taac_types.DirectIxiaConnection(
            interface="eth1/1/1",
            ixia_chassis_ip="2401:db00:2066:31fb::3025",
            ixia_port="1/7",
        ),
        taac_types.DirectIxiaConnection(
            interface="eth1/64/5",
            ixia_chassis_ip="2401:db00:2066:31fb::3025",
            ixia_port="1/8",
        ),
    ],
    hostname="fboss335776657.ash6",
    line_rate=99,
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


ICEPACK_STANDALONE_TEST_CONFIG_FR4_400G = gen_snake_test_config(
    name="ICEPACK_STANDALONE_TEST_CONFIG_FR4_400G",
    basset_pool="dne.standalone",
    snake_configs=[
        taac_types.SnakeConfig(
            source="fboss336803613.ash6:eth1/1/1",
            destination="fboss336803613.ash6:eth1/64/5",
            source_ip="5000:1::1/64",
            destination_ip="5000:1::2/64",
        ),
    ],
    hostname="fboss336803613.ash6",
    line_rate=49,
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


# Throughput benchmark: the 10-point packet-size sweep at 100% line rate, 12
# mins per size (~2h). Kept as its own TestConfig rather than folded into
# MINIPACK3_STANDALONE so the standard snake suites keep their current runtime;
# the long soak playbooks are skipped here since the benchmark is the point.
MINIPACK3_STANDALONE_BENCHMARK_TEST_CONFIG = gen_snake_test_config(
    name="MINIPACK3_STANDALONE_BENCHMARK",
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
    include_benchmark=True,
    playbooks_to_skip=[
        "test_one_hour_longevity",
        "test_72hr_longevity",
    ],
)

SNAKE_TEST_CONFIGS = [
    MINIPACK3_STANDALONE_TEST_CONFIG_FBOSS159_800G_DR4_GEARBOX,
    MINIPACK3_STANDALONE_TEST_CONFIG,
    MINIPACK3_STANDALONE_BENCHMARK_TEST_CONFIG,
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
    ICEPACK_STANDALONE_TEST_CONFIG_FR4_400G,
    ICEPACK_STANDALONE_TEST_CONFIG_FR4_800G,
]
