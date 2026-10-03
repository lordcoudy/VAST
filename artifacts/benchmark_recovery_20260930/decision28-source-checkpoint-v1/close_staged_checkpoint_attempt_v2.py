"""Close the completed finite stage after an overbroad forensic whitespace check."""
from pathlib import Path
import hashlib, json, os, stat, subprocess

ROOT = Path('E:/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
HERE = Path(__file__).resolve().parent
HEAD = '958a036bc5a55821c712204577fdf4c51c2181c7'
GIT = ['git','-c','gc.auto=0','-c','maintenance.auto=false','-c','core.longpaths=true']
def call(args):
    p = subprocess.run(GIT+args,cwd=ROOT,capture_output=True,timeout=15)
    assert len(p.stdout) <= 8*1024*1024 and len(p.stderr) <= 65536
    return p
def ok(args):
    p = call(args); assert p.returncode == 0,(args,p.returncode,p.stderr[:1024]); return p.stdout
def epoch(s):
    return [s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
def exclusive(path,raw):
    with path.open('xb') as f:
        assert f.write(raw) == len(raw); f.flush(); os.fsync(f.fileno())
def desc(path):
    b=path.read_bytes(); return {'path':path.relative_to(ROOT).as_posix(),'size_bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
freeze_path = HERE/'checkpoint-freeze.v1.json'
freeze_raw = freeze_path.read_bytes()
assert len(freeze_raw) == 85428 and hashlib.sha256(freeze_raw).hexdigest() == '2d1191ee94d903e5048ae6964ea064355e007203c674f4dc83342ab2595d0cbd'
freeze=json.loads(freeze_raw)
assert freeze['previous_head'] == HEAD and freeze['prospective_raw_clean_equality_autocrlf_false_true'] is True
assert ok(['rev-parse','HEAD']).decode().strip() == HEAD
expected=set(freeze['owned_files'])|{freeze_path.relative_to(ROOT).as_posix()}
actual=set(ok(['diff','--cached','--name-only','-z']).decode().split('\0'))-{''}
assert actual == expected and len(expected) == 201
for name in sorted(expected):
    path=ROOT/name; before=path.lstat(); b=path.read_bytes()
    assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and epoch(path.lstat()) == epoch(before)
    assert ok(['show',':'+name]) == b
    if name in freeze['owned_files']:
        saved=freeze['owned_files'][name]
        assert len(b)==saved['size_bytes'] and hashlib.sha256(b).hexdigest()==saved['sha256']
        assert epoch(before)==saved['epoch7']
# This is a NEW read-only diagnostic, not recovered original stage stdout.
diagnostic=call(['diff','--cached','--check'])
assert diagnostic.returncode == 2 and diagnostic.stderr == b''
exclusive(HERE/'new-unscoped-whitespace-diagnostic.stdout.raw',diagnostic.stdout)
exclusive(HERE/'new-unscoped-whitespace-diagnostic.stderr.raw',diagnostic.stderr)
authored=['.gitattributes','BENCHMARK_RECOVERY_PLAN.md',
    'openspec/changes/fix-benchmark-preparations-spec/tasks.md',
    'scripts/checkpoint_gstreamer_analytics_sidecar.py','scripts/publication_operational_process_custody_v1.py',
    'tests/test_checkpoint_gstreamer_analytics_sidecar.py','tests/test_publication_operational_process_custody_v1.py',
    'tests/test_publication_worker_termination_facts_v1.py']
scoped=call(['-c','core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol',
    'diff','--cached','--check','--',*authored])
assert scoped.returncode == 0 and scoped.stdout == scoped.stderr == b''
receipt={'artifact_kind':'decision28_staged_checkpoint_attempt_closure_v2','schema_version':2,
    'baseline_commit':HEAD,'original_staging_script_tool_session':4382,'original_staging_script_exit_code':1,
    'original_final_Git_diff_check_returncode':2,
    'original_failure':'Final unscoped whitespace check treated immutable retained logs/source snapshots/diffs as newly authored source and CR as trailing whitespace; all201 physical/index joins had completed.',
    'original_unscoped_full_stdout_retained':False,
    'new_diagnostic_label':'New read-only observation at the unchanged staged index; not original execution stdout.',
    'new_unscoped_diagnostic_returncode':diagnostic.returncode,
    'new_unscoped_stdout':desc(HERE/'new-unscoped-whitespace-diagnostic.stdout.raw'),
    'new_unscoped_stderr':desc(HERE/'new-unscoped-whitespace-diagnostic.stderr.raw'),
    'authored_code_test_docs_paths':authored,'authored_whitespace_check_returncode':0,
    'authored_whitespace_policy':'blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol; explicit CR matches reviewed existing byte contracts.',
    'retained_forensic_evidence_whitespace_normalized':False,
    'all201_original_staged_physical_index_and_frozen_bytes_epochs_equal':True,
    'source_test_snapshot_bytes_modified':False,'original_failed_stage_immutable':True,
    'benchmark_or_fullCI_accepted':False,'status':'closed_finite_stage_with_scoped_authored_whitespace_check'}
receipt_raw=(json.dumps(receipt,sort_keys=True,indent=2)+'\n').encode()
exclusive(HERE/'staged-attempt-closure.v2.json',receipt_raw)
new_paths=[Path(__file__).resolve(),HERE/'new-unscoped-whitespace-diagnostic.stdout.raw',
    HERE/'new-unscoped-whitespace-diagnostic.stderr.raw',HERE/'staged-attempt-closure.v2.json']
owned={}
for path in new_paths:
    s=path.lstat(); b=path.read_bytes()
    assert stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_size<=8*1024*1024 and epoch(path.lstat())==epoch(s)
    name=path.relative_to(ROOT).as_posix(); oid=hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
    for setting in ('false','true'):
        p=subprocess.run(GIT+['-c','core.autocrlf='+setting,'hash-object','--path='+name,'--stdin'],cwd=ROOT,input=b,capture_output=True,timeout=15)
        assert p.returncode==0 and p.stdout.decode().strip()==oid
    owned[name]=b
for name,b in owned.items():
    p=subprocess.run(GIT+['hash-object','-w','--stdin'],cwd=ROOT,input=b,capture_output=True,timeout=15)
    assert p.returncode==0
    ok(['update-index','--add','--cacheinfo','100644,'+p.stdout.decode().strip()+','+name])
assert set(ok(['diff','--cached','--name-only','-z']).decode().split('\0'))-{''} == expected|set(owned)
for name in expected|set(owned): assert ok(['show',':'+name]) == (ROOT/name).read_bytes()
print(json.dumps({'owned_staged_file_count':205,'all_physical_index_equal':True,
    'authored_code_test_docs_whitespace_check_passed':True,'original_raw_evidence_preserved':True,
    'closure':desc(HERE/'staged-attempt-closure.v2.json')}))
