#pragma once

#include <algorithm>
#include <array>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <cstdint>
#include <fcntl.h>
#include <limits>
#include <mutex>
#include <poll.h>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <unistd.h>

namespace vast {

// One owned lifecycle bound, shared by its callbacks and transports. Realtime
// START/drain and per-request monotonic endpoints are checked in their own
// domains; neither a readiness wakeup nor partial progress renews either bound.
class CheckpointIoDeadline {
 public:
  explicit CheckpointIoDeadline(std::uint64_t monotonic_deadline_ns = 0)
      : monotonic_deadline_ns_(monotonic_deadline_ns) {}

  static std::uint64_t monotonic_now_ns() {
    return static_cast<std::uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count());
  }

  static std::uint64_t realtime_now_ns() {
    return static_cast<std::uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count());
  }

  void bind_original_drain_end_ms(std::uint64_t end_ms) {
    if (end_ms == 0 || end_ms > UINT64_MAX / 1'000'000ULL) {
      throw std::runtime_error("checkpoint original drain deadline is invalid");
    }
    const std::uint64_t value = end_ms * 1'000'000ULL;
    std::uint64_t expected = 0;
    if (!realtime_deadline_ns_.compare_exchange_strong(expected, value) && expected != value) {
      throw std::runtime_error("checkpoint original drain deadline cannot be rebound");
    }
  }

  void abort() noexcept { aborted_.store(true); }
  bool aborted() const noexcept { return aborted_.load(); }

  void check(std::uint64_t request_deadline_ns = 0) const {
    check_original_deadline(request_deadline_ns);
    if (aborted_.load()) throw std::runtime_error("checkpoint I/O owner aborted");
  }

  // Retirement may persist/close journals after callback cancellation, but
  // still uses the very same original endpoint; abort grants no extra time.
  void check_original_deadline(std::uint64_t request_deadline_ns = 0) const {
    const auto mono = monotonic_now_ns();
    if ((request_deadline_ns != 0 && mono >= request_deadline_ns) ||
        (monotonic_deadline_ns_ != 0 && mono >= monotonic_deadline_ns_) ||
        (realtime_deadline_ns_.load() != 0 && realtime_now_ns() >= realtime_deadline_ns_.load())) {
      throw std::runtime_error("checkpoint I/O original deadline exceeded");
    }
  }

  std::unique_lock<std::timed_mutex> acquire(
      std::timed_mutex& mutex, std::uint64_t request_deadline_ns = 0) const {
    std::unique_lock<std::timed_mutex> lock(mutex, std::defer_lock);
    do {
      check(request_deadline_ns);
    } while (!lock.try_lock_for(std::chrono::milliseconds(remaining_poll_ms(request_deadline_ns))));
    check(request_deadline_ns);
    return lock;
  }

  void wait(int fd, short events, std::uint64_t request_deadline_ns = 0) const {
    while (true) {
      check(request_deadline_ns);
      pollfd descriptor{fd, events, 0};
      const int result = ::poll(&descriptor, 1, remaining_poll_ms(request_deadline_ns));
      if (result < 0 && errno == EINTR) continue;
      if (result < 0) throw std::runtime_error("checkpoint I/O readiness poll failed");
      if (result == 0) continue;
      check(request_deadline_ns);
      if ((descriptor.revents & POLLNVAL) != 0) {
        throw std::runtime_error("checkpoint I/O descriptor became invalid before retirement");
      }
      // HUP/ERR still permit the next nonblocking syscall to observe buffered
      // bytes or the genuine EOF/error. They are never fabricated progress.
      if ((descriptor.revents & (events | POLLHUP | POLLERR)) != 0) return;
    }
  }

  static void set_owned_nonblocking(int fd) {
    const int flags = ::fcntl(fd, F_GETFL);
    if (flags < 0 || ::fcntl(fd, F_SETFL, flags | O_NONBLOCK) != 0) {
      throw std::runtime_error("failed to make owned checkpoint I/O nonblocking");
    }
  }

 private:
  std::atomic<bool> aborted_{false};
  std::atomic<std::uint64_t> realtime_deadline_ns_{0};
  const std::uint64_t monotonic_deadline_ns_;

  int remaining_poll_ms(std::uint64_t request_deadline_ns) const {
    check(request_deadline_ns);
    std::uint64_t remaining = 10'000'000ULL;
    const auto reduce = [&](std::uint64_t end, std::uint64_t now) {
      if (end != 0) remaining = std::min(remaining, end > now ? end - now : 0);
    };
    const auto mono = monotonic_now_ns();
    reduce(request_deadline_ns, mono);
    reduce(monotonic_deadline_ns_, mono);
    reduce(realtime_deadline_ns_.load(), realtime_now_ns());
    if (remaining == 0) throw std::runtime_error("checkpoint I/O original deadline exceeded");
    return static_cast<int>((remaining + 999'999ULL) / 1'000'000ULL);
  }
};

struct CheckpointAdmissionFrame {
  std::uint64_t sequence = 0;
  bool keyframe = false;
  std::uint64_t source_cycle = 0;
  std::uint64_t access_unit_pts_ns = 0;
  std::uint64_t transport_pts_ns = 0;
  std::uint64_t access_unit_dts_ns = std::numeric_limits<std::uint64_t>::max();
  std::uint64_t duration_ns = 0;
  // Local observation only; the original 80-byte transport protocol is unchanged.
  std::uint64_t source_schedule_offset_ns = 0;
  std::string admission_id;
  std::string input_frame_key;
  std::string payload_sha256;
  std::vector<std::uint8_t> payload;
};

class CheckpointAdmissionTransport {
 public:
  static constexpr std::uint16_t kProtocolVersion = 1;
  static constexpr std::uint16_t kFlagKeyframe = 1U << 0;
  static constexpr std::uint16_t kKnownFlags = kFlagKeyframe;
  static constexpr std::uint64_t kMissingTimestamp = std::numeric_limits<std::uint64_t>::max();
  static constexpr std::size_t kMaximumTextBytes = 8192;
  static constexpr std::size_t kMaximumPayloadBytes = 64U * 1024U * 1024U;

  static void write_frame(int fd, const CheckpointAdmissionFrame& frame,
                          const CheckpointIoDeadline* io = nullptr) {
    if (io != nullptr) CheckpointIoDeadline::set_owned_nonblocking(fd);
    validate(frame);
    std::array<std::uint8_t, kFixedHeaderBytes> header{};
    std::copy(kMagic.begin(), kMagic.end(), header.begin());
    write_u16(header.data() + 8, kProtocolVersion);
    write_u16(header.data() + 10, frame.keyframe ? kFlagKeyframe : 0);
    write_u64(header.data() + 12, frame.sequence);
    write_u64(header.data() + 20, frame.source_cycle);
    write_u64(header.data() + 28, frame.access_unit_pts_ns);
    write_u64(header.data() + 36, frame.transport_pts_ns);
    write_u64(header.data() + 44, frame.access_unit_dts_ns);
    write_u64(header.data() + 52, frame.duration_ns);
    write_u32(header.data() + 60, checked_size(frame.admission_id.size(), "admission_id"));
    write_u32(header.data() + 64, checked_size(frame.input_frame_key.size(), "input_frame_key"));
    write_u32(header.data() + 68, checked_size(frame.payload_sha256.size(), "payload_sha256"));
    write_u64(header.data() + 72, frame.payload.size());

    write_exact(fd, header.data(), header.size(), io);
    write_exact(fd, frame.admission_id.data(), frame.admission_id.size(), io);
    write_exact(fd, frame.input_frame_key.data(), frame.input_frame_key.size(), io);
    write_exact(fd, frame.payload_sha256.data(), frame.payload_sha256.size(), io);
    write_exact(fd, frame.payload.data(), frame.payload.size(), io);
  }

  // Returns false only for a clean EOF before the next frame starts.
  static bool read_frame(int fd, CheckpointAdmissionFrame& frame,
                         const CheckpointIoDeadline* io = nullptr,
                         std::size_t maximum_payload_bytes = kMaximumPayloadBytes) {
    if (maximum_payload_bytes == 0 || maximum_payload_bytes > kMaximumPayloadBytes) {
      throw std::runtime_error("checkpoint caller payload size cap is invalid");
    }
    if (io != nullptr) CheckpointIoDeadline::set_owned_nonblocking(fd);
    std::array<std::uint8_t, kFixedHeaderBytes> header{};
    if (!read_exact(fd, header.data(), header.size(), true, io)) {
      return false;
    }
    if (!std::equal(kMagic.begin(), kMagic.end(), header.begin())) {
      throw std::runtime_error("checkpoint admission frame has invalid magic");
    }
    const std::uint16_t flags = read_u16(header.data() + 10);
    if (read_u16(header.data() + 8) != kProtocolVersion || (flags & ~kKnownFlags) != 0) {
      throw std::runtime_error("unsupported checkpoint admission transport protocol");
    }

    const std::size_t admission_size = checked_text_size(read_u32(header.data() + 60), "admission_id");
    const std::size_t key_size = checked_text_size(read_u32(header.data() + 64), "input_frame_key");
    const std::size_t digest_size = checked_text_size(read_u32(header.data() + 68), "payload_sha256");
    const std::uint64_t payload_size = read_u64(header.data() + 72);
    if (payload_size == 0 || payload_size > maximum_payload_bytes) {
      throw std::runtime_error("checkpoint admission payload size is out of range");
    }

    CheckpointAdmissionFrame decoded;
    decoded.keyframe = (flags & kFlagKeyframe) != 0;
    decoded.sequence = read_u64(header.data() + 12);
    decoded.source_cycle = read_u64(header.data() + 20);
    decoded.access_unit_pts_ns = read_u64(header.data() + 28);
    decoded.transport_pts_ns = read_u64(header.data() + 36);
    decoded.access_unit_dts_ns = read_u64(header.data() + 44);
    decoded.duration_ns = read_u64(header.data() + 52);
    decoded.admission_id.resize(admission_size);
    decoded.input_frame_key.resize(key_size);
    decoded.payload_sha256.resize(digest_size);
    decoded.payload.resize(static_cast<std::size_t>(payload_size));
    read_exact(fd, decoded.admission_id.data(), decoded.admission_id.size(), false, io);
    read_exact(fd, decoded.input_frame_key.data(), decoded.input_frame_key.size(), false, io);
    read_exact(fd, decoded.payload_sha256.data(), decoded.payload_sha256.size(), false, io);
    read_exact(fd, decoded.payload.data(), decoded.payload.size(), false, io);
    validate(decoded);
    frame = std::move(decoded);
    return true;
  }

 private:
  inline static constexpr std::array<std::uint8_t, 8> kMagic = {
      'V', 'A', 'S', 'T', 'A', 'U', '0', '1'};
  static constexpr std::size_t kFixedHeaderBytes = 80;

  static void validate(const CheckpointAdmissionFrame& frame) {
    if (frame.sequence == 0) {
      throw std::runtime_error("checkpoint admission frame sequence must be positive");
    }
    if (frame.transport_pts_ns < frame.access_unit_pts_ns) {
      throw std::runtime_error("checkpoint transport PTS cannot precede native access-unit PTS");
    }
    require_text(frame.admission_id, "admission_id");
    require_text(frame.input_frame_key, "input_frame_key");
    if (frame.payload_sha256.size() != 64 ||
        !std::all_of(frame.payload_sha256.begin(), frame.payload_sha256.end(), [](unsigned char value) {
          return (value >= '0' && value <= '9') || (value >= 'a' && value <= 'f');
        })) {
      throw std::runtime_error("checkpoint admission payload SHA-256 must be lowercase hexadecimal");
    }
    if (frame.payload.empty() || frame.payload.size() > kMaximumPayloadBytes) {
      throw std::runtime_error("checkpoint admission payload size is out of range");
    }
  }

  static void require_text(const std::string& value, const char* name) {
    if (value.empty() || value.size() > kMaximumTextBytes ||
        std::any_of(value.begin(), value.end(), [](unsigned char character) {
          return character <= 0x20 || character == 0x7f;
        })) {
      throw std::runtime_error(std::string("invalid checkpoint admission text field: ") + name);
    }
  }

  static std::uint32_t checked_size(std::size_t value, const char* name) {
    if (value > kMaximumTextBytes || value > std::numeric_limits<std::uint32_t>::max()) {
      throw std::runtime_error(std::string("checkpoint admission text field is too long: ") + name);
    }
    return static_cast<std::uint32_t>(value);
  }

  static std::size_t checked_text_size(std::uint32_t value, const char* name) {
    if (value == 0 || value > kMaximumTextBytes) {
      throw std::runtime_error(std::string("checkpoint admission text size is out of range: ") + name);
    }
    return static_cast<std::size_t>(value);
  }

  static void write_u16(std::uint8_t* output, std::uint16_t value) {
    output[0] = static_cast<std::uint8_t>((value >> 8) & 0xff);
    output[1] = static_cast<std::uint8_t>(value & 0xff);
  }

  static void write_u32(std::uint8_t* output, std::uint32_t value) {
    for (int shift = 24, index = 0; shift >= 0; shift -= 8, ++index) {
      output[index] = static_cast<std::uint8_t>((value >> shift) & 0xff);
    }
  }

  static void write_u64(std::uint8_t* output, std::uint64_t value) {
    for (int shift = 56, index = 0; shift >= 0; shift -= 8, ++index) {
      output[index] = static_cast<std::uint8_t>((value >> shift) & 0xff);
    }
  }

  static std::uint16_t read_u16(const std::uint8_t* input) {
    return static_cast<std::uint16_t>((static_cast<std::uint16_t>(input[0]) << 8) | input[1]);
  }

  static std::uint32_t read_u32(const std::uint8_t* input) {
    std::uint32_t value = 0;
    for (int index = 0; index < 4; ++index) {
      value = (value << 8) | input[index];
    }
    return value;
  }

  static std::uint64_t read_u64(const std::uint8_t* input) {
    std::uint64_t value = 0;
    for (int index = 0; index < 8; ++index) {
      value = (value << 8) | input[index];
    }
    return value;
  }

  static void write_exact(int fd, const void* data, std::size_t size,
                          const CheckpointIoDeadline* io) {
    const auto* bytes = static_cast<const std::uint8_t*>(data);
    std::size_t offset = 0;
    while (offset < size) {
      if (io != nullptr) io->check();
      const ssize_t written = ::write(fd, bytes + offset, size - offset);
      if (written < 0 && errno == EINTR) {
        continue;
      }
      if (written < 0 && (errno == EAGAIN || errno == EWOULDBLOCK) && io != nullptr) {
        io->wait(fd, POLLOUT);
        continue;
      }
      if (written <= 0) {
        throw std::runtime_error("failed to write checkpoint admission frame");
      }
      offset += static_cast<std::size_t>(written);
    }
  }

  static bool read_exact(int fd, void* data, std::size_t size, bool clean_eof_allowed,
                         const CheckpointIoDeadline* io) {
    auto* bytes = static_cast<std::uint8_t*>(data);
    std::size_t offset = 0;
    while (offset < size) {
      if (io != nullptr) io->check();
      const ssize_t count = ::read(fd, bytes + offset, size - offset);
      if (count < 0 && errno == EINTR) {
        continue;
      }
      if (count < 0 && (errno == EAGAIN || errno == EWOULDBLOCK) && io != nullptr) {
        io->wait(fd, POLLIN);
        continue;
      }
      if (count == 0 && offset == 0 && clean_eof_allowed) {
        return false;
      }
      if (count <= 0) {
        throw std::runtime_error("truncated checkpoint admission frame");
      }
      offset += static_cast<std::size_t>(count);
    }
    return true;
  }
};

}  // namespace vast
