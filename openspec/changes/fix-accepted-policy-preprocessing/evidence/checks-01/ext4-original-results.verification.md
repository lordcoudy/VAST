# Original591 Ext4 Retention

The parent independently reviewed helper SHA-256
`bb012e68ad3928229f08238870c9c206b8ec5e41e8c618960a21b0c8c80928b2`
and exact plan SHA-256
`ecd8bfddc9df5b5ca07457a8698165cef0ad867df5c3cb19f91f2da1bc898928`,
then authorized one managed-only guarded apply. Shared snapshot primitives
remain at reviewed SHA-256
`01e4d5bfe1738167e8ec1da5b45104e349b2c5052fddc89ea71b5ba92bd4b6ed`.

The syntax-checked wrapper `run_ext4_original_retention.sh` has SHA-256
`590b53da50571c80be43983ef98792079dd0f71df3f664ccad2c7bf6f4e67b95`.
Original apply exited zero from `2026-10-11T21:51:35Z` to
`2026-10-11T21:51:36Z`, with empty stderr. Original stdout SHA-256 is
`fa42f5c941cdbd687634dbfda36a6de91b2e36ea002c8285e1ff74edd635d364`.

Exactly 76 original files, 12,930,417 bytes, are in fresh managed
`ext4-original-results/`: 27 outer controls/input-copy reports, 28 harness
reports/logs and raw source inventories, seven namespace diagnostic files,
five original observer streams/lifecycle files, and nine small acquisition
receipts. Compiled binaries/build trees and model/corpus/runtime/input trees
were not retained. The provenance catalogue `ext4-original-results.v1.json`
has SHA-256
`3ca5b360987d853e99dce65d71b47317870e8a99af96cad32a20792e542dee20`.

An independent read-only execution subsequently verified all 76 retained
destination hashes/bytes and all 76 recorded source physical epochs unchanged,
then rechecked SOURCE591 exact HEAD and clean tracked state. It exited zero;
its original saved stdout SHA-256 is
`18a15730a23fb9a11894463c1f8cfdc22b796a9b5909aa6f0d7b76a4df2bb3c8`.
Controls are in `ext4-original-retention-control/`. No SOURCE or CI-clone file
was written. Four authorized finite active/archive raw-byte rules cover only
these two output/control directories.

## Preserved Original Failure

Original session 44214 and parent both exited 1 at exact
`591a93e778a9a7839da6278326d215e24e91ea45`. The original harness ran 3291 tests:
3202 successes, two failures, one error, 86 unchanged-policy skips. The two
failed test IDs and one error ID are retained without relabeling in the plan,
catalogue, original reports, and logs.

The 86 actual skip IDs and reasons match the original committed selection
manifest exactly, and their audit matches its unchanged allowed rows;
`acceptance_claim=false` remains explicit. Selection manifest SHA-256 is
`09e9268069e88b957f9ae54a827960bc18ee13a00d4319994d108d3cb81a0805`.
Integration tests were not executed by this suite.

The original harness records `raw_checkout_bytes_match_commit=true` and no
changed tracked paths. Its before/after inventories are byte-identical,
SHA-256 `e09afd11f9b8a95cfd5a855af2d59da15341c5cf41a85e09c1594c709235379b`.
The original observer faithfully records child return code 1. These facts do
not make the suite pass.

The outer whole-mount comparison failed after the suite. The wrapper stopped
before its final source/byte gates; those gates are not claimed as executed.
Separate subsequent stock source verification is documented in
`ext4-independent-source-followup.md` and is not original-wrapper success.
Hardware, complete-consumer, qualification, and campaign acceptance remain
unproven by this retained run.
