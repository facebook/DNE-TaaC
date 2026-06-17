# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import ipaddress
import json
import re
import time
import typing as t
from collections import Counter

from neteng.fboss.bgp_thrift.types import TBgpPeerState
from taac.constants import TestDevice
from taac.health_checks.abstract_health_check import (
    AbstractDeviceHealthCheck,
)
from taac.utils.health_check_utils import is_parent_prefix
from taac.health_check.health_check import types as hc_types

BGPCPP_CONFIG_PATH = "/mnt/flash/bgpcpp_config"


class BgpSessionEstablishedHealthCheck(
    AbstractDeviceHealthCheck[hc_types.BaseHealthCheckIn]
):
    CHECK_NAME = hc_types.CheckName.BGP_SESSION_ESTABLISH_CHECK
    OPERATING_SYSTEMS = [
        "FBOSS",
        "EOS",
    ]
    # DEFAULT_PRIORITY = hc_types.DEFAULT_HC_PRIORITY

    @staticmethod
    def _normalize_ip(addr: str) -> str:
        """Normalize an IP address string for consistent comparison."""
        try:
            return str(ipaddress.ip_address(addr))
        except (ValueError, TypeError):
            return addr

    async def _read_bgpcpp_config(self, hostname: str) -> t.Optional[t.Dict[str, str]]:
        """Read bgpcpp_config from the device and extract expected peer addresses.

        Reads /mnt/flash/bgpcpp_config, parses the JSON, and builds a map of
        {normalized_peer_addr: normalized_local_addr} from the configured peers.

        Returns None if the file cannot be read or parsed.
        """
        try:
            # pyrefly: ignore [missing-attribute]
            config_content = await self.driver.async_read_file(BGPCPP_CONFIG_PATH)
            if not config_content:
                self.logger.info(
                    f"{hostname}: No bgpcpp_config found at {BGPCPP_CONFIG_PATH}, "
                    "skipping peer identity validation"
                )
                return None

            try:
                config = json.loads(config_content)
            except json.JSONDecodeError:
                # Handle non-standard JSON (e.g. trailing commas in auto-generated configs)
                cleaned = re.sub(r",\s*([}\]])", r"\1", config_content)
                config = json.loads(cleaned)
            peers = config.get("peers", [])
            if not peers:
                self.logger.info(
                    f"{hostname}: bgpcpp_config has no peers, "
                    "skipping peer identity validation"
                )
                return None

            expected: t.Dict[str, str] = {}
            for peer in peers:
                peer_addr = peer.get("peer_addr")
                local_addr = peer.get("local_addr")
                if peer_addr and local_addr:
                    expected[self._normalize_ip(peer_addr)] = self._normalize_ip(
                        local_addr
                    )

            self.logger.info(
                f"{hostname}: Loaded {len(expected)} expected peers from bgpcpp_config"
            )
            return expected

        except Exception as e:
            self.logger.warning(
                f"{hostname}: Failed to read bgpcpp_config: {e}, "
                "skipping peer identity validation"
            )
            return None

    def _validate_peer_identity(
        self,
        expected_peers: t.Dict[str, str],
        established_sessions: t.List,
        hostname: str,
    ) -> t.List[str]:
        """Validate established sessions against expected peer/local addresses.

        Compares actual (peer_addr, my_addr) pairs against expected. Logs a
        concise summary and returns warning strings for any mismatches.
        """
        actual_by_peer: t.Dict[str, str] = {}
        for session in established_sessions:
            norm_peer = self._normalize_ip(str(session.peer_addr))
            norm_local = self._normalize_ip(str(getattr(session, "my_addr", "")))
            actual_by_peer[norm_peer] = norm_local

        actual_addrs = set(actual_by_peer.keys())
        expected_addrs = set(expected_peers.keys())

        matched = 0
        local_mismatches = []
        for peer_addr in actual_addrs & expected_addrs:
            expected_local = expected_peers[peer_addr]
            actual_local = actual_by_peer[peer_addr]
            if actual_local == expected_local:
                matched += 1
            else:
                local_mismatches.append(
                    f"expected {expected_local} -> {peer_addr}, "
                    f"actual {actual_local} -> {peer_addr}"
                )

        missing = expected_addrs - actual_addrs
        unexpected = actual_addrs - expected_addrs

        self.logger.info(
            f"{hostname}: Peer identity check — "
            f"matched={matched}, missing={len(missing)}, "
            f"unexpected={len(unexpected)}, local_mismatch={len(local_mismatches)}"
        )

        warnings = []
        if missing:
            sample = [f"{expected_peers[p]} -> {p}" for p in sorted(missing)[:5]]
            self.logger.warning(
                f"{hostname}: Missing expected peers ({len(missing)}): "
                f"{sample}{'...' if len(missing) > 5 else ''}"
            )
            warnings.append(f"Missing {len(missing)} expected peers: {sample}")
        if unexpected:
            sample = [f"{actual_by_peer[p]} -> {p}" for p in sorted(unexpected)[:5]]
            self.logger.warning(
                f"{hostname}: Unexpected peers ({len(unexpected)}): "
                f"{sample}{'...' if len(unexpected) > 5 else ''}"
            )
            warnings.append(f"Unexpected {len(unexpected)} peers: {sample}")
        if local_mismatches:
            sample = local_mismatches[:3]
            self.logger.warning(
                f"{hostname}: Local address mismatches ({len(local_mismatches)}): {sample}"
            )
            warnings.append(
                f"Local addr mismatch on {len(local_mismatches)} peers: {sample}"
            )

        return warnings

    def _log_session_summary(
        self,
        established_sessions: t.List,
        hostname: str,
    ) -> str:
        """Log established BGP session count with breakdown by remote AS.

        Returns a formatted summary string for inclusion in the result message.
        """
        if not established_sessions:
            self.logger.info(f"{hostname}: No established BGP sessions")
            return "No established sessions"

        # Group by remote AS
        as_counts: t.Counter[int] = Counter()
        for session in established_sessions:
            remote_as = getattr(session.peer, "remote_as", None)
            if remote_as is not None:
                as_counts[remote_as] += 1

        total = len(established_sessions)
        breakdown = ", ".join(
            f"AS{asn}:{count}" for asn, count in sorted(as_counts.items())
        )
        summary = f"Established sessions: {total}"
        if breakdown:
            summary += f" ({breakdown})"

        self.logger.info(f"{hostname}: {summary}")
        return summary

    async def _get_service_restart_epoch(
        self, hostname: str, service: str
    ) -> t.Optional[float]:
        """Get the epoch time when a systemd service last entered active state.

        Uses ``date -d`` on the device to convert the systemd timestamp to
        epoch, avoiding timezone parsing issues on the devserver side.
        """
        cmd = (
            f"ts=$(systemctl show {service} -p ActiveEnterTimestamp --value); "
            f'date -d "$ts" +%s 2>/dev/null || echo ""'
        )
        try:
            # pyrefly: ignore [missing-attribute]
            output = await self.driver.async_run_cmd_on_shell(cmd)
            epoch_str = output.strip()
            if not epoch_str:
                return None
            return float(epoch_str)
        except Exception as e:
            self.logger.warning(
                f"{hostname}: Failed to get ActiveEnterTimestamp for {service}: {e}"
            )
            return None

    async def _check_convergence_timing(
        self,
        hostname: str,
        established_sessions: t.List,
        max_convergence_sec: float,
        service: str = "bgpd",
    ) -> t.Optional[hc_types.HealthCheckResult]:
        """Validate BGP sessions came up within max_convergence_sec of service restart.

        Fetches ActiveEnterTimestamp for the service via systemctl, computes
        convergence_sec = session_established_at - service_restart_epoch for
        each established session, and checks that at least one converged
        within the threshold.

        Returns None if the restart timestamp can't be determined (skip).
        """
        from statistics import median

        from taac.utils.common import (
            async_everpaste_str,
            async_get_fburl,
        )

        restart_epoch = await self._get_service_restart_epoch(hostname, service)
        if restart_epoch is None:
            self.logger.warning(
                f"{hostname}: Could not determine {service} restart time, "
                f"skipping convergence timing check"
            )
            return None

        now = time.time()
        detail_lines = [
            f"BGP Session Convergence Timing — {hostname}",
            f"  now:           {now:.0f} ({time.strftime('%H:%M:%S', time.localtime(now))})",
            f"  restart_epoch: {restart_epoch:.0f} ({time.strftime('%H:%M:%S', time.localtime(restart_epoch))})",
            f"  delta:         {now - restart_epoch:.1f}s",
            "",
            f"  {'Peer Address':<45} {'Uptime(ms)':>12} {'Uptime(s)':>10} {'Established At':>16} {'Convergence(s)':>16}",
            f"  {'-' * 45} {'-' * 12} {'-' * 10} {'-' * 16} {'-' * 16}",
        ]
        convergence_times = []
        for s in established_sessions:
            if s.uptime is None:
                continue
            uptime_sec = s.uptime / 1000.0
            established_at = now - uptime_sec
            convergence_sec = established_at - restart_epoch
            detail_lines.append(
                f"  {str(s.peer_addr):<45} {s.uptime:>12} {uptime_sec:>10.1f} "
                f"{time.strftime('%H:%M:%S', time.localtime(established_at)):>16} "
                f"{convergence_sec:>16.1f}"
            )
            if convergence_sec < 0:
                convergence_sec = 0.0
            convergence_times.append((str(s.peer_addr), convergence_sec))

        if not convergence_times:
            self.logger.warning(
                f"{hostname}: No sessions with uptime data for convergence check"
            )
            return None

        sorted_times = sorted(ct for _, ct in convergence_times)
        fastest_sec = sorted_times[0]
        slowest_sec = sorted_times[-1]
        p50_sec = median(sorted_times)

        detail_lines.append("")
        detail_lines.append(
            f"  fastest={fastest_sec:.1f}s  p50={p50_sec:.1f}s  slowest={slowest_sec:.1f}s"
        )

        try:
            ep_url = await async_get_fburl(
                await async_everpaste_str("\n".join(detail_lines))
            )
        except Exception:
            ep_url = "(everpaste unavailable)"

        passed = p50_sec <= max_convergence_sec

        self.logger.info(
            f"{hostname}: {service} restarted at "
            f"{time.strftime('%H:%M:%S', time.localtime(restart_epoch))} "
            f"({now - restart_epoch:.0f}s ago). "
            f"{len(convergence_times)} sessions — "
            f"fastest={fastest_sec:.1f}s, p50={p50_sec:.1f}s, "
            f"slowest={slowest_sec:.1f}s "
            f"(threshold: p50 ≤ {max_convergence_sec:.0f}s → "
            f"{'PASS' if passed else 'FAIL'}) | {ep_url}"
        )

        if passed:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.PASS,
                message=(
                    f"Convergence OK: p50={p50_sec:.1f}s "
                    f"(fastest={fastest_sec:.1f}s, slowest={slowest_sec:.1f}s) "
                    f"within {max_convergence_sec:.0f}s of {service} restart "
                    f"({len(convergence_times)} sessions) | {ep_url}"
                ),
            )

        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.FAIL,
            message=(
                f"Convergence FAIL: p50={p50_sec:.1f}s exceeds "
                f"{max_convergence_sec:.0f}s threshold "
                f"(fastest={fastest_sec:.1f}s, slowest={slowest_sec:.1f}s, "
                f"{len(convergence_times)} sessions) | {ep_url}"
            ),
        )

    async def _run(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,  # Required by the AbstractDeviceHealthCheck interface
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        """
        Run a health check to verify BGP session count matches expectation.

        Also reads /mnt/flash/bgpcpp_config from the device (if present) to
        validate that actual BGP session peer/local addresses match what was
        configured. Mismatches are logged as WARNINGs (do not cause FAIL).

        Args:
            obj: Test device
            input: Base health check input
            check_params: Dictionary containing:
                - expected_established_session_count: Expected number of established BGP sessions (optional, defaults to "all established")
                - parent_prefixes_to_ignore: Optional list of CIDR prefixes to exclude (subnet_of matching)
                - ignore_all_prefixes_except: Optional list of prefixes to exclusively check
                  (only sessions with these prefixes will be checked, all others will be ignored)
                - verbose: Optional boolean to enable verbose output (defaults to False)

        Returns:
            HealthCheckResult: Result of the health check
        """
        hostname = obj.name

        parent_prefixes_to_ignore = check_params.get("parent_prefixes_to_ignore", [])
        ignore_all_prefixes_except = check_params.get("ignore_all_prefixes_except", [])
        verbose = check_params.get("verbose", False)
        expected_established_session_count = check_params.get(
            "expected_established_session_count"
        )

        if expected_established_session_count is not None:
            try:
                expected_established_session_count = int(
                    expected_established_session_count
                )
                self.logger.info(
                    f"Expected_established_session_count = {expected_established_session_count}"
                )
            except (ValueError, TypeError):
                self.logger.warning(
                    f"Invalid expected_established_session_count value: {expected_established_session_count}, ignoring"
                )
                expected_established_session_count = None

        self.logger.info(f"Running BGP session health check on {hostname}")

        # Get all BGP sessions
        # pyrefly: ignore [missing-attribute]
        bgp_sessions = await self.driver.async_get_bgp_sessions()

        # Handle case where no BGP sessions are configured at all
        if not bgp_sessions:
            # If we expected 0 established sessions and there are no sessions at all, that's a pass
            if expected_established_session_count == 0:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.PASS,
                    message=f"No BGP sessions configured on {hostname} - matches expected 0 established sessions",
                )
            # If we expected some established sessions but there are no sessions at all, that's a fail
            elif (
                expected_established_session_count is not None
                and expected_established_session_count > 0
            ):
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=f"No BGP sessions configured on {hostname}, but expected {expected_established_session_count} established sessions",
                )
            # If no expectation was set and there are no sessions, that's also a fail
            else:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=f"No BGP sessions found on {hostname}",
                )

        # Count sessions by state
        session_states: t.Counter = Counter()
        non_established_sessions = []
        established_session_list = []

        for session in bgp_sessions:
            if parent_prefixes_to_ignore and any(
                is_parent_prefix(session.peer_addr, prefix)
                for prefix in parent_prefixes_to_ignore
            ):
                continue

            # If ignore_all_prefixes_except is specified, only check sessions with these prefixes
            if ignore_all_prefixes_except and not any(
                session.peer_addr == prefix for prefix in ignore_all_prefixes_except
            ):
                continue

            session_states[session.peer.peer_state] += 1

            if session.peer.peer_state != TBgpPeerState.ESTABLISHED:
                non_established_sessions.append(
                    {
                        "peer_addr": session.peer_addr,
                        "my_addr": session.my_addr,
                        "state": str(session.peer.peer_state),
                        "uptime": session.uptime,
                        "asn": session.peer.remote_as,
                    }
                )
            else:
                established_session_list.append(session)

        total_sessions = sum(session_states.values())
        established_sessions = session_states.get(TBgpPeerState.ESTABLISHED, 0)

        self.logger.info(f"Total BGP sessions: {total_sessions}")
        self.logger.info(f"Established BGP sessions: {established_sessions}")

        # Print session state counts
        for state, count in session_states.items():
            self.logger.info(f"Sessions in {state} state: {count}")

        # Log established session summary with breakdown by remote AS
        session_summary = self._log_session_summary(established_session_list, hostname)

        # Print details of non-established sessions if verbose
        if verbose and non_established_sessions:
            self.logger.info("Non-established BGP sessions:")
            for session in non_established_sessions:
                self.logger.info(
                    f"  Peer: {session['peer_addr']} (ASN: {session['asn']})"
                )
                self.logger.info(f"  Local: {session['my_addr']}")
                self.logger.info(f"  State: {session['state']}")
                self.logger.info(f"  Uptime: {session['uptime']} seconds")
                self.logger.info("  ---")

        # Format non-established session details for failure messages
        non_established_details = [
            f"{s['peer_addr']} (state={s['state']}, ASN={s['asn']})"
            for s in non_established_sessions
        ]

        min_established_pct = check_params.get("min_established_pct")

        # Generalized logic: If expected count is provided, use simple comparison
        if expected_established_session_count is not None:
            if established_sessions == expected_established_session_count:
                pass_result = hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.PASS,
                    message=f"BGP session count matches expected: {established_sessions} established sessions on {hostname}. {session_summary}",
                )
            else:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=f"BGP session count mismatch on {hostname}: expected {expected_established_session_count} established sessions, found {established_sessions}. "
                    f"Total sessions: {total_sessions}. "
                    f"Non-established: {non_established_details}. {session_summary}",
                )
        elif min_established_pct is not None and total_sessions > 0:
            pct = established_sessions / total_sessions
            threshold = float(min_established_pct)
            if pct >= threshold:
                self.logger.info(
                    f"{hostname}: {established_sessions}/{total_sessions} "
                    f"({pct:.0%}) BGP sessions established, "
                    f"threshold {threshold:.0%} met"
                )
                pass_result = hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.PASS,
                    message=(
                        f"{established_sessions}/{total_sessions} "
                        f"({pct:.0%}) BGP sessions established on "
                        f"{hostname} (threshold: {threshold:.0%}). "
                        f"{session_summary}"
                    ),
                )
            else:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=(
                        f"Only {established_sessions}/{total_sessions} "
                        f"({pct:.0%}) BGP sessions established on "
                        f"{hostname}, below {threshold:.0%} threshold. "
                        f"Non-established: {non_established_details}. "
                        f"{session_summary}"
                    ),
                )
        else:
            # Backward compatibility: Original behavior when no expected count is provided
            if non_established_sessions:
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=f"Found {len(non_established_sessions)} BGP sessions that are not established on {hostname}. "
                    f"Total sessions: {total_sessions}, Established sessions: {established_sessions}. "
                    f"Non-established: {non_established_details}. {session_summary}",
                )

            self.logger.info(
                f"All {total_sessions} BGP sessions are established on {hostname}"
            )
            pass_result = hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.PASS,
                message=f"All {total_sessions} BGP sessions are established on {hostname}. {session_summary}",
            )

        # Validate peer identities against bgpcpp_config on the device
        expected_peers = await self._read_bgpcpp_config(hostname)
        if expected_peers:
            peer_warnings = self._validate_peer_identity(
                expected_peers, established_session_list, hostname
            )
            if peer_warnings:
                pass_result = hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.PASS,
                    message=(pass_result.message or "")
                    + ". Peer identity warnings: "
                    + "; ".join(peer_warnings),
                )

        max_session_uptime_sec = check_params.get("max_session_uptime_sec")
        if (
            max_session_uptime_sec is not None
            and established_session_list
            and pass_result.status == hc_types.HealthCheckStatus.PASS
        ):
            convergence_result = await self._check_convergence_timing(
                hostname,
                established_session_list,
                float(max_session_uptime_sec),
                check_params.get("convergence_service", "bgpd"),
            )
            if convergence_result is not None:
                if convergence_result.status == hc_types.HealthCheckStatus.PASS:
                    pass_result = hc_types.HealthCheckResult(
                        status=hc_types.HealthCheckStatus.PASS,
                        message=(
                            f"{pass_result.message or ''}. {convergence_result.message}"
                        ),
                    )
                else:
                    return convergence_result

        return pass_result

    async def _run_arista(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
    ) -> hc_types.HealthCheckResult:
        """
        Verify BGP sessions on ar-bgp (native EOS BGP) devices via EOS CLI.

        ar-bgp devices have no BGP++ thrift API, so async_get_bgp_sessions()
        is not available. Instead, uses 'show bgp ipv6 unicast summary | json'
        and 'show bgp ipv4 unicast summary | json' to get peer states.

        Args:
            obj: Test device
            input: Base health check input
            check_params: Dictionary containing:
                - expected_established_session_count: Expected established sessions (optional)
                - address_family: "ipv4", "ipv6", or "both" (optional, defaults to "both")
        """
        hostname = obj.name
        expected_established_session_count = check_params.get(
            "expected_established_session_count"
        )
        address_family = check_params.get("address_family", "both")

        if expected_established_session_count is not None:
            try:
                expected_established_session_count = int(
                    expected_established_session_count
                )
            except (ValueError, TypeError):
                expected_established_session_count = None

        self.logger.info(
            f"Running ar-bgp session health check on {hostname} via EOS CLI"
        )

        try:
            all_peers = {}
            bgp_inactive = False

            # Query IPv6 BGP summary
            if address_family in ("ipv6", "both"):
                try:
                    # pyrefly: ignore [missing-attribute]
                    v6_result = await self.driver.async_execute_show_json_on_shell(
                        "show bgp ipv6 unicast summary | json"
                    )
                    v6_peers = (
                        v6_result.get("vrfs", {}).get("default", {}).get("peers", {})
                    )
                    for peer_ip, peer_info in v6_peers.items():
                        all_peers[f"v6:{peer_ip}"] = peer_info
                except Exception as e:
                    if "BGP inactive" in str(e):
                        bgp_inactive = True
                    self.logger.warning(
                        f"Failed to get IPv6 BGP summary on {hostname}: {e}"
                    )

            # Query IPv4 BGP summary
            if address_family in ("ipv4", "both"):
                try:
                    # pyrefly: ignore [missing-attribute]
                    v4_result = await self.driver.async_execute_show_json_on_shell(
                        "show bgp ipv4 unicast summary | json"
                    )
                    v4_peers = (
                        v4_result.get("vrfs", {}).get("default", {}).get("peers", {})
                    )
                    for peer_ip, peer_info in v4_peers.items():
                        all_peers[f"v4:{peer_ip}"] = peer_info
                except Exception as e:
                    if "BGP inactive" in str(e):
                        bgp_inactive = True
                    self.logger.warning(
                        f"Failed to get IPv4 BGP summary on {hostname}: {e}"
                    )

            # If native EOS BGP is inactive, this is likely an ARISTA_FBOSS device
            # running BGP++ instead of native EOS BGP. Fall back to the Thrift-based
            # check which queries BGP++ sessions directly.
            if bgp_inactive and not all_peers:
                self.logger.info(
                    f"Native EOS BGP is inactive on {hostname}, "
                    f"falling back to BGP++ Thrift-based session check"
                )
                return await self._run(obj, input, check_params)

            if not all_peers:
                if expected_established_session_count == 0:
                    return hc_types.HealthCheckResult(
                        status=hc_types.HealthCheckStatus.PASS,
                        message=f"No BGP peers found on {hostname} — matches expected 0",
                    )
                return hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.FAIL,
                    message=f"No BGP peers found on {hostname} via EOS CLI",
                )

            established = 0
            established_peer_addrs = []
            non_established = []
            for peer_key, peer_info in all_peers.items():
                # peer_key is "v4:ip" or "v6:ip", extract raw IP
                raw_ip = peer_key.split(":", 1)[1] if ":" in peer_key else peer_key
                state = peer_info.get("peerState", "Unknown")
                if state == "Established":
                    established += 1
                    established_peer_addrs.append(raw_ip)
                else:
                    non_established.append(
                        f"{peer_key} (state={state}, asn={peer_info.get('asn', '?')})"
                    )

            total = len(all_peers)
            self.logger.info(
                f"ar-bgp sessions on {hostname}: {established}/{total} Established"
            )

            if expected_established_session_count is not None:
                if established == expected_established_session_count:
                    pass_result = hc_types.HealthCheckResult(
                        status=hc_types.HealthCheckStatus.PASS,
                        message=(
                            f"ar-bgp session count matches on {hostname}: "
                            f"{established} established"
                        ),
                    )
                else:
                    return hc_types.HealthCheckResult(
                        status=hc_types.HealthCheckStatus.FAIL,
                        message=(
                            f"ar-bgp session count mismatch on {hostname}: "
                            f"expected {expected_established_session_count}, "
                            f"found {established}/{total}. "
                            f"Non-established: {non_established}"
                        ),
                    )
            else:
                if non_established:
                    return hc_types.HealthCheckResult(
                        status=hc_types.HealthCheckStatus.FAIL,
                        message=(
                            f"{len(non_established)} ar-bgp sessions not established "
                            f"on {hostname}: {non_established}"
                        ),
                    )

                pass_result = hc_types.HealthCheckResult(
                    status=hc_types.HealthCheckStatus.PASS,
                    message=(f"All {total} ar-bgp sessions established on {hostname}"),
                )

            return pass_result

        except Exception as e:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.ERROR,
                message=f"Error checking ar-bgp sessions on {hostname}: {e}",
            )
