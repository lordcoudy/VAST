#pragma once

#include <array>
#include <cerrno>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <map>
#include <mutex>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>

#include <sys/socket.h>
#include <unistd.h>

namespace vast {

struct CheckpointNativePolicyRequest {
  std::string run_id;
  std::string worker_id;
  std::string input_frame_key;
  std::string trace_id;
  std::uint64_t stream_id = 0;
  std::uint64_t frame_id = 0;
  std::uint64_t transport_pts_ns = 0;
  std::string branch;
  double arrival_ms = 0.0;
  double decision_time_ms = 0.0;
  double feature_observed_timestamp_ms = 0.0;
  std::uint64_t cpu_queue_depth = 0;
  std::uint64_t gpu_queue_depth = 0;
};

struct CheckpointNativePolicyDecision {
  std::string decision_id;
  std::uint64_t decision_seq = 0;
  std::string selected_resource;
  std::string selected_implementation_id;
  std::string emitter_id;
  std::string emitter_sha256;
};

struct CheckpointNativeExecutionBinding {
  std::string resource;
  std::string implementation_id;
  std::string emitter_id;
  std::string emitter_sha256;
};

class CheckpointNativePolicyClient {
 public:
  static constexpr const char* kFdEnvironment = "VAST_CHECKPOINT_POLICY_FD";
  static constexpr std::uint64_t kSchemaVersion = 1;
  static constexpr std::size_t kMaximumMessageBytes = 64U * 1024U;

  explicit CheckpointNativePolicyClient(int fd) : fd_(fd) {
    if (fd_ < 0) {
      throw std::runtime_error("native policy socket FD is invalid");
    }
    int socket_type = 0;
    socklen_t size = sizeof(socket_type);
    if (::getsockopt(fd_, SOL_SOCKET, SO_TYPE, &socket_type, &size) != 0 ||
        size != sizeof(socket_type) || socket_type != SOCK_SEQPACKET) {
      throw std::runtime_error("native policy FD is not a SOCK_SEQPACKET endpoint");
    }
  }

  static CheckpointNativePolicyClient from_environment() {
    const char* raw = std::getenv(kFdEnvironment);
    if (raw == nullptr || std::string(raw).empty()) {
      throw std::runtime_error("missing VAST_CHECKPOINT_POLICY_FD");
    }
    std::size_t consumed = 0;
    int fd = -1;
    try {
      fd = std::stoi(raw, &consumed);
    } catch (const std::exception&) {
      throw std::runtime_error("invalid VAST_CHECKPOINT_POLICY_FD");
    }
    if (consumed != std::string(raw).size() || fd < 0) {
      throw std::runtime_error("invalid VAST_CHECKPOINT_POLICY_FD");
    }
    return CheckpointNativePolicyClient(fd);
  }

  CheckpointNativePolicyClient(const CheckpointNativePolicyClient&) = delete;
  CheckpointNativePolicyClient& operator=(const CheckpointNativePolicyClient&) = delete;

  CheckpointNativePolicyClient(CheckpointNativePolicyClient&& other) noexcept : fd_(other.fd_) {
    other.fd_ = -1;
  }

  CheckpointNativePolicyClient& operator=(CheckpointNativePolicyClient&& other) noexcept {
    if (this != &other) {
      close_fd();
      fd_ = other.fd_;
      other.fd_ = -1;
    }
    return *this;
  }

  ~CheckpointNativePolicyClient() { close_fd(); }

  CheckpointNativePolicyDecision decide(const CheckpointNativePolicyRequest& request) {
    validate_request(request);
    std::ostringstream json;
    json << "{\"arrival_ms\":" << number(request.arrival_ms)
         << ",\"branch\":\"" << escape(request.branch)
         << "\",\"decision_time_ms\":" << number(request.decision_time_ms)
         << ",\"feature_observed_timestamp_ms\":"
         << number(request.feature_observed_timestamp_ms)
         << ",\"frame_id\":" << request.frame_id
         << ",\"input_frame_key\":\"" << escape(request.input_frame_key)
         << "\",\"message_type\":\"decision_request\""
         << ",\"queue_depths\":{\"cpu\":" << request.cpu_queue_depth
         << ",\"gpu\":" << request.gpu_queue_depth << "}"
         << ",\"run_id\":\"" << escape(request.run_id)
         << "\",\"schema_version\":1"
         << ",\"stream_id\":" << request.stream_id
         << ",\"trace_id\":\"" << escape(request.trace_id)
         << "\",\"transport_pts_ns\":" << request.transport_pts_ns
         << ",\"worker_id\":\"" << escape(request.worker_id) << "\"}";
    const FlatObject response = exchange(json.str());
    require_response_fields(
        response,
        "decision_response",
        {
            "schema_version",
            "message_type",
            "decision_id",
            "decision_seq",
            "selected_resource",
            "selected_implementation_id",
            "emitter_id",
            "emitter_sha256",
        });
    CheckpointNativePolicyDecision decision;
    decision.decision_id = string_value(response, "decision_id");
    decision.decision_seq = integer_value(response, "decision_seq");
    decision.selected_resource = string_value(response, "selected_resource");
    decision.selected_implementation_id =
        string_value(response, "selected_implementation_id");
    decision.emitter_id = string_value(response, "emitter_id");
    decision.emitter_sha256 = string_value(response, "emitter_sha256");
    require_stable_text(decision.decision_id, "decision_id");
    if (decision.decision_seq == 0 ||
        (decision.selected_resource != "cpu" && decision.selected_resource != "gpu")) {
      throw std::runtime_error("native policy decision identity or resource is invalid");
    }
    require_stable_text(decision.selected_implementation_id, "selected_implementation_id");
    require_stable_text(decision.emitter_id, "emitter_id");
    require_sha256(decision.emitter_sha256, "emitter_sha256");
    return decision;
  }

  void enter_path(
      const CheckpointNativePolicyRequest& request,
      const CheckpointNativePolicyDecision& decision,
      const CheckpointNativeExecutionBinding& binding,
      const std::string& event_id,
      double timestamp_ms) {
    validate_request(request);
    validate_local_binding(decision, binding);
    require_stable_text(event_id, "event_id");
    require_finite(timestamp_ms, "path timestamp_ms", true);
    if (timestamp_ms < request.decision_time_ms) {
      throw std::runtime_error("native path entry precedes policy decision");
    }
    std::ostringstream json;
    json << "{\"branch\":\"" << escape(request.branch)
         << "\",\"decision_id\":\"" << escape(decision.decision_id)
         << "\",\"emitter_id\":\"" << escape(binding.emitter_id)
         << "\",\"emitter_sha256\":\"" << binding.emitter_sha256
         << "\",\"event_id\":\"" << escape(event_id)
         << "\",\"implementation_id\":\"" << escape(binding.implementation_id)
         << "\",\"input_frame_key\":\"" << escape(request.input_frame_key)
         << "\",\"message_type\":\"path_enter\""
         << ",\"run_id\":\"" << escape(request.run_id)
         << "\",\"schema_version\":1"
         << ",\"selected_resource\":\"" << binding.resource
         << "\",\"timestamp_ms\":" << number(timestamp_ms)
         << ",\"transport_pts_ns\":" << request.transport_pts_ns
         << ",\"worker_id\":\"" << escape(request.worker_id) << "\"}";
    require_ack(exchange(json.str()), "path_ack", decision.decision_id);
  }

  void terminal(
      const CheckpointNativePolicyRequest& request,
      const CheckpointNativePolicyDecision& decision,
      const CheckpointNativeExecutionBinding& binding,
      const std::string& terminal_status,
      double terminal_timestamp_ms,
      double actual_service_ms,
      const std::string& detector,
      const std::string& backend) {
    validate_request(request);
    validate_local_binding(decision, binding);
    if (terminal_status != "completed") {
      throw std::runtime_error("native policy terminal must be completed");
    }
    require_finite(terminal_timestamp_ms, "terminal_timestamp_ms", true);
    require_finite(actual_service_ms, "actual_service_ms", true);
    if (terminal_timestamp_ms < request.decision_time_ms) {
      throw std::runtime_error("native terminal precedes policy decision");
    }
    require_stable_text(detector, "detector");
    require_stable_text(backend, "backend");
    std::ostringstream json;
    json << "{\"actual_service_ms\":" << number(actual_service_ms)
         << ",\"backend\":\"" << escape(backend)
         << "\",\"branch\":\"" << escape(request.branch)
         << "\",\"decision_id\":\"" << escape(decision.decision_id)
         << "\",\"detector\":\"" << escape(detector)
         << "\",\"input_frame_key\":\"" << escape(request.input_frame_key)
         << "\",\"message_type\":\"terminal\""
         << ",\"run_id\":\"" << escape(request.run_id)
         << "\",\"schema_version\":1"
         << ",\"selected_resource\":\"" << binding.resource
         << "\",\"terminal_status\":\"completed\""
         << ",\"terminal_timestamp_ms\":" << number(terminal_timestamp_ms)
         << ",\"transport_pts_ns\":" << request.transport_pts_ns
         << ",\"worker_id\":\"" << escape(request.worker_id) << "\"}";
    require_ack(exchange(json.str()), "terminal_ack", decision.decision_id);
  }

 private:
  enum class ValueKind { kString, kInteger, kBoolean };

  struct FlatValue {
    ValueKind kind = ValueKind::kString;
    std::string text;
    std::uint64_t integer = 0;
    bool boolean = false;
  };

  using FlatObject = std::map<std::string, FlatValue>;

  int fd_ = -1;
  std::mutex mutex_;

  void close_fd() noexcept {
    if (fd_ >= 0) {
      ::close(fd_);
      fd_ = -1;
    }
  }

  static void require_finite(double value, const char* name, bool positive) {
    if (!std::isfinite(value) || value < 0.0 || (positive && value <= 0.0)) {
      throw std::runtime_error(std::string("native policy ") + name + " is invalid");
    }
  }

  static void require_stable_text(const std::string& value, const char* name) {
    if (value.size() < 8 || value.size() > 4096) {
      throw std::runtime_error(std::string("native policy ") + name + " has invalid length");
    }
    for (const unsigned char character : value) {
      if (character < 0x21 || character == 0x7f) {
        throw std::runtime_error(std::string("native policy ") + name + " contains controls");
      }
    }
  }

  static void require_sha256(const std::string& value, const char* name) {
    if (value.size() != 64) {
      throw std::runtime_error(std::string("native policy ") + name + " is not SHA-256");
    }
    for (const char character : value) {
      if (!((character >= '0' && character <= '9') ||
            (character >= 'a' && character <= 'f'))) {
        throw std::runtime_error(std::string("native policy ") + name + " is not SHA-256");
      }
    }
  }

  static void validate_request(const CheckpointNativePolicyRequest& request) {
    require_stable_text(request.run_id, "run_id");
    require_stable_text(request.worker_id, "worker_id");
    require_stable_text(request.input_frame_key, "input_frame_key");
    require_stable_text(request.trace_id, "trace_id");
    require_stable_text(request.branch, "branch");
    require_finite(request.arrival_ms, "arrival_ms", false);
    require_finite(request.decision_time_ms, "decision_time_ms", true);
    require_finite(
        request.feature_observed_timestamp_ms,
        "feature_observed_timestamp_ms",
        true);
    if (request.arrival_ms > request.decision_time_ms ||
        request.feature_observed_timestamp_ms > request.decision_time_ms) {
      throw std::runtime_error("native policy request uses future observations");
    }
  }

  static void validate_local_binding(
      const CheckpointNativePolicyDecision& decision,
      const CheckpointNativeExecutionBinding& binding) {
    if (binding.resource != decision.selected_resource ||
        binding.implementation_id != decision.selected_implementation_id ||
        binding.emitter_id != decision.emitter_id ||
        binding.emitter_sha256 != decision.emitter_sha256) {
      throw std::runtime_error("unselected or relabelled native execution path");
    }
    if (binding.resource != "cpu" && binding.resource != "gpu") {
      throw std::runtime_error("native execution resource is invalid");
    }
    require_stable_text(binding.implementation_id, "implementation_id");
    require_stable_text(binding.emitter_id, "emitter_id");
    require_sha256(binding.emitter_sha256, "emitter_sha256");
  }

  static std::string number(double value) {
    require_finite(value, "JSON number", false);
    std::ostringstream output;
    output << std::setprecision(17) << value;
    return output.str();
  }

  static std::string escape(const std::string& value) {
    std::ostringstream output;
    for (const unsigned char character : value) {
      switch (character) {
        case '\"': output << "\\\""; break;
        case '\\': output << "\\\\"; break;
        case '\b': output << "\\b"; break;
        case '\f': output << "\\f"; break;
        case '\n': output << "\\n"; break;
        case '\r': output << "\\r"; break;
        case '\t': output << "\\t"; break;
        default:
          if (character < 0x20 || character == 0x7f) {
            output << "\\u" << std::hex << std::setw(4) << std::setfill('0')
                   << static_cast<unsigned int>(character) << std::dec;
          } else {
            output << static_cast<char>(character);
          }
      }
    }
    return output.str();
  }

  FlatObject exchange(const std::string& request) {
    if (request.empty() || request.size() >= kMaximumMessageBytes) {
      throw std::runtime_error("native policy request size is invalid");
    }
    std::lock_guard<std::mutex> lock(mutex_);
    ssize_t written = -1;
    do {
      written = ::send(fd_, request.data(), request.size(), 0);
    } while (written < 0 && errno == EINTR);
    if (written < 0 || static_cast<std::size_t>(written) != request.size()) {
      throw std::runtime_error("failed to send native policy request");
    }
    std::array<char, kMaximumMessageBytes> buffer{};
    ssize_t received = -1;
    do {
      received = ::recv(fd_, buffer.data(), buffer.size(), MSG_TRUNC);
    } while (received < 0 && errno == EINTR);
    if (received <= 0 || static_cast<std::size_t>(received) >= buffer.size()) {
      throw std::runtime_error("native policy response is missing or truncated");
    }
    return parse_object(std::string(buffer.data(), static_cast<std::size_t>(received)));
  }

  static void skip_space(const std::string& json, std::size_t& offset) {
    while (offset < json.size() &&
           (json[offset] == ' ' || json[offset] == '\t' ||
            json[offset] == '\r' || json[offset] == '\n')) {
      ++offset;
    }
  }

  static std::string parse_string(const std::string& json, std::size_t& offset) {
    if (offset >= json.size() || json[offset++] != '\"') {
      throw std::runtime_error("native policy response expected a JSON string");
    }
    std::string value;
    while (offset < json.size()) {
      const unsigned char character = json[offset++];
      if (character == '\"') {
        return value;
      }
      if (character != '\\') {
        if (character < 0x20) {
          throw std::runtime_error("native policy response string contains controls");
        }
        value.push_back(static_cast<char>(character));
        continue;
      }
      if (offset >= json.size()) {
        break;
      }
      const char escaped = json[offset++];
      switch (escaped) {
        case '\"': value.push_back('\"'); break;
        case '\\': value.push_back('\\'); break;
        case '/': value.push_back('/'); break;
        case 'b': value.push_back('\b'); break;
        case 'f': value.push_back('\f'); break;
        case 'n': value.push_back('\n'); break;
        case 'r': value.push_back('\r'); break;
        case 't': value.push_back('\t'); break;
        default:
          throw std::runtime_error("native policy response uses an unsupported JSON escape");
      }
    }
    throw std::runtime_error("native policy response has an unterminated JSON string");
  }

  static FlatObject parse_object(const std::string& json) {
    std::size_t offset = 0;
    skip_space(json, offset);
    if (offset >= json.size() || json[offset++] != '{') {
      throw std::runtime_error("native policy response must be a JSON object");
    }
    FlatObject result;
    skip_space(json, offset);
    if (offset < json.size() && json[offset] == '}') {
      ++offset;
    } else {
      while (true) {
        skip_space(json, offset);
        const std::string key = parse_string(json, offset);
        skip_space(json, offset);
        if (offset >= json.size() || json[offset++] != ':') {
          throw std::runtime_error("native policy response JSON object lacks a colon");
        }
        skip_space(json, offset);
        FlatValue value;
        if (offset < json.size() && json[offset] == '\"') {
          value.kind = ValueKind::kString;
          value.text = parse_string(json, offset);
        } else if (json.compare(offset, 4, "true") == 0 ||
                   json.compare(offset, 5, "false") == 0) {
          value.kind = ValueKind::kBoolean;
          value.boolean = json.compare(offset, 4, "true") == 0;
          offset += value.boolean ? 4 : 5;
        } else {
          value.kind = ValueKind::kInteger;
          if (offset >= json.size() || json[offset] < '0' || json[offset] > '9') {
            throw std::runtime_error("native policy response value type is unsupported");
          }
          std::uint64_t integer = 0;
          while (offset < json.size() && json[offset] >= '0' && json[offset] <= '9') {
            const std::uint64_t digit = static_cast<std::uint64_t>(json[offset++] - '0');
            if (integer > (UINT64_MAX - digit) / 10) {
              throw std::runtime_error("native policy response integer overflows uint64");
            }
            integer = integer * 10 + digit;
          }
          value.integer = integer;
        }
        if (!result.emplace(key, std::move(value)).second) {
          throw std::runtime_error("native policy response contains a duplicate field");
        }
        skip_space(json, offset);
        if (offset >= json.size()) {
          throw std::runtime_error("native policy response JSON object is truncated");
        }
        const char delimiter = json[offset++];
        if (delimiter == '}') {
          break;
        }
        if (delimiter != ',') {
          throw std::runtime_error("native policy response JSON object delimiter is invalid");
        }
      }
    }
    skip_space(json, offset);
    if (offset != json.size()) {
      throw std::runtime_error("native policy response has trailing bytes");
    }
    return result;
  }

  static std::string string_value(const FlatObject& object, const std::string& key) {
    const auto iterator = object.find(key);
    if (iterator == object.end() || iterator->second.kind != ValueKind::kString) {
      throw std::runtime_error("native policy response string field is missing: " + key);
    }
    return iterator->second.text;
  }

  static std::uint64_t integer_value(const FlatObject& object, const std::string& key) {
    const auto iterator = object.find(key);
    if (iterator == object.end() || iterator->second.kind != ValueKind::kInteger) {
      throw std::runtime_error("native policy response integer field is missing: " + key);
    }
    return iterator->second.integer;
  }

  static bool boolean_value(const FlatObject& object, const std::string& key) {
    const auto iterator = object.find(key);
    if (iterator == object.end() || iterator->second.kind != ValueKind::kBoolean) {
      throw std::runtime_error("native policy response boolean field is missing: " + key);
    }
    return iterator->second.boolean;
  }

  static void require_response_fields(
      const FlatObject& object,
      const std::string& message_type,
      const std::set<std::string>& expected) {
    const auto kind = object.find("message_type");
    if (kind != object.end() && kind->second.kind == ValueKind::kString &&
        kind->second.text == "policy_error") {
      const std::set<std::string> error_fields = {
          "schema_version", "message_type", "error"};
      std::set<std::string> observed;
      for (const auto& entry : object) observed.insert(entry.first);
      if (observed != error_fields || integer_value(object, "schema_version") != kSchemaVersion) {
        throw std::runtime_error("malformed native policy error response");
      }
      throw std::runtime_error("native policy service rejected execution: " +
                               string_value(object, "error"));
    }
    std::set<std::string> observed;
    for (const auto& entry : object) observed.insert(entry.first);
    if (observed != expected || integer_value(object, "schema_version") != kSchemaVersion ||
        string_value(object, "message_type") != message_type) {
      throw std::runtime_error("native policy response fields or identity have drifted");
    }
  }

  static void require_ack(
      const FlatObject& response,
      const std::string& message_type,
      const std::string& decision_id) {
    require_response_fields(
        response,
        message_type,
        {"schema_version", "message_type", "decision_id", "accepted"});
    if (string_value(response, "decision_id") != decision_id ||
        !boolean_value(response, "accepted")) {
      throw std::runtime_error("native policy acknowledgement did not accept the exact decision");
    }
  }
};

}  // namespace vast
