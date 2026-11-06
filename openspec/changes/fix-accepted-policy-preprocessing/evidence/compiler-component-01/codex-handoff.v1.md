# Codex context handoff: PR #9, Claude Code session of 2026-10-15/16

- **Change:** `fix-accepted-policy-preprocessing`
- **Branch:** `codex/fix-accepted-policy-preprocessing`
- **Draft PR:** https://github.com/lordcoudy/VAST/pull/9
- **Worktree:** `C:/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST`
- **Handoff written at head:** `2fec1cff3eda6f0caf68fdf537b01e7de0a3970c`; CI is green on every
  implementation commit.

The user stopped the earlier Codex chat. A Claude Code session then took over
the same worktree and branch and continued under AGENTS.md: delegated AGENT
self-approval after independent review, CI at the exact commit, and the
227-image stop. This file is the full context. The repository documents are
authoritative; this file only indexes them.

## 1. What changed in this session (all in PR #9, all CI-green)

| Item | Result | Key commit | PR #9 comment |
|---|---|---|---|
| Task 1.23, Decision16 spec | Independently reviewed (CLEAR_WITH_NOTES, N1–N4 dispositioned). CI attempt 1 failed on an unrelated flaky test; attempt 2 passed. Delegated approval | `06c965fb` | 6200421578 |
| Task 2.9, fixture compiler | WIP snapshotted and finished. Claude and grok both BLOCK at `87feaf2d`; fixed; re-reviews CLEAR_WITH_NOTES. 164 tests at that point | final `70466266` | 6200572771 |
| Task 2.11, bounded standalone reader | TDD. Claude and grok both BLOCK at `036bc039` (closure race, leaks, late persistence, drain); fixed; CLEAR_WITH_NOTES | logic `2543819f`, final `16dbaa2a` | 6202559098 |
| Task 2.10 plan | V1–V4 BLOCKed by both reviewers; V5 cleared by both | `efa59e92` | 6204153691 |
| Task 2.10 gate 1 | Gate-1 code: containment from observed state with `RPC_LIMIT` 23; C6 seam; pinned C1–C5 sources and D bytes; seed/admission writers; probe program and runner; plan V6 (C5 = blocking include) and V7 (memfd exec). Claude BLOCK → CLEAR_WITH_NOTES; grok CLEAR_WITH_NOTES | `8c08cd30` | 6210515683 |
| P0 | The user ran the root `ctr` commands. The provider chain `sha256:583abc90…b43c1a` is Committed | evidence `p0-01/` | (in 6212407700) |
| B1 → gate | B1 ran. One deviation (glibc `setrlimit` recorded CPython's ValueError mapping of EPERM). Both reviewers: PROCEED | `e39dbea2` | 6212407700 |
| B2 → gate | B2: x32 and i386 SIGSYS 0x1f. D1 (`print-fatal-signals`) and D2 (`dxg` boot noise). Both reviewers: PROCEED; B3 values pinned | `2453ab9e` | 6213031979 |
| B3 | Matched all pinned values. D3: concurrent unattended systemd upgrade logged two journald lines; **pending gate 2** | `2fec1cff` | 6213112912 (status) |

`tasks.md` checks 1.23, 2.9 and 2.11. Task 2.10 stays open; its sub-notes
sit under the 2.10 row.

## 2. Task 2.10 state: authoritative documents

All are in `openspec/changes/fix-accepted-policy-preprocessing/evidence/compiler-component-01/`.

- **Plans:** `component-admission-plan.v7.md` is current (V5 approved; V6 and V7
  amendments approved with gate 1). V1–V6 are retained history; never edit
  them.
- **Observations:** `observations-01/` holds the raw Engine API GET replies.
  `p0-01/` holds the P0 proof.
- **Runs:** `b1-01/`, `b2-01/` and `b3-01/` each hold a README, the
  byte-exact `outputs/`, `run-records/` and `originals.sha256`. They list
  component-root paths: `runs/` maps to `run-records/` because the repo
  `.gitignore` ignores `runs/`. Host dmesg dumps are not committed; only
  hashes and deltas are.
- **Gate dispositions:** `b1-01/gate-b1-b2-disposition.v1.md` and
  `b2-01/gate-b2-b3-disposition.v1.md`.
- **Component root (ext4, mode 0700, seven blob-verified files at
  `8c08cd30`):**
  `/home/s-a-balashov/work/vast-fixture-compiler-component-8c08cd30f2355a26b2e7a31b53e6f268acafda29-01`.
  It holds `outputs/B1..B3`, `runs/`, and `p0/p0-info.json`.
- **Retained stopped containers:** never remove or prune them.
  - B1 `4df593e12ca362e69f0594b2035197335f335d3ceae3c71894b31db9f197a09f`
  - B2 `9b5c396109909a8a091a0fc6bb6529f887233df77ab314435ce85ab05e22fbc5`
  - B3 `90f8ebb69bd83cbb02067a831cc2ace5efe78fc6b568a665bd93333d7b4b6e87`
- **Container budget:** three of the nine planned containers are used. Six
  remain, and all six are for C1–C6. Do not re-run B stages; that breaks the
  seal.
- **Charge ledger:** 11,890,688 B cumulative, against the 512 MiB seal.
  - B1: 7,430,144 B
  - B2: 331,776 B
  - B3: 4,128,768 B

  Per-container stop: 16 MiB of non-output growth.

## 3. Next: gate 2 (must be independently reviewed, CI-green and approved before any C/D container)

Every input below comes from the B1–B3 originals.

1. **Component seed.** Seal it with
   `accepted_policy_fixture_compiler_component_v1.component_seed_v1` /
   `seal_json_v1` (kind `vast_fixture_compiler_component_seed_v1`, ≤ 4096 B).
   - engine: driver overlayfs, cgroup systemd, the security options, runtimes
     `b480bc96…`;
   - provider: RootFS `1e0fe0c4…`, size 10,469,582,904;
   - the 60 sorted env keys;
   - `mounts_sha256` `3da03bbba33c8c86f2935cfcfcc07f16bb4020337d8d130deb5d8595851ff470`;
   - proof hashes (`baseline`/`toolchain`/`abi`/`limits`/`closure`) over the
     retained B reports;
   - admissions keep `component_seed: null`.
2. **N3 owner amendment** (`tests/fixtures/accepted_policy_fixture_compiler_v1.py`,
   `inspect_owned`, about lines 1536–1540). Accept only what B observed:
   - `Config.Labels` may equal the requested labels plus the provider image's
     23 labels, with no key collisions;
   - `Config.Volumes` may be `{}` or `null`;
   - every other requested Config and HostConfig key stays exact;
   - CapAdd stays exact: `[]` was observed, so do not pre-accept `null`.

   Add RED/GREEN tests and keep the 2.9 tests green.
3. **F2 toolchain gap.** Hash the PIE start files actually used (`Scrt1.o`,
   `crtbeginS.o`, `crtendS.o`), `libc.so.6` and the glibc version, and cc1's
   version, without a new container. Example: read-only
   `GET /containers/{B1}/archive?path=…` on the stopped B1 container, which
   charges the ledger. Otherwise record the gap explicitly in the seed's
   `toolchain` proof. `cc1 --version` was empty on both streams.
4. **Restate C3 dmesg.** A SIGXFSZ `as` death is coredump-class, so expect
   the sig-25 "potentially unexpected fatal signal" banner, a register dump,
   "RLIMIT_CORE set to 1" and "Aborting core". `print-fatal-signals` is 1.
5. **Dispose D3** (journald restart lines from a concurrent unattended
   upgrade), and name `/dev/mqueue` (rw, uid-1000-writable, noexec) as an
   expected rw mount.
6. **Pin C1–C6 exact expected outcomes**, causes included. Derive them from
   the code as the reviewers did for B3. C2's cause list is
   `["owner_wait_status"]`. C6's is `["export_OSError", "attach_incomplete"]`,
   pinned by a test. The plan expects C4 to end with rc −15. Also write the
   C/D runners: the gate-1 approval covers only the runner pattern, so new
   runner code needs review.

After gate 2, run C1–C6 via `_compile_fixture_component_v1` and then stage D
(host ELF execution: a hash-verified 0700 copy, CORE 1/1 and FSIZE in the
child, crash-directory listings before and after). Every run is sequential
with fresh guards and needs its own exact-value evaluation. Any deviation
stops the plan for an independent disposition review.

Still open after 2.10: 2.12, which needs whole 1.5 first; whole 1.5; 2.8;
4.x; 5.x; 6.x conformance, archive and final. See `tasks.md`.

## 4. How the work was run (repeat this)

- **Two independent reviewers per gate**, both read-only in detached
  scratch worktrees (`git worktree add --detach <scratch> <sha>`; remove
  after):
  - a Claude subagent;
  - grok CLI (user-authorized):
    `grok -p "$(cat prompt.md)" --cwd <scratch-worktree> --always-approve --output-format plain --no-alt-screen`.

  Brief them with the plan section, the exact commit, raw originals, "derive
  from raw", and the verdict vocabulary. Record their verdicts, dispositions,
  CI run/job IDs and the exact SHA in a PR #9 comment. Label it "delegated
  AGENT approval, not human review".
- **Strict plan rule:** any deviation from exact expected values stops the
  run. Write a disposition document, have both reviewers rule on it, wait for
  CI on its commit, record approval, and only then continue. Never relax a
  check after the fact. Never re-run to get a clean result.
- **Python:** probe code runs in the container's Python 3.10. Check syntax
  with `ast.parse(..., feature_version=(3,10))`. Host tests run under WSL
  `python3` 3.12.3. The Windows Python 3.14 lacks pandas and `fcntl`, so many
  modules skip there; hosted CI is Linux-only.

## 5. Environment facts and pitfalls learned

- **Push:** `env -u HTTPS_PROXY -u HTTP_PROXY git push`; the proxy breaks
  GitHub. `gh` works with the same unset.
- **WSL from Git Bash:** prefix `MSYS_NO_PATHCONV=1`. WSL git cannot read the
  Codex worktree's `.git` file, so run git through Windows git and
  `wslpath`.
- **VM idling:** the WSL VM idles out between commands and boots on the next
  `wsl.exe`. Containers persist across the restart, but the boot ID changes
  and boot logging pollutes dmesg. Pre-warm about 30–40 s inside the same WSL
  session, and capture dmesg and the boot ID before and after in that same
  session. Do not run `wsl.exe` from another process during a run.
- **Kernel facts:** `kernel.print-fatal-signals=1`; `core_pattern` is
  `|/wsl-capture-crash %t %E %p %s`; only an exact `RLIMIT_CORE` of 1 stops
  the pipe helper (bash `ulimit -c 1` means 1 KiB). The crash directory is
  `%LOCALAPPDATA%\Temp\wsl-crashes`.
  - One host dump there, `…x86_64-linux-gnu-as-25.dmp`, came from this
    session's host-only C3 pre-check. It is disclosed in `b2-01/README.md`
    and left in place.
- **Unattended upgrades:** `apt-daily-upgrade.timer` runs inside WSL Ubuntu.
  It upgraded systemd mid-B3; the Docker apt origin is not allowed, so Docker
  is unaffected. Disabling it is a system setting, so the user must decide;
  it has been flagged in the PR. Every run's identity guards refuse on drift.
- **Docker defaults:** Docker mounts `HostConfig.Tmpfs` noexec by default. B2
  therefore execs from `memfd_create(MFD_EXEC)`, which the profile allows.
- **Flaky hosted test:**
  `test_backend_publication_output_transaction_production_v3…test_real_parent_store_recovers_receipt_window_without_spawn`
  is unrelated. A rerun of the failed job is acceptable only with the
  original failure disclosed.
- **Shared test process:** tests must leave the test process child-free.
  `_LinuxSubreaperScope` in other suites refuses a caller with children; the
  reader tests' cleanup enforces this.
- **Byte-exact HTTP originals** contain CRLF; `git diff --check` warns about
  them, which is expected. `core.autocrlf` is false. Committed blobs were
  verified byte-exact.
- **Untracked files in the worktree:** `scripts/*rehearsal*.ps1`,
  `tests/Test-RehearsalCustody*.ps1` and `.publication-atomic-staging-v1/`
  are untracked Decision9–13 history left by the earlier Codex chat. Not
  touched; do not commit or delete them.

## 6. Hard limits (unchanged)

- No container may run except the remaining planned C1–C6 and D, after the
  gate-2 approval.
- No pull, prune, image deletion or offload. The 227 protected images need
  explicit user consent per image and action.
- No Q1 and no storage or configuration change.
- No merge. The PR stays Draft until archive and final review.
