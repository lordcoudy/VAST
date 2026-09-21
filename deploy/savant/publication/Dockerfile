ARG SOURCE_DATE_EPOCH=1722470400
ARG NATIVE_BUILDER_IMAGE=vast/savant-native-probe:0.5.17-7.0
ARG SAVANT_BASE_IMAGE=ghcr.io/insight-platform/savant-deepstream:0.5.17-7.0

FROM ${NATIVE_BUILDER_IMAGE} AS native-builder

FROM ${SAVANT_BASE_IMAGE}

ARG VAST_SAVANT_RUNTIME_SOURCE_SHA256=unknown
ARG VAST_SAVANT_RUNTIME_BUNDLE_SHA256=unknown
ARG VAST_BASE_IMAGE_ID
ARG VAST_NATIVE_BUILDER_IMAGE_ID
ARG VAST_NATIVE_BUILDER_SOURCE_SHA256
LABEL org.vast.component="savant-checkpoint-publication-runtime"
LABEL org.vast.savant.publication-runtime="v3"
LABEL org.vast.publication-runtime-abi="3"
LABEL org.vast.savant.version="0.5.17"
LABEL org.vast.deepstream.version="7.0"
LABEL org.vast.base-image-id="${VAST_BASE_IMAGE_ID}"
LABEL org.vast.native-builder-image-id="${VAST_NATIVE_BUILDER_IMAGE_ID}"
LABEL org.vast.native-builder-source-sha256="${VAST_NATIVE_BUILDER_SOURCE_SHA256}"
LABEL org.vast.savant.runtime-source-sha256="${VAST_SAVANT_RUNTIME_SOURCE_SHA256}"
LABEL org.vast.savant.runtime-bundle-sha256="${VAST_SAVANT_RUNTIME_BUNDLE_SHA256}"
LABEL org.vast.claim-status="native-sdk-runtime-awaiting-endpoint-bound-full-arm"
LABEL org.vast.publication-ready="false"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONNOUSERSITE=1 \
    PYTHONPATH=/opt/vast/checkpoint:/opt/savant \
    VAST_NATIVE_PYTHONPATH=/opt/vast/checkpoint:/opt/savant \
    GST_PLUGIN_PATH=/usr/local/lib/gstreamer-1.0:${GST_PLUGIN_PATH} \
    SAVANT_STATUS_FILEPATH=/tmp/vast-savant-status.txt

# BEGIN VAST_RUNTIME_DEPENDENCY_ALLOWLIST
COPY deploy/deepstream/checkpoint/requirements.lock /tmp/vast-python/requirements.lock
# BEGIN VAST_SAVANT_RUNTIME_SOURCE_ALLOWLIST
COPY \
  deploy/deepstream/checkpoint/wheels/PyYAML-6.0.2-cp310-cp310-manylinux_2_17_x86_64.manylinux2014_x86_64.whl \
  deploy/deepstream/checkpoint/wheels/numpy-1.26.4-cp310-cp310-manylinux_2_17_x86_64.manylinux2014_x86_64.whl \
  deploy/deepstream/checkpoint/wheels/pandas-2.2.3-cp310-cp310-manylinux_2_17_x86_64.manylinux2014_x86_64.whl \
  deploy/deepstream/checkpoint/wheels/python_dateutil-2.9.0.post0-py2.py3-none-any.whl \
  deploy/deepstream/checkpoint/wheels/pytz-2026.3.post1-py2.py3-none-any.whl \
  deploy/deepstream/checkpoint/wheels/six-1.17.0-py2.py3-none-any.whl \
  deploy/deepstream/checkpoint/wheels/tzdata-2026.3-py2.py3-none-any.whl \
  /tmp/vast-python/wheels/
# END VAST_RUNTIME_DEPENDENCY_ALLOWLIST
RUN python3 -m pip install \
      --no-index --no-compile --find-links=/tmp/vast-python/wheels \
      --require-hashes -r /tmp/vast-python/requirements.lock \
    && rm -rf /tmp/vast-python

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
  scripts/checkpoint_deepstream_protocol_adapter.py \
  scripts/checkpoint_deepstream_protocol_bridge.py \
  scripts/checkpoint_deepstream_qualification_fragment_v1.py \
  scripts/checkpoint_deepstream_resource_runtime_v3.py \
  scripts/checkpoint_deepstream_sdk_runtime.py \
  scripts/checkpoint_gstreamer_analytics_bridge.py \
  scripts/checkpoint_gstreamer_analytics_sidecar.py \
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
  scripts/checkpoint_savant_container_runtime_v3.py \
  scripts/checkpoint_savant_ingress.py \
  scripts/checkpoint_savant_launcher.py \
  scripts/checkpoint_savant_native_module.py \
  scripts/checkpoint_savant_protocol_adapter_v3.py \
  scripts/checkpoint_savant_protocol_bridge.py \
  scripts/checkpoint_savant_publication_specs_v3.py \
  scripts/checkpoint_savant_pyfunc_v3.py \
  scripts/checkpoint_savant_resource_runtime_v3.py \
  scripts/checkpoint_savant_runtime.py \
  scripts/checkpoint_savant_sdk_runtime_v3.py \
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
  /opt/vast/checkpoint/
# END VAST_SAVANT_RUNTIME_SOURCE_ALLOWLIST
COPY configs/checkpoint_analytics_models_openvino.yaml /opt/vast/configs/checkpoint_analytics_models_openvino.yaml
COPY deploy/savant/publication/runtime-source-allowlist.txt \
  /opt/vast/runtime-source-allowlist.txt
COPY deploy/deepstream/checkpoint/runtime-dependency-allowlist.txt \
  /opt/vast/runtime-dependency-allowlist.txt
COPY deploy/savant/publication/vast_savant_checkpoint_runtime /usr/local/bin/vast_savant_checkpoint_runtime
COPY --from=native-builder /usr/local/bin/vast_checkpoint_source /usr/local/bin/vast_checkpoint_source
COPY --from=native-builder /usr/local/lib/gstreamer-1.0/libgstvastcheckpointbranchqueue.so /usr/local/lib/gstreamer-1.0/libgstvastcheckpointbranchqueue.so

RUN chmod 0555 /usr/local/bin/vast_savant_checkpoint_runtime \
      /usr/local/bin/vast_checkpoint_source \
    && chmod 0444 /opt/vast/checkpoint/*.py \
      /opt/vast/configs/checkpoint_analytics_models_openvino.yaml \
      /opt/vast/runtime-source-allowlist.txt \
      /opt/vast/runtime-dependency-allowlist.txt \
    && ( /usr/local/bin/vast_checkpoint_source --help >/dev/null 2>&1; test "$?" -eq 2 ) \
    && PYTHONDONTWRITEBYTECODE=1 python3 -B -c \
      'import checkpoint_savant_sdk_runtime_v3; import checkpoint_savant_native_module' \
    && python3 -B -c \
      'import gi; gi.require_version("Gst", "1.0"); from gi.repository import Gst; Gst.init(None); assert Gst.ElementFactory.make("vastcheckpointbranchqueue") is not None' \
    && python3 -B /opt/vast/checkpoint/checkpoint_savant_container_runtime_v3.py --help >/dev/null

ENTRYPOINT ["/usr/local/bin/vast_savant_checkpoint_runtime"]
