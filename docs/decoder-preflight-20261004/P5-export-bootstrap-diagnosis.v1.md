# S4 compact-result exporter bootstrap race — read-only findings

**Verdict:** demonstrated source ordering defect consistent with the authentic hosted failure; smallest proposed correction belongs to P5 planning first. Corrected V6 cold remains unexecuted/blocked by current CI. No tests, producer, cold, engine, code, CI or spec edits occurred in this review.

Source commit: `11471c5e13787dd7eac710738cd67472dc60b591`. Relevant full raw source pins:
- `scripts/full_publication_results.py`: 23051 B, SHA256 `dde01c5bb9e88e036e0dc9de11f233efd6504b46c99dae4df53a3fa9ef98c8ca`; managed physical == fresh raw S4 Git blob.
- `tests/test_full_publication_results.py`: 14223 B, SHA256 `680235b031de3e2e0b4116111863ec1e9a0ed9440dfb74d6734ebfaac76f2ab7`; managed physical == fresh raw S4 Git blob.
- `scripts/publication_physical_io_v1.py`: 132238 B, SHA256 `bc8a28239d86f1913a66757a497d9d5398dd1b17757c6f17725ae72bc01961ed`; managed physical == fresh raw S4 Git blob.

Original ZIP: `/mnt/e/STUDY/VAST/tmp/decoder-preflight-v6-20261004/ci-S411471c5e-v1/original-retention-v1/artifact-11314041069.original.zip`; 2224182 B, SHA256 `f325b3e1784375176fb496ea38ea5a1e970567cc227f66ba214c79d33a16e13f`. Narrow actual-member review only: `report.json` 1861001 B / `7299e9fcaa8bb7ca860139e76906d4b5d574de8ba9724a638c60e70b54e13105` and `unittest-child.report.json` 1789869 B / `5e8a3152bbcff6be8efada7ba2f4be78f0d7583b7c0affe38604a7369d0e3614` contain the same single error for `test_full_publication_results.FullPublicationResultsTests.test_concurrent_exact_exporters_serialize_and_adopt_one_bundle`. Full provider/CI acceptance belongs to the separate original-artifact peer.

## Causal ordering and proven limits

1. `tests/test_full_publication_results.py:201–210` genuinely submits two exact exports of the same finalized run. The test has no deterministic interleaving control; one hosted scheduling window exposed the defect.
2. `scripts/full_publication_results.py:473–478` opens physical run-root custody and calls `ensure_directory_owned(_INTENT_ROOT)` **before** publishing/adopting the lock leaf at481 and acquiring `_exclusive_bundle_lock` at489. Thus bootstrap is outside the bundle mutex.
3. `scripts/publication_physical_io_v1.py:2912–2924` opens the run-root and intent-root directory FDs, captures their epochs at2918, verifies the chain, and then compares epochs at2920. `_require_epochs:397–406` deliberately rejects any observed namespace-clock mutation; this guard is behaving as designed.
4. A second cooperative exporter can pass its own bootstrap and then create `.publication-atomic-staging-v1`, the lock/intent, or results while the first exporter still holds the pre-lock epoch snapshot. Those permitted writes change a checked directory's size/link/mutation clocks and cause the first exporter to refuse before its own bundle lock. The actual trace proves the failed check, not which exact inode/field/syscall changed: none is reconstructed or claimed as directly observed.
5. This distinction is already explicit in `_open_atomic_staging_lock_posix:1659–1663`: converge on the held directory inode and serialize before inspecting mutable staging epochs. `_directory_epoch:210` intentionally includes mutation clocks. The exporter violates the ordering, rather than revealing a reason to weaken physical IO.

## Narrow proposed correction (not implementation approval)

Change only `scripts/full_publication_results.py` and `tests/test_full_publication_results.py`. On production POSIX, serialize all cooperating exporters on the already-existing, held run-root directory inode **before** intent-directory/bootstrap mutation, and hold this coordination through the entire current bundle mutation/final-verification region. A private directory-FD `flock` can do this without first creating another lock file or namespace. Open with directory/no-follow/close-on-exec, join named/held identity before and after acquisition, keep custody's ancestor checks, and close/unlock independently. Retain existing persistent `.bundle.lock` and its payload/adoption/identity checks unless the planning author explicitly proposes and reviews a smaller equivalent migration.

The order must be existing root coordination → current bundle lock → per-operation atomic staging lock. Do **not** hold `_open_atomic_staging_lock_posix` over the entire export: each `commit_or_adopt_exact_identity` takes that staging lock itself; a separately opened outer acquisition can self-deadlock. A process-local `threading.Lock/RLock` alone does not meet interprocess serialization. Releasing root coordination immediately after lock-file bootstrap is also insufficient: a blocked peer could run its strict bootstrap while the first exporter publishes intent/output and mutate the same root epochs again.

Keep current Windows fallback behavior; do not silently remove supported platform behavior to satisfy the Linux failure. A bounded POSIX-specific ordering regression may state its actual platform prerequisite, but existing portable tests/skip policy must not be relaxed. No change to `publication_physical_io_v1.py`, producer/V6 observer, schemas, finalized evidence, per-file no-clobber checks, epochs, links, permission checks, receipt-last order, CI selection, retry or capacities is needed for this correction.

## Deterministic genuine regression design

Keep the current concurrent test and all its original assertions. Add a two-exporter real-temporary-directory ordering case with events/barriers and unchanged real IO:

- Pause exporter A immediately before its first real `_require_epochs` check labelled `compact result intent root`, after the expected directory epochs have been captured. Delegate to the original check after release.
- Start exporter B only after A is parked. A test-only wrapper around **real** `fcntl.flock` signals immediately before B's first actual `LOCK_EX` call and then delegates unchanged; it never simulates a granted lock. That signal releases A. Bound all event waits/futures and release barriers in `finally`.
- On the old source, B reaches its first atomic-staging flock only after genuinely creating the staging root. A's real check then rejects its stale epoch: deterministic RED at the actual original boundary.
- On the corrected source, B's first flock is the existing run-root coordination and it blocks before bootstrap changes. A's original epoch check and export finish; B then adopts the exact same bundle. Assert both real futures succeed, equal bundles, exactly the four expected result files, one exact intent/manifest and unchanged payload bytes. Keep existing foreign-final rejection and crash-window receipt-last tests intact.

Do not precreate mutable staging/intent/lock namespaces in the fixture merely to hide the race; do not patch filesystem epochs, bypass guards, use sleeps/statistical retry, or convert real exceptions into success. The new coordination's held-name/root-rebinding rejection should have a genuine negative check if that guard is newly introduced; an unrelated mutation must still fail closed.

## Custody and disposition

Seven relevant original/source leaves were read with regular-file/no-follow/single-link holds, full raw SHA and named/FD seven-epoch before/after equality; all FDs closed. Own FD count `6→6`. Read-only native Git cat-file children returned0/reaped. Elapsed 0.040851s. No own later-process/global-quiescence claim is made here.

The original S4 hosted CI error, original four-run S3 producer completion, and original FAILED cold namespace refusal remain separate immutable facts. This source diagnosis does not accept S4 CI, corrected cold,128 AU/64pairs or any scientific conclusion, and authorizes no retry. Exact P5 planning review/comment precedes any proposed code/test correction.
