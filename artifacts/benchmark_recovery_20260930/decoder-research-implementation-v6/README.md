# V6 decoder setup and unchanged research protocol

This copy implements OpenSpec change `fix-decoder-preflight`, reviewed planning commit
`3aa35c3b2eedc05d22cf16ba37d470143d080f6b` (P). V5 and original attempts remain
immutable. No actual metadata or research operation is authorized by this README or
by a successful CPU fixture suite.

Controller requires `--project-root`, `--review-repository-root`, exact lowercase
40-hex `--source-commit` (S), `--mode metadata-only|research` and a fresh
`--output-dir`. Guest requires the same explicit mode in its sealed plan and argv.
There is no default, resume or retry. P is fixed in V6 source; S must have separate
exact-source review and dispatch approval. Current checkout H may contain later task
progress/archive while S remains its ancestor and all three held runtime files match
raw S blobs. Native Linux Git uses its held executable and supported `-C` commands;
the controller saves four exact raw P blobs as exclusive `reviewed-*.md` leaves.
A fresh standard ext4 Git checkout avoids Windows managed-worktree Git path issues.
The physical root remains the original prerequisite/media checkout, separately bound
to its frozen ledger, source citations, custody helper and original media descriptors.

The shared fresh/cache mapped-input verifier keeps all visible named/held file and
ancestor guards. A distinct backing identity requires a short readonly mapping of the
held FD, an actual checked buffer range and strict backing/offset/permission joins.
Selected target-owner/library rows are bracketed while the owner is alive; the guest
probe owner is recorded separately for source-child rows. Only selected original maps
rows are retained. Full-view maps SHA is an original observation; unavailable
unselected bytes and mapped-memory integrity are not independently proved.

`metadata-only` performs packaged registry/GI/plugin/library preflight and creates no
original source, AUs, run directory or decoder pipeline. Its terminal is
`metadata-preflight-terminal.v1.json`, with result null, runs_completed0 and
research_complete false. `research` retains four32-AU operations in this exact order:
front_gate/default, front_gate/zero, underbody/zero, underbody/default. Source cadence,
transport600scale, cohorts and all byte/time limits remain unchanged. The existing
600s whole, shared120s prelaunch,120s run,45s startup,10s drain and15s cleanup clocks
are enforced; natural fast exit does not bypass the metadata body deadline.

A sealed terminal is provisional until its owner finally closes. Success additionally
requires actual post-close stdout and rc0, unchanged physical receipt size/SHA, exact
closed namespaces, no primary/close/late failure companions and the original positive
container terminal, owned removal and separate CID/name absence. Controller final close
has its own original post-close observation. CPU fixture results and external PID reap
facts do not prove Docker cleanup or research acceptance.

## CPU fixtures visible to repository CI

`tests/test_decoder_research_v6.py` runs one fresh CPython3.12.3 `-I -B` child. That
child discovers all six local test modules, including appended classes, and uses the
existing CI `RecordedResult` for individual started/terminal/outcome records. The
adapter freezes the original66 IDs from the initial-copy inventory, verifies all
origins and runtime modules, rejects partial/foreign/skipped inventories and checks
that source bytes stayed unchanged. Both original real15s controller-finalization
negatives execute. No parent import of generic research modules occurs.

Run the same discoverable adapter on the canonical interpreter:

```sh
RUNNER_TEMP=/path/to/fresh-native-ext4-fixture-root python -I -B tests/test_decoder_research_v6.py -v
```

Original stdout/stderr, child suite report and parent terminal remain under
`RUNNER_TEMP/vast-cpu-checks/decoder-v6-fixtures/attempt-<unique-id>/`. Each channel
is limited to1MiB; the child has120s and owned final close at most15s. The report lists
actual inherited66 plus every discovered new case; one root adapter case is not a
claim that the historical baseline CI already included those nested tests. Fixtures
use real temporary files, readonly mappings, Git repos/worktrees and tiny CPython
children with explicit synthetic engine/GI metadata; they launch no Docker, packaged
source, decoder, model or research operation. Hosted required CI must pass on final S.

Use native ext4 for the disposable Git and held-file fixtures as well as their
originals. The adapter deliberately sets its temporary fixture directory beneath
RUNNER_TEMP. DrVFS can reject renaming an open file and consume the fixed120s limit.
Root lifecycle regressions also verify partial acquisition, primary/cleanup errors
and actual after-persist/close clock observations. Adapter receipts remain
provisional; successful return requires completed bounded validation and retirement.

## Separate original dispatch and cold review

After exact S/observer/helper review, required CI and namespace/input prechecks, root
uses the separately frozen external helper below on canonical host CPython3.12.3.
`PHYS` is the frozen original physical root; `REVIEW` is the prepared standard ext4
Git checkout; `S` and `REVIEWED_HELPER_SHA` are the actual approved source identities,
not placeholders that confer authority. The helper is outside Git S and its full
reviewed SHA is required independently; no digest is invented here.

```sh
/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python -I -B /mnt/e/STUDY/VAST/tmp/decoder-preflight-v6-20261004/capture_original_v6.py --project-root "$PHYS" --review-repository-root "$REVIEW" --source-commit "$S" --mode metadata-only --capture-source-sha256 "$REVIEWED_HELPER_SHA"
```

One invocation consumes the exact P-prescribed metadata attempt/capture namespaces.
The external helper owns only its exact CPython child/group and original capture;
the controller owns Docker custody. A Git-tracked, separately reviewed
`artifacts/benchmark_recovery_20260930/decoder-independent-v6/cold_reader.py` then
checks the closed metadata evidence without importing producer/GI/model code.

```sh
/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python -I -B "$REVIEW/artifacts/benchmark_recovery_20260930/decoder-independent-v6/cold_reader.py" --project-root "$PHYS" --review-repository-root "$REVIEW" --planning-commit 3aa35c3b2eedc05d22cf16ba37d470143d080f6b --source-commit "$S" --mode metadata-only --attempt "$CLOSED_ATTEMPT" --external-terminal "$EXTERNAL_TERMINAL" --capture-source-sha256 "$REVIEWED_HELPER_SHA" --capture-tool-record "$ORIGINAL_TOOL_RECORD" --report "$NEW_EXCLUSIVE_REPORT"
```

The cold report is exclusive. The external terminal and original exec/write_stdin
tool record provide separate after-close facts; the external producer cannot attest
to its own final write using a recursive self hash. No current global absence is inferred.

Only accepted closed metadata preflight plus a separate exact research-dispatch review
permits one equivalent helper invocation with `--mode research`, on the same P/S
and the separate P-prescribed research/capture/cold namespaces. It has no automatic
transition after metadata success. Independent research replay must reconstruct all
128 AUs, ACK/control/causal gates, PTS/pixel/caps joins and fixed cohorts from original
closed evidence. A partial/failing operation retains its prefix and stops; missing
stages remain unexecuted. Metadata, research and cold checking stay nonpromoting:
no pipeline adoption, benchmark/native pair, qualification, model/parity or publication
acceptance, and no completion of the outstanding full32/Q4/5600 campaigns.
