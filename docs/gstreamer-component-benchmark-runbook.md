# GStreamer component benchmark

This entry point runs a real baseline/shared GStreamer pair for one analytics resource, then stops the guardian and cold-validates both arms. Run CPU and GPU separately. A completed pair produces descriptive data; it does not complete the historical multi-backend qualification campaign.

## Current validation status

Current benchmark source: `a00aa57f7d9534f8e7920f14f70d6a75a23570ed` (B), OpenSpec change `fix-benchmark-preparations-spec`, PR2. Genuine CPU08 and GPU02 completed with original CLI exit0, full all-phase cold reconciliation and authenticated guardian cleanup. Their outer captures took814.727s and841.889s within the unchanged2100s CLI/2250s capture limits. Independent audits verified all95 held input hashes/seven epochs, output hashes, process quiescence, descriptor closure and release of each20GiB reserve. One unchanged stock four-arm raw-sidecar reduction completed in60.223s, matching all carried summaries and CSV fields and preserving original custody. Implementation checkpoint,3 October2026,repository source D `3c025b29`: hosted and prerequisite-corrected local full CI passed; independent current conformance, same-change archive, checks on the eventual archived commit and exact final review were pending at this snapshot. The [PR2 final process ledger](https://github.com/lordcoudy/VAST/pull/2) records subsequent repository closure.

The practical path uses a private Linux ext4 checkout, one bounded guardian per resource pair and a standalone component CLI. It measures the selected GStreamer baseline/shared comparison without requiring an unfinished multi-backend campaign to run first. The original32-arm,1120-operation and5600-operation campaigns remain unexecuted and retain their original requirements.

The selected runtime image is `sha256:222a0003661e8229a431c69a513d7352294e6a38028abeb5b133aab45b3945a1`, with its genuine source/import/embedded freeze. Its 73 selected sources, three native foundations and two worker source closures remain verified. The actual stock 87-source host closure is distinct from the image receipt. Current repository code is `3c025b29b3c1d5275c2ec693410e4b83700583de` (D). Its CI clock repair and three selected-image test literals change neither the 95 benchmark inputs nor these runtime closures, so they do not require a measurement replay. Hosted run 37116707816 genuinely passed: 3001 discovered tests, 2992 selected, 2904 successes, 88 individually allowed skips, zero failures/errors, all six native builds and all three required native regressions. Source-before/after inventories match.

The separate earlier original ext4 full CI failed its final skip audit: the canonical interpreter was installed but its required project read-only bind was absent. All2992 tests finished with2904 successes,88 skips and zero testcase failures/errors; that failed CI remains failed. The unchanged stock mount helper subsequently materialized and checked the read-only bind. The existing runtime test then passed without a skip, and a fresh audit verified every original benchmark input hash and Linux identity. The prerequisite-corrected original full CI subsequently passed against unchanged D source in a fresh output directory:3001 discovered,2992 selected,2906 successes,86 approved skips,9 deferred integrations and zero failures/errors. All six native builds and all three required native regressions passed; source-before/after tables matched all5577 files. Its original capture closed with exit0 after2115.37338894s. The namespace diagnostic succeeded and the profile was not required. The two formerly skipped local checks ran successfully; this local count differs from the hosted2904/88 outcome. The [independent original review](../artifacts/benchmark_recovery_20260930/decision29-local-ci-D-prerequisite-result-review-preparation-v1/original-prerequisite-review-attempt01/review.v1.json) retains report, observer/wrapper closure and reader FD6 to6. Current conformance, archive, checks on the eventual archived commit and exact final review remain pending.

Earlier outcomes remain historical. CPU05 failed its final2100s deadline at2125.861s despite native/cold completion. CPU06/GPU01 were accepted at0ad/e474 and have preserved earlier science. CPU07 failed with EPIPE after a completed worker response; its underlying disconnect cause remains unknown and its later Docker exit-zero event does not establish that cause. The repairs preserve original failure channels and distinguish worker invocation from response delivery. No earlier failed namespace or receipt has been overwritten or relabeled.

## Fixed experiment

Each pair retains six H.264 streams, four branches, seed20260323,100ms deadline,30s warmup,180s measurement and10s drain. The offered rate is1fps per logical stream,6fps total. Five streams replay the front-gate recording and one replays the underbody recording; these are replicas of two recordings. Source PTS/DTS/duration and cycle duration use exact timestamp scale600 from the encoded600fps timeline. Baseline uses independent pipelines; shared uses a shared video DAG. Both retain the same measured ingress schedule. The guardian loads and warms all eight CPU/GPU workers symmetrically, then the arm's forced policy selects the analytics resource.

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
IMAGE="$ROOT/artifacts/benchmark_recovery_20260930/decision28-gstreamer-build-2a6a42c9-v1/gstreamer_custom.runtime.freeze.json"
WORKERS="$ROOT/artifacts/fix_benchmark_preparations_20260928g/worker_images/analytics-worker.freeze.json"
CLOSURE="$ROOT/artifacts/gstreamer_component_release_20260930_a4e145b7/host/execution-code-closure.ext4-decision28.v4.json"
```

Capture a new closure through `scripts/publication_policy_qualification_execution_code_closure_v1.py` whenever its physical source/interpreter facts change. Existing closure files are exclusive receipts and must not be overwritten. The fresh ext4 receipt is30266 bytes, SHA256 `3c91339d43f6154dd76afe8a89c02d82f60a4b1e5da16623039f691fdc6701f2`; it remains usable only while the stock loader verifies its original source epochs and interpreter. The historical Windows-rootv6 receipt is not current authority at the new root.

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

The separately retained recovery controllers add bounded external capture, exact HEAD binding and95 simultaneously held source/input/interpreter/controller files. They take the actual40-character source commit and64-character closure hash as arguments. CPU08 and GPU02 completed and both exclusive output namespaces are consumed; CPU05, CPU07 and all prior failed namespaces remain immutable. Choose GPU with `RESOURCE=gpu` and a separate fresh output directory after the CPU CLI has stopped and released its reserve. The generic CLI command above can be repeated only with a new output name and still-valid physical inputs. Relocation to another physical project root requires a new stock host closure and newly produced component execution authorities; copying historical execution receipts does not authorize reuse.

## Progress and completion

`component_pair_timing.v1.jsonl` records at most12 start/terminal phase pairs within16KiB: reservation, source, context, capture, preprocessing, guardian start, runtime, baseline, shared, guardian stop, cold, context close. These are actual monotonic/wall-clock observations. A start without a terminal remains incomplete. Timing is diagnostic and grants no acceptance.

Require exit0 and a successful `component_cli_terminal.v1.json` with its original cleanup and pair-result descriptor. Inspect the cold result at `cold-pair/component_pair_result.v1.json`, both arm receipts, raw sidecars, original process/container captures and guardian lifecycle. An arm's exit0 or an existing CSV alone does not prove a completed pair. Cold validation requires the full operational journal, including warmup/drain, as well as measured ingress, branch/drop provenance, resource attribution and equal schedule fingerprints.

The cold pair writes `component_pair_metrics.csv` and `component_pair_latency_ecdf.svg` before committing its receipt. The CSV reports admitted/completed/dropped/censored counts, deadline misses and coverage. ECDF and latency quantiles describe completed measurement frames only; interpret them alongside drops. Completion differs between arms, so their latency samples can contain different admitted frames; a median difference is not a matched-frame causal speedup. Ratios with a nonpositive baseline remain null with a reason. One pair per resource has no population confidence interval.

Before interpreting carried `C_obs` values, independently rerun the stock raw-sidecar reducer under physical input custody and compare every carried field. `C_obs` is partial attributed stage elapsed time. It is not CPU work, GPU/NVDEC busy time, energy saving or an accuracy score. A negative result, including zero frames meeting100ms, is a valid scientific outcome when the full original pair and raw reduction pass. One baseline-first pair per resource supports a descriptive fixed-case comparison; it does not separate order, thermal or shared-resource effects.

## Current descriptive results

The independently recomputed [CSV](../artifacts/benchmark_recovery_20260930/decision28-four-arm-science-preparation-v1/attempt01/four_arm_metrics.csv) and [figure](../artifacts/benchmark_recovery_20260930/decision28-four-arm-science-preparation-v1/attempt01/four_arm_latency_coverage_cobs.svg) accompany each latency distribution with completion coverage, deadline outcomes and partial attributed elapsed time. Each arm admitted1080 measured frames; none was censored.

- CPU baseline/shared completed516/664 and dropped564/416. Completion coverage was47.78%/61.48%; median completed latency was5727.5/3621ms. Both had zero on-time completions.
- GPU baseline/shared completed1070/1075 and dropped10/5. Completion coverage was99.07%/99.54%; median completed latency was2127/2168ms. On-time completions were3/1, or0.278%/0.093% of admitted work.
- Partial `C_obs` per admitted frame was14286.59/7613.10ms for CPU and10291.31/2984.16ms for GPU. Its lower shared total is a reduction in attributed elapsed time; it establishes no processor-work or energy saving.

The observed SLO failures and drops do not identify their causal mechanism. These results show operation and fixed-case behavior; they do not show that the system meets100ms or that shared execution improves GPU deadline performance.

Every component authority/result retains false qualification/publication/full-run eligibility. The legacy32-arm,1120-operation and5600-operation campaigns remain explicitly unexecuted. Final repository acceptance additionally requires the actual native/portable CI, source/skip checks and archived-spec conformance; focused tests do not satisfy those gates.
