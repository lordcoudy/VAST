// Real CUDA-backed adaptive scheduler for the custom_cpp_cuda_qt benchmark.

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdint>
#include <cstdlib>
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

struct Task {
  int frame_id = 0;
  int stream_id = 0;
  int stage_index = 0;
  int objects = 0;
  double aggregate = 0.0;
  std::array<float, kSignalWidth> signal{};
  std::chrono::steady_clock::time_point created_at;
  std::chrono::steady_clock::time_point queue_enter_at;
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

  static StageSpec stage_spec_for_name(const std::string& name) {
    if (name == "decode") return {"decode", Resource::Gpu, 0.95f, 1.05f, 0.08f};
    if (name == "detect") return {"detect", Resource::Gpu, 1.05f, 1.35f, 0.22f};
    if (name == "track") return {"track", Resource::Cpu, 1.25f, 0.85f, 0.16f};
    if (name == "classify") return {"classify", Resource::Cpu, 1.05f, 0.70f, 0.11f};
    if (name == "aggregate") return {"aggregate", Resource::Cpu, 0.88f, 0.62f, 0.05f};
    if (name == "record") return {"record", Resource::Cpu, 0.82f, 0.55f, 0.04f};
    if (name == "visualize") return {"visualize", Resource::Cpu, 0.90f, 0.65f, 0.06f};
    return {name, Resource::Cpu, 1.00f, 0.70f, 0.05f};
  }

  void load_policy_artifact() {
    if (args_.policy != "ql_heft_frozen" && args_.policy != "ql_heft_online") {
      return;
    }
    std::ifstream input(args_.policy_artifact);
    if (!input.is_open()) {
      throw std::runtime_error("QL-HEFT policy artifact is missing: " + args_.policy_artifact);
    }
    std::string line;
    while (std::getline(input, line)) {
      const auto pos = line.find('=');
      if (pos == std::string::npos) continue;
      const std::string key = line.substr(0, pos);
      const std::string value = line.substr(pos + 1);
      if (key == "cpu_queue_weight") cpu_queue_weight_.store(std::stod(value));
      if (key == "gpu_queue_weight") gpu_queue_weight_.store(std::stod(value));
      if (key == "heavy_gpu_bonus") heavy_gpu_bonus_.store(std::stod(value));
      if (key == "heavy_object_threshold") heavy_object_threshold_ = std::stoi(value);
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
    if (args_.policy == "ql_heft_frozen" || args_.policy == "ql_heft_online") {
      const double cpu_cost = static_cast<double>(cpu_backlog + 1) * stage.cpu_gain * cpu_queue_weight_.load();
      double gpu_cost = static_cast<double>(gpu_backlog + 1) * stage.gpu_gain * gpu_queue_weight_.load();
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
    const auto latency_ms =
        std::chrono::duration_cast<std::chrono::microseconds>(completed_at - task.created_at).count() / 1000.0;
    FrameRecord row;
    row.trace_id = args_.run_id + ":" + std::to_string(task.stream_id) + ":" + std::to_string(task.frame_id);
    row.frame_id = task.frame_id;
    row.stream_id = task.stream_id;
    row.objects = task.objects;
    row.ingress_timestamp_ms = telemetry_timestamp_ms(task.created_at);
    row.egress_timestamp_ms = telemetry_timestamp_ms(completed_at);
    row.latency_ms = latency_ms;

    {
      std::lock_guard<std::mutex> lock(rows_mutex_);
      rows_.push_back(row);
    }
    if (args_.policy == "ql_heft_online") {
      const double direction = latency_ms > args_.deadline_ms ? -0.002 : 0.0002;
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
    const Resource resource = choose_resource(task.stage_index, task);
    if (resource == Resource::Cpu) {
      cpu_queue_.push(std::move(task));
    } else {
      gpu_queue_.push(std::move(task));
    }
  }

  void process_task(Task task, Resource resource, GpuExecutor* gpu_executor) {
    const StageSpec& stage = stages_[static_cast<std::size_t>(task.stage_index)];
    const auto stage_start = std::chrono::steady_clock::now();
    const std::size_t queue_depth = resource == Resource::Cpu ? cpu_queue_.size() : gpu_queue_.size();
    const double predicted_ms = estimated_cost_ms(resource, stage, task);
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
    events << std::fixed << std::setprecision(6);
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
