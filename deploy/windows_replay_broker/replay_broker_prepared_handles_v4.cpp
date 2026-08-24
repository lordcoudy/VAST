#include "replay_broker_prepared_handles_v4.hpp"
#include "replay_broker_prepared_handles_observation_bridge_v4.hpp"

#include <winternl.h>

#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <memory>
#include <new>
#include <string>
#include <utility>

namespace vast::replay_broker::v4 {
namespace {

constexpr std::size_t kArtifactCount = 6;
constexpr ACCESS_MASK kDiskRequired = FILE_READ_DATA | FILE_READ_ATTRIBUTES;
constexpr ACCESS_MASK kDiskAllowed = FILE_READ_DATA | FILE_READ_ATTRIBUTES |
    SYNCHRONIZE;
// CreatePipe read endpoints additionally carry FILE_WRITE_ATTRIBUTES; data-flow
// direction is proven only by FILE_READ_DATA present / FILE_WRITE_DATA absent.
constexpr ACCESS_MASK kPipeReadAllowed = FILE_GENERIC_READ | FILE_WRITE_ATTRIBUTES;
constexpr ACCESS_MASK kPipeWriteAllowed = FILE_GENERIC_WRITE | FILE_READ_ATTRIBUTES;
constexpr ACCESS_MASK kDiskDangerousAccess = DELETE | WRITE_DAC | WRITE_OWNER |
    FILE_WRITE_DATA | FILE_APPEND_DATA | FILE_WRITE_EA | FILE_WRITE_ATTRIBUTES |
    GENERIC_WRITE | GENERIC_ALL | MAXIMUM_ALLOWED;

struct PublicObjectBasicInformation final {
  ULONG Attributes;
  ACCESS_MASK GrantedAccess;
  ULONG HandleCount;
  ULONG PointerCount;
  ULONG PagedPoolCharge;
  ULONG NonPagedPoolCharge;
  ULONG Reserved[3];
  ULONG NameInfoSize;
  ULONG TypeInfoSize;
  ULONG SecurityDescriptorSize;
  LARGE_INTEGER CreationTime;
};

static_assert(sizeof(PublicObjectBasicInformation) == 56,
              "unexpected PUBLIC_OBJECT_BASIC_INFORMATION size");
static_assert(offsetof(PublicObjectBasicInformation, GrantedAccess) == 4,
              "unexpected GrantedAccess offset");

using NtQueryObjectFunction = NTSTATUS(NTAPI*)(
    HANDLE, OBJECT_INFORMATION_CLASS, PVOID, ULONG, PULONG);
using CompareObjectHandlesFunction = BOOL(WINAPI*)(HANDLE, HANDLE);

struct FileIdentity final {
  ULONGLONG volume = 0;
  FILE_ID_128 id{};
};

struct EndpointSnapshot final {
  DWORD type = FILE_TYPE_UNKNOWN;
  DWORD flags = 0;
  DWORD pipe_flags = 0;
  ACCESS_MASK access = 0;
  FILE_STANDARD_INFO standard{};
  FILE_ATTRIBUTE_TAG_INFO tags{};
  FileIdentity identity{};
};

bool same_identity(const FileIdentity& left, const FileIdentity& right) noexcept {
  return left.volume == right.volume &&
      std::memcmp(left.id.Identifier, right.id.Identifier,
                  sizeof(left.id.Identifier)) == 0;
}

bool same_snapshot(const EndpointSnapshot& left,
                   const EndpointSnapshot& right) noexcept {
  return left.type == right.type && left.flags == right.flags &&
      left.pipe_flags == right.pipe_flags && left.access == right.access &&
      left.standard.EndOfFile.QuadPart == right.standard.EndOfFile.QuadPart &&
      left.standard.NumberOfLinks == right.standard.NumberOfLinks &&
      left.standard.DeletePending == right.standard.DeletePending &&
      left.standard.Directory == right.standard.Directory &&
      left.tags.FileAttributes == right.tags.FileAttributes &&
      left.tags.ReparseTag == right.tags.ReparseTag &&
      same_identity(left.identity, right.identity);
}

bool same_endpoint_object(const EndpointSnapshot& left,
                          const EndpointSnapshot& right) noexcept {
  EndpointSnapshot normalized_left = left;
  EndpointSnapshot normalized_right = right;
  normalized_left.flags = 0;
  normalized_right.flags = 0;
  return same_snapshot(normalized_left, normalized_right);
}

bool valid_raw_handle(HANDLE value) noexcept {
  return value != nullptr && value != INVALID_HANDLE_VALUE &&
      value != reinterpret_cast<HANDLE>(static_cast<std::intptr_t>(-2)) &&
      value != reinterpret_cast<HANDLE>(static_cast<std::intptr_t>(-3)) &&
      value != reinterpret_cast<HANDLE>(static_cast<std::intptr_t>(-4));
}

void close_all(std::array<HANDLE, 10>& values) noexcept {
  for (HANDLE& value : values) {
    if (valid_raw_handle(value)) CloseHandle(value);
    value = nullptr;
  }
}

NtQueryObjectFunction nt_query_object() noexcept {
  static const auto function = reinterpret_cast<NtQueryObjectFunction>(
      GetProcAddress(GetModuleHandleW(L"ntdll.dll"), "NtQueryObject"));
  return function;
}

CompareObjectHandlesFunction compare_object_handles() noexcept {
  static const auto function = []() noexcept {
    const HMODULE kernel_base = GetModuleHandleW(L"kernelbase.dll");
    if (kernel_base != nullptr) {
      const auto candidate = reinterpret_cast<CompareObjectHandlesFunction>(
          GetProcAddress(kernel_base, "CompareObjectHandles"));
      if (candidate != nullptr) return candidate;
    }
    return reinterpret_cast<CompareObjectHandlesFunction>(
        GetProcAddress(GetModuleHandleW(L"kernel32.dll"),
                       "CompareObjectHandles"));
  }();
  return function;
}

bool granted_access(HANDLE handle, ACCESS_MASK& access) noexcept {
  const auto query = nt_query_object();
  if (query == nullptr) return false;
  PublicObjectBasicInformation information{};
  ULONG return_length = 0;
  const NTSTATUS status = query(handle, ObjectBasicInformation, &information,
      static_cast<ULONG>(sizeof(information)), &return_length);
  if (status < 0 || return_length != sizeof(PublicObjectBasicInformation)) {
    return false;
  }
  access = information.GrantedAccess;
  return true;
}

PrepareHandleFailure failure(PrepareHandleError error, std::size_t index,
                             DWORD code = ERROR_SUCCESS) noexcept {
  return {error, index, code};
}

#if defined(VAST_REPLAY_BROKER_PREPARED_HANDLES_TESTING)
PreparedHandlesTestFailurePoint g_failure_point =
    PreparedHandlesTestFailurePoint::none;
std::size_t g_failure_ordinal = 0;
bool should_fail(PreparedHandlesTestFailurePoint point, std::size_t ordinal) {
  return g_failure_point == point && g_failure_ordinal == ordinal;
}
#else
bool should_fail(int, std::size_t) { return false; }
#endif

bool snapshot_disk(HANDLE handle, DWORD expected_flags,
                   const ArtifactIdentity& metadata, EndpointSnapshot& snapshot,
                   PrepareHandleFailure& out, std::size_t index) noexcept {
  if (!GetHandleInformation(handle, &snapshot.flags) ||
      snapshot.flags != expected_flags) {
    out = failure(PrepareHandleError::original_handle_revalidation_failed, index,
                  ERROR_INVALID_HANDLE);
    return false;
  }
  if (!granted_access(handle, snapshot.access) ||
      (snapshot.access & kDiskRequired) != kDiskRequired ||
      (snapshot.access & kDiskDangerousAccess) != 0 ||
      (snapshot.access & ~kDiskAllowed) != 0) {
    out = failure(PrepareHandleError::disk_access_invalid, index,
                  ERROR_INVALID_ACCESS);
    return false;
  }
  snapshot.type = GetFileType(handle);
  if (snapshot.type != FILE_TYPE_DISK) {
    out = failure(PrepareHandleError::disk_endpoint_invalid, index);
    return false;
  }
  FILE_ID_INFO id{};
  if (!GetFileInformationByHandleEx(handle, FileStandardInfo, &snapshot.standard,
          sizeof(snapshot.standard)) ||
      !GetFileInformationByHandleEx(handle, FileAttributeTagInfo, &snapshot.tags,
          sizeof(snapshot.tags)) ||
      !GetFileInformationByHandleEx(handle, FileIdInfo, &id, sizeof(id))) {
    out = failure(PrepareHandleError::disk_metadata_invalid, index,
                  GetLastError());
    return false;
  }
  if (snapshot.standard.Directory || snapshot.standard.DeletePending ||
      snapshot.standard.NumberOfLinks != 1 ||
      (snapshot.tags.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0 ||
      snapshot.standard.EndOfFile.QuadPart <= 0) {
    out = failure(PrepareHandleError::disk_metadata_invalid, index);
    return false;
  }
  if (static_cast<std::uint64_t>(snapshot.standard.EndOfFile.QuadPart) !=
      metadata.size_bytes) {
    out = failure(PrepareHandleError::artifact_size_mismatch, index);
    return false;
  }
  snapshot.identity.volume = id.VolumeSerialNumber;
  snapshot.identity.id = id.FileId;
  return true;
}

bool snapshot_pipe(HANDLE handle, DWORD expected_flags, bool require_write,
                   EndpointSnapshot& snapshot, PrepareHandleFailure& out,
                   std::size_t index) noexcept {
  if (!GetHandleInformation(handle, &snapshot.flags) ||
      snapshot.flags != expected_flags) {
    out = failure(PrepareHandleError::original_handle_revalidation_failed, index,
                  ERROR_INVALID_HANDLE);
    return false;
  }
  snapshot.type = GetFileType(handle);
  if (snapshot.type != FILE_TYPE_PIPE) {
    out = failure(PrepareHandleError::pipe_type_invalid, index);
    return false;
  }
  if (!GetNamedPipeInfo(handle, &snapshot.pipe_flags, nullptr, nullptr, nullptr)) {
    out = failure(PrepareHandleError::pipe_type_invalid, index, GetLastError());
    return false;
  }
  if ((snapshot.pipe_flags & PIPE_TYPE_MESSAGE) != 0) {
    out = failure(PrepareHandleError::pipe_type_invalid, index,
                  ERROR_INVALID_DATA);
    return false;
  }
  const ACCESS_MASK required = require_write ? FILE_WRITE_DATA : FILE_READ_DATA;
  const ACCESS_MASK opposite = require_write ? FILE_READ_DATA : FILE_WRITE_DATA;
  const ACCESS_MASK allowed = require_write ? kPipeWriteAllowed : kPipeReadAllowed;
  if (!granted_access(handle, snapshot.access) ||
      (snapshot.access & required) == 0 ||
      (snapshot.access & opposite) != 0 || snapshot.access != allowed) {
    out = failure(PrepareHandleError::pipe_direction_invalid, index,
                  ERROR_INVALID_ACCESS);
    return false;
  }
  return true;
}

bool snapshot_endpoints(const std::array<HANDLE, 10>& handles,
                        DWORD expected_flags, const ContractInput& metadata,
                        std::array<EndpointSnapshot, 10>& snapshots,
                        PrepareHandleFailure& out) noexcept {
  for (std::size_t index = 0; index < kArtifactCount; ++index) {
    if (!snapshot_disk(handles[index], expected_flags,
                       metadata.artifacts[index], snapshots[index], out, index))
      return false;
    for (std::size_t prior = 0; prior < index; ++prior) {
      if (same_identity(snapshots[index].identity,
                        snapshots[prior].identity)) {
        out = failure(PrepareHandleError::duplicate_disk_identity, index);
        return false;
      }
    }
  }
  for (std::size_t index = kArtifactCount; index < handles.size(); ++index) {
    if (!snapshot_pipe(handles[index], expected_flags, index >= 8,
                       snapshots[index], out, index)) return false;
  }
  return true;
}

bool compare_generations(
    const std::array<EndpointSnapshot, 10>& expected,
    const std::array<EndpointSnapshot, 10>& actual, bool ignore_flags,
    PrepareHandleError error, PrepareHandleFailure& out) noexcept {
  for (std::size_t index = 0; index < expected.size(); ++index) {
    const bool equal = ignore_flags
        ? same_endpoint_object(expected[index], actual[index])
        : same_snapshot(expected[index], actual[index]);
    if (!equal) {
      out = failure(error, index, ERROR_INVALID_DATA);
      return false;
    }
  }
  return true;
}

bool compare_kernel_objects(const std::array<HANDLE, 10>& originals,
                            const std::array<HANDLE, 10>& duplicates,
                            PrepareHandleFailure& out) noexcept {
  const auto compare = compare_object_handles();
  if (compare == nullptr) {
    out = failure(PrepareHandleError::duplicate_revalidation_failed, 0,
                  ERROR_PROC_NOT_FOUND);
    return false;
  }
  for (std::size_t index = 0; index < originals.size(); ++index) {
    if (!compare(originals[index], duplicates[index])) {
      out = failure(PrepareHandleError::duplicate_revalidation_failed, index,
                    ERROR_INVALID_DATA);
      return false;
    }
  }
  return true;
}

bool pairwise_distinct_kernel_objects(
    const std::array<HANDLE, 10>& handles,
    PrepareHandleError unavailable_error,
    PrepareHandleFailure& out) noexcept {
  const auto compare = compare_object_handles();
  if (compare == nullptr) {
    out = failure(unavailable_error, 0, ERROR_PROC_NOT_FOUND);
    return false;
  }
  for (std::size_t index = 0; index < handles.size(); ++index) {
    for (std::size_t prior = 0; prior < index; ++prior) {
      if (compare(handles[index], handles[prior])) {
        out = failure(PrepareHandleError::duplicate_endpoint_object, index,
                      ERROR_ALREADY_EXISTS);
        return false;
      }
    }
  }
  return true;
}

}  // namespace

struct PreparedHandlesImplementation final {
  std::array<detail::FrozenArtifactObservationMetadata, 6>
      frozen_artifacts{};
  LogicalBindingCandidate binding;
  std::array<HANDLE, 10> children{};
  std::unique_ptr<std::byte[]> attribute_storage;
  STARTUPINFOEXW startup{};
  static std::array<HANDLE, 10> release(
      TransferredHandleSet& value) noexcept {
    return value.release_all();
  }
  static PreparedOsHandleSet make(
      std::unique_ptr<PreparedHandlesImplementation> implementation) noexcept {
    return PreparedOsHandleSet(std::move(implementation));
  }
  ~PreparedHandlesImplementation() {
    if (startup.lpAttributeList != nullptr) {
      DeleteProcThreadAttributeList(startup.lpAttributeList);
      startup.lpAttributeList = nullptr;
    }
    close_all(children);
  }
};

TransferredHandleSet::TransferredHandleSet(
    std::array<HANDLE, 10> handles) noexcept : handles_(handles) {}

TransferredHandleSet::~TransferredHandleSet() { close_all(handles_); }

TransferredHandleSet::TransferredHandleSet(TransferredHandleSet&& other) noexcept
    : handles_(other.release_all()) {}

TransferredHandleSet& TransferredHandleSet::operator=(
    TransferredHandleSet&& other) noexcept {
  if (this != &other) {
    close_all(handles_);
    handles_ = other.release_all();
  }
  return *this;
}

std::array<HANDLE, 10> TransferredHandleSet::release_all() noexcept {
  auto values = handles_;
  handles_.fill(nullptr);
  return values;
}

TakeExclusiveResult TransferredHandleSet::take_exclusive(
    const std::array<HANDLE, 10>& raw_handles) noexcept {
  for (std::size_t index = 0; index < raw_handles.size(); ++index) {
    if (!valid_raw_handle(raw_handles[index])) {
      return {nullptr, {TransferHandleError::invalid_handle, index}};
    }
    for (std::size_t prior = 0; prior < index; ++prior) {
      if (raw_handles[index] == raw_handles[prior]) {
        return {nullptr, {TransferHandleError::duplicate_handle_value, index}};
      }
    }
    DWORD flags = 0;
    if (!GetHandleInformation(raw_handles[index], &flags)) {
      return {nullptr, {TransferHandleError::handle_flags_query_failed, index}};
    }
    if (flags != 0) {
      return {nullptr, {TransferHandleError::handle_flags_not_zero, index}};
    }
  }
  auto value = std::unique_ptr<TransferredHandleSet>(
      new (std::nothrow) TransferredHandleSet(raw_handles));
  if (!value) {
    return {nullptr, {TransferHandleError::allocation_failed, 0}};
  }
  return {std::move(value), {TransferHandleError::none, 0}};
}

PreparedOsHandleSet::PreparedOsHandleSet(
    std::unique_ptr<PreparedHandlesImplementation> implementation) noexcept
    : implementation_(std::move(implementation)) {}
PreparedOsHandleSet::~PreparedOsHandleSet() = default;
PreparedOsHandleSet::PreparedOsHandleSet(PreparedOsHandleSet&&) noexcept = default;
PreparedOsHandleSet& PreparedOsHandleSet::operator=(PreparedOsHandleSet&&) noexcept = default;

PreparedHandleState PreparedOsHandleSet::state() const noexcept {
  return PreparedHandleState::prepared_os_handles_validated;
}
const LogicalBindingCandidate& PreparedOsHandleSet::logical_binding() const noexcept {
  return implementation_->binding;
}
const std::array<HANDLE, 10>& PreparedOsHandleSet::child_handles() const noexcept {
  return implementation_->children;
}
const STARTUPINFOEXW& PreparedOsHandleSet::startup_info() const noexcept {
  return implementation_->startup;
}
PreparedHandleClaims PreparedOsHandleSet::claims() const noexcept { return {}; }

std::optional<detail::ArtifactObservationSeed>
detail::PreparedHandleObservationBridge::snapshot(
    const PreparedOsHandleSet& prepared) noexcept {
  try {
    if (prepared.implementation_ == nullptr) return std::nullopt;
    detail::ArtifactObservationSeed seed{};
    for (std::size_t index = 0; index < seed.handles.size(); ++index) {
      seed.handles[index] = prepared.implementation_->children[index];
      seed.artifacts[index] =
          prepared.implementation_->frozen_artifacts[index];
    }
    return seed;
  } catch (...) {
    return std::nullopt;
  }
}

PrepareHandleResult prepare_os_handles(
    ContractInput metadata, TransferredHandleSet&& transferred) noexcept {
  try {
  auto originals = PreparedHandlesImplementation::release(transferred);
  struct OriginalsGuard final {
    std::array<HANDLE, 10>& values;
    ~OriginalsGuard() { close_all(values); }
  } originals_guard{originals};

  for (std::size_t index = 0; index < kArtifactCount; ++index) {
    metadata.artifacts[index].token.value = static_cast<std::uint64_t>(
        reinterpret_cast<std::uintptr_t>(originals[index]));
  }
  for (std::size_t index = 0; index < 4; ++index) {
    metadata.channels[index].token.value = static_cast<std::uint64_t>(
        reinterpret_cast<std::uintptr_t>(originals[kArtifactCount + index]));
  }
  if (!logically_bind(metadata).has_value()) {
    return failure(PrepareHandleError::logical_contract_invalid, 0);
  }
  PrepareHandleFailure problem{};
  std::array<EndpointSnapshot, 10> original_initial{};
  if (!snapshot_endpoints(originals, 0, metadata, original_initial, problem) ||
      !pairwise_distinct_kernel_objects(originals,
          PrepareHandleError::original_handle_revalidation_failed, problem)) {
    return problem;
  }

  auto implementation = std::unique_ptr<PreparedHandlesImplementation>(
      new (std::nothrow) PreparedHandlesImplementation{});
  if (!implementation) {
    return failure(PrepareHandleError::attribute_list_failed, 0,
                   ERROR_NOT_ENOUGH_MEMORY);
  }
  for (std::size_t index = 0; index < kArtifactCount; ++index) {
    implementation->frozen_artifacts[index] = {
        metadata.artifacts[index].role,
        metadata.artifacts[index].file_sha256,
        metadata.artifacts[index].size_bytes};
  }
  for (std::size_t index = 0; index < implementation->children.size(); ++index) {
#if defined(VAST_REPLAY_BROKER_PREPARED_HANDLES_TESTING)
    if (should_fail(PreparedHandlesTestFailurePoint::duplicate, index)) {
      return failure(PrepareHandleError::duplicate_failed, index,
                     ERROR_GEN_FAILURE);
    }
#endif
    HANDLE duplicate = nullptr;
    if (!DuplicateHandle(GetCurrentProcess(), originals[index],
                         GetCurrentProcess(), &duplicate, 0, TRUE,
                         DUPLICATE_SAME_ACCESS)) {
      return failure(PrepareHandleError::duplicate_failed, index,
                     GetLastError());
    }
    implementation->children[index] = duplicate;
  }
  // Revalidate both generations only after all ten duplications are complete.
  std::array<EndpointSnapshot, 10> original_after_duplicate{};
  if (!snapshot_endpoints(originals, 0, metadata, original_after_duplicate,
                          problem) ||
      !compare_generations(original_initial, original_after_duplicate, false,
          PrepareHandleError::original_handle_revalidation_failed, problem)) {
    if (problem.error != PrepareHandleError::original_handle_revalidation_failed)
      problem.error = PrepareHandleError::original_handle_revalidation_failed;
    return problem;
  }
  if (!pairwise_distinct_kernel_objects(originals,
          PrepareHandleError::original_handle_revalidation_failed, problem)) {
    return problem;
  }
  std::array<EndpointSnapshot, 10> duplicate_after_duplicate{};
  if (!snapshot_endpoints(implementation->children, HANDLE_FLAG_INHERIT,
                          metadata, duplicate_after_duplicate, problem) ||
      !compare_generations(original_initial, duplicate_after_duplicate, true,
          PrepareHandleError::duplicate_revalidation_failed, problem) ||
      !compare_kernel_objects(originals, implementation->children, problem)) {
    if (problem.error != PrepareHandleError::duplicate_revalidation_failed)
      problem.error = PrepareHandleError::duplicate_revalidation_failed;
    return problem;
  }
  if (!pairwise_distinct_kernel_objects(implementation->children,
          PrepareHandleError::duplicate_revalidation_failed, problem)) {
    return problem;
  }
  ContractInput child_metadata = metadata;
  for (std::size_t index = 0; index < kArtifactCount; ++index) {
    child_metadata.artifacts[index].token.value = static_cast<std::uint64_t>(
        reinterpret_cast<std::uintptr_t>(implementation->children[index]));
  }
  for (std::size_t index = 0; index < 4; ++index) {
    child_metadata.channels[index].token.value = static_cast<std::uint64_t>(
        reinterpret_cast<std::uintptr_t>(
            implementation->children[kArtifactCount + index]));
  }
  auto rebound = logically_bind(child_metadata);
  if (!rebound) return failure(PrepareHandleError::logical_contract_invalid, 0);
  implementation->binding = std::move(*rebound);

  SIZE_T storage_size = 0;
  InitializeProcThreadAttributeList(nullptr, 1, 0, &storage_size);
  if (storage_size == 0) {
    return failure(PrepareHandleError::attribute_list_failed, 0, GetLastError());
  }
  implementation->attribute_storage.reset(
      new (std::nothrow) std::byte[storage_size]);
  if (!implementation->attribute_storage) {
    return failure(PrepareHandleError::attribute_list_failed, 0,
                   ERROR_NOT_ENOUGH_MEMORY);
  }
  implementation->startup = {};
  implementation->startup.StartupInfo.cb = sizeof(STARTUPINFOEXW);
  implementation->startup.lpAttributeList =
      reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(
          implementation->attribute_storage.get());
#if defined(VAST_REPLAY_BROKER_PREPARED_HANDLES_TESTING)
  if (should_fail(PreparedHandlesTestFailurePoint::attribute_initialize, 0)) {
    implementation->startup.lpAttributeList = nullptr;
    return failure(PrepareHandleError::attribute_list_failed, 0,
                   ERROR_GEN_FAILURE);
  }
#endif
  if (!InitializeProcThreadAttributeList(
          implementation->startup.lpAttributeList, 1, 0, &storage_size)) {
    implementation->startup.lpAttributeList = nullptr;
    return failure(PrepareHandleError::attribute_list_failed, 0,
                   GetLastError());
  }
#if defined(VAST_REPLAY_BROKER_PREPARED_HANDLES_TESTING)
  if (should_fail(PreparedHandlesTestFailurePoint::attribute_update, 0)) {
    return failure(PrepareHandleError::attribute_list_failed, 0,
                   ERROR_GEN_FAILURE);
  }
#endif
  if (!UpdateProcThreadAttribute(implementation->startup.lpAttributeList, 0,
          PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
          implementation->children.data(),
          implementation->children.size() * sizeof(HANDLE), nullptr, nullptr)) {
    return failure(PrepareHandleError::attribute_list_failed, 0,
                   GetLastError());
  }
  implementation->startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
  implementation->startup.StartupInfo.hStdInput = implementation->children[7];
  implementation->startup.StartupInfo.hStdOutput = implementation->children[8];
  implementation->startup.StartupInfo.hStdError = implementation->children[9];
  std::array<EndpointSnapshot, 10> original_final{};
  std::array<EndpointSnapshot, 10> duplicate_final{};
  if (!snapshot_endpoints(originals, 0, metadata, original_final, problem) ||
      !compare_generations(original_initial, original_final, false,
          PrepareHandleError::original_handle_revalidation_failed, problem)) {
    if (problem.error != PrepareHandleError::original_handle_revalidation_failed)
      problem.error = PrepareHandleError::original_handle_revalidation_failed;
    return problem;
  }
  if (!pairwise_distinct_kernel_objects(originals,
          PrepareHandleError::original_handle_revalidation_failed, problem)) {
    return problem;
  }
  if (!snapshot_endpoints(implementation->children, HANDLE_FLAG_INHERIT,
                          metadata, duplicate_final, problem) ||
      !compare_generations(duplicate_after_duplicate, duplicate_final, false,
          PrepareHandleError::duplicate_revalidation_failed, problem) ||
      !compare_generations(original_final, duplicate_final, true,
          PrepareHandleError::duplicate_revalidation_failed, problem) ||
      !compare_kernel_objects(originals, implementation->children, problem)) {
    if (problem.error != PrepareHandleError::duplicate_revalidation_failed)
      problem.error = PrepareHandleError::duplicate_revalidation_failed;
    return problem;
  }
  if (!pairwise_distinct_kernel_objects(implementation->children,
          PrepareHandleError::duplicate_revalidation_failed, problem)) {
    return problem;
  }
  return PreparedHandlesImplementation::make(std::move(implementation));
  } catch (...) {
    return failure(PrepareHandleError::allocation_failed, 0,
                   ERROR_NOT_ENOUGH_MEMORY);
  }
}

#if defined(VAST_REPLAY_BROKER_PREPARED_HANDLES_TESTING)
void set_prepared_handles_test_failure(
    PreparedHandlesTestFailurePoint point, std::size_t ordinal) noexcept {
  g_failure_point = point;
  g_failure_ordinal = ordinal;
}
#endif

}  // namespace vast::replay_broker::v4
