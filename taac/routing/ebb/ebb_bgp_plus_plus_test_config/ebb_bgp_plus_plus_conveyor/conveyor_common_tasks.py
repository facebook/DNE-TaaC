# pyre-unsafe
"""
Common setup and teardown tasks shared across EBB BGP++ conveyor test configs.

These functions generate the standard set of tasks needed for any EBB BGP++
conveyor test, parameterized by device-specific values (hostname, interfaces,
BGP ASN, speed, configerator paths, etc.).

The following tasks are included:
    Helper functions:
    - _get_pre_ixia_interface_tasks: Configure IXIA interfaces pre-IXIA
    - _get_bgpcpp_deployment_tasks: Deploy BGP++ configs, certs, daemons
    - _get_control_plane_tasks: ACLs + daemon enable
    - _get_full_scale_ip_config_tasks: Full-scale IP config (140 EBGP + 8 planes)
    - _get_openr_setup_tasks: OpenR Port-Channel + route injection
    - _get_iptables_flush_tasks: Flush EOS_BGP iptables
"""

import base64
import ipaddress
import json
import typing as t

from taac.constants import (
    BgpPlusPlusProfile,
    DEFAULT_OPENR_START_IPV4S,
    DEFAULT_OPENR_START_IPV6S,
    OpenRRouteAction,
)
from taac.routing.ebb.ebb_bgp_plus_plus_test_config.ebb_bgp_plus_plus_conveyor.conveyor_constants import (
    ACL_COMMANDS,
    BGP_MON_PEER_COUNT,
    BGPCPP_DAEMONS,
    EBGP_PEER_COUNT_V4,
    EBGP_PEER_COUNT_V6,
    FIBAGENT_BGP_CONF_DEPLOY_CMD,
    FIBAGENT_CONF_DEPLOY_CMD,
    IBGP_PEER_SCALE_PER_PLANE,
    IXIA_BGP_MON_IC_PARENT_NETWORK,
    IXIA_EBGP_IC_PARENT_NETWORK_V4,
    IXIA_EBGP_IC_PARENT_NETWORK_V6,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE2,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE3,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE4,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE1,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE2,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE3,
    IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE4,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE2,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE3,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE4,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE1,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE2,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE3,
    IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE4,
    IXIA_IPV4_START_OFFSET,
    IXIA_IPV6_START_OFFSET,
    OPENR_LOCAL_LINK,
    OPENR_OTHER_LINK,
    OPENR_PORT_CHANNEL,
    OPENR_PORT_CHANNEL_ID,
    OPENR_PORT_CHANNEL_IPV4,
    OPENR_PORT_CHANNEL_IPV6,
    OPENR_PORT_CHANNEL_LINK_LOCAL,
    OPENR_PORT_CHANNEL_MEMBER,
    UPDATE_GROUP_CONFIG,
)
from taac.task_definitions import (
    create_arista_create_file_from_config_task,
    create_arista_daemon_control_task,
    create_deploy_tls_certs_task,
    create_interface_ip_cleanup_task,
    create_interface_ip_configuration_task,
    create_openr_route_action_task,
    create_run_commands_on_shell_task,
    create_set_bgp_setting_config_task,
    create_validate_bgpcpp_config_on_device_task,
)
from taac.test_as_a_config.types import Task

# Lazy import — `_generate_bgpcpp_peers_modification_tasks` lives in
# `testconfigs.routing.ebb.case1_test_config`. Importing it at module load time creates
# a circular import once any other `testconfigs/routing/ebb/*` test config (e.g.,
# `bag010_ash6_test_config`) imports `conveyor_common_tasks`, because that
# import chain re-enters `testconfigs.routing.ebb.__init__`. Defer to call time.

BGPCPP_CONFIG_PATH = "/mnt/flash/bgpcpp_config"

# Thrift ACL files on device where intern userid should be added for auth
THRIFT_ACL_FILES = [
    "/usr/facebook/thrift_acls/Bgpd_lab.json",
    "/usr/facebook/thrift_acls/FibAgent.json",
    "/usr/facebook/thrift_acls/FibAgent_lab.json",
]

INTERN_USER_IDS = [
    "1179835461009564",
    "1414546347",
    "1531998838006730",
]


# =============================================================================
# Helper: Add user IDs to thrift ACL files
# =============================================================================
def _get_add_intern_userid_tasks(
    device_name: str,
) -> t.List[Task]:
    """
    Add intern userids to thrift ACL files on the device if not already present.

    Writes a Python script to /tmp on the device via base64 encoding (avoiding
    shell quoting issues with FCR), then executes it.

    For each ACL file, reads the JSON, checks every permission action's entries
    for each userid, and appends it if missing. Skips files that don't exist.

    Args:
        device_name: Device hostname

    Returns:
        List of Task objects to add intern userids to ACL files
    """
    import base64

    script = f"""\
import json
import os
import sys

UIDS = {repr(INTERN_USER_IDS)}
FILES = {repr(THRIFT_ACL_FILES)}

for f in FILES:
    if not os.path.exists(f):
        print(f"SKIP {{f}}: does not exist")
        continue
    try:
        with open(f) as fh:
            data = json.load(fh)
        modified = False
        for perm in data.get("permissions", []):
            entries = perm.setdefault("entries", [])
            existing_ids = set(
                e.get("identity", {{}}).get("id_data") for e in entries
            )
            for uid in UIDS:
                if uid not in existing_ids:
                    entries.append({{"identity": {{"id_type": "USER", "id_data": uid}}}})
                    modified = True
        if modified:
            with open(f, "w") as fh:
                json.dump(data, fh, indent=4)
            print(f"UPDATED {{f}}")
        else:
            print(f"OK {{f}}: all uids already present")
    except Exception as e:
        print(f"ERROR {{f}}: {{e}}", file=sys.stderr)
        sys.exit(1)
"""
    encoded = base64.b64encode(script.encode("utf-8")).decode("utf-8")
    return [
        create_run_commands_on_shell_task(
            hostname=device_name,
            cmds=[
                f"bash echo '{encoded}' | base64 -d > /tmp/add_uids.py && sudo python3 /tmp/add_uids.py",
            ],
            set_outer_hostname=True,
            ixia_needed=True,
        ),
    ]


# =============================================================================
# Helper 1: Pre-IXIA interface configuration
# =============================================================================
def _get_pre_ixia_interface_tasks(
    device_name: str,
    ixia_interfaces: t.List[t.Tuple[str, str]],
) -> t.List[Task]:
    """
    Configure IXIA interfaces so they are UP before IXIA connects.

    After device reload, interface config (speed, switchport) is lost.
    These MUST run before IXIA setup (ixia_needed=False).

    Args:
        device_name: Device hostname
        ixia_interfaces: List of (interface_name, description) tuples

    Returns:
        List of Task objects for pre-IXIA interface configuration
    """
    tasks: t.List[Task] = []
    for interface_name, description in ixia_interfaces:
        tasks.append(
            create_run_commands_on_shell_task(
                hostname=device_name,
                cmds=[
                    "configure\n"
                    f"interface {interface_name}\n"
                    f"description {description}\n"
                    "no shutdown\n"
                    "speed 100g-2\n"
                    "no switchport\n"
                    "ipv6 enable\n"
                    "end",
                ],
                set_outer_hostname=True,
                ixia_needed=False,
            )
        )

    # Sleep to allow links to come up after image update/interface config
    tasks.append(
        create_run_commands_on_shell_task(
            hostname=device_name,
            cmds=["bash sleep 30"],
            set_outer_hostname=True,
            ixia_needed=False,
        )
    )
    return tasks


# =============================================================================
# Helper 2: BGP++ config deployment
# =============================================================================
def _get_bgpcpp_deployment_tasks(
    device_name: str,
    bgp_asn: int,
    bgpcpp_configerator_path: str,
    openr_configerator_path: t.Optional[str] = None,
    enable_update_group: bool = False,
    update_group_config: t.Optional[t.Dict[str, t.Any]] = None,
) -> t.List[Task]:
    """
    Deploy BGP++ configuration, certificates, and supporting agent configs.

    Includes: directories, TLS certs, EOS BGP shutdown, bgpcpp_config
    deployment + client cert patch, FibAgent configs, OpenR config.

    Args:
        device_name: Device hostname
        bgp_asn: BGP AS number to shutdown
        bgpcpp_configerator_path: Configerator path for bgpcpp_config
        openr_configerator_path: Configerator path for OpenR config
        enable_update_group: When True, patches the freshly-deployed
            ``/mnt/flash/bgpcpp_config`` to enable update grouping plus the
            full ``update_group_config`` struct (per D100093369). The
            standalone ``enable_serialize_group_pdu`` field no longer
            exists in the thrift schema — its replacement
            ``enableSerializeGroupPdu`` lives inside
            ``update_group_config``.
        update_group_config: Optional override for the ``update_group_config``
            struct written to the device. When ``None`` (default), the
            ``UPDATE_GROUP_CONFIG`` constant from ``conveyor_constants.py``
            is used. Only honored when ``enable_update_group=True``.

    Returns:
        List of Task objects for BGP++ deployment
    """
    tasks: t.List[Task] = []

    # Create required directories
    tasks.append(
        create_run_commands_on_shell_task(
            hostname=device_name,
            cmds=[
                "bash mkdir -p /usr/facebook/thrift_acls",
                "bash mkdir -p /mnt/fb/agent_configs",
                "bash mkdir -p /mnt/fb/certs",
                "bash touch /usr/facebook/thrift_acls/auth_kill_switch_file",
            ],
            set_outer_hostname=True,
            ixia_needed=True,
        )
    )

    # Deploy self-signed TLS certs for FibAgent and BGP++ daemons
    tasks.append(create_deploy_tls_certs_task(hostname=device_name))

    # Shutdown EOS native BGP (must be done before enabling BGP++ daemons)
    tasks.append(
        create_run_commands_on_shell_task(
            hostname=device_name,
            cmds=[f"configure\nrouter bgp {bgp_asn}\nshutdown\nend"],
            set_outer_hostname=True,
            ixia_needed=True,
        )
    )

    # Deploy base bgpcpp_config from configerator
    tasks.append(
        create_arista_create_file_from_config_task(
            hostname=device_name,
            configerator_path=bgpcpp_configerator_path,
            file_path=BGPCPP_CONFIG_PATH,
            ixia_needed=True,
        )
    )

    # Patch bgpcpp_config to disable client cert verification
    # This allows the TAAC framework to query BGP++ Thrift APIs
    # without proper infrasec authorization (test environment only).
    # ``sudo`` is required because ``/mnt/flash/bgpcpp_config`` is
    # root-owned on EOS; without it the ``open(...,'w')`` raises
    # PermissionError, the python process exits non-zero, but the
    # outer ``bash`` swallows the error so the task reports success
    # while the patch silently never lands on disk.
    tasks.append(
        create_run_commands_on_shell_task(
            hostname=device_name,
            cmds=[
                'bash sudo python3 -c "'
                "import json; "
                f"f=open('{BGPCPP_CONFIG_PATH}'); c=json.load(f); f.close(); "
                "c.setdefault('thrift_server_config',{})['verify_client_type']=0; "
                f"f=open('{BGPCPP_CONFIG_PATH}','w'); "
                "json.dump(c,f,indent=2); f.close(); "
                "print('Patched verify_client_type to 0')"
                '"',
            ],
            set_outer_hostname=True,
            ixia_needed=True,
        )
    )

    # Optionally toggle BGP++ update_group settings.
    # We patch the freshly-deployed /mnt/flash/bgpcpp_config in-shell (same
    # pattern as the verify_client_type patch above) instead of going through
    # the SFTP-based ``set_bgp_setting_config`` task — that task has a 120s
    # SFTP write timeout which fails on the ~1.16 MB bgpcpp_config file.
    # ``reload_bgp`` is unnecessary here because the daemons will be started
    # fresh by the subsequent control plane step and will pick up the new
    # settings directly.
    #
    # Per D100093369, the standalone ``enable_serialize_group_pdu`` field
    # has moved into the new ``update_group_config`` struct (field 15) on
    # ``BgpSettingConfig``. When update_group is enabled we write the
    # full struct (allowSlowPeerDetach + slow-peer thresholds +
    # enableSerializeGroupPdu) so slow peer detachment is exercised
    # alongside update grouping. Callers can override the struct by passing
    # ``update_group_config``; otherwise the ``UPDATE_GROUP_CONFIG``
    # constant from ``conveyor_constants.py`` is used.
    if enable_update_group:
        ug_config = (
            update_group_config
            if update_group_config is not None
            else UPDATE_GROUP_CONFIG
        )
        tasks.append(
            create_run_commands_on_shell_task(
                hostname=device_name,
                cmds=[
                    # See verify_client_type patch above for why ``sudo`` is
                    # required — without it the patch silently never lands.
                    'bash sudo python3 -c "'
                    "import json; "
                    f"f=open('{BGPCPP_CONFIG_PATH}'); c=json.load(f); f.close(); "
                    "s=c.setdefault('bgp_setting_config',{}); "
                    f"s['enable_update_group']={bool(enable_update_group)}; "
                    f"s['update_group_config']={ug_config!r}; "
                    f"f=open('{BGPCPP_CONFIG_PATH}','w'); "
                    "json.dump(c,f,indent=2); f.close(); "
                    "print('Patched bgp_setting_config: update_group=%s, update_group_config=%s' "
                    f"% ({bool(enable_update_group)}, {json.dumps(ug_config)!r}))"
                    '"',
                ],
                set_outer_hostname=True,
                ixia_needed=True,
            )
        )

    # Validate bgpcpp_config using the production validator binary.
    # Catches truncation from base64 chunk failures AND corruption
    # from the Python patching scripts above — fails the setup task
    # immediately instead of letting BGP++ crash 30 min into the test.
    tasks.append(
        create_validate_bgpcpp_config_on_device_task(
            hostname=device_name,
            config_path=BGPCPP_CONFIG_PATH,
            ixia_needed=True,
        )
    )

    # Deploy fib_agent_bgp.conf via embedded base64
    tasks.append(
        create_run_commands_on_shell_task(
            hostname=device_name,
            cmds=[FIBAGENT_BGP_CONF_DEPLOY_CMD],
            set_outer_hostname=True,
            ixia_needed=True,
        )
    )

    # Deploy fib_agent.conf via embedded base64
    tasks.append(
        create_run_commands_on_shell_task(
            hostname=device_name,
            cmds=[FIBAGENT_CONF_DEPLOY_CMD],
            set_outer_hostname=True,
            ixia_needed=True,
        )
    )

    # Deploy OpenR config from configerator (if provided)
    if openr_configerator_path is not None:
        tasks.append(
            create_arista_create_file_from_config_task(
                hostname=device_name,
                configerator_path=openr_configerator_path,
                file_path="/mnt/flash/openr_config",
                ixia_needed=True,
            )
        )
        tasks.append(
            create_run_commands_on_shell_task(
                hostname=device_name,
                cmds=[
                    "bash sudo ln -sf /mnt/flash/openr_config /etc/openr_config",
                ],
                set_outer_hostname=True,
                ixia_needed=True,
            )
        )

    return tasks


# =============================================================================
# Helper 3: Control plane tasks (ACLs + daemon enable)
# =============================================================================
def _get_control_plane_tasks(
    device_name: str,
    profile: BgpPlusPlusProfile,
    enable_update_group: bool = False,
) -> t.List[Task]:
    """
    Apply control-plane ACLs and enable BGP++ daemons.

    Open/R is bounced (disable -> enable) only for the WITH_OPEN_R profile. For
    WITHOUT_OPEN_R no ``openr_config`` is deployed, so enabling a config-less
    Open/R daemon just produces cores without contributing to BGP++ validation;
    it is left disabled instead.

    Args:
        device_name: Device hostname
        profile: BGP++ profile -- controls whether the Open/R daemon is enabled.
        enable_update_group: When True, a final task verifies that BGP++ is
            running with ``update_group`` enabled (via ``show bgpcpp
            update-group``). Catches the historical silent-failure mode
            where the bgpcpp_config patch never landed on disk and
            ``_UPDATE_GROUP`` test variants ran for hours measuring the
            NON-UG baseline while claiming UG coverage.

    Returns:
        List of Task objects for ACLs and daemon enable
    """
    tasks: t.List[Task] = []

    # Add control plane ACLs on device
    tasks.append(
        create_run_commands_on_shell_task(
            hostname=device_name,
            cmds=[ACL_COMMANDS],
            set_outer_hostname=True,
            ixia_needed=True,
        )
    )

    # Enable BGP++ daemons (shutdown first to pick up new configs). Open/R is
    # only enabled for the WITH_OPEN_R profile; otherwise it is left disabled --
    # no openr_config is deployed for WITHOUT_OPEN_R, so a config-less Open/R
    # daemon only cores and validates nothing.
    enable_open_r = profile == BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R
    for daemon in BGPCPP_DAEMONS:
        tasks.append(
            create_arista_daemon_control_task(
                hostname=device_name,
                daemon_name=daemon,
                action="disable",
                ixia_needed=True,
            )
        )
        if daemon == "Openr" and not enable_open_r:
            continue
        tasks.append(
            create_arista_daemon_control_task(
                hostname=device_name,
                daemon_name=daemon,
                action="enable",
                ixia_needed=True,
            )
        )

    # Add intern userid to thrift ACL files AFTER daemon restart.
    # Daemons may regenerate ACL files on startup, so UIDs must be
    # injected after daemons are running.
    tasks.extend(_get_add_intern_userid_tasks(device_name=device_name))

    # Restart Bgp, FibAgent, and FibAgentBgp so they re-read the updated ACL
    # files. These daemons load their thrift ACLs at startup and don't re-read
    # on modification, so a restart is required for the new UIDs to take
    # effect. Without restarting Bgp here, any later Thrift call against the
    # Bgp daemon (e.g. ``getBgpSessions`` from ``BGP_SESSION_CHECK``) gets
    # ``AuthorizationException: Authorization failed`` because Bgp's
    # in-memory ACL still reflects the pre-injection ``Bgpd_lab.json``.
    for daemon in ["Bgp", "FibAgent", "FibAgentBgp"]:
        tasks.append(
            create_arista_daemon_control_task(
                hostname=device_name,
                daemon_name=daemon,
                action="disable",
                ixia_needed=True,
            )
        )
        tasks.append(
            create_arista_daemon_control_task(
                hostname=device_name,
                daemon_name=daemon,
                action="enable",
                ixia_needed=True,
            )
        )

    # Verify ``update_group`` is actually active on the running BGP++
    # daemon. The Bgp daemon was just re-enabled above and has read
    # the patched ``/mnt/flash/bgpcpp_config``. ``show bgpcpp
    # update-group`` reports ``Update group: DISABLED`` if the patch
    # did not take effect -- fail the setup loudly instead of letting
    # the playbook measure the NON-UG baseline.
    #
    # The check requires BOTH (a) no ``DISABLED`` in the output AND
    # (b) positive evidence of ``Update group: ENABLED``. Without the
    # positive match, any CLI failure that doesn't emit ``DISABLED``
    # (command unavailable, daemon mid-restart, auth error,
    # connection error, etc.) would fall through to a false PASS --
    # the exact silent-failure mode this check exists to catch.
    if enable_update_group:
        tasks.append(
            create_run_commands_on_shell_task(
                hostname=device_name,
                cmds=[
                    "bash sudo bash -c 'set +e; "
                    'out=$(Cli -p15 -c "show bgpcpp update-group" 2>&1); '
                    'echo "$out"; '
                    'if echo "$out" | grep -qi DISABLED; then '
                    'echo "FAIL: BGP++ update_group is DISABLED -- patch did not take"; '
                    "exit 1; fi; "
                    'if echo "$out" | grep -qi "Update group: ENABLED"; then '
                    'echo "PASS: BGP++ update_group is ENABLED"; exit 0; fi; '
                    'echo "FAIL: BGP++ update_group state could not be confirmed -- '
                    'CLI may have failed or returned unexpected output"; '
                    "exit 1'"
                ],
                set_outer_hostname=True,
                ixia_needed=True,
            )
        )

    return tasks


# =============================================================================
# Helper 4: Full-scale IP configuration
# =============================================================================
def _get_full_scale_ip_config_tasks(
    device_name: str,
    ixia_interface_mimic_ebgp: str,
    ixia_interface_mimic_ibgp: str,
    ixia_interface_mimic_bgp_mon: str,
) -> t.List[Task]:
    """
    Configure full-scale IP addresses for all IXIA interfaces.

    Full-scale EBB topology:
    - eBGP: 140 peers, dual-stack (IPv4 + IPv6)
    - iBGP: 8 planes (4 DC + 4 MP) × 63 peers each, dual-stack
    - BGP MON: 2 peers, IPv6 only

    Args:
        device_name: Device hostname
        ixia_interface_mimic_ebgp: eBGP IXIA interface
        ixia_interface_mimic_ibgp: iBGP IXIA interface
        ixia_interface_mimic_bgp_mon: BGP MON IXIA interface

    Returns:
        List of Task objects for IP configuration
    """
    tasks: t.List[Task] = []

    # Configure eBGP interface IPs
    tasks.append(
        create_interface_ip_configuration_task(
            interface=ixia_interface_mimic_ebgp,
            peer_count=EBGP_PEER_COUNT_V6,
            ipv4_base_network=IXIA_EBGP_IC_PARENT_NETWORK_V4,
            ipv6_base_network=IXIA_EBGP_IC_PARENT_NETWORK_V6,
            address_families=["ipv4", "ipv6"],
            clear_existing=True,
            ipv4_start_offset=IXIA_IPV4_START_OFFSET,
            ipv6_start_offset=IXIA_IPV6_START_OFFSET,
            hostname=device_name,
            ixia_needed=True,
        )
    )

    # Configure iBGP interface IPs (all 8 planes: 4 DC + 4 MP)
    ibgp_plane_networks = [
        (
            IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1,
            IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1,
        ),
        (
            IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE2,
            IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE2,
        ),
        (
            IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE3,
            IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE3,
        ),
        (
            IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE4,
            IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE4,
        ),
        (
            IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE1,
            IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE1,
        ),
        (
            IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE2,
            IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE2,
        ),
        (
            IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE3,
            IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE3,
        ),
        (
            IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE4,
            IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE4,
        ),
    ]
    for plane_idx, (ipv4_network, ipv6_network) in enumerate(ibgp_plane_networks):
        tasks.append(
            create_interface_ip_configuration_task(
                interface=ixia_interface_mimic_ibgp,
                peer_count=IBGP_PEER_SCALE_PER_PLANE,
                ipv4_base_network=ipv4_network,
                ipv6_base_network=ipv6_network,
                address_families=["ipv4", "ipv6"],
                clear_existing=plane_idx == 0,
                all_secondary=plane_idx > 0,
                ipv4_start_offset=IXIA_IPV4_START_OFFSET,
                ipv6_start_offset=IXIA_IPV6_START_OFFSET,
                hostname=device_name,
                ixia_needed=True,
            )
        )

    # Configure BGP MON interface IPs
    tasks.append(
        create_interface_ip_configuration_task(
            interface=ixia_interface_mimic_bgp_mon,
            peer_count=BGP_MON_PEER_COUNT,
            ipv6_base_network=IXIA_BGP_MON_IC_PARENT_NETWORK,
            address_families=["ipv6"],
            clear_existing=True,
            ipv4_start_offset=IXIA_IPV4_START_OFFSET,
            ipv6_start_offset=IXIA_IPV6_START_OFFSET,
            hostname=device_name,
            ixia_needed=True,
        )
    )

    return tasks


# =============================================================================
# Helper 5: OpenR setup tasks
# =============================================================================
def _get_openr_setup_tasks(
    device_name: str,
    profile: BgpPlusPlusProfile,
    openr_port_channel_member: t.Optional[str] = None,
    openr_port_channel_ipv4: t.Optional[str] = None,
    openr_port_channel_link_local: t.Optional[str] = None,
    openr_local_link: t.Optional[t.Dict[str, t.Any]] = None,
    openr_other_link: t.Optional[t.Dict[str, t.Any]] = None,
) -> t.List[Task]:
    """
    Configure OpenR Port-Channel and inject routes if profile requires it.

    Only runs when profile is BGP_PLUS_PLUS_WITH_OPEN_R.

    Args:
        device_name: Device hostname
        profile: BGP++ profile
        openr_port_channel_member: Port-Channel member interface override
            (defaults to OPENR_PORT_CHANNEL_MEMBER constant)
        openr_port_channel_ipv4: Port-Channel IPv4 address override
            (defaults to OPENR_PORT_CHANNEL_IPV4 constant)
        openr_port_channel_link_local: Port-Channel link-local address override
            (defaults to OPENR_PORT_CHANNEL_LINK_LOCAL constant)
        openr_local_link: Local link config dict override
            (defaults to OPENR_LOCAL_LINK constant)
        openr_other_link: Other link config dict override
            (defaults to OPENR_OTHER_LINK constant)

    Returns:
        List of Task objects for OpenR setup (empty if not needed)
    """
    tasks: t.List[Task] = []

    if profile != BgpPlusPlusProfile.BGP_PLUS_PLUS_WITH_OPEN_R:
        return tasks

    pc_member = openr_port_channel_member or OPENR_PORT_CHANNEL_MEMBER
    pc_ipv4 = openr_port_channel_ipv4 or OPENR_PORT_CHANNEL_IPV4
    pc_link_local = openr_port_channel_link_local or OPENR_PORT_CHANNEL_LINK_LOCAL
    local_link = openr_local_link or OPENR_LOCAL_LINK
    other_link = openr_other_link or OPENR_OTHER_LINK

    # Configure Port-Channel and member interface for OpenR nexthop
    tasks.append(
        create_run_commands_on_shell_task(
            hostname=device_name,
            cmds=[
                "configure\n"
                f"default interface {pc_member}\n"
                "!\n"
                f"interface {OPENR_PORT_CHANNEL}\n"
                "description po100211.bag013\n"
                "load-interval 5\n"
                "mtu 9192\n"
                "no switchport\n"
                f"ip address {pc_ipv4}\n"
                f"ipv6 address {OPENR_PORT_CHANNEL_IPV6}\n"
                f"ipv6 address {pc_link_local} link-local\n"
                "ipv6 nd ra disabled\n"
                "!\n"
                f"interface {pc_member}\n"
                "no shutdown\n"
                "mtu 9000\n"
                "speed 400g-8\n"
                "no switchport\n"
                "ipv6 enable\n"
                "ipv6 address auto-config\n"
                "ipv6 nd ra rx accept default-route\n"
                f"channel-group {OPENR_PORT_CHANNEL_ID} mode active\n"
                "end",
            ],
            set_outer_hostname=True,
            ixia_needed=True,
        )
    )

    # Inject OpenR routes
    tasks.append(
        create_openr_route_action_task(
            device_name=device_name,
            action=OpenRRouteAction.INJECT.value,
            start_ipv4s=DEFAULT_OPENR_START_IPV4S,
            start_ipv6s=DEFAULT_OPENR_START_IPV6S,
            local_link=local_link,
            other_link=other_link,
            count=63,
            step=2,
            ixia_needed=True,
            set_outer_hostname=True,
        ),
    )

    return tasks


# =============================================================================
# Helper 6: iptables flush
# =============================================================================
def _get_iptables_flush_tasks(
    device_name: str,
) -> t.List[Task]:
    """
    Flush EOS_BGP iptables rules that block BGP++.

    Native EOS BGP's BGPSACL creates iptables DROP rules that block BGP++.
    Since BGP++ manages its own peers, we flush EOS_BGP and set ACCEPT.

    Args:
        device_name: Device hostname

    Returns:
        List of Task objects for iptables flush
    """
    return [
        create_run_commands_on_shell_task(
            hostname=device_name,
            cmds=[
                "bash sudo iptables -F EOS_BGP",
                "bash sudo iptables -A EOS_BGP -j ACCEPT",
                "bash sudo ip6tables -F EOS_BGP",
                "bash sudo ip6tables -A EOS_BGP -j ACCEPT",
            ],
            set_outer_hostname=True,
            ixia_needed=True,
        )
    ]


# =============================================================================
# IPv6-only peer entry generation for update packing test
# =============================================================================
def _generate_ixia_v6_peer_entries_for_bgpcpp(
    remote_as: int,
    ixia_ipv6_base: str,
    peer_count: int,
    peer_group_v6: str,
    start_offset: int = 16,
) -> t.List[t.Dict[str, t.Any]]:
    """
    Generate IPv6-only BGP++ peer entries for IXIA-facing sessions.

    These are added to /mnt/flash/bgpcpp_config so BGP++ knows about
    the IXIA peers. Only generates IPv6 peers (no IPv4).

    Args:
        remote_as: IXIA's simulated AS number
        ixia_ipv6_base: IPv6 base for IXIA peering
        peer_count: Number of IXIA peers
        peer_group_v6: Peer group for IPv6 IXIA sessions
        start_offset: Host offset of the first local address (peer = local+1,
            stepping by 2 per peer). Defaults to 16 (``::10``) to match the
            existing conveyor deployments; callers can override to align with a
            specific IXIA-side addressing scheme.

    Returns:
        List of IPv6 peer entry dicts for bgpcpp_config
    """
    peers = []
    for i in range(peer_count):
        addr_idx = i * 2
        v6_local = f"{ixia_ipv6_base}::{start_offset + addr_idx:x}"
        v6_peer = f"{ixia_ipv6_base}::{start_offset + 1 + addr_idx:x}"

        peers.append(
            {
                "remote_as_4_byte": remote_as,
                "local_addr": v6_local,
                "peer_addr": v6_peer,
                "next_hop4": "0.0.0.0",
                "next_hop6": v6_local,
                "description": f"IXIA_V6_PEER_{i + 1}",
                "peer_id": v6_peer,
                "peer_group_name": peer_group_v6,
            }
        )

    return peers


# =============================================================================
# IPv4 peer-entry generator (mirror of the IPv6 version above).
# =============================================================================
def _generate_ixia_v4_peer_entries_for_bgpcpp(
    remote_as: int,
    ixia_ipv4_base: str,
    peer_count: int,
    peer_group_v4: str,
    start_offset: int = 16,
) -> t.List[t.Dict[str, t.Any]]:
    """Generate IPv4 BGP++ peer entries for IXIA-facing sessions.

    Mirror of ``_generate_ixia_v6_peer_entries_for_bgpcpp`` for the v4 AF.
    Used together with the v6 generator to produce a combined v6+v4 peer
    list for dual-stack sweeps (e.g. bag012 performance scaling).

    ``start_offset`` is the host offset of the first local address (peer =
    local+1, stepping by 2 per peer). Defaults to 16 (``.16``) to match the
    existing conveyor deployments; callers can override to align with a
    specific IXIA-side addressing scheme.

    Host offsets beyond 255 roll over into the third octet (e.g. 128 peers
    from ``.10`` span ``X.Y.28.10`` -> ``X.Y.29.*``). This matches both the
    IXIA-side numeric IP increment and the legacy ReplaceBgpPeersTask, and
    is a no-op for the small peer counts the other callers use.
    """
    octets = ixia_ipv4_base.split(".")
    base_third_octet = int(octets[2])
    peers = []
    for i in range(peer_count):
        local_offset = start_offset + i * 2
        peer_offset = local_offset + 1
        v4_local = (
            f"{octets[0]}.{octets[1]}."
            f"{base_third_octet + local_offset // 256}.{local_offset % 256}"
        )
        v4_peer = (
            f"{octets[0]}.{octets[1]}."
            f"{base_third_octet + peer_offset // 256}.{peer_offset % 256}"
        )
        peers.append(
            {
                "remote_as_4_byte": remote_as,
                "local_addr": v4_local,
                "peer_addr": v4_peer,
                "next_hop4": v4_local,
                "next_hop6": "0::0",
                "description": f"IXIA_V4_PEER_{i + 1}",
                "peer_id": v4_peer,
                "peer_group_name": peer_group_v4,
            }
        )
    return peers


# =============================================================================
# Combined v6+v4 peer-list builder for dual-stack sweeps.
# =============================================================================
def build_sweep_peer_list(
    *,
    ebgp_remote_as: int,
    ibgp_remote_as: int,
    ebgp_v6_base: str,
    ebgp_v4_base: str,
    ibgp_v6_base: str,
    ibgp_v4_base: str,
    peergroup_ebgp_v6: str,
    peergroup_ebgp_v4: str,
    peergroup_ibgp_v6: str,
    peergroup_ibgp_v4: str,
    ebgp_peer_count: int,
    ibgp_peer_count: int,
) -> t.List[t.Dict[str, t.Any]]:
    """Build the full peer-list for one sweep iteration: v6+v4 EBGP + v6+v4 IBGP.

    Just concatenates outputs of the two single-AF generators. Pass the
    result to ``build_bgpcpp_peers_patch_shell_cmds`` to splice it into
    the deployed bgpcpp_config.
    """
    return (
        _generate_ixia_v6_peer_entries_for_bgpcpp(
            ebgp_remote_as, ebgp_v6_base, ebgp_peer_count, peergroup_ebgp_v6
        )
        + _generate_ixia_v4_peer_entries_for_bgpcpp(
            ebgp_remote_as, ebgp_v4_base, ebgp_peer_count, peergroup_ebgp_v4
        )
        + _generate_ixia_v6_peer_entries_for_bgpcpp(
            ibgp_remote_as, ibgp_v6_base, ibgp_peer_count, peergroup_ibgp_v6
        )
        + _generate_ixia_v4_peer_entries_for_bgpcpp(
            ibgp_remote_as, ibgp_v4_base, ibgp_peer_count, peergroup_ibgp_v4
        )
    )


# =============================================================================
# In-shell bgpcpp_config peers-patch command builder.
# =============================================================================
# EOS shell command-length cap forces base64 chunking of the peers JSON.
_PEERS_B64_CHUNK_SIZE: int = 20000


def build_bgpcpp_peers_patch_shell_cmds(
    peers: t.List[t.Dict[str, t.Any]],
    router_id: str,
    config_path: str = BGPCPP_CONFIG_PATH,
) -> t.List[str]:
    """Build shell commands that splice ``peers`` + ``router_id`` into the
    deployed bgpcpp_config on the device.

    Pure string-builder. Output is intended for ``create_run_commands_on_shell_step``.
    Mechanism: base64-encode the peers JSON, chunk-write to /tmp/peers.b64,
    decode to /tmp/peers.json, run an inline ``python3 -c`` that loads
    config, swaps in ``c['peers']`` and ``c['router_id']``, writes back.
    """
    peers_b64 = base64.b64encode(json.dumps(peers).encode()).decode()
    chunks = [
        peers_b64[i : i + _PEERS_B64_CHUNK_SIZE]
        for i in range(0, len(peers_b64), _PEERS_B64_CHUNK_SIZE)
    ]
    cmds: t.List[str] = []
    for i, chunk in enumerate(chunks):
        op = ">" if i == 0 else ">>"
        cmds.append(f"bash echo '{chunk}' {op} /tmp/peers.b64")
    cmds.append("bash base64 -d /tmp/peers.b64 > /tmp/peers.json")
    cmds.append("bash rm -f /tmp/peers.b64")
    merge = (
        'bash python3 -c "import json; '
        f"f=open('{config_path}'); c=json.load(f); f.close(); "
        "p=open('/tmp/peers.json'); c['peers']=json.load(p); p.close(); "
        f"c['router_id']='{router_id}'; "
        f"f=open('{config_path}','w'); json.dump(c,f,indent=2); f.close(); "
        "print('Updated peers:',len(c['peers']),'router_id:',c['router_id'])\""
    )
    cmds.append(merge)
    return cmds


# =============================================================================
# Per-iteration step composers (Bgp daemon cycle around peer rewrite, IXIA reset).
# =============================================================================
def build_rescale_bgpcpp_config_steps(
    *,
    device_name: str,
    peers: t.List[t.Dict[str, t.Any]],
    router_id: str,
    config_path: str = BGPCPP_CONFIG_PATH,
) -> list:
    """Disable Bgp daemon, splice the new peer list into bgpcpp_config, re-enable Bgp.

    Returns a 3-Step list: daemon disable, shell-patch, daemon enable. Bgp
    daemon reads the new peers list on enable.
    """
    from taac.steps.step_definitions import (
        create_daemon_control_step,
        create_run_commands_on_shell_step,
    )

    return [
        create_daemon_control_step(
            device_name=device_name,
            daemon_name="Bgp",
            action="disable",
            description=(
                f"Disable Bgp daemon before rewriting {config_path}"
                f" with {len(peers)} peers"
            ),
        ),
        create_run_commands_on_shell_step(
            device_name=device_name,
            cmds=build_bgpcpp_peers_patch_shell_cmds(
                peers=peers, router_id=router_id, config_path=config_path
            ),
            description=(
                f"Rewrite {config_path} with {len(peers)} peer entries"
                " (in-shell base64+python3 merge)"
            ),
        ),
        create_daemon_control_step(
            device_name=device_name,
            daemon_name="Bgp",
            action="enable",
            description=f"Re-enable Bgp daemon with {len(peers)} peers configured",
        ),
    ]


# Upper bound used when stopping IXIA IBGP peers between iterations. Matches
# the long-standing lab convention.
PER_ITERATION_MAX_IBGP_SESSIONS_TO_STOP: int = 500
_REGEX_IBGP_V6: str = "BGP_PEER_IPV6_IBGP"
_REGEX_IBGP_V4: str = "BGP_PEER_IPV4_IBGP"


def build_ixia_ibgp_subset_activation_steps(n_v6: int, n_v4: int) -> list:
    """Stop any prior IXIA IBGP sessions on both AFs, then start n_v6 + n_v4.

    Skips the start step for an AF whose count is 0.
    """
    from taac.steps.step_definitions import create_ixia_api_step

    def _args(start: bool, regex: str, end_idx: int) -> t.Dict[str, t.Any]:
        return {
            "start": start,
            "regex": regex,
            "session_start_idx": 1,
            "session_end_idx": end_idx,
        }

    steps = [
        create_ixia_api_step(
            api_name="start_bgp_peers",
            args_dict=_args(False, regex, PER_ITERATION_MAX_IBGP_SESSIONS_TO_STOP),
            description=f"Stop any {label} IBGP peers from prior iterations",
        )
        for regex, label in (
            (_REGEX_IBGP_V6, "IPv6"),
            (_REGEX_IBGP_V4, "IPv4"),
        )
    ]
    for regex, label, n in (
        (_REGEX_IBGP_V6, "IPv6", n_v6),
        (_REGEX_IBGP_V4, "IPv4", n_v4),
    ):
        if n > 0:
            steps.append(
                create_ixia_api_step(
                    api_name="start_bgp_peers",
                    args_dict=_args(True, regex, n),
                    description=f"Start {n} {label} IBGP peers for this iteration",
                )
            )
    return steps


# =============================================================================
# Per-iteration setup-steps factory: device-side rescale + IXIA peer activation.
# =============================================================================
def build_per_iteration_factory_v4_capable(
    *,
    device_name: str,
    router_id: str,
    ebgp_remote_as: int,
    ibgp_remote_as: int,
    ebgp_v6_base: str,
    ebgp_v4_base: str,
    ibgp_v6_base: str,
    ibgp_v4_base: str,
    peergroup_ebgp_v6: str,
    peergroup_ebgp_v4: str,
    peergroup_ibgp_v6: str,
    peergroup_ibgp_v4: str,
    ebgp_peer_count: int = 1,
    config_path: str = BGPCPP_CONFIG_PATH,
):
    """Return a closure ``(n_v6, n_v4) -> List[Step]`` for v6+v4 sweeps.

    Each call composes:
      1. Build the combined v6+v4 EBGP+IBGP peers list for this iteration.
      2. Rescale ``/mnt/flash/bgpcpp_config`` (Bgp disable → patch → enable).
      3. Activate the matching IXIA IBGP session subset.

    Plug into ``test_config_for_bgp_plus_plus_on_ebb_arista_performance_scaling``'s
    ``per_iteration_setup_steps_factory`` parameter.
    """

    def factory(n_v6: int, n_v4: int) -> list:
        peers = build_sweep_peer_list(
            ebgp_remote_as=ebgp_remote_as,
            ibgp_remote_as=ibgp_remote_as,
            ebgp_v6_base=ebgp_v6_base,
            ebgp_v4_base=ebgp_v4_base,
            ibgp_v6_base=ibgp_v6_base,
            ibgp_v4_base=ibgp_v4_base,
            peergroup_ebgp_v6=peergroup_ebgp_v6,
            peergroup_ebgp_v4=peergroup_ebgp_v4,
            peergroup_ibgp_v6=peergroup_ibgp_v6,
            peergroup_ibgp_v4=peergroup_ibgp_v4,
            ebgp_peer_count=ebgp_peer_count,
            ibgp_peer_count=max(n_v6, n_v4),
        )
        return build_rescale_bgpcpp_config_steps(
            device_name=device_name,
            peers=peers,
            router_id=router_id,
            config_path=config_path,
        ) + build_ixia_ibgp_subset_activation_steps(n_v6=n_v6, n_v4=n_v4)

    return factory


# =============================================================================
# Public API: Dynamic BGP++ setting toggle
# =============================================================================
def get_set_bgp_setting_config_task(
    device_name: str,
    enable_update_group: bool = False,
    update_group_config: t.Optional[t.Dict[str, t.Any]] = None,
    reload_bgp: bool = True,
) -> Task:
    """
    Build a ``set_bgp_setting_config`` Task that dynamically toggles BGP++
    settings on the device.

    The task SSH-patches ``/mnt/flash/bgpcpp_config`` with the requested
    ``bgp_setting_config`` overrides and (by default) reloads the BGP daemon
    so the change takes effect before subsequent steps run.

    Args:
        device_name: Device hostname (e.g. "bag011.ash6")
        enable_update_group: Toggle BGP++ ``enable_update_group`` setting.
            When True the ``update_group_config`` struct (per D100093369) is
            also written.
        update_group_config: Optional override for the ``update_group_config``
            struct. When ``None`` (default) the ``UPDATE_GROUP_CONFIG``
            constant from ``conveyor_constants.py`` is used.
        reload_bgp: When True (default) reloads the BGP daemon after patching.
            Set to False when an upcoming stage will restart BGP anyway.

    Returns:
        A single Task suitable for appending to ``setup_tasks``.
    """
    settings: t.Dict[str, t.Any] = {
        "enable_update_group": enable_update_group,
    }
    if enable_update_group:
        settings["update_group_config"] = (
            update_group_config
            if update_group_config is not None
            else UPDATE_GROUP_CONFIG
        )
    return create_set_bgp_setting_config_task(
        hostname=device_name,
        settings=settings,
        reload_bgp=reload_bgp,
    )


# =============================================================================
# Public API: Full-scale setup (used by bag011 and other full-scale tests)
# =============================================================================
def get_common_setup_tasks(
    device_name: str,
    bgp_asn: int,
    ixia_interface_mimic_ebgp: str,
    ixia_interface_mimic_ibgp: str,
    ixia_interface_mimic_bgp_mon: str,
    bgpcpp_configerator_path: str,
    profile: BgpPlusPlusProfile,
    openr_configerator_path: t.Optional[str] = None,
    openr_port_channel_member: t.Optional[str] = None,
    openr_port_channel_ipv4: t.Optional[str] = None,
    openr_port_channel_link_local: t.Optional[str] = None,
    openr_local_link: t.Optional[t.Dict[str, t.Any]] = None,
    openr_other_link: t.Optional[t.Dict[str, t.Any]] = None,
    enable_update_group: bool = False,
    update_group_config: t.Optional[t.Dict[str, t.Any]] = None,
) -> t.List[Task]:
    """
    Generate common setup tasks for a full-scale EBB BGP++ conveyor test config.

    Includes core BGP++ setup plus full-scale IP configuration for:
    - 140 eBGP peers (dual-stack)
    - 8 iBGP planes (4 DC + 4 MP) × 63 peers each (dual-stack)
    - 2 BGP MON peers

    Returns:
        List of setup Task objects.
    """
    setup_tasks: t.List[Task] = []

    # Disable BgpTcpdump daemon before any setup
    # This daemon is not needed for conveyor testing and can interfere.
    setup_tasks.append(
        create_arista_daemon_control_task(
            hostname=device_name,
            daemon_name="BgpTcpdump",
            action="disable",
        )
    )

    # 1. Pre-IXIA interface configuration (3 interfaces)
    setup_tasks.extend(
        _get_pre_ixia_interface_tasks(
            device_name=device_name,
            ixia_interfaces=[
                (ixia_interface_mimic_ebgp, "IXIA_MIMIC_EBGP"),
                (ixia_interface_mimic_ibgp, "IXIA_MIMIC_IBGP"),
                (ixia_interface_mimic_bgp_mon, "IXIA_MIMIC_BGP_MON"),
            ],
        )
    )

    # 2. BGP++ config deployment
    setup_tasks.extend(
        _get_bgpcpp_deployment_tasks(
            device_name=device_name,
            bgp_asn=bgp_asn,
            bgpcpp_configerator_path=bgpcpp_configerator_path,
            openr_configerator_path=openr_configerator_path,
            enable_update_group=enable_update_group,
            update_group_config=update_group_config,
        )
    )

    # 3. Control plane (ACLs + daemons)
    setup_tasks.extend(
        _get_control_plane_tasks(
            device_name=device_name,
            profile=profile,
            enable_update_group=enable_update_group,
        )
    )

    # 4. Full-scale IP configuration
    setup_tasks.extend(
        _get_full_scale_ip_config_tasks(
            device_name=device_name,
            ixia_interface_mimic_ebgp=ixia_interface_mimic_ebgp,
            ixia_interface_mimic_ibgp=ixia_interface_mimic_ibgp,
            ixia_interface_mimic_bgp_mon=ixia_interface_mimic_bgp_mon,
        )
    )

    # 5. OpenR setup (conditional on profile)
    setup_tasks.extend(
        _get_openr_setup_tasks(
            device_name=device_name,
            profile=profile,
            openr_port_channel_member=openr_port_channel_member,
            openr_port_channel_ipv4=openr_port_channel_ipv4,
            openr_port_channel_link_local=openr_port_channel_link_local,
            openr_local_link=openr_local_link,
            openr_other_link=openr_other_link,
        )
    )

    # 6. Flush iptables
    setup_tasks.extend(_get_iptables_flush_tasks(device_name=device_name))

    return setup_tasks


def build_expected_peer_identity() -> t.Dict[str, str]:
    """
    Build expected {peer_addr: local_addr} mapping for full-scale EBB tests.

    Uses the same IXIA network constants and address generation logic as
    get_common_setup_tasks to produce a peer identity map suitable for
    passing to create_standard_snapshot_checks(expected_peer_identity=...).

    This is optional — callers that don't need peer identity validation
    can skip calling this entirely.
    """
    expected_peer_identity: t.Dict[str, str] = {}

    # IPv6 peers (from _generate_ixia_v6_peer_entries_for_bgpcpp)
    for base, count in [
        (IXIA_EBGP_IC_PARENT_NETWORK_V6, EBGP_PEER_COUNT_V6),
        (IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE1, IBGP_PEER_SCALE_PER_PLANE),
        (IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE2, IBGP_PEER_SCALE_PER_PLANE),
        (IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE3, IBGP_PEER_SCALE_PER_PLANE),
        (IXIA_IBGP_IC_PARENT_NETWORK_V6_DC_PLANE4, IBGP_PEER_SCALE_PER_PLANE),
        (IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE1, IBGP_PEER_SCALE_PER_PLANE),
        (IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE2, IBGP_PEER_SCALE_PER_PLANE),
        (IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE3, IBGP_PEER_SCALE_PER_PLANE),
        (IXIA_IBGP_IC_PARENT_NETWORK_V6_MP_PLANE4, IBGP_PEER_SCALE_PER_PLANE),
        (IXIA_BGP_MON_IC_PARENT_NETWORK, BGP_MON_PEER_COUNT),
    ]:
        for entry in _generate_ixia_v6_peer_entries_for_bgpcpp(
            remote_as=0,
            ixia_ipv6_base=base,
            peer_count=count,
            peer_group_v6="",
        ):
            expected_peer_identity[entry["peer_addr"]] = entry["local_addr"]

    # IPv4 peers (same offset formula: local = base + start_offset + i*2)
    for base, count in [
        (IXIA_EBGP_IC_PARENT_NETWORK_V4, EBGP_PEER_COUNT_V4),
        (IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE1, IBGP_PEER_SCALE_PER_PLANE),
        (IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE2, IBGP_PEER_SCALE_PER_PLANE),
        (IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE3, IBGP_PEER_SCALE_PER_PLANE),
        (IXIA_IBGP_IC_PARENT_NETWORK_V4_DC_PLANE4, IBGP_PEER_SCALE_PER_PLANE),
        (IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE1, IBGP_PEER_SCALE_PER_PLANE),
        (IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE2, IBGP_PEER_SCALE_PER_PLANE),
        (IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE3, IBGP_PEER_SCALE_PER_PLANE),
        (IXIA_IBGP_IC_PARENT_NETWORK_V4_MP_PLANE4, IBGP_PEER_SCALE_PER_PLANE),
    ]:
        base_ip = ipaddress.IPv4Address(f"{base}.{IXIA_IPV4_START_OFFSET}")
        for i in range(count):
            local_ip = str(base_ip + i * 2)
            peer_ip = str(base_ip + i * 2 + 1)
            expected_peer_identity[peer_ip] = local_ip

    return expected_peer_identity


# =============================================================================
# Public API: Update packing setup (used by bag012 update packing test)
# =============================================================================
def get_update_packing_setup_tasks(
    device_name: str,
    bgp_asn: int,
    ixia_interface_mimic_ebgp: str,
    ixia_interface_mimic_ibgp: str,
    ebgp_peer_count: int,
    ibgp_peer_count: int,
    ebgp_remote_as: int,
    ibgp_remote_as: int,
    ixia_ebgp_ic_parent_network_v6: str,
    ixia_ibgp_ic_parent_network_v6: str,
    router_id: str,
    bgpcpp_configerator_path: str,
    profile: BgpPlusPlusProfile,
    ebgp_peer_group_v6: str = "EB-FA-V6",
    ibgp_peer_group_v6: str = "EB-EB-V6",
    openr_configerator_path: t.Optional[str] = None,
    ixia_ebgp_ic_parent_network_v4: t.Optional[str] = None,
    ixia_ibgp_ic_parent_network_v4: t.Optional[str] = None,
    ebgp_peer_group_v4: str = "EB-FA-V4",
    ibgp_peer_group_v4: str = "EB-EB-V4",
    enable_update_group: bool = False,
    update_group_config: t.Optional[t.Dict[str, t.Any]] = None,
    v4_peer_start_offset: int = 16,
) -> t.List[Task]:
    """
    Generate setup tasks for the BGP UPDATE packing validation conveyor test.

    Uses the same core BGP++ setup as full-scale tests but with:
    - Only 2 IXIA interfaces (eBGP + iBGP, no BGP MON)
    - Simplified IP configuration (e.g. 10 eBGP + 1 iBGP, IPv6 only)
    - Peer modification to update bgpcpp_config with matching peers

    Args:
        v4_peer_start_offset: Host offset of the first IPv4 peer local address
            (peer = local+1, stepping by 2 per peer). Defaults to 16 to match
            the existing conveyor deployments. Note the interface secondary IPs
            are always laid out from ``IXIA_IPV4_START_OFFSET`` (10). This v4
            offset is only exercised when v4 networks are passed (i.e. v4 peers
            are actually generated); the other conveyor callers (CAS / Queue
            Memory Monitor / Update Packing) pass IPv6 networks only and bring
            up zero v4 sessions, so their v4 peer offset never matters. A test
            that does bring up v4 sessions (e.g. bounded ECMP) must pass
            ``v4_peer_start_offset=IXIA_IPV4_START_OFFSET`` so the generated v4
            peers match the device's v4 secondary IPs and the IXIA-side layout.

    Returns:
        List of setup Task objects.
    """
    setup_tasks: t.List[Task] = []

    # Disable BgpTcpdump daemon before any setup
    # This daemon is not needed for conveyor testing and can interfere.
    setup_tasks.append(
        create_arista_daemon_control_task(
            hostname=device_name,
            daemon_name="BgpTcpdump",
            action="disable",
        )
    )

    # 1. Pre-IXIA interface configuration (2 interfaces, no BGP MON)
    setup_tasks.extend(
        _get_pre_ixia_interface_tasks(
            device_name=device_name,
            ixia_interfaces=[
                (ixia_interface_mimic_ebgp, "IXIA_MIMIC_EBGP"),
                (ixia_interface_mimic_ibgp, "IXIA_MIMIC_IBGP"),
            ],
        )
    )

    # 2. BGP++ config deployment
    setup_tasks.extend(
        _get_bgpcpp_deployment_tasks(
            device_name=device_name,
            bgp_asn=bgp_asn,
            bgpcpp_configerator_path=bgpcpp_configerator_path,
            openr_configerator_path=openr_configerator_path,
            enable_update_group=enable_update_group,
            update_group_config=update_group_config,
        )
    )

    # 3. Control plane (ACLs + daemons)
    setup_tasks.extend(
        _get_control_plane_tasks(
            device_name=device_name,
            profile=profile,
            enable_update_group=enable_update_group,
        )
    )

    # 4. Simplified IP configuration (IPv6 + optional IPv4)
    ebgp_address_families = (
        ["ipv6", "ipv4"] if ixia_ebgp_ic_parent_network_v4 is not None else ["ipv6"]
    )
    ibgp_address_families = (
        ["ipv6", "ipv4"] if ixia_ibgp_ic_parent_network_v4 is not None else ["ipv6"]
    )
    setup_tasks.append(
        create_interface_ip_configuration_task(
            interface=ixia_interface_mimic_ebgp,
            peer_count=ebgp_peer_count,
            ipv4_base_network=ixia_ebgp_ic_parent_network_v4,
            ipv6_base_network=ixia_ebgp_ic_parent_network_v6,
            address_families=ebgp_address_families,
            clear_existing=True,
            ipv4_start_offset=IXIA_IPV4_START_OFFSET,
            ipv6_start_offset=IXIA_IPV6_START_OFFSET,
            hostname=device_name,
            ixia_needed=True,
        )
    )
    setup_tasks.append(
        create_interface_ip_configuration_task(
            interface=ixia_interface_mimic_ibgp,
            peer_count=ibgp_peer_count,
            ipv4_base_network=ixia_ibgp_ic_parent_network_v4,
            ipv6_base_network=ixia_ibgp_ic_parent_network_v6,
            address_families=ibgp_address_families,
            clear_existing=True,
            ipv4_start_offset=IXIA_IPV4_START_OFFSET,
            ipv6_start_offset=IXIA_IPV6_START_OFFSET,
            hostname=device_name,
            ixia_needed=True,
        )
    )

    # 5. Peer modification: update bgpcpp_config with IPv6 (+ optional IPv4) peers
    ebgp_peers = _generate_ixia_v6_peer_entries_for_bgpcpp(
        remote_as=ebgp_remote_as,
        ixia_ipv6_base=ixia_ebgp_ic_parent_network_v6,
        peer_count=ebgp_peer_count,
        peer_group_v6=ebgp_peer_group_v6,
    )
    ibgp_peers = _generate_ixia_v6_peer_entries_for_bgpcpp(
        remote_as=ibgp_remote_as,
        ixia_ipv6_base=ixia_ibgp_ic_parent_network_v6,
        peer_count=ibgp_peer_count,
        peer_group_v6=ibgp_peer_group_v6,
    )
    all_peers = ebgp_peers + ibgp_peers
    if ixia_ebgp_ic_parent_network_v4 is not None:
        all_peers += _generate_ixia_v4_peer_entries_for_bgpcpp(
            remote_as=ebgp_remote_as,
            ixia_ipv4_base=ixia_ebgp_ic_parent_network_v4,
            peer_count=ebgp_peer_count,
            peer_group_v4=ebgp_peer_group_v4,
            start_offset=v4_peer_start_offset,
        )
    if ixia_ibgp_ic_parent_network_v4 is not None:
        all_peers += _generate_ixia_v4_peer_entries_for_bgpcpp(
            remote_as=ibgp_remote_as,
            ixia_ipv4_base=ixia_ibgp_ic_parent_network_v4,
            peer_count=ibgp_peer_count,
            peer_group_v4=ibgp_peer_group_v4,
            start_offset=v4_peer_start_offset,
        )

    from taac.testconfigs.routing.ebb.case1_test_config import (
        _generate_bgpcpp_peers_modification_tasks,
    )

    setup_tasks.extend(
        _generate_bgpcpp_peers_modification_tasks(
            bgpcpp_device=device_name,
            router_id=router_id,
            peers=all_peers,
        )
    )

    # 5b. Restart Bgp so it re-reads the freshly-rewritten bgpcpp_config.
    # The peer-modification above only rewrites the on-disk
    # /mnt/flash/bgpcpp_config (replacing the deployed base config's peers with
    # THIS test's peer set). bgpcpp loads its config only on (re)start, and the
    # control-plane bounce happened BEFORE the rewrite -- so without this restart
    # Bgp keeps running the base config's full-scale peers and the test's peer
    # set never takes effect (e.g. the device shows 1274 peers instead of the
    # configured count). Restart LAST so the new peers are what bgpcpp loads.
    setup_tasks.append(
        create_arista_daemon_control_task(
            hostname=device_name,
            daemon_name="Bgp",
            action="disable",
            ixia_needed=True,
        )
    )
    setup_tasks.append(
        create_arista_daemon_control_task(
            hostname=device_name,
            daemon_name="Bgp",
            action="enable",
            ixia_needed=True,
        )
    )

    # 6. OpenR setup (conditional on profile)
    setup_tasks.extend(_get_openr_setup_tasks(device_name=device_name, profile=profile))

    # 7. Flush iptables
    setup_tasks.extend(_get_iptables_flush_tasks(device_name=device_name))

    return setup_tasks


def build_update_packing_expected_peer_identity(
    ebgp_peer_count: int,
    ibgp_peer_count: int,
    ebgp_remote_as: int,
    ibgp_remote_as: int,
    ixia_ebgp_ic_parent_network_v6: str,
    ixia_ibgp_ic_parent_network_v6: str,
    ebgp_peer_group_v6: str = "EB-FA-V6",
    ibgp_peer_group_v6: str = "EB-EB-V6",
) -> t.Dict[str, str]:
    """
    Build expected {peer_addr: local_addr} mapping for update packing tests.

    Uses the same peer generation logic as get_update_packing_setup_tasks.
    This is optional — callers that don't need peer identity validation
    can skip calling this entirely.
    """
    ebgp_peers = _generate_ixia_v6_peer_entries_for_bgpcpp(
        remote_as=ebgp_remote_as,
        ixia_ipv6_base=ixia_ebgp_ic_parent_network_v6,
        peer_count=ebgp_peer_count,
        peer_group_v6=ebgp_peer_group_v6,
    )
    ibgp_peers = _generate_ixia_v6_peer_entries_for_bgpcpp(
        remote_as=ibgp_remote_as,
        ixia_ipv6_base=ixia_ibgp_ic_parent_network_v6,
        peer_count=ibgp_peer_count,
        peer_group_v6=ibgp_peer_group_v6,
    )
    return {e["peer_addr"]: e["local_addr"] for e in ebgp_peers + ibgp_peers}


# =============================================================================
# Public API: Teardown
# =============================================================================
def get_teardown_tasks(
    ixia_interface_mimic_ebgp: str,
    ixia_interface_mimic_ibgp: str,
    ixia_interface_mimic_bgp_mon: t.Optional[str] = None,
    device_name: t.Optional[str] = None,
) -> t.List[Task]:
    """
    Generate common teardown tasks for an EBB BGP++ conveyor test config.

    Restores interface IP configurations from backup for all IXIA interfaces.

    Args:
        ixia_interface_mimic_ebgp: eBGP IXIA interface
        ixia_interface_mimic_ibgp: iBGP IXIA interface
        ixia_interface_mimic_bgp_mon: BGP MON IXIA interface (optional,
            not needed for update packing tests)
        device_name: Device hostname for the cleanup tasks

    Returns:
        List of Task objects for test config teardown_tasks
    """
    tasks = [
        create_interface_ip_cleanup_task(
            interfaces=[ixia_interface_mimic_ebgp],
            restore_from_backup=True,
            hostname=device_name,
        ),
        create_interface_ip_cleanup_task(
            interfaces=[ixia_interface_mimic_ibgp],
            restore_from_backup=True,
            hostname=device_name,
        ),
    ]
    if ixia_interface_mimic_bgp_mon is not None:
        tasks.append(
            create_interface_ip_cleanup_task(
                interfaces=[ixia_interface_mimic_bgp_mon],
                restore_from_backup=True,
                hostname=device_name,
            )
        )
    return tasks


# CPU stress constants and task factories are in task_definitions.py.
# Re-export for backwards compatibility.
from taac.task_definitions import (  # noqa: F401
    CPU_STRESS_REMOTE_PATH,
    CPU_STRESS_SCRIPT,
    create_cpu_stress_setup_tasks,
    create_cpu_stress_teardown_task,
)
