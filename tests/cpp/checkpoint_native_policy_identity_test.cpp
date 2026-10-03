#define main vast_native_gst_probe_embedded_main
#include "../../deploy/native_gst_probe/vast_native_gst_probe.cpp"
#undef main

#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {

const std::string kSha(64, 'a');

void expect(bool condition, const std::string& message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

void set_identity(const char* resource, const char* branch, const char* implementation,
                  const char* emitter, const char* emitter_sha) {
  const std::string suffix = std::string("_") + branch;
  const std::string base = std::string("VAST_CHECKPOINT_ANALYTICS_") + resource + "_";
  const auto put = [](const std::string& name, const char* value) {
    if (value == nullptr) {
      ::unsetenv(name.c_str());
    } else if (::setenv(name.c_str(), value, 1) != 0) {
      throw std::runtime_error("setenv failed");
    }
  };
  put(base + "IMPLEMENTATION_ID" + suffix, implementation);
  put(base + "EMITTER_ID" + suffix, emitter);
  put(base + "EMITTER_SHA256" + suffix, emitter_sha);
}

void expect_rejected(const char* resource, const char* branch) {
  vast::CheckpointNativeExecutionBinding binding;
  bool rejected = false;
  try {
    checkpoint_injected_policy_identity(branch, resource[0] == 'C' ? "cpu" : "gpu", binding);
  } catch (const std::exception& error) {
    rejected = std::string(error.what()).find("no exact native policy identity") != std::string::npos;
  }
  expect(rejected, std::string("malformed injected identity was accepted for ") + resource);
}

}  // namespace

int main() {
  try {
    vast::CheckpointNativeExecutionBinding binding;
    set_identity("CPU", "damage", nullptr, nullptr, nullptr);
    expect(!checkpoint_injected_policy_identity("damage", "cpu", binding),
           "absent identity must fall back to the legacy derivation");

    // The frozen qualification-v2 manifest identities bind exactly, for the
    // six-byte "damage" branch and for both resources.
    set_identity("CPU", "damage", "openvino_gva-qualification-authority-v2:damage:cpu:abc",
                 "openvino_gva-native-policy-emitter-v2:damage:cpu:abc", kSha.c_str());
    expect(checkpoint_injected_policy_identity("damage", "cpu", binding),
           "injected CPU identity was ignored");
    expect(binding.resource == "cpu" &&
               binding.implementation_id == "openvino_gva-qualification-authority-v2:damage:cpu:abc" &&
               binding.emitter_id == "openvino_gva-native-policy-emitter-v2:damage:cpu:abc" &&
               binding.emitter_sha256 == kSha,
           "injected CPU identity changed");
    set_identity("GPU", "vehicle_type", "gstreamer_custom-qualification-authority-v2:vehicle_type:gpu:def",
                 "gstreamer_custom-native-policy-emitter-v2:vehicle_type:gpu:def", kSha.c_str());
    expect(checkpoint_injected_policy_identity("vehicle_type", "gpu", binding) &&
               binding.resource == "gpu" &&
               binding.implementation_id ==
                   "gstreamer_custom-qualification-authority-v2:vehicle_type:gpu:def",
           "injected GPU identity changed");

    // Partial, control-bearing or non-SHA identities fail closed.
    set_identity("CPU", "damage", "openvino_gva-qualification-authority-v2:damage:cpu:abc",
                 nullptr, kSha.c_str());
    expect_rejected("CPU", "damage");
    set_identity("CPU", "damage", "openvino_gva-qualification authority", "emitter-id-0001",
                 kSha.c_str());
    expect_rejected("CPU", "damage");
    set_identity("GPU", "vehicle_type", "implementation-0001", "emitter-id-0001",
                 std::string(64, 'A').c_str());
    expect_rejected("GPU", "vehicle_type");
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
