# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
"""RBB SRv6 and multi-DUT control-plane verification task.

Runs a device ``show`` command and asserts expected substrings are present
and/or absent, or checks exact BGP peers through the existing FBOSS driver.
Raises ``TestCaseFailure`` (a FAIL verdict, not an ERROR) on mismatch. Used for
the multi-DUT/SRv6 stage gates that cannot be scoped by one playbook-level
health-check invocation:

- S10  topology-selected core port-channel RIF present
- S11  SRv6 tunnels programmed
- S22-S23  tail prefix owned by TE_AGENT with the expected decap SID
- S26  exact steered prefix + SRv6 next-hop present in the FIB
- S28  after direct-route delete, prefix owned by BGPD (not TE_AGENT)

Verification is a registered Task (not a new health-check class) on purpose:
adding a ``CheckName`` enum value is a Thrift change that must be regenerated
and coordinated with a maintainer (§11). This keeps the OSS slice importable
and schema-stable while staying factory-built (§5.1).
"""

import ipaddress
import typing as t

from taac.constants import TestCaseFailure
from taac.tasks.base_task import BaseTask
from taac.utils.driver_factory import async_get_device_driver
from taac.utils.oss_taac_lib_utils import ConsoleFileLogger


class RbbSrv6VerifyTask(BaseTask):
    """Assert show output, interface/BGP state, or exact FIB prefixes."""

    # pyrefly: ignore [bad-override-mutable-attribute]
    NAME: str = "rbb_srv6_verify"

    def __init__(
        self,
        hostname: t.Optional[str] = None,
        description: t.Optional[str] = None,
        ixia: t.Optional[t.Any] = None,
        logger: t.Optional[ConsoleFileLogger] = None,
        shared_data: t.Optional[t.Dict[t.Any, t.Any]] = None,
    ) -> None:
        super().__init__(hostname, description, ixia, logger, shared_data)

    async def run(self, params: t.Dict[str, t.Any]) -> None:
        """Run ``show_cmd`` and assert content.

        params:
            hostname: DUT to query (required).
            show_cmd: command whose stdout is inspected (content checks only).
            expect_contains: substrings that MUST all appear (optional).
            expect_absent: substrings that must NOT appear (optional).
            interfaces_up: interface names that must all be operationally Up.
            bgp_peers_established: exact peer addresses that must be Established.
            fib_prefixes: exact IPv4/IPv6 prefixes that must exist in the FBOSS
                agent FIB.
            gate: human-readable gate label for logs/failure (optional).
        """
        hostname = params.get("hostname") or self.hostname
        if not hostname:
            raise ValueError("rbb_srv6_verify requires 'hostname'")
        show_cmd = params.get("show_cmd")
        expect_contains: t.List[str] = params.get("expect_contains", [])
        expect_absent: t.List[str] = params.get("expect_absent", [])
        interfaces_up: t.List[str] = params.get("interfaces_up", [])
        bgp_peers: t.List[str] = params.get("bgp_peers_established", [])
        fib_prefixes: t.List[str] = params.get("fib_prefixes", [])
        gate = params.get("gate", "rbb_srv6_verify")

        if (
            not expect_contains
            and not expect_absent
            and not interfaces_up
            and not bgp_peers
            and not fib_prefixes
        ):
            raise ValueError(
                "rbb_srv6_verify requires a content, interface-state, or BGP assertion"
            )
        if (expect_contains or expect_absent) and not show_cmd:
            raise ValueError("rbb_srv6_verify content checks require 'show_cmd'")

        driver = await async_get_device_driver(hostname)
        if interfaces_up:
            states = await driver.async_get_interfaces_operational_state(
                interfaces_up
            )
            not_up = [name for name in interfaces_up if states.get(name) is not True]
            if not_up:
                raise TestCaseFailure(
                    f"[{gate}] interfaces are missing or not Up on {hostname}: "
                    f"{not_up}; observed={states}"
                )
        if bgp_peers:
            expected = {str(ipaddress.ip_address(peer)) for peer in bgp_peers}
            sessions = await driver.async_get_bgp_sessions()
            established: t.Set[str] = set()
            for session in sessions:
                state = getattr(getattr(session, "peer", None), "peer_state", None)
                state_name = getattr(state, "name", str(state)).rsplit(".", 1)[-1]
                if state_name.upper() == "ESTABLISHED":
                    established.add(str(ipaddress.ip_address(session.peer_addr)))
            missing_peers = sorted(expected - established)
            if missing_peers:
                raise TestCaseFailure(
                    f"[{gate}] BGP peers are not Established on {hostname}: "
                    f"missing={missing_peers} established={sorted(established)}"
                )
            self.logger.info(
                f"{hostname} -- [{gate}] BGP peers Established: {sorted(expected)}"
            )
        if fib_prefixes:
            expected_fib = {
                str(ipaddress.ip_network(prefix, strict=True))
                for prefix in fib_prefixes
            }
            fib_routes = await driver.async_get_fib_table_entries_all()
            observed_fib = {
                str(
                    ipaddress.ip_network(
                        f"{ipaddress.ip_address(route.dest.ip.addr)}/"
                        f"{route.dest.prefixLength}",
                        strict=False,
                    )
                )
                for route in fib_routes
            }
            missing_fib = sorted(expected_fib - observed_fib)
            if missing_fib:
                raise TestCaseFailure(
                    f"[{gate}] prefixes are absent from the FBOSS FIB on "
                    f"{hostname}: {missing_fib}"
                )
            self.logger.info(
                f"{hostname} -- [{gate}] FIB prefixes present: "
                f"{sorted(expected_fib)}"
            )
        if not show_cmd:
            return
        self.logger.info(f"{hostname} -- [{gate}] verify: {show_cmd}")
        output = await driver.async_run_cmd_on_shell(show_cmd) or ""

        missing = [s for s in expect_contains if s not in output]
        unexpected = [s for s in expect_absent if s in output]

        if missing or unexpected:
            raise TestCaseFailure(
                f"[{gate}] SRv6 verification failed on {hostname} "
                f"(cmd={show_cmd!r}): missing={missing} unexpected_present={unexpected}"
            )
        self.logger.info(f"{hostname} -- [{gate}] verification passed")
