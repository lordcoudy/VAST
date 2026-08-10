#include <gst/app/gstappsrc.h>
#include <gst/base/gstbasetransform.h>
#include <gst/gst.h>

#include <cstdlib>
#include <fstream>
#include <iostream>
#include <string>

#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>

#include "checkpoint_analytics_terminal_transport.hpp"

#define GST_TYPE_BLOCKING_GVA_DETECT (gst_blocking_gva_detect_get_type())

typedef struct _GstBlockingGvaDetect GstBlockingGvaDetect;
typedef struct _GstBlockingGvaDetectClass GstBlockingGvaDetectClass;

struct _GstBlockingGvaDetect {
  GstBaseTransform parent;
  gchar* model;
  GMutex lock;
  GCond condition;
  gboolean entered;
  gboolean released;
};

struct _GstBlockingGvaDetectClass {
  GstBaseTransformClass parent_class;
};

G_DEFINE_TYPE(GstBlockingGvaDetect, gst_blocking_gva_detect, GST_TYPE_BASE_TRANSFORM)

enum {
  PROP_0,
  PROP_MODEL,
  N_PROPERTIES,
};

static GParamSpec* properties[N_PROPERTIES] = {nullptr};

static GstStaticPadTemplate sink_template = GST_STATIC_PAD_TEMPLATE(
    "sink", GST_PAD_SINK, GST_PAD_ALWAYS, GST_STATIC_CAPS_ANY);
static GstStaticPadTemplate src_template = GST_STATIC_PAD_TEMPLATE(
    "src", GST_PAD_SRC, GST_PAD_ALWAYS, GST_STATIC_CAPS_ANY);

static GstFlowReturn transform_ip(GstBaseTransform* transform, GstBuffer*) {
  GstBlockingGvaDetect* self = reinterpret_cast<GstBlockingGvaDetect*>(transform);
  g_mutex_lock(&self->lock);
  self->entered = TRUE;
  g_cond_broadcast(&self->condition);
  while (!self->released) {
    g_cond_wait(&self->condition, &self->lock);
  }
  g_mutex_unlock(&self->lock);
  return GST_FLOW_OK;
}

static void set_property(GObject* object, guint prop_id, const GValue* value, GParamSpec* pspec) {
  GstBlockingGvaDetect* self = reinterpret_cast<GstBlockingGvaDetect*>(object);
  if (prop_id != PROP_MODEL) {
    G_OBJECT_WARN_INVALID_PROPERTY_ID(object, prop_id, pspec);
    return;
  }
  g_free(self->model);
  self->model = g_value_dup_string(value);
}

static void get_property(GObject* object, guint prop_id, GValue* value, GParamSpec* pspec) {
  GstBlockingGvaDetect* self = reinterpret_cast<GstBlockingGvaDetect*>(object);
  if (prop_id != PROP_MODEL) {
    G_OBJECT_WARN_INVALID_PROPERTY_ID(object, prop_id, pspec);
    return;
  }
  g_value_set_string(value, self->model);
}

static void finalize(GObject* object) {
  GstBlockingGvaDetect* self = reinterpret_cast<GstBlockingGvaDetect*>(object);
  g_free(self->model);
  g_mutex_clear(&self->lock);
  g_cond_clear(&self->condition);
  G_OBJECT_CLASS(gst_blocking_gva_detect_parent_class)->finalize(object);
}

static void gst_blocking_gva_detect_init(GstBlockingGvaDetect* self) {
  g_mutex_init(&self->lock);
  g_cond_init(&self->condition);
  gst_base_transform_set_in_place(GST_BASE_TRANSFORM(self), TRUE);
}

static void gst_blocking_gva_detect_class_init(GstBlockingGvaDetectClass* klass) {
  GObjectClass* object_class = G_OBJECT_CLASS(klass);
  GstElementClass* element_class = GST_ELEMENT_CLASS(klass);
  GstBaseTransformClass* transform_class = GST_BASE_TRANSFORM_CLASS(klass);
  object_class->set_property = set_property;
  object_class->get_property = get_property;
  object_class->finalize = finalize;
  properties[PROP_MODEL] = g_param_spec_string(
      "model", "Model", "Test-only model property", nullptr,
      static_cast<GParamFlags>(G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS));
  g_object_class_install_properties(object_class, N_PROPERTIES, properties);
  gst_element_class_set_static_metadata(
      element_class, "Blocking contract-test detector", "Filter/Video",
      "Blocks one detector call so queue overflow is deterministic", "VAST tests");
  gst_element_class_add_static_pad_template(element_class, &sink_template);
  gst_element_class_add_static_pad_template(element_class, &src_template);
  transform_class->transform_ip = GST_DEBUG_FUNCPTR(transform_ip);
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

static GstBuffer* buffer_with_pts(GstClockTime pts) {
  GstBuffer* buffer = gst_buffer_new_allocate(nullptr, 12, nullptr);
  GST_BUFFER_PTS(buffer) = pts;
  return buffer;
}

static bool wait_until_entered(GstBlockingGvaDetect* detector) {
  const gint64 deadline = g_get_monotonic_time() + 2 * G_TIME_SPAN_SECOND;
  g_mutex_lock(&detector->lock);
  while (!detector->entered) {
    if (!g_cond_wait_until(&detector->condition, &detector->lock, deadline)) {
      g_mutex_unlock(&detector->lock);
      return false;
    }
  }
  g_mutex_unlock(&detector->lock);
  return true;
}

static void release_detector(GstBlockingGvaDetect* detector) {
  g_mutex_lock(&detector->lock);
  detector->released = TRUE;
  g_cond_broadcast(&detector->condition);
  g_mutex_unlock(&detector->lock);
}

int main(int argc, char** argv) {
  if (argc != 2) {
    std::cerr << "usage: gst-vast-analytics-queue-test PLUGIN\n";
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
      !gst_element_register(nullptr, "gvadetect", GST_RANK_PRIMARY, GST_TYPE_BLOCKING_GVA_DETECT)) {
    std::cerr << "test-only detector factory could not be registered\n";
    return 77;
  }

  char directory_template[] = "/private/tmp/vast-queue-model-XXXXXX";
  const char* directory = ::mkdtemp(directory_template);
  if (directory == nullptr) {
    return 4;
  }
  const std::string model_path = std::string(directory) + "/damage.xml";
  const std::string weights_path = std::string(directory) + "/damage.bin";
  const std::string model_contents = "<net name=\"queue-test\" version=\"11\"/>\n";
  const std::string weights_contents = "queue-test-openvino-weights\n";
  {
    std::ofstream model(model_path, std::ios::binary);
    std::ofstream weights(weights_path, std::ios::binary);
    model << model_contents;
    weights << weights_contents;
    if (!model || !weights) {
      return 5;
    }
  }

  int descriptors[2] = {-1, -1};
  if (::socketpair(AF_UNIX, SOCK_DGRAM, 0, descriptors) != 0) {
    return 6;
  }
  const timeval timeout = {2, 0};
  ::setsockopt(descriptors[1], SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
  const std::string descriptor = std::to_string(descriptors[0]);
  if (::setenv(vast::CheckpointAnalyticsTerminalTransport::kFdEnvironment, descriptor.c_str(), 1) != 0) {
    return 7;
  }

  GstElement* pipeline = gst_pipeline_new("queue-test");
  GstElement* source = gst_element_factory_make("appsrc", nullptr);
  GstElement* queue = gst_element_factory_make("vastanalyticsqueue", nullptr);
  GstElement* detector = gst_element_factory_make("gvadetect", nullptr);
  GstElement* sink = gst_element_factory_make("fakesink", nullptr);
  if (pipeline == nullptr || source == nullptr || queue == nullptr || detector == nullptr || sink == nullptr) {
    return 8;
  }
  const std::string model_sha256 = sha256_text(model_contents);
  const std::string weights_sha256 = sha256_text(weights_contents);
  g_object_set(source, "format", GST_FORMAT_TIME, nullptr);
  g_object_set(detector, "model", model_path.c_str(), nullptr);
  g_object_set(sink, "sync", FALSE, nullptr);
  g_object_set(
      queue,
      "branch-id", "damage",
      "detector-id", "contract-test-detector",
      "expected-downstream-factory", "gvadetect",
      "expected-model-sha256", model_sha256.c_str(),
      "expected-weights-sha256", weights_sha256.c_str(),
      "max-buffers", 1u,
      nullptr);
  gst_bin_add_many(GST_BIN(pipeline), source, queue, detector, sink, nullptr);
  if (!gst_element_link_many(source, queue, detector, sink, nullptr)) {
    return 9;
  }
  if (gst_element_set_state(pipeline, GST_STATE_PLAYING) == GST_STATE_CHANGE_FAILURE) {
    return 10;
  }

  if (gst_app_src_push_buffer(GST_APP_SRC(source), buffer_with_pts(100)) != GST_FLOW_OK ||
      !wait_until_entered(reinterpret_cast<GstBlockingGvaDetect*>(detector))) {
    return 11;
  }
  if (gst_app_src_push_buffer(GST_APP_SRC(source), buffer_with_pts(200)) != GST_FLOW_OK ||
      gst_app_src_push_buffer(GST_APP_SRC(source), buffer_with_pts(300)) != GST_FLOW_OK) {
    return 12;
  }

  const vast::CheckpointAnalyticsTerminal terminal =
      vast::CheckpointAnalyticsTerminalTransport::receive(descriptors[1]);
  if (terminal.transport_pts_ns != 300 ||
      terminal.status != vast::CheckpointAnalyticsTerminalStatus::kDrop ||
      terminal.objects != 0 || terminal.branch_id != "damage" ||
      terminal.terminal_reason != "native_pre_detector_queue_full_drop_newest" ||
      terminal.detector !=
          "contract-test-detector;model_sha256=" + model_sha256 +
              ";weights_sha256=" + weights_sha256 ||
      terminal.backend != "openvino-dlstreamer:gvadetect") {
    return 13;
  }

  release_detector(reinterpret_cast<GstBlockingGvaDetect*>(detector));
  gst_app_src_end_of_stream(GST_APP_SRC(source));
  gst_element_set_state(pipeline, GST_STATE_NULL);
  gst_object_unref(pipeline);
  ::unsetenv(vast::CheckpointAnalyticsTerminalTransport::kFdEnvironment);
  ::close(descriptors[0]);
  ::close(descriptors[1]);
  ::unlink(model_path.c_str());
  ::unlink(weights_path.c_str());
  ::rmdir(directory);
  return 0;
}
