// Copyright (c) Meta Platforms, Inc. and affiliates.
package "meta.com/neteng/test_infra/dne/taac/test_run_result"

include "configerator/structs/neteng/taac/health_check.thrift"
include "configerator/structs/neteng/taac/test_as_a_config.thrift"

namespace py3 taac
namespace py taac.test_run_result.test_run_result
namespace cpp2 facebook.taac.test_run_result

enum RunOutcome {
  UNKNOWN = 0,
  // Exit code 0.
  PASS = 1,
  // Exit code 1.
  TEST_FAILED = 2,
  // Exit code 1.
  INVALID_CONFIG = 3,
  // Exit code 128.
  INFRA_ERROR = 4,
  // The run completed without error but executed zero playbooks, so it proved
  // nothing. Exit code 1.
  NOTHING_RAN = 5,
}

enum SectionStatus {
  UNKNOWN = 0,
  PASS = 1,
  FAIL = 2,
  INFRA_ERROR = 3,
  SKIPPED = 4,
  IN_PROGRESS = 5,
}

enum InvestigationPhase {
  UNKNOWN = 0,
  TEST_CONFIG_SETUP = 1,
  TEST_CASE = 2,
  TEST_CONFIG_TEARDOWN = 3,
}

struct CheckResult {
  1: string check_name;
  2: optional test_as_a_config.ValidationStage check_stage;
  3: health_check.HealthCheckStatus status;
  4: list<string> hostnames;
  5: map<string, string> hardware_by_hostname;
  6: i64 start_time_epoch_s;
  7: i64 end_time_epoch_s;
  // Always the check's text, never a link. Once the raw text exceeds the
  // producer's inline limit this holds a truncated prefix of it and
  // `message_url` holds the whole thing: a reader gets the gist of every
  // message without a fetch, and the long ones stay reachable.
  8: optional string message;
  9: string test_case_name;
  // Set only when `message` was truncated, so its presence is what tells a
  // reader the text is a prefix.
  10: optional string message_url;
}

struct PlaybookResult {
  1: string playbook_name;
  2: string dut;
  3: i32 iteration;
  4: health_check.HealthCheckStatus status;
  5: list<CheckResult> results;
}

// Deliberately carries no log lines: a section's logs are reachable through
// `everpaste_url`.
struct SectionResult {
  1: string name;
  2: SectionStatus status;
  3: double duration_secs;
  // A section's parent is the nearest section before it in `RunResult.sections`
  // with a lower `indent_level`, so the flat list and this field already
  // reconstruct the tree and no parent pointer is needed.
  4: i32 indent_level;
  5: optional string everpaste_url;
  6: optional string error_message;
  7: i64 start_time_epoch_s;
  // Equal to `start_time_epoch_s` for a section the run abandoned before it
  // ended, which is also the only case with a zero `duration_secs`.
  8: i64 end_time_epoch_s;
}

struct InvestigationArtifact {
  1: InvestigationPhase phase;
  // The decision line produced by the investigation. It is absent when the
  // transcript exists but the agent could not produce a structured report.
  2: optional string headline;
  3: string transcript_url;
  4: optional string playbook_name;
  5: optional string dut;
}

struct RunResult {
  // The tictaac CLI ships as an fbpkg independently of whatever deserializes
  // this, so producer and consumer can be arbitrarily far apart in version.
  // Consumers reject a payload numbered above the version they were built
  // against rather than deserialize it: under SimpleJSON a field whose type
  // they do not expect is skipped and lands at its intrinsic default, so
  // reading a newer payload succeeds while quietly reporting the wrong thing.
  // Preserve the original IDL default for compatibility. Producers set their
  // current schema version explicitly.
  1: i32 schema_version = 1;
  2: string test_config;
  3: RunOutcome outcome;
  4: i32 exit_code;
  5: i64 start_time_epoch_s;
  6: i64 end_time_epoch_s;
  7: list<string> duts;
  8: list<PlaybookResult> playbooks;
  9: list<SectionResult> sections;
  10: optional string error_message;
  11: optional string log_file;
  12: list<InvestigationArtifact> investigation_artifacts;
}
