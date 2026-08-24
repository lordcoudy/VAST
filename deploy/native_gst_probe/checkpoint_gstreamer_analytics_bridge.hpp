#pragma once

#include "checkpoint_analytics_execution_client.hpp"
#include "checkpoint_analytics_terminal_transport.hpp"

#include <gst/gst.h>
#include <gst/video/video.h>

#include <cstdint>
#include <cstring>
#include <limits>
#include <mutex>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace vast {

struct CheckpointGstreamerAnalyticsFrame {
  std::string format;
  std::uint64_t width = 0;
  std::uint64_t height = 0;
  std::uint64_t stride = 0;
  std::vector<std::uint8_t> payload;
};

template <typename Callable>
decltype(auto) checkpoint_external_call(
    std::unique_lock<std::mutex>& runtime_lock,
    Callable&& callable) {
  if (runtime_lock.owns_lock()) {
    throw std::runtime_error(
        "checkpoint external call attempted while the runtime mutex is held");
  }
  return std::forward<Callable>(callable)();
}

inline GstPadProbeReturn checkpoint_external_execution_probe_return() {
  // The sidecar already emitted the one authoritative terminal. Never let the
  // same buffer reach the legacy in-process detector/terminal chain.
  return GST_PAD_PROBE_DROP;
}

inline CheckpointGstreamerAnalyticsFrame map_checkpoint_gstreamer_analytics_frame(
    GstPad* pad,
    GstBuffer* buffer) {
  if (pad == nullptr || buffer == nullptr) {
    throw std::runtime_error("GStreamer analytics frame pad/buffer is missing");
  }
  GstCaps* caps = gst_pad_get_current_caps(pad);
  if (caps == nullptr || gst_caps_is_empty(caps) || gst_caps_is_any(caps)) {
    if (caps != nullptr) gst_caps_unref(caps);
    throw std::runtime_error("GStreamer analytics frame has no fixed negotiated caps");
  }
  GstVideoInfo info{};
  const bool parsed = gst_video_info_from_caps(&info, caps) != FALSE;
  gst_caps_unref(caps);
  if (!parsed || GST_VIDEO_INFO_N_PLANES(&info) != 1) {
    throw std::runtime_error("GStreamer analytics frame caps are not one packed video plane");
  }
  const GstVideoFormat negotiated = GST_VIDEO_INFO_FORMAT(&info);
  const char* format = nullptr;
  if (negotiated == GST_VIDEO_FORMAT_BGR) {
    format = "BGR";
  } else if (negotiated == GST_VIDEO_FORMAT_RGB) {
    format = "RGB";
  } else {
    throw std::runtime_error("GStreamer analytics frame format is not packed RGB/BGR");
  }
  GstVideoFrame frame{};
  if (!gst_video_frame_map(&frame, &info, buffer, GST_MAP_READ)) {
    throw std::runtime_error("failed to map negotiated GStreamer analytics frame");
  }
  try {
    const guint width = GST_VIDEO_FRAME_WIDTH(&frame);
    const guint height = GST_VIDEO_FRAME_HEIGHT(&frame);
    const gint signed_stride = GST_VIDEO_FRAME_PLANE_STRIDE(&frame, 0);
    auto* plane = static_cast<const std::uint8_t*>(GST_VIDEO_FRAME_PLANE_DATA(&frame, 0));
    if (width == 0 || height == 0 || signed_stride <= 0 || plane == nullptr ||
        static_cast<std::uint64_t>(signed_stride) < static_cast<std::uint64_t>(width) * 3ULL ||
        static_cast<std::uint64_t>(height) >
            std::numeric_limits<std::size_t>::max() / static_cast<std::uint64_t>(signed_stride)) {
      throw std::runtime_error("GStreamer analytics frame geometry/stride is invalid");
    }
    const std::size_t bytes =
        static_cast<std::size_t>(height) * static_cast<std::size_t>(signed_stride);
    std::vector<std::uint8_t> payload(bytes);
    for (guint row = 0; row < height; ++row) {
      std::memcpy(
          payload.data() + static_cast<std::size_t>(row) * signed_stride,
          plane + static_cast<std::size_t>(row) * signed_stride,
          static_cast<std::size_t>(signed_stride));
    }
    gst_video_frame_unmap(&frame);
    return {
        format,
        static_cast<std::uint64_t>(width),
        static_cast<std::uint64_t>(height),
        static_cast<std::uint64_t>(signed_stride),
        std::move(payload),
    };
  } catch (...) {
    gst_video_frame_unmap(&frame);
    throw;
  }
}

inline CheckpointAnalyticsTerminal checkpoint_terminal_from_validated_execution(
    const CheckpointAnalyticsExecutionResult& result,
    std::uint64_t transport_pts_ns,
    const std::string& expected_branch) {
  if (transport_pts_ns == GST_CLOCK_TIME_NONE || result.branch != expected_branch ||
      result.terminal_status != "completed" || result.terminal_reason.empty() ||
      result.detector.empty() || result.backend.empty() ||
      result.detector == "identity" || result.backend == "identity") {
    throw std::runtime_error("analytics execution result cannot become a branch terminal");
  }
  CheckpointAnalyticsTerminal terminal;
  terminal.transport_pts_ns = transport_pts_ns;
  terminal.status = CheckpointAnalyticsTerminalStatus::kCompleted;
  terminal.objects = result.objects;
  terminal.branch_id = expected_branch;
  terminal.terminal_reason = result.terminal_reason;
  terminal.detector = result.detector;
  terminal.backend = result.backend;
  return terminal;
}

}  // namespace vast
