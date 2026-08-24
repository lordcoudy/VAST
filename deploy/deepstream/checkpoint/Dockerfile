ARG BASE_IMAGE=nvcr.io/nvidia/deepstream:7.0-triton-multiarch
FROM ${BASE_IMAGE}

LABEL org.vast.component="deepstream-checkpoint-capability-probe"
LABEL org.vast.claim-status="engineering-capability-probe-not-measurement"
LABEL org.vast.publication-ready="false"

COPY deploy/deepstream/checkpoint/deepstream_checkpoint_capability_probe.py \
  /opt/vast/checkpoint/deepstream_checkpoint_capability_probe.py

ENTRYPOINT ["python3", "/opt/vast/checkpoint/deepstream_checkpoint_capability_probe.py"]
