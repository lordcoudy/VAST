# Native dual analytics execution layer

This directory contains two separate native workers behind one bounded Linux
IPC contract.  The OpenVINO worker compiles an exact XML/BIN pair on `CPU`.
The TensorRT worker deserializes an exact immutable `.engine` on the declared
NVIDIA GPU and calls `IExecutionContext::enqueueV3`.  OpenVINO `GPU` is never
accepted as NVIDIA CUDA evidence.

The coordinator and each worker use an `AF_UNIX` `SOCK_SEQPACKET` connection.
Canonical JSON carries only bounded control metadata.  A real preprocessed
tensor is passed as a fully sealed `memfd` with `SCM_RIGHTS`; the result is
returned in a second sealed `memfd`.  A worker is serial and admits exactly one
in-flight request.

Every handshake binds the protocol identity, worker image ID, implementation
digest, branch, source-model digest, runtime-artifact digest, preprocessing
contract, output contract, runtime, device API and physical device identity.
Every successful response repeats the frame/PTS identity and binds input and
output byte digests, native inference API, monotonic latency and process/CUDA
resource fields.  A backend-specific DeepStream, Savant, OpenVINO or custom
GStreamer runtime may emit its branch terminal only after validating that
response and its output memfd.

The TensorRT engine is authoritative and immutable.  The worker verifies its
SHA-256 over the same bytes it deserializes.  It never builds or rebuilds an
engine.  A missing or changed engine is a permanent contract failure because
TensorRT serialization is not byte-reproducible on the current toolchain.

`--capability` performs no model load and no inference.  It only attests the
runtime library, CPU/GPU device API and the three required IPC primitives.
Publication execution remains blocked until the model-parity manifest and its
calibration/evaluation evidence pass independently.
