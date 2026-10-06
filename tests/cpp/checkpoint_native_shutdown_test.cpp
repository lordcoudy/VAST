#define VAST_NATIVE_PROBE_TESTING 1
#define main embedded_native_main
#include "../../deploy/native_gst_probe/vast_native_gst_probe.cpp"
#undef main
#include <dirent.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <csignal>

struct NativeProbeRuntimeTestAccess {
  template<typename Journal> static auto finish(Journal& journal,int)->decltype(journal.finish(),void()) {journal.finish();}
  template<typename Journal> static void finish(Journal&,long) {}
  static bool journal_finalization(const fs::path& root) {
    const int before=[] {DIR* d=::opendir("/proc/self/fd");int n=0;while(::readdir(d))++n;::closedir(d);return n;}();
    bool negative=true;
    for(int mode=0;mode<3;++mode) {
      const auto path=root/("original-journal-"+std::to_string(mode));
      NativeProbeRuntime::StudyJournal journal;journal.open_new(path.string());
      vast::CheckpointIoDeadline io(vast::CheckpointIoDeadline::monotonic_now_ns()+1'000'000'000ULL);
      journal.append("{\"actual\":true}\n",io);
      if(mode==1) {fs::rename(path,path.string()+".held");std::ofstream foreign(path);foreign<<"{\"actual\":true}\n";}
      if(mode==2) ::close(journal.fd); // Real lost owned descriptor, no fake close return.
      bool refused=false;try{finish(journal,0);}catch(const std::exception&){refused=true;}
      if(mode==0) negative=negative&&!refused&&journal.fd==-1;
      else negative=negative&&refused;
    }
    const int after=[] {DIR* d=::opendir("/proc/self/fd");int n=0;while(::readdir(d))++n;::closedir(d);return n;}();
    return negative&&before==after;
  }
  static void attach(NativeProbeRuntime& runtime, GstElement* pipeline, int socket) {
    runtime.pipelines_.push_back(pipeline);
    runtime.checkpoint_analytics_execution_client_ =
        std::make_unique<vast::CheckpointAnalyticsExecutionClient>(socket);
  }
  static void stop(NativeProbeRuntime& runtime) { runtime.stop_pipelines(); }
  static void start_owned_readers(NativeProbeRuntime& runtime, int control, int status, int data,
                                  GstElement* pipeline) {
    runtime.checkpoint_control_fd_=control; runtime.checkpoint_status_fd_=status;
    runtime.checkpoint_data_fd_=data; runtime.pipelines_.push_back(pipeline);
    runtime.checkpoint_io_=std::make_shared<vast::CheckpointIoDeadline>(
        vast::CheckpointIoDeadline::monotonic_now_ns()+5'000'000'000ULL);
    runtime.checkpoint_control_thread_=std::thread([&runtime]{runtime.wait_for_checkpoint_stop();});
    runtime.checkpoint_data_thread_=std::thread([&runtime]{runtime.receive_checkpoint_access_units();});
    runtime.checkpoint_appsrc_thread_=std::thread([&runtime]{runtime.feed_checkpoint_access_units();});
  }
  static void execute(NativeProbeRuntime& runtime) {
    vast::CheckpointAnalyticsExecutionRequest request;
    request.request_id=std::string(64,'1'); request.run_id="shutdown-run";
    request.arm_id=std::string(64,'2'); request.worker_id="native-owner";
    request.input_frame_key="kpp:0:"+std::string(64,'a')+":0:0";
    request.stream_id=0; request.frame_id=0; request.transport_pts_ns=0; request.branch="damage";
    request.decision={"decision-shutdown",1,"cpu","implementation","emitter",std::string(64,'e')};
    request.deadline_monotonic_ns=vast::CheckpointIoDeadline::monotonic_now_ns()+5'000'000'000ULL;
    request.format="RGB"; request.width=1; request.height=1; request.stride=3;
    request.preprocessing_contract_sha256=std::string(64,'f');
    const std::array<std::uint8_t,3> pixels{4,5,6};
    request.raw_input_sha256=NativeProbeRuntime::sha256_raw_bytes(std::vector<std::uint8_t>(pixels.begin(),pixels.end()));
    (void)runtime.checkpoint_analytics_execution_client_->execute(request,pixels.data(),pixels.size());
  }
};
namespace {
int fd_count() { DIR* directory=::opendir("/proc/self/fd"); if(!directory) throw std::runtime_error("no FD view");
  int count=0; while(::readdir(directory)) ++count; ::closedir(directory); return count; }
struct CallbackState { NativeProbeRuntime* runtime; std::string failure; std::atomic<bool> retired{false}; };
GstPadProbeReturn actual_callback(GstPad*,GstPadProbeInfo*,gpointer raw) {
  auto* state=static_cast<CallbackState*>(raw);
  try { NativeProbeRuntimeTestAccess::execute(*state->runtime); }
  catch(const std::exception& exc) {state->failure=exc.what();}
  state->retired.store(true); return GST_PAD_PROBE_DROP;
}
bool native_null_retires_blocked_callback() {
  const int before=fd_count();
  int sockets[2]; if(::socketpair(AF_UNIX,SOCK_SEQPACKET,0,sockets)) throw std::runtime_error("socket pair failed");
  const auto path=fs::temp_directory_path()/("vast-native-retirement-"+std::to_string(::getpid()));
  fs::create_directory(path);
  bool finished=false, retired_before_release=false, valid_payload=false;
  std::string failure;
  {
    Args args; args.system="gstreamer_custom"; args.role="edge"; args.run_id="shutdown-run";
    args.output_dir=path.string(); args.detector="opaque"; args.backend="fixture";
    args.dataset_streams_json="[]"; args.executable_path="/proc/self/exe";
    NativeProbeRuntime runtime(args);
    GError* error=nullptr;
    GstElement* pipeline=gst_parse_launch("fakesrc num-buffers=1 ! identity name=owner_callback ! fakesink sync=false",&error);
    if(error||!pipeline) throw std::runtime_error("real software GStreamer graph unavailable");
    NativeProbeRuntimeTestAccess::attach(runtime,pipeline,sockets[0]); sockets[0]=-1;
    CallbackState state{&runtime};
    GstElement* identity=gst_bin_get_by_name(GST_BIN(pipeline),"owner_callback");
    GstPad* pad=gst_element_get_static_pad(identity,"src");
    gst_pad_add_probe(pad,GST_PAD_PROBE_TYPE_BUFFER,actual_callback,&state,nullptr);
    gst_object_unref(pad); gst_object_unref(identity);
    gst_element_set_state(pipeline,GST_STATE_PLAYING);
    std::array<char,65536> text{}; std::array<char,CMSG_SPACE(sizeof(int))> control{};
    iovec iov{text.data(),text.size()}; msghdr message{}; message.msg_iov=&iov;message.msg_iovlen=1;
    message.msg_control=control.data(); message.msg_controllen=control.size();
    const ssize_t received=::recvmsg(sockets[1],&message,0);
    if(received<=0) throw std::runtime_error("actual streaming callback sent no request");
    const auto* ancillary=CMSG_FIRSTHDR(&message); int received_fd=-1;
    if(ancillary&&ancillary->cmsg_level==SOL_SOCKET&&ancillary->cmsg_type==SCM_RIGHTS) std::memcpy(&received_fd,CMSG_DATA(ancillary),sizeof(int));
    if(received_fd>=0) {
      std::array<std::uint8_t,3> pixels{};
      const int seals=::fcntl(received_fd,F_GET_SEALS);
      valid_payload=::pread(received_fd,pixels.data(),pixels.size(),0)==3&&pixels==std::array<std::uint8_t,3>{4,5,6}&&
          (seals&(F_SEAL_WRITE|F_SEAL_GROW|F_SEAL_SHRINK|F_SEAL_SEAL))==(F_SEAL_WRITE|F_SEAL_GROW|F_SEAL_SHRINK|F_SEAL_SEAL);
      ::close(received_fd);
    }
    std::mutex mutex; std::condition_variable changed;
    std::thread shutdown([&]{NativeProbeRuntimeTestAccess::stop(runtime);
      {std::lock_guard<std::mutex> lock(mutex);finished=true;} changed.notify_all();});
    {
      std::unique_lock<std::mutex> lock(mutex);
      retired_before_release=changed.wait_for(lock,std::chrono::seconds(1),[&]{return finished;});
    }
    // Peer remains alive until AFTER observing real production GST_STATE_NULL.
    ::close(sockets[1]); sockets[1]=-1;
    shutdown.join(); failure=state.failure;
    retired_before_release=retired_before_release&&state.retired.load();
  }
  for(int socket:sockets) if(socket>=0) ::close(socket);
  fs::remove_all(path);
  if(!valid_payload||!retired_before_release||failure.find("aborted")==std::string::npos||fd_count()!=before) {
    std::cerr<<"real GST_STATE_NULL failed to abort and retire callback before peer release: "<<failure
             <<" valid_payload="<<valid_payload<<" retired="<<retired_before_release<<'\n';return false;
  }
  return true;
}
bool native_typed_study_flags() {
  std::vector<std::string> words={"native", "--checkpoint-study-kind", "finite-component-study",
      "--checkpoint-study-width", "1920", "--checkpoint-study-height", "1080",
      "--checkpoint-study-waits-path", "/tmp/owned-native-waits.jsonl", "--checkpoint-study-accounting-path",
      "/tmp/owned-native-receives.jsonl", "--checkpoint-analytics-client-mode", "branch", "--source-replay", "finite"};
  std::vector<char*> pointers; for(auto& word:words) pointers.push_back(word.data());
  try {
    if(parse_args(static_cast<int>(pointers.size()),pointers.data()).source_replay!="finite")return false;
    for(const std::string& raw:{"1920tail","1920.0","-1920","+1920"," 1920"}) {
      words[4]=raw;pointers[4]=words[4].data();
      bool refused=false;try{(void)parse_args(pointers.size(),pointers.data());}catch(const std::exception&){refused=true;}
      if(!refused){std::cerr<<"native accepted noncanonical study geometry: "<<raw<<'\n';return false;}
    }
    return true;
  }
  catch(const std::exception& exc) {std::cerr<<"native typed study unavailable: "<<exc.what()<<'\n';return false;}
}
bool actual_exception_retirement() {
  const pid_t child=::fork(); if(child<0) throw std::runtime_error("retirement fixture fork failed");
  if(child==0) {
    std::array<std::array<int,2>,3> pipes;
    for(auto& ends:pipes) if(::pipe(ends.data())) _exit(10);
    const int before=fd_count();
    const auto path=fs::temp_directory_path()/("vast-native-exception-"+std::to_string(::getpid()));
    fs::create_directory(path);
    {
      Args args;args.role="edge";args.system="gstreamer_custom";args.output_dir=path.string();
      args.detector="opaque";args.backend="fixture";args.dataset_streams_json="[]";
      NativeProbeRuntime runtime(args);
      GError* error=nullptr;
      GstElement* pipeline=gst_parse_launch("appsrc name=checkpoint_appsrc0 ! fakesink sync=false",&error);
      if(!pipeline||error) _exit(11);
      NativeProbeRuntimeTestAccess::start_owned_readers(runtime,::dup(pipes[0][0]),::dup(pipes[1][1]),
                                                       ::dup(pipes[2][0]),pipeline);
      // The original live writers remain open; no peer EOF releases readers.
      std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }
    const bool closed=fd_count()==before;
    for(auto& ends:pipes) for(int fd:ends) ::close(fd);
    fs::remove_all(path); _exit(closed?0:12);
  }
  int status=0; bool reaped=false;
  const auto observed_end=std::chrono::steady_clock::now()+std::chrono::seconds(1);
  while(std::chrono::steady_clock::now()<observed_end) {
    if(::waitpid(child,&status,WNOHANG)==child) {reaped=true;break;}
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
  }
  if(!reaped) {::kill(child,SIGKILL);::waitpid(child,&status,0);}
  if(!reaped||!WIFEXITED(status)||WEXITSTATUS(status)!=0) {
    std::cerr<<"actual native exception destructor did not join/close owned readers before bound, status="<<status<<'\n';return false;
  }
  return true;
}
}
int main(int argc,char** argv) {gst_init(&argc,&argv); const bool bounded=native_null_retires_blocked_callback();
  const bool typed=native_typed_study_flags();const bool retirement=actual_exception_retirement();
  const auto path=fs::temp_directory_path()/("vast-native-journal-close-"+std::to_string(::getpid()));fs::create_directory(path);
  const bool journals=NativeProbeRuntimeTestAccess::journal_finalization(path);fs::remove_all(path);
  if(!journals)std::cerr<<"actual journal final-close/path-rebind/lost-FD failure was not checked before success\n";
  return bounded&&typed&&retirement&&journals?0:1;}
