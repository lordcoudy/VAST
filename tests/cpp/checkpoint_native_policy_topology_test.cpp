#define VAST_NATIVE_PROBE_TESTING 1
#define main vast_native_gst_probe_embedded_main
#include "../../deploy/native_gst_probe/vast_native_gst_probe.cpp"
#undef main

#include <filesystem>
#include <iostream>
#include <poll.h>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

struct NativeProbeRuntimeTestAccess {
  static void admit(NativeProbeRuntime& runtime, std::uint64_t pts) {
    Trace trace;
    trace.stream_id = 0;
    trace.frame_id = 7;
    trace.ingress_ms = 1000;
    trace.source_pts_ns = pts;
    trace.admission_id = "test-admission-7";
    trace.payload_sha256 = std::string(64, 'a');
    runtime.states_.front().local_traces_by_pts.emplace(pts, trace);
    runtime.states_.front().traces.push_back(trace);
  }

  static void handle(
      NativeProbeRuntime& runtime,
      const vast::CheckpointAnalyticsTerminal& terminal) {
    runtime.handle_checkpoint_analytics_terminal(terminal);
  }

  static void register_policy_entry(
      NativeProbeRuntime& runtime,
      const std::string& branch,
      std::uint64_t pts) {
    runtime.states_.front().checkpoint_policy_executions_by_branch[branch][pts] =
        NativePolicyExecution{};
  }

  static bool has_admitted_pts(const NativeProbeRuntime& runtime, std::uint64_t pts) {
    return runtime.states_.front().local_traces_by_pts.count(pts) != 0;
  }
  static std::string execute_branch(NativeProbeRuntime& runtime,const std::string& branch,std::uint64_t pts) {
    vast::CheckpointAnalyticsExecutionRequest request;
    request.request_id=NativeProbeRuntime::sha256_text(branch);request.run_id=runtime.args_.run_id;
    request.arm_id=std::string(64,'2');request.worker_id=runtime.checkpoint_worker_id_;
    request.input_frame_key="kpp:0:"+runtime.args_.source_sha256+":0:"+std::to_string(pts);
    request.stream_id=0;request.frame_id=7;request.transport_pts_ns=pts;request.branch=branch;
    request.decision={"decision-"+branch,1,"cpu","implementation","emitter",std::string(64,'e')};
    request.deadline_monotonic_ns=vast::CheckpointIoDeadline::monotonic_now_ns()+500'000'000ULL;
    request.format="RGB";request.width=1;request.height=1;request.stride=3;
    request.preprocessing_contract_sha256=std::string(64,'f');
    const std::vector<std::uint8_t> pixels{1,2,3};request.raw_input_sha256=NativeProbeRuntime::sha256_raw_bytes(pixels);
    try {runtime.checkpoint_execution_client_for_branch(branch).execute(request,pixels.data(),pixels.size());}
    catch(const std::exception& exc) {return exc.what();}
    return "unexpected success";
  }
  static void receive(NativeProbeRuntime& runtime) {runtime.receive_checkpoint_access_units();}
};

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

constexpr std::uint64_t kTestPts = 123456789;
const std::vector<std::string> kBranches = {
    "damage", "foreign_object", "plate_number", "vehicle_type"};

std::string detector_identity(const std::string& branch) {
  return branch + "-detector;model_sha256=" + std::string(64, 'b') +
         ";weights_sha256=" + std::string(64, 'c');
}

std::string worker_detector_identity(const std::string& branch) {
  return "opaque_" + branch + ";model_sha256=" + std::string(64, 'd');
}

void configure_model_bindings() {
  ::setenv("VAST_CHECKPOINT_ANALYTICS_EXTERNAL_EXECUTION_MODE", "1", 1);
  for (const std::string& branch : kBranches) {
    const std::string prefix = "VAST_CHECKPOINT_ANALYTICS_";
    ::setenv((prefix + "DETECTOR_ID_" + branch).c_str(), (branch + "-detector").c_str(), 1);
    ::setenv((prefix + "MODEL_SHA256_" + branch).c_str(), std::string(64, 'b').c_str(), 1);
    ::setenv((prefix + "WEIGHTS_SHA256_" + branch).c_str(), std::string(64, 'c').c_str(), 1);
    ::setenv((prefix + "FACTORY_" + branch).c_str(), "gvadetect", 1);
    ::setenv((prefix + "DROP_DETECTOR_" + branch).c_str(),
             worker_detector_identity(branch).c_str(), 1);
    for (const std::string& resource : {"CPU", "GPU"}) {
      ::setenv((prefix + resource + "_IMPLEMENTATION_ID_" + branch).c_str(),
               ("qualified-" + resource + "-implementation").c_str(), 1);
      ::setenv((prefix + resource + "_EMITTER_ID_" + branch).c_str(),
               ("qualified-" + resource + "-emitter").c_str(), 1);
      ::setenv((prefix + resource + "_EMITTER_SHA256_" + branch).c_str(),
               std::string(64, 'e').c_str(), 1);
    }
  }
}

vast::CheckpointAnalyticsTerminal queue_drop(
    const std::string& branch,
    bool postdecode) {
  vast::CheckpointAnalyticsTerminal terminal;
  terminal.transport_pts_ns = kTestPts;
  terminal.status = vast::CheckpointAnalyticsTerminalStatus::kDrop;
  terminal.objects = 0;
  terminal.branch_id = branch;
  terminal.terminal_reason = postdecode
      ? "native_postdecode_preprocess_queue_full_drop_newest"
      : "native_pre_detector_queue_full_drop_newest";
  terminal.detector = postdecode ? "runtime-bound-postdecode-drop" : detector_identity(branch);
  terminal.backend = postdecode ? "runtime-bound-postdecode-drop" : "openvino-dlstreamer:gvadetect";
  return terminal;
}

Args drop_args(const std::filesystem::path& output, bool shared) {
  Args args = checkpoint_args(output, "openvino_gva");
  if (shared) {
    args.role = "checkpoint_shared";
    args.checkpoint_branch.clear();
    args.checkpoint_branches = "damage,foreign_object,plate_number,vehicle_type";
  }
  return args;
}

std::vector<std::string> drain_event_lines(int fd) {
  std::string data;
  while (true) {
    pollfd descriptor{fd, POLLIN, 0};
    const int ready = ::poll(&descriptor, 1, 0);
    if (ready < 0) {
      throw std::runtime_error("native drop test could not poll event pipe");
    }
    if (ready == 0 || (descriptor.revents & POLLIN) == 0) {
      break;
    }
    char buffer[8192];
    const ssize_t size = ::read(fd, buffer, sizeof(buffer));
    if (size <= 0) {
      throw std::runtime_error("native drop test failed to drain event pipe");
    }
    data.append(buffer, static_cast<std::size_t>(size));
  }
  std::vector<std::string> lines;
  std::istringstream input(data);
  std::string line;
  while (std::getline(input, line)) {
    if (!line.empty()) {
      lines.push_back(line);
    }
  }
  return lines;
}

void expect_no_policy_or_inference_calls(const Descriptors& descriptors) {
  for (int fd : {descriptors.policy_socket[1], descriptors.execution_socket[1]}) {
    pollfd descriptor{fd, POLLIN, 0};
    const int ready = ::poll(&descriptor, 1, 0);
    if (ready < 0) {
      throw std::runtime_error("native queue drop could not inspect policy/inference socket");
    }
    char byte = 0;
    if (ready > 0 && (descriptor.revents & POLLIN) != 0 &&
        ::recv(fd, &byte, 1, MSG_PEEK | MSG_DONTWAIT) != 0) {
      throw std::runtime_error("native queue drop sent a policy or inference call");
    }
  }
}

void expect_rejected_drop(
    NativeProbeRuntime& runtime,
    const vast::CheckpointAnalyticsTerminal& terminal,
    const std::string& message,
    int event_fd) {
  bool rejected = false;
  try {
    NativeProbeRuntimeTestAccess::handle(runtime, terminal);
  } catch (const std::exception& error) {
    rejected = std::string(error.what()).find(message) != std::string::npos;
  }
  if (!rejected || !drain_event_lines(event_fd).empty()) {
    throw std::runtime_error("native queue drop was not rejected before event emission: " + message);
  }
}

void exercise_valid_drop(
    const std::filesystem::path& output,
    bool shared,
    bool postdecode) {
  Descriptors descriptors;
  configure_environment(descriptors, shared ? "stream-0-shared" : "stream-0-branch-damage");
  NativeProbeRuntime runtime(drop_args(output, shared));
  NativeProbeRuntimeTestAccess::admit(runtime, kTestPts);
  const std::vector<std::string> branches = shared ? kBranches : std::vector<std::string>{"damage"};
  for (const std::string& branch : branches) {
    NativeProbeRuntimeTestAccess::handle(runtime, queue_drop(branch, postdecode));
  }
  const std::vector<std::string> lines = drain_event_lines(descriptors.event_pipe[0]);
  if (lines.size() != branches.size()) {
    throw std::runtime_error("native queue drop did not emit one terminal per branch");
  }
  for (std::size_t index = 0; index < branches.size(); ++index) {
    const std::string& branch = branches[index];
    vast::CheckpointAnalyticsExecutionResult completed_result;
    completed_result.branch = branch;
    completed_result.terminal_status = "completed";
    completed_result.terminal_reason = "external_worker_completed";
    completed_result.detector = worker_detector_identity(branch);
    completed_result.backend = "analytics-execution:openvino_cpu";
    const auto completed_terminal = vast::checkpoint_terminal_from_validated_execution(
        completed_result, kTestPts, branch);
    const std::string expected_parent =
        "run-native-policy-topology-0001:0:7:" +
        std::string(postdecode ? (shared ? "shared:decode" : branch + ":decode")
                               : (shared ? branch + ":fanout" : branch + ":preprocess"));
    if (lines[index].find("\"event_kind\":\"branch_drop\"") == std::string::npos ||
        lines[index].find("\"branch_id\":\"" + branch + "\"") == std::string::npos ||
        lines[index].find("\"parent_execution_ids\":[\"" + expected_parent + "\"]") ==
            std::string::npos ||
        lines[index].find("\"terminal_reason\":\"" +
                              queue_drop(branch, postdecode).terminal_reason + "\"") ==
            std::string::npos ||
        lines[index].find("\"objects\":0") == std::string::npos ||
        lines[index].find("\"detector\":\"" + completed_terminal.detector + "\"") ==
            std::string::npos ||
        lines[index].find("\"backend\":\"openvino-dlstreamer:gvadetect\"") ==
            std::string::npos ||
        lines[index].find("\"admission_id\":\"test-admission-7\"") ==
            std::string::npos) {
      throw std::runtime_error("native queue drop terminal identity or lineage drifted");
    }
  }
  if (NativeProbeRuntimeTestAccess::has_admitted_pts(runtime, kTestPts)) {
    throw std::runtime_error("fully terminalized native drop frame retained its admitted trace");
  }
  expect_no_policy_or_inference_calls(descriptors);
}

void expect_rejected(const Args& args, const char* expected);

void exercise_invalid_drops(const std::filesystem::path& output) {
  {
    Descriptors descriptors;
    configure_environment(descriptors, "stream-0-branch-damage");
    NativeProbeRuntime runtime(drop_args(output / "wrong-origin", false));
    NativeProbeRuntimeTestAccess::admit(runtime, kTestPts);
    auto terminal = queue_drop("damage", false);
    terminal.terminal_reason = "unverified_queue_drop";
    expect_rejected_drop(runtime, terminal, "verified queue origin", descriptors.event_pipe[0]);
    terminal = queue_drop("damage", false);
    terminal.detector = "unverified-detector";
    expect_rejected_drop(runtime, terminal, "detector/backend binding drifted", descriptors.event_pipe[0]);
    terminal = queue_drop("damage", false);
    terminal.backend = "openvino-dlstreamer:other";
    expect_rejected_drop(runtime, terminal, "detector/backend binding drifted", descriptors.event_pipe[0]);
    terminal = queue_drop("damage", false);
    terminal.objects = 1;
    expect_rejected_drop(runtime, terminal, "reported accepted objects", descriptors.event_pipe[0]);
    terminal = queue_drop("damage", true);
    terminal.detector = "unverified-placeholder";
    expect_rejected_drop(runtime, terminal, "invalid terminal binding", descriptors.event_pipe[0]);
    terminal = queue_drop("damage", false);
    terminal.status = vast::CheckpointAnalyticsTerminalStatus::kCompleted;
    expect_rejected_drop(runtime, terminal, "completion reason drifted", descriptors.event_pipe[0]);
    expect_no_policy_or_inference_calls(descriptors);
  }
  {
    Descriptors descriptors;
    configure_environment(descriptors, "stream-0-branch-damage");
    NativeProbeRuntime runtime(drop_args(output / "orphan", false));
    expect_rejected_drop(
        runtime, queue_drop("damage", false), "no admitted transport PTS", descriptors.event_pipe[0]);
    expect_no_policy_or_inference_calls(descriptors);
  }
  {
    Descriptors descriptors;
    configure_environment(descriptors, "stream-0-branch-damage");
    NativeProbeRuntime runtime(drop_args(output / "post-entry", false));
    NativeProbeRuntimeTestAccess::admit(runtime, kTestPts);
    NativeProbeRuntimeTestAccess::register_policy_entry(runtime, "damage", kTestPts);
    expect_rejected_drop(
        runtime, queue_drop("damage", false), "followed policy path entry", descriptors.event_pipe[0]);
    expect_no_policy_or_inference_calls(descriptors);
  }
  {
    Descriptors descriptors;
    configure_environment(descriptors, "stream-0-shared");
    NativeProbeRuntime runtime(drop_args(output / "duplicate", true));
    NativeProbeRuntimeTestAccess::admit(runtime, kTestPts);
    NativeProbeRuntimeTestAccess::handle(runtime, queue_drop("damage", false));
    if (drain_event_lines(descriptors.event_pipe[0]).size() != 1) {
      throw std::runtime_error("native duplicate setup did not emit first terminal");
    }
    expect_rejected_drop(
        runtime, queue_drop("damage", false), "duplicate checkpoint analytics terminal",
        descriptors.event_pipe[0]);
    expect_no_policy_or_inference_calls(descriptors);
  }
  {
    const std::string pin = "VAST_CHECKPOINT_ANALYTICS_DROP_DETECTOR_damage";
    ::unsetenv(pin.c_str());
    Descriptors descriptors;
    configure_environment(descriptors, "stream-0-branch-damage");
    expect_rejected(
        drop_args(output / "missing-semantic-pin", false),
        "missing checkpoint analytics model binding");
    expect_no_policy_or_inference_calls(descriptors);
    ::setenv(pin.c_str(), worker_detector_identity("damage").c_str(), 1);
  }
  {
    for (const std::string& field : {"IMPLEMENTATION_ID", "EMITTER_ID", "EMITTER_SHA256"}) {
      ::unsetenv(("VAST_CHECKPOINT_ANALYTICS_GPU_" + field + "_damage").c_str());
    }
    Descriptors descriptors;
    configure_environment(descriptors, "stream-0-branch-damage");
    expect_rejected(
        drop_args(output / "partial-external-bindings", false),
        "incomplete external execution bindings");
    expect_no_policy_or_inference_calls(descriptors);
    configure_model_bindings();
  }
  {
    const std::string pin = "VAST_CHECKPOINT_ANALYTICS_DROP_DETECTOR_damage";
    const std::string malformed = "opaque_damage;model_sha256=" + std::string(64, 'A');
    Descriptors descriptors;
    configure_environment(descriptors, "stream-0-branch-damage");
    NativeProbeRuntime runtime(drop_args(output / "post-start-invalid-semantic-pin", false));
    NativeProbeRuntimeTestAccess::admit(runtime, kTestPts);
    ::setenv(pin.c_str(), malformed.c_str(), 1);
    auto unverified_proxy = queue_drop("damage", false);
    unverified_proxy.detector = "unverified-proxy";
    expect_rejected_drop(
        runtime, unverified_proxy, "detector/backend binding drifted",
        descriptors.event_pipe[0]);
    expect_rejected_drop(
        runtime, queue_drop("damage", false), "semantic detector pin is invalid",
        descriptors.event_pipe[0]);
    for (const std::string& reserved : {"identity", "topology_only"}) {
      const std::string invalid = reserved + ";model_sha256=" + std::string(64, 'd');
      ::setenv(pin.c_str(), invalid.c_str(), 1);
      expect_rejected_drop(
          runtime, queue_drop("damage", false), "semantic detector pin is invalid",
          descriptors.event_pipe[0]);
    }
    expect_no_policy_or_inference_calls(descriptors);
    ::setenv(pin.c_str(), worker_detector_identity("damage").c_str(), 1);
  }
  {
    const std::string pin = "VAST_CHECKPOINT_ANALYTICS_DROP_DETECTOR_damage";
    const std::string malformed = "opaque_damage;model_sha256=" + std::string(64, 'A');
    ::setenv(pin.c_str(), malformed.c_str(), 1);
    Descriptors descriptors;
    configure_environment(descriptors, "stream-0-branch-damage");
    expect_rejected(
        drop_args(output / "startup-invalid-semantic-pin", false),
        "semantic detector pin is invalid");
    expect_no_policy_or_inference_calls(descriptors);
    ::setenv(pin.c_str(), worker_detector_identity("damage").c_str(), 1);
  }
  {
    ::unsetenv("VAST_CHECKPOINT_ANALYTICS_EXTERNAL_EXECUTION_MODE");
    Descriptors descriptors;
    configure_environment(descriptors, "stream-0-branch-damage");
    expect_rejected(
        drop_args(output / "missing-external-mode", false),
        "mode and branch bindings disagree");
    expect_no_policy_or_inference_calls(descriptors);
  }
  {
    ::setenv("VAST_CHECKPOINT_ANALYTICS_EXTERNAL_EXECUTION_MODE", "invalid", 1);
    Descriptors descriptors;
    configure_environment(descriptors, "stream-0-branch-damage");
    expect_rejected(
        drop_args(output / "invalid-external-mode", false),
        "external execution mode marker is invalid");
    expect_no_policy_or_inference_calls(descriptors);
    ::setenv("VAST_CHECKPOINT_ANALYTICS_EXTERNAL_EXECUTION_MODE", "1", 1);
  }
  {
    const std::string pin = "VAST_CHECKPOINT_ANALYTICS_DROP_DETECTOR_damage";
    ::unsetenv(pin.c_str());
    for (const std::string& resource : {"CPU", "GPU"}) {
      for (const std::string& field : {"IMPLEMENTATION_ID", "EMITTER_ID", "EMITTER_SHA256"}) {
        ::unsetenv(("VAST_CHECKPOINT_ANALYTICS_" + resource + "_" + field + "_damage").c_str());
      }
    }
    Descriptors descriptors;
    configure_environment(descriptors, "stream-0-branch-damage");
    expect_rejected(
        drop_args(output / "missing-all-external-pins", false),
        "mode and branch bindings disagree");
    expect_no_policy_or_inference_calls(descriptors);
    configure_model_bindings();
  }
}

void exercise_legacy_drop(const std::filesystem::path& output) {
  Descriptors descriptors;
  configure_environment(descriptors, "stream-0-branch-damage");
  ::unsetenv("VAST_CHECKPOINT_ANALYTICS_EXTERNAL_EXECUTION_MODE");
  const std::string pin = "VAST_CHECKPOINT_ANALYTICS_DROP_DETECTOR_damage";
  ::unsetenv(pin.c_str());
  for (const std::string& resource : {"CPU", "GPU"}) {
    for (const std::string& field : {"IMPLEMENTATION_ID", "EMITTER_ID", "EMITTER_SHA256"}) {
      ::unsetenv(("VAST_CHECKPOINT_ANALYTICS_" + resource + "_" + field + "_damage").c_str());
    }
  }
  NativeProbeRuntime runtime(drop_args(output, false));
  NativeProbeRuntimeTestAccess::admit(runtime, kTestPts);
  ::setenv(pin.c_str(), worker_detector_identity("damage").c_str(), 1);
  expect_rejected_drop(
      runtime, queue_drop("damage", false), "incomplete external execution bindings",
      descriptors.event_pipe[0]);
  ::unsetenv(pin.c_str());
  NativeProbeRuntimeTestAccess::handle(runtime, queue_drop("damage", false));
  const auto lines = drain_event_lines(descriptors.event_pipe[0]);
  if (lines.size() != 1 ||
      lines.front().find("\"detector\":\"" + detector_identity("damage") + "\"") ==
          std::string::npos ||
      lines.front().find("\"backend\":\"openvino-dlstreamer:gvadetect\"") ==
          std::string::npos) {
    throw std::runtime_error("legacy native CPU drop identity changed");
  }
  expect_no_policy_or_inference_calls(descriptors);
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

void exercise_real_independent_study_channels(const std::filesystem::path& output) {
  Descriptors descriptors;
  configure_environment(descriptors,"stream-0-shared");
  const auto path=(output.parent_path()/"study-channels.sock").string();
  const int listener=::socket(AF_UNIX,SOCK_SEQPACKET|SOCK_CLOEXEC|SOCK_NONBLOCK,0);
  sockaddr_un address{};address.sun_family=AF_UNIX;
  std::memcpy(address.sun_path,path.c_str(),path.size()+1);
  if(listener<0||::bind(listener,reinterpret_cast<sockaddr*>(&address),sizeof(address))||::listen(listener,8))
    throw std::runtime_error("real study channel listener failed");
  ::unsetenv("VAST_CHECKPOINT_ANALYTICS_EXECUTION_FD");
  ::setenv("VAST_CHECKPOINT_ANALYTICS_EXECUTION_SOCKET",path.c_str(),1);
  ::setenv("VAST_CHECKPOINT_STARTUP_DEADLINE_MONOTONIC_NS",
      std::to_string(vast::CheckpointIoDeadline::monotonic_now_ns()+5'000'000'000ULL).c_str(),1);
  std::ifstream boot("/proc/sys/kernel/random/boot_id");std::string boot_id;std::getline(boot,boot_id);
  std::array<char,256> clock_name{};const auto clock_length=::readlink("/proc/self/ns/time",clock_name.data(),clock_name.size());
  if(boot_id.empty()||clock_length<=0) throw std::runtime_error("actual fixture clock domain unavailable");
  ::setenv("VAST_CHECKPOINT_WORKER_CLOCK_BOOT_ID",boot_id.c_str(),1);
  ::setenv("VAST_CHECKPOINT_WORKER_CLOCK_TIME_NAMESPACE",std::string(clock_name.data(),clock_length).c_str(),1);
  auto args=drop_args(output,true);
  args.checkpoint_study_kind="finite-component-study";args.source_replay="finite";
  args.checkpoint_study_width=1920;args.checkpoint_study_height=1080;
  args.checkpoint_study_waits_path=(output.parent_path()/"waits.jsonl").string();
  args.checkpoint_study_accounting_path=(output.parent_path()/"receives.jsonl").string();
  args.checkpoint_analytics_client_mode="branch";
  std::vector<int> accepted;
  std::size_t simultaneous_requests=0;
  bool sealed_payloads=true;
  std::string expected_payload_sha;
  {
    NativeProbeRuntime runtime(args);
    if(!std::filesystem::is_regular_file(args.checkpoint_study_waits_path)||
       !std::filesystem::is_regular_file(args.checkpoint_study_accounting_path))
      throw std::runtime_error("native study has no owned wait/receive journals before callbacks");
    while(true) {int socket=::accept4(listener,nullptr,nullptr,SOCK_CLOEXEC|SOCK_NONBLOCK);
      if(socket<0) {if(errno!=EAGAIN&&errno!=EWOULDBLOCK) throw std::runtime_error("actual accept failed"); break;}
      accepted.push_back(socket);
    }
    NativeProbeRuntimeTestAccess::admit(runtime,kTestPts);
    std::array<std::string,2> failures;
    std::thread first([&]{failures[0]=NativeProbeRuntimeTestAccess::execute_branch(runtime,"damage",kTestPts);});
    std::thread second([&]{failures[1]=NativeProbeRuntimeTestAccess::execute_branch(runtime,"foreign_object",kTestPts);});
    std::vector<pollfd> pending;for(int socket:accepted) pending.push_back({socket,POLLIN,0});
    const auto inspect_end=std::chrono::steady_clock::now()+std::chrono::milliseconds(200);
    while(simultaneous_requests<2&&std::chrono::steady_clock::now()<inspect_end) {
      if(::poll(pending.data(),pending.size(),10)<0) throw std::runtime_error("real branch-channel poll failed");
      for(auto& item:pending) if(item.fd>=0&&(item.revents&POLLIN)) {
        std::array<char,65536> bytes{};std::array<char,CMSG_SPACE(sizeof(int))> ancillary{};
        iovec iov{bytes.data(),bytes.size()};msghdr message{};message.msg_iov=&iov;message.msg_iovlen=1;
        message.msg_control=ancillary.data();message.msg_controllen=ancillary.size();
        const auto size=::recvmsg(item.fd,&message,MSG_DONTWAIT|MSG_CMSG_CLOEXEC);
        auto* control=CMSG_FIRSTHDR(&message);int payload=-1;
        if(control&&control->cmsg_level==SOL_SOCKET&&control->cmsg_type==SCM_RIGHTS)
          std::memcpy(&payload,CMSG_DATA(control),sizeof(int));
        const int required=F_SEAL_WRITE|F_SEAL_GROW|F_SEAL_SHRINK|F_SEAL_SEAL;
        sealed_payloads=sealed_payloads&&size>0&&payload>=0&&(::fcntl(payload,F_GET_SEALS)&required)==required;
        if(payload>=0) ::close(payload);
        ++simultaneous_requests;item.fd=-1;
      }
    }
    // No reply or peer close occurs before this overlap observation.
    first.join();second.join();
    if(failures[0].find("deadline")==std::string::npos||failures[1].find("deadline")==std::string::npos)
      throw std::runtime_error("independent branch requests did not retain original deadlines");
    vast::CheckpointAdmissionFrame delivered;
    delivered.sequence=1;delivered.keyframe=true;delivered.source_cycle=0;
    delivered.access_unit_pts_ns=0;delivered.transport_pts_ns=0;delivered.access_unit_dts_ns=0;
    delivered.duration_ns=500'000'000;delivered.admission_id=args.run_id+":0:admission:1";
    delivered.input_frame_key="kpp:0:"+args.source_sha256+":0:0";
    delivered.payload={0,0,0,1,0x65,0x88,0x84};
    gchar* digest=g_compute_checksum_for_data(G_CHECKSUM_SHA256,delivered.payload.data(),delivered.payload.size());
    delivered.payload_sha256=digest;g_free(digest);
    expected_payload_sha=delivered.payload_sha256;
    vast::CheckpointAdmissionTransport::write_frame(descriptors.data_pipe[1],delivered);
    ::close(descriptors.data_pipe[1]);descriptors.data_pipe[1]=-1;
    NativeProbeRuntimeTestAccess::receive(runtime);
  }
  const auto read_original=[](const std::string& path) {
    std::ifstream source(path);return std::string(std::istreambuf_iterator<char>(source),{});};
  const auto waits=read_original(args.checkpoint_study_waits_path);
  const auto receives=read_original(args.checkpoint_study_accounting_path);
  const auto occurrences=[](const std::string& text,const std::string& needle) {
    std::size_t count=0,offset=0;while((offset=text.find(needle,offset))!=std::string::npos) {++count;offset+=needle.size();}return count;};
  if(occurrences(waits,"\"phase\":\"begin\"")!=2||occurrences(waits,"\"phase\":\"released\"")!=2||
      occurrences(waits,"\"reply_ns\":null")!=4||occurrences(waits,"\"boot_id\":\""+boot_id+"\"")!=4||
      occurrences(receives,"\"type\":\"recipient_received\"")!=1||
      receives.find("\"planned_schedule_offset_ns\":0")==std::string::npos||
      receives.find("\"payload_sha256\":\""+expected_payload_sha+"\"")==std::string::npos)
    throw std::runtime_error("native journals did not retain actual wait failure/receive/self-clock observations");
  auto foreign=args;
  foreign.checkpoint_study_waits_path=(output.parent_path()/"foreign-waits.jsonl").string();
  foreign.checkpoint_study_accounting_path=(output.parent_path()/"foreign-receives.jsonl").string();
  ::setenv("VAST_CHECKPOINT_WORKER_CLOCK_TIME_NAMESPACE","unknown",1);
  expect_rejected(foreign,"clock namespace proof is missing or mismatched");
  if(std::filesystem::exists(foreign.checkpoint_study_waits_path)||std::filesystem::exists(foreign.checkpoint_study_accounting_path))
    throw std::runtime_error("foreign clock projection allocated study state before rejection");
  bool closed=true;
  for(int socket:accepted) {char byte;closed=closed&&::recv(socket,&byte,1,MSG_DONTWAIT)==0;::close(socket);}
  ::close(listener);::unlink(path.c_str());
  ::unsetenv("VAST_CHECKPOINT_ANALYTICS_EXECUTION_SOCKET");
  ::unsetenv("VAST_CHECKPOINT_STARTUP_DEADLINE_MONOTONIC_NS");
  ::unsetenv("VAST_CHECKPOINT_WORKER_CLOCK_BOOT_ID");::unsetenv("VAST_CHECKPOINT_WORKER_CLOCK_TIME_NAMESPACE");
  if(accepted.size()!=4||!closed||simultaneous_requests!=2||!sealed_payloads)
    throw std::runtime_error("study branch mode did not overlap and retire genuine independent sealed requests: "+std::to_string(accepted.size()));
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
    configure_model_bindings();
    exercise_real_independent_study_channels(temporary / "study-branches");
    exercise_valid_drop(temporary / "independent-prefix-drop", false, true);
    exercise_valid_drop(temporary / "independent-detector-drop", false, false);
    exercise_valid_drop(temporary / "shared-prefix-drop", true, true);
    exercise_valid_drop(temporary / "shared-detector-drop", true, false);
    exercise_invalid_drops(temporary / "invalid-drops");
    exercise_legacy_drop(temporary / "legacy-drop");
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
