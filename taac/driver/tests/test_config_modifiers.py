# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import json
import logging
import typing as t

# IsolatedAsyncioTestCase, not later.unittest.TestCase: ShipIt exports
# driver/tests/ to the OSS repo (unlike libs/tests/ and utils/tests/, which are
# stripped) and github/conftest.py collects it, but `later` is Meta-internal and
# absent from the OSS requirements -- importing it would fail collection for the
# whole OSS suite. The two driver tests already shipping use stdlib unittest for
# the same reason.
from unittest import IsolatedAsyncioTestCase as TestCase
from unittest.mock import AsyncMock, patch

# @manual=//configerator/structs/neteng/fboss/bgp:bgp_config-python-types
from configerator.structs.neteng.fboss.bgp.bgp_config.thrift_types import (
    BgpConfig,
    BgpNetwork,
    BgpPeer,
    PeerGroup,
)
from configerator.structs.neteng.robotron.bgp_policy.thrift_types import (
    BgpPolicies,
    BgpPolicyActionType,
    BgpPolicyAtomicMatchType,
    BgpPolicyStatement,
    CommunityActionType,
    CommunityList,
    DrainState,
    FlowControlAction,
)
from taac.driver import config_modifiers as _config_modifiers
from taac.driver.abstract_switch import AbstractSwitch
from taac.driver.config_modifiers import (
    _FILE_EXISTS_SENTINEL as FILE_EXISTS_SENTINEL,
    _HIDDEN_STARTUP_CONFIG_SYMLINK as HIDDEN_SYMLINK,
    _serialize_config,
    build_propagate_policies,
    COMMUNITY_DRAIN,
    COMMUNITY_LIVE,
    ConfigModifierError,
    drain_device,
    generate_base_configs,
    LIVE_CONFIG_PATH,
    LOCAL_PREF_DRAIN,
    LOCAL_PREF_LIVE,
    MARKER_SOFT_DRAINED,
    MARKER_UNDRAINED,
    POLICY_PROPAGATE_IN,
    POLICY_PROPAGATE_OUT,
    POLICY_PROPAGATE_OUT_DRAIN,
    PROPAGATE_POLICIES,
    setup_base_configs,
    SOFTDRAIN_CONFIG_PATH,
    STARTUP_CONFIG_SYMLINK,
    undrain_device,
)
from taac.driver.driver_constants import FbossSystemctlServiceName
from taac.driver.fboss_switch import FbossSwitch
from thrift.python.serializer import deserialize, Protocol, serialize

# ShipIt rewrites import statements but not string literals, so a hardcoded
# dotted path is only correct in one of the two worlds; read the name off the
# imported module instead.
_MODULE = _config_modifiers.__name__


class _Device:
    """The slice of on-device state drain/undrain can observe or change.

    Modelling the symlink instead of stubbing ``readlink`` means the verification
    step in ``_apply_drain_state`` reads back the value the ``ln -sfn`` command
    actually set, so ``symlink_after_restart`` can emulate an on-device selector
    clobbering it.
    """

    def __init__(self) -> None:
        self.commands: list[str] = []
        self.restarted_services: list[FbossSystemctlServiceName] = []
        # Contents matter only to the base-config tests; the drain tests care
        # solely about which paths are present.
        self.files: dict[str, str] = {LIVE_CONFIG_PATH: "", SOFTDRAIN_CONFIG_PATH: ""}
        self.writes: list[tuple[str, str]] = []
        self.symlink_target: str = ""
        # Set to a path to emulate an ExecStartPre config_selector repointing the
        # symlink during the bgpd restart.
        self.symlink_after_restart: str | None = None

    @property
    def mutating_commands(self) -> list[str]:
        """Commands that change device state, i.e. everything but the probes."""
        return [c for c in self.commands if not c.startswith(("test -f ", "readlink "))]

    def command_containing(self, needle: str) -> str:
        matches = [c for c in self.commands if needle in c]
        assert len(matches) == 1, f"expected exactly one {needle!r} cmd, got {matches}"
        return matches[0]

    async def run_cmd(self, cmd: str, *args, **kwargs) -> str:
        self.commands.append(cmd)
        # Paths are interpolated unquoted (they are module constants with no shell
        # metacharacters), so a plain split recovers the argv.
        if cmd.startswith("test -f "):
            # "test -f <path> && echo <sentinel> || true"
            path = cmd.split()[2]
            return f"{FILE_EXISTS_SENTINEL}\n" if path in self.files else "\n"
        if cmd.startswith("readlink "):
            return f"{self.symlink_target}\n"
        if cmd.startswith("ln -sfn "):
            # "ln -sfn <target> <staging> && mv -Tf <staging> <link>"
            self.symlink_target = cmd.split()[2]
        return ""

    async def restart_service(self, service, agents=None) -> None:
        self.restarted_services.append(service)
        if self.symlink_after_restart is not None:
            self.symlink_target = self.symlink_after_restart

    async def read_file(self, file_location: str) -> str:
        return self.files[file_location]

    async def write_file(self, contents: str, remote_path: str, **kwargs) -> None:
        self.files[remote_path] = contents
        self.writes.append((remote_path, contents))


def _make_switch(device: _Device) -> AbstractSwitch:
    """Build a driver double wired to ``device``.

    ``spec=AbstractSwitch`` does the work a hand-written subclass otherwise
    would: it satisfies ``isinstance``, auto-provides every method on the ABC so
    none need stubbing, and still raises AttributeError on a typo'd member. The
    ABC cannot be instantiated directly -- it has 18 abstract methods.
    """
    switch = AsyncMock(spec=AbstractSwitch)
    # hostname/logger are set in AbstractSwitch.__init__, so they are not part of
    # the class spec; plain `spec` (unlike `spec_set`) still allows setting them.
    switch.hostname = "test-switch"
    switch.logger = logging.getLogger("test_config_modifiers")
    switch.async_run_cmd_on_shell.side_effect = device.run_cmd
    switch.async_restart_service.side_effect = device.restart_service
    switch.async_read_file.side_effect = device.read_file
    # AsyncMock is not nominally an AbstractSwitch even though spec= makes it one
    # at runtime; the cast keeps that fact in one place instead of at every call.
    return t.cast(AbstractSwitch, switch)


def _make_fboss_switch(device: _Device) -> FbossSwitch:
    """Build a driver double specced against the concrete FBOSS driver.

    ``setup_base_configs`` calls ``async_write_file_on_device``, which lives on
    ``FbossSwitch`` rather than on the ABC, so an ``AbstractSwitch``-specced mock
    would raise AttributeError on it. Speccing against ``FbossSwitch`` also
    satisfies ``_assert_fboss_device`` for real, so these tests exercise the
    guard rather than patching it out.

    Typed as ``FbossSwitch``, not ``AbstractSwitch``: ``OnboxDrainDriverMethodsTest``
    passes the result as ``self`` to unbound ``FbossSwitch`` methods, which the
    wider type would reject. Callers wanting the ABC get it by subtyping.
    """
    switch = AsyncMock(spec=FbossSwitch)
    switch.hostname = "test-switch"
    switch.logger = logging.getLogger("test_config_modifiers")
    switch.async_run_cmd_on_shell.side_effect = device.run_cmd
    switch.async_restart_service.side_effect = device.restart_service
    switch.async_read_file.side_effect = device.read_file
    switch.async_write_file_on_device.side_effect = device.write_file
    return t.cast(FbossSwitch, switch)


class DrainUndrainTest(TestCase):
    def setUp(self) -> None:
        self.device = _Device()
        self.switch = _make_switch(self.device)
        # The driver double is a spec'd mock, not a real FbossSwitch, so point the
        # FBOSS-driver check at its class. The check's own logic is covered by
        # FbossDeviceGuardTest below.
        guard = patch(f"{_MODULE}._fboss_switch_cls", return_value=type(self.switch))
        guard.start()
        self.addCleanup(guard.stop)

    def assert_restarted_bgpd(self, times: int) -> None:
        self.assertEqual(
            [FbossSystemctlServiceName.BGP] * times, self.device.restarted_services
        )

    async def test_drain_clears_undrained_before_setting_soft_drained(self) -> None:
        # The selector resolves UNDRAINED ahead of SOFT_DRAINED, so a drain that
        # sets its marker without clearing the opposite one silently stays live.
        await drain_device(self.switch)

        marker_cmd = self.device.command_containing(MARKER_SOFT_DRAINED)
        self.assertLess(
            marker_cmd.index(f"rm -f {MARKER_UNDRAINED}"),
            marker_cmd.index(f"touch {MARKER_SOFT_DRAINED}"),
        )

    async def test_undrain_clears_soft_drained_before_setting_undrained(self) -> None:
        await undrain_device(self.switch)

        marker_cmd = self.device.command_containing(MARKER_UNDRAINED)
        self.assertLess(
            marker_cmd.index(f"rm -f {MARKER_SOFT_DRAINED}"),
            marker_cmd.index(f"touch {MARKER_UNDRAINED}"),
        )

    async def test_markers_updated_in_a_single_invocation(self) -> None:
        # Two separate calls would leave a window where both or neither marker
        # exists, which the selector would resolve to the wrong config.
        await drain_device(self.switch)

        self.assertEqual(
            f"rm -f {MARKER_UNDRAINED} && touch {MARKER_SOFT_DRAINED}",
            self.device.command_containing("touch "),
        )

    async def test_drain_points_symlink_at_softdrain_config(self) -> None:
        await drain_device(self.switch)

        self.assertEqual(
            f"ln -sfn {SOFTDRAIN_CONFIG_PATH} {HIDDEN_SYMLINK} && "
            f"mv -Tf {HIDDEN_SYMLINK} {STARTUP_CONFIG_SYMLINK}",
            self.device.command_containing("ln -sfn"),
        )
        self.assertEqual(SOFTDRAIN_CONFIG_PATH, self.device.symlink_target)

    async def test_undrain_points_symlink_at_live_config(self) -> None:
        await undrain_device(self.switch)

        self.assertEqual(
            f"ln -sfn {LIVE_CONFIG_PATH} {HIDDEN_SYMLINK} && "
            f"mv -Tf {HIDDEN_SYMLINK} {STARTUP_CONFIG_SYMLINK}",
            self.device.command_containing("ln -sfn"),
        )
        self.assertEqual(LIVE_CONFIG_PATH, self.device.symlink_target)

    async def test_symlink_swap_is_atomic_rename_not_unlink_relink(self) -> None:
        # `ln -sf` on its own unlinks the destination before recreating it, which
        # leaves a window where bgpd could read a missing symlink. Staging plus
        # `mv -T` (rename(2)) closes it -- same idiom fboss_config_selector uses.
        await drain_device(self.switch)

        symlink_cmd = self.device.command_containing("ln -sfn")
        self.assertIn(f"mv -Tf {HIDDEN_SYMLINK} {STARTUP_CONFIG_SYMLINK}", symlink_cmd)
        self.assertLess(symlink_cmd.index("ln -sfn"), symlink_cmd.index("mv -Tf"))

    async def test_restarts_bgpd_once(self) -> None:
        await drain_device(self.switch)

        self.assert_restarted_bgpd(1)

    async def test_restart_bgp_false_skips_restart_only(self) -> None:
        await drain_device(self.switch, restart_bgp=False)

        self.assert_restarted_bgpd(0)
        # Markers and symlink are still applied so a later restart picks them up.
        self.assertIn(
            f"touch {MARKER_SOFT_DRAINED}", self.device.command_containing("touch ")
        )
        self.assertEqual(SOFTDRAIN_CONFIG_PATH, self.device.symlink_target)

    async def test_missing_target_config_raises_before_touching_device(self) -> None:
        del self.device.files[SOFTDRAIN_CONFIG_PATH]

        with self.assertRaises(ConfigModifierError) as ctx:
            await drain_device(self.switch)

        self.assertIn(SOFTDRAIN_CONFIG_PATH, str(ctx.exception))
        self.assertEqual([], self.device.mutating_commands)
        self.assert_restarted_bgpd(0)

    async def test_undrain_missing_live_config_raises(self) -> None:
        del self.device.files[LIVE_CONFIG_PATH]

        with self.assertRaises(ConfigModifierError):
            await undrain_device(self.switch)

        self.assertEqual([], self.device.mutating_commands)

    async def test_symlink_clobbered_during_restart_raises(self) -> None:
        # Emulates an on-device config_selector re-deriving the symlink at bgpd
        # ExecStartPre and forcing the undrained config -- the drain did not
        # actually take effect, so this must not pass silently.
        self.device.symlink_after_restart = LIVE_CONFIG_PATH

        with self.assertRaises(ConfigModifierError) as ctx:
            await drain_device(self.switch)

        message = str(ctx.exception)
        self.assertIn(LIVE_CONFIG_PATH, message)
        self.assertIn(SOFTDRAIN_CONFIG_PATH, message)
        self.assertIn("drainable", message)

    async def test_missing_symlink_raises(self) -> None:
        self.device.symlink_after_restart = ""

        with self.assertRaises(ConfigModifierError) as ctx:
            await drain_device(self.switch)

        self.assertIn("<nothing>", str(ctx.exception))

    async def test_verification_reads_link_without_resolving_it(self) -> None:
        # readlink -f would follow a coop config symlink through to the file it
        # resolves to and never match the path we set.
        await drain_device(self.switch)

        self.assertEqual(
            f"readlink {STARTUP_CONFIG_SYMLINK}",
            self.device.command_containing("readlink"),
        )

    async def test_drain_undrain_round_trip_leaves_single_marker(self) -> None:
        for _ in range(3):
            await drain_device(self.switch)
            self.assertEqual(SOFTDRAIN_CONFIG_PATH, self.device.symlink_target)
            await undrain_device(self.switch)
            self.assertEqual(LIVE_CONFIG_PATH, self.device.symlink_target)

        self.assert_restarted_bgpd(6)


class FbossDeviceGuardTest(TestCase):
    """The FBOSS-only guard, exercised against the real _assert_fboss_device."""

    class _SomeOtherDriver:
        """Stands in for FbossSwitch so the driver double fails the check."""

    def setUp(self) -> None:
        self.device = _Device()
        self.switch = _make_switch(self.device)

    async def test_rejects_non_fboss_driver(self) -> None:
        # An Arista/Cisco driver would run these FBOSS-specific commands against a
        # device that has no /dev/shm/fboss markers and no bgpd systemd unit.
        with patch(f"{_MODULE}._fboss_switch_cls", return_value=self._SomeOtherDriver):
            with self.assertRaises(ConfigModifierError) as ctx:
                await drain_device(self.switch)

        self.assertIn("FbossSwitch", str(ctx.exception))

    async def test_guard_runs_before_any_device_command(self) -> None:
        with patch(f"{_MODULE}._fboss_switch_cls", return_value=self._SomeOtherDriver):
            with self.assertRaises(ConfigModifierError):
                await drain_device(self.switch)

        self.assertEqual([], self.device.commands)
        self.assertEqual([], self.device.restarted_services)

    def test_resolver_returns_the_real_fboss_switch(self) -> None:
        # The one line the patched tests above cannot cover.
        from taac.driver.config_modifiers import _fboss_switch_cls

        self.assertIs(FbossSwitch, _fboss_switch_cls())


class ConfigPathTest(TestCase):
    """The two on-device config paths, pinned to their literal values.

    Every other test here refers to them through the constants, so a wrong path
    would propagate into the expectations and pass unnoticed while drain/undrain
    reads and writes files bgpd never looks at.
    """

    def test_live_config_is_the_path_bgpd_is_launched_against(self) -> None:
        # bgpd's provisioned --config, which fboss2's config session keeps as a
        # symlink into the CLI-managed bgpcpp/bgpcpp.conf.
        self.assertEqual("/etc/coop/bgpcpp.conf", LIVE_CONFIG_PATH)

    def test_softdrain_config_sits_beside_the_live_one(self) -> None:
        self.assertEqual("/etc/coop/bgpcpp_softdrain.conf", SOFTDRAIN_CONFIG_PATH)


_T = t.TypeVar("_T")


def _present(value: _T | None) -> _T:
    """Assert an optional thrift field is set, and narrow it for the type checker.

    Most of the fields these tests read are ``optional`` in the thrift, so a
    plain attribute chain is a type error even where the value is obviously
    populated. This keeps the assertion at the point of access instead of
    scattering suppressions.
    """
    assert value is not None
    return value


def _sample_config() -> BgpConfig:
    """A config in the shape this feature has to cope with.

    Deliberately messy: policies we do not recognise, a peer group and a peer
    already pointing at them, a peer whose names differ from its group's, and
    originated networks with policy references. Every one of those is a thing
    the transform has to deal with rather than a thing it can assume away.
    """
    return BgpConfig(
        router_id="192.0.2.1",
        peer_groups=[
            PeerGroup(
                name="RSW_TO_FSW",
                ingress_policy_name="LEGACY_IN",
                egress_policy_name="LEGACY_OUT",
            ),
            PeerGroup(name="RSW_TO_SLB"),
        ],
        peers=[
            BgpPeer(
                local_addr="2001:db8::1",
                peer_addr="2001:db8::2",
                ingress_policy_name="PEER_OVERRIDE_IN",
                egress_policy_name="PEER_OVERRIDE_OUT",
            ),
            BgpPeer(local_addr="2001:db8::3", peer_addr="2001:db8::4"),
        ],
        networks4=[BgpNetwork(prefix="192.0.2.0/24", policy_name="ORIGINATE_V4")],
        networks6=[BgpNetwork(prefix="2001:db8::/32")],
        policies=BgpPolicies(
            bgp_policy_statements=[
                BgpPolicyStatement(name="LEGACY_IN", policy_version="7"),
                BgpPolicyStatement(name="LEGACY_OUT", policy_version="7"),
            ],
            community_lists=[CommunityList(name="LEGACY_COMMUNITIES")],
            obj_uuid="uuid-from-the-original-config",
        ),
    )


class PropagatePolicyTest(TestCase):
    """The three policies, checked against what bgpd actually reads."""

    def setUp(self) -> None:
        self.policies = {policy.name: policy for policy in PROPAGATE_POLICIES}

    def test_builds_exactly_the_three_expected_policies(self) -> None:
        self.assertEqual(
            [POLICY_PROPAGATE_IN, POLICY_PROPAGATE_OUT, POLICY_PROPAGATE_OUT_DRAIN],
            [policy.name for policy in PROPAGATE_POLICIES],
        )

    def test_ingress_evaluates_drain_term_before_the_catch_all(self) -> None:
        # The single most important ordering property in the feature.
        # PROPAGATE_EVERYTHING_OUT adds LIVE without stripping DRAIN, so a route
        # that came from a drained device and was re-advertised by a healthy one
        # carries both communities. If the catch-all ran first it would win and
        # the route would land on the live local-pref, silently undoing the
        # drain one hop downstream.
        terms = self.policies[POLICY_PROPAGATE_IN].policy_entries

        self.assertEqual(
            ["TERM_MATCH_DRAIN", "TERM_DEFAULT_LIVE"], [t.name for t in terms]
        )
        drain_match = _present(terms[0].policy_match_entries).match_entries[0]
        self.assertEqual(BgpPolicyAtomicMatchType.COMMUNITY_LIST, drain_match.type)
        self.assertEqual(
            [COMMUNITY_DRAIN],
            list(_present(_present(drain_match.communities_filter).communities)),
        )
        self.assertEqual(
            BgpPolicyAtomicMatchType.ALWAYS,
            _present(terms[1].policy_match_entries).match_entries[0].type,
        )

    def test_ingress_sets_the_two_local_prefs(self) -> None:
        terms = self.policies[POLICY_PROPAGATE_IN].policy_entries

        self.assertEqual(
            LOCAL_PREF_DRAIN,
            _present(terms[0].policy_action_entries[0].set_local_pref).local_pref,
        )
        self.assertEqual(
            LOCAL_PREF_LIVE,
            _present(terms[1].policy_action_entries[0].set_local_pref).local_pref,
        )

    def test_egress_live_adds_live_and_removes_nothing(self) -> None:
        actions = self.policies[POLICY_PROPAGATE_OUT].policy_entries[0]
        actions = actions.policy_action_entries

        self.assertEqual(1, len(actions))
        community_action = _present(actions[0].community_action)
        self.assertEqual(CommunityActionType.ADD, community_action.action_type)
        self.assertEqual([COMMUNITY_LIVE], list(_present(community_action.communities)))

    async def test_egress_drain_removes_live_before_adding_drain(self) -> None:
        # Order is carried by list position: bgpd applies policy_action_entries
        # in the order configured and never reads sequence_number. Reversed, a
        # prefix that already carried LIVE would be advertised as both live and
        # drained.
        actions = self.policies[POLICY_PROPAGATE_OUT_DRAIN].policy_entries[0]
        actions = actions.policy_action_entries

        self.assertEqual(
            [
                (CommunityActionType.REMOVE, [COMMUNITY_LIVE]),
                (CommunityActionType.ADD, [COMMUNITY_DRAIN]),
            ],
            [
                (
                    _present(action.community_action).action_type,
                    list(_present(_present(action.community_action).communities)),
                )
                for action in actions
            ],
        )

    def test_every_statement_accepts(self) -> None:
        for policy in PROPAGATE_POLICIES:
            with self.subTest(policy=policy.name):
                self.assertEqual(FlowControlAction.ACCEPT, policy.result)

    def test_no_term_carries_an_explicit_permit(self) -> None:
        # A matching term permits by default; an explicit PERMIT would be a
        # second flow-control action and bgpd allows at most one.
        for policy in PROPAGATE_POLICIES:
            for term in policy.policy_entries:
                for action in term.policy_action_entries:
                    with self.subTest(policy=policy.name, term=term.name):
                        self.assertNotEqual(BgpPolicyActionType.PERMIT, action.type)

    def test_only_the_fields_bgpd_reads_are_populated(self) -> None:
        # bgp_policy.thrift carries a newer mirror for several of these fields
        # that bgpd's policy engine never reads. Populating both would bloat an
        # already large config and let the two copies drift apart.
        for policy in PROPAGATE_POLICIES:
            for term in policy.policy_entries:
                with self.subTest(policy=policy.name, term=term.name):
                    self.assertIsNone(term.policy_matches)
                    for match in _present(term.policy_match_entries).match_entries:
                        self.assertIsNone(match.community_list)
                    for action in term.policy_action_entries:
                        self.assertIsNone(action.action_type)
                        self.assertIsNone(action.community_list)
                        if action.community_action is not None:
                            self.assertIsNone(action.community_action.community_lists)

    def test_generating_configs_leaves_the_shared_constant_alone(self) -> None:
        # The constant is built once at import and reused for every device and
        # both config copies, so anything that could mutate it would corrupt
        # every later run in the same process. Note it is not aliased into the
        # generated configs: thrift-python copies a struct on the way into a
        # container. Immutability makes that a detail rather than a guarantee we
        # depend on.
        expected = build_propagate_policies()

        live, drain = generate_base_configs(_sample_config())

        self.assertEqual(expected, PROPAGATE_POLICIES)
        for config in (live, drain):
            self.assertEqual(
                list(expected), list(_present(config.policies).bgp_policy_statements)
            )

    def test_rebuilding_produces_an_identical_result(self) -> None:
        self.assertEqual(PROPAGATE_POLICIES, build_propagate_policies())

    def test_serialized_form_matches_the_golden(self) -> None:
        """Pin the exact JSON that lands on the device.

        Two jobs. It is a readable artifact: during bring-up this is what you
        paste into a config by hand to try the policies without running TAAC.
        And it is a tripwire -- a change to the builders, or an upstream change
        to bgp_policy.thrift that adds a field, shows up here as a diff instead
        of as behaviour nobody notices.

        The golden is at the bottom of this file. Regenerate it after an
        intentional change by printing::

            json.dumps(json.loads(serialize(
                BgpPolicies(bgp_policy_statements=list(PROPAGATE_POLICIES)),
                protocol=Protocol.JSON,
            ).decode()), indent=2, sort_keys=True)
        """
        rendered = serialize(
            BgpPolicies(bgp_policy_statements=list(PROPAGATE_POLICIES)),
            protocol=Protocol.JSON,
        ).decode()

        self.assertEqual(
            json.loads(_GOLDEN_PROPAGATE_POLICIES_JSON), json.loads(rendered)
        )


class GenerateBaseConfigsTest(TestCase):
    def setUp(self) -> None:
        self.original = _sample_config()
        self.live, self.drain = generate_base_configs(self.original)

    def test_original_policies_are_gone(self) -> None:
        self.assertEqual(
            [POLICY_PROPAGATE_IN, POLICY_PROPAGATE_OUT, POLICY_PROPAGATE_OUT_DRAIN],
            [p.name for p in _present(self.live.policies).bgp_policy_statements],
        )

    def test_auxiliary_lists_are_emptied_but_uuid_survives(self) -> None:
        # Those lists only existed to serve the policies we just deleted; our
        # three define their communities inline. The uuid identifies the
        # container rather than its contents, so it is carried over.
        policies = _present(self.live.policies)

        self.assertEqual([], list(policies.community_lists))
        self.assertEqual([], list(policies.aspath_lists))
        self.assertEqual([], list(policies.prefix_lists))
        self.assertEqual([], list(policies.as_paths))
        self.assertEqual([], list(policies.communities))
        self.assertEqual("uuid-from-the-original-config", policies.obj_uuid)

    def test_peer_groups_differ_only_in_egress_policy(self) -> None:
        for config, expected_egress in (
            (self.live, POLICY_PROPAGATE_OUT),
            (self.drain, POLICY_PROPAGATE_OUT_DRAIN),
        ):
            for peer_group in _present(config.peer_groups):
                with self.subTest(egress=expected_egress, group=peer_group.name):
                    self.assertEqual(
                        POLICY_PROPAGATE_IN, peer_group.ingress_policy_name
                    )
                    self.assertEqual(expected_egress, peer_group.egress_policy_name)

    def test_peers_are_retargeted_too(self) -> None:
        # Peer-level names override the group's, so a peer left on its original
        # policy would both dangle and escape the drain.
        for peer in self.drain.peers:
            with self.subTest(peer=peer.peer_addr):
                self.assertEqual(POLICY_PROPAGATE_IN, peer.ingress_policy_name)
                self.assertEqual(POLICY_PROPAGATE_OUT_DRAIN, peer.egress_policy_name)

    def test_originated_network_policies_are_cleared(self) -> None:
        # Origination policies have no live/drain variant, so there is nothing
        # correct to repoint them at once the originals are gone.
        for network in list(self.live.networks4) + list(self.live.networks6):
            with self.subTest(prefix=network.prefix):
                self.assertIsNone(network.policy_name)

    def test_drain_state_is_declared_per_variant(self) -> None:
        self.assertEqual(DrainState.UNDRAINED, self.live.drain_state)
        self.assertEqual(DrainState.SOFT_DRAINED, self.drain.drain_state)

    def test_variants_differ_only_in_egress_and_drain_state(self) -> None:
        # Policies are byte-identical in both copies -- that is what makes a
        # drain a file swap rather than a config rebuild.
        self.assertEqual(self.live.policies, self.drain.policies)
        normalized = self.drain(
            drain_state=self.live.drain_state,
            peer_groups=self.live.peer_groups,
            peers=self.live.peers,
        )
        self.assertEqual(self.live, normalized)

    def test_input_config_is_not_mutated(self) -> None:
        self.assertEqual(_sample_config(), self.original)

    def test_is_idempotent(self) -> None:
        live_again, drain_again = generate_base_configs(self.live)

        self.assertEqual(self.live, live_again)
        self.assertEqual(self.drain, drain_again)

    def test_config_without_peer_groups_or_policies(self) -> None:
        # A device may legitimately have neither; we add ours rather than
        # failing on the absence.
        bare = BgpConfig(router_id="192.0.2.2")

        live, drain = generate_base_configs(bare)

        self.assertEqual(
            list(PROPAGATE_POLICIES),
            list(_present(live.policies).bgp_policy_statements),
        )
        self.assertIsNone(_present(live.policies).obj_uuid)
        self.assertEqual(DrainState.SOFT_DRAINED, drain.drain_state)

    def test_round_trips_through_simple_json(self) -> None:
        # Protocol.JSON is SimpleJSON, which is the format bgpd reads and writes.
        # COMPACT_JSON would use field ids instead of names and not round-trip.
        for config in (self.live, self.drain):
            with self.subTest(drain_state=config.drain_state):
                raw = serialize(config, protocol=Protocol.JSON)
                self.assertEqual(
                    config, deserialize(BgpConfig, raw, protocol=Protocol.JSON)
                )

    def test_serialized_config_is_indented_and_newline_terminated(self) -> None:
        # thrift's SimpleJSON writer puts the whole document on one line, which
        # is unreadable at the ~19 KB a real config runs to. What lands on the
        # device is re-indented; a regression here is invisible until someone
        # tries to read or diff a config on the box.
        for config in (self.live, self.drain):
            with self.subTest(drain_state=config.drain_state):
                rendered = _serialize_config(config)

                self.assertTrue(rendered.endswith("\n"))
                self.assertGreater(len(rendered.splitlines()), 100)
                self.assertIn('\n  "', rendered)

    def test_indenting_does_not_change_the_document(self) -> None:
        # The re-indent must be formatting only: same parsed JSON as the
        # compact form, and still deserializes to an identical BgpConfig.
        for config in (self.live, self.drain):
            with self.subTest(drain_state=config.drain_state):
                compact = serialize(config, protocol=Protocol.JSON).decode()
                rendered = _serialize_config(config)

                self.assertEqual(json.loads(compact), json.loads(rendered))
                self.assertEqual(
                    config,
                    deserialize(BgpConfig, rendered.encode(), protocol=Protocol.JSON),
                )


class SetupBaseConfigsTest(TestCase):
    """The device-facing half: read, transform, write both, undrain."""

    def setUp(self) -> None:
        self.device = _Device()
        self.device.files[LIVE_CONFIG_PATH] = serialize(
            _sample_config(), protocol=Protocol.JSON
        ).decode()
        self.switch = _make_fboss_switch(self.device)

    def written(self, path: str) -> BgpConfig:
        contents = dict(self.device.writes)[path]
        return deserialize(BgpConfig, contents.encode(), protocol=Protocol.JSON)

    async def test_writes_the_live_and_drain_configs(self) -> None:
        await setup_base_configs(self.switch)

        self.assertEqual(
            [LIVE_CONFIG_PATH, SOFTDRAIN_CONFIG_PATH],
            [path for path, _ in self.device.writes],
        )
        expected_live, expected_drain = generate_base_configs(_sample_config())
        self.assertEqual(expected_live, self.written(LIVE_CONFIG_PATH))
        self.assertEqual(expected_drain, self.written(SOFTDRAIN_CONFIG_PATH))

    async def test_policies_are_written_inline_in_both_configs(self) -> None:
        # OSS has no separate policy file today, so the policies have to travel
        # inside the config bgpd loads.
        await setup_base_configs(self.switch)

        for path in (LIVE_CONFIG_PATH, SOFTDRAIN_CONFIG_PATH):
            with self.subTest(path=path):
                self.assertEqual(
                    list(PROPAGATE_POLICIES),
                    list(_present(self.written(path).policies).bgp_policy_statements),
                )

    async def test_leaves_the_device_undrained(self) -> None:
        # The symlink may still point at a config that no longer exists, so the
        # device is put into a known state rather than left where it was.
        await setup_base_configs(self.switch)

        self.assertEqual(LIVE_CONFIG_PATH, self.device.symlink_target)
        self.assertEqual(
            [FbossSystemctlServiceName.BGP], self.device.restarted_services
        )

    async def test_undrain_happens_after_both_writes(self) -> None:
        # Undraining first would restart bgpd onto a config that is still the
        # old one, then leave the new one unloaded.
        await setup_base_configs(self.switch)

        self.assertEqual(2, len(self.device.writes))
        self.assertEqual(SOFTDRAIN_CONFIG_PATH, self.device.writes[-1][0])
        self.assertEqual(LIVE_CONFIG_PATH, self.device.symlink_target)

    async def test_restart_bgp_false_stages_without_restarting(self) -> None:
        await setup_base_configs(self.switch, restart_bgp=False)

        self.assertEqual(2, len(self.device.writes))
        self.assertEqual([], self.device.restarted_services)

    async def test_missing_live_config_raises_before_writing(self) -> None:
        del self.device.files[LIVE_CONFIG_PATH]

        with self.assertRaises(ConfigModifierError) as ctx:
            await setup_base_configs(self.switch)

        self.assertIn(LIVE_CONFIG_PATH, str(ctx.exception))
        self.assertEqual([], self.device.writes)

    async def test_unparseable_config_raises_before_writing(self) -> None:
        self.device.files[LIVE_CONFIG_PATH] = "not json at all"

        with self.assertRaises(ConfigModifierError) as ctx:
            await setup_base_configs(self.switch)

        self.assertIn(LIVE_CONFIG_PATH, str(ctx.exception))
        self.assertEqual([], self.device.writes)

    async def test_rejects_non_fboss_driver_before_reading(self) -> None:
        with patch(f"{_MODULE}._fboss_switch_cls", return_value=DrainUndrainTest):
            with self.assertRaises(ConfigModifierError) as ctx:
                await setup_base_configs(self.switch)

        self.assertIn("FbossSwitch", str(ctx.exception))
        self.assertEqual([], self.device.commands)
        self.assertEqual([], self.device.writes)


class OnboxDrainDriverMethodsTest(TestCase):
    """The FbossSwitch methods DrainUndrainStep calls for DrainHandler.LOCAL_DRAINER.

    Invoked unbound with a spec'd mock as ``self`` so the real method bodies run
    -- the point is to exercise them, not a double of them.
    """

    def setUp(self) -> None:
        self.device = _Device()
        self.switch = _make_fboss_switch(self.device)

        # async_onbox_drain_device delegates to self.async_onbox_softdrain_device,
        # which on a spec'd mock is a mock rather than the real method. Point it
        # back at the real one so the delegation actually executes. The side
        # effect has to be a coroutine function, not a lambda returning one --
        # AsyncMock awaits the former and merely returns the latter.
        async def real_softdrain() -> None:
            await FbossSwitch.async_onbox_softdrain_device(self.switch)

        # self.switch is typed as the real class so it can be passed as `self`
        # above; reach through to the mock to set a side effect on it.
        t.cast(
            AsyncMock, self.switch
        ).async_onbox_softdrain_device.side_effect = real_softdrain

    async def test_softdrain_selects_the_softdrain_config(self) -> None:
        await FbossSwitch.async_onbox_softdrain_device(self.switch)

        self.assertEqual(SOFTDRAIN_CONFIG_PATH, self.device.symlink_target)
        self.assertEqual(
            [FbossSystemctlServiceName.BGP], self.device.restarted_services
        )

    async def test_undrain_selects_the_live_config(self) -> None:
        await FbossSwitch.async_onbox_undrain_device(self.switch)

        self.assertEqual(LIVE_CONFIG_PATH, self.device.symlink_target)

    async def test_drain_and_softdrain_do_the_same_thing(self) -> None:
        # OSS has no hard drain; the two names must not diverge into one of them
        # quietly doing nothing.
        await FbossSwitch.async_onbox_drain_device(self.switch)
        via_drain = self.device.symlink_target

        self.device.symlink_target = ""
        await FbossSwitch.async_onbox_softdrain_device(self.switch)

        self.assertEqual(SOFTDRAIN_CONFIG_PATH, via_drain)
        self.assertEqual(via_drain, self.device.symlink_target)

    async def test_drain_warns_that_oss_drain_is_soft(self) -> None:
        # Internally this method name is a hard drain. The divergence has to be
        # visible in the logs of any run that hits it, not just in a docstring.
        with self.assertLogs("test_config_modifiers", level="WARNING") as logs:
            await FbossSwitch.async_onbox_drain_device(self.switch)

        self.assertTrue(
            any("SOFT" in line for line in logs.output),
            f"expected a soft-drain warning, got {logs.output}",
        )

    def test_overrides_the_abstract_no_ops(self) -> None:
        # AbstractSwitch declares both with `...` as the body, so losing these
        # overrides would not fail -- a LOCAL_DRAINER drain step would silently
        # succeed having done nothing. That is the failure this guards.
        for name in ("async_onbox_drain_device", "async_onbox_undrain_device"):
            with self.subTest(method=name):
                self.assertIsNot(
                    getattr(AbstractSwitch, name), getattr(FbossSwitch, name)
                )


# The policy section exactly as it is serialized into both config files. Kept at
# the bottom rather than beside its test because of its size; see
# PropagatePolicyTest.test_serialized_form_matches_the_golden for how to
# regenerate it.
_GOLDEN_PROPAGATE_POLICIES_JSON = """
{
  "as_paths": [],
  "aspath_lists": [],
  "bgp_policy_statements": [
    {
      "description": "TAAC: accept everything; depreference DRAIN-tagged routes",
      "name": "PROPAGATE_EVERYTHING_IN",
      "policy_entries": [
        {
          "description": "DRAIN community -> local-pref 25",
          "match_logic_type": 1,
          "name": "TERM_MATCH_DRAIN",
          "policy_action_entries": [
            {
              "set_local_pref": {
                "boolean_operator": 2,
                "description": "",
                "local_pref": 25,
                "name": ""
              },
              "type": 3
            }
          ],
          "policy_match_entries": {
            "description": "",
            "match_entries": [
              {
                "communities_filter": {
                  "boolean_operator": 2,
                  "communities": [
                    "65446:10"
                  ],
                  "description": "",
                  "name": "COMM_LIST_DRAIN"
                },
                "match_logic_type": 0,
                "type": 3
              }
            ],
            "match_logic_type": 1,
            "name": ""
          },
          "term_miss_action": 3
        },
        {
          "description": "Everything else -> local-pref 90",
          "match_logic_type": 1,
          "name": "TERM_DEFAULT_LIVE",
          "policy_action_entries": [
            {
              "set_local_pref": {
                "boolean_operator": 2,
                "description": "",
                "local_pref": 90,
                "name": ""
              },
              "type": 3
            }
          ],
          "policy_match_entries": {
            "description": "",
            "match_entries": [
              {
                "match_logic_type": 0,
                "type": 20
              }
            ],
            "match_logic_type": 1,
            "name": ""
          },
          "term_miss_action": 3
        }
      ],
      "policy_version": "1",
      "result": 1
    },
    {
      "description": "TAAC: advertise everything, tag LIVE",
      "name": "PROPAGATE_EVERYTHING_OUT",
      "policy_entries": [
        {
          "description": "Tag every advertised prefix LIVE",
          "match_logic_type": 1,
          "name": "TERM_TAG_LIVE",
          "policy_action_entries": [
            {
              "community_action": {
                "action_type": 1,
                "communities": [
                  "65446:30"
                ],
                "description": "",
                "name": ""
              },
              "type": 2
            }
          ],
          "policy_match_entries": {
            "description": "",
            "match_entries": [
              {
                "match_logic_type": 0,
                "type": 20
              }
            ],
            "match_logic_type": 1,
            "name": ""
          },
          "term_miss_action": 3
        }
      ],
      "policy_version": "1",
      "result": 1
    },
    {
      "description": "TAAC: advertise everything, strip LIVE, tag DRAIN",
      "name": "PROPAGATE_EVERYTHING_OUT_DRAIN",
      "policy_entries": [
        {
          "description": "Replace LIVE with DRAIN on every advertised prefix",
          "match_logic_type": 1,
          "name": "TERM_TAG_DRAIN",
          "policy_action_entries": [
            {
              "community_action": {
                "action_type": 3,
                "communities": [
                  "65446:30"
                ],
                "description": "",
                "name": ""
              },
              "type": 2
            },
            {
              "community_action": {
                "action_type": 1,
                "communities": [
                  "65446:10"
                ],
                "description": "",
                "name": ""
              },
              "type": 2
            }
          ],
          "policy_match_entries": {
            "description": "",
            "match_entries": [
              {
                "match_logic_type": 0,
                "type": 20
              }
            ],
            "match_logic_type": 1,
            "name": ""
          },
          "term_miss_action": 3
        }
      ],
      "policy_version": "1",
      "result": 1
    }
  ],
  "communities": [],
  "community_lists": [],
  "prefix_lists": []
}
"""
