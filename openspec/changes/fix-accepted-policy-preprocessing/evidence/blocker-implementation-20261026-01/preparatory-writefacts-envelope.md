# Composed sidecar write facts — Grok finding reproduction/correction

Configured Grok reviewed7f243fb0 in session01a17a23-89fc-7282-b568-cf620956851c.
Initial3turn result was incomplete; same-session final opinion REQUEST CHANGES:
owner write/flush/close handlers overwrite the sink's exact submitted-prefix
facts with unknown extent. Existing sink-only cases do not prove composed
behavior. Independent primary review agrees and acknowledges the missed owner
overwrite. Preserve the original31-pass outcome, source and Grok refusal; they
do not establish this missing behavior or physical approval.

This correction follows existing D16 fact rules, not a design relaxation.
accepted_text_bytes remains the exact sum of interpreted stream.write returns.
Only a stream.write raise/unusable return marks unknown submitted extent; short
returns and refusals before forwarding stay known. Flush/fsync/close have their
own persistence flags and must not synthesize write uncertainty. Never clear an
unknown flag already established by a stream write. Retain original primary and
distinct secondary failures. No production/program/reader/scientific change.

New test5777B/SHA256
a4b2eb3fde66073e93ec9990702612ec68b961a0c66441641489daa1160e3a74
selects5methods in writefacts-red-01, on unchanged Native31082B/5c216...:
six expected failures (short return with/without close fault; pre-forward
overflow/non-ASCII; flush failure with/without close fault) and two passing
control methods (write raises after a known prefix; four unusable write returns).
All paths traverse the owner and sink. Fake streams store<=4KiB text, open and
fsync are doubled, no real file/FD/root exists. The new source is copied before
RED. Actual six failures must be independently accepted before correction.

Then remove only the owner assignments that coarsen sink facts. Correct the one
old expectation claiming unknown for a to_csv failure that submits no bytes;
preserve its original source/outcome. The two new controls still require unknown
on actual stream failures, preventing a blanket weakening. After source review,
writefacts-green-01 runs36methods (5new+15sidecars+2edges+6bindings+8quantity),
with the revised old-test hash authenticated at admission. Both new names are
fresh; no consumed name or old result is rerun/relabelled.

Separate32MiB tranche assigns8MiB source/Git including index+lock,8MiB channels/
copies,4MiB reviews/copies,4MiB combined ZIP+manifest/copies,2MiB results/
admissions and2MiB outer metadata:28MiB. Cumulative1456MiB1526726656B and
derived C69.943359375GiB fit C80GiB above40GiB floor. E65GiB/full64GiB
pagefile and cumulative192MiB source/Git cap remain. Retain all failures. No
payload/CI artifact/extra tree/repack/cleanup credit or retry is funded.

Runner12386B/SHA256
907158bbf86fd34e50963e02bcbe005995a719959a20d8ea6c153ed8062bfaba
adds only literal5RED/36GREEN phases with fresh direct-C output/TMPDIR,
300s total including5/5/5cleanup and unchanged D16 channel1MiB/result32KiB/
status2KiB/persistence/one-use limits. Exact runner SHA/size, closed roster and
capacity review precede fresh Windows/Linux physical/source admission for EACH.
Renew C>=128849018880B/E>=70866960384B/ext4>=2147483648B,<=4096units,
mount/UUID/boot,<=24GiB memory/exact6GiB swap,.wslconfig21B/SHA,E-only64GiB
pagefile,C-USN32MiB/8MiB and inactive E-USN. Unknown/forced/overflow/incomplete
closure or persistence holds further work. These tests grant no genuine payload,
reader/compiler/Docker authority or full B3/task1.5 acceptance;46/24 stays.
