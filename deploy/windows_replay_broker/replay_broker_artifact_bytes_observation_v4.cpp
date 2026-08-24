#include "replay_broker_artifact_bytes_observation_v4.hpp"
#include "replay_broker_prepared_handles_observation_bridge_v4.hpp"

#include <bcrypt.h>

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>
#include <memory>
#include <new>
#include <utility>

namespace vast::replay_broker::v4 {
namespace {

constexpr std::size_t kArtifactCount = 6;
constexpr DWORD kReadChunkBytes = 1U << 20U;
constexpr ULONG kSha256Bytes = 32;
constexpr ULONG kMaxHashObjectBytes = 64U * 1024U;
constexpr LONG kInjectedBcryptFailure = static_cast<LONG>(0xC0000001UL);

constexpr std::array<ArtifactRole, kArtifactCount> kArtifactRoles = {{
    ArtifactRole::runner_entrypoint_read,
    ArtifactRole::runner_authority_read,
    ArtifactRole::validator_authority_read,
    ArtifactRole::validation_request_read,
    ArtifactRole::raw_evidence_read,
    ArtifactRole::runtime_closure_bundle_read,
}};

#if defined(VAST_REPLAY_BROKER_ARTIFACT_BYTES_OBSERVATION_TESTING)
ArtifactBytesObservationTestFailurePoint g_failure_point =
    ArtifactBytesObservationTestFailurePoint::none;
std::size_t g_failure_ordinal = 0;
std::size_t g_reopened_handles = 0;
std::size_t g_algorithm_providers = 0;
std::size_t g_hash_handles = 0;

bool should_fail(ArtifactBytesObservationTestFailurePoint point,
                 std::size_t ordinal) noexcept {
  return g_failure_point == point && g_failure_ordinal == ordinal;
}
void reopened_acquired() noexcept { ++g_reopened_handles; }
void reopened_released() noexcept { --g_reopened_handles; }
void algorithm_acquired() noexcept { ++g_algorithm_providers; }
void algorithm_released() noexcept { --g_algorithm_providers; }
void hash_acquired() noexcept { ++g_hash_handles; }
void hash_released() noexcept { --g_hash_handles; }
#else
void reopened_acquired() noexcept {}
void reopened_released() noexcept {}
void algorithm_acquired() noexcept {}
void algorithm_released() noexcept {}
void hash_acquired() noexcept {}
void hash_released() noexcept {}
#endif

bool valid_handle(HANDLE value) noexcept {
  return value != nullptr && value != INVALID_HANDLE_VALUE;
}

class ScopedHandle final {
 public:
  ScopedHandle() = default;
  ~ScopedHandle() { reset(); }
  ScopedHandle(const ScopedHandle&) = delete;
  ScopedHandle& operator=(const ScopedHandle&) = delete;
  ScopedHandle(ScopedHandle&& other) noexcept : value_(other.release()) {}
  ScopedHandle& operator=(ScopedHandle&& other) noexcept {
    if (this != &other) reset(other.release());
    return *this;
  }
  HANDLE get() const noexcept { return value_; }
  void reset(HANDLE value = nullptr) noexcept {
    if (valid_handle(value_)) {
      CloseHandle(value_);
      reopened_released();
    }
    value_ = value;
    if (valid_handle(value_)) reopened_acquired();
  }
  HANDLE release() noexcept {
    HANDLE value = value_;
    if (valid_handle(value_)) reopened_released();
    value_ = nullptr;
    return value;
  }

 private:
  HANDLE value_ = nullptr;
};

class ScopedAlgorithm final {
 public:
  ScopedAlgorithm() = default;
  ~ScopedAlgorithm() { reset(); }
  ScopedAlgorithm(const ScopedAlgorithm&) = delete;
  ScopedAlgorithm& operator=(const ScopedAlgorithm&) = delete;
  BCRYPT_ALG_HANDLE get() const noexcept { return value_; }
  BCRYPT_ALG_HANDLE* put() noexcept {
    reset();
    return &value_;
  }
  void mark_acquired() noexcept {
    if (value_ != nullptr && !counted_) {
      counted_ = true;
      algorithm_acquired();
    }
  }
  void reset() noexcept {
    if (value_ != nullptr) BCryptCloseAlgorithmProvider(value_, 0);
    value_ = nullptr;
    if (counted_) algorithm_released();
    counted_ = false;
  }

 private:
  BCRYPT_ALG_HANDLE value_ = nullptr;
  bool counted_ = false;
};

class ScopedHash final {
 public:
  ScopedHash() = default;
  ~ScopedHash() { reset(); }
  ScopedHash(const ScopedHash&) = delete;
  ScopedHash& operator=(const ScopedHash&) = delete;
  BCRYPT_HASH_HANDLE get() const noexcept { return value_; }
  BCRYPT_HASH_HANDLE* put() noexcept {
    reset();
    return &value_;
  }
  void mark_acquired() noexcept {
    if (value_ != nullptr && !counted_) {
      counted_ = true;
      hash_acquired();
    }
  }
  void reset() noexcept {
    if (value_ != nullptr) BCryptDestroyHash(value_);
    value_ = nullptr;
    if (counted_) hash_released();
    counted_ = false;
  }

 private:
  BCRYPT_HASH_HANDLE value_ = nullptr;
  bool counted_ = false;
};

struct FileIdentity final {
  ULONGLONG volume = 0;
  FILE_ID_128 id{};
};

struct FileSnapshot final {
  DWORD handle_flags = 0;
  DWORD type = FILE_TYPE_UNKNOWN;
  FILE_STANDARD_INFO standard{};
  FILE_ATTRIBUTE_TAG_INFO tags{};
  FILE_BASIC_INFO basic{};
  FileIdentity identity{};
};

bool same_identity(const FileIdentity& left, const FileIdentity& right) noexcept {
  return left.volume == right.volume &&
      std::memcmp(left.id.Identifier, right.id.Identifier,
                  sizeof(left.id.Identifier)) == 0;
}

bool same_metadata(const FileSnapshot& left,
                   const FileSnapshot& right) noexcept {
  return left.type == right.type &&
      left.standard.AllocationSize.QuadPart ==
          right.standard.AllocationSize.QuadPart &&
      left.standard.EndOfFile.QuadPart == right.standard.EndOfFile.QuadPart &&
      left.standard.NumberOfLinks == right.standard.NumberOfLinks &&
      left.standard.DeletePending == right.standard.DeletePending &&
      left.standard.Directory == right.standard.Directory &&
      left.tags.FileAttributes == right.tags.FileAttributes &&
      left.tags.ReparseTag == right.tags.ReparseTag &&
      left.basic.CreationTime.QuadPart == right.basic.CreationTime.QuadPart &&
      left.basic.LastWriteTime.QuadPart == right.basic.LastWriteTime.QuadPart &&
      left.basic.ChangeTime.QuadPart == right.basic.ChangeTime.QuadPart &&
      left.basic.FileAttributes == right.basic.FileAttributes &&
      same_identity(left.identity, right.identity);
}

ArtifactBytesObservationFailure failure(
    ArtifactBytesObservationError error,
    ArtifactBytesObservationStage stage,
    std::size_t index,
    std::uint64_t offset = 0,
    DWORD win32_error = ERROR_SUCCESS,
    LONG bcrypt_status = 0) noexcept {
  return {error, stage, index, offset, win32_error, bcrypt_status};
}

bool lowercase_hex_digest(
    const std::string& value,
    std::array<std::uint8_t, kSha256Bytes>& output) noexcept {
  if (value.size() != kSha256Bytes * 2U) return false;
  auto digit = [](char character, std::uint8_t& result) noexcept {
    if (character >= '0' && character <= '9') {
      result = static_cast<std::uint8_t>(character - '0');
      return true;
    }
    if (character >= 'a' && character <= 'f') {
      result = static_cast<std::uint8_t>(10 + character - 'a');
      return true;
    }
    return false;
  };
  for (std::size_t index = 0; index < output.size(); ++index) {
    std::uint8_t high = 0;
    std::uint8_t low = 0;
    if (!digit(value[index * 2U], high) ||
        !digit(value[index * 2U + 1U], low)) return false;
    output[index] = static_cast<std::uint8_t>((high << 4U) | low);
  }
  return true;
}

bool snapshot_file(HANDLE handle,
                   DWORD expected_flags,
                   std::uint64_t expected_size,
                   bool reopened,
                   ArtifactBytesObservationStage stage,
                   std::size_t index,
                   FileSnapshot& snapshot,
                   ArtifactBytesObservationFailure& out) noexcept {
  if (!GetHandleInformation(handle, &snapshot.handle_flags)) {
    out = failure(
        reopened
            ? ArtifactBytesObservationError::reopened_handle_flags_query_failed
            : ArtifactBytesObservationError::metadata_changed,
        stage, index, 0, GetLastError());
    return false;
  }
  if (snapshot.handle_flags != expected_flags) {
    out = failure(
        reopened
            ? ArtifactBytesObservationError::reopened_handle_flags_invalid
            : ArtifactBytesObservationError::metadata_changed,
        stage, index, 0, ERROR_INVALID_HANDLE);
    return false;
  }
  snapshot.type = GetFileType(handle);
  if (snapshot.type != FILE_TYPE_DISK) {
    out = failure(ArtifactBytesObservationError::disk_endpoint_invalid,
                  stage, index, 0, GetLastError());
    return false;
  }
  FILE_ID_INFO identity{};
  if (!GetFileInformationByHandleEx(handle, FileStandardInfo,
          &snapshot.standard, sizeof(snapshot.standard)) ||
      !GetFileInformationByHandleEx(handle, FileAttributeTagInfo,
          &snapshot.tags, sizeof(snapshot.tags)) ||
      !GetFileInformationByHandleEx(handle, FileBasicInfo,
          &snapshot.basic, sizeof(snapshot.basic)) ||
      !GetFileInformationByHandleEx(handle, FileIdInfo,
          &identity, sizeof(identity))) {
    out = failure(ArtifactBytesObservationError::metadata_query_failed,
                  stage, index, 0, GetLastError());
    return false;
  }
  if (snapshot.standard.Directory || snapshot.standard.DeletePending ||
      snapshot.standard.NumberOfLinks != 1 ||
      snapshot.standard.EndOfFile.QuadPart <= 0 ||
      (snapshot.tags.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0) {
    out = failure(ArtifactBytesObservationError::metadata_shape_invalid,
                  stage, index, 0, ERROR_INVALID_DATA);
    return false;
  }
  if (static_cast<std::uint64_t>(snapshot.standard.EndOfFile.QuadPart) !=
      expected_size) {
    out = failure(ArtifactBytesObservationError::metadata_size_mismatch,
                  stage, index, 0, ERROR_FILE_INVALID);
    return false;
  }
  snapshot.identity.volume = identity.VolumeSerialNumber;
  snapshot.identity.id = identity.FileId;
  return true;
}

bool validate_frozen_metadata(
    const detail::ArtifactObservationSeed& seed,
    std::array<std::array<std::uint8_t, kSha256Bytes>, kArtifactCount>&
        expected,
    ArtifactBytesObservationFailure& out) noexcept {
  std::uint64_t total = 0;
  for (std::size_t index = 0; index < kArtifactCount; ++index) {
    const auto& artifact = seed.artifacts[index];
    if (artifact.role != kArtifactRoles[index] || artifact.size_bytes == 0 ||
        artifact.size_bytes > kMaxArtifactBytes ||
        !lowercase_hex_digest(artifact.file_sha256, expected[index]) ||
        total > kMaxTotalArtifactBytes - artifact.size_bytes) {
      out = failure(ArtifactBytesObservationError::frozen_metadata_invalid,
                    ArtifactBytesObservationStage::input, index);
      return false;
    }
    total += artifact.size_bytes;
  }
  return true;
}

bool bcrypt_property(ScopedAlgorithm& algorithm,
                     LPCWSTR name,
                     ULONG& value,
                     ArtifactBytesObservationError injected_error,
                     ArtifactBytesObservationFailure& out) noexcept {
  (void)injected_error;
  ULONG bytes = 0;
  const LONG status = BCryptGetProperty(
      algorithm.get(), name, reinterpret_cast<PUCHAR>(&value), sizeof(value),
      &bytes, 0);
  if (status < 0) {
    out = failure(ArtifactBytesObservationError::bcrypt_property_query_failed,
        ArtifactBytesObservationStage::crypto_properties,
        kArtifactObservationGlobalIndex, 0, ERROR_SUCCESS, status);
    return false;
  }
  if (bytes != sizeof(value)) {
    out = failure(ArtifactBytesObservationError::bcrypt_property_invalid,
        ArtifactBytesObservationStage::crypto_properties,
        kArtifactObservationGlobalIndex, 0, ERROR_SUCCESS, status);
    return false;
  }
  return true;
}

}  // namespace

struct ArtifactBytesObservationImplementation final {
  PreparedOsHandleSet prepared;
  std::array<ArtifactByteObservation, kArtifactCount> observations;

  ArtifactBytesObservationImplementation(
      PreparedOsHandleSet&& prepared_value,
      std::array<ArtifactByteObservation, kArtifactCount> observations_value)
      noexcept
      : prepared(std::move(prepared_value)),
        observations(std::move(observations_value)) {}

  static ArtifactBytesObservedPreparedOsHandleSet make(
      std::unique_ptr<ArtifactBytesObservationImplementation>
          implementation) noexcept {
    return ArtifactBytesObservedPreparedOsHandleSet(std::move(implementation));
  }
};

ArtifactBytesObservedPreparedOsHandleSet::
    ArtifactBytesObservedPreparedOsHandleSet(
        std::unique_ptr<ArtifactBytesObservationImplementation>
            implementation) noexcept
    : implementation_(std::move(implementation)) {}
ArtifactBytesObservedPreparedOsHandleSet::~
    ArtifactBytesObservedPreparedOsHandleSet() = default;
ArtifactBytesObservedPreparedOsHandleSet::
    ArtifactBytesObservedPreparedOsHandleSet(
        ArtifactBytesObservedPreparedOsHandleSet&&) noexcept = default;
ArtifactBytesObservedPreparedOsHandleSet&
ArtifactBytesObservedPreparedOsHandleSet::operator=(
    ArtifactBytesObservedPreparedOsHandleSet&&) noexcept = default;

bool ArtifactBytesObservedPreparedOsHandleSet::valid() const noexcept {
  return implementation_ != nullptr;
}

std::optional<ArtifactBytesObservationState>
ArtifactBytesObservedPreparedOsHandleSet::state() const noexcept {
  if (!implementation_) return std::nullopt;
  return ArtifactBytesObservationState::
      prepared_artifact_file_bytes_sha256_point_in_time_validated;
}

const PreparedOsHandleSet*
ArtifactBytesObservedPreparedOsHandleSet::prepared_handles() const noexcept {
  return implementation_ ? &implementation_->prepared : nullptr;
}

const std::array<ArtifactByteObservation, kArtifactCount>*
ArtifactBytesObservedPreparedOsHandleSet::observations() const noexcept {
  return implementation_ ? &implementation_->observations : nullptr;
}

const ArtifactBytesObservationClaims*
ArtifactBytesObservedPreparedOsHandleSet::claims() const noexcept {
  static constexpr ArtifactBytesObservationClaims claims{};
  return implementation_ ? &claims : nullptr;
}

ArtifactBytesObservationResult observe_artifact_bytes(
    PreparedOsHandleSet prepared) noexcept {
  try {
    const auto seed =
        detail::PreparedHandleObservationBridge::snapshot(prepared);
    if (!seed) {
      return failure(ArtifactBytesObservationError::invalid_prepared_state,
          ArtifactBytesObservationStage::input,
          kArtifactObservationGlobalIndex);
    }

    ArtifactBytesObservationFailure problem{};
    std::array<std::array<std::uint8_t, kSha256Bytes>, kArtifactCount>
        expected{};
    if (!validate_frozen_metadata(*seed, expected, problem)) return problem;

    std::array<FileSnapshot, kArtifactCount> original_before{};
    for (std::size_t index = 0; index < kArtifactCount; ++index) {
      if (!snapshot_file(seed->handles[index], HANDLE_FLAG_INHERIT,
              seed->artifacts[index].size_bytes, false,
              ArtifactBytesObservationStage::before_read_metadata,
              index, original_before[index], problem)) return problem;
    }

    std::array<ScopedHandle, kArtifactCount> reopened{};
    std::array<FileSnapshot, kArtifactCount> reopened_before{};
    for (std::size_t index = 0; index < kArtifactCount; ++index) {
#if defined(VAST_REPLAY_BROKER_ARTIFACT_BYTES_OBSERVATION_TESTING)
      if (should_fail(ArtifactBytesObservationTestFailurePoint::reopen,
                      index)) {
        return failure(ArtifactBytesObservationError::reopen_failed,
            ArtifactBytesObservationStage::reopen, index, 0,
            ERROR_GEN_FAILURE);
      }
#endif
      HANDLE value = ReOpenFile(seed->handles[index], FILE_READ_DATA | FILE_READ_ATTRIBUTES | SYNCHRONIZE, FILE_SHARE_READ, FILE_FLAG_SEQUENTIAL_SCAN);
      if (!valid_handle(value)) {
        return failure(ArtifactBytesObservationError::reopen_failed,
            ArtifactBytesObservationStage::reopen, index, 0,
            GetLastError());
      }
      reopened[index].reset(value);
      if (!snapshot_file(reopened[index].get(), 0,
              seed->artifacts[index].size_bytes, true,
              ArtifactBytesObservationStage::before_read_metadata,
              index, reopened_before[index], problem)) return problem;
      if (!same_identity(original_before[index].identity,
                         reopened_before[index].identity)) {
        return failure(ArtifactBytesObservationError::metadata_identity_mismatch,
            ArtifactBytesObservationStage::before_read_metadata, index, 0,
            ERROR_INVALID_DATA);
      }
      if (!same_metadata(original_before[index], reopened_before[index])) {
        return failure(ArtifactBytesObservationError::metadata_changed,
            ArtifactBytesObservationStage::before_read_metadata, index, 0,
            ERROR_INVALID_DATA);
      }
    }

    ScopedAlgorithm algorithm;
#if defined(VAST_REPLAY_BROKER_ARTIFACT_BYTES_OBSERVATION_TESTING)
    if (should_fail(ArtifactBytesObservationTestFailurePoint::bcrypt_open, 0)) {
      return failure(ArtifactBytesObservationError::bcrypt_provider_open_failed,
          ArtifactBytesObservationStage::crypto_provider,
          kArtifactObservationGlobalIndex, 0, ERROR_SUCCESS,
          kInjectedBcryptFailure);
    }
#endif
    LONG status = BCryptOpenAlgorithmProvider(algorithm.put(),
        BCRYPT_SHA256_ALGORITHM, MS_PRIMITIVE_PROVIDER, 0);
    if (status < 0) {
      return failure(ArtifactBytesObservationError::bcrypt_provider_open_failed,
          ArtifactBytesObservationStage::crypto_provider,
          kArtifactObservationGlobalIndex, 0, ERROR_SUCCESS, status);
    }
    algorithm.mark_acquired();

    ULONG object_length = 0;
#if defined(VAST_REPLAY_BROKER_ARTIFACT_BYTES_OBSERVATION_TESTING)
    if (should_fail(
            ArtifactBytesObservationTestFailurePoint::bcrypt_object_length, 0)) {
      return failure(ArtifactBytesObservationError::bcrypt_property_query_failed,
          ArtifactBytesObservationStage::crypto_properties,
          kArtifactObservationGlobalIndex, 0, ERROR_SUCCESS,
          kInjectedBcryptFailure);
    }
#endif
    if (!bcrypt_property(algorithm, BCRYPT_OBJECT_LENGTH, object_length,
                         ArtifactBytesObservationError::bcrypt_property_query_failed,
                         problem)) return problem;
    if (object_length == 0 || object_length > kMaxHashObjectBytes) {
      return failure(ArtifactBytesObservationError::bcrypt_property_invalid,
          ArtifactBytesObservationStage::crypto_properties,
          kArtifactObservationGlobalIndex);
    }

    ULONG hash_length = 0;
#if defined(VAST_REPLAY_BROKER_ARTIFACT_BYTES_OBSERVATION_TESTING)
    if (should_fail(
            ArtifactBytesObservationTestFailurePoint::bcrypt_hash_length, 0)) {
      return failure(ArtifactBytesObservationError::bcrypt_property_query_failed,
          ArtifactBytesObservationStage::crypto_properties,
          kArtifactObservationGlobalIndex, 0, ERROR_SUCCESS,
          kInjectedBcryptFailure);
    }
#endif
    if (!bcrypt_property(algorithm, BCRYPT_HASH_LENGTH, hash_length,
                         ArtifactBytesObservationError::bcrypt_property_query_failed,
                         problem)) return problem;
    if (hash_length != kSha256Bytes) {
      return failure(ArtifactBytesObservationError::bcrypt_property_invalid,
          ArtifactBytesObservationStage::crypto_properties,
          kArtifactObservationGlobalIndex);
    }

    auto object = std::unique_ptr<UCHAR[]>(new (std::nothrow)
        UCHAR[object_length]);
    auto buffer = std::unique_ptr<UCHAR[]>(new (std::nothrow)
        UCHAR[kReadChunkBytes]);
    if (!object || !buffer) {
      return failure(ArtifactBytesObservationError::allocation_failed,
          ArtifactBytesObservationStage::input,
          kArtifactObservationGlobalIndex, 0, ERROR_NOT_ENOUGH_MEMORY);
    }

    std::array<ArtifactByteObservation, kArtifactCount> observations{};
    for (std::size_t index = 0; index < kArtifactCount; ++index) {
      LARGE_INTEGER zero{};
      LARGE_INTEGER position{};
#if defined(VAST_REPLAY_BROKER_ARTIFACT_BYTES_OBSERVATION_TESTING)
      if (should_fail(ArtifactBytesObservationTestFailurePoint::seek, index)) {
        return failure(ArtifactBytesObservationError::seek_failed,
            ArtifactBytesObservationStage::seek, index, 0,
            ERROR_GEN_FAILURE);
      }
#endif
      if (!SetFilePointerEx(reopened[index].get(), zero, &position, FILE_BEGIN) ||
          position.QuadPart != 0) {
        return failure(ArtifactBytesObservationError::seek_failed,
            ArtifactBytesObservationStage::seek, index, 0, GetLastError());
      }

      ScopedHash hash;
#if defined(VAST_REPLAY_BROKER_ARTIFACT_BYTES_OBSERVATION_TESTING)
      if (should_fail(
              ArtifactBytesObservationTestFailurePoint::bcrypt_create, index)) {
        return failure(ArtifactBytesObservationError::bcrypt_hash_create_failed,
            ArtifactBytesObservationStage::crypto_provider, index, 0,
            ERROR_SUCCESS, kInjectedBcryptFailure);
      }
#endif
      status = BCryptCreateHash(algorithm.get(), hash.put(), object.get(),
          object_length, nullptr, 0, 0);
      if (status < 0) {
        return failure(ArtifactBytesObservationError::bcrypt_hash_create_failed,
            ArtifactBytesObservationStage::crypto_provider, index, 0,
            ERROR_SUCCESS, status);
      }
      hash.mark_acquired();

      const std::uint64_t expected_size = seed->artifacts[index].size_bytes;
      std::uint64_t offset = 0;
      while (offset < expected_size) {
        const DWORD request = static_cast<DWORD>(std::min<std::uint64_t>(
            expected_size - offset, kReadChunkBytes));
        DWORD read = 0;
#if defined(VAST_REPLAY_BROKER_ARTIFACT_BYTES_OBSERVATION_TESTING)
        if (should_fail(ArtifactBytesObservationTestFailurePoint::read, index)) {
          return failure(ArtifactBytesObservationError::read_failed,
              ArtifactBytesObservationStage::read, index, offset,
              ERROR_GEN_FAILURE);
        }
#endif
        if (!ReadFile(reopened[index].get(), buffer.get(), request, &read,
                      nullptr)) {
          return failure(ArtifactBytesObservationError::read_failed,
              ArtifactBytesObservationStage::read, index, offset,
              GetLastError());
        }
        if (read == 0 || read > request) {
          return failure(ArtifactBytesObservationError::unexpected_eof,
              ArtifactBytesObservationStage::read, index, offset,
              ERROR_HANDLE_EOF);
        }
#if defined(VAST_REPLAY_BROKER_ARTIFACT_BYTES_OBSERVATION_TESTING)
        if (should_fail(
                ArtifactBytesObservationTestFailurePoint::bcrypt_update,
                index)) {
          return failure(
              ArtifactBytesObservationError::bcrypt_hash_update_failed,
              ArtifactBytesObservationStage::hash_update, index, offset,
              ERROR_SUCCESS, kInjectedBcryptFailure);
        }
#endif
        status = BCryptHashData(hash.get(), buffer.get(), read, 0);
        if (status < 0) {
          return failure(
              ArtifactBytesObservationError::bcrypt_hash_update_failed,
              ArtifactBytesObservationStage::hash_update, index, offset,
              ERROR_SUCCESS, status);
        }
        if (offset > std::numeric_limits<std::uint64_t>::max() - read) {
          return failure(ArtifactBytesObservationError::frozen_metadata_invalid,
              ArtifactBytesObservationStage::read, index, offset,
              ERROR_ARITHMETIC_OVERFLOW);
        }
        offset += read;
      }

      UCHAR trailing = 0;
      DWORD trailing_read = 0;
      if (!ReadFile(reopened[index].get(), &trailing, 1, &trailing_read,
                    nullptr)) {
        const DWORD code = GetLastError();
        if (code != ERROR_HANDLE_EOF) {
          return failure(ArtifactBytesObservationError::read_failed,
              ArtifactBytesObservationStage::read, index, offset, code);
        }
      } else if (trailing_read != 0) {
        return failure(ArtifactBytesObservationError::trailing_bytes,
            ArtifactBytesObservationStage::read, index, offset,
            ERROR_FILE_INVALID);
      }

      std::array<std::uint8_t, kSha256Bytes> computed{};
#if defined(VAST_REPLAY_BROKER_ARTIFACT_BYTES_OBSERVATION_TESTING)
      if (should_fail(
              ArtifactBytesObservationTestFailurePoint::bcrypt_finish, index)) {
        return failure(
            ArtifactBytesObservationError::bcrypt_hash_finish_failed,
            ArtifactBytesObservationStage::hash_finish, index, offset,
            ERROR_SUCCESS, kInjectedBcryptFailure);
      }
#endif
      status = BCryptFinishHash(hash.get(), computed.data(),
                                static_cast<ULONG>(computed.size()), 0);
      if (status < 0) {
        return failure(ArtifactBytesObservationError::bcrypt_hash_finish_failed,
            ArtifactBytesObservationStage::hash_finish, index, offset,
            ERROR_SUCCESS, status);
      }
      hash.reset();
      if (computed != expected[index]) {
        return failure(ArtifactBytesObservationError::sha256_mismatch,
            ArtifactBytesObservationStage::compare, index, offset);
      }
      observations[index] = {
          seed->artifacts[index].role, offset, computed};
    }

    for (std::size_t index = 0; index < kArtifactCount; ++index) {
#if defined(VAST_REPLAY_BROKER_ARTIFACT_BYTES_OBSERVATION_TESTING)
      if (should_fail(
              ArtifactBytesObservationTestFailurePoint::final_metadata,
              index)) {
        return failure(ArtifactBytesObservationError::metadata_changed,
            ArtifactBytesObservationStage::after_read_metadata, index, 0,
            ERROR_GEN_FAILURE);
      }
#endif
      FileSnapshot original_after{};
      FileSnapshot reopened_after{};
      if (!snapshot_file(seed->handles[index], HANDLE_FLAG_INHERIT,
              seed->artifacts[index].size_bytes, false,
              ArtifactBytesObservationStage::after_read_metadata,
              index, original_after, problem) ||
          !snapshot_file(reopened[index].get(), 0,
              seed->artifacts[index].size_bytes, true,
              ArtifactBytesObservationStage::after_read_metadata,
              index, reopened_after, problem)) return problem;
      if (!same_metadata(original_before[index], original_after) ||
          !same_metadata(reopened_before[index], reopened_after) ||
          !same_identity(original_after.identity, reopened_after.identity) ||
          !same_metadata(original_after, reopened_after)) {
        return failure(ArtifactBytesObservationError::metadata_changed,
            ArtifactBytesObservationStage::after_read_metadata, index, 0,
            ERROR_INVALID_DATA);
      }
    }

    auto implementation =
        std::unique_ptr<ArtifactBytesObservationImplementation>(
            new (std::nothrow) ArtifactBytesObservationImplementation(
                std::move(prepared), observations));
    if (!implementation) {
      return failure(ArtifactBytesObservationError::allocation_failed,
          ArtifactBytesObservationStage::input,
          kArtifactObservationGlobalIndex, 0, ERROR_NOT_ENOUGH_MEMORY);
    }
    return ArtifactBytesObservationImplementation::make(
        std::move(implementation));
  } catch (...) {
    return failure(ArtifactBytesObservationError::allocation_failed,
        ArtifactBytesObservationStage::input,
        kArtifactObservationGlobalIndex, 0, ERROR_NOT_ENOUGH_MEMORY);
  }
}

#if defined(VAST_REPLAY_BROKER_ARTIFACT_BYTES_OBSERVATION_TESTING)
void set_artifact_bytes_observation_test_failure(
    ArtifactBytesObservationTestFailurePoint point,
    std::size_t ordinal) noexcept {
  g_failure_point = point;
  g_failure_ordinal = ordinal;
}

ArtifactBytesObservationTestResources
artifact_bytes_observation_test_resources() noexcept {
  return {g_reopened_handles, g_algorithm_providers, g_hash_handles};
}
#endif

}  // namespace vast::replay_broker::v4
