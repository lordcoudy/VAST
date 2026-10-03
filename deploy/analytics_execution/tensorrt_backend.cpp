#include <NvInfer.h>
#include <cuda_runtime_api.h>
#include <openssl/sha.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <fstream>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

constexpr std::uint64_t kMaximumTensorBytes = 67'108'864;
constexpr std::size_t kMaximumRank = 8;

class Logger final : public nvinfer1::ILogger {
 public:
  void log(Severity severity, const char* message) noexcept override {
    if (severity <= Severity::kERROR && message != nullptr) {
      std::fprintf(stderr, "TensorRT: %s\n", message);
    }
  }
};

Logger g_logger;

void set_error(char* target, std::size_t capacity, const std::string& message) noexcept {
  if (target == nullptr || capacity == 0) {
    return;
  }
  const std::size_t copied = std::min(capacity - 1, message.size());
  std::memcpy(target, message.data(), copied);
  target[copied] = '\0';
}

void check_cuda(cudaError_t status, const char* operation) {
  if (status != cudaSuccess) {
    throw std::runtime_error(std::string(operation) + ": " + cudaGetErrorString(status));
  }
}

std::uint64_t monotonic_ns() {
  timespec value{};
  if (clock_gettime(CLOCK_MONOTONIC, &value) != 0 || value.tv_sec < 0 ||
      value.tv_nsec < 0) {
    throw std::runtime_error("clock_gettime CLOCK_MONOTONIC failed");
  }
  return static_cast<std::uint64_t>(value.tv_sec) * 1'000'000'000ULL +
      static_cast<std::uint64_t>(value.tv_nsec);
}

std::uint64_t cuda_event_elapsed_ns(
    cudaEvent_t start, cudaEvent_t end, const char* operation) {
  float elapsed_ms = 0.0F;
  check_cuda(cudaEventElapsedTime(&elapsed_ms, start, end), operation);
  if (!std::isfinite(elapsed_ms) || elapsed_ms <= 0.0F) {
    throw std::runtime_error(std::string(operation) +
        ": CUDA event elapsed time is not positive");
  }
  const double elapsed_ns = static_cast<double>(elapsed_ms) * 1'000'000.0;
  if (elapsed_ns > static_cast<double>(std::numeric_limits<std::uint64_t>::max())) {
    throw std::runtime_error(std::string(operation) +
        ": CUDA event elapsed time exceeds uint64");
  }
  const auto rounded = static_cast<std::uint64_t>(std::llround(elapsed_ns));
  if (rounded == 0) {
    throw std::runtime_error(std::string(operation) +
        ": CUDA event elapsed time rounded to zero");
  }
  return rounded;
}

std::vector<std::uint8_t> read_file(const char* path) {
  if (path == nullptr || *path == '\0') {
    throw std::runtime_error("engine path is empty");
  }
  std::ifstream input(path, std::ios::binary | std::ios::ate);
  if (!input) {
    throw std::runtime_error("cannot open the immutable TensorRT engine");
  }
  const std::streamoff end = input.tellg();
  if (end <= 0 || static_cast<unsigned long long>(end) > std::numeric_limits<std::size_t>::max()) {
    throw std::runtime_error("TensorRT engine size is invalid");
  }
  std::vector<std::uint8_t> bytes(static_cast<std::size_t>(end));
  input.seekg(0, std::ios::beg);
  if (!input.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()))) {
    throw std::runtime_error("cannot read the immutable TensorRT engine");
  }
  return bytes;
}

std::string sha256(const std::vector<std::uint8_t>& bytes) {
  std::array<unsigned char, SHA256_DIGEST_LENGTH> digest{};
  SHA256_CTX context;
  if (SHA256_Init(&context) != 1 ||
      SHA256_Update(&context, bytes.data(), bytes.size()) != 1 ||
      SHA256_Final(digest.data(), &context) != 1) {
    throw std::runtime_error("cannot hash the immutable TensorRT engine");
  }
  static constexpr char kHex[] = "0123456789abcdef";
  std::string result;
  result.resize(digest.size() * 2);
  for (std::size_t index = 0; index < digest.size(); ++index) {
    result[index * 2] = kHex[digest[index] >> 4];
    result[index * 2 + 1] = kHex[digest[index] & 0x0f];
  }
  return result;
}

std::string gpu_uuid(int device_index) {
  cudaDeviceProp properties{};
  check_cuda(cudaGetDeviceProperties(&properties, device_index), "cudaGetDeviceProperties");
  const auto* value = reinterpret_cast<const unsigned char*>(properties.uuid.bytes);
  char text[41]{};
  const int written = std::snprintf(
      text,
      sizeof(text),
      "%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",
      value[0], value[1], value[2], value[3], value[4], value[5], value[6], value[7],
      value[8], value[9], value[10], value[11], value[12], value[13], value[14], value[15]);
  if (written != 36) {
    throw std::runtime_error("cannot format the NVIDIA GPU UUID");
  }
  return std::string("GPU-") + text;
}

std::uint64_t checked_product(const nvinfer1::Dims& dimensions) {
  if (dimensions.nbDims <= 0 || dimensions.nbDims > static_cast<int>(kMaximumRank)) {
    throw std::runtime_error("TensorRT tensor rank is invalid");
  }
  std::uint64_t value = 1;
  for (int index = 0; index < dimensions.nbDims; ++index) {
    const int dimension = dimensions.d[index];
    if (dimension <= 0 || value > kMaximumTensorBytes / static_cast<std::uint64_t>(dimension)) {
      throw std::runtime_error("TensorRT requires a static bounded tensor shape");
    }
    value *= static_cast<std::uint64_t>(dimension);
  }
  return value;
}

struct TypeInfo {
  int code = -1;
  std::uint64_t bytes = 0;
};

TypeInfo type_info(nvinfer1::DataType type) {
  switch (type) {
    case nvinfer1::DataType::kFLOAT:
      return {2, 4};
    case nvinfer1::DataType::kHALF:
      return {1, 2};
    case nvinfer1::DataType::kUINT8:
      return {0, 1};
    default:
      throw std::runtime_error("TensorRT tensor dtype is outside the worker protocol");
  }
}

struct TensorBinding {
  std::string name;
  nvinfer1::Dims dimensions{};
  int dtype_code = -1;
  std::uint64_t bytes = 0;
  void* device = nullptr;
};

struct Session {
  nvinfer1::IRuntime* runtime = nullptr;
  nvinfer1::ICudaEngine* engine = nullptr;
  nvinfer1::IExecutionContext* context = nullptr;
  cudaStream_t stream = nullptr;
  cudaEvent_t h2d_start_event = nullptr;
  cudaEvent_t h2d_end_event = nullptr;
  cudaEvent_t d2h_start_event = nullptr;
  cudaEvent_t d2h_end_event = nullptr;
  TensorBinding input;
  std::vector<TensorBinding> outputs;
  std::uint64_t allocation_bytes = 0;
  int device_index = 0;

  ~Session() {
    if (stream != nullptr) {
      cudaStreamSynchronize(stream);
    }
    if (input.device != nullptr) {
      cudaFree(input.device);
    }
    for (auto& output : outputs) {
      if (output.device != nullptr) {
        cudaFree(output.device);
      }
    }
    if (h2d_start_event != nullptr) {
      cudaEventDestroy(h2d_start_event);
    }
    if (h2d_end_event != nullptr) {
      cudaEventDestroy(h2d_end_event);
    }
    if (d2h_start_event != nullptr) {
      cudaEventDestroy(d2h_start_event);
    }
    if (d2h_end_event != nullptr) {
      cudaEventDestroy(d2h_end_event);
    }
    if (stream != nullptr) {
      cudaStreamDestroy(stream);
    }
    delete context;
    delete engine;
    delete runtime;
  }
};

TensorBinding inspect_tensor(
    nvinfer1::ICudaEngine& engine,
    nvinfer1::IExecutionContext& context,
    const char* name) {
  if (name == nullptr || *name == '\0') {
    throw std::runtime_error("TensorRT engine contains an unnamed tensor");
  }
  TensorBinding binding;
  binding.name = name;
  binding.dimensions = context.getTensorShape(name);
  const TypeInfo type = type_info(engine.getTensorDataType(name));
  binding.dtype_code = type.code;
  const std::uint64_t elements = checked_product(binding.dimensions);
  if (elements > kMaximumTensorBytes / type.bytes) {
    throw std::runtime_error("TensorRT tensor exceeds the bounded worker maximum");
  }
  binding.bytes = elements * type.bytes;
  check_cuda(cudaMalloc(&binding.device, static_cast<std::size_t>(binding.bytes)), "cudaMalloc");
  if (!context.setTensorAddress(binding.name.c_str(), binding.device)) {
    cudaFree(binding.device);
    binding.device = nullptr;
    throw std::runtime_error("TensorRT refused the tensor device address");
  }
  return binding;
}

std::unique_ptr<Session> create_session(
    const char* engine_path,
    const char* expected_sha256,
    int device_index) {
  if (expected_sha256 == nullptr || std::strlen(expected_sha256) != 64) {
    throw std::runtime_error("expected TensorRT engine SHA-256 is invalid");
  }
  check_cuda(cudaSetDevice(device_index), "cudaSetDevice");
  check_cuda(cudaFree(nullptr), "CUDA context initialization");
  const std::vector<std::uint8_t> engine_bytes = read_file(engine_path);
  if (sha256(engine_bytes) != expected_sha256) {
    throw std::runtime_error("TensorRT engine SHA-256 differs from the authoritative artifact");
  }
  auto session = std::make_unique<Session>();
  session->device_index = device_index;
  session->runtime = nvinfer1::createInferRuntime(g_logger);
  if (session->runtime == nullptr) {
    throw std::runtime_error("cannot create TensorRT runtime");
  }
  session->engine = session->runtime->deserializeCudaEngine(engine_bytes.data(), engine_bytes.size());
  if (session->engine == nullptr) {
    throw std::runtime_error("cannot deserialize the immutable TensorRT engine");
  }
  session->context = session->engine->createExecutionContext();
  if (session->context == nullptr) {
    throw std::runtime_error("cannot create TensorRT execution context");
  }
  check_cuda(cudaStreamCreateWithFlags(&session->stream, cudaStreamNonBlocking), "cudaStreamCreateWithFlags");
  check_cuda(cudaEventCreateWithFlags(&session->h2d_start_event, cudaEventDefault),
             "cudaEventCreateWithFlags H2D start");
  check_cuda(cudaEventCreateWithFlags(&session->h2d_end_event, cudaEventDefault),
             "cudaEventCreateWithFlags H2D end");
  check_cuda(cudaEventCreateWithFlags(&session->d2h_start_event, cudaEventDefault),
             "cudaEventCreateWithFlags D2H start");
  check_cuda(cudaEventCreateWithFlags(&session->d2h_end_event, cudaEventDefault),
             "cudaEventCreateWithFlags D2H end");
  const int count = session->engine->getNbIOTensors();
  if (count < 2 || count > 65) {
    throw std::runtime_error("TensorRT engine I/O tensor count is invalid");
  }
  bool found_input = false;
  for (int index = 0; index < count; ++index) {
    const char* name = session->engine->getIOTensorName(index);
    const auto mode = session->engine->getTensorIOMode(name);
    TensorBinding binding = inspect_tensor(*session->engine, *session->context, name);
    session->allocation_bytes += binding.bytes;
    if (mode == nvinfer1::TensorIOMode::kINPUT) {
      if (found_input) {
        throw std::runtime_error("TensorRT worker supports exactly one input tensor");
      }
      session->input = std::move(binding);
      found_input = true;
    } else if (mode == nvinfer1::TensorIOMode::kOUTPUT) {
      session->outputs.push_back(std::move(binding));
    } else {
      throw std::runtime_error("TensorRT tensor I/O mode is invalid");
    }
  }
  if (!found_input || session->outputs.empty() || session->allocation_bytes == 0) {
    throw std::runtime_error("TensorRT engine lacks bounded input/output bindings");
  }
  return session;
}

TensorBinding& select_tensor(Session& session, int index) {
  if (index == -1) {
    return session.input;
  }
  if (index < 0 || static_cast<std::size_t>(index) >= session.outputs.size()) {
    throw std::runtime_error("TensorRT output index is invalid");
  }
  return session.outputs[static_cast<std::size_t>(index)];
}

const char* runtime_version() {
  static const std::string value = std::to_string(NV_TENSORRT_MAJOR) + "." +
      std::to_string(NV_TENSORRT_MINOR) + "." + std::to_string(NV_TENSORRT_PATCH) + "." +
      std::to_string(NV_TENSORRT_BUILD);
  return value.c_str();
}

}  // namespace

extern "C" {

struct VastCudaTransferTiming {
  std::uint64_t h2d_host_start_monotonic_ns;
  std::uint64_t h2d_host_end_monotonic_ns;
  std::uint64_t h2d_device_elapsed_ns;
  std::uint64_t d2h_host_start_monotonic_ns;
  std::uint64_t d2h_host_end_monotonic_ns;
  std::uint64_t d2h_device_elapsed_ns;
};

const char* vast_trt_runtime_version() noexcept {
  return runtime_version();
}

int vast_trt_probe(
    int device_index,
    char* uuid,
    std::size_t uuid_capacity,
    char* error,
    std::size_t error_capacity) noexcept {
  try {
    check_cuda(cudaSetDevice(device_index), "cudaSetDevice");
    check_cuda(cudaFree(nullptr), "CUDA context initialization");
    const std::string identity = gpu_uuid(device_index);
    if (uuid == nullptr || uuid_capacity <= identity.size()) {
      throw std::runtime_error("GPU UUID output buffer is too small");
    }
    std::memcpy(uuid, identity.data(), identity.size());
    uuid[identity.size()] = '\0';
    nvinfer1::IRuntime* runtime = nvinfer1::createInferRuntime(g_logger);
    if (runtime == nullptr) {
      throw std::runtime_error("cannot create TensorRT runtime");
    }
    delete runtime;
    return 0;
  } catch (const std::exception& exception) {
    set_error(error, error_capacity, exception.what());
    return 1;
  }
}

int vast_trt_create(
    const char* engine_path,
    const char* expected_sha256,
    int device_index,
    void** output_session,
    char* uuid,
    std::size_t uuid_capacity,
    char* error,
    std::size_t error_capacity) noexcept {
  try {
    if (output_session == nullptr) {
      throw std::runtime_error("TensorRT output session pointer is null");
    }
    *output_session = nullptr;
    std::unique_ptr<Session> session = create_session(engine_path, expected_sha256, device_index);
    const std::string identity = gpu_uuid(device_index);
    if (uuid == nullptr || uuid_capacity <= identity.size()) {
      throw std::runtime_error("GPU UUID output buffer is too small");
    }
    std::memcpy(uuid, identity.data(), identity.size());
    uuid[identity.size()] = '\0';
    *output_session = session.release();
    return 0;
  } catch (const std::exception& exception) {
    set_error(error, error_capacity, exception.what());
    return 1;
  }
}

void vast_trt_destroy(void* opaque) noexcept {
  delete static_cast<Session*>(opaque);
}

int vast_trt_output_count(void* opaque) noexcept {
  const auto* session = static_cast<Session*>(opaque);
  if (session == nullptr || session->outputs.size() > static_cast<std::size_t>(std::numeric_limits<int>::max())) {
    return -1;
  }
  return static_cast<int>(session->outputs.size());
}

int vast_trt_tensor_info(
    void* opaque,
    int index,
    char* name,
    std::size_t name_capacity,
    int* dtype_code,
    std::int64_t* dimensions,
    std::size_t dimensions_capacity,
    std::size_t* rank,
    std::uint64_t* byte_length,
    char* error,
    std::size_t error_capacity) noexcept {
  try {
    auto* session = static_cast<Session*>(opaque);
    if (session == nullptr || dtype_code == nullptr || dimensions == nullptr || rank == nullptr || byte_length == nullptr) {
      throw std::runtime_error("TensorRT tensor metadata output pointer is null");
    }
    TensorBinding& tensor = select_tensor(*session, index);
    if (name == nullptr || name_capacity <= tensor.name.size()) {
      throw std::runtime_error("TensorRT tensor name output buffer is too small");
    }
    const std::size_t tensor_rank = static_cast<std::size_t>(tensor.dimensions.nbDims);
    if (dimensions_capacity < tensor_rank) {
      throw std::runtime_error("TensorRT dimensions output buffer is too small");
    }
    std::memcpy(name, tensor.name.data(), tensor.name.size());
    name[tensor.name.size()] = '\0';
    for (std::size_t dimension = 0; dimension < tensor_rank; ++dimension) {
      dimensions[dimension] = tensor.dimensions.d[dimension];
    }
    *dtype_code = tensor.dtype_code;
    *rank = tensor_rank;
    *byte_length = tensor.bytes;
    return 0;
  } catch (const std::exception& exception) {
    set_error(error, error_capacity, exception.what());
    return 1;
  }
}

int vast_trt_device_allocation_bytes(void* opaque, std::uint64_t* output) noexcept {
  const auto* session = static_cast<Session*>(opaque);
  if (session == nullptr || output == nullptr) {
    return 1;
  }
  *output = session->allocation_bytes;
  return 0;
}

int vast_trt_infer(
    void* opaque,
    const void* input,
    std::uint64_t input_bytes,
    void* output,
    std::uint64_t output_capacity,
    std::uint64_t* output_bytes,
    VastCudaTransferTiming* transfer_timing,
    char* error,
    std::size_t error_capacity) noexcept {
  try {
    auto* session = static_cast<Session*>(opaque);
    if (session == nullptr || input == nullptr || output == nullptr ||
        output_bytes == nullptr || transfer_timing == nullptr) {
      throw std::runtime_error("TensorRT inference pointer is null");
    }
    *transfer_timing = VastCudaTransferTiming{};
    if (input_bytes != session->input.bytes) {
      throw std::runtime_error("TensorRT input byte length differs from the engine binding");
    }
    std::uint64_t required_output = 0;
    for (const auto& tensor : session->outputs) {
      required_output += tensor.bytes;
    }
    if (output_capacity < required_output) {
      throw std::runtime_error("TensorRT output buffer is too small");
    }
    check_cuda(cudaSetDevice(session->device_index), "cudaSetDevice");
    const std::uint64_t h2d_host_start_ns = monotonic_ns();
    check_cuda(cudaEventRecord(session->h2d_start_event, session->stream),
               "cudaEventRecord H2D start");
    check_cuda(cudaMemcpyAsync(session->input.device, input, static_cast<std::size_t>(input_bytes), cudaMemcpyHostToDevice, session->stream), "cudaMemcpyAsync H2D");
    check_cuda(cudaEventRecord(session->h2d_end_event, session->stream),
               "cudaEventRecord H2D end");
    // Close the H2D host envelope at the native H2D completion boundary.
    // Reusing the later whole-stream synchronization timestamp here makes the
    // H2D envelope cover inference and D2H as well, so the two transfer
    // intervals overlap even though their CUDA events are correctly ordered.
    check_cuda(cudaEventSynchronize(session->h2d_end_event),
               "cudaEventSynchronize H2D end");
    const std::uint64_t h2d_host_end_ns = monotonic_ns();
    if (!session->context->enqueueV3(session->stream)) {
      throw std::runtime_error("TensorRT enqueueV3 failed");
    }
    const std::uint64_t d2h_host_start_ns = monotonic_ns();
    check_cuda(cudaEventRecord(session->d2h_start_event, session->stream),
               "cudaEventRecord D2H start");
    std::uint64_t offset = 0;
    auto* output_bytes_pointer = static_cast<std::uint8_t*>(output);
    for (const auto& tensor : session->outputs) {
      check_cuda(cudaMemcpyAsync(output_bytes_pointer + offset, tensor.device, static_cast<std::size_t>(tensor.bytes), cudaMemcpyDeviceToHost, session->stream), "cudaMemcpyAsync D2H");
      offset += tensor.bytes;
    }
    check_cuda(cudaEventRecord(session->d2h_end_event, session->stream),
               "cudaEventRecord D2H end");
    check_cuda(cudaStreamSynchronize(session->stream), "cudaStreamSynchronize");
    const std::uint64_t d2h_host_end_ns = monotonic_ns();
    transfer_timing->h2d_host_start_monotonic_ns = h2d_host_start_ns;
    transfer_timing->h2d_host_end_monotonic_ns = h2d_host_end_ns;
    transfer_timing->h2d_device_elapsed_ns = cuda_event_elapsed_ns(
        session->h2d_start_event, session->h2d_end_event,
        "cudaEventElapsedTime H2D");
    transfer_timing->d2h_host_start_monotonic_ns = d2h_host_start_ns;
    transfer_timing->d2h_host_end_monotonic_ns = d2h_host_end_ns;
    transfer_timing->d2h_device_elapsed_ns = cuda_event_elapsed_ns(
        session->d2h_start_event, session->d2h_end_event,
        "cudaEventElapsedTime D2H");
    if (transfer_timing->h2d_host_start_monotonic_ns >=
            transfer_timing->h2d_host_end_monotonic_ns ||
        transfer_timing->h2d_host_end_monotonic_ns >
            transfer_timing->d2h_host_start_monotonic_ns ||
        transfer_timing->d2h_host_start_monotonic_ns >=
            transfer_timing->d2h_host_end_monotonic_ns ||
        transfer_timing->h2d_device_elapsed_ns >
            transfer_timing->h2d_host_end_monotonic_ns -
                transfer_timing->h2d_host_start_monotonic_ns ||
        transfer_timing->d2h_device_elapsed_ns >
            transfer_timing->d2h_host_end_monotonic_ns -
                transfer_timing->d2h_host_start_monotonic_ns) {
      throw std::runtime_error(
          "CUDA event duration is outside its CLOCK_MONOTONIC host envelope");
    }
    *output_bytes = required_output;
    return 0;
  } catch (const std::exception& exception) {
    set_error(error, error_capacity, exception.what());
    return 1;
  }
}

}  // extern "C"
