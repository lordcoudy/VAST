"""Original image validators over actual retained build facts; no hardware grant."""
import ast, hashlib, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
import checkpoint_gstreamer_publication_runtime_v3 as runtime

BASE = ROOT / 'artifacts/benchmark_recovery_20260930'
receipt_path = BASE / 'selected-gstreamer-build-a3e976d0-v1/gstreamer_custom.runtime.freeze.json'
raw = receipt_path.read_bytes()
assert hashlib.sha256(raw).hexdigest() == '7807fc43cf4f706d2756baefcbdd4887798b04168db06f7acbdbea4a8541cc8c'
receipt = json.loads(raw)
assert receipt['candidate_binding_eligible'] is True and receipt['blockers'] == []
physical = receipt['physical_identity']
actual = {'image_id': physical['image_id'],
          'repository_digest': physical['canonical_repository_digest'],
          'inspect_projection_sha256': physical['inspect_projection_sha256'],
          'base_image_id': physical['base']['image_id']}
assert runtime._validate_image(actual) == actual
inspections = json.loads((BASE / 'selected-gstreamer-build-a3e976d0-v1/image-after.stdout.raw').read_bytes())
assert len(inspections) == 3
for image in inspections:
    projection = runtime._image_projection(image)
    assert projection['Id'] == actual['image_id']
    assert projection['RepoDigests'] == [actual['repository_digest']]
    assert projection['Os'] == 'linux' and projection['Architecture'] == 'amd64'
    assert projection['Created'] == '1970-01-01T00:00:00Z'
    assert projection['Config']['Entrypoint'] == [runtime.EXPECTED_IMAGE_ENTRYPOINT]
    assert projection['Config']['User'] == runtime.EXPECTED_IMAGE_USER
    assert projection['Config']['Labels'] == runtime.EXPECTED_IMAGE_LABELS
    assert runtime.image_projection_sha256(projection) == actual['inspect_projection_sha256']
assert physical['embedded_files'] == runtime.EXPECTED_EMBEDDED_ARTIFACTS
original = BASE / 'component-host-image-binding-renewal-v2/original-host-wrapper.raw'
tree = ast.parse(original.read_bytes())
old = {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body
       if isinstance(node, ast.Assign) and len(node.targets) == 1
       and isinstance(node.targets[0], ast.Name)
       and node.targets[0].id in ('EXPECTED_IMAGE_ID', 'EXPECTED_REPOSITORY_DIGEST',
                                  'EXPECTED_IMAGE_INSPECT_PROJECTION_SHA256', 'EXPECTED_BASE_IMAGE_ID')}
old_image = {'image_id': old['EXPECTED_IMAGE_ID'], 'repository_digest': old['EXPECTED_REPOSITORY_DIGEST'],
             'inspect_projection_sha256': old['EXPECTED_IMAGE_INSPECT_PROJECTION_SHA256'],
             'base_image_id': old['EXPECTED_BASE_IMAGE_ID']}
try:
    runtime._validate_image(old_image)
except runtime.GstreamerPublicationRuntimeV3Error as error:
    assert str(error) == 'gstreamer_container_image_contract_invalid'
else:
    raise AssertionError('historical image unexpectedly accepted')
result = {'actual_retained_image_contract_accepted': True, 'actual_inspect_projections_checked': 3,
          'historical_image_contract_rejected': True, 'original_embedded_files_match': True,
          'live_inspection_executed': False, 'hardware_acceptance': False,
          'runtime_receipt_sha256': hashlib.sha256(raw).hexdigest(), 'image_id': actual['image_id']}
with (Path(__file__).parent / 'direct-image-gate.v1.json').open('x') as stream:
    json.dump(result, stream, sort_keys=True); stream.write('\n')
print(json.dumps(result, sort_keys=True))
