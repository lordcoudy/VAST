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
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

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
};

enum class Resource { Cpu, Gpu };

struct FrameRecord {
  long long timestamp_ms = 0;
  int frame_id = 0;
  int stream_id = 0;
  int objects = 0;
  double latency_ms = 0.0;
  double fps_instant = 0.0;
  int slo_violation = 0;
};

struct Task {
  int frame_id = 0;
  int stream_id = 0;
  int stage_index = 0;
  int objects = 0;
  double aggregate = 0.0;
  std::array<float, kSignalWidth> signal{};
  std::chrono::steady_clock::time_point created_at;
  std::chrono::system_clock::time_point wall_created_at;
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
  const char* name;
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
    init_stages();
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
  std::mutex done_mutex_;
  std::condition_variable done_cv_;
  std::atomic<int> remaining_frames_{0};
  std::atomic<int> active_cpu_{0};
  std::atomic<int> active_gpu_{0};
  std::atomic<bool> stop_requested_{false};
  std::mutex failure_mutex_;
  std::string failure_message_;
  std::uint32_t seed_value_ = 0;

  void init_stages() {
    stages_ = {
        {"decode", Resource::Gpu, 0.95f, 1.05f, 0.08f},
        {"detect", Resource::Gpu, 1.05f, 1.35f, 0.22f},
        {"track", Resource::Cpu, 1.25f, 0.85f, 0.16f},
        {"classify", Resource::Cpu, 1.05f, 0.70f, 0.11f},
        {"visualize", Resource::Cpu, 0.90f, 0.65f, 0.06f},
    };
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
    const auto now = std::chrono::system_clock::now();
    const auto latency_ms =
        std::chrono::duration_cast<std::chrono::microseconds>(now - task.wall_created_at).count() / 1000.0;
    FrameRecord row;
    row.timestamp_ms = std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()).count();
    row.frame_id = task.frame_id;
    row.stream_id = task.stream_id;
    row.objects = task.objects;
    row.latency_ms = latency_ms;
    row.fps_instant = latency_ms > 0.0 ? 1000.0 / latency_ms : 0.0;
    row.slo_violation = latency_ms > args_.deadline_ms ? 1 : 0;

    {
      std::lock_guard<std::mutex> lock(rows_mutex_);
      rows_.push_back(row);
    }

    if (remaining_frames_.fetch_sub(1) == 1) {
      done_cv_.notify_one();
    }
  }

  void enqueue_stage(Task task) {
    if (stop_requested_.load()) {
      return;
    }

    const Resource resource = choose_resource(task.stage_index, task);
    if (resource == Resource::Cpu) {
      cpu_queue_.push(std::move(task));
    } else {
      gpu_queue_.push(std::move(task));
    }
  }

  void process_task(Task task, Resource resource, GpuExecutor* gpu_executor) {
    const StageSpec& stage = stages_[static_cast<std::size_t>(task.stage_index)];
    if (resource == Resource::Cpu) {
      (void)cpu_stage_step(task, stage);
    } else {
      if (gpu_executor == nullptr) {
        throw std::runtime_error("GPU executor unavailable");
      }
      (void)gpu_stage_step(task, stage, *gpu_executor);
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
      producers_.emplace_back([=, this] {
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
          task.frame_id = stream_id * frames_per_stream_ + frame_idx;
          task.stream_id = stream_id;
          task.stage_index = 0;
          task.objects = object_count_for_frame(task.frame_id, stream_id);
          task.created_at = std::chrono::steady_clock::now();
          task.wall_created_at = std::chrono::system_clock::now();
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
      if (a.timestamp_ms != b.timestamp_ms) return a.timestamp_ms < b.timestamp_ms;
      return a.frame_id < b.frame_id;
    });

    ofs << "timestamp_ms,frame_id,stream_id,objects,latency_ms,fps_instant,slo_violation\n";
    ofs << std::fixed << std::setprecision(6);
    for (const auto& row : rows_) {
      ofs << row.timestamp_ms << ','
          << row.frame_id << ','
          << row.stream_id << ','
          << row.objects << ','
          << row.latency_ms << ','
          << row.fps_instant << ','
          << row.slo_violation << '\n';
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

    if (args.streams < 1) {
      args.streams = 1;
    }
    if (args.duration < 1) {
      args.duration = 1;
    }
    if (args.source_fps <= 0.0) {
      args.source_fps = 30.0;
    }

    AdaptivePipeline pipeline(std::move(args));
    return pipeline.run();
  } catch (const std::exception& ex) {
    std::cerr << "[error] " << ex.what() << "\n";
    return 1;
  }
}
