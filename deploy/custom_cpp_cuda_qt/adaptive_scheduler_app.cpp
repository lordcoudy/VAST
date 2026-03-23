#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <random>
#include <string>

namespace fs = std::filesystem;

struct Args {
  std::string scenario = "baseline";
  int streams = 6;
  int duration = 30;
  std::string output_dir = ".";
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

  fs::create_directories(args.output_dir);
  fs::path out = fs::path(args.output_dir) / "frames.csv";
  std::ofstream f(out);
  if (!f.is_open()) {
    std::cerr << "Failed to open output: " << out << "\n";
    return 1;
  }

  f << "timestamp_ms,frame_id,stream_id,objects,latency_ms,fps_instant,slo_violation\n";

  const int fps_base = 30;
  const int total_frames = std::max(1, args.duration * fps_base * args.streams);
  const double latency_base = 130.0;

  std::mt19937 rng(14700);
  std::uniform_int_distribution<int> obj_dist(0, 40);
  std::uniform_real_distribution<double> jitter(0.93, 1.09);

  auto now_ms = []() -> long long {
    return std::chrono::duration_cast<std::chrono::milliseconds>(
               std::chrono::system_clock::now().time_since_epoch())
        .count();
  };

  const long long start = now_ms();

  for (int i = 0; i < total_frames; ++i) {
    int stream_id = i % std::max(1, args.streams);
    int objects = obj_dist(rng);

    double load = 1.0 + static_cast<double>(objects) / 50.0;
    double fps = (fps_base / load) * jitter(rng);
    if (fps < 3.0) fps = 3.0;
    if (fps > 35.0) fps = 35.0;

    double latency = latency_base * load * jitter(rng);
    if (args.scenario == "dynamic_workload" && (i % 97 == 0)) {
      latency *= 3.0;
    }

    int slo = latency > 3000.0 ? 1 : 0;
    long long ts = start + static_cast<long long>((1000.0 * i) / (fps_base * std::max(1, args.streams)));

    f << ts << ',' << i << ',' << stream_id << ',' << objects << ',' << latency << ',' << fps << ',' << slo << "\n";
  }

  std::cout << "Wrote synthetic custom-app frames to " << out << "\n";
  return 0;
}
