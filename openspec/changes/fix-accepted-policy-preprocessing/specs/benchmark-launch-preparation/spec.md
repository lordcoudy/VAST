## ADDED Requirements

### Requirement: Accepted policy consumers preserve authority-v2 qualification semantics
Accepted-policy guardian preprocessing SHALL cold-revalidate a promoted full qualification bundle with validators matching its independently validated authority-v2 transaction lineage. The transaction, four fragment descriptors, completed index, execution closure, candidate and accepted outputs SHALL bind to the same physical evidence and policy/dataset/model/runtime identities. Successful materialization SHALL retain the existing receipt-last contract and post-qualification Q4 preprocessing scope; it SHALL NOT establish Q4, capacity or full-publication eligibility. Legacy qualification entrypoints SHALL retain their existing validation behavior.

#### Scenario: Authority-v2 promotion reaches the guardian consumer
- **WHEN** an authority-v2 qualification has complete current transaction and execution closure, all 32 cells and matching accepted policy outputs
- **THEN** the production guardian materializer and its standalone cold reader SHALL independently accept the bundle, revalidating real fragments and pilots without a substituted assessment or legacy-only identity requirement.

#### Scenario: Promotion lineage or physical evidence is foreign
- **WHEN** a transaction, fragment, index, closure, candidate or accepted output is missing, substituted, mismatched, changed, outside its physical root or linked to a different qualification
- **THEN** materialization SHALL refuse before creating output directories or files, and a cold reader SHALL refuse the affected receipt; matching aggregate totals or a self-hash alone SHALL NOT confer acceptance.

#### Scenario: Component, study or historical evidence is presented as full qualification
- **WHEN** a component, study, unsupported-kind artifact or the failed attempt-4 diagnostic is supplied as a fresh accepted full qualification
- **THEN** full consumer eligibility SHALL remain false; diagnosis SHALL NOT promote, relabel or rewrite that evidence.

#### Scenario: A legacy qualification is read independently
- **WHEN** a public legacy qualification entrypoint reads historical evidence without authority-v2 lineage
- **THEN** its existing strict validators and outcome SHALL remain unchanged, with no implicit fallback that substitutes authority-v2 acceptance for failed legacy validation.

### Requirement: Policy calibration samples retain complete decision validation
Authority-v2 policy pilot validation SHALL require reset evidence for six streams and preserve every existing acceptance, decision replay, native identity, CSV/JSONL linkage, uniqueness, branch terminal and actual-service check. Only a GPU decision tied to a validated ingress terminal exactly equal to `drop`, with no positive native transfer interval, SHALL be omitted from calibration samples after all decision checks pass. CPU samples and GPU samples with positive transfer intervals SHALL retain their reviewed stock semantics. Every branch in every system/resource/codec/topology cell SHALL still supply at least 30 valid samples.

#### Scenario: Dropped GPU ingress has no transfer interval
- **WHEN** an otherwise valid GPU decision has a validated dropped ingress frame and no positive transfer interval
- **THEN** the decision SHALL remain fully checked and SHALL contribute no calibration sample or invented interval.

#### Scenario: Completed GPU ingress has no transfer interval
- **WHEN** a GPU decision on a completed ingress frame lacks a positive transfer interval
- **THEN** qualification assessment and accepted-policy preprocessing SHALL refuse it.

#### Scenario: A dropped decision has corrupt linkage or replay
- **WHEN** a dropped ingress decision has a missing ingress association, invalid replay, changed native evidence, duplicate identity or mismatched CSV/JSONL linkage
- **THEN** assessment SHALL refuse before considering sample exclusion; dropping the frame SHALL NOT bypass validation.

#### Scenario: Existing valid samples and reset failures are checked
- **WHEN** CPU decisions or GPU decisions with positive transfer intervals validate, or six-stream reset evidence is incomplete or invalid
- **THEN** valid samples SHALL equal the reviewed stock samples for those decisions, while invalid reset evidence SHALL still refuse the bundle.

### Requirement: Accepted policy coverage records measured counts
The accepted-policy guardian consumer and full-publication identity reader SHALL require exactly 32 bindings and 32 pilot cells, a minimum of 30 samples per branch cell, and an exact integer accepted-sample count of at least 3,840. Booleans, fractional numbers, strings, unsupported coverage keys, missing coordinates and inconsistent totals SHALL refuse acceptance. Measured counts SHALL equal the complete calibration sample total; the guardian consumer SHALL additionally require exact agreement with its fresh full qualification assessment and all accepted outputs. Counts SHALL NOT be capped or rewritten to the minimum.

#### Scenario: Coverage exceeds the minimum
- **WHEN** a valid promoted policy has 126,016 measured samples, complete calibration totals and matching fresh assessment
- **THEN** both consumers SHALL preserve that count and accept coverage without requiring it to equal 3,840.

#### Scenario: Coverage is at the supported minimum
- **WHEN** all 32 cells and every branch satisfy their minimum and the count and calibration total equal 3,840
- **THEN** coverage SHALL remain valid under the existing accepted receipt kind and schema.

#### Scenario: Coverage has the right total but incomplete cells
- **WHEN** the total exceeds 3,840 but a branch cell is below 30, absent or duplicated
- **THEN** the full assessment SHALL refuse, and the guardian SHALL not materialize accepted-policy inputs.

#### Scenario: Count type or calibration total differs
- **WHEN** coverage uses a boolean, fraction, string, unsupported key, fewer than 3,840 samples, or a total inconsistent with calibration or fresh assessment
- **THEN** the corresponding consumer SHALL refuse before creating any materialized output.

### Requirement: Validator repairs renew affected qualification readiness
A packaged accepted-policy repair SHALL invalidate affected image/source/parity/pin and execution-closure readiness. Before the next Q1 launch, all affected deterministic builds, packaged checks, physical parity, required CI, ext4 and integration checks SHALL pass on the exact renewed input commit, with independently reviewed changes to the qualification runbook. Renewal allocations SHALL require fresh physical backing capacity sufficient for the conservative peak of the whole build/check/consumer chain, including retained inputs, images, outputs, evidence and backups, while preserving at least 40 GiB free on C: and every involved filesystem's applicable threshold. Launch observation SHALL establish zero unrelated containers, VAST workers and GPU compute jobs, sufficient space on every required volume, disabled AC sleep/hibernation and a Windows Update pause covering the entire current execution estimate plus an explicit margin. Historical receipts SHALL remain immutable.

#### Scenario: Packaged validator bytes change before Q1
- **WHEN** the repair changes a source copied into the runtime images or reachable from the qualification code closure
- **THEN** affected inputs and authorities SHALL be regenerated under fresh identities before dependent execution; previous image/parity/closure receipts SHALL NOT be silently rebound.

#### Scenario: A launch prerequisite is stale or unobserved
- **WHEN** a required check is missing, fails, applies to another commit, or the observed host protection does not cover the complete run duration
- **THEN** Q1 SHALL remain unstarted until the prerequisite is renewed and accepted.

#### Scenario: The whole renewal chain lacks backing capacity
- **WHEN** fresh physical capacity cannot cover the conservative whole-chain peak while preserving the C: 40 GiB floor and applicable filesystem thresholds, or the peak is unqualified
- **THEN** dependent copying/building/check/consumer allocations SHALL remain held with a recorded shortfall and concrete remedy; a first-stage allowance, virtual capacity, historical sample, blind retry or lowered floor SHALL NOT admit the chain.

### Requirement: Integrated repair preserves accepted storage behavior and evidence boundaries
The accepted repaired baseline SHALL preserve the accepted S3 export/recovery contract and supported historical Seafile reading while retaining the complete inherited implementation and repair's reviewed behavior. Integration acceptance SHALL require independent review of the entire inherited/repair diff at its exact integrated commit, required current checks and genuine scenario conformance. Repair sync/archive SHALL preserve the accepted S3 main requirements/archive and every unaffected main requirement/scenario. Historical failed qualification documents, unchecked tasks, raw evidence and identities SHALL retain their original disposition; code integration SHALL NOT establish qualification, Q4, capacity or full-publication eligibility. All 227 retained images SHALL remain protected unless explicit human confirmation covers the exact images and deletion/offload action.

#### Scenario: Accepted storage delivery and operational execution are combined
- **WHEN** the repaired baseline combines the accepted S3 delivery with the inherited operational supervisor/service behavior
- **THEN** downstream export and supported recovery SHALL retain verified upload/readback/receipt/durable-ledger-before-owned-prune and existing stop/recovery outcomes, historical Seafile readers SHALL remain usable, and independent integrated-input checks SHALL establish the combined behavior before baseline acceptance.

#### Scenario: Failed qualification is inherited with working code
- **WHEN** integration includes the stopped `qualify-full-benchmark` change and its implementation
- **THEN** its PR SHALL remain closed/unmerged, attempts 1-4 SHALL remain failed, attempt 5 SHALL remain unstarted, tasks 6.2/7.1-7.6/8.1-8.2 SHALL remain unchecked and the incomplete change SHALL remain unarchived; only a distinct fresh qualification SHALL establish future acceptance.

#### Scenario: Repair finalization would discard retained contracts or evidence
- **WHEN** repair sync/archive, integration or retention would remove an unaffected main requirement/scenario, the accepted S3 archive, an original failed receipt/raw input, either retained version of staged-and-modified evidence, or an image without exact human confirmation
- **THEN** finalization SHALL refuse until preservation or the applicable exact image authorization is established; successful backup, recovery, format checks, author checks or delegated agent approval SHALL NOT substitute for those gates.
