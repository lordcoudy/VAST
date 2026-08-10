#include <gst/gst.h>
#include <gst/app/gstappsrc.h>
#include <gst/rtp/rtp.h>

#include "checkpoint_admission_transport.hpp"
#include "checkpoint_analytics_terminal_transport.hpp"
#include "checkpoint_resource_interval_emitter.hpp"
#include "checkpoint_runtime_emitter.hpp"

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <deque>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <memory>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <tuple>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include <poll.h>
#include <unistd.h>

namespace fs = std::filesystem;

constexpr guint8 kTraceExtensionId = 1;
constexpr std::uint16_t kTraceMagic = 0x5641;
constexpr std::uint8_t kTraceVersion = 1;
constexpr std::size_t kTracePayloadSize = 16;

struct Args {
  std::string executable_path;
  std::string system;
  std::string role;
  std::string stages;
  std::string run_id;
  std::string detector;
  std::string backend;
  std::string output_dir;
  std::string output_host;
  std::string video_layout_dir = "data/videos";
  std::string dataset_streams_json;
  std::string detect_bin = "identity";
  std::string checkpoint_branches;
  std::string checkpoint_branch;
  std::string dataset_id;
  std::string source_sha256;
  std::string checkpoint_container;
  std::string checkpoint_codec;
  std::string checkpoint_allowed_decoder_factories;
  std::string source_replay;
  std::string checkpoint_analytics_mode = "topology_only";
  std::uint64_t source_duration_ns = 0;
  int input_port_base = 0;
  int output_port_base = 0;
  int port_stride = 1;
  int streams = 1;
  int logical_stream_id = 0;
  int duration_s = 1;
  int min_objects = 0;
  int max_objects = 20;
  double deadline_ms = 100.0;
  std::string policy = "static_hybrid";
};

struct Trace {
  std::uint8_t stream_id = 0;
  std::uint32_t frame_id = 0;
  std::uint64_t ingress_ms = 0;
  std::uint64_t source_cycle = 0;
  std::uint64_t source_pts_ns = 0;
  std::string admission_id;
  std::string payload_sha256;
};

struct FanoutIntervalStart {
  std::uint64_t host_start_timestamp_ns = 0;
  std::uint64_t bytes = 0;
  std::uint32_t frame_id = 0;
};

struct StreamState {
  std::uint32_t edge_frame_id = 0;
  std::uint32_t local_frame_id = 0;
  Trace current_output_trace{};
  bool has_output_trace = false;
  std::uint32_t last_input_frame_id = 0;
  bool has_last_input_frame = false;
  std::deque<Trace> traces;
  std::deque<Trace> aggregate_traces;
  std::unordered_map<std::uint64_t, Trace> local_traces_by_pts;
  std::unordered_map<std::uint64_t, Trace> checkpoint_deliveries_by_pts;
  std::unordered_map<std::uint64_t, std::unordered_set<std::string>> checkpoint_completed_branches_by_pts;
  std::unordered_map<std::string, std::unordered_map<std::uint64_t, FanoutIntervalStart>>
      checkpoint_fanout_starts_by_branch;
  std::uint64_t last_checkpoint_pts = 0;
  bool has_last_checkpoint_pts = false;
  std::uint64_t checkpoint_source_cycle = 0;
};

class NativeProbeRuntime {
 public:
  explicit NativeProbeRuntime(Args args) : args_(std::move(args)), streams_(std::max(1, args_.streams)) {
    stage_names_ = parse_stage_names(args_.stages);
    checkpoint_branches_ = parse_stage_names(args_.checkpoint_branches);
    checkpoint_allowed_decoder_factories_ = parse_stage_names(args_.checkpoint_allowed_decoder_factories);
    if (!checkpoint_allowed_decoder_factories_.empty()) {
      if (!is_checkpoint_role()) {
        throw std::runtime_error("decoder-factory allowlist is valid only for checkpoint roles");
      }
      if (args_.checkpoint_codec != "h264") {
        throw std::runtime_error("decoder-factory allowlist requires the preregistered H.264 checkpoint codec");
      }
      if (streams_ != 1) {
        throw std::runtime_error("decoder-placement lifecycle verification requires one stream per worker");
      }
      std::unordered_set<std::string> unique_factories;
      for (const std::string& factory : checkpoint_allowed_decoder_factories_) {
        if (factory.find_first_not_of(
                "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.+-") != std::string::npos) {
          throw std::runtime_error("checkpoint decoder-factory allowlist is not canonical");
        }
        if (!unique_factories.insert(factory).second) {
          throw std::runtime_error("checkpoint decoder-factory allowlist contains duplicates");
        }
      }
    }
    if (args_.role == "checkpoint_branch") {
      if (args_.checkpoint_branch.empty()) {
        throw std::runtime_error("checkpoint_branch role requires --checkpoint-branch");
      }
      checkpoint_branches_ = {args_.checkpoint_branch};
      stage_names_ = {
          "decode_" + args_.checkpoint_branch,
          "preprocess_" + args_.checkpoint_branch,
          args_.checkpoint_branch,
      };
      initialize_checkpoint_runtime();
    } else if (args_.role == "checkpoint_shared") {
      if (checkpoint_branches_.empty()) {
        throw std::runtime_error("checkpoint_shared role requires --checkpoint-branches");
      }
      stage_names_ = {"decode", "preprocess"};
      stage_names_.insert(stage_names_.end(), checkpoint_branches_.begin(), checkpoint_branches_.end());
      initialize_checkpoint_runtime();
    }
    if (stage_names_.empty()) {
      if (args_.role == "edge") {
        stage_names_ = {"decode"};
      } else if (args_.role == "gpu_worker") {
        stage_names_ = {"detect"};
      } else {
        stage_names_ = {"decode", "detect", "aggregate"};
      }
    }
    states_.resize(static_cast<std::size_t>(streams_));
    sources_ = parse_json_string_array(args_.dataset_streams_json);
    open_outputs();
  }

  ~NativeProbeRuntime() {
    for (GstElement* pipeline : pipelines_) {
      if (pipeline != nullptr) {
        gst_element_set_state(pipeline, GST_STATE_NULL);
      }
    }
    stop_checkpoint_analytics_terminal_reader();
    for (GstElement* pipeline : pipelines_) {
      if (pipeline != nullptr) {
        gst_object_unref(pipeline);
      }
    }
  }

  int run() {
    build_pipelines();
    GMainLoop* loop = g_main_loop_new(nullptr, FALSE);
    loop_ = loop;
    if (is_checkpoint_role()) {
      write_checkpoint_lifecycle_status("READY", steady_now_ns());
      wait_for_checkpoint_start();
      const auto start_time = std::chrono::steady_clock::time_point(
          std::chrono::nanoseconds(checkpoint_common_start_monotonic_ns_));
      std::this_thread::sleep_until(start_time);
      start_checkpoint_analytics_terminal_reader();
    }
    for (GstElement* pipeline : pipelines_) {
      gst_element_set_state(pipeline, GST_STATE_PLAYING);
    }
    if (is_checkpoint_role()) {
      write_checkpoint_lifecycle_status("STARTED", now_ms());
      checkpoint_data_thread_ = std::thread([this]() { feed_checkpoint_access_units(); });
      checkpoint_control_thread_ = std::thread([this]() { wait_for_checkpoint_stop(); });
      std::cerr << "[native-probe][checkpoint] common lifecycle started window=["
                << checkpoint_window_start_ms_ << "," << checkpoint_window_end_ms_
                << ") drain_end=" << checkpoint_drain_end_ms_ << "\n";
    } else {
      std::cerr << "[native-probe] waiting for first frame event before starting "
                << args_.duration_s << "s measurement timer\n";
    }
    g_main_loop_run(loop);
    checkpoint_loop_finished_.store(true);
    if (checkpoint_control_thread_.joinable()) {
      checkpoint_control_thread_.join();
    }
    if (checkpoint_data_thread_.joinable()) {
      checkpoint_data_thread_.join();
    }
    const guint timer = measurement_timer_id_.exchange(0);
    if (timer != 0) {
      g_source_remove(timer);
    }
    stop_pipelines();
    stop_checkpoint_analytics_terminal_reader();
    g_main_loop_unref(loop);
    loop_ = nullptr;
    flush_outputs();
    return failed_.load() ? 1 : 0;
  }

 private:
  Args args_;
  int streams_ = 1;
  std::vector<StreamState> states_;
  std::vector<std::string> sources_;
  std::vector<std::string> stage_names_;
  std::vector<std::string> checkpoint_branches_;
  std::vector<std::string> checkpoint_allowed_decoder_factories_;
  std::vector<GstElement*> pipelines_;
  std::unique_ptr<vast::CheckpointRuntimeEmitter> checkpoint_emitter_;
  std::unique_ptr<vast::CheckpointResourceIntervalEmitter> checkpoint_resource_interval_emitter_;
  GMainLoop* loop_ = nullptr;
  int checkpoint_control_fd_ = -1;
  int checkpoint_status_fd_ = -1;
  int checkpoint_data_fd_ = -1;
  std::thread checkpoint_control_thread_;
  std::thread checkpoint_data_thread_;
  std::thread checkpoint_analytics_terminal_thread_;
  std::atomic<bool> checkpoint_admission_stopped_{false};
  std::atomic<bool> checkpoint_data_eof_{false};
  std::atomic<bool> checkpoint_drain_reported_{false};
  std::atomic<bool> checkpoint_decoder_placement_verified_{false};
  std::atomic<bool> checkpoint_loop_finished_{false};
  std::atomic<bool> checkpoint_analytics_terminal_stop_{false};
  int checkpoint_analytics_terminal_read_fd_ = -1;
  int checkpoint_analytics_terminal_write_fd_ = -1;
  std::uint64_t checkpoint_common_start_monotonic_ns_ = 0;
  std::uint64_t checkpoint_window_start_ms_ = 0;
  std::uint64_t checkpoint_window_end_ms_ = 0;
  std::uint64_t checkpoint_drain_end_ms_ = 0;
  std::atomic<guint> measurement_timer_id_{0};
  std::atomic<bool> measurement_started_{false};
  std::ofstream events_;
  std::ofstream frames_;
  std::ofstream stage_contracts_;
  std::mutex mutex_;
  std::mutex output_mutex_;
  std::mutex checkpoint_status_mutex_;
  std::unordered_set<std::uint64_t> written_frame_keys_;
  std::unordered_set<std::string> written_checkpoint_stage_contracts_;
  std::atomic<bool> failed_{false};

  static std::uint64_t now_ms() {
    using namespace std::chrono;
    return static_cast<std::uint64_t>(duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count());
  }

  static std::uint64_t now_ns() {
    using namespace std::chrono;
    return static_cast<std::uint64_t>(
        duration_cast<nanoseconds>(system_clock::now().time_since_epoch()).count());
  }

  static std::uint64_t steady_now_ns() {
    using namespace std::chrono;
    return static_cast<std::uint64_t>(duration_cast<nanoseconds>(steady_clock::now().time_since_epoch()).count());
  }

  bool is_checkpoint_role() const {
    return args_.role == "checkpoint_branch" || args_.role == "checkpoint_shared";
  }

  static std::string csv_field(const std::string& value) {
    if (value.find_first_of(",\"\r\n") == std::string::npos) {
      return value;
    }
    std::string escaped = "\"";
    for (char character : value) {
      escaped += character == '\"' ? "\"\"" : std::string(1, character);
    }
    escaped += '\"';
    return escaped;
  }

  static std::string sha256_text(const std::string& value) {
    gchar* digest = g_compute_checksum_for_string(G_CHECKSUM_SHA256, value.c_str(), -1);
    if (digest == nullptr) {
      throw std::runtime_error("failed to compute checkpoint stage-contract SHA-256");
    }
    std::string result(digest);
    g_free(digest);
    return result;
  }

  static std::string sha256_bytes(const std::vector<std::uint8_t>& value) {
    gchar* digest = g_compute_checksum_for_data(
        G_CHECKSUM_SHA256,
        reinterpret_cast<const guchar*>(value.data()),
        value.size());
    if (digest == nullptr) {
      throw std::runtime_error("failed to compute compressed access-unit SHA-256");
    }
    std::string result(digest);
    g_free(digest);
    return result;
  }

  static std::string sha256_file(const std::string& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input.is_open()) {
      throw std::runtime_error("failed to open runtime artifact for SHA-256: " + path);
    }
    GChecksum* checksum = g_checksum_new(G_CHECKSUM_SHA256);
    if (checksum == nullptr) {
      throw std::runtime_error("failed to initialize runtime artifact SHA-256");
    }
    std::array<char, 1024 * 1024> buffer{};
    while (input.good()) {
      input.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
      const auto count = input.gcount();
      if (count > 0) {
        g_checksum_update(
            checksum,
            reinterpret_cast<const guchar*>(buffer.data()),
            static_cast<gsize>(count));
      }
    }
    if (!input.eof()) {
      g_checksum_free(checksum);
      throw std::runtime_error("failed while hashing runtime artifact: " + path);
    }
    const gchar* digest = g_checksum_get_string(checksum);
    if (digest == nullptr) {
      g_checksum_free(checksum);
      throw std::runtime_error("failed to finalize runtime artifact SHA-256: " + path);
    }
    const std::string result(digest);
    g_checksum_free(checksum);
    return result;
  }

  struct StageArtifact {
    std::string role;
    std::string kind;
    std::string logical_name;
    std::string sha256;
  };

  static StageArtifact checkpoint_plugin_artifact(
      const std::string& role,
      const std::string& factory_name) {
    GstElementFactory* factory = gst_element_factory_find(factory_name.c_str());
    if (factory == nullptr) {
      throw std::runtime_error("failed to resolve loaded GStreamer factory artifact: " + factory_name);
    }
    GstPlugin* plugin = gst_plugin_feature_get_plugin(GST_PLUGIN_FEATURE(factory));
    if (plugin == nullptr) {
      gst_object_unref(factory);
      throw std::runtime_error("GStreamer factory has no loaded plugin artifact: " + factory_name);
    }
    const gchar* filename = gst_plugin_get_filename(plugin);
    if (filename == nullptr || std::string(filename).empty()) {
      gst_object_unref(plugin);
      gst_object_unref(factory);
      throw std::runtime_error("GStreamer plugin has no hashable runtime path: " + factory_name);
    }
    const std::string artifact_path(filename);
    gst_object_unref(plugin);
    gst_object_unref(factory);
    return StageArtifact{role, "plugin", factory_name, sha256_file(artifact_path)};
  }

  std::string checkpoint_artifact_manifest(
      const std::vector<std::pair<std::string, std::string>>& plugin_factories) const {
    std::vector<StageArtifact> artifacts = {
        StageArtifact{
            "stage_host",
            "executable",
            "vast_native_gst_probe",
            sha256_file(args_.executable_path),
        },
    };
    for (const auto& [role, factory_name] : plugin_factories) {
      artifacts.push_back(checkpoint_plugin_artifact(role, factory_name));
    }
    std::sort(
        artifacts.begin(),
        artifacts.end(),
        [](const StageArtifact& left, const StageArtifact& right) {
          return std::tie(left.role, left.kind, left.logical_name, left.sha256) <
                 std::tie(right.role, right.kind, right.logical_name, right.sha256);
        });
    for (std::size_t index = 1; index < artifacts.size(); ++index) {
      if (std::tie(artifacts[index - 1].role, artifacts[index - 1].kind, artifacts[index - 1].logical_name) ==
          std::tie(artifacts[index].role, artifacts[index].kind, artifacts[index].logical_name)) {
        throw std::runtime_error("duplicate checkpoint runtime artifact identity");
      }
    }
    std::ostringstream json;
    json << '[';
    for (std::size_t index = 0; index < artifacts.size(); ++index) {
      if (index != 0) {
        json << ',';
      }
      const StageArtifact& artifact = artifacts[index];
      json << "{\"kind\":\"" << artifact.kind
           << "\",\"logical_name\":\"" << artifact.logical_name
           << "\",\"role\":\"" << artifact.role
           << "\",\"sha256\":\"" << artifact.sha256 << "\"}";
    }
    json << ']';
    return json.str();
  }

  static std::string gstreamer_version() {
    guint major = 0;
    guint minor = 0;
    guint micro = 0;
    guint nano = 0;
    gst_version(&major, &minor, &micro, &nano);
    return std::to_string(major) + "." + std::to_string(minor) + "." +
           std::to_string(micro) + "." + std::to_string(nano);
  }

  std::string checkpoint_execution_domain() const {
    std::array<char, 256> hostname{};
    if (::gethostname(hostname.data(), hostname.size() - 1) != 0) {
      throw std::runtime_error("failed to resolve checkpoint worker hostname");
    }
    const char* worker_id = std::getenv("VAST_CHECKPOINT_WORKER_ID");
    if (worker_id == nullptr || std::string(worker_id).empty()) {
      throw std::runtime_error("missing checkpoint worker ID for semantic contract");
    }
    return std::string(hostname.data()) + ":pid-" + std::to_string(::getpid()) + ":worker-" + worker_id;
  }

  void write_checkpoint_stage_contract(
      const std::string& stage,
      const std::string& base_stage,
      const std::string& implementation_config_json,
      const std::string& implementation_artifacts_json,
      const std::string& transform_json,
      const std::string& output_shape_json) {
    const std::string execution_domain = checkpoint_execution_domain();
    const std::string contract_id = args_.run_id + ":" + execution_domain + ":" + stage;
    const std::vector<std::string> values = {
        "2",
        "2",
        args_.run_id,
        contract_id,
        execution_domain,
        stage,
        base_stage,
        "vast-native-gstreamer-checkpoint-" + base_stage,
        gstreamer_version(),
        implementation_config_json,
        sha256_text(implementation_config_json),
        implementation_artifacts_json,
        sha256_text(implementation_artifacts_json),
        "runtime_loaded_artifacts_v1",
        transform_json,
        "video/x-raw",
        "rgb24",
        "uint8",
        output_shape_json,
        "native_pts_preserved_with_gap_free_decode_order_admission_v3",
        "runtime_loaded_configuration",
        "native",
    };
    for (std::size_t index = 0; index < values.size(); ++index) {
      if (index != 0) {
        stage_contracts_ << ',';
      }
      stage_contracts_ << csv_field(values[index]);
    }
    stage_contracts_ << '\n';
    stage_contracts_.flush();
  }

  static std::string checkpoint_decoder_factory(GstElement* pipeline) {
    GstIterator* iterator = gst_bin_iterate_recurse(GST_BIN(pipeline));
    GValue item = G_VALUE_INIT;
    std::vector<std::string> factories;
    bool done = false;
    while (!done) {
      switch (gst_iterator_next(iterator, &item)) {
        case GST_ITERATOR_OK: {
          GstElement* element = GST_ELEMENT(g_value_get_object(&item));
          GstElementFactory* factory = gst_element_get_factory(element);
          if (factory != nullptr) {
            const gchar* klass = gst_element_factory_get_metadata(factory, GST_ELEMENT_METADATA_KLASS);
            const gchar* name = gst_plugin_feature_get_name(GST_PLUGIN_FEATURE(factory));
            if (klass != nullptr && name != nullptr && g_strrstr(klass, "Decoder") != nullptr &&
                g_strrstr(klass, "Video") != nullptr) {
              factories.emplace_back(name);
            }
          }
          g_value_reset(&item);
          break;
        }
        case GST_ITERATOR_RESYNC:
          gst_iterator_resync(iterator);
          break;
        case GST_ITERATOR_ERROR:
          g_value_unset(&item);
          gst_iterator_free(iterator);
          throw std::runtime_error("failed to inspect the runtime checkpoint decoder");
        case GST_ITERATOR_DONE:
          done = true;
          break;
      }
    }
    g_value_unset(&item);
    gst_iterator_free(iterator);
    std::sort(factories.begin(), factories.end());
    factories.erase(std::unique(factories.begin(), factories.end()), factories.end());
    if (factories.size() != 1) {
      throw std::runtime_error(
          "checkpoint runtime must expose exactly one loaded video decoder, observed=" +
          std::to_string(factories.size()));
    }
    if (factories.front().find_first_not_of(
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.+-") != std::string::npos) {
      throw std::runtime_error("checkpoint decoder factory name cannot be represented canonically");
    }
    return factories.front();
  }

  static void require_checkpoint_caps(GstPad* pad, int expected_width = 0, int expected_height = 0) {
    GstCaps* caps = gst_pad_get_current_caps(pad);
    if (caps == nullptr || gst_caps_is_empty(caps) || gst_caps_get_size(caps) != 1) {
      if (caps != nullptr) {
        gst_caps_unref(caps);
      }
      throw std::runtime_error("checkpoint stage has no single negotiated output caps");
    }
    const GstStructure* structure = gst_caps_get_structure(caps, 0);
    const gchar* media_type = gst_structure_get_name(structure);
    const gchar* format = gst_structure_get_string(structure, "format");
    int width = 0;
    int height = 0;
    const bool size_matches =
        (expected_width == 0 && expected_height == 0) ||
        (gst_structure_get_int(structure, "width", &width) &&
         gst_structure_get_int(structure, "height", &height) &&
         width == expected_width && height == expected_height);
    const bool matches = media_type != nullptr && std::string(media_type) == "video/x-raw" &&
                         format != nullptr && std::string(format) == "RGB" && size_matches;
    gst_caps_unref(caps);
    if (!matches) {
      throw std::runtime_error("checkpoint negotiated caps do not match the declared RGB stage contract");
    }
  }

  void write_checkpoint_decode_contract(GstElement* pipeline, GstPad* pad, const std::string& stage) {
    if (!written_checkpoint_stage_contracts_.insert(stage).second) {
      return;
    }
    require_checkpoint_caps(pad);
    const std::string decoder_factory = checkpoint_decoder_factory(pipeline);
    if (!checkpoint_allowed_decoder_factories_.empty() &&
        std::find(
            checkpoint_allowed_decoder_factories_.begin(),
            checkpoint_allowed_decoder_factories_.end(),
            decoder_factory) == checkpoint_allowed_decoder_factories_.end()) {
      std::ostringstream allowed;
      for (std::size_t index = 0; index < checkpoint_allowed_decoder_factories_.size(); ++index) {
        if (index != 0) {
          allowed << ',';
        }
        allowed << checkpoint_allowed_decoder_factories_[index];
      }
      throw std::runtime_error(
          "checkpoint decoder factory is outside the preregistered allowlist: observed=" +
          decoder_factory + " allowed=" + allowed.str());
    }
    const std::string decode_config =
        "{\"autoplugger\":\"decodebin\",\"backend\":\"gstreamer\","
        "\"caps\":\"video/x-raw,format=RGB\",\"decoder_factory\":\"" + decoder_factory +
        "\",\"pipeline_role\":\"checkpoint\",\"stage\":\"decode\","
        "\"video_convert\":\"videoconvert\"}";
    const std::string identity_transform =
        "{\"normalization\":{\"mode\":\"identity\"},\"resize\":{\"mode\":\"identity\"}}";
    write_checkpoint_stage_contract(
        stage,
        "decode",
        decode_config,
        checkpoint_artifact_manifest(
            {
                {"autoplugger", "decodebin"},
                {"decoder", decoder_factory},
                {"format_converter", "videoconvert"},
            }),
        identity_transform,
        "[\"source_height\",\"source_width\",3]");
    if (!checkpoint_allowed_decoder_factories_.empty() &&
        !checkpoint_decoder_placement_verified_.exchange(true)) {
      write_checkpoint_lifecycle_status("DECODER_PLACEMENT_VERIFIED", now_ms());
    }
  }

  void write_checkpoint_preprocess_contract(GstPad* pad, const std::string& stage) {
    if (!written_checkpoint_stage_contracts_.insert(stage).second) {
      return;
    }
    require_checkpoint_caps(pad, 640, 360);
    const std::string preprocess_config =
        "{\"caps\":\"video/x-raw,format=RGB,width=640,height=360\","
        "\"pipeline_role\":\"checkpoint\",\"stage\":\"preprocess\","
        "\"video_convert\":\"videoconvert\",\"video_scale\":\"videoscale\"}";
    const std::string preprocess_transform =
        "{\"normalization\":{\"mode\":\"identity\"},"
        "\"resize\":{\"algorithm\":\"gstreamer-default\",\"mode\":\"fixed\","
        "\"output_height\":360,\"output_width\":640}}";
    write_checkpoint_stage_contract(
        stage,
        "preprocess",
        preprocess_config,
        checkpoint_artifact_manifest(
            {
                {"caps_filter", "capsfilter"},
                {"format_converter", "videoconvert"},
                {"resizer", "videoscale"},
            }),
        preprocess_transform,
        "[360,640,3]");
  }

  static gboolean quit_loop(gpointer data) {
    auto* self = static_cast<NativeProbeRuntime*>(data);
    self->measurement_timer_id_.store(0);
    if (self->loop_ != nullptr) {
      g_main_loop_quit(self->loop_);
    }
    return G_SOURCE_REMOVE;
  }

  static void write_u16(std::uint8_t* out, std::uint16_t value) {
    out[0] = static_cast<std::uint8_t>((value >> 8) & 0xff);
    out[1] = static_cast<std::uint8_t>(value & 0xff);
  }

  static void write_u32(std::uint8_t* out, std::uint32_t value) {
    for (int i = 3; i >= 0; --i) {
      out[3 - i] = static_cast<std::uint8_t>((value >> (i * 8)) & 0xff);
    }
  }

  static void write_u64(std::uint8_t* out, std::uint64_t value) {
    for (int i = 7; i >= 0; --i) {
      out[7 - i] = static_cast<std::uint8_t>((value >> (i * 8)) & 0xff);
    }
  }

  static std::uint16_t read_u16(const std::uint8_t* in) {
    return static_cast<std::uint16_t>((in[0] << 8) | in[1]);
  }

  static std::uint32_t read_u32(const std::uint8_t* in) {
    std::uint32_t out = 0;
    for (int i = 0; i < 4; ++i) {
      out = (out << 8) | in[i];
    }
    return out;
  }

  static std::uint64_t read_u64(const std::uint8_t* in) {
    std::uint64_t out = 0;
    for (int i = 0; i < 8; ++i) {
      out = (out << 8) | in[i];
    }
    return out;
  }

  static std::array<std::uint8_t, kTracePayloadSize> pack_trace(const Trace& trace) {
    std::array<std::uint8_t, kTracePayloadSize> payload{};
    write_u16(payload.data(), kTraceMagic);
    payload[2] = kTraceVersion;
    payload[3] = trace.stream_id;
    write_u32(payload.data() + 4, trace.frame_id);
    write_u64(payload.data() + 8, trace.ingress_ms);
    return payload;
  }

  static bool unpack_trace(const std::uint8_t* payload, std::size_t size, Trace& out) {
    if (size != kTracePayloadSize) {
      return false;
    }
    if (read_u16(payload) != kTraceMagic || payload[2] != kTraceVersion) {
      return false;
    }
    out.stream_id = payload[3];
    out.frame_id = read_u32(payload + 4);
    out.ingress_ms = read_u64(payload + 8);
    return true;
  }

  static std::vector<std::string> parse_stage_names(const std::string& raw) {
    std::vector<std::string> stages;
    std::istringstream input(raw);
    std::string stage;
    while (std::getline(input, stage, ',')) {
      const auto first = stage.find_first_not_of(" \t\r\n");
      if (first == std::string::npos) {
        continue;
      }
      const auto last = stage.find_last_not_of(" \t\r\n");
      stages.push_back(stage.substr(first, last - first + 1));
    }
    return stages;
  }

  static bool valid_checkpoint_name(const std::string& value) {
    return !value.empty() && std::all_of(value.begin(), value.end(), [](unsigned char character) {
      return (character >= 'a' && character <= 'z') ||
             (character >= '0' && character <= '9') || character == '_';
    });
  }

  static bool valid_sha256(const std::string& value) {
    return value.size() == 64 && std::all_of(value.begin(), value.end(), [](unsigned char character) {
      return (character >= '0' && character <= '9') || (character >= 'a' && character <= 'f');
    });
  }

  static std::uint64_t parse_uint64(const std::string& raw, const char* name) {
    std::size_t consumed = 0;
    std::uint64_t value = 0;
    try {
      value = std::stoull(raw, &consumed);
    } catch (const std::exception&) {
      throw std::runtime_error(std::string("invalid checkpoint lifecycle integer: ") + name);
    }
    if (consumed != raw.size()) {
      throw std::runtime_error(std::string("invalid checkpoint lifecycle integer: ") + name);
    }
    return value;
  }

  static int required_checkpoint_fd(const char* name) {
    const char* raw = std::getenv(name);
    if (raw == nullptr || std::string(raw).empty()) {
      throw std::runtime_error(std::string("missing checkpoint lifecycle FD: ") + name);
    }
    const std::uint64_t value = parse_uint64(raw, name);
    if (value > static_cast<std::uint64_t>(std::numeric_limits<int>::max())) {
      throw std::runtime_error(std::string("checkpoint lifecycle FD is out of range: ") + name);
    }
    return static_cast<int>(value);
  }

  static std::string read_fd_line(int fd) {
    std::string line;
    char character = '\0';
    while (true) {
      const ssize_t result = ::read(fd, &character, 1);
      if (result < 0 && errno == EINTR) {
        continue;
      }
      if (result <= 0) {
        throw std::runtime_error("checkpoint lifecycle control pipe closed unexpectedly");
      }
      if (character == '\n') {
        return line;
      }
      line.push_back(character);
      if (line.size() > 4096) {
        throw std::runtime_error("checkpoint lifecycle control line is too long");
      }
    }
  }

  bool wait_for_checkpoint_stop_line(std::string& line) {
    while (!checkpoint_loop_finished_.load()) {
      pollfd descriptor{};
      descriptor.fd = checkpoint_control_fd_;
      descriptor.events = POLLIN;
      const int result = ::poll(&descriptor, 1, 100);
      if (result < 0 && errno == EINTR) {
        continue;
      }
      if (result < 0) {
        throw std::runtime_error("checkpoint lifecycle control poll failed");
      }
      if (result == 0) {
        continue;
      }
      if ((descriptor.revents & POLLIN) != 0) {
        line = read_fd_line(checkpoint_control_fd_);
        return true;
      }
      if ((descriptor.revents & (POLLERR | POLLHUP | POLLNVAL)) != 0) {
        throw std::runtime_error("checkpoint lifecycle control pipe closed before STOP");
      }
    }
    return false;
  }

  void write_checkpoint_lifecycle_status(const std::string& state, std::uint64_t timestamp) {
    std::lock_guard<std::mutex> lock(checkpoint_status_mutex_);
    const char* worker_id = std::getenv("VAST_CHECKPOINT_WORKER_ID");
    if (worker_id == nullptr || std::string(worker_id).empty()) {
      throw std::runtime_error("missing checkpoint worker ID for lifecycle status");
    }
    const std::string payload =
        "1 " + state + " " + std::string(worker_id) + " " + std::to_string(timestamp) + "\n";
    std::size_t offset = 0;
    while (offset < payload.size()) {
      const ssize_t written = ::write(
          checkpoint_status_fd_,
          payload.data() + offset,
          payload.size() - offset);
      if (written < 0 && errno == EINTR) {
        continue;
      }
      if (written <= 0) {
        throw std::runtime_error("failed to write checkpoint lifecycle status");
      }
      offset += static_cast<std::size_t>(written);
    }
  }

  void wait_for_checkpoint_start() {
    const std::string line = read_fd_line(checkpoint_control_fd_);
    std::istringstream input(line);
    std::string version;
    std::string command;
    std::string start_ns;
    std::string window_start_ms;
    std::string window_end_ms;
    std::string drain_end_ms;
    std::string extra;
    input >> version >> command >> start_ns >> window_start_ms >> window_end_ms >> drain_end_ms;
    if ((input >> extra) || version != "1" || command != "START") {
      throw std::runtime_error("invalid checkpoint START lifecycle command");
    }
    checkpoint_common_start_monotonic_ns_ = parse_uint64(start_ns, "start_monotonic_ns");
    checkpoint_window_start_ms_ = parse_uint64(window_start_ms, "window_start_timestamp_ms");
    checkpoint_window_end_ms_ = parse_uint64(window_end_ms, "window_end_timestamp_ms");
    checkpoint_drain_end_ms_ = parse_uint64(drain_end_ms, "drain_end_timestamp_ms");
    if (checkpoint_common_start_monotonic_ns_ < steady_now_ns() ||
        checkpoint_window_start_ms_ >= checkpoint_window_end_ms_ ||
        checkpoint_window_end_ms_ > checkpoint_drain_end_ms_) {
      throw std::runtime_error("checkpoint START lifecycle boundaries are invalid");
    }
  }

  bool checkpoint_state_drained() const {
    const StreamState& state = states_.front();
    const bool fanout_intervals_drained = std::all_of(
        state.checkpoint_fanout_starts_by_branch.begin(),
        state.checkpoint_fanout_starts_by_branch.end(),
        [](const auto& entry) { return entry.second.empty(); });
    return checkpoint_data_eof_.load() && state.checkpoint_deliveries_by_pts.empty() &&
           state.local_traces_by_pts.empty() && state.traces.empty() &&
           state.checkpoint_completed_branches_by_pts.empty() && fanout_intervals_drained;
  }

  void finish_checkpoint_drain(bool censored) {
    bool expected = false;
    if (!checkpoint_drain_reported_.compare_exchange_strong(expected, true)) {
      return;
    }
    try {
      write_checkpoint_lifecycle_status(
          censored ? "CENSORED" : "DRAINED",
          censored ? checkpoint_drain_end_ms_ : now_ms());
    } catch (const std::exception& exc) {
      failed_ = true;
      std::cerr << "[native-probe][checkpoint] " << exc.what() << "\n";
    }
    if (loop_ != nullptr) {
      g_main_loop_quit(loop_);
    }
  }

  void wait_for_checkpoint_stop() {
    try {
      std::string line;
      if (!wait_for_checkpoint_stop_line(line)) {
        return;
      }
      std::istringstream input(line);
      std::string version;
      std::string command;
      std::string window_end_ms;
      std::string extra;
      input >> version >> command >> window_end_ms;
      if ((input >> extra) || version != "1" || command != "STOP" ||
          parse_uint64(window_end_ms, "stop_window_end_timestamp_ms") != checkpoint_window_end_ms_) {
        throw std::runtime_error("invalid checkpoint STOP lifecycle command");
      }
      bool drained = false;
      {
        std::lock_guard<std::mutex> lock(mutex_);
        checkpoint_admission_stopped_.store(true);
        write_checkpoint_lifecycle_status("ADMISSION_STOPPED", checkpoint_window_end_ms_);
        drained = checkpoint_state_drained();
      }
      if (drained) {
        finish_checkpoint_drain(false);
        return;
      }
      while (!checkpoint_drain_reported_.load() && now_ms() < checkpoint_drain_end_ms_) {
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
      }
      if (!checkpoint_drain_reported_.load()) {
        finish_checkpoint_drain(true);
      }
    } catch (const std::exception& exc) {
      failed_ = true;
      std::cerr << "[native-probe][checkpoint] " << exc.what() << "\n";
      if (loop_ != nullptr) {
        g_main_loop_quit(loop_);
      }
    }
  }

  void initialize_checkpoint_runtime() {
    if (streams_ != 1) {
      throw std::runtime_error("checkpoint worker process must own exactly one logical stream");
    }
    if (args_.logical_stream_id < 0 ||
        args_.logical_stream_id > static_cast<int>(std::numeric_limits<std::uint8_t>::max())) {
      throw std::runtime_error("checkpoint worker logical stream ID must fit the trace uint8 field");
    }
    if (!valid_sha256(args_.source_sha256)) {
      throw std::runtime_error("checkpoint worker requires lowercase source SHA-256");
    }
    if (!valid_checkpoint_name(args_.dataset_id)) {
      throw std::runtime_error("checkpoint worker requires a lowercase dataset ID");
    }
    if (args_.checkpoint_container != "mp4") {
      throw std::runtime_error("checkpoint worker requires an MP4 source container");
    }
    if (args_.checkpoint_codec != "h264" && args_.checkpoint_codec != "h265") {
      throw std::runtime_error("checkpoint worker requires H.264 or H.265 source codec");
    }
    if (args_.source_duration_ns == 0) {
      throw std::runtime_error("checkpoint worker requires a positive source duration");
    }
    if (args_.source_replay != "continuous") {
      throw std::runtime_error("checkpoint worker requires continuous finite-source replay");
    }
    if (checkpoint_branches_.empty() ||
        std::any_of(checkpoint_branches_.begin(), checkpoint_branches_.end(), [](const std::string& branch) {
          return !NativeProbeRuntime::valid_checkpoint_name(branch);
        }) ||
        std::unordered_set<std::string>(checkpoint_branches_.begin(), checkpoint_branches_.end()).size() !=
            checkpoint_branches_.size()) {
      throw std::runtime_error("checkpoint worker requires unique lowercase branch names");
    }
    checkpoint_emitter_ = vast::CheckpointRuntimeEmitter::make_from_environment();
    checkpoint_control_fd_ = required_checkpoint_fd("VAST_CHECKPOINT_CONTROL_FD");
    checkpoint_status_fd_ = required_checkpoint_fd("VAST_CHECKPOINT_STATUS_FD");
    checkpoint_data_fd_ = required_checkpoint_fd("VAST_CHECKPOINT_ADMISSION_DATA_FD");
    const char* admission_mode = std::getenv("VAST_CHECKPOINT_ADMISSION_MODE");
    if (admission_mode == nullptr || std::string(admission_mode) != "native_common_source_coordinator") {
      throw std::runtime_error("checkpoint worker requires native common-source admission mode");
    }
    initialize_checkpoint_analytics_bridge();
  }

  bool native_checkpoint_analytics_enabled() const {
    return args_.checkpoint_analytics_mode == "native_terminal_socket_v1";
  }

  void initialize_checkpoint_analytics_bridge() {
    if (args_.checkpoint_analytics_mode == "topology_only") {
      ::unsetenv(vast::CheckpointAnalyticsTerminalTransport::kFdEnvironment);
      return;
    }
    if (!native_checkpoint_analytics_enabled()) {
      throw std::runtime_error("unsupported checkpoint analytics terminal mode");
    }
    if (args_.detect_bin.empty() || args_.detect_bin == "identity") {
      throw std::runtime_error("native checkpoint analytics mode requires a non-identity detect bin");
    }
    if (args_.detect_bin.find("{branch}") == std::string::npos) {
      throw std::runtime_error("native checkpoint analytics detect bin must contain the {branch} placeholder");
    }
    if (args_.detect_bin.find("vastanalyticsterminal") != std::string::npos) {
      if (args_.detect_bin.find("vastanalyticsqueue") == std::string::npos) {
        throw std::runtime_error(
            "vastanalyticsterminal requires vastanalyticsqueue immediately before each detector");
      }
      const std::array<const char*, 7> placeholders = {
          "{branch}",
          "{factory}",
          "{model_path}",
          "{model_sha256}",
          "{weights_sha256}",
          "{detector_id}",
          "{max_buffers}",
      };
      for (const char* placeholder : placeholders) {
        if (args_.detect_bin.find(placeholder) == std::string::npos) {
          throw std::runtime_error(
              std::string("vastanalyticsterminal detect bin lacks placeholder ") + placeholder);
        }
      }
      for (const std::string& branch : checkpoint_branches_) {
        (void)checkpoint_analytics_binding(branch, "FACTORY");
        (void)checkpoint_analytics_binding(branch, "MODEL_PATH");
        (void)checkpoint_analytics_binding(branch, "MODEL_SHA256");
        (void)checkpoint_analytics_binding(branch, "WEIGHTS_SHA256", true);
        (void)checkpoint_analytics_binding(branch, "DETECTOR_ID");
        const std::string raw_max_buffers = checkpoint_analytics_binding(branch, "MAX_BUFFERS");
        std::size_t consumed = 0;
        const unsigned long long max_buffers = std::stoull(raw_max_buffers, &consumed);
        if (consumed != raw_max_buffers.size() || max_buffers == 0) {
          throw std::runtime_error("checkpoint analytics MAX_BUFFERS must be a positive integer");
        }
      }
    }
    int descriptors[2] = {-1, -1};
    if (::socketpair(AF_UNIX, SOCK_DGRAM, 0, descriptors) != 0) {
      throw std::runtime_error("failed to create checkpoint analytics terminal socketpair");
    }
    checkpoint_analytics_terminal_read_fd_ = descriptors[0];
    checkpoint_analytics_terminal_write_fd_ = descriptors[1];
    const std::string write_fd = std::to_string(checkpoint_analytics_terminal_write_fd_);
    if (::setenv(
            vast::CheckpointAnalyticsTerminalTransport::kFdEnvironment,
            write_fd.c_str(),
            1) != 0) {
      close_checkpoint_analytics_bridge();
      throw std::runtime_error("failed to expose checkpoint analytics terminal socket");
    }
  }

  void close_checkpoint_analytics_bridge() {
    if (checkpoint_analytics_terminal_read_fd_ >= 0) {
      ::close(checkpoint_analytics_terminal_read_fd_);
      checkpoint_analytics_terminal_read_fd_ = -1;
    }
    if (checkpoint_analytics_terminal_write_fd_ >= 0) {
      ::close(checkpoint_analytics_terminal_write_fd_);
      checkpoint_analytics_terminal_write_fd_ = -1;
    }
    ::unsetenv(vast::CheckpointAnalyticsTerminalTransport::kFdEnvironment);
  }

  void start_checkpoint_analytics_terminal_reader() {
    if (!native_checkpoint_analytics_enabled()) {
      return;
    }
    if (checkpoint_analytics_terminal_read_fd_ < 0 || checkpoint_analytics_terminal_thread_.joinable()) {
      throw std::runtime_error("checkpoint analytics terminal bridge is not ready");
    }
    checkpoint_analytics_terminal_stop_.store(false);
    checkpoint_analytics_terminal_thread_ = std::thread([this]() {
      try {
        while (true) {
          pollfd descriptor{};
          descriptor.fd = checkpoint_analytics_terminal_read_fd_;
          descriptor.events = POLLIN;
          const int result = ::poll(&descriptor, 1, 50);
          if (result < 0 && errno == EINTR) {
            continue;
          }
          if (result < 0) {
            throw std::runtime_error("checkpoint analytics terminal poll failed");
          }
          if (result == 0) {
            if (checkpoint_analytics_terminal_stop_.load()) {
              return;
            }
            continue;
          }
          if ((descriptor.revents & POLLIN) != 0) {
            handle_checkpoint_analytics_terminal(
                vast::CheckpointAnalyticsTerminalTransport::receive(
                    checkpoint_analytics_terminal_read_fd_));
            continue;
          }
          throw std::runtime_error("checkpoint analytics terminal socket failed");
        }
      } catch (const std::exception& exc) {
        failed_ = true;
        std::cerr << "[native-probe][checkpoint-analytics] " << exc.what() << "\n";
        if (loop_ != nullptr) {
          g_main_loop_quit(loop_);
        }
      }
    });
  }

  void stop_checkpoint_analytics_terminal_reader() {
    checkpoint_analytics_terminal_stop_.store(true);
    if (checkpoint_analytics_terminal_thread_.joinable()) {
      checkpoint_analytics_terminal_thread_.join();
    }
    close_checkpoint_analytics_bridge();
  }

  std::string checkpoint_input_frame_key(const Trace& trace) const {
    return args_.dataset_id + ":" + std::to_string(args_.logical_stream_id) + ":" +
           args_.source_sha256 + ":" + std::to_string(trace.source_cycle) + ":" +
           std::to_string(trace.source_pts_ns);
  }

  std::string checkpoint_execution_id(
      const Trace& trace,
      const std::string& branch,
      const std::string& suffix) const {
    return trace_id(trace) + ":" + branch + ":" + suffix;
  }

  void emit_checkpoint_event(
      const Trace& trace,
      std::uint64_t pts,
      const std::string& event_kind,
      const std::string& stage,
      const std::string& branch,
      const std::string& suffix,
      const std::vector<std::string>& parents,
      std::uint64_t timestamp_ms) {
    (void)pts;
    if (!checkpoint_emitter_) {
      throw std::runtime_error("checkpoint runtime emitter is not initialized");
    }
    if (trace.admission_id.empty() || !valid_sha256(trace.payload_sha256)) {
      throw std::runtime_error("checkpoint trace lacks verified direct-admission linkage");
    }
    checkpoint_emitter_->emit_with_admission(
        trace_id(trace),
        trace.frame_id,
        checkpoint_input_frame_key(trace),
        event_kind,
        stage,
        branch,
        checkpoint_execution_id(trace, branch, suffix),
        parents,
        timestamp_ms,
        trace.admission_id,
        trace.payload_sha256);
  }

  void emit_checkpoint_branch_terminal(
      const Trace& trace,
      const vast::CheckpointAnalyticsTerminal& terminal,
      const std::vector<std::string>& parents,
      std::uint64_t timestamp_ms) {
    if (!checkpoint_emitter_) {
      throw std::runtime_error("checkpoint runtime emitter is not initialized");
    }
    if (trace.admission_id.empty() || !valid_sha256(trace.payload_sha256)) {
      throw std::runtime_error("checkpoint terminal trace lacks verified direct-admission linkage");
    }
    const bool dropped = terminal.status == vast::CheckpointAnalyticsTerminalStatus::kDrop;
    checkpoint_emitter_->emit_branch_terminal_with_admission(
        trace_id(trace),
        trace.frame_id,
        checkpoint_input_frame_key(trace),
        dropped ? "branch_drop" : "branch_complete",
        terminal.branch_id,
        terminal.branch_id,
        checkpoint_execution_id(trace, terminal.branch_id, dropped ? "drop" : "complete"),
        parents,
        timestamp_ms,
        trace.admission_id,
        trace.payload_sha256,
        terminal.terminal_reason,
        terminal.objects,
        terminal.detector,
        terminal.backend);
  }

  void handle_checkpoint_analytics_terminal(
      const vast::CheckpointAnalyticsTerminal& terminal) {
    const std::uint64_t timestamp_ms = now_ms();
    std::lock_guard<std::mutex> lock(mutex_);
    if (!native_checkpoint_analytics_enabled()) {
      throw std::runtime_error("received a native analytics terminal in topology-only mode");
    }
    if (std::find(
            checkpoint_branches_.begin(),
            checkpoint_branches_.end(),
            terminal.branch_id) == checkpoint_branches_.end()) {
      throw std::runtime_error("checkpoint analytics terminal selected an undeclared branch");
    }
    if (args_.role == "checkpoint_branch" && terminal.branch_id != args_.checkpoint_branch) {
      throw std::runtime_error("checkpoint branch worker received another branch terminal");
    }
    StreamState& state = states_.front();
    const auto trace_it = state.local_traces_by_pts.find(terminal.transport_pts_ns);
    if (trace_it == state.local_traces_by_pts.end()) {
      throw std::runtime_error("checkpoint analytics terminal has no admitted transport PTS");
    }
    const Trace trace = trace_it->second;
    const std::string prefix_parent = args_.role == "checkpoint_shared"
                                          ? checkpoint_execution_id(trace, terminal.branch_id, "fanout")
                                          : checkpoint_execution_id(trace, terminal.branch_id, "preprocess");
    if (terminal.status == vast::CheckpointAnalyticsTerminalStatus::kCompleted) {
      const std::string analytics_id = checkpoint_execution_id(trace, terminal.branch_id, "analytics");
      emit_checkpoint_event(
          trace,
          terminal.transport_pts_ns,
          "stage_complete",
          terminal.branch_id,
          terminal.branch_id,
          "analytics",
          {prefix_parent},
          timestamp_ms);
      write_event(trace, terminal.branch_id, timestamp_ms, timestamp_ms);
      emit_checkpoint_branch_terminal(trace, terminal, {analytics_id}, timestamp_ms);
    } else {
      emit_checkpoint_branch_terminal(trace, terminal, {prefix_parent}, timestamp_ms);
    }
    auto& terminal_branches = state.checkpoint_completed_branches_by_pts[terminal.transport_pts_ns];
    if (!terminal_branches.insert(terminal.branch_id).second) {
      throw std::runtime_error("duplicate checkpoint analytics terminal for one branch and frame");
    }
    if (terminal_branches.size() == checkpoint_branches_.size()) {
      state.checkpoint_completed_branches_by_pts.erase(terminal.transport_pts_ns);
      state.local_traces_by_pts.erase(trace_it);
      state.traces.erase(
          std::remove_if(
              state.traces.begin(),
              state.traces.end(),
              [&](const Trace& pending) { return pending.frame_id == trace.frame_id; }),
          state.traces.end());
    }
    if (checkpoint_admission_stopped_.load() && checkpoint_state_drained()) {
      finish_checkpoint_drain(false);
    }
  }

  void feed_checkpoint_access_units() {
    GstElement* appsrc_element = nullptr;
    try {
      if (pipelines_.size() != 1) {
        throw std::runtime_error("checkpoint worker requires exactly one appsrc pipeline");
      }
      appsrc_element = gst_bin_get_by_name(GST_BIN(pipelines_.front()), "checkpoint_appsrc0");
      if (appsrc_element == nullptr || !GST_IS_APP_SRC(appsrc_element)) {
        throw std::runtime_error("checkpoint worker appsrc was not found");
      }
      vast::CheckpointAdmissionFrame frame;
      while (vast::CheckpointAdmissionTransport::read_frame(checkpoint_data_fd_, frame)) {
        if (sha256_bytes(frame.payload) != frame.payload_sha256) {
          throw std::runtime_error("checkpoint worker received an AU with a mismatched payload SHA-256");
        }
        Trace trace;
        trace.stream_id = static_cast<std::uint8_t>(args_.logical_stream_id);
        trace.source_cycle = frame.source_cycle;
        trace.source_pts_ns = frame.access_unit_pts_ns;
        trace.admission_id = frame.admission_id;
        trace.payload_sha256 = frame.payload_sha256;
        {
          std::lock_guard<std::mutex> lock(mutex_);
          StreamState& state = states_.front();
          if (!state.checkpoint_deliveries_by_pts.emplace(frame.transport_pts_ns, trace).second) {
            throw std::runtime_error("checkpoint worker received duplicate transport PTS");
          }
        }

        GstBuffer* buffer = gst_buffer_new_allocate(nullptr, frame.payload.size(), nullptr);
        if (buffer == nullptr ||
            gst_buffer_fill(buffer, 0, frame.payload.data(), frame.payload.size()) != frame.payload.size()) {
          if (buffer != nullptr) {
            gst_buffer_unref(buffer);
          }
          throw std::runtime_error("failed to allocate checkpoint appsrc AU buffer");
        }
        GST_BUFFER_PTS(buffer) = frame.transport_pts_ns;
        GST_BUFFER_DTS(buffer) =
            frame.access_unit_dts_ns == vast::CheckpointAdmissionTransport::kMissingTimestamp
                ? GST_CLOCK_TIME_NONE
                : frame.source_cycle * args_.source_duration_ns + frame.access_unit_dts_ns;
        GST_BUFFER_DURATION(buffer) = frame.duration_ns == 0 ? GST_CLOCK_TIME_NONE : frame.duration_ns;
        const GstFlowReturn flow = gst_app_src_push_buffer(GST_APP_SRC(appsrc_element), buffer);
        if (flow != GST_FLOW_OK) {
          throw std::runtime_error("checkpoint appsrc rejected a framed compressed access unit");
        }
      }
      checkpoint_data_eof_.store(true);
      gst_app_src_end_of_stream(GST_APP_SRC(appsrc_element));
      bool drained = false;
      {
        std::lock_guard<std::mutex> lock(mutex_);
        drained = checkpoint_state_drained();
      }
      if (checkpoint_admission_stopped_.load() && drained) {
        finish_checkpoint_drain(false);
      }
    } catch (const std::exception& exc) {
      failed_ = true;
      std::cerr << "[native-probe][checkpoint] " << exc.what() << "\n";
      if (loop_ != nullptr) {
        g_main_loop_quit(loop_);
      }
    }
    if (appsrc_element != nullptr) {
      gst_object_unref(appsrc_element);
    }
  }

  static std::string stage_probe_name(const std::string& stage, int stream_id) {
    return stage + "_probe" + std::to_string(stream_id);
  }

  static bool is_branch_suffix(const std::string& suffix) {
    return suffix == "a" || suffix == "b" || suffix == "primary" ||
           suffix == "secondary" || suffix == "left" || suffix == "right";
  }

  static bool is_stage_base_name(const std::string& value) {
    return value == "decode" || value == "preprocess" || value == "detect" || value == "track" ||
           value == "classify" || value == "aggregate" || value == "record" || value == "visualize";
  }

  static std::string stage_base_name(const std::string& stage) {
    const auto first = stage.find('_');
    if (first != std::string::npos) {
      const std::string prefix = stage.substr(0, first);
      if (is_stage_base_name(prefix)) {
        return prefix;
      }
    }
    const auto pos = stage.rfind('_');
    if (pos == std::string::npos || pos == 0 || pos + 1 >= stage.size()) {
      return stage;
    }
    const std::string base = stage.substr(0, pos);
    const std::string suffix = stage.substr(pos + 1);
    if (is_branch_suffix(suffix) && is_stage_base_name(base)) {
      return base;
    }
    return stage;
  }

  std::size_t first_stage_index_with_base(const std::string& base) const {
    for (std::size_t index = 0; index < stage_names_.size(); ++index) {
      if (stage_base_name(stage_names_[index]) == base) {
        return index;
      }
    }
    return stage_names_.size();
  }

  std::string first_stage_with_base(const std::string& base) const {
    const std::size_t index = first_stage_index_with_base(base);
    return index < stage_names_.size() ? stage_names_[index] : base;
  }

  static std::vector<std::string> parse_json_string_array(const std::string& raw) {
    std::vector<std::string> values;
    std::string current;
    bool in_string = false;
    bool escape = false;
    for (char c : raw) {
      if (!in_string) {
        if (c == '"') {
          in_string = true;
          current.clear();
        }
        continue;
      }
      if (escape) {
        current.push_back(c);
        escape = false;
      } else if (c == '\\') {
        escape = true;
      } else if (c == '"') {
        values.push_back(current);
        in_string = false;
      } else {
        current.push_back(c);
      }
    }
    return values;
  }

  std::string source_for_stream(int stream_id) const {
    if (!sources_.empty()) {
      fs::path source = sources_[static_cast<std::size_t>(stream_id) % sources_.size()];
      if (source.is_relative()) {
        source = fs::current_path() / source;
      }
      return source.string();
    }
    return args_.video_layout_dir + "/stream" + (stream_id + 1 < 10 ? "0" : "") + std::to_string(stream_id + 1) + ".mp4";
  }

  std::string uri_for_stream(int stream_id) const {
    const std::string source = source_for_stream(stream_id);
    if (source.find("://") != std::string::npos) {
      return source;
    }
    GError* error = nullptr;
    gchar* uri = g_filename_to_uri(source.c_str(), nullptr, &error);
    if (uri == nullptr) {
      std::string message = error != nullptr ? error->message : "unknown URI conversion error";
      if (error != nullptr) {
        g_error_free(error);
      }
      throw std::runtime_error("failed to convert source path to URI: " + source + ": " + message);
    }
    std::string out(uri);
    g_free(uri);
    return out;
  }

  int object_count() const {
    return std::max(args_.min_objects, std::min(args_.max_objects, (args_.min_objects + args_.max_objects) / 2));
  }

  std::string trace_id(const Trace& trace) const {
    return args_.run_id + ":" + std::to_string(trace.stream_id) + ":" + std::to_string(trace.frame_id);
  }

  static std::uint64_t frame_key(const Trace& trace) {
    return (static_cast<std::uint64_t>(trace.stream_id) << 32) | static_cast<std::uint64_t>(trace.frame_id);
  }

  void open_outputs() {
    fs::create_directories(args_.output_dir);
    events_.open((fs::path(args_.output_dir) / "frame_events.csv").string(), std::ios::out | std::ios::trunc);
    if (!events_.is_open()) {
      throw std::runtime_error("failed to open frame_events.csv");
    }
    events_ << "schema_version,run_id,trace_id,stream_id,frame_id,stage,role,host,resource,"
               "queue_enter_timestamp_ms,stage_start_timestamp_ms,stage_end_timestamp_ms,queue_depth,estimated_cost_ms,policy_action\n";
    if (args_.role == "aggregator" || args_.role == "local") {
      frames_.open((fs::path(args_.output_dir) / "frames.csv").string(), std::ios::out | std::ios::trunc);
      if (!frames_.is_open()) {
        throw std::runtime_error("failed to open frames.csv");
      }
      frames_ << "schema_version,run_id,trace_id,stream_id,frame_id,ingress_timestamp_ms,egress_timestamp_ms,"
                 "e2e_latency_ms,objects,detector,backend,telemetry_source\n";
    }
    if (args_.role == "checkpoint_branch" || args_.role == "checkpoint_shared") {
      stage_contracts_.open(
          (fs::path(args_.output_dir) / "stage_contracts.runtime.csv").string(),
          std::ios::out | std::ios::trunc);
      if (!stage_contracts_.is_open()) {
        throw std::runtime_error("failed to open stage_contracts.runtime.csv");
      }
      stage_contracts_
          << "schema_version,semantic_contract_version,run_id,contract_id,execution_domain,stage,base_stage,"
             "implementation_name,implementation_version,implementation_config_json,config_sha256,"
             "implementation_artifacts_json,implementation_artifacts_sha256,implementation_artifact_provenance,"
             "transform_json,"
             "output_media_type,output_format,output_dtype,output_shape_json,ordering_contract,contract_provenance,"
             "telemetry_source\n";
      stage_contracts_.flush();
    }
    if (args_.role == "checkpoint_shared") {
      checkpoint_resource_interval_emitter_ =
          std::make_unique<vast::CheckpointResourceIntervalEmitter>(
              (fs::path(args_.output_dir) /
               vast::CheckpointResourceIntervalEmitter::kRuntimeFilename)
                  .string());
    }
  }

  void write_event(const Trace& trace, const std::string& stage, std::uint64_t start_ms, std::uint64_t end_ms) {
    start_measurement_timer_if_needed();
    std::ostringstream row;
    row << "2," << args_.run_id << "," << trace_id(trace) << "," << static_cast<int>(trace.stream_id) << ","
        << trace.frame_id << "," << stage << "," << args_.role << ",localhost,cpu," << start_ms << ","
        << start_ms << "," << end_ms << ",0," << std::max<std::uint64_t>(1, end_ms - start_ms)
        << ",native:" << args_.system << "\n";
    std::lock_guard<std::mutex> lock(output_mutex_);
    events_ << row.str();
    events_.flush();
  }

  void write_stage_events(const Trace& trace, const std::vector<std::string>& stages, std::uint64_t start_ms, std::uint64_t end_ms) {
    if (stages.empty()) {
      return;
    }
    if (end_ms < start_ms) {
      end_ms = start_ms;
    }
    const std::uint64_t span = std::max<std::uint64_t>(1, end_ms - start_ms);
    const std::uint64_t step = std::max<std::uint64_t>(1, span / static_cast<std::uint64_t>(stages.size()));
    std::uint64_t cursor = start_ms;
    for (std::size_t index = 0; index < stages.size(); ++index) {
      std::uint64_t stage_end = index + 1 == stages.size() ? end_ms : std::min<std::uint64_t>(end_ms, cursor + step);
      if (stage_end < cursor) {
        stage_end = cursor;
      }
      write_event(trace, stages[index], cursor, stage_end);
      cursor = stage_end;
    }
  }

  void start_measurement_timer_if_needed() {
    if (is_checkpoint_role()) {
      return;
    }
    bool expected = false;
    if (!measurement_started_.compare_exchange_strong(expected, true)) {
      return;
    }
    const guint timer = g_timeout_add_seconds(
        static_cast<guint>(std::max(1, args_.duration_s)),
        &NativeProbeRuntime::quit_loop,
        this);
    measurement_timer_id_.store(timer);
    std::cerr << "[native-probe] measurement timer started duration_s=" << args_.duration_s << "\n";
  }

  void write_frame(const Trace& trace, std::uint64_t egress_ms) {
    const std::uint64_t ingress = trace.ingress_ms;
    const std::uint64_t latency = egress_ms >= ingress ? egress_ms - ingress : 0;
    std::ostringstream row;
    row << "2," << args_.run_id << "," << trace_id(trace) << "," << static_cast<int>(trace.stream_id) << ","
        << trace.frame_id << "," << ingress << "," << egress_ms << "," << latency << "," << object_count()
        << "," << args_.detector << "," << args_.backend << ",native\n";
    std::lock_guard<std::mutex> lock(output_mutex_);
    if (!written_frame_keys_.insert(frame_key(trace)).second) {
      return;
    }
    frames_ << row.str();
    frames_.flush();
  }

  void stop_pipelines() {
    for (GstElement* pipeline : pipelines_) {
      if (pipeline != nullptr) {
        gst_element_set_state(pipeline, GST_STATE_NULL);
      }
    }
    for (GstElement* pipeline : pipelines_) {
      if (pipeline != nullptr) {
        gst_element_get_state(pipeline, nullptr, nullptr, 5 * GST_SECOND);
      }
    }
  }

  void flush_outputs() {
    std::lock_guard<std::mutex> lock(output_mutex_);
    events_.flush();
    frames_.flush();
    stage_contracts_.flush();
  }

  struct ProbeContext {
    NativeProbeRuntime* runtime = nullptr;
    GstElement* pipeline = nullptr;
    int stream_id = 0;
    std::string kind;
    std::string stage;
    bool final_stage = false;
    std::string branch;
  };

  static GstPadProbeReturn edge_pay_probe(GstPad*, GstPadProbeInfo* info, gpointer data) {
    auto* ctx = static_cast<ProbeContext*>(data);
    auto* self = ctx->runtime;
    auto handle_buffer = [&](GstBuffer* buffer) {
      if (buffer == nullptr) {
        return;
      }
      GstRTPBuffer read_rtp = GST_RTP_BUFFER_INIT;
      if (!gst_rtp_buffer_map(buffer, GST_MAP_READ, &read_rtp)) {
        return;
      }
      const bool marker = gst_rtp_buffer_get_marker(&read_rtp);
      gst_rtp_buffer_unmap(&read_rtp);

      Trace trace;
      bool completed_frame = false;
      {
        std::lock_guard<std::mutex> lock(self->mutex_);
        StreamState& state = self->states_[static_cast<std::size_t>(ctx->stream_id)];
        if (!state.has_output_trace) {
          state.current_output_trace.stream_id = static_cast<std::uint8_t>(ctx->stream_id);
          state.current_output_trace.frame_id = state.edge_frame_id++;
          state.current_output_trace.ingress_ms = now_ms();
          state.has_output_trace = true;
        }
        trace = state.current_output_trace;
        if (marker) {
          state.has_output_trace = false;
          completed_frame = true;
        }
      }

      GstRTPBuffer write_rtp = GST_RTP_BUFFER_INIT;
      if (!gst_rtp_buffer_map(buffer, GST_MAP_READWRITE, &write_rtp)) {
        return;
      }
      const auto payload = pack_trace(trace);
      gst_rtp_buffer_add_extension_onebyte_header(&write_rtp, kTraceExtensionId, payload.data(), payload.size());
      gst_rtp_buffer_unmap(&write_rtp);

      if (completed_frame) {
        const std::uint64_t end = now_ms();
        self->write_stage_events(trace, self->stage_names_, trace.ingress_ms, end);
      }
    };

    if (GST_PAD_PROBE_INFO_TYPE(info) & GST_PAD_PROBE_TYPE_BUFFER_LIST) {
      GstBufferList* list = GST_PAD_PROBE_INFO_BUFFER_LIST(info);
      if (list == nullptr) {
        return GST_PAD_PROBE_OK;
      }
      list = gst_buffer_list_make_writable(list);
      GST_PAD_PROBE_INFO_DATA(info) = list;
      for (guint index = 0; index < gst_buffer_list_length(list); ++index) {
        handle_buffer(gst_buffer_list_get_writable(list, index));
      }
    } else if (GstBuffer* buffer = GST_PAD_PROBE_INFO_BUFFER(info); buffer != nullptr) {
      buffer = gst_buffer_make_writable(buffer);
      GST_PAD_PROBE_INFO_DATA(info) = buffer;
      handle_buffer(buffer);
    }
    return GST_PAD_PROBE_OK;
  }

  static bool extract_trace(GstBuffer* buffer, Trace& trace) {
    GstRTPBuffer rtp = GST_RTP_BUFFER_INIT;
    if (!gst_rtp_buffer_map(buffer, GST_MAP_READ, &rtp)) {
      return false;
    }
    gpointer data = nullptr;
    guint size = 0;
    const bool ok = gst_rtp_buffer_get_extension_onebyte_header(&rtp, kTraceExtensionId, 0, &data, &size) &&
                    data != nullptr && unpack_trace(static_cast<const std::uint8_t*>(data), size, trace);
    gst_rtp_buffer_unmap(&rtp);
    return ok;
  }

  static GstPadProbeReturn input_rtp_probe(GstPad*, GstPadProbeInfo* info, gpointer data) {
    auto* ctx = static_cast<ProbeContext*>(data);
    auto* self = ctx->runtime;
    auto handle_buffer = [&](GstBuffer* buffer) {
      if (buffer == nullptr) {
        return;
      }
      Trace trace;
      if (!extract_trace(buffer, trace)) {
        return;
      }
      const std::uint64_t end = now_ms();
      bool write_aggregate = false;
      {
        std::lock_guard<std::mutex> lock(self->mutex_);
        StreamState& state = self->states_[static_cast<std::size_t>(ctx->stream_id)];
        if (state.has_last_input_frame && state.last_input_frame_id == trace.frame_id) {
          return;
        }
        state.last_input_frame_id = trace.frame_id;
        state.has_last_input_frame = true;
        if (self->args_.role == "gpu_worker") {
          state.traces.push_back(trace);
        } else if (self->args_.role == "aggregator") {
          write_aggregate = true;
        }
      }
      if (write_aggregate) {
        const std::uint64_t start = end > self->stage_names_.size() ? end - self->stage_names_.size() : end;
        self->write_stage_events(trace, self->stage_names_, start, end);
        self->write_frame(trace, end);
      }
    };
    if (GST_PAD_PROBE_INFO_TYPE(info) & GST_PAD_PROBE_TYPE_BUFFER_LIST) {
      GstBufferList* list = GST_PAD_PROBE_INFO_BUFFER_LIST(info);
      if (list != nullptr) {
        for (guint index = 0; index < gst_buffer_list_length(list); ++index) {
          handle_buffer(gst_buffer_list_get(list, index));
        }
      }
    } else {
      handle_buffer(GST_PAD_PROBE_INFO_BUFFER(info));
    }
    return GST_PAD_PROBE_OK;
  }

  static GstPadProbeReturn worker_pay_probe(GstPad*, GstPadProbeInfo* info, gpointer data) {
    auto* ctx = static_cast<ProbeContext*>(data);
    auto* self = ctx->runtime;
    auto handle_buffer = [&](GstBuffer* buffer) {
      if (buffer == nullptr) {
        return;
      }
      GstRTPBuffer read_rtp = GST_RTP_BUFFER_INIT;
      if (!gst_rtp_buffer_map(buffer, GST_MAP_READ, &read_rtp)) {
        return;
      }
      const bool marker = gst_rtp_buffer_get_marker(&read_rtp);
      gst_rtp_buffer_unmap(&read_rtp);

      Trace trace;
      bool completed_frame = false;
      {
        std::lock_guard<std::mutex> lock(self->mutex_);
        StreamState& state = self->states_[static_cast<std::size_t>(ctx->stream_id)];
        if (!state.has_output_trace) {
          if (state.traces.empty()) {
            return;
          }
          state.current_output_trace = state.traces.front();
          state.traces.pop_front();
          state.has_output_trace = true;
        }
        trace = state.current_output_trace;
        if (marker) {
          state.has_output_trace = false;
          completed_frame = true;
        }
      }

      GstRTPBuffer write_rtp = GST_RTP_BUFFER_INIT;
      if (!gst_rtp_buffer_map(buffer, GST_MAP_READWRITE, &write_rtp)) {
        return;
      }
      const auto payload = pack_trace(trace);
      gst_rtp_buffer_add_extension_onebyte_header(&write_rtp, kTraceExtensionId, payload.data(), payload.size());
      gst_rtp_buffer_unmap(&write_rtp);

      if (completed_frame) {
        const std::uint64_t end = now_ms();
        const std::uint64_t start = end > self->stage_names_.size() ? end - self->stage_names_.size() : end;
        self->write_stage_events(trace, self->stage_names_, start, end);
      }
    };

    if (GST_PAD_PROBE_INFO_TYPE(info) & GST_PAD_PROBE_TYPE_BUFFER_LIST) {
      GstBufferList* list = GST_PAD_PROBE_INFO_BUFFER_LIST(info);
      if (list == nullptr) {
        return GST_PAD_PROBE_OK;
      }
      list = gst_buffer_list_make_writable(list);
      GST_PAD_PROBE_INFO_DATA(info) = list;
      for (guint index = 0; index < gst_buffer_list_length(list); ++index) {
        handle_buffer(gst_buffer_list_get_writable(list, index));
      }
    } else if (GstBuffer* buffer = GST_PAD_PROBE_INFO_BUFFER(info); buffer != nullptr) {
      buffer = gst_buffer_make_writable(buffer);
      GST_PAD_PROBE_INFO_DATA(info) = buffer;
      handle_buffer(buffer);
    }
    return GST_PAD_PROBE_OK;
  }

  static GstPadProbeReturn local_stage_probe(GstPad*, GstPadProbeInfo* info, gpointer data) {
    auto* ctx = static_cast<ProbeContext*>(data);
    auto* self = ctx->runtime;
    GstBuffer* buffer = GST_PAD_PROBE_INFO_BUFFER(info);
    if (buffer == nullptr) {
      return GST_PAD_PROBE_OK;
    }

    const std::uint64_t end = now_ms();
    const std::uint64_t pts = GST_BUFFER_PTS_IS_VALID(buffer) ? GST_BUFFER_PTS(buffer) : GST_CLOCK_TIME_NONE;
    std::lock_guard<std::mutex> lock(self->mutex_);
    StreamState& state = self->states_[static_cast<std::size_t>(ctx->stream_id)];
    Trace trace;
    if (ctx->kind == "local-decode") {
      trace.stream_id = static_cast<std::uint8_t>(ctx->stream_id);
      trace.frame_id = state.local_frame_id++;
      trace.ingress_ms = end;
      if (pts != GST_CLOCK_TIME_NONE) {
        state.local_traces_by_pts[pts] = trace;
      }
      state.traces.push_back(trace);
      self->write_event(trace, ctx->stage, trace.ingress_ms, end);
      if (ctx->final_stage) {
        self->write_frame(trace, end);
      }
      return GST_PAD_PROBE_OK;
    }

    const auto trace_it = state.local_traces_by_pts.find(pts);
    bool matched_by_pts = trace_it != state.local_traces_by_pts.end();
    if (matched_by_pts) {
      trace = trace_it->second;
    } else {
      if (state.traces.empty()) {
        return GST_PAD_PROBE_OK;
      }
      trace = state.traces.front();
      if (pts != GST_CLOCK_TIME_NONE) {
        state.local_traces_by_pts[pts] = trace;
        matched_by_pts = true;
      }
    }
    self->write_event(trace, ctx->stage, end > 1 ? end - 1 : end, end);
    if (ctx->final_stage) {
      self->write_frame(trace, end);
      if (matched_by_pts) {
        state.local_traces_by_pts.erase(pts);
      }
      state.traces.erase(
          std::remove_if(
              state.traces.begin(),
              state.traces.end(),
              [&](const Trace& pending) { return pending.frame_id == trace.frame_id; }),
          state.traces.end());
    }
    return GST_PAD_PROBE_OK;
  }

  static GstPadProbeReturn checkpoint_stage_probe(GstPad* pad, GstPadProbeInfo* info, gpointer data) {
    auto* ctx = static_cast<ProbeContext*>(data);
    auto* self = ctx->runtime;
    GstBuffer* buffer = GST_PAD_PROBE_INFO_BUFFER(info);
    if (buffer == nullptr) {
      return GST_PAD_PROBE_OK;
    }
    if (!GST_BUFFER_PTS_IS_VALID(buffer)) {
      self->failed_ = true;
      std::cerr << "[native-probe][checkpoint] buffer has no native PTS\n";
      if (self->loop_ != nullptr) {
        g_main_loop_quit(self->loop_);
      }
      return GST_PAD_PROBE_DROP;
    }

    const std::uint64_t pts = GST_BUFFER_PTS(buffer);
    std::lock_guard<std::mutex> lock(self->mutex_);
    const std::uint64_t event_timestamp_ns = now_ns();
    const std::uint64_t end = event_timestamp_ns / 1'000'000;
    StreamState& state = self->states_[static_cast<std::size_t>(ctx->stream_id)];
    Trace trace;
    if (ctx->kind == "checkpoint-ingress") {
      if (end > self->checkpoint_drain_end_ms_) {
        return GST_PAD_PROBE_DROP;
      }
      const auto delivery_it = state.checkpoint_deliveries_by_pts.find(pts);
      if (delivery_it == state.checkpoint_deliveries_by_pts.end()) {
        self->failed_ = true;
        std::cerr << "[native-probe][checkpoint] appsrc AU has no direct-admission transport metadata\n";
        if (self->loop_ != nullptr) {
          g_main_loop_quit(self->loop_);
        }
        return GST_PAD_PROBE_DROP;
      }
      trace = delivery_it->second;
      state.checkpoint_deliveries_by_pts.erase(delivery_it);
      trace.frame_id = state.local_frame_id++;
      trace.ingress_ms = end;
      if (!state.local_traces_by_pts.emplace(pts, trace).second) {
        self->failed_ = true;
        std::cerr << "[native-probe][checkpoint] duplicate appsrc transport PTS\n";
        if (self->loop_ != nullptr) {
          g_main_loop_quit(self->loop_);
        }
        return GST_PAD_PROBE_DROP;
      }
      state.traces.push_back(trace);
      const std::string branch = self->args_.role == "checkpoint_shared" ? "shared" : self->args_.checkpoint_branch;
      self->emit_checkpoint_event(trace, pts, "source_read", "source", branch, "source", {}, end);
      return GST_PAD_PROBE_OK;
    }

    if (ctx->kind == "checkpoint-branch" && self->native_checkpoint_analytics_enabled()) {
      // In native mode only the analytics adapter terminal socket may close a branch.
      return GST_PAD_PROBE_OK;
    }

    const auto trace_it = state.local_traces_by_pts.find(pts);
    if (trace_it == state.local_traces_by_pts.end()) {
      self->failed_ = true;
      std::cerr << "[native-probe][checkpoint] event has no pre-decode access-unit PTS parent\n";
      if (self->loop_ != nullptr) {
        g_main_loop_quit(self->loop_);
      }
      return GST_PAD_PROBE_DROP;
    }
    trace = trace_it->second;
    if (ctx->kind == "checkpoint-decode") {
      if (state.has_last_checkpoint_pts && pts <= state.last_checkpoint_pts) {
        self->failed_ = true;
        std::cerr << "[native-probe][checkpoint] decoded-buffer PTS is not strictly increasing within source cycle\n";
        if (self->loop_ != nullptr) {
          g_main_loop_quit(self->loop_);
        }
        return GST_PAD_PROBE_DROP;
      }
      state.last_checkpoint_pts = pts;
      state.has_last_checkpoint_pts = true;
      const std::string branch = self->args_.role == "checkpoint_shared" ? "shared" : self->args_.checkpoint_branch;
      const std::string decode_stage = self->args_.role == "checkpoint_shared"
                                           ? "decode"
                                           : "decode_" + self->args_.checkpoint_branch;
      try {
        self->write_checkpoint_decode_contract(ctx->pipeline, pad, decode_stage);
      } catch (const std::exception& exc) {
        self->failed_ = true;
        std::cerr << "[native-probe][checkpoint] " << exc.what() << "\n";
        if (self->loop_ != nullptr) {
          g_main_loop_quit(self->loop_);
        }
        return GST_PAD_PROBE_DROP;
      }
      const std::string source_id = self->checkpoint_execution_id(trace, branch, "source");
      self->emit_checkpoint_event(
          trace,
          pts,
          "stage_complete",
          decode_stage,
          branch,
          "decode",
          {source_id},
          end);
      self->write_event(trace, decode_stage, end, end);
      return GST_PAD_PROBE_OK;
    }
    if (ctx->kind == "checkpoint-preprocess") {
      const std::string branch = self->args_.role == "checkpoint_shared" ? "shared" : self->args_.checkpoint_branch;
      const std::string stage = self->args_.role == "checkpoint_shared"
                                    ? "preprocess"
                                    : "preprocess_" + self->args_.checkpoint_branch;
      try {
        self->write_checkpoint_preprocess_contract(pad, stage);
      } catch (const std::exception& exc) {
        self->failed_ = true;
        std::cerr << "[native-probe][checkpoint] " << exc.what() << "\n";
        if (self->loop_ != nullptr) {
          g_main_loop_quit(self->loop_);
        }
        return GST_PAD_PROBE_DROP;
      }
      const std::string decode_id = self->checkpoint_execution_id(trace, branch, "decode");
      self->emit_checkpoint_event(
          trace,
          pts,
          "stage_complete",
          stage,
          branch,
          "preprocess",
          {decode_id},
          end);
      self->write_event(trace, stage, end, end);
      return GST_PAD_PROBE_OK;
    }
    if (ctx->kind == "checkpoint-fanout-start") {
      const std::uint64_t bytes = gst_buffer_get_size(buffer);
      if (bytes == 0) {
        self->failed_ = true;
        std::cerr << "[native-probe][checkpoint] fanout queue received an empty buffer\n";
        if (self->loop_ != nullptr) {
          g_main_loop_quit(self->loop_);
        }
        return GST_PAD_PROBE_DROP;
      }
      auto& starts = state.checkpoint_fanout_starts_by_branch[ctx->branch];
      if (!starts.emplace(
              pts,
              FanoutIntervalStart{event_timestamp_ns, bytes, trace.frame_id})
               .second) {
        self->failed_ = true;
        std::cerr << "[native-probe][checkpoint] duplicate fanout queue sink interval start\n";
        if (self->loop_ != nullptr) {
          g_main_loop_quit(self->loop_);
        }
        return GST_PAD_PROBE_DROP;
      }
      return GST_PAD_PROBE_OK;
    }
    if (ctx->kind == "checkpoint-fanout") {
      auto branch_starts_it = state.checkpoint_fanout_starts_by_branch.find(ctx->branch);
      if (branch_starts_it == state.checkpoint_fanout_starts_by_branch.end()) {
        self->failed_ = true;
        std::cerr << "[native-probe][checkpoint] fanout queue src has no paired sink start\n";
        if (self->loop_ != nullptr) {
          g_main_loop_quit(self->loop_);
        }
        return GST_PAD_PROBE_DROP;
      }
      auto start_it = branch_starts_it->second.find(pts);
      if (start_it == branch_starts_it->second.end()) {
        self->failed_ = true;
        std::cerr << "[native-probe][checkpoint] fanout queue src has no matching PTS start\n";
        if (self->loop_ != nullptr) {
          g_main_loop_quit(self->loop_);
        }
        return GST_PAD_PROBE_DROP;
      }
      const FanoutIntervalStart interval_start = start_it->second;
      branch_starts_it->second.erase(start_it);
      if (interval_start.frame_id != trace.frame_id ||
          interval_start.bytes != gst_buffer_get_size(buffer) ||
          interval_start.host_start_timestamp_ns >= event_timestamp_ns ||
          !self->checkpoint_resource_interval_emitter_) {
        self->failed_ = true;
        std::cerr << "[native-probe][checkpoint] fanout queue interval linkage is invalid\n";
        if (self->loop_ != nullptr) {
          g_main_loop_quit(self->loop_);
        }
        return GST_PAD_PROBE_DROP;
      }
      const std::string preprocess_id = self->checkpoint_execution_id(trace, "shared", "preprocess");
      const std::string execution_id = self->checkpoint_execution_id(trace, ctx->branch, "fanout");
      self->emit_checkpoint_event(
          trace,
          pts,
          "fanout",
          "fanout",
          ctx->branch,
          "fanout",
          {preprocess_id},
          end);
      try {
        const std::string native_event_id = sha256_text(
            "fanout_interval_v1\n" + self->args_.run_id + "\n" + self->trace_id(trace) +
            "\n" + std::to_string(ctx->stream_id) + "\n" +
            std::to_string(trace.frame_id) + "\n" + ctx->branch + "\n" + execution_id +
            "\n" + std::to_string(interval_start.host_start_timestamp_ns) + "\n" +
            std::to_string(event_timestamp_ns) + "\n" +
            std::to_string(interval_start.bytes));
        self->checkpoint_resource_interval_emitter_->emit_fanout(
            self->args_.run_id,
            self->trace_id(trace),
            static_cast<std::uint64_t>(ctx->stream_id),
            trace.frame_id,
            self->checkpoint_input_frame_key(trace),
            ctx->branch,
            execution_id,
            interval_start.host_start_timestamp_ns,
            event_timestamp_ns,
            interval_start.bytes,
            native_event_id);
      } catch (const std::exception& exc) {
        self->failed_ = true;
        std::cerr << "[native-probe][checkpoint] " << exc.what() << "\n";
        if (self->loop_ != nullptr) {
          g_main_loop_quit(self->loop_);
        }
        return GST_PAD_PROBE_DROP;
      }
      return GST_PAD_PROBE_OK;
    }
    if (ctx->kind == "checkpoint-branch") {
      const std::string parent_id = self->args_.role == "checkpoint_shared"
                                        ? self->checkpoint_execution_id(trace, ctx->branch, "fanout")
                                        : self->checkpoint_execution_id(trace, ctx->branch, "preprocess");
      const std::string analytics_id = self->checkpoint_execution_id(trace, ctx->branch, "analytics");
      self->emit_checkpoint_event(
          trace,
          pts,
          "stage_complete",
          ctx->branch,
          ctx->branch,
          "analytics",
          {parent_id},
          end);
      self->write_event(trace, ctx->branch, end, end);
      self->emit_checkpoint_event(
          trace,
          pts,
          "branch_complete",
          ctx->branch,
          ctx->branch,
          "complete",
          {analytics_id},
          end);
      if (self->args_.role == "checkpoint_shared") {
        auto& completed = state.checkpoint_completed_branches_by_pts[pts];
        completed.insert(ctx->branch);
        if (completed.size() != self->checkpoint_branches_.size()) {
          return GST_PAD_PROBE_OK;
        }
        state.checkpoint_completed_branches_by_pts.erase(pts);
      }
      state.local_traces_by_pts.erase(trace_it);
      state.traces.erase(
          std::remove_if(
              state.traces.begin(),
              state.traces.end(),
              [&](const Trace& pending) { return pending.frame_id == trace.frame_id; }),
          state.traces.end());
      if (self->checkpoint_admission_stopped_.load() && self->checkpoint_state_drained()) {
        self->finish_checkpoint_drain(false);
      }
      return GST_PAD_PROBE_OK;
    }
    self->failed_ = true;
    std::cerr << "[native-probe][checkpoint] unsupported checkpoint probe kind\n";
    if (self->loop_ != nullptr) {
      g_main_loop_quit(self->loop_);
    }
    return GST_PAD_PROBE_DROP;
  }

  static gboolean bus_callback(GstBus*, GstMessage* message, gpointer data) {
    auto* self = static_cast<NativeProbeRuntime*>(data);
    if (GST_MESSAGE_TYPE(message) == GST_MESSAGE_ERROR) {
      GError* err = nullptr;
      gchar* debug = nullptr;
      gst_message_parse_error(message, &err, &debug);
      std::cerr << "[native-probe][error] " << (err ? err->message : "unknown") << "\n";
      if (debug != nullptr) {
        std::cerr << "[native-probe][debug] " << debug << "\n";
      }
      if (err != nullptr) {
        g_error_free(err);
      }
      g_free(debug);
      self->failed_ = true;
      if (self->loop_ != nullptr) {
        g_main_loop_quit(self->loop_);
      }
    } else if (
        GST_MESSAGE_TYPE(message) == GST_MESSAGE_EOS &&
        (self->args_.role == "checkpoint_branch" || self->args_.role == "checkpoint_shared")) {
      bool drained = false;
      {
        std::lock_guard<std::mutex> lock(self->mutex_);
        drained = self->checkpoint_state_drained();
      }
      if (!drained) {
        self->failed_ = true;
        std::cerr << "[native-probe][checkpoint] appsrc EOS reached before every admitted AU drained\n";
        if (self->loop_ != nullptr) {
          g_main_loop_quit(self->loop_);
        }
        return TRUE;
      }
      if (self->checkpoint_admission_stopped_.load()) {
        self->finish_checkpoint_drain(false);
        return TRUE;
      }
      std::cerr << "[native-probe][checkpoint] admission data pipe drained; awaiting coordinated STOP\n";
    }
    return TRUE;
  }

  static void set_string_property(
      GstElement* pipeline,
      const std::string& element_name,
      const std::string& property_name,
      const std::string& value) {
    GstElement* element = gst_bin_get_by_name(GST_BIN(pipeline), element_name.c_str());
    if (element == nullptr) {
      throw std::runtime_error("missing property target element: " + element_name);
    }
    g_object_set(G_OBJECT(element), property_name.c_str(), value.c_str(), nullptr);
    gst_object_unref(element);
  }

  void add_probe(
      GstElement* pipeline,
      const std::string& element_name,
      const std::string& kind,
      int stream_id,
      const std::string& stage = "",
      bool final_stage = false,
      const std::string& branch = "",
      const std::string& pad_name = "src") {
    GstElement* element = gst_bin_get_by_name(GST_BIN(pipeline), element_name.c_str());
    if (element == nullptr) {
      throw std::runtime_error("missing probe element: " + element_name);
    }
    GstPad* pad = gst_element_get_static_pad(element, pad_name.c_str());
    if (pad == nullptr) {
      gst_object_unref(element);
      throw std::runtime_error("missing " + pad_name + " pad on probe element: " + element_name);
    }
    auto* ctx = new ProbeContext{this, pipeline, stream_id, kind, stage, final_stage, branch};
    if (kind == "edge-pay") {
      gst_pad_add_probe(
          pad,
          static_cast<GstPadProbeType>(GST_PAD_PROBE_TYPE_BUFFER | GST_PAD_PROBE_TYPE_BUFFER_LIST),
          &NativeProbeRuntime::edge_pay_probe,
          ctx,
          nullptr);
    } else if (kind == "worker-pay") {
      gst_pad_add_probe(
          pad,
          static_cast<GstPadProbeType>(GST_PAD_PROBE_TYPE_BUFFER | GST_PAD_PROBE_TYPE_BUFFER_LIST),
          &NativeProbeRuntime::worker_pay_probe,
          ctx,
          nullptr);
    } else if (kind.rfind("local-", 0) == 0) {
      gst_pad_add_probe(pad, GST_PAD_PROBE_TYPE_BUFFER, &NativeProbeRuntime::local_stage_probe, ctx, nullptr);
    } else if (kind.rfind("checkpoint-", 0) == 0) {
      gst_pad_add_probe(pad, GST_PAD_PROBE_TYPE_BUFFER, &NativeProbeRuntime::checkpoint_stage_probe, ctx, nullptr);
    } else {
      gst_pad_add_probe(
          pad,
          static_cast<GstPadProbeType>(GST_PAD_PROBE_TYPE_BUFFER | GST_PAD_PROBE_TYPE_BUFFER_LIST),
          &NativeProbeRuntime::input_rtp_probe,
          ctx,
          nullptr);
    }
    gst_object_unref(pad);
    gst_object_unref(element);
  }

  void add_local_stage_probes(GstElement* pipeline, int stream_id) {
    const std::size_t first_decode = first_stage_index_with_base("decode");
    for (std::size_t index = 0; index < stage_names_.size(); ++index) {
      const std::string& stage = stage_names_[index];
      const std::string base = stage_base_name(stage);
      const bool final_stage = index + 1 == stage_names_.size();
      const std::string kind = base == "decode" && index == first_decode ? "local-decode"
                               : (base == "detect" ? "local-detect" : "local-stage");
      add_probe(pipeline, stage_probe_name(stage, stream_id), kind, stream_id, stage, final_stage);
    }
  }

  std::string detect_bin() const {
    if (args_.detect_bin.empty()) {
      return "identity";
    }
    return args_.detect_bin;
  }

  static void replace_all(
      std::string& value,
      const std::string& placeholder,
      const std::string& replacement) {
    std::size_t offset = 0;
    while ((offset = value.find(placeholder, offset)) != std::string::npos) {
      value.replace(offset, placeholder.size(), replacement);
      offset += replacement.size();
    }
  }

  static std::string checkpoint_analytics_binding(
      const std::string& branch,
      const std::string& field,
      bool allow_empty = false) {
    const std::string name = "VAST_CHECKPOINT_ANALYTICS_" + field + "_" + branch;
    const char* raw = std::getenv(name.c_str());
    if (raw == nullptr || (!allow_empty && std::string(raw).empty())) {
      throw std::runtime_error("missing checkpoint analytics model binding: " + name);
    }
    return raw;
  }

  std::string checkpoint_detect_bin(const std::string& branch) const {
    std::string value = detect_bin();
    replace_all(value, "{branch}", branch);
    if (value.find("vastanalyticsterminal") != std::string::npos) {
      replace_all(value, "{factory}", checkpoint_analytics_binding(branch, "FACTORY"));
      replace_all(value, "{model_path}", checkpoint_analytics_binding(branch, "MODEL_PATH"));
      replace_all(value, "{model_sha256}", checkpoint_analytics_binding(branch, "MODEL_SHA256"));
      replace_all(
          value,
          "{weights_sha256}",
          checkpoint_analytics_binding(branch, "WEIGHTS_SHA256", true));
      replace_all(value, "{detector_id}", checkpoint_analytics_binding(branch, "DETECTOR_ID"));
      replace_all(value, "{max_buffers}", checkpoint_analytics_binding(branch, "MAX_BUFFERS"));
    }
    return value;
  }

  bool uses_deepstream_elements() const {
    return args_.system == "deepstream" || args_.system == "savant";
  }

  std::string generic_stage_operation(const std::string& stage, int stream_id, bool source_decode) const {
    const std::string base = stage_base_name(stage);
    if (base == "decode") {
      if (source_decode) {
        return "";
      }
      return "videoconvert ! jpegenc ! jpegdec ! videoconvert";
    }
    if (base == "preprocess") {
      return "videoconvert ! videoscale ! video/x-raw,format=RGB,width=640,height=360";
    }
    if (base == "detect") {
      return detect_bin();
    }
    if (base == "track" || base == "classify") {
      return "videoconvert ! video/x-raw,format=I420 ! videoconvert ! video/x-raw,format=RGB ! identity name=" +
             stage + "_op" + std::to_string(stream_id) + " silent=false";
    }
    if (base == "record") {
      return "videoconvert ! jpegenc ! jpegdec ! videoconvert";
    }
    return "identity name=" + stage + "_op" + std::to_string(stream_id) + " silent=false";
  }

  std::string deepstream_stage_operation(const std::string& stage, int stream_id, bool source_decode) const {
    const std::string base = stage_base_name(stage);
    if (base == "decode") {
      if (source_decode) {
        return "";
      }
      return "nvvideoconvert ! video/x-raw,format=I420 ! jpegenc ! jpegdec ! nvvideoconvert ! video/x-raw(memory:NVMM),format=NV12";
    }
    if (base == "preprocess") {
      return "nvvideoconvert ! video/x-raw(memory:NVMM),format=NV12,width=640,height=360";
    }
    if (base == "detect") {
      return detect_bin();
    }
    if (base == "track" || base == "classify") {
      return "identity name=" + stage + "_op" + std::to_string(stream_id) + " sleep-time=1000 silent=false";
    }
    if (base == "record") {
      return "nvvideoconvert ! video/x-raw,format=I420 ! jpegenc ! jpegdec ! nvvideoconvert ! video/x-raw(memory:NVMM),format=NV12";
    }
    return "identity name=" + stage + "_op" + std::to_string(stream_id) + " silent=false";
  }

  std::string edge_pipeline(int stream_id) const {
    if (uses_deepstream_elements()) {
      return deepstream_edge_pipeline(stream_id);
    }
    const std::size_t first_decode = first_stage_index_with_base("decode");
    std::ostringstream p;
    p << "filesrc name=file_src" << stream_id
      << " ! decodebin ! videoconvert ! videorate ! video/x-raw,framerate=30/1";
    for (std::size_t index = 0; index < stage_names_.size(); ++index) {
      const std::string op = generic_stage_operation(stage_names_[index], stream_id, index == first_decode);
      if (!op.empty()) {
        p << " ! " << op;
      }
    }
    p << " ! identity sync=true ! jpegenc ! rtpjpegpay pt=26 name=pay" << stream_id
      << " ! udpsink name=out_sink" << stream_id << " port=" << (args_.output_port_base + stream_id * args_.port_stride)
      << " sync=false async=false";
    return p.str();
  }

  std::string deepstream_edge_pipeline(int stream_id) const {
    const std::size_t first_decode = first_stage_index_with_base("decode");
    std::ostringstream p;
    p << "nvurisrcbin name=uri_src" << stream_id << " file-loop=true"
      << " ! queue ! nvvideoconvert ! video/x-raw,format=I420";
    for (std::size_t index = 0; index < stage_names_.size(); ++index) {
      const std::string op = deepstream_stage_operation(stage_names_[index], stream_id, index == first_decode);
      if (!op.empty()) {
        p << " ! " << op;
      }
    }
    p << " ! identity sync=true ! jpegenc ! rtpjpegpay pt=26 name=pay" << stream_id
      << " ! udpsink name=out_sink" << stream_id << " port=" << (args_.output_port_base + stream_id * args_.port_stride)
      << " sync=false async=false";
    return p.str();
  }

  std::string worker_pipeline(int stream_id) const {
    if (uses_deepstream_elements()) {
      return deepstream_worker_pipeline(stream_id);
    }
    std::ostringstream p;
    p << "udpsrc name=src" << stream_id << " port=" << (args_.input_port_base + stream_id * args_.port_stride)
      << " caps=\"application/x-rtp,media=(string)video,encoding-name=(string)JPEG,payload=(int)26\""
      << " ! rtpjpegdepay ! jpegdec ! videoconvert";
    for (const std::string& stage : stage_names_) {
      const std::string op = generic_stage_operation(stage, stream_id, false);
      if (!op.empty()) {
        p << " ! " << op;
      }
    }
    p << " ! videoconvert ! jpegenc ! rtpjpegpay pt=26 name=pay" << stream_id
      << " ! udpsink name=out_sink" << stream_id << " port=" << (args_.output_port_base + stream_id * args_.port_stride)
      << " sync=false async=false";
    return p.str();
  }

  std::string aggregator_pipeline(int stream_id) const {
    std::ostringstream p;
    p << "udpsrc name=src" << stream_id << " port=" << (args_.input_port_base + stream_id * args_.port_stride)
      << " caps=\"application/x-rtp,media=(string)video,encoding-name=(string)JPEG,payload=(int)26\""
      << " ! rtpjpegdepay ! jpegdec ! videoconvert ! fakesink sync=false async=false";
    return p.str();
  }

  std::string local_pipeline(int stream_id) const {
    if (uses_deepstream_elements()) {
      return deepstream_local_pipeline(stream_id);
    }
    const std::size_t first_decode = first_stage_index_with_base("decode");
    std::ostringstream p;
    p << "filesrc name=file_src" << stream_id
      << " ! decodebin ! videoconvert ! videorate ! video/x-raw,framerate=30/1";
    for (std::size_t index = 0; index < stage_names_.size(); ++index) {
      const std::string& stage = stage_names_[index];
      const std::string op = generic_stage_operation(stage, stream_id, index == first_decode);
      if (!op.empty()) {
        p << " ! " << op;
      }
      p << " ! queue name=" << stage_probe_name(stage, stream_id);
    }
    p << " ! fakesink sync=false async=false";
    return p.str();
  }

  std::string checkpoint_source_pipeline(int stream_id) const {
    const std::string parser = args_.checkpoint_codec == "h264" ? "h264parse" : "h265parse";
    const std::string media_type = args_.checkpoint_codec == "h264" ? "video/x-h264" : "video/x-h265";
    std::ostringstream p;
    p << "appsrc name=checkpoint_appsrc" << stream_id
      << " is-live=true format=time do-timestamp=false block=true"
      << " caps=\"" << media_type << ",stream-format=byte-stream,alignment=au\""
      << " ! " << parser
      << " ! " << media_type << ",stream-format=byte-stream,alignment=au"
      << " ! identity name=checkpoint_ingress" << stream_id;
    return p.str();
  }

  std::string checkpoint_branch_pipeline(int stream_id) const {
    const std::string branch = args_.checkpoint_branch;
    std::ostringstream p;
    p << checkpoint_source_pipeline(stream_id)
      << " ! decodebin ! videoconvert ! video/x-raw,format=RGB"
      << " ! queue name=checkpoint_decode" << stream_id
      << " ! videoconvert ! videoscale ! video/x-raw,format=RGB,width=640,height=360"
      << " ! queue name=checkpoint_preprocess" << stream_id
      << " ! " << checkpoint_detect_bin(branch)
      << " ! queue name=checkpoint_branch_" << branch << "_" << stream_id
      << " ! fakesink sync=false async=false";
    return p.str();
  }

  std::string checkpoint_shared_pipeline(int stream_id) const {
    std::ostringstream p;
    p << checkpoint_source_pipeline(stream_id)
      << " ! decodebin ! videoconvert ! video/x-raw,format=RGB"
      << " ! queue name=checkpoint_decode" << stream_id
      << " ! videoconvert ! videoscale ! video/x-raw,format=RGB,width=640,height=360"
      << " ! queue name=checkpoint_preprocess" << stream_id
      << " ! tee name=checkpoint_tee" << stream_id;
    for (const std::string& branch : checkpoint_branches_) {
      p << " checkpoint_tee" << stream_id << "."
        << " ! queue name=checkpoint_fanout_" << branch << "_" << stream_id
        << " ! " << checkpoint_detect_bin(branch)
        << " ! queue name=checkpoint_branch_" << branch << "_" << stream_id
        << " ! fakesink sync=false async=false";
    }
    return p.str();
  }

  std::string deepstream_local_pipeline(int stream_id) const {
    const std::size_t first_decode = first_stage_index_with_base("decode");
    const std::string source_decode_stage = first_stage_with_base("decode");
    std::ostringstream p;
    p << "nvstreammux name=mux" << stream_id
      << " batch-size=1 width=1920 height=1080 live-source=0 batched-push-timeout=40000";
    for (std::size_t index = 0; index < stage_names_.size(); ++index) {
      const std::string& stage = stage_names_[index];
      if (index == first_decode && stage_base_name(stage) == "decode") {
        continue;
      }
      const std::string op = deepstream_stage_operation(stage, stream_id, false);
      if (!op.empty()) {
        p << " ! " << op;
      }
      p << " ! queue name=" << stage_probe_name(stage, stream_id);
    }
    p << " ! nvvideoconvert ! video/x-raw ! fakesink sync=false async=false "
      << "uridecodebin name=uri_src" << stream_id
      << " ! queue name=" << stage_probe_name(source_decode_stage, stream_id)
      << " ! nvvideoconvert ! video/x-raw(memory:NVMM),format=NV12"
      << " ! mux" << stream_id << ".sink_0";
    return p.str();
  }

  std::string deepstream_worker_pipeline(int stream_id) const {
    std::ostringstream p;
    p << "nvstreammux name=mux" << stream_id
      << " batch-size=1 width=1920 height=1080 live-source=1 batched-push-timeout=40000";
    for (const std::string& stage : stage_names_) {
      const std::string op = deepstream_stage_operation(stage, stream_id, false);
      if (!op.empty()) {
        p << " ! " << op;
      }
    }
    p << " ! nvvideoconvert ! video/x-raw"
      << " ! jpegenc ! rtpjpegpay pt=26 name=pay" << stream_id
      << " ! udpsink name=out_sink" << stream_id << " port=" << (args_.output_port_base + stream_id * args_.port_stride)
      << " sync=false async=false "
      << "udpsrc name=src" << stream_id << " port=" << (args_.input_port_base + stream_id * args_.port_stride)
      << " caps=\"application/x-rtp,media=(string)video,encoding-name=(string)JPEG,payload=(int)26\""
      << " ! rtpjpegdepay ! jpegdec ! nvvideoconvert ! video/x-raw(memory:NVMM),format=NV12"
      << " ! mux" << stream_id << ".sink_0";
    return p.str();
  }

  void build_pipelines() {
    for (int stream_id = 0; stream_id < streams_; ++stream_id) {
      std::string pipeline_text;
      if (args_.role == "edge") {
        pipeline_text = edge_pipeline(stream_id);
      } else if (args_.role == "gpu_worker") {
        pipeline_text = worker_pipeline(stream_id);
      } else if (args_.role == "aggregator") {
        pipeline_text = aggregator_pipeline(stream_id);
      } else if (args_.role == "local") {
        pipeline_text = local_pipeline(stream_id);
      } else if (args_.role == "checkpoint_branch") {
        pipeline_text = checkpoint_branch_pipeline(stream_id);
      } else if (args_.role == "checkpoint_shared") {
        pipeline_text = checkpoint_shared_pipeline(stream_id);
      } else {
        throw std::runtime_error("unsupported role: " + args_.role);
      }

      GError* error = nullptr;
      GstElement* pipeline = gst_parse_launch(pipeline_text.c_str(), &error);
      if (pipeline == nullptr) {
        std::string message = error != nullptr ? error->message : "unknown parse error";
        if (error != nullptr) {
          g_error_free(error);
        }
        throw std::runtime_error("failed to build pipeline: " + message + " pipeline=" + pipeline_text);
      }
      GstBus* bus = gst_element_get_bus(pipeline);
      gst_bus_add_watch(bus, &NativeProbeRuntime::bus_callback, this);
      gst_object_unref(bus);
      if (args_.role == "edge") {
        if (uses_deepstream_elements()) {
          set_string_property(pipeline, "uri_src" + std::to_string(stream_id), "uri", uri_for_stream(stream_id));
        } else {
          set_string_property(pipeline, "file_src" + std::to_string(stream_id), "location", source_for_stream(stream_id));
        }
        set_string_property(pipeline, "out_sink" + std::to_string(stream_id), "host", args_.output_host);
        add_probe(pipeline, "pay" + std::to_string(stream_id), "edge-pay", stream_id);
      } else if (args_.role == "gpu_worker") {
        set_string_property(pipeline, "out_sink" + std::to_string(stream_id), "host", args_.output_host);
        add_probe(pipeline, "src" + std::to_string(stream_id), "input", stream_id);
        add_probe(pipeline, "pay" + std::to_string(stream_id), "worker-pay", stream_id);
      } else if (args_.role == "aggregator") {
        add_probe(pipeline, "src" + std::to_string(stream_id), "input", stream_id);
      } else if (args_.role == "local") {
        if (uses_deepstream_elements()) {
          set_string_property(pipeline, "uri_src" + std::to_string(stream_id), "uri", uri_for_stream(stream_id));
        } else {
          set_string_property(pipeline, "file_src" + std::to_string(stream_id), "location", source_for_stream(stream_id));
        }
        add_local_stage_probes(pipeline, stream_id);
      } else if (args_.role == "checkpoint_branch" || args_.role == "checkpoint_shared") {
        add_probe(pipeline, "checkpoint_ingress" + std::to_string(stream_id), "checkpoint-ingress", stream_id);
        add_probe(pipeline, "checkpoint_decode" + std::to_string(stream_id), "checkpoint-decode", stream_id);
        add_probe(
            pipeline,
            "checkpoint_preprocess" + std::to_string(stream_id),
            "checkpoint-preprocess",
            stream_id);
        if (args_.role == "checkpoint_branch") {
          add_probe(
              pipeline,
              "checkpoint_branch_" + args_.checkpoint_branch + "_" + std::to_string(stream_id),
              "checkpoint-branch",
              stream_id,
              args_.checkpoint_branch,
              true,
              args_.checkpoint_branch);
        } else {
          for (const std::string& branch : checkpoint_branches_) {
            add_probe(
                pipeline,
                "checkpoint_fanout_" + branch + "_" + std::to_string(stream_id),
                "checkpoint-fanout-start",
                stream_id,
                "fanout",
                false,
                branch,
                "sink");
            add_probe(
                pipeline,
                "checkpoint_fanout_" + branch + "_" + std::to_string(stream_id),
                "checkpoint-fanout",
                stream_id,
                "fanout",
                false,
                branch);
            add_probe(
                pipeline,
                "checkpoint_branch_" + branch + "_" + std::to_string(stream_id),
                "checkpoint-branch",
                stream_id,
                branch,
                true,
                branch);
          }
        }
      }
      pipelines_.push_back(pipeline);
      std::cerr << "[native-probe] role=" << args_.role << " stream=" << stream_id << " pipeline=" << pipeline_text << "\n";
    }
  }
};

static std::string env_or(const char* name, const std::string& fallback = "") {
  const char* value = std::getenv(name);
  return value == nullptr || std::string(value).empty() ? fallback : std::string(value);
}

static std::string resolve_executable_path(const char* argv0) {
  std::array<char, 4096> proc_path{};
  const ssize_t proc_length = ::readlink(
      "/proc/self/exe",
      proc_path.data(),
      proc_path.size() - 1);
  if (proc_length > 0) {
    proc_path[static_cast<std::size_t>(proc_length)] = '\0';
    return std::string(proc_path.data());
  }
  std::error_code error;
  const fs::path canonical = fs::canonical(fs::path(argv0), error);
  if (error || !fs::is_regular_file(canonical)) {
    throw std::runtime_error("failed to resolve the loaded native-probe executable path");
  }
  return canonical.string();
}

static Args parse_args(int argc, char** argv) {
  Args args;
  args.system = env_or("VAST_PROBE_SYSTEM", "gstreamer_custom");
  args.role = env_or("EXPERIMENT_HOST_ROLE", "local");
  args.stages = env_or("EXPERIMENT_PIPELINE_STAGES", "");
  args.run_id = env_or("EXPERIMENT_RUN_ID", "native-probe");
  args.detector = env_or("ADAPTER_DETECTOR", args.system);
  args.backend = env_or("ADAPTER_BACKEND", args.system);
  args.video_layout_dir = env_or("VIDEO_LAYOUT_DIR", args.video_layout_dir);
  args.dataset_streams_json = env_or("DATASET_STREAMS_JSON", "");
  args.checkpoint_branches = env_or("VAST_CHECKPOINT_BRANCHES", "");
  args.checkpoint_branch = env_or("VAST_CHECKPOINT_BRANCH_ID", "");
  args.dataset_id = env_or("VAST_CHECKPOINT_DATASET_ID", "");
  args.source_sha256 = env_or("VAST_CHECKPOINT_SOURCE_SHA256", "");
  args.checkpoint_container = env_or("VAST_CHECKPOINT_SOURCE_CONTAINER", "");
  args.checkpoint_codec = env_or("VAST_CHECKPOINT_SOURCE_CODEC", "");
  args.checkpoint_allowed_decoder_factories = env_or(
      "VAST_CHECKPOINT_ALLOWED_DECODER_FACTORIES",
      "");
  args.source_replay = env_or("VAST_CHECKPOINT_SOURCE_REPLAY", "");
  args.checkpoint_analytics_mode = env_or(
      "VAST_CHECKPOINT_ANALYTICS_MODE",
      args.checkpoint_analytics_mode);
  if (!env_or("VAST_CHECKPOINT_SOURCE_DURATION_NS").empty()) {
    args.source_duration_ns = std::stoull(env_or("VAST_CHECKPOINT_SOURCE_DURATION_NS"));
  }
  if (!env_or("VAST_CHECKPOINT_STREAM_ID").empty()) {
    args.logical_stream_id = std::stoi(env_or("VAST_CHECKPOINT_STREAM_ID"));
  }
  args.policy = env_or("SCHEDULER_POLICY", args.policy);
  if (!env_or("DEADLINE_MS").empty()) {
    args.deadline_ms = std::stod(env_or("DEADLINE_MS"));
  }
  args.output_host = env_or("EXPERIMENT_RTP_OUTPUT_HOST", "127.0.0.1");
  args.output_dir = ".";
  if (!env_or("EXPERIMENT_RTP_INPUT_PORT").empty()) {
    args.input_port_base = std::stoi(env_or("EXPERIMENT_RTP_INPUT_PORT"));
  }
  if (!env_or("EXPERIMENT_RTP_OUTPUT_PORT").empty()) {
    args.output_port_base = std::stoi(env_or("EXPERIMENT_RTP_OUTPUT_PORT"));
  }
  if (!env_or("EXPERIMENT_RTP_PORT_STRIDE").empty()) {
    args.port_stride = std::max(1, std::stoi(env_or("EXPERIMENT_RTP_PORT_STRIDE")));
  }

  for (int i = 1; i < argc; ++i) {
    const std::string key = argv[i];
    auto value = [&](const char* flag) -> std::string {
      if (i + 1 >= argc) {
        throw std::runtime_error(std::string("missing value for ") + flag);
      }
      return argv[++i];
    };
    if (key == "--system") args.system = value("--system");
    else if (key == "--role") args.role = value("--role");
    else if (key == "--stages") args.stages = value("--stages");
    else if (key == "--run-id") args.run_id = value("--run-id");
    else if (key == "--detector") args.detector = value("--detector");
    else if (key == "--backend") args.backend = value("--backend");
    else if (key == "--output-dir") args.output_dir = value("--output-dir");
    else if (key == "--duration") args.duration_s = std::stoi(value("--duration"));
    else if (key == "--streams") args.streams = std::stoi(value("--streams"));
    else if (key == "--input-port-base") args.input_port_base = std::stoi(value("--input-port-base"));
    else if (key == "--output-host") args.output_host = value("--output-host");
    else if (key == "--output-port-base") args.output_port_base = std::stoi(value("--output-port-base"));
    else if (key == "--port-stride") args.port_stride = std::max(1, std::stoi(value("--port-stride")));
    else if (key == "--video-layout-dir") args.video_layout_dir = value("--video-layout-dir");
    else if (key == "--dataset-streams-json") args.dataset_streams_json = value("--dataset-streams-json");
    else if (key == "--checkpoint-branches") args.checkpoint_branches = value("--checkpoint-branches");
    else if (key == "--checkpoint-branch") args.checkpoint_branch = value("--checkpoint-branch");
    else if (key == "--dataset-id") args.dataset_id = value("--dataset-id");
    else if (key == "--source-sha256") args.source_sha256 = value("--source-sha256");
    else if (key == "--checkpoint-container") args.checkpoint_container = value("--checkpoint-container");
    else if (key == "--checkpoint-codec") args.checkpoint_codec = value("--checkpoint-codec");
    else if (key == "--checkpoint-allowed-decoder-factories") {
      args.checkpoint_allowed_decoder_factories = value("--checkpoint-allowed-decoder-factories");
    }
    else if (key == "--source-duration-ns") args.source_duration_ns = std::stoull(value("--source-duration-ns"));
    else if (key == "--source-replay") args.source_replay = value("--source-replay");
    else if (key == "--checkpoint-analytics-mode") {
      args.checkpoint_analytics_mode = value("--checkpoint-analytics-mode");
    }
    else if (key == "--logical-stream-id") args.logical_stream_id = std::stoi(value("--logical-stream-id"));
    else if (key == "--detect-bin") args.detect_bin = value("--detect-bin");
    else if (key == "--min-objects") args.min_objects = std::stoi(value("--min-objects"));
    else if (key == "--max-objects") args.max_objects = std::stoi(value("--max-objects"));
    else if (key == "--deadline-ms") args.deadline_ms = std::stod(value("--deadline-ms"));
    else if (key == "--policy") args.policy = value("--policy");
    else throw std::runtime_error("unknown argument: " + key);
  }
  return args;
}

int main(int argc, char** argv) {
  try {
    const std::string executable_path = resolve_executable_path(argv[0]);
    gst_init(&argc, &argv);
    Args args = parse_args(argc, argv);
    args.executable_path = executable_path;
    NativeProbeRuntime runtime(std::move(args));
    return runtime.run();
  } catch (const std::exception& exc) {
    std::cerr << "[native-probe][fatal] " << exc.what() << "\n";
    return 2;
  }
}
