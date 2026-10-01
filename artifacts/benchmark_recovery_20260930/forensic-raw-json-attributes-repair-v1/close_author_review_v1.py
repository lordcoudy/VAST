"""Close finite source/effect and original Git fixture evidence; no new workload."""
import hashlib,json,os,stat,subprocess,time
from pathlib import Path
ROOT=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
HERE=Path(__file__).resolve().parent
FAILED=Path('/home/s-a-balashov/work/vast-current-source-ci-20261001-supervisor')
GIT=['/usr/bin/git','-c','core.longpaths=true','--git-dir=/mnt/e/STUDY/VAST/.git/worktrees/fix-benchmark-preparations-spec','--work-tree='+str(ROOT)]
def ep(i):return [i.st_dev,i.st_ino,i.st_mode,i.st_nlink,i.st_size,i.st_mtime_ns,i.st_ctime_ns]
def pin(p):
    p=Path(p);i=p.lstat();assert stat.S_ISREG(i.st_mode) and i.st_size<8*1024*1024
    fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
    try:
        before=ep(os.fstat(fd));assert before==ep(i);sha=hashlib.sha256();count=0
        while True:
            raw=os.read(fd,262144)
            if not raw:break
            count+=len(raw);sha.update(raw)
        assert before==ep(os.fstat(fd))==ep(p.lstat()) and count==i.st_size
    finally:os.close(fd)
    return {'path':str(p),'size_bytes':count,'sha256':sha.hexdigest(),'epoch':before}
proposal=json.loads((HERE/'preedit-proposal-and-authorization.v1.json').read_bytes())
execution_path=HERE/'controlled-original-attempt01/execution.v1.json'
execution=json.loads(execution_path.read_bytes());assert execution['status']=='passed_fixture_only' and execution['elapsed_s']<120
assert len(execution['actual_original_commands'])==109
old=(HERE/'gitattributes.before.raw').read_bytes();new=(ROOT/'.gitattributes').read_bytes()
assert new==(HERE/'gitattributes.after.raw').read_bytes() and new.startswith(old)
expected_append=b'\n# Preserve these exact retained forensic JSON blobs; automatic clean must not normalize them.\n'+('\n'.join(proposal['proposed_only_mutation']['append_exact_rules'])+'\n').encode('ascii')
assert new==old+expected_append
assert hashlib.sha256(new).hexdigest()=='27b8b1feaaaa51f2b01de423cfa4824d4f351613650f5b2fe137295610237c3f'
source_after=[]
for relative,original in proposal['before_source_descriptors'].items():
    current=pin(ROOT/relative);assert current==original;source_after.append(current)
original_json_after=[]
for row in proposal['findings']:
    primary=pin(ROOT/row['path']);failed=pin(FAILED/row['path'])
    assert primary==row['original_git_and_primary'] and failed==row['failed_checkout']
    original_json_after.append({'path':row['path'],'primary':primary,'retained_failed_checkout':failed})
env={**os.environ,'GIT_OPTIONAL_LOCKS':'0'}
head=subprocess.run(GIT+['rev-parse','HEAD'],capture_output=True,check=True,timeout=10,env=env).stdout.decode().strip();assert head==proposal['source_commit']
attributes=subprocess.run(GIT+['check-attr','-z','text','eol','--stdin'],input=('\0'.join(r['path'] for r in proposal['findings'])+'\0').encode(),capture_output=True,check=True,timeout=10,env=env).stdout
f=attributes.decode().split('\0')[:-1];effective=[{'path':f[i],'attribute':f[i+1],'value':f[i+2]} for i in range(0,len(f),3)]
assert all(x['value']==('unset' if x['attribute']=='text' else 'unspecified') for x in effective)
groups={r['owner']['pgid'] for r in execution['actual_original_commands']}
controller=execution['controller'];groups.add(controller['pgid']);pids={r['owner']['pid'] for r in execution['actual_original_commands']}|{controller['pid']}
scans=[]
for _ in range(2):
    matches=[];observed=time.time_ns()
    for proc in Path('/proc').iterdir():
        if not proc.name.isdecimal():continue
        try:
            raw=(proc/'stat').read_text();tail=raw[raw.rfind(')')+2:].split();pid=int(proc.name);pgid=int(tail[2])
            if pid in pids or pgid in groups:matches.append({'pid':pid,'pgid':pgid,'startticks':int(tail[19]),'state':tail[0]})
        except (FileNotFoundError,ProcessLookupError,PermissionError):continue
    assert not matches,matches
    scans.append({'observed_at_ns':observed,'exact_original_PIDs_and_groups':sorted(pids),'matches':matches})
owned=[]
for p in sorted(HERE.rglob('*')):
    if p.is_file():owned.append(pin(p))
report={'schema_version':1,'kind':'vast_finite_forensic_json_attributes_author_review_v1','source_commit':head,'status':'frozen_pending_independent_peer',
 'only_production_path':pin(ROOT/'.gitattributes'),'exact_15_rules':proposal['proposed_only_mutation']['append_exact_rules'],
 'attributes_before':pin(HERE/'gitattributes.before.raw'),'unchanged_original_prefix_bytes':len(old),'added_bytes':len(expected_append),
 'all_original_LF_contract_lines_preserved':True,'no_wildcard_or_payload_change':True,'no_source_normalization_or_renormalize':True,
 'original_cause':'All fifteen failed checkout files equal their original e897 CRLF Git blobs. Original text/eol=lf automatic clean transforms them to different LF object IDs, so Git status reports modified. The exact exceptions disable that transformation.',
 'original_setup_remains_failed_untouched':True,'future_full_CI_requires_new_exact_source_commit_and_checkout':True,
 'preedit_proposal':pin(HERE/'preedit-proposal-and-authorization.v1.json'),'controlled_original_execution':pin(execution_path),
 'controlled_RED':'Original actual fifteen blobs and attrs reproduce fifteen modified paths, with raw bytes equal original Git and clean objects unequal.',
 'controlled_GREEN':'New attrs retain all fifteen exact raw and clean blob identities and yield empty status in fresh initial autocrlf=false and true checkouts.',
 'controlled_fixture_only_attrs_commit_changed':True,'controlled_scratch_outside_evidence':execution['scratch_root'],
 'actual_Git_children':109,'actual_original_elapsed_s':execution['elapsed_s'],'two_actual_process_scans':scans,'all_capture_and_review_fds_closed':True,
 'source_scope':{'host87_intersection':[],'selected73_intersection':[],'native3_worker2_and_runtime4_intersections':{},'all9_manifest_source_members_unchanged':len(source_after),'after_descriptors':source_after},
 'original_15_payload_and_failed_checkout_descriptors_unchanged':original_json_after,'current_effective_attributes':effective,
 'tool_observations':[{'source':'diagnose_v1.py','original_tool_chunk_id':'99d8b5','rc':1,'error':'AssertionError: incorrect unpublished assumption raw checkout must differ; no source edits.'},
 {'source':'diagnose_v2.py','original_tool_chunk_id':'2f831e','rc':1,'error':'AssertionError: newline input supplied to check-attr -z; no source edits.'},
 {'source':'diagnose_v3.py','original_tool_chunk_id':'800eb6','rc':0,'resolution':'Required NUL-separated stdin; actual fifteen automatic-clean mismatches proved before attribute append.'}],
 'owned_finite_files':owned,'tests_or_CI_acceptance':False,'benchmark_or_engine_or_model_invocations':0,
 'review_limits':['The controlled small fixture proves these fifteen blobs and attrs, not a complete new source checkout or full CI pass.',
 'No original payload, failed checkout or 0ad benchmark input/authority is rebound or modified. Hosted run32 has no inferred outcome here.',
 'Original setup failed before any full CI/model/native/benchmark operation; failed roots and originals stay retained.',
 'No .git directory is inside the finite owned evidence folder; scratch repositories stay external and are not swept or deleted.'],
 'self_review':'Minimal fix is finite attributes rather than rewriting forensic JSON. Preserve declared LF production contracts and original failed setup; require independent source/effect peer, root checkpoint and new exclusive current-source CI setup.'}
for path,data in proposal['source_groups'].items():report['source_scope']['native3_worker2_and_runtime4_intersections'][path]={'count':data['count'],'intersection':[],'manifest':data['manifest']}
out=HERE/'author-review.v1.json';raw=(json.dumps(report,indent=2,sort_keys=True,ensure_ascii=True)+'\n').encode('ascii')
with out.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
print(json.dumps({'path':str(out),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'source_members':len(source_after),'controller_and_children_absent':True}))
