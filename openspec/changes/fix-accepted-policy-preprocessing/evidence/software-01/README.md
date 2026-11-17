# First Repair Slice

## Authorization And Baseline

- Human specification approval: planning commit `299c9c0eefb83fe3031096b0e96527236678a4d2`, recorded before production/test edits in [PR #9 comment 6112617121](https://github.com/lordcoudy/VAST/pull/9#issuecomment-6112617121). Independent technical reviews of that same planning commit are recorded in the PR description; they are not human approval.
- Retained baseline: `4219f3e5ed818a508b3fb032b8310181bab16ce5` on `codex/qualify-full-benchmark`. GitHub plugin rechecked PR #7 closed/unmerged; no historical failure evidence or incomplete task was changed during apply.
- Canonical test runtime: WSL `/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python`, with `TMPDIR=/var/tmp` for physical custody. Windows Python lacks the test dependencies and is not the qualification interpreter.
- The eight missing ignored OMZ XML/BIN assets were copied from the existing main workspace only after checking ignore status, absent destinations and equal source/destination SHA-256. No failed pilot data was copied or used for promotion.

## Tests-First Evidence

These commands used `-B -m unittest discover -s tests -p <filename> -v` in the repair worktree. Outcomes refer to the evolving first implementation slice, not final-commit readiness. Original console output is retained in this Codex execution transcript; subsequent final checks must also preserve their raw logs in this evidence tree.

- Guardian baseline: existing five tests passed. Completed test-only calibration coordinates and added measured-count/type/coordinate/total cases. RED after correcting a test result-key mistake: seven tests, ten failed subcases and one error. The valid 126,016 case refused at the old exact-3,840 boundary; floating counts and incomplete calibration were wrongly accepted. GREEN after coverage repair: seven tests passed, including materialization and independent cold reading at 3,840 and 126,016.
- Guardian default routing/cold-transaction boundary RED: two tests, eleven refusal failures and one missing-leaf error. GREEN after real cold descriptor and lineage checks: two tests passed. The assessment spy is explicitly routing-only and supplies no qualification success evidence.
- F5 baseline: seven tests passed. Leaf ownership/exception identity/fresh-process import tests failed before extraction. Shared function extraction then passed ten focused tests, including the unchanged stock-file hash and exact reviewed-function diff. Adjacent stock policy tests passed 16/16.
- Full-publication identity reader RED: real capability assessment accepts the completed minimum fixture; a valid 126,016 fixture was rejected by the old count equality. Floating coverage and malformed/below-minimum/foreign calibration samples were wrongly accepted. GREEN: 35 tests across measured coverage, identity artifacts, manifest v2, runtime authority v3 and backend grant v2 passed, including POSIX custody cases.
- Runtime Python 3.10 grammar/API/source existence checks passed 5/5 after package updates.
- Independent review found that the new guardian cold call had not activated the original transaction custody context. A real held-descriptor-read spy reproduced two failing success/refusal subcases. After wrapping the unchanged validator with the shared custody object, token set/reset and final verification, all three lineage tests passed; the independent reviewer reran and confirmed the fix.
- F1 promotion now imports the defining fragment leaf, so dependency injection targets the actual reader owner. The complete promotion/F5 rerun passed 19/19 (nine promotion and ten F5 tests, 350.834 seconds), including real transaction/index/assessment/promotion regressions. This does not replace the complete default guardian fixture.
- All runtime source-closure regression tests passed 17/17 (22.454 seconds). They are package/source checks, not execution under newly rebuilt image interpreters.

## Limits And Next Gates

The guardian's aggregate/custody fixture still uses injected upstream dependencies. F5 predicate tests isolate native sidecar boundaries. Neither is evidence that a complete promoted bundle passes the full production default guardian path. Tasks 2.1/2.3/5.3 remain unchecked until a purpose-built complete real-validation chain succeeds. No attempt-4/G9 bytes may be used to fill this gap.

The inspected guardian import graph now has 67 project modules. Exactly four newly required package members were found: the three shared validation leaves and existing `analytics_execution_capability.py`. All four runtime allowlists/COPY groups include those members. Final graph, native/worker input invariance, packaged imports, A/B builds, parity/pins, ext4, integrations, hosted checks and scenario conformance remain required; none is inferred from this first slice.

Hosted checks do not automatically trigger for PR #9's retained-branch target. A supported manual dispatch and exact-SHA results are required; CI configuration and a new conformance pipeline are outside this repair.
