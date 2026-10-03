#pragma once

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct VastDeepStreamFrameObservation {
  uint32_t abi_version;
  uint32_t num_frames_in_batch;
  uint32_t source_id;
  uint32_t batch_id;
  int32_t frame_num;
  uint32_t reserved;
  uint64_t buf_pts_ns;
  uint8_t identity_sha256[32];
} VastDeepStreamFrameObservation;

int vast_deepstream_observe_frame(
    void* gst_buffer,
    uint32_t expected_source_id,
    VastDeepStreamFrameObservation* observation,
    char* error,
    size_t error_size);

int vast_deepstream_bind_admission(
    void* gst_buffer,
    uint32_t expected_source_id,
    uint64_t expected_buf_pts_ns,
    const uint8_t identity_sha256[32],
    VastDeepStreamFrameObservation* observation,
    char* error,
    size_t error_size);

int vast_deepstream_verify_admission(
    void* gst_buffer,
    uint32_t expected_source_id,
    uint64_t expected_buf_pts_ns,
    const uint8_t identity_sha256[32],
    VastDeepStreamFrameObservation* observation,
    char* error,
    size_t error_size);

#ifdef __cplusplus
}
#endif
