#pragma once

#include "checkpoint_admission_transport.hpp"
#include <gst/gst.h>
#include <gst/app/gstappsrc.h>
#include <gst/app/gstappsink.h>
#include <gst/video/video.h>
#include <algorithm>
#include <array>
#include <atomic>
#include <deque>
#include <exception>
#include <functional>
#include <fstream>
#include <cstdlib>
#include <iostream>
#include <memory>
#include <mutex>
#include <set>
#include <sstream>
#include <string>
#include <thread>
#include <vector>
#include <sys/stat.h>

namespace vast::study {
namespace detail {
inline constexpr std::size_t kEncodedAuBytes = 16U * 1024U * 1024U;
inline constexpr std::size_t kTransientBytes = 64U * 1024U * 1024U;
inline constexpr std::size_t kMaximumFrames = 442;
inline constexpr std::size_t kMaximumRowBytes = 2048;

inline void require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}
inline constexpr const char* kClockDomainLabel = "timens-offsets:monotonic=0,0;boottime=0,0";
// Zero monotonic/boottime offsets of the namespace this process runs in share the initial clock;
// a container runtime may still give each container its own namespace inode.
inline std::string actual_clock_domain_label() {
  const auto link = [](const char* path) {
    char name[256];
    const auto count = ::readlink(path, name, sizeof(name));
    require(count > 0 && count < static_cast<ssize_t>(sizeof(name)), "study clock namespace is unavailable");
    return std::string(name, static_cast<std::size_t>(count));
  };
  require(link("/proc/self/ns/time") == link("/proc/self/ns/time_for_children"),
          "study clock time and time_for_children namespaces differ");
  std::ifstream input("/proc/self/timens_offsets");
  std::vector<std::string> words; std::string word;
  while (words.size() <= 6 && input >> word) words.push_back(word);
  require(words == std::vector<std::string>{"monotonic", "0", "0", "boottime", "0", "0"},
          "study clock namespace offsets are missing, malformed or nonzero");
  return kClockDomainLabel;
}
inline void verify_original_preparation_clock() {
  const char* expected_boot = std::getenv("VAST_CHECKPOINT_PREPARATION_CLOCK_BOOT_ID");
  const char* expected_namespace = std::getenv("VAST_CHECKPOINT_PREPARATION_CLOCK_TIME_NAMESPACE");
  std::ifstream input("/proc/sys/kernel/random/boot_id"); std::string actual_boot;
  std::string actual_domain;
  try { actual_domain = actual_clock_domain_label(); } catch (const std::exception&) {}
  require(expected_boot && *expected_boot && expected_namespace && *expected_namespace &&
          bool(std::getline(input, actual_boot)) && actual_boot == expected_boot &&
          !actual_domain.empty() && actual_domain == expected_namespace,
          "clock namespace proof missing or mismatched");
}
inline std::string quote(const std::string& input) {
  std::string result = "\"";
  for (unsigned char value : input) {
    if (value == '"' || value == '\\') { result += '\\'; result += static_cast<char>(value); }
    else if (value < 32 || value == 127) throw std::runtime_error("study JSON text contains controls");
    else result += static_cast<char>(value);
  }
  return result + '"';
}
inline std::uint64_t integer(const char* text) {
  require(text && *text, "study CLI integer is missing");
  std::uint64_t result = 0;
  for (const unsigned char* p = reinterpret_cast<const unsigned char*>(text); *p; ++p) {
    require(*p >= '0' && *p <= '9', "study CLI integer is not decimal");
    require(result <= (UINT64_MAX - (*p - '0')) / 10, "study CLI integer overflow");
    result = result * 10 + *p - '0';
  }
  return result;
}
inline void geometry(int width, int height) {
  require(width >= 2 && height >= 2 && width <= 1920 && height <= 1080 &&
          width % 2 == 0 && height % 2 == 0, "study active geometry exceeds bounded even 8-bit420 domain");
}
inline std::string caps_text(GstCaps* caps) {
  gchar* text = gst_caps_to_string(caps); require(text != nullptr, "study caps serialization failed");
  std::string result(text); g_free(text); return result;
}
inline GstCaps* raw_caps(int width, int height, bool rgb) {
  geometry(width, height);
  GstVideoInfo info{}; gst_video_info_init(&info);
  require(gst_video_info_set_format(&info, rgb ? GST_VIDEO_FORMAT_RGB : GST_VIDEO_FORMAT_NV12, width, height),
          "study raw format cannot be constructed");
  info.fps_n = 30; info.fps_d = 1;
  info.interlace_mode = GST_VIDEO_INTERLACE_MODE_PROGRESSIVE;
  info.colorimetry.range = rgb ? GST_VIDEO_COLOR_RANGE_0_255 : GST_VIDEO_COLOR_RANGE_16_235;
  info.colorimetry.matrix = rgb ? GST_VIDEO_COLOR_MATRIX_RGB : GST_VIDEO_COLOR_MATRIX_BT709;
  info.colorimetry.transfer = GST_VIDEO_TRANSFER_BT709;
  info.colorimetry.primaries = GST_VIDEO_COLOR_PRIMARIES_BT709;
  info.chroma_site = rgb ? GST_VIDEO_CHROMA_SITE_NONE : GST_VIDEO_CHROMA_SITE_MPEG2;
  GstCaps* caps = gst_video_info_to_caps(&info);
  require(caps != nullptr, "study fixed raw caps unavailable");
  gst_caps_set_features(caps, 0, gst_caps_features_new(GST_CAPS_FEATURE_MEMORY_SYSTEM_MEMORY, nullptr));
  return caps;
}
struct Checksum {
  GChecksum* value = g_checksum_new(G_CHECKSUM_SHA256);
  Checksum() { require(value != nullptr, "study SHA256 allocation failed"); }
  ~Checksum() { g_checksum_free(value); }
  void update(const std::uint8_t* data, std::size_t bytes) { g_checksum_update(value, data, bytes); }
  std::string text() const { return g_checksum_get_string(value); }
};
inline std::string bytes_sha(const std::uint8_t* bytes, std::size_t count) {
  Checksum hash; hash.update(bytes, count); return hash.text();
}

struct ActiveHashes {
  std::string y_sha256, u_sha256, v_sha256, nv12_sha256, i420_sha256, rgb_sha256;
  std::uint64_t pts = GST_CLOCK_TIME_NONE, dts = GST_CLOCK_TIME_NONE, duration = GST_CLOCK_TIME_NONE;
  std::string caps, caps_actual, caps_actual_sha256;
};
// Pinned caps text only if the actual fixed caps, without the GStreamer default
// multiview-mode=mono / multiview-flags=0:ffffffff fields, are structurally equal.
inline std::string canonical_caps_text(GstCaps* actual, int width, int height, bool rgb) {
  GstCaps* stripped = gst_caps_copy(actual);
  GstStructure* structure = gst_caps_get_structure(stripped, 0);
  const gchar* mode = gst_structure_get_string(structure, "multiview-mode");
  if (mode && std::string(mode) == "mono") gst_structure_remove_field(structure, "multiview-mode");
  guint flags = 0, mask = 0;
  if (gst_structure_has_field(structure, "multiview-flags") &&
      gst_structure_get_flagset(structure, "multiview-flags", &flags, &mask) &&
      flags == 0 && mask == GST_FLAG_SET_MASK_EXACT)
    gst_structure_remove_field(structure, "multiview-flags");
  GstCaps* pinned = raw_caps(width, height, rgb);
  const bool equal = gst_caps_is_equal(stripped, pinned);
  const std::string text = caps_text(equal ? pinned : stripped);
  gst_caps_unref(pinned); gst_caps_unref(stripped);
  return text;
}
inline ActiveHashes active_hashes(
    GstBuffer* buffer, GstCaps* caps, int width, int height, bool rgb,
    const CheckpointIoDeadline& io) {
  io.check(); geometry(width, height);
  require(buffer && caps && gst_caps_is_fixed(caps) && gst_caps_get_size(caps) == 1,
          "study active buffer/caps are missing or nonfixed");
  const GstCapsFeatures* features = gst_caps_get_features(caps, 0);
  require(features && !gst_caps_features_is_any(features) &&
          gst_caps_features_contains(features, GST_CAPS_FEATURE_MEMORY_SYSTEM_MEMORY),
          "study reference requires actual SystemMemory");
  GstVideoInfo info{};
  require(gst_video_info_from_caps(&info, caps) && GST_VIDEO_INFO_WIDTH(&info) == width &&
          GST_VIDEO_INFO_HEIGHT(&info) == height && GST_VIDEO_INFO_FPS_N(&info) == 30 &&
          GST_VIDEO_INFO_FPS_D(&info) == 1 && info.interlace_mode == GST_VIDEO_INTERLACE_MODE_PROGRESSIVE &&
          GST_VIDEO_INFO_FORMAT(&info) == (rgb ? GST_VIDEO_FORMAT_RGB : GST_VIDEO_FORMAT_NV12),
          "study active format/geometry/framerate mismatch");
  require(info.colorimetry.range == (rgb ? GST_VIDEO_COLOR_RANGE_0_255 : GST_VIDEO_COLOR_RANGE_16_235) &&
          info.colorimetry.matrix == (rgb ? GST_VIDEO_COLOR_MATRIX_RGB : GST_VIDEO_COLOR_MATRIX_BT709) &&
          info.colorimetry.transfer == GST_VIDEO_TRANSFER_BT709 &&
          info.colorimetry.primaries == GST_VIDEO_COLOR_PRIMARIES_BT709 &&
          (rgb || info.chroma_site == GST_VIDEO_CHROMA_SITE_MPEG2),
          "study active actual colour tuple mismatch");
  require(gst_buffer_get_size(buffer) <= kTransientBytes, "study active buffer exceeds transient cap");
  const GstVideoMeta* meta = gst_buffer_get_video_meta(buffer);
  const unsigned planes = rgb ? 1 : 2;
  if (meta) require(meta->format == GST_VIDEO_INFO_FORMAT(&info) && meta->width == static_cast<unsigned>(width) &&
                    meta->height == static_cast<unsigned>(height) && meta->n_planes == planes,
                    "study actual video metadata geometry/format mismatch");
  for (unsigned plane = 0; plane < planes; ++plane) {
    const auto stride = meta ? meta->stride[plane] : info.stride[plane];
    const auto offset = meta ? meta->offset[plane] : info.offset[plane];
    const std::size_t active = rgb ? static_cast<std::size_t>(width) * 3 : width;
    const std::size_t rows = plane == 0 ? height : height / 2;
    const auto size = gst_buffer_get_size(buffer);
    require(stride > 0 && static_cast<std::size_t>(stride) >= active && offset <= size &&
            static_cast<std::size_t>(stride) <= kTransientBytes &&
            (rows - 1) * static_cast<std::size_t>(stride) <= size - offset &&
            active <= size - offset - (rows - 1) * static_cast<std::size_t>(stride),
            "study active plane offset/stride escapes allocation");
  }
  GstVideoFrame mapped{};
  require(gst_video_frame_map(&mapped, &info, buffer, GST_MAP_READ), "study active plane map failed");
  ActiveHashes result;
  try {
    result.pts = GST_BUFFER_PTS(buffer); result.dts = GST_BUFFER_DTS(buffer);
    result.duration = GST_BUFFER_DURATION(buffer); result.caps_actual = caps_text(caps);
    result.caps_actual_sha256 = bytes_sha(reinterpret_cast<const std::uint8_t*>(result.caps_actual.data()), result.caps_actual.size());
    result.caps = canonical_caps_text(caps, width, height, rgb);
    require(GST_CLOCK_TIME_IS_VALID(result.pts), "study actual frame PTS is missing");
    if (rgb) {
      Checksum hash;
      const auto* data = static_cast<const std::uint8_t*>(GST_VIDEO_FRAME_PLANE_DATA(&mapped, 0));
      for (int row = 0; row < height; ++row) { io.check(); hash.update(data + row * GST_VIDEO_FRAME_PLANE_STRIDE(&mapped, 0), width * 3); }
      result.rgb_sha256 = hash.text();
    } else {
      Checksum y, u, v, packed_nv12, packed_i420;
      const auto* luma = static_cast<const std::uint8_t*>(GST_VIDEO_FRAME_PLANE_DATA(&mapped, 0));
      const auto* chroma = static_cast<const std::uint8_t*>(GST_VIDEO_FRAME_PLANE_DATA(&mapped, 1));
      std::vector<std::uint8_t> u_row(width / 2), v_row(width / 2);
      for (int row = 0; row < height; ++row) {
        io.check(); const auto* data = luma + row * GST_VIDEO_FRAME_PLANE_STRIDE(&mapped, 0);
        y.update(data, width); packed_nv12.update(data, width); packed_i420.update(data, width);
      }
      for (int row = 0; row < height / 2; ++row) {
        io.check(); const auto* data = chroma + row * GST_VIDEO_FRAME_PLANE_STRIDE(&mapped, 1);
        for (int col = 0; col < width / 2; ++col) { u_row[col] = data[2 * col]; v_row[col] = data[2 * col + 1]; }
        u.update(u_row.data(), u_row.size()); v.update(v_row.data(), v_row.size());
        packed_nv12.update(data, width); packed_i420.update(u_row.data(), u_row.size());
      }
      for (int row = 0; row < height / 2; ++row) {
        io.check(); const auto* data = chroma + row * GST_VIDEO_FRAME_PLANE_STRIDE(&mapped, 1);
        for (int col = 0; col < width / 2; ++col) v_row[col] = data[2 * col + 1];
        packed_i420.update(v_row.data(), v_row.size());
      }
      result.y_sha256 = y.text(); result.u_sha256 = u.text(); result.v_sha256 = v.text();
      result.nv12_sha256 = packed_nv12.text(); result.i420_sha256 = packed_i420.text();
    }
  } catch (...) { gst_video_frame_unmap(&mapped); throw; }
  gst_video_frame_unmap(&mapped); io.check(); return result;
}

inline bool read_exact(int fd, void* data, std::size_t count, bool allow_eof, const CheckpointIoDeadline& io) {
  auto* bytes = static_cast<std::uint8_t*>(data); std::size_t position = 0;
  while (position < count) {
    io.check(); const auto received = ::read(fd, bytes + position, count - position);
    if (received < 0 && errno == EINTR) continue;
    if (received < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) { io.wait(fd, POLLIN); continue; }
    if (received == 0 && position == 0 && allow_eof) return false;
    require(received > 0, "short original study input body"); position += static_cast<std::size_t>(received);
  }
  io.check(); return true;
}
inline bool read_transport_frame(int fd, CheckpointAdmissionFrame& frame, const CheckpointIoDeadline& io, std::uint64_t sequence) {
  if (!CheckpointAdmissionTransport::read_frame(fd, frame, &io, kEncodedAuBytes)) return false;
  require(sequence <= kMaximumFrames && frame.sequence == sequence && frame.source_cycle == 0 && frame.keyframe &&
          frame.duration_ns > 0 && GST_CLOCK_TIME_IS_VALID(frame.transport_pts_ns) &&
          frame.access_unit_dts_ns == frame.transport_pts_ns,
          "study transport sequence/cycle/keyframe/identity/duration mismatch");
  require(bytes_sha(frame.payload.data(), frame.payload.size()) == frame.payload_sha256,
          "study transport actual payload SHA256 mismatch");
  io.check(); return true;
}

inline int open_parent(const std::string& path, std::string& name) {
  require(!path.empty() && path[0] == '/' && path.size() <= 4096, "study file path must be bounded and absolute");
  int directory = ::open("/", O_DIRECTORY | O_RDONLY | O_CLOEXEC);
  require(directory >= 0, "study root directory open failed");
  std::size_t offset = 1;
  try {
    while (true) {
      const auto slash = path.find('/', offset); const auto part = path.substr(offset, slash - offset);
      require(!part.empty() && part != "." && part != "..", "study path contains an empty/traversal component");
      if (slash == std::string::npos) { name = part; return directory; }
      const int next = ::openat(directory, part.c_str(), O_DIRECTORY | O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
      require(next >= 0, "study ancestor is missing or linked"); ::close(directory); directory = next; offset = slash + 1;
    }
  } catch (...) { ::close(directory); throw; }
}
inline bool same_epoch(const struct stat& a, const struct stat& b) {
  return a.st_dev == b.st_dev && a.st_ino == b.st_ino && a.st_size == b.st_size &&
         a.st_mode == b.st_mode && a.st_uid == b.st_uid && a.st_gid == b.st_gid && a.st_nlink == b.st_nlink &&
         a.st_mtim.tv_sec == b.st_mtim.tv_sec && a.st_mtim.tv_nsec == b.st_mtim.tv_nsec &&
         a.st_ctim.tv_sec == b.st_ctim.tv_sec && a.st_ctim.tv_nsec == b.st_ctim.tv_nsec;
}
struct HeldFile {
  int parent = -1, fd = -1; std::string path, name; struct stat initial{};
  HeldFile(const std::string& input, const CheckpointIoDeadline& io) : path(input) {
    io.check(); parent = open_parent(path, name);
    fd = ::openat(parent, name.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0 || ::fstat(fd, &initial) != 0 || !S_ISREG(initial.st_mode) || initial.st_nlink != 1 ||
        initial.st_size <= 0 || static_cast<std::uint64_t>(initial.st_size) > 512U * 1024U * 1024U) {
      if (fd >= 0) { ::close(fd); } ::close(parent); fd = parent = -1;
      throw std::runtime_error("study input is not a bounded no-link regular file");
    }
  }
  ~HeldFile() { if (fd >= 0) ::close(fd); if (parent >= 0) ::close(parent); }
  std::string checksum(const CheckpointIoDeadline& io) const {
    Checksum hash; std::array<std::uint8_t, 65536> bytes{}; off_t offset = 0;
    while (offset < initial.st_size) {
      io.check(); const auto received = ::pread(fd, bytes.data(), std::min<off_t>(bytes.size(), initial.st_size - offset), offset);
      if (received < 0 && errno == EINTR) continue;
      require(received > 0, "short held original study input"); hash.update(bytes.data(), received); offset += received;
    }
    verify(io); return hash.text();
  }
  void verify(const CheckpointIoDeadline& io) const {
    io.check(); struct stat held{}, visible{}; std::string final_name;
    const int current_parent = open_parent(path, final_name); struct stat before_parent{}, after_parent{};
    const bool same_parent = ::fstat(parent, &before_parent) == 0 && ::fstat(current_parent, &after_parent) == 0 &&
                             before_parent.st_dev == after_parent.st_dev && before_parent.st_ino == after_parent.st_ino;
    ::close(current_parent);
    require(same_parent && final_name == name && ::fstat(fd, &held) == 0 &&
            ::fstatat(parent, name.c_str(), &visible, AT_SYMLINK_NOFOLLOW) == 0 &&
            same_epoch(initial, held) && same_epoch(initial, visible), "study held input/path epoch changed");
  }
  void finish(const CheckpointIoDeadline& io) {
    verify(io); const int input = fd; fd = -1;
    require(::close(input) == 0, "study held input close failed"); io.check();
    const int directory = parent; parent = -1;
    require(::close(directory) == 0, "study held input parent close failed"); io.check();
  }
};
struct Jsonl {
  int parent = -1, fd = -1; std::size_t bytes = 0; std::string path, name; struct stat opened{};
  const CheckpointIoDeadline& io;
  Jsonl(const std::string& output, const CheckpointIoDeadline& clock) : path(output), io(clock) {
    io.check(); parent = open_parent(path, name);
    fd = ::openat(parent, name.c_str(), O_CREAT | O_EXCL | O_RDWR | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (fd < 0 || ::fstat(fd, &opened) != 0 || !S_ISREG(opened.st_mode) || opened.st_nlink != 1 || opened.st_uid != ::geteuid()) {
      if (fd >= 0) { ::close(fd); } ::close(parent); fd = parent = -1;
      throw std::runtime_error("study output is not an exclusive owned regular file");
    }
  }
  ~Jsonl() { if (fd >= 0) ::close(fd); if (parent >= 0) ::close(parent); }
  void row(const std::string& text) {
    io.check(); require(text.size() + 1 <= kMaximumRowBytes && bytes + text.size() + 1 <= (kMaximumFrames + 2) * kMaximumRowBytes,
                        "study JSONL row/file exceeds finite bound");
    const std::string line = text + '\n'; std::size_t position = 0;
    while (position < line.size()) {
      io.check(); const auto written = ::write(fd, line.data() + position, line.size() - position);
      if (written < 0 && errno == EINTR) continue;
      require(written > 0, "short study JSONL write"); position += static_cast<std::size_t>(written);
    }
    bytes += line.size(); io.check();
  }
  void finish() {
    io.check(); require(::fsync(fd) == 0, "study output fsync failed"); io.check();
    struct stat held{}, visible{}, old_parent{}, current{}; std::string final_name;
    const int current_parent = open_parent(path, final_name);
    const bool parent_same = ::fstat(parent, &old_parent) == 0 && ::fstat(current_parent, &current) == 0 &&
                             old_parent.st_dev == current.st_dev && old_parent.st_ino == current.st_ino;
    ::close(current_parent);
    require(parent_same && final_name == name && ::fstat(fd, &held) == 0 &&
            ::fstatat(parent, name.c_str(), &visible, AT_SYMLINK_NOFOLLOW) == 0 &&
            held.st_dev == opened.st_dev && held.st_ino == opened.st_ino && held.st_nlink == 1 &&
            held.st_uid == opened.st_uid && held.st_mode == opened.st_mode &&
            held.st_size == static_cast<off_t>(bytes) && same_epoch(held, visible),
            "study exclusive output custody changed before close");
    const int closing = fd; fd = -1;
    require(::close(closing) == 0, "study output close failed"); io.check();
    const int closing_parent = parent; parent = -1;
    require(::close(closing_parent) == 0, "study output parent close failed"); io.check();
  }
};
inline std::string timestamp(std::uint64_t value) { return GST_CLOCK_TIME_IS_VALID(value) ? std::to_string(value) : "null"; }
}  // namespace detail

inline std::string color_prefix_fragment(int width, int height) {
  GstCaps* nv12 = detail::raw_caps(width, height, false); GstCaps* rgb = detail::raw_caps(width, height, true);
  const auto input = detail::caps_text(nv12), output = detail::caps_text(rgb);
  gst_caps_unref(nv12); gst_caps_unref(rgb);
  return input + " ! videoconvert n-threads=1 dither=none chroma-resampler=linear chroma-mode=full "
                 "matrix-mode=full gamma-mode=none primaries-mode=none alpha-mode=copy alpha-value=1.0 ! " + output;
}

namespace detail {
inline std::string prefix_description(int width, int height) {
  const auto fragment = color_prefix_fragment(width, height);
  const std::string validation = "identity ! " + fragment + " ! identity";
  GError* error = nullptr; GstElement* bin = gst_parse_bin_from_description(validation.c_str(), TRUE, &error);
  if (!bin || error) {
    const std::string text = error ? error->message : "unknown parse failure";
    if (error) { g_error_free(error); } if (bin) { gst_object_unref(bin); }
    throw std::runtime_error("unsupported fixed study colour prefix: " + text);
  }
  gst_object_unref(bin);
  GstCaps* input = raw_caps(width, height, false); GstCaps* output = raw_caps(width, height, true);
  const std::string result = "{\"nv12_caps\":" + quote(caps_text(input)) + ",\"rgb_caps\":" + quote(caps_text(output)) +
      ",\"converter_config\":\"n-threads=1;dither=none;chroma-resampler=linear;chroma-mode=full;matrix-mode=full;gamma-mode=none;primaries-mode=none;alpha-mode=copy;alpha-value=1\",\"fragment\":" +
      quote(fragment);
  gchar* version = gst_version_string();
  const std::string completed = result + ",\"gstreamer_runtime\":" + quote(version ? version : "unknown") + "}";
  g_free(version);
  gst_caps_unref(input); gst_caps_unref(output); return completed;
}
inline void bus_error(GstBus* bus, bool& eos) {
  while (GstMessage* message = gst_bus_pop_filtered(bus, static_cast<GstMessageType>(GST_MESSAGE_ERROR | GST_MESSAGE_EOS))) {
    if (GST_MESSAGE_TYPE(message) == GST_MESSAGE_EOS) { eos = true; gst_message_unref(message); continue; }
    GError* error = nullptr; gchar* debug = nullptr; gst_message_parse_error(message, &error, &debug);
    const std::string text = error ? error->message : "unknown GStreamer error";
    if (error) { g_error_free(error); } g_free(debug); gst_message_unref(message);
    throw std::runtime_error("study pipeline failed: " + text);
  }
}
struct Pipeline {
  GstElement* value = nullptr; GstElement* sink = nullptr; GstElement* source = nullptr; GstBus* bus = nullptr;
  bool stopped = false;
  explicit Pipeline(const std::string& text) {
    GError* error = nullptr; value = gst_parse_launch(text.c_str(), &error);
    if (!value || error) {
      const std::string message = error ? error->message : "pipeline parse failed";
      if (error) { g_error_free(error); } if (value) { gst_object_unref(value); } value = nullptr;
      throw std::runtime_error(message);
    }
    sink = gst_bin_get_by_name(GST_BIN(value), "study_sink"); source = gst_bin_get_by_name(GST_BIN(value), "study_source");
    bus = gst_element_get_bus(value);
  }
  ~Pipeline() {
    if (value) { if (!stopped) gst_element_set_state(value, GST_STATE_NULL); gst_object_unref(value); }
    if (sink) { gst_object_unref(sink); } if (source) { gst_object_unref(source); } if (bus) { gst_object_unref(bus); }
  }
  void stop() {
    if (value && !stopped) {
      require(gst_element_set_state(value, GST_STATE_NULL) != GST_STATE_CHANGE_FAILURE, "study pipeline NULL failed"); stopped = true;
    }
  }
  void finish() {
    stop(); if (sink) gst_object_unref(sink); sink = nullptr;
    if (source) { gst_object_unref(source); } source = nullptr;
    if (bus) { gst_object_unref(bus); } bus = nullptr;
    if (value) { gst_object_unref(value); } value = nullptr;
  }
};
struct Observation {
  CheckpointIoDeadline& io; int width, height; std::mutex mutex; std::deque<ActiveHashes> queue;
  std::exception_ptr failure;
  Observation(CheckpointIoDeadline& io_, int width_, int height_) : io(io_), width(width_), height(height_) {}
  void fail(std::exception_ptr value) {
    { std::lock_guard<std::mutex> lock(mutex); if (!failure) failure = value; }
    io.abort();
  }
  void check() { std::exception_ptr value; { std::lock_guard<std::mutex> lock(mutex); value = failure; } if (value) std::rethrow_exception(value); io.check(); }
};
inline GstPadProbeReturn nv12_probe(GstPad* pad, GstPadProbeInfo* info, gpointer raw) noexcept {
  auto& state = *static_cast<Observation*>(raw);
  GstCaps* caps = gst_pad_get_current_caps(pad);
  try {
    auto hashes = active_hashes(GST_PAD_PROBE_INFO_BUFFER(info), caps, state.width, state.height, false, state.io);
    std::lock_guard<std::mutex> lock(state.mutex);
    require(state.queue.size() < 4, "study NV12/RGB pairing exceeded bounded streaming queue");
    state.queue.push_back(std::move(hashes));
    if (caps) { gst_caps_unref(caps); } return GST_PAD_PROBE_OK;
  } catch (...) { if (caps) gst_caps_unref(caps); state.fail(std::current_exception()); return GST_PAD_PROBE_DROP; }
}
inline std::string frame_row(std::size_t ordinal, const ActiveHashes& yuv, const ActiveHashes& rgb, int width, int height) {
  return "{\"schema_version\":1,\"type\":\"frame\",\"ordinal\":" + std::to_string(ordinal) +
      ",\"pts_ns\":" + timestamp(rgb.pts) + ",\"dts_ns\":" + timestamp(rgb.dts) + ",\"duration_ns\":" + timestamp(rgb.duration) +
      ",\"width\":" + std::to_string(width) + ",\"height\":" + std::to_string(height) +
      ",\"y_sha256\":" + quote(yuv.y_sha256) + ",\"u_sha256\":" + quote(yuv.u_sha256) + ",\"v_sha256\":" + quote(yuv.v_sha256) +
      ",\"nv12_sha256\":" + quote(yuv.nv12_sha256) + ",\"i420_sha256\":" + quote(yuv.i420_sha256) +
      ",\"rgb_sha256\":" + quote(rgb.rgb_sha256) + ",\"active_y_bytes\":" + std::to_string(width * height) +
      ",\"active_u_bytes\":" + std::to_string(width * height / 4) + ",\"active_v_bytes\":" + std::to_string(width * height / 4) +
      ",\"rgb_bytes\":" + std::to_string(width * height * 3) + ",\"nv12_caps\":" + quote(yuv.caps) + ",\"rgb_caps\":" + quote(rgb.caps) +
      ",\"nv12_caps_actual_sha256\":" + quote(yuv.caps_actual_sha256) + ",\"rgb_caps_actual_sha256\":" + quote(rgb.caps_actual_sha256) + "}";
}

inline int reference(const std::string& mode, const std::string& input, const std::string& output,
                     int width, int height, std::uint64_t deadline, std::size_t expected) {
  geometry(width, height); require(deadline > 0 && expected > 0 && expected <= kMaximumFrames, "study reference bound is invalid");
  require(mode == "transport" || expected == kMaximumFrames, "full derivative reference requires exactly442 frames");
  CheckpointIoDeadline io(deadline); io.check();
  const std::string completion = mode == "transport" ? "offered_prefix_transport_eof" :
                                 mode == "nv12" ? "independent_nv12_full_eos" : "derived_full_eos";
  std::unique_ptr<HeldFile> held;
  if (mode == "media") held = std::make_unique<HeldFile>(input, io);
  const std::string input_hash = held ? held->checksum(io) : "";
  const auto description = prefix_description(width, height);
  Jsonl writer(output, io);
  writer.row("{\"schema_version\":1,\"type\":\"header\",\"kind\":\"checkpoint_study_reference_v1\",\"completion_kind\":" + quote(completion) +
      ",\"expected_count\":" + std::to_string(expected) + ",\"input_sha256\":" + quote(input_hash) +
      ",\"deadline_monotonic_ns\":" + std::to_string(deadline) + ",\"prefix\":" + description + "}");
  const std::string upstream = mode == "media" ? "filesrc name=study_source ! qtdemux ! h264parse config-interval=-1 ! video/x-h264,stream-format=byte-stream,alignment=au ! nvh264dec ! " :
      mode == "transport" ? "appsrc name=study_source is-live=true format=time do-timestamp=false block=false max-buffers=1 max-bytes=16777216 caps=\"video/x-h264,stream-format=byte-stream,alignment=au\" ! h264parse ! video/x-h264,stream-format=byte-stream,alignment=au ! nvh264dec ! " :
                            "appsrc name=study_source is-live=false format=time do-timestamp=false block=false max-buffers=1 max-bytes=16777216 ! ";
  Pipeline pipeline(upstream + "identity name=study_nv12 ! " + color_prefix_fragment(width, height) +
                    " ! appsink name=study_sink sync=false emit-signals=false max-buffers=1 drop=false");
  if (held) g_object_set(pipeline.source, "location", ("/proc/self/fd/" + std::to_string(held->fd)).c_str(), nullptr);
  if (mode == "nv12") { GstCaps* caps = raw_caps(width, height, false); gst_app_src_set_caps(GST_APP_SRC(pipeline.source), caps); gst_caps_unref(caps); }
  Observation observation{io, width, height};
  GstElement* converter = nullptr;
  {
    GstIterator* iterator = gst_bin_iterate_all_by_element_factory_name(GST_BIN(pipeline.value), "videoconvert");
    GValue item = G_VALUE_INIT; int found = 0;
    while (gst_iterator_next(iterator, &item) == GST_ITERATOR_OK) {
      ++found; if (!converter) converter = GST_ELEMENT(g_value_dup_object(&item)); g_value_reset(&item);
    }
    g_value_unset(&item); gst_iterator_free(iterator);
    if (found != 1) { if (converter) gst_object_unref(converter); throw std::runtime_error("study reference requires exactly one pinned converter"); }
  }
  GstPad* pad = gst_element_get_static_pad(converter, "sink"); gst_object_unref(converter);
  const gulong probe = gst_pad_add_probe(pad, GST_PAD_PROBE_TYPE_BUFFER, nv12_probe, &observation, nullptr);
  std::thread feeder; std::size_t count = 0; std::exception_ptr primary; bool actual_eos = false;
  std::set<std::string> printed_caps;
  try {
    require(gst_element_set_state(pipeline.value, GST_STATE_PLAYING) != GST_STATE_CHANGE_FAILURE, "study reference PLAYING failed");
    if (mode != "media") feeder = std::thread([&]() {
      try {
        CheckpointIoDeadline::set_owned_nonblocking(STDIN_FILENO);
        const std::size_t packed_size = static_cast<std::size_t>(width) * height * 3 / 2;
        std::size_t input_count = 0;
        while (true) {
          io.check(); CheckpointAdmissionFrame frame; std::vector<std::uint8_t> raw;
          if (mode == "transport") { if (!read_transport_frame(STDIN_FILENO, frame, io, input_count + 1)) break; }
          else {
            raw.resize(packed_size);
            if (!read_exact(STDIN_FILENO, raw.data(), raw.size(), true, io)) break;
          }
          require(input_count < expected, "study reference received extra original input frame");
          guint64 queued = 0;
          do {
            io.check(); g_object_get(pipeline.source, "current-level-bytes", &queued, nullptr);
            if (queued) std::this_thread::sleep_for(std::chrono::milliseconds(1));
          } while (queued);
          const auto& bytes = mode == "transport" ? frame.payload : raw;
          GstBuffer* buffer = gst_buffer_new_allocate(nullptr, bytes.size(), nullptr);
          require(buffer != nullptr && gst_buffer_fill(buffer, 0, bytes.data(), bytes.size()) == bytes.size(), "study input buffer copy failed");
          if (mode == "nv12") {
            gsize offsets[GST_VIDEO_MAX_PLANES] = {0, static_cast<gsize>(width) * height, 0, 0};
            gint strides[GST_VIDEO_MAX_PLANES] = {width, width, 0, 0};
            if (!gst_buffer_add_video_meta_full(buffer, GST_VIDEO_FRAME_FLAG_NONE, GST_VIDEO_FORMAT_NV12, width, height, 2, offsets, strides)) {
              gst_buffer_unref(buffer); throw std::runtime_error("study packed NV12 metadata failed");
            }
            GST_BUFFER_PTS(buffer) = gst_util_uint64_scale(input_count, GST_SECOND, 30);
            GST_BUFFER_DTS(buffer) = GST_BUFFER_PTS(buffer); GST_BUFFER_DURATION(buffer) = gst_util_uint64_scale(1, GST_SECOND, 30);
          } else {
            GST_BUFFER_PTS(buffer) = frame.transport_pts_ns;
            GST_BUFFER_DTS(buffer) = frame.access_unit_dts_ns;
            GST_BUFFER_DURATION(buffer) = frame.duration_ns; GST_BUFFER_FLAG_UNSET(buffer, GST_BUFFER_FLAG_DELTA_UNIT);
          }
          require(gst_app_src_push_buffer(GST_APP_SRC(pipeline.source), buffer) == GST_FLOW_OK, "study original appsrc push failed"); ++input_count;
        }
        require(input_count == expected, "study original input count differs from expected prefix/full inventory");
        io.check(); require(gst_app_src_end_of_stream(GST_APP_SRC(pipeline.source)) == GST_FLOW_OK, "study original input EOS failed");
      } catch (...) { observation.fail(std::current_exception()); }
    });
    while (true) {
      observation.check(); bus_error(pipeline.bus, actual_eos);
      GstSample* sample = gst_app_sink_try_pull_sample(GST_APP_SINK(pipeline.sink), 10 * GST_MSECOND);
      if (!sample) { if (actual_eos && gst_app_sink_is_eos(GST_APP_SINK(pipeline.sink))) break; continue; }
      try {
        auto rgb = active_hashes(gst_sample_get_buffer(sample), gst_sample_get_caps(sample), width, height, true, io);
        ActiveHashes yuv;
        { std::lock_guard<std::mutex> lock(observation.mutex); require(!observation.queue.empty(), "study RGB has no actual NV12 input"); yuv = std::move(observation.queue.front()); observation.queue.pop_front(); }
        require(count < expected && rgb.pts == yuv.pts, "study NV12/RGB actual ordinal/PTS/count join failed");
        for (const auto* observed : {&yuv, &rgb})
          if (printed_caps.insert(observed->caps_actual_sha256).second)
            std::cerr << "[study-reference] actual " << (observed == &rgb ? "rgb" : "nv12") << " caps sha256="
                      << observed->caps_actual_sha256 << " " << observed->caps_actual << '\n';
        writer.row(frame_row(count++, yuv, rgb, width, height));
      } catch (...) { gst_sample_unref(sample); throw; }
      gst_sample_unref(sample);
    }
    if (feeder.joinable()) feeder.join();
    observation.check(); bus_error(pipeline.bus, actual_eos);
    { std::lock_guard<std::mutex> lock(observation.mutex); require(observation.queue.empty(), "study EOS left unmatched actual NV12 frames"); }
    require(actual_eos && count == expected, "study decoded EOS count mismatch");
    pipeline.stop(); gst_pad_remove_probe(pad, probe); gst_object_unref(pad); pad = nullptr;
    pipeline.finish(); io.check();
    if (held) held->finish(io);
    writer.row("{\"schema_version\":1,\"type\":\"terminal\",\"success\":true,\"accepted\":false,\"provisional_until_owner_final_close\":true,\"actual_eos\":true,\"decoded_count\":" +
        std::to_string(count) + ",\"completion_kind\":" + quote(completion) + "}");
    writer.finish(); io.check(); return 0;
  } catch (...) { primary = std::current_exception(); io.abort(); }
  // Fatal deadline/read/hash failures publish abort before Gst NULL and join.
  // The caller's owned process guard remains necessary for driver/library hangs.
  try { pipeline.stop(); } catch (...) { if (!primary) primary = std::current_exception(); }
  if (feeder.joinable()) feeder.join();
  if (pad) { gst_pad_remove_probe(pad, probe); gst_object_unref(pad); }
  std::rethrow_exception(primary);
}

inline int inventory(const std::string& input, int width, int height, std::uint64_t deadline) {
  geometry(width, height); require(deadline > 0, "study inventory original deadline missing");
  CheckpointIoDeadline io(deadline); io.check(); HeldFile held(input, io);
  const auto hash = held.checksum(io);
  Pipeline pipeline("filesrc name=study_source ! qtdemux ! h264parse config-interval=-1 ! video/x-h264,stream-format=byte-stream,alignment=au ! appsink name=study_sink sync=false emit-signals=false max-buffers=1 drop=false");
  g_object_set(pipeline.source, "location", ("/proc/self/fd/" + std::to_string(held.fd)).c_str(), nullptr);
  CheckpointIoDeadline::set_owned_nonblocking(STDOUT_FILENO);
  const auto emit = [&](const std::string& row) {
    io.check(); require(row.size() + 1 <= kMaximumRowBytes, "study inventory row exceeds cap");
    const std::string line = row + '\n'; std::size_t position = 0;
    while (position < line.size()) {
      io.check(); const auto written = ::write(STDOUT_FILENO, line.data() + position, line.size() - position);
      if (written < 0 && errno == EINTR) continue;
      if (written < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) { io.wait(STDOUT_FILENO, POLLOUT); continue; }
      require(written > 0, "study inventory stdout failed"); position += written;
    }
    io.check();
  };
  std::size_t count = 0; bool actual_eos = false;
  try {
    emit("{\"schema_version\":1,\"type\":\"header\",\"kind\":\"checkpoint_study_au_inventory_v1\",\"input_sha256\":" + quote(hash) + "}");
    require(gst_element_set_state(pipeline.value, GST_STATE_PLAYING) != GST_STATE_CHANGE_FAILURE, "study inventory PLAYING failed");
    while (true) {
      io.check(); bus_error(pipeline.bus, actual_eos);
      GstSample* sample = gst_app_sink_try_pull_sample(GST_APP_SINK(pipeline.sink), 10 * GST_MSECOND);
      if (!sample) { if (actual_eos && gst_app_sink_is_eos(GST_APP_SINK(pipeline.sink))) break; continue; }
      GstBuffer* buffer = gst_sample_get_buffer(sample); GstCaps* caps = gst_sample_get_caps(sample);
      GstMapInfo map{};
      try {
        require(caps && gst_caps_is_fixed(caps) && gst_caps_get_size(caps) == 1,
                "study original AU actual caps are missing or nonfixed");
        gint actual_width = 0, actual_height = 0; const auto* structure = gst_caps_get_structure(caps, 0);
        require(gst_structure_get_int(structure, "width", &actual_width) && gst_structure_get_int(structure, "height", &actual_height) && actual_width == width && actual_height == height,
                "study original AU caps geometry mismatch");
        require(count < kMaximumFrames && GST_BUFFER_PTS_IS_VALID(buffer) && GST_BUFFER_DTS_IS_VALID(buffer) && GST_BUFFER_DURATION_IS_VALID(buffer) &&
                GST_BUFFER_DURATION(buffer) > 0 && GST_BUFFER_PTS(buffer) == GST_BUFFER_DTS(buffer) &&
                !GST_BUFFER_FLAG_IS_SET(buffer, GST_BUFFER_FLAG_DELTA_UNIT), "study AU count/PTS/DTS/keyframe mismatch");
        require(gst_buffer_map(buffer, &map, GST_MAP_READ) && map.size > 0 && map.size <= kEncodedAuBytes, "study AU map/selected16MiB cap failed");
        emit("{\"schema_version\":1,\"type\":\"au\",\"ordinal\":" + std::to_string(count++) + ",\"pts_ns\":" + timestamp(GST_BUFFER_PTS(buffer)) +
            ",\"dts_ns\":" + timestamp(GST_BUFFER_DTS(buffer)) + ",\"duration_ns\":" + timestamp(GST_BUFFER_DURATION(buffer)) + ",\"payload_sha256\":" +
            quote(bytes_sha(map.data, map.size)) + ",\"payload_size_bytes\":" + std::to_string(map.size) + ",\"keyframe\":true}");
      } catch (...) { if (map.data) gst_buffer_unmap(buffer, &map); gst_sample_unref(sample); throw; }
      gst_buffer_unmap(buffer, &map); gst_sample_unref(sample);
    }
    bus_error(pipeline.bus, actual_eos); require(actual_eos && count == kMaximumFrames, "study AU inventory requires exactly442 actual EOS rows");
    pipeline.finish(); held.finish(io);
    emit("{\"schema_version\":1,\"type\":\"terminal\",\"success\":true,\"accepted\":false,\"provisional_until_capture_return\":true,\"actual_eos\":true,\"au_count\":442}");
    io.check(); return 0;
  } catch (...) { io.abort(); throw; }
}
}  // namespace detail

inline int dispatch_reference_cli(int argc, char** argv, bool& handled) {
  handled = argc > 1 && (std::string(argv[1]) == "--checkpoint-study-prefix-description" ||
      std::string(argv[1]) == "--checkpoint-study-reference" || std::string(argv[1]) == "--checkpoint-study-reference-nv12" ||
      std::string(argv[1]) == "--checkpoint-study-reference-transport");
  if (!handled) return 0;
  try {
    const std::string mode(argv[1]);
    if (mode == "--checkpoint-study-prefix-description") {
      if (!gst_is_initialized()) gst_init(nullptr, nullptr);
      detail::require(argc == 4, "study prefix-description requires WIDTH HEIGHT");
      const auto width = detail::integer(argv[2]), height = detail::integer(argv[3]);
      detail::require(width <= 1920 && height <= 1080, "study prefix geometry overflow");
      std::cout << detail::prefix_description(width, height) << '\n'; return bool(std::cout) ? 0 : 1;
    }
    detail::verify_original_preparation_clock();
    if (!gst_is_initialized()) gst_init(nullptr, nullptr);
    const bool media = mode == "--checkpoint-study-reference";
    detail::require(argc == (media ? 8 : 7), "study reference exact arguments mismatch");
    const int offset = media ? 1 : 0;
    const auto width = detail::integer(argv[3 + offset]), height = detail::integer(argv[4 + offset]);
    detail::require(width <= 1920 && height <= 1080, "study reference geometry overflow");
    return detail::reference(media ? "media" : mode == "--checkpoint-study-reference-nv12" ? "nv12" : "transport",
        media ? argv[2] : "", argv[2 + offset], width, height, detail::integer(argv[5 + offset]), detail::integer(argv[6 + offset]));
  } catch (const std::exception& error) { std::cerr << "[study-reference] " << error.what() << '\n'; return 1; }
}
inline int dispatch_au_inventory_cli(int argc, char** argv, bool& handled) {
  handled = argc > 1 && std::string(argv[1]) == "--checkpoint-study-au-inventory";
  if (!handled) return 0;
  try {
    detail::require(argc == 6, "study AU inventory requires PATH WIDTH HEIGHT DEADLINE_NS");
    detail::verify_original_preparation_clock();
    if (!gst_is_initialized()) gst_init(nullptr, nullptr);
    const auto width = detail::integer(argv[3]), height = detail::integer(argv[4]);
    detail::require(width <= 1920 && height <= 1080, "study AU inventory geometry overflow");
    return detail::inventory(argv[2], width, height, detail::integer(argv[5]));
  } catch (const std::exception& error) { std::cerr << "[study-inventory] " << error.what() << '\n'; return 1; }
}
}  // namespace vast::study
