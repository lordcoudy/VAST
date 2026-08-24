#include "vast_deepstream_meta_bridge.h"

#include <gst/gst.h>
#include <gstnvdsmeta.h>
#include <nvdsmeta.h>

#include <array>
#include <cstring>
#include <iostream>

namespace {

struct Fixture {
  GstBuffer* buffer = nullptr;
  NvDsBatchMeta* batch = nullptr;
  NvDsFrameMeta* frame = nullptr;

  Fixture() {
    buffer = gst_buffer_new();
    batch = nvds_create_batch_meta(1);
    frame = nvds_acquire_frame_meta_from_pool(batch);
    if (buffer == nullptr || batch == nullptr || frame == nullptr) {
      throw std::runtime_error("DeepStream metadata fixture allocation failed");
    }
    frame->source_id = 2;
    frame->frame_num = 7;
    frame->buf_pts = 123456789;
    nvds_add_frame_meta_to_batch(batch, frame);
    NvDsMeta* meta = gst_buffer_add_nvds_meta(
        buffer, batch, nullptr, nvds_batch_meta_copy_func,
        nvds_batch_meta_release_func);
    if (meta == nullptr) {
      throw std::runtime_error("DeepStream GstMeta attachment failed");
    }
    meta->meta_type = NVDS_BATCH_GST_META;
  }

  ~Fixture() {
    if (buffer != nullptr) {
      gst_buffer_unref(buffer);
    }
  }
};

bool contains(const char* value, const char* expected) {
  return value != nullptr && std::strstr(value, expected) != nullptr;
}

}  // namespace

int main() {
  gst_init(nullptr, nullptr);
  Fixture fixture;
  const std::array<uint8_t, 32> identity = {
      0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
      16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31};
  VastDeepStreamFrameObservation observed{};
  std::array<char, 512> error{};

  if (vast_deepstream_bind_admission(
          fixture.buffer, 2, 123456789, identity.data(), &observed,
          error.data(), error.size()) != 0) {
    std::cerr << "bind failed: " << error.data() << '\n';
    return 1;
  }
  if (observed.abi_version != 1 || observed.num_frames_in_batch != 1 ||
      observed.source_id != 2 || observed.frame_num != 7 ||
      observed.buf_pts_ns != 123456789 ||
      std::memcmp(observed.identity_sha256, identity.data(), identity.size()) != 0) {
    std::cerr << "bound observation drifted\n";
    return 2;
  }
  if (vast_deepstream_verify_admission(
          fixture.buffer, 2, 123456789, identity.data(), &observed,
          error.data(), error.size()) != 0) {
    std::cerr << "verify failed: " << error.data() << '\n';
    return 3;
  }

  auto wrong_identity = identity;
  wrong_identity[0] ^= 0xff;
  error.fill(0);
  if (vast_deepstream_verify_admission(
          fixture.buffer, 2, 123456789, wrong_identity.data(), &observed,
          error.data(), error.size()) == 0 || !contains(error.data(), "digest mismatch")) {
    std::cerr << "digest mismatch was accepted\n";
    return 4;
  }
  error.fill(0);
  if (vast_deepstream_verify_admission(
          fixture.buffer, 3, 123456789, identity.data(), &observed,
          error.data(), error.size()) == 0 || !contains(error.data(), "source_id mismatch")) {
    std::cerr << "source mismatch was accepted\n";
    return 5;
  }
  error.fill(0);
  if (vast_deepstream_verify_admission(
          fixture.buffer, 2, 123456790, identity.data(), &observed,
          error.data(), error.size()) == 0 || !contains(error.data(), "buf_pts mismatch")) {
    std::cerr << "PTS mismatch was accepted\n";
    return 6;
  }
  fixture.frame->frame_num = -1;
  error.fill(0);
  if (vast_deepstream_verify_admission(
          fixture.buffer, 2, 123456789, identity.data(), &observed,
          error.data(), error.size()) == 0 || !contains(error.data(), "negative")) {
    std::cerr << "negative frame counter was accepted\n";
    return 7;
  }
  return 0;
}
