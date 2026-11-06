# Fixture Compiler Component Admission Plan V1 (task 2.10)

Status: planning only. No container, probe, compile or host ELF execution has
run or is authorized by this draft. It needs independent review, mandatory
checks on its exact pushed commit and a recorded delegated AGENT approval in
PR #9 before gate 1 work below. Decision15 (approved at
`c8362f290be986a60403eac306375e26fac43f39`) governs the boundary; task 2.9
implementation is final at `70466266`. Nothing here closes whole 1.5, 2.8,
5.3 or any genuine cohort, and nothing grants Q1, storage, image or provider
authority.

## 1. Fresh read-only observations

Captured 2026-10-15T21:29:14Z from the WSL Ubuntu distribution as uid 1000
(docker group), with raw replies retained in `observations-01/`:

| Fact | Observed | Decision15 / 2.9 pin |
|---|---|---|
| Engine ID | `1e493309-3767-45fb-9078-05b838bdfd80` | same |
| Docker server / API / min API | 29.7.2 / 1.55 / 1.40 | 29.7.2, min <= 1.55 <= API |
| Storage driver, cgroup | overlayfs, systemd, cgroup v2 | recipe fields |
| Security options | `name=seccomp,profile=builtin`, `name=cgroupns` | builtin seccomp required |
| Runtimes canonical SHA-256 | `b480bc96...c4a5d1` (runc 1.4.3, libseccomp 2.5.5) | sealed into seed |
| Kernel | 6.6.87.2-microsoft-standard-WSL2 | 6.6.87.2 |
| Provider Id / RepoDigest | `sha256:c11befa8...81759`, single matching digest | `PROVIDER_ID` |
| Provider size / RootFS canonical SHA-256 | 10,469,582,904 B / `1e0fe0c4...7ebfd981` (47 layers) | sealed into seed |
| Provider `Config.Volumes`, Healthcheck | null, null | null/empty required |
| Provider env keys | 60 keys, canonical sorted SHA-256 `6785bc7c...8b1db9` | all overridden |
| Containers (all states) | 0 | no competing work |
| Physical free | C: 108,318,408,704 B (100.88 GiB); E: 167,261,798,400 B | C floor 40 GiB |

The provider is already present: no pull, export or image action is needed or
allowed. Ubuntu ext4 and Docker data are physically backed by C:, so C: free
is the binding capacity. These observations are refreshed immediately before
every run below; any drift stops the plan.

## 2. Component root

A fresh ext4 directory, `/home/s-a-balashov/work/vast-fixture-compiler-component-<commit>-01`,
holds only a minimal export of the reviewed commit, not a 6.7 GB source clone:
`tests/fixtures/accepted_policy_fixture_compiler_v1.py`,
`tests/fixtures/accepted_policy_fixture_compiler_publisher_v1.py`,
`tests/fixtures/accepted_policy_fixture_compiler_seccomp_v1.json`,
`scripts/publication_operational_request_domain_v1.py` (the only non-stdlib
import, itself stdlib-only), and the gate-1 probe module and runner recipe.
Each exported file must equal its blob at the reviewed commit (`git ls-tree`
blob ID and SHA-256) before and after every run; the root is created with
mode 0700 and never reused for another commit. Outputs go to fresh
`outputs/<stage>/` subdirectories inside it. Nothing is written to the PR
worktree, other clones, `/mnt/*`, Docker paths or the image store.

## 3. Stages and gates

All runs are strictly sequential, one container at a time, with zero other
running containers and no GPU workload observed immediately before each run.
Each run uses a fresh nonce/name, persists creation intent before create and
the CID before start, and has one absolute 150 s owner deadline with the 2.9
phase split (10 s prestart, 60 s work, 10 s normal close, 30 s TERM, 30 s KILL,
10 s final). At most one TERM and one KILL; no retry, relaunch or second
provider. Any refusal not listed as an expected outcome stops the plan with
originals retained.

**Gate 1 (before any container).** Implement and independently review, with CI
on its exact commit, a fixed probe module that runs inside the identical
`compiler_container_config_v1` HostConfig (same profile, limits, tmpfs, user,
env, network/IPC none). It is bind-mounted read-only at the same target
`/fixture/compiler.py`, so the entrypoint and rw mount set are unchanged and
only the bind source and its label digest differ. Its host side reuses the 2.9
`_DockerClientV1`, `_CompilerAttachV1`, `capture_export_v1` framing and owned
lifecycle, with the probe report carried as the bounded `compiler.stdout`
member and no ELF. The runner recipe seals each admission no more than 60 s
before use from refreshed facts, binding `physical_plan_sha256` to this
file's committed blob.

**Stage B1, environment probe (1 container).** Reports, bounded at 1 MiB:
uid/gid 1000, `NoNewPrivs: 1`, `Seccomp: 2`, empty effective/bounding
capabilities, `/proc/self/limits` (CORE 1/1, FSIZE 16777216/16777216), cgroup
`memory.max` 536870912, `memory.swap.max`, `pids.max` 32, `cpu.max` for one
CPU, the complete `/proc/self/mountinfo`, and the rw-mount canonical SHA-256
computed exactly as `_compiler_process_facts_v1` does. It also reports the
initial environment and the resolved paths, versions, ELF64/EM_X86_64 class
and SHA-256 of python3, cc and the reached compiler helpers, loader, headers,
start files, libc and the specs output. Native CORE probes: a `prlimit64` CORE
query with a NULL new limit succeeds; CORE writes through `setrlimit` and
`prlimit64`, at the same value, a lower value and the upper-bit resource
alias, all fail with EPERM; and a fork-exec child reports inherited CORE 1/1.
None of these probes may crash. In parallel the host reads
`/proc/<pid>/mountinfo`, cgroup and namespace facts as the 2.9 owner does.

**Stage B2, bad-ABI rejection (1 container).** Inside `/work`, cc builds two
tiny static probes: an x32 syscall (`__X32_SYSCALL_BIT | getpid`) and an i386
`int 0x80` getpid. Each runs as a separately bounded child (2 s each) and is
expected to die by SIGSYS under the established CORE policy, with no core
helper and an exact reaped status. A child that returns normally is a
seccomp failure and stops the plan. These negative cases create no
usable-fixture evidence.

**Gate 2 (between B and C).** From B1/B2 originals, independently reviewed:
the sealed component seed (`vast_fixture_compiler_component_seed_v1`) with
the observed engine, provider, env keys, `mounts_sha256`, and toolchain, ABI,
limits and closure proof hashes; and the 2.9 N3 disposition. That is a narrow
reviewed amendment that accepts only the effective-Config differences
actually observed from Docker's create merge (for example inherited image
labels, `Volumes` null versus `{}`), keeps every other field exact, and is
covered by tests and CI. If B shows any Decision15 assumption to be false,
for example a CORE write succeeding, x32 surviving or an unexpected rw mount,
stop and amend the specification instead.

**Stage C, publisher component runs via `_compile_fixture_component_v1`
(5 containers).**

| Run | Source | Expected original outcome |
|---|---|---|
| C1 | tiny valid C answering one fixed command | compiler rc 0, authenticated ELF64/x86-64 export, normal closure |
| C2 | syntactically invalid C | compiler rc != 0, raw stderr retained, no ELF |
| C3 | 20 MiB initialized static array | real FSIZE enforcement (SIGXFSZ/EFBIG), no ELF |
| C4 | source yielding > 1 MiB of diagnostics | stderr overflow with exact 1 MiB prefix, no ELF |
| C5 | bounded slow compile exceeding the 60 s work window | real deadline TERM (KILL if needed), forced, no ELF |

Each C source is generated under the 8 MiB source bound. Its exact bytes and
SHA-256 are fixed in the gate-2 recipe before admission. Synthetic I/O,
clock and export faults stay in the existing unit tests and are not repeated
physically. They are labelled synthetic and prove no runtime enforcement.

**Stage D, host ABI execution (no container).** Execute the C1 ELF on the host
once with the fixed command on stdin, a 4 KiB capture bound, a 10 s deadline
and an owned process group. Expect the exact fixed reply and rc 0.

## 4. Finite peak and retention

| Item | Bound |
|---|---|
| Component root code export | <= 1 MiB |
| B1/B2 retained originals (2 runs x (1 MiB report + 1 MiB stderr + 64 KiB frame + 256 KiB RPC/metadata + 32 KiB control)) | <= 4.75 MiB |
| C1-C5 retained originals (owner quote 3 x 16 MiB + 8 MiB source + 2 MiB + 256 KiB, sealed at 64 MiB per run) | <= 320 MiB |
| D capture | <= 64 KiB |
| Docker daemon metadata and per-container snapshot, runtime-generated files (7 stopped containers, log driver none), sealed at 8 MiB each | <= 56 MiB |
| Total additional physical disk, sealed | 512 MiB |
| Memory | 512 MiB cgroup (includes 128 MiB `/work` tmpfs) plus the host runner |
| CPU / GPU | 1 CPU / none |
| Wall time | <= 7 x 150 s + 10 s, serialized |

Each admission requires physical C: free >= 40 GiB + 512 MiB at sealing time,
measured from the Windows volume, not the WSL virtual size. The per-run
`retained_upper_bytes` is 64 MiB and `additional_disk_upper_bytes` 128 MiB.
After stage B the measured daemon metadata and snapshot growth per container
replaces the 8 MiB planning bound; if it exceeds the bound, stop and re-plan.

## 5. Retention, remnants and what stays open

All originals (requests, replies, raw channels, statuses, intents, CIDs,
receipts and failure records) are retained in the component root. The seven
stopped containers and their daemon metadata are retained, not removed.
Removing them, or the root, needs a separate reviewed action. Every remnant,
including the root, stopped containers, measured daemon growth and outputs,
is carried into whole 1.5 accounting, and the affected integrated diff is
re-reviewed then. Component success establishes provider facts only. It is
not usable-fixture admission and does not dispatch any standalone, cold-order
or genuine reader. The usable `compile_fixture_engine_v1` path stays refused
until whole 1.5 is accepted. The custody fixture's host `cc` wiring is
unchanged by this plan. The 227 protected images, historical roots and
original evidence are untouched.
