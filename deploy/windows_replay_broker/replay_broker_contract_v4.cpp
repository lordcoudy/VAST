#include "replay_broker_contract_v4.hpp"

#include <array>
#include <string>
#include <utility>

namespace vast::replay_broker::v4 {
namespace {

constexpr std::array<ArtifactRole, 6> kArtifactRoles = {
    ArtifactRole::runner_entrypoint_read,
    ArtifactRole::runner_authority_read,
    ArtifactRole::validator_authority_read,
    ArtifactRole::validation_request_read,
    ArtifactRole::raw_evidence_read,
    ArtifactRole::runtime_closure_bundle_read,
};

constexpr std::array<ChannelRole, 4> kChannelRoles = {
    ChannelRole::challenge_read,
    ChannelRole::stdin_eof_read,
    ChannelRole::record_stdout_write,
    ChannelRole::acknowledgement_stderr_write,
};

constexpr std::array<LogicalSlot, 10> kOrderedSlots = {{
    {"runner_entrypoint_read"},
    {"runner_authority_read"},
    {"validator_authority_read"},
    {"validation_request_read"},
    {"raw_evidence_read"},
    {"runtime_closure_bundle_read"},
    {"challenge_read"},
    {"stdin_eof_read"},
    {"record_stdout_write"},
    {"acknowledgement_stderr_write"},
}};

bool is_lowercase_sha256(std::string_view value) noexcept {
  if (value.size() != 64) return false;
  for (const char character : value) {
    if (!((character >= '0' && character <= '9') ||
          (character >= 'a' && character <= 'f'))) {
      return false;
    }
  }
  return true;
}

bool is_safe_token(std::string_view value) noexcept {
  if (value.empty() || value.size() > 128) return false;
  const auto alnum = [](char character) {
    return (character >= 'A' && character <= 'Z') ||
           (character >= 'a' && character <= 'z') ||
           (character >= '0' && character <= '9');
  };
  if (!alnum(value.front())) return false;
  for (const char character : value) {
    if (!(alnum(character) || character == '.' || character == '_' ||
          character == '-')) {
      return false;
    }
  }
  return true;
}

bool is_valid_opaque_token(std::uint64_t value) noexcept {
  return value != 0 && value < UINT64_MAX - 3;
}

bool artifacts_are_valid(const std::array<ArtifactIdentity, 6>& artifacts) noexcept {
  std::uint64_t total = 0;
  for (std::size_t index = 0; index < artifacts.size(); ++index) {
    const auto& artifact = artifacts[index];
    if (artifact.role != kArtifactRoles[index] ||
        !is_lowercase_sha256(artifact.file_sha256) ||
        !is_lowercase_sha256(artifact.semantic_sha256) ||
        artifact.size_bytes == 0 || artifact.size_bytes > kMaxArtifactBytes ||
        !is_valid_opaque_token(artifact.token.value) ||
        total > kMaxTotalArtifactBytes - artifact.size_bytes) {
      return false;
    }
    for (std::size_t prior = 0; prior < index; ++prior) {
      if (artifact.file_sha256 == artifacts[prior].file_sha256 ||
          artifact.semantic_sha256 == artifacts[prior].semantic_sha256) {
        return false;
      }
    }
    total += artifact.size_bytes;
  }
  return total <= kMaxTotalArtifactBytes;
}

bool tokens_are_pairwise_distinct(
    const std::array<ArtifactIdentity, 6>& artifacts,
    const std::array<ChannelIdentity, 4>& channels) noexcept {
  std::array<std::uint64_t, 10> values{};
  for (std::size_t index = 0; index < artifacts.size(); ++index) {
    values[index] = artifacts[index].token.value;
  }
  for (std::size_t index = 0; index < channels.size(); ++index) {
    values[artifacts.size() + index] = channels[index].token.value;
  }
  for (std::size_t index = 0; index < values.size(); ++index) {
    for (std::size_t prior = 0; prior < index; ++prior) {
      if (values[index] == values[prior]) return false;
    }
  }
  return true;
}

bool channels_are_valid(const std::array<ChannelIdentity, 4>& channels) noexcept {
  for (std::size_t index = 0; index < channels.size(); ++index) {
    if (channels[index].role != kChannelRoles[index] ||
        !is_valid_opaque_token(channels[index].token.value)) {
      return false;
    }
  }
  return true;
}

std::string handle_map_descriptor(
    const std::array<ArtifactIdentity, 6>& artifacts,
    const std::array<ChannelIdentity, 4>& channels) {
  return "hmap4;runner_entrypoint_read=" + std::to_string(artifacts[0].token.value) +
      ";runner_authority_read=" + std::to_string(artifacts[1].token.value) +
      ";validator_authority_read=" + std::to_string(artifacts[2].token.value) +
      ";validation_request_read=" + std::to_string(artifacts[3].token.value) +
      ";raw_evidence_read=" + std::to_string(artifacts[4].token.value) +
      ";runtime_closure_bundle_read=" + std::to_string(artifacts[5].token.value) +
      ";challenge_read=" + std::to_string(channels[0].token.value) +
      ";stdin_eof_read=" + std::to_string(channels[1].token.value) +
      ";record_stdout_write=" + std::to_string(channels[2].token.value) +
      ";acknowledgement_stderr_write=" + std::to_string(channels[3].token.value);
}

}  // namespace

std::optional<LogicalBindingCandidate> logically_bind(
    const ContractInput& input) {
  if (input.protocol_semantic_sha256 != kReplayProtocolSemanticSha256 ||
      !is_lowercase_sha256(input.project_root_identity_sha256) ||
      !is_safe_token(input.session_id) || !is_safe_token(input.lease_id) ||
      input.cell_index > 559 || input.attempt_ordinal > 1 ||
      !is_lowercase_sha256(input.runner_authority_sha256) ||
      !is_lowercase_sha256(input.validator_authority_sha256) ||
      !is_lowercase_sha256(input.request_sha256) ||
      !artifacts_are_valid(input.artifacts) || !channels_are_valid(input.channels) ||
      !tokens_are_pairwise_distinct(input.artifacts, input.channels) ||
      input.runner_authority_sha256 != input.artifacts[1].semantic_sha256 ||
      input.validator_authority_sha256 != input.artifacts[2].semantic_sha256 ||
      input.request_sha256 != input.artifacts[3].semantic_sha256) {
    return std::nullopt;
  }
  std::array<std::string, 21> argv = {{
      "vast-replay-native-runner-v4",
      "--protocol-sha256", input.protocol_semantic_sha256,
      "--project-root-identity-sha256", input.project_root_identity_sha256,
      "--session-id", input.session_id,
      "--lease-id", input.lease_id,
      "--cell-index", std::to_string(input.cell_index),
      "--attempt-ordinal", std::to_string(input.attempt_ordinal),
      "--runner-authority-sha256", input.runner_authority_sha256,
      "--validator-authority-sha256", input.validator_authority_sha256,
      "--request-sha256", input.request_sha256,
      "--handle-map", handle_map_descriptor(input.artifacts, input.channels),
  }};
  return LogicalBindingCandidate{BindingState::unvalidated,
                                 BindingState::logically_bound,
                                 kOrderedSlots,
                                 std::move(argv),
                                 ExactFalseClaims{}};
}

}  // namespace vast::replay_broker::v4
