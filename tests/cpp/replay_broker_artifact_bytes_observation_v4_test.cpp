#include "replay_broker_artifact_bytes_observation_v4.hpp"
#include "replay_broker_prepared_handles_observation_bridge_v4.hpp"

#include <Windows.h>

#include <algorithm>
#include <array>
#include <cstdint>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <string_view>
#include <type_traits>
#include <utility>
#include <variant>
#include <vector>

namespace {
namespace replay_v4 = vast::replay_broker::v4;

void require(bool condition, std::string_view message) {
  if (!condition) throw std::runtime_error(std::string(message));
}

std::string digest(char digit) { return std::string(64, digit); }

std::array<std::vector<std::uint8_t>, 6> artifact_bytes() {
  std::array<std::vector<std::uint8_t>, 6> values{};
  values[0] = {0x00};
  values[1] = {'a', 'b', 'c'};
  values[2] = {0xff, 0x00, 0x7f, 0x01};
  values[3] = {'r', 'u', 'n', 'n', 'e', 'r', '-', 'a', 'u', 't', 'h',
               'o', 'r', 'i', 't', 'y', '-', 'v', '4'};
  values[4].resize((1U << 20U) + 17U);
  for (std::size_t index = 0; index < values[4].size(); ++index) {
    values[4][index] = static_cast<std::uint8_t>(index % 251U);
  }
  values[5].resize(257U, 0U);
  return values;
}

constexpr std::array<std::string_view, 6> kExpectedSha256 = {{
    "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d",
    "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    "7a13d23d21e4910af4297b0299f847c02cc65fbf81e4b741105ae5461327f341",
    "d81c9f13503481b189ec3736a1021a77c57012ee37da50892d6b7a776367e0ac",
    "f4bf9b8dec6e3e28b2ec33266145d244fe97a6bce1ec054ace053bab67d2ef9a",
    "6c934d0cdf9dba94b474d6d1929f16739bd9a8ed31d0c3bcaf82c283fb7a3568",
}};

std::uint8_t hex_digit(char value) {
  if (value >= '0' && value <= '9') return static_cast<std::uint8_t>(value - '0');
  if (value >= 'a' && value <= 'f') {
    return static_cast<std::uint8_t>(10 + value - 'a');
  }
  throw std::runtime_error("invalid fixed SHA-256 vector");
}

std::array<std::uint8_t, 32> digest_bytes(std::string_view value) {
  require(value.size() == 64U, "invalid fixed SHA-256 length");
  std::array<std::uint8_t, 32> result{};
  for (std::size_t index = 0; index < result.size(); ++index) {
    result[index] = static_cast<std::uint8_t>(
        (hex_digit(value[index * 2U]) << 4U) |
        hex_digit(value[index * 2U + 1U]));
  }
  return result;
}

class FixtureHandle final {
 public:
  FixtureHandle() = default;
  explicit FixtureHandle(HANDLE value) noexcept : value_(value) {}
  ~FixtureHandle() { reset(); }
  FixtureHandle(const FixtureHandle&) = delete;
  FixtureHandle& operator=(const FixtureHandle&) = delete;
  FixtureHandle(FixtureHandle&& other) noexcept : value_(other.release()) {}
  FixtureHandle& operator=(FixtureHandle&& other) noexcept {
    if (this != &other) reset(other.release());
    return *this;
  }
  HANDLE get() const noexcept { return value_; }
  HANDLE release() noexcept { return std::exchange(value_, nullptr); }
  void reset(HANDLE value = nullptr) noexcept {
    if (value_ != nullptr && value_ != INVALID_HANDLE_VALUE) CloseHandle(value_);
    value_ = value;
  }

 private:
  HANDLE value_ = nullptr;
};

struct FileFixture final {
  std::wstring path;
  FixtureHandle handle;
  std::vector<std::uint8_t> bytes;

  FileFixture(std::vector<std::uint8_t> content, unsigned ordinal)
      : bytes(std::move(content)) {
    wchar_t directory[MAX_PATH + 1]{};
    require(GetTempPathW(MAX_PATH, directory) != 0, "GetTempPathW failed");
    path = directory;
    path += L"vast_observe_" + std::to_wstring(GetCurrentProcessId()) + L"_" +
            std::to_wstring(ordinal) + L"_" + std::to_wstring(GetTickCount64());
    FixtureHandle writer(CreateFileW(path.c_str(), GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
        CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr));
    require(writer.get() != INVALID_HANDLE_VALUE, "fixture file create failed");
    DWORD written = 0;
    require(bytes.size() <= static_cast<std::size_t>(MAXDWORD),
            "fixture exceeds one WriteFile call");
    require(WriteFile(writer.get(), bytes.data(), static_cast<DWORD>(bytes.size()),
                      &written, nullptr) != FALSE && written == bytes.size(),
            "fixture file write failed");
    writer.reset();
    handle.reset(CreateFileW(path.c_str(),
        FILE_READ_DATA | FILE_READ_ATTRIBUTES | SYNCHRONIZE,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
        OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
    require(handle.get() != INVALID_HANDLE_VALUE, "fixture file read open failed");
  }
  ~FileFixture() {
    handle.reset();
    if (!path.empty()) DeleteFileW(path.c_str());
  }
  FileFixture(const FileFixture&) = delete;
  FileFixture& operator=(const FileFixture&) = delete;

  void replace_same_size(std::uint8_t value) {
    FixtureHandle writer(CreateFileW(path.c_str(), FILE_WRITE_DATA,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
        OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
    require(writer.get() != INVALID_HANDLE_VALUE, "mutation open failed");
    std::vector<std::uint8_t> replacement(bytes.size(), value);
    DWORD written = 0;
    require(WriteFile(writer.get(), replacement.data(),
                      static_cast<DWORD>(replacement.size()), &written,
                      nullptr) != FALSE && written == replacement.size(),
            "mutation write failed");
    FlushFileBuffers(writer.get());
  }

  void resize(std::uint64_t size) {
    FixtureHandle writer(CreateFileW(path.c_str(), FILE_WRITE_DATA,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
        OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
    require(writer.get() != INVALID_HANDLE_VALUE, "resize open failed");
    LARGE_INTEGER target{};
    target.QuadPart = static_cast<LONGLONG>(size);
    require(SetFilePointerEx(writer.get(), target, nullptr, FILE_BEGIN) != FALSE &&
                SetEndOfFile(writer.get()) != FALSE,
            "resize failed");
    FlushFileBuffers(writer.get());
  }

  FixtureHandle open_writer_sentinel() const {
    return FixtureHandle(CreateFileW(path.c_str(), FILE_WRITE_DATA,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
        OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
  }
};

struct PipeFixture final {
  FixtureHandle read;
  FixtureHandle write;
  PipeFixture() {
    HANDLE read_value = nullptr;
    HANDLE write_value = nullptr;
    require(CreatePipe(&read_value, &write_value, nullptr, 0) != FALSE,
            "CreatePipe failed");
    read.reset(read_value);
    write.reset(write_value);
  }
};

struct Fixture final {
  std::array<std::unique_ptr<FileFixture>, 6> files{};
  PipeFixture challenge;
  PipeFixture stdin_eof;
  PipeFixture stdout_record;
  PipeFixture stderr_ack;

  Fixture() {
    auto values = artifact_bytes();
    for (std::size_t index = 0; index < files.size(); ++index) {
      files[index] = std::make_unique<FileFixture>(
          std::move(values[index]), static_cast<unsigned>(index));
    }
  }

  replay_v4::ContractInput input() const {
    using AR = replay_v4::ArtifactRole;
    using CR = replay_v4::ChannelRole;
    return {
        std::string(replay_v4::kReplayProtocolSemanticSha256), digest('7'),
        "session-1", "lease-1", 559, 1, digest('b'), digest('c'), digest('d'),
        {{{AR::runner_entrypoint_read, std::string(kExpectedSha256[0]), digest('a'),
           files[0]->bytes.size(), {0}},
          {AR::runner_authority_read, std::string(kExpectedSha256[1]), digest('b'),
           files[1]->bytes.size(), {0}},
          {AR::validator_authority_read, std::string(kExpectedSha256[2]), digest('c'),
           files[2]->bytes.size(), {0}},
          {AR::validation_request_read, std::string(kExpectedSha256[3]), digest('d'),
           files[3]->bytes.size(), {0}},
          {AR::raw_evidence_read, std::string(kExpectedSha256[4]), digest('e'),
           files[4]->bytes.size(), {0}},
          {AR::runtime_closure_bundle_read, std::string(kExpectedSha256[5]), digest('f'),
           files[5]->bytes.size(), {0}}}},
        {{{CR::challenge_read, {0}}, {CR::stdin_eof_read, {0}},
          {CR::record_stdout_write, {0}},
          {CR::acknowledgement_stderr_write, {0}}}}};
  }

  std::array<HANDLE, 10> raw_handles() const noexcept {
    return {{files[0]->handle.get(), files[1]->handle.get(),
             files[2]->handle.get(), files[3]->handle.get(),
             files[4]->handle.get(), files[5]->handle.get(),
             challenge.read.get(), stdin_eof.read.get(),
             stdout_record.write.get(), stderr_ack.write.get()}};
  }

  replay_v4::TransferredHandleSet take() {
    auto result = replay_v4::TransferredHandleSet::take_exclusive(raw_handles());
    require(result.value != nullptr, "valid exclusive transfer failed");
    for (auto& file : files) (void)file->handle.release();
    (void)challenge.read.release();
    (void)stdin_eof.read.release();
    (void)stdout_record.write.release();
    (void)stderr_ack.write.release();
    return std::move(*result.value);
  }
};

replay_v4::PreparedOsHandleSet prepare(
    Fixture& fixture, replay_v4::ContractInput metadata) {
  auto result = replay_v4::prepare_os_handles(std::move(metadata), fixture.take());
  auto* prepared = std::get_if<replay_v4::PreparedOsHandleSet>(&result);
  if (prepared == nullptr) {
    const auto& failed = std::get<replay_v4::PrepareHandleFailure>(result);
    throw std::runtime_error("PREPARED failed error=" +
        std::to_string(static_cast<int>(failed.error)) + " index=" +
        std::to_string(failed.index) + " win32=" +
        std::to_string(failed.win32_error));
  }
  return std::move(*prepared);
}

replay_v4::ArtifactBytesObservedPreparedOsHandleSet& observed(
    replay_v4::ArtifactBytesObservationResult& result) {
  auto* value = std::get_if<
      replay_v4::ArtifactBytesObservedPreparedOsHandleSet>(&result);
  if (value == nullptr) {
    const auto& failed = std::get<replay_v4::ArtifactBytesObservationFailure>(result);
    throw std::runtime_error("observation failed error=" +
        std::to_string(static_cast<int>(failed.error)) + " stage=" +
        std::to_string(static_cast<int>(failed.stage)) + " index=" +
        std::to_string(failed.index) + " win32=" +
        std::to_string(failed.win32_error) + " bcrypt=" +
        std::to_string(failed.bcrypt_status));
  }
  return *value;
}

replay_v4::ArtifactBytesObservationFailure failed(
    replay_v4::ArtifactBytesObservationResult& result) {
  auto* value = std::get_if<replay_v4::ArtifactBytesObservationFailure>(&result);
  require(value != nullptr, "expected observation failure");
  return *value;
}

void require_handles_closed(const std::array<HANDLE, 10>& handles) {
  for (HANDLE value : handles) {
    DWORD flags = 0;
    require(GetHandleInformation(value, &flags) == FALSE,
            "consumed PREPARED handle remained open on failure");
  }
}

void require_no_observation_resources() {
  const auto resources = replay_v4::artifact_bytes_observation_test_resources();
  require(resources.reopened_handles == 0U && resources.algorithm_providers == 0U &&
              resources.hash_handles == 0U,
          "observation leaked a Win32 or CNG resource");
}

void known_vectors_are_observed_without_changing_child_offsets() {
  static_assert(!std::is_copy_constructible_v<
                replay_v4::ArtifactBytesObservedPreparedOsHandleSet>);
  static_assert(std::is_move_constructible_v<
                replay_v4::ArtifactBytesObservedPreparedOsHandleSet>);
  Fixture fixture;
  auto prepared = prepare(fixture, fixture.input());
  const auto child_values = prepared.child_handles();
  std::array<LONGLONG, 6> positions{};
  for (std::size_t index = 0; index < positions.size(); ++index) {
    LARGE_INTEGER target{};
    target.QuadPart = static_cast<LONGLONG>(
        std::min<std::size_t>(index + 1U, fixture.files[index]->bytes.size()));
    LARGE_INTEGER actual{};
    require(SetFilePointerEx(child_values[index], target, &actual, FILE_BEGIN) != FALSE,
            "child cursor setup failed");
    positions[index] = actual.QuadPart;
  }

  auto result = replay_v4::observe_artifact_bytes(std::move(prepared));
  require(!replay_v4::detail::PreparedHandleObservationBridge::snapshot(prepared),
          "source PREPARED still owns a PIMPL after consuming observation");
  auto& value = observed(result);
  require(value.valid(), "successful observed typestate is invalid");
  const auto* claims = value.claims();
  require(claims != nullptr &&
              claims->artifact_file_bytes_sha256_point_in_time_validated &&
              claims->all_six_expected_length_byte_sequences_observed &&
              claims->handle_relative_reopen_used &&
              claims->separate_reopened_file_objects_used_for_reads &&
              claims->pre_post_identity_metadata_stable_point_in_time &&
              claims->results_published_all_or_none &&
              claims->prepared_handle_custody_retained &&
              !claims->artifact_semantic_identity_validated &&
              !claims->source_bytes_immutable_validated &&
              !claims->atomic_six_artifact_snapshot_validated &&
              !claims->coherent_cross_artifact_snapshot_validated &&
              !claims->mutation_impossible_validated &&
              !claims->digest_binds_future_child_consumption &&
              !claims->bounded_completion_latency_validated &&
              !claims->inherited_handle_allowlist_validated &&
              !claims->ambient_inheritable_handles_absent_validated &&
              !claims->process_created && !claims->process_executed &&
              !claims->execution_authorized,
          "observation claim surface drifted");
  const auto* observations = value.observations();
  const auto* retained = value.prepared_handles();
  require(observations != nullptr && retained != nullptr,
          "successful observation did not retain complete output");
  for (std::size_t index = 0; index < observations->size(); ++index) {
    require((*observations)[index].role == fixture.input().artifacts[index].role &&
                (*observations)[index].bytes_observed ==
                    fixture.files[index]->bytes.size() &&
                (*observations)[index].sha256 == digest_bytes(kExpectedSha256[index]),
            "observed artifact tuple drifted");
    require(retained->child_handles()[index] == child_values[index],
            "observation replaced a child artifact handle");
    DWORD flags = 0;
    require(GetHandleInformation(child_values[index], &flags) != FALSE &&
                flags == HANDLE_FLAG_INHERIT,
            "retained child handle flags drifted");
    LARGE_INTEGER zero{};
    LARGE_INTEGER current{};
    require(SetFilePointerEx(child_values[index], zero, &current, FILE_CURRENT) != FALSE &&
                current.QuadPart == positions[index],
            "observer changed a child file cursor");
  }
  require(retained->startup_info().StartupInfo.hStdInput == child_values[7] &&
              retained->startup_info().StartupInfo.hStdOutput == child_values[8] &&
              retained->startup_info().StartupInfo.hStdError == child_values[9],
          "observer changed prepared standard handles");
  require_no_observation_resources();

  replay_v4::ArtifactBytesObservedPreparedOsHandleSet moved(std::move(value));
  require(!value.valid() && value.prepared_handles() == nullptr &&
              value.observations() == nullptr && value.claims() == nullptr,
          "moved-from observed typestate still exposes success claims");
  require(moved.valid() && moved.prepared_handles() != nullptr,
          "moved-to observed typestate lost custody");
}

void wrong_hash_size_drift_and_writer_share_are_rejected() {
  {
    Fixture fixture;
    auto metadata = fixture.input();
    metadata.artifacts[2].file_sha256 = digest('9');
    auto prepared = prepare(fixture, std::move(metadata));
    const auto handles = prepared.child_handles();
    auto result = replay_v4::observe_artifact_bytes(std::move(prepared));
    const auto error = failed(result);
    require(error.error == replay_v4::ArtifactBytesObservationError::sha256_mismatch &&
                error.index == 2U,
            "wrong SHA-256 did not fail precisely");
    require_handles_closed(handles);
    require_no_observation_resources();
  }
  {
    Fixture fixture;
    auto prepared = prepare(fixture, fixture.input());
    const auto handles = prepared.child_handles();
    fixture.files[4]->resize(fixture.files[4]->bytes.size() - 1U);
    auto result = replay_v4::observe_artifact_bytes(std::move(prepared));
    const auto error = failed(result);
    require(error.error ==
                replay_v4::ArtifactBytesObservationError::metadata_size_mismatch &&
                error.index == 4U,
            "size drift did not fail before hashing");
    require_handles_closed(handles);
    require_no_observation_resources();
  }
  {
    Fixture fixture;
    auto prepared = prepare(fixture, fixture.input());
    const auto handles = prepared.child_handles();
    auto writer = fixture.files[0]->open_writer_sentinel();
    require(writer.get() != INVALID_HANDLE_VALUE, "writer sentinel open failed");
    auto result = replay_v4::observe_artifact_bytes(std::move(prepared));
    const auto error = failed(result);
    require(error.error == replay_v4::ArtifactBytesObservationError::reopen_failed &&
                error.index == 0U && error.win32_error == ERROR_SHARING_VIOLATION,
            "writer-share conflict did not fail closed");
    require_handles_closed(handles);
    require_no_observation_resources();
  }
}

void same_size_mutation_is_detected_by_digest() {
  Fixture fixture;
  auto prepared = prepare(fixture, fixture.input());
  const auto handles = prepared.child_handles();
  fixture.files[1]->replace_same_size(0x5aU);
  auto result = replay_v4::observe_artifact_bytes(std::move(prepared));
  const auto error = failed(result);
  require(error.error == replay_v4::ArtifactBytesObservationError::sha256_mismatch &&
              error.index == 1U,
          "same-size mutation did not fail digest comparison");
  require_handles_closed(handles);
  require_no_observation_resources();
}

void injected_failures_are_precise_consuming_and_leak_free() {
  using Error = replay_v4::ArtifactBytesObservationError;
  using Point = replay_v4::ArtifactBytesObservationTestFailurePoint;
  struct Case final {
    Point point;
    std::size_t ordinal;
    Error error;
    std::size_t index;
  };
  const std::array<Case, 12> cases = {{{Point::reopen, 0, Error::reopen_failed, 0},
      {Point::reopen, 3, Error::reopen_failed, 3},
      {Point::reopen, 5, Error::reopen_failed, 5},
      {Point::bcrypt_open, 0, Error::bcrypt_provider_open_failed,
       replay_v4::kArtifactObservationGlobalIndex},
      {Point::bcrypt_object_length, 0, Error::bcrypt_property_query_failed,
       replay_v4::kArtifactObservationGlobalIndex},
      {Point::bcrypt_hash_length, 0, Error::bcrypt_property_query_failed,
       replay_v4::kArtifactObservationGlobalIndex},
      {Point::bcrypt_create, 2, Error::bcrypt_hash_create_failed, 2},
      {Point::read, 4, Error::read_failed, 4},
      {Point::bcrypt_update, 1, Error::bcrypt_hash_update_failed, 1},
      {Point::bcrypt_finish, 5, Error::bcrypt_hash_finish_failed, 5},
      {Point::seek, 3, Error::seek_failed, 3},
      {Point::final_metadata, 2, Error::metadata_changed, 2}}};

  for (const auto& test : cases) {
    Fixture fixture;
    auto prepared = prepare(fixture, fixture.input());
    const auto handles = prepared.child_handles();
    replay_v4::set_artifact_bytes_observation_test_failure(
        test.point, test.ordinal);
    auto result = replay_v4::observe_artifact_bytes(std::move(prepared));
    replay_v4::set_artifact_bytes_observation_test_failure(Point::none, 0);
    const auto error = failed(result);
    require(error.error == test.error && error.index == test.index,
            "injected observation failure taxonomy drifted");
    require_handles_closed(handles);
    require_no_observation_resources();
  }
}

void moved_from_prepared_is_rejected_without_claims() {
  Fixture fixture;
  auto prepared = prepare(fixture, fixture.input());
  replay_v4::PreparedOsHandleSet owner(std::move(prepared));
  auto result = replay_v4::observe_artifact_bytes(std::move(prepared));
  const auto error = failed(result);
  require(error.error ==
              replay_v4::ArtifactBytesObservationError::invalid_prepared_state &&
              error.index == replay_v4::kArtifactObservationGlobalIndex,
          "moved-from PREPARED state was not rejected precisely");
  require(owner.child_handles()[0] != nullptr,
          "rejecting moved-from input disturbed the actual owner");
  require_no_observation_resources();
}

}  // namespace

int main() {
  try {
    known_vectors_are_observed_without_changing_child_offsets();
    wrong_hash_size_drift_and_writer_share_are_rejected();
    same_size_mutation_is_detected_by_digest();
    injected_failures_are_precise_consuming_and_leak_free();
    moved_from_prepared_is_rejected_without_claims();
    std::cout << "replay broker artifact byte observation v4 tests passed\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
