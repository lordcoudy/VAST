#include "checkpoint_runtime_emitter.hpp"

#include <unistd.h>

#include <array>
#include <cstdlib>
#include <iostream>
#include <string>

int main() {
  std::array<int, 2> pipe_fds{};
  if (::pipe(pipe_fds.data()) != 0) {
    return 2;
  }
  const std::string fd = std::to_string(pipe_fds[1]);
  ::setenv("VAST_CHECKPOINT_EVENT_FD", fd.c_str(), 1);
  ::setenv("VAST_CHECKPOINT_WORKER_ID", "worker-\"one", 1);
  ::setenv("VAST_CHECKPOINT_RUN_ID", "run-1", 1);
  ::setenv("VAST_CHECKPOINT_TOPOLOGY_KIND", "shared_video_dag", 1);
  ::setenv("VAST_CHECKPOINT_STREAM_ID", "3", 1);

  auto emitter = vast::CheckpointRuntimeEmitter::from_environment();
  emitter.emit("run-1:3:0", 0, "dataset:3:sha:pts0", "source_read", "source", "shared", "source", {}, 1000);
  emitter.emit_with_admission(
      "run-1:3:0",
      0,
      "dataset:3:sha:pts0",
      "stage_complete",
      "decode",
      "shared",
      "decode",
      {"source"},
      999,
      "run-1:3:admission:1",
      "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef");
  emitter.emit_branch_terminal_with_admission(
      "run-1:3:0",
      0,
      "dataset:3:sha:pts0",
      "branch_complete",
      "damage",
      "damage",
      "damage-complete",
      {"damage-analytics"},
      1001,
      "run-1:3:admission:1",
      "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      "native_result_committed",
      3,
      "damage-net-v1",
      "gstreamer-native");
  ::close(pipe_fds[1]);

  std::string payload;
  std::array<char, 4096> buffer{};
  while (true) {
    const ssize_t count = ::read(pipe_fds[0], buffer.data(), buffer.size());
    if (count <= 0) {
      break;
    }
    payload.append(buffer.data(), static_cast<std::size_t>(count));
  }
  ::close(pipe_fds[0]);
  std::cout << payload;
  return emitter.sequence() == 3 ? 0 : 3;
}
