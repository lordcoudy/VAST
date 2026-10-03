"""Refine existing reviewed planning; never edit executable implementation."""
from pathlib import Path
import hashlib

root = Path.cwd()
change = root / 'openspec/changes/fix-benchmark-preparations-spec'
expected = {
    'proposal.md': 'ee2f54dabb74a5cf3e17b875dc82c4c2c6084b5fed9f18922079bc861846456a',
    'design.md': '28363b051ca6eb8b546dd6eb89863c29510943a4e618e0f2aa2916ee6988b5fe',
    'tasks.md': '8b1ee3ac57501c56751e8e5c958d7ba57e6780bcd4742294acefbe2c5c4c0c5f',
    'specs/benchmark-launch-preparation/spec.md': 'f05a8b6c799098b0c9331fa068668c7cc735c286fdbb9ed619974aaf4d5eec38',
}
texts = {}
for name, digest in expected.items():
    raw = (change / name).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == digest, name
    texts[name] = raw.decode('utf8').replace('\r\n', '\n')

checkpoint = '''## Current recovery checkpoint - 2026-09-30 04:24 UTC

Source/remote70ef8d0a66d5d42f9a539fb2b414bf61aa1fdc9d freezes artifact-v2 and the original external dispatch. Its single actual attempt02 failed with original return1 after12.433s. Actual packaged GI3.50/Gst1.28.2 initialization with[] completed; the first default front_gate pipeline then failed before source launch with `pin is not a bounded single-link regular file`. The original failing Pin path/stat was not retained. No access unit, decoder observation or completed research run exists. Positive exact-owned CIDe8eb32bc was stopped/Pid0/Exit1/OOMfalse, actually removed nonforce, and both CID/name and original host identities/groups are absent. Postterminal receipt1b2bbf04 and independent failed audit2e6aee9b close this failed scope; original v1/v2 evidence stays immutable. All held b244 planning/code custody is explicitly released. This planning amendment authorizes only diagnostic precision in artifact-v3 and one reviewed fresh attempt03 under the same experiment, custody predicates and caps; it does not justify a particular Pin cause, predicate waiver or scientific change.

Hosted run36656805742 retains six successful CPU builds but only a partial suite; source-before/after completion and full CI remain unverified. A separate bounded two-test clean-checkout diagnostic reproduced missing damage XML; peer identity passed locally on WSL, leaving hosted peer/production causes unknown. The original eight assets match both manifest digests, total15,514,597B/largest5,774,062B. Decision19 proposes exact bounded ephemeral CI acquisition and immediate per-test/stack/host facts without skipping tests or changing real broker600000/615000-ms limits. No dependent implementation occurs before exact planning review/PR record. Tasks remain31/72; no new checkbox, scientific adoption, model pair, qualification/Q4/full result, final CI/conformance, archive or merge is complete.

Next: review/freeze this coherent amendment and closed failed/CI evidence in the same PR. Implement minimal path/stat/stage/traceback diagnostics and focused negatives, freeze exact artifact-v3 before one fresh attempt03, and preserve the failure if the strict predicate still rejects. Implement exact model acquisition plus immediate CI diagnostics, inspect actual hosted exceptions, then review a concrete platform remedy if necessary. Reassess the recovery approach against real output before any broad renewal. The objective remains active.

'''

proposal = texts['proposal.md']
marker = '## Capabilities\n'
assert proposal.count(marker) == 1
proposal = proposal.replace(marker, '''## Narrow setup and CI diagnosis amendment - 2026-09-30

Actual attempt02 completed GI initialization but failed the first pipeline's file pinning before source admission. Preserve its original unknown failing path/stat and verified exact-owned cleanup. New artifact-v3 records the original Pin path, stat/type/link/size/bound facts and inner stage/traceback without weakening its checks; one explicitly reviewed fresh attempt03 retains the original four32-AU experiment and caps. Diagnose the demonstrated rejection before reviewing a package-policy remedy.

Repair the demonstrated clean-checkout model prerequisite by acquiring only the eight unchanged manifest objects with exact size/SHA-256/SHA-384 and bounded exclusive publication. Extend the existing CPU test result with immediate per-test start/terminal/elapsed/tracebacks,60-second original stacks and16-KiB whitelisted host facts. Preserve full discovery, three required native successes,90-minute job and real600000/615000-ms broker constraints. Hosted peer/production causes remain unknown until original exceptions are retained. This amendment adopts no pipeline, corpus, algorithm, deadline, metric or shortened matrix.

''' + marker)
proposal = proposal.replace('CPU CI is configured and its original hosted runs are in progress; no completed build/test or GPU-CI success is inferred.', 'CPU CI is configured; original runs36656805742,36658359728 and36661462648 were cancelled by their job budgets, while later original runs remain active. Six CPU targets built in the first run, but complete suite/latest-source or GPU-CI success is unverified.')
texts['proposal.md'] = proposal

design = texts['design.md']
marker = '## Risks / Trade-offs\n'
assert design.count(marker) == 1
design = design.replace(marker, '''### 19. Diagnose strict setup rejection and make CPU CI failures observable

Artifact-v2 at70ef and its single physical attempt02 are closed failed originals. GI initialization completed, but first-run terminal reports the generic bounded-single-link Pin rejection before source launch; no original path/stat identifies its cause. Independent failed audit2e6aee9b verifies exact stoppedExit1/OOMfalse, actual nonforce removal and post-removal CID/name absence. Preserve all original bytes and unknowns. New artifact-v3 adds only a bounded structured Pin rejection containing requested/resolved path, original held-fd fstat and named-path lstat when available (device/inode/mode/type/link count/size/time), maximum and each predicate result. An unavailable stat stays explicitly unavailable. Capture original inner exception type/stack and named run stage before cleanup; cleanup failures remain separate from the first error. Error paths/text must fit16KiB and metadata/run limits; exceeding a limit remains failure, without a late success receipt. Use a small structured exception/error record in existing code, not another custody framework. Keep regular-file/single-link/size/identity/hash predicates unchanged. Focused actual-file/process cases verify hard links, oversize/type/substitution and original first-error retention. Exact amendment review and exact implementation freeze/review precede one new attempt03 of the same fixed four32-AU experiment. No decoder or scientific conclusion follows from preflight, fixture or zero-AU success. A demonstrated real package-policy incompatibility requires a further reviewed source-grounded remedy before changing a predicate; no automatic retry is permitted.

The first hosted CI artifact contains six successful CPU builds and a truthful interrupted suite prefix, without final exception reports/source-after manifest. A bounded two-ID clean-checkout diagnostic reproduces missing `damage:model_path`; the mocked-Docker peer test passes on actual WSL, not evidence of the hosted failure's cause. Original CI logs/artifacts and failed diagnostic-v1 remain immutable. Extend existing RecordedResult to flush each test's start and real terminal, monotonic elapsed and original failure/error/subtest traceback immediately. A started interrupted test has no terminal. Keep suite-end report and full discovery; periodically dump original faulthandler stacks every60s without terminating/retrying a test. Save at most16KiB of whitelisted Python/version/realpath/executable stat, UID/GID, kernel, capability/NoNewPrivs/Seccomp, API availability and selected namespace sysctl facts. Do not dump environment/secrets or probe namespaces/Docker as part of host observation. Preserve90-minute job, all test selection, three required native successes and real broker600000/615000-ms constraints; obtain actual hosted tracebacks before reviewing a platform fixture or runner change. Never replace strict WSL/namespace production behavior with a blanket skip.

Provision only the frozen manifest's eight original XML/BIN objects before the unchanged repository model test. The read-only inventory47bd7543 binds manifest48de16da and exact per-file size/SHA-256/SHA-384, total15,514,597B/largest5,774,062B. Pin that manifest/inventory interpretation; each exact size is both transfer ceiling and required EOF size, with both declared digests mandatory. Use the declared HTTPS origin, reject unexpected redirects/origins/status, stream64KiB chunks with at most128KiB content buffers, and enforce24MiB of owned namespace storage (final objects plus at most one largest staging object and1MiB metadata). Each object has120s including up to10s teardown; overall600s includes all dispatch/verification/publication/teardown. Socket waits are at most15s/remaining deadline; existing original-process/group containment provides the outer bound for blocked DNS/calls. Never reset the overall clock. Resolve only the eight declared destinations contained under models; reject symlink/alias components, unexpected paths or replacement races. Verify an existing regular object completely before reuse; corrupt/partial objects fail without overwrite/deletion/automatic retry. Absent objects use exclusive owned staging and nonreplacing verified publication. Retain failed owned partial/error facts and actual status/URL/whitelisted response/received-byte/prefix-digest/timeout facts within metadata caps; no secret headers. No manifest rewrite, moving downloader, corpus, inference or hardware grant follows. Preserve original dispatch/stdout/stderr/terminal including an outer timeout if no clean child terminal exists.

CI-only dependency membership must be proven against actual runtime/host allowlists before retaining source/image claims. Required model/network negatives and interrupted-test diagnostic tests gate this slice; a genuine empty-models hosted run must obtain exactly the declared files, run unchanged full discovery/native successes and retain source-before/after/complete report. This setup slice cannot by itself complete task16.1 or prove GPU, publication, scientific or full-benchmark acceptance. Author self-review must challenge the recovery's accumulating proof machinery and return to the smallest real-output experiment; preserve necessary rejection while avoiding new unvalidated abstraction layers.

''' + marker)
texts['design.md'] = design

tasks = texts['tasks.md']
tasks = tasks.replace('## Current recovery checkpoint - 2026-09-30 03:34 UTC', '## Previous recovery checkpoint - 2026-09-30 03:34 UTC', 1)
first_heading = tasks.find('\n\n')
tasks = tasks[:first_heading+2] + checkpoint + tasks[first_heading+2:]
old = '- [ ] 13.6 Preserve failed attempt01/v1'
start = tasks.index(old)
end = tasks.index('\n', start)
tasks = tasks[:start] + '- [ ] 13.6 Preserve immutable failed attempt01/v1 and attempt02/v2 with independently verified owned cleanup. Retain v2 CID/cleanup and explicit[] initialization corrections. After exact amendment review, add minimal artifact-v3 original Pin requested/resolved path/fstat/lstat/predicate/limit and inner named stage/traceback diagnostics without weakening any custody predicate or cap. Pass focused actual-file/process negatives and independent exact-code freeze/review before one fresh attempt03 of the same four fixed original-media/packaged-source/decoder32-AU prefixes/central9-24. A diagnosed predicate incompatibility requires a further coherent reviewed remedy. Require complete output correctness/order, original binary/plugin/library/process/container receipts and independent raw validation before this task completes. No automatic retry, cohort search, scientific adoption or model/parity/pair/qualification count is granted by setup repair.' + tasks[end:]
start = tasks.index('- [ ] 16.1 ')
end = tasks.index('\n', start)
tasks = tasks[:start] + '- [ ] 16.1 Configure and execute actual required CI structure/format/build/test/conformance gates. Apply decision19 exact eight-model ephemeral acquisition and immediate per-test/traceback/elapsed,60s stacks and16KiB hosted facts; pass bounded acquisition/corrupt-cache/redirect/timeout/diagnostic regressions. Preserve full discovery, required three native successes,90-minute job and broker600000/615000-ms constraints. Diagnose actual hosted peer/production exceptions before a separately reviewed platform remedy; prove CI-only dependency scope. Latest-source complete hosted build/suite/source-after/report is required, with physical GPU evidence distinct and remaining hardware/conformance limitations explicit.' + tasks[end:]
texts['tasks.md'] = tasks

spec = texts['specs/benchmark-launch-preparation/spec.md']
spec = spec.replace('- **WHEN** the first physical research attempt fails during setup with no source/decoder cohort', '- **WHEN** a physical research attempt fails during setup with no source/decoder cohort')
marker = '### Requirement: Authorized full execution closes durable results and repository evidence\n'
assert spec.count(marker) == 1
spec = spec.replace(marker, '''#### Scenario: A strict research file pin fails without original path facts
- **WHEN** actual attempt02 is reviewed or a subsequent strict file pin rejects an input
- **THEN** original unknown cause and zero-AU failure SHALL be preserved; new artifact-v3 SHALL record bounded requested/resolved path, original fstat/lstat/type/link/size/predicate/limit and inner stage/traceback when available before cleanup, without weakening checks. One exact-reviewed fresh attempt03 MAY execute the same fixed experiment/caps after focused negatives and implementation freeze; any actual predicate remedy SHALL require further source-grounded review, and no automatic retry or research acceptance SHALL be inferred.

''' + marker)
marker = '### Requirement: Recovery first proves a bounded genuine native pair\n'
assert spec.count(marker) == 1
spec = spec.replace(marker, '''#### Scenario: Clean checkout lacks the frozen model assets
- **WHEN** CPU CI prepares an empty declared models destination
- **THEN** it SHALL acquire only the eight frozen XML/BIN HTTPS objects, enforcing exact per-file size and both manifest digests,64KiB chunks/128KiB buffers,24MiB namespace,120s/object and600s overall including teardown,15s-or-remaining socket waits and actual outer containment. Exclusive nonreplacing publication SHALL reject alias/path escape, corrupt cache, short/oversize/wrong digest/status/redirect and timeout without overwrite/deletion/automatic retry. Failed original partial/status/byte/error facts SHALL remain bounded and inspectable. The unchanged model test/full discovery and three native successes SHALL execute; acquisition SHALL NOT grant inference or hardware acceptance.

#### Scenario: Hosted test failure or interruption occurs before the suite report
- **WHEN** a discovered CPU test fails, errors, or remains active at job cancellation
- **THEN** existing result logging SHALL flush its original start/real terminal/elapsed and immediate original traceback/subtest failure; periodic60s original stacks and at most16KiB whitelisted host facts SHALL remain retained. An interrupted test SHALL have no invented terminal. Full selection,90-minute job and600000/615000-ms broker constraints SHALL remain; actual hosted exceptions SHALL precede a platform remedy, with no blanket skip or strict WSL/namespace waiver. Complete latest-source suite/source-before/after/report SHALL remain required for CI success.

''' + marker)
texts['specs/benchmark-launch-preparation/spec.md'] = spec

for name, text in texts.items():
    (change / name).write_bytes(text.encode('utf8'))
plan_path = root / 'BENCHMARK_RECOVERY_PLAN.md'
plan = plan_path.read_bytes().decode('utf8').replace('\r\n', '\n')
plan = plan.replace('## Current recovery checkpoint - 2026-09-30 03:34 UTC', '## Previous recovery checkpoint - 2026-09-30 03:34 UTC', 1)
marker = '## Previous recovery checkpoint - 2026-09-30 03:34 UTC\n'
assert plan.count(marker) == 1
plan = plan.replace(marker, checkpoint + marker, 1)
plan_path.write_bytes(plan.encode('utf8'))
verify_path = change / 'verification-plan.md'
verify = verify_path.read_bytes().decode('utf8').replace('\r\n', '\n')
verify += '\n## Decision19 setup diagnosis and CPU CI validation\n\n' + checkpoint.split('Next:')[0].split('\n\n',1)[1] + '\nCheck original Pin path/stat/predicate and first inner traceback retention for actual regular, hardlink, oversized/type/substituted inputs without waiver. Verify one reviewed fresh fixed attempt03 and original ownership cleanup; zero-AU diagnostic failure does not complete13.6. For CI, test exact eight acquisition with empty/valid/corrupt cache, path alias/escape, short/oversize/digest/status/redirect/timeout failures and exclusive publication. Verify bounded storage/buffers/deadlines, immediate test/subtest tracebacks and interrupted start without terminal, periodic stacks/host-facts secret whitelist, unchanged full discovery/native requirements and real broker constraints. Obtain actual hosted peer/production exceptions before remedy; require latest-source complete CI/source-after report. Preserve original failed evidence and separately review source/image dependency scope.\n'
verify_path.write_bytes(verify.encode('utf8'))
print('Updated six existing planning/plan documents only; no implementation or checkbox completion.')
