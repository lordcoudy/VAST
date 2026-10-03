#include "checkpoint_native_policy_client.hpp"

#include <sys/socket.h>
#include <unistd.h>
#include <poll.h>

#include <exception>
#include <atomic>
#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace {

std::string receive_packet(int fd) {
  std::vector<char> buffer(65536);
  const ssize_t size = ::recv(fd, buffer.data(), buffer.size(), MSG_TRUNC);
  if (size <= 0 || static_cast<std::size_t>(size) >= buffer.size()) {
    throw std::runtime_error("invalid test policy packet");
  }
  return std::string(buffer.data(), static_cast<std::size_t>(size));
}

void send_packet(int fd, const std::string& payload) {
  const ssize_t size = ::send(fd, payload.data(), payload.size(), 0);
  if (size != static_cast<ssize_t>(payload.size())) {
    throw std::runtime_error("failed to send test policy packet");
  }
}

bool contains(const std::string& value, const std::string& expected) {
  return value.find(expected) != std::string::npos;
}

}  // namespace

int main() {
  int descriptors[2] = {-1, -1};
  if (::socketpair(AF_UNIX, SOCK_SEQPACKET, 0, descriptors) != 0) {
    std::cerr << "socketpair failed\n";
    return 2;
  }
  try {
    std::exception_ptr server_error;
    std::thread server([&]() {
      try {
        const std::string request = receive_packet(descriptors[1]);
        if (!contains(request, "\"message_type\":\"decision_request\"") ||
            !contains(request, "\"queue_depths\":{\"cpu\":2,\"gpu\":3}") ||
            !contains(request, "\"transport_pts_ns\":90000")) {
          throw std::runtime_error("decision request is incomplete");
        }
        send_packet(
            descriptors[1],
            "{\"decision_id\":\"run-policy:decision:0001\",\"decision_seq\":1,"
            "\"emitter_id\":\"vast-gst-policy:plate_number:cpu:v1\","
            "\"emitter_sha256\":\"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\","
            "\"message_type\":\"decision_response\",\"schema_version\":1,"
            "\"selected_implementation_id\":\"gst-openvino:plate_number:cpu:v1\","
            "\"selected_resource\":\"cpu\"}");
        const std::string path = receive_packet(descriptors[1]);
        if (!contains(path, "\"message_type\":\"path_enter\"") ||
            !contains(path, "\"event_id\":\"native-path-event:0001\"") ||
            !contains(path, "\"selected_resource\":\"cpu\"")) {
          throw std::runtime_error("path entry is incomplete");
        }
        send_packet(
            descriptors[1],
            "{\"accepted\":true,\"decision_id\":\"run-policy:decision:0001\","
            "\"message_type\":\"path_ack\",\"schema_version\":1}");
        const std::string terminal = receive_packet(descriptors[1]);
        if (!contains(terminal, "\"message_type\":\"terminal\"") ||
            !contains(terminal, "\"backend\":\"analytics-execution:openvino_cpu;runtime=OpenVINO;native_api=openvino.CompiledModel.__call__;device=CPU:Intel(R) Core(TM) i7-14700K\"") ||
            !contains(terminal, "\"actual_service_ms\":2.5")) {
          throw std::runtime_error("terminal evidence is incomplete");
        }
        send_packet(
            descriptors[1],
            "{\"accepted\":true,\"decision_id\":\"run-policy:decision:0001\","
            "\"message_type\":\"terminal_ack\",\"schema_version\":1}");
      } catch (...) {
        server_error = std::current_exception();
      }
      ::close(descriptors[1]);
    });

    vast::CheckpointNativePolicyClient client(descriptors[0]);
    vast::CheckpointNativePolicyRequest request;
    request.run_id = "run-native-policy-0001";
    request.worker_id = "worker-shared-0001";
    request.input_frame_key = "dataset:0:source:1:90000";
    request.trace_id = "run-native-policy-0001:0:1";
    request.stream_id = 0;
    request.frame_id = 1;
    request.transport_pts_ns = 90000;
    request.branch = "plate_number";
    request.arrival_ms = 1000.0;
    request.decision_time_ms = 1001.0;
    request.feature_observed_timestamp_ms = 1000.5;
    request.cpu_queue_depth = 2;
    request.gpu_queue_depth = 3;
    const auto decision = client.decide(request);
    vast::CheckpointNativeExecutionBinding binding;
    binding.resource = "cpu";
    binding.implementation_id = "gst-openvino:plate_number:cpu:v1";
    binding.emitter_id = "vast-gst-policy:plate_number:cpu:v1";
    binding.emitter_sha256 =
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
    client.enter_path(request, decision, binding, "native-path-event:0001", 1002.0);
    client.terminal(
        request,
        decision,
        binding,
        "completed",
        1004.5,
        2.5,
        "plate-number-detector-v1",
        "analytics-execution:openvino_cpu;runtime=OpenVINO;native_api=openvino.CompiledModel.__call__;device=CPU:Intel(R) Core(TM) i7-14700K");
    server.join();
    if (server_error) {
      std::rethrow_exception(server_error);
    }
    for (const std::string& invalid_backend : {
             " leading-backend", "trailing-backend ", "backend\tcontrol"}) {
      bool rejected = false;
      try {
        client.terminal(request, decision, binding, "completed", 1004.5,
                        2.5, "plate-number-detector-v1", invalid_backend);
      } catch (const std::exception& error) {
        rejected = contains(error.what(), "backend contains controls");
      }
      if (!rejected) {
        throw std::runtime_error("unsafe native policy backend was accepted");
      }
    }

    int mismatch_fds[2] = {-1, -1};
    if (::socketpair(AF_UNIX, SOCK_SEQPACKET, 0, mismatch_fds) != 0) {
      throw std::runtime_error("second socketpair failed");
    }
    std::atomic<bool> unexpected_unselected_path{false};
    std::thread mismatch_server([&]() {
      (void)receive_packet(mismatch_fds[1]);
      send_packet(
          mismatch_fds[1],
          "{\"decision_id\":\"run-policy:decision:0002\",\"decision_seq\":2,"
          "\"emitter_id\":\"vast-gst-policy:plate_number:gpu:v1\","
          "\"emitter_sha256\":\"1123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\","
          "\"message_type\":\"decision_response\",\"schema_version\":1,"
          "\"selected_implementation_id\":\"gst-tensorrt:plate_number:gpu:v1\","
          "\"selected_resource\":\"gpu\"}");
      pollfd descriptor{};
      descriptor.fd = mismatch_fds[1];
      descriptor.events = POLLIN;
      if (::poll(&descriptor, 1, 100) > 0 && (descriptor.revents & POLLIN) != 0) {
        unexpected_unselected_path.store(true);
      }
      ::close(mismatch_fds[1]);
    });
    vast::CheckpointNativePolicyClient mismatch_client(mismatch_fds[0]);
    const auto mismatch_decision = mismatch_client.decide(request);
    bool rejected = false;
    try {
      mismatch_client.enter_path(
          request,
          mismatch_decision,
          binding,
          "native-path-event:0002",
          1002.0);
    } catch (const std::exception&) {
      rejected = true;
    }
    mismatch_server.join();
    if (!rejected || unexpected_unselected_path.load()) {
      throw std::runtime_error("unselected local path was accepted");
    }

    // The frozen six-byte "damage" branch is valid; unknown names are rejected
    // locally before any request is sent.
    int branch_fds[2] = {-1, -1};
    if (::socketpair(AF_UNIX, SOCK_SEQPACKET, 0, branch_fds) != 0) {
      throw std::runtime_error("branch socketpair failed");
    }
    std::exception_ptr branch_error;
    std::atomic<int> branch_requests{0};
    std::thread branch_server([&]() {
      try {
        const std::string packet = receive_packet(branch_fds[1]);
        branch_requests.fetch_add(1);
        if (!contains(packet, "\"branch\":\"damage\"")) {
          throw std::runtime_error("damage decision request lost its branch");
        }
        send_packet(
            branch_fds[1],
            "{\"decision_id\":\"run-policy:decision:0003\",\"decision_seq\":3,"
            "\"emitter_id\":\"vast-gst-policy:damage:cpu:v1\","
            "\"emitter_sha256\":\"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\","
            "\"message_type\":\"decision_response\",\"schema_version\":1,"
            "\"selected_implementation_id\":\"gst-openvino:damage:cpu:v1\","
            "\"selected_resource\":\"cpu\"}");
        pollfd extra{};
        extra.fd = branch_fds[1];
        extra.events = POLLIN;
        if (::poll(&extra, 1, 100) > 0 && (extra.revents & POLLIN) != 0) {
          char probe = 0;
          // A closed peer also reports POLLIN; count only a real packet.
          if (::recv(branch_fds[1], &probe, sizeof(probe), MSG_DONTWAIT | MSG_TRUNC) > 0) {
            branch_requests.fetch_add(1);
          }
        }
      } catch (...) {
        branch_error = std::current_exception();
      }
      ::close(branch_fds[1]);
    });
    std::exception_ptr client_error;
    try {
      vast::CheckpointNativePolicyClient branch_client(branch_fds[0]);
      vast::CheckpointNativePolicyRequest damage = request;
      damage.branch = "damage";
      (void)branch_client.decide(damage);
      for (const char* invalid : {"", "dmg", "damage2", "Damage", "unknown_branch"}) {
        vast::CheckpointNativePolicyRequest bad = request;
        bad.branch = invalid;
        bool branch_rejected = false;
        try {
          (void)branch_client.decide(bad);
        } catch (const std::exception& error) {
          branch_rejected = contains(error.what(), "frozen branch set");
        }
        if (!branch_rejected) {
          throw std::runtime_error(std::string("invalid policy branch was accepted: ") + invalid);
        }
      }
    } catch (...) {
      client_error = std::current_exception();
      ::shutdown(branch_fds[0], SHUT_RDWR);
    }
    branch_server.join();
    if (client_error) {
      std::rethrow_exception(client_error);
    }
    if (branch_error) {
      std::rethrow_exception(branch_error);
    }
    if (branch_requests.load() != 1) {
      throw std::runtime_error("invalid policy branch reached the policy transport");
    }
  } catch (const std::exception& exc) {
    std::cerr << exc.what() << '\n';
    return 1;
  }
  return 0;
}
