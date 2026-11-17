# B4 bounded build-context metadata, prospective control recipe

Same change, C: worktree, branch and PR9. Base b98b4aced156784c883887910f9e481e867b8d44.
This is a narrow implementation of approved B4's every-selected-writer boundary;
no Docker, compiler, pip, image, volume or real build is admitted here.

Close the materializer's manifest and context metadata before the first destination
write. Fixed envelope: at most3 manifests,8192 bytes/128 entries each, union128;
printable ASCII canonical relative paths <=256 bytes/depth8; each source <=32 MiB,
aggregate <=40 MiB; at most896 parent directory names; hash rows <=65536 bytes;
the exact existing success JSON schema including LF <=65536 bytes. Preserve
accepted order, source bytes, hash algorithm, output schema, modes and timestamps.
The helper source itself is in the contexts, so its change necessarily renews
actual context aggregate hashes; no historical aggregate is reused.

Read manifests through O_RDONLY|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK held descriptors
(where supported), immediately check fstat identity/regular single-link state,
and stop on remaining+1 before accumulating. Check close and named identity too.
Check manifest count before materializing its input sequence, entry count before
collections, union and all source sizes before copying. Preflight JSON escaping
with a fixed64-character digest before any destination write. Empty/output scans
use lazy scandir, never listdir/rglob; refuse unknown entries before collection or
descent, then check the complete bounded expected tree. The existing copy helper
remains byte-exact; no cleanup/clock/custody redesign is folded into this slice.

RED selects only old-boundary tests against unchanged materializer. They must fail
by concrete assertions (unbounded read/acceptance/early destination writes), not
missing APIs. GREEN runs the new class and existing12 tests under the qualified
Linux filesystem so actual0444 mode/symlink checks retain meaning. New synthetic
cases use tiny source files and controlled stat/read streams; no32/40 MiB payload
or actual FIFO operation is created. No child process is started by a test.
New test roots are retained with mkdtemp. Across BOTH phases, including the old
cases and Python's two tiny tempdir-selection probes, require at most64 roots,
256 file-creation forms,256 directories and64 KiB logical payload. The closed
authored census is53 case roots/225 file-creation forms/217 directories (including
both phase TMPDIRs). Existing successful TemporaryDirectory cases
retain their unchanged cleanup behavior; failure/extent witnesses stay retained.
The unchanged D16 owner/capture gives each phase one absolute300s deadline with
5/5/5s tails,1 MiB per channel, result <=32768 bytes and status <=2048 bytes.
One RED and one GREEN only; a failure consumes its namespace.

Prospective new32 MiB direct pair, before any test invocation:
4 MiB two phase raw channels;1 MiB results/admission/tool forms;2 MiB exact
source forms/copies;1 MiB fixture allowance;4 MiB directory/rounding/metadata;
8 MiB two public ZIPs and8 MiB their Git copies (each ZIP <=4 MiB);
1 MiB commands/manifests/checkpoint/tails;3 MiB retained slack.
Separate2 GiB additional sparse-ext4 allocation/scattering liability carries
the entire Linux pair without cleanup credit. Derivation at one1 MiB VHD block
per potentially newly allocated4 KiB guest unit:230 file-data units (225 plus4
for two8193-byte files and1 for the8192-byte file),217 directory-data units,
884 metadata units (two per442 file/directory creation forms) and64 parent/control
units total1395 MiB, leaving653 MiB retained physical slack. Fixed journal/maps/
VHD controls remain fully priced separately; no cleanup or co-location credit.
The prior448 MiB scattering quote becomes2496 MiB. Direct cumulative allowance becomes2224 MiB=2332033024 B
(Grok read-only profile32 MiB remains UNADMITTED, not silently funded here).
C derived additional quote73.130859375 GiB remains below80 GiB above40 GiB;
E65 GiB/full64 GiB pagefile and source/Git192 MiB remain unchanged.
Each archive has exactly9 members: that phase's command, admission, three source
copies, outer tool return, two raw channels and result JSON. At their ceilings,
inputs <=2392064 B plus655360 B conservative header allowance is below4 MiB.
The retained ext4 fixture roots are NOT copied or included in either ZIP; they
remain on the qualified filesystem and fully charged. Archive manifests <=16 KiB,
individual members <=1 MiB, fresh NoCompression ZIPs;
source/control recipes <=64 KiB/file and <=512 KiB aggregate/phase. Renew exact
Windows/Linux boot/UUID/config/units/RAM/swap/floor observations before each phase.

Independent recipe/test/launcher/capacity review precedes RED; source and RED
disposition review precedes sole GREEN. Then retain originals/ZIPs, obtain exact
commit review/configured Grok/latest-head CI and delegated source approval.
Actual retained RED:8 methods/14 intended assertion failures,0 errors/skips,
0.113s; D16 child1/outer0, complete EOF/closure/persistence and no force/overflow/
unknown/deadline. Sole GREEN selects27 methods (15 new and12 unchanged).
After RED, the oversized-manifest test was strengthened with no-open/no-read
tripwires; this adds no case root/file and is disclosed as GREEN strengthening.
Exact source-copy totals:62059 B RED and66422 B proposed GREEN, each <128 KiB.

All earlier builders' shell mapfile/closure reads, pip and compiler scratch and
outputs, image/cache/VHD growth, whole1.5 and actual compiler/reader/controller/
runtime/genuine acceptance remain open. No task is checked by portable controls.
