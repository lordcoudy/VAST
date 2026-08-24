#include "checkpoint_gstreamer_analytics_bridge.hpp"

#include <cstdint>
#include <exception>
#include <iostream>
#include <mutex>
#include <stdexcept>
#include <string>

namespace {

void require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}

GstPad* make_linked_source(GstPad* sink, GstVideoInfo* info, GstVideoFormat format) {
  require(gst_video_info_set_format(info, format, 4, 2), "failed to create video info");
  GstCaps* caps = gst_video_info_to_caps(info);
  require(caps != nullptr, "failed to create caps");
  GstPad* source = gst_pad_new("analytics_source", GST_PAD_SRC);
  require(source != nullptr, "failed to create source pad");
  require(gst_pad_set_active(source, TRUE), "failed to activate source pad");
  require(gst_pad_link(source, sink) == GST_PAD_LINK_OK, "failed to link test pads");
  require(gst_pad_push_event(source, gst_event_new_caps(caps)), "failed to install negotiated caps");
  gst_caps_unref(caps);
  return source;
}

}  // namespace

int main(int argc, char** argv) {
  gst_init(&argc, &argv);
  GstPad* pad = gst_pad_new("analytics_sink", GST_PAD_SINK);
  if (pad == nullptr) return 2;
  GstBuffer* buffer = nullptr;
  GstPad* source = nullptr;
  try {
    require(gst_pad_set_active(pad, TRUE), "failed to activate pad");
    GstVideoInfo info{};
    source = make_linked_source(pad, &info, GST_VIDEO_FORMAT_BGR);
    buffer = gst_buffer_new_allocate(nullptr, info.size, nullptr);
    require(buffer != nullptr, "failed to allocate frame");

    GstVideoFrame writable{};
    require(
        gst_video_frame_map(&writable, &info, buffer, GST_MAP_WRITE),
        "failed to map writable frame");
    const gint stride = GST_VIDEO_FRAME_PLANE_STRIDE(&writable, 0);
    require(stride >= 12, "unexpected packed BGR stride");
    auto* plane = static_cast<std::uint8_t*>(GST_VIDEO_FRAME_PLANE_DATA(&writable, 0));
    for (guint row = 0; row < 2; ++row) {
      for (gint column = 0; column < stride; ++column) {
        plane[row * stride + column] = static_cast<std::uint8_t>(row * stride + column);
      }
    }
    gst_video_frame_unmap(&writable);

    const vast::CheckpointGstreamerAnalyticsFrame mapped =
        vast::map_checkpoint_gstreamer_analytics_frame(pad, buffer);
    require(mapped.format == "BGR", "negotiated format drifted");
    require(mapped.width == 4 && mapped.height == 2, "negotiated geometry drifted");
    require(mapped.stride == static_cast<std::uint64_t>(stride), "negotiated stride drifted");
    require(mapped.payload.size() == static_cast<std::size_t>(stride * 2), "payload size drifted");
    for (std::size_t index = 0; index < mapped.payload.size(); ++index) {
      require(mapped.payload[index] == static_cast<std::uint8_t>(index), "row bytes drifted");
    }

    vast::CheckpointAnalyticsExecutionResult result;
    result.branch = "damage";
    result.terminal_status = "completed";
    result.terminal_reason = "native_tensorrt_inference_completed";
    result.objects = 3;
    result.detector = "damage-resnet50-v1";
    result.backend = "cuda-tensorrt:sidecar;device=NVIDIA_CUDA:0";
    const vast::CheckpointAnalyticsTerminal terminal =
        vast::checkpoint_terminal_from_validated_execution(result, 90000, "damage");
    require(terminal.transport_pts_ns == 90000, "terminal PTS drifted");
    require(terminal.status == vast::CheckpointAnalyticsTerminalStatus::kCompleted,
            "terminal status drifted");
    require(terminal.objects == 3 && terminal.branch_id == "damage", "terminal binding drifted");

    std::mutex runtime_mutex;
    std::unique_lock<std::mutex> runtime_lock(runtime_mutex);
    bool rejected_locked_external_call = false;
    try {
      (void)vast::checkpoint_external_call(runtime_lock, []() { return 1; });
    } catch (const std::exception&) {
      rejected_locked_external_call = true;
    }
    require(rejected_locked_external_call, "external call was allowed under the runtime mutex");
    runtime_lock.unlock();
    require(
        vast::checkpoint_external_call(runtime_lock, [&runtime_mutex]() {
          const bool acquired = runtime_mutex.try_lock();
          if (acquired) runtime_mutex.unlock();
          return acquired;
        }),
        "external call could not acquire the released runtime mutex");
    require(
        vast::checkpoint_external_execution_probe_return() == GST_PAD_PROBE_DROP,
        "externally completed frame would reach the legacy detector terminal");

    bool rejected = false;
    result.terminal_status = "drop";
    try {
      (void)vast::checkpoint_terminal_from_validated_execution(result, 90000, "damage");
    } catch (const std::exception&) {
      rejected = true;
    }
    require(rejected, "unvalidated terminal status was accepted");

    require(gst_pad_unlink(source, pad), "failed to unlink packed test pads");
    gst_object_unref(source);
    source = nullptr;
    require(gst_pad_set_active(pad, FALSE), "failed to deactivate sink pad");
    require(gst_pad_set_active(pad, TRUE), "failed to reactivate sink pad");
    GstVideoInfo planar{};
    source = make_linked_source(pad, &planar, GST_VIDEO_FORMAT_I420);
    rejected = false;
    try {
      (void)vast::map_checkpoint_gstreamer_analytics_frame(pad, buffer);
    } catch (const std::exception&) {
      rejected = true;
    }
    require(rejected, "planar format was accepted as packed RGB/BGR");
  } catch (const std::exception& exc) {
    std::cerr << exc.what() << '\n';
    if (buffer != nullptr) gst_buffer_unref(buffer);
    if (source != nullptr) gst_object_unref(source);
    gst_object_unref(pad);
    return 1;
  }
  if (buffer != nullptr) gst_buffer_unref(buffer);
  if (source != nullptr) gst_object_unref(source);
  gst_object_unref(pad);
  return 0;
}
