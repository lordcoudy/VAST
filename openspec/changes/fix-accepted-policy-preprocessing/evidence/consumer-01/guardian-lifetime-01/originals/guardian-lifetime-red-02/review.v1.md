# Original Focused Guardian Lifetime RED

Root reviewed operational wrapper SHA256
`686c39ad79c702e996c77d48de696b7037f41961219f79780f2a6fc7274c0059`
and cleared one corrected invocation. The earlier controls01 wrapper failure
remains separately preserved and never executed the test.

## Actual Result

The canonical CPython invocation completed naturally with original exit code 1,
UTC 2026-10-12T11:36:40.3909023Z through 2026-10-12T11:36:41.5258187Z.
Whole invocation elapsed time was 1.1348906 seconds. Stdlib unittest reported
one test, 0.135 seconds, one assertion failure and no errors or skips.

The actual failure is at regression line 145 after an injected 1801-second
advance of only the fixture module's elapsed clock:

```text
AssertionError: False is not true : fixture responder expired before owner stop: [RuntimeError('fixture guardian control request bound exceeded')]
```

The initial real UNIX status query completed before the clock advance. The
unmodified fixture responder then exited before authenticated stop. The test's
owned finally block closed the session and asserted its thread had terminated.
Authenticated finish and the second explicit-close case were not reached in
this RED; they remain GREEN verification obligations.

## Scope And Custody

The external ordinary ext4 overlay is
`/home/s-a-balashov/work/vast-guardian-lifetime-red-20261012-02`.
It contains 238 SOURCE06 script files, 19 SOURCE06 fixture files and the one
changed regression test: 258 files, all byte-verified before and after execution.
SOURCE06 has no `tests/__init__.py`; none was invented.

The same single test invocation verified exact physical import origins for
the test, lifecycle fixture and production sidecar before selecting and
executing one test. `PYTHONPATH` and `PYTHONHOME` were removed, canonical runtime
`/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python`
ran with `-B`, HOME `/home/s-a-balashov`, UID/GID 1000 and native ext4 paths.
Both Linux and Windows prelaunch owned-worker observations had no matching
actors. The postclosure Linux observation completed with exit code 0 and no
matching actors.

The changed test SHA256 is
`19543d86e69094d36f4ef6a6268d486218f8eeab3d4358f89d77d046f4952c4d`.
The unchanged SOURCE06 lifecycle helper SHA256 is
`2d3837adc2683eefbd9497de00ff724a0935bf8df9d8543ffac4844bbcc63910`.
Only the fixture module's time reference was proxied; the test verifies that
the production sidecar still holds the real time module. No production
request timeout, validation predicate or acceptance dependency was changed.

No retry, process signal, SOURCE06/CI write or historical mutation occurred.
This is focused nonauthorizing test evidence, not a complete consumer,
qualification or campaign acceptance. The original minimum10 deadline
attribution remains an inference from its preserved failure timing; this
focused test directly demonstrates the fixture deadline mechanism.

## Original Evidence

`command.v1.json`, `copy-plan.v1.json`, `copy-proof.v1.json`,
`owned-workers-before.v1.json`, `test-original.result.v1.json`, the two
`test-original.*.raw` streams and `result.v1.json` retain the originals.
The stderr includes the unchanged native WSL proxy warning followed by the
real unittest assertion; it was not filtered or rewritten.

- stdout SHA256: `afc6d3e9ee82cf53dcd27f9f7cd390af2d91c4a0cf70f81702c858002aafa0df`
- stderr SHA256: `380ee1c1438138911ba0ff3d694e6bff9a8d2ff8c829f22b8132858c65edcf3a`
- copy-plan SHA256: `1298f595ae5eff292afbb9169119ef23b04a576e3c3c43d138c7ca0da76eea0c`
- original test receipt SHA256: `cbbb1bd699b69486076edaa50af9d3f343e9a55613d2718cec2f260ec4694154`
- postclosure result SHA256: `2013ba48cb510eaf34fa87e5b14623b6a69f7efb09078f01a7639989ce032c15`
