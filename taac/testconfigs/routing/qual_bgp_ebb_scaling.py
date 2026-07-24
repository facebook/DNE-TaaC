# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
"""BGP++ EBB scaling qualification testconfigs (Arista lab boxes eb02 / eb03).

Wave 5C -- migrates the 5 ``test_config_performance_scaling_case{1,3,4,6,9}``
factories and their 10 thin wrappers into the routing framework. Each
TestConfig constant name below is grandfathered from the legacy
``testconfigs/routing/ebb/eb0{2,3}_arista_performance_scaling_test_*.py``
wrappers so the golden manifest hash is byte-wise identical.

External consumers import via ``testconfigs.routing`` root; see README.md §7.
"""

import json
import os

from taac.testconfigs.routing.factories.bgp_ebb_characteristic import (
    test_config_constant_attribute_storage_on_eos,
)
from taac.testconfigs.routing.factories.bgp_ebb_scaling import (
    create_bgp_ebb_scaling_bounded_ecmp_sets_test_config,
    create_bgp_ebb_scaling_performance_test_config,
    create_bgp_ebb_scaling_route_churn_prefix_test_config,
    create_bgp_ebb_scaling_transient_memory_peer_scale_test_config,
    create_bgp_ebb_scaling_transient_memory_route_scale_test_config,
)
from taac.testconfigs.routing.physical_inventory import (
    EB02_LAB_ASH6,
    EB03_LAB_ASH6,
)
from taac.test_as_a_config import types as taac_types


# ─── EB02 -- perf-scaling case 1: egress IBGP peer sweep (5 scales) ────────
# TestConfig ``name`` fields grandfathered from the legacy wrappers
# ``eb02_arista_performance_scaling_test_1_{200,400,600,800,1000}_ibgp_peers_test_config.py``
# so the golden manifest stays byte-wise identical.
EB02_ARISTA_PERFORMANCE_SCALING_TEST_1_200_IBGP_PEERS_TEST_CONFIG = (
    create_bgp_ebb_scaling_performance_test_config(
        EB02_LAB_ASH6,
        name="EB02-ARISTA_PERFORMANCE_SCALING_TEST_1_200_IBGP_PEERS",
        egress_peer_counts=[100],
    )
)
EB02_ARISTA_PERFORMANCE_SCALING_TEST_1_400_IBGP_PEERS_TEST_CONFIG = (
    create_bgp_ebb_scaling_performance_test_config(
        EB02_LAB_ASH6,
        name="EB02-ARISTA_PERFORMANCE_SCALING_TEST_1_400_IBGP_PEERS",
        egress_peer_counts=[200],
    )
)
EB02_ARISTA_PERFORMANCE_SCALING_TEST_1_600_IBGP_PEERS_TEST_CONFIG = (
    create_bgp_ebb_scaling_performance_test_config(
        EB02_LAB_ASH6,
        name="EB02-ARISTA_PERFORMANCE_SCALING_TEST_1_600_IBGP_PEERS",
        egress_peer_counts=[300],
    )
)
EB02_ARISTA_PERFORMANCE_SCALING_TEST_1_800_IBGP_PEERS_TEST_CONFIG = (
    create_bgp_ebb_scaling_performance_test_config(
        EB02_LAB_ASH6,
        name="EB02-ARISTA_PERFORMANCE_SCALING_TEST_1_800_IBGP_PEERS",
        egress_peer_counts=[400],
    )
)
EB02_ARISTA_PERFORMANCE_SCALING_TEST_1_1000_IBGP_PEERS_TEST_CONFIG = (
    create_bgp_ebb_scaling_performance_test_config(
        EB02_LAB_ASH6,
        name="EB02-ARISTA_PERFORMANCE_SCALING_TEST_1_1000_IBGP_PEERS",
        egress_peer_counts=[500],
    )
)


# ─── EB02 -- perf-scaling case 3: transient memory route scale ────────────
EB02_ARISTA_PERFORMANCE_SCALING_TEST_3_ROUTE_SCALE_TEST_CONFIG = (
    create_bgp_ebb_scaling_transient_memory_route_scale_test_config(
        EB02_LAB_ASH6,
        name="EB02-ARISTA_PERFORMANCE_SCALING_TEST_3_ROUTE_SCALE",
    )
)


# ─── EB02 -- perf-scaling case 4: transient memory peer scale ─────────────
EB02_ARISTA_PERFORMANCE_SCALING_TEST_4_PEER_SCALE_TEST_CONFIG = (
    create_bgp_ebb_scaling_transient_memory_peer_scale_test_config(
        EB02_LAB_ASH6,
        name="EB02-ARISTA_PERFORMANCE_SCALING_TEST_4_PEER_SCALE",
    )
)


# ─── EB02 -- perf-scaling case 6: route churn prefix scaling ──────────────
EB02_ARISTA_PERFORMANCE_SCALING_TEST_6_ROUTE_CHURN_TEST_CONFIG = (
    create_bgp_ebb_scaling_route_churn_prefix_test_config(
        EB02_LAB_ASH6,
        name="EB02-ARISTA_PERFORMANCE_SCALING_TEST_6_ROUTE_CHURN",
        soak_duration_seconds=180,
    )
)


# ─── EB02 -- perf-scaling case 9: bounded ECMP sets ───────────────────────
EB02_ARISTA_PERFORMANCE_SCALING_TEST_9_BOUNDED_ECMP_SETS_TEST_CONFIG = (
    create_bgp_ebb_scaling_bounded_ecmp_sets_test_config(
        EB02_LAB_ASH6,
        name="EB02-ARISTA_PERFORMANCE_SCALING_TEST_9_BOUNDED_ECMP_SETS",
    )
)


# ─── EB03 -- perf-scaling case 2: constant attribute storage ──────────────
# Uses the ``test_config_constant_attribute_storage_on_eos`` helper (absorbed
# into ``factories/bgp_ebb_characteristic.py`` by Wave 5D.1). Binding
# preserves every arg passed by the legacy
# ``eb03_arista_performance_scaling_test_2_test_config.py`` wrapper so the
# golden manifest hash is byte-wise identical.
_EB03_LAB_DEVICE_PASSWORD = os.environ.get(
    "TAAC_EBB_LAB_DEVICE_PASSWORD",
    "dnepit",  # pragma: allowlist secret
)

EB03_ARISTA_PERFORMANCE_SCALING_TEST_2_TEST_CONFIG = (
    test_config_constant_attribute_storage_on_eos(
        test_config_name="EB03_ARISTA_PERFORMANCE_SCALING_TEST_2",
        device_name=EB03_LAB_ASH6.device_name,
        ixia_interface_mimic_ebgp=EB03_LAB_ASH6.ixia_ports[0][0],
        ebgp_remote_as=65334,
        ixia_ebgp_ic_parent_network_v6="2401:db00:e50d:11:8",
        ixia_ebgp_ic_parent_network_v4="10.163.28",
        ebgp_peer_counts=[128],
        constant_total_paths=800000,
        soak_time_minutes=1,
        host_driver_args={
            EB03_LAB_ASH6.device_name: json.dumps(
                {"username": "admin", "password": _EB03_LAB_DEVICE_PASSWORD}
            ),
        },
        oss_mock_device_data={
            EB03_LAB_ASH6.device_name: taac_types.MockDeviceInfo(
                name=EB03_LAB_ASH6.device_name,
                hardware="ARISTA_7516",
                role="EB",
                operating_system="EOS",
                dc="ash6",
                region="ash",
                asset_id=12345,
                asic="JERICHO",
                routing_protocol="BGP",
                dc_type="ONE",
                network_area="BACKBONE",
                network_area_type="BACKBONE",
                network_type="EBB",
            ),
        },
        host_os_type_map={
            EB03_LAB_ASH6.device_name: taac_types.DeviceOsType.ARISTA_FBOSS
        },
        direct_ixia_connections=[
            taac_types.DirectIxiaConnection(
                interface=EB03_LAB_ASH6.ixia_ports[0][0],
                ixia_chassis_ip=EB03_LAB_ASH6.ixia_chassis_ip,
                ixia_port=EB03_LAB_ASH6.ixia_ports[0][1],
            ),
        ],
        constant_acceptance_communities=["65529:39744"],
        max_communities_per_route_from_pool=5,
        randomize_attributes=True,
        random_seed=42,
        dump_attribute_assignments=True,
    )
)


__all__ = [
    "EB02_ARISTA_PERFORMANCE_SCALING_TEST_1_1000_IBGP_PEERS_TEST_CONFIG",
    "EB02_ARISTA_PERFORMANCE_SCALING_TEST_1_200_IBGP_PEERS_TEST_CONFIG",
    "EB02_ARISTA_PERFORMANCE_SCALING_TEST_1_400_IBGP_PEERS_TEST_CONFIG",
    "EB02_ARISTA_PERFORMANCE_SCALING_TEST_1_600_IBGP_PEERS_TEST_CONFIG",
    "EB02_ARISTA_PERFORMANCE_SCALING_TEST_1_800_IBGP_PEERS_TEST_CONFIG",
    "EB02_ARISTA_PERFORMANCE_SCALING_TEST_3_ROUTE_SCALE_TEST_CONFIG",
    "EB02_ARISTA_PERFORMANCE_SCALING_TEST_4_PEER_SCALE_TEST_CONFIG",
    "EB02_ARISTA_PERFORMANCE_SCALING_TEST_6_ROUTE_CHURN_TEST_CONFIG",
    "EB02_ARISTA_PERFORMANCE_SCALING_TEST_9_BOUNDED_ECMP_SETS_TEST_CONFIG",
    "EB03_ARISTA_PERFORMANCE_SCALING_TEST_2_TEST_CONFIG",
]
