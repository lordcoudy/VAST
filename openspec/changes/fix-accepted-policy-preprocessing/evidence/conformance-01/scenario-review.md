# Scenario Conformance Review

## Review Boundary

Review snapshot: 2026-10-11 20:37 UTC, active change
`fix-accepted-policy-preprocessing`, approved planning commit
`299c9c0eefb83fe3031096b0e96527236678a4d2`. This is independent technical
evidence, not human approval, final CI, completed implementation or Q1 readiness.
The runtime/parity evidence binds source build commit
`aca94dd0a57566d5a9ecc27d8dac1ca71ca0e795`; subsequent host pins and tests are
working-tree changes and must receive exact-final-commit checks separately.

All four delta requirements and fourteen scenarios are mapped below. `Proven`
describes only the stated boundary. `Outstanding` must not be inferred from an
injected assessment, a receipt self-hash, a source inspection or a dispatched CI run.

## Evidence Ledger

- `software-01/README.md`, `extraction-review.md` and
  `f5-extraction.verification.md` retain the first-slice commands/results:
  stock policy 16/16; F5 10/10; promotion plus F5 19/19; leaf extraction
  regression 8/8; guardian transaction lineage 3/3; identity suites 35/35;
  runtime source-closure checks 17/17. Their limits remain in those reports.
- `physical-01/packaged-reader-results.v1.json` and four retained reports prove
  28/28 fresh image-interpreter modes, including real held/unheld transaction
  descriptor reads. The artificial descriptor fixture is not complete semantic
  qualification. F1 is intentionally host-only; no F1 image import was faked.
- `physical-01/physical-results.v1.json` and retained independent parity audit
  prove fresh four-image A/B/refreeze evidence and parity 480 executions,
  32 groups, 1,920 execution members and 960 tensor files against the canonical
  reference. This is model parity, not accepted policy/Q1 evidence.
- The exact reviewed eight-file host-pin plan is
  `pins-01/host-pin-rebind.plan.v1.json`, SHA256
  `9faf81a6ade677afd6db3af947b3895ab286b43a93a8076602eaf5c173c3b311`.
  Its guarded application passed. CI fixture plan
  `ci-fixtures-01/ci-fixtures.plan.v1.json`, SHA256
  `602a4a1b7071d547934ef75af9873e4b3a430619e70d5035ef60ed91e3ab51fd`,
  was independently reviewed and applied: eleven fresh byte snapshots, all
  eleven old snapshot bytes retained, nineteen original origin rows retained,
  eleven additive rows, fixture-only/nonpublication flags unchanged.
- New F5 real-refusal tests pass 8/8 in 6.661 seconds. Their console output is
  `f5-real-refusals.green.log`. An intentionally corrupted valid-baseline
  control failed at the exact physical SHA predicate, retained in
  `f5-real-refusals.negative-control.log`; it is a negative control, not a newly
  discovered production defect. The first suite run had one overly specific
  test-message assertion; only that assertion was corrected, not production.

## Requirement 1: Authority-V2 Qualification Semantics

### 1. Authority-v2 promotion reaches the guardian consumer

Implementation: guardian `_default_assess_policy_qualification` at
`scripts/publication_guardian_accepted_policy_preprocessing_contract_v1.py:248`
selects shared authority-v2 fragment/F5 validators after cold transaction and
fragment-lineage checks. `_source_material` at line 457 independently loads
predecessor/closure/outputs; lines 732 onward compare the fresh full assessment
to exact coverage, capability, calibration and identities. Materializer at
line 1060 and standalone reader at line 1155 both use this path.

Proven: lineage/routing/custody tests pass 3/3; F1 promotion regression passes
9/9. The routing assessment spy intentionally supplies no qualification success.
Outstanding: a complete purpose-built promoted bundle passing both default
guardian materialization and independent cold load, with no upstream validation
substitution. The physical v2 fixture is under construction; no success is inferred.

### 2. Promotion lineage or physical evidence is foreign

Implementation: guardian verified physical descriptors and predecessor/index/
closure/transaction agreement at lines 457, 591, 631 and 733; the transaction
leaf's `cold_validate_committed_transaction_v2` and shared custody ContextVar;
the materializer validates source material before its receipt-last writer.

Proven: `tests/test_accepted_policy_guardian_transaction_lineage.py:130`
refuses foreign/mutated transaction descriptors before the assessment spy;
guardian unit tests at lines 570, 604 and 772 refuse accepted-output drift,
cross-run index lineage and unsafe/no-overwrite cases. Leaf tests at lines
133, 219 and 234 preserve cold mutation/link/custody refusals. Packaged cold
descriptor tests prove actual physical-reader mechanics under all four images.
Outstanding: broad genuine default-consumer mutations, including each listed
fragment/candidate/closure/parity/config/operational-accounting input, and
absence of every refused output namespace. Injected aggregate tests do not close this gate.

### 3. Component, study or historical evidence is presented as full qualification

Implementation: exact transaction kind/schema/nonaccepted scope at guardian
line 272, exact accepted policy kind/status at line 683, and unchanged strict
predecessor authority loaders. Matching totals/self-hashes cannot change kinds.

Proven: the lineage test explicitly refuses kind `study` and misleading
accepted/publication/authorization flags before assessment. Unsupported kinds
are rejected by exact kind checks. PR #7 remains closed/unmerged; no failed
attempt-4/G9 input was admitted to any repair promoter/materializer.
Outstanding: complete genuine-fixture component/unsupported-kind consumer
refusals. Historical raw pilot data must remain unexecuted by promotion, not
be fed to the consumer merely to manufacture this scenario's test result.

### 4. A legacy qualification is read independently

Implementation: stock `scripts/publication_policy_qualification.py` remains
byte-identical, SHA256
`f4478804491922c3e25ab414ba8f000c1964b46633f9dfb3a5bc87212748dbde`.
Authority-v2 selection is explicit in the guardian/F1, not a stock fallback.
Original builders re-export the same moved exception/default/custody objects.

Proven: stock policy 16/16; source/signature equality for all 58 moved
transaction/fragment definitions; pre/post-extraction cold success/refusal
and public object-identity tests. No legacy validator weakening was found.
Outstanding: final-commit regression rerun; prior focused results are not final CI.

## Requirement 2: Complete Decision Validation

### 5. Dropped GPU ingress has no transfer interval

Implementation: shared F5 at
`scripts/publication_policy_qualification_pilot_validation_v2.py:229`
excludes a GPU sample only for exact validated ingress terminal `drop` and
nonpositive transfer, after replay/cell/native identity/uniqueness/CSV/terminal/
actual-service checks. No interval or sample is invented.

Proven: original F5 test at line 197 checks the exact resulting sample set,
including preservation of a dropped GPU branch with positive transfer, and
stock refusal of the no-transfer branch. New portable baseline at
`tests/test_accepted_policy_f5_real_refusals.py:110` uses actual native/sidecar/
six-stream-reset validators and reaches only the unavailable dataset gate.
Outstanding: genuine full F5/default-consumer success using the physical fixture.

### 6. Completed GPU ingress has no transfer interval

Implementation: F5 line 245 refuses non-dropped GPU decisions without a
positive transfer; neither `completed`, `censored` nor missing ingress can
activate exclusion.

Proven: original focused test at line 212 refuses completed/censored/unknown
ingress with missing transfer. These decision tests isolate sidecar validators.
Outstanding: a completed/no-transfer mutation through the genuine complete
acceptance/default-consumer fixture; do not label the isolated test full acceptance.

### 7. A dropped decision has corrupt linkage or replay

Implementation: all F5 native decision predicates precede the exclusion;
accepted raw hashes and real sidecar/replay validators precede the decision loop.

Proven: original focused tests at lines 220 and 236 refuse invalid replay,
foreign cell, CSV/JSONL trace mismatch, branch terminal drift, invalid actual
service and duplicate native event. New actual-validator tests at lines 119,
127, 136 and 145 refuse changed on-disk native evidence, independent CSV and
JSONL duplicate IDs, and missing dropped-ingress association, with precise
error predicates. Semantic mutations rebind test-only physical hashes so a
stale descriptor is not mistaken for the intended semantic refusal.
Limit: only the upstream pilot acceptance reader is substituted in the new
portable F5 tests; native/replay/descriptor/sidecar/reset validators are not.
Outstanding: broad genuine upstream-acceptance refusal replay where feasible.

### 8. Existing valid samples and reset failures are checked

Implementation: exact stock-copy diff/hash lock plus six-stream reset
arguments at F5 line 143; all other sample fields and predicates are unchanged.

Proven: original test at line 252 compares CPU and positive-transfer GPU
samples directly to stock (isolated sidecar boundary). New tests at lines 155,
162 and 170 refuse missing reset physical input, malformed reset provenance
and incomplete six-stream process coverage using actual reset validators.
The missing-file F5 refusal occurs at accepted physical evidence, while the
same input independently refuses in the real sidecar loader.
Outstanding: genuine CPU/GPU-positive stock sample equality without upstream
substitution. Helpers at new-test lines 180 and 195 derive actual context and
compare actual F5/stock on a genuine arm, but have not run. A dropped GPU arm
without transfer is not a valid stock-equivalence input: stock must refuse it.

## Requirement 3: Measured Coverage

### 9. Coverage exceeds the minimum

Implementation: guardian `_validate_measured_coverage` at line 368 and
`scripts/full_publication_identity_artifacts.py:682` require exact integer
keys and measured samples >= 3,840, not equality with the minimum. Both sum
all 32 system/branch/resource calibration coordinates; the guardian additionally
compares complete fresh assessment/output equality at line 733.

Proven: guardian unit test at line 476 preserves 126,016 during materialization
and cold read with injected upstream assessment. The actual full-identity
policy reader test at `tests/test_full_publication_identity_policy_coverage.py:104`
preserves 126,016 and checks real capability/calibration/physical bindings.
Limit: the full-identity reader has no pilot/index replay authority; that test
is not 126,016 real pilot replays. Real native matrix test source enumerates
3,840/3,968, not 126,016 complete guardian success.
Outstanding: complete production guardian success for minimum/larger measured
fixture counts. Neither injected 126,016 nor native-sidecar totals substitute for it.

### 10. Coverage is at the supported minimum

Proven: guardian injected materialization/cold-read test at line 476 and actual
identity-reader test at line 96 preserve 3,840 under unchanged receipt kinds.
The production assessor still requires 32 cells x 4 branches x 30 samples.
Outstanding: complete genuine promoted guardian materialization/cold-read at
3,840. Source presence of the native 32-cell test is not a recorded full consumer result.

### 11. Coverage has the right total but incomplete cells

Implementation: stock `_validate_sample_rows` at line 861 enforces each branch
cell minimum, and the assessor at line 1026 retains that path. Guardian's fresh
assessment gate cannot be replaced by its aggregate calibration sum. Identity
validation separately requires all 32 balanced aggregate coordinates >= 120.

Proven: stock policy test at line 487 refuses missing pilot cells and duplicate
samples; guardian aggregate test at line 498 refuses missing/extra calibration
coordinates and underbalanced totals. Actual identity test at line 165 refuses
119/121 aggregate redistribution even when the overall total agrees.
Outstanding: genuine full-consumer per-cell minimum/absent/duplicate mutations
with a still-large matching total and no materialized output.

### 12. Count type or calibration total differs

Proven: guardian test at line 498 rejects bool/string/float counts, unsupported
keys, totals below 3,840, missing/extra coordinates and inconsistent totals
before writes. Actual identity tests at lines 113, 134, 155, 174 and 181
rebind all downstream physical/self-hashes before semantic count/calibration/
capability refusal, avoiding false SHA-only evidence.
Limit: guardian upstream assessment remains injected in these aggregate tests.
Outstanding: final-commit rerun and genuine-default assessment-disagreement
mutations in the complete fixture. The actual code still compares exact fresh
coverage/capability/calibration, not merely minimum totals.

## Requirement 4: Renewed Readiness

### 13. Packaged validator bytes change before Q1

Proven: exact 67-source shared graph / 93-source original full qualification
seed inventory, all four allowlist/COPY reconciliations, actual packaged
standalone/import-order/cold descriptor checks, deterministic runtime x4 A/B,
fresh refreeze/patch/parity, independently reviewed paired host pin application
and additive byte-exact CI fixtures. Native/worker invariance follows explicit
receipt-bound input inventory, not assumed image names. Historical namespaces
and canonical tags remain preserved.
Limit: the valid derived patch retains `candidate_binding_eligible=false`
and its two worker-identity refresh blockers. Fresh accepted model parity
binds the refreshed chain independently; the patch is not acceptance authority.
Outstanding: affected final source/executable/downstream authorities, complete
production consumer fixture, final exact-SHA hosted/ext4/integration checks,
archive/sync/final approval and the separate new qualification change/runbook.

### 14. A launch prerequisite is stale or unobserved

Proven: approved design requires all exact-final-commit checks and immediate
zero-unrelated-container/worker/GPU, volume-space, AC sleep/hibernation and
full-duration Update-pause observations. Pause coverage is the refreshed full
estimate plus at least six hours (35 hours for the historical 29-hour estimate),
not the old fixed 12-hour statement. The user launch intent persists, but it
does not waive the new qualification spec or input gates. PR #7 attempt 5 stays unstarted.
Outstanding: new qualification change, reviewed fresh runbook/input SHA and
immediate host observations. Existing observations/build-time idle evidence
expire and cannot authorize a future launch. A hosted workflow dispatch is not
exact-SHA CI success; its returned run head and required check conclusions
must be independently verified.

## Remaining Acceptance Limits

No dedicated automated requirement-to-behavior conformance CI gate exists;
this report does not create or impersonate one. Final hosted required checks,
the ext4 suite/approved skip comparison and all nine physical integrations
have not been established by this review snapshot. Complete genuine guardian
and downstream fixture results must be added before related tasks close.
No Q4, capacity, full-publication or campaign authority is established here.
