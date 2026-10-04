## Purpose

Explain retained component benchmark latency, coverage and observation gaps without changing the original workload or granting new experiment acceptance.

## ADDED Requirements

### Requirement: Current status distinguishes completed release and incomplete campaigns
Current plan, progress and operating guidance SHALL identify the actual PR2 merge, distinct measured/implementation/final-check sources, completed process gates and current tasks. Earlier dated document content and archived evidence SHALL remain intact. Qualification/Q4/full campaign counts and eligibility SHALL remain unexecuted/false until their original acceptance gates pass.

#### Scenario: Previous release actions are already complete
- **WHEN** the latest merged release is reconciled with existing pending status
- **THEN** current guidance SHALL close the actual completed actions without repeating measurements or rewriting historical failure/snapshot records.

#### Scenario: Full input closures are stale
- **WHEN** the current source differs from a full backend receipt
- **THEN** the roadmap SHALL require that backend's actual source/image/packaged-validation renewal before full qualification and SHALL NOT treat component acceptance as full readiness.

### Requirement: Offline diagnostics retain original populations and identities
A public command SHALL read a caller-selected evidence directory containing retained frames, ingress ledger, branch terminals and frame events, with optional retained native policy evidence. It SHALL produce JSON and readable diagnostic outputs in a fresh exclusive directory, identifying exact input paths, sizes and SHA256. It SHALL preserve the recorded measurement cohort, join by run/frame/stream/trace identities rather than row order and separately report admissions, completed frames, dropped/censored frames, branch outcomes and absolute deadline results. No engine/model calls or raw changes SHALL occur. Outputs SHALL be diagnostic only and confer no cold/qualification/publication authority.

#### Scenario: Complete original evidence is analyzed
- **WHEN** all required input rows and identifiers consistently describe the selected measurement cohort
- **THEN** the command SHALL report its original denominators and completed-frame results with input identities, without rerunning any arm.

#### Scenario: Diagnostic deadline is explicitly supplied
- **WHEN** the caller supplies a finite positive diagnostic deadline
- **THEN** the report SHALL identify that parameter's provenance as caller_parameter, corroborate it against supplied optional native-policy deadline/arrival evidence and SHALL NOT invent an original deadline from CSVs which do not record it; a missing/nonpositive/nonfinite or contradictory supplied deadline SHALL fail.

#### Scenario: Cohort boundary wall clocks differ
- **WHEN** a recorded measurement admission lies slightly before the wall-clock measurement start but belongs to the recorded scheduled cohort
- **THEN** the command SHALL preserve the stock recorded cohort rather than selecting a new one by wall time.

#### Scenario: Malformed or inconsistent evidence is supplied
- **WHEN** input is missing, exceeds declared finite limits, contains nonfinite/reversed timing, duplicate/conflicting identities or an incomplete completed-frame branch path
- **THEN** the command SHALL fail clearly without reporting a successful diagnostic, modifying inputs or inventing zero observations.

#### Scenario: Output is occupied
- **WHEN** the requested output directory already exists
- **THEN** the command SHALL reject it without changing existing files.

### Requirement: Latency diagnostics report observed envelopes and unknown service components
For each completed measurement frame, diagnostics SHALL identify the branch with latest required postprocess completion, choose its branch-specific baseline decoder completion or the shared decoder completion, and report ingress-to-decoder and decoder-to-frame-join envelopes whose sum equals original end-to-end latency. Quantiles SHALL use linear interpolation at q*(n-1); empty populations SHALL return null with an explicit reason. Original stage spans SHALL be named parent-to-completion envelopes. Recorded equal queue-enter/start timestamps SHALL NOT imply measured zero true queue wait or pure worker service. Optional policy-path timings SHALL remain path envelopes with their own valid population and identity joins, not inference service. Decoder residence SHALL NOT be called NVDEC busy time.

#### Scenario: Critical-path branch varies
- **WHEN** different branches finish last on completed frames
- **THEN** decoder/residual diagnostics SHALL follow each frame's actual critical branch, avoiding sums of overlapping branches or sums of marginal quantiles.

#### Scenario: Queue timestamps are equal by construction
- **WHEN** promoted frame events record identical queue-enter and stage-start timestamps
- **THEN** outputs SHALL show the recorded span separately and label true queue wait and pure inference service unknown.

#### Scenario: Optional policy evidence is unavailable
- **WHEN** no optional policy evidence is supplied
- **THEN** frame diagnostics SHALL remain usable and policy-path quantities SHALL be explicitly unavailable, never zero.

### Requirement: Actual four-arm review preserves scientific limits
The shipped explanatory report SHALL reproduce all four original accepted CPU08/GPU02 arm counts and completed-frame end-to-end quantiles, independently verify critical-path decomposition and available native timing joins, and distinguish observation from causal hypothesis. It SHALL retain drops, negative deadline results, different completed subsets, one baseline-first pair per resource, two original recordings, common NVDEC and partial overlapping C_obs. Changed intake/cadence/decoder/metrics and causal speedup/service claims SHALL require separately reviewed controlled evidence before adoption.

#### Scenario: Decoder envelope dominates GPU latency
- **WHEN** retained raw data shows most completed latency occurs before decoder completion
- **THEN** the report SHALL state that observed envelope and its population, without attributing it solely to hardware, reorder/display delay or policy/worker service.

#### Scenario: Next performance experiment is proposed
- **WHEN** offline observations support a follow-up intervention
- **THEN** current guidance SHALL list the specific unresolved mechanism and controlled evidence needed while preserving original results and full-campaign gates.
