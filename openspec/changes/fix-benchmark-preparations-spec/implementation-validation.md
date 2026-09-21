# Implementation validation — in progress

Change: `fix-benchmark-preparations-spec`. Preparation is not ready. No qualification, Q4 or full-matrix arms have been launched by this change. Draft PR #2 continues the approved planning change after the explicitly authorized recovery from merged PR #1.

## Verified repairs

- The native client validates bounds before allocation, hashes its owned snapshot, rejects a wrong supplied digest before exchange, and seals the same bytes. The discovered Linux regression compiles with existing GLib tooling. Its cases cover the 64-MiB boundary, synchronized caller-buffer reuse and descriptor cleanup. The wrong-digest case failed against the original implementation and passed after repair.
- Guardian control validation now precedes request reservation and payload verification. The focused tests cover attributed and unattributed rejections, first-failure concurrency, bounded immutable diagnostics, unsafe descriptors and persistence failure. A pre-authority failure cannot commit an orphan diagnostic.
- All four service/supervisor API/CLI unexpected-retry defaults are zero. Omission tests verify the default and its forwarding; supervisor behavior tests verify one launch, permanent exit 78 and no retry sleep. Existing explicit retry budgets and transient exit 75 recovery remain covered.

## Focused Linux test results

Executed on 2026-09-21 using the existing frozen CPython 3.12 environment, without installing dependencies:

- Native client runner: 1 test passed, including embedded C++ cases.
- GStreamer analytics bridge: 8 passed.
- Production sidecar: 50 passed.
- Analytics protocol: 4 passed.
- Full-publication supervisor: 13 passed.
- WSL service materialization: 25 passed.
- Storage recovery: 10 passed.
- Qualification execution closure: 13 passed.
- Failed-guardian evidence snapshot: 9 passed, including a diagnostic emitted by the real sidecar failure path. Existing lifecycle v1 fixtures and the successful-only qualification closure remain unchanged. A read-only check against actual A269 authority/lifecycle files returned explicit historical diagnostic absence, created no snapshot and preserved both source hashes. Second/third-write failures also preserve sources and partial output, report no success, reject reuse of that partial path and permit a fresh snapshot path. The collector does not claim atomic directory publication.

The combined verification captured unchanged before/after source hashes. Initial harness invocations were retained as failures: `-S` hid the environment's required NumPy/YAML packages, and `-I` prevented a storage-test import of the repository's `tests` namespace. Corrected invocations passed; no source or dependency change was needed to resolve those harness errors.

Reproduce each module from the repository root with the verified frozen interpreter:

```bash
"$PYTHON" -B -X utf8 -m unittest discover -s tests -p test_checkpoint_analytics_execution_client_cpp.py -v
"$PYTHON" -B -X utf8 -m unittest discover -s tests -p test_checkpoint_gstreamer_analytics_bridge.py -v
"$PYTHON" -B -X utf8 -m unittest discover -s tests -p test_checkpoint_gstreamer_analytics_sidecar.py -v
"$PYTHON" -B -X utf8 -m unittest discover -s tests -p test_analytics_execution_protocol.py -v
"$PYTHON" -B -X utf8 -m unittest discover -s tests -p test_full_publication_supervisor.py -v
"$PYTHON" -B -X utf8 -m unittest discover -s tests -p test_full_publication_wsl_user_service_v1.py -v
"$PYTHON" -B -X utf8 -m unittest discover -s tests -p test_publication_storage_recovery.py -v
"$PYTHON" -B -X utf8 -m unittest discover -s tests -p test_publication_policy_qualification_execution_closure_v1.py -v
"$PYTHON" -B -X utf8 -m unittest discover -s tests -p test_benchmark_preparation_evidence_v1.py -v
```

## Image and operational gates

The three native foundations passed deterministic A/B rebuilds with identical image IDs within each pair, stock source/context checks and smoke execution. Their identities changed as expected. The two dependent analytics worker images also rebuilt successfully against the new native receipt. All four runtime images then rebuilt and passed stock capture/patch verification. Packaged tests found that OpenVINO GVA and GStreamer Custom omitted a module required by the bridge/guardian. Both Dockerfiles now copy that module into the final runtime and exercise real guardian imports during the build. Those two images were rebuilt again and replacement receipts/patch verified; their earlier receipts are retained as superseded evidence.

Current packaged protocol/bridge/sidecar suites pass in all four runtimes; both worker protocol suites pass. Existing packaged policy, clock/backend and external-manifest checks also pass on the current images. Fifteen image/source-closure tests passed. An affected CUDA-transfer test initially failed to compile because its command lacked GLib flags; its corrected compiler invocation passed both tests. No extra runtime dependency was installed.

The fresh physical parity materializer completed its original invocation with exit 0: 480 executions in 32 groups, 15 per group. The stock acceptance loader returned successfully and the physical descriptor traversal passed. A later independent-comparison wrapper then failed because it looked for the historical reference in the isolated checkout; that failure was retained. A separate comparison against the original read-only reference passed, with all 480 input/output tensor hashes matching.

Host identity fixtures were then renewed in the four host-only files so OpenVINO GVA and GStreamer Custom constants match the rebuilt `:materialized` images (`sha256:261ef8a6…` and `sha256:4e1cbec0…`). Thirteen focused identity tests passed in 0.194s. The stock v4 acceptance loader then reloaded the current receipts (`acceptance_identity_sha256=7d6fd530…`). Live preflight was not executed: the accepted assessment identity is bound to the worktree `models/` inventory without OMZ proxy files, and `_omz_bindings` requires those files at `models/openvino`. The live preflight test now skips unless both Docker and those OMZ files are present.

The environment baseline records the frozen interpreter/packages, OS/kernel/WSL/Docker, CPU/GPU/driver and power/resource settings, current data/model/image/parity descriptors, 24-GB WSL configuration and process ownership. A269 remains retired; no workers or containers remained after parity. These observations do not replace final live preflight.

The final ext4 suite, fresh qualification, Q4, dated capacity, live preflight and the unstarted service package remain pending.

The new preparation runbook passed syntax-only Bash parsing, its explicit variable allowlist and parser-only CLI checks. README, PLAN and progress link it while retaining historical A269 status and numbered PLAN obligations.

## Evidence and review limits

Detailed operational inventories, physical paths and raw logs remain local. This document summarizes actual checks; it is not a runtime authorization receipt or a CI result. A full service launch was not performed by the focused tests. Required final scenario conformance and latest-commit checks remain outstanding. CI setup is outside this change's approved scope; no CI success or merge readiness is claimed.
