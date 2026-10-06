#include "checkpoint_runtime_emitter.hpp"
#include "checkpoint_admission_transport.hpp"
#include <chrono>
#include <condition_variable>
#include <thread>
#include <iostream>
#include <dirent.h>
namespace {
template<typename E> auto bind(E& emitter,std::shared_ptr<vast::CheckpointIoDeadline> io,int)
    -> decltype(emitter.bind_lifecycle(io),void()) {emitter.bind_lifecycle(std::move(io));}
template<typename E> void bind(E&,std::shared_ptr<vast::CheckpointIoDeadline>,long) {}
int fd_count() {DIR* d=::opendir("/proc/self/fd");if(!d) throw std::runtime_error("no genuine FD observation");
  int n=0;while(::readdir(d)) ++n;::closedir(d);return n;}
bool actual_filled_event_pipe(bool abort) {
  const int before=fd_count();int fds[2];if(::pipe(fds)) throw std::runtime_error("pipe failed");
  vast::CheckpointIoDeadline::set_owned_nonblocking(fds[1]);std::array<char,4096> filler{};
  while(::write(fds[1],filler.data(),filler.size())>0) {}
  if(errno!=EAGAIN) throw std::runtime_error("actual event pipe did not fill");
  ::fcntl(fds[1],F_SETFL,::fcntl(fds[1],F_GETFL)&~O_NONBLOCK);
  const auto end=vast::CheckpointIoDeadline::monotonic_now_ns()+250'000'000ULL;
  auto io=std::make_shared<vast::CheckpointIoDeadline>(end);
  std::array<std::string,2> failures;std::mutex mutex;std::condition_variable changed;int done=0;
  bool bounded=false;
  {
    vast::CheckpointRuntimeEmitter emitter(std::to_string(fds[1]),"native-owner","run","gstreamer_custom","0");
    bind(emitter,io,0);
    auto call=[&](int index){
      try {emitter.emit("run:0:0",0,"dataset:0:sha:0:0","source_read","source","shared","source",{},1000);}
      catch(const std::exception& exc) {failures[index]=exc.what();}
      {std::lock_guard<std::mutex> lock(mutex);++done;}changed.notify_all();
    };
    std::thread first(call,0);std::this_thread::sleep_for(std::chrono::milliseconds(25));std::thread second(call,1);
    if(abort) {std::this_thread::sleep_for(std::chrono::milliseconds(25));io->abort();}
    {
      std::unique_lock<std::mutex> lock(mutex);bounded=changed.wait_until(lock,std::chrono::steady_clock::time_point(
          std::chrono::nanoseconds(end+750'000'000ULL)),[&]{return done==2;});
    }
    // No reader/peer close releases capacity until AFTER this observation.
    vast::CheckpointIoDeadline::set_owned_nonblocking(fds[0]);
    while(true) {{std::lock_guard<std::mutex> lock(mutex);if(done==2) break;}
      (void)::read(fds[0],filler.data(),filler.size());std::this_thread::sleep_for(std::chrono::milliseconds(1));}
    first.join();second.join();
  }
  ::close(fds[0]);::close(fds[1]);
  const auto reason=abort?"aborted":"deadline";
  if(!bounded||failures[0].find(reason)==std::string::npos||failures[1].find(reason)==std::string::npos||fd_count()!=before) {
    std::cerr<<"actual filled native event pipe/queued emitter exceeded owner bound: "<<failures[0]<<" / "<<failures[1]<<'\n';return false;}
  return true;
}
}
int main() {const bool deadline=actual_filled_event_pipe(false);const bool abort=actual_filled_event_pipe(true);return deadline&&abort?0:1;}
