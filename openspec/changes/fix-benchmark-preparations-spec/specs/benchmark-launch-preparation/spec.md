## Purpose

Make VAST executable and independently verifiable through bounded native diagnostics, complete operational accounting, qualification, Q4, factual storage admission, durable full-matrix execution and scientifically truthful finalized results.

## ADDED Requirements

### Requirement: Benchmark recovery has explicit execution and completion gates
Recovery SHALL include reviewed repairs, genuine bounded native pair diagnostics, complete request-domain validation, fresh qualification, Q4, factual capacity attestation, current preflight and a validated service package before authorized full-matrix installation/start. A readiness statement SHALL identify its observation time and become stale when a bound identity or prerequisite changes. The user's standing authorization SHALL permit continuation through actual full-run verification, finalization, export and repository completion; it SHALL NOT substitute for any runtime, storage, scientific or review gate.

#### Scenario: Preparation succeeds
- **WHEN** every required preparation gate is accepted and current
- **THEN** the evidence packet SHALL report preparation_ready=true and the actual launch/completion state; before authorized full-run launch it SHALL report full_run_started=false and publication_ready=false rather than claim completion from diagnostics or service materialization.

#### Scenario: Readiness ages or inputs change
- **WHEN** a guardian identity, source, configuration, image, capacity basis, or other bound prerequisite changes after handoff
- **THEN** affected readiness gates SHALL be invalidated and stock preflight SHALL be repeated before dependent launch or supported resume, without silently rebinding historical receipts.

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
OpenVINO GVA and GStreamer Custom qualification cells SHALL execute through the native probe with queue-level reads matching each property's declared width, a container task ceiling that admits all 24 workers (4096), decode-stage artifacts that are loaded GStreamer factories only, and identifier validation that accepts every frozen branch name. CPU and GPU native policy implementation, emitter and emitter-hash identities SHALL be bound to the frozen qualification-v2 capability manifest, and the executing analytics path SHALL match the manifest's selected backend. A verified native queue overflow before policy path entry SHALL produce one native branch-drop terminal with correct trace lineage and no policy decision, path entry, policy execution terminal or analytics inference for that branch/frame. Stage and resource attribution SHALL reflect only physically completed stages: a postdecode prefix drop has decode evidence but no preprocessing for its affected branch, whereas a pre-detector drop follows preprocessing. Missing preprocessing for any other branch outcome SHALL remain invalid. The shared native-probe runtime SHALL produce a preexisting `resource_events.csv` from the accepted native stage intervals before publication, with one matching resource row per physical stage, explicit provenance for measured time and estimated auxiliary metrics, and no fabricated missing stage. Publication SHALL still reject an absent or inconsistent sidecar. Unknown, duplicate or post-entry drops SHALL fail closed. The GStreamer Custom runtime SHALL accept the qualification bundle's copied, hash-verified container-engine client. Before any 32-cell attempt, one nonpromoting pre-check replay for each native-probe system and resource SHALL reach its original successful terminal.

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

#### Scenario: Postdecode prefix queue overflows before policy entry
- **WHEN** the native postdecode queue emits `native_postdecode_preprocess_queue_full_drop_newest` for an admitted branch/frame before policy path entry
- **THEN** exactly one correctly linked native branch-drop terminal and the completed decode evidence SHALL be recorded without a fabricated preprocessing stage/interval or a policy decision, path entry, policy execution terminal or analytics inference for that branch/frame.

#### Scenario: Pre-detector queue overflows before policy entry
- **WHEN** the native pre-detector queue emits `native_pre_detector_queue_full_drop_newest` for an admitted branch/frame before policy path entry
- **THEN** exactly one correctly linked native branch-drop terminal and the completed decode/preprocessing evidence SHALL be recorded without a policy decision, path entry, policy execution terminal or analytics inference for that branch/frame.

#### Scenario: Queue-drop identity or ordering is invalid
- **WHEN** a queue-drop terminal has an unknown reason or binding, no matching admitted branch/frame, a duplicate terminal, or an already entered policy path
- **THEN** the attempt SHALL fail closed before emitting a terminal for that invalid event, without relabelling it as a completed policy execution or promoting evidence.

#### Scenario: Preprocessing evidence is missing without a verified prefix drop
- **WHEN** a completed branch or pre-detector drop lacks its native preprocessing stage/interval, or a claimed prefix drop lacks its native reason and lineage
- **THEN** publication and resource-attribution validation SHALL reject the measurement rather than infer or fabricate an interval.

#### Scenario: Independent and shared prefix-drop coverage
- **WHEN** independent branches have mixed verified prefix drops and other outcomes, or a shared postdecode prefix queue drops a frame
- **THEN** stage/resource coverage SHALL be checked for each independent branch, while a shared prefix drop SHALL cover every branch of that frame with shared decode and no shared preprocess/fanout; a partial shared prefix drop SHALL be rejected.

#### Scenario: Native stage resource sidecar
- **WHEN** an OpenVINO GVA or GStreamer Custom native-probe arm reaches publication with physical stage intervals for the accepted measurement cohort
- **THEN** its runtime SHALL exclusively write and validate `resource_events.csv` before publication with exactly the corresponding stage keys, durations and labeled provenance; a missing, duplicate, invalid or unmatched extra interval for an accepted measurement ingress, or an existing target file, SHALL block publication, and a verified prefix drop SHALL have no invented preprocessing resource row. Warmup and drain events outside the accepted cohort SHALL remain excluded by the stock reducer.

#### Scenario: Pre-check fails
- **WHEN** a native-probe pre-check replay does not reach a successful terminal
- **THEN** no 32-cell attempt SHALL start, and its evidence SHALL be preserved as nonpromoting.

### Requirement: Published policy decisions preserve canonical linkage and actual runtime history
Native policy publication SHALL project only the explicitly validated measurement cohort into canonical aggregate frame traces and dense decision ordinals 1..N. CSV, outer JSONL and each JSONL request SHALL agree on trace, ordinal, decision ID and branch; CSV and outer JSONL SHALL also agree on policy and selected resource without adding fields to the exact request schema. Projection metadata outside the request SHALL preserve original runtime decision identity, issued/accepted hashes, evaluations, state_before and native execution evidence reversibly, without changing the live engine, wire decisions, selected execution path, timing or actual feedback. For `adaptive_weights`, a strict versioned bounded runtime-history sidecar SHALL bind every actual issuance and feedback from the actual initial reset, including excluded warmup/drain predecessors and interleaved updates, to the adaptive acceptance evidence namespace and hashes. Original feedback payloads/hashes SHALL remain unchanged; dense measurement feedback ordinals SHALL be derived from the actual history, retaining original runtime ordinals in history envelopes. Cold decision/feedback validation, qualification and the independent Q4 reader SHALL reconstruct and replay originals, validate the complete measurement projection and reject inconsistent, incomplete or unsupported evidence. Manifest/native capability checks SHALL still require the actual accepted capability manifest; standalone mathematical replay SHALL NOT invent one or grant capability authority. Unprojected historical evidence SHALL retain its existing strict validation; failed historical artifacts SHALL not be rewritten.

#### Scenario: Worker traces and runtime sequence gaps enter a measurement cohort
- **WHEN** accepted measurement decisions have branch-worker trace IDs and runtime ordinals with excluded warmup/drain gaps
- **THEN** publication SHALL use the original native `input_frame_key`, validated accepted-ingress mapping and original CSV feature provenance to bind canonical frame/worker/branch/PTS identity, then use original runtime order to emit matching aggregate traces and dense ordinals in CSV and both outer/request JSONL fields with reversible original identity/hash metadata, without trace-suffix inference.

#### Scenario: Publication preserves live decision and feedback authority
- **WHEN** a runtime decision is issued, executed, receives feedback and is later projected for publication
- **THEN** its wire response, original issued-record hash, selected path, evaluations and actual engine transitions SHALL remain unchanged, and reconstruction SHALL verify both issued and accepted originals under the frozen policy/native evidence validators.

#### Scenario: Excluded feedback influences a measured adaptive decision
- **WHEN** excluded warmup/drain or interleaved feedback updates the adaptive engine before a measurement decision or its terminal
- **THEN** cold validation SHALL replay every actual issuance and feedback in captured global order from the actual initial reset and verify all original states and measurement links; it SHALL NOT insert a reset or omit a predecessor update to make dense measurement feedback appear contiguous.

#### Scenario: Nonadaptive publication preserves strict closure without adaptive history
- **WHEN** CPU-only, GPU-only or another nonadaptive policy publishes a measurement cohort
- **THEN** the producer SHALL require validated native terminal closure for every live issued decision, each measurement original SHALL be reconstructed and individually replayed with its actual reset state (same arm, weights 1 and empty EWMA), no history or feedback sidecar SHALL be accepted, and canonical projection checks SHALL run without a resource-specific bypass while preserving the existing nonadaptive evidence namespace.

#### Scenario: Publication mapping or original proof is corrupt
- **WHEN** a mapping is missing, ambiguous or orphaned, a projected outer/request identity differs, or an issued/accepted/native evidence hash or evaluation is changed
- **THEN** promotion and cold qualification SHALL reject the output without treating it as accepted policy evidence.

#### Scenario: Runtime history or projected ordering is incomplete
- **WHEN** history has a duplicate, missing, reordered or orphan issuance/feedback, an unclosed issuance, a substituted initial state, an unsupported version, or the measurement decision/feedback view has non-dense ordinals or a mismatched cohort
- **THEN** whole-history replay and publication SHALL fail closed without fabricating an event or state transition.

#### Scenario: History input exceeds its bound or is malformed
- **WHEN** the adaptive sidecar exceeds the existing 64-MiB per-file or 256-MiB aggregate acceptance bounds, 1,000,000 events or 256 KiB per record, or contains duplicate keys or nonfinite numbers
- **THEN** the producer or cold reader SHALL reject it within bounded allocation before acceptance, incrementally enforcing the tighter existing stage custody bounds including Savant's 64-MiB child-output aggregate and retained-file count without raising them.

#### Scenario: Existing strict historical records are read
- **WHEN** an unprojected historical arm is validated
- **THEN** the existing strict record/linkage/feedback path SHALL apply; a mixed projected/unprojected arm or incomplete projection metadata SHALL be rejected rather than admitted as legacy evidence.

#### Scenario: Independent Q4 reader runs under its isolated loader
- **WHEN** Q4 executes its pinned validator bytes through `python -I -S -B`
- **THEN** projection reconstruction, independent policy evaluation and adaptive history validation SHALL succeed for valid evidence using a self-contained reader, without an unpinned helper import or unrestricted project search path; malformed evidence SHALL remain rejected by that same loader.

#### Scenario: Original producer success has rejected cold evidence
- **WHEN** an original diagnostic exits 0 but its physical policy artifacts fail cold canonical linkage, sequence or history validation
- **THEN** process success and cold rejection SHALL be recorded separately, no qualification or Q4 stage SHALL start, and the attempt SHALL be preserved and its guardian authenticated-stopped as nonpublication before a reviewed repair and wholly fresh renewal chain.

### Requirement: Qualification reconciles the complete operational request domain
Fresh qualification SHALL bind complete original native execution evidence for every allowed original precheck, diagnostic and qualification invocation, including warmup, measurement and drain, separately from measurement and adaptive feedback/history evidence. It SHALL retain validated native input/stream/frame/PTS/worker, original decision and selected route/capability/model identities and the actual transport identity semantics. Every original issued execution SHALL have one validated completed terminal. Guardian evidence SHALL pair every actual attributed front request with exactly one terminal and retain its original authority/lifecycle/owner/source binding. The complete allowed request-identity multiset SHALL equal the guardian's started and completed multisets, lifetime count and all eight worker totals, with zero failed or unfinished requests. Measurement32 SHALL remain an independently validated exact subset/projection, preserving all existing native/policy/model/resource checks.

Operational evidence SHALL be versioned, physically bound, immutable on success, bounded and nonauthorizing. Each original producer invocation SHALL retain its unchanged legacy stage group and every existing aggregate/file/count limit (including Savant's 64-MiB limit), plus a separately sealed operational group of at most 64 MiB with one canonical JSONL, header at most 64 KiB and completed occurrence at most 9,216 bytes. Both groups SHALL count within the enclosing 256-MiB retained-operation limit. Original accepted/request/path/terminal fields, numeric types, evaluator values and hashes SHALL remain lossless; issued reconstruction SHALL verify the original issued hash and unchanged native-binding roundtrip without duplicating full issued JSON or inventing missing source records. Guardian evidence SHALL use ordinary explicit JSON objects and independently validated immutable references for repeated constants, without a positional/arithmetic/numeric codec. Its complete lifetime group SHALL remain eight route journals plus final companion, at most 256 MiB/1,000,000 events, route/header at most 64 MiB/64 KiB, companion at most 1 MiB, begin/terminal at most 768/256 bytes and at most 128 pending terminal reservations. Each terminal SHALL reference its unique original begin and losslessly resolved identity. The qualification manifest SHALL contain exactly 37 distinct original producing entries and occupy at most 1 MiB; separately scoped two-arm diagnostics SHALL never satisfy this manifest by fabricated entries. Successful qualification pairing SHALL permit at most 500,000 requests. Before acceptance the source SHALL prove actual constructor field/number/string/state sizes, scaled CFR cadence and deadline/concurrency budgets; offered-fps labels, empirical file sizes and compression ratios SHALL NOT establish feasibility. A failed proof SHALL require reviewed design revision, not truncation, raised limits or silent constructor tightening. Additional capture/cold sorting SHALL obey the reviewed fixed memory/file/disk bounds with terminal capacity reserved at begin. Attribution SHALL NOT be claimed as front-client authentication, an access grant or independent full-wire-byte attestation. Historical strict validation SHALL remain readable, but aggregate-only evidence SHALL not satisfy this new gate. Counter reset/offset/inequality, caller phase tags and relaxed measurement checks SHALL NOT substitute for complete identities.

#### Scenario: Allowed predecessor and pilot traffic completes
- **WHEN** original prechecks, the diagnostic and all 32 cells complete with native executions across warmup, measurement and drain under one guardian
- **THEN** their independently bound complete operational domains SHALL reconcile exactly to every guardian request/terminal and worker total, while source-proven zero-request setup probes and pre-entry drops SHALL contribute no invented calls.

#### Scenario: Unknown traffic preserves aggregate totals
- **WHEN** an extra, missing or substituted request changes run, wire arm, frame, PTS, worker, model, route or native identity even though lifetime and worker totals remain equal
- **THEN** exact domain matching SHALL reject qualification rather than accept aggregate equality.

#### Scenario: Separate invocations repeat a wire identity
- **WHEN** physically distinct allowed original precheck and pilot invocations legitimately emit the same wire request identity
- **THEN** reconciliation SHALL preserve their exact occurrence multiplicity; a duplicate inside one invocation, excess occurrence or reused invocation proof SHALL be rejected without inventing a globally unique client or PID identity.

#### Scenario: A measurement request finishes during drain
- **WHEN** a request belonging to validated measurement ingress completes after the measurement window
- **THEN** its original terminal SHALL remain in the complete operational domain and its existing measurement subset without classification by terminal time or a caller phase label.

#### Scenario: Request or terminal capture is incomplete
- **WHEN** a begin has no terminal, a terminal has no begin, completions repeat, send fails, or concurrent completion order differs
- **THEN** missing/duplicate/failing pairs SHALL block success; valid concurrent order SHALL retain exact pairs and multiplicities without comparing unrelated sequence order.

#### Scenario: Operational evidence exceeds bounds or cannot persist
- **WHEN** capture or cold reading exceeds a defined producer/guardian group/file/record/header/event/pending limit, a tighter existing stage bound, the 1-MiB domain limit or fixed append/sort/scratch bounds, source cadence/deadline/concurrency assumptions are unsupported, or a write/short-write/fsync fails
- **THEN** the attempt SHALL fail within bounded allocation, preserve the original failure and partial evidence, and SHALL not truncate, raise limits, retry or claim successful closure.

#### Scenario: Domain custody or schema is invalid
- **WHEN** a descriptor or source/owner/guardian binding changes, an invocation is foreign/reused, files are missing/truncated/unsafe, or records have duplicate keys, nonfinite values or unsupported versions
- **THEN** independent physical validation SHALL reject the domain and all dependent qualification or promotion.

#### Scenario: Only legacy aggregate evidence exists
- **WHEN** an original historical guardian has no complete operational journal or producer domain
- **THEN** its historical validation SHALL preserve its original outcome without rewriting, but it SHALL remain ineligible for the new qualification accounting gate.

#### Scenario: Source accounting defect is found before pilots
- **WHEN** source review identifies an unsatisfied complete-domain gate before any pilot submission
- **THEN** dependent pilots SHALL remain unstarted, original successful diagnostics SHALL remain truthful, and exact amended review plus the actual original guardian terminal/lifecycle and a wholly fresh affected chain SHALL precede implementation acceptance; an already failed guardian SHALL NOT be retrospectively given a clean retirement.

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
The validated package and subsequent run SHALL preserve 4 systems, 2 codecs, 2 topologies, 7 policies, 5 deadlines and 10 repeats, yielding 2,800 pairs/5,600 arms, six streams, seed 20260323, 30-second warmup and 180-second measurement. They SHALL preserve paired order, schedule/seed equality, frozen model/preprocessing identities, fixed analysis and valid negative results. Canonical run/state/output paths and current accepted identities SHALL be bound; current stock preflight SHALL precede installation/start under the user's standing authorization.

#### Scenario: Unstarted package validates
- **WHEN** materialization and non-starting validation pass after accepted live preflight
- **THEN** the evidence packet SHALL include exact sanitized argv, receipt hashes, checkpoint/state paths and blockers; installation/start SHALL use that package only after all current gates pass, without claiming execution from materialization alone.

#### Scenario: Altered matrix or malformed command
- **WHEN** a candidate changes frozen counts/hashes/settings, uses corrupted variable names, wrong option order, or unsupported paths
- **THEN** preparation verification SHALL reject it before workload execution.

### Requirement: Documentation and conformance are truthful
One current runbook SHALL distinguish diagnostic, preparation, full execution and finalization stages, correct corrupted examples, preserve original obligations and label historical status. A conformance record SHALL map every requirement/scenario to implementation and actual tests/manual evidence, including unresolved gaps. Reviewed appropriate CI SHALL execute on the final commit and explicitly distinguish hosted checks from physical hardware evidence. OpenSpec format checks, skipped hardware jobs and historical local suites SHALL NOT be reported as current CI or real benchmark acceptance.

#### Scenario: Documentation reviewed
- **WHEN** the runbook is delivered
- **THEN** shell examples SHALL pass syntax-only validation, supported flags/path constraints SHALL be checked against source, and actual launch/finalization commands SHALL be gated by the current accepted predecessor receipts.

#### Scenario: Required CI is unavailable
- **WHEN** no required checks have run on the final commit
- **THEN** merge readiness SHALL remain blocked and required CI setup/checks SHALL remain outstanding rather than being replaced by local tests or delegated review comments.

### Requirement: Recovery first proves a bounded genuine native pair
Recovery SHALL execute exactly one baseline/shared pair per bounded diagnostic context through the existing publication-v3 execution spine with real pinned analytics, six streams/four branches, paired input schedules, original process/cold evidence and the unchanged warmup/measurement/drop/censoring/resource rules. It SHALL use explicit two-arm operational activation and full all-phase identity equality separately from measured evidence. Model workers SHALL remain warm across that pair with symmetric readiness and existing warmup, while native source/graph reset rules remain unchanged. Forced CPU and GPU diagnostic pairs SHALL precede a static-hybrid diagnostic using the exact current physically bound calibration and exhaustive mixed-map result. Diagnostics SHALL remain nonpromoting and SHALL NOT count toward qualification, Q4 or full-run repeats. The first affected packaged runtime/real-boundary regression SHALL gate broad renewal. Stock all-four-runtime patch-bound authority and normal fresh parity SHALL precede the physical pair; a narrow two-entry nonpromoting adapter MAY select genuine materialized GStreamer v3 contracts without creating new aggregate authority or reusing old patch-bound acceptance. The physical pair SHALL precede qualification32/Q4/full.

#### Scenario: Forced-resource diagnostic pair completes
- **WHEN** both native topology arms execute a supported forced resource to original successful terminals
- **THEN** success SHALL additionally require complete operational reconciliation, stock model/policy/resource/measurement cold validation, exact pair equality and an immutable nonpromoting receipt; identity/topology-only output SHALL be insufficient.

#### Scenario: Static-hybrid inputs are not yet materialized
- **WHEN** existing candidate inputs have no static map or only support forced policies
- **THEN** the diagnostic SHALL wait for the reviewed nonpromoting static diagnostic context, explicitly scoped guardian preprocessing/runtime-input authority and exact current physically calibrated selector map. Existing forced receipts SHALL retain their scope and SHALL NOT be relabelled/rebound as static authority; caller-selected maps, stale calibration and manufactured qualification/production grants SHALL be rejected.

#### Scenario: Diagnostic authority or accounting is incomplete
- **WHEN** changed source/image/model dependencies, the two original operation receipts, all-phase requests or cold checks are incomplete
- **THEN** diagnostic acceptance and dependent qualification32/Q4/full execution SHALL remain blocked without substituting smoke evidence or counterfeit 37-entry qualification evidence.

### Requirement: Operations retain bounded ownership and worker termination facts
Each bounded diagnostic and long-running benchmark stage SHALL have one persisted original owner, fresh output reservation, sanitized argv and actual process/unit identities, bounded lifecycle deadlines and immutable receipt-last outcome. A worker exit SHALL preserve original terminal status and available engine/cgroup/kernel/log evidence with source/time or explicit unavailable facts before disposable cleanup. Unknown causes SHALL remain unknown; exit 137 SHALL NOT alone be identified as OOM. Cleanup SHALL target only owned workers/sockets after preserving evidence, and worker replacement or silent measurement retry SHALL NOT produce acceptance.

#### Scenario: Worker exits during a diagnostic
- **WHEN** an owned worker dies or becomes unavailable
- **THEN** the diagnostic SHALL fail nonpublication, retain bounded original process/container/log/resource facts, stop owned dependents and block acceptance without automatic replacement.

#### Scenario: Historical guardian already failed
- **WHEN** original failed g evidence is examined or a prior stage is terminal
- **THEN** its actual terminal/lifecycle SHALL be retained without retroactive clean stop, duplicate owner or rewritten success; only a fresh valid context may execute changed bytes.

### Requirement: Scientific interpretation matches the executed workload
Final outputs SHALL describe the opaque ResNet workload as `topology_load_proxy_only` under common OpenVINO CPU/TensorRT CUDA workers and limit backend comparisons to observed topology/scheduling/transport/resource behaviour. They SHALL retain real deadline/drop/negative outcomes and distinguish additive work from nonadditive elapsed diagnostics. Real KPP accuracy, backend-native inference rankings, true NVDEC busy time and formal AW-HEFT equivalence SHALL NOT be claimed without independently accepted corresponding evidence.

#### Scenario: Relative quality passes despite absolute deadline misses
- **WHEN** a paired quality difference satisfies the frozen rule but both arms miss an absolute SLO
- **THEN** outputs SHALL report those actual misses and may report only the supported relative result, without claiming absolute SLO compliance or changing deadlines.

#### Scenario: Only proxy or partial resource evidence exists
- **WHEN** accepted execution uses opaque models or lacks direct evidence for a resource quantity or formal scheduler equivalence
- **THEN** analysis and claim state SHALL retain the exact proxy/coverage limitation without relabelling it as the missing scientific proof.

### Requirement: Authorized full execution closes durable results and repository evidence
After all current qualification/Q4/storage/preflight gates pass, recovery SHALL execute the preserved full experiment through one supported durable owner/checkpoint. Accepted pairs SHALL be uploaded, read back and durably receipted before raw cleanup; supported resume SHALL verify and reuse accepted pairs without remeasurement. Completion SHALL require 5,600 accepted arms, 2,800 accepted pairs and verified storage transactions, successful stock verify/finalize/finalized-only export and independently checked analysis. Required CI/conformance and reviewed warnings SHALL precede supported sync/archive in this same branch/PR; archive and main specs SHALL be committed/pushed, and required final-commit checks and delegated final review/authorization SHALL precede merge. Missing factual capacity or failed required checks SHALL remain real blockers, never inferred from general authorization.

#### Scenario: Full benchmark finishes with valid negative results
- **WHEN** every required arm/pair/storage transaction and stock verification/finalization/export succeeds
- **THEN** completion SHALL report actual immutable counts/descriptors and scientifically valid positive, negative or inconclusive outcomes rather than requiring a favorable effect.

#### Scenario: Accepted pairs exist when transient offload fails
- **WHEN** supported transport/low-storage recovery resumes the same valid checkpoint
- **THEN** existing accepted pairs SHALL be reverified and offloaded without new measurement, and raw cleanup SHALL wait for verified durable receipts.

#### Scenario: Completion or final repository gate is missing
- **WHEN** any full-run result, storage proof, required CI/conformance, pushed archive or applicable final review is missing
- **THEN** its completion/merge state SHALL remain incomplete or blocked; no diagnostic, partial attempt, document check or delegated comment SHALL be substituted for that gate.
