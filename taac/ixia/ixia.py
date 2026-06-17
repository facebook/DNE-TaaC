#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.

# pyre-unsafe

import ipaddress
import itertools
import logging
import os
import random
import re
import threading
import time
import typing as t
import warnings
from collections import defaultdict, namedtuple
from concurrent.futures import as_completed, ThreadPoolExecutor
from dataclasses import dataclass, field
from ipaddress import ip_address, IPv6Address

TAAC_OSS = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")

if not TAAC_OSS:
    from configerator.client import ConfigeratorClient

from ixia.ixia import types as ixia_types
from ixnetwork_restpy.assistants.sessions.sessionassistant import (
    SessionAssistant as IxnSessionAssistant,
)
from ixnetwork_restpy.assistants.statistics.statviewassistant import (
    StatViewAssistant as IxnStatViewAssistant,
)
from ixnetwork_restpy.files import Files
from taac.libs.custom_payload_registry import (
    get_custom_frame_payload,
)
from taac.utils.common import timeit
from taac.utils.oss_taac_lib_utils import (
    await_sync,
    memoize_forever,
    none_throws,
    retryable,
    to_fb_uqdn,
)

# The monorepo ships these constants at neteng.test_infra.ixia.ixnetwork_restpy.constants;
# in OSS we vendor a copy alongside this module.
if TAAC_OSS:
    from taac.ixia.ixnetwork_restpy_constants import (
        ALLOWED_IPV4_ADVERTISEMENTS,
        ALLOWED_IPV6_ADVERTISEMENTS,
        API_SERVER_PASSWORD,
        API_SERVER_USERNAME,
        DESIRED_BGP_V4_PEER_NAME,
        DESIRED_BGP_V4_PREFIX_NAME,
        DESIRED_BGP_V6_PEER_NAME,
        DESIRED_BGP_V6_PREFIX_NAME,
        DESIRED_DEVICE_GROUP_NAME,
        DESIRED_ETHERNET_NAME,
        DESIRED_IPV4_NAME,
        DESIRED_IPV6_NAME,
        DESIRED_IPV6_PTP_NAME,
        DESIRED_TOPOLOGY_NAME,
        DESIRED_V4_BGP_PREFIX_NAME,
        DESIRED_V6_BGP_PREFIX_NAME,
        DESIRED_VPORT_NAME,
    )
else:
    from neteng.test_infra.ixia.ixnetwork_restpy.constants import (
        ALLOWED_IPV4_ADVERTISEMENTS,
        ALLOWED_IPV6_ADVERTISEMENTS,
        API_SERVER_PASSWORD,
        API_SERVER_USERNAME,
        DESIRED_BGP_V4_PEER_NAME,
        DESIRED_BGP_V4_PREFIX_NAME,
        DESIRED_BGP_V6_PEER_NAME,
        DESIRED_BGP_V6_PREFIX_NAME,
        DESIRED_DEVICE_GROUP_NAME,
        DESIRED_ETHERNET_NAME,
        DESIRED_IPV4_NAME,
        DESIRED_IPV6_NAME,
        DESIRED_IPV6_PTP_NAME,
        DESIRED_TOPOLOGY_NAME,
        DESIRED_V4_BGP_PREFIX_NAME,
        DESIRED_V6_BGP_PREFIX_NAME,
        DESIRED_VPORT_NAME,
    )
from uhd_restpy.assistants.sessions.sessionassistant import (
    SessionAssistant as UhdSessionAssistant,
)
from uhd_restpy.assistants.statistics.statviewassistant import (
    StatViewAssistant as UhdStatViewAssistant,
)


warnings.filterwarnings(action="ignore", category=ResourceWarning)
warnings.filterwarnings(action="ignore", category=DeprecationWarning)

from ixnetwork_restpy.testplatform.sessions.ixnetwork.topology.bgpipv6peer_8b9aa9838ebd53702954aa471913ed1e import (
    BgpIpv6Peer as IxnBgpIpv6Peer,
)
from uhd_restpy.testplatform.sessions.ixnetwork.topology.bgpipv6peer_d4ac277d9da759fd5a152b8e6eb0ab20 import (
    BgpIpv6Peer as UhdBgpIpv6Peer,
)

BgpIpv6Peer = t.Union[IxnBgpIpv6Peer, UhdBgpIpv6Peer]

from ixnetwork_restpy.testplatform.sessions.ixnetwork.topology.ipv4prefixpools_2d6f2aedde61c058965d4e1b21741352 import (
    Ipv4PrefixPools as IxnIpv4PrefixPools,
)
from uhd_restpy.testplatform.sessions.ixnetwork.topology.ipv4prefixpools_2d6f2aedde61c058965d4e1b21741352 import (
    Ipv4PrefixPools as UhdIpv4PrefixPools,
)

Ipv4PrefixPools = t.Union[IxnIpv4PrefixPools, UhdIpv4PrefixPools]
from ixnetwork_restpy.testplatform.sessions.ixnetwork.topology.ipv6prefixpools_f83aba85ff769655b348dc60ddcb30f2 import (
    Ipv6PrefixPools as IxnIpv6PrefixPools,
)
from uhd_restpy.testplatform.sessions.ixnetwork.topology.ipv6prefixpools_f83aba85ff769655b348dc60ddcb30f2 import (
    Ipv6PrefixPools as UhdIpv6PrefixPools,
)

Ipv6PrefixPools = t.Union[IxnIpv6PrefixPools, UhdIpv6PrefixPools]


if t.TYPE_CHECKING:
    # fmt: off
    # TODO: Create shorthands for these long absolute imports for readability
    from ixnetwork_restpy.testplatform.testplatform import (
        TestPlatform as IxnTestPlatform,
    )
    from uhd_restpy.testplatform.testplatform import TestPlatform as UhdTestPlatform
    TestPlatform = t.Union[IxnTestPlatform, UhdTestPlatform]
    from ixnetwork_restpy.testplatform.sessions.sessions import Sessions as IxnSessions
    from uhd_restpy.testplatform.sessions.sessions import Sessions as UhdSessions
    Sessions = t.Union[IxnSessions, UhdSessions]
    from ixnetwork_restpy.testplatform.sessions.ixnetwork.ixnetwork import (
        Ixnetwork as IxnIxnetwork,
    )
    from uhd_restpy.testplatform.sessions.ixnetwork.ixnetwork import (
        Ixnetwork as UhdIxnetwork,
    )
    Ixnetwork = t.Union[IxnIxnetwork, UhdIxnetwork]
    from ixnetwork_restpy.testplatform.sessions.ixnetwork.vport.vport import (
        Vport as IxnVport,
    )
    from uhd_restpy.testplatform.sessions.ixnetwork.vport.vport import Vport as UhdVport
    Vport = t.Union[IxnVport, UhdVport]
    from ixnetwork_restpy.testplatform.sessions.ixnetwork.topology.topology_9d0fe0bb2c064aa7010adbdb6cf68958 import (
        Topology as IxnTopology,
    )
    from uhd_restpy.testplatform.sessions.ixnetwork.topology.topology_9d0fe0bb2c064aa7010adbdb6cf68958 import (
        Topology as UhdTopology,
    )
    Topology = t.Union[IxnTopology, UhdTopology]
    from ixnetwork_restpy.testplatform.sessions.ixnetwork.topology.devicegroup_fe4647b311377ec16edf5dcfe93dca09 import (
        DeviceGroup as IxnDeviceGroup,
    )
    from uhd_restpy.testplatform.sessions.ixnetwork.topology.devicegroup_fe4647b311377ec16edf5dcfe93dca09 import (
        DeviceGroup as UhdDeviceGroup,
    )
    DeviceGroup = t.Union[IxnDeviceGroup, UhdDeviceGroup]
    from ixnetwork_restpy.testplatform.sessions.ixnetwork.topology.ethernet_18677f1f170027c217563a3250b1f635 import (
        Ethernet as IxnEthernet,
    )
    from uhd_restpy.testplatform.sessions.ixnetwork.topology.ethernet_18677f1f170027c217563a3250b1f635 import (
        Ethernet as UhdEthernet,
    )
    Ethernet = t.Union[IxnEthernet, UhdEthernet]
    from ixnetwork_restpy.testplatform.sessions.ixnetwork.topology.ipv4_8cb960b62ae85a03e1b40a57bfaeb7bb import (
        Ipv4 as IxnIpv4,
    )
    from uhd_restpy.testplatform.sessions.ixnetwork.topology.ipv4_8cb960b62ae85a03e1b40a57bfaeb7bb import (
        Ipv4 as UhdIpv4,
    )
    Ipv4 = t.Union[IxnIpv4, UhdIpv4]
    from ixnetwork_restpy.testplatform.sessions.ixnetwork.topology.ipv6_b40789fa49420009901a46b8dc683afc import (
        Ipv6 as IxnIpv6,
    )
    from uhd_restpy.testplatform.sessions.ixnetwork.topology.ipv6_abda0a2a4cac3d529994b093916059a4 import (
        Ipv6 as UhdIpv6,
    )
    Ipv6 = t.Union[IxnIpv6, UhdIpv6]
    from ixnetwork_restpy.testplatform.sessions.ixnetwork.topology.bgpipv4peer_6f0423477064be24e0493341e399bee9 import (
        BgpIpv4Peer as IxnBgpIpv4Peer,
    )
    from uhd_restpy.testplatform.sessions.ixnetwork.topology.bgpipv4peer_9dd9eddcf2bd784d82d8a016e392f035 import (
        BgpIpv4Peer as UhdBgpIpv4Peer,
    )
    BgpIpv4Peer = t.Union[IxnBgpIpv4Peer, UhdBgpIpv4Peer]
    from ixnetwork_restpy.testplatform.sessions.ixnetwork.topology.bgpiprouteproperty_3dbf4edca5d6573869a4ee79cda6644b import (
        BgpIPRouteProperty as IxnBgpIPRouteProperty,
    )
    from uhd_restpy.testplatform.sessions.ixnetwork.topology.bgpiprouteproperty_ffd9071ae88c6283e9f54ec948882405 import (
        BgpIPRouteProperty as UhdBgpIPRouteProperty,
    )
    BgpIPRouteProperty = t.Union[IxnBgpIPRouteProperty, UhdBgpIPRouteProperty]
    from ixnetwork_restpy.testplatform.sessions.ixnetwork.topology.bgpv6iprouteproperty_a52cfd647078952e2675a9fcb67c5b8c import (
        BgpV6IPRouteProperty as IxnBgpV6IPRouteProperty,
    )
    from uhd_restpy.testplatform.sessions.ixnetwork.topology.bgpv6iprouteproperty_3bc5aff598784532c6b5ff0b601d2985 import (
        BgpV6IPRouteProperty as UhdBgpV6IPRouteProperty,
    )
    BgpV6IPRouteProperty = t.Union[IxnBgpV6IPRouteProperty, UhdBgpV6IPRouteProperty]
    from ixnetwork_restpy.testplatform.sessions.ixnetwork.topology.networkgroup_4a63874e791827c3a0361c2d201dbc0c import (
        NetworkGroup as IxnNetworkGroup,
    )
    from uhd_restpy.testplatform.sessions.ixnetwork.topology.networkgroup_4a63874e791827c3a0361c2d201dbc0c import (
        NetworkGroup as UhdNetworkGroup,
    )
    NetworkGroup = t.Union[IxnNetworkGroup, UhdNetworkGroup]
    from ixnetwork_restpy.testplatform.sessions.ixnetwork.traffic.trafficitem.trafficitem import (
        TrafficItem as IxnTrafficItem,
    )
    from uhd_restpy.testplatform.sessions.ixnetwork.traffic.trafficitem.trafficitem import (
        TrafficItem as UhdTrafficItem,
    )
    IxiaTrafficItem = t.Union[IxnTrafficItem, UhdTrafficItem]
    from ixnetwork_restpy.testplatform.sessions.ixnetwork.traffic.trafficitem.configelement.configelement import (
        ConfigElement as IxnConfigElement,
    )
    from uhd_restpy.testplatform.sessions.ixnetwork.traffic.trafficitem.configelement.configelement import (
        ConfigElement as UhdConfigElement,
    )
    ConfigElement = t.Union[IxnConfigElement, UhdConfigElement]
    from ixnetwork_restpy.testplatform.sessions.ixnetwork.traffic.trafficitem.tracking.tracking import (
        Tracking as IxnTracking,
    )
    from uhd_restpy.testplatform.sessions.ixnetwork.traffic.trafficitem.tracking.tracking import (
        Tracking as UhdTracking,
    )
    Tracking = t.Union[IxnTracking, UhdTracking]
    from ixnetwork_restpy.testplatform.sessions.ixnetwork.traffic.trafficitem.configelement.stack.stack import (
        Stack as IxnStack,
    )
    from uhd_restpy.testplatform.sessions.ixnetwork.traffic.trafficitem.configelement.stack.stack import (
        Stack as UhdStack,
    )
    Stack = t.Union[IxnStack, UhdStack]
    from ixnetwork_restpy.testplatform.sessions.ixnetwork.traffic.trafficitem.configelement.stack.field.field import (
        Field as IxnField,
    )
    from uhd_restpy.testplatform.sessions.ixnetwork.traffic.trafficitem.configelement.stack.field.field import (
        Field as UhdField,
    )
    Field = t.Union[IxnField, UhdField]
    from ixnetwork_restpy.testplatform.sessions.ixnetwork.traffic.protocoltemplate.protocoltemplate import (
        ProtocolTemplate as IxnProtocolTemplate,
    )
    from ixnetwork_restpy.testplatform.sessions.ixnetwork.vport.l1config.ethernet.fcoe.fcoe import (
        Fcoe,
    )
    from uhd_restpy.testplatform.sessions.ixnetwork.traffic.protocoltemplate.protocoltemplate import (
        ProtocolTemplate as UhdProtocolTemplate,
    )
    ProtocolTemplate = t.Union[IxnProtocolTemplate, UhdProtocolTemplate]
    SessionAssistant = t.Union[IxnSessionAssistant, UhdSessionAssistant]
    StatViewAssistant = t.Union[IxnStatViewAssistant, UhdStatViewAssistant]

    # fmt: on


class AsPathValuesNotFoundError(Exception):
    pass


class BgpAsPathSegmentListNotFoundError(Exception):
    pass


class BgpCommunitiesListNotFoundError(Exception):
    pass


class BgpIPRoutePropertyNotFoundError(Exception):
    pass


class DeviceGroupNotFoundError(Exception):
    pass


class FetchIxiaApiKeyFailedError(Exception):
    pass


class IpPrefixPoolsNotFoundError(Exception):
    pass


class InvalidDSCPValueError(Exception):
    pass


class InvalidInputError(Exception):
    pass


class IxiaSetupError(Exception):
    pass


class NetworkGroupNotFoundError(Exception):
    pass


class TopologyNotFoundError(Exception):
    pass


class DangerousIxiaIPAdvertiseError(Exception):
    pass


class TrafficItemNotFoundError(Exception):
    pass


def get_logger() -> logging.Logger:
    LOGGING_FMT = "%(asctime)s [%(levelname)-8s] %(message)s"
    logging.basicConfig(
        level=logging.DEBUG, format=LOGGING_FMT, datefmt="%Y-%m-%d %H:%M:%S"
    )
    # Used to suppress the logging messages from the REQUESTS library
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logger = logging.getLogger("IXIA_LIBRARY")
    return logger


# ANSI color constants for colored IXIA setup logging
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_MAGENTA = "\033[35m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RESET = "\033[0m"
_BG_BLUE = "\033[44m"
_WHITE = "\033[97m"

IpAddressResult = namedtuple("IpAddressResult", ["ipv4", "ipv6"])

# IXIA REST API expects string enum for extended community sub-type, not integer
_SUBTYPE_MAP = {
    2: "routetarget",
    3: "origin",
    4: "extendedbandwidth",
    11: "color",
    12: "encapsulation",
    1978: "macaddress",
}


@dataclass
class NetworkGroupIndex:
    network_group: "NetworkGroup"
    bgp_ip_route: t.Optional["BgpIPRouteProperty"] = None
    ipv4_bgp_peer: t.Optional["BgpIpv6Peer"] = None
    ipv6_bgp_peer: t.Optional["BgpIpv6Peer"] = None


@dataclass
class DeviceGroupIndex:
    device_group: "DeviceGroup"
    network_group_indices: t.Dict[int, NetworkGroupIndex] = field(default_factory=dict)
    ipv4: t.Optional["Ipv4"] = None
    ipv6: t.Optional["Ipv6"] = None
    ethernet: t.Optional["Ethernet"] = None


@dataclass
class VportIndex:
    name: str
    device_group_indices: t.Dict[int, DeviceGroupIndex] = field(default_factory=dict)
    topology_name: t.Optional[str] = None


def require_traffic_item(func: t.Callable) -> t.Callable:
    """Decorator to skip the function execution if no traffic items are found"""

    def wrapper(self, *args, **kwargs) -> t.Any:
        if not self.has_traffic_items():
            self.logger.debug(
                f"[GLOBAL] No traffic items found in the IXIA setup! Skipping {func.__name__}."
            )
            return
        return func(self, *args, **kwargs)

    return wrapper


def external_api(func: t.Callable) -> t.Callable:
    def wrapper(self, *args, **kwargs) -> t.Any:
        return func(self, *args, **kwargs)

    return wrapper


def split_list_into_chunks(list_to_split: list, chunk_size: int) -> t.List[list]:
    return [
        list_to_split[i : i + chunk_size]
        for i in range(0, len(list_to_split), chunk_size)
    ]


def _ixia_value_equals(current: t.Any, desired: t.Any) -> bool:
    """Type-coerce-safe comparison of an IxNetwork Multivalue read vs a desired write.

    IxNetwork returns Multivalue `.Values[i]` as strings regardless of the
    semantic Python type — `True` round-trips as `"true"`, `60` as `"60"`,
    etc. A naive `==` between the string read and the bool/int desired
    value always returns False, which would silently disable any skip-if-
    converged optimization. This helper normalizes both sides before comparing.

    Returns True if `current` is semantically equal to `desired` after type
    coercion; False otherwise (including on coercion errors — when in doubt,
    return False so the caller falls through to a write).
    """
    if isinstance(desired, bool):
        return str(current).strip().lower() == str(desired).lower()
    if isinstance(desired, int):
        try:
            return int(current) == desired
        except (TypeError, ValueError):
            return False
    if isinstance(desired, float):
        try:
            return float(current) == desired
        except (TypeError, ValueError):
            return False
    return str(current) == str(desired)


def _set_multivalue_if_changed(multivalue: t.Any, desired: t.Any) -> bool:
    """Set an IxNetwork Multivalue to `desired` only if its current value differs.

    Reads `multivalue.Values[0]` first, compares against `desired` via
    `_ixia_value_equals`. If unchanged, skip the write and return False.
    Otherwise issue `multivalue.Single(value=desired)` and return True.

    On ANY exception during the Values read (multivalue in a non-Single
    pattern, network blip, missing attribute), falls through to the write
    — the safe default is "write" because correctness > optimization.

    Used by Pain #1 Lever E paths in `configure_bgp_peers_flap` and
    elsewhere. Backward-compatible: any caller that currently does
    `mv.Single(value=X)` can swap in `_set_multivalue_if_changed(mv, X)`
    without changing observable behavior except for skipping no-op writes.
    """
    try:
        current_values = multivalue.Values
        if current_values and _ixia_value_equals(current_values[0], desired):
            return False  # already converged, no PATCH issued
    except Exception:
        # Conservative fallback — when the read path is unreliable, prefer
        # the write. This guarantees `_set_multivalue_if_changed(X, Y)` is
        # never a worse choice than the unconditional `Single(value=Y)`.
        pass
    multivalue.Single(value=desired)
    return True


class Ixia:
    def __init__(
        self,
        ixia_config: t.Optional[ixia_types.IxiaConfig] = None,
        logger: t.Optional[logging.Logger] = None,
        session_id: t.Optional[int] = None,  # For linux based API servers only
        session_name: t.Optional[str] = None,
        chassis_ip: t.Optional[str] = None,
        cleanup_config: bool = True,
        teardown_session: bool = True,  # For linux based API servers only
        force_take_port_ownership: bool = False,  # Use with CAUTION!!
        override_traffic_items: bool = False,
        cleanup_failed_setup: bool = True,
        skip_advertised_prefixes_check: bool = False,
        skip_ixia_protocol_verification: bool = False,
        ixia_protocol_verification_timeout: int = 90,
        api_key: t.Optional[str] = None,
        password: t.Optional[str] = API_SERVER_PASSWORD,
        username: t.Optional[str] = API_SERVER_USERNAME,
        ixia_recovery: t.Optional[t.Any] = None,
    ) -> None:
        """Instantiates the object of class Ixia

        Args:
            ixia_configs: Thrift object for feeding the metadata of
                the IXIA configuration

            logger: t.Optional arg. If no logger is provided, the library
                will use its own (DEBUG level)

            session_id: If provided by the user, the tool will search for an
                existing Session with that ID. Else a new one will be
                created on the fly

                NOTE: In case of Windows based API server, there is
                ONLY ONE session. Windows will always default to using
                Session ID 1.
                However, in Linux API Server (standalone|embedded),
                there is multi-session support.

            session_name: Applicable ONLY for Linux based servers that support
                multiple concurrent sessions. If provided by the user,
                tool will search for an existing session with that session
                name. Else, a new one will be created

            cleanup_config: If set to True, this will clean up the existing
                config on the current session and proceed with
                a clean template. If set to False, the pre-created
                IXIA configuration will be reused for that session.

            teardown_session: This applies only for Linux based server that
                can support multiple concurrent session and when we want
                to tear down the current session.

                If set to True, the current session will be completely
                torn down and the socket resources will be released back
                to the server. Else, the session will still be intact even
                after the script execution is complete.

                NOTE: Even though Linux based servers can support upto
                10 concurrent sessions (depending on the hardware resources),
                it is still HIGHLY RECOMMMENDED TO TEAR DOWN THE SESSION
                after usage by setting this flag to True.

                Performance differnce:
                - Time take to create a new session on a Linux Server is
                    approximately 30 seconds
                - If you are reusing an existing session (by referencing
                    an existing session ID and name), then it should take
                    under 10 seconds
                - Session tear down DOES NOT apply to Windows based server
                    as the session is always open!

            force_take_port_ownership: If enabled, will forcibly grab the
                ownership of the IXIA ports if it is currently in a
                'reserved' status.

                NOTE: USE WITH CAUTION!! Because if the port the session is
                trying to reserve is currently owned and worse, if used by
                another engineer or testing tool, then we will force grab it
                and it might not be desired. That is why it is set to False
                by default. In which case, if the port the tool is trying
                to grab an already reserved port it will automatically
                timeout after 600 seconds :)

            api_key: IXIA supports logging in to traffic generator using API keys.
                When provided, this key will be used for authentication
                overring username and password.

            password: Provide a password to log in to Ixia chassis. When not provided,
                the default password will be used for logging in.
            username: Provide a username to log in to Ixia chassis. When not provided,
                the default username will be used for logging in.
        """

        self.logger = logger if logger else get_logger()

        if not (ixia_config or session_id):
            raise InvalidInputError("Either ixia_config or session_id is required")

        self.ixia_config = ixia_config
        self.primary_chassis_ip = (
            self.ixia_config.api_server_ip if self.ixia_config else chassis_ip
        )

        if session_id and not self.primary_chassis_ip:
            raise InvalidInputError("chassis_ip is required when using session_id")

        self.session: SessionAssistant = None  # pyre-ignore[8]
        self.ixnetwork: Ixnetwork = None  # pyre-ignore[8]
        # Applicable only for IXIA sessions with Linux API server that support
        # concurrent sessions unlike Windows API server with only session (ID=1)
        self.session_name = session_name
        self.session_id = session_id

        # By default, we will NOT let the automation to grab IXIA ports
        # that is already reserved
        self.force_take_port_ownership: bool = force_take_port_ownership
        self.cleanup_config: bool = cleanup_config
        self.teardown_session: bool = teardown_session

        self.ApiKey: t.Optional[str] = api_key
        self.password = password
        self.username = username
        # if port_configs is an empty list, session id of an existing session has been provided
        self.is_existing_session = bool(self.session_id)
        self.override_traffic_items = override_traffic_items

        # Variable to keep chassis type
        # If True chassis is UHD type that requires usage of udh_restpy module
        # We can detect if chassis is UHD if chassis_ip is set to "localuhd"
        self.is_uhd_chassis = self.primary_chassis_ip == "localuhd"
        self.cleanup_failed_setup = cleanup_failed_setup
        self.skip_advertised_prefixes_check = skip_advertised_prefixes_check
        self.skip_ixia_protocol_verification = skip_ixia_protocol_verification
        self.ixia_protocol_verification_timeout = ixia_protocol_verification_timeout
        # Python-side index of vport metadata, populated ONLY by
        # `assign_ports()` (gated by `is_existing_session` — see
        # `create_basic_setup`). On IXIA topology-cache HIT (Tier 1
        # LoadConfig / Tier 2 Manifold via `taac_ixia.load_config_from_chassis`
        # or `ixia_config_cache_manager.try_load_from_manifold`) the server-
        # side vports are restored but this dict stays empty. Any TAAC step,
        # health check, or helper that reads `vport_indices` (e.g.
        # `register_cpu_queue_static_route_patcher`) will KeyError on cache
        # hit — the owning TestConfig MUST opt out of the cache via
        # `ixia_config_cache=taac_types.IxiaConfigCache(enabled=False)`
        # until the cache layer learns to rehydrate this dict.
        self.vport_indices: t.Dict[str, VportIndex] = {}
        self.traffic_items_start_time: float = 0.0
        self.cfgr_client = ConfigeratorClient()
        self.ptp_configured: bool = False
        self.tag_name_to_device_group_name_list = defaultdict(list)
        self._capture_stopped: bool = (
            False  # Track if we've already stopped packet capture
        )
        # Opt-in IXIA REST API tier soft recovery on 5xx during connect().
        # Type-annotated as Any because the Thrift type cannot be imported
        # from this OSS-shared module. The real type is
        # `taac.test_as_a_config.types.IxiaRecovery`.
        #
        # NOTE on `max_attempts`: the per-call retry loop here is structured
        # to allow exactly ONE in-band recovery attempt per `connect()`
        # invocation regardless of the configured `max_attempts`. Multi-shot
        # in-band retry is intentionally NOT implemented because the outer
        # `@retryable(num_tries=3)` on `_create_basic_setup` already
        # re-enters `connect()` up to 3 times, and the budget is reset on
        # each entry (see the reset block at the top of
        # `_create_basic_setup`). The `max_attempts` field is reserved for a
        # future loop refactor; for now `_DEFAULT_IXIA_RECOVERY.max_attempts`
        # is 1 and any larger value will be silently capped at 1 per
        # `connect()` invocation.
        self.ixia_recovery: t.Optional[t.Any] = ixia_recovery
        # Tracks remaining recovery attempts inside this `_create_basic_setup`
        # invocation. Reset by `_create_basic_setup` before each retry round.
        self._ixia_recovery_attempts_remaining: int = (
            ixia_recovery.max_attempts if ixia_recovery else 1
        )

    @staticmethod
    def get_formatted_ip_address(ixia_server_ip: str) -> str:
        """API to get the formatted IP address

        Temporary fix to the IXIA APIs bug wherein they don't add the
        escape characters '[' & ']' around the IPv6 addresses while
        creating the REST URLs. No change for the IPv4 addresses.

        Args:
            ixia_server_ip: IPv6 defined as a string.

        Returns:
            A string of IPv6 with added escape characters, else the IPv4
            address as it is.
        """

        try:
            # Adding escape characters if it is an IPv6 address
            return (
                f"[{ixia_server_ip}]"
                if isinstance(ip_address(ixia_server_ip), IPv6Address)
                else ixia_server_ip
            )

        except ValueError:
            raise InvalidInputError(
                f"Invalid IXIA API Server IP address {ixia_server_ip}. Please check!"
            )

    @staticmethod
    def get_port_identifier(port_name: str) -> str:
        """API to get the port identifier

        Gets the appropriate port identifier name.

        Args:
            port_name: Given port name as a string.

        Returns:
            A string with the appropriate port name.
        """

        if port_name.isdigit():
            return f"PORT_{port_name}"
        else:
            # Normalize hostname part to UQDN to ensure consistent keys
            # regardless of whether FQDN or UQDN is provided.
            if ":" in port_name:
                hostname, interface = port_name.split(":", 1)
                port_name = f"{to_fb_uqdn(hostname)}:{interface}"
            return port_name.upper()

    def connect(self) -> None:
        """API to connect to an Ixia session

        Search for an existing session with the respective Session ID and/or
        Name first. If found, then that SessionAssistant object is returned.
        Else, a new session will be created for this automation run.

        NOTE:
        - If the API server is a WINDOWS based, then there is only one
        Session that can be used and it is always up and running (even if
        we try to kill it)

        - Else if it is LINUX based, then it can support multiple connections
        (upto 10 depending on the Server resources). In which case, each
        new/existing session gets it own Session ID and Session Name.
        """

        self.logger.info(
            f"{_CYAN}{_BOLD}[IXIA]{_RESET} Connecting to chassis "
            f"{_YELLOW}{self.primary_chassis_ip}{_RESET} "
            f"(session_id={self.session_id or 'new'}, "
            f"session_name={self.session_name or 'auto'})"
        )
        if self.cleanup_config and not self.is_existing_session:
            self.logger.info(
                f"{_CYAN}[IXIA]{_RESET} {_DIM}Cleaning up existing config — "
                f"starting fresh{_RESET}"
            )
        SessionAssistant = (
            UhdSessionAssistant if self.is_uhd_chassis else IxnSessionAssistant
        )
        try:
            self.session = SessionAssistant(
                # pyrefly: ignore [bad-argument-type]
                IpAddress=Ixia.get_formatted_ip_address(self.primary_chassis_ip),
                RestPort=None,
                UserName=self.username,
                Password=self.password,
                SessionName=self.session_name,
                SessionId=self.session_id,
                ApiKey=self.ApiKey,
                ClearConfig=(
                    self.cleanup_config if not self.is_existing_session else False
                ),
            )
        except Exception as exc:
            if not self._should_attempt_recovery(exc):
                raise
            self._ixia_recovery_attempts_remaining -= 1
            self.logger.warning(
                f"{_YELLOW}[IXIA]{_RESET} SessionAssistant failed with 5xx — "
                f"attempting in-band recovery: {type(exc).__name__}: {exc!r}"
            )
            recovered = self._attempt_inband_recovery()
            if not recovered:
                raise
            self.logger.info(
                f"{_GREEN}[IXIA]{_RESET} Recovery succeeded — retrying SessionAssistant"
            )
            self.session = SessionAssistant(
                # pyrefly: ignore [bad-argument-type]
                IpAddress=Ixia.get_formatted_ip_address(self.primary_chassis_ip),
                RestPort=None,
                UserName=self.username,
                Password=self.password,
                SessionName=self.session_name,
                SessionId=self.session_id,
                ApiKey=self.ApiKey,
                ClearConfig=(
                    self.cleanup_config if not self.is_existing_session else False
                ),
            )

        # Re-populating the Session ID and Name if a new one was created
        # as the user left them to default input as None
        was_new_session = not self.session_id
        if not self.session_id:
            self.session_id = self.session.Session.Id
        if not self.session_name:
            self.session_name = self.session.Session.Name

        action = "Created new" if was_new_session else "Reusing existing"
        self.logger.info(
            f"{_GREEN}{_BOLD}[IXIA]{_RESET} {action} session — "
            f"ID: {_YELLOW}{self.session_id}{_RESET}, "
            f"Name: {_YELLOW}{self.session_name}{_RESET}"
        )

        self.ixnetwork = self.session.Ixnetwork

    _RECOVERY_TRIGGER_TOKENS: t.Tuple[str, ...] = ("502", "503", "504")

    def _should_attempt_recovery(self, exc: BaseException) -> bool:
        """Decide whether to invoke `ixia_recovery_lib.restart_ixnetwork`.

        Returns True only when ALL hold:
        - The TestConfig opted in (or omitted opt-out — see
          `_DEFAULT_IXIA_RECOVERY` in `libs/test_setup_orchestrator.py`).
        - `_ixia_recovery_attempts_remaining > 0` for this `connect()` round.
        - The exception's stringified message contains a 5xx token (502/503/
          504). We grep the message because `ixnetwork-restpy` wraps the
          underlying `HTTPError` and the wrapper type does not preserve the
          status code as an attribute we can read.
        """
        if self.ixia_recovery is None or not getattr(
            self.ixia_recovery, "enabled", False
        ):
            return False
        if self._ixia_recovery_attempts_remaining <= 0:
            return False
        msg = f"{type(exc).__name__}: {exc!s}"
        return any(token in msg for token in self._RECOVERY_TRIGGER_TOKENS)

    def _attempt_inband_recovery(self) -> bool:
        """Best-effort soft restart of `ixnetworkweb` via `ixia_recovery_lib`.

        Returns True iff the lib reports success AND `/api/v1/sessions`
        returned 200 within the poll window. Any exception inside the lib
        is logged and treated as a recovery failure.
        """
        # OSS guard: `ixia_recovery_lib` is internal-only (the surrounding
        # file is OSS-shared). Skip in OSS builds without even attempting
        # the import, matching the convention used by `fetch_ixia_credentials`
        # elsewhere in this module. See `.llms/skills/taac_oss_privacy_rules.md`.
        if TAAC_OSS:
            return False
        # Lazy import: keeps the dep chain off the hot connect path and
        # prevents a circular import.
        try:
            from taac.internal.utils.ixia_recovery_lib import (
                restart_ixnetwork,
            )
        except ImportError as ie:
            self.logger.warning(
                f"{_YELLOW}[IXIA]{_RESET} ixia_recovery_lib not importable "
                f"({ie!r}) — skipping in-band recovery"
            )
            return False
        cooldown = getattr(self.ixia_recovery, "cooldown_minutes", 30)
        try:
            result = restart_ixnetwork(
                chassis_hostname=str(self.primary_chassis_ip),
                username=str(self.username),
                password=self.password,
                cooldown_minutes=int(cooldown),
                triggered_by="phase2_inband",
            )
        except Exception as e:
            self.logger.warning(
                f"{_YELLOW}[IXIA]{_RESET} in-band recovery raised "
                f"unexpectedly: {type(e).__name__}: {e!r}"
            )
            return False
        if not result.get("success"):
            self.logger.warning(
                f"{_YELLOW}[IXIA]{_RESET} in-band recovery refused/failed: "
                f"blocked_reason={result.get('blocked_reason')!r}"
            )
            return False
        return True

    def assign_ports(self, port_configs: t.Sequence[ixia_types.PortConfig]) -> None:
        """API to assign ports to the IXIA setup by creating new vport instances

        For the given list of port configs, it reserves the physical ports
        and creates the vport instances by forcefully taking ownership of
        ports.

        Args:
            port_configs: t.List of type PortConfig containing port config
                details.

        WARNING — Cache caveat:
            This method is the ONLY producer of `self.vport_indices`. It is
            skipped by `create_basic_setup` when `is_existing_session=True`,
            which is the state after an IXIA topology-cache HIT
            (`taac_ixia.load_config_from_chassis` /
            `ixia_config_cache_manager.try_load_from_manifold`). On cache
            hit the server-side vports are restored but `vport_indices`
            stays empty — any downstream API that traverses through
            `vport_indices` will KeyError. TestConfigs that use such APIs
            (e.g. `register_cpu_queue_static_route_patcher`) MUST opt out
            of the cache via
            `ixia_config_cache=taac_types.IxiaConfigCache(enabled=False)`.
        """

        portmap_obj = self.session.PortMapAssistant()

        start_time = time.time()
        for port_config in port_configs:
            port_identifier: str = self.get_port_identifier(port_config.port_name)
            desired_vport_name: str = DESIRED_VPORT_NAME.format(
                port_identifier=port_identifier
            )
            self.vport_indices[port_identifier] = VportIndex(name=desired_vport_name)
            chassis_ip: str = port_config.phy_port_config.chassis_ip
            slot_num: int = port_config.phy_port_config.slot_number
            port_num: int = port_config.phy_port_config.port_number
            if self.is_uhd_chassis:
                # For UHD chassis Map should be created with location
                # in format "localuhd/1" where 1 is port number
                portmap_obj.Map(
                    Location=f"{chassis_ip}/{port_num}",
                    Name=desired_vport_name,
                )
                # Port mode needs to be defined and set as "measure"
                vport = self.ixnetwork.Vport.find(Name=desired_vport_name)
                vport.RxMode = "measure"
            else:
                portmap_obj.Map(
                    IpAddress=chassis_ip,
                    CardId=slot_num,
                    PortId=port_num,
                    Name=desired_vport_name,
                )
            self.logger.info(
                f"{_CYAN}[IXIA]{_RESET}   Port {_YELLOW}{port_identifier}{_RESET} "
                f"-> vport {_DIM}{desired_vport_name}{_RESET} "
                f"({chassis_ip} {slot_num}/{port_num})"
            )
        self.logger.info(
            f"{_CYAN}[IXIA]{_RESET} Connecting {len(port_configs)} port(s)... "
            f"{_DIM}(force_ownership={self.force_take_port_ownership}){_RESET}"
        )
        try:
            portmap_obj.Connect(ForceOwnership=self.force_take_port_ownership)
        except Exception as connect_ex:
            # Log per-port link state to identify which port(s) failed
            self.logger.error(
                f"{_MAGENTA}[IXIA]{_RESET} Port connect failed, checking per-port link state..."
            )
            try:
                for vport in self.ixnetwork.Vport.find():
                    self.logger.error(
                        f"{_MAGENTA}[IXIA]{_RESET}   vport={vport.Name} "
                        f"type={vport.Type} "
                        f"state={vport.State} "
                        f"connection_state={vport.ConnectionState} "
                        f"assigned_to={vport.AssignedTo}"
                    )
            except Exception as log_ex:
                self.logger.error(
                    f"{_MAGENTA}[IXIA]{_RESET}   Failed to query vport states: {log_ex}"
                )
            raise connect_ex
        elapsed_time = time.time() - start_time
        self.logger.info(
            f"{_GREEN}{_BOLD}[IXIA]{_RESET} All ports reserved in "
            f"{_YELLOW}{elapsed_time:.1f}s{_RESET}"
        )

    def create_topology(self, port_identifier: str, vport: "Vport") -> "Topology":
        """
        This API checks for the presence of a topology for a given
        vport instance. If found, that's returned else a new topology
        is added for the given vport instance.

        Args:
            port_identifier: Device name associated with the ixia port.
                For e.g., "rsw001.p004.f03.snc1" or
                "ixia01.netcastle.snc1.facebook.com_2_5" if ixia back to back
                port connection is used.
            vport: An object of type Vport used to create for the topology
                in the ixia session.

        Returns:
            An object of type Topology either that's already present
            or the newly created one.
        """

        desired_topo_name: str = DESIRED_TOPOLOGY_NAME.format(
            port_identifier=port_identifier
        )
        topology: "Topology" = self.ixnetwork.Topology.find(Name=desired_topo_name)
        if topology:
            self.logger.info(
                f"{_CYAN}[IXIA]{_RESET}   Topology "
                f"{_MAGENTA}{desired_topo_name}{_RESET} "
                f"{_DIM}(reusing existing){_RESET}"
            )
            return topology

        topology: "Topology" = self.ixnetwork.Topology.add(
            Name=desired_topo_name, Ports=vport
        )
        self.logger.info(
            f"{_GREEN}[IXIA]{_RESET}   Topology "
            f"{_MAGENTA}{desired_topo_name}{_RESET} {_GREEN}created{_RESET}"
        )
        return topology

    def create_device_group(
        self,
        port_identifier: str,
        device_multiplier: int,
        topology: "Topology",
        enable: bool = True,
        device_group_name: t.Optional[str] = None,
        parent_device_group: t.Optional["DeviceGroup"] = None,
    ) -> "DeviceGroup":
        """
        This API checks for the presence of a device group for the
        given port identifier, device multiplier and topology. If found,
        we return that else we create a new device group.

        Args:
            port_identifier: Device name associated with the ixia port.
                For e.g., "rsw001.p004.f03.snc1" or
                "ixia01.netcastle.snc1.facebook.com_2_5" if ixia back to
                back port connection is used.
            device_multiplier: An integer value used to tell how many
                device groups are associated with the given topology
                and port identifier.
            topology: An object instance of type Topology associated with
                the port identifier.
            parent_device_group: Optional parent DeviceGroup for creating
                chained (nested) device groups. When provided, the new DG
                is created under this parent instead of under the topology.

        Returns:
            An object of type DeviceGroup either that's already present
            or the newly created one.
        """

        desired_dev_grp_name: str = DESIRED_DEVICE_GROUP_NAME.format(
            port_identifier=port_identifier
        )
        # Use parent DG's DeviceGroup accessor for chained DGs, otherwise
        # use the topology's DeviceGroup accessor.
        dg_container = parent_device_group if parent_device_group else topology
        device_group: "DeviceGroup" = dg_container.DeviceGroup.find(
            Name=desired_dev_grp_name, Multiplier=device_multiplier
        )

        if device_group:
            self.logger.info(
                f"{_CYAN}[IXIA]{_RESET}     DeviceGroup "
                f"{_YELLOW}{desired_dev_grp_name}{_RESET} "
                f"(x{device_multiplier}) "
                f"{_DIM}(reusing existing){_RESET}"
            )
            return device_group

        dg_display_name = device_group_name or desired_dev_grp_name
        device_group: "DeviceGroup" = dg_container.DeviceGroup.add(
            Name=dg_display_name, Multiplier=device_multiplier
        )
        # Enable/Disable the device_group
        device_group.Enabled.Single(enable)
        enabled_str = (
            f"{_GREEN}enabled{_RESET}" if enable else f"{_DIM}disabled{_RESET}"
        )
        chained_str = f" {_DIM}(chained){_RESET}" if parent_device_group else ""
        self.logger.info(
            f"{_GREEN}[IXIA]{_RESET}     DeviceGroup "
            f"{_YELLOW}{dg_display_name}{_RESET} "
            f"(x{device_multiplier}) [{enabled_str}]{chained_str}"
        )
        return device_group

    def create_ethernet_group(
        self, port_identifier: str, device_group: "DeviceGroup"
    ) -> "Ethernet":
        """
        This API checks for the presence of an ethernet group for the
        given port identifier and device group. If found, we return that
        else we create a new ethernet group.

        Args:
            port_identifier: Device name associated with the ixia port.
                For e.g., "rsw001.p004.f03.snc1" or
                "ixia01.netcastle.snc1.facebook.com_2_5" if ixia back to
                back port connection is used.
            device_group: An object instance of type DeviceGroup associated
                with the given port identifier.

        Returns:
            An object of type Ethernet either that's already present
            or the newly created one.
        """

        desired_ethernet_name: str = DESIRED_ETHERNET_NAME.format(
            port_identifier=port_identifier
        )
        ethernet: "Ethernet" = device_group.Ethernet.find(Name=desired_ethernet_name)

        if ethernet:
            self.logger.info(
                f"[{port_identifier}] There is already an existing ethernet "
                f"stack instance {desired_ethernet_name}. Hence not creating "
                "a new one!"
            )
            return ethernet

        ethernet: "Ethernet" = device_group.Ethernet.add(Name=desired_ethernet_name)
        self.logger.info(
            f"[{port_identifier}] Successfully created a new ethernet protocol "
            f"stack {desired_ethernet_name}"
        )
        return ethernet

    def find_device_group(self, port_identifier: str) -> "DeviceGroup":
        """Finds the DeviceGroup for a given port identifier in a topology.

        This helps to find the topology with the given port_identifier. After
        that, it finds the device group present in that topology.

        Args:
            port_identifier: Device name associated with the ixia port.
                For e.g., "rsw001.p004.f03.snc1" or
                "ixia01.netcastle.snc1.facebook.com_2_5" if ixia back to
                back port connection is used.

        Returns:
            device_group: An object of type DeviceGroup.
        """

        # Find the Topology object
        topology_name: str = DESIRED_TOPOLOGY_NAME.format(
            port_identifier=port_identifier.upper()
        )
        topology: "Topology" = self.ixnetwork.Topology.find(Name=topology_name)
        if not topology:
            raise TopologyNotFoundError(
                f"Topology not found for the given port_identifier '{port_identifier}'"
            )

        # Find the Device Group object from Topology object
        device_group_name: str = DESIRED_DEVICE_GROUP_NAME.format(
            port_identifier=port_identifier.upper()
        )
        device_group: "DeviceGroup" = topology.DeviceGroup.find(Name=device_group_name)
        if not device_group:
            raise DeviceGroupNotFoundError(
                f"Device group not found for the given port_identifier '{port_identifier}' "
                f"and topology '{topology_name}'"
            )

        return device_group

    def assign_ipv4_address(
        self,
        port_identifier: str,
        ipv4_addr_info: ixia_types.IPv4AddressInfo,
        ethernet: "Ethernet",
        device_group_index: t.Optional[DeviceGroupIndex] = None,
        start_index: t.Optional[int] = None,
    ) -> "Ipv4":
        """
        This checks for the presence of an IPv4 protocol stack for
        a given ethernet group and port identifier. If found, we return
        that else we create a new IPv4 protocol stack and assign the IPv4
        address information for a given port identifier, IPv4 address
        information and ethernet group.

        Args:
            port_identifier: Device name associated with the ixia port.
                For e.g., "rsw001.p004.f03.snc1" or
                "ixia01.netcastle.snc1.facebook.com_2_5" if ixia back to
                back port connection is used.
            ipv4_addr_info: An object of type IPv4AddressInfo containing
                details pertaining to IPv4 address.
            ethernet: An object of type Ethernet associated with the given
                port identifier.

        Returns:
            An object of type Ipv4.
        """

        desired_ipv4_name: str = DESIRED_IPV4_NAME.format(
            port_identifier=port_identifier
        )

        ipv4_addr: "Ipv4" = ethernet.Ipv4.find(Name=desired_ipv4_name)

        if ipv4_addr:
            self.logger.info(
                f"[{port_identifier}] There is already an existing IPv4 "
                f"instance {desired_ipv4_name}. Hence not creating a new one!"
            )
            return ipv4_addr
        if start_index is not None:
            base_starting_ip = ipaddress.IPv4Address(ipv4_addr_info.starting_ip)
            base_gateway_starting_ip = ipaddress.IPv4Address(
                ipv4_addr_info.gateway_starting_ip
            )
            start_ip_increment_int = int(
                ipaddress.IPv4Address(ipv4_addr_info.increment_ip)
            )
            gateway_ip_increment_int = int(
                ipaddress.IPv4Address(ipv4_addr_info.gateway_increment_ip)
            )
            # Convert increment to int (e.g., "0.0.0.1" -> 1)
            starting_ip = str(base_starting_ip + (start_index * start_ip_increment_int))
            gateway_starting_ip = str(
                base_gateway_starting_ip + (start_index * gateway_ip_increment_int)
            )
        else:
            starting_ip = ipv4_addr_info.starting_ip
            gateway_starting_ip = ipv4_addr_info.gateway_starting_ip
        ipv4_addr: "Ipv4" = ethernet.Ipv4.add(Name=desired_ipv4_name)
        ipv4_addr.Address.Increment(
            start_value=starting_ip,
            step_value=ipv4_addr_info.increment_ip,
        )
        ipv4_addr.Prefix.Single(value=ipv4_addr_info.subnet_mask)
        ipv4_addr.GatewayIp.Increment(
            start_value=gateway_starting_ip,
            step_value=ipv4_addr_info.gateway_increment_ip,
        )
        if device_group_index:
            device_group_index.ipv4 = ipv4_addr
        self.logger.info(
            f"[{port_identifier}] Successfully created a new IPv4 "
            f"stack {desired_ipv4_name}"
        )
        return ipv4_addr

    def assign_ipv6_address(
        self,
        port_identifier: str,
        ipv6_addr_info: ixia_types.IPv6AddressInfo,
        ethernet: "Ethernet",
        device_group_index: t.Optional[DeviceGroupIndex] = None,
        start_index: t.Optional[int] = None,
        ipv6_multiplier: t.Optional[int] = None,
    ) -> "Ipv6":
        """
        This checks for the presence of an IPv6 protocol stack for
        a given ethernet group and port identifier. If found, we return
        that else we create a new IPv6 protocol stack and assign the IPv6
        address information for a given port identifier, IPv4 address
        information and ethernet group.

        Args:
            port_identifier: Device name associated with the ixia port.
                For e.g., "rsw001.p004.f03.snc1" or
                "ixia01.netcastle.snc1.facebook.com_2_5" if ixia back to
                back port connection is used.
            ipv4_addr_info: An object of type IPv6AddressInfo containing
                details pertaining to IPv6 address.
            ethernet: An object of type Ethernet associated with the given
                port identifier.

        Returns:
            An object of type Ipv6.
        """

        desired_ipv6_name: str = DESIRED_IPV6_NAME.format(
            port_identifier=port_identifier
        )
        ipv6_addr: "Ipv6" = ethernet.Ipv6.find(Name=desired_ipv6_name)

        if ipv6_addr:
            self.logger.info(
                f"[{port_identifier}] There is already an existing IPv6 "
                f"instance {desired_ipv6_name}. Hence not creating a new one!"
            )
            return ipv6_addr

        ipv6_add_kwargs: dict[str, t.Any] = {"Name": desired_ipv6_name}
        if ipv6_multiplier and ipv6_multiplier > 1:
            ipv6_add_kwargs["Multiplier"] = ipv6_multiplier
        ipv6_addr: "Ipv6" = ethernet.Ipv6.add(**ipv6_add_kwargs)

        if start_index is not None:
            base_starting_ip = ipaddress.IPv6Address(ipv6_addr_info.starting_ip)
            base_gateway_starting_ip = ipaddress.IPv6Address(
                ipv6_addr_info.gateway_starting_ip
            )
            start_ip_increment_int = int(
                ipaddress.IPv6Address(ipv6_addr_info.increment_ip)
            )
            gateway_ip_increment_int = int(
                ipaddress.IPv6Address(ipv6_addr_info.gateway_increment_ip)
            )
            starting_ip = str(base_starting_ip + (start_index * start_ip_increment_int))
            gateway_starting_ip = str(
                base_gateway_starting_ip + (start_index * gateway_ip_increment_int)
            )
        else:
            starting_ip = ipv6_addr_info.starting_ip
            gateway_starting_ip = ipv6_addr_info.gateway_starting_ip
        ipv6_addr.Address.Increment(
            start_value=starting_ip,
            step_value=ipv6_addr_info.increment_ip,
        )
        ipv6_addr.Prefix.Single(value=ipv6_addr_info.subnet_mask)
        ipv6_addr.GatewayIp.Increment(
            start_value=gateway_starting_ip,
            step_value=ipv6_addr_info.gateway_increment_ip,
        )
        if device_group_index:
            device_group_index.ipv6 = ipv6_addr
        self.logger.info(
            f"[{port_identifier}] Successfully created a new IPv6 "
            f"stack {desired_ipv6_name}"
        )
        return ipv6_addr

    def assign_ip_adddress(
        self,
        port_identifier: str,
        ip_addresses: ixia_types.IpAddresses,
        ethernet: "Ethernet",
        device_group_index: t.Optional[DeviceGroupIndex] = None,
        ipv6_multiplier: t.Optional[int] = None,
    ) -> IpAddressResult:
        """
        This API is used to assign IPv4 or IPv6 addresses based on the
        address family. These are needed for physical Ixia port. It could
        be conatain IPv4 address or IPv6 address or both.

        Args:
            port_identifier: Device name associated with the ixia port.
                For e.g., "rsw001.p004.f03.snc1" or
                "ixia01.netcastle.snc1.facebook.com_2_5" if ixia back to
                back port connection is used.
            ip_addresses: Object of type IpAddresses. Could contain IPv4
                or IPv6 address or both.
            ethernet: An object of type Ethernet defining the Ethernet
                protocol stack in the DeviceGroup.

        Returns:
            An object of namedtuple IpAddressResult containing IPv4 or/and
            IPv6 address.

        Raises:
            InvalidInputError: If no IP address is present in ip_addresses,
            this custom error is raised.
        """

        ipv4_addr, ipv6_addr = None, None
        ip_addresses_configs: t.List[
            t.Union[ixia_types.IPv4AddressInfo, ixia_types.IPv6AddressInfo]
        ] = []
        if ip_addresses.ipv6_addresses_config:
            ip_addresses_configs.append(ip_addresses.ipv6_addresses_config)
        if ip_addresses.ipv4_addresses_config:
            ip_addresses_configs.append(ip_addresses.ipv4_addresses_config)

        if not ip_addresses_configs:
            raise InvalidInputError(
                "Looks like no IP address information was provided while "
                f"configuring port {port_identifier}. At least one IP address "
                "information (IPv4|IPv6) is needed to complete the IXIA setup!"
            )

        for ip_address_config in ip_addresses_configs:
            if isinstance(ip_address_config, ixia_types.IPv4AddressInfo):
                ipv4_addr = self.assign_ipv4_address(
                    port_identifier,
                    ip_address_config,
                    ethernet,
                    device_group_index,
                    ip_address_config.start_index,
                )

            if isinstance(ip_address_config, ixia_types.IPv6AddressInfo):
                ipv6_addr = self.assign_ipv6_address(
                    port_identifier,
                    ip_address_config,
                    ethernet,
                    device_group_index,
                    ip_address_config.start_index,
                    ipv6_multiplier=ipv6_multiplier,
                )
            if not ipv4_addr and not ipv6_addr:
                self.logger.warning(
                    f"[{port_identifier}] Both v4 and v6 protocol stack does not "
                    f"exist for this port. Please check the config to see if "
                    "this is expected!"
                )

        return IpAddressResult(ipv4=ipv4_addr, ipv6=ipv6_addr)

    def start_protocols(self) -> None:
        """Used to start all the protocols synchronously"""

        self.ixnetwork.StartAllProtocols(Arg1="sync")
        self.logger.info(
            "[GLOBAL] Successfully started all the protocols in the IXIA setup"
        )

    def stop_protocols(self, sleep_timer: int = 0) -> None:
        """Used to stop all the protocols synchronously"""

        self.ixnetwork.StopAllProtocols(Arg1="sync")
        self.logger.info(
            "[GLOBAL] Successfully stopped all the protocols in the IXIA setup"
        )

        time.sleep(sleep_timer)

    def verify_protocols(self) -> None:
        """API to verify the status of the protocols in the topology"""
        if self.skip_ixia_protocol_verification:
            # We need to skip the protocol verification
            if self.ixia_protocol_verification_timeout:
                time.sleep(self.ixia_protocol_verification_timeout)
            return
        StatViewAssistant = (
            UhdStatViewAssistant if self.is_uhd_chassis else IxnStatViewAssistant
        )

        protocols_summary = StatViewAssistant(self.ixnetwork, "Protocols Summary")

        protocols_summary.CheckCondition(
            "Sessions Not Started", StatViewAssistant.EQUAL, 0
        )

        protocols_summary.CheckCondition("Sessions Down", StatViewAssistant.EQUAL, 0)

        self.logger.info(
            "[GLOBAL] Successfully verified the operational status of all "
            "the protocols in the IXIA setup!"
        )

    @retryable(num_tries=3, sleep_time=10, debug=True)
    def apply_changes(self, sleep_timer: int = 0) -> None:
        """API to apply the changes made on the fly to the topology"""

        self.ixnetwork.Globals.Topology.ApplyOnTheFly()
        self.logger.debug("[GLOBAL] Successfully applied changes on the fly")

        time.sleep(sleep_timer)

    @staticmethod
    def get_traffic_item_name(traffic_item: ixia_types.TrafficItem) -> str:
        """API to get the name of the traffic item

        Args:
            traffic_item: An object of type TrafficItem

        Returns:
            A string defining the name of the traffic iteam
        """
        src_name, dst_name = "", ""
        for source in traffic_item.source_endpoints:
            src_name += source.port_name
            if source.bgp_prefix_name:
                src_name += f"_{source.bgp_prefix_name}"
        for dest in traffic_item.dest_endpoints:
            dst_name += dest.port_name
            if dest.bgp_prefix_name:
                dst_name += f"_{dest.bgp_prefix_name}"
        traffic_item_name = (
            f"{src_name}_to_{dst_name}_{traffic_item.traffic_type.name}".upper()
        )
        return traffic_item_name

    @staticmethod
    def update_traffic_item_global_params(
        traffic_item: "IxiaTrafficItem",
        traffic_flow_config: ixia_types.TrafficFlowConfig,
    ) -> None:
        """Updates the global parameters of traffic item

        Args:
            traffic_item: An object of type IxiaTrafficItem
            traffic_flow_config: An object of type TrafficFlowConfig
        """

        traffic_item.update(
            AllowSelfDestined=traffic_flow_config.allow_self_destined,
            BiDirectional=traffic_flow_config.bidirectional,
            MergeDestinations=traffic_flow_config.merge_destinations,
            RouteMesh=ixia_types.ROUTE_MESH_MAP[traffic_flow_config.route_mesh],
            SrcDestMesh=ixia_types.SRC_DEST_MESH_MAP[traffic_flow_config.src_dest_mesh],
            TransmitMode=ixia_types.TRANSMIT_MODE_MAP[
                traffic_flow_config.transmit_mode
            ],
        )

    def get_endpoint_object(
        self,
        endpoint: ixia_types.Endpoint,
        traffic_type: ixia_types.TrafficType,
        # pyre-fixme[7]: Expected `t.Union[IxnIpv6, IxnNetworkGroup, IxnVport, UhdIpv6,
        #  UhdNetworkGroup, UhdVport]` but got implicit return value of `None`.
    ) -> t.Union["Ipv6", "NetworkGroup", "Vport", "Ipv4"]:
        port_identifier: str = Ixia.get_port_identifier(endpoint.port_name)
        if traffic_type == ixia_types.TrafficType.RAW:
            desired_vport_name: str = DESIRED_VPORT_NAME.format(
                port_identifier=port_identifier
            )
            vport: "Vport" = self.ixnetwork.Vport.find(Name=desired_vport_name)
            return vport.Protocols.find()

        vport_index = self.vport_indices[port_identifier]
        device_group_index = vport_index.device_group_indices[
            endpoint.device_group_index
        ]
        if traffic_type == ixia_types.TrafficType.IPV6:
            ipv6_obj: "Ipv6" = none_throws(device_group_index.ipv6)
            if endpoint.network_group_index is None:
                return ipv6_obj
            else:
                network_group_index = device_group_index.network_group_indices[
                    endpoint.network_group_index
                ]
                return network_group_index.network_group

        elif traffic_type == ixia_types.TrafficType.IPV4:
            ipv4_obj: "Ipv4" = none_throws(device_group_index.ipv4)
            if endpoint.network_group_index is None:
                return ipv4_obj
            else:
                network_group_index = device_group_index.network_group_indices[
                    endpoint.network_group_index
                ]
                return network_group_index.network_group

    def configure_frame_size(
        self, config_element: "ConfigElement", frame_size: ixia_types.FrameSize
    ) -> None:
        """Configures the frame size for the config element

        Args:
            config_element: An object of type ConfigElement
            frame_size: An object of type FrameSizeType defining the
                type - fixed or increment.
        """

        frame_size_raw: str = ixia_types.FRAME_SIZE_TYPE_MAP[frame_size.type]
        if frame_size.type == ixia_types.FrameSizeType.FIXED:
            config_element.FrameSize.update(
                Type=frame_size_raw, FixedSize=frame_size.fixed_size
            )
        elif frame_size.type == ixia_types.FrameSizeType.INCREMENT:
            config_element.FrameSize.update(
                Type=frame_size_raw,
                IncrementFrom=frame_size.increment_from,
                IncrementStep=frame_size.increment_step,
                IncrementTo=frame_size.increment_to,
            )
        elif frame_size.type == ixia_types.FrameSizeType.CUSTOM_IMIX:
            weighted_pairs = [n for p in frame_size.imix_weight.items() for n in p]
            config_element.FrameSize.update(
                Type=frame_size_raw,
                WeightedPairs=weighted_pairs,
            )
        elif frame_size.type == ixia_types.FrameSizeType.RANDOM:
            config_element.FrameSize.update(
                Type=frame_size_raw,
                RandomMax=frame_size.random_max,
                RandomMin=frame_size.random_min,
            )

    def configure_frame_payload_pattern(
        self,
        config_element: "ConfigElement",
        frame_payload_pattern: ixia_types.FramePayloadPattern,
    ) -> None:
        """Configures the frame payload pattern for the config element.

        Args:
            config_element: An object of type ConfigElement
            frame_payload_pattern: An object of type FramePayloadPattern
                defining the pattern - increment btye/word or decrement byte/word.
        """

        frame_payload_pattern_raw: str = ixia_types.FRAME_PAYLOAD_PATTERN_MAP[
            frame_payload_pattern
        ]
        config_element.FramePayload.update(Type=frame_payload_pattern_raw)

    def configure_custom_frame_payload(
        self,
        config_element: "ConfigElement",
        custom_hex_pattern: str,
    ) -> None:
        """Override FramePayload with raw custom bytes.

        Used to inject a structurally valid protocol body (e.g. a 28-byte ARP
        request) into RAW traffic items where the IxNetwork stack template is
        unavailable or unreliable. Bytes are placed at the start of the frame
        payload (after the explicit packet header stacks); IxNetwork zero-pads
        the remaining bytes to the configured frame size.
        """
        config_element.FramePayload.update(
            Type="custom",
            CustomPattern=custom_hex_pattern,
            CustomRepeat=False,
        )

    def configure_crc_type(
        self, config_element: "ConfigElement", crc_type: ixia_types.CrcType
    ) -> None:
        """Configures the CRC type for the config element.

        Args:
            config_element: An object of type ConfigElement
            crc_type: An object of type CrcType defining the
                type - good crc/bad crc.
        """

        crc_type_raw: str = ixia_types.CRC_TYPE_MAP[crc_type]
        config_element.update(Crc=crc_type_raw)

    def configure_frame_setup(
        self, config_element: "ConfigElement", traffic_item_info: ixia_types.TrafficItem
    ) -> None:
        """Configures the frame setup for the config element.

        Args:
            config_element: An object of type ConfigElement
            traffic_item_info: An object of type TrafficItem
        """

        traffic_flow_config: ixia_types.TrafficFlowConfig = (
            traffic_item_info.traffic_flow_config
        )

        self.configure_frame_size(config_element, traffic_flow_config.frame_size)

        self.configure_frame_payload_pattern(
            config_element, traffic_flow_config.frame_payload_pattern
        )

        self.configure_crc_type(config_element, traffic_flow_config.crc_type)

    @staticmethod
    def configure_traffic_rate(
        config_element: "ConfigElement", traffic_rate_info: ixia_types.TrafficRateInfo
    ) -> None:
        """Configures the traffic rate for the config element

        Args:
            config_element: An object of type ConfigElement
            traffic_rate_info: An object of type TrafficRateInfo
        """

        rate_type: ixia_types.RateType = traffic_rate_info.rate_type
        if rate_type == ixia_types.RateType.PERCENT_LINE_RATE:
            config_element.FrameRate.update(
                Type=ixia_types.RATE_TYPE_MAP[rate_type],
                Rate=traffic_rate_info.rate_value,
            )
        if rate_type == ixia_types.RateType.FRAMES_PER_SECOND:
            config_element.FrameRate.update(
                Type=ixia_types.RATE_TYPE_MAP[rate_type],
                Rate=traffic_rate_info.rate_value,
            )

    @staticmethod
    def _configure_transmission_control(
        config_element: "ConfigElement",
        transmission_control: ixia_types.TransmissionControl,
    ) -> None:
        """Configures the transmission control for the config element

        Args:
            config_element: An object of type ConfigElement
            transmission_control: An object of type TransmissionControl
        """

        transmission_control_type_raw: str = ixia_types.TRANS_CONTROL_TYPE_MAP[
            transmission_control.type
        ]
        if transmission_control.type == ixia_types.TransmissionControlType.CONTINUOUS:
            config_element.TransmissionControl.update(
                Type=transmission_control_type_raw
            )

        elif (
            transmission_control.type
            == ixia_types.TransmissionControlType.FIXED_DURATION
        ):
            config_element.TransmissionControl.update(
                Type=transmission_control_type_raw,
                Duration=transmission_control.duration,
            )

        elif (
            transmission_control.type
            == ixia_types.TransmissionControlType.FIXED_FRAME_COUNT
        ):
            config_element.TransmissionControl.update(
                Type=transmission_control_type_raw,
                Duration=transmission_control.frame_count,
            )

    @staticmethod
    def configure_rate_distribution(
        config_element: "ConfigElement", rate_distribution: ixia_types.RateDistribution
    ) -> None:
        """Configures rate distribution for the config element

        Args:
            config_element: An object of type ConfigElement
            rate_distribution: An object of type RateDistribution
        """

        port_rate_dis_type: ixia_types.RateDistributionType = (
            rate_distribution.port_rate_distribution
        )
        flowgroups_rate_dis_type: ixia_types.RateDistributionType = (
            rate_distribution.flowgroups_rate_distribution
        )
        config_element.FrameRateDistribution.update(
            PortDistribution=ixia_types.RATE_DIS_TYPE_MAP[port_rate_dis_type],
            StreamDistribution=ixia_types.RATE_DIS_TYPE_MAP[flowgroups_rate_dis_type],
        )

    def configure_rate_setup(
        self, config_element: "ConfigElement", traffic_item_info: ixia_types.TrafficItem
    ) -> None:
        """Configures the rate setup for the config element

        Args:
            config_element: An object of type ConfigElement
            traffic_item_info: An object of type TrafficItem
        """

        traffic_rate_info: ixia_types.TrafficRateInfo = (
            traffic_item_info.traffic_rate_info
        )
        traffic_flow_config: ixia_types.TrafficFlowConfig = (
            traffic_item_info.traffic_flow_config
        )

        Ixia.configure_traffic_rate(config_element, traffic_rate_info)

        Ixia.configure_rate_distribution(
            config_element, traffic_flow_config.rate_distribution
        )

        Ixia._configure_transmission_control(
            config_element, traffic_flow_config.transmission_control
        )

    @staticmethod
    def configure_traffic_stats_tracking(
        traffic_item_obj: "IxiaTrafficItem",
        traffic_flow_config: ixia_types.TrafficFlowConfig,
        default_tracking_types_raw: t.Optional[t.List[str]] = None,
    ) -> None:
        """Configures the traffic statistics for tracking the flow config for a
            traffic item

        Args:
            traffic_item_obj: An object of type IxiaTrafficItem
            traffic_flow_config: An object of type TrafficFlowConfig
        """
        tracking_types_raw = []
        if default_tracking_types_raw:
            tracking_types_raw.extend(default_tracking_types_raw)
        for tracking_type in traffic_flow_config.tracking_types:
            tracking_types_raw.append(
                ixia_types.TRAFFIC_STATS_TRACKING_TYPE_MAP[tracking_type]
            )
        tracking_obj: "Tracking" = traffic_item_obj.Tracking.find()
        tracking_obj.update(TrackBy=list(set(tracking_types_raw)))

    def _get_ip_address_family_str(
        self, ip_address_family: ixia_types.IpAddressFamily
    ) -> str:
        return (
            "IPv6" if ip_address_family == ixia_types.IpAddressFamily.IPV6 else "IPv4"
        )

    def set_hoplimit(
        self,
        config_element: "ConfigElement",
        ip_address_family: ixia_types.IpAddressFamily,
        hoplimit: ixia_types.HopLimitConfig,
    ) -> None:
        """API to set the hot limit

        Configures the traffic item with the hoplimit value
        for both IPv4(TTL) and IPv6(Hop Limit). Can be used
        to set one specific value.

        Args:
            config_element: An object of type ConfigElement.
            ip_family: A string defining the IP version.
            hoplimit: An object of type HopLimitConfig defining
                the value to be set for the hop limit.
        """

        disp_name = (
            "TTL (Time to live)"
            if ip_address_family == ixia_types.IpAddressFamily
            else "Hop Limit"
        )
        packet_header_stack_obj: "Stack" = config_element.Stack.find(
            DisplayName=self._get_ip_address_family_str(ip_address_family)
        )
        packet_header_field_obj: "Field" = packet_header_stack_obj.Field.find()
        hoplimit_field: "Field" = packet_header_field_obj.find(DisplayName=disp_name)
        hoplimit_field.ActiveFieldChoice = True
        hoplimit_field.SingleValue = str(hoplimit.value)

    def _create_l4_protocol_stack(
        self,
        traffic_item_obj: "IxiaTrafficItem",
        l4_protocol_config: ixia_types.L4ProtocolConfig,
    ) -> None:
        """Creates L4 protocol stack for the Device Group in the topology

        Args:
            traffic_item_obj: An object of type IxiaTrafficItem.
            l4_protocol_config: An object of type L4ProtocolConfig
                defining the L4 protocol stack configs.
        """

        protocol_name: str = ixia_types.TRANSPORT_PROTOCOL_MAP[
            l4_protocol_config.protocol
        ].upper()

        l3_stack_obj: "Stack" = traffic_item_obj.ConfigElement.find()[0].Stack.find(
            DisplayName="^IP.*"
        )
        protocol_template: "ProtocolTemplate" = (
            self.ixnetwork.Traffic.ProtocolTemplate.find(
                DisplayName=f"^{protocol_name}$"
            )
        )
        l3_stack_obj.AppendProtocol(Arg2=protocol_template.href)

        l4_stack_obj: "Stack" = traffic_item_obj.ConfigElement.find()[0].Stack.find(
            DisplayName=f"^{protocol_name}$"
        )

        l4_src_port_obj: "Field" = l4_stack_obj.Field.find(DisplayName="Source-Port")
        l4_src_port_obj.update(
            Auto=False,
            ValueType="increment",
            StartValue=str(l4_protocol_config.src_port_start_value),
            StepValue=str(l4_protocol_config.src_port_increment_value),
            CountValue=str(l4_protocol_config.src_port_count_value),
        )
        l4_dst_port_obj: "Field" = l4_stack_obj.Field.find(DisplayName="Dest-Port")
        l4_dst_port_obj.update(
            Auto=False,
            ValueType="increment",
            StartValue=str(l4_protocol_config.dst_port_start_value),
            StepValue=str(l4_protocol_config.dst_port_increment_value),
            CountValue=str(l4_protocol_config.dst_port_count_value),
        )

    def modify_traffic_options(self) -> None:
        """API to modify the traffic options

        This will enable the capability to enable the packet loss duration
        in milliseconds.
        """

        self.ixnetwork.Traffic.Statistics.PacketLossDuration.update(Enabled=True)

    def find_or_create_stack(
        self,
        trafficItemObj: "IxiaTrafficItem",
        query: ixia_types.Query,
        append_to_query: t.Optional[ixia_types.Query] = None,
    ):
        config_element = trafficItemObj.ConfigElement.find()[0]
        if append_to_query:
            packet_header_protocol_template = (
                self.ixnetwork.Traffic.ProtocolTemplate.find(
                    **{ixia_types.QUERY_TYPE_MAP[query.query_type]: query.regex}
                )
            )
            if not config_element.Stack.find(
                StackTypeId=packet_header_protocol_template.StackTypeId
            ):
                append_to_stack_obj = config_element.Stack.find(
                    **{
                        ixia_types.QUERY_TYPE_MAP[
                            append_to_query.query_type
                        ]: append_to_query.regex
                    }
                )
                append_to_stack_obj.Append(Arg2=packet_header_protocol_template)
        stack = config_element.Stack.find(
            **{ixia_types.QUERY_TYPE_MAP[query.query_type]: query.regex}
        )
        return stack

    def modify_packet_headers(
        self,
        traffic_item_obj: "IxiaTrafficItem",
        packet_headers: t.Sequence[ixia_types.PacketHeader],
    ) -> None:
        for packet_header in packet_headers:
            stack = self.find_or_create_stack(
                traffic_item_obj,
                query=packet_header.query,
                append_to_query=packet_header.append_to_query,
            )
            if packet_header.remove_from_stack:
                stack.Remove()
                continue
            if not packet_header.fields:
                continue
            for header_field in packet_header.fields:
                field_obj = stack.Field.find(
                    **{
                        ixia_types.QUERY_TYPE_MAP[
                            header_field.query.query_type
                        ]: header_field.query.regex
                    }
                )
                if not field_obj:
                    continue
                for attr in header_field.attrs:
                    if hasattr(field_obj, attr.name):
                        attr_value = attr.value.value
                        if attr.value.type in [
                            ixia_types.AttrValue.Type.integer_list,
                            ixia_types.AttrValue.Type.str_list,
                        ]:
                            attr_value = list(attr_value)  # pyre-ignore
                        setattr(field_obj, attr.name, attr_value)
            self.logger.info(
                f"Successfully created or modified packet header {packet_header.query.regex}"
            )
        self.logger.info(
            f"Successfully created and/or modified all packet headers for the traffic item {traffic_item_obj.Name}"
        )

    def create_packet_header(
        self, trafficItemObj, packet_header_to_add=None, append_to_stack=None
    ):
        config_element = trafficItemObj.ConfigElement.find()[0]

        # Do the followings to add packet headers on the new traffic item

        # Uncomment this to show a list of all the available protocol templates to create (packet headers)
        # for protocolHeader in ixNetwork.Traffic.ProtocolTemplate.find():
        #     ixNetwork.info('Protocol header: --{}--'.format(protocolHeader.StackTypeId))

        # 1> Get the <new packet header> protocol template from the ProtocolTemplate list.
        packet_header_protocol_template = self.ixnetwork.Traffic.ProtocolTemplate.find(
            StackTypeId=packet_header_to_add
        )
        # 2> Append the <new packet header> object after the specified packet header stack.
        append_to_stack_obj = config_element.Stack.find(StackTypeId=append_to_stack)
        append_to_stack_obj.Append(Arg2=packet_header_protocol_template)

        # 3> Get the new packet header stack to use it for appending an IPv4 stack after it.
        # Look for the packet header object and stack ID.
        packet_header_stack_obj = config_element.Stack.find(
            StackTypeId=packet_header_to_add
        )

        # 4> In order to modify the fields, get the field object
        packet_header_field_obj = packet_header_stack_obj.Field.find()

        # 5> Save the above configuration to the base config file.
        # ixNetwork.SaveConfig(Files('baseConfig.ixncfg', local_file=True))

        return packet_header_field_obj

    def create_traffic_items(
        self,
        traffic_items: t.Sequence[ixia_types.TrafficItem],
        override_traffic_items: bool = False,
    ) -> None:
        """API to create traffic item

        This API checks for the presence of traffic items in the topology. If
        found, we continue else we create new traffic items. This has various
        steps involved in the process.
            Step 1: Create the base traffic item object.
            Step 2: Update the global parameters for the traffic item.
            Step 3: Configure the endpoint flow groups.
            Step 4: Configure all the frame level parameters.
            Step 5: Configure all the traffic rate related parameters
            Step 6: Configure the Transport layer L4 (TCP/UDP) protocol stack on
                top of the IP (L3) layer.
            Step 7: Configure the type of traffic statistics tracking for the
                current traffic item.
            STEP 8: Configure the MPLS protocol stack on top of the
                Ethernet (L2) layer
            Step 9: Regenerate the traffic item.
            Step 10: Modify traffic options. This will enable the capturing of
                packet loss duration in ms while fetching the traffic statistics.

        Args:
            traffic_items: A list containing elements of type TrafficItem.
        """

        for traffic_item_info in traffic_items:
            traffic_item_name: str = (
                traffic_item_info.name or Ixia.get_traffic_item_name(traffic_item_info)
            )
            self.logger.debug(
                f"[GLOBAL] Attempting to create traffic item {traffic_item_name}"
            )

            traffic_item_obj: "IxiaTrafficItem" = (
                self.ixnetwork.Traffic.TrafficItem.find(Name=rf"^{traffic_item_name}&")
            )
            if traffic_item_obj and not override_traffic_items:
                self.logger.info(
                    f"[{traffic_item_name}] There is already an existing Traffic "
                    f"item instance {traffic_item_name}. Hence not creating a new one!"
                )
                continue
            else:
                # [STEP 1]: Creating the base traffic item object
                traffic_item_obj: "IxiaTrafficItem" = (
                    self.ixnetwork.Traffic.TrafficItem.add(
                        Name=traffic_item_name,
                        TrafficType=ixia_types.TRAFFIC_TYPE_MAP[
                            traffic_item_info.traffic_type
                        ],
                    )
                )
                if traffic_item_info.traffic_type == ixia_types.TrafficType.RAW:
                    traffic_item_obj.TrafficItemType = "l2L3"
            self.logger.debug(
                f"[{traffic_item_name}] Successfully found or created the base "
                "traffic item object"
            )

            # [STEP 2]: Updating global parameters for the traffic item
            Ixia.update_traffic_item_global_params(
                traffic_item_obj, traffic_item_info.traffic_flow_config
            )
            self.logger.debug(
                f"[{traffic_item_name}] Successfully configured the global "
                "parameters for this traffic item"
            )
            # [STEP 3]: Adding Endpoint flow groups
            sources = [
                self.get_endpoint_object(
                    src_endpoint,
                    traffic_type=traffic_item_info.traffic_type,
                )
                for src_endpoint in traffic_item_info.source_endpoints
            ]
            destinations = [
                self.get_endpoint_object(
                    dest_endpoint,
                    traffic_type=traffic_item_info.traffic_type,
                )
                for dest_endpoint in traffic_item_info.dest_endpoints
            ]
            traffic_item_obj.EndpointSet.add(
                Sources=sources,
                Destinations=destinations,
            )
            self.logger.debug(
                f"[{traffic_item_name}] Successfully added the source and "
                "destination endpoints for this traffic item"
            )

            # Note: The traffic item could have several Endpoint sets/flow groups.
            # That is why config_element is a list
            config_element: "ConfigElement" = traffic_item_obj.ConfigElement.find()[0]
            # [STEP 4]: Configure all frame level parameters
            self.configure_frame_setup(config_element, traffic_item_info)
            self.logger.debug(
                f"[{traffic_item_name}] Successfully configured the frame "
                "level parameters for this traffic item"
            )

            custom_frame_payload = get_custom_frame_payload(traffic_item_name)
            if custom_frame_payload is not None:
                self.configure_custom_frame_payload(
                    config_element, custom_frame_payload
                )
                self.logger.info(
                    f"[{traffic_item_name}] Applied custom frame payload "
                    f"({len(custom_frame_payload) // 2} bytes) from registry"
                )

            # [STEP 5]: Configure all traffic rate related parameters
            self.configure_rate_setup(config_element, traffic_item_info)
            self.logger.debug(
                f"[{traffic_item_name}] Successfully configured the traffic "
                "rate parameters for this traffic item"
            )
            if traffic_item_info.packet_headers:
                self.modify_packet_headers(
                    traffic_item_obj, traffic_item_info.packet_headers
                )
            if traffic_item_info.traffic_type == ixia_types.TrafficType.IPV6:
                ip_address_family = ixia_types.IpAddressFamily.IPV6
            elif traffic_item_info.traffic_type == ixia_types.TrafficType.IPV4:
                ip_address_family = ixia_types.IpAddressFamily.IPV4
            else:
                ip_address_family = None
            # Set hoplimit (ttl) config
            if traffic_item_info.hoplimit_config:
                self.set_hoplimit(
                    config_element,
                    none_throws(ip_address_family),
                    traffic_item_info.hoplimit_config,
                )
                self.logger.info(
                    f"[{traffic_item_name}] Successfully configured the hoplimit "
                    "config for this traffic item"
                )
            if traffic_item_info.qos_config:
                self.configure_qos_config(
                    config_element,
                    traffic_item_info.qos_config,
                    none_throws(ip_address_family),
                )
                self.logger.debug(
                    f"[{traffic_item_name}] Successfully configured the QoS "
                    "Config for this traffic item"
                )

            if traffic_item_info.l4_protocol_config:
                # [STEP 6]: Configure the Transport layer L4 (TCP/UDP) protocol
                # stack on top of the IP (L3) layer
                self._create_l4_protocol_stack(
                    traffic_item_obj, traffic_item_info.l4_protocol_config
                )
                self.logger.debug(
                    f"[{traffic_item_name}] Successfully configured the L4 "
                    "protocol stack for this traffic item"
                )

            default_tracking_types_raw = (
                [
                    ixia_types.TRAFFIC_STATS_TRACKING_TYPE_MAP[
                        ixia_types.TrafficStatsTrackingType.FLOW_GROUP
                    ]
                ]
                if traffic_item_info.traffic_type != ixia_types.TrafficType.RAW
                and not traffic_item_info.traffic_flow_config.tracking_types
                else []
            )
            # [STEP 7]: Configure the type of traffic statistics tracking
            Ixia.configure_traffic_stats_tracking(
                traffic_item_obj,
                traffic_item_info.traffic_flow_config,
                default_tracking_types_raw,
            )
            self.logger.debug(
                f"[{traffic_item_name}] Successfully configured the traffic "
                "statistics tracking type for this tracking item"
            )
            # [STEP 9]: Regenerate traffic item
            traffic_item_obj.Generate()
            self.logger.debug(
                f"[{traffic_item_name}] Successfully regenerated the traffic item"
            )
            traffic_item_obj.update(Enabled=traffic_item_info.enabled)

            # [STEP 9]: Modify traffic options. This will enable the capture of
            # packet loss duration in ms while fetching the traffic statistics
            self.modify_traffic_options()

            self.logger.info(
                "[GLOBAL] Successfully configured all parameters for the "
                f"traffic item {traffic_item_name}"
            )

    def modify_bgp_capabilities(
        self,
        bgp_peer_obj: t.Union["BgpIpv4Peer", "BgpIpv6Peer"],
        desired_capabilities: t.Sequence[ixia_types.BgpCapability],
    ) -> None:
        """
        Modifies the various BGP capabilities as set by the user in
        `ixia.thrift`.

        Args:
            bgp_peer_obj: An object of type either BgpIpv4Peer or BgpIpv6Peer
                which has the user-defined BGP capabilities defined.
            desired_capabilities: A list of type BgpCapability which is desired.
        """

        bgp_cap_obj_map = defaultdict()
        for capability in ixia_types.BgpCapability:
            if capability == ixia_types.BgpCapability.IpV4Unicast:
                bgp_cap_obj_map[capability] = bgp_peer_obj.CapabilityIpV4Unicast

            elif capability == ixia_types.BgpCapability.IpV6Unicast:
                bgp_cap_obj_map[capability] = bgp_peer_obj.CapabilityIpV6Unicast

            elif capability == ixia_types.BgpCapability.RouteRefresh:
                bgp_cap_obj_map[capability] = bgp_peer_obj.CapabilityRouteRefresh

            elif capability == ixia_types.BgpCapability.IpV4Multicast:
                bgp_cap_obj_map[capability] = bgp_peer_obj.CapabilityIpV4Multicast

            elif capability == ixia_types.BgpCapability.IpV4MulticastVpn:
                bgp_cap_obj_map[capability] = bgp_peer_obj.CapabilityIpV4MulticastVpn

            elif capability == ixia_types.BgpCapability.IpV4MplsVpn:
                bgp_cap_obj_map[capability] = bgp_peer_obj.CapabilityIpV4MplsVpn

            elif capability == ixia_types.BgpCapability.IpV6Mpls:
                bgp_cap_obj_map[capability] = bgp_peer_obj.CapabilityIpV6Mpls

            elif capability == ixia_types.BgpCapability.IpV6MplsVpn:
                bgp_cap_obj_map[capability] = bgp_peer_obj.CapabilityIpV6MplsVpn

            elif capability == ixia_types.BgpCapability.IpV6Multicast:
                bgp_cap_obj_map[capability] = bgp_peer_obj.CapabilityIpV6Multicast

            elif capability == ixia_types.BgpCapability.IpV6MulticastVpn:
                bgp_cap_obj_map[capability] = bgp_peer_obj.CapabilityIpV6MulticastVpn

            elif capability == ixia_types.BgpCapability.Ipv4UnicastAddPath:
                bgp_cap_obj_map[capability] = bgp_peer_obj.CapabilityIpv4UnicastAddPath

            elif capability == ixia_types.BgpCapability.Ipv6UnicastAddPath:
                bgp_cap_obj_map[capability] = bgp_peer_obj.CapabilityIpv6UnicastAddPath

            elif capability == ixia_types.BgpCapability.LinkStateNonVpn:
                bgp_cap_obj_map[capability] = bgp_peer_obj.CapabilityLinkStateNonVpn

            # fmt: off
            # BgpIpv4Peer does not have the Next Hop Encoding capability
            elif capability == ixia_types.BgpCapability.NHEncodingCapabilities and (
                isinstance(bgp_peer_obj, IxnBgpIpv6Peer)
                or isinstance(bgp_peer_obj, UhdBgpIpv6Peer)
            ):
                bgp_cap_obj_map[capability] = (
                    bgp_peer_obj.CapabilityNHEncodingCapabilities
                )  # noqa
            # fmt: on

            elif capability == ixia_types.BgpCapability.RouteConstraint:
                bgp_cap_obj_map[capability] = bgp_peer_obj.CapabilityRouteConstraint

            elif capability == ixia_types.BgpCapability.SRTEPoliciesV4:
                bgp_cap_obj_map[capability] = bgp_peer_obj.CapabilitySRTEPoliciesV4

            elif capability == ixia_types.BgpCapability.SRTEPoliciesV6:
                bgp_cap_obj_map[capability] = bgp_peer_obj.CapabilitySRTEPoliciesV6

            elif capability == ixia_types.BgpCapability.Vpls:
                bgp_cap_obj_map[capability] = bgp_peer_obj.CapabilityVpls

            elif capability == ixia_types.BgpCapability.ipv4UnicastFlowSpec:
                bgp_cap_obj_map[capability] = bgp_peer_obj.Capabilityipv4UnicastFlowSpec

            elif capability == ixia_types.BgpCapability.ipv6UnicastFlowSpec:
                bgp_cap_obj_map[capability] = bgp_peer_obj.Capabilityipv6UnicastFlowSpec

        for bgp_capability, cap_obj in bgp_cap_obj_map.items():
            if bgp_capability in desired_capabilities:
                cap_obj.Single(True)
            else:
                cap_obj.Single(False)

    def create_bgp_peer(
        self,
        port_identifier: str,
        ip_address_family: ixia_types.IpAddressFamily,
        bgp_peer_config: ixia_types.BgpPeerConfig,
        ip_addr_obj: t.Union["Ipv4", "Ipv6"],
    ) -> t.Union["BgpIpv4Peer", "BgpIpv6Peer"]:
        """API to create a BGP peer

        This API checks for the presence of a BGP IP peer
        in the topology. If the object is found, we use that
        else a new BGP peer object is created. This involes
        with populating the various BGP related properties.

        Args:
            port_identifier: Device name associated with the ixia port.
                For e.g., "rsw001.p004.f03.snc1" or
                "ixia01.netcastle.snc1.facebook.com_2_5" if ixia back to
                back port connection is used.
            ip_address_family: An object of type IpAddressFamily defining the IP
                version.
            bgp_peer_config: An object of type BgpPeerConfig defining the
                configs related to the BGP peer.
            ip_addr_obj: An object of type either Ipv4 or Ipv6.

        Returns:
            An object of type either BgpIpv4Peer or BgpIpv6Peer.
        """
        if ip_address_family == ixia_types.IpAddressFamily.IPV4:
            desired_bgp_name: str = (
                bgp_peer_config.bgp_peer_name
                or DESIRED_BGP_V4_PEER_NAME.format(port_identifier=port_identifier)
            )
            bgp_peer_cls = ip_addr_obj.BgpIpv4Peer  # pyre-ignore

        elif ip_address_family == ixia_types.IpAddressFamily.IPV6:
            desired_bgp_name: str = (
                bgp_peer_config.bgp_peer_name
                or DESIRED_BGP_V6_PEER_NAME.format(port_identifier=port_identifier)
            )
            bgp_peer_cls = ip_addr_obj.BgpIpv6Peer  # pyre-ignore

        bgp_peer_obj: t.Union["BgpIpv4Peer", "BgpIpv6Peer"] = bgp_peer_cls.find(
            # pyre-fixme[61]: `desired_bgp_name` may not be initialized here.
            Name=desired_bgp_name
        )
        if bgp_peer_obj:
            self.logger.info(
                f"[{port_identifier}] There is already an existing IPv6 "
                # pyre-fixme[61]: `desired_bgp_name` may not be initialized here.
                f"instance of the BGP prefix {desired_bgp_name}. Hence "
                "not creating a new one!"
            )
            return bgp_peer_obj

        bgp_peer_obj: t.Union["BgpIpv4Peer", "BgpIpv6Peer"] = bgp_peer_cls.add(
            # pyre-fixme[61]: `desired_bgp_name` may not be initialized here.
            Name=desired_bgp_name
        )
        bgp_peer_obj.DutIp.Increment(
            start_value=bgp_peer_config.remote_peer_starting_ip,
            step_value=bgp_peer_config.remote_peer_increment_ip,
        )
        bgp_peer_obj.Type.Single(
            ixia_types.BGP_PEER_TYPE_MAP[bgp_peer_config.peer_type]
        )
        bgp_peer_obj.LocalAs2Bytes.Increment(
            start_value=bgp_peer_config.local_as,
            step_value=bgp_peer_config.local_as_increment,
        )
        if bgp_peer_config.enable_4_byte_local_as:
            bgp_peer_obj.Enable4ByteAs.Single(value=True)
            bgp_peer_obj.LocalAs4Bytes.Increment(
                start_value=bgp_peer_config.local_as_4_bytes
                or bgp_peer_config.local_as,
                step_value=bgp_peer_config.local_as_increment,
            )
        # Set AS Set Mode - explicit setting takes precedence over is_confed
        # Use getattr for backward compatibility with older thrift types
        as_set_mode = getattr(bgp_peer_config, "as_set_mode", None)
        if as_set_mode is not None:
            as_set_mode_str = ixia_types.BGP_AS_SET_MODE_MAP.get(as_set_mode)
            if as_set_mode_str:
                self.logger.info(
                    f"[{port_identifier}] Setting AsSetMode to {as_set_mode_str}"
                )
                bgp_peer_obj.AsSetMode.Single(as_set_mode_str)
        elif bgp_peer_config.is_confed:
            self.logger.info(f"[{port_identifier}] Setting Confed")
            bgp_peer_obj.AsSetMode.Single("includelocalasasasseqconfederation")

        bgp_peer_obj.RestartTime.Single(bgp_peer_config.graceful_restart_timer)
        bgp_peer_obj.EnableGracefulRestart.Single(
            bgp_peer_config.enable_graceful_restart
        )

        bgp_peer_obj.AdvertiseEndOfRib.Single(bgp_peer_config.advertise_end_of_rib)

        if bgp_peer_config.hold_timer is not None:
            bgp_peer_obj.HoldTimer.Single(bgp_peer_config.hold_timer)
        if bgp_peer_config.keepalive_timer is not None:
            bgp_peer_obj.ConfigureKeepaliveTimer.Single(True)
            bgp_peer_obj.KeepaliveTimer.Single(bgp_peer_config.keepalive_timer)

        if bgp_peer_config.capabilities:
            self.modify_bgp_capabilities(bgp_peer_obj, bgp_peer_config.capabilities)

        if bgp_peer_config.peer_flap_config:
            # NOTE: Initially configuring the flap settings and disabling the
            # flap action. This will be enabled only on adhoc basis by
            # by calling the actual BGP peers flap method
            bgp_peer_obj.Flap.Single(value=True)
            bgp_peer_obj.UptimeInSec.Single(
                value=bgp_peer_config.peer_flap_config.uptime_in_sec
            )
            bgp_peer_obj.DowntimeInSec.Single(
                value=bgp_peer_config.peer_flap_config.downtime_in_sec
            )

        self.logger.info(
            # pyre-fixme[61]: `desired_bgp_name` may not be initialized here.
            f"[{port_identifier}] Successfully created BGP peer {desired_bgp_name}"
        )
        return bgp_peer_obj

    def check_valid_advertised_address(
        self,
        addresses: t.List[str],
        ip_version: ixia_types.IpAddressFamily,
        device_group_name: str,
    ) -> None:
        """
        For a given list of ip address, this function checks if the given addresses are part
        of the allowed_advertised ip prefixes. If not raises an exception

        Args:
            addresses: Address to be checked, could be a v6 or v4 address
            ip_verions: address family of the address v4 or v6
            device_group_name: Name of the device group to include while raising exception
        """
        if self.skip_advertised_prefixes_check:
            return

        if ip_version == ixia_types.IpAddressFamily.IPV4:
            allowed_advertisements = ALLOWED_IPV4_ADVERTISEMENTS
        elif ip_version == ixia_types.IpAddressFamily.IPV6:
            allowed_advertisements = ALLOWED_IPV6_ADVERTISEMENTS

        for addr in addresses:
            valid_address = False
            for allowed_advertisement in allowed_advertisements:
                if ipaddress.ip_address(addr) in allowed_advertisement:
                    valid_address = True
                    break
            if not valid_address:
                raise DangerousIxiaIPAdvertiseError(
                    f"Dangerous ip advertisement from device group {device_group_name}: {addr}"
                )

    def get_advertised_bgp_prefixes(self) -> t.List[str]:
        v4_v6_advertised_bgp_prefixes = []
        topologies = self.ixnetwork.Topology.find()
        for topology in topologies:
            for device_group in topology.DeviceGroup.find():
                for network_group in device_group.NetworkGroup.find():
                    for ip_prefix_pool in network_group.Ipv6PrefixPools.find():
                        v4_v6_advertised_bgp_prefixes += (
                            ip_prefix_pool.NetworkAddress.Values
                        )
                    for ip_prefix_pool in network_group.Ipv4PrefixPools.find():
                        v4_v6_advertised_bgp_prefixes += (
                            ip_prefix_pool.NetworkAddress.Values
                        )
        return v4_v6_advertised_bgp_prefixes

    def get_prefix_pools(
        self, regex: t.Optional[str] = None, ignore_case: bool = False
    ) -> t.List[t.Union["Ipv6PrefixPools", "Ipv4PrefixPools"]]:
        prefix_pools = []
        topologies = self.ixnetwork.Topology.find()
        for topology in topologies:
            for device_group in topology.DeviceGroup.find():
                self._collect_prefix_pools(device_group, prefix_pools)
        if regex:
            prefix_pools = [
                pool
                for pool in prefix_pools
                if re.search(regex, pool.Name, re.IGNORECASE if ignore_case else 0)
            ]
        return prefix_pools

    def _collect_prefix_pools(
        self,
        device_group: "DeviceGroup",
        prefix_pools: t.List[t.Union["Ipv6PrefixPools", "Ipv4PrefixPools"]],
    ) -> None:
        for network_group in device_group.NetworkGroup.find():
            prefix_pools.extend(network_group.Ipv6PrefixPools.find())
            prefix_pools.extend(network_group.Ipv4PrefixPools.find())
        for child_dg in device_group.DeviceGroup.find():
            self._collect_prefix_pools(child_dg, prefix_pools)

    def verify_ip_advertise_gating(self) -> None:
        """
        For a given Ixia session checks the presence of any IP prefix pools and
        verified if the IP addresses advertised by this pools is laong the expected
        The hierarchy of Ixia session is topology -> Device group -> Network group ->
        ip prefix pool -> Last network address
        Verify that ip network of these last network addresses are not outside the
        range, if not then raise the appropriate address
        """
        topologies = self.ixnetwork.Topology.find()
        for topology in topologies:
            for device_group in topology.DeviceGroup.find():
                for network_group in device_group.NetworkGroup.find():
                    for ip_prefix_pool in network_group.Ipv6PrefixPools.find():
                        self.check_valid_advertised_address(
                            # NetworkAddress is of type ixnetwork_restpy.multivalue.Multivalue
                            # Need to use .Values to find addresses
                            ip_prefix_pool.NetworkAddress.Values,
                            ixia_types.IpAddressFamily.IPV6,
                            device_group.Name,
                        )
                        self.check_valid_advertised_address(
                            ip_prefix_pool.LastNetworkAddress,
                            ixia_types.IpAddressFamily.IPV6,
                            device_group.Name,
                        )
                    for ip_prefix_pool in network_group.Ipv4PrefixPools.find():
                        self.check_valid_advertised_address(
                            # NetworkAddress is of type ixnetwork_restpy.multivalue.Multivalue
                            # Need to use .Values to find addresses
                            ip_prefix_pool.NetworkAddress.Values,
                            ixia_types.IpAddressFamily.IPV4,
                            device_group.Name,
                        )
                        self.check_valid_advertised_address(
                            ip_prefix_pool.LastNetworkAddress,
                            ixia_types.IpAddressFamily.IPV4,
                            device_group.Name,
                        )
        self.logger.info("Ixia IP advertisement verified for this session")

    def get_traffic_items(
        self, regex: t.Optional[str] = None
    ) -> t.List["IxiaTrafficItem"]:
        all_traffic_items = self.ixnetwork.Traffic.TrafficItem.find()
        if regex:
            return [
                traffic_item
                for traffic_item in all_traffic_items
                if re.search(regex, traffic_item.Name, re.IGNORECASE)
            ]
        return all_traffic_items

    @external_api
    def regenerate_traffic_items(self, regex: t.Optional[str] = None) -> None:
        self.logger.info("Regenerating traffic items...")
        traffic_running = self.is_traffic_running()
        if traffic_running:
            self.stop_traffic()
        traffic_items = self.get_traffic_items(regex)
        for traffic_item_obj in traffic_items:
            traffic_item_obj.Generate()
        self.logger.info(traffic_items)
        if traffic_running:
            self.start_traffic()

    @external_api
    def start_bgp_peers(
        self,
        start: bool,
        regex: t.Optional[str] = None,
        ignore_case: bool = False,
        vport_idx: t.Optional[str] = None,
        device_group_idx: t.Optional[int] = None,
        session_start_idx: int = 1,
        session_end_idx: t.Optional[int] = None,
    ) -> None:
        assert regex or (
            device_group_idx and vport_idx,
            "Either regex or vport_idx and network_group_idx is required",
        )
        if regex:
            bgp_peers = self.find_bgp_peers(regex, ignore_case)
        else:
            device_group_idx_obj = self.vport_indices[
                none_throws(vport_idx)
            ].device_group_indices[none_throws(device_group_idx)]
            bgp_peers = []
            for (
                network_group_index
            ) in device_group_idx_obj.network_group_indices.values():
                if network_group_index.ipv4_bgp_peer:
                    bgp_peers.append(network_group_index.ipv4_bgp_peer)
                if network_group_index.ipv6_bgp_peer:
                    bgp_peers.append(network_group_index.ipv6_bgp_peer)
        for bgp_peer in bgp_peers:
            session_end_idx = session_end_idx or bgp_peer.Count
            if start:
                bgp_peer.Start(SessionIndices=f"{session_start_idx}-{session_end_idx}")
            else:
                bgp_peer.Stop(SessionIndices=f"{session_start_idx}-{session_end_idx}")
            self.logger.debug(
                f"Successfully {'started' if start else 'stopped'} BGP sessions {session_start_idx}-{session_end_idx} on {bgp_peer.Name}"
            )

    @external_api
    def toggle_device_groups(
        self,
        enable: bool,
        device_group_name_regex: str,
        all_bgp_peers: bool = False,
        exception_device_groups: t.Optional[t.List[str]] = None,
        sleep_time_before_applying_change: int = 30,
    ) -> None:
        if all_bgp_peers:
            device_groups = self.find_device_groups(device_group_name_regex)
            for device_group in device_groups:
                # Skip if any exception matches
                if exception_device_groups and any(
                    exception in device_group.Name
                    for exception in exception_device_groups
                ):
                    continue
                self.logger.info(f"Applying enable={enable} to {device_group.Name}")
                device_group.Enabled.Single(enable)
        else:
            device_groups = self.find_device_groups(device_group_name_regex)
            for device_group in device_groups:
                self.logger.info(f"Applying enable={enable} to {device_group.Name}")
                device_group.Enabled.Single(enable)
        self.logger.info(
            f"Waiting for {sleep_time_before_applying_change}s before applying change"
        )
        time.sleep(sleep_time_before_applying_change)
        self.apply_changes()
        device_group_name = [device_group.Name for device_group in device_groups]
        self.logger.info(
            f"Successfully {'enabled' if enable else 'disabled'} device group {device_group_name}"
        )

    @external_api
    def rename_device_groups(
        self,
        device_group_name_regex: str,
        old_tag_name: str,
        new_tag_name: str,
    ) -> None:
        """Rename device groups by replacing a tag name substring in their names.

        This API finds device groups matching the regex and replaces occurrences
        of old_tag_name with new_tag_name in their names. This is useful for
        dynamically updating device group tags during test execution.

        Args:
            device_group_name_regex: Regex pattern to match device group names.
            old_tag_name: The tag name substring to replace.
            new_tag_name: The new tag name to use as replacement.
        """
        device_groups = self.find_device_groups(device_group_name_regex)
        for device_group in device_groups:
            old_name = device_group.Name
            new_name = old_name.replace(old_tag_name, new_tag_name)
            device_group.Name = new_name
            self.logger.info(f"Renamed device group '{old_name}' -> '{new_name}'")
        # Update the tag_name_to_device_group_name_list mapping
        if old_tag_name in self.tag_name_to_device_group_name_list:
            old_device_group_names = self.tag_name_to_device_group_name_list.pop(
                old_tag_name
            )
            self.tag_name_to_device_group_name_list[new_tag_name] = [
                name.replace(old_tag_name, new_tag_name)
                for name in old_device_group_names
            ]
        self.apply_changes()

    @external_api
    def toggle_session_flapping(
        self,
        is_flap: bool,
        is_active: bool,
        bgp_peer_group_name_regex: str,
    ) -> None:
        self.logger.info(
            f"Attemping to set enable to flap to {is_flap} for {bgp_peer_group_name_regex} regexes"
        )
        bgp_peers = self.find_bgp_peers(bgp_peer_group_name_regex)
        for bgp_peer in bgp_peers:
            bgp_peer.Flap.Single(value=is_flap)
            self.logger.info(f"Setting Flap feature of {bgp_peer.Name} to {is_flap}")
        self.apply_changes()

    @external_api
    def toggle_prefix_flapping(
        self,
        is_flap: bool,
        network_group_name_regex: str,
        uptime_in_sec=None,
        downtime_in_sec=None,
    ) -> None:
        self.logger.info(
            f"Attemping to set enable to flap to {is_flap} for {network_group_name_regex} Network group regexes"
        )
        network_groups = self.find_network_groups(network_group_name_regex)
        prefix_pools = []
        for network_group in network_groups:
            prefix_pools.extend(network_group.Ipv6PrefixPools.find())
            prefix_pools.extend(network_group.Ipv4PrefixPools.find())
        self.logger.info(f"Prefix pools: {[pool.Name for pool in prefix_pools]}")
        for prefix_pool in prefix_pools:
            bgp_ip_route_property: "BgpIPRouteProperty" = (
                (prefix_pool.BgpIPRouteProperty.find())
                if isinstance(prefix_pool, Ipv4PrefixPools)
                else prefix_pool.BgpV6IPRouteProperty.find()
            )[0]
            bgp_ip_route_property.EnableFlapping.Single(value=is_flap)
            if is_flap:
                # if not uptime_in_sec or not downtime_in_sec:
                #     raise
                bgp_ip_route_property.Uptime.Single(value=uptime_in_sec)
                bgp_ip_route_property.Downtime.Single(value=downtime_in_sec)

            self.logger.info(
                f"Updated Flap setting to {'enabled' if is_flap else 'disabled'} for {prefix_pool.Name}"
            )
        self.apply_changes()

    @external_api
    def configure_traffic_item_src_mac_entry_count(
        self,
        src_mac_entry_count: int,
        traffic_item_name: str = "",
        traffic_item_regex: str = "",
    ) -> None:
        self.logger.info(
            f"Attempting to modify src_mac_entry_count to {src_mac_entry_count} "
            f"(name={traffic_item_name!r}, regex={traffic_item_regex!r})"
        )
        self.stop_traffic()
        if traffic_item_regex:
            traffic_item_obj = self.ixnetwork.Traffic.TrafficItem.find(
                Name=traffic_item_regex
            )
        else:
            traffic_item_obj = self.ixnetwork.Traffic.TrafficItem.find(
                Name=traffic_item_name
            )
        query = ixia_types.Query(
            regex="^ethernet$",
            query_type=ixia_types.QueryType.STACK_TYPE_ID,
        )
        fields = [
            ixia_types.Field(
                query=ixia_types.Query(regex="Source MAC Address"),
                attrs=[
                    ixia_types.Attr(
                        name="CountValue",
                        value=ixia_types.AttrValue(integer=src_mac_entry_count),
                    )
                ],
            ),
        ]
        packet_headers = [ixia_types.PacketHeader(query=query, fields=fields)]
        for packet_header in packet_headers:
            stack = self.find_or_create_stack(
                traffic_item_obj,
                query=packet_header.query,
                append_to_query=packet_header.append_to_query,
            )
            for header_field in none_throws(packet_header.fields):
                field_obj = stack.Field.find(
                    **{
                        ixia_types.QUERY_TYPE_MAP[
                            header_field.query.query_type
                        ]: header_field.query.regex
                    }
                )
                if not field_obj:
                    continue
                for attr in header_field.attrs:
                    if hasattr(field_obj, attr.name):
                        attr_value = attr.value.value
                        if attr.value.type in [
                            ixia_types.AttrValue.Type.integer_list,
                            ixia_types.AttrValue.Type.str_list,
                        ]:
                            attr_value = list(attr_value)  # pyre-ignore
                        setattr(field_obj, attr.name, attr_value)
            self.logger.info(
                f"Successfully created or modified packet header {packet_header.query.regex}"
            )
        traffic_item_obj.Enabled = True
        self.regenerate_traffic_items()
        self.start_traffic()

    @external_api
    def configure_bgp_peers_flap(
        self,
        regex: str,
        enable: t.Optional[bool] = None,
        uptime_in_sec: t.Optional[int] = None,
        downtime_in_sec: t.Optional[int] = None,
    ) -> None:
        """API to configure Bgp peer flap settings.

        Note: When enabling flap with new uptime/downtime values, the timing
        values must be set BEFORE enabling the flap for them to take effect
        immediately. The per-peer worker below sets uptime/downtime first,
        then enables flap.

        Per-peer property PATCHes are issued concurrently via
        ThreadPoolExecutor (mirroring `_apply_as_positions_concurrently`).
        Failed peers are retried sequentially. At BAG013/plane-aware scale
        (N peer containers, 3 properties each) this turns an O(N) serial wall
        clock into ~O(N/max_workers).

        Pain #1 Lever E — skip-if-already-converged: each per-property
        PATCH is gated on a `.Values[0]` read first; if the chassis already
        holds the desired value (with type-coerce-safe comparison), the
        PATCH is skipped. Saves wall-clock on repeated stage invocations
        where the same flap settings are re-applied (common on plane-aware
        oscillation stages). A per-call summary line at end-of-call reports
        `skipped/total` so the optimization is observable in worker logs
        without needing Scuba instrumentation.
        """
        from concurrent.futures import as_completed, ThreadPoolExecutor

        bgp_peers = self.find_bgp_peers(regex)
        if not bgp_peers:
            self.logger.info(
                f"configure_bgp_peers_flap: no BGP peer containers matched regex "
                f"{regex!r}; nothing to do"
            )
            return

        # Thread-safe write/skip counters — accessed from worker threads.
        skipped_writes = 0
        total_writes = 0
        counter_lock = threading.Lock()

        def _set_peer_flap_props(bgp_peer: t.Any) -> None:
            nonlocal skipped_writes, total_writes
            local_skipped = 0
            local_total = 0
            try:
                # Set uptime/downtime BEFORE enabling flap so new values take
                # effect immediately when flapping starts.
                if uptime_in_sec is not None:
                    local_total += 1
                    if not _set_multivalue_if_changed(
                        bgp_peer.UptimeInSec, uptime_in_sec
                    ):
                        local_skipped += 1
                if downtime_in_sec is not None:
                    local_total += 1
                    if not _set_multivalue_if_changed(
                        bgp_peer.DowntimeInSec, downtime_in_sec
                    ):
                        local_skipped += 1
                if enable is not None:
                    local_total += 1
                    if not _set_multivalue_if_changed(bgp_peer.Flap, enable):
                        local_skipped += 1
            finally:
                # Merge counters in `finally` so partial-progress writes are
                # accounted even when a worker raises mid-property. Without
                # this, a worker that wrote 2 of 3 properties then raised
                # would lose those writes from the counter; the sequential
                # retry would then see them already-converged and erroneously
                # count them as "skipped — already converged", inflating the
                # skip metric in the summary log.
                if local_total:
                    with counter_lock:
                        total_writes += local_total
                        skipped_writes += local_skipped

        max_workers = 10
        self.logger.info(
            f"configure_bgp_peers_flap: applying to {len(bgp_peers)} peer "
            f"containers concurrently (max_workers={max_workers}, "
            f"uptime={uptime_in_sec}, downtime={downtime_in_sec}, enable={enable})"
        )

        # Errors carry the peer OBJECT (not just its Name) — IxNetwork allows
        # two distinct BgpIpv4/v6Peer containers under different DGs to share
        # a Name, so a name-keyed retry could collapse them.
        errors: t.List[t.Tuple[t.Any, str]] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_set_peer_flap_props, peer): peer for peer in bgp_peers
            }
            for future in as_completed(futures):
                peer = futures[future]
                try:
                    future.result()
                except Exception as e:
                    errors.append((peer, str(e)))

        if errors:
            self.logger.warning(
                f"configure_bgp_peers_flap: {len(errors)} peer(s) failed during "
                f"concurrent application, retrying sequentially..."
            )
            for peer, err in errors[:5]:
                self.logger.warning(f"  {peer.Name}: {err}")
            retry_failures: t.List[t.Tuple[str, str]] = []
            for peer, _ in errors:
                try:
                    _set_peer_flap_props(peer)
                except Exception as e:
                    retry_failures.append((peer.Name, str(e)))
                    self.logger.warning(f"  {peer.Name} still failed after retry: {e}")
            if retry_failures:
                raise RuntimeError(
                    f"configure_bgp_peers_flap: {len(retry_failures)} peer(s) "
                    f"failed even after sequential retry: {retry_failures[:5]}"
                )

        self.apply_changes()
        self.logger.info(
            "BGP peer flap configuration changes applied successfully "
            f"({skipped_writes}/{total_writes} writes skipped — already converged)"
        )

    @external_api
    def activate_deactivate_bgp_prefix(
        self,
        network_group_name_regex: str,
        active: bool,
    ) -> None:
        """API to activate/deactivate BGP prefix settings.

        This sets the Active flag on BGP IP Route Properties within network groups
        matching the regex pattern. Setting Active=True advertises routes (BGP UPDATE),
        setting Active=False withdraws routes (BGP WITHDRAW).

        Args:
            network_group_name_regex: Regex pattern to match network group names
            active: True to activate (advertise), False to deactivate (withdraw)
        """
        # Use get_prefix_pools_by_regexes (same as configure_random_mask_prefixes)
        prefix_pools = self.get_prefix_pools_by_regexes(
            network_group_regex=network_group_name_regex
        )
        self.logger.info(
            f"Found {len(prefix_pools)} prefix pools matching '{network_group_name_regex}'"
        )

        for prefix_pool in prefix_pools:
            self.logger.info(f"Processing prefix pool: {prefix_pool.Name}")

            # Try IPv6 route property first, then IPv4
            bgp_route_props = None
            if hasattr(prefix_pool, "BgpV6IPRouteProperty"):
                bgp_route_props = prefix_pool.BgpV6IPRouteProperty.find()
            if not bgp_route_props and hasattr(prefix_pool, "BgpIPRouteProperty"):
                bgp_route_props = prefix_pool.BgpIPRouteProperty.find()

            if bgp_route_props:
                # Iterate over ALL BGP route properties
                for prop in bgp_route_props:
                    prop.Active.Single(value=active)
                    self.logger.info(
                        f"Updated Active={active} for {prop.Name} in {prefix_pool.Name}"
                    )
            else:
                self.logger.warning(
                    f"No BGP route property found for prefix pool: {prefix_pool.Name}"
                )

        self.apply_changes()
        self.logger.info(
            f"Successfully applied Active={active} changes for pattern '{network_group_name_regex}'"
        )

    def configure_prefix_length(
        self,
        bgp_prefix_config: ixia_types.BgpPrefixConfig,
        ip_prefix_pool_obj: t.Union["Ipv4PrefixPools", "Ipv6PrefixPools"],
    ) -> None:
        """
        For bgp_prefixes being advertised from ixia, this function determines
        whether all the prefixes are supposed to have a single / same values
        for their prefix lengths, or different prefix length
        values are expected for different bgp_prefixes. If multiple prefix
        lengths are expected, ixia used custom distribution function to
        determine that values and their respective weights.

        Refer https://pxl.cl/1VLDW to visualize how distributed function
        works.
        """
        # Use bgp_prefix_config.prefix_length when only a single value prefix is required.
        # Matching on prefix_length = 0 to support default route prefix
        if bgp_prefix_config.prefix_length or bgp_prefix_config.prefix_length == 0:
            ip_prefix_pool_obj.PrefixLength.Single(bgp_prefix_config.prefix_length)
        # When multiple value custom distribution is required use
        # bgp_prefix_config.distributed_prefix_length_config.prefix_length
        # Refer struct definitions in ixia_config_thrift.thrift for more details.
        elif (
            # pyre-ignore[16]: `Optional` has no attribute `prefix_length_value_weight_map`
            bgp_prefix_config.distributed_prefix_length_config.prefix_length_value_weight_map
        ):
            values_list = []
            # pyrefly: ignore [not-iterable]
            for val in bgp_prefix_config.distributed_prefix_length_config.prefix_length_value_weight_map:
                values_list.append(
                    (
                        val,
                        # pyrefly: ignore [bad-index]
                        bgp_prefix_config.distributed_prefix_length_config.prefix_length_value_weight_map[
                            val
                        ],
                    )
                )
            ip_prefix_pool_obj.PrefixLength.Distributed(
                algorithm=ixia_types.PREFIX_LENGTH_DISTRIBUTED_ALGORITHM_MAP[
                    # pyre-ignore[16]: `Optional` has no attribute `algorithm`.
                    bgp_prefix_config.distributed_prefix_length_config.algorithm
                ],
                mode=ixia_types.PREFIX_LENGTH_DISTRIBUTED_MODE_MAP[
                    # pyre-ignore[16]: `Optional` has no attribute `mode`.
                    bgp_prefix_config.distributed_prefix_length_config.mode
                ],
                values=values_list,
            )
        else:
            self.logger.critical(
                "No prefix length detail provided. Either provide prefix length or provide prefix_length_values along with alogrithm and mode for custom distribution"
            )

    @external_api
    def configure_advertised_prefixes(
        self,
        starting_ip: t.Optional[str] = None,
        prefix_length: t.Optional[int] = None,
        increment_ip: t.Optional[str] = None,
        network_group_regex: t.Optional[str] = None,
        prefix_pool_regex: t.Optional[str] = None,
    ) -> None:
        assert starting_ip or prefix_length or increment_ip, (
            "At least one of 'starting_ip', 'prefix_length' or 'increment_ip' is required"
        )
        prefix_pools = self.get_prefix_pools_by_regexes(
            network_group_regex, prefix_pool_regex
        )
        for prefix_pool in prefix_pools:
            if starting_ip or increment_ip:
                network_address = prefix_pool.NetworkAddress
                network_address.Pattern
                prefix_pool.NetworkAddress.Increment(
                    start_value=starting_ip
                    or network_address._properties["counter"]["start"],
                    step_value=increment_ip
                    or network_address._properties["counter"]["step"],
                )
                if starting_ip:
                    self.logger.debug(
                        f"Updated starting prefix for prefix pool {prefix_pool.Name} to {starting_ip}"
                    )
                if increment_ip:
                    self.logger.debug(
                        f"Updated increment ip prefix for prefix pool {prefix_pool.Name} to {starting_ip}"
                    )
            if prefix_length:
                prefix_pool.PrefixLength.Single(prefix_length)
                self.logger.debug(
                    f"Updated prefix length for prefix pool {prefix_pool.Name} to {prefix_length}"
                )
        self.apply_changes()

    @external_api
    def configure_random_mask_prefixes(
        self,
        fixed_value: str,
        mask_value: str,
        seed: int = 1,
        prefix_count: int = 1,
        prefix_length: t.Optional[int] = None,
        network_group_regex: t.Optional[str] = None,
        prefix_pool_regex: t.Optional[str] = None,
    ) -> None:
        """Configure prefixes using Random Mask pattern for non-contiguous distribution.

        This method sets the NetworkAddress pattern to RandomMask, which generates
        random prefixes based on fixed value and mask parameters. This is useful
        for simulating non-contiguous prefix distributions in production.

        Args:
            fixed_value: Fixed prefix value (e.g., "6000:0:0:0:0:0:0:0")
            mask_value: Mask determining which parts are randomized
                       (e.g., "0:ffff:ffff:0:0:0:0:0" for /48)
            seed: Random seed for reproducibility (default: 1)
            prefix_count: Number of prefixes to generate (default: 1)
            prefix_length: Prefix length/mask (e.g., 48, 64, 80, 128)
            network_group_regex: Regex to filter network groups
            prefix_pool_regex: Regex to filter prefix pools

        Example IXIA GUI equivalent:
            BGP IP Route Range -> Address -> Pattern: Random Mask
            Fixed: 6000:0:0:0:0:0:0:0
            Mask: 0:ffff:ffff:0:0:0:0:0
            Seed: 1
            Count: 1
        """
        prefix_pools = self.get_prefix_pools_by_regexes(
            network_group_regex, prefix_pool_regex
        )
        for prefix_pool in prefix_pools:
            network_address = prefix_pool.NetworkAddress
            network_address.RandomMask(
                fixed_value=fixed_value,
                mask_value=mask_value,
                seed=seed,
                count=prefix_count,
            )
            self.logger.debug(
                f"Set Random Mask pattern for prefix pool {prefix_pool.Name}: "
                f"fixed={fixed_value}, mask={mask_value}, seed={seed}, count={prefix_count}"
            )
            if prefix_length:
                prefix_pool.PrefixLength.Single(prefix_length)
                self.logger.debug(
                    f"Updated prefix length for prefix pool {prefix_pool.Name} to {prefix_length}"
                )
        self.apply_changes()

    @external_api
    def configure_bgp_prefixes_flap(
        self,
        network_group_regex: t.Optional[str] = None,
        prefix_pool_regex: t.Optional[str] = None,
        enable_flap: t.Optional[bool] = None,
        uptime_in_sec: t.Optional[int] = None,
        downtime_in_sec: t.Optional[int] = None,
    ) -> None:
        """API to configure Bgp prefix flap settings"""
        prefix_pools = self.get_prefix_pools_by_regexes(
            network_group_regex, prefix_pool_regex
        )
        for prefix_pool in prefix_pools:
            bgp_ip_route_property = prefix_pool.BgpIPRouteProperty.find()[0]
            if enable_flap is not None:
                bgp_ip_route_property.EnableFlapping.Single(value=enable_flap)
                self.logger.info(
                    f"Updated Flap setting to {'enabled' if enable_flap else 'disabled'} for {prefix_pool.Name}"
                )
            if uptime_in_sec is not None:
                bgp_ip_route_property.Uptime.Single(value=uptime_in_sec)
                self.logger.info(
                    f"Updated Flap uptime to {uptime_in_sec} seconds for {prefix_pool.Name}"
                )
            if downtime_in_sec is not None:
                bgp_ip_route_property.Downtime.Single(value=downtime_in_sec)
                self.logger.info(
                    f"Updated Flap downtime to {downtime_in_sec} seconds for {prefix_pool.Name}"
                )
        self.apply_changes()

    @external_api
    def bounce_bgp_next_hop_attribute(
        self,
        network_group_regex: t.Optional[str] = None,
        prefix_pool_regex: t.Optional[str] = None,
        enable: t.Optional[bool] = None,
    ) -> None:
        """API to configure Nexthop attribute enable/disable settings"""
        prefix_pools = self.get_prefix_pools_by_regexes(
            network_group_regex, prefix_pool_regex
        )
        for prefix_pool in prefix_pools:
            bgp_ip_route_property: "BgpIPRouteProperty" = (
                (prefix_pool.BgpIPRouteProperty.find())
                if isinstance(prefix_pool, Ipv4PrefixPools)
                else prefix_pool.BgpV6IPRouteProperty.find()
            )[0]
            if enable is not None:
                bgp_ip_route_property.EnableNextHop.Single(value=enable)
                self.logger.info(
                    f"Updated Enable Nexthop setting to {'enabled' if enable else 'disabled'} for {prefix_pool.Name}"
                )
        self.apply_changes()

    def get_prefix_pools_by_regexes(
        self,
        network_group_regex: t.Optional[str] = None,
        prefix_pool_regex: t.Optional[str] = None,
    ) -> t.List[t.Union["Ipv6PrefixPools", "Ipv4PrefixPools"]]:
        assert network_group_regex or prefix_pool_regex, (
            "At least one of network_group_regex and prefix_pool_regex is required"
        )
        prefix_pools_from_regex = []
        prefix_pools_from_network_groups = []
        if prefix_pool_regex:
            prefix_pools_from_regex = self.get_prefix_pools(prefix_pool_regex)
        if network_group_regex:
            network_groups = self.find_network_groups(network_group_regex)
            for network_group in network_groups:
                prefix_pools_from_network_groups.extend(
                    network_group.Ipv6PrefixPools.find()
                )
                prefix_pools_from_network_groups.extend(
                    network_group.Ipv4PrefixPools.find()
                )
        if network_group_regex and prefix_pool_regex:
            names_from_regex = {pool.Name for pool in prefix_pools_from_regex}
            names_from_network_groups = {
                pool.Name for pool in prefix_pools_from_network_groups
            }
            # Find the intersection of names
            common_names = names_from_regex.intersection(names_from_network_groups)
            prefix_pools = [
                pool
                for pool in prefix_pools_from_regex + prefix_pools_from_network_groups
                if pool.Name in common_names
            ]
        else:
            prefix_pools = prefix_pools_from_regex + prefix_pools_from_network_groups
        seen_names = set()
        unique_prefix_pools = [
            pool
            for pool in prefix_pools
            if pool.Name not in seen_names and not seen_names.add(pool.Name)
        ]
        return unique_prefix_pools

    @external_api
    def configure_bgp_prefixes(
        self,
        network_group_regex: t.Optional[str] = None,
        prefix_pool_regex: t.Optional[str] = None,
        prefix_count: t.Optional[int] = None,
        enable: t.Optional[bool] = None,
        session_start_idx: int = 1,
        session_end_idx: t.Optional[int] = None,
    ) -> None:
        prefix_pools = self.get_prefix_pools_by_regexes(
            network_group_regex, prefix_pool_regex
        )
        for prefix_pool in prefix_pools:
            if enable is not None:
                bgp_ip_route_property: "BgpIPRouteProperty" = (
                    (prefix_pool.BgpIPRouteProperty.find())
                    if isinstance(prefix_pool, Ipv4PrefixPools)
                    else prefix_pool.BgpV6IPRouteProperty.find()
                )[0]
                session_end_idx = session_end_idx or bgp_ip_route_property.Count
                if enable:
                    bgp_ip_route_property.Start(
                        SessionIndices=f"{session_start_idx}-{session_end_idx}"
                    )
                else:
                    bgp_ip_route_property.Stop(
                        SessionIndices=f"{session_start_idx}-{session_end_idx}"
                    )
            if prefix_count:
                prefix_pool.NumberOfAddresses = prefix_count
                self.logger.debug(
                    f"Updated prefix pool {prefix_pool.Name} prefix count to {prefix_count}"
                )
        self.apply_changes()

    def toggle_device_group(self, device_group, sleep_time_between_toggle_s) -> None:
        device_group.Enabled.Single(False)
        self.logger.info(
            f"Waiting {sleep_time_between_toggle_s} seconds for {device_group.Name} to disable"
        )
        time.sleep(sleep_time_between_toggle_s)
        # enable device group
        device_group.Enabled.Single(True)
        self.logger.info(
            f"Waiting {sleep_time_between_toggle_s} seconds for {device_group.Name} to ena"
        )
        time.sleep(sleep_time_between_toggle_s)

    def get_bgp_device_group_name(
        self, all_device_groups: t.List["DeviceGroup"]
    ) -> t.List[str]:
        bgp_device_group_name = []
        for device_group in all_device_groups:
            for ethernet in device_group.Ethernet.find():
                for ipv6 in ethernet.Ipv6.find():
                    bgp_peer = ipv6.BgpIpv6Peer.find()
                    if bgp_peer:
                        # Skip updating the ipv6 stack which has bgp sessions in it
                        bgp_device_group_name.append(device_group.Name)
                for ipv4 in ethernet.Ipv4.find():
                    bgp_peer = ipv4.BgpIpv4Peer.find()
                    if bgp_peer:
                        # Skip updating the ipv6 stack which has bgp sessions in it
                        bgp_device_group_name.append(device_group.Name)
        return bgp_device_group_name

    @external_api
    def configure_ipv6_entries(
        self,
        device_group_regex: t.Optional[str] = None,
        prefix_count: t.Optional[int] = None,
        toggle_all_ipv6_ipv4_only_protocol: bool = False,
        sleep_time_between_toggle_s: int = 30,
    ) -> None:
        """API to configure IPv6 entries"""
        if device_group_regex:
            device_groups = self.find_device_groups(device_group_regex)
            for device_group in device_groups:
                for ethernet in device_group.Ethernet.find():
                    for ipv6 in ethernet.Ipv6.find():
                        bgp_peer = ipv6.BgpIpv6Peer.find()
                        if bgp_peer:
                            # Skip updating the ipv6 stack which has bgp sessions in it
                            continue
                        if prefix_count:
                            f"Updating {device_group.Name} device multiplier to {prefix_count}"
                            device_group.update(Multiplier=prefix_count)
            self.apply_changes()

        if not toggle_all_ipv6_ipv4_only_protocol:
            return
        all_device_groups = self.find_device_groups()
        bgp_device_group_name = self.get_bgp_device_group_name(all_device_groups)
        for device_group in all_device_groups:
            if device_group.Name not in bgp_device_group_name:
                self.toggle_device_group(device_group, sleep_time_between_toggle_s)

        self.apply_changes()

    @external_api
    def configure_ipv4_entries(
        self,
        device_group_regex: str,
        prefix_count: t.Optional[int] = None,
        toggle_all_ipv6_ipv4_only_protocol: bool = False,
        sleep_time_between_toggle_s: int = 30,
    ) -> None:
        """API to configure IPv6 entries"""
        device_groups = self.find_device_groups(device_group_regex)
        for device_group in device_groups:
            for ethernet in device_group.Ethernet.find():
                for ipv4 in ethernet.Ipv4.find():
                    bgp_peer = ipv4.BgpIpv4Peer.find()
                    if bgp_peer:
                        # Skip updating the ipv6 stack which has bgp sessions in it
                        continue

                    if prefix_count:
                        self.logger.info(
                            f"Updating {device_group.Name} device multiplier to {prefix_count}"
                        )
                        device_group.update(Multiplier=prefix_count)
                        self.toggle_device_group(
                            device_group, sleep_time_between_toggle_s
                        )

        self.apply_changes()
        if not toggle_all_ipv6_ipv4_only_protocol:
            return
        all_device_groups = self.find_device_groups(device_group_regex)
        bgp_device_group_name = self.get_bgp_device_group_name(all_device_groups)
        for device_group in all_device_groups:
            if device_group.Name not in bgp_device_group_name:
                self.toggle_device_group(device_group, sleep_time_between_toggle_s)

        self.apply_changes()

    def create_bgp_prefixes(
        self,
        port_identifier: str,
        ip_address_family: ixia_types.IpAddressFamily,
        bgp_prefix_configs: t.Sequence[ixia_types.BgpPrefixConfig],
        device_group_obj: "DeviceGroup",
        device_group_index: DeviceGroupIndex,
    ) -> None:
        """Creates the BGP prefixes which would be advertised

        This checks for the presence of any existing NetworkGroup in
        associated with the given port identifier and prefix name. If
        found, it returns the IP instance of the BGP prefix else creates
        a new one. This involves addition of IP prefix pool and BGP IP
        route property. Various user-defined parameters, if present, are
        populated in the network group object.

        Args:
            port_identifier: Device name associated with the ixia port.
                For e.g., "rsw001.p004.f03.snc1" or
                "ixia01.netcastle.snc1.facebook.com_2_5" if ixia back to back
                port connection is used.
            ip_address_family: An object of type IpAddressFamily defining the IP
                version.
            bgp_prefix_configs: A list of type BgpPrefixConfig defining the
                various user-defined parameters to be populated into the topology.
            device_group_obj: A DeviceGroup object to which the Network Group is
                associated with.
            bgp_peer_obj: An object of type either BgpIpv4Peer or BgpIpv6Peer.
            update_network_object: A boolean flag to indicate if the existing
             network object needs to be updated or not.
        """

        for bgp_prefix_config in bgp_prefix_configs:
            """
            If the address type is given in the bgp prefix config, the network group
            and the ip_prefix_pools will be of the type mentioned in the bgp_prefix_config
            else address type will be pulled BGPConfig
            This is mainly doen to support advertising v4 prefixes over v6 peers and to support
            reverse compatibility
            """
            bgp_prefix_port_identifier = (
                f"N{bgp_prefix_config.network_group_index}_{port_identifier}"
            )

            bgp_prefix_family_type = (
                bgp_prefix_config.ip_address_family
                if bgp_prefix_config.ip_address_family
                else ip_address_family
            )
            if bgp_prefix_family_type == ixia_types.IpAddressFamily.IPV4:
                desired_bgp_prefix_name = DESIRED_V4_BGP_PREFIX_NAME.format(
                    port_identifier=bgp_prefix_port_identifier
                )
                prefix_pool_attr = "Ipv4PrefixPools"
            elif bgp_prefix_family_type == ixia_types.IpAddressFamily.IPV6:
                desired_bgp_prefix_name = DESIRED_V6_BGP_PREFIX_NAME.format(
                    port_identifier=bgp_prefix_port_identifier
                )
                prefix_pool_attr = "Ipv6PrefixPools"
            else:
                raise ValueError("Unsupported BGP prefix family type")

            if not (
                network_group_obj := device_group_obj.NetworkGroup.find(
                    Name=desired_bgp_prefix_name
                )
            ):
                network_group_obj = device_group_obj.NetworkGroup.add(
                    Multiplier=bgp_prefix_config.multiplier,
                    Name=desired_bgp_prefix_name,
                )
            network_group_index = NetworkGroupIndex(network_group=network_group_obj)
            device_group_index.network_group_indices[
                bgp_prefix_config.network_group_index
            ] = network_group_index
            self.logger.debug(
                f"Created a new {bgp_prefix_family_type.name} instance of the BGP prefix {desired_bgp_prefix_name}"
            )
            ip_prefix_pool_cls = getattr(network_group_obj, prefix_pool_attr)

            ip_prefix_pool_obj: t.Union["Ipv4PrefixPools", "Ipv6PrefixPools"] = (
                ip_prefix_pool_cls.add(NumberOfAddresses=bgp_prefix_config.count)
            )
            if bgp_prefix_config.prefix_pool_name:
                ip_prefix_pool_obj.Name = bgp_prefix_config.prefix_pool_name
            ip_prefix_pool_obj.NetworkAddress.Increment(
                start_value=bgp_prefix_config.starting_ip,
                step_value=bgp_prefix_config.increment_ip,
            )

            self.configure_prefix_length(bgp_prefix_config, ip_prefix_pool_obj)
            route_prop_obj: "BgpIPRouteProperty" = (
                (ip_prefix_pool_obj.BgpIPRouteProperty.add())
                if ip_address_family == ixia_types.IpAddressFamily.IPV4
                else (ip_prefix_pool_obj.BgpV6IPRouteProperty.add())
            )

            if bgp_prefix_config.prefix_flap_config:
                route_prop_obj.EnableFlapping.Single(value=True)
                route_prop_obj.Uptime.Single(
                    value=bgp_prefix_config.prefix_flap_config.uptime_in_sec
                )
                route_prop_obj.Downtime.Single(
                    value=bgp_prefix_config.prefix_flap_config.downtime_in_sec
                )
            # Add BGP community and related parameters, if present.
            bgp_ip_route_property = self.get_bgp_ip_route_property(
                desired_bgp_prefix_name,
                bgp_prefix_family_type,
                device_group_obj,
                ip_address_family,
            )
            if bgp_prefix_config.bgp_communities:
                # Enable the BGP community for the identified route property object
                self.change_bgp_community_state(
                    bgp_ip_route_property, bgp_community_flag=True
                )

                self.set_bgp_community_parameters(
                    bgp_ip_route_property,
                    bgp_prefix_port_identifier,
                    desired_bgp_prefix_name,
                    bgp_prefix_config.bgp_communities,
                    ip_address_family,
                )
                self.logger.debug(
                    f"[{bgp_prefix_port_identifier}] Successfully created the BGP "
                    f"community for {desired_bgp_prefix_name}"
                )

            # Add extended BGP community parameters, if present.
            if bgp_prefix_config.extended_bgp_communities:
                self.set_bgp_extended_community_parameters(
                    bgp_ip_route_property,
                    bgp_prefix_port_identifier,
                    desired_bgp_prefix_name,
                    bgp_prefix_config.extended_bgp_communities,
                    ip_address_family,
                )
                self.logger.debug(
                    f"[{bgp_prefix_port_identifier}] Successfully configured extended BGP "
                    f"communities for {desired_bgp_prefix_name}"
                )

            # Add AS Path prepend and related parameters, if present.
            if bgp_prefix_config.as_path_prepends:
                self.configure_as_path_prepends(
                    bgp_ip_route_property,
                    bgp_prefix_port_identifier,
                    desired_bgp_prefix_name,
                    bgp_prefix_config.as_path_prepends,
                    ip_address_family,
                )
                self.logger.debug(
                    f"[{bgp_prefix_port_identifier}] Successfully added the AS Path prepend "
                    f"attribute for {desired_bgp_prefix_name}"
                )

            self.logger.debug(
                f"[{bgp_prefix_port_identifier}] Successfully created the BGP prefix "
                f"{desired_bgp_prefix_name}"
            )
        self.logger.info(
            f"[{port_identifier}] Successfully created all the "
            f"{ip_address_family.name.upper()} BGP prefixes"
        )

    def flap_bgp_prefix(
        self,
        port_identifier: str,
        prefix_name: str,
        enable: bool,
        ip_version: ixia_types.IpAddressFamily,
    ) -> None:
        """
        Enables or disables network groups associated with BGP prefixes that are to
        be flapped to either withdraw or re-advertise. If enable is set, we enable
        the network group and advertise the associated prefixes in the network group.

        Args:
            port_identifier: Device name associated with the ixia port. For e.g.,
                "rsw001.p004.f03.snc1" or "ixia01.netcastle.snc1.facebook.com_2_5"
                if ixia back to back port connection is used.
            prefix_name: Name of the prefix pool to act on.
            enable: A boolean value representing whether to advertise or withdraw
                the prefixes associated with a network group with true representing
                advertise.
            ip_version: An enum defining the IP version. For e.g., ipv4 or ipv6.
        """

        prefix_action: str = "Advertising" if enable else "Withdrawing"
        network_group_action: str = "enabling" if enable else "disabling"

        device_group: "DeviceGroup" = self.find_device_group(port_identifier)

        network_group_name = self.get_network_group_name(
            port_identifier, prefix_name, ip_version
        )

        # Find Network Group object from Device Group object
        network_group = self.find_network_group(
            network_group_name,
            device_group,
        )
        # Enable or disable the network group object thereby advertising
        # or withdrawing the routes in the prefix pool associated with it
        network_group.Enabled.Single(value=enable)
        self.logger.info(
            f"{prefix_action} prefixes in {prefix_name} by {network_group_action} "
            f"{network_group_name}"
        )

    def find_network_group(
        self,
        network_group_name: str,
        device_group: "DeviceGroup",
    ) -> "NetworkGroup":
        """Finds the Network Group present for a given Device Group.

        This finds the Network Group associated with the given Device
        Group for a given IP version, port identifier and prefix name.
        """
        network_group: "NetworkGroup" = device_group.NetworkGroup.find(
            Name=network_group_name
        )
        if not network_group:
            raise NetworkGroupNotFoundError(
                "Network group object not found for the network group "
                f"name '{network_group_name}'"
            )
        return network_group

    def modify_network_group_multipliers(
        self,
        device_group: "DeviceGroup",
        network_group_name_to_multiplier_map: t.Dict[str, int],
    ) -> None:
        """Modifies network group multipliers within a device group.

        This method performs the following steps:
        1. Disables the device group
        2. Updates the network group multipliers based on the provided map
        3. Re-enables the device group

        Args:
            device_group: The DeviceGroup object containing the network groups
                to be modified.
            network_group_name_to_multiplier_map: Dictionary mapping network group
                names to their new multiplier values.

        Example:
            >>> device_group = self.find_device_group(port_identifier)
            >>> self.modify_network_group_multipliers(
            ...     device_group=device_group,
            ...     network_group_name_to_multiplier_map={
            ...         "network_group_3": 10,
            ...         "network_group_4": 20,
            ...     }
            ... )
        """
        device_group_name: str = device_group.Name

        # Step 1: Disable the device group
        self.logger.info(f"Disabling device group: {device_group_name}")
        device_group.Enabled.Single(False)
        self.apply_changes()

        # Wait for the device group to be disabled
        time.sleep(5)

        # Step 2: Update multipliers for specified network groups
        self.logger.info(
            f"Updating network group multipliers for device group: {device_group_name}"
        )
        for (
            network_group_name,
            new_multiplier,
        ) in network_group_name_to_multiplier_map.items():
            for network_group in device_group.NetworkGroup.find():
                if network_group.Name == network_group_name:
                    old_multiplier = network_group.Multiplier
                    self.logger.info(
                        f"Updating {network_group_name} multiplier from "
                        f"{old_multiplier} to {new_multiplier}"
                    )
                    network_group.Multiplier = new_multiplier
                    break
            else:
                self.logger.warning(
                    f"Network group '{network_group_name}' not found in "
                    f"device group '{device_group_name}'"
                )

        # Step 3: Re-enable the device group
        self.logger.info(f"Re-enabling device group: {device_group_name}")
        device_group.Enabled.Single(True)
        self.apply_changes()

        self.logger.info(
            f"Successfully updated network group multipliers for "
            f"device group: {device_group_name}"
        )

    def configure_custom_network_groups(
        self,
        custom_network_groups: t.List["ixia_types.CustomNetworkGroupConfig"],
        device_group_obj: "DeviceGroup",
        device_group_index: DeviceGroupIndex,
    ) -> None:
        """Configures custom network groups with ECMP width and nexthop settings.

        This method creates/updates network groups within a device group with
        custom prefix and nexthop configurations for ECMP testing. If a network
        group does not exist, it will be created with the specified configuration.

        Args:
            custom_network_groups: List of CustomNetworkGroupConfig configurations
                specifying the device group name, network group name, multiplier,
                prefix, nexthop, and ECMP width settings.
            device_group_obj: The DeviceGroup object to configure network groups in.
            device_group_index: DeviceGroupIndex to associate the network
                group with for traffic endpoint lookup.

        Example:
            >>> custom_configs = [
            ...     ixia_types.CustomNetworkGroupConfig(
            ...         device_group_name="test_device_group",
            ...         network_group_name="test_name",
            ...         network_group_multiplier=2048,
            ...         prefix_start_value="6000:ee:0:0:0:0:0:0",
            ...         prefix_length=64,
            ...         nexthop_start_value="2401:db00:e50d:1101:a:0:0:a000",
            ...         nexthop_increments="::1",
            ...         ecmp_width=63,
            ...         network_group_index=0,
            ...     ),
            ... ]
            >>> self.configure_custom_network_groups(custom_configs, device_group, device_group_index)
        """
        device_group_name: str = device_group_obj.Name
        for config in custom_network_groups:
            self.logger.info(
                f"Configuring custom network groups for device group: {device_group_name}"
            )

            network_groups = device_group_obj.NetworkGroup.find(
                Name=config.network_group_name
            )

            if not network_groups:
                # Create new network group if it doesn't exist
                self.logger.info(
                    f"Network group '{config.network_group_name}' not found in "
                    f"device group '{device_group_name}'. Creating new network group."
                )
                network_group = self._create_custom_network_group(
                    device_group_obj, config, device_group_index
                )
            else:
                # Update existing network group(s)
                for network_group in network_groups:
                    self._update_custom_network_group(network_group, config)

            self.logger.info(
                f"Configured network group '{config.network_group_name}' with "
                f"multiplier={config.network_group_multiplier}, "
                f"ecmp_width={config.ecmp_width}"
            )

    def _create_custom_network_group(
        self,
        device_group: "DeviceGroup",
        config: "ixia_types.CustomNetworkGroupConfig",
        device_group_index: DeviceGroupIndex,
    ) -> "NetworkGroup":
        """Creates a new custom network group with prefix pool and BGP route property.

        Args:
            device_group: The DeviceGroup object to create the network group in.
            config: CustomNetworkGroup configuration.
            device_group_index: DeviceGroupIndex to associate the network
                group with for traffic endpoint lookup.

        Returns:
            The created NetworkGroup object.
        """
        # Create network group
        network_group = device_group.NetworkGroup.add(
            Multiplier=config.network_group_multiplier,
            Name=config.network_group_name,
        )

        # Associate network group with device group index for traffic endpoint lookup
        network_group_index = NetworkGroupIndex(network_group=network_group)
        device_group_index.network_group_indices[config.network_group_index] = (
            network_group_index
        )

        # Create IPv6 prefix pool
        ip_prefix_pool = network_group.Ipv6PrefixPools.add(
            NumberOfAddresses=config.number_of_addresses_per_row
        )

        # Configure prefix pool network address with custom ECMP configuration.
        # Use zero step when multiple addresses per row so all devices in the
        # DG multiplier share the same prefix pool.
        prefix_step = getattr(
            config,
            "prefix_address_step",
            "::" if config.number_of_addresses_per_row > 1 else "0:0:1:0:0:0:0:0",
        )
        ip_prefix_pool.NetworkAddress.Custom(
            start_value=config.prefix_start_value,
            step_value=prefix_step,
            increments=[("::", config.ecmp_width, [])],
        )

        # Configure prefix length
        ip_prefix_pool.PrefixLength.Single(config.prefix_length)

        # Create BGP V6 IP Route Property
        bgp_route_prop = ip_prefix_pool.BgpV6IPRouteProperty.add()

        # Configure next hop settings
        bgp_route_prop.NextHopType.Single(config.next_hop_type)
        bgp_route_prop.NextHopIPType.Single(config.next_hop_ip_type)
        bgp_route_prop.NextHopIncrementMode.Single(config.next_hop_increment_mode)

        # Configure IPv6 next hop with custom ECMP configuration
        bgp_route_prop.Ipv6NextHop.Custom(
            start_value=config.nexthop_start_value,
            step_value="0:0:0:0:0:0:0:1",
            increments=[
                (
                    config.nexthop_increments,
                    config.ecmp_width,
                    [],
                )
            ],
        )

        # Configure BGP communities if provided
        if config.community_list:
            bgp_route_prop.EnableCommunity.Single(True)
            bgp_route_prop.NoOfCommunities = len(config.community_list)

            bgp_community_objs = bgp_route_prop.BgpCommunitiesList.find()

            if bgp_community_objs:
                for community_index, community_value in enumerate(
                    config.community_list
                ):
                    if community_index < len(bgp_community_objs):
                        bgp_community_obj = bgp_community_objs[community_index]

                        # Parse community value (e.g., "65001:100")
                        if ":" in community_value:
                            as_number, last_two_octets = community_value.split(":", 1)
                            bgp_community_obj.Type.Single("manual")
                            bgp_community_obj.AsNumber.Single(int(as_number))
                            bgp_community_obj.LastTwoOctets.Single(int(last_two_octets))
                        else:
                            self.logger.warning(
                                f"Invalid community format '{community_value}'. "
                                f"Expected format: 'AS:VALUE'"
                            )

        self.logger.debug(
            f"Created custom network group '{config.network_group_name}' with "
            f"prefix pool and BGP route property"
        )

        return network_group

    def _update_custom_network_group(
        self,
        network_group: "NetworkGroup",
        config: "ixia_types.CustomNetworkGroupConfig",
    ) -> None:
        """Updates an existing network group with custom ECMP configuration.

        Args:
            network_group: The NetworkGroup object to update.
            config: CustomNetworkGroup configuration.
        """
        # Update multiplier
        network_group.Multiplier = config.network_group_multiplier

        # Get IPv6 prefix pools
        ipv6_prefix_pools = network_group.Ipv6PrefixPools.find()

        for prefix_pool in ipv6_prefix_pools:
            # Set the network address custom configuration.
            # Use zero step when multiple addresses per row so all devices
            # in the DG multiplier share the same prefix pool.
            prefix_step = getattr(
                config,
                "prefix_address_step",
                "::" if config.number_of_addresses_per_row > 1 else "0:0:1:0:0:0:0:0",
            )
            prefix_pool.NetworkAddress.Custom(
                start_value=config.prefix_start_value,
                step_value=prefix_step,
                increments=[("::", config.ecmp_width, [])],
            )

            # Get BGP route property (assuming only one RouteObject)
            bgp_route_props = prefix_pool.BgpV6IPRouteProperty.find()
            if bgp_route_props:
                bgp_route_prop = bgp_route_props[0]
                # Set the IPv6 next hop custom configuration
                bgp_route_prop.Ipv6NextHop.Custom(
                    start_value=config.nexthop_start_value,
                    step_value="0:0:0:0:0:0:0:1",
                    increments=[
                        (
                            config.nexthop_increments,
                            config.ecmp_width,
                            [],
                        )
                    ],
                )

    def _find_ip_prefix_pool(
        self,
        network_group: "NetworkGroup",
        network_group_name: str,
        ip_version: ixia_types.IpAddressFamily,
    ) -> t.Union["Ipv4PrefixPools", "Ipv6PrefixPools"]:
        """Finds the IP Prefix Pool present in a given Network Group.

        This finds the IP Prefix Pool associated with a given Network
        Group for a given IP version.

        Args:
            network_group: Given NetworkGroup object.
            network_group_name: String defining the name of the given NetworkGroup
                object.
            ip_version: An enum defining the IP version. For e.g., ipv4 or ipv6.

        Returns:
            ip_prefix_pool: An object either of type Ipv4PrefixPools or
                Ipv6PrefixPools depending on the given IP version.
        """

        ip_prefix_pool: t.Union["Ipv4PrefixPools", "Ipv6PrefixPools"] = (
            network_group.Ipv6PrefixPools.find()
            if ip_version == ixia_types.IpAddressFamily.IPV6
            else network_group.Ipv4PrefixPools.find()
        )

        if not ip_prefix_pool:
            raise IpPrefixPoolsNotFoundError(
                f"{ip_version.name.upper()} Prefix Pool not "
                f"found for the network group name '{network_group_name}'"
            )

        return ip_prefix_pool

    def get_network_group_name(
        self,
        port_identifier: str,
        prefix_name: str,
        ip_version: ixia_types.IpAddressFamily,
    ) -> str:
        network_group_name = (
            DESIRED_BGP_V6_PREFIX_NAME.format(
                port_identifier=port_identifier.upper(), prefix_name=prefix_name
            )
            if ip_version == ixia_types.IpAddressFamily.IPV6
            else DESIRED_BGP_V4_PREFIX_NAME.format(
                port_identifier=port_identifier.upper(), prefix_name=prefix_name
            )
        )
        return network_group_name

    def _find_bgp_route_property(
        self,
        device_group: "DeviceGroup",
        network_group_name: str,
        ip_version: ixia_types.IpAddressFamily,
        bgp_ip_route_property_addr_family: t.Optional[
            ixia_types.IpAddressFamily
        ] = None,
    ) -> t.Union["BgpIPRouteProperty", "BgpV6IPRouteProperty"]:
        """Finds the BGP IP Route Property for a given device group,
          network_group_name and IP version.

        Helps to find the BGP IP Route Property present under the IP prefix
        pool for a network group attached to a device group for a given IP
        version.

        Args:
            device_group: An object of DeviceGroup type.
            network_group_name: Name of the prefix pool to act on.
            ip_version: An enum defining the IP version of network_group and ip_prefix_pool. For e.g., ipv4 or ipv6.
            bgp_ip_route_property_addr_family: An enum defining the IP version of the bgp_ip_route object for the prefix_pool

        Returns:
            bgp_ip_route_property: An object either of type BgpIPRouteProperty or
                BgpV6IPRouteProperty depending on the given IP version.
        """
        if not bgp_ip_route_property_addr_family:
            bgp_ip_route_property_addr_family = ip_version

        network_group = self.find_network_group(
            network_group_name,
            device_group,
        )

        # Find the IP Prefix Pool in the Network Group.
        ip_prefix_pool: t.Union["Ipv4PrefixPools", "Ipv6PrefixPools"] = (
            self._find_ip_prefix_pool(network_group, network_group_name, ip_version)
        )

        # Find the BGP IP route property in the IP prefix pool.
        bgp_ip_route_property: t.Union["BgpIPRouteProperty", "BgpV6IPRouteProperty"] = (
            ip_prefix_pool.BgpV6IPRouteProperty.find()
            if bgp_ip_route_property_addr_family == ixia_types.IpAddressFamily.IPV6
            else ip_prefix_pool.BgpIPRouteProperty.find()
        )
        if not bgp_ip_route_property:
            raise BgpIPRoutePropertyNotFoundError(
                "BGP IP Route Property not found for network group name "
                f"'{network_group_name}' and {ip_version.name.upper()} "
                f"prefix pool '{ip_prefix_pool}'"
            )

        return bgp_ip_route_property

    def change_bgp_community_state(
        self,
        bgp_ip_route_property: t.Union["BgpIPRouteProperty", "BgpV6IPRouteProperty"],
        bgp_community_flag: bool,
    ) -> None:
        """Changes the BGP community state for a given BGP IP route property object

        For the given bgp route obj, it will enable/disable the BGP community based on
            bool arg given

        Args:
            bgp_ip_route_property: BGP route property obj on which communit will enabled or disabled
            bgp_community_flag: If true, it enables the BGP community in the network
                group, else disables it.
        """

        if bgp_community_flag:
            bgp_ip_route_property.EnableCommunity.Single(True)
        else:
            bgp_ip_route_property.EnableCommunity.Single(False)

    def get_bgp_ip_route_property(
        self,
        prefix_name: str,
        ip_version: ixia_types.IpAddressFamily,
        device_group_obj: "DeviceGroup",
        bgp_ip_route_property_addr_family: t.Optional[
            ixia_types.IpAddressFamily
        ] = None,
    ) -> t.Union["BgpIPRouteProperty", "BgpV6IPRouteProperty"]:
        """
        Args:
            port_identifier: Device name associated with the ixia port. For e.g.,
                "rsw001.p004.f03.snc1" or "ixia01.netcastle.snc1.facebook.com_2_5"
                if ixia back to back port connection is used.
            prefix_name: Name of the prefix pool to act on.
            ip_version: An enum defining the IP version of the network group and ip prefix pools. For e.g., ipv4 or ipv6.
            bgp_ip_route_property_addr_family: An enum defining the IP version of the bgp_ip_route object for the prefix_pool
        """
        if not bgp_ip_route_property_addr_family:
            bgp_ip_route_property_addr_family = ip_version
        return self._find_bgp_route_property(
            device_group_obj,
            prefix_name,
            ip_version,
            bgp_ip_route_property_addr_family,
        )

    def set_bgp_community_parameters(
        self,
        bgp_ip_route_property: t.Union["BgpIPRouteProperty", "BgpV6IPRouteProperty"],
        port_identifier: str,
        prefix_name: str,
        bgp_communities_config: t.Sequence[ixia_types.BgpCommunity],
        ip_version: ixia_types.IpAddressFamily,
    ) -> None:
        """Sets the BGP community parameters - Type, AS number and last two octets for
            a given network group within a topology.

        Sets the BGP community parameters (type, AS number and last two octets) for the
        given bgp_ip_route_property of network group present in the device group for a topology.

        Args:
            bgp_ip_route_property: bgp_ip_route_property for which the communities need to be set
            port_identifier: Device name associated with the ixia port. For e.g.,
                "rsw001.p004.f03.snc1" or "ixia01.netcastle.snc1.facebook.com_2_5"
                if ixia back to back port connection is used.
            prefix_name: Name of the prefix pool to act on.
            bgp_community_type: Defines the community type (Possible values- manual,
                noexport, noadvertised, noexport_subconfed, llgr_stale, no_llgr)
            as_number: Integer value AS number (eg., '65000' in '65000:100')
            last_two_octets: Integer value last two octets (eg., '100' in '65000:100')
            ip_version: An enum defining the IP version. For e.g., ipv4 or ipv6.
        """
        # Sets the BGP community list count for identified route property object
        bgp_ip_route_property.NoOfCommunities = len(bgp_communities_config)

        bgp_community_objs = bgp_ip_route_property.BgpCommunitiesList.find()

        if not bgp_community_objs:
            raise BgpCommunitiesListNotFoundError(
                "BGP Communities t.List associated with "
                f"{ip_version.name.upper()} not found for "
                f"port identifier '{port_identifier}' and prefix name "
                f"'{prefix_name}'"
            )

        # Updating the community values to the community objects
        for bgp_community, bgp_community_obj in zip(
            bgp_communities_config, bgp_community_objs
        ):
            bgp_community_obj.AsNumber.Single(bgp_community.as_number)
            bgp_community_obj.LastTwoOctets.Single(bgp_community.last_two_octets)
            bgp_community_obj.Type.Single(
                ixia_types.BGP_COMMUNITY_TYPE_MAP[bgp_community.bgp_community_type]
            )

        self.logger.info(
            f"[{port_identifier}] Successfully set the BGP community "
            "parameters - Type, AS number and last two octets associated "
            f"with {ip_version.name.upper()} for the port "
            f"identifier '{port_identifier}' and prefix_name '{prefix_name}' "
            "as requested by the user!"
        )

    def set_bgp_extended_community_parameters(
        self,
        bgp_ip_route_property: t.Union["BgpIPRouteProperty", "BgpV6IPRouteProperty"],
        port_identifier: str,
        prefix_name: str,
        bgp_ext_communities_config: t.Sequence[ixia_types.ExtendedBgpCommunity],
        ip_version: ixia_types.IpAddressFamily,
    ) -> None:
        """Sets the BGP extended community parameters for a given network group within a topology.

        Configures extended BGP communities (e.g. Link Bandwidth) on the
        bgp_ip_route_property of a network group present in the device group for a topology.

        The IXIA BgpExtendedCommunitiesList REST API exposes these Multivalue properties
        per extended community type:
            Link Bandwidth (sub_type=0x04):
                Type            -> "administratoras2octet"
                SubType         -> "linkbandwidth"
                AsNumber2Bytes  -> 2-octet Global Administrator (AS number)
                LinkBandwidth   -> 4-octet Local Administrator (bytes/sec, IEEE 754 float32)

        Args:
            bgp_ip_route_property: bgp_ip_route_property for which the extended
                communities need to be set.
            port_identifier: Device name associated with the ixia port.
            prefix_name: Name of the prefix pool to act on.
            bgp_ext_communities_config: Sequence of ExtendedBgpCommunity structs
                to configure on the route property.
            ip_version: An enum defining the IP version (ipv4 or ipv6).
        """
        bgp_ip_route_property.EnableExtendedCommunity.Single(True)

        # Pre-allocate extended community objects on the IXIA server, then
        # retrieve them with .find() — same pattern as NoOfCommunities for
        # regular communities (line 3619) and attribute profiles (line 6689).
        bgp_ip_route_property.NoOfExternalCommunities = len(bgp_ext_communities_config)
        bgp_ext_community_objs = bgp_ip_route_property.BgpExtendedCommunitiesList.find()

        if not bgp_ext_community_objs:
            raise BgpCommunitiesListNotFoundError(
                f"BGP Extended Communities List associated with "
                f"{ip_version.name.upper()} not found for "
                f"port identifier '{port_identifier}' and prefix name "
                f"'{prefix_name}'"
            )

        for ext_community, bgp_ext_comm_obj in zip(
            bgp_ext_communities_config, bgp_ext_community_objs
        ):
            if ext_community.type == ixia_types.ExtendedBgpCommunityType.LINK_BW:
                bgp_ext_comm_obj.Type.Single("administratoras2octetlinkbw")
                bgp_ext_comm_obj.SubType.Single(
                    _SUBTYPE_MAP.get(
                        ext_community.sub_type, str(ext_community.sub_type)
                    )
                )
                bgp_ext_comm_obj.AsNumber2Bytes.Single(ext_community.global_as_number)
                bgp_ext_comm_obj.LinkBandwidth.Single(ext_community.local_bw_value)

        self.logger.info(
            f"[{port_identifier}] Successfully set BGP extended community "
            f"parameters associated with {ip_version.name.upper()} for the port "
            f"identifier '{port_identifier}' and prefix_name '{prefix_name}'"
        )

    def configure_as_path_prepends(
        self,
        bgp_ip_route_property: t.Union["BgpIPRouteProperty", "BgpV6IPRouteProperty"],
        port_identifier: str,
        prefix_name: str,
        as_path_prepend_configs: t.Sequence[ixia_types.AsPathPrepend],
        ip_version: ixia_types.IpAddressFamily,
    ) -> None:
        """Enables AS Path prepending for bgp_ip_route_property of a given IP prefix pool.

        Args:
            bgp_ip_route_property: bgp_ip_route_property for which AS path prependong needs to be enabled
            port_identifier: Device name associated with the ixia port. For e.g.,
                "rsw001.p004.f03.snc1" or "ixia01.netcastle.snc1.facebook.com_2_5"
                if ixia back to back port connection is used.
            prefix_name: Name of the prefix pool to act on.
            as_numbers: Defines the AS numbers to be added in the AS path list.
                For e.g., [65000, 65000]. If list is empty, AsPathValuesNotFoundError
                is raised.
            ip_version: An enum defining the IP version. For e.g., ipv4 or ipv6.
        """

        # Set the flag as True to enable the AS Path Prepending
        self._configure_as_path_prepend(
            bgp_ip_route_property,
            port_identifier,
            prefix_name,
            ip_version,
            as_path_prepend_flag=True,
            as_path_prepend_configs=as_path_prepend_configs,
        )
        self.logger.info(
            f"[{port_identifier}] Successfully enabled the AS Path prepending "
            f"associated with {ip_version.name.upper()} "
            f"for the port identifier '{port_identifier}' and "
            f"prefix_name '{prefix_name}' as requested by the user!"
        )

    def _configure_as_path_prepend(
        self,
        bgp_ip_route_property: t.Union["BgpIPRouteProperty", "BgpV6IPRouteProperty"],
        port_identifier: str,
        prefix_name: str,
        ip_version: ixia_types.IpAddressFamily,
        as_path_prepend_flag: bool,
        as_path_prepend_configs: t.Optional[
            t.Sequence[ixia_types.AsPathPrepend]
        ] = None,
    ) -> None:
        """Changes the AS Path prepend for a given Network Group within a topology if
            as_path_prepend_flag is set to True and configures the given AS numbers,
            if present. Else, disables AS Path prepending.

        Sets the AS path prepend attribute of the BGP using the length of as_numbers
        and as_numbers itself, if as_path_prepend_flag is True else disbles it for the given bgp_ip_route_property.

        Args:
            bgp_ip_route_property: bgp_ip_route_property for which AS path prependong needs to be changed
            port_identifier: Device name associated with the ixia port. For e.g.,
                "rsw001.p004.f03.snc1" or "ixia01.netcastle.snc1.facebook.com_2_5"
                if ixia back to back port connection is used.
            prefix_name: Name of the prefix pool to act on.
            as_numbers: Defines the AS numbers to be added in the AS path prepend list.
                For e.g., [65000, 65000]. If list is empty, AsPathValuesNotFoundError
                is raised. Only present for enabling AS Path prepending.
            ip_version: An enum defining the IP version. For e.g., ipv4 or ipv6.
            as_path_prepend_flag: A boolean flag if set to True, sets the AS Path prepend
                attribute else disables it.

        Raises:
            AsPathValuesNotFoundError: Raised when AS numbers which need to be added for
                AS Path Prepending are not given.
        """
        if not as_path_prepend_flag:
            # Disable the AS Path segment
            bgp_ip_route_property.EnableAsPathSegments.Single(False)
        else:
            if not as_path_prepend_configs:
                raise AsPathValuesNotFoundError(
                    "AS Prepend Configs are not given, found an empty list! Please "
                    "ensure that atleast one AS number is provided in the "
                    "list of as_path_prepend_configs."
                )
            # Enable the AS Path segment
            bgp_ip_route_property.EnableAsPathSegments.Single(True)
            bgp_ip_route_property.NoOfASPathSegmentsPerRouteRange = len(
                as_path_prepend_configs
            )
            # Find the BGP AS Path Segment t.List in the BGP IP Route Property Group.
            bgp_as_path_segment_list = bgp_ip_route_property.BgpAsPathSegmentList.find()

            if not bgp_as_path_segment_list:
                raise BgpAsPathSegmentListNotFoundError(
                    "BGP AS Path Segment t.List associated with "
                    f"{ip_version.name.upper()} not "
                    f"found for port identifier '{port_identifier}' "
                    f"and prefix name '{prefix_name}'"
                )
            for i, as_path_prepend_config in enumerate(as_path_prepend_configs):
                bgp_as_path_segment = bgp_as_path_segment_list[i]
                as_numbers = as_path_prepend_config.as_numbers
                # Set segment type to AS_SEQUENCE instead of AS_SET
                # AS_SEQUENCE = ordered list (65403 64901)
                # AS_SET = unordered set {65403, 64901}
                bgp_as_path_segment.SegmentType.Single("asseq")
                bgp_as_path_segment.NumberOfAsNumberInSegment = len(as_numbers)
                # Add the AS Numbers in the AS Path prepend list.
                bgp_as_number_list = bgp_as_path_segment.BgpAsNumberList.find()
                for j, value in enumerate(as_numbers):
                    (bgp_as_number_list[j].AsNumber.Single(value))

    def create_bgp_stacks(
        self,
        port_identifier: str,
        bgp_config: ixia_types.BgpConfig,
        device_group_obj: "DeviceGroup",
        ip_address_obj: t.Union["Ipv4", "Ipv6"],
        device_group_index: DeviceGroupIndex,
        custom_network_group_configs: t.Optional[
            t.List["ixia_types.CustomNetworkGroupConfig"]
        ] = None,
    ) -> None:
        self.create_bgp_peer(
            port_identifier,
            bgp_config.ip_address_family,
            bgp_config.bgp_peer_config,
            ip_address_obj,
        )
        # If custom_network_group_configs is provided, use it and ignore bgp_prefix_configs
        if custom_network_group_configs:
            self.configure_custom_network_groups(
                custom_network_group_configs,
                device_group_obj,
                device_group_index=device_group_index,
            )
        elif bgp_config.bgp_prefix_configs:
            self.create_bgp_prefixes(
                port_identifier,
                bgp_config.ip_address_family,
                bgp_config.bgp_prefix_configs,
                device_group_obj,
                device_group_index=device_group_index,
            )
        if bgp_config.import_bgp_routes_params_list:
            self.import_bgp_routes(
                port_identifier,
                bgp_config.ip_address_family,
                bgp_config.import_bgp_routes_params_list,
                device_group_obj,
                device_group_index=device_group_index,
            )

    def is_traffic_running(self) -> bool:
        """API to get the current traffic state

        True is returned if the traffic has been started and is running
        through IXIA. Else, False is returned.

        Returns:
            A boolean to indicate the current traffic state.
        """

        traffic_flow_state: bool = self.ixnetwork.Traffic.IsTrafficRunning
        return traffic_flow_state

    @retryable(num_tries=100, sleep_time=2)
    @require_traffic_item
    def validate_traffic_flow_state(self, running: bool) -> None:
        """API used to validate the traffic flow state in a topology

        This API validates the traffic flow state in the topology
        by getting the current traffic state from the Ixia session
        and checking it against the expected state.
        """
        is_traffic_running = self.is_traffic_running()
        if running:
            assert is_traffic_running, "Traffic is not STARTED"
        else:
            assert not is_traffic_running, " Traffic is not STOPPED"

    @require_traffic_item
    @retryable(num_tries=15, sleep_time=5, debug=True)
    def start_traffic(self, regenerate_traffic_items: bool = False) -> None:
        """Controls starting the traffic items"""
        # If the traffic has already been started
        if self.is_traffic_running():
            self.logger.debug("[GLOBAL] Traffic has already been started and running!")  # noqa
            return
        regenerate_traffic_items and self.regenerate_traffic_items()
        self.apply_traffic()
        # If we call regular StartTraffic() and immediately the script for verifying
        # stats, the stats are not ready yet because the traffic has not completely
        # started yet.
        self.ixnetwork.Traffic.Start()
        self.validate_traffic_flow_state(running=True)
        self.traffic_items_start_time = time.time()
        self.logger.debug(
            "[GLOBAL] Successfully started all the traffic items in the IXIA setup!"
        )

    @require_traffic_item
    @retryable(num_tries=3, sleep_time=10, debug=True)
    def stop_traffic(self) -> None:
        """Controls stopping the traffic items with and/or without delays"""
        self.ixnetwork.Traffic.Stop()
        self.validate_traffic_flow_state(running=False)
        self.logger.info(
            "[GLOBAL] Successfully stopped all the traffic items in the IXIA setup!"
        )

    @require_traffic_item
    @retryable(num_tries=5, sleep_time=2, debug=False)
    @external_api
    def clear_traffic_stats(self, wait_for_refresh: bool = True) -> None:
        """
        API used to clear the port and traffic statistics
        Args:
            wait_for_refresh: do not return until there is a confirmation
            that all counters are cleared. It may take about 10 seconds to get
            refreshed counters.
        """

        kwargs = {"Arg1": ["waitForTrafficStatsRefresh"]} if wait_for_refresh else {}
        self.ixnetwork.ClearPortsAndTrafficStats(**kwargs)
        self.logger.info(
            "[GLOBAL] All the port and traffic statistics have been "
            "successfully cleared!"
        )

    @retryable(num_tries=3, sleep_time=2, debug=False)
    @external_api
    def clear_bgp_stats(self) -> None:
        """
        Clear BGP protocol statistics.

        This method clears all BGP protocol statistics, including updates sent/received,
        routes advertised/received, etc. It should be called before starting a BGP test
        to ensure that the statistics collected are only for the current test.
        """
        try:
            # Clear protocol statistics
            self.ixnetwork.ClearProtocolStats()
            self.logger.info(
                "[GLOBAL] All BGP protocol statistics have been successfully cleared!"
            )
        except Exception as e:
            self.logger.error(f"Error clearing BGP statistics: {str(e)}")

    def tear_down(self) -> None:
        """API used to tear down any existing session"""

        if self.session:
            if self.teardown_session:
                self.logger.debug(
                    "[GLOBAL] Attempting to tear down the Session ID "
                    f"{self.session_id} configured as {self.session_name} "
                    " as requested by the user..."
                )
                self.session.Session.remove()
                self.logger.info(
                    "[GLOBAL] Successfully tore down the session(s) "
                    "as requested by the user!"
                )
                return

            self.logger.info(
                f"[GLOBAL] Not tearing down the Session ID {self.session_id} as "
                "requested by the user!"
            )

        else:
            self.logger.warning(
                "No session object found and hence the tear down is a NO-OP"
            )

    @staticmethod
    def fetch_ixia_credentials(secret_name: str, secret_group: str) -> t.Optional[str]:
        """Fetches Ixia credentials. In OSS mode, reads from env/CSV. Internal uses keychain."""
        if TAAC_OSS:
            from taac.utils.oss_ixia_utils import (
                get_oss_ixia_password,
            )

            _username, password = get_oss_ixia_password()
            return password

        from taac.internal.internal_utils import (
            fetch_ixia_password_internal,
        )

        return fetch_ixia_password_internal()

    def configure_l1_settings(
        self,
        vport: t.Union["Vport", str],
        l1_config: ixia_types.L1Config,
    ) -> None:
        """Configures the L1 settings for the given vport"""
        if isinstance(vport, str):
            port_identifier = self.get_port_identifier(vport)
            desired_vport_name = DESIRED_VPORT_NAME.format(
                port_identifier=port_identifier
            )
            vport = self.ixnetwork.Vport.find(Name=desired_vport_name)
        else:
            port_identifier = vport.Name
        if l1_config.enable_fcoe:
            if "Fcoe" not in vport.L1Config.CurrentType:
                new_current_type = vport.L1Config.CurrentType + "Fcoe"
                vport.L1Config.CurrentType = new_current_type
                self.logger.debug(
                    f"Successfully configured L1Config CurrentType for {port_identifier} as {new_current_type}"
                )
            if l1_config.flow_control_config:
                fcoe = getattr(
                    vport.L1Config,
                    (
                        vport.L1Config.CurrentType[0].upper()
                        + vport.L1Config.CurrentType[1:]
                    ).replace("Fcoe", ""),
                ).Fcoe
                self.apply_flow_control_config(fcoe, l1_config.flow_control_config)
        else:
            if "Fcoe" in vport.L1Config.CurrentType:
                new_current_type = vport.L1Config.CurrentType.replace("Fcoe", "")
                vport.L1Config.CurrentType = new_current_type
                self.logger.debug(
                    f"Successfully configured L1Config CurrentType for {port_identifier} as {new_current_type}"
                )

    def start_and_verify_protocols(self) -> None:
        """Starts and verifies the protocols"""
        self.start_protocols()
        self._send_arp_and_ns()
        self.verify_protocols()

    def _send_arp_and_ns(self) -> None:
        """Send ARP (IPv4) and NS (IPv6) on all device group interfaces.

        After StartAllProtocols(), IXIA device groups may not respond to
        ARP requests from the DUT until explicit SendArp/SendNs is called.
        This ensures L2 address resolution completes for both V4 and V6.
        """
        for topology in self.ixnetwork.Topology.find():
            for device_group in topology.DeviceGroup.find():
                self._send_arp_ns_on_device_group(device_group)

    def _send_arp_ns_on_device_group(self, device_group: "DeviceGroup") -> None:
        """Send ARP/NS on a device group and its children recursively."""
        dg_name = device_group.Name
        for ethernet in device_group.Ethernet.find():
            for ipv4 in ethernet.Ipv4.find():
                try:
                    ipv4.SendArp()
                    self.logger.info(f"[{dg_name}] Sent ARP on IPv4 stack")
                except Exception as e:
                    self.logger.warning(f"[{dg_name}] SendArp failed (non-fatal): {e}")
            for ipv6 in ethernet.Ipv6.find():
                try:
                    ipv6.SendNs()
                    self.logger.info(f"[{dg_name}] Sent NS on IPv6 stack")
                except Exception as e:
                    self.logger.warning(f"[{dg_name}] SendNs failed (non-fatal): {e}")
        # Recurse into child device groups
        for child_dg in device_group.DeviceGroup.find():
            self._send_arp_ns_on_device_group(child_dg)

    def apply_flow_control_config(
        self, fcoe: "Fcoe", flow_control_config: ixia_types.FlowControlConfig
    ):
        if flow_control_config.flow_control_type:
            fcoe.FlowControlType = ixia_types.FLOW_CONTROL_TYPE_MAP[
                flow_control_config.flow_control_type
            ]
        if flow_control_config.enable_pfc_pause_delay:
            fcoe.EnablePFCPauseDelay = flow_control_config.enable_pfc_pause_delay
        if flow_control_config.pfc_prority_groups_config:
            fcoe.PfcPriorityGroups = [
                ixia_types.PFC_QUEUE_MAP[pfc_queue]
                for _, pfc_queue in flow_control_config.pfc_prority_groups_config
            ]

    def create_device_groups(
        self,
        port_identifier: str,
        device_group_configs: t.Sequence[ixia_types.DeviceGroupConfig],
        topology: "Topology",
    ) -> t.List["DeviceGroup"]:
        device_groups = []
        created_dgs_by_index: t.Dict[int, "DeviceGroup"] = {}

        # Get port index for unique MAC generation
        port_index = len(self.vport_indices)
        for idx, existing_port in enumerate(self.vport_indices.keys()):
            if existing_port == port_identifier:
                port_index = idx
                break

        for device_group_config in device_group_configs:
            device_group_port_identifier = (
                f"D{device_group_config.device_group_index}_{port_identifier}"
            )
            if device_group_config.tag_name:
                device_group_port_identifier += (
                    f"_{device_group_config.tag_name.upper()}"
                )
                # Pain #1 Lever A: this defaultdict is mutated from per-port
                # worker threads inside _build_topologies_and_device_groups_\
                # concurrently. `__getitem__` (defaultdict autoviv) + `.append`
                # is not atomic if two workers share the same `tag_name` —
                # both appends succeed but ordering and intermediate states
                # may interleave. Lock around the read-modify-write. Lazy
                # `getattr` keeps callers from the legacy single-threaded
                # path unaffected (no lock to acquire → no contention).
                _lock = getattr(self, "_tag_to_dg_lock", None)
                if _lock is not None:
                    with _lock:
                        self.tag_name_to_device_group_name_list[
                            device_group_config.tag_name
                        ].append(device_group_port_identifier)
                else:
                    self.tag_name_to_device_group_name_list[
                        device_group_config.tag_name
                    ].append(device_group_port_identifier)

            # Detect chained device group pattern: tag_name contains
            # "CHAINED_N" where N is the parent DG index.
            parent_device_group = None
            chained_parent_idx = None
            tag_upper = (device_group_config.tag_name or "").upper()
            match = re.search(r"CHAINED_(\d+)", tag_upper)
            if match:
                chained_parent_idx = int(match.group(1))
                parent_device_group = created_dgs_by_index.get(chained_parent_idx)
                if parent_device_group is None:
                    self.logger.warning(
                        f"[{port_identifier}] Chained DG references parent index "
                        f"{chained_parent_idx} but it has not been created yet. "
                        f"Creating as a top-level DG instead."
                    )

            # NDP handler pattern: create DG with multiplier=1 but IPv6
            # with multiplier=N. This allows a single device to handle NDP
            # for N IPv6 addresses, avoiding issues where multiplied devices
            # don't respond to NDP probes.
            is_ndp_handler = (
                device_group_config.tag_name
                and "NDP_HANDLER" in device_group_config.tag_name.upper()
            )
            dg_multiplier = 1 if is_ndp_handler else device_group_config.multiplier
            ipv6_multiplier = device_group_config.multiplier if is_ndp_handler else None
            device_group: "DeviceGroup" = self.create_device_group(
                device_group_port_identifier,
                dg_multiplier,
                topology,
                device_group_config.enable,
                device_group_config.device_group_name,
                parent_device_group=parent_device_group,
            )
            created_dgs_by_index[device_group_config.device_group_index] = device_group
            device_group_index = DeviceGroupIndex(device_group=device_group)
            self.vport_indices[port_identifier].device_group_indices[
                device_group_config.device_group_index
            ] = device_group_index

            ethernet: "Ethernet" = self.create_ethernet_group(
                device_group_port_identifier, device_group
            )

            # For chained DGs, set the Connector to point to the parent's
            # Ethernet stack so the chained DG uses the parent's resolved
            # L2/L3 sessions.
            if chained_parent_idx is not None and parent_device_group is not None:
                parent_dg_idx = self.vport_indices[
                    port_identifier
                ].device_group_indices.get(chained_parent_idx)
                if parent_dg_idx and parent_dg_idx.ethernet:
                    parent_ethernet = none_throws(parent_dg_idx.ethernet)
                    connector = ethernet.Connector.find()
                    if connector:
                        connector.update(ConnectedTo=parent_ethernet.href)
                    else:
                        ethernet.Connector.add(ConnectedTo=parent_ethernet.href)
                    self.logger.info(
                        f"[{port_identifier}] Chained DG "
                        f"{device_group_config.device_group_index} connector set "
                        f"to parent DG {chained_parent_idx} Ethernet stack"
                    )

            # MAC address configuration for multiplied device groups:
            # - NDP_HANDLER: Uses same MAC for all (single device with multiple IPs)
            # - Other device groups: Increment MAC for each device
            # Use unique starting MAC per port/DG to avoid collisions
            if device_group_config.multiplier > 1:
                # Generate unique starting MAC based on port and DG index
                # Format: 00:11:PP:DD:00:01 where PP=port_index, DD=dg_index
                dg_idx = device_group_config.device_group_index
                start_mac = f"00:11:{port_index:02x}:{dg_idx:02x}:00:01"
                if is_ndp_handler:
                    # NDP handler: single device responds for multiple IPs
                    ethernet.Mac.Increment(
                        start_value=start_mac,
                        step_value="00:00:00:00:00:00",
                    )
                else:
                    # Multiple devices: each needs unique MAC
                    ethernet.Mac.Increment(
                        start_value=start_mac,
                        step_value="00:00:00:00:00:01",
                    )
            device_group_index.ethernet = ethernet
            ip_addr_res = None
            if device_group_config.ip_addresses_config:
                self.logger.info(
                    f"{_CYAN}[IXIA]{_RESET}       Configuring IP addresses"
                )
                ip_addr_res = self.assign_ip_adddress(
                    device_group_port_identifier,
                    device_group_config.ip_addresses_config,
                    ethernet,
                    device_group_index,
                    ipv6_multiplier=ipv6_multiplier,
                )
                if (
                    (bgp_config := device_group_config.bgp_config)
                    and not bgp_config.bgp_v4_config
                    and not bgp_config.bgp_v6_config
                ):
                    self.logger.info(
                        f"{_CYAN}[IXIA]{_RESET}       IP-only stack — applying configs"
                    )

                    ipv4 = self.ixnetwork.Globals.Topology.Ipv4
                    ipv4.Name = "Ipv4GlobalAndPortData"
                    ipv4.SuppressArpForDuplicateGateway.Single(False)

                    ipv6 = self.ixnetwork.Globals.Topology.Ipv6
                    ipv6.Name = "Ipv6GlobalAndPortData"
                    ipv6.SuppressNsForDuplicateGateway.Single(False)

                    self.apply_changes()
            if device_group_config.bgp_config:
                ip_addr_res = none_throws(ip_addr_res)
                if bgp_v4_config := device_group_config.bgp_config.bgp_v4_config:
                    bgp_v4_as = getattr(bgp_v4_config.bgp_peer_config, "local_as", "?")
                    self.logger.info(
                        f"{_CYAN}[IXIA]{_RESET}       BGPv4 peer (AS {bgp_v4_as})"
                    )
                    self.create_bgp_stacks(
                        device_group_port_identifier,
                        bgp_v4_config,
                        device_group,
                        ip_addr_res.ipv4,
                        device_group_index,
                        custom_network_group_configs=(
                            list(bgp_v4_config.custom_network_group_configs)
                            if bgp_v4_config.custom_network_group_configs
                            else None
                        ),
                    )
                if bgp_v6_config := device_group_config.bgp_config.bgp_v6_config:
                    bgp_v6_as = getattr(bgp_v6_config.bgp_peer_config, "local_as", "?")
                    self.logger.info(
                        f"{_CYAN}[IXIA]{_RESET}       BGPv6 peer (AS {bgp_v6_as})"
                    )
                    self.create_bgp_stacks(
                        device_group_port_identifier,
                        bgp_v6_config,
                        device_group,
                        ip_addr_res.ipv6,
                        device_group_index,
                        custom_network_group_configs=(
                            list(bgp_v6_config.custom_network_group_configs)
                            if bgp_v6_config.custom_network_group_configs
                            else None
                        ),
                    )
            device_groups.append(device_group)
        # Snapshot the tag→DG mapping under the lock — without this,
        # `dict(...)` racing against a concurrent `defaultdict.__getitem__` +
        # `list.append` in another worker (from
        # `_build_topologies_and_device_groups_concurrently`) can raise
        # `RuntimeError: dictionary changed size during iteration`. Inner
        # lists are also deep-copied via `list(v)` so the f-string `repr()`
        # below — which runs AFTER lock release — iterates frozen snapshots
        # rather than shared lists that another worker may still append to.
        # `getattr` keeps callers from the legacy single-threaded path
        # unaffected (lock absent → fall through to a plain dict comp).
        _lock = getattr(self, "_tag_to_dg_lock", None)
        if _lock is not None:
            with _lock:
                tag_to_dg_snapshot = {
                    k: list(v)
                    for k, v in self.tag_name_to_device_group_name_list.items()
                }
        else:
            tag_to_dg_snapshot = {
                k: list(v) for k, v in self.tag_name_to_device_group_name_list.items()
            }
        self.logger.info(
            f"{_DIM}[IXIA] Tag -> DG mapping: {tag_to_dg_snapshot}{_RESET}"
        )
        return device_groups

    @timeit
    @retryable(num_tries=3, sleep_time=30, print_ex=True)
    def _create_basic_setup(
        self,
        trial_traffic_interval_s=60,
    ) -> None:
        """
        Does the IXIA basic setup creation by connecting to an
        IXIA session or creates a new one followed by topology
        creation.
        """

        setup_start = time.time()
        # Use warning level so messages pass through suppress_console_logs
        _log = self.logger.warning

        # Reset the in-band-recovery budget for THIS attempt of
        # `_create_basic_setup`. The outer `@retryable(num_tries=3)` may call
        # us up to 3 times; on each call we get a fresh budget so a recovered
        # chassis isn't denied recovery on a later transient 5xx.
        self._ixia_recovery_attempts_remaining = (
            self.ixia_recovery.max_attempts if self.ixia_recovery else 1
        )

        # If a previous retry attempt created a session, destroy it before
        # starting fresh.  Reusing the same session via NewConfig() causes a
        # race condition: the old Connection's in-flight PATCH operations may
        # still be committing server-side when NewConfig() wipes the SDM
        # registry, leading to NullReferenceException in IxNetwork.
        if self.session_id and not self.is_existing_session:
            _log(
                f"{_YELLOW}[IXIA]{_RESET} Destroying session "
                f"{_YELLOW}{self.session_id}{_RESET} from previous failed "
                f"attempt before retry"
            )
            try:
                if self.session:
                    self.session.Session.remove()
            except Exception:
                pass
            self.session_id = None
            self.vport_indices = {}
            self.tag_name_to_device_group_name_list = defaultdict(list)
            self.ptp_configured = False

        _log(f"{_BG_BLUE}{_WHITE}{_BOLD} IXIA SETUP {_RESET}")

        # ── Step 1: Connect ──────────────────────────────────────
        _log(f"{_CYAN}{_BOLD}[1/7] Connecting to IXIA chassis...{_RESET}")
        _step_start = time.time()
        self.connect()
        _log(f"{_GREEN}[IXIA]{_RESET} Connected in {time.time() - _step_start:.0f}s")

        # if we connected to existing session, and didn't clean it up
        # check traffic to ensure it's not running
        if not self.cleanup_config and self.is_traffic_running():
            _log(f"{_YELLOW}[IXIA]{_RESET} Traffic was running — stopping it")
            self.stop_traffic()

        # If session ID of an existing session has been provided, following steps can be skipped
        if not self.is_existing_session:
            port_configs: t.Optional[t.Sequence[ixia_types.PortConfig]] = none_throws(
                self.ixia_config
            ).port_configs

            # ── Step 2: Assign ports ─────────────────────────────
            _log(
                # pyrefly: ignore [bad-argument-type]
                f"{_CYAN}{_BOLD}[2/7] Assigning {len(port_configs)} port(s)...{_RESET}"
            )
            _step_start = time.time()
            # pyrefly: ignore [bad-argument-type]
            self.assign_ports(port_configs)
            _log(
                f"{_GREEN}[IXIA]{_RESET} Ports assigned in {time.time() - _step_start:.0f}s"
            )

            # ── Step 3: Topologies & device groups ───────────────
            _log(
                # pyrefly: ignore [bad-argument-type]
                f"{_CYAN}{_BOLD}[3/7] Creating topologies & device groups "
                f"({len(port_configs)} port(s))...{_RESET}"
            )
            _step_start = time.time()
            # pyrefly: ignore [not-iterable, bad-argument-type]
            self._build_topologies_and_device_groups_concurrently(port_configs, _log)
            _log(
                f"{_GREEN}[IXIA]{_RESET} Topologies & device groups created in "
                f"{time.time() - _step_start:.0f}s"
            )

            # ── Step 4: PTP & chassis config ─────────────────────
            _log(f"{_CYAN}{_BOLD}[4/7] PTP setup & chassis configuration...{_RESET}")
            _step_start = time.time()
            self.create_ptp_setup()
            _log(
                f"{_GREEN}[IXIA]{_RESET} PTP setup done in {time.time() - _step_start:.0f}s"
            )
            _step_start = time.time()
            self.configure_ixia_chassis()
            _log(
                f"{_GREEN}[IXIA]{_RESET} Chassis configured in {time.time() - _step_start:.0f}s"
            )
        else:
            _log(
                f"{_DIM}[IXIA] Steps 2-4 skipped — "
                f"reusing existing session ID {self.session_id}{_RESET}"
            )

        # ── Step 5: Verify & start protocols ─────────────────────
        _log(f"{_CYAN}{_BOLD}[5/7] Verifying IP ranges & starting protocols...{_RESET}")
        _step_start = time.time()
        self.verify_ip_advertise_gating()
        _log(
            f"{_GREEN}[IXIA]{_RESET} IP range verification done in "
            f"{time.time() - _step_start:.0f}s"
        )
        _step_start = time.time()
        self.start_and_verify_protocols()
        _log(
            f"{_GREEN}[IXIA]{_RESET} Protocols started and verified in "
            f"{time.time() - _step_start:.0f}s"
        )

        ixia_config = self.ixia_config
        if (
            ixia_config
            and ixia_config.traffic_items
            and
            # Traffic items for an existing session are already present
            (not self.is_existing_session or self.override_traffic_items)
        ):
            # ── Step 6: Traffic items ────────────────────────────
            traffic_items = ixia_config.traffic_items
            num_items = len(traffic_items)
            _log(f"{_CYAN}{_BOLD}[6/7] Creating {num_items} traffic item(s)...{_RESET}")
            _step_start = time.time()
            self.create_traffic_items(traffic_items)
            _log(
                f"{_GREEN}[IXIA]{_RESET} {num_items} traffic item(s) created in "
                f"{time.time() - _step_start:.0f}s"
            )

            # ── Step 7: Trial traffic ────────────────────────────
            _log(
                f"{_CYAN}{_BOLD}[7/7] Trial traffic for ARP/NDP resolution "
                f"({trial_traffic_interval_s}s)...{_RESET}"
            )
            _step_start = time.time()
            self.start_traffic()
            _log(f"{_DIM}[IXIA] Waiting {trial_traffic_interval_s}s...{_RESET}")
            time.sleep(trial_traffic_interval_s)
            self.stop_traffic()
            _log(
                f"{_GREEN}[IXIA]{_RESET} Trial traffic complete in "
                f"{time.time() - _step_start:.0f}s"
            )
        else:
            _log(f"{_DIM}[IXIA] Steps 6-7 skipped — no traffic items to create{_RESET}")

        total_elapsed = time.time() - setup_start
        _log(
            f"\n{_GREEN}{_BOLD}[IXIA] Setup complete in {total_elapsed:.0f}s{_RESET}\n"
        )

    def _build_topologies_and_device_groups_concurrently(
        self,
        port_configs: t.Sequence[ixia_types.PortConfig],
        _log: t.Callable[[str], None],
    ) -> None:
        """Build Step 3 (topologies + device groups + optional L1) in parallel
        across ports.

        Each port is independent — vports are distinct SDM nodes, topologies
        are scoped per-vport, and `self.vport_indices[port_identifier]` only
        writes to a per-port-keyed entry (different keys → no dict contention).
        Single-attempt parallel: a port failure raises `IxiaSetupError`
        (from `_create_basic_setup`'s wrapper at `create_basic_setup`,
        line 4729), which the wrapper handles by tearing down the whole
        session when `cleanup_failed_setup=True`. We DELIBERATELY do not
        retry per-port like `_apply_as_positions_concurrently` does:
        `create_device_groups` is non-idempotent (multi-step DG creation +
        appends to `tag_name_to_device_group_name_list`), so a retry after
        a mid-step failure would produce duplicate DGs and duplicate dict
        entries. Fail fast → let the session-level cleanup recover.

        Thread safety:
          * `self.vport_indices[port_identifier].topology_name = ...`
            writes a per-port-keyed attribute; ports never collide on the
            same key. `_vport_indices_lock` guards the write for paranoia.
          * `self.tag_name_to_device_group_name_list[tag].append(...)`
            inside `create_device_groups` is guarded by `_tag_to_dg_lock`
            (acquired in `create_device_groups` itself, not here). Lock
            init is lazy so callers from the legacy non-parallel path get
            no lock-acquisition overhead.

        Determinism note: insertion order of values in
        `tag_name_to_device_group_name_list[tag]` is non-deterministic
        across runs (worker thread completion order varies). Verified
        2026-06-05 via grep that no consumer iterates these lists in an
        order-sensitive way — only `__contains__` checks at `ixia.py:2400`
        and dict-level pop+rewrite at `2401-2404`. If you add a new
        consumer that needs deterministic order, sort by port name at
        read time.
        """
        # Lazy lock init keeps the refactor self-contained — no constructor
        # change, no risk of breaking subclasses that override __init__.
        if not hasattr(self, "_vport_indices_lock"):
            self._vport_indices_lock = threading.Lock()
        if not hasattr(self, "_tag_to_dg_lock"):
            self._tag_to_dg_lock = threading.Lock()

        def _build_one_port(port: ixia_types.PortConfig) -> None:
            port_identifier: str = Ixia.get_port_identifier(port.port_name)
            _log(f"{_MAGENTA}[IXIA]{_RESET} Port {_BOLD}{port_identifier}{_RESET}")
            desired_vport_name: str = DESIRED_VPORT_NAME.format(
                port_identifier=port_identifier
            )
            vport = self.ixnetwork.Vport.find(Name=desired_vport_name)
            topology = self.create_topology(port_identifier, vport)
            with self._vport_indices_lock:
                self.vport_indices[port_identifier].topology_name = topology.Name
            dg_configs = none_throws(port.device_group_configs)
            _log(
                f"{_CYAN}[IXIA]{_RESET}   "
                f"Creating {_YELLOW}{len(dg_configs)}{_RESET} device group(s) "
                f"for {port_identifier}..."
            )
            _dg_start = time.time()
            self.create_device_groups(port_identifier, dg_configs, topology)
            _log(
                f"{_GREEN}[IXIA]{_RESET}   "
                f"Device groups for {port_identifier} created in "
                f"{time.time() - _dg_start:.0f}s"
            )
            if port.l1_config:
                _log(
                    f"{_CYAN}[IXIA]{_RESET}   Configuring L1 settings "
                    f"for {port_identifier}"
                )
                self.configure_l1_settings(vport, port.l1_config)

        max_workers = 10
        port_count = len(port_configs)
        _log(
            f"{_DIM}[IXIA] Building {port_count} port(s) concurrently "
            f"(max_workers={max_workers}){_RESET}"
        )

        errors: t.List[t.Tuple[ixia_types.PortConfig, str]] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_build_one_port, p): p for p in port_configs}
            for future in as_completed(futures):
                port = futures[future]
                try:
                    future.result()
                except Exception as e:
                    errors.append((port, repr(e)))

        if errors:
            # Single-attempt — no retry. `create_device_groups` is non-
            # idempotent (multi-step + tag-list appends), so retrying a
            # partially-failed port would create duplicate DGs / duplicate
            # tag entries. Let the outer wrapper tear down the whole
            # session and let the test framework retry at a higher level.
            for port, err in errors[:5]:
                self.logger.warning(
                    f"  {Ixia.get_port_identifier(port.port_name)}: {err}"
                )
            raise RuntimeError(
                f"Parallel topology setup failed for {len(errors)} port(s); "
                f"first failures: {[(Ixia.get_port_identifier(p.port_name), e) for p, e in errors[:5]]}"
            )

    def create_basic_setup(self) -> None:
        """Creates the basic IXIA setup"""

        try:
            self._create_basic_setup()
        except Exception as ex:
            if self.cleanup_failed_setup and not self.is_existing_session:
                self.tear_down()
            raise IxiaSetupError(
                f"IXIA setup configuration failed with the following error: {ex}"
            )

    def find_network_groups(
        self, regex: t.Optional[str] = None, ignore_case: bool = False
    ) -> t.List["NetworkGroup"]:
        network_groups = []
        topologies = self.ixnetwork.Topology.find()
        for topology in topologies:
            for device_group in topology.DeviceGroup.find():
                self._collect_network_groups(device_group, network_groups)
        if regex:
            network_groups = [
                network_group
                for network_group in network_groups
                if re.search(
                    regex, network_group.Name, re.IGNORECASE if ignore_case else 0
                )
            ]
        return network_groups

    def _collect_network_groups(
        self,
        device_group: "DeviceGroup",
        network_groups: t.List["NetworkGroup"],
    ) -> None:
        for network_group in device_group.NetworkGroup.find():
            network_groups.append(network_group)
        for child_dg in device_group.DeviceGroup.find():
            self._collect_network_groups(child_dg, network_groups)

    def find_device_groups(
        self, regex: t.Optional[str] = None, ignore_case: bool = False
    ) -> t.List["DeviceGroup"]:
        device_groups = []
        topologies = self.ixnetwork.Topology.find()
        for topology in topologies:
            for device_group in topology.DeviceGroup.find():
                self._collect_device_groups(device_group, device_groups)
        if regex:
            device_groups = [
                device_group
                for device_group in device_groups
                if re.search(
                    regex, device_group.Name, re.IGNORECASE if ignore_case else 0
                )
            ]
        return device_groups

    def _collect_device_groups(
        self,
        device_group: "DeviceGroup",
        device_groups: t.List["DeviceGroup"],
    ) -> None:
        device_groups.append(device_group)
        for child_dg in device_group.DeviceGroup.find():
            self._collect_device_groups(child_dg, device_groups)

    def find_bgp_peers(
        self, regex: t.Optional[str] = None, ignore_case: bool = False
    ) -> t.List[t.Union["BgpIpv6Peer", "BgpIpv4Peer"]]:
        """Finds BGP peers in the IXIA setup"""
        all_device_groups = self.find_device_groups()
        bgp_peers = []
        for device_group in all_device_groups:
            for ethernet in device_group.Ethernet.find():
                for ipv6 in ethernet.Ipv6.find():
                    bgp_peer = ipv6.BgpIpv6Peer.find()
                    if not bgp_peer:
                        continue
                    bgp_peers.append(bgp_peer)
                for ipv4 in ethernet.Ipv4.find():
                    bgp_peer = ipv4.BgpIpv4Peer.find()
                    if not bgp_peer:
                        continue
                    bgp_peers.append(bgp_peer)
        self.logger.info(
            f"Prefilter BGP Peer: {[bgp_peer.Name for bgp_peer in bgp_peers]}"
        )
        if regex:
            bgp_peers = [
                bgp_peer
                for bgp_peer in bgp_peers
                if re.search(regex, bgp_peer.Name, re.IGNORECASE if ignore_case else 0)
            ]
            self.logger.info(
                f"Postfilter BGP Peer: {[bgp_peer.Name for bgp_peer in bgp_peers]}"
            )
        return bgp_peers

    def find_bgp_ipv6_peer(self, port_identifier: str) -> t.Optional["BgpIpv6Peer"]:
        """Finds the BGP peer in the IXIA setup"""
        ipv6 = self.find_ipv6(port_identifier)
        if not ipv6:
            return
        bgp_peer = ipv6.BgpIpv6Peer.find(
            Name=DESIRED_BGP_V6_PEER_NAME.format(port_identifier=port_identifier)
        )
        if bgp_peer:
            return bgp_peer[0]

    def restart_bgp_peers(self, regexes: t.Optional[t.List[str]] = None) -> None:
        bgp_peers_to_restart = []
        all_bgp_peers = self.find_bgp_peers()
        if regexes:
            for bgp_peer in all_bgp_peers:
                for regex in regexes:
                    if re.match(regex, bgp_peer.Name):
                        bgp_peers_to_restart.append(bgp_peer)
        else:
            bgp_peers_to_restart = all_bgp_peers
        self.logger.info(
            f"Restarting BGP peers {[bgp_peer.Name for bgp_peer in bgp_peers_to_restart]} as requested by the user."
        )
        for bgp_peer in bgp_peers_to_restart:
            bgp_peer.Stop(SessionIndices=f"1-{bgp_peer.Count}")
            bgp_peer.Start(SessionIndices=f"1-{bgp_peer.Count}")

    def find_ipv6s(
        self, regex: t.Optional[str] = None, ignore_case: bool = False
    ) -> t.List["Ipv6"]:
        """Finds all the IPv6 objects in the IXIA setup"""
        ipv6s = []
        topologies = self.ixnetwork.Topology.find()

        for topology in topologies:
            for device_group in topology.DeviceGroup.find():
                for ethernet in device_group.Ethernet.find():
                    for ipv6 in ethernet.Ipv6.find():
                        ipv6s.append(ipv6)

        matched_ipv6s = []
        if regex:
            matched_ipv6s = [
                ipv6
                for ipv6 in ipv6s
                if re.search(regex, ipv6.Name, re.IGNORECASE if ignore_case else 0)
            ]

        return matched_ipv6s

    def find_ipv4s(
        self, regex: t.Optional[str] = None, ignore_case: bool = False
    ) -> t.List["Ipv4"]:
        """Finds all the IPv4 objects in the IXIA setup"""
        ipv4s = []
        topologies = self.ixnetwork.Topology.find()
        for topology in topologies:
            for device_group in topology.DeviceGroup.find():
                for ethernet in device_group.Ethernet.find():
                    for ipv4 in ethernet.Ipv4.find():
                        ipv4s.append(ipv4)
        if regex:
            ipv4s = [
                ipv4
                for ipv4 in ipv4s
                if re.search(regex, ipv4.Name, re.IGNORECASE if ignore_case else 0)
            ]
        return ipv4s

    def find_ipv6(self, port_identifier: str) -> t.Optional["Ipv6"]:
        topology = self.ixnetwork.Topology.find(
            Name=DESIRED_TOPOLOGY_NAME.format(port_identifier=port_identifier)
        )
        if not topology:
            self.logger.debug(f"Unable to find topology for the port {port_identifier}")
            return
        device_group = topology.DeviceGroup.find(
            Name=DESIRED_DEVICE_GROUP_NAME.format(port_identifier=port_identifier)
        )
        if not device_group:
            self.logger.debug(
                f"Unable to find device group for the port {port_identifier}"
            )
            return
        ethernet = device_group.Ethernet.find(
            Name=DESIRED_ETHERNET_NAME.format(port_identifier=port_identifier)
        )
        if not ethernet:
            self.logger.debug(f"Unable to find ethernet for the port {port_identifier}")
            return
        ipv6 = ethernet.Ipv6.find(
            Name=DESIRED_IPV6_NAME.format(port_identifier=port_identifier)
        )
        return ipv6

    def create_ptp_setup(
        self,
    ) -> None:
        ptp_configs = none_throws(self.ixia_config).ptp_configs
        if not ptp_configs:
            self.logger.info(
                "[GLOBAL] PTP config(s) is not provided. Skipping PTP setup."
            )
            return
        for ptp_config in ptp_configs:
            server_vport_index = self.vport_indices[
                self.get_port_identifier(ptp_config.server_endpoint.name)
            ]
            server_device_group_index = server_vport_index.device_group_indices[
                ptp_config.server_endpoint.device_group_index
            ]
            server_ipv6_obj = none_throws(server_device_group_index.ipv6)
            self.create_ptp_stack(
                server_device_group_index.device_group.Name,
                ipv6=server_ipv6_obj,
                role="master",  # server
                communication_mode=ptp_config.communication_mode,
                step_mode=ptp_config.step_mode,
            )
            server_multiplier = server_device_group_index.device_group.Multiplier
            for client_endpoint in ptp_config.client_endpoints:
                client_vport_index = self.vport_indices[
                    self.get_port_identifier(client_endpoint.name)
                ]
                client_device_group_index = client_vport_index.device_group_indices[
                    client_endpoint.device_group_index
                ]
                client_ipv6_obj = none_throws(client_device_group_index.ipv6)
                server_address = server_ipv6_obj.Address
                server_address.Pattern
                server_starting_ip = server_address._properties["counter"]["start"]
                server_increment_ip = server_address._properties["counter"]["step"]
                client_multiplier = client_device_group_index.device_group.Multiplier
                # When slave count > master count, use round-robin assignment
                # so that slaves wrap around to available masters
                server_ip_list = None
                if client_multiplier > server_multiplier:
                    start_ip = ipaddress.IPv6Address(server_starting_ip)
                    step_int = int(ipaddress.IPv6Address(server_increment_ip))
                    server_ip_list = [
                        str(start_ip + (i % server_multiplier) * step_int)
                        for i in range(client_multiplier)
                    ]
                    self.logger.info(
                        f"[PTP] Client multiplier ({client_multiplier}) > server multiplier "
                        f"({server_multiplier}), using round-robin master IP assignment"
                    )
                self.create_ptp_stack(
                    client_device_group_index.device_group.Name,
                    ipv6=client_ipv6_obj,
                    role="slave",  # client
                    communication_mode=ptp_config.communication_mode,
                    step_mode=ptp_config.step_mode,
                    server_starting_ip=server_starting_ip,
                    server_increment_ip=server_increment_ip,
                    server_ip_list=server_ip_list,
                )

    def create_ptp_stack(
        self,
        device_group_name: str,
        ipv6: "Ipv6",
        role: str,
        communication_mode: ixia_types.PTPCommunicationMode,
        step_mode: ixia_types.PTPStepMode,
        server_starting_ip: t.Optional[str] = None,
        server_increment_ip: t.Optional[str] = None,
        server_ip_list: t.Optional[t.List[str]] = None,
    ) -> None:
        communication_mode_str = ixia_types.PTP_COMMUNICATION_MODE_MAP[
            communication_mode
        ]
        step_mode_str = ixia_types.PTP_STEP_MODE_MAP[step_mode]
        self.logger.info(
            f"[{device_group_name}] Creating PTP stack with the configurations: role = {role}, "
            f"communication mode = {communication_mode_str}, step mode = {step_mode_str}"
        )
        desired_ipv6_ptp_name: str = DESIRED_IPV6_PTP_NAME.format(
            port_identifier=device_group_name
        )
        if ipv6.Ptp.find(Name=desired_ipv6_ptp_name):
            self.logger.info(
                f"[{device_group_name}] PTP stack {desired_ipv6_ptp_name} already exists"
            )
            return
        ptp = ipv6.Ptp.add(Name=desired_ipv6_ptp_name)
        ptp.CommunicationMode.Single(communication_mode_str)
        ptp.StepMode.Single(step_mode_str)
        ptp.Role.Single(role)
        if server_ip_list:
            ptp.MasterIpv6Address.ValueList(server_ip_list)
        elif server_starting_ip and server_increment_ip:
            ptp.MasterIpv6Address.Increment(
                start_value=server_starting_ip,
                step_value=server_increment_ip,
            )
        self.logger.info(
            f"{device_group_name} Successfully created a new PTP stack {desired_ipv6_ptp_name}"
        )

    def configure_ixia_chassis(self):
        """
        Configure Ixia chassis with primary chassis as master and others in daisy chain topology.
        """
        primary_chassis_ip = ipaddress.ip_address(self.primary_chassis_ip)
        vport = None
        if not any(
            ipaddress.ip_address(port_config.phy_port_config.chassis_ip)
            == primary_chassis_ip
            for port_config in none_throws(self.ixia_config).port_configs
        ):
            self.logger.info(
                "Unable to locate any ports from the Ixia configuration that are associated "
                "with the primary chassis."
            )
            portmap_assistant = self.session.PortMapAssistant()
            # attempt to connect to at least one vport on the primary chassis
            vport = portmap_assistant.Map(
                IpAddress=self.primary_chassis_ip,
                CardId=1,
                PortId=100,  # an arbitrary port id
                Name="DO_NOT_USE",
            )
            portmap_assistant.Connect(ForceOwnership=False)
        elif all(
            ipaddress.ip_address(port_config.phy_port_config.chassis_ip)
            == primary_chassis_ip
            for port_config in none_throws(self.ixia_config).port_configs
        ):
            self.logger.info(
                "All ports from the Ixia configuration are associated with the primary chassis. Skipping the chassis configuration"
            )
            return
        all_chassis = self.ixnetwork.AvailableHardware.Chassis.find()
        primary_chassis = next(
            (
                chassis
                for chassis in all_chassis
                if ipaddress.ip_address(chassis.Hostname) == primary_chassis_ip
            ),
            None,
        )
        secondary_chassis = [
            chassis for chassis in all_chassis if chassis != primary_chassis
        ]
        if not primary_chassis:
            raise ValueError(f"Primary chassis {self.primary_chassis_ip} is not found")
        primary_chassis.SequenceId = 1
        primary_chassis.ChainTopology = "daisy"
        t.sequence_id = 2
        for chassis in secondary_chassis:
            chassis.MasterChassis = primary_chassis.Hostname
            chassis.SequenceId = t.sequence_id
            t.sequence_id += 1
        if vport:
            vport.remove()

    @external_api
    @require_traffic_item
    def enable_traffic(
        self, regexes: t.Optional[t.List[str]] = None, enable: bool = True
    ) -> None:
        """
        Enable or disable traffic items that match the given regexes.
        When enable=True and regexes are provided, non-matching items are
        explicitly disabled so that only the selected items run.
        Args:
            regexes (List[str], t.optional): Regexes of traffic items to enable/disable. Defaults to None.
            enable (bool, t.optional): Whether to enable or disable traffic items. Defaults to True.
        """
        all_traffic_items = self.ixnetwork.Traffic.TrafficItem.find()
        name_to_traffic_item = {item.Name: item for item in all_traffic_items}
        if regexes is None:
            traffic_items = list(name_to_traffic_item.values())
        else:
            traffic_items = []
            for name, item in name_to_traffic_item.items():
                for regex in regexes:
                    if re.match(regex, name):
                        traffic_items.append(item)
                        break  # Avoid adding same item multiple times
        matched_names = {ti.Name for ti in traffic_items}
        for traffic_item in traffic_items:
            traffic_item.Enabled = enable
        # When enabling selected items, explicitly disable non-matching items
        # so that only the requested traffic items run.
        if enable and regexes is not None:
            non_matching = [
                item
                for name, item in name_to_traffic_item.items()
                if name not in matched_names
            ]
            for traffic_item in non_matching:
                traffic_item.Enabled = False
            if non_matching:
                self.logger.info(
                    f"Disabled non-matching traffic item(s) "
                    f"{[ti.Name for ti in non_matching]}"
                )
        action = "enabled" if enable else "disabled"
        self.logger.info(
            f"Successfully {action} traffic item(s) {[traffic_item.Name for traffic_item in traffic_items]}"
        )
        self.apply_traffic()

    def configure_line_rate(
        self,
        config_element: "ConfigElement",
        line_rate: t.Optional[int] = None,
        line_rate_type: t.Optional[ixia_types.RateType] = None,
    ) -> None:
        """
        Configure line rate for the given traffic items
        """
        config_element.FrameRate.update(
            Type=ixia_types.RATE_TYPE_MAP[line_rate_type] if line_rate_type else None,
            Rate=line_rate if line_rate else None,
        )

    @require_traffic_item
    def apply_traffic(self) -> None:
        try:
            self.ixnetwork.Traffic.Apply()
        except Exception as e:
            self.logger.debug(f"Failed to apply traffic: {e}")

    def has_traffic_items(self) -> bool:
        try:
            return bool(self.ixnetwork.Traffic.TrafficItem.find())
        except Exception:
            return False

    @external_api
    def set_bgp_local_preference(
        self,
        local_preference: int,
        network_group_regex: t.Optional[str] = None,
        prefix_pool_regex: t.Optional[str] = None,
    ) -> None:
        """Sets the BGP local preference for network groups matching the given regex criteria.

        Args:
            local_preference: Integer value for the local preference to be set.
            network_group_regex: Regular expression to match network group names.
            prefix_pool_regex: Regular expression to match prefix pool names.
        """
        assert network_group_regex or prefix_pool_regex, (
            "At least one of network_group_regex or prefix_pool_regex must be provided"
        )

        self.logger.info(f"Prefix pool regex provided: {prefix_pool_regex}")
        self.logger.info(f"Network group regex provided: {network_group_regex}")

        prefix_pools = self.get_prefix_pools_by_regexes(
            network_group_regex, prefix_pool_regex
        )
        self.logger.info(f"Prefix pools found: {prefix_pools}")
        if not prefix_pools:
            self.logger.warning("No prefix pools found to set BGP local preference")

        for prefix_pool in prefix_pools:
            bgp_ip_route_property: "BgpIPRouteProperty" = (
                (prefix_pool.BgpIPRouteProperty.find())
                if isinstance(prefix_pool, Ipv4PrefixPools)
                else prefix_pool.BgpV6IPRouteProperty.find()
            )[0]

            # Enable local preference and set the value
            bgp_ip_route_property.EnableLocalPreference.Single(True)
            bgp_ip_route_property.LocalPreference.Single(local_preference)

            self.logger.info(
                f"Successfully set the BGP local preference to {local_preference} "
                f"for prefix pool {prefix_pool.Name}"
            )
        self.apply_changes()

    @external_api
    def get_device_groups_by_port_and_interface(
        self, hostname: str, interface: str
    ) -> t.List["DeviceGroup"]:
        """
        Find device groups by hostname and interface.

        Args:
            hostname: Hostname of the device
            interface: Interface name

        Returns:
            List of device groups in the matching topology
        """
        port_identifier = self.get_port_identifier(f"{hostname}:{interface}")
        topology_name = DESIRED_TOPOLOGY_NAME.format(port_identifier=port_identifier)

        self.logger.info(f"Looking for topology with name: {topology_name}")

        # Find the topology with the given name
        topology = self.ixnetwork.Topology.find(Name=topology_name)

        if not topology:
            self.logger.warning(f"Could not find topology with name: {topology_name}")
            return []

        # Get device groups from the topology
        device_groups = topology.DeviceGroup.find()

        if not device_groups:
            self.logger.warning(f"No device groups found in topology: {topology_name}")
            return []

        self.logger.info(
            f"Found {len(device_groups)} device groups in topology {topology_name}"
        )
        return device_groups

    @external_api
    def update_device_group_multipliers_by_port(
        self, hostname: str, interface: str, multiplier: int
    ) -> None:
        """
        Update the multiplier for device groups in the topology for the specified port.

        Args:
            hostname: Hostname of the device
            interface: Interface name
            multiplier: New multiplier value to set
        """
        device_groups = self.get_device_groups_by_port_and_interface(
            hostname, interface
        )

        if not device_groups:
            self.logger.warning(
                f"No device groups found to update multipliers for {hostname}:{interface}"
            )
            return

        # Update multiplier for all device groups
        for dg in device_groups:
            self.logger.info(
                f"Setting multiplier to {multiplier} for device group {dg.Name}"
            )
            dg.Multiplier = multiplier

        # Apply the changes
        self.apply_changes()

        self.logger.info(
            f"Successfully updated multipliers for device groups in topology for {hostname}:{interface}"
        )

    @external_api
    def update_prefix_counts_by_port(
        self,
        hostname: str,
        interface: str,
        prefix_count: int,
        network_group_multiplier: t.Optional[int] = None,
    ) -> None:
        """
        Update the prefix counts and optionally the network group multiplier for the specified port.

        Args:
            hostname: Hostname of the device
            interface: Interface name
            prefix_count: New prefix count value to set
            network_group_multiplier: Optional multiplier to set for network groups
        """
        device_groups = self.get_device_groups_by_port_and_interface(
            hostname, interface
        )

        if not device_groups:
            self.logger.warning(
                f"No device groups found to update prefix counts for {hostname}:{interface}"
            )
            return

        # Update prefix counts for all network groups in all device groups
        for dg in device_groups:
            for network_group in dg.NetworkGroup.find():
                # Update network group multiplier if specified
                if network_group_multiplier is not None:
                    self.logger.info(
                        f"Setting multiplier to {network_group_multiplier} for network group {network_group.Name}"
                    )
                    network_group.Multiplier = network_group_multiplier

                # Update IPv6 prefix pools
                for ipv6_prefix_pool in network_group.Ipv6PrefixPools.find():
                    self.logger.info(
                        f"Setting IPv6 prefix count to {prefix_count} for network group {network_group.Name}"
                    )
                    ipv6_prefix_pool.NumberOfAddresses = prefix_count

                # Update IPv4 prefix pools
                for ipv4_prefix_pool in network_group.Ipv4PrefixPools.find():
                    self.logger.info(
                        f"Setting IPv4 prefix count to {prefix_count} for network group {network_group.Name}"
                    )
                    ipv4_prefix_pool.NumberOfAddresses = prefix_count

        # Apply the changes.
        self.apply_changes()

        self.logger.info(
            f"Successfully updated prefix counts and network group multipliers for topology {hostname}:{interface}"
        )

    @external_api
    def configure_same_prefixes_across_peers(
        self,
        hostname: str,
        interface: str,
        prefix_count: int,
        ipv4_prefix_start: str = "100.0.0.0",
        ipv4_prefix_step: str = "0.0.1.0",
        ipv6_prefix_start: str = "2001:db8:1::",
        ipv6_prefix_step: str = "0:0:1:0:0:0:0:0",
    ) -> None:
        """
        Configure IXIA to make all peers send the same prefixes using Custom() with increments.
        This is useful for ECMP testing where multiple peers advertise the same prefixes
        with different next-hops.

        Args:
            hostname: Hostname of the device
            interface: Interface name
            prefix_count: Number of prefixes each peer should advertise
            ipv4_prefix_start: Starting IPv4 prefix (default: "100.0.0.0")
            ipv4_prefix_step: IPv4 prefix increment step (default: "0.0.1.0")
            ipv6_prefix_start: Starting IPv6 prefix (default: "2001:db8:1::")
            ipv6_prefix_step: IPv6 prefix increment step (default: "0:0:1:0:0:0:0:0")
        Example:
            With prefix_count=10000 and 2 peers:
            - Peer 1: prefixes 2001:db8:1:: to 2001:db8:10000::, nexthop fe80::1
            - Peer 2: prefixes 2001:db8:1:: to 2001:db8:10000::, nexthop fe80::2
            (Same prefixes, different next-hops for ECMP)
        """
        device_groups = self.get_device_groups_by_port_and_interface(
            hostname, interface
        )

        if not device_groups:
            self.logger.warning(
                f"No device groups found to configure same prefixes for {hostname}:{interface}"
            )
            return

        self.logger.info(
            f"Configuring {prefix_count} same prefixes across all peers for {hostname}:{interface}"
        )

        for dg in device_groups:
            for network_group in dg.NetworkGroup.find():
                self.logger.info(
                    f"Configuring network group {network_group.Name} with Custom() method"
                )

                # Configure IPv6 prefix pools
                for ipv6_prefix_pool in network_group.Ipv6PrefixPools.find():
                    self.logger.info(
                        f"Setting IPv6 prefix pool with {prefix_count} prefixes using Custom() with increments"
                    )

                    # Use Custom() with increments to make all peers send the same prefixes
                    # increments=[("::", prefix_count, [])] means:
                    # - After prefix_count routes, increment by "::" (which is 0)
                    # - Result: All peers repeat the same prefix_count prefixes
                    ipv6_prefix_pool.NetworkAddress.Custom(
                        start_value=ipv6_prefix_start,
                        step_value="::",
                        increments=[(ipv6_prefix_step, prefix_count, [])],
                    )

                # Configure IPv4 prefix pools
                for ipv4_prefix_pool in network_group.Ipv4PrefixPools.find():
                    self.logger.info(
                        f"Setting IPv4 prefix pool with {prefix_count} prefixes using Custom() with increments"
                    )

                    # Use Custom() with increments to make all peers send the same prefixes
                    ipv4_prefix_pool.NetworkAddress.Custom(
                        start_value=ipv4_prefix_start,
                        step_value="0.0.0.0",
                        increments=[(ipv4_prefix_step, prefix_count, [])],
                    )

        time.sleep(10)

        # Apply the changes
        self.apply_changes()

        self.logger.info(
            f"Successfully configured same prefixes across all peers for {hostname}:{interface}"
        )

    @retryable(num_tries=20, sleep_time=10, debug=True)
    def get_bgp_update_statistics(
        self,
        port: t.Optional[str] = None,
        hostname: t.Optional[str] = None,
        interface: t.Optional[str] = None,
    ) -> t.List[t.Dict[str, t.Any]]:
        """
        Get BGP update statistics from IXIA for both IPv4 and IPv6.

        This method collects statistics from both "BGP Peer Per Port" (IPv4) and
        "BGP+ Peer Per Port" (IPv6) views and combines the results.

        Args:
            port: Optional port identifier to filter statistics for (e.g., "10.0.0.1:1/1")
            hostname: Optional hostname to filter statistics for (used with interface)
            interface: Optional interface to filter statistics for (used with hostname)

        Returns:
            List[Dict[str, Any]]: List of dictionaries containing BGP update statistics
                                 filtered by port if specified
        """
        try:
            # Define the views we want to collect statistics from
            views = ["BGP Peer Per Port", "BGP+ Peer Per Port"]
            combined_stats = []

            # Select the appropriate StatViewAssistant class based on chassis type
            StatViewAssistant = (
                UhdStatViewAssistant if self.is_uhd_chassis else IxnStatViewAssistant
            )

            # Collect statistics from both views
            for view_name in views:
                self.logger.info(
                    f"Getting BGP update statistics from view: {view_name}"
                )

                try:
                    # Get the BGP protocol statistics view
                    stats_view = StatViewAssistant(self.ixnetwork, view_name)

                    # Check a condition to ensure the view is ready
                    # This will wait until the view is fully populated
                    try:
                        stats_view.CheckCondition(
                            "Port Name",
                            StatViewAssistant.NOT_EQUAL,
                            "DUMMY_VALUE_THAT_WONT_MATCH",
                        )
                    except Exception as e:
                        # This exception is expected and just ensures the view is ready
                        self.logger.debug(
                            f"CheckCondition exception (expected): {str(e)}"
                        )

                    # Get the statistics from this view
                    view_stats = []
                    for row in stats_view.Rows:
                        stat_entry = {}
                        # Copy all columns to the stat entry
                        for column_name in row.Columns:
                            stat_entry[column_name] = row[column_name]
                        # Add the view name to identify which view this came from
                        stat_entry["View"] = view_name
                        view_stats.append(stat_entry)

                    self.logger.info(
                        f"Retrieved {len(view_stats)} entries from {view_name}"
                    )
                    combined_stats.extend(view_stats)

                except Exception as e:
                    # If one view fails, log the error but continue with the other view
                    self.logger.warning(
                        f"Error getting statistics from {view_name}: {str(e)}"
                    )

            # Filter statistics by port if specified
            filtered_stats = combined_stats
            if port:
                filtered_stats = [
                    stat for stat in combined_stats if port in stat.get("Port", "")
                ]
                self.logger.info(
                    f"Filtered statistics for port {port}: {len(filtered_stats)} entries"
                )
            # Filter by hostname and interface if both are provided
            elif hostname and interface:
                # Construct port identifier
                port_id = self.get_port_identifier(f"{hostname}:{interface}")
                filtered_stats = [
                    stat for stat in combined_stats if port_id in stat.get("Port", "")
                ]
                self.logger.info(
                    f"Filtered statistics for {hostname}:{interface} (port ID: {port_id}): {len(filtered_stats)} entries"
                )

            self.logger.info(
                f"Retrieved a total of {len(filtered_stats)} BGP statistics entries from all views"
            )

            # If filtering was requested but no results were found, log a warning
            if (port or (hostname and interface)) and not filtered_stats:
                filter_desc = port if port else f"{hostname}:{interface}"
                self.logger.warning(
                    f"No BGP statistics found for {filter_desc} in any view. "
                    f"Available ports: {{stat.get('Port', '') for stat in combined_stats if 'Port' in stat}}"
                )

            return filtered_stats

        except Exception as e:
            self.logger.error(f"Error getting BGP update statistics: {str(e)}")
            return []

    def _get_property(
        self, obj: t.Any, property_names: t.List[str]
    ) -> t.Optional[t.Any]:
        """
        Helper method to get a property from an object, trying different case variations.

        Args:
            obj: The object to get the property from
            property_names: List of property names to try (e.g., ["EnableAsPath", "enableAsPath"])

        Returns:
            The property if found, None otherwise
        """
        for name in property_names:
            if hasattr(obj, name):
                return getattr(obj, name)

        self.logger.warning(
            f"Could not find any of {property_names} properties on object"
        )
        return None

    def _configure_bgp_attributes(
        self,
        bgp_route_property: t.Any,
        unique_attributes_count: int,
        constant_communities: t.Optional[t.List[str]] = None,
    ) -> None:
        """
        Configure random BGP attributes for a route property.

        Args:
            bgp_route_property: The BGP route property object to configure
            unique_attributes_count: Number of unique attribute combinations to generate
            constant_communities: List of communities to add to all routes
        """
        try:
            # 1. Enable random AS paths
            if hasattr(bgp_route_property, "EnableRandomAsPath"):
                bgp_route_property.EnableRandomAsPath.Single(True)
                self.logger.info("Enabled random AS paths")

            # 2. Set AsPathPerRoute to 1 (asdiff)
            if hasattr(bgp_route_property, "AsPathPerRoute"):
                bgp_route_property.AsPathPerRoute.Single(1)  # 1 = asdiff
                self.logger.info("Set AsPathPerRoute to 1 (asdiff)")

            # 3. Configure AS path parameters
            if hasattr(bgp_route_property, "MinNoOfASPathSegmentsPerRouteRange"):
                bgp_route_property.MinNoOfASPathSegmentsPerRouteRange.Single(1)

            if hasattr(bgp_route_property, "MaxNoOfASPathSegmentsPerRouteRange"):
                bgp_route_property.MaxNoOfASPathSegmentsPerRouteRange.Single(1)

            if hasattr(bgp_route_property, "MinASNumPerSegment"):
                bgp_route_property.MinASNumPerSegment.Single(3)

            if hasattr(bgp_route_property, "MaxASNumPerSegment"):
                bgp_route_property.MaxASNumPerSegment.Single(3)

            # 4. Set AsRandomSeed with an incrementing pattern
            if hasattr(bgp_route_property, "AsRandomSeed"):
                base_seed = unique_attributes_count % 65535

                # Try to use Increment method for different seeds per route
                try:
                    bgp_route_property.AsRandomSeed.Increment(
                        start_value=base_seed, step_value=1
                    )
                    self.logger.info(f"Set AsRandomSeed to increment from {base_seed}")
                except Exception:
                    # Fall back to Single method if Increment fails
                    bgp_route_property.AsRandomSeed.Single(base_seed)
                    self.logger.info(f"Set AsRandomSeed to {base_seed} (single value)")

            # 5. Configure communities if provided
            if constant_communities and hasattr(bgp_route_property, "EnableCommunity"):
                bgp_route_property.EnableCommunity.Single(True)

                if hasattr(bgp_route_property, "NoOfCommunities"):
                    bgp_route_property.NoOfCommunities.Single(len(constant_communities))

                if hasattr(bgp_route_property, "CommunityValue"):
                    bgp_route_property.CommunityValue.ValueList(constant_communities)
                    self.logger.info(
                        f"Set constant communities: {constant_communities}"
                    )

        except Exception as e:
            self.logger.warning(f"Error configuring BGP attributes: {str(e)}")

    @external_api
    def configure_random_bgp_attributes(
        self,
        hostname: str,
        interface: str,
        unique_attributes_count: int = 2000,
        constant_communities: t.Optional[t.List[str]] = None,
        restart_protocols: bool = True,
    ) -> bool:
        """
        Configure random BGP attributes (AS path, communities, extended communities) for BGP routes.

        This method configures random BGP attributes for the routes advertised by the specified
        interface. It creates unique attribute combinations that are shared among all prefixes.

        If constant_communities is provided, these communities will be added to all routes in addition
        to the random communities. This is useful when certain communities are required by policy.

        Args:
            hostname: The hostname of the device
            interface: The interface to configure random attributes for
            unique_attributes_count: Number of unique attribute combinations to generate
            constant_communities: List of communities to add to all routes (e.g., ["65001:1", "65001:2"])
            restart_protocols: Whether to restart protocols after configuring attributes (default: True)

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            self.logger.info(
                f"Configuring random BGP attributes for {hostname}:{interface}"
            )

            if constant_communities:
                self.logger.info(
                    f"Adding constant communities to all routes: {constant_communities}"
                )

            # Stop protocols before making changes
            self.logger.info("Stopping protocols before configuring BGP attributes")
            self.stop_protocols()

            # Find device groups for the specified interface
            device_groups = self.get_device_groups_by_port_and_interface(
                hostname, interface
            )

            if not device_groups:
                self.logger.error(
                    f"Could not find device groups for {hostname}:{interface}"
                )
                return False

            self.logger.info(f"Found {len(device_groups)} device groups")

            # Process each device group
            for device_group in device_groups:
                # Find all network groups in the device group
                network_groups = device_group.NetworkGroup.find()

                if not network_groups:
                    self.logger.warning(
                        f"No network groups found in device group {device_group.Name}"
                    )
                    continue

                self.logger.info(
                    f"Found {len(network_groups)} network groups in device group {device_group.Name}"
                )

                # Configure random attributes for each network group
                for network_group in network_groups:
                    # Configure IPv4 prefix pools
                    for ip_prefix_pool in network_group.Ipv4PrefixPools.find():
                        # Find the BgpIPRouteProperty object
                        bgp_route_properties = ip_prefix_pool.BgpIPRouteProperty.find()
                        if bgp_route_properties:
                            self._configure_bgp_attributes(
                                bgp_route_properties[0],
                                unique_attributes_count,
                                constant_communities,
                            )
                        else:
                            self.logger.warning(
                                f"No BgpIPRouteProperty found for IPv4 prefix pool in {network_group.Name}"
                            )

                    # Configure IPv6 prefix pools
                    for ip_prefix_pool in network_group.Ipv6PrefixPools.find():
                        # Find the BgpV6IPRouteProperty object
                        bgp_route_properties = (
                            ip_prefix_pool.BgpV6IPRouteProperty.find()
                        )
                        if bgp_route_properties:
                            self._configure_bgp_attributes(
                                bgp_route_properties[0],
                                unique_attributes_count,
                                constant_communities,
                            )
                        else:
                            self.logger.warning(
                                f"No BgpV6IPRouteProperty found for IPv6 prefix pool in {network_group.Name}"
                            )

            # Apply the changes
            self.apply_changes()
            self.logger.info(
                f"Successfully configured random BGP attributes for {hostname}:{interface}"
            )

            # Restart protocols if requested
            if restart_protocols:
                self.logger.info(
                    "Restarting protocols after configuring BGP attributes"
                )
                self.start_protocols()

            return True

        except Exception as e:
            self.logger.error(f"Error configuring random BGP attributes: {str(e)}")
            # Try to restart protocols in case of error
            try:
                if restart_protocols:
                    self.logger.info("Attempting to restart protocols after error")
                    self.start_protocols()
            except Exception as restart_error:
                self.logger.error(f"Error restarting protocols: {str(restart_error)}")
            return False

    def _revert_route_storm_attributes_on_route_property(
        self,
        bgp_route_prop: t.Any,
    ) -> None:
        """
        Revert "New Year Tree" BGP attributes on a single route property to defaults.

        Resets AS path, MED, local preference, ORIGIN, communities, and extended
        communities to their default/disabled state.

        Args:
            bgp_route_prop: BGP route property object (BgpIPRouteProperty or BgpV6IPRouteProperty)
        """
        try:
            # --- AS path: disable segments, reset to 1 ---
            bgp_route_prop.EnableAsPathSegments.Single(False)
            bgp_route_prop.NoOfASPathSegmentsPerRouteRange = 1
            self.logger.info("Reverted AS path segments to defaults")

            # --- MED: disable ---
            if hasattr(bgp_route_prop, "EnableMultiExitDiscriminator"):
                bgp_route_prop.EnableMultiExitDiscriminator.Single(False)
                self.logger.info("Disabled MED")

            # --- Local preference: reset to 100 ---
            if hasattr(bgp_route_prop, "EnableLocalPreference"):
                bgp_route_prop.EnableLocalPreference.Single(True)
            if hasattr(bgp_route_prop, "LocalPreference"):
                bgp_route_prop.LocalPreference.Single(100)
                self.logger.info("Reset local preference to 100")

            # --- ORIGIN: reset to igp ---
            if hasattr(bgp_route_prop, "Origin"):
                bgp_route_prop.Origin.Single("igp")
                self.logger.info("Reset ORIGIN to igp")

            # --- Standard communities: disable ---
            if hasattr(bgp_route_prop, "EnableCommunity"):
                bgp_route_prop.EnableCommunity.Single(False)
                self.logger.info("Disabled standard communities")

            # --- Extended communities: disable ---
            if hasattr(bgp_route_prop, "EnableExtendedCommunity"):
                bgp_route_prop.EnableExtendedCommunity.Single(False)
                self.logger.info("Disabled extended communities")

        except Exception as e:
            self.logger.warning(f"Error reverting route storm attributes: {str(e)}")

    @external_api
    def revert_route_storm_attributes(
        self,
        hostname: str,
        interface: str,
        device_group_regex: str = ".*",
        restart_protocols: bool = True,
    ) -> bool:
        """
        Revert "New Year Tree" BGP attributes to defaults after route storm testing.

        Resets AS path segments, MED, local preference, ORIGIN, communities,
        and extended communities back to their default/disabled state.

        Args:
            hostname: The hostname of the device
            interface: The interface to revert attributes for
            device_group_regex: Regex to filter device groups by name (default: ".*" matches all)
            restart_protocols: Whether to restart protocols after reverting (default: True)

        Returns:
            bool: True if successful, False otherwise
        """
        import re

        try:
            self.logger.info(
                f"Reverting route storm attributes for {hostname}:{interface} "
                f"(device_group_regex={device_group_regex})"
            )

            # Stop protocols before making changes
            self.logger.info(
                "Stopping protocols before reverting route storm attributes"
            )
            self.stop_protocols(sleep_timer=30)

            # Find device groups for the specified interface
            device_groups = self.get_device_groups_by_port_and_interface(
                hostname, interface
            )

            if not device_groups:
                self.logger.error(
                    f"Could not find device groups for {hostname}:{interface}"
                )
                return False

            self.logger.info(f"Found {len(device_groups)} device groups")

            dg_pattern = re.compile(device_group_regex, re.IGNORECASE)

            # Process each device group
            for device_group in device_groups:
                if not dg_pattern.search(device_group.Name):
                    self.logger.debug(
                        f"Skipping device group {device_group.Name} "
                        f"(does not match regex '{device_group_regex}')"
                    )
                    continue

                network_groups = device_group.NetworkGroup.find()

                if not network_groups:
                    self.logger.warning(
                        f"No network groups found in device group {device_group.Name}"
                    )
                    continue

                self.logger.info(
                    f"Found {len(network_groups)} network groups in device group {device_group.Name}"
                )

                for network_group in network_groups:
                    # Revert IPv4 prefix pools
                    for ip_prefix_pool in network_group.Ipv4PrefixPools.find():
                        bgp_route_properties = ip_prefix_pool.BgpIPRouteProperty.find()
                        if bgp_route_properties:
                            self._revert_route_storm_attributes_on_route_property(
                                bgp_route_properties[0],
                            )
                        else:
                            self.logger.warning(
                                f"No BgpIPRouteProperty found for IPv4 prefix pool in {network_group.Name}"
                            )

                    # Revert IPv6 prefix pools
                    for ip_prefix_pool in network_group.Ipv6PrefixPools.find():
                        bgp_route_properties = (
                            ip_prefix_pool.BgpV6IPRouteProperty.find()
                        )
                        if bgp_route_properties:
                            self._revert_route_storm_attributes_on_route_property(
                                bgp_route_properties[0],
                            )
                        else:
                            self.logger.warning(
                                f"No BgpV6IPRouteProperty found for IPv6 prefix pool in {network_group.Name}"
                            )

            # Apply the changes
            self.apply_changes()
            self.logger.info(
                f"Successfully reverted route storm attributes for {hostname}:{interface}"
            )

            # Restart protocols if requested
            if restart_protocols:
                self.logger.info(
                    "Restarting protocols after reverting route storm attributes"
                )
                self.start_protocols()

            return True

        except Exception as e:
            self.logger.error(f"Error reverting route storm attributes: {str(e)}")
            # Try to restart protocols in case of error
            try:
                if restart_protocols:
                    self.logger.info("Attempting to restart protocols after error")
                    self.start_protocols()
            except Exception as restart_error:
                self.logger.error(f"Error restarting protocols: {str(restart_error)}")
            return False

    @external_api
    def configure_as_path_pool(
        self,
        hostname: str,
        interface: str,
        as_path_pool: t.List[str],
        restart_protocols: bool = True,
        device_group_regex: str = ".*",
    ) -> bool:
        """
        Configure AS path distribution from a constant pool across BGP routes.

        Uses Ixia's BGP route property API to distribute AS paths from the pool
        across routes cyclically. Each route gets ONE AS path from the pool in a
        round-robin fashion (route 1 → path 1, route 2 → path 2, etc.).

        This enables testing that BGP++ memory depends on unique AS paths,
        not on the total number of routes.

        Args:
            hostname: The hostname of the device
            interface: The interface to configure AS paths for
            as_path_pool: List of AS path strings (e.g., ["65001 65002", "65003 65004"])
            restart_protocols: Whether to restart protocols after configuring (default: True)
            device_group_regex: Regex to filter device groups by name (default: ".*" matches all)

        Returns:
            bool: True if successful, False otherwise

        Example:
            >>> success = ixia.configure_as_path_pool(
            ...     hostname="arista01",
            ...     interface="Ethernet1",
            ...     as_path_pool=["65001 65002 65003", "65004 65005 65006"],
            ... )
        """
        import re

        try:
            self.logger.info(
                f"Configuring AS path pool for {hostname}:{interface} "
                f"with {len(as_path_pool)} unique paths "
                f"(device_group_regex={device_group_regex})"
            )

            # Stop protocols before making changes
            self.logger.info("Stopping protocols before configuring AS path pool")
            self.stop_protocols()

            # Find device groups for the specified interface using existing method
            device_groups = self.get_device_groups_by_port_and_interface(
                hostname, interface
            )

            if not device_groups:
                self.logger.error(
                    f"Could not find device groups for {hostname}:{interface}"
                )
                return False

            self.logger.info(f"Found {len(device_groups)} device groups")

            dg_pattern = re.compile(device_group_regex, re.IGNORECASE)

            # Process each device group
            for device_group in device_groups:
                if not dg_pattern.search(device_group.Name):
                    self.logger.debug(
                        f"Skipping device group {device_group.Name} "
                        f"(does not match regex '{device_group_regex}')"
                    )
                    continue

                # Find all network groups in the device group
                network_groups = device_group.NetworkGroup.find()

                if not network_groups:
                    self.logger.warning(
                        f"No network groups found in device group {device_group.Name}"
                    )
                    continue

                self.logger.info(
                    f"Found {len(network_groups)} network groups in device group {device_group.Name}"
                )

                # Configure AS paths for each network group
                for network_group in network_groups:
                    # Configure IPv4 prefix pools
                    for ip_prefix_pool in network_group.Ipv4PrefixPools.find():
                        bgp_route_properties = ip_prefix_pool.BgpIPRouteProperty.find()
                        if bgp_route_properties:
                            self._configure_as_path_pool_on_route_property(
                                bgp_route_properties[0], as_path_pool
                            )
                        else:
                            self.logger.warning(
                                f"No BgpIPRouteProperty found for IPv4 prefix pool in {network_group.Name}"
                            )

                    # Configure IPv6 prefix pools
                    for ip_prefix_pool in network_group.Ipv6PrefixPools.find():
                        bgp_route_properties = (
                            ip_prefix_pool.BgpV6IPRouteProperty.find()
                        )
                        if bgp_route_properties:
                            self._configure_as_path_pool_on_route_property(
                                bgp_route_properties[0], as_path_pool
                            )
                        else:
                            self.logger.warning(
                                f"No BgpV6IPRouteProperty found for IPv6 prefix pool in {network_group.Name}"
                            )

            # Apply the changes
            self.apply_changes()
            self.logger.info(
                f"Successfully configured AS path pool for {hostname}:{interface}"
            )

            # Restart protocols if requested
            if restart_protocols:
                self.logger.info("Restarting protocols after configuring AS path pool")
                self.start_protocols()

            return True

        except Exception as e:
            self.logger.error(f"Error configuring AS path pool: {str(e)}")
            # Try to restart protocols in case of error
            try:
                if restart_protocols:
                    self.logger.info("Attempting to restart protocols after error")
                    self.start_protocols()
            except Exception as restart_error:
                self.logger.error(f"Error restarting protocols: {str(restart_error)}")
            return False

    @staticmethod
    def _build_as_path_position_values(
        as_path_pool: t.List[str],
        max_as_path_length: int,
    ) -> t.List[t.List[int]]:
        """Build per-position AS number value lists from an AS path pool.

        For each position index 0..max_as_path_length-1, collect the AS number
        at that position from every path in the pool (0 if the path is shorter).

        Returns:
            List of value lists, one per AS number position.
        """
        position_values = []
        for asn_position in range(max_as_path_length):
            as_values_at_position = []
            for as_path_str in as_path_pool:
                as_numbers = [int(asn) for asn in as_path_str.split()]
                if asn_position < len(as_numbers):
                    as_values_at_position.append(as_numbers[asn_position])
                else:
                    as_values_at_position.append(0)
            position_values.append(as_values_at_position)
        return position_values

    def _apply_as_positions_concurrently(
        self,
        bgp_as_number_list: t.Any,
        position_values: t.List[t.List[int]],
    ) -> None:
        """Apply AS number position values concurrently via ThreadPoolExecutor.

        Failed positions are automatically retried sequentially.
        """
        from concurrent.futures import as_completed, ThreadPoolExecutor

        max_workers = 10
        num_positions = len(position_values)
        self.logger.info(
            f"Configuring {num_positions} AS positions concurrently "
            f"(max_workers={max_workers})..."
        )

        def set_position(pos: int) -> None:
            bgp_as_number_list[pos].AsNumber.ValueList(position_values[pos])
            bgp_as_number_list[pos].EnableASNumber.Single(True)

        errors = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(set_position, pos): pos for pos in range(num_positions)
            }
            for future in as_completed(futures):
                pos = futures[future]
                try:
                    future.result()
                except Exception as e:
                    errors.append((pos, str(e)))

        if not errors:
            return

        self.logger.warning(
            f"{len(errors)} positions failed during concurrent config, "
            f"retrying sequentially..."
        )
        for pos, err in errors[:5]:
            self.logger.warning(f"  Position {pos}: {err}")

        retry_failures = []
        for pos, _ in errors:
            try:
                set_position(pos)
            except Exception as e:
                retry_failures.append((pos, str(e)))
                self.logger.warning(f"Position {pos} still failed after retry: {e}")
        if retry_failures:
            raise RuntimeError(
                f"{len(retry_failures)} AS path positions failed even after retry: "
                f"{retry_failures[:5]}"
            )

    def _configure_as_path_pool_on_route_property(
        self,
        bgp_route_prop: t.Union["BgpIPRouteProperty", "BgpV6IPRouteProperty"],
        as_path_pool: t.List[str],
    ) -> None:
        """
        Configure AS path pool on a BGP route property to distribute AS paths across routes.

        This is an internal helper function used by configure_as_path_pool.
        Uses concurrent REST calls via ThreadPoolExecutor to configure all AS number
        positions in parallel, reducing wall-clock time by ~5-10x compared to sequential.

        Args:
            bgp_route_prop: BGP route property object (BgpIPRouteProperty or BgpV6IPRouteProperty)
            as_path_pool: List of AS path strings
        """
        try:
            self.logger.info(
                f"Configuring AS path pool with {len(as_path_pool)} unique paths"
            )

            # Enable AS path segments
            bgp_route_prop.EnableAsPathSegments.Single(True)

            # Configure to use 1 AS path segment per route
            bgp_route_prop.NoOfASPathSegmentsPerRouteRange = 1

            # Get the AS path segment list
            bgp_as_path_segment_list = bgp_route_prop.BgpAsPathSegmentList.find()

            if not bgp_as_path_segment_list:
                self.logger.warning("No BGP AS path segment list found")
                return

            # Configure the first (and only) segment to cycle through AS paths
            bgp_as_path_segment = bgp_as_path_segment_list[0]

            # Set segment type to AS_SEQUENCE (type 2) instead of AS_SET (type 1)
            bgp_as_path_segment.SegmentType.Single("asseq")

            # Find the maximum AS path length in the pool
            max_as_path_length = max(len(as_path.split()) for as_path in as_path_pool)

            # Set the segment to hold the maximum number of AS numbers
            bgp_as_path_segment.NumberOfAsNumberInSegment = max_as_path_length

            self.logger.info(f"Maximum AS path length in pool: {max_as_path_length}")

            # Get AS number list
            bgp_as_number_list = bgp_as_path_segment.BgpAsNumberList.find()

            if not bgp_as_number_list:
                self.logger.warning("No BGP AS number list found")
                return

            position_values = self._build_as_path_position_values(
                as_path_pool, max_as_path_length
            )
            self._apply_as_positions_concurrently(bgp_as_number_list, position_values)

            self.logger.info("Successfully configured AS path distribution")
            self.logger.info(
                f"  - Each route will get ONE AS path from the {len(as_path_pool)}-path pool"
            )
            self.logger.info(
                "  - AS paths will cycle: route 1 → path 1, route 2 → path 2, ..."
            )

        except Exception as e:
            self.logger.warning(f"Error configuring AS path pool: {str(e)}")

    @external_api
    def configure_community_pool(
        self,
        hostname: str,
        interface: str,
        community_combinations: t.List[t.List[str]],
        restart_protocols: bool = True,
        device_group_regex: str = ".*",
    ) -> bool:
        """
        Configure diverse community combinations for each prefix using Ixia API.

        This method distributes different community combinations across routes,
        enabling testing of constant attribute storage with multiple communities per prefix.

        Note: Current implementation enables communities but does not yet apply
        combinations via Ixia's API. This requires additional Ixia API work
        similar to AS path distribution.

        Args:
            hostname: The hostname of the device
            interface: The interface to configure communities for
            community_combinations: List of community lists, one per prefix.
                Example: [["100:1", "100:2"], ["100:2", "100:3"], ...]
            restart_protocols: Whether to restart protocols after configuring (default: True)
            device_group_regex: Regex to filter device groups by name (default: ".*" matches all)

        Returns:
            bool: True if successful, False otherwise

        Example:
            >>> combinations = [
            ...     ["100:1", "100:2", "100:3"],
            ...     ["100:2", "100:3", "100:4"],
            ... ]
            >>> success = ixia.configure_community_pool(
            ...     hostname="arista01",
            ...     interface="Ethernet1",
            ...     community_combinations=combinations,
            ... )
        """
        import re

        try:
            self.logger.info(
                f"Configuring community combinations for {hostname}:{interface} "
                f"(device_group_regex={device_group_regex})"
            )

            if not community_combinations:
                self.logger.warning("Empty community combinations provided")
                return False

            communities_per_prefix = len(community_combinations[0])

            # Stop protocols before making changes
            self.logger.info("Stopping protocols before configuring community pool")
            self.stop_protocols()

            # Find device groups for the specified interface
            device_groups = self.get_device_groups_by_port_and_interface(
                hostname, interface
            )

            if not device_groups:
                self.logger.error(
                    f"Could not find device groups for {hostname}:{interface}"
                )
                return False

            self.logger.info(f"Found {len(device_groups)} device groups")

            dg_pattern = re.compile(device_group_regex, re.IGNORECASE)

            # Process each device group
            for device_group in device_groups:
                if not dg_pattern.search(device_group.Name):
                    self.logger.debug(
                        f"Skipping device group {device_group.Name} "
                        f"(does not match regex '{device_group_regex}')"
                    )
                    continue

                # Find all network groups in the device group
                network_groups = device_group.NetworkGroup.find()

                if not network_groups:
                    self.logger.warning(
                        f"No network groups found in device group {device_group.Name}"
                    )
                    continue

                self.logger.info(
                    f"Found {len(network_groups)} network groups in device group {device_group.Name}"
                )

                # Configure communities for each network group
                for network_group in network_groups:
                    # Configure IPv4 prefix pools
                    for ip_prefix_pool in network_group.Ipv4PrefixPools.find():
                        bgp_route_properties = ip_prefix_pool.BgpIPRouteProperty.find()
                        if bgp_route_properties:
                            self._configure_community_pool_on_route_property(
                                bgp_route_properties[0], community_combinations
                            )
                        else:
                            self.logger.warning(
                                f"No BgpIPRouteProperty found for IPv4 prefix pool in {network_group.Name}"
                            )

                    # Configure IPv6 prefix pools
                    for ip_prefix_pool in network_group.Ipv6PrefixPools.find():
                        bgp_route_properties = (
                            ip_prefix_pool.BgpV6IPRouteProperty.find()
                        )
                        if bgp_route_properties:
                            self._configure_community_pool_on_route_property(
                                bgp_route_properties[0], community_combinations
                            )
                        else:
                            self.logger.warning(
                                f"No BgpV6IPRouteProperty found for IPv6 prefix pool in {network_group.Name}"
                            )

            self.logger.info(
                f"Generated {len(community_combinations)} community combinations "
                f"with {communities_per_prefix} communities each"
            )

            # Apply the changes
            self.apply_changes()
            self.logger.info(
                f"Successfully configured community pool for {hostname}:{interface}"
            )

            # Restart protocols if requested
            if restart_protocols:
                self.logger.info(
                    "Restarting protocols after configuring community pool"
                )
                self.start_protocols()

            return True

        except Exception as e:
            self.logger.error(f"Error configuring community pool: {str(e)}")
            # Try to restart protocols in case of error
            try:
                if restart_protocols:
                    self.logger.info("Attempting to restart protocols after error")
                    self.start_protocols()
            except Exception as restart_error:
                self.logger.error(f"Error restarting protocols: {str(restart_error)}")
            return False

    def _configure_community_pool_on_route_property(
        self,
        bgp_route_prop: t.Union["BgpIPRouteProperty", "BgpV6IPRouteProperty"],
        community_combinations: t.List[t.List[str]],
    ) -> None:
        """
        Configure community pool on a BGP route property using ValueList API.

        This method distributes community combinations from the pool across routes
        cyclically using Ixia's ValueList feature.

        Args:
            bgp_route_prop: BGP route property object
            community_combinations: List of community lists (one per route)
                Example: [["100:1", "100:2"], ["100:3", "100:4"], ...]
        """
        try:
            if not community_combinations:
                self.logger.warning("Empty community combinations provided")
                return

            communities_per_prefix = len(community_combinations[0])

            # Step 1: Enable communities FIRST (this may initialize BgpCommunitiesList)
            if not hasattr(bgp_route_prop, "EnableCommunity"):
                self.logger.warning("EnableCommunity attribute not found")
                return

            bgp_route_prop.EnableCommunity.Single(True)
            self.logger.info("Enabled communities on route property")

            # Step 2: Set number of communities per route (similar to AS path pattern at line 4671)
            if not hasattr(bgp_route_prop, "NoOfCommunities"):
                self.logger.warning("NoOfCommunities attribute not found")
                return

            # Direct assignment (not .Single()) - matches existing pattern at line 3110
            bgp_route_prop.NoOfCommunities = communities_per_prefix
            self.logger.info(
                f"Set NoOfCommunities to {communities_per_prefix} communities per prefix"
            )

            # Step 3: NOW try to access the BGP community list (should be available after enabling)
            if not hasattr(bgp_route_prop, "BgpCommunitiesList"):
                self.logger.warning(
                    "BgpCommunitiesList attribute not found even after enabling communities. "
                    "This may be a limitation of programmatically created routes."
                )
                return

            bgp_community_list = bgp_route_prop.BgpCommunitiesList.find()

            if not bgp_community_list:
                self.logger.warning(
                    "No BGP community objects found in BgpCommunitiesList after enabling"
                )
                return

            self.logger.info(
                f"Found {len(bgp_community_list)} community positions to configure"
            )

            # Configure each community position to cycle through values from the pool
            for community_idx in range(communities_per_prefix):
                if community_idx >= len(bgp_community_list):
                    self.logger.warning(
                        f"Not enough community list entries ({len(bgp_community_list)}) "
                        f"for {communities_per_prefix} communities"
                    )
                    break

                # Collect community values at this position from all combinations
                community_values_at_position = []

                for community_combination in community_combinations:
                    if community_idx < len(community_combination):
                        community_str = community_combination[community_idx]
                        # Parse community string (format: "AS:VALUE" or integer)
                        # Convert to integer format that Ixia expects
                        try:
                            if ":" in community_str:
                                # Format: AS:VALUE (e.g., "100:1")
                                as_num, value = community_str.split(":")
                                # Convert to 32-bit integer: (AS << 16) | VALUE
                                community_int = (int(as_num) << 16) | int(value)
                            else:
                                # Already an integer
                                community_int = int(community_str)

                            community_values_at_position.append(community_int)
                        except ValueError as e:
                            self.logger.warning(
                                f"Invalid community format '{community_str}': {e}"
                            )
                            community_values_at_position.append(0)
                    else:
                        # This combination doesn't have a community at this position
                        community_values_at_position.append(0)

                # Apply ValueList to cycle through community values
                bgp_community = bgp_community_list[community_idx]

                # Set community type (typically manual AS number)
                if hasattr(bgp_community, "Type"):
                    bgp_community.Type.Single("manual")

                # Configure the AS number field with ValueList
                if hasattr(bgp_community, "AsNumber"):
                    # Extract AS numbers (high 16 bits)
                    as_numbers = [
                        (comm >> 16) if comm != 0 else 0
                        for comm in community_values_at_position
                    ]
                    bgp_community.AsNumber.ValueList(as_numbers)

                # Configure the last two octets field with ValueList
                if hasattr(bgp_community, "LastTwoOctets"):
                    # Extract values (low 16 bits)
                    values = [
                        (comm & 0xFFFF) if comm != 0 else 0
                        for comm in community_values_at_position
                    ]
                    bgp_community.LastTwoOctets.ValueList(values)

                self.logger.debug(
                    f"Community position {community_idx}: cycling through {len(community_values_at_position)} values"
                )

            self.logger.info(
                f"Successfully configured community distribution for {len(community_combinations)} routes"
            )
            self.logger.info(
                f"  - Each route will get {communities_per_prefix} communities from the pool"
            )
            self.logger.info(
                "  - Communities will cycle: route 1 → combination 1, route 2 → combination 2, ..."
            )

        except Exception as e:
            self.logger.warning(f"Error configuring community pool: {str(e)}")

    @external_api
    def configure_extended_community_pool(
        self,
        hostname: str,
        interface: str,
        extended_community_combinations: t.List[t.List[str]],
        restart_protocols: bool = True,
        device_group_regex: str = ".*",
    ) -> bool:
        """
        Configure diverse extended community combinations for each prefix using Ixia API.

        This method distributes different extended community combinations across routes,
        enabling testing of constant attribute storage with multiple extended communities
        per prefix.

        Note: Current implementation enables extended communities but does not yet apply
        combinations via Ixia's API. This requires additional Ixia API work
        similar to AS path distribution.

        Args:
            hostname: The hostname of the device
            interface: The interface to configure extended communities for
            extended_community_combinations: List of extended community lists, one per prefix.
                Example: [["rt:100:1", "rt:100:2"], ["rt:100:2", "rt:100:3"], ...]
            restart_protocols: Whether to restart protocols after configuring (default: True)
            device_group_regex: Regex to filter device groups by name (default: ".*" matches all)

        Returns:
            bool: True if successful, False otherwise

        Example:
            >>> combinations = [
            ...     ["rt:100:1", "rt:100:2", "rt:100:3"],
            ...     ["rt:100:2", "rt:100:3", "rt:100:4"],
            ... ]
            >>> success = ixia.configure_extended_community_pool(
            ...     hostname="arista01",
            ...     interface="Ethernet1",
            ...     extended_community_combinations=combinations,
            ... )
        """
        import re

        try:
            self.logger.info(
                f"Configuring extended community combinations for {hostname}:{interface} "
                f"(device_group_regex={device_group_regex})"
            )

            if not extended_community_combinations:
                self.logger.warning("Empty extended community combinations provided")
                return False

            ext_communities_per_prefix = len(extended_community_combinations[0])

            # Stop protocols before making changes
            self.logger.info(
                "Stopping protocols before configuring extended community pool"
            )
            self.stop_protocols()

            # Find device groups for the specified interface
            device_groups = self.get_device_groups_by_port_and_interface(
                hostname, interface
            )

            if not device_groups:
                self.logger.error(
                    f"Could not find device groups for {hostname}:{interface}"
                )
                return False

            self.logger.info(f"Found {len(device_groups)} device groups")

            dg_pattern = re.compile(device_group_regex, re.IGNORECASE)

            # Process each device group
            for device_group in device_groups:
                if not dg_pattern.search(device_group.Name):
                    self.logger.debug(
                        f"Skipping device group {device_group.Name} "
                        f"(does not match regex '{device_group_regex}')"
                    )
                    continue

                # Find all network groups in the device group
                network_groups = device_group.NetworkGroup.find()

                if not network_groups:
                    self.logger.warning(
                        f"No network groups found in device group {device_group.Name}"
                    )
                    continue

                self.logger.info(
                    f"Found {len(network_groups)} network groups in device group {device_group.Name}"
                )

                # Configure extended communities for each network group
                for network_group in network_groups:
                    # Configure IPv4 prefix pools
                    for ip_prefix_pool in network_group.Ipv4PrefixPools.find():
                        bgp_route_properties = ip_prefix_pool.BgpIPRouteProperty.find()
                        if bgp_route_properties:
                            self._configure_extended_community_pool_on_route_property(
                                bgp_route_properties[0],
                                extended_community_combinations,
                            )
                        else:
                            self.logger.warning(
                                f"No BgpIPRouteProperty found for IPv4 prefix pool in {network_group.Name}"
                            )

                    # Configure IPv6 prefix pools
                    for ip_prefix_pool in network_group.Ipv6PrefixPools.find():
                        bgp_route_properties = (
                            ip_prefix_pool.BgpV6IPRouteProperty.find()
                        )
                        if bgp_route_properties:
                            self._configure_extended_community_pool_on_route_property(
                                bgp_route_properties[0],
                                extended_community_combinations,
                            )
                        else:
                            self.logger.warning(
                                f"No BgpV6IPRouteProperty found for IPv6 prefix pool in {network_group.Name}"
                            )

            self.logger.info(
                f"Generated {len(extended_community_combinations)} extended community combinations "
                f"with {ext_communities_per_prefix} extended communities each"
            )

            # Apply the changes
            self.apply_changes()
            self.logger.info(
                f"Successfully configured extended community pool for {hostname}:{interface}"
            )

            # Restart protocols if requested
            if restart_protocols:
                self.logger.info(
                    "Restarting protocols after configuring extended community pool"
                )
                self.start_protocols()

            return True

        except Exception as e:
            self.logger.error(f"Error configuring extended community pool: {str(e)}")
            # Try to restart protocols in case of error
            try:
                if restart_protocols:
                    self.logger.info("Attempting to restart protocols after error")
                    self.start_protocols()
            except Exception as restart_error:
                self.logger.error(f"Error restarting protocols: {str(restart_error)}")
            return False

    def _configure_extended_community_pool_on_route_property(
        self,
        bgp_route_prop: t.Union["BgpIPRouteProperty", "BgpV6IPRouteProperty"],
        extended_community_combinations: t.List[t.List[str]],
    ) -> None:
        """
        Configure extended community pool on a BGP route property using ValueList API.

        This method distributes extended community combinations from the pool across routes
        cyclically using Ixia's ValueList feature.

        Args:
            bgp_route_prop: BGP route property object
            extended_community_combinations: List of extended community lists (one per route)
                Example: [["rt:100:1", "rt:100:2"], ["rt:100:3", "rt:100:4"], ...]
        """
        try:
            if not extended_community_combinations:
                self.logger.warning("Empty extended community combinations provided")
                return

            ext_communities_per_prefix = len(extended_community_combinations[0])

            # Step 1: Enable extended communities FIRST (this may initialize BgpExtendedCommunitiesList)
            if not hasattr(bgp_route_prop, "EnableExtendedCommunity"):
                self.logger.warning("EnableExtendedCommunity attribute not found")
                return

            bgp_route_prop.EnableExtendedCommunity.Single(True)
            self.logger.info("Enabled extended communities on route property")

            # Step 2: Try to set number of extended communities per route
            # Note: NoOfExtendedCommunity only exists for EVPN route types, not regular BGP routes
            # For regular BGP routes created via route_scales, Ixia only supports 1 extended community
            if hasattr(bgp_route_prop, "NoOfExtendedCommunity"):
                # EVPN routes support multiple extended communities
                # pyre-ignore[16]: NoOfExtendedCommunity only exists for EVPN route types, checked dynamically
                bgp_route_prop.NoOfExtendedCommunity = ext_communities_per_prefix
                self.logger.info(
                    f"Set NoOfExtendedCommunity to {ext_communities_per_prefix} extended communities per prefix"
                )
            else:
                # Regular BGP routes only support 1 extended community
                self.logger.warning(
                    f"NoOfExtendedCommunity attribute not available for this route type. "
                    f"Regular BGP routes created via route_scales only support 1 extended community. "
                    f"Requested {ext_communities_per_prefix}, but will configure only 1."
                )

            # Step 3: NOW access the BGP extended community list (should have correct count now)
            if not hasattr(bgp_route_prop, "BgpExtendedCommunitiesList"):
                self.logger.warning(
                    "BgpExtendedCommunitiesList attribute not found even after enabling extended communities. "
                    "This may be a limitation of programmatically created routes."
                )
                return

            bgp_ext_community_list = bgp_route_prop.BgpExtendedCommunitiesList.find()

            if not bgp_ext_community_list:
                self.logger.warning("No BgpExtendedCommunitiesList found")
                return

            self.logger.info(
                f"Found {len(bgp_ext_community_list)} extended community positions to configure"
            )

            # Configure each extended community position to cycle through values from the pool
            for ext_comm_idx in range(ext_communities_per_prefix):
                if ext_comm_idx >= len(bgp_ext_community_list):
                    self.logger.warning(
                        f"Not enough extended community list entries ({len(bgp_ext_community_list)}) "
                        f"for {ext_communities_per_prefix} extended communities"
                    )
                    break

                # Collect extended community values at this position from all combinations
                ext_comm_values_at_position = []

                for ext_comm_combination in extended_community_combinations:
                    if ext_comm_idx < len(ext_comm_combination):
                        ext_comm_str = ext_comm_combination[ext_comm_idx]

                        # Parse extended community string
                        # Formats: "rt:AS:VALUE", "soo:AS:VALUE", "target:AS:VALUE"
                        try:
                            if ":" in ext_comm_str:
                                parts = ext_comm_str.split(":")
                                if len(parts) == 3:
                                    # Format: type:AS:VALUE (e.g., "rt:100:1")
                                    ec_type, as_num, value = parts
                                    ext_comm_values_at_position.append(
                                        {
                                            "type": ec_type.lower(),
                                            "as_number": int(as_num),
                                            "value": int(value),
                                        }
                                    )
                                elif len(parts) == 2:
                                    # Format: AS:VALUE (default to route-target)
                                    as_num, value = parts
                                    ext_comm_values_at_position.append(
                                        {
                                            "type": "rt",
                                            "as_number": int(as_num),
                                            "value": int(value),
                                        }
                                    )
                                else:
                                    raise ValueError(
                                        f"Invalid extended community format: {ext_comm_str}"
                                    )
                            else:
                                # Integer format (not typical for extended communities)
                                self.logger.warning(
                                    f"Unexpected integer format for extended community: {ext_comm_str}"
                                )
                                ext_comm_values_at_position.append(
                                    {"type": "rt", "as_number": 0, "value": 0}
                                )
                        except (ValueError, IndexError) as e:
                            self.logger.warning(
                                f"Invalid extended community format '{ext_comm_str}': {e}"
                            )
                            ext_comm_values_at_position.append(
                                {"type": "rt", "as_number": 0, "value": 0}
                            )
                    else:
                        # This combination doesn't have an extended community at this position
                        ext_comm_values_at_position.append(
                            {"type": "rt", "as_number": 0, "value": 0}
                        )

                # Apply ValueList to cycle through extended community values
                bgp_ext_community = bgp_ext_community_list[ext_comm_idx]

                # Set extended community type using Ixia enum values
                # Valid enum values: 0=administratoras2octet, 1=administratorip, 2=administratoras4octet,
                # 3=opaque, 6=evpn, 64=administratoras2octetlinkbw, 255=custom
                if hasattr(bgp_ext_community, "Type"):
                    # Map common types to Ixia extended community type enums
                    ec_type = ext_comm_values_at_position[0]["type"]
                    type_mapping = {
                        "rt": "administratoras2octet",  # Route Target (enum 0)
                        "soo": "opaque",  # Site of Origin (enum 3)
                        "target": "administratoras2octet",  # Route Target (enum 0)
                    }
                    # pyrefly: ignore [no-matching-overload]
                    ixia_type = type_mapping.get(ec_type, "administratoras2octet")
                    bgp_ext_community.Type.Single(ixia_type)

                # Configure the AS number field with ValueList
                if hasattr(bgp_ext_community, "AsNumber"):
                    as_numbers = [ec["as_number"] for ec in ext_comm_values_at_position]
                    bgp_ext_community.AsNumber.ValueList(as_numbers)

                # Configure the assigned number field with ValueList
                if hasattr(bgp_ext_community, "AssignedNumberSubType"):
                    values = [ec["value"] for ec in ext_comm_values_at_position]
                    bgp_ext_community.AssignedNumberSubType.ValueList(values)

                self.logger.debug(
                    f"Extended community position {ext_comm_idx}: cycling through {len(ext_comm_values_at_position)} values"
                )

            self.logger.info(
                f"Successfully configured extended community distribution for {len(extended_community_combinations)} routes"
            )
            self.logger.info(
                f"  - Each route will get {ext_communities_per_prefix} extended communities from the pool"
            )
            self.logger.info(
                "  - Extended communities will cycle: route 1 → combination 1, route 2 → combination 2, ..."
            )

        except Exception as e:
            self.logger.warning(f"Error configuring extended community pool: {str(e)}")

    def import_bgp_attribute_profile_from_configerator(
        self,
        bgp_route_import_file_path: str,
        base_path: str = "taac/bgp_attribute_profiles",
    ) -> str:
        """Import BGP attribute profile from configerator.

        Args:
            bgp_route_import_file_path: The file path/name for the BGP route import file
            base_path: The base path in configerator where BGP attribute profiles are stored.
                      Defaults to "taac/bgp_attribute_profiles"

        Returns:
            The config contents as a string
        """
        bgp_route_attribute_profile_path = f"{base_path}/{bgp_route_import_file_path}"
        bgp_routes_config = self.cfgr_client.get_config_contents(
            bgp_route_attribute_profile_path
        )
        return bgp_routes_config

    def import_bgp_routes(
        self,
        port_identifier: str,
        ip_address_family: ixia_types.IpAddressFamily,
        import_bgp_routes_params_list: t.Sequence[ixia_types.ImportBgpRoutesParams],
        device_group_obj: "DeviceGroup",
        device_group_index: "DeviceGroupIndex",
    ) -> None:
        prefix_pool_attr_map = {
            ixia_types.IpAddressFamily.IPV4: (
                "Ipv4PrefixPools",
                DESIRED_V4_BGP_PREFIX_NAME,
            ),
            ixia_types.IpAddressFamily.IPV6: (
                "Ipv6PrefixPools",
                DESIRED_V6_BGP_PREFIX_NAME,
            ),
        }
        bgp_route_property_attr_map = {
            ixia_types.IpAddressFamily.IPV4: "BgpIPRouteProperty",
            ixia_types.IpAddressFamily.IPV6: "BgpV6IPRouteProperty",
        }
        for import_bgp_routes_params in import_bgp_routes_params_list:
            network_group_identifier = (
                f"N{import_bgp_routes_params.network_group_index}_{port_identifier}"
            )
            try:
                prefix_pool_attr, desired_network_group_name_template = (
                    prefix_pool_attr_map[ip_address_family]
                )
                bgp_route_property_attr = bgp_route_property_attr_map[ip_address_family]
            except KeyError:
                raise ValueError("Unsupported BGP prefix family type")
            desired_network_group_name = desired_network_group_name_template.format(
                port_identifier=network_group_identifier
            )
            bgp_routes_import_file = (
                self.import_bgp_attribute_profile_from_configerator(
                    import_bgp_routes_params.bgp_route_import_file_path,
                )
            )
            network_group_obj = device_group_obj.NetworkGroup.find(
                Name=desired_network_group_name
            ) or device_group_obj.NetworkGroup.add(
                Name=desired_network_group_name,
            )
            network_group_index = NetworkGroupIndex(network_group=network_group_obj)
            device_group_index.network_group_indices[
                import_bgp_routes_params.network_group_index
            ] = network_group_index
            ip_prefix_pool_cls = getattr(network_group_obj, prefix_pool_attr)
            ip_prefix_pool_obj = ip_prefix_pool_cls.add()
            if import_bgp_routes_params.prefix_pool_name:
                ip_prefix_pool_obj.Name = import_bgp_routes_params.prefix_pool_name
            bgp_ip_route_property_cls = getattr(
                ip_prefix_pool_obj, bgp_route_property_attr
            )
            bgp_ip_route_property = bgp_ip_route_property_cls.add()
            set_next_hop_type = (
                import_bgp_routes_params.set_next_hop_type
                or ixia_types.SetNextHopType.MANUALLY
            )
            bgp_ip_route_property.NextHopType.Single(
                ixia_types.SET_NEXT_HOP_TYPE_MAP[set_next_hop_type]
            )
            bgp_ip_route_property.NextHopIPType.Single(ip_address_family.name.lower())
            temp_file_path = import_bgp_routes_params.bgp_route_import_file_path.split(
                "/"
            )[-1]
            bgp_routes_import_file_list = bgp_routes_import_file.split("\n")
            bgp_routes_import_file_list_in_chunks = split_list_into_chunks(
                bgp_routes_import_file_list[1:], import_bgp_routes_params.multiplier
            )
            chunk_start_idx = import_bgp_routes_params.start_index or 0
            chunk_end_idx = import_bgp_routes_params.end_index or len(
                bgp_routes_import_file_list_in_chunks
            )
            with open(temp_file_path, "w") as f:
                f.write(bgp_routes_import_file_list[0] + "\n")
                for chunk_idx, chunk in enumerate(
                    bgp_routes_import_file_list_in_chunks
                ):
                    if chunk_idx >= chunk_start_idx and chunk_idx < chunk_end_idx:
                        f.write("\n".join(chunk))
            bgp_ip_route_property.ImportBgpRoutes(
                Arg2=ixia_types.BGP_ROUTE_DISTRIBUTION_TYPE_MAP[
                    import_bgp_routes_params.bgp_route_distribution_type
                ],
                Arg3=import_bgp_routes_params.import_only_best_routes,
                Arg4=ixia_types.BGP_NEXT_HOP_MODIFICATION_TYPE_MAP[
                    import_bgp_routes_params.bgp_next_hop_modification_type
                ],
                Arg5=ixia_types.BGP_ROUTE_IMPORT_FILE_TYPE_MAP[
                    import_bgp_routes_params.import_file_type
                ],
                Arg6=(Files(temp_file_path, local_file=True)),
            )
            network_group_obj.Multiplier = import_bgp_routes_params.multiplier
            if import_bgp_routes_params.bgp_attribute_configs:
                self.configure_bgp_attributes(
                    bgp_ip_route_property,
                    import_bgp_routes_params.bgp_attribute_configs,
                )

    def configure_bgp_attributes(
        self,
        bgp_ip_route_property: "BgpIPRouteProperty",
        bgp_attribute_configs: t.Sequence[ixia_types.BgpAttributeConfig],
    ) -> None:
        """Configure BGP attributes for a given IP route property."""

        for config in bgp_attribute_configs:
            assert config.value_lists or config.file_path

            if config.attribute not in [
                ixia_types.BgpAttribute.COMMUNITIES,
                ixia_types.BgpAttribute.EXT_COMMUNITIES,
            ]:
                continue
            # Extract communities from file or value lists
            if config.value_lists:
                communities_list_of_lists = config.value_lists
            else:
                bgp_communities_file = (
                    self.import_bgp_attribute_profile_from_configerator(
                        config.file_path  # pyre-ignore
                    )
                )
                communities_list_of_lists = self._parse_communities_file(
                    bgp_communities_file
                )
            # Enable community and set number of communities
            bgp_ip_route_property.EnableCommunity.Single(True)
            no_of_communities = len(communities_list_of_lists[0])

            if config.attribute == ixia_types.BgpAttribute.COMMUNITIES:
                bgp_ip_route_property.NoOfCommunities = no_of_communities
                communities_list = bgp_ip_route_property.BgpCommunitiesList.find()
            else:
                bgp_ip_route_property.NoOfExternalCommunities = no_of_communities
                communities_list = (
                    bgp_ip_route_property.BgpExtendedCommunitiesList.find()
                )
            # Distribute communities among community objects
            community_obj_to_community_list = self.distribute_communities(
                communities_list,
                communities_list_of_lists,
                config.distribution_type,
            )
            # Set AS numbers and last two octets for each community object
            for (
                community_obj,
                community_list,
            ) in community_obj_to_community_list.items():
                as_numbers, last_two_octets = self._split_community_values(
                    community_list
                )
                community_obj.Type.Single(
                    ixia_types.BGP_COMMUNITY_TYPE_MAP[
                        config.bgp_community_type or ixia_types.BgpCommunityType.MANUAL
                    ]
                )
                if config.attribute == ixia_types.BgpAttribute.COMMUNITIES:
                    community_obj.AsNumber.ValueList(as_numbers)
                    community_obj.LastTwoOctets.ValueList(last_two_octets)
                else:
                    community_obj.AsNumber4Bytes.ValueList(as_numbers)
                    community_obj.AssignedNumber4Bytes.ValueList(last_two_octets)

    def _parse_communities_file(self, file_content: str) -> list[list[str]]:
        """Parse a communities file into a list of community lists."""

        communities_list_of_lists = []
        for row in file_content.split("\n"):
            community_list = []
            values = row.split(",")
            for i in range(0, len(values), 2):
                if i + 1 < len(values):  # Ensure we have both AS and Last Two Octets
                    as_num = values[i]
                    last_two_octets = values[i + 1]
                    community_list.append(f"{as_num}:{last_two_octets}")
            communities_list_of_lists.append(community_list)
        return communities_list_of_lists

    def _split_community_values(
        self, community_list: list[str]
    ) -> tuple[list[str], list[str]]:
        """Split community values into AS numbers and last two octets."""
        as_numbers = []
        last_two_octets = []
        for community in community_list:
            as_number, last_two_octet = community.split(":")
            as_numbers.append(as_number)
            last_two_octets.append(last_two_octet)
        return as_numbers, last_two_octets

    def distribute_communities(
        self,
        bgp_communities_list: t.List,
        communities_list_of_lists: t.Sequence[t.Sequence[str]],
        distribution_type: ixia_types.DistribitionType,
    ) -> dict:
        assert len(bgp_communities_list) == len(communities_list_of_lists[0])
        count = bgp_communities_list[0].Count
        bgp_communities_list_obj_to_community_list = defaultdict(list)
        repeated_communities_list_of_lists = itertools.cycle(communities_list_of_lists)
        community_lists = []
        if distribution_type == ixia_types.DistribitionType.ROUND_ROBIN:
            # Distribute communities round-robin
            community_lists = [
                next(repeated_communities_list_of_lists) for _ in range(count)
            ]
        elif distribution_type == ixia_types.DistribitionType.RANDOMIZE:
            # Distribute communities randomly
            # Repeat the community values to match the count
            repeated_community_values = list(
                itertools.islice(
                    itertools.cycle(repeated_communities_list_of_lists), count
                )
            )
            # Shuffle the repeated community values
            random.shuffle(repeated_community_values)
            community_lists = repeated_community_values
        bgp_communities_list_obj_to_community_list = dict(
            zip(
                bgp_communities_list, [list(row) for row in list(zip(*community_lists))]
            )
        )
        return bgp_communities_list_obj_to_community_list

    # Note: This function is computationally expensive and may take up to 30 seconds to run.
    # It is memoized with @memoize_forever because the mapping is unlikely to change during a test run.
    @memoize_forever
    def map_prefix_pools_to_network_groups(self) -> t.Tuple[dict, dict]:
        """
        Maps IPv6 and IPv4 prefix pools to their corresponding network groups.
        This function iterates through all network groups and their associated prefix pools,
        collecting mappings from each IPv6 and IPv4 prefix pool name to the network group it belongs to.
        Since IPv6 and IPv4 prefix pools can share the same name, two separate dictionaries are maintained:
        one for IPv6 prefix pools and one for IPv4 prefix pools.
        """
        ipv6_prefix_pool_to_network_group_map = {}
        ipv4_prefix_pool_to_network_group_map = {}
        network_groups = self.find_network_groups()
        for network_group in network_groups:
            for v6_prefix_pool in network_group.Ipv6PrefixPools.find():
                ipv6_prefix_pool_to_network_group_map[v6_prefix_pool.Name] = (
                    network_group
                )
            for v4_prefix_pool in network_group.Ipv4PrefixPools.find():
                ipv4_prefix_pool_to_network_group_map[v4_prefix_pool.Name] = (
                    network_group
                )
        return (
            ipv6_prefix_pool_to_network_group_map,
            ipv4_prefix_pool_to_network_group_map,
        )

    def map_prefix_pool_to_network_group(
        self, prefix_pool_obj: t.Union["Ipv4PrefixPools", "Ipv6PrefixPools"]
    ) -> "NetworkGroup":
        ipv6_prefix_pool_to_network_group_map, ipv4_prefix_pool_to_network_group_map = (
            self.map_prefix_pools_to_network_groups()
        )
        if isinstance(prefix_pool_obj, Ipv4PrefixPools):
            return ipv4_prefix_pool_to_network_group_map[prefix_pool_obj.Name]
        else:
            return ipv6_prefix_pool_to_network_group_map[prefix_pool_obj.Name]

    # Note: This function is computationally expensive and may take up to 30 seconds to run.
    # It is memoized with @memoize_forever because the mapping is unlikely to change during a test run.
    @memoize_forever
    def map_prefix_pools_to_device_groups(self) -> t.Tuple[dict, dict]:
        """
        Maps IPv6 and IPv4 prefix pools to their corresponding device groups.
        This function iterates through all device groups and their associated network groups,
        collecting mappings from each IPv6 and IPv4 prefix pool name to the device group it belongs to.
        Since IPv6 and IPv4 prefix pools can share the same name, two separate dictionaries are maintained:
        one for IPv6 prefix pools and one for IPv4 prefix pools.
        """
        ipv6_prefix_pool_to_device_group_map = {}
        ipv4_prefix_pool_to_device_group_map = {}
        device_group_obj_list = self.find_device_groups()
        for device_group in device_group_obj_list:
            network_group_obj_list = device_group.NetworkGroup.find()
            for network_group_obj in network_group_obj_list:
                for v6_prefix_pool in network_group_obj.Ipv6PrefixPools.find():
                    ipv6_prefix_pool_to_device_group_map[v6_prefix_pool.Name] = (
                        device_group
                    )
                for v4_prefix_pool in network_group_obj.Ipv4PrefixPools.find():
                    ipv4_prefix_pool_to_device_group_map[v4_prefix_pool.Name] = (
                        device_group
                    )
        return (
            ipv6_prefix_pool_to_device_group_map,
            ipv4_prefix_pool_to_device_group_map,
        )

    def map_prefix_pool_to_device_group(
        self, prefix_pool_obj: t.Union["Ipv4PrefixPools", "Ipv6PrefixPools"]
    ) -> "DeviceGroup":
        ipv6_prefix_pool_to_device_group_map, ipv4_prefix_pool_to_device_group_map = (
            self.map_prefix_pools_to_device_groups()
        )
        if isinstance(prefix_pool_obj, Ipv4PrefixPools):
            return ipv4_prefix_pool_to_device_group_map[prefix_pool_obj.Name]
        else:
            return ipv6_prefix_pool_to_device_group_map[prefix_pool_obj.Name]

    def map_prefix_pool_to_bgp_peer(
        self, prefix_pool_obj: t.Union["Ipv4PrefixPools", "Ipv6PrefixPools"]
    ) -> t.Union["BgpIpv4Peer", "BgpIpv6Peer"]:
        device_group_obj = self.map_prefix_pool_to_device_group(prefix_pool_obj)
        if isinstance(prefix_pool_obj, Ipv4PrefixPools):
            return device_group_obj.Ethernet.find().Ipv4.find().BgpIpv4Peer.find()
        else:
            return device_group_obj.Ethernet.find().Ipv6.find().BgpIpv6Peer.find()

    def _get_modified_dscp_bits(
        self,
        dscp_decimal_value: int,
        ip_address_family: ixia_types.IpAddressFamily,
        ecn_capability: ixia_types.EcnCapability,
    ) -> t.List[int]:
        """Gets the DSCP bits for an IP version

        Returns the actual DSCP value -
        for IPv4 this would be ToS, and TC for IPv6.
        A specific value will win over a Queue specification.
        """
        if ip_address_family == ixia_types.IpAddressFamily.IPV6:
            return self._get_modified_ipv6_bits(dscp_decimal_value, ecn_capability)
        return [dscp_decimal_value]

    def _get_modified_ipv6_bits(
        self, dscp_decimal_value: int, ecn_capability: ixia_types.EcnCapability
    ) -> t.List[int]:
        """Gets the modified IPv6 bits

        IXIA specific behaviour
        IPv6 side DSCP configuration on ixia is raw input.
        Need to include last 2 bits (unused – reserved) into
        the calculation.
        For example, if you make DSCP AF21, which is 010010 in binary,
        and 18 in Decimal, in actual 8 bits, it will be “01001000" and
        you may need to put 72.

        Args:
            dscp_decimal_value: An integer defining the decimal
                value of DSCP.

        Returns:
            An integer defining the binary value of DSCP.
        """

        if 0 > dscp_decimal_value > 64:
            raise InvalidDSCPValueError(
                f"INCORRECT DSCP VALUE: {dscp_decimal_value}."
                "Acceptable range is [0, 64)"
            )
        if ecn_capability == ixia_types.EcnCapability.ECN_CAPABLE:
            last_two_bits = ["10"]
        elif ecn_capability == ixia_types.EcnCapability.MIXED:
            last_two_bits = ["10", "00"]
        else:
            last_two_bits = ["00"]
        return [int(bin(dscp_decimal_value) + bits, 2) for bits in last_two_bits]

    def configure_qos_config(
        self,
        config_element: "ConfigElement",
        qos_config: ixia_types.QoSConfig,
        ip_address_family: ixia_types.IpAddressFamily,
    ) -> None:
        """Configures the QoS configuration

        Configures the QoS configuration for a traffic item.
        The QoS configuration can be used to set the DSCP value
        for both IPv4(ToS) and IPv6(TC). Can be used to
        set one specific value or a range of values.
        """
        dscp_values = self._get_modified_dscp_bits(
            qos_config.dscp_value,
            ip_address_family,
            qos_config.ecn_capability,
        )
        field_name = ixia_types.DSCP_MAP[qos_config.phb_type]
        self.configure_dscp(
            config_element,
            ip_address_family,
            field_name,
            dscp_values,
        )

    def configure_dscp(
        self,
        config_element: "ConfigElement",
        ip_address_family: ixia_types.IpAddressFamily,
        field_name: str,
        dscp_values: t.List[int],
    ) -> None:
        """Configures the DSCP value

        Configures a traffic item with the DSCP value
        for both IPv4(ToS) and IPv6(TC). Can be used to
        set one specific value

        Args:
            traffic_item_obj: An object of type IxiaTrafficItem
            ip_family: A string defining the IP version.
            field_name: A string defining the name to be used
                as the Display Name to find the packet header
                field object.
            dscp_value: An integer defining the DSCP value to
                be set.
        """
        packet_header_stack_obj = config_element.Stack.find(
            DisplayName=self._get_ip_address_family_str(ip_address_family)
        )
        packet_header_field_obj = packet_header_stack_obj.Field.find()
        dscp_field = packet_header_field_obj.find(DisplayName=field_name)
        dscp_field.ActiveFieldChoice = True
        if len(dscp_values) == 1:
            dscp_field.ValueType = "singleValue"
            dscp_field.SingleValue = dscp_values[0]
        else:
            dscp_field.ValueType = "valueList"
            dscp_field.ValueList = dscp_values

    def configure_traffic_items_on_the_fly(
        self,
        traffic_item_name: str,
        line_rate: t.Optional[int],
        line_rate_type: t.Optional[ixia_types.RateType],
        frame_size_setting: t.Optional[ixia_types.FrameSize],
        qos_config: t.Optional[ixia_types.QoSConfig],
    ) -> None:
        traffic_item_obj = self.ixnetwork.Traffic.TrafficItem.find(
            Name=traffic_item_name
        )
        if not traffic_item_obj:
            self.logger.debug(
                f"Traffic item {traffic_item_name} not found. Skipping..."
            )
            return

        ip_address_family = None
        if qos_config:
            if traffic_item_obj.TrafficType == "ipv6":
                ip_address_family = ixia_types.IpAddressFamily.IPV6
            elif traffic_item_obj.TrafficType == "ipv4":
                ip_address_family = ixia_types.IpAddressFamily.IPV4

        # Bidirectional traffic items have multiple ConfigElements (one per
        # direction).  Apply settings to ALL of them so line rate, frame size,
        # and QoS/DSCP are consistent in both directions.
        config_elements = traffic_item_obj.ConfigElement.find()
        for config_element in config_elements:
            if line_rate or line_rate_type:
                self.configure_line_rate(config_element, line_rate, line_rate_type)
            if frame_size_setting:
                self.configure_frame_size(config_element, frame_size_setting)
            if qos_config:
                self.configure_qos_config(
                    config_element,
                    qos_config,
                    none_throws(ip_address_family),
                )
        traffic_item_obj.Generate()

    @external_api
    def start_packet_capture(
        self,
        hostname: str,
        interface: str,
        capture_filter: str = "tcp port 179",
        control_plane: bool = True,
    ) -> str:
        """
        Start packet capture on IXIA port.

        This method starts packet capture on the specified IXIA port, which is much
        more reliable than using tcpdump on the device for BGP message analysis.

        Note: The capture is performed at the wire level (all traffic), and filtering
        is done during tshark analysis. This approach is more reliable than hardware-level
        BPF filtering and ensures complete packet capture.

        Args:
            hostname: Device hostname (e.g., "eb04.lab.ash6")
            interface: Interface name (e.g., "Ethernet3/1/1")
            capture_filter: Informational - describes what will be filtered during
                          tshark analysis (default: "tcp port 179" for BGP)
            control_plane: If True, capture control plane traffic (BGP, protocols).
                          If False, capture data plane traffic (user traffic flows).
                          Default: True (for BGP control plane capture)

        Returns:
            str: Vport href for later reference

        Raises:
            ValueError: If port not found or capture cannot be started

        Example:
            >>> # Capture BGP control plane traffic (default)
            >>> ixia = Ixia(...)
            >>> vport_href = ixia.start_packet_capture(
            ...     hostname="eb04.lab.ash6",
            ...     interface="Ethernet3/1/1"
            ... )

            >>> # Capture data plane traffic
            >>> vport_href = ixia.start_packet_capture(
            ...     hostname="eb04.lab.ash6",
            ...     interface="Ethernet3/1/1",
            ...     capture_filter="",
            ...     control_plane=False
            ... )
        """
        # Get port identifier
        port_identifier = self.get_port_identifier(f"{hostname}:{interface}")

        # Get vport for this port
        desired_vport_name: str = DESIRED_VPORT_NAME.format(
            port_identifier=port_identifier
        )
        vport: "Vport" = self.ixnetwork.Vport.find(Name=desired_vport_name)

        if not vport:
            raise ValueError(
                f"Vport not found for {port_identifier}. "
                f"Ensure port is configured in test."
            )

        self.logger.info(f"Starting packet capture on IXIA port: {desired_vport_name}")
        self.logger.info(
            f"  Capture type: {'Control plane' if control_plane else 'Data plane'}"
        )
        self.logger.info(
            f"  Will filter for: {capture_filter} (during tshark analysis)"
        )

        # Enable packet capture
        try:
            # Set capture mode to enable packet capture on this vport
            # RxMode options: "capture", "captureAndMeasure", "measure"
            vport.RxMode = "capture"

            # Configure capture settings based on IXIA RestPy API
            capture = vport.Capture

            if control_plane:
                # For control plane traffic (BGP, protocols), use SOFTWARE capture
                # Control plane protocols run on the IXIA CPU, not in hardware
                self.logger.info("  Configuring SOFTWARE capture (control plane)")
                capture.SoftwareEnabled = True
                capture.HardwareEnabled = False

                # Set control capture buffer settings
                capture.ControlBufferBehaviour = "bufferLiveNonCircular"
                capture.ControlBufferSize = 30  # MB
                # Use "specificInterface" to capture only from this vport's interface
                # Using "anyInterface" causes all vports to capture from all interfaces
                capture.ControlInterfaceType = "specificInterface"

                # Set capture mode for continuous capture
                capture.CaptureMode = "captureContinuousMode"

                # Set slice size to capture full packets (important for protocol analysis)
                capture.SliceSize = 65535
            else:
                # For data plane traffic (user traffic flows), use HARDWARE capture
                # Hardware capture is for wire-rate packet capture of data plane traffic
                self.logger.info("  Configuring HARDWARE capture (data plane)")
                capture.HardwareEnabled = True
                capture.SoftwareEnabled = False

                # Hardware capture settings
                capture.SliceSize = 65535  # Full packet capture

            # Clear any previous capture data to ensure fresh capture
            try:
                self.logger.info("  Clearing previous capture data...")
                # pyre-fixme[16]: Only UhdVport has ClearStats, not IxnVport
                if hasattr(vport, "ClearStats"):
                    vport.ClearStats()  # type: ignore
            except Exception as clear_error:
                self.logger.warning(
                    f"  Could not clear previous capture data: {clear_error}"
                )
                # Continue anyway - this is not critical

            # Note: We capture control plane traffic (BGP on TCP 179).
            # The tshark command uses: -Y 'bgp.type == 2' to filter BGP UPDATE messages.

            # Start capture at session level (IxNetwork API pattern)
            # This triggers capture on vports with RxMode="capture"
            self.ixnetwork.StartCapture()

            self.logger.info(f"✓ Packet capture started on {desired_vport_name}")
            self.logger.info(
                "  (Capturing all traffic - will filter with tshark later)"
            )

            return vport.href

        except Exception as e:
            self.logger.error(
                f"✗ Failed to start packet capture on {desired_vport_name}: {e}"
            )
            raise ValueError(f"Failed to start packet capture: {e}")

    @external_api
    def stop_packet_capture(
        self,
        vport_href: str,
    ) -> None:
        """
        Stop packet capture on IXIA port.

        Note: StopCapture() is a session-level operation that stops ALL packet captures.
        This method tracks whether capture has already been stopped to avoid errors when
        stopping multiple captures in the same session.

        Args:
            vport_href: Vport href returned by start_packet_capture()

        Raises:
            ValueError: If capture cannot be stopped

        Example:
            >>> ixia.stop_packet_capture(vport_href)
        """
        try:
            self.logger.info(f"Stopping packet capture (href: {vport_href})")

            # Check if we've already stopped capture for this session
            if self._capture_stopped:
                self.logger.info(
                    "✓ Packet capture already stopped (session-level operation)"
                )
                return

            # StopCapture() is a session-level operation that stops ALL captures
            try:
                self.ixnetwork.StopCapture()
                self._capture_stopped = True  # Mark as stopped
                self.logger.info("✓ Packet capture stopped (all vports)")
            except Exception as stop_err:
                # If StopCapture fails, check if it's a benign error
                error_msg = str(stop_err).lower()
                if any(
                    keyword in error_msg
                    for keyword in [
                        "not started",
                        "not running",
                        "no active capture",
                        "already stopped",
                        "abnormally stopped",
                        "capture is not active",
                    ]
                ):
                    self.logger.warning(
                        f"Capture already stopped or inactive: {stop_err}"
                    )
                    self._capture_stopped = True  # Mark as stopped even if benign error
                else:
                    # Real error - re-raise
                    raise

        except Exception as e:
            self.logger.error(f"✗ Failed to stop packet capture: {e}")
            raise ValueError(f"Failed to stop packet capture: {e}")

    @external_api
    def save_capture_to_pcap(
        self,
        vport_href: str,
        pcap_filename: str = "bgp_capture.pcap",
    ) -> str:
        """
        Save IXIA capture to PCAP file on IXIA server.

        Args:
            vport_href: Vport href returned by start_packet_capture()
            pcap_filename: Name for the PCAP file (default: "bgp_capture.pcap")

        Returns:
            str: Path to PCAP file on IXIA server

        Raises:
            ValueError: If capture cannot be saved

        Example:
            >>> pcap_path = ixia.save_capture_to_pcap(vport_href, "bgp_test.pcap")
        """
        try:
            # Find vport by href
            # Get all vports and find the one matching the href
            all_vports = self.ixnetwork.Vport.find()
            vport = None
            for v in all_vports:
                if v.href == vport_href:
                    vport = v
                    break

            if not vport:
                raise ValueError(f"Could not find vport with href: {vport_href}")

            self.logger.info(
                f"Saving capture from {vport.Name} to PCAP: {pcap_filename}"
            )

            # Export capture to PCAP file on IXIA server
            # Use the vport's capture buffer and export to file
            # The file is saved in the default captures directory on the IXIA chassis
            pcap_path = (
                f"/root/.local/share/Ixia/sdmStreamManager/common/{pcap_filename}"
            )

            # Execute the export action on the vport
            # NOTE: ExportCaptureAsPcap method does not exist in RestPy API
            # Use SaveCaptureFiles instead which saves all active captures

            # Create a directory name from the filename
            save_dir = pcap_filename.replace(".pcap", "").replace(".cap", "")

            # SaveCaptureFiles saves all captures to the specified directory
            # Returns a list of relative paths
            saved_files = self.ixnetwork.SaveCaptureFiles(save_dir)

            if not saved_files or len(saved_files) == 0:
                raise ValueError("No capture files were saved")

            # Filter to find the capture file for this specific vport
            # File names contain vport name, e.g.: "VPORT_EB03.LAB.ASH6-ETHERNET3-1-1_SW.cap"
            # vport.Name format: "VPORT_EB03.LAB.ASH6:ETHERNET3/1/1"
            # We need to match the vport name pattern in the filename
            vport_name_normalized = (
                vport.Name.replace(":", "-").replace("/", "-").upper()
            )

            matching_file = None
            for saved_file in saved_files:
                # Extract filename from path (e.g., "captures/dir/VPORT_NAME.cap")
                filename = saved_file.split("/")[-1].upper()
                # Check if this file corresponds to our vport
                if vport_name_normalized in filename:
                    matching_file = saved_file
                    break

            if not matching_file:
                self.logger.warning(
                    f"Could not find capture file matching vport {vport.Name}. "
                    f"Available files: {saved_files}"
                )
                # Fall back to first file (old behavior)
                matching_file = saved_files[0]
                self.logger.warning(f"Using first file as fallback: {matching_file}")

            pcap_path = matching_file

            self.logger.info(f"✓ Capture saved to: {pcap_path}")
            self.logger.info(
                f"  Full path on IXIA: /root/.local/share/Ixia/{pcap_path}"
            )

            return pcap_path

        except Exception as e:
            self.logger.error(f"✗ Failed to save capture to PCAP: {e}")
            raise ValueError(f"Failed to save capture: {e}")

    @external_api
    def download_capture_file(
        self,
        remote_pcap_path: str,
        local_pcap_path: str,
    ) -> str:
        """
        Download PCAP file from IXIA server to local dev server.

        Args:
            remote_pcap_path: Relative path on IXIA (from save_capture_to_pcap)
            local_pcap_path: Local path to save PCAP (e.g., "/tmp/bgp_capture.pcap")

        Returns:
            str: Local path to downloaded PCAP file

        Raises:
            ValueError: If download fails

        Example:
            >>> local_path = ixia.download_capture_file(
            ...     remote_pcap_path="captures/bgp_test/VPORT_NAME_SW.cap",
            ...     local_pcap_path="/tmp/bgp_capture.pcap"
            ... )
        """
        try:
            self.logger.info("Downloading PCAP from IXIA...")
            self.logger.info(f"  Remote: {remote_pcap_path}")
            self.logger.info(f"  Local:  {local_pcap_path}")

            # Use session.Session.DownloadFile() - this is the working method!
            # Downloads from IXIA server to local dev server
            self.session.Session.DownloadFile(
                remote_pcap_path,  # Relative path on IXIA server
                local_pcap_path,  # Local destination path
            )

            self.logger.info(f"✓ PCAP downloaded to: {local_pcap_path}")

            # Verify file was downloaded
            import os

            if os.path.exists(local_pcap_path):
                file_size = os.path.getsize(local_pcap_path)
                self.logger.info(
                    f"  File size: {file_size:,} bytes ({file_size / 1024 / 1024:.2f} MB)"
                )
            else:
                raise ValueError(f"Downloaded file not found at {local_pcap_path}")

            return local_pcap_path

        except Exception as e:
            self.logger.error(f"✗ Failed to download PCAP file: {e}")
            raise ValueError(f"Failed to download PCAP: {e}")
