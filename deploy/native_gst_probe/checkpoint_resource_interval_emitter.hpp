#pragma once

#include <cstdint>
#include <fstream>
#include <mutex>
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <vector>

namespace vast {

class CheckpointResourceIntervalEmitter {
 public:
  static constexpr std::uint64_t kTelemetrySchemaVersion = 2;
  static constexpr std::uint64_t kIntervalContractVersion = 2;
  static constexpr const char* kRuntimeFilename = "resource_intervals.runtime.csv";
  static constexpr const char* kFanoutDurationProvenance =
      "native_gstreamer_pad_probe_interval_v1";

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
    for (std::size_t index = 0; index < values.size(); ++index) {
      if (index != 0) {
        output_ << ',';
      }
      output_ << csv_field(values[index]);
    }
    output_ << '\n';
    output_.flush();
    if (!output_) {
      throw std::runtime_error("failed to write runtime fanout interval");
    }
  }

 private:
  std::ofstream output_;
  std::mutex mutex_;
  std::unordered_set<std::string> native_event_ids_;
  std::unordered_set<std::string> execution_ids_;

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
