#include <gst/app/gstappsink.h>
#include <gst/gst.h>

#include "checkpoint_admission_transport.hpp"

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstdlib>
#include <deque>
#include <iostream>
#include <limits>
#include <memory>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

#include <poll.h>
#include <unistd.h>

namespace {

struct Args {
  std::string source_path;
  std::string dataset_id;
  std::string source_sha256;
  std::string container;
  std::string codec;
  std::string replay;
  std::uint64_t source_duration_ns = 0;
  int stream_id = -1;
};

std::string required_env(const char* name) {
  const char* value = std::getenv(name);
  if (value == nullptr || std::string(value).empty()) {
    throw std::runtime_error(std::string("missing checkpoint source environment variable: ") + name);
  }
  return value;
}

std::uint64_t parse_uint64(const std::string& raw, const char* name) {
  std::size_t consumed = 0;
  std::uint64_t value = 0;
  try {
    value = std::stoull(raw, &consumed);
  } catch (const std::exception&) {
    throw std::runtime_error(std::string("invalid checkpoint source integer: ") + name);
  }
  if (consumed != raw.size()) {
    throw std::runtime_error(std::string("invalid checkpoint source integer: ") + name);
  }
  return value;
}

int required_fd(const char* name) {
  const std::uint64_t value = parse_uint64(required_env(name), name);
  if (value > static_cast<std::uint64_t>(std::numeric_limits<int>::max())) {
    throw std::runtime_error(std::string("checkpoint source FD is out of range: ") + name);
  }
  return static_cast<int>(value);
}

void write_exact(int fd, const std::string& payload) {
  std::size_t offset = 0;
  while (offset < payload.size()) {
    const ssize_t written = ::write(fd, payload.data() + offset, payload.size() - offset);
    if (written < 0 && errno == EINTR) {
      continue;
    }
    if (written <= 0) {
      throw std::runtime_error("checkpoint source pipe write failed");
    }
    offset += static_cast<std::size_t>(written);
  }
}

std::string read_line(int fd) {
  std::string line;
  char character = '\0';
  while (true) {
    const ssize_t count = ::read(fd, &character, 1);
    if (count < 0 && errno == EINTR) {
      continue;
    }
    if (count <= 0) {
      throw std::runtime_error("checkpoint source control pipe closed unexpectedly");
    }
    if (character == '\n') {
      return line;
    }
    line.push_back(character);
    if (line.size() > 65536) {
      throw std::runtime_error("checkpoint source control line is too long");
    }
  }
}

std::string json_escape(const std::string& value) {
  std::ostringstream output;
  for (const unsigned char character : value) {
    switch (character) {
      case '"': output << "\\\""; break;
      case '\\': output << "\\\\"; break;
      case '\b': output << "\\b"; break;
      case '\f': output << "\\f"; break;
      case '\n': output << "\\n"; break;
      case '\r': output << "\\r"; break;
      case '\t': output << "\\t"; break;
      default:
        if (character < 0x20) {
          const char* digits = "0123456789abcdef";
          output << "\\u00" << digits[(character >> 4) & 0x0f] << digits[character & 0x0f];
        } else {
          output << static_cast<char>(character);
        }
    }
  }
  return output.str();
}

bool valid_name(const std::string& value) {
  return !value.empty() && std::all_of(value.begin(), value.end(), [](unsigned char character) {
    return (character >= 'a' && character <= 'z') || (character >= '0' && character <= '9') ||
           character == '_' || character == '-';
  });
}

bool valid_sha256(const std::string& value) {
  return value.size() == 64 && std::all_of(value.begin(), value.end(), [](unsigned char character) {
    return (character >= '0' && character <= '9') || (character >= 'a' && character <= 'f');
  });
}

std::unordered_map<std::string, int> parse_consumer_fds(const std::string& raw) {
  std::unordered_map<std::string, int> result;
  std::size_t cursor = 0;
  auto require_character = [&](char expected) {
    if (cursor >= raw.size() || raw[cursor] != expected) {
      throw std::runtime_error("invalid checkpoint consumer FD JSON");
    }
    ++cursor;
  };
  require_character('{');
  while (cursor < raw.size() && raw[cursor] != '}') {
    if (!result.empty()) {
      require_character(',');
    }
    require_character('"');
    const std::size_t name_start = cursor;
    while (cursor < raw.size() && raw[cursor] != '"') {
      ++cursor;
    }
    if (cursor >= raw.size()) {
      throw std::runtime_error("unterminated checkpoint consumer ID");
    }
    const std::string name = raw.substr(name_start, cursor - name_start);
    ++cursor;
    require_character(':');
    const std::size_t fd_start = cursor;
    while (cursor < raw.size() && raw[cursor] >= '0' && raw[cursor] <= '9') {
      ++cursor;
    }
    if (!valid_name(name) || fd_start == cursor) {
      throw std::runtime_error("invalid checkpoint consumer binding");
    }
    const std::uint64_t fd = parse_uint64(raw.substr(fd_start, cursor - fd_start), "consumer_fd");
    if (fd > static_cast<std::uint64_t>(std::numeric_limits<int>::max()) ||
        !result.emplace(name, static_cast<int>(fd)).second) {
      throw std::runtime_error("duplicate or out-of-range checkpoint consumer binding");
    }
  }
  require_character('}');
  if (cursor != raw.size() || result.empty()) {
    throw std::runtime_error("checkpoint source requires at least one exact consumer binding");
  }
  return result;
}

std::uint64_t now_ms() {
  using namespace std::chrono;
  return static_cast<std::uint64_t>(duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count());
}

std::string payload_sha256(const GstMapInfo& map) {
  gchar* digest = g_compute_checksum_for_data(G_CHECKSUM_SHA256, map.data, map.size);
  if (digest == nullptr) {
    throw std::runtime_error("failed to compute checkpoint source AU SHA-256");
  }
  std::string result(digest);
  g_free(digest);
  return result;
}

Args parse_args(int argc, char** argv) {
  Args args;
  for (int index = 1; index < argc; ++index) {
    const std::string key = argv[index];
    auto value = [&](const char* flag) {
      if (index + 1 >= argc) {
        throw std::runtime_error(std::string("missing value for ") + flag);
      }
      return std::string(argv[++index]);
    };
    if (key == "--source-path") args.source_path = value("--source-path");
    else if (key == "--dataset-id") args.dataset_id = value("--dataset-id");
    else if (key == "--source-sha256") args.source_sha256 = value("--source-sha256");
    else if (key == "--checkpoint-container") args.container = value("--checkpoint-container");
    else if (key == "--checkpoint-codec") args.codec = value("--checkpoint-codec");
    else if (key == "--source-duration-ns") {
      args.source_duration_ns = parse_uint64(value("--source-duration-ns"), "source_duration_ns");
    } else if (key == "--source-replay") args.replay = value("--source-replay");
    else if (key == "--logical-stream-id") {
      args.stream_id = static_cast<int>(parse_uint64(value("--logical-stream-id"), "stream_id"));
    } else {
      throw std::runtime_error("unknown checkpoint source argument: " + key);
    }
  }
  if (args.source_path.empty() || !valid_name(args.dataset_id) || !valid_sha256(args.source_sha256) ||
      args.container != "mp4" || (args.codec != "h264" && args.codec != "h265") ||
      args.source_duration_ns == 0 || args.replay != "continuous" || args.stream_id < 0) {
    throw std::runtime_error("incomplete or invalid checkpoint source contract");
  }
  return args;
}

class SourceCoordinator {
 public:
  explicit SourceCoordinator(Args args)
      : args_(std::move(args)),
        source_process_id_(required_env("VAST_CHECKPOINT_WORKER_ID")),
        run_id_(required_env("VAST_CHECKPOINT_RUN_ID")),
        admission_fd_(required_fd("VAST_CHECKPOINT_ADMISSION_EVENT_FD")),
        ack_fd_(required_fd("VAST_CHECKPOINT_ADMISSION_ACK_FD")),
        control_fd_(required_fd("VAST_CHECKPOINT_CONTROL_FD")),
        status_fd_(required_fd("VAST_CHECKPOINT_STATUS_FD")) {
    const auto consumer_fds = parse_consumer_fds(required_env("VAST_CHECKPOINT_ADMISSION_CONSUMER_FDS_JSON"));
    std::vector<std::pair<std::string, int>> ordered(consumer_fds.begin(), consumer_fds.end());
    std::sort(ordered.begin(), ordered.end());
    for (const auto& binding : ordered) {
      auto channel = std::make_unique<ConsumerChannel>();
      channel->consumer_id = binding.first;
      channel->fd = binding.second;
      consumers_.push_back(std::move(channel));
    }
    if (required_env("VAST_CHECKPOINT_DATASET_ID") != args_.dataset_id ||
        required_env("VAST_CHECKPOINT_SOURCE_SHA256") != args_.source_sha256 ||
        parse_uint64(required_env("VAST_CHECKPOINT_STREAM_ID"), "stream_id") !=
            static_cast<std::uint64_t>(args_.stream_id)) {
      throw std::runtime_error("checkpoint source command and PID-bound environment differ");
    }
  }

  ~SourceCoordinator() {
    stop_.store(true);
    close_consumer_channels(false);
    if (control_thread_.joinable()) {
      control_thread_.join();
    }
    if (appsink_ != nullptr) {
      gst_object_unref(appsink_);
      appsink_ = nullptr;
    }
    if (pipeline_ != nullptr) {
      gst_element_set_state(pipeline_, GST_STATE_NULL);
      gst_object_unref(pipeline_);
    }
  }

  int run() {
    build_pipeline();
    start_consumer_senders();
    const GstStateChangeReturn paused = gst_element_set_state(pipeline_, GST_STATE_PAUSED);
    if (paused == GST_STATE_CHANGE_FAILURE) {
      throw std::runtime_error("checkpoint source failed to enter PAUSED state");
    }
    write_status("READY", steady_now_ns());
    wait_start();
    std::this_thread::sleep_until(std::chrono::steady_clock::time_point(
        std::chrono::nanoseconds(common_start_monotonic_ns_)));
    if (gst_element_set_state(pipeline_, GST_STATE_PLAYING) == GST_STATE_CHANGE_FAILURE) {
      throw std::runtime_error("checkpoint source failed to enter PLAYING state");
    }
    write_status("STARTED", now_ms());
    control_thread_ = std::thread([this]() { wait_stop(); });

    try {
      while (!stop_.load()) {
        check_consumer_senders();
        check_bus_error();
        GstSample* sample = gst_app_sink_try_pull_sample(GST_APP_SINK(appsink_), 10 * GST_MSECOND);
        if (sample == nullptr) {
          if (gst_app_sink_is_eos(GST_APP_SINK(appsink_)) && !stop_.load()) {
            replay_source();
          }
          continue;
        }
        try {
          admit_and_broadcast(sample);
        } catch (...) {
          gst_sample_unref(sample);
          throw;
        }
        gst_sample_unref(sample);
      }
      check_consumer_senders();
    } catch (const std::exception& exc) {
      failed_.store(true);
      stop_.store(true);
      std::cerr << "[checkpoint-source] " << exc.what() << "\n";
    }

    gst_element_set_state(pipeline_, GST_STATE_NULL);
    close_consumer_channels(!failed_.load());
    try {
      check_consumer_senders();
    } catch (const std::exception& exc) {
      failed_.store(true);
      std::cerr << "[checkpoint-source] " << exc.what() << "\n";
    }
    if (control_thread_.joinable()) {
      control_thread_.join();
    }
    write_status(failed_.load() ? "CENSORED" : "DRAINED", now_ms());
    return failed_.load() ? 1 : 0;
  }

 private:
  struct ConsumerChannel {
    std::string consumer_id;
    int fd = -1;
    std::mutex mutex;
    std::condition_variable ready;
    std::deque<std::shared_ptr<const vast::CheckpointAdmissionFrame>> queue;
    bool closing = false;
    bool drain = true;
    std::string error;
    std::thread sender;
  };

  static constexpr std::size_t kMaximumQueuedAccessUnitsPerConsumer = 512;

  Args args_;
  std::string source_process_id_;
  std::string run_id_;
  int admission_fd_ = -1;
  int ack_fd_ = -1;
  int control_fd_ = -1;
  int status_fd_ = -1;
  std::vector<std::unique_ptr<ConsumerChannel>> consumers_;
  GstElement* pipeline_ = nullptr;
  GstElement* appsink_ = nullptr;
  std::thread control_thread_;
  std::mutex status_mutex_;
  std::mutex admission_mutex_;
  std::atomic<bool> stop_{false};
  std::atomic<bool> failed_{false};
  std::uint64_t common_start_monotonic_ns_ = 0;
  std::uint64_t window_end_ms_ = 0;
  std::uint64_t source_cycle_ = 0;
  std::uint64_t sequence_ = 0;
  std::uint64_t next_schedule_offset_ns_ = 0;

  void start_consumer_senders() {
    for (auto& channel : consumers_) {
      channel->sender = std::thread([this, target = channel.get()]() {
        try {
          while (true) {
            std::shared_ptr<const vast::CheckpointAdmissionFrame> frame;
            {
              std::unique_lock<std::mutex> lock(target->mutex);
              target->ready.wait(lock, [&]() { return target->closing || !target->queue.empty(); });
              if (target->closing && (!target->drain || target->queue.empty())) {
                return;
              }
              frame = target->queue.front();
              target->queue.pop_front();
            }
            vast::CheckpointAdmissionTransport::write_frame(target->fd, *frame);
          }
        } catch (const std::exception& exc) {
          std::lock_guard<std::mutex> lock(target->mutex);
          target->error = exc.what();
          target->closing = true;
          target->drain = false;
          stop_.store(true);
        }
      });
    }
  }

  void enqueue_for_all_consumers(const vast::CheckpointAdmissionFrame& frame) {
    const auto shared = std::make_shared<const vast::CheckpointAdmissionFrame>(frame);
    for (auto& channel : consumers_) {
      std::lock_guard<std::mutex> lock(channel->mutex);
      if (!channel->error.empty()) {
        throw std::runtime_error(
            "checkpoint consumer delivery failed for " + channel->consumer_id + ": " + channel->error);
      }
      if (channel->closing || channel->queue.size() >= kMaximumQueuedAccessUnitsPerConsumer) {
        throw std::runtime_error("checkpoint consumer delivery queue overflow for " + channel->consumer_id);
      }
      channel->queue.push_back(shared);
      channel->ready.notify_one();
    }
  }

  void check_consumer_senders() {
    for (auto& channel : consumers_) {
      std::lock_guard<std::mutex> lock(channel->mutex);
      if (!channel->error.empty()) {
        throw std::runtime_error(
            "checkpoint consumer delivery failed for " + channel->consumer_id + ": " + channel->error);
      }
    }
  }

  void close_consumer_channels(bool drain) {
    for (auto& channel : consumers_) {
      {
        std::lock_guard<std::mutex> lock(channel->mutex);
        channel->closing = true;
        channel->drain = drain;
        if (!drain) {
          channel->queue.clear();
        }
      }
      channel->ready.notify_all();
    }
    for (auto& channel : consumers_) {
      if (channel->sender.joinable()) {
        channel->sender.join();
      }
    }
  }

  static std::uint64_t steady_now_ns() {
    using namespace std::chrono;
    return static_cast<std::uint64_t>(duration_cast<nanoseconds>(steady_clock::now().time_since_epoch()).count());
  }

  void build_pipeline() {
    const std::string parser = args_.codec == "h264" ? "h264parse" : "h265parse";
    const std::string media = args_.codec == "h264" ? "video/x-h264" : "video/x-h265";
    const std::string text =
        "filesrc name=checkpoint_source_file ! qtdemux ! " + parser +
        " config-interval=-1 ! " + media +
        ",stream-format=byte-stream,alignment=au ! appsink name=checkpoint_source_sink "
        "sync=true emit-signals=false max-buffers=1 drop=false";
    GError* error = nullptr;
    pipeline_ = gst_parse_launch(text.c_str(), &error);
    if (pipeline_ == nullptr) {
      const std::string message = error != nullptr ? error->message : "unknown parse error";
      if (error != nullptr) {
        g_error_free(error);
      }
      throw std::runtime_error("failed to build checkpoint source pipeline: " + message);
    }
    GstElement* file = gst_bin_get_by_name(GST_BIN(pipeline_), "checkpoint_source_file");
    appsink_ = gst_bin_get_by_name(GST_BIN(pipeline_), "checkpoint_source_sink");
    if (file == nullptr || appsink_ == nullptr || !GST_IS_APP_SINK(appsink_)) {
      if (file != nullptr) gst_object_unref(file);
      throw std::runtime_error("checkpoint source pipeline lacks filesrc/appsink");
    }
    g_object_set(G_OBJECT(file), "location", args_.source_path.c_str(), nullptr);
    gst_object_unref(file);
  }

  void wait_start() {
    std::istringstream input(read_line(control_fd_));
    std::string version;
    std::string command;
    std::string start_ns;
    std::string window_start_ms;
    std::string window_end_ms;
    std::string drain_end_ms;
    std::string extra;
    input >> version >> command >> start_ns >> window_start_ms >> window_end_ms >> drain_end_ms;
    if ((input >> extra) || version != "1" || command != "START") {
      throw std::runtime_error("invalid checkpoint source START command");
    }
    common_start_monotonic_ns_ = parse_uint64(start_ns, "start_monotonic_ns");
    window_end_ms_ = parse_uint64(window_end_ms, "window_end_ms");
    if (common_start_monotonic_ns_ < steady_now_ns() ||
        parse_uint64(window_start_ms, "window_start_ms") >= window_end_ms_ ||
        window_end_ms_ > parse_uint64(drain_end_ms, "drain_end_ms")) {
      throw std::runtime_error("invalid checkpoint source lifecycle boundaries");
    }
  }

  void wait_stop() {
    try {
      while (!stop_.load()) {
        pollfd descriptor{};
        descriptor.fd = control_fd_;
        descriptor.events = POLLIN;
        const int result = ::poll(&descriptor, 1, 100);
        if (result < 0 && errno == EINTR) {
          continue;
        }
        if (result < 0) {
          throw std::runtime_error("checkpoint source STOP poll failed");
        }
        if (result == 0) {
          continue;
        }
        if ((descriptor.revents & POLLIN) != 0) {
          break;
        }
        if ((descriptor.revents & (POLLERR | POLLHUP | POLLNVAL)) != 0) {
          throw std::runtime_error("checkpoint source control pipe closed before STOP");
        }
      }
      if (stop_.load()) {
        return;
      }
      std::istringstream input(read_line(control_fd_));
      std::string version;
      std::string command;
      std::string window_end;
      std::string extra;
      input >> version >> command >> window_end;
      if ((input >> extra) || version != "1" || command != "STOP" ||
          parse_uint64(window_end, "stop_window_end_ms") != window_end_ms_) {
        throw std::runtime_error("invalid checkpoint source STOP command");
      }
      {
        std::lock_guard<std::mutex> lock(admission_mutex_);
        stop_.store(true);
        write_status("ADMISSION_STOPPED", window_end_ms_);
      }
    } catch (const std::exception& exc) {
      std::cerr << "[checkpoint-source] " << exc.what() << "\n";
      failed_.store(true);
      stop_.store(true);
    }
  }

  void write_status(const std::string& state, std::uint64_t timestamp) {
    std::lock_guard<std::mutex> lock(status_mutex_);
    write_exact(status_fd_, "1 " + state + " " + source_process_id_ + " " + std::to_string(timestamp) + "\n");
  }

  void replay_source() {
    if (!gst_element_seek_simple(
            pipeline_,
            GST_FORMAT_TIME,
            static_cast<GstSeekFlags>(GST_SEEK_FLAG_FLUSH | GST_SEEK_FLAG_KEY_UNIT),
            0)) {
      throw std::runtime_error("checkpoint source failed to seek for continuous replay");
    }
    ++source_cycle_;
  }

  void check_bus_error() {
    GstBus* bus = gst_element_get_bus(pipeline_);
    GstMessage* message = gst_bus_pop_filtered(bus, GST_MESSAGE_ERROR);
    gst_object_unref(bus);
    if (message == nullptr) {
      return;
    }
    GError* error = nullptr;
    gchar* debug = nullptr;
    gst_message_parse_error(message, &error, &debug);
    const std::string text = error != nullptr ? error->message : "unknown GStreamer error";
    if (error != nullptr) g_error_free(error);
    g_free(debug);
    gst_message_unref(message);
    throw std::runtime_error("checkpoint source pipeline failed: " + text);
  }

  void admit_and_broadcast(GstSample* sample) {
    std::lock_guard<std::mutex> admission_lock(admission_mutex_);
    if (stop_.load() || now_ms() >= window_end_ms_) {
      return;
    }
    GstBuffer* buffer = gst_sample_get_buffer(sample);
    if (buffer == nullptr || !GST_BUFFER_PTS_IS_VALID(buffer)) {
      throw std::runtime_error("checkpoint source AU lacks native PTS");
    }
    const std::uint64_t native_pts = GST_BUFFER_PTS(buffer);
    GstMapInfo map = GST_MAP_INFO_INIT;
    if (!gst_buffer_map(buffer, &map, GST_MAP_READ) || map.size == 0) {
      throw std::runtime_error("checkpoint source failed to map compressed AU");
    }
    try {
      vast::CheckpointAdmissionFrame frame;
      frame.sequence = ++sequence_;
      frame.source_cycle = source_cycle_;
      frame.access_unit_pts_ns = native_pts;
      frame.transport_pts_ns = source_cycle_ * args_.source_duration_ns + native_pts;
      frame.access_unit_dts_ns =
          GST_BUFFER_DTS_IS_VALID(buffer) ? GST_BUFFER_DTS(buffer) : vast::CheckpointAdmissionTransport::kMissingTimestamp;
      frame.duration_ns = GST_BUFFER_DURATION_IS_VALID(buffer) ? GST_BUFFER_DURATION(buffer) : 0;
      frame.admission_id = run_id_ + ":" + std::to_string(args_.stream_id) + ":admission:" +
                           std::to_string(frame.sequence);
      frame.input_frame_key = args_.dataset_id + ":" + std::to_string(args_.stream_id) + ":" +
                              args_.source_sha256 + ":" + std::to_string(frame.source_cycle) + ":" +
                              std::to_string(frame.access_unit_pts_ns);
      frame.payload_sha256 = payload_sha256(map);
      frame.payload.assign(map.data, map.data + map.size);
      const std::uint64_t schedule_offset_ns = next_schedule_offset_ns_;

      std::ostringstream event;
      event << "{\"protocol_version\":1,\"source_process_id\":\"" << json_escape(source_process_id_)
            << "\",\"sequence\":" << frame.sequence << ",\"run_id\":\"" << json_escape(run_id_)
            << "\",\"dataset_id\":\"" << json_escape(args_.dataset_id) << "\",\"stream_id\":"
            << args_.stream_id << ",\"admission_id\":\"" << json_escape(frame.admission_id)
            << "\",\"input_frame_key\":\"" << json_escape(frame.input_frame_key)
            << "\",\"source_sha256\":\"" << args_.source_sha256 << "\",\"source_cycle\":"
            << frame.source_cycle << ",\"access_unit_pts_ns\":" << frame.access_unit_pts_ns
            << ",\"payload_sha256\":\"" << frame.payload_sha256 << "\",\"payload_size_bytes\":"
            << frame.payload.size() << ",\"schedule_offset_ns\":" << schedule_offset_ns
            << ",\"admission_timestamp_ms\":" << now_ms()
            << ",\"event_provenance\":\"native_common_source_coordinator\"}\n";
      write_exact(admission_fd_, event.str());
      const std::string expected_ack = "1 ACK " + std::to_string(frame.sequence);
      if (read_line(ack_fd_) != expected_ack) {
        throw std::runtime_error("checkpoint source received an invalid admission ACK");
      }
      enqueue_for_all_consumers(frame);
      const std::uint64_t schedule_step_ns = std::max<std::uint64_t>(frame.duration_ns, 1);
      if (next_schedule_offset_ns_ > std::numeric_limits<std::uint64_t>::max() - schedule_step_ns) {
        throw std::runtime_error("checkpoint source decode-order schedule overflow");
      }
      next_schedule_offset_ns_ += schedule_step_ns;
    } catch (...) {
      gst_buffer_unmap(buffer, &map);
      throw;
    }
    gst_buffer_unmap(buffer, &map);
  }
};

}  // namespace

int main(int argc, char** argv) {
  try {
    gst_init(&argc, &argv);
    SourceCoordinator coordinator(parse_args(argc, argv));
    return coordinator.run();
  } catch (const std::exception& exc) {
    std::cerr << "[checkpoint-source][fatal] " << exc.what() << "\n";
    return 2;
  }
}
