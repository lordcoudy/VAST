"""Pure actual selected/native/worker source closure comparison; no engine."""
from pathlib import Path
import hashlib, json, os, sys
ROOT = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
sys.path.insert(0, str(ROOT / 'scripts'))
import publication_image_build_v1 as image_build
import publication_qualification_image_refreeze_v1 as refreeze
HOST = ('scripts/publication_gstreamer_component_cli_v1.py',
        'scripts/publication_gstreamer_component_inputs_v1.py',
        'scripts/publication_gstreamer_component_runtime_v1.py')
OUT = ROOT / 'artifacts/benchmark_recovery_20260930/component-held-session-host-image-scope-v1'
assert not OUT.exists()
OUT.mkdir()
def pin(path):
    raw = path.read_bytes()
    return {'path': path.relative_to(ROOT).as_posix(), 'size_bytes': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest()}
registry = refreeze.load_refreeze_registry(project_root=ROOT, registry_path=ROOT / refreeze.REGISTRY_RELATIVE_PATH)
selected = next(row for row in registry['systems'] if row['system'] == 'gstreamer_custom')
receipt_path = ROOT / 'artifacts/benchmark_recovery_20260930/selected-gstreamer-build-a4e145b7-v1/gstreamer_custom.runtime.freeze.json'
receipt = refreeze.load_runtime_image_receipt(receipt_path)
sources = refreeze._read_allowlist(ROOT, selected['source_allowlist'])
assert len(sources) == 73 and not set(HOST).intersection(sources)
assert receipt['physical_identity']['source_identity'] == refreeze._source_identity(ROOT, selected)
assert receipt['physical_identity']['image_id'] == 'sha256:e474867043f1a74387573140cb2bfd69825df2672edad0acda0d28954af84cb6'
assert receipt['candidate_binding_eligible'] is True and receipt['blockers'] == []
plan = image_build.publication_image_build_plan(project_root=ROOT, registry_path=ROOT / image_build.REGISTRY_RELATIVE_PATH)
current = {row['name']: row for row in plan['images']}
groups = []
for relative, expected_count in (
    ('artifacts/fix_benchmark_preparations_20260928g/native-a/native_probe.freeze.json', 3),
    ('artifacts/fix_benchmark_preparations_20260928g/worker_images/analytics-worker.freeze.json', 2),
):
    path = ROOT / relative
    previous = image_build.load_publication_image_freeze_receipt(path)
    assert len(previous['images']) == expected_count
    assert previous['registry_sha256'] == plan['registry_sha256']
    identities = []
    for row in previous['images']:
        live = current[row['name']]
        keys = ('source_set_sha256', 'dependency_set_sha256', 'build_context_sha256')
        assert all(row[key] == live[key] for key in keys)
        sources_in_image = live['relative_paths']
        assert not set(HOST).intersection(sources_in_image)
        identities.append({'name': row['name'], 'image_id': row['image_id'],
                           **{key: live[key] for key in keys}})
    groups.append({'receipt': pin(path), 'current_source_equals_original_freeze': True, 'images': identities})
document = {'artifact_kind': 'vast_component_host_only_image_scope_v1', 'host_sources': [pin(ROOT / p) for p in HOST],
    'selected_source_count': 73, 'host_sources_absent_from_selected_and_native_worker_images': True,
    'selected_runtime_receipt': pin(receipt_path), 'selected_source_identity': refreeze._source_identity(ROOT, selected),
    'groups': groups, 'engine_operations': 0, 'model_assessments': 0, 'image_builds': 0,
    'current_live_image_observation': False, 'host_closure_renewal_still_required': True,
    'selected_image_rebuild_required_by_this_source_diff': False}
raw = (json.dumps(document, sort_keys=True, separators=(',', ':')) + '\n').encode()
with (OUT / 'review.v1.json').open('xb') as stream:
    stream.write(raw); stream.flush(); os.fsync(stream.fileno())
print(json.dumps({'selected73_source_unchanged': True, 'native3_worker2_sources_unchanged': True,
                  'no_build_or_engine_operation': True, 'receipt_sha256': hashlib.sha256(raw).hexdigest()}))
