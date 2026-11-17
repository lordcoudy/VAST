# Archive Draft Static Validation

Root explicitly cleared only syntax checks and structured AST comparison of the
three reviewed draft files. One canonical unoptimized Python validation child
ran; no reviewed Python module was imported, no launcher mode was executed, and
no source clone, input copy, mount or archive action was taken by this validation.

Original child and capture exit statuses: 0. Original child UTC:
`2026-10-11T22:59:03.994164+00:00` through
`2026-10-11T22:59:04.196640+00:00`. Exact child argv is retained in
`controls/command.json`; original raw stdout/stderr, RC and UTC files are in the
same fresh controls directory. The original stderr is empty. Tool invocation
`1f4d2d` was the authorized canonical Python `--capture` call; `fb74f9` independently
read its complete child result and `114a38` read and hashed all seven controls.

Validation helper SHA256:
`2586a7e466b00b95270822090ebec34b10dae31f95f2c18737367e080f9709c2`.
Original result stdout SHA256:
`beaf3ca3684e71d9a295088758bc5daaea9b311386f1b7ac07c9ef840f3a17db`.
Before/after byte proof SHA256:
`0e61523211f981aa8dd4ecaa261a9309e0b7f648883ef9e333bb77f2b4ba7784`.

## Observed Checks

- Python AST syntax parsing passed for the two sealed originals and two new
  Python drafts, plus all seven embedded Python blocks in the new shell.
- Actual `/bin/bash -n <real-managed-path>/run_archive_checks_v1.sh` returned 0
  without stdout or stderr. No shell command in the launcher ran.
- The entire fresh-copy operational module AST is equal after removing only
  the exact disclosed old/new origin statements, new origin function/date
  import, cosmetic docstring and explicit report metadata. Normalized AST
  SHA256 `0f145cec23bf51bd789816d0f9c2b89c5ff86ee2962057365ed0f7c50916f5e3`.
- The entire source-comparison predicate module AST is equal after removing
  only the exact disclosed old constant/new real-origin path statements,
  origin import, cosmetic docstring and report metadata, and normalizing the
  two exact read-only evidence-name aliases. Normalized AST SHA256
  `c760fa3c6b6708981142a60f9bb7b838b5f96cfaf57da5e6456b56de6ac11093`.
- The new launcher's complete strict portable-report block and ordinary-limit
  block are AST-equal to their sealed full-suite counterparts. Its ordered33
  focus module list equals the complete sealed focus declaration.
- All eight reviewed input hashes, including all three new draft hashes,
  matched before and after validation. No sealed original bytes changed.

The additional real-origin function is disclosed separately, not claimed to be
an old predicate. Its static AST SHA256 is
`cf667f7c49495dabd6dcbc62a846478200c96f8da605650729f3e9cbf3739612`.
Human read-only reviews of that guard are recorded in the adjacent draft review.

## Limits

This establishes syntax and declared-delta static equivalence only. It does not
prove a physical archive origin, a final-head check result, a successful mount
comparison, physical qualification or Q1 admission. Final archive/check
dispatch requires the real archive, exact committed final SHA, fresh verified
roots, reviewed copies and separate orchestration clearance. The separately
authorized A16 fullsuite is owned session55655; this static result is not that
suite's result and does not change its tracked source or controls.
