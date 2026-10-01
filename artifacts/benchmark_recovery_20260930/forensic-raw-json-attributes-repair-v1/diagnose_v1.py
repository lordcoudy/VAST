"""Original finite JSON checkout diagnosis and pre-edit authorization record.
Reads real retained status, blobs and files; never repairs the failed checkout.
"""
import hashlib,json,os,stat,subprocess,time
from pathlib import Path
ROOT=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
HERE=Path(__file__).resolve().parent
FAILED=Path('/home/s-a-balashov/work/vast-current-source-ci-20261001-supervisor')
COMMIT='e897514dbefe3015756995d05f924aa44dd39552'
START=time.monotonic_ns();DEADLINE=START+60_000_000_000
GIT=['/usr/bin/git','-c','core.longpaths=true','--git-dir=/mnt/e/STUDY/VAST/.git/worktrees/fix-benchmark-preparations-spec','--work-tree='+str(ROOT)]
reads={};commands=[]
def ep(i):return [i.st_dev,i.st_ino,i.st_mode,i.st_nlink,i.st_size,i.st_mtime_ns,i.st_ctime_ns]
def read(p):
    p=Path(p);i=p.lstat();assert stat.S_ISREG(i.st_mode) and i.st_size<=8*1024*1024
    fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
    try:
        e=ep(os.fstat(fd));assert e==ep(i);parts=[]
        while True:
            raw=os.read(fd,262144)
            if not raw:break
            parts.append(raw)
        raw=b''.join(parts);assert e==ep(os.fstat(fd))==ep(p.lstat()) and len(raw)==i.st_size
    finally:os.close(fd)
    reads[str(p)]={'path':str(p),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'epoch':e}
    return raw
def run(argv,input=None):
    assert time.monotonic_ns()<DEADLINE
    s=time.monotonic_ns();p=subprocess.run(argv,input=input,capture_output=True,timeout=min(15,(DEADLINE-s)/1e9),check=True)
    commands.append({'argv':argv,'returncode':p.returncode,'elapsed_s':(time.monotonic_ns()-s)/1e9,'stdout_sha256':hashlib.sha256(p.stdout).hexdigest(),'stderr_sha256':hashlib.sha256(p.stderr).hexdigest()})
    return p.stdout
def write(p,raw):
    p=Path(p)
    with p.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    return {'path':str(p),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def save(name,value):return write(HERE/name,(json.dumps(value,indent=2,sort_keys=True)+'\n').encode('utf-8'))
status_path=ROOT/'artifacts/benchmark_recovery_20260930/component-current-source-ci-supervisor-preparation-v1/original-setup-attempt01/07-setup.stdout.raw'
original_status=read(status_path)
entries=[s for s in original_status.split(b'\0') if s]
assert len(entries)==15 and all(s[:3]==b' M ' for s in entries)
paths=[s[3:].decode('utf-8') for s in entries]
assert len(set(paths))==15 and all(p.startswith('artifacts/benchmark_recovery_20260930/') and p.endswith('.json') and '..' not in Path(p).parts for p in paths)
assert run(GIT+['rev-parse','HEAD']).decode().strip()==COMMIT
assert run(['/usr/bin/git','-c','core.longpaths=true','-C',str(FAILED),'rev-parse','HEAD']).decode().strip()==COMMIT
refs=['.gitattributes']+paths
batch=run(GIT+['cat-file','--batch'],(''.join(COMMIT+':'+p+'\n' for p in refs)).encode())
pos=0;blobs={}
for path in refs:
    end=batch.index(b'\n',pos);header=batch[pos:end].decode().split();assert len(header)==3 and header[1]=='blob'
    size=int(header[2]);pos=end+1;raw=batch[pos:pos+size];pos+=size;assert batch[pos:pos+1]==b'\n';pos+=1
    blobs[path]=(header[0],raw)
assert pos==len(batch)
attrs=read(ROOT/'.gitattributes');assert attrs==blobs['.gitattributes'][1]
write(HERE/'gitattributes.before.raw',attrs)
(HERE/'original-git-json-blobs').mkdir()
rows=[]
for index,path in enumerate(paths,1):
    blob_id,raw=blobs[path];current=read(ROOT/path);failed=read(FAILED/path)
    assert raw==current and raw!=failed
    assert raw.replace(b'\r\n',b'\n')==failed and b'\r\n' in raw and b'\r\n' not in failed
    saved=write(HERE/'original-git-json-blobs'/f'{index:02}.json.raw',raw)
    rows.append({'path':path,'git_blob_id':blob_id,'original_git_and_primary':reads[str(ROOT/path)],'failed_checkout':reads[str(FAILED/path)],'raw_bytes_equal':False,'difference':'CRLF Git/primary bytes were checked out as LF under *.json text eol=lf','raw_CRLF_count':raw.count(b'\r\n'),'saved_original_git_blob':saved})
stdin=('\n'.join(paths)+'\n').encode()
original_attr=run(GIT+['check-attr','-z','text','eol','--stdin'],stdin)
failed_attr=run(['/usr/bin/git','-c','core.longpaths=true','-C',str(FAILED),'check-attr','-z','text','eol','--stdin'],stdin)
assert original_attr==failed_attr
fields=original_attr.decode().split('\0');fields=fields[:-1]
observed=[]
for i in range(0,len(fields),3):observed.append({'path':fields[i],'attribute':fields[i+1],'value':fields[i+2]})
assert all(x['value']==('set' if x['attribute']=='text' else 'lf') for x in observed)
write(HERE/'original-effective-attributes.raw',original_attr)
hostpath=ROOT/'artifacts/gstreamer_component_release_20260930_a4e145b7/host/execution-code-closure.v6.json'
host=json.loads(read(hostpath));host_paths={x['path'] for x in host['project_sources']};assert len(host_paths)==87
manifests=[
 'deploy/gstreamer_custom/publication/runtime-source-allowlist.txt',
 'deploy/deepstream/checkpoint/runtime-source-allowlist.txt',
 'deploy/openvino_gva/publication/runtime-source-allowlist.txt',
 'deploy/savant/publication/runtime-source-allowlist.txt',
 'deploy/native_gst_probe/publication/deepstream-source-allowlist.txt',
 'deploy/native_gst_probe/publication/openvino-source-allowlist.txt',
 'deploy/native_gst_probe/publication/savant-source-allowlist.txt',
 'deploy/analytics_execution/publication/openvino-source-allowlist.txt',
 'deploy/analytics_execution/publication/tensorrt-source-allowlist.txt']
groups={};source_paths=set(host_paths)
for manifest in manifests:
    raw=read(ROOT/manifest)
    entries={s.strip() for s in raw.decode('ascii').splitlines() if s.strip() and not s.startswith('#')}
    assert not entries.intersection(set(refs))
    groups[manifest]={'manifest':reads[str(ROOT/manifest)],'members':sorted(entries),'count':len(entries),'changed_path_intersection':[]}
    source_paths.update(entries)
assert len(groups[manifests[0]]['members'])==73
assert not host_paths.intersection(set(refs))
before_sources={}
for p in sorted(source_paths):
    read(ROOT/p);before_sources[p]=reads[str(ROOT/p)]
lf_rules=[line for line in attrs.decode('ascii').splitlines() if line.strip() and not line.startswith('#') and 'text eol=lf' in line]
proposal={'schema_version':1,'artifact_kind':'vast_finite_forensic_raw_json_attributes_preedit_v1','source_commit':COMMIT,
 'original_failed_setup_status':reads[str(status_path)],'findings':rows,'effective_original_attributes':observed,
 'proposed_only_mutation':{'path':'.gitattributes','append_exact_rules':[f'/{p} -text !eol' for p in paths]},
 'preserve':'Every JSON payload, original failed checkout and original LF source contract remains untouched. No wildcard, normalization, renormalize, reset, clean or retry.',
 'standing_authorization':'Root explicitly authorized this narrow existing Decision25 finite raw-byte/attributes repair before edits under the human carte-blanche. The exact original status list determines all fifteen exceptions; no normative design is changed.',
 'necessary_cause':'The stager retained original CRLF Git blobs while *.json text eol=lf makes fresh checkout LF and automatic clean converts the working file to LF, yielding a mismatch to the original CRLF index. Exact -text !eol retains raw forensic bytes in new checkouts.',
 'existing_LF_rule_lines':lf_rules,'source_groups':groups,'host87_members':sorted(host_paths),'authority_source_path_intersection':[],
 'before_source_descriptors':before_sources,'commands':commands,'all_read_fds_closed':True,'elapsed_s':(time.monotonic_ns()-START)/1e9,
 'acceptance':False,'original_full_CI_started':False,'hardware_or_model_invocations':0,
 'future_requirement':'New source commit and exclusive fresh CI checkout after independent review. The failed e897 checkout is preserved unchanged.'}
out=save('preedit-proposal-and-authorization.v1.json',proposal)
save('source-input-read-inventory.v1.json',{'files':list(reads.values()),'all_read_fds_closed':True,'no_source_mutation':True})
print(json.dumps({'proposal':out,'paths':paths,'source_members':len(source_paths),'elapsed_s':(time.monotonic_ns()-START)/1e9}))
