#define VAST_NATIVE_PROBE_TESTING 1
#define main embedded_native_main
#include "../../deploy/native_gst_probe/vast_native_gst_probe.cpp"
#undef main
#include <filesystem>
struct NativeProbeRuntimeTestAccess {
  static std::pair<std::string,std::string> graphs(NativeProbeRuntime& runtime) {
    runtime.args_.checkpoint_codec="h264";runtime.args_.checkpoint_study_kind="finite-component-study";
    runtime.args_.checkpoint_study_width=1920;runtime.args_.checkpoint_study_height=1080;
    runtime.args_.checkpoint_branch="damage";runtime.checkpoint_branches_={"damage","vehicle_type","plate_number","foreign_object"};
    runtime.checkpoint_allowed_decoder_factories_={"identity"};
    return {runtime.checkpoint_branch_pipeline(0),runtime.checkpoint_shared_pipeline(0)};
  }
};
int main(int argc,char** argv) {
  gst_init(&argc,&argv);
  const auto path=fs::temp_directory_path()/("vast-study-prefix-"+std::to_string(::getpid()));fs::create_directory(path);
  bool valid=true;
  {
    Args args;args.role="edge";args.output_dir=path.string();args.dataset_streams_json="[]";args.system="gstreamer_custom";
    NativeProbeRuntime runtime(args);const auto graphs=NativeProbeRuntimeTestAccess::graphs(runtime);
    for(const auto& graph:{graphs.first,graphs.second}) {
      const std::string marker=" name=checkpoint_nvdec0 ! ";
      const auto start=graph.find(marker);const auto end=graph.find(" ! queue name=checkpoint_decode0");
      if(start==std::string::npos||end==std::string::npos) {valid=false;continue;}
      const std::string prefix=graph.substr(start+marker.size(),end-start-marker.size());
      if(prefix.find("format=(string)NV12")==std::string::npos||prefix.find("format=(string)RGB")==std::string::npos||
         prefix.find("width=(int)1920")==std::string::npos||prefix.find("height=(int)1080")==std::string::npos||
         prefix.find("framerate=(fraction)30/1")==std::string::npos||prefix.find("chroma-site=(string)mpeg2")==std::string::npos||
         prefix.find("n-threads=1 dither=none chroma-resampler=linear chroma-mode=full matrix-mode=full gamma-mode=none primaries-mode=none")==std::string::npos||
         graph.find("video/x-raw,format=BGR,width=640,height=360")==std::string::npos) valid=false;
      GError* error=nullptr;GstElement* bin=gst_parse_bin_from_description(("identity ! "+prefix+" ! identity").c_str(),TRUE,&error);
      if(!bin||error) valid=false;if(bin)gst_object_unref(bin);if(error)g_error_free(error);
    }
  }
  std::vector<std::string> words={"native","--checkpoint-study-prefix-description","1920","1080"};
  std::vector<char*> pointers;for(auto& word:words)pointers.push_back(word.data());
  std::ostringstream output;auto* previous=std::cout.rdbuf(output.rdbuf());
  const int rc=embedded_native_main(pointers.size(),pointers.data());std::cout.rdbuf(previous);
  if(rc!=0||output.str().find("\"converter_config\"")==std::string::npos)valid=false;
  fs::remove_all(path);if(!valid)std::cerr<<"native study graph/CLI does not use actual fixed common original-geometry colour prefix\n";
  return valid?0:1;
}
