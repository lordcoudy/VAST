"""Freeze exact reviewed planning and closed import/CPU04 facts only."""
from pathlib import Path
import hashlib, json, subprocess
root = Path.cwd()
base = 'artifacts/benchmark_recovery_20260930/'
git = ['git', '-c', 'core.longpaths=true']
old = '2f40946589254b3698eebedadb4b9d578f297deb'
assert subprocess.check_output(git + ['rev-parse', 'HEAD'], text=True).strip() == old
assert not subprocess.check_output(git + ['diff', '--cached', '--name-only'])
review_path = base + 'decision26-planning-independent-review-v1/review.v2.json'
assert hashlib.sha256((root / review_path).read_bytes()).hexdigest() == 'c64480dd00c11f515a95d6d0aa83d4583f464af6150d433645e4a72dc0a03c03'
review = json.loads((root / review_path).read_bytes())
assert review['verdict'].startswith('APPROVED exact corrected six-document planning scope')
planning = [row['current'] for row in review['planning_after']]
assert len(planning) == 6
owned = []
for row in planning:
    raw = (root / row['path']).read_bytes()
    assert len(raw) == row['size_bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256']
    owned.append(row['path'])
checks = {
    'component-cold-provider-independent-review-v1/review.v1.json': 'fb47145c3add34845c695293e6467b9e79a1fe2e7c8f39df25d5e9124b0af050',
    'component-cpu04-corrected-cold-reader-independent-review-v1/review.v1.json': '7b07e2ca92b47e0327c3256ad69179b16d162d13edfb9047a08edd9ef5f277e3',
    'component-cpu04-postterminal-independent-review-v1/review.v1.json': '595e40bf132d8041995a13baa6f42435e0889be13a4fd53d003f8ac90d306709',
    'component-practical-runtime-review-v2/review.v1.json': 'da4ce882dd89cd4ce30a20cb04880edf8b9c2517a4c9f55515b40ba75f676fd9',
}
for path, expected in checks.items():
    assert hashlib.sha256((root / base / path).read_bytes()).hexdigest() == expected
assert hashlib.sha256((root / 'scripts/publication_gstreamer_component_runtime_v1.py').read_bytes()).hexdigest() == '23202bc466cd53f60cc0b78eb7902b5cdb1be4c6242c04e5ed81d13609a0d49e'
owned += ['scripts/publication_gstreamer_component_runtime_v1.py',
          'tests/test_publication_gstreamer_component_runtime_v1.py',
          base + 'amend_held_pair_session_planning_v1.py', base + 'stage_decision26_planning_v1.py']
for directory in ('decision26-planning-originals-v1', 'decision26-planning-independent-review-v1',
                  'component-cold-provider-seam-repair-v1', 'component-cold-provider-independent-review-v1',
                  'component-cold-helper-api-audit-v1', 'component-practical-runtime-review-v1',
                  'component-practical-runtime-review-v2', 'component-cpu04-postterminal-independent-review-v1',
                  'component-cpu04-corrected-cold-reader-preparation-v1',
                  'component-cpu04-corrected-cold-reader-independent-review-v1',
                  'ci-78-original-retention-v1', 'ci-2f409-original-retention-v1'):
    owned += [p.relative_to(root).as_posix() for p in sorted((root / base / directory).rglob('*'))
              if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc']
cpu = 'artifacts/gstreamer_component_release_20260930_a4e145b7/'
owned += [cpu + 'cpu-pair-04-original-controller/original.terminal.v1.json',
          cpu + 'cpu-pair-04/component_cli_terminal.v1.json']
assert len(owned) == len(set(owned))
physical = {p: (root / p).read_bytes() for p in owned}
subprocess.run(git + ['add', '-f', '--', *owned], check=True)
def blobs():
    raw = subprocess.check_output(git + ['cat-file', '--batch'], input=''.join(':' + p + '\n' for p in owned).encode())
    pos, result = 0, {}
    for p in owned:
        end = raw.index(b'\n', pos); header = raw[pos:end].split()
        assert len(header) == 3 and header[1] == b'blob'
        count = int(header[2]); pos = end + 1
        result[p] = raw[pos:pos + count]; pos += count
        assert raw[pos:pos + 1] == b'\n'; pos += 1
    assert pos == len(raw)
    return result
carriers = []
for p, raw in blobs().items():
    if raw != physical[p]:
        assert p.startswith('artifacts/'), p
        oid = subprocess.check_output(git + ['hash-object', '-w', '--stdin'], input=physical[p]).decode().strip()
        subprocess.run(git + ['update-index', '--add', '--cacheinfo', '100644,' + oid + ',' + p], check=True)
        carriers.append(p)
assert blobs() == physical
changed = set(subprocess.check_output(git + ['diff', '--cached', '--name-only'], text=True).splitlines())
assert changed.issubset(owned)
subprocess.run(git + ['-c', 'core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol',
                     'diff', '--cached', '--check', '--', *[r['path'] for r in planning],
                     'scripts/publication_gstreamer_component_runtime_v1.py',
                     'tests/test_publication_gstreamer_component_runtime_v1.py', base + 'stage_decision26_planning_v1.py'], check=True)
freeze = base + 'decision26-planning-freeze.v1.json'
assert not (root / freeze).exists()
(root / freeze).write_bytes((json.dumps({'previous_head': old, 'planning_files': planning,
    'review_sha256': hashlib.sha256((root / review_path).read_bytes()).hexdigest(), 'checks': checks,
    'owned_files': {p: {'size_bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest()} for p, b in physical.items()},
    'changed_paths': sorted(changed), 'unfiltered_artifacts': carriers, 'physical_index_equal': True,
    'private_session_implemented': False, 'historical_reader_executed': False,
    'cpu04_original_status': 'failed', 'new_cpu_gpu_acceptance': False, 'full_ci_accepted': False},
    sort_keys=True, separators=(',', ':')) + '\n').encode())
subprocess.run(git + ['add', '-f', '--', freeze], check=True)
print(json.dumps({'owned_files': len(owned) + 1, 'changed_files': len(changed) + 1, 'physical_index_equal': True}))
