# Independent 12 KiB accounting-slice working review

Verdict: CLEAR_WITH_NOTES.

Reviewed at HEAD b5f64480cccddebf3656e8c17c6520d448e26d7a under recorded planning approval https://github.com/lordcoudy/VAST/pull/9#issuecomment-6228062438. This is a working-byte review of the frozen accounting slice, not an exact implemented-commit or full-source approval. Active operator/Node work is excluded.

## Frozen reviewed files

- tests/fixtures/accepted_policy_fixture_compiler_component_v1.py: 32732 bytes; SHA256 329fb13f2c6dcee0872e5a29ec1fd769dc6e57ce92ee1076fef6737f1da86d88.
- tests/fixtures/accepted_policy_fixture_compiler_gate2_c_v1.py: 130783 bytes; SHA256 5a6c4b08ce3d381c355cbf72f93057c991b4adcb9d6ca8c43a638acd64f2ecf9.
- tests/test_accepted_policy_fixture_compiler_gate2_c_v1.py: 123945 bytes; SHA256 eee908c5fa72f8046dcc1665b5fb0e499ccff8c60bb86f604eb2010fcbc0fad3.
- tests/test_accepted_policy_fixture_compiler_gate2_resume_retention_v1.py: 15591 bytes; SHA256 1c7f801bc7bafea1bfb47ac7667b22b3555b6757927158730e4128afea91288c.
- openspec/changes/fix-accepted-policy-preprocessing/evidence/compiler-component-01/gate2-p0-465-retention.v1.json: 9998 bytes; SHA256 d310418f13e8a0afd287a1d774056ace70287f1d37a5841270a52e8dc5f8109c.

## Complete preservation and accounting checks

Pure in-memory inverse transformations, without executing project code, reconstructed the prior frozen bytes exactly:

- Reversing only the component resume-cap constant reconstructs 32730 bytes, SHA256 da997d0a2a79e72778bcfd374871a1fdf9fc5173d41419ed68713dddc5650436.
- Reversing C's initial charge, two resume-source fences, final outer tail and outside outer term reconstructs 130781 bytes, SHA256 1b981e75756598b3b10c7917927feb5295c69f76afcbc96b2af7147b5c14d196.
- Removing the appended plan version and retained_69_plan_Git assignment, restoring current_bindings[10]=16, the six changed numeric limits and the old new_outer upper reconstructs the complete 9829-byte prior index, SHA256 ceef345a82f39c8301706ecda73ea5d12cd1cf825e321b9214e409c6a64c2ab7.

The exact prior index hash establishes preservation of every historical datum, including the 21 versions, four roles, row16, refs, native extras and unknown observations. The new 22nd version is slot10, Git blob 8cf0afbf9dd122de6acb5682d9e470e4eacec358, 40901 bytes, SHA256 dc130a657a7c582c084f364425773f17e2487afb95cd65825e2e815041cf83d6. Current-plan binding is null/external. No index self-hash or future implemented-consumer commit was introduced.

Legacy CURRENT_CODE_FORMS_V1=524288 remains unchanged. The resume maximum is 991232 under 1032192, leaving 40960. A further distinct 40 KiB plan Git form adds 45056: 1036288 exceeds the cap by 4096. Full identity tuple deduplication retains size/SHA256 as well as Git identity.

C requires initial charge 29323264 exactly, with negative tests for adjacent values and wrong numeric type. Unchanged future liabilities 507510784 fit 507547648 available. FINAL adds 32768 outer plus 12544 P0-copy = 45312 AFTER the interval maximum. It preserves old debit 5345280, N<=2650112 and active F2<=7995392. Outside usage increases by 8192 inside its already-funded 524288 row; there is no additional global outside debit.

The reviewed bounds remain SOURCE 991232/1032192, native 1019136/1048576, outside 516352/524288 and global 536834048/536870912. These are bounded form assignments, not measured new-operation costs or a VHD peak guarantee.

## Controlled evidence inspected, not rerun

All three existing Temp originals were read and their bytes/hashes verified:

- vast-gate2-resume-source-12k-red-01.original.log: 1735 bytes; SHA256 2f04c77744437bd0dd9aaa901fbbe7b5c6b1d24e5bb24185a04a606df1668834. One test reports a real ComponentRecipeError: resume forms bound.
- vast-gate2-resume-source-12k-green-02.original.log: 16549 bytes; SHA256 2cb46e20b3d34ac51ad74afa44e6b8c0ef35c7faed339674976238977851fb07. 74 tests passed in 3.018s.
- vast-gate2-resume-source-12k-green-03.original.log: 1746 bytes; SHA256 b155ed759b8ad706679af5559e53b7ccfeb9227b781dcbbd77da98f8ab72e34f. Seven source-form cases passed in 0.257s.

The final retention test directly requires the actual 22nd version and null current-plan binding. Its transitional 21-version self-repair was removed after review; the original RED remains retained. No test was executed by this reviewer.

## Actual-form audit reference and limits

Root-produced development audit: gate2-implementation-tests/resume-current-source-forms-12k-05.derived.json, 7473 bytes; SHA256 7e6e0fb9002e09f570e3cde37f579a11320ac3f4ca4e41f961d12449422bfbcf. This review verified the record's identity and scope, not a replay of its Windows API observations.

The audit records current14 same-FD Windows allocations and all22 existing historical Git blobs, with prospective first source-commit forms: SOURCE working385024 plus 10 distinct Git forms606208 = 991232; helpers204800; index working/prospective-Git forms32768. S/N/O assignments are 991232/1019136/516352. It records new Git objects written=0, physical_acceptance=false and task_2_10_complete=false. Current new Git forms remain prospective until the implementation commit; the audit is not source approval or a native workload/export/capture.

No blocking accounting discrepancy remains in the frozen slice. Final caller/source integration, exact implemented-commit independent reviews, required implementation CI and final actual-form checks remain outstanding. Historical failed attempts, unavailable closing/peak and unknown old child closure remain unaccepted. This review grants no physical, packet, C/D, whole1.5, archive or merge approval.

The review made no source/test/index/planning/Git changes, broad reruns, native/WSL/component calls or physical actions. This separately authorized new development-review file is its sole write.
