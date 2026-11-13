# B2 finite preparatory allowance — review before execution

This is source integration and controlled portable testing only. It cannot close
task 1.5, qualify a compiler/reader, mutate a provider, or admit physical use.
Planning commit `2e72b22195c4d47e09c13ce17ccf863d24dc26df` was independently
reviewed CLEAR; delegated AGENT implementation approval is recorded in PR9.

The exact one-use `preparatory_checks.py` reuses the existing D16 owned capture;
it has four literal phases, each once, with no automatic retry:

1. `red`: the six new pre-allocation authority tests against the old constructor
   and two outer entrypoints. Missing authority must expose the old allocations;
   malformed-authority cases initially expose the missing interface. No compiler,
   API or expensive setup may actually run: explicit sentinels precede entry.
2. `green`: the same six tests after source integration.
3. `owner`: the existing 12 export/source and 38 controlled owner tests.
4. `transport`: the two transport tests plus the explicitly named 14 negative/pure
   probe-binding cases. The transport setup gets an explicit controlled preflight
   spy and checks descriptor/deadline forwarding; real sockets/readers remain real.

The three positive cases that currently call host cc are excluded from this
allowance. They require a separately reviewed bounded external compiler setup and
reservation before execution; exclusion is not a new skip or acceptance claim.

Independently inspected existing cases create 12 export roots, 83 owner roots
(including nested HostConfig subcases), three transport roots and 14 probe roots.
RED/GREEN add six each: 124 cumulative roots, conservatively priced at 1 MiB
each and rounded upward to 128 MiB. Tiny source/reply maps, fake ELF (64 B), fake
channels and 31,921 B seccomp copies fit within each case's 1 MiB allowance; no
test can call a real compiler/engine/large fixture provider. All failures count
as retained even where ordinary test cleanup succeeds; no cleanup credit is used.

The cumulative allowance includes all four commands and retained failures:

- working, intermediate and Git source forms: 4 MiB;
- four captures, stdout/stderr each 1 MiB and one additional full copy: at most
  16 MiB, reserved within a 32 MiB log allowance;
- all 124 temporary roots/failure forms: 128 MiB;
- result records (32 KiB each), outer status (at most 2 KiB each), review/admission
  records and copies: 32 MiB;
- directories/allocation/metadata: 16 MiB, conditional on allocation units <=4096 B.

Total 212 MiB; reserve **512 MiB (536,870,912 B)** on the physical C: backing,
also conservatively require that allowance above the temporary filesystem floor.
This is cumulative across the four phases, not 512 MiB per phase. No source/test
roster expansion or extra invocation is covered. The constructor source checks
are derived/reviewed before execution; source review alone is not test success.

Immediately before each invocation, observe Windows C: and the actual Linux
`/mnt/c` and `/var/tmp` backing. C: free must be at least **43,486,543,872 B**
(40 GiB floor + allowance); selected ext4 available must be at least
**1,610,612,736 B** (1 GiB floor + allowance). Existing occupied artifacts already
reduce those free-space observations and receive no invented release credit.
The Ubuntu guest's available bytes do not replace physical C: admission.

Use the established Ubuntu `.venv/bin/python -B`, with process-scoped TMPDIR in
fresh `/var/tmp/vast-pr9-b2-prep-<phase>`. Each phase has one absolute 300-second
deadline including 5-second TERM, 5-second KILL and 5-second final phases.
Raw channels have D16's unchanged 1 MiB limits each. Result JSON is bounded to
32 KiB and the outer tool prints its fixed status, path and bounded returned
result-persistence facts, including failed write/fsync/close causes and unknown
extents. The single phase clock starts before namespace allocation. Capture/EOF,
owned child/descendant closure and completed raw/result persistence must all be
observed. RED retains the actual failing child code; it is never reported as
passing tests. Preserve failed originals. Stop and reprice on a failed or unknown
bound; no image/build/component/scientific action is included.

An expected exit 1 alone is not meaningful RED. Before GREEN is released, an
independent reviewer must inspect the retained verbose RED output for all six
named methods, the three old missing-authority allocations/sentinel refusals and
three absent malformed-authority interfaces. Import errors, unloaded tests or an
unrelated runner failure do not establish RED. Record that exact disposition.
