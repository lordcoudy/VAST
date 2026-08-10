# Project Usage Instruction

This instruction explains how to install dependencies and run the experiment project on a target device.

## Target Platform

Primary target used by the experiment design:
- GPU: NVIDIA RTX 3060
- CPU: Intel Core i7-14700K
- RAM: 22 GB

## Supported OS Paths

1. Linux (recommended): Ubuntu 22.04/24.04 for complete stack support (DeepStream, Savant, OpenVINO, GStreamer).
2. Windows (partial native + full via WSL2):
   - Native Windows path can install Python/OpenVINO/GStreamer.
   - DeepStream and Savant should be run through WSL2 Ubuntu (or native Linux).

## One-Command Auto Launcher

Use the cross-platform launcher from project root:

```bash
python3 scripts/setup_target.py
```

On Windows:

```powershell
py scripts\setup_target.py
```

It auto-detects OS and calls:
- Linux: `scripts/setup_target.sh`
- Windows: `scripts/setup_target_windows.ps1`

## Fixed Input/Model Layout Used By Real Templates

After setup, these paths are expected and used automatically:
- Video streams:
  - `data/videos/stream01.mp4`
  - `data/videos/stream02.mp4`
  - `data/videos/stream03.mp4`
  - `data/videos/stream04.mp4`
  - `data/videos/stream05.mp4`
  - `data/videos/stream06.mp4`
- OpenVINO IR model:
  - `models/openvino/public/intel/person-vehicle-bike-detection-crossroad-0078/FP16/person-vehicle-bike-detection-crossroad-0078.xml`

These are created by:

```bash
bash scripts/prepare_assets.sh
```

`scripts/setup_target.sh` runs this automatically unless `PREPARE_ASSETS=0`.

## A) Linux Full Setup (Recommended)

From project root:

```bash
chmod +x scripts/setup_target.sh
./scripts/setup_target.sh
```

What this script installs:
- Base tools: Python, pip, venv, git, ffmpeg, build dependencies
- GStreamer runtime + dev packages
- Docker
- NVIDIA Container Toolkit for GPU containers
- Python venv dependencies from requirements.txt
- OpenVINO Python packages
- Pull attempt for:
   - DeepStream container image: nvcr.io/nvidia/deepstream:7.0-triton-multiarch
   - Savant container image: ghcr.io/insight-platform/savant-deepstream:0.5.17-7.0

Notes:
- DeepStream pull may require NGC login:
  - `docker login nvcr.io`
- If your user is newly added to the docker group, re-login is required.

Optional environment variables for setup script:
- `INSTALL_DOCKER=0` skip Docker install
- `INSTALL_GPU_STACK=0` skip NVIDIA Container Toolkit
- `INSTALL_OPENVINO=0` skip OpenVINO Python packages
- `INSTALL_DEEPSTREAM=0` skip DeepStream pull
- `INSTALL_SAVANT=0` skip Savant pull
- `DOCKER_PULL_TIMEOUT=1200` cap each image pull in seconds (0 disables the cap)
- `DEEPSTREAM_IMAGE=...` custom image
- `SAVANT_IMAGE=...` custom image

Example:

```bash
INSTALL_SAVANT=0 ./scripts/setup_target.sh
```

## B) Windows Setup

Run PowerShell as Administrator in project root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_target_windows.ps1
```

What this script does:
- Installs Chocolatey if missing
- Installs core tools (git, Docker Desktop, NVIDIA display driver)
- Installs WSL2 Ubuntu (recommended path for DeepStream + Savant)
- Optionally installs Windows-native Python 3.12, OpenVINO, and GStreamer when
  `-InstallNativePython`, `-InstallNativeOpenVino`, or
  `-InstallNativeGStreamer` are passed

Important:
- DeepStream is Linux-first; run full stack in WSL2 Ubuntu or native Linux.
- The full benchmark path does not need Windows-native OpenVINO/GStreamer; run
  those inside WSL instead.
- After WSL setup, open Ubuntu and run:

```bash
bash scripts/setup_target.sh
```

## Verify Installation

Activate venv:

```bash
source .venv/bin/activate
```

Check detected hardware:

```bash
python scripts/check_system.py
```

Expected on target device:
- GPU contains RTX 3060
- CPU contains i7-14700K
- RAM close to 22 GB

A real `--mode benchmark` run fails closed when any of these target fields does
not match. Smoke and `--dry-run-plan` only warn and remain non-measurement
checks. Completed proof metadata records the frozen target and detected host;
the publication report independently recomputes the same CPU/GPU/RAM gate.

## OpenVINO GVA Plugin Install (gvadetect)

If `openvino_gva` fails with `gvadetect element is unavailable`, install DL Streamer plugins in the same Linux/WSL environment where experiments run:

```bash
bash scripts/install_openvino_dlstreamer.sh
```

For a Windows host running commands through WSL, run:

```bash
wsl -e bash -lc "cd /mnt/e/STUDY/VAST; bash scripts/install_openvino_dlstreamer.sh"
```

The script performs a verification check and exits non-zero unless `gst-inspect-1.0 gvadetect` is visible.
If apt packages are unavailable for your Ubuntu release, the script automatically falls back to extracting DL Streamer runtime from `intel/dlstreamer:latest` and configures environment variables under `/etc/profile.d/vast_dlstreamer.sh`.

## Run Experiments

Synthetic scheduler smoke test:

```bash
python scripts/run_experiments.py --mode smoke --run-kind heterogeneous \
  --systems custom_cpp_cuda_qt --scenarios checkpoint_video_dag_shared \
  --repeats 1 --warmup 0 --measurement 5
```

Attempt the strict benchmark matrix from config. This currently fails fast
while the checkpoint scenarios retain `benchmark_status: blocked_topology`;
it must not be replaced by smoke output in scientific tables:

```bash
python scripts/run_experiments.py --mode benchmark
```

## Analyze Results

Analyze latest run:

```bash
python scripts/analyze_results.py
```

Analyze a specific run folder:

```bash
python scripts/analyze_results.py --run runs/<run_timestamp>
```

Reports are written to:
- `reports/<run_timestamp>/summary_aggregated.csv`
- `reports/<run_timestamp>/*.png`

## Run Real Pipelines

`configs/experiments.yaml` is already wired to `scripts/run_system_template.sh`, which contains real command templates for:
- DeepStream
- Savant
- OpenVINO + GVA
- GStreamer + custom plugin
- Custom C++ + CUDA + Qt

`benchmark` mode is the default behavior. It accepts only native schema-v2
`frames.csv` telemetry and fails when an adapter does not provide it.
Runtime-derived rows are synthetic and available only with `--mode smoke`.
Synthetic, skipped, and legacy rows are excluded from publishable analysis.

Both dissertation checkpoint scenarios are currently marked
`benchmark_status: blocked_topology`. Code audit showed that the shared native
probe executes configured stages serially in one pipeline, while the local
Savant module records configured pyfunc hooks in one pipeline. Repeated stage
labels and a four-to-one event-factor are therefore insufficient evidence of
independent process-per-detector execution or shared Video-DAG fanout. The
runner and `run_system_template.sh` reject these scenario names in benchmark
mode. Use smoke mode only for command, input, and telemetry-contract checks.

Topology contract v1 requires a native `topology_events.csv` row stream for
every completed frame. It records `input_frame_key`, topology/event kind,
branch and execution IDs, JSON parent execution IDs, execution domain,
timestamp, and provenance. The validator links every `stage_complete` row to
exactly one native `frame_events.csv` stage end. Baseline branches must use four
distinct execution domains and independent source/decode/preprocess chains.
The shared scenario must expose one source/decode/preprocess chain, one fanout
event per branch, and one join whose parents are all branch-completion events.
The report generator requires `topology_trace_complete=true`. Current adapters
do not emit this file and therefore remain blocked.

Topology acceptance is necessary but not sufficient for a reuse claim. Each
proof run must also provide native `stage_contracts.csv` metadata for every
physical `decode` and `preprocess` execution-domain/stage pair present in the
accepted topology trace. Each row records implementation name/version,
canonical runtime configuration and its lowercase SHA-256 digest,
an ordered non-empty manifest of stage-relevant runtime artifacts and their
lowercase SHA-256 digests, artifact-manifest SHA-256, and
`runtime_loaded_artifacts_v1` provenance,
resize/normalization parameters, output media type/format/dtype/shape, and the
ordering contract. Baseline branch rows for the same logical stage must be
semantically identical. `summary.csv` publishes
`stage_semantic_contract_complete`, `semantic_contract_version`, and a
`semantic_prefix_contract_sha256`; the report gate requires version 2 and the
same prefix hash in each exact baseline/shared pair. The harness has no
fallback writer for this file. The source-level GStreamer roles now contain a
runtime fragment emitter that hashes the loaded probe executable and
stage-relevant GStreamer plugin files; it has been built and exercised locally with short
synthetic H.264/H.265 inputs. No accepted sidecar exists and the target stand
has not been exercised; these runs therefore prove engineering-path behavior
only. The manifest is adapter evidence of byte identity, not remote
attestation, and it does not replace native execution events or effect
measurement. Version-1 sidecars must be re-emitted rather than upgraded.
For the frozen H.264 primary cell, accepted decode rows also feed decoder-
placement contract v1. `implementation_config_json.decoder_factory` must be a
single value, must be `nvh264dec` or `nvv4l2decoder`, and must match exactly
between baseline and shared. `avdec_h264`, a missing/multiple factory, or a
pair mismatch fails `decoder_placement_verified`. This check proves selected
decoder identity only; it must not be reported as NVDEC busy time or included
in `C_obs` as a duration.
For the primary runtime blueprint the launcher passes this exact allowlist to
every checkpoint worker. The native probe resolves the actual factory only
after `decodebin` autoplugging and negotiated output, then writes the
runtime-only decode contract and emits lifecycle state
`DECODER_PLACEMENT_VERIFIED`. The coordinator requires all worker states before
the positive warmup ends; missing verification or a disallowed factory aborts
the arm before the measurement window. Do not require the state from common
source coordinators. Do not treat the state or runtime fragment as accepted
evidence: publication still requires accepted `stage_contracts.csv`, exact
factory equality across the pair, and separate NVDEC activity counters.
The distributed executor combines role-local `stage_contracts*.csv` and
`ingress_ledger*.csv` fragments into the run-level sidecars and fails a strict
checkpoint run if either fragment set is absent.

The KPP H.264/H.265 manifests are load-replication datasets: six logical stream
entries reference only two unique recorded sources. Five entries reuse the
front-gate capture and one uses the underbody capture. The entries currently
carry one `camera_role` each, while the checkpoint scenario lists four branches
for every stream. The primary architecture contrast deliberately resolves the
scenario-level route as `all_branches_per_stream` with scope
`topology_only_stress`; the datasets retain `analytics_routing: unresolved` and
list this route only as an allowed non-production experimental profile. This
choice supports a controlled 4:1 topology test but does not reinterpret
`camera_role`. A production route-aware alternative must define the exact
branch set and expected multiplicity per source before implementation.

The machine-readable preregistration in `configs/experiments.yaml` fixes the
primary cell before results are inspected: `static_hybrid`, `kpp_real_h264`,
H.264, 100 ms, six logical streams, four branches per stream, effective batch
size 1, seed 20260323, 30 s warmup, 180 s measurement, and 10 repeats. H.265,
other deadlines, policies, and stream counts are secondary analyses. The
preregistration status is `preregistered_blocked_execution`; it does not remove
the `blocked_topology` gate or create a scientific measurement.

Audit the exact architecture-pair order before any target execution:

```bash
python scripts/run_experiments.py --primary-architecture-plan
```

This non-measurement command emits ten alternating baseline/shared blocks and
the version-1 `primary_architecture_pair` payload expected in each arm's
`run_metadata.json`. The report requires the frozen strategy, repeat,
first/second arm, and arm position for both arms. The current status is
`blocked_primary_architecture_topology_implementation` with
`runtime_execution_allowed=false`; do not bypass it with the ordinary matrix
loop, whose scenario-block ordering is not counterbalanced. Metadata records
the execution contract but is not independent proof of wall-clock chronology,
physical topology, native provenance, or effect.

Once and only once both checkpoint scenarios are physically implemented and
their `benchmark_status` is `supported`, execute the frozen sequence with:

```bash
python scripts/run_experiments.py --primary-architecture-run \
  --output-root /path/outside/the/repository
```

This mode accepts no matrix selectors, timing/repeat overrides, smoke/dry-run,
or `--continue-on-error`. Before creating the output root it re-resolves all 20
cells and checks topology readiness, the exact dataset, target hardware, and
frozen seed. Each arm must finish before the next starts. To resume an
interrupted sequence, use the same mode with `--resume-run-root`; all reusable
completed arms must form a contiguous prefix and must pass the exact pair,
scenario, dataset, seed, evidence-bundle, and native-sidecar gates. A later
completed arm after a missing or failed step is rejected rather than reordered.
Controlled invocation order is still not an independent attestation of reset,
chronology, physical topology, native provenance, or effect.

Generate and validate the current execution blueprint outside `runs/` and
`reports/` with:

```bash
python scripts/checkpoint_runtime_plan.py \
  --config configs/experiments.yaml \
  --datasets configs/datasets.yaml \
  --system gstreamer_custom \
  --output /tmp/vast-checkpoint-runtime-plan.json
```

The blueprint fixes four branch worker processes per stream for the baseline,
one shared GStreamer `tee` graph with a queue per route for the shared variant,
the pre-decode access-unit PTS/source-cycle/source-hash frame identity, exact
MP4/codec/duration metadata, the 30 s + 180 s cohort protocol, and a direct
runtime completion protocol for join. It intentionally writes no accepted
`frames.csv`, `topology_events.csv`, `ingress_ledger.csv`,
`branch_terminals.csv`, `stage_contracts.csv`, or `reset_evidence.csv`. A
post-hoc CSV join is prohibited. The file is an implementation input with
`claim_status=planning_only_not_measurement`, not a benchmark result.

Inspect the concrete native command expansion without executing it:

```bash
python scripts/checkpoint_gstreamer_runtime.py \
  --scenario checkpoint_independent_processes_baseline
python scripts/checkpoint_gstreamer_runtime.py \
  --scenario checkpoint_video_dag_shared
python scripts/checkpoint_gstreamer_runtime.py \
  --scenario checkpoint_video_dag_shared \
  --use-preregistered-window
```

The first command expands to 24 C++ workers, four per logical stream; the
second expands to six shared graph workers. `checkpoint_runtime.py` gives each
worker an inherited event pipe and binds accepted events to the observed PID.
It validates sequence, parent visibility, frame identity, branch ownership,
and execution-domain isolation before producing a live coordinator join.
Separate control/status pipes implement a barrier: every worker reports
`READY`, all receive one future monotonic `START`, the coordinator sends one
`STOP` at the common window end, and every worker must close with `DRAINED` or
`CENSORED`. `--use-preregistered-window` selects the exact 30 s warmup and
180 s measurement; without it `--warmup`/`--duration` define only a short
engineering window.
After an explicit run, `cohort_audit.runtime.json` reports direct source-event
coverage, baseline branch key-set equality, timestamp spread, post-window
events, and join closure. Its claim status is
`engineering_diagnostic_not_native_ingress_ledger`; it always records
`external_ingress_schedule_proven=false` and never creates accepted frame or
ledger rows. `direct_admission_audit.runtime.json` separately records the
run-ID-independent engineering schedule fingerprint and consumer coverage; it
has claim status `runtime_protocol_evidence_not_terminal_ingress_ledger`.
`ingress_ledger.runtime.csv` then closes each direct measurement admission as
`completed` after the coordinator observes a live join, as `drop` only after
an explicit protocol-v3 native `branch_drop` and a terminal outcome for every
required branch, or as `censored` at the drain boundary. It does not infer a
`drop` from a missing completion. The companion
`terminal_admission_audit.runtime.json` reports frame linkage, consumer
coverage, post-window admission, lifecycle closure, and censoring with claim
status `runtime_terminal_closure_not_accepted_ingress_ledger`. The runtime
ledger uses `telemetry_source=engineering_runtime`; the publishable
`validate_ingress_ledger` contract rejects it and the launcher still does not
write accepted `frames.csv`, `topology_events.csv`, `ingress_ledger.csv`,
`branch_terminals.csv`, `stage_contracts.csv`, or `reset_evidence.csv`.
Worker runtime protocol v3 adds branch terminal reason, accepted object count,
and detector/backend identity only for `branch_complete` or `branch_drop`.
The default `--checkpoint-analytics-mode topology_only` keeps the identity
pipeline restricted to engineering topology completion. To exercise a real
adapter, select `native_terminal_socket_v1` and provide a non-identity
`--detect-bin` containing `{branch}`. Each branch-aware analytics element must
use `checkpoint_analytics_terminal_transport.hpp` and the borrowed
`VAST_CHECKPOINT_ANALYTICS_TERMINAL_FD` to send its live outcome for the exact
GStreamer transport PTS. The worker, rather than the element, binds that
outcome to admission identity and emits protocol v3. Such a run writes
`branch_terminals.runtime.csv` and `branch_terminal_audit.runtime.json` with an
engineering-only claim status; it still does not write accepted
`branch_terminals.csv`.

The repository includes `vastanalyticsterminal` as a strict reference element
for DL Streamer ROI-producing detectors and `vastanalyticsqueue` as its native
pre-detector overload source. Build both outside generated run/report
directories with the CMake targets `gstvastanalyticsterminal` and
`gstvastanalyticsqueue`, expose the resulting libraries through
`GST_PLUGIN_PATH`, and bracket the detector with them:

```text
vastanalyticsqueue branch-id={branch} detector-id={detector_id} expected-downstream-factory={factory} expected-model-sha256="{model_sha256}" expected-weights-sha256="{weights_sha256}" max-buffers={max_buffers} ! {factory} model="{model_path}" device=GPU ! vastanalyticsterminal branch-id={branch} detector-id={detector_id} expected-upstream-factory={factory} expected-model-sha256="{model_sha256}" expected-weights-sha256="{weights_sha256}"
```

Pass the binding file with `--analytics-model-manifest`. Its strict shape is:

```yaml
schema_version: 1
artifact_kind: checkpoint_analytics_model_bindings
branches:
  damage:
    factory: gvadetect
    detector_id: kpp-damage-v1
    model_path: /abs/models/damage.xml
    model_sha256: <lowercase SHA-256 of damage.xml>
    weights_path: /abs/models/damage.bin
    weights_sha256: <lowercase SHA-256 of damage.bin>
  # The other required branches must be declared with the same fields.
```

The loader requires exact coverage of the scenario branch set, resolves
relative paths against the manifest directory, streams every file through
SHA-256, and rejects drift before worker startup. For an `.xml` model the
weights path must be the sibling `.bin`; non-IR models must omit weights
fields. Shared workers receive all branch bindings, while each baseline worker
receives only its branch. The native probe performs branch-specific
substitution and both queue and terminal recompute the same digests before
accepting an input or output buffer. The queue capacity is not taken from the
model manifest. The validated primary blueprint fixes `max_buffers=1` per
branch, with waiting buffers counted separately from the in-flight detector
buffer, and supplies `{max_buffers}` to baseline and shared workers. The value
is the minimum positive pre-results backlog bound, not an optimized capacity;
post-hoc retuning of the primary cell is prohibited. The optional
`--analytics-queue-max-buffers 1` argument only asserts equality with that
contract and any other value is rejected.

`object_detect` may be used only when both the actual element factory and
`expected-upstream-factory` are `object_detect`. Startup fails for identity,
an intervening queue/element, a factory mismatch, an empty upstream `model`, a
missing artifact, or digest drift. Each output buffer must have a valid transport PTS. The element
counts `GstVideoRegionOfInterestMeta` and emits `completed`, including a valid
zero-object completion. It does not infer or emit drop. The adjacent
`vastanalyticsqueue` emits a drop only when its bounded waiting queue is full;
the policy rejects the newest incoming buffer and sends its exact transport
PTS with reason `native_pre_detector_queue_full_drop_newest`. Teardown,
downstream failure, and missing detector output are not reclassified as drop
and remain censored by the drain rule. The local contract tests use a test-only
detector factory; the queue test blocks one detector call, fills one waiting
slot, and checks the dropped third PTS. They do not establish real model
execution, detection quality, KPP coverage, or publishable telemetry.
Independent worker-local frame ordinals are not compared across processes;
pairing uses `(logical_stream_id, input_frame_key)`, after which the coordinator
assigns canonical trace/frame IDs. A worker cannot emit `join_complete` itself.
One source coordinator per logical stream receives the absolute MP4 path;
workers receive no path and consume only framed compressed access units. The
frame key contains dataset, logical stream, manifest SHA-256, zero-based
`source_cycle`, and native compressed-AU PTS captured before decode. Explicit
engineering execution recomputes file SHA-256 before startup and verifies the
manifest container, codec, and duration arguments.

`vast_checkpoint_source` is the only MP4 demux/parser per logical stream;
`vast_native_gst_probe` contains `checkpoint_branch` and `checkpoint_shared`
worker roles. The shared graph uses one decoded/preprocessed prefix, a
GStreamer `tee`, and one queue per branch. On EOS the source waits for AU
delivery, increments `source_cycle`, and seeks to zero. Gap-free admission
sequence defines decode order. Native PTS remains part of frame identity and
may reorder for B-frames; the deterministic schedule offset accumulates AU
durations instead of treating PTS as an ordinal. Execution is deliberately
available only through `--execute-engineering-runtime`; output is constrained
outside `runs/`, `reports/`, `build/`, `.venv/`, and `.pytest_cache`, and the
live trace is named `topology_events.runtime.csv` so the publication gate
cannot consume it accidentally. Local synthetic H.264/H.265 runs have completed
for both topologies, but the target stand and preregistered KPP window have not
run. Current blockers remain: the coordinator does not emit accepted
`frames.csv`, `topology_events.csv`, `ingress_ledger.csv`,
`branch_terminals.csv`, `stage_contracts.csv`, or `reset_evidence.csv`;
resource attribution and branch-specific analytics acceptance are also absent.
The latest two-second H.264 pair closed 126 direct admissions per topology and
the H.265 pair closed 150 per topology as `completed`, with no runtime
censoring and matching schedule fingerprints inside each pair. This closes the
engineering accounting contract only. The scientific ingress cohort still
requires target-run common-source admission, accepted native frame linkage,
native completion/drop provenance, and terminal completion/drop/censoring for
every key.

The execution blueprint now requires one source coordinator process per
logical stream. Its direct admission protocol records a gap-free sequence,
`source_cycle`, native compressed access-unit PTS, exact payload SHA-256/size,
decode-order duration offset, and source-assigned `admission_id`. The coordinator
PID-binds this event and sends `ACK` before the source may deliver the token to
workers. Admission-enforced workers use runtime protocol v2 and repeat the
same `admission_id` and payload digest; baseline coverage is complete only
after all four branch processes consume that direct admission. The resulting
schedule fingerprint excludes run ID and absolute wall-clock time, so a pair
can be rejected when content, order, source position, payload, size, or
relative schedule differs. Current process fixtures test this IPC ordering. A
bounded C++17 binary frame for compressed AU bytes and a protocol-v2 worker
emitter are independently round-trip/parser tested, including embedded NUL
bytes and truncated-frame rejection. The source/worker implementation now
wires a singleton GStreamer `appsink` to admission -> ACK -> framed broadcast
and worker `appsrc`; worker commands receive no MP4 path and verify payload
SHA-256 before decode. Both native targets compile and link against GStreamer
1.28.5 in an out-of-tree local build. Short local synthetic H.264/H.265 pairs
completed with full consumer coverage, join closure, and matching persisted
schedule fingerprints. The path remains unexecuted on real KPP inputs and
unaccepted. A bounded
sender queue per consumer isolates admission from slow-branch backpressure
until capacity and fails the run on overflow; target execution, overload
exercise, and accepted terminal traces remain pending. The former worker-local MP4 path cannot satisfy the paired ingress
gate or create `ingress_ledger.csv`.
At source level each checkpoint worker writes `stage_contracts.runtime.csv`
only after checking negotiated RGB caps, identifying the loaded video
decoder, and hashing the running executable plus stage-relevant loaded plugin
files. The launcher binds those fragments to observed worker PIDs, merges
them under the same engineering-only name, and runs the semantic validator.
This engineering-only path is not accepted telemetry and does not remove
`blocked_topology`.

The runner also writes provenance-labeled sidecars. `telemetry_source=native`
means the source frame/stage event is native; it does not by itself make every
derived field a hardware counter. The current generic derivation labels
frame-size H2D/D2H estimates, stage-presence NVDEC proxies, inferred frame-id
drops, and selected-action-only policy records explicitly. Those values remain
diagnostic and are omitted from scientific summaries that require native
transfer/NVDEC/drop counters or a replayable full policy trace. Archived
sidecars without provenance labels can be inspected, but new benchmark runs
require the labels.

For scheduler-specific claims, an adapter may provide a full
`policy_decisions.csv` before harness post-processing. The harness preserves
that file after validation. Full rows include JSON objects for allowed
resources, all alternative scores, cost components, policy parameters and
updates, plus policy version, tie-break rule, decision mode, and monotonic
`update_seq`. The validator checks that the selected resource is allowed and
minimizes the recorded scores within `score_epsilon`. Update sequences are
validated independently per run and policy: every increment is exactly one and
must include a reason, a non-empty feature snapshot, positive old/new weights,
and post-update parameters matching the new values. Weighted `ql_heft_*`
traces must include weights for every allowed resource, while frozen traces
must keep `update_seq=0` and an empty update. If no native policy file exists,
the fallback contains only the selected action, and
`policy_trace_complete` remains false; this does not invalidate architecture
event-factor analysis but prevents causal AW-HEFT conclusions.

Causal acceptance uses a separate column group and summary flag. Rows marked
`causal_trace_completeness=full` must include a unique decision ID, strictly
increasing decision sequence, decision time, graph/profile versions, and
source/time/age/estimator provenance for every feature. An online update must
reference the complete prior applied-decision set of one terminal frame, must
not use `censored` feedback, and must identify the first decision that consumes
the new parameter snapshot. For the weighted CPU/GPU proxy, its GPU queue
feature must match the maximum decision-time snapshot in that source set, not
a post-completion queue sample. The validator reports
`policy_causal_trace_complete` independently of the backward-compatible
`policy_trace_complete` engineering gate.

The bounded online contract uses a separate adapter-emitted
`policy_feedback.csv`. One row is required for every terminal applied trace,
including feedback that leaves parameters unchanged. The file carries
gap-free `feedback_seq`, the complete source-decision set, its oldest source
snapshot and maximum staleness lag, cooldown position, old/raw/projected weight maps, the frozen box bounds
and projection rule, variation before/after/budget, feedback features,
`update` or `no_op`, reason, resulting `update_seq`, and the first consumer for
an update. The validator reproduces Euclidean projection onto the box with
arithmetic mean one, checks lag/cooldown and total-variation limits, and
requires state-changing rows to match the legacy update payload on exactly one
first-consumer decision. It reports `policy_online_trace_complete`; missing
native feedback remains false and is not derived from `policy_decisions.csv`.

The proof scenarios additionally require adapter-emitted
`ingress_ledger.csv`. The harness deliberately does not derive this file from
`frames.csv`, frame-id gaps, or `drop_counters.csv`: such a derivation would
define the input count from known outcomes and hide missing in-flight frames.
The ledger has one row per frame admitted during a single native ingress
window and records:

- `cohort_id`, stable `trace_id`, `input_frame_key`, stream and frame IDs;
- gap-free per-stream `admission_seq`, source/payload SHA-256, source cycle,
  access-unit PTS, payload size, and direct schedule offset;
- ingress, window start/end, terminal, and drain-end timestamps;
- exactly one terminal status: `completed`, `drop`, or `censored`;
- terminal reason, one explicit censoring rule, and native provenance.

Validation requires all ingress timestamps to fall in `[t0, t1)`, all terminal
events to occur no later than the drain boundary, and censored timestamps to
equal that boundary. Completed rows must match `frames.csv` exactly by
run/trace/stream/frame and by ingress/egress time. Native drop counters, when
present, must match per-stream ledger drop rows. For checkpoint scenarios the
completed ledger identities must also match `topology_events.csv`, including
`input_frame_key`. `summary.csv` publishes `ingress_ledger_complete`,
`ingress_cohort_closed`, `ingress_frame_count`, completed/drop/censored counts,
the censoring rule, and window/drain times. The report generator rejects a
proof summary without this gate or without the arithmetic balance
`N_in = N_completed + N_drop + N_censored`.

For a closed accepted cohort, `summarize_measurement_passport` derives two
independent SHA-256 values: one over the exact direct-admission schedule and
one over the ordered input-key sequence. Passport version 4 accepts resource
attribution only when `resource_events.csv` and the closed cohort's
`frame_events.csv` have the same unique stage-interval keys by
run/trace/stream/frame/stage/resource. Duplicate or uncovered intervals and
rows outside the cohort fail closed. The whole matched interval must satisfy
`ingress <= queue_enter <= stage_start <= stage_end <= terminal`; a resource
timestamp inside the overlap does not compensate for an out-of-cohort
interval. Each resource timestamp must also lie inside its matched stage interval, and every
ingress key must cover `decode` and `preprocess`. For
`derived_from_native_stage_timestamps`, CPU/GPU time must equal
`stage_end-stage_start`, excluding queue wait before stage execution. CPU/GPU
time must be finite and non-negative, and no frame may be censored. The
resulting canonical measurement signature lists CPU/GPU stage time as covered
and transfer duration, NVDEC busy time, and fanout time as absent. It also
defines `C_obs` as an unweighted sum of attributed CPU/GPU
device-milliseconds, exports both component totals and per-ingress values, and
requires their sums to reproduce the aggregate. Do not interpret this scalar
as energy, FLOPs, monetary cost, or calibrated cross-device equivalent work.
The report accepts the canonical SHA-256 only after validating the complete
payload against the exact v4 schema. Missing or altered coverage semantics,
unsupported, duplicated, or unsorted provenance, and unknown fields fail
closed even if the modified JSON was rehashed consistently.
The stored payload string must be the exact canonical ASCII serialization;
reordered keys, extra whitespace, and duplicate JSON keys are rejected before
the declared digest is accepted.
Thus current `c_obs_in` and `c_obs_comp` are explicitly partial; they are not a
proxy for missing components. The publication report exports `measurement_passports.csv`
and rejects baseline/shared rows with differing schedule/key digests, window
duration, drain rule, attribution, or signature.
The derived passport version does not change telemetry schema v2.

This is currently validator readiness, not native measurement readiness. None
of the blocked checkpoint adapters has yet emitted an accepted ledger on the
target stand, so the dissertation's primary `c_obs_in` and `Delta_reuse_obs`
remain unavailable.

The exact architectural inference rule is frozen as
`benchmark.primary_architecture_contrast` preregistration version 4, including
the `gstreamer_custom` implementation. The ten
baseline/shared pairs counterbalance which architecture runs first. Before
each arm, restart all source and worker processes from source cycle 0 and
the first native admission sequence 1, require empty analytics queues and a new telemetry
directory, exclude warmup from measurement, stop admission before drain, and
drain to zero censored frames. A pair requires identical `repeat`, base
`seed`, derived `run_seed`, `input_schedule_sha256`,
`input_frame_key_sequence_sha256`, `measurement_window_duration_ms`,
`ingress_censoring_rule`, resource attribution, measurement signature,
semantic-prefix contract hash, and `branch_analytics_contract_sha256`. The
last value is the canonical sorted identity of every required branch's
verified detector/model/weights digest and backend; a mismatch closes the
pair and is not an effect estimate. Report
the median, IQR, and 95% paired percentile-bootstrap interval with 10,000
resamples and seed 20260323 for `Delta_reuse_obs`,
`F_decode(baseline)-F_decode(shared)`, and
`F_preprocess(baseline)-F_preprocess(shared)`. Every co-primary lower bound
must exceed zero. The upper bounds for
`Vmax(shared)-Vmax(baseline)` and
`drop_max(shared)-drop_max(baseline)` must be at most zero, with positive
per-stream ingress/completed counts, identical input keys and measurement
signature/attribution, and zero censored in both arms. Treat any missing pair,
failed native gate, or nonconforming bound as inconclusive or a limitation;
do not substitute a favorable secondary result. The contract is still blocked
execution, not a measured result.

Do not set `reset_state_verified` directly. Each accepted arm must contain
native `reset_evidence.csv` contract version 1. It must cover all source and
worker processes, native process-start tokens/PIDs, zero queue-depth snapshots,
the cycle-0/sequence-1 source origin, an initially empty telemetry sink,
warmup exclusion, stop-admission before drain, and terminal `DRAINED` state.
The report derives the run gate from this file and rejects a pair that reuses a
process-start token or telemetry-sink ID across arms. The engineering
`reset_evidence.runtime.csv` is diagnostic only and is rejected by the
publication validator.

The publication report derives these values again from accepted raw sidecars.
For every primary arm it reruns topology validation and the complete
ingress/branch-terminal/stage-contract/resource/policy/drop/reset sidecar
validation, then rebuilds the measurement passport, semantic-prefix hash,
reset process-token set, and sink ID. Pair-critical `summary.csv` fields are
only consistency witnesses: any `summary_raw_mismatch:*` blocks the arm, and
the report never substitutes the summary value for the raw-derived value.
Before sidecar revalidation, the primary report requires schema-v2
`run_metadata.json` and cross-checks the top-level `mode`,
`result.run_mode`, and summary `run_mode` against `benchmark`. It also checks
the result identity plus the top-level run seed, policy, and dataset. It
re-resolves the configured scenario and requires both the stored
`resolved_scenario` and its declared version/hash to match the ordered pipeline,
topology/runtime blueprint, workload/routing, placement, network, and
distributed contract. Dataset name equality alone is likewise insufficient:
the report recomputes a versioned identity over the complete ordered logical
manifest and separately compares the aggregate stream checksum. It also
recomputes a versioned `publication_run_contract` over the exact run
coordinates, protocol, transport, telemetry contract, selected system
configuration, hardware target, and any applicable primary architecture or
policy preregistration record. The stored payload and declared identity must
both match. For an ordered architecture or policy arm,
`--resume-run-root` must also receive the same exact pair contract and match it
to the stored copy. Missing expected metadata, an unexpected stored pair
contract, coordinate or arm-position drift, mutually exclusive pair contracts,
or pair metadata in smoke mode is rejected. Generic matrix resume cannot
silently reuse ordered-arm provenance. After accepted-sidecar validation, each completed topology run also
stores a version-1 `publication_evidence_bundle`. The expected scope is derived
from config and run coordinates. Architecture and frozen-policy runs bind the
relative path, byte size, and SHA-256 of these exact files: `frames.csv`, `frame_events.csv`,
`resource_events.csv`, `policy_decisions.csv`, `drop_counters.csv`,
`topology_events.csv`, `ingress_ledger.csv`, `branch_terminals.csv`,
`stage_contracts.csv`, and `reset_evidence.csv`; the online-policy scope adds
`policy_feedback.csv`. Publication reporting and `--resume-run-root`
independently select the expected scope, recompute the full bundle, and reject
missing, changed, symlinked, scope-drifting, or identity-drifting evidence.
`system_metrics.csv` is outside all current scopes because the coprimary
architecture estimands do not consume it; expand and version the scope before
results if a later claim depends on another file or formal-policy artifact.
This bundle is a byte-integrity witness only. It does not prove native
origin, adapter correctness, remote attestation, or an effect. No accepted
bundle exists in the current workspace because the target KPP topology
benchmark has not run. The report also
requires the recorded `hardware_target` to equal the report configuration and
reassesses `detected_hardware` against that target. `--resume-run-root` applies
the same scenario, dataset, and publication-run checks, including requested
base and derived run seeds, before reusing a completed run. Missing,
inconsistent, or target-incompatible metadata is a contract error. These checks
establish configuration provenance and target-stand eligibility only; actual
execution still requires raw topology/sidecar acceptance, and neither is a
scientific measurement by itself.
The normal broad publication path applies this metadata gate to every
completed proof row before it creates `summary_combined.csv` or any secondary
report artifact. Primary-only mode is therefore not the sole enforcement
point and cannot be bypassed by selecting the broad report. The broad path
also reopens every completed proof run and validates raw frames,
stage/topology events, ingress, branch terminals, stage contracts,
resource/policy/drop sidecars, and reset evidence. It rederives the
measurement passport, semantic-prefix hash, reset identity, cohort counts, and
partial `c_obs` values and compares them with the summary copy. Any raw error
or mismatch stops processing before the report output directory is created;
secondary tables must never rely on summary-only gate flags.
Proof rows must be unique by expected-matrix cell (`dataset`, scenario,
deadline, deployment, system, policy, repeat) before any run directory is
resolved. Duplicate rows from the same or different `summary_path` values are
contract errors and must not be averaged or treated as additional repeats.
Every proof row must also belong to the matrix frozen by the report config.
Reject an unknown scenario or any out-of-plan dataset, deadline, deployment,
host topology, system, policy, or repeat before raw lookup. Missing expected
cells remain valid audit results with status `missing`; observed rows must
never extend the planned matrix.
The runner's stable summary schema must retain base/derived seeds, all
cohort/resource completeness counters, the full measurement-passport copy,
and reset contract identities. Do not remove these columns when changing
summary serialization: the primary report uses them for raw-versus-summary
consistency checks and exact pairing.
The runner validates the complete row set before opening `summary.csv`.
Every row must contain the common identity/metric fields and explicit
`run_mode`. A completed benchmark row must contain every stable-schema field
and use `telemetry_source=native`; unknown keys are a contract error. A
completed smoke row may omit proof fields and remains non-publishable even when
its frame rows have native provenance. `--resume-run-root` accepts completed
benchmark metadata only with the current schema and the requested `run_mode`;
the top-level metadata `mode` must also match the requested mode and
`result.run_mode`. Stale or partial metadata must not be merged into a
publication summary.
It exports `primary_architecture_pairs.csv`,
`primary_architecture_inference.csv`, and
`primary_architecture_claim_state.json`. The state is
`blocked_missing_required_pairs_or_gates` until all ten exact pairs and every
native/reset gate pass. With a complete accepted series, any failed interval
condition yields `not_confirmed_interval_conditions_failed`. If the full
intersection rule passes with a partial resource signature, the state is
`favorable_preregistered_rule_satisfied_partial_resource_coverage` and applies
only to measured CPU/GPU stage intervals. The unqualified
`favorable_preregistered_rule_satisfied` state is reserved for complete
resource coverage. None of these labels implies universal superiority outside
the frozen cell or complete CPU/GPU/NVDEC/transfer/fanout savings under partial
coverage.

The future interval-sidecar contract can be inspected without creating data:

```bash
python scripts/resource_interval_contract.py
```

The standalone validator result must remain
`validator_ready_not_emitted_not_publication_bound`, while the configuration
assessment reports
`ready_validator_and_fanout_source_not_target_verified_not_publication_bound`.
Both keep
`publication_bundle_bound=false` and `evidence_accepted=false`. A future
adapter may validate a candidate `resource_intervals.csv` only by supplying
the accepted `ingress_ledger.csv`, `topology_events.csv`, and
`frame_events.csv` plus the exact topology kind. The validator rejects proxy
durations, non-native rows, linkage drift, and duplicate native events; missing
expected transfer, decoder-submit-complete, or shared-fanout intervals produce
an incomplete non-accepted linkage result. Under contract version 2 only
CUDA-event transfer duration is additive resource work. Decoder
submit-to-output and queue sink-to-src spans are non-additive diagnostics; do
not sum them as NVDEC busy time, fanout resource work, or `C_obs`. Do not add this
sidecar to measurement passport v4 or publication evidence bundle v1. The
shared checkpoint source contains paired GStreamer queue sink/src probes and a
runtime-only `resource_intervals.runtime.csv` fanout emitter. The coordinator
requires exact fanout-topology coverage and forbids the fragment in the
independent-process baseline. This path has not run on the target stand and is
not an accepted sidecar; native CUDA-event and decoder submit/complete emitters
still do not exist, and true NVDEC/fanout activity counters are absent. A
publishable use requires a new preregistered
full-resource evidence scope before any result is inspected.

Pair rows also contain baseline-minus-shared CPU/GPU component deltas, the
component shares of both arms, and shared-minus-baseline share shifts. The
claim JSON summarizes these values in `resource_mix_diagnostics` with role
`secondary_descriptive_not_claim_condition` and `threshold_rule` set to
`none_preregistered`. Inspect them whenever the unweighted `C_obs` is
interpreted; they do not calibrate devices and do not change the frozen claim
rule. Treat `static_hybrid` as a run coordinate only: actual checkpoint
placement must be evidenced by accepted stage and resource traces. In the
primary H.264 pair, require `decoder_placement_verified=true` and the exact same
allowed decoder factory in both arms; keep NVDEC busy time unavailable until a
separate native activity counter is accepted.
The same report writes `primary_policy_equivalence_scope.json`,
`primary_policy_pairs.csv`, `primary_policy_inference.csv`, and
`primary_policy_claim_state.json`. The scope file records that the version-4
`policy_implementation_equivalence` proxy-passport replay is implemented but
has not been executed on an accepted pair. The replay recomputes decision
scores and every tie-break branch, checks the complete frozen passport and
runtime artifact SHA-256 for both arms, and reproduces online raw/projected
weights plus update/no-op reasons. The pair state machine requires exactly ten
counterbalanced pairs, matching seed/run seed/schedule/key sequence, terminal
map, and branch analytics contract hash, independent reset identities, zero censored frames, no online
drop-rate increase, positive completed counts per stream, and the actual
replay object. The complete replay assessment is serialized in the pair row.
Only 10/10 accepted pairs produce the paired percentile-bootstrap interval;
otherwise the claim state is `blocked_missing_required_pairs_or_gates`.
Its current static status remains
`ready_runtime_reference_replay_not_executed` with
`runtime_reference_replay_performed=false`, and the current claim has 0/10
accepted pairs. The separate formal AW-HEFT contract still fails the static
composition check for the current CPU/GPU proxy. Do not convert either static
status or the executable analysis path into a passed gate or a policy effect.
Before attempting the policy series, run:

```bash
python scripts/run_experiments.py --primary-policy-plan
```

This is a non-measurement contract audit. It emits the frozen order of twenty
arms with `primary_policy_pair.contract_version`, pair repeat, first/second
arm, and arm position. It currently reports
`blocked_runtime_policy_implementation_mismatch` and
`runtime_execution_allowed=false`: the v4 cell names `gstreamer_custom`, but
its plugin source does not emit the ql_heft v4 decision/feedback contract.
The only registered source-level emitter is the diagnostic internal-signal
`custom_cpp_cuda_qt` runtime, which is neither dataset-consuming nor
benchmark-eligible. `run_one` rejects pair metadata while this compatibility
assessment is blocked. The report generator independently applies the same
source-level assessment as a mandatory pair gate and records
`runtime_policy_implementation_not_compatible` on all pairs while it is
blocked. Accepted sidecars, proxy replay, and bootstrap therefore cannot
override the mismatch. Do not execute the twenty arms, substitute the
diagnostic runtime, or edit the frozen v4 cell after inspecting results. A
dataset-consuming implementation and its versioned cell binding must be
created before execution; architecture acceptance remains a separate
prerequisite after runtime compatibility passes.
Use `generate_vast_report_artifacts.py --primary-architecture-only` for this
primary run root. The default report mode still expects the broader secondary
matrix and must not be used to force missing secondary cells into the primary
claim.

The checkpoint pair additionally requires adapter-emitted
`branch_terminals.csv`. Its native rows use the same cohort, trace, frame, and
`input_frame_key` identity as the ingress ledger and record one `completed` or
`drop` outcome per observed analytics branch. Completed and dropped ingress
rows must cover the full preregistered branch set; a censored row may contain
only a completed subset and may not hide a native drop event. For a completed
admission, the one end-to-end `frames.csv` row uses
`detector=checkpoint_all_branches_per_stream_v1`, its object count equals the
sum of the four accepted branch results, and its egress time equals the latest
branch terminal time. Dropped and censored admissions have no completed frame
row. The publication report requires `branch_terminal_trace_complete=true`
and `checkpoint_frame_aggregation_complete=true` in addition to the ingress,
topology, semantic, resource, and SLO/drop gates. Current checkpoint adapters
do not emit this accepted sidecar.

For an accepted file, `detector` must be
`detector_id;model_sha256=<64 lowercase hex>` with an optional trailing
`;weights_sha256=<64 lowercase hex>`, and `backend` must name the verified
`openvino-dlstreamer:gvadetect` or `openvino-dlstreamer:object_detect`
factory. One branch may not change this identity during a run. The validator
hashes the sorted branch map as `branch_analytics_contract_sha256`; both the
baseline/shared and frozen/online pair gates require the same value.

Every applied policy row is also joined to `frame_events.csv` by
run/trace/frame/stage and must match its resource, decision-time queue depth,
and selected score. The custom CUDA+Qt adapter emits such rows for
`ql_heft_frozen` and `ql_heft_online` with policy version
`simplified-cpu-gpu-weighted-proxy-v4-*`. The source emits causal identity,
feature-provenance, terminal, source-decision, and first-consumer fields for
the current two-resource proxy contract. Its schema-v2 policy artifact fixes a
bounded mean-one initial weight vector and the online passport. The online
source path additionally writes one native `policy_feedback.csv` row for each
considered terminal outcome, including no-op, with old/raw/projected weights,
oldest-source maximum-staleness lag/cooldown, variation accounting,
action/reason, update sequence, and first
consumer. Helper and contract tests cover the deterministic projection, gate
order, artifact digest, exact CSV header, independent score/update replay, and
validator behavior. The decision trace now records the stage preference needed
to reproduce the final exact-score/exact-queue tie-break branch. The current
environment has no `nvcc`, so native `.cu` compilation, target-run emission,
and an observed `policy_online_trace_complete=true` remain to be verified.
This is not implementation evidence for the formal
CPU/GPU/NVDEC AW-HEFT model: native transfer/deadline-risk components, NVDEC,
the formal stability window, target-hardware compilation, and benchmark
measurements remain required.

A separately versioned static reference is available as
`policies/aw_heft_reference_v1.json` and
`scripts/formal_aw_heft_reference.py`. It implements deterministic contract
logic for `rank_u`, ready ordering, CPU/GPU/NVDEC scoring,
transfer/memory/deadline-risk components, causal heavy-scene correction,
tie-break, three-resource projection, bounded feedback, and a version-1
input-only replay contract. Replay recomputes the canonical graph/profile
identity, ranks, ready order and all alternatives, then checks the complete
applied-source set, parameter-state continuity, frozen/online update mode and
the first consumer of each applied update. Both files are SHA-256-bound in
`configs/experiments.yaml`. Verify them without starting a run:

```bash
python scripts/formal_aw_heft_reference.py
```

The command must report `reference_only_not_runtime_bound`,
`runtime_bound=false`, `benchmark_eligible=false`,
`formal_reference_replay_implemented=true`, and
`accepted_formal_trace_replay_performed=false`. A replay-input packet can be
checked explicitly with:

```bash
python scripts/formal_aw_heft_reference.py --trace /path/to/formal-replay-input.json
```

Such a packet must identify itself as
`replay_input_only_not_accepted_telemetry`; successful replay reports
`evidence_accepted=false` and does not enter the publication evidence bundle.
The formal equivalence scope therefore remains
`blocked_reference_not_runtime_bound_or_preregistered`: no formal H2 cell is
preregistered, the reference is not a dataset-consuming adapter, and no
accepted formal trace or replay of accepted evidence exists.

The primary frozen/online cell is already frozen in
`benchmark.primary_policy_ablation`. It reuses the accepted shared Video-DAG
cell with `kpp_real_h264`/H.264, 100 ms, six logical streams,
`all_branches_per_stream` in `topology_only_stress` scope, batch size 1, seed
20260323, 30 s warmup, 180 s measurement, and ten paired repeats. Arm order is
counterbalanced; each measurement reloads the same schema-v2 artifact and
clears feedback/update state. Acceptance uses completed-frame
`Vmax(online) - Vmax(frozen)` and a 95% paired percentile bootstrap with 10,000
resamples. The upper bound must be below zero and the pair must have identical
`input_frame_key` sequences, identical terminal status for every key, zero
censored, no online drop-rate increase, and positive completed frames in every
stream. Do not add `ql_heft_*` to `scheduler_policies` while the cell remains
`preregistered_blocked_execution`; first accept the architecture, a
dataset-consuming policy path, all native policy gates, pair/reset identity,
and implementation equivalence.

The current custom binary is not a publishable video adapter: it generates an
internal signal and does not read the selected H.264/H.265 dataset. Its system
entry is marked `benchmark_status: diagnostic_only`; the default benchmark
matrix excludes it, an explicit benchmark request fails, and
`run_system_template.sh` has the same guard. Use it only in smoke/engineering
mode for scheduler and trace checks until a dataset-consuming implementation
preserves frame provenance from the configured source.

The intended publication command, to be used only after implementing and
validating both physical topologies, is:

```bash
python scripts/run_experiments.py --mode benchmark --run-kind heterogeneous \
  --systems deepstream savant openvino_gva gstreamer_custom \
  --scenarios checkpoint_independent_processes_baseline checkpoint_video_dag_shared \
  --repeats 1 --warmup 0 --measurement 30
```

Tailored behavior in real templates:
- DeepStream: benchmark mode uses `vast/deepstream-native-probe:7.0` with a native `uridecodebin -> nvstreammux -> nvinfer` probe graph; the sample app path is smoke/demo only.
- Savant: benchmark mode uses `deploy/savant/canonical_heterogeneous_module.yml` or `deploy/savant/canonical_distributed_module.yml` with native CSV telemetry merge.
- OpenVINO+GVA: pinned OpenVINO Python install `2024.6.0`, uses `gvadetect` with the exact OpenVINO model XML path above.
- GStreamer custom: builds bundled plugin `build/lib/libgstadaptivescheduler.so` from `deploy/gstreamer_adaptivescheduler` and uses element `adaptivescheduler`; it falls back to `identity` only outside strict mode.
- Custom CUDA + Qt diagnostic path: builds `build/bin/adaptive_scheduler_app` from
  `deploy/custom_cpp_cuda_qt/adaptive_scheduler_app.cu` through CMake and runs
  its Qt dashboard with `QT_QPA_PLATFORM=offscreen`; benchmark mode rejects it
  until the binary consumes the configured video dataset.

Blocked dissertation benchmark scenarios:
- `checkpoint_independent_processes_baseline` requires four independently
  launched detector branches that each consume the same source frame and
  execute their own decode/preprocess path.
- `checkpoint_video_dag_shared` requires one measured decode/preprocess prefix,
  native fanout into four analytics branches, and join-complete frame
  provenance.
- Stage-name coverage, sequential placeholder operations, and telemetry hooks
  do not satisfy these topology requirements.

Useful template environment variables:
- `DEEPSTREAM_IMAGE`, `DEEPSTREAM_CONFIG`
- `SAVANT_IMAGE`, `SAVANT_MODULE`, `SAVANT_SOURCE`
- `OPENVINO_MODEL_XML`, `OPENVINO_SOURCE`
- `OPENVINO_GVA_IMAGE` (default: `intel/dlstreamer:latest`)
- `OPENVINO_GVA_USE_CONTAINER` (`1` by default; set `0` to force host runtime path)
- `GST_CUSTOM_PLUGIN`, `GST_CUSTOM_SOURCE`
- `CUSTOM_APP_BIN`
- `EXPERIMENT_SCENARIO_JSON`, `EXPERIMENT_DISTRIBUTED`, `EXPERIMENT_HOST_ROLE`, `EXPERIMENT_PIPELINE_STAGES`
- `BENCHMARK_MODE`, `DATASET_NAME`, `DATASET_STREAMS_JSON`, `EXPERIMENT_RUN_ID`, `EXPERIMENT_RUN_SEED`
- `SCHEDULER_POLICY`, `QL_HEFT_POLICY_ARTIFACT`
- `NATIVE_PROBE_BIN`, `DEEPSTREAM_NATIVE_PROBE_IMAGE`, `SAVANT_NATIVE_PROBE_IMAGE`
- `SAVANT_CANONICAL_MODULE`, `DEEPSTREAM_PGIE_CONFIG`, `GST_CUSTOM_STRICT`
- `DISTRIBUTED_NATIVE_CMD_<SYSTEM>_<ROLE>` or `DISTRIBUTED_NATIVE_CMD` as override paths for native role-specific RTP commands

Build and verify the bundled GStreamer custom plugin manually:

```bash
cmake -S . -B build/cmake -DVAST_BUILD_GSTREAMER_CUSTOM_PLUGIN=ON
cmake --build build/cmake --target gstadaptivescheduler
GST_PLUGIN_PATH="$PWD/build/lib" gst-inspect-1.0 adaptivescheduler
```

## Scenario Schema and Distributed Runs

`configs/experiments.yaml` now uses structured scenario definitions:
- `workload`: stream count/range, object density, burst profile, and optional variants
- `pipeline`: ordered video analytics stages
- `placement`: maps each stage to a logical role such as `local`, `edge`, `gpu_worker`, or `aggregator`
  - `network`: records measured-network acceptance ranges
- `distributed`: enables staged SSH orchestration with RTP endpoints

Distributed host inventory lives in `configs/hosts.yaml`. Replace the placeholder hostnames with real SSH-accessible Linux/WSL hosts:

```yaml
hosts:
  - name: edge-node
    address: edge01.example.net
    user: vast
    port: 22
    project_path: /opt/vast
    roles: [edge]
```

Do not store SSH keys, passwords, or private credentials in the repository.

Execution modes:
- `--run-kind heterogeneous`: regular one-server CPU/GPU execution; `--run-kind local` remains a deprecated alias.
- `--run-kind single-server-distributed`: launches `edge`, `gpu_worker`, and `aggregator` through SSH on one server and disables project rsync.
- `--run-kind distributed`: launches roles on the hosts from `configs/hosts.yaml`.

Prepare and validate the frozen KPP primary dataset. The preparation command
requires the two checksum-matching source AVIs, creates only two physical H.264
targets for the six logical entries, verifies the output hashes, and then runs
the full ffprobe/annotation/identity preflight:

```bash
python scripts/prepare_benchmark_dataset.py --dataset kpp_real_h264
python scripts/check_dataset.py --dataset kpp_real_h264
```

Use `--dataset kpp_real_h265` for the secondary codec dataset. `--dry-run`
checks the regeneration plan and source checksums without writing target files.
Preparation never changes the manifest and does not make a run publishable.

Preview the resolved launch plan without creating a run:

```bash
python scripts/run_experiments.py --mode smoke --run-kind heterogeneous --dry-run-plan --systems custom_cpp_cuda_qt --scenarios checkpoint_independent_processes_baseline --repeats 1 --measurement 5
python scripts/run_experiments.py --mode smoke --run-kind heterogeneous --dry-run-plan --systems custom_cpp_cuda_qt --scenarios checkpoint_video_dag_shared --repeats 1 --measurement 5
```

Build strict native probe images for DeepStream and Savant:

```bash
scripts/build_native_probe_images.sh
```

Primary publication execution after topology acceptance and target-host setup:

```bash
python scripts/run_experiments.py --primary-architecture-run \
  --output-root /path/outside/the/repository
```

The broad matrix remains a separate secondary workflow and must not replace
this counterbalanced primary executor.

Distributed roles start as `aggregator`, `gpu_worker`, then `edge`. Multi-host
preflight requires `chronyc`, `ping`, and `iperf3`. Single-server SSH topology
writes `same_host_loopback` network metrics and skips chrony/iperf checks.
Network shaping is not applied. The degraded network scenario is skipped unless
measured values match its configured acceptance ranges.

Canonical RTP transport uses one UDP port per stream:
`edge_to_gpu_worker + stream_id * stream_port_stride` and
`gpu_worker_to_aggregator + stream_id * stream_port_stride`. The strict trace
header extension is id `1`, URI `urn:vast:rtp-trace:v1`, and contains
`stream_id`, `frame_id`, and original ingress timestamp.

Use `--run-kind local` to execute a scenario through the local path for smoke testing:

```bash
python scripts/run_experiments.py --mode smoke --run-kind local --systems custom_cpp_cuda_qt --scenarios checkpoint_video_dag_shared --repeats 1 --warmup 0 --measurement 5
```


Legacy setup notes for engineering paths:


    python3 scripts/setup_target.py


    bash scripts/prepare_assets.sh


The legacy one-line benchmark invocation was removed because it mixed a
diagnostic signal adapter with an undefined `baseline` scenario.
