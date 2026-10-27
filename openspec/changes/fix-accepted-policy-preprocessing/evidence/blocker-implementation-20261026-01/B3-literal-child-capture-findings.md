# Remaining literal Git and raw-source-proof capture requirements

Independent read-only source audit at d9d5813180ad402c5efe720af65fdc88063bf2f1
by /root/blocker_plan_review found three unbounded positive Git captures and
at most four direct negative Git captures plus two Python raw-source proofs.
Each proof invokes three nested Git commands in run_ci_checks: ls-files,
object-format and ls-tree. Imports load five repository scripts, 114679 raw
bytes, without invoking CI main or their operational routines.

Reuse _capture_owned_reader_v2 unchanged with a fixed command/name roster and
the original sealed reader clock. Require the same qualified Git executable,
configuration/filter/helper/trace environment and explicit worktree bindings:
GIT_DIR=/mnt/e/STUDY/VAST/.git/worktrees/VAST8 and
GIT_WORK_TREE=/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST.
Do not mutate the parent environment or .git to supply them.

Outer 1 MiB channels do not bound nested Git buffers, split/decoded path lists,
ls-tree dictionaries/comparison sets, Git metadata/decompression or imports.
Seal maximum entry count, individual/aggregate paths, inventory bytes, tracked
file sizes/aggregate hashing I/O and heap before calling the existing proof.
verify_committed_bytes already accepts absolute_deadline_ns; the current caller
omits it. Pass the observation boundary derived from the same inherited clock.
Nested fixed timeouts do not replace ownership, closure or the parent deadline.

Initial captures need a separately admitted fresh evidence namespace because
the preparation output must remain absent. Precheck the complete fixed path
roster before writes; retain partial failures and consumed names. HEAD's
41-byte stdout and clean status's zero-byte stdout are semantic expectations,
not allocation limits. Price both 1 MiB channels: positive raw retention up to
6 MiB, negative direct Git plus proof channels up to 12 MiB, before copies,
records and metadata. Validate proof JSON and retain transcripts by reference.

The negative finally can replace an initiating error with after-proof, Git or
report persistence errors. Preserve original and distinct secondary causes.
An expired clock must prevent another spawn. Reuse existing bounded encoding
and _write_result_v2 with original status/EOF/ownership/persistence facts; a
retained prefix cannot be accepted as complete output.

This is a source audit, not implemented capture, execution or CI redesign.
The subsequent B3-literal-reads-checkpoint.md closes the two fixed observation
file reads and entrypoint hashing adapters only; the child captures above and
the negative source-plan selector remain open.
No test, workload or provider command was run by the reviewer. Source anchors:
consumer-01/build_production_fixture_v2.py:75,
consumer-01/build_per_cell_minimum_refusal_v1.py:23 and :177,
scripts/run_ci_checks.py:142 and :179,
tests/fixtures/accepted_policy_standalone_reader_fixture_v2.py:236.
