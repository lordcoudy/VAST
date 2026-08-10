#pragma once

#include <gst/gst.h>

#include <array>
#include <fstream>
#include <stdexcept>
#include <string>

namespace vast::gstanalytics {

inline gboolean supported_detector_factory(const gchar* factory) {
  return g_strcmp0(factory, "gvadetect") == 0 || g_strcmp0(factory, "object_detect") == 0;
}

inline gboolean valid_sha256(const gchar* value) {
  if (value == nullptr || std::char_traits<char>::length(value) != 64) {
    return FALSE;
  }
  for (const gchar* cursor = value; *cursor != '\0'; ++cursor) {
    if (!((*cursor >= '0' && *cursor <= '9') || (*cursor >= 'a' && *cursor <= 'f'))) {
      return FALSE;
    }
  }
  return TRUE;
}

inline gboolean valid_detector_id(const gchar* value) {
  if (value == nullptr || value[0] == '\0' || std::char_traits<char>::length(value) > 80 ||
      g_strcmp0(value, "identity") == 0 || g_strcmp0(value, "topology_only") == 0) {
    return FALSE;
  }
  for (const guchar* cursor = reinterpret_cast<const guchar*>(value); *cursor != '\0'; ++cursor) {
    if (*cursor < 0x20 || *cursor > 0x7e || *cursor == ';') {
      return FALSE;
    }
  }
  return TRUE;
}

inline gboolean valid_branch_id(const gchar* value) {
  if (value == nullptr || value[0] == '\0' || std::char_traits<char>::length(value) > 128) {
    return FALSE;
  }
  for (const gchar* cursor = value; *cursor != '\0'; ++cursor) {
    if (!((*cursor >= 'a' && *cursor <= 'z') || (*cursor >= '0' && *cursor <= '9') ||
          *cursor == '_' || *cursor == '-' || *cursor == '.')) {
      return FALSE;
    }
  }
  return TRUE;
}

inline std::string sha256_file(const gchar* path) {
  if (path == nullptr || path[0] == '\0' || !g_file_test(path, G_FILE_TEST_IS_REGULAR)) {
    throw std::runtime_error("model artifact is not a regular file");
  }
  std::ifstream input(path, std::ios::binary);
  if (!input) {
    throw std::runtime_error("model artifact cannot be opened");
  }
  GChecksum* checksum = g_checksum_new(G_CHECKSUM_SHA256);
  if (checksum == nullptr) {
    throw std::runtime_error("SHA-256 checksum initialization failed");
  }
  std::array<char, 1024 * 1024> buffer{};
  while (input) {
    input.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
    const std::streamsize count = input.gcount();
    if (count > 0) {
      g_checksum_update(
          checksum,
          reinterpret_cast<const guchar*>(buffer.data()),
          static_cast<gssize>(count));
    }
  }
  if (!input.eof()) {
    g_checksum_free(checksum);
    throw std::runtime_error("model artifact read failed");
  }
  const gchar* digest = g_checksum_get_string(checksum);
  const std::string result = digest == nullptr ? std::string() : std::string(digest);
  g_checksum_free(checksum);
  if (result.size() != 64) {
    throw std::runtime_error("model artifact SHA-256 calculation failed");
  }
  return result;
}

inline gboolean has_suffix(const std::string& value, const std::string& suffix) {
  return value.size() >= suffix.size() &&
         value.compare(value.size() - suffix.size(), suffix.size(), suffix) == 0;
}

inline std::string verified_model_identity(
    GstElement* detector,
    const gchar* detector_id,
    const gchar* expected_model_sha256,
    const gchar* expected_weights_sha256) {
  GParamSpec* model_property = g_object_class_find_property(G_OBJECT_GET_CLASS(detector), "model");
  if (model_property == nullptr || G_PARAM_SPEC_VALUE_TYPE(model_property) != G_TYPE_STRING) {
    throw std::runtime_error("detector has no string model property");
  }
  gchar* raw_model = nullptr;
  g_object_get(detector, "model", &raw_model, nullptr);
  const std::string model_path = raw_model == nullptr ? std::string() : std::string(raw_model);
  g_free(raw_model);
  if (model_path.empty()) {
    throw std::runtime_error("detector has an empty model property");
  }
  if (!valid_sha256(expected_model_sha256)) {
    throw std::runtime_error("expected-model-sha256 must be a lowercase SHA-256 digest");
  }
  const std::string model_sha256 = sha256_file(model_path.c_str());
  if (model_sha256 != expected_model_sha256) {
    throw std::runtime_error("detector model SHA-256 does not match the declared digest");
  }

  std::string weights_sha256;
  if (has_suffix(model_path, ".xml")) {
    if (!valid_sha256(expected_weights_sha256)) {
      throw std::runtime_error("OpenVINO IR requires expected-weights-sha256 for the sibling .bin file");
    }
    const std::string weights_path = model_path.substr(0, model_path.size() - 4) + ".bin";
    weights_sha256 = sha256_file(weights_path.c_str());
    if (weights_sha256 != expected_weights_sha256) {
      throw std::runtime_error("OpenVINO weights SHA-256 does not match the declared digest");
    }
  } else if (expected_weights_sha256 != nullptr && expected_weights_sha256[0] != '\0') {
    throw std::runtime_error("expected-weights-sha256 is only supported for an OpenVINO .xml model");
  }

  std::string identity = std::string(detector_id) + ";model_sha256=" + model_sha256;
  if (!weights_sha256.empty()) {
    identity += ";weights_sha256=" + weights_sha256;
  }
  if (identity.size() > 256) {
    throw std::runtime_error("verified detector identity exceeds the terminal transport limit");
  }
  return identity;
}

inline GstElement* immediate_peer_element(GstPad* pad) {
  GstPad* peer = gst_pad_get_peer(pad);
  if (peer == nullptr) {
    return nullptr;
  }
  GstElement* element = gst_pad_get_parent_element(peer);
  gst_object_unref(peer);
  return element;
}

inline std::string element_factory_name(GstElement* element) {
  GstElementFactory* factory = element == nullptr ? nullptr : gst_element_get_factory(element);
  const gchar* name = factory == nullptr
      ? nullptr
      : gst_plugin_feature_get_name(GST_PLUGIN_FEATURE(factory));
  return name == nullptr ? std::string() : std::string(name);
}

}  // namespace vast::gstanalytics
