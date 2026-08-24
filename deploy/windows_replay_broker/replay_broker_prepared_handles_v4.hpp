#pragma once

#include "replay_broker_contract_v4.hpp"

#include <Windows.h>

#include <array>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <variant>

namespace vast::replay_broker::v4 {

struct PreparedHandlesImplementation;
namespace detail {
class PreparedHandleObservationBridge;
}

enum class TransferHandleError {
  none,
  allocation_failed,
  invalid_handle,
  duplicate_handle_value,
  handle_flags_query_failed,
  handle_flags_not_zero,
};

enum class PrepareHandleError {
  allocation_failed,
  logical_contract_invalid,
  original_handle_revalidation_failed,
  disk_access_invalid,
  disk_endpoint_invalid,
  disk_metadata_invalid,
  artifact_size_mismatch,
  duplicate_disk_identity,
  duplicate_endpoint_object,
  pipe_access_invalid,
  pipe_direction_invalid,
  pipe_type_invalid,
  duplicate_failed,
  duplicate_revalidation_failed,
  attribute_list_failed,
};

class TransferredHandleSet;

struct TakeExclusiveFailure final {
  TransferHandleError error = TransferHandleError::none;
  std::size_t index = 0;
};

struct TakeExclusiveResult final {
  std::unique_ptr<TransferredHandleSet> value;
  TakeExclusiveFailure failure;
};

class TransferredHandleSet final {
 public:
  ~TransferredHandleSet();
  TransferredHandleSet(const TransferredHandleSet&) = delete;
  TransferredHandleSet& operator=(const TransferredHandleSet&) = delete;
  TransferredHandleSet(TransferredHandleSet&&) noexcept;
  TransferredHandleSet& operator=(TransferredHandleSet&&) noexcept;

  // Exclusive custody is a precondition. Failure retains caller custody and
  // closes nothing; success transfers custody of all ten values.
  [[nodiscard]] static TakeExclusiveResult take_exclusive(
      const std::array<HANDLE, 10>& raw_handles) noexcept;

 private:
  explicit TransferredHandleSet(std::array<HANDLE, 10> handles) noexcept;
  std::array<HANDLE, 10> release_all() noexcept;
  std::array<HANDLE, 10> handles_{};
  friend struct PreparedHandlesImplementation;
};

enum class PreparedHandleState { prepared_os_handles_validated };

struct PreparedHandleClaims final {
  static constexpr bool original_handle_flags_point_in_time_validated = true;
  static constexpr bool os_handle_endpoint_shape_point_in_time_validated = true;
  static constexpr bool broker_owned_duplicate_set_point_in_time_validated = true;
  static constexpr bool prepared_standard_handle_mapping_constructed = true;
  static constexpr bool artifact_file_bytes_identity_validated = false;
  static constexpr bool artifact_semantic_identity_validated = false;
  static constexpr bool inherited_handle_allowlist_validated = false;
  static constexpr bool ambient_inheritable_handles_absent_validated = false;
  static constexpr bool process_created = false;
  static constexpr bool process_executed = false;
  static constexpr bool execution_authorized = false;
};

class PreparedOsHandleSet final {
 public:
  ~PreparedOsHandleSet();
  PreparedOsHandleSet(const PreparedOsHandleSet&) = delete;
  PreparedOsHandleSet& operator=(const PreparedOsHandleSet&) = delete;
  PreparedOsHandleSet(PreparedOsHandleSet&&) noexcept;
  PreparedOsHandleSet& operator=(PreparedOsHandleSet&&) noexcept;

  [[nodiscard]] PreparedHandleState state() const noexcept;
  [[nodiscard]] const LogicalBindingCandidate& logical_binding() const noexcept;
  [[nodiscard]] const std::array<HANDLE, 10>& child_handles() const noexcept;
  [[nodiscard]] const STARTUPINFOEXW& startup_info() const noexcept;
  [[nodiscard]] PreparedHandleClaims claims() const noexcept;

 private:
  explicit PreparedOsHandleSet(
      std::unique_ptr<PreparedHandlesImplementation> implementation) noexcept;
  std::unique_ptr<PreparedHandlesImplementation> implementation_;
  friend struct PreparedHandlesImplementation;
  friend class detail::PreparedHandleObservationBridge;
};

struct PrepareHandleFailure final {
  PrepareHandleError error = PrepareHandleError::logical_contract_invalid;
  std::size_t index = 0;
  DWORD win32_error = ERROR_SUCCESS;
};

using PrepareHandleResult =
    std::variant<PreparedOsHandleSet, PrepareHandleFailure>;

[[nodiscard]] PrepareHandleResult prepare_os_handles(
    ContractInput metadata, TransferredHandleSet&& originals) noexcept;

#if defined(VAST_REPLAY_BROKER_PREPARED_HANDLES_TESTING)
enum class PreparedHandlesTestFailurePoint {
  none,
  duplicate,
  attribute_initialize,
  attribute_update,
};
void set_prepared_handles_test_failure(
    PreparedHandlesTestFailurePoint point, std::size_t ordinal) noexcept;
#endif

}  // namespace vast::replay_broker::v4
