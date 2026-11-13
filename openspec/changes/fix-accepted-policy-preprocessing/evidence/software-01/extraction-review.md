# Transaction and Fragment Validation Extraction

## Scope and Baseline

- Reviewed planning commit: `299c9c0eefb83fe3031096b0e96527236678a4d2`.
- Worktree: `C:/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST`.
- Canonical interpreter: `/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python` (Python 3.12.3).
- WSL distribution: Ubuntu; worktree path: `/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST`; temporary directories use `TMPDIR=/var/tmp` for native physical custody.
- No historical pilot, transaction, promotion, or preprocessing receipt was used as acceptance evidence. No Docker operation or long qualification suite was run.

The initial worktree lacked ignored OMZ model assets. Eight XML/BIN files were copied from `E:/STUDY/VAST` to the same relative paths after verifying `git check-ignore`, refusing existing destinations, and checking source/destination SHA256 equality. These hashes match `configs/checkpoint_analytics_models_openvino.yaml`:

- `vehicle-license-plate-detection-barrier-0106.xml`: `69ed174cee70e19b098215f53d1fe6f27edc5b417790bbc44cde7f37cc082fae`
- `vehicle-license-plate-detection-barrier-0106.bin`: `7f96bfaa0ac3af65d136f6a185d1d78d68d03bab2e1f2faafe1d27ccd94b0dc1`
- `vehicle-detection-0202.xml`: `08b844a402a615605a626261fd9e27161a044845426ece5aa0872203c50bb5a2`
- `vehicle-detection-0202.bin`: `c0a602428cfd71ac63a533c23b7cdb8c83e144f118a81001420246701daf0c78`
- `person-vehicle-bike-detection-2002.xml`: `2630c4cc5a68d8b1f7f224741340ddf8f733e245252379c691083c7d3dc111ed`
- `person-vehicle-bike-detection-2002.bin`: `7f9344e41167d14179a0da136f87f2570a30ac5399e0363fd6787a9ae18d0fa0`
- `person-vehicle-bike-detection-crossroad-1016.xml`: `baed27b9dde81b75590a382d2aa458d63391cdb146e7ef20c12577c4cb0617d8`
- `person-vehicle-bike-detection-crossroad-1016.bin`: `a7f04e3243aae3099a00c5276074bdbe57bc8bf91986093dfeafb3b065843f45`

## Compatibility Evidence

`publication_policy_qualification_transaction_validation_v2.py` owns the shared transaction exception, custody ContextVar, physical descriptor readers, read-only default authority loaders, and committed receipt validators. The public `cold_validate_committed_transaction_v2` is an alias of the unchanged original `_cold_validate_committed_transaction`. Writer-only `TransactionDependencies` and its default instance remain builder-owned.

`publication_policy_qualification_fragment_validation_v2.py` owns the shared fragment exception, `FragmentAuthorityDependenciesV2`, its one default dependency instance, read-only authority loaders, and both existing authority-v2 validator functions. The original builders explicitly reexport the moved objects. The original fragment test's private `_descriptor` patch now targets the defining validation module.

All 58 moved function/class definitions, including decorators and signatures, were compared to the approved commit with both AST and exact normalized source extraction. There were no mismatches. The regression suite freezes these source hashes:

- Transaction, 18 definitions: `848cfb033614e531c9133e2a847064de7881feeeda4d3ae0169b8c7265dbdb4e`.
- Fragment, 40 definitions: `dba29d7fd618f83a92e6b1b7742d8a84f13600a7539d106a6e5aa3b6a7cf46ea`.

## Focused Commands and Outcomes

Run each command from the WSL worktree with the canonical interpreter above and `TMPDIR=/var/tmp`:

```sh
python -B -m unittest discover -s tests -p test_publication_policy_qualification_transaction_v2.py -v
python -B -m unittest discover -s tests -p test_publication_policy_qualification_fragments_from_authority_v2.py -v
python -B -m unittest discover -s tests -p test_publication_policy_qualification_validation_leaves_v2.py -v
PYTHONPATH=tests:scripts python -B -m unittest test_publication_policy_qualification_transaction_v2 test_publication_policy_qualification_fragments_from_authority_v2 test_publication_policy_qualification_validation_leaves_v2 -v
```

- Pre-extraction transaction baseline: PASS, 12 tests.
- Pre-extraction fragment baseline with real copied model assets: PASS, 6 tests, 28.383 seconds.
- Post-extraction transaction: PASS, 12 tests, 1.741 seconds.
- Post-extraction fragment: PASS, 6 tests, 26.816 seconds.
- Initial extraction-specific suite: PASS, 6 tests, 2.679 seconds.
- Combined focused suite at that stage: PASS, 24 tests, 33.692 seconds.
- Final extraction-specific suite after adding explicit link and held-custody cases: PASS, 8 tests, 2.932 seconds.
- `git diff --check`: PASS.

Extraction-specific coverage includes all moved object identities, shared dependency defaults and signatures, the transaction custody ContextVar, exact cold success/refusal outputs, symlink and hard-link refusal, held-custody descriptor reads and custody failures, recursive AST import closure excluding host/builders, standalone leaf imports, and both builder/leaf import orders in fresh interpreters.

The stock `publication_policy_qualification_execution_code_closure_v1._discover_sources` literal-import scanner returns exactly 67 modules for both the guardian seed and the combined transaction/fragment leaf seeds after consumer integration: the prior 63 plus `analytics_execution_capability` and the three validation leaves. No host builder/executor/F1 module was added. The leaves have no direct guardian or sidecar imports; the old dependency graph still reaches those modules transitively through pre-existing lazy-import edges. This is not a claim that the full literal graph is acyclic. Fresh standalone import and import-order checks cover actual initialization separately.

## Independent Consumer Review

Reviewed the guardian default lineage/routing and measured-coverage changes, plus full-publication identity count/calibration validation and their focused tests, against the approved spec/design. No remaining implementation blocker was found in this reviewed surface. Verdict: `PASS_WITH_NOTES`, not human approval or overall readiness.

One required finding was raised and resolved: the first guardian revision invoked the extracted cold transaction reader without enabling its shared custody ContextVar. The root owner fixed this by opening the same leaf `PhysicalRootCustodyV1`, setting the shared `_ACTIVE_CUSTODY`, running the unchanged cold reader, verifying held custody, and resetting the token in `finally`, inside the existing translated `_call` error boundary. Independent follow-up review confirmed that this matches the original public builder cold phase.

Follow-up command and result:

```sh
TMPDIR=/var/tmp PYTHONPATH=tests:scripts python -B -m unittest test_accepted_policy_guardian_transaction_lineage -v
```

PASS: 3 tests, 0.086 seconds. The new success/refusal test uses real held descriptor reads with a spy, checks both transaction JSON reads take the held branch, and confirms context restoration in both outcomes. The root owner separately recorded a two-subcase RED result before the fix; this reviewer independently observed the final GREEN result only.

Before that fix, the existing lineage, guardian and real identity coverage suites were independently run together: PASS, 17 tests, 5.639 seconds. This verifies narrow routing/count behavior, not a complete production qualification. The guardian's fresh stock assessment still enforces exact outputs and all 32 pilot cells; the identity reader checks bound complete calibration/capability coordinates, integer samples, 120 balanced minimum per aggregate coordinate and the exact measured total, without claiming independent pilot replay.

Remaining notes: the full production-default promoted fixture is a separate required gate still under construction at this review. Packaged builds/checks, parity/repin, complete promotion/materialization/cold-read rejection coverage, exact-commit CI/ext4/integration and future Q1 launch prerequisites are not established by these focused suites.

## Limits

This evidence does not establish production guardian qualification acceptance, Docker build parity, host behavior, repinning, image reconstruction, or Q1 readiness. The production-default complete guardian fixture and broader checks are independent gates.

The noncanonical Windows Python 3.14 environment lacks pandas and exhibited pre-existing Windows custody projection failures before extraction. Those environment failures were not changed or counted as canonical acceptance. The first fragment run without ignored models failed fixture setup; a read-only model-source overlay diagnostic passed, but the actual before/after baseline above was rerun using real copied assets, not an overlay.
