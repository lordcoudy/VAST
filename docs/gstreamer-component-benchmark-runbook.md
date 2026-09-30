# GStreamer component benchmark

This entry point runs a real baseline/shared GStreamer pair for one analytics resource, then stops the guardian and cold-validates both arms. Run CPU and GPU separately. A completed pair produces descriptive data; it does not complete the historical multi-backend qualification campaign.

## Current validation status

Current execution checkpoint: `0ad78d6abdb3c526544a17185af7fe8094716735`, OpenSpec change `fix-benchmark-preparations-spec`, PR2. The isolated ext4 execution copy preserves all2693 selected inputs and4,379,009,017 original bytes. Independent setup, read-only Docker bind and fresh stock87-source closure checks passed. CPU06 completed successfully in803.434s, including full all-phase cold reconciliation, within the2100s limit. Its independent95-file custody/cleanup audit passed, guardian stopped and20GiB reserve released. GPU01v3 remains unexecuted; final four-arm scientific and repository acceptance are incomplete.

CPU05 is preserved as a failed attempt: both native arms and full cold reconciliation completed, but the original CLI failed its final2100s deadline at2125.861s. Its CSV/SVG does not establish an accepted pair. Independent95-file audit confirms unchanged inputs, stopped processes/guardian and released reserve. The ext4 approach changes storage and preparation, while retaining the selected image, source checks, full cold validation and scientific settings.

The selected runtime image is `sha256:e474867043f1a74387573140cb2bfd69825df2672edad0acda0d28954af84cb6`. Its73 sources and six dependencies are unchanged by the three host-only session edits. Receipt and host closure identities are distinct: changing a host source requires a new host closure even when the image remains current.

## Fixed experiment

Each pair retains six H.264 streams, four branches, seed20260323,100ms deadline,30s warmup,180s measurement and10s drain. Baseline uses independent pipelines; shared uses a shared video DAG. Both retain the same measured ingress schedule. The guardian loads and warms all eight CPU/GPU workers symmetrically, then the arm's forced policy selects the analytics resource.

`--resource cpu` means CPU analytics inference. The video pipeline still uses NVDEC; this is not a comparison of CPU decoding against GPU decoding. The workload is a topology/load proxy, with no accuracy or quality noninferiority claim.

The stock CLI allows2100s for a pair. Recovery controllers retain2250s outer capture and15s containment cleanup. They do not extend the measurement. The CLI reserves20GiB of real scratch space while retaining a20GiB free floor; use a local scratch filesystem with sufficient capacity. Output must be a fresh, exclusive directory under the project root. Use a short scratch root so Unix socket paths remain below108 bytes.

## Prerequisites

Use Linux/WSL2 with the validated Python3.12.3 environment, the Docker client and Unix socket, and actual NVIDIA GPU/NVDEC support. The selected runtime, three native images and two worker images must remain available under their recorded identities. Original model binaries, raw numeric parity evidence, calibration samples, source clips and all referenced manifests must be physically present. The CLI checks these facts; a filename or copied receipt is insufficient.

Use a canonical, private execution root on the Linux ext4 filesystem. This avoids making the benchmark's repeated physical validation depend on the Windows filesystem bridge. The retained concrete root below has its own detached Git HEAD/index, an exact tracked checkout, and exclusively copied original input leaves. Its shared Git object dependency is `/mnt/e/STUDY/VAST/.git/objects`; preserve that repository and the referenced ancestry. A path string alone does not prove storage type, source bytes or Docker bind reachability.

Freeze the source before capture. Do not edit a held source, replace an input, change the active execution root's HEAD, or remove an image while an original recovery controller is running. Wait for original EOF, process/container quiescence, authenticated guardian stop and reserve release before changing source or dispatching another pair. Keep failed output permanently and diagnose its first cause before choosing a new namespace.

The following commands use the concrete selected input bundle retained in this repository. They require those original files and their current images. A future source/image/model change requires genuinely refreshed evidence; do not change recorded hashes to make old evidence appear current.

```bash
ROOT=/home/s-a-balashov/work/vast-component-release-20260930-d27
PYTHON=/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python
CAPABILITY="$ROOT/artifacts/publication_policy_qualification_v2_fix_benchmark_20260928g/candidate/checkpoint_policy_capability_candidate_manifest.json"
CALIBRATION="$ROOT/artifacts/publication_policy_qualification_v2_fix_benchmark_20260928g/bootstrap/checkpoint_policy_qualification_bootstrap_calibration.gstreamer_custom.v2.json"
MODEL="$ROOT/configs/checkpoint_analytics_model_parity.refreshed.v4.fix-benchmark-20260928g.accepted.acceptance_receipt.json"
IMAGE="$ROOT/artifacts/benchmark_recovery_20260930/selected-gstreamer-build-a4e145b7-v1/gstreamer_custom.runtime.freeze.json"
WORKERS="$ROOT/artifacts/fix_benchmark_preparations_20260928g/worker_images/analytics-worker.freeze.json"
CLOSURE="$ROOT/artifacts/gstreamer_component_release_20260930_a4e145b7/host/execution-code-closure.ext4.v1.json"
```

Capture a new closure through `scripts/publication_policy_qualification_execution_code_closure_v1.py` whenever its physical source/interpreter facts change. Existing closure files are exclusive receipts and must not be overwritten. The fresh ext4 receipt is30266 bytes, SHA256 `adbcb638a5f104e43c95b84e4d16388a8111d39321afb3e8e7a26f2ef537b498`; it remains usable only while the stock loader verifies its original source epochs and interpreter. The historical Windows-rootv6 receipt is not current authority at the new root.

For a fresh pair, choose a new output name and resource, then invoke the real CLI with its default production dependencies:

```bash
RESOURCE=cpu
OUTPUT="$ROOT/artifacts/gstreamer-component-local/cpu-pair-new"
ENTRY="import runpy,sys;sys.path.insert(0,sys.argv[1]+'/scripts');root=sys.argv.pop(1);runpy.run_path(root+'/scripts/publication_gstreamer_component_cli_v1.py',run_name='__main__')"
"$PYTHON" -I -B -c "$ENTRY" "$ROOT" \
  --project-root "$ROOT" --resource "$RESOURCE" --output-dir "$OUTPUT" \
  --scratch-root /tmp --container-engine /usr/bin/docker \
  --container-engine-socket /run/docker.sock \
  --capability-manifest-path "$CAPABILITY" --calibration-path "$CALIBRATION" \
  --model-parity-receipt-path "$MODEL" --runtime-image-receipt-path "$IMAGE" \
  --worker-freeze-receipt-path "$WORKERS" --execution-code-closure-path "$CLOSURE"
```

The separately retained recovery controllers add bounded external capture, exact HEAD binding and95 simultaneously held source/input/interpreter/controller files. They take the actual40-character source commit and64-character closure hash as arguments. CPU06 completed and its exclusive output namespace is consumed; CPU05 and all prior failed namespaces remain immutable. GPU01v3 is unexecuted and requires its separate reviewed dispatch. The generic CLI command above can be repeated only with a new output name and still-valid physical inputs. Relocation to another physical project root requires a new stock host closure and newly produced component execution authorities; copying historical execution receipts does not authorize reuse.

## Progress and completion

`component_pair_timing.v1.jsonl` records at most12 start/terminal phase pairs within16KiB: reservation, source, context, capture, preprocessing, guardian start, runtime, baseline, shared, guardian stop, cold, context close. These are actual monotonic/wall-clock observations. A start without a terminal remains incomplete. Timing is diagnostic and grants no acceptance.

Require exit0 and a successful `component_cli_terminal.v1.json` with its original cleanup and pair-result descriptor. Inspect the cold result at `cold-pair/component_pair_result.v1.json`, both arm receipts, raw sidecars, original process/container captures and guardian lifecycle. An arm's exit0 or an existing CSV alone does not prove a completed pair. Cold validation requires the full operational journal, including warmup/drain, as well as measured ingress, branch/drop provenance, resource attribution and equal schedule fingerprints.

The cold pair writes `component_pair_metrics.csv` and `component_pair_latency_ecdf.svg` before committing its receipt. The CSV reports admitted/completed/dropped/censored counts, deadline misses and coverage. ECDF and latency quantiles describe completed measurement frames only; interpret them alongside drops. Ratios with a nonpositive baseline remain null with a reason. One pair per resource has no population confidence interval.

Before interpreting carried `C_obs` values, independently rerun the stock raw-sidecar reducer under physical input custody and compare every carried field. `C_obs` is partial attributed stage elapsed time. It is not CPU work, GPU/NVDEC busy time, energy saving or an accuracy score. A negative result, including zero frames meeting100ms, is a valid scientific outcome when the full original pair and raw reduction pass.

Every component authority/result retains false qualification/publication/full-run eligibility. The legacy32-arm,1120-operation and5600-operation campaigns remain explicitly unexecuted. Final repository acceptance additionally requires the actual native/portable CI, source/skip checks and archived-spec conformance; focused tests do not satisfy those gates.
