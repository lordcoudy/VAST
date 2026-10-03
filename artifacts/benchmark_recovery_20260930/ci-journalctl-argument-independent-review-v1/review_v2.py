"""Finite static source and closed original-record review; no project imports/test run."""
import ast,hashlib,json,re
from pathlib import Path
ROOT=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
OUT=Path(__file__).parent
E=ROOT/'artifacts/benchmark_recovery_20260930/ci-journalctl-argument-seam-repair-v1'
def descriptor(path):
 raw=path.read_bytes();return {'path':str(path.relative_to(ROOT)),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def doc(path):return json.loads(path.read_bytes())
def verify(reference):
 p=ROOT/reference['path'];d=descriptor(p);assert d==reference;return d
review_ref={'path':str((E/'author-review.v1.json').relative_to(ROOT)),'size_bytes':21353,'sha256':'c6ec12d9947bd377a9972f6bc9b3cd6e57f74d085f1f3f6027c2383938f1a26d'}
verify(review_ref);author=doc(E/'author-review.v1.json')
final=[verify(r) for r in author['final_owned_sources']]
before=[verify(r) for r in author['before']]
old=(E/'before/ci_namespace_diagnostic_v1.py').read_bytes();new=(ROOT/'scripts/ci_namespace_diagnostic_v1.py').read_bytes()
assert new.count(b"'--dmesg'")==1 and new.replace(b"'--dmesg'",b"'--kernel'")==old
old_tree=ast.parse((E/'before/test_ci_namespace_diagnostic_v1.py').read_text());new_tree=ast.parse((ROOT/'tests/test_ci_namespace_diagnostic_v1.py').read_text())
def methods(tree):return {n.name:n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name.startswith('test_')}
class RevertLiteral(ast.NodeTransformer):
 def visit_Constant(self,node):
  if node.value=='--dmesg':node.value='--kernel'
  return node
old_tests=methods(old_tree);new_tests=methods(new_tree)
assert len(old_tests)==15 and len(new_tests)==16 and set(old_tests)<=set(new_tests)
assert set(new_tests)-set(old_tests)=={'test_actual_journalctl_parser_accepts_original_query_options_without_reading_journals'}
for name,node in old_tests.items():assert ast.dump(node)==ast.dump(RevertLiteral().visit(new_tests[name]))
verified=[]
for row in author['original_runs']:
 for reference in row['original_physical_leaves']:verified.append(verify(reference))
for row in author['original_hosted_unsupported_option_snapshots']:
 d=descriptor(ROOT/row['snapshot']);assert d['sha256']==row['sha256'] and d['size_bytes']==row['size_bytes'];verified.append(d)
red=doc(E/'red-01/test-results.json');green=doc(E/'green-01/test-results.json')
assert red['tests_run']==1 and len(red['failures'])==1 and not red['errors'] and not red['skips'] and red['successful'] is False
assert green['tests_run']==16 and green['successful'] and not green['failures'] and not green['errors'] and not green['skips']
assert (E/'red-01/actual-parser-00/stderr.raw').read_bytes()==(E/'before/original-hosted-query/namespace-diagnostic/kernel-query/stderr.raw').read_bytes()==b"/usr/bin/journalctl: unrecognized option '--kernel'\n"
for selection in ('red','green'):
 p=E/(selection+'-01');assert (p/'source.before.json').read_bytes()==(p/'source.after.json').read_bytes()
 result=doc(p/'execution.json');assert result['original_capture_completed'] and result['original_pid_absent'] and result['original_group_members']==[] and result['pipe_eof']=={'stdout':True,'stderr':True}
 assert result['source_stable'] and not result['timed_out'] and result['failure'] is None
 parser=doc(p/'actual-parser-00/capture.json');assert parser['capture_completed'] and parser['original_group_absent'] and parser['original_group_members']==[] and parser['eof']=={'stdout':True,'stderr':True}
 assert parser['returncode']==(1 if selection=='red' else 0) and not parser['timed_out'] and not parser['capture_exceeded']
 augmented=doc(p/'test-results.json')['real_parser_captures'][0]['capture']
 assert all(augmented[key]==value for key,value in parser.items())
 assert '--help' in parser['argv'] and augmented['gate_owner_executable_is_initial_python'] and augmented['post_exec_executable_observed'] is False
raw=(E/'green-01/stderr.raw').read_bytes();assert re.search(rb'Ran 16 tests in 0\.546s\s+OK\s*$',raw)
v6=doc(ROOT/author['scope']['host_v6']['path']);verify(author['scope']['host_v6']);assert len(v6['project_sources'])==87
assert all(r['path'] not in {row['path'] for row in v6['project_sources']} for r in final)
report={'schema_version':1,'artifact_kind':'vast_ci_journalctl_argument_independent_review_v1','disposition':'approved_source_and_closed_parser_fixture_scope','reviewable':True,'blockers':[], 'owned_sources':final,'original_sources':before,'author_review':review_ref,'owned_diff':verify(author['diff']),'scope_checks':{'complete_production_inverse_byte_equality_except_single_option':True,'all_original_15_test_methods_and_assertions_unchanged_after_option_literal_normalization':True,'one_added_production_argument_parser_regression':True,'project_source_87_intersection':[],'unchanged_20_plus_10_deadlines_64KiB_domain_2_plus_1_query_capture_and_original_owner_checks':True,'no_sudo_policy_or_namespace_predicate_change':True},'original_red':{'capture':descriptor(E/'red-01/execution.json'),'tests_run':1,'failure_count':1,'parser_returncode':1,'retained_original_unsupported_option':True},'original_green':{'capture':descriptor(E/'green-01/execution.json'),'tests_run':16,'successes':16,'failures':0,'errors':0,'skips':0,'unittest_elapsed_s':0.546,'capture_elapsed_s':doc(E/'green-01/execution.json')['elapsed_s'],'parser_returncode':0,'both_channels_EOF_and_original_child_groups_absent':True,'source_before_after_equal':True},'verified_closed_leaf_count':len(verified),'reviewer_operations':'Read source/diff, parse AST, rehash closed original records; no producer import, test rerun, actual namespace, journal read, engine, model, profile or remote call.','limits':['Actual --help proves supported spelling with the generated production arguments; it does not prove hosted journal permission, availability or an AppArmor root cause.','Original same-PID launch records prove the initial Python owner. The post-exec journal executable is explicitly unobserved.','The original hosted unsupported-option failure remains failed. Full CI, benchmark acceptance and namespace or policy causality remain unclaimed.'],'source_recheck':[descriptor(ROOT/r['path']) for r in final]}
assert report['source_recheck']==final
with (OUT/'review.v1.json').open('x') as out:json.dump(report,out,sort_keys=True,indent=2);out.write('\n')
print(json.dumps(descriptor(OUT/'review.v1.json')))