#include <gst/gst.h>

#ifndef PACKAGE
#define PACKAGE "vast"
#endif

// One waiting RGB buffer, plus the buffer currently owned by downstream.
// Unlike queue::overrun, buffer-dropped reports an irrevocable decision and
// carries the discarded buffer's identity. Reporting must be acknowledged.
typedef struct {
  GstMiniObject* object;
  gboolean is_buffer;
} BranchQueueItem;

typedef struct _GstVastCheckpointBranchQueue {
  GstElement parent;
  GstPad* sink_pad;
  GstPad* src_pad;
  GMutex lock;
  GCond condition;
  GQueue items;
  guint max_buffers;
  guint queued_buffers;
  gboolean running;
  gboolean flushing;
  gboolean eos;
  GstFlowReturn downstream_flow;
} GstVastCheckpointBranchQueue;

typedef struct _GstVastCheckpointBranchQueueClass {
  GstElementClass parent_class;
} GstVastCheckpointBranchQueueClass;

#define GST_TYPE_VAST_CHECKPOINT_BRANCH_QUEUE (gst_vast_checkpoint_branch_queue_get_type())
#define GST_VAST_CHECKPOINT_BRANCH_QUEUE(obj) \
  (G_TYPE_CHECK_INSTANCE_CAST((obj), GST_TYPE_VAST_CHECKPOINT_BRANCH_QUEUE, GstVastCheckpointBranchQueue))

G_DEFINE_TYPE(GstVastCheckpointBranchQueue, gst_vast_checkpoint_branch_queue, GST_TYPE_ELEMENT)

enum { PROP_0, PROP_MAX_BUFFERS, PROP_CURRENT_LEVEL_BUFFERS, PROP_DROP_POLICY, N_PROPERTIES };
enum { SIGNAL_BUFFER_DROPPED, N_SIGNALS };
static GParamSpec* properties[N_PROPERTIES] = {nullptr};
static guint signals[N_SIGNALS] = {0};
static GstStaticPadTemplate sink_template = GST_STATIC_PAD_TEMPLATE(
    "sink", GST_PAD_SINK, GST_PAD_ALWAYS, GST_STATIC_CAPS("video/x-raw,format=RGB"));
static GstStaticPadTemplate src_template = GST_STATIC_PAD_TEMPLATE(
    "src", GST_PAD_SRC, GST_PAD_ALWAYS, GST_STATIC_CAPS("video/x-raw,format=RGB"));

static void clear_items_locked(GstVastCheckpointBranchQueue* self) {
  while (!g_queue_is_empty(&self->items)) {
    auto* item = static_cast<BranchQueueItem*>(g_queue_pop_head(&self->items));
    gst_mini_object_unref(item->object);
    g_free(item);
  }
  self->queued_buffers = 0;
}

static void stop_runtime(GstVastCheckpointBranchQueue* self) {
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
}

static void queue_task(gpointer data) {
  auto* self = GST_VAST_CHECKPOINT_BRANCH_QUEUE(data);
  BranchQueueItem* item = nullptr;
  g_mutex_lock(&self->lock);
  while (self->running && !self->flushing && g_queue_is_empty(&self->items)) {
    g_cond_wait(&self->condition, &self->lock);
  }
  if (self->running && !self->flushing) {
    item = static_cast<BranchQueueItem*>(g_queue_pop_head(&self->items));
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
    flow = gst_pad_push(self->src_pad, GST_BUFFER_CAST(item->object));
  } else if (!gst_pad_push_event(self->src_pad, GST_EVENT_CAST(item->object))) {
    flow = GST_FLOW_ERROR;
  }
  g_free(item);
  if (flow != GST_FLOW_OK) {
    g_mutex_lock(&self->lock);
    self->downstream_flow = flow;
    clear_items_locked(self);
    g_mutex_unlock(&self->lock);
    if (flow != GST_FLOW_FLUSHING && flow != GST_FLOW_EOS) {
      GST_ELEMENT_ERROR(self, STREAM, FAILED,
          ("checkpoint branch queue downstream failed"), ("%s", gst_flow_get_name(flow)));
    }
    gst_pad_pause_task(self->src_pad);
  }
}

static GstFlowReturn sink_chain(GstPad*, GstObject* parent, GstBuffer* buffer) {
  auto* self = GST_VAST_CHECKPOINT_BRANCH_QUEUE(parent);
  if (!GST_BUFFER_PTS_IS_VALID(buffer)) {
    gst_buffer_unref(buffer);
    GST_ELEMENT_ERROR(self, STREAM, FORMAT,
        ("checkpoint branch queue buffer has no transport PTS"), (nullptr));
    return GST_FLOW_ERROR;
  }

  g_mutex_lock(&self->lock);
  GstFlowReturn flow = self->downstream_flow;
  if (!self->running || self->flushing) {
    flow = GST_FLOW_FLUSHING;
  } else if (self->eos) {
    flow = GST_FLOW_EOS;
  }
  if (flow != GST_FLOW_OK) {
    g_mutex_unlock(&self->lock);
    gst_buffer_unref(buffer);
    return flow;
  }
  if (self->queued_buffers < self->max_buffers) {
    auto* item = g_new0(BranchQueueItem, 1);
    item->object = GST_MINI_OBJECT_CAST(buffer);
    item->is_buffer = TRUE;
    g_queue_push_tail(&self->items, item);
    ++self->queued_buffers;
    g_cond_signal(&self->condition);
    g_mutex_unlock(&self->lock);
    return GST_FLOW_OK;
  }

  // The full-queue decision is final while still holding the capacity mutex.
  // A consumer draining during reporting cannot turn this discard into enqueue.
  const guint64 pts = GST_BUFFER_PTS(buffer);
  g_mutex_unlock(&self->lock);
  gst_buffer_unref(buffer);
  gboolean acknowledged = FALSE;
  g_signal_emit(self, signals[SIGNAL_BUFFER_DROPPED], 0, pts, &acknowledged);
  if (!acknowledged) {
    g_mutex_lock(&self->lock);
    self->downstream_flow = GST_FLOW_ERROR;
    clear_items_locked(self);
    g_mutex_unlock(&self->lock);
    GST_ELEMENT_ERROR(self, STREAM, FAILED,
        ("checkpoint branch queue drop was not acknowledged"),
        ("discarded transport PTS=%" G_GUINT64_FORMAT, pts));
    return GST_FLOW_ERROR;
  }
  return GST_FLOW_OK;
}

static gboolean sink_event(GstPad*, GstObject* parent, GstEvent* event) {
  auto* self = GST_VAST_CHECKPOINT_BRANCH_QUEUE(parent);
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
    self->eos = FALSE;
    self->downstream_flow = GST_FLOW_OK;
    const gboolean running = self->running;
    g_mutex_unlock(&self->lock);
    if (running && gst_pad_get_task_state(self->src_pad) != GST_TASK_STARTED) {
      gst_pad_start_task(self->src_pad, queue_task, self, nullptr);
    }
    return pushed;
  }
  if (!GST_EVENT_IS_SERIALIZED(event)) {
    return gst_pad_push_event(self->src_pad, event);
  }
  g_mutex_lock(&self->lock);
  if (!self->running || self->flushing || self->downstream_flow != GST_FLOW_OK) {
    g_mutex_unlock(&self->lock);
    gst_event_unref(event);
    return FALSE;
  }
  if (GST_EVENT_TYPE(event) == GST_EVENT_EOS) {
    self->eos = TRUE;
  }
  auto* item = g_new0(BranchQueueItem, 1);
  item->object = GST_MINI_OBJECT_CAST(event);
  item->is_buffer = FALSE;
  g_queue_push_tail(&self->items, item);
  g_cond_signal(&self->condition);
  g_mutex_unlock(&self->lock);
  return TRUE;
}

static gboolean src_event(GstPad*, GstObject* parent, GstEvent* event) {
  return gst_pad_push_event(GST_VAST_CHECKPOINT_BRANCH_QUEUE(parent)->sink_pad, event);
}
static gboolean sink_query(GstPad* pad, GstObject* parent, GstQuery* query) {
  if (GST_QUERY_TYPE(query) == GST_QUERY_CAPS || GST_QUERY_TYPE(query) == GST_QUERY_ACCEPT_CAPS) {
    return gst_pad_query_default(pad, parent, query);
  }
  return gst_pad_peer_query(GST_VAST_CHECKPOINT_BRANCH_QUEUE(parent)->src_pad, query);
}
static gboolean src_query(GstPad* pad, GstObject* parent, GstQuery* query) {
  if (GST_QUERY_TYPE(query) == GST_QUERY_CAPS || GST_QUERY_TYPE(query) == GST_QUERY_ACCEPT_CAPS) {
    return gst_pad_query_default(pad, parent, query);
  }
  return gst_pad_peer_query(GST_VAST_CHECKPOINT_BRANCH_QUEUE(parent)->sink_pad, query);
}

static GstStateChangeReturn change_state(GstElement* element, GstStateChange transition) {
  auto* self = GST_VAST_CHECKPOINT_BRANCH_QUEUE(element);
  if (transition == GST_STATE_CHANGE_READY_TO_PAUSED) {
    g_mutex_lock(&self->lock);
    const gboolean valid_capacity = self->max_buffers == 1;
    clear_items_locked(self);
    self->running = valid_capacity;
    self->flushing = FALSE;
    self->eos = FALSE;
    self->downstream_flow = GST_FLOW_OK;
    g_mutex_unlock(&self->lock);
    if (!valid_capacity) {
      GST_ELEMENT_ERROR(self, RESOURCE, SETTINGS,
          ("checkpoint branch queue requires exactly one waiting buffer"), (nullptr));
      return GST_STATE_CHANGE_FAILURE;
    }
    if (!gst_pad_start_task(self->src_pad, queue_task, self, nullptr)) {
      stop_runtime(self);
      return GST_STATE_CHANGE_FAILURE;
    }
  } else if (transition == GST_STATE_CHANGE_PAUSED_TO_READY) {
    stop_runtime(self);
  }
  const GstStateChangeReturn result =
      GST_ELEMENT_CLASS(gst_vast_checkpoint_branch_queue_parent_class)->change_state(element, transition);
  if (result == GST_STATE_CHANGE_FAILURE && transition == GST_STATE_CHANGE_READY_TO_PAUSED) {
    stop_runtime(self);
  }
  return result;
}

static void set_property(GObject* object, guint id, const GValue* value, GParamSpec* pspec) {
  auto* self = GST_VAST_CHECKPOINT_BRANCH_QUEUE(object);
  if (id != PROP_MAX_BUFFERS) {
    G_OBJECT_WARN_INVALID_PROPERTY_ID(object, id, pspec);
    return;
  }
  g_mutex_lock(&self->lock);
  if (!self->running) {
    self->max_buffers = g_value_get_uint(value);
  } else if (g_value_get_uint(value) != self->max_buffers) {
    g_mutex_unlock(&self->lock);
    GST_ELEMENT_ERROR(self, RESOURCE, SETTINGS,
        ("checkpoint branch queue capacity cannot change while running"), (nullptr));
    return;
  }
  g_mutex_unlock(&self->lock);
}

static void get_property(GObject* object, guint id, GValue* value, GParamSpec* pspec) {
  auto* self = GST_VAST_CHECKPOINT_BRANCH_QUEUE(object);
  g_mutex_lock(&self->lock);
  if (id == PROP_MAX_BUFFERS) {
    g_value_set_uint(value, self->max_buffers);
  } else if (id == PROP_CURRENT_LEVEL_BUFFERS) {
    g_value_set_uint(value, self->queued_buffers);
  } else if (id == PROP_DROP_POLICY) {
    g_value_set_string(value, "drop_newest");
  } else {
    G_OBJECT_WARN_INVALID_PROPERTY_ID(object, id, pspec);
  }
  g_mutex_unlock(&self->lock);
}

static void finalize(GObject* object) {
  auto* self = GST_VAST_CHECKPOINT_BRANCH_QUEUE(object);
  stop_runtime(self);
  g_mutex_clear(&self->lock);
  g_cond_clear(&self->condition);
  G_OBJECT_CLASS(gst_vast_checkpoint_branch_queue_parent_class)->finalize(object);
}

static void gst_vast_checkpoint_branch_queue_init(GstVastCheckpointBranchQueue* self) {
  self->sink_pad = gst_pad_new_from_static_template(&sink_template, "sink");
  self->src_pad = gst_pad_new_from_static_template(&src_template, "src");
  gst_pad_set_chain_function(self->sink_pad, GST_DEBUG_FUNCPTR(sink_chain));
  gst_pad_set_event_function(self->sink_pad, GST_DEBUG_FUNCPTR(sink_event));
  gst_pad_set_event_function(self->src_pad, GST_DEBUG_FUNCPTR(src_event));
  gst_pad_set_query_function(self->sink_pad, GST_DEBUG_FUNCPTR(sink_query));
  gst_pad_set_query_function(self->src_pad, GST_DEBUG_FUNCPTR(src_query));
  gst_element_add_pad(GST_ELEMENT(self), self->sink_pad);
  gst_element_add_pad(GST_ELEMENT(self), self->src_pad);
  g_mutex_init(&self->lock);
  g_cond_init(&self->condition);
  g_queue_init(&self->items);
  self->max_buffers = 1;
  self->downstream_flow = GST_FLOW_OK;
}

static void gst_vast_checkpoint_branch_queue_class_init(GstVastCheckpointBranchQueueClass* klass) {
  auto* object_class = G_OBJECT_CLASS(klass);
  auto* element_class = GST_ELEMENT_CLASS(klass);
  object_class->set_property = set_property;
  object_class->get_property = get_property;
  object_class->finalize = finalize;
  element_class->change_state = change_state;
  properties[PROP_MAX_BUFFERS] = g_param_spec_uint(
      "max-size-buffers", "Maximum queued buffers", "Must be exactly one waiting buffer",
      1, G_MAXUINT, 1, static_cast<GParamFlags>(G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS));
  properties[PROP_CURRENT_LEVEL_BUFFERS] = g_param_spec_uint(
      "current-level-buffers", "Queued buffers", "Waiting buffers excluding the active downstream buffer",
      0, G_MAXUINT, 0, static_cast<GParamFlags>(G_PARAM_READABLE | G_PARAM_STATIC_STRINGS));
  properties[PROP_DROP_POLICY] = g_param_spec_string(
      "drop-policy", "Drop policy", "Full queue discards the incoming buffer", "drop_newest",
      static_cast<GParamFlags>(G_PARAM_READABLE | G_PARAM_STATIC_STRINGS));
  g_object_class_install_properties(object_class, N_PROPERTIES, properties);
  signals[SIGNAL_BUFFER_DROPPED] = g_signal_new(
      "buffer-dropped", G_TYPE_FROM_CLASS(klass), G_SIGNAL_RUN_LAST,
      0, nullptr, nullptr, nullptr, G_TYPE_BOOLEAN, 1, G_TYPE_UINT64);
  gst_element_class_set_static_metadata(element_class,
      "VAST bounded checkpoint branch queue", "Generic/Queue/Video",
      "Reports exact discarded RGB buffer PTS after an atomic drop-newest decision", "VAST benchmark");
  gst_element_class_add_static_pad_template(element_class, &sink_template);
  gst_element_class_add_static_pad_template(element_class, &src_template);
}

static gboolean plugin_init(GstPlugin* plugin) {
  return gst_element_register(plugin, "vastcheckpointbranchqueue", GST_RANK_NONE,
                              GST_TYPE_VAST_CHECKPOINT_BRANCH_QUEUE);
}

GST_PLUGIN_DEFINE(GST_VERSION_MAJOR, GST_VERSION_MINOR, vastcheckpointbranchqueue,
    "VAST native checkpoint branch queue with exact drop acknowledgement", plugin_init,
    "1.0.0", "LGPL", "VAST", "https://example.invalid/vast")
