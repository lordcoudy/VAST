from pathlib import Path
import ast, hashlib, json, subprocess
root=Path(__file__).resolve().parents[3];out=Path(__file__).parent
relative='tests/test_checkpoint_openvino_gva_qualification_fragment_v3.py'
original=(out/'original-test.raw').read_bytes();current=(root/relative).read_bytes()
assert subprocess.check_output(['git','-c','core.longpaths=true','show','5bc416a2beab98b6cc60229dac56332b48cc6ca2:'+relative],cwd=root)==original
old=ast.parse(original);new=ast.parse(current)
for node in ast.walk(new):
    if isinstance(node,ast.FunctionDef) and node.name=='expected_terminal_detector':
        assert node.args.args[-1].arg=='project_root';node.args.args.pop()
        for n in ast.walk(node):
            if isinstance(n,ast.Name) and n.id=='project_root':n.id='ROOT'
    if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='expected_terminal_detector':
        assert len(node.args)==3 and ast.unparse(node.args[-1])=='self.project_root';node.args.pop()
assert ast.dump(old,include_attributes=False)==ast.dump(new,include_attributes=False)
execution=json.loads((out/'attempt01/execution.json').read_bytes())
results=json.loads((out/'attempt01/test-results.json').read_bytes())
assert execution['successful'] and execution['returncode']==0 and execution['original_pid_absent']
assert not execution['original_group_members'] and all(execution['pipe_eof'].values())
assert execution['source_stable'] and execution['source_path_count']==522
assert results['tests_run']==4 and len(results['successes'])==4 and not results['errors'] and not results['failures'] and not results['skips']
def desc(p):
    b=p.read_bytes();return {'path':p.relative_to(root).as_posix(),'size_bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
report={'artifact_kind':'vast_gva_pure_fixture_root_author_review_v1','source_commit':'5bc416a2beab98b6cc60229dac56332b48cc6ca2',
 'original_physical_test_equals_commit':True,'whole_module_AST_equal_after_exact_four_location_reversal':True,
 'all_four_original_methods_and_assertions_preserved':True,'changed_source':desc(root/relative),
 'original_source':desc(out/'original-test.raw'),'actual_original_execution':desc(out/'attempt01/execution.json'),
 'actual_original_results':desc(out/'attempt01/test-results.json'),'original_stderr':desc(out/'attempt01/stderr.raw'),
 'actual_tests':4,'actual_successes':4,'source_before_after_equal_count':522,
 'actual_elapsed_s':execution['elapsed_s'],'original_owner':execution['owner'],
 'original_red':'retained original5bc CPU ZIP8b03433f, exact failure-index6cbd1526: helper read globalROOT instead of already-materialized owned fixture project',
 'scope':'one test module; no production/image/dependency/receipt/skip/native/model/hardware change',
 'full_ci_acceptance':False,'benchmark_acceptance':False,'review_required':True}
(out/'author-review.v1.json').open('xb').write((json.dumps(report,sort_keys=True,indent=2)+'\n').encode())
print(json.dumps(report))
