"""Own only the namespace test file; preserve exact preexisting bytes and ASTs."""
import ast,hashlib,json
from pathlib import Path
OUT=Path(__file__).parent
WORK=OUT.parents[2]
TARGET=WORK/'tests/test_ci_namespace_diagnostic_v1.py'
BEFORE=OUT.parent/'decision29-ci-clock-repair-v1/before/tests__test_ci_namespace_diagnostic_v1.py.raw'
old=BEFORE.read_bytes();assert TARGET.read_bytes()==old
assert len(old)==20805 and hashlib.sha256(old).hexdigest()=='37d771d553a76cbbaf6d878ab10cc2a7f409bb054c41ada8f36daba16da91223'
newline=b'\r\n' if b'\r\n' in old else b'\n'
marker=newline+newline+b"if __name__ == '__main__':"
assert old.count(marker)==1
chunk=(OUT/'new_methods.v1.raw').read_bytes().replace(b'\r\n',b'\n').replace(b'\n',newline)
new=old.replace(marker,newline+newline+chunk+marker)
assert new.replace(newline+newline+chunk+marker,marker)==old
def methods(raw):
    tree=ast.parse(raw)
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='NamespaceDiagnosticTests')
    return {n.name:ast.dump(n,include_attributes=False) for n in cls.body if isinstance(n,ast.FunctionDef)}
a,b=methods(old),methods(new)
assert all(b[name]==value for name,value in a.items())
old_tests=[name for name in a if name.startswith('test')];new_tests=[name for name in b if name.startswith('test') and name not in a]
assert len(old_tests)==16 and len(new_tests)==6
TARGET.write_bytes(new)
def pin(path,raw):return {'path':path.as_posix(),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
report={'schema_version':1,'scope':'Source-only namespace wrapper tests author; no test execution or real namespace/policy/journal/child operations.','author':'/root/decision28_source_peer','reviewed_planning_commit':'56dd56bcc80519b99357546a49dbd65377e0db22','authorization_PR_comment':'https://github.com/lordcoudy/VAST/pull/2#issuecomment-5967478840','owned_source_pins':[pin(TARGET,new)],'original_snapshot':pin(BEFORE,old),'all_existing_file_bytes_preserved_by_exact_inverse':True,'all_original_class_method_ASTs_unchanged':True,'all_original_assertions_preserved_in_method_ASTs':True,'original_test_method_count':16,'new_test_method_count':6,'new_test_methods':new_tests,'new_fixture_helpers':[name for name in b if name not in a and not name.startswith('test')],'tests_executed':False,'synthetic_only':True,'test_behaviors':['Exact USER-unshare pre-sample on start+completed, failed-setgroups-open post-sample after original terminal; genuine-format synthetic value/clock/phase/PID/boot/time fields and ordered exactly-once delegates.','Failed USER-unshare retains one pre sample and identical original exception.','Clock OSError yields explicit unavailable facts; both original delegates execute once and original open error remains identical. Unavailable terminal clock is not fabricated.','Pre/post KeyboardInterrupt and SystemExit propagate; bindings restore, and post-cancellation retains original denial in its exception context.','Non-USER unshare, uid_map/unrelated opens, successful setgroups open, pipe2 and mount do not sample coarse time.'],'first_cause_or_hardware_acceptance_not_invented':True,'future_test_result':None}
with (OUT/'author.v1.json').open('xb') as f:f.write((json.dumps(report,sort_keys=True,indent=2)+'\n').encode())
print(json.dumps({'source':report['owned_source_pins'][0],'original_methods_unchanged':len(a),'old_tests':old_tests,'new_tests':new_tests}))
