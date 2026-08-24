#include "replay_broker_prepared_handles_v4.hpp"
#include "replay_broker_prepared_handles_observation_bridge_v4.hpp"

#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <type_traits>
#include <utility>
#include <variant>

namespace {
namespace replay_v4 = vast::replay_broker::v4;

void require(bool condition, std::string_view message) {
  if (!condition) throw std::runtime_error(std::string(message));
}

std::uint64_t token(HANDLE value) noexcept {
  return static_cast<std::uint64_t>(reinterpret_cast<std::uintptr_t>(value));
}

std::string digest(char digit) { return std::string(64, digit); }

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
  std::uint64_t size_bytes;

  FileFixture(std::uint64_t size, unsigned ordinal) : size_bytes(size) {
    wchar_t directory[MAX_PATH + 1]{};
    require(GetTempPathW(MAX_PATH, directory) != 0, "GetTempPathW failed");
    path = directory;
    path += L"vast_prepared_" + std::to_wstring(GetCurrentProcessId()) + L"_" +
            std::to_wstring(ordinal) + L"_" + std::to_wstring(GetTickCount64());
    FixtureHandle writer(CreateFileW(path.c_str(), GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
        CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr));
    require(writer.get() != INVALID_HANDLE_VALUE, "fixture file create failed");
    std::array<unsigned char, 6> bytes{};
    DWORD written = 0;
    require(WriteFile(writer.get(), bytes.data(), static_cast<DWORD>(size),
                      &written, nullptr) != FALSE && written == size,
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
  std::array<FileFixture, 6> files{{
      FileFixture(1, 1), FileFixture(2, 2), FileFixture(3, 3),
      FileFixture(4, 4), FileFixture(5, 5), FileFixture(6, 6)}};
  PipeFixture challenge;
  PipeFixture stdin_eof;
  PipeFixture stdout_record;
  PipeFixture stderr_ack;

  replay_v4::ContractInput input() const {
    using AR = replay_v4::ArtifactRole;
    using CR = replay_v4::ChannelRole;
    return {
        std::string(replay_v4::kReplayProtocolSemanticSha256), digest('7'),
        "session-1", "lease-1", 559, 1, digest('b'), digest('c'), digest('d'),
        {{{AR::runner_entrypoint_read, digest('1'), digest('a'), 1, {0}},
          {AR::runner_authority_read, digest('2'), digest('b'), 2, {0}},
          {AR::validator_authority_read, digest('3'), digest('c'), 3, {0}},
          {AR::validation_request_read, digest('4'), digest('d'), 4, {0}},
          {AR::raw_evidence_read, digest('5'), digest('e'), 5, {0}},
          {AR::runtime_closure_bundle_read, digest('6'), digest('f'), 6, {0}}}},
        {{{CR::challenge_read, {0}}, {CR::stdin_eof_read, {0}},
          {CR::record_stdout_write, {0}},
          {CR::acknowledgement_stderr_write, {0}}}}};
  }

  std::array<HANDLE, 10> raw_handles() const noexcept {
    return {{files[0].handle.get(), files[1].handle.get(), files[2].handle.get(),
             files[3].handle.get(), files[4].handle.get(), files[5].handle.get(),
             challenge.read.get(), stdin_eof.read.get(), stdout_record.write.get(),
             stderr_ack.write.get()}};
  }

  replay_v4::TakeExclusiveResult take_exclusive() {
    auto result = replay_v4::TransferredHandleSet::take_exclusive(raw_handles());
    if (result.value != nullptr) {
      (void)files[0].handle.release(); (void)files[1].handle.release();
      (void)files[2].handle.release(); (void)files[3].handle.release();
      (void)files[4].handle.release(); (void)files[5].handle.release();
      (void)challenge.read.release(); (void)stdin_eof.read.release();
      (void)stdout_record.write.release(); (void)stderr_ack.write.release();
    }
    return result;
  }
};

replay_v4::TransferredHandleSet take(Fixture& fixture) {
  auto result = fixture.take_exclusive();
  if (result.value == nullptr) {
    throw std::runtime_error("valid exclusive transfer failed; error=" +
        std::to_string(static_cast<int>(result.failure.error)) + " index=" +
        std::to_string(result.failure.index));
  }
  return std::move(*result.value);
}

replay_v4::PreparedOsHandleSet& success(replay_v4::PrepareHandleResult& result) {
  auto* value = std::get_if<replay_v4::PreparedOsHandleSet>(&result);
  if (value == nullptr) {
    const auto& failed = std::get<replay_v4::PrepareHandleFailure>(result);
    throw std::runtime_error("expected PREPARED OS-handle success; error=" +
        std::to_string(static_cast<int>(failed.error)) + " index=" +
        std::to_string(failed.index) + " win32=" +
        std::to_string(failed.win32_error));
  }
  return *value;
}

replay_v4::PrepareHandleFailure failure(replay_v4::PrepareHandleResult& result) {
  auto* value = std::get_if<replay_v4::PrepareHandleFailure>(&result);
  require(value != nullptr, "expected PREPARED OS-handle failure");
  return *value;
}

std::string expected_map(const std::array<HANDLE, 10>& handles) {
  static constexpr std::array<std::string_view, 10> roles = {{
      "runner_entrypoint_read", "runner_authority_read",
      "validator_authority_read", "validation_request_read", "raw_evidence_read",
      "runtime_closure_bundle_read", "challenge_read", "stdin_eof_read",
      "record_stdout_write", "acknowledgement_stderr_write"}};
  std::string value = "hmap4";
  for (std::size_t index = 0; index < handles.size(); ++index) {
    value += ";";
    value += roles[index];
    value += "=";
    value += std::to_string(token(handles[index]));
  }
  return value;
}

void success_consumes_originals_and_owns_exact_duplicate_set() {
  static_assert(!std::is_copy_constructible_v<replay_v4::TransferredHandleSet>);
  static_assert(!std::is_copy_constructible_v<replay_v4::PreparedOsHandleSet>);
  static_assert(std::is_move_constructible_v<replay_v4::PreparedOsHandleSet>);
  Fixture fixture;
  const auto originals = fixture.raw_handles();
  auto result = replay_v4::prepare_os_handles(fixture.input(), take(fixture));
  auto& prepared = success(result);
  require(prepared.state() ==
              replay_v4::PreparedHandleState::prepared_os_handles_validated,
          "wrong PREPARED state");
  for (HANDLE original : originals) {
    DWORD flags = 0;
    require(GetHandleInformation(original, &flags) == FALSE,
            "successful preparation did not consume an original HANDLE");
  }
  const auto& children = prepared.child_handles();
  for (std::size_t index = 0; index < children.size(); ++index) {
    DWORD flags = 0;
    require(GetHandleInformation(children[index], &flags) != FALSE &&
                flags == HANDLE_FLAG_INHERIT,
            "owned duplicate flags are not exactly inheritable");
    for (std::size_t prior = 0; prior < index; ++prior) {
      require(children[index] != children[prior], "owned duplicate aliases");
    }
  }
  require(prepared.logical_binding().logical_argv_projection.back() ==
              expected_map(children),
          "argv handle-map is not exact owned duplicate set");
  const auto& startup = prepared.startup_info();
  require(startup.lpAttributeList != nullptr &&
              (startup.StartupInfo.dwFlags & STARTF_USESTDHANDLES) != 0 &&
              startup.StartupInfo.hStdInput == children[7] &&
              startup.StartupInfo.hStdOutput == children[8] &&
              startup.StartupInfo.hStdError == children[9],
          "prepared standard handle mapping drifted");
  const auto claims = prepared.claims();
  require(claims.original_handle_flags_point_in_time_validated &&
              claims.os_handle_endpoint_shape_point_in_time_validated &&
              claims.broker_owned_duplicate_set_point_in_time_validated &&
              claims.prepared_standard_handle_mapping_constructed &&
              !claims.artifact_file_bytes_identity_validated &&
              !claims.artifact_semantic_identity_validated &&
              !claims.inherited_handle_allowlist_validated &&
              !claims.ambient_inheritable_handles_absent_validated &&
              !claims.process_created && !claims.process_executed &&
              !claims.execution_authorized,
          "PREPARED claim surface overclaimed");
}

void failure_consumes_originals_and_leaks_no_partial_output() {
  Fixture fixture;
  auto metadata = fixture.input();
  ++metadata.artifacts[5].size_bytes;
  const auto originals = fixture.raw_handles();
  DWORD before = 0;
  require(GetProcessHandleCount(GetCurrentProcess(), &before) != FALSE,
          "handle count before failure failed");
  auto result = replay_v4::prepare_os_handles(metadata, take(fixture));
  require(failure(result).error == replay_v4::PrepareHandleError::artifact_size_mismatch,
          "wrong-size artifact was not rejected precisely");
  for (HANDLE original : originals) {
    DWORD flags = 0;
    require(GetHandleInformation(original, &flags) == FALSE,
            "failed preparation did not consume an original HANDLE");
  }
  DWORD after = 0;
  require(GetProcessHandleCount(GetCurrentProcess(), &after) != FALSE &&
              after + originals.size() == before,
          "failed preparation leaked a duplicate or partial output");
}

void invalid_inherit_access_and_identity_are_rejected() {
  {
    Fixture fixture;
    const HANDLE first = fixture.files[0].handle.get();
    require(SetHandleInformation(first, HANDLE_FLAG_PROTECT_FROM_CLOSE,
                                 HANDLE_FLAG_PROTECT_FROM_CLOSE) != FALSE,
            "test could not protect original from close");
    auto transfer = fixture.take_exclusive();
    DWORD flags = 0;
    const bool retained = GetHandleInformation(first, &flags) != FALSE;
    const bool restored = SetHandleInformation(
        first, HANDLE_FLAG_PROTECT_FROM_CLOSE, 0) != FALSE;
    require(transfer.value == nullptr && transfer.failure.error ==
                replay_v4::TransferHandleError::handle_flags_not_zero &&
                retained && (flags & HANDLE_FLAG_PROTECT_FROM_CLOSE) != 0 &&
                restored,
            "protected original was consumed, mutated, or accepted");
  }
  {
    Fixture fixture;
    const HANDLE first = fixture.files[0].handle.get();
    require(SetHandleInformation(first, HANDLE_FLAG_INHERIT,
                                 HANDLE_FLAG_INHERIT) != FALSE,
            "test could not mark original inheritable");
    auto transfer = fixture.take_exclusive();
    require(transfer.value == nullptr && transfer.failure.error ==
                replay_v4::TransferHandleError::handle_flags_not_zero,
            "inheritable original passed exclusive-transfer factory");
    DWORD flags = 0;
    require(GetHandleInformation(first, &flags) != FALSE &&
                flags == HANDLE_FLAG_INHERIT,
            "failed factory consumed or mutated caller custody");
    require(SetHandleInformation(first, HANDLE_FLAG_INHERIT, 0) != FALSE,
            "test could not restore inherit flag");
  }
  {
    Fixture fixture;
    FixtureHandle writable(CreateFileW(fixture.files[0].path.c_str(),
        GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
        OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
    require(writable.get() != INVALID_HANDLE_VALUE, "writable open failed");
    fixture.files[0].handle.reset(writable.release());
    auto result = replay_v4::prepare_os_handles(fixture.input(), take(fixture));
    require(failure(result).error == replay_v4::PrepareHandleError::disk_access_invalid,
            "writable disk endpoint was not rejected");
  }
  {
    Fixture fixture;
    HANDLE read_end = fixture.challenge.read.release();
    HANDLE write_end = fixture.stdout_record.write.release();
    fixture.challenge.read.reset(write_end);
    fixture.stdout_record.write.reset(read_end);
    auto result = replay_v4::prepare_os_handles(fixture.input(), take(fixture));
    require(failure(result).error == replay_v4::PrepareHandleError::pipe_direction_invalid,
            "wrong pipe direction was not rejected");
  }
  {
    Fixture fixture;
    FixtureHandle alias(CreateFileW(fixture.files[0].path.c_str(),
        FILE_READ_DATA | FILE_READ_ATTRIBUTES | SYNCHRONIZE,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
        OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
    require(alias.get() != INVALID_HANDLE_VALUE, "identity alias open failed");
    fixture.files[1].handle.reset(alias.release());
    auto metadata = fixture.input();
    metadata.artifacts[1].size_bytes = metadata.artifacts[0].size_bytes;
    auto result = replay_v4::prepare_os_handles(metadata, take(fixture));
    require(failure(result).error ==
                replay_v4::PrepareHandleError::duplicate_disk_identity,
            "duplicate disk FileId was not rejected");
  }
  {
    Fixture fixture;
    const std::wstring hardlink = fixture.files[0].path + L".hardlink";
    require(CreateHardLinkW(hardlink.c_str(), fixture.files[0].path.c_str(),
                            nullptr) != FALSE,
            "hardlink fixture creation failed");
    auto result = replay_v4::prepare_os_handles(fixture.input(), take(fixture));
    const auto rejected = failure(result);
    const bool removed = DeleteFileW(hardlink.c_str()) != FALSE;
    require(rejected.error == replay_v4::PrepareHandleError::disk_metadata_invalid &&
                removed,
            "hardlinked disk endpoint was not rejected");
  }
  {
    Fixture fixture;
    FixtureHandle deleter(CreateFileW(fixture.files[0].path.c_str(), DELETE,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
        OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
    require(deleter.get() != INVALID_HANDLE_VALUE,
            "delete-pending fixture open failed");
    FILE_DISPOSITION_INFO disposition{TRUE};
    require(SetFileInformationByHandle(deleter.get(), FileDispositionInfo,
                                       &disposition,
                                       sizeof(disposition)) != FALSE,
            "delete-pending fixture disposition failed");
    deleter.reset();
    auto result = replay_v4::prepare_os_handles(fixture.input(), take(fixture));
    require(failure(result).error ==
                replay_v4::PrepareHandleError::disk_metadata_invalid,
            "delete-pending disk endpoint was not rejected");
  }
  {
    Fixture fixture;
    wchar_t temporary[MAX_PATH + 1]{};
    require(GetTempPathW(MAX_PATH, temporary) != 0,
            "directory fixture temp path failed");
    std::wstring directory = temporary;
    directory += L"vast_prepared_dir_" +
        std::to_wstring(GetCurrentProcessId()) + L"_" +
        std::to_wstring(GetTickCount64());
    require(CreateDirectoryW(directory.c_str(), nullptr) != FALSE,
            "directory fixture create failed");
    FixtureHandle directory_handle(CreateFileW(directory.c_str(),
        FILE_READ_DATA | FILE_READ_ATTRIBUTES | SYNCHRONIZE,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
        OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, nullptr));
    require(directory_handle.get() != INVALID_HANDLE_VALUE,
            "directory fixture open failed");
    fixture.files[0].handle.reset(directory_handle.release());
    auto result = replay_v4::prepare_os_handles(fixture.input(), take(fixture));
    const auto rejected = failure(result);
    const bool removed = RemoveDirectoryW(directory.c_str()) != FALSE;
    require(rejected.error == replay_v4::PrepareHandleError::disk_metadata_invalid &&
                removed,
            "directory disk endpoint was not rejected");
  }
}

void distinct_handle_values_cannot_alias_channel_objects() {
  {
    Fixture fixture;
    HANDLE alias = nullptr;
    require(DuplicateHandle(GetCurrentProcess(), fixture.challenge.read.get(),
                            GetCurrentProcess(), &alias, 0, FALSE,
                            DUPLICATE_SAME_ACCESS) != FALSE,
            "read-role alias duplication failed");
    fixture.stdin_eof.read.reset(alias);
    auto result = replay_v4::prepare_os_handles(fixture.input(), take(fixture));
    require(failure(result).error ==
                replay_v4::PrepareHandleError::duplicate_endpoint_object,
            "distinct read HANDLE values aliased one channel object");
  }
  {
    Fixture fixture;
    HANDLE alias = nullptr;
    require(DuplicateHandle(GetCurrentProcess(),
                            fixture.stdout_record.write.get(),
                            GetCurrentProcess(), &alias, 0, FALSE,
                            DUPLICATE_SAME_ACCESS) != FALSE,
            "write-role alias duplication failed");
    fixture.stderr_ack.write.reset(alias);
    auto result = replay_v4::prepare_os_handles(fixture.input(), take(fixture));
    require(failure(result).error ==
                replay_v4::PrepareHandleError::duplicate_endpoint_object,
            "distinct write HANDLE values aliased one channel object");
  }
}

void injected_failures_are_atomic_and_consume_transfer() {
  using Point = replay_v4::PreparedHandlesTestFailurePoint;
  struct Case final {
    Point point;
    std::size_t ordinal;
    replay_v4::PrepareHandleError expected;
  };
  constexpr std::array<Case, 5> cases{{
      {Point::duplicate, 0, replay_v4::PrepareHandleError::duplicate_failed},
      {Point::duplicate, 5, replay_v4::PrepareHandleError::duplicate_failed},
      {Point::duplicate, 9, replay_v4::PrepareHandleError::duplicate_failed},
      {Point::attribute_initialize, 0,
       replay_v4::PrepareHandleError::attribute_list_failed},
      {Point::attribute_update, 0,
       replay_v4::PrepareHandleError::attribute_list_failed},
  }};
  for (const auto& test_case : cases) {
    Fixture fixture;
    const auto originals = fixture.raw_handles();
    DWORD before = 0;
    require(GetProcessHandleCount(GetCurrentProcess(), &before) != FALSE,
            "handle count before injected failure failed");
    replay_v4::set_prepared_handles_test_failure(
        test_case.point, test_case.ordinal);
    auto result = replay_v4::prepare_os_handles(fixture.input(), take(fixture));
    replay_v4::set_prepared_handles_test_failure(Point::none, 0);
    require(failure(result).error == test_case.expected,
            "injected failure returned the wrong error");
    for (HANDLE original : originals) {
      DWORD flags = 0;
      require(GetHandleInformation(original, &flags) == FALSE,
              "injected failure did not consume an original HANDLE");
    }
    DWORD after = 0;
    require(GetProcessHandleCount(GetCurrentProcess(), &after) != FALSE &&
                after + originals.size() == before,
            "injected failure leaked a duplicate or partial output");
  }
}

void moved_result_keeps_heap_stable_attribute_storage() {
  Fixture fixture;
  auto result = replay_v4::prepare_os_handles(fixture.input(), take(fixture));
  auto prepared = std::move(success(result));
  const auto* attribute = prepared.startup_info().lpAttributeList;
  auto moved = std::move(prepared);
  require(moved.startup_info().lpAttributeList == attribute,
          "moving result relocated attribute-list backing storage");
  for (HANDLE child : moved.child_handles()) {
    DWORD flags = 0;
    require(GetHandleInformation(child, &flags) != FALSE,
            "moving result lost duplicate ownership");
  }
}

void observation_bridge_snapshots_only_frozen_artifact_seed() {
  Fixture fixture;
  const auto expected = fixture.input();
  auto result = replay_v4::prepare_os_handles(expected, take(fixture));
  auto& prepared = success(result);
  const auto seed = replay_v4::detail::PreparedHandleObservationBridge::snapshot(
      prepared);
  require(seed.has_value(), "valid PREPARED did not yield observation seed");
  for (std::size_t index = 0; index < seed->handles.size(); ++index) {
    require(seed->handles[index] == prepared.child_handles()[index],
            "observation seed did not borrow exact child artifact HANDLE");
    require(seed->artifacts[index].role == expected.artifacts[index].role &&
                seed->artifacts[index].size_bytes ==
                    expected.artifacts[index].size_bytes &&
                seed->artifacts[index].file_sha256 ==
                    expected.artifacts[index].file_sha256,
            "observation seed did not copy exact frozen artifact metadata");
  }
  auto moved = std::move(prepared);
  require(!replay_v4::detail::PreparedHandleObservationBridge::snapshot(
               prepared).has_value(),
          "moved-from PREPARED yielded an observation seed");
  require(replay_v4::detail::PreparedHandleObservationBridge::snapshot(
              moved).has_value(),
          "moved PREPARED lost observation seed");
}

}  // namespace

int main() {
  try {
    success_consumes_originals_and_owns_exact_duplicate_set();
    failure_consumes_originals_and_leaks_no_partial_output();
    invalid_inherit_access_and_identity_are_rejected();
    distinct_handle_values_cannot_alias_channel_objects();
    injected_failures_are_atomic_and_consume_transfer();
    moved_result_keeps_heap_stable_attribute_storage();
    observation_bridge_snapshots_only_frozen_artifact_seed();
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
  return 0;
}
