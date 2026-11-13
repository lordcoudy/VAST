# Proposed fixed producer failure-frame shape

This records the independent provider-route audit at d950/f35d and its concrete
corrections, before implementation. It is an implementation detail of approved B3;
full exact-source/test/capacity review is still required. No frame code, execution
or whole1.5 acceptance follows. The separate two-clock fix is not this full repair.

Remove general str(error), traceback.format_exc and full-assessment f-strings from
both producers AND consumer_fixture_v2's failed F1 assessor branch. Before the
unchanged exact short promoter-refusal comparison, require exact canonical
QualificationError, one exact builtin string argument and length no greater than
the existing exact expected message. Otherwise re-raise the original unexpected
error without formatting. Keep the actual assessment in fixed
private fixture state before refusal; the existing16MiB failure-report encoder/
writer can carry that actual object unchanged. The external frame reports its
availability, known passed status and the actual existing failure-report reference/
persistence. Encoding/write failure means not durably preserved, never success
inferred from a path. No new report file or generic reporter is required.

Use one thin CLI boundary after main/source cleanup: fixed bounded ASCII JSON plus
LF on inherited stderr, then integer nonzero exit. In-process main keeps raising
its original errors. Avoid implicit Python traceback/exception formatting at the
actual CLI boundary; preserve integer argparse exits deliberately, with no arbitrary
SystemExit data formatting. No new owner, worker, timer, retry or fresh deadline.
Broken/partial/overflowed transport remains nonzero/incomplete; no claimed delivery.

The optional private CLI-created state retains the actual source context before
its with block, actual report facts immediately when returned and the one actual
standalone-reader return. Source __exit__ returns False on ordinary body failures,
so walking exception chains alone cannot recover prior records. The consumer must
retain standalone facts immediately after its call, before identity/refusal checks
can raise. A producer-only first slice would have to label those facts unavailable.
Use fixed per-site records, not callbacks or a new event/logging system.

Closed recipe maxima: positive3 source slots,1 cold reader,6 report sites; negative
6 source slots,0 cold readers,3 report sites. Unused, not entered, returned and
unavailable are distinct. Source-result persistence belongs to source records;
it must not also count as a literal report site.

The independently derived EMISSION cap is485376B INCLUDING LF, encoded with
unchanged fixture_report_bytes_v1. The512KiB reporting band remains an outer
ceiling, with38912B reserved for other reporting diagnostics. Eventual runtime
admission must also price startup/argparse/cleanup/other stderr within the unchanged
1MiB outer capture; no such runtime admission follows here. Complete geometry:

- 22 unique file references x8192B =180224B.
- 6 D16 capture blocks x18432B =110592B.
- 6 source-slot blocks x2048B =12288B.
- 6 report-site blocks x2048B =12288B.
- 1 cold-reader summary x2048B =2048B.
- 64 error records x2048B =131072B.
- Fixed header/flags/LF4096B.
- Compiler cause-code/availability reserve16384B.
- One complete sidecar block16384B.

No larger frame may consume the38912B reporting margin. Error records contain only fixed kind/role codes, ordinal
primary/secondary/fact/reference links and availability flags. They MUST NOT embed
full .facts/.evidence. Each actual fact set projects ONCE in its fixed role block;
errors link to it. Otherwise the64x2KiB error reservation is invalid. Link/dedup by
object identity, never exception/class hashing. Cap owned structure at64 objects,
eight levels and eight secondary links per node; reject/mark incomplete on excess.

Recognize exact owned types by identity only: _FixtureProducerFailureV2,
LiteralSourceCaptureRefusedV2, _FixturePreparationCleanupErrorV2,
_FixtureCapturedEngineErrorV2, _FixtureJournalIoErrorV1,
FixtureReportPersistenceRefusedV2, StandaloneReaderRefusedV2,
_FixtureSidecarWriteErrorV2 and the separate terminal FixtureCompilerError case
described below. Resolve producer __main__/import identity correctly.
Unknown exceptions get a fixed opaque_exception code. Never traverse arbitrary
__cause__/__context__/args/notes/dictionaries or read custom __name__/str/repr.
Preserve actual primary/ordered identity-distinct secondary links for owned wrappers;
do not invent per-operation completion facts for cleanup wrappers that lack them.

D16 projection: five deadline integers, original PID/start ticks, returncode/signal,
forced/TERM/KILL flags and delivered counts, closure/subreaper/unknown flags, up to
64 recorded PID/start-tick pairs, both channels' observed/retained/discarded counts,
EOF/overflow/remainder flags, retained hashes and raw-file reference IDs. The D16
owned_descendants list is signalled-identity history, not a live-leftover list.
D16 capture causes have a separate64-entry/128checked-JSON-safe-ASCII-char allowance because
some existing codes append dynamic exception type names. JSON-safe means each
character is0x20..0x7E excluding quote0x22 and backslash0x5C; reject control/DEL,
non-ASCII, empty or oversized codes before encoding with explicit null/incomplete.
This alphabet applies to compiler and all other admitted non-whitelist cause codes;
ASCII alone does not bound escaping. Use signed64 scalars;
unknown/malformed/oversized data becomes null plus fixed refusal codes and explicit
facts_complete=false, not silent truncation or substituted successful values.

Persistence projects the actual six returned fields attempted, written_bytes,
write_extent_unknown, fsync_completed, close_completed and causes. A writer that
raises without returning facts is unavailable. D16 writer has maximum four concurrent
causes (write/short-write,fsync,close,final deadline); early deadline/open returns are
separate. Its seven fixed codes are at most24chars. Eight-entry headroom plus the
fixed report deadline/clock markers fits the2KiB report-site block.

Current source-slot cause count is at most two from five fixed literals. Use the
actual fixed source whitelist (each<64chars) and writer's short fixed vocabulary.
Do not allow two independent8x128char arrays in a2KiB source record; that geometry
does not fit. Complete source-result persistence is below512B. Slot data includes
used/returned/observed-clock-available flags, original observed return or unknown,
within-observation/result-complete flags and three references. Exclude command and
proof/channel payloads. Report sites include entered/returned, known encoded length,
actual persistence, post-write clock availability and reference, never a self-attest.

Header includes a fixed whitelist of at most32 projection-refusal codes, each at
most64 JSON-safe ASCII characters; header/flags/key syntax/codes/LF together<=4096B.
Compiler fact-kind is one fixed enum(absent,null,exact_dict,other), never __name__.
One GLOBAL compiler block and one GLOBAL sidecar block are allowed. Extra distinct
compiler/sidecar terminals link to unavailable with fixed refusal/incomplete state;
they never create more16KiB blocks. The reader summary and capture roster are also
global fixed-role blocks, not per-error copies.

File references use actual path, known hash/count/persistence and fixed role IDs.
Check exact path strings<=640codepoints before encoding; worst escaping7682B leaves
510B ALL non-path metadata/key syntax inside8192B; check each complete encoded
reference against8192B rather than assuming key overhead is free. Existing source paths are at most541filesystem bytes
(directory512+separator+filename28). Report/reader/sidecar paths need their own checked
admission; that bound is not established by their present callers.

Sidecar error is an actual omitted owned shape, not a generic .facts dictionary.
Its record has filename from12 fixed names(length<=64), admitted_upper_bytes and
accepted_text_bytes, seven Booleans(open_completed,serialization_completed,
flush_completed,fsync_completed,close_attempted,close_completed,write_extent_unknown)
and failure_stage(None,dataframe,open,write,flush,fsync,close). Require exact integers
0<=accepted_text_bytes<=admitted_upper_bytes<=that existing table ceiling(max64MiB).
accepted_text_bytes is text accepted by the stream, not confirmed on-disk bytes.
Retain failed facts plus up to11 preceding completed table facts at1KiB each inside
the16KiB sidecar block, and original primary/at-most-one close secondary. No hashes
or stronger persistence facts can be invented. Current exception lacks output-dir;
retain one checked actual directory at its existing catch, then combine with fixed
filenames. Until retained, location is unavailable. Sidecar failure precedes the
positive cold reader and cannot coexist with it. Negative can still finish six
source slots and failure/after-proof reports; its final success report cannot
coexist. Reserved22refs covers18source+3report+1sidecar conservatively.

Recognize only the exact frozen canonical FixtureCompilerError identity as a
terminal case, never as an aggregate wrapper. Its16KiB compiler block retains at
most64 exact JSON-safe ASCII cause codes of<=128chars and actual absent/present/type status
of its optional .facts. Do not inspect or copy any heterogeneous facts keys or
invent a result-file reference: compiler_facts_reference stays null until an actual
separately qualified reference exists. Missing/malformed/oversized causes mark
projection incomplete. Other compiler-like classes remain opaque. The frozen
compiler is unchanged; full compiler fact transport and actual heap/runtime
qualification remain a separate open source-backed audit. No new compiler state
sink is needed.

Meaningful future controls must expose old formatting callbacks, both clock losses,
disk-report failure with actual source/D16 facts, ordinary body error retaining prior
source records, post-reader consumer refusal, sidecar completed/failed records and
location, maximum geometry/refusal boundaries and CLI single-frame/nonzero exit
without implicit traceback. Preflight all controlled batch forms before execution.
This file is a proposed next-slice audit; no task or genuine gate is closed.
