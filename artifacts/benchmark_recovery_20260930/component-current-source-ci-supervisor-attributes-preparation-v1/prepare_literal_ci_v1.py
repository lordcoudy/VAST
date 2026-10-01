"""Prepare literal-only CI helpers; never launch their setup or CI commands."""
import ast
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import time

HERE = Path(__file__).parent
ROOT = HERE.parents[2]
BASE = HERE.parent / 'component-current-source-ci-4cb9-preparation-v1'
SUPERVISOR = HERE.parent / 'component-current-source-ci-supervisor-preparation-v1'
COMMIT = '78b869e4f8bc101413ed00776bd89d1089a8318d'
NEW_ROOT = '/home/s-a-balashov/work/vast-current-source-ci-20261001-supervisor-attributes'
PYTHON = '/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python'
ORIGINALS = {
    'recipe': (BASE / 'recipe.v1.json', 6954, '3cf7baa8a668f96753b1572f798c48d86cc15491359b9bbf1d6193e4819fb9a7'),
    'setup': (BASE / 'setup_original_current_ci_v1.py', 12547, '0469d49fa251540f70db5b35f4c65a80c63c0ffbc79ac0c09344b9f1d1e5f4e0'),
    'setup_capture': (SUPERVISOR / 'capture_original_setup_v1.py', 4849, 'd1bd578609c08f08824d9b9b26d27efb2f8f6fecd49778c6a4d5927d0e2cc86e'),
    'full_capture': (SUPERVISOR / 'capture_original_full_ci_v1.py', 10360, 'd2ccc319ea70f21fa66710697dba2603f63b6508d6c29e69fd4410f997722281'),
}


def epoch(s):
    return [s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns]


def read_pin(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= 1048576
        raw = b''
        while chunk := os.read(fd, 65536):
            raw += chunk
        assert len(raw) == before.st_size and epoch(before) == epoch(os.fstat(fd)) == epoch(path.lstat())
        return raw, {'path': str(path), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'epoch7': epoch(before)}
    finally:
        os.close(fd)


def write_exclusive(name, raw):
    with (HERE / name).open('xb') as stream:
        assert stream.write(raw) == len(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return read_pin(HERE / name)[1]


def transform(raw, substitutions):
    text = raw.decode('utf-8')
    counts = []
    for old, new in substitutions:
        assert old != new and old in text
        counts.append({'old': old, 'new': new, 'occurrences': text.count(old)})
        text = text.replace(old, new)
    result = text.encode('utf-8')
    inverse = text
    for old, new in reversed(substitutions):
        inverse = inverse.replace(new, old)
    assert inverse.encode('utf-8') == raw
    return result, counts


def functions(raw):
    tree = ast.parse(raw)
    return {node.name: ast.dump(node, include_attributes=False) for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}


assert HERE.resolve(strict=True) == HERE
assert os.getuid() == os.getgid() == 1000
original_raw = {}
original_pins = {}
for role, (path, size, sha) in ORIGINALS.items():
    raw, pin = read_pin(path)
    assert pin['size_bytes'] == size and pin['sha256'] == sha
    original_raw[role] = raw
    original_pins[role] = pin

old_recipe = json.loads(original_raw['recipe'])
old_commit = old_recipe['source_commit']
old_root = old_recipe['checkout']
recipe_raw, recipe_changes = transform(original_raw['recipe'], [(old_commit, COMMIT), (old_root, NEW_ROOT)])
recipe = json.loads(recipe_raw)
assert recipe['source_commit'] == COMMIT and recipe['checkout'] == NEW_ROOT
assert recipe['output'] == NEW_ROOT + '-original-output'
assert recipe['benchmark_root_commit_untouched'] == '0ad78d6abdb3c526544a17185af7fe8094716735'
assert recipe['source_pins'] == old_recipe['source_pins'] and len(recipe['source_pins']) == 8
assert recipe['setup_work_limit_s'] == 300 and recipe['setup_cleanup_s'] == 10
assert recipe['stock_original_job_limit_s'] == 5400 and recipe['outer_cleanup_s'] == 10
assert len(recipe['setup_commands']) == 6
assert all(command[:3] == ['/usr/bin/git', '-c', 'core.longpaths=true'] for command in recipe['setup_commands'])
recipe_sha = hashlib.sha256(recipe_raw).hexdigest()
setup_raw, setup_changes = transform(original_raw['setup'], [
    (old_commit, COMMIT),
    ("recipe_pin['size_bytes']==6954", "recipe_pin['size_bytes']==" + str(len(recipe_raw))),
    (ORIGINALS['recipe'][2], recipe_sha),
])
setup_sha = hashlib.sha256(setup_raw).hexdigest()
capture_raw, capture_changes = transform(original_raw['setup_capture'], [
    (str(SUPERVISOR), str(HERE)),
    ("before['size_bytes']==12547", "before['size_bytes']==" + str(len(setup_raw)))
        if len(setup_raw) != 12547 else
        ("before['sha256']=='0951dacf74c17fab49de6799375234c45dacfb778dcc22c7b4c9ae4a861b3b25'", "before['sha256']=='" + setup_sha + "'"),
])
if len(setup_raw) != 12547:
    capture_raw, remaining_changes = transform(capture_raw, [('0951dacf74c17fab49de6799375234c45dacfb778dcc22c7b4c9ae4a861b3b25', setup_sha)])
    capture_changes += remaining_changes
full_raw, full_changes = transform(original_raw['full_capture'], [
    ('/home/s-a-balashov/work/vast-current-source-ci-20261001-supervisor', NEW_ROOT),
])
derived = {'setup': setup_raw, 'setup_capture': capture_raw, 'full_capture': full_raw}
function_counts = {}
for role, raw in derived.items():
    assert functions(raw) == functions(original_raw[role])
    function_counts[role] = len(functions(raw))
    ast.parse(raw)

future = [NEW_ROOT, recipe['output'], str(HERE / 'original-setup-attempt01'), str(HERE / 'original-full-ci-attempt01')]
assert all(not os.path.lexists(path) for path in future)
git = ['/usr/bin/git', '-c', 'core.longpaths=true', '--git-dir=/mnt/e/STUDY/VAST/.git/worktrees/fix-benchmark-preparations-spec', '--work-tree=' + str(ROOT)]
head = subprocess.run(git + ['rev-parse', 'HEAD'], check=True, capture_output=True, timeout=10).stdout.strip().decode('ascii')
assert head == COMMIT
source_pins = {}
source_raw = {}
for relative, expected in recipe['source_pins'].items():
    raw, pin = read_pin(ROOT / relative)
    assert pin['size_bytes'] == expected['size_bytes'] and pin['sha256'] == expected['sha256']
    source_pins[relative] = pin
    source_raw[relative] = raw
batch_argv = git + ['cat-file', '--batch']
batch = subprocess.run(batch_argv, input=b''.join((COMMIT + ':' + relative + '\n').encode('ascii') for relative in source_raw), check=True, capture_output=True, timeout=10)
assert batch.stderr == b''
remaining = batch.stdout
source_commit_objects = {}
for relative, raw in source_raw.items():
    header, remaining = remaining.split(b'\n', 1)
    oid, kind, size = header.split()
    assert kind == b'blob' and int(size) == len(raw) and remaining[:len(raw)] == raw
    assert remaining[len(raw):len(raw) + 1] == b'\n'
    remaining = remaining[len(raw) + 1:]
    source_commit_objects[relative] = oid.decode('ascii')
assert remaining == b''

files = {}
for name, raw in [
    ('recipe.v1.json', recipe_raw),
    ('setup_original_current_ci_v1.py', setup_raw),
    ('capture_original_setup_v1.py', capture_raw),
    ('capture_original_full_ci_v1.py', full_raw),
]:
    files[name] = write_exclusive(name, raw)
for role, (path, _, _) in ORIGINALS.items():
    assert read_pin(path)[1] == original_pins[role]
for relative in source_pins:
    assert read_pin(ROOT / relative)[1] == source_pins[relative]
assert subprocess.run(git + ['rev-parse', 'HEAD'], check=True, capture_output=True, timeout=10).stdout.strip().decode('ascii') == COMMIT
review = {
    'schema_version': 1,
    'artifact_kind': 'vast_current_source_ci_literal_preparation_v1',
    'status': 'prepared_unexecuted_requires_peer_and_original_root_dispatch',
    'source_commit': COMMIT,
    'standing_authorization_record': 'https://github.com/lordcoudy/VAST/pull/2#issuecomment-5922384139',
    'checkout': NEW_ROOT, 'output': recipe['output'],
    'benchmark_root_untouched': recipe['benchmark_root_untouched'],
    'benchmark_root_commit_required': recipe['benchmark_root_commit_untouched'],
    'failed_previous_checkout_retained_untouched': '/home/s-a-balashov/work/vast-current-source-ci-20261001-supervisor',
    'originals': original_pins, 'files': files,
    'changes': {'recipe': recipe_changes, 'setup': setup_changes, 'setup_capture': capture_changes, 'full_capture': full_changes},
    'complete_raw_inverse_equal': True, 'all_original_function_and_class_AST_equal': True,
    'original_function_counts': function_counts,
    'eight_physical_source_pins': source_pins, 'eight_exact_commit_blob_oids': source_commit_objects,
    'source_pins_equal_original_recipe_and_current_commit': True,
    'future_output_namespaces_absent': future,
    'setup_bounds_s': [300, 10], 'full_ci_bounds_s': [5400, 10],
    'original95_metadata_custody_and_full_tracked_raw_byte_prerequisites_preserved': True,
    'ready_setup_argv': [PYTHON, '-I', '-B', str(HERE / 'capture_original_setup_v1.py')],
    'ready_full_ci_argv_only_after_original_successful_setup': [PYTHON, '-I', '-B', str(HERE / 'capture_original_full_ci_v1.py'), COMMIT],
    'actual_setup_dispatch': None, 'actual_setup_terminal': None,
    'actual_ci_dispatch': None, 'actual_ci_terminal': None, 'actual_ci_success': None,
    'limitations': 'Metadata literal preparation only. No new checkout, install, model, engine, namespace/profile, native test, benchmark or CI execution. Existing benchmark root and failed checkout were not modified. Future source/prerequisite/raw Git equality, original process ownership, complete stock CI results and final deadlines must be observed; this document grants no acceptance.',
    'prepared_at_ns': time.time_ns(), 'preparation_read_fds_closed': True,
    'author_generator': read_pin(Path(__file__))[1],
}
pin = write_exclusive('preparation.v1.json', (json.dumps(review, sort_keys=True, indent=2) + '\n').encode('utf-8'))
print(json.dumps({'status': review['status'], 'preparation': pin, 'files': files, 'setup_argv': review['ready_setup_argv'], 'original_function_counts': function_counts}, sort_keys=True))
