"""Finite metadata/AST conformance preparation. No project imports, tests or grants.

Each output is exclusive. Physical descriptors identify the files read by this
review; they are not replacement runtime/model/image or measurement authorities.
"""
import ast
import collections
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time

ROOT=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
HERE=Path(__file__).resolve().parent
BASE='artifacts/benchmark_recovery_20260930/'
OLD='artifacts/benchmark_recovery_20260929/'
START=time.monotonic_ns()
DEADLINE=START+120_000_000_000
MAX_FILE=8*1024*1024
MAX_TOTAL=96*1024*1024
pins={}; raw_cache={}; total=0

def epoch(i):
    return [i.st_dev,i.st_ino,i.st_mode,i.st_nlink,i.st_size,i.st_mtime_ns,i.st_ctime_ns]

def read(relative):
    global total
    if relative in raw_cache:return raw_cache[relative]
    assert time.monotonic_ns()<DEADLINE,'original metadata deadline exceeded'
    p=ROOT/relative
    assert p.is_absolute() and p.is_relative_to(ROOT)
    named=p.lstat()
    assert stat.S_ISREG(named.st_mode) and not stat.S_ISLNK(named.st_mode)
    assert named.st_size<=MAX_FILE and total+named.st_size<=MAX_TOTAL
    fd=os.open(p,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW)
    try:
        held=os.fstat(fd); assert epoch(held)==epoch(named)
        chunks=[]; count=0
        while True:
            chunk=os.read(fd,262144)
            if not chunk:break
            count+=len(chunk);assert count<=MAX_FILE
            chunks.append(chunk)
        raw=b''.join(chunks)
        assert epoch(os.fstat(fd))==epoch(held)==epoch(p.lstat())
    finally:os.close(fd)
    assert len(raw)==held.st_size
    total+=len(raw)
    pins[relative]={'path':relative,'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'observed_epoch':epoch(held)}
    raw_cache[relative]=raw
    return raw

def document(relative):return json.loads(read(relative))

def author(name):
    p=HERE/(name+'.py'); relative=str(p.relative_to(ROOT));read(relative)
    spec=importlib.util.spec_from_file_location(name,p)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def descriptor(relative):read(relative);return dict(pins[relative])

def node_sha(node):return hashlib.sha256(ast.dump(node,include_attributes=False).encode()).hexdigest()

reviews=author('scenario_reviews_v1').REVIEWS
notes=author('behavior_notes_v1').BEHAVIOR
assert set(reviews)==set(notes)
old=document(BASE+'final-conformance-mapping-skeleton-v1/mapping.v4.json')
spec_path='openspec/changes/fix-benchmark-preparations-spec/specs/benchmark-launch-preparation/spec.md'
spec=read(spec_path).decode('utf-8-sig')
lines=spec.splitlines(); actual=[]; current=None; ri=0;si=0
for number,line in enumerate(lines,1):
    if line.startswith('### Requirement: '):
        ri+=1;si=0;current={'id':f'R{ri}','name':line.split(': ',1)[1],'line':number,'scenarios':[]};actual.append(current)
    elif line.startswith('#### Scenario: '):
        si+=1;assert current is not None
        end=number
        while end<len(lines) and not lines[end].startswith('###'):end+=1
        clause='\n'.join(lines[number-1:end]).strip()
        current['scenarios'].append({'id':f'R{ri}/S{si}','name':line.split(': ',1)[1],'line':number,'exact_clause':clause})
assert len(actual)==20 and sum(len(x['scenarios']) for x in actual)==112
oldrows={s['id']:s for r in old['requirements'] for s in r['scenarios']}
assert set(oldrows)==set(reviews)
for r in actual:
    for s in r['scenarios']:
        prior=oldrows[s['id']]
        assert s['name']==prior['name'] and s['exact_clause']==prior['exact_clause'],s['id']
assert sum(bool(s['historical_register_id']) for s in oldrows.values())==82

doc_paths=[spec_path,'openspec/changes/fix-benchmark-preparations-spec/proposal.md',
 'openspec/changes/fix-benchmark-preparations-spec/design.md','openspec/changes/fix-benchmark-preparations-spec/tasks.md',
 'openspec/changes/fix-benchmark-preparations-spec/verification-plan.md','openspec/changes/fix-benchmark-preparations-spec/preparation-plan.md',
 'BENCHMARK_RECOVERY_PLAN.md','docs/gstreamer-component-benchmark-runbook.md']
for p in doc_paths:read(p)

paths=list((ROOT/'tests').glob('test*.py'))
paths+=list((ROOT/(BASE+'decoder-research-implementation-v5')).glob('test*.py'))
paths+=list((ROOT/(BASE+'component-ext4-relocation-preparation-v1')).glob('test*.py'))
methods={};trees={}
for p in sorted(paths):
    relative=str(p.relative_to(ROOT));raw=read(relative)
    tree=ast.parse(raw,filename=relative);trees[relative]=tree
    module=p.stem
    for cls in tree.body:
        if not isinstance(cls,ast.ClassDef):continue
        for node in cls.body:
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name.startswith('test_'):
                item={'id':f'{module}.{cls.name}.{node.name}','path':relative,'class':cls.name,'node':node}
                methods.setdefault(node.name,[]).append(item);methods[item['id']]=[item]

custom={
 'cpu06':BASE+'component-cpu06-ext4-actual-audit-closure-v1/review.v1.json',
 'gpu01':BASE+'component-gpu01-ext4-actual-audit-closure-v1/review.v1.json',
 'science':BASE+'component-four-arm-independent-science-result-review-v1/review.v1.json',
 'science_export':BASE+'component-four-arm-independent-science-preparation-v1/attempt01/exports-and-interpretation.v1.json',
 'science_csv':BASE+'component-four-arm-independent-science-preparation-v1/attempt01/four_arm_metrics.csv',
 'science_svg':BASE+'component-four-arm-independent-science-preparation-v1/attempt01/four_arm_latency_coverage_cobs.svg',
 'runbook':BASE+'component-runbook-independent-review-v1/review.v3.json',
 'profile_actual':BASE+'decision24-ci-userns-profile-actual-independent-review-v1/review.v1.json',
 'broker_author':BASE+'broker-terminal-owner-repair-v1/author-review.v1.json',
 'broker_supplement':BASE+'broker-terminal-owner-repair-v1/author-review.v2.supplement.json',
 'broker_peer':BASE+'broker-terminal-owner-independent-review-v1/review.v1.json',
 'broker_green':BASE+'broker-terminal-owner-repair-v1/attempt-02-green/execution.v1.json',
 'broker_cleanup_green':BASE+'broker-terminal-owner-repair-v1/attempt-03-observation-cleanup-green/execution.v1.json',
 'capacity_peer':BASE+'capacity-fixture-independent-review-v1/review.v1.json',
 'capacity_author':BASE+'ci-4cb9-two-failure-diagnosis-v1/capacity-fixture-repair-v1/author-review.v1.json',
 'capacity_green':BASE+'ci-4cb9-two-failure-diagnosis-v1/capacity-fixture-focused-attempt02/terminal.v1.json',
 'ci4cb':BASE+'ci-4cb9-two-failure-diagnosis-v1/original-member-copies-v1/unittest-child.report.json.original.raw',
 'ci4cb_diagnosis':BASE+'ci-4cb9-two-failure-diagnosis-v1/diagnosis.v1.json',
 'ci4cb_source_before':BASE+'ci-4cb9-two-failure-diagnosis-v1/original-member-copies-v1/tracked-source.before.json.original.raw',
 'ci4cb_source_after':BASE+'ci-4cb9-two-failure-diagnosis-v1/original-member-copies-v1/tracked-source.after.json.original.raw',
 'ci4cb_native':BASE+'ci-4cb9-two-failure-diagnosis-v1/original-member-copies-v1/native-build.json.original.raw',
 'ci4cb_member_provenance':BASE+'ci-4cb9-two-failure-diagnosis-v1/original-member-copies-v1/provenance.v1.json',
 'ext4_setup':BASE+'component-ext4-setup-physical-review-v2/review.v1.json',
 'ext4_bind':BASE+'component-ext4-bind-actual-independent-review-v1/review.v1.json',
 'ext4_host':BASE+'component-ext4-host-closure-physical-review-v1/review.v1.json',
 'byte_freeze':BASE+'checkout-byte-freeze-independent-review.v4.json',
 'peer_unit':BASE+'peer-unit-implementation-independent-review-v1/review.v1.json',
 'budget_proof':OLD+'operational-budget-proof.v1.json',
 'source_freeze':OLD+'initial-source-manifest.v1.json',
 'g_failed':OLD+'worker-stop-investigation.v1.json',
 'g_lifecycle':OLD+'original-g-service_lifecycle.v1.json',
 'accounting_review':OLD+'boundary-production-review.v1.json',
 'policy_equivalence':BASE+'policy-selection-equivalence-review.v1.json',
 'historical_reader':BASE+'component-cpu04-corrected-cold-reader-independent-review-v1/review.v1.json',
 'research04':BASE+'decoder-attempt04-independent-failed-review-v1/review.v1.json',
 'research05':BASE+'decoder-attempt05-independent-failed-review-v1/review.v1.json',
 'research_v3_peer':BASE+'decoder-research-v3-independent-review-v1/review.v1.json',
 'research_v4_peer':BASE+'decoder-research-v4-independent-review-v1/review.v1.json',
 'research_v5_peer':BASE+'decoder-research-v5-independent-review-v1/review.v1.json',
}
aliases={'held_peer':'held_session_peer','selected_packaged':'selected_packaged_terminal',
 'fixture_author':'portable_fixture_author','fixture_peer':'portable_fixture_peer',
 'seam2_peer':'seam2_peer','sibling_packaging':'sibling_packaging_original',
 'cpu05':'cpu05_postterminal_peer','cpu04':'historical_reader',
 'asset_peer':None,'skip_peer':None}
# These two original scope reviews are independent of final whole-lane acceptance.
custom['asset_peer']=BASE+'ci-model-assets-independent-review-v1/review.v1.json'
custom['skip_peer']=BASE+'decision25-ci-root-independent-review-v1/scope-review.v1.json'
ev={}
needed=set(x for r in reviews.values() for x in r['evidence'])|set(custom)
for key in sorted(needed):
    if key in custom:path=custom[key]
    else:
        origin=aliases.get(key,key)
        assert origin in old['evidence'] or origin in custom,(key,origin)
        path=custom[origin] if origin in custom else old['evidence'][origin]['path']
    ev[key]=descriptor(path)

ci=document(custom['ci4cb']);before=document(custom['ci4cb_source_before']);after=document(custom['ci4cb_source_after'])
assert before==after
success=set(ci['successful_test_ids']);discovered=set(ci['discovered_ids'])
skip_ids={x.get('test_id',x.get('id')) for x in ci['skips']}
failure_ids={x.get('test_id',x.get('id')) for x in ci['failures']}
error_ids={x.get('test_id',x.get('id')) for x in ci['errors']}
assert len(ci['failures'])==2 and len(ci['errors'])==0

focused={}; focused_docs={}
for key in ('broker_green','broker_cleanup_green','capacity_green'):
    d=document(custom[key]);focused_docs[key]=d
    assert d['returncode']==0 and not d['timed_out'] and d['source_before']==d['source_after']
    stderr_ref=d['stderr']; path=Path(stderr_ref['path'])
    relative=str(path.relative_to(ROOT));raw=read(relative)
    assert len(raw)==stderr_ref['size_bytes'] and hashlib.sha256(raw).hexdigest()==stderr_ref['sha256']
    ev[key+'_stderr']=descriptor(relative)
    for line in raw.decode('utf-8').splitlines():
        hit=re.match(r'(test_[A-Za-z0-9_]+) \(([^)]+)\).*\.\.\. ok$',line)
        if hit:
            name,qual=hit.groups(); ident=qual if qual.endswith('.'+name) else qual+'.'+name
            focused.setdefault(ident,[]).append(key)

def match_ref(pin,source):
    oldpin=source.get(pin['path'])
    return bool(oldpin and oldpin['sha256']==pin['sha256'] and oldpin['size_bytes']==pin['size_bytes'])

def assertions(node):
    values=[]
    for x in ast.walk(node):
        if isinstance(x,ast.Assert) or (isinstance(x,ast.Call) and isinstance(x.func,ast.Attribute) and x.func.attr.startswith('assert')):
            values.append({'line':x.lineno,'assertion':ast.unparse(x)})
    return sorted(values,key=lambda x:x['line'])

test_index={};source_index={}
def test_ref(name):
    hits=methods.get(name,[]);assert len(hits)==1,(name,[x['id'] for x in hits])
    m=hits[0];ident=m['id'];node=m['node'];path=m['path'];pin=descriptor(path)
    if ident not in test_index:
        code=read(path).decode('utf-8-sig');tested_same=match_ref(pin,before)
        outcome=('success' if ident in success else 'failed' if ident in failure_ids else 'error' if ident in error_ids else 'skipped_nonexecution' if ident in skip_ids else 'not_discovered' if ident not in discovered else 'no_success_record')
        fk=focused.get(ident,[])
        current_fk=[]
        for key in fk:
            candidates=focused_docs[key]['source_before']
            if any(x.get('sha256')==pin['sha256'] and Path(x.get('path','')).name==Path(path).name for x in candidates):current_fk.append(key)
        test_index[ident]={'id':ident,'source':pin,'line':node.lineno,'end_line':node.end_lineno,
            'method_ast_sha256':node_sha(node),'assertions':assertions(node),
            'called_boundaries':sorted(set(ast.unparse(x.func) for x in ast.walk(node) if isinstance(x,ast.Call))),
            'method_source':ast.get_source_segment(code,node),
            'fixture_limits':'Read the pinned method and its class helpers. Injected backend/transport/parser faults prove the asserted boundary only, never an external model, image or whole campaign grant.',
            'original_4cb':{'report_ref':'ci4cb','outcome':outcome,'current_test_file_bytes_match_original':tested_same,'source_commit':'4cb9d8313cca71256179bc3b59cc6f9137e7b8ba','whole_run_success':False},
            'current_focused_original_receipts':current_fk,
            'current_assertion_execution_available':bool(current_fk or (tested_same and outcome=='success')),
            'coverage_limit':'A direct file/method match is not proof of unchanged transitive dependencies or of scenario completeness. Whole current CI and physical acceptance are separate pending joins.'}
    return ident

def source_ref(path,anchor):
    key=path+'#'+anchor
    if key not in source_index:
        raw=read(path);text=raw.decode('utf-8-sig');ls=text.splitlines()
        found=[i+1 for i,s in enumerate(ls) if anchor in s];assert found,key
        tree=None
        if path.endswith('.py'):
            tree=trees.get(path) or ast.parse(raw,filename=path)
        nodes=[] if tree is None else [x for x in ast.walk(tree) if isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))]
        preferred=[n for n in nodes if n.name==anchor or anchor in (ls[n.lineno-1])]
        line=preferred[0].lineno if preferred else found[0]
        containing=[x for x in nodes if x.lineno<=line<=x.end_lineno]
        fn=min(containing,key=lambda x:x.end_lineno-x.lineno) if containing else None
        pin=descriptor(path)
        source_index[key]={'source':pin,'anchor':anchor,'line':line,'matching_lines':found,
            'enclosing_boundary':None if fn is None else {'name':fn.name,'line':fn.lineno,'end_line':fn.end_lineno,'ast_sha256':node_sha(fn)},
            'excerpt':'\n'.join(ls[max(0,line-2):min(len(ls),line+5)]),
            'current_bytes_match_original_4cb':match_ref(pin,before),
            'limit':'Source inspection identifies the predicate. It is not an execution result.'}
    return key

physical_rows=set('R1/S1 R1/S2 R5/S1 R5/S2 R6/S5 R6/S11 R7/S10 R8/S4 R8/S10 R9/S3 R12/S1 R13/S1 R13/S3 R13/S4 R14/S3 R15/S1 R15/S2 R15/S4 R15/S10 R16/S3 R16/S4 R19/S2 R19/S5 R19/S6 R20/S2 R20/S3'.split())
hardware_pending='New supervisor 99f changes host87: new original host closure, CPU07 and GPU02 successful CLI/cold/95-input/cleanup results and stock four-arm exports must be joined. The 0ad results remain historical successes.'
final_pending='Exact-current hosted and independent ext4 portable/native/source/skip CI, complete conformance peer review, archive and latest-commit final review remain pending.'
scopes=collections.Counter();behaviors=collections.Counter()
for req in actual:
    req['implementation_profile_ref']=req['id']
    for item in req['scenarios']:
        ident=item['id'];review=reviews[ident];prior=oldrows[ident]
        test_ids=[test_ref(t) for t in review['tests']]
        src_ids=[source_ref(p,a) for p,a in review['anchors']]
        direct_match=all(source_index[x]['current_bytes_match_original_4cb'] for x in src_ids if source_index[x]['source']['path'].startswith('scripts/'))
        active='active_selected_component_or_repository_behavior'==prior['scope']
        conditional=prior['scope'].startswith('conditional') or 'future' in prior['scope']
        item.update({'historical_register_id':prior['historical_register_id'],'scope':prior['scope'],'scope_reason':prior['scope_reason'],
            'active_obligations':'Current safety, format, ownership, isolation and future-entrypoint rejection predicates remain active, including rows whose real campaign execution is separately provisioned.',
            'implementation_behavior':notes[ident],'test_refs':test_ids,'source_anchor_refs':src_ids,'evidence_refs':review['evidence'],
            'scoped_execution_status':'asserted methods have current-byte scoped original results' if test_ids and all(test_index[x]['current_assertion_execution_available'] for x in test_ids) else 'some methods need a current-byte original result, or this is manual/physical evidence',
            'direct_implementation_bytes_match_original_4cb':direct_match,
            'current_scenario_acceptance':'pending_final_join_not_granted',
            'pending':[final_pending]+([hardware_pending] if ident in physical_rows else []),
            'automatic_verification_limits':['AST, names, hashes and document structure cannot prove the runtime behavior; pinned methods expose their actual assertions and fixture boundaries.',
             'Historic or individual successful tests do not turn FAILED whole CI into success. A scenario needs its own active predicates and all applicable physical/manual gates.'],
            'registered_future_execution_remains_unexecuted':conditional,
            'mapping_basis':'Scenario-specific source/test review plus closed evidence; no broad topic-only coverage or deferred-to-executed relabel.'})
        if conditional:item['pending'].append('The original full qualification/Q4/cloud/service/campaign physical action remains registered future work; unit predicates are still active.')
        if ident=='R13/S6':item['pending'].append('Direct component-kind negative tests for every named qualification/promotion/Q4/publication/full consumer are not identified. Strict source-kind predicates and the preprocessing dispatch test are narrower evidence; do not infer full entrypoint test coverage.')
        if ident.startswith('R15/') and ident in {'R15/S5','R15/S6','R15/S7','R15/S8','R15/S9'}:
            item['pending'].append('All real decoder research attempts are failed with no causal cohort. Artifact-only assertions check failure integrity/protocol mechanics and cannot authorize changed intake or causal science.')
        if ident=='R14/S4':item['resolved_interpretation']={'basis':'Root review explicitly applies the enclosing owner/authorization limits and one persisted original owner to journal validation.','elected_owner':'Must emit its bounded failed terminal on setup failure; emission failure returns 74 and retains original cause.','losing_candidate':'Cannot gain terminal authority before its immutable owner commit. Bounded failed stdout is allowed; foreign winner journal must stay untouched.','waiver':False}
        scopes[item['scope']]+=1;behaviors[item['scoped_execution_status']]+=1

# All descriptors are metadata inputs; release happened after each bounded read.
for p,d in list(pins.items()):
    current=(ROOT/p).lstat();assert epoch(current)==d['observed_epoch'],p
    assert hashlib.sha256(raw_cache[p]).hexdigest()==d['sha256']
assert time.monotonic_ns()<DEADLINE
git=['git','-c','core.longpaths=true','--git-dir=/mnt/e/STUDY/VAST/.git/worktrees/fix-benchmark-preparations-spec','--work-tree='+str(ROOT)]
head=subprocess.run(git+['rev-parse','HEAD'],capture_output=True,check=True,timeout=10).stdout.decode().strip()
changes=subprocess.run(git+['diff','--name-only','-z','HEAD','--','scripts','tests','.ci','.github','.gitattributes'],capture_output=True,check=True,timeout=10).stdout.decode().split('\0')
changes=[x for x in changes if x]
mapping={'schema_version':1,'artifact_kind':'vast_current_conformance_preparation_v1','active_change':'fix-benchmark-preparations-spec',
 'status':'prepared_detailed_mapping_not_final_acceptance','current_source_commit':head,'physical_source_changes_vs_head':changes,
 'requirements_count':20,'scenario_count':112,'historical_exact_register_scenarios':82,'new_scenarios':30,
 'publication_ready':False,'component_release_complete':False,'full_run_started':False,'archive_complete':False,
 'historical_measurement_source_commit':'0ad78d6abdb3c526544a17185af7fe8094716735',
 'historical_cpu06_gpu01':'Both original source-specific commands succeeded and passed full cold, guardian, cleanup and 95-input gates. They are not rebound to the changed supervisor.',
 'current_changed_supervisor':descriptor('scripts/backend_publication_process_supervisor_v3.py'),
 'requirements':actual,'tests':test_index,'source_anchors':source_index,'evidence':ev,
 'scope_counts':dict(scopes),'scoped_result_counts':dict(behaviors),
 'global_pending':[hardware_pending,final_pending],
 'ci_4cb_original':{'source_commit':'4cb9d8313cca71256179bc3b59cc6f9137e7b8ba','whole_run_success':False,
 'discovered':len(ci['discovered_ids']),'tests_run':ci['tests_run'],'successful_test_ids':len(success),'failures':ci['failures'],'errors':ci['errors'],
 'skips':len(ci['skips']),'selection':ci['selection'],'missing_required_successes':ci['missing_required_successes'],
 'source_before_after_equal':True,'original_native_report_ref':'ci4cb_native'},
 'interpretation_limits':['This is a prepared conformance index, not proof that tasks, archive or latest checks have completed.',
 'Runtime and source identity are source-specific. Individual fixture assertions, image/package evidence, real measurements and final repository gates are separate.',
 'Structure validation confirms document integrity only. It never certifies behavior.',
 'Unexecuted legacy campaign clauses keep both their future physical requirement and their current strict interface obligations. No broad deferral removes active safety checks.']}
inventory={'schema_version':1,'artifact_kind':'vast_conformance_metadata_read_inventory_v1','source_root':str(ROOT),'files':list(pins.values()),
 'aggregate_bytes_read':total,'limits':{'individual_bytes':MAX_FILE,'aggregate_bytes':MAX_TOTAL,'original_elapsed_limit_s':120},
 'reads':'Bounded regular named FD reads with before/after fstat/name epoch equality, immediate FD close and final epoch checks. No model weights or producer media read.',
 'all_review_fds_closed':True,'project_imports':0,'tests_executed':0,'hardware_or_engine_queries':0,'elapsed_s':(time.monotonic_ns()-START)/1e9}
summary={'schema_version':1,'artifact_kind':'vast_current_conformance_preparation_review_v1','source_commit':head,'status':'prepared_not_accepted',
 'requirement_count':20,'scenario_count':112,'original_memberships_preserved':82,'unresolved_test_or_source_links':[],
 'qualified_test_count':len(test_index),'source_anchor_count':len(source_index),'evidence_count':len(ev),
 'specific_remaining_gap':['R13/S6 lacks direct component-kind negative tests of every named full consumer. The map records strict source predicates and narrower dispatch assertions without claiming exhaustive rejection tests.'],
 'global_pending':[hardware_pending,final_pending],
 'owner_interpretation':'R14/S4 owner election is normative authority, not a waiver: elected owner failure must emit; losing candidate must not alter a foreign winner.',
 'no_acceptance_claim':True,'no_task_updates':True,'all_review_fds_closed':True,'project_imports':0,'tests_executed':0,
 'automatic_verification_limits':mapping['interpretation_limits']}

def write(name,value):
    raw=(json.dumps(value,indent=2,sort_keys=True,ensure_ascii=True,allow_nan=False)+'\n').encode('ascii')
    assert len(raw)<MAX_FILE
    p=HERE/name
    with p.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    return {'path':str(p.relative_to(ROOT)),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}

out={}
out['mapping']=write('mapping.v1.json',mapping)
out['inventory']=write('source-review-inventory.v1.json',inventory)
summary['outputs']=out
out['review']=write('review.v1.json',summary)
print(json.dumps({'outputs':out,'scenarios':112,'tests':len(test_index),'anchors':len(source_index),'elapsed_s':(time.monotonic_ns()-START)/1e9},sort_keys=True))
