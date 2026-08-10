# VAST Video Analytics Benchmark

This project scaffolds the experimental study for task distribution in multi-stream KPP video analytics on the target platform:
- GPU: NVIDIA RTX 3060
- CPU: Intel Core i7-14700K
- RAM: 22 GB
- SLO deadlines: 16.7, 33.3, 50, 100, and 500 ms for publishable checkpoint scenarios

The default `benchmark` mode is strict: publishable runs require native
per-frame telemetry schema v2. Runtime-derived synthetic rows are available
only in explicit `smoke` mode and are excluded from scientific reports.

Current checkpoint status is `blocked_topology`. The generic native probe and
the local Savant module still do not implement the accepted comparison. A
separate common-source engineering path now launches four independent
process-per-detector workers per stream or one shared `decode -> preprocess ->
tee` graph, and it has completed short local synthetic H.264/H.265 runs. Those
runs write only runtime-suffixed diagnostics: they do not emit accepted
`frames.csv`, `topology_events.csv`, `ingress_ledger.csv`,
`branch_terminals.csv`, `stage_contracts.csv`, `reset_evidence.csv`, resource
attribution, or terminal cohort closure. Benchmark selection and the shell template
therefore continue to reject both checkpoint scenarios. Topology contract v1
and local engineering execution do not unblock either adapter.

`scripts/checkpoint_runtime_plan.py` now materializes a planning-only execution
blueprint for the preregistered pair. It requires four OS-process branch
workers per logical stream in the baseline and one `decode -> preprocess ->
tee` graph with four queued routes in the shared variant. Both plans require a
join driven by direct runtime completion events and explicitly prohibit a
post-hoc join reconstructed from CSV. The JSON has
`claim_status=planning_only_not_measurement`; it is not a telemetry sidecar and
does not change `blocked_topology`.

The next engineering layer is now present but not accepted as a benchmark
adapter. `scripts/checkpoint_runtime.py` launches every worker with a dedicated
inherited event pipe, binds events to the observed child PID, enforces gap-free
per-worker sequence and causal parents online, and emits join only while all
required branch processes are still part of the runtime. The native probe
source has `checkpoint_branch` and `checkpoint_shared` roles; the latter builds
an actual GStreamer `tee` with one queue per branch. The incomplete launcher
`scripts/checkpoint_gstreamer_runtime.py` writes only runtime-suffixed
engineering artifacts outside generated benchmark directories and reports
missing publication artifacts. Besides `topology_events.runtime.csv`, it
writes `cohort_audit.runtime.json`, `direct_admission_audit.runtime.json`,
`ingress_ledger.runtime.csv`, `terminal_admission_audit.runtime.json`, and
validated `stage_contracts.runtime.csv`. The cohort audit reports source
coverage, key-set equality, timestamp spread, and join closure without
constructing `ingress_ledger.csv`; `external_ingress_schedule_proven` remains
false. Exactly one `vast_checkpoint_source` process receives the absolute MP4
path for each logical stream. Workers receive only framed compressed access
units through inherited pipes. The runtime key includes dataset, logical
stream, manifest SHA-256, zero-based source cycle, and native compressed-AU PTS
before decoding. The source continuously replays a finite MP4 after drained
EOS; each replay increments `source_cycle`, so a PTS reset cannot duplicate the
key. Before execution the launcher recomputes source SHA-256 and rejects
provenance drift. Worker-local trace/frame ordinals are not compared across
processes: the coordinator matches `(logical_stream_id, input_frame_key)` and
assigns canonical run identities. The runtime ledger gives every direct
measurement admission exactly one terminal state: `completed` after a live
coordinator join, `drop` only after a protocol-v3 native `branch_drop` plus a
terminal outcome for every required branch, or `censored` at the drain
boundary. It never infers `drop` from a missing completion. The protocol-v3
parser and C++ emitter are contract-tested. The worker now has an explicit
`native_terminal_socket_v1` bridge for a real in-process analytics element:
the element sends the exact transport PTS, branch, completed/drop status,
object count, reason, and detector/backend identity through the borrowed
`VAST_CHECKPOINT_ANALYTICS_TERMINAL_FD`. The worker matches that live message
to direct admission before emitting protocol v3. The default `topology_only`
identity branch does not use the bridge and cannot provide a native analytics
terminal. When the bridge is selected, the launcher writes only
`branch_terminals.runtime.csv` plus an engineering audit; it still does not
write accepted `branch_terminals.csv`.
Its source is `engineering_runtime`, and the benchmark validator rejects it as
an accepted `ingress_ledger.csv`. None of these runtime files changes scenario
status or creates accepted telemetry.

The bundled `vastanalyticsterminal` element is the strict reference producer
for OpenVINO DL Streamer ROI metadata. It must be placed immediately after a
real `gvadetect` or `object_detect` element with a non-empty `model` property.
It verifies the actual upstream factory, preserves the detector output PTS,
recomputes SHA-256 of the exact configured model artifact and, for OpenVINO IR,
its sibling `.bin`, counts `GstVideoRegionOfInterestMeta`, and emits one native `completed`
datagram; zero ROI is a valid completed inference. It never infers `drop` from
zero ROI or from a missing buffer. Explicit overload drops are produced by the
bundled `vastanalyticsqueue`, placed directly before the same verified
detector. Primary contract version 1 fixes `max_buffers=1` for every branch in
both architectures and in the dependent policy ablation. The capacity counts
waiting buffers only; the buffer currently executing in the detector is
excluded. This is the minimum positive backlog bound selected before results,
not a performance-optimality claim, and post-hoc retuning is prohibited for
the primary cell. The queue uses `drop-newest`: only an incoming buffer
observed while its one waiting slot is full is discarded, and its exact PTS is emitted as
`native_pre_detector_queue_full_drop_newest`. Buffers lost elsewhere remain
censored. Build targets `gstvastanalyticsterminal` and
`gstvastanalyticsqueue`. A branch template has the following form. The launcher
loads `--analytics-model-manifest`, derives the capacity from the validated
primary blueprint, verifies exact branch coverage and file digests, and
supplies every placeholder separately to each branch. The optional
`--analytics-queue-max-buffers` argument is an assertion only and must equal
the preregistered value `1`:

```text
vastanalyticsqueue branch-id={branch} detector-id={detector_id} expected-downstream-factory={factory} expected-model-sha256="{model_sha256}" expected-weights-sha256="{weights_sha256}" max-buffers={max_buffers} ! {factory} model="{model_path}" device=GPU ! vastanalyticsterminal branch-id={branch} detector-id={detector_id} expected-upstream-factory={factory} expected-model-sha256="{model_sha256}" expected-weights-sha256="{weights_sha256}"
```

The manifest has `schema_version: 1`,
`artifact_kind: checkpoint_analytics_model_bindings`, and an exact `branches`
mapping. Each branch declares `factory`, `detector_id`, `model_path`, and
`model_sha256`. An OpenVINO `.xml` entry additionally declares the sibling
`weights_path` and `weights_sha256`; a non-IR model omits both weights fields.
The terminal records the verified digest pair in its detector identity, so a
user-provided label alone cannot establish model provenance.

The modules and their transport behavior are build/contract-tested with a
test-only detector factory. The queue test blocks the first detector call,
fills its single waiting slot, and verifies the exact PTS of the third,
drop-newest admission. No real DL Streamer model or KPP input has been run
through this path in the current workspace, so the test is not analytics or
benchmark evidence.

The finite H.264 sources last about 91.198333 s and 135.288333 s, while the
preregistered warmup plus measurement interval is 210 s. The blueprint now
therefore carries exact container, codec, duration, frame count, replay, and
cohort contracts instead of silently allowing early EOS. Continuous replay is
only an engineering prerequisite. The direct runtime now adds separate
control/status pipes: all workers must report `READY` before one common
monotonic `START`, receive the same `STOP` at the measurement boundary, and
finish with `DRAINED` or `CENSORED`. The launcher can select the exact 30+180 s
window explicitly; its default short window remains an engineering check.
Fixture processes and short local synthetic H.264/H.265 executions verify this
lifecycle. They do not verify the preregistered 210 s window, the target stand,
KPP media, overload behavior, accepted terminal ledger, or native analytics
completion/drop events.
Equal process boundaries and
an engineering fingerprint are necessary diagnostics, not an accepted ingress
cohort.

The planning blueprint now makes that missing boundary executable as a direct
protocol contract. Frame identity contract v3 requires one native source
coordinator per logical stream, a gap-free admission sequence, zero-based
source cycle plus native compressed-AU PTS, SHA-256 of the exact compressed
payload, and a deterministic decode-order schedule offset. Native PTS is an
identity coordinate and may reorder for B-frames; it is not an admission-order
counter. Worker
runtime protocol v2 must carry the source-assigned `admission_id` and payload
digest on every event; protocol v3 adds branch terminal reason, accepted object
count, and detector/backend identity only for `branch_complete` or
`branch_drop`. `checkpoint_admission.py` PID-binds each source pipe,
rejects admission after worker `source_read`, acknowledges an accepted source
event before the source may fan it out, verifies complete baseline/shared
consumer coverage, and computes a run-ID-independent schedule fingerprint for
the paired runs. A process fixture exercises the admission -> ACK -> four
consumer delivery -> join order. The C++17 admission transport now defines and
round-trip-tests a bounded binary frame carrying native/transport timestamps,
source cycle, identity, digest, and the exact byte payload; runtime protocol
v2/v3 emission is also parser-tested. The source/worker code path is now wired:
one `vast_checkpoint_source` per logical stream reads MP4 through `appsink`,
emits admission before delivery, and broadcasts the framed AU; workers receive
no file path, verify the exact payload digest, and push the AU through
`appsrc`. Both native targets compile and link against GStreamer 1.28.5 in an
out-of-tree local build. Short synthetic H.264 and H.265 pairs completed with
full consumer coverage and matching runtime schedule fingerprints, including
an H.265 stream with reordered B-frame PTS. This remains unaccepted engineering
evidence. Per-consumer bounded
sender queues isolate admission from a slow branch until capacity is reached
and fail the run explicitly on overflow, but this behavior is not target-run
evidence; the KPP media files are absent from this working copy. Target
execution, the preregistered window, overload rejection, accepted sidecars,
an analytics plugin that calls the terminal bridge, real branch models, and
accepted branch-terminal closure remain pending.
Therefore no accepted `ingress_ledger.csv` or scientific schedule claim is
produced.

Semantic equivalence of that topology is checked by a separate native
`stage_contracts.csv` sidecar. It covers every physical `decode` and
`preprocess` execution-domain/stage pair from the accepted topology trace and
records implementation identity/version, canonical configuration plus its
SHA-256 digest, a canonical manifest of stage-relevant loaded executables,
plugins, libraries, models or policies with their SHA-256 digests,
resize/normalization parameters, output media
type/format/dtype/shape, and frame-ordering contract. The validator requires
runtime-loaded artifact provenance, canonical manifest order, unique artifact
identities, a matching manifest digest, identical semantic payloads across baseline
branches, and the publication
report requires the resulting prefix hash to match the paired baseline/shared
run. The harness does not derive this file from stage labels or configuration
files. The source-level GStreamer checkpoint roles now write worker-local
`stage_contracts.runtime.csv` only after observing negotiated RGB caps and the
actually loaded video-decoder factory; each engineering row hashes the running
probe executable and the GStreamer plugin files used by that stage. The
engineering launcher PID-binds,
merges, and validates these fragments under the same runtime-only filename.
This path has been built and exercised locally only with synthetic media. It
has not run on the target GStreamer stand and does not create accepted
`stage_contracts.csv`, so engineering readiness does not unblock the benchmark
or establish reuse.

Stage semantic contract v2 proves consistency of the adapter-declared loaded
artifact set, not remote attestation or execution effect. It therefore remains
conjunctive with native topology/stage events, ingress/terminal/reset evidence,
and the paired benchmark rule. Version-1 sidecars are not upgraded post hoc.

The frozen H.264 primary cell additionally has decoder-placement contract v1.
The policy label `static_hybrid` and the `decodebin` autoplugger do not prove
NVDEC placement. The report reads the actual
`implementation_config_json.decoder_factory` from accepted decode-stage rows,
requires one factory per arm, accepts only `nvh264dec` or `nvv4l2decoder`, and
requires the exact same factory in the paired baseline/shared arms. Missing,
multiple, software, or mismatched factories fail `decoder_placement_verified`.
This factory identity establishes selected implementation only; it is not an
NVDEC busy-time counter and does not make partial `C_obs` complete.

The primary engineering launcher also binds the same frozen allowlist to every
checkpoint worker before process start. After `decodebin` has autoplugged and
the first negotiated decode buffer has exposed the loaded factory, the native
probe validates the factory, writes its runtime-only stage contract, and emits
`DECODER_PLACEMENT_VERIFIED`. The lifecycle coordinator requires that state
from every worker during the positive 30-second warmup and terminates the arm
if it is absent at measurement-window start. Source coordinators do not emit
this worker-only state. This fail-early barrier prevents a known software
fallback from entering the measurement window, but it is engineering control
evidence only: accepted `stage_contracts.csv`, exact baseline/shared factory
matching, and separate NVDEC activity telemetry remain mandatory.

Arm reset is accepted only from a separate native `reset_evidence.csv` sidecar.
It covers every source and worker process, a unique process-start token and
observed PID, the first direct admission at source cycle 0/sequence 1, a
zero-depth snapshot for every preregistered analytics queue, an initially empty
telemetry sink, warmup exclusion, stop-admission before drain, and terminal
`DRAINED` lifecycle. Paired arms must use disjoint process-start tokens and
different telemetry-sink IDs. The engineering launcher writes only
`reset_evidence.runtime.csv` with `telemetry_source=engineering_runtime`; the
accepted validator rejects it and does not infer reset from configuration or a
summary flag.
For distributed runs the executor combines role-local
`stage_contracts*.csv` and `ingress_ledger*.csv` fragments into the run-level
sidecars and fails a strict checkpoint run when either fragment set is absent.

The local KPP manifests contain six logical stream entries replicated from two
recorded sources, not six independent camera recordings. Five entries reuse
the same front-gate recording and one uses the underbody recording. Their
`camera_role` labels imply one route per replica, while the checkpoint pipeline
applies four analytics branches to every stream. The primary architecture
contrast now deliberately selects `all_branches_per_stream` as a non-production,
topology-only stress profile. Dataset-level `analytics_routing` remains
`unresolved`, so this does not reinterpret `camera_role`. Publication mode
remains blocked on physical topology and native trace acceptance. No accuracy
or six-camera diversity claim is supported by the current local dataset.

Inspect the frozen primary architecture order without starting a measurement:

```bash
python scripts/run_experiments.py --primary-architecture-plan
```

The command emits 20 ordered arms and a version-1
`primary_architecture_pair` metadata payload for each arm. The payload records
the pair repeat, strategy, first/second arm, and arm position. It currently
reports `blocked_primary_architecture_topology_implementation` and
`runtime_execution_allowed=false`, because both checkpoint scenarios remain
`blocked_topology`. The normal matrix loop runs scenarios in blocks and is not
silently labeled counterbalanced. Primary report pairing fails closed when
either arm lacks or drifts from this metadata contract. This plan is not a
benchmark run and does not establish chronology, topology, or an effect without
the corresponding controlled execution and accepted native evidence.

After both checkpoint scenarios have a supported physical implementation, run
the frozen target sequence only through:

```bash
python scripts/run_experiments.py --primary-architecture-run \
  --output-root /path/outside/the/repository
```

The dedicated executor rejects matrix selectors, timing/repeat overrides,
smoke/dry-run mode, and `--continue-on-error`. It resolves the single frozen
cell, checks topology readiness before media, hardware, or output-directory
access, and invokes the 20 arms sequentially with their exact pair metadata.
Resume uses the same command with `--resume-run-root` and accepts completed
arms only as a contiguous prefix of the frozen sequence; a completed arm after
a gap fails closed. The executor controls invocation order but remains local
harness evidence, not independent proof of process reset, wall-clock chronology,
native topology, sidecar provenance, or effect.

It includes:
- Scenario and protocol configuration
- Automated experiment runner
- CPU/GPU metric collection at 1-second frequency
- Repetition handling and structured outputs
- Summary analysis and comparison plots
- Target setup scripts for Linux and Windows/WSL2

## Project layout

- `configs/experiments.yaml`: Hardware target, protocol, structured scenarios, and system command templates
- `configs/datasets.yaml`: Public benchmark and synthetic smoke dataset manifests
- `configs/hosts.yaml`: SSH host inventory used by distributed scenarios
- `scripts/check_system.py`: Prints detected hardware
- `scripts/collect_metrics.py`: CPU/GPU sampler (CSV)
- `scripts/run_experiments.py`: Main matrix execution tool
- `scripts/distributed_executor.py`: SSH/rsync/scp executor for multi-host scenarios
- `scripts/benchmark_adapters.py`: Strict benchmark adapter support matrix and fail-fast contract checks
- `scripts/topology_contract.py`: Native per-frame process/fanout/join topology validator
- `scripts/checkpoint_runtime_plan.py`: Planning-only process/tee/join blueprint for the preregistered checkpoint pair
- `scripts/checkpoint_runtime.py`: Direct pipe protocol, PID-bound event validation, and live join coordinator
- `scripts/checkpoint_gstreamer_runtime.py`: Engineering-only launcher for the incomplete native checkpoint roles
- `scripts/check_dataset.py`: Dataset checksum validator
- `scripts/train_ql_heft.py`: Seeded offline adaptive-weight parameter generator for the technical `ql_heft_frozen` artifact
- `docs/NATIVE_ADAPTERS.md`: Required native probe and distributed RTP contract
- `scripts/analyze_results.py`: Aggregation and plotting
- `scripts/setup_target.sh`: Linux full-stack bootstrap script
- `scripts/setup_target_windows.ps1`: Windows bootstrap + WSL2 preparation
- `scripts/setup_target.py`: One-command OS auto-detect launcher for installers
- `scripts/run_system_template.sh`: Compatibility wrapper for strict adapters and smoke/demo command templates
- `deploy/gstreamer_adaptivescheduler/`: Bundled `adaptivescheduler` GStreamer plugin source
- `scripts/emit_runtime_frames_csv.py`: Smoke-only synthetic per-frame CSV exporter
- `scripts/prepare_assets.sh`: Builds 6-stream video layout and downloads OpenVINO model to fixed paths
- `INSTRUCTIONS.md`: Full setup and usage guide
- `runs/`: Raw run outputs (generated)
- `reports/`: Aggregated reports and figures (generated)

## 1) Setup

Preferred Linux setup:

```bash
chmod +x scripts/setup_target.sh
./scripts/setup_target.sh
```

One-command auto launcher (recommended):

```bash
python3 scripts/setup_target.py
```

Asset paths used by real templates:
- Videos: `data/videos/stream01.mp4` ... `data/videos/stream06.mp4`
- OpenVINO model: `models/openvino/public/intel/person-vehicle-bike-detection-crossroad-0078/FP16/person-vehicle-bike-detection-crossroad-0078.xml`
- Savant benchmark modules: `deploy/savant/canonical_heterogeneous_module.yml` and `deploy/savant/canonical_distributed_module.yml`

Pinned system defaults:
- DeepStream image: `nvcr.io/nvidia/deepstream:7.0-triton-multiarch`
- Savant image: `ghcr.io/insight-platform/savant-deepstream:0.5.17-7.0`
- OpenVINO Python: `2024.6.0`
- Custom CUDA + Qt reference app source: `deploy/custom_cpp_cuda_qt/adaptive_scheduler_app.cu`
- GStreamer custom plugin: `build/lib/libgstadaptivescheduler.so`, built from `deploy/gstreamer_adaptivescheduler`

Prepare assets manually (if needed):

```bash
bash scripts/prepare_assets.sh
```

Windows setup (run PowerShell as Administrator):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_target_windows.ps1
```

The Windows script prepares Git, Docker Desktop, NVIDIA driver, and WSL2
Ubuntu. Windows-native Python/OpenVINO/GStreamer are optional diagnostics; pass
`-InstallNativePython`, `-InstallNativeOpenVino`, or `-InstallNativeGStreamer`
only if you need them outside WSL.

Windows one-command launcher:

```powershell
py scripts\setup_target.py
```

Manual Python-only setup (minimal):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Build the bundled GStreamer custom plugin manually:

```bash
cmake -S . -B build/cmake -DVAST_BUILD_GSTREAMER_CUSTOM_PLUGIN=ON
cmake --build build/cmake --target gstadaptivescheduler
GST_PLUGIN_PATH="$PWD/build/lib" gst-inspect-1.0 adaptivescheduler
```

## 2) Validate hardware visibility

```bash
python scripts/check_system.py
```

Expected target:
- GPU string should include RTX 3060
- CPU string should include i7-14700K
- RAM should be close to 22 GB

The real `--mode benchmark` path fails closed when the detected CPU, GPU, or
RAM does not match this frozen target. Smoke and `--dry-run-plan` only print a
warning and remain non-measurement checks. Every completed proof run records
both `hardware_target` and `detected_hardware`; the publication report
recomputes the same gate from `run_metadata.json`, so a run copied from another
host cannot enter the primary report as target-stand evidence.

## 3) Scenario schema

Scenarios in `configs/experiments.yaml` use the structured schema:
- `workload`: `streams` or `stream_range`, object density, optional burst profile, optional variants
- `pipeline`: ordered stages such as `decode`, `detect`, `track`, `classify`, `record`, `aggregate`
- `placement`: stage-to-role mapping and a placement policy label
- `network`: latency, jitter, bandwidth, and packet-loss profile for distributed runs
- `distributed`: enables SSH-based role execution and artifact collection

Distributed scenarios use logical roles such as `edge`, `gpu_worker`, and `aggregator`. Use `--run-kind single-server-distributed` to launch those roles over SSH on one server, or map roles to real SSH hosts in `configs/hosts.yaml` for `--run-kind distributed`; keep SSH keys and credentials outside the repo.

## 4) Run experiments

Attempting the default benchmark currently fails fast because no checkpoint
scenario has passed the topology contract:

```bash
python scripts/run_experiments.py
```

Run a synthetic custom scheduler smoke test:

```bash
python scripts/run_experiments.py --mode smoke --run-kind heterogeneous \
  --systems custom_cpp_cuda_qt --scenarios checkpoint_video_dag_shared \
  --repeats 1 --warmup 0 --measurement 5
```

Preview the checkpoint baseline and shared Video-DAG commands without executing them:

```bash
python scripts/run_experiments.py --mode smoke --run-kind heterogeneous --dry-run-plan \
  --systems custom_cpp_cuda_qt --scenarios checkpoint_independent_processes_baseline \
  --repeats 1 --measurement 5
python scripts/run_experiments.py --mode smoke --run-kind heterogeneous --dry-run-plan \
  --systems custom_cpp_cuda_qt --scenarios checkpoint_video_dag_shared \
  --repeats 1 --measurement 5
```

Prepare and validate the frozen KPP H.264 dataset. Preparation requires the two
manifest-matching AVI sources, deduplicates six logical replicas into two
physical transcodes, and installs only outputs whose SHA-256 matches the
manifest. The target command remains unavailable until native topology is
validated and both scenario entries are changed to `benchmark_status:
supported`:

```bash
python scripts/prepare_benchmark_dataset.py --dataset kpp_real_h264
python scripts/check_dataset.py --dataset kpp_real_h264
python scripts/run_experiments.py --primary-architecture-run \
  --output-root /path/outside/the/repository
```

Use the same preparation tool with `--dataset kpp_real_h265` for the secondary
codec dataset. Preparation and checksum validation do not create measurements
or remove topology, hardware, native-sidecar, or claim-state gates.

## 5) Analyze

Analyze latest run:

```bash
python scripts/analyze_results.py
```

Analyze a specific run folder:

```bash
python scripts/analyze_results.py --run runs/20260323_120000
```

Generate only the preregistered primary architecture artifacts, without
requiring the secondary system/policy/deadline matrix:

```bash
python scripts/generate_vast_report_artifacts.py \
  --run-root runs/20260323_120000 \
  --output-dir reports/20260323_120000_primary \
  --primary-architecture-only
```

## Real system commands

In `configs/experiments.yaml`, each system points to `scripts/run_system_template.sh` for:
- NVIDIA DeepStream SDK
- Savant
- Intel OpenVINO + GVA
- GStreamer + custom plugin
- Custom C++ + CUDA + Qt implementation

Keep these placeholders in command strings:
- `{scenario}`
- `{duration_s}`
- `{streams}`
- `{min_objects}`
- `{max_objects}`
- `{output_dir}`

The runner also exports scenario context to templates:
- `EXPERIMENT_SCENARIO_JSON`
- `EXPERIMENT_DISTRIBUTED`
- `EXPERIMENT_HOST_ROLE`
- `EXPERIMENT_PIPELINE_STAGES`

## Notes

- The dissertation checkpoint program defines two currently blocked scenarios:
  `checkpoint_independent_processes_baseline` for process-per-detector
  repeated decode/preprocess, and `checkpoint_video_dag_shared` for the shared
  Video-DAG prefix. The local workload is six logical replicas of two recorded
  sources. Its preregistered `all_branches_per_stream` route is a topology-only
  stress profile and must not be described as production routing or six
  independent cameras.
- `stream_scaling` automatically expands stream count from 1 to 16 when enabled
  in experimental scenarios.
- Adapters intentionally use native detector models. Cross-system plots compare
  deployable stacks, not isolated scheduler overhead; reports retain detector
  and backend identity for every row.
- `benchmark` mode rejects missing, legacy, and synthetic per-frame telemetry.
- Benchmark sidecars label metric provenance separately from the native source
  event. Stage time derived from native timestamps remains usable; frame-size
  transfer estimates, stage-presence NVDEC proxies, inferred frame-id drops,
  and selected-action-only policy rows are excluded from scientific summaries
  that require native counters or a replayable scheduler trace.
- A replayable policy row stores JSON-encoded allowed resources, alternative
  scores, cost components, parameters, tie-break state, decision mode, and
  update data. Validation checks the selected-resource argmin invariant and a
  gap-free `update_seq` per run and policy. Each sequence increment must be
  exactly one and carry the update reason, feature snapshot, positive old/new
  weights, and a matching post-update parameter snapshot; frozen policies must
  keep sequence zero. `summary.csv` exposes `policy_trace_complete`.
- Causal policy acceptance is a separate, backward-compatible gate. A row with
  `causal_trace_completeness=full` must also provide a unique `decision_id`, a
  strictly increasing `decision_seq`, decision time, graph/profile versions,
  source/time/age/estimator provenance for every recorded feature, and a
  terminal status. Each applied update must reference the complete set of prior
  applied decisions for one terminal frame, exclude `censored` feedback, occur
  after those terminal events, and identify the first decision that consumes
  the new parameters. For the current weighted CPU/GPU proxy, the update's GPU
  queue feature must equal the maximum decision-time snapshot in that applied
  set, rather than a queue value sampled after completion. `summary.csv`
  exposes this stricter result as
  `policy_causal_trace_complete`; it does not change the meaning of
  `policy_trace_complete` for archived engineering traces.
- Bounded online feedback is accepted through a separate native
  `policy_feedback.csv` sidecar. It records every terminal outcome considered
  by the online policy, including no-ops, with gap-free `feedback_seq`, the
  oldest parameter version in the complete applied-source set, maximum
  staleness from that version, events since the last update, old/raw/projected
  weights, fixed box bounds and projection rule, variation accounting, action,
  reason, and optional first consumer. Validation requires mean-one bounded
  snapshots, deterministic `euclidean_box_mean_one_v1` projection, the frozen
  lag/cooldown/variation passport, exact full applied-source coverage, and a
  one-to-one match between state-changing feedback and the decision row that
  first consumes the new `update_seq`. `summary.csv` exposes the result as
  `policy_online_trace_complete`. Absence of the sidecar leaves this gate
  false; the harness never reconstructs no-op feedback from decision rows.
- The independent input cohort is carried by adapter-emitted
  `ingress_ledger.csv`; the harness never reconstructs it from completed
  `frames.csv` rows or aggregate drop counters. Every row records one native
  ingress event in a single `[window_start, window_end)` cohort, its stable
  `trace_id` and `input_frame_key`, plus the direct-admission coordinates
  `admission_seq`, source/payload SHA-256, source cycle, access-unit PTS,
  payload size, and schedule offset. It also records one terminal status
  (`completed`, `drop`, or `censored`), the drain boundary, and an explicit
  censoring rule.
  Validation requires unique input identities, timestamps inside the
  measurement/drain interval, exact completed-row linkage to `frames.csv`,
  native drop-count agreement when such counters are present, and matching
  `input_frame_key` values in a topology trace. `summary.csv` exposes
  `ingress_ledger_complete`, the four cohort counts, window/drain boundaries,
  and `ingress_cohort_closed`; absence of the file remains an explicit false
  gate rather than an inferred denominator.
- For an accepted closed cohort, the sidecar summary derives a measurement
  passport without reading scenario labels as evidence. It hashes the exact
  direct-admission schedule separately from the ordered `input_frame_key`
  sequence. Passport version 4 requires a one-to-one match between every
  accepted `resource_events.csv` row and every `frame_events.csv` stage
  interval in the closed cohort by run/trace/stream/frame/stage/resource.
  Duplicate or uncovered intervals, rows outside the cohort, and resource
  timestamps outside either the ingress-to-terminal window or the matched
  stage interval fail attribution. The whole interval must satisfy
  `ingress <= queue_enter <= stage_start <= stage_end <= terminal`; a resource
  timestamp in the overlap alone is insufficient. Every ingress key must cover both
  `decode` and `preprocess`. For
  `derived_from_native_stage_timestamps`, CPU/GPU time must equal
  `stage_end-stage_start`; queue wait before `stage_start` is excluded. The
  current `C_obs` passport therefore uses an unweighted sum of linked CPU/GPU
  device-milliseconds and exports the CPU and GPU totals plus their
  per-ingress normalizations. Publication validation requires both component
  sums to reproduce `C_obs` and `c_obs_in`. This scalar is not energy, FLOPs,
  monetary cost, or calibrated cross-device equivalent work. It remains a
  descriptive resource-time aggregate under one matched signature;
  the signature payload is validated as an exact fail-closed schema before
  its canonical SHA-256 is accepted. Missing or changed coverage fields,
  unsupported, duplicated, or unsorted provenance, and unknown fields are
  rejected even when the altered JSON has been rehashed correctly.
  The stored JSON text must also equal the canonical ASCII serialization
  byte-for-byte: reordered keys, extra whitespace, and duplicate JSON keys
  fail before the declared SHA-256 is accepted.
  transfer duration, NVDEC busy time, and fanout time remain explicitly
  absent, so `c_obs_is_partial=true`. `summary.csv` exposes the gates and
  normalized aggregate/component diagnostics and `c_obs_comp`; the report writes the same
  provenance-bearing rows to `measurement_passports.csv`.
  This derived passport version is independent of telemetry schema v2.
- Checkpoint runs also require adapter-emitted `branch_terminals.csv`. It has
  one native terminal row per required analytics branch and admitted frame,
  with branch-specific detector/backend identity, object count, terminal time,
  reason, and either `native_completion_event` or `native_drop_event`
  provenance. A completed or dropped ingress row must cover the entire
  preregistered branch set; an incomplete set is `censored`, never an inferred
  drop. The single checkpoint `frames.csv` row is an end-to-end aggregate with
  `detector=checkpoint_all_branches_per_stream_v1` and `objects` equal to the
  sum of the four accepted branch results. Dropped and censored admissions do
  not produce a completed frame row.
  Accepted detector identities must have the exact verified form
  `detector_id;model_sha256=<64 lowercase hex>[;weights_sha256=<64 lowercase hex>]`
  and a backend of `openvino-dlstreamer:gvadetect` or
  `openvino-dlstreamer:object_detect`. The identity may not drift within a
  branch. A canonical sorted branch/model/backend map is exported as
  `branch_analytics_contract_sha256`.
- Checkpoint benchmark scenarios require a complete topology trace, native
  stage semantic contract, complete native ingress ledger, complete native
  branch terminal trace, and accepted native reset evidence. The publication
  report independently checks
  `N_in = N_completed + N_drop + N_censored`, requires a non-empty censoring
  rule, rejects summaries that substitute `frames` for the input count, and
  requires one 64-character semantic-prefix SHA-256 value and one
  `branch_analytics_contract_sha256` within each exact
  baseline/shared pair. It also rejects an incomplete measurement passport
  or a pair with differing schedule/key digests, measurement-window duration,
  attribution rule, or measurement signature. `summary.csv` exposes
  `stage_semantic_contract_complete`, `semantic_contract_version`, and
  `semantic_prefix_contract_sha256`, and
  `branch_analytics_contract_sha256`. Contract tests demonstrate validator
  behavior only; no current checkpoint adapter has produced the four accepted
  native checkpoint sidecars on the target stand.
- Applied policy rows must link to exactly one native stage event with the same
  run/trace/frame/stage key, selected resource, decision-time queue depth, and
  selected score. This prevents an internally valid decision file from being
  treated as evidence when it is detached from actual execution.
- `benchmark.primary_architecture_contrast` preregistration version 4 freezes
  the paired inference rule and the `gstreamer_custom` implementation before
  accepted checkpoint results exist. Baseline
  and shared alternate as the first arm over ten pairs; every arm restarts the
  source/workers from cycle 0 and the first native admission sequence 1, uses empty analytics
  queues and a new telemetry directory, excludes warmup, stops admission
  before drain, and requires zero censored frames. Pairing requires the same
  `repeat`, base `seed`, derived `run_seed`, `input_schedule_sha256`,
  `input_frame_key_sequence_sha256`, `measurement_window_duration_ms`,
  `ingress_censoring_rule`, resource attribution, and measurement signature.
  The report also checks one semantic-prefix contract hash and one branch
  analytics contract hash. The former identifies the common prefix; the latter
  fixes every required branch's verified model/weights and backend. Neither is
  an effect measurement. The co-primary statistics are the median paired
  `Delta_reuse_obs`, `Delta F_decode`, and `Delta F_preprocess`; each lower
  bound of a 95% paired percentile-bootstrap interval with 10,000 resamples
  and seed 20260323 must exceed zero. Quality guardrails use
  `Vmax(shared)-Vmax(baseline)` and `drop_max(shared)-drop_max(baseline)`;
  both upper bounds must be at most zero. All conditions and native gates are
  conjunctive, so no favorable component compensates for another failed or
  inconclusive component. This contract does not create benchmark evidence;
  the cell remains `preregistered_blocked_execution`.
  `generate_vast_report_artifacts.py --primary-architecture-only` exports one row per expected pair to
  `primary_architecture_pairs.csv`, the frozen median/IQR/bootstrap results to
  `primary_architecture_inference.csv`, and the conservative state machine to
  `primary_architecture_claim_state.json`. Missing pairs or gates produce
  `blocked_missing_required_pairs_or_gates`; a complete series that fails an
  interval condition produces `not_confirmed_interval_conditions_failed`.
  After all ten pairs, all gates, and all five bounds pass, partial resource
  signatures produce
  `favorable_preregistered_rule_satisfied_partial_resource_coverage`; this
  state is limited to the measured CPU/GPU stage intervals. The unqualified
  `favorable_preregistered_rule_satisfied` state is reserved for a complete
  resource signature. Both states apply only to this cell and neither implies
  universal superiority or complete CPU/GPU/NVDEC/transfer/fanout savings
  under partial coverage.
- `benchmark.resource_interval_extension` defines a standalone version-2
  contract for a future `resource_intervals.csv` sidecar. The validator in
  `scripts/resource_interval_contract.py` requires exact native per-trace
  intervals linked to the accepted ingress, topology, and frame-stage rows.
  Transfer direction must follow a CPU-to-GPU or GPU-to-CPU topology edge;
  decoder submit-to-output intervals must belong to an NVDEC decode execution;
  fanout intervals must start after their parent and end at the native fanout
  event.
  The only accepted duration provenance values are
  `native_cuda_event_interval_v1`,
  `native_decoder_submit_complete_interval_v1`, and
  `native_gstreamer_pad_probe_interval_v1`. Duplicate event identities,
  duplicate physical intervals, and proxy provenance fail closed; incomplete
  expected transfer/decoder-submit-complete/fanout linkage is reported as
  incomplete and is never accepted. Version 2 declares only CUDA-event transfer
  duration as additive resource work. Decoder submit-to-output and queue
  sink-to-src spans are non-additive diagnostics: their sums are not NVDEC busy
  time or fanout resource work and must not be inserted into `C_obs`. The shared
  checkpoint source now contains a runtime-only
  fanout emitter: paired probes on the sink and source pads of each branch
  queue delimit the interval, bind it to the direct-admission trace and native
  fanout execution, and write `resource_intervals.runtime.csv`. The launcher
  merges this engineering fragment only after exact topology coverage and
  parent-time checks; the independent-process baseline must not emit it.
  This source-level path has not run on the target stand, does not emit CUDA
  transfer or decoder submit-to-output intervals, does not measure true NVDEC
  busy time or fanout resource work, and does not create the accepted
  `resource_intervals.csv`. No accepted interval packet exists, and the
  extension remains `publication_bundle_bound=false` and
  `evidence_accepted=false`. Measurement passport v4 and publication evidence
  bundle v1 remain unchanged. A publishable full-resource claim would require
  the separately preregistered future scope
  `primary_architecture_full_resource_raw_evidence_v2` before results.
  Pair rows also export baseline-minus-shared CPU/GPU component deltas, each
  arm's component shares, and shared-minus-baseline share shifts. The claim
  JSON summarizes their count, median, minimum, and maximum under
  `resource_mix_diagnostics`, explicitly marked
  `secondary_descriptive_not_claim_condition` with no preregistered threshold.
  These fields expose a changed resource mix but never calibrate CPU time
  against GPU time or alter the five frozen interval conditions. The
  `static_hybrid` string is a run coordinate, not proof of device placement;
  accepted stage/resource sidecars establish the executed placement. For the
  frozen H.264 primary cell, `decoder_placement_verified` specifically requires
  an accepted decode-stage factory of `nvh264dec` or `nvv4l2decoder` and exact
  pair identity; this gate does not measure NVDEC busy time.
  The primary report does not trust pair-critical values copied into
  `summary.csv`: it revalidates raw topology, ingress, branch-terminal,
  stage-contract, resource, policy-linkage, drop, and reset sidecars, then
  rederives the measurement passport and semantic/reset identities. Any
  disagreement with the summary adds a `summary_raw_mismatch:*` blocker; the
  raw-derived value is retained and the arm is excluded from inference.
  Before revalidating sidecars, the primary report also requires a schema-v2
  `run_metadata.json`. Its top-level `mode`, `result.run_mode`, and summary
  `run_mode` must all equal `benchmark`; the result identity and top-level
  run seed, policy, and dataset must agree with the summary copy. The report
  resolves the current scenario defaults and variant and recomputes a versioned
  identity over its ordered pipeline, topology/runtime blueprint, workload and
  routing fields, placement, network, and distributed contract. The stored
  `resolved_scenario` and its declared identity must both match. A matching
  dataset name is also insufficient: the report recomputes the versioned
  identity of the complete logical manifest, including ordered stream records,
  source and camera roles, codec metadata, expected file/annotation checksums,
  and routing metadata, and separately checks the ordered aggregate stream
  checksum. A separate versioned `publication_run_contract` binds the exact
  run coordinates, protocol, transport, telemetry contract, selected system
  configuration, hardware target, and the applicable primary architecture or
  policy preregistration record. Both its stored payload and declared identity
  must match the current configuration; production resume applies the same
  check and also verifies the requested base and derived run seeds. For an
  ordered architecture or policy arm, resume additionally requires the caller
  to supply the same exact pair contract and compares it with the stored copy.
  Missing expected metadata, an unexpected stored pair contract, coordinate or
  arm-position drift, mutually exclusive contracts, and pair metadata outside
  benchmark mode all fail closed. A generic matrix resume therefore cannot
  silently inherit ordered-arm status. After all
  accepted-sidecar validators pass, the runner also stores a version-1
  `publication_evidence_bundle`. Its scope is derived from the frozen config
  and run coordinates, not trusted from metadata. The architecture and frozen-
  policy scopes bind the relative path, byte size, and SHA-256 of exactly
  `frames.csv`, `frame_events.csv`, `resource_events.csv`,
  `policy_decisions.csv`, `drop_counters.csv`, `topology_events.csv`,
  `ingress_ledger.csv`, `branch_terminals.csv`, `stage_contracts.csv`, and
  `reset_evidence.csv`; the online-policy scope adds `policy_feedback.csv`.
  Report generation and production resume independently select the expected
  scope, recompute the complete set, and fail closed on a missing, replaced,
  symlinked, scope-drifting, or identity-drifting file. Every current scope
  intentionally excludes `system_metrics.csv`, because
  no coprimary architecture estimand is derived from it; any later claim that
  depends on another file or a new formal-policy artifact requires a new bundle
  scope/version before results.
  The bundle proves byte-set integrity relative to the recorded metadata, not
  native origin, adapter correctness, remote attestation, or scientific effect.
  No accepted bundle exists in the current workspace because the target KPP
  topology benchmark has not run.
  The frozen
  `hardware_target` must match the report configuration,
  and the recorded `detected_hardware` must pass the CPU/GPU/RAM target
  assessment. Missing, drifting, or target-incompatible metadata is a contract
  error. These identity checks establish configuration provenance only; raw
  topology/sidecar validation remains necessary to establish actual execution,
  and neither step is benchmark evidence by itself.
  The normal broad publication path applies the same metadata gate to every
  completed proof row before creating `summary_combined.csv` or any secondary
  report artifact; primary-only mode is not a bypass or the sole enforcement
  point. It also reopens every completed proof run and validates raw frames,
  stage/topology events, ingress, branch terminals, stage contracts,
  resource/policy/drop sidecars, and reset evidence. The measurement passport,
  semantic-prefix hash, reset identity, cohort counts, and partial `c_obs`
  values are rederived and compared with the summary copy. Any mismatch or
  invalid raw artifact stops the broad report before its output directory is
  created, so secondary tables cannot rely on summary-only gates.
  Before any per-run lookup, proof rows must also be unique by expected-matrix
  cell (`dataset`, scenario, deadline, deployment, system, policy, repeat).
  Duplicate rows, including copies found through different `summary_path`
  values, are contract errors rather than extra repetitions.
  Every proof row must also belong to the matrix frozen by the report config:
  an unknown scenario or an out-of-plan dataset, deadline, deployment, host
  topology, system, policy, or repeat is rejected before raw lookup. Missing
  expected cells remain allowed and are recorded as `missing` by the matrix
  audit; an observed row cannot silently extend the experiment design.
  `run_experiments.py` serializes the complete stable summary contract,
  including base/derived seeds, cohort/resource counters, the measurement
  passport, and reset identities; omitting any of these fields is a contract
  error rather than a silently truncated summary.
  Every row is validated before `summary.csv` is opened: all rows must carry
  the common identity/metric fields and an explicit `run_mode`; completed
  benchmark rows must carry every proof field and use
  `telemetry_source=native`, and unknown columns are rejected. A completed
  smoke row may itself contain native-origin frame rows but remains
  non-publishable because `run_mode=smoke`. Resume metadata with an older or
  partial benchmark completed-row schema is rejected instead of being copied
  into a new summary. Resume additionally requires the top-level metadata
  `mode` to agree with both the requested mode and `result.run_mode`.
- For `ql_heft_frozen` and `ql_heft_online`, the custom CUDA+Qt adapter now
  contains native-emitter instrumentation for a replayable and causal trace
  labeled
  `simplified-cpu-gpu-weighted-proxy-v4-*`. It records CPU/GPU alternatives,
  queue/profile components, parameter snapshots, tie-breaks, and serialized
  online updates together with decision identity/order/time, feature
  provenance, terminal status, complete source-decision sets, their oldest
  snapshot, and the first consumer of an update. The schema-v2 policy artifact
  fixes a bounded,
  mean-one initial weight vector and the projection, lag, cooldown, variation
  budget, and update-rule passport. For `ql_heft_online`, the source emits one
  native `policy_feedback.csv` row for every considered terminal outcome,
  including no-op, and links every state change to the first decision using
  the new snapshot. Helper and contract tests cover projection, gate order,
  artifact reproducibility, CSV-schema parity, and validator behavior. The
  `.cu` target still cannot be compiled in the current environment because
  `nvcc` is unavailable, so actual target-run emission and
  `policy_online_trace_complete=true` remain unverified. `full` describes the
  acceptance contract for this diagnostic source, not a locally observed
  native run. The proxy still lacks the formal AW-HEFT rank, NVDEC, transfer,
  deadline-risk, and stability-window model. Target execution cannot by itself
  convert this fixed proxy into full AW-HEFT.
- A separate `policies/aw_heft_reference_v1.json` and
  `scripts/formal_aw_heft_reference.py` now provide an executable formal
  reference for `rank_u`, ready ordering, CPU/GPU/NVDEC alternatives,
  transfer/memory/deadline-risk components, causal heavy-scene correction,
  deterministic tie-break, three-resource mean-one projection, and bounded
  terminal feedback. Configuration pins both files by SHA-256. Run
  `python scripts/formal_aw_heft_reference.py` to verify the static artifact.
  The expected result is `reference_only_not_runtime_bound` with
  `benchmark_eligible=false`; it is not a video adapter, does not emit an
  accepted trace, and has not replayed a target run.
- `benchmark.primary_policy_ablation` preregistration version 4 fixes the only primary
  frozen/online cell: `checkpoint_video_dag_shared` once that architecture is
  accepted, using the same `gstreamer_custom` implementation,
  `kpp_real_h264`/H.264, 100 ms, six logical streams,
  `all_branches_per_stream` with `topology_only_stress` scope, effective batch
  size 1, seed 20260323, 30 s warmup, 180 s measurement, and ten paired
  repeats. The arms use the same schema-v2 artifact and alternate the first
  arm by pair; the artifact and feedback state are reset before every
  measurement. The primary estimand is completed-frame `Vmax(online) -
  Vmax(frozen)`. A favorable claim requires the upper bound of the
  preregistered 95% paired percentile-bootstrap interval to be below zero,
  identical ingress key sequences and terminal status per key, zero censored,
  no increase in online drop rate, and positive completed counts per stream.
  The cell remains `preregistered_blocked_execution`; the two policy IDs stay
  outside the active benchmark matrix until architecture, dataset-consuming
  path, native policy gates, and pair/reset identity are accepted. Even after
  those gates pass, this cell estimates only the technical proxy update; it
  cannot be relabeled retrospectively as full AW-HEFT.
- The version-4 pair gate `policy_implementation_equivalence` is scoped to an
  executable replay against the frozen technical proxy passport. The replay
  implementation now independently recomputes every CPU/GPU score from the
  recorded profile, object, queue, active-task, weight, and heavy-scene
  components; reproduces all tie-break branches from the recorded stage
  preference; replays raw/projected online weights and update/no-op reasons;
  and binds both runs to the preregistered artifact SHA-256 from runtime
  metadata. It fails closed on incomplete native/causal traces or any passport
  mismatch. No accepted frozen/online pair exists, so report generation still
  reports `ready_runtime_reference_replay_not_executed` and
  `runtime_reference_replay_performed=false` in
  `primary_policy_equivalence_scope.json`. The paired policy state machine is
  now executable and fail-closed. It writes the ten expected rows to
  `primary_policy_pairs.csv`, preserves the complete replay assessment in each
  pair, and writes `primary_policy_inference.csv` plus
  `primary_policy_claim_state.json`. A pair is accepted only after exact
  counterbalanced arm order, pairing keys, ingress/terminal identity, an
  identical branch analytics contract hash,
  independent reset, zero censoring, the drop guardrail, and actual replay all
  pass. With the current zero accepted pairs, the claim state is
  `blocked_missing_required_pairs_or_gates`; no interval or policy effect is
  produced, and no summary flag is accepted. The static scope artifact records
  the separate formal-method gate as
  `blocked_reference_not_runtime_bound_or_preregistered`. The frozen proxy
  passport still lacks NVDEC, rank/ready-order, transfer/memory, deadline-risk,
  and stability-window semantics. The separate reference covers these
  equations in contract tests. Its version-1 input-only replay recomputes the
  canonical graph/profile hash, upward ranks and ready order, verifies the
  graph-compatible resource set and every recorded alternative, and then
  replays frozen/online feedback state, complete applied-source sets and the
  first consumer of each update. The replay result always carries
  `evidence_accepted=false` and `benchmark_eligible=false`. There is still no
  dataset-consuming binding, preregistered H2 cell, accepted trace, or replay
  of accepted evidence. This is executable contract readiness, not benchmark
  evidence.
- A source-level runtime audit adds a separate blocker:
  `blocked_runtime_policy_implementation_mismatch`. The frozen v4 cell names
  `gstreamer_custom`, but
  `deploy/gstreamer_adaptivescheduler/gstadaptivescheduler.c` does not emit
  the `ql_heft_frozen`/`ql_heft_online` v4 decision and feedback contract.
  The only local source containing that emitter is
  `deploy/custom_cpp_cuda_qt/adaptive_scheduler_app.cu`; it belongs to the
  diagnostic internal-signal runtime, is not dataset-consuming, and is not
  benchmark-eligible. Inspect the frozen 20-run order and metadata contract
  with:

  ```bash
  python scripts/run_experiments.py --primary-policy-plan
  ```

  The command is non-measurement planning only and currently returns
  `runtime_execution_allowed=false`. `run_one` rejects pair metadata while
  runtime compatibility is blocked. The report generator evaluates the same
  source-level status as a mandatory pair gate and records
  `runtime_policy_implementation_not_compatible` on every pair while it is
  blocked; accepted sidecars, a successful replay, or a favorable bootstrap
  cannot bypass it. Do not move the diagnostic emitter into the publication
  claim or modify the v4 cell retrospectively; implement and version a
  dataset-consuming runtime before results.
- The current custom CUDA+Qt binary generates an internal signal workload and
  does not consume `DATASET_STREAMS_JSON` or the selected H.264/H.265 source.
  It is therefore `diagnostic_only`: default benchmark matrices exclude it,
  explicit benchmark requests fail, and its trace may be used only to test
  scheduler mechanics. Smoke mode remains available. A future publishable
  adapter must decode the configured dataset and preserve frame provenance.
- Adapter-provided provenance-labeled sidecars are validated and preserved.
  The generic fallback is written only when an adapter did not provide one and
  is marked `selected_action_only`.
- Archived schema-v2 sidecars without provenance columns remain readable as
  `unlabeled_legacy`, but new benchmark runs reject them.
- Distributed roles start in the order `aggregator -> gpu_worker -> edge`.
- DeepStream, Savant, OpenVINO+GVA, and GStreamer custom must provide strict
  native adapters for the checkpoint scenarios before their rows are used in
  publishable analysis. The current custom C++ signal app and other
  experimental paths fail fast in benchmark mode until they consume the
  configured video data and provide native stage telemetry.
- `DISTRIBUTED_NATIVE_CMD_*` remains an override path for custom deployments.
  The common RTP bridge is smoke-only.
- Diagnostic custom CUDA + Qt smoke runs use `QT_QPA_PLATFORM=offscreen`;
  generate the frozen policy with `python scripts/train_ql_heft.py`.
- All run metadata, commands, dataset checksums, git state, and logs are stored per repetition.
- The legacy aggregate SLO field uses 3000 ms only for diagnostics. Publishable
  checkpoint reports recompute violations from raw frames at 16.7, 33.3, 50,
  100, and 500 ms.
- For complete installation and runbook details, see `INSTRUCTIONS.md`.
