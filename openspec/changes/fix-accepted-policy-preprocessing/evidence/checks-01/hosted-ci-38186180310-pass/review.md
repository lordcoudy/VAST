# Hosted 06 Original Artifact Review

This is a post-run review, not a reconstructed original command capture.
GitHub plugin verified run 38186180310, attempt 1, completed success at exact
source `06c828ce798d3454f1d4b8a992aed7133882b5a1`. Both CPU and host-diagnostic
jobs passed. Run: https://github.com/lordcoudy/VAST/actions/runs/38186180310.

The original downloaded ZIP archives are retained without extraction,
normalization or rewriting. Their lengths and SHA256 match GitHub metadata:

- CPU artifact 11720049738: 2812616 bytes,
  `dcb9e90465f3eca84df4eee98c2331e9e4ccd16a6b45dd51fc74fcb7f00822e9`.
- Host artifact 11720010760: 918371 bytes,
  `1ce659c722ab7ef41d87ffb640da34c1fcc80201ee0d589476f535795e405ce3`.

Native HTTP downloads completed with status 200 and exact digest/length checks
at 2026-10-12T09:56:27.6467120Z and 2026-10-12T09:59:00.9269894Z respectively.
Signed download references are not retained. The earlier Node download timed
out and its kernel reset, leaving no archive; that attempt is not success.
An initial current reference-shape guard refused before download/file writes
because the connector returns a structured file reference, not a bare URL.

## Exact CPU Report

Read the exact root ZIP entry `report.json`, not
`model-acquisition/report.json`. Raw report SHA256:
`66f55915e865e430be6387f54720f668a4501184e9c2b4edfaa9c2a9546b05c4`.
Structured assertions passed against the unchanged committed selection manifest:

- 3331 discovered IDs, 3322 portable tests, 3234 successes and 88 skips.
- Zero failures, errors, expected failures, unexpected successes or missing
  required successes. Actual source commit is exact 06; raw checkout bytes
  match it, and changed tracked paths are empty.
- Every skip identity and reason matches the declaration. The complete audit
  including classifications and false acceptance claims equals the selected
  manifest rows in ordinal test-ID order. Manifest SHA256 remains
  `09e9268069e88b957f9ae54a827960bc18ee13a00d4319994d108d3cb81a0805`.
- CMake configure and all six native targets returned zero without timeout.
- Python syntax checked 536 files; Bash syntax checked 16 files. The 88 skips
  comprise 78 platform/explicit prerequisites and 10 retired-schema migrations.
  Portable selection reports that its nine physical integrations were not run.
- Observer returned zero with successful completion, control/trace EOF,
  35 completed responses to 35 requests and no forced SIGTERM or SIGKILL.
  Its own report explicitly does not establish descendant quiescence.
- Actual stock report elapsed time: 2201.301173292 seconds.

Review-only guarded failures are retained in tool history: a suffix selector
was ambiguous between the two report entries; two subsequent array assertions
used PowerShell culture-sensitive ordering, which differs from the stock
ordinal ordering. The corrected exact entry and structured JsonNode comparison
with StringComparer.Ordinal passed (tool c06785). No CI check was rerun,
mutated, waived or relabeled by these review-only attempts.

## Limits

Hardware acceptance is false. Hosted CI does not establish physical decode,
packaged SDK execution, native paired inference, qualification, Q4 or Q1.
Complete default-consumer, genuine 126016-sample/refusal evidence and final
archived-head checks remain separate gates. This archive binds 06 only, not
a later evidence/archive commit. PR9 remains Draft and unmerged.
