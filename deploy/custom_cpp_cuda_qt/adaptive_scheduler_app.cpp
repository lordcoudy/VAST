// Adaptive custom pipeline prototype used by the experiment harness.
// It models a multi-stage CPU/GPU scheduler and emits frames.csv directly.

#include <algorithm>
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
#include <string>
#include <thread>
#include <utility>
#include <vector>

namespace fs = std::filesystem;

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
  double cpu_ms;
  double gpu_ms;
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
    start_workers();
    start_producers();
    wait_for_completion();
    close_workers();
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
  std::uint32_t seed_value_ = 0;

  void init_stages() {
    stages_ = {
        {"decode", Resource::Gpu, 2.2, 1.0},
        {"detect", Resource::Gpu, 11.0, 4.5},
        {"track", Resource::Cpu, 3.5, 2.4},
        {"classify", Resource::Cpu, 2.8, 1.6},
        {"visualize", Resource::Cpu, 2.0, 1.2},
    };
  }

  static int clamp_int(int v, int lo, int hi) {
    return std::max(lo, std::min(hi, v));
  }

  int object_count_for_frame(int frame_id, int stream_id) {
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

  Resource choose_resource(int stage_index, const Task& task) {
    const StageSpec& stage = stages_[static_cast<std::size_t>(stage_index)];
    const std::size_t cpu_backlog = cpu_queue_.size() + static_cast<std::size_t>(active_cpu_.load());
    const std::size_t gpu_backlog = gpu_queue_.size() + static_cast<std::size_t>(active_gpu_.load());
    const bool detect_heavy = task.objects > ((std::min(args_.min_objects, args_.max_objects) + std::max(args_.min_objects, args_.max_objects)) / 2);

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

  double stage_target_ms(Resource resource, int stage_index, const Task& task) const {
    const StageSpec& stage = stages_[static_cast<std::size_t>(stage_index)];
    const double object_bias = static_cast<double>(task.objects) * (stage_index == 1 ? 0.18 : stage_index == 2 ? 0.08 : 0.05);
    const double stream_bias = static_cast<double>(task.stream_id % 3) * 0.12;
    const double base = resource == Resource::Gpu ? stage.gpu_ms : stage.cpu_ms;
    const double scenario_bias = args_.scenario == "complex_pipeline" ? 1.4 : args_.scenario == "dynamic_workload" ? 0.8 : 0.0;
    return std::max(0.25, base + object_bias + stream_bias + scenario_bias);
  }

  void burn_for_ms(double ms, Resource resource, int frame_id) {
    const double busy_ratio = resource == Resource::Cpu ? 0.85 : 0.3;
    const auto busy_target = std::chrono::duration<double, std::milli>(ms * busy_ratio);
    const auto sleep_target = std::chrono::duration<double, std::milli>(ms * (1.0 - busy_ratio));
    const auto start = std::chrono::steady_clock::now();
    double x = static_cast<double>(frame_id + 1);

    while (std::chrono::steady_clock::now() - start < busy_target) {
      for (int i = 0; i < 256; ++i) {
        x = x * 1.000001 + static_cast<double>((frame_id % 7) + 1) * 0.00001;
        x = std::fmod(x, 100000.0);
      }
    }

    if (sleep_target.count() > 0.0) {
      std::this_thread::sleep_for(sleep_target);
    }

    volatile double sink = x;
    (void)sink;
  }

  void start_workers() {
    const unsigned hw = std::max(2u, std::thread::hardware_concurrency());
    const int cpu_workers = std::max(2, static_cast<int>(hw / 4));
    const int gpu_workers = 1;

    for (int i = 0; i < cpu_workers; ++i) {
      workers_.emplace_back([this] { worker_loop(Resource::Cpu); });
    }
    for (int i = 0; i < gpu_workers; ++i) {
      workers_.emplace_back([this] { worker_loop(Resource::Gpu); });
    }
  }

  void worker_loop(Resource resource) {
    BlockingQueue<Task>& queue = resource == Resource::Cpu ? cpu_queue_ : gpu_queue_;
    Task task;
    while (queue.pop(task)) {
      if (resource == Resource::Cpu) {
        ++active_cpu_;
      } else {
        ++active_gpu_;
      }

      const double target_ms = stage_target_ms(resource, task.stage_index, task);
      burn_for_ms(target_ms, resource, task.frame_id);

      if (resource == Resource::Cpu) {
        --active_cpu_;
      } else {
        --active_gpu_;
      }

      on_stage_complete(task);
    }
  }

  void on_stage_complete(Task task) {
    ++task.stage_index;
    if (task.stage_index < static_cast<int>(stages_.size())) {
      enqueue_stage(std::move(task));
      return;
    }

    const auto now = std::chrono::system_clock::now();
    const auto elapsed_ms = std::chrono::duration_cast<std::chrono::microseconds>(now - task.wall_created_at).count() / 1000.0;
    FrameRecord row;
    row.timestamp_ms = std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()).count();
    row.frame_id = task.frame_id;
    row.stream_id = task.stream_id;
    row.objects = task.objects;
    row.latency_ms = elapsed_ms;
    row.fps_instant = elapsed_ms > 0.0 ? 1000.0 / elapsed_ms : 0.0;
    row.slo_violation = elapsed_ms > args_.deadline_ms ? 1 : 0;

    {
      std::lock_guard<std::mutex> lock(rows_mutex_);
      rows_.push_back(row);
    }

    if (remaining_frames_.fetch_sub(1) == 1) {
      done_cv_.notify_one();
    }
  }

  void enqueue_stage(Task task) {
    const Resource resource = choose_resource(task.stage_index, task);
    if (resource == Resource::Cpu) {
      cpu_queue_.push(std::move(task));
    } else {
      gpu_queue_.push(std::move(task));
    }
  }

  void start_producers() {
    remaining_frames_.store(total_frames_);
    const auto start_tp = std::chrono::steady_clock::now();
    const auto interval = std::chrono::duration<double>(1.0 / std::max(1.0, args_.source_fps));

    for (int stream_id = 0; stream_id < stream_count_; ++stream_id) {
      producers_.emplace_back([=, this] {
        for (int frame_idx = 0; frame_idx < frames_per_stream_; ++frame_idx) {
          const auto due = start_tp + std::chrono::duration_cast<std::chrono::steady_clock::duration>(interval * frame_idx);
          std::this_thread::sleep_until(due);

          Task task;
          task.frame_id = stream_id * frames_per_stream_ + frame_idx;
          task.stream_id = stream_id;
          task.stage_index = 0;
          task.objects = object_count_for_frame(task.frame_id, stream_id);
          task.created_at = std::chrono::steady_clock::now();
          task.wall_created_at = std::chrono::system_clock::now();
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
    done_cv_.wait(lock, [&] { return remaining_frames_.load() == 0; });
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
      std::cerr << "Failed to open output file: " << out_path << "\n";
      std::exit(1);
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
}
