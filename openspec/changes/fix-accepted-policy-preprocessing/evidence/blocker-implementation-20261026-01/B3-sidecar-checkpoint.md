# Fixed twelve-table bounds and persistence

NativeV2 now admits run64/arm68 safe-ASCII names before mkdir. The original
twelve CSV names/columns/rows remain. Each table has a literal maximum row count,
encoded row/file cap, supported scalar kinds and complete ASCII/CSV upper-bound
check before any output DataFrame. All twelve preflights precede the first
sidecar open. Integers and finite floats reserve32characters to cover pandas
dtype coercion; strings are <=4096ASCII, with doubled quotes, delimiters and
CRLF charged. None/missing/extra-key behavior matches the original DataFrame.

One original DataFrame/to_csv formatter feeds a private forwarding sink, which
checks actual ASCII bytes against the admitted total before each write. UTF-8,
strict errors and newline="" preserve existing pandas bytes. Exclusive opens
refuse collisions. The owner preserves serialization/accepted-text/flush/fsync/
close/unknown-extent facts and the original primary plus distinct close errors.
Successful twelve-file facts remain in metadata; earlier completed facts remain
on a failed owner. Accepted text counts do not by themselves prove persistence.

Original RED ran once on Native3a66...:15methods,45intended failures and one
valid run/arm control,0.127s,no errors/skips. Two actual old-writer cases reached
serialization tripwires;41explicit missing-API assertions do not qualify I/O.
The original13424B test was saved before execution. Independent source/capacity
reviews accepted the exact recipe and actual failure shapes.

Independent implementation review rejected uncorrected Native31029B/55fe...
before GREEN for two P2 findings: construction could bypass owner/prior facts;
close could duplicate the identical primary. A separately admitted2-method RED
on that preserved source produced3intended failures,0.040s,no errors/skips.
Both reviewers accepted it before fixes. The exact3752B test and uncorrected
Native source were copied and authenticated BEFORE this focused RED.

Corrected Native31082B/SHA256
5c216e9d4f4210e2c0cf0c40c136e7da08d2cd4a7f63bcbcb71e29ac405db33f
moves construction into stage=dataframe and excludes identical close objects
from secondary causes. Independent corrected-source review is CLEAR. The single
GREEN ran31/31PASS,0.068s,no errors/skips:15sidecars+2edges+6bindings+8quantity.
It verifies twelve in-memory CSV byte comparisons, count/scalar/sink limits,
collision refusal, distinct/same causes and original/prior construction facts.
These are controlled protocol/serialization checks, not genuine data validation.

All three captures have normal owned closure/EOF, no forcing/overflow/discard/
unknown/signal/deadline overrun and completed raw persistence. Outer returns prove
2176B/2190B/2337B result writes/fsync/close. Result SHA256 respectively:
1d7136524cd180465c90251cfaa457f847df48e31fa462998adf1272e3e844e6;
512f39360c7e57a33f3af0abb0acf9e381ccb0d470a21c59ef9801bf01abb4ab;
0c48fbbbf999a2404ecaf50213e402492e54582bbb6ff557aa16d75dce07796f.
All names are consumed. ZIP/manifest preserves channels/results/admissions/
outer returns and original sources; local originals remain. The first runner
614e... was recovered AFTER all outcomes by reversing only the later literal
extension and matches its pre-admission11026B/SHA exactly; it is honestly marked
as authenticated recovery, not a pre-run source capture. The later11377B/e38b...
runner is retained directly and will be committed as source.

Separate64MiB+16MiB tranches were independently priced before execution; cumulative
direct forms are1360MiB, derived C69.849609375GiB within80GiB above40GiB floor.
Fresh Windows/Linux C/E/ext4/runtime/config/pagefile/USN/mount/UUID/boot checks
preceded EACH invocation. E65GiB/full64GiB pagefile and192MiB cumulative source
cap remain. No native payload or test file/root was generated; memory fakes and
tripwires stayed within the reviewed roster. No cleanup or virtual-space credit.

Prospective CSV caps sum131766272B;4KiB rounding+64KiB facts+16nodes x16KiB
metadata fit128MiB/op,4.625GiB for37ops per representation. This is a conditional
future allowance, not local payload authority or whole-peak acceptance. Policy/
operational outputs, limits JSON, earlier three linkage DataFrames/readers,
retained objects/copies, remaining metadata/I/O/phase clocks and initial source
admissions remain separately open. Exact-commit independent/Grok/CI review is
still required. Full B3/task1.5, compiler/reader qualification, Docker/lifecycle/
runtime/genuine consumers remain open;46/24tasks and parked D27/Native57 remain.
