#define main vast_native_gst_probe_embedded_main
#include "../../deploy/native_gst_probe/vast_native_gst_probe.cpp"
#undef main

#include <iostream>
#include <stdexcept>
#include <string>

namespace {

void expect(bool condition, const std::string& message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

// Every decode-stage artifact must name a loaded GStreamer factory; a label
// such as the explicit hardware-decoder autoplugger cannot be resolved.
void test_decode_artifacts_are_resolvable_factories() {
  const auto factories = checkpoint_decode_artifact_factories("identity");
  expect(factories.size() == 2, "decode stage artifact set changed");
  for (const auto& [role, factory_name] : factories) {
    expect(role != "autoplugger", "autoplugger label is resolved as a plugin artifact");
    GstElementFactory* factory = gst_element_factory_find(factory_name.c_str());
    expect(factory != nullptr, "decode stage artifact is not a loaded factory: " + factory_name);
    gst_object_unref(factory);
  }
  expect(factories[0] == std::make_pair(std::string("decoder"), std::string("identity")),
         "decode stage does not bind the observed decoder factory");
  expect(gst_element_factory_find("explicit_hardware_decoder") == nullptr,
         "fixture assumption changed: the autoplugger label resolved as a factory");
}

}  // namespace

int main(int argc, char** argv) {
  try {
    g_log_set_always_fatal(
        static_cast<GLogLevelFlags>(G_LOG_LEVEL_WARNING | G_LOG_LEVEL_CRITICAL));
    gst_init(&argc, &argv);
    test_decode_artifacts_are_resolvable_factories();
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
