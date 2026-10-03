"""Prepare an exact later CI checkout recipe from reviewed4cb source; no execution."""
from pathlib import Path
import ast
import hashlib
import json
import sys

HERE = Path(__file__).parent
OLD = HERE.parent / 'component-current-source-ci-4cb9-preparation-v1'
assert len(sys.argv) == 2
commit = sys.argv[1]
assert len(commit) == 40 and all(c in '0123456789abcdef' for c in commit)
original_recipe = (OLD / 'recipe.v1.json').read_bytes()
assert len(original_recipe) == 6954 and hashlib.sha256(original_recipe).hexdigest() == '3cf7baa8a668f96753b1572f798c48d86cc15491359b9bbf1d6193e4819fb9a7'
recipe = json.loads(original_recipe)
old_commit = recipe['source_commit']
old_root = recipe['checkout']
new_root = '/home/s-a-balashov/work/vast-current-source-ci-20261001-supervisor'
recipe_text = original_recipe.decode().replace(old_commit, commit).replace(old_root, new_root)
new_recipe = json.loads(recipe_text)
assert new_recipe['source_commit'] == commit
assert new_recipe['benchmark_root_commit_untouched'] == '0ad78d6abdb3c526544a17185af7fe8094716735'
raw_recipe = recipe_text.encode()
raw_setup = (OLD / 'setup_original_current_ci_v1.py').read_bytes()
assert len(raw_setup) == 12547 and hashlib.sha256(raw_setup).hexdigest() == '0469d49fa251540f70db5b35f4c65a80c63c0ffbc79ac0c09344b9f1d1e5f4e0'
setup_text = raw_setup.decode().replace(old_commit, commit)
setup_text = setup_text.replace("recipe_pin['size_bytes']==6954", "recipe_pin['size_bytes']==" + str(len(raw_recipe)))
setup_text = setup_text.replace('3cf7baa8a668f96753b1572f798c48d86cc15491359b9bbf1d6193e4819fb9a7', hashlib.sha256(raw_recipe).hexdigest())
original_functions = [ast.dump(n, include_attributes=False) for n in ast.parse(raw_setup).body if isinstance(n, (ast.FunctionDef, ast.ClassDef))]
new_functions = [ast.dump(n, include_attributes=False) for n in ast.parse(setup_text).body if isinstance(n, (ast.FunctionDef, ast.ClassDef))]
assert original_functions == new_functions
rows = []
for name, raw in [('recipe.v1.json', raw_recipe), ('setup_original_current_ci_v1.py', setup_text.encode())]:
    with (HERE / name).open('xb') as stream:
        assert stream.write(raw) == len(raw)
    rows.append({'name': name, 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
value = {
    'scope': 'prepared exact CI checkout only; run before selected benchmark root renewal',
    'status': 'prepared_unexecuted', 'source_commit': commit,
    'benchmark_root_commit_required_still_0ad': True,
    'original95_metadata_holds_preserved': True, 'all_original_functions_AST_equal': True,
    'literal_changes_only': ['new CI source commit', 'fresh checkout/output namespace', 'recipe integrity pin'],
    'files': rows, 'setup_bounds_s': [300, 10], 'full_ci_bounds_s': [5400, 10],
    'hardware_or_ci_acceptance': False,
}
raw = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
with (HERE / 'literal-preparation.v1.json').open('xb') as stream:
    assert stream.write(raw) == len(raw)
print(json.dumps(value))
