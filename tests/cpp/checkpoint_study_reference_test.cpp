#include "checkpoint_study_reference.hpp"

#include <gst/gst.h>
#include <gst/video/video.h>
#include <dirent.h>
#include <fcntl.h>
#include <unistd.h>

#include <atomic>
#include <condition_variable>
#include <fstream>
#include <future>
#include <iostream>
#include <mutex>
#include <sstream>
#include <thread>
#include <vector>

namespace {
void require(bool value, const char* message) {
  if (!value) throw std::runtime_error(message);
}
template <class Call> void refuses(Call call, const char* message) {
  bool failed = false;
  try { call(); } catch (const std::exception&) { failed = true; }
  require(failed, message);
}
std::string sha(const std::vector<std::uint8_t>& bytes) {
  gchar* result = g_compute_checksum_for_data(G_CHECKSUM_SHA256, bytes.data(), bytes.size());
  std::string text(result); g_free(result); return text;
}
int fd_count() {
  DIR* directory = ::opendir("/proc/self/fd");
  require(directory != nullptr, "real FD inventory unavailable");
  int count = 0;
  while (dirent* entry = ::readdir(directory)) if (entry->d_name[0] != '.') ++count;
  ::closedir(directory); return count;
}
std::string read_file(const std::string& path) {
  std::ifstream input(path); std::ostringstream output; output << input.rdbuf(); return output.str();
}
void bind_actual_preparation_clock() {
  std::ifstream boot_file("/proc/sys/kernel/random/boot_id"); std::string boot;
  require(bool(std::getline(boot_file, boot)) && !boot.empty(), "actual boot identity unavailable");
  const std::string time_namespace = vast::study::detail::actual_clock_domain_label();
  require(::setenv("VAST_CHECKPOINT_PREPARATION_CLOCK_BOOT_ID", boot.c_str(), 1) == 0 &&
          ::setenv("VAST_CHECKPOINT_PREPARATION_CLOCK_TIME_NAMESPACE", time_namespace.c_str(), 1) == 0,
          "actual clock proof fixture setup failed");
}
void actual_clock_domain_guard(const std::string& directory) {
  const int before = fd_count();
  const std::string output = directory + "/foreign-clock.jsonl";
  const auto deadline = std::to_string(vast::CheckpointIoDeadline::monotonic_now_ns() + 1000000000ULL);
  char inode[256]; const auto inode_count = ::readlink("/proc/self/ns/time", inode, sizeof(inode));
  require(inode_count > 0 && inode_count < static_cast<ssize_t>(sizeof(inode)), "actual time namespace unavailable");
  // The former inode proof value is no longer a clock-domain proof.
  const std::string old_inode_proof(inode, static_cast<std::size_t>(inode_count));
  for (bool inventory : {true, false}) for (int variant : {0, 1, 2}) {
    bind_actual_preparation_clock();
    if (variant == 0) ::unsetenv("VAST_CHECKPOINT_PREPARATION_CLOCK_BOOT_ID");
    else ::setenv("VAST_CHECKPOINT_PREPARATION_CLOCK_TIME_NAMESPACE",
                  variant == 1 ? "time:[foreign-fixture]" : old_inode_proof.c_str(), 1);
    std::vector<std::string> text = inventory ?
        std::vector<std::string>{"unit", "--checkpoint-study-au-inventory", "/proc/vast-clock-fixture-missing.mp4", "8", "4", deadline} :
        std::vector<std::string>{"unit", "--checkpoint-study-reference", "/proc/vast-clock-fixture-missing.mp4", output, "8", "4", deadline, "442"};
    std::vector<char*> argv; for (auto& value : text) argv.push_back(value.data());
    bool handled = false; std::ostringstream captured; auto* original = std::cerr.rdbuf(captured.rdbuf());
    const int result = inventory ? vast::study::dispatch_au_inventory_cli(argv.size(), argv.data(), handled) :
                                  vast::study::dispatch_reference_cli(argv.size(), argv.data(), handled);
    std::cerr.rdbuf(original);
    require(handled && result == 1 &&
            captured.str().find("clock namespace proof missing or mismatched") != std::string::npos,
            "timed CLI reached media ownership before verifying the actual deadline clock domain");
    require(::access(output.c_str(), F_OK) != 0 && fd_count() == before,
            "foreign clock fixture acquired output or leaked descriptors");
  }
  bind_actual_preparation_clock();
}

void actual_caps_and_strides() {
  auto io = vast::CheckpointIoDeadline(vast::CheckpointIoDeadline::monotonic_now_ns() + 2000000000);
  GstCaps* caps = vast::study::detail::raw_caps(8, 4, false);
  GstBuffer* padded = gst_buffer_new_allocate(nullptr, 72, nullptr);
  GST_BUFFER_PTS(padded) = 0; GST_BUFFER_DTS(padded) = 0; GST_BUFFER_DURATION(padded) = 33333333;
  GstMapInfo memory{};
  require(gst_buffer_map(padded, &memory, GST_MAP_WRITE), "padded buffer allocation failed");
  std::fill(memory.data, memory.data + memory.size, 0xaa);
  for (int row = 0; row < 4; ++row) std::fill(memory.data + row * 12, memory.data + row * 12 + 8, 16);
  for (int row = 0; row < 2; ++row) for (int col = 0; col < 4; ++col) {
    memory.data[48 + row * 12 + col * 2] = 80;
    memory.data[48 + row * 12 + col * 2 + 1] = 170;
  }
  gst_buffer_unmap(padded, &memory);
  gsize offsets[GST_VIDEO_MAX_PLANES] = {0, 48, 0, 0};
  gint strides[GST_VIDEO_MAX_PLANES] = {12, 12, 0, 0};
  auto* meta = gst_buffer_add_video_meta_full(padded, GST_VIDEO_FRAME_FLAG_NONE,
      GST_VIDEO_FORMAT_NV12, 8, 4, 2, offsets, strides);
  require(meta != nullptr, "real padded video metadata unavailable");
  const auto hashes = vast::study::detail::active_hashes(padded, caps, 8, 4, false, io);
  std::vector<std::uint8_t> expected_nv12(32, 16), expected_i420(32, 16);
  for (int index = 0; index < 8; ++index) { expected_nv12.push_back(80); expected_nv12.push_back(170); }
  expected_i420.insert(expected_i420.end(), 8, 80); expected_i420.insert(expected_i420.end(), 8, 170);
  require(hashes.y_sha256 == sha(std::vector<std::uint8_t>(32, 16)) &&
          hashes.u_sha256 == sha(std::vector<std::uint8_t>(8, 80)) &&
          hashes.v_sha256 == sha(std::vector<std::uint8_t>(8, 170)) &&
          hashes.nv12_sha256 == sha(expected_nv12) && hashes.i420_sha256 == sha(expected_i420),
          "active Y/U/V packing accidentally hashed padding or interleaved planes");
  meta->stride[0] = 7;
  refuses([&]() { (void)vast::study::detail::active_hashes(padded, caps, 8, 4, false, io); },
          "short active stride accepted");
  meta->stride[0] = 12; meta->offset[1] = 70;
  refuses([&]() { (void)vast::study::detail::active_hashes(padded, caps, 8, 4, false, io); },
          "active chroma escaped its real allocation");
  meta->offset[1] = 48;
  gst_caps_set_simple(caps, "framerate", GST_TYPE_FRACTION, 600, 1, nullptr);
  refuses([&]() { (void)vast::study::detail::active_hashes(padded, caps, 8, 4, false, io); },
          "encoded600 caps accepted as nominal30");
  gst_caps_set_simple(caps, "framerate", GST_TYPE_FRACTION, 30, 1, "colorimetry", G_TYPE_STRING, "1:3:5:1", nullptr);
  refuses([&]() { (void)vast::study::detail::active_hashes(padded, caps, 8, 4, false, io); },
          "full-range input accepted as fixed limited709");
  gst_caps_unref(caps); gst_buffer_unref(padded);
}

void actual_transport_eof() {
  const int before = fd_count();
  int descriptors[2]; require(::pipe(descriptors) == 0, "real transport pipe unavailable");
  auto io = vast::CheckpointIoDeadline(vast::CheckpointIoDeadline::monotonic_now_ns() + 2000000000);
  vast::CheckpointAdmissionFrame expected;
  expected.sequence = 1; expected.keyframe = true; expected.duration_ns = 33333333;
  expected.access_unit_pts_ns = 0; expected.transport_pts_ns = 0; expected.access_unit_dts_ns = 0;
  expected.admission_id = "unit-admission:1"; expected.input_frame_key = "unit-frame:1";
  expected.payload = {0, 0, 0, 1, 0x65, 0x88}; expected.payload_sha256 = sha(expected.payload);
  std::exception_ptr writer_error;
  std::thread writer([&]() {
    try { vast::CheckpointAdmissionTransport::write_frame(descriptors[1], expected, &io); }
    catch (...) { writer_error = std::current_exception(); }
    ::close(descriptors[1]);
  });
  vast::CheckpointAdmissionFrame actual;
  std::exception_ptr primary;
  try {
    require(vast::study::detail::read_transport_frame(descriptors[0], actual, io, 1) &&
            actual.payload == expected.payload && actual.duration_ns == expected.duration_ns,
            "genuine 80-byte wire header/payload was not read intact");
    require(!vast::study::detail::read_transport_frame(descriptors[0], actual, io, 2),
            "closed transport EOF was not distinct from another access unit");
  } catch (...) { primary = std::current_exception(); io.abort(); }
  writer.join(); ::close(descriptors[0]);
  if (primary) std::rethrow_exception(primary);
  if (writer_error) std::rethrow_exception(writer_error);
  require(fd_count() == before, "transport fixture leaked real endpoints");
  require(::pipe(descriptors) == 0, "malformed timestamp pipe unavailable");
  expected.access_unit_dts_ns = 1;
  vast::CheckpointAdmissionTransport::write_frame(descriptors[1], expected, &io);
  ::close(descriptors[1]);
  refuses([&]() { (void)vast::study::detail::read_transport_frame(descriptors[0], actual, io, 1); },
          "all-I source PTS/DTS mismatch reached reference decode");
  ::close(descriptors[0]); require(fd_count() == before, "timestamp mismatch fixture leaked FD");
  require(::pipe(descriptors) == 0, "partial header pipe unavailable");
  const char partial[] = "VASTAU01";
  require(::write(descriptors[1], partial, sizeof(partial) - 1) == 8, "partial header write failed");
  ::close(descriptors[1]);
  refuses([&]() { (void)vast::study::detail::read_transport_frame(descriptors[0], actual, io, 1); },
          "partial 80-byte transport header became a clean prefix EOF");
  ::close(descriptors[0]); require(fd_count() == before, "partial header fixture leaked FD");
}

int raw_cli(const std::string& output, bool partial, bool silent) {
  const int before = fd_count();
  int descriptors[2]; require(::pipe(descriptors) == 0, "real NV12 stdin pipe unavailable");
  const int original_stdin = ::dup(STDIN_FILENO);
  require(original_stdin >= 0 && ::dup2(descriptors[0], STDIN_FILENO) >= 0, "stdin ownership setup failed");
  ::close(descriptors[0]);
  const auto deadline = vast::CheckpointIoDeadline::monotonic_now_ns() +
                        (silent ? 200000000ULL : 3000000000ULL);
  vast::CheckpointIoDeadline writer_io(deadline);
  std::mutex release_mutex; std::condition_variable release_gate; bool release = false;
  std::exception_ptr writer_error;
  std::thread writer([&]() {
    try {
      std::vector<std::uint8_t> pixels(48, 128); std::fill(pixels.begin(), pixels.begin() + 32, 16);
      const int frames = partial || silent ? 1 : 442;
      vast::CheckpointIoDeadline::set_owned_nonblocking(descriptors[1]);
      for (int index = 0; index < frames; ++index) {
        std::size_t position = 0;
        while (position < pixels.size()) {
          writer_io.check(); const auto written = ::write(descriptors[1], pixels.data() + position, pixels.size() - position);
          if (written < 0 && errno == EINTR) continue;
          if (written < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
            writer_io.wait(descriptors[1], POLLOUT); continue;
          }
          if (written <= 0) throw std::runtime_error("fixture NV12 pipe write failed");
          position += static_cast<std::size_t>(written);
        }
      }
      if (partial) require(::write(descriptors[1], "abc", 3) == 3, "partial frame fixture failed");
      if (silent) {
        std::unique_lock<std::mutex> lock(release_mutex);
        require(release_gate.wait_for(lock, std::chrono::seconds(2), [&]() { return release; }),
                "silent peer safety gate expired before observed original deadline");
      }
    } catch (...) { writer_error = std::current_exception(); }
    ::close(descriptors[1]);
  });
  std::vector<std::string> text{"unit", "--checkpoint-study-reference-nv12", output, "8", "4", std::to_string(deadline), "442"};
  std::vector<char*> argv; for (auto& value : text) argv.push_back(value.data());
  bool handled = false;
  const int result = vast::study::dispatch_reference_cli(static_cast<int>(argv.size()), argv.data(), handled);
  const bool stdin_still_held = ::fcntl(STDIN_FILENO, F_GETFD) >= 0;
  { std::lock_guard<std::mutex> lock(release_mutex); release = true; }
  release_gate.notify_all(); writer.join();
  require(::dup2(original_stdin, STDIN_FILENO) >= 0, "stdin restoration failed"); ::close(original_stdin);
  if (writer_error) std::rethrow_exception(writer_error);
  require(handled && stdin_still_held && fd_count() == before, "CLI did not retire its input/output/thread ownership");
  return result;
}

void actual_software_reference(const std::string& directory) {
  const std::string full = directory + "/full.jsonl";
  require(raw_cli(full, false, false) == 0, "real software NV12/common-converter/full442 EOS failed");
  const auto body = read_file(full);
  const auto black = sha(std::vector<std::uint8_t>(96, 0));
  std::size_t frames = 0, cursor = 0;
  while ((cursor = body.find("\"type\":\"frame\"", cursor)) != std::string::npos) { ++frames; ++cursor; }
  std::size_t exact_rgb = 0; cursor = 0;
  while ((cursor = body.find("\"rgb_sha256\":\"" + black + "\"", cursor)) != std::string::npos) { ++exact_rgb; ++cursor; }
  require(frames == 442 && exact_rgb == 442 &&
          body.find("\"completion_kind\":\"independent_nv12_full_eos\"") != std::string::npos &&
          body.find("\"success\":true") != std::string::npos,
          "software converter colour/hash/EOS report does not describe actual frames");
  require(raw_cli(directory + "/partial.jsonl", true, false) != 0,
          "short real stdin body promoted to full reference EOS");
  require(raw_cli(directory + "/silent.jsonl", false, true) != 0,
          "silent live stdin ignored the original absolute clock");
  require(read_file(directory + "/partial.jsonl").find("\"success\":true") == std::string::npos &&
          read_file(directory + "/silent.jsonl").find("\"success\":true") == std::string::npos,
          "failed reference prefix contains fabricated successful completion");
}
}  // namespace

int main() {
  gst_init(nullptr, nullptr);
  char pattern[] = "/tmp/vast-study-reference-unit-XXXXXX";
  const char* created = ::mkdtemp(pattern);
  if (!created) return 2;
  const std::string directory(created);
  int result = 0;
  try {
    actual_clock_domain_guard(directory); std::cout << "study-reference actual clock-domain proof PASS\n";
    actual_caps_and_strides(); std::cout << "study-reference active-strides/caps PASS\n";
    actual_transport_eof(); std::cout << "study-reference wire80/partial/EOF PASS (no decoder claim)\n";
    actual_software_reference(directory); std::cout << "study-reference real-software-NV12/RGB/EOS/short/deadline PASS\n";
  } catch (const std::exception& error) { std::cerr << error.what() << '\n'; result = 1; }
  for (const char* name : {"full.jsonl", "partial.jsonl", "silent.jsonl"}) ::unlink((directory + "/" + name).c_str());
  ::rmdir(directory.c_str());
  return result;
}
