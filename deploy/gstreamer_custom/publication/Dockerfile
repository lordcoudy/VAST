ARG BASE_IMAGE=vast/openvino-native-probe@sha256:fc26a96b600484da32fc304461a0484225b931e0e1ddfc9a1f112414d737b16a
ARG SOURCE_DATE_EPOCH=0

FROM ${BASE_IMAGE} AS native-provider

FROM ${BASE_IMAGE} AS runtime_builder

ARG SOURCE_DATE_EPOCH
USER root

RUN install -d -m 0755 \
      /opt/vast/runtime-root/opt/vast/checkpoint \
      /opt/vast/runtime-root/opt/vast/lib/gstreamer-1.0 \
      /opt/vast/runtime-root/opt/vast/python \
      /opt/vast/runtime-root/opt/vast/share \
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
COPY scripts/checkpoint_deepstream_protocol_bridge.py /workspace/scripts/
COPY \
  scripts/analytics_execution_endpoint.py \
  scripts/analytics_execution_protocol.py \
  scripts/analytics_execution_worker.py \
  scripts/analytics_model_contract.py \
  scripts/backend_publication_dispatch.py \
  scripts/backend_publication_launcher_invocation_v3.py \
  scripts/backend_publication_output_receipt.py \
  scripts/backend_publication_runtime_authority.py \
  scripts/backend_runtime_grant.py \
  scripts/backend_runtime_qualification_v3.py \
  scripts/benchmark_contract.py \
  scripts/checkpoint_acceptance_metadata_binding.py \
  scripts/checkpoint_admission.py \
  scripts/checkpoint_deepstream_qualification_fragment_v1.py \
  scripts/checkpoint_gstreamer_analytics_bridge.py \
  scripts/checkpoint_gstreamer_analytics_sidecar.py \
  scripts/checkpoint_gstreamer_custom_container_coordinator_v3.py \
  scripts/checkpoint_gstreamer_runtime.py \
  scripts/checkpoint_model_parity.py \
  scripts/checkpoint_model_parity_acceptance.py \
  scripts/checkpoint_model_parity_acceptance_v4.py \
  scripts/checkpoint_model_parity_v4.py \
  scripts/checkpoint_native_policy_runtime.py \
  scripts/checkpoint_publication_runtime.py \
  scripts/checkpoint_qualification_pilot_acceptance_v1.py \
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
  scripts/publication_guardian_accepted_policy_preprocessing_contract_v1.py \
  scripts/publication_guardian_preprocessing_contract_v1.py \
  scripts/publication_guardian_runtime_expectations_v1.py \
  scripts/publication_owned_staging_cleanup_v1.py \
  scripts/publication_physical_io_v1.py \
  scripts/publication_policy_contract.py \
  scripts/publication_policy_qualification.py \
  scripts/publication_policy_qualification_execution_closure_v1.py \
  scripts/publication_qualification_image_refreeze_v1.py \
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
COPY deploy/gstreamer_custom/publication/runtime-source-allowlist.txt \
  /opt/vast/runtime-root/opt/vast/runtime-source-allowlist.txt
COPY deploy/gstreamer_custom/publication/vast_gstreamer_custom_publication_runtime_v3 \
  /opt/vast/runtime-root/usr/local/bin/vast_gstreamer_custom_publication_runtime_v3

COPY --from=native-provider /usr/local/bin/vast_native_gst_probe /opt/vast/runtime-root/usr/local/bin/vast_native_gst_probe
COPY --from=native-provider /usr/local/bin/vast_checkpoint_source /opt/vast/runtime-root/usr/local/bin/vast_checkpoint_source
COPY --from=native-provider /opt/vast/lib/gstreamer-1.0/libgstadaptivescheduler.so /opt/vast/runtime-root/opt/vast/lib/gstreamer-1.0/libgstadaptivescheduler.so
COPY --from=native-provider /opt/vast/lib/gstreamer-1.0/libgstvastanalyticsterminal.so /opt/vast/runtime-root/opt/vast/lib/gstreamer-1.0/libgstvastanalyticsterminal.so
COPY --from=native-provider /opt/vast/lib/gstreamer-1.0/libgstvastanalyticsqueue.so /opt/vast/runtime-root/opt/vast/lib/gstreamer-1.0/libgstvastanalyticsqueue.so
COPY --from=native-provider /opt/vast/lib/gstreamer-1.0/libgstvastcheckpointprefixqueue.so /opt/vast/runtime-root/opt/vast/lib/gstreamer-1.0/libgstvastcheckpointprefixqueue.so
COPY --from=native-provider /opt/vast/share/gstreamer-registry.bin /opt/vast/runtime-root/opt/vast/share/gstreamer-registry.bin

RUN chmod 0555 \
      /opt/vast/runtime-root/usr/local/bin/vast_native_gst_probe \
      /opt/vast/runtime-root/usr/local/bin/vast_checkpoint_source \
      /opt/vast/runtime-root/usr/local/bin/vast_gstreamer_custom_publication_runtime_v3 \
      /opt/vast/runtime-root/opt/vast/lib/gstreamer-1.0/*.so \
  && chmod 0444 \
      /opt/vast/runtime-root/opt/vast/checkpoint/*.py \
      /opt/vast/runtime-root/opt/vast/share/gstreamer-registry.bin \
      /opt/vast/runtime-root/opt/vast/runtime-source-allowlist.txt \
  && find /opt/vast/runtime-root -exec touch -h -d "@${SOURCE_DATE_EPOCH}" {} + \
  && PYTHONDONTWRITEBYTECODE=1 \
     PYTHONPATH=/opt/vast/runtime-root/opt/vast/checkpoint:/opt/vast/runtime-root/opt/vast/python \
     /usr/bin/python3 -B -c 'import checkpoint_gstreamer_custom_container_coordinator_v3'

FROM ${BASE_IMAGE}

ARG VAST_RUNTIME_SOURCE_SHA256
ARG VAST_DEPENDENCY_SET_SHA256
ARG VAST_NATIVE_PROBE_SOURCE_SHA256
ARG VAST_BASE_IMAGE_ID

LABEL org.vast.component="gstreamer-custom-checkpoint-publication-runtime"
LABEL org.vast.publication-runtime-abi="3"
LABEL org.vast.base-image-id="${VAST_BASE_IMAGE_ID}"
LABEL org.vast.native_probe.source_sha="${VAST_NATIVE_PROBE_SOURCE_SHA256}"
LABEL org.vast.runtime-source-sha256="${VAST_RUNTIME_SOURCE_SHA256}"
LABEL org.vast.runtime-dependency-set-sha256="${VAST_DEPENDENCY_SET_SHA256}"
LABEL org.vast.claim-status="deterministic-image-awaiting-exact-kpp-v3-gpu-pilots"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONNOUSERSITE=1 \
    PYTHONPATH=/opt/vast/checkpoint:/opt/vast/python \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility,video \
    VAST_GST_REGISTRY_TEMPLATE=/opt/vast/share/gstreamer-registry.bin \
    GST_PLUGIN_PATH=/opt/vast/lib/gstreamer-1.0:/opt/intel/dlstreamer/lib:/opt/intel/dlstreamer/gstreamer/lib/gstreamer-1.0:/opt/intel/dlstreamer/gstreamer/lib/

USER root
COPY --from=runtime_builder /opt/vast/runtime-root/ /
USER dlstreamer

ENTRYPOINT ["/usr/local/bin/vast_gstreamer_custom_publication_runtime_v3"]
