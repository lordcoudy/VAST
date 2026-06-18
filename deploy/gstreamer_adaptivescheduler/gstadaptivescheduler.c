#include <gst/base/gstbasetransform.h>
#include <gst/gst.h>
#include <gst/video/video.h>

#ifndef PACKAGE
#define PACKAGE "vast"
#endif

#define GST_TYPE_ADAPTIVE_SCHEDULER (gst_adaptive_scheduler_get_type())
#define GST_ADAPTIVE_SCHEDULER(obj) \
  (G_TYPE_CHECK_INSTANCE_CAST((obj), GST_TYPE_ADAPTIVE_SCHEDULER, GstAdaptiveScheduler))

typedef struct _GstAdaptiveScheduler GstAdaptiveScheduler;
typedef struct _GstAdaptiveSchedulerClass GstAdaptiveSchedulerClass;

struct _GstAdaptiveScheduler {
  GstBaseTransform parent;
  GstVideoInfo info;
  gboolean have_info;
  gint workload;
  gint tiles;
  gdouble threshold;
};

struct _GstAdaptiveSchedulerClass {
  GstBaseTransformClass parent_class;
};

G_DEFINE_TYPE(GstAdaptiveScheduler, gst_adaptive_scheduler, GST_TYPE_BASE_TRANSFORM)

enum {
  PROP_0,
  PROP_WORKLOAD,
  PROP_TILES,
  PROP_THRESHOLD,
  N_PROPERTIES,
};

typedef struct {
  guint x;
  guint y;
  guint w;
  guint h;
} DetectionBox;

static GParamSpec* properties[N_PROPERTIES] = {NULL};

static GstStaticPadTemplate sink_template = GST_STATIC_PAD_TEMPLATE(
    "sink",
    GST_PAD_SINK,
    GST_PAD_ALWAYS,
    GST_STATIC_CAPS(GST_VIDEO_CAPS_MAKE("{ RGB, BGR, RGBA, BGRA, GRAY8 }")));

static GstStaticPadTemplate src_template = GST_STATIC_PAD_TEMPLATE(
    "src",
    GST_PAD_SRC,
    GST_PAD_ALWAYS,
    GST_STATIC_CAPS(GST_VIDEO_CAPS_MAKE("{ RGB, BGR, RGBA, BGRA, GRAY8 }")));

static guint8 sample_luma(GstVideoFrame* frame, GstVideoFormat format, guint x, guint y) {
  guint8* plane = GST_VIDEO_FRAME_PLANE_DATA(frame, 0);
  gint stride = GST_VIDEO_FRAME_PLANE_STRIDE(frame, 0);
  guint8* p = plane + y * stride;
  guint r = 0;
  guint g = 0;
  guint b = 0;

  switch (format) {
    case GST_VIDEO_FORMAT_RGB:
      p += x * 3;
      r = p[0];
      g = p[1];
      b = p[2];
      break;
    case GST_VIDEO_FORMAT_BGR:
      p += x * 3;
      b = p[0];
      g = p[1];
      r = p[2];
      break;
    case GST_VIDEO_FORMAT_RGBA:
      p += x * 4;
      r = p[0];
      g = p[1];
      b = p[2];
      break;
    case GST_VIDEO_FORMAT_BGRA:
      p += x * 4;
      b = p[0];
      g = p[1];
      r = p[2];
      break;
    case GST_VIDEO_FORMAT_GRAY8:
      return p[x];
    default:
      return 0;
  }

  return (guint8)((299u * r + 587u * g + 114u * b) / 1000u);
}

static gboolean gst_adaptive_scheduler_set_caps(
    GstBaseTransform* transform,
    GstCaps* incaps,
    GstCaps* outcaps) {
  (void)outcaps;
  GstAdaptiveScheduler* self = GST_ADAPTIVE_SCHEDULER(transform);
  self->have_info = gst_video_info_from_caps(&self->info, incaps);
  return self->have_info;
}

static GstFlowReturn gst_adaptive_scheduler_transform_ip(GstBaseTransform* transform, GstBuffer* buffer) {
  GstAdaptiveScheduler* self = GST_ADAPTIVE_SCHEDULER(transform);
  GstVideoFrame frame;
  DetectionBox detections[64];
  guint detection_count = 0;

  if (!self->have_info) {
    return GST_FLOW_OK;
  }
  if (!gst_video_frame_map(&frame, &self->info, buffer, GST_MAP_READ)) {
    return GST_FLOW_OK;
  }

  const guint width = GST_VIDEO_INFO_WIDTH(&self->info);
  const guint height = GST_VIDEO_INFO_HEIGHT(&self->info);
  const GstVideoFormat format = GST_VIDEO_INFO_FORMAT(&self->info);
  const guint tiles = (guint)CLAMP(self->tiles, 1, 64);
  const guint tile_w = MAX(1u, (width + tiles - 1u) / tiles);
  const guint tile_h = MAX(1u, (height + tiles - 1u) / tiles);
  const gint workload = CLAMP(self->workload, 1, 100);

  for (guint ty = 0; ty < tiles; ++ty) {
    const guint y0 = ty * tile_h;
    const guint y1 = MIN(height, y0 + tile_h);
    if (y0 >= height) {
      continue;
    }
    for (guint tx = 0; tx < tiles; ++tx) {
      const guint x0 = tx * tile_w;
      const guint x1 = MIN(width, x0 + tile_w);
      if (x0 >= width) {
        continue;
      }

      const guint step_y = MAX(1u, (y1 - y0) / 8u);
      const guint step_x = MAX(1u, (x1 - x0) / 8u);
      gdouble sum = 0.0;
      guint samples = 0;

      for (gint pass = 0; pass < workload; ++pass) {
        for (guint y = y0; y < y1; y += step_y) {
          for (guint x = x0; x < x1; x += step_x) {
            sum += sample_luma(&frame, format, x, y);
            ++samples;
          }
        }
      }

      if (samples > 0 && (sum / (gdouble)samples) >= self->threshold && detection_count < G_N_ELEMENTS(detections)) {
        detections[detection_count++] = (DetectionBox){
            x0,
            y0,
            x1 - x0,
            y1 - y0,
        };
      }
    }
  }

  gst_video_frame_unmap(&frame);

  if (gst_buffer_is_writable(buffer)) {
    for (guint i = 0; i < detection_count; ++i) {
      gst_buffer_add_video_region_of_interest_meta(
          buffer,
          "adaptivescheduler-object",
          detections[i].x,
          detections[i].y,
          detections[i].w,
          detections[i].h);
    }
  }

  return GST_FLOW_OK;
}

static void gst_adaptive_scheduler_set_property(
    GObject* object,
    guint prop_id,
    const GValue* value,
    GParamSpec* pspec) {
  GstAdaptiveScheduler* self = GST_ADAPTIVE_SCHEDULER(object);

  switch (prop_id) {
    case PROP_WORKLOAD:
      self->workload = g_value_get_int(value);
      break;
    case PROP_TILES:
      self->tiles = g_value_get_int(value);
      break;
    case PROP_THRESHOLD:
      self->threshold = g_value_get_double(value);
      break;
    default:
      G_OBJECT_WARN_INVALID_PROPERTY_ID(object, prop_id, pspec);
      break;
  }
}

static void gst_adaptive_scheduler_get_property(
    GObject* object,
    guint prop_id,
    GValue* value,
    GParamSpec* pspec) {
  GstAdaptiveScheduler* self = GST_ADAPTIVE_SCHEDULER(object);

  switch (prop_id) {
    case PROP_WORKLOAD:
      g_value_set_int(value, self->workload);
      break;
    case PROP_TILES:
      g_value_set_int(value, self->tiles);
      break;
    case PROP_THRESHOLD:
      g_value_set_double(value, self->threshold);
      break;
    default:
      G_OBJECT_WARN_INVALID_PROPERTY_ID(object, prop_id, pspec);
      break;
  }
}

static void gst_adaptive_scheduler_init(GstAdaptiveScheduler* self) {
  gst_video_info_init(&self->info);
  self->have_info = FALSE;
  self->workload = 5;
  self->tiles = 8;
  self->threshold = 180.0;
  gst_base_transform_set_in_place(GST_BASE_TRANSFORM(self), TRUE);
  gst_base_transform_set_passthrough(GST_BASE_TRANSFORM(self), FALSE);
}

static void gst_adaptive_scheduler_class_init(GstAdaptiveSchedulerClass* klass) {
  GObjectClass* object_class = G_OBJECT_CLASS(klass);
  GstElementClass* element_class = GST_ELEMENT_CLASS(klass);
  GstBaseTransformClass* transform_class = GST_BASE_TRANSFORM_CLASS(klass);

  object_class->set_property = gst_adaptive_scheduler_set_property;
  object_class->get_property = gst_adaptive_scheduler_get_property;

  properties[PROP_WORKLOAD] = g_param_spec_int(
      "workload",
      "Workload",
      "Deterministic CPU scan multiplier used by the custom detection stage",
      1,
      100,
      5,
      G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS);
  properties[PROP_TILES] = g_param_spec_int(
      "tiles",
      "Tiles",
      "Number of horizontal and vertical tiles scanned for bright-region detections",
      1,
      64,
      8,
      G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS);
  properties[PROP_THRESHOLD] = g_param_spec_double(
      "threshold",
      "Threshold",
      "Mean luma threshold for emitting GstVideoRegionOfInterestMeta",
      0.0,
      255.0,
      180.0,
      G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS);
  g_object_class_install_properties(object_class, N_PROPERTIES, properties);

  gst_element_class_set_static_metadata(
      element_class,
      "VAST adaptive scheduler custom detection stage",
      "Filter/Effect/Video",
      "Runs deterministic tile-based video analysis and emits ROI metadata",
      "VAST benchmark");
  gst_element_class_add_static_pad_template(element_class, &sink_template);
  gst_element_class_add_static_pad_template(element_class, &src_template);

  transform_class->set_caps = GST_DEBUG_FUNCPTR(gst_adaptive_scheduler_set_caps);
  transform_class->transform_ip = GST_DEBUG_FUNCPTR(gst_adaptive_scheduler_transform_ip);
}

static gboolean plugin_init(GstPlugin* plugin) {
  return gst_element_register(plugin, "adaptivescheduler", GST_RANK_NONE, GST_TYPE_ADAPTIVE_SCHEDULER);
}

GST_PLUGIN_DEFINE(
    GST_VERSION_MAJOR,
    GST_VERSION_MINOR,
    adaptivescheduler,
    "VAST adaptive scheduler custom GStreamer element",
    plugin_init,
    "1.0.0",
    "LGPL",
    "VAST",
    "https://example.invalid/vast")
