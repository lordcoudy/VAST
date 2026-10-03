"""Verify the actual repair commit against the frozen physical/index bytes."""
from pathlib import Path
import hashlib,json,os,subprocess
ROOT=Path('E:/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
HERE=Path(__file__).resolve().parent
COMMIT='2a6a42c924ae3447ceda4bd9d1b6db33765c6466'
BEFORE='958a036bc5a55821c712204577fdf4c51c2181c7'
GIT=['git','-c','gc.auto=0','-c','maintenance.auto=false','-c','core.longpaths=true']
def run(args):
 p=subprocess.run(GIT+args,cwd=ROOT,capture_output=True,timeout=15)
 assert p.returncode==0,(args,p.returncode,p.stderr[:1024]);return p.stdout
assert run(['rev-parse','HEAD']).decode().strip()==COMMIT
assert run(['diff','--cached','--name-only','-z'])==b''
freeze_path=HERE/'checkpoint-freeze.v1.json';b=freeze_path.read_bytes()
assert hashlib.sha256(b).hexdigest()=='2d1191ee94d903e5048ae6964ea064355e007203c674f4dc83342ab2595d0cbd'
freeze=json.loads(b); names=set(freeze['owned_files'])|{freeze_path.relative_to(ROOT).as_posix()}
names|={str((HERE/name).relative_to(ROOT)).replace('\\','/') for name in
 ('close_staged_checkpoint_attempt_v2.py','new-unscoped-whitespace-diagnostic.stdout.raw',
  'new-unscoped-whitespace-diagnostic.stderr.raw','staged-attempt-closure.v2.json')}
assert len(names)==205
assert set(run(['diff','--name-only','-z',BEFORE,COMMIT]).decode().split('\0'))-{''}==names
rows=[]
for name in sorted(names):
 raw=(ROOT/name).read_bytes()
 assert run(['show',COMMIT+':'+name])==run(['show',':'+name])==raw,name
 if name in freeze['owned_files']:
  p=freeze['owned_files'][name];assert len(raw)==p['size_bytes'] and hashlib.sha256(raw).hexdigest()==p['sha256']
 rows.append({'path':name,'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
receipt={'artifact_kind':'decision28_committed_checkpoint_physical_index_join_v1','schema_version':1,
 'previous_commit':BEFORE,'actual_source_checkpoint_A':COMMIT,'all205_physical_index_committed_equal':True,
 'index_empty':True,'owned_files':rows,'source_peer_sha256':freeze['source_peer_sha256'],
 'count_addendum_sha256':freeze['count_addendum_sha256'],'authored_whitespace_scope_passed':True,
 'original_failed_staging_check_retained':True,'hardware_or_fullCI_accepted':False,'source_renewal_pending':True}
out=(json.dumps(receipt,sort_keys=True,indent=2)+'\n').encode()
with (HERE/'committed-checkpoint-proof.v1.json').open('xb') as f:f.write(out);f.flush();os.fsync(f.fileno())
print(json.dumps({'source_checkpoint_A':COMMIT,'owned_files':205,'physical_index_committed_equal':True,
 'proof_size_bytes':len(out),'proof_sha256':hashlib.sha256(out).hexdigest()}))
