#pragma once

#include <cstdint>
#include <fstream>
#include <limits>
#include <mutex>
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <utility>
#include <vector>

namespace vast {

class CheckpointResourceIntervalEmitter {
 public:
  static constexpr std::uint64_t kTelemetrySchemaVersion = 2;
  static constexpr std::uint64_t kIntervalContractVersion = 2;
  static constexpr const char* kRuntimeFilename = "resource_intervals.runtime.csv";
  static constexpr const char* kNvdecDurationProvenance =
      "native_decoder_submit_complete_interval_v1";
  static constexpr const char* kFanoutDurationProvenance =
      "native_gstreamer_pad_probe_interval_v1";
  static constexpr const char* kCudaDurationProvenance =
      "native_cuda_event_interval_v1";

  explicit CheckpointResourceIntervalEmitter(const std::string& path)
      : output_(path, std::ios::out | std::ios::trunc) {
    if (!output_.is_open()) {
      throw std::runtime_error("failed to open runtime resource-interval fragment: " + path);
    }
    output_
        << "schema_version,interval_contract_version,run_id,trace_id,stream_id,frame_id,"
           "input_frame_key,component,direction,stage,branch_id,execution_id,"
           "host_start_timestamp_ns,host_end_timestamp_ns,duration_ns,bytes,device_id,"
           "counter_scope,native_event_id,duration_provenance,telemetry_source\n";
    output_.flush();
  }

  static std::uint64_t canonical_interval_end_ns(
      std::uint64_t host_start_timestamp_ns,
      std::uint64_t physical_end_timestamp_ns,
      std::uint64_t requested_topology_timestamp_ms,
      std::uint64_t serialized_topology_timestamp_ms) {
    if (host_start_timestamp_ns >= physical_end_timestamp_ns) {
      throw std::runtime_error("physical resource interval must have positive width");
    }
    if (requested_topology_timestamp_ms != physical_end_timestamp_ns / 1'000'000) {
      throw std::runtime_error("physical interval end does not match requested topology time");
    }
    if (serialized_topology_timestamp_ms < requested_topology_timestamp_ms) {
      throw std::runtime_error("serialized topology time moved backwards");
    }
    if (serialized_topology_timestamp_ms == requested_topology_timestamp_ms) {
      return physical_end_timestamp_ns;
    }
    if (serialized_topology_timestamp_ms >
        std::numeric_limits<std::uint64_t>::max() / 1'000'000) {
      throw std::runtime_error("serialized topology time overflows nanoseconds");
    }
    const std::uint64_t canonical_end_timestamp_ns =
        serialized_topology_timestamp_ms * 1'000'000;
    if (canonical_end_timestamp_ns <= host_start_timestamp_ns) {
      throw std::runtime_error("canonical resource interval must have positive width");
    }
    return canonical_end_timestamp_ns;
  }

  void emit_nvdec_submit_complete(
      const std::string& run_id,
      const std::string& trace_id,
      std::uint64_t stream_id,
      std::uint64_t frame_id,
      const std::string& input_frame_key,
      const std::string& branch_id,
      const std::string& execution_id,
      std::uint64_t host_start_timestamp_ns,
      std::uint64_t host_end_timestamp_ns,
      std::uint64_t bytes,
      const std::string& device_id,
      const std::string& native_event_id) {
    require_text(run_id, "run_id");
    require_text(trace_id, "trace_id");
    require_text(input_frame_key, "input_frame_key");
    require_text(branch_id, "branch_id");
    require_text(execution_id, "execution_id");
    if (host_start_timestamp_ns >= host_end_timestamp_ns) {
      throw std::runtime_error("NVDEC submit-to-output interval must have positive width");
    }
    if (bytes == 0) {
      throw std::runtime_error("NVDEC submit-to-output interval must report positive bytes");
    }
    if (!valid_device_id(device_id) || device_id.rfind("nvdec:", 0) != 0) {
      throw std::runtime_error("NVDEC interval device_id must be canonical and start with nvdec:");
    }
    if (!valid_sha256(native_event_id)) {
      throw std::runtime_error("NVDEC native_event_id must be lowercase SHA-256");
    }

    std::lock_guard<std::mutex> lock(mutex_);
    if (!native_event_ids_.insert(native_event_id).second) {
      throw std::runtime_error("NVDEC native_event_id is duplicated in one runtime fragment");
    }
    if (!execution_ids_.insert(execution_id).second) {
      throw std::runtime_error("NVDEC execution_id has more than one runtime interval");
    }
    const std::string stage = branch_id == "shared" ? "decode" : "decode_" + branch_id;
    const std::vector<std::string> values = {
        std::to_string(kTelemetrySchemaVersion),
        std::to_string(kIntervalContractVersion),
        run_id,
        trace_id,
        std::to_string(stream_id),
        std::to_string(frame_id),
        input_frame_key,
        "nvdec_submit_complete",
        "none",
        stage,
        branch_id,
        execution_id,
        std::to_string(host_start_timestamp_ns),
        std::to_string(host_end_timestamp_ns),
        std::to_string(host_end_timestamp_ns - host_start_timestamp_ns),
        std::to_string(bytes),
        device_id,
        "per_trace_interval",
        native_event_id,
        kNvdecDurationProvenance,
        "native",
    };
    write_values(values, "NVDEC submit-to-output interval");
  }

  void emit_fanout(
      const std::string& run_id,
      const std::string& trace_id,
      std::uint64_t stream_id,
      std::uint64_t frame_id,
      const std::string& input_frame_key,
      const std::string& branch_id,
      const std::string& execution_id,
      std::uint64_t host_start_timestamp_ns,
      std::uint64_t host_end_timestamp_ns,
      std::uint64_t bytes,
      const std::string& native_event_id) {
    require_text(run_id, "run_id");
    require_text(trace_id, "trace_id");
    require_text(input_frame_key, "input_frame_key");
    require_text(branch_id, "branch_id");
    require_text(execution_id, "execution_id");
    if (host_start_timestamp_ns >= host_end_timestamp_ns) {
      throw std::runtime_error("fanout pad-probe interval must have positive width");
    }
    if (bytes == 0) {
      throw std::runtime_error("fanout pad-probe interval must report positive bytes");
    }
    if (!valid_sha256(native_event_id)) {
      throw std::runtime_error("fanout native_event_id must be lowercase SHA-256");
    }

    std::lock_guard<std::mutex> lock(mutex_);
    if (!native_event_ids_.insert(native_event_id).second) {
      throw std::runtime_error("fanout native_event_id is duplicated in one runtime fragment");
    }
    if (!execution_ids_.insert(execution_id).second) {
      throw std::runtime_error("fanout execution_id has more than one runtime interval");
    }
    const std::vector<std::string> values = {
        std::to_string(kTelemetrySchemaVersion),
        std::to_string(kIntervalContractVersion),
        run_id,
        trace_id,
        std::to_string(stream_id),
        std::to_string(frame_id),
        input_frame_key,
        "fanout",
        "none",
        "fanout",
        branch_id,
        execution_id,
        std::to_string(host_start_timestamp_ns),
        std::to_string(host_end_timestamp_ns),
        std::to_string(host_end_timestamp_ns - host_start_timestamp_ns),
        std::to_string(bytes),
        "gstreamer:tee-queue",
        "per_trace_interval",
        native_event_id,
        kFanoutDurationProvenance,
        "native",
    };
    write_values(values, "fanout interval");
  }

  static std::pair<std::uint64_t, std::uint64_t>
  correlate_monotonic_envelope_to_realtime(
      std::uint64_t host_start_monotonic_ns,
      std::uint64_t host_end_monotonic_ns,
      std::uint64_t clock_monotonic_anchor_ns,
      std::uint64_t clock_realtime_anchor_ns) {
    if (host_start_monotonic_ns == 0 ||
        host_start_monotonic_ns >= host_end_monotonic_ns ||
        host_end_monotonic_ns > clock_monotonic_anchor_ns) {
      throw std::runtime_error(
          "CUDA transfer CLOCK_MONOTONIC envelope is invalid or after its anchor");
    }
    if (clock_realtime_anchor_ns <= clock_monotonic_anchor_ns) {
      throw std::runtime_error("CUDA transfer clock correlation is invalid");
    }
    const std::uint64_t start_delta =
        clock_monotonic_anchor_ns - host_start_monotonic_ns;
    const std::uint64_t end_delta =
        clock_monotonic_anchor_ns - host_end_monotonic_ns;
    if (clock_realtime_anchor_ns <= start_delta ||
        clock_realtime_anchor_ns <= end_delta) {
      throw std::runtime_error("CUDA transfer realtime conversion underflows");
    }
    const std::uint64_t host_start_timestamp_ns =
        clock_realtime_anchor_ns - start_delta;
    const std::uint64_t host_end_timestamp_ns =
        clock_realtime_anchor_ns - end_delta;
    if (host_start_timestamp_ns >= host_end_timestamp_ns) {
      throw std::runtime_error("CUDA transfer realtime envelope is invalid");
    }
    return {host_start_timestamp_ns, host_end_timestamp_ns};
  }

  static std::uint64_t correlate_monotonic_point_to_realtime(
      std::uint64_t point_monotonic_ns,
      std::uint64_t clock_monotonic_anchor_ns,
      std::uint64_t clock_realtime_anchor_ns) {
    if (point_monotonic_ns == 0 ||
        point_monotonic_ns > clock_monotonic_anchor_ns) {
      throw std::runtime_error(
          "monotonic point is invalid or after its realtime anchor");
    }
    if (clock_realtime_anchor_ns <= clock_monotonic_anchor_ns) {
      throw std::runtime_error("monotonic point clock correlation is invalid");
    }
    const std::uint64_t delta =
        clock_monotonic_anchor_ns - point_monotonic_ns;
    if (clock_realtime_anchor_ns <= delta) {
      throw std::runtime_error("monotonic point realtime conversion underflows");
    }
    return clock_realtime_anchor_ns - delta;
  }

  void emit_cuda_transfer(
      const std::string& run_id,
      const std::string& trace_id,
      std::uint64_t stream_id,
      std::uint64_t frame_id,
      const std::string& input_frame_key,
      const std::string& branch_id,
      const std::string& stage,
      const std::string& execution_id,
      const std::string& direction,
      std::uint64_t host_start_monotonic_ns,
      std::uint64_t host_end_monotonic_ns,
      std::uint64_t device_elapsed_ns,
      std::uint64_t bytes,
      const std::string& gpu_uuid,
      const std::string& timing_source,
      std::uint64_t clock_monotonic_anchor_ns,
      std::uint64_t clock_realtime_anchor_ns,
      const std::string& native_event_id) {
    require_text(run_id, "run_id");
    require_text(trace_id, "trace_id");
    require_text(input_frame_key, "input_frame_key");
    require_text(branch_id, "branch_id");
    require_text(stage, "stage");
    require_text(execution_id, "execution_id");
    if (direction != "h2d" && direction != "d2h") {
      throw std::runtime_error("CUDA transfer direction must be h2d or d2h");
    }
    const auto correlated = correlate_monotonic_envelope_to_realtime(
        host_start_monotonic_ns,
        host_end_monotonic_ns,
        clock_monotonic_anchor_ns,
        clock_realtime_anchor_ns);
    if (device_elapsed_ns == 0 ||
        device_elapsed_ns > host_end_monotonic_ns - host_start_monotonic_ns) {
      throw std::runtime_error(
          "CUDA event elapsed duration is invalid or exceeds its host envelope");
    }
    if (bytes == 0) {
      throw std::runtime_error("CUDA transfer interval must report positive bytes");
    }
    if (!valid_gpu_uuid(gpu_uuid)) {
      throw std::runtime_error("CUDA transfer interval GPU UUID is invalid");
    }
    if (timing_source != "cudaEventElapsedTime") {
      throw std::runtime_error(
          "CUDA transfer interval timing source must be cudaEventElapsedTime");
    }
    const std::uint64_t host_start_timestamp_ns = correlated.first;
    const std::uint64_t host_end_timestamp_ns = correlated.second;
    if (!valid_sha256(native_event_id)) {
      throw std::runtime_error("CUDA transfer native_event_id must be lowercase SHA-256");
    }

    std::string canonical_gpu_uuid = gpu_uuid;
    for (char& character : canonical_gpu_uuid) {
      if (character >= 'A' && character <= 'Z') {
        character = static_cast<char>(character - 'A' + 'a');
      }
    }
    const std::string device_id = "gpu:" + canonical_gpu_uuid;
    if (!valid_device_id(device_id)) {
      throw std::runtime_error("CUDA transfer row device_id is not canonical");
    }

    std::lock_guard<std::mutex> lock(mutex_);
    if (!native_event_ids_.insert(native_event_id).second) {
      throw std::runtime_error(
          "CUDA transfer native_event_id is duplicated in one runtime fragment");
    }
    const std::string execution_direction = execution_id + "\n" + direction;
    if (!transfer_execution_directions_.insert(execution_direction).second) {
      throw std::runtime_error(
          "CUDA transfer execution/direction is duplicated in one runtime fragment");
    }
    const std::vector<std::string> values = {
        std::to_string(kTelemetrySchemaVersion),
        std::to_string(kIntervalContractVersion),
        run_id,
        trace_id,
        std::to_string(stream_id),
        std::to_string(frame_id),
        input_frame_key,
        "transfer",
        direction,
        stage,
        branch_id,
        execution_id,
        std::to_string(host_start_timestamp_ns),
        std::to_string(host_end_timestamp_ns),
        std::to_string(device_elapsed_ns),
        std::to_string(bytes),
        device_id,
        "per_trace_interval",
        native_event_id,
        kCudaDurationProvenance,
        "native",
    };
    write_values(values, "CUDA transfer interval");
  }

 private:
  std::ofstream output_;
  std::mutex mutex_;
  std::unordered_set<std::string> native_event_ids_;
  std::unordered_set<std::string> execution_ids_;
  std::unordered_set<std::string> transfer_execution_directions_;

  static void require_text(const std::string& value, const char* name) {
    if (value.empty() || value.find_first_of("\r\n") != std::string::npos) {
      throw std::runtime_error(std::string("invalid fanout interval field: ") + name);
    }
  }

  static bool valid_sha256(const std::string& value) {
    if (value.size() != 64) {
      return false;
    }
    for (const char character : value) {
      if (!((character >= '0' && character <= '9') ||
            (character >= 'a' && character <= 'f'))) {
        return false;
      }
    }
    return true;
  }

  static bool valid_device_id(const std::string& value) {
    if (value.empty() || value.front() < 'a' || value.front() > 'z') {
      return false;
    }
    for (const char character : value) {
      if (!((character >= 'a' && character <= 'z') ||
            (character >= '0' && character <= '9') || character == '_' ||
            character == '.' || character == ':' || character == '-')) {
        return false;
      }
    }
    return true;
  }

  static bool valid_gpu_uuid(const std::string& value) {
    if (value.size() != 40 || value.rfind("GPU-", 0) != 0 ||
        value[12] != '-' || value[17] != '-' ||
        value[22] != '-' || value[27] != '-') {
      return false;
    }
    for (std::size_t index = 4; index < value.size(); ++index) {
      if (index == 12 || index == 17 || index == 22 || index == 27) {
        continue;
      }
      const char character = value[index];
      if (!((character >= '0' && character <= '9') ||
            (character >= 'a' && character <= 'f') ||
            (character >= 'A' && character <= 'F'))) {
        return false;
      }
    }
    return true;
  }

  void write_values(const std::vector<std::string>& values, const char* kind) {
    for (std::size_t index = 0; index < values.size(); ++index) {
      if (index != 0) {
        output_ << ',';
      }
      output_ << csv_field(values[index]);
    }
    output_ << '\n';
    output_.flush();
    if (!output_) {
      throw std::runtime_error(std::string("failed to write runtime ") + kind);
    }
  }

  static std::string csv_field(const std::string& value) {
    if (value.find_first_of(",\"\r\n") == std::string::npos) {
      return value;
    }
    std::string escaped = "\"";
    for (const char character : value) {
      escaped += character == '\"' ? "\"\"" : std::string(1, character);
    }
    escaped += '\"';
    return escaped;
  }
};

class CheckpointFanoutWorkCounterEmitter {
 public:
  static constexpr std::uint64_t kTelemetrySchemaVersion = 2;
  static constexpr std::uint64_t kResourceContractVersion = 2;
  static constexpr const char* kRuntimeFilename = "fanout_work_counters.runtime.csv";
  static constexpr const char* kCounterProvenance = "native_thread_cpu_time_v1";

  explicit CheckpointFanoutWorkCounterEmitter(const std::string& path)
      : output_(path, std::ios::out | std::ios::trunc) {
    if (!output_.is_open()) {
      throw std::runtime_error("failed to open runtime fanout-work fragment: " + path);
    }
    output_
        << "schema_version,resource_contract_version,run_id,trace_id,stream_id,frame_id,"
           "input_frame_key,branch_id,execution_id,thread_cpu_time_ns,work_units,"
           "device_id,counter_scope,counter_provenance,telemetry_source\n";
    output_.flush();
  }

  void emit(
      const std::string& run_id,
      const std::string& trace_id,
      std::uint64_t stream_id,
      std::uint64_t frame_id,
      const std::string& input_frame_key,
      const std::string& branch_id,
      const std::string& execution_id,
      std::uint64_t thread_cpu_time_ns,
      std::uint64_t work_units) {
    require_text(run_id, "run_id");
    require_text(trace_id, "trace_id");
    require_text(input_frame_key, "input_frame_key");
    require_text(branch_id, "branch_id");
    require_text(execution_id, "execution_id");
    if (thread_cpu_time_ns == 0) {
      throw std::runtime_error("fanout thread CPU time must be positive");
    }
    if (work_units == 0) {
      throw std::runtime_error("fanout work_units must be positive");
    }

    std::lock_guard<std::mutex> lock(mutex_);
    if (!execution_ids_.insert(execution_id).second) {
      throw std::runtime_error("fanout execution_id has more than one resource-work counter");
    }
    const std::vector<std::string> values = {
        std::to_string(kTelemetrySchemaVersion),
        std::to_string(kResourceContractVersion),
        run_id,
        trace_id,
        std::to_string(stream_id),
        std::to_string(frame_id),
        input_frame_key,
        branch_id,
        execution_id,
        std::to_string(thread_cpu_time_ns),
        std::to_string(work_units),
        "host:fanout",
        "per_trace_resource_work",
        kCounterProvenance,
        "native",
    };
    for (std::size_t index = 0; index < values.size(); ++index) {
      if (index != 0) {
        output_ << ',';
      }
      output_ << csv_field(values[index]);
    }
    output_ << '\n';
    output_.flush();
    if (!output_) {
      throw std::runtime_error("failed to write runtime fanout-work counter");
    }
  }

 private:
  std::ofstream output_;
  std::mutex mutex_;
  std::unordered_set<std::string> execution_ids_;

  static void require_text(const std::string& value, const char* name) {
    if (value.empty() || value.find_first_of("\r\n") != std::string::npos) {
      throw std::runtime_error(std::string("invalid fanout-work field: ") + name);
    }
  }

  static std::string csv_field(const std::string& value) {
    if (value.find_first_of(",\"\r\n") == std::string::npos) {
      return value;
    }
    std::string escaped = "\"";
    for (const char character : value) {
      escaped += character == '\"' ? "\"\"" : std::string(1, character);
    }
    escaped += '\"';
    return escaped;
  }
};
}  // namespace vast
