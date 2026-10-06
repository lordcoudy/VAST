#include <atomic>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <thread>
#include <sys/socket.h>

namespace analytics_reply_scheduling_fixture {
std::atomic<int> target_fd{-1};
std::atomic<std::uint64_t> original_deadline_ns{0}, received_ns{0}, returned_ns{0};
std::atomic<ssize_t> received_bytes{0};
std::uint64_t now_ns() {
  return static_cast<std::uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(
      std::chrono::steady_clock::now().time_since_epoch()).count());
}
}
// Forward a genuine recv unchanged, then model a scheduling pause after the
// kernel supplied a valid packet. Neither the packet nor the clock is mocked.
ssize_t fixture_recv_after_original_deadline(int fd, void* bytes, std::size_t size, int flags) {
  const ssize_t actual = ::recv(fd, bytes, size, flags);
  if (actual > 0 && fd == analytics_reply_scheduling_fixture::target_fd.load()) {
    analytics_reply_scheduling_fixture::received_ns.store(analytics_reply_scheduling_fixture::now_ns());
    analytics_reply_scheduling_fixture::received_bytes.store(actual);
    const auto release = analytics_reply_scheduling_fixture::original_deadline_ns.load() + 20'000'000ULL;
    while (analytics_reply_scheduling_fixture::now_ns() < release)
      std::this_thread::sleep_for(std::chrono::milliseconds(1));
    analytics_reply_scheduling_fixture::returned_ns.store(analytics_reply_scheduling_fixture::now_ns());
  }
  return actual;
}
#define recv fixture_recv_after_original_deadline
#include "checkpoint_analytics_execution_client.hpp"
#undef recv

#include <glib.h>

#include <algorithm>
#include <array>
#include <cerrno>
#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <cstdint>
#include <cstring>
#include <dirent.h>
#include <exception>
#include <fcntl.h>
#include <iostream>
#include <mutex>
#include <stdexcept>
#include <string>
#include <sys/stat.h>
#include <thread>
#include <vector>

#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

namespace {

constexpr std::size_t kMaximumPayloadBytes = 67'108'864U;

struct Packet {
  std::string json;
  int fd = -1;
};

Packet receive_packet(int socket_fd) {
  std::array<char, 65536> data{};
  std::array<char, CMSG_SPACE(sizeof(int))> control{};
  iovec vector{};
  vector.iov_base = data.data();
  vector.iov_len = data.size();
  msghdr message{};
  message.msg_iov = &vector;
  message.msg_iovlen = 1;
  message.msg_control = control.data();
  message.msg_controllen = control.size();
  const ssize_t size = ::recvmsg(socket_fd, &message, MSG_CMSG_CLOEXEC | MSG_TRUNC);
  if (size <= 0 || static_cast<std::size_t>(size) >= data.size() ||
      (message.msg_flags & (MSG_TRUNC | MSG_CTRUNC)) != 0) {
    throw std::runtime_error(
        "invalid analytics execution packet: size=" + std::to_string(size) +
        " flags=" + std::to_string(message.msg_flags) +
        " control=" + std::to_string(message.msg_controllen) +
        " errno=" + std::to_string(errno));
  }
  cmsghdr* header = CMSG_FIRSTHDR(&message);
  if (header == nullptr || header->cmsg_level != SOL_SOCKET ||
      header->cmsg_type != SCM_RIGHTS || header->cmsg_len != CMSG_LEN(sizeof(int)) ||
      CMSG_NXTHDR(&message, header) != nullptr) {
    throw std::runtime_error("analytics execution packet lacks one input FD");
  }
  int received_fd = -1;
  std::memcpy(&received_fd, CMSG_DATA(header), sizeof(received_fd));
  return {std::string(data.data(), static_cast<std::size_t>(size)), received_fd};
}

void send_packet(int fd, const std::string& payload) {
  const ssize_t size = ::send(fd, payload.data(), payload.size(), 0);
  if (size != static_cast<ssize_t>(payload.size())) {
    throw std::runtime_error("failed to send analytics execution response");
  }
}

bool contains(const std::string& value, const std::string& expected) {
  return value.find(expected) != std::string::npos;
}

void test_environment_path_connection() {
  const std::string path =
      "/tmp/vast-analytics-execution-client-" + std::to_string(::getpid()) + ".sock";
  ::unlink(path.c_str());
  const int listener = ::socket(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0);
  if (listener < 0) throw std::runtime_error("failed to create path listener");
  sockaddr_un address{};
  address.sun_family = AF_UNIX;
  if (path.size() >= sizeof(address.sun_path)) {
    ::close(listener);
    throw std::runtime_error("test socket path is too long");
  }
  std::memcpy(address.sun_path, path.c_str(), path.size() + 1);
  if (::bind(
          listener,
          reinterpret_cast<const sockaddr*>(&address),
          static_cast<socklen_t>(offsetof(sockaddr_un, sun_path) + path.size() + 1)) != 0 ||
      ::listen(listener, 1) != 0) {
    ::close(listener);
    ::unlink(path.c_str());
    throw std::runtime_error("failed to bind/listen on path socket");
  }
  try {
    ::unsetenv(vast::CheckpointAnalyticsExecutionClient::kFdEnvironment);
    if (::setenv(
            vast::CheckpointAnalyticsExecutionClient::kSocketEnvironment,
            path.c_str(),
            1) != 0) {
      throw std::runtime_error("failed to set path environment");
    }
    {
      vast::CheckpointAnalyticsExecutionClient client =
          vast::CheckpointAnalyticsExecutionClient::from_environment();
      const int accepted = ::accept4(listener, nullptr, nullptr, SOCK_CLOEXEC);
      if (accepted < 0) throw std::runtime_error("path listener did not accept client");
      int socket_type = 0;
      socklen_t size = sizeof(socket_type);
      if (::getsockopt(accepted, SOL_SOCKET, SO_TYPE, &socket_type, &size) != 0 ||
          size != sizeof(socket_type) || socket_type != SOCK_SEQPACKET) {
        ::close(accepted);
        throw std::runtime_error("path client did not negotiate SOCK_SEQPACKET");
      }
      ::close(accepted);
    }

    if (::setenv(
            vast::CheckpointAnalyticsExecutionClient::kSocketEnvironment,
            "relative.sock",
            1) != 0) {
      throw std::runtime_error("failed to set relative path environment");
    }
    bool rejected_relative = false;
    try {
      (void)vast::CheckpointAnalyticsExecutionClient::from_environment();
    } catch (const std::exception& exc) {
      rejected_relative = contains(exc.what(), "path is invalid");
    }
    if (!rejected_relative) {
      throw std::runtime_error("relative analytics execution socket path was accepted");
    }
  } catch (...) {
    ::unsetenv(vast::CheckpointAnalyticsExecutionClient::kSocketEnvironment);
    ::close(listener);
    ::unlink(path.c_str());
    throw;
  }
  ::unsetenv(vast::CheckpointAnalyticsExecutionClient::kSocketEnvironment);
  ::close(listener);
  ::unlink(path.c_str());
}

std::string sha256(const std::uint8_t* data, std::size_t size) {
  gchar* digest = g_compute_checksum_for_data(
      G_CHECKSUM_SHA256, reinterpret_cast<const guchar*>(data), static_cast<gsize>(size));
  if (digest == nullptr) throw std::runtime_error("GLib did not compute SHA-256");
  std::string result(digest);
  g_free(digest);
  return result;
}

vast::CheckpointAnalyticsExecutionRequest make_request(
    std::size_t size, const std::string& digest) {
  vast::CheckpointAnalyticsExecutionRequest request;
  request.request_id = "analytics-boundary-test";
  request.run_id = "run-boundary-test";
  request.arm_id = "arm-boundary-test";
  request.worker_id = "worker-boundary-test";
  request.input_frame_key = "dataset:0:source:1:90000";
  request.branch = "damage";
  request.decision.decision_id = "decision-boundary-test";
  request.decision.decision_seq = 1;
  request.decision.selected_resource = "gpu";
  request.decision.selected_implementation_id = "implementation-boundary-test";
  request.decision.emitter_id = "emitter-boundary-test";
  request.decision.emitter_sha256 = std::string(64, '1');
  request.deadline_monotonic_ns = static_cast<std::uint64_t>(
      std::chrono::duration_cast<std::chrono::nanoseconds>(
          std::chrono::steady_clock::now().time_since_epoch()).count()) + 60'000'000'000ULL;
  request.format = "BGR";
  request.width = 1;
  request.height = 1;
  request.stride = size;
  request.preprocessing_contract_sha256 = std::string(64, '2');
  request.raw_input_sha256 = digest;
  return request;
}

template <typename Invoke>
void expect_local_rejection(Invoke&& invoke, const std::string& expected_message) {
  int descriptors[2] = {-1, -1};
  if (::socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0, descriptors) != 0) {
    throw std::runtime_error("local-rejection socketpair failed");
  }
  timeval timeout{};
  timeout.tv_sec = 2;
  ::setsockopt(descriptors[0], SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
  try {
    {
      vast::CheckpointAnalyticsExecutionClient client(descriptors[0]);
      bool rejected = false;
      try {
        invoke(client);
      } catch (const std::exception& error) {
        rejected = contains(error.what(), expected_message);
      }
      if (!rejected) throw std::runtime_error("missing local error: " + expected_message);
      char byte = 0;
      errno = 0;
      const ssize_t received = ::recv(descriptors[1], &byte, 1, MSG_DONTWAIT);
      if (received != -1 || (errno != EAGAIN && errno != EWOULDBLOCK)) {
        throw std::runtime_error("invalid request sent a datagram or payload FD");
      }
    }
    ::close(descriptors[1]);
  } catch (...) {
    ::close(descriptors[1]);
    throw;
  }
}

void test_local_payload_rejections() {
  const std::array<std::uint8_t, 4> payload{1, 2, 3, 4};
  const auto wrong_hash = make_request(payload.size(), std::string(64, '0'));
  expect_local_rejection(
      [&](vast::CheckpointAnalyticsExecutionClient& client) {
        (void)client.execute(wrong_hash, payload.data(), payload.size());
      },
      "SHA-256 differs");
  const auto zero = make_request(3, std::string(64, '0'));
  expect_local_rejection(
      [&](vast::CheckpointAnalyticsExecutionClient& client) {
        (void)client.execute(zero, nullptr, 0);
      },
      "payload is empty");
  const std::uint8_t one_byte = 7;
  const std::size_t oversized = kMaximumPayloadBytes + 1U;
  const auto too_large = make_request(oversized, std::string(64, '0'));
  expect_local_rejection(
      [&](vast::CheckpointAnalyticsExecutionClient& client) {
        (void)client.execute(too_large, &one_byte, oversized);
      },
      "bounded maximum");
}

std::string sha256_fd(int fd, std::size_t size) {
  GChecksum* checksum = g_checksum_new(G_CHECKSUM_SHA256);
  if (checksum == nullptr) throw std::runtime_error("GLib did not allocate a checksum");
  std::array<std::uint8_t, 64 * 1024> buffer{};
  std::size_t offset = 0;
  while (offset < size) {
    const std::size_t wanted = std::min(buffer.size(), size - offset);
    const ssize_t count = ::pread(fd, buffer.data(), wanted, static_cast<off_t>(offset));
    if (count <= 0) {
      g_checksum_free(checksum);
      throw std::runtime_error("sealed snapshot is truncated");
    }
    g_checksum_update(checksum, buffer.data(), static_cast<gssize>(count));
    offset += static_cast<std::size_t>(count);
  }
  const std::string result(g_checksum_get_string(checksum));
  g_checksum_free(checksum);
  return result;
}

std::size_t open_fd_count() {
  DIR* directory = ::opendir("/proc/self/fd");
  if (directory == nullptr) throw std::runtime_error("cannot inspect /proc/self/fd");
  std::size_t count = 0;
  while (::readdir(directory) != nullptr) ++count;
  ::closedir(directory);
  return count;
}

std::string valid_cpu_fixture_response(const vast::CheckpointAnalyticsExecutionRequest& request) {
  const auto received = vast::CheckpointIoDeadline::monotonic_now_ns();
  const auto started = vast::CheckpointIoDeadline::monotonic_now_ns();
  const auto finished = vast::CheckpointIoDeadline::monotonic_now_ns();
  const auto completed = vast::CheckpointIoDeadline::monotonic_now_ns();
  // Synthetic protocol-worker fields, never a claim that inference executed.
  // All four fixture timing markers are real observations in this process.
  return "{\"schema_version\":1,\"message_type\":\"analytics_execute_response\",\"request_id\":\"" +
      request.request_id + "\",\"decision_id\":\"" + request.decision.decision_id + "\",\"decision_seq\":" +
      std::to_string(request.decision.decision_seq) + ",\"branch\":\"damage\",\"selected_resource\":\"cpu\","
      "\"terminal_status\":\"completed\",\"terminal_reason\":\"synthetic_protocol_fixture_completed\",\"objects\":1,"
      "\"detector\":\"fixture-detector\",\"backend\":\"fixture-openvino-protocol\",\"worker_id\":\"fixture-worker\","
      "\"engine\":\"openvino_cpu\",\"worker_image_id\":\"sha256:" + std::string(64, '3') + "\","
      "\"worker_implementation_sha256\":\"" + std::string(64, '4') + "\",\"runtime_name\":\"OpenVINO\","
      "\"runtime_version\":\"fixture\",\"device_api\":\"CPU\",\"device_id\":\"fixture CPU\","
      "\"native_inference_api\":\"openvino.CompiledModel.__call__\",\"execution_path\":\"openvino_cpu_native\","
      "\"model_id\":\"fixture-model\",\"source_model_sha256\":\"" + std::string(64, '5') + "\","
      "\"model_artifact_sha256\":\"" + std::string(64, '6') + "\",\"preprocessing_contract_sha256\":\"" +
      request.preprocessing_contract_sha256 + "\",\"output_contract_sha256\":\"" + std::string(64, '7') + "\","
      "\"raw_input_sha256\":\"" + request.raw_input_sha256 + "\",\"input_sha256\":\"" + request.raw_input_sha256 + "\","
      "\"output_sha256\":\"" + std::string(64, '8') + "\",\"output_bytes\":4,\"worker_received_monotonic_ns\":" +
      std::to_string(received) + ",\"inference_started_monotonic_ns\":" + std::to_string(started) +
      ",\"inference_finished_monotonic_ns\":" + std::to_string(finished) + ",\"worker_completed_monotonic_ns\":" +
      std::to_string(completed) + ",\"inference_latency_ns\":" + std::to_string(finished - started) +
      ",\"resource\":{\"process_cpu_time_ns\":0,\"rss_before_bytes\":0,\"rss_after_bytes\":0,"
      "\"accelerator_memory_bytes\":0,\"cuda_h2d_bytes\":0,\"cuda_d2h_bytes\":0,\"cuda_transfer_intervals\":[]}}";
}

void test_post_response_validation_preserves_original_deadline() {
  const auto before = open_fd_count();
  bool held_reply_refused = false, poisoned_before_reuse = false;
  for (const bool pause : {false, true}) {
    int sockets[2] = {-1, -1};
    if (::socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0, sockets))
      throw std::runtime_error("post-reply actual socketpair failed");
    const std::vector<std::uint8_t> payload{1, 2, 3, 4};
    auto request = make_request(payload.size(), sha256(payload.data(), payload.size()));
    request.decision.selected_resource = "cpu";
    request.deadline_monotonic_ns = vast::CheckpointIoDeadline::monotonic_now_ns() + 300'000'000ULL;
    const auto response = valid_cpu_fixture_response(request);
    std::mutex mutex; std::condition_variable changed; bool client_retired = false;
    std::exception_ptr peer_error; std::string error, reuse_error;
    std::thread peer([&] {
      int snapshot = -1;
      try {
        const auto packet = receive_packet(sockets[1]); snapshot = packet.fd;
        struct stat held{}; const int required = F_SEAL_SEAL | F_SEAL_SHRINK | F_SEAL_GROW | F_SEAL_WRITE;
        if (snapshot < 0 || ::fstat(snapshot, &held) || held.st_size != static_cast<off_t>(payload.size()) ||
            (::fcntl(snapshot, F_GET_SEALS) & required) != required ||
            sha256_fd(snapshot, payload.size()) != request.raw_input_sha256 ||
            !contains(packet.json, "\"request_id\":\"" + request.request_id + "\"") ||
            !contains(packet.json, "\"sha256\":\"" + request.raw_input_sha256 + "\"") ||
            !contains(packet.json, "\"deadline_monotonic_ns\":" + std::to_string(request.deadline_monotonic_ns)))
          throw std::runtime_error("post-reply peer did not receive exact bound sealed request");
        ::close(snapshot); snapshot = -1;
        send_packet(sockets[1], response);
        std::unique_lock<std::mutex> lock(mutex); changed.wait(lock, [&] { return client_retired; });
        char extra = 0; errno = 0;
        const ssize_t received = ::recv(sockets[1], &extra, 1, MSG_DONTWAIT);
        if (received != -1 || (errno != EAGAIN && errno != EWOULDBLOCK))
          throw std::runtime_error("poisoned client sent another request before peer retirement");
      } catch (...) { peer_error = std::current_exception(); }
      if (snapshot >= 0) ::close(snapshot); ::close(sockets[1]);
    });
    {
      vast::CheckpointAnalyticsExecutionClient client(sockets[0]);
      analytics_reply_scheduling_fixture::received_ns.store(0);
      analytics_reply_scheduling_fixture::returned_ns.store(0);
      analytics_reply_scheduling_fixture::received_bytes.store(0);
      analytics_reply_scheduling_fixture::original_deadline_ns.store(request.deadline_monotonic_ns);
      analytics_reply_scheduling_fixture::target_fd.store(pause ? sockets[0] : -1);
      try {
        const auto result = client.execute(request, payload.data(), payload.size());
        if (result.request_id != request.request_id || result.raw_input_sha256 != request.raw_input_sha256 ||
            result.selected_resource != "cpu" || result.terminal_status != "completed")
          throw std::runtime_error("actual unaltered post-reply protocol response drifted");
      } catch (const std::exception& exc) { error = exc.what(); }
      analytics_reply_scheduling_fixture::target_fd.store(-1);
      if (pause && error.find("original deadline exceeded") != std::string::npos) {
        held_reply_refused = true;
        // This is a distinct reuse attempt with its own request ID; it never
        // renews the failed request or the owner endpoint. It must send nothing.
        auto reuse = request; reuse.request_id += "-must-not-reuse";
        reuse.deadline_monotonic_ns = vast::CheckpointIoDeadline::monotonic_now_ns() + 1'000'000'000ULL;
        try { (void)client.execute(reuse, payload.data(), payload.size()); }
        catch (const std::exception& exc) { reuse_error = exc.what(); }
        poisoned_before_reuse = reuse_error.find("poisoned") != std::string::npos;
      }
      { std::lock_guard<std::mutex> lock(mutex); client_retired = true; } changed.notify_all(); peer.join();
    }
    if (peer_error) std::rethrow_exception(peer_error);
    if (!pause && !error.empty()) throw std::runtime_error("valid unpaused protocol control failed: " + error);
    if (pause && (analytics_reply_scheduling_fixture::received_ns.load() == 0 ||
        analytics_reply_scheduling_fixture::received_ns.load() >= request.deadline_monotonic_ns ||
        analytics_reply_scheduling_fixture::returned_ns.load() <= request.deadline_monotonic_ns ||
        analytics_reply_scheduling_fixture::received_bytes.load() != static_cast<ssize_t>(response.size())))
      throw std::runtime_error("post-reply fixture did not actually receive intact response before holding return through original deadline");
    if (pause) {
      std::cerr << "real intact reply bytes=" << analytics_reply_scheduling_fixture::received_bytes.load()
                << " received_ns=" << analytics_reply_scheduling_fixture::received_ns.load()
                << " original_deadline_ns=" << request.deadline_monotonic_ns
                << " returned_ns=" << analytics_reply_scheduling_fixture::returned_ns.load()
                << " result=" << (error.empty() ? "unexpected_success" : error)
                << " reuse=" << reuse_error << '\n';
    }
  }
  if (!held_reply_refused || !poisoned_before_reuse || open_fd_count() != before)
    throw std::runtime_error("actual valid response received before original deadline was accepted after scheduling pause, or channel reused/leaked");
  std::cerr << "actual post-reply original-deadline refusal/poisoned-before-reuse PASS; live socket, sealed memfd and threads/FD retired\n";
}

using WaitObserver = std::function<void(const vast::CheckpointAnalyticsExecutionRequest&,
    const std::string&, std::uint64_t, std::uint64_t, std::uint64_t, std::uint64_t)>;
template<typename Client> auto attach_wait_observer(Client& client, WaitObserver observer, int)
    -> decltype(client.bind_wait_observer(observer), void()) { client.bind_wait_observer(std::move(observer)); }
template<typename Client> void attach_wait_observer(Client&, WaitObserver, long) {}

void test_path_connect_uses_original_startup_bound() {
  const auto before = open_fd_count();
  const auto path = "/tmp/vast-original-startup-" + std::to_string(::getpid()) + ".sock";
  int listener = ::socket(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0);
  sockaddr_un address{}; address.sun_family=AF_UNIX;
  std::memcpy(address.sun_path,path.c_str(),path.size()+1);
  if(listener<0||::bind(listener,reinterpret_cast<sockaddr*>(&address),sizeof(address))!=0||::listen(listener,0)!=0)
    throw std::runtime_error("actual startup listener unavailable");
  int filler=::socket(AF_UNIX,SOCK_SEQPACKET|SOCK_CLOEXEC,0);
  if(filler<0||::connect(filler,reinterpret_cast<sockaddr*>(&address),sizeof(address))!=0)
    throw std::runtime_error("genuine listener backlog did not fill");
  ::unsetenv(vast::CheckpointAnalyticsExecutionClient::kFdEnvironment);
  ::setenv(vast::CheckpointAnalyticsExecutionClient::kSocketEnvironment,path.c_str(),1);
  const auto end=vast::CheckpointIoDeadline::monotonic_now_ns()+250'000'000ULL;
  ::setenv("VAST_CHECKPOINT_STARTUP_DEADLINE_MONOTONIC_NS",std::to_string(end).c_str(),1);
  std::mutex mutex; std::condition_variable changed; bool done=false; std::string error;
  std::thread connecting([&] {
    try { auto client=vast::CheckpointAnalyticsExecutionClient::from_environment(); }
    catch(const std::exception& exc) {error=exc.what();}
    {std::lock_guard<std::mutex> lock(mutex);done=true;}changed.notify_all();
  });
  bool bounded=false;
  {
    std::unique_lock<std::mutex> lock(mutex);
    bounded=changed.wait_until(lock,std::chrono::steady_clock::time_point(
        std::chrono::nanoseconds(end+750'000'000ULL)),[&]{return done;});
  }
  // Free the actual backlog only AFTER observing the unchanged startup bound.
  int accepted=::accept(listener,nullptr,nullptr);
  if(accepted>=0) ::close(accepted);
  connecting.join(); ::close(filler); ::close(listener); ::unlink(path.c_str());
  ::unsetenv("VAST_CHECKPOINT_STARTUP_DEADLINE_MONOTONIC_NS");
  ::unsetenv(vast::CheckpointAnalyticsExecutionClient::kSocketEnvironment);
  if(!bounded||error.find("deadline")==std::string::npos||open_fd_count()!=before)
    throw std::runtime_error("actual full listener backlog exceeded original startup deadline before fixture release");
}

void test_observer_io_is_not_client_mutex_wait() {
  const auto before=open_fd_count();int sockets[2];
  if(::socketpair(AF_UNIX,SOCK_SEQPACKET|SOCK_CLOEXEC,0,sockets))throw std::runtime_error("actual wait pair failed");
  std::mutex mutex;std::condition_variable changed;bool done=false;std::exception_ptr peer_error;
  std::thread peer([&]{try{auto packet=receive_packet(sockets[1]);if(packet.fd<0)throw std::runtime_error("no actual sealed wait request");
      ::close(packet.fd);std::unique_lock<std::mutex> lock(mutex);changed.wait(lock,[&]{return done;});}
    catch(...){peer_error=std::current_exception();}::close(sockets[1]);});
  std::array<std::uint64_t,4> observed{};
  const std::vector<std::uint8_t> payload{1,2,3};auto request=make_request(payload.size(),sha256(payload.data(),payload.size()));
  request.deadline_monotonic_ns=vast::CheckpointIoDeadline::monotonic_now_ns()+250'000'000ULL;
  std::string error;
  {
    vast::CheckpointAnalyticsExecutionClient client(sockets[0]);
    attach_wait_observer(client,[&](const auto&,const std::string& phase,auto attempt,auto acquired,auto reply,auto released){
      if(phase=="begin")std::this_thread::sleep_for(std::chrono::milliseconds(100));
      else if(phase=="released")observed={attempt,acquired,reply,released};
    },0);
    try{client.execute(request,payload.data(),payload.size());}catch(const std::exception& exc){error=exc.what();}
    {std::lock_guard<std::mutex> lock(mutex);done=true;}changed.notify_all();peer.join();
  }
  if(peer_error)std::rethrow_exception(peer_error);
  if(error.find("deadline")==std::string::npos||observed[0]==0||observed[1]<observed[0]||
     observed[1]-observed[0]>=50'000'000ULL||observed[3]-observed[0]<150'000'000ULL||open_fd_count()!=before)
    throw std::runtime_error("actual synchronous observer delay was misclassified as client mutex wait");
}

void test_original_startup_deadline_cannot_be_signed_or_coerced() {
  const auto before=open_fd_count();::unsetenv(vast::CheckpointAnalyticsExecutionClient::kFdEnvironment);
  ::setenv(vast::CheckpointAnalyticsExecutionClient::kSocketEnvironment,"/proc/vast-missing-listener/socket",1);
  bool all=true;
  for(const auto* raw:{"-1","+999999999999999999"," 999999999999999999","999tail","0"}) {
    ::setenv("VAST_CHECKPOINT_STARTUP_DEADLINE_MONOTONIC_NS",raw,1);std::string error;
    try{auto client=vast::CheckpointAnalyticsExecutionClient::from_environment();}catch(const std::exception& exc){error=exc.what();}
    all=all&&error.find("invalid original analytics startup deadline")!=std::string::npos;
  }
  ::unsetenv("VAST_CHECKPOINT_STARTUP_DEADLINE_MONOTONIC_NS");
  ::unsetenv(vast::CheckpointAnalyticsExecutionClient::kSocketEnvironment);
  if(!all||open_fd_count()!=before)throw std::runtime_error("original analytics startup deadline accepted signed/coerced input before owned allocation");
}

void test_maximum_snapshot_reuse_and_cleanup() {
  const std::size_t before = open_fd_count();
  const std::size_t size = kMaximumPayloadBytes;
  std::vector<std::uint8_t> payload(size, 0x5a);
  const std::string digest = sha256(payload.data(), payload.size());
  const auto request = make_request(size, digest);
  int descriptors[2] = {-1, -1};
  if (::socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0, descriptors) != 0) {
    throw std::runtime_error("maximum-payload socketpair failed");
  }
  std::mutex mutex;
  std::condition_variable condition;
  bool received = false;
  bool reused = false;
  std::exception_ptr server_error;
  std::exception_ptr client_error;
  std::thread server([&]() {
    int payload_fd = -1;
    try {
      Packet packet = receive_packet(descriptors[1]);
      payload_fd = packet.fd;
      struct stat state{};
      if (::fstat(payload_fd, &state) != 0 || static_cast<std::size_t>(state.st_size) != size) {
        throw std::runtime_error("sealed snapshot has wrong size");
      }
      const int seals = ::fcntl(payload_fd, F_GET_SEALS);
      const int required = F_SEAL_SEAL | F_SEAL_SHRINK | F_SEAL_GROW | F_SEAL_WRITE;
      if (seals < 0 || (seals & required) != required) {
        throw std::runtime_error("snapshot is not fully sealed");
      }
      {
        std::unique_lock<std::mutex> lock(mutex);
        received = true;
        condition.notify_all();
        condition.wait(lock, [&]() { return reused; });
      }
      if (sha256_fd(payload_fd, size) != digest ||
          !contains(packet.json, "\"sha256\":\"" + digest + "\"") ||
          !contains(packet.json, "\"byte_length\":" + std::to_string(size))) {
        throw std::runtime_error("sealed bytes and request metadata describe different snapshots");
      }
    } catch (...) {
      server_error = std::current_exception();
      std::lock_guard<std::mutex> lock(mutex);
      received = true;
      reused = true;
      condition.notify_all();
    }
    if (payload_fd >= 0) ::close(payload_fd);
    ::close(descriptors[1]);
  });
  std::thread caller([&]() {
    try {
      vast::CheckpointAnalyticsExecutionClient client(descriptors[0]);
      (void)client.execute(request, payload.data(), payload.size());
      throw std::runtime_error("closed test worker unexpectedly returned a response");
    } catch (const std::exception& error) {
      if (!contains(error.what(), "peer closed before its response")) {
        client_error = std::current_exception();
      }
    }
  });
  {
    std::unique_lock<std::mutex> lock(mutex);
    condition.wait(lock, [&]() { return received; });
    std::fill(payload.begin(), payload.end(), 0xa5);
    reused = true;
    condition.notify_all();
  }
  caller.join();
  server.join();
  if (server_error) std::rethrow_exception(server_error);
  if (client_error) std::rethrow_exception(client_error);
  if (open_fd_count() != before) throw std::runtime_error("exception path leaked a descriptor");
}

void test_original_deadline_interrupts_silent_peer_and_queued_caller() {
  const auto before = open_fd_count();
  int descriptors[2] = {-1, -1};
  if (::socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0, descriptors) != 0) {
    throw std::runtime_error("silent-peer socketpair failed");
  }
  std::mutex gate_mutex;
  std::condition_variable gate;
  bool received = false;
  bool release_peer = false;
  std::size_t completed = 0;
  std::array<std::string, 2> errors;
  std::exception_ptr peer_error;
  const std::vector<std::uint8_t> payload{1, 2, 3};
  auto request = make_request(payload.size(), sha256(payload.data(), payload.size()));
  const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(250);
  request.deadline_monotonic_ns = static_cast<std::uint64_t>(
      std::chrono::duration_cast<std::chrono::nanoseconds>(deadline.time_since_epoch()).count());
  bool settled_before_release = false;
  std::vector<std::array<std::uint64_t,4>> observed_waits;
  std::size_t begin_rows=0;
  {
    vast::CheckpointAnalyticsExecutionClient client(descriptors[0]);
    attach_wait_observer(client, [&](const auto&,const std::string& phase,auto attempt,auto acquired,auto reply,auto released) {
      std::lock_guard<std::mutex> lock(gate_mutex);
      if(phase=="begin") {if(attempt==0||acquired||reply||released) throw std::runtime_error("fabricated wait begin"); ++begin_rows;}
      else if(phase=="released") observed_waits.push_back({attempt,acquired,reply,released});
    },0);
    std::thread peer([&]() {
      int snapshot_fd = -1;
      try {
        const Packet packet = receive_packet(descriptors[1]);
        snapshot_fd = packet.fd;
        const int required = F_SEAL_SEAL | F_SEAL_SHRINK | F_SEAL_GROW | F_SEAL_WRITE;
        if (snapshot_fd < 0 || (::fcntl(snapshot_fd, F_GET_SEALS) & required) != required ||
            sha256_fd(snapshot_fd, payload.size()) != request.raw_input_sha256) {
          throw std::runtime_error("silent peer did not receive the genuine sealed request");
        }
      } catch (...) {
        peer_error = std::current_exception();
      }
      if (snapshot_fd >= 0) ::close(snapshot_fd);
      std::unique_lock<std::mutex> lock(gate_mutex);
      received = true;
      gate.notify_all();
      gate.wait_for(lock, std::chrono::seconds(3), [&]() { return release_peer; });
      lock.unlock();
      ::close(descriptors[1]);
    });
    auto invoke = [&](std::size_t index) {
      auto local = request;
      local.request_id += std::to_string(index);
      try {
        (void)client.execute(local, payload.data(), payload.size());
        errors[index] = "unexpected success";
      } catch (const std::exception& error) {
        errors[index] = error.what();
      }
      std::lock_guard<std::mutex> lock(gate_mutex);
      ++completed;
      gate.notify_all();
    };
    std::thread first(invoke, 0);
    bool first_seen = false;
    {
      std::unique_lock<std::mutex> lock(gate_mutex);
      first_seen = gate.wait_for(lock, std::chrono::seconds(1), [&]() { return received; });
    }
    std::thread second(invoke, 1);
    {
      std::unique_lock<std::mutex> lock(gate_mutex);
      settled_before_release = first_seen && gate.wait_until(
          lock, deadline + std::chrono::milliseconds(750), [&]() { return completed == 2; });
      release_peer = true;
      gate.notify_all();
    }
    // Fixture releases its own endpoint only after observing the bound. The
    // client FD remains owned until both real callers have actually retired.
    first.join();
    second.join();
    peer.join();
  }
  if (peer_error) std::rethrow_exception(peer_error);
  if (!settled_before_release || errors[0].find("deadline") == std::string::npos ||
      errors[1].find("deadline") == std::string::npos) {
    throw std::runtime_error(
        "original deadline did not retire silent-peer exchange and queued caller before fixture release");
  }
  if (open_fd_count() != before) throw std::runtime_error("silent-peer deadline leaked an owned FD");
  if(begin_rows!=1||observed_waits.size()!=2) throw std::runtime_error("actual acquired/unknown wait prefixes are missing");
  for(const auto& wait:observed_waits) if(wait[0]==0||wait[3]<wait[0]||wait[2]!=0)
    throw std::runtime_error("failed silent-peer wait fabricated a reply/clock");
}

}  // namespace

void test_peer_close_is_not_reported_as_truncation() {
  // Real J: the sidecar failed closed and later clients saw EOF, not an oversized reply.
  int sockets[2] = {-1, -1};
  if (::socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0, sockets))
    throw std::runtime_error("peer-close socketpair failed");
  const std::vector<std::uint8_t> payload{1, 2, 3, 4};
  auto request = make_request(payload.size(), sha256(payload.data(), payload.size()));
  request.decision.selected_resource = "cpu";
  request.deadline_monotonic_ns = vast::CheckpointIoDeadline::monotonic_now_ns() + 2'000'000'000ULL;
  std::thread peer([&] {
    try { const auto packet = receive_packet(sockets[1]); if (packet.fd >= 0) ::close(packet.fd); } catch (...) {}
    ::close(sockets[1]);
  });
  std::string error;
  {
    vast::CheckpointAnalyticsExecutionClient client(sockets[0]);
    try { (void)client.execute(request, payload.data(), payload.size()); } catch (const std::exception& exc) { error = exc.what(); }
  }
  peer.join();
  if (error.find("peer closed") == std::string::npos || error.find("truncated") != std::string::npos)
    throw std::runtime_error("analytics peer close was reported as: " + error);
}

int main() {
  try {
    test_peer_close_is_not_reported_as_truncation();
    test_post_response_validation_preserves_original_deadline();
    test_path_connect_uses_original_startup_bound();
    test_original_startup_deadline_cannot_be_signed_or_coerced();
    test_observer_io_is_not_client_mutex_wait();
    test_original_deadline_interrupts_silent_peer_and_queued_caller();
    test_local_payload_rejections();
    test_maximum_snapshot_reuse_and_cleanup();
    test_environment_path_connection();
  } catch (const std::exception& exc) {
    std::cerr << exc.what() << '\n';
    return 1;
  }
  int descriptors[2] = {-1, -1};
  if (::socketpair(AF_UNIX, SOCK_SEQPACKET, 0, descriptors) != 0) {
    std::cerr << "socketpair failed\n";
    return 2;
  }
  timeval timeout{};
  timeout.tv_sec = 2;
  if (::setsockopt(descriptors[0], SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) != 0 ||
      ::setsockopt(descriptors[1], SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) != 0) {
    std::cerr << "setsockopt failed\n";
    return 2;
  }
  try {
    const std::string raw_sha =
        "9f64a747e1b97f131fabb6b447296c9b6f0201e79fb3c5356e6c77e89b6a806a";
    const std::string policy_sha =
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
    const std::string contract_sha =
        "1123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
    std::exception_ptr server_error;
    std::thread server([&]() {
      try {
        Packet packet = receive_packet(descriptors[1]);
        if (!contains(packet.json, "\"message_type\":\"analytics_execute\"") ||
            !contains(packet.json, "\"selected_resource\":\"gpu\"") ||
            !contains(packet.json, "\"kind\":\"raw_gstreamer_frame\"") ||
            !contains(packet.json, "\"format\":\"BGR\"") ||
            !contains(packet.json, "\"stride\":4") ||
            !contains(packet.json, "\"sha256\":\"" + raw_sha + "\"")) {
          throw std::runtime_error("analytics execution request is incomplete");
        }
        const int seals = ::fcntl(packet.fd, F_GET_SEALS);
        const int required = F_SEAL_SEAL | F_SEAL_SHRINK | F_SEAL_GROW | F_SEAL_WRITE;
        if (seals < 0 || (seals & required) != required) {
          throw std::runtime_error("analytics input memfd is not sealed");
        }
        std::array<std::uint8_t, 4> observed{};
        if (::pread(packet.fd, observed.data(), observed.size(), 0) !=
                static_cast<ssize_t>(observed.size()) ||
            observed != std::array<std::uint8_t, 4>{1, 2, 3, 4}) {
          throw std::runtime_error("analytics input memfd payload drifted");
        }
        ::close(packet.fd);
        send_packet(
            descriptors[1],
            "{\"backend\":\"cuda-tensorrt:sidecar;device=NVIDIA CUDA:0\","
            "\"branch\":\"damage\",\"decision_id\":\"decision-native-0001\"," 
            "\"decision_seq\":7,\"detector\":\"damage-gpu-detector-v1\"," 
            "\"device_api\":\"NVIDIA_CUDA\",\"device_id\":\"GPU-00000000-0000-0000-0000-000000000001\"," 
            "\"engine\":\"tensorrt_cuda\",\"execution_path\":\"tensorrt_cuda_native\"," 
            "\"inference_finished_monotonic_ns\":130,\"inference_latency_ns\":20," 
            "\"inference_started_monotonic_ns\":110,\"input_sha256\":\"2123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\"," 
            "\"message_type\":\"analytics_execute_response\",\"model_artifact_sha256\":\"3123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\"," 
            "\"model_id\":\"damage-model-v1\",\"native_inference_api\":\"nvinfer1::IExecutionContext::enqueueV3\"," 
            "\"objects\":1,\"output_bytes\":32,\"output_contract_sha256\":\"4123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\"," 
            "\"output_sha256\":\"5123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\"," 
            "\"preprocessing_contract_sha256\":\"" + contract_sha + "\"," 
            "\"raw_input_sha256\":\"" + raw_sha + "\",\"request_id\":\"analytics-request-0001\"," 
            "\"resource\":{\"accelerator_memory_bytes\":4096,\"cuda_d2h_bytes\":32,"
            "\"cuda_h2d_bytes\":4,\"cuda_transfer_intervals\":["
            "{\"bytes\":4,\"device_elapsed_ns\":3,"
            "\"device_id\":\"GPU-00000000-0000-0000-0000-000000000001\","
            "\"direction\":\"h2d\",\"host_end_monotonic_ns\":115,"
            "\"host_start_monotonic_ns\":111,\"timing_source\":\"cudaEventElapsedTime\"},"
            "{\"bytes\":32,\"device_elapsed_ns\":3,"
            "\"device_id\":\"GPU-00000000-0000-0000-0000-000000000001\","
            "\"direction\":\"d2h\",\"host_end_monotonic_ns\":129,"
            "\"host_start_monotonic_ns\":125,\"timing_source\":\"cudaEventElapsedTime\"}],"
            "\"process_cpu_time_ns\":50,\"rss_after_bytes\":8192,\"rss_before_bytes\":4096},"
            "\"runtime_name\":\"TensorRT\",\"runtime_version\":\"8.6.1.6\",\"schema_version\":1," 
            "\"selected_resource\":\"gpu\",\"source_model_sha256\":\"6123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\"," 
            "\"terminal_reason\":\"native_fixed_tensor_completed\",\"terminal_status\":\"completed\"," 
            "\"worker_completed_monotonic_ns\":140,\"worker_id\":\"vast.damage.tensorrt\"," 
            "\"worker_image_id\":\"sha256:7123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\"," 
            "\"worker_implementation_sha256\":\"8123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\"," 
            "\"worker_received_monotonic_ns\":100}");
      } catch (...) {
        server_error = std::current_exception();
      }
      ::close(descriptors[1]);
    });

    vast::CheckpointAnalyticsExecutionClient client(descriptors[0]);
    vast::CheckpointAnalyticsExecutionRequest request;
    request.request_id = "analytics-request-0001";
    request.run_id = "run-native-analytics-0001";
    request.arm_id = "arm-native-analytics-0001";
    request.worker_id = "checkpoint-worker-0001";
    request.input_frame_key = "dataset:0:source:1:90000";
    request.stream_id = 0;
    request.frame_id = 1;
    request.transport_pts_ns = 90000;
    request.branch = "damage";
    request.decision.decision_id = "decision-native-0001";
    request.decision.decision_seq = 7;
    request.decision.selected_resource = "gpu";
    request.decision.selected_implementation_id = "gstreamer-damage-gpu-implementation-v1";
    request.decision.emitter_id = "gstreamer-damage-gpu-emitter-v1";
    request.decision.emitter_sha256 = policy_sha;
    request.deadline_monotonic_ns = static_cast<std::uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::steady_clock::now().time_since_epoch()).count()) + 60'000'000'000ULL;
    request.format = "BGR";
    request.width = 1;
    request.height = 1;
    request.stride = 4;
    request.preprocessing_contract_sha256 = contract_sha;
    request.raw_input_sha256 = raw_sha;
    const std::array<std::uint8_t, 4> payload{1, 2, 3, 4};
    vast::CheckpointAnalyticsExecutionResult result;
    try {
      result = client.execute(request, payload.data(), payload.size());
    } catch (const std::exception& client_error) {
      const std::string message = client_error.what();
      server.join();
      throw std::runtime_error("client failed before response: " + message);
    }
    server.join();
    if (server_error) {
      std::rethrow_exception(server_error);
    }
    if (result.decision_id != request.decision.decision_id ||
        result.selected_resource != "gpu" || result.device_api != "NVIDIA_CUDA" ||
        result.raw_input_sha256 != raw_sha || result.terminal_status != "completed" ||
        result.detector != "damage-gpu-detector-v1" || result.objects != 1 ||
        result.backend != "cuda-tensorrt:sidecar;device=NVIDIA CUDA:0" ||
        result.cuda_transfer_intervals.size() != 2 ||
        result.cuda_transfer_intervals[0].direction != "h2d" ||
        result.cuda_transfer_intervals[1].direction != "d2h") {
      throw std::runtime_error("validated analytics execution result drifted");
    }
  } catch (const std::exception& exc) {
    std::cerr << exc.what() << '\n';
    return 1;
  }
  return 0;
}
