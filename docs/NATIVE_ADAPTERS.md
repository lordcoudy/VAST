# Native adapter contract

Publishable `--mode benchmark` runs require each adapter to write schema-v2
telemetry directly from its pipeline probes. The harness intentionally refuses
to derive scientific metrics from process duration.

## Local adapters

Each configured system command receives:

- `EXPERIMENT_RUN_ID`
- `EXPERIMENT_SCENARIO_JSON`
- `EXPERIMENT_PIPELINE_STAGES`
- `SCHEDULER_POLICY`
- `ADAPTER_DETECTOR`
- `ADAPTER_BACKEND`
- `VIDEO_LAYOUT_DIR`
- `DATASET_STREAMS_JSON`
- `EXPERIMENT_RUN_SEED`

The command must publish:

- `frames.csv`: one row per completed frame using the columns defined in
  `scripts/benchmark_contract.py::FRAME_COLUMNS`
- `frame_events.csv`: one row per stage execution using
  `scripts/benchmark_contract.py::FRAME_EVENT_COLUMNS`

Adapters may write intermediate `frame_events*.csv` fragments inside
per-stream or per-role output directories before merge. Strict validation reads
every raw fragment row before measured-frame filtering, so malformed rows are
rejected even when they fall outside the measurement window. Savant local writes
per-stage fragments such as `frame_events_decode.csv`, `frame_events_detect.csv`,
`frame_events_track.csv`, `frame_events_classify.csv`, `frame_events_aggregate.csv`,
and `frame_events_record.csv` to avoid concurrent writes to one file. Only stages
listed in `EXPERIMENT_PIPELINE_STAGES` are required; the merge publishes the
benchmark root `frame_events.csv`.

DeepStream and Savant adapters should use GStreamer pad probes. OpenVINO+GVA
and GStreamer custom adapters should use source/sink pad probes. The custom
CUDA+Qt adapter writes both files directly for diagnostic signal runs, but it
does not yet consume the configured video dataset and is excluded from strict
benchmark mode.

## Topology trace

Dissertation checkpoint scenarios additionally require `topology_events.csv`
with topology contract version 1. Each row contains:

- schema/run/trace/stream/frame identity and a stable `input_frame_key`;
- `topology_kind`, `event_kind`, exact stage, and branch ID;
- unique execution ID, JSON parent execution IDs, and execution-domain ID;
- event timestamp, `event_provenance=native_runtime_event`, and
  `telemetry_source=native`.

Allowed event kinds are `source_read`, `stage_complete`, `fanout`,
`branch_complete`, and `join_complete`. Every `stage_complete` must match
exactly one native `frame_events.csv` row by run/trace/stream/frame/stage and
stage-end timestamp. All events for a completed trace must use one
`input_frame_key`, stay within its ingress/egress interval, use unique execution
IDs, and reference parents from the same frame trace that complete no later
than their children.

For `independent_processes`, every required branch has its own
source/decode/preprocess/analytics chain in one branch-local execution domain;
domains must differ across branches. For `shared_video_dag`, one shared
source/decode/preprocess prefix parents one native fanout per branch. Both kinds
require a join whose parent set equals the complete set of branch-completion
executions. Repeated stage labels, derived rows, timestamp splitting, or a
shared baseline process fail the contract. `topology_trace_complete=true` is
written to the summary only after this validation succeeds.

Topology contract v1 is defined for the explicit
`routing_mode=all_branches_per_stream` profile. The checkpoint scenarios select
this route explicitly as a non-production `topology_only_stress` profile; the
KPP manifests retain dataset-level `analytics_routing=unresolved` because six
logical stream entries are replicas of two recordings and their `camera_role`
labels do not define the four-branch production route. The validator rejects
an unresolved or mismatched scenario-level route. If per-source routing is
selected, the contract and event-factor analysis must be extended to validate
the required branch set and multiplicity for each `source_id`; changing only
the labels is not sufficient.

## Checkpoint branch terminals

Checkpoint adapters must also publish `branch_terminals.csv` with the columns
defined by `BRANCH_TERMINAL_COLUMNS`. Each row is a native analytics terminal
event for one admitted frame and required branch. It carries the ingress
cohort identity, `input_frame_key`, branch, terminal timestamp, accepted object
count, detector/backend identity, reason, and terminal provenance.

`branch_complete` uses `native_completion_event`; `branch_drop` uses
`native_drop_event` and reports zero accepted objects. A completed or dropped
ingress row must have exactly one terminal event for every required branch. If
one or more branches have no terminal event by the drain boundary, the ingress
row is `censored`; missing completion is never converted to `drop`. A censored
row may not contain a native branch drop event.

Because schema-v2 `frames.csv` has one unique `trace_id` per row, a checkpoint
frame is represented as one end-to-end aggregate only after all branches
complete. Its `detector` is
`checkpoint_all_branches_per_stream_v1`, `objects` is the sum of accepted
branch object counts, and egress time is the latest branch terminal time.
Branch-specific detector results remain in `branch_terminals.csv`. The default
identity checkpoint probe does not satisfy this contract and must not emit the
accepted sidecar.

The source-level checkpoint worker exposes a strict live bridge for a real
analytics element. `topology_only` mode preserves the legacy buffer-reach
completion used by engineering topology checks. In
`native_terminal_socket_v1` mode the detect-bin must be non-identity and must
contain a `{branch}` placeholder so the shared graph cannot silently reuse one
unlabelled detector instance for every route. The element includes
`checkpoint_analytics_terminal_transport.hpp`, borrows the descriptor from
`VAST_CHECKPOINT_ANALYTICS_TERMINAL_FD`, and sends one bounded binary datagram
for the exact `GST_BUFFER_PTS`. The datagram carries the declared branch,
`completed` or `drop`, accepted object count, reason, and detector/backend
identity. Identity/topology-only detector or backend labels, control
characters, undeclared branches, duplicate outcomes, unknown PTS, and a drop
with nonzero objects are rejected. Missing terminal messages remain censored.

The worker matches the datagram to its verified direct-admission trace and
only then emits protocol-v3 `branch_complete`/`branch_drop`. The coordinator
retains those fields separately from the topology trace. The engineering
launcher may serialize them as `branch_terminals.runtime.csv` with
`telemetry_source=engineering_runtime` and a companion audit. This file is
deliberately rejected by the accepted sidecar validator. Promotion still
requires a real detector/model run, target KPP execution, accepted ingress and
aggregate frame linkage, and the remaining publication gates.

Checkpoint adapters must also emit `reset_evidence.csv` directly from the
native process lifecycle, queue snapshots, direct-admission origin, and
telemetry-sink creation path. Contract version 1 has one row per source or
worker process. Source rows prove first cycle 0/admission sequence 1; worker
rows provide a zero-depth map for every owned preregistered analytics queue.
All rows name an observed PID, a unique process-start SHA-256 token, one new
empty telemetry-sink SHA-256 ID, excluded warmup, stop-admission before drain,
and terminal `DRAINED` state. Baseline/shared report pairing additionally
requires disjoint process tokens and different sink IDs. Configuration values,
fresh-directory assumptions, and the engineering
`reset_evidence.runtime.csv` cannot be promoted to accepted reset evidence.

The repository reference element is `vastanalyticsterminal`. It is an in-place
metadata consumer that must immediately follow `gvadetect` or `object_detect`.
At startup it verifies that the observed factory equals the declared
`expected-upstream-factory` and that the upstream element exposes a non-empty
string `model` property. It recomputes SHA-256 of that exact artifact and, for
an OpenVINO `.xml` model, of the sibling `.bin`, then compares both with the
preregistered binding. For every detector output with valid PTS it counts
`GstVideoRegionOfInterestMeta` and emits one `completed` terminal, including
zero-object results. It does not equate zero ROI or missing output with drop.

The corresponding explicit overload producer is `vastanalyticsqueue`. It must
be placed immediately before the same detector and verifies the downstream
factory plus the same model/weights digests. The element owns an asynchronous
waiting queue with a required preregistered `max-buffers` value. When that
waiting queue is full, it rejects only the newest incoming buffer and emits
`branch_drop` for that buffer's exact PTS with reason
`native_pre_detector_queue_full_drop_newest`. It does not turn flush, shutdown,
downstream failure, or absent detector output into drop; those admissions are
resolved by the normal drain/censoring contract. CMake builds and transport
integration tests for both elements are available. The queue test blocks the
first test-only detector call, fills one waiting slot, and verifies the exact
PTS of the third admission. No real DL Streamer plugin/model or KPP media has
passed through this path in this workspace.

Branch-specific bindings are supplied through an external schema-v1
`checkpoint_analytics_model_bindings` manifest. The engineering launcher
requires exact branch coverage, recomputes model/weights digests, and exports
separate values for every worker branch. The native detect-bin template must
contain `{branch}`, `{factory}`, `{model_path}`, `{model_sha256}`,
`{weights_sha256}`, `{detector_id}`, and `{max_buffers}`, and must contain both
reference elements around the detector. The queue capacity is supplied
by the validated primary blueprint because it is an execution coordinate
rather than model provenance. Contract version 1 fixes one waiting buffer per
branch, excluding the in-flight detector buffer, for both baseline and shared;
the optional `--analytics-queue-max-buffers 1` is only an equality assertion.
The selected value is a minimum positive pre-results backlog bound and cannot
be retuned post hoc for the primary cell. The shared graph resolves all values
per branch rather than reusing one digest label. The emitted detector identity
contains the verified full digest pair; a free-form detector label is not
sufficient provenance.

## Checkpoint runtime blueprint

`scripts/checkpoint_runtime_plan.py` validates the preregistered primary cell
and emits a non-measurement JSON blueprint. For every logical stream the
baseline has four OS-process workers, each reading the same source and running
its own branch-local decode, preprocess, and analytics stages. The shared plan
has one graph process with a single decode/preprocess prefix, a GStreamer `tee`,
one queue per required route, and a full branch join. Pairing uses dataset,
logical stream, source SHA-256, and native decoded-buffer PTS.

The join source is `direct_runtime_completion_events`: a coordinator must
observe branch completions during execution. Reconstructing a join later from
CSV fragments is expressly prohibited. The blueprint remains
`planning_only_not_measurement`, requires the scenario to stay
`blocked_topology`, and never emits scientific sidecars. Native worker,
coordinator, ingress-ledger, topology, and semantic-contract emission still
have to be implemented and accepted on the target runtime.

The direct runtime layer is implemented separately from benchmark acceptance.
`checkpoint_runtime.py` launches workers with one inherited pipe each and
derives execution domains from the observed PID rather than a worker-supplied
label. Messages use protocol version 1, a gap-free worker sequence, full frame
and input identity, execution/parent IDs, and event timestamp. Causal parents
must already have arrived on a direct pipe. Only the coordinator may create
`join_complete`, immediately after all required branch-completion messages;
an incomplete branch set remains unresolved.

The C++ probe source includes a header-only protocol emitter plus two new
roles. `checkpoint_branch` owns one source/decode/preprocess/analytics chain.
`checkpoint_shared` owns one source/decode/preprocess prefix followed by a
GStreamer `tee`, a queue per branch, analytics probes, and direct completion
messages. `checkpoint_gstreamer_runtime.py` expands the primary blueprint to 24
baseline or six shared workers plus one source process per logical stream.
Only the source receives an absolute MP4 path; dataset ID, logical stream,
manifest SHA-256, source cycle, native PTS, admission ID, and compressed-payload
SHA-256 form the input identity delivered to workers. Explicit execution
verifies the file hash before launch. Both source and worker targets compile
and link against GStreamer 1.28.5 in an out-of-tree local build. This remains
an engineering path because the KPP media files are absent locally and the
source/worker lifecycle has not been executed. The launcher emits only
`topology_events.runtime.csv`; accepted frame, ingress, semantic-contract, and
resource sidecars remain mandatory before integration with the strict shell
adapter.

## Sidecar provenance

After native frame and stage validation, the harness writes
`resource_events.csv`, `policy_decisions.csv`, and `drop_counters.csv`. Each
sidecar keeps `telemetry_source=native` to identify the source event and carries
separate provenance columns for the derived metrics:

- resource time may be `derived_from_native_stage_timestamps` or a native
  hardware counter;
- H2D/D2H, NVDEC, and VRAM fields distinguish native counters from frame-size
  estimates, stage-presence proxies, unavailable values, and unlabeled legacy
  data;
- policy rows distinguish a native full scheduler trace from a decision derived
  from a frame event and mark whether all alternatives and parameters exist;
- drop and late rates distinguish native events from frame-id-gap inference and
  latency-derived deadline checks.

New benchmark runs require all provenance columns. Archived schema-v2 sidecars
without them remain readable as `unlabeled_legacy` for diagnostics. Report
generation does not plot or aggregate transfer, NVDEC, VRAM, or drop metrics as
scientific measurements unless their provenance satisfies the corresponding
native-counter contract.

Checkpoint adapters must also copy the direct-admission coordinates into every
accepted `ingress_ledger.csv` row: gap-free per-stream `admission_seq`,
`source_sha256`, `source_cycle`, `access_unit_pts_ns`, `payload_sha256`,
`payload_size_bytes`, and `schedule_offset_ns`. The harness hashes this exact
schedule separately from the ordered `input_frame_key` sequence. It then
accepts `resource_attribution_complete` only when every closed-cohort ingress
key has attributable `decode` and `preprocess` resource rows, no resource row
falls outside the cohort or terminal interval, and all CPU/GPU times have
publishable provenance. The derived measurement signature deliberately lists
transfer duration, NVDEC busy time, and fanout time as absent until adapters
emit real time counters; estimates must not be inserted into those components.

An adapter-provided `policy_decisions.csv` is preserved rather than replaced by
the generic fallback. A `full` trace must provide `policy_version`, JSON-encoded
allowed resources, alternative scores, per-resource cost components and policy
parameters, `tie_break_rule`, `decision_mode`, gap-free `update_seq`, update
JSON when the sequence advances, and a reason. The validator replays the
admissibility and argmin checks using `parameters_json.score_epsilon`, verifies
the selected score and update snapshots, and links every applied row to a
native stage event with matching resource, queue depth, and selected cost. Rows derived from
`frame_events.csv` are marked `selected_action_only`; they remain useful for
stage linkage but are not eligible for scheduler-causality claims.

The diagnostic custom CUDA+Qt adapter writes an adapter-provided full trace for the
technical `ql_heft_frozen` and `ql_heft_online` policies. Its version is
explicitly `simplified-cpu-gpu-weighted-proxy-v4-*`: the trace is replayable for
the implemented CPU/GPU queue-weighted proxy, including serialized online
updates, but it is not evidence that the formal dissertation AW-HEFT contract
with NVDEC, transfer/deadline-risk terms, and the full stability rule has been
implemented or experimentally validated.

The separate formal reference accepts a version-1 replay packet only through
`formal_aw_heft_reference.py --trace`. That packet recomputes graph/profile
identity, rank, ready order, all resource alternatives and feedback state, but
is deliberately labeled `replay_input_only_not_accepted_telemetry`. It is not
derived from or merged into `policy_decisions.csv`/`policy_feedback.csv`, and a
successful replay has `evidence_accepted=false`. A future dataset-consuming
binding must version the mapping from native sidecars to this packet and expand
the publication evidence scope before any formal-policy result is observed.

This trace is not sufficient for publishable video results because the current
binary generates its input signal internally. Configuration marks the system
`diagnostic_only`, default benchmark selection omits it, and both explicit
adapter validation and the shell template reject benchmark execution. A strict
successor must consume the selected H.264/H.265 stream and retain dataset/frame
provenance through every stage.

## Distributed adapters

The SSH executor launches roles in this order:

1. `aggregator`
2. `gpu_worker`
3. `edge`

The built-in commands can exercise DeepStream, Savant, OpenVINO+GVA, and
GStreamer custom with native schema-v2 probes, but schema compliance does not
establish scenario topology. The current common probe serializes configured
stage operations in one pipeline, and the local Savant module serializes
telemetry hooks around one inference path. Consequently, both dissertation
checkpoint scenarios are `blocked_topology` and rejected in benchmark mode.
The validator still derives required native events from an eligible scenario
pipeline, including `track`, `classify`, and `record`; completed frames must
cover every listed stage. `--run-kind auto` dispatches local scenarios as heterogeneous and
distributed scenarios as single-server SSH role launches. Host inventories may
still override distributed commands with `DISTRIBUTED_NATIVE_CMD_<SYSTEM>_<ROLE>`
or the generic `DISTRIBUTED_NATIVE_CMD` fallback for custom deployments. The
command receives:

- `EXPERIMENT_HOST_ROLE`
- `EXPERIMENT_PIPELINE_STAGES`
- `EXPERIMENT_RTP_INPUT_PORT` when the role consumes RTP
- `EXPERIMENT_RTP_OUTPUT_HOST` and `EXPERIMENT_RTP_OUTPUT_PORT` when the role
  produces RTP
- `EXPERIMENT_TRACE_METADATA=rtp_header_extension`
- `EXPERIMENT_RTP_PORT_STRIDE`, default `1`

The role command must process only the assigned stages. It must propagate
`trace_id`, `stream_id`, `frame_id`, and the original edge ingress timestamp
through an RTP header extension. The aggregator writes E2E `frames.csv`; every
role writes `frame_events.csv` or mergeable `frame_events*.csv` fragments that
publish as the role benchmark `frame_events.csv`.

The canonical transport uses one UDP port per stream:

- edge to worker: `transport.role_ports.edge_to_gpu_worker + stream_id * stream_port_stride`
- worker to aggregator: `transport.role_ports.gpu_worker_to_aggregator + stream_id * stream_port_stride`

The native RTP trace header extension uses extension id `1` and URI
`urn:vast:rtp-trace:v1`. Its payload is 16 bytes:
`magic:u16`, `version:u8`, `stream_id:u8`, `frame_id:u32`,
`ingress_timestamp_ms:u64`, all encoded big-endian. The same serializer lives in
`scripts/rtp_trace.py` for tests and non-C++ tooling.

`vast_native_gst_probe` is the common runtime for edge/aggregator roles, host
OpenVINO/GStreamer custom worker roles, and DeepStream native probe containers.
The DeepStream local and worker paths use a DeepStream-specific
`uridecodebin`/`nvstreammux`/`nvinfer` graph instead of the generic detector
chain. Build it with:

```bash
cmake -S . -B build/cmake -DVAST_BUILD_NATIVE_GST_PROBE=ON -DVAST_BUILD_CUSTOM_CUDA_QT=OFF
cmake --build build/cmake --target vast_native_gst_probe
```

Containerized DeepStream and Savant roles use derived images:

```bash
scripts/build_native_probe_images.sh
```

Defaults:

- `vast/deepstream-native-probe:7.0`, based on `nvcr.io/nvidia/deepstream:7.0-triton-multiarch`
- `vast/savant-native-probe:0.5.17-7.0`, based on `ghcr.io/insight-platform/savant-deepstream:0.5.17-7.0`
- Savant distributed roles run the native RTP trace probe inside the Savant-derived image; local Savant still runs the Savant module.
- OpenVINO+GVA requires `gvadetect` or `object_detect`. When the host DL Streamer
  runtime is incomplete, strict local mode uses `intel/dlstreamer:latest` and
  isolates each stream in a short finite-input container chunk to avoid the
  DL Streamer `meta_aggregate` EOS path.
- GStreamer custom uses the bundled `adaptivescheduler` plugin by default.
  Build it with `cmake --build build/cmake --target gstadaptivescheduler`
  and expose it with `GST_PLUGIN_PATH=$PWD/build/lib`. Strict mode still
  fails fast if `gst-inspect-1.0 adaptivescheduler` cannot load it.

The common RTP bridge in `scripts/run_system_template.sh` is intentionally
restricted to `--mode smoke`. It verifies transport wiring but does not satisfy
the native inference or trace propagation contract.

## Resource interval extension

`scripts/resource_interval_contract.py` specifies a version-1, non-publication
extension for native transfer, NVDEC-busy, and fanout durations. An adapter
that eventually emits `resource_intervals.csv` must preserve the exact
run/trace/stream/frame/input key, stage, branch, and execution identity from
accepted ingress, topology, and frame-stage sidecars. Transfer rows use native
CUDA event elapsed time and a direction implied by a CPU/GPU topology edge;
NVDEC rows span a native decoder submit/complete interval for an NVDEC decode;
fanout rows use a native GStreamer pad-probe interval after the causal parent.
Every row has a unique SHA-256 native event identity, positive duration and
payload bytes, an explicit device, `counter_scope=per_trace_interval`, and
`telemetry_source=native`.

This is an emitter specification and fail-closed validator, not accepted
telemetry. No current adapter emits the sidecar. The contract is deliberately
outside measurement passport v4 and publication evidence bundle v1, and every
validator summary keeps `publication_bundle_bound=false` and
`evidence_accepted=false`. Full-resource publication would require native
emitters, accepted sidecars for both frozen arms, and a separately
preregistered `primary_architecture_full_resource_raw_evidence_v2` scope.

`--run-kind single-server-distributed` still uses SSH role launches, but all
roles target one server. The executor disables project sync and records
`same_host_loopback` network metrics instead of requiring chrony/ping/iperf
preflight between separate hosts.

## Acceptance

Before either dissertation checkpoint scenario can be marked `supported`, its
adapter must additionally prove the physical architecture:

- the baseline launches four independent analytics processes or equivalent
  isolation domains, each with its own source decode and preprocess execution;
- the shared variant executes one decode/preprocess prefix and fans the same
  frame identity out to four analytics branches;
- all branch events retain dataset, stream, frame, and branch provenance, and a
  completed shared frame is emitted only after the required branch join;
- the observed decode/preprocess event factor follows from those executions,
  not from repeated labels or timestamp splitting.

A distributed benchmark run is rejected when:

- `chronyc tracking` reports more than 5 ms offset on any role;
- required public dataset checksums are absent or invalid;
- the aggregator does not write E2E `frames.csv`;
- any role omits native event output (`frame_events.csv` or mergeable
  `frame_events*.csv`) or `system_metrics.csv`;
- a checkpoint topology produces no `topology_events.csv` or mergeable
  `topology_events*.csv` fragments;
- any frame row is synthetic, legacy, malformed, or has a duplicate trace ID;
- any completed frame lacks native events for a required pipeline stage.
