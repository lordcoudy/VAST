"""Join actual checkpointB physical/index/commit bytes and every selected source to A."""
from pathlib import Path
import hashlib,json,os,subprocess
ROOT=Path('E:/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
HERE=Path(__file__).resolve().parent
A='2a6a42c924ae3447ceda4bd9d1b6db33765c6466'
B='a00aa57f7d9534f8e7920f14f70d6a75a23570ed'
GIT=['git','-c','gc.auto=0','-c','maintenance.auto=false','-c','core.longpaths=true']
def run(args):
    p=subprocess.run(GIT+args,cwd=ROOT,capture_output=True,timeout=15)
    assert p.returncode==0,(args,p.returncode,p.stderr[:1024]);return p.stdout
assert run(['rev-parse','HEAD']).decode().strip()==B
assert run(['diff','--cached','--name-only','-z'])==b''
fp=HERE/'checkpoint-freeze.v1.json';fr=fp.read_bytes()
assert len(fr)==56672 and hashlib.sha256(fr).hexdigest()=='487ce8abb2085a84c2cd9d5516b5994cf7264f10798d47d2488077fc864e306f'
freeze=json.loads(fr);names=set(freeze['owned_files'])|{fp.relative_to(ROOT).as_posix()}
assert len(names)==132
assert set(run(['diff','--name-only','-z',A,B]).decode().split('\0'))-{''}==names
owned=[]
for name in sorted(names):
    raw=(ROOT/name).read_bytes();assert run(['show',B+':'+name])==run(['show',':'+name])==raw,name
    if name in freeze['owned_files']:
        row=freeze['owned_files'][name];assert len(raw)==row['size_bytes'] and hashlib.sha256(raw).hexdigest()==row['sha256']
    owned.append({'path':name,'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
peer_path=ROOT/'artifacts/benchmark_recovery_20260930/decision28-host-image-independent-review-v1/review.v1.json'
pb=peer_path.read_bytes();assert len(pb)==30902 and hashlib.sha256(pb).hexdigest()=='83d27f58d5e54f1ae48c2df98bf2fa61c8f8f8e39a530bf49fbf91084166d9eb'
peer=json.loads(pb);selected=[]
for row in peer['selected73_current_pins']:
    name=row['path'];raw=(ROOT/name).read_bytes()
    assert run(['show',A+':'+name])==run(['show',B+':'+name])==raw,name
    assert run(['ls-tree',A,'--',name])==run(['ls-tree',B,'--',name]),name
    assert len(raw)==row['size_bytes'] and hashlib.sha256(raw).hexdigest()==row['sha256']
    selected.append(dict(row))
assert len(selected)==73 and 'scripts/checkpoint_gstreamer_publication_runtime_v3.py' not in {r['path'] for r in selected}
v={'schema_version':1,'source_checkpoint_A':A,'actual_host_identity_checkpoint_B':B,
    'all132_physical_index_committed_equal':True,'index_empty':True,'owned_files':owned,
    'selected73_A_B_physical_bytes_and_Git_modes_equal':True,'selected73':selected,
    'selected_image_rebuild_after_B_required':False,'image_id':'sha256:222a0003661e8229a431c69a513d7352294e6a38028abeb5b133aab45b3945a1',
    'host_source_peer_sha256':'83d27f58d5e54f1ae48c2df98bf2fa61c8f8f8e39a530bf49fbf91084166d9eb',
    'current_host_closure_current95_CPU_GPU_local_fullCI_pending':True,'hardware_acceptance':False}
q=HERE/'committed-checkpoint-proof.v1.json';raw=(json.dumps(v,sort_keys=True,indent=2)+'\n').encode()
with q.open('xb') as o:o.write(raw);o.flush();os.fsync(o.fileno())
print(json.dumps({'checkpoint_B':B,'owned_files':132,'selected73_A_B_unchanged':True,'proof_size_bytes':len(raw),'proof_sha256':hashlib.sha256(raw).hexdigest()}))
