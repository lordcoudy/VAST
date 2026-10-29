# Independent Source Follow-Up After Original Ext4 Failure

This is attributed technical text evidence from independent reviewer
`/root/stage2_contract_audit`, not a reconstructed original raw stdout file.
It is separate from failed original session 44214 and its stopped wrapper.
No verification rerun or SOURCE/CI-clone write was performed by the retention
author for this note.

The reviewer reported tool chunk `bf5c2d`, original return code zero, for:

```powershell
wsl --distribution Ubuntu --user s-a-balashov --exec /bin/bash -c 'export VAST_REPAIR_CHECK_ROOT=/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-source-591a93e778a9a7839da6278326d215e24e91ea45; source "$VAST_REPAIR_CHECK_ROOT/openspec/changes/fix-accepted-policy-preprocessing/evidence/checks-01/recipe_common.sh"; assert_frozen_root 591a93e778a9a7839da6278326d215e24e91ea45; assert_committed_bytes "$ROOT"; assert_committed_bytes /home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-ci-591a93e778a9a7839da6278326d215e24e91ea45; printf "%s\n" ORIGINAL_SOURCE591_AND_CI591_RAW_BYTE_CHECK_PASS'
```

The reported original stdout marker is
`ORIGINAL_SOURCE591_AND_CI591_RAW_BYTE_CHECK_PASS` followed by one newline.
The tool also emitted the usual WSL localhost-proxy/NAT warning; the reviewer
did not classify that warning as a source or test failure.

The verifier used the exact SOURCE591 committed recipe functions and stock
`run_ci_checks.tracked_paths` / `verify_committed_bytes` for both source and
CI clones. The reviewer separately reported CI `rev-parse HEAD` at exact
`591a93e778a9a7839da6278326d215e24e91ea45` (chunk `4f4f60`, return code zero)
and empty tracked `status --porcelain --untracked-files=no` output (chunk
`d2cd7a`, return code zero).

These are independent later raw-source observations. They do not establish
that the original wrapper's stopped final gates executed, do not erase its
whole-mount mismatch, and do not change the original suite's two failures,
one error, or return code 1. New-source checks remain necessary after fixes.
