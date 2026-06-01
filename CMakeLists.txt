cmake_minimum_required(VERSION 3.24)

project(vast_custom_cpp_cuda_qt LANGUAGES CXX CUDA)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CUDA_STANDARD 17)
set(CMAKE_CUDA_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

if(DEFINED ENV{CUDA_TOOLKIT_ROOT} AND NOT "$ENV{CUDA_TOOLKIT_ROOT}" STREQUAL "")
  set(CUDAToolkit_ROOT "$ENV{CUDA_TOOLKIT_ROOT}" CACHE PATH "CUDA toolkit root" FORCE)
endif()

if(NOT CMAKE_CUDA_ARCHITECTURES)
  set(CMAKE_CUDA_ARCHITECTURES 86)
endif()

set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${PROJECT_SOURCE_DIR}/build/bin")

find_package(Threads REQUIRED)
find_package(CUDAToolkit REQUIRED)
find_package(Qt6 REQUIRED COMPONENTS Widgets)

add_executable(adaptive_scheduler_app
  deploy/custom_cpp_cuda_qt/adaptive_scheduler_app.cu
)

set_target_properties(adaptive_scheduler_app PROPERTIES
  CUDA_SEPARABLE_COMPILATION ON
  CUDA_RUNTIME_LIBRARY Static
)

target_compile_options(adaptive_scheduler_app PRIVATE
  $<$<COMPILE_LANGUAGE:CUDA>:--expt-relaxed-constexpr>
)

target_link_libraries(adaptive_scheduler_app PRIVATE
  Threads::Threads
  CUDA::cudart_static
  Qt6::Widgets
)
