#define main vast_native_gst_probe_embedded_main
#include "../../deploy/native_gst_probe/vast_native_gst_probe.cpp"
#undef main

#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {

struct LevelElement {
  GstElement parent;
  guint64 level;
};

struct LevelElementClass {
  GstElementClass parent_class;
};

struct LevelSpec {
  GType value_type;
  GParamFlags flags;
};

void level_get_property(GObject* object, guint, GValue* value, GParamSpec* pspec) {
  const guint64 level = reinterpret_cast<LevelElement*>(object)->level;
  const GType type = G_PARAM_SPEC_VALUE_TYPE(pspec);
  if (type == G_TYPE_UINT64) {
    g_value_set_uint64(value, level);
  } else if (type == G_TYPE_UINT) {
    g_value_set_uint(value, static_cast<guint>(level));
  } else {
    g_value_set_int(value, static_cast<gint>(level));
  }
}

void level_set_property(GObject* object, guint, const GValue* value, GParamSpec*) {
  reinterpret_cast<LevelElement*>(object)->level = g_value_get_uint(value);
}

void level_class_init(gpointer klass, gpointer class_data) {
  const auto* spec = static_cast<const LevelSpec*>(class_data);
  GObjectClass* object_class = G_OBJECT_CLASS(klass);
  object_class->get_property = level_get_property;
  object_class->set_property = level_set_property;
  GParamSpec* property = nullptr;
  if (spec->value_type == G_TYPE_UINT64) {
    property = g_param_spec_uint64(
        "current-level-buffers", "level", "level", 0, G_MAXUINT64, 0, spec->flags);
  } else if (spec->value_type == G_TYPE_UINT) {
    property = g_param_spec_uint(
        "current-level-buffers", "level", "level", 0, G_MAXUINT, 0, spec->flags);
  } else {
    property = g_param_spec_int(
        "current-level-buffers", "level", "level", 0, G_MAXINT, 0, spec->flags);
  }
  g_object_class_install_property(object_class, 1, property);
}

GType register_level_element(const char* name, const LevelSpec* spec) {
  const GTypeInfo info = {
      sizeof(LevelElementClass), nullptr, nullptr, level_class_init, nullptr, spec,
      sizeof(LevelElement), 0, nullptr, nullptr};
  return g_type_register_static(GST_TYPE_ELEMENT, name, &info, static_cast<GTypeFlags>(0));
}

const LevelSpec kUint64Spec{G_TYPE_UINT64, G_PARAM_READABLE};
const LevelSpec kUintSpec{G_TYPE_UINT, G_PARAM_READABLE};
const LevelSpec kIntSpec{G_TYPE_INT, G_PARAM_READABLE};
const LevelSpec kWriteOnlySpec{G_TYPE_UINT, G_PARAM_WRITABLE};

void expect(bool condition, const std::string& message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

GstElement* make_level_element(GType type, guint64 level) {
  GstElement* element = GST_ELEMENT(g_object_new(type, nullptr));
  reinterpret_cast<LevelElement*>(element)->level = level;
  return element;
}

GstElement* bin_with(GstElement* first, GstElement* second = nullptr) {
  GstElement* bin = gst_bin_new(nullptr);
  gst_bin_add(GST_BIN(bin), first);
  if (second != nullptr) {
    gst_bin_add(GST_BIN(bin), second);
  }
  return bin;
}

GType property_type(GstElement* element) {
  GParamSpec* property =
      g_object_class_find_property(G_OBJECT_GET_CLASS(element), "current-level-buffers");
  expect(property != nullptr, "fixture element lacks current-level-buffers");
  return G_PARAM_SPEC_VALUE_TYPE(property);
}

void expect_verify_rejects(GstElement* bin, const char* expected) {
  bool rejected = false;
  try {
    verify_pipeline_queues_empty(bin);
  } catch (const std::exception& error) {
    rejected = std::string(error.what()).find(expected) != std::string::npos;
  }
  gst_object_unref(bin);
  expect(rejected, std::string("queue verification did not reject: ") + expected);
}

void test_real_elements_use_their_declared_widths() {
  GError* error = nullptr;
  GstElement* pipeline =
      gst_parse_launch("appsrc name=src ! queue name=q ! fakesink", &error);
  expect(pipeline != nullptr && error == nullptr, "failed to build appsrc/queue pipeline");
  GstElement* appsrc = gst_bin_get_by_name(GST_BIN(pipeline), "src");
  GstElement* queue = gst_bin_get_by_name(GST_BIN(pipeline), "q");
  expect(property_type(appsrc) == G_TYPE_UINT64, "appsrc level is expected to be guint64");
  expect(property_type(queue) == G_TYPE_UINT, "queue level is expected to be guint");
  std::uint64_t level = 99;
  expect(read_current_level_buffers(appsrc, level) && level == 0, "appsrc level is not zero");
  level = 99;
  expect(read_current_level_buffers(queue, level) && level == 0, "queue level is not zero");
  gst_object_unref(appsrc);
  gst_object_unref(queue);
  expect(verify_pipeline_queues_empty(pipeline) == 2, "reset path did not observe both queues");
  gst_object_unref(pipeline);

  GstElement* unobservable = gst_parse_launch("fakesrc ! fakesink", &error);
  expect(unobservable != nullptr && error == nullptr, "failed to build queue-free pipeline");
  expect(verify_pipeline_queues_empty(unobservable) == 0, "queue-free pipeline reported queues");
  gst_object_unref(unobservable);
}

void test_wide_level_is_read_without_truncation(GType uint64_type) {
  const guint64 wide = (G_GUINT64_CONSTANT(1) << 32) + 5;
  GstElement* element = make_level_element(uint64_type, wide);
  gst_object_ref_sink(element);
  std::uint64_t level = 0;
  expect(read_current_level_buffers(element, level) && level == wide,
         "guint64 level was truncated");
  gst_object_unref(element);

  // A 32-bit read of 2^32 yields zero; the reset check must still reject it.
  expect_verify_rejects(
      bin_with(make_level_element(uint64_type, G_GUINT64_CONSTANT(1) << 32)),
      "checkpoint queue is not empty before READY");
}

void test_mixed_empty_queues_pass_and_nonempty_queue_rejects(GType uint64_type, GType uint_type) {
  GstElement* empty = bin_with(make_level_element(uint64_type, 0), make_level_element(uint_type, 0));
  expect(verify_pipeline_queues_empty(empty) == 2, "empty mixed-width queues were not counted");
  gst_object_unref(empty);

  expect_verify_rejects(
      bin_with(make_level_element(uint64_type, 0), make_level_element(uint_type, 3)),
      "checkpoint queue is not empty before READY");
}

void test_unsupported_or_unreadable_level_fails_explicitly(GType int_type, GType write_only_type) {
  expect_verify_rejects(
      bin_with(make_level_element(int_type, 0)),
      "checkpoint queue level property has an unsupported type");
  expect_verify_rejects(
      bin_with(make_level_element(write_only_type, 0)),
      "checkpoint queue level property is not readable");
}

}  // namespace

int main(int argc, char** argv) {
  try {
    g_log_set_always_fatal(
        static_cast<GLogLevelFlags>(G_LOG_LEVEL_WARNING | G_LOG_LEVEL_CRITICAL));
    gst_init(&argc, &argv);
    const GType uint64_type = register_level_element("VastTestLevelUint64", &kUint64Spec);
    const GType uint_type = register_level_element("VastTestLevelUint", &kUintSpec);
    const GType int_type = register_level_element("VastTestLevelInt", &kIntSpec);
    const GType write_only_type = register_level_element("VastTestLevelWriteOnly", &kWriteOnlySpec);

    test_real_elements_use_their_declared_widths();
    test_wide_level_is_read_without_truncation(uint64_type);
    test_mixed_empty_queues_pass_and_nonempty_queue_rejects(uint64_type, uint_type);
    test_unsupported_or_unreadable_level_fails_explicitly(int_type, write_only_type);
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
