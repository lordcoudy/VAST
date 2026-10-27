# Proposed fixed Git and stock-proof capture recipe

This refines the approved B3 capture work for the two literal producers. It is
not execution admission. Independently review the concrete policy before its
dependent implementation; runtime qualification, whole1.5 and required source
reviews/CI still precede any genuine invocation. No new owner, generic loader,
Git proxy, snapshot repository or CI-helper modification is proposed.

## Interface and custody

Add one explicit --source-capture-dir to both fixture-only CLIs. The operator
must precreate this separately admitted directory before launching the caller;
the flag grants no authority. It must be a physical canonical directory below
the same project root, outside the fresh fixture output, initially empty. Missing,
foreign, noncanonical or occupied destinations refuse before Git/capture writes.
Precheck the complete applicable fixed stdout/stderr/result path roster. Names
remain consumed after failure. Hold existing physical-I/O custody and verify the
namespace before/after each capture and publication, including completed-file
validation. The admitted trusted, quiescent source window explicitly includes
this capture directory: D16 uses absolute-path opens, so held/pre-post directory
checks do not make writes continuously anchored or prove race-proof custody.
Do not execute without that reviewed quiescence prerequisite. Do not rewrite .git,
change the parent environment or create a replacement source checkout.

Positive has three slots: HEAD, tracked status and the already-approved guardian
source. Negative has six: before HEAD/status/proof and after proof/HEAD/status.
Only the existing exact commands are permitted. Use the original reader clock
for every slot; no per-slot timeout/default window. Validate exact HEAD bytes,
empty tracked status and complete bounded guardian bytes. A slot is used once.

## Runtime and environment prerequisites

Qualify the actual parent launch before use, including credentials, its complete
environment, Python/stdlib/site/module closure, loader/libraries, absolute env,
prlimit and Git paths, configurations and effective limits. env -i on a child
does not authenticate the parent or env's loader. The proposed caller address-
space soft AND hard ceilings are12 GiB, imposed before Python startup and checked
as finite and at most12 GiB
in the caller. This is a candidate containment bound, not demonstrated consumer
fit; remaining phase/background memory belongs in whole1.5. Keep the D16 Linux/
pidfd, one-Python-thread and no-live-preexisting-child requirements.

Reuse unchanged _capture_owned_reader_v2. Its command is fixed env -i plus the
qualified prlimit, imposing1 GiB soft AND hard address-space ceilings before Git
or proof Python starts, inherited by nested Git. Price and qualify env/prlimit
startup under the parent ceiling before the child ceiling becomes active.
Qualify actual fit/enforcement first.
Use process-local PATH=/usr/bin:/bin and fixed locale, no site/user/cwd injection
for proof Python (-I -S -B), and exactly:
GIT_DIR=/mnt/e/STUDY/VAST/.git/worktrees/VAST8;
GIT_WORK_TREE=/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST.
Disable system/global configuration and optional index writes. Qualify/pin all
common/worktree/include/info-attribute/alternate/promisor/replacement contributors
and reject unreviewed helpers, filters, fsmonitor, trace or lookup behavior.
Apply fixed GIT_CONFIG_COUNT overrides to direct and nested Git: no maintenance/
GC, no fsmonitor/untracked cache/preload or hooks, one index/pack thread,1 MiB
packed window,64 MiB packed mapping cache and16 MiB delta-base cache. These are
selected-buffer limits, not total-heap/IO claims; the address cap is independent.
No pull/network/helper fallback or other Git operation is admitted.

## Input and stock-verifier bounds

Use exact-head CI inventory as external admission evidence. Current historical
sizing at34f is14147 paths/1755971 NUL-inclusive bytes, max344-byte path,
636568803 logical file bytes, largest21482466 B and1749 parent names. The same
CI JSON geometry is3400326 B, not a newly authenticated current inventory.
Refresh all bindings after source/HEAD/index/config/boot changes. Proposed limits:
16384 regular stage-zero entries;512-byte individual and2 MiB aggregate NUL-
inclusive paths;4 MiB inventory/index;32 MiB file;1 GiB total source files;
32768 parent names;32 path components. Independently qualify physical source
custody or explicitly review/enforce the quiescent trusted-source window.
Cached Git index sizes do not supply physical file bounds.

The proof remains the stock ci.tracked_paths + ci.verify_committed_bytes, freshly
imported from the same five114679-B repository scripts. The fixed proof program
checks the live path/type/stat/aggregate bounds before the verifier's hashing
loop and passes the same derived observe_end_ns through its existing keyword.
It checks expiry before calling each stock helper. The1 GiB kernel limit is
already active before imports and either stock command's buffers allocate.
No subprocess monkeypatch, alternate verifier or proof substitution is allowed.

For SHA1 the quoted path limit implies at most2965504 B ls-tree output; actual
34f geometry is2505762 B. This exceeds one D16 channel. Do not print the inventory
through that channel or accept a retained prefix. The proof prints only its
existing three fields after successful verification. Validate exact keys/types,
true verification, count and exact verifier origin after normal closure, with
an8 KiB proof-JSON parsing ceiling and empty successful stderr. Retain originals
by reference; no second full proof dump. Quantify hashing/import/pack/decompression
IO and simultaneous memory separately during actual runtime admission.

## Deadline, persistence and failure semantics

Reject expiry before any outer slot starts. A stock helper has internal fixed
timeouts and does not check the passed deadline before every nested Git spawn.
This policy does not claim that stronger guarantee. D16 owns and bounds the
entire proof, and any return at/after the inherited observe_end_ns, or any forced/
unknown/overflow/nonzero result, refuses. Result persistence remains inside the
original absolute end, with no renewed observation window. If a
stronger nested pre-spawn rule is required, review that change before code;
passing the existing keyword alone cannot establish it.

Reuse _bounded_json_v2/_write_result_v2 for each complete capture result under
the original absolute end. Save owner facts before protocol validation, preserving
raw prefixes, original status, EOF, ownership and first/distinct secondary causes.
Result persistence facts remain external to the saved result. Require normal
closure, both complete EOFs and write/fsync/close; a partial file never passes.
Do not reuse guardian-specific _reader_error_v2 for Git. Preserve existing
successful producer/proof data and defaults. Fix the negative finally's masking
and prevent expired after-proof/head/status launches; retain initiating errors
and distinct cleanup/reporting errors. Parent str/traceback preallocation and
failure-fact transport remain separate B3 obligations, not silently waived.

## Physical forms and validation

D16 remains1 MiB/channel and2 MiB/result. Positive reserves6 MiB raw plus6 MiB
results; negative12 MiB raw plus12 MiB results, before namespace, final report,
outer channels, originals/ZIP/Git and failure-copy tails. Actual cohort schedule
must multiply these forms explicitly in whole1.5. No new allocation is released
by this proposed recipe or prior portable success.

Meaningful RED/GREEN must cover both literal callers, missing destination/runtime/
clock before writes, complete fixed roster/collision refusal, original clock and
environment/limits, late/nonzero/signal/overflow/truncated/unknown ownership or
EOF, result IO failure, exact HEAD/status/source/proof validation and preserved
primary/secondary errors. Use fixed controlled children only after a separately
reviewed finite case recipe; actual Git/runtime qualification follows exact-source
independent/configured-Grok review and required CI. No genuine cohort, model,
provider or Docker command is included in portable capture tests.

Independent /root/provider_route_review at product30ef found this fixed approach
within approved B3, with no formal amendment needed. It required the explicit
trusted/quiescent directory wording above; pre/post checks alone supply no
continuous anchoring. Its reviewed original was7660 B, SHA256
d2b48eafc6dbba342c18f9d5c4ba9060c2df2affae76ee90a17f364746433966.
The proposed runtime limits/inventory remain prerequisites rather than fit or
execution acceptance. No stronger check before every nested stock Git spawn is
required by B3/D16; the disclosed stock-helper limitation remains exact.
