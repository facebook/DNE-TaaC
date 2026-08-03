# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

# pyre-unsafe

import ipaddress
import typing as t

from neteng.fboss.bgp_thrift.types import TBgpPeerState
from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.health_check.health_check import types as hc_types


_KNOWN_GROUP_STATES = frozenset({"UNINITIALIZED", "IDLE", "READY", "WAITING"})


def _group_state_name(value: t.Any) -> str:
    raw = getattr(value, "name", value)
    return str(raw or "").rsplit(".", 1)[-1].upper()


def _validate_out_delay_expectations(
    hostname: str,
    groups: t.Iterable[t.Any],
    expected_by_substring: t.Mapping[str, int],
) -> list[str]:
    groups_by_peer_group: dict[str, list[t.Any]] = {}
    missing_peer_group_name_ids: list[t.Any] = []
    for group in groups:
        group_key = getattr(group, "group_key", None)
        if group_key is None:
            missing_peer_group_name_ids.append(getattr(group, "group_id", None))
            continue
        peer_group_name = getattr(group_key, "peer_group_name", None)
        if isinstance(peer_group_name, str) and peer_group_name:
            groups_by_peer_group.setdefault(peer_group_name, []).append(group)
        else:
            missing_peer_group_name_ids.append(getattr(group, "group_id", None))

    failures: list[str] = []
    if expected_by_substring and missing_peer_group_name_ids:
        failures.append(
            f"Cannot validate IAR out_delay_seconds on {hostname}: update groups "
            f"{missing_peer_group_name_ids} have missing or empty peer_group_name."
        )
        if not groups_by_peer_group:
            failures.append(
                f"No update groups matched any expected IAR selector on {hostname}; "
                f"expected selectors {sorted(expected_by_substring)}."
            )
            return failures
    observed_names = sorted(groups_by_peer_group)
    for substring, expected_seconds in sorted(expected_by_substring.items()):
        matching_names = [name for name in observed_names if substring in name]
        if not matching_names:
            failures.append(
                f"IAR selector '{substring}' matches no update-group "
                f"peer_group_name on {hostname}; observed {observed_names}."
            )
            continue
        if len(matching_names) != 1:
            failures.append(
                f"IAR selector '{substring}' is ambiguous on {hostname}; it "
                f"matches peer_group_names {matching_names}."
            )
            continue

        peer_group_name = matching_names[0]
        for group in groups_by_peer_group[peer_group_name]:
            actual_seconds = getattr(group.group_key, "out_delay_seconds", None)
            if isinstance(actual_seconds, bool) or not isinstance(actual_seconds, int):
                failures.append(
                    f"Peer-group '{peer_group_name}' update group {group.group_id} "
                    f"has no valid out_delay_seconds key on {hostname}; expected "
                    f"{expected_seconds}."
                )
            elif actual_seconds != expected_seconds:
                failures.append(
                    f"Peer-group '{peer_group_name}' update group {group.group_id} "
                    f"has out_delay_seconds={actual_seconds} on {hostname}; "
                    f"expected {expected_seconds}."
                )
    return failures


class BgpUpdateGroupHealthCheck(AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]):
    """
    Verify BGP++ Update Group membership, size, and policy.

    Backed by the ``getUpdateGroupInfo`` thrift API (the same data shown by
    ``show bgpcpp update-group``), so it reads the *actual* grouping the
    UpdateGroupManager computed. Because that API hardcodes per-peer
    ``session_state`` to IDLE (see PeerManagerUtils.cpp), the check cross-
    references ``getBgpSessions`` (which carries the real BGP session state) and
    intersects by peer address to determine which update-group members are
    actually ESTABLISHED.

    The three things we care about per the Update Group test plan are: the
    number of update groups, the number of ESTABLISHED members in each group,
    and the egress policy name each group was keyed on.

    A peer-group is NOT guaranteed to map to a single update group: the update
    group is keyed on ``TUpdateGroupKey``, of which ``peer_group_name`` is only
    one field. Peers in the same peer-group split into separate update groups
    when they differ in any other key dimension (negotiated AFI/SAFI, add-path,
    RFC5549 extended nexthop, 4-byte ASN capability, per-peer egress policy
    override, out-delay, RR-client, link-bandwidth mode, etc.). So this check
    treats each peer-group as mapping to ONE OR MORE update groups and asserts
    over that whole set -- it never fails merely because a peer-group spans
    multiple groups.

    Reusable across Update Group test cases. Configurable via ``check_params``:

      - ``expect_enabled`` (bool, default True): assert the BGP++
        ``enable_update_group`` feature is on.
      - ``peer_group_substrings`` (list[str]): peer-group substrings (e.g.
        ``["EB-EB-V6", "EB-FA-V6", "BGP-MON"]``) matched against each update
        group's ``group_key.peer_group_name`` or its peers' descriptions. Each
        must match at least one update group with >= 1 ESTABLISHED member
        (cross-referenced with getBgpSessions) -- else FAIL (the peer-group is
        down). A peer-group may map to multiple update groups; not a failure.
      - ``expected_member_counts`` (dict[str, int], default {}): substring ->
        expected TOTAL number of ESTABLISHED members across ALL update groups
        the peer-group forms (cross-referenced with getBgpSessions).
      - ``expected_policy_names`` (dict[str, list[str]], default {}): substring
        -> the EXACT SET of egress policy names (``group_key.egress_policy_name``)
        the peer-group's update groups must be keyed on. A peer-group forms one
        update group per distinct egress policy, so this is a set, not a single
        value: ``{"EB-EB-V6": ["IBGP-V6-EGRESS"]}`` for a single-policy
        peer-group, ``{"EB-FA-V6": ["A", "B"]}`` for one with two.
      - ``expected_group_count`` (optional int): if set, asserts the total
        number of update groups on the device equals this value.
      - ``expected_group_states`` (list[str], default omitted): when set,
        asserts every update group on the device is in one of these operational
        states. This is intentionally global rather than peer-group scoped so
        an unhealthy unselected group cannot escape the check.
      - ``expected_afi_by_substring`` (dict[str, str], default {}): substring ->
        ``"ipv4"`` | ``"ipv6"``; asserts every update group the peer-group maps
        to negotiates ONLY that address family. Directly verifies dual-stack
        isolation (UG spec 2.9.4): IPv4 and IPv6 peers must live in separate,
        AFI-pure update groups (from ``TUpdateGroupKey.afi_ipv4_negotiated`` /
        ``afi_ipv6_negotiated``), so a v4 route operation can never be
        distributed through the v6 group. A group negotiating BOTH AFIs (or the
        wrong one) is a leak and FAILs.
      - ``expected_out_delay_seconds_by_substring`` (dict[str, int], default
        {}): substring -> expected out-delay seconds. Each selector must match
        exactly one authoritative ``group_key.peer_group_name`` and every
        update group for that peer-group must carry the exact value. IAR
        (Immediate Advertisement of Routes) requires zero.

    All configured assertions are evaluated in a single run; every failure is
    collected and reported together (the check does NOT stop at the first
    failure), so one run surfaces every problem at once. A failed thrift query
    still returns ERROR immediately, since no assertion can run without data.

    OS: Arista (EOS / ARISTA_FBOSS).
    """

    CHECK_NAME = hc_types.CheckName.BGP_UPDATE_GROUP_CHECK
    OPERATING_SYSTEMS = [
        # "FBOSS",
        "EOS",
    ]

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        hostname = obj.name
        expect_enabled = check_params.get("expect_enabled", True)
        peer_group_substrings = check_params.get("peer_group_substrings", [])
        expected_member_counts = check_params.get("expected_member_counts") or {}
        expected_policy_names = check_params.get("expected_policy_names") or {}
        expected_group_count = check_params.get("expected_group_count")
        raw_expected_group_states = check_params.get("expected_group_states")
        if "expected_group_states" in check_params and (
            not isinstance(raw_expected_group_states, list)
            or not raw_expected_group_states
        ):
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message=(
                    "expected_group_states must be a non-empty list of known "
                    f"Update Group states; got {raw_expected_group_states!r}"
                ),
            )
        expected_group_states = {
            _group_state_name(state) for state in (raw_expected_group_states or ())
        }
        unknown_expected_states = expected_group_states - _KNOWN_GROUP_STATES
        if unknown_expected_states:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message=(
                    "expected_group_states contains unknown states "
                    f"{sorted(unknown_expected_states)}; expected one of "
                    f"{sorted(_KNOWN_GROUP_STATES)}"
                ),
            )
        expect_empty_peer_groups = check_params.get("expect_empty_peer_groups") or []
        expected_afi_by_substring = check_params.get("expected_afi_by_substring") or {}
        expected_out_delay_seconds_by_substring = (
            check_params.get("expected_out_delay_seconds_by_substring") or {}
        )

        try:
            # pyrefly: ignore [missing-attribute]
            resp = await self.driver.async_get_update_group_info()
        except Exception as e:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message=f"Unable to query update-group info from {hostname}: {e}",
            )

        # getUpdateGroupInfo hardcodes per-peer ``session_state`` to IDLE (see
        # PeerManagerUtils.cpp TODO), so it cannot tell us which update-group
        # members are actually ESTABLISHED. Cross-reference getBgpSessions (which
        # carries the real BGP session state) and intersect by peer address.
        try:
            # pyrefly: ignore [missing-attribute]
            sessions = await self.driver.async_get_bgp_sessions()
        except Exception as e:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message=f"Unable to query BGP sessions from {hostname}: {e}",
            )

        def _norm(addr: t.Optional[str]) -> str:
            if addr is None:
                return ""
            try:
                return str(ipaddress.ip_address(addr))
            except ValueError:
                return addr

        established_addrs = {
            _norm(s.peer_addr)
            for s in (sessions or [])
            if s.peer is not None and s.peer.peer_state == TBgpPeerState.ESTABLISHED
        }

        # Accumulate every failed assertion so a single run reports them all,
        # rather than stopping at the first failure.
        failures: t.List[str] = []

        if expect_enabled and not resp.enable_update_group:
            failures.append(
                f"BGP++ update_group is NOT enabled on {hostname} "
                f"(enable_update_group=False)."
            )

        groups = resp.update_groups or []
        id_to_group = {group.group_id: group for group in groups}
        failures.extend(
            _validate_out_delay_expectations(
                hostname,
                groups,
                expected_out_delay_seconds_by_substring,
            )
        )
        if expected_group_states:
            unexpected_group_states = []
            for group in groups:
                raw_state = getattr(group, "group_state", None)
                state = _group_state_name(raw_state) or "<missing>"
                if state not in expected_group_states:
                    unexpected_group_states.append(
                        f"group_id={getattr(group, 'group_id', None)!r} state={state!r}"
                    )
            if unexpected_group_states:
                failures.append(
                    f"Update groups on {hostname} have unexpected operational "
                    f"states: {', '.join(unexpected_group_states)}; expected every "
                    f"group state to be one of {sorted(expected_group_states)}."
                )

        def _group_afi(gid: int) -> str:
            """Address family an update group negotiates, from its
            ``TUpdateGroupKey``: ``"ipv4"``/``"ipv6"`` for an AFI-pure group,
            ``"both"`` if it negotiated both (a dual-stack-isolation leak),
            ``"none"`` if neither."""
            gk = id_to_group[gid].group_key
            if gk is None:
                # A group with no key can't have negotiated an AFI; treat as
                # "none" so the caller's AFI-purity assertion flags it rather
                # than crashing on attribute access.
                return "none"
            v4 = bool(gk.afi_ipv4_negotiated)
            v6 = bool(gk.afi_ipv6_negotiated)
            if v4 and v6:
                return "both"
            if v4:
                return "ipv4"
            if v6:
                return "ipv6"
            return "none"

        substrings = (
            set(peer_group_substrings)
            | set(expected_member_counts)
            | set(expected_policy_names)
            | set(expect_empty_peer_groups)
            | set(expected_afi_by_substring)
        )
        # A peer-group substring matches an update group if it appears in the
        # group's ``peer_group_name`` (authoritative) or in any of its peers'
        # descriptions. For each group, the number of ESTABLISHED members is the
        # count of its peers whose address is established per getBgpSessions.
        sub_to_groups: t.Dict[str, t.Set[int]] = {s: set() for s in substrings}
        group_established: t.Dict[int, int] = {}
        observed_peer_group_names: t.Set[str] = set()
        total_established = 0
        for group in groups:
            pg_name = group.group_key.peer_group_name or ""
            observed_peer_group_names.add(pg_name)
            est = sum(
                1
                for p in (group.peers or [])
                if _norm(p.peer_addr) in established_addrs
            )
            group_established[group.group_id] = est
            total_established += est
            descriptions = " ".join(p.description or "" for p in (group.peers or []))
            for substring in substrings:
                if substring in pg_name or substring in descriptions:
                    sub_to_groups[substring].add(group.group_id)

        # (1) each listed peer-group must match at least one update group with at
        # least one ESTABLISHED member. A peer-group mapping to >1 group is fine.
        substrings_needing_presence = (
            set(peer_group_substrings)
            | set(expected_member_counts)
            | set(expected_policy_names)
            | set(expected_afi_by_substring)
        )
        for substring in sorted(substrings_needing_presence):
            gids = sub_to_groups.get(substring, set())
            est_sum = sum(group_established.get(gid, 0) for gid in gids)
            if not gids or est_sum == 0:
                failures.append(
                    f"No update group matching '{substring}' (by peer_group_name "
                    f"or peer description) with ESTABLISHED members on {hostname}. "
                    f"Observed {len(groups)} update group(s) with peer_group_names "
                    f"{sorted(observed_peer_group_names)} and {total_established} "
                    f"established member(s) total (cross-referenced with "
                    f"getBgpSessions; {len(established_addrs)} established sessions)."
                )

        # (2) total ESTABLISHED members across ALL update groups the peer-group
        # forms (cross-referenced with getBgpSessions).
        for substring, expected_members in expected_member_counts.items():
            group_ids = sub_to_groups[substring]
            if not group_ids:
                continue  # already reported by the presence check above
            actual_members = sum(group_established.get(gid, 0) for gid in group_ids)
            if actual_members != int(expected_members):
                failures.append(
                    f"Peer-group '{substring}' has {actual_members} ESTABLISHED "
                    f"members across update groups {sorted(group_ids)} on "
                    f"{hostname}; expected {expected_members}."
                )

        # (3) egress policy names: the SET of policies the peer-group's update
        # groups are keyed on must equal the expected set (a peer-group forms one
        # update group per distinct egress policy).
        for substring, expected_policies in expected_policy_names.items():
            group_ids = sub_to_groups[substring]
            actual_policies = {
                id_to_group[gid].group_key.egress_policy_name for gid in group_ids
            }
            if actual_policies != set(expected_policies):
                failures.append(
                    f"Peer-group '{substring}' update groups are keyed on egress "
                    f"policies {sorted(actual_policies)} on {hostname}; expected "
                    f"{sorted(set(expected_policies))}."
                )

        # (4) total update-group count on the device
        if expected_group_count is not None and len(groups) != expected_group_count:
            failures.append(
                f"Total update group count on {hostname} is {len(groups)}; "
                f"expected {expected_group_count}."
            )

        # (5) peer-groups asserted EMPTY: each must map to NO update group with
        # Established members (the last peer left, so the group emptied / was
        # cleaned up). Inverse of the presence check (1); cross-referenced with
        # getBgpSessions, so a group lingering with only down peers counts as
        # empty, while a group that still has an Established member FAILs. Used by
        # the UG "empty group" edge case (spec 2.9.7).
        for substring in sorted(set(expect_empty_peer_groups)):
            gids = sub_to_groups.get(substring, set())
            est_sum = sum(group_established.get(gid, 0) for gid in gids)
            if est_sum != 0:
                failures.append(
                    f"Peer-group '{substring}' is expected EMPTY on {hostname} "
                    f"but still has {est_sum} Established member(s) across update "
                    f"groups {sorted(gids)} (cross-referenced with getBgpSessions). "
                    f"The empty-group condition did not take effect."
                )

        # (6) AFI purity / separation: each listed peer-group must map ONLY to
        # update groups negotiating the expected address family (and not the
        # other). This directly verifies dual-stack isolation (spec 2.9.4) -- v4
        # and v6 peers live in SEPARATE, AFI-pure update groups, so a v4 route
        # operation can never be distributed through the v6 group. A group that
        # negotiated BOTH AFIs (or the wrong one) is a leak and FAILs.
        for substring in sorted(expected_afi_by_substring):
            expected_afi = str(expected_afi_by_substring[substring]).lower()
            gids = sub_to_groups.get(substring, set())
            if not gids:
                continue  # already reported by the presence check above
            for gid in sorted(gids):
                actual_afi = _group_afi(gid)
                if actual_afi != expected_afi:
                    failures.append(
                        f"Peer-group '{substring}' update group {gid} negotiates "
                        f"AFI '{actual_afi}' on {hostname}; expected only "
                        f"'{expected_afi}' (dual-stack isolation: IPv4 and IPv6 "
                        f"peers must be in separate, AFI-pure update groups)."
                    )

        # If any assertion failed, report them all together.
        if failures:
            numbered = "\n".join(f"  {i}. {f}" for i, f in enumerate(failures, 1))
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    f"BGP++ update-group check found {len(failures)} failure(s) on "
                    f"{hostname}:\n{numbered}"
                ),
            )

        # Surface the things we care about: total group count and per-peer-group
        # {group_ids, established members, member_count, policies, group_state}.
        summary = {}
        for substring in peer_group_substrings:
            group_ids = sorted(sub_to_groups[substring])
            if not group_ids:
                continue
            summary[substring] = {
                "group_ids": group_ids,
                "established": sum(group_established.get(gid, 0) for gid in group_ids),
                "member_count": sum(
                    int(id_to_group[gid].member_count or 0) for gid in group_ids
                ),
                "policies": sorted(
                    {id_to_group[gid].group_key.egress_policy_name for gid in group_ids}
                ),
                "afis": sorted({_group_afi(gid) for gid in group_ids}),
                "group_states": sorted(
                    {id_to_group[gid].group_state for gid in group_ids}
                ),
            }
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=(
                f"Update group check PASSED on {hostname}: {len(groups)} groups, "
                f"{total_established} established members; peer-group -> "
                f"{{group_ids, established, member_count, policies, afis, "
                f"group_states}} {summary}."
            ),
        )
