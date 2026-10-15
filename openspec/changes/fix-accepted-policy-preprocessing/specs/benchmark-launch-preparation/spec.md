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

### Requirement: Recovery diagnostics preserve failure causes and unresolved child closure
Recovery diagnostic reports SHALL preserve an initiating failure independently from termination, receipt and cleanup failures, including signal-mask/timer restoration, stream closure and every result/enclosing-receipt write, with bounded typed operation/phase reasons, child identity and the observed original return code or explicit unknown state at every owned recorder/launcher/guest layer. Every started command SHALL receive an attempted bounded result record; a failed write SHALL be reported distinctly by enclosing capture rather than fabricated as success. All owned children SHALL remain tracked through cleanup, and forced or unproved closure SHALL prevent recovery acceptance regardless of other successful cleanup. Native publication diagnostics SHALL retain bounded sanitized cause/phase and available monotonic timing without weakening sticky-stop, original numerical, authentication, custody or restore-equality gates. Synthetic/offline reporting evidence SHALL execute the same v6 reporting/closure logic through a sealed fixture-only entrypoint unable to reach production main or real commands, and SHALL confer no real storage/recovery, image deletion/offload or qualification authority.

#### Scenario: An initiating failure is followed by finalization failures
- **WHEN** a controlled reporting-chain case has an initiating failure followed by termination, signal-mask/timer restoration, stream closure, result/enclosing-receipt or cleanup failures
- **THEN** the reports SHALL preserve that initiating cause and each distinct secondary cause with its original operation/phase and observed per-layer exit or unknown state; no later exception or cleanup success SHALL replace or clear the first failure.

#### Scenario: Child termination is forced or remains unresolved
- **WHEN** the first termination wait times out and the second wait either closes a killed child or also times out
- **THEN** both bounded signal/wait attempts and final observed return code or explicit unknown closure SHALL be retained, forced/unresolved closure SHALL reach the enclosing failure report and recovery acceptance SHALL remain false; an unforced outer launcher alone SHALL NOT prove graceful child closure.

#### Scenario: A command result or enclosing receipt cannot be written
- **WHEN** result persistence fails after an actual child was created or finalization remains incomplete
- **THEN** the available enclosing capture SHALL preserve separate receipt failure and primary/termination/cleanup causes with result availability explicit; absent durable evidence or a zero exit elsewhere SHALL NOT establish command closure or recovery acceptance.

#### Scenario: Native sampling or heartbeat publication fails
- **WHEN** a controlled native sample/write/flush/move/post-check failure or publication-budget violation occurs
- **THEN** bounded sanitized cause/phase and available monotonic facts SHALL survive generic wrapping, unavailable facts SHALL be explicit and sticky stop/unchanged floors and budgets SHALL still refuse; credentials or unrelated process contents SHALL NOT enter diagnostics.

#### Scenario: A synthetic child closes gracefully
- **WHEN** the isolated offline/synthetic recorder-to-launcher-to-guest case observes its own child close gracefully without finalization errors
- **THEN** the same v6 reporting/closure logic used by actual helpers SHALL record its observed diagnostic exit and graceful closure as synthetic evidence with recovery acceptance false through a sealed fixture-only entrypoint; unrelated mocks or AST/footer claims SHALL NOT substitute, and mode/command crossover SHALL refuse before production main or real commands become reachable.

#### Scenario: Diagnostic success is offered as authority for live storage or image work
- **WHEN** a diagnostic test passes or delegated diagnostic approval is presented for backing-storage rehearsal, a real restore, artifact upload or image deletion/offload
- **THEN** those actions SHALL remain unstarted under this diagnostics scope, all original failed roots/scratch/helpers/receipts/TARs and all227images SHALL remain protected, and each future live scope SHALL require its own applicable reviewed authority plus exact human image confirmation before deletion/offload.

### Requirement: Packaged accepted policy readers close their actual production dependencies
The supported default accepted-policy cold-reader path SHALL validate authority-v2 fragment, image-patch and producer-receipt inputs using a shared read-only receipt-validation dependency available in every runtime package. It SHALL preserve the public host receipt reader's signature, valid outputs, canonical/self-hash bytes, exact rejection and exception/cause behavior, shared default dependency identities and existing physical custody/descriptor checks without loading or executing host build orchestration. Dependency inventory SHALL cover transitive function-body/conditional/literal imports, fixed file-loader targets, finite module-name maps and supported default call paths, with explicit preserved host-only legacy/build-route dispositions. Missing reachable production dependencies or unresolved required routes SHALL block package acceptance. Tests SHALL use fresh isolated interpreters and actual renewed package versions without host production-source mounts, preloaded-module rescues or substituted production dependencies. Existing receipt kinds/schemas, sample/calibration/physical/renewal gates and original evidence SHALL remain unchanged.

#### Scenario: The default packaged authority reader has no host builder available
- **WHEN** a renewed runtime package independently cold-validates a valid authority-v2 fragment and its physical image-patch/producer-receipt chain through the supported production defaults while host builder and build materializer sources are unavailable
- **THEN** the read-only dependency SHALL be present and the real default path SHALL retain the stock valid result, identity and custody checks without importing or executing host build orchestration, an injected validator or a host-source fallback; successful import alone SHALL NOT establish this point-of-use behavior.

#### Scenario: Producer receipt or physical custody is invalid
- **WHEN** fresh cold checks encounter malformed/foreign/self-hash-invalid producer receipts, missing/directory/symlink/hardlink inputs or descriptor/receipt mutation at existing validation boundaries
- **THEN** the shared reader and preserved public host reader SHALL retain the original rejection predicates, exception classes/messages/causes and physical refusal behavior, and dependent materialization SHALL create no accepted output; extraction SHALL NOT relax or silently strengthen the receipt schema or reinterpret original evidence.

#### Scenario: Fixed or finite runtime dependency has no valid disposition
- **WHEN** dependency inventory finds a fixed file-loader target or finite module-name route beyond the literal graph
- **THEN** every supported production default path SHALL have its complete actual package closure, preserved host-only legacy/build routes SHALL have explicit source/call-path dispositions without gaining packaged authority, and any missing reachable dependency or unresolved required route SHALL block acceptance rather than be waived by a historical closure count, portable CI or conservative-name-only packaging.

#### Scenario: Cold reader is loaded in different supported orders
- **WHEN** standalone leaf and supported promotion-first/sidecar-first reader paths run in fresh isolated interpreters and the default cold receipt chain runs under each renewed image's observed interpreter/package versions
- **THEN** results, refusal behavior and shared public/default object identities SHALL agree without preloaded caches, host mounts or substituted production dependencies; unsupported host-only image orders SHALL remain explicitly unsupported, and every changed package/closure identity SHALL still require the existing complete renewal and consumer gates.

### Requirement: Fresh fixture compilation has a fixed bounded boundary
Fresh artificial fixture engine preparation SHALL use one qualified pinned compiler provider with fixed pre-exec isolation, resource and crash policies, bounded original source/channel/ELF export and positively established owned closure. It SHALL compile the actual fresh namespace/reply bindings without changing genuine coordinator, custody, production default validator, sample or refusal semantics. Unsupported provider/configuration, unqualified physical allocation, overflow, compiler failure, unavailable evidence or forced/unknown closure SHALL refuse acceptance without fallback, retry, old ELF reuse or erased originals. Component qualification SHALL require its own reviewed finite admission and SHALL NOT substitute for whole-chain capacity or genuine consumer acceptance.

#### Scenario: A fresh artificial engine is prepared successfully
- **WHEN** the single qualified provider compiles the actual current source/replies and namespace under the reviewed effective policy
- **THEN** bounded framed export SHALL retain the authenticated ELF, complete original channels and distinct original statuses, and positively verified unforced compiler/client/container closure SHALL precede use through the unchanged genuine custody/default-consumer path.

#### Scenario: The compiler or publication fails
- **WHEN** compilation, export, capture or persistence fails, overflows or loses a channel
- **THEN** preparation SHALL retain its first and distinct secondary causes, actual compiler/client/container statuses and bounded original prefixes with exact known counts or explicitly unknown remainder, SHALL create no accepted ELF/result, and SHALL preserve failed originals without automatic retry or provider fallback.

#### Scenario: Startup or a descendant attempts to enable core dumps
- **WHEN** the qualified runtime starts the first payload or a payload attempts CORE writes through either setter, upper-bit aliases or compatibility syscalls
- **THEN** pre-first-exec soft/hard CORE=1 and the immutable native-only seccomp policy SHALL prevent the piped crash helper from being enabled, preserve applicable stronger daemon restrictions, allow reviewed native read-only queries and harmless other-resource operations, and refuse unsupported policy/runtime drift.

#### Scenario: A resource bound or owned deadline is exhausted
- **WHEN** source, work bytes/inodes, memory/pids, channel/ELF/frame/metadata limits or the one enclosing deadline is reached, or cleanup is forced or unresolved
- **THEN** all retained/written forms SHALL stay within the reviewed pre-write bounds, the result SHALL remain failed with explicit original/closure availability, and client exit, later cleanup success or an extended/reset phase clock SHALL NOT confer acceptance.

#### Scenario: Component preparation is offered as complete repair evidence
- **WHEN** a compiler profile/probe or tiny fixture succeeds before whole-chain capacity, renewed packages and genuine consumer cohorts are independently accepted
- **THEN** task 1.5, renewal, complete 3840/3968/126016 and 29/20/42, current checks, conformance and archive/final approval gates SHALL remain required; old ELF, substituted defaults, synthetic enforcement or component success SHALL NOT close them.

### Requirement: Standalone fixture cold readers bound original capture and owned closure
The fixed complete-fixture standalone cold reader SHALL preserve its existing default validation program, genuine guardian/fragment/stock predicates, full provenance proof and identity checks while bounding original stdout and stderr to1,048,576B each and the complete result JSON to2,097,152B before encoding/retention/writes. It SHALL use one recipe-supplied absolute deadline within the unchanged enclosing budget, with predeclared finite observation/TERM/KILL/final phases and positively established actual owned-child/descendant closure, EOF and persistence. Overflow, nonzero, late, forced, unavailable or unresolved outcomes SHALL refuse reader acceptance without substituted defaults, cached proofs, retries or erased originals. Original prefixes/counts, explicitly unknown remainder and first/distinct secondary causes SHALL remain independently attributable; an inner receipt SHALL NOT attest its own completed write. Logical per-reader bounds SHALL NOT establish physical peak, whole-chain capacity or complete genuine acceptance.

#### Scenario: The unchanged default reader closes normally
- **WHEN** the actual current default reader returns its complete original proof within the reviewed byte/deadline limits and every owned child/descendant, channel and persistence boundary closes normally
- **THEN** its full proof, default/module/semantic identity checks and original raw bytes SHALL remain exact, with actual status and EOF retained; no production validator or scientific acceptance predicate SHALL be replaced.

#### Scenario: A raw channel or result exceeds its fixed ceiling
- **WHEN** stdout, stderr or complete encoded result metadata would exceed its selected ceiling
- **THEN** retention/encoding/writes SHALL refuse before crossing that bound, preserve the exact available raw prefixes with observed/discarded counts or explicitly unknown remainder, and record a bounded incomplete failure without accepted reader output or a larger allowance.

#### Scenario: A deadline or owned closure cannot be established
- **WHEN** the inherited deadline is missed, a child exits nonzero or by signal, termination is forced, a descendant/EOF remains live or unknown, or ownership is unavailable
- **THEN** the invocation SHALL remain failed with original statuses and separate closure facts; parent exit, incomplete empty-scope observations, later cleanup or a success-shaped proof SHALL NOT confer acceptance, reset time or authorize guessed cleanup.

#### Scenario: Capture and receipt failures follow an initiating failure
- **WHEN** an initiating failure is followed by read/wait/signal/identity/stream-close/flush/raw/result-write/result-close or cleanup failures
- **THEN** the first and every distinct secondary cause SHALL survive with available original bytes/statuses and explicit persistence uncertainty, including unknown unreturned write extent and enclosing capture when an inner result is unavailable; no receipt SHALL claim its own completed persistence.

#### Scenario: A bounded reader boundary is offered as complete repair evidence
- **WHEN** portable/controlled boundary tests or actual bounded reader qualification pass while parent/enclosing logs, proof copies, physical peak, renewal or genuine cohorts remain incomplete
- **THEN** whole1.5 and existing2.8/4.2-4.5/5.2/5.3/conformance/archive/final gates SHALL remain required, all preserved failures/history SHALL retain their original disposition, and neither the4MiB per-reader/16MiB four-fixture logical quote nor compiler approval SHALL grant additional execution or Q1/storage/image authority.
