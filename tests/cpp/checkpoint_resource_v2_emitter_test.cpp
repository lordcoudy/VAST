#include "checkpoint_resource_interval_emitter.hpp"

#include <exception>
#include <iostream>

int main(int argc, char** argv) {
  if (argc != 2) {
    std::cerr << "expected resource-interval output path\n";
    return 2;
  }
  try {
    vast::CheckpointResourceIntervalEmitter emitter(argv[1]);
    emitter.emit_nvdec_submit_complete(
        "run-1",
        "run-1:3:7",
        3,
        7,
        "kpp_real_h265:3:source:0:90000",
        "shared",
        "run-1:3:7:shared:decode",
        1'000'000'001,
        1'000'000'321,
        42'000,
        "nvdec:0",
        "1123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef");
    emitter.emit_fanout(
        "run-1",
        "run-1:3:7",
        3,
        7,
        "kpp_real_h265:3:source:0:90000",
        "damage",
        "run-1:3:7:damage:fanout",
        1'000'000'401,
        1'000'000'721,
        691'200,
        "2123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef");
  } catch (const std::exception& exc) {
    std::cerr << exc.what() << '\n';
    return 1;
  }
  return 0;
}
