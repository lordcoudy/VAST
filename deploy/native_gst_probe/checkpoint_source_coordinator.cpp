#include <gst/app/gstappsink.h>
#include <gst/gst.h>

#include "checkpoint_admission_transport.hpp"
#include "checkpoint_study_reference.hpp"

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstdlib>
#include <deque>
#include <iostream>
#include <fstream>
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
#include <sys/stat.h>
#include <unistd.h>

namespace {

struct Args {
  std::string source_path;
  std::string dataset_id;
  std::string source_sha256;
  std::string container;
  std::string codec;
  std::string replay;
  std::string study_kind;
  std::string study_accounting_path;
  std::uint64_t study_width = 0;
  std::uint64_t study_height = 0;
  std::uint64_t source_duration_ns = 0;
  std::uint64_t playback_timestamp_scale = 0;
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
  if (raw.empty() || raw.find_first_not_of("0123456789") != std::string::npos)
    throw std::runtime_error(std::string("invalid checkpoint source integer: ") + name);
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

void write_exact(int fd, const std::string& payload,
                 const vast::CheckpointIoDeadline* io = nullptr) {
  if (io) vast::CheckpointIoDeadline::set_owned_nonblocking(fd);
  std::size_t offset = 0;
  while (offset < payload.size()) {
    if (io) io->check();
    const ssize_t written = ::write(fd, payload.data() + offset, payload.size() - offset);
    if (written < 0 && errno == EINTR) {
      continue;
    }
    if (written < 0 && (errno == EAGAIN || errno == EWOULDBLOCK) && io) {
      io->wait(fd, POLLOUT);
      continue;
    }
    if (written <= 0) {
      throw std::runtime_error("checkpoint source pipe write failed");
    }
    offset += static_cast<std::size_t>(written);
  }
}

std::string read_line(int fd, const vast::CheckpointIoDeadline* io = nullptr) {
  if (io) vast::CheckpointIoDeadline::set_owned_nonblocking(fd);
  std::string line;
  char character = '\0';
  while (true) {
    if (io) io->check();
    const ssize_t count = ::read(fd, &character, 1);
    if (count < 0 && errno == EINTR) {
      continue;
    }
    if (count < 0 && (errno == EAGAIN || errno == EWOULDBLOCK) && io) {
      io->wait(fd, POLLIN);
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
    } else if (key == "--playback-timestamp-scale") {
      args.playback_timestamp_scale =
          parse_uint64(value("--playback-timestamp-scale"), "playback_timestamp_scale");
    } else if (key == "--source-replay") args.replay = value("--source-replay");
    else if (key == "--checkpoint-study-kind") args.study_kind = value("--checkpoint-study-kind");
    else if (key == "--checkpoint-study-accounting-path") args.study_accounting_path = value("--checkpoint-study-accounting-path");
    else if (key == "--checkpoint-study-width") args.study_width = parse_uint64(value("--checkpoint-study-width"), "study_width");
    else if (key == "--checkpoint-study-height") args.study_height = parse_uint64(value("--checkpoint-study-height"), "study_height");
    else if (key == "--logical-stream-id") {
      args.stream_id = static_cast<int>(parse_uint64(value("--logical-stream-id"), "stream_id"));
    } else {
      throw std::runtime_error("unknown checkpoint source argument: " + key);
    }
  }
  if (args.source_path.empty() || !valid_name(args.dataset_id) || !valid_sha256(args.source_sha256) ||
      args.container != "mp4" || (args.codec != "h264" && args.codec != "h265") ||
      args.source_duration_ns == 0 || args.playback_timestamp_scale == 0 ||
      args.stream_id < 0 ||
      (args.study_kind.empty() ? (args.replay != "continuous" || !args.study_accounting_path.empty() || args.study_width || args.study_height) :
       (args.study_kind != "finite-component-study" || args.replay != "finite" || args.codec != "h264" ||
        args.study_accounting_path.empty() || args.stream_id > 5 ||
        args.study_width != (args.stream_id == 5 ? 1700ULL : 1920ULL) ||
        args.study_height != (args.stream_id == 5 ? 236ULL : 1080ULL)))) {
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
    if (!args_.study_kind.empty()) {
      if (args_.study_kind != "finite-component-study" || args_.replay != "finite") {
        throw std::runtime_error("invalid finite source study binding");
      }
      const char* original_startup = std::getenv("VAST_CHECKPOINT_STARTUP_DEADLINE_MONOTONIC_NS");
      if (!original_startup || !*original_startup ||
          parse_uint64(original_startup, "original startup deadline") <= steady_now_ns()) {
        throw std::runtime_error("finite source requires original verified startup deadline");
      }
      std::ifstream boot("/proc/sys/kernel/random/boot_id");
      std::getline(boot, boot_id_);
      if (boot_id_.empty()) throw std::runtime_error("finite source clock namespace identity is unavailable");
      time_namespace_ = vast::study::detail::actual_clock_domain_label();
      study_fd_ = ::open(args_.study_accounting_path.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
      if (study_fd_ < 0) throw std::runtime_error("finite source accounting path must be new and exclusively owned");
      struct stat identity{};
      if (::fstat(study_fd_, &identity) != 0 || !S_ISREG(identity.st_mode) || identity.st_nlink != 1) {
        ::close(study_fd_); study_fd_ = -1;
        throw std::runtime_error("finite source accounting must be one owned regular file");
      }
      study_opened_ = identity;
    }
  }

  ~SourceCoordinator() {
    io_->abort();
    startup_io_->abort();
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
    if (study_fd_ >= 0) { ::close(study_fd_); study_fd_ = -1; }
    retire_owned_descriptors(false);
  }

  int run() {
    build_pipeline();
    start_consumer_senders();
    const GstStateChangeReturn paused = gst_element_set_state(pipeline_, GST_STATE_PAUSED);
    if (paused == GST_STATE_CHANGE_FAILURE) {
      throw std::runtime_error("checkpoint source failed to enter PAUSED state");
    }
    verify_reset_state_before_ready();
    write_status("READY", steady_now_ns());
    wait_start();
    wait_scheduled(common_start_monotonic_ns_);
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
            if (!args_.study_kind.empty()) throw std::runtime_error("finite source reached EOF before original STOP");
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
      io_->abort();
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
    try { finish_study_journal(); }
    catch (const std::exception& exc) {
      failed_.store(true);
      std::cerr << "[checkpoint-source][cleanup] " << exc.what() << '\n';
    }
    if (!failed_.load()) write_status("DRAINED", now_ms());
    retire_owned_descriptors(true);
    return failed_.load() ? 1 : 0;
  }

 private:
#ifdef VAST_SOURCE_COORDINATOR_TESTING
  friend struct SourceCoordinatorTestAccess;
#endif
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
  std::timed_mutex status_mutex_;
  std::timed_mutex admission_mutex_;
  std::shared_ptr<vast::CheckpointIoDeadline> io_ = std::make_shared<vast::CheckpointIoDeadline>();
  std::shared_ptr<vast::CheckpointIoDeadline> startup_io_ = [] {
    const char* deadline = std::getenv("VAST_CHECKPOINT_STARTUP_DEADLINE_MONOTONIC_NS");
    return std::make_shared<vast::CheckpointIoDeadline>(
        deadline && *deadline ? parse_uint64(deadline, "original startup deadline") : 0);
  }();
  std::atomic<bool> stop_{false};
  std::atomic<bool> failed_{false};
  std::uint64_t common_start_monotonic_ns_ = 0;
  std::uint64_t window_end_ms_ = 0;
  std::uint64_t source_cycle_ = 0;
  std::uint64_t sequence_ = 0;
  std::uint64_t next_schedule_offset_ns_ = 0;
  int study_fd_ = -1;
  struct stat study_opened_{};
  std::timed_mutex study_mutex_;
  std::uint64_t study_bytes_ = 0;
  std::string boot_id_;
  std::string time_namespace_;

  void start_consumer_senders() {
    for (auto& channel : consumers_) {
      channel->sender = std::thread([this, target = channel.get()]() {
        try {
          while (true) {
            std::shared_ptr<const vast::CheckpointAdmissionFrame> frame;
            {
              std::unique_lock<std::mutex> lock(target->mutex);
              while (!target->closing && target->queue.empty()) {
                target->ready.wait_for(lock, std::chrono::milliseconds(10));
                io_->check();
              }
              if (target->closing && (!target->drain || target->queue.empty())) {
                return;
              }
              frame = target->queue.front();
              target->queue.pop_front();
            }
            vast::CheckpointAdmissionTransport::write_frame(target->fd, *frame, io_.get());
            study_row("recipient_delivered", *frame, target->consumer_id);
          }
        } catch (const std::exception& exc) {
          std::lock_guard<std::mutex> lock(target->mutex);
          target->error = exc.what();
          target->closing = true;
          target->drain = false;
          failed_.store(true);
          stop_.store(true);
          io_->abort();
        }
      });
    }
  }

  void verify_reset_state_before_ready() {
    if (source_cycle_ != 0 || sequence_ != 0 || next_schedule_offset_ns_ != 0 ||
        stop_.load() || failed_.load()) {
      throw std::runtime_error("checkpoint source replay origin is not reset before READY");
    }
    for (const auto& channel : consumers_) {
      std::lock_guard<std::mutex> lock(channel->mutex);
      if (!channel->queue.empty() || channel->closing || !channel->error.empty()) {
        throw std::runtime_error(
            "checkpoint source consumer delivery state is not empty before READY");
      }
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
      study_row("fanout_enqueued", frame, channel->consumer_id);
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
    std::istringstream input(read_line(control_fd_, startup_io_.get()));
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
    io_->bind_original_drain_end_ms(parse_uint64(drain_end_ms, "drain_end_ms"));
  }

  void wait_stop() {
    try {
      while (!stop_.load()) {
        io_->check();
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
      std::istringstream input(read_line(control_fd_, io_.get()));
      std::string version;
      std::string command;
      std::string window_end;
      std::string extra;
      input >> version >> command >> window_end;
      if ((input >> extra) || version != "1" || command != "STOP" ||
          parse_uint64(window_end, "stop_window_end_ms") != window_end_ms_) {
        throw std::runtime_error("invalid checkpoint source STOP command");
      }
      stop_.store(true);  // Latch before waiting behind an already admitted ACK.
      {
        auto lock = io_->acquire(admission_mutex_);
        write_status("ADMISSION_STOPPED", window_end_ms_);
      }
    } catch (const std::exception& exc) {
      std::cerr << "[checkpoint-source] " << exc.what() << "\n";
      failed_.store(true);
      stop_.store(true);
      io_->abort();
    }
  }

  void write_status(const std::string& state, std::uint64_t timestamp) {
    const auto& bound = state == "READY" ? startup_io_ : io_;
    auto lock = bound->acquire(status_mutex_);
    write_exact(status_fd_, "1 " + state + " " + source_process_id_ + " " + std::to_string(timestamp) + "\n", bound.get());
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
    auto admission_lock = io_->acquire(admission_mutex_);
    if (stop_.load() || now_ms() >= window_end_ms_) {
      return;
    }
    GstBuffer* buffer = gst_sample_get_buffer(sample);
    if (buffer == nullptr || !GST_BUFFER_PTS_IS_VALID(buffer)) {
      throw std::runtime_error("checkpoint source AU lacks native PTS");
    }
    const std::uint64_t native_pts = GST_BUFFER_PTS(buffer);
    const std::uint64_t schedule_offset_ns = next_schedule_offset_ns_;
    if (common_start_monotonic_ns_ >
        std::numeric_limits<std::uint64_t>::max() - schedule_offset_ns) {
      throw std::runtime_error("checkpoint source wall-clock schedule overflow");
    }
    const auto scheduled_admission_time = common_start_monotonic_ns_ + schedule_offset_ns;
    wait_scheduled(scheduled_admission_time);
    if (stop_.load() || now_ms() >= window_end_ms_) {
      return;
    }
    GstMapInfo map = GST_MAP_INFO_INIT;
    if (!gst_buffer_map(buffer, &map, GST_MAP_READ) || map.size == 0) {
      throw std::runtime_error("checkpoint source failed to map compressed AU");
    }
    try {
      vast::CheckpointAdmissionFrame frame;
      frame.sequence = ++sequence_;
      frame.source_schedule_offset_ns = schedule_offset_ns;
      frame.keyframe = !GST_BUFFER_FLAG_IS_SET(buffer, GST_BUFFER_FLAG_DELTA_UNIT);
      frame.source_cycle = source_cycle_;
      frame.access_unit_pts_ns = native_pts;
      const auto checked_multiply = [](std::uint64_t left, std::uint64_t right, const char* field) {
        if (left != 0 && right > std::numeric_limits<std::uint64_t>::max() / left) {
          throw std::runtime_error(std::string("checkpoint source timestamp overflow: ") + field);
        }
        return left * right;
      };
      const std::uint64_t cycle_offset_ns =
          checked_multiply(source_cycle_, args_.source_duration_ns, "source_cycle");
      const std::uint64_t scaled_pts_ns =
          checked_multiply(native_pts, args_.playback_timestamp_scale, "PTS");
      if (cycle_offset_ns > std::numeric_limits<std::uint64_t>::max() - scaled_pts_ns) {
        throw std::runtime_error("checkpoint source timestamp overflow: transport PTS");
      }
      frame.transport_pts_ns = cycle_offset_ns + scaled_pts_ns;
      frame.access_unit_dts_ns =
          GST_BUFFER_DTS_IS_VALID(buffer)
              ? checked_multiply(GST_BUFFER_DTS(buffer), args_.playback_timestamp_scale, "DTS")
              : vast::CheckpointAdmissionTransport::kMissingTimestamp;
      frame.duration_ns =
          GST_BUFFER_DURATION_IS_VALID(buffer)
              ? checked_multiply(GST_BUFFER_DURATION(buffer), args_.playback_timestamp_scale, "duration")
              : 0;
      frame.admission_id = run_id_ + ":" + std::to_string(args_.stream_id) + ":admission:" +
                           std::to_string(frame.sequence);
      frame.input_frame_key = args_.dataset_id + ":" + std::to_string(args_.stream_id) + ":" +
                              args_.source_sha256 + ":" + std::to_string(frame.source_cycle) + ":" +
                              std::to_string(frame.access_unit_pts_ns);
      frame.payload_sha256 = payload_sha256(map);
      if (!args_.study_kind.empty() && (map.size > 16ULL * 1024 * 1024 || frame.source_cycle != 0 ||
          frame.sequence > 442 || !frame.keyframe || frame.duration_ns == 0 ||
          frame.access_unit_dts_ns != frame.transport_pts_ns))
        throw std::runtime_error("finite source AU does not match the bounded all-I inventory contract");
      frame.payload.assign(map.data, map.data + map.size);
      study_row("source_offered", frame);

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
      write_exact(admission_fd_, event.str(), io_.get());
      const std::string expected_ack = "1 ACK " + std::to_string(frame.sequence);
      if (read_line(ack_fd_, io_.get()) != expected_ack) {
        throw std::runtime_error("checkpoint source received an invalid admission ACK");
      }
      study_row("source_admitted", frame);
      study_row("source_ack", frame);
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

  void wait_scheduled(std::uint64_t due_ns) {
    while (!stop_.load() && steady_now_ns() < due_ns) {
      io_->check();
      const auto remaining = due_ns - std::min(due_ns, steady_now_ns());
      std::this_thread::sleep_for(std::chrono::nanoseconds(std::min<std::uint64_t>(remaining, 10'000'000)));
    }
    io_->check();
  }

  void study_row(const std::string& event, const vast::CheckpointAdmissionFrame& frame,
                 const std::string& recipient = "") {
    if (study_fd_ < 0) return;
    if (frame.source_cycle != 0 || frame.sequence == 0 || frame.sequence > 442) {
      throw std::runtime_error("finite source row exceeds original single-pass inventory");
    }
    const auto actual = steady_now_ns();
    // No cross-process or cross-domain subtraction: both endpoints below were
    // observed by this source in its own verified original START clock.
    const auto schedule = frame.source_schedule_offset_ns; // Original cumulative parsed-AU durations.
    const auto due = common_start_monotonic_ns_ + schedule;
    const auto lateness = actual > due ? actual - due : 0;
    std::ostringstream row;
    row << "{\"study_kind\":\"finite-component-study\",\"type\":\"" << event
        << "\",\"run_id\":\"" << json_escape(run_id_) << "\",\"worker_id\":\"" << json_escape(source_process_id_)
        << "\",\"stream_id\":" << args_.stream_id << ",\"sequence\":" << frame.sequence
        << ",\"derived_ordinal\":" << frame.sequence - 1 << ",\"source_cycle\":0,\"input_frame_key\":\""
        << json_escape(frame.input_frame_key) << "\",\"access_unit_pts_ns\":" << frame.access_unit_pts_ns
        << ",\"planned_schedule_offset_ns\":" << schedule << ",\"payload_sha256\":\"" << frame.payload_sha256
        << "\",\"recipient_id\":\"" << json_escape(recipient) << "\",\"pid\":" << ::getpid()
        << ",\"actual_monotonic_ns\":" << actual << ",\"actual_realtime_ns\":" << vast::CheckpointIoDeadline::realtime_now_ns()
        << ",\"clock_boot_id\":\"" << json_escape(boot_id_) << "\",\"clock_time_namespace\":\"" << json_escape(time_namespace_)
        << "\",\"source_lateness_ns\":" << lateness << "}\n";
    const auto bytes = row.str();
    auto lock = io_->acquire(study_mutex_);
    if (bytes.size() > 2048 || study_bytes_ > 64ULL * 1024 * 1024 - bytes.size()) {
      throw std::runtime_error("finite source accounting exceeded frozen row/file cap");
    }
    write_exact(study_fd_, bytes, io_.get());
    study_bytes_ += bytes.size();
  }

  void finish_study_journal() {
    if (study_fd_ < 0) return;
    std::exception_ptr primary;
    const auto verify = [&] {
      io_->check_original_deadline();
      struct stat held{}, visible{};
      if (::fstat(study_fd_, &held) || ::lstat(args_.study_accounting_path.c_str(), &visible) ||
          !S_ISREG(held.st_mode) || !S_ISREG(visible.st_mode) || held.st_nlink != 1 || visible.st_nlink != 1 ||
          held.st_dev != study_opened_.st_dev || held.st_ino != study_opened_.st_ino ||
          visible.st_dev != held.st_dev || visible.st_ino != held.st_ino || held.st_size < 0 ||
          static_cast<std::uint64_t>(held.st_size) != study_bytes_ || visible.st_size != held.st_size)
        throw std::runtime_error("finite source journal final descriptor/path/bytes custody failed");
    };
    try {
      verify();
      while (::fsync(study_fd_) != 0) {
        if (errno != EINTR) throw std::runtime_error("finite source journal final fsync failed");
        io_->check_original_deadline();
      }
      verify();
    } catch (...) { primary = std::current_exception(); }
    const int owned = study_fd_; study_fd_ = -1;
    if (::close(owned) != 0) {
      std::cerr << "[checkpoint-source][cleanup] finite source journal final close failed\n";
      if (!primary) primary = std::make_exception_ptr(std::runtime_error("finite source journal final close failed"));
    }
    try { io_->check_original_deadline(); } catch (...) { if (!primary) primary = std::current_exception(); }
    if (primary) std::rethrow_exception(primary);
  }

  void retire_owned_descriptors(bool checked) noexcept {
    // Only the owner retires descriptors, after all sender/control users joined.
    std::vector<int> retired;
    const auto close_owned = [&](int& fd) {
      const int owned = fd; fd = -1;
      if (owned < 0 || std::find(retired.begin(), retired.end(), owned) != retired.end()) return;
      retired.push_back(owned);
      if (::close(owned) != 0 && checked) {
        failed_.store(true);
        std::cerr << "[checkpoint-source][cleanup] owned source descriptor close failed\n";
      }
    };
    for (auto& channel : consumers_) close_owned(channel->fd);
    for (int* fd : {&admission_fd_, &ack_fd_, &control_fd_, &status_fd_}) close_owned(*fd);
  }
};

}  // namespace

int main(int argc, char** argv) {
  try {
    bool handled = false;
    const int inventory_status = vast::study::dispatch_au_inventory_cli(argc, argv, handled);
    if (handled) return inventory_status;
    gst_init(&argc, &argv);
    SourceCoordinator coordinator(parse_args(argc, argv));
    return coordinator.run();
  } catch (const std::exception& exc) {
    std::cerr << "[checkpoint-source][fatal] " << exc.what() << "\n";
    return 2;
  }
}
