# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.
# pyre-unsafe
import json
import unittest
from dataclasses import replace
from unittest.mock import patch

from taac.abstractions.physical_inventory import (
    BAG010_ASH6,
    BAG012_ASH6,
    NRQEB006_ASH6,
    NRQEB007_ASH6,
    NRQEB008_ASH6,
    NRQEB009_ASH6,
)
from taac.abstractions.topologies.bounded_ecmp import (
    BOUNDED_ECMP_PARENT_NETWORKS_IXIA03,
)
from taac.abstractions.topologies.egress_peer_scale import (
    EGRESS_PEER_SCALE_PARENT_NETWORKS,
    EGRESS_PEER_SCALE_PARENT_NETWORKS_IXIA03,
    EGRESS_PEER_SCALE_SWEEP_PEER_COUNTS,
)
from taac.abstractions.topologies.ipv6_update_packing import (
    IPV6_UPDATE_PACKING_PARENT_NETWORKS_IXIA03,
)
from taac.constants import BgpPlusPlusProfile
from taac.testconfigs.routing.factories import (
    bgp_ebb_characteristic as characteristic_factory,
)
from taac.testconfigs.routing.factories.bgp_ebb_characteristic import (
    create_bgp_ebb_characteristic_bounded_ecmp_sc9_test_config,
    create_bgp_ebb_characteristic_constant_attribute_storage_ingress_test_config,
    create_bgp_ebb_characteristic_performance_scaling_test_config,
    create_bgp_ebb_characteristic_transient_memory_route_scale_test_config,
    create_bgp_ebb_update_packing_test_config,
)
from taac.testconfigs.routing.factories.bgp_ebb_scaling import (
    create_bgp_ebb_scaling_performance_test_config,
)
from taac.testconfigs.routing.util.bgp_ebb_setup_tasks import (
    build_bgpcpp_peers_patch_shell_cmds,
    get_update_packing_setup_tasks,
)
from taac.test_as_a_config.types import Params, Task

# The router_id splice fragment written into the in-shell bgpcpp_config merge.
_ROUTER_ID_ASSIGN = "c['router_id']="


def _task_json_params(task) -> dict:
    json_params = task.params.json_params
    if json_params is None:
        raise AssertionError("task must have JSON parameters")
    value = json.loads(json_params)
    if not isinstance(value, dict):
        raise AssertionError("task JSON parameters must be an object")
    return value


def _custom_step_params(config) -> list:
    """Params of every CUSTOM_STEP across the config's playbooks."""
    found = []
    for pb in config.playbooks or []:
        for stage in getattr(pb, "stages", None) or []:
            for step in stage.steps or []:
                step_params = getattr(step, "step_params", None)
                raw = getattr(step_params, "json_params", None) if step_params else None
                if raw:
                    params = json.loads(raw)
                    if params.get("custom_step_name"):
                        found.append(params)
    return found


class PerformanceScalingPhysicalInventoryDrivenTest(unittest.TestCase):
    """The perf-scaling factory is physical-inventory-driven: the TestConfig name derives
    from ``physical_inventory.device_name`` and ``router_id`` is optional so physical inventories that
    rely on the device-default router-id (bag010) work without pinning one."""

    def test_name_derives_from_device(self) -> None:
        # The name is device-derived: {DEVICE}_SC1_EGRESS_PEER_SCALE_TEST. A
        # non-bag010 device (bag012) exercises the derivation independently of
        # the bag010 default.
        config = create_bgp_ebb_characteristic_performance_scaling_test_config(
            BAG012_ASH6
        )
        self.assertEqual(config.name, "BAG012_ASH6_SC1_EGRESS_PEER_SCALE_TEST")

    def test_bag010_builds_without_router_id(self) -> None:
        # bag010 has no router_id — the factory must not require one, and the
        # name must derive from the physical_inventory device_name.
        config = create_bgp_ebb_characteristic_performance_scaling_test_config(
            BAG010_ASH6
        )
        self.assertEqual(config.name, "BAG010_ASH6_SC1_EGRESS_PEER_SCALE_TEST")

    def test_update_group_appends_suffix(self) -> None:
        config = create_bgp_ebb_characteristic_performance_scaling_test_config(
            BAG010_ASH6, enable_update_group=True
        )
        self.assertEqual(
            config.name,
            "BAG010_ASH6_SC1_EGRESS_PEER_SCALE_TEST_UPDATE_GROUP",
        )

    def test_nrqeb006_sc2_uses_primary_ixia03_addresses_and_port(self) -> None:
        config = create_bgp_ebb_characteristic_constant_attribute_storage_ingress_test_config(
            NRQEB006_ASH6,
            enable_update_group=True,
            name_override="NRQEB006_SC2_CONSTANT_ATTRIBUTE_STORAGE_INGRESS_TEST_CONFIG_UG",
            include_direct_ixia_connections=True,
        )

        self.assertEqual(
            "NRQEB006_SC2_CONSTANT_ATTRIBUTE_STORAGE_INGRESS_TEST_CONFIG_UG",
            config.name,
        )
        self.assertEqual(
            ["nrqeb006.ash6:Ethernet3/35/1"],
            [port.endpoint for port in config.basic_port_configs or []],
        )
        dut_endpoints = [endpoint for endpoint in config.endpoints if endpoint.dut]
        self.assertEqual(1, len(dut_endpoints))
        self.assertEqual(
            [
                (
                    "Ethernet3/35/1",
                    "2401:db00:2066:3036::3003",
                    "1/81",
                )
            ],
            [
                (connection.interface, connection.ixia_chassis_ip, connection.ixia_port)
                for connection in dut_endpoints[0].direct_ixia_connections or []
            ],
        )
        self.assertEqual(
            ["2401:db00:e50d:33:8::11"],
            [
                group.v6_addresses_config.starting_ip
                for port in config.basic_port_configs or []
                for group in port.device_group_configs or []
                if group.v6_addresses_config is not None
            ],
        )
        setup_payloads = "\n".join(
            task.params.json_params or "" for task in config.setup_tasks or []
        )
        interface_ip_tasks = [
            _task_json_params(task)
            for task in config.setup_tasks or []
            if task.task_name == "interface_ip_configuration"
        ]
        self.assertEqual(
            [("Ethernet3/35/1", 8)],
            [
                (params["interface"], params["peer_count"])
                for params in interface_ip_tasks
            ],
        )
        self.assertNotIn("Ethernet3/35/2", setup_payloads)
        self.assertNotIn("2401:db00:e50d:33:9", setup_payloads)
        self.assertIn("2401:db00:e50d:33:8", setup_payloads)
        self.assertNotIn("2401:db00:e50d:11:8", setup_payloads)

    def test_sc2_one_ixia_port_reuses_interface_for_zero_peer_helper(self) -> None:
        one_port = replace(
            NRQEB006_ASH6,
            ixia_ports=NRQEB006_ASH6.ixia_ports[:1],
            secondary_ixia_chassis_ip=None,
            secondary_ixia_ports=[],
        )

        config = create_bgp_ebb_characteristic_constant_attribute_storage_ingress_test_config(
            one_port,
            include_direct_ixia_connections=True,
        )

        self.assertEqual(
            ["nrqeb006.ash6:Ethernet3/35/1"],
            [port.endpoint for port in config.basic_port_configs or []],
        )
        interface_ip_tasks = [
            _task_json_params(task)
            for task in config.setup_tasks or []
            if task.task_name == "interface_ip_configuration"
        ]
        self.assertEqual(
            [("Ethernet3/35/1", 8)],
            [
                (params["interface"], params["peer_count"])
                for params in interface_ip_tasks
            ],
        )

    def test_sc2_rejects_parent_networks_for_another_ixia_chassis(self) -> None:
        with self.assertRaisesRegex(ValueError, "do not match IXIA chassis"):
            create_bgp_ebb_characteristic_constant_attribute_storage_ingress_test_config(
                NRQEB006_ASH6,
                parent_networks=EGRESS_PEER_SCALE_PARENT_NETWORKS,
            )

    def test_sc2_empty_parent_networks_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing required keys"):
            create_bgp_ebb_characteristic_constant_attribute_storage_ingress_test_config(
                BAG010_ASH6,
                parent_networks={},
            )

    def test_sc2_explicit_parent_networks_support_unknown_ixia_chassis(self) -> None:
        unknown_chassis = replace(
            BAG010_ASH6,
            primary_ixia_chassis_ip="2401:db00:2066:3036::ffff",
        )

        config = create_bgp_ebb_characteristic_constant_attribute_storage_ingress_test_config(
            unknown_chassis,
            parent_networks=EGRESS_PEER_SCALE_PARENT_NETWORKS,
        )

        self.assertIn(
            EGRESS_PEER_SCALE_PARENT_NETWORKS["ebgp_v6"],
            "\n".join(
                task.params.json_params or "" for task in config.setup_tasks or []
            ),
        )

    def test_sc2_required_keys_are_derived_from_canonical_maps(self) -> None:
        unknown_chassis = replace(
            BAG010_ASH6,
            primary_ixia_chassis_ip="2401:db00:2066:3036::ffff",
        )
        first_canonical_map = {
            **EGRESS_PEER_SCALE_PARENT_NETWORKS,
            "future_first_v6": "2001:db8:fffe:1:1",
        }
        second_canonical_map = {
            **EGRESS_PEER_SCALE_PARENT_NETWORKS,
            "future_second_v6": "2001:db8:ffff:1:1",
        }

        with (
            patch.dict(
                characteristic_factory._EGRESS_PEER_SCALE_PARENT_NETWORKS_BY_CHASSIS,
                {
                    "first-chassis": first_canonical_map,
                    "second-chassis": second_canonical_map,
                },
                clear=True,
            ),
            self.assertRaisesRegex(ValueError, "future_second_v6"),
        ):
            create_bgp_ebb_characteristic_constant_attribute_storage_ingress_test_config(
                unknown_chassis,
                parent_networks=first_canonical_map,
            )

    def test_sc2_unknown_chassis_requires_a_canonical_key_map(self) -> None:
        with (
            patch.dict(
                characteristic_factory._EGRESS_PEER_SCALE_PARENT_NETWORKS_BY_CHASSIS,
                {},
                clear=True,
            ),
            self.assertRaisesRegex(ValueError, "without a canonical IXIA chassis map"),
        ):
            characteristic_factory._resolve_egress_peer_scale_parent_networks(
                EGRESS_PEER_SCALE_PARENT_NETWORKS,
                ixia_chassis_ip="2401:db00:2066:3036::ffff",
            )

    def test_sc2_known_chassis_uses_only_its_canonical_keys(self) -> None:
        legacy_chassis = BAG010_ASH6.primary_ixia_chassis_ip
        extended_other_chassis_map = {
            **EGRESS_PEER_SCALE_PARENT_NETWORKS_IXIA03,
            "future_required": "2001:db8:ffff::",
        }

        with patch.dict(
            characteristic_factory._EGRESS_PEER_SCALE_PARENT_NETWORKS_BY_CHASSIS,
            {
                legacy_chassis: EGRESS_PEER_SCALE_PARENT_NETWORKS,
                "future-chassis": extended_other_chassis_map,
            },
            clear=True,
        ):
            resolved = (
                characteristic_factory._resolve_egress_peer_scale_parent_networks(
                    EGRESS_PEER_SCALE_PARENT_NETWORKS,
                    ixia_chassis_ip=legacy_chassis,
                )
            )

        self.assertEqual(EGRESS_PEER_SCALE_PARENT_NETWORKS, resolved)
        self.assertEqual(sorted(EGRESS_PEER_SCALE_PARENT_NETWORKS), list(resolved))

    def test_sc2_rejects_parent_network_key_without_address_family(self) -> None:
        extended_canonical_map = {
            **EGRESS_PEER_SCALE_PARENT_NETWORKS,
            "future_required": "2001:db8:ffff",
        }

        with (
            patch.dict(
                characteristic_factory._EGRESS_PEER_SCALE_PARENT_NETWORKS_BY_CHASSIS,
                {"future-chassis": extended_canonical_map},
                clear=True,
            ),
            self.assertRaisesRegex(ValueError, "must end in _v4 or _v6"),
        ):
            characteristic_factory._resolve_egress_peer_scale_parent_networks(
                extended_canonical_map,
                ixia_chassis_ip="future-chassis",
            )

    def test_sc2_unknown_chassis_rejects_invalid_parent_network_values(self) -> None:
        unknown_chassis_ip = "2401:db00:2066:3036::ffff"
        for key, invalid_value in (
            ("ebgp_v6", ""),
            ("ebgp_v6", "2001:db8:1"),
            ("ebgp_v4", "not-a-network"),
            ("ibgp_v6", "10.0.0"),
            ("ibgp_v4", "2001:db8"),
        ):
            with (
                self.subTest(key=key, invalid_value=invalid_value),
                self.assertRaisesRegex(ValueError, key),
            ):
                characteristic_factory._resolve_egress_peer_scale_parent_networks(
                    {
                        **EGRESS_PEER_SCALE_PARENT_NETWORKS,
                        key: invalid_value,
                    },
                    ixia_chassis_ip=unknown_chassis_ip,
                )

    def test_sc2_explicit_legacy_parent_networks_do_not_imply_direct_binding(
        self,
    ) -> None:
        config = create_bgp_ebb_characteristic_constant_attribute_storage_ingress_test_config(
            BAG010_ASH6,
            parent_networks={
                **EGRESS_PEER_SCALE_PARENT_NETWORKS,
                "metadata": "ignored",
            },
        )
        dut_endpoints = [endpoint for endpoint in config.endpoints if endpoint.dut]

        self.assertEqual(1, len(dut_endpoints))
        self.assertFalse(dut_endpoints[0].direct_ixia_connections)
        self.assertIn(
            EGRESS_PEER_SCALE_PARENT_NETWORKS["ebgp_v6"],
            "\n".join(
                task.params.json_params or "" for task in config.setup_tasks or []
            ),
        )

    def test_custom_interface_tasks_reject_zero_peer_interface(self) -> None:
        custom_task = Task(
            task_name="interface_ip_configuration",
            params=Params(
                json_params=json.dumps({"interface": "Ethernet2", "peer_count": 4})
            ),
        )

        with self.assertRaisesRegex(ValueError, "positive peer counts"):
            get_update_packing_setup_tasks(
                device_name="dut.example.com",
                bgp_asn=65001,
                ixia_interface_mimic_ebgp="Ethernet1",
                ixia_interface_mimic_ibgp="Ethernet2",
                ebgp_peer_count=8,
                ibgp_peer_count=0,
                ebgp_remote_as=65002,
                ibgp_remote_as=65001,
                ixia_ebgp_ic_parent_network_v6="2001:db8:1::",
                ixia_ibgp_ic_parent_network_v6="2001:db8:2::",
                router_id=None,
                bgpcpp_configerator_path="bgpcpp/config",
                profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
                interface_ip_tasks=[custom_task],
            )

    def test_custom_interface_tasks_validate_params_and_peer_count(self) -> None:
        for task_name, json_params, error_pattern in (
            ("not_interface_ip_configuration", "{}", "contain only"),
            ("interface_ip_configuration", None, "valid JSON object"),
            ("interface_ip_configuration", "not-json", "valid JSON object"),
            ("interface_ip_configuration", "[]", "valid JSON object"),
            (
                "interface_ip_configuration",
                json.dumps({"peer_count": 8}),
                "nonempty interface",
            ),
            (
                "interface_ip_configuration",
                json.dumps({"interface": "Ethernet1"}),
                "positive integer peer_count",
            ),
            (
                "interface_ip_configuration",
                json.dumps({"interface": "Ethernet1", "peer_count": 4}),
                "does not match the topology-derived positive peer counts",
            ),
        ):
            with self.subTest(task_name=task_name, json_params=json_params):
                custom_task = Task(
                    task_name=task_name,
                    params=Params(json_params=json_params),
                )

                with self.assertRaisesRegex(ValueError, error_pattern):
                    get_update_packing_setup_tasks(
                        device_name="dut.example.com",
                        bgp_asn=65001,
                        ixia_interface_mimic_ebgp="Ethernet1",
                        ixia_interface_mimic_ibgp="Ethernet2",
                        ebgp_peer_count=8,
                        ibgp_peer_count=0,
                        ebgp_remote_as=65002,
                        ibgp_remote_as=65001,
                        ixia_ebgp_ic_parent_network_v6="2001:db8:1::",
                        ixia_ibgp_ic_parent_network_v6="2001:db8:2::",
                        router_id=None,
                        bgpcpp_configerator_path="bgpcpp/config",
                        profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
                        interface_ip_tasks=[custom_task],
                    )

    def test_custom_interface_peer_count_error_preserves_role_order(self) -> None:
        custom_task = Task(
            task_name="interface_ip_configuration",
            params=Params(
                json_params=json.dumps({"interface": "Ethernet1", "peer_count": 5})
            ),
        )

        with self.assertRaises(ValueError) as raised:
            get_update_packing_setup_tasks(
                device_name="dut.example.com",
                bgp_asn=65001,
                ixia_interface_mimic_ebgp="Ethernet1",
                ixia_interface_mimic_ibgp="Ethernet1",
                ebgp_peer_count=8,
                ibgp_peer_count=4,
                ebgp_remote_as=65002,
                ibgp_remote_as=65001,
                ixia_ebgp_ic_parent_network_v6="2001:db8:1::",
                ixia_ibgp_ic_parent_network_v6="2001:db8:2::",
                router_id=None,
                bgpcpp_configerator_path="bgpcpp/config",
                profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
                interface_ip_tasks=[custom_task],
            )

        self.assertIn(
            "expected=[('Ethernet1', 8), ('Ethernet1', 4)], actual=5",
            str(raised.exception),
        )

    def test_update_packing_rejects_empty_custom_interface_tasks(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            get_update_packing_setup_tasks(
                device_name="dut.example.com",
                bgp_asn=65001,
                ixia_interface_mimic_ebgp="Ethernet1",
                ixia_interface_mimic_ibgp="Ethernet2",
                ebgp_peer_count=8,
                ibgp_peer_count=0,
                ebgp_remote_as=65002,
                ibgp_remote_as=65001,
                ixia_ebgp_ic_parent_network_v6="2001:db8:1::",
                ixia_ibgp_ic_parent_network_v6="2001:db8:2::",
                router_id=None,
                bgpcpp_configerator_path="bgpcpp/config",
                profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
                interface_ip_tasks=[],
            )

    def test_shared_custom_interface_tasks_cover_both_roles_and_clear_once(
        self,
    ) -> None:
        def task(peer_count: int, clear_existing: bool) -> Task:
            return Task(
                task_name="interface_ip_configuration",
                params=Params(
                    json_params=json.dumps(
                        {
                            "interface": "Ethernet1",
                            "peer_count": peer_count,
                            "clear_existing": clear_existing,
                        }
                    )
                ),
            )

        common_args = {
            "device_name": "dut.example.com",
            "bgp_asn": 65001,
            "ixia_interface_mimic_ebgp": "Ethernet1",
            "ixia_interface_mimic_ibgp": "Ethernet1",
            "ebgp_peer_count": 8,
            "ibgp_peer_count": 4,
            "ebgp_remote_as": 65002,
            "ibgp_remote_as": 65001,
            "ixia_ebgp_ic_parent_network_v6": "2001:db8:1::",
            "ixia_ibgp_ic_parent_network_v6": "2001:db8:2::",
            "router_id": None,
            "bgpcpp_configerator_path": "bgpcpp/config",
            "profile": BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
        }

        with self.assertRaisesRegex(ValueError, "cover every topology-derived"):
            get_update_packing_setup_tasks(
                **common_args,
                interface_ip_tasks=[task(8, True)],
            )
        with self.assertRaisesRegex(
            ValueError, "must clear each IXIA interface exactly once"
        ):
            get_update_packing_setup_tasks(
                **common_args,
                interface_ip_tasks=[task(8, True), task(4, True)],
            )
        with self.assertRaisesRegex(ValueError, "eBGP/iBGP role order"):
            get_update_packing_setup_tasks(
                **common_args,
                interface_ip_tasks=[task(4, True), task(8, False)],
            )

        custom_tasks = [task(8, True), task(4, False)]
        setup_tasks = get_update_packing_setup_tasks(
            **common_args,
            interface_ip_tasks=custom_tasks,
        )
        self.assertEqual(
            custom_tasks,
            [
                setup_task
                for setup_task in setup_tasks
                if setup_task.task_name == "interface_ip_configuration"
            ],
        )

    def test_update_packing_rejects_zero_peers(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one IXIA peer count"):
            get_update_packing_setup_tasks(
                device_name="dut.example.com",
                bgp_asn=65001,
                ixia_interface_mimic_ebgp="Ethernet1",
                ixia_interface_mimic_ibgp="Ethernet2",
                ebgp_peer_count=0,
                ibgp_peer_count=0,
                ebgp_remote_as=65002,
                ibgp_remote_as=65001,
                ixia_ebgp_ic_parent_network_v6="2001:db8:1::",
                ixia_ibgp_ic_parent_network_v6="2001:db8:2::",
                router_id=None,
                bgpcpp_configerator_path="bgpcpp/config",
                profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
            )

    def test_shared_active_interface_is_configured_without_second_clear(self) -> None:
        tasks = get_update_packing_setup_tasks(
            device_name="dut.example.com",
            bgp_asn=65001,
            ixia_interface_mimic_ebgp="Ethernet1",
            ixia_interface_mimic_ibgp="Ethernet1",
            ebgp_peer_count=8,
            ibgp_peer_count=4,
            ebgp_remote_as=65002,
            ibgp_remote_as=65001,
            ixia_ebgp_ic_parent_network_v6="2001:db8:1::",
            ixia_ibgp_ic_parent_network_v6="2001:db8:2::",
            router_id=None,
            bgpcpp_configerator_path="bgpcpp/config",
            profile=BgpPlusPlusProfile.BGP_PLUS_PLUS_WITHOUT_OPEN_R,
        )

        interface_ip_tasks = [
            _task_json_params(task)
            for task in tasks
            if task.task_name == "interface_ip_configuration"
        ]
        self.assertEqual(
            [("Ethernet1", True), ("Ethernet1", False)],
            [
                (params["interface"], params["clear_existing"])
                for params in interface_ip_tasks
            ],
        )
        setup_payloads = "\n".join(task.params.json_params or "" for task in tasks)
        self.assertEqual(1, setup_payloads.count("description IXIA_MIMIC_EBGP"))
        self.assertIn("description IXIA_MIMIC_EBGP_IBGP", setup_payloads)

    def test_nrqeb007_sc3_uses_primary_ixia03_addresses_and_ports(self) -> None:
        config = create_bgp_ebb_characteristic_transient_memory_route_scale_test_config(
            NRQEB007_ASH6,
            enable_update_group=True,
            name_override="NRQEB007_SC3_TRANSIENT_MEMORY_ROUTE_SCALE_TEST_CONFIG_UG",
            parent_networks=EGRESS_PEER_SCALE_PARENT_NETWORKS_IXIA03,
            include_direct_ixia_connections=True,
        )

        self.assertEqual(
            "NRQEB007_SC3_TRANSIENT_MEMORY_ROUTE_SCALE_TEST_CONFIG_UG",
            config.name,
        )
        self.assertEqual(
            [
                "nrqeb007.ash6:Ethernet3/35/1",
                "nrqeb007.ash6:Ethernet3/35/2",
            ],
            [port.endpoint for port in config.basic_port_configs or []],
        )
        self.assertEqual(
            [
                ("Ethernet3/35/1", "2401:db00:2066:3036::3003", "1/85"),
                ("Ethernet3/35/2", "2401:db00:2066:3036::3003", "1/86"),
            ],
            [
                (connection.interface, connection.ixia_chassis_ip, connection.ixia_port)
                for connection in config.endpoints[0].direct_ixia_connections or []
            ],
        )
        address_starts = {
            address.starting_ip
            for port in config.basic_port_configs or []
            for group in port.device_group_configs or []
            for address in (
                group.v4_addresses_config,
                group.v6_addresses_config,
            )
            if address is not None
        }
        self.assertEqual(
            {
                "10.180.28.11",
                "10.181.28.11",
                "2401:db00:e50d:33:8::11",
                "2401:db00:e50d:33:9::11",
            },
            address_starts,
        )

    def test_sc3_rejects_parent_networks_for_different_ixia_chassis(self) -> None:
        with self.assertRaisesRegex(ValueError, "do not match IXIA chassis"):
            create_bgp_ebb_characteristic_transient_memory_route_scale_test_config(
                BAG010_ASH6,
                parent_networks=EGRESS_PEER_SCALE_PARENT_NETWORKS_IXIA03,
            )

    def test_nrqeb008_sc1_uses_primary_ixia03_addresses_and_ports(self) -> None:
        config = create_bgp_ebb_characteristic_performance_scaling_test_config(
            NRQEB008_ASH6,
            enable_update_group=True,
            name_override="NRQEB008_SC1_EGRESS_PEER_SCALE_TEST_CONFIG_UG",
            parent_networks=EGRESS_PEER_SCALE_PARENT_NETWORKS_IXIA03,
        )

        self.assertEqual(
            "NRQEB008_SC1_EGRESS_PEER_SCALE_TEST_CONFIG_UG",
            config.name,
        )
        self.assertEqual(
            [
                ("Ethernet3/35/1", "2401:db00:2066:3036::3003", "1/89"),
                ("Ethernet3/35/2", "2401:db00:2066:3036::3003", "1/90"),
            ],
            [
                (connection.interface, connection.ixia_chassis_ip, connection.ixia_port)
                for connection in config.endpoints[0].direct_ixia_connections or []
            ],
        )
        address_starts = {
            address.starting_ip
            for port in config.basic_port_configs or []
            for group in port.device_group_configs or []
            for address in (
                group.v4_addresses_config,
                group.v6_addresses_config,
            )
            if address is not None
        }
        self.assertEqual(
            {
                "10.180.28.11",
                "10.181.28.11",
                "2401:db00:e50d:33:8::11",
                "2401:db00:e50d:33:9::11",
            },
            address_starts,
        )

    def test_sc1_requires_complete_dual_stack_parent_network_map(self) -> None:
        cases = (
            (BAG012_ASH6, EGRESS_PEER_SCALE_PARENT_NETWORKS),
            (NRQEB008_ASH6, EGRESS_PEER_SCALE_PARENT_NETWORKS_IXIA03),
        )
        required_keys = ("ebgp_v4", "ebgp_v6", "ibgp_v4", "ibgp_v6")

        for inventory, complete_networks in cases:
            for missing_key in required_keys:
                with self.subTest(
                    device=inventory.device_name,
                    missing_key=missing_key,
                ):
                    incomplete_networks = dict(complete_networks)
                    del incomplete_networks[missing_key]
                    with self.assertRaisesRegex(ValueError, missing_key):
                        create_bgp_ebb_characteristic_performance_scaling_test_config(
                            inventory,
                            parent_networks=incomplete_networks,
                        )

    def test_nrqeb009_sc9_uses_primary_ixia03_addresses_and_ports(self) -> None:
        config = create_bgp_ebb_characteristic_bounded_ecmp_sc9_test_config(
            NRQEB009_ASH6,
            enable_update_group=True,
            name_override="NRQEB009_SC9_BOUNDED_ECMP_SETS_TEST_CONFIG_UG",
            parent_networks=BOUNDED_ECMP_PARENT_NETWORKS_IXIA03,
        )

        self.assertEqual(
            "NRQEB009_SC9_BOUNDED_ECMP_SETS_TEST_CONFIG_UG",
            config.name,
        )
        self.assertEqual(
            ["nrqeb009.ash6"],
            [endpoint.name for endpoint in config.endpoints if endpoint.dut],
        )
        self.assertEqual(
            [
                ("Ethernet3/35/1", "2401:db00:2066:3036::3003", "1/93"),
                ("Ethernet3/35/2", "2401:db00:2066:3036::3003", "1/94"),
            ],
            [
                (connection.interface, connection.ixia_chassis_ip, connection.ixia_port)
                for connection in config.endpoints[0].direct_ixia_connections or []
            ],
        )
        address_starts = {
            address.starting_ip
            for port in config.basic_port_configs or []
            for group in port.device_group_configs or []
            for address in (
                group.v4_addresses_config,
                group.v6_addresses_config,
            )
            if address is not None
        }
        self.assertEqual(
            {
                "10.180.28.11",
                "10.180.28.95",
                "10.180.28.179",
                "10.181.28.11",
                "2401:db00:e50d:33:8::11",
                "2401:db00:e50d:33:8::65",
                "2401:db00:e50d:33:8::b9",
                "2401:db00:e50d:33:9::11",
            },
            address_starts,
        )

    def test_update_packing_conveyor_config_is_ug_and_non_vacuous(self) -> None:
        config = create_bgp_ebb_update_packing_test_config(
            NRQEB008_ASH6,
            enable_update_group=True,
            name_override="NRQEB008_SC5_UPDATE_PACKING_TEST_CONFIG_UG",
            min_advertised_nlri=50000,
            parent_networks=IPV6_UPDATE_PACKING_PARENT_NETWORKS_IXIA03,
        )

        self.assertEqual("NRQEB008_SC5_UPDATE_PACKING_TEST_CONFIG_UG", config.name)
        self.assertEqual(
            ["bgp_ebb_update_packing_playbook"],
            [playbook.name for playbook in config.playbooks or []],
        )
        update_group_validators = [
            _task_json_params(task)
            for task in config.setup_tasks or []
            if task.task_name == "validate_bgpcpp_update_group_state"
        ]
        self.assertEqual(
            [{"hostname": "nrqeb008.ash6", "expect_enabled": True}],
            update_group_validators,
        )
        startup_flags = [
            _task_json_params(task)["flags"]
            for task in config.setup_tasks or []
            if task.task_name == "configure_bgpcpp_startup"
        ]
        self.assertEqual(
            [{"bgp_resolve_nexthops_from_interface_state": "true"}],
            startup_flags,
        )
        lifecycle_tasks = [
            *(config.setup_tasks or []),
            *(config.teardown_tasks or []),
        ]
        self.assertFalse(
            any(
                "bag013.ash6" in (task.params.json_params or "")
                for task in lifecycle_tasks
            ),
            "the no-OpenR Conveyor binding must not mutate a helper device",
        )
        self.assertNotIn(
            "openr_route_action",
            [task.task_name for task in lifecycle_tasks],
        )
        direct_connections = config.endpoints[0].direct_ixia_connections or []
        self.assertEqual(
            [
                (
                    "Ethernet3/35/1",
                    "2401:db00:2066:3036::3003",
                    "1/89",
                ),
                (
                    "Ethernet3/35/2",
                    "2401:db00:2066:3036::3003",
                    "1/90",
                ),
            ],
            [
                (connection.interface, connection.ixia_chassis_ip, connection.ixia_port)
                for connection in direct_connections
            ],
        )
        self.assertEqual(
            {
                "2401:db00:e50d:33:8::11",
                "2401:db00:e50d:33:9::11",
            },
            {
                group.v6_addresses_config.starting_ip
                for port in config.basic_port_configs or []
                for group in port.device_group_configs or []
                if group.v6_addresses_config is not None
            },
        )
        packing_steps = [
            params
            for params in _custom_step_params(config)
            if params.get("custom_step_name")
            == "test_bgp_update_packing_eos_bgp_plus_plus"
        ]
        self.assertEqual(1, len(packing_steps))
        self.assertEqual(50000, packing_steps[0].get("min_advertised_nlri"))

    def test_explicit_empty_ixia_overrides_are_preserved(self) -> None:
        config = create_bgp_ebb_scaling_performance_test_config(
            BAG010_ASH6,
            name="EMPTY_IXIA_OVERRIDES",
            egress_peer_counts=[1],
            endpoints=[],
            basic_port_configs=[],
        )

        self.assertEqual([], config.endpoints)
        self.assertEqual([], config.basic_port_configs)

    def test_router_id_spliced_when_present(self) -> None:
        # A real router_id is written into /mnt/flash/bgpcpp_config verbatim
        # (unchanged from the legacy behavior).
        merge = build_bgpcpp_peers_patch_shell_cmds(peers=[], router_id="10.163.28.11")[
            -1
        ]
        self.assertIn("c['router_id']='10.163.28.11'; ", merge)

    def test_router_id_preserved_when_none(self) -> None:
        # router_id=None must NOT emit a router_id assignment (preserve the
        # deployed config's router_id) and must never splice the literal
        # string 'None' into the device config.
        merge = build_bgpcpp_peers_patch_shell_cmds(peers=[], router_id=None)[-1]
        self.assertNotIn(_ROUTER_ID_ASSIGN, merge)
        self.assertNotIn("None", merge)


class PerformanceScalingInterfaceIpCoverageTest(unittest.TestCase):
    """The iBGP interface must carry secondary source-IPs for the FULL sweep.

    The per-iteration rescale rewrites only the bgpcpp peer list, never the
    interface IPs. The canonical interface plan must provision the maximum
    resolved peer set once so every sweep stage can establish.
    """

    def _ibgp_interface_ip_peer_counts(self, config) -> list:
        ibgp_iface = BAG010_ASH6.ixia_ports[1][0]
        counts = []
        for task in config.setup_tasks or []:
            if task.task_name != "interface_ip_configuration":
                continue
            params = _task_json_params(task)
            if params["interface"] == ibgp_iface:
                counts.append(params["peer_count"])
        return counts

    def test_ibgp_interface_covers_full_sweep(self) -> None:
        config = create_bgp_ebb_characteristic_performance_scaling_test_config(
            BAG010_ASH6
        )
        counts = self._ibgp_interface_ip_peer_counts(config)
        self.assertEqual(
            [max(EGRESS_PEER_SCALE_SWEEP_PEER_COUNTS)],
            counts,
            "the canonical interface plan must render the iBGP source-address "
            f"set exactly once; got peer_counts={counts}",
        )


class PerformanceScalingNexthopResolutionGflagTest(unittest.TestCase):
    """The perf-scaling test runs WITHOUT_OPEN_R, so directly-connected egress
    nexthops resolve only when bgp_resolve_nexthops_from_interface_state is set
    in run_bgpcpp.sh. The factory must wire a managed-shell configure-startup
    task that enables it; otherwise nexthops stay unresolved (no path selected)
    and convergence completes vacuously.
    """

    def _configure_startup_params(self, config) -> list:
        params = []
        for task in config.setup_tasks or []:
            if task.task_name != "configure_bgpcpp_startup":
                continue
            params.append(_task_json_params(task))
        return params

    def test_nexthop_resolution_gflag_enabled_via_managed_shell(self) -> None:
        config = create_bgp_ebb_characteristic_performance_scaling_test_config(
            BAG010_ASH6
        )
        matching = [
            p
            for p in self._configure_startup_params(config)
            if p.get("flags", {}).get("bgp_resolve_nexthops_from_interface_state")
            == "true"
        ]
        self.assertEqual(
            len(matching),
            1,
            "exactly one configure_bgpcpp_startup task must enable "
            "bgp_resolve_nexthops_from_interface_state",
        )
        self.assertTrue(
            matching[0].get("use_managed_shell"),
            "the nexthop-resolution gflag task must run over the managed shell "
            "(perf-scaling passes no SSH credentials)",
        )

    def test_no_openr_ingress_only_config_uses_same_mode_invariant(self) -> None:
        config = create_bgp_ebb_characteristic_constant_attribute_storage_ingress_test_config(
            BAG010_ASH6,
            enable_update_group=True,
        )
        matching = [
            params
            for params in self._configure_startup_params(config)
            if params.get("flags", {}).get("bgp_resolve_nexthops_from_interface_state")
            == "true"
        ]
        self.assertEqual(1, len(matching))
        self.assertTrue(matching[0].get("use_managed_shell"))

        flag_indices = [
            index
            for index, task in enumerate(config.setup_tasks or [])
            if task.task_name == "configure_bgpcpp_startup"
            and _task_json_params(task)
            .get("flags", {})
            .get("bgp_resolve_nexthops_from_interface_state")
            == "true"
        ]
        bgp_enable_indices = [
            index
            for index, task in enumerate(config.setup_tasks or [])
            if task.task_name == "arista_daemon_control"
            and _task_json_params(task).get("daemon_name") == "Bgp"
            and _task_json_params(task).get("action") == "enable"
        ]
        self.assertEqual(1, len(flag_indices))
        self.assertGreater(len(bgp_enable_indices), 0)
        self.assertLess(flag_indices[0], bgp_enable_indices[0])

    def test_ingress_only_config_also_resolves_nexthops(self) -> None:
        """SC2 must resolve next-hops too, and be ingress-only for a different
        reason.

        char-2 measures attribute storage in a REAL, best-path selected RIB;
        leaving next-hops unresolvable would measure a different (and easier)
        thing to store, and forces the acceptance gate down to counting RECEIVED
        rather than accepted-and-resolved. Selection state does not distort
        sc2_memory_growth either -- the path count is fixed at 800K across the
        sweep, so it is a constant additive term, not a growth term.

        Ingress-only comes from configuring NO egress peer, which the sibling
        test below pins.
        """
        config = create_bgp_ebb_characteristic_constant_attribute_storage_ingress_test_config(
            BAG010_ASH6,
            enable_update_group=True,
        )
        enabling = [
            params
            for params in self._configure_startup_params(config)
            if params.get("flags", {}).get("bgp_resolve_nexthops_from_interface_state")
            == "true"
        ]
        self.assertEqual(
            1,
            len(enabling),
            "SC2 measures a resolved RIB; exactly one setup task must enable "
            "bgp_resolve_nexthops_from_interface_state",
        )

    def test_update_group_state_uses_thrift_after_final_bgp_restart(self) -> None:
        config = create_bgp_ebb_characteristic_constant_attribute_storage_ingress_test_config(
            BAG010_ASH6,
            enable_update_group=True,
        )
        tasks = config.setup_tasks or []
        validators = [
            (index, _task_json_params(task))
            for index, task in enumerate(tasks)
            if task.task_name == "validate_bgpcpp_update_group_state"
        ]
        bgp_enable_indices = [
            index
            for index, task in enumerate(tasks)
            if task.task_name == "arista_daemon_control"
            and _task_json_params(task).get("daemon_name") == "Bgp"
            and _task_json_params(task).get("action") == "enable"
        ]
        shell_commands = [
            command
            for task in tasks
            if task.task_name == "run_commands_on_shell"
            for command in _task_json_params(task).get("cmds", [])
        ]

        self.assertEqual(1, len(validators))
        self.assertEqual(
            {
                "hostname": BAG010_ASH6.device_name,
                "expect_enabled": True,
            },
            validators[0][1],
        )
        self.assertGreater(validators[0][0], max(bgp_enable_indices))
        self.assertFalse(
            any("show bgpcpp update-group" in command for command in shell_commands)
        )

    def test_ingress_only_comes_from_having_no_egress_peer(self) -> None:
        """The property that actually makes SC2 ingress-only.

        With next-hops resolving, nothing stops advertisement except the absence
        of an egress peer -- so pin it. Note BGP++ does NOT suppress eBGP->eBGP
        under update-group (``AdjRibOutGroup::canAnnounceForGroup`` returns true
        for eBGP without consulting ``suppressLoopedAdvertisements``), so the
        iBGP peer count reaching zero is what keeps the DUT silent.
        """
        config = create_bgp_ebb_characteristic_constant_attribute_storage_ingress_test_config(
            BAG010_ASH6,
            enable_update_group=True,
        )
        sweep_steps = [
            params
            for params in _custom_step_params(config)
            if "unique_combination_counts" in params
        ]
        self.assertEqual(
            1, len(sweep_steps), "expected exactly one combination-sweep step"
        )
        self.assertEqual(
            0,
            sweep_steps[0].get("constant_ibgp_peer_count"),
            "SC2 is ingress-only by configuring no iBGP egress peer",
        )


class ConstantAttributeStorageIngressAttributeDumpTest(unittest.TestCase):
    """SC2 must not run the per-iteration attribute dump/verify work.

    ``dump_attribute_assignments`` enables two things inside the sweep step, and
    the first one corrupts the measurement SC2 exists to make:

      * Step 9 (``dump_and_verify_rib_attributes``) pulls the entire 800K-path
        RIB over thrift out of ``bgpd_main`` once per sweep point. The sweep
        deliberately never restarts BGP between iterations, so the RSS churned
        serving that dump carries into the NEXT point's stable-memory sample --
        the exact quantity the blocking ``sc2_memory_growth`` gate compares.
      * Step 1's combination file-dump writes ~180MB to the runner's /tmp over
        the sweep, uploads nowhere, and emits four files that are prefixes of
        one another.

    Neither is part of a scale-characteristic measurement, so the flag stays off.
    """

    def test_attribute_dump_disabled(self) -> None:
        config = create_bgp_ebb_characteristic_constant_attribute_storage_ingress_test_config(
            BAG010_ASH6,
            enable_update_group=True,
        )
        sweep_steps = [
            params
            for params in _custom_step_params(config)
            if "unique_combination_counts" in params
        ]
        self.assertEqual(
            1, len(sweep_steps), "expected exactly one combination-sweep step"
        )
        # Assert the key is present rather than relying on a .get() default: if
        # it is ever renamed, this test must fail loudly instead of passing on a
        # missing-key fallback that happens to be False.
        self.assertIn("dump_attribute_assignments", sweep_steps[0])
        self.assertFalse(
            sweep_steps[0]["dump_attribute_assignments"],
            "SC2 is a scale-characteristic measurement; the RIB attribute "
            "dump/verify perturbs bgpd_main RSS across sweep points",
        )


class PerformanceScalingRouteFilterClearTest(unittest.TestCase):
    """This test injects arbitrary scale prefixes that are not in the device's
    baked-in route registry, so the Centralized Route Filter (CRF) must be
    cleared -- otherwise all but the registered handful are denied at ingress
    ("Denied by Route Filter Policy")."""

    def test_route_filter_cleared(self) -> None:
        config = create_bgp_ebb_characteristic_performance_scaling_test_config(
            BAG010_ASH6
        )
        clear_tasks = [
            task
            for task in (config.setup_tasks or [])
            if task.task_name == "bgp_clear_route_filter"
        ]
        self.assertEqual(
            len(clear_tasks),
            1,
            "exactly one bgp_clear_route_filter task must be wired so injected "
            "prefixes are not blocked by the route registry",
        )
