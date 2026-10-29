# Producer report persistence on the inherited absolute clock

The positive producer's _fresh_json now requires an explicit positive integer
absolute_deadline_ns. It checks expiry before encoding and before opening any
output, preserves the complete bounded ASCII JSON/native final newline, and
reuses unchanged _write_result_v2. Success requires attempted writing, exact
known byte extent, fsync, close, no persistence causes and a final clock check.
It returns the original facts object. Its private refusal preserves that same
object and copies ordered causes without mutation, appending a distinct
post-return deadline cause when needed. All three positive and three negative
report call sites pass the existing reader absolute clock, without renewal.

Positive producer17003 B, SHA256
27df471bb0765c36dfcae99bde130410b2a4dea653066b08c393f6e271183288.
Negative producer13773 B, SHA256
fcb0764f0a14665a80d5c49315f96778144cf8c942049567d43c981635cbfd89.
New tests9285 B, SHA256
95da18b8bdf0d780a39d4d8fdd26686701750dac76921676b7685bbd54e41e80.
Legacy report tests7780 B, SHA256
978da2544c6459d396b063d3dc368157dfee5c386d1c7ca2328831e4abdcf7f6:
only time import and explicit controlled deadlines at two calls changed;
assertions remain. Runner19830 B, SHA256
b5f8c52352d756d7c83776469fde1e6a5559f31a4d9df7f01c1b3078e3f28a30.
The report encoder, D16 writer/owner and frozen compiler remain unchanged.

Actual once-only RED:7 methods/19 intended failures, no errors/skips,0.156 s.
The missing-clock case reaches the old unclocked text writer; both main callers
omit the inherited report clock. Other new-interface cases fail assertions on
the unsupported keyword/facts rather than erroring. Result2195 B, SHA256
c84cb5408e3897a6676a7e99af0254bacc80fbfb3fbe543bda2535b7659f00da.
Independent /root/provider_route_review cleared the exact recipe, then current
implementation/RED before GREEN. Fresh Linux provenance and Windows guards
preceded each once-only launch; the unresolved template is not executable
admission. Template plus two launch commands total52637 B raw/61440 B rounded,
within64 KiB aggregate and32 KiB individual limits.

Actual GREEN:28 methods/49 cases passed, no errors/skips,0.344 s. It selects the
new7/19, existing8 writer methods/11 cases, positive argument8/11 and negative5/8.
The new tests and argument cases double I/O. The legacy writer cases create
eleven temporary roots and one tiny real report, preserving byte equivalence
and exercising the unchanged writer; they are not real consumer execution.
Result2388 B, SHA256
ae822893163d4a153126bcf06321d8bcc33362ea17d325d02b298c3cfd153b26.
Returned raw/result facts and separately retained outer returns show normal
owned-child closure, both EOFs and completed write/fsync/close, with no overflow,
forcing, unknown remainder or deadline breach. Both stdout files are empty.

The33-member NoCompression ZIP365268 B, SHA256
98760846a55a02469f398758864e6f8b6b63a8fa5099432acdeed73b9d6848ca,
binds all originals, which remain. Ten source copies total130312/132249 B raw
and151552/155648 B rounded for RED/GREEN, within64 KiB individual/256 KiB
aggregate guards. Combined archive/manifest/copies allowance is6 MiB. Closed
forms total25.8125 MiB; conservative reservation30.5625 MiB fits31 MiB assigned
within the32 MiB pair. Case filesystem1 MiB and command64 KiB caps are explicit.
Cumulative direct allowance1936 MiB=2030043136 B; C70.412109375 GiB<80 above
40 GiB floor, E65 GiB/full64 GiB pagefile and192 MiB source/Git reserve remain.
Both namespaces are consumed. Exact-commit review, configured Grok and new CI
are pending at this checkpoint.

Caller test coverage includes positive initial-phase/failure and negative
failure/raw-after forwarding. Later success phases/final reports are source-
review coverage only. Parent error masking, str/traceback construction, failure
fact transport, Git/raw-proof capture, full heap/capacity and actual compiler/
reader/runtime/genuine/final gates remain open. No task1.5/B3/B4 acceptance follows.

Independent working source/outcome/archive/checkpoint review by
/root/provider_route_review is CLEAR. All33 stored members, CRCs, hashes and
originals match; the legacy scope was independently observed as eleven roots
and one132-byte report. This verdict does not replace exact-commit/Grok/CI gates.

Exact-commit follow-up: /root/provider_route_review returned CLEAR for
30ef6372397476b83f62b8b29bc983008ce56b72, including both producers, tests,
runner, all33 archive members and checkpoint scope. Configured Grok completed
normally with CLEAR for that same commit: actual modelUsage grok-4.6-build,
one turn, exit0,116.941 s. It reviewed supplied source; it did not rerun tests,
hashes, CRCs, CI or physical qualification. The four-member review-originals
ZIP is76215 B, SHA256
d00b85f54cfd6e2572b6afd67b8423a80569554074878219012b41d05e2b4523.
Prompt, raw stdout/stderr and the actual stored outer completion are preserved.
The last phrase in Grok's text about S96/images is scoped here: S96 fit is OPEN,
all227 images remain protected, and D27/Native57 remains parked.

GitHub Actions VAST CPU checks40462783038 completed SUCCESS at exact30ef.
This completes the review/check conditions for delegated AGENT source-stage
approval of this slice only. It closes no task1.5, B3/B4, compiler/reader/runtime,
genuine-consumer, conformance, archive or merge gate.

PR9comment6436235576 records that narrow delegated AGENT approval. Independent
/root/capacity_review verified all four ZIP members, CRCs, hashes and preserved
originals:75467 B originals,77081 B archive/manifest,229629 B including the one
funded Git archive/manifest copy. The final outer-tool wall_time is return latency,
not Grok's duration. Fresh Windows/Linux guards and the exact-head CI connector
observation are retained in B3-report-persistence-review-completion.original.json;
they permit only this small retention within the existing16 MiB metadata tranche.

CI provenance qualification: the retained connector response identifies the run
and SUCCESS but does not itself include a head SHA. The30ef association comes
from the actual fetch_commit_workflow_runs query for that exact SHA, retained in
the tool-call history; the wrapper's authored source_commit field alone is not
an additional service assertion. No historical query or response is reconstructed.
