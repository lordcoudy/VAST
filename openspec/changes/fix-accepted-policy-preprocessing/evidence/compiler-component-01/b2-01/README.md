# B2 bad-ABI rejection: second component container

This run was made after the B1→B2 gate approval (PR #9 comment 6212407700,
evidence at `e39dbea2`). It used the unchanged gate-1 runner and the same
component root as B1, and the only allowed prior CID was B1's
`4df593e1...`.

- **Container:** `9b5c396109909a8a091a0fc6bb6529f887233df77ab314435ce85ab05e22fbc5`
  (`vast-fixture-compiler-probe-b2-e452bcbebfda05be79880c9cf43ba07f`).
- **Timing:** started 2026-10-16T09:26:03.25Z and finished 09:26:03.51Z.
- **Outcome:**
  - ExitCode 0, `OOMKilled` false, runner causes `[]`.
  - 10 RPCs used 207,892 metadata bytes.
  - The normal-close wait returned `StatusCode` 0, so no TERM or KILL was
    sent.
  - Closure: init absent, cgroup empty.
  - The rw-mount hash is `3da03bbb...`, the same as B1.
  - The container is retained, stopped.
- **Charge:** C: free unchanged, ext4 +331,776 B, `SizeRw` 12,288 B.

## Results against plan V7

**Matched exactly:**
- **CORE:** confirmed 1/1 by the NULL `prlimit64` query. No write was
  attempted.
- **Probe builds and launch:** both built with `-nostdlib -static` (rc 0)
  and ran from an `MFD_EXEC` memfd via `fexecve`. `/work` is noexec. There
  was no `memfd_error`.
  - x32 image: 4,728 B, SHA-256 `a18e1885...`.
  - i386 image: 4,704 B, SHA-256 `c0303d2c...`.
  - Both are the same bytes as the host-only pre-check.
- **x32 `getpid` (`0x40000027`):** wait status exactly **0x1f**, SIGSYS, no
  core flag. This matches the libseccomp 2.5.5 bad-arch jump that both
  reviewers cited.
- **i386 `int 0x80` getpid:** wait status exactly **0x1f**, SIGSYS, no core
  flag.
- **dmesg, required kinds, for each death:**
  - one seccomp audit record (`type=1326`, `sig=31`). The x32 record shows
    `arch=c000003e syscall=1073741863`; the i386 record shows
    `arch=40000003 syscall=20`.
  - one `Process N(memfd:vast-prob) has RLIMIT_CORE set to 1` line;
  - one `Aborting core` line, with `core_pattern` set to the pipe
    `|/wsl-capture-crash %t %E %p %s`.

  No pipe helper ran. No `type=1701` line appeared, as expected with audit
  disabled.
- **Windows WSL crash directory:** no entry is newer than 2026-10-16T06:26:35Z,
  before B2 started at 09:26:02Z, so B2 created no crash dump. The listing is
  in `run-records/wsl-crashes.listing.after-b2.tsv`. No listing was taken
  before B2, so this is an mtime-based check.

**Deviations from V7's exact dmesg expectation (dispositions pending
review):**
- **D1:** each SIGSYS death also printed `potentially unexpected fatal signal
  31.` and a register dump (`CPU`, `RIP`, `RSP`, `RAX`...`FS/GS`, `Code:`).
  The WSL kernel runs with `kernel.print-fatal-signals=1`
  (`run-records/B2.kernel-facts.txt`), which V7 did not anticipate. These
  lines are the kernel reporting the same SIGSYS; they are not an extra
  event.
- **D2:** the delta also holds `misc dxg: dxgk: ...` lines. The WSL VM had
  idled out after B1 and booted on the B2 command, and B2 ran about 2.9 s
  into boot, so the "before" snapshot (460 lines) was taken while the boot
  log was still being written. The `dxg` GPU paravirtualization driver
  messages are boot noise from a subsystem unrelated to the probe container,
  which has no devices. The boot ID changed between B1 and B2, and both
  containers persisted across the restart.

## Disclosure: a host crash dump from an earlier host-only pre-check

The newest crash-directory entry,
`wsl-crash-1792131995-672-_usr_bin_x86_64-linux-gnu-as-25.dmp` (913,408 B,
06:26:35Z), was created by my own host-only C3 sanity check earlier that
day, not by any container. That check ran
`ulimit -f 16384; ulimit -c 1; gcc ... c3.c`. bash's `ulimit -c` counts
1 KiB blocks, so the core limit was 1,024 B, not 1. The kernel therefore
started the pipe helper and `as`'s SIGXFSZ core was captured. This confirms
Decision15's premise that only an exact limit of 1 stops the helper. The file
was left in place and nothing in the crash directory was changed.

The host dmesg dumps before and after stay in the component root; their
hashes are in `run-records/B2.originals.sha256`, and only the delta is
committed. B3 is held until D1 and D2 are independently reviewed and
approved.
