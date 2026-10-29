# Next Exact-Source Reconstruction Copy Draft

This draft prepares the already-reviewed copy-only restoration for a new exact
source commit. No v2 plan generation, copy, stock corpus revalidation, source
clone, or check worker was executed. Only Python AST parsing and Bash `-n`
syntax checks ran; both exited zero without executing either helper.

## New Files

- `copy_reconstruction_inputs_v2.py`, SHA-256
  `d6e3fc1286fabb9127cae9417de0b6f05689c6d3e1c90951dd0149cbe4bbfbf6`.
- `run_reconstruction_input_copy_v2.sh`, SHA-256
  `31bbb99e0ed4a4aa3593abb1e9e97a24dc78ef1c5896d80c0b1566813f40df58`.

The sealed591 v1 helper and wrapper remain unchanged at SHA-256
`f6fc58865cbebb67bb55c1677673a8dd24ea4f8ca44314f749acdc0f69095474`
and `c5d6de8f3b56ff3c2cd31eb968d912f2caf6ce1781aa10f88daa3484beb8f03f`.
The new helper does not import or override globals in the old helper.

## Exact Commit Binding

The helper requires `--source-commit` before its `plan` or `apply` subcommand;
there is no source-commit default. A lowercase 40-digit hexadecimal SHA maps
only to `/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-source-`
plus that SHA. Any explicit project root must equal this literal derived root.
The physical root must be plain, HEAD must equal the supplied commit, and
tracked state must be clean. `apply` separately requires the supplied commit
to equal the reviewed plan commit before rederiving and comparing the plan.

The small change threads the explicit commit through existing source, authority,
planning and apply functions. No reusable abstraction or production API changes
were introduced. Exact five stock authority modules and dataset catalog bytes
still match that commit. Both retained D1 and E-workspace source inventories
still require the real stock gate and unchanged exact 12 descriptors.

The existing plain-chain, single-link file, physical-epoch, streaming SHA/size,
exclusive `O_NOFOLLOW` copy, fresh tree, fsync, post-copy stock gate, and both
source-after inventory checks are retained. An explicit `git check-ignore -q`
gate now checks all 12 target paths before and after copying. A failure does
not authorize rewriting, adopting, removing, freezing, or transforming data.

## Prepared Invocation

After the parent seals and creates the next source root, it supplies the real
`NEW_SHA`. Read-only plan generation will be:

```bash
PY=/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python
MANAGED=/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/openspec/changes/fix-accepted-policy-preprocessing/evidence/checks-01
"$PY" -B "$MANAGED/copy_reconstruction_inputs_v2.py" --source-commit "$NEW_SHA" plan
```

The exact generated plan bytes must be saved and independently reviewed before
copy approval. The wrapper then requires all four named inputs:

```bash
bash "$MANAGED/run_reconstruction_input_copy_v2.sh" \
  --source-commit "$NEW_SHA" \
  --plan "$REVIEWED_PLAN_ABSOLUTE_PATH" \
  --reviewed-plan-sha256 "$REVIEWED_PLAN_SHA256" \
  --reviewed-helper-sha256 d6e3fc1286fabb9127cae9417de0b6f05689c6d3e1c90951dd0149cbe4bbfbf6
```

The wrapper uses the canonical Python and source-root committed recipe's
original HEAD/clean/ext4/raw-tracked-byte gates before and after apply.
It records original stdout/stderr, return code, timestamps, source commit and
helper/plan/wrapper hashes in a fresh `reconstruction-inputs-copy-v2-<SHA>`
controls directory; no prior control directory is reused. These are prepared
commands, not evidence of execution or authorization to run them.

There is no CI selection, workflow, skip-policy, historical-receipt, descriptor,
media, or production-source change. Successful future input restoration would
only supply ignored regression-check assets; it would not establish complete
consumer, qualification, campaign, or historical-v1 identity acceptance.
