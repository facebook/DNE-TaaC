#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

"""
OSS-safe BGP config modifiers for FBOSS devices.

Soft-drain and undrain a device without any Meta-internal dependency -- no
LocalDrainer, no config_selector, no COOP. The only primitive we rely on is the
launch convention: bgpd reads ``--config /dev/shm/fboss/bgpcpp_startup_config``,
which is a symlink.

A drain is therefore three things:

1. Update the ``/dev/shm/fboss`` drain markers.
2. Repoint the startup-config symlink at the corresponding config file.
3. Restart bgpd.

Both config files (live and soft-drain) must already exist on the device.
``setup_base_configs`` produces them: it reads the device's current BGP config,
replaces whatever policies it had with three generalized propagate policies,
points every peer group and peer at them, and writes back a live copy and a
soft-drain copy that differ only in their egress policy and drain state.
Drain/undrain then just selects between those two files.

Call these from a TAAC step or task with the device's driver::

    # step: Step.setUp already populated self.driver
    await setup_base_configs(self.driver)
    await drain_device(self.driver)

    # task: build one from the hostname
    driver = await async_get_device_driver(hostname)
    await drain_device(driver)
"""

import json
import logging
import typing as t

# Both of these imports resolve in OSS as well as internally. The module path is
# the thrift's `namespace py3`, not its location on disk, which is why
# bgp_policy.thrift -- at configerator/structs/neteng/bgp_policy/thrift/ -- is
# imported from ...neteng.robotron. github/thrift/CMakeLists.txt already
# generates both bindings under exactly these namespaces, from the copies
# mirrored into public facebook/fboss via neteng/fboss/bgp/public_tld/.
#
# @manual=//configerator/structs/neteng/fboss/bgp:bgp_config-python-types
# The pin is Buck-only (OSS builds with CMake): that OSS mirror is also a Buck
# target, bgp_config_oss-python-types, which emits the same Python module.
# autodeps picks the mirror, and having both in one binary is a module
# collision -- the same pin every other TAAC and COOP call site carries.
from configerator.structs.neteng.fboss.bgp.bgp_config.thrift_types import (
    BgpConfig,
    BgpNetwork,
    BgpPeer,
    PeerGroup,
)
from configerator.structs.neteng.robotron.bgp_policy.thrift_types import (
    BgpPolicies,
    BgpPolicyAction,
    BgpPolicyActionType,
    BgpPolicyAtomicMatch,
    BgpPolicyAtomicMatchType,
    BgpPolicyMatch,
    BgpPolicyStatement,
    BgpPolicyTerm,
    CommunityAction,
    CommunityActionType,
    CommunityList,
    DrainState,
    FlowControlAction,
    LocalPreference,
)
from taac.driver.abstract_switch import AbstractSwitch
from taac.driver.driver_constants import FbossSystemctlServiceName
from thrift.python.serializer import deserialize, Protocol, serialize

logger: logging.Logger = logging.getLogger(__name__)

# Peer groups and peers carry the same pair of policy-name fields and are
# retargeted identically; the TypeVar keeps _retarget from widening either one
# into a union at its call sites.
_PolicyHolder = t.TypeVar("_PolicyHolder", PeerGroup, BgpPeer)


# Drain markers and the bgpd startup-config symlink. Mirrors the layout in
# neteng/fboss/config_selector/fboss_config_selector.py so a device that does run
# the internal selector stays consistent with what we do here.
#
# This is not our choice of location: bgpd is launched with
# --config /dev/shm/fboss/bgpcpp_startup_config, so the path is a fixed FBOSS
# on-device contract we interoperate with rather than a scratch area we picked.
# patternlint-disable-next-line no-dev-shm-usage
FBOSS_DRAIN_DIR: str = "/dev/shm/fboss"
STARTUP_CONFIG_SYMLINK: str = f"{FBOSS_DRAIN_DIR}/bgpcpp_startup_config"
# Staging name for the atomic symlink swap, matching the selector's own
# ".{daemon}_startup_config" convention.
_HIDDEN_STARTUP_CONFIG_SYMLINK: str = f"{FBOSS_DRAIN_DIR}/.bgpcpp_startup_config"

MARKER_UNDRAINED: str = f"{FBOSS_DRAIN_DIR}/UNDRAINED"
MARKER_SOFT_DRAINED: str = f"{FBOSS_DRAIN_DIR}/SOFT_DRAINED"

COOP_DIR: str = "/etc/coop"
LIVE_CONFIG_PATH: str = f"{COOP_DIR}/bgpcpp.conf"
SOFTDRAIN_CONFIG_PATH: str = f"{COOP_DIR}/bgpcpp_softdrain.conf"

_UNDRAIN: str = "undrain"
_SOFT_DRAIN: str = "soft-drain"
_BASE_CONFIG_SETUP: str = "set up base configs for"

# The two communities that carry drain state between devices. A drained device
# tags what it advertises with DRAIN instead of LIVE; every device depreferences
# DRAIN-tagged routes on ingress. Values match the fleet-wide meanings in
# neteng/fboss/bgp/if/bgp_route_types.thrift, so a TAAC-configured device and a
# COOP-configured neighbour agree on what a drain looks like.
COMMUNITY_LIVE: str = "65446:30"
COMMUNITY_DRAIN: str = "65446:10"

# Local preferences the ingress policy assigns. The gap only has to be wide
# enough that any LIVE path beats any DRAIN path; these mirror the values used
# for the same purpose internally.
LOCAL_PREF_LIVE: int = 90
LOCAL_PREF_DRAIN: int = 25

POLICY_PROPAGATE_IN: str = "PROPAGATE_EVERYTHING_IN"
POLICY_PROPAGATE_OUT: str = "PROPAGATE_EVERYTHING_OUT"
POLICY_PROPAGATE_OUT_DRAIN: str = "PROPAGATE_EVERYTHING_OUT_DRAIN"

_POLICY_VERSION: str = "1"

# Emitted by the file-existence probe. `test -f` alone communicates via exit code,
# which does not survive every driver transport, so echo a sentinel instead.
_FILE_EXISTS_SENTINEL: str = "__FILE_EXISTS__"


class ConfigModifierError(Exception):
    """A drain/undrain precondition failed, or the transition did not take effect."""


def _fboss_switch_cls() -> type:
    """Resolve FbossSwitch lazily.

    Imported inside a function rather than at module scope because drain/undrain
    *are* now exposed as driver methods: ``FbossSwitch.async_onbox_drain_device``
    calls into this module, so fboss_switch_lib depends on config_modifiers_lib
    and the reverse dep cannot be declared -- Buck rejects the cycle. Hence the
    suppression below: pyre resolves imports through the Buck source database and
    cannot see a dep that is deliberately absent.

    Safe regardless of the missing dep. Anything that reaches this guard is
    holding an FbossSwitch, so the module is already in sys.modules by the time
    the import runs.
    """
    # pyre-ignore[21]: see above -- declaring this dep would create a Buck cycle.
    from taac.driver.fboss_switch import FbossSwitch

    return FbossSwitch


def _assert_fboss_device(switch: AbstractSwitch, state_name: str) -> None:
    """Reject drivers whose devices do not use the FBOSS bgpd launch convention.

    Everything here -- the ``/dev/shm/fboss`` markers, the ``/etc/coop/bgpcpp*``
    configs, ``systemctl restart bgpd`` -- is specific to a device running FBOSS
    bgpcpp under systemd. On an Arista or Cisco driver these commands are
    meaningless, and without this check the failure surfaces as a confusing shell
    error partway through instead of a clear rejection up front.

    ``FbossSwitchInternal`` subclasses ``FbossSwitch``, so internal runs pass.
    ``AristaFbossSwitch`` deliberately does not: it subclasses ``AristaSwitch``
    and drives bgpcpp through /mnt/flash + run_bgpcpp.sh under Arista daemon
    control, so none of the paths below apply to it.
    """
    if not isinstance(switch, _fboss_switch_cls()):
        raise ConfigModifierError(
            f"Cannot {state_name} {switch.hostname}: {type(switch).__name__} is not "
            "an FbossSwitch. Drain/undrain drives the FBOSS bgpd launch convention "
            "(/dev/shm/fboss markers, /etc/coop/bgpcpp* configs, systemctl bgpd), "
            "which does not apply to this device."
        )


async def _async_file_exists(switch: AbstractSwitch, path: str) -> bool:
    """Check for a regular file using only the AbstractSwitch API.

    ``FbossSwitch.async_check_if_file_exists`` would be the obvious call, but it
    is not on ``AbstractSwitch`` -- and steps and tasks hold their driver as an
    ``AbstractSwitch``, so depending on it would push a type-ignore onto every
    call site. The shell probe below is what the internal driver mixin falls back
    to for the same reason: ``test -f`` reports through its exit code, which does
    not survive every transport, so echo a sentinel and look for that instead.
    """
    output = await switch.async_run_cmd_on_shell(
        f"test -f {path} && echo {_FILE_EXISTS_SENTINEL} || true"
    )
    return _FILE_EXISTS_SENTINEL in (output or "")


async def _verify_startup_config(
    switch: AbstractSwitch, expected_config: str, state_name: str
) -> None:
    """Confirm the startup-config symlink still points where we put it.

    On a device that runs the internal ``config_selector`` at bgpd's
    ``ExecStartPre``, the selector re-derives this symlink from the drain markers
    on every restart. It forces the undrained config when the device reports as
    non-drainable, which would silently undo a drain. Reading the link back after
    the restart turns that into a loud failure instead of a test that quietly
    measured nothing.
    """
    # Plain readlink, not readlink -f: we want the literal target we set, and the
    # coop config paths can themselves be symlinks that -f would resolve through
    # (fboss2's config session keeps /etc/coop/bgpcpp.conf pointing into
    # bgpcpp/bgpcpp.conf).
    actual = await switch.async_run_cmd_on_shell(f"readlink {STARTUP_CONFIG_SYMLINK}")
    actual = (actual or "").strip()

    if actual != expected_config:
        raise ConfigModifierError(
            f"{state_name} of {switch.hostname} did not take effect: "
            f"{STARTUP_CONFIG_SYMLINK} points at {actual or '<nothing>'}, expected "
            f"{expected_config}. If an on-device config_selector runs at bgpd "
            "ExecStartPre, it may have re-derived the symlink from the drain "
            "markers -- check whether this device reports as drainable."
        )


async def drain_device(switch: AbstractSwitch, restart_bgp: bool = True) -> None:
    """Soft-drain a device: advertise DRAIN-tagged routes instead of LIVE.

    Routes are re-tagged, never withdrawn, so the drained path stays a viable
    backup while neighbours depreference it.

    Args:
        switch: driver for the device to drain.
        restart_bgp: restart bgpd so the new config takes effect. Pass False to
            batch several changes and restart once at the end -- until bgpd is
            restarted the device is still running its previous config.

    Raises:
        ConfigModifierError: the soft-drain config is missing, or the symlink did
            not survive the restart (see ``_verify_startup_config``).
    """
    await _apply_drain_state(
        switch,
        target_marker=MARKER_SOFT_DRAINED,
        opposite_marker=MARKER_UNDRAINED,
        target_config=SOFTDRAIN_CONFIG_PATH,
        state_name=_SOFT_DRAIN,
        restart_bgp=restart_bgp,
    )


async def undrain_device(switch: AbstractSwitch, restart_bgp: bool = True) -> None:
    """Undrain a device: return to advertising LIVE-tagged routes.

    Args:
        switch: driver for the device to undrain.
        restart_bgp: restart bgpd so the new config takes effect.

    Raises:
        ConfigModifierError: the live config is missing, or the symlink did not
            survive the restart.
    """
    await _apply_drain_state(
        switch,
        target_marker=MARKER_UNDRAINED,
        opposite_marker=MARKER_SOFT_DRAINED,
        target_config=LIVE_CONFIG_PATH,
        state_name=_UNDRAIN,
        restart_bgp=restart_bgp,
    )


async def _apply_drain_state(
    switch: AbstractSwitch,
    *,
    target_marker: str,
    opposite_marker: str,
    target_config: str,
    state_name: str,
    restart_bgp: bool,
) -> None:
    """Shared drain/undrain worker. The two directions differ only in arguments.

    Keyword-only (the bare ``*``) because four of the five arguments are plain
    strings and two of them are near-identical marker paths -- a positional call
    that transposed target_marker and opposite_marker would produce a "drain"
    that silently leaves the device live.
    """
    hostname = switch.hostname
    _assert_fboss_device(switch, state_name)

    if not await _async_file_exists(switch, target_config):
        raise ConfigModifierError(
            f"Cannot {state_name} {hostname}: BGP config {target_config} is missing. "
            "Generate the base configs first -- drain/undrain only selects between "
            "configs that already exist on the device."
        )

    # Order matters and is not merely defensive: the selector resolves markers as
    # UNDRAINED > WARM_DRAINED > SOFT_DRAINED > DRAINED, so leaving UNDRAINED in
    # place while adding SOFT_DRAINED would silently keep the device live. Removing
    # the opposite marker and setting the target in one invocation also avoids a
    # window where both or neither marker exists.
    switch.logger.info(
        f"[{state_name}] {hostname}: clearing {opposite_marker}, setting {target_marker}"
    )
    await switch.async_run_cmd_on_shell(
        f"rm -f {opposite_marker} && touch {target_marker}"
    )

    # Symlink into a staging name, then rename over the real one. rename(2) is
    # atomic, so bgpd can never observe a missing or half-written symlink -- this
    # is the same symlink_to()-then-rename() idiom fboss_config_selector.py uses.
    # `ln -sf` alone would not do: it unlinks the destination before recreating it.
    #
    # -n on the ln so an existing symlink-to-directory is replaced rather than
    # dereferenced (without it, ln would create the link *inside* that directory),
    # and -T on the mv for the same reason.
    switch.logger.info(
        f"[{state_name}] {hostname}: pointing {STARTUP_CONFIG_SYMLINK} at {target_config}"
    )
    await switch.async_run_cmd_on_shell(
        f"ln -sfn {target_config} {_HIDDEN_STARTUP_CONFIG_SYMLINK} && "
        f"mv -Tf {_HIDDEN_STARTUP_CONFIG_SYMLINK} {STARTUP_CONFIG_SYMLINK}"
    )

    if restart_bgp:
        switch.logger.info(f"[{state_name}] {hostname}: restarting bgpd")
        await switch.async_restart_service(FbossSystemctlServiceName.BGP)

    await _verify_startup_config(switch, target_config, state_name)


# ---------------------------------------------------------------------------
# Policy construction
#
# Only the fields bgpd actually reads are populated. bgp_policy.thrift carries
# a "modern" mirror for several of them -- policy_matches for
# policy_match_entries, community_list for communities_filter, action_type for
# type -- but bgpd's policy engine reads the older set exclusively
# (neteng/fboss/bgp/cpp/policy/PolicyTerm.cpp). Populating both would double the
# size of an already large config and let the two copies drift.
# ---------------------------------------------------------------------------


def _always_match() -> BgpPolicyMatch:
    """A match that every prefix satisfies.

    An empty ``match_entries`` would behave identically -- bgpd treats a term
    with no conditions as matching everything -- but the explicit ALWAYS atom
    says "catch-all" rather than "someone forgot to fill this in".
    """
    return BgpPolicyMatch(
        match_entries=[BgpPolicyAtomicMatch(type=BgpPolicyAtomicMatchType.ALWAYS)]
    )


def _community_match(name: str, community: str) -> BgpPolicyMatch:
    """Match prefixes carrying ``community``.

    ``communities_filter`` is mandatory for a COMMUNITY_LIST match and its
    community list must be non-empty: bgpd dereferences it unconditionally and
    throws ``The attribute "communities" is empty`` otherwise
    (PolicyMatch.cpp CommunityMatch).
    """
    return BgpPolicyMatch(
        match_entries=[
            BgpPolicyAtomicMatch(
                type=BgpPolicyAtomicMatchType.COMMUNITY_LIST,
                communities_filter=CommunityList(name=name, communities=[community]),
            )
        ]
    )


def _set_local_pref_action(local_pref: int) -> BgpPolicyAction:
    return BgpPolicyAction(
        type=BgpPolicyActionType.SET_LOCAL_PREF,
        set_local_pref=LocalPreference(local_pref=local_pref),
    )


def _community_action(
    community: str, action_type: CommunityActionType
) -> BgpPolicyAction:
    """Add or remove ``community`` on advertisement.

    Add/remove is ``CommunityAction.action_type`` (ADD/SET/REMOVE), not the
    ``BgpPolicyAction.action_type`` field one directory up in the struct -- that
    one is only read for the ExtCommunity path.
    """
    return BgpPolicyAction(
        type=BgpPolicyActionType.COMMUNITY_LIST,
        community_action=CommunityAction(
            communities=[community], action_type=action_type
        ),
    )


def build_propagate_policies() -> tuple[BgpPolicyStatement, ...]:
    """Build the three policies every TAAC-managed peer group points at.

    ``PROPAGATE_EVERYTHING_IN``
        Accept everything, but depreference anything a drained device sent us.
        The DRAIN term must come first: ``PROPAGATE_EVERYTHING_OUT`` only adds
        LIVE, it does not strip DRAIN, so a route learned from a drained device
        and re-advertised by a healthy one carries *both* communities. Evaluated
        in this order it lands on LOCAL_PREF_DRAIN, which is the point -- drain
        depreference propagates along the path rather than stopping at the first
        healthy hop.

    ``PROPAGATE_EVERYTHING_OUT``
        Advertise everything, tagged LIVE.

    ``PROPAGATE_EVERYTHING_OUT_DRAIN``
        Advertise everything, tagged DRAIN and with LIVE stripped. Routes are
        re-tagged, never withdrawn, so the drained device stays a usable backup.

    No term needs an explicit PERMIT action: a term that matches permits by
    default (PolicyTerm.cpp, "0 is fine as we default to permit"), and
    ``term_miss_action`` already defaults to NEXT_TERM.
    """
    return (
        BgpPolicyStatement(
            name=POLICY_PROPAGATE_IN,
            description="TAAC: accept everything; depreference DRAIN-tagged routes",
            policy_version=_POLICY_VERSION,
            result=FlowControlAction.ACCEPT,
            policy_entries=[
                BgpPolicyTerm(
                    name="TERM_MATCH_DRAIN",
                    description=(f"DRAIN community -> local-pref {LOCAL_PREF_DRAIN}"),
                    policy_match_entries=_community_match(
                        "COMM_LIST_DRAIN", COMMUNITY_DRAIN
                    ),
                    policy_action_entries=[_set_local_pref_action(LOCAL_PREF_DRAIN)],
                ),
                BgpPolicyTerm(
                    name="TERM_DEFAULT_LIVE",
                    description=f"Everything else -> local-pref {LOCAL_PREF_LIVE}",
                    policy_match_entries=_always_match(),
                    policy_action_entries=[_set_local_pref_action(LOCAL_PREF_LIVE)],
                ),
            ],
        ),
        BgpPolicyStatement(
            name=POLICY_PROPAGATE_OUT,
            description="TAAC: advertise everything, tag LIVE",
            policy_version=_POLICY_VERSION,
            result=FlowControlAction.ACCEPT,
            policy_entries=[
                BgpPolicyTerm(
                    name="TERM_TAG_LIVE",
                    description="Tag every advertised prefix LIVE",
                    policy_match_entries=_always_match(),
                    policy_action_entries=[
                        _community_action(COMMUNITY_LIVE, CommunityActionType.ADD)
                    ],
                )
            ],
        ),
        BgpPolicyStatement(
            name=POLICY_PROPAGATE_OUT_DRAIN,
            description="TAAC: advertise everything, strip LIVE, tag DRAIN",
            policy_version=_POLICY_VERSION,
            result=FlowControlAction.ACCEPT,
            policy_entries=[
                BgpPolicyTerm(
                    name="TERM_TAG_DRAIN",
                    description="Replace LIVE with DRAIN on every advertised prefix",
                    policy_match_entries=_always_match(),
                    # Order is load-bearing and is set by list position, not by
                    # sequence_number, which bgpd does not read: actions of the
                    # same type are applied in the order configured. REMOVE must
                    # precede ADD or a prefix that already carries LIVE keeps it
                    # and ends up advertised as both live and drained.
                    policy_action_entries=[
                        _community_action(COMMUNITY_LIVE, CommunityActionType.REMOVE),
                        _community_action(COMMUNITY_DRAIN, CommunityActionType.ADD),
                    ],
                )
            ],
        ),
    )


# Built once at import and reused for every device and both config copies.
# thrift-python copies a struct when it goes into a container rather than
# aliasing it, and the structs are immutable either way, so no caller can reach
# back and disturb this value -- no defensive copying needed.
PROPAGATE_POLICIES: tuple[BgpPolicyStatement, ...] = build_propagate_policies()


# ---------------------------------------------------------------------------
# Config transforms
#
# All pure: they take a BgpConfig and return a new one. thrift-python structs
# are immutable, so calling an instance with keyword arguments returns a
# modified copy and the caller's config is never touched.
# ---------------------------------------------------------------------------


def _retarget(target: _PolicyHolder, egress_policy: str) -> _PolicyHolder:
    """Point one peer group or peer at the propagate policies.

    Shared by both so the pairing is stated once: ingress is always
    PROPAGATE_EVERYTHING_IN, and only egress distinguishes live from drained.
    """
    return target(
        ingress_policy_name=POLICY_PROPAGATE_IN, egress_policy_name=egress_policy
    )


def _clear_policy(network: BgpNetwork) -> BgpNetwork:
    return network(policy_name=None)


def _reset_policies(config: BgpConfig) -> BgpConfig:
    """Replace the config's entire policy section with the three propagate policies.

    The whole ``BgpPolicies`` container goes, not just the statements: the
    auxiliary lists (community lists, as-path lists, prefix lists) only existed
    to serve the policies being removed, and our three define their communities
    inline. ``obj_uuid`` is carried over because it identifies the container
    itself rather than anything in it.
    """
    existing = config.policies
    removed = len(existing.bgp_policy_statements) if existing else 0
    logger.info(
        f"Replacing {removed} policy statement(s) with "
        f"{len(PROPAGATE_POLICIES)} propagate policies"
    )
    return config(
        policies=BgpPolicies(
            bgp_policy_statements=list(PROPAGATE_POLICIES),
            obj_uuid=existing.obj_uuid if existing else None,
        )
    )


def _retarget_peer_groups(config: BgpConfig, egress_policy: str) -> BgpConfig:
    """Point every peer group at the propagate policies.

    Every one, with no role resolution: a soft-drain is a whole-device
    operation, so a peer group left on its original policy would keep
    advertising LIVE while the rest of the device drains.
    """
    peer_groups = config.peer_groups
    if not peer_groups:
        logger.warning("Config has no peer groups to retarget")
        return config

    logger.info(
        f"Retargeting {len(peer_groups)} peer group(s) to "
        f"({POLICY_PROPAGATE_IN}, {egress_policy})"
    )
    return config(
        peer_groups=[_retarget(peer_group, egress_policy) for peer_group in peer_groups]
    )


def _retarget_peers(config: BgpConfig, egress_policy: str) -> BgpConfig:
    """Point every peer at the propagate policies.

    Peer-level policy names override the peer group's, so a peer still naming a
    policy we just deleted would both dangle and escape the drain.
    """
    peers = config.peers
    if not peers:
        return config

    logger.info(f"Retargeting {len(peers)} peer(s) to egress {egress_policy}")
    return config(peers=[_retarget(peer, egress_policy) for peer in peers])


def _clear_network_policies(config: BgpConfig) -> BgpConfig:
    """Drop policy references from originated networks.

    These are origination policies, and unlike propagation they have no live and
    drain variant -- there is nothing correct to repoint them at once the
    original policies are gone, so the reference is cleared rather than left
    dangling. This does change the attributes of originated routes, which is why
    the count is logged.
    """
    cleared = sum(
        1
        for network in list(config.networks4) + list(config.networks6)
        if network.policy_name
    )
    if not cleared:
        return config

    logger.info(f"Clearing policy_name from {cleared} originated network(s)")
    return config(
        networks4=[_clear_policy(network) for network in config.networks4],
        networks6=[_clear_policy(network) for network in config.networks6],
    )


def _set_drain_state(config: BgpConfig, drain_state: DrainState) -> BgpConfig:
    """Record the config's drain state.

    Declarative only -- bgpd's policy engine never reads it, and drain behaviour
    comes entirely from which egress policy the peer groups name. It is set so
    that a drain-state query on the device reports the truth, which makes it
    usable as a test assertion.
    """
    return config(drain_state=drain_state)


def _generate_variant(
    base: BgpConfig, egress_policy: str, drain_state: DrainState
) -> BgpConfig:
    """Build one of the two config variants from the shared base.

    Both variants go through this, so the live and drain copies cannot drift
    into differing by anything other than these two arguments.
    """
    config = _retarget_peer_groups(base, egress_policy)
    config = _retarget_peers(config, egress_policy)
    return _set_drain_state(config, drain_state)


def generate_base_configs(config: BgpConfig) -> tuple[BgpConfig, BgpConfig]:
    """Derive the live and soft-drain configs from a device's current config.

    The two outputs are identical except for the egress policy every peer group
    and peer names, and the declared drain state. Policies themselves are
    byte-identical in both, which is what makes drain a file swap rather than a
    config rebuild.

    Args:
        config: the device's current BGP config. Not modified.

    Returns:
        ``(live_config, soft_drain_config)``.
    """
    base = _clear_network_policies(_reset_policies(config))
    return (
        _generate_variant(base, POLICY_PROPAGATE_OUT, DrainState.UNDRAINED),
        _generate_variant(base, POLICY_PROPAGATE_OUT_DRAIN, DrainState.SOFT_DRAINED),
    )


def _deserialize_config(raw_config: str, hostname: str) -> BgpConfig:
    """Parse a bgpd config file.

    Protocol.JSON is SimpleJSON, which is what bgpd reads and writes
    (SimpleJSONSerializer in Config.cpp / ConfigManager.cpp). Protocol.COMPACT_JSON
    would parse and serialize using field ids instead of names and would not
    round-trip against the daemon.
    """
    try:
        return deserialize(BgpConfig, raw_config.encode(), protocol=Protocol.JSON)
    except Exception as exc:
        raise ConfigModifierError(
            f"Cannot {_BASE_CONFIG_SETUP} {hostname}: {LIVE_CONFIG_PATH} is not a "
            f"parseable BGP config ({exc})."
        ) from exc


def _serialize_config(config: BgpConfig) -> str:
    """Serialize a config as indented JSON, newline-terminated.

    thrift's SimpleJSON writer emits the whole document on a single line. At the
    ~19 KB a real config runs to, that makes the file useless to read on the
    box: `cat` gives one unbroken line and `diff` reports the whole file as
    changed for a one-field edit. COOP's own configs are indented, so matching
    that keeps what we write looking like what the device already has.

    Re-indenting through `json` is a formatting change only -- the parsed
    document is identical, key order is preserved (dicts keep insertion order
    and `sort_keys` is off), and bgpd's SimpleJSON reader ignores whitespace
    between tokens. `ensure_ascii=False` so a non-ASCII peer description
    survives as itself instead of being escaped to \\uXXXX.
    """
    compact = serialize(config, protocol=Protocol.JSON).decode()
    return json.dumps(json.loads(compact), indent=2, ensure_ascii=False) + "\n"


async def _async_write_config(
    switch: AbstractSwitch, config: BgpConfig, remote_path: str
) -> None:
    """Serialize a config and write it to the device."""
    contents = _serialize_config(config)
    # pyre-ignore[16]: FbossSwitch-only, and _assert_fboss_device has already run.
    await switch.async_write_file_on_device(contents, remote_path)


async def setup_base_configs(switch: AbstractSwitch, restart_bgp: bool = True) -> None:
    """Generate both BGP configs on a device and leave it undrained.

    Reads the device's live config, rewrites its policies into the three
    generalized propagate policies, and writes back a live copy and a soft-drain
    copy. Run this once before any drain/undrain: those only ever select between
    the two files this produces.

    Note that the live config is written back to the same path it was read from,
    replacing it. On a device where COOP manages ``/etc/coop/bgpcpp.conf``, COOP
    may re-materialize its own version later and undo this.

    Args:
        switch: driver for the device to configure.
        restart_bgp: restart bgpd so the new live config takes effect. Pass
            False to stage the files without disturbing a running session.

    Raises:
        ConfigModifierError: the device has no live config to read, or it could
            not be parsed.
    """
    hostname = switch.hostname
    _assert_fboss_device(switch, _BASE_CONFIG_SETUP)

    if not await _async_file_exists(switch, LIVE_CONFIG_PATH):
        raise ConfigModifierError(
            f"Cannot {_BASE_CONFIG_SETUP} {hostname}: {LIVE_CONFIG_PATH} is missing. "
            "The device must already be running a BGP config -- this generates the "
            "drain variants of an existing config, it does not create one."
        )

    switch.logger.info(f"{hostname}: reading BGP config from {LIVE_CONFIG_PATH}")
    raw_config = await switch.async_read_file(LIVE_CONFIG_PATH)
    config = _deserialize_config(raw_config, hostname)

    live_config, drain_config = generate_base_configs(config)

    for target_config, path in (
        (live_config, LIVE_CONFIG_PATH),
        (drain_config, SOFTDRAIN_CONFIG_PATH),
    ):
        switch.logger.info(f"{hostname}: writing {path}")
        await _async_write_config(switch, target_config, path)

    # Leave the device in a known state rather than wherever its markers happened
    # to point: the symlink may still reference a config that no longer exists.
    await undrain_device(switch, restart_bgp=restart_bgp)
