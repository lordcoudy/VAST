#pragma once

#include <algorithm>
#include <array>
#include <cerrno>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <unistd.h>

namespace vast {

struct CheckpointAdmissionFrame {
  std::uint64_t sequence = 0;
  std::uint64_t source_cycle = 0;
  std::uint64_t access_unit_pts_ns = 0;
  std::uint64_t transport_pts_ns = 0;
  std::uint64_t access_unit_dts_ns = std::numeric_limits<std::uint64_t>::max();
  std::uint64_t duration_ns = 0;
  std::string admission_id;
  std::string input_frame_key;
  std::string payload_sha256;
  std::vector<std::uint8_t> payload;
};

class CheckpointAdmissionTransport {
 public:
  static constexpr std::uint16_t kProtocolVersion = 1;
  static constexpr std::uint64_t kMissingTimestamp = std::numeric_limits<std::uint64_t>::max();
  static constexpr std::size_t kMaximumTextBytes = 8192;
  static constexpr std::size_t kMaximumPayloadBytes = 64U * 1024U * 1024U;

  static void write_frame(int fd, const CheckpointAdmissionFrame& frame) {
    validate(frame);
    std::array<std::uint8_t, kFixedHeaderBytes> header{};
    std::copy(kMagic.begin(), kMagic.end(), header.begin());
    write_u16(header.data() + 8, kProtocolVersion);
    write_u16(header.data() + 10, 0);
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

    write_exact(fd, header.data(), header.size());
    write_exact(fd, frame.admission_id.data(), frame.admission_id.size());
    write_exact(fd, frame.input_frame_key.data(), frame.input_frame_key.size());
    write_exact(fd, frame.payload_sha256.data(), frame.payload_sha256.size());
    write_exact(fd, frame.payload.data(), frame.payload.size());
  }

  // Returns false only for a clean EOF before the next frame starts.
  static bool read_frame(int fd, CheckpointAdmissionFrame& frame) {
    std::array<std::uint8_t, kFixedHeaderBytes> header{};
    if (!read_exact(fd, header.data(), header.size(), true)) {
      return false;
    }
    if (!std::equal(kMagic.begin(), kMagic.end(), header.begin())) {
      throw std::runtime_error("checkpoint admission frame has invalid magic");
    }
    if (read_u16(header.data() + 8) != kProtocolVersion || read_u16(header.data() + 10) != 0) {
      throw std::runtime_error("unsupported checkpoint admission transport protocol");
    }

    const std::size_t admission_size = checked_text_size(read_u32(header.data() + 60), "admission_id");
    const std::size_t key_size = checked_text_size(read_u32(header.data() + 64), "input_frame_key");
    const std::size_t digest_size = checked_text_size(read_u32(header.data() + 68), "payload_sha256");
    const std::uint64_t payload_size = read_u64(header.data() + 72);
    if (payload_size == 0 || payload_size > kMaximumPayloadBytes) {
      throw std::runtime_error("checkpoint admission payload size is out of range");
    }

    CheckpointAdmissionFrame decoded;
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
    read_exact(fd, decoded.admission_id.data(), decoded.admission_id.size(), false);
    read_exact(fd, decoded.input_frame_key.data(), decoded.input_frame_key.size(), false);
    read_exact(fd, decoded.payload_sha256.data(), decoded.payload_sha256.size(), false);
    read_exact(fd, decoded.payload.data(), decoded.payload.size(), false);
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

  static void write_exact(int fd, const void* data, std::size_t size) {
    const auto* bytes = static_cast<const std::uint8_t*>(data);
    std::size_t offset = 0;
    while (offset < size) {
      const ssize_t written = ::write(fd, bytes + offset, size - offset);
      if (written < 0 && errno == EINTR) {
        continue;
      }
      if (written <= 0) {
        throw std::runtime_error("failed to write checkpoint admission frame");
      }
      offset += static_cast<std::size_t>(written);
    }
  }

  static bool read_exact(int fd, void* data, std::size_t size, bool clean_eof_allowed) {
    auto* bytes = static_cast<std::uint8_t*>(data);
    std::size_t offset = 0;
    while (offset < size) {
      const ssize_t count = ::read(fd, bytes + offset, size - offset);
      if (count < 0 && errno == EINTR) {
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
