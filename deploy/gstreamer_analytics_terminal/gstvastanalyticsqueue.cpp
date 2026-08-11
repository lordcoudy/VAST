#include <gst/gst.h>

#include <exception>
#include <string>

#include "checkpoint_analytics_terminal_transport.hpp"
#include "checkpoint_analytics_model_provenance.hpp"

#ifndef PACKAGE
#define PACKAGE "vast"
#endif

#define GST_TYPE_VAST_ANALYTICS_QUEUE (gst_vast_analytics_queue_get_type())
#define GST_VAST_ANALYTICS_QUEUE(obj) \
  (G_TYPE_CHECK_INSTANCE_CAST((obj), GST_TYPE_VAST_ANALYTICS_QUEUE, GstVastAnalyticsQueue))

typedef struct _GstVastAnalyticsQueue GstVastAnalyticsQueue;
typedef struct _GstVastAnalyticsQueueClass GstVastAnalyticsQueueClass;

typedef struct {
  GstMiniObject* object;
  gboolean is_buffer;
} QueueItem;

struct _GstVastAnalyticsQueue {
  GstElement parent;
  GstPad* sink_pad;
  GstPad* src_pad;
  gchar* branch_id;
  gchar* detector_id;
  gchar* expected_downstream_factory;
  gchar* expected_model_sha256;
  gchar* expected_weights_sha256;
  gchar* verified_downstream_factory;
  gchar* verified_detector_identity;
  guint max_buffers;
  GMutex lock;
  GCond condition;
  GQueue items;
  guint queued_buffers;
  gboolean running;
  gboolean flushing;
  GstFlowReturn downstream_flow;
  vast::CheckpointAnalyticsTerminalEmitter* emitter;
};

struct _GstVastAnalyticsQueueClass {
  GstElementClass parent_class;
};

G_DEFINE_TYPE(GstVastAnalyticsQueue, gst_vast_analytics_queue, GST_TYPE_ELEMENT)

enum {
  PROP_0,
  PROP_BRANCH_ID,
  PROP_DETECTOR_ID,
  PROP_EXPECTED_DOWNSTREAM_FACTORY,
  PROP_EXPECTED_MODEL_SHA256,
  PROP_EXPECTED_WEIGHTS_SHA256,
  PROP_MAX_BUFFERS,
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

static void free_item(QueueItem* item) {
  if (item == nullptr) {
    return;
  }
  gst_mini_object_unref(item->object);
  g_free(item);
}

static void clear_items_locked(GstVastAnalyticsQueue* self) {
  while (!g_queue_is_empty(&self->items)) {
    free_item(static_cast<QueueItem*>(g_queue_pop_head(&self->items)));
  }
  self->queued_buffers = 0;
}

static gboolean start_runtime(GstVastAnalyticsQueue* self) {
  if (!vast::gstanalytics::valid_branch_id(self->branch_id) ||
      !vast::gstanalytics::valid_detector_id(self->detector_id) || self->max_buffers == 0 ||
      self->expected_downstream_factory == nullptr || self->expected_downstream_factory[0] == '\0') {
    GST_ELEMENT_ERROR(
        self,
        RESOURCE,
        SETTINGS,
        ("branch-id, valid detector-id, positive max-buffers, and expected-downstream-factory are required"),
        (nullptr));
    return FALSE;
  }
  if (!vast::gstanalytics::supported_detector_factory(self->expected_downstream_factory)) {
    GST_ELEMENT_ERROR(
        self,
        RESOURCE,
        SETTINGS,
        ("expected-downstream-factory must be gvadetect or object_detect"),
        ("received %s", self->expected_downstream_factory));
    return FALSE;
  }

  GstElement* downstream = vast::gstanalytics::immediate_peer_element(self->src_pad);
  const std::string factory = vast::gstanalytics::element_factory_name(downstream);
  if (downstream == nullptr || factory.empty()) {
    if (downstream != nullptr) {
      gst_object_unref(downstream);
    }
    GST_ELEMENT_ERROR(
        self,
        RESOURCE,
        SETTINGS,
        ("unable to identify the immediate downstream detector factory"),
        (nullptr));
    return FALSE;
  }
  if (!vast::gstanalytics::supported_detector_factory(factory.c_str()) ||
      g_strcmp0(factory.c_str(), self->expected_downstream_factory) != 0) {
    GST_ELEMENT_ERROR(
        self,
        RESOURCE,
        SETTINGS,
        ("analytics queue must be placed directly before the declared real detector"),
        ("expected %s, observed %s", self->expected_downstream_factory, factory.c_str()));
    gst_object_unref(downstream);
    return FALSE;
  }

  std::string detector_identity;
  try {
    detector_identity = vast::gstanalytics::verified_model_identity(
        downstream,
        self->detector_id,
        self->expected_model_sha256,
        self->expected_weights_sha256);
  } catch (const std::exception& exc) {
    GST_ELEMENT_ERROR(
        self,
        RESOURCE,
        SETTINGS,
        ("downstream detector model provenance is invalid"),
        ("factory %s: %s", factory.c_str(), exc.what()));
    gst_object_unref(downstream);
    return FALSE;
  }
  gst_object_unref(downstream);

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

  g_free(self->verified_downstream_factory);
  g_free(self->verified_detector_identity);
  self->verified_downstream_factory = g_strdup(factory.c_str());
  self->verified_detector_identity = g_strdup(detector_identity.c_str());
  g_mutex_lock(&self->lock);
  clear_items_locked(self);
  self->queued_buffers = 0;
  self->flushing = FALSE;
  self->downstream_flow = GST_FLOW_OK;
  self->running = TRUE;
  g_mutex_unlock(&self->lock);
  return TRUE;
}

static void stop_runtime(GstVastAnalyticsQueue* self) {
  g_mutex_lock(&self->lock);
  self->running = FALSE;
  self->flushing = TRUE;
  g_cond_broadcast(&self->condition);
  g_mutex_unlock(&self->lock);
  if (self->src_pad != nullptr && GST_IS_PAD(self->src_pad)) {
    gst_pad_stop_task(self->src_pad);
  }
  g_mutex_lock(&self->lock);
  clear_items_locked(self);
  g_mutex_unlock(&self->lock);
  delete self->emitter;
  self->emitter = nullptr;
  g_clear_pointer(&self->verified_downstream_factory, g_free);
  g_clear_pointer(&self->verified_detector_identity, g_free);
}

static void queue_task(gpointer data) {
  GstVastAnalyticsQueue* self = GST_VAST_ANALYTICS_QUEUE(data);
  QueueItem* item = nullptr;
  g_mutex_lock(&self->lock);
  while (self->running && !self->flushing && g_queue_is_empty(&self->items)) {
    g_cond_wait(&self->condition, &self->lock);
  }
  if (self->running && !self->flushing) {
    item = static_cast<QueueItem*>(g_queue_pop_head(&self->items));
    if (item != nullptr && item->is_buffer) {
      --self->queued_buffers;
    }
  }
  g_mutex_unlock(&self->lock);

  if (item == nullptr) {
    gst_pad_pause_task(self->src_pad);
    return;
  }

  GstFlowReturn flow = GST_FLOW_OK;
  if (item->is_buffer) {
    GstBuffer* buffer = GST_BUFFER_CAST(item->object);
    item->object = nullptr;
    flow = gst_pad_push(self->src_pad, buffer);
  } else {
    GstEvent* event = GST_EVENT_CAST(item->object);
    item->object = nullptr;
    if (!gst_pad_push_event(self->src_pad, event)) {
      flow = GST_FLOW_ERROR;
    }
  }
  g_free(item);

  if (flow != GST_FLOW_OK) {
    g_mutex_lock(&self->lock);
    self->downstream_flow = flow;
    clear_items_locked(self);
    g_mutex_unlock(&self->lock);
    gst_pad_pause_task(self->src_pad);
  }
}

static GstFlowReturn sink_chain(GstPad*, GstObject* parent, GstBuffer* buffer) {
  GstVastAnalyticsQueue* self = GST_VAST_ANALYTICS_QUEUE(parent);
  if (!GST_BUFFER_PTS_IS_VALID(buffer)) {
    gst_buffer_unref(buffer);
    GST_ELEMENT_ERROR(
        self,
        STREAM,
        FORMAT,
        ("analytics queue input buffer has no valid transport PTS"),
        (nullptr));
    return GST_FLOW_ERROR;
  }

  g_mutex_lock(&self->lock);
  if (!self->running || self->flushing) {
    g_mutex_unlock(&self->lock);
    gst_buffer_unref(buffer);
    return GST_FLOW_FLUSHING;
  }
  if (self->downstream_flow != GST_FLOW_OK) {
    const GstFlowReturn flow = self->downstream_flow;
    g_mutex_unlock(&self->lock);
    gst_buffer_unref(buffer);
    return flow;
  }
  if (self->queued_buffers < self->max_buffers) {
    QueueItem* item = g_new0(QueueItem, 1);
    item->object = GST_MINI_OBJECT_CAST(buffer);
    item->is_buffer = TRUE;
    g_queue_push_tail(&self->items, item);
    ++self->queued_buffers;
    g_cond_signal(&self->condition);
    g_mutex_unlock(&self->lock);
    return GST_FLOW_OK;
  }
  g_mutex_unlock(&self->lock);

  vast::CheckpointAnalyticsTerminal terminal;
  terminal.transport_pts_ns = GST_BUFFER_PTS(buffer);
  terminal.status = vast::CheckpointAnalyticsTerminalStatus::kDrop;
  terminal.objects = 0;
  terminal.branch_id = self->branch_id;
  terminal.terminal_reason = "native_pre_detector_queue_full_drop_newest";
  terminal.detector = self->verified_detector_identity;
  terminal.backend = std::string("openvino-dlstreamer:") + self->verified_downstream_factory;
  gst_buffer_unref(buffer);
  try {
    self->emitter->emit(terminal);
  } catch (const std::exception& exc) {
    GST_ELEMENT_ERROR(
        self,
        RESOURCE,
        WRITE,
        ("failed to emit native pre-detector queue drop"),
        ("%s", exc.what()));
    return GST_FLOW_ERROR;
  }
  return GST_FLOW_OK;
}

static gboolean sink_event(GstPad*, GstObject* parent, GstEvent* event) {
  GstVastAnalyticsQueue* self = GST_VAST_ANALYTICS_QUEUE(parent);
  if (GST_EVENT_TYPE(event) == GST_EVENT_FLUSH_START) {
    g_mutex_lock(&self->lock);
    self->flushing = TRUE;
    clear_items_locked(self);
    g_cond_broadcast(&self->condition);
    g_mutex_unlock(&self->lock);
    return gst_pad_push_event(self->src_pad, event);
  }
  if (GST_EVENT_TYPE(event) == GST_EVENT_FLUSH_STOP) {
    const gboolean pushed = gst_pad_push_event(self->src_pad, event);
    g_mutex_lock(&self->lock);
    self->flushing = FALSE;
    self->downstream_flow = GST_FLOW_OK;
    g_cond_broadcast(&self->condition);
    g_mutex_unlock(&self->lock);
    if (self->running && gst_pad_get_task_state(self->src_pad) != GST_TASK_STARTED) {
      gst_pad_start_task(self->src_pad, queue_task, self, nullptr);
    }
    return pushed;
  }
  if (!GST_EVENT_IS_SERIALIZED(event)) {
    return gst_pad_push_event(self->src_pad, event);
  }

  g_mutex_lock(&self->lock);
  if (!self->running || self->flushing) {
    g_mutex_unlock(&self->lock);
    gst_event_unref(event);
    return FALSE;
  }
  QueueItem* item = g_new0(QueueItem, 1);
  item->object = GST_MINI_OBJECT_CAST(event);
  item->is_buffer = FALSE;
  g_queue_push_tail(&self->items, item);
  g_cond_signal(&self->condition);
  g_mutex_unlock(&self->lock);
  return TRUE;
}

static gboolean src_event(GstPad*, GstObject* parent, GstEvent* event) {
  return gst_pad_push_event(GST_VAST_ANALYTICS_QUEUE(parent)->sink_pad, event);
}

static gboolean sink_query(GstPad*, GstObject* parent, GstQuery* query) {
  return gst_pad_peer_query(GST_VAST_ANALYTICS_QUEUE(parent)->src_pad, query);
}

static gboolean src_query(GstPad*, GstObject* parent, GstQuery* query) {
  return gst_pad_peer_query(GST_VAST_ANALYTICS_QUEUE(parent)->sink_pad, query);
}

static GstStateChangeReturn change_state(GstElement* element, GstStateChange transition) {
  GstVastAnalyticsQueue* self = GST_VAST_ANALYTICS_QUEUE(element);
  if (transition == GST_STATE_CHANGE_READY_TO_PAUSED) {
    if (!start_runtime(self) || !gst_pad_start_task(self->src_pad, queue_task, self, nullptr)) {
      stop_runtime(self);
      return GST_STATE_CHANGE_FAILURE;
    }
  } else if (transition == GST_STATE_CHANGE_PAUSED_TO_READY) {
    stop_runtime(self);
  }

  const GstStateChangeReturn result =
      GST_ELEMENT_CLASS(gst_vast_analytics_queue_parent_class)->change_state(element, transition);
  if (result == GST_STATE_CHANGE_FAILURE && transition == GST_STATE_CHANGE_READY_TO_PAUSED) {
    stop_runtime(self);
  }
  return result;
}

static void set_property(GObject* object, guint prop_id, const GValue* value, GParamSpec* pspec) {
  GstVastAnalyticsQueue* self = GST_VAST_ANALYTICS_QUEUE(object);
  gchar** target = nullptr;
  switch (prop_id) {
    case PROP_BRANCH_ID:
      target = &self->branch_id;
      break;
    case PROP_DETECTOR_ID:
      target = &self->detector_id;
      break;
    case PROP_EXPECTED_DOWNSTREAM_FACTORY:
      target = &self->expected_downstream_factory;
      break;
    case PROP_EXPECTED_MODEL_SHA256:
      target = &self->expected_model_sha256;
      break;
    case PROP_EXPECTED_WEIGHTS_SHA256:
      target = &self->expected_weights_sha256;
      break;
    case PROP_MAX_BUFFERS:
      self->max_buffers = g_value_get_uint(value);
      return;
    default:
      G_OBJECT_WARN_INVALID_PROPERTY_ID(object, prop_id, pspec);
      return;
  }
  g_free(*target);
  *target = g_value_dup_string(value);
}

static void get_property(GObject* object, guint prop_id, GValue* value, GParamSpec* pspec) {
  GstVastAnalyticsQueue* self = GST_VAST_ANALYTICS_QUEUE(object);
  switch (prop_id) {
    case PROP_BRANCH_ID:
      g_value_set_string(value, self->branch_id);
      break;
    case PROP_DETECTOR_ID:
      g_value_set_string(value, self->detector_id);
      break;
    case PROP_EXPECTED_DOWNSTREAM_FACTORY:
      g_value_set_string(value, self->expected_downstream_factory);
      break;
    case PROP_EXPECTED_MODEL_SHA256:
      g_value_set_string(value, self->expected_model_sha256);
      break;
    case PROP_EXPECTED_WEIGHTS_SHA256:
      g_value_set_string(value, self->expected_weights_sha256);
      break;
    case PROP_MAX_BUFFERS:
      g_value_set_uint(value, self->max_buffers);
      break;
    default:
      G_OBJECT_WARN_INVALID_PROPERTY_ID(object, prop_id, pspec);
      break;
  }
}

static void finalize(GObject* object) {
  GstVastAnalyticsQueue* self = GST_VAST_ANALYTICS_QUEUE(object);
  stop_runtime(self);
  g_free(self->branch_id);
  g_free(self->detector_id);
  g_free(self->expected_downstream_factory);
  g_free(self->expected_model_sha256);
  g_free(self->expected_weights_sha256);
  g_mutex_clear(&self->lock);
  g_cond_clear(&self->condition);
  G_OBJECT_CLASS(gst_vast_analytics_queue_parent_class)->finalize(object);
}

static void gst_vast_analytics_queue_init(GstVastAnalyticsQueue* self) {
  self->sink_pad = gst_pad_new_from_static_template(&sink_template, "sink");
  self->src_pad = gst_pad_new_from_static_template(&src_template, "src");
  gst_pad_set_chain_function(self->sink_pad, GST_DEBUG_FUNCPTR(sink_chain));
  gst_pad_set_event_function(self->sink_pad, GST_DEBUG_FUNCPTR(sink_event));
  gst_pad_set_query_function(self->sink_pad, GST_DEBUG_FUNCPTR(sink_query));
  gst_pad_set_event_function(self->src_pad, GST_DEBUG_FUNCPTR(src_event));
  gst_pad_set_query_function(self->src_pad, GST_DEBUG_FUNCPTR(src_query));
  gst_element_add_pad(GST_ELEMENT(self), self->sink_pad);
  gst_element_add_pad(GST_ELEMENT(self), self->src_pad);
  g_mutex_init(&self->lock);
  g_cond_init(&self->condition);
  g_queue_init(&self->items);
  self->max_buffers = 0;
  self->downstream_flow = GST_FLOW_OK;
}

static void gst_vast_analytics_queue_class_init(GstVastAnalyticsQueueClass* klass) {
  GObjectClass* object_class = G_OBJECT_CLASS(klass);
  GstElementClass* element_class = GST_ELEMENT_CLASS(klass);
  object_class->set_property = set_property;
  object_class->get_property = get_property;
  object_class->finalize = finalize;
  element_class->change_state = change_state;

  properties[PROP_BRANCH_ID] = g_param_spec_string(
      "branch-id", "Branch ID", "Checkpoint branch receiving explicit queue drops", nullptr,
      static_cast<GParamFlags>(G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS));
  properties[PROP_DETECTOR_ID] = g_param_spec_string(
      "detector-id", "Detector ID", "Stable detector/model identifier", nullptr,
      static_cast<GParamFlags>(G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS));
  properties[PROP_EXPECTED_DOWNSTREAM_FACTORY] = g_param_spec_string(
      "expected-downstream-factory", "Expected downstream factory",
      "Exact allowed DL Streamer detector factory immediately downstream", nullptr,
      static_cast<GParamFlags>(G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS));
  properties[PROP_EXPECTED_MODEL_SHA256] = g_param_spec_string(
      "expected-model-sha256", "Expected model SHA-256",
      "Lowercase SHA-256 of the exact downstream detector model file", nullptr,
      static_cast<GParamFlags>(G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS));
  properties[PROP_EXPECTED_WEIGHTS_SHA256] = g_param_spec_string(
      "expected-weights-sha256", "Expected weights SHA-256",
      "Lowercase SHA-256 of the sibling OpenVINO IR .bin file", nullptr,
      static_cast<GParamFlags>(G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS));
  properties[PROP_MAX_BUFFERS] = g_param_spec_uint(
      "max-buffers", "Maximum queued buffers",
      "Pre-registered number of waiting buffers; a full queue drops the newest admission",
      0, G_MAXUINT, 0,
      static_cast<GParamFlags>(G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS));
  g_object_class_install_properties(object_class, N_PROPERTIES, properties);

  gst_element_class_set_static_metadata(
      element_class,
      "VAST bounded native analytics queue",
      "Generic/Queue/Video",
      "Emits exact-PTS branch drops when the pre-detector waiting queue is full",
      "VAST benchmark");
  gst_element_class_add_static_pad_template(element_class, &sink_template);
  gst_element_class_add_static_pad_template(element_class, &src_template);
}

static gboolean plugin_init(GstPlugin* plugin) {
  return gst_element_register(
      plugin,
      "vastanalyticsqueue",
      GST_RANK_NONE,
      GST_TYPE_VAST_ANALYTICS_QUEUE);
}

GST_PLUGIN_DEFINE(
    GST_VERSION_MAJOR,
    GST_VERSION_MINOR,
    vastanalyticsqueue,
    "VAST bounded native pre-detector analytics queue",
    plugin_init,
    "1.0.0",
    "LGPL",
    "VAST",
    "https://example.invalid/vast")
