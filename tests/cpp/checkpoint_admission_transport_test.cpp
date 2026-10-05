#include "checkpoint_admission_transport.hpp"

#include <unistd.h>

#include <array>
#include <chrono>
#include <condition_variable>
#include <dirent.h>
#include <iostream>
#include <mutex>
#include <thread>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

vast::CheckpointAdmissionFrame sample_frame() {
  vast::CheckpointAdmissionFrame frame;
  frame.sequence = 7;
  frame.keyframe = true;
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
  return left.sequence == right.sequence && left.keyframe == right.keyframe &&
         left.source_cycle == right.source_cycle &&
         left.access_unit_pts_ns == right.access_unit_pts_ns &&
         left.transport_pts_ns == right.transport_pts_ns &&
         left.access_unit_dts_ns == right.access_unit_dts_ns && left.duration_ns == right.duration_ns &&
         left.admission_id == right.admission_id && left.input_frame_key == right.input_frame_key &&
         left.payload_sha256 == right.payload_sha256 && left.payload == right.payload;
}

int fd_count() {
  DIR* directory = ::opendir("/proc/self/fd");
  if (!directory) throw std::runtime_error("cannot inspect genuine FD closure");
  int count = 0;
  while (::readdir(directory)) ++count;
  ::closedir(directory);
  return count;
}
template<typename Transport> auto read_with_cap(int fd, vast::CheckpointAdmissionFrame& frame,
    const vast::CheckpointIoDeadline* io, std::size_t cap, int)
    -> decltype(Transport::read_frame(fd,frame,io,cap)) {return Transport::read_frame(fd,frame,io,cap);}
template<typename Transport> bool read_with_cap(int fd, vast::CheckpointAdmissionFrame& frame,
    const vast::CheckpointIoDeadline* io, std::size_t, long) {return Transport::read_frame(fd,frame,io);}
bool caller_cap_checked_before_body() {
  std::array<int,2> fds{}; if(::pipe(fds.data())!=0) throw std::runtime_error("cap pipe failed");
  vast::CheckpointAdmissionTransport::write_frame(fds[1],sample_frame()); ::close(fds[1]);
  vast::CheckpointAdmissionFrame actual;
  vast::CheckpointIoDeadline io(vast::CheckpointIoDeadline::monotonic_now_ns()+1'000'000'000ULL);
  bool rejected=false;
  try {(void)read_with_cap<vast::CheckpointAdmissionTransport>(fds[0],actual,&io,4,0);}
  catch(const std::exception& exc) {rejected=std::string(exc.what()).find("payload size")!=std::string::npos;}
  ::close(fds[0]);
  if(!rejected) std::cerr<<"caller transient payload cap was ignored before body allocation\n";
  return rejected;
}

// Peers remain open until AFTER the deadline observation. Closing a fixture's
// peer must never masquerade as successful owner cancellation.
bool original_deadline_retires_real_pipe(int mode) {
  const int before = fd_count();
  std::array<int, 2> fds{};
  if (::pipe(fds.data()) != 0) throw std::runtime_error("pipe failed");
  auto frame = sample_frame();
  if (mode == 1) {
    std::array<int, 2> encoded{};
    if (::pipe(encoded.data()) != 0) throw std::runtime_error("encoding pipe failed");
    vast::CheckpointAdmissionTransport::write_frame(encoded[1], frame);
    ::close(encoded[1]);
    std::vector<std::uint8_t> bytes(1024);
    const auto count = ::read(encoded[0], bytes.data(), bytes.size());
    ::close(encoded[0]);
    if (count <= static_cast<ssize_t>(frame.payload.size())) throw std::runtime_error("no real frame body");
    bytes.resize(static_cast<std::size_t>(count) - 2);
    if (::write(fds[1], bytes.data(), bytes.size()) != static_cast<ssize_t>(bytes.size())) {
      throw std::runtime_error("failed to write actual partial body");
    }
  } else if (mode != 2) {
    const std::array<std::uint8_t, 4> prefix = {'V', 'A', 'S', 'T'};
    if (::write(fds[1], prefix.data(), prefix.size()) != 4) throw std::runtime_error("partial header failed");
  } else {
    frame.payload.resize(128 * 1024, 0x65);
  }
  const auto end = vast::CheckpointIoDeadline::monotonic_now_ns() + 250'000'000ULL;
  vast::CheckpointIoDeadline io(end);
  std::mutex mutex;
  std::condition_variable changed;
  bool done = false;
  std::string failure;
  std::thread worker([&] {
    try {
      if (mode == 2) vast::CheckpointAdmissionTransport::write_frame(fds[1], frame, &io);
      else vast::CheckpointAdmissionTransport::read_frame(fds[0], frame, &io);
    } catch (const std::exception& exc) { failure = exc.what(); }
    { std::lock_guard<std::mutex> lock(mutex); done = true; }
    changed.notify_all();
  });
  if (mode == 3) {
    std::this_thread::sleep_for(std::chrono::milliseconds(50));
    io.abort();
  }
  bool retired_before_peer_release = false;
  {
    std::unique_lock<std::mutex> lock(mutex);
    retired_before_peer_release = changed.wait_until(lock,
        std::chrono::steady_clock::time_point(std::chrono::nanoseconds(end + 750'000'000ULL)),
        [&] { return done; });
  }
  if (mode == 2) {
    vast::CheckpointIoDeadline::set_owned_nonblocking(fds[0]);
    std::array<std::uint8_t, 4096> discard{};
    while (true) {
      { std::lock_guard<std::mutex> lock(mutex); if (done) break; }
      (void)::read(fds[0], discard.data(), discard.size());
      std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
  } else {
    ::close(fds[1]);
    fds[1] = -1;
  }
  worker.join();
  ::close(fds[0]);
  if (fds[1] >= 0) ::close(fds[1]);
  const bool deadline_failure = failure.find(mode == 3 ? "aborted" : "deadline") != std::string::npos;
  if (!retired_before_peer_release || !deadline_failure || fd_count() != before) {
    std::cerr << "actual pipe mode " << mode << " did not retire before fixture release: " << failure << '\n';
    return false;
  }
  return true;
}

}  // namespace

int main() {
  bool all_retired = true;
  for (int mode = 0; mode < 4; ++mode) all_retired = original_deadline_retires_real_pipe(mode) && all_retired;
  if (!all_retired) return 10;
  if (!caller_cap_checked_before_body()) return 11;
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
