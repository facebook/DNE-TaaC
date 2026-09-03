# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""Unit tests for the RBB SRv6 scenario builders and TestConfig factory.

Lives under ``taac/playbooks/routing/tests`` (not ``taac/testconfigs/routing/
tests``) because the OSS pytest harness never recurses into any ``testconfigs``
directory (``pyproject.toml`` ``norecursedirs``); placing the file here is what
actually gets it run. The factory/scenario modules under test are imported by
absolute path, so their real home under ``taac/testconfigs`` is unaffected.
"""

import json
import unittest
from unittest import mock

from taac.testconfigs.routing.factories.qual_rbb.rbb_srv6_test_config import (
    create_rbb_srv6_3_usids_test_config,
    create_rbb_srv6_te_baseline_test_config,
)
from taac.testconfigs.routing.util import bgp_rbb_constants as C
from taac.testconfigs.routing.util.bgp_rbb_scenario_profiles import (
    core_interface_cmds,
    direct_route_delete_cmds,
    direct_route_install_cmds,
    ixia_edge_cmds,
    srv6_decap_counter_spec,
    srv6_encap_counter_spec,
    SRV6_3_USIDS_PROFILE,
    srv6_program_cmds,
    verify_core_links_up_spec,
    verify_openr_adjacency_spec,
    verify_openr_redistribute_spec,
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
    return load_rbb_topology(circuit_info_path="/nonexistent/rbb_circuit_info.csv")


class ScenarioBuilderTest(unittest.TestCase):
    def test_core_interface_cmds_is_nondestructive_read(self) -> None:
        # The live core is pre-provisioned and must never be mutated; the
        # "setup" step is a read-only aggregate-port dump.
        self.assertEqual(core_interface_cmds("r1"), ["fboss2 show aggregate-port"])
        self.assertEqual(core_interface_cmds("r2"), ["fboss2 show aggregate-port"])

    def test_srv6_program_is_nondestructive_mysid_read(self) -> None:
        # SRv6 is ASIC-programmed via agent config; there is no CLI write path,
        # so "program" is a read-only confirm of the live micro-SID state.
        for node in ("r1", "r2"):
            self.assertEqual(
                srv6_program_cmds(node, SRV6_3_USIDS_PROFILE), ["fboss2 show mysid"]
            )

    def test_direct_route_install_and_delete_reference_tail_prefix(self) -> None:
        # Generic-NOS shell templates still reference the tail prefix (the FBOSS
        # playbook drives the lifecycle over thrift instead).
        self.assertIn(
            SRV6_3_USIDS_PROFILE.tail_prefix,
            "\n".join(direct_route_install_cmds(SRV6_3_USIDS_PROFILE)),
        )
        self.assertIn(
            SRV6_3_USIDS_PROFILE.tail_prefix,
            "\n".join(direct_route_delete_cmds(SRV6_3_USIDS_PROFILE)),
        )

    def test_ixia_edge_cmds_reference_topology_interface(self) -> None:
        # The edge interface is topology-derived, not a hardcoded constant.
        topo = _generic_topology()
        iface = topo.r1.primary_ixia_interface
        self.assertTrue(iface)  # generic fallback provides a placeholder edge
        self.assertIn(iface, "\n".join(ixia_edge_cmds("r1", topo)))

    def test_verify_specs_assert_route_ownership_transition(self) -> None:
        te = verify_route_owner_te_agent_spec(SRV6_3_USIDS_PROFILE)
        self.assertIn(C.ROUTE_OWNER_TE_AGENT, te["expect_contains"])
        # show_cmd greps the tail prefix's route-details block. The slash in the
        # prefix is escaped for the sed address regex (203.0.113.0\/24), so assert
        # on the network-address portion, which appears verbatim.
        self.assertIn(
            SRV6_3_USIDS_PROFILE.tail_prefix.split("/")[0], te["show_cmd"]
        )
        bgpd = verify_route_owner_bgpd_spec(SRV6_3_USIDS_PROFILE)
        self.assertIn(C.ROUTE_OWNER_BGPD, bgpd["expect_contains"])
        self.assertIn(C.ROUTE_OWNER_TE_AGENT, bgpd["expect_absent"])

    def test_verify_tunnels_asserts_derived_locator_and_behaviors(self) -> None:
        # The assert token is DERIVED from the profile's locator, not hardcoded.
        r1 = verify_srv6_tunnels_spec("r1", SRV6_3_USIDS_PROFILE)
        self.assertEqual(r1["show_cmd"], "fboss2 show mysid")
        self.assertIn(SRV6_3_USIDS_PROFILE.locator_token, r1["expect_contains"])
        self.assertIn(C.SRV6_BEHAVIOR_ADJACENCY, r1["expect_contains"])
        self.assertNotIn(C.SRV6_BEHAVIOR_DECAP, r1["expect_contains"])
        # The tail (R2) additionally terminates: decap behavior asserted.
        r2 = verify_srv6_tunnels_spec("r2", SRV6_3_USIDS_PROFILE)
        self.assertIn(C.SRV6_BEHAVIOR_DECAP, r2["expect_contains"])

    def test_verify_pc_rif_spec_uses_topology_show_name(self) -> None:
        topo = _generic_topology()
        spec = verify_pc162_global_ipv6_spec("r2", topo)
        self.assertEqual(spec["show_cmd"], "fboss2 show aggregate-port")
        # The asserted PC name is the topology-derived show name, capitalized.
        pc = topo.r2.rif_verify_pc
        self.assertIsNotNone(pc)
        self.assertIn(pc.show_name, spec["expect_contains"])

    def test_core_links_up_spec_asserts_members(self) -> None:
        # S02-S05 is a REAL link-up assertion: PC show name + every member.
        topo = _generic_topology()
        spec = verify_core_links_up_spec("r1", topo)
        self.assertEqual(spec["show_cmd"], "fboss2 show aggregate-port")
        for pc in topo.r1.core_pcs:
            self.assertIn(pc.show_name, spec["expect_contains"])
            for member in pc.members:
                self.assertIn(member, spec["expect_contains"])

    def test_peer_loopback_spec_targets_other_node(self) -> None:
        # S07: R1 asserts R2's loopback (router-id) and vice versa.
        r1 = verify_peer_loopback_learned_spec("r1")
        self.assertIn(C.R2_ROUTER_ID, r1["expect_contains"])
        r2 = verify_peer_loopback_learned_spec("r2")
        self.assertIn(C.R1_ROUTER_ID, r2["expect_contains"])

    def test_openr_redistribute_spec_targets_own_loopback(self) -> None:
        # S13 (alt): OpenR redistributes this node's own loopback.
        self.assertIn(C.R1_ROUTER_ID, verify_openr_redistribute_spec("r1")["expect_contains"])

    def test_openr_adjacency_spec_asserts_openr_client_on_peer_lo(self) -> None:
        # S06/S13 default path: peer loopback carries an OPENR route client
        # (fboss2 read; the shipped OpenR HCs are NotImplemented in OSS).
        r1 = verify_openr_adjacency_spec("r1")
        self.assertIn("OPENR", r1["expect_contains"])
        self.assertIn(C.R2_ROUTER_ID, r1["expect_contains"])
        self.assertIn(C.R2_ROUTER_ID, r1["show_cmd"])
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
        self.assertNotIn("fdad:ffff", C.SRV6_LOCATOR)
        for usid in (C.SRV6_USID_HEAD, C.SRV6_USID_MID, C.SRV6_USID_TAIL):
            self.assertTrue(usid.startswith("2001:db8:"))
            self.assertNotIn("fdad:ffff", usid)

    def test_tail_prefix_default_is_documentation_range(self) -> None:
        # RFC 5737 documentation range (not the lab's 10.10.10.0/24).
        self.assertEqual(C.TAIL_DEST_PREFIX, "203.0.113.0/24")

    def test_ixia_edge_defaults_are_documentation_range(self) -> None:
        # IXIA edge emulation addresses/pools default to RFC 3849 doc range —
        # nothing lab-specific committed (real values via the lab profile).
        for addr in (
            C.IXIA_R1_EDGE_V6,
            C.IXIA_R2_EDGE_V6,
            C.IXIA_TAIL_ADVERTISED_PREFIX,
            C.IXIA_HEAD_ADVERTISED_PREFIX,
        ):
            self.assertTrue(addr.startswith("2001:db8:"))
            self.assertNotIn("fdad:ffff", addr)

    def test_edge_ebgp_off_by_default(self) -> None:
        # DUT-side edge eBGP is opt-in (non-destructive default).
        self.assertFalse(C.EDGE_EBGP_ENABLED)

    def test_locator_token_derived_from_locator(self) -> None:
        self.assertEqual(C.locator_token("2001:db8:6::/48"), "2001:db8:6:")
        self.assertEqual(C.locator_token("fdad:ffff::/32"), "fdad:ffff:")
        # The committed token matches the committed (generic) locator.
        self.assertEqual(C.SRV6_LOCATOR_TOKEN, C.locator_token(C.SRV6_LOCATOR))


class RbbTestConfigStructureTest(unittest.TestCase):
    def test_tc1_structure(self) -> None:
        config = create_rbb_srv6_3_usids_test_config()
        self.assertEqual(config.name, "RBB_SRV6_3_USIDS_TEST")
        # Two DUTs, both marked dut=True.
        self.assertEqual(len(config.endpoints or []), 2)
        self.assertTrue(all(e.dut for e in (config.endpoints or [])))
        # Core underlay setup: one task per DUT (edge eBGP is opt-in/off).
        self.assertEqual(len(config.setup_tasks or []), 2)
        # One playbook with the full S02-S28 stage sequence.
        self.assertEqual(len(config.playbooks or []), 1)
        playbook = (config.playbooks or [])[0]
        self.assertEqual(playbook.name, "bgp_rbb_srv6_3_usids")
        self.assertGreaterEqual(len(playbook.stages or []), 15)

    def test_tc1_wires_ixia_traffic_config(self) -> None:
        # Increment B/C: IXIA edge eBGP-emulation port configs + the real
        # port3→port10 traffic items are attached (include_traffic default on).
        config = create_rbb_srv6_3_usids_test_config()
        self.assertTrue(config.basic_port_configs)
        self.assertEqual(len(config.basic_port_configs or []), 2)
        item_names = {
            item.name for item in (config.basic_traffic_item_configs or [])
        }
        self.assertIn(C.TRAFFIC_ITEM_R1_TO_R2, item_names)
        self.assertIn(C.TRAFFIC_ITEM_R2_TO_R1, item_names)
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

    def test_edge_ebgp_enabled_wires_rbb_edge_ebgp_setup_and_restore(self) -> None:
        # With the opt-in edge flag on, the DUT-side edge eBGP is brought up by
        # the bgp.json-compatible ``rbb_edge_ebgp`` task (not the bgpcpp-targeting
        # ``configure_ixia_interfaces``), one per DUT, with a matching restore
        # teardown per DUT.
        with mock.patch.object(C, "EDGE_EBGP_ENABLED", True):
            config = create_rbb_srv6_3_usids_test_config()
        setup_names = [task.task_name for task in (config.setup_tasks or [])]
        self.assertEqual(setup_names.count("rbb_edge_ebgp"), 2)
        self.assertNotIn("configure_ixia_interfaces", setup_names)
        teardown = [
            (task.task_name, json.loads(task.params.json_params))
            for task in (config.teardown_tasks or [])
        ]
        self.assertEqual([n for n, _ in teardown], ["rbb_edge_ebgp", "rbb_edge_ebgp"])
        self.assertTrue(all(p.get("action") == "restore" for _, p in teardown))

    def test_setup_tasks_target_both_duts(self) -> None:
        config = create_rbb_srv6_3_usids_test_config()
        hostnames = {
            json.loads(task.params.json_params)["hostname"]
            for task in (config.setup_tasks or [])
        }
        self.assertEqual(hostnames, {C.R1_HOSTNAME, C.R2_HOSTNAME})

    def test_tc2_baseline_structure(self) -> None:
        config = create_rbb_srv6_te_baseline_test_config()
        self.assertEqual(config.name, "RBB_SRV6_TE_BASELINE_TEST")
        playbook = (config.playbooks or [])[0]
        self.assertEqual(playbook.name, "bgp_rbb_srv6_te_baseline")


if __name__ == "__main__":
    unittest.main()
