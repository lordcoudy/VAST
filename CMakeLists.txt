cmake_minimum_required(VERSION 3.22)

project(vast_benchmark LANGUAGES C CXX)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${PROJECT_SOURCE_DIR}/build/bin")
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY "${PROJECT_SOURCE_DIR}/build/lib")

option(VAST_BUILD_NATIVE_GST_PROBE "Build strict native GStreamer probe runtime" ON)
option(VAST_BUILD_GSTREAMER_CUSTOM_PLUGIN "Build bundled custom GStreamer adaptivescheduler plugin" ON)
option(VAST_BUILD_CUSTOM_CUDA_QT "Build custom CUDA + Qt scheduler app when dependencies are available" ON)

find_package(Threads REQUIRED)
find_package(PkgConfig QUIET)

if(VAST_BUILD_NATIVE_GST_PROBE)
  if(PkgConfig_FOUND)
    pkg_check_modules(GSTREAMER QUIET IMPORTED_TARGET
      gstreamer-1.0
      gstreamer-rtp-1.0
    )
  endif()
  if(GSTREAMER_FOUND)
    add_executable(vast_native_gst_probe
      deploy/native_gst_probe/vast_native_gst_probe.cpp
    )
    target_link_libraries(vast_native_gst_probe PRIVATE
      Threads::Threads
      PkgConfig::GSTREAMER
    )
  else()
    message(WARNING "GStreamer development packages were not found; vast_native_gst_probe will not be built")
  endif()
endif()

if(VAST_BUILD_GSTREAMER_CUSTOM_PLUGIN)
  if(PkgConfig_FOUND)
    pkg_check_modules(GSTREAMER_CUSTOM_PLUGIN QUIET IMPORTED_TARGET
      gstreamer-1.0
      gstreamer-base-1.0
      gstreamer-video-1.0
    )
  endif()
  if(GSTREAMER_CUSTOM_PLUGIN_FOUND)
    add_library(gstadaptivescheduler MODULE
      deploy/gstreamer_adaptivescheduler/gstadaptivescheduler.c
    )
    set_target_properties(gstadaptivescheduler PROPERTIES
      LIBRARY_OUTPUT_DIRECTORY "${PROJECT_SOURCE_DIR}/build/lib"
    )
    target_compile_definitions(gstadaptivescheduler PRIVATE
      PACKAGE="vast"
    )
    target_link_libraries(gstadaptivescheduler PRIVATE
      PkgConfig::GSTREAMER_CUSTOM_PLUGIN
    )
  else()
    message(WARNING "GStreamer base/video development packages were not found; gstadaptivescheduler plugin will not be built")
  endif()
endif()

if(VAST_BUILD_CUSTOM_CUDA_QT)
  include(CheckLanguage)
  if(DEFINED ENV{CUDA_TOOLKIT_ROOT} AND NOT "$ENV{CUDA_TOOLKIT_ROOT}" STREQUAL "")
    set(CUDAToolkit_ROOT "$ENV{CUDA_TOOLKIT_ROOT}" CACHE PATH "CUDA toolkit root" FORCE)
  endif()
  check_language(CUDA)
  find_package(CUDAToolkit QUIET)
  find_package(Qt6 QUIET COMPONENTS Widgets)

  if(CMAKE_CUDA_COMPILER AND CUDAToolkit_FOUND AND Qt6_FOUND)
    enable_language(CUDA)
    set(CMAKE_CUDA_STANDARD 17)
    set(CMAKE_CUDA_STANDARD_REQUIRED ON)
    if(NOT CMAKE_CUDA_ARCHITECTURES)
      set(CMAKE_CUDA_ARCHITECTURES 86)
    endif()

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
  else()
    message(WARNING "CUDA toolkit/compiler or Qt6 Widgets were not found; adaptive_scheduler_app will not be built")
  endif()
endif()
