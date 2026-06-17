# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import ipaddress
import time
import typing as t
from collections import namedtuple

from neteng.fboss.bgp_thrift.types import TBgpPeerState, TBgpSession
from taac.constants import TestDevice
from taac.health_checks.abstract_snapshot_health_check import (
    AbstractDeviceSnapshotHealthCheck,
)
from taac.health_checks.constants import Snapshot
from taac.utils.health_check_utils import is_parent_prefix
from taac.health_check.health_check import types as hc_types


BgpSessionId = namedtuple(
    "BgpSessionId", ["my_addr", "peer_addr", "peer_session_state"], defaults=(None,)
)


class BgpSessionHealthCheck(
    AbstractDeviceSnapshotHealthCheck[hc_types.BaseHealthCheckIn],
):
    CHECK_NAME = hc_types.CheckName.BGP_SESSION_CHECK
    OPERATING_SYSTEMS = [
        "FBOSS",
        "EOS",
    ]
    DEFAULT_PRIORITY = hc_types.DEFAULT_HC_PRIORITY

    async def capture_pre_snapshot(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
        timestamp: int,
    ) -> Snapshot:
        parent_prefixes_to_ignore = check_params.get("parent_prefixes_to_ignore", [])
        bgp_sessions = await self.async_get_bgp_sessions(parent_prefixes_to_ignore)
        # Stamp the snapshot at the instant the device data is actually read, NOT
        # the framework-supplied `timestamp` (captured before this query ran). The
        # device query can take many seconds when the control plane is busy (e.g.
        # right after an IGP/PNH oscillation playbook); anchoring to the pre-query
        # moment skews any uptime math derived from this timestamp.
        return Snapshot(data=bgp_sessions, timestamp=int(time.time()))

    async def capture_post_snapshot(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
        timestamp: int,
    ) -> Snapshot:
        parent_prefixes_to_ignore = check_params.get("parent_prefixes_to_ignore", [])
        bgp_sessions = await self.async_get_bgp_sessions(parent_prefixes_to_ignore)
        # Stamp the snapshot at the instant the device data is actually read, NOT
        # the framework-supplied `timestamp` (captured before this query ran). The
        # device query can take many seconds when the control plane is busy (e.g.
        # right after an IGP/PNH oscillation playbook); anchoring to the pre-query
        # moment skews any uptime math derived from this timestamp.
        return Snapshot(data=bgp_sessions, timestamp=int(time.time()))

    async def compare_snapshots(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
        pre_snapshot: Snapshot,
        post_snapshot: Snapshot,
    ) -> hc_types.HealthCheckResult:
        skip_flap_check = check_params.get("skip_flap_check")
        skip_uptime_check = check_params.get("skip_uptime_check")
        pre_snapshot_bgp_sessions = pre_snapshot.data
        post_snapshot_bgp_sessions = post_snapshot.data
        deleted_bgp_sessions = list(
            set(pre_snapshot_bgp_sessions.keys())
            - set(post_snapshot_bgp_sessions.keys())
        )
        if deleted_bgp_sessions:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=(
                    f"Bgp sessions with the following local_addr and peer_addr are "
                    f"not present in post snapshot: {deleted_bgp_sessions}"
                ),
            )

        issues = []

        if not skip_flap_check:
            flapped_bgp_sessions = []
            for key in post_snapshot_bgp_sessions.keys():
                pre_snapshot_bgp_session = pre_snapshot_bgp_sessions.get(key)
                post_snapshot_bgp_session = post_snapshot_bgp_sessions[key]
                if not pre_snapshot_bgp_session:
                    continue
                if (
                    pre_snapshot_bgp_session.details
                    and post_snapshot_bgp_session.details
                ):
                    if (
                        post_snapshot_bgp_session.details.num_of_flaps
                        > pre_snapshot_bgp_session.details.num_of_flaps
                    ):
                        flapped_bgp_sessions.append(key)
                        self.logger.debug(
                            f"The number of flaps increased from {pre_snapshot_bgp_session.details.num_of_flaps} "
                            f"to {post_snapshot_bgp_session.details.num_of_flaps} for {key}"
                        )
                else:
                    if (
                        post_snapshot_bgp_session.uptime
                        < pre_snapshot_bgp_session.uptime
                    ):
                        flapped_bgp_sessions.append(key)
                        self.logger.debug(
                            f"The uptime for {key} decreased from {pre_snapshot_bgp_session.uptime} to "
                            f"{post_snapshot_bgp_session.uptime}. This indicates a flap"
                        )
            if flapped_bgp_sessions:
                flapped_sessions_str = "\n    • ".join(
                    [
                        self._format_session_id(session)
                        for session in flapped_bgp_sessions
                    ]
                )
                issues.append(f"Flapped BGP sessions:\n    • {flapped_sessions_str}")

        # Backstop reset detection: flag any session that is YOUNGER than the
        # inter-snapshot interval (it could not have stayed up the whole window,
        # so it must have reset). We intentionally do NOT compare uptime against a
        # computed "expected" magnitude — a session cannot over-stay, so that
        # comparison only ever fires on measurement skew. The primary flap signals
        # are num_of_flaps and uptime-decrease, checked above.
        uptime_issues = []
        if not skip_uptime_check:
            for key in post_snapshot_bgp_sessions.keys():
                pre_snapshot_bgp_session = pre_snapshot_bgp_sessions.get(key)
                post_snapshot_bgp_session = post_snapshot_bgp_sessions[key]
                if not pre_snapshot_bgp_session:
                    continue

                session_uptime_issues = self._check_uptime_consistency(
                    key,
                    post_snapshot_bgp_session,
                    pre_snapshot.timestamp,
                    post_snapshot.timestamp,
                )
                uptime_issues.extend(session_uptime_issues)

        if uptime_issues:
            uptime_issues_str = "\n    • ".join(uptime_issues)
            issues.append(f"BGP session uptime issues:\n    • {uptime_issues_str}")

        # Validate peer identities against expected mappings from check_params
        expected_peer_identity = check_params.get("expected_peer_identity")
        if expected_peer_identity:
            parent_prefixes_to_ignore = check_params.get(
                "parent_prefixes_to_ignore", []
            )
            if parent_prefixes_to_ignore:
                expected_peer_identity = {
                    peer: local
                    for peer, local in expected_peer_identity.items()
                    if not any(
                        is_parent_prefix(peer, prefix)
                        for prefix in parent_prefixes_to_ignore
                    )
                }
            peer_issues = self._validate_peer_identity(
                expected_peer_identity, post_snapshot_bgp_sessions, obj.name
            )
            if peer_issues:
                issues.extend(peer_issues)

        if issues:
            formatted_message = "BGP session issues detected:\n\n" + "\n\n".join(issues)
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=formatted_message,
            )

        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
        )

    async def async_get_bgp_sessions(
        self,
        parent_prefixes_to_ignore: t.List[str],
    ) -> t.Dict[BgpSessionId, TBgpSession]:
        """
        Retrieves BGP sessions from the driver and maps them to a dictionary.
        Args:
            parent_prefixes_to_ignore: CIDR prefixes to exclude (subnet_of matching).
        Returns:
            A dictionary mapping BgpSessionId to TBgpSession.
        """
        # pyrefly: ignore [missing-attribute]
        bgp_sessions = await self.driver.async_get_bgp_sessions()
        bgp_sessions_map: t.Dict[BgpSessionId, TBgpSession] = {}
        for bgp_session in bgp_sessions:
            if parent_prefixes_to_ignore:
                should_ignore_prefix = any(
                    is_parent_prefix(bgp_session.peer_addr, parent_prefix)
                    for parent_prefix in parent_prefixes_to_ignore
                )
                if should_ignore_prefix:
                    continue
            if bgp_session.peer.peer_state != TBgpPeerState.ESTABLISHED:
                continue
            session_id = BgpSessionId(
                my_addr=bgp_session.my_addr,
                peer_addr=bgp_session.peer_addr,
                peer_session_state=bgp_session.peer.peer_state,
            )
            bgp_sessions_map[session_id] = bgp_session
        return bgp_sessions_map

    def _format_session_id(self, session_id: BgpSessionId) -> str:
        return f"{session_id.my_addr} (local_addr) → {session_id.peer_addr} (peer_addr)"

    def _check_uptime_consistency(
        self,
        session_key: BgpSessionId,
        post_session: TBgpSession,
        pre_timestamp: int,
        post_timestamp: int,
    ) -> t.List[str]:
        """
        Detect a BGP session reset across the pre/post snapshot window.

        The only physically meaningful uptime signal for "did the session stay
        up?" is the session being YOUNGER than it should be: if its post-snapshot
        uptime is less than the wall-clock elapsed between the two snapshots, it
        could not have stayed up the whole window and therefore must have reset.

        We deliberately do NOT flag uptime being HIGHER than some computed
        "expected" value. A session cannot over-stay, so that comparison carries
        no diagnostic meaning — it only ever fires on measurement skew, because
        the device-reported uptime and the snapshot timestamp are sampled at
        slightly different instants (and the gap grows when the device is slow to
        answer the post-snapshot query). Genuine flaps/resets are already covered
        by the num_of_flaps and uptime-decrease checks in compare_snapshots; this
        is a one-directional backstop for the case where neither of those fires.

        Returns list of issues found.
        """
        issues = []

        # Convert uptime from milliseconds to seconds.
        post_uptime_seconds = post_session.uptime // 1000 if post_session.uptime else 0

        # Wall-clock elapsed between the two snapshots (seconds).
        time_elapsed = post_timestamp - pre_timestamp

        session_str = self._format_session_id(session_key)

        # A session whose current uptime is less than the inter-snapshot interval
        # must have reset during the window.
        if post_uptime_seconds < time_elapsed:
            issues.append(
                f"{session_str}: Session restarted (uptime: {post_uptime_seconds}s, expected: >{time_elapsed}s)"
            )

        return issues

    @staticmethod
    def _normalize_ip(addr: str) -> str:
        """Normalize an IP address string for consistent comparison."""
        try:
            return str(ipaddress.ip_address(addr))
        except (ValueError, TypeError):
            return addr

    def _validate_peer_identity(
        self,
        expected_peer_identity: t.Dict[str, str],
        session_map: t.Dict[BgpSessionId, TBgpSession],
        hostname: str,
    ) -> t.List[str]:
        """Validate established sessions against expected local_addr -> peer_addr.

        Returns list of issue strings for mismatches, missing, or unexpected peers.
        """
        expected = {
            self._normalize_ip(p): self._normalize_ip(l)
            for p, l in expected_peer_identity.items()
        }

        actual_by_peer: t.Dict[str, str] = {}
        for session_id in session_map.keys():
            norm_peer = self._normalize_ip(str(session_id.peer_addr))
            norm_local = self._normalize_ip(str(session_id.my_addr))
            actual_by_peer[norm_peer] = norm_local

        actual_addrs = set(actual_by_peer.keys())
        expected_addrs = set(expected.keys())

        matched = 0
        local_mismatches = []
        for peer_addr in actual_addrs & expected_addrs:
            expected_local = expected[peer_addr]
            actual_local = actual_by_peer[peer_addr]
            if actual_local == expected_local:
                matched += 1
            else:
                local_mismatches.append(
                    f"expected {expected_local} -> {peer_addr}, "
                    f"actual {actual_local} -> {peer_addr}"
                )
                self.logger.warning(
                    f"{hostname}: local_addr mismatch for peer {peer_addr}: "
                    f"expected local_addr={expected_local} -> peer_addr={peer_addr}, "
                    f"actual local_addr={actual_local} -> peer_addr={peer_addr}"
                )

        missing = expected_addrs - actual_addrs
        unexpected = actual_addrs - expected_addrs

        self.logger.info(
            f"{hostname}: Peer identity check — "
            f"matched={matched}, missing={len(missing)}, "
            f"unexpected={len(unexpected)}, local_mismatch={len(local_mismatches)}"
        )

        issues = []

        if local_mismatches:
            mismatch_str = "\n    • ".join(local_mismatches[:10])
            suffix = (
                f"\n    • ... and {len(local_mismatches) - 10} more"
                if len(local_mismatches) > 10
                else ""
            )
            issues.append(
                f"Peer identity local_addr mismatches ({len(local_mismatches)}):"
                f"\n    • {mismatch_str}{suffix}"
            )

        if missing:
            missing_samples = [f"{expected[p]} -> {p}" for p in sorted(missing)[:10]]
            missing_str = "\n    • ".join(missing_samples)
            suffix = (
                f"\n    • ... and {len(missing) - 10} more" if len(missing) > 10 else ""
            )
            issues.append(
                f"Missing expected peers ({len(missing)}):\n    • {missing_str}{suffix}"
            )
            for peer_addr in sorted(missing):
                self.logger.warning(
                    f"{hostname}: Expected peer not found in sessions: "
                    f"expected local_addr={expected[peer_addr]} -> "
                    f"peer_addr={peer_addr}"
                )

        if unexpected:
            unexpected_samples = [
                f"{actual_by_peer[p]} -> {p}" for p in sorted(unexpected)[:10]
            ]
            unexpected_str = "\n    • ".join(unexpected_samples)
            suffix = (
                f"\n    • ... and {len(unexpected) - 10} more"
                if len(unexpected) > 10
                else ""
            )
            issues.append(
                f"Unexpected peers ({len(unexpected)}):\n    • {unexpected_str}{suffix}"
            )
            for peer_addr in sorted(unexpected):
                self.logger.warning(
                    f"{hostname}: Unexpected peer in sessions (not in expected config): "
                    f"actual local_addr={actual_by_peer[peer_addr]} -> "
                    f"peer_addr={peer_addr}"
                )

        return issues
