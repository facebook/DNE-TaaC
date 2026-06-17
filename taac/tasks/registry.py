# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-unsafe
import os

TAAC_OSS = os.environ.get("TAAC_OSS", "").lower() in ("1", "true", "yes")

if not TAAC_OSS:
    from taac.internal.tasks.ixia_diagnostics_collection_task import (
        IxiaDiagnosticsCollectionTask,
    )
    from taac.internal.tasks.openr_route_action_task import (
        OpenRRouteActionTask,
    )
from taac.internal.tasks.bgp_peer_group_config_task import (
    GetEnforceFirstAsRejectsTask,
    SetPeerGroupEnforceFirstAsTask,
)
from taac.internal.tasks.bgp_replace_peers_task import (
    ReplaceBgpPeersTask,
    RestoreBgpPeersTask,
)
from taac.internal.tasks.bgp_set_peer_groups_policy_task import (
    BgpSetPeerGroupsPolicyTask,
)
from taac.internal.tasks.bgp_set_peers_policy_task import (
    BgpSetPeersPolicyTask,
)
from taac.internal.tasks.bgp_set_route_filter_task import (
    BgpSetRouteFilterTask,
)
from taac.internal.tasks.bgp_setting_config_task import (
    DisableMedComparisonTask,
    EnableMedComparisonTask,
    SetBgpSettingConfigTask,
)
from taac.internal.tasks.bgp_verify_received_routes_task import (
    BgpVerifyReceivedRoutesTask,
)
from taac.internal.tasks.bgp_weight_policy_task import (
    AddBgpWeightPolicyTask,
    RemoveBgpWeightPolicyTask,
)
from taac.internal.tasks.device_provisioning_task import (
    DeviceProvisioningTask,
)
from taac.internal.tasks.ixia_preflight_task import (
    IxiaPreflightTask,
)
from taac.tasks.all import (
    AddBgpPolicyMatchPrefixToPropagateRoutes,
    AddStressStaticRoutes,
    AllocateCgroupSliceMemory,
    AristaCreateFileFromConfig,
    AristaDaemonControlTask,
    AssertThriftRateLimitEnabledTask,
    ConfigureParallelBgpPeers,
    CoopApplyPatchersTask,
    CoopApplyPatchersV2,
    CoopRegisterPatcherTask,
    CoopUnregisterPatchersTask,
    CreateVipInjectors,
    DeployEosImageTask,
    InjectBgpPolicyStatements,
    InvokeConcurrentThriftRequestsTask,
    IsolatePorts,
    RunCommandsOnShell,
    ScpFile,
    SetPortChannelMinLinkPatcherTask,
    ValidateBgpcppConfigOnDevice,
    WaitForAgentConvergenceTask,
    WaitForBgpConvergenceTask,
)
from taac.tasks.bgp_policy_generator_task import (
    GenerateCommunityBgpPolicyAndInjectTask,
    GenerateCommunityBgpPolicyTask,
    GenerateMultipleCommunityBgpPoliciesTask,
)
from taac.tasks.bgp_tcpdump_task import BgpTcpdumpTask
from taac.tasks.configure_bgpcpp_startup_task import (
    ConfigureBgpcppStartupTask,
)
from taac.tasks.deploy_exabgp_task import (
    CleanupExaBGPTask,
    DeployExaBGPTask,
)
from taac.tasks.eos import (
    AddEosBgpPrefixListToPeerGroup,
    BackupRunningConfigTask,
    ConfigureEosParallelBgpPeers,
    CreateEosBgpPeerGroup,
    RestoreRunningConfigTask,
)
from taac.tasks.fpf_collector_tasks import (
    FpfStartCollectorsTask,
    FpfStopCollectorsTask,
)
from taac.tasks.fpf_ib_traffic_task import (
    FpfStartIbTrafficTask,
    FpfStopIbTrafficTask,
)
from taac.tasks.full_reboot_task import FullRebootTask
from taac.tasks.interface_ip_configuration_task import (
    InterfaceIpCleanupTask,
    InterfaceIpConfigurationTask,
)
from taac.tasks.ixia_tasks import (
    ConfigureIxiaInterfaces,
    InvokeIxiaApiTask,
    IxiaChangeAsPathLength,
    IxiaDrainUndrainBgpPeers,
    IxiaEnableDisableBgpPrefixes,
    IxiaModifyBgpPrefixesCommunities,
    IxiaModifyBgpPrefixesMedValue,
    IxiaModifyBgpPrefixesOriginValue,
    IxiaPacketCaptureTask,
    IxiaRandomizeBgpPrefixLocalPreference,
    IxiaRestartBgpSessions,
    IxiaSetBgpPrefixesLocalPreference,
)
from taac.tasks.periodic_tasks import (
    CounterThresholdTask,
    CpuLoadAverageTask,
    NexthopGroupPoll,
    OpticsTemperatureTask,
    ProcessMonitorTask,
    ThriftStressPeriodicTask,
)
from taac.tasks.verify_best_path_changes_task import (
    VerifyBestPathChangesTask,
)


TASK_REGISTRY = [
    AristaDaemonControlTask,
    AssertThriftRateLimitEnabledTask,
    BgpTcpdumpTask,
    CoopUnregisterPatchersTask,
    DeployEosImageTask,
    DeviceProvisioningTask,
    InterfaceIpCleanupTask,
    InterfaceIpConfigurationTask,
    WaitForAgentConvergenceTask,
    WaitForBgpConvergenceTask,
    ConfigureParallelBgpPeers,
    CoopRegisterPatcherTask,
    CoopApplyPatchersTask,
    InvokeConcurrentThriftRequestsTask,
    AddStressStaticRoutes,
    CreateVipInjectors,
    ScpFile,
    RunCommandsOnShell,
    AllocateCgroupSliceMemory,
    InjectBgpPolicyStatements,
    IsolatePorts,
    IxiaEnableDisableBgpPrefixes,
    IxiaRandomizeBgpPrefixLocalPreference,
    IxiaModifyBgpPrefixesOriginValue,
    IxiaDrainUndrainBgpPeers,
    IxiaRestartBgpSessions,
    AddBgpPolicyMatchPrefixToPropagateRoutes,
    CoopApplyPatchersV2,
    CounterThresholdTask,
    CpuLoadAverageTask,
    ProcessMonitorTask,
    OpticsTemperatureTask,
    InvokeIxiaApiTask,
    ConfigureIxiaInterfaces,
    IxiaModifyBgpPrefixesMedValue,
    IxiaChangeAsPathLength,
    IxiaModifyBgpPrefixesCommunities,
    IxiaSetBgpPrefixesLocalPreference,
    IxiaPacketCaptureTask,
    BgpSetRouteFilterTask,
    BgpSetPeerGroupsPolicyTask,
    BgpSetPeersPolicyTask,
    BgpVerifyReceivedRoutesTask,
    NexthopGroupPoll,
    ThriftStressPeriodicTask,
    AristaCreateFileFromConfig,
    ValidateBgpcppConfigOnDevice,
    AddBgpWeightPolicyTask,
    RemoveBgpWeightPolicyTask,
    ReplaceBgpPeersTask,
    RestoreBgpPeersTask,
    SetBgpSettingConfigTask,
    EnableMedComparisonTask,
    DisableMedComparisonTask,
    SetPeerGroupEnforceFirstAsTask,
    GetEnforceFirstAsRejectsTask,
    ConfigureBgpcppStartupTask,
    AddEosBgpPrefixListToPeerGroup,
    BackupRunningConfigTask,
    ConfigureEosParallelBgpPeers,
    CreateEosBgpPeerGroup,
    RestoreRunningConfigTask,
    VerifyBestPathChangesTask,
    DeployExaBGPTask,
    CleanupExaBGPTask,
    IxiaPreflightTask,
    GenerateCommunityBgpPolicyTask,
    GenerateMultipleCommunityBgpPoliciesTask,
    GenerateCommunityBgpPolicyAndInjectTask,
    SetPortChannelMinLinkPatcherTask,
    FullRebootTask,
    FpfStartCollectorsTask,
    FpfStopCollectorsTask,
    FpfStartIbTrafficTask,
    FpfStopIbTrafficTask,
]

if not TAAC_OSS:
    # pyre-fixme[6]: For 1st argument expected `Type[Union[AddBgpPolicyMatchPrefixToP...
    TASK_REGISTRY.append(OpenRRouteActionTask)
    # pyre-fixme[6]: For 1st argument expected `Type[Union[AddBgpPolicyMatchPrefixToP...
    TASK_REGISTRY.append(IxiaDiagnosticsCollectionTask)

TASK_NAME_TO_CLASS = {task.NAME: task for task in TASK_REGISTRY}
