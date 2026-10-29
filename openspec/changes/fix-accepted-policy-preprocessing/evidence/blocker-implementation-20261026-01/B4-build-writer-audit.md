# Independent builder/storage completeness audit, source only

Review of approved B4 planning and the existing four build scripts/handoff at
7f243... found that enforcement is still absent. No operator/VHD allocation,
Docker/service/workload/API/command or edit was performed by this audit. These
are source/filesystem observations, not authenticated execution receipts or
proof that eight A/B builds fit96GiB. Physical allocation/execution remain HOLD.

Literal context unions in build_openvino_gva_publication_runtime_v3.sh,
build_gstreamer_custom_publication_runtime_v3.sh,
build_deepstream_publication_runtime_v3.sh and
build_savant_publication_runtime_v3.sh respectively:

- OpenVINO:92files,32564680B.
- GStreamer:92files,32565126B.
- DeepStream:95files,36935584B.
- Savant:98files,36974699B.

One context serves each A/B pair:4retained contexts,377files,139040089logical
bytes;4KiB payload rounding139825152B plus32directories and separate metadata.
Current materializer success text is5240..5302B. All builders still use literal
/tmp paths with unconditional EXIT context deletion. Explicit checked S roots
and retained failures are required; TMPDIR alone cannot redirect literal paths.

Wheel central directories provide finite INPUT forms only. OpenVINO/GStreamer
each have5wheels,28769167compressed file bytes,100317758uncompressed bytes,
2781entries. DeepStream/Savant each have7wheels,33153731compressed file bytes,
113336910uncompressed bytes,3980entries. Across8builds:854618672uncompressed
wheel-input bytes and27044entries. This does not bound installations, metadata,
temporary extraction, caches/snapshots or source-provider assets.

Actual source schedule includes20RUN instructions,8pip installs,4g++ calls and
92COPY instructions across A/B, plus6post-build Docker verification containers
(OpenVINO2/GStreamer2/DeepStream1/Savant1). Mutable layers/logs/tmpfs and backend
retirement of these six belong in the ledger, beyond eight image builds.
Retain COPY payloads even after later-layer rm; no failure/cleanup/cache credit.

Required narrow implementation gaps:

- Existing materialize_runtime_build_context_v3.py lacks pre-allocation aggregate
  bytes/file-count/deadline admission and checks copied size only after EOF.
  Authenticate fixed manifests/member bytes first; refuse growth before forwarding
  the oversized block. Preserve bytes/modes/timestamps/package inventory.
- Handoff copies all os.environ, leaving Docker/buildx selectors, config/activity/
  caches/temp, Python bytecode and shell startup uncontrolled. Seal installed CLI/
  plugin identities, native endpoint, existing builder/driver and small explicit
  environment; writable client paths go on S. DOCKER_HOST alone is insufficient.
- DeepStream/Savant use Docker exporter type=docker,rewrite-timestamp=true,
  unpack=false. Preserve it; this is not docker image save. Bind actual builder/
  client/export/load staging. unpack=false is no proof of absent temporary copies.
- Handoff subprocess lacks inherited deadline/bounded capture; client retirement
  does not prove daemon-owned BuildKit/verification-container retirement.
- Enclose both Docker/containerd stores plus BuildKit, daemon temp, service stdout/
  stderr/journals,/run state,tmpfs,swap and crash-handler outputs. Host TMPDIR does
  not set build RUN environment. CORE1/filter alone cannot prove an arbitrary piped
  handler's destination: qualify actual daemon/RUN policy or fund outside/HOLD.
- Verify exact VHD/device/UUID/usable capacity and both bind sources in service
  mount namespaces before startup. Stop socket activation during offline copy,
  couple lifetimes, refuse hidden-original fallback. Preserve daemon ID/socket,
  provider/runtime/driver/cgroup/security settings; renew inode/device-epoch facts.
- Savant manifest is an external project artifact with temporary sibling; handoff
  artifact_dir must remain under project_root. Bound/price it outside S rather
  than weakening custody. Its inspect helper checks8MiB only after capture_output;
  capture must be bounded while reading. Preserve complete RepoDigest sets.

Whole peak still needs authenticated base blobs/unpacked snapshots/native assets,
mutable build/cache/export forms and retained failures against USABLE S capacity.
No-cache, later A/B equality, garbage collection or the96GiB ceiling proves fit.
Keep base manifest/index digests distinct from receipt-backed image-config IDs.
Preserve dependency locks/offline hash flags/Python versions/native assets and
timestamp normalization. Use the literal one-time store operator/mount guards
already designed, not a general migrator, new provider/builder, prune or offload.
