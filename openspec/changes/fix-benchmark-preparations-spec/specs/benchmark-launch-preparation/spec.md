## Purpose

Make VAST ready for a reproducible full benchmark by verifying repairs, runtime identities, qualification, Q4, storage admission and launch configuration, while stopping before full-matrix execution.

## ADDED Requirements

### Requirement: Preparation has an explicit stopping point
Preparation SHALL include repairs, tests, fresh qualification, Q4, capacity attestation, live preflight and a validated unstarted service package. It SHALL NOT execute full-matrix arms, install/enable a full-run service that can start automatically, invoke its start/launch command, or claim completed publication. A readiness statement SHALL identify its observation time and become stale when a bound identity or prerequisite changes.

#### Scenario: Preparation succeeds
- **WHEN** every required preparation gate is accepted and current
- **THEN** the handoff SHALL report preparation_ready=true, full_run_started=false and publication_ready=false, with zero full-matrix arms launched by this change.

#### Scenario: Readiness ages or inputs change
- **WHEN** a guardian identity, source, configuration, image, capacity basis, or other bound prerequisite changes after handoff
- **THEN** the affected readiness gates SHALL be invalidated and stock preflight SHALL be repeated before any later authorized launch.

### Requirement: Native payload descriptors match immutable bytes
A native producer SHALL validate its envelope and a payload size of 1 through 67,108,864 bytes before snapshot allocation, then bind the declared length and SHA-256 to the same immutable snapshot used for its sealed descriptor. A supplied digest that differs from the snapshot SHALL be rejected locally before sending, without silently replacing the contract digest. Caller storage SHALL remain valid and unmodified during capture.

#### Scenario: Correct payload and reuse
- **WHEN** a valid payload is captured and the caller later reuses its storage
- **THEN** transmitted metadata and bytes SHALL still match the captured snapshot and the normal response contract SHALL be preserved.

#### Scenario: Incorrect digest
- **WHEN** a syntactically valid digest describes different bytes of the same length
- **THEN** the producer SHALL raise a local failure without sending a request or file descriptor.

#### Scenario: Payload bounds
- **WHEN** size is zero or exceeds 67,108,864 bytes
- **THEN** the producer SHALL reject before allocating/copying a snapshot; otherwise valid boundary-size requests SHALL pass the size check.

### Requirement: Guardian preserves rejection and diagnostic evidence
The guardian SHALL retain independent descriptor count/type/size/seal/hash and applicable route/identity checks. A valid attribution envelope SHALL establish stable request/run/arm identifiers, frame/branch, decision resource or negotiated worker route, message type and payload descriptor syntax/binding before request reservation. This attribution SHALL NOT be described as front-client authentication. A routed integrity failure SHALL count exactly once as started and failed, never completed, and SHALL prevent inference.

Terminal failures SHALL produce at most one immutable diagnostic no larger than 8 KiB, bound to lifecycle/service identity and recording protocol mode, validated attribution, expected/observed size/hash and seals where safely available. Unsafe or unavailable facts SHALL be null, not invented. Diagnostics SHALL contain no raw payload or credentials. Historical lifecycle v1 evidence SHALL remain valid without rewriting.

#### Scenario: Routed sealed wrong-content request
- **WHEN** a safely attributed request has a sealed correctly sized descriptor with the wrong content hash
- **THEN** the guardian SHALL reject it, account one failed request, preserve bounded expected/observed facts and keep the attempt nonpublication.

#### Scenario: Invalid attribution or descriptor
- **WHEN** input fails before attribution, has missing/extra descriptors, lacks seals, or has invalid size/identity
- **THEN** rejection SHALL remain strict, received descriptors SHALL close, and pre-attribution failures SHALL remain connection-only.

#### Scenario: Concurrent failures or diagnostic persistence error
- **WHEN** terminal failures race or writing their diagnostic fails
- **THEN** at most one first-failure diagnostic SHALL be committed and the original integrity failure SHALL remain terminal without a retry or successful lifecycle claim.

#### Scenario: Historical lifecycle
- **WHEN** a lifecycle v1 record without the new diagnostic is inspected
- **THEN** existing validation SHALL remain compatible and missing forensic context SHALL remain explicit.

### Requirement: Retry and recovery policy is predictable
Full-publication service and supervisor API/CLI defaults SHALL allow zero unexpected retries. Canonical launch configuration SHALL explicitly set zero. Unexpected or integrity failures SHALL stop with permanent exit 78; supported transport/storage failures SHALL retain transient exit 75 recovery with the same checkpoint. New-pair admission SHALL enforce the 20-GiB operational reserve on all required volumes while accepted-pair offload recovery SHALL not remeasure accepted arms.

#### Scenario: Retry option omitted
- **WHEN** an API or CLI caller omits the retry budget and the first invocation fails unexpectedly
- **THEN** it SHALL enter failed_permanent (exit 78) after one invocation without retry sleep.

#### Scenario: Transient offload or low storage
- **WHEN** storage is below reserve or upload/readback has a supported transport failure
- **THEN** new measurements SHALL pause with exit 75 while existing accepted-pair recovery preserves upload, readback, receipt/ledger and raw-cleanup ordering.

#### Scenario: Remote integrity mismatch
- **WHEN** a completed remote read has wrong size or SHA-256
- **THEN** the failure SHALL remain permanent exit 78 and unverified local raw evidence SHALL not be removed.

### Requirement: Baselines and affected evidence are reproducible
Preparation SHALL bind exact source/fixture/configuration bytes, runtime/package versions, hardware/platform identities, datasets/models, image digests and relevant receipts. Git HEAD alone SHALL not identify a dirty runtime. Changed packaged sources SHALL invalidate all affected build/parity/downstream identities; unchanged evidence SHALL be reused only after dependency verification. Final tests SHALL verify exact before/after bytes and compare skip identities, not assume historical test totals remain fixed.

#### Scenario: Existing working tree differs from clean checkout
- **WHEN** implementation starts from a checkout lacking reviewed runtime bytes
- **THEN** source reconciliation and review SHALL precede implementation and no blanket staging of unrelated files SHALL occur.

#### Scenario: Packaged source changes
- **WHEN** a repair modifies a native/runtime/worker source closure
- **THEN** affected images, packaged tests, physical parity and downstream bindings SHALL be renewed before qualification, preserving historical receipts unchanged.

#### Scenario: Deterministic planning replay
- **WHEN** the same accepted inputs and environment generate the full-run plan again
- **THEN** its matrix/policy identities, pair/arm order, seeds, durations and analysis settings SHALL match exactly.

### Requirement: Native-probe qualification path is integrated before qualification
OpenVINO GVA and GStreamer Custom qualification cells SHALL execute through the native probe with queue-level reads matching each property's declared width, a container task ceiling that admits all 24 workers (4096), decode-stage artifacts that are loaded GStreamer factories only, and identifier validation that accepts every frozen branch name. CPU and GPU native policy implementation, emitter and emitter-hash identities SHALL be bound to the frozen qualification-v2 capability manifest, and the executing analytics path SHALL match the manifest's selected backend. The GStreamer Custom runtime SHALL accept the qualification bundle's copied, hash-verified container-engine client. Before any 32-cell attempt, one nonpromoting pre-check replay per native-probe system SHALL reach its original successful terminal.

#### Scenario: Mixed-width queue properties
- **WHEN** pipeline elements expose `current-level-buffers` as `guint` and `guint64`
- **THEN** the reset check SHALL read each at its declared width, reject any nonzero level and fail explicitly on unreadable or unsupported types.

#### Scenario: Branch identifier shorter than eight bytes
- **WHEN** a native policy request names the frozen branch `damage`
- **THEN** identifier validation SHALL accept it, while rejecting empty, oversized, control-containing or non-frozen branch names.

#### Scenario: Policy decision names a manifest identity
- **WHEN** a decision selects the manifest's implementation and emitter identities for the loaded branch and resource
- **THEN** the local binding SHALL match them exactly and path entry and terminal messages SHALL proceed without a relabel failure.

#### Scenario: Loaded path differs from manifest backend
- **WHEN** the loaded analytics path or its identities differ from the manifest's selected backend
- **THEN** the worker SHALL fail closed before the measurement window, without promotion.

#### Scenario: Qualification bundle supplies a copied engine client
- **WHEN** the container-engine pin is a project-relative copied client with matching size and SHA-256
- **THEN** the runtime SHALL accept it; a path escaping the project root or with mismatched bytes SHALL be rejected.

#### Scenario: Pre-check fails
- **WHEN** a native-probe pre-check replay does not reach a successful terminal
- **THEN** no 32-cell attempt SHALL start, and its evidence SHALL be preserved as nonpromoting.

### Requirement: Qualification and Q4 are complete before launch readiness
Preparation SHALL require all 32 qualification cells in one fresh valid attempt, authenticated guardian stop, successful lifecycle/closure and policy/resource promotion. It SHALL then require Q4 phase A with 560 runs, its identity/grant boundary, phase B with 560 runs and 280 sizing pairs derived from phase B, all bound to current authorities. Failed attempts and partial cells SHALL never be combined.

#### Scenario: A269 has eight historical cells
- **WHEN** the failed A269 evidence is reviewed
- **THEN** its cells SHALL remain historical, its services/helpers SHALL remain retired, and zero of those cells SHALL count toward fresh qualification.

#### Scenario: Fresh qualification and Q4 succeed
- **WHEN** all 32 qualification cells and promotion, all 560 phase-A records, boundary, all 560 phase-B records and 280 sizing records validate
- **THEN** those preparation gates SHALL be accepted with original invocation identities and physical receipt hashes.

#### Scenario: A prerequisite is missing or fails
- **WHEN** any diagnostic, lifecycle, promotion or Q4 stage fails or is incomplete
- **THEN** dependent stages SHALL remain blocked, evidence SHALL be preserved, and repeated execution SHALL require diagnosis and a valid fresh or supported resumable context.

### Requirement: Cloud admission uses an actual dated guarantee
Capacity admission SHALL require a current explicit operator guarantee in bytes, with UTC timestamp/reference, bound to the existing destination, actual 280 Q4 sizing pairs and successful upload/readback. The required capacity SHALL be max(500 GiB, ceil(projected_remote_bytes times 1.25) plus 5 GiB), using ten repeats. Undated notes SHALL not count as confirmation and capability URLs SHALL not appear in published evidence.

#### Scenario: Confirmation missing
- **WHEN** only an old 500-GiB estimate or undated 1500-GB note exists
- **THEN** launch readiness SHALL remain blocked without fabricating confirmation; otherwise authorized qualification/Q4 SHALL not be blocked solely by that missing confirmation.

#### Scenario: Sizing or readback exceeds the guarantee
- **WHEN** actual required capacity exceeds the guarantee or upload/readback fails validation
- **THEN** cloud admission SHALL fail and full-run readiness SHALL remain false.

### Requirement: Launch handoff preserves the full experiment
The handoff SHALL preserve 4 systems, 2 codecs, 2 topologies, 7 policies, 5 deadlines and 10 repeats, yielding 2,800 pairs/5,600 arms, six streams, seed 20260323, 30-second warmup and 180-second measurement. It SHALL preserve existing paired order, schedule/seed equality, fixed analysis and negative results. The package SHALL bind canonical run/state/output paths and current accepted identities, and SHALL require a new execution request and repeated current preflight before later installation/start.

#### Scenario: Unstarted package validates
- **WHEN** materialization and non-starting validation pass after accepted live preflight
- **THEN** the handoff SHALL include exact sanitized argv, receipt hashes, checkpoint/state paths, blockers and later install/start/verify/finalize/export instructions without executing them.

#### Scenario: Altered matrix or malformed command
- **WHEN** a candidate changes frozen counts/hashes/settings, uses corrupted variable names, wrong option order, or unsupported paths
- **THEN** preparation verification SHALL reject it before workload execution.

### Requirement: Documentation and conformance are truthful
One current runbook SHALL distinguish preparation from subsequent full execution, correct corrupted examples, preserve original PLAN obligations and label historical status. A conformance record SHALL map every requirement/scenario to code and tests or manual evidence, including unresolved gaps. OpenSpec format checks and historical local suites SHALL not be reported as current CI or real benchmark acceptance.

#### Scenario: Documentation reviewed
- **WHEN** the runbook is delivered
- **THEN** shell examples SHALL pass syntax-only validation, supported flags/path constraints SHALL be checked against source, and no full-run start SHALL be part of its preparation steps.

#### Scenario: Required CI is unavailable
- **WHEN** no required checks have run on the final commit
- **THEN** merge readiness SHALL remain blocked and separately agreed CI setup SHALL be recorded as outstanding rather than claimed complete.
