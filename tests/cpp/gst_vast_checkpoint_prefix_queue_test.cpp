#include <gst/gst.h>

#include <cerrno>
#include <cstdint>
#include <cstdlib>
#include <exception>
#include <iostream>
#include <set>
#include <string>
#include <vector>

#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>

#include "checkpoint_analytics_terminal_transport.hpp"

namespace {

struct DownstreamGate {
  GMutex lock;
  GCond condition;
  bool entered = false;
  bool released = false;
};

GstPadProbeReturn hold_downstream_buffer(GstPad*, GstPadProbeInfo*, gpointer data) {
  auto* gate = static_cast<DownstreamGate*>(data);
  g_mutex_lock(&gate->lock);
  gate->entered = true;
  g_cond_broadcast(&gate->condition);
  while (!gate->released) {
    g_cond_wait(&gate->condition, &gate->lock);
  }
  g_mutex_unlock(&gate->lock);
  return GST_PAD_PROBE_OK;
}

bool wait_for_downstream(DownstreamGate* gate) {
  const gint64 deadline = g_get_monotonic_time() + 2 * G_TIME_SPAN_SECOND;
  g_mutex_lock(&gate->lock);
  while (!gate->entered) {
    if (!g_cond_wait_until(&gate->condition, &gate->lock, deadline)) {
      g_mutex_unlock(&gate->lock);
      return false;
    }
  }
  g_mutex_unlock(&gate->lock);
  return true;
}

void release_downstream(DownstreamGate* gate) {
  g_mutex_lock(&gate->lock);
  gate->released = true;
  g_cond_broadcast(&gate->condition);
  g_mutex_unlock(&gate->lock);
}

GstBuffer* buffer_with_pts(std::uint64_t pts) {
  GstBuffer* buffer = gst_buffer_new_allocate(nullptr, 3, nullptr);
  GST_BUFFER_PTS(buffer) = pts;
  GST_BUFFER_DURATION(buffer) = GST_SECOND;
  return buffer;
}

bool run_overflow_case(const std::vector<std::string>& branches) {
  DownstreamGate gate;
  g_mutex_init(&gate.lock);
  g_cond_init(&gate.condition);
  int sockets[2] = {-1, -1};
  GstElement* pipeline = nullptr;
  GstPad* upstream = nullptr;
  GstPad* queue_sink = nullptr;
  GstPad* sink_pad = nullptr;
  std::string failure;

  try {
    do {
      if (::socketpair(AF_UNIX, SOCK_DGRAM, 0, sockets) != 0) {
        failure = "socketpair failed";
        break;
      }
      const timeval timeout = {2, 0};
      if (::setsockopt(sockets[1], SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) != 0) {
        failure = "receive timeout setup failed";
        break;
      }
      const std::string descriptor = std::to_string(sockets[0]);
      if (::setenv(vast::CheckpointAnalyticsTerminalTransport::kFdEnvironment,
                   descriptor.c_str(), 1) != 0) {
        failure = "terminal descriptor setup failed";
        break;
      }

      pipeline = gst_pipeline_new("prefix-queue-test");
      GstElement* queue = gst_element_factory_make("vastcheckpointprefixqueue", nullptr);
      GstElement* sink = gst_element_factory_make("fakesink", nullptr);
      if (pipeline == nullptr || queue == nullptr || sink == nullptr) {
        failure = "actual prefix queue plugin or fakesink is unavailable";
        break;
      }
      std::string branch_ids;
      for (const auto& branch : branches) {
        if (!branch_ids.empty()) {
          branch_ids += ',';
        }
        branch_ids += branch;
      }
      g_object_set(queue, "branch-ids", branch_ids.c_str(), "max-buffers", 1u, nullptr);
      g_object_set(sink, "async", FALSE, "sync", FALSE, nullptr);
      gst_bin_add_many(GST_BIN(pipeline), queue, sink, nullptr);
      if (!gst_element_link(queue, sink)) {
        failure = "prefix queue could not link to fakesink";
        break;
      }
      upstream = gst_pad_new("test-src", GST_PAD_SRC);
      queue_sink = gst_element_get_static_pad(queue, "sink");
      sink_pad = gst_element_get_static_pad(sink, "sink");
      if (upstream == nullptr || queue_sink == nullptr || sink_pad == nullptr) {
        failure = "test pad setup failed";
        break;
      }
      gst_pad_add_probe(sink_pad, GST_PAD_PROBE_TYPE_BUFFER,
                        hold_downstream_buffer, &gate, nullptr);
      if (!gst_pad_set_active(upstream, TRUE) ||
          gst_pad_link(upstream, queue_sink) != GST_PAD_LINK_OK ||
          gst_element_set_state(pipeline, GST_STATE_PLAYING) == GST_STATE_CHANGE_FAILURE) {
        failure = "prefix queue could not start";
        break;
      }
      gst_pad_push_event(upstream, gst_event_new_stream_start("prefix-queue-overflow"));
      GstCaps* caps = gst_caps_from_string(
          "video/x-raw,format=RGB,width=1,height=1,framerate=1/1");
      gst_pad_push_event(upstream, gst_event_new_caps(caps));
      gst_caps_unref(caps);
      GstSegment segment;
      gst_segment_init(&segment, GST_FORMAT_TIME);
      gst_pad_push_event(upstream, gst_event_new_segment(&segment));

      if (gst_pad_push(upstream, buffer_with_pts(100)) != GST_FLOW_OK ||
          !wait_for_downstream(&gate)) {
        failure = "first buffer did not block downstream";
        break;
      }
      if (gst_pad_push(upstream, buffer_with_pts(200)) != GST_FLOW_OK ||
          gst_pad_push(upstream, buffer_with_pts(300)) != GST_FLOW_OK) {
        failure = "overflow input was not accepted";
        break;
      }
      std::set<std::string> observed;
      for (std::size_t index = 0; index < branches.size(); ++index) {
        const auto terminal = vast::CheckpointAnalyticsTerminalTransport::receive(sockets[1]);
        if (terminal.transport_pts_ns != 300 ||
            terminal.status != vast::CheckpointAnalyticsTerminalStatus::kDrop ||
            terminal.objects != 0 ||
            terminal.terminal_reason !=
                "native_postdecode_preprocess_queue_full_drop_newest" ||
            terminal.detector != "runtime-bound-postdecode-drop" ||
            terminal.backend != "runtime-bound-postdecode-drop" ||
            !observed.insert(terminal.branch_id).second) {
          failure = "prefix queue emitted an invalid overflow terminal";
          break;
        }
      }
      if (!failure.empty()) {
        break;
      }
      if (observed != std::set<std::string>(branches.begin(), branches.end())) {
        failure = "overflow branch fanout is incomplete";
        break;
      }
      char extra = 0;
      if (::recv(sockets[1], &extra, sizeof(extra), MSG_DONTWAIT) >= 0 ||
          (errno != EAGAIN && errno != EWOULDBLOCK)) {
        failure = "prefix queue emitted an extra terminal";
        break;
      }
    } while (false);
  } catch (const std::exception& error) {
    failure = error.what();
  }

  release_downstream(&gate);
  if (pipeline != nullptr) {
    gst_element_set_state(pipeline, GST_STATE_NULL);
  }
  if (upstream != nullptr && queue_sink != nullptr) {
    gst_pad_unlink(upstream, queue_sink);
  }
  if (upstream != nullptr) {
    gst_pad_set_active(upstream, FALSE);
    gst_object_unref(upstream);
  }
  if (queue_sink != nullptr) {
    gst_object_unref(queue_sink);
  }
  if (sink_pad != nullptr) {
    gst_object_unref(sink_pad);
  }
  if (pipeline != nullptr) {
    gst_object_unref(pipeline);
  }
  ::unsetenv(vast::CheckpointAnalyticsTerminalTransport::kFdEnvironment);
  for (int socket : sockets) {
    if (socket >= 0) {
      ::close(socket);
    }
  }
  g_mutex_clear(&gate.lock);
  g_cond_clear(&gate.condition);
  if (!failure.empty()) {
    std::cerr << failure << '\n';
    return false;
  }
  return true;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 2) {
    std::cerr << "usage: gst-vast-checkpoint-prefix-queue-test PLUGIN\n";
    return 2;
  }
  gst_init(&argc, &argv);
  GError* error = nullptr;
  GstPlugin* plugin = gst_plugin_load_file(argv[1], &error);
  if (plugin == nullptr) {
    std::cerr << (error == nullptr ? "plugin load failed" : error->message) << '\n';
    g_clear_error(&error);
    return 3;
  }
  gst_object_unref(plugin);
  if (!run_overflow_case({"damage"})) {
    return 4;
  }
  if (!run_overflow_case({"plate_number", "vehicle_type", "damage", "foreign_object"})) {
    return 5;
  }
  return 0;
}
