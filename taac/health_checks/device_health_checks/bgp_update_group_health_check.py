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

        substrings = (
            set(peer_group_substrings)
            | set(expected_member_counts)
            | set(expected_policy_names)
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
                "group_states": sorted(
                    {id_to_group[gid].group_state for gid in group_ids}
                ),
            }
        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message=(
                f"Update group check PASSED on {hostname}: {len(groups)} groups, "
                f"{total_established} established members; peer-group -> "
                f"{{group_ids, established, member_count, policies, group_states}} "
                f"{summary}."
            ),
        )
