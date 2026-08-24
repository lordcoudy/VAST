# Analytics model parity contract v3

## Scope

This contract is the pre-measurement gate for the four frozen heterogeneous
analytics workload slots. It asks a narrow question: do OpenVINO on exact CPU
and TensorRT on exact NVIDIA CUDA execute derivations of the same pinned ONNX
source with equivalent FP32 classification outputs?

Passing this gate does not claim that ResNet performs license-plate, vehicle,
damage, or foreign-object analytics. The four branch identifiers are stable
matrix positions. Their model semantics are deliberately opaque and the only
permitted scientific claim is `topology_load_proxy_only`. Consequently,
differences measured after this gate can be interpreted as topology/resource
behavior without silently comparing unrelated model families between CPU and
GPU.

The assessor never downloads, converts, builds, starts a container, or runs an
inference. Its only permitted external command is read-only `docker image
inspect`; everything else is local path, hash, schema, and numeric-evidence
validation.

## Frozen workload slots and sources

The source artifact is declared once in `source_registry`; slots refer to it by
ID. An ONNX file is not duplicated or disguised as OpenVINO `weights`.

- `plate_number` -> `opaque_rn18` -> `resnet18_v1_7`
  - revision `e7cb849a949bdceba02356b8b923d53cc01108e1`
  - file `resnet18-v1-7.onnx`, 46,820,737 bytes
  - SHA-256 `4e8f8653e7a2222b3904cc3fe8e304cd8b339ce1d05fd24688162f86fb6df52c`
  - actual parsed ONNX opset 8, IR 0.0.3
  - output `resnetv15_dense0_fwd`
- `vehicle_type` -> `opaque_rn34` -> `resnet34_v1_7`
  - revision `9019d62c2f74b941ae6ce05de1d4013732703765`
  - file `resnet34-v1-7.onnx`, 87,302,588 bytes
  - SHA-256 `883a41b2e30ddc2e422c108b091b5e70b92d37dc5c345a2c563dcae27971e2cc`
  - actual parsed ONNX opset 8, IR 0.0.3
  - output `resnetv16_dense0_fwd`
- `damage` -> `opaque_rn50` -> `resnet50_v1_12`
  - revision `1f95315d8bd3b3ca2ceabe54d274e0cdf5a83bbe`
  - file `resnet50-v1-12.onnx`, 102,576,593 bytes
  - SHA-256 `3f03fdef724b22947eed826f1eef1dc5c34151bb4c37d634f1db89dfa2dd1526`
  - actual parsed ONNX opset 12, IR 0.0.4
  - output `resnetv17_dense0_fwd`
- `foreign_object` -> `opaque_rn101` -> `resnet101_v1_7`
  - revision `524206ecbf2cefaa7654d6e6ff29f9a921f2b1d5`
  - file `resnet101-v1-7.onnx`, 178,914,043 bytes
  - SHA-256 `760702f6ec0138f71ebac66f4e95d1c72dc9267a8544f4d4667a53075fd0497c`
  - actual parsed ONNX opset 8, IR 0.0.3
  - output `resnetv18_dense0_fwd`

All four are Apache-2.0 artifacts from the pinned `onnxmodelzoo/resnet`
repository revisions. Filenames containing `v1-7` do not establish opset 7;
the actual parser metadata above is authoritative.

Each source exposes FP32 `data` in NCHW form with dynamic source batch and
spatial shape 3x224x224. The frozen execution binding is exactly
`[1,3,224,224]`. Each output is FP32 `[1,1000]` raw pre-softmax ImageNet logits.
No implementation may insert softmax before parity comparison. Top-1 ties use
the lowest class index.

## Exact preprocessing

Both runtimes must consume the same pre-materialized FP32 tensor bytes. The
corpus records both the original input SHA-256 and the preprocessed tensor
SHA-256 for every sample. The frozen reference transform is:

1. decoded RGB `uint8` input;
2. aspect-preserving resize of the shorter side to 256 using bilinear,
   half-pixel coordinates and round-half-up sizing;
3. center crop 224x224;
4. scale by 1/255;
5. channel means `[0.485, 0.456, 0.406]` and standard deviations
   `[0.229, 0.224, 0.225]`;
6. FP32 NCHW batch-one output;
7. NumPy v1 little-endian C-contiguous serialization for the hashed tensor.

A change to any value changes the manifest identity and the preprocessing
contract hash to which probes and raw bundles are bound.

## Derived artifacts and toolchains

OpenVINO derivations are pinned to `ovc`
`2026.1.0-21367-63e31528c62-releases/2026/1`, FP32, batch one. Canonical argv
uses `SOURCE.onnx` and `DEST.xml` placeholders rather than host absolute paths.
A repeated RN18 conversion was observed byte-identical, and each archived XML
and BIN has its own exact hash.

TensorRT derivations are pinned to TensorRT 8.6.1.6, CUDA 12.2.2, driver
610.47, RTX 3060, UUID `GPU-00bb784b-60f3-8bf6-bbd3-5a0c09805266`, PCI
`00000000:01:00.0`, compute capability 8.6, static batch one, FP32, and
`--noTF32`. The complete normalized `trtexec` argv and its canonical hash are
in the manifest.

TensorRT tactic selection is not byte-reproducible: a repeated RN18 build with
the same image, argv, GPU, and driver produced a different engine SHA-256.
Therefore the archived exact engine is authoritative and must never be
silently rebuilt during resume. Toolchain, argv, GPU, driver, and any future
layer/tactic manifest are provenance, not a promise that rebuild bytes match.

TensorRT 8.6 reported that ONNX INT64 weights were cast to INT32 for all four
models. The manifest records this parser fact. It is not by itself a blocker; the
raw numeric parity gate decides whether the resulting execution is acceptable.

## Base/toolchain versus worker runtime identity

Schema v3 deliberately preserves two different immutable identities. The
`matrix_binding` and `toolchain_registry` image references identify the base
converter/builder environment and remain the objects of the assessor's
read-only `docker image inspect`. They are provenance and are never relabelled
as the image that served an inference request.

`worker_runtime_registry` separately binds the actual derived OpenVINO and
TensorRT worker image IDs and each worker implementation SHA-256. Its
`execution_config` record pins the physical execution config SHA-256, its
unchanged sorted-compact-JSON content identity, and a canonical hash of the
two worker projections. Each projection also repeats and cross-binds the base
image identity, so either a base/toolchain drift or a derived worker drift is
fail-closed. Execution probes carry both actual `runtime_image_id` and
`worker_implementation_sha256`; policy and raw bundles bind that exact probe
by SHA-256 and repeat its actual worker image ID.

## Mandatory evidence

Every slot requires exactly eight hash-bound JSON artifacts:

- an exact OpenVINO CPU execution probe;
- an exact TensorRT NVIDIA CUDA execution probe;
- an immutable calibration corpus;
- a disjoint immutable evaluation corpus;
- CPU policy-calibration evidence;
- CUDA policy-calibration evidence;
- CPU raw per-sample output bundle;
- CUDA raw per-sample output bundle.

Execution probes bind source, derived artifact hashes, actual worker runtime
image ID and worker implementation SHA-256,
device identity, preprocessing/output contract hashes, exact tensor names,
shape, dtype, success, sample count, and output finiteness. `OPENVINO_GPU`
never satisfies the NVIDIA CUDA resource.

Corpus manifests contain an ordered `samples` array. Each record has exactly
`sample_id`, `input_sha256`, and `preprocessed_tensor_sha256`; the whole array
also has a canonical SHA-256. Calibration and evaluation IDs must be disjoint.
Both corpora require at least 30 unique samples per branch.

Policy calibration is separate from model parity. Each CPU and CUDA resource
requires at least 30 ordered, finite, positive `service_time_ms` observations
bound to the calibration corpus, exact execution probe, runtime image, source,
and derived artifacts. These observations support scheduling-policy
calibration; they are not inference equivalence metrics.

## Raw-output recomputation

A raw bundle contains no trusted `metrics` or `passed` field. Extra fields make
its exact schema invalid. For each ordered evaluation sample it carries the
same input/preprocessed hashes and exactly 1000 finite numeric logits. CPU and
CUDA bundles must have identical order, tensor name, FP32 dtype, shape
`[1,1000]`, corpus hash, semantic hashes, image/probe identity, and artifact
lineage.

The assessor recomputes, per sample:

- maximum absolute logit error;
- maximum symmetric relative logit error with denominator floor 1e-6;
- mean absolute logit error;
- cosine distance;
- CPU and CUDA top-1 indices and equality.

It then recomputes global maximum absolute error, global maximum relative
error, mean absolute error over all logits, maximum cosine distance, and top-1
mismatch rate. Frozen limits are 0.02, 0.05, 0.005, 0.001, and 0.0,
respectively. Publication readiness requires every recomputed metric to pass
for every branch.

This closes the v1 evidence gap: a producer cannot submit favorable aggregate
numbers without the raw per-sample bundle from which the assessor derives
them.

## Fail-closed file handling

Manifest, source, IR, BIN, engine, corpus, probe, calibration, and bundle paths
must stay lexical and resolved descendants of the selected project root.
Symlinks are rejected before content is accepted. Artifact bytes must match
the declared lowercase SHA-256. JSON evidence is capped at 64 MiB, must be
UTF-8, rejects duplicate keys, and rejects `NaN`/`Infinity`. YAML duplicate
keys are also rejected. The complete canonical manifest and assessment carry
the established identity envelope (`schema_version: 2`,
`sorted_compact_json_utf8_v2`). Manifest schema evolution does not silently
change that top-level content-identity algorithm/version.

## Commands and exit contract

```text
python scripts/checkpoint_model_parity.py manifest
python scripts/checkpoint_model_parity.py assess
```

`manifest` validates and emits the canonical identity. `assess` returns 0 only
when the full contract passes and 78 for a blocked or invalid contract. It does
not provide a build, download, container-run, or measurement command.

## Current repository state

As of the v3 refreeze, all four ONNX sources, all four OpenVINO XML/BIN pairs,
all four archived TensorRT engines, and both pinned runtime images pass local
identity checks. Read-only smoke observations also showed OpenVINO CPU compile
and one finite `[1,1000]` inference, plus TensorRT engine deserialize and one
finite CUDA inference for every model. Those console observations are not
hash-bound JSON and therefore are deliberately not accepted as publication
evidence.

`publication_ready` remains false. For every branch the eight mandatory
evidence references are still absent/unhashed: two execution probes, two
corpora, two resource-specific policy calibrations, and two raw output bundles.
No source, derived artifact, or runtime image is currently missing. Measurement
arms must remain blocked until durable evidence is generated, archived, pinned
in the manifest, and the assessor returns zero.

The publication entrypoint must later consume schema v3 directly: bind the
parity manifest identity, assessment identity, source-registry artifacts,
derived artifacts, corpora, probes, calibrations, and raw bundles. It must not
map ONNX into the old repeated `model_path`/`weights_path` pair or weaken the
lexical/symlink checks during integration.
