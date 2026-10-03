"""Finite metadata/source review; no imports or execution of reviewed project code."""
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time

CONTROL = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
HERE = CONTROL / 'artifacts/benchmark_recovery_20260930/decision29-current-conformance-independent-review-v1'
BASE = CONTROL / 'artifacts/benchmark_recovery_20260930/decision29-current-conformance-preparation-v1'
SOURCE = Path('/home/s-a-balashov/work/vast-current-source-ci-20261003-decision29-D')
D = '3c025b29b3c1d5275c2ec693410e4b83700583de'
B = 'a00aa57f7d9534f8e7920f14f70d6a75a23570ed'
EXPECTED = {
 'mapping.v1.json': (4907163, '8d8b80bbc7a50c87e519f40f37a4bd2e3c965d3c8dca02af72fd04699770e583'),
 'input-custody.v1.json': (145106, 'ae767c3fcfa51a31efecae0b3b8c56008362344832ea21d29c0258cac9111028'),
 'terminal.v1.json': (1419, 'ffa350ef8061a69a12bd019a5a5c5e41b15b74ba8a4f8000bc5d665da1ec3d52'),
}

# These are the independent semantic adjudications, written after reading the
# complete normative clauses and actual assertion/boundary excerpts. Checks
# below bind them to current source and originals; AST checks are not behavior.
NOTES = {
 'R1': [
 'Two owned native resource pairs and their cold/science proofs support selected scope; final archive/review gates remain conditional.',
 'Identity replacement and image projection drift refuse before next use; original failed authorities cannot be rebound.'],
 'R2': [
 'Compiled client regression checks snapshot bytes and sealed transport after synchronized storage reuse.',
 'Compiled regression rejects wrong digest locally before sending a payload FD.',
 'Compiled regression covers zero, oversize and real maximum payload with cleanup; allocator bounds precede snapshot.'],
 'R3': [
 'Attributable wrong content produces one failed request and bounded diagnostic without inference.',
 'Unattributable envelope/FD rejection closes connection only; unsafe bytes and secrets are not diagnostics.',
 'First error persistence lock selects once; storage/concurrency failures preserve original cause and FD cleanup.',
 'Historical failed lifecycle remains nonauthorizing; missing diagnostics are not fabricated.',
 'Artifact preflight regressions preserve original Pin facts before retirement; no whole-CI execution or decoder acceptance is claimed.'],
 'R4': [
 'Omitted API/CLI retry options launch once and produce permanent unknown failure without sleep.',
 'Transient storage/offload recovery keeps the valid checkpoint and accepted pairs; receipt/ledger precede prune.',
 'Remote size/hash mismatch is permanent and cannot authorize deletion; no physical remote run is claimed.'],
 'R5': [
 'Physical dirty bytes are separately identified; they are not equated with clean Git source authority.',
 'Reachable source/COPY manifests identify affected grants; unselected runtime grants remain historical.',
 'Deterministic matrix/order/state tests validate planning, not execution of 5600 arms.',
 'Finite historical byte-freeze proof preserves raw165/22 and nineLF contracts; current whole-source CI tables are separate.',
 'Ten canonical LF controllers and nine build closures are manual physical evidence, with no invented direct test.',
 'Portable peer unit delegates real proc open/read/fstat/close but returns explicit WSL fixture bytes; it does not attest Ubuntu as WSL.',
 'Direct non-WSL parser negative preserves production marker and FD/path predicates.'],
 'R6': [
 'Native compiled reset test covers actual guint/guint64 properties and invalid/nonzero/unreadable values.',
 'Native identifier test permits damage and rejects malformed/unknown identifiers.',
 'Native policy implementation identities join actual manifest emitter/worker rows; labels alone do not grant execution.',
 'Loaded CPU/GPU backend and decoder placement mismatches reject; fixture metadata is not a live device grant.',
 'Copied engine bytes must be project-contained and hash-bound; the stock positive and mismatch predicates remain.',
 'Postdecode prefix drop resolves branch once retaining decode, without fabricated preprocess/policy/inference.',
 'Pre-detector drop retains decode and preprocess only, no join/detector/policy execution.',
 'Unknown identity, sequence, lineage, duplicate/orphan and post-entry drop reject rather than emit accepted terminal.',
 'Absent preprocess is allowed only by verified prefix provenance; missing ordinary required stage fails cold.',
 'Independent mixed/all-prefix and shared all-or-none drop cases retain exact completed stages.',
 'Native stage intervals and attribution retain provenance and measurement bounds; partial observed elapsed is not additive work.',
 'Failed precheck blocks dependent full32; current selected Gst pair does not attest all four native prechecks.'],
 'R7': [
 'Canonical ingress mapping is independent of worker sequence gaps and warmup trace suffixes.',
 'Original decision/feedback hashes and native state remain authority; projected IDs do not replace original bytes.',
 'Adaptive state replays complete chronological predecessor history including excluded phases.',
 'Nonadaptive closure requires excluded issuance/reset proof without adaptive history or inferred filename policy.',
 'Mapping/dense ordinal/original proof and worker identity substitutions reject.',
 'Missing/reordered history, reset/state and measurement omissions reject independent replay.',
 'Streaming replay enforces file/aggregate/record/line bounds and rejects malformed/nonfinite/truncated inputs.',
 'Strict historical legacy records remain readable; mixed or unsupported projection is rejected.',
 'Isolated pure Q4 replay fixtures pass/reject source drift; physical Q4 phases remain unexecuted.',
 'Producer success and rejected cold result are distinct; original failed CPU04/05/07 are not promoted.'],
 'R8': [
 'Original operation identity and all-phase request equality remain strict; composition fixtures are not37 real executions.',
 'Equal totals cannot conceal foreign frame/worker/model/stream identity.',
 'Multiplicity is per original operation; duplicate within-operation or reused proof rejects.',
 'Membership follows validated ingress schedule, retaining measurement requests completed in drain.',
 'Missing/duplicate begin/terminal and failed response remain failed; completion interleaving is not loss.',
 'Source-derived pending/cadence/storage bounds reject before unbounded persistence and preserve first failure.',
 'Physical path/hash/epoch drift and invalid schema reject independently of resealing.',
 'Legacy aggregate32 remains readable but cannot promote without complete original accounting.',
 'Source accounting defect blocks full pilots; active promotion predicates remain strict and campaign execution future.',
 'B two-operation pairs reconcile all phases and eight workers; old pending sentence is historical, superseded only by exact B proofs.'],
 'R9': [
 'A269 remains failed/retired and counts zero toward future qualification; legacy readable does not mean promotable.',
 'Full32, Q4 phases560+560 and280 sizing still require complete current evidence; fixtures are not physical execution.',
 'Missing prerequisites reject before launch and preserve failed original without automatic second operation.'],
 'R10': [
 'Undated capacity estimates are not destination-bound operator grants; no current remote guarantee is manufactured.',
 'Frozen floor, margin and exact sizing/destination/readback are enforced; real remote sizing/admission remains future.'],
 'R11': [
 'Service materialization binds exact frozen command/root/state without start; live full preflight remains mandatory.',
 'Alternate matrix/hash/argv/path/source refuses before callbacks or installation.'],
 'R12': [
 'Current runbook/source flags and syntax-only manual evidence distinguish B measurements, D CI, failed history and future archive.',
 'Current complete CI has genuine originals; future archive-commit checks remain required and format checks are not behavior.',
 'Eight fixed model assets retain dual digests/exclusive inode/caps/deadline; actual D offline reuse still runs stock verifier.',
 'Per-test start/terminal/tracebacks are original and immediate; interruption cannot manufacture terminal or source-after.'],
 'R13': [
 'Actual B forced pairs pass strict original native/guardian/all-phase cold, while publication eligibility remains false.',
 'Forced authority cannot become static; selector requires real selected8 calibration and static execution remains future.',
 'Seven roles/source plan/front workers and complete domains join physically before native execution and cold acceptance.',
 'Current selected physical8/model/calibration grant is distinct; complete historical table remains verbatim descriptive only.',
 'Resealed source/image/model/factory substitutions cannot bypass held physical checks.',
 'Named full consumers reject component kind/coordinates/full grant; manual source review is explicit, with no all-consumer direct-negative or universal zero-FS claim.',
 'Actual two-arm active capture rejects foreign run/stream/resource/system before backend inference.'],
 'R14': [
 'Worker death fails service and retains bounded observed facts; exit137 does not establish OOM actor or cause.',
 'Original failed guardian lifecycle remains failed with actual retired owner; no retroactive clean stop.',
 'Exact CID/name/daemon ownership precedes cleanup; foreign or earlier absence cannot prove quiescence.',
 'Only immutable elected owner gains terminal journal; losing candidate cannot poison winner. Both early setup entries preserve owner/auth limit.',
 'Quiescent broker without durable response fails promptly; stdout is not durable authority and600/615 ABI remains.',
 'First validated route snapshots once before teardown, response_send differs from inference, and live/unavailable facts are not cause or terminal.',
 'Exact original CID terminal event filters retain2s/8192/1024/32 gates; no history/OOM inference from absence.',
 'Failed original measurement preserves binary/empty prefixes and nonauthorizing adjunct; persistence/timeout/cap failure stays failed.'],
 'R15': [
 'Actual severe100ms misses and drops remain visible; relative result does not claim absolute SLO or quality noninferiority.',
 'Opaque topology-load proxy and partial C_obs remain explicit; no accuracy/energy/NVDEC/formal equivalence claim.',
 'Frozen HEFT/DAHEFT aliases retain formulas and coordinates; forced pairs are not a scheduler ablation.',
 'Saturated deadline statistic and confounded elapsed costs limit interpretation; null/unestimable metrics are not fabricated.',
 'Fixed four32-AU research needs complete pixels/order/cohort/source/EOS before causal adoption; real mechanism remains unexecuted/failed.',
 'Original zero-AU setup failures keep unknown cause and immutable bounded facts; artifact tests are not whole CI or mechanism pass.',
 'Strict Pin diagnostics preserve actual rejected path/epoch/link/size before retirement without predicate relaxation.',
 'Explicit mapped-backing join allows its reviewed positive-link domain only; ordinary Pins remain single-link.',
 'Reviewed mapped correction and focused children remain separate from failed real research; no automatic retry or causal conclusion.',
 'Unchanged intake may execute selected descriptive pairs independently of unfinished mechanism research.'],
 'R16': [
 'Full5600/2800 completion remains conditional future, never substituted by four selected arms.',
 'Remote receipt/ledger and supported same checkpoint avoid remeasurement; selected local receipt is not remote grant.',
 'Archive/sync/latest-commit/final approval remain open gates; this conformance review alone cannot complete release or merge.',
 'B physical four arms and D CI/science support selected milestone, but archive/final repository gates still prevent completion claim.'],
 'R17': [
 'External observer adds no watchdog task to suite child; unchanged native single-task predicates and three required regressions actually succeed.',
 'Actual requests/response times retain late/coalesced limitations; no timely response or clock reset is inferred.',
 'Trace1MiB/namespace8MiB and capture/drain/receipt-close failures are sticky and original child FDs retire.',
 'Original signal/nonzero/interruption remain failure; historic139 cause remains unknown.',
 'Generic errno/sysctl alone grants no profile; exact original PID/path/label/boot/time denial is required.',
 'Actual hosted exact-executable ephemeral profile is load/suite-label/unload verified; no global policy waiver.',
 'Focused profile/observer tests do not replace actual hosted/ext4/source/native/science/final checks.',
 'Clock contract2 samples coarse bracket around one original syscall sequence; inclusive millisecond bins join original audit timestamp.',
 'Missing/malformed/unavailable/out-of-capture v2 facts cannot downgrade; delegates and original exception/cancellation fates persist.',
 'Explicit legacy contract1 preserves fine-clock rejection and old B failure; no inferred downgrade or binary provenance claim.'],
 'R18': [
 'Isolated fixed imports and canonical real executable retain IDs/-I/-B; foreign namespace origins reject.',
 'Loaded appsrc/queue/videoconvert facts and all six builds/three native successes are actual mandatory lane gates.',
 'Reachable sibling source metadata is repaired, while sibling image/full model grants remain historical.',
 'Hermetic metadata/owned temporary fixtures preserve strict pure contracts and confer no physical model/image authority.',
 'Finite exact declarations preserve default mandatory selection and exact audited skip reasons; safety cannot be deferred.',
 'Nine real-data/full-authority integrations remain genuine unexecuted obligations; selected current test binds exact selected receipt.',
 'Both D lanes pass full selected inventory with actual88/86 audited skips and5577 unchanged raw sources; final archive-commit checks remain pending.'],
 'R19': [
 'Private owner/root/authority/open lifetime rejects raw dict, foreign owner and expired session.',
 'Two complete source assessments plus one session retain full checks; five borrowed boundaries refresh20 original image observations.',
 'Standalone public entrypoints acquire independent complete validation; no public skip/global cache escape.',
 'Full raw/name/ancestor/seven epochs and engine/socket/fresh projection drift refuse before next native/result commit.',
 'Historical cold consumer failure cannot be repaired by producer restoration; accepted B uses its own original new closure.',
 'At most12 phase pairs/16KiB timing retains real incomplete/error fate and unchanged final2100 gate; logical reads are not measured I/O.'],
 'R20': [
 'Actual finite ext4 transfer2693=189+2504, Git/root/bind/FD proof is manual setup evidence, not model or benchmark grant.',
 'New stock closure binds genuine relocated epochs; stale Windows/old pair source cannot authorize new root.',
 'Original2100/2250/15 decide real B acceptance; late CPU05 remains failed despite output, with no inferred speedup.'],
}

def require(condition, message):
    if not condition:
        raise ValueError(message)

def epoch(st):
    return [st.st_dev, st.st_ino, st.st_mode, st.st_nlink, st.st_size, st.st_mtime_ns, st.st_ctime_ns]

def owner(pid):
    raw = Path(f'/proc/{pid}/stat').read_text()
    tail = raw[raw.rfind(')') + 2:].split()
    st = Path(f'/proc/{pid}').stat()
    return {'pid': pid, 'ppid': int(tail[1]), 'pgid': int(tail[2]), 'session': int(tail[3]),
            'startticks': int(tail[19]), 'uid': st.st_uid, 'gid': st.st_gid,
            'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def clauses(text):
    rows, current = [], None
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith('### Requirement:') or line.startswith('#### Scenario:'):
            end = i + 1
            while end < len(lines) and not lines[end].startswith(('### Requirement:', '#### Scenario:')):
                end += 1
            body = '\n'.join(lines[i:end]).strip()
            if line.startswith('### Requirement:'):
                current = {'id': f'R{len(rows)+1}', 'name': line[17:], 'exact_requirement_clause': body, 'scenarios': []}
                rows.append(current)
            else:
                current['scenarios'].append({'id': current['id'] + f'/S{len(current["scenarios"])+1}',
                    'name': line[15:], 'exact_clause': body})
    return rows

def tasks(text, historical=False):
    return [{'id': m[1], 'text': m[2], 'checked_historical' if historical else 'checked': line[3].lower() == 'x'}
            for line in text.splitlines() if (m := re.match(r'- \[[ xX]\] ([0-9]+(?:\.[0-9]+)*) (.+)', line))]

def node_sha(node):
    return sha(ast.dump(node, include_attributes=False).encode())

def save(path, obj):
    with open(path, 'xb') as stream:
        stream.write(json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2).encode() + b'\n')
        stream.flush()
        os.fsync(stream.fileno())

def main():
    started = time.monotonic_ns()
    fd_before = len(os.listdir('/proc/self/fd'))
    original_owner = owner(os.getpid())
    original_owner['observed_parent'] = owner(original_owner['ppid'])
    holds, ancestors, cached, witnesses = {}, {}, {}, []
    first = None
    close_errors = []
    report = {'schema_version': 1, 'reviewable': False, 'blocking_findings': [],
              'reviewer_handles_released': False, 'source_commit': D, 'measurement_source_commit': B,
              'reader_original': original_owner, 'archive_complete': False, 'merge_performed': False,
              'publication_ready': False, 'full_campaign_executed': False, 'component_release_complete': False}

    def remaining():
        require(time.monotonic_ns() - started <= 120_000_000_000, 'original review120s deadline')

    def digest(fd, size):
        h, offset = hashlib.sha256(), 0
        while offset < size:
            remaining()
            chunk = os.pread(fd, min(65536, size-offset), offset)
            require(bool(chunk), 'unexpected EOF')
            offset += len(chunk)
            h.update(chunk)
        require(os.pread(fd, 1, size) == b'', 'unexpected trailing bytes')
        return h.hexdigest()

    def held(path, descriptor=None):
        path = Path(path)
        require(path.is_absolute(), 'absolute original path required')
        key = str(path)
        if key not in holds:
            for parent in reversed(path.parents):
                name = str(parent)
                if name not in ancestors:
                    fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
                    ancestors[name] = (fd, epoch(os.fstat(fd)))
                    require(stat.S_ISDIR(os.fstat(fd).st_mode), 'ancestor is not directory')
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
            holds[key] = (fd, epoch(os.fstat(fd)))
            initial = holds[key][1]
            require(stat.S_ISREG(initial[2]) and initial[3] == 1 and 0 < initial[4] <= 16*1024*1024, 'finite single-link regular input')
            require(epoch(os.lstat(path)) == initial, 'named original identity')
            actual = digest(fd, initial[4])
            witnesses.append({'physical_path': key, 'size_bytes': initial[4], 'sha256': actual, 'epoch': initial})
        fd, initial = holds[key]
        witness = next(w for w in witnesses if w['physical_path'] == key)
        if descriptor:
            require(witness['size_bytes'] == descriptor['size_bytes'] and witness['sha256'] == descriptor['sha256'], 'descriptor bytes mismatch: ' + key)
            if 'observed_epoch' in descriptor:
                require(initial == descriptor['observed_epoch'], 'original seven epochs mismatch: ' + key)
        if key not in cached:
            raw, offset = bytearray(), 0
            while offset < initial[4]:
                chunk = os.pread(fd, min(65536, initial[4]-offset), offset)
                require(bool(chunk), 'metadata unexpected EOF')
                raw.extend(chunk)
                offset += len(chunk)
            require(sum(map(len, cached.values())) + len(raw) <= 96*1024*1024, '96MiB finite metadata cache')
            cached[key] = bytes(raw)
        return cached[key]

    def load_ref(ref):
        root = SOURCE if ref['domain'] == 'source' else CONTROL
        path = root / ref['path']
        require(path == Path(ref.get('physical_path', path)), 'root/descriptor path alias')
        return held(path, ref)

    try:
        HERE.mkdir(exist_ok=True)
        save(HERE/'reader-original.v1.json', original_owner)
        held(Path(__file__))
        for name, (size, expected_sha) in EXPECTED.items():
            held(BASE/'attempt01'/name, {'size_bytes': size, 'sha256': expected_sha})
        mapping = json.loads(held(BASE/'attempt01/mapping.v1.json'))
        custody = json.loads(held(BASE/'attempt01/input-custody.v1.json'))
        terminal = json.loads(held(BASE/'attempt01/terminal.v1.json'))
        require(terminal['first_failure'] is None and terminal['FD_holds_released'] and terminal['close_errors'] == [], 'original mapper not closed clean')
        require(terminal['fd_before'] == terminal['fd_after'] == 6, 'original mapper FD count')
        require(custody['FD_holds_released'] and custody['leaf_fullSHA_and_seven_epochs_rechecked'] and custody['close_errors'] == [], 'original custody failure')
        for ref in custody['files']:
            load_ref(ref)
        binding = json.loads(held(BASE/'binding.components.D.v5.json', {'size_bytes':33240,'sha256':'5d2f16cda7acb8edd727238bc244dd28f7623dd8a73b3ba13e9ddddaddb81c50'}))
        require(binding['source_commit'] == D and binding['measurement_source_commit'] == B, 'producer/reader source scope')
        require(held(SOURCE/'.git/HEAD').decode().strip() == D, 'actual current D HEAD')
        spec = next(ref for ref in binding['planning'] if ref['path'].endswith('/spec.md'))
        actual_req = clauses(load_ref(spec).decode())
        require(len(actual_req) == 20 and sum(len(r['scenarios']) for r in actual_req) == 118, '20/118 normative counts')
        for current, actual in zip(mapping['requirements'], actual_req):
            require(current['id'] == actual['id'] and current['name'] == actual['name'] and current['exact_requirement_clause'] == actual['exact_requirement_clause'], 'complete requirement differs')
            require(len(current['scenarios']) == len(actual['scenarios']), 'scenario cardinality')
            for row, normative in zip(current['scenarios'], actual['scenarios']):
                require(all(row[k] == normative[k] for k in ('id','name','exact_clause')), 'complete normative scenario differs: '+row['id'])
        old = json.loads(load_ref(binding['old_mapping']))
        old_rows = {s['id']:s for r in old['requirements'] for s in r['scenarios']}
        new_rows = {s['id']:s for r in mapping['requirements'] for s in r['scenarios']}
        require(len(old_rows) == 112 and set(new_rows)-set(old_rows) == {'R14/S6','R14/S7','R14/S8','R17/S8','R17/S9','R17/S10'}, 'six explicit added clauses')
        for ident, row in old_rows.items():
            require(new_rows[ident]['exact_clause'] == row['exact_clause'], 'original112 clause changed: '+ident)
        original82 = [s for r in clauses(load_ref(binding['original_spec']).decode()) for s in r['scenarios']]
        require(len(original82) == 82 and all({k: a[k] for k in ('id','name','exact_clause')} == {k: b[k] for k in ('id','name','exact_clause')} for a,b in zip(original82,mapping['historical_original_scenarios'])), 'original82 register')
        require(tasks(load_ref(binding['original_tasks']).decode(), True) == mapping['historical_original_task_register'], 'original72 tasks/text/state changed')
        task_ref = next(ref for ref in binding['planning'] if ref['path'].endswith('/tasks.md'))
        require(tasks(load_ref(task_ref).decode()) == mapping['current_task_states'], 'current task states')
        require(len(mapping['current_task_states']) == 74 and sum(x['checked'] for x in mapping['current_task_states']) == 65, 'current65/74 boundary')

        trees = {}
        def tree(ref):
            raw = load_ref(ref)
            name = str(ref.get('physical_path', (SOURCE if ref['domain']=='source' else CONTROL)/ref['path']))
            if name not in trees:
                trees[name] = ast.parse(raw.decode('utf-8-sig'), filename=name)
            return trees[name], raw.decode('utf-8-sig').splitlines()
        for ident, test in mapping['tests'].items():
            parsed, lines = tree(test['source'])
            nodes = [node for node in ast.walk(parsed) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.lineno == test['line'] and node.name == ident.split('.')[-1]]
            require(len(nodes) == 1 and node_sha(nodes[0]) == test['method_ast_sha256'] and nodes[0].end_lineno == test['end_line'], 'qualified method AST: '+ident)
            require('\n'.join(lines[test['line']-1:test['end_line']]) == test['method_source'], 'qualified method body: '+ident)
            actual_asserts = [{'line':node.lineno,'assertion':ast.unparse(node)} for node in ast.walk(nodes[0]) if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr.startswith('assert')]
            require(actual_asserts == test['assertions'], 'actual assertion calls: '+ident)
            for helper in test['directly_called_assertion_helpers']:
                candidates = [node for node in ast.walk(parsed) if isinstance(node, (ast.FunctionDef,ast.AsyncFunctionDef)) and node.lineno == helper['line'] and node.name == helper['name']]
                require(len(candidates)==1 and node_sha(candidates[0]) == helper['ast_sha256'], 'direct assertion helper AST: '+ident)
            for cpp in test['compiled_cpp_inputs']:
                lines_cpp = load_ref(cpp['source']).decode().splitlines()
                require(all(lines_cpp[row['line']-1] == row['text'] for row in cpp['named_checks']), 'compiled C++ actual checks')
        for key, anchor in mapping['source_anchors'].items():
            raw = load_ref(anchor['source']).decode('utf-8-sig')
            lines = raw.splitlines()
            require([i+1 for i,line in enumerate(lines) if anchor['anchor'] in line] == anchor['matching_lines'], 'source anchor literal: '+key)
            if anchor['enclosing_boundary']:
                boundary = anchor['enclosing_boundary']
                parsed, _ = tree(anchor['source'])
                candidates = [n for n in ast.walk(parsed) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and n.lineno == boundary['line'] and n.name == boundary['name']]
                require(len(candidates)==1 and node_sha(candidates[0]) == boundary['ast_sha256'], 'source boundary AST: '+key)

        lanes = {}
        tables = {}
        for lane, ci in mapping['current_CI'].items():
            refs = ci['original_refs']
            outputs = {k:json.loads(load_ref(v)) for k,v in refs.items()}
            r, unit = outputs['report'], outputs['report']['unittest']
            require(r['commit'] == D and r['successful'] and r['raw_checkout_bytes_match_commit'] and r['changed_tracked_paths']==[], 'actual current CI report: '+lane)
            require(unit['successful'] and not unit['failures'] and not unit['errors'] and not unit['missing_required_successes'] and not unit['unexpected_successes'], 'actual full suite failed: '+lane)
            require(outputs['source_before'] == outputs['source_after'] and len(outputs['source_before'])==5577, 'whole tested source table')
            require(all(set(row) >= {'size_bytes','sha256'} for row in outputs['source_before'].values()), 'raw source table shape')
            selection = unit['selection']
            require(len(unit['discovered_ids'])==3001 and len(set(unit['discovered_ids']))==3001 and unit['tests_run']==2992, 'original discovered/selected counts')
            require(len(unit['successful_test_ids'])==(2906 if lane=='ext4' else 2904) and len(unit['skips'])==(86 if lane=='ext4' else 88), 'original lane outcomes')
            require(len(set(unit['successful_test_ids']))==len(unit['successful_test_ids']), 'duplicate success IDs')
            require(unit['skips'] == ci['skips'] and selection == ci['selection'], 'actual exact portable skip selection')
            allowed = {x['test_id']: x for x in selection['allowed_portable_skips']}
            require(all(x['test_id'] in allowed and x['reason'] == allowed[x['test_id']]['reason'] for x in unit['portable_skip_audit']), 'exact skip ID/reason allowance')
            require(all(x['acceptance_claim'] is False for x in unit['portable_skip_audit']), 'skip acceptance')
            require(len(r['built_targets'])==6 and set(r['built_targets'])==set(ci['built_targets']), 'actual six build targets')
            observer = r['observer']
            require(observer['returncode']==0 and observer['signal'] is None and observer['successful'] and observer['failure'] is None and all(observer['pipe_eof'].values()) and not observer['forced_sigterm'] and not observer['forced_sigkill'], 'original observer failed')
            require(outputs['terminal']==observer, 'observer exact report/terminal join')
            for ident, test in mapping['tests'].items():
                outcome = ('success' if ident in unit['successful_test_ids'] else 'audited_nonexecution' if any(x['test_id']==ident for x in unit['portable_skip_audit']) else 'not_reported_as_executed')
                require(test['current_ci_outcomes'][lane]==outcome, 'actual method outcome join: '+ident)
                if test['source']['domain']=='source':
                    row=outputs['source_before'][test['source']['path']]
                    require(row['size_bytes']==test['source']['size_bytes'] and row['sha256']==test['source']['sha256'], 'tested method raw source')
            if lane=='ext4':
                require(outputs['closure']['mandatory_local_CI_pass'] and outputs['closure']['error'] is None and outputs['closure']['all_reader_handles_released'], 'actual local review closure')
            else:
                require(outputs['closure']['mandatory_hosted_CPU_CI_pass_for_exact_commit'] and outputs['closure']['reviewable'] and outputs['closure']['blocking_findings']==[] and outputs['closure']['reviewer_handles_released'], 'actual hosted review closure')
            lanes[lane]={'original_refs': refs, 'commit':D, 'discovered':3001,'selected':2992,'successes':len(unit['successful_test_ids']),'audited_skips':len(unit['skips']),'six_built_targets':r['built_targets'],'mandatory_native_missing':[], 'observer_returncode':0,'original_EOF':observer['pipe_eof'],'closure_bound':True,
                'limits':'No skipped method or deferred integration is passed; hosted executable raw binary/global descendant absence is not invented.'}
            tables[lane]=outputs['source_before']
        require(tables['hosted']==tables['ext4'], 'both D whole tested raw tables differ')
        source_paths = {test['source']['path'] for test in mapping['tests'].values() if test['source']['domain']=='source'} | {anchor['source']['path'] for anchor in mapping['source_anchors'].values() if anchor['source']['domain']=='source'}
        for path in source_paths:
            actual = next(w for w in witnesses if w['physical_path']==str(SOURCE/path))
            require(actual['size_bytes']==tables['ext4'][path]['size_bytes'] and actual['sha256']==tables['ext4'][path]['sha256'], 'raw whole tested source anchor: '+path)

        adjudications = []
        for requirement in mapping['requirements']:
            require(len(NOTES[requirement['id']]) == len(requirement['scenarios']), 'independent all-row notes missing')
            for row,note in zip(requirement['scenarios'],NOTES[requirement['id']]):
                require(bool(row['source_anchor_refs']) and all(i in mapping['tests'] for i in row['test_refs']), 'unresolved scenario refs')
                limits = list(row['automatic_verification_limits'])
                if row['id'] in {'R5/S5','R12/S1','R14/S2','R20/S1'}:
                    limits.append('Manual physical/documentary row: no direct named test is invented.')
                if row['id']=='R13/S6':
                    limits.append('Named full consumer source guards manually checked; direct negative tests for every consumer and universal zero-side-effect rejection remain unverified.')
                if row['scope']!='active_selected_component_or_repository_behavior':
                    limits.append('Physical future campaign/research completion remains unexecuted; only applicable current interface/failure predicates and retained focused evidence are reviewed.')
                not_run = [i for i in row['test_refs'] if all(v!='success' for v in mapping['tests'][i]['current_ci_outcomes'].values())]
                if not_run:
                    limits.append('These methods are not executed-success by either whole CI: '+', '.join(not_run))
                adjudications.append({'id':row['id'],'name':row['name'],'exact_clause_sha256':sha(row['exact_clause'].encode()),'scope':row['scope'],'historical_register_id':row['historical_register_id'],
                    'adjudication':'reviewed_current_predicates_and_scoped_evidence_not_full_campaign_completion','independent_semantic_reason':note,
                    'qualified_test_ids':row['test_refs'],'actual_method_outcomes':{i:mapping['tests'][i]['current_ci_outcomes'] for i in row['test_refs']},
                    'actual_source_anchors':row['source_anchor_refs'],'automatic_and_manual_limits':limits,'blocking_findings':[]})
        require(len(adjudications)==118, 'every row adjudication')
        report.update({'reviewable':True,'status':'current_conformance_semantically_reviewable_with_explicit_limits',
            'requirements':[{'id':r['id'],'name':r['name'],'complete_clause_sha256':sha(r['exact_requirement_clause'].encode()),'scenario_ids':[s['id'] for s in r['scenarios']],
                'disposition':'all current applicable predicates reviewed; conditional future completion and final repository gates retained'} for r in mapping['requirements']],
            'scenario_adjudications':adjudications,'normative_preservation':{'requirements':20,'scenarios':118,'original112_complete_clauses':True,'six_added_ids':sorted(set(new_rows)-set(old_rows)),
                'historical82_exact_memberships_names_bodies':True,'historical72_exact_task_text_state':True,'historical_checked':31,'historical_unchecked':41,'current_checked':65,'current_count':74},
            'source_test_checks':{'unique_qualified_methods':290,'actual_method_AST_body_assertions_and_direct_helpers_checked':True,'unique_anchors':195,'raw_tested_D_source_paths_checked':len(source_paths),
                'literal_source_lines_and_enclosing_AST_checked':True,'compiled_CPP_checks_source_bound':True,'AST_is_not_execution_proof':True},
            'actual_CI':lanes,'all_whole_tested_sources_equal_between_D_lanes':5577,
            'physical_evidence':mapping['current_evidence'],'manual_coverage_rows':['R5/S5','R12/S1','R14/S2','R20/S1'],'all_consumer_direct_negative_gap':'R13/S6',
            'current_finalization':mapping['finalization'],
            'nonblocking_interpretation_notes':['Inherited historical pending sentences are superseded only by exact current evidence joins, never historical receipt rebinding.',
              'R14/S4 validated journal remains subject to explicit owner/authorization: only elected immutable owner may emit its durable terminal; failed losing candidate has bounded stdout only.',
              'Current normative Windows documents and clean tested D sources are separate physical identities; no entire current Windows tree == D claim.',
              'Mapper actual FD6->6 and closed custody are verified; missing original mapper birth/session observations are not reconstructed. Later mapper/reader owner closure is separate.'],
            'limits':['No target code import, model/inference/engine/test/CI/generator execution or Git action.',
              'Both actual complete portable CI lanes are accepted in their own source scope;9 exact physical integrations and full32/Q4/5600 remain unexecuted.',
              'B four arms are one baseline-first descriptive pair per resource under opaque proxy/partial C_obs; no SLO, accuracy, causal speedup, energy/NVDEC busy or population claim.',
              'Archive/main-spec synchronization, cleanup, pushed latest archive-commit checks and exact final review remain separate gates.',
              'No currently live reader can attest its own later absence; this report records held FD release only.']})
        for name,(fd,initial) in ancestors.items():
            require(epoch(os.fstat(fd))[:3]==initial[:3] and epoch(os.lstat(name))[:3]==initial[:3], 'held ancestor changed: '+name)
        for path,(fd,initial) in holds.items():
            require(epoch(os.fstat(fd))==initial and epoch(os.lstat(path))==initial, 'held/named seven epochs changed: '+path)
            require(digest(fd,initial[4])==next(w['sha256'] for w in witnesses if w['physical_path']==path), 'held final raw SHA drift: '+path)
        report['physical_input_witnesses'] = witnesses
        report['full_before_after_held_SHA_name_seven_epochs_rechecked']=True
    except BaseException as exc:
        first={'type':type(exc).__name__,'message':str(exc)}
        report.update(reviewable=False,blocking_findings=[first])
    finally:
        for path,(fd,_) in reversed(list(holds.items())+list(ancestors.items())):
            try:
                os.close(fd)
            except BaseException as exc:
                close_errors.append({'path':path,'type':type(exc).__name__,'message':str(exc)})
        report['first_failure']=first
        report['close_errors']=close_errors
        report['fd_before']=fd_before
        report['fd_after']=len(os.listdir('/proc/self/fd'))
        report['reviewer_handles_released']=not close_errors and report['fd_after']==fd_before
        report['held_leaf_count']=len(holds)
        report['held_ancestor_count']=len(ancestors)
        report['elapsed_s']=(time.monotonic_ns()-started)/1e9
        report['reviewable']=report['reviewable'] and report['reviewer_handles_released']
        save(HERE/'review.v1.json',report)
        final_elapsed=(time.monotonic_ns()-started)/1e9
        if final_elapsed>120:
            save(HERE/'late-failure.v1.json',{'first_failure':first,'actual_final_elapsed_s':final_elapsed,'original_limit_s':120,'reviewable':False})
            return 78
        if first or close_errors:
            print(json.dumps({'reviewable':False,'first_failure':first,'close_errors':close_errors}))
            return 78
        raw=(HERE/'review.v1.json').read_bytes()
        print(json.dumps({'reviewable':report['reviewable'],'path':str(HERE/'review.v1.json'),'size_bytes':len(raw),'sha256':sha(raw),'final_elapsed_s':final_elapsed,'pid':os.getpid()}))
        return 0

if __name__ == '__main__':
    raise SystemExit(main())
