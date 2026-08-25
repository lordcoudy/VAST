ARG BASE_IMAGE=vast/openvino-native-probe@sha256:5c43c6c1f95b3fbb4a95957d1d293b1272c1db6a44a7a2063aad3aeba7c951d1
ARG SOURCE_DATE_EPOCH=0

FROM ${BASE_IMAGE} AS runtime_builder

ARG SOURCE_DATE_EPOCH
USER root

RUN install -d -m 0755 \
      /opt/vast/runtime-root/opt/vast/checkpoint \
      /opt/vast/runtime-root/opt/vast/python \
      /opt/vast/runtime-root/usr/local/bin \
      /opt/vast/wheels

COPY deploy/gstreamer_custom/publication/requirements.lock /opt/vast/requirements.lock
COPY deploy/gstreamer_custom/publication/wheels/ /opt/vast/wheels/

RUN /usr/bin/python3 -m pip install \
      --no-index --no-deps --no-compile --require-hashes \
      --find-links=/opt/vast/wheels \
      --target=/opt/vast/runtime-root/opt/vast/python \
      --requirement=/opt/vast/requirements.lock

# BEGIN VAST_RUNTIME_SOURCE_ALLOWLIST
COPY \
  scripts/analytics_model_contract.py \
  scripts/backend_publication_dispatch.py \
  scripts/backend_publication_output_receipt.py \
  scripts/backend_publication_runtime_authority.py \
  scripts/backend_runtime_grant.py \
  scripts/backend_runtime_qualification_v3.py \
  scripts/benchmark_contract.py \
  scripts/checkpoint_acceptance_metadata_binding.py \
  scripts/checkpoint_admission.py \
  scripts/checkpoint_gstreamer_runtime.py \
  scripts/checkpoint_native_policy_runtime.py \
  scripts/checkpoint_openvino_gva_container_coordinator_v3.py \
  scripts/checkpoint_publication_runtime.py \
  scripts/checkpoint_runtime.py \
  scripts/checkpoint_runtime_plan.py \
  scripts/extract_kpp_legacy_iss.py \
  scripts/formal_aw_heft_reference.py \
  scripts/freeze_kpp_frozen_reconstruction_v1.py \
  scripts/freeze_kpp_iss_publication_v3.py \
  scripts/freeze_kpp_legacy_iss_v2_transcodes.py \
  scripts/full_resource_contract.py \
  scripts/kpp_frozen_reconstruction_v1_dataset.py \
  scripts/kpp_iss_publication_v3_dataset.py \
  scripts/kpp_legacy_iss_v2_manifest.py \
  scripts/model_parity_grant.py \
  scripts/publication_acceptance_evidence.py \
  scripts/publication_policy_contract.py \
  scripts/resource_interval_contract.py \
  scripts/topology_contract.py \
  /opt/vast/runtime-root/opt/vast/checkpoint/
COPY \
  deploy/native_gst_probe/checkpoint_admission_transport.hpp \
  deploy/native_gst_probe/checkpoint_analytics_execution_client.hpp \
  deploy/native_gst_probe/checkpoint_analytics_terminal_transport.hpp \
  deploy/native_gst_probe/checkpoint_gstreamer_analytics_bridge.hpp \
  deploy/native_gst_probe/checkpoint_native_policy_client.hpp \
  deploy/native_gst_probe/checkpoint_resource_interval_emitter.hpp \
  deploy/native_gst_probe/checkpoint_runtime_emitter.hpp \
  deploy/native_gst_probe/vast_native_gst_probe.cpp \
  /opt/vast/native-src/
# END VAST_RUNTIME_SOURCE_ALLOWLIST
COPY deploy/openvino_gva/publication/runtime-source-allowlist.txt \
  /opt/vast/runtime-root/opt/vast/runtime-source-allowlist.txt
COPY deploy/openvino_gva/publication/vast_openvino_gva_publication_runtime_v3 \
  /opt/vast/runtime-root/usr/local/bin/vast_openvino_gva_publication_runtime_v3

RUN /usr/bin/c++ \
      -std=c++17 -O2 -DNDEBUG \
      -ffile-prefix-map=/opt/vast/native-src=. \
      -fdebug-prefix-map=/opt/vast/native-src=. \
      $(/usr/bin/pkg-config --cflags \
        gstreamer-1.0 gstreamer-app-1.0 gstreamer-rtp-1.0 gstreamer-video-1.0) \
      /opt/vast/native-src/vast_native_gst_probe.cpp \
      $(/usr/bin/pkg-config --libs \
        gstreamer-1.0 gstreamer-app-1.0 gstreamer-rtp-1.0 gstreamer-video-1.0) \
      -o /opt/vast/runtime-root/usr/local/bin/vast_native_gst_probe \
  && /usr/bin/strip --strip-unneeded \
      /opt/vast/runtime-root/usr/local/bin/vast_native_gst_probe \
  && chmod 0555 \
      /opt/vast/runtime-root/usr/local/bin/vast_native_gst_probe \
      /opt/vast/runtime-root/usr/local/bin/vast_openvino_gva_publication_runtime_v3 \
  && chmod 0444 \
      /opt/vast/runtime-root/opt/vast/checkpoint/*.py \
      /opt/vast/runtime-root/opt/vast/runtime-source-allowlist.txt \
  && find /opt/vast/runtime-root -exec touch -h -d "@${SOURCE_DATE_EPOCH}" {} + \
  && PYTHONDONTWRITEBYTECODE=1 \
     PYTHONPATH=/opt/vast/runtime-root/opt/vast/checkpoint:/opt/vast/runtime-root/opt/vast/python \
     /usr/bin/python3 -B -c 'import checkpoint_openvino_gva_container_coordinator_v3'

FROM ${BASE_IMAGE}

ARG VAST_RUNTIME_SOURCE_SHA256
ARG VAST_DEPENDENCY_SET_SHA256
ARG VAST_NATIVE_PROBE_SOURCE_SHA256
ARG VAST_RUNTIME_SOURCE_ALLOWLIST_SHA256

LABEL org.vast.component="openvino-gva-checkpoint-publication-runtime"
LABEL org.vast.publication-runtime-abi="3"
LABEL org.vast.base-image-id="sha256:5c43c6c1f95b3fbb4a95957d1d293b1272c1db6a44a7a2063aad3aeba7c951d1"
LABEL org.vast.native_probe.kind="openvino-dlstreamer-publication-v3"
LABEL org.vast.native_probe.source_sha="${VAST_NATIVE_PROBE_SOURCE_SHA256}"
LABEL org.vast.runtime-source-sha256="${VAST_RUNTIME_SOURCE_SHA256}"
LABEL org.vast.runtime-dependency-set-sha256="${VAST_DEPENDENCY_SET_SHA256}"
LABEL org.vast.runtime-source-allowlist-sha256="${VAST_RUNTIME_SOURCE_ALLOWLIST_SHA256}"
LABEL org.vast.publication-ready="false"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONNOUSERSITE=1 \
    PYTHONPATH=/opt/vast/checkpoint:/opt/vast/python \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility,video \
    VAST_GST_REGISTRY_TEMPLATE=/opt/vast/share/gstreamer-registry.bin \
    GST_PLUGIN_PATH=/opt/vast/lib/gstreamer-1.0:/opt/intel/dlstreamer/lib:/opt/intel/dlstreamer/gstreamer/lib/gstreamer-1.0:/opt/intel/dlstreamer/gstreamer/lib/

USER root
COPY --from=runtime_builder /opt/vast/runtime-root/ /
USER dlstreamer

ENTRYPOINT ["/usr/local/bin/vast_openvino_gva_publication_runtime_v3"]
