# Fixture Compiler Component Admission Plan V9: fresh direct gate 2

Status: proposed, not execution approval. V9 replaces these parts of V8 for task
2.10: section 2; section 3's packet and P0-operator parts; section 5's ledger table;
and sections 7–8. V8 sections 1 and 4, the rest of section 3 (N3, seed/admission
schema, P0 argv and caps), and section 6 stay in force unchanged. V8 is bound here by
its Git blob `8cf0afbf9dd122de6acb5682d9e470e4eacec358` (40,901 B, SHA256
`dc130a657a7c582c084f364425773f17e2487afb95cd65825e2e815041cf83d6`). V1–V8 are
retained history and are not edited. The reasons are in design.md, "Fresh direct
gate 2 for task 2.10, 2026-11-12".

**Superseded explicitly:**
- V8:305's "no … third setup": this one fresh packet operation is admitted under V9.
- V8 section 5's "including host noise", for the period from the 465 F2 `last`
  measurement to the fresh PRE only. Within every operation interval, host noise is
  still charged.
- V8:315's 74 MiB shared slack. It is now 75,010,048 B (section 5), which is
  2,584,576 B short of the worst case in which every C stage reaches its 16 MiB
  runtime stop. That case fails closed at `reserve_v1` before a later stage and
  stops the chain. This risk is accepted.

## 1. Starting state (observed read-only, 2026-11-12)

- **Engine:** native `1e493309-3767-45fb-9078-05b838bdfd80`, 29.7.2, overlayfs,
  systemd.
- **Provider:** `c11befa8…`, restored by B1 attempt 02: RootFS `1e0fe0c4…`, Size
  10,469,582,904, chain `583abc90…` Committed.
- **Containers:** `GET /containers/json?all=1` (the call C uses) works and lists
  exactly the three exited B containers (`B_CIDS`), and nothing else.
  - All three B containers have lost their writable-layer snapshots.
  - Plain `GET /containers/{id}/json` works. `?size=1`, `docker system df`, archive
    export and start fail.
  - No V9 step size-inspects, exports or starts a B container.
- **Old roots:** the 465 owner root has `p0/`, code copies and its plan, but no `r1/`
  and no `r1.operator-originals/`. The consumed attempt in PR #9 comment 6230407759
  therefore created no native namespace. The c75 and 465 roots, their `.f2` and
  `.operator-originals` siblings, and the B component root stay untouched.
- **F2:** `validate_supplement_v1` accepts the retained 465 F2 originals
  (`…465ab79…-01.f2/f2.supplement.v1.json`, review commit `465ab79…`) unchanged, in
  a read-only dry run.

## 2. Code, manifest and authority

- **Reviewed commit X** is the exact PR head that receives the implementation
  approval. Local Git is never used, and HEAD is never required to equal X.
- **Manifest.**
  - **What it is:** a canonical JSON file of at most 8,192 B. It lists the path,
    size, SHA256 and Git blob id of every exported file and of the operator.
  - **How it is made:** after CI passes on X, Claude reads it from the GitHub tree of
    X and writes it to `C:\Users\s-a-balashov\AppData\Local\Temp\vast-gate2-fresh-X.manifest.json`.
  - **Approval:** the implementation approval comment records X and the manifest's
    SHA256.
- **Operator arguments:** `X`, the approval URL, the manifest path and the manifest
  SHA256.
  - The operator refuses a manifest whose hash differs, or any file whose blob id,
    recomputed from its bytes as `sha1("blob N\0" + bytes)`, differs.
  - It does no network I/O.
  - The packet review checks that the approval comment names X and the manifest
    hash.
- **Exported set:** the gate-2 `CODE_PATHS`, the D, D-child, recovery and P0
  optional paths, and this plan, at their repository-relative paths. The plan uses
  the active change-directory form, which R1 keeps as the recorded identity.
  `_verify_code` re-checks the exported code on every packet validation.
- **Fresh context:** at most 8,192 B, with exactly these keys:
  - `schema_version` (1) and `project_root`;
  - `consumer_commit` (X) and `approval_reference`;
  - `manifest`: the size and SHA256 of the manifest copy in `.operator-originals`;
  - `operator` and `plan`: each exactly `path`, `size_bytes`, `sha256`, `git_blob`.
    The operator is not in `CODE_PATHS`;
  - `f2_producer`: exactly `commit` and `plan_sha256`;
  - `boot_id`;
  - `info`: the request and reply descriptors of the `.operator-originals` RPC pair,
    plus the identity projection `engine_id`, `server_version`, `containers`,
    `running`, `paused`, `stopped`. The reply itself is not embedded;
  - `measurements`: exactly `pre` and `pre_packet`;
  - `allocation_bytes`, `noise_bytes` and `excess_bytes` (section 5).
- **Packet-to-manifest binding.** The fresh branch reads the manifest copy from
  `.operator-originals` and checks its size and SHA256 against the context. It then
  requires:
  - every packet `code` descriptor to equal its manifest row;
  - the `plan` descriptor to equal the manifest's plan row;
  - the `operator` descriptor to equal the manifest's operator row.

  Each C-stage revalidation therefore sees the manifest too.
- **Windows-side imports:** the operator loads every module it uses on Windows, P0
  included, from bytes it read once and verified against the manifest. It never
  imports from the working tree.
- **Fresh root:** `/home/s-a-balashov/work/vast-fixture-compiler-gate2-X-01`, the
  name `gate2_c`'s native bootstrap already expects.
  - The operator refuses if the root or `…-01.operator-originals` already exists, or
    if the 465 `r1/` exists.
  - It creates both 0700 as uid 1000.
  - Claude creates the empty `…-01.guard` directory just before the first guard run,
    because the guard needs it for its record.

## 3. Fresh packet operation (one invocation)

- **Launch:** Claude starts the containment guard (section 6) as uid 1000 in WSL.
  The guard starts `C:\Python314\python.exe -I -B <repo>\tests\fixtures\accepted_policy_fixture_compiler_gate2_fresh_v1.py
  <args>` through WSL interop.
- **Linux phases:** each phase runs `wsl.exe -d Ubuntu -u s-a-balashov --cd /
  --exec /usr/bin/python3 -I -B -c <BOOT> <phase> <size> <sha>`.
  - `BOOT` is a fixed string in the operator. It reads the operator file once from
    its `/mnt/c` path, checks its size and SHA256, executes those same bytes, and
    calls their `native_entry_v1(phase, x)` with `x` read from stdin. This is the
    resume operator's pattern (resume:466).
  - PRE and EXPORT use only the operator's code and the standard library.
  - PACKET imports only from the fresh root, after EXPORT has verified it.
- **Clock:** one original 150 s deadline, set before authentication; a 140 s work
  cutoff and a 10 s return reserve. Each WSL phase gets at most 15 s, or less if
  less remains.
- **Phases, in order:**
  1. **PRE.** Read the boot id. Make one ordinary `GET /info` over
     `/run/docker.sock`; request plus reply is at most 16,384 B on the wire. It must
     show `Containers` 3 / running 0 / paused 0 / stopped 3. Read the C:/E:/ext4
     measurement. The results stay in bounded memory, and nothing is written.
  2. **EXPORT.**
     - Create the fresh root and `.operator-originals`.
     - Write the PRE originals, the manifest copy and the authority record into
       `.operator-originals`.
     - Copy each manifest file from `/mnt/c` with one read: verify it, write it with
       `O_EXCL`, fsync it and read it back.
     - Rebuild the corrected B2 index there with `build_b2_index_v1`.
  3. **P0.**
     - Call `collect_native_p0_v1` with `windows_native_p0_effects()`, writing to
       `\\wsl.localhost\Ubuntu<root>\p0`.
     - The V8 section 3 argv, its 30 s deadline and its caps are unchanged.
     - The sealed binding's ordinary-API provenance uses the PRE engine id, the boot
       id and the `/info` originals. The reviewed commit is X.
  4. **PACKET.**
     - First take the `pre_packet` measurement and the allocation, and compute the
       charge (section 5).
     - Then call `build_packet_v1(..., fresh_context=...)`. It writes
       `<root>/gate2.packet.original.json`, at most 32,768 B (`FRESH_PACKET_LIMIT_V1`).
       It then reads the file back and validates it with `validate_packet_v1`.
     - The `physical_plan` path is the exported V9 copy. The `p0` path is
       `<root>/p0/p0-completion.v1.json`.
  5. **POST.** Take one more measurement and run the POST check in section 5.
- **Evidence:**
  - the B originals, from the B component root;
  - the rebuilt B2 index;
  - the 465 F2 supplement, index and final accounting. F2 is authenticated as
    evidence of producer commit `465ab79…` and its producer plan hash, not of X.
- **Output:** one canonical ASCII stdout document of at most 2,048 B, written after
  the work. It holds the packet size and SHA256, the boot id, the phase statuses,
  the charge figures, and the first cause plus ordered distinct secondary causes. The
  operator emits no progress, stderr or traceback output of its own.
- **Children:** the operator copies each child's facts first. Then it kills that
  child and waits for it, bounded by the deadline (the R4 rule).
- **After the run:** Claude copies the originals byte-exact into
  `evidence/compiler-component-01/gate2-fresh-01/`. Nothing is deleted, and no C or
  D stage runs in this invocation.

## 4. Packet approval, then C1–C6 and D

- **Packet approval:** C1 waits for an independent review of the packet, P0, phase
  originals, charge figures and POST outcome, and a recorded delegated agent approval. The approval names
  the packet size and SHA256. It admits C1–C6 and D, one invocation each.
- **C stages:** for each stage, the guard runs as uid 1000:
  `/usr/bin/python3 -B <root>/tests/fixtures/accepted_policy_fixture_compiler_gate2_c_v1.py
  Cn X <packet size> <packet sha> <prior>`.
  - For C1, `<prior>` is `-`.
  - For later stages it is the comma-separated `size:sha` of each earlier stage's
    `outer.invocation.original.json`.
- **D:** `/usr/bin/python3 -B <root>/tests/fixtures/accepted_policy_fixture_compiler_gate2_d_v1.py
  X <packet size> <packet sha> <six priors>`. There is no stage token.
- **Recording:** stdout, stderr and status are kept for every stage. The expected
  outcomes are exactly those of V8 section 4. A passing stage needs no new approval
  before the next one.
- **Stop rule.** The chain stops on any of these:
  - a refusal, deviation, or unknown or late status;
  - a boot-id change;
  - interstage dmesg or crash-listing drift;
  - a guard breach;
  - a form or allocation above its cap (section 5);
  - a guard record larger than 65,536 B. Claude checks each record's size after
    its run and records the measured size in the PR #9 evidence for every
    invocation.

  A stage is never rerun. Continuing needs a reviewed disposition, exact-commit CI and
  a recorded approval (V8 section 6).
- **Boot stability.**
  - Before PRE, Claude starts one uid-1000 keepalive,
    `wsl.exe -d Ubuntu -u s-a-balashov --exec /usr/bin/sleep infinity`. It runs until
    D returns, so the WSL VM does not idle out between the packet and C1.
  - Root timers such as `unattended-upgrades` are external writers. They are observed,
    not disabled.
  - From the packet to D, Claude runs nothing else on the native engine and nothing as
    root in Ubuntu.
  - Desktop is not touched.
  - A drift caused by an external writer stops the chain, as above.
- **Retention:** the C and D originals are copied into
  `evidence/compiler-component-01/gate2-fresh-01/outputs/<stage>/`.
  - Host dmesg dumps, and any single original larger than 1 MiB, are recorded
    there by path, size and SHA256 only, as with B1–B3. The native originals stay
    in the fresh root and are never deleted.
  - The committed evidence stays within 64 MiB in total.

## 5. Ledger and stop rule

The cumulative ledger is never reset. The starting debit is the 465 resume's carried
debit (V8:315, 351). It is kept conservatively, and is made up of:
- B1–B3: 11,890,688;
- the old B code root: 1 MiB;
- the 465 code/P0 root: 1 MiB;
- the 6 MiB carry;
- F2: 7,995,392;
- the retired SOURCE row: 1,032,192;
- the 16,384 diagnostic.

| Aggregate | Bytes |
|---|---:|
| Carried debit (`RESUME_INITIAL_CHARGE_V1`) | 29,323,264 |
| Fresh root, `.operator-originals`, `.guard` and the packet-operation noise | 2,621,440 |
| Six C runs, sources and all retained forms (V8) | 402,653,184 |
| Runtime growth planning allowance (V8) | 25,165,824 |
| D ELF/file/control/capture aggregate (V8) | 2,097,152 |
| Shared bbolt/journal/metadata slack (V8: 83,886,080; resume: 77,594,624) | 75,010,048 |
| Total = original seal | 536,870,912 |

**Closed assignment of the 2,621,440 row.** All figures are allocated bytes: each
file is rounded up to 4,096 B, plus 256 B per inode.

| Form | Cap (B) |
|---|---:|
| Exported code, plan and packet: at most 14 files, at most 655,360 B logical (the existing `code_packet_allocation`) | 720,896 |
| P0 originals (P0's own allocated maximum) | 387,328 |
| `.operator-originals`, 10 files: authority 8,192, `/info` request and reply 16,384 together, manifest 8,192, B2 index 65,536, phase records 4 × 8,192, measurements 8,192; with rounding and inodes at most about 145,920 | 172,032 |
| Guard records: 8 invocations × 65,536 | 524,288 |
| 12 directories and their inodes | 65,536 |
| Packet-operation host noise allowance | 751,360 |

- **Charge formula.** It is computed before, and checked after, the packet is written:
  - **A** is the actual allocation, measured as `_resume_allocated_v1` does, of the
    root, `.operator-originals` and `p0/`. A plus 36,864 B (the packet reserve) must
    be at most 1,345,792 B, the sum of the form caps excluding guard records and
    noise. Otherwise the operation stops.
  - **Interval** is the V8 section 5 interval from `pre` to `pre_packet`: the largest
    of the C:-free decrease, the ext4 growth and A.
  - **Noise** = max(0, interval − A).
  - **Excess** = max(0, noise − 751,360).
  - The packet's `initial_charged_bytes` is exactly 31,944,704 + excess. The fresh
    branch recomputes it from the context, so later stages carry any excess, and
    `reserve_v1` fails closed if the slack runs out.
  - **Before PACKET:** if 31,944,704 + excess + 73,400,320 (C1's liability:
    64 + 4 + 2 MiB) exceeds 536,870,912, the operation stops before writing the
    packet, so the admission is not spent on a packet C1 could never pass.
  - **POST check:**
    - The allocation measured after the packet write must be at most A + 36,864.
      Otherwise a form is over its cap, and the chain stops.
    - A_post = max(measured allocation, A + 36,864).
    - The POST interval is the V8 section 5 interval from `pre` to `post`.
    - noise_post = max(0, POST interval − A_post).
    - The check requires max(0, noise_post − 751,360) ≤ excess. Otherwise the packet
      is retained but not usable: the chain stops before C1, for a disposition.
    - The operator's stdout document carries the POST outcome, and the packet review
      and approval (section 4) must check it explicitly.
  - The boundary tests cover noise exactly at the allowance and one byte over, both
    before PACKET and at POST, the post-write allocation at A + 36,864 and one byte
    over, and the C1-liability bound.
- **Guard records:** guard records are charged here, at most 65,536 B each, not to
  the C/D allocations.
- **Outside the native seal:** the D17–D27 Temp forms, the `.retired` copies and the
  evidence copies in the repository live on C: NTFS and in Git. They are counted as
  external terms in the split-route re-admission. The committed evidence is at most
  64 MiB.
- **Unchanged:** the 16 MiB per-container non-output stop, the owner floor
  43,620,761,600 B and all reserve checks. The seal is not raised, no floor is
  lowered, nothing is cleaned or deleted, and no image is offloaded.

## 6. Admission and containment

- **Re-admission.** Before the packet operation, a fresh C:/E: sample is re-admitted
  against the remaining whole-chain peak and recorded in PR #9. The peak includes:
  - the observed Desktop `docker_data.vhdx` growth: 143.6 GB at admission, 154.2 GB
    on 2026-11-12;
  - the gate-2 seal remainder;
  - the external terms in section 5.
- **Guard.** Every invocation (packet, C1–C6, D) runs under
  `scripts/accepted_policy_containment_guard_v1.py --interval 0.5`, without its Docker
  options. Each record goes to `…-01.guard/<phase>.json`.
- **Guard limits.**
  - The guard does not own compiler containers; the D15 executor creates them. On a
    breach during a C or D stage, the guard stops the stage's process group. A
    container that already exists then ends under its in-container publisher
    deadlines, is recorded as unknown closure, and the chain stops.
  - During the packet operation, the guard's stop reaches only the interop process.
    The closure of `python.exe`, its `wsl.exe` children and their Linux children is
    then unknown, recorded so, and the chain stops.
- **Nesting check (no-effect run, before implementation approval).** The guard writes
  its record to `/home/s-a-balashov/work/vast-pr9-gate2-fresh-nesting-check-01/`,
  outside every fresh root and sibling. It launches interop `python.exe -I -c` with
  two `wsl.exe -u s-a-balashov --exec` children:
  1. `/usr/bin/true` must return 0;
  2. `/usr/bin/sleep 20`, during which the guard is stopped by SIGTERM.

  The record states which processes outlived the stop. This run makes no Docker call
  and does no root or repository write.

## 7. Completion

After D, an independent review of the raw evidence and every charged form must come
before 2.10 is checked. These remnants are carried into whole 1.5:
- the loss of the B writable layers;
- C6's synthetic-only fault;
- the unavailable historical 465 closing meter;
- any unknown closure.

Reader 2.12, whole 1.5, genuine 2.8/5.3, renewal, conformance, archive and final
approval are still required. No component result grants Q1 or merge.
