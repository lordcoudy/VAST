#pragma once

#include "checkpoint_native_policy_client.hpp"

#include <glib.h>

#include <array>
#include <cerrno>
#include <cstdint>
#include <cstring>
#include <fcntl.h>
#include <map>
#include <mutex>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <linux/memfd.h>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <sys/un.h>
#include <unistd.h>

namespace vast {

struct CheckpointAnalyticsExecutionRequest {
  std::string request_id;
  std::string run_id;
  std::string arm_id;
  std::string worker_id;
  std::string input_frame_key;
  std::uint64_t stream_id = 0;
  std::uint64_t frame_id = 0;
  std::uint64_t transport_pts_ns = 0;
  std::string branch;
  CheckpointNativePolicyDecision decision;
  std::uint64_t deadline_monotonic_ns = 0;
  std::string format;
  std::uint64_t width = 0;
  std::uint64_t height = 0;
  std::uint64_t stride = 0;
  std::string preprocessing_contract_sha256;
  std::string raw_input_sha256;
};

struct CheckpointCudaTransferInterval {
  std::string direction;
  std::uint64_t host_start_monotonic_ns = 0;
  std::uint64_t host_end_monotonic_ns = 0;
  std::uint64_t device_elapsed_ns = 0;
  std::uint64_t bytes = 0;
  std::string device_id;
  std::string timing_source;
};

struct CheckpointAnalyticsExecutionResult {
  std::string request_id;
  std::string decision_id;
  std::uint64_t decision_seq = 0;
  std::string branch;
  std::string selected_resource;
  std::string terminal_status;
  std::string terminal_reason;
  std::uint64_t objects = 0;
  std::string detector;
  std::string backend;
  std::string worker_id;
  std::string engine;
  std::string worker_image_id;
  std::string worker_implementation_sha256;
  std::string runtime_name;
  std::string runtime_version;
  std::string device_api;
  std::string device_id;
  std::string native_inference_api;
  std::string execution_path;
  std::string model_id;
  std::string source_model_sha256;
  std::string model_artifact_sha256;
  std::string preprocessing_contract_sha256;
  std::string output_contract_sha256;
  std::string raw_input_sha256;
  std::string input_sha256;
  std::string output_sha256;
  std::uint64_t output_bytes = 0;
  std::uint64_t worker_received_monotonic_ns = 0;
  std::uint64_t inference_started_monotonic_ns = 0;
  std::uint64_t inference_finished_monotonic_ns = 0;
  std::uint64_t worker_completed_monotonic_ns = 0;
  std::uint64_t inference_latency_ns = 0;
  std::uint64_t process_cpu_time_ns = 0;
  std::uint64_t rss_before_bytes = 0;
  std::uint64_t rss_after_bytes = 0;
  std::uint64_t accelerator_memory_bytes = 0;
  std::uint64_t cuda_h2d_bytes = 0;
  std::uint64_t cuda_d2h_bytes = 0;
  std::vector<CheckpointCudaTransferInterval> cuda_transfer_intervals;
};

class CheckpointAnalyticsExecutionClient {
 public:
  static constexpr const char* kFdEnvironment = "VAST_CHECKPOINT_ANALYTICS_EXECUTION_FD";
  static constexpr const char* kSocketEnvironment = "VAST_CHECKPOINT_ANALYTICS_EXECUTION_SOCKET";
  static constexpr std::uint64_t kSchemaVersion = 1;
  static constexpr std::size_t kMaximumMessageBytes = 64U * 1024U;
  static constexpr std::size_t kMaximumPayloadBytes = 67'108'864U;
  static constexpr const char* kProtocolIdentitySha256 =
      "3bed4ad0e5cd46b01649b054fa520c0f728a1ceeb14502fb9fe1f0f8f5941eff";

  static std::string cuda_transfer_native_event_material(
      const CheckpointAnalyticsExecutionRequest& request,
      const CheckpointAnalyticsExecutionResult& result,
      const std::string& execution_id,
      const CheckpointCudaTransferInterval& interval);

  explicit CheckpointAnalyticsExecutionClient(int fd) : fd_(fd) {
    if (fd_ < 0) {
      throw std::runtime_error("analytics execution socket FD is invalid");
    }
    int socket_type = 0;
    socklen_t size = sizeof(socket_type);
    if (::getsockopt(fd_, SOL_SOCKET, SO_TYPE, &socket_type, &size) != 0 ||
        size != sizeof(socket_type) || socket_type != SOCK_SEQPACKET) {
      throw std::runtime_error("analytics execution FD is not a SOCK_SEQPACKET endpoint");
    }
  }

  static CheckpointAnalyticsExecutionClient from_environment() {
    const char* raw = std::getenv(kFdEnvironment);
    const char* raw_socket = std::getenv(kSocketEnvironment);
    const bool has_fd = raw != nullptr && !std::string(raw).empty();
    const bool has_socket = raw_socket != nullptr && !std::string(raw_socket).empty();
    if (has_fd == has_socket) {
      throw std::runtime_error(
          "analytics execution requires exactly one FD or socket path");
    }
    if (has_socket) {
      const std::string path(raw_socket);
      sockaddr_un address{};
      require(
          !path.empty() && path.front() == '/' &&
              path.size() < sizeof(address.sun_path) &&
              path.find('\0') == std::string::npos,
          "analytics execution socket path is invalid");
      address.sun_family = AF_UNIX;
      std::memcpy(address.sun_path, path.c_str(), path.size() + 1);
      const int socket_fd = ::socket(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0);
      if (socket_fd < 0) {
        throw std::runtime_error("failed to create analytics execution socket");
      }
      if (::connect(
              socket_fd,
              reinterpret_cast<const sockaddr*>(&address),
              static_cast<socklen_t>(offsetof(sockaddr_un, sun_path) + path.size() + 1)) != 0) {
        ::close(socket_fd);
        throw std::runtime_error("failed to connect analytics execution sidecar");
      }
      return CheckpointAnalyticsExecutionClient(socket_fd);
    }
    std::size_t consumed = 0;
    int fd = -1;
    try {
      fd = std::stoi(raw, &consumed);
    } catch (const std::exception&) {
      throw std::runtime_error("invalid VAST_CHECKPOINT_ANALYTICS_EXECUTION_FD");
    }
    if (consumed != std::string(raw).size() || fd < 0) {
      throw std::runtime_error("invalid VAST_CHECKPOINT_ANALYTICS_EXECUTION_FD");
    }
    return CheckpointAnalyticsExecutionClient(fd);
  }

  CheckpointAnalyticsExecutionClient(const CheckpointAnalyticsExecutionClient&) = delete;
  CheckpointAnalyticsExecutionClient& operator=(const CheckpointAnalyticsExecutionClient&) = delete;

  CheckpointAnalyticsExecutionClient(CheckpointAnalyticsExecutionClient&& other) noexcept
      : fd_(other.fd_) {
    other.fd_ = -1;
  }

  CheckpointAnalyticsExecutionClient& operator=(CheckpointAnalyticsExecutionClient&& other) noexcept {
    if (this != &other) {
      close_fd();
      fd_ = other.fd_;
      other.fd_ = -1;
    }
    return *this;
  }

  ~CheckpointAnalyticsExecutionClient() { close_fd(); }

  CheckpointAnalyticsExecutionResult execute(
      const CheckpointAnalyticsExecutionRequest& request,
      const std::uint8_t* payload,
      std::size_t payload_size) {
    validate_request(request, payload, payload_size);
    const std::vector<std::uint8_t> snapshot(payload, payload + payload_size);
    const std::string snapshot_sha256 = sha256(snapshot);
    require(
        snapshot_sha256 == request.raw_input_sha256,
        "analytics execution payload SHA-256 differs from raw_input_sha256");
    std::ostringstream json;
    json << "{\"arm_id\":\"" << escape(request.arm_id)
         << "\",\"decision\":{\"decision_id\":\"" << escape(request.decision.decision_id)
         << "\",\"decision_seq\":" << request.decision.decision_seq
         << ",\"emitter_id\":\"" << escape(request.decision.emitter_id)
         << "\",\"emitter_sha256\":\"" << request.decision.emitter_sha256
         << "\",\"selected_implementation_id\":\""
         << escape(request.decision.selected_implementation_id)
         << "\",\"selected_resource\":\"" << request.decision.selected_resource
         << "\"},\"deadline_monotonic_ns\":" << request.deadline_monotonic_ns
         << ",\"frame\":{\"branch\":\"" << escape(request.branch)
         << "\",\"frame_id\":" << request.frame_id
         << ",\"input_frame_key\":\"" << escape(request.input_frame_key)
         << "\",\"stream_id\":" << request.stream_id
         << ",\"transport_pts_ns\":" << request.transport_pts_ns
         << "},\"gstreamer_worker_id\":\"" << escape(request.worker_id)
         << "\",\"message_type\":\"analytics_execute\",\"payload\":{\"byte_length\":"
         << snapshot.size() << ",\"format\":\"" << request.format
         << "\",\"height\":" << request.height
         << ",\"kind\":\"raw_gstreamer_frame\",\"preprocessing_contract_sha256\":\""
         << request.preprocessing_contract_sha256 << "\",\"sha256\":\""
         << snapshot_sha256 << "\",\"stride\":" << request.stride
         << ",\"width\":" << request.width << "},\"request_id\":\""
         << escape(request.request_id) << "\",\"run_id\":\"" << escape(request.run_id)
         << "\",\"schema_version\":1}";
    const int payload_fd = create_sealed_memfd(snapshot.data(), snapshot.size());
    FlatObject response;
    try {
      response = exchange(json.str(), payload_fd);
    } catch (...) {
      ::close(payload_fd);
      throw;
    }
    ::close(payload_fd);
    return validate_response(response, request);
  }

 private:
  enum class ValueKind { kString, kInteger, kObject, kArray };

  struct FlatValue {
    ValueKind kind = ValueKind::kString;
    std::string text;
    std::uint64_t integer = 0;
    std::map<std::string, FlatValue> object;
    std::vector<FlatValue> array;
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

  static void require(bool condition, const std::string& message) {
    if (!condition) {
      throw std::runtime_error(message);
    }
  }

  static void require_text(const std::string& value, const char* name) {
    if (value.empty() || value.size() > 4096) {
      throw std::runtime_error(std::string("analytics execution ") + name + " has invalid length");
    }
    for (const unsigned char character : value) {
      if (character < 0x21 || character == 0x7f) {
        throw std::runtime_error(std::string("analytics execution ") + name + " contains controls");
      }
    }
  }

  static void require_sha256(const std::string& value, const char* name) {
    if (value.size() != 64 ||
        value.find_first_not_of("0123456789abcdef") != std::string::npos) {
      throw std::runtime_error(std::string("analytics execution ") + name + " is not SHA-256");
    }
  }

  static std::string sha256(const std::vector<std::uint8_t>& value) {
    gchar* digest = g_compute_checksum_for_data(
        G_CHECKSUM_SHA256,
        reinterpret_cast<const guchar*>(value.data()),
        static_cast<gsize>(value.size()));
    if (digest == nullptr) {
      throw std::runtime_error("failed to compute analytics execution payload SHA-256");
    }
    std::string result(digest);
    g_free(digest);
    return result;
  }

  static void validate_request(
      const CheckpointAnalyticsExecutionRequest& request,
      const std::uint8_t* payload,
      std::size_t payload_size) {
    require(payload != nullptr && payload_size > 0, "analytics execution payload is empty");
    require(
        payload_size <= kMaximumPayloadBytes,
        "analytics execution payload exceeds bounded maximum");
    for (const auto& field : {
             std::make_pair(&request.request_id, "request_id"),
             std::make_pair(&request.run_id, "run_id"),
             std::make_pair(&request.arm_id, "arm_id"),
             std::make_pair(&request.worker_id, "worker_id"),
             std::make_pair(&request.input_frame_key, "input_frame_key"),
             std::make_pair(&request.branch, "branch"),
             std::make_pair(&request.decision.decision_id, "decision_id"),
             std::make_pair(&request.decision.selected_implementation_id, "implementation_id"),
             std::make_pair(&request.decision.emitter_id, "emitter_id"),
         }) {
      require_text(*field.first, field.second);
    }
    require(
        request.decision.decision_seq > 0 &&
            (request.decision.selected_resource == "cpu" ||
             request.decision.selected_resource == "gpu"),
        "analytics execution decision identity/resource is invalid");
    require_sha256(request.decision.emitter_sha256, "emitter_sha256");
    require_sha256(request.preprocessing_contract_sha256, "preprocessing_contract_sha256");
    require_sha256(request.raw_input_sha256, "raw_input_sha256");
    require(
        request.deadline_monotonic_ns > 0 &&
            (request.format == "BGR" || request.format == "RGB") &&
            request.width > 0 && request.height > 0 && request.stride >= request.width * 3 &&
            request.height <= UINT64_MAX / request.stride &&
            request.height * request.stride == payload_size,
        "analytics execution raw frame descriptor is invalid");
  }

  static int create_sealed_memfd(const std::uint8_t* payload, std::size_t size) {
    const int fd = static_cast<int>(
        ::syscall(SYS_memfd_create, "vast-gstreamer-frame", MFD_CLOEXEC | MFD_ALLOW_SEALING));
    if (fd < 0) {
      throw std::runtime_error("failed to create analytics input memfd");
    }
    std::size_t offset = 0;
    while (offset < size) {
      const ssize_t written = ::write(fd, payload + offset, size - offset);
      if (written < 0 && errno == EINTR) {
        continue;
      }
      if (written <= 0) {
        ::close(fd);
        throw std::runtime_error("failed to populate analytics input memfd");
      }
      offset += static_cast<std::size_t>(written);
    }
    const int seals = F_SEAL_SEAL | F_SEAL_SHRINK | F_SEAL_GROW | F_SEAL_WRITE;
    if (::fcntl(fd, F_ADD_SEALS, seals) != 0) {
      ::close(fd);
      throw std::runtime_error("failed to seal analytics input memfd");
    }
    return fd;
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
            throw std::runtime_error("analytics execution request contains unsupported controls");
          }
          output << static_cast<char>(character);
      }
    }
    return output.str();
  }

  FlatObject exchange(const std::string& request, int payload_fd) {
    require(!request.empty() && request.size() < kMaximumMessageBytes,
            "analytics execution request size is invalid");
    std::lock_guard<std::mutex> lock(mutex_);
    std::array<char, CMSG_SPACE(sizeof(int))> control{};
    iovec vector{};
    vector.iov_base = const_cast<char*>(request.data());
    vector.iov_len = request.size();
    msghdr message{};
    message.msg_iov = &vector;
    message.msg_iovlen = 1;
    message.msg_control = control.data();
    message.msg_controllen = control.size();
    cmsghdr* header = CMSG_FIRSTHDR(&message);
    header->cmsg_level = SOL_SOCKET;
    header->cmsg_type = SCM_RIGHTS;
    header->cmsg_len = CMSG_LEN(sizeof(int));
    std::memcpy(CMSG_DATA(header), &payload_fd, sizeof(payload_fd));
    ssize_t written = -1;
    do {
      written = ::sendmsg(fd_, &message, MSG_NOSIGNAL);
    } while (written < 0 && errno == EINTR);
    if (written < 0 || static_cast<std::size_t>(written) != request.size()) {
      throw std::runtime_error("failed to send analytics execution request");
    }
    std::array<char, kMaximumMessageBytes> buffer{};
    ssize_t received = -1;
    do {
      received = ::recv(fd_, buffer.data(), buffer.size(), MSG_TRUNC);
    } while (received < 0 && errno == EINTR);
    if (received <= 0 || static_cast<std::size_t>(received) >= buffer.size()) {
      throw std::runtime_error("analytics execution response is missing or truncated");
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
    require(offset < json.size() && json[offset++] == '\"',
            "analytics execution response expected a JSON string");
    std::string value;
    while (offset < json.size()) {
      const unsigned char character = json[offset++];
      if (character == '\"') return value;
      if (character != '\\') {
        require(character >= 0x20, "analytics execution response string contains controls");
        value.push_back(static_cast<char>(character));
        continue;
      }
      require(offset < json.size(), "analytics execution response string escape is truncated");
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
        default: throw std::runtime_error("analytics execution response uses unsupported JSON escape");
      }
    }
    throw std::runtime_error("analytics execution response has an unterminated string");
  }

  static FlatValue parse_value(
      const std::string& json,
      std::size_t& offset,
      std::size_t depth);

  static FlatObject parse_nested_object(
      const std::string& json,
      std::size_t& offset,
      std::size_t depth) {
    require(
        depth <= 5 && offset < json.size() && json[offset++] == '{',
        "analytics execution response object nesting is invalid");
    FlatObject result;
    skip_space(json, offset);
    if (offset < json.size() && json[offset] == '}') {
      ++offset;
    } else {
      while (true) {
        skip_space(json, offset);
        const std::string key = parse_string(json, offset);
        skip_space(json, offset);
        require(offset < json.size() && json[offset++] == ':',
                "analytics execution response object lacks a colon");
        skip_space(json, offset);
        FlatValue value = parse_value(json, offset, depth + 1);
        require(result.emplace(key, std::move(value)).second,
                "analytics execution response contains a duplicate field");
        skip_space(json, offset);
        require(offset < json.size(), "analytics execution response object is truncated");
        const char delimiter = json[offset++];
        if (delimiter == '}') break;
        require(delimiter == ',', "analytics execution response object delimiter is invalid");
      }
    }
    return result;
  }

  static std::vector<FlatValue> parse_array(
      const std::string& json,
      std::size_t& offset,
      std::size_t depth) {
    require(
        depth <= 5 && offset < json.size() && json[offset++] == '[',
        "analytics execution response array nesting is invalid");
    std::vector<FlatValue> result;
    skip_space(json, offset);
    if (offset < json.size() && json[offset] == ']') {
      ++offset;
      return result;
    }
    while (true) {
      skip_space(json, offset);
      require(
          result.size() < 16,
          "analytics execution response array exceeds its bounded cardinality");
      result.push_back(parse_value(json, offset, depth + 1));
      skip_space(json, offset);
      require(offset < json.size(), "analytics execution response array is truncated");
      const char delimiter = json[offset++];
      if (delimiter == ']') break;
      require(delimiter == ',', "analytics execution response array delimiter is invalid");
    }
    return result;
  }

  static FlatObject parse_object(const std::string& json) {
    std::size_t offset = 0;
    skip_space(json, offset);
    FlatObject result = parse_nested_object(json, offset, 1);
    skip_space(json, offset);
    require(offset == json.size(), "analytics execution response has trailing bytes");
    return result;
  }

  static std::string string_value(const FlatObject& object, const char* key) {
    const auto iterator = object.find(key);
    require(iterator != object.end() && iterator->second.kind == ValueKind::kString,
            std::string("analytics execution response string field is missing: ") + key);
    return iterator->second.text;
  }

  static std::uint64_t integer_value(const FlatObject& object, const char* key) {
    const auto iterator = object.find(key);
    require(iterator != object.end() && iterator->second.kind == ValueKind::kInteger,
            std::string("analytics execution response integer field is missing: ") + key);
    return iterator->second.integer;
  }

  static const FlatObject& object_value(const FlatObject& object, const char* key) {
    const auto iterator = object.find(key);
    require(iterator != object.end() && iterator->second.kind == ValueKind::kObject,
            std::string("analytics execution response object field is missing: ") + key);
    return iterator->second.object;
  }

  static const std::vector<FlatValue>& array_value(
      const FlatObject& object,
      const char* key) {
    const auto iterator = object.find(key);
    require(iterator != object.end() && iterator->second.kind == ValueKind::kArray,
            std::string("analytics execution response array field is missing: ") + key);
    return iterator->second.array;
  }

  static CheckpointAnalyticsExecutionResult validate_response(
      const FlatObject& response,
      const CheckpointAnalyticsExecutionRequest& request) {
    const std::set<std::string> expected = {
        "schema_version", "message_type", "request_id", "decision_id", "decision_seq",
        "branch", "selected_resource", "terminal_status", "terminal_reason", "objects",
        "detector", "backend", "worker_id", "engine", "worker_image_id",
        "worker_implementation_sha256", "runtime_name", "runtime_version", "device_api",
        "device_id", "native_inference_api", "execution_path", "model_id",
        "source_model_sha256", "model_artifact_sha256", "preprocessing_contract_sha256",
        "output_contract_sha256", "raw_input_sha256", "input_sha256", "output_sha256",
        "output_bytes", "worker_received_monotonic_ns", "inference_started_monotonic_ns",
        "inference_finished_monotonic_ns", "worker_completed_monotonic_ns",
        "inference_latency_ns", "resource",
    };
    std::set<std::string> observed;
    for (const auto& entry : response) observed.insert(entry.first);
    require(observed == expected && integer_value(response, "schema_version") == kSchemaVersion &&
                string_value(response, "message_type") == "analytics_execute_response",
            "analytics execution response fields or identity drifted");
    CheckpointAnalyticsExecutionResult result;
#define VAST_READ_TEXT(field) result.field = string_value(response, #field)
    VAST_READ_TEXT(request_id);
    VAST_READ_TEXT(decision_id);
    result.decision_seq = integer_value(response, "decision_seq");
    VAST_READ_TEXT(branch);
    VAST_READ_TEXT(selected_resource);
    VAST_READ_TEXT(terminal_status);
    VAST_READ_TEXT(terminal_reason);
    result.objects = integer_value(response, "objects");
    VAST_READ_TEXT(detector);
    VAST_READ_TEXT(backend);
    VAST_READ_TEXT(worker_id);
    VAST_READ_TEXT(engine);
    VAST_READ_TEXT(worker_image_id);
    VAST_READ_TEXT(worker_implementation_sha256);
    VAST_READ_TEXT(runtime_name);
    VAST_READ_TEXT(runtime_version);
    VAST_READ_TEXT(device_api);
    VAST_READ_TEXT(device_id);
    VAST_READ_TEXT(native_inference_api);
    VAST_READ_TEXT(execution_path);
    VAST_READ_TEXT(model_id);
    VAST_READ_TEXT(source_model_sha256);
    VAST_READ_TEXT(model_artifact_sha256);
    VAST_READ_TEXT(preprocessing_contract_sha256);
    VAST_READ_TEXT(output_contract_sha256);
    VAST_READ_TEXT(raw_input_sha256);
    VAST_READ_TEXT(input_sha256);
    VAST_READ_TEXT(output_sha256);
#undef VAST_READ_TEXT
    result.output_bytes = integer_value(response, "output_bytes");
    result.worker_received_monotonic_ns = integer_value(response, "worker_received_monotonic_ns");
    result.inference_started_monotonic_ns = integer_value(response, "inference_started_monotonic_ns");
    result.inference_finished_monotonic_ns = integer_value(response, "inference_finished_monotonic_ns");
    result.worker_completed_monotonic_ns = integer_value(response, "worker_completed_monotonic_ns");
    result.inference_latency_ns = integer_value(response, "inference_latency_ns");
    const FlatObject& resource = object_value(response, "resource");
    const std::set<std::string> expected_resource_fields = {
        "process_cpu_time_ns",
        "rss_before_bytes",
        "rss_after_bytes",
        "accelerator_memory_bytes",
        "cuda_h2d_bytes",
        "cuda_d2h_bytes",
        "cuda_transfer_intervals",
    };
    std::set<std::string> observed_resource_fields;
    for (const auto& entry : resource) observed_resource_fields.insert(entry.first);
    require(
        observed_resource_fields == expected_resource_fields,
        "analytics execution response resource fields drifted");
    result.process_cpu_time_ns = integer_value(resource, "process_cpu_time_ns");
    result.rss_before_bytes = integer_value(resource, "rss_before_bytes");
    result.rss_after_bytes = integer_value(resource, "rss_after_bytes");
    result.accelerator_memory_bytes = integer_value(resource, "accelerator_memory_bytes");
    result.cuda_h2d_bytes = integer_value(resource, "cuda_h2d_bytes");
    result.cuda_d2h_bytes = integer_value(resource, "cuda_d2h_bytes");
    require(
        result.request_id == request.request_id &&
            result.decision_id == request.decision.decision_id &&
            result.decision_seq == request.decision.decision_seq &&
            result.branch == request.branch &&
            result.selected_resource == request.decision.selected_resource &&
            result.terminal_status == "completed" &&
            result.raw_input_sha256 == request.raw_input_sha256 &&
            result.preprocessing_contract_sha256 == request.preprocessing_contract_sha256,
        "analytics execution response is not bound to the exact request/decision");
    const bool cpu = result.selected_resource == "cpu";
    require(
        (cpu &&
         result.engine == "openvino_cpu" &&
         result.runtime_name == "OpenVINO" &&
         result.device_api == "CPU" &&
         result.device_id == "CPU" &&
         result.native_inference_api == "openvino.CompiledModel.__call__" &&
         result.execution_path == "openvino_cpu_native") ||
            (!cpu &&
             result.engine == "tensorrt_cuda" &&
             result.runtime_name == "TensorRT" &&
             result.device_api == "NVIDIA_CUDA" &&
             result.native_inference_api ==
                 "nvinfer1::IExecutionContext::enqueueV3" &&
             result.execution_path == "tensorrt_cuda_native"),
        "analytics execution response resource/backend identity drifted");
    const std::vector<FlatValue>& transfer_values =
        array_value(resource, "cuda_transfer_intervals");
    if (cpu) {
      require(
          result.accelerator_memory_bytes == 0 &&
              result.cuda_h2d_bytes == 0 &&
              result.cuda_d2h_bytes == 0 &&
              transfer_values.empty(),
          "OpenVINO CPU analytics response claims CUDA resource work");
    } else {
      require(
          result.accelerator_memory_bytes > 0 &&
              result.cuda_h2d_bytes > 0 &&
              result.cuda_d2h_bytes == result.output_bytes &&
              transfer_values.size() == 2,
          "TensorRT CUDA analytics response resource counters drifted");
      const std::array<std::pair<const char*, std::uint64_t>, 2> expected_transfers = {{
          {"h2d", result.cuda_h2d_bytes},
          {"d2h", result.cuda_d2h_bytes},
      }};
      const std::set<std::string> expected_interval_fields = {
          "direction",
          "host_start_monotonic_ns",
          "host_end_monotonic_ns",
          "device_elapsed_ns",
          "bytes",
          "device_id",
          "timing_source",
      };
      for (std::size_t index = 0; index < transfer_values.size(); ++index) {
        require(
            transfer_values[index].kind == ValueKind::kObject,
            "CUDA transfer interval must be an object");
        const FlatObject& interval = transfer_values[index].object;
        std::set<std::string> observed_interval_fields;
        for (const auto& entry : interval) observed_interval_fields.insert(entry.first);
        require(
            observed_interval_fields == expected_interval_fields,
            "CUDA transfer interval fields drifted");
        CheckpointCudaTransferInterval parsed;
        parsed.direction = string_value(interval, "direction");
        parsed.host_start_monotonic_ns =
            integer_value(interval, "host_start_monotonic_ns");
        parsed.host_end_monotonic_ns =
            integer_value(interval, "host_end_monotonic_ns");
        parsed.device_elapsed_ns = integer_value(interval, "device_elapsed_ns");
        parsed.bytes = integer_value(interval, "bytes");
        parsed.device_id = string_value(interval, "device_id");
        parsed.timing_source = string_value(interval, "timing_source");
        require(
            parsed.direction == expected_transfers[index].first &&
                parsed.host_start_monotonic_ns > 0 &&
                parsed.host_start_monotonic_ns < parsed.host_end_monotonic_ns &&
                parsed.device_elapsed_ns > 0 &&
                parsed.device_elapsed_ns <=
                    parsed.host_end_monotonic_ns - parsed.host_start_monotonic_ns &&
                parsed.bytes == expected_transfers[index].second &&
                parsed.device_id == result.device_id &&
                parsed.timing_source == "cudaEventElapsedTime",
            "CUDA transfer interval identity/timing/bytes drifted");
        result.cuda_transfer_intervals.push_back(std::move(parsed));
      }
      require(
          result.cuda_transfer_intervals[0].host_start_monotonic_ns >=
                  result.inference_started_monotonic_ns &&
              result.cuda_transfer_intervals[0].host_end_monotonic_ns <=
                  result.cuda_transfer_intervals[1].host_start_monotonic_ns &&
              result.cuda_transfer_intervals[1].host_end_monotonic_ns <=
                  result.inference_finished_monotonic_ns,
          "CUDA transfer intervals are outside or reorder the inference lifetime");
    }
    for (const auto& field : {
             std::make_pair(&result.terminal_reason, "terminal_reason"),
             std::make_pair(&result.detector, "detector"),
             std::make_pair(&result.backend, "backend"),
             std::make_pair(&result.worker_id, "worker_id"),
             std::make_pair(&result.runtime_name, "runtime_name"),
             std::make_pair(&result.runtime_version, "runtime_version"),
             std::make_pair(&result.device_id, "device_id"),
             std::make_pair(&result.native_inference_api, "native_inference_api"),
             std::make_pair(&result.execution_path, "execution_path"),
             std::make_pair(&result.model_id, "model_id"),
         }) {
      require_text(*field.first, field.second);
    }
    require(result.detector != "identity" && result.backend != "identity",
            "analytics execution terminal cannot be identity-only");
    if (!cpu) {
      require(
          result.device_id.size() == 40 &&
              result.device_id.rfind("GPU-", 0) == 0 &&
              result.device_id[12] == '-' &&
              result.device_id[17] == '-' &&
              result.device_id[22] == '-' &&
              result.device_id[27] == '-',
          "TensorRT CUDA analytics response GPU UUID is invalid");
      for (std::size_t index = 4; index < result.device_id.size(); ++index) {
        if (index == 12 || index == 17 || index == 22 || index == 27) continue;
        const char character = result.device_id[index];
        require(
            (character >= '0' && character <= '9') ||
                (character >= 'a' && character <= 'f') ||
                (character >= 'A' && character <= 'F'),
            "TensorRT CUDA analytics response GPU UUID is invalid");
      }
    }
    require(
        result.worker_image_id.rfind("sha256:", 0) == 0 &&
            result.worker_image_id.size() == 71,
        "analytics execution worker image ID is invalid");
    require_sha256(result.worker_image_id.substr(7), "worker_image_id");
    for (const auto& field : {
             std::make_pair(&result.worker_implementation_sha256, "worker_implementation_sha256"),
             std::make_pair(&result.source_model_sha256, "source_model_sha256"),
             std::make_pair(&result.model_artifact_sha256, "model_artifact_sha256"),
             std::make_pair(&result.preprocessing_contract_sha256, "preprocessing_contract_sha256"),
             std::make_pair(&result.output_contract_sha256, "output_contract_sha256"),
             std::make_pair(&result.raw_input_sha256, "raw_input_sha256"),
             std::make_pair(&result.input_sha256, "input_sha256"),
             std::make_pair(&result.output_sha256, "output_sha256"),
         }) {
      require_sha256(*field.first, field.second);
    }
    require(
        result.output_bytes > 0 && result.worker_received_monotonic_ns > 0 &&
            result.worker_received_monotonic_ns <= result.inference_started_monotonic_ns &&
            result.inference_started_monotonic_ns <= result.inference_finished_monotonic_ns &&
            result.inference_finished_monotonic_ns <= result.worker_completed_monotonic_ns &&
            result.inference_latency_ns ==
                result.inference_finished_monotonic_ns - result.inference_started_monotonic_ns,
        "analytics execution response timing/provenance is invalid");
    return result;
  }
};

inline CheckpointAnalyticsExecutionClient::FlatValue
CheckpointAnalyticsExecutionClient::parse_value(
    const std::string& json,
    std::size_t& offset,
    std::size_t depth) {
  require(depth <= 5 && offset < json.size(),
          "analytics execution response value nesting is invalid");
  FlatValue value;
  if (json[offset] == '\"') {
    value.kind = ValueKind::kString;
    value.text = parse_string(json, offset);
  } else if (json[offset] == '{') {
    value.kind = ValueKind::kObject;
    value.object = parse_nested_object(json, offset, depth);
  } else if (json[offset] == '[') {
    value.kind = ValueKind::kArray;
    value.array = parse_array(json, offset, depth);
  } else {
    value.kind = ValueKind::kInteger;
    require(json[offset] >= '0' && json[offset] <= '9',
            "analytics execution response value type is unsupported");
    while (offset < json.size() && json[offset] >= '0' && json[offset] <= '9') {
      const std::uint64_t digit = static_cast<std::uint64_t>(json[offset++] - '0');
      require(value.integer <= (UINT64_MAX - digit) / 10,
              "analytics execution response integer overflows uint64");
      value.integer = value.integer * 10 + digit;
    }
  }
  return value;
}

inline std::string
CheckpointAnalyticsExecutionClient::cuda_transfer_native_event_material(
    const CheckpointAnalyticsExecutionRequest& request,
    const CheckpointAnalyticsExecutionResult& result,
    const std::string& execution_id,
    const CheckpointCudaTransferInterval& interval) {
  require_text(request.run_id, "CUDA event run_id");
  require_text(request.arm_id, "CUDA event arm_id");
  require_text(request.input_frame_key, "CUDA event input_frame_key");
  require_text(execution_id, "CUDA event execution_id");
  require_sha256(
      result.worker_implementation_sha256,
      "CUDA event worker_implementation_sha256");
  require(
      result.selected_resource == "gpu" &&
          (interval.direction == "h2d" || interval.direction == "d2h") &&
          interval.host_start_monotonic_ns > 0 &&
          interval.host_start_monotonic_ns < interval.host_end_monotonic_ns &&
          interval.device_elapsed_ns > 0 &&
          interval.device_elapsed_ns <=
              interval.host_end_monotonic_ns - interval.host_start_monotonic_ns &&
          interval.bytes > 0 &&
          interval.device_id == result.device_id &&
          interval.timing_source == "cudaEventElapsedTime",
      "CUDA native event interval is not bound to the validated GPU result");
  std::size_t exact_matches = 0;
  for (const CheckpointCudaTransferInterval& candidate :
       result.cuda_transfer_intervals) {
    if (candidate.direction == interval.direction &&
        candidate.host_start_monotonic_ns == interval.host_start_monotonic_ns &&
        candidate.host_end_monotonic_ns == interval.host_end_monotonic_ns &&
        candidate.device_elapsed_ns == interval.device_elapsed_ns &&
        candidate.bytes == interval.bytes &&
        candidate.device_id == interval.device_id &&
        candidate.timing_source == interval.timing_source) {
      ++exact_matches;
    }
  }
  require(
      exact_matches == 1,
      "CUDA native event interval is absent or duplicated in the validated result");

  std::ostringstream material;
  material
      << "{\"arm_id\":\"" << escape(request.arm_id)
      << "\",\"direction\":\"" << interval.direction
      << "\",\"execution_id\":\"" << escape(execution_id)
      << "\",\"input_frame_key\":\"" << escape(request.input_frame_key)
      << "\",\"interval\":{\"bytes\":" << interval.bytes
      << ",\"device_elapsed_ns\":" << interval.device_elapsed_ns
      << ",\"device_id\":\"" << interval.device_id
      << "\",\"direction\":\"" << interval.direction
      << "\",\"host_end_monotonic_ns\":" << interval.host_end_monotonic_ns
      << ",\"host_start_monotonic_ns\":" << interval.host_start_monotonic_ns
      << ",\"timing_source\":\"" << interval.timing_source
      << "\"},\"protocol_identity_sha256\":\"" << kProtocolIdentitySha256
      << "\",\"run_id\":\"" << escape(request.run_id)
      << "\",\"worker_implementation_sha256\":\""
      << result.worker_implementation_sha256 << "\"}";
  return material.str();
}

}  // namespace vast
