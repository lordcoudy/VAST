"""Prepare an unexecuted literal-only D capture; never import or run a target."""
import ast
import difflib
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time

HERE = Path(__file__).resolve().parent
CONTROL = HERE.parents[2]
BASE = CONTROL / 'artifacts/benchmark_recovery_20260930'
OLD = BASE / 'decision29-successor-ci-D-preparation-v1'
COMMIT = '3c025b29b3c1d5275c2ec693410e4b83700583de'
ROOT = '/home/s-a-balashov/work/vast-current-source-ci-20261003-decision29-D'
OLD_RESULT = ROOT + '-original-output'
NEW_RESULT = ROOT + '-prerequisite-original-output'
START = time.monotonic()
PINS = {}

def epoch(s):
    return [s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_size, s.st_mtime_ns, s.st_ctime_ns]

def read(p):
    assert time.monotonic() - START < 120
    fd = os.open(p, os.O_RDONLY | getattr(os, 'O_BINARY', 0))
    try:
        s = os.fstat(fd)
        assert stat.S_ISREG(s.st_mode) and s.st_nlink == 1 and s.st_size <= 16 * 1024 * 1024
        assert epoch(s) == epoch(p.lstat())
        raw = b''
        while b := os.read(fd, 65536):
            assert time.monotonic() - START < 120 and len(raw) + len(b) <= s.st_size
            raw += b
        assert len(raw) == s.st_size and epoch(s) == epoch(os.fstat(fd)) == epoch(p.lstat())
        value = {'path': str(p), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
                 'authoring_view_epoch7': epoch(s)}
        PINS[p] = (fd, value)
        return raw, value
    except BaseException:
        os.close(fd)
        raise

def save(name, raw):
    assert time.monotonic() - START < 120
    p = HERE / name
    with p.open('xb') as f:
        assert f.write(raw) == len(raw)
        f.flush()
        os.fsync(f.fileno())
    return {'path': str(p), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

def functions(raw):
    return {n.name: ast.dump(n, include_attributes=False) for n in ast.parse(raw).body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}

before = {}
after = []
close_errors = []
try:
    capture, capture_pin = read(OLD / 'capture_original_full_ci_v1.py')
    recipe, recipe_pin = read(OLD / 'recipe.bound.v1.json')
    assert capture_pin['size_bytes'] == 12433 and capture_pin['sha256'] == 'b41ab243053aea3be149f01801490e84623fa11efedcf0e706f2111090769b97'
    assert recipe_pin['size_bytes'] == 11220 and recipe_pin['sha256'] == 'e8df0e735c27bd282eee9692144fb0e42ab7491259bedb2626e1714fe64865c5'
    old_json = json.loads(recipe)
    assert old_json['source_commit'] == COMMIT and old_json['checkout'] == ROOT
    pairs = [(b"OUT = HERE / 'original-full-ci-attempt01'", b"OUT = HERE / 'original-full-ci-prerequisite-attempt01'"),
             (OLD_RESULT.encode(), NEW_RESULT.encode())]
    current_capture = capture
    for a, b in pairs:
        assert current_capture.count(a) == 1
        current_capture = current_capture.replace(a, b)
    inverse = current_capture
    for a, b in reversed(pairs):
        assert inverse.count(b) == 1
        inverse = inverse.replace(b, a)
    assert inverse == capture and functions(capture) == functions(current_capture)
    assert recipe.count(OLD_RESULT.encode()) == 2
    current_recipe = recipe.replace(OLD_RESULT.encode(), NEW_RESULT.encode())
    assert current_recipe.replace(NEW_RESULT.encode(), OLD_RESULT.encode()) == recipe
    new_json = json.loads(current_recipe)
    assert new_json['output'] == NEW_RESULT and new_json['stock_cli_argv'][7] == NEW_RESULT
    assert new_json['setup_commands'] == old_json['setup_commands']
    assert new_json['source_pins'] == old_json['source_pins'] and new_json['stock_checks'] == old_json['stock_checks']
    before['capture'] = save('accepted-capture.before.raw', capture)
    before['recipe'] = save('accepted-recipe.before.raw', recipe)
    capture_out = save('capture_original_full_ci_v1.py', current_capture)
    recipe_out = save('recipe.bound.v1.json', current_recipe)
    diff = ''.join(difflib.unified_diff(capture.decode().splitlines(True), current_capture.decode().splitlines(True),
                                    fromfile='accepted-D/capture_original_full_ci_v1.py',
                                    tofile='prerequisite-prepared/capture_original_full_ci_v1.py'))
    diff += ''.join(difflib.unified_diff(recipe.decode().splitlines(True), current_recipe.decode().splitlines(True),
                                      fromfile='accepted-D/recipe.bound.v1.json',
                                      tofile='prerequisite-prepared/recipe.bound.v1.json'))
    diff_out = save('literal-only.delta.v1.patch', diff.encode())
    references = {}
    for key, rel in {
        'original_D_setup': 'decision29-successor-ci-D-preparation-v1/original-setup-attempt01/execution.v1.json',
        'original_D_tracked_raw': 'decision29-successor-ci-D-preparation-v1/original-setup-attempt01/tracked-raw-source.v1.json',
        'original_post_D_setup95_audit': 'decision29-current95-post-D-setup-audit-preparation-v1/original-audit-attempt01/review.v1.json',
        'cache_copy_review': 'decision29-ext4-asset-cache-copy-actual-review-v1/review.v1.json',
        'stock_existing_eight_review': 'decision29-ext4-asset-cache-stock-reuse-review-v1/review.v1.json',
        'closed_failed_D_review': 'decision29-local-ci-D-original-review-preparation-v1/original-review-attempt01/review.v1.json',
        'failed_D_original_terminal': 'decision29-successor-ci-D-preparation-v1/original-full-ci-attempt01/terminal.v1.json',
    }.items():
        raw, value = read(BASE / rel)
        references[key] = value
        if key == 'closed_failed_D_review':
            failure = json.loads(raw)
        if key == 'original_D_setup':
            setup = json.loads(raw)
    assert setup['source_commit'] == COMMIT and len(setup['commands']) == 14
    assert setup['raw_committed_bytes_equal'] is True and setup['tracked_count'] == 5577
    assert failure['original_full_CI_disposition'] == 'FAILED' and failure['mandatory_local_CI_pass'] is False
    assert failure['facts']['actual_counts'] == {'deferred_integration': 9, 'discovered': 3001, 'error': 0,
                                               'failure': 0, 'selected': 2992, 'skip': 88, 'success': 2904}
    test_path = Path('//wsl.localhost/Ubuntu/home/s-a-balashov/work/vast-current-source-ci-20261003-decision29-D/tests/test_backend_publication_output_transaction_production_v3.py')
    test_raw, test_pin = read(test_path)
    assert test_pin['sha256'] == 'f78c2fa070e672f3777aca28f5d5043a19fca63987afa5fd8300d1582334812d'
    assert b'canonical WSL publication venv bind is not mounted' in test_raw
    references['actual_D_runtime_bind_test_source'] = test_pin
    preparation = {
        'schema_version': 1, 'status': 'prepared_unexecuted_requires_independent_source_review_and_prerequisites',
        'author': '/root/adversarial_review', 'source_commit': COMMIT, 'checkout': ROOT,
        'originals_preserved': True, 'preserved_before': before, 'accepted_capture': capture_pin, 'accepted_recipe': recipe_pin,
        'prepared_capture': capture_out, 'prepared_recipe': recipe_out, 'literal_diff': diff_out,
        'capture_literal_pairs': [[a.decode(), b.decode()] for a, b in pairs],
        'capture_byte_inverse_exact': True, 'all_eight_function_ASTs_identical': True,
        'unchanged_function_names': list(functions(capture)),
        'recipe_byte_inverse_exact': True, 'recipe_only_changed_literal': [OLD_RESULT, NEW_RESULT],
        'setup_command_arrays_all_stock_checks_source_pins_and_other_recipe_fields_unchanged': True,
        'original_setup_14_commands_passed_reference_only_not_reexecuted': references['original_D_setup'],
        'limits': {'original_job_s': 5400, 'original_cleanup_s': 10, 'channel_bytes_each': 4194304,
                   'held_capture_source_leaf_max_bytes': 1048576},
        'original_stock_argv_unchanged_except_fresh_output': new_json['stock_cli_argv'],
        'capture_cli_argv_prepared_not_executed': [new_json['python'], '-I', '-B',
            str(capture_out['path']).replace('E:\\', '/mnt/e/').replace('\\', '/'), COMMIT,
            str(recipe_out['size_bytes']), recipe_out['sha256']],
        'fresh_capture_output': 'original-full-ci-prerequisite-attempt01', 'fresh_stock_result': NEW_RESULT,
        'fresh_WSL_namespaces_absence_observation': None,
        'closed_evidence_references': references,
        'failed_original_disposition': failure['original_full_CI_disposition'],
        'failed_original_counts': failure['facts']['actual_counts'],
        'failed_original_skip': failure['facts']['unapproved_original_skip'],
        'missing_prerequisite': {
            'source_runtime_root': '/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1',
            'project_runtime_mount': ROOT + '/.publication-runtime/full-publication-cp312-v1',
            'required_entry': ROOT + '/.publication-runtime/full-publication-cp312-v1/bin/python',
            'stock_contract_functions': ['build_production_runtime_bind_mount_contract_v3', 'preflight_production_runtime_bind_mount_v3'],
            'actual_D_test_method': 'test_backend_publication_output_transaction_production_v3.BackendPublicationOutputTransactionProductionV3Tests.test_canonical_wsl_venv_requires_plain_copied_python',
            'source_lines': [1088, 1124], 'physical_readonly_bind_setup_review': None,
            'physical_mount_observed_by_author': False},
        'required_before_root_one_original_CI_grant': [
            'Independent exact-source review of this capture/recipe; preserve failed original D output.',
            'Separate approved stock read-only runtime bind setup and independently retained actual physical contract review.',
            'One fresh 95 full SHA/size plus original Linux seven-epoch audit after prerequisite setup; verify all handles/processes closed.',
            'Verify canonical D root, exact unchanged committed raw source D, interpreter and source95 epochs, and absent fresh output names.',
            'Root exact original execution grant binds this source/recipe and actual prerequisite/audit refs. No cloned setup, test selection, skip reasons or source changes.'
        ],
        'count_semantics': '88 is the unchanged allowed skip declaration set, not a required observed skip count. The mounted existing test must execute its original assertions; no expected count is forced.',
        'inherited_recipe_setup_fields': 'The byte-exact inherited recipe describes the original initial setup contract. Its setup arrays/null clone fields are historical source-preparation fields; no clone/setup command is dispatched by this capture. Actual original setup refs above do not prove the missing bind or the required fresh95 audit.',
        'future_original_owner': None, 'future_original_terminal': None, 'future_CI_success': None,
        'hardware_acceptance': False, 'release_acceptance': False, 'generator_or_capture_executed': False,
        'source_test_CI_model_engine_native_mount_or_Git_operation_performed': False,
        'authoring_interpreter': sys.version, 'epoch_view_limitation': 'Authoring-view metadata is not the original Linux source95 epoch authority.'
    }
finally:
    for p, (fd, value) in PINS.items():
        try:
            assert epoch(os.fstat(fd)) == epoch(p.lstat()) == value['authoring_view_epoch7']
            after.append(value)
        except BaseException as e:
            close_errors.append({'path': str(p), 'type': type(e).__name__, 'message': str(e)[:2048]})
        finally:
            try:
                os.close(fd)
            except BaseException as e:
                close_errors.append({'path': str(p), 'type': type(e).__name__, 'message': str(e)[:2048]})
assert not close_errors and len(after) == len(PINS)
preparation['author_input_handles_released'] = True
preparation['author_before_after_epoch_identity_equal'] = True
preparation['author_elapsed_s_before_receipt'] = time.monotonic() - START
pin = save('preparation.v1.json', (json.dumps(preparation, sort_keys=True, indent=2) + '\n').encode())
assert time.monotonic() - START < 120
print(json.dumps({'status': 'prepared_unexecuted', 'capture': capture_out, 'recipe': recipe_out, 'preparation': pin,
                  'author_input_handles_released': True, 'author_elapsed_s': time.monotonic() - START}))
