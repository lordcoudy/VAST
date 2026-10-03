"""Static byte/AST author proof only; never execute/import the observer."""
import ast
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

def pin(path, data=None):
    data = path.read_bytes() if data is None else data
    return {'path': str(path), 'size_bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}

def write_new(path, data):
    with path.open('xb') as stream:
        assert stream.write(data) == len(data)

old_path = HERE / 'audit_actual95_post_setup_v1.py'
old = old_path.read_bytes()
old_prep_path = HERE / 'preparation.v1.json'
old_prep = old_prep_path.read_bytes()
assert pin(old_path, old)['sha256'] == 'f2b09d5b8336b9276bfb4da459bbcb7fc1e8cf18b77199f48eb8b56916e21eeb'
assert pin(old_prep_path, old_prep)['sha256'] == 'e35eee4aff086dbee427bc4ad2a3570602ceb718d949e8dd592176adbdec80b2'
needle = b"    print(json.dumps({'review':ref,'first_error':first,'reviewable':first is None,'fd_before':fd_before,'fd_final':fd_final,'elapsed_s':time.monotonic()-START}),flush=True)\n"
replacement = b"""    try:print(json.dumps({'review':ref,'first_error':first,'reviewable':first is None,'fd_before':fd_before,'fd_final':fd_final,'elapsed_s':time.monotonic()-START}),flush=True)
    except BaseException as exc:
        was_clean=first is None;fail('final-stdout-write',exc)
        if was_clean and output_owned:
            try:save('failure-companion.v1.json',{'reviewable':False,'first_error':first,'original_review':ref},65536)
            except BaseException as companion_error:fail('final-stdout-failure-companion',companion_error)
"""
assert old.count(needle) == 1
new = old.replace(needle, replacement)
assert new.count(replacement) == 1 and new.replace(replacement, needle) == old
old_tree = ast.parse(old, filename=str(old_path))
new_path = HERE / 'audit_actual95_post_setup_v2.py'
new_tree = ast.parse(new, filename=str(new_path))
old_funcs = {n.name: ast.dump(n, include_attributes=False) for n in old_tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
new_funcs = {n.name: ast.dump(n, include_attributes=False) for n in new_tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
assert len(old_funcs) == 12 and old_funcs == new_funcs
before = HERE / 'before-v2'
before.mkdir()
write_new(before / 'audit_actual95_post_setup_v1.py.raw', old)
write_new(before / 'preparation.v1.json.raw', old_prep)
write_new(new_path, new)
prep = json.loads(old_prep)
prep['source'] = pin(new_path, new)
prep['source']['path'] = 'artifacts/benchmark_recovery_20260930/decision29-current95-post-setup-audit-preparation-v1/audit_actual95_post_setup_v2.py'
prep['future_dispatch_only'][-1] = prep['future_dispatch_only'][-1].replace('audit_actual95_post_setup_v1.py', 'audit_actual95_post_setup_v2.py')
prep['preserved_v1_source'] = pin(old_path, old)
prep['preserved_v1_preparation'] = pin(old_prep_path, old_prep)
prep['v2_narrow_change'] = 'Guard the final summary stdout write with the existing sticky first-error and exclusive bounded failure-companion attempt. All12 module function ASTs and every other source byte are unchanged by the exact inverse.'
prep['v1_review_limit'] = 'V1 is preserved and unexecuted. A late stdout exception would produce nonzero but lack a retained first-cause companion; v2 is the proposed dispatch source.'
prep['source_guard_details'][3] = 'The first failure is sticky. Every close is attempted despite later errors/deadlines. FD baseline is observed before/after closes, final receipt and stdout. Receipt/late/stdout failure attempts an exclusive bounded nonauthorizing companion; nonzero prevents acceptance even if companion publication fails.'
prep['status'] = 'source_only_v2_prepared_unexecuted_after_genuine_setup'
prep_raw = json.dumps(prep, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
prep_path = HERE / 'preparation.v2.json'
write_new(prep_path, prep_raw)
proof = {
    'schema_version': 1,
    'author': '/root/decision28_source_peer',
    'author_handles_released': True,
    'old_source': pin(old_path, old),
    'old_preparation': pin(old_prep_path, old_prep),
    'source': pin(new_path, new),
    'preparation': pin(prep_path, prep_raw),
    'module_functions_ast_unchanged': list(old_funcs),
    'module_function_count': len(old_funcs),
    'exact_forward_and_inverse': True,
    'replacement_occurrences': 1,
    'new_target_functions': [],
    'target_imported_compiled_executed': False,
    'future_owner': None,
    'future_outcome': None,
    'scope': prep['v2_narrow_change'],
    'independent_root_source_review_required_before_execution': True,
}
proof_raw = json.dumps(proof, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
proof_path = HERE / 'author.v2.json'
write_new(proof_path, proof_raw)
print(json.dumps({'source': pin(new_path, new), 'preparation': pin(prep_path, prep_raw), 'author': pin(proof_path, proof_raw)}, sort_keys=True))
