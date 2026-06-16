namespace py neteng.test_infra.ixia.ixnetwork_restpy.ixia_config_thrift
namespace py3 neteng.test_infra.ixia.ixnetwork_restpy
namespace cpp2 facebook.neteng.test_infra.ixia.ixnetwork_restpy

include "neteng/test_infra/dne/utils/if/qos_config.thrift"

package "meta.com/neteng/test_infra/ixia/ixnetwork_restpy"

################################################################################
# NOTE for N00bs: All struct field with default values are implicitly optional
# Sample Config (10/22/19): P119544133
################################################################################

enum ApiServerOsType {
  LINUX = 0,
  WINDOWS = 1,
}

enum IpAddrFamily {
  IPV4 = 0,
  IPV6 = 1,
  RAW = 2,
}

const map<IpAddrFamily, string> IP_ADDR_FAMILY_MAP = {
  IpAddrFamily.IPV4: "ipv4",
  IpAddrFamily.IPV6: "ipv6",
  IpAddrFamily.RAW: "raw",
};

const map<TrafficType, string> TRAFFIC_TYPE_MAP = {
  TrafficType.IPV4: "ipv4",
  TrafficType.IPV6: "ipv6",
  TrafficType.RAW: "raw",
};

enum BgpCapability {
  IpV4Unicast = 0,
  IpV6Unicast = 1,
  RouteRefresh = 2,
  IpV4Multicast = 3,
  IpV4MulticastVpn = 4,
  IpV6Mpls = 5,
  IpV6MplsVpn = 6,
  IpV6Multicast = 7,
  IpV6MulticastVpn = 8,
  Ipv4UnicastAddPath = 9,
  Ipv6UnicastAddPath = 10,
  LinkStateNonVpn = 11,
  NHEncodingCapabilities = 12,
  RouteConstraint = 13,
  SRTEPoliciesV4 = 14,
  SRTEPoliciesV6 = 15,
  Vpls = 16,
  ipv4UnicastFlowSpec = 17,
  ipv6UnicastFlowSpec = 18,
  IpV4MplsVpn = 19,
}

# Combination that is used to uniquely identify any IXIA port in our network
struct PhyPortConfig {
  1: string chassis_ip;
  2: i16 slot_number;
  3: i16 port_number;
}

struct IPv4AddressInfo {
  1: string starting_ip;
  2: i16 subnet_mask = 24;
  3: string increment_ip = "0.0.0.1";
  4: string gateway_starting_ip;
  5: string gateway_increment_ip = "0.0.0.0";
  6: string ip_obj_name = "";
}

struct IPv6AddressInfo {
  1: string starting_ip;
  2: i16 subnet_mask = 64;
  3: string increment_ip = "0:0:0:0:0:0:0:1";
  4: string gateway_starting_ip;
  5: string gateway_increment_ip = "0:0:0:0:0:0:0:0";
  6: string ip_obj_name = "";
}

union IpAddressInfo {
  1: IPv4AddressInfo ipv4_addr_info;
  2: IPv6AddressInfo ipv6_addr_info;
}

struct IpAddresses {
  # At least one IP address information is needed per IXIA physical port.
  # It could either be a V4 or V6 address or both. But can't be Empty.
  1: IpAddressInfo ip_addr_1;
  2: optional IpAddressInfo ip_addr_2;
  # deprecate the field above
  3: optional IPv6AddressInfo ipv6_addresses_config;
  4: optional IPv4AddressInfo ipv4_addresses_config;
}

enum EndpointType {
  IXIA_PORT = 0,
  BGP_PREFIX = 1,
}

struct Endpoint {
  1: string port_name;
  2: EndpointType endpoint_type = EndpointType.IXIA_PORT;
  # Will be used if the traffic source or destination endpoint is a BGP prefix
  # instead of a physical IXIA port
  3: optional string bgp_prefix_name;

  # Will be used if the traffic endpoint is a BGP prefix or IXIA port
  4: i32 device_group_index;
  # Will be used if the traffic endpoint is a BGP prefix
  # instead of a physical IXIA port
  5: optional i32 network_group_index;
}

enum RateType {
  # bitsPerSecond|framesPerSecond|interPacketGap|percentLineRate
  # NOTE: For now, only PERCENT_LINE_RATE is supported
  PERCENT_LINE_RATE = 0,
  // BITS_PER_SECOND = 1
  FRAMES_PER_SECOND = 2,
// INTER_PACKET_GAP = 3
}

const map<RateType, string> RATE_TYPE_MAP = {
  // BITS_PER_SECOND: "bitsPerSecond",
  FRAMES_PER_SECOND: "framesPerSecond",
  // INTER_PACKET_GAP: "interPacketGap",
  PERCENT_LINE_RATE: "percentLineRate",
};

struct TrafficRateInfo {
  1: RateType rate_type = RateType.PERCENT_LINE_RATE;
  2: i32 rate_value;
}

enum TransportProtocol {
  UDP = 0,
  TCP = 1,
}

const map<TransportProtocol, string> TRANSPORT_PROTOCOL_MAP = {
  UDP: "UDP",
  TCP: "TCP",
};

struct L4ProtocolConfig {
  1: TransportProtocol protocol = TransportProtocol.TCP;
  2: i32 src_port_start_value = 10000;
  3: i32 src_port_increment_value = 1;
  4: i32 src_port_count_value = 1000;
  5: i32 dst_port_start_value = 20000;
  6: i32 dst_port_increment_value = 1;
  7: i32 dst_port_count_value = 1000;
}

struct MPLSConfig {
  1: list<i32> label_value = [16];
  3: i32 time_to_live = 64;
  4: i32 experimental = 0;
}

enum QueryType {
  DISPLAY_NAME = 1,
  STACK_TYPE_ID = 2,
  TEMPLATE_NAME = 3,
}

const map<QueryType, string> QUERY_TYPE_MAP = {
  DISPLAY_NAME: "DisplayName",
  STACK_TYPE_ID: "StackTypeId",
  TEMPLATE_NAME: "TemplateName",
};

union AttrValue {
  1: string str;
  2: i32 integer;
  3: list<string> str_list;
  4: list<i32> integer_list;
  5: bool boolean;
}

struct Attr {
  1: string name;
  2: AttrValue value;
}

struct Query {
  1: string regex;
  2: QueryType query_type = QueryType.DISPLAY_NAME;
}

struct Field {
  1: Query query;
  2: list<Attr> attrs;
}

struct PacketHeader {
  1: Query query;
  2: optional list<Field> fields;
  3: optional Query append_to_query;
  4: bool remove_from_stack = false;
}

struct TrafficItem {
  1: optional string name;
  2: Endpoint source_endpoint;
  3: Endpoint dest_endpoint;
  4: IpAddrFamily ipaddr;
  5: TrafficRateInfo traffic_rate_info;
  # TODO: What is the correct/apt name for the traffic flow global params
  6: TrafficFlowConfig traffic_flow_config;
  7: optional L4ProtocolConfig l4_protocol_config;
  8: optional QoSConfig qos_config;
  # Delay time given in seconds to start a traffic item
  9: optional i16 start_delay_in_sec;
  # TTL/Hop Limit
  10: optional HopLimitConfig hoplimit_config;
  11: optional MPLSConfig mpls_config;
  12: optional RawTrafficType raw_traffic_type;
  13: optional string default_gateway_ipv6_addr;
  14: optional string dst_mac_addr_raw_traffic;
  15: optional string src_ipv6_addr_raw_traffic;
  16: bool enabled = true;
  20: optional list<PacketHeader> packet_headers;
  21: TrafficType traffic_type;
  # TODO: migrate to use (source|dest)_endpoints instead of (source|dest)_endpoint
  17: list<Endpoint> source_endpoints = [];
  18: list<Endpoint> dest_endpoints = [];
  19: optional string dst_ipv6_addr_raw_traffic;
}

struct PortConfig {
  # Must be unique to identify an IXIA port in the entire topology. This will
  # be used to refer src/dst end points while configuring traffic items
  1: string port_name;
  2: string description = "";
  3: PhyPortConfig phy_port_config;
  4: i16 device_multiplier = 1;
  5: IpAddresses ip_addresses;
  6: optional BgpConfigInfo bgp_config_info;
  7: optional L1Config l1_config;
  8: optional list<DeviceGroupConfig> device_group_configs;
}

struct DeviceGroupConfig {
  1: i32 device_group_index;
  2: i16 multiplier = 1;
  3: IpAddresses ip_addresses_config;
  4: optional BgpConfigInfo bgp_config;
}

struct IxiaConfig {
  1: string api_server_ip;
  2: ApiServerOsType api_server_platform_type = ApiServerOsType.WINDOWS;
  3: list<PortConfig> port_configs;
  4: list<TrafficItem> traffic_items;
  5: list<PTPConfig> ptp_configs;
}

##############################
# BGP CONFIG RELATED STRUCTS #
##############################

enum BgpPeerType {
  IBGP = 0,
  EBGP = 1,
}

enum RawTrafficType {
  LLDP = 1,
  BGP_CP = 2,
  ICMPV6_REQ = 3,
  DHCPV6 = 4,
  TCP_DIR_CONN_HOST = 5,
  TCP_REMOTE_SUBNET = 6,
  ARP = 7,
}

const map<RawTrafficType, string> RAW_TRAFFIC_TYPE_MAP = {
  LLDP: "LLDP",
  BGP_CP: "BGP_CP",
  ICMPV6_REQ: "ICMPV6_REQ",
  DHCPV6: "DHCPV6",
  TCP_DIR_CONN_HOST: "TCP_DIR_CONN_HOST",
  TCP_REMOTE_SUBNET: "TCP_REMOTE_SUBNET",
  ARP: "ARP",
};

const map<BgpPeerType, string> BGP_PEER_TYPE_MAP = {
  IBGP: "internal",
  EBGP: "external",
};

struct BgpFlapConfig {
  1: i16 uptime_in_sec;
  2: i16 downtime_in_sec;
}

struct BgpPeerConfig {
  1: optional i32 local_as;
  2: BgpPeerType peer_type = BgpPeerType.EBGP;
  3: string local_peer_starting_ip;
  4: string local_peer_increment_ip;
  5: string remote_peer_starting_ip;
  6: string remote_peer_increment_ip;
  7: bool enable_graceful_restart = false;
  // @lint-ignore LINEWRAP
  8: list<BgpCapability> capabilities = [
    BgpCapability.IpV4Unicast,
    BgpCapability.IpV6Unicast,
  ];
  9: optional BgpFlapConfig peer_flap_config;
  10: optional bool advertise_end_of_rib;
  11: optional i32 graceful_restart_timer;
  12: optional bool is_confed;
  13: optional i64 local_as_4_bytes;
  14: bool enable_4_byte_local_as = true;
  15: i32 local_as_increment = 0;
}

enum PrefixLengthDistributionAlgorithmType {
  PERCENTAGE = 0,
  WEIGHTED = 1,
  AUTOEVEN = 2,
  AUTOGEOMETRIC = 3,
}

const map<
  PrefixLengthDistributionAlgorithmType,
  string
> PREFIX_LENGTH_DISTRIBUTED_ALGORITHM_MAP = {
  PrefixLengthDistributionAlgorithmType.PERCENTAGE: "percentage",
  PrefixLengthDistributionAlgorithmType.WEIGHTED: "weighted",
  PrefixLengthDistributionAlgorithmType.AUTOEVEN: "autoEven",
  PrefixLengthDistributionAlgorithmType.AUTOGEOMETRIC: "autoGeometric",
};

enum PrefixLengthDistributionModeType {
  # The custom distribution algo will be applied on all the prefixes for the entire device group
  PERDEVICE = 0,
  # The custom distribution algo will be applied on all the prefixes for the entire topology obj
  PERTOPOLOGY = 1,
  # The custom distribution algo will be applied on all the prefixes for the entire ixia port
  PERPORT = 2,
}

const map<
  PrefixLengthDistributionModeType,
  string
> PREFIX_LENGTH_DISTRIBUTED_MODE_MAP = {
  PrefixLengthDistributionModeType.PERDEVICE: "perDevice",
  PrefixLengthDistributionModeType.PERTOPOLOGY: "perTopology",
  PrefixLengthDistributionModeType.PERPORT: "perPort",
};

struct DistributedPrefixLengthConfig {
  # Algorithm to use for custom distribution of prefix length
  1: PrefixLengthDistributionAlgorithmType algorithm;
  # Mode to use for custom distribution of prefix length
  2: PrefixLengthDistributionModeType mode;
  # Value map to use for custom distribution of prefix length.
  # Key is prefix length and its value is its weightage.
  3: map<i16, i16> prefix_length_value_weight_map;
}

struct BgpPrefixConfig {
  1: string prefix_name;
  2: string starting_ip;
  # Increment for IP address between different clients
  3: string increment_ip;
  # Use when single valued prefix length for all ixia advertised bgp prefixes is desired
  # It has precedence over DistributedPrefixLengthConfig
  4: optional i16 prefix_length;
  # Number of prefixes per client
  5: i32 count;
  6: optional BgpFlapConfig prefix_flap_config;
  7: optional BgpCommunity bgp_community;
  8: optional AsPathPrepend as_path_prepend;
  14: optional list<AsPathPrepend> as_path_prepends;
  9: optional list<BgpCommunity> bgp_communities;
  # Use when custom distribution pattern is required to be used for bgp prefix lengths.
  10: optional DistributedPrefixLengthConfig distributed_prefix_length_config;
  # Address family is included in the prefix config as well, as we should be able to
  # advertise v4 prefixes over v6 peers
  11: optional IpAddrFamily af_type;
  12: i32 network_group_index;
  13: i32 multiplier;
}

enum BgpCommunityType {
  NOEXPORT = 0,
  NOADVERTISED = 1,
  NOEXPORT_SUBCONFED = 2,
  MANUAL = 3,
  // For details about LLGR options - refer http://docs.frrouting.org/en/latest/bgp.html
  LLGR_STALE = 4,
  NO_LLGR = 5,
}

const map<BgpCommunityType, string> BGP_COMMUNITY_TYPE_MAP = {
  BgpCommunityType.NOEXPORT: "noexport",
  BgpCommunityType.NOADVERTISED: "noadvertised",
  BgpCommunityType.NOEXPORT_SUBCONFED: "noexport_subconfed",
  BgpCommunityType.MANUAL: "manual",
  BgpCommunityType.LLGR_STALE: "llgr_stale",
  BgpCommunityType.NO_LLGR: "no_llgr",
};

struct BgpCommunity {
  1: BgpCommunityType bgp_community_type;
  // For ex., as_number would be '65000' in '65000:100'
  2: i64 as_number;
  // For ex., last_two_octets would be '100' in '65000:100'
  3: i64 last_two_octets;
}

struct AsPathPrepend {
  // For ex., [65000, 65000]
  1: list<i64> as_numbers;
}

struct CustomNetworkGroupConfig {
  1: string device_group_name;
  2: string network_group_name;
  3: i32 network_group_multiplier;
  4: string prefix_start_value;
  5: optional i16 prefix_length;
  6: optional string nexthop_start_value;
  7: optional string nexthop_increments;
  8: optional i32 ecmp_width;
  9: optional i32 number_of_addresses_per_row;
  10: optional list<string> community_list;
  11: optional string next_hop_type;
  12: optional string next_hop_ip_type;
  13: optional string next_hop_increment_mode;
  14: optional i32 network_group_index;
}

struct BgpConfig {
  1: IpAddrFamily af_type;
  2: BgpPeerConfig bgp_peer_config;
  3: optional list<BgpPrefixConfig> bgp_prefix_configs;
  4: optional list<CustomNetworkGroupConfig> custom_network_group_configs;
}

struct BgpConfigInfo {
  1: optional BgpConfig bgp_v4_config;
  2: optional BgpConfig bgp_v6_config;
}

#######################################
# TRAFFIC ITEM CONFIG RELATED STRUCTS #
#######################################

enum TransmissionControlType {
  # auto|burstFixedDuration|continuous|custom|fixedDuration|fixedFrameCount|fixedIterationCount
  # NOTE: Only CONTINUOUS mode is supported as of now
  CONTINUOUS = 0,
  FIXED_DURATION = 1,
  FIXED_FRAME_COUNT = 2,
}

const map<TransmissionControlType, string> TRANS_CONTROL_TYPE_MAP = {
  CONTINUOUS: "continuous",
  FIXED_DURATION: "fixedDuration",
  FIXED_FRAME_COUNT: "fixedFrameCount",
};

struct TransmissionControl {
  1: TransmissionControlType type = TransmissionControlType.CONTINUOUS;
  # Will be used for FIXED_FRAME_COUNT mode
  2: i32 frame_count = 10000;
  # Will be used for FIXED_DURATION mode. Unit in seconds
  3: i32 duration = 300; # in seconds
}

enum FramePayloadPattern {
  # decrementByte|decrementWord|incrementByte|incrementWord|random
  INCREMENT_BYTE = 0,
  INCREMENT_WORD = 1,
  DECREMENT_BYTE = 2,
  DECREMENT_WORD = 3,
  RANDOM = 4,
}

const map<FramePayloadPattern, string> FRAME_PAYLOAD_PATTERN_MAP = {
  INCREMENT_BYTE: "incrementByte",
  INCREMENT_WORD: "incrementWord",
  DECREMENT_BYTE: "decrementByte",
  DECREMENT_WORD: "decrementWord",
  RANDOM: "random",
};

enum RateDistributionType {
  # applyRateToAll|splitRateEvenly
  APPLY_RATE_TO_ALL = 0,
  SPLIT_RATE_EVENLY = 1,
}

const map<RateDistributionType, string> RATE_DIS_TYPE_MAP = {
  APPLY_RATE_TO_ALL: "applyRateToAll",
  SPLIT_RATE_EVENLY: "splitRateEvenly",
};

struct RateDistribution {
  // @lint-ignore LINEWRAP
  1: RateDistributionType port_rate_distribution = RateDistributionType.APPLY_RATE_TO_ALL; # noqa: B950
  // @lint-ignore LINEWRAP
  2: RateDistributionType flowgroups_rate_distribution = RateDistributionType.SPLIT_RATE_EVENLY; # noqa: B950
}

enum SrcDestMeshType {
  # fullMesh|manyToMany|none|oneToOne
  FULL_MESH = 0,
  MANY_TO_MANY = 1,
  NONE = 2,
  ONE_TO_ONE = 3,
}

const map<SrcDestMeshType, string> SRC_DEST_MESH_MAP = {
  FULL_MESH: "fullMesh",
  MANY_TO_MANY: "manyToMany",
  NONE: "none",
  ONE_TO_ONE: "oneToOne",
};

enum RouteMeshType {
  # fullMesh|oneToOne
  ROUTE_ONE_TO_ONE = 0,
  ROUTE_FULL_MESH = 1,
}

const map<RouteMeshType, string> ROUTE_MESH_MAP = {
  ROUTE_ONE_TO_ONE: "oneToOne",
  ROUTE_FULL_MESH: "fullMesh",
};

enum TransmitModeType {
  # interleaved|sequential
  INTERLEAVED = 0,
  SEQUENTIAL = 1,
}

const map<TransmitModeType, string> TRANSMIT_MODE_MAP = {
  INTERLEAVED: "interleaved",
  SEQUENTIAL: "sequential",
};

enum CrcType {
  # badCrc|goodCrc
  GOOD_CRC = 0,
  BAD_CRC = 1,
}

const map<CrcType, string> CRC_TYPE_MAP = {
  GOOD_CRC: "goodCrc",
  BAD_CRC: "badCrc",
};

enum FrameSizeType {
  # auto|fixed|increment|presetDistribution|quadGaussian|random|weightedPairs
  FIXED = 0,
  INCREMENT = 1,
  CUSTOM_IMIX = 2,
}

const map<FrameSizeType, string> FRAME_SIZE_TYPE_MAP = {
  FIXED: "fixed",
  INCREMENT: "increment",
  CUSTOM_IMIX: "weightedPairs",
};

struct FrameSize {
  1: FrameSizeType type = FrameSizeType.FIXED;
  # Used by FrameSizeType.FIXED mode
  2: i16 fixed_size = 400;
  # Used by FrameSizeType.INCREMENT mode
  3: i16 increment_from = 64;
  # Used by FrameSizeType.INCREMENT mode
  4: i16 increment_step = 100;
  # Used by FrameSizeType.INCREMENT mode
  5: i16 increment_to = 1500;
  # Used by FrameSizeType.CUSTOM_IMIX mode
  # defines farame size to weight mapping
  6: map<i16, i16> imix_weight = {128: 2, 1000: 1, 9000: 1};
}

enum TrafficStatsTrackingType {
  TRAFFIC_ITEM = 0,
  FLOW_GROUP = 1,
  SRC_DEST_ENDPOINT_PAIR = 2,
  SRC_DEST_VALUE_PAIR = 3,
  TCP_DST_PORT = 4,
  IPV6_DST_ADDR = 5,
  UDP_SRC_PORT = 6,
  UDP_DST_PORT = 7,
}

const map<TrafficStatsTrackingType, string> TRAFFIC_STATS_TRACKING_TYPE_MAP = {
  TRAFFIC_ITEM: "trackingenabled0",
  FLOW_GROUP: "flowGroup0",
  SRC_DEST_ENDPOINT_PAIR: "sourceDestEndpointPair0",
  SRC_DEST_VALUE_PAIR: "sourceDestValuePair0",
  TCP_DST_PORT: "tcpTcpDstPrt0",
  IPV6_DST_ADDR: "ipv6DestIp0",
  UDP_SRC_PORT: "udpUdpSrcPrt0",
  UDP_DST_PORT: "udpUdpDstPrt0",
};

struct TrafficFlowConfig {
  # TODO: Setting CRC type support is missing as IXIA RestPy has not yet
  #  implemented it, unlike the low level APIs
  1: TransmissionControl transmission_control;
  2: RateDistribution rate_distribution;
  3: FrameSize frame_size;
  // @lint-ignore LINEWRAP
  4: FramePayloadPattern frame_payload_pattern = FramePayloadPattern.INCREMENT_BYTE;
  5: SrcDestMeshType src_dest_mesh = SrcDestMeshType.MANY_TO_MANY;
  6: RouteMeshType route_mesh = RouteMeshType.ROUTE_FULL_MESH;
  7: bool allow_self_destined = false;
  8: bool bidirectional = true;
  9: bool merge_destinations = false;
  10: TransmitModeType transmit_mode = TransmitModeType.INTERLEAVED;
  11: CrcType crc_type = CrcType.GOOD_CRC;
  # By default, TrafficStatsTrackingType.TRAFFIC_ITEM will always be enabled
  12: list<TrafficStatsTrackingType> tracking_types;
}

enum PHBTypes {
  # TRAFFIC CLASS is the DS field for IPv6
  # Rest of the fields signify the various ways
  # to specify DS values for IPv4 https://fburl.com/wda68475
  DEFAULT = 0,
  CLASSSELECTOR = 1,
  AF = 2,
  EF = 3,
  TRAFFIC_CLASS = 4,
}

# Maps PHBtypes to IXIA Rest API strings
const map<PHBTypes, string> DSCP_MAP = {
  DEFAULT: "Default PHB",
  CLASSSELECTOR: "Class selector",
  AF: "Assured forwarding PHB",
  EF: "Expedited forwarding PHB",
  TRAFFIC_CLASS: "Traffic Class",
};

# QoS config for IXIA packet generation API
struct QoSConfig {
  # Default PHBType is Traffic class for IPv6
  # Other values can be specified for IPv4 from
  # DSCP_MAP
  1: PHBTypes phb_type = TRAFFIC_CLASS;
  # Specific value for DSCP that a packet must be
  # marked with. This value will be modified if
  # packet type is IPv6
  # Users need to specify either value or queue name
  # If both are specified , the value will win
  2: optional i32 value;
  # Olympic QoS Queue Name
  3: optional qos_config.ClassOfService olympic_queue;
}

# TTL/Hop Limit config for IXIA packet generation API
struct HopLimitConfig {
  1: i32 value;
}

struct PTPConfig {
  1: string server_port_name;
  2: list<string> client_port_name_list;
  3: string communication_mode;
  4: string step_mode;
}

enum PfcQueue {
  ZERO = 0,
  ONE = 1,
  TWO = 2,
  THREE = 3,
  FOUR = 4,
  FIVE = 5,
  SIX = 6,
  SEVEN = 7,
  NONE = 999,
}

const map<PfcQueue, string> PFC_QUEUE_MAP = {
  PfcQueue.NONE: "-1",
  ZERO: "0",
  ONE: "1",
  TWO: "2",
  THREE: "3",
  FOUR: "4",
  FIVE: "5",
  SIX: "6",
  SEVEN: "7",
};

enum FlowControlType {
  IEEE_802_1_QBB = 1,
  IEEE_802_3X = 2,
}

const map<FlowControlType, string> FLOW_CONTROL_TYPE_MAP = {
  IEEE_802_1_QBB: "ieee802.1Qbb",
  IEEE_802_3X: "ieee802.3x",
};

struct PfcPriorityGroupsConfig {
  1: PfcQueue priority0_pfc_queue = PfcQueue.ZERO;
  2: PfcQueue priority1_pfc_queue = PfcQueue.ONE;
  3: PfcQueue priority2_pfc_queue = PfcQueue.TWO;
  4: PfcQueue priority3_pfc_queue = PfcQueue.THREE;
  5: PfcQueue priority4_pfc_queue = PfcQueue.NONE;
  6: PfcQueue priority5_pfc_queue = PfcQueue.NONE;
  7: PfcQueue priority6_pfc_queue = PfcQueue.NONE;
  8: PfcQueue priority7_pfc_queue = PfcQueue.NONE;
}

struct FlowControlConfig {
  1: optional bool enable_pfc_pause_delay;
  2: optional PfcPriorityGroupsConfig pfc_prority_groups_config;
  3: optional FlowControlType flow_control_type;
}

struct L1Config {
  1: bool enable_fcoe = false;
  2: optional FlowControlConfig flow_control_config;
}

enum TrafficType {
  IPV4 = 1,
  IPV6 = 2,
  RAW = 3,
}
