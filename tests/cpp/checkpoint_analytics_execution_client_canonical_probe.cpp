// Emits one real analytics execution request on stdout so the Python test can
// check it with the guardian's own canonical-JSON parser.
#include "checkpoint_analytics_execution_client.hpp"
#include <glib.h>
#include <sys/socket.h>
#include <unistd.h>
#include <cstdio>
#include <thread>
#include <vector>
#include <iostream>
int main() {
  int fds[2];
  if (::socketpair(AF_UNIX, SOCK_SEQPACKET, 0, fds) != 0) return 2;
  std::thread server([&]() {
    std::vector<char> buf(1 << 20);
    char control[CMSG_SPACE(sizeof(int))];
    iovec v{buf.data(), buf.size()};
    msghdr m{}; m.msg_iov = &v; m.msg_iovlen = 1; m.msg_control = control; m.msg_controllen = sizeof(control);
    ssize_t n = ::recvmsg(fds[1], &m, 0);
    if (n > 0) { std::fwrite(buf.data(), 1, static_cast<std::size_t>(n), stdout); std::fflush(stdout); }
    ::close(fds[1]);
  });
  ::setenv(vast::CheckpointAnalyticsExecutionClient::kFdEnvironment, std::to_string(fds[0]).c_str(), 1);
  vast::CheckpointAnalyticsExecutionClient client = vast::CheckpointAnalyticsExecutionClient::from_environment();
  vast::CheckpointAnalyticsExecutionRequest r;
  std::vector<std::uint8_t> payload(640 * 360 * 3, 7);
  r.request_id = std::string(64, 'b');
  r.run_id = "qualification-v2-openvino_gva-cpu-h264-independent-processes";
  r.arm_id = std::string(64, 'c');
  r.worker_id = "stream-0-branch-damage";
  r.input_frame_key = "kpp:0:" + std::string(64, 'd') + ":0:33366666";
  r.stream_id = 0; r.frame_id = 12; r.transport_pts_ns = 400000000;
  r.branch = "damage";
  r.decision.decision_id = "qualification-v2-openvino_gva:checkpoint_independent_processes_baseline:h264:cpu_only:100.0:decision:00000001";
  r.decision.decision_seq = 1;
  r.decision.emitter_id = "openvino_gva-native-policy-emitter-v2:damage:cpu:" + std::string(64, 'e');
  r.decision.emitter_sha256 = std::string(64, 'f');
  r.decision.selected_implementation_id = "openvino_gva-qualification-authority-v2:damage:cpu:" + std::string(64, 'e');
  r.decision.selected_resource = "cpu";
  r.deadline_monotonic_ns = 1234567890123ULL;
  r.format = "BGR"; r.width = 640; r.height = 360; r.stride = 1920;
  r.preprocessing_contract_sha256 = std::string(64, 'a');
  { gchar* d = g_compute_checksum_for_data(G_CHECKSUM_SHA256, payload.data(), payload.size()); r.raw_input_sha256 = d; g_free(d); }
  try { client.execute(r, payload.data(), payload.size()); } catch (const std::exception& e) { std::cerr << "client: " << e.what() << "\n"; }
  server.join();
  return 0;
}
