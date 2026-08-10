#include "checkpoint_admission_transport.hpp"

#include <unistd.h>

#include <array>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

vast::CheckpointAdmissionFrame sample_frame() {
  vast::CheckpointAdmissionFrame frame;
  frame.sequence = 7;
  frame.source_cycle = 2;
  frame.access_unit_pts_ns = 90'000;
  frame.transport_pts_ns = 20'000'090'000;
  frame.access_unit_dts_ns = 80'000;
  frame.duration_ns = 33'333'333;
  frame.admission_id = "run-1:3:admission:7";
  frame.input_frame_key = "dataset:3:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:2:90000";
  frame.payload_sha256 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
  frame.payload = {0x00, 0x00, 0x01, 0x65, 0x0a, 0x00, 0xff};
  return frame;
}

bool same(const vast::CheckpointAdmissionFrame& left, const vast::CheckpointAdmissionFrame& right) {
  return left.sequence == right.sequence && left.source_cycle == right.source_cycle &&
         left.access_unit_pts_ns == right.access_unit_pts_ns &&
         left.transport_pts_ns == right.transport_pts_ns &&
         left.access_unit_dts_ns == right.access_unit_dts_ns && left.duration_ns == right.duration_ns &&
         left.admission_id == right.admission_id && left.input_frame_key == right.input_frame_key &&
         left.payload_sha256 == right.payload_sha256 && left.payload == right.payload;
}

}  // namespace

int main() {
  std::array<int, 2> pipe_fds{};
  if (::pipe(pipe_fds.data()) != 0) {
    return 2;
  }
  const auto expected = sample_frame();
  vast::CheckpointAdmissionTransport::write_frame(pipe_fds[1], expected);
  ::close(pipe_fds[1]);

  vast::CheckpointAdmissionFrame observed;
  if (!vast::CheckpointAdmissionTransport::read_frame(pipe_fds[0], observed) || !same(expected, observed)) {
    return 3;
  }
  if (vast::CheckpointAdmissionTransport::read_frame(pipe_fds[0], observed)) {
    return 4;
  }
  ::close(pipe_fds[0]);

  std::array<int, 2> truncated{};
  if (::pipe(truncated.data()) != 0) {
    return 5;
  }
  const std::array<std::uint8_t, 4> prefix = {'V', 'A', 'S', 'T'};
  if (::write(truncated[1], prefix.data(), prefix.size()) != static_cast<ssize_t>(prefix.size())) {
    return 6;
  }
  ::close(truncated[1]);
  bool rejected = false;
  try {
    vast::CheckpointAdmissionTransport::read_frame(truncated[0], observed);
  } catch (const std::runtime_error&) {
    rejected = true;
  }
  ::close(truncated[0]);
  if (!rejected) {
    return 7;
  }

  auto invalid = sample_frame();
  invalid.payload_sha256 = "not-a-digest";
  std::array<int, 2> invalid_pipe{};
  if (::pipe(invalid_pipe.data()) != 0) {
    return 8;
  }
  rejected = false;
  try {
    vast::CheckpointAdmissionTransport::write_frame(invalid_pipe[1], invalid);
  } catch (const std::runtime_error&) {
    rejected = true;
  }
  ::close(invalid_pipe[0]);
  ::close(invalid_pipe[1]);
  return rejected ? 0 : 9;
}
