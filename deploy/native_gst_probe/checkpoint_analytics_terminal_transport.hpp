#pragma once

#include <array>
#include <cerrno>
#include <cstdint>
#include <cstdlib>
#include <stdexcept>
#include <string>
#include <vector>

#include <sys/socket.h>
#include <unistd.h>

namespace vast {

enum class CheckpointAnalyticsTerminalStatus : std::uint8_t {
  kCompleted = 1,
  kDrop = 2,
};

struct CheckpointAnalyticsTerminal {
  std::uint64_t transport_pts_ns = 0;
  CheckpointAnalyticsTerminalStatus status = CheckpointAnalyticsTerminalStatus::kCompleted;
  std::uint64_t objects = 0;
  std::string branch_id;
  std::string terminal_reason;
  std::string detector;
  std::string backend;
};

class CheckpointAnalyticsTerminalTransport {
 public:
  static constexpr const char* kFdEnvironment = "VAST_CHECKPOINT_ANALYTICS_TERMINAL_FD";
  static constexpr std::uint32_t kMagic = 0x5641544d;
  static constexpr std::uint16_t kVersion = 1;
  static constexpr std::size_t kMaximumDatagramBytes = 4096;

  static std::vector<std::uint8_t> encode(const CheckpointAnalyticsTerminal& terminal) {
    validate(terminal);
    std::vector<std::uint8_t> payload;
    payload.reserve(32 + terminal.branch_id.size() + terminal.terminal_reason.size() +
                    terminal.detector.size() + terminal.backend.size());
    append_u32(payload, kMagic);
    append_u16(payload, kVersion);
    payload.push_back(static_cast<std::uint8_t>(terminal.status));
    payload.push_back(0);
    append_u64(payload, terminal.transport_pts_ns);
    append_u64(payload, terminal.objects);
    append_u16(payload, length(terminal.branch_id, "branch_id"));
    append_u16(payload, length(terminal.terminal_reason, "terminal_reason"));
    append_u16(payload, length(terminal.detector, "detector"));
    append_u16(payload, length(terminal.backend, "backend"));
    append_text(payload, terminal.branch_id);
    append_text(payload, terminal.terminal_reason);
    append_text(payload, terminal.detector);
    append_text(payload, terminal.backend);
    if (payload.size() > kMaximumDatagramBytes) {
      throw std::runtime_error("checkpoint analytics terminal datagram is too large");
    }
    return payload;
  }

  static CheckpointAnalyticsTerminal decode(const std::uint8_t* data, std::size_t size) {
    if (data == nullptr || size < 32 || size > kMaximumDatagramBytes) {
      throw std::runtime_error("checkpoint analytics terminal datagram has an invalid size");
    }
    std::size_t offset = 0;
    if (read_u32(data, size, offset) != kMagic) {
      throw std::runtime_error("checkpoint analytics terminal magic mismatch");
    }
    if (read_u16(data, size, offset) != kVersion) {
      throw std::runtime_error("unsupported checkpoint analytics terminal protocol version");
    }
    const std::uint8_t status_raw = read_u8(data, size, offset);
    if (read_u8(data, size, offset) != 0) {
      throw std::runtime_error("checkpoint analytics terminal reserved field must be zero");
    }
    CheckpointAnalyticsTerminal terminal;
    if (status_raw == static_cast<std::uint8_t>(CheckpointAnalyticsTerminalStatus::kCompleted)) {
      terminal.status = CheckpointAnalyticsTerminalStatus::kCompleted;
    } else if (status_raw == static_cast<std::uint8_t>(CheckpointAnalyticsTerminalStatus::kDrop)) {
      terminal.status = CheckpointAnalyticsTerminalStatus::kDrop;
    } else {
      throw std::runtime_error("checkpoint analytics terminal status is invalid");
    }
    terminal.transport_pts_ns = read_u64(data, size, offset);
    terminal.objects = read_u64(data, size, offset);
    const std::array<std::uint16_t, 4> lengths = {
        read_u16(data, size, offset),
        read_u16(data, size, offset),
        read_u16(data, size, offset),
        read_u16(data, size, offset),
    };
    terminal.branch_id = read_text(data, size, offset, lengths[0]);
    terminal.terminal_reason = read_text(data, size, offset, lengths[1]);
    terminal.detector = read_text(data, size, offset, lengths[2]);
    terminal.backend = read_text(data, size, offset, lengths[3]);
    if (offset != size) {
      throw std::runtime_error("checkpoint analytics terminal datagram has trailing bytes");
    }
    validate(terminal);
    return terminal;
  }

  static CheckpointAnalyticsTerminal receive(int fd) {
    std::array<std::uint8_t, kMaximumDatagramBytes> buffer{};
    ssize_t received = -1;
    do {
      received = ::recv(fd, buffer.data(), buffer.size(), MSG_TRUNC);
    } while (received < 0 && errno == EINTR);
    if (received < 0) {
      throw std::runtime_error("failed to receive checkpoint analytics terminal datagram");
    }
    if (static_cast<std::size_t>(received) > buffer.size()) {
      throw std::runtime_error("checkpoint analytics terminal datagram was truncated");
    }
    return decode(buffer.data(), static_cast<std::size_t>(received));
  }

  static void send(int fd, const CheckpointAnalyticsTerminal& terminal) {
    const std::vector<std::uint8_t> payload = encode(terminal);
    ssize_t written = -1;
    do {
      written = ::send(fd, payload.data(), payload.size(), 0);
    } while (written < 0 && errno == EINTR);
    if (written < 0 || static_cast<std::size_t>(written) != payload.size()) {
      throw std::runtime_error("failed to send checkpoint analytics terminal datagram");
    }
  }

 private:
  static void validate(const CheckpointAnalyticsTerminal& terminal) {
    if (!valid_branch(terminal.branch_id)) {
      throw std::runtime_error("checkpoint analytics terminal branch_id is invalid");
    }
    validate_text(terminal.terminal_reason, "terminal_reason", 512);
    validate_text(terminal.detector, "detector", 256);
    validate_text(terminal.backend, "backend", 256);
    if (terminal.detector == "identity" || terminal.backend == "identity" ||
        terminal.detector == "topology_only" || terminal.backend == "topology_only") {
      throw std::runtime_error("checkpoint analytics terminal cannot claim an identity-only adapter");
    }
    if (terminal.status == CheckpointAnalyticsTerminalStatus::kDrop && terminal.objects != 0) {
      throw std::runtime_error("checkpoint analytics drop must not report accepted objects");
    }
  }

  static bool valid_branch(const std::string& value) {
    if (value.empty() || value.size() > 128) {
      return false;
    }
    for (const char ch : value) {
      const bool valid = (ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9') ||
                         ch == '_' || ch == '-' || ch == '.';
      if (!valid) {
        return false;
      }
    }
    return true;
  }

  static void validate_text(const std::string& value, const char* name, std::size_t maximum) {
    if (value.empty() || value.size() > maximum) {
      throw std::runtime_error(std::string("checkpoint analytics terminal ") + name + " has an invalid length");
    }
    for (const unsigned char ch : value) {
      if (ch < 0x20 || ch == 0x7f) {
        throw std::runtime_error(std::string("checkpoint analytics terminal ") + name + " contains controls");
      }
    }
  }

  static std::uint16_t length(const std::string& value, const char* name) {
    if (value.size() > 0xffff) {
      throw std::runtime_error(std::string("checkpoint analytics terminal ") + name + " is too long");
    }
    return static_cast<std::uint16_t>(value.size());
  }

  static void append_text(std::vector<std::uint8_t>& target, const std::string& value) {
    target.insert(target.end(), value.begin(), value.end());
  }

  static void append_u16(std::vector<std::uint8_t>& target, std::uint16_t value) {
    target.push_back(static_cast<std::uint8_t>((value >> 8) & 0xff));
    target.push_back(static_cast<std::uint8_t>(value & 0xff));
  }

  static void append_u32(std::vector<std::uint8_t>& target, std::uint32_t value) {
    for (int shift = 24; shift >= 0; shift -= 8) {
      target.push_back(static_cast<std::uint8_t>((value >> shift) & 0xff));
    }
  }

  static void append_u64(std::vector<std::uint8_t>& target, std::uint64_t value) {
    for (int shift = 56; shift >= 0; shift -= 8) {
      target.push_back(static_cast<std::uint8_t>((value >> shift) & 0xff));
    }
  }

  static std::uint8_t read_u8(const std::uint8_t* data, std::size_t size, std::size_t& offset) {
    if (offset >= size) {
      throw std::runtime_error("checkpoint analytics terminal datagram is truncated");
    }
    return data[offset++];
  }

  static std::uint16_t read_u16(const std::uint8_t* data, std::size_t size, std::size_t& offset) {
    const std::uint16_t high = read_u8(data, size, offset);
    const std::uint16_t low = read_u8(data, size, offset);
    return static_cast<std::uint16_t>((high << 8) | low);
  }

  static std::uint32_t read_u32(const std::uint8_t* data, std::size_t size, std::size_t& offset) {
    std::uint32_t value = 0;
    for (int index = 0; index < 4; ++index) {
      value = static_cast<std::uint32_t>((value << 8) | read_u8(data, size, offset));
    }
    return value;
  }

  static std::uint64_t read_u64(const std::uint8_t* data, std::size_t size, std::size_t& offset) {
    std::uint64_t value = 0;
    for (int index = 0; index < 8; ++index) {
      value = static_cast<std::uint64_t>((value << 8) | read_u8(data, size, offset));
    }
    return value;
  }

  static std::string read_text(
      const std::uint8_t* data,
      std::size_t size,
      std::size_t& offset,
      std::uint16_t length) {
    if (offset + length > size) {
      throw std::runtime_error("checkpoint analytics terminal string is truncated");
    }
    const char* begin = reinterpret_cast<const char*>(data + offset);
    std::string value(begin, begin + length);
    offset += length;
    return value;
  }
};

class CheckpointAnalyticsTerminalEmitter {
 public:
  static CheckpointAnalyticsTerminalEmitter from_environment() {
    const char* raw = std::getenv(CheckpointAnalyticsTerminalTransport::kFdEnvironment);
    if (raw == nullptr || std::string(raw).empty()) {
      throw std::runtime_error("missing VAST_CHECKPOINT_ANALYTICS_TERMINAL_FD");
    }
    std::size_t consumed = 0;
    int fd = -1;
    try {
      fd = std::stoi(raw, &consumed);
    } catch (const std::exception&) {
      throw std::runtime_error("invalid VAST_CHECKPOINT_ANALYTICS_TERMINAL_FD");
    }
    if (consumed != std::string(raw).size() || fd < 0) {
      throw std::runtime_error("invalid VAST_CHECKPOINT_ANALYTICS_TERMINAL_FD");
    }
    return CheckpointAnalyticsTerminalEmitter(fd);
  }

  explicit CheckpointAnalyticsTerminalEmitter(int fd) : fd_(fd) {
    if (fd_ < 0) {
      throw std::runtime_error("checkpoint analytics terminal FD must be non-negative");
    }
  }

  void emit(const CheckpointAnalyticsTerminal& terminal) const {
    CheckpointAnalyticsTerminalTransport::send(fd_, terminal);
  }

 private:
  int fd_ = -1;
};

}  // namespace vast
