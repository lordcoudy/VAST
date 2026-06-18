#include <gst/gst.h>
#include <gst/rtp/rtp.h>

#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <deque>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace fs = std::filesystem;

constexpr guint8 kTraceExtensionId = 1;
constexpr std::uint16_t kTraceMagic = 0x5641;
constexpr std::uint8_t kTraceVersion = 1;
constexpr std::size_t kTracePayloadSize = 16;

struct Args {
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
  int input_port_base = 0;
  int output_port_base = 0;
  int port_stride = 1;
  int streams = 1;
  int duration_s = 1;
  int min_objects = 0;
  int max_objects = 20;
};

struct Trace {
  std::uint8_t stream_id = 0;
  std::uint32_t frame_id = 0;
  std::uint64_t ingress_ms = 0;
};

struct StreamState {
  std::uint32_t edge_frame_id = 0;
  std::uint32_t local_frame_id = 0;
  Trace current_output_trace{};
  bool has_output_trace = false;
  std::deque<Trace> traces;
  std::deque<Trace> aggregate_traces;
};

class NativeProbeRuntime {
 public:
  explicit NativeProbeRuntime(Args args) : args_(std::move(args)), streams_(std::max(1, args_.streams)) {
    states_.resize(static_cast<std::size_t>(streams_));
    sources_ = parse_json_string_array(args_.dataset_streams_json);
    open_outputs();
  }

  ~NativeProbeRuntime() {
    for (GstElement* pipeline : pipelines_) {
      if (pipeline != nullptr) {
        gst_element_set_state(pipeline, GST_STATE_NULL);
        gst_object_unref(pipeline);
      }
    }
  }

  int run() {
    build_pipelines();
    GMainLoop* loop = g_main_loop_new(nullptr, FALSE);
    loop_ = loop;
    guint timer = g_timeout_add_seconds(static_cast<guint>(std::max(1, args_.duration_s)), &NativeProbeRuntime::quit_loop, this);
    for (GstElement* pipeline : pipelines_) {
      gst_element_set_state(pipeline, GST_STATE_PLAYING);
    }
    g_main_loop_run(loop);
    if (timer != 0) {
      g_source_remove(timer);
    }
    g_main_loop_unref(loop);
    loop_ = nullptr;
    events_.flush();
    frames_.flush();
    return failed_ ? 1 : 0;
  }

 private:
  Args args_;
  int streams_ = 1;
  std::vector<StreamState> states_;
  std::vector<std::string> sources_;
  std::vector<GstElement*> pipelines_;
  GMainLoop* loop_ = nullptr;
  std::ofstream events_;
  std::ofstream frames_;
  std::mutex mutex_;
  bool failed_ = false;

  static std::uint64_t now_ms() {
    using namespace std::chrono;
    return static_cast<std::uint64_t>(duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count());
  }

  static gboolean quit_loop(gpointer data) {
    auto* self = static_cast<NativeProbeRuntime*>(data);
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
  }

  void write_event(const Trace& trace, const std::string& stage, std::uint64_t start_ms, std::uint64_t end_ms) {
    events_ << "2," << args_.run_id << "," << trace_id(trace) << "," << static_cast<int>(trace.stream_id) << ","
            << trace.frame_id << "," << stage << "," << args_.role << ",localhost,cpu," << start_ms << ","
            << start_ms << "," << end_ms << ",0," << std::max<std::uint64_t>(1, end_ms - start_ms)
            << ",native:" << args_.system << "\n";
  }

  void write_frame(const Trace& trace, std::uint64_t egress_ms) {
    const std::uint64_t ingress = trace.ingress_ms;
    const std::uint64_t latency = egress_ms >= ingress ? egress_ms - ingress : 0;
    frames_ << "2," << args_.run_id << "," << trace_id(trace) << "," << static_cast<int>(trace.stream_id) << ","
            << trace.frame_id << "," << ingress << "," << egress_ms << "," << latency << "," << object_count()
            << "," << args_.detector << "," << args_.backend << ",native\n";
  }

  struct ProbeContext {
    NativeProbeRuntime* runtime = nullptr;
    int stream_id = 0;
    std::string kind;
  };

  static GstPadProbeReturn edge_pay_probe(GstPad*, GstPadProbeInfo* info, gpointer data) {
    auto* ctx = static_cast<ProbeContext*>(data);
    auto* self = ctx->runtime;
    GstBuffer* buffer = GST_PAD_PROBE_INFO_BUFFER(info);
    if (buffer == nullptr) {
      return GST_PAD_PROBE_OK;
    }
    buffer = gst_buffer_make_writable(buffer);
    GST_PAD_PROBE_INFO_DATA(info) = buffer;
    GstRTPBuffer rtp = GST_RTP_BUFFER_INIT;
    if (!gst_rtp_buffer_map(buffer, GST_MAP_READWRITE, &rtp)) {
      return GST_PAD_PROBE_OK;
    }
    const bool marker = gst_rtp_buffer_get_marker(&rtp);
    Trace trace;
    {
      std::lock_guard<std::mutex> lock(self->mutex_);
      StreamState& state = self->states_[static_cast<std::size_t>(ctx->stream_id)];
      if (!state.has_output_trace) {
        state.current_output_trace.stream_id = static_cast<std::uint8_t>(ctx->stream_id);
        state.current_output_trace.frame_id = state.edge_frame_id;
        state.current_output_trace.ingress_ms = now_ms();
        state.has_output_trace = true;
      }
      trace = state.current_output_trace;
      const auto payload = pack_trace(trace);
      gst_rtp_buffer_add_extension_onebyte_header(&rtp, kTraceExtensionId, payload.data(), payload.size());
      if (marker) {
        const std::uint64_t end = now_ms();
        self->write_event(trace, "decode", trace.ingress_ms, end);
        ++state.edge_frame_id;
        state.has_output_trace = false;
      }
    }
    gst_rtp_buffer_unmap(&rtp);
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
    GstBuffer* buffer = GST_PAD_PROBE_INFO_BUFFER(info);
    if (buffer == nullptr) {
      return GST_PAD_PROBE_OK;
    }
    GstRTPBuffer rtp = GST_RTP_BUFFER_INIT;
    if (!gst_rtp_buffer_map(buffer, GST_MAP_READ, &rtp)) {
      return GST_PAD_PROBE_OK;
    }
    const bool marker = gst_rtp_buffer_get_marker(&rtp);
    gst_rtp_buffer_unmap(&rtp);
    if (!marker) {
      return GST_PAD_PROBE_OK;
    }
    Trace trace;
    if (!extract_trace(buffer, trace)) {
      return GST_PAD_PROBE_OK;
    }
    const std::uint64_t end = now_ms();
    std::lock_guard<std::mutex> lock(self->mutex_);
    if (self->args_.role == "gpu_worker") {
      self->states_[static_cast<std::size_t>(ctx->stream_id)].traces.push_back(trace);
    } else if (self->args_.role == "aggregator") {
      self->write_event(trace, "aggregate", end > 1 ? end - 1 : end, end);
      self->write_frame(trace, end);
    }
    return GST_PAD_PROBE_OK;
  }

  static GstPadProbeReturn worker_pay_probe(GstPad*, GstPadProbeInfo* info, gpointer data) {
    auto* ctx = static_cast<ProbeContext*>(data);
    auto* self = ctx->runtime;
    GstBuffer* buffer = GST_PAD_PROBE_INFO_BUFFER(info);
    if (buffer == nullptr) {
      return GST_PAD_PROBE_OK;
    }
    buffer = gst_buffer_make_writable(buffer);
    GST_PAD_PROBE_INFO_DATA(info) = buffer;
    GstRTPBuffer rtp = GST_RTP_BUFFER_INIT;
    if (!gst_rtp_buffer_map(buffer, GST_MAP_READWRITE, &rtp)) {
      return GST_PAD_PROBE_OK;
    }
    const bool marker = gst_rtp_buffer_get_marker(&rtp);
    Trace trace;
    bool have_trace = false;
    {
      std::lock_guard<std::mutex> lock(self->mutex_);
      StreamState& state = self->states_[static_cast<std::size_t>(ctx->stream_id)];
      if (!state.has_output_trace && !state.traces.empty()) {
        state.current_output_trace = state.traces.front();
        state.traces.pop_front();
        state.has_output_trace = true;
      }
      if (state.has_output_trace) {
        trace = state.current_output_trace;
        have_trace = true;
      }
      if (have_trace) {
        const auto payload = pack_trace(trace);
        gst_rtp_buffer_add_extension_onebyte_header(&rtp, kTraceExtensionId, payload.data(), payload.size());
      }
      if (marker && have_trace) {
        const std::uint64_t end = now_ms();
        self->write_event(trace, "detect", end > 1 ? end - 1 : end, end);
        state.has_output_trace = false;
      }
    }
    gst_rtp_buffer_unmap(&rtp);
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
    std::lock_guard<std::mutex> lock(self->mutex_);
    StreamState& state = self->states_[static_cast<std::size_t>(ctx->stream_id)];

    if (ctx->kind == "local-decode") {
      Trace trace;
      trace.stream_id = static_cast<std::uint8_t>(ctx->stream_id);
      trace.frame_id = state.local_frame_id++;
      trace.ingress_ms = end;
      self->write_event(trace, "decode", trace.ingress_ms, end);
      state.traces.push_back(trace);
      return GST_PAD_PROBE_OK;
    }

    if (ctx->kind == "local-detect") {
      if (state.traces.empty()) {
        return GST_PAD_PROBE_OK;
      }
      Trace trace = state.traces.front();
      state.traces.pop_front();
      self->write_event(trace, "detect", end > 1 ? end - 1 : end, end);
      state.aggregate_traces.push_back(trace);
      return GST_PAD_PROBE_OK;
    }

    if (ctx->kind == "local-aggregate") {
      if (state.aggregate_traces.empty()) {
        return GST_PAD_PROBE_OK;
      }
      Trace trace = state.aggregate_traces.front();
      state.aggregate_traces.pop_front();
      self->write_event(trace, "aggregate", end > 1 ? end - 1 : end, end);
      self->write_frame(trace, end);
      return GST_PAD_PROBE_OK;
    }

    return GST_PAD_PROBE_OK;
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

  void add_probe(GstElement* pipeline, const std::string& element_name, const std::string& kind, int stream_id) {
    GstElement* element = gst_bin_get_by_name(GST_BIN(pipeline), element_name.c_str());
    if (element == nullptr) {
      throw std::runtime_error("missing probe element: " + element_name);
    }
    GstPad* pad = gst_element_get_static_pad(element, kind == "input" ? "src" : "src");
    if (pad == nullptr) {
      gst_object_unref(element);
      throw std::runtime_error("missing src pad on probe element: " + element_name);
    }
    auto* ctx = new ProbeContext{this, stream_id, kind};
    if (kind == "edge-pay") {
      gst_pad_add_probe(pad, GST_PAD_PROBE_TYPE_BUFFER, &NativeProbeRuntime::edge_pay_probe, ctx, nullptr);
    } else if (kind == "worker-pay") {
      gst_pad_add_probe(pad, GST_PAD_PROBE_TYPE_BUFFER, &NativeProbeRuntime::worker_pay_probe, ctx, nullptr);
    } else if (kind == "local-decode" || kind == "local-detect" || kind == "local-aggregate") {
      gst_pad_add_probe(pad, GST_PAD_PROBE_TYPE_BUFFER, &NativeProbeRuntime::local_stage_probe, ctx, nullptr);
    } else {
      gst_pad_add_probe(pad, GST_PAD_PROBE_TYPE_BUFFER, &NativeProbeRuntime::input_rtp_probe, ctx, nullptr);
    }
    gst_object_unref(pad);
    gst_object_unref(element);
  }

  std::string detect_bin() const {
    if (args_.detect_bin.empty()) {
      return "identity";
    }
    return args_.detect_bin;
  }

  bool is_deepstream() const {
    return args_.system == "deepstream";
  }

  std::string edge_pipeline(int stream_id) const {
    std::ostringstream p;
    p << "filesrc name=file_src" << stream_id
      << " ! decodebin ! videoconvert ! videorate ! video/x-raw,framerate=30/1"
      << " ! jpegenc ! rtpjpegpay pt=26 name=pay" << stream_id
      << " ! udpsink name=out_sink" << stream_id << " port=" << (args_.output_port_base + stream_id * args_.port_stride)
      << " sync=false async=false";
    return p.str();
  }

  std::string worker_pipeline(int stream_id) const {
    if (is_deepstream()) {
      return deepstream_worker_pipeline(stream_id);
    }
    std::ostringstream p;
    p << "udpsrc name=src" << stream_id << " port=" << (args_.input_port_base + stream_id * args_.port_stride)
      << " caps=\"application/x-rtp,media=(string)video,encoding-name=(string)JPEG,payload=(int)26\""
      << " ! rtpjpegdepay ! jpegdec ! videoconvert ! " << detect_bin()
      << " ! videoconvert ! jpegenc ! rtpjpegpay pt=26 name=pay" << stream_id
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
    if (is_deepstream()) {
      return deepstream_local_pipeline(stream_id);
    }
    std::ostringstream p;
    p << "filesrc name=file_src" << stream_id
      << " ! decodebin ! videoconvert ! videorate ! video/x-raw,framerate=30/1"
      << " ! queue name=decode_probe" << stream_id
      << " ! " << detect_bin()
      << " ! queue name=detect_probe" << stream_id
      << " ! videoconvert"
      << " ! queue name=aggregate_probe" << stream_id
      << " ! fakesink sync=false async=false";
    return p.str();
  }

  std::string deepstream_local_pipeline(int stream_id) const {
    std::ostringstream p;
    p << "nvstreammux name=mux" << stream_id
      << " batch-size=1 width=1920 height=1080 live-source=0 batched-push-timeout=40000"
      << " ! " << detect_bin()
      << " ! queue name=detect_probe" << stream_id
      << " ! nvvideoconvert ! video/x-raw"
      << " ! queue name=aggregate_probe" << stream_id
      << " ! fakesink sync=false async=false "
      << "uridecodebin name=uri_src" << stream_id
      << " ! queue name=decode_probe" << stream_id
      << " ! nvvideoconvert ! video/x-raw(memory:NVMM),format=NV12"
      << " ! mux" << stream_id << ".sink_0";
    return p.str();
  }

  std::string deepstream_worker_pipeline(int stream_id) const {
    std::ostringstream p;
    p << "nvstreammux name=mux" << stream_id
      << " batch-size=1 width=1920 height=1080 live-source=1 batched-push-timeout=40000"
      << " ! " << detect_bin()
      << " ! nvvideoconvert ! video/x-raw"
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
        set_string_property(pipeline, "file_src" + std::to_string(stream_id), "location", source_for_stream(stream_id));
        set_string_property(pipeline, "out_sink" + std::to_string(stream_id), "host", args_.output_host);
        add_probe(pipeline, "pay" + std::to_string(stream_id), "edge-pay", stream_id);
      } else if (args_.role == "gpu_worker") {
        set_string_property(pipeline, "out_sink" + std::to_string(stream_id), "host", args_.output_host);
        add_probe(pipeline, "src" + std::to_string(stream_id), "input", stream_id);
        add_probe(pipeline, "pay" + std::to_string(stream_id), "worker-pay", stream_id);
      } else if (args_.role == "aggregator") {
        add_probe(pipeline, "src" + std::to_string(stream_id), "input", stream_id);
      } else if (args_.role == "local") {
        if (is_deepstream()) {
          set_string_property(pipeline, "uri_src" + std::to_string(stream_id), "uri", uri_for_stream(stream_id));
        } else {
          set_string_property(pipeline, "file_src" + std::to_string(stream_id), "location", source_for_stream(stream_id));
        }
        add_probe(pipeline, "decode_probe" + std::to_string(stream_id), "local-decode", stream_id);
        add_probe(pipeline, "detect_probe" + std::to_string(stream_id), "local-detect", stream_id);
        add_probe(pipeline, "aggregate_probe" + std::to_string(stream_id), "local-aggregate", stream_id);
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
    else if (key == "--detect-bin") args.detect_bin = value("--detect-bin");
    else if (key == "--min-objects") args.min_objects = std::stoi(value("--min-objects"));
    else if (key == "--max-objects") args.max_objects = std::stoi(value("--max-objects"));
    else throw std::runtime_error("unknown argument: " + key);
  }
  return args;
}

int main(int argc, char** argv) {
  try {
    gst_init(&argc, &argv);
    Args args = parse_args(argc, argv);
    NativeProbeRuntime runtime(std::move(args));
    return runtime.run();
  } catch (const std::exception& exc) {
    std::cerr << "[native-probe][fatal] " << exc.what() << "\n";
    return 2;
  }
}
