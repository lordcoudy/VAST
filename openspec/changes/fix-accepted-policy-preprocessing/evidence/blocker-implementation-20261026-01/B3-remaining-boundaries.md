# Independent remaining-boundary audit, before physical admission

This is the original audit. Some duplicate consumer/assertion/companion reads
have since been bounded; see B3-reader-checkpoint.md for exact scoped evidence.
The other listed boundaries remain open; no complete B3/peak claim is implied.
The duplicate journal header/cleanup slice is now addressed separately in
B3-journal-checkpoint.md; this retained original audit is not rewritten as a
claim that the enclosing I/O, replay or whole-chain gates have passed.
Seven fixed-role artifact reads are separately bounded in
B3-artifact-reads-checkpoint.md; their byte ceilings do not close the retained
audit's conditional metadata heap, captured engine, finalization or caller work.
The captured-engine read/pin slice is now addressed in B3-engine-pin-checkpoint.md;
its enclosing caller/outer cleanup/timing and actual execution gates remain open.
Finalization CSV/hash/candidate encoding bounds are now separately addressed in
B3-finalizer-bounds-checkpoint.md; candidate persistence/enclosing clocks and all
other unclosed audit terms remain open.
The complete consumer now validates its existing reader clock before its own
materialization; see B3-consumer-clock-checkpoint.md. The literal producer and
enclosing-call clock/admission/persistence work remain unclosed.
The positive literal producer now requires and forwards its existing authorities
and clocks; see B3-execution-arguments-checkpoint.md. Owned child capture,
enclosing clocks and persistence remain open. Mixed-cohort capacity
must use B3-cohort-geometry-correction.md, including five ancillary985 operations.
Negative-29 now requires the same arguments, validates clocks early and forwards
compiler authorities; see B3-refusal-arguments-checkpoint.md. The fixed refusal
recipe is preserved; owned children, enclosing clocks and persistence remain open.
Outer preparation socket ownership and initiating/distinct-close preservation
are separately addressed in B3-preparation-cleanup-checkpoint.md. Per-socket
closure facts and inner accept/restoration cleanup remain unqualified.
Complete reply-map and unique-alias preflight is separately addressed in
B3-reply-preflight-checkpoint.md. Literal reads and pre-parse/whole heap remain
open; B3-literal-child-capture-findings.md records the concrete nested Git/proof
requirements. B4-retained-input-capacity-findings.md records the missing build
state and sharing evidence without admitting the 96 GiB volume.

Independent provider/source review inspected the unchanged enclosing fixture
callers at2fcb1478514d5fe90e916c60706484fdac6a8d41 while the fixed sidecar
slice was being implemented. The findings below retain that historical audit;
the checkpoint pointers above identify subsequently closed slices and residuals.
They do not claim acceptance, allocation permission or production-reader changes.
No tests/workloads/services/Git subprocesses/APIs or edits were run by that audit.

Historical findings at 2fcb1478514d5fe90e916c60706484fdac6a8d41 follow.
Use existing PhysicalRootCustodyV1 bounded reads/hashes where applicable; do not
introduce a general loader or change the standalone program. Original distinctions:

- guardian_journal header: read<=65537B; require<=65536B and terminating LF
  before JSON. Companion metadata is1MiB;256MiB is its eight-route lifetime
  group, not its own file limit. Individual routes remain64MiB.
- Consumer/assertion descriptors should hash without whole-file capture.
  Decision JSONL legitimately reaches64MiB; ingress uses its selected CSV cap.
- Physical captured native ELF is16MiB, not the portable compiler's1MiB.
  Original-operation documents are1MiB, source-plan/calibration assets16MiB,
  native payload64MiB and runtime-input receipt64MiB. Existing read_bytes
  precedes later checks and must be bounded before allocation.
- Finalization currently performs352whole-file hash reads (32cells x11files),
  including policy CSV/decision JSONL with64MiB limits. Stream by role. Admit
  frames/ingress file+row bounds before pandas reads. Fixed candidate shape
  (11SHA entries,6stream counts, identities/status) supports prospective8KiB.
- The literal producer caller's three Git forms require existing owned capture
  and inherited time bounds. HEAD expects41stdout bytes; clean status expects
  empty stdout but still needs bounded diagnostic capture; old pinned source
  needs its separately admitted1MiB stdout. Inspection/probe maps need complete
  nested/file bounds before setup; entrypoint source hash already has a2MiB role.
- Failure reporting currently formats unbounded exception/traceback text before
  its report guard and can mask the primary on report failure. Preserve bounded
  causes, attributable prefixes/unknown remainder and reader/persistence/cleanup
  facts. _fresh_json still needs inherited-clock, fsync and distinct I/O outcomes.
- Lifecycle fixture JSON has a1MiB existing reader role and still needs bounded
  construction/persistence. This does not replace the later reviewed atomic
  lifecycle publication repair.
- Literal positive caller still omits compiler admissions/deadline and standalone
  reader deadline; reader clock validation arrives after major materialization.
  Validate admitted clocks before allocation and forward original authorities,
  with no fresh-default windows. The current literal script is not executable
  admission authority.

Additional already-derived shapes/copies that the whole ledger must include:

- Four native payload copies per operation: producer, scratch coordinator,
  scratch ELF output, final operational output. Thirty-seven transfers add
  74intent/receipt documents<=8KiB each (606208B); the child also holds one full
  <=64MiB payload in RAM. Promotion's256MiB operation cap excludes later sidecars.
- Operational binding:187descriptors (37x5 plus capture plan and companion),
  existing1MiB writer limit. Process custody has32calls,64KiB launches/receipts,
  4KiB terminals and8MiB/channel; container custody has8commands,16KiB raw
  command outputs and128KiB facts. Failed channels/publication tails remain.
- Coverage4integers,32calibration coordinates/32capability bindings,37native
  descriptors,32finalized cells,2stock comparisons and21coverage-predicate
  mutations. The latter are separate from sealed20/42 refusal cohorts.
- Provenance list<=524545compact bytes (256x2048records plus list syntax).
  Four lists in final producer report total<=2098180B before other fields;
  three phase files retain three more lists. All five producer paths (three
  phases, stage and failure) remain charged; stage/failure can coexist.
- Prospective fixture receipt8KiB, calibration32KiB and capability256KiB need
  complete copied implementation/emitter/runtime-identity admission first.
  Production cold readers keep their64MiB guards. The fixture8/16MiB report
  guards are ceilings, not full field-fit or peak proof.

Protected predecessor readers include custody-checked reads to EOF without their
own byte cap. Bounding a duplicate fixture JSON read does not bound those later
reads: seal/fund their exact selected inputs/schemas/copies/memory before entry.
Complete B3/task1.5 and compiler/reader/whole-chain admissions remain OPEN.
