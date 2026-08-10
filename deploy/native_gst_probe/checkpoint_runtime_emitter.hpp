#pragma once

#include <cerrno>
#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <mutex>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include <unistd.h>

namespace vast {

class CheckpointRuntimeEmitter {
 public:
  static constexpr int kProtocolVersion = 1;
  static constexpr int kProtocolVersionWithAdmission = 2;
  static constexpr int kProtocolVersionWithBranchTerminal = 3;

  static CheckpointRuntimeEmitter from_environment() {
    return CheckpointRuntimeEmitter(
        required_env("VAST_CHECKPOINT_EVENT_FD"),
        required_env("VAST_CHECKPOINT_WORKER_ID"),
        required_env("VAST_CHECKPOINT_RUN_ID"),
        required_env("VAST_CHECKPOINT_TOPOLOGY_KIND"),
        required_env("VAST_CHECKPOINT_STREAM_ID"));
  }

  static std::unique_ptr<CheckpointRuntimeEmitter> make_from_environment() {
    return std::unique_ptr<CheckpointRuntimeEmitter>(new CheckpointRuntimeEmitter(
        required_env("VAST_CHECKPOINT_EVENT_FD"),
        required_env("VAST_CHECKPOINT_WORKER_ID"),
        required_env("VAST_CHECKPOINT_RUN_ID"),
        required_env("VAST_CHECKPOINT_TOPOLOGY_KIND"),
        required_env("VAST_CHECKPOINT_STREAM_ID")));
  }

  CheckpointRuntimeEmitter(
      std::string event_fd,
      std::string worker_id,
      std::string run_id,
      std::string topology_kind,
      std::string stream_id)
      : event_fd_(parse_nonnegative_integer(event_fd, "VAST_CHECKPOINT_EVENT_FD")),
        worker_id_(nonempty(std::move(worker_id), "worker_id")),
        run_id_(nonempty(std::move(run_id), "run_id")),
        topology_kind_(nonempty(std::move(topology_kind), "topology_kind")),
        stream_id_(parse_nonnegative_integer(stream_id, "VAST_CHECKPOINT_STREAM_ID")) {}

  void emit(
      const std::string& trace_id,
      std::uint64_t frame_id,
      const std::string& input_frame_key,
      const std::string& event_kind,
      const std::string& stage,
      const std::string& branch_id,
      const std::string& execution_id,
      const std::vector<std::string>& parent_execution_ids,
      std::uint64_t timestamp_ms) {
    emit_impl(
        kProtocolVersion,
        trace_id,
        frame_id,
        input_frame_key,
        event_kind,
        stage,
        branch_id,
        execution_id,
        parent_execution_ids,
        timestamp_ms,
        "",
        "",
        "",
        0,
        "",
        "");
  }

  void emit_with_admission(
      const std::string& trace_id,
      std::uint64_t frame_id,
      const std::string& input_frame_key,
      const std::string& event_kind,
      const std::string& stage,
      const std::string& branch_id,
      const std::string& execution_id,
      const std::vector<std::string>& parent_execution_ids,
      std::uint64_t timestamp_ms,
      const std::string& admission_id,
      const std::string& payload_sha256) {
    if (!valid_sha256(payload_sha256)) {
      throw std::runtime_error("checkpoint admission payload SHA-256 must be lowercase hexadecimal");
    }
    emit_impl(
        kProtocolVersionWithAdmission,
        trace_id,
        frame_id,
        input_frame_key,
        event_kind,
        stage,
        branch_id,
        execution_id,
        parent_execution_ids,
        timestamp_ms,
        nonempty_copy(admission_id, "admission_id"),
        payload_sha256,
        "",
        0,
        "",
        "");
  }

  void emit_branch_terminal_with_admission(
      const std::string& trace_id,
      std::uint64_t frame_id,
      const std::string& input_frame_key,
      const std::string& event_kind,
      const std::string& stage,
      const std::string& branch_id,
      const std::string& execution_id,
      const std::vector<std::string>& parent_execution_ids,
      std::uint64_t timestamp_ms,
      const std::string& admission_id,
      const std::string& payload_sha256,
      const std::string& terminal_reason,
      std::uint64_t objects,
      const std::string& detector,
      const std::string& backend) {
    if (event_kind != "branch_complete" && event_kind != "branch_drop") {
      throw std::runtime_error("checkpoint terminal emitter requires branch_complete or branch_drop");
    }
    if (event_kind == "branch_drop" && objects != 0) {
      throw std::runtime_error("checkpoint branch drop must not report accepted objects");
    }
    if (!valid_sha256(payload_sha256)) {
      throw std::runtime_error("checkpoint admission payload SHA-256 must be lowercase hexadecimal");
    }
    emit_impl(
        kProtocolVersionWithBranchTerminal,
        trace_id,
        frame_id,
        input_frame_key,
        event_kind,
        stage,
        branch_id,
        execution_id,
        parent_execution_ids,
        timestamp_ms,
        nonempty_copy(admission_id, "admission_id"),
        payload_sha256,
        nonempty_copy(terminal_reason, "terminal_reason"),
        objects,
        nonempty_copy(detector, "detector"),
        nonempty_copy(backend, "backend"));
  }

  std::uint64_t sequence() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return sequence_;
  }

 private:
  int event_fd_ = -1;
  std::string worker_id_;
  std::string run_id_;
  std::string topology_kind_;
  int stream_id_ = 0;
  mutable std::mutex mutex_;
  std::uint64_t sequence_ = 0;
  std::uint64_t last_timestamp_ms_ = 0;

  void emit_impl(
      int protocol_version,
      const std::string& trace_id,
      std::uint64_t frame_id,
      const std::string& input_frame_key,
      const std::string& event_kind,
      const std::string& stage,
      const std::string& branch_id,
      const std::string& execution_id,
      const std::vector<std::string>& parent_execution_ids,
      std::uint64_t timestamp_ms,
      const std::string& admission_id,
      const std::string& payload_sha256,
      const std::string& terminal_reason,
      std::uint64_t objects,
      const std::string& detector,
      const std::string& backend) {
    std::lock_guard<std::mutex> lock(mutex_);
    const std::uint64_t sequence = ++sequence_;
    // Callbacks can sample wall time before competing for this lock. Bind the
    // event timestamp to the serialized sequence without moving it backwards.
    timestamp_ms = std::max(timestamp_ms, last_timestamp_ms_);
    last_timestamp_ms_ = timestamp_ms;
    std::ostringstream row;
    row << "{\"protocol_version\":" << protocol_version
        << ",\"worker_id\":\"" << escape(worker_id_)
        << "\",\"sequence\":" << sequence
        << ",\"run_id\":\"" << escape(run_id_)
        << "\",\"trace_id\":\"" << escape(nonempty_copy(trace_id, "trace_id"))
        << "\",\"stream_id\":" << stream_id_
        << ",\"frame_id\":" << frame_id
        << ",\"input_frame_key\":\"" << escape(nonempty_copy(input_frame_key, "input_frame_key"))
        << "\",\"topology_kind\":\"" << escape(topology_kind_)
        << "\",\"event_kind\":\"" << escape(nonempty_copy(event_kind, "event_kind"))
        << "\",\"stage\":\"" << escape(nonempty_copy(stage, "stage"))
        << "\",\"branch_id\":\"" << escape(nonempty_copy(branch_id, "branch_id"))
        << "\",\"execution_id\":\"" << escape(nonempty_copy(execution_id, "execution_id"))
        << "\",\"parent_execution_ids\":[";
    for (std::size_t index = 0; index < parent_execution_ids.size(); ++index) {
      if (index != 0) {
        row << ',';
      }
      row << '\"' << escape(nonempty_copy(parent_execution_ids[index], "parent_execution_id")) << '\"';
    }
    row << ']';
    if (protocol_version >= kProtocolVersionWithAdmission) {
      row << ",\"admission_id\":\"" << escape(admission_id)
          << "\",\"payload_sha256\":\"" << payload_sha256 << '\"';
    }
    if (protocol_version == kProtocolVersionWithBranchTerminal) {
      row << ",\"terminal_reason\":\"" << escape(terminal_reason)
          << "\",\"objects\":" << objects
          << ",\"detector\":\"" << escape(detector)
          << "\",\"backend\":\"" << escape(backend) << '\"';
    }
    row << ",\"timestamp_ms\":" << timestamp_ms << "}\n";
    write_all(row.str());
  }

  static std::string required_env(const char* name) {
    const char* value = std::getenv(name);
    if (value == nullptr || std::string(value).empty()) {
      throw std::runtime_error(std::string("missing checkpoint runtime environment variable: ") + name);
    }
    return value;
  }

  static std::string nonempty(std::string value, const char* name) {
    if (value.empty()) {
      throw std::runtime_error(std::string("empty checkpoint runtime field: ") + name);
    }
    return value;
  }

  static const std::string& nonempty_copy(const std::string& value, const char* name) {
    if (value.empty()) {
      throw std::runtime_error(std::string("empty checkpoint runtime field: ") + name);
    }
    return value;
  }

  static int parse_nonnegative_integer(const std::string& raw, const char* name) {
    std::size_t consumed = 0;
    int value = 0;
    try {
      value = std::stoi(raw, &consumed);
    } catch (const std::exception&) {
      throw std::runtime_error(std::string("invalid checkpoint runtime integer: ") + name);
    }
    if (consumed != raw.size() || value < 0) {
      throw std::runtime_error(std::string("invalid checkpoint runtime integer: ") + name);
    }
    return value;
  }

  static std::string escape(const std::string& value) {
    std::ostringstream escaped;
    for (const unsigned char character : value) {
      switch (character) {
        case '\"': escaped << "\\\""; break;
        case '\\': escaped << "\\\\"; break;
        case '\b': escaped << "\\b"; break;
        case '\f': escaped << "\\f"; break;
        case '\n': escaped << "\\n"; break;
        case '\r': escaped << "\\r"; break;
        case '\t': escaped << "\\t"; break;
        default:
          if (character < 0x20) {
            const char* digits = "0123456789abcdef";
            escaped << "\\u00" << digits[(character >> 4) & 0x0f] << digits[character & 0x0f];
          } else {
            escaped << static_cast<char>(character);
          }
      }
    }
    return escaped.str();
  }

  static bool valid_sha256(const std::string& value) {
    return value.size() == 64 && std::all_of(value.begin(), value.end(), [](unsigned char character) {
      return (character >= '0' && character <= '9') || (character >= 'a' && character <= 'f');
    });
  }

  void write_all(const std::string& payload) const {
    std::size_t offset = 0;
    while (offset < payload.size()) {
      const ssize_t written = ::write(event_fd_, payload.data() + offset, payload.size() - offset);
      if (written < 0 && errno == EINTR) {
        continue;
      }
      if (written <= 0) {
        throw std::runtime_error("failed to write checkpoint runtime event pipe");
      }
      offset += static_cast<std::size_t>(written);
    }
  }
};

}  // namespace vast
