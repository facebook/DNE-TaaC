# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe
import typing as t
from collections import namedtuple

from neteng.fboss.bgp_attr.types import TBgpAfi, TIpPrefix
from neteng.fboss.bgp_thrift.types import TBgpPeerState
from taac.constants import TestDevice
from taac.health_checks.abstract_snapshot_health_check import (
    AbstractDeviceSnapshotHealthCheck,
    Snapshot,
)
from taac.utils.health_check_utils import is_parent_prefix
from taac.health_check.health_check import types as hc_types


BgpSummaryData = namedtuple(
    "BgpSummaryData", ["total_paths_received", "total_paths_sent", "peer_data"]
)

BgpPeerData = namedtuple("BgpPeerData", ["prefixes_sent", "prefixes_received"])


def format_ip_prefix(prefix: TIpPrefix) -> str:
    """Format TIpPrefix for display."""
    try:
        import socket

        # TIpPrefix has afi, prefix_bin, and num_bits attributes
        if (
            hasattr(prefix, "prefix_bin")
            and hasattr(prefix, "num_bits")
            and hasattr(prefix, "afi")
        ):
            # Use enum comparison directly
            if prefix.afi == TBgpAfi.AFI_IPV4:  # IPv4
                # IPv4 addresses are 4 bytes
                addr_bytes = prefix.prefix_bin[:4]
                addr = socket.inet_ntoa(addr_bytes)
            elif prefix.afi == TBgpAfi.AFI_IPV6:  # IPv6
                # IPv6 addresses are 16 bytes
                addr_bytes = prefix.prefix_bin[:16]
                addr = socket.inet_ntop(socket.AF_INET6, addr_bytes)
            else:
                return f"Unknown AFI {prefix.afi}: {prefix.prefix_bin.hex()}/{prefix.num_bits}"

            return f"{addr}/{prefix.num_bits}"
        else:
            return str(prefix)
    except Exception as e:
        return f"Error formatting prefix: {e} - {str(prefix)}"


def count_bgp_paths(path_or_paths) -> int:
    """Count BGP paths, handling both single TBgpPath and list of TBgpPath."""
    if isinstance(path_or_paths, list):
        return len(path_or_paths)
    else:
        return 1  # Single TBgpPath object


class BgpPeersHealthCheck(
    AbstractDeviceSnapshotHealthCheck[hc_types.BaseHealthCheckIn],
):
    CHECK_NAME = hc_types.CheckName.BGP_PEER_ROUTE_CHECK
    OPERATING_SYSTEMS = ["FBOSS"]

    async def capture_pre_snapshot(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
        timestamp: int,
    ) -> Snapshot:
        self.logger.debug(f"Capturing BGP summary pre-snapshot on {obj.name}")
        parent_peers_to_ignore = check_params.get("parent_peers_to_ignore", [])
        parent_prefixes_to_ignore = check_params.get("parent_prefixes_to_ignore", [])
        verbose = check_params.get("verbose", False)
        bgp_summary_data = await self.get_bgp_summary_data(
            obj, parent_peers_to_ignore, parent_prefixes_to_ignore, verbose
        )
        self.logger.info(
            f"Pre-snapshot BGP data for {obj.name}: "
            f"Total paths received: {bgp_summary_data.total_paths_received}, "
            f"Total paths sent: {bgp_summary_data.total_paths_sent}, "
            f"Number of peers: {len(bgp_summary_data.peer_data)}"
        )
        return Snapshot(data=bgp_summary_data, timestamp=timestamp)

    async def capture_post_snapshot(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
        timestamp: int,
    ) -> Snapshot:
        self.logger.debug(f"Capturing BGP summary post-snapshot on {obj.name}")
        parent_peers_to_ignore = check_params.get("parent_peers_to_ignore", [])
        parent_prefixes_to_ignore = check_params.get("parent_prefixes_to_ignore", [])
        verbose = check_params.get("verbose", False)
        bgp_summary_data = await self.get_bgp_summary_data(
            obj, parent_peers_to_ignore, parent_prefixes_to_ignore, verbose
        )
        self.logger.info(
            f"Post-snapshot BGP data for {obj.name}: "
            f"Total paths received: {bgp_summary_data.total_paths_received}, "
            f"Total paths sent: {bgp_summary_data.total_paths_sent}, "
            f"Number of peers: {len(bgp_summary_data.peer_data)}"
        )
        return Snapshot(data=bgp_summary_data, timestamp=timestamp)

    async def compare_snapshots(
        self,
        obj: TestDevice,
        input: hc_types.BaseHealthCheckIn,
        check_params: t.Dict[str, t.Any],
        pre_snapshot: Snapshot,
        post_snapshot: Snapshot,
    ) -> hc_types.HealthCheckResult:
        self.logger.debug(f"Comparing BGP summary snapshots on {obj.name}")

        pre_data = pre_snapshot.data
        post_data = post_snapshot.data

        self.logger.info(
            f"Comparison for {obj.name} - Pre: {pre_data.total_paths_received} received, "
            f"{pre_data.total_paths_sent} sent, {len(pre_data.peer_data)} peers | "
            f"Post: {post_data.total_paths_received} received, "
            f"{post_data.total_paths_sent} sent, {len(post_data.peer_data)} peers"
        )

        issues = []

        # Compare total paths
        if pre_data.total_paths_received != post_data.total_paths_received:
            issues.append(
                f"Total paths received changed from {pre_data.total_paths_received} "
                f"to {post_data.total_paths_received}"
            )

        if pre_data.total_paths_sent != post_data.total_paths_sent:
            issues.append(
                f"Total paths sent changed from {pre_data.total_paths_sent} "
                f"to {post_data.total_paths_sent}"
            )

        # Compare per-peer data
        pre_peers = set(pre_data.peer_data.keys())
        post_peers = set(post_data.peer_data.keys())

        # Check for missing peers
        missing_peers = pre_peers - post_peers
        if missing_peers:
            issues.append(f"Missing peers in post-snapshot: {missing_peers}")

        # Check for new peers
        new_peers = post_peers - pre_peers
        if new_peers:
            issues.append(f"New peers in post-snapshot: {new_peers}")

        # Compare existing peers
        common_peers = pre_peers & post_peers
        for peer in common_peers:
            pre_peer_data = pre_data.peer_data[peer]
            post_peer_data = post_data.peer_data[peer]

            if pre_peer_data.prefixes_sent != post_peer_data.prefixes_sent:
                issues.append(
                    f"Peer {peer}: Prefixes sent changed from {pre_peer_data.prefixes_sent} "
                    f"to {post_peer_data.prefixes_sent}"
                )

            if pre_peer_data.prefixes_received != post_peer_data.prefixes_received:
                issues.append(
                    f"Peer {peer}: Prefixes received changed from {pre_peer_data.prefixes_received} "
                    f"to {post_peer_data.prefixes_received}"
                )

        if issues:
            return hc_types.HealthCheckResult(
                status=hc_types.HealthCheckStatus.FAIL,
                message=f"BGP summary changes detected: {'\n '.join(issues)}",
            )

        return hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
            message="BGP summary data is consistent between snapshots",
        )

    async def get_bgp_summary_data(
        self,
        obj: TestDevice,
        parent_peers_to_ignore: t.Optional[t.List[str]] = None,
        parent_prefixes_to_ignore: t.Optional[t.List[str]] = None,
        verbose: bool = False,
    ) -> BgpSummaryData:
        """
        Get BGP summary data using Thrift API to extract total paths and per-peer PS/PR/uptime data.
        Args:
            obj: The test device
            parent_peers_to_ignore: List of parent prefixes to ignore when collecting BGP data
            parent_prefixes_to_ignore: List of BGP prefixes to ignore when calculating paths
        """

        # Get BGP sessions using Thrift API
        # pyrefly: ignore [missing-attribute]
        bgp_sessions = await self.driver.async_get_bgp_sessions()

        self.logger.debug(f"Retrieved {len(bgp_sessions)} BGP sessions for {obj.name}")

        # Calculate totals and per-peer data
        total_paths_received = 0
        total_paths_sent = 0
        peer_data = {}
        ignored_peers_count = 0

        for session in bgp_sessions:
            peer_ip = str(session.peer_addr)

            # Check if this peer should be ignored based on parent prefixes
            if parent_peers_to_ignore:
                should_ignore_prefix = any(
                    is_parent_prefix(peer_ip, parent_peer)
                    for parent_peer in parent_peers_to_ignore
                )
                if should_ignore_prefix:
                    ignored_peers_count += 1
                    if verbose:
                        self.logger.debug(
                            f"Ignoring peer {peer_ip} due to parent prefix match"
                        )
                    continue

            if session.peer.peer_state != TBgpPeerState.ESTABLISHED:
                continue

            # If parent_prefixes_to_ignore is provided, use thrift APIs to get detailed prefix data
            if parent_prefixes_to_ignore:
                (
                    prefixes_received,
                    prefixes_sent,
                ) = await self._get_filtered_prefix_counts(
                    peer_ip, parent_prefixes_to_ignore, verbose
                )
            else:
                # Use session counters for backward compatibility
                prefixes_received = session.prepolicy_rcvd_prefix_count
                prefixes_sent = session.postpolicy_sent_prefix_count

            # Add to totals
            total_paths_received += prefixes_received
            total_paths_sent += prefixes_sent

            # Store per-peer data
            peer_data[peer_ip] = BgpPeerData(
                prefixes_sent=prefixes_sent,
                prefixes_received=prefixes_received,
            )

        # Log summary information including ignored peers count
        ignore_summary = ""
        if parent_prefixes_to_ignore:
            ignore_summary = (
                f", using {len(parent_prefixes_to_ignore)} prefix ignore patterns"
            )
        if parent_peers_to_ignore:
            ignore_summary += (
                f", using {len(parent_peers_to_ignore)} peer ignore patterns"
            )

        self.logger.info(
            f"BGP summary for {obj.name}: {len(peer_data)} active peers, "
            f"{ignored_peers_count} peers ignored, "
            f"{total_paths_received} total paths received, "
            f"{total_paths_sent} total paths sent{ignore_summary}"
        )

        result = BgpSummaryData(
            total_paths_received=total_paths_received,
            total_paths_sent=total_paths_sent,
            peer_data=peer_data,
        )

        return result

    async def _get_filtered_prefix_counts(
        self,
        peer_ip: str,
        parent_prefixes_to_ignore: t.List[str],
        verbose: bool = False,
    ) -> t.Tuple[int, int]:
        """
        Get filtered prefix counts for a peer by calling thrift APIs and filtering out ignored prefixes.

        Args:
            peer_ip: The IP address of the BGP peer
            parent_prefixes_to_ignore: List of BGP prefixes to ignore when counting

        Returns:
            Tuple of (prefixes_received_count, prefixes_sent_count) after filtering
        """
        try:
            # Get received networks using thrift API
            received_networks = (
                # pyrefly: ignore [missing-attribute]
                await self.driver.async_get_postfilter_received_networks(peer_ip)
            )

            # Get advertised networks using thrift API
            advertised_networks = (
                # pyrefly: ignore [missing-attribute]
                await self.driver.async_get_postfilter_advertised_networks(peer_ip)
            )

            # Filter out ignored prefixes from received networks
            filtered_received_count = 0
            ignored_received_prefixes = []
            ignored_received_paths_count = 0

            for prefix, path in received_networks.items():
                prefix_str = format_ip_prefix(prefix)
                should_ignore = any(
                    self._prefix_matches_ignore_pattern(prefix_str, ignore_prefix)
                    for ignore_prefix in parent_prefixes_to_ignore
                )
                if should_ignore:
                    # Track ignored prefixes and their path counts
                    path_count = count_bgp_paths(path)
                    ignored_received_prefixes.append(prefix_str)
                    ignored_received_paths_count += path_count
                else:
                    # Count the number of paths for this prefix
                    filtered_received_count += count_bgp_paths(path)

            # Filter out ignored prefixes from advertised networks
            filtered_sent_count = 0
            ignored_sent_prefixes = []
            ignored_sent_paths_count = 0

            for prefix, path in advertised_networks.items():
                prefix_str = format_ip_prefix(prefix)
                should_ignore = any(
                    self._prefix_matches_ignore_pattern(prefix_str, ignore_prefix)
                    for ignore_prefix in parent_prefixes_to_ignore
                )
                if should_ignore:
                    # Track ignored prefixes and their path counts
                    path_count = count_bgp_paths(path)
                    ignored_sent_prefixes.append(prefix_str)
                    ignored_sent_paths_count += path_count
                else:
                    # Count the number of paths for this prefix
                    filtered_sent_count += count_bgp_paths(path)

            # Log summary of ignored prefixes per peer (only if verbose is enabled)
            if verbose and (ignored_received_prefixes or ignored_sent_prefixes):
                self.logger.debug(
                    f"Peer {peer_ip}: Ignored {len(ignored_received_prefixes)} received prefixes "
                    f"({ignored_received_paths_count} paths), {len(ignored_sent_prefixes)} sent prefixes "
                    f"({ignored_sent_paths_count} paths)"
                )

            if verbose:
                self.logger.debug(
                    f"Peer {peer_ip}: Final counts - Received: {filtered_received_count}, "
                    f"Sent: {filtered_sent_count} (after applying {len(parent_prefixes_to_ignore)} ignore patterns)"
                )

            return filtered_received_count, filtered_sent_count

        except Exception as e:
            self.logger.error(
                f"Error getting filtered prefix counts for peer {peer_ip}: {e}"
            )
            # Fall back to 0 counts on error
            return 0, 0

    def _prefix_matches_ignore_pattern(self, prefix: str, ignore_pattern: str) -> bool:
        """
        Check if a prefix matches an ignore pattern by checking if it's a subnet of the ignore pattern.

        Args:
            prefix: The BGP prefix string (e.g., "192.168.1.0/25")
            ignore_pattern: The parent prefix pattern to match against (e.g., "192.168.1.0/24")

        Returns:
            True if the prefix should be ignored (i.e., it's a subnet of ignore_pattern), False otherwise
        """
        try:
            import ipaddress

            # Parse the prefix and ignore pattern as IP networks
            prefix_network = ipaddress.ip_network(prefix, strict=False)
            ignore_network = ipaddress.ip_network(ignore_pattern, strict=False)

            # Check if both networks are the same IP version (IPv4 vs IPv6)
            if prefix_network.version != ignore_network.version:
                # Different IP versions can't be subnets of each other
                return False

            # Check if the prefix is a subnet of the ignore pattern
            # pyrefly: ignore [bad-argument-type]
            return prefix_network.subnet_of(ignore_network)

        # pyrefly: ignore [unbound-name]
        except (ipaddress.AddressValueError, ValueError) as e:
            self.logger.warning(
                f"Error parsing IP networks - prefix: {prefix}, ignore_pattern: {ignore_pattern}, error: {e}"
            )
            # Fall back to exact string match if parsing fails
            return prefix == ignore_pattern
