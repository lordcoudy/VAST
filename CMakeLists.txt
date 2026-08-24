cmake_minimum_required(VERSION 3.22)

project(vast_benchmark LANGUAGES C CXX)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${PROJECT_SOURCE_DIR}/build/bin" CACHE PATH
  "Output directory for VAST executables")
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY "${PROJECT_SOURCE_DIR}/build/lib" CACHE PATH
  "Output directory for VAST libraries")

option(VAST_BUILD_NATIVE_GST_PROBE "Build strict native GStreamer probe runtime" ON)
option(VAST_BUILD_CHECKPOINT_SOURCE_TRUST_CANDIDATE
  "Build a fail-closed hardened checkpoint source trust candidate" OFF)
option(VAST_BUILD_GSTREAMER_CUSTOM_PLUGIN "Build bundled custom GStreamer adaptivescheduler plugin" ON)
option(VAST_BUILD_CUSTOM_CUDA_QT "Build custom CUDA + Qt scheduler app when dependencies are available" ON)
option(VAST_BUILD_REPLAY_BROKER_CONTRACT
  "Build the nonauthorizing replay-broker v4 logical contract" OFF)
option(VAST_BUILD_REPLAY_BROKER_CONTRACT_TESTS
  "Build tests for the nonauthorizing replay-broker v4 logical contract" OFF)
option(VAST_BUILD_REPLAY_BROKER_PREPARED_HANDLES
  "Build the nonauthorizing replay-broker v4 OS-handle preparation candidate" OFF)
option(VAST_BUILD_REPLAY_BROKER_PREPARED_HANDLES_TESTS
  "Build tests for the replay-broker v4 OS-handle preparation candidate" OFF)
option(VAST_BUILD_REPLAY_BROKER_ARTIFACT_BYTES_OBSERVATION
  "Build the nonauthorizing replay-broker v4 artifact-byte observer" OFF)
option(VAST_BUILD_REPLAY_BROKER_ARTIFACT_BYTES_OBSERVATION_TESTS
  "Build tests for the replay-broker v4 artifact-byte observer" OFF)

if(VAST_BUILD_REPLAY_BROKER_CONTRACT_TESTS AND
   NOT VAST_BUILD_REPLAY_BROKER_CONTRACT)
  message(FATAL_ERROR
    "VAST_BUILD_REPLAY_BROKER_CONTRACT_TESTS requires VAST_BUILD_REPLAY_BROKER_CONTRACT")
endif()

if(VAST_BUILD_REPLAY_BROKER_PREPARED_HANDLES AND
   NOT VAST_BUILD_REPLAY_BROKER_CONTRACT)
  message(FATAL_ERROR
    "VAST_BUILD_REPLAY_BROKER_PREPARED_HANDLES requires VAST_BUILD_REPLAY_BROKER_CONTRACT")
endif()

if(VAST_BUILD_REPLAY_BROKER_PREPARED_HANDLES_TESTS AND
   NOT VAST_BUILD_REPLAY_BROKER_PREPARED_HANDLES)
  message(FATAL_ERROR
    "VAST_BUILD_REPLAY_BROKER_PREPARED_HANDLES_TESTS requires VAST_BUILD_REPLAY_BROKER_PREPARED_HANDLES")
endif()

if(VAST_BUILD_REPLAY_BROKER_ARTIFACT_BYTES_OBSERVATION AND
   NOT VAST_BUILD_REPLAY_BROKER_PREPARED_HANDLES)
  message(FATAL_ERROR
    "VAST_BUILD_REPLAY_BROKER_ARTIFACT_BYTES_OBSERVATION requires VAST_BUILD_REPLAY_BROKER_PREPARED_HANDLES")
endif()

if(VAST_BUILD_REPLAY_BROKER_ARTIFACT_BYTES_OBSERVATION_TESTS AND
   NOT VAST_BUILD_REPLAY_BROKER_ARTIFACT_BYTES_OBSERVATION)
  message(FATAL_ERROR
    "VAST_BUILD_REPLAY_BROKER_ARTIFACT_BYTES_OBSERVATION_TESTS requires VAST_BUILD_REPLAY_BROKER_ARTIFACT_BYTES_OBSERVATION")
endif()

if(VAST_BUILD_CHECKPOINT_SOURCE_TRUST_CANDIDATE AND
   NOT VAST_BUILD_NATIVE_GST_PROBE)
  message(FATAL_ERROR
    "VAST_BUILD_CHECKPOINT_SOURCE_TRUST_CANDIDATE requires VAST_BUILD_NATIVE_GST_PROBE")
endif()

if(VAST_BUILD_REPLAY_BROKER_CONTRACT)
  if(NOT WIN32 OR NOT CMAKE_SIZEOF_VOID_P EQUAL 8)
    message(FATAL_ERROR
      "The replay-broker v4 logical contract is supported only on Windows x64")
  endif()
  add_library(vast_replay_broker_contract_v4 STATIC
    deploy/windows_replay_broker/replay_broker_contract_v4.cpp
  )
  target_compile_features(vast_replay_broker_contract_v4 PUBLIC cxx_std_17)
  target_include_directories(vast_replay_broker_contract_v4 PUBLIC
    deploy/windows_replay_broker
  )
  if(MSVC)
    target_compile_options(vast_replay_broker_contract_v4 PRIVATE
      /W4 /WX /permissive- /EHsc /utf-8
    )
  endif()
  if(VAST_BUILD_REPLAY_BROKER_CONTRACT_TESTS)
    include(CTest)
    add_executable(vast_replay_broker_contract_v4_test
      tests/cpp/replay_broker_contract_v4_test.cpp
    )
    target_compile_features(vast_replay_broker_contract_v4_test PRIVATE cxx_std_17)
    if(MSVC)
      target_compile_options(vast_replay_broker_contract_v4_test PRIVATE
        /W4 /WX /permissive- /EHsc /utf-8
      )
    endif()
    target_link_libraries(vast_replay_broker_contract_v4_test PRIVATE
      vast_replay_broker_contract_v4
    )
    add_test(NAME vast_replay_broker_contract_v4_test
      COMMAND vast_replay_broker_contract_v4_test
    )
    set_tests_properties(vast_replay_broker_contract_v4_test PROPERTIES
      TIMEOUT 30
    )
  endif()
endif()

if(VAST_BUILD_REPLAY_BROKER_PREPARED_HANDLES)
  if(NOT WIN32 OR NOT CMAKE_SIZEOF_VOID_P EQUAL 8)
    message(FATAL_ERROR
      "The replay-broker v4 OS-handle preparation candidate is supported only on Windows x64")
  endif()
  add_library(vast_replay_broker_prepared_handles_v4 STATIC
    deploy/windows_replay_broker/replay_broker_prepared_handles_v4.cpp
  )
  target_compile_features(vast_replay_broker_prepared_handles_v4 PUBLIC cxx_std_17)
  target_compile_definitions(vast_replay_broker_prepared_handles_v4 PRIVATE
    WIN32_LEAN_AND_MEAN NOMINMAX UNICODE _UNICODE
  )
  target_include_directories(vast_replay_broker_prepared_handles_v4 PUBLIC
    deploy/windows_replay_broker
  )
  target_link_libraries(vast_replay_broker_prepared_handles_v4 PUBLIC
    vast_replay_broker_contract_v4
  )
  if(MSVC)
    target_compile_options(vast_replay_broker_prepared_handles_v4 PRIVATE
      /W4 /WX /permissive- /EHsc /utf-8
    )
  endif()
  if(VAST_BUILD_REPLAY_BROKER_PREPARED_HANDLES_TESTS)
    include(CTest)
    target_compile_definitions(vast_replay_broker_prepared_handles_v4 PRIVATE
      VAST_REPLAY_BROKER_PREPARED_HANDLES_TESTING=1
    )
    add_executable(vast_replay_broker_prepared_handles_v4_test
      tests/cpp/replay_broker_prepared_handles_v4_test.cpp
    )
    target_compile_features(vast_replay_broker_prepared_handles_v4_test PRIVATE
      cxx_std_17
    )
    target_compile_definitions(vast_replay_broker_prepared_handles_v4_test PRIVATE
      WIN32_LEAN_AND_MEAN NOMINMAX UNICODE _UNICODE
      VAST_REPLAY_BROKER_PREPARED_HANDLES_TESTING=1
    )
    if(MSVC)
      target_compile_options(vast_replay_broker_prepared_handles_v4_test PRIVATE
        /W4 /WX /permissive- /EHsc /utf-8
      )
    endif()
    target_link_libraries(vast_replay_broker_prepared_handles_v4_test PRIVATE
      vast_replay_broker_prepared_handles_v4
    )
    add_test(NAME vast_replay_broker_prepared_handles_v4_test
      COMMAND vast_replay_broker_prepared_handles_v4_test
    )
    set_tests_properties(vast_replay_broker_prepared_handles_v4_test PROPERTIES
      TIMEOUT 60
    )
  endif()
endif()

if(VAST_BUILD_REPLAY_BROKER_ARTIFACT_BYTES_OBSERVATION)
  if(NOT WIN32 OR NOT CMAKE_SIZEOF_VOID_P EQUAL 8)
    message(FATAL_ERROR
      "The replay-broker v4 artifact-byte observer is supported only on Windows x64")
  endif()
  add_library(vast_replay_broker_artifact_bytes_observation_v4 STATIC
    deploy/windows_replay_broker/replay_broker_artifact_bytes_observation_v4.cpp
  )
  target_compile_features(
    vast_replay_broker_artifact_bytes_observation_v4 PUBLIC cxx_std_17)
  target_compile_definitions(
    vast_replay_broker_artifact_bytes_observation_v4 PRIVATE
    WIN32_LEAN_AND_MEAN NOMINMAX UNICODE _UNICODE
  )
  target_include_directories(
    vast_replay_broker_artifact_bytes_observation_v4 PUBLIC
    deploy/windows_replay_broker
  )
  target_link_libraries(vast_replay_broker_artifact_bytes_observation_v4
    PUBLIC vast_replay_broker_prepared_handles_v4
    PRIVATE bcrypt
  )
  if(MSVC)
    target_compile_options(
      vast_replay_broker_artifact_bytes_observation_v4 PRIVATE
      /W4 /WX /permissive- /EHsc /utf-8
    )
  endif()
  if(VAST_BUILD_REPLAY_BROKER_ARTIFACT_BYTES_OBSERVATION_TESTS)
    include(CTest)
    target_compile_definitions(
      vast_replay_broker_artifact_bytes_observation_v4 PRIVATE
      VAST_REPLAY_BROKER_ARTIFACT_BYTES_OBSERVATION_TESTING=1
    )
    add_executable(vast_replay_broker_artifact_bytes_observation_v4_test
      tests/cpp/replay_broker_artifact_bytes_observation_v4_test.cpp
    )
    target_compile_features(
      vast_replay_broker_artifact_bytes_observation_v4_test PRIVATE cxx_std_17)
    target_compile_definitions(
      vast_replay_broker_artifact_bytes_observation_v4_test PRIVATE
      WIN32_LEAN_AND_MEAN NOMINMAX UNICODE _UNICODE
      VAST_REPLAY_BROKER_ARTIFACT_BYTES_OBSERVATION_TESTING=1
    )
    if(MSVC)
      target_compile_options(
        vast_replay_broker_artifact_bytes_observation_v4_test PRIVATE
        /W4 /WX /permissive- /EHsc /utf-8
      )
    endif()
    target_link_libraries(
      vast_replay_broker_artifact_bytes_observation_v4_test PRIVATE
      vast_replay_broker_artifact_bytes_observation_v4
    )
    add_test(NAME vast_replay_broker_artifact_bytes_observation_v4_test
      COMMAND vast_replay_broker_artifact_bytes_observation_v4_test
    )
    set_tests_properties(
      vast_replay_broker_artifact_bytes_observation_v4_test PROPERTIES
      TIMEOUT 120
    )
  endif()
endif()

find_package(Threads REQUIRED)
find_package(PkgConfig QUIET)

if(VAST_BUILD_NATIVE_GST_PROBE)
  if(PkgConfig_FOUND)
    pkg_check_modules(GSTREAMER QUIET IMPORTED_TARGET
      gstreamer-1.0
      gstreamer-app-1.0
      gstreamer-rtp-1.0
      gstreamer-video-1.0
    )
  endif()
  if(GSTREAMER_FOUND)
    add_executable(vast_native_gst_probe
      deploy/native_gst_probe/vast_native_gst_probe.cpp
    )
    add_executable(vast_checkpoint_source
      deploy/native_gst_probe/checkpoint_source_coordinator.cpp
    )
    if(VAST_BUILD_CHECKPOINT_SOURCE_TRUST_CANDIDATE)
      if(CMAKE_CONFIGURATION_TYPES OR
         NOT CMAKE_BUILD_TYPE STREQUAL "Release")
        message(FATAL_ERROR
          "checkpoint source hardening requires a single-config Release build")
      endif()
      if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux" OR
         NOT CMAKE_SYSTEM_PROCESSOR MATCHES "^(x86_64|amd64|AMD64)$" OR
         NOT CMAKE_CXX_COMPILER_ID STREQUAL "GNU" OR
         NOT CMAKE_CXX_COMPILER_VERSION VERSION_GREATER_EQUAL "13.0" OR
         NOT CMAKE_CXX_COMPILER_VERSION VERSION_LESS "14.0")
        message(FATAL_ERROR
          "checkpoint source hardening requires Linux x86_64 and GNU C++ 13.x")
      endif()

      include(CheckCXXCompilerFlag)
      include(CheckLinkerFlag)
      check_cxx_compiler_flag("-O2" VAST_CHECKPOINT_SOURCE_HAS_O2)
      check_cxx_compiler_flag("-fstack-protector-strong"
        VAST_CHECKPOINT_SOURCE_HAS_STACK_PROTECTOR)
      check_cxx_compiler_flag("-D_FORTIFY_SOURCE=3"
        VAST_CHECKPOINT_SOURCE_HAS_FORTIFY3)
      check_cxx_compiler_flag("-fPIE" VAST_CHECKPOINT_SOURCE_HAS_FPIE)
      check_cxx_compiler_flag("-fcf-protection=full"
        VAST_CHECKPOINT_SOURCE_HAS_CET)
      check_linker_flag(CXX "-Wl,-z,relro"
        VAST_CHECKPOINT_SOURCE_HAS_RELRO)
      check_linker_flag(CXX "-Wl,-z,now"
        VAST_CHECKPOINT_SOURCE_HAS_BIND_NOW)
      check_linker_flag(CXX "-Wl,-z,noexecstack"
        VAST_CHECKPOINT_SOURCE_HAS_NOEXECSTACK)
      check_linker_flag(CXX "-pie" VAST_CHECKPOINT_SOURCE_HAS_PIE)
      foreach(checkpoint_source_flag IN ITEMS
          VAST_CHECKPOINT_SOURCE_HAS_O2
          VAST_CHECKPOINT_SOURCE_HAS_STACK_PROTECTOR
          VAST_CHECKPOINT_SOURCE_HAS_FORTIFY3
          VAST_CHECKPOINT_SOURCE_HAS_FPIE
          VAST_CHECKPOINT_SOURCE_HAS_CET
          VAST_CHECKPOINT_SOURCE_HAS_RELRO
          VAST_CHECKPOINT_SOURCE_HAS_BIND_NOW
          VAST_CHECKPOINT_SOURCE_HAS_NOEXECSTACK
          VAST_CHECKPOINT_SOURCE_HAS_PIE)
        if(NOT ${checkpoint_source_flag})
          message(FATAL_ERROR
            "checkpoint source hardening requires ${checkpoint_source_flag}")
        endif()
      endforeach()
      target_compile_options(vast_checkpoint_source PRIVATE
        $<$<CONFIG:Release>:-O2>
        $<$<CONFIG:Release>:-fstack-protector-strong>
        $<$<CONFIG:Release>:-D_FORTIFY_SOURCE=3>
        $<$<CONFIG:Release>:-fPIE>
        $<$<CONFIG:Release>:-fcf-protection=full>
      )
      target_link_options(vast_checkpoint_source PRIVATE
        $<$<CONFIG:Release>:-Wl,-z,relro>
        $<$<CONFIG:Release>:-Wl,-z,now>
        $<$<CONFIG:Release>:-Wl,-z,noexecstack>
        $<$<CONFIG:Release>:-pie>
      )
    endif()
    target_link_libraries(vast_native_gst_probe PRIVATE
      Threads::Threads
      PkgConfig::GSTREAMER
    )
    target_link_libraries(vast_checkpoint_source PRIVATE
      Threads::Threads
      PkgConfig::GSTREAMER
    )
  else()
    if(VAST_BUILD_CHECKPOINT_SOURCE_TRUST_CANDIDATE)
      message(FATAL_ERROR
        "checkpoint source trust candidate requires GStreamer development packages")
    else()
      message(WARNING "GStreamer development packages were not found; vast_native_gst_probe will not be built")
    endif()
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
      LIBRARY_OUTPUT_DIRECTORY "${CMAKE_LIBRARY_OUTPUT_DIRECTORY}"
    )
    target_compile_definitions(gstadaptivescheduler PRIVATE
      PACKAGE="vast"
    )
    target_link_libraries(gstadaptivescheduler PRIVATE
      PkgConfig::GSTREAMER_CUSTOM_PLUGIN
    )

    add_library(gstvastanalyticsterminal MODULE
      deploy/gstreamer_analytics_terminal/gstvastanalyticsterminal.cpp
    )
    set_target_properties(gstvastanalyticsterminal PROPERTIES
      LIBRARY_OUTPUT_DIRECTORY "${CMAKE_LIBRARY_OUTPUT_DIRECTORY}"
    )
    target_compile_definitions(gstvastanalyticsterminal PRIVATE
      PACKAGE="vast"
    )
    target_include_directories(gstvastanalyticsterminal PRIVATE
      deploy/native_gst_probe
    )
    target_link_libraries(gstvastanalyticsterminal PRIVATE
      PkgConfig::GSTREAMER_CUSTOM_PLUGIN
    )

    add_library(gstvastanalyticsqueue MODULE
      deploy/gstreamer_analytics_terminal/gstvastanalyticsqueue.cpp
    )
    set_target_properties(gstvastanalyticsqueue PROPERTIES
      LIBRARY_OUTPUT_DIRECTORY "${CMAKE_LIBRARY_OUTPUT_DIRECTORY}"
    )
    target_compile_definitions(gstvastanalyticsqueue PRIVATE
      PACKAGE="vast"
    )
    target_include_directories(gstvastanalyticsqueue PRIVATE
      deploy/native_gst_probe
      deploy/gstreamer_analytics_terminal
    )
    target_link_libraries(gstvastanalyticsqueue PRIVATE
      PkgConfig::GSTREAMER_CUSTOM_PLUGIN
    )

    add_library(gstvastcheckpointprefixqueue MODULE
      deploy/gstreamer_analytics_terminal/gstvastcheckpointprefixqueue.cpp
    )
    set_target_properties(gstvastcheckpointprefixqueue PROPERTIES
      LIBRARY_OUTPUT_DIRECTORY "${CMAKE_LIBRARY_OUTPUT_DIRECTORY}"
    )
    target_compile_definitions(gstvastcheckpointprefixqueue PRIVATE
      PACKAGE="vast"
    )
    target_include_directories(gstvastcheckpointprefixqueue PRIVATE
      deploy/native_gst_probe
    )
    target_link_libraries(gstvastcheckpointprefixqueue PRIVATE
      PkgConfig::GSTREAMER_CUSTOM_PLUGIN
    )
  else()
    message(WARNING "GStreamer base/video development packages were not found; custom GStreamer plugins will not be built")
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
