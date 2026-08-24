#include "replay_broker_contract_v4.hpp"

#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>

namespace {
namespace replay_v4 = vast::replay_broker::v4;

std::string digest(char digit) { return std::string(64, digit); }

replay_v4::ArtifactIdentity artifact(replay_v4::ArtifactRole role,
                                     char file_digit, char semantic_digit,
                                     std::uint64_t size_bytes,
                                     std::uint64_t token) {
  return {role, digest(file_digit), digest(semantic_digit), size_bytes, {token}};
}

replay_v4::ContractInput valid_input() {
  return {
      std::string(replay_v4::kReplayProtocolSemanticSha256),
      digest('7'),
      "session-1",
      "lease_1",
      559,
      1,
      digest('b'),
      digest('c'),
      digest('d'),
      {{artifact(replay_v4::ArtifactRole::runner_entrypoint_read, '1', 'a', 1, 101),
        artifact(replay_v4::ArtifactRole::runner_authority_read, '2', 'b', 2, 102),
        artifact(replay_v4::ArtifactRole::validator_authority_read, '3', 'c', 3, 103),
        artifact(replay_v4::ArtifactRole::validation_request_read, '4', 'd', 4, 104),
        artifact(replay_v4::ArtifactRole::raw_evidence_read, '5', 'e', 5, 105),
        artifact(replay_v4::ArtifactRole::runtime_closure_bundle_read, '6', 'f', 6, 106)}},
      {{{replay_v4::ChannelRole::challenge_read, {107}},
        {replay_v4::ChannelRole::stdin_eof_read, {108}},
        {replay_v4::ChannelRole::record_stdout_write, {109}},
        {replay_v4::ChannelRole::acknowledgement_stderr_write, {110}}}}};
}

void require(bool condition, std::string_view message) {
  if (!condition) throw std::runtime_error(std::string(message));
}

template <typename Mutator>
void require_rejected(Mutator mutate, std::string_view message) {
  auto input = valid_input();
  mutate(input);
  require(!replay_v4::logically_bind(input).has_value(), message);
}

void valid_projection_is_only_logically_bound() {
  const auto candidate = replay_v4::logically_bind(valid_input());
  require(candidate.has_value(), "valid structural input was rejected");
  require(candidate->prior_state == replay_v4::BindingState::unvalidated,
          "logical transition did not begin unvalidated");
  require(candidate->state == replay_v4::BindingState::logically_bound,
          "logical transition did not end logically_bound");
  require(candidate->ordered_slots.size() == 10,
          "projection did not contain exactly ten ordered slots");
  require(candidate->ordered_slots.front().role == "runner_entrypoint_read" &&
              candidate->ordered_slots.back().role ==
                  "acknowledgement_stderr_write",
          "projection role order drifted");
  require(candidate->logical_argv_projection.size() == 21 &&
              candidate->logical_argv_projection.front() ==
                  "vast-replay-native-runner-v4" &&
              candidate->logical_argv_projection.back() ==
                  "hmap4;runner_entrypoint_read=101;runner_authority_read=102;"
                  "validator_authority_read=103;validation_request_read=104;"
                  "raw_evidence_read=105;runtime_closure_bundle_read=106;"
                  "challenge_read=107;stdin_eof_read=108;record_stdout_write=109;"
                  "acknowledgement_stderr_write=110",
          "logical child argv drifted");
  const std::array<std::string, 21> expected_argv = {{
      "vast-replay-native-runner-v4",
      "--protocol-sha256", std::string(replay_v4::kReplayProtocolSemanticSha256),
      "--project-root-identity-sha256", digest('7'),
      "--session-id", "session-1",
      "--lease-id", "lease_1",
      "--cell-index", "559",
      "--attempt-ordinal", "1",
      "--runner-authority-sha256", digest('b'),
      "--validator-authority-sha256", digest('c'),
      "--request-sha256", digest('d'),
      "--handle-map",
      "hmap4;runner_entrypoint_read=101;runner_authority_read=102;"
      "validator_authority_read=103;validation_request_read=104;"
      "raw_evidence_read=105;runtime_closure_bundle_read=106;"
      "challenge_read=107;stdin_eof_read=108;record_stdout_write=109;"
      "acknowledgement_stderr_write=110",
  }};
  require(candidate->logical_argv_projection == expected_argv,
          "logical argv token equality drifted");
  require(!candidate->claims.atomic_runtime_closure_snapshot_validated &&
              !candidate->claims.inherited_handle_allowlist_validated &&
              !candidate->claims.standard_handle_mapping_validated &&
              !candidate->claims.handle_sealing_validated &&
              !candidate->claims.child_path_reopen_prevented &&
              !candidate->claims.native_broker_implemented &&
              !candidate->claims.broker_state_machine_enforced &&
              !candidate->claims.challenge_delivery_validated &&
              !candidate->claims.challenge_freshness_validated &&
              !candidate->claims.stdout_integrity_validated &&
              !candidate->claims.lease_enforcement_validated &&
              !candidate->claims.sandbox_enforcement_validated &&
              !candidate->claims.process_executed &&
              !candidate->claims.validation_records_authenticated &&
              !candidate->claims.execution_authorized &&
              !candidate->claims.expected_record_parent_isolation_validated &&
              !candidate->claims.native_image_handle_binding_validated &&
              !candidate->claims.filesystem_write_policy_enforced &&
              !candidate->claims.network_policy_enforced,
          "a nonauthorizing claim became true");
}

void invalid_material_is_rejected() {
  require_rejected([](auto& v) { v.protocol_semantic_sha256 = digest('9'); },
                   "wrong protocol identity was accepted");
  require_rejected([](auto& v) { v.runner_authority_sha256 = digest('8'); },
                   "runner authority crossbind mismatch was accepted");
  require_rejected([](auto& v) { v.validator_authority_sha256 = digest('8'); },
                   "validator authority crossbind mismatch was accepted");
  require_rejected([](auto& v) { v.request_sha256 = digest('8'); },
                   "request crossbind mismatch was accepted");
  require_rejected([](auto& v) { v.artifacts[1].semantic_sha256 = digest('8'); },
                   "resealed runner authority mismatch was accepted");
  require_rejected([](auto& v) { v.artifacts[2].semantic_sha256 = digest('8'); },
                   "resealed validator authority mismatch was accepted");
  require_rejected([](auto& v) { v.artifacts[3].semantic_sha256 = digest('8'); },
                   "resealed request mismatch was accepted");
  require_rejected([](auto& v) { v.artifacts[1].role = v.artifacts[0].role; },
                   "drifted artifact role was accepted");
  require_rejected([](auto& v) { v.artifacts[0].file_sha256 = digest('A'); },
                   "non-lowercase identity was accepted");
  require_rejected([](auto& v) { v.artifacts[0].file_sha256.clear(); },
                   "empty identity was accepted");
  require_rejected([](auto& v) { v.artifacts[0].file_sha256 = std::string(63, '1'); },
                   "63-character identity was accepted");
  require_rejected([](auto& v) { v.artifacts[0].file_sha256 = std::string(65, '1'); },
                   "65-character identity was accepted");
  require_rejected([](auto& v) { v.artifacts[0].file_sha256[0] = 'g'; },
                   "nonhex identity was accepted");
  auto same_ref_identity = valid_input();
  same_ref_identity.artifacts[0].semantic_sha256 =
      same_ref_identity.artifacts[0].file_sha256;
  require(replay_v4::logically_bind(same_ref_identity).has_value(),
          "same-ref file/semantic identity was incorrectly rejected");
  require_rejected([](auto& v) { v.artifacts[1].file_sha256 = v.artifacts[0].file_sha256; },
                   "cross-role duplicate file identity was accepted");
  require_rejected([](auto& v) { v.artifacts[1].semantic_sha256 = v.artifacts[0].semantic_sha256; },
                   "cross-role duplicate semantic identity was accepted");
  require_rejected([](auto& v) { v.artifacts[0].size_bytes = 0; },
                   "zero-size artifact was accepted");
  require_rejected([](auto& v) { v.artifacts[0].size_bytes = replay_v4::kMaxArtifactBytes + 1; },
                   "oversize artifact was accepted");
  require_rejected([](auto& v) {
    for (auto& artifact : v.artifacts) artifact.size_bytes = replay_v4::kMaxArtifactBytes;
  }, "oversize total was accepted");
  require_rejected([](auto& v) { v.channels[2].role = v.channels[1].role; },
                   "drifted channel role was accepted");
  require_rejected([](auto& v) { v.channels[3].token.value = 0; },
                   "zero opaque token was accepted");
  require_rejected([](auto& v) {
    v.channels[3].token.value = v.channels[2].token.value;
  },
                   "duplicate opaque token was accepted");
  require_rejected([](auto& v) {
    v.channels[0].token.value = v.artifacts[0].token.value;
  }, "cross-kind duplicate opaque token was accepted");
  for (std::uint64_t pseudo = UINT64_MAX - 3; pseudo <= UINT64_MAX; ++pseudo) {
    require_rejected([pseudo](auto& v) { v.channels[0].token.value = pseudo; },
                     "pseudo opaque token was accepted");
    if (pseudo == UINT64_MAX) break;
  }
  require_rejected([](auto& v) { v.project_root_identity_sha256 = digest('A'); },
                   "uppercase root identity was accepted");
  require_rejected([](auto& v) { v.project_root_identity_sha256 = std::string(63, '7'); },
                   "short project-root identity was accepted");
  require_rejected([](auto& v) { v.runner_authority_sha256[0] = '\0'; },
                   "NUL authority identity was accepted");
  require_rejected([](auto& v) { v.session_id.clear(); },
                   "empty session token was accepted");
  require_rejected([](auto& v) { v.session_id = std::string(129, 'a'); },
                   "129-character session token was accepted");
  require_rejected([](auto& v) { v.session_id = std::string("s") + static_cast<char>(0x80); },
                   "non-ASCII session token was accepted");
  require_rejected([](auto& v) { v.session_id = ".bad"; },
                   "invalid-leading session token was accepted");
  require_rejected([](auto& v) { v.session_id = "bad\nvalue"; },
                   "control-bearing session was accepted");
  require_rejected([](auto& v) { v.lease_id.clear(); },
                   "empty lease token was accepted");
  require_rejected([](auto& v) { v.lease_id = std::string(129, 'a'); },
                   "129-character lease token was accepted");
  require_rejected([](auto& v) { v.lease_id = std::string("l") + static_cast<char>(0x80); },
                   "non-ASCII lease token was accepted");
  require_rejected([](auto& v) { v.lease_id = "-bad"; },
                   "unsafe lease token was accepted");
  require_rejected([](auto& v) { v.cell_index = 560; },
                   "out-of-range cell was accepted");
  require_rejected([](auto& v) { v.attempt_ordinal = 2; },
                   "out-of-range attempt was accepted");
}

void logical_candidate_owns_argv_strings() {
  const auto candidate = [] {
    auto input = valid_input();
    auto local_candidate = replay_v4::logically_bind(input);
    input.protocol_semantic_sha256.assign(64, '0');
    input.project_root_identity_sha256.assign(64, '0');
    input.session_id = "mutated-session";
    input.lease_id = "mutated-lease";
    input.runner_authority_sha256.assign(64, '0');
    input.validator_authority_sha256.assign(64, '0');
    input.request_sha256.assign(64, '0');
    for (auto& artifact : input.artifacts) artifact.token.value = 999;
    for (auto& channel : input.channels) channel.token.value = 999;
    return local_candidate;
  }();
  require(candidate.has_value(), "ownership test input was rejected");
  require(candidate->logical_argv_projection[2] ==
              replay_v4::kReplayProtocolSemanticSha256 &&
              candidate->logical_argv_projection[4] == digest('7') &&
              candidate->logical_argv_projection[6] == "session-1" &&
              candidate->logical_argv_projection[8] == "lease_1" &&
              candidate->logical_argv_projection.back().find("=101;") !=
                  std::string::npos,
          "candidate argv did not own its strings");
}
}  // namespace

int main() {
  try {
    valid_projection_is_only_logically_bound();
    invalid_material_is_rejected();
    logical_candidate_owns_argv_strings();
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
  return 0;
}
