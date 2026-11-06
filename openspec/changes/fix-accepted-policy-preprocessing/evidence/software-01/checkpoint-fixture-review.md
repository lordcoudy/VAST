# Checkpoint Fixture Review

Test-only producer: `tests/fixtures/accepted_policy_checkpoint_fixture_v1.py`,
SHA-256 `de084fbda62ad3d2f866c47358b4baa81574a3462c083f8f6f45e9b082b99c58`.
Refusal tests: `tests/test_accepted_policy_checkpoint_fixture_v1.py`,
SHA-256 `0c0965a2c0983ff79d4ffbaa9b01116fa5bd8efc89897fafa7ab3a3ffe65a7e8`.

The helper selects the actual executor module from the caller's exact project
root, holds the stock physical-root custody/context, and uses actual
qualification/code-closure/operational loaders. Service authority, preprocessing,
and runtime-expectation validators are their production defaults. No runtime
runner, input loader, file reader, or service validator is replaced.

All 32 finalized pilot namespaces and acceptance operational bindings are
validated with the executor's stock functions. Checkpoint entries, deterministic
matrix hash, named input hashes, source/interpreter physical identities, and
execution barriers use stock builders. The stock exclusive writer preserves
nonpublication/nonauthorizing fields. Stock checkpoint reload and a separate
held-custody cold scan verify all 512 evidence leaves and complete pinned input
namespace without altering their recorded paths, snapshots, or hashes.

First RED: both tests failed import because the new helper did not exist
(exit 1, errors=2). Initial GREEN: both refusal tests passed in 0.795 seconds.
After using the existing stock execution-barrier helper before and after write,
the combined bounded command passed:

```text
wsl -d Ubuntu --cd /mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST --exec env TMPDIR=/var/tmp /home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python -B -m unittest -v tests.test_accepted_policy_checkpoint_fixture_v1 tests.test_accepted_policy_guardian_lifecycle_fixture_v1
```

Result: exit 0, four tests, 0.920 seconds, no failures/errors/skips. The two new
checkpoint tests prove a loaded executor cannot authorize another project root,
and an output cannot escape the selected root before writes. They do not prove
the complete successful 32-cell path; that remains an explicit real-graph
consumer-fixture check, not inferred from refusal tests or code inspection.
No active fixture worker was interrupted, no historical pilot admitted, and no
Docker or full suite was run by this helper author. No owned session remains.
