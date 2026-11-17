# B1→B2 gate disposition (plan V7 erratum)

Two independent reviewers read the B1 originals at `7b252d59`, read-only, and
re-derived every expected value from the raw files: a Claude subagent and
grok. Both returned **PROCEED_TO_B2**. Claude's verdict depends on the
written dispositions below.

## F1: glibc `setrlimit` recorded as `ValueError` (accepted; instrumentation defect)

The probe called `resource.setrlimit(RLIMIT_CORE, (1, 1))`, caught only
`OSError`, and recorded the exception type. Both reviewers checked primary
sources and found:
- CPython 3.10 `Modules/resource.c` maps a failing `setrlimit` with EPERM to
  `ValueError("not allowed to raise maximum limit")` and EINVAL to
  `ValueError("current limit exceeds maximum limit")`. Any other errno becomes
  `OSError`, and the other `ValueError` paths cannot be reached with
  (4, (1, 1)).
- EINVAL is impossible: (1, 1) has cur = max, and the NULL query read 1/1.
- glibc 2.35 `setrlimit` is exactly `prlimit64(0, resource, new, NULL)`, the
  shape the raw `prlimit64_unchanged` probe showed returning EPERM in the
  same container.
- The submitted profile (RPC05, byte-equal to the committed JSON) has no rule
  that allows a CORE write. Only the default errno 1 (EPERM) or the clone3
  errno 38 can result, and ENOSYS would surface as `OSError`.
- On the host, a non-root uid reproduces the CPython mapping. (1, 2) gives the
  EPERM message and (2, 1) gives the EINVAL message.

**Disposition.** The raw `setrlimit` (160) and `prlimit64` (302) probes
positively qualify CORE-write enforcement, together with the upper-bit alias
and the NOFILE positive control. The libc-level result is derived, not
observed: the original does not contain the message. No CORE write succeeded,
so none of gate 2's stop-and-amend triggers occurred. B1 is not re-run,
because that would be a tenth container outside the nine-container seal.

## F2: toolchain record incomplete (README corrected; carried to gate 2)

- cc's `-###` shows the PIE default objects `Scrt1.o`, `crtbeginS.o` and
  `crtendS.o`. The probe hashed `crt1.o`, `crtbegin.o` and `crtend.o`, which
  cc does not use.
- The real `libc.so.6` is not hashed and no glibc version is recorded;
  `libc.so` and `libgcc_s.so` are linker scripts.
- `cc1 --version` produced 0 bytes on both streams (rc 0), so V7 section 12's
  "read stderr" finds nothing. collect2 has no version.

This does not affect B2, whose `-nostdlib -static` build uses only cc1, as
and ld, all resolved and hashed. Gate 2 must close the gap without a new
container, for example by read-only reads from the retained B1 container, or
record it explicitly in the seed's `toolchain` proof. The B1 README's
"matched exactly" wording for the toolchain is corrected accordingly.

## Carried to gate 2

- **F3 (N3):** effective `Config.Labels` adds the image's 23 labels to ours
  (no key collisions), and `Volumes` reads `{}` as `null`. Every requested
  HostConfig key is exact, including `CapAdd` `[]` on both sides, so N3 must
  not pre-accept `CapAdd` null versus `[]`. Inspect adds Docker defaults the
  create body omits, such as `MaskedPaths` and `ReadonlyPaths`. The owner's
  exact comparison of the requested keys must be amended for Labels and
  Volumes before C1.
- **F4:** `/dev/mqueue` is an rw mount writable by uid 1000, mounted noexec.
  It is a Docker default inside the matched rw-mount hash, bounded by
  RLIMIT_MSGQUEUE and memcg, and gate 2 names it explicitly.
- **F5:** `/system/df` and output-directory totals were not recorded,
  because V7 section 12 narrowed the runner's list. B1's charge is the
  maximum of the three recorded deltas: 7,430,144 B of C: free. That is above
  the 4 MiB planning figure but under the 16 MiB per-container stop, and the
  cumulative ledger starts here.

## Decision

Following both reviews, B2 may proceed under the unchanged gate-1 runner and
plan V7, once this disposition is committed, CI passes on its commit, and
delegated AGENT approval is recorded in PR #9. B3 follows only after B2 meets
its exact expected values.
