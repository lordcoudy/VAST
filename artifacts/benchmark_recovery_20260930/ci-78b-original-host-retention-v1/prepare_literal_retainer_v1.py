from pathlib import Path
import ast
import hashlib
import json

HERE = Path(__file__).parent
OLD = HERE.parent / 'ci-e897-original-host-retention-v1/retain_originals_v1.py'
raw = OLD.read_bytes()
original = raw.decode()
pairs = [
    ('ci-e897-original-host-retention-v1', 'ci-78b-original-host-retention-v1'),
    ('RUN=36794448836', 'RUN=36797383777'),
    ('CPU=110154542231', 'CPU=110163826615'),
    ('HOST=110154541899', 'HOST=110163826390'),
    ('e897514dbefe3015756995d05f924aa44dd39552', '78b869e4f8bc101413ed00776bd89d1089a8318d'),
]
current = original
for old, new in pairs:
    assert current.count(old) == 1 and new not in current
    current = current.replace(old, new)
inverse = current
for old, new in reversed(pairs):
    inverse = inverse.replace(new, old)
assert inverse == original
functions = lambda value: [ast.dump(n, include_attributes=False) for n in ast.walk(ast.parse(value)) if isinstance(n, (ast.FunctionDef, ast.ClassDef))]
assert functions(current) == functions(original)
output = current.encode()
with (HERE / 'retain_originals_v1.py').open('xb') as stream:
    assert stream.write(output) == len(output)
value = {
    'scope': 'Read-only retention of original completed hosted run33; no workflow action or benchmark acceptance',
    'original_source_size_bytes': len(raw),
    'original_source_sha256': hashlib.sha256(raw).hexdigest(),
    'prepared_size_bytes': len(output),
    'prepared_sha256': hashlib.sha256(output).hexdigest(),
    'raw_inverse_equal': True,
    'all_function_class_AST_equal': True,
    'work_s': 180,
    'source_commit': '78b869e4f8bc101413ed00776bd89d1089a8318d',
    'original_run_id': 36797383777,
    'credentials_and_signed_redirects_memory_only': True,
    'actual_retention_pending': True,
}
encoded = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
with (HERE / 'literal-preparation.v1.json').open('xb') as stream:
    assert stream.write(encoded) == len(encoded)
print(json.dumps(value))
