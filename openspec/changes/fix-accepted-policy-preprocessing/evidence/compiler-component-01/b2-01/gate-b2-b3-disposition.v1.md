# B2→B3 gate disposition (plan V7 erratum)

Two independent reviewers read the B2 originals at `067abf83`, read-only, and
re-derived the results from the raw files: a Claude subagent and grok. Both
returned **PROCEED_TO_B3**. Claude's verdict depends on B3's expected values
being restated, as below; the stricter of the two sets is adopted.

## Dispositions

- **D1 (accepted):** `kernel.print-fatal-signals=1` makes `get_signal()`
  print "potentially unexpected fatal signal" and a register dump for
  coredump-class deaths, just before `do_coredump`. That is the same death,
  not a second event; the dumps confirm `ORIG_RAX` 0x40000027 and 0x14.
  Gate 2 must restate C3's dmesg expectation: a SIGXFSZ `as` death also
  prints a sig 25 banner and a register dump.
- **D2 (accepted):** the `misc dxg:` lines are host-side; the container has
  no devices and no dxg node. The WSL VM idles out between commands and
  boots on the next `wsl.exe`, and both retained containers persist. For B3,
  the VM is pre-warmed and dmesg is captured within one boot ID.
  **Reviewers must not run `wsl.exe` while B3 runs.**
- **Host `as` crash dump:** it comes from a host-only bash check (`ulimit -c 1`
  is 1 KiB) and changes no container claim. Stage D sets limits through the
  runner and takes crash-directory listings before and after.
- **Integrity:** `B2.originals.sha256` hashed itself while it was being
  written, so its self line does not reproduce. All other 37 committed
  entries match. The crash-directory listing is outside the manifest. B3
  writes its manifest last and excludes itself.
- **Pre-registration:** V7's B3 list did not pin the cause set; it is pinned
  below.

## B3 expected values (all must hold exactly; anything else stops the plan)

1. **Before the run:**
   - The VM is pre-warmed: one no-op `wsl.exe`, then about 30 s for boot
     logging to settle.
   - Recorded: the boot ID, `print-fatal-signals`, `dmesg` (component root
     only) and the WSL crash-directory listing.
   - The create guard sees nothing running, and the all-state list is
     exactly the stopped `4df593e12ca362e69f0594b2035197335f335d3ceae3c71894b31db9f197a09f`
     and `9b5c396109909a8a091a0fc6bb6529f887233df77ab314435ce85ab05e22fbc5`.
2. **Probe:** it reads the B3 request, ignores SIGTERM, writes nothing and
   sleeps.
3. **Containment sequence** in `probe.result.original.json`, in this order:
   1. `normal_close_wait` times out;
   2. `kill_SIGTERM` replies with no body (204);
   3. `wait_after_SIGTERM` times out at about 30 s;
   4. `kill_SIGKILL` replies with no body (204);
   5. `wait_after_SIGKILL` returns `{"StatusCode": 137}`;
   6. `final_inspect`.

   That is 14 RPCs in total, with no 409 and no `docker_sticky_failure`.
4. **Runner causes:** a subset of {`docker_attach_TimeoutError`,
   `docker_deadline`, `attach_incomplete`, `docker_io_TimeoutError`}, which
   must contain `docker_attach_TimeoutError` or `docker_deadline` (the
   work-window expiry). Any other cause stops the plan.
5. **Final state:** ExitCode 137, `OOMKilled` false, an incomplete export
   and no ELF.
6. **Closure:** init absent, cgroup unpopulated.
7. **dmesg delta** (same boot ID before and after): zero lines of each of
   these kinds:
   - "potentially unexpected fatal signal" (SIGTERM is ignored, and SIGKILL
     is not coredump-class);
   - "RLIMIT_CORE" or "Aborting core";
   - `type=1326` or `type=1701`;
   - `wsl-capture-crash`.

   Only host-side `misc dxg:` lines are allowed.
8. **Crash directory:** the listings before and after B3 are identical.
9. **Charge:** at most 16 MiB of non-output growth, added to the cumulative
   ledger (7,761,920 B after B2).

## Decision

B3 may run once under the unchanged gate-1 runner and plan V7 once this
disposition is committed, CI passes on its commit, and delegated AGENT
approval is recorded in PR #9. After B3, gate 2 (seed, N3, the F2 toolchain
gap, the C3 dmesg restatement, `/dev/mqueue`, the ledger) must be reviewed
and approved before any C or D run.
