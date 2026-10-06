## MODIFIED Requirements

### Requirement: Benchmark recovery has explicit execution and completion gates
Recovery SHALL deliver a reproducible selected component command and four genuine GStreamer/H.264 native arms through two separately owned baseline/shared contexts for CPU and GPU. It SHALL preserve six streams/four branches, seed20260323,100ms deadline, paired schedules/order,30-second warmup/180-second measurement/10-second drain, original model/intake/source/graph semantics, complete operational identities and strict measured physical checks. Accepted component results SHALL retain raw evidence and current source/model/resource/owner bindings, descriptive comparisons and explicit limits. Any changed identity SHALL invalidate affected readiness. Component completion SHALL NOT establish full campaign readiness, counts, authority or publication eligibility; legacy full gates SHALL remain strict and SHALL remain explicitly unexecuted until a reviewed staged full-campaign change actually executes and accepts them under their unchanged predicates; component or study evidence SHALL never satisfy them. Standing authorization permits autonomous work but SHALL NOT substitute for actual checks/review.

The separately typed finite-component-study objective SHALL require all 24 prescribed effect arms and 12 paired comparisons on one current final bundle, complete raw accounting and independent reduction, unchanged within-pair bindings, bounded physical closure, current mandatory CI and conformance. A valid negative performance result SHALL be admissible; a pilot or partial matrix SHALL NOT satisfy this objective. For this new canonical objective only, the legacy 32 qualification campaigns, Q4 and 5600 full matrix SHALL be superseded as execution and completion prerequisites. Their historical unexecuted/false/zero dispositions and original register SHALL remain unchanged. Strict legacy qualification, promotion, Q4, publication and full entrypoints SHALL retain their exact-kind/readiness/rejection predicates and SHALL NOT accept a study artifact as full authority. This objective SHALL NOT relabel prior component, decoder, metadata or pilot evidence as the 24-arm study.

#### Scenario: Preparation succeeds
- **WHEN** every required component release gate is accepted and current
- **THEN** the evidence packet SHALL report component_release_complete=true with four actual component arms/two pairs and current evidence, while full_run_started=false and qualification/Q4/publication/full eligibility remain false; unexecuted campaign counts SHALL remain zero.

#### Scenario: Readiness ages or inputs change
- **WHEN** a guardian identity, source, configuration, image, capacity basis, or other bound prerequisite changes after handoff
- **THEN** affected readiness gates SHALL be invalidated and stock preflight SHALL be repeated before dependent launch or supported resume, without silently rebinding historical receipts.

#### Scenario: A staged full-campaign change executes a legacy gate
- **WHEN** a reviewed staged change executes fresh full qualification, Q4 or the full matrix
- **THEN** only that stage's own fresh receipts SHALL change its disposition; the strict legacy predicates, historical failed attempts and all later stages SHALL remain unchanged, and component or study artifacts SHALL still be rejected as full authority.

## ADDED Requirements

### Requirement: Legacy runtime wall stamps are strictly increasing per process
Every legacy full-campaign runtime process that stamps wall-clock time and later compares the ordering or positive width of those stamps (native probes, the DeepStream SDK runtime and protocol bridge, the Savant runtime and the guardian operational recorder) SHALL derive those stamps from one per-process non-decreasing source: each stamp SHALL be max(previous+1 ns, raw CLOCK_REALTIME), a backward raw step larger than 10 ms SHALL fail closed with an explicit error, and the largest applied clamp SHALL be retained in the process evidence. Ordering and width predicates SHALL remain unchanged. Cross-process comparisons SHALL keep their documented residual limits and SHALL NOT be relaxed.

#### Scenario: The host clock steps back by a few milliseconds
- **WHEN** CLOCK_REALTIME steps back by about 2 ms between two stamps of one process
- **THEN** the later stamp SHALL be exactly 1 ns after the earlier one, every ordering and positive-width check SHALL pass, and the retained max clamp SHALL report the applied step.

#### Scenario: The host clock steps back beyond the bound
- **WHEN** CLOCK_REALTIME steps back by more than 10 ms within one process
- **THEN** the process SHALL fail closed with an explicit clock error and SHALL NOT fabricate ordering, retry or accept the affected operation.

#### Scenario: A runtime bypasses the shared source
- **WHEN** a covered runtime file stamps wall-clock time for an ordered or width-checked field without the shared non-decreasing source
- **THEN** a static source check in CI SHALL fail.

### Requirement: The full campaign resumes in independently accepted stages
The full campaign SHALL resume in three sequential reviewed stages: (1) fresh full qualification with promotion, (2) Q4 with sizing and a dated capacity attestation, (3) the full matrix with verify, finalize and export. Each stage SHALL start only after the previous stage is accepted from its own fresh receipts on current images, SHALL use one fresh attempt with failure rules declared before execution, and SHALL leave later-stage eligibility false. A failed stage SHALL preserve its evidence and SHALL require diagnosis and a reviewed amendment before any new attempt. Accepted qualification SHALL be bound to the exact rebuilt native, runtime and worker identities and patch-bound parity it ran on.

#### Scenario: Qualification is accepted
- **WHEN** four native prechecks, the Savant diagnostic and all 32 cells complete under one guardian, the authenticated stop and lifecycle succeed, all 37 producing operations reconcile exactly and policy/resource promotion validates
- **THEN** qualification SHALL be accepted with its original invocation identities and receipt hashes, while Q4, capacity and full-run eligibility SHALL remain false.

#### Scenario: Images changed after the last receipts
- **WHEN** native, runtime or worker sources in an image allowlist differ from the bytes bound by the latest image and parity receipts
- **THEN** the affected images SHALL be rebuilt deterministically, unchanged images SHALL be proven unchanged against their freeze receipts, parity SHALL be repeated against the new patch, and no qualification SHALL run on stale identities.

#### Scenario: A stage attempt fails
- **WHEN** any precheck, diagnostic, cell, stop, closure or promotion fails or is externally interrupted
- **THEN** the attempt SHALL be recorded as failed with preserved evidence, no partial cell SHALL count, and a new attempt SHALL require a reviewed amendment and an explicit human decision.

#### Scenario: A full consumer receives a foreign authority
- **WHEN** a qualification, promotion, Q4 or full-publication consumer receives a component, study or other foreign artifact kind
- **THEN** it SHALL reject the input before creating any directory or file under its output roots.
