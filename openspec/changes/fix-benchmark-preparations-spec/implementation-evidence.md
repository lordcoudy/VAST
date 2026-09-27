# Implementation evidence

Status: implementation in progress; preparation_ready=false, full_run_started=false, publication_ready=false. Earlier failed pre-check chains, including `20260927b` through `20260927e`, remain historical and unaccepted with their actual guardian lifecycles preserved. The `20260927f` nine-image, 23-check packaged, 480-execution/32-group parity and final ext4 retry gates have passed on their exact bytes; the retry ran 2,545 tests with 88 reviewed skips and the independent checker rehashed 2,874 files. Its first failed ext4 attempt remains preserved. Fresh f input materialization is running; guardian, four native CPU/GPU pre-checks, Savant diagnostic and 32 qualification cells remain unaccepted. Q4, capacity and preflight remain open. No full-run arms have started. See implementation-validation.md for physical evidence and limits.

## Approval and workflow recovery

The user approved spec commit `9cf91d929c52e587d012c40555db8c99c4304d1f`, recording the approval on PR #1 and using a follow-up Draft PR with the same change name and branch. Approval was recorded at https://github.com/lordcoudy/VAST/pull/1#issuecomment-5759830400 before code edits. PR #1 had already been merged as `f8b4c3cdce52dd9d4971e44868dadb052621f50a`. This is an explicitly authorized recovery of the PR sequence, not retrospective reviewer approval or completed implementation.

Branch: codex/fix-benchmark-preparations-spec. Worktree: E:/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec. Original dirty runtime at E:/STUDY/VAST is preserved. Public publication was explicitly authorized by the user; the proposal's historical publication-blocker notes are superseded by that permission.

## Baseline reconciliation

All 44 proposal-reviewed files were physically rehashed and unchanged before implementation. implementation-baseline.json captures 544 selected source/test/build/configuration files before repairs. This inventory is an exact local baseline, not a blanket staging list. Pre-existing substantive differences comprise 287 deploy/scripts/tests paths; each included dependency must be justified by the repair or subsequent preparation stage. Generated attempt receipts, private capability files, editor metadata and other OpenSpec changes were excluded from copying.

The selected runtime was committed as `067fa429ab05d0ede56807af0c65e383ca9f5088` (`chore: reconcile required benchmark runtime baseline`; 243 files changed). Staging used LF identity (`stage-reviewed-runtime-baseline.py`) rather than wholesale dirty-tree copies. A later independent review of that commit against `review-context.json` and the original dirty root `E:/STUDY/VAST` found:

- 44/44 inspected review files still match the original dirty runtime;
- 24/44 still match the current worktree (the other 20 were later repair/docs edits in this same branch);
- 494 copied baseline paths; wheels, GUI, and unrelated helpers were recorded as not copied;
- 55 commit-vs-source hash differences are CRLF-only after LF normalization;
- remaining content differences vs the live dirty main checkout are later main-tree drift and must not be restaged now, because that would undo the accepted ext4-suite source bytes.

reviewed-runtime-reconciliation.json and reviewed-runtime-reconciliation.lf-check.json are the reviewed diff. Unrelated untracked configs, receipts and editor metadata remain excluded.

## Initial environment observation

WSL Ubuntu runs as UID 1000 on kernel 6.6.87.2-microsoft-standard-WSL2. Observed memory total 25,196,371,968 bytes; available 23,709,769,728 bytes. Docker server 29.7.2 with overlayfs. GPU NVIDIA GeForce RTX 3060, driver 610.47, 12,288 MiB. Available storage at this observation: WSL root 932,565,581,824 bytes, Windows C: 328,115,585,024 bytes, E: 377,864,859,648 bytes. No matching active publication/guardian/test/Q4 processes or loaded vast user units were returned by initial ownership inspection. These observations are not final preflight or a dated remote-capacity guarantee.

Frozen Python: /home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python. pytest is absent; standard-library unittest is available and used without installing dependencies.

## Guardian regression

The new sealed wrong-content regression failed against the original implementation: requests_started was 0, expected 1. After extracting bridge metadata/binding validation and retaining bounded first-failure diagnostics, the 48-test guardian suite passed under WSL (5.418 seconds). Cases cover both protocol modes, malformed IDs/routes/bindings, missing/extra/unsealed/wrong-size descriptors, bounded diagnostics, descriptor cleanup, first-failure concurrency and diagnostic-write failure. Existing successful lifecycle/stop and custody regressions also passed. Further independent review, combined regressions, exact-byte final suite and physical image/qualification evidence remain outstanding.

## 2026-09-25 scope decision

The Sep24 qualification failure exposed a native defect outside the repairs named in design.md: the checkpoint reset check read GstAppSrc's `guint64` `current-level-buffers` property into a `guint`. On 2026-09-25 the operator was offered either revising and re-reviewing the planning commit, or treating the repair as within the approved preparation scope. The operator chose the latter, as with the Sep23 native-probe predicates and Sep24 registry refresh. This record is that decision, not reviewer approval of new requirements. The repair is limited to a type-matched read and its regression. It does not change the benchmark matrix, estimands, thresholds or acceptance rules.

## 2026-09-25 second scope decision

After the Sep25 pilot failed at cell 17 on a 512-task container ceiling and a decode-stage artifact label resolved as a GStreamer factory, the operator again chose to treat the repairs as within the approved preparation scope, with nonpromoting OpenVINO GVA and GStreamer Custom pre-check replays before the next 32-cell attempt. The ceiling change is a container safety limit (4096, as already used by Savant), not a change to CPU, memory, the matrix, estimands or acceptance rules.

## 2026-09-25 spec revision required

Nonpromoting pre-checks found three further OpenVINO GVA / GStreamer Custom qualification integration defects (identifier minimum length, CPU policy identity scheme, GStreamer Custom container-engine pin). Because the identity scheme needs a design decision, the operator chose to revise and re-review the planning artifacts with `openspec-update-change` before any further production-code change. Implementation is paused until that revision is approved.

## 2026-09-26 revision approval

The revised planning commit `16b5fefe793590eec2dcc8c601fe2d909e3440c3` (requirement "Native-probe qualification path is integrated before qualification", design decision 8, tasks 10.1-10.7) was approved on PR #2 at https://github.com/lordcoudy/VAST/pull/2#issuecomment-5844363496 (2026-09-26T07:45:54Z), after which implementation was requested with `/opsx:apply`. The approval does not select the design alternative, so decision 8's recommended option (manifest-injected CPU/GPU identities) is implemented.

## 2026-09-26 execution-deadline decision

The native probe used the policy deadline as the analytics worker execution deadline, so a single late frame aborted a qualification cell through the fail-closed guardian. The operator chose to align OpenVINO GVA and GStreamer Custom with the DeepStream adapter: worker requests carry the same 300-second transport bound, and policy-deadline misses remain measured outcomes. This does not change the deadlines, policies, estimands or acceptance rules.

## 2026-09-27 native drop failure and delegated planning review

Fresh guardian invocation `c69470b3e9df4167af8b2d12b58166d7` attested eight workers. The runtime-input materialization service exited 0, and an independent audit verified 32 bundles and four assets. OpenVINO GVA CPU pre-check invocation `05c7c45af2b7422f8285ecbdaf221fd8` failed at engine call 5: the 180-second native measurement returned 1 after 215.203 seconds, with captured stderr SHA-256 `b67d213279c55f332920733d8d0a4a2263d4b9c326bf57554c551872e75ac99b` and the message `native policy publication cannot bind a pre-detector/drop terminal as execution`. The log does not identify which of the two native queues emitted the drop. The guardian exited 78 with a connection-reset ProtocolError and `failed_stop_nonpublication` lifecycle, then retired its socket and workers. An authenticated stop request was no longer possible because the owner process had already exited. No later pre-check or qualification cell was launched for this chain.

The operator then instructed: “Work fully autonomously with openspec. Review, approve and apply all by yourself. Continue work.” This supersedes the earlier request for confirmation of each planning edit. Proposal, delta spec, design and tasks were revised and self-reviewed at exact planning commit `280059541853ad0ef0ed9601b65f44f229799e89`, pushed to the same branch and Draft PR #2. Strict OpenSpec validation passed. GitHub COMMENT review `5329408254` is anchored to that commit and records the operator-delegated self-approval; it is explicitly not an independent GitHub APPROVE review. The PR remains Draft. Implementation may proceed under this delegated decision, while CI, accepted runtime evidence, archive and final merge gates remain outstanding.

The renewed native and publication source invalidates the previous 20260927 image, parity and final-suite receipts. Tasks 5.2-5.4 are reopened until replacement evidence is verified. A fresh 20260927b host clearance at 2026-09-27T07:59:50Z passed: Windows commit headroom beyond possible WSL growth was 29,043,167,232 bytes, and C:, E: and WSL ext4 all exceeded the 20-GiB reserve. This is a point-in-time observation, not qualification acceptance; clearance must be checked again before the long live chain.
