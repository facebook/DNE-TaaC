// Copyright (c) Meta Platforms, Inc. and affiliates.
package "meta.com/neteng/test_infra/dne/utils/qos_config"

namespace py neteng.test_infra.dne.utils.qos_config
namespace cpp2 neteng.test_infra.dne.utils.qos_config
namespace py3 neteng.test_infra.dne.utils

# Olympic QoS Queues
enum ClassOfService {
  # TODO: find ODS key for NCNF queue
  // NCNF = 0
  BRONZE = 1,
  SILVER = 2,
  GOLD = 3,
  ICP = 4,
  NC = 5,
}

# Src : https://fburl.com/diffusion/e5lt4c25
# Maps Olympic QoS Queues to specific DSCP values for testing
const map<ClassOfService, i32> QUEUE_DSCP_BIT_MAP = {
  BRONZE: 10,
  SILVER: 0,
  GOLD: 18,
  ICP: 35,
  NC: 48,
// NCNF: 51,
};
