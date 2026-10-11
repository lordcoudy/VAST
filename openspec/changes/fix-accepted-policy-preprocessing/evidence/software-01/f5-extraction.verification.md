# F5 Extraction Verification

Status: verified focused implementation behavior, not final repair readiness or human approval.
Planning authority: approved commit `299c9c0eefb83fe3031096b0e96527236678a4d2`.
All commands below used the shared repair worktree with implementation changes present; no final source SHA is claimed.

## Baseline and Tests-First Evidence

The original F5 suite passed 7/7 tests before extraction, in 0.059s.
The new leaf ownership, exception identity and fresh-process forbidden-import tests produced the expected RED result before the leaf existed: 9 tests, one failure and two missing-leaf errors, in 0.063s.
After extraction, the focused suite passed 9/9. A further negative test added terminal linkage, invalid service-value and duplicate-event refusal checks before ingress-drop sample exclusion; the resulting F5 suite passed 10/10 in 0.606s.

## Final Focused Run

Executed from WSL `tests/` with `TMPDIR=/var/tmp` using the existing canonical runtime:

```text
wsl.exe -d Ubuntu -u s-a-balashov --cd /mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/tests -- env TMPDIR=/var/tmp /home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python -B -m unittest -v test_publication_qualification_promotion_v2 test_publication_qualification_policy_pilot_validator_v2
```

Result: 19/19 PASS in 350.834s, comprising all nine promotion tests and all ten F5 tests. The real transaction-v2/index/assessment/promotion case and the stock legacy refusal case both passed.
An earlier adjacent promotion run could not enter its assertions because ignored OMZ model inputs were absent. The integration owner subsequently made those inputs available. During integration, F1's `fragments_v2` import was moved from the builder wrapper to the defining fragment leaf, restoring the documented default dependency injection boundary used by F1 tests.

The stock policy qualification suite separately passed all 16 tests in the earlier 25-test combined invocation, where the nine promotion setup errors were exclusively the then-missing OMZ model input. Command:

```text
wsl.exe -d Ubuntu -u s-a-balashov --cd /mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/tests -- env TMPDIR=/var/tmp /home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python -B -m unittest -v test_publication_qualification_promotion_v2 test_publication_policy_qualification
```

## Preserved Contracts

- `publication_policy_qualification_pilot_validation_v2.policy_pilot_validator` owns the reviewed F5 function; F1 re-exports that same function object.
- The stock policy source remains byte-identical with SHA256 `f4478804491922c3e25ab414ba8f000c1964b46633f9dfb3a5bc87212748dbde`; the exact reviewed function diff still passes.
- Reset evidence and six streams remain mandatory. CPU and transfer-backed GPU samples remain equal to stock behavior. A dropped GPU decision without transfer is excluded only after replay, cell, evidence, uniqueness, CSV, terminal and service checks.
- The standalone pilot leaf imports no host promotion, transaction/fragment builder, index/bootstrap builder, pilot executor, operational owner or sidecar, and retains the stock exception class identity.
- Re-exporting a shared default dependency object preserves object identity. Reassigning an attribute on the old builder wrapper does not rebind a leaf's globals; tests must patch the actual defining owner or use the supported explicit dependencies argument. No dynamic module proxy was introduced.

No commits, pushes, Docker builds, Q1 workers, historical promoters or historical raw-data materializers were run by this subagent.
