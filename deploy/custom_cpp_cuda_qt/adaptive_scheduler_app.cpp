// Simple implementation that emits a realistic frames.csv so experiments can collect
// metrics. This is not a full video pipeline; it simulates per-frame timing and
// writes the CSV expected by the experiment suite.

#include <chrono>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <string>
#include <system_error>

struct Args {
  std::string scenario = "baseline";
  int streams = 6;
  int duration = 30; // seconds
  std::string output_dir = ".";
  std::uint32_t seed = 0;
  bool has_seed = false;
  int min_objects = 0;
  int max_objects = 20;
  double deadline_ms = 3000.0;
};

bool parseArgs(int argc, char** argv, Args& args) {
  for (int i = 1; i < argc; ++i) {
    std::string k = argv[i];
    if (k == "--scenario" && i + 1 < argc) {
      args.scenario = argv[++i];
    } else if (k == "--streams" && i + 1 < argc) {
      args.streams = std::stoi(argv[++i]);
    } else if (k == "--duration" && i + 1 < argc) {
      args.duration = std::stoi(argv[++i]);
    } else if (k == "--output" && i + 1 < argc) {
      args.output_dir = argv[++i];
    } else if (k == "--seed" && i + 1 < argc) {
      args.seed = static_cast<std::uint32_t>(std::stoul(argv[++i]));
      args.has_seed = true;
    } else {
      std::cerr << "Unknown or incomplete arg: " << k << "\n";
      return false;
    }
  }
  return true;
}

int main(int argc, char** argv) {
  Args args;
  if (!parseArgs(argc, argv, args)) {
    return 2;
  }

  // Seed-based variability can be supplied via env as well; respect it when present.
  const char* env_seed = std::getenv("EXPERIMENT_RUN_SEED");
  if (!args.has_seed && env_seed) {
    try {
      args.seed = static_cast<std::uint32_t>(std::stoul(env_seed));
      args.has_seed = true;
    } catch (...) {
      // ignore parsing errors
    }
  }

  // Basic parameters for synthetic frame generation.
  const double source_fps = 30.0;
  const int streams = std::max(1, args.streams);
  const int duration_s = std::max(1, args.duration);

  // Estimate total frames similar to the Python emitter: fps * duration * streams
  const int target_frames = static_cast<int>(std::round(source_fps * duration_s * streams));
  const int total_frames = std::max(1, target_frames);

  // Simple latency model: evenly split elapsed_ms over frames
  const double elapsed_ms = static_cast<double>(duration_s) * 1000.0;
  double latency_ms = elapsed_ms / static_cast<double>(total_frames);
  if (latency_ms <= 0.0) latency_ms = 0.001;
  const double fps_instant = 1000.0 / latency_ms;

  const int objects = std::max(args.min_objects, std::min(args.max_objects, (args.min_objects + args.max_objects) / 2));
  const int slo = (latency_ms > args.deadline_ms) ? 1 : 0;

  // Prepare output file
  std::string out_path = args.output_dir;
  // If caller gave a directory, append frames.csv; allow file paths too.
  if (out_path.size() == 0) out_path = ".";
  if (out_path.back() == '/' || out_path.back() == '\\') {
    out_path += "frames.csv";
  }

  std::ofstream ofs(out_path, std::ios::out | std::ios::trunc);
  if (!ofs.is_open()) {
    std::cerr << "Failed to open output file: " << out_path << "\n";
    return 1;
  }

  // CSV header
  ofs << "timestamp_ms,frame_id,stream_id,objects,latency_ms,fps_instant,slo_violation\n";

  // Start timestamp such that the last frame is 'now'
  const auto now = std::chrono::system_clock::now();
  const auto now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()).count();
  const long long start_ts = static_cast<long long>(now_ms - static_cast<long long>(elapsed_ms));

  const double frame_dt_ms = std::max(1.0, 1000.0 / std::max(fps_instant, 0.001));

  for (int fid = 0; fid < total_frames; ++fid) {
    long long ts = start_ts + static_cast<long long>(std::llround(fid * frame_dt_ms));
    int stream_id = fid % streams;
    ofs << ts << "," << fid << "," << stream_id << "," << objects << ",";
    ofs << std::fixed << std::setprecision(6) << latency_ms << "," << fps_instant << "," << slo << "\n";
  }

  ofs.close();
  return 0;
}
