#include <gst/base/gstbasetransform.h>
#include <gst/gst.h>
#include <gst/video/gstvideometa.h>

#include <exception>
#include <string>

#include "checkpoint_analytics_terminal_transport.hpp"
#include "checkpoint_analytics_model_provenance.hpp"

#ifndef PACKAGE
#define PACKAGE "vast"
#endif

#define GST_TYPE_VAST_ANALYTICS_TERMINAL (gst_vast_analytics_terminal_get_type())
#define GST_VAST_ANALYTICS_TERMINAL(obj) \
  (G_TYPE_CHECK_INSTANCE_CAST((obj), GST_TYPE_VAST_ANALYTICS_TERMINAL, GstVastAnalyticsTerminal))

typedef struct _GstVastAnalyticsTerminal GstVastAnalyticsTerminal;
typedef struct _GstVastAnalyticsTerminalClass GstVastAnalyticsTerminalClass;

struct _GstVastAnalyticsTerminal {
  GstBaseTransform parent;
  gchar* branch_id;
  gchar* detector_id;
  gchar* expected_upstream_factory;
  gchar* expected_model_sha256;
  gchar* expected_weights_sha256;
  gchar* verified_upstream_factory;
  gchar* verified_detector_identity;
  vast::CheckpointAnalyticsTerminalEmitter* emitter;
};

struct _GstVastAnalyticsTerminalClass {
  GstBaseTransformClass parent_class;
};

G_DEFINE_TYPE(GstVastAnalyticsTerminal, gst_vast_analytics_terminal, GST_TYPE_BASE_TRANSFORM)

enum {
  PROP_0,
  PROP_BRANCH_ID,
  PROP_DETECTOR_ID,
  PROP_EXPECTED_UPSTREAM_FACTORY,
  PROP_EXPECTED_MODEL_SHA256,
  PROP_EXPECTED_WEIGHTS_SHA256,
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

static guint64 count_roi_metadata(GstBuffer* buffer) {
  guint64 count = 0;
  gpointer state = nullptr;
  const GstMeta* meta = nullptr;
  while ((meta = gst_buffer_iterate_meta(buffer, &state)) != nullptr) {
    if (meta->info->api == GST_VIDEO_REGION_OF_INTEREST_META_API_TYPE) {
      ++count;
    }
  }
  return count;
}

static gboolean gst_vast_analytics_terminal_start(GstBaseTransform* transform) {
  GstVastAnalyticsTerminal* self = GST_VAST_ANALYTICS_TERMINAL(transform);
  if (!vast::gstanalytics::valid_branch_id(self->branch_id) ||
      !vast::gstanalytics::valid_detector_id(self->detector_id) ||
      self->expected_upstream_factory == nullptr || self->expected_upstream_factory[0] == '\0') {
    GST_ELEMENT_ERROR(
        self,
        RESOURCE,
        SETTINGS,
        ("branch-id, valid detector-id, and expected-upstream-factory are required"),
        (nullptr));
    return FALSE;
  }
  if (!vast::gstanalytics::supported_detector_factory(self->expected_upstream_factory)) {
    GST_ELEMENT_ERROR(
        self,
        RESOURCE,
        SETTINGS,
        ("expected-upstream-factory must be gvadetect or object_detect"),
        ("received %s", self->expected_upstream_factory));
    return FALSE;
  }

  GstElement* upstream = vast::gstanalytics::immediate_peer_element(GST_BASE_TRANSFORM_SINK_PAD(self));
  const std::string factory = vast::gstanalytics::element_factory_name(upstream);
  if (factory.empty() || upstream == nullptr) {
    GST_ELEMENT_ERROR(
        self,
        RESOURCE,
        SETTINGS,
        ("unable to identify the immediate upstream detector factory"),
        (nullptr));
    return FALSE;
  }
  const gboolean factory_matches =
      vast::gstanalytics::supported_detector_factory(factory.c_str()) &&
      g_strcmp0(factory.c_str(), self->expected_upstream_factory) == 0;
  if (!factory_matches) {
    GST_ELEMENT_ERROR(
        self,
        RESOURCE,
        SETTINGS,
        ("analytics terminal must be placed directly after the declared real detector"),
        ("expected %s, observed %s", self->expected_upstream_factory, factory.c_str()));
    gst_object_unref(upstream);
    return FALSE;
  }

  std::string detector_identity;
  try {
    detector_identity = vast::gstanalytics::verified_model_identity(
        upstream,
        self->detector_id,
        self->expected_model_sha256,
        self->expected_weights_sha256);
  } catch (const std::exception& exc) {
    GST_ELEMENT_ERROR(
        self,
        RESOURCE,
        SETTINGS,
        ("upstream detector model provenance is invalid"),
        ("factory %s: %s", factory.c_str(), exc.what()));
    gst_object_unref(upstream);
    return FALSE;
  }
  gst_object_unref(upstream);

  try {
    self->emitter = new vast::CheckpointAnalyticsTerminalEmitter(
        vast::CheckpointAnalyticsTerminalEmitter::from_environment());
  } catch (const std::exception& exc) {
    GST_ELEMENT_ERROR(
        self,
        RESOURCE,
        OPEN_READ,
        ("checkpoint analytics terminal transport is unavailable"),
        ("%s", exc.what()));
    return FALSE;
  }
  g_free(self->verified_upstream_factory);
  g_free(self->verified_detector_identity);
  self->verified_upstream_factory = g_strdup(factory.c_str());
  self->verified_detector_identity = g_strdup(detector_identity.c_str());
  return TRUE;
}

static gboolean gst_vast_analytics_terminal_stop(GstBaseTransform* transform) {
  GstVastAnalyticsTerminal* self = GST_VAST_ANALYTICS_TERMINAL(transform);
  delete self->emitter;
  self->emitter = nullptr;
  g_clear_pointer(&self->verified_upstream_factory, g_free);
  g_clear_pointer(&self->verified_detector_identity, g_free);
  return TRUE;
}

static GstFlowReturn gst_vast_analytics_terminal_transform_ip(
    GstBaseTransform* transform,
    GstBuffer* buffer) {
  GstVastAnalyticsTerminal* self = GST_VAST_ANALYTICS_TERMINAL(transform);
  if (self->emitter == nullptr || self->verified_upstream_factory == nullptr ||
      self->verified_detector_identity == nullptr) {
    GST_ELEMENT_ERROR(self, RESOURCE, FAILED, ("analytics terminal is not started"), (nullptr));
    return GST_FLOW_ERROR;
  }
  if (!GST_BUFFER_PTS_IS_VALID(buffer)) {
    GST_ELEMENT_ERROR(
        self,
        STREAM,
        FORMAT,
        ("detector output buffer has no valid transport PTS"),
        (nullptr));
    return GST_FLOW_ERROR;
  }

  vast::CheckpointAnalyticsTerminal terminal;
  terminal.transport_pts_ns = GST_BUFFER_PTS(buffer);
  terminal.status = vast::CheckpointAnalyticsTerminalStatus::kCompleted;
  terminal.objects = count_roi_metadata(buffer);
  terminal.branch_id = self->branch_id;
  terminal.terminal_reason = "native_roi_metadata_committed";
  terminal.detector = self->verified_detector_identity;
  terminal.backend = std::string("openvino-dlstreamer:") + self->verified_upstream_factory;
  try {
    self->emitter->emit(terminal);
  } catch (const std::exception& exc) {
    GST_ELEMENT_ERROR(
        self,
        RESOURCE,
        WRITE,
        ("failed to emit checkpoint analytics terminal"),
        ("%s", exc.what()));
    return GST_FLOW_ERROR;
  }
  return GST_FLOW_OK;
}

static void gst_vast_analytics_terminal_set_property(
    GObject* object,
    guint prop_id,
    const GValue* value,
    GParamSpec* pspec) {
  GstVastAnalyticsTerminal* self = GST_VAST_ANALYTICS_TERMINAL(object);
  gchar** target = nullptr;
  switch (prop_id) {
    case PROP_BRANCH_ID:
      target = &self->branch_id;
      break;
    case PROP_DETECTOR_ID:
      target = &self->detector_id;
      break;
    case PROP_EXPECTED_UPSTREAM_FACTORY:
      target = &self->expected_upstream_factory;
      break;
    case PROP_EXPECTED_MODEL_SHA256:
      target = &self->expected_model_sha256;
      break;
    case PROP_EXPECTED_WEIGHTS_SHA256:
      target = &self->expected_weights_sha256;
      break;
    default:
      G_OBJECT_WARN_INVALID_PROPERTY_ID(object, prop_id, pspec);
      return;
  }
  g_free(*target);
  *target = g_value_dup_string(value);
}

static void gst_vast_analytics_terminal_get_property(
    GObject* object,
    guint prop_id,
    GValue* value,
    GParamSpec* pspec) {
  GstVastAnalyticsTerminal* self = GST_VAST_ANALYTICS_TERMINAL(object);
  switch (prop_id) {
    case PROP_BRANCH_ID:
      g_value_set_string(value, self->branch_id);
      break;
    case PROP_DETECTOR_ID:
      g_value_set_string(value, self->detector_id);
      break;
    case PROP_EXPECTED_UPSTREAM_FACTORY:
      g_value_set_string(value, self->expected_upstream_factory);
      break;
    case PROP_EXPECTED_MODEL_SHA256:
      g_value_set_string(value, self->expected_model_sha256);
      break;
    case PROP_EXPECTED_WEIGHTS_SHA256:
      g_value_set_string(value, self->expected_weights_sha256);
      break;
    default:
      G_OBJECT_WARN_INVALID_PROPERTY_ID(object, prop_id, pspec);
      break;
  }
}

static void gst_vast_analytics_terminal_finalize(GObject* object) {
  GstVastAnalyticsTerminal* self = GST_VAST_ANALYTICS_TERMINAL(object);
  delete self->emitter;
  g_free(self->branch_id);
  g_free(self->detector_id);
  g_free(self->expected_upstream_factory);
  g_free(self->expected_model_sha256);
  g_free(self->expected_weights_sha256);
  g_free(self->verified_upstream_factory);
  g_free(self->verified_detector_identity);
  G_OBJECT_CLASS(gst_vast_analytics_terminal_parent_class)->finalize(object);
}

static void gst_vast_analytics_terminal_init(GstVastAnalyticsTerminal* self) {
  self->branch_id = nullptr;
  self->detector_id = nullptr;
  self->expected_upstream_factory = nullptr;
  self->expected_model_sha256 = nullptr;
  self->expected_weights_sha256 = nullptr;
  self->verified_upstream_factory = nullptr;
  self->verified_detector_identity = nullptr;
  self->emitter = nullptr;
  gst_base_transform_set_in_place(GST_BASE_TRANSFORM(self), TRUE);
  gst_base_transform_set_passthrough(GST_BASE_TRANSFORM(self), FALSE);
}

static void gst_vast_analytics_terminal_class_init(GstVastAnalyticsTerminalClass* klass) {
  GObjectClass* object_class = G_OBJECT_CLASS(klass);
  GstElementClass* element_class = GST_ELEMENT_CLASS(klass);
  GstBaseTransformClass* transform_class = GST_BASE_TRANSFORM_CLASS(klass);

  object_class->set_property = gst_vast_analytics_terminal_set_property;
  object_class->get_property = gst_vast_analytics_terminal_get_property;
  object_class->finalize = gst_vast_analytics_terminal_finalize;

  properties[PROP_BRANCH_ID] = g_param_spec_string(
      "branch-id",
      "Branch ID",
      "Declared checkpoint branch receiving this detector result",
      nullptr,
      static_cast<GParamFlags>(G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS));
  properties[PROP_DETECTOR_ID] = g_param_spec_string(
      "detector-id",
      "Detector ID",
      "Stable detector/model identifier recorded in the branch terminal",
      nullptr,
      static_cast<GParamFlags>(G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS));
  properties[PROP_EXPECTED_UPSTREAM_FACTORY] = g_param_spec_string(
      "expected-upstream-factory",
      "Expected upstream factory",
      "Exact allowed DL Streamer detector factory immediately upstream",
      nullptr,
      static_cast<GParamFlags>(G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS));
  properties[PROP_EXPECTED_MODEL_SHA256] = g_param_spec_string(
      "expected-model-sha256",
      "Expected model SHA-256",
      "Lowercase SHA-256 of the exact file configured by the upstream model property",
      nullptr,
      static_cast<GParamFlags>(G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS));
  properties[PROP_EXPECTED_WEIGHTS_SHA256] = g_param_spec_string(
      "expected-weights-sha256",
      "Expected weights SHA-256",
      "Lowercase SHA-256 of the sibling .bin file required by an OpenVINO IR model",
      nullptr,
      static_cast<GParamFlags>(G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS));
  g_object_class_install_properties(object_class, N_PROPERTIES, properties);

  gst_element_class_set_static_metadata(
      element_class,
      "VAST native analytics terminal",
      "Filter/Metadata/Video",
      "Emits branch completion from ROI metadata produced by a verified DL Streamer detector",
      "VAST benchmark");
  gst_element_class_add_static_pad_template(element_class, &sink_template);
  gst_element_class_add_static_pad_template(element_class, &src_template);

  transform_class->start = GST_DEBUG_FUNCPTR(gst_vast_analytics_terminal_start);
  transform_class->stop = GST_DEBUG_FUNCPTR(gst_vast_analytics_terminal_stop);
  transform_class->transform_ip = GST_DEBUG_FUNCPTR(gst_vast_analytics_terminal_transform_ip);
}

static gboolean plugin_init(GstPlugin* plugin) {
  return gst_element_register(
      plugin,
      "vastanalyticsterminal",
      GST_RANK_NONE,
      GST_TYPE_VAST_ANALYTICS_TERMINAL);
}

GST_PLUGIN_DEFINE(
    GST_VERSION_MAJOR,
    GST_VERSION_MINOR,
    vastanalyticsterminal,
    "VAST native branch analytics terminal",
    plugin_init,
    "1.0.0",
    "LGPL",
    "VAST",
    "https://example.invalid/vast")
