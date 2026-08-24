#pragma once

#include "replay_broker_prepared_handles_v4.hpp"

#include <Windows.h>

#include <array>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>
#include <variant>

namespace vast::replay_broker::v4 {

inline constexpr std::size_t kArtifactObservationGlobalIndex = 6;

enum class ArtifactBytesObservationState {
  prepared_artifact_file_bytes_sha256_point_in_time_validated,
};

struct ArtifactBytesObservationClaims final {
  static constexpr bool artifact_file_bytes_sha256_point_in_time_validated = true;
  static constexpr bool all_six_expected_length_byte_sequences_observed = true;
  static constexpr bool handle_relative_reopen_used = true;
  static constexpr bool separate_reopened_file_objects_used_for_reads = true;
  static constexpr bool pre_post_identity_metadata_stable_point_in_time = true;
  static constexpr bool results_published_all_or_none = true;
  static constexpr bool prepared_handle_custody_retained = true;
  static constexpr bool artifact_semantic_identity_validated = false;
  static constexpr bool source_bytes_immutable_validated = false;
  static constexpr bool atomic_six_artifact_snapshot_validated = false;
  static constexpr bool coherent_cross_artifact_snapshot_validated = false;
  static constexpr bool mutation_impossible_validated = false;
  static constexpr bool digest_binds_future_child_consumption = false;
  static constexpr bool bounded_completion_latency_validated = false;
  static constexpr bool inherited_handle_allowlist_validated = false;
  static constexpr bool ambient_inheritable_handles_absent_validated = false;
  static constexpr bool process_created = false;
  static constexpr bool process_executed = false;
  static constexpr bool execution_authorized = false;
};

struct ArtifactByteObservation final {
  ArtifactRole role;
  std::uint64_t bytes_observed;
  std::array<std::uint8_t, 32> sha256;
};

enum class ArtifactBytesObservationError {
  none,
  invalid_prepared_state,
  frozen_metadata_invalid,
  allocation_failed,
  bcrypt_provider_open_failed,
  bcrypt_property_query_failed,
  bcrypt_property_invalid,
  bcrypt_hash_create_failed,
  bcrypt_hash_update_failed,
  bcrypt_hash_finish_failed,
  reopen_failed,
  reopened_handle_flags_query_failed,
  reopened_handle_flags_invalid,
  disk_endpoint_invalid,
  metadata_query_failed,
  metadata_identity_mismatch,
  metadata_shape_invalid,
  metadata_size_mismatch,
  metadata_changed,
  seek_failed,
  read_failed,
  unexpected_eof,
  trailing_bytes,
  sha256_mismatch,
};

enum class ArtifactBytesObservationStage {
  input,
  crypto_provider,
  crypto_properties,
  reopen,
  before_read_metadata,
  seek,
  read,
  hash_update,
  hash_finish,
  after_read_metadata,
  compare,
};

struct ArtifactBytesObservationFailure final {
  ArtifactBytesObservationError error = ArtifactBytesObservationError::none;
  ArtifactBytesObservationStage stage = ArtifactBytesObservationStage::input;
  std::size_t index = kArtifactObservationGlobalIndex;
  std::uint64_t offset = 0;
  DWORD win32_error = ERROR_SUCCESS;
  LONG bcrypt_status = 0;
};

struct ArtifactBytesObservationImplementation;

class ArtifactBytesObservedPreparedOsHandleSet final {
 public:
  ~ArtifactBytesObservedPreparedOsHandleSet();
  ArtifactBytesObservedPreparedOsHandleSet(
      const ArtifactBytesObservedPreparedOsHandleSet&) = delete;
  ArtifactBytesObservedPreparedOsHandleSet& operator=(
      const ArtifactBytesObservedPreparedOsHandleSet&) = delete;
  ArtifactBytesObservedPreparedOsHandleSet(
      ArtifactBytesObservedPreparedOsHandleSet&&) noexcept;
  ArtifactBytesObservedPreparedOsHandleSet& operator=(
      ArtifactBytesObservedPreparedOsHandleSet&&) noexcept;

  [[nodiscard]] bool valid() const noexcept;
  [[nodiscard]] std::optional<ArtifactBytesObservationState> state()
      const noexcept;
  [[nodiscard]] const PreparedOsHandleSet* prepared_handles() const noexcept;
  [[nodiscard]] const std::array<ArtifactByteObservation, 6>* observations()
      const noexcept;
  [[nodiscard]] const ArtifactBytesObservationClaims* claims() const noexcept;

 private:
  explicit ArtifactBytesObservedPreparedOsHandleSet(
      std::unique_ptr<ArtifactBytesObservationImplementation>
          implementation) noexcept;
  std::unique_ptr<ArtifactBytesObservationImplementation> implementation_;
  friend struct ArtifactBytesObservationImplementation;
};

using ArtifactBytesObservationResult = std::variant<
    ArtifactBytesObservedPreparedOsHandleSet, ArtifactBytesObservationFailure>;

// This transition consumes PREPARED custody. Success retains it in the new
// typestate; every failure destroys it and closes all ten child HANDLE values.
[[nodiscard]] ArtifactBytesObservationResult observe_artifact_bytes(
    PreparedOsHandleSet prepared) noexcept;

#if defined(VAST_REPLAY_BROKER_ARTIFACT_BYTES_OBSERVATION_TESTING)
enum class ArtifactBytesObservationTestFailurePoint {
  none,
  reopen,
  bcrypt_open,
  bcrypt_object_length,
  bcrypt_hash_length,
  bcrypt_create,
  seek,
  read,
  bcrypt_update,
  bcrypt_finish,
  final_metadata,
};

struct ArtifactBytesObservationTestResources final {
  std::size_t reopened_handles;
  std::size_t algorithm_providers;
  std::size_t hash_handles;
};

void set_artifact_bytes_observation_test_failure(
    ArtifactBytesObservationTestFailurePoint point,
    std::size_t ordinal) noexcept;
[[nodiscard]] ArtifactBytesObservationTestResources
artifact_bytes_observation_test_resources() noexcept;
#endif

}  // namespace vast::replay_broker::v4
