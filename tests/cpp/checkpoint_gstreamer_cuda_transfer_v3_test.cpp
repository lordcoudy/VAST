#include "checkpoint_analytics_execution_client.hpp"
#include "checkpoint_resource_interval_emitter.hpp"

#include <array>
#include <cstdint>
#include <cstring>
#include <exception>
#include <fcntl.h>
#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>

#include <sys/socket.h>
#include <unistd.h>

namespace {

constexpr const char* kGpuUuid = "GPU-00000000-0000-0000-0000-000000000001";
constexpr const char* kRawSha =
    "9f64a747e1b97f131fabb6b447296c9b6f0201e79fb3c5356e6c77e89b6a806a";
constexpr const char* kContractSha =
    "1123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

struct Packet {
  int fd = -1;
};

Packet receive_request(int socket_fd) {
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
    throw std::runtime_error("invalid request packet");
  }
  cmsghdr* header = CMSG_FIRSTHDR(&message);
  if (header == nullptr || header->cmsg_level != SOL_SOCKET ||
      header->cmsg_type != SCM_RIGHTS || header->cmsg_len != CMSG_LEN(sizeof(int)) ||
      CMSG_NXTHDR(&message, header) != nullptr) {
    throw std::runtime_error("request lacks exactly one payload FD");
  }
  int received_fd = -1;
  std::memcpy(&received_fd, CMSG_DATA(header), sizeof(received_fd));
  return {received_fd};
}

std::string intervals(
    const std::string& first_direction = "h2d",
    std::uint64_t h2d_bytes = 4,
    std::uint64_t h2d_elapsed = 250,
    const std::string& h2d_device = kGpuUuid,
    bool extra_field = false) {
  return
      "[{\"bytes\":" + std::to_string(h2d_bytes) +
      ",\"device_elapsed_ns\":" + std::to_string(h2d_elapsed) +
      ",\"device_id\":\"" + h2d_device +
      "\",\"direction\":\"" + first_direction +
      "\",\"host_end_monotonic_ns\":1400,\"host_start_monotonic_ns\":1000," +
      (extra_field ? "\"unexpected\":1," : "") +
      "\"timing_source\":\"cudaEventElapsedTime\"},"
      "{\"bytes\":32,\"device_elapsed_ns\":300,\"device_id\":\"" +
      std::string(kGpuUuid) +
      "\",\"direction\":\"d2h\",\"host_end_monotonic_ns\":2000,"
      "\"host_start_monotonic_ns\":1600,\"timing_source\":\"cudaEventElapsedTime\"}]";
}

std::string response(const std::string& transfer_intervals) {
  return
      "{\"backend\":\"cuda-tensorrt:sidecar;device=NVIDIA_CUDA:0\","
      "\"branch\":\"damage\",\"decision_id\":\"decision-native-0001\","
      "\"decision_seq\":7,\"detector\":\"damage-gpu-detector-v1\","
      "\"device_api\":\"NVIDIA_CUDA\",\"device_id\":\"" + std::string(kGpuUuid) +
      "\",\"engine\":\"tensorrt_cuda\",\"execution_path\":\"tensorrt_cuda_native\","
      "\"inference_finished_monotonic_ns\":2100,\"inference_latency_ns\":1200,"
      "\"inference_started_monotonic_ns\":900,"
      "\"input_sha256\":\"2123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\","
      "\"message_type\":\"analytics_execute_response\","
      "\"model_artifact_sha256\":\"3123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\","
      "\"model_id\":\"damage-model-v1\","
      "\"native_inference_api\":\"nvinfer1::IExecutionContext::enqueueV3\","
      "\"objects\":1,\"output_bytes\":32,"
      "\"output_contract_sha256\":\"4123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\","
      "\"output_sha256\":\"5123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\","
      "\"preprocessing_contract_sha256\":\"" + std::string(kContractSha) +
      "\",\"raw_input_sha256\":\"" + std::string(kRawSha) +
      "\",\"request_id\":\"analytics-request-0001\","
      "\"resource\":{\"accelerator_memory_bytes\":4096,\"cuda_d2h_bytes\":32,"
      "\"cuda_h2d_bytes\":4,\"cuda_transfer_intervals\":" + transfer_intervals +
      ",\"process_cpu_time_ns\":50,\"rss_after_bytes\":8192,\"rss_before_bytes\":4096},"
      "\"runtime_name\":\"TensorRT\",\"runtime_version\":\"8.6.1.6\","
      "\"schema_version\":1,\"selected_resource\":\"gpu\","
      "\"source_model_sha256\":\"6123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\","
      "\"terminal_reason\":\"native_fixed_tensor_completed\",\"terminal_status\":\"completed\","
      "\"worker_completed_monotonic_ns\":2200,\"worker_id\":\"vast.damage.tensorrt\","
      "\"worker_image_id\":\"sha256:7123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\","
      "\"worker_implementation_sha256\":\"8123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\","
      "\"worker_received_monotonic_ns\":800}";
}

void replace_exact(
    std::string& value,
    const std::string& source,
    const std::string& replacement) {
  const std::size_t offset = value.find(source);
  if (offset == std::string::npos ||
      value.find(source, offset + source.size()) != std::string::npos) {
    throw std::runtime_error("test response replacement is absent or ambiguous");
  }
  value.replace(offset, source.size(), replacement);
}

std::string cpu_response() {
  std::string value = response("[]");
  replace_exact(
      value,
      "\"backend\":\"cuda-tensorrt:sidecar;device=NVIDIA_CUDA:0\"",
      "\"backend\":\"openvino-dlstreamer:sidecar;device=CPU\"");
  replace_exact(value, "\"device_api\":\"NVIDIA_CUDA\"", "\"device_api\":\"CPU\"");
  replace_exact(
      value,
      "\"device_id\":\"GPU-00000000-0000-0000-0000-000000000001\"",
      "\"device_id\":\"CPU\"");
  replace_exact(value, "\"engine\":\"tensorrt_cuda\"", "\"engine\":\"openvino_cpu\"");
  replace_exact(
      value,
      "\"execution_path\":\"tensorrt_cuda_native\"",
      "\"execution_path\":\"openvino_cpu_native\"");
  replace_exact(
      value,
      "\"native_inference_api\":\"nvinfer1::IExecutionContext::enqueueV3\"",
      "\"native_inference_api\":\"openvino.CompiledModel.__call__\"");
  replace_exact(value, "\"runtime_name\":\"TensorRT\"", "\"runtime_name\":\"OpenVINO\"");
  replace_exact(value, "\"selected_resource\":\"gpu\"", "\"selected_resource\":\"cpu\"");
  replace_exact(
      value,
      "\"resource\":{\"accelerator_memory_bytes\":4096,\"cuda_d2h_bytes\":32,"
      "\"cuda_h2d_bytes\":4,\"cuda_transfer_intervals\":[],\"process_cpu_time_ns\":50,"
      "\"rss_after_bytes\":8192,\"rss_before_bytes\":4096}",
      "\"resource\":{\"accelerator_memory_bytes\":0,\"cuda_d2h_bytes\":0,"
      "\"cuda_h2d_bytes\":0,\"cuda_transfer_intervals\":[],\"process_cpu_time_ns\":50,"
      "\"rss_after_bytes\":8192,\"rss_before_bytes\":4096}");
  return value;
}

vast::CheckpointAnalyticsExecutionRequest request(
    const std::string& selected_resource = "gpu") {
  vast::CheckpointAnalyticsExecutionRequest value;
  value.request_id = "analytics-request-0001";
  value.run_id = "run-native-analytics-0001";
  value.arm_id = "arm-native-analytics-0001";
  value.worker_id = "checkpoint-worker-0001";
  value.input_frame_key = "dataset:0:source:1:90000";
  value.stream_id = 0;
  value.frame_id = 1;
  value.transport_pts_ns = 90000;
  value.branch = "damage";
  value.decision.decision_id = "decision-native-0001";
  value.decision.decision_seq = 7;
  value.decision.selected_resource = selected_resource;
  value.decision.selected_implementation_id = "gstreamer-damage-gpu-implementation-v1";
  value.decision.emitter_id = "gstreamer-damage-gpu-emitter-v1";
  value.decision.emitter_sha256 =
      "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
  value.deadline_monotonic_ns = 9999999999;
  value.format = "BGR";
  value.width = 1;
  value.height = 1;
  value.stride = 4;
  value.preprocessing_contract_sha256 = kContractSha;
  value.raw_input_sha256 = kRawSha;
  return value;
}

vast::CheckpointAnalyticsExecutionResult execute_once(
    const std::string& server_response,
    const std::string& selected_resource = "gpu") {
  int descriptors[2] = {-1, -1};
  if (::socketpair(AF_UNIX, SOCK_SEQPACKET, 0, descriptors) != 0) {
    throw std::runtime_error("socketpair failed");
  }
  std::exception_ptr server_error;
  std::thread server([&]() {
    try {
      Packet packet = receive_request(descriptors[1]);
      ::close(packet.fd);
      if (::send(descriptors[1], server_response.data(), server_response.size(), 0) !=
          static_cast<ssize_t>(server_response.size())) {
        throw std::runtime_error("failed to send response");
      }
    } catch (...) {
      server_error = std::current_exception();
    }
    ::close(descriptors[1]);
  });
  vast::CheckpointAnalyticsExecutionResult result;
  try {
    vast::CheckpointAnalyticsExecutionClient client(descriptors[0]);
    const std::array<std::uint8_t, 4> payload{1, 2, 3, 4};
    result = client.execute(request(selected_resource), payload.data(), payload.size());
  } catch (...) {
    server.join();
    if (server_error) std::rethrow_exception(server_error);
    throw;
  }
  server.join();
  if (server_error) std::rethrow_exception(server_error);
  return result;
}

void require_rejected(const std::string& value) {
  try {
    (void)execute_once(value);
  } catch (const std::exception&) {
    return;
  }
  throw std::runtime_error("drifted CUDA transfer response was accepted");
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 2) {
    std::cerr << "expected runtime resource interval path\n";
    return 2;
  }
  try {
    if (std::string(vast::CheckpointAnalyticsExecutionClient::kProtocolIdentitySha256) !=
        "3bed4ad0e5cd46b01649b054fa520c0f728a1ceeb14502fb9fe1f0f8f5941eff") {
      throw std::runtime_error("native protocol identity pin drifted");
    }
    if (vast::CheckpointResourceIntervalEmitter::correlate_monotonic_point_to_realtime(
            2100, 5000, 1000005000) != 1000002100) {
      throw std::runtime_error("monotonic inference boundary correlation drifted");
    }
    bool future_point_rejected = false;
    try {
      (void)vast::CheckpointResourceIntervalEmitter::correlate_monotonic_point_to_realtime(
          5001, 5000, 1000005000);
    } catch (const std::exception&) {
      future_point_rejected = true;
    }
    if (!future_point_rejected) {
      throw std::runtime_error("future monotonic inference boundary was accepted");
    }
    const vast::CheckpointAnalyticsExecutionResult result = execute_once(response(intervals()));
    if (result.cuda_transfer_intervals.size() != 2 ||
        result.cuda_transfer_intervals[0].direction != "h2d" ||
        result.cuda_transfer_intervals[1].direction != "d2h" ||
        result.cuda_transfer_intervals[0].bytes != 4 ||
        result.cuda_transfer_intervals[1].bytes != 32) {
      throw std::runtime_error("validated CUDA transfer intervals drifted");
    }
    const vast::CheckpointAnalyticsExecutionResult cpu_result =
        execute_once(cpu_response(), "cpu");
    if (!cpu_result.cuda_transfer_intervals.empty() ||
        cpu_result.accelerator_memory_bytes != 0 ||
        cpu_result.cuda_h2d_bytes != 0 ||
        cpu_result.cuda_d2h_bytes != 0) {
      throw std::runtime_error("validated CPU response retained forbidden CUDA resource work");
    }
    const vast::CheckpointAnalyticsExecutionRequest event_request = request();
    std::cout
        << vast::CheckpointAnalyticsExecutionClient::cuda_transfer_native_event_material(
               event_request,
               result,
               "run-native-analytics-0001:0:1:damage:analytics",
               result.cuda_transfer_intervals[0])
        << '\n'
        << vast::CheckpointAnalyticsExecutionClient::cuda_transfer_native_event_material(
               event_request,
               result,
               "run-native-analytics-0001:0:1:damage:postprocess",
               result.cuda_transfer_intervals[1])
        << '\n';
    require_rejected(response("[]"));
    require_rejected(response(intervals("d2h")));
    require_rejected(response(intervals("h2d", 5)));
    require_rejected(response(intervals("h2d", 4, 401)));
    require_rejected(response(intervals(
        "h2d", 4, 250, "GPU-00000000-0000-0000-0000-000000000002")));
    require_rejected(response(intervals("h2d", 4, 250, kGpuUuid, true)));

    vast::CheckpointResourceIntervalEmitter emitter(argv[1]);
    emitter.emit_cuda_transfer(
        "run-native-analytics-0001", "run-native-analytics-0001:0:1", 0, 1,
        "dataset:0:source:1:90000", "damage", "damage",
        "run-native-analytics-0001:0:1:damage:analytics",
        "h2d", 1000, 1400, 250, 4, kGpuUuid, "cudaEventElapsedTime",
        5000, 1000005000,
        "49ede9393089ee17cbe7bb6710189f0b3fa21c38b4fd03c09330b8a292c56dd6");
    emitter.emit_cuda_transfer(
        "run-native-analytics-0001", "run-native-analytics-0001:0:1", 0, 1,
        "dataset:0:source:1:90000", "damage", "postprocess_damage",
        "run-native-analytics-0001:0:1:damage:postprocess", "d2h", 1600, 2000, 300, 32,
        kGpuUuid, "cudaEventElapsedTime", 5000, 1000005000,
        "fb91785aee8bfd07d445d9604b77e5d7b78951092350ce4fb9f42b1ba5f57747");
    bool duplicate_rejected = false;
    try {
      emitter.emit_cuda_transfer(
          "run-native-analytics-0001", "run-native-analytics-0001:0:1", 0, 1,
          "dataset:0:source:1:90000", "damage", "damage",
          "run-native-analytics-0001:0:1:damage:analytics",
          "h2d", 1000, 1400, 250, 4, kGpuUuid, "cudaEventElapsedTime",
          5000, 1000005000,
          "b123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef");
    } catch (const std::exception&) {
      duplicate_rejected = true;
    }
    if (!duplicate_rejected) {
      throw std::runtime_error("duplicate execution/direction interval was accepted");
    }
  } catch (const std::exception& exc) {
    std::cerr << exc.what() << '\n';
    return 1;
  }
  return 0;
}
