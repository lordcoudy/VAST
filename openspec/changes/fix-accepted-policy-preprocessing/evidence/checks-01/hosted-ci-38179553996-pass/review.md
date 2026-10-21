# Hosted A16 Original Artifact Review

This is a post-run review, not a reconstructed original command capture. GitHub run 38179553996, attempt 1, completed successfully at source commit `a16f243e7e80f093342ccdddf717d59d6d46f0a8`. Both original-host diagnostics and CPU-check jobs succeeded. The run remains available at https://github.com/lordcoudy/VAST/actions/runs/38179553996.

The original downloaded archives are retained without extraction, normalization or rewriting:

- CPU artifact 11717826105: 2,786,665 bytes; SHA-256 `27edbe5ff3e68c4344f6dcd81078ee0785682a393cadabd659cc837c90421643`.
- Host diagnostics artifact 11716779531: 898,618 bytes; SHA-256 `7a349676ee1d245d833a789fa80c343b6e78a44ead4b53cb1b77322bbcdc63f7`.

Both downloaded hashes and lengths match the GitHub plugin's artifact metadata and exact source head. Signed download URLs are not retained.

## Independent CPU Read

The reviewer read the exact ZIP entry `report.json`, not the separate `model-acquisition/report.json`. Structured assertions against the unchanged committed `.ci/integration-test-selection.v1.json` passed:

- 3,316 discovered IDs, 3,307 tests run, 3,219 successful tests.
- Zero errors, failures, expected failures, unexpected successes or missing required successes.
- 88 exact audited non-executions: 10 retired-schema migration cases and 78 platform or explicit physical-prerequisite cases. Each actual test ID, reason, classification and false acceptance claim matched the unchanged policy; no duplicates or unapproved skips.
- All nine declared physical integration cases were excluded from the portable run, absent from its successes and skips, and were not claimed as executed.
- Selection manifest SHA-256 `09e9268069e88b957f9ae54a827960bc18ee13a00d4319994d108d3cb81a0805` matched the actual committed file.
- Actual source head matched A16, tracked checkout bytes matched the commit, and the changed tracked-path list was empty.
- CMake configure and all six requested native targets completed with original return code 0 and no timeout. Python syntax checked 535 files; Bash syntax checked 16 files; all three required GStreamer factory inspections returned 0.
- Model acquisition reported `complete` with eight assets. This is asset preparation, not inference acceptance.
- The original suite observer reported return code 0, successful completion, both control and trace EOF, 24 completed responses to 24 requests, and no forced SIGTERM or SIGKILL. Its report explicitly does not establish descendant quiescence merely from original-child status.
- The scoped namespace profile's load and unload were verified and held descriptors were released.

Review tool output `60352e` records the successful structured assertions. Earlier review-only attempts used an ambiguous ZIP suffix selector or printed an oversized selection object; they did not rerun, alter or waive any CI check.

## Limits

The report's `hardware_acceptance` is false. Hosted success does not prove NVIDIA decode, packaged SDK execution, model parity, native paired execution, qualification, Q4, storage or the full benchmark. Physical integration, complete default consumers, adversarial refusal cases and final archived-head checks are separate gates. This artifact applies to A16 only, not an eventual later evidence/archive commit. PR #9 stays Draft and no new Q1 campaign is started by this review.
