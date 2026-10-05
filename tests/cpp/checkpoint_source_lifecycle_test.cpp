#define VAST_SOURCE_COORDINATOR_TESTING 1
#define main embedded_source_main
#include "../../deploy/native_gst_probe/checkpoint_source_coordinator.cpp"
#undef main
#include <dirent.h>
#include <filesystem>
#include <csignal>
#include <sys/ioctl.h>

namespace {
struct SourceCoordinatorTestAccess {
  static void start(SourceCoordinator& source) { source.wait_start(); }
  static void admit(SourceCoordinator& source, GstSample* sample) { source.admit_and_broadcast(sample); }
  static void stop(SourceCoordinator& source) { source.wait_stop(); }
  static bool latched(SourceCoordinator& source) { return source.stop_.load(); }
  static void start_senders(SourceCoordinator& source) { source.start_consumer_senders(); }
  static void close_senders(SourceCoordinator& source) { source.close_consumer_channels(false); }
  static void abort(SourceCoordinator& source) { source.io_->abort(); }
  static bool failed(SourceCoordinator& source) { return source.failed_.load(); }
  static int journal_fd(SourceCoordinator& source) { return source.study_fd_; }
  static void append_known_prefix(SourceCoordinator& source) {
    vast::CheckpointAdmissionFrame frame; frame.sequence = 1;
    frame.input_frame_key = "kpp:0:" + std::string(64, 'a') + ":0:0";
    frame.payload_sha256 = std::string(64, 'b');
    source.study_row("source_offered", frame);
  }
  static std::string sender_error(SourceCoordinator& source, const std::string& recipient) {
    for (auto& channel : source.consumers_) if (channel->consumer_id == recipient) {
      std::lock_guard<std::mutex> lock(channel->mutex); return channel->error;
    }
    throw std::runtime_error("fixture recipient is absent");
  }
  template<class T> static auto finish_impl(T& source, int)
      -> decltype(source.finish_study_journal(), void()) { source.finish_study_journal(); }
  // The real old source compiles, but its missing finalization cannot pass the
  // ownership/retirement assertions below. This is never a production fallback.
  template<class T> static void finish_impl(T&, long) {}
  static void finish(SourceCoordinator& source) { finish_impl(source, 0); }
};
int fd_count() {
  DIR* directory = ::opendir("/proc/self/fd");
  if (!directory) throw std::runtime_error("FD inspection failed");
  int count = 0; while (::readdir(directory)) ++count;
  ::closedir(directory); return count;
}
void env_fd(const char* key, int fd) { ::setenv(key, std::to_string(fd).c_str(), 1); }
struct SourceFixturePipes {
  std::array<std::array<int, 2>, 6> pipes{};
  SourceFixturePipes() {
    for (auto& pair : pipes) pair = {-1, -1};
    try {
      for (auto& pair : pipes) if (::pipe(pair.data()) != 0) throw std::runtime_error("fixture pipe failed");
    } catch (...) { close(); throw; }
    env_fd("VAST_CHECKPOINT_ADMISSION_EVENT_FD", pipes[0][1]);
    env_fd("VAST_CHECKPOINT_ADMISSION_ACK_FD", pipes[1][0]);
    env_fd("VAST_CHECKPOINT_CONTROL_FD", pipes[2][0]);
    env_fd("VAST_CHECKPOINT_STATUS_FD", pipes[3][1]);
    ::setenv("VAST_CHECKPOINT_ADMISSION_CONSUMER_FDS_JSON", ("{\"a-full\":" +
        std::to_string(pipes[4][1]) + ",\"b-partial\":" + std::to_string(pipes[5][1]) + "}").c_str(), 1);
    ::setenv("VAST_CHECKPOINT_WORKER_ID", "source-owner", 1);
    ::setenv("VAST_CHECKPOINT_RUN_ID", "source-real-journal", 1);
    ::setenv("VAST_CHECKPOINT_DATASET_ID", "kpp", 1);
    ::setenv("VAST_CHECKPOINT_SOURCE_SHA256", std::string(64, 'a').c_str(), 1);
    ::setenv("VAST_CHECKPOINT_STREAM_ID", "0", 1);
    ::setenv("VAST_CHECKPOINT_STARTUP_DEADLINE_MONOTONIC_NS", std::to_string(
        vast::CheckpointIoDeadline::monotonic_now_ns() + 3'000'000'000ULL).c_str(), 1);
  }
  void close() noexcept { for (auto& pair : pipes) for (int& fd : pair)
      if (fd >= 0) { ::close(fd); fd = -1; } }
  ~SourceFixturePipes() { close(); }
};
struct SourceFixtureDirectory {
  std::string path;
  SourceFixtureDirectory() {
    std::array<char, 64> name{};
    const std::string pattern = "/tmp/vast-source-journal-fixture-XXXXXX";
    std::copy(pattern.begin(), pattern.end(), name.begin());
    const char* actual = ::mkdtemp(name.data());
    if (!actual) throw std::runtime_error("fixture private directory failed");
    path = actual;
  }
  ~SourceFixtureDirectory() { std::error_code ignored; std::filesystem::remove_all(path, ignored); }
};
Args study_args(const std::string& journal) {
  Args args; args.dataset_id = "kpp"; args.source_sha256 = std::string(64, 'a');
  args.stream_id = 0; args.source_duration_ns = 33'333'333;
  args.playback_timestamp_scale = 15; args.replay = "finite";
  args.study_kind = "finite-component-study"; args.study_width = 1920; args.study_height = 1080;
  args.study_accounting_path = journal; return args;
}
std::uint64_t start_fixture(SourceCoordinator& source, SourceFixturePipes& fixture,
                            std::uint64_t drain_after_ms) {
  const auto common = vast::CheckpointIoDeadline::monotonic_now_ns() + 20'000'000ULL;
  const auto real = now_ms();
  write_exact(fixture.pipes[2][1], "1 START " + std::to_string(common) + " " +
      std::to_string(real) + " " + std::to_string(real + drain_after_ms / 2) + " " +
      std::to_string(real + drain_after_ms) + "\n");
  SourceCoordinatorTestAccess::start(source); return real + drain_after_ms;
}
std::string journal_text(const std::string& path) {
  std::ifstream stream(path); if (!stream) throw std::runtime_error("fixture journal read failed");
  return std::string(std::istreambuf_iterator<char>(stream), std::istreambuf_iterator<char>());
}
std::size_t event_count(const std::string& bytes, const std::string& event,
                        const std::string& recipient = "") {
  std::istringstream input(bytes); std::string line; std::size_t count = 0;
  while (std::getline(input, line)) if (line.find("\"type\":\"" + event + "\"") != std::string::npos &&
      (recipient.empty() || line.find("\"recipient_id\":\"" + recipient + "\"") != std::string::npos)) ++count;
  return count;
}
bool source_journal_ack_and_partial_fanout() {
  const int before = fd_count(); bool passed = false; std::string failure;
  {
    SourceFixtureDirectory directory; SourceFixturePipes fixture;
    const std::string path = directory.path + "/source.jsonl";
    SourceCoordinator source(study_args(path));
    std::thread admission, full_reader;
    GstSample* sample = nullptr;
    std::mutex mutex; std::condition_variable changed;
    bool admission_done = false, full_done = false, release_full_peer = false;
    std::string admission_error, reader_error;
    vast::CheckpointAdmissionFrame received;
    const vast::CheckpointIoDeadline reader_bound(vast::CheckpointIoDeadline::monotonic_now_ns() + 2'000'000'000ULL);
    try {
      // Keep the blocked recipient live. Fill its real pipe and free exactly
      // one page: the actual header/body prefix fits, the complete AU cannot.
      const long page = ::sysconf(_SC_PAGESIZE);
      if (page <= 0) throw std::runtime_error("fixture page size unavailable");
      vast::CheckpointIoDeadline::set_owned_nonblocking(fixture.pipes[5][1]);
      std::vector<std::uint8_t> filler(static_cast<std::size_t>(page), 0x5a);
      std::size_t filled = 0;
      while (true) {
        const ssize_t n = ::write(fixture.pipes[5][1], filler.data(), filler.size());
        if (n > 0) { filled += static_cast<std::size_t>(n); continue; }
        if (n < 0 && errno == EINTR) continue;
        if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) break;
        throw std::runtime_error("fixture actual pipe fill failed");
      }
      if (filled < static_cast<std::size_t>(page)) throw std::runtime_error("fixture pipe capacity is too small");
      std::size_t removed = 0;
      while (removed < filler.size()) {
        const ssize_t n = ::read(fixture.pipes[5][0], filler.data() + removed, filler.size() - removed);
        if (n <= 0) throw std::runtime_error("fixture free page failed");
        removed += static_cast<std::size_t>(n);
      }
      const std::size_t remaining_filler = filled - removed;
      const auto original_drain_ms = start_fixture(source, fixture, 650);
      SourceCoordinatorTestAccess::start_senders(source);
      // This is synthetic compressed data for transport/accounting only; no
      // decoder or physical recording is invoked by this source-entry fixture.
      // The non-page-aligned tail gives Linux's real nonblocking writer a
      // positive body append in the partially occupied final pipe page.
      std::vector<std::uint8_t> payload(32 * 1024 + 123, 0x65);
      payload[0] = payload[1] = payload[2] = 0; payload[3] = 1;
      GstBuffer* buffer = gst_buffer_new_allocate(nullptr, payload.size(), nullptr);
      gst_buffer_fill(buffer, 0, payload.data(), payload.size());
      GST_BUFFER_PTS(buffer) = GST_BUFFER_DTS(buffer) = 0; GST_BUFFER_DURATION(buffer) = 33'333'333;
      sample = gst_sample_new(buffer, nullptr, nullptr, nullptr); gst_buffer_unref(buffer);
      full_reader = std::thread([&] {
        try {
          if (!vast::CheckpointAdmissionTransport::read_frame(fixture.pipes[4][0], received, &reader_bound))
            throw std::runtime_error("fixture full recipient got premature EOF");
        } catch (const std::exception& exc) { reader_error = exc.what(); }
        std::unique_lock<std::mutex> lock(mutex); full_done = true; changed.notify_all();
        changed.wait(lock, [&] { return release_full_peer; });
      });
      admission = std::thread([&] {
        try { SourceCoordinatorTestAccess::admit(source, sample); }
        catch (const std::exception& exc) { admission_error = exc.what(); }
        { std::lock_guard<std::mutex> lock(mutex); admission_done = true; } changed.notify_all();
      });
      const auto actual_offer = read_line(fixture.pipes[0][0], &reader_bound);
      const auto before_ack = journal_text(path);
      bool is_still_waiting;
      { std::lock_guard<std::mutex> lock(mutex); is_still_waiting = !admission_done; }
      if (actual_offer.find("\"payload_size_bytes\":32891") == std::string::npos || !is_still_waiting ||
          event_count(before_ack, "source_offered") != 1 || event_count(before_ack, "source_admitted") != 0 ||
          event_count(before_ack, "source_ack") != 0 || event_count(before_ack, "fanout_enqueued") != 0 ||
          event_count(before_ack, "recipient_delivered") != 0)
        throw std::runtime_error("source journal fabricated admission/delivery before actual ACK");
      write_exact(fixture.pipes[1][1], "1 ACK 1\n");
      {
        std::unique_lock<std::mutex> lock(mutex);
        if (!changed.wait_for(lock, std::chrono::seconds(2), [&] { return admission_done && full_done; }))
          throw std::runtime_error("source real fanout fixture did not settle");
      }
      admission.join();
      gchar* checksum = g_compute_checksum_for_data(G_CHECKSUM_SHA256, payload.data(), payload.size());
      const std::string expected_sha = checksum ? checksum : ""; g_free(checksum);
      if (!admission_error.empty() || !reader_error.empty() || received.sequence != 1 || received.payload != payload ||
          expected_sha.empty() || received.payload_sha256 != expected_sha)
        throw std::runtime_error("full recipient failed to read original complete hashed AU");
      // The held blocked peer is never released to manufacture completion.
      // Joining actual sender threads must end at the same START/drain bound.
      SourceCoordinatorTestAccess::close_senders(source);
      if (now_ms() < original_drain_ms || !SourceCoordinatorTestAccess::failed(source) ||
          SourceCoordinatorTestAccess::sender_error(source, "b-partial").find("deadline") == std::string::npos)
        throw std::runtime_error("partial recipient did not fail at original source drain");
      int pending = 0;
      if (::ioctl(fixture.pipes[5][0], FIONREAD, &pending) != 0 || pending <= static_cast<int>(remaining_filler))
        throw std::runtime_error("blocked recipient did not retain a positive actual write prefix");
      std::vector<std::uint8_t> observed(static_cast<std::size_t>(pending)); std::size_t used = 0;
      while (used < observed.size()) {
        const ssize_t n = ::read(fixture.pipes[5][0], observed.data() + used, observed.size() - used);
        if (n <= 0) throw std::runtime_error("fixture retained prefix read failed"); used += static_cast<std::size_t>(n);
      }
      const std::string magic = "VASTAU01";
      const auto prefix_size = observed.size() - remaining_filler;
      const auto complete_size = 80 + received.admission_id.size() + received.input_frame_key.size() +
          received.payload_sha256.size() + payload.size();
      const auto header_and_text_size = complete_size - payload.size();
      if (prefix_size <= header_and_text_size || prefix_size >= complete_size ||
          !std::equal(magic.begin(), magic.end(), observed.begin() + remaining_filler))
        throw std::runtime_error("blocked recipient prefix is absent or falsely complete");
      const auto after = journal_text(path);
      const auto admitted = after.find("\"type\":\"source_admitted\"");
      const auto ack = after.find("\"type\":\"source_ack\"");
      const auto enqueue = after.find("\"type\":\"fanout_enqueued\"");
      if (event_count(after, "source_offered") != 1 || event_count(after, "source_admitted") != 1 ||
          event_count(after, "source_ack") != 1 || event_count(after, "fanout_enqueued", "a-full") != 1 ||
          event_count(after, "fanout_enqueued", "b-partial") != 1 ||
          event_count(after, "recipient_delivered", "a-full") != 1 ||
          event_count(after, "recipient_delivered", "b-partial") != 0 || !(admitted < ack && ack < enqueue))
        throw std::runtime_error("source journal does not preserve admitted prefix and distinguish queued/full delivery");
      std::cerr << "source journal actual ACK/full recipient plus blocked partial prefix=" << prefix_size
                << "/" << complete_size << " original-drain failure, no delivered row; threads retired\n";
      passed = true;
    } catch (const std::exception& exc) { failure = exc.what(); }
    // Always cancel callbacks before joining fixture peers or closing their
    // FDs; assertions cannot trigger a joinable-thread destructor or fake EOF.
    SourceCoordinatorTestAccess::abort(source);
    SourceCoordinatorTestAccess::close_senders(source);
    if (admission.joinable()) admission.join();
    { std::lock_guard<std::mutex> lock(mutex); release_full_peer = true; } changed.notify_all();
    if (full_reader.joinable()) full_reader.join();
    if (sample) gst_sample_unref(sample);
  }
  if (!passed || fd_count() != before) {
    std::cerr << "source journal fanout fixture failed: " << failure << " FD before=" << before
              << " after=" << fd_count() << '\n'; return false;
  }
  return true;
}
bool source_journal_finish_ownership_and_retirement() {
  const int before = fd_count(); bool passed = true;
  for (const std::string kind : {"normal", "path-replaced", "lost-fd"}) {
    SourceFixtureDirectory directory; SourceFixturePipes fixture;
    const auto path = directory.path + "/source.jsonl";
    SourceCoordinator source(study_args(path)); start_fixture(source, fixture, 2000);
    const int original = SourceCoordinatorTestAccess::journal_fd(source);
    // The actual owner append updates its byte counter; bypassing that owner
    // would correctly be refused by the exact final file-size custody guard.
    SourceCoordinatorTestAccess::append_known_prefix(source);
    const auto original_prefix = journal_text(path);
    if (kind == "path-replaced") {
      std::filesystem::rename(path, directory.path + "/original-held.jsonl");
      const int foreign = ::open(path.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
      if (foreign < 0) throw std::runtime_error("fixture foreign journal replacement failed");
      write_exact(foreign, "foreign\n"); ::close(foreign);
    } else if (kind == "lost-fd" && ::close(original) != 0) {
      throw std::runtime_error("fixture actual descriptor close failed");
    }
    SourceCoordinatorTestAccess::abort(source);  // Cleanup retains the original bound after cancellation.
    bool refused = false;
    try { SourceCoordinatorTestAccess::finish(source); }
    catch (const std::exception& exc) { refused = true; std::cerr << "source finish " << kind << ": " << exc.what() << '\n'; }
    const bool retired = SourceCoordinatorTestAccess::journal_fd(source) == -1;
    const bool physically_closed = ::fcntl(original, F_GETFD) == -1 && errno == EBADF;
    const bool expected = kind == "normal" ? !refused && retired && physically_closed : refused && retired && physically_closed;
    if (!expected) {
      std::cerr << "source actual finish boundary " << kind << " refused=" << refused << " retired=" << retired << '\n';
      passed = false;
    }
    if (kind == "path-replaced" && journal_text(path) != "foreign\n")
      throw std::runtime_error("source finish wrote or adopted the foreign replacement");
    if (journal_text(kind == "path-replaced" ? directory.path + "/original-held.jsonl" : path) != original_prefix)
      throw std::runtime_error("source finish changed the actual original owner prefix");
  }
  if (fd_count() != before) passed = false;
  return passed;
}
bool silent_ack_and_stop_retire() {
  const int before = fd_count();
  std::array<std::array<int, 2>, 5> pipes{};
  for (auto& fds : pipes) if (::pipe(fds.data()) != 0) throw std::runtime_error("pipe failed");
  env_fd("VAST_CHECKPOINT_ADMISSION_EVENT_FD", pipes[0][1]);
  env_fd("VAST_CHECKPOINT_ADMISSION_ACK_FD", pipes[1][0]);
  env_fd("VAST_CHECKPOINT_CONTROL_FD", pipes[2][0]);
  env_fd("VAST_CHECKPOINT_STATUS_FD", pipes[3][1]);
  ::setenv("VAST_CHECKPOINT_ADMISSION_CONSUMER_FDS_JSON",
      ("{\"recipient\":" + std::to_string(pipes[4][1]) + "}").c_str(), 1);
  ::setenv("VAST_CHECKPOINT_WORKER_ID", "source-owner", 1);
  ::setenv("VAST_CHECKPOINT_RUN_ID", "source-real-stop", 1);
  ::setenv("VAST_CHECKPOINT_DATASET_ID", "kpp", 1);
  ::setenv("VAST_CHECKPOINT_SOURCE_SHA256", std::string(64, 'a').c_str(), 1);
  ::setenv("VAST_CHECKPOINT_STREAM_ID", "0", 1);
  Args args; args.dataset_id="kpp"; args.source_sha256=std::string(64, 'a');
  args.stream_id=0; args.source_duration_ns=33'333'333; args.playback_timestamp_scale=30;
  bool stop_latched = false, settled = false;
  std::string error;
  {
    SourceCoordinator source(args);
    const auto common_start = vast::CheckpointIoDeadline::monotonic_now_ns()+20'000'000ULL;
    const auto start_real = now_ms();
    const auto stop_real = start_real+150;
    const auto drain_real = start_real+350;
    write_exact(pipes[2][1], "1 START " + std::to_string(common_start) + " " +
        std::to_string(start_real) + " " + std::to_string(stop_real) + " " + std::to_string(drain_real) + "\n");
    SourceCoordinatorTestAccess::start(source);
    GstBuffer* buffer=gst_buffer_new_allocate(nullptr, 7, nullptr);
    const std::array<std::uint8_t,7> nal{0,0,0,1,0x65,0x88,0x84};
    gst_buffer_fill(buffer,0,nal.data(),nal.size());
    GST_BUFFER_PTS(buffer)=0; GST_BUFFER_DTS(buffer)=0; GST_BUFFER_DURATION(buffer)=33'333'333;
    GstSample* sample=gst_sample_new(buffer,nullptr,nullptr,nullptr); gst_buffer_unref(buffer);
    std::mutex mutex; std::condition_variable changed; bool admission_done=false, stop_done=false;
    std::thread admission([&]{
      try { SourceCoordinatorTestAccess::admit(source,sample); }
      catch(const std::exception& exc) { error=exc.what(); }
      {std::lock_guard<std::mutex> lock(mutex); admission_done=true;} changed.notify_all();
    });
    const auto actual_offer=read_line(pipes[0][0]);
    if(actual_offer.find("\"sequence\":1")==std::string::npos) throw std::runtime_error("no actual original admission offer");
    write_exact(pipes[2][1],"1 STOP "+std::to_string(stop_real)+"\n");
    std::thread control([&]{ SourceCoordinatorTestAccess::stop(source);
      {std::lock_guard<std::mutex> lock(mutex); stop_done=true;} changed.notify_all(); });
    std::this_thread::sleep_for(std::chrono::milliseconds(50));
    stop_latched=SourceCoordinatorTestAccess::latched(source);
    {
      std::unique_lock<std::mutex> lock(mutex);
      settled=changed.wait_until(lock,std::chrono::steady_clock::time_point(
          std::chrono::nanoseconds(common_start+1'100'000'000ULL)),[&]{return admission_done&&stop_done;});
    }
    // Only after observing the original drain bound may the fixture release ACK.
    write_exact(pipes[1][1],"1 ACK 1\n");
    admission.join(); control.join(); gst_sample_unref(sample);
  }
  for(auto& fds:pipes) for(int fd:fds) ::close(fd);
  if(!stop_latched||!settled||error.find("deadline")==std::string::npos||fd_count()!=before) {
    std::cerr<<"actual source STOP latch/silent ACK exceeded original drain: latched="<<stop_latched
             <<" settled="<<settled<<" error="<<error<<'\n'; return false;
  }
  return true;
}
bool typed_finite_contract() {
  std::vector<std::string> words={"source", "--source-path", "/tmp/derived.mp4", "--dataset-id", "kpp",
      "--source-sha256", std::string(64,'a'), "--checkpoint-container", "mp4", "--checkpoint-codec", "h264",
      "--source-duration-ns", "14733333333", "--playback-timestamp-scale", "15", "--source-replay", "finite",
      "--logical-stream-id", "0", "--checkpoint-study-kind", "finite-component-study",
      "--checkpoint-study-width", "1920", "--checkpoint-study-height", "1080",
      "--checkpoint-study-accounting-path", "/tmp/owned-study-source.jsonl"};
  std::vector<char*> pointers; for(auto& word:words) pointers.push_back(word.data());
  try {
    const auto args=parse_args(static_cast<int>(pointers.size()),pointers.data());
    if(args.replay!="finite") return false;
    // A finite replay without the explicit validated study kind remains forbidden.
    pointers.resize(pointers.size()-8);
    try { (void)parse_args(static_cast<int>(pointers.size()),pointers.data()); }
    catch(const std::runtime_error&) { return true; }
  } catch(const std::exception& exc) { std::cerr<<"typed finite source unavailable: "<<exc.what()<<'\n'; }
  return false;
}
bool inventory_cli_is_genuinely_dispatched() {
  std::ifstream boot_file("/proc/sys/kernel/random/boot_id"); std::string boot;
  if(!std::getline(boot_file,boot)||boot.empty()) return false;
  const std::string time_namespace=vast::study::detail::actual_clock_domain_label();
  if(::setenv("VAST_CHECKPOINT_PREPARATION_CLOCK_BOOT_ID",boot.c_str(),1)!=0 ||
     ::setenv("VAST_CHECKPOINT_PREPARATION_CLOCK_TIME_NAMESPACE",time_namespace.c_str(),1)!=0) return false;
  std::vector<std::string> words={"source","--checkpoint-study-au-inventory",
      "/proc/this-vast-fixture-path-does-not-exist/derived.mp4","1920","1080",
      std::to_string(vast::CheckpointIoDeadline::monotonic_now_ns()+1'000'000'000ULL)};
  std::vector<char*> pointers;for(auto& word:words)pointers.push_back(word.data());
  std::ostringstream captured;auto* original=std::cerr.rdbuf(captured.rdbuf());
  const int code=embedded_source_main(pointers.size(),pointers.data());std::cerr.rdbuf(original);
  if(code!=1||captured.str().find("[study-inventory]")==std::string::npos ||
     captured.str().find("clock namespace proof missing or mismatched")!=std::string::npos) {
    std::cerr<<"source did not dispatch actual inventory ownership validation: "<<captured.str();return false;
  }
  return true;
}
}
int main(int argc,char** argv) {
  gst_init(&argc,&argv); std::signal(SIGPIPE,SIG_IGN);
  const bool bounded=silent_ack_and_stop_retire();
  const bool finite=typed_finite_contract();
  const bool inventory=inventory_cli_is_genuinely_dispatched();
  const bool journal=source_journal_ack_and_partial_fanout();
  const bool finish=source_journal_finish_ownership_and_retirement();
  return bounded&&finite&&inventory&&journal&&finish?0:1;
}
