"""Stage only closed, reviewed host-session and diagnostic evidence."""
from pathlib import Path
import hashlib
import json
import subprocess

root = Path.cwd()
base = 'artifacts/benchmark_recovery_20260930/'
git = ['git', '-c', 'core.longpaths=true']
old = '6358c42cf1b969fb7ac2aa7be51929c3da46b9af'
assert subprocess.check_output(git + ['rev-parse', 'HEAD'], text=True).strip() == old
assert not subprocess.check_output(git + ['diff', '--cached', '--name-only'])
checks = {
    'component-held-session-implementation-v1/author-review.v1.json': 'fdde3a22d521366d8cc2ab4eb067b63bcf54bf9a8b511de2c8f5effd46aee7f0',
    'component-held-session-independent-review-v1/review.v1.json': 'b8623147480662bd30fd6b721692d95a78c7930e8c6a6a88d7cd47dfd98089e8',
    'component-held-session-independent-review-v1/preparation-review.v2.json': 'f1b8f5d077b77505ec3f90f80e391ad398ec847127b4681046d18926a7c057e2',
    'component-held-session-implementation-v1/attempt-04-focused/execution.json': 'a73811714efb59491f2ac5acf2cd37002e7ba0ecc42e84269dde384a1383ae15',
    'component-held-session-host-image-scope-v1/review.v1.json': '3d401843d9e788ff76f0b2140fef8878d0f694529cc0406e076369cab91ae8e9',
    'ci-namespace-denial-capture-independent-review-v1/review.v1.json': 'a05acb095bf0b00379a6107157de874a9fae3857417b215615fda68adbc5c552',
    'component-cpu04-sidecar-independent-reduction-v1/scientific-report.v1.json': '218b23bf7f0484ac9432f945b8839fff386f1865954308682e8c8d173f0875cf',
}
for path, expected in checks.items():
    assert hashlib.sha256((root / base / path).read_bytes()).hexdigest() == expected, path
review = json.loads((root / base / 'component-held-session-independent-review-v1/review.v1.json').read_bytes())
assert review['disposition'] == 'approved_source_review'
owned = []
for row in review['sources']:
    raw = (root / row['path']).read_bytes()
    assert len(raw) == row['size_bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256'], row['path']
    owned.append(row['path'])
assert len(owned) == 6
for path, expected in {
    'scripts/ci_namespace_diagnostic_v1.py': 'c27e5fde456c0448cee9e7ea20a5861e66e5f0636c56fe207995993549dbcff8',
    'tests/test_ci_namespace_diagnostic_v1.py': 'fe07668ac4b3c2f1f7c1af8c668b0d86e1b74d3f0d1cfc085074050ab6010832',
    base + 'capture_selected_host_closure_v6.py': 'a05b1c72e6188dac057ea7104e2ffe2cc83cf8f596ab1b1675b10f70a09314db',
    base + 'selected-gstreamer-cpu05-controller-preparation-v1/run_original_cpu_component_pair_v1.py': 'a6245ffaef0f197fa561dacdd173aa45a1a35b84e4beda1fbe063ddcb1d19c13',
    base + 'selected-gstreamer-gpu01-controller-preparation-v2/run_original_gpu_component_pair_v1.py': '095de25ad80f0d2e38da3cbb2cbd5df0e84e51df4f55d0dccb07781b71e6a707',
}.items():
    assert hashlib.sha256((root / path).read_bytes()).hexdigest() == expected, path
    owned.append(path)
owned += ['BENCHMARK_RECOVERY_PLAN.md', 'openspec/changes/fix-benchmark-preparations-spec/tasks.md',
          base + 'verify_component_host_only_image_scope_v1.py',
          base + 'stage_component_held_session_checkpoint_v1.py']
for directory in ('component-held-session-implementation-v1', 'component-held-session-independent-review-v1',
                  'component-held-session-host-image-scope-v1', 'ci-namespace-denial-capture-repair-v1',
                  'ci-namespace-denial-capture-independent-review-v1', 'ci-2f409-readonly-failure-diagnosis-v1',
                  'component-cpu04-sidecar-independent-reduction-v1'):
    owned += [p.relative_to(root).as_posix() for p in sorted((root / base / directory).rglob('*'))
              if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc']
owned = sorted(set(owned))
physical = {p: (root / p).read_bytes() for p in owned}
subprocess.run(git + ['add', '-f', '--', *owned], check=True)

def blobs():
    raw = subprocess.check_output(git + ['cat-file', '--batch'], input=''.join(':' + p + '\n' for p in owned).encode())
    position, result = 0, {}
    for path in owned:
        end = raw.index(b'\n', position)
        header = raw[position:end].split()
        assert len(header) == 3 and header[1] == b'blob'
        count = int(header[2])
        position = end + 1
        result[path] = raw[position:position + count]
        position += count
        assert raw[position:position + 1] == b'\n'
        position += 1
    assert position == len(raw)
    return result

carriers = []
for path, raw in blobs().items():
    if raw != physical[path]:
        assert path.startswith('artifacts/'), path
        oid = subprocess.check_output(git + ['hash-object', '-w', '--stdin'], input=physical[path]).decode().strip()
        subprocess.run(git + ['update-index', '--add', '--cacheinfo', '100644,' + oid + ',' + path], check=True)
        carriers.append(path)
assert blobs() == physical
changed = set(subprocess.check_output(git + ['diff', '--cached', '--name-only'], text=True).splitlines())
assert changed.issubset(owned)
source_paths = [p for p in owned if not p.startswith('artifacts/')] + [base + 'stage_component_held_session_checkpoint_v1.py']
subprocess.run(git + ['-c', 'core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol',
                     'diff', '--cached', '--check', '--', *source_paths], check=True)
freeze = base + 'component-held-session-checkpoint-freeze.v1.json'
assert not (root / freeze).exists()
(root / freeze).write_bytes((json.dumps({'previous_head': old, 'checks': checks,
    'owned_files': {p: {'size_bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest()} for p, b in physical.items()},
    'changed_paths': sorted(changed), 'unfiltered_artifacts': carriers, 'physical_index_equal': True,
    'fresh_host_v6_executed': False, 'fresh_cpu_gpu_accepted': False, 'full_ci_accepted': False,
    'historical_cpu04_status': 'failed', 'unrelated_dirty_files_preserved': True},
    sort_keys=True, separators=(',', ':')) + '\n').encode())
subprocess.run(git + ['add', '-f', '--', freeze], check=True)
print(json.dumps({'owned_files': len(owned) + 1, 'changed_files': len(changed) + 1, 'physical_index_equal': True}))
