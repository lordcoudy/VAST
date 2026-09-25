# Implementation evidence

Status: implementation in progress; preparation_ready=false, full_run_started=false, publication_ready=false. The Sep24 32-cell pilot failed at cell 17 on a native reset-check defect; after its repair, the image chain and a fresh qualification must be renewed; Q4 and full-run arms have not started. See implementation-validation.md for the current physical evidence.

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
