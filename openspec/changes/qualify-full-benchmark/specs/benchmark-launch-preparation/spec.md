## MODIFIED Requirements

### Requirement: Benchmark recovery has explicit execution and completion gates
Recovery SHALL deliver a reproducible selected component command and four genuine GStreamer/H.264 native arms through two separately owned baseline/shared contexts for CPU and GPU. It SHALL preserve six streams/four branches, seed20260323,100ms deadline, paired schedules/order,30-second warmup/180-second measurement/10-second drain, original model/intake/source/graph semantics, complete operational identities and strict measured physical checks. Accepted component results SHALL retain raw evidence and current source/model/resource/owner bindings, descriptive comparisons and explicit limits. Any changed identity SHALL invalidate affected readiness. Component completion SHALL NOT establish full campaign readiness, counts, authority or publication eligibility; legacy full gates SHALL remain strict and SHALL remain unaccepted (unexecuted, or failed with preserved evidence) until a reviewed staged full-campaign change actually executes and accepts them under their unchanged predicates; component or study evidence SHALL never satisfy them. Such acceptance SHALL change only the current disposition of that stage; historical unexecuted, failed, false and zero records SHALL remain unchanged. Standing authorization permits autonomous work but SHALL NOT substitute for actual checks/review.

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

### Requirement: Recovery first proves a bounded genuine native pair
Recovery SHALL execute one forced-CPU baseline/shared pair and one separately owned forced-GPU pair through the existing native runtime with real pinned workers/models, six streams/four branches, paired schedules, original warmup/measurement/drop/censoring/resource rules and strict process/cold evidence. Each pair SHALL have explicit two-operation accounting and exact all-phase request equality, symmetric warm worker readiness and original graph/source resets. Selected current physical source/image/worker/model/preprocessing/output/toolchain/calibration/resource facts SHALL grant only a distinct nonpublication component authority. Calibration SHALL retain at least30 actual samples per selected branch/resource cell. A complete historical four-system declaration MAY remain verbatim data only when actual selected eight-worker row equality is independently verified; it SHALL NOT renew sibling/full authority. Missing or stale selected facts SHALL reject launch or require the missing selected evidence, never a manufactured full input/aggregate grant or old receipt rebind. Full qualification/accepted-policy/Q4/publisher entrypoints SHALL reject component authority and retain complete contracts. Static-hybrid and all-system campaign execution remain future scope. Unchanged-intake component pairs SHALL NOT wait for unfinished decoder mechanism research.

#### Scenario: Forced-resource diagnostic pair completes
- **WHEN** both native topology arms execute a supported forced resource to original successful terminals
- **THEN** success SHALL additionally require complete operational reconciliation, stock model/policy/resource/measurement cold validation, exact pair equality and an immutable nonpromoting receipt; identity/topology-only output SHALL be insufficient.

#### Scenario: Static-hybrid inputs are not yet materialized
- **WHEN** existing candidate inputs have no static map or only support forced policies
- **THEN** the diagnostic SHALL wait for the reviewed nonpromoting static diagnostic context, explicitly scoped guardian preprocessing/runtime-input authority and exact current physically calibrated selector map. Existing forced receipts SHALL retain their scope and SHALL NOT be relabelled/rebound as static authority; caller-selected maps, stale calibration and manufactured qualification/production grants SHALL be rejected.

#### Scenario: Diagnostic authority or accounting is incomplete
- **WHEN** changed source/image/model dependencies, the two original operation receipts, all-phase requests or cold checks are incomplete
- **THEN** diagnostic acceptance and dependent qualification32/Q4/full execution SHALL remain blocked without substituting smoke evidence or counterfeit 37-entry qualification evidence.

#### Scenario: Selected component authority materializes
- **WHEN** current selected image/source, eight worker/model/preprocessing/output bindings, resource/calibration, physical inputs and owned two-operation reservations validate
- **THEN** only the explicit component kind SHALL permit its GStreamer/H.264 forced-resource pair; historical table compatibility alone SHALL grant no current execution or full eligibility.

#### Scenario: Selected physical or declaration row drifts
- **WHEN** actual selected worker/model/source/image/preprocessing/output/toolchain facts disagree with bound evidence or historical selected rows
- **THEN** component materialization/launch SHALL reject, preserving old receipt/declaration provenance without rebinding it or renewing siblings.

#### Scenario: Component authority reaches a full entrypoint
- **WHEN** a component receipt, a study artifact or an unknown kind is supplied to qualification, accepted-policy, promotion, Q4 or full publication
- **THEN** the full entrypoint SHALL reject it even when an accepted=false flag or structurally complete historical table is present, before creating any directory or file under its output or work roots; both original full kinds SHALL retain their strict behavior.

#### Scenario: Component request is outside its original pair
- **WHEN** a component service receives a request without active capture or for an unplanned system, arm, source context or policy
- **THEN** it SHALL reject before backend inference using the actual bound two-operation context, without granting permission from the historical complete declaration.

## ADDED Requirements

### Requirement: Legacy runtime wall stamps are strictly increasing per process
Every legacy full-campaign runtime process that stamps wall-clock time and later compares the ordering or positive width of those stamps (native probes, the DeepStream SDK runtime and protocol bridge, the Savant runtime and the guardian operational recorder) SHALL derive those stamps from one per-process non-decreasing source: each stamp SHALL be max(previous+1 ns, raw CLOCK_REALTIME), a backward raw step larger than 10 ms SHALL fail closed with an explicit error, and the largest applied clamp SHALL be reported by every covered process: it SHALL be written into the persisted structured evidence where the process already persists such evidence on success (the guardian operational group, whose readers SHALL still accept historical groups without the field), and native and SDK runtime processes SHALL emit it on every exit path they control (normal return, exception and nonzero exit) in their stderr, which existing owners retain as failure evidence. A process killed by its owner MAY lack the line. Ordering and width predicates SHALL remain unchanged. Cross-process comparisons SHALL keep their documented residual limits and SHALL NOT be relaxed.

#### Scenario: The host clock steps back by a few milliseconds
- **WHEN** CLOCK_REALTIME steps back by about 2 ms between two stamps of one process
- **THEN** the later stamp SHALL be exactly 1 ns after the earlier one, every ordering and positive-width check SHALL pass, and the reported max clamp (guardian operational group or process stderr) SHALL report the applied step.

#### Scenario: The host clock steps back beyond the bound
- **WHEN** CLOCK_REALTIME steps back by more than 10 ms within one process
- **THEN** the process SHALL fail closed with an explicit clock error and SHALL NOT fabricate ordering, retry or accept the affected operation.

#### Scenario: A runtime bypasses the shared source
- **WHEN** a covered runtime file stamps wall-clock time for an ordered or width-checked field without the shared non-decreasing source
- **THEN** a static source check in CI SHALL fail.

### Requirement: The full campaign resumes in independently accepted stages
The full campaign SHALL resume in three sequential reviewed stages: (1) fresh full qualification with promotion, (2) Q4 with sizing and a dated capacity attestation, (3) the full matrix with verify, finalize and export. Each stage SHALL start only after the previous stage is accepted from its own fresh receipts on current images, SHALL execute as one declared attempt with failure rules declared before execution, and SHALL leave later-stage eligibility false. A supported resume of the same attempt from its own checkpoint after a transient exit 75, under the existing retry and recovery policy, SHALL NOT count as a new attempt. A failed attempt (exit 78, a failed gate or an unsupported interruption) SHALL preserve its evidence and SHALL require diagnosis and a reviewed amendment before any new attempt. Accepted qualification SHALL be bound to the exact rebuilt or proven-unchanged native, runtime and worker identities and the patch-bound parity it ran on.

#### Scenario: Qualification is accepted
- **WHEN** four native prechecks, the Savant diagnostic and all 32 cells complete under one guardian, the authenticated stop and lifecycle succeed, all 37 producing operations reconcile exactly and policy/resource promotion validates
- **THEN** qualification SHALL be accepted with its original invocation identities and receipt hashes, while Q4, capacity and full-run eligibility SHALL remain false.

#### Scenario: Images changed after the last receipts
- **WHEN** native, runtime or worker sources in an image allowlist differ from the bytes bound by the latest image and parity receipts
- **THEN** the affected images SHALL be rebuilt through the existing deterministic build and refreeze verification; an image whose own inputs are unchanged but whose produced base was rebuilt SHALL also be rebuilt and SHALL prove its source, dependency and build-context hashes equal to its latest freeze receipt; only images with unchanged inputs and base SHALL be proven unchanged as images; parity SHALL be repeated against the new patch, and no qualification SHALL run on stale identities.

#### Scenario: A stage attempt fails
- **WHEN** any precheck, diagnostic, cell, stop, closure or promotion fails or the attempt suffers an unsupported interruption
- **THEN** the attempt SHALL be recorded as failed with preserved evidence, no partial cell SHALL count, and a new attempt SHALL require a reviewed amendment and an explicit human decision.
