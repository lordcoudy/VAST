# Gate-2 implementation conformance: controlled evidence and physical hold

Scope: task2.10's approved V8 continuation in PR9, change
`fix-accepted-policy-preprocessing`. This is a component implementation report;
it does not complete task2.10, whole1.5, genuine consumers, package renewal,
whole-change conformance, archive, Q1 or merge.

Planning approval is PR9comment6215421351, reviewing exact commit
`93bb04b647a9015f47ad3743551cb416b1695376` after separate CLEAR /
CLEAR_WITH_NOTES reviews and required CI38895458000 SUCCESS. That approval
preceded these source/test edits and authorizes implementation and controlled
tests. Implemented-source review/CI and actual evidence approval are distinct.

## Requirement and scenario mapping

1. **N3 effective configuration.** The shared compiler constructs only the
   three requested labels, refuses collisions with the provider's23 labels,
   and requires the exact effective26-label union. Only a present empty
   `Config.Volumes` may normalize null/empty-object. Every other requested
   Config/HostConfig field, including `CapAdd=[]`, retains exact comparison.
   Owner/config tests cover missing/extra/changed labels, collisions, missing
   Volumes and independent requested HostConfig mutations. These are controlled
   effective-inspect cases; fresh Docker behavior is not yet qualified.

2. **Unchanged ordinary transport contract.** Private reply-cap/decoder hooks
   preserve default strict JSON/status behavior, including the old null200
   result. Archive-specific caps apply before Content-Length/chunk bodies are
   accumulated. Transport tests cover unchanged null/status/JSON behavior,
   oversized length/chunks, EOF, persistence and closure failures. The ordinary
   owner's256KiB metadata ceiling remains unchanged.

3. **Finite F2 recovery.** The recovery helper exposes only the fixed19 GETs:
   initial/final version/info/stopped-B1 inspect and the13 approved archive
   paths. It enforces the original90s/5s deadlines, raw/decoded/derived/physical
   caps, socket epoch and source/provider bindings, exact Go PathStat semantics,
   one regular tar member, size/ELF/script/package checks and no extracted copy.
   Recovery tests exercise all19 requests with controlled sockets, framing,
   tar/path/stat/content/identity drift, deadline, actual measured growth and
   persistence faults. `validate_supplement_v1` rereads originals without RPCs.
   Package metadata and libc banners remain labelled; B1's empty direct cc1
   version is unavailable. No physical archive request has run.

4. **External C/D authority.** The C module authenticates retained B originals,
   a corrected no-self B2 index, F2 supplement/index/accounting, all five proof
   envelopes, fixed seed/source/helper bytes and exported Git-blob identities.
   The expected packet SHA and reviewed commit come from outside the packet.
   Tests refuse self-authority, changed helpers/seed/proofs and incomplete stage
   chains. Actual packet generation and external evidence approval remain
   pending; a syntactically valid review string does not authorize execution.

5. **Fresh P0.** Grok CLI implements the fixed three-command Windows root
   collector and controlled negative tests. Integration adds strict snapshot
   JSON and the pure original validator, exact eight-file inventory and actual
   block/inode/copy accounting. Native provenance, exclusive raw originals,
   exact argv/environment and one30s/max10s deadline remain mandatory, including
   native validation/factory/event-loop startup and final close. Oversized
   completion metadata refuses before opening. Injected controlled effects
   cannot launch or qualify a physical proof. The file validator grants no
   physical acceptance and cannot infer its own completion's historical
   persistence; actual successful native invocation/status/EOF and the returned
   completed write proof require external review. No native P0 ran in tests.

6. **C1-C6 outcomes.** The fixed C runner preserves full returned owner facts,
   raw HTTP/header/member originals and independent post-inspect/wait replies.
   Its pure evaluator compares the declared source/limits/status/ordered causes,
   EOF/hash/persistence/native-closure and no-promotion facts for all six stages,
   including both C4/C5 descendant schedules and C6's sole first-ELF-write fault.
   A completion footer does not prove its own successful close or final checks.
   Each next C stage, and D, requires exact external completion-authority
   descriptors for every prior stage, bound to an enclosing invocation record
   produced after the actual successful call. The fixed completion helper uses
   the original150s deadline and already reserved tail; its record cannot
   approve itself. Independent review of actual invocation status/EOF and
   completed enclosing persistence supplies the authoritative descriptor.
   C tests include a complete six-stage fake-owner replay, late/partial footer
   and enclosing writes, missing/wrong completion authority, altered facts and
   forbidden repeats. Publisher tests exercise the actual C4/C5 reporting logic
   under controlled schedules. No C container has been created.

7. **C3/C5 attribution limits.** C3 compares fresh kernel originals and the
   expected assembler SIGXFSZ/driver1 evidence. This is operational attribution;
   it does not directly sample an assembler PID in the container cgroup. C5's
   exact45s cutoff is code-derived and checked against actual enclosing elapsed
   time. Controlled tests cannot supply physical signal/timing evidence; the
   eventual raw physical run requires its own independent disposition.

8. **D custody, child and closure.** D accepts only C1's retained ELF after all
   six C results and their external completion authorities validate. It makes an exclusive0700 bounded/hash/ABI-checked
   copy, uses the fixed environment/command/reply/state and obtains a measured
   child pre-exec proof for UID/GID1000, CORE1/1 and FSIZE1048576/1048576.
   The original10s budget includes preparation,7s work boundary, TERM/KILL/final
   phases, capture, closure and receipt. Tests cover actual child-supervisor
   logic through controlled effects, malformed proof, owned identity, raw wait
   core bit,4KiB shared channels, all phases, prefix/close faults, operator stop,
   exclusive custody and post-run packet/ELF/raw-original drift. Full successful
   child facts survive combined enclosing receipt fsync/close failure. Blocking
   kernel/native calls are trusted boundaries; a late return cannot pass and
   no hard kernel preemption is claimed. No retained ELF has been executed.

9. **Inclusive controls and ledger.** C controls stay inside each64MiB C
   allocation. D reserves prospective rounded controls before each operation:
   both192KiB kernel captures, bounded crash listings,96KiB remaining controls,
   raw native/RPC/child files, its private20KiB receipt,16KiB enclosing
   capture/copy liability and a separate4352B later ext4 index.
   The later index allowance includes its inode; it never authorizes a duplicate
   full receipt. D controls remain<=512KiB and its aggregate<=2MiB. Tests use
   native-shaped maximum metadata, short/unknown writes, post-receipt metrics,
   operation accounting, idle-period separation, floors and reserve exhaustion. The512MiB global seal and
   original physical floor remain hard limits. Historical B/code/F2/export/
   interstage/final forms must all be charged, with host noise included.

## Current physical decision

`gate2-readiness-01.v1.json` binds the authenticated B3 endpoint to a fresh
read-only readiness observation. C: free bytes changed from104354775040 to
100952293376 during idle planning. The author initially treated3402481664B as
a charge against the512MiB seal. Independent requirements review rejected that
added continuous-accounting rule: V7 measures C: decrease **over each run**;
V8 carries the fixed approved B charge and adds finite F2/export/D intervals.
The accepted B1-to-B2 idle drop1926148096B corroborates this interpretation.
The original mistaken HOLD and its correction are both preserved.

Start each new operation's measurement before its first allocation and finish
after owned work, capture, persistence and the accounting tail. Carry all old
charges and outstanding component liabilities forward; an idle-period label
cannot conceal component writes. Charge host noise inside each operation and
enforce fresh floors/readiness outside it. Current observed free space exceeds
the unchanged43620761600B floor. This correction does not expand the seal,
reset the charged ledger or authorize cleanup/storage/image changes. Physical
execution still awaits implemented-source review/CI/approval and actual packet
approval; no F2/P0/C/D action has begun.

All failed roots, stopped B containers and original manifests remain retained.
The227 protected images are untouched. Task2.10 remains unchecked, and the
whole change retains24 completed tasks out of46.

## Verification and review boundary

Unique RED/GREEN originals are retained in `gate2-implementation-tests/`;
historical failed harness invocations are preserved alongside successful tests.
`gate2-implementation-advisory-01.v1.json` records precommit BLOCK findings
and their dispositions separately from formal exact-commit approval. Final
controlled discovery passes363 tests with zero failures/errors/skips under
canonical WSL Python3.12.3 (`gate2-integrated-02.original.txt`). All25 compiler
fixture/test Python files parse using Python3.10 grammar
(`gate2-syntax-02.original.txt`). Strict OpenSpec validation passed
(`gate2-openspec-01.original.txt`); existing long-requirement INFO messages
are retained, with no validation errors. The final C/P0/D/export compatibility
slice passes127 tests; independent focused C review resolved both completion
and post-denial-writing P1 findings. The final scalar guard also refuses
boolean/integer schema confusion. The source/log identities and commands are
bound in `gate2-implementation-verification.v1.json`.

Formal whole implemented-commit independent review, required hosted CI and
delegated AGENT approval are still pending at this precommit snapshot. Their
exact commit/verdict/run/disposition will be recorded externally in PR9 before
physical use; this report does not approve its own future source commit.

There is no dedicated CI behavioral-conformance gate. The configured CPU/host
checks and this report do not replace physical observations or independent
evidence review. No successful physical qualification or whole-change archive
is claimed by controlled tests or document validation.

## Subsequent operator implementation gate

Core implementation commit `e16273e4a3f450fd16c6d2079b22c05de389eb10`
received two independent source CLEAR_WITH_NOTES verdicts, recorded in
PR9comment6217523594. Grok's initial BLOCK on a closed-F2/idle/packet interval
remains preserved; its re-review accepts only one finite contiguous setup
operation, with actual measurement before first allocation through completed
packet and capture persistence. This is an operational boundary, not a source
fix or authority from caller-supplied measurements. Core363-test evidence above
precedes the operator integration and is not its final verification.

The setup/capture command candidates grew into substantive implementation:
deadline admission, native process capture, source custody, ledger and acceptance
decisions. Independent review requires these helpers in this same PR with
meaningful controlled tests and exact-commit review/CI. A Temp path and a
reviewed SHA alone cannot replace those gates. No candidate was executed.

Tracked operator helpers and controlled tests are being integrated. They must
share one original150s setup window; retain the original F2/P0 windows; enforce
fresh floors and post-observation deadline admission; authenticate both helper
sources and the ten exported runtime files against the externally approved
commit; preserve native status/EOF/completed writes; and carry every source,
candidate, capture, metadata and copy form within existing allocations. Runtime
CODE_PATHS, actors, literal root commands, caps and C/D predicates remain fixed.
The external packet review must bind actual before/end observations and the
funded closing tail. Pending operator tests/review/CI prohibit physical use.

Independent accounting review distinguishes actual runtime forms from retained
development history. The initial conservative operator quote unnecessarily made
superseded Temp candidates runtime proof inputs. Four actual draft files are
retired, never executed or rewritten, and inventoried separately for whole1.5;
no fifth duplicate is needed. Runtime authority comes from the new reviewed Git
bytes and external approval. Removing draft reads corrects that interpretation
without removing history or granting an allocation credit.

Both deployed operator working sources and their new Git forms require a finite
component quote; equal content does not remove a distinct retained allocation.
Neither the old B-code reservation nor the fresh export/P0 reservation is spare
operator space. F2 originals, derived records and their retained/report/Git copies
remain within the unchanged8MiB aggregate and512MiB seal. Its512KiB outside
subreserve is an implementation choice, not permission to omit forms or expand
the aggregate.

Historical controlled-test/CI logs and source-test/development Git forms are
retained inputs to whole1.5 and fresh physical floors. They are not retroactively
charged to F2 simply because they belong to this change. Their retention and
whole-chain capacity remain incomplete; this distinction grants no cleanup or
whole1.5 acceptance. Before physical use, actual bounded operator/F2 forms and
all outstanding copy/control liabilities must fit the implemented reservation.

## Operator integration verification

The tracked setup and capture helpers are frozen for exact-commit review.
They retain the ten-file runtime export and use an externally supplied reviewed
commit and PR approval. Both helpers authenticate their actual source bytes
against that commit's Git blobs before allocation or native work. Canonical
WSL controlled discovery passes433 tests with zero failures/errors/skips
(`operator-integrated-01.original.txt`). Python3.10 grammar checks pass for
all30 compiler fixture/test files and11 embedded operator code strings
(`operator-syntax-01.original.txt`). Strict OpenSpec validation passes all6items;
existing long-requirement INFO messages remain. The original validation log is
intact; its enclosing Windows display command encountered a cp1251 Unicode
encoding error after the validator had already returned0. No validation rerun
is used to overwrite that original or invent a successful wrapper exit. The
subsequent validation after report updates passes with the UTF8 wrapper too
(`setup-openspec-02.original.txt`, validator/enclosing status0).

- **Deadline and native admission:** controlled late boot/statvfs/source reads,
  imports and persistence prevent later dispatch. The same original150s Windows
  and conservative Linux deadlines cover export, F2, native P0, packet and final
  capture. F2/P0 retain their90s/30s limits and fixed commands. Full setup and
  capture orchestration tests exercise actual phase bodies with only external
  effects controlled; no native component runs in these tests.
- **Authority:** the packet binds the actual operator authority record's hash.
  The capture meter independently reads and authenticates that record and its
  helper/context/commit/approval bindings. Cross-helper tests mutate these
  bindings rather than substituting an independently invented success schema.
- **Accounting:** actual source working/Git forms, bounded auxiliary originals,
  derived F2 copies and a prospective64KiB enclosing capture reserve fit the
  existing512KiB outside allowance or refuse before dependent work. The actual
  normal status and one permitted copy remain within32KiB. A failed driver can
  retain12KiB stdout and32KiB stderr, plus Windows metadata, within the funded
  failure reserve; it creates no status/copy or later meter. Tests exercise
  full combined prefixes, larger physical allocation, copy overflow and floors.
- **Failure evidence:** bounded diagnostics preserve ordered causes and actual
  status/EOF/write/closure facts. Larger facts retain byte counts, hashes and
  exact finite prefixes with explicit incompleteness. Native Git failure facts
  survive refusal. Raw F2/P0 originals and their limits are unchanged.
- **Core record writers:** actual BufferedWriter/RawIO partial-write faults
  reproduced false known-extent reporting in C/F2 JSON and shared request/reply
  originals. Four opens now use unbuffered I/O, so an unreturned partial write
  sets the existing unknown-extent flag. Four new regression tests and109tests
  across the affected writer/transport/C/F2 slice pass. RED originals, including
  the initial missing-import harness error, remain preserved.

Independent advisory review of frozen affected bytes finds no remaining
confirmed P1. This does not replace the upcoming exact-commit reviews or CI.
The earlier e162 reviews remain historical; the new writer defect was discovered
after them and prohibits using that old verdict for physical execution.

Hosted run38911635009 for e162 ended with CPU failure. GitHub's retained
annotation says "The hosted runner lost communication with the server."
The underlying cause is unverified; no CPU test/build result or successful check
is inferred. CPU logs were unavailable through the API, and no CPU artifact was
published. The successful host job's original ZIP and API receipts are retained
in `hosted-ci-e162-38911635009-01/`; the ZIP matches GitHub's advertised digest.
No job was restarted. Required checks on the new implemented commit remain
mandatory before delegated AGENT approval and any physical operation.

`gate2-operator-verification.v1.json` records the historical c67 source/log identities and
the verification boundary without overwriting the historical363-test manifest.
All physical evidence review, external native-return authority and task2.10
acceptance remain pending. Whole1.5 and the change's22 remaining tasks are not
closed by these controlled checks.

## Subsequent C/D invocation and allocation correction

Commit `c67b25cd4e87499dc9575ed4e58c5159ac9abf18` received independent
CLEAR_WITH_NOTES source reviews from the separate Codex reviewer and Grok CLI
reviewer session `01a144ff-9c02-7803-b3ee-2b6862245be7`. Their verdicts are
historical: subsequent preparation found that D's4352B ext4 index reservation
did not fund an additional enclosing Windows capture and its permitted copy.
No physical work preceded this discovery. The existing required CI run for c67
continues without cancellation/restart; its result cannot approve later bytes.

The correction reserves16384B for one bounded external capture and one copy,
separately from the4352B ext4 index. Both liabilities are added after the maximum
of retained allocation, C-free decrease and ext4-used growth; host noise or a
previous tail cannot swallow a future form. D reserves each observation before
its allocation, and the full remaining child/after-guard/receipt/index/capture
suffix before both ELF copy and child execution. Budget/floor denial prohibits
fresh receipt writes; retained originals and bounded returned facts survive.
The unchanged96KiB other-control,512KiB control,2MiB aggregate and512MiB global
limits remain binding. Flat `before.`/`after.` filenames save two directories;
the private receipt bound decreases from24KiB to20KiB without discarding facts.
Independent requirements review classifies this as faithful implementation,
with no requirements amendment or cap increase.

The controlled fixture uses the actual C guard producer with only external
process/pipe/time effects replaced, the actual three-row transport epoch shape
and the95-character native root. Its receipt is16444B with a pre-encoding JSON
bound19833B<=20480B. The previous whitespace-filled GPU boundary now refuses
before copy/exec when the full suffix cannot fit; its earlier successful test
remains historical. No arbitrary future whitespace or native outcome is added
to the acceptance predicates.

Fixed C/D command-line entrypoints accept only an externally reviewed40hex
commit, positive bounded packet size, approved64hex packet hash and ordered
prior completion size/hash pairs. They derive the sole fixed export and prior
record paths internally. Isolated Python `-I -S -B` validates the exact script
path before project imports. Bootstrap/import errors use bounded refusal output;
no user argument selects a program or arbitrary path. Pure startup/import and
argument validation precede the existing physical API clock: C's150s starts
before its first measurement/allocation, D's10s starts before chain validation
and its first measurement/allocation. These clocks never reset for completion
or output. Actual enclosing process status/EOF remains external evidence.

C immediately calls its existing completion helper after a successful run,
under that original deadline. A failed run never creates a completion. D emits
only its final receipt identity, post-receipt measurements/ledger and evaluation;
it never duplicates the raw receipt. The single unbuffered stdout write records
known partial versus unknown unreturned extent; flush and original-deadline
checks remain mandatory. A bounded refusal projects actual nested wrapper
causes and known write/closure observations, plus full bounded-facts SHA/count,
a finite prefix and explicit unknown remainder. Independent advisory BLOCKs on
lost nested facts, unbounded import exceptions and fresh writes after budget
denial are retained and corrected before formal re-review.

The D summary and post-stdout refusal together measure926B in the controlled
producer original, which records an816B command and2602B selected frame. Quoting
the WSL executable adds two bytes, giving818B/2604B; this is a calculation from
that original, not a second producer measurement. Independent grammar bounds
keep the selected frame below3200B.
Before opening its retained form, UTF8 JSON plus newline must be<=4096B; each
form funds4096B data and4096B Windows metadata, including one equally bounded
copy in16384B. This is a bound on the selected frame, not arbitrary raw tool
JSON. The4334B generic quote-filled counterexample remains a negative test.
Only actually observed metadata may be recorded; no PID, separate stream EOF
or persistence flag may be invented from an absent tool field. Early launcher
errors require bounded observed prefixes/counts/hashes and explicit unknown
facts; truncation, unknown closure or incomplete persistence cannot pass.

Final controlled discovery passes468 tests with zero failures/errors/skips
under canonical WSL Python3.12.3 (`invocation-integrated-03.original.txt`). All31
fixture/test files and11 statically resolved embedded operator strings pass
Python3.10 grammar checks (`invocation-syntax-03.original.txt`). The separate
reviewer gives advisory CLEAR for C source79b55f9d and D source31c3a7c9 after
resolving the recorded BLOCKs; no reviewer ran a native action. Specific floor,
backing-stat and allocation/walk read errors are now sticky unknown-budget
refusals, including post-child failures; complete child facts remain retained.

Final controlled evidence and source identities are bound in
`gate2-invocation-verification.v1.json`. The earlier363/433-test manifests remain
unchanged historical snapshots. Exact final-commit independent reviews, required
CI and explicit delegated AGENT approval in PR9 still precede physical setup;
actual packet approval and per-stage native evidence reviews remain separate.
No F2/P0/C/D, prewarm, keepalive, image action, retry, Q1, archive or merge has run.

## Hosted runner identity in controlled D tests

Required c67 run38922339662 completed with an actual CPU test failure.
Its original artifact reports3874 tests,15 errors and88 existing skips. All15
errors are in controlled D OuterTests: the hosted suite runs as UID/GID1001,
while the fixture left the four OS identity getters unmocked. D correctly
refused `d_host_identity` before allocating facts; secondary NoneType errors
followed. All six CPU targets built, and the observer recorded actual rc1,
completed trace/control EOF and no forced TERM/KILL. This differs from e162's
earlier lost-communication failure. Neither failed run supplies CI acceptance.

The original3040372B CPU ZIP matches GitHub's SHA256
`5287934f939350cac17e06fc2cdca7a745c57522bc7ce48fd3f4105469bd820d`.
It and original run/job/annotation/artifact API responses are retained in
`hosted-ci-c67b-38922339662-01/`. Original job logs, including the first gh
escape-sequence refusal and later successful raw fetch, remain retained in the
recorded Temp directory; extracted test traces are preserved with that ZIP.
No check was cancelled or restarted. The already running4e1 check continues
naturally; only a successful check on the forthcoming test-fix commit can
satisfy its required gate.

The correction changes the controlled test helper only: it patches all four
identity getters to1000 inside the fake-observer/child/clock invocation. A new
ambient1001 case verifies both correct controlled behavior and restoration of
the enclosing identities. Four direct-entry negative cases still require each
wrong native identity to refuse before binding, measurement, D allocation,
copy or child work. Production C/D source, native UID/GID1000, original clocks,
commands, packet/export inventory and every limit remain unchanged.

The D/child suite passes84 tests normally and84 with all four ambient IDs1001;
the original hosted-actor RED22 and GREEN23 are retained. Final focused
discovery passes470 tests with zero failures/errors/skips;31-file/11-embedded
Python3.10 grammar checks pass. Separate advisory review is CLEAR for the
test-only diff. `gate2-hosted-actor-verification.v1.json` binds the new evidence
and current sources without rewriting earlier historical manifests. Formal
exact-commit reviews, latest required CI and explicit delegated AGENT approval
remain mandatory before physical work; task2.10 remains unchecked.

Both independent source reviewers returned CLEAR_WITH_NOTES for exact4e1.
Grok's exported final-response section is retained separately; its full original
session export remains in Temp. The UID fixture note is addressed by this
test-only correction. Its two-byte frame-reporting note is clarified above;
the original2602B measurement remains unchanged. These historical source
verdicts do not approve the later test/evidence commit or its pending CI.


## One-successor implementation after planning commit8332

Planning commit8332ed4ef720bb76881ef4055a57c11f9b58a1d4 received separate
Codex and Grok CLI CLEAR_WITH_NOTES reviews, required successful run38943143205,
and explicit delegated AGENT approval in PR9 comment6222272081 before these
production/test edits. That approval permits implementation only. New exact
implemented-commit reviews, new required CI and explicit delegated AGENT
approval must precede the sole fresh successor. Its actual packet and each
later C completion require their separate evidence reviews/authorities.

The c75 setup remains FAILED after three identity GETs, before archives/P0/C/D.
Its original roots, streams, selected outer-tool frame and held tool transcript
remain retained. The original closing measurement/peak is UNAVAILABLE;618496B
is a partial charge. The absent6213B native stdout is not reconstructed. The
6651B held transcript retains its distinct tool-return provenance. The frozen
9637B plain JSON retention index and all previous verification manifests remain
unchanged. No additional old-failure copies are introduced.

For "Historical stopped-source empty DNS defaults have a different
representation", recovery permits only the three present sealed-null DNS
fields to remain null or become typed empty lists, under exact network mode
none. Tests replay the actual B1 raw inspect with the narrowly derived fresh
c75 HTTP framing/hash and complete all19 fixed GETs/13 members; the read-only
validator rereads actual originals. No normalized hash substitutes for a fresh
raw/selected hash. Package associations remain metadata, and B1's empty direct
cc1 version remains UNAVAILABLE.

For "DNS policy or fresh operation identity differs beyond the narrow
exception", missing/wrong-type/nonempty DNS, a different network mode, bool/int/
float changes to other selected values, malformed State and changed fresh
before/after identity refuse. Fresh identity hashes remain unnormalized.
Recovery/transport/package parsing and the existing owner/N3 policy retain
their original scopes; there is no general empty-value normalization.

For "A failed setup is offered for reuse or an unapproved successor", the
capture/setup fixed commit, exact Git/current helper bindings, original
deadline and fresh commit-derived root remain mandatory. Syntax is not
approval. The external operator must independently establish the exact PR
review/CI/AGENT approval before invocation, then independently approve the
actual packet before C1. Tests cover missing/changed bootstrap/context,
unreviewed helper bytes, late authentication and source denial before
allocation/dispatch. No test receipt establishes external approval or consumes
the one physical admission. A failed successor would consume it and prohibit
another attempt; this work grants no third setup, repeated B/C or fallback.

For "Successor admission must carry prior forms with an unavailable closing
meter", component_v1 owns the fixed combined8MiB/old384KiB/active7995392B,
private failed-owned2162688B and additive6291456B prior limits. Before capture
allocation, Windows authenticates the new component/index Git blobs and all13
old c75 Git variants. The ordinary native PRE meter runs the actual fixed
28-node retained verifier, known blocks, three Windows original forms and the
held transcript. The index supplies bindings, not paths for command dispatch
or historical checked flags as current proof. Descriptor-only observations
fit the unchanged context/meter/authority bounds; the index body is not copied
into those channels or exported as an eleventh source.

Setup binds the completed PRE observation into the actual enclosing authority.
C authenticates that authority, canonical typed context and prior observation,
actual helper bytes and the pinned index/mutable retained forms before packet
acceptance. Its helper descriptors match the actual setup authority's FOUR
fields, including exact fixed Windows paths; reads use fixed Linux paths.
Tests use setup.authority_record_v1 rather than a synthetic three-key authority,
and reject foreign/missing paths, float sizes and changed helper bytes. Linux C
inherits reviewed Windows Git provenance through the independently approved
packet; it does not claim a fresh Git-store query or continuous object presence.

Setup, POST and initial C packet checks add the6MiB carry AFTER the maximum of
new-operation physical growth/retained liabilities, once. Subsequent C/D inherit
that ledger. Old F2 proof is carried within the prior reserve, not charged again
as active F2. Controlled20MiB host growth with the old40MiB fixture funding now
refuses; positive tests retain growth larger than retained data. Exact boundary
and category tests prevent borrowing unused code allowance for old F2 proof.
The global inclusive512MiB seal, floors, six C allowances, D2MiB, raw6MiB,
13 member/TAR bounds and12MiB wire limit remain unchanged. The reviewed bridge
includes idle/unattributed fall and conservative future copy accounting; it
does not restore the missing old peak or guarantee background metadata growth.

The shared final-accounting footer cap is16384B. Its root, supplement descriptor,
13 accounting fields and baseline/last measurements have closed schemas and
strict integer bounds. Duplicate/noncanonical/extra/wrong-type fields refuse;
other controls retain262144B. The actual producer/reader/copy quotes preserve
the full failure liability following a partial footer, all rounding/metadata,
sticky unknown-budget refusal and the unchanged original deadlines. Tests
separate the934B maximal canonical footer shape from its conservative
pre-encoding bound, and retain partial-write/fsync/close/floor/deadline failures.

Bootstrap reads check kind/link/cap before nonblocking/no-follow open and bind
the opened FD and post-read epoch, including block extent. Both capture loaders
compile the already authenticated bounded component bytes, avoiding a second
source-path read. Controlled path-change/FIFO, byte-loader and typed PRE
observation regressions preserve their actual RED/GREEN originals. Selected
setup/capture allocation scans now enumerate incrementally with the existing
1024-node bound; oversized iterators and scan errors refuse. Trusted synchronous
OS calls remain non-preemptible, with original before/after deadline checks.

The complete controlled F2 producer exposed an outside-form capacity failure
before any physical attempt:19 RPCs/13 members/38 raw originals produced
29344B supplement,5194B index and741B footer, giving114688B for two permitted
control-copy forms. The then-current helper quote made the total531968B,
7680B above524288B. This failed observation is retained. Source-only removal
of redundant documentation/comments/blank lines reduces helper allocation
steps; executable AST equivalence and affected tests verify that compaction.
No form, metadata quote, guard or cap is removed to obtain admission.
The final verification manifest binds the actual final source geometry and
complete producer specimens. Controlled/native-projected metadata specimens
are capacity calculations, not native evidence or a universal sufficiency
guarantee; every actual outside copy/active F2/global/floor guard still binds.

The five earlier fixture-boundary scenarios retain their controlled coverage:
successful preparation uses the actual setup orchestration and authority
builder with only external effects controlled; compiler/publication failures
retain exact C mappings and original-write faults; startup/core enforcement
retains D/child and required native compiler checks; resource exhaustion retains
deadline/overflow/budget tests; component-only proof cannot acquire whole-chain
authority. Native gate2 qualification is still pending. These tests do not
substitute for actual F2/P0/C1-C6/D, whole1.5, genuine consumers or packaged-image
checks. No other repair requirement/scenario is closed by this increment.

gate2-f2-successor-verification.v1.json records final source/test/log bindings,
controlled regression/grammar/OpenSpec checks and capacity evidence. Earlier
RED/GREEN/failed CI/source reviews remain historical. Existing long-requirement
OpenSpec INFO diagnostics are retained without weakening requirements.
OpenSpec format checks are separate from behavior and independent review;
the repository still lacks a dedicated CI conformance gate. Task2.10 remains
unchecked, progress24/46. Archive, merge and Q1 remain unavailable until their
existing full repair gates succeed.


Independent review also found that the planned subtotal did not explicitly
assign the distinct NEW runtime10/plan Git variants and changed current working
forms. The correction spends524288B of the existing1085440B unallocated seal
headroom on a separate current-code-proof reserve. It charges FULL current
working plus FULL new Git forms for every changed fixed variant, even if an old
working form remains; no replacement/inode or early dedup credit is assumed.
Unchanged variants reuse only explicitly matching old size/SHA/Git identities.
The planned535785472B subtotal remains historical; the corrected prospective
subtotal is536309760B, leaving561152B under the SAME536870912B seal. The prior
6MiB and all named F2/outside/code-root/C/D/floor limits remain unchanged.

The shared fixed-eleven current_code_forms_quote_v1 API authenticates all ten
working code files plus the amended plan against exact three-field descriptors,
fresh hashes/Git-blob identities and known native allocation. Changed variants
receive both complete forms, with rounding and4096B metadata per form; unknown
native allocation or quote>524288 refuses. Setup observes all eleven actual
Windows Git blobs inside the original150s clock BEFORE export and enforces this
quote. C freshly authenticates working counterparts/allocation and inherits
Git provenance only through the independently approved actual packet. Its
packet binds the actual current-form quote as a strict integer. All three
setup/POST/C ledger paths add the FULL524288 once AFTER the new-operation
maximum, separately from the prior6MiB; a smaller actual quote gives no credit.
An exact implemented-commit Windows Git/working audit must also be recorded in
the PR before ANY prewarm/capture. Capture validates the prospective full
reserve before its first file write. No extra context payload or reset clock
is introduced. Independent review classified this as faithful completion of
the already-required all-forms accounting within unallocated headroom, with
no new requirements amendment or physical approval.

A real safe Windows Python3.14 source/index read exposed lstat/fstat ctime
incompatibility, which the Linux-only controls had missed. The original
observations showed equal device/inode/mode/link/size/mtime/birth identities,
but path ctime represented birth while FD ctime represented modification.
The [CPython issue](https://github.com/python/cpython/issues/157671) and
[Python os documentation](https://docs.python.org/3/library/os.html#os.stat_result.st_ctime_ns)
support the platform distinction. Windows cross-API identity uses portable
fields plus birthtime; full FD ctime before/after AND full path ctime before/
after remain checked. Linux ctime/block checks are preserved. Controlled
cross-API/drift negatives and actual Windows source/index/fixed-eleven reads
pass; these are file-reader checks, not a gate2 physical attempt.

The accepted-metadata adversarial Unicode specimen is explicitly NEGATIVE:
four512-character astral package Version values, escaped64-character mtime
and269-character banner produce55566B supplement/5194B index/742B footer and
163840B two-form copies. Even after helper compaction, its outside quote564736B
exceeds524288B by40448B. Actual runtime copy guards refuse such a result; no
universal metadata-fit or native package observation is claimed. The ordinary
and maximum ASCII specimens are narrower capacity calculations. Native package
metadata remains unobserved before the separately approved sole invocation,
and any actual overrun/unknown stops without a further attempt.


Final frozen-source verification passes541 compiler tests (zero failures,
errors or skips),32 fixture/test files and11 embedded Python3.10 grammar
checks, strict OpenSpec all6 and archived5 validation, and git diff --check.
These are controlled/source checks; required new implemented-commit CI and
both exact-commit reviews remain pending.

The safe actual Windows FileStandardInfo working-only audit completed in
tool chunk79ec24 with actual enclosing exit0, before any capture/prewarm.
GetFileInformationByHandleEx(FileStandardInfo=1) queried AllocationSize and
EndOfFile on each authenticated open FD before and after its bounded read,
with stable FD/path identity, known regular/single-link/non-delete facts and
all allocated bytes <= each selected rounded working quote. The fixed-eleven
source-rows digest is c5fb280a96b951e3c611d4e156f9594e69a09f18d756bb89695cdd8327b70181;
changed two-form code quote466944B leaves57344B in524288B. This working-only
observation makes NO new Git-commit observation. Before any physical allocation,
repeat the exact-commit Git/working/allocation audit and record actual status/
completed communication in the PR. The Windows component API fallback is only
a selected logical quote whose backing is established by this separate audit;
it cannot independently observe native allocation. Native C still checks
fresh blocks. This is point-in-time backing, not continuous custody.

Microsoft defines the queried
[FILE_STANDARD_INFO allocation field](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_standard_info)
and [GetFileInformationByHandleEx](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getfileinformationbyhandleex).
No monitor, new context payload, deadline extension, source-root allowance,
F2/outside cap or physical approval is introduced by this external prerequisite.
