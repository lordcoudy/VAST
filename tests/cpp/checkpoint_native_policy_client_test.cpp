#include "checkpoint_native_policy_client.hpp"
#include "checkpoint_admission_transport.hpp"

#include <sys/socket.h>
#include <unistd.h>
#include <poll.h>
#include <fcntl.h>
#include <dirent.h>

#include <exception>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <functional>
#include <future>
#include <memory>
#include <mutex>
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

// Compile the same real-peer regressions against the old implementation: its
// missing binding API is a no-op, so RED is a live blocked RPC, not an API error.
template <class Client>
auto bind_owner(Client& client, std::shared_ptr<vast::CheckpointIoDeadline> io,
                std::function<bool(const std::string&)> eligible, int)
    -> decltype(client.bind_lifecycle(io, eligible), void()) {
  client.bind_lifecycle(std::move(io), std::move(eligible));
}
template <class Client>
void bind_owner(Client&, std::shared_ptr<vast::CheckpointIoDeadline>,
                std::function<bool(const std::string&)>, long) {}
template <class Client>
auto abort_owner(Client& client, std::shared_ptr<vast::CheckpointIoDeadline>, int)
    -> decltype(client.abort(), void()) { client.abort(); }
template <class Client>
void abort_owner(Client&, std::shared_ptr<vast::CheckpointIoDeadline> io, long) {
  io->abort();
}

struct OwnedPair {
  int fds[2] = {-1, -1};
  OwnedPair() {
    if (::socketpair(AF_UNIX, SOCK_SEQPACKET, 0, fds) != 0)
      throw std::runtime_error("lifecycle socketpair failed");
  }
  ~OwnedPair() { for (int fd : fds) if (fd >= 0) ::close(fd); }
  int take_client() { const int fd = fds[0]; fds[0] = -1; return fd; }
  void retire_peer() { ::close(fds[1]); fds[1] = -1; }
};

int fd_count() {
  DIR* directory = ::opendir("/proc/self/fd");
  if (!directory) throw std::runtime_error("cannot count real test FDs");
  int count = 0;
  while (dirent* entry = ::readdir(directory))
    if (entry->d_name[0] != '.') ++count;
  ::closedir(directory);
  return count;
}

std::string bounded_receive(int fd) {
  pollfd item{fd, POLLIN, 0};
  if (::poll(&item, 1, 1000) <= 0)
    throw std::runtime_error("test peer did not receive a real packet");
  return receive_packet(fd);
}

vast::CheckpointNativePolicyRequest lifecycle_request() {
  vast::CheckpointNativePolicyRequest value;
  value.run_id = "run-native-policy-lifecycle";
  value.worker_id = "worker-shared-lifecycle";
  value.input_frame_key = "dataset:0:source:1:90000";
  value.trace_id = "run-native-policy-lifecycle:0:1";
  value.frame_id = 1;
  value.transport_pts_ns = 90000;
  value.branch = "plate_number";
  value.arrival_ms = 1000;
  value.decision_time_ms = 1001;
  value.feature_observed_timestamp_ms = 1000.5;
  return value;
}

std::string lifecycle_decision_packet() {
  return "{\"decision_id\":\"run-policy:decision:0001\",\"decision_seq\":1,"
         "\"emitter_id\":\"vast-gst-policy:plate_number:cpu:v1\","
         "\"emitter_sha256\":\"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\","
         "\"message_type\":\"decision_response\",\"schema_version\":1,"
         "\"selected_implementation_id\":\"gst-openvino:plate_number:cpu:v1\","
         "\"selected_resource\":\"cpu\"}";
}
std::string lifecycle_ack(const std::string& kind) {
  return "{\"accepted\":true,\"decision_id\":\"run-policy:decision:0001\","
         "\"message_type\":\"" + kind + "\",\"schema_version\":1}";
}

void silent_rpc(const std::string& stage, bool queued, bool abort) {
  const int before = fd_count();
  int retired_client = -1;
  bool returned_before_release = false, queued_before_release = !queued;
  bool deadline_observed = false, gate_expired = false, fds_held = false;
  std::string failure, queued_failure;
  std::exception_ptr peer_error;
  {
    OwnedPair pair;
    const int peer_fd = pair.fds[1];
    retired_client = pair.take_client();
    vast::CheckpointNativePolicyClient client(retired_client);
    auto io = std::make_shared<vast::CheckpointIoDeadline>();
    // Represents the last 200 ms of the already established owner drain,
    // not a fresh per-RPC allowance or a changed production drain duration.
    io->bind_original_drain_end_ms(
        vast::CheckpointIoDeadline::realtime_now_ns() / 1000000 + 200);
    bind_owner(client, io, [](const std::string&) { return true; }, 0);
    std::mutex gate_mutex;
    std::condition_variable gate;
    bool release = false;
    std::promise<void> target_received;
    auto observed = target_received.get_future();
    std::thread peer([&]() {
      try {
        auto packet = bounded_receive(peer_fd);
        if (!contains(packet, "\"message_type\":\"decision_request\""))
          throw std::runtime_error("silent decision fixture got another wire kind");
        if (stage != "decision") {
          send_packet(peer_fd, lifecycle_decision_packet());
          packet = bounded_receive(peer_fd);
          if (!contains(packet, "\"message_type\":\"path_enter\""))
            throw std::runtime_error("silent path fixture got another wire kind");
          if (stage == "terminal") {
            send_packet(peer_fd, lifecycle_ack("path_ack"));
            packet = bounded_receive(peer_fd);
            if (!contains(packet, "\"message_type\":\"terminal\""))
              throw std::runtime_error("silent terminal fixture got another wire kind");
          }
        }
        target_received.set_value();
        std::unique_lock<std::mutex> lock(gate_mutex);
        if (!gate.wait_for(lock, std::chrono::seconds(2), [&]() { return release; }))
          gate_expired = true;
      } catch (...) { peer_error = std::current_exception(); }
      // Only the owning peer retires its endpoint, AFTER the test has checked
      // deadline/abort and both callers while the peer remained silent/live.
      pair.retire_peer();
    });
    const auto request = lifecycle_request();
    auto caller = std::async(std::launch::async, [&]() -> std::string {
      try {
        const auto decision = client.decide(request);
        if (stage != "decision") {
          vast::CheckpointNativeExecutionBinding binding{
              "cpu", "gst-openvino:plate_number:cpu:v1",
              "vast-gst-policy:plate_number:cpu:v1",
              "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"};
          client.enter_path(request, decision, binding, "native-path-event:0001", 1002);
          if (stage == "terminal")
            client.terminal(request, decision, binding, "completed", 1004, 2,
                            "plate-number-detector-v1", "openvino-cpu-backend");
        }
        return "unexpected-success";
      } catch (const std::exception& error) { return error.what(); }
    });
    const bool saw_target = observed.wait_for(std::chrono::seconds(1)) ==
                            std::future_status::ready;
    std::future<std::string> second;
    if (queued && saw_target) {
      second = std::async(std::launch::async, [&]() -> std::string {
        try { (void)client.decide(request); return "unexpected-success"; }
        catch (const std::exception& error) { return error.what(); }
      });
    }
    if (abort) {
      abort_owner(client, io, 0);
      deadline_observed = io->aborted();
    } else {
      const auto fixture_end = std::chrono::steady_clock::now() + std::chrono::seconds(1);
      while (std::chrono::steady_clock::now() < fixture_end) {
        try { io->check(); }
        catch (const std::exception& error) {
          deadline_observed = contains(error.what(), "original deadline exceeded");
          break;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
      }
    }
    returned_before_release = caller.wait_for(std::chrono::milliseconds(80)) ==
                              std::future_status::ready;
    if (second.valid())
      queued_before_release = second.wait_for(std::chrono::milliseconds(80)) ==
                              std::future_status::ready;
    fds_held = ::fcntl(retired_client, F_GETFD) >= 0 && ::fcntl(peer_fd, F_GETFD) >= 0;
    { std::lock_guard<std::mutex> lock(gate_mutex); release = true; }
    gate.notify_all();
    peer.join();
    failure = caller.get();
    if (second.valid()) queued_failure = second.get();
    if (!saw_target) throw std::runtime_error("silent fixture never reached its real RPC");
  }
  if (peer_error) std::rethrow_exception(peer_error);
  const std::string expected = abort ? "owner aborted" : "original deadline exceeded";
  if (!deadline_observed || !returned_before_release || !queued_before_release ||
      !contains(failure, expected) || (queued && !contains(queued_failure, expected)) ||
      !fds_held || gate_expired || ::fcntl(retired_client, F_GETFD) != -1 ||
      errno != EBADF || fd_count() != before)
    throw std::runtime_error(stage + (abort ? " abort" : " original-deadline") +
                             " RPC/queued caller did not fail before live-peer release/retirement");
}

void queued_key_eligibility() {
  const int before = fd_count();
  bool refused = false;
  std::atomic<bool> second_started{false}, first_release{false}, callback_after_release{false};
  std::atomic<bool> unexpected_packet{false};
  std::exception_ptr peer_error;
  {
    OwnedPair pair;
    const int peer_fd = pair.fds[1];
    vast::CheckpointNativePolicyClient client(pair.take_client());
    auto io = std::make_shared<vast::CheckpointIoDeadline>(
        vast::CheckpointIoDeadline::monotonic_now_ns() + 2000000000ULL);
    std::atomic<bool> eligible{true};
    const auto first_request = lifecycle_request();
    auto second_request = first_request;
    second_request.input_frame_key = "dataset:0:source:2:180000";
    bind_owner(client, io, [&](const std::string& key) {
      if (key == second_request.input_frame_key) {
        callback_after_release = first_release.load();
        return eligible.load();
      }
      return key == first_request.input_frame_key;
    }, 0);
    std::promise<void> first_received;
    auto observed = first_received.get_future();
    std::thread peer([&]() {
      try {
        (void)bounded_receive(peer_fd);
        first_received.set_value();
        const auto guard = std::chrono::steady_clock::now() + std::chrono::seconds(1);
        while (!first_release && std::chrono::steady_clock::now() < guard)
          std::this_thread::sleep_for(std::chrono::milliseconds(1));
        if (!first_release) throw std::runtime_error("eligibility fixture release missing");
        send_packet(peer_fd, lifecycle_decision_packet());
        pollfd item{peer_fd, POLLIN, 0};
        if (::poll(&item, 1, 100) > 0 && (item.revents & POLLIN)) {
          const auto packet = bounded_receive(peer_fd);
          unexpected_packet = !packet.empty();
          send_packet(peer_fd, lifecycle_decision_packet());
        }
      } catch (...) { peer_error = std::current_exception(); }
      pair.retire_peer();
    });
    auto first = std::async(std::launch::async, [&]() {
      try { (void)client.decide(first_request); return std::string(); }
      catch (const std::exception& error) { return std::string(error.what()); }
    });
    const bool saw_first = observed.wait_for(std::chrono::seconds(1)) == std::future_status::ready;
    auto second = std::async(std::launch::async, [&]() {
      second_started = true;
      try { (void)client.decide(second_request); return std::string(); }
      catch (const std::exception& error) { return std::string(error.what()); }
    });
    while (!second_started) std::this_thread::yield();
    const bool queued = second.wait_for(std::chrono::milliseconds(20)) == std::future_status::timeout;
    eligible = false;
    first_release = true;
    const auto first_error = first.get();
    const auto second_error = second.get();
    peer.join();
    refused = saw_first && queued && first_error.empty() &&
              contains(second_error, "not eligible") && callback_after_release && !unexpected_packet;
  }
  if (peer_error) std::rethrow_exception(peer_error);
  if (!refused || fd_count() != before)
    throw std::runtime_error("queued policy key was not rechecked after client lock/retirement");
}

void poisoned_reply(bool oversized) {
  const int before = fd_count();
  std::atomic<bool> unexpected_packet{false};
  bool rejected_first = false, rejected_reuse = false;
  std::exception_ptr peer_error;
  {
    OwnedPair pair;
    const int peer_fd = pair.fds[1];
    vast::CheckpointNativePolicyClient client(pair.take_client());
    auto io = std::make_shared<vast::CheckpointIoDeadline>(
        vast::CheckpointIoDeadline::monotonic_now_ns() + 2000000000ULL);
    bind_owner(client, io, [](const std::string&) { return true; }, 0);
    std::thread peer([&]() {
      try {
        (void)bounded_receive(peer_fd);
        send_packet(peer_fd, oversized ? std::string(65537, 'x') : "{\"schema_version\":");
        pollfd item{peer_fd, POLLIN, 0};
        if (::poll(&item, 1, 100) > 0 && (item.revents & POLLIN)) {
          (void)bounded_receive(peer_fd);
          unexpected_packet = true;
          send_packet(peer_fd, lifecycle_decision_packet());
        }
      } catch (...) { peer_error = std::current_exception(); }
      pair.retire_peer();
    });
    try { (void)client.decide(lifecycle_request()); }
    catch (const std::exception& error) {
      rejected_first = contains(error.what(), oversized ? "truncated" : "unsupported");
    }
    try { (void)client.decide(lifecycle_request()); }
    catch (const std::exception& error) { rejected_reuse = contains(error.what(), "channel failed"); }
    peer.join();
  }
  if (peer_error) std::rethrow_exception(peer_error);
  if (!rejected_first || !rejected_reuse || unexpected_packet || fd_count() != before)
    throw std::runtime_error("malformed/truncated policy reply did not poison the retired channel");
}

void policy_lifecycle_regressions() {
  std::vector<std::string> errors;
  for (const std::string stage : {"decision", "path", "terminal", "queued", "abort"}) {
    try {
      silent_rpc(stage == "queued" || stage == "abort" ? "path" : stage,
                 stage == "queued" || stage == "abort", stage == "abort");
      std::cout << "policy-lifecycle " << stage << " PASS\n";
    } catch (const std::exception& error) {
      errors.push_back(error.what());
      std::cerr << "policy-lifecycle " << stage << " FAIL: " << error.what() << '\n';
    }
  }
  for (const auto& test : std::vector<std::pair<std::string, std::function<void()>>>{
           {"queued-key", queued_key_eligibility},
           {"malformed", []() { poisoned_reply(false); }},
           {"truncated", []() { poisoned_reply(true); }}}) {
    try {
      test.second();
      std::cout << "policy-lifecycle " << test.first << " PASS\n";
    } catch (const std::exception& error) {
      errors.push_back(error.what());
      std::cerr << "policy-lifecycle " << test.first << " FAIL: " << error.what() << '\n';
    }
  }
  if (!errors.empty()) throw std::runtime_error("policy lifecycle regressions failed");
}

}  // namespace

int main() {
  int descriptors[2] = {-1, -1};
  if (::socketpair(AF_UNIX, SOCK_SEQPACKET, 0, descriptors) != 0) {
    std::cerr << "socketpair failed\n";
    return 2;
  }
  try {
    policy_lifecycle_regressions();
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
