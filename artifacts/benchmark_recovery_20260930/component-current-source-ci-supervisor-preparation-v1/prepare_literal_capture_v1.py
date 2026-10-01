from pathlib import Path
import ast
import hashlib
import json
HERE = Path(__file__).parent
source_record = HERE.parent / 'component-current-source-ci-4cb9-preparation-v1/original-setup.capture-launch.v1.json'
original = json.loads(source_record.read_bytes())['capture_owner']['argv'][-1]
assert original.startswith('import hashlib,json,os,signal,stat,subprocess,time\n')
old_name = 'component-current-source-ci-4cb9-preparation-v1'
new_name = 'component-current-source-ci-supervisor-preparation-v1'
old_sha = '0469d49fa251540f70db5b35f4c65a80c63c0ffbc79ac0c09344b9f1d1e5f4e0'
new_sha = '0951dacf74c17fab49de6799375234c45dacfb778dcc22c7b4c9ae4a861b3b25'
prepared = original.replace(old_name, new_name).replace(old_sha, new_sha)
assert prepared.replace(new_name, old_name).replace(new_sha, old_sha) == original
functions = lambda s: [ast.dump(n, include_attributes=False) for n in ast.parse(s).body if isinstance(n, (ast.FunctionDef, ast.ClassDef))]
assert functions(original) == functions(prepared)
raw = prepared.encode()
path = HERE / 'capture_original_setup_v1.py'
with path.open('xb') as stream:
    assert stream.write(raw) == len(raw)
value = {'scope': 'prepared capture only, exact literal adaptation of authentic closed4cb setup capture',
         'source_record': str(source_record), 'original_source_sha256': hashlib.sha256(original.encode()).hexdigest(),
         'prepared_source': str(path), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
         'full_inverse_equal': True, 'all_functions_AST_equal': True, 'work_s': 300, 'cleanup_s': 10,
         'execution_performed': False}
with (HERE / 'capture-literal-preparation.v1.json').open('x') as stream:
    json.dump(value, stream, sort_keys=True, indent=2)
    stream.write('\n')
print(json.dumps(value))
