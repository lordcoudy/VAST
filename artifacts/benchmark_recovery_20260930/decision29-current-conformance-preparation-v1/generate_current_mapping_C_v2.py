"""Prepared metadata/AST index only. No target import, Git, test or runtime call.

One invocation consumes an independently reviewed exact binding and publishes
one fresh result directory. It cannot declare conformance, archive or release.
Run only after the root has reviewed this source and granted the exact binding.
"""
import ast
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
import traceback

HERE = Path(__file__).absolute().parent
CONTROL = HERE.parents[2]
SOURCE = Path('/home/s-a-balashov/work/vast-current-source-ci-20261003-decision29')
COMMIT = '04a5d1c7b90274af71f4ff2456ec3013107c2bb3'
MEASUREMENT = 'a00aa57f7d9534f8e7920f14f70d6a75a23570ed'
START = time.monotonic_ns()
DEADLINE = START + 120_000_000_000
MAX_FILE = 16 * 1024 * 1024
MAX_TOTAL = 96 * 1024 * 1024
NEW = {'R14/S6', 'R14/S7', 'R14/S8', 'R17/S8', 'R17/S9', 'R17/S10'}
holds = {}
ancestors = {}
raw_cache = {}
total = 0
close_errors = []


def require(ok, message):
    if not ok:
        raise ValueError(message)


def check_clock():
    require(time.monotonic_ns() < DEADLINE, 'original120s metadata deadline exceeded')


def epoch(info):
    return [info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def directory_identity(info):
    return [info.st_dev, info.st_ino, info.st_mode]


def absolute(ref):
    require(ref.get('domain') in {'control', 'source'}, 'unknown source domain')
    rel = Path(ref['path'])
    require(not rel.is_absolute() and bool(rel.parts) and
            all(part not in {'..', '.', ''} for part in rel.parts), 'noncanonical relative leaf')
    root = CONTROL if ref['domain'] == 'control' else SOURCE
    return root / rel


def hold_ancestors(path):
    for parent in reversed(path.parents):
        key = str(parent)
        if key in ancestors:
            continue
        before = parent.lstat()
        require(stat.S_ISDIR(before.st_mode), 'ancestor is not a real directory: ' + key)
        fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        ancestors[key] = [fd, directory_identity(before)]
        require(directory_identity(os.fstat(fd)) == directory_identity(before) ==
                directory_identity(parent.lstat()), 'ancestor identity drift: ' + key)


def read_ref(ref):
    global total
    check_clock()
    path = absolute(ref)
    key = str(path)
    if key in holds:
        row = holds[key]
        if 'sha256' in ref:
            require(row['sha256'] == ref['sha256'] and row['size_bytes'] == ref['size_bytes'],
                    'conflicting expected descriptor: ' + key)
        return raw_cache[key], row
    hold_ancestors(path)
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and
            0 <= before.st_size <= MAX_FILE, 'leaf type/link/size refused: ' + key)
    require(total + before.st_size <= MAX_TOTAL, 'aggregate metadata budget exceeded')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    row = {'domain': ref['domain'], 'path': ref['path'], 'physical_path': key,
           'fd': fd, 'observed_epoch': epoch(before), 'size_bytes': before.st_size}
    holds[key] = row
    require(epoch(os.fstat(fd)) == row['observed_epoch'] == epoch(path.lstat()),
            'opening leaf epoch drift: ' + key)
    chunks = []
    offset = 0
    while offset < before.st_size:
        check_clock()
        block = os.pread(fd, min(1024 * 1024, before.st_size - offset), offset)
        require(bool(block), 'short original metadata read: ' + key)
        chunks.append(block)
        offset += len(block)
    raw = b''.join(chunks)
    require(os.pread(fd, 1, offset) == b'', 'metadata grew during read: ' + key)
    row['sha256'] = hashlib.sha256(raw).hexdigest()
    require(epoch(os.fstat(fd)) == row['observed_epoch'] == epoch(path.lstat()),
            'read epoch drift: ' + key)
    if 'sha256' in ref:
        require(row['sha256'] == ref['sha256'] and row['size_bytes'] == ref['size_bytes'],
                'expected raw SHA/size mismatch: ' + key)
    total += len(raw)
    raw_cache[key] = raw
    return raw, row


def descriptor(row):
    return {key: value for key, value in row.items() if key != 'fd'}


def load(ref):
    raw, row = read_ref(ref)
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, 'duplicate JSON key: ' + key)
            value[key] = item
        return value
    return json.loads(raw, object_pairs_hook=unique), descriptor(row)


def parse_spec(raw):
    lines = raw.decode('utf-8').splitlines()
    result = []
    current = None
    for index, line in enumerate(lines):
        if line.startswith('### Requirement: '):
            end = index + 1
            while end < len(lines) and not lines[end].startswith(('### Requirement:', '#### Scenario:')):
                end += 1
            current = {'id': 'R' + str(len(result) + 1), 'name': line[17:],
                       'line': index + 1, 'exact_requirement_clause':'\n'.join(lines[index:end]).strip(),
                       'scenarios': []}
            result.append(current)
        if line.startswith('#### Scenario: '):
            require(current is not None, 'scenario has no requirement')
            end = index + 1
            while end < len(lines) and not lines[end].startswith(('### Requirement:', '#### Scenario:')):
                end += 1
            current['scenarios'].append({'id': current['id'] + '/S' + str(len(current['scenarios']) + 1),
                'name': line[15:], 'line': index + 1, 'exact_clause': '\n'.join(lines[index:end]).strip()})
    return result


def node_sha(node):
    return hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()


def method_node(tree, classname, method):
    found = [node for cls in tree.body if isinstance(cls, ast.ClassDef) and cls.name == classname
             for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method]
    require(len(found) == 1, 'missing or ambiguous qualified method: ' + classname + '.' + method)
    return found[0]


def verify_all():
    for key, (fd, identity) in ancestors.items():
        check_clock()
        require(directory_identity(os.fstat(fd)) == identity ==
                directory_identity(Path(key).lstat()), 'final ancestor drift: ' + key)
    for key, row in holds.items():
        check_clock()
        require(epoch(os.fstat(row['fd'])) == row['observed_epoch'] ==
                epoch(Path(key).lstat()), 'final full seven-epoch drift: ' + key)
        digest = hashlib.sha256()
        offset = 0
        while offset < row['size_bytes']:
            check_clock()
            block = os.pread(row['fd'], min(1024 * 1024, row['size_bytes'] - offset), offset)
            require(bool(block), 'final short read: ' + key)
            digest.update(block)
            offset += len(block)
        require(os.pread(row['fd'], 1, offset) == b'' and digest.hexdigest() == row['sha256'],
                'final raw SHA/size drift: ' + key)
        require(epoch(os.fstat(row['fd'])) == row['observed_epoch'] ==
                epoch(Path(key).lstat()), 'final posthash epoch drift: ' + key)
    for key, (fd, identity) in ancestors.items():
        check_clock()
        require(directory_identity(os.fstat(fd)) == identity ==
                directory_identity(Path(key).lstat()), 'final posthash ancestor drift: ' + key)


def retire_all():
    for row in list(holds.values()):
        try:
            os.close(row['fd'])
        except BaseException as error:
            close_errors.append({'path': row['physical_path'], 'type': type(error).__name__,
                                 'message': str(error)[:300]})
    for key, (fd, _) in list(ancestors.items()):
        try:
            os.close(fd)
        except BaseException as error:
            close_errors.append({'path': key, 'type': type(error).__name__, 'message': str(error)[:300]})


def publish(out, name, value):
    check_clock()
    raw = (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + '\n').encode('ascii')
    require(len(raw) <= MAX_FILE, 'output metadata exceeds16MiB: ' + name)
    fd = os.open(out / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        offset = 0
        while offset < len(raw):
            check_clock()
            written = os.write(fd, raw[offset:])
            require(written > 0, 'short result write: ' + name)
            offset += written
        os.fsync(fd)
    finally:
        os.close(fd)
    return {'path': str(out / name), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def build(binding):
    require(binding['schema_version'] == 1 and binding['kind'] == 'decision29_current_conformance_input_binding_v1',
            'wrong conformance binding schema/kind')
    require(binding['source_commit'] == COMMIT and binding['source_root'] == str(SOURCE) and
            binding['measurement_source_commit'] == MEASUREMENT, 'prepared repository/measurement source binding drifted')
    head, _ = read_ref({'domain': 'source', 'path': '.git/HEAD'})
    require(head == (COMMIT + '\n').encode(), 'bound actual checkout HEAD differs')
    original, original_ref = load(binding['old_mapping'])
    require(original['scenario_count'] == 112 and original['requirements_count'] == 20 and
            original['historical_exact_register_scenarios'] == 82, 'wrong original mapping')
    for ref in binding['old_generators'] + binding['documents']:
        read_ref(ref)
    planning = {ref['path']: read_ref(ref)[0] for ref in binding['planning']}
    spec_path = next(path for path in planning if path.endswith('/specs/benchmark-launch-preparation/spec.md'))
    verification_path = next(path for path in planning if path.endswith('/verification-plan.md'))
    task_path = next(path for path in planning if path.endswith('/tasks.md'))
    requirements = parse_spec(planning[spec_path])
    actual = {item['id']: item for req in requirements for item in req['scenarios']}
    prior = {item['id']: item for req in original['requirements'] for item in req['scenarios']}
    require(len(requirements) == 20 and len(actual) == 118 and set(actual) - set(prior) == NEW,
            '20requirements/118scenarios/six additions drifted')
    for ident, row in prior.items():
        require(actual[ident]['exact_clause'] == row['exact_clause'] and actual[ident]['name'] == row['name'],
                'original112 scenario clause/name altered: ' + ident)
    notes, notes_ref = load(binding['notes'])
    require(set(notes.get('current_behavior_overrides', {})) <= set(prior), 'reviewed behavior override refers to an unknown original scenario')
    require(set(notes['new_scenarios']) == NEW, 'six reviewed scenario notes drifted')
    legacy_task_raw, legacy_task_ref = read_ref(binding['original_tasks'])
    legacy_spec_raw, legacy_spec_ref = read_ref(binding['original_spec'])
    register = planning[verification_path].decode('utf-8')
    current_tasks = planning[task_path].decode('utf-8')
    tasks = []
    for line in legacy_task_raw.decode('utf-8').splitlines():
        match = re.fullmatch(r'- \[([ x])\] (\d+(?:\.\d+)+) (.+)', line)
        if match:
            state, ident, text = match.groups()
            expected = '- Original `' + ident + '`; state=' + ('checked-historical' if state == 'x' else 'unchecked-unexecuted-at-original-scope') + '; ' + text
            require(expected in register, 'literal original task register drift: ' + ident)
            if state == 'x':
                require(line in current_tasks, 'original checked task text/state drift: ' + ident)
            tasks.append({'id': ident, 'checked_historical': state == 'x', 'text': text})
    historical_scenarios = [row for req in parse_spec(legacy_spec_raw) for row in req['scenarios']]
    require(len(tasks) == 72 and sum(row['checked_historical'] for row in tasks) == 31 and
            len(historical_scenarios) == 82, 'original72/31/82 register count drifted')
    for row in historical_scenarios:
        require(row['id'] + ': ' + row['name'] + '.' in register,
                'original82 scenario register name drift: ' + row['id'])

    tests = {}
    anchors = {}
    source_trees = {}
    gaps = []
    def source(path):
        if path not in source_trees:
            raw, pin = read_ref({'domain': 'source', 'path': path})
            source_trees[path] = (raw.decode('utf-8'), ast.parse(raw, filename=path) if path.endswith('.py') else None, descriptor(pin))
        return source_trees[path]
    def test(ident):
        if ident in tests:
            return ident
        if ident in original['tests']:
            path = original['tests'][ident]['source']['path']
            old = original['tests'][ident]
        else:
            module, _, _ = ident.rsplit('.', 2)
            path, old = 'tests/' + module + '.py', None
        text, tree, pin = source(path)
        _, cls, name = ident.rsplit('.', 2)
        node = method_node(tree, cls, name)
        reviewed_delta = None
        reviewed_change = notes.get('reviewed_method_changes', {}).get(ident)
        if reviewed_change is not None and reviewed_change.get('applicable_source_commit', COMMIT) == COMMIT:
            revised = ast.parse(ast.unparse(node)).body[0]
            changed_count = 0
            if reviewed_change['change_type'] == 'one_explicit_legacy_clock_keyword':
                for call in ast.walk(revised):
                    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute) or call.func.attr != 'join_original_userns_denial_v1':
                        continue
                    remaining = []
                    for keyword in call.keywords:
                        if keyword.arg == 'expected_clock_contract_version' and isinstance(keyword.value, ast.Constant) and type(keyword.value.value) is int and keyword.value.value == 1:
                            changed_count += 1
                        else:
                            remaining.append(keyword)
                    call.keywords = remaining
                require(changed_count == 1, 'reviewed legacy-context keyword delta drifted: ' + ident)
            elif reviewed_change['change_type'] == 'three_current_receipt_literals':
                reverse = reviewed_change['reverse_constants']
                for constant in ast.walk(revised):
                    if not isinstance(constant, ast.Constant) or type(constant.value) not in {str, int}:
                        continue
                    key = str(constant.value)
                    if key in reverse:
                        constant.value = reverse[key]
                        changed_count += 1
                require(changed_count == 3, 'reviewed current-receipt three-literal delta drifted: ' + ident)
            else:
                raise ValueError('unknown reviewed test delta: ' + ident)
            require(old is not None and node_sha(revised) == old['method_ast_sha256'],
                    'original test body/assertions differ after exact reviewed inverse: ' + ident)
            reviewed_delta = reviewed_change
        assertions = [{'line': call.lineno, 'assertion': ast.unparse(call)} for call in ast.walk(node)
                      if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr.startswith('assert')]
        owner = next(cl for cl in tree.body if isinstance(cl, ast.ClassDef) and cl.name == cls)
        helper_names = {call.func.attr for call in ast.walk(node) if isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name)
                        and call.func.value.id == 'self' and not call.func.attr.startswith('assert')}
        helper_rows = []
        for helper in owner.body:
            if not isinstance(helper, (ast.FunctionDef, ast.AsyncFunctionDef)) or helper.name not in helper_names:
                continue
            helper_rows.append({'name':helper.name,'line':helper.lineno,'end_line':helper.end_lineno,
                'ast_sha256':node_sha(helper),
                'assertions':[{'line':call.lineno,'assertion':ast.unparse(call)} for call in ast.walk(helper)
                    if isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute) and call.func.attr.startswith('assert')],
                'source':'\n'.join(text.splitlines()[helper.lineno-1:helper.end_lineno]),
                'limit':'One directly called class helper only; not exhaustive transitive assertion coverage.'})
        cpp_inputs = []
        for call in ast.walk(node):
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == '_compile_and_run' and call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
                cpp = 'tests/cpp/' + call.args[0].value
                require(Path(call.args[0].value).name == call.args[0].value and cpp.endswith('.cpp'), 'invalid literal native test input')
                cpp_raw, cpp_pin = read_ref({'domain':'source','path':cpp})
                cpp_inputs.append({'source':descriptor(cpp_pin),
                    'named_checks':[{'line':number+1,'text':line[:300]} for number,line in enumerate(cpp_raw.decode().splitlines())
                        if re.search(r'\b(assert|require|expect|check|fail|throw)\b',line,re.I)],
                    'limit':'Pinned compiled source and explicit check lines; original successful native test ID still required.'})
        tests[ident] = {'id': ident, 'source': pin, 'line': node.lineno, 'end_line': node.end_lineno,
                       'method_ast_sha256': node_sha(node), 'assertions': assertions,
                       'method_source': '\n'.join(text.splitlines()[node.lineno-1:node.end_lineno]),
                       'directly_called_assertion_helpers':helper_rows,'compiled_cpp_inputs':cpp_inputs,
                       'called_boundaries': sorted({ast.unparse(call.func) for call in ast.walk(node) if isinstance(call, ast.Call)}),
                       'AST_equal_to_prior_review': None if old is None else node_sha(node) == old['method_ast_sha256'],
                       'reviewed_exact_AST_delta':reviewed_delta,
                       'historical_assertion_evidence_ref': original_ref if old is not None else None,
                       'current_ci_outcomes': {}, 'fixture_limit': 'Assertions apply to the pinned method and its actual fixtures; no transitive/hardware/full-consumer grant follows from a method hash.'}
        return ident
    def anchor(path, needle):
        key = path + '#' + needle
        if key in anchors:
            return key
        text, tree, pin = source(path)
        lines = text.splitlines()
        found = [i+1 for i, line in enumerate(lines) if needle in line]
        require(bool(found), 'current exact source anchor missing: ' + key)
        defs = [] if tree is None else [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
        named = [n for n in defs if n.name == needle.removeprefix('def ')]
        line = named[0].lineno if len(named) == 1 else found[0]
        within = [n for n in defs if n.lineno <= line <= n.end_lineno]
        node = min(within, key=lambda n:n.end_lineno-n.lineno) if within else None
        prior_anchor = original['source_anchors'].get(key)
        boundary = None if node is None else {'name': node.name, 'line': node.lineno, 'end_line': node.end_lineno, 'ast_sha256': node_sha(node)}
        anchors[key] = {'source': pin, 'anchor': needle, 'line': line, 'matching_lines': found,
                        'enclosing_boundary': boundary,
                        'excerpt': '\n'.join(lines[max(0,line-2):min(len(lines),line+5)])[:2000],
                        'AST_equal_to_prior_review': None if prior_anchor is None or boundary is None or prior_anchor.get('enclosing_boundary') is None else boundary['ast_sha256'] == prior_anchor['enclosing_boundary']['ast_sha256'],
                        'raw_equal_to_prior_review': None if prior_anchor is None else pin['sha256'] == prior_anchor['source']['sha256'] and pin['size_bytes'] == prior_anchor['source']['size_bytes'],
                        'limit': 'Pinned source predicate, not an executed boundary assertion.'}
        return key
    for ident in original['tests']:
        test(ident)
    for key in original['source_anchors']:
        path, needle = key.split('#', 1)
        anchor(path, needle)
    evidence = {}
    historical_evidence = {}
    for alias, ref in original['evidence'].items():
        domain_ref = {**ref, 'domain': 'control'}
        _, observed = read_ref(domain_ref)
        historical_evidence[alias] = descriptor(observed)
    for alias, ref in binding['evidence'].items():
        value, pin = load(ref) if ref['path'].endswith('.json') else (None, descriptor(read_ref(ref)[1]))
        evidence[alias] = {'physical': pin, 'classification': 'source-specific scoped original evidence; not overall conformance acceptance'}
        if alias in {'cpu08', 'gpu02'}:
            require(value.get('benchmark_accepted') is True, 'current original pair audit is not accepted: ' + alias)
        if alias == 'selected_image_test_unit' and COMMIT == '3c025b29b3c1d5275c2ec693410e4b83700583de':
            ident = 'test_publication_runtime_frozen_identity_constants_v1.PublicationRuntimeFrozenIdentityConstantsV1Tests.test_gstreamer_current_runtime_is_exactly_refrozen'
            require(value['tests_run'] == 1 and value['ids'] == [ident] and not value['errors'] and not value['failures'] and not value['skips'] and value['source_stable'],
                    'original current-image one-test focused result differs')
            require(value['source_before'] == value['source_after'] and len(value['fd_timing_facts']) == 1 and value['fd_timing_facts'][0]['id'] == ident,
                    'original selected-image focused source/ID facts differ')
            test(ident)
            prefix = '/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec/'
            path = tests[ident]['source']['path']
            tested = next((row for row in value['source_before'] if row['path'] == prefix + path), None)
            require(tested is not None and tested['sha256'] == tests[ident]['source']['sha256'] and tested['size_bytes'] == tests[ident]['source']['size_bytes'],
                    'one focused test raw bytes do not join the bound D checkout')
            tests[ident]['current_focused_outcome'] = {'outcome':'success','tested_source':tests[ident]['source'],
                'result_ref':evidence[alias]['physical'],'limit':value['classification']}
        if alias == 'ci_clock_unit':
            require(value['tests_run'] == 51 and not value['errors'] and not value['failures'] and not value['skips'] and value['source_stable'],
                    'original51 focused clock result differs')
            require(value['source_before'] == value['source_after'] and len(value['fd_timing_facts']) == 51,
                    'original focused source/51 per-test facts differ')
            prefix = '/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec/'
            by_path = {row['path'][len(prefix):]: row for row in value['source_before']
                       if row['path'].startswith(prefix)}
            for module in value['ids']:
                path = 'tests/' + module + '.py'
                _, _, pin = source(path)
                row = by_path.get(path)
                require(row is not None and row['sha256'] == pin['sha256'] and row['size_bytes'] == pin['size_bytes'],
                        'focused test raw bytes do not equal actual tested checkout: ' + path)
            focused_ids = [row['id'] for row in value['fd_timing_facts']]
            require(len(set(focused_ids)) == 51, 'duplicate/missing original focused ID')
            for ident in focused_ids:
                test(ident)
                tests[ident]['current_focused_outcome'] = {'outcome':'success', 'tested_source':tests[ident]['source'],
                    'result_ref':evidence[alias]['physical'],
                    'limit':value['classification']}
    consumer_refs = [anchor(path, needle) for path, needle in notes['full_consumer_anchors']]
    for ident, reviewed in notes['new_scenarios'].items():
        for test_id in reviewed['tests']:
            test(test_id)
        for path, needle in reviewed['anchors']:
            anchor(path, needle)

    ci = {}
    for lane in ('hosted', 'ext4'):
        record = binding['current_ci'][lane]
        if record is None:
            ci[lane] = {'status': 'pending_original_bound_source_terminal_binding', 'whole_success': None}
            continue
        require(set(record) == {'report','source_before','source_after','terminal','closure'}, 'invalid exact CI lane refs: ' + lane)
        values = {name: load(ref)[0] for name, ref in record.items()}
        report, before, after = values['report'], values['source_before'], values['source_after']
        require(report.get('commit') == COMMIT and before == after and report.get('raw_checkout_bytes_match_commit') is True,
                'exact tested CI raw source/commit evidence differs: ' + lane)
        for pin in holds.values():
            if pin['domain'] != 'source' or pin['path'].startswith('.git/'):
                continue
            path = pin['path']
            row = before.get(path)
            require(row is not None and row['sha256'] == pin['sha256'] and row['size_bytes'] == pin['size_bytes'],
                    'tested source table does not join exact checkout leaf: ' + path)
        suite = report.get('unittest', {})
        success = set(suite.get('successful_test_ids', []))
        skips = {row['test_id']: row['reason'] for row in suite.get('skips', [])}
        failures = {row['test_id'] for row in suite.get('failures', [])}
        errors = {row['test_id'] for row in suite.get('errors', [])}
        require(not (success & (set(skips)|failures|errors)), 'conflicting original test statuses')
        for ident in tests:
            tests[ident]['current_ci_outcomes'][lane] = ('success' if ident in success else 'audited_nonexecution' if ident in skips else 'failure' if ident in failures else 'error' if ident in errors else 'not_reported_as_executed')
        ci[lane] = {'status': 'original_metadata_joined_requires_independent_CI_peer',
                    'whole_success': report.get('successful') is True,
                    'source_table_count': len(before), 'built_targets': report.get('built_targets'),
                    'tests_run': suite.get('tests_run'), 'success_count': len(success),
                    'failures': suite.get('failures', []), 'errors': suite.get('errors', []),
                    'skips': suite.get('skips', []), 'selection': suite.get('selection'),
                    'missing_required_successes': suite.get('missing_required_successes'),
                    'original_refs': record, 'terminal_and_closure': {'terminal': values['terminal'], 'closure': values['closure']},
                    'limit': 'Terminal/closure originals are pinned; their actual provider/process/profile semantics still require an independent reader. Success never inferred from a pin.'}

    for req in requirements:
        for row in req['scenarios']:
            ident = row['id']
            if ident in NEW:
                reviewed = notes['new_scenarios'][ident]
                row.update({'scope':'active_selected_component_or_repository_behavior','historical_register_id':None,
                    'implementation_behavior':reviewed['behavior'], 'review_basis':'six new scenario-specific source/test notes',
                    'test_refs':[test(t) for t in reviewed['tests']],
                    'source_anchor_refs':[anchor(p,a) for p,a in reviewed['anchors']],
                    'evidence_refs':reviewed['evidence'], 'automatic_verification_limits':reviewed['limits']})
            else:
                old = prior[ident]
                row.update({'scope':old['scope'],'scope_reason':old['scope_reason'],
                    'historical_register_id':old['historical_register_id'],
                    'implementation_behavior':notes.get('current_behavior_overrides', {}).get(ident, old['implementation_behavior']),
                    'prior_implementation_behavior_historical_only':old['implementation_behavior'],
                    'behavior_text_classification':('current source-specific evidence disposition reviewed' if ident in notes.get('current_behavior_overrides', {}) else 'inherited semantic predicate review with refreshed actual source/assertion pins; historical execution sentences remain prior evidence only'),
                    'prior_pending_and_result_claims_historical_only':{'pending':old['pending'],'execution_status':old['scoped_execution_status']},
                    'test_refs':old['test_refs'],'source_anchor_refs':old['source_anchor_refs'],
                    'historical_evidence_refs':old['evidence_refs'],
                    'current_scoped_evidence_refs':['cpu08','gpu02','science','science_root'],
                    'automatic_verification_limits':old['automatic_verification_limits']})
                changed = [t for t in row['test_refs'] if tests[t]['AST_equal_to_prior_review'] is False and tests[t]['reviewed_exact_AST_delta'] is None]
                row['changed_method_AST_since_prior_review'] = changed
                row['changed_source_boundaries_since_prior_review'] = [key for key in row['source_anchor_refs']
                    if anchors[key]['AST_equal_to_prior_review'] is False or
                       (anchors[key]['AST_equal_to_prior_review'] is None and anchors[key]['raw_equal_to_prior_review'] is False)]
                if changed:
                    gaps.append({'scenario':ident,'type':'changed_method_assertions_need_current_review','tests':changed})
            row['current_scenario_acceptance'] = 'not_granted_by_metadata_generator'
            row['pending'] = ['Actual exact-source hosted and ext4 original outcomes/source/selection/native/profile/closure joins and independent CI review.',
                              'Final scenario-specific conformance review, archive/sync, latest-commit CI and final approval.']
            row['registered_future_execution_remains_unexecuted'] = ('future' in row['scope'] or row['scope'].startswith('conditional'))
            if row['registered_future_execution_remains_unexecuted']:
                row['pending'].append('Original full32/1120/5600/Q4/cloud/service physical campaign remains unexecuted; active safety/interface predicates are not deferred.')
            if ident in notes['manual_rows']:
                row['manual_review_required'] = notes['manual_limit']
            if ident == 'R13/S6':
                row['full_consumer_source_refs'] = consumer_refs
                row['unverified_behavior_gap'] = notes['R13_S6_gap']
                row['pending'].append(notes['R13_S6_gap'])
            row['current_runtime_scope_note'] = notes['current_runtime_note']
    return {'schema_version':1, 'artifact_kind':'decision29_current_conformance_mapping_v1',
        'status':'metadata_and_AST_mapping_requires_independent_conformance_review',
        'active_change':'fix-benchmark-preparations-spec', 'bound_actual_checkout_commit':COMMIT,
        'bound_actual_checkout_root':str(SOURCE),
        'whole_tested_source_binding':('pending_original_CI_and_independent_peer' if any(value['whole_success'] is None for value in ci.values()) else 'original_metadata_joined_requires_independent_CI_peer'), 'measurement_source_commit':MEASUREMENT,
        'requirement_count':20,'scenario_count':118, 'preserved_prior_clause_count':112,
        'historical_original_task_register':tasks, 'historical_original_scenarios':historical_scenarios,
        'original_register_refs':{'tasks':descriptor(legacy_task_ref),'spec':descriptor(legacy_spec_ref)},
        'current_task_states': [{'id':match[1], 'checked':match[0]=='x', 'text':match[2]}
            for match in re.findall(r'^- \[([ x])\] (\d+(?:\.\d+)+) (.+)$',current_tasks,re.M)],
        'requirements':requirements,'tests':tests,'source_anchors':anchors,
        'current_evidence':evidence,'historical_evidence_not_current_authority':historical_evidence,
        'current_CI':ci,'structural_link_gaps':gaps,
        'current_reviewed_notes':notes_ref,'old_mapping_historical_ref':original_ref,
        'publication_ready':False,'component_release_complete':False,'archive_complete':False,
        'merge_performed':False,'user_authorization':binding['finalization']['merge'],
        'finalization':binding['finalization'],
        'limits':['Raw tested ext4 bytes are never equated with dirty Windows CRLF source bytes.',
                  'AST or clause equality identifies preserved predicates; it is not runtime proof or complete scenario coverage.',
                  'Original negative outcomes remain failures. B measurements and focused51 are separate from whole tested-source CI.',
                  'No target imports/tests/Git/contracts/models/engine/reducers/native/guardian commands execute.']}


out = None
owned = False
first = None
mapping = None
fd_before = len(os.listdir('/proc/self/fd'))
try:
    require(sys.version_info[:3] == (3,12,3) and os.name == 'posix', 'pinned POSIX CPython3.12.3 required for comparable AST/hash and custody semantics')
    require(len(sys.argv) == 4, 'usage: generator binding_leaf exact_size exact_SHA256')
    binding_leaf, size, sha = sys.argv[1:]
    require(Path(binding_leaf).name == binding_leaf and re.fullmatch(r'[A-Za-z0-9_.-]+\.json', binding_leaf), 'binding is not an owned leaf')
    require(size.isdecimal() and re.fullmatch(r'[0-9a-f]{64}', sha), 'invalid exact binding descriptor')
    binding, binding_pin = load({'domain':'control','path':str((HERE / binding_leaf).relative_to(CONTROL)),
                                 'size_bytes':int(size),'sha256':sha})
    read_ref({'domain':'control','path':str(Path(__file__).absolute().relative_to(CONTROL))})
    leaf = binding['output_leaf']
    require(re.fullmatch(r'attempt[0-9]{2}', leaf), 'fresh output name is not canonical')
    out = HERE / leaf
    out.mkdir(mode=0o700)
    owned = True
    mapping = build(binding)
    verify_all()
except BaseException as error:
    first = {'type':type(error).__name__,'message':str(error)[:1000],
             'traceback':traceback.format_exc()[-12000:]}
finally:
    inventory = [descriptor(row) for row in holds.values()]
    retire_all()

fd_after = len(os.listdir('/proc/self/fd'))
if close_errors or fd_before != fd_after:
    if first is None:
        first = {'type':'ResourceClosureFailure','message':'independent FD close or numeric FD balance failed'}
outputs = {}
terminal_attempted = False
terminal_ref = None
late = None
try:
    if owned:
        if first is None:
            outputs['mapping'] = publish(out,'mapping.v1.json',mapping)
        outputs['inventory'] = publish(out,'input-custody.v1.json',
            {'files':inventory,'aggregate_bytes_read':total,'ancestor_count':len(ancestors),
             'FD_holds_released':not close_errors,'close_errors':close_errors,
             'fd_before':fd_before,'fd_after':fd_after,'leaf_fullSHA_and_seven_epochs_rechecked':first is None})
        terminal_attempted = True
        terminal_ref = publish(out,'terminal.v1.json',
            {'schema_version':1,'status':'failed' if first else 'metadata_preparation_complete_not_acceptance',
             'first_failure':first,'source_commit':COMMIT,'measurement_source_commit':MEASUREMENT,
             'original_pid':os.getpid(),'original_ppid':os.getppid(),'original_pgid':os.getpgrp(),
             'python_version':sys.version,'python_executable':sys.executable,
             'elapsed_s':(time.monotonic_ns()-START)/1e9,'outputs':outputs,
             'FD_holds_released':not close_errors,'close_errors':close_errors,
             'fd_before':fd_before,'fd_after':fd_after,
             'conformance_accepted':False,'archive_complete':False,'hardware_acceptance':False})
    print(json.dumps({'status':'failed' if first else 'prepared_not_accepted','terminal':terminal_ref,
                      'output_owned':owned,'elapsed_s':(time.monotonic_ns()-START)/1e9}),flush=True)
    if time.monotonic_ns() >= DEADLINE:
        raise TimeoutError('original120s final receipt/flush deadline exceeded')
except BaseException as error:
    late = {'type':type(error).__name__,'message':str(error)[:1000]}
    if owned:
        # No post-deadline hashing, output rewriting or claimed verified terminal.
        companion = {'first_failure':first,'persistence_or_late_failure':late,
                     'terminal_attempted':terminal_attempted,'terminal_ref':terminal_ref,
                     'known_terminal_path':str(out/'terminal.v1.json'),
                     'complete_descriptor_verified':terminal_ref is not None,
                     'elapsed_s':(time.monotonic_ns()-START)/1e9,'accepted':False}
        try:
            with (out/'persistence-or-late-failure.v1.json').open('xb') as stream:
                stream.write((json.dumps(companion,sort_keys=True)+'\n').encode())
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException as companion_error:
            print(json.dumps({'companion_failure':type(companion_error).__name__,
                              'output_owned':owned}),flush=True)
sys.exit(1 if first or late else 0)
