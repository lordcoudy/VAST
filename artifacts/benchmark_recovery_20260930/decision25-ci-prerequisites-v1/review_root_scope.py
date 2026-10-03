"""Finite read-only sibling/attribute/selection evidence audit; no test discovery."""
from pathlib import Path
import ast
import hashlib
import json
import os
import zipfile

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'artifacts/benchmark_recovery_20260930/decision25-ci-root-independent-review-v1'
OUT.mkdir()
def pin(path):
    raw=path.read_bytes()
    return {'path':path.relative_to(ROOT).as_posix(),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
base=ROOT/'artifacts/benchmark_recovery_20260930'
selection=ROOT/'.ci/integration-test-selection.v1.json'
manifest=json.loads(selection.read_bytes())
integrations={r['test_id']:r for r in manifest['integration_declarations']}
skips={r['test_id']:r for r in manifest['allowed_portable_skips']}
assert len(integrations)==9 and len(skips)==80
assert sum(r['classification']=='existing_retired_schema_migration' for r in skips.values())==10
with zipfile.ZipFile(base/'ci-a3-original-retention-v1/36705774549-cpu/original-artifact.zip') as archive:
    report_names=[n for n in archive.namelist() if n.endswith('test-child-report.json')]
    assert len(report_names)==1, report_names
    raw=archive.read(report_names[0]);original=json.loads(raw)
    original_skips={r['test_id']:r['reason'] for r in original['skipped']}
assert len(original_skips)==82
assert {n:r['reason'] for n,r in skips.items()}=={n:r for n,r in original_skips.items() if n not in integrations}
model_ast=ast.parse((ROOT/'tests/test_checkpoint_model_parity.py').read_text())
assessment=next(n for n in model_ast.body if isinstance(n,ast.ClassDef) and n.name=='AssessmentTests')
assert any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='skip'
           and isinstance(n.args[0],ast.Constant) and n.args[0].value=='schema-v1 fixture retained only as migration history'
           for n in assessment.decorator_list)
methods={n.name for n in assessment.body if isinstance(n,ast.FunctionDef)}
assert all(n.rsplit('.',1)[1] in methods for n,r in skips.items() if r['classification']=='existing_retired_schema_migration')
pack=base/'decision25-sibling-packaging-v1'
green=json.loads((pack/'green-01/terminal.v1.json').read_bytes())
assert green['original_child_returncode']==0 and green['sources_stable'] and green['source_before']==green['source_after']
assert b'Ran 23 tests' in (pack/'green-01/stderr.raw').read_bytes()
for name,descriptor in green['source_after'].items():
    actual=pin(ROOT/name)
    assert actual['size_bytes']==descriptor['size_bytes'] and actual['sha256']==descriptor['sha256']
    before=(pack/'before'/name).read_bytes()
    after=(ROOT/name).read_bytes()
    insert=[b'scripts/publication_gstreamer_component_authority_v1.py',b'scripts/publication_guardian_component_preprocessing_contract_v1.py']
    lines=after.splitlines(keepends=True)
    filtered=[line for line in lines if not any(path in line for path in insert)]
    assert b''.join(filtered)==before
    assert all(sum(path in line for line in lines)==1 for path in insert)
    if name.endswith('allowlist.txt'):
        assert b'\r' not in after and after.decode().splitlines()==sorted(after.decode().splitlines())
attrs=ROOT/'.gitattributes';attrbase=base/'decision25-finite-attributes-v1'
change=json.loads((attrbase/'change.v1.json').read_bytes());before=(attrbase/'before.gitattributes.raw').read_bytes()
after=attrs.read_bytes()
assert after.startswith(before) and hashlib.sha256(after).hexdigest()==change['new_sha256']
suffix=after[len(before):].decode().splitlines();rules=[n for n in suffix if n and not n.startswith('#')]
assert rules==change['added_finite_rules'] and len(rules)==22
assert sum(n.endswith('text eol=lf') for n in rules)==15
assert sum(n.endswith('-text !eol') for n in rules)==7
value={'schema_version':1,'artifact_kind':'vast_decision25_ci_root_independent_scope_review_v1',
 'scope':'Original9/80/10 selection evidence, six sibling COPY/allowlists and current22 finite attribute rules. No tests/discovery/engine/probe run.',
 'selection_evidence':{'manifest':pin(selection),'original_child_report_member':report_names[0],
    'original_report_sha256':hashlib.sha256(raw).hexdigest(),'integrations':9,'allowed_existing_skips':80,
    'original_a3_skips':82,'source_attested_retired_nonexecution':10,
    'verdict':'Current declarations preserve exact historical skip IDs/reasons and nine physical obligations. Mandatory protection expansion is pending separate root repair.'},
 'packaging':{'verdict':'approved source scope only','sources':[pin(ROOT/n) for n in green['source_after']],
    'original_green':pin(pack/'green-01/terminal.v1.json'),'tests':23,
    'original_raw_stderr':pin(pack/'green-01/stderr.raw'),
    'only_two_required_modules_inserted':True,'historical_scope':pin(pack/'current-scope.v1.json'),
    'limitation':'Scope63146780 is the original packaging checkpoint; subsequent packaged authority repair can invalidate selected887. No current image or sibling grant is inferred.'},
 'attributes':{'verdict':'approved finite rules only','current':pin(attrs),'before':pin(attrbase/'before.gitattributes.raw'),
    'original_prefix_unchanged':True,'finite_rules':22,'LF_rules':15,'raw_rules':7,
    'fresh_checkout_pending':True,'additional_new_rules_not_reviewed':True},
 'notes':['Five integration source.line values are historical descriptive coordinates; exactmethod IDs and paths remain valid. Lines do not grant authority.',
          'Retired10 schema migration skips remain nonexecution and need final conformance disposition; they are never successes.',
          'Reviewer authored the separate CI prerequisite slice; this receipt independently reviews root-owned selection evidence/packaging/attributes.'],
 'executed_tests':0,'engine_queries':0,'namespace_calls':0,'hardware_acceptance':False}
with (OUT/'scope-review.v1.json').open('xb') as stream:
    stream.write((json.dumps(value,sort_keys=True,indent=2)+'\n').encode());stream.flush();os.fsync(stream.fileno())
print(json.dumps(pin(OUT/'scope-review.v1.json')))
