# Proposed private producer failure-state boundary

Read with B3-producer-failure-frame-shape.proposed.md. This is the concrete next
implementation contract for independent review before code/tests; the485376B
diagnostic is not a qualification proof or a new execution authority. No new
process owner, loader, reporter, service, worker or deadline is introduced.

Keep the fixed codec and thin CLI wrapper in build_production_fixture_v2.py,
already imported by the negative producer. This keeps both producer-owned error
classes in the actual helper globals when positive runs as __main__ or negative
imports it. Other owned types come only from their fixed, already loaded canonical
fixture modules; compare exact type identities. Do not import a second positive
module to classify its __main__ errors, or hash arbitrary classes/errors.

main gains only an optional private keyword-only _failure_state=None. Normal
in-process main() calls retain their argument/call shapes and original raised
objects. The actual CLI alone creates a fixed-recipe state and supplies it. Both
__main__ tails become integer SystemExit of the same private CLI wrapper; the
wrapper invokes the actual main, catches after complete unwinding, emits at most
one frame, then returns an integer status. Preserve ordinary success and known
origin-established integer argparse exits; arbitrary body SystemExit(0) is still
a nonzero opaque failure. Establish origin with the actual CLI-only parser exit
hook retaining the exact exception identity/status, never infer it from integer
code alone. The CLI parser error hook emits no arbitrary error text; fixed help
output remains bounded and default in-process parser behavior remains unchanged.
Unknown SystemExit objects never reach implicit formatting.
Use one bounded unbuffered stderr write and check its returned count; no retry
after a partial frame. Full encoding happens before the first stderr write;
an encoding/projection failure may select one fixed small incomplete frame instead.
An external-write failure cannot prove delivery and must keep nonzero status.

State is plain private data, never a callback or authority input. Its fixed fields:

- recipe: positive/negative constant, never an arbitrary label.
- source_context: actual fixed source-capture object saved BEFORE entering its
  with block, even if __enter__/body/__exit__ fails. No reconstructed records.
- reports: fixed positive six slots (phase00,phase01,phase02,phase03,stage,failure)
  or negative three slots (after-proof,failure,final). Unused slots stay explicitly
  unused; record site entry, encoding length/hash when known, writer entry/return,
  exact returned persistence and clock observation availability immediately.
- assessment: actual F1 object saved immediately before its refusal check; known
  passed status only when exact builtins permit it. The existing failure report
  carries the actual object unchanged through its preflighted16MiB encoder.
- cold_reader: actual returned standalone evidence assigned immediately after the
  existing call in complete_fixture_production_consumers_v2, before subsequent
  identity-policy/refusal checks. Also retain its actual supplied output directory
  before the call: the frozen owner omits result_path from its return. The fixed
  intended result filename may be joined to that direct argument only, explicitly
  labelled an intended target, never evidence that the writer entered/completed.
  No reader/_PROGRAM/owner change or unrelated-path reconstruction.

_fresh_json adds optional private state/site keywords. Existing default call/return
behavior remains. Every CLI report site supplies a fixed slot; unknown/reused slots
refuse before encoding/writing. Record actual facts before any post-write clock or
validation. A writer that raises has returned=false and facts unavailable, never
invented six-field facts. Source-result persistence is NOT a literal report slot.
Do not count phase entry as writer entry. Clock unavailable is distinct from late.

Pass state only when supplied into the two existing _run helpers and the complete
consumer; default in-process calls receive no extra forwarded keyword. The consumer
adds only an optional private state keyword. Its failed-assessment error becomes
constant text, with the actual assessment retained in state and on the newly created
owned refusal object for in-process inspection; avoid formatting the object. The
negative assessor branch uses the same retention-before-check rule. The known short
scientific promoter-refusal string comparison stays byte-for-byte unchanged AFTER
a pre-format guard: exact canonical QualificationError, exact tuple args of length1,
one exact builtin str and length<=the existing exact expected-message length.
Unexpected type/args/length reraises the original error without formatting. Tests
must cover hostile subclasses, argument objects and oversized strings.

The native sidecar owner already catches its exact write error and attaches the
current completed dictionary. Attach the actual output directory at that SAME catch;
retain original files/facts/error objects and add no I/O. The codec reads the new
directory only on that exact owned type. Current completed is a dictionary of at
most11 preceding fixed filename-to-fact records, not an arbitrary event list.

Failure-report construction uses fixed error/role/status data instead of general
str/repr/traceback. Keep the original error first and any distinct report failure
second via the existing aggregation. The CLI-created state survives both that
failure and source-context cleanup. A post-main frame includes the actual final
ordered errors and source records. It excludes complete report/proof/command text.
The disk failure report contains a bounded pre-report error summary, not a final
self-attesting CLI frame: it cannot claim its own future writer facts or source
cleanup/checks that have not happened. Those actual returned facts belong only to
the later state/external frame. Store no report payload inside its own site record.

The frame has a fixed version/kind, recipe, non-authority flags, completeness and
bounded projection-refusal codes, plus files/captures/source_slots/report_sites/
reader/sidecar/errors blocks. Per-block maxima and485376B complete geometry are in
the shape audit. Actual emitted frame including LF<=485376B; the38912B reporting
margin inside512KiB is not available to a bigger frame. Header/refusal codes stay
within4096B, at most32 fixed codes<=64 JSON-safe chars; compiler fact-kind is a
fixed enum. All checked cause alphabets exclude quote/backslash/control/DEL, not
merely non-ASCII. Each whole encoded file reference includes all key syntax under
8192B, with non-path metadata<=510B. Error records are links only. Facts project once per actual fixed
role; malformed/foreign/overflowed fields become explicit null/unknown plus fixed
codes and incomplete status. Unknown errors never expose their names/args/notes/
causes/dictionaries. Identity dedup uses builtin id or is, not user hashing/equality.
The sole compiler exception is exact frozen FixtureCompilerError, a terminal case
with its separately reserved16KiB short-code/availability block. Inspect only its
owned .causes and optional facts availability/type; keep heterogeneous facts
unprojected and their unqualified reference null. It has no aggregate links or
new state sink. The frozen compiler and full compiler transport gate stay intact.
Compiler and sidecar blocks are GLOBAL singletons; additional distinct terminal
objects are explicitly unavailable/incomplete, never additional per-error blocks.

Do not overstate hash/extent meaning: D16 retained-byte hash is not proof of a
completed disk file when its raw writer failed. A source/report intended-result
hash/count describes encoded bytes, with actual persistence stored separately.
Use distinct fixed field names or links for intended/retained data and confirmed
persistence. File-reference metadata stays within its510B allowance; cause arrays
live in their owner block, not repeated in every file/error reference.

Before execution prepare a separately priced finite RED/GREEN recipe with actual
source/test/command/parent/retention/copy maxima. RED must expose existing arbitrary
formatting, source-record/report fact loss and CLI implicit formatting through
controlled effects; missing new API checks alone are insufficient. GREEN covers
both actual main paths, the consumer post-reader/assessment seams, sidecar directory/
completed facts, unknown/malformed/maximum frame boundaries and nonzero single-frame
CLI exit. Preserve all existing scientific assertions and unchanged owner/compiler
source. Independent exact review/configuredGrok/new-head CI/delegated approval follow.

This proposal does not close heterogeneous compiler fact transport, actual frame/
environment/heap fit, whole1.5 or real controller/runtime/genuine/final acceptance.
