"""Stage this finite reviewed checkpoint only; retain original artifact bytes."""
from pathlib import Path
import hashlib, json, subprocess

root = Path.cwd()
git = ['git', '-c', 'core.longpaths=true']
base = 'artifacts/benchmark_recovery_20260930/'
assert subprocess.check_output(git + ['rev-parse', 'HEAD'], text=True).strip() == 'a3e976d02e19e714232bc78a4da3e72c99bb8cde'
assert not subprocess.check_output(git + ['diff', '--cached', '--name-only'])
sources = {'scripts/checkpoint_gstreamer_publication_runtime_v3.py': 'c81e40d04871854a0ca49c1124543cedc5c877a12e045f4149ba922abe29750e',
           'tests/test_checkpoint_gstreamer_custom_publication_runtime_v3.py': 'f59410fd2af9ecd42d9740323b93f0efd0f5c4421e3503be70f1438aa9dc1fe8'}
reviews = {'component-host-image-binding-independent-review-v1/review.v1.json': '7b5cadf302091f91097a1ed8f830fb8daf74104279d21c2825f0bb5bd3fa877b',
           'component-host-image-binding-independent-review-v1/focused-test-supplement.v1.json': '23785574f1760ec3b906fd9055e4f20f27d15404cee71ac2f32cd8042cae80db'}
for path, digest in sources.items():
    assert hashlib.sha256((root / path).read_bytes()).hexdigest() == digest, path
for path, digest in reviews.items():
    assert hashlib.sha256((root / base / path).read_bytes()).hexdigest() == digest, path
owned = list(sources) + ['BENCHMARK_RECOVERY_PLAN.md', base + 'renew_selected_host_image_binding_v1.py',
                        base + 'stage_selected_image_host_checkpoint_v1.py',
                        'artifacts/gstreamer_component_release_20260930_a3e976d0/host/execution-code-closure.v1.json']
for directory in ('selected-gstreamer-image-preparation-v1', 'selected-gstreamer-build-a3e976d0-v1',
                  'selected-gstreamer-packaged-preparation-v1', 'selected-gstreamer-packaged-a3e976d0-v1',
                  'component-selected-host-preparation-v1', 'component-selected-input-readonly-preparation-v1',
                  'component-host-image-binding-renewal-v1', 'component-host-image-binding-renewal-v2',
                  'component-host-image-binding-renewal-focused-v1', 'component-host-image-binding-independent-review-v1',
                  'ci-followup-original-retention-v1', 'ci-a3-original-retention-v1'):
    paths = sorted(p for p in (root / base / directory).rglob('*') if p.is_file()
                   and '__pycache__' not in p.parts and p.suffix != '.pyc')
    assert paths, directory
    owned.extend(p.relative_to(root).as_posix() for p in paths)
assert len(owned) == len(set(owned))
physical = {p: (root / p).read_bytes() for p in owned}
subprocess.run(git + ['add', '-f', '--', *owned], check=True)
def blobs(paths):
    raw = subprocess.run(git + ['cat-file', '--batch'], input=''.join(':' + p + '\n' for p in paths).encode(), stdout=subprocess.PIPE, check=True).stdout
    cursor, result = 0, {}
    for path in paths:
        end = raw.index(b'\n', cursor); header = raw[cursor:end].split()
        assert len(header) == 3 and header[1] == b'blob', (path, header)
        size = int(header[2]); cursor = end + 1
        result[path] = raw[cursor:cursor + size]; cursor += size
        assert raw[cursor:cursor + 1] == b'\n'; cursor += 1
    assert cursor == len(raw)
    return result
carriers = []
for path, staged in blobs(owned).items():
    if staged != physical[path]:
        assert path.startswith('artifacts/') and path not in sources, path
        blob = subprocess.check_output(git + ['hash-object', '-w', '--stdin'], input=physical[path]).decode().strip()
        subprocess.run(git + ['update-index', '--add', '--cacheinfo', '100644,' + blob + ',' + path], check=True)
        carriers.append(path)
report = base + 'selected-image-host-checkpoint-freeze.v1.json'
assert not (root / report).exists()
data = {'previous_head': 'a3e976d02e19e714232bc78a4da3e72c99bb8cde', 'reviewed_source_hashes': sources,
        'independent_reviews': reviews, 'owned_files': {p: {'size_bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest()} for p,b in physical.items()},
        'unfiltered_original_artifact_imports': carriers, 'hardware_acceptance': False, 'full_ci_acceptance': False,
        'historical_host_closure_v1_ineligible_after_renewal': True, 'unrelated_dirt_preserved': True}
(root / report).write_bytes((json.dumps(data, sort_keys=True, separators=(',', ':')) + '\n').encode())
subprocess.run(git + ['add', '-f', '--', report], check=True)
owned.append(report); physical[report] = (root / report).read_bytes()
assert set(subprocess.check_output(git + ['diff', '--cached', '--name-only'], text=True).splitlines()) == set(owned)
assert blobs(owned) == physical
subprocess.run(git + ['diff', '--cached', '--check', '--', *sources, 'BENCHMARK_RECOVERY_PLAN.md', base + 'stage_selected_image_host_checkpoint_v1.py'], check=True)
print(json.dumps({'owned_paths': len(owned), 'reviewed_sources': len(sources), 'physical_index_equal': True, 'unfiltered_original_artifacts': carriers}))
