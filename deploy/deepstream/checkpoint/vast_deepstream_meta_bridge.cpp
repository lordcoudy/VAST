#include "vast_deepstream_meta_bridge.h"

#include <gst/gst.h>
#include <gstnvdsmeta.h>
#include <nvdsmeta.h>

#include <array>
#include <cstdarg>
#include <cstdio>
#include <cstring>

namespace {

constexpr uint32_t kAbiVersion = 1;
constexpr size_t kIdentityBytes = 32;

int fail(char* output, size_t output_size, const char* format, ...) {
  if (output != nullptr && output_size > 0) {
    va_list values;
    va_start(values, format);
    std::vsnprintf(output, output_size, format, values);
    va_end(values);
    output[output_size - 1] = '\0';
  }
  return -1;
}

NvDsFrameMeta* exact_frame(
    void* raw_buffer,
    uint32_t expected_source_id,
    NvDsBatchMeta** batch_output,
    char* error,
    size_t error_size) {
  if (raw_buffer == nullptr || batch_output == nullptr) {
    fail(error, error_size, "null GstBuffer or batch output");
    return nullptr;
  }
  auto* buffer = static_cast<GstBuffer*>(raw_buffer);
  NvDsBatchMeta* batch = gst_buffer_get_nvds_batch_meta(buffer);
  if (batch == nullptr) {
    fail(error, error_size, "GstBuffer has no NvDsBatchMeta");
    return nullptr;
  }
  if (batch->num_frames_in_batch != 1 || batch->frame_meta_list == nullptr ||
      batch->frame_meta_list->next != nullptr) {
    fail(error, error_size, "NvDsBatchMeta must contain exactly one frame");
    return nullptr;
  }
  auto* frame = static_cast<NvDsFrameMeta*>(batch->frame_meta_list->data);
  if (frame == nullptr) {
    fail(error, error_size, "NvDsBatchMeta contains a null frame");
    return nullptr;
  }
  if (frame->source_id != expected_source_id) {
    fail(error, error_size, "NvDsFrameMeta source_id mismatch: actual=%u expected=%u",
         frame->source_id, expected_source_id);
    return nullptr;
  }
  // frame_num is a signed DeepStream source counter in decoded-output order.
  // It is observable provenance, but it is not the admission sequence: codecs
  // with B-frames may reorder it relative to compressed AU delivery.
  if (frame->frame_num < 0) {
    fail(error, error_size, "NvDsFrameMeta frame_num is negative: actual=%d",
         frame->frame_num);
    return nullptr;
  }
  *batch_output = batch;
  return frame;
}

void observe(
    const NvDsBatchMeta* batch,
    const NvDsFrameMeta* frame,
    VastDeepStreamFrameObservation* output) {
  std::memset(output, 0, sizeof(*output));
  output->abi_version = kAbiVersion;
  output->num_frames_in_batch = batch->num_frames_in_batch;
  output->source_id = frame->source_id;
  output->batch_id = frame->batch_id;
  output->frame_num = static_cast<int32_t>(frame->frame_num);
  output->buf_pts_ns = frame->buf_pts;
  static_assert(sizeof(frame->misc_frame_info) >= kIdentityBytes,
                "NvDsFrameMeta.misc_frame_info cannot hold SHA-256 identity");
  std::memcpy(output->identity_sha256, frame->misc_frame_info, kIdentityBytes);
}

int access_admission(
    bool bind,
    void* gst_buffer,
    uint32_t expected_source_id,
    uint64_t expected_buf_pts_ns,
    const uint8_t identity_sha256[kIdentityBytes],
    VastDeepStreamFrameObservation* observation,
    char* error,
    size_t error_size) {
  if (identity_sha256 == nullptr || observation == nullptr) {
    return fail(error, error_size, "null identity or observation");
  }
  NvDsBatchMeta* batch = nullptr;
  NvDsFrameMeta* frame = exact_frame(
      gst_buffer, expected_source_id, &batch, error, error_size);
  if (frame == nullptr) {
    return -1;
  }
  if (frame->buf_pts != expected_buf_pts_ns) {
    return fail(error, error_size,
                "NvDsFrameMeta buf_pts mismatch: actual=%llu expected=%llu",
                static_cast<unsigned long long>(frame->buf_pts),
                static_cast<unsigned long long>(expected_buf_pts_ns));
  }
  if (bind) {
    std::memcpy(frame->misc_frame_info, identity_sha256, kIdentityBytes);
  } else if (std::memcmp(frame->misc_frame_info, identity_sha256, kIdentityBytes) != 0) {
    return fail(error, error_size, "NvDsFrameMeta admission identity digest mismatch");
  }
  observe(batch, frame, observation);
  if (std::memcmp(observation->identity_sha256, identity_sha256, kIdentityBytes) != 0) {
    return fail(error, error_size, "NvDsFrameMeta admission identity was not retained");
  }
  return 0;
}

}  // namespace

extern "C" int vast_deepstream_observe_frame(
    void* gst_buffer,
    uint32_t expected_source_id,
    VastDeepStreamFrameObservation* observation,
    char* error,
    size_t error_size) {
  if (observation == nullptr) {
    return fail(error, error_size, "null observation");
  }
  NvDsBatchMeta* batch = nullptr;
  NvDsFrameMeta* frame = exact_frame(
      gst_buffer, expected_source_id, &batch, error, error_size);
  if (frame == nullptr) {
    return -1;
  }
  observe(batch, frame, observation);
  return 0;
}

extern "C" int vast_deepstream_bind_admission(
    void* gst_buffer,
    uint32_t expected_source_id,
    uint64_t expected_buf_pts_ns,
    const uint8_t identity_sha256[32],
    VastDeepStreamFrameObservation* observation,
    char* error,
    size_t error_size) {
  return access_admission(true, gst_buffer, expected_source_id,
                          expected_buf_pts_ns, identity_sha256, observation, error,
                          error_size);
}

extern "C" int vast_deepstream_verify_admission(
    void* gst_buffer,
    uint32_t expected_source_id,
    uint64_t expected_buf_pts_ns,
    const uint8_t identity_sha256[32],
    VastDeepStreamFrameObservation* observation,
    char* error,
    size_t error_size) {
  return access_admission(false, gst_buffer, expected_source_id,
                          expected_buf_pts_ns, identity_sha256, observation, error,
                          error_size);
}
