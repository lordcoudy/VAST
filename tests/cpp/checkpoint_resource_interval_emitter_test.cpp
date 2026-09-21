#include "checkpoint_resource_interval_emitter.hpp"

#include <exception>
#include <fstream>
#include <iostream>
#include <string>

int main(int argc, char** argv) {
  if (argc != 3) {
    std::cerr << "expected interval and fanout-work output paths\n";
    return 2;
  }
  try {
    const std::uint64_t unclamped_submillisecond_end =
        vast::CheckpointResourceIntervalEmitter::canonical_interval_end_ns(
            1'000'000'001,
            1'000'000'321,
            1000,
            1000);
    if (unclamped_submillisecond_end != 1'000'000'321) {
      std::cerr << "unclamped sub-millisecond endpoint lost precision\n";
      return 5;
    }
    const std::uint64_t causally_serialized_end =
        vast::CheckpointResourceIntervalEmitter::canonical_interval_end_ns(
            999'900'000,
            999'950'000,
            999,
            1002);
    if (causally_serialized_end != 1'002'000'000) {
      std::cerr << "clamped topology timestamp was not shared with fanout interval\n";
      return 6;
    }
    vast::CheckpointResourceIntervalEmitter emitter(argv[1]);
    vast::CheckpointFanoutWorkCounterEmitter work_emitter(argv[2]);
    emitter.emit_fanout(
        "run-1",
        "run-1:3:7",
        3,
        7,
        "kpp_real_h264:3:source:0:90000",
        "damage",
        "run-1:3:7:damage:fanout",
        1'000'000'001,
        1'000'000'321,
        691'200,
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef");
    work_emitter.emit(
        "run-1",
        "run-1:3:7",
        3,
        7,
        "kpp_real_h264:3:source:0:90000",
        "damage",
        "run-1:3:7:damage:fanout",
        25'000,
        1);
    try {
      emitter.emit_fanout(
          "run-1",
          "run-1:3:8",
          3,
          8,
          "kpp_real_h264:3:source:0:93000",
          "damage",
          "run-1:3:8:damage:fanout",
          2'000,
          2'000,
          1,
          "1123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef");
      std::cerr << "zero-width interval was accepted\n";
      return 3;
    } catch (const std::exception&) {
    }
  } catch (const std::exception& exc) {
    std::cerr << exc.what() << '\n';
    return 1;
  }
  return 0;
}
