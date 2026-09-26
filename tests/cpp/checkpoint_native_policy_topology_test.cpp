#define main vast_native_gst_probe_embedded_main
#include "../../deploy/native_gst_probe/vast_native_gst_probe.cpp"
#undef main

#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <string>
#include <utility>

#include <sys/socket.h>
#include <unistd.h>

namespace {

struct Descriptors {
  int event_pipe[2] = {-1, -1};
  int control_pipe[2] = {-1, -1};
  int status_pipe[2] = {-1, -1};
  int data_pipe[2] = {-1, -1};
  int policy_socket[2] = {-1, -1};
  int execution_socket[2] = {-1, -1};

  Descriptors() {
    if (::pipe(event_pipe) != 0 || ::pipe(control_pipe) != 0 ||
        ::pipe(status_pipe) != 0 || ::pipe(data_pipe) != 0 ||
        ::socketpair(AF_UNIX, SOCK_SEQPACKET, 0, policy_socket) != 0 ||
        ::socketpair(AF_UNIX, SOCK_SEQPACKET, 0, execution_socket) != 0) {
      throw std::runtime_error("failed to create native-policy topology test descriptors");
    }
  }

  ~Descriptors() {
    for (int* pair : {event_pipe, control_pipe, status_pipe, data_pipe, policy_socket, execution_socket}) {
      for (int index = 0; index < 2; ++index) {
        if (pair[index] >= 0) {
          ::close(pair[index]);
          pair[index] = -1;
        }
      }
    }
  }
};

void set_integer_environment(const char* name, int value) {
  const std::string text = std::to_string(value);
  if (::setenv(name, text.c_str(), 1) != 0) {
    throw std::runtime_error(std::string("failed to set ") + name);
  }
}

Args checkpoint_args(const std::filesystem::path& output, const std::string& system) {
  Args args;
  args.system = system;
  args.role = "checkpoint_branch";
  args.run_id = "run-native-policy-topology-0001";
  args.output_dir = output.string();
  args.streams = 1;
  args.logical_stream_id = 0;
  args.checkpoint_branch = "damage";
  args.dataset_id = "kpp";
  args.source_sha256 = std::string(64, 'a');
  args.checkpoint_container = "mp4";
  args.checkpoint_codec = "h264";
  args.source_duration_ns = 1;
  args.source_replay = "continuous";
  args.checkpoint_analytics_mode = "native_terminal_socket_v1";
  args.detect_bin = "fakesrc name={branch}";
  args.deadline_ms = 100.0;
  args.executable_path = "/proc/self/exe";
  return args;
}

void configure_environment(const Descriptors& descriptors, const std::string& worker_id) {
  set_integer_environment("VAST_CHECKPOINT_EVENT_FD", descriptors.event_pipe[1]);
  set_integer_environment("VAST_CHECKPOINT_CONTROL_FD", descriptors.control_pipe[0]);
  set_integer_environment("VAST_CHECKPOINT_STATUS_FD", descriptors.status_pipe[1]);
  set_integer_environment("VAST_CHECKPOINT_ADMISSION_DATA_FD", descriptors.data_pipe[0]);
  set_integer_environment("VAST_CHECKPOINT_POLICY_FD", descriptors.policy_socket[0]);
  set_integer_environment("VAST_CHECKPOINT_ANALYTICS_EXECUTION_FD", descriptors.execution_socket[0]);
  ::unsetenv("VAST_CHECKPOINT_ANALYTICS_EXECUTION_SOCKET");
  ::setenv("VAST_CHECKPOINT_WORKER_ID", worker_id.c_str(), 1);
  ::setenv("VAST_CHECKPOINT_RUN_ID", "run-native-policy-topology-0001", 1);
  ::setenv("VAST_CHECKPOINT_TOPOLOGY_KIND", "openvino_gva", 1);
  ::setenv("VAST_CHECKPOINT_STREAM_ID", "0", 1);
  ::setenv("VAST_CHECKPOINT_ADMISSION_MODE", "native_common_source_coordinator", 1);
}

void expect_rejected(const Args& args, const char* expected) {
  bool rejected = false;
  try {
    NativeProbeRuntime runtime(args);
  } catch (const std::exception& error) {
    rejected = std::string(error.what()).find(expected) != std::string::npos;
  }
  if (!rejected) {
    throw std::runtime_error(std::string("native policy topology did not reject: ") + expected);
  }
}

}  // namespace

int main() {
  std::filesystem::path temporary;
  try {
    char template_path[] = "/tmp/vast-native-policy-topology-XXXXXX";
    const char* created = ::mkdtemp(template_path);
    if (created == nullptr) {
      throw std::runtime_error("failed to create native-policy topology temporary directory");
    }
    temporary = created;

    {
      Descriptors descriptors;
      configure_environment(descriptors, "stream-0-branch-damage");
      NativeProbeRuntime runtime(checkpoint_args(temporary / "openvino", "openvino_gva"));
    }
    {
      Descriptors descriptors;
      configure_environment(descriptors, "stream-0-branch-damage");
      expect_rejected(
          checkpoint_args(temporary / "unsupported", "deepstream"),
          "topology-specific to gstreamer_custom and openvino_gva");
    }
    {
      Descriptors descriptors;
      configure_environment(descriptors, "stream-0-branch-damage!");
      expect_rejected(
          checkpoint_args(temporary / "unsafe-worker", "openvino_gva"),
          "requires a stable worker ID");
    }
    std::filesystem::remove_all(temporary);
    return 0;
  } catch (const std::exception& error) {
    if (!temporary.empty()) {
      std::error_code ignored;
      std::filesystem::remove_all(temporary, ignored);
    }
    std::cerr << error.what() << '\n';
    return 1;
  }
}
