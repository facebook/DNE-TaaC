# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
SYSTEMD_BGP_SERVICE_TEMPLATE = r"""
#
# Copyright (c) 2014-present, Meta Platforms, Inc.
#

[Unit]
Description=FBOSS BGP Routing Daemon
After=wedge_agent.service
BindsTo=wedge_agent.service
# Unlimited restarts (no start limit hit within a given time period)
StartLimitIntervalSec=0

[Service]
# + == run as root ...
Type=simple
User=bgp
Group=switching
EnvironmentFile=-/etc/sysconfig/fboss_bgp_secure
# Have any XAR we spawn (e.g. core copier) umount in 1 second
Environment=XAR_MOUNT_TIMEOUT=1
ExecStartPre=+/usr/local/fbcode/bin/python3 \
    /etc/packages/neteng-fboss-bgpd/current/fboss_config_selector.py bgpcpp
ExecStart=/etc/packages/neteng-fboss-bgpd/current/cpp/bgpd_cpp \
    # Config selction is kept up to date by ExecStartPre
    --config /dev/shm/fboss/bgpcpp_startup_config \
    # symlink does not exist in non Polestar mode
    --policy /dev/shm/fboss/bgpcpp_startup_policy \
    # Default options found
    --vmodule Vip*=2 \
    --logging .=DBG1;default:async=true \
    --v 0 \
    --platform={platform} \
    --enable_crypto_auth_token_tracing_module=false \
    # Memory Tweaks pulled from wrapper
    --max_rss_size {max_rss_size} \
    --bgp_policy_cache_size {bgp_policy_cache_size} \
    --undefok=policy,disable_rib_policy_scuba_logging \
    $TLSFLAGS
ExecStartPost=+/bin/bash -c 'echo "$MAINPID" > /run/bgpd.pid'
ExecStopPost=+/usr/local/bin/fboss-core-copier \
    -p /run/bgpd.pid \
    /etc/packages/neteng-fboss-bgpd/current/cpp/bgpd_cpp \
    bgpd_cpp

Restart=always
RestartSec=1
TimeoutStopSec=12
TimeoutStopFailureMode=abort
# From output of `man systemd.service`, we have the following:
#
# If the service has a short `TimeoutStopSec=`, this option can be used to give
# the system more time to write a core dump of the service.
#
# Give 3s delta between `TimeoutStopSec` and `TimeoutAbortSec`
TimeoutAbortSec=15
LimitNOFILE=10000000
LimitCORE=32G
SyslogIdentifier=bgpd

# Disable swap for this unit file (cgroup)  until we have sorted issues
# with swap and slow disk-io
# NOTE: We disable crypto auth token tracing module to avoid configerator
# dependency on startup
MemorySwapMax=0

# Ensure capability for non root service to bind to TCP port 179
AmbientCapabilities=CAP_NET_BIND_SERVICE

# Place in unrestricted workload.slice
Slice=workload.slice

[Install]
WantedBy=multi-user.target wedge_agent.service
"""

SYSTEMD_BGP_SERVICE_TEMPLATE_NO_PLATFORM = r"""
#
# Copyright (c) 2014-present, Meta Platforms, Inc.
#

[Unit]
Description=FBOSS BGP Routing Daemon
After=wedge_agent.service
BindsTo=wedge_agent.service
# Unlimited restarts (no start limit hit within a given time period)
StartLimitIntervalSec=0

[Service]
# + == run as root ...
Type=simple
User=bgp
Group=switching
EnvironmentFile=-/etc/sysconfig/fboss_bgp_secure
# Have any XAR we spawn (e.g. core copier) umount in 1 second
Environment=XAR_MOUNT_TIMEOUT=1
ExecStartPre=+/usr/local/fbcode/bin/python3 \
    /etc/packages/neteng-fboss-bgpd/current/fboss_config_selector.py bgpcpp
ExecStart=/etc/packages/neteng-fboss-bgpd/current/cpp/bgpd_cpp \
    # Config selction is kept up to date by ExecStartPre
    --config /dev/shm/fboss/bgpcpp_startup_config \
    # symlink does not exist in non Polestar mode
    --policy /dev/shm/fboss/bgpcpp_startup_policy \
    # Default options found
    --vmodule Vip*=2 \
    --logging .=DBG1;default:async=true \
    --v 0 \
    --enable_crypto_auth_token_tracing_module=false \
    # Memory Tweaks pulled from wrapper
    --max_rss_size {max_rss_size} \
    --bgp_policy_cache_size {bgp_policy_cache_size} \
    --undefok=policy,disable_rib_policy_scuba_logging \
    $TLSFLAGS
ExecStartPost=+/bin/bash -c 'echo "$MAINPID" > /run/bgpd.pid'
ExecStopPost=+/usr/local/bin/fboss-core-copier \
    -p /run/bgpd.pid \
    /etc/packages/neteng-fboss-bgpd/current/cpp/bgpd_cpp \
    bgpd_cpp

Restart=always
RestartSec=1
TimeoutStopSec=12
TimeoutStopFailureMode=abort
# From output of `man systemd.service`, we have the following:
#
# If the service has a short `TimeoutStopSec=`, this option can be used to give
# the system more time to write a core dump of the service.
#
# Give 3s delta between `TimeoutStopSec` and `TimeoutAbortSec`
TimeoutAbortSec=15
LimitNOFILE=10000000
LimitCORE=32G
SyslogIdentifier=bgpd

# Disable swap for this unit file (cgroup)  until we have sorted issues
# with swap and slow disk-io
# NOTE: We disable crypto auth token tracing module to avoid configerator
# dependency on startup
MemorySwapMax=0

# Ensure capability for non root service to bind to TCP port 179
AmbientCapabilities=CAP_NET_BIND_SERVICE

# Place in unrestricted workload.slice
Slice=workload.slice

[Install]
WantedBy=multi-user.target wedge_agent.service
"""

# template name to template and default template parameters pair
FILE_TEMPLATES = {
    "systemd_bgp_service": (
        SYSTEMD_BGP_SERVICE_TEMPLATE,
        {"max_rss_size": "5", "bgp_policy_cache_size": "40000", "platform": "dev"},
    ),
    "systemd_bgp_service_no_platform": (
        SYSTEMD_BGP_SERVICE_TEMPLATE_NO_PLATFORM,
        {"max_rss_size": "5", "bgp_policy_cache_size": "40000"},
    ),
}
