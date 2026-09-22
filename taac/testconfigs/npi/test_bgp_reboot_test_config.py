# Copyright (c) Meta Platforms, Inc. and affiliates.

import json
import unittest

from taac.testconfigs.npi.bgp_reboot_test_config import (
    _increment_ip_addresses,
    create_npi_bgp_reboot_test_config,
)
from taac.test_as_a_config import types as taac_types


class BgpRebootTestConfigTest(unittest.TestCase):
    def test_increment_ip_addresses_matches_ixia_device_group(self) -> None:
        self.assertEqual(
            _increment_ip_addresses(
                starting_ip="2401:db00:501c::11",
                increment_ip="::2",
                count=20,
            ),
            [f"2401:db00:501c::{suffix:x}" for suffix in range(0x11, 0x38, 2)],
        )

    def test_rsw_splits_ixia_ports_into_explicit_vlans(self) -> None:
        config = create_npi_bgp_reboot_test_config(
            test_config_name="RSW_REBOOT_TEST",
            device_name="rsw001.p001.f01.qzd1",
            device_role="RSW",
            ixia_source_interface="eth1/17/1",
            ixia_destination_interface="eth1/18/1",
            source_dut_ip_v6="2401:db00:501c::10",
            destination_dut_ip_v6="2401:db00:e50d:11:18::10",
            source_ixia_ip_v6="2401:db00:501c::11",
            destination_ixia_ip_v6="2401:db00:e50d:11:18::11",
            peer_prefix_length=127,
            source_advertised_prefix_v6="5000:17::",
            destination_advertised_prefix_v6="5000:18::",
            source_remote_as=65000,
            destination_remote_as=6016,
            source_vlan_id=2000,
            destination_vlan_id=4016,
            device_group_multiplier=20,
        )

        setup_tasks = config.setup_tasks
        assert setup_tasks is not None
        configure_task = next(
            task
            for task in setup_tasks
            if task.task_name == "configure_parallel_bgp_peers"
        )
        configure_task_params = configure_task.params
        assert configure_task_params is not None
        assert configure_task_params.json_params is not None
        configure_params = json.loads(configure_task_params.json_params)
        self.assertEqual(configure_params["shared_vlan_id"], 2000)
        peer_config = json.loads(configure_params["config_json"])
        self.assertEqual(peer_config["eth1/17/1"][0]["vlan_id"], 2000)
        self.assertEqual(peer_config["eth1/18/1"][0]["vlan_id"], 4016)
        self.assertFalse(peer_config["eth1/17/1"][0]["retain_existing_vlan_addresses"])
        self.assertFalse(peer_config["eth1/18/1"][0]["retain_existing_vlan_addresses"])
        self.assertEqual(
            [
                peer_config[interface][0]["remote_as_4_byte"]
                for interface in ("eth1/17/1", "eth1/18/1")
            ],
            [65000, 6016],
        )
        basic_port_configs = config.basic_port_configs
        assert basic_port_configs is not None
        device_group_configs = []
        for port in basic_port_configs:
            configs = port.device_group_configs
            assert configs is not None
            self.assertTrue(configs)
            device_group_configs.append(configs[0])

        self.assertEqual(
            [device_group.multiplier for device_group in device_group_configs],
            [20, 20],
        )
        self.assertEqual(
            [
                peer_config[interface][0]["num_sessions"]
                for interface in ("eth1/17/1", "eth1/18/1")
            ],
            [20, 20],
        )
        starting_ips = []
        gateway_ips = []
        local_asns = []
        for device_group in device_group_configs:
            address_config = device_group.v6_addresses_config
            bgp_config = device_group.v6_bgp_config
            assert address_config is not None
            assert bgp_config is not None
            starting_ips.append(address_config.starting_ip)
            gateway_ips.append(address_config.gateway_starting_ip)
            local_asns.append(bgp_config.local_as_4_bytes)
        self.assertEqual(
            starting_ips,
            ["2401:db00:501c::11", "2401:db00:e50d:11:18::11"],
        )
        self.assertEqual(
            gateway_ips,
            ["2401:db00:501c::10", "2401:db00:e50d:11:18::10"],
        )
        self.assertEqual(local_asns, [65000, 6016])

    def test_builds_all_three_reboot_variants(self) -> None:
        config = create_npi_bgp_reboot_test_config(
            test_config_name="RSW_REBOOT_TEST",
            device_name="rsw001.p001.f01.qzd1",
            device_role="RSW",
            ixia_source_interface="eth1/17/1",
            ixia_destination_interface="eth1/18/1",
            source_dut_ip_v6="2401:db00:501c::10",
            destination_dut_ip_v6="2401:db00:e50d:11:18::10",
            source_ixia_ip_v6="2401:db00:501c::11",
            destination_ixia_ip_v6="2401:db00:e50d:11:18::11",
            peer_prefix_length=127,
            source_advertised_prefix_v6="5000:17::",
            destination_advertised_prefix_v6="5000:18::",
            source_remote_as=65000,
            destination_remote_as=6016,
            source_vlan_id=2000,
            destination_vlan_id=4016,
            device_group_multiplier=20,
        )

        self.assertEqual(
            [playbook.name for playbook in config.playbooks],
            [
                "test_system_reboot_bmc_full",
                "test_system_reboot_bmc_full_stability",
                "test_system_reboot_bmc_microserver",
                "test_system_reboot_bmc_microserver_stability",
                "test_system_reboot_microserver",
                "test_system_reboot_microserver_stability",
            ],
        )
        reboot_playbooks = config.playbooks[::2]
        reboot_triggers = []
        for playbook in reboot_playbooks:
            reboot_input = playbook.stages[0].steps[0].input_json
            assert reboot_input is not None
            reboot_triggers.append(json.loads(reboot_input)["trigger"])
        self.assertEqual(
            reboot_triggers,
            [
                taac_types.SystemRebootTrigger.FULL_SYSTEM_REBOOT,
                taac_types.SystemRebootTrigger.BMC_POWER_RESET,
                taac_types.SystemRebootTrigger.BMC_MICROSERVER_ONLY_RESET,
            ],
        )


if __name__ == "__main__":
    unittest.main()
