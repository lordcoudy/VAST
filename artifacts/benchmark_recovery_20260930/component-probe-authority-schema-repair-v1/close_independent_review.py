"""Finite independent source/evidence review; no assessor, engine or test call."""
from pathlib import Path
import hashlib
import json
import os

ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).parent
OUT=HERE.with_name('component-probe-authority-schema-independent-review-v1')
OUT.mkdir()
def pin(path):
    raw=path.read_bytes()
    return {'path':path.relative_to(ROOT).as_posix(),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
author=json.loads((HERE/'author-review.v1.json').read_bytes())
green=json.loads((HERE/'green-01/terminal.v1.json').read_bytes())
red=json.loads((HERE/'red-01/terminal.v1.json').read_bytes())
assert green['original_child_returncode']==0 and red['original_child_returncode']==1
assert green['source_before']==green['source_after'] and green['sources_stable']
for name,value in green['source_after'].items():
    current=pin(ROOT/name)
    assert current['sha256']==value['sha256'] and current['size_bytes']==value['size_bytes']
for name,value in green['outputs'].items():
    actual=pin(HERE/'green-01'/(name+'.raw'))
    assert actual['sha256']==value['sha256'] and actual['size_bytes']==value['size_bytes']
assert b'Ran 14 tests' in (HERE/'green-01/stderr.raw').read_bytes()
assert b"KeyError: 'content_identity_sha256'" in (HERE/'red-01/stderr.raw').read_bytes()
original_path=ROOT/'configs/checkpoint_analytics_model_parity.refreshed.v4.fix-benchmark-20260928g.accepted.acceptance_receipt.json'
original=json.loads(original_path.read_bytes())
assert all(set(p)=={'path','size_bytes','sha256','worker_implementation_sha256'}
           for p in original['refresh_authority']['runtime_probes'].values())
value={'schema_version':1,'artifact_kind':'vast_component_probe_schema_independent_source_review_v1',
 'verdict':'approved within narrow source repair','reviewable':True,
 'owned_final':[pin(ROOT/v['path']) for v in author['owned_final'].values()],
 'author_review':pin(HERE/'author-review.v1.json'),
 'original_receipt':pin(original_path),
 'original_green':{**pin(HERE/'green-01/terminal.v1.json'),'tests':14,
     'raw_stderr':pin(HERE/'green-01/stderr.raw'),'source5_before_after_equal':True,
     'elapsed_capture_s':green['elapsed_s'],'reviewer_rerun':False},
 'original_red':pin(HERE/'red-01/terminal.v1.json'),
 'source_findings':[
    'Stock validate_refresh_authority_v4108/144 returns exact4 runtime-probe authority fields; the removed semantic-content field was invented by the prior fixture.',
    'Changed _worker_material175–190 now rejects nonexact4 shape and joins authority implementation to the schema/engine-validated physical probe; existing worker config/probe equality is retained.',
    'ComponentPinsV1.read/object still verifies original path,size,full serialized SHA and held epoch. Removing an absent secondary semantic hash does not remove original-byte custody.',
    'Component authority projection still equals the original accepted receipt projection. Kind/resource/accepted/publication/qualification flags remain strict and unchanged.',
    'New original receipt parser regression and resealed extra-field/foreign-implementation negatives reach the intended probe boundary; all13 prior methods remain and the fixture now has stock shape.'
 ],
 'source_audit':{**pin(HERE/'source-image-scope.v1.json'),
    'all_four_runtime_aggregates_invalidated':True,'native3_worker2_unchanged':True,
    'required_before_physical_pair':'Genuine renewed selected image, exact host wrapper identities and fresh host closure. Sibling images stay historical/ineligible.'},
 'self_review':'Approval fixes a source/fixture schema mismatch, not physical operability. Actual CPU03 reached a device probe but no measurement. No retained per-call CID proof is invented. Later runtime/model/pair acceptance remains unproved.',
 'reviewer_owned_other_files':['scripts/run_ci_checks.py','.github/workflows/ci.yml','tests/test_run_ci_checks.py','scripts/ci_namespace_diagnostic_v1.py','tests/test_ci_namespace_diagnostic_v1.py'],
 'reviewer_production_edits':False,'reviewer_tests_run':0,'engine_queries':0,
 'model_or_hardware_acceptance':False,'new_workload_authorized_by_receipt':False}
with (OUT/'review.v1.json').open('xb') as stream:
    stream.write((json.dumps(value,sort_keys=True,indent=2)+'\n').encode());stream.flush();os.fsync(stream.fileno())
print(json.dumps(pin(OUT/'review.v1.json')))
