# Benchmark Launch Preparation

## Purpose

Make VAST operable through a reproducible real GStreamer component benchmark with complete physical/operational validation and scientifically truthful descriptive results, while preserving explicitly separate conditional full-campaign contracts.

## Scope

Decision23 release consists of four genuine GStreamer/H.264 arms: one CPU and one GPU baseline/shared pair. Requirements concerning full qualification/Q4, remote capacity and the full matrix retain their existing conditional full-entrypoint behavior; executing those campaigns is future work, not component release acceptance. The original72 tasks/82 scenarios and exact Decision22 clauses are retained in verification-plan.md and the byte-exact historical snapshot. Deferral SHALL NOT be reported as execution. Component qualification/Q4/publication/full eligibility SHALL remain false.

The separately typed finite-component-study is the canonical bounded selected systems objective: actual 24 effect arms and 12 pairs with complete raw accounting, current physical/source checks and independent reduction. Legacy 32 qualification, Q4 and 5600 full-matrix campaigns are superseded only as prerequisites for this new objective, while their historical unexecuted/false/zero dispositions, original register and strict full-entrypoint contracts remain unchanged. Study, pilot or descriptive decoder evidence SHALL NOT establish legacy full eligibility or relabel historical campaigns as executed.

## Requirements

### Requirement: Benchmark recovery has explicit execution and completion gates
Recovery SHALL deliver a reproducible selected component command and four genuine GStreamer/H.264 native arms through two separately owned baseline/shared contexts for CPU and GPU. It SHALL preserve six streams/four branches, seed20260323,100ms deadline, paired schedules/order,30-second warmup/180-second measurement/10-second drain, original model/intake/source/graph semantics, complete operational identities and strict measured physical checks. Accepted component results SHALL retain raw evidence and current source/model/resource/owner bindings, descriptive comparisons and explicit limits. Any changed identity SHALL invalidate affected readiness. Component completion SHALL NOT establish full campaign readiness, counts, authority or publication eligibility; legacy full gates SHALL remain strict and explicitly unexecuted. Standing authorization permits autonomous work but SHALL NOT substitute for actual checks/review.

The separately typed finite-component-study objective SHALL require all 24 prescribed effect arms and 12 paired comparisons on one current final bundle, complete raw accounting and independent reduction, unchanged within-pair bindings, bounded physical closure, current mandatory CI and conformance. A valid negative performance result SHALL be admissible; a pilot or partial matrix SHALL NOT satisfy this objective. For this new canonical objective only, the legacy 32 qualification campaigns, Q4 and 5600 full matrix SHALL be superseded as execution and completion prerequisites. Their historical unexecuted/false/zero dispositions and original register SHALL remain unchanged. Strict legacy qualification, promotion, Q4, publication and full entrypoints SHALL retain their exact-kind/readiness/rejection predicates and SHALL NOT accept a study artifact as full authority. This objective SHALL NOT relabel prior component, decoder, metadata or pilot evidence as the 24-arm study.

#### Scenario: Preparation succeeds
- **WHEN** every required component release gate is accepted and current
- **THEN** the evidence packet SHALL report component_release_complete=true with four actual component arms/two pairs and current evidence, while full_run_started=false and qualification/Q4/publication/full eligibility remain false; unexecuted campaign counts SHALL remain zero.

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

#### Scenario: Preflight library rejection retains original structured facts
- **WHEN** decoder research fails in preflight with attached Pin rejection before any run starts
- **THEN** the original bounded16KiB first-error record SHALL retain the actual path/stat/predicate/mapping provenance from the original snapshot captured before rejected-FD retirement, then serialize it before remaining guest teardown, without replacing the primary error, waiving identity equality or interpreting absent frames. A fresh reviewed v5 attempt05 SHALL preserve every original experiment and cleanup bound; failed04 SHALL remain immutable.

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

#### Scenario: Exact source identity depends on inherited line endings
- **WHEN** the captured 165-file executable/build source inventory has only inherited CR-at-EOL differences from committed blobs
- **THEN** the reviewed finite exact-path byte-preservation rules and only the 22 original raw replacements SHALL preserve all physical source bytes and nine existing explicit LF contracts; fresh initial checkouts with autocrlf true and false SHALL reproduce every size/SHA and actual dependency context before reproducibility is claimed, without blanket staging or reuse of another checkout's physical custody.

#### Scenario: Stock build controller requires canonical LF metadata
- **WHEN** a fresh initial checkout preserves165 source descriptors but converts the ten separately pinned native/worker controller manifests to CRLF
- **THEN** only those ten exact-path LF contracts SHALL be added, their already canonical source bytes SHALL remain unchanged, and both new initial autocrlf checkouts SHALL reproduce the separate165-source and ten-controller groups with clean declared paths and unchanged stock dependency contexts; the original failed checkout SHALL remain failed and immutable.

#### Scenario: Peer-observer unit runs on a non-WSL Linux CI host
- **WHEN** the unit exercises the strict observer with its existing fixed WSL/Docker fixtures on Ubuntu
- **THEN** only returned read bytes MAY be fixture-controlled while real default proc opening, FD/name checks, real bounded reads and closing remain exercised; exact256/223 bounds, same FD, flags and post-close EBADF SHALL be asserted. Production source/constants SHALL remain unchanged and fixture output SHALL NOT be claimed as actual-host WSL attestation.

#### Scenario: Portable unit fixture preserves non-WSL rejection
- **WHEN** the production parser receives non-WSL Linux kernel bytes
- **THEN** it SHALL still reject the WSL marker, with no skip, observer/path/owner emulation or relaxed production validation. Original hosted failure and independent full-suite limitations SHALL remain retained.

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
Each component pair and fresh full qualification SHALL bind complete original native execution evidence for every allowed original precheck, diagnostic and qualification invocation, including warmup, measurement and drain, separately from measurement and adaptive feedback/history evidence. It SHALL retain validated native input/stream/frame/PTS/worker, original decision and selected route/capability/model identities and the actual transport identity semantics. Every original issued execution SHALL have one validated completed terminal. Guardian evidence SHALL pair every actual attributed front request with exactly one terminal and retain its original authority/lifecycle/owner/source binding. The complete allowed request-identity multiset SHALL equal the guardian's started and completed multisets, lifetime count and all eight worker totals, with zero failed or unfinished requests. For full qualification, Measurement32 SHALL remain an independently validated exact subset/projection. Each component pair SHALL instead retain its exact two-arm ingress-derived measurement subset/projection, preserving all applicable native/policy/model/resource checks.

Operational evidence SHALL be versioned, physically bound, immutable on success, bounded and nonauthorizing. Each original producer invocation SHALL retain its unchanged legacy stage group and every existing aggregate/file/count limit (including Savant's 64-MiB limit), plus a separately sealed operational group of at most 64 MiB with one canonical JSONL, header at most 64 KiB and completed occurrence at most 9,216 bytes. Both groups SHALL count within the enclosing 256-MiB retained-operation limit. Original accepted/request/path/terminal fields, numeric types, evaluator values and hashes SHALL remain lossless; issued reconstruction SHALL verify the original issued hash and unchanged native-binding roundtrip without duplicating full issued JSON or inventing missing source records. Guardian evidence SHALL use ordinary explicit JSON objects and independently validated immutable references for repeated constants, without a positional/arithmetic/numeric codec. Its complete lifetime group SHALL remain eight route journals plus final companion, at most 256 MiB/1,000,000 events, route/header at most 64 MiB/64 KiB, companion at most 1 MiB, begin/terminal at most 768/256 bytes and at most 128 pending terminal reservations. Each terminal SHALL reference its unique original begin and losslessly resolved identity. A component manifest SHALL contain exactly its two original producing operations and use the existing two-arm accounting mode. The full qualification manifest SHALL contain exactly 37 distinct original producing entries and occupy at most 1 MiB; separately scoped two-arm diagnostics SHALL never satisfy this manifest by fabricated entries. Successful qualification pairing SHALL permit at most 500,000 requests. Before acceptance the source SHALL prove actual constructor field/number/string/state sizes, scaled CFR cadence and deadline/concurrency budgets; offered-fps labels, empirical file sizes and compression ratios SHALL NOT establish feasibility. A failed proof SHALL require reviewed design revision, not truncation, raised limits or silent constructor tightening. Additional capture/cold sorting SHALL obey the reviewed fixed memory/file/disk bounds with terminal capacity reserved at begin. Attribution SHALL NOT be claimed as front-client authentication, an access grant or independent full-wire-byte attestation. Historical strict validation SHALL remain readable, but aggregate-only evidence SHALL not satisfy this new gate. Counter reset/offset/inequality, caller phase tags and relaxed measurement checks SHALL NOT substitute for complete identities.

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

#### Scenario: Component pair reconciles all phases
- **WHEN** both genuine component topology arms and their owned guardian complete
- **THEN** their two physical original operation domains SHALL reconcile exactly to all warmup/measurement/drain request/terminal occurrences and eight worker totals under the unchanged bounds, separately from the measurement subset; zero-frame, aggregate-only or fabricated37-entry evidence SHALL fail.

### Requirement: Qualification and Q4 are complete before full launch readiness
Full-campaign preparation SHALL require all 32 qualification cells in one fresh valid attempt, authenticated guardian stop, successful lifecycle/closure and policy/resource promotion. It SHALL then require Q4 phase A with 560 runs, its identity/grant boundary, phase B with 560 runs and 280 sizing pairs derived from phase B, all bound to current authorities. Failed attempts and partial cells SHALL never be combined.

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
Remote full-campaign capacity admission SHALL require a current explicit operator guarantee in bytes, with UTC timestamp/reference, bound to the existing destination, actual 280 Q4 sizing pairs and successful upload/readback. The required capacity SHALL be max(500 GiB, ceil(projected_remote_bytes times 1.25) plus 5 GiB), using ten repeats. Undated notes SHALL not count as confirmation and capability URLs SHALL not appear in published evidence.

#### Scenario: Confirmation missing
- **WHEN** only an old 500-GiB estimate or undated 1500-GB note exists
- **THEN** full-campaign launch readiness SHALL remain blocked without fabricating confirmation; otherwise authorized qualification/Q4 SHALL not be blocked solely by that missing confirmation.

#### Scenario: Sizing or readback exceeds the guarantee
- **WHEN** actual required capacity exceeds the guarantee or upload/readback fails validation
- **THEN** cloud admission SHALL fail and full-run readiness SHALL remain false.

### Requirement: Launch handoff preserves the full experiment
The conditional full-campaign validated package and subsequent run SHALL preserve 4 systems, 2 codecs, 2 topologies, 7 policies, 5 deadlines and 10 repeats, yielding 2,800 pairs/5,600 arms, six streams, seed 20260323, 30-second warmup and 180-second measurement. They SHALL preserve paired order, schedule/seed equality, frozen model/preprocessing identities, fixed analysis and valid negative results. Canonical run/state/output paths and current accepted identities SHALL be bound; current stock preflight SHALL precede installation/start under the user's standing authorization.

#### Scenario: Unstarted package validates
- **WHEN** materialization and non-starting validation pass after accepted live preflight
- **THEN** the evidence packet SHALL include exact sanitized argv, receipt hashes, checkpoint/state paths and blockers; installation/start SHALL use that package only after all current gates pass, without claiming execution from materialization alone.

#### Scenario: Altered matrix or malformed command
- **WHEN** a candidate changes frozen counts/hashes/settings, uses corrupted variable names, wrong option order, or unsupported paths
- **THEN** preparation verification SHALL reject it before workload execution.

### Requirement: Documentation and conformance are truthful
One current runbook SHALL distinguish selected component release, diagnostic research, future full preparation/execution and finalization stages, correct corrupted examples, preserve original obligations and label historical status. A conformance record SHALL map every requirement/scenario to implementation and actual tests/manual evidence, including unresolved gaps. Reviewed appropriate CI SHALL execute on the final commit and explicitly distinguish hosted checks from physical hardware evidence. OpenSpec format checks, skipped hardware jobs and historical local suites SHALL NOT be reported as current CI or real benchmark acceptance.

#### Scenario: Documentation reviewed
- **WHEN** the runbook is delivered
- **THEN** shell examples SHALL pass syntax-only validation, supported flags/path constraints SHALL be checked against source, and actual launch/finalization commands SHALL be gated by the current accepted predecessor receipts.

#### Scenario: Required CI is unavailable
- **WHEN** no required checks have run on the final commit
- **THEN** merge readiness SHALL remain blocked and required CI setup/checks SHALL remain outstanding rather than being replaced by local tests or delegated review comments.

#### Scenario: Clean checkout lacks the frozen model assets
- **WHEN** CPU CI prepares an empty declared models destination
- **THEN** it SHALL acquire only the eight frozen XML/BIN HTTPS objects, enforcing exact per-file size and both manifest digests,64KiB chunks/128KiB buffers,24MiB namespace,120s/object and600s overall including teardown,15s-or-remaining socket waits and actual outer containment. Exclusive nonreplacing publication SHALL reject alias/path escape, corrupt cache, short/oversize/wrong digest/status/redirect and timeout without overwrite/deletion/automatic retry. Failed original partial/status/byte/error facts SHALL remain bounded and inspectable. The unchanged model test/full discovery and three native successes SHALL execute; acquisition SHALL NOT grant inference or hardware acceptance.

#### Scenario: Hosted test failure or interruption occurs before the suite report
- **WHEN** a discovered CPU test fails, errors, or remains active at job cancellation
- **THEN** existing result logging SHALL flush its original start/real terminal/elapsed and immediate original traceback/subtest failure; periodic60s original stacks and at most16KiB whitelisted host facts SHALL remain retained. An interrupted test SHALL have no invented terminal. Full selection,90-minute job and600000/615000-ms broker constraints SHALL remain; actual hosted exceptions SHALL precede a platform remedy, with no blanket skip or strict WSL/namespace waiver. Complete latest-source suite/source-before/after/report SHALL remain required for CI success.

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
- **WHEN** a component receipt or unknown kind is supplied to qualification, accepted-policy, promotion, Q4 or full publication
- **THEN** the full entrypoint SHALL reject it even when an accepted=false flag or structurally complete historical table is present; both original full kinds SHALL retain their strict behavior.

#### Scenario: Component request is outside its original pair
- **WHEN** a component service receives a request without active capture or for an unplanned system, arm, source context or policy
- **THEN** it SHALL reject before backend inference using the actual bound two-operation context, without granting permission from the historical complete declaration.

### Requirement: Operations retain bounded ownership and worker termination facts
Each bounded diagnostic and long-running benchmark stage SHALL have one persisted original owner, fresh output reservation, sanitized argv and actual process/unit identities, bounded lifecycle deadlines and immutable receipt-last outcome. A worker exit SHALL preserve original terminal status and available engine/cgroup/kernel/log evidence with source/time or explicit unavailable facts before disposable cleanup. Unknown causes SHALL remain unknown; exit 137 SHALL NOT alone be identified as OOM. Cleanup SHALL target only owned workers/sockets after preserving evidence, and worker replacement or silent measurement retry SHALL NOT produce acceptance.

#### Scenario: Worker exits during a diagnostic
- **WHEN** an owned worker dies or becomes unavailable
- **THEN** the diagnostic SHALL fail nonpublication, retain bounded original process/container/log/resource facts, stop owned dependents and block acceptance without automatic replacement.

#### Scenario: Historical guardian already failed
- **WHEN** original failed g evidence is examined or a prior stage is terminal
- **THEN** its actual terminal/lifecycle SHALL be retained without retroactive clean stop, duplicate owner or rewritten success; only a fresh valid context may execute changed bytes.

#### Scenario: Original launcher terminates during container ID publication
- **WHEN** the owned launcher exits or fails while its container ID is missing or partially published
- **THEN** bounded original file/process facts SHALL be retained, valid partial publication SHALL remain pending within existing limits, and terminal ownership SHALL be rechecked after launcher completion; cleanup success SHALL require positive exact ownership, preserved terminal state, actual owned removal and subsequent CID/name absence. Earlier NotFound or unavailable terminal state SHALL NOT be reported as post-removal quiescence or successful execution.

#### Scenario: Early broker setup fails with a validated durable journal
- **WHEN** either normal or held broker setup fails after journal validation
- **THEN** its failed terminal SHALL use the existing exclusive intent/barrier/response sequence, retaining actual bounded stage/type/errno and owner/authorization limits; emission failure SHALL remain failed. No child work or accepted publication SHALL be inferred, and unvalidated requests SHALL NOT receive durable authority.

#### Scenario: Quiescent broker has no durable terminal response
- **WHEN** the parent observes original broker capture/exit/quiescence but the required validated journal response is absent
- **THEN** it SHALL fail promptly with bounded original diagnostic facts rather than spend another execution allowance or accept stdout as durable authority;600000-ms execution and15000-ms cleanup constraints SHALL remain unchanged. Hosted setup errno/crash cause SHALL remain unknown until actually observed.

#### Scenario: Validated worker transport fails before frontend exit is visible
- **WHEN** the first validated production request fails on its exact owned worker route while the Docker frontend has not reported exit
- **THEN** shutdown SHALL retain that route's bounded original failure-time process/container/log snapshot exactly once before disposable teardown, without moving a live capture writer's file offset; the diagnostic stage SHALL distinguish worker invocation from front response transmission. Live or unavailable facts SHALL NOT be reported as terminal exit, clean stop or cause. Observation failure or a later concurrent failure SHALL NOT replace the original request failure or grant acceptance.

#### Scenario: Worker history contains frequent health-check events
- **WHEN** bounded original worker termination history is observed
- **THEN** the query SHALL use the original container identity and container die/oom/kill/destroy filters under the existing2-second,8192/1024-byte and32-record bounds; cap failure or unavailable history SHALL remain explicit, and missing OOM events or exit137 alone SHALL NOT establish OOM attribution or its absence.

#### Scenario: Original native measurement has a failed captured terminal
- **WHEN** an original measured engine child has nonzero return, timeout, capture overflow or drain failure
- **THEN** the producer SHALL exclusively preserve its already captured stdout/stderr bytes at the existing8MiB/channel bounds before disposal, with a <=4KiB nonauthorizing adjunct binding unchanged original launch/terminal descriptors, raw hashes and actual incomplete-capture flags. Persistence failure SHALL remain sticky failed, original failure facts SHALL survive, and no additional measurement, successful receipt or publication authority SHALL be inferred. Successful calls SHALL retain their existing schema and SHALL NOT produce a failed-call adjunct.

### Requirement: Scientific interpretation matches the executed workload
Final outputs SHALL describe the opaque ResNet workload as `topology_load_proxy_only` under common OpenVINO CPU/TensorRT CUDA workers and limit backend comparisons to observed topology/scheduling/transport/resource behaviour. They SHALL retain real deadline/drop/negative outcomes and distinguish additive work from nonadditive elapsed diagnostics. Real KPP accuracy, backend-native inference rankings, true NVDEC busy time and formal AW-HEFT equivalence SHALL NOT be claimed without independently accepted corresponding evidence.

#### Scenario: Relative quality passes despite absolute deadline misses
- **WHEN** a paired quality difference satisfies the frozen rule but both arms miss an absolute SLO
- **THEN** outputs SHALL report those actual misses and may report only the supported relative result, without claiming absolute SLO compliance or changing deadlines.

#### Scenario: Only proxy or partial resource evidence exists
- **WHEN** accepted execution uses opaque models or lacks direct evidence for a resource quantity or formal scheduler equivalence
- **THEN** analysis and claim state SHALL retain the exact proxy/coverage limitation without relabelling it as the missing scientific proof.

#### Scenario: Frozen policy labels are placement aliases
- **WHEN** the HEFT and deadline-aware HEFT selectors have the proved identical finish ordering, allowed set and tie rules
- **THEN** outputs SHALL identify the labels as placement aliases/expected algorithmic null control, retain their frozen coordinates and actual run noise, and SHALL NOT claim a distinct deadline-aware algorithm advantage or silently alter formulas/remove arms.

#### Scenario: Deadline and attributed elapsed measurements are saturated or confounded
- **WHEN** the worst-stream deadline statistic saturates or decoder wall residence dominates attributed elapsed cost
- **THEN** outputs SHALL report actual latency/drop/headroom and the guardrail's lost sensitivity, label C_obs as partial observed attributed stage elapsed, and SHALL NOT infer CPU work, NVDEC busy time, energy saving or absolute compliance from duplicated waiting intervals or a zero relative violation difference.

#### Scenario: Decoder mechanism research precedes an adopted regime
- **WHEN** the four reviewed isolated original-media default/zero display-delay research runs execute
- **THEN** they SHALL retain exactly 32 original paced access units per run, preselected central timing, complete per-PTS pixel/caps/completeness/order evidence, actual package/plugin/library/source identities, original bounded ownership/terminals and immutable nonpromoting receipts; no host decoder, model acceptance, benchmark count or qualification grant SHALL be substituted, and any adopted pipeline/corpus/deadline/metric change SHALL wait for a further exact-commit planning review.

#### Scenario: Research fails before source or decoder admission
- **WHEN** a physical research attempt fails during setup with no source/decoder cohort
- **THEN** its original errors, available facts and unknown causes SHALL remain immutable without a causal decoding conclusion; a reviewed setup correction SHALL retain named failure stages, bounded traceback and actual initialization metadata, and only an independently reviewed fresh attempt of the same fixed experiment and limits SHALL proceed, with zero automatic retry, fallback initialization or cohort search.

#### Scenario: A strict research file pin fails without original path facts
- **WHEN** actual attempt02 is reviewed or a subsequent strict file pin rejects an input
- **THEN** original unknown cause and zero-AU failure SHALL be preserved; new artifact-v3 SHALL record bounded requested/resolved path, original fstat/lstat/type/link/size/predicate/limit and inner stage/traceback when available before cleanup, without weakening checks. One exact-reviewed fresh attempt03 MAY execute the same fixed experiment/caps after focused negatives and implementation freeze; any actual predicate remedy SHALL require further source-grounded review, and no automatic retry or research acceptance SHALL be inferred.

#### Scenario: A mapped library has several hard links
- **WHEN** an already selected library has positive hard-link count and its original bounded process-map device/inode matches the held regular file and named resolved file before hashing
- **THEN** the explicit mapped-input Pin MAY accept those original backing bytes under unchanged size/hash/ancestor/full-epoch checks; ordinary plan/code/media/CID/evidence Pins and default cache hits SHALL retain single-link rejection. Conflicting/malformed/deleted mappings, mismatched identity or later bytes/path/link-count mutation SHALL fail. Mapping identity SHALL NOT imply memory-page integrity or a particular reason for the link count.

#### Scenario: Reviewed mapped-input correction precedes another research attempt
- **WHEN** the closed failed attempt03 diagnosis is used to implement artifact-v4
- **THEN** original failures and independently verified owned cleanup SHALL remain immutable; focused actual mmap/file/process negatives and exact source/dispatch review SHALL precede one fresh attempt04 under the same four32-AU source/order/cohort and every original cap. No automatic retry, changed scientific regime or research/benchmark acceptance SHALL follow from the setup correction alone.

#### Scenario: Unchanged intake runs before mechanism research completes
- **WHEN** selected component inputs retain the exact frozen intake and no causal decoder correction is claimed
- **THEN** incomplete four32-AU mechanism research SHALL NOT block genuine component execution; failed original research SHALL remain separate, and any changed intake/pipeline/cadence/deadline/metric or causal correction SHALL require its reviewed scientific evidence before adoption.

#### Scenario: Selected mapping and visible file identities differ
- **WHEN** a selected library's bounded original process mapping has a backing device/inode different from the unchanged held and named visible file identity
- **THEN** artifact-v6 SHALL accept the explicit mapped-input case only after a short private read-only mapping of that exact held file descriptor proves the same complete backing device/inode through its actual buffer address, containing range, permissions and effective file offset. It SHALL retain both identity views, full held-byte hash, size, ancestor and seven-field visible epochs; an inode-only match, named reopen, copied-file/hash-only substitute, ambiguous or unavailable join SHALL fail. The existing direct-view positive-hardlink case SHALL remain valid, and no capability or privileged map-file access SHALL be added.

#### Scenario: A mapped file is reused through the package cache
- **WHEN** the same physical library is requested through a fresh or cached explicit mapped-input route, or later through a default route
- **THEN** both mapped routes SHALL apply the same complete identity and unchanged visible-epoch checks, including expected size and full-byte hash when supplied; a cached mapped allowance SHALL NOT grant a default caller positive-hardlink acceptance. Ordinary plan/code/media/CID/evidence and default cache routes SHALL retain single-link rejection, and later path/ancestor/bytes/link/size changes SHALL fail.

#### Scenario: Alive mapping observations belong to self or the original source child
- **WHEN** selected library rows are observed for the guest process or its recorded original source child
- **THEN** bounded before/after observations SHALL bind the same PID, PPID, startticks, UID, GID and boot identity and the entire selected mapping multiset with addresses, permissions, offsets, device, inode and path. They SHALL distinguish the target owner from the guest-owned temporary bridge, reject changed/exited/reused owners and changed or ambiguous selected ranges, and keep source-child observation after READY and before START/ACK. Only the uniquely observed temporary self bridge may be excluded during comparison; later file verification SHALL NOT claim that a departed source PID or its mappings remain alive.

#### Scenario: A backing observation or its retirement fails
- **WHEN** buffer acquisition, mapping parse/join, hash, metadata persistence, export release, mapping close or owned descriptor retirement fails or exceeds its bound
- **THEN** the original primary exception and available failure-time facts SHALL be retained before retirement; each successfully acquired export SHALL have exactly one release obligation, later owned retirement steps SHALL still be attempted, and separate cleanup failures or unavailable retirement facts SHALL remain explicit. Failed or unverified retirement SHALL produce nonzero failure and no later setting, identity fallback, automatic retry or successful receipt inferred from an earlier provisional terminal. Original maps1MiB-plus-sentinel and all existing evidence/event/clock caps SHALL remain enforced.

#### Scenario: Reviewed planning bytes outlive task progress and archive
- **WHEN** the reviewed successor planning commit is used from a supported repository or worktree after legitimate task updates or OpenSpec archive
- **THEN** the execution SHALL bind the exact approved planning commit and retain bounded raw Git blobs and exclusive physical copies of its proposal, design, tasks and delta spec. It SHALL distinguish those immutable reviewed bytes from current checkout files, reject absent/foreign/oversize/unavailable commit or blob observations, and SHALL NOT require current task bytes or active planning paths to equal the reviewed commit or use a hardcoded historical Git directory.

#### Scenario: Reviewed source and immutable physical inputs have separate roots
- **WHEN** the successor executes reviewed code from a repository distinct from its frozen original prerequisite and media root
- **THEN** its sealed plan and original launch/terminal evidence SHALL bind the exact planning and independently reviewed implementation commits, actual repository and physical input roots, runtime/helper bytes, retained planning blobs, historical prerequisite/source/media descriptors and original image. Actual code/helper bytes SHALL match their reviewed or separately frozen authority before launch; archived paths or merged source SHALL NOT silently replace frozen input descriptors. Historical image availability SHALL NOT establish that packaged source/plugin binaries were built from the new implementation commit.

#### Scenario: Execution mode is explicit and sealed end to end
- **WHEN** the successor controller or guest is invoked
- **THEN** an explicit metadata-only or research mode SHALL be required and agree with the sealed plan, original launch and mode-specific terminal before source/run creation. Missing, invalid or mismatched mode SHALL fail without defaulting or transitioning to research. Metadata completion SHALL require its own truthful success predicate; the research mode SHALL retain its exact-four fixed-order completion and first-failure stop predicates.

#### Scenario: Metadata-only preflight completes without a source cohort
- **WHEN** the independently reviewed successor is dispatched once in metadata-only mode
- **THEN** it SHALL perform the original bounded packaged initialization, fresh registry, factory/plugin and input/library pin checks under unchanged image/grants and produce zero original source processes, AU admissions, decoder pipelines, property interventions or run namespaces. Its closed original evidence SHALL bind actual initialization, guest ABI and direct/backing observations and mode-specific completion with runs_completed0, research result null and all scientific/benchmark/native/qualification/model/publication authority false or zero. Guest final rehash, receipt and stream/pin close SHALL obey the remaining shared host-plus-guest120-second prelaunch budget; owned controller cleanup/finalization SHALL retain the original15-second and whole600-second bounds, with late/close companions blocking success.

#### Scenario: Inherited and successor regressions are actually discovered by CI
- **WHEN** artifact-v6 implementation is verified
- **THEN** the complete66-method inherited companion inventory and all approved new identity/owner/mode/planning/retirement/deadline cases SHALL execute in an isolated bounded test process through discoverable repository CI. Original per-case started/terminal IDs, outcomes, logs, source bytes, child return and timeout/cleanup facts SHALL be retained, with zero failures, errors, skips, expected failures or unexpected successes required for GREEN. The two existing actual15-second outer finalization negatives SHALL execute; an empty or partial suite, historical55-case receipt, aggregate count or baseline CI without the adapter SHALL NOT establish successor coverage.

#### Scenario: One metadata-only deployment precedes independent cold review
- **WHEN** focused RED/GREEN, latest-commit required CI and exact successor source/dispatch review permit the fresh metadata-only deployment
- **THEN** one original invocation SHALL consume a fresh owned namespace under the original isolation and exact-positive ownership/cleanup rules. An independent bounded cold read of its closed physical descriptors, mode/plan/source/owner joins, planning blob copies, closed membership, original logs/terminals and failure companions SHALL precede any research eligibility. Original failed attempts and false/null cleanup fields SHALL remain immutable; PID capture, an inner owned removal or setup success SHALL NOT be relabelled as an independent outer cleanup, scientific completion or current global absence.

#### Scenario: Accepted preflight permits one separately dispatched unchanged experiment
- **WHEN** the original metadata-only attempt passes independent cold review and a separate exact-commit review approves the explicit research dispatch on the same reviewed planning and frozen successor source
- **THEN** one fresh research invocation SHALL execute only the unchanged front_gate/default, front_gate/zero, underbody/zero, underbody/default experiment with exactly32 paced original AUs per run, original scale600/cadence/ACK/cohorts/pipeline/property comparison and every120/45/10/15/600-second and byte/event bound. It SHALL stop after the first failure and retain its original prefix without retry, resume or cohort search. No source run SHALL start automatically after metadata completion or after failed/unreviewed preflight; an unexecuted or incomplete scientific cohort SHALL remain explicitly unexecuted or incomplete.

#### Scenario: Original successor research evidence is cold reconstructed
- **WHEN** the conditional four-run original research attempt is reviewed
- **THEN** an independent bounded physical replay SHALL reconstruct original32 admission/status/ACK/START/STOP and80-byte transport/header/payload identities, complete per-PTS sink/src/RGB multisets, pixel/caps/completeness/order pairs, actual sink EOS and startup/central/tail timing from retained raw leaves before any supported timing interpretation. It SHALL bind the same reviewed planning/source/image/mode and preserve failures, unknowns, central flush-only insufficiency and hash/backpressure limitations. Old version-bound cold readers or producer summaries SHALL NOT substitute for this replay, and no decoder busy-time, pipeline adoption, model/parity, benchmark/qualification/publication or full-campaign grant SHALL follow from this research alone.

#### Scenario: External containment extends the controller owner record
- **WHEN** closed original controller evidence records PID, PPID, startticks, UID, GID and boot identity and its external capture records those same six fields plus original process-group and session identity
- **THEN** independent cold review SHALL validate each exact recorded schema and compare all six core fields strictly, while separately validating the external child and parent eight-field records, positive integer group/session identities, original owner/launch/terminal and child-to-parent joins and child new-session containment. It SHALL retain the parent's original group/session facts without assuming parent leadership. Additional genuine group/session facts SHALL NOT make an otherwise matching core owner fail whole-dictionary equality, and SHALL NOT be discarded, fabricated or accepted without validation. Missing, changed or arbitrary extra owner fields and incompatible containment SHALL fail; an observed departed owner's records SHALL NOT imply current liveness or global absence.

#### Scenario: Guest and controller retain different paths for the same terminal
- **WHEN** the original guest stdout receipt names the sealed mode's terminal under `/opt/vast/output/metadata/` and the controller retains the physical descriptor under the same attempt's `guest/metadata/` directory
- **THEN** independent cold review SHALL require each exact mode-specific path in its original namespace, translate only the permitted guest output alias to the expected physical leaf, and join both descriptors to that held regular file with identical size, full SHA and unchanged named/held/ancestor/seven-epoch checks. Both original paths SHALL remain recorded. Foreign roots, alternate aliases, traversal, wrong mode/leaf, size/hash mismatch or changed physical bytes SHALL fail; neither raw-dictionary equality nor basename-only acceptance SHALL replace this join, and the general output translator SHALL NOT admit arbitrary physical paths.

#### Scenario: A corrected observer reads an immutable original attempt
- **WHEN** a separately reviewed observer correction at commit C reads the original closed producer evidence at P1/S2 after an independently reviewed planning amendment P2
- **THEN** paired observer-repository-root/observer-commit inputs SHALL independently bind supported Git, the approved raw P2 blobs, compatible P1/S2/P2/C ancestry and the executed observer's raw C bytes/full hash/current held epochs; missing one of the pair SHALL fail, and omitting both SHALL retain the same-version producer-repository/source default only when that source incorporates P2. Original S2 SHALL require an explicitly supplied separately pinned C/repository. Original runtime, sealed plan, P1 copies, producer checkout/root and original external-observer descriptor SHALL remain checked at P1/S2 without retroactive retargeting; the report SHALL keep the separate observer_binding out of those original producer bindings. Exact-C tests/required CI and independent source/once-read review SHALL precede one fresh exclusive corrected cold report against that same closed attempt. Original FAILED verification and data SHALL remain immutable; the correction SHALL neither repeat metadata execution nor start source/AUs or grant research eligibility before the actual corrected result independently passes every unchanged cold predicate. Any newly exposed failure SHALL remain failed and stop the conditional scientific gate.

#### Scenario: A cached file is checked in a later owned phase
- **WHEN** a previously held physical input is reused during a later startup, body or cleanup phase
- **THEN** its unchanged full-byte recheck SHALL obey that phase's existing absolute deadline and retain the same held descriptor, named/ancestor/seven-field epochs, mapped identity, size and hash predicates. An expired acquisition deadline SHALL NOT reject a recheck which completes inside the current phase, and a future acquisition deadline SHALL NOT permit a recheck after the current phase expires. No relative-clock reset, omitted hash, extra cleanup time or replacement of the original120/45/10/15/600-second limits SHALL be introduced; any actual current-phase or physical failure SHALL preserve first-failure stop and retirement semantics.

#### Scenario: A reviewed phase-clock correction precedes fresh source-bound observations
- **WHEN** the closed failed S2 research and C cold disposition leads to independently approved amendment P3 and a separately frozen corrected source S3
- **THEN** the original failed invocation,32-AU front_gate observations, incomplete cleanup, unexecuted underbody and unaccepted full128/64 result SHALL remain immutable without setting/intake/adoption promotion. Latest exact-S3 required CI, independent ordinary-source/dispatch review and raw P3 planning evidence SHALL precede one fresh metadata-only invocation and accepted independent cold gate, followed only by a separate once-only unchanged four-by32 research grant and independent actual cold disposition. Producer P1 and observer P2 authorities SHALL remain distinct from P3; the observer SHALL bind S3 or an explicitly reviewed compatible later commit, with same-version C3=S3 permitted and old C never substituted for future S3. New separately reviewed clock-fixed namespaces and a helper copy changing only the two mode-prefix literals SHALL isolate those operations without retry, resume, overwrite or combination with S2 prefixes. Every original mode, source/image/input, cadence/cohort, clock, byte, FD, ownership, close and scientific predicate SHALL remain mandatory; complete/numeric conclusions SHALL require all four valid new run terminals/full128/64 and accepted cold evidence, while any failure or unexecuted dependency SHALL remain explicit and nonpromoting.

#### Scenario: Bounded mapped evidence is independently replayed after producer completion
- **WHEN** the original S3 four-run producer completes but its original C3 cold review rejects the closed metadata namespace or the serialized mapped-input document admission limit
- **THEN** a separately exact-commit reviewed P4 observer correction MAY admit at most40 metadata leaves derived from eight fixed research leaves and the existing16 before/closed mapping collections, and at most2MiB only for the exact expected before/closed mapping documents and source-READY reads of those same descriptor-bound collections. Both exact physical BEFORE and CLOSED mapping-name sets SHALL equal the ordered declared final collections: the observer SHALL add strict BEFORE-set equality while preserving the existing CLOSED-set predicate, sequence and descriptor joins, and SHALL reject orphan or alternate BEFORE names even below the count ceiling. General JSON/maps/channels1MiB, run32/controller128 leaf limits, exact mode/ordered collection/path/kind/size/hash joins, metadata16MiB, total/report/FD/epoch/Git and continuous120s cold bounds SHALL remain mandatory; larger, foreign, changed or inconsistent evidence SHALL fail. Meaningful real-file RED/GREEN and full latest exact-S4 CI/source/once-read review SHALL precede one exclusive corrected cold report over the immutable P1/S3 producer evidence with independently recorded P4/S4 observer authority. Original FAILED verification and producer/raw/tool identities SHALL remain unchanged, no producer/helper/source/AU/research replay or retry SHALL occur, and complete/numeric findings SHALL require independent reconstruction of all four32-AU runs/full128/64 and actual accepted close/retirement evidence, otherwise retain truthful failure without promotion.

### Requirement: Component release closes durable results and repository evidence
Component release completion SHALL require four original accepted arms/two descriptive pairs with retained raw source/model/resource/operational/measurement evidence, two owned authenticated guardian closures, strict cold validation, reproducible command and truthful tables/plots/limitations. It SHALL preserve genuine negative deadline/effect results and report unestimable quantities explicitly. Qualification/Q4/publication/full eligibility and executed full-campaign counts SHALL remain false/zero. The legacy original unchecked tasks/clauses SHALL remain unexecuted in the exact historical register; a component slice SHALL NOT complete a mixed full-scope task. Current required native/ext4/hosted CI, conformance and reviewed warnings SHALL precede supported sync/archive in this same branch/PR, with all active release tasks complete. Archive/main specs SHALL be committed/pushed; latest-commit checks and exact final review SHALL precede merge. The conditional full campaign still requires5600 accepted arms/2800 pairs and its original stock verification/finalization/storage gates before its own completion can be claimed.

#### Scenario: Full benchmark finishes with valid negative results
- **WHEN** a future full campaign completes every originally required arm/pair/storage transaction and stock verification/finalization/export
- **THEN** full completion SHALL report its actual immutable5600/2800 counts and valid outcomes; four component arms SHALL never substitute.

#### Scenario: Accepted pairs exist when transient offload fails
- **WHEN** supported full-campaign transport/low-storage recovery resumes its same valid checkpoint
- **THEN** existing accepted pairs SHALL be reverified/offloaded without remeasurement and raw cleanup SHALL wait for verified durable receipts; a local component receipt SHALL confer no remote capacity/offload grant.

#### Scenario: Completion or final repository gate is missing
- **WHEN** any active component result, physical closure, required final CI/conformance, pushed archive or applicable final review is missing
- **THEN** component completion/merge SHALL remain incomplete; a partial attempt, historical suite, document check or delegated comment SHALL NOT substitute. Missing future campaign results SHALL remain explicitly unexecuted rather than falsely checked.

#### Scenario: Selected component release finishes
- **WHEN** all four real native arms/two owned contexts, strict cold/operational checks, durable results/commands and final repository gates pass
- **THEN** only the selected descriptive release SHALL be complete, with actual component counts and false full eligibility; the historical campaign register SHALL remain preserved with every original incomplete scope.

### Requirement: CPU CI observation preserves native process invariants
CPU CI observation SHALL preserve the pinned Python3.12.3, full discovered selection, original required native successes, source-before/after/report and90-minute whole-job gate,600000/615000-ms production ABI and strict native-task/namespace/WSL predicates. An external original parent SHALL supervise exactly one fresh full-suite child. Periodic observation SHALL add no watchdog or timer thread to that child and SHALL retain scheduled60s requests plus actual completed responses and explicit late/missing/coalescing limitations. The existing hosted-interruption scenario's periodic-stack wording SHALL mean these actual observations, not a guarantee of60s response. Trace capture SHALL use a parent-drained bounded pipe with at most1MiB persisted trace, <=16KiB whitelisted host facts and <=8MiB new diagnostic namespace; overflow, observer/persistence/cleanup failure SHALL remain sticky failed CI. Original signal/nonzero/interruption, PID lifecycle and reachable source facts SHALL remain intact. The original139 cause SHALL remain unproven absent actual causal evidence. This observer SHALL confer no component/scientific/full grant.

#### Scenario: Full-suite worker enters strict native containment
- **WHEN** CPU CI launches its original full-suite child and a test enters the production subreaper
- **THEN** observation SHALL introduce no additional child native/Python thread or descendant observer; actual native task facts SHALL remain observable and any existing import-created task SHALL still fail the unchanged predicate. No per-test substitute child, Python bump or predicate waiver SHALL replace full selection.

#### Scenario: Scheduled stack request is late or absent
- **WHEN** an original scheduled60s request reaches delayed Python dispatch or a response is absent or potentially coalesced
- **THEN** actual send/response/arrival times and their clock domains SHALL be retained with honest late/missing/ambiguous delivery state; sending SHALL NOT imply a completed stack, no timely response SHALL be invented, and test/job deadlines SHALL NOT reset.

#### Scenario: Trace channel overflows or persistence fails
- **WHEN** the parent observes more trace bytes than its fixed1MiB allowance or capture/write/drain/EOF/observer failure
- **THEN** it SHALL retain only the bounded original prefix and available failure facts, fail CI permanently for that attempt and contain only the owned child within existing absolute limits; a direct unbounded trace file, silent truncation with success or accepted cleanup inference SHALL NOT substitute.

#### Scenario: Full-suite child crashes or is interrupted
- **WHEN** the original suite child exits by signal/nonzero or is contained at cancellation/timeout
- **THEN** its original status and actual process/FD lifecycle SHALL remain failed, incomplete test starts and absent final source/report facts SHALL remain explicit, and no successful test/suite terminal or replacement run SHALL be manufactured. The observer SHALL stop requests before teardown and use existing bounded remaining cleanup.

#### Scenario: Namespace setup emits a generic denial
- **WHEN** actual namespace setup reports errno13 without an exact original userns policy denial join
- **THEN** at most one preselected bounded diagnostic SHALL retain actual syscall/stage/errno/PID/interpreter/label and at most64KiB relevant timestamped denial facts or their unavailability within20s execution plus10s-or-remaining cleanup; a sysctl value or generic errno SHALL NOT authorize a profile, global change or namespace success claim.

#### Scenario: Exact executable userns policy denial is observed
- **WHEN** an original syscall/PID/executable/label/time join establishes a userns policy denial for the actual pinned interpreter
- **THEN** only a separately reviewed job-owned ephemeral per-executable profile MAY be applied, preserving actual profile/load/unload/operation evidence and rejecting collision/foreign/unavailable or failed enforcement. Global sysctl changes, privileged backend/capability bypass, alternate sandbox, blanket skips, Python upgrade and automatic retry/profile search SHALL remain prohibited.

#### Scenario: Observer repair passes focused checks
- **WHEN** focused observer or conditional policy regressions pass
- **THEN** current complete hosted source-before/after/report/full-selection/required-native and final ext4/conformance gates SHALL still be required; Decision23 four-arm physical/cold/scientific/repository acceptance and original unchecked campaign scopes SHALL remain unchanged and incomplete until actually verified.


#### Scenario: Original audit clock differs from the fine syscall clock
- **WHEN** the new declared namespace clock contract observes the original unshare and failed setgroups-open sequence
- **THEN** it SHALL retain available-or-unavailable clockid5 CLOCK_REALTIME_COARSE samples before unshare starts and after the failed open's original terminal timestamps, with exact integer values, phase, original PID/boot and monotonic sampling intervals enclosing those operations within the original capture/job. The unmodified millisecond audit MESSAGE timestamp SHALL join the inclusively millisecond-floored observed coarse endpoints, including equal endpoints, while all original identity/operation/chronology, journal reception and policy ownership/bounds remain required. No arbitrary larger tolerance, extra thread, repeated syscall or deadline reset SHALL substitute.

#### Scenario: New coarse-clock evidence is missing or inconsistent
- **WHEN** the live consumer expects the new contract from its trusted producer/capture source context but a denial record lacks both declaration and observations, or has missing, partial, unavailable, unknown-version, malformed, foreign, reversed, out-of-capture or out-of-bracket coarse-clock observations
- **THEN** CI SHALL fail before profile operations, retaining explicit original failure/unavailability without generic-errno authorization or fallback to a legacy clock join. Sampling failure SHALL preserve the original delegated syscall/result/exception; channel, row, report, diagnostic20+10 and whole-job limits SHALL remain unchanged.

#### Scenario: A legacy denial record has no new clock contract
- **WHEN** an explicitly selected historical or pure legacy context processes genuinely legacy retained records lacking the new namespace clock declaration and observations
- **THEN** their original strict fine-clock audit predicate SHALL remain required and every original failed outcome SHALL remain failed. New observations SHALL NOT be fabricated for earlier records, and fixture or later current CI success SHALL NOT relabel original B run37 or establish patched kernel/systemd binary provenance.

### Requirement: CI executes explicit portable contracts and preserves physical integration obligations

The active release's prior full hosted/ext4 selection references SHALL mean complete default-discovery inventory plus complete mandatory portable execution under the original external observer/one actual canonical Python3.12.3 child, original source-before/after/report/90m/600000/615000 and native-task/namespace predicates. All six CPU builds and three original required native successes SHALL remain mandatory. A versioned finite manifest MAY declare only exact individual physical integration IDs with source-derived reasons/required real-data or grant capabilities; every other discovered ID SHALL be mandatory portable by default. Complete sorted discovered/selected/integration inventories, manifest identity, exact outcomes and explicit unexecuted integration obligations SHALL be retained. The separately executed Decision23 four-arm model/source/resource/guardian/cold evidence SHALL remain required; no fixture/portable success SHALL confer full eligibility or execute a deferred campaign.

#### Scenario: Hosted executable is an alias and repository imports are isolated
- **WHEN** the actual3.12.3 launcher path resolves to a distinct canonical executable and isolated discovery needs repository namespace imports
- **THEN** the suite SHALL use the validated canonical real executable and fixed physical repository import path while preserving -I/-B, existing test IDs and strict interpreter predicates; imported project/tests/deploy origins SHALL be contained. Patching sys.executable, ambient PYTHONPATH, a Python bump or renamed mandatory IDs SHALL NOT substitute.

#### Scenario: Native build succeeds but a runtime factory is absent
- **WHEN** a required native regression needs appsrc/queue/videoconvert in the ephemeral hosted runtime
- **THEN** explicit runtime plugin/tool prerequisites and actual loaded-factory facts SHALL precede the unchanged required tests; missing factories or unsuccessful original native tests SHALL fail the lane. Package installation or a substituted pipeline SHALL NOT establish success.

#### Scenario: Shared imports reach new component helpers in a sibling image
- **WHEN** exact source closure discovers the two approved component authority/preprocessing helpers outside a sibling manifest/COPY set
- **THEN** only those reachable source entries SHALL be renewed through the original validators and affected inventories; affected sibling image/parity authorities SHALL remain historical/ineligible until their own renewal. Their metadata repair SHALL NOT rebind old receipts or block the independently current selected pair.

#### Scenario: Pure contract tests depend on ignored historical fixture files
- **WHEN** a portable test's actual intent is filesystem/transport/schema/negative-contract behavior rather than current real-data integration
- **THEN** coherent declared small metadata or freshly owned temporary physical fixtures SHALL preserve the original ID/assertions and carry explicit fixture provenance; missing temporary parents SHALL be created within the owned fixture root. Fixture outputs SHALL confer no physical model/image/full/component grant and SHALL NOT be installed as production inputs or used to replace real integration evidence.

#### Scenario: Manifest omits a portable test or hides a mandatory failure
- **WHEN** discovery returns a new/undeclared test, a declaration is duplicate/missing/malformed, or an integration assignment targets a mandatory native/interpreter/source/broker/safety regression
- **THEN** undeclared tests SHALL execute as mandatory portable; invalid declarations SHALL fail before acceptance. Failure-text classification, blanket module exemptions, automatic integration fallback and unexpected portable skips SHALL be rejected; legitimate platform skips SHALL retain exact audited IDs/reasons.

#### Scenario: Actual physical integration prerequisites are unavailable or historical
- **WHEN** an exact declared corpus/full-qualification/live integration method lacks its real bytes/grant, or old g receipts disagree with current selected renewal
- **THEN** its separate lane SHALL remain explicitly unexecuted or failed until genuinely provisioned and run, preserving original predicates and campaign obligation; it SHALL NOT count passed or as hardware acceptance. Current selected-identity tests SHALL bind the actual reviewed selected receipt, and no old aggregate authority SHALL be relabeled current or loosened to satisfy the test.

#### Scenario: Portable lane succeeds with remaining campaign obligations
- **WHEN** all required portable/native/build/source/report/skip gates pass on the current hosted and ext4 source but declared future integration remains unexecuted
- **THEN** results/conformance/archive SHALL report only the complete portable lane and independently verified selected component scope, with discovered/selected/deferred IDs/counts and false full eligibility. Historical failed full runs SHALL retain their original outcomes; selected physical/cold/model/resource/guardian gates and final exact-commit checks SHALL still precede release completion/merge.

### Requirement: Selected pair owns one physically held validation session

A successful original selected CLI pair SHALL retain one private genuine held-selected session after source materialization and through original runtime/two arms/cold closure. Source materialization SHALL retain its two complete stock assessments and the session SHALL perform one, totaling three complete model/numeric validations on that successful path. Public standalone entrypoints SHALL acquire independent full validation. The session SHALL preserve original full raw hash sweeps, held FDs/seven epochs/name/ancestor and engine/socket barriers, fresh original four-image observations at former validation boundaries, exact factory reconstruction and all original native/device/source/model/guardian/process/container/resource/operational/cold predicates. It SHALL confer no full qualification/publication/Q4 eligibility. Actual2100/2250/15 limits and measurement settings SHALL remain unchanged.

#### Scenario: Borrowed context is foreign or closed
- **WHEN** a private runtime stage receives a raw dict, foreign owner/root/authority or post-close session
- **THEN** it SHALL reject before launch/receipt; only the CLI's active genuine held lifetime MAY be borrowed and no public skip-validation parameter/global cache SHALL authorize it.

#### Scenario: One original pair traverses repeated runtime stages
- **WHEN** source, materializer, two arms and cold validation execute under one owned original command
- **THEN** complete stock model/numeric assessments SHALL total two source assessments plus one session assessment; original full byte barriers, fresh observed image facts and native wrapper probes/scans SHALL remain mandatory at their boundaries, and no partial assessor or old observation SHALL substitute.

#### Scenario: Public validator runs independently
- **WHEN** a standalone component materializer/executor/cold reader is invoked outside the private CLI session
- **THEN** it SHALL independently acquire genuine current selected inputs and execute the existing complete validation before delegation; a retained session from another call SHALL not silently authorize it.

#### Scenario: Held source or live engine facts drift
- **WHEN** bytes, inode/name/ancestor/seven-field epoch, engine/socket or a freshly observed original image binding differs from the held valid context
- **THEN** the original fail-closed checks SHALL reject before the next native launch or result commit, with actual first-failure evidence and bounded owned cleanup; epoch-only reuse or serialized old image facts SHALL NOT weaken verification.

#### Scenario: Cold consumer fails after real native arms
- **WHEN** CPU04 or another original command fails its final cold consumer
- **THEN** its original terminal/raw results SHALL remain immutable failed evidence. The prepared CPU04 copied consumer SHALL remain unexecuted: the unchanged full stock closure binds every source epoch as well as bytes, so producer-byte restoration cannot validate historical v5 after an edit. Producer restoration, known-failing assessment, historical receipt rebinding and waived closure checks SHALL NOT substitute for acceptance. Versioned historical consumer acceptance remains deferred; fresh original CPU/GPU CLIs under a new host closure SHALL still pass complete original cold validation and18.8.

#### Scenario: Runtime improvement is assessed
- **WHEN** the held-session implementation is reviewed or executed
- **THEN** at most12 fixed phase start/terminal pairs and16KiB nonauthorizing timing metadata SHALL report actual clock domains/durations and incomplete phases honestly. Source counts/logical hash-reader bytes SHALL NOT be called measured storage I/O or a speedup; real current original CPU/GPU/cold results and unchanged deadlines SHALL remain required.
### Requirement: Relocated selected execution preserves genuine physical validation

A selected execution MAY use a fresh isolated canonical ext4 project root at the exact reviewed source commit. Relocation SHALL preserve every declared original model/numeric/corpus/authority byte and sealed association, independently enumerate the full current closure beyond the held subset, reject unowned paths/links/different-byte collisions, verify original and destination physical bytes/names/epochs, and preserve the original Windows and WSL primary checkouts. Current selected/native/worker source/dependency/image checks and all stock validators SHALL remain unchanged. Relocated source epochs SHALL be captured in a NEW stock host closure; selected/capture/preprocessing/runtime/guardian/arm/cold authorities SHALL be genuinely produced under fresh names. CPU05's failed CLI and historical receipts SHALL remain unchanged. Preparation SHALL NOT extend original2100/2250/15 benchmark limits or alter intake/scientific/acceptance/CI/campaign scope.

#### Scenario: Genuine finite inputs are copied to a new root
- **WHEN** setup copies the source-derived full numeric/corpus closure and exact source/control inputs to an exclusive ext4 checkout
- **THEN** it SHALL retain original descriptor bytes and historical sealed observations, verify full current physical original/destination custody and exact model/source membership, record actual root/owner/space/Git identity and daemon bind-root reachability, and fail on missing/conflicting/unowned/link input or incomplete transfer. Setup alone SHALL NOT grant model/image/benchmark acceptance.

#### Scenario: A historical closure or execution receipt is reused after relocation
- **WHEN** a caller presents CPU05's source-epoch or execution authority as current at the new root
- **THEN** relocation SHALL NOT authorize its reuse or rewrite; a fresh stock source closure and newly produced current execution authorities SHALL be required while original producer outcomes and evidence remain immutable.

#### Scenario: A relocated pair completes or exceeds its original deadline
- **WHEN** the unchanged original CPU or separately owned GPU CLI runs against the fresh physical root
- **THEN** all original stock model/source/device/native/process/container/resource/guardian/all-phase cold and2100/2250/15 gates SHALL still decide acceptance; authentic raw/cold/CSV output with a late/nonzero original CLI SHALL remain failed, independent custody SHALL close before another grant, and no automatic retry, time reset, speedup inference or deferred campaign execution SHALL follow.
