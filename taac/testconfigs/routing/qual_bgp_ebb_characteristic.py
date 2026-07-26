# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""BGP EBB characteristic qualification testconfigs (Arista lab boxes eb02 / eb03 / eb04 / eb.test).

Wave 5D.1 -- migrates the 5 thin wrappers previously living at
``testconfigs/routing/ebb/eb02_arista_constant_attribute_storage_varying_combinations_test_config.py``,
``testconfigs/routing/ebb/eb03_arista_high_diversity_test_config.py``,
``testconfigs/routing/ebb/eb02_arista_bgp_queue_memory_monitor_ipv6_50ebgp_25ibgp_with_flapping_test_config.py``,
``testconfigs/routing/ebb/eb04_arista_bgp_queue_memory_monitor_ipv6_50ebgp_25ibgp_with_flapping_test_config.py``
and
``testconfigs/routing/ebb/eb_test_device_bgp_queue_memory_monitor_ipv6_50ebgp_25ibgp_with_flapping_test_config.py``
into this catalog. Each ``TestConfig.name`` string is grandfathered from
the legacy wrapper so the golden manifest hash is byte-wise identical.

External consumers import via ``testconfigs.routing`` root; see README.md §7.
"""

from taac.abstractions.physical_inventory import (
    EB02_LAB_ASH6,
    EB03_LAB_ASH6,
    EB04_LAB_ASH6,
    EB_TEST_DEVICE,
)
from taac.testconfigs.routing.factories.bgp_ebb_characteristic import (
    create_bgp_ebb_characteristic_constant_attribute_storage_test_config,
    create_bgp_ebb_characteristic_constant_attribute_storage_varying_combinations_test_config,
    create_bgp_ebb_characteristic_queue_memory_monitor_test_config,
    create_bgp_ebb_characteristic_separable_policy_test_config,
    create_bgp_ebb_characteristic_update_packing_test_config,
)
from taac.test_as_a_config import types as taac_types


# ─── EB02 -- constant-attribute-storage varying-combinations ─────────────
EB02_ARISTA_CONSTANT_ATTRIBUTE_STORAGE_VARYING_COMBINATIONS_TEST_CONFIG = create_bgp_ebb_characteristic_constant_attribute_storage_varying_combinations_test_config(
    EB02_LAB_ASH6,
    name="EB02_ARISTA_CONSTANT_ATTRIBUTE_STORAGE_VARYING_COMBINATIONS_TEST",
)


# ─── EB03 -- high-diversity constant-attribute-storage ───────────────────
EB03_ARISTA_HIGH_DIVERSITY_TEST_CONFIG = (
    create_bgp_ebb_characteristic_constant_attribute_storage_test_config(
        EB03_LAB_ASH6,
        name="EB03_ARISTA_HIGH_DIVERSITY_TEST",
    )
)


# ─── EB02 -- queue memory monitor (with ssh setup tasks) ─────────────────
# Legacy wrapper wired ``direct_ixia_connections`` EBGP-first (Ethernet3/1/3
# card 6/2, then Ethernet3/1/5 card 6/3); preserve that ordering for
# byte-identical golden hash.
EB02_ARISTA_BGP_QUEUE_MEMORY_MONITOR_IPV6_50EBGP_25IBGP_WITH_FLAPPING_TEST_CONFIG = (
    create_bgp_ebb_characteristic_queue_memory_monitor_test_config(
        EB02_LAB_ASH6,
        name="EB02_ARISTA_BGP_QUEUE_MEMORY_MONITOR_IPV6_50EBGP_25IBGP_WITH_FLAPPING",
        ssh_user="admin",
        direct_ixia_connections=[
            taac_types.DirectIxiaConnection(
                interface="Ethernet3/1/3",
                ixia_chassis_ip=EB02_LAB_ASH6.ixia_chassis_ip,
                ixia_port="6/2",
            ),
            taac_types.DirectIxiaConnection(
                interface="Ethernet3/1/5",
                ixia_chassis_ip=EB02_LAB_ASH6.ixia_chassis_ip,
                ixia_port="6/3",
            ),
        ],
    )
)


# ─── EB04 -- queue memory monitor (no ssh setup tasks) ────────────────────
# Legacy wrapper wired ``direct_ixia_connections`` IBGP-first (Ethernet3/1/3
# card 6/8, then Ethernet3/1/1 card 6/7); preserve that ordering.
EB04_ARISTA_BGP_QUEUE_MEMORY_MONITOR_IPV6_50EBGP_25IBGP_WITH_FLAPPING_TEST_CONFIG = (
    create_bgp_ebb_characteristic_queue_memory_monitor_test_config(
        EB04_LAB_ASH6,
        name="EB04_ARISTA_BGP_QUEUE_MEMORY_MONITOR_IPV6_50EBGP_25IBGP_WITH_FLAPPING",
        direct_ixia_connections=[
            taac_types.DirectIxiaConnection(
                interface="Ethernet3/1/3",
                ixia_chassis_ip=EB04_LAB_ASH6.ixia_chassis_ip,
                ixia_port="6/8",
            ),
            taac_types.DirectIxiaConnection(
                interface="Ethernet3/1/1",
                ixia_chassis_ip=EB04_LAB_ASH6.ixia_chassis_ip,
                ixia_port="6/7",
            ),
        ],
    )
)


# ─── EB_TEST_DEVICE -- queue memory monitor (bgp_ip host_driver extra) ────
# Legacy wrapper wired ``direct_ixia_connections`` EBGP-first (Ethernet3/1/5
# card 5/3, then Ethernet3/1/3 card 5/2); preserve that ordering.
EB_TEST_DEVICE_BGP_QUEUE_MEMORY_MONITOR_IPV6_50EBGP_25IBGP_WITH_FLAPPING_TEST_CONFIG = (
    create_bgp_ebb_characteristic_queue_memory_monitor_test_config(
        EB_TEST_DEVICE,
        name="EB_TEST_DEVICE_BGP_QUEUE_MEMORY_MONITOR_IPV6_50EBGP_25IBGP_WITH_FLAPPING",
        direct_ixia_connections=[
            taac_types.DirectIxiaConnection(
                interface="Ethernet3/1/5",
                ixia_chassis_ip=EB_TEST_DEVICE.ixia_chassis_ip,
                ixia_port="5/3",
            ),
            taac_types.DirectIxiaConnection(
                interface="Ethernet3/1/3",
                ixia_chassis_ip=EB_TEST_DEVICE.ixia_chassis_ip,
                ixia_port="5/2",
            ),
        ],
    )
)


# ─── EB02 -- separable policy case 8 (ssh_user=admin, sends via BgpPeers) ─
# Legacy wrapper wired ``direct_ixia_connections`` EBGP-only (Ethernet3/1/3
# card 6/2). Preserve the ordering for byte-identical golden hash.
EB02_ARISTA_BGP_PLUS_PLUS_SEPARABLE_POLICY_1_PEER_TEST_CONFIG = (
    create_bgp_ebb_characteristic_separable_policy_test_config(
        EB02_LAB_ASH6,
        name="EB02_ARISTA_BGP_PLUS_PLUS_SEPARABLE_POLICY_1_PEER",
        ssh_user="admin",
    )
)


# ─── EB04 -- separable policy case 8 (no ssh_user, factory defaults) ──────
# Wave 5E.1 -- migrated from
# ``testconfigs/routing/ebb/eb04_arista_bgp_plus_plus_separable_policy_1_peer_test_config.py``.
# Legacy wrapper wired a single EBGP ``DirectIxiaConnection`` (Ethernet3/1/1
# card 6/7), matched by ``EB04_LAB_ASH6.ixia_ports[0]`` so the factory
# default reproduces the same list. ``TestConfig.name`` preserved verbatim.
EB04_ARISTA_BGP_PLUS_PLUS_SEPARABLE_POLICY_1_PEER_TEST_CONFIG = (
    create_bgp_ebb_characteristic_separable_policy_test_config(
        EB04_LAB_ASH6,
        name="EB04_ARISTA_BGP_PLUS_PLUS_SEPARABLE_POLICY_1_PEER",
    )
)


# ─── EB02 -- BGP UPDATE message packing validation ────────────────────────
EB02_ARISTA_BGP_UPDATE_PACKING_VALIDATION_TEST_CONFIG = (
    create_bgp_ebb_characteristic_update_packing_test_config(
        EB02_LAB_ASH6,
        name="EB02_ARISTA_BGP_UPDATE_PACKING_VALIDATION",
    )
)


__all__ = [
    "EB02_ARISTA_BGP_PLUS_PLUS_SEPARABLE_POLICY_1_PEER_TEST_CONFIG",
    "EB02_ARISTA_BGP_QUEUE_MEMORY_MONITOR_IPV6_50EBGP_25IBGP_WITH_FLAPPING_TEST_CONFIG",
    "EB02_ARISTA_BGP_UPDATE_PACKING_VALIDATION_TEST_CONFIG",
    "EB02_ARISTA_CONSTANT_ATTRIBUTE_STORAGE_VARYING_COMBINATIONS_TEST_CONFIG",
    "EB03_ARISTA_HIGH_DIVERSITY_TEST_CONFIG",
    "EB04_ARISTA_BGP_PLUS_PLUS_SEPARABLE_POLICY_1_PEER_TEST_CONFIG",
    "EB04_ARISTA_BGP_QUEUE_MEMORY_MONITOR_IPV6_50EBGP_25IBGP_WITH_FLAPPING_TEST_CONFIG",
    "EB_TEST_DEVICE_BGP_QUEUE_MEMORY_MONITOR_IPV6_50EBGP_25IBGP_WITH_FLAPPING_TEST_CONFIG",
]
