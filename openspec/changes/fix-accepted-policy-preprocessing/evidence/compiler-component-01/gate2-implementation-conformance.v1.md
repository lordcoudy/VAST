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
   raw native/RPC/child files, its private24KiB receipt and a small later index.
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
