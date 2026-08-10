#include "checkpoint_analytics_terminal_transport.hpp"

#include <cstdlib>
#include <functional>
#include <stdexcept>
#include <string>
#include <vector>

#include <sys/socket.h>
#include <unistd.h>

namespace {

void require(bool condition, const char* message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

void require_throws(const std::function<void()>& callback, const char* message) {
  try {
    callback();
  } catch (const std::exception&) {
    return;
  }
  throw std::runtime_error(message);
}

}  // namespace

int main() {
  int descriptors[2] = {-1, -1};
  require(::socketpair(AF_UNIX, SOCK_DGRAM, 0, descriptors) == 0, "socketpair failed");
  const std::string write_fd = std::to_string(descriptors[1]);
  require(
      ::setenv(vast::CheckpointAnalyticsTerminalTransport::kFdEnvironment, write_fd.c_str(), 1) == 0,
      "setenv failed");

  vast::CheckpointAnalyticsTerminal complete;
  complete.transport_pts_ns = 123456789;
  complete.status = vast::CheckpointAnalyticsTerminalStatus::kCompleted;
  complete.objects = 3;
  complete.branch_id = "damage";
  complete.terminal_reason = "native_result_committed";
  complete.detector = "damage-net-v1";
  complete.backend = "openvino-gva";

  auto emitter = vast::CheckpointAnalyticsTerminalEmitter::from_environment();
  emitter.emit(complete);
  const auto received = vast::CheckpointAnalyticsTerminalTransport::receive(descriptors[0]);
  require(received.transport_pts_ns == complete.transport_pts_ns, "transport PTS mismatch");
  require(received.status == complete.status, "terminal status mismatch");
  require(received.objects == complete.objects, "object count mismatch");
  require(received.branch_id == complete.branch_id, "branch mismatch");
  require(received.terminal_reason == complete.terminal_reason, "terminal reason mismatch");
  require(received.detector == complete.detector, "detector mismatch");
  require(received.backend == complete.backend, "backend mismatch");

  auto malformed = vast::CheckpointAnalyticsTerminalTransport::encode(complete);
  malformed.push_back(0);
  require_throws(
      [&]() { vast::CheckpointAnalyticsTerminalTransport::decode(malformed.data(), malformed.size()); },
      "trailing analytics terminal byte was accepted");

  vast::CheckpointAnalyticsTerminal invalid_drop = complete;
  invalid_drop.status = vast::CheckpointAnalyticsTerminalStatus::kDrop;
  invalid_drop.objects = 1;
  require_throws(
      [&]() { vast::CheckpointAnalyticsTerminalTransport::encode(invalid_drop); },
      "drop with accepted objects was accepted");

  vast::CheckpointAnalyticsTerminal identity = complete;
  identity.detector = "identity";
  require_throws(
      [&]() { vast::CheckpointAnalyticsTerminalTransport::encode(identity); },
      "identity adapter terminal was accepted");

  ::unsetenv(vast::CheckpointAnalyticsTerminalTransport::kFdEnvironment);
  ::close(descriptors[0]);
  ::close(descriptors[1]);
  return 0;
}
