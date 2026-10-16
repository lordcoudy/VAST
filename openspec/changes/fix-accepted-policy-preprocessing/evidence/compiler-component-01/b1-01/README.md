# B1 environment and CORE probe: first component container

Run under the probe runner at the gate-1 commit `8c08cd30` (approved in PR #9
comment 6210515683), after the P0 committed-snapshot proof (`../p0-01/`).
The component root is
`/home/s-a-balashov/work/vast-fixture-compiler-component-8c08cd30f2355a26b2e7a31b53e6f268acafda29-01`:
seven blob-verified files, 244,183 B, mode 0700.

- Container: `4df593e12ca362e69f0594b2035197335f335d3ceae3c71894b31db9f197a09f`
  (`vast-fixture-compiler-probe-b1-66f97415cf0d360619ca942bb7eedcc8`).
- Timing: started 2026-10-16T08:37:32.67Z, finished 08:38:03.04Z (about 30 s).
- Outcome: ExitCode 0, `OOMKilled` false, runner causes `[]`, 10 RPCs
  (202,970 metadata bytes).
- Containment: the normal-close wait returned `StatusCode` 0; no TERM or KILL
  was sent.
- Closure: init absent, cgroup empty and unpopulated.
- The container is retained, stopped. Nothing was removed or pruned.

## Results against plan V7 (`run-records/B1.evaluation.json`)

**Matched exactly:**

- **Identity and privilege:** uid/gid 1000; `NoNewPrivs` 1; `Seccomp` 2 with
  filters; every capability set is 0.
- **Limits:** CORE 1/1 and FSIZE 16,777,216/16,777,216. A fork-exec child
  inherits CORE 1/1, Seccomp 2 and NoNewPrivs 1.
- **cgroup:** `memory.max` 536,870,912, `memory.swap.max` 0, `pids.max` 32,
  `cpu.max` "100000 100000".
- **Network and devices:** `lo` is the only interface; there is no
  `/dev/nvidia*`.
- **Raw CORE syscalls:** the NULL `prlimit64` query reads 1/1. Each of these
  returns EPERM:
  - raw `setrlimit` at {1,1} and at {0,0};
  - raw `prlimit64` at {1,1} and at {0,0};
  - the upper-bit alias `4 | 1<<32` with a non-NULL limit.

  The NOFILE positive control succeeds. No probe child crashed.
- **tmpfs:** exactly eight full 16 MiB files fit (134,217,728 B), and ENOSPC
  came on the ninth. 4,095 inodes were created, then ENOSPC. `/work` started
  empty.
- **Mounts:** the in-container rw-mount hash
  `3da03bbb...51ff470` equals the host owner's live hash.
- **`/work` flags:** `rw,nosuid,nodev,noexec,relatime`, the noexec
  that V7 predicted. `vm.memfd_noexec` is 0.
- **Toolchain:**
  - Python 3.10.12 at `/usr/bin/python3.10`.
  - cc is gcc 11.4.0 (`/usr/bin/x86_64-linux-gnu-gcc-11`).
  - Helpers: cc1 and collect2 in `/usr/lib/gcc/x86_64-linux-gnu/11/`, as at
    `/usr/bin/x86_64-linux-gnu-as`, and ld at
    `/usr/bin/x86_64-linux-gnu-ld.bfd`. All are ELF64/x86-64 and hashed.
  - 25 reached headers are hashed.
  - **Gap (F2 in `gate-b1-b2-disposition.v1.md`):** the probe hashed
    `crt1.o`, `crtbegin.o` and `crtend.o`, but cc uses the PIE `Scrt1.o`,
    `crtbeginS.o` and `crtendS.o`. The real `libc.so.6` and the glibc
    version are not recorded, and `cc1 --version` is empty. The toolchain
    record is therefore not complete; gate 2 closes or records the gap.
  - C4's `cc -E` was killed at its 10 s bound, as V7 expected.
- **C5 slope:** the full 20 s window. Still running at kill, 0 output bytes,
  RSS flat at 11,200 KiB throughout.
- **Measurements:** C: free fell 7,430,144 B over the run (host noise
  included); ext4 used rose 372,736 B; journald stayed at 808.0 MiB;
  container `SizeRw` was 12,288 B. The dmesg dumps before and after are
  byte-identical (SHA-256 `9d0a7bf6...`), so the delta is empty. The dumps
  stay in the component root and only their hashes and the empty delta are
  committed here.
- **Effective config (N3 input for gate 2):** the only differences from the
  request are the inherited image labels (23 provider labels added; ours
  unchanged) and `Volumes` `{}` read back as `null`. Every HostConfig field
  equals the request.

**One deviation** (see `gate-b1-b2-disposition.v1.md`):

- `glibc_setrlimit` (Python `resource.setrlimit(RLIMIT_CORE, (1, 1))`)
  recorded `{"exception": "ValueError"}`, not `errno: EPERM`.
- Cause: CPython's `resource.setrlimit` reports EPERM as
  `ValueError("not allowed to raise maximum limit")`, and EINVAL as
  `ValueError("current limit exceeds maximum limit")`. On this host, Python
  3.12.3 shows exactly that message for a real EPERM.
- EINVAL is impossible for (1, 1) with an equal hard limit.
- glibc's `setrlimit` is implemented as `prlimit64`, which the same container
  shows returning EPERM for the identical values.

This is an instrumentation defect in how the probe recorded the outcome, not
a CORE write that succeeded. Plan V7 nonetheless says the B1→B2 gate needs
every expected value observed exactly. B2 is therefore held until this
disposition is independently reviewed and approved. Re-running B1 would be a
tenth container, outside the nine-container seal, and is not proposed.

`originals.sha256` lists the component-root source paths (`outputs/B1/`,
`runs/`). In this repository they are `outputs/` and `run-records/`, because
the repository's `.gitignore` excludes any `runs/` directory. The two host
dmesg dumps listed there stay only in the component root.
