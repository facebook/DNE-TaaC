# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Unit tests for the RBB SRv6 scenario builders and TestConfig factory.

Lives under ``taac/playbooks/routing/tests`` (not ``taac/testconfigs/routing/
tests``) because the OSS pytest harness never recurses into any ``testconfigs``
directory (``pyproject.toml`` ``norecursedirs``); placing the file here is what
actually gets it run. The factory/scenario modules under test are imported by
absolute path, so their real home under ``taac/testconfigs`` is unaffected.
"""

import ipaddress
import json
import os
import re
import unittest
from dataclasses import replace
from unittest import mock

from ixia.ixia import types as ixia_types
from taac.testconfigs.routing.factories.qual_rbb.rbb_srv6_test_config import (
    _validate_traffic_route_contract,
    create_rbb_srv6_3_usids_test_config,
)
from taac.testconfigs.routing.util import bgp_rbb_constants as C
from taac.testconfigs.routing.util.bgp_rbb_scenario_profiles import (
    srv6_decap_counter_spec,
    srv6_encap_counter_spec,
    SRV6_3_USIDS_PROFILE,
    verify_core_links_up_spec,
    verify_openr_adjacency_spec,
    verify_pc162_global_ipv6_spec,
    verify_peer_loopback_learned_spec,
    verify_route_owner_bgpd_spec,
    verify_route_owner_te_agent_spec,
    verify_srv6_tunnels_spec,
)
from taac.testconfigs.routing.util.bgp_rbb_topology import load_rbb_topology


# A deterministic, generic (documentation-only) topology: force the CSV-absent
# fallback with an explicit nonexistent path so these assertions never depend on
# ambient TAAC_CIRCUIT_INFO_PATH / a lab profile being present in the env.
def _generic_topology():
    with mock.patch.dict(os.environ, {"TAAC_CIRCUIT_INFO_PATH": ""}):
        return load_rbb_topology()


class ScenarioBuilderTest(unittest.TestCase):
    def test_final_usid_is_the_effective_decap_sid(self) -> None:
        self.assertEqual(
            SRV6_3_USIDS_PROFILE.usids[-1],
            SRV6_3_USIDS_PROFILE.decap_sid,
        )

    def test_verify_specs_assert_route_ownership_transition(self) -> None:
        te = verify_route_owner_te_agent_spec(SRV6_3_USIDS_PROFILE)
        self.assertIn(C.ROUTE_OWNER_TE_AGENT, te["expect_contains"])
        self.assertIn(SRV6_3_USIDS_PROFILE.decap_sid, te["expect_contains"])
        self.assertIn(
            C.pack_usid_container(
                SRV6_3_USIDS_PROFILE.locator,
                SRV6_3_USIDS_PROFILE.encap_usids,
            ),
            te["expect_contains"],
        )
        self.assertNotIn(
            C.pack_usid_container(
                SRV6_3_USIDS_PROFILE.locator, SRV6_3_USIDS_PROFILE.usids
            ),
            te["expect_contains"],
        )
        # show_cmd greps the tail prefix's route-details block. The slash in the
        # prefix is escaped for the sed address regex (203.0.113.0\/24), so assert
        # on the network-address portion, which appears verbatim.
        self.assertIn(
            SRV6_3_USIDS_PROFILE.tail_prefix.split("/")[0], te["show_cmd"]
        )
        bgpd = verify_route_owner_bgpd_spec(SRV6_3_USIDS_PROFILE)
        self.assertIn(C.ROUTE_OWNER_BGPD, bgpd["expect_contains"])
        self.assertIn(C.ROUTE_OWNER_TE_AGENT, bgpd["expect_absent"])

    def test_verify_tunnels_asserts_full_sids_and_behaviors(self) -> None:
        # The CLI renders full MySID prefixes, not decimal agent-config map keys.
        r1 = verify_srv6_tunnels_spec("r1", SRV6_3_USIDS_PROFILE)
        self.assertEqual(r1["show_cmd"], "fboss2 show mysid")
        self.assertIn(SRV6_3_USIDS_PROFILE.locator_token, r1["expect_contains"])
        self.assertIn(SRV6_3_USIDS_PROFILE.usid_head, r1["expect_contains"])
        self.assertIn(C.SRV6_BEHAVIOR_ADJACENCY, r1["expect_contains"])
        self.assertNotIn(C.SRV6_BEHAVIOR_DECAP, r1["expect_contains"])
        # The tail (R2) additionally terminates: decap behavior asserted.
        r2 = verify_srv6_tunnels_spec("r2", SRV6_3_USIDS_PROFILE)
        self.assertIn(SRV6_3_USIDS_PROFILE.usid_mid, r2["expect_contains"])
        self.assertIn(SRV6_3_USIDS_PROFILE.decap_sid, r2["expect_contains"])
        self.assertIn(C.SRV6_BEHAVIOR_DECAP, r2["expect_contains"])

    def test_verify_pc_rif_spec_checks_interface_address(self) -> None:
        topo = _generic_topology()
        spec = verify_pc162_global_ipv6_spec("r2", topo, rif_token="db8:core")
        self.assertEqual(spec["show_cmd"], "fboss2 show interface eth1/2")
        self.assertEqual(spec["expect_contains"], ["db8:core"])

    def test_verify_pc_rif_derives_selected_core_address(self) -> None:
        topo = _generic_topology()
        with mock.patch.object(C, "PC162_RIF_TOKEN", ""):
            spec = verify_pc162_global_ipv6_spec("r1", topo)
        self.assertEqual(
            spec["expect_contains"],
            [str(ipaddress.ip_interface(C.core_rif_cidr("r1", 1, 6)).ip)],
        )

    def test_core_links_up_spec_asserts_members(self) -> None:
        # S02-S05 is a REAL link-up assertion: PC show name + every member.
        topo = _generic_topology()
        spec = verify_core_links_up_spec("r1", topo)
        self.assertEqual(spec["show_cmd"], "fboss2 show aggregate-port")
        for pc in topo.r1.core_pcs:
            self.assertIn(pc.show_name, spec["expect_contains"])
            for member in pc.members:
                self.assertIn(member, spec["expect_contains"])
                self.assertIn(member, spec["interfaces_up"])

    def test_peer_loopback_spec_targets_other_node(self) -> None:
        # S07: R1 asserts R2's loopback (router-id) and vice versa.
        r1 = verify_peer_loopback_learned_spec("r1")
        self.assertIn(C.R2_ROUTER_ID, r1["expect_contains"])
        r2 = verify_peer_loopback_learned_spec("r2")
        self.assertIn(C.R1_ROUTER_ID, r2["expect_contains"])

    def test_openr_adjacency_spec_asserts_openr_client_on_peer_lo(self) -> None:
        # S06/S13 default path: peer loopback carries an OPENR route client
        # (fboss2 read; the shipped OpenR HCs are NotImplemented in OSS).
        r1 = verify_openr_adjacency_spec("r1")
        self.assertIn("OPENR", r1["expect_contains"])
        self.assertIn(C.R2_ROUTER_ID, r1["expect_contains"])
        self.assertIn(re.escape(C.R2_ROUTER_ID), r1["show_cmd"])
        r2 = verify_openr_adjacency_spec("r2")
        self.assertIn(C.R1_ROUTER_ID, r2["expect_contains"])

    def test_counter_specs_carry_cmd_and_regex(self) -> None:
        # S25 encap (R1) / decap (R2) counter-delta specs.
        topo = _generic_topology()
        enc = srv6_encap_counter_spec("r1", topo)
        self.assertEqual(enc["direction"], "encap")
        self.assertTrue(enc["counter_cmd"])
        self.assertTrue(enc["counter_regex"])
        dec = srv6_decap_counter_spec("r2", topo)
        self.assertEqual(dec["direction"], "decap")
        self.assertTrue(dec["counter_cmd"])
        self.assertTrue(dec["counter_regex"])


class GenericDefaultsTest(unittest.TestCase):
    """The committed constants must carry only generic documentation values."""

    def test_srv6_defaults_are_documentation_range(self) -> None:
        # RFC 3849 (2001:db8::/32) locator + uSIDs, no operator block committed.
        self.assertTrue(C.SRV6_LOCATOR.startswith("2001:db8:"))
        for usid in (C.SRV6_USID_HEAD, C.SRV6_USID_MID, C.SRV6_USID_TAIL):
            self.assertTrue(usid.startswith("2001:db8:"))

    def test_tail_prefix_default_is_documentation_range(self) -> None:
        # The generic direct route is the exact first IXIA tail prefix.
        self.assertEqual(
            C.TAIL_DEST_PREFIX,
            f"{C.IXIA_TAIL_ADVERTISED_PREFIX}/"
            f"{C.IXIA_TAIL_ADVERTISED_PREFIX_LEN}",
        )

    def test_ixia_edge_defaults_are_documentation_range(self) -> None:
        # IXIA edge emulation addresses/pools default to RFC 3849 doc range —
        # nothing lab-specific committed (real values via the lab profile).
        for addr in (
            C.IXIA_R1_EDGE_V6,
            C.IXIA_R2_EDGE_V6,
            C.IXIA_TAIL_ADVERTISED_PREFIX,
        ):
            self.assertTrue(addr.startswith("2001:db8:"))

    def test_edge_ebgp_off_by_default(self) -> None:
        # DUT-side edge eBGP is opt-in (non-destructive default).
        self.assertFalse(C.EDGE_EBGP_ENABLED)

    def test_dut_bootstrap_off_by_default(self) -> None:
        self.assertFalse(C.SETUP_DUTS_ENABLED)

    def test_traffic_off_by_default(self) -> None:
        self.assertFalse(C.INCLUDE_TRAFFIC)

    def test_locator_token_derived_from_locator(self) -> None:
        self.assertEqual(C.locator_token("2001:db8:6::/48"), "2001:db8:6:")
        self.assertEqual(
            C.locator_token("2001:db8:6:1234::/48"), "2001:db8:6:"
        )
        # The committed token matches the committed (generic) locator.
        self.assertEqual(C.SRV6_LOCATOR_TOKEN, C.locator_token(C.SRV6_LOCATOR))

    def test_usid_helpers_reject_unaligned_locator(self) -> None:
        with self.assertRaisesRegex(ValueError, "aligned"):
            C.default_usid("2001:db8::/33", 1)

    def test_pack_three_usids_into_one_segment_container(self) -> None:
        self.assertEqual(
            C.pack_usid_container(
                "2001:db8::/32",
                (
                    "2001:db8:27cc::",
                    "2001:db8:27d6::",
                    "2001:db8:7fff::",
                ),
            ),
            "2001:db8:27cc:27d6:7fff::",
        )

    def test_pack_usids_rejects_ambiguous_or_foreign_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "one 16-bit function"):
            C.pack_usid_container(
                "2001:db8::/32", ("2001:db8:27cc:1::",)
            )
        with self.assertRaisesRegex(ValueError, "outside"):
            C.pack_usid_container(
                "2001:db8::/32", ("2001:db9:27cc::",)
            )


class RbbTestConfigStructureTest(unittest.TestCase):
    def test_tc1_rejects_route_and_traffic_prefix_mismatch(self) -> None:
        mismatched = replace(
            SRV6_3_USIDS_PROFILE, tail_prefix="2001:db8:dead::/64"
        )
        with self.assertRaisesRegex(ValueError, "must equal"):
            _validate_traffic_route_contract(mismatched, include_traffic=True)

    def test_ixia_route_pool_must_start_on_network_boundary(self) -> None:
        with mock.patch.object(
            C, "IXIA_TAIL_ADVERTISED_PREFIX", "2001:db8:beef::1"
        ):
            with self.assertRaisesRegex(ValueError, "not a /64 network address"):
                _validate_traffic_route_contract(
                    SRV6_3_USIDS_PROFILE, include_traffic=True
                )

    def test_tc1_structure(self) -> None:
        config = create_rbb_srv6_3_usids_test_config()
        self.assertEqual(config.name, "RBB_SRV6_3_USIDS_TEST")
        # Two DUTs, both marked dut=True.
        self.assertEqual(len(config.endpoints or []), 2)
        self.assertTrue(all(e.dut for e in (config.endpoints or [])))
        # The non-destructive default validates the pre-existing underlay.
        self.assertFalse(config.setup_tasks)
        # One playbook with the full S02-S28 stage sequence.
        self.assertEqual(len(config.playbooks or []), 1)
        playbook = (config.playbooks or [])[0]
        self.assertEqual(playbook.name, "bgp_rbb_srv6_3_usids")
        self.assertGreaterEqual(len(playbook.stages or []), 10)
        self.assertFalse(config.basic_port_configs)
        self.assertFalse(config.basic_traffic_item_configs)
        self.assertFalse(any(endpoint.ixia_needed for endpoint in config.endpoints))

    def test_tc1_wires_ixia_traffic_config(self) -> None:
        # Increment B/C: IXIA edge eBGP-emulation port configs + the real
        # Traffic items are attached only when explicitly enabled.
        config = create_rbb_srv6_3_usids_test_config(
            topology=_generic_topology(), include_traffic=True
        )
        self.assertTrue(config.basic_port_configs)
        self.assertEqual(len(config.basic_port_configs or []), 2)
        items = config.basic_traffic_item_configs or []
        self.assertEqual([item.name for item in items], [C.TRAFFIC_ITEM_R1_TO_R2])
        self.assertTrue(
            all(item.traffic_type == ixia_types.TrafficType.IPV6 for item in items)
        )
        # Endpoints request IXIA and carry their edge interfaces + explicit
        # direct-IXIA connections (required by OSS traffic_generator — no LLDP).
        for endpoint in config.endpoints or []:
            self.assertTrue(endpoint.ixia_needed)
            self.assertTrue(endpoint.ixia_ports)
            self.assertTrue(endpoint.direct_ixia_connections)
            for conn in endpoint.direct_ixia_connections or []:
                self.assertIn("/", conn.ixia_port)
                self.assertTrue(conn.interface)
                self.assertTrue(conn.ixia_chassis_ip)

    def test_ixia_protocol_verification_tracks_traffic_not_edge_mutation(self) -> None:
        topology = _generic_topology()
        with mock.patch.object(C, "EDGE_EBGP_ENABLED", False):
            preconfigured_edge = create_rbb_srv6_3_usids_test_config(
                topology=topology, include_traffic=True
            )
        self.assertFalse(preconfigured_edge.skip_ixia_protocol_verification)

        with mock.patch.object(C, "EDGE_EBGP_ENABLED", True):
            managed_edge = create_rbb_srv6_3_usids_test_config(
                topology=topology, include_traffic=True
            )
        self.assertFalse(managed_edge.skip_ixia_protocol_verification)

        device_only = create_rbb_srv6_3_usids_test_config(
            topology=topology, include_traffic=False
        )
        self.assertTrue(device_only.skip_ixia_protocol_verification)

    def test_ixia_advertisement_safety_requires_explicit_opt_out(self) -> None:
        topology = _generic_topology()
        with mock.patch.object(C, "SKIP_ADVERTISED_PREFIXES_CHECK", False):
            protected = create_rbb_srv6_3_usids_test_config(
                topology=topology, include_traffic=True
            )
        self.assertFalse(protected.skip_advertised_prefixes_check)

        with mock.patch.object(C, "SKIP_ADVERTISED_PREFIXES_CHECK", True):
            isolated_lab = create_rbb_srv6_3_usids_test_config(
                topology=topology, include_traffic=True
            )
        self.assertTrue(isolated_lab.skip_advertised_prefixes_check)

    def test_edge_ebgp_enabled_wires_rbb_edge_ebgp_setup_and_restore(self) -> None:
        # With the opt-in edge flag on, the DUT-side edge eBGP is brought up by
        # the bgp.json-compatible ``rbb_edge_ebgp`` task (not the bgpcpp-targeting
        # ``configure_ixia_interfaces``), one per DUT, with a matching restore
        # teardown per DUT.
        with mock.patch.object(C, "EDGE_EBGP_ENABLED", True):
            config = create_rbb_srv6_3_usids_test_config(
                topology=_generic_topology(), include_traffic=True
            )
        setup_names = [task.task_name for task in (config.setup_tasks or [])]
        self.assertEqual(setup_names.count("rbb_edge_ebgp"), 2)
        self.assertNotIn("configure_ixia_interfaces", setup_names)
        edge_params = [
            json.loads(task.params.json_params)
            for task in (config.setup_tasks or [])
            if task.task_name == "rbb_edge_ebgp"
        ]
        self.assertTrue(all(params["enable_ipv6_afi"] for params in edge_params))
        self.assertEqual(edge_params[0]["ibgp_peer_addr"], C.R2_ROUTER_ID)
        self.assertEqual(edge_params[1]["ibgp_peer_addr"], C.R1_ROUTER_ID)
        self.assertNotIn("ibgp_srv6_nexthop", edge_params[0])
        self.assertEqual(edge_params[1]["ibgp_srv6_nexthop"], C.SRV6_DECAP_SID)
        teardown = [
            (task.task_name, json.loads(task.params.json_params))
            for task in (config.teardown_tasks or [])
        ]
        self.assertEqual(
            [name for name, _ in teardown],
            ["rbb_edge_ebgp", "rbb_edge_ebgp"],
        )
        self.assertTrue(all(p.get("action") == "restore" for _, p in teardown))

    def test_dut_bootstrap_is_opt_in_and_precedes_edge_overlay(self) -> None:
        topology = _generic_topology()
        with mock.patch.object(C, "SETUP_DUTS_ENABLED", True), mock.patch.object(
            C, "EDGE_EBGP_ENABLED", True
        ):
            config = create_rbb_srv6_3_usids_test_config(
                topology=topology, include_traffic=True
            )
        setup_names = [task.task_name for task in (config.setup_tasks or [])]
        self.assertEqual(
            setup_names,
            [
                "rbb_dut_bootstrap",
                "rbb_dut_bootstrap",
                "rbb_edge_ebgp",
                "rbb_edge_ebgp",
            ],
        )
        bootstrap_params = [
            json.loads(task.params.json_params)
            for task in (config.setup_tasks or [])[:2]
        ]
        self.assertEqual(
            [params["role"] for params in bootstrap_params], ["r1", "r2"]
        )
        self.assertTrue(all(params["include_traffic"] for params in bootstrap_params))
        self.assertEqual(
            bootstrap_params[0]["core_port_channels"][0]["members"],
            list(topology.r1.core_pcs[0].members),
        )
        teardown_names = [task.task_name for task in (config.teardown_tasks or [])]
        self.assertEqual(
            teardown_names,
            [
                "rbb_edge_ebgp",
                "rbb_edge_ebgp",
                "rbb_dut_bootstrap",
                "rbb_dut_bootstrap",
            ],
        )

    def test_dut_bootstrap_does_not_change_default_mode(self) -> None:
        with mock.patch.object(C, "SETUP_DUTS_ENABLED", False):
            config = create_rbb_srv6_3_usids_test_config(
                topology=_generic_topology(), include_traffic=False
            )
        self.assertFalse(config.setup_tasks)
        self.assertFalse(config.teardown_tasks)

    def test_device_only_bootstrap_uses_the_minimal_nontraffic_mode(self) -> None:
        with mock.patch.object(C, "SETUP_DUTS_ENABLED", True):
            config = create_rbb_srv6_3_usids_test_config(
                topology=_generic_topology(), include_traffic=False
            )
        params = [
            json.loads(task.params.json_params) for task in (config.setup_tasks or [])
        ]
        self.assertEqual(
            [entry["include_traffic"] for entry in params], [False, False]
        )

    def test_fresh_image_traffic_requires_edge_setup(self) -> None:
        with mock.patch.object(C, "SETUP_DUTS_ENABLED", True), mock.patch.object(
            C, "EDGE_EBGP_ENABLED", False
        ):
            with self.assertRaisesRegex(ValueError, "requires.*setup-dut-edges"):
                create_rbb_srv6_3_usids_test_config(
                    topology=_generic_topology(), include_traffic=True
                )

    def test_live_traffic_without_explicit_wiring_is_rejected(self) -> None:
        with mock.patch.dict(os.environ, {"TAAC_CIRCUIT_INFO_PATH": ""}):
            with self.assertRaises(ValueError):
                create_rbb_srv6_3_usids_test_config(include_traffic=True)

if __name__ == "__main__":
    unittest.main()
