# Fixture Compiler Component Admission Plan V7 (task 2.10)

Status: planning only. No container, probe, compile or host ELF execution has
run or is authorized. V1 (`e8ca7c22`), V2 (`9706bd89`), V3 (`74ec0e00`) and
V4 (`6b80c17f`) are retained unchanged as history, as is V5 (`efa59e92`),
which was approved in PR #9 comment 6204153691 (Claude CLEAR_WITH_NOTES, grok
CLEAR). V6 (`e042c47a`) changed only C5's workload (section 11). V7 adds the
gate-1 review corrections in section 12: B2's memfd execution, the x32 ENOSYS
code, the C4 sizes, and runner-recorded measurements. V7 is reviewed together
with the gate-1 code and needs independent review,
mandatory checks on its exact pushed commit and a recorded delegated AGENT
approval in PR #9 before any gate-1 work. Decision15 (approved at `c8362f290be986a60403eac306375e26fac43f39`)
governs the boundary; task 2.9 implementation is final at `70466266`.
Nothing here closes whole 1.5, 2.8 or 5.3, or any genuine cohort. Nothing
grants Q1, storage, image or provider authority.

## 1. Fresh read-only observations

Captured 2026-10-15T21:29:14Z (manifests/system df later in the same session)
from the WSL Ubuntu distribution as uid 1000 (docker group; `sudo` needs a
password; the only root observation is the user-run P0 below). Raw replies are
retained in `observations-01/`.

| Fact | Observed | Decision15 / 2.9 pin |
|---|---|---|
| Engine ID | `1e493309-3767-45fb-9078-05b838bdfd80` | same |
| Docker server / API / min API | 29.7.2 / 1.55 / 1.40 | 29.7.2, min <= 1.55 <= API |
| Storage | overlayfs via `io.containerd.snapshotter.v1`; systemd cgroup v2 | recipe fields |
| Security options | `name=seccomp,profile=builtin`, `name=cgroupns` | builtin seccomp required |
| Runtimes canonical SHA-256 | `b480bc96...c4a5d1` (runc 1.4.3, libseccomp 2.5.5) | sealed into seed |
| Kernel | 6.6.87.2-microsoft-standard-WSL2 | 6.6.87.2 |
| Provider Id / RepoDigest | `sha256:c11befa8...81759`, single matching digest | `PROVIDER_ID` |
| amd64 platform manifest | `34e56b46...`, `Available: true`, content 10,469,582,159 B, **`ImageData.Size.Unpacked` 18,930,790,400 B** | `PROVIDER_PLATFORM_MANIFEST` |
| arm64 manifest | unavailable, 0 B | never selected |
| Provider size / RootFS canonical SHA-256 | 10,469,582,904 B / `1e0fe0c4...7ebfd981` (47 layers) | sealed into seed |
| Provider top layer chain ID (computed from the 47 diff IDs) | `sha256:583abc9004877e79fd0f5d47e4c7cff085b8538fdcbff0c070e044bdb0b43c1a` | P0 snapshot key |
| Provider `Config.Volumes`, Healthcheck | null, null | null/empty required |
| Provider env keys | 60, canonical sorted SHA-256 `6785bc7c...8b1db9` | all overridden |
| Containers (all states) | 0 | |
| Physical free | C: 108,318,408,704 B; E: 167,261,798,400 B | C floor below |
| journald on-disk | 799.5 MiB | delta measured per run |

Ubuntu's `ext4.vhdx` (non-sparse, so growth is never returned) and the native
Docker data root inside it are physically on C:. C: free is the binding
capacity. The ext4 `df` value (about 713 GB available) is virtual.

## 2. Pre-run guards (refreshed before every container create)

**P0, committed-snapshot proof (user-run, root, read-only).** The manifest's
`Unpacked` size is image metadata that can survive missing layer data, so it
does not prove that a committed overlayfs snapshot exists. Create by ID
cannot pull, but it could unpack about 18.9 GB. Before B1, and again before
C1, the user runs these commands, and their output is retained verbatim:

```bash
sudo ctr -n moby snapshots --snapshotter overlayfs info sha256:583abc9004877e79fd0f5d47e4c7cff085b8538fdcbff0c070e044bdb0b43c1a
```

```bash
sudo ctr -n moby snapshots --snapshotter overlayfs ls
```

The output must show `Kind: Committed` for that chain ID. If it is absent,
not committed, or the command cannot be run, the plan stops. Nothing in this
plan removes or prunes images or snapshots.

**Per-create guards.**
- **Identity, exact match:** engine ID, server version, runtimes hash,
  security options, kernel, provider Id/RepoDigest/RootFS/Size/Volumes and
  env keys, and the amd64 manifest `Available: true` with `Unpacked`
  18,930,790,400. This is consistent with P0, not a substitute for it.
- **Capacity, in the owner's own inequality:** `statvfs("/mnt/c")` free
  (`f_bavail * f_frsize`, the reading `_compiler_floor_facts_v1` uses) >=
  `c_bytes` + `additional_disk_upper_bytes` (43,486,543,872 + 134,217,728,
  that is 40 GiB + 640 MiB). The cumulative charge (section 5) must also stay
  <= 512 MiB.
- **Containers:** zero running, and the all-state list equal to exactly this
  plan's own earlier stopped CIDs.
- **GPU:** no GPU compute process active.

C: free changes on its own, so it is a floor, not an equality.

## 3. Component root

A fresh ext4 directory, `/home/s-a-balashov/work/vast-fixture-compiler-component-<commit>-01`
(mode 0700, never reused for another commit), holds only a minimal export of
the reviewed gate-1 commit. The export contains the compiler module, publisher,
seccomp JSON, `scripts/publication_operational_request_domain_v1.py` (the only
non-stdlib import, itself stdlib-only), the gate-1 probe module and runner, and
the fixed C sources. Every file must equal its blob at that commit (`git
ls-tree` blob ID and SHA-256), checked before and after every run. The runner
runs as `python3 -I -B` with an explicit `sys.path` for `scripts/` and the
root, and it writes no `__pycache__`. Outputs go to fresh `outputs/<run>/`
directories. Nothing is written to the PR worktree, other clones, `/mnt/*`,
Docker paths or the image store, and no image, volume or prune API is called.

## 4. Gates and stages

All runs are strictly sequential and use the 2.9 identity discipline: a fresh
nonce/name, intent persisted before create, the CID before start, one absolute
150 s deadline split 10 s prestart, 60 s work, 10 s normal close, 30 s TERM,
30 s KILL and 10 s final, and at most one TERM and one KILL. There are no
retries, relaunches or second providers. Each run has an exact expected
outcome set (causes, statuses, prefixes and closure). Any deviation,
including `OOMKilled: true` anywhere, stops the plan with originals retained.

**Gate 1 (code; reviewed with CI on its exact commit before any container).**
1. 2.9 defect fix. Containment now starts from observed state, not from
   `final`. Today a non-zero wait, or any failure before wait (for example an
   export fault), leaves `final` unset, so the owner TERM/KILLs a container
   that may already have exited, and Docker's 409 replies add timing-dependent
   causes. Fixed sequence:
   - A wait reply that carries an integer `StatusCode` counts as observed
     not-running.
   - Otherwise, containment first spends the normal-close phase on one
     identity summary plus one `wait?condition=not-running`. If `normal_end`
     is already set, this wait is bounded by `normal_end`; otherwise by
     min(now + 10 s, `deadline` − 70 s). If that bound is not after now, the
     wait is skipped and containment goes straight to TERM. There is no phase
     reset or extension, the full 30 s TERM, 30 s KILL and 10 s final
     allowances remain, and unit tests pin both cases.
   - Only a container still running after that gets the one TERM and one KILL.
   - One final summary and inspect follow.
   - The class constant `_DockerClientV1.RPC_LIMIT` (currently 21) becomes
     the sealed ceiling 23: 11 normal calls, 2 normal-close containment
     calls, 8 TERM/KILL calls and 2 final calls. A failure after a failed
     wait uses at most 22.
   - RED/GREEN unit tests cover the non-zero-wait, pre-wait-failure and
     still-running paths.
2. Fixed probe module and host probe runner (`accepted_policy_fixture_compiler_probe_v1.py`).
   - The runner builds the identical `compiler_container_config_v1` config; the
     probe program is bind-mounted read-only at the same `/fixture/compiler.py`
     target. The rw-mount set therefore matches C, and only the bind source and
     label digest differ.
   - It reuses `_DockerClientV1`, `_CompilerAttachV1` and `capture_export_v1`
     framing, with the probe report as the bounded `compiler.stdout` member and
     no ELF.
   - It does NOT call `_compile_fixture_owned_v1`. It records, without
     enforcing, the effective Config/HostConfig diff, the live
     mountinfo/cgroup/namespace facts and the rw-mount hash computed exactly as
     `_compiler_process_facts_v1` does.
   - It keeps the same intent/CID/deadline/TERM/KILL discipline and its own
     closure facts.
3. Fixed C sources C1-C5, and stage D's command and reply bytes, with their
   bytes and SHA-256. They are fixed now because B1's toolchain proof records
   the headers they reach. Each source:
   - is ASCII with no NUL and at most 8 MiB;
   - starts with `#define STATE_FILE ` and has `\n#define DAEMON_ID ` within
     the first 8,192 B.

   C1's `STATE_FILE` is the relative path `"engine.state"`, resolved from
   stage D's working directory, so no source names a commit-dependent path.
   C5 is a fixed blocking-include source: `#include "/proc/self/fd/1"`.
   cc's stdout is the publisher's capture pipe, which no process writes, so
   cpp blocks reading it, memory-flat and CPU-idle, until the publisher's
   45 s deadline. Its total preprocessed output is analytically zero. B1
   measures that it is still blocked, with flat RSS.
4. Admission/seed writer. Each admission is sealed no more than 60 s before
   use and binds `physical_plan_sha256` to this file's committed blob. C runs
   pass the seed as a separate sealed qualification descriptor (component
   kind), with `component_seed: null` in the admission. Each sealed file is
   capped at 4,096 B, and the seed fits: the 60 sorted env keys take 1,133 B.
   Fixed values:
   `c_bytes` 43,486,543,872 (40 GiB + 512 MiB), `additional_disk_upper_bytes`
   134,217,728, `retained_upper_bytes` 67,108,864 (code quote 61,079,552),
   `metadata_upper_bytes` 262,144 and `project_bytes` 1,073,741,824. The
   project value is checked against virtual ext4 statvfs and is documented as
   non-binding.
5. C6 injection seam. `capture_export_v1` opens its member files through a
   module-level indirection, `_export_member_open`, whose default is the
   existing `Path.open`. Only the C6 runner replaces it, and only for the
   `engine.unaccepted` member, with a file whose first `write` raises
   OSError. C1's ELF arrives as one chunk well under 64 KiB, so a later-write
   fault would never fire.
   - Expected host classification: `export_OSError` (`extent_known` false),
     member `size_bytes` and `sha256` null, with the stdout/stderr members
     unaffected.
   - A gate-1 unit test replays this exact seam against a fake engine and
     pins the complete owner cause list, which includes the attach and
     normal-close outcomes.
   - The publisher is never faulted, and no other process-wide patch is
     used.

**B1, environment and CORE probe (1 container).** The report, at most 1 MiB,
must show:
- **Identity:** uid/gid 1000, `NoNewPrivs: 1`, `Seccomp: 2` with
  `Seccomp_filters` >= 1, and empty effective, permitted, inheritable,
  bounding and ambient capabilities.
- **Limits:** `/proc/self/limits` CORE 1/1 and FSIZE 16,777,216/16,777,216.
  cgroup `memory.max` 536,870,912, `memory.swap.max` 0, `pids.max` 32,
  `cpu.max` "100000 100000".
- **Mounts and devices:**
  - The complete mountinfo and the rw-mount hash.
  - For each rw mount: statvfs bytes and inodes, and uid-1000 writability.
  - `lo` is the only network interface; there is no `/dev/nvidia*`.
- **Environment and toolchain:**
  - The initial environment.
  - python3, cc and the helpers, loader, headers, start files, libc and
    specs it reaches: resolved paths, versions, ELF64/EM_X86_64 class and
    SHA-256.
  - Recorded from `cc -###` for C1-C5, and from `cc -E -o /dev/null` for
    C1-C4 only, never for C5. Each run's stderr goes to a byte counter only,
    so C4's 3-4 MiB of diagnostics never enter the 1 MiB report. Nothing is
    linked.
  - C5 memory slope and progress: C5 runs once as a separately bounded child
    whose preprocessed output goes to a byte counter. RSS, CPU time and
    output bytes are sampled every second, and the child is hard-killed at
    20 s. Gate 2 seals the measured slope and requires two projections from
    the sampled output rate: completion no earlier than 90 s, and RSS at
    45 s at most 256 MiB.
  - If either projection fails, C5 needs a replacement. That replacement has
    no measured slope or recorded headers, so it would need another B-type
    container outside the nine-container, 512 MiB seal. The plan then stops
    and is re-planned under review.
  - B1's 60 s work window: about 20 s for the C5 child and at most 30 s for
    everything else. If the work slips past the window, the plan stops; the
    window is never extended inside this seal.
- **Native CORE probes:** each runs in a disposable child, never PID1 or the
  inheritance parent, using raw `syscall()` with 64-bit arguments.
  - A `prlimit64(0, 4, NULL, &old)` query succeeds and reads 1/1.
  - These writes, all with resource 4 and a non-NULL new limit, return EPERM:
    - the raw `setrlimit` syscall (160) with `{1,1}` (unchanged) and `{0,0}`;
    - raw `prlimit64` (302) with the same two values;
    - raw `prlimit64` with the upper-bit alias, as the `uint64_t` value
      `4 | (1ULL << 32)`, and a non-NULL `{0,0}`;
    - glibc `setrlimit(RLIMIT_CORE)`.
  - Positive control: raw `setrlimit` on RLIMIT_NOFILE at its current value
    succeeds, so a blanket EPERM cannot pass as CORE enforcement.
  - A fork-exec child reports CORE 1/1, with Seccomp 2 and NoNewPrivs 1.
  - No probe may crash.
- **Real tmpfs enforcement:**
  - A disposable child writes 16 MiB files into `/work` until ENOSPC; this
    is the real 128 MiB byte limit, with FSIZE capping each file.
  - A second child creates empty files until ENOSPC on inodes; this is the
    real 4,096-inode limit.
  - Both run with SIGXFSZ ignored. They record `/work`'s starting contents
    (expected empty) and exact counts and statuses, then delete their files.
    - Bytes: ENOSPC, with total file data in [128 MiB − 8 KiB, 128 MiB]
      and per-file counts recorded. tmpfs charges directory pages against
      `size=`, so the eighth write may be short; eight full files are not
      required.
    - Which byte case occurred is recorded: eight full files, then ENOSPC
      on a ninth; or a short eighth write.
    - Inodes: 4,095 entries minus any existing ones, then ENOSPC.
    - Everything stays inside the 512 MiB memory limit.
  - This proves the tmpfs limits at kernel level. The publisher's own
    handling of ENOSPC remains covered only by unit tests.
- **Host side:** reads `/proc/<pid>` mountinfo, cgroup and namespace facts,
  as the 2.9 owner does.

Gate B1→B2 requires every expected value to be observed exactly.

**B2, bad-ABI rejection (1 container).** cc builds two ELF64 `-nostdlib -static`
inline-assembly probes in `/work`: an x32 `getpid` (`0x40000000 | 39`) and an
i386 `int 0x80` getpid. Docker mounts `HostConfig.Tmpfs` `/work` `noexec` by
default, and the config stays identical, so each built image is copied into
a `memfd_create` file and run with `fexecve`. The profile allows
`memfd_create` and `execveat`, and B1 records `vm.memfd_noexec` and `/work`'s
effective flags. Each runs as a separately bounded child (2 s), after
confirming CORE 1/1 with the NULL `prlimit64` query. No write is attempted,
since B1 shows writes are EPERM.

Expected outcomes:
- **i386 and x32:** each wait status is exactly 0x1f (SIGSYS, no core flag),
  as a reaped fatal bad-arch status. Both reviewers now agree from primary
  sources:
  - libseccomp 2.5.5 `_gen_bpf_arch`, in the x86_64-only filter, jumps any
    `nr >= 0x40000000` (except -1) to the bad-arch action before any rule or
    the ERRNO default runs, and `act_badarch` is KILL;
  - runc 1.4.3 never overrides the bad-arch action;
  - `int 0x80` reports the foreign `AUDIT_ARCH_I386`.

  Any other outcome stops the plan and requires a specification amendment.
  That includes an x32 child that sees `-EPERM` (fixed exit 3), `-ENOSYS`
  (fixed exit 5), or its pid back (exit 4; `CONFIG_X86_X32_ABI=y`), an exec
  failure (exit 127), and a recorded `memfd_error`.
- **dmesg** (`dmesg_restrict` = 0): for each SIGSYS death the expected delta
  is one `has RLIMIT_CORE set to 1` line and one `Aborting core` line (pipe
  `core_pattern`, recorded), with no pipe-helper execution and an unchanged
  Windows WSL crash-directory listing.
- **Audit lines** (`audit_enabled` = 0 at boot, journald not collecting
  audit):
  - One seccomp `type=1326` (`sig=31`) record is expected per death. Because
    kauditd prints it through the shared `printk_ratelimit()`, a missing one
    becomes a gate-2 explanation item, not an automatic stop.
  - A `type=1701` record should be absent; it is allowed only if audit
    turns out to be enabled.
- **Emitted filter:** reading it (`PTRACE_SECCOMP_GET_FILTER`) needs
  CAP_SYS_ADMIN, which is unavailable here. Gate 2's explanation therefore
  rests on the cited sources together with the observed statuses, and says
  so.

**B3, host container TERM/KILL (1 container).** The probe ignores SIGTERM
and sleeps past the 60 s work window. The runner sends one Docker
`kill?signal=SIGTERM`, waits the 30 s grace, then sends one `SIGKILL`.
Expected:
- both kill replies (204) recorded;
- the bounded 30 s TERM wait times out, adding the client wait-deadline cause;
- after KILL, wait status and container ExitCode 137;
- a reaped, empty cgroup with the init process absent, and no 409. This physically exercises the
Docker kill/wait path. The owner's own containment code still runs only in unit
tests (its containment cannot be reached physically through the bounded
publisher), and is carried forward as a physically unqualified remnant.

**Gate 2 (reviewed, with CI, before C).** From the B1-B3 originals:
- The sealed component seed descriptor contains the observed engine, provider,
  env keys and `mounts_sha256`, and the `baseline`, `toolchain`, `abi`,
  `limits` and `closure` proof hashes of the retained B reports.
- The N3 amendment accepts only the effective Config and HostConfig
  differences B1 actually observed from Docker's create merge (for example
  inherited image labels, `Volumes` null versus `{}`, `CapAdd` [] versus
  null). Every other field stays exact, with tests and CI.
- If B shows any Decision15 assumption to be false, stop and amend the
  specification. Examples: a CORE write succeeding, x32 or i386 surviving,
  an unexpected rw mount, swap above 0, or a core helper run.

**C, publisher runs via `_compile_fixture_component_v1` (6 containers).**

| Run | Input or injection | Expected original outcome |
|---|---|---|
| C1 | tiny valid C answering one fixed command | rc 0; authenticated ELF64/x86-64 export bound to its member; normal closure; `accepted` false (component path) |
| C2 | invalid C | compiler rc != 0, raw stderr; publisher causes; ExitCode 1; `owner_wait_status`; no TERM/KILL and no 409 (gate-1 fix); no ELF; exact cause list from the gate-1 review |
| C3 | `static const char a[20 << 20] = {1};` (kept at -O0, in .rodata) | real FSIZE: `as` dies by SIGXFSZ (default action Core) or exits non-zero on EFBIG; compiler rc != 0; no ELF. dmesg may hold only that process's `has RLIMIT_CORE set to 1` and `Aborting core` lines, plus one `type=1701` (`sig=25`) record if audit is enabled |
| C4 | about 40,000 `#warning` lines (about 0.45 MiB source, about 3-4 MiB diagnostics) | real 1 MiB stderr overflow with exact prefix and observed/discarded counts, or an explicitly unknown remainder; compiler rc in {-15, 1, 0} (no `main`, so a finished link fails); no ELF |
| C5 | gate-1 fixed blocking-include source, slope and progress sealed at gate 2 | cc still running at publisher start+45 s; real in-container publisher deadline (cc TERMed there); publisher refusal; ExitCode 1; `forced` false. A cc that finishes earlier, or any `OOMKilled`, stops the plan |
| C6 | C1 source with the gate-1 `_export_member_open` first-write fault | real container lifecycle with a labelled synthetic host fault. The publisher exits normally, so the normal-close wait observes it stopped: no TERM/KILL. Expected: `export_OSError` (extent unknown), ELF member `size_bytes`/`sha256` null, the gate-1-pinned full cause list, closure facts, no ELF. Proves no runtime enforcement |

Receipt persistence has no runtime enforcer to qualify. Its labelled synthetic
faults stay in the existing unit tests and are not run physically, and they
are listed as a synthetic-only remnant.

**D, host ABI execution (no container).** Copy the C1 ELF to a fresh 0700
D directory, verify its SHA-256, and chmod the copy to 0700; the original
stays retained. Run it once from the gate-1 runner with:
- RLIMIT_CORE 1/1 and FSIZE 1 MiB set in the child before exec, and verified;
- the D directory as working directory, so `engine.state` resolves there;
- the gate-1 fixed command on stdin, a 4 KiB capture bound and a 10 s
  deadline;
- an owned new session;
- the ELF's interpreter path recorded (glibc 2.35 build on the 24.04 host).

Expected: the exact fixed reply, rc 0, no WCOREDUMP, and an unchanged dmesg
and crash-directory listing.

## 5. Finite peak and retention

| Item | Sealed bound |
|---|---|
| Component root export | <= 1 MiB |
| B1-B3 retained originals (3 x 2.35 MiB) | <= 7.5 MiB |
| C1-C6 retained originals (6 x 64 MiB) | <= 384 MiB |
| D capture and copy | <= 1 MiB |
| Per-container daemon/runtime growth (9 containers) | measured, <= 4 MiB each planned |
| bbolt/meta step growth and journald (including audit/"Aborting core" lines) | <= 80 MiB slack |
| **Total additional physical disk** | **512 MiB** |
| Memory | 512 MiB cgroup (includes 128 MiB `/work`) plus the runner |
| CPU / GPU | 1 CPU / none |
| Wall time | <= 9 x 150 s + 10 s, serialized |

Measurement method: no root is needed. Before and after each run, record:
- `df -B1 /` used bytes and Windows C: free;
- `/containers/<id>/json?size=1` (`SizeRw`, `SizeRootFs`);
- `/system/df`;
- `journalctl --disk-usage`;
- the output directory byte total.

Charge the largest of three values:
- the ext4-used growth;
- the retained-output total plus `SizeRw`;
- the Windows C: free decrease over the run.

Net ext4 growth is not an upper bound for a non-sparse VHD, because blocks
that are allocated and then freed still grow it. The C: delta also includes
unrelated host activity, so it can only overcharge. If cumulative charge exceeds 512 MiB, or a single container exceeds
16 MiB of non-output growth, stop and re-plan before the next run.

## 6. Remnants and what stays open

All originals are retained in the component root: requests, replies, raw
channels, statuses, intents, CIDs, receipts, guard and measurement records,
dmesg/journal deltas and failure records. The 9 stopped containers (no logs,
RestartPolicy `no`) and their daemon metadata are retained. Removing them or
the root needs a separate reviewed action.

Every remnant is carried into whole 1.5 accounting, and the affected
integrated diff is re-reviewed then. That includes:
- the root, the stopped containers and the measured C: growth (never
  returned by the non-sparse VHD);
- the physically unqualified owner containment path, the synthetic-only
  export/receipt faults, and the publisher's own ENOSPC handling (B1
  qualifies only the kernel tmpfs limits).

Component success establishes provider facts only. It is not usable-fixture
admission and dispatches no standalone, cold-order or genuine reader.
`compile_fixture_engine_v1` stays refused until whole 1.5 is accepted. The
custody fixture's host `cc` wiring is unchanged. The 227 protected images,
historical roots and original evidence are untouched.

## 7. V1 review findings and dispositions

| V1 finding | Disposition in V2 |
|---|---|
| Unpack/snapshot not pre-bounded (both) | Read-only proof that the amd64 snapshot is unpacked; per-create exact `Available`/`Unpacked` guard; journald, bbolt and ext4/C: deltas sealed (sections 2, 5) |
| C5 not a host 60 s TERM (both) | C5 is now the in-container publisher deadline; host TERM/KILL physically exercised by B3; owner containment carried as a remnant |
| Non-zero exit triggers containment of a stopped container, 409 (Claude) | Gate-1 code fix with tests; C2-C5 expectations derived from the code |
| Gate 1 cannot reuse the owner and also learn `mounts_sha256` (both) | The probe runner records and never enforces, and never calls the owner; gate 2 seals the seed; C is the first owner call |
| Inode/export/receipt failures not staged (grok) | Real tmpfs byte and inode limits in B1; C6 labelled synthetic export fault inside a real lifecycle; receipt fault stays synthetic in unit tests |
| Stage D crash policy, file mode, `STATE_FILE` (Claude) | Child CORE 1/1 + FSIZE, hash-verified 0700 copy, `STATE_FILE` in the D directory, dmesg/WCOREDUMP checks |
| "Any drift stops" unworkable (Claude) | Exact identity, capacity floor, container list equal to own prior CIDs |
| Code floor versus plan floor; virtual `project_bytes` (Claude) | Exact admission values fixed (gate 1, item 4) |
| 8 MiB per container not credible; no method (Claude) | Non-root measurement method, 80 MiB slack, per-container 16 MiB stop |
| B1/B2 probe details (both) | Raw syscalls in disposable children, full expected-value list, ELF64 `-nostdlib` asm, exact 0x1f, dmesg/crash-directory checks |
| C3 zero initializer, source header rule, seed embedding size, `baseline` proof, HostConfig normalizations, runner `-B` (both) | All pinned in gate 1/2 and the C table |

## 8. V2 review findings and dispositions

| V2 finding | Disposition in V3 |
|---|---|
| `Unpacked` metadata is not a committed-snapshot proof (grok) | P0: user-run read-only `ctr` proof of the computed chain ID, before B1 and C1 |
| B2 dmesg cannot be only "Aborting core" (Claude); C3 line kind (grok) | Exact per-SIGSYS line set (audit 1326, RLIMIT_CORE, Aborting core); C3 allows only its own two lines or none |
| x32 outcome: reviewers split between SIGSYS and EPERM | Either exact rejection is accepted and recorded; a returned pid stops |
| C5 cannot be pinned before any container; `-E` would run it in B1 (both) | C5 bytes fixed at gate 1; `-###` only; separately bounded 20 s slope child in B1; gate 2 seals the slope |
| C6 timing-dependent; injection unnamed (both) | Gate-1 containment begins with a bounded normal-close wait; `_export_member_open` seam; exact cause |
| `STATE_FILE` refers to its own commit (Claude) | Relative `engine.state` from D's working directory |
| CORE probe "at 0" ambiguous; no positive control (grok) | Resource 4, non-NULL limits, explicit values; NOFILE positive control |
| Section 2 floor differs from the code inequality (grok) | Code inequality on every create, plus cumulative 512 MiB |
| B3 wait timeout cause; SIGKILL not recordable inside (both) | Listed; kill replies and 137 recorded |
| tmpfs counts depend on `/work` contents; SIGXFSZ in children (Claude) | Starting contents recorded, SIGXFSZ ignored, expected counts given |
| C4 rc depends on timing (Claude) | rc in {-15, 1, 0}; no ELF in any case |
| VHD churn not bounded by net ext4 growth (Claude) | Also charge the Windows C: free decrease |
| Receipt synthetic wording; publisher ENOSPC handling (Claude) | Reworded as a synthetic-only remnant; ENOSPC handling stays unit-only |
| Seed size and `component_seed` (grok) | `component_seed: null`; the seed fits the 4,096 B cap |

## 9. V3 review findings and dispositions

| V3 finding | Disposition in V4 |
|---|---|
| C6 fault never fires on a one-chunk ELF; wrong cause classifier (both) | First-write fault; expected `export_OSError` with null size/hash; full cause list pinned by a gate-1 replay test |
| B1 "eight full 16 MiB files" impossible (tmpfs directory pages) (grok) | ENOSPC with data in [128 MiB − 8 KiB, 128 MiB]; counts recorded |
| Containment wait could reset a phase (Claude) | Bounded by `normal_end` or min(now + 10 s, deadline − 70 s); unit test |
| C5 replacement has no measurement; C5 must outlast 45 s (both) | Progress and slope projections at gate 2; replacement means stop and re-plan; early finish stops |
| B1 `-E` of C4 stderr volume (Claude) | stderr to a byte counter only |
| `type=1701` core audit line (grok) | Allowed in B2 and C3 |
| Alias spelling (grok) | `uint64_t` `4 | (1ULL << 32)` |
| `RPC_LIMIT` class constant (grok) | Gate 1 changes 21 to 23 |
| Capacity reading (grok) | `statvfs("/mnt/c")` as in the code |
| Publisher ENOSPC remnant (grok) | Listed in section 6 |
| x32 SIGSYS vs EPERM (still split) | Superseded in V5 (section 10): SIGSYS only |

## 10. V4 review findings and dispositions

| V4 finding | Disposition in V5 |
|---|---|
| x32 must be SIGSYS only (grok BLOCK, now agreeing with the Claude subagent) | Exact 0x1f for x32 and i386; EPERM or pid stops and amends |
| B2 "re-assert CORE" conflicts with B1 EPERM writes (grok) | Confirm by the NULL `prlimit64` query only |
| B1 time slip (grok) | Stop; no window extension |
| Emitted filter unreadable without CAP_SYS_ADMIN (Claude) | Gate 2 rests on sources plus statuses, and says so |
| Rate-limited 1326 line; 1701 absent with audit disabled (Claude) | A missing 1326 is a gate-2 explanation item; 1701 allowed only if audit is enabled |
| Containment wait with no time left (Claude) | Skipped, straight to TERM; unit test |
| tmpfs mechanism doubt (Claude) | The accepted range covers both cases; the case is recorded |

## 11. V6 amendment (C5 workload only)

The reviewers showed that any CPU-bound C5 built from macro or include
expansion grows GCC's line maps (`-ftrack-macro-expansion=2`) and risks
`OOMKilled` before the 45 s publisher deadline. V6 therefore replaces it
with a blocking include of cc's own captured stdout pipe. Everything else is
unchanged, including stop on early finish, stop on `OOMKilled`, the 20 s B1
slope child with output counted, and the gate-2 projections.

Host-only pre-checks were run with gcc 13.3 on the WSL host, not in any
container:
- With stdout a pipe, cc blocks until killed. With stdout `/dev/null`, it
  finishes immediately.
- The probe program's 20 s slope child recorded: RSS flat at 11,200 KiB, 0
  CPU ticks, 0 output bytes, and still running when killed at 20 s.

Both projections (completion no earlier than 90 s, RSS at 45 s at most
256 MiB) hold by construction. The actual container measurements in B1
remain required.

## 12. V7 gate-1 review corrections

- **B2 execution:** `/work` is `noexec` under Docker's tmpfs defaults, so the
  probes run from an executable memfd via `fexecve`. A host-only check (no
  container, no seccomp) showed both memfd-executed probes running and
  returning the pid (exit 4), as designed for an unfiltered host.
- **x32 exit codes:** -EPERM gives 3, -ENOSYS 5, a pid 4. Only wait status
  0x1f passes.
- **C4 sizes:** the pinned C4 source is 1,360,072 B. On the host, `cc -E` of
  C4 was killed at B1's 10 s bound after about 1.49 MB of diagnostics. B1
  therefore expects its C4 `-E` run to be killed at that bound, with stderr
  counted only. In stage C, C4 most likely ends with compiler rc -15, which
  is already in the expected set.
- **Measurements:** the probe runner itself records non-root before/after
  measurements: C: free, ext4 used, `journalctl --disk-usage`, and the
  container's `SizeRw`/`SizeRootFs`. Stage C/D runners must do the same.
- **P0 output:** the runner validates the `ctr ... info` JSON for the
  committed chain. The user-run `snapshots ls` output is retained alongside
  it by the operator.
- **Operator notes:**
  - With the owner's handlers installed, a SIGINT or SIGTERM to the runner
    is recorded, and the run continues to its bounded deadline (at most
    150 s) with full containment.
  - `cc1 --version` writes to stderr, so gate 2 reads that field.
  - `memfd_create` passes `MFD_EXEC` explicitly.
- **C5 projection:** a sampled output rate of 0 B/s means "never
  completes", which satisfies the 90 s projection. The slope child is capped
  at min(20 s, the probe's remaining in-container budget − 3 s), and a short
  window is recorded as not a full window. The publisher's cc driver passes
  its stdout pipe to cc1 as fd 1, as in the host `cc -c` check, so C5 blocks
  the same way there.
- **P0 format:** `ctr ... snapshots info` prints JSON; the runner requires
  `Name` equal to the chain ID and `Kind` "Committed".
- **GPU guard:** an unavailable `nvidia-smi` query refuses as unprovable
  (`probe_gpu_query_unavailable`), separately from a busy GPU.
