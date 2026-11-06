# Original Archive-Origin RED Observation

Tool chunk `87fee1` executed the canonical WSL publication Python in the managed
worktree with `TMPDIR=/var/tmp`, `PYTHONDONTWRITEBYTECODE=1`, and this command:

```bash
/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python -B -m unittest tests.test_accepted_policy_change_paths_v1.AcceptedPolicyChangePathsV1Tests.test_actual_main_origin_expression_resolves_active_and_supported_archive -v
```

The original return code was 1. One actual test ran in 0.023 seconds; active
origins passed, while both simulated archive origins failed their real main
origin expression. At date `2026-10-12-fix-accepted-policy-preprocessing`, both
`build_production_fixture_v2.py` and `build_per_cell_minimum_refusal_v1.py`
selected `/var/tmp/accepted-policy-archive-origin-1laoqn6f/openspec` instead of
`/var/tmp/accepted-policy-archive-origin-1laoqn6f`. The terminal result was
`FAILED (failures=2)`.

This technical text records the original observed tool result. The original
execution UTC and separate raw stdout/stderr streams were not captured; they
are intentionally not invented or reconstructed. No later rerun is represented
as this original RED command. The test evaluated only the actual path-origin
assignment against tiny temporary evidence layouts; it did not execute a
consumer, validate campaign data, move a real change, or perform an archive.
