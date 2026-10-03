"""Static AST/closed result/physical owned file joins only; no project imports/tests."""
from pathlib import Path
import ast,hashlib,json,os,re,subprocess
ROOT=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
OUT=Path(__file__).parent;BASE=ROOT/'artifacts/benchmark_recovery_20260930/ci-2f409-portable-fixture-repairs-v1'
author=json.loads((BASE/'author-review.v1.json').read_bytes())
def pin(path):
    b=path.read_bytes();return {'path':path.relative_to(ROOT).as_posix(),'size_bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
def require_pin(row):
    assert pin(ROOT/row['path'])==row

def cases(path):
    tree=ast.parse(path.read_text(encoding='utf-8-sig'))
    return {path.stem+'.'+c.name+'.'+f.name:f for c in tree.body if isinstance(c,ast.ClassDef) for f in c.body if isinstance(f,(ast.FunctionDef,ast.AsyncFunctionDef)) and f.name.startswith('test_')}
def assertions(node):
    return [ast.dump(n,include_attributes=False) for n in ast.walk(node) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr.startswith('assert')]
rows=[];old_ids=set();new_ids=set()
GIT=['/usr/bin/git','--git-dir=/mnt/e/STUDY/VAST/.git/worktrees/fix-benchmark-preparations-spec','--work-tree='+str(ROOT)]
head=subprocess.check_output(GIT+['rev-parse','HEAD'],timeout=5,text=True).strip();assert head=='8fefa4ba0c5b135c66f85a6eb7f4fd1aaebfdc21'
for row in author['before_after']:
    require_pin(row['before']);require_pin(row['after'])
    oldpath=ROOT/row['before']['path'];newpath=ROOT/row['after']['path']
    a,b=cases(oldpath),cases(newpath);assert a.keys()<=b.keys()
    assert len(a)==row['old_method_count'] and len(b)==row['current_method_count']
    diffs=[]
    for key in a:
        assert len(assertions(a[key]))==len(assertions(b[key]))
        assert [ast.dump(n,include_attributes=False) for n in a[key].decorator_list]==[ast.dump(n,include_attributes=False) for n in b[key].decorator_list]
        if assertions(a[key])!=assertions(b[key]):diffs.append(key)
    original_git=subprocess.check_output(GIT+['show',head+':'+row['after']['path']],timeout=5)
    assert original_git==oldpath.read_bytes(),'physical pre-edit snapshot differs from original current checkpoint'
    old_ids.update(a);new_ids.update(b)
    rows.append({'before':row['before'],'after':row['after'],'original_cases':len(a),'current_cases':len(b),'all_original_decorators_and_assertion_counts_equal':True,'assertion_AST_changed_cases':diffs,'before_equals_original_commit_bytes':True})
assert len(old_ids)==96 and len(new_ids)==99 and len(new_ids-old_ids)==3
mb=json.loads((ROOT/author['manifest']['before']['path']).read_bytes());ma=json.loads((ROOT/author['manifest']['after']['path']).read_bytes())
require_pin(author['manifest']['before']);require_pin(author['manifest']['after'])
key='allowed_portable_skips'
assert {k:v for k,v in mb.items() if k!=key}=={k:v for k,v in ma.items() if k!=key}
a={r['test_id']:r for r in mb[key]};b={r['test_id']:r for r in ma[key]};assert len(a)==80 and len(b)==88 and all(b[k]==v for k,v in a.items())
added=[b[k] for k in sorted(b.keys()-a.keys())];proof=json.loads((BASE/'skip-provenance.v1.json').read_bytes());assert {r['test_id'] for r in added}=={r['test_id'] for r in proof['original_unapproved_eight']}
for row in proof['original_unapproved_eight']:
    require_pin(row['source']);path=ROOT/row['source']['path'];f=cases(path)[row['test_id']]
    original=subprocess.check_output(GIT+['show','2f40946589254b3698eebedadb4b9d578f297deb:'+row['source']['path']],timeout=5).decode('utf-8-sig')
    oldtree=ast.parse(original);old=next(fn for cl in oldtree.body if isinstance(cl,ast.ClassDef) for fn in cl.body if isinstance(fn,ast.FunctionDef) and fn.name==f.name)
    assert ast.dump(f,include_attributes=False)==ast.dump(old,include_attributes=False)
    assert any(isinstance(n,ast.Constant) and n.value==row['reason'] for d in f.decorator_list for n in ast.walk(d))
    assert b[row['test_id']]['reason']==row['reason'] and b[row['test_id']]['acceptance_claim'] is False
focused=author['original_focused_attempts'][-1]
for key in ('execution','launch','results','stderr','stdout'):require_pin(focused[key])
result=json.loads((ROOT/focused['results']['path']).read_bytes());execution=json.loads((ROOT/focused['execution']['path']).read_bytes())
assert result['tests_run']==99 and result['successful'] is True and result['errors']==[] and result['failures']==[]
assert len(result['successes'])==96 and len(result['skips'])==3 and len(set(result['successes']))==96
assert set(result['successes'])|{r['test_id'] for r in result['skips']}==new_ids
assert execution['returncode']==0 and execution['timed_out'] is False and execution['source_stable'] is True and execution['original_pid_absent'] is True and execution['original_group_members']==[] and all(execution['pipe_eof'].values())
source_before=json.loads((BASE/'attempt04-final/source.before.json').read_bytes());source_after=json.loads((BASE/'attempt04-final/source.after.json').read_bytes());assert source_before==source_after and len(source_before)==531
stderr=(ROOT/focused['stderr']['path']).read_text();assert 'Ran 99 tests in 136.829s' in stderr and 'OK (skipped=3)' in stderr
patch=(BASE/'owned-source.diff').read_text();diff_paths=set(re.findall(r'^\+\+\+ after/(.+)$',patch,re.M));assert diff_paths=={r['after']['path'] for r in author['before_after']}|{author['manifest']['after']['path']}
wheel=json.loads((BASE/'wheel-fixture-provenance.v1.json').read_bytes());assert len(wheel['wheels'])==7 and wheel['not_installed_or_acquired'] is True
for row in wheel['wheels']:
    actual=pin(ROOT/row['path']);assert all(actual[k]==row[k] for k in ('path','size_bytes','sha256'))
    assert row['path'] in source_before and {k:source_before[row['path']][k] for k in ('size_bytes','sha256')}=={k:row[k] for k in ('size_bytes','sha256')}
owned=diff_paths;v6=json.loads((ROOT/'artifacts/gstreamer_component_release_20260930_a4e145b7/host/execution-code-closure.v6.json').read_bytes());assert not owned.intersection(r['path'] for r in v6['project_sources'])
for allowlist in author['image_source_scope']['all9_allowlists']:
    require_pin(allowlist['manifest']);entries=(ROOT/allowlist['manifest']['path']).read_text().splitlines();assert not owned.intersection(entries)
value={'schema_version':1,'artifact_kind':'vast_portable_fixture_independent_static_audit_v1','source_checkpoint':head,'original_test_ids':96,'current_test_ids':99,'new_case_ids':sorted(new_ids-old_ids),'owned_before_after':rows,'manifest_before':author['manifest']['before'],'manifest_after':author['manifest']['after'],'nine_integrations_and_all_non_skip_fields_unchanged':True,'old80_skip_rows_unchanged':True,'eight_additions_original2f_decorated_methods_exact_AST':True,'actual_final_test_successes':96,'actual_final_skips':result['skips'],'original99_execution':focused['execution'],'closed531_before_after_equal':True,'original_unit_duration_s':136.829,'original_capture_elapsed_s':execution['elapsed_s'],'current_owned_paths_disjoint_from_host87_and_all9_allowlists':True,'exact_patch_paths':sorted(diff_paths),'no_project_imports_or_tests_executed':True}
raw=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
with (OUT/'static-audit.v1.json').open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
print(json.dumps({'result':'static_scope_pass','before96_after99':True,'actual96success3skip':True,'sha256':hashlib.sha256(raw).hexdigest()}))