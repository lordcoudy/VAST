"""Decision23 planning only; preserve the exact Decision22 source and task states."""
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHANGE = ROOT / 'openspec/changes/fix-benchmark-preparations-spec'
RECOVERY = ROOT / 'artifacts/benchmark_recovery_20260930'
BASE = '9c514a60d644c8c3ecd637eb83185a59aa2a5e01'
PATHS = ['proposal.md', 'design.md', 'tasks.md',
         'specs/benchmark-launch-preparation/spec.md', 'verification-plan.md']
AUDIT = RECOVERY / 'decoder-attempt05-independent-failed-review-v1/review.v1.json'
assert hashlib.sha256(AUDIT.read_bytes()).hexdigest() == 'b0190bd4c9238aa98513b60806d4a0eef0037f626e88cf282db64f30ea292e05'
old = {}
pins = []
for name in PATHS:
    path = CHANGE / name
    raw = path.read_bytes()
    committed = subprocess.run(['git', '-c', 'core.longpaths=true', 'show',
        BASE + ':' + path.relative_to(ROOT).as_posix()], cwd=ROOT,
        check=True, capture_output=True).stdout
    assert raw == committed, name
    old[name] = raw.decode('utf-8')
    pins.append({'path': name, 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
tasks = re.findall(r'^- \[([ x])\] (\d+(?:\.\d+)+) (.+)$', old['tasks.md'], re.M)
assert len(tasks) == 72 and sum(state == 'x' for state, _, _ in tasks) == 31
scenario_names = re.findall(r'^#### Scenario: (.+)$', old[PATHS[3]], re.M)
assert len(scenario_names) == 82
requirements = re.split(r'(?=^### Requirement: )', old[PATHS[3]], flags=re.M)
assert len(requirements) == 17

proposal = '''## Why

VAST's publication prerequisites have prevented an independently verified benchmark result from being produced. Decision23 makes the existing runtime usable through a selected GStreamer component release, preserving the full campaign as explicitly unexecuted future work instead of making every campaign prerequisite a gate to basic operability.

## What Changes

- Deliver one original H.264 CPU baseline/shared pair and one separately owned GPU pair: four real arms, six streams/four branches, seed20260323,100ms deadline,30s warmup/180s measurement/10s drain, unchanged intake and source/graph semantics.
- Add an explicit nonpublication component authority over independently current selected image/source, eight workers/model bindings, preprocessing/output, calibration, resource/device/socket and owned output facts. Reuse the native runtime, production guardian/service, workers and operational recorders through three narrow seams: selected host materialization, component preprocessing dispatch and component cold result.
- Keep the complete historical four-system capability declaration verbatim as data; require exact actual selected-row equality. Keep full candidate/qualification/accepted-policy/Q4/publisher entrypoints strict and rejecting component authority. No partial assessor, new scheduler, fabricated full inputs, parity-reuse framework or old aggregate receipt rebinding.
- Retain exact physical common model/calibration evidence only after unchanged selected worker/model/preprocessing/output/toolchain closure verification and raw numeric checks; otherwise acquire missing selected evidence through existing checks. Preserve at least30 actual calibration samples per selected branch/resource cell.
- Make unchanged-intake execution independent of incomplete decoder research. Complete reviewed mechanism evidence remains a gate to a changed intake or causal decoder correction claim. Preserve failed attempts01-05, original limits and actual device2112 versus77 rejection with unknown underlying cause; no sixth experiment is required by this release.
- Retain prior payload/rejection/accounting/retry/native/history/checkout repairs, bounded owner/worker failure evidence, the portable peer unit and reviewed durable broker terminal repair. Renew only dependencies actually changed by component implementation.
- Require original terminals, authenticated guardian closure, complete all-phase identity matching, ingress-derived measurement membership and strict physical model/source/resource/cold checks. Publish descriptive latency/deadline/drop/coverage and paired topology results, including valid negative or unestimable effects with explicit reasons.
- **BREAKING scope change:** release completion no longer asserts32-cell qualification,1120 Q4 runs/280 sizing pairs, remote capacity admission, static-hybrid execution or5600 arms/2800 pairs. Their original clauses, task IDs and unchecked states remain in the exact historical register and existing full entrypoints; they are not executed by deferral or by four component arms.
- Complete required final native/ext4/hosted checks, current conformance, durable raw results/reproducible commands and own-thought review; sync/archive in this same branch/PR and pass latest-commit checks/final review before merge.

## Capabilities

### New Capabilities

- `benchmark-launch-preparation`: trustworthy selected component execution and repository completion, with preserved conditional full-campaign contracts and explicitly separate eligibility.

### Modified Capabilities

None. The main-spec inventory remains empty.

## Impact

Selected runtime-input helpers, guardian preprocessing/runtime expectations and sidecar dispatch, a component executor/cold reader/CLI, affected GStreamer packaging/host source closure, scoped integration tests and operating guidance. Native policy math, source cadence, dataset/model bytes, eight-worker transport, accounting formats and full campaign entrypoints retain their contracts. No runtime dependency is proposed.

## Review and historical scope

One change/branch/PR remains fix-benchmark-preparations-spec / codex/fix-benchmark-preparations-spec / https://github.com/lordcoudy/VAST/pull/2. The user's carte-blanche authorizes this amendment and subsequent separately recorded exact-commit delegated review/application; it does not establish GitHub reviewer approval or runtime acceptance. The reviewed three-seam proposal and exhaustive historical allocation are independently checked by fdaa3ab3. Decision22 at9c and all its original clauses/states are retained in artifacts/benchmark_recovery_20260930/decision22-planning-originals-v1 and the verification-plan register.

Scope is an operable, repeatable selected-system benchmark with scientifically bounded descriptive results. It does not establish a four-backend ranking, task accuracy, quality noninferiority or population inference from one pair/resource. Full campaign methodology and grants are preserved for a separate later campaign decision; no incomplete full campaign is archived as completed.
'''

design = '''## Context

See proposal.md for Decision23 scope. Five isolated decoder attempts produced zero source/AUs/frames. The latest original05 now retains the actual failing GStreamer SO: maps device2112/inode130187 versus held/named device77/inode130187, regular one-link1843168-byte input. The device-number comparison fails; its underlying cause and byte equality are not proven. Auditb0190bd4 verified original exit1/nonforce removal/identifier and process absence and released the held v5/core22 phase. Decoder research is therefore separate from unchanged-intake benchmark operability.

The independent reviewfdaa3ab3 supports three authority seams and verifies all16 historical requirements/79 then-current scenarios/72 task IDs. Decision22 adds three retained first-error/broker scenarios. The original31 checked tasks retain their original historical scope; every other original task remains unexecuted at its full scope. Decision22's55 research and11 broker focused tests passed, but complete latest-source CI/hardware acceptance has not yet passed. Old065 crash cause and old hosted setup errno remain unknown.

## Goals / Non-Goals

Goals: give the user one reproducible bounded command, four actual native GStreamer arms, complete operational and measurement evidence, cold descriptive results, explicit failure behavior and final source/repository verification.

Non-goals: execute the legacy32/1120/5600 campaign as part of this release, renew untouched sibling images, manufacture aggregate authority, replace scheduling/evaluation/accounting machinery, change intake or claim decoder causation without evidence, or relabel opaque common-worker inference as backend-native/task-accuracy/true NVDEC busy proof.

## Decisions

### 23. Separate selected release from preserved campaign

The release contains two exactly scoped two-operation contexts, forced CPU and forced GPU. Each has one owned guardian, eight real authenticated workers with symmetric readiness/warmup, and original baseline/shared native graphs. Preserve six streams/four branches, paired schedule/order/seed and original30/180/10 durations,100ms deadline, source resets, drops/censoring and ingress-derived measurement cohort. Use a fresh bounded local namespace, physical required-volume capacity admission and the existing20-GiB operational reserve; retain raw data durably without fabricating Seafile/Q4 capacity. A documented command must recreate this scope in a new namespace and reject occupied outputs, stale identities and unsupported resources.

Full campaign counts, policies/codecs/backends,32-cell qualification,1120 Q4 runs/280 sizing pairs, remote max(500GiB,ceil(projected_remote_bytes*1.25)+5GiB) guarantee and durable offload/finalization stay conditional full-entrypoint contracts. Historical checked tasks are not current-image evidence; original mixed tasks remain incomplete in the register. Active release tasks have new18.x IDs so component completion cannot check a full-scope task by accident. Archive completes only the reviewed active release, while preserving the register and false full eligibility.

Alternative rejected: wait for all four images/fresh480 parity/32 qualification/Q4/5600 arms before the first meaningful paired result. That couples independent prerequisites and has repeatedly hidden runtime failure behind preparation. An ad hoc identity smoke or a fabricated partial qualification object would not retain the actual physical/scientific checks.

### 24. Selected host materialization uses explicit physical inputs

Introduce the distinct authority kind vast_gstreamer_component_authority_v1, scoped only to gstreamer_custom/h264/cpu_only or gpu_only and its original baseline/shared pair. Bind current selected image and embedded/import source closure; actual execution configuration, binding index/eight binding documents/two worker probes, worker/model/preprocessing/output/toolchain closures, selected calibration and dataset plans; source assets, resource/device identity, pinned engine/socket, output reservations and two-operation context. Identity expiration/change rejects launch.

Keep the complete historical capability JSON verbatim with its original provenance. The existing assessor and coordinator use it as a declaration; the external runtime must independently compare its eight actual selected worker capabilities exactly to those selected rows. Historical implementation/emitter document hashes are not current image hashes. Reject selected-row drift; do not silently update/rebind the historical declaration or grant siblings.

Factor explicit-pin portions of _system_file_descriptors and pure construction from _runtime_contract_for_cell; keep full wrappers over their real QualificationInputs and existing all-system preflight. A selected inventory independently loads current selected facts; it is not a fake QualificationInputs. Avoid the unconditional GVA authority dependency in _local_omz_model_pins by using the actual canonical selected proxy/OpenVINO binding manifest. Reuse NativePublicationRequestV3/lower runtime and original external manifest constructors. No partial assessor/scheduler/new parity-reuse authority.

Original common parity remains historical with its exact aggregate patch association. Obtain selected numeric/model facts by existing read-only physical/raw-numeric validators plus exact current worker/model/preprocessing/output/toolchain closure equality. If they do not match, collect the missing selected evidence; never renew the old aggregate receipt. Calibration must have at least30 actual samples per selected branch/resource cell and current physical resource/model/source binding. Forced policy does not waive calibration. Eight historical compatibility rows or old sample counts alone are not a live grant.

### 25. Explicit preprocessing and guardian dispatch

Component preprocessing has distinct receipt and authority kinds, carrying current component source descriptors and operational_context. Return the existing loader shape {preprocessing_contract,receipt,authority}; do not counterfeit qualification/accepted-policy image-patch/transaction fields. Factor the shared actual execution_config/binding_set/workers/runtime_probes projection in runtime expectations; preserve strict legacy outer five-field refresh checks. Exact-eight worker closure and actual production worker startup remain shared.

Update only the explicit authority validator, CLI receipt-loader dispatch and constructor manifest-field dispatch to an exact three-kind map. Unknown kinds, missing/foreign worker/source/preprocessing facts and wrong contexts fail. Component service requires active operational capture and rejects any request outside its exact two planned original GStreamer/H.264 forced-resource operations before backend inference. Reuse the original context/recorder binding checks for this gate; the historical four-system declaration grants no sibling or arbitrary-arm permission. Full qualification/accepted-policy/promotion/Q4/publisher loaders reject the new kind and retain original complete grants. Boolean accepted=false alone is not sufficient kind separation.

### 26. Real executor and component cold result

Reuse existing two-original capture planning, native GStreamer runtime, sealed-memfd front and hardware/process/container custody. Owned startup/warmup/execution/drain/cleanup deadlines, receipt-last outcomes, zero unrecognized retries and explicit authenticated stop are required. Duplicate owners/occupied namespaces, source drift, worker death and record persistence failures are terminal. Preserve available original exit/signal/OOM/cgroup/kernel/log facts before cleanup; unknown remains unknown. Historical g137 is not retroactively a clean or OOM stop.

The host collector stops before physical cold validation. Reuse prepare_checkpoint_publication_acceptance's source/cohort/full-resource validation and nonauthorizing operational reconciliation internals, not the aggregate bootstrap/qualification finalizer grant. Join original CLI and CID/image/source/transfer evidence, every warmup/measurement/drain native request and guardian begin/terminal occurrence, all eight worker totals and exact measurement projection. No caller phase classification, guessed identities, counter offsets, aggregate-only match or fabricated37-entry domain.

Successful component evidence binds four original native terminals and two owned guardian closures, positive real decoded/source processing, physically verified current model/resource evidence, complete drop/stage/branch accounting and strict cold measured checks. A zero-frame or identity-only smoke cannot complete the release. Where physical stock validation rejects a missing/invalid measured quantity, retain failure and diagnose; do not loosen it. A valid negative effect/deadline miss is acceptable; a ratio or quality quantity without a valid denominator is null with an explicit reason, never invented. Component result has its distinct kind and component-only counts; qualification/Q4/publication/full eligibility and campaign execution counts remain false/zero.

### 27. Scientific interpretation follows the executed evidence

Report latency distributions, original absolute deadline misses, drops/coverage and descriptive paired topology differences separately for CPU/GPU. One pair/resource does not justify confidence intervals, quality noninferiority or statistical generality. Use the existing deterministic paired cohort/comparison rules wherever estimable; preserve original unestimable/failing outcomes. Opaque common OpenVINO/TensorRT workers mean topology_load_proxy_only. C_obs is partial observed attributed stage elapsed, not compute/energy/NVDEC busy. HEFT/deadline-aware HEFT remain placement aliases/expected null labels in future policy claims; frozen coordinates/formulas remain untouched.

Unchanged frozen intake can run before four32-AU mechanism research is complete. Any changed source cadence/media/pipeline/deadline/metric or causal decoder correction needs a new exact scientific review with complete appropriate original pixel/caps/order/PTS mechanism evidence; failed setup attempts grant none. Decision23 authorizes no new mapper predicate waiver or automatic attempt06.

### 28. Preserve repairs and finish current checks

Keep prior payload snapshot/hash/bounds and rejection/accounting/8-KiB first-failure behavior; zero service retries with supported same-checkpoint exit75 recovery/permanent78; native queue/drop/resource/projection/history/operational limits; exact checkout contracts; portable peer and durable broker failure terminal fixes. Original detailed decisions1-22 remain byte-exact in the historical snapshot and source commits.

Before component source edits, map every affected host/embedded/native/worker image closure. Rebuild/repackage only actually affected selected GStreamer, preserve native-three/worker-two only after exact unchanged-closure proof, and leave affected sibling publication receipts historical/ineligible. Renew the new selected host/source authority. The broker repair is outside165/78/all9 allowlists and needs broker/CI closure renewal only. No evidence is retained as current merely because a Git commit matches.

Require appropriate focused regressions, actual six CPU builds/three required native successes/full hosted discovery with source-before/after/report, final exact-byte ext4 suite and explicit physical hardware results. Diagnose actual hosted errors before reviewed platform provisioning;600000/615000-ms production ABI and strict namespace/WSL checks remain. CI format success is not conformance. Conformance maps every active scenario to current implementation/test/evidence and each preserved campaign clause to its unexecuted register; resolve critical gaps. Then sync/archive in this same PR, preserve main requirements/.openspec.yaml, commit/push, pass final-commit checks and exact final delegated review before merge.

## Risks / Trade-offs

The unchanged intake may expose severe deadline saturation -> retain actual negative results and unestimable metrics; review any later scientific intake change separately. Historical row compatibility may drift -> reject and collect current selected facts; no declaration rebind. New kind dispatch may accidentally inherit full grant -> exact kind and full-entrypoint negative regressions. Selected source edits may change worker/model closure -> dependency-map and renew only affected numeric/image evidence. Hosted CI may reveal real platform defects -> retain original errors and fix from facts, without blanket skips or shortened timeouts. Four arms have limited generality -> component claims/counts only.

## Migration Plan

Review exact Decision23 documents/legacy register in this same Draft PR under standing authorization before dependent implementation. Apply three seams incrementally with focused source/current-kind compatibility tests and actual dependency auditing. Materialize current selected inputs, execute the two owned original pairs, cold validate, retain raw results and operating guidance, complete final checks/conformance/own-thought review, then supported sync/archive/commit/push/final review. Rollback rejects the new kind and returns to the unchanged full entrypoints; historical failed/result bytes remain retained. No existing worker/check is restarted for an artifact or phase transition.
'''

def paragraph(section, text):
    head, rest = section.split('\n', 1)
    index = rest.index('#### Scenario:')
    return head + '\n' + text.strip() + '\n\n' + rest[index:]

requirements[0] = '''## Purpose

Make VAST operable through a reproducible real GStreamer component benchmark with complete physical/operational validation and scientifically truthful descriptive results, while preserving explicitly separate conditional full-campaign contracts.

## Scope

Decision23 release consists of four genuine GStreamer/H.264 arms: one CPU and one GPU baseline/shared pair. Requirements concerning full qualification/Q4, remote capacity and the full matrix retain their existing conditional full-entrypoint behavior; executing those campaigns is future work, not component release acceptance. The original72 tasks/82 scenarios and exact Decision22 clauses are retained in verification-plan.md and the byte-exact historical snapshot. Deferral SHALL NOT be reported as execution. Component qualification/Q4/publication/full eligibility SHALL remain false.

## ADDED Requirements

'''
requirements[1] = paragraph(requirements[1], '''Recovery SHALL deliver a reproducible selected component command and four genuine GStreamer/H.264 native arms through two separately owned baseline/shared contexts for CPU and GPU. It SHALL preserve six streams/four branches, seed20260323,100ms deadline, paired schedules/order,30-second warmup/180-second measurement/10-second drain, original model/intake/source/graph semantics, complete operational identities and strict measured physical checks. Accepted component results SHALL retain raw evidence and current source/model/resource/owner bindings, descriptive comparisons and explicit limits. Any changed identity SHALL invalidate affected readiness. Component completion SHALL NOT establish full campaign readiness, counts, authority or publication eligibility; legacy full gates SHALL remain strict and explicitly unexecuted. Standing authorization permits autonomous work but SHALL NOT substitute for actual checks/review.''')
requirements[1] = requirements[1].replace('every required preparation gate is accepted and current', 'every required component release gate is accepted and current').replace('preparation_ready=true and the actual launch/completion state; before authorized full-run launch it SHALL report full_run_started=false and publication_ready=false rather than claim completion from diagnostics or service materialization.', 'component_release_complete=true with four actual component arms/two pairs and current evidence, while full_run_started=false and qualification/Q4/publication/full eligibility remain false; unexecuted campaign counts SHALL remain zero.')
requirements[8] = requirements[8].replace('Fresh qualification SHALL bind', 'Each component pair and fresh full qualification SHALL bind', 1)
requirements[8] = requirements[8].replace('Measurement32 SHALL remain an independently validated exact subset/projection, preserving all existing native/policy/model/resource checks.', 'For full qualification, Measurement32 SHALL remain an independently validated exact subset/projection. Each component pair SHALL instead retain its exact two-arm ingress-derived measurement subset/projection, preserving all applicable native/policy/model/resource checks.', 1)
requirements[8] = requirements[8].replace("The qualification manifest SHALL contain exactly 37", "A component manifest SHALL contain exactly its two original producing operations and use the existing two-arm accounting mode. The full qualification manifest SHALL contain exactly 37", 1)
requirements[8] += '''#### Scenario: Component pair reconciles all phases
- **WHEN** both genuine component topology arms and their owned guardian complete
- **THEN** their two physical original operation domains SHALL reconcile exactly to all warmup/measurement/drain request/terminal occurrences and eight worker totals under the unchanged bounds, separately from the measurement subset; zero-frame, aggregate-only or fabricated37-entry evidence SHALL fail.

'''
requirements[9] = requirements[9].replace('Preparation SHALL require', 'Full-campaign preparation SHALL require', 1)
requirements[9] = requirements[9].replace('### Requirement: Qualification and Q4 are complete before launch readiness', '### Requirement: Qualification and Q4 are complete before full launch readiness', 1)
requirements[10] = requirements[10].replace('Capacity admission SHALL require', 'Remote full-campaign capacity admission SHALL require', 1).replace('launch readiness SHALL remain blocked', 'full-campaign launch readiness SHALL remain blocked')
requirements[11] = requirements[11].replace('The validated package and subsequent run SHALL preserve', 'The conditional full-campaign validated package and subsequent run SHALL preserve', 1)
requirements[12] = requirements[12].replace('One current runbook SHALL distinguish diagnostic, preparation, full execution and finalization stages', 'One current runbook SHALL distinguish selected component release, diagnostic research, future full preparation/execution and finalization stages', 1)
requirements[13] = paragraph(requirements[13], '''Recovery SHALL execute one forced-CPU baseline/shared pair and one separately owned forced-GPU pair through the existing native runtime with real pinned workers/models, six streams/four branches, paired schedules, original warmup/measurement/drop/censoring/resource rules and strict process/cold evidence. Each pair SHALL have explicit two-operation accounting and exact all-phase request equality, symmetric warm worker readiness and original graph/source resets. Selected current physical source/image/worker/model/preprocessing/output/toolchain/calibration/resource facts SHALL grant only a distinct nonpublication component authority. Calibration SHALL retain at least30 actual samples per selected branch/resource cell. A complete historical four-system declaration MAY remain verbatim data only when actual selected eight-worker row equality is independently verified; it SHALL NOT renew sibling/full authority. Missing or stale selected facts SHALL reject launch or require the missing selected evidence, never a manufactured full input/aggregate grant or old receipt rebind. Full qualification/accepted-policy/Q4/publisher entrypoints SHALL reject component authority and retain complete contracts. Static-hybrid and all-system campaign execution remain future scope. Unchanged-intake component pairs SHALL NOT wait for unfinished decoder mechanism research.''')
requirements[13] += '''#### Scenario: Selected component authority materializes
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

'''
requirements[15] += '''#### Scenario: Unchanged intake runs before mechanism research completes
- **WHEN** selected component inputs retain the exact frozen intake and no causal decoder correction is claimed
- **THEN** incomplete four32-AU mechanism research SHALL NOT block genuine component execution; failed original research SHALL remain separate, and any changed intake/pipeline/cadence/deadline/metric or causal correction SHALL require its reviewed scientific evidence before adoption.

'''
requirements[16] = '''### Requirement: Component release closes durable results and repository evidence
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
'''
spec = ''.join(requirements)
assert len(re.findall(r'^### Requirement:', spec, re.M)) == 16
assert len(re.findall(r'^#### Scenario:', spec, re.M)) == 89

checked_lines = []
checked_group = None
for state, number, text in tasks:
    if state != 'x':
        continue
    group = number.split('.')[0]
    if group != checked_group:
        checked_lines.append('\n## ' + group + '. Inherited checked tasks - original scope\n')
        checked_group = group
    checked_lines.append('- [x] ' + number + ' ' + text)
checked = '\n'.join(checked_lines)
active = [
('18.1', 'Record exact Decision23 delegated planning review and PR authorization before dependent source changes; verify the committed five artifacts/register and original05 hold-release audit.'),
('18.2', 'Map selected component imports/build/worker/model dependencies before edits; verify actual affected closure inventory and preserve unrelated source/evidence.'),
('18.3', 'Implement selected explicit physical host inventory/materialization and pure existing helper factoring; verify real selected bindings, >=30 calibration samples/cell, historical selected-row equality, stale/foreign rejection and unchanged full wrappers without fake QualificationInputs.'),
('18.4', 'Implement distinct component preprocessing/authority receipt and exact three-kind guardian/sidecar/runtime-expectations dispatch; verify all8 workers/current pins/active two-operation context, before-inference unplanned arm/system/policy rejection, both old kind paths, unknown/foreign negatives and full-entrypoint rejection.'),
('18.5', 'Implement real component executor and cold result over original runtime/custody/physical validators and complete operational reconciliation; verify original CLI/CID/hardware collector and measurement/domain checks, no aggregate grant, bounded failure/cleanup and false full eligibility.'),
('18.6', 'Renew only affected selected host/GStreamer packaging and actual image/import/embedded identities; verify packaged component regressions and unchanged native3/worker2 closures or renew affected evidence. Physically verify selected original common model/raw-numeric/calibration evidence or obtain missing selected checks without rebinding aggregate acceptance.'),
('18.7', 'Preflight fresh local bounded namespaces, actual volume capacity/20GiB reserves, models/resources/owner/socket and current identities; verify exact six-stream/four-branch paired plan and reject occupied/stale/unsupported inputs.'),
('18.8', 'Execute the original forced-CPU baseline/shared pair under one owned guardian; verify both original native terminals, positive source/decoded processing, real model/resource evidence, authenticated stop and strict all-phase/cold paired acceptance; preserve every failure without replacement or automatic retry.'),
('18.9', 'Execute the separately owned forced-GPU pair with the same frozen settings; verify original terminals, current GPU/model facts, full operational/measurement custody and cold paired acceptance without counting either pair as qualification/Q4/full.'),
('18.10', 'Cold recompute four retained raw arms/two descriptive pairs and publish tables/plots plus actual repeatable CLI; verify ingress/order/cohort equality, real drops/deadlines, negative/unestimable outcomes, proxy/sample-size/C_obs/alias limitations and no unsupported inference.'),
('18.11', 'Complete actual final six CPU builds/three required native successes/full hosted discovery with source-before/after/report and final exact-byte ext4 suite; verify all original results, skip identities and physical hardware evidence. Resolve real broker/platform/worker errors from facts without blanket skips or shortened600/615 bounds.'),
('18.12', 'Complete final requirement/scenario conformance and updated runbook/durable plan/own-thought review; verify each active requirement against actual current tests/results and every original unchecked campaign ID/82 scenarios against its explicit unexecuted historical register.'),
('18.13', 'After all active release tasks/checks pass, perform supported sync/archive in this same branch/PR; verify unaffected main specs, .openspec.yaml/legacy register preservation, actual archive path and committed/pushed archive; require latest archived-commit checks.'),
('18.14', 'Complete exact final delegated review and resolve warnings on the final checked/archive commit before removing Draft/authorized merge; verify no incomplete full campaign is asserted as executed or achieved.'),
]
task_doc = '''## 0. Decision23 active scope and historical evidence

The reviewed selected release has14 active18.x tasks below. The31 inherited checked tasks remain byte-exact historical completion statements at their original scope, not current-source/image/whole-campaign acceptance. All41 originally unchecked tasks remain incomplete at their original scope in verification-plan.md and the exact Decision22 snapshot; no mixed task is completed by its selected slice. Static/all-system/32-cell/Q4/remote/5600 execution is future campaign scope. There is no new research attempt06 or changed intake requirement for unchanged-intake component execution.

''' + checked + '\n\n## 18. Operable selected component release\n\n' + '\n'.join('- [ ] ' + number + ' ' + text for number, text in active) + '\n'

register = '''# Decision23 verification and exact historical scope register

Planning source is Decision22 commit9c514a60d644c8c3ecd637eb83185a59aa2a5e01. Its five documents are retained byte-exact at artifacts/benchmark_recovery_20260930/decision22-planning-originals-v1; original72 tasks/31checked/41unchecked and16requirements/82scenarios are preserved. Decision23 changes active release scope under user standing authorization; it does not mark any original unchecked task executed. Prior selected allocationfdaa3ab3 covered79scenarios atc956; the three current22 additions (outer primary capture, durable setup failure, quiescent missing journal) remain release obligations.

## Active release verification

- Selected input/kind boundary: genuine physical files and current selected workers/probes/models/image/calibration, exact eight selected rows, source/owner/socket/device/output bindings; stale/foreign/missing facts and unknown/full-kind escalation negatives; both original full kinds unchanged.
- Actual runtime: four original successful native CLI/container terminals, two owned guardian authenticated stops/lifecycles, positive actual source/decoded processing, real model/resource evidence, original6/4/seed100ms/30/180/10/source settings; no zero-frame smoke acceptance.
- Operational/measurement: full warmup/measurement/drain request occurrence equality and eight worker totals, strict physically bound native domain and ingress-derived measurement projection; drops/concurrent order/repeated identity/extra/missing/persistence negatives within original caps.
- Result: original raw hashes, strict source/cohort/model/resource/cold checks, descriptive CPU/GPU topology results, real deadline/drop/coverage, estimable paired quantities or explicit null reasons, no CI/noninferiority/accuracy/true NVDEC/compute claim.
- Final gates: appropriate focused/package regressions, actual final native builds/required3/full hosted discovery/source-after/report, exact-byte ext4/skip audit, physical hardware facts, every active scenario conformance, operating command/plan/own-review, supported pushed archive and latest checks/final review.

Actual conformance must identify exact implementation and current test/original evidence for each active scenario, unresolved deviations and manual limits. Format checks or historic passed tasks do not prove behavior. Preserved future interface clauses are checked for strict rejection/count/gate compatibility; their physical campaign execution stays unexecuted and cannot be cited as release results.

## Exact original task register

States below are literal Decision22 states. They are retained history; original unchecked tasks never become checked by migration. The new18.x tasks implement only the reviewed component/operability portions of any mixed original requirement. Full campaigns keep their original counts/grants/capacity/acceptance requirements.

'''
register += '\n'.join('- Original `' + number + '`; state=' + ('checked-historical' if state == 'x' else 'unchecked-unexecuted-at-original-scope') + '; ' + text for state, number, text in tasks)
register += '\n\n## Exact original requirement/scenario register\n\n'
for number, section in enumerate(requirements[1:], 1):
    original_section = re.split(r'(?=^### Requirement: )', old[PATHS[3]], flags=re.M)[number]
    title = original_section.splitlines()[0].removeprefix('### Requirement: ')
    names = re.findall(r'^#### Scenario: (.+)$', original_section, re.M)
    register += '- Original R' + str(number) + ': ' + title + '; exact clauses in retained spec.md.\n'
    for index, name in enumerate(names, 1):
        register += '  - R' + str(number) + '/S' + str(index) + ': ' + name + '.\n'
register += '\nThe original all-system qualification/Q4/cloud/full/static execution clauses remain future at their original scope. Existing full entrypoints must keep their strict complete-grant behavior and reject component receipts. Preserved repair/trust/scientific/ownership clauses remain active behavior for their applicable selected path; exact implementation evidence must be renewed where dependencies changed. There is no statement that old full-scope tasks or original physical scenarios were executed by this release.\n\n## Original planning physical pins\n\n' + json.dumps(pins, ensure_ascii=True, indent=2) + '\n'

snapshot = RECOVERY / 'decision22-planning-originals-v1'
assert not snapshot.exists()
snapshot.mkdir()
snapshot_names = dict(zip(PATHS, ['proposal.md','design.md','tasks.md','spec.md','verification-plan.md']))
for name, target in snapshot_names.items():
    (snapshot / target).write_bytes(old[name].encode('utf-8'))
new = {'proposal.md': proposal, 'design.md': design, 'tasks.md': task_doc,
       PATHS[3]: spec, 'verification-plan.md': register}
for name in PATHS:
    (CHANGE / name).write_bytes(new[name].encode('utf-8'))
print(json.dumps({'decision':23,'original_tasks':72,'historical_checked':31,
    'original_unchecked_preserved':41,'active_release_tasks':14,
    'requirements':16,'scenarios':89,'snapshot':str(snapshot),
    'planning':[{**{'path':n},'size_bytes':(CHANGE/n).stat().st_size,
        'sha256':hashlib.sha256((CHANGE/n).read_bytes()).hexdigest()} for n in PATHS]}, indent=2))
