# Finite sealed build-context copy regression

This is the existing B4 pre-write-bound requirement applied to the host context
materializer, not whole-task1.5 admission. At source d950d8124960e82db88ae5cc08775d9683b047a4,
_copy_held_source writes every chunk before checking expected.st_size at EOF.
Reject any chunk exceeding the remaining sealed extent before digest/counter/
destination write. Request at most min(the existing1MiB chunk, remaining+1) to
detect growth, including empty sources and growth immediately after the exact
extent. Preserve final length, source snapshots, short-write handling, exclusive
destination creation, immutable metadata, hash/manifest output and failure roots.
No numerical runtime cap, Dockerfile input, public interface or owner changes.

Add RuntimeBuildContextCopyExtentTests to tests/test_runtime_build_context_v3.py.
The four new methods contain seven controlled vectors: oversized first chunk for
empty/nonempty sources2; growth after a partial/exact prefix2; truncated stream1;
and exact empty/chunked short-write/hash controls2. Finite read doubles model
post-open growth. Actual tiny destination files and one-byte writes expose the
side effect; assertions inspect their real bytes, write count and lack of fsync
on refusal. The new class uses mkdtemp without cleanup so its actual source and
destination witnesses survive both outcomes. Keep the eight existing real-
filesystem/custody tests unchanged; their existing TemporaryDirectory cleanup is
not retained-witness evidence and yields no admission credit.
RED selects only the two growth methods/four vectors against unchanged product:
expected four assertion failures because actual destination bytes exceed the
sealed extent. It must not fail from missing APIs, exhausted doubles or imports.
GREEN selects the entire module: twelve methods/fifteen fixture vectors, no skips
on the qualified Linux runtime. Two legacy methods call the materializer twice,
so GREEN has seventeen direct materializer/copy invocations, not fifteen calls.
It checks failure and success behavior together.

Use fresh buildextent-red-01/buildextent-green-01 once each through the unchanged
D16 capture/writer in preparatory_checks.py. The runner changes only their literal
roster, existing C:/temporary/E:/memory guards, cumulative allowance and expected
RED status. Preserve both raw channels, result, actual outer tool return, admission,
actual command and exact materializer/test/runner copies. No genuine compiler,
reader, Git/proof child, Docker, image, storage/config mutation or runtime build.
Independent recipe/source/capacity review precedes each selected invocation.

Reserve one additional32MiB pair within existing C80GiB above the40GiB floor:
4MiB two-phase raw channels;256KiB result/outer/admission;1MiB exact source forms
and one funded Git copy;8MiB two capture ZIPs plus their Git copies (each ZIP<=2MiB,
each manifest<=16KiB; raw/source and retained tiny witnesses are separate ZIPs);
5MiB configured Grok original/ZIP/Git forms (prompt<=128KiB, channels<=512KiB each,
outer<=16KiB, ZIP<=1.5MiB);1MiB case filesystem/namespace allocation;1MiB retained
commands/checkpoint/review tails including their copy and the two capture manifests
with Git copies (<=64KiB combined); remainder retained slack.
Source originals: three per phase, each<=64KiB, aggregate<=128KiB. At most four
command forms (two templates/two actuals), each<=16KiB, aggregate<=64KiB.
Both phases together use at most32 small fixture roots,192 files/directories and
16KiB payload; charge their1MiB peak without cleanup credit. Existing TMPDIR and
-B bytecode prohibition remain. No old archive or output ceiling is increased.

Cumulative direct reservation becomes2080MiB=2181038080B. Unchanged guards:
C80GiB additional plus40GiB floor; E65GiB including full64GiB pagefile; source/Git
192MiB; same Ubuntu boot/UUID/config, allocation units<=4096, guest RAM<=24GiB
and exactly6GiB swap. New finite preparatory approval cannot close whole1.5,
prove host context aggregate fit/BuildKit limits, or authorize genuine execution.
Exact source review, configured Grok and exact-head CI follow GREEN in PR9.

## First GREEN failure and one prospective Linux-filesystem validation

The admitted buildextent-green-01 ran12 methods in1.183s: all four new methods
passed; the existing immutable-metadata success test failed because its C: DrvFS
destination reports0555 after chmod0444. All other methods passed; no errors/skips.
The observed mount is9p/DrvFS without metadata. The unchanged eight-test fixture
was placed on the wrong filesystem for its actual POSIX-mode assertion. Preserve
the failed capture/outer/admission and all seven new retained roots. Its legacy
TemporaryDirectory witness is unavailable after that predeclared cleanup.
Microsoft documents this permission translation at
https://learn.microsoft.com/en-us/windows/wsl/file-permissions . No mount option,
configuration, permission assertion, production code or existing test changes.

Independently review ONE additional buildextent-posix-green-01 before execution.
It selects the same12 methods/15 fixture vectors/17 direct invocations with exact
unchanged materializer/test bytes. Only this named phase keeps the runner's
original /var/tmp/vast-pr9-b2-prep-buildextent-posix-green-01 temporary root;
its canonical parent must share the already-qualified ext4 root device. Capture,
result, admission, three source copies and command remain in the same C: worktree.
Fresh guards must prove the new Linux and C: namespaces unused. Keep all seven
new tiny Linux fixture roots; the original eight retain their unchanged cleanup.
Copy at most14 fixed source/destination witnesses, each<=4B, into one new C: witness
directory with bounded reads/pre-write equality, preserving original Linux files.
Retain a separate <=2MiB ZIP and<=16KiB manifest for this phase and its tiny copied
witnesses; no existing ZIP cap is increased.

Before allocation assign7.5MiB of the original11.75MiB retained slack:
2MiB additional raw channels;128KiB result/outer/admission;256KiB three source
forms and their Git copy;4MiB extra ZIP/Git plus32KiB manifest/Git;1MiB Linux/C:
case allocation and metadata with no cleanup credit;64KiB additional command/tail
forms. These sum7.46875MiB, leaving32KiB inside this assignment. The original
four command forms remain unchanged; this fifth actual command has its own
<=16KiB limit here. No second proposal template is created. Listed original20.25
plus selected7.5 equals27.75MiB<32MiB; cumulative2080MiB/C80/E65/Git192MiB unchanged.
The failed phase remains consumed; this is a named, independently admitted
filesystem correction, not an automatic replay or physical build qualification.

For the new Linux fixtures also fund physical VHD scattering before allocation:
the full1MiB case ceiling is256x4KiB pages, each conservatively charged as a1MiB
VHD block (256MiB), plus192 additional per-node metadata pages similarly charged
(192MiB). Carry448MiB with no sharing/retirement credit; the existing seal's full
fixed ext4 metadata/journal/VHD-control charges remain. The derived C quote rises
from70.552734375GiB to70.990234375GiB<80GiB; neither the32MiB direct-file tranche
nor the C80GiB additional/40GiB floor or E65GiB reservation changes.
