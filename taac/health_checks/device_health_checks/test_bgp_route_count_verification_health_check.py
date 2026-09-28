# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, MagicMock, patch

from neteng.netcastle.logger import ConsoleFileLogger
from taac.constants import TestDevice
from taac.health_checks.device_health_checks.bgp_route_count_verification_health_check import (
    BgpRouteCountVerificationHealthCheck,
)
from taac.health_check.health_check import types as hc_types

_MODULE = (
    "neteng.test_infra.dne.taac.health_checks.device_health_checks."
    "bgp_route_count_verification_health_check"
)


class BgpRouteCountVerificationHealthCheckTest(unittest.IsolatedAsyncioTestCase):
    def _health_check(
        self,
    ) -> tuple[BgpRouteCountVerificationHealthCheck, AsyncMock]:
        health_check = BgpRouteCountVerificationHealthCheck(
            logger=MagicMock(spec=ConsoleFileLogger)
        )
        driver = AsyncMock()
        health_check.driver = driver
        return health_check, driver

    async def test_bgp_inactive_falls_back_before_peer_group_resolution(self) -> None:
        health_check, driver = self._health_check()
        driver.async_execute_show_json_on_shell.side_effect = Exception("BGP inactive")
        device = MagicMock(spec=TestDevice)
        device.name = "dut.example.com"
        health_input = hc_types.BaseHealthCheckIn()
        expected = hc_types.HealthCheckResult(
            status=hc_types.HealthCheckStatus.PASS,
        )

        with patch.object(
            health_check,
            "_run",
            new=AsyncMock(return_value=expected),
        ) as thrift_check:
            result = await health_check._run_arista(
                device,
                health_input,
                {
                    "exact_peer_group_names": ["EB-FA-V6", "EB-FA-V4"],
                    "expected_count": 750,
                },
            )

        self.assertEqual(expected, result)
        thrift_check.assert_awaited_once()
        driver.bgp.assert_not_awaited()

    async def test_raw_payload_rejects_mixed_peer_selectors(self) -> None:
        device = MagicMock(spec=TestDevice)
        device.name = "dut.example.com"
        health_input = hc_types.BaseHealthCheckIn()
        params = {
            "descriptions_to_check": ["EBGP"],
            "exact_peer_group_names": ["EB-FA-V6", "EB-FA-V4"],
            "expected_count": 750,
        }

        for method_name in ("_run", "_run_arista"):
            health_check, driver = self._health_check()
            with self.subTest(method_name=method_name):
                result = await getattr(health_check, method_name)(
                    device,
                    health_input,
                    params,
                )

            self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
            self.assertIn("mutually exclusive", result.message)
            driver.async_get_bgp_sessions.assert_not_awaited()
            driver.async_execute_show_json_on_shell.assert_not_awaited()

    async def test_thrift_histogram_is_compared_per_afi(self) -> None:
        health_check, driver = self._health_check()
        driver.async_get_bgp_sessions.return_value = [object()] * 4
        device = MagicMock(spec=TestDevice)
        device.name = "dut.example.com"
        peers = (
            "2001:db8::1",
            "2001:db8::2",
            "2001:db8::3",
            "2001:db8::4",
        )
        histogram = {
            "ipv4": {720: 2},
            "ipv6": {750: 2},
        }

        with (
            patch(f"{_MODULE}.filter_bgp_sessions", return_value=list(peers)),
            patch(
                f"{_MODULE}.get_route_count_histogram_by_afi_for_peers",
                new=AsyncMock(return_value=histogram),
            ) as collect_histogram,
        ):
            result = await health_check._run(
                device,
                hc_types.BaseHealthCheckIn(),
                {
                    "expected_count_histogram_by_afi": {
                        "ipv4": {"720": 1, "750": 1},
                        "ipv6": {"720": 1, "750": 1},
                    }
                },
            )

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("histogram by AFI", result.message or "")
        self.assertIn("'ipv4': {720: 2}", result.message or "")
        self.assertIn("'ipv6': {750: 2}", result.message or "")
        collect_histogram.assert_awaited_once_with(
            peers=list(peers),
            afis={"ipv4": {720: 1, 750: 1}, "ipv6": {720: 1, 750: 1}},
            direction="received",
            policy_type="pre_policy",
            bgp_helper=driver.bgp.return_value,
        )

    async def test_thrift_histogram_evidence_failure_is_error(self) -> None:
        health_check, driver = self._health_check()
        driver.async_get_bgp_sessions.return_value = [object()]
        device = MagicMock(spec=TestDevice)
        device.name = "dut.example.com"

        with (
            patch(f"{_MODULE}.filter_bgp_sessions", return_value=["2001:db8::1"]),
            patch(
                f"{_MODULE}.get_route_count_histogram_by_afi_for_peers",
                new=AsyncMock(side_effect=ValueError("missing session details")),
            ),
        ):
            result = await health_check._run(
                device,
                hc_types.BaseHealthCheckIn(),
                {"expected_count_histogram_by_afi": {"ipv4": {720: 1}}},
            )

        self.assertEqual(hc_types.HealthCheckStatus.ERROR, result.status)
        self.assertIn(
            "Could not collect authoritative route-count histogram",
            result.message or "",
        )
        self.assertIn("missing session details", result.message or "")

    async def test_thrift_histogram_empty_requested_afi_is_failure(self) -> None:
        health_check, driver = self._health_check()
        driver.async_get_bgp_sessions.return_value = [object()]
        device = MagicMock(spec=TestDevice)
        device.name = "dut.example.com"
        actual = {"ipv4": {}, "ipv6": {750: 1}}

        with (
            patch(
                f"{_MODULE}.filter_bgp_sessions",
                return_value=["2001:db8::1"],
            ),
            patch(
                f"{_MODULE}.get_route_count_histogram_by_afi_for_peers",
                new=AsyncMock(return_value=actual),
            ),
        ):
            result = await health_check._run(
                device,
                hc_types.BaseHealthCheckIn(),
                {
                    "expected_count_histogram_by_afi": {
                        "ipv4": {720: 1},
                        "ipv6": {750: 1},
                    }
                },
            )

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        self.assertIn("'ipv4': {}", result.message or "")
        self.assertIn("'ipv6': {750: 1}", result.message or "")

    async def test_arista_histogram_queries_and_validates_both_afis(self) -> None:
        health_check, driver = self._health_check()
        driver.async_execute_show_json_on_shell.side_effect = [
            {
                "vrfs": {
                    "default": {
                        "peers": {
                            "192.0.2.1": {
                                "peerState": "Established",
                                "prefixReceived": 720,
                            },
                            "192.0.2.2": {
                                "peerState": "Established",
                                "prefixReceived": 750,
                            },
                        }
                    }
                }
            },
            {
                "vrfs": {
                    "default": {
                        "peers": {
                            "2001:db8::1": {
                                "peerState": "Established",
                                "prefixReceived": 720,
                            },
                            "2001:db8::2": {
                                "peerState": "Established",
                                "prefixReceived": 750,
                            },
                        }
                    }
                }
            },
        ]
        device = MagicMock(spec=TestDevice)
        device.name = "dut.example.com"

        result = await health_check._run_arista(
            device,
            hc_types.BaseHealthCheckIn(),
            {
                "expected_count_histogram_by_afi": {
                    "ipv4": {"720": 1, "750": 1},
                    "ipv6": {"720": 1, "750": 1},
                }
            },
        )

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertEqual(
            [
                call("show bgp ipv4 unicast summary | json"),
                call("show bgp ipv6 unicast summary | json"),
            ],
            driver.async_execute_show_json_on_shell.await_args_list,
        )

    async def test_arista_histogram_uses_queried_afi_for_shared_peer_ip(self) -> None:
        health_check, driver = self._health_check()
        driver.async_execute_show_json_on_shell.side_effect = [
            {
                "vrfs": {
                    "default": {
                        "peers": {
                            "192.0.2.1": {
                                "peerState": "Established",
                                "prefixReceived": 720,
                            }
                        }
                    }
                }
            },
            {
                "vrfs": {
                    "default": {
                        "peers": {
                            "192.0.2.1": {
                                "peerState": "Established",
                                "prefixReceived": 750,
                            }
                        }
                    }
                }
            },
        ]
        device = MagicMock(spec=TestDevice)
        device.name = "dut.example.com"

        result = await health_check._run_arista(
            device,
            hc_types.BaseHealthCheckIn(),
            {
                "expected_count_histogram_by_afi": {
                    "ipv4": {"720": 1},
                    "ipv6": {"750": 1},
                }
            },
        )

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)
        self.assertIn("1 peers checked", result.message or "")

    async def test_arista_empty_first_afi_is_error_but_checks_second_afi(
        self,
    ) -> None:
        health_check, driver = self._health_check()
        driver.async_execute_show_json_on_shell.side_effect = [
            {"vrfs": {"default": {"peers": {}}}},
            {
                "vrfs": {
                    "default": {
                        "peers": {
                            "2001:db8::1": {
                                "peerState": "Established",
                                "prefixReceived": 749,
                            }
                        }
                    }
                }
            },
        ]
        device = MagicMock(spec=TestDevice)
        device.name = "dut.example.com"

        result = await health_check._run_arista(
            device,
            hc_types.BaseHealthCheckIn(),
            {
                "expected_count_histogram_by_afi": {
                    "ipv4": {"720": 1},
                    "ipv6": {"750": 1},
                }
            },
        )

        self.assertEqual(hc_types.HealthCheckStatus.ERROR, result.status)
        self.assertIn(
            "No BGP peers found on dut.example.com for ipv4", result.message or ""
        )
        self.assertNotIn(
            "Expected route-count histogram for ipv4 {720: 1}, got {}",
            result.message or "",
        )
        self.assertIn("histogram for ipv6", result.message or "")
        self.assertIn("{749: 1}", result.message or "")
        self.assertEqual(2, driver.async_execute_show_json_on_shell.await_count)

    async def test_arista_malformed_route_counts_are_errors(self) -> None:
        for count_check in (
            {"expected_count": 720},
            {"min_count": 720},
            {"max_count": 720},
            {"expected_count_histogram_by_afi": {"ipv4": {"720": 1}}},
        ):
            for malformed_count in (
                None,
                "not-a-count",
                "720",
                True,
                720.0,
                720.5,
                -1,
            ):
                with self.subTest(
                    count_check=count_check,
                    malformed_count=malformed_count,
                ):
                    health_check, driver = self._health_check()
                    driver.async_execute_show_json_on_shell.return_value = {
                        "vrfs": {
                            "default": {
                                "peers": {
                                    "192.0.2.1": {
                                        "peerState": "Established",
                                        "prefixReceived": malformed_count,
                                    }
                                }
                            }
                        }
                    }
                    device = MagicMock(spec=TestDevice)
                    device.name = "dut.example.com"

                    result = await health_check._run_arista(
                        device,
                        hc_types.BaseHealthCheckIn(),
                        {"address_family": "ipv4", **count_check},
                    )

                    self.assertEqual(hc_types.HealthCheckStatus.ERROR, result.status)
                    self.assertIn("Peer 192.0.2.1 for ipv4", result.message or "")
                    self.assertIn("invalid prefixReceived", result.message or "")
                    if "expected_count_histogram_by_afi" in count_check:
                        self.assertNotIn(
                            "Expected route-count histogram",
                            result.message or "",
                        )

    async def test_arista_malformed_count_continues_all_peers_and_afis(self) -> None:
        health_check, driver = self._health_check()
        driver.async_execute_show_json_on_shell.side_effect = [
            {
                "vrfs": {
                    "default": {
                        "peers": {
                            "192.0.2.1": {
                                "peerState": "Established",
                                "prefixReceived": "not-a-count",
                            },
                            "192.0.2.2": {
                                "peerState": "Established",
                                "prefixReceived": 719,
                            },
                        }
                    }
                }
            },
            {
                "vrfs": {
                    "default": {
                        "peers": {
                            "2001:db8::1": {
                                "peerState": "Established",
                                "prefixReceived": 749,
                            }
                        }
                    }
                }
            },
        ]
        device = MagicMock(spec=TestDevice)
        device.name = "dut.example.com"

        result = await health_check._run_arista(
            device,
            hc_types.BaseHealthCheckIn(),
            {
                "expected_count_histogram_by_afi": {
                    "ipv4": {720: 1},
                    "ipv6": {750: 1},
                }
            },
        )

        self.assertEqual(hc_types.HealthCheckStatus.ERROR, result.status)
        message = result.message or ""
        self.assertIn(
            "Peer 192.0.2.1 for ipv4: invalid prefixReceived value 'not-a-count'",
            message,
        )
        self.assertNotIn(
            "Expected route-count histogram for ipv4 {720: 1}, got {719: 1}",
            message,
        )
        self.assertIn(
            "Expected route-count histogram for ipv6 {750: 1}, got {749: 1}",
            message,
        )
        self.assertEqual(2, driver.async_execute_show_json_on_shell.await_count)

    async def test_arista_missing_route_count_preserves_legacy_zero(self) -> None:
        health_check, driver = self._health_check()
        driver.async_execute_show_json_on_shell.return_value = {
            "vrfs": {
                "default": {
                    "peers": {
                        "192.0.2.1": {
                            "peerState": "Established",
                        }
                    }
                }
            }
        }
        device = MagicMock(spec=TestDevice)
        device.name = "dut.example.com"

        result = await health_check._run_arista(
            device,
            hc_types.BaseHealthCheckIn(),
            {"address_family": "ipv4", "expected_count": 0},
        )

        self.assertEqual(hc_types.HealthCheckStatus.PASS, result.status)

    async def test_arista_valid_route_count_mismatches_are_failures(self) -> None:
        for count_check, received_count in (
            ({"expected_count": 720}, 719),
            ({"min_count": 720}, 719),
            ({"max_count": 720}, 721),
        ):
            with self.subTest(
                count_check=count_check,
                received_count=received_count,
            ):
                health_check, driver = self._health_check()
                driver.async_execute_show_json_on_shell.return_value = {
                    "vrfs": {
                        "default": {
                            "peers": {
                                "192.0.2.1": {
                                    "peerState": "Established",
                                    "prefixReceived": received_count,
                                }
                            }
                        }
                    }
                }
                device = MagicMock(spec=TestDevice)
                device.name = "dut.example.com"

                result = await health_check._run_arista(
                    device,
                    hc_types.BaseHealthCheckIn(),
                    {"address_family": "ipv4", **count_check},
                )

                self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)

    async def test_arista_histogram_filter_miss_is_reported_once(self) -> None:
        health_check, driver = self._health_check()
        driver.async_execute_show_json_on_shell.side_effect = [
            {
                "vrfs": {
                    "default": {
                        "peers": {
                            "192.0.2.1": {
                                "description": "IBGP",
                                "peerState": "Established",
                                "prefixReceived": 720,
                            }
                        }
                    }
                }
            },
            {
                "vrfs": {
                    "default": {
                        "peers": {
                            "2001:db8::1": {
                                "description": "EBGP",
                                "peerState": "Established",
                                "prefixReceived": 749,
                            }
                        }
                    }
                }
            },
        ]
        device = MagicMock(spec=TestDevice)
        device.name = "dut.example.com"

        result = await health_check._run_arista(
            device,
            hc_types.BaseHealthCheckIn(),
            {
                "descriptions_to_check": ["EBGP"],
                "expected_count_histogram_by_afi": {
                    "ipv4": {720: 1},
                    "ipv6": {750: 1},
                },
            },
        )

        self.assertEqual(hc_types.HealthCheckStatus.FAIL, result.status)
        message = result.message or ""
        self.assertEqual(1, message.count("No peers matched filter"))
        self.assertNotIn("Expected route-count histogram for ipv4", message)
        self.assertIn(
            "Expected route-count histogram for ipv6 {750: 1}, got {749: 1}",
            message,
        )

    async def test_exact_peer_groups_resolve_without_update_group_api(self) -> None:
        health_check, driver = self._health_check()
        bgp_helper = driver.bgp.return_value
        bgp_helper.async_get_running_config_struct.return_value = SimpleNamespace(
            peers=[
                SimpleNamespace(
                    peer_group_name="EB-FA-V6",
                    peer_addr="2001:db8::1",
                ),
                SimpleNamespace(
                    peer_group_name="EB-FA-V4",
                    peer_addr="192.0.2.1",
                ),
            ],
        )
        bgp_helper.async_get_update_group_info = AsyncMock()

        selected = await health_check._resolve_peer_group_addresses(
            "dut.example.com",
            ["EB-FA-V6", "EB-FA-V4"],
        )

        self.assertEqual({"2001:db8::1", "192.0.2.1"}, selected)
        driver.bgp.assert_awaited_once_with()
        bgp_helper.async_get_running_config_struct.assert_awaited_once_with()
        bgp_helper.async_get_update_group_info.assert_not_awaited()

    async def test_exact_peer_group_failure_includes_config_diagnostics(
        self,
    ) -> None:
        health_check, driver = self._health_check()
        bgp_helper = driver.bgp.return_value
        bgp_helper.async_get_running_config_struct.return_value = SimpleNamespace(
            peers=[
                SimpleNamespace(
                    peer_group_name="EB-FA-V6",
                    peer_addr="2001:db8::1",
                )
            ],
        )

        with self.assertRaises(RuntimeError) as error:
            await health_check._resolve_peer_group_addresses(
                "dut.example.com",
                ["EB-FA-V6", "EB-FA-V4"],
            )

        message = str(error.exception)
        self.assertIn("missing=['EB-FA-V4']", message)
        self.assertIn("observed=['EB-FA-V6']", message)
        self.assertIn("configured_peers=1", message)

    async def test_arista_exact_selector_with_validation_mismatch_reports_error(
        self,
    ) -> None:
        health_check, driver = self._health_check()
        driver.async_execute_show_json_on_shell.side_effect = [
            {
                "vrfs": {
                    "default": {
                        "peers": {
                            "192.0.2.9": {
                                "description": "unselected",
                                "peerState": "Established",
                                "prefixReceived": 750,
                            }
                        }
                    }
                }
            },
            {
                "vrfs": {
                    "default": {
                        "peers": {
                            "2001:db8::1": {
                                "description": "selected",
                                "peerState": "Established",
                                "prefixReceived": 749,
                            }
                        }
                    }
                }
            },
        ]
        device = MagicMock(spec=TestDevice)
        device.name = "dut.example.com"

        with patch.object(
            health_check,
            "_resolve_peer_group_addresses",
            new=AsyncMock(return_value={"192.0.2.1", "2001:db8::1"}),
        ):
            result = await health_check._run_arista(
                device,
                hc_types.BaseHealthCheckIn(),
                {
                    "exact_peer_group_names": ["EB-FA-V6", "EB-FA-V4"],
                    "expected_count_histogram_by_afi": {
                        "ipv4": {750: 1},
                        "ipv6": {750: 1},
                    },
                },
            )

        self.assertEqual(hc_types.HealthCheckStatus.ERROR, result.status)
        message = result.message or ""
        self.assertIn("Error verifying ar-bgp route counts", message)
        self.assertIn(
            "No established peers matched the selected exact peer groups for ipv4",
            message,
        )
        self.assertNotIn(
            "Expected route-count histogram for ipv4 {750: 1}, got {}",
            message,
        )
        self.assertIn(
            "Expected route-count histogram for ipv6 {750: 1}, got {749: 1}",
            message,
        )

    async def test_arista_exact_selector_without_validation_mismatch_reports_error(
        self,
    ) -> None:
        health_check, driver = self._health_check()
        driver.async_execute_show_json_on_shell.return_value = {
            "vrfs": {
                "default": {
                    "peers": {
                        "192.0.2.9": {
                            "description": "unselected",
                            "peerState": "Established",
                            "prefixReceived": 750,
                        }
                    }
                }
            }
        }
        device = MagicMock(spec=TestDevice)
        device.name = "dut.example.com"

        with patch.object(
            health_check,
            "_resolve_peer_group_addresses",
            new=AsyncMock(return_value={"192.0.2.1"}),
        ):
            result = await health_check._run_arista(
                device,
                hc_types.BaseHealthCheckIn(),
                {
                    "address_family": "ipv4",
                    "exact_peer_group_names": ["EB-FA-V4"],
                    "expected_count": 750,
                },
            )

        self.assertEqual(hc_types.HealthCheckStatus.ERROR, result.status)
        self.assertEqual(
            "Error verifying ar-bgp route counts on dut.example.com: "
            "No established peers matched the selected exact peer groups for ipv4",
            result.message,
        )
