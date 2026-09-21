#include "checkpoint_analytics_execution_client.hpp"

#include <glib.h>

#include <algorithm>
#include <array>
#include <cerrno>
#include <condition_variable>
#include <cstdlib>
#include <cstdint>
#include <cstring>
#include <dirent.h>
#include <exception>
#include <fcntl.h>
#include <iostream>
#include <mutex>
#include <stdexcept>
#include <string>
#include <sys/stat.h>
#include <thread>
#include <vector>

#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

namespace {

constexpr std::size_t kMaximumPayloadBytes = 67'108'864U;

struct Packet {
  std::string json;
  int fd = -1;
};

Packet receive_packet(int socket_fd) {
  std::array<char, 65536> data{};
  std::array<char, CMSG_SPACE(sizeof(int))> control{};
  iovec vector{};
  vector.iov_base = data.data();
  vector.iov_len = data.size();
  msghdr message{};
  message.msg_iov = &vector;
  message.msg_iovlen = 1;
  message.msg_control = control.data();
  message.msg_controllen = control.size();
  const ssize_t size = ::recvmsg(socket_fd, &message, MSG_CMSG_CLOEXEC | MSG_TRUNC);
  if (size <= 0 || static_cast<std::size_t>(size) >= data.size() ||
      (message.msg_flags & (MSG_TRUNC | MSG_CTRUNC)) != 0) {
    throw std::runtime_error(
        "invalid analytics execution packet: size=" + std::to_string(size) +
        " flags=" + std::to_string(message.msg_flags) +
        " control=" + std::to_string(message.msg_controllen) +
        " errno=" + std::to_string(errno));
  }
  cmsghdr* header = CMSG_FIRSTHDR(&message);
  if (header == nullptr || header->cmsg_level != SOL_SOCKET ||
      header->cmsg_type != SCM_RIGHTS || header->cmsg_len != CMSG_LEN(sizeof(int)) ||
      CMSG_NXTHDR(&message, header) != nullptr) {
    throw std::runtime_error("analytics execution packet lacks one input FD");
  }
  int received_fd = -1;
  std::memcpy(&received_fd, CMSG_DATA(header), sizeof(received_fd));
  return {std::string(data.data(), static_cast<std::size_t>(size)), received_fd};
}

void send_packet(int fd, const std::string& payload) {
  const ssize_t size = ::send(fd, payload.data(), payload.size(), 0);
  if (size != static_cast<ssize_t>(payload.size())) {
    throw std::runtime_error("failed to send analytics execution response");
  }
}

bool contains(const std::string& value, const std::string& expected) {
  return value.find(expected) != std::string::npos;
}

void test_environment_path_connection() {
  const std::string path =
      "/tmp/vast-analytics-execution-client-" + std::to_string(::getpid()) + ".sock";
  ::unlink(path.c_str());
  const int listener = ::socket(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0);
  if (listener < 0) throw std::runtime_error("failed to create path listener");
  sockaddr_un address{};
  address.sun_family = AF_UNIX;
  if (path.size() >= sizeof(address.sun_path)) {
    ::close(listener);
    throw std::runtime_error("test socket path is too long");
  }
  std::memcpy(address.sun_path, path.c_str(), path.size() + 1);
  if (::bind(
          listener,
          reinterpret_cast<const sockaddr*>(&address),
          static_cast<socklen_t>(offsetof(sockaddr_un, sun_path) + path.size() + 1)) != 0 ||
      ::listen(listener, 1) != 0) {
    ::close(listener);
    ::unlink(path.c_str());
    throw std::runtime_error("failed to bind/listen on path socket");
  }
  try {
    ::unsetenv(vast::CheckpointAnalyticsExecutionClient::kFdEnvironment);
    if (::setenv(
            vast::CheckpointAnalyticsExecutionClient::kSocketEnvironment,
            path.c_str(),
            1) != 0) {
      throw std::runtime_error("failed to set path environment");
    }
    {
      vast::CheckpointAnalyticsExecutionClient client =
          vast::CheckpointAnalyticsExecutionClient::from_environment();
      const int accepted = ::accept4(listener, nullptr, nullptr, SOCK_CLOEXEC);
      if (accepted < 0) throw std::runtime_error("path listener did not accept client");
      int socket_type = 0;
      socklen_t size = sizeof(socket_type);
      if (::getsockopt(accepted, SOL_SOCKET, SO_TYPE, &socket_type, &size) != 0 ||
          size != sizeof(socket_type) || socket_type != SOCK_SEQPACKET) {
        ::close(accepted);
        throw std::runtime_error("path client did not negotiate SOCK_SEQPACKET");
      }
      ::close(accepted);
    }

    if (::setenv(
            vast::CheckpointAnalyticsExecutionClient::kSocketEnvironment,
            "relative.sock",
            1) != 0) {
      throw std::runtime_error("failed to set relative path environment");
    }
    bool rejected_relative = false;
    try {
      (void)vast::CheckpointAnalyticsExecutionClient::from_environment();
    } catch (const std::exception& exc) {
      rejected_relative = contains(exc.what(), "path is invalid");
    }
    if (!rejected_relative) {
      throw std::runtime_error("relative analytics execution socket path was accepted");
    }
  } catch (...) {
    ::unsetenv(vast::CheckpointAnalyticsExecutionClient::kSocketEnvironment);
    ::close(listener);
    ::unlink(path.c_str());
    throw;
  }
  ::unsetenv(vast::CheckpointAnalyticsExecutionClient::kSocketEnvironment);
  ::close(listener);
  ::unlink(path.c_str());
}

std::string sha256(const std::uint8_t* data, std::size_t size) {
  gchar* digest = g_compute_checksum_for_data(
      G_CHECKSUM_SHA256, reinterpret_cast<const guchar*>(data), static_cast<gsize>(size));
  if (digest == nullptr) throw std::runtime_error("GLib did not compute SHA-256");
  std::string result(digest);
  g_free(digest);
  return result;
}

vast::CheckpointAnalyticsExecutionRequest make_request(
    std::size_t size, const std::string& digest) {
  vast::CheckpointAnalyticsExecutionRequest request;
  request.request_id = "analytics-boundary-test";
  request.run_id = "run-boundary-test";
  request.arm_id = "arm-boundary-test";
  request.worker_id = "worker-boundary-test";
  request.input_frame_key = "dataset:0:source:1:90000";
  request.branch = "damage";
  request.decision.decision_id = "decision-boundary-test";
  request.decision.decision_seq = 1;
  request.decision.selected_resource = "gpu";
  request.decision.selected_implementation_id = "implementation-boundary-test";
  request.decision.emitter_id = "emitter-boundary-test";
  request.decision.emitter_sha256 = std::string(64, '1');
  request.deadline_monotonic_ns = 9999999999ULL;
  request.format = "BGR";
  request.width = 1;
  request.height = 1;
  request.stride = size;
  request.preprocessing_contract_sha256 = std::string(64, '2');
  request.raw_input_sha256 = digest;
  return request;
}

template <typename Invoke>
void expect_local_rejection(Invoke&& invoke, const std::string& expected_message) {
  int descriptors[2] = {-1, -1};
  if (::socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0, descriptors) != 0) {
    throw std::runtime_error("local-rejection socketpair failed");
  }
  timeval timeout{};
  timeout.tv_sec = 2;
  ::setsockopt(descriptors[0], SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
  try {
    {
      vast::CheckpointAnalyticsExecutionClient client(descriptors[0]);
      bool rejected = false;
      try {
        invoke(client);
      } catch (const std::exception& error) {
        rejected = contains(error.what(), expected_message);
      }
      if (!rejected) throw std::runtime_error("missing local error: " + expected_message);
      char byte = 0;
      errno = 0;
      const ssize_t received = ::recv(descriptors[1], &byte, 1, MSG_DONTWAIT);
      if (received != -1 || (errno != EAGAIN && errno != EWOULDBLOCK)) {
        throw std::runtime_error("invalid request sent a datagram or payload FD");
      }
    }
    ::close(descriptors[1]);
  } catch (...) {
    ::close(descriptors[1]);
    throw;
  }
}

void test_local_payload_rejections() {
  const std::array<std::uint8_t, 4> payload{1, 2, 3, 4};
  const auto wrong_hash = make_request(payload.size(), std::string(64, '0'));
  expect_local_rejection(
      [&](vast::CheckpointAnalyticsExecutionClient& client) {
        (void)client.execute(wrong_hash, payload.data(), payload.size());
      },
      "SHA-256 differs");
  const auto zero = make_request(3, std::string(64, '0'));
  expect_local_rejection(
      [&](vast::CheckpointAnalyticsExecutionClient& client) {
        (void)client.execute(zero, nullptr, 0);
      },
      "payload is empty");
  const std::uint8_t one_byte = 7;
  const std::size_t oversized = kMaximumPayloadBytes + 1U;
  const auto too_large = make_request(oversized, std::string(64, '0'));
  expect_local_rejection(
      [&](vast::CheckpointAnalyticsExecutionClient& client) {
        (void)client.execute(too_large, &one_byte, oversized);
      },
      "bounded maximum");
}

std::string sha256_fd(int fd, std::size_t size) {
  GChecksum* checksum = g_checksum_new(G_CHECKSUM_SHA256);
  if (checksum == nullptr) throw std::runtime_error("GLib did not allocate a checksum");
  std::array<std::uint8_t, 64 * 1024> buffer{};
  std::size_t offset = 0;
  while (offset < size) {
    const std::size_t wanted = std::min(buffer.size(), size - offset);
    const ssize_t count = ::pread(fd, buffer.data(), wanted, static_cast<off_t>(offset));
    if (count <= 0) {
      g_checksum_free(checksum);
      throw std::runtime_error("sealed snapshot is truncated");
    }
    g_checksum_update(checksum, buffer.data(), static_cast<gssize>(count));
    offset += static_cast<std::size_t>(count);
  }
  const std::string result(g_checksum_get_string(checksum));
  g_checksum_free(checksum);
  return result;
}

std::size_t open_fd_count() {
  DIR* directory = ::opendir("/proc/self/fd");
  if (directory == nullptr) throw std::runtime_error("cannot inspect /proc/self/fd");
  std::size_t count = 0;
  while (::readdir(directory) != nullptr) ++count;
  ::closedir(directory);
  return count;
}

void test_maximum_snapshot_reuse_and_cleanup() {
  const std::size_t before = open_fd_count();
  const std::size_t size = kMaximumPayloadBytes;
  std::vector<std::uint8_t> payload(size, 0x5a);
  const std::string digest = sha256(payload.data(), payload.size());
  const auto request = make_request(size, digest);
  int descriptors[2] = {-1, -1};
  if (::socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0, descriptors) != 0) {
    throw std::runtime_error("maximum-payload socketpair failed");
  }
  std::mutex mutex;
  std::condition_variable condition;
  bool received = false;
  bool reused = false;
  std::exception_ptr server_error;
  std::exception_ptr client_error;
  std::thread server([&]() {
    int payload_fd = -1;
    try {
      Packet packet = receive_packet(descriptors[1]);
      payload_fd = packet.fd;
      struct stat state{};
      if (::fstat(payload_fd, &state) != 0 || static_cast<std::size_t>(state.st_size) != size) {
        throw std::runtime_error("sealed snapshot has wrong size");
      }
      const int seals = ::fcntl(payload_fd, F_GET_SEALS);
      const int required = F_SEAL_SEAL | F_SEAL_SHRINK | F_SEAL_GROW | F_SEAL_WRITE;
      if (seals < 0 || (seals & required) != required) {
        throw std::runtime_error("snapshot is not fully sealed");
      }
      {
        std::unique_lock<std::mutex> lock(mutex);
        received = true;
        condition.notify_all();
        condition.wait(lock, [&]() { return reused; });
      }
      if (sha256_fd(payload_fd, size) != digest ||
          !contains(packet.json, "\"sha256\":\"" + digest + "\"") ||
          !contains(packet.json, "\"byte_length\":" + std::to_string(size))) {
        throw std::runtime_error("sealed bytes and request metadata describe different snapshots");
      }
    } catch (...) {
      server_error = std::current_exception();
      std::lock_guard<std::mutex> lock(mutex);
      received = true;
      reused = true;
      condition.notify_all();
    }
    if (payload_fd >= 0) ::close(payload_fd);
    ::close(descriptors[1]);
  });
  std::thread caller([&]() {
    try {
      vast::CheckpointAnalyticsExecutionClient client(descriptors[0]);
      (void)client.execute(request, payload.data(), payload.size());
      throw std::runtime_error("closed test worker unexpectedly returned a response");
    } catch (const std::exception& error) {
      if (!contains(error.what(), "response is missing or truncated")) {
        client_error = std::current_exception();
      }
    }
  });
  {
    std::unique_lock<std::mutex> lock(mutex);
    condition.wait(lock, [&]() { return received; });
    std::fill(payload.begin(), payload.end(), 0xa5);
    reused = true;
    condition.notify_all();
  }
  caller.join();
  server.join();
  if (server_error) std::rethrow_exception(server_error);
  if (client_error) std::rethrow_exception(client_error);
  if (open_fd_count() != before) throw std::runtime_error("exception path leaked a descriptor");
}

}  // namespace

int main() {
  try {
    test_local_payload_rejections();
    test_maximum_snapshot_reuse_and_cleanup();
    test_environment_path_connection();
  } catch (const std::exception& exc) {
    std::cerr << exc.what() << '\n';
    return 1;
  }
  int descriptors[2] = {-1, -1};
  if (::socketpair(AF_UNIX, SOCK_SEQPACKET, 0, descriptors) != 0) {
    std::cerr << "socketpair failed\n";
    return 2;
  }
  timeval timeout{};
  timeout.tv_sec = 2;
  if (::setsockopt(descriptors[0], SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) != 0 ||
      ::setsockopt(descriptors[1], SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) != 0) {
    std::cerr << "setsockopt failed\n";
    return 2;
  }
  try {
    const std::string raw_sha =
        "9f64a747e1b97f131fabb6b447296c9b6f0201e79fb3c5356e6c77e89b6a806a";
    const std::string policy_sha =
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
    const std::string contract_sha =
        "1123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
    std::exception_ptr server_error;
    std::thread server([&]() {
      try {
        Packet packet = receive_packet(descriptors[1]);
        if (!contains(packet.json, "\"message_type\":\"analytics_execute\"") ||
            !contains(packet.json, "\"selected_resource\":\"gpu\"") ||
            !contains(packet.json, "\"kind\":\"raw_gstreamer_frame\"") ||
            !contains(packet.json, "\"format\":\"BGR\"") ||
            !contains(packet.json, "\"stride\":4") ||
            !contains(packet.json, "\"sha256\":\"" + raw_sha + "\"")) {
          throw std::runtime_error("analytics execution request is incomplete");
        }
        const int seals = ::fcntl(packet.fd, F_GET_SEALS);
        const int required = F_SEAL_SEAL | F_SEAL_SHRINK | F_SEAL_GROW | F_SEAL_WRITE;
        if (seals < 0 || (seals & required) != required) {
          throw std::runtime_error("analytics input memfd is not sealed");
        }
        std::array<std::uint8_t, 4> observed{};
        if (::pread(packet.fd, observed.data(), observed.size(), 0) !=
                static_cast<ssize_t>(observed.size()) ||
            observed != std::array<std::uint8_t, 4>{1, 2, 3, 4}) {
          throw std::runtime_error("analytics input memfd payload drifted");
        }
        ::close(packet.fd);
        send_packet(
            descriptors[1],
            "{\"backend\":\"cuda-tensorrt:sidecar;device=NVIDIA_CUDA:0\"," 
            "\"branch\":\"damage\",\"decision_id\":\"decision-native-0001\"," 
            "\"decision_seq\":7,\"detector\":\"damage-gpu-detector-v1\"," 
            "\"device_api\":\"NVIDIA_CUDA\",\"device_id\":\"GPU-00000000-0000-0000-0000-000000000001\"," 
            "\"engine\":\"tensorrt_cuda\",\"execution_path\":\"tensorrt_cuda_native\"," 
            "\"inference_finished_monotonic_ns\":130,\"inference_latency_ns\":20," 
            "\"inference_started_monotonic_ns\":110,\"input_sha256\":\"2123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\"," 
            "\"message_type\":\"analytics_execute_response\",\"model_artifact_sha256\":\"3123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\"," 
            "\"model_id\":\"damage-model-v1\",\"native_inference_api\":\"nvinfer1::IExecutionContext::enqueueV3\"," 
            "\"objects\":1,\"output_bytes\":32,\"output_contract_sha256\":\"4123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\"," 
            "\"output_sha256\":\"5123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\"," 
            "\"preprocessing_contract_sha256\":\"" + contract_sha + "\"," 
            "\"raw_input_sha256\":\"" + raw_sha + "\",\"request_id\":\"analytics-request-0001\"," 
            "\"resource\":{\"accelerator_memory_bytes\":4096,\"cuda_d2h_bytes\":32,"
            "\"cuda_h2d_bytes\":4,\"cuda_transfer_intervals\":["
            "{\"bytes\":4,\"device_elapsed_ns\":3,"
            "\"device_id\":\"GPU-00000000-0000-0000-0000-000000000001\","
            "\"direction\":\"h2d\",\"host_end_monotonic_ns\":115,"
            "\"host_start_monotonic_ns\":111,\"timing_source\":\"cudaEventElapsedTime\"},"
            "{\"bytes\":32,\"device_elapsed_ns\":3,"
            "\"device_id\":\"GPU-00000000-0000-0000-0000-000000000001\","
            "\"direction\":\"d2h\",\"host_end_monotonic_ns\":129,"
            "\"host_start_monotonic_ns\":125,\"timing_source\":\"cudaEventElapsedTime\"}],"
            "\"process_cpu_time_ns\":50,\"rss_after_bytes\":8192,\"rss_before_bytes\":4096},"
            "\"runtime_name\":\"TensorRT\",\"runtime_version\":\"8.6.1.6\",\"schema_version\":1," 
            "\"selected_resource\":\"gpu\",\"source_model_sha256\":\"6123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\"," 
            "\"terminal_reason\":\"native_fixed_tensor_completed\",\"terminal_status\":\"completed\"," 
            "\"worker_completed_monotonic_ns\":140,\"worker_id\":\"vast.damage.tensorrt\"," 
            "\"worker_image_id\":\"sha256:7123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\"," 
            "\"worker_implementation_sha256\":\"8123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\"," 
            "\"worker_received_monotonic_ns\":100}");
      } catch (...) {
        server_error = std::current_exception();
      }
      ::close(descriptors[1]);
    });

    vast::CheckpointAnalyticsExecutionClient client(descriptors[0]);
    vast::CheckpointAnalyticsExecutionRequest request;
    request.request_id = "analytics-request-0001";
    request.run_id = "run-native-analytics-0001";
    request.arm_id = "arm-native-analytics-0001";
    request.worker_id = "checkpoint-worker-0001";
    request.input_frame_key = "dataset:0:source:1:90000";
    request.stream_id = 0;
    request.frame_id = 1;
    request.transport_pts_ns = 90000;
    request.branch = "damage";
    request.decision.decision_id = "decision-native-0001";
    request.decision.decision_seq = 7;
    request.decision.selected_resource = "gpu";
    request.decision.selected_implementation_id = "gstreamer-damage-gpu-implementation-v1";
    request.decision.emitter_id = "gstreamer-damage-gpu-emitter-v1";
    request.decision.emitter_sha256 = policy_sha;
    request.deadline_monotonic_ns = 9999999999;
    request.format = "BGR";
    request.width = 1;
    request.height = 1;
    request.stride = 4;
    request.preprocessing_contract_sha256 = contract_sha;
    request.raw_input_sha256 = raw_sha;
    const std::array<std::uint8_t, 4> payload{1, 2, 3, 4};
    vast::CheckpointAnalyticsExecutionResult result;
    try {
      result = client.execute(request, payload.data(), payload.size());
    } catch (const std::exception& client_error) {
      const std::string message = client_error.what();
      server.join();
      throw std::runtime_error("client failed before response: " + message);
    }
    server.join();
    if (server_error) {
      std::rethrow_exception(server_error);
    }
    if (result.decision_id != request.decision.decision_id ||
        result.selected_resource != "gpu" || result.device_api != "NVIDIA_CUDA" ||
        result.raw_input_sha256 != raw_sha || result.terminal_status != "completed" ||
        result.detector != "damage-gpu-detector-v1" || result.objects != 1 ||
        result.cuda_transfer_intervals.size() != 2 ||
        result.cuda_transfer_intervals[0].direction != "h2d" ||
        result.cuda_transfer_intervals[1].direction != "d2h") {
      throw std::runtime_error("validated analytics execution result drifted");
    }
  } catch (const std::exception& exc) {
    std::cerr << exc.what() << '\n';
    return 1;
  }
  return 0;
}
