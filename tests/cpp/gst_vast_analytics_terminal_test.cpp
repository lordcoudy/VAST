#include <gst/base/gstbasetransform.h>
#include <gst/gst.h>
#include <gst/video/gstvideometa.h>

#include <cstdlib>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

#include <sys/socket.h>
#include <unistd.h>

#include "checkpoint_analytics_terminal_transport.hpp"

#define GST_TYPE_MOCK_GVA_DETECT (gst_mock_gva_detect_get_type())

typedef struct _GstMockGvaDetect GstMockGvaDetect;
typedef struct _GstMockGvaDetectClass GstMockGvaDetectClass;

struct _GstMockGvaDetect {
  GstBaseTransform parent;
  gchar* model;
};

struct _GstMockGvaDetectClass {
  GstBaseTransformClass parent_class;
};

G_DEFINE_TYPE(GstMockGvaDetect, gst_mock_gva_detect, GST_TYPE_BASE_TRANSFORM)

enum {
  PROP_0,
  PROP_MODEL,
  N_PROPERTIES,
};

static GParamSpec* properties[N_PROPERTIES] = {nullptr};

static GstStaticPadTemplate sink_template = GST_STATIC_PAD_TEMPLATE(
    "sink",
    GST_PAD_SINK,
    GST_PAD_ALWAYS,
    GST_STATIC_CAPS_ANY);

static GstStaticPadTemplate src_template = GST_STATIC_PAD_TEMPLATE(
    "src",
    GST_PAD_SRC,
    GST_PAD_ALWAYS,
    GST_STATIC_CAPS_ANY);

static void gst_mock_gva_detect_set_property(
    GObject* object,
    guint prop_id,
    const GValue* value,
    GParamSpec* pspec) {
  GstMockGvaDetect* self = reinterpret_cast<GstMockGvaDetect*>(object);
  if (prop_id != PROP_MODEL) {
    G_OBJECT_WARN_INVALID_PROPERTY_ID(object, prop_id, pspec);
    return;
  }
  g_free(self->model);
  self->model = g_value_dup_string(value);
}

static void gst_mock_gva_detect_get_property(
    GObject* object,
    guint prop_id,
    GValue* value,
    GParamSpec* pspec) {
  GstMockGvaDetect* self = reinterpret_cast<GstMockGvaDetect*>(object);
  if (prop_id != PROP_MODEL) {
    G_OBJECT_WARN_INVALID_PROPERTY_ID(object, prop_id, pspec);
    return;
  }
  g_value_set_string(value, self->model);
}

static void gst_mock_gva_detect_finalize(GObject* object) {
  GstMockGvaDetect* self = reinterpret_cast<GstMockGvaDetect*>(object);
  g_free(self->model);
  G_OBJECT_CLASS(gst_mock_gva_detect_parent_class)->finalize(object);
}

static void gst_mock_gva_detect_init(GstMockGvaDetect* self) {
  self->model = nullptr;
  gst_base_transform_set_in_place(GST_BASE_TRANSFORM(self), TRUE);
}

static void gst_mock_gva_detect_class_init(GstMockGvaDetectClass* klass) {
  GObjectClass* object_class = G_OBJECT_CLASS(klass);
  GstElementClass* element_class = GST_ELEMENT_CLASS(klass);
  object_class->set_property = gst_mock_gva_detect_set_property;
  object_class->get_property = gst_mock_gva_detect_get_property;
  object_class->finalize = gst_mock_gva_detect_finalize;
  properties[PROP_MODEL] = g_param_spec_string(
      "model",
      "Model",
      "Test-only model property",
      nullptr,
      static_cast<GParamFlags>(G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS));
  g_object_class_install_properties(object_class, N_PROPERTIES, properties);
  gst_element_class_set_static_metadata(
      element_class,
      "Contract-test detector",
      "Filter/Video",
      "Test-only factory used to exercise the terminal contract",
      "VAST tests");
  gst_element_class_add_static_pad_template(element_class, &sink_template);
  gst_element_class_add_static_pad_template(element_class, &src_template);
}

static bool run_terminal(
    const char* upstream_factory,
    const char* expected_factory,
    const char* model_path,
    const char* expected_model_sha256,
    const char* expected_weights_sha256,
    bool expect_start) {
  GstElement* upstream = gst_element_factory_make(upstream_factory, nullptr);
  GstElement* terminal = gst_element_factory_make("vastanalyticsterminal", nullptr);
  if (upstream == nullptr || terminal == nullptr) {
    return false;
  }
  g_object_set(upstream, "model", model_path, nullptr);
  g_object_set(
      terminal,
      "branch-id",
      "damage",
      "detector-id",
      "contract-test-detector",
      "expected-upstream-factory",
      expected_factory,
      "expected-model-sha256",
      expected_model_sha256,
      "expected-weights-sha256",
      expected_weights_sha256,
      nullptr);
  if (!gst_element_link(upstream, terminal)) {
    gst_object_unref(upstream);
    gst_object_unref(terminal);
    return false;
  }

  GstBaseTransform* transform = GST_BASE_TRANSFORM(terminal);
  GstBaseTransformClass* transform_class = GST_BASE_TRANSFORM_GET_CLASS(transform);
  const gboolean started = transform_class->start(transform);
  if (static_cast<bool>(started) != expect_start) {
    gst_object_unref(upstream);
    gst_object_unref(terminal);
    return false;
  }
  if (!started) {
    gst_object_unref(upstream);
    gst_object_unref(terminal);
    return true;
  }

  GstBuffer* buffer = gst_buffer_new_allocate(nullptr, 12, nullptr);
  GST_BUFFER_PTS(buffer) = 123456789;
  gst_buffer_add_video_region_of_interest_meta(buffer, "vehicle", 0, 0, 1, 1);
  gst_buffer_add_video_region_of_interest_meta(buffer, "damage", 1, 1, 1, 1);
  const GstFlowReturn flow = transform_class->transform_ip(transform, buffer);
  gst_buffer_unref(buffer);
  transform_class->stop(transform);
  gst_object_unref(upstream);
  gst_object_unref(terminal);
  return flow == GST_FLOW_OK;
}

static std::string sha256_text(const std::string& value) {
  gchar* digest = g_compute_checksum_for_data(
      G_CHECKSUM_SHA256,
      reinterpret_cast<const guchar*>(value.data()),
      value.size());
  const std::string result = digest == nullptr ? std::string() : std::string(digest);
  g_free(digest);
  return result;
}

int main(int argc, char** argv) {
  if (argc != 2) {
    std::cerr << "usage: gst-vast-analytics-terminal-test PLUGIN\n";
    return 2;
  }
  gst_init(&argc, &argv);
  GError* error = nullptr;
  GstPlugin* plugin = gst_plugin_load_file(argv[1], &error);
  if (plugin == nullptr) {
    std::cerr << (error == nullptr ? "plugin load failed" : error->message) << "\n";
    g_clear_error(&error);
    return 3;
  }
  gst_object_unref(plugin);

  if (gst_element_factory_find("gvadetect") != nullptr ||
      !gst_element_register(nullptr, "gvadetect", GST_RANK_PRIMARY, GST_TYPE_MOCK_GVA_DETECT)) {
    std::cerr << "test-only detector factories could not be registered\n";
    return 77;
  }

  const char* configured_tmp = std::getenv("TMPDIR");
  const std::string tmp_root =
      configured_tmp == nullptr || std::string(configured_tmp).empty() ? "/tmp" : configured_tmp;
  const std::string directory_pattern = tmp_root + "/vast-terminal-model-XXXXXX";
  std::vector<char> directory_template(directory_pattern.begin(), directory_pattern.end());
  directory_template.push_back('\0');
  const char* directory = ::mkdtemp(directory_template.data());
  if (directory == nullptr) {
    return 4;
  }
  const std::string model_path = std::string(directory) + "/damage.xml";
  const std::string weights_path = std::string(directory) + "/damage.bin";
  const std::string model_contents = "<net name=\"contract-test\" version=\"11\"/>\n";
  const std::string weights_contents = "contract-test-openvino-weights\n";
  {
    std::ofstream model(model_path, std::ios::binary);
    std::ofstream weights(weights_path, std::ios::binary);
    model << model_contents;
    weights << weights_contents;
    if (!model || !weights) {
      return 5;
    }
  }
  const std::string model_sha256 = sha256_text(model_contents);
  const std::string weights_sha256 = sha256_text(weights_contents);

  int descriptors[2] = {-1, -1};
  if (::socketpair(AF_UNIX, SOCK_DGRAM, 0, descriptors) != 0) {
    return 6;
  }
  const std::string descriptor = std::to_string(descriptors[0]);
  if (::setenv(vast::CheckpointAnalyticsTerminalTransport::kFdEnvironment, descriptor.c_str(), 1) != 0) {
    return 7;
  }

  if (!run_terminal(
          "gvadetect",
          "gvadetect",
          model_path.c_str(),
          model_sha256.c_str(),
          weights_sha256.c_str(),
          true)) {
    return 8;
  }
  const vast::CheckpointAnalyticsTerminal terminal =
      vast::CheckpointAnalyticsTerminalTransport::receive(descriptors[1]);
  if (terminal.transport_pts_ns != 123456789 ||
      terminal.status != vast::CheckpointAnalyticsTerminalStatus::kCompleted ||
      terminal.objects != 2 || terminal.branch_id != "damage" ||
      terminal.terminal_reason != "native_roi_metadata_committed" ||
      terminal.detector !=
          "contract-test-detector;model_sha256=" + model_sha256 +
              ";weights_sha256=" + weights_sha256 ||
      terminal.backend != "openvino-dlstreamer:gvadetect") {
    return 9;
  }
  if (!run_terminal(
          "gvadetect",
          "object_detect",
          model_path.c_str(),
          model_sha256.c_str(),
          weights_sha256.c_str(),
          false)) {
    return 10;
  }
  if (!run_terminal(
          "gvadetect",
          "gvadetect",
          model_path.c_str(),
          "0000000000000000000000000000000000000000000000000000000000000000",
          weights_sha256.c_str(),
          false)) {
    return 11;
  }
  if (!run_terminal(
          "gvadetect",
          "gvadetect",
          model_path.c_str(),
          model_sha256.c_str(),
          "0000000000000000000000000000000000000000000000000000000000000000",
          false)) {
    return 12;
  }

  ::unsetenv(vast::CheckpointAnalyticsTerminalTransport::kFdEnvironment);
  ::close(descriptors[0]);
  ::close(descriptors[1]);
  ::unlink(model_path.c_str());
  ::unlink(weights_path.c_str());
  ::rmdir(directory);
  return 0;
}
