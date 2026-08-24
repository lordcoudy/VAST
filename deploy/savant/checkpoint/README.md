# Savant checkpoint capability layer

This directory contains a read-only engineering probe for the immutable image
`ghcr.io/insight-platform/savant-deepstream:0.5.17-7.0`
(`sha256:3c0ef6f4bb57e385644da526789626f0c943dcb90ff32b72a7883e05798ce9e6`).

The topology plan is generated and validated by
`scripts/checkpoint_savant_runtime.py`.  It freezes:

- six logical input streams and both H264/H265 parser bindings;
- 24 isolated Savant module processes for the baseline;
- six shared decode/preprocess module processes with four bounded queued
  analytics routes each for the Video-DAG;
- protocol-v3 common admission, native policy request/response/path/terminal
  field names, and equal paired schedule fingerprints;
- explicit `nvv4l2decoder` NVDEC placement and an `nvinfer` +
  `deepstream_tensorrt` + `NVIDIA_CUDA` GPU analytics requirement.

The existing `deploy/savant/module.yml` and canonical pyfunc/PeopleNet modules
are not accepted as the checkpoint runtime.  They use generic URI/JPEG sources
and sample analytics, and do not implement frozen per-frame CPU/CUDA policy
routing or native terminal/resource-v2 evidence.

Run the capability-only preflight:

```bash
python scripts/checkpoint_savant_runtime.py probe
```

The command mounts only the probe directory and the two codec sample
directories read-only.  It imports Savant 0.5.17, inspects required plugins,
checks the visible NVIDIA GPU, and decodes one H264 and one H265 buffer through
`nvv4l2decoder`.

Probe success is not benchmark readiness.  Schema v1 always keeps
`publication_ready=false` until a dedicated Savant runtime and module configs,
protocol-v3 native policy routing, equivalent frozen CPU/CUDA branch models, an
accepted resource-v2 emitter, and paired hardware pilots exist.
