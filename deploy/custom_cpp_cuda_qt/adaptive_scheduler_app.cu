// Real CUDA-backed adaptive scheduler for the custom_cpp_cuda_qt benchmark.

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdint>
#include <cstdlib>
#include <deque>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <mutex>
#include <queue>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include <QApplication>
#include <QLabel>
#include <QTimer>
#include <QVBoxLayout>
#include <QWidget>
#include <cuda_runtime.h>

#include "policy_trace_format.hpp"
#include "weighted_proxy_policy.hpp"

namespace fs = std::filesystem;

constexpr int kSignalWidth = 512;
constexpr int kGpuBlockSize = 256;
constexpr int kGpuReduceBlocks = (kSignalWidth + kGpuBlockSize - 1) / kGpuBlockSize;

inline void check_cuda(cudaError_t status, const char* what) {
  if (status != cudaSuccess) {
    throw std::runtime_error(std::string(what) + ": " + cudaGetErrorString(status));
  }
}

struct Args {
  std::string scenario = "baseline";
  int streams = 6;
  int duration = 30;
  std::string output = ".";
  std::uint32_t seed = 0;
  bool has_seed = false;
  int min_objects = 0;
  int max_objects = 20;
  double deadline_ms = 3000.0;
  double source_fps = 30.0;
  std::string policy = "static_hybrid";
  std::string policy_artifact = "policies/ql_heft_frozen.policy";
  std::string run_id = "custom-unassigned";
  std::string detector = "custom_cuda_signal";
  std::string backend = "cuda_qt";
  std::string role = "local";
  std::string host = "localhost";
};

enum class Resource { Cpu, Gpu };

struct DecisionSnapshot {
  std::uint64_t ordinal = 0;
  std::string decision_id = "unavailable";
  std::uint64_t decision_seq = 0;
  double decision_timestamp_ms = 0.0;
  Resource resource = Resource::Cpu;
  std::size_t queue_depth = 0;
  std::size_t cpu_queue_depth_snapshot = 0;
  std::size_t gpu_queue_depth_snapshot = 0;
  double selected_score_ms = 0.0;
  std::uint64_t update_seq = 0;
  std::string policy_version;
  std::string allowed_resources_json = "[]";
  std::string alternative_scores_json = "{}";
  std::string cost_components_json = "{}";
  std::string parameters_json = "{}";
  std::string tie_break_rule = "unavailable";
  std::string update_json = "{}";
  std::string reason = "unavailable";
  std::string graph_version = "unavailable";
  std::string profile_version = "unavailable";
  std::string feature_provenance_json = "{}";
  std::string terminal_status = "unavailable";
  double terminal_timestamp_ms = 0.0;
  double update_timestamp_ms = 0.0;
  std::string source_decision_ids_json = "[]";
  std::string first_consumer_decision_id = "unavailable";
  std::uint64_t first_consumer_decision_seq = 0;
  bool replayable = false;
};

struct PendingPolicyFeedback {
  std::string trace_id;
  double latency_ms = 0.0;
  double deadline_ms = 0.0;
  std::size_t gpu_queue_depth = 0;
  vast_weighted_proxy::UpdateSignal signal = vast_weighted_proxy::UpdateSignal::None;
  bool late = false;
  bool overloaded = false;
  bool stable = false;
  std::string terminal_status = "completed";
  double terminal_timestamp_ms = 0.0;
  std::vector<std::string> source_decision_ids;
  std::uint64_t source_parameter_snapshot_seq = 0;
};

struct AppliedPolicyUpdate {
  std::string update_json = "{}";
  double update_timestamp_ms = 0.0;
  std::string source_decision_ids_json = "[]";
};

struct PolicyFeedbackRecord {
  std::uint64_t feedback_seq = 0;
  double feedback_timestamp_ms = 0.0;
  std::string source_trace_id;
  std::string terminal_status;
  double terminal_timestamp_ms = 0.0;
  std::string source_decision_ids_json = "[]";
  std::uint64_t source_parameter_snapshot_seq = 0;
  std::uint64_t parameter_lag = 0;
  std::uint64_t events_since_update = 0;
  vast_weighted_proxy::WeightPair old_weights;
  vast_weighted_proxy::WeightPair raw_weights;
  vast_weighted_proxy::WeightPair projected_weights;
  double variation_before = 0.0;
  double variation_after = 0.0;
  std::string feedback_features_json = "{}";
  std::string feedback_action = "no_op";
  std::string reason;
  std::uint64_t update_seq = 0;
  std::string first_consumer_decision_id = "unavailable";
  std::uint64_t first_consumer_decision_seq = 0;
};

struct FrameRecord {
  std::string trace_id;
  int frame_id = 0;
  int stream_id = 0;
  int objects = 0;
  double ingress_timestamp_ms = 0.0;
  double egress_timestamp_ms = 0.0;
  double latency_ms = 0.0;
};

struct EventRecord {
  std::string trace_id;
  int frame_id = 0;
  int stream_id = 0;
  std::string stage;
  std::string resource;
  double queue_enter_timestamp_ms = 0.0;
  double stage_start_timestamp_ms = 0.0;
  double stage_end_timestamp_ms = 0.0;
  std::size_t queue_depth = 0;
  double estimated_cost_ms = 0.0;
  std::string policy_action;
};

struct PolicyDecisionRecord {
  std::string trace_id;
  int frame_id = 0;
  int stream_id = 0;
  std::string stage;
  DecisionSnapshot decision;
};

struct Task {
  int frame_id = 0;
  int stream_id = 0;
  int stage_index = 0;
  int objects = 0;
  double aggregate = 0.0;
  std::array<float, kSignalWidth> signal{};
  std::chrono::steady_clock::time_point created_at;
  std::chrono::steady_clock::time_point queue_enter_at;
  DecisionSnapshot decision;
  std::vector<std::string> applied_decision_ids;
  std::size_t max_applied_gpu_queue_depth = 0;
  std::uint64_t oldest_applied_parameter_snapshot_seq = 0;
};

template <typename T>
class BlockingQueue {
 public:
  void push(T value) {
    {
      std::lock_guard<std::mutex> lock(mutex_);
      queue_.push(std::move(value));
    }
    cv_.notify_one();
  }

  bool pop(T& out) {
    std::unique_lock<std::mutex> lock(mutex_);
    cv_.wait(lock, [&] { return closed_ || !queue_.empty(); });
    if (queue_.empty()) {
      return false;
    }
    out = std::move(queue_.front());
    queue_.pop();
    return true;
  }

  void close() {
    {
      std::lock_guard<std::mutex> lock(mutex_);
      closed_ = true;
    }
    cv_.notify_all();
  }

  std::size_t size() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return queue_.size();
  }

 private:
  mutable std::mutex mutex_;
  std::condition_variable cv_;
  std::queue<T> queue_;
  bool closed_ = false;
};

struct StageSpec {
  std::string name;
  Resource preferred;
  float cpu_gain;
  float gpu_gain;
  float bias;
};

__global__ void transform_kernel(float* signal,
                                 int width,
                                 float gain,
                                 float bias,
                                 int frame_id,
                                 int stage_index,
                                 int objects) {
  const int idx = blockIdx.x * blockDim.x + threadIdx.x;
  if (idx >= width) {
    return;
  }

  const float x = signal[idx];
  const float phase = 0.001f * static_cast<float>((frame_id + 1) * (idx + 1));
  const float stage_bias = bias + 0.0008f * static_cast<float>(objects) + 0.0004f * static_cast<float>(stage_index);
  const float mixed = x * gain + stage_bias + phase;
  signal[idx] = tanhf(mixed) + 0.15f * sinf(mixed * 1.37f) + 0.05f * cosf(mixed * 0.91f);
}

__global__ void reduce_kernel(const float* signal, float* block_sums, int width) {
  extern __shared__ float shared[];
  const int tid = threadIdx.x;
  float local = 0.0f;

  for (int i = blockIdx.x * blockDim.x + tid; i < width; i += blockDim.x * gridDim.x) {
    local += fabsf(signal[i]);
  }

  shared[tid] = local;
  __syncthreads();

  for (int stride = blockDim.x / 2; stride > 0; stride >>= 1) {
    if (tid < stride) {
      shared[tid] += shared[tid + stride];
    }
    __syncthreads();
  }

  if (tid == 0) {
    block_sums[blockIdx.x] = shared[0];
  }
}

class GpuExecutor {
 public:
  GpuExecutor() {
    check_cuda(cudaSetDevice(0), "cudaSetDevice");
    check_cuda(cudaStreamCreateWithFlags(&stream_, cudaStreamNonBlocking), "cudaStreamCreateWithFlags");
    check_cuda(cudaEventCreate(&start_event_), "cudaEventCreate(start)");
    check_cuda(cudaEventCreate(&stop_event_), "cudaEventCreate(stop)");
    check_cuda(cudaMalloc(&d_signal_, sizeof(float) * kSignalWidth), "cudaMalloc(signal)");
    check_cuda(cudaMalloc(&d_block_sums_, sizeof(float) * kGpuReduceBlocks), "cudaMalloc(block_sums)");
    partial_host_.resize(kGpuReduceBlocks);
  }

  GpuExecutor(const GpuExecutor&) = delete;
  GpuExecutor& operator=(const GpuExecutor&) = delete;

  ~GpuExecutor() {
    if (d_block_sums_ != nullptr) {
      cudaFree(d_block_sums_);
    }
    if (d_signal_ != nullptr) {
      cudaFree(d_signal_);
    }
    if (start_event_ != nullptr) {
      cudaEventDestroy(start_event_);
    }
    if (stop_event_ != nullptr) {
      cudaEventDestroy(stop_event_);
    }
    if (stream_ != nullptr) {
      cudaStreamDestroy(stream_);
    }
  }

  float run(Task& task, const StageSpec& stage) {
    const float gain = stage.gpu_gain * (1.0f + 0.02f * static_cast<float>(task.objects));
    const float bias = stage.bias + 0.001f * static_cast<float>(task.stream_id) +
                       0.0005f * static_cast<float>(task.frame_id % 17);

    check_cuda(cudaEventRecord(start_event_, stream_), "cudaEventRecord(start)");
    check_cuda(cudaMemcpyAsync(d_signal_, task.signal.data(), sizeof(float) * kSignalWidth,
                               cudaMemcpyHostToDevice, stream_),
               "cudaMemcpyAsync(HtoD)");

    const dim3 block(kGpuBlockSize);
    const dim3 grid((kSignalWidth + kGpuBlockSize - 1) / kGpuBlockSize);
    transform_kernel<<<grid, block, 0, stream_>>>(d_signal_, kSignalWidth, gain, bias,
                                                  task.frame_id, task.stage_index, task.objects);
    check_cuda(cudaGetLastError(), "transform_kernel");

    reduce_kernel<<<kGpuReduceBlocks, kGpuBlockSize, sizeof(float) * kGpuBlockSize, stream_>>>(
        d_signal_, d_block_sums_, kSignalWidth);
    check_cuda(cudaGetLastError(), "reduce_kernel");

    check_cuda(cudaMemcpyAsync(partial_host_.data(), d_block_sums_, sizeof(float) * kGpuReduceBlocks,
                               cudaMemcpyDeviceToHost, stream_),
               "cudaMemcpyAsync(block_sums)");
    check_cuda(cudaMemcpyAsync(task.signal.data(), d_signal_, sizeof(float) * kSignalWidth,
                               cudaMemcpyDeviceToHost, stream_),
               "cudaMemcpyAsync(signal)");
    check_cuda(cudaEventRecord(stop_event_, stream_), "cudaEventRecord(stop)");
    check_cuda(cudaStreamSynchronize(stream_), "cudaStreamSynchronize");

    float elapsed_ms = 0.0f;
    check_cuda(cudaEventElapsedTime(&elapsed_ms, start_event_, stop_event_), "cudaEventElapsedTime");

    double total = 0.0;
    for (float value : partial_host_) {
      total += static_cast<double>(value);
    }
    task.aggregate = total / static_cast<double>(kSignalWidth);
    return elapsed_ms;
  }

 private:
  cudaStream_t stream_ = nullptr;
  cudaEvent_t start_event_ = nullptr;
  cudaEvent_t stop_event_ = nullptr;
  float* d_signal_ = nullptr;
  float* d_block_sums_ = nullptr;
  std::vector<float> partial_host_;
};

class AdaptivePipeline {
 public:
  explicit AdaptivePipeline(Args args)
      : args_(std::move(args)),
        stream_count_(std::max(1, args_.streams)),
        frames_per_stream_(std::max(1, static_cast<int>(std::round(args_.duration * args_.source_fps)))),
        total_frames_(stream_count_ * frames_per_stream_),
        seed_value_(args_.has_seed ? args_.seed : static_cast<std::uint32_t>(
                                         std::chrono::high_resolution_clock::now().time_since_epoch().count())) {
    rows_.reserve(static_cast<std::size_t>(total_frames_));
    events_.reserve(static_cast<std::size_t>(total_frames_) * 5);
    policy_decisions_.reserve(static_cast<std::size_t>(total_frames_) * 5);
    policy_feedback_.reserve(static_cast<std::size_t>(total_frames_));
    init_stages();
    load_policy_artifact();
  }

  int run() {
    print_cuda_device();
    start_workers();
    start_producers();
    wait_for_completion();
    close_workers();

    if (!failure_message_.empty()) {
      throw std::runtime_error(failure_message_);
    }

    if (args_.policy == "ql_heft_online") {
      std::lock_guard<std::mutex> lock(policy_mutex_);
      flush_pending_policy_feedback_locked();
    }

    write_csv();
    return 0;
  }

  int completed_frames() const {
    return completed_frames_.load();
  }

 private:
  Args args_;
  const int stream_count_;
  const int frames_per_stream_;
  const int total_frames_;
  std::vector<StageSpec> stages_;
  BlockingQueue<Task> cpu_queue_;
  BlockingQueue<Task> gpu_queue_;
  std::vector<std::thread> workers_;
  std::vector<std::thread> producers_;
  std::mutex rows_mutex_;
  std::vector<FrameRecord> rows_;
  std::vector<EventRecord> events_;
  std::vector<PolicyDecisionRecord> policy_decisions_;
  std::vector<PolicyFeedbackRecord> policy_feedback_;
  std::mutex done_mutex_;
  std::condition_variable done_cv_;
  std::atomic<int> remaining_frames_{0};
  std::atomic<int> active_cpu_{0};
  std::atomic<int> active_gpu_{0};
  std::atomic<bool> stop_requested_{false};
  std::atomic<int> completed_frames_{0};
  std::mutex failure_mutex_;
  std::string failure_message_;
  std::uint32_t seed_value_ = 0;
  std::atomic<double> cpu_queue_weight_{1.0};
  std::atomic<double> gpu_queue_weight_{0.85};
  std::atomic<double> heavy_gpu_bonus_{1.75};
  int heavy_object_threshold_ = 32;
  double weight_lower_bound_ = 0.5;
  double weight_upper_bound_ = 1.5;
  std::string projection_rule_ = "unavailable";
  std::uint64_t feedback_lag_limit_ = 0;
  std::uint64_t feedback_cooldown_events_ = 0;
  double variation_budget_ = 0.0;
  std::string feedback_update_rule_ = "unavailable";
  double feedback_penalty_step_ = 0.0;
  double feedback_reward_step_ = 0.0;
  std::mutex policy_mutex_;
  std::deque<PendingPolicyFeedback> pending_policy_feedback_;
  std::uint64_t next_decision_ordinal_ = 0;
  std::uint64_t next_feedback_seq_ = 0;
  std::uint64_t policy_update_seq_ = 0;
  std::uint64_t last_update_feedback_seq_ = 0;
  double policy_total_variation_ = 0.0;
  const std::chrono::steady_clock::time_point telemetry_steady_epoch_ = std::chrono::steady_clock::now();
  const std::chrono::system_clock::time_point telemetry_wall_epoch_ = std::chrono::system_clock::now();

  double telemetry_timestamp_ms(std::chrono::steady_clock::time_point timestamp) const {
    const auto wall_epoch_ms = std::chrono::duration<double, std::milli>(telemetry_wall_epoch_.time_since_epoch()).count();
    const auto elapsed_ms = std::chrono::duration<double, std::milli>(timestamp - telemetry_steady_epoch_).count();
    return wall_epoch_ms + elapsed_ms;
  }

  void init_stages() {
    const std::vector<std::string> requested = requested_pipeline_stages();
    if (requested.empty()) {
      stages_ = {
          stage_spec_for_name("decode"),
          stage_spec_for_name("detect"),
          stage_spec_for_name("track"),
          stage_spec_for_name("classify"),
          stage_spec_for_name("visualize"),
      };
      return;
    }

    stages_.clear();
    stages_.reserve(requested.size());
    for (const auto& stage : requested) {
      stages_.push_back(stage_spec_for_name(stage));
    }
    if (stages_.empty()) {
      stages_.push_back(stage_spec_for_name("aggregate"));
    }
  }

  static std::string trim_copy(const std::string& value) {
    const auto first = value.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) {
      return "";
    }
    const auto last = value.find_last_not_of(" \t\r\n");
    return value.substr(first, last - first + 1);
  }

  static std::vector<std::string> split_csv(const std::string& value) {
    std::vector<std::string> parts;
    std::string current;
    std::istringstream input(value);
    while (std::getline(input, current, ',')) {
      current = trim_copy(current);
      if (!current.empty()) {
        parts.push_back(current);
      }
    }
    return parts;
  }

  static std::vector<std::string> requested_pipeline_stages() {
    const char* raw = std::getenv("EXPERIMENT_PIPELINE_STAGES");
    if (raw == nullptr) {
      return {};
    }
    return split_csv(raw);
  }

  static bool is_branch_suffix(const std::string& suffix) {
    return suffix == "a" || suffix == "b" || suffix == "primary" ||
           suffix == "secondary" || suffix == "left" || suffix == "right";
  }

  static std::string stage_base_name(const std::string& name) {
    const auto pos = name.rfind('_');
    if (pos == std::string::npos || pos == 0 || pos + 1 >= name.size()) {
      return name;
    }
    const std::string base = name.substr(0, pos);
    const std::string suffix = name.substr(pos + 1);
    if (!is_branch_suffix(suffix)) {
      return name;
    }
    if (base == "decode" || base == "preprocess" || base == "detect" || base == "track" ||
        base == "classify" || base == "aggregate" || base == "record" || base == "visualize") {
      return base;
    }
    return name;
  }

  static StageSpec stage_spec_for_name(const std::string& name) {
    const std::string base = stage_base_name(name);
    if (base == "decode") return {name, Resource::Gpu, 0.95f, 1.05f, 0.08f};
    if (base == "preprocess") return {name, Resource::Cpu, 1.12f, 0.90f, 0.12f};
    if (base == "detect") return {name, Resource::Gpu, 1.05f, 1.35f, 0.22f};
    if (base == "track") return {name, Resource::Cpu, 1.25f, 0.85f, 0.16f};
    if (base == "classify") return {name, Resource::Cpu, 1.05f, 0.70f, 0.11f};
    if (base == "aggregate") return {name, Resource::Cpu, 0.88f, 0.62f, 0.05f};
    if (base == "record") return {name, Resource::Cpu, 0.82f, 0.55f, 0.04f};
    if (base == "visualize") return {name, Resource::Cpu, 0.90f, 0.65f, 0.06f};
    return {name, Resource::Cpu, 1.00f, 0.70f, 0.05f};
  }

  void load_policy_artifact() {
    if (args_.policy != "ql_heft_frozen" && args_.policy != "ql_heft_online") {
      return;
    }
    std::ifstream input(args_.policy_artifact);
    if (!input.is_open()) {
      throw std::runtime_error("Adaptive-weight policy artifact is missing: " + args_.policy_artifact);
    }
    int artifact_schema_version = 0;
    std::string line;
    while (std::getline(input, line)) {
      const auto pos = line.find('=');
      if (pos == std::string::npos) continue;
      const std::string key = line.substr(0, pos);
      const std::string value = line.substr(pos + 1);
      if (key == "schema_version") artifact_schema_version = std::stoi(value);
      if (key == "cpu_queue_weight") cpu_queue_weight_.store(std::stod(value));
      if (key == "gpu_queue_weight") gpu_queue_weight_.store(std::stod(value));
      if (key == "heavy_gpu_bonus") heavy_gpu_bonus_.store(std::stod(value));
      if (key == "heavy_object_threshold") heavy_object_threshold_ = std::stoi(value);
      if (key == "weight_lower_bound") weight_lower_bound_ = std::stod(value);
      if (key == "weight_upper_bound") weight_upper_bound_ = std::stod(value);
      if (key == "projection_rule") projection_rule_ = value;
      if (key == "feedback_lag_limit") feedback_lag_limit_ = std::stoull(value);
      if (key == "feedback_cooldown_events") feedback_cooldown_events_ = std::stoull(value);
      if (key == "variation_budget") variation_budget_ = std::stod(value);
      if (key == "feedback_update_rule") feedback_update_rule_ = value;
      if (key == "feedback_penalty_step") feedback_penalty_step_ = std::stod(value);
      if (key == "feedback_reward_step") feedback_reward_step_ = std::stod(value);
    }
    const vast_weighted_proxy::WeightPair initial_weights{
        cpu_queue_weight_.load(), gpu_queue_weight_.load()};
    const vast_weighted_proxy::WeightPair minimum_weights{
        weight_lower_bound_, weight_lower_bound_};
    const vast_weighted_proxy::WeightPair maximum_weights{
        weight_upper_bound_, weight_upper_bound_};
    (void)vast_weighted_proxy::project_box_mean_one(
        initial_weights, minimum_weights, maximum_weights);
    if (artifact_schema_version != 2 || !vast_weighted_proxy::mean_one(initial_weights) ||
        initial_weights.cpu < weight_lower_bound_ || initial_weights.cpu > weight_upper_bound_ ||
        initial_weights.gpu < weight_lower_bound_ || initial_weights.gpu > weight_upper_bound_ ||
        !std::isfinite(heavy_gpu_bonus_.load()) || heavy_gpu_bonus_.load() <= 0.0 ||
        heavy_object_threshold_ < 0 || projection_rule_ != "euclidean_box_mean_one_v1" ||
        feedback_update_rule_ != "simplified_gpu_queue_terminal_signal_v1" ||
        !std::isfinite(feedback_penalty_step_) || feedback_penalty_step_ <= 0.0 ||
        !std::isfinite(feedback_reward_step_) || feedback_reward_step_ <= 0.0 ||
        !std::isfinite(variation_budget_) || variation_budget_ < 0.0) {
      throw std::runtime_error("Adaptive-weight policy artifact violates the bounded feedback passport");
    }
  }

  void print_cuda_device() {
    int device_count = 0;
    check_cuda(cudaGetDeviceCount(&device_count), "cudaGetDeviceCount");
    if (device_count <= 0) {
      throw std::runtime_error("No CUDA device available");
    }
    cudaDeviceProp prop{};
    check_cuda(cudaGetDeviceProperties(&prop, 0), "cudaGetDeviceProperties");
    std::cout << "[cuda] device 0: " << prop.name << " (sm " << prop.major << "." << prop.minor
              << ")\n";
  }

  static int clamp_int(int value, int lo, int hi) {
    return std::max(lo, std::min(hi, value));
  }

  int object_count_for_frame(int frame_id, int stream_id) const {
    const int lo = std::min(args_.min_objects, args_.max_objects);
    const int hi = std::max(args_.min_objects, args_.max_objects);
    const int span = std::max(1, hi - lo + 1);
    const std::uint32_t mix = seed_value_ ^ static_cast<std::uint32_t>(frame_id * 2654435761u) ^
                              static_cast<std::uint32_t>(stream_id * 40503u);

    if (args_.scenario == "dynamic_workload") {
      const double phase = static_cast<double>((frame_id + stream_id * 11) % 120) / 120.0;
      const double wave = 0.5 + 0.5 * std::sin(phase * 2.0 * 3.14159265358979323846);
      return clamp_int(static_cast<int>(std::lround(lo + wave * (hi - lo))), lo, hi);
    }

    if (args_.scenario == "stream_scaling") {
      return clamp_int(lo + (stream_id % 4) * std::max(1, (hi - lo) / 6), lo, hi);
    }

    if (args_.scenario == "complex_pipeline") {
      return clamp_int(lo + (hi - lo) * 2 / 3, lo, hi);
    }

    if (args_.scenario == "heterogeneous_distribution") {
      return clamp_int(lo + ((frame_id + stream_id) % std::max(1, hi - lo + 1)), lo, hi);
    }

    return lo + static_cast<int>(mix % static_cast<std::uint32_t>(span));
  }

  void fill_signal(Task& task) const {
    const float base = 0.15f + 0.02f * static_cast<float>(task.objects);
    for (int i = 0; i < kSignalWidth; ++i) {
      const float phase = 0.0035f * static_cast<float>((task.frame_id + 1) * (i + 1));
      const float stream_bias = 0.01f * static_cast<float>(task.stream_id % 7);
      task.signal[static_cast<std::size_t>(i)] =
          base + stream_bias + std::sin(phase) + 0.5f * std::cos(phase * 0.37f);
    }
  }

  static bool is_ql_heft_policy(const std::string& policy) {
    return policy == "ql_heft_frozen" || policy == "ql_heft_online";
  }

  static std::string weights_json(double cpu_weight, double gpu_weight) {
    return "{\"cpu\":" + vast_policy_trace::json_number(cpu_weight) +
           ",\"gpu\":" + vast_policy_trace::json_number(gpu_weight) + "}";
  }

  static std::string weights_json(const vast_weighted_proxy::WeightPair& weights) {
    return weights_json(weights.cpu, weights.gpu);
  }

  static std::string string_array_json(const std::vector<std::string>& values) {
    std::string result = "[";
    for (std::size_t index = 0; index < values.size(); ++index) {
      if (index != 0) {
        result += ',';
      }
      result += vast_policy_trace::json_quote(values[index]);
    }
    result += ']';
    return result;
  }

  std::string frame_trace_id(const Task& task) const {
    return args_.run_id + ":" + std::to_string(task.stream_id) + ":" + std::to_string(task.frame_id);
  }

  static std::string feature_provenance_entry(const std::string& source,
                                              const std::string& source_trace_id,
                                              double observed_timestamp_ms,
                                              double decision_timestamp_ms,
                                              const std::string& estimator_version) {
    return "{\"source\":" + vast_policy_trace::json_quote(source) +
           ",\"source_trace_id\":" + vast_policy_trace::json_quote(source_trace_id) +
           ",\"observed_timestamp_ms\":" + vast_policy_trace::json_number(observed_timestamp_ms) +
           ",\"age_ms\":" +
           vast_policy_trace::json_number(std::max(0.0, decision_timestamp_ms - observed_timestamp_ms)) +
           ",\"estimator_version\":" + vast_policy_trace::json_quote(estimator_version) + "}";
  }

  std::string decision_feature_provenance_json(const Task& task,
                                               double queue_snapshot_timestamp_ms,
                                               double policy_snapshot_timestamp_ms,
                                               double decision_timestamp_ms) const {
    const std::string trace_id = frame_trace_id(task);
    const std::string scheduler_trace = args_.run_id + ":" + args_.policy;
    const std::string ingress = feature_provenance_entry(
        "native_signal_ingress_metadata",
        trace_id,
        telemetry_timestamp_ms(task.created_at),
        decision_timestamp_ms,
        "custom-signal-generator-v1");
    const std::string queue = feature_provenance_entry(
        "native_scheduler_snapshot",
        scheduler_trace,
        queue_snapshot_timestamp_ms,
        decision_timestamp_ms,
        "custom-scheduler-queue-snapshot-v1");
    const std::string profile = feature_provenance_entry(
        "configured_stage_profile",
        args_.policy_artifact,
        policy_snapshot_timestamp_ms,
        decision_timestamp_ms,
        "custom-signal-stage-proxy-v2");
    const std::string policy_state = feature_provenance_entry(
        "native_policy_state",
        scheduler_trace,
        policy_snapshot_timestamp_ms,
        decision_timestamp_ms,
        "simplified-cpu-gpu-weighted-proxy-v4");
    return "{\"objects\":" + ingress +
           ",\"cpu_queue_depth\":" + queue +
           ",\"gpu_queue_depth\":" + queue +
           ",\"active_cpu_tasks\":" + queue +
           ",\"active_gpu_tasks\":" + queue +
           ",\"cpu_profile_proxy_ms\":" + profile +
           ",\"gpu_profile_proxy_ms\":" + profile +
           ",\"stage_preference\":" + profile +
           ",\"cpu_weight\":" + policy_state +
           ",\"gpu_weight\":" + policy_state +
           ",\"heavy_gpu_bonus\":" + policy_state + "}";
  }

  static std::string alternative_scores_json(double cpu_score, double gpu_score) {
    return "{\"cpu\":" + vast_policy_trace::json_number(cpu_score) +
           ",\"gpu\":" + vast_policy_trace::json_number(gpu_score) + "}";
  }

  static std::string cost_components_json(double cpu_profile_ms,
                                          double gpu_profile_ms,
                                          double object_multiplier,
                                          std::size_t cpu_queue_depth,
                                          std::size_t gpu_queue_depth,
                                          int active_cpu,
                                          int active_gpu,
                                          double cpu_weight,
                                          double gpu_weight,
                                          double gpu_heavy_multiplier) {
    const auto component = [&](double profile_ms,
                               std::size_t queue_depth,
                               int active,
                               double weight,
                               double heavy_multiplier) {
      const double backlog = static_cast<double>(queue_depth + static_cast<std::size_t>(std::max(0, active)));
      return "{\"profile_exec_proxy_ms\":" + vast_policy_trace::json_number(profile_ms) +
             ",\"object_multiplier\":" + vast_policy_trace::json_number(object_multiplier) +
             ",\"queue_depth\":" + std::to_string(queue_depth) +
             ",\"active_tasks\":" + std::to_string(std::max(0, active)) +
             ",\"queue_wait_proxy_ms\":" +
             vast_policy_trace::json_number(backlog * profile_ms * object_multiplier) +
             ",\"weight\":" + vast_policy_trace::json_number(weight) +
             ",\"heavy_multiplier\":" + vast_policy_trace::json_number(heavy_multiplier) + "}";
    };
    return "{\"cpu\":" + component(cpu_profile_ms, cpu_queue_depth, active_cpu, cpu_weight, 1.0) +
           ",\"gpu\":" +
           component(gpu_profile_ms, gpu_queue_depth, active_gpu, gpu_weight, gpu_heavy_multiplier) + "}";
  }

  std::string parameters_json(double cpu_weight,
                              double gpu_weight,
                              double heavy_bonus,
                              bool heavy_scene,
                              Resource stage_preference) const {
    return "{\"score_epsilon\":1e-9,\"weights\":" + weights_json(cpu_weight, gpu_weight) +
           ",\"weight_lower_bounds\":" + weights_json(weight_lower_bound_, weight_lower_bound_) +
           ",\"weight_upper_bounds\":" + weights_json(weight_upper_bound_, weight_upper_bound_) +
           ",\"projection_rule\":" + vast_policy_trace::json_quote(projection_rule_) +
           ",\"feedback_lag_limit\":" + std::to_string(feedback_lag_limit_) +
           ",\"feedback_cooldown_events\":" + std::to_string(feedback_cooldown_events_) +
           ",\"variation_budget\":" + vast_policy_trace::json_number(variation_budget_) +
           ",\"feedback_update_rule\":" + vast_policy_trace::json_quote(feedback_update_rule_) +
           ",\"feedback_update_parameters\":{\"penalty_step\":" +
           vast_policy_trace::json_number(feedback_penalty_step_) +
           ",\"reward_step\":" + vast_policy_trace::json_number(feedback_reward_step_) + "}" +
           ",\"heavy_gpu_bonus\":" + vast_policy_trace::json_number(heavy_bonus) +
           ",\"heavy_object_threshold\":" + std::to_string(heavy_object_threshold_) +
           ",\"heavy_scene\":" + (heavy_scene ? "true" : "false") +
           ",\"stage_preference\":" +
           vast_policy_trace::json_quote(resource_name(stage_preference)) +
           ",\"policy_scope\":\"simplified_cpu_gpu_queue_weighted_proxy\"}";
  }

  static std::string feedback_features_json(const PendingPolicyFeedback& feedback) {
    return "{\"trace_id\":" + vast_policy_trace::json_quote(feedback.trace_id) +
           ",\"latency_ms\":" + vast_policy_trace::json_number(feedback.latency_ms) +
           ",\"deadline_ms\":" + vast_policy_trace::json_number(feedback.deadline_ms) +
           ",\"gpu_queue_depth\":" + std::to_string(feedback.gpu_queue_depth) +
           ",\"late\":" + (feedback.late ? "true" : "false") +
           ",\"overloaded\":" + (feedback.overloaded ? "true" : "false") +
           ",\"stable\":" + (feedback.stable ? "true" : "false") +
           ",\"terminal_status\":" + vast_policy_trace::json_quote(feedback.terminal_status) +
           ",\"terminal_timestamp_ms\":" +
           vast_policy_trace::json_number(feedback.terminal_timestamp_ms) + "}";
  }

  AppliedPolicyUpdate process_pending_policy_feedback_locked(
      const std::string& first_consumer_decision_id,
      std::uint64_t first_consumer_decision_seq,
      bool has_first_consumer) {
    while (!pending_policy_feedback_.empty()) {
      PendingPolicyFeedback feedback = std::move(pending_policy_feedback_.front());
      pending_policy_feedback_.pop_front();
      if (feedback.source_parameter_snapshot_seq > policy_update_seq_) {
        throw std::runtime_error("Terminal feedback references a future parameter snapshot");
      }

      PolicyFeedbackRecord record;
      record.feedback_seq = ++next_feedback_seq_;
      record.feedback_timestamp_ms = telemetry_timestamp_ms(std::chrono::steady_clock::now());
      record.source_trace_id = feedback.trace_id;
      record.terminal_status = feedback.terminal_status;
      record.terminal_timestamp_ms = feedback.terminal_timestamp_ms;
      record.source_decision_ids_json = string_array_json(feedback.source_decision_ids);
      record.source_parameter_snapshot_seq = feedback.source_parameter_snapshot_seq;
      record.parameter_lag = policy_update_seq_ - feedback.source_parameter_snapshot_seq;
      record.events_since_update = record.feedback_seq - last_update_feedback_seq_;
      record.old_weights = {cpu_queue_weight_.load(), gpu_queue_weight_.load()};
      const double delta = vast_weighted_proxy::update_delta(
          feedback.signal, feedback_penalty_step_, feedback_reward_step_);
      record.raw_weights = {record.old_weights.cpu, record.old_weights.gpu + delta};
      record.projected_weights = vast_weighted_proxy::project_box_mean_one(
          record.raw_weights,
          {weight_lower_bound_, weight_lower_bound_},
          {weight_upper_bound_, weight_upper_bound_});
      record.variation_before = policy_total_variation_;
      record.feedback_features_json = feedback_features_json(feedback);

      const double candidate_variation = vast_weighted_proxy::l1_variation(
          record.old_weights, record.projected_weights);
      vast_weighted_proxy::FeedbackGateInput gate_input;
      gate_input.signal = feedback.signal;
      gate_input.censored = feedback.terminal_status == "censored";
      gate_input.parameter_lag = record.parameter_lag;
      gate_input.lag_limit = feedback_lag_limit_;
      gate_input.events_since_update = record.events_since_update;
      gate_input.cooldown_events = feedback_cooldown_events_;
      gate_input.candidate_variation = candidate_variation;
      gate_input.variation_before = policy_total_variation_;
      gate_input.variation_budget = variation_budget_;
      gate_input.has_first_consumer = has_first_consumer;
      const vast_weighted_proxy::FeedbackGateDecision gate =
          vast_weighted_proxy::evaluate_feedback_gate(gate_input);
      record.reason = gate.reason;

      AppliedPolicyUpdate applied;
      if (gate.apply) {
        cpu_queue_weight_.store(record.projected_weights.cpu);
        gpu_queue_weight_.store(record.projected_weights.gpu);
        ++policy_update_seq_;
        last_update_feedback_seq_ = record.feedback_seq;
        policy_total_variation_ += candidate_variation;
        record.feedback_action = "update";
        record.variation_after = policy_total_variation_;
        record.update_seq = policy_update_seq_;
        record.first_consumer_decision_id = first_consumer_decision_id;
        record.first_consumer_decision_seq = first_consumer_decision_seq;

        applied.update_timestamp_ms = record.feedback_timestamp_ms;
        applied.source_decision_ids_json = record.source_decision_ids_json;
        applied.update_json = "{\"reason\":" + vast_policy_trace::json_quote(record.reason) +
                              ",\"features\":" + record.feedback_features_json +
                              ",\"old_weights\":" + weights_json(record.old_weights) +
                              ",\"new_weights\":" + weights_json(record.projected_weights) + "}";
        policy_feedback_.push_back(std::move(record));
        return applied;
      }

      record.feedback_action = "no_op";
      record.variation_after = policy_total_variation_;
      record.update_seq = policy_update_seq_;
      policy_feedback_.push_back(std::move(record));
    }
    return AppliedPolicyUpdate{};
  }

  void flush_pending_policy_feedback_locked() {
    (void)process_pending_policy_feedback_locked("unavailable", 0, false);
    if (!pending_policy_feedback_.empty()) {
      throw std::runtime_error("Pending policy feedback was not fully drained");
    }
  }

  DecisionSnapshot choose_ql_heft_decision(int stage_index, const Task& task) {
    const StageSpec& stage = stages_[static_cast<std::size_t>(stage_index)];
    const std::size_t cpu_queue_depth = cpu_queue_.size();
    const std::size_t gpu_queue_depth = gpu_queue_.size();
    const int active_cpu = active_cpu_.load();
    const int active_gpu = active_gpu_.load();
    const double object_multiplier = 1.0 + 0.01 * static_cast<double>(task.objects);
    const bool heavy_scene = task.objects >= heavy_object_threshold_;
    const double queue_snapshot_timestamp_ms = telemetry_timestamp_ms(std::chrono::steady_clock::now());

    std::lock_guard<std::mutex> lock(policy_mutex_);
    DecisionSnapshot decision;
    decision.ordinal = next_decision_ordinal_++;
    decision.decision_seq = decision.ordinal + 1;
    decision.decision_id = args_.run_id + ":" + args_.policy + ":decision:" +
                           std::to_string(decision.decision_seq);
    const AppliedPolicyUpdate applied_update =
        args_.policy == "ql_heft_online"
            ? process_pending_policy_feedback_locked(
                  decision.decision_id, decision.decision_seq, true)
            : AppliedPolicyUpdate{};
    decision.update_json = applied_update.update_json;
    decision.update_timestamp_ms = applied_update.update_timestamp_ms;
    decision.source_decision_ids_json = applied_update.source_decision_ids_json;
    if (decision.update_json != "{}") {
      decision.first_consumer_decision_id = decision.decision_id;
      decision.first_consumer_decision_seq = decision.decision_seq;
    }
    decision.update_seq = policy_update_seq_;

    const double cpu_weight = cpu_queue_weight_.load();
    const double gpu_weight = gpu_queue_weight_.load();
    const double heavy_bonus = heavy_gpu_bonus_.load();
    const double policy_snapshot_timestamp_ms = telemetry_timestamp_ms(std::chrono::steady_clock::now());
    const double gpu_heavy_multiplier = heavy_scene ? 1.0 / heavy_bonus : 1.0;
    constexpr double score_epsilon = 1e-9;
    vast_weighted_proxy::DecisionInput proxy_input;
    proxy_input.cpu_profile_proxy_ms = stage.cpu_gain;
    proxy_input.gpu_profile_proxy_ms = stage.gpu_gain;
    proxy_input.object_multiplier = object_multiplier;
    proxy_input.cpu_queue_depth = cpu_queue_depth;
    proxy_input.gpu_queue_depth = gpu_queue_depth;
    proxy_input.active_cpu = active_cpu;
    proxy_input.active_gpu = active_gpu;
    proxy_input.cpu_weight = cpu_weight;
    proxy_input.gpu_weight = gpu_weight;
    proxy_input.gpu_heavy_multiplier = gpu_heavy_multiplier;
    proxy_input.score_epsilon = score_epsilon;
    proxy_input.stage_preference = stage.preferred == Resource::Cpu
                                       ? vast_weighted_proxy::Resource::Cpu
                                       : vast_weighted_proxy::Resource::Gpu;
    const vast_weighted_proxy::Decision proxy_decision = vast_weighted_proxy::choose(proxy_input);
    decision.resource = proxy_decision.selected == vast_weighted_proxy::Resource::Cpu
                            ? Resource::Cpu
                            : Resource::Gpu;
    decision.reason = proxy_decision.reason;
    const double cpu_score = proxy_decision.cpu_score_ms;
    const double gpu_score = proxy_decision.gpu_score_ms;

    decision.queue_depth = decision.resource == Resource::Cpu ? cpu_queue_depth : gpu_queue_depth;
    decision.cpu_queue_depth_snapshot = cpu_queue_depth;
    decision.gpu_queue_depth_snapshot = gpu_queue_depth;
    decision.selected_score_ms = decision.resource == Resource::Cpu ? cpu_score : gpu_score;
    decision.policy_version = "simplified-cpu-gpu-weighted-proxy-v4-" +
                              std::string(args_.policy == "ql_heft_online" ? "online" : "frozen");
    decision.allowed_resources_json = "[\"cpu\",\"gpu\"]";
    decision.alternative_scores_json = alternative_scores_json(cpu_score, gpu_score);
    decision.cost_components_json = cost_components_json(
        stage.cpu_gain,
        stage.gpu_gain,
        object_multiplier,
        cpu_queue_depth,
        gpu_queue_depth,
        active_cpu,
        active_gpu,
        cpu_weight,
        gpu_weight,
        gpu_heavy_multiplier);
    decision.parameters_json = parameters_json(
        cpu_weight, gpu_weight, heavy_bonus, heavy_scene, stage.preferred);
    decision.tie_break_rule = "score_then_queue_depth_then_stage_preference";
    decision.graph_version = "custom-signal-graph-v2:" + args_.scenario;
    decision.profile_version = "custom-signal-stage-proxy-v2";
    decision.decision_timestamp_ms = telemetry_timestamp_ms(std::chrono::steady_clock::now());
    decision.feature_provenance_json = decision_feature_provenance_json(
        task,
        queue_snapshot_timestamp_ms,
        policy_snapshot_timestamp_ms,
        decision.decision_timestamp_ms);
    decision.replayable = true;
    return decision;
  }

  void queue_online_policy_feedback(const Task& task, double latency_ms, double terminal_timestamp_ms) {
    if (args_.policy != "ql_heft_online" || task.applied_decision_ids.empty()) {
      return;
    }
    const std::size_t gpu_queue_depth = task.max_applied_gpu_queue_depth;
    PendingPolicyFeedback feedback;
    feedback.trace_id = frame_trace_id(task);
    feedback.latency_ms = latency_ms;
    feedback.deadline_ms = args_.deadline_ms;
    feedback.gpu_queue_depth = gpu_queue_depth;
    feedback.late = latency_ms > args_.deadline_ms;
    feedback.overloaded = gpu_queue_depth > 0;
    feedback.stable = !feedback.late && gpu_queue_depth == 0;
    feedback.terminal_timestamp_ms = terminal_timestamp_ms;
    feedback.source_decision_ids = task.applied_decision_ids;
    feedback.source_parameter_snapshot_seq = task.oldest_applied_parameter_snapshot_seq;
    feedback.signal = vast_weighted_proxy::classify_update(
        latency_ms, args_.deadline_ms, gpu_queue_depth);
    std::lock_guard<std::mutex> lock(policy_mutex_);
    pending_policy_feedback_.push_back(std::move(feedback));
  }

  Resource choose_resource(int stage_index, const Task& task) const {
    const StageSpec& stage = stages_[static_cast<std::size_t>(stage_index)];
    const std::size_t cpu_backlog = cpu_queue_.size() + static_cast<std::size_t>(active_cpu_.load());
    const std::size_t gpu_backlog = gpu_queue_.size() + static_cast<std::size_t>(active_gpu_.load());
    const bool detect_heavy = task.objects >
                              ((std::min(args_.min_objects, args_.max_objects) +
                                std::max(args_.min_objects, args_.max_objects)) /
                               2);

    if (args_.policy == "cpu_only") {
      return Resource::Cpu;
    }
    if (args_.policy == "gpu_only") {
      return Resource::Gpu;
    }
    if (args_.policy == "static_hybrid") {
      return stage.preferred;
    }
    if (args_.policy == "heft") {
      const double cpu_cost = static_cast<double>(cpu_backlog + 1) * stage.cpu_gain;
      const double gpu_cost = static_cast<double>(gpu_backlog + 1) * stage.gpu_gain;
      return gpu_cost <= cpu_cost ? Resource::Gpu : Resource::Cpu;
    }
    if (args_.policy == "deadline_aware_heft") {
      const auto now = std::chrono::steady_clock::now();
      const double elapsed_ms = std::chrono::duration<double, std::milli>(now - task.created_at).count();
      const double remaining_ms = std::max(0.1, args_.deadline_ms - elapsed_ms);
      const double deadline_pressure = remaining_ms < args_.deadline_ms * 0.35 ? 0.72 : 1.0;
      const double cpu_cost = static_cast<double>(cpu_backlog + 1) * stage.cpu_gain;
      const double gpu_cost = static_cast<double>(gpu_backlog + 1) * stage.gpu_gain * deadline_pressure;
      return gpu_cost <= cpu_cost ? Resource::Gpu : Resource::Cpu;
    }
    if (args_.policy == "queue_aware_edf") {
      const auto now = std::chrono::steady_clock::now();
      const double elapsed_ms = std::chrono::duration<double, std::milli>(now - task.created_at).count();
      const double slack_ms = std::max(0.1, args_.deadline_ms - elapsed_ms);
      const double cpu_cost = (static_cast<double>(cpu_backlog) + 1.0) * stage.cpu_gain / slack_ms;
      const double gpu_cost = (static_cast<double>(gpu_backlog) + 1.0) * stage.gpu_gain / slack_ms;
      return gpu_cost <= cpu_cost ? Resource::Gpu : Resource::Cpu;
    }
    if (args_.policy == "adaptive_weights") {
      const double cpu_cost = static_cast<double>(cpu_backlog + 1) * stage.cpu_gain * cpu_queue_weight_.load();
      double gpu_cost = static_cast<double>(gpu_backlog + 1) * stage.gpu_gain * gpu_queue_weight_.load();
      if (task.objects >= heavy_object_threshold_) {
        gpu_cost /= heavy_gpu_bonus_.load();
      }
      return gpu_cost <= cpu_cost ? Resource::Gpu : Resource::Cpu;
    }
    if (args_.policy == "no_queues") {
      return stage.gpu_gain <= stage.cpu_gain ? Resource::Gpu : Resource::Cpu;
    }
    if (args_.policy == "no_transfer_cost") {
      const double cpu_cost = static_cast<double>(cpu_backlog + 1) * stage.cpu_gain;
      const double gpu_cost = static_cast<double>(gpu_backlog + 1) * stage.gpu_gain;
      return gpu_cost <= cpu_cost ? Resource::Gpu : Resource::Cpu;
    }
    if (args_.policy == "no_deadline_penalty") {
      const double cpu_cost = static_cast<double>(cpu_backlog + 1) * stage.cpu_gain;
      const double gpu_cost = static_cast<double>(gpu_backlog + 1) * stage.gpu_gain;
      return gpu_cost <= cpu_cost ? Resource::Gpu : Resource::Cpu;
    }
    if (args_.policy == "no_adaptive_weights") {
      const double cpu_cost = static_cast<double>(cpu_backlog + 1) * stage.cpu_gain;
      double gpu_cost = static_cast<double>(gpu_backlog + 1) * stage.gpu_gain;
      if (task.objects >= heavy_object_threshold_) {
        gpu_cost /= heavy_gpu_bonus_.load();
      }
      return gpu_cost <= cpu_cost ? Resource::Gpu : Resource::Cpu;
    }
    if (args_.scenario == "heterogeneous_distribution") {
      if (stage.preferred == Resource::Gpu) {
        return (gpu_backlog <= cpu_backlog + 1 || detect_heavy) ? Resource::Gpu : Resource::Cpu;
      }
      return (cpu_backlog <= gpu_backlog + 1) ? Resource::Cpu : Resource::Gpu;
    }

    if (args_.scenario == "stream_scaling") {
      if (stage.preferred == Resource::Gpu) {
        return (gpu_backlog <= cpu_backlog + 4) ? Resource::Gpu : Resource::Cpu;
      }
      return Resource::Cpu;
    }

    if (args_.scenario == "dynamic_workload") {
      if (stage.preferred == Resource::Gpu) {
        return (detect_heavy || gpu_backlog <= cpu_backlog + 2) ? Resource::Gpu : Resource::Cpu;
      }
      return (cpu_backlog <= gpu_backlog + 2) ? Resource::Cpu : Resource::Gpu;
    }

    if (stage.preferred == Resource::Gpu) {
      return (gpu_backlog <= cpu_backlog + 2) ? Resource::Gpu : Resource::Cpu;
    }
    return (cpu_backlog <= gpu_backlog + 2) ? Resource::Cpu : Resource::Gpu;
  }

  static const char* resource_name(Resource resource) {
    return resource == Resource::Cpu ? "cpu" : "gpu";
  }

  double estimated_cost_ms(Resource resource, const StageSpec& stage, const Task& task) const {
    const double backlog = resource == Resource::Cpu ? cpu_queue_.size() + active_cpu_.load()
                                                     : gpu_queue_.size() + active_gpu_.load();
    const double gain = resource == Resource::Cpu ? stage.cpu_gain : stage.gpu_gain;
    return (backlog + 1.0) * gain * (1.0 + 0.01 * static_cast<double>(task.objects));
  }

  float cpu_stage_step(Task& task, const StageSpec& stage) const {
    const auto start = std::chrono::steady_clock::now();
    const float gain = stage.cpu_gain * (1.0f + 0.01f * static_cast<float>(task.objects));
    const float bias = stage.bias + 0.0015f * static_cast<float>(task.stream_id);
    double total = 0.0;

    for (int i = 0; i < kSignalWidth; ++i) {
      float value = task.signal[static_cast<std::size_t>(i)];
      for (int iter = 0; iter < 6 + task.stage_index; ++iter) {
        value = std::tanh(value * gain + bias + 0.0002f * static_cast<float>(i));
        value += 0.12f * std::sin(value + stage.bias);
      }
      task.signal[static_cast<std::size_t>(i)] = value;
      total += std::fabs(value);
    }

    task.aggregate = total / static_cast<double>(kSignalWidth);
    return std::chrono::duration<float, std::milli>(std::chrono::steady_clock::now() - start).count();
  }

  float gpu_stage_step(Task& task, const StageSpec& stage, GpuExecutor& executor) const {
    const float elapsed_ms = executor.run(task, stage);
    task.aggregate += static_cast<double>(elapsed_ms) * 0.001;
    return elapsed_ms;
  }

  void record_completion(const Task& task) {
    const auto completed_at = std::chrono::steady_clock::now();
    const double terminal_timestamp_ms = telemetry_timestamp_ms(completed_at);
    const auto latency_ms =
        std::chrono::duration_cast<std::chrono::microseconds>(completed_at - task.created_at).count() / 1000.0;
    FrameRecord row;
    row.trace_id = frame_trace_id(task);
    row.frame_id = task.frame_id;
    row.stream_id = task.stream_id;
    row.objects = task.objects;
    row.ingress_timestamp_ms = telemetry_timestamp_ms(task.created_at);
    row.egress_timestamp_ms = terminal_timestamp_ms;
    row.latency_ms = latency_ms;

    {
      std::lock_guard<std::mutex> lock(rows_mutex_);
      rows_.push_back(row);
      for (auto& policy_record : policy_decisions_) {
        if (std::find(
                task.applied_decision_ids.begin(),
                task.applied_decision_ids.end(),
                policy_record.decision.decision_id) != task.applied_decision_ids.end()) {
          policy_record.decision.terminal_status = "completed";
          policy_record.decision.terminal_timestamp_ms = terminal_timestamp_ms;
        }
      }
    }
    queue_online_policy_feedback(task, latency_ms, terminal_timestamp_ms);
    if (args_.policy == "adaptive_weights") {
      const double direction = latency_ms > args_.deadline_ms ? 0.002 : -0.0002;
      gpu_queue_weight_.store(std::max(0.5, std::min(1.5, gpu_queue_weight_.load() + direction)));
    }
    ++completed_frames_;

    if (remaining_frames_.fetch_sub(1) == 1) {
      done_cv_.notify_one();
    }
  }

  void enqueue_stage(Task task) {
    if (stop_requested_.load()) {
      return;
    }

    task.queue_enter_at = std::chrono::steady_clock::now();
    Resource resource = Resource::Cpu;
    if (is_ql_heft_policy(args_.policy)) {
      task.decision = choose_ql_heft_decision(task.stage_index, task);
      const bool first_applied_decision = task.applied_decision_ids.empty();
      task.applied_decision_ids.push_back(task.decision.decision_id);
      task.max_applied_gpu_queue_depth =
          std::max(task.max_applied_gpu_queue_depth, task.decision.gpu_queue_depth_snapshot);
      task.oldest_applied_parameter_snapshot_seq =
          first_applied_decision
              ? task.decision.update_seq
              : std::min(task.oldest_applied_parameter_snapshot_seq, task.decision.update_seq);
      resource = task.decision.resource;
    } else {
      resource = choose_resource(task.stage_index, task);
      const StageSpec& stage = stages_[static_cast<std::size_t>(task.stage_index)];
      task.decision.resource = resource;
      task.decision.queue_depth = resource == Resource::Cpu ? cpu_queue_.size() : gpu_queue_.size();
      task.decision.selected_score_ms = estimated_cost_ms(resource, stage, task);
    }
    if (resource == Resource::Cpu) {
      cpu_queue_.push(std::move(task));
    } else {
      gpu_queue_.push(std::move(task));
    }
  }

  void process_task(Task task, Resource resource, GpuExecutor* gpu_executor) {
    const StageSpec& stage = stages_[static_cast<std::size_t>(task.stage_index)];
    const auto stage_start = std::chrono::steady_clock::now();
    const std::size_t queue_depth = task.decision.queue_depth;
    const double predicted_ms = task.decision.selected_score_ms;
    if (resource == Resource::Cpu) {
      (void)cpu_stage_step(task, stage);
    } else {
      if (gpu_executor == nullptr) {
        throw std::runtime_error("GPU executor unavailable");
      }
      (void)gpu_stage_step(task, stage, *gpu_executor);
    }
    const auto stage_end = std::chrono::steady_clock::now();
    EventRecord event;
    event.trace_id = args_.run_id + ":" + std::to_string(task.stream_id) + ":" + std::to_string(task.frame_id);
    event.frame_id = task.frame_id;
    event.stream_id = task.stream_id;
    event.stage = stage.name;
    event.resource = resource_name(resource);
    event.queue_enter_timestamp_ms = telemetry_timestamp_ms(task.queue_enter_at);
    event.stage_start_timestamp_ms = telemetry_timestamp_ms(stage_start);
    event.stage_end_timestamp_ms = telemetry_timestamp_ms(stage_end);
    event.queue_depth = queue_depth;
    event.estimated_cost_ms = predicted_ms;
    event.policy_action = args_.policy + ":" + resource_name(resource);
    {
      std::lock_guard<std::mutex> lock(rows_mutex_);
      events_.push_back(std::move(event));
      if (task.decision.replayable) {
        PolicyDecisionRecord policy_record;
        policy_record.trace_id = args_.run_id + ":" + std::to_string(task.stream_id) + ":" +
                                 std::to_string(task.frame_id);
        policy_record.frame_id = task.frame_id;
        policy_record.stream_id = task.stream_id;
        policy_record.stage = stage.name;
        policy_record.decision = task.decision;
        policy_decisions_.push_back(std::move(policy_record));
      }
    }

    ++task.stage_index;
    if (task.stage_index < static_cast<int>(stages_.size())) {
      enqueue_stage(std::move(task));
      return;
    }

    record_completion(task);
  }

  void handle_failure(const std::string& message) {
    bool notify = false;
    {
      std::lock_guard<std::mutex> lock(failure_mutex_);
      if (failure_message_.empty()) {
        failure_message_ = message;
        notify = true;
      }
    }

    if (notify) {
      stop_requested_.store(true);
      cpu_queue_.close();
      gpu_queue_.close();
      done_cv_.notify_all();
    }
  }

  void cpu_worker_loop() {
    try {
      Task task;
      while (!stop_requested_.load() && cpu_queue_.pop(task)) {
        ++active_cpu_;
        try {
          process_task(std::move(task), Resource::Cpu, nullptr);
        } catch (...) {
          --active_cpu_;
          throw;
        }
        --active_cpu_;
      }
    } catch (const std::exception& ex) {
      handle_failure(ex.what());
    }
  }

  void gpu_worker_loop() {
    try {
      GpuExecutor executor;
      Task task;
      while (!stop_requested_.load() && gpu_queue_.pop(task)) {
        ++active_gpu_;
        try {
          process_task(std::move(task), Resource::Gpu, &executor);
        } catch (...) {
          --active_gpu_;
          throw;
        }
        --active_gpu_;
      }
    } catch (const std::exception& ex) {
      handle_failure(ex.what());
    }
  }

  void start_workers() {
    const unsigned hw = std::max(2u, std::thread::hardware_concurrency());
    const int cpu_workers = std::max(2, static_cast<int>(hw / 4));

    for (int i = 0; i < cpu_workers; ++i) {
      workers_.emplace_back([this] { cpu_worker_loop(); });
    }
    workers_.emplace_back([this] { gpu_worker_loop(); });
  }

  void start_producers() {
    remaining_frames_.store(total_frames_);
    const auto start_tp = std::chrono::steady_clock::now();
    const auto interval = std::chrono::duration<double>(1.0 / std::max(1.0, args_.source_fps));

    for (int stream_id = 0; stream_id < stream_count_; ++stream_id) {
      producers_.emplace_back([this, start_tp, interval, stream_id] {
        for (int frame_idx = 0; frame_idx < frames_per_stream_; ++frame_idx) {
          if (stop_requested_.load()) {
            break;
          }

          const auto due = start_tp + std::chrono::duration_cast<std::chrono::steady_clock::duration>(interval * frame_idx);
          std::this_thread::sleep_until(due);

          if (stop_requested_.load()) {
            break;
          }

          Task task;
          task.frame_id = frame_idx;
          task.stream_id = stream_id;
          task.stage_index = 0;
          task.objects = object_count_for_frame(task.frame_id, stream_id);
          task.created_at = std::chrono::steady_clock::now();
          fill_signal(task);
          enqueue_stage(std::move(task));
        }
      });
    }

    for (auto& producer : producers_) {
      producer.join();
    }
    producers_.clear();
  }

  void wait_for_completion() {
    std::unique_lock<std::mutex> lock(done_mutex_);
    done_cv_.wait(lock, [&] { return remaining_frames_.load() == 0 || stop_requested_.load(); });
  }

  void close_workers() {
    cpu_queue_.close();
    gpu_queue_.close();
    for (auto& worker : workers_) {
      if (worker.joinable()) {
        worker.join();
      }
    }
    workers_.clear();
  }

  fs::path resolve_output_path() const {
    fs::path out_path = args_.output;
    if (out_path.empty()) {
      out_path = ".";
    }
    const std::string out_str = out_path.string();
    const bool looks_like_dir = !out_str.empty() && (out_str.back() == '/' || out_str.back() == '\\');
    if (looks_like_dir || out_path.extension().empty()) {
      fs::create_directories(out_path);
      out_path /= "frames.csv";
    } else {
      fs::create_directories(out_path.parent_path());
    }
    return out_path;
  }

  static void write_csv_row(std::ofstream& output, const std::vector<std::string>& fields) {
    for (std::size_t index = 0; index < fields.size(); ++index) {
      if (index != 0) {
        output << ',';
      }
      output << vast_policy_trace::csv_escape(fields[index]);
    }
    output << '\n';
  }

  void write_csv() {
    const fs::path out_path = resolve_output_path();
    std::ofstream ofs(out_path.string(), std::ios::out | std::ios::trunc);
    if (!ofs.is_open()) {
      throw std::runtime_error("Failed to open output file: " + out_path.string());
    }

    std::sort(rows_.begin(), rows_.end(), [](const FrameRecord& a, const FrameRecord& b) {
      if (a.egress_timestamp_ms != b.egress_timestamp_ms) return a.egress_timestamp_ms < b.egress_timestamp_ms;
      return a.frame_id < b.frame_id;
    });

    ofs << "schema_version,run_id,trace_id,stream_id,frame_id,ingress_timestamp_ms,egress_timestamp_ms,e2e_latency_ms,objects,detector,backend,telemetry_source\n";
    ofs << std::fixed << std::setprecision(6);
    for (const auto& row : rows_) {
      ofs << "2,"
          << args_.run_id << ','
          << row.trace_id << ','
          << row.stream_id << ','
          << row.frame_id << ','
          << row.ingress_timestamp_ms << ','
          << row.egress_timestamp_ms << ','
          << row.latency_ms << ','
          << row.objects << ','
          << args_.detector << ','
          << args_.backend << ','
          << "native\n";
    }
    ofs.close();

    const fs::path events_path = out_path.parent_path() / "frame_events.csv";
    std::ofstream events(events_path.string(), std::ios::out | std::ios::trunc);
    if (!events.is_open()) {
      throw std::runtime_error("Failed to open output file: " + events_path.string());
    }
    events << "schema_version,run_id,trace_id,stream_id,frame_id,stage,role,host,resource,queue_enter_timestamp_ms,stage_start_timestamp_ms,stage_end_timestamp_ms,queue_depth,estimated_cost_ms,policy_action\n";
    events << std::fixed << std::setprecision(12);
    for (const auto& event : events_) {
      events << "2,"
             << args_.run_id << ','
             << event.trace_id << ','
             << event.stream_id << ','
             << event.frame_id << ','
             << event.stage << ','
             << args_.role << ','
             << args_.host << ','
             << event.resource << ','
             << event.queue_enter_timestamp_ms << ','
             << event.stage_start_timestamp_ms << ','
             << event.stage_end_timestamp_ms << ','
             << event.queue_depth << ','
             << event.estimated_cost_ms << ','
             << event.policy_action << '\n';
    }
    events.close();

    if (policy_decisions_.empty()) {
      return;
    }
    std::sort(policy_decisions_.begin(), policy_decisions_.end(), [](const PolicyDecisionRecord& a,
                                                                    const PolicyDecisionRecord& b) {
      return a.decision.ordinal < b.decision.ordinal;
    });
    const fs::path policy_path = out_path.parent_path() / "policy_decisions.csv";
    std::ofstream policy(policy_path.string(), std::ios::out | std::ios::trunc);
    if (!policy.is_open()) {
      throw std::runtime_error("Failed to open output file: " + policy_path.string());
    }
    policy << "schema_version,run_id,trace_id,stream_id,frame_id,stage,policy,decision,resource,queue_depth,estimated_cost_ms,deadline_ms,policy_version,allowed_resources_json,alternative_scores_json,cost_components_json,parameters_json,tie_break_rule,decision_mode,update_seq,update_json,reason,decision_id,decision_seq,decision_timestamp_ms,graph_version,profile_version,feature_provenance_json,terminal_status,terminal_timestamp_ms,update_timestamp_ms,source_decision_ids_json,first_consumer_decision_id,first_consumer_decision_seq,causal_trace_completeness,decision_provenance,trace_completeness,telemetry_source\n";
    for (const auto& record : policy_decisions_) {
      const DecisionSnapshot& decision = record.decision;
      const std::string resource = resource_name(decision.resource);
      const bool causal_complete = decision.decision_id != "unavailable" &&
                                   decision.decision_seq > 0 &&
                                   decision.decision_timestamp_ms > 0.0 &&
                                   decision.terminal_status == "completed" &&
                                   decision.terminal_timestamp_ms >= decision.decision_timestamp_ms;
      write_csv_row(
          policy,
          {
              "2",
              args_.run_id,
              record.trace_id,
              std::to_string(record.stream_id),
              std::to_string(record.frame_id),
              record.stage,
              args_.policy,
              args_.policy + ":" + resource,
              resource,
              std::to_string(decision.queue_depth),
              vast_policy_trace::json_number(decision.selected_score_ms),
              vast_policy_trace::json_number(args_.deadline_ms),
              decision.policy_version,
              decision.allowed_resources_json,
              decision.alternative_scores_json,
              decision.cost_components_json,
              decision.parameters_json,
              decision.tie_break_rule,
              "applied",
              std::to_string(decision.update_seq),
              decision.update_json,
              decision.reason,
              decision.decision_id,
              std::to_string(decision.decision_seq),
              vast_policy_trace::json_number(decision.decision_timestamp_ms),
              decision.graph_version,
              decision.profile_version,
              decision.feature_provenance_json,
              decision.terminal_status,
              vast_policy_trace::json_number(decision.terminal_timestamp_ms),
              vast_policy_trace::json_number(decision.update_timestamp_ms),
              decision.source_decision_ids_json,
              decision.first_consumer_decision_id,
              std::to_string(decision.first_consumer_decision_seq),
              causal_complete ? "full" : "partial",
              "native_scheduler_trace",
              "full",
              "native",
          });
    }
    policy.close();

    if (args_.policy != "ql_heft_online") {
      return;
    }
    if (policy_feedback_.empty()) {
      throw std::runtime_error("Online policy completed without terminal feedback rows");
    }
    std::sort(policy_feedback_.begin(), policy_feedback_.end(), [](const PolicyFeedbackRecord& a,
                                                                   const PolicyFeedbackRecord& b) {
      return a.feedback_seq < b.feedback_seq;
    });
    const fs::path feedback_path = out_path.parent_path() / "policy_feedback.csv";
    std::ofstream feedback(feedback_path.string(), std::ios::out | std::ios::trunc);
    if (!feedback.is_open()) {
      throw std::runtime_error("Failed to open output file: " + feedback_path.string());
    }
    feedback << "schema_version,run_id,policy,feedback_seq,feedback_timestamp_ms,source_trace_id,terminal_status,terminal_timestamp_ms,source_decision_ids_json,source_parameter_snapshot_seq,parameter_lag,events_since_update,old_weights_json,raw_weights_json,projected_weights_json,weight_lower_bounds_json,weight_upper_bounds_json,projection_rule,variation_before,variation_after,variation_budget,feedback_features_json,feedback_action,reason,update_seq,first_consumer_decision_id,first_consumer_decision_seq,feedback_provenance,feedback_trace_completeness,telemetry_source\n";
    for (const auto& record : policy_feedback_) {
      write_csv_row(
          feedback,
          {
              "2",
              args_.run_id,
              args_.policy,
              std::to_string(record.feedback_seq),
              vast_policy_trace::json_number(record.feedback_timestamp_ms),
              record.source_trace_id,
              record.terminal_status,
              vast_policy_trace::json_number(record.terminal_timestamp_ms),
              record.source_decision_ids_json,
              std::to_string(record.source_parameter_snapshot_seq),
              std::to_string(record.parameter_lag),
              std::to_string(record.events_since_update),
              weights_json(record.old_weights),
              weights_json(record.raw_weights),
              weights_json(record.projected_weights),
              weights_json(weight_lower_bound_, weight_lower_bound_),
              weights_json(weight_upper_bound_, weight_upper_bound_),
              projection_rule_,
              vast_policy_trace::json_number(record.variation_before),
              vast_policy_trace::json_number(record.variation_after),
              vast_policy_trace::json_number(variation_budget_),
              record.feedback_features_json,
              record.feedback_action,
              record.reason,
              std::to_string(record.update_seq),
              record.first_consumer_decision_id,
              std::to_string(record.first_consumer_decision_seq),
              "native_terminal_feedback",
              "full",
              "native",
          });
    }
  }
};

bool parse_args(int argc, char** argv, Args& args) {
  for (int i = 1; i < argc; ++i) {
    const std::string key = argv[i];
    const auto need_value = [&](const char* name) -> bool {
      if (i + 1 >= argc) {
        std::cerr << "Missing value for " << name << "\n";
        return false;
      }
      return true;
    };

    if (key == "--scenario" && need_value("--scenario")) {
      args.scenario = argv[++i];
    } else if (key == "--streams" && need_value("--streams")) {
      args.streams = std::stoi(argv[++i]);
    } else if (key == "--duration" && need_value("--duration")) {
      args.duration = std::stoi(argv[++i]);
    } else if (key == "--output" && need_value("--output")) {
      args.output = argv[++i];
    } else if (key == "--seed" && need_value("--seed")) {
      args.seed = static_cast<std::uint32_t>(std::stoul(argv[++i]));
      args.has_seed = true;
    } else if (key == "--min-objects" && need_value("--min-objects")) {
      args.min_objects = std::stoi(argv[++i]);
    } else if (key == "--max-objects" && need_value("--max-objects")) {
      args.max_objects = std::stoi(argv[++i]);
    } else if (key == "--deadline-ms" && need_value("--deadline-ms")) {
      args.deadline_ms = std::stod(argv[++i]);
    } else if (key == "--fps" && need_value("--fps")) {
      args.source_fps = std::stod(argv[++i]);
    } else if (key == "--policy" && need_value("--policy")) {
      args.policy = argv[++i];
    } else if (key == "--policy-artifact" && need_value("--policy-artifact")) {
      args.policy_artifact = argv[++i];
    } else if (key == "--run-id" && need_value("--run-id")) {
      args.run_id = argv[++i];
    } else if (key == "--detector" && need_value("--detector")) {
      args.detector = argv[++i];
    } else if (key == "--backend" && need_value("--backend")) {
      args.backend = argv[++i];
    } else {
      std::cerr << "Unknown or incomplete arg: " << key << "\n";
      return false;
    }
  }
  return true;
}

int main(int argc, char** argv) {
  try {
    Args args;
    if (!parse_args(argc, argv, args)) {
      return 2;
    }

    const char* env_seed = std::getenv("EXPERIMENT_RUN_SEED");
    if (!args.has_seed && env_seed) {
      try {
        args.seed = static_cast<std::uint32_t>(std::stoul(env_seed));
        args.has_seed = true;
      } catch (...) {
      }
    }
    if (const char* env_role = std::getenv("EXPERIMENT_HOST_ROLE")) {
      args.role = env_role;
    }
    if (const char* env_host = std::getenv("HOSTNAME")) {
      args.host = env_host;
    }

    if (args.streams < 1) {
      args.streams = 1;
    }
    if (args.duration < 1) {
      args.duration = 1;
    }
    if (args.source_fps <= 0.0) {
      args.source_fps = 30.0;
    }

    if (qEnvironmentVariableIsEmpty("QT_QPA_PLATFORM")) {
      qputenv("QT_QPA_PLATFORM", "offscreen");
    }
    QApplication app(argc, argv);
    QWidget dashboard;
    dashboard.setWindowTitle("VAST CUDA Scheduler");
    auto* layout = new QVBoxLayout(&dashboard);
    auto* status = new QLabel("Starting scheduler", &dashboard);
    layout->addWidget(status);
    dashboard.show();

    AdaptivePipeline pipeline(std::move(args));
    std::string failure;
    int pipeline_rc = 0;
    std::thread worker([&] {
      try {
        pipeline_rc = pipeline.run();
      } catch (const std::exception& ex) {
        failure = ex.what();
        pipeline_rc = 1;
      }
      QMetaObject::invokeMethod(&app, "quit", Qt::QueuedConnection);
    });
    QTimer timer;
    QObject::connect(&timer, &QTimer::timeout, [&] {
      status->setText(QString("Completed frames: %1").arg(pipeline.completed_frames()));
    });
    timer.start(200);
    (void)app.exec();
    worker.join();
    if (!failure.empty()) {
      throw std::runtime_error(failure);
    }
    return pipeline_rc;
  } catch (const std::exception& ex) {
    std::cerr << "[error] " << ex.what() << "\n";
    return 1;
  }
}
