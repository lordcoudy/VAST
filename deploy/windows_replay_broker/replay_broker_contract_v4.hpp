#pragma once

#include <array>
#include <cstdint>
#include <optional>
#include <string>
#include <string_view>

namespace vast::replay_broker::v4 {

inline constexpr std::string_view kReplayProtocolSemanticSha256 =
    "e6c81cb0019a4103b86dfaa5585da868bd72484198e83381de7b5456e66fad88";
inline constexpr std::uint64_t kMaxArtifactBytes = 512ULL * 1024ULL * 1024ULL;
inline constexpr std::uint64_t kMaxTotalArtifactBytes = 1024ULL * 1024ULL * 1024ULL;

enum class BindingState { unvalidated, logically_bound };

struct OpaqueHandleToken final {
  std::uint64_t value;
};

enum class ArtifactRole {
  runner_entrypoint_read,
  runner_authority_read,
  validator_authority_read,
  validation_request_read,
  raw_evidence_read,
  runtime_closure_bundle_read,
};

enum class ChannelRole {
  challenge_read,
  stdin_eof_read,
  record_stdout_write,
  acknowledgement_stderr_write,
};

struct ArtifactIdentity final {
  ArtifactRole role;
  std::string file_sha256;
  std::string semantic_sha256;
  std::uint64_t size_bytes;
  OpaqueHandleToken token;
};

struct ChannelIdentity final { ChannelRole role; OpaqueHandleToken token; };

struct ContractInput final {
  std::string protocol_semantic_sha256;
  std::string project_root_identity_sha256;
  std::string session_id;
  std::string lease_id;
  std::uint32_t cell_index;
  std::uint32_t attempt_ordinal;
  std::string runner_authority_sha256;
  std::string validator_authority_sha256;
  std::string request_sha256;
  std::array<ArtifactIdentity, 6> artifacts;
  std::array<ChannelIdentity, 4> channels;
};

struct ExactFalseClaims final {
  static constexpr bool atomic_runtime_closure_snapshot_validated = false;
  static constexpr bool inherited_handle_allowlist_validated = false;
  static constexpr bool standard_handle_mapping_validated = false;
  static constexpr bool handle_sealing_validated = false;
  static constexpr bool child_path_reopen_prevented = false;
  static constexpr bool native_broker_implemented = false;
  static constexpr bool broker_state_machine_enforced = false;
  static constexpr bool challenge_delivery_validated = false;
  static constexpr bool challenge_freshness_validated = false;
  static constexpr bool stdout_integrity_validated = false;
  static constexpr bool lease_enforcement_validated = false;
  static constexpr bool sandbox_enforcement_validated = false;
  static constexpr bool process_executed = false;
  static constexpr bool validation_records_authenticated = false;
  static constexpr bool execution_authorized = false;
  static constexpr bool expected_record_parent_isolation_validated = false;
  static constexpr bool native_image_handle_binding_validated = false;
  static constexpr bool filesystem_write_policy_enforced = false;
  static constexpr bool network_policy_enforced = false;
};

struct LogicalSlot final {
  std::string_view role;
};

struct LogicalBindingCandidate final {
  BindingState prior_state;
  BindingState state;
  std::array<LogicalSlot, 10> ordered_slots;
  std::array<std::string, 21> logical_argv_projection;
  ExactFalseClaims claims;
};

[[nodiscard]] std::optional<LogicalBindingCandidate> logically_bind(
    const ContractInput& input);

}  // namespace vast::replay_broker::v4
