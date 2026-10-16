# Fixture Compiler Component Admission Plan V8: gate 2

Status: proposed, not execution approval. This amendment supplements immutable
V7 and the B1/B2/B3 dispositions. It changes no scientific predicate, owner
schema, provider, source pin, seccomp profile, source/channel/ELF cap or owner
deadline. Two independent exact-commit reviews, required CI and recorded
delegated AGENT approval precede dependent implementation; the implemented
gate-2 packet requires its own review/CI/approval before F2 recovery or C/D.
No new B container, retry, pull, prune, storage/configuration change, Q1 or
merge is included. All originals, old roots and stopped containers survive.

## 1. Starting evidence and dispositions

Base is 5c557489a7bff4e5a804405413e1165bf7d860cf. B1/B2/B3 are the three
retained stopped containers named by the handoff; six containers remain for
C1-C6. Their cumulative charge is 11,890,688 B.

- B3 D3: the two journald lines are attributable to the retained concurrent
  unattended-upgrade logs and systemd restart. They are not a probe crash.
  Accept only this recorded historical deviation after independent review.
  Do not disable timers or accept arbitrary future noise. Fresh guards and
  a same-session, pre-warmed VM/boot-ID check precede each run.
- B1 /dev/mqueue is rw,nosuid,nodev,noexec,relatime, uid-1000-writable.
  Its statvfs zeros do not mean zero capacity. The observed RLIMIT_MSGQUEUE
  soft/hard limit is 819,200 B; the existing 512 MiB memcg also applies.
- C3 permits only the attributable assembler SIGXFSZ 25 fatal banner,
  register dump, CORE=1/Aborting-core pair, and the previously specified
  audit record when applicable. No crash helper or new crash dump is allowed.
- B1 C5: full 20 s, two processes, zero output/CPU, flat 11,200 KiB RSS,
  unfinished until deliberate kill. Zero output predicts no completion
  before 90 s; projected 45 s RSS is 11,200 KiB, below 256 MiB. These are
  projections, not a replacement for C5.
- B2's original checksum manifest contains a stale self-entry at line 36.
  Its other 37 locally available entries match; the two full dmesg originals
  remain in the ext4 root as documented. Preserve the manifest unchanged.
  A supplementary no-self index authenticates current original bytes,
  including that original manifest; the index's own hash is bound externally
  by the reviewed packet/Git. The stale self-entry is never an authority.

The earlier Grok CLI excerpt-only review returned BLOCK. Its C4 source-cap
and missing HostConfig claims are contradicted by SOURCE_LIMIT=8 MiB and
the existing requested-key comparison. Its C6/TERM/KILL concerns require
physical qualification and complete evaluators, not optimistic guarantees.
Its transfer/allocation/authentication concerns are addressed below. Preserve
that verdict and its scope; this author's disposition is not independent
approval.

## 2. F2: finite recovery from stopped B1

Only GET archive data for these exact paths is admitted after implementation
approval. Read-only planning HEAD observations found regular files with empty
linkTarget. /lib resolves to /usr/lib; no alternate-path fallback is allowed.
Each row gives exact member bytes and maximum transfer-decoded tar bytes.

| Path | Member B | Tar cap B |
|---|---:|---:|
| /usr/lib/x86_64-linux-gnu/Scrt1.o | 1656 | 12288 |
| /usr/lib/gcc/x86_64-linux-gnu/11/crtbeginS.o | 2752 | 13312 |
| /usr/lib/gcc/x86_64-linux-gnu/11/crtendS.o | 1168 | 11776 |
| /lib/x86_64-linux-gnu/libc.so.6 | 2220400 | 2230784 |
| /usr/lib/gcc/x86_64-linux-gnu/11/liblto_plugin.so | 89120 | 99840 |
| /lib/x86_64-linux-gnu/libgcc_s.so.1 | 125488 | 136192 |
| /usr/lib/x86_64-linux-gnu/libc.so | 283 | 10752 |
| /usr/lib/gcc/x86_64-linux-gnu/11/libgcc_s.so | 132 | 10752 |
| /var/lib/dpkg/status | 869316 | 879616 |
| /var/lib/dpkg/info/gcc-11.md5sums | 2804 | 13312 |
| /var/lib/dpkg/info/cpp-11.md5sums | 287 | 10752 |
| /var/lib/dpkg/info/libc6:amd64.md5sums | 21606 | 32256 |
| /usr/lib/gcc/x86_64-linux-gnu/11/lto-wrapper | 753768 | 764416 |

The 13 member bytes total 4,088,780 B; tar caps total 4,226,048 B.
The wrapper is included because its path is passed to the reached linker
plug-in; its inclusion does not claim LTO execution.

Use one 90 s monotonic deadline, at most 5 s per request and no retries.
A fixed read-only recovery helper uses the existing socket/peer/epoch and
strict HTTP framing discipline. Preserve the existing owner's 256 KiB
metadata ceiling. If a private reply-decoding seam is extracted for reuse,
its default JSON/status behavior must remain exact and tested. The separate
fixed archive instance may charge at most 12 MiB logical wire-plus-raw bytes
(2x), 8 KiB headers per reply, 2 KiB per request, and 4,226,048 B aggregate
decoded tar data; no change to the owner's limits follows.

Admit at most 19 RPCs: three initial identity observations (version/info/B1
inspect), exactly 13 archive GETs, and the same three final observations.
Before each archive GET, revalidate the socket endpoint epoch and the B1
CID/provider binding from the sealed observations; final engine/B1 identity
must match. The API inventory has no exec/start/create/write endpoint.
A stopped-source filesystem change observed through stat/content drift
fails recovery; host/root mutation remains a trusted external boundary.
The fixed root contains only newly named output files, never reused paths.

Keep byte-exact HTTP request/reply originals once in the ext4 F2 directory;
this includes received chunk framing. Decode only after the bounded raw
receipt is available. Require status 200, exact expected basename, exactly
one regular tar member of the observed size, and no other file members,
links/devices/directories/path traversal. Permit only tar-format metadata
needed to represent that single member, bounded by its tar cap. Never
extract paths or persist extracted member copies. Hash members in memory;
require ELF64/EM_X86_64 for object/binary entries. Match the two linker-script
hashes against B1 before interpreting their declared references. Unknown
references, changed sizes, incomplete capture/persistence or overflow stop.

The fixed package reader selects installed package/version fields and file
associations from these bounded originals. MD5 association files are package
metadata, not cryptographic authenticity; SHA-256 and the pinned provider
bind recovered bytes. An embedded libc banner or package version is labelled
as such. B1's actual empty cc1 --version streams stay empty/unavailable and
are never relabelled as a measured version. Reviewers must disposition this
observation explicitly; no unsupported direct-version claim may close 2.10.

Combined persisted raw HTTP originals are <=6 MiB. The derived supplement
is <=256 KiB before encoding/writes. Git receives only the bounded supplement,
small indexes and their hashes/references; no raw tar/HTTP binary or extracted
file copy enters Git. Include all retained forms, report/Git copies and
allocation rounding in the 8 MiB F2/supplement aggregate. Stop on either the
logical limit or measured physical 8 MiB limit. Preserve failed prefixes and
unknown extents; do not retry or expand the path set.

## 3. N3 and externally bound C/D packet

Accept effective Config.Labels only as the exact union of the pinned provider
image's 23 labels and the requested ownership labels, with no collisions.
Missing/changed/additional labels refuse. Only empty Config.Volumes may
normalize between {} and null. Every other requested Config/HostConfig field
keeps its existing exact comparison; CapAdd must remain []. Added Docker
default keys outside the requested subset retain V7's documented disposition.

The C runner uses the unchanged component-only seed/admission schema, each
<=4096 B, with component_seed null and whole-chain authority absent. Require
all five nonnull proof hashes (baseline/toolchain/abi/limits/closure) and
authenticate them from B originals, corrected B2 index and F2 supplement.
A small external packet manifest binds the exact reviewed commit, approval
reference, physical-plan hash, runner/component/host/publisher/profile bytes,
fixed C-source pins, B proof/index identities and seed bytes/hash. Check
against reviewed Git blobs before export, and recheck exported bytes before
and after every run. A syntactically valid review field or seed hash alone
cannot authorize an unreviewed runner or changed module.

Retain the old B root. Export only code/packet files to the fresh gate-2
root's <=1 MiB code/P0 allocation (code and packet <=640 KiB; P0 originals
<=384 KiB). Generate C1-C5 source exclusively under each
fresh C output directory and charge source bytes to that C's 64 MiB
allocation. In particular, C4's 1,360,072 B is source, below the unchanged
8 MiB source ceiling; it is not charged to the 1 MiB stderr or code-export cap.
C6 uses C1's pinned source bytes under a fresh path.

Fresh P0 committed-snapshot info AND snapshots-ls evidence is required again
before C1. Historical B1 P0 or Unpacked metadata alone cannot pass. V8 permits
the delegated agent, as operator, to obtain the same proof without a human
typing a sudo password: fixed C:/Windows/System32/wsl.exe invocations with
-d Ubuntu -u root --cd / --exec and only these literal Linux commands:

- /usr/bin/id -u (must return 0);
- /usr/bin/ctr -n moby snapshots --snapshotter overlayfs info
  sha256:583abc9004877e79fd0f5d47e4c7cff085b8538fdcbff0c070e044bdb0b43c1a;
- /usr/bin/ctr -n moby snapshots --snapshotter overlayfs ls.

No shell, project helper, alternate executable, arbitrary command or default
user/configuration change is admitted. Record this as agent-observed root
proof, never human review. The ordinary C/D runner remains UID/GID1000.
Use one absolute 30 s P0 deadline, at most 10 s per command; stdout caps are
16 B /64 KiB /256 KiB respectively, combined stderr <=16 KiB, and all P0
original/control forms <=384 KiB inside the fresh 1 MiB code/P0 allocation.
Retain exact argv, PID/status/EOF/persistence and bounded originals; require
the exact committed chain JSON, its listing row and matching engine identity.
A timeout, overflow, nonzero, unknown closure or incomplete capture stops
continuation without guessed cleanup. Source/approval/hash bindings cover
the fixed P0 capture; this supersedes only V7's human-typed actor choice.
Before every create verify exact engine/provider/platform/security/runtime/mount
pins, zero running containers, exactly prior retained CIDs, idle GPU and all
original physical floors. Use one same-session pre-warm/boot-ID observation.
No C/D begins until this packet's implemented bytes have both independent
reviews, required exact-head CI and recorded delegated AGENT approval.

## 4. Fixed outcomes and independent evaluation

Pure tests must pin these complete expected mappings before execution.
Predictions are not guarantees; any other cause, status, unknown state or
timing deviation stops progression with originals preserved.

- C1: compiler/publisher/container 0; publisher/owner causes []; complete
  authenticated ELF64/x86-64 export; native normal closure; receipt persisted;
  forced false, accepted false, no published executable.
- C2: compiler 1, publisher/container 1; publisher causes exactly
  [compiler_exit_nonzero]; owner causes exactly [owner_wait_status].
- C3: same original statuses/causes as C2, with attributable assembler
  SIGXFSZ 25. The GCC driver return is 1, not -25. The old V7 EFBIG
  alternative is not accepted by this selected exact C3 expectation.
- C4: compiler -15, publisher/container 1; publisher causes exactly
  [stderr_overflow, compiler_term_attempted, compiler_exit_nonzero] OR
  [stderr_overflow, compiler_term_attempted, descendant_exit_nonzero,
  compiler_exit_nonzero]. Retain exactly 1,048,576 stderr bytes; EOF true;
  discarded = observed - retained > 0; authenticate the exact retained prefix.
- C5: compiler -15, publisher/container 1; same two cause lists with trigger
  compiler_deadline instead of stderr_overflow. Cutoff is publisher entry
  +45 s; TERM grace 5 s, KILL grace 5 s, export reserve 5 s. Require complete
  empty channels and normal compiler/descendant reap. KILL or earlier
  descendant failure is a deviation, not an extra accepted variant.
- C6: compiler/publisher/container 0 and publisher causes []; host first ELF
  write fault is explicitly synthetic. Owner causes exactly
  [export_OSError, attach_incomplete], forced false; ELF size/hash null,
  extent unknown, persisted/complete false; other members complete.
  Require the existing bounded normal-close wait to observe stop without
  owner TERM/KILL or HTTP409. Failure to do so stops, never reruns.

For C2-C6 require owner accepted/forced false, normal_closed false,
receipt_persisted true. Independently check the actual stopped final state:
Running/Restarting/Paused/Dead/OOMKilled false, Pid0, expected ExitCode,
Error empty, RestartCount0. Require containment_native closed true,
populated0, procs[], init_absent true. No matching owner-cause list alone
passes. C2-C5 must separately validate canonical captured header/source
binding, runtime PID1/CORE1/FSIZE16MiB/native ABI, compiler/descendant reap,
exact causes/statuses, member hashes, EOF/counts and persistence/close facts
that the owner's nonzero wait exception skips. No ELF is available there.
C6 authenticates the retained original header and failed_operation members;
its inner receipt export_binding is null and does not supply a success proof.

Stage D authenticates C1's retained
<executable>.compiler-originals/engine.unaccepted, never a nonexistent
published executable. Copy exclusively into a fresh 0700 directory with an
independently hashed 0700 ELF copy. Refuse before copy if ELF exceeds
524,288 B (512 KiB). This is a component pre-copy guard, not a change to
the compiler's 16 MiB ELF ceiling. Set CORE exactly1/1 and FSIZE1MiB in the
child before exec. A <=1 KiB pre-exec proof pipe records actual PID/UID and
getrlimit results after setting them; actual status, EOF and persistence
remain separately mandatory. The child has an owned fresh session and a
fixed minimal environment (PATH=/usr/bin:/bin, LANG=C, LC_ALL=C and HOME,
TMPDIR, TMP, TEMP equal to the D directory), without inherited loader hooks.
One 10 s absolute deadline includes 7 s work, at most one TERM/1 s, at most
one KILL/1 s and 1 s final observation; no reset or extra cleanup time.
Forced, late or unknown closure never passes. Close stdin after the fixed
command. Combined stdout/stderr capture <=4 KiB. Require exact D_REPLY,
rc0, engine.state bytes "ok\n", no WCOREDUMP and unchanged dmesg/crash
listings. Retain two dmesg originals <=192 KiB each, two crash listings
<=16 KiB each and all remaining control/capture/records <=96 KiB: 512 KiB
controls total. Refuse oversized pre-capture before exec. Reserve the full
1 MiB child-file liability, <=512 KiB ELF copy and <=512 KiB controls in
the 2 MiB D aggregate. This physical allocation replaces V7's 1 MiB D
quote without changing CORE/FSIZE or the 512 MiB seal.

## 5. Charge ledger and stop rule

These are inclusive aggregates, not permissions to omit copies or reset the
ledger. C wrappers/guards/evaluations/crash and journal records have a 4 MiB
combined cap inside each C's existing 64 MiB, with bounded pre-encoding
records and byte-exact prefixes retained on overflow.

| Aggregate | Bytes |
|---|---:|
| B1-B3 already charged | 11890688 |
| Original B code root, conservatively reserved separately | 1048576 |
| Fresh gate-2 code/packet root | 1048576 |
| F2 recovery, index, supplement and every persisted form | 8388608 |
| Six C runs, sources and all retained/Git forms | 402653184 |
| Remaining runtime growth planning allowance | 25165824 |
| Shared bbolt/journal/metadata slack | 83886080 |
| D ELF/file/control/capture aggregate | 2097152 |
| Total | 536178688 |
| Original seal | 536870912 |
| Unallocated | 692224 |

Runtime growth above the planned 4 MiB/run consumes the shared slack; the
unchanged 16 MiB per-container non-output stop still applies. Before each
operation reserve its bounded output and control liability against the
remaining seal. Charge the largest of ext4-used growth, retained output plus
SizeRw, and physical C-free decrease, including host noise, without counting
the same allocation twice. Measure non-container F2/export/D intervals too.
Preserve the original owner floor c_bytes + additional_disk_upper_bytes =
43,620,761,600 B, and applicable filesystem thresholds. Unknown backing,
exhausted reserve, floor/identity drift or exceeded allowance stops further
operations. Do not lower floors, increase the seal, clean originals or
delete/offload any image to make the plan pass.

## 6. Review and completion

Required RED/GREEN tests: exact label union/collision/extra/missing/value
drift, Volumes normalization only, independent mutations of every requested
HostConfig field, both ordered C4/C5 cause variants, rejection of KILL/unknown
EOF/forged headers/changed hashes/closure, changed packet/helper/source bytes,
null/foreign B proofs, bounded archive framing/tar/path/size/status/deadline/
persistence failures, fixed root-P0 argv/deadline/capture/provenance refusal,
D pre-exec limit proof and all four D phases, and exclusive C1-to-D
copy/source/command/reply/state binding. Check probe/publisher payload syntax
under Python3.10 grammar;
run host tests under canonical WSL Python3.12.3 and configured hosted CI.

After each physical run persist actual original values and their comparison.
Any deviation requires a separately reviewed disposition and exact-commit
CI/approval before the next run; it never authorizes rerunning a B/C stage.
After F2/C1-C6/D, obtain independent review of raw evidence and all charged
forms before checking 2.10 complete. Carry every remnant, unavailable
observation and synthetic-only enforcement limit into whole1.5. Reader2.12,
whole1.5, genuine2.8/5.3, package renewal, conformance, archive and final
approval remain required. No component result grants Q1 or merge.

## 7. Observed F2 identity refusal: proposed single-successor disposition

This addendum is a proposal, not continuation authority. Exact c75ad950ee542621a365725db627fdd03d2363e8 had two independent source CLEAR_WITH_NOTES reviews, successful required run38930817812 and delegated AGENT approval PR9comment6220677031. Its one actual setup stopped after three HTTP200 identity GETs: no archive GET, member, P0, C or D ran. Preserve that failed root, its six HTTP originals, failure/control files, Temp streams and enclosing tool original. Never reuse it or relabel it accepted.

The only decoded old/new inspect differences are HostConfig.Dns, DnsOptions and DnsSearch: null became []. B1's original create requested none; NetworkMode remains none. All other decoded values match. Old/new inspect SHAs are9d515b0717a579df4da87f3193e60eb5c8540e0ec1f52769470354f56ac5584b and58b2b00a2efb0331e734eb5af5146115f64c6f1a788f0ed48175dd3aab9ef086. The failure original is4791B/SHAa41a90e8b23675ba3852c38a81f0da9ad3b143b596233ddc2afe0cd8826aa6a4. This is not evidence of changed source files or requested policy; c75 nevertheless correctly refused its full-HostConfig predicate.

Permit only these three historical empty-default representations in a corrected comparison: each key must exist, the pinned historical value must be null, and the fresh value must be null or a typed empty list, under unchanged NetworkMode=none. Missing, nonempty, wrong-type or other changes refuse. Every other Config/HostConfig/state/provider/mount/size comparison remains exact. Hash the ACTUAL fresh selected inspect, so fresh initial/final representation changes still refuse. Bind regression tests to the retained raw pair; never rewrite either original.

After independent exact planning review, required CI and recorded delegated approval, implement the correction and bounded retention binding. After two independent exact implemented-source reviews, new required CI and recorded delegated approval, admit AT MOST ONE successor setup at its newly reviewed commit-derived fresh root. This explicit exception supersedes the no-retry rule only for this recorded identity-only failure; it grants no automatic retry, third setup, B/C rerun, extra container, fallback or cleanup. The successor performs all19 F2 GETs and fresh P0 under the original contiguous150s envelope,90s/5s F2 and30s P0 limits. Actual packet and per-stage reviews remain mandatory.

Bind all failed forms and source versions with one readable plain-JSON frozen index (encoded bytes<=12288B, independently bounded working plus Git rounded/metadata forms<=32768B), authenticated against reviewed Git before new allocation and bound into operator authority/packet review. The derived planning index is gate2-f2-c75a-retention.v1.json,9637B including LF/SHA2568925428192e339d52d2bcc7a2f99587303765796dc0769f47dcf192ce40ce006; it binds historical c75 plan bytes, while successor authority binds this index and the amended plan separately, without a hash cycle. Preserve the6651B held diagnostic tool-output transcript, SHA4677b02a792cf28f83cc59cf15c575b1358c6d9fd4b6ced00e33d9416e8d3db8, once in Temp; it contains the actual receipt and parsed inventory, but the separate6213B native stdout original was NOT retained or reconstructed. Its Windows quote is round4096(6651)+4096=12288B:8192B data plus4096B metadata, already included rather than added again. No full old source-tree, raw-stream or receipt duplicates are added. The conservative no-dedup owned quote2057216B already includes old source working/Git versions; plus transcript12288B and index32768B gives2102272B, leaving60416B under the private failed-owned2162688B (2MiB+64KiB) cap; D remains independently limited to2097152B. Shared identities need one explicit global assignment; no unproved dedup credit or omitted distinct old Git variant. Failed-specific outside forms remain <=512KiB inside that tighter owned bound; active-successor outside remains <=512KiB. The explicitly changed combined outside ceiling is1MiB, funded below, rather than pretending both fit the old512KiB.

The original closing meter/peak is UNAVAILABLE. The618496B F2 partial charge precedes later writes. The separate17:16:39Z diagnostic cannot replace that endpoint: setup-baseline-to-diagnostic C-free decrease5369856B includes idle/unattributed effects. Charge a conservative6MiB prior-attempt BRIDGE after the successor operation's maximum, without acceptance or credit for the failed interval: max(2162688B failed-owned forms,5369856+524288 outstanding-copy conservatism)=5894144B <6291456B. The524288B term does not permit that much additional owned allocation. Changed/unreadable forms, exceeded quotes or unresolved disposition stop admission.

Old F2 ALL forms are constrained to393216B inside the bridge, once globally: directory106496 + nonshared old AUX/Windows/copies83200 + whole index32768 + transcript12288 + distinct old capture/setup Git forms45056+53248 =333056B, leaving60160B under that subcap. Source10/plan code forms have their separate code assignment; no proof/capture form disappears from both subcap checks. Both this384KiB limit and the private2162688B failed-owned limit bind. Preserve the combined F2 ceiling8388608B by limiting the successor to7995392B; do not reset it or add the old proof debit globally a second time.

Keep raw-original6291456B, logical-wire12MiB and every13member/tar bound unchanged. Only f2.final-accounting.v1.json receives a private16384B limit; originals index, supplement and failure stay262144B each. Close the footer schema before encoding: exact root/producer-accounting keys; supplement relative_path=f2.supplement.v1.json, size<=262144 and64hex SHA; baseline/last have exactly ext4_used_bytes/c_free_bytes uint64 integers and fragment_bytes4096; reject extra fields/types/ranges. An independent conservative symbolic bound is934B; meaningful tests must verify it after planning approval. One filename-to-cap table governs prospective liabilities, pre-encoding/pre-open writes and read-only validation. Pre-footer control reserve is16384+262144=278528B plus both slots'4096B rounding and4096B metadata. A partial footer stays untouched and retains the full failure-slot liability; unknown/late/over-budget states never accept or start an unfunded failure write. No truncation, second footer or discarded facts earns room. Required tests cover maximal/malformed/oversized footer, entry boundaries, partial write/fsync/close and unchanged other-control caps.

The successor entry liability is8216576-(262144-16384)=7970816B, leaving24576B inside7995392B. The revised envelope is B11890688 + oldBcode1048576 + successorcode/P01048576 + priorbridge6291456 + successorF27995392 + C402653184 + runtime25165824 + shared77594624 + D2097152 =535785472B, below the unchanged536870912B seal by1085440B. Shared slack decreases80MiB to74MiB:72MiB maximum runtime extras plus2MiB PLANNED daemon/journal reserve. This is not a hard growth guarantee or evidence of intervening peaks. Preserve existing fresh entry/end measurements and full prospective reservations; charge observed non-container excess and refuse on exhausted/unknown backing. Floors and all existing C/D/source/runtime/output limits stay unchanged. No whole1.5, genuine consumer, Q1, archive or merge acceptance follows.
