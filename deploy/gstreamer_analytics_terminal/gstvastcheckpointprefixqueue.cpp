#include <gst/gst.h>

#include <exception>
#include <string>
#include <unordered_set>
#include <vector>

#include "checkpoint_analytics_terminal_transport.hpp"

#ifndef PACKAGE
#define PACKAGE "vast"
#endif

#define GST_TYPE_VAST_CHECKPOINT_PREFIX_QUEUE (gst_vast_checkpoint_prefix_queue_get_type())
#define GST_VAST_CHECKPOINT_PREFIX_QUEUE(obj)   (G_TYPE_CHECK_INSTANCE_CAST((obj), GST_TYPE_VAST_CHECKPOINT_PREFIX_QUEUE, GstVastCheckpointPrefixQueue))

typedef struct _GstVastCheckpointPrefixQueue GstVastCheckpointPrefixQueue;
typedef struct _GstVastCheckpointPrefixQueueClass GstVastCheckpointPrefixQueueClass;

typedef struct {
  GstMiniObject* object;
  gboolean is_buffer;
} PrefixQueueItem;

struct _GstVastCheckpointPrefixQueue {
  GstElement parent;
  GstPad* sink_pad;
  GstPad* src_pad;
  gchar* branch_ids;
  guint max_buffers;
  GMutex lock;
  GCond condition;
  GQueue items;
  guint queued_buffers;
  gboolean running;
  gboolean flushing;
  GstFlowReturn downstream_flow;
  std::vector<std::string>* branches;
  vast::CheckpointAnalyticsTerminalEmitter* emitter;
};

struct _GstVastCheckpointPrefixQueueClass {
  GstElementClass parent_class;
};

G_DEFINE_TYPE(
    GstVastCheckpointPrefixQueue,
    gst_vast_checkpoint_prefix_queue,
    GST_TYPE_ELEMENT)

enum {
  PROP_0,
  PROP_BRANCH_IDS,
  PROP_MAX_BUFFERS,
  N_PROPERTIES,
};

static GParamSpec* properties[N_PROPERTIES] = {nullptr};

static GstStaticPadTemplate sink_template = GST_STATIC_PAD_TEMPLATE(
    "sink",
    GST_PAD_SINK,
    GST_PAD_ALWAYS,
    GST_STATIC_CAPS("video/x-raw"));

static GstStaticPadTemplate src_template = GST_STATIC_PAD_TEMPLATE(
    "src",
    GST_PAD_SRC,
    GST_PAD_ALWAYS,
    GST_STATIC_CAPS("video/x-raw"));

static bool valid_branch_id(const std::string& value) {
  if (value.empty() || value.size() > 128) {
    return false;
  }
  for (const char character : value) {
    const bool valid =
        (character >= 'a' && character <= 'z') ||
        (character >= '0' && character <= '9') ||
        character == '_' || character == '-' || character == '.';
    if (!valid) {
      return false;
    }
  }
  return true;
}

static std::vector<std::string> parse_branch_ids(const gchar* raw) {
  if (raw == nullptr || raw[0] == '\0') {
    throw std::runtime_error("branch-ids must not be empty");
  }
  std::vector<std::string> branches;
  std::unordered_set<std::string> unique;
  const std::string value(raw);
  std::size_t begin = 0;
  while (begin <= value.size()) {
    const std::size_t separator = value.find(',', begin);
    const std::string branch =
        value.substr(begin, separator == std::string::npos ? std::string::npos : separator - begin);
    if (!valid_branch_id(branch) || !unique.insert(branch).second) {
      throw std::runtime_error("branch-ids must be a unique canonical comma-separated list");
    }
    branches.push_back(branch);
    if (separator == std::string::npos) {
      break;
    }
    begin = separator + 1;
  }
  return branches;
}

static void free_item(PrefixQueueItem* item) {
  if (item == nullptr) {
    return;
  }
  gst_mini_object_unref(item->object);
  g_free(item);
}

static void clear_items_locked(GstVastCheckpointPrefixQueue* self) {
  while (!g_queue_is_empty(&self->items)) {
    free_item(static_cast<PrefixQueueItem*>(g_queue_pop_head(&self->items)));
  }
  self->queued_buffers = 0;
}

static gboolean start_runtime(GstVastCheckpointPrefixQueue* self) {
  try {
    if (self->max_buffers == 0) {
      throw std::runtime_error("max-buffers must be positive");
    }
    delete self->branches;
    self->branches = new std::vector<std::string>(parse_branch_ids(self->branch_ids));
    delete self->emitter;
    self->emitter = new vast::CheckpointAnalyticsTerminalEmitter(
        vast::CheckpointAnalyticsTerminalEmitter::from_environment());
  } catch (const std::exception& exc) {
    GST_ELEMENT_ERROR(
        self,
        RESOURCE,
        SETTINGS,
        ("checkpoint prefix queue configuration is invalid"),
        ("%s", exc.what()));
    return FALSE;
  }

  g_mutex_lock(&self->lock);
  clear_items_locked(self);
  self->flushing = FALSE;
  self->downstream_flow = GST_FLOW_OK;
  self->running = TRUE;
  g_mutex_unlock(&self->lock);
  return TRUE;
}

static void stop_runtime(GstVastCheckpointPrefixQueue* self) {
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
  delete self->branches;
  self->branches = nullptr;
}

static void queue_task(gpointer data) {
  GstVastCheckpointPrefixQueue* self = GST_VAST_CHECKPOINT_PREFIX_QUEUE(data);
  PrefixQueueItem* item = nullptr;
  g_mutex_lock(&self->lock);
  while (self->running && !self->flushing && g_queue_is_empty(&self->items)) {
    g_cond_wait(&self->condition, &self->lock);
  }
  if (self->running && !self->flushing) {
    item = static_cast<PrefixQueueItem*>(g_queue_pop_head(&self->items));
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
  GstVastCheckpointPrefixQueue* self = GST_VAST_CHECKPOINT_PREFIX_QUEUE(parent);
  if (!GST_BUFFER_PTS_IS_VALID(buffer)) {
    gst_buffer_unref(buffer);
    GST_ELEMENT_ERROR(
        self,
        STREAM,
        FORMAT,
        ("checkpoint prefix queue input buffer has no valid transport PTS"),
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
    PrefixQueueItem* item = g_new0(PrefixQueueItem, 1);
    item->object = GST_MINI_OBJECT_CAST(buffer);
    item->is_buffer = TRUE;
    g_queue_push_tail(&self->items, item);
    ++self->queued_buffers;
    g_cond_signal(&self->condition);
    g_mutex_unlock(&self->lock);
    return GST_FLOW_OK;
  }
  const std::vector<std::string> branches = *self->branches;
  g_mutex_unlock(&self->lock);

  const std::uint64_t transport_pts_ns = GST_BUFFER_PTS(buffer);
  gst_buffer_unref(buffer);
  try {
    for (const std::string& branch : branches) {
      vast::CheckpointAnalyticsTerminal terminal;
      terminal.transport_pts_ns = transport_pts_ns;
      terminal.status = vast::CheckpointAnalyticsTerminalStatus::kDrop;
      terminal.objects = 0;
      terminal.branch_id = branch;
      terminal.terminal_reason = "native_postdecode_preprocess_queue_full_drop_newest";
      terminal.detector = "runtime-bound-postdecode-drop";
      terminal.backend = "runtime-bound-postdecode-drop";
      self->emitter->emit(terminal);
    }
  } catch (const std::exception& exc) {
    GST_ELEMENT_ERROR(
        self,
        RESOURCE,
        WRITE,
        ("failed to emit native post-decode prefix drops"),
        ("%s", exc.what()));
    return GST_FLOW_ERROR;
  }
  return GST_FLOW_OK;
}

static gboolean sink_event(GstPad*, GstObject* parent, GstEvent* event) {
  GstVastCheckpointPrefixQueue* self = GST_VAST_CHECKPOINT_PREFIX_QUEUE(parent);
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
  PrefixQueueItem* item = g_new0(PrefixQueueItem, 1);
  item->object = GST_MINI_OBJECT_CAST(event);
  item->is_buffer = FALSE;
  g_queue_push_tail(&self->items, item);
  g_cond_signal(&self->condition);
  g_mutex_unlock(&self->lock);
  return TRUE;
}

static gboolean src_event(GstPad*, GstObject* parent, GstEvent* event) {
  return gst_pad_push_event(GST_VAST_CHECKPOINT_PREFIX_QUEUE(parent)->sink_pad, event);
}

static gboolean sink_query(GstPad*, GstObject* parent, GstQuery* query) {
  return gst_pad_peer_query(GST_VAST_CHECKPOINT_PREFIX_QUEUE(parent)->src_pad, query);
}

static gboolean src_query(GstPad*, GstObject* parent, GstQuery* query) {
  return gst_pad_peer_query(GST_VAST_CHECKPOINT_PREFIX_QUEUE(parent)->sink_pad, query);
}

static GstStateChangeReturn change_state(GstElement* element, GstStateChange transition) {
  GstVastCheckpointPrefixQueue* self = GST_VAST_CHECKPOINT_PREFIX_QUEUE(element);
  if (transition == GST_STATE_CHANGE_READY_TO_PAUSED) {
    if (!start_runtime(self) || !gst_pad_start_task(self->src_pad, queue_task, self, nullptr)) {
      stop_runtime(self);
      return GST_STATE_CHANGE_FAILURE;
    }
  } else if (transition == GST_STATE_CHANGE_PAUSED_TO_READY) {
    stop_runtime(self);
  }

  const GstStateChangeReturn result =
      GST_ELEMENT_CLASS(gst_vast_checkpoint_prefix_queue_parent_class)->change_state(element, transition);
  if (result == GST_STATE_CHANGE_FAILURE && transition == GST_STATE_CHANGE_READY_TO_PAUSED) {
    stop_runtime(self);
  }
  return result;
}

static void set_property(GObject* object, guint prop_id, const GValue* value, GParamSpec* pspec) {
  GstVastCheckpointPrefixQueue* self = GST_VAST_CHECKPOINT_PREFIX_QUEUE(object);
  switch (prop_id) {
    case PROP_BRANCH_IDS:
      g_free(self->branch_ids);
      self->branch_ids = g_value_dup_string(value);
      break;
    case PROP_MAX_BUFFERS:
      self->max_buffers = g_value_get_uint(value);
      break;
    default:
      G_OBJECT_WARN_INVALID_PROPERTY_ID(object, prop_id, pspec);
      break;
  }
}

static void get_property(GObject* object, guint prop_id, GValue* value, GParamSpec* pspec) {
  GstVastCheckpointPrefixQueue* self = GST_VAST_CHECKPOINT_PREFIX_QUEUE(object);
  switch (prop_id) {
    case PROP_BRANCH_IDS:
      g_value_set_string(value, self->branch_ids);
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
  GstVastCheckpointPrefixQueue* self = GST_VAST_CHECKPOINT_PREFIX_QUEUE(object);
  stop_runtime(self);
  g_free(self->branch_ids);
  g_mutex_clear(&self->lock);
  g_cond_clear(&self->condition);
  G_OBJECT_CLASS(gst_vast_checkpoint_prefix_queue_parent_class)->finalize(object);
}

static void gst_vast_checkpoint_prefix_queue_init(GstVastCheckpointPrefixQueue* self) {
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
  self->branches = nullptr;
  self->emitter = nullptr;
}

static void gst_vast_checkpoint_prefix_queue_class_init(GstVastCheckpointPrefixQueueClass* klass) {
  GObjectClass* object_class = G_OBJECT_CLASS(klass);
  GstElementClass* element_class = GST_ELEMENT_CLASS(klass);
  object_class->set_property = set_property;
  object_class->get_property = get_property;
  object_class->finalize = finalize;
  element_class->change_state = change_state;

  properties[PROP_BRANCH_IDS] = g_param_spec_string(
      "branch-ids", "Branch IDs",
      "Unique canonical comma-separated branches terminated by a prefix drop", nullptr,
      static_cast<GParamFlags>(G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS));
  properties[PROP_MAX_BUFFERS] = g_param_spec_uint(
      "max-buffers", "Maximum queued buffers",
      "Number of decoded raw frames waiting before preprocess; a full queue drops the newest frame",
      0, G_MAXUINT, 0,
      static_cast<GParamFlags>(G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS));
  g_object_class_install_properties(object_class, N_PROPERTIES, properties);

  gst_element_class_set_static_metadata(
      element_class,
      "VAST bounded checkpoint prefix queue",
      "Generic/Queue/Video",
      "Drops exact-PTS decoded raw frames before preprocess and terminalizes every branch",
      "VAST benchmark");
  gst_element_class_add_static_pad_template(element_class, &sink_template);
  gst_element_class_add_static_pad_template(element_class, &src_template);
}

static gboolean plugin_init(GstPlugin* plugin) {
  return gst_element_register(
      plugin,
      "vastcheckpointprefixqueue",
      GST_RANK_NONE,
      GST_TYPE_VAST_CHECKPOINT_PREFIX_QUEUE);
}

GST_PLUGIN_DEFINE(
    GST_VERSION_MAJOR,
    GST_VERSION_MINOR,
    vastcheckpointprefixqueue,
    "VAST bounded native post-decode checkpoint prefix queue",
    plugin_init,
    "1.0.0",
    "LGPL",
    "VAST",
    "https://example.invalid/vast")
