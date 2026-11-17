# Archive-Safe Test and Current Entrypoint Resolution

Scope: exactly this repair's active layout or one valid
`YYYY-MM-DD-fix-accepted-policy-preprocessing` archive layout. Missing,
ambiguous, invalid-date, double-dated, noncanonical, and unrelated layouts are
refused. No repository-root upward search, production source expansion,
historical record rewrite, actual change move, or archive was performed.

## Original Checks

The original RED command/result is attributed in `red.original-observation.md`:
one test, two genuine archived-origin failures, return code 1 (tool `87fee1`).
The old main assignments selected `openspec` instead of the repository root.
The original RED UTC and separate raw streams were not captured and are not
reconstructed.

The original GREEN (tool `d9e2ef`) ran 14 tests in 4.705 seconds, return code 0,
zero skips. Its original decoded tool result is losslessly encoded in
`green.original-tool-observation.v1.json`; it is not claimed as raw split
stdout/stderr or a record of execution UTC. Exact GREEN command:

```bash
/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python -B -m unittest tests.test_accepted_policy_change_paths_v1 tests.test_accepted_policy_native_fixture_v2.AcceptedPolicyNativeFixtureV2Tests.test_explicit_fixture_paths_refuse_parent_traversal_before_writes tests.test_accepted_policy_native_fixture_v2.AcceptedPolicyNativeFixtureV2Tests.test_explicit_fixture_paths_refuse_symlinked_ancestors_before_writes tests.test_accepted_policy_native_fixture_v2.AcceptedPolicyNativeFixtureV2Tests.test_explicit_consumer_helpers_retain_selected_production_source_provenance tests.test_accepted_policy_native_fixture_v2.AcceptedPolicyNativeFixtureV2Tests.test_explicit_fixture_initial_imports_fit_unchanged_executor_source_closure tests.test_accepted_policy_fixture_sample_counts_v2.AcceptedPolicyFixtureSampleCountsV2Tests.test_negative_entrypoint_compiles_and_uses_actual_call_signatures_without_changing_positive_gate -v
```

The current next-source focused recipe now includes the nine-test resolver
module; all other additions remain. Historical checked outputs and sealed591
recipes were not edited.

## Separately Captured Combined GREEN

The independent fixture owner subsequently retained the exact command, UTC,
original raw stdout/stderr, return code, and equal before/after source hashes
under sibling `standalone-reader-01/bounded.*`. That original combined run
passed all 26 tests in 10.948 seconds with zero skips and includes all nine
archive simulations, all six native-fixture tests, and all four count tests.
It is a separately attributed run, not a replacement for either original
14-test GREEN or the failed RED. The stderr's mixed WSL proxy-warning bytes
are retained there unchanged, not normalized for this note.
The captured UTC interval is `2026-10-11T22:08:32.8344915Z` to
`2026-10-11T22:08:45.3175593Z`; original return code is zero. Its raw stdout
SHA-256 is `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
(empty), and raw stderr SHA-256 is
`5511f49f81df079e65fb8f21b84bd9369f55c78fbc1aaa2c8439fc425162f435`.

## Own Source Hashes

These hashes were measured after the original 14-test GREEN. The first six
match the independent combined run's before/after records; the focused recipe
hash is a separate after-edit measurement, not a claim that this recipe ran:

- `tests/fixtures/accepted_policy_change_paths_v1.py`: `b213ecba7fec7b5959145c02e7efba4a2e7fa156c15edd953d7189fa76ddb0f3`.
- `tests/test_accepted_policy_change_paths_v1.py`: `a277bfb3e5b5afcb7be4dd9309ce6600a93ffb6cc5aeedbda3ef1173b4ca3fcd`.
- `tests/test_accepted_policy_native_fixture_v2.py`: `68f1313ebf3aabdfc6ab60653118e6111f66afd3e625a2e1dfe689cfbcb7075c`.
- `tests/test_accepted_policy_fixture_sample_counts_v2.py`: `3f0f0169a472b166a31dc985750810c36c811bb061f1d458e3bf6eafb1c40c02`.
- `build_production_fixture_v2.py`: `068cc6bc174f2526ccd9af6ea7e47c0cce9de83debcc5151e3958a2cfc20995d`.
- `build_per_cell_minimum_refusal_v1.py`: `51d4a63bb8874955ae48851f9235dc92aa39ea0ea747c9bcb499c3d214918e40`.
- `checks-01/run_focused_suite.sh`: `237ae90c628d187b9d6e66847b3176f24f399d7ed700350df9257d983477ca42`.

These checks prove bounded resolution and refusal behavior plus unchanged
production import closure at the tested boundary. They are not post-archive
CI on an actual archived commit, complete policy acceptance, physical inference,
qualification, or Q1 campaign evidence. New source sealing and actual final
checks remain the parent's responsibility.
