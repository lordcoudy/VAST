"""Complete the immutable v1 map with source-specific AST/EOL and focused joins.

This reads original Git blobs and closed unit metadata only. No project imports,
unit execution, media reads or authority renewal. Raw byte distinctions survive.
"""
import ast, hashlib, json, os, re, stat, subprocess, time
from pathlib import Path
ROOT=Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
HERE=Path(__file__).resolve().parent
BASE='artifacts/benchmark_recovery_20260930/'
START=time.monotonic_ns();DEADLINE=START+120_000_000_000
pins={};TOTAL=0
def read(relative):
    global TOTAL
    assert time.monotonic_ns()<DEADLINE
    p=ROOT/relative;i=p.lstat();assert stat.S_ISREG(i.st_mode) and not stat.S_ISLNK(i.st_mode) and i.st_size<8*1024*1024
    fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
    try:
        def ep(x):return [x.st_dev,x.st_ino,x.st_mode,x.st_nlink,x.st_size,x.st_mtime_ns,x.st_ctime_ns]
        original=ep(os.fstat(fd));assert original==ep(i)
        chunks=[]
        while True:
            raw=os.read(fd,262144)
            if not raw:break
            chunks.append(raw)
        data=b''.join(chunks);assert len(data)==i.st_size and ep(os.fstat(fd))==original==ep(p.lstat())
    finally:os.close(fd)
    TOTAL+=len(data);assert TOTAL<64*1024*1024
    pins[relative]={'path':relative,'size_bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'epoch':original}
    return data
def doc(relative):return json.loads(read(relative))
def ref(relative):read(relative);return dict(pins[relative])
def ast_hash(raw):return hashlib.sha256(ast.dump(ast.parse(raw),include_attributes=False).encode()).hexdigest()
mapping=doc(str((HERE/'mapping.v1.json').relative_to(ROOT)))
prior_review=doc(str((HERE/'review.v1.json').relative_to(ROOT)))
before=doc(BASE+'ci-4cb9-two-failure-diagnosis-v1/original-member-copies-v1/tracked-source.before.json.original.raw')
files=set(t['source']['path'] for t in mapping['tests'].values())|set(s['source']['path'] for s in mapping['source_anchors'].values())
paths=sorted(p for p in files if p in before)
git=['git','-c','core.longpaths=true','--git-dir=/mnt/e/STUDY/VAST/.git/worktrees/fix-benchmark-preparations-spec','--work-tree='+str(ROOT)]
commit='4cb9d8313cca71256179bc3b59cc6f9137e7b8ba'
request=''.join(commit+':'+p+'\n' for p in paths).encode()
result=subprocess.run(git+['cat-file','--batch'],input=request,capture_output=True,timeout=30,check=True)
payload=result.stdout;pos=0;joins={}
for p in paths:
    end=payload.index(b'\n',pos);header=payload[pos:end].decode('ascii').split();assert len(header)==3 and header[1]=='blob'
    n=int(header[2]);pos=end+1;original=payload[pos:pos+n];pos+=n
    assert payload[pos:pos+1]==b'\n';pos+=1
    original_sha=hashlib.sha256(original).hexdigest();assert original_sha==before[p]['sha256'] and n==before[p]['size_bytes'],p
    current=read(p);raw_equal=current==original
    normalized_equal=current.replace(b'\r\n',b'\n')==original.replace(b'\r\n',b'\n')
    py_equal=ast_hash(current)==ast_hash(original) if p.endswith('.py') else None
    joins[p]={'original_commit':commit,'git_blob_id':header[0],'original_bytes':{'size_bytes':n,'sha256':original_sha},
      'current':dict(pins[p]),'raw_equal':raw_equal,'CR_at_EOL_equivalent':normalized_equal,'python_AST_equal':py_equal,
      'meaning':'Raw bytes are never equated by normalization. Exact EOL equivalence allows a scoped same-assertion interpretation only; it does not renew physical runtime authority.'}
assert pos==len(payload)

focused=[]
for receipt,stderr,kind in [
 (BASE+'decoder-research-v5-focused-tests/attempt-01/terminal.v1.json',BASE+'decoder-research-v5-focused-tests/attempt-01/original.stderr','artifact research protocol/failure fixtures, no accepted decoder cohort'),
 (BASE+'broker-terminal-owner-repair-v1/attempt-02-green/execution.v1.json',BASE+'broker-terminal-owner-repair-v1/attempt-02-green/stderr.raw','isolated real child/journal owner boundary'),
 (BASE+'broker-terminal-owner-repair-v1/attempt-03-observation-cleanup-green/execution.v1.json',BASE+'broker-terminal-owner-repair-v1/attempt-03-observation-cleanup-green/stderr.raw','two final real winner/loser boundary cases'),
 (BASE+'ci-4cb9-two-failure-diagnosis-v1/capacity-fixture-focused-attempt02/terminal.v1.json',BASE+'ci-4cb9-two-failure-diagnosis-v1/capacity-fixture-focused-attempt02/stderr.raw','genuine local CLI process custody fixtures')]:
    d=doc(receipt);raw=read(stderr);assert d['returncode']==0 and not d['timed_out']
    assert d['source_before']==d['source_after']
    assert hashlib.sha256(raw).hexdigest()==d['stderr']['sha256']
    assert len(raw)==d['stderr']['size_bytes']
    ids=[]
    for line in raw.decode('utf-8').splitlines():
        hit=re.match(r'(test_[A-Za-z0-9_]+) \(([^)]+)\).*\.\.\. ok$',line)
        if hit:
            name,qual=hit.groups();ids.append(qual if qual.endswith('.'+name) else qual+'.'+name)
    focused.append({'receipt':ref(receipt),'stderr':ref(stderr),'classification':kind,'successful_ids':ids,'source_before':d['source_before'],'whole_CI_or_hardware_acceptance':False})

broker_old_path=BASE+'broker-terminal-owner-repair-v1/test_before_observation_cleanup_fix.raw'
broker_old=read(broker_old_path)
assert hashlib.sha256(broker_old).hexdigest()=='aa427e5e4ecd2e9e787516c85580d7d9b4dd5fda5e3ae9d26f73fca24d11fec8'
broker_current=read('tests/test_backend_publication_broker_terminal_v3.py')
old_tree=ast.parse(broker_old);new_tree=ast.parse(broker_current)
def members(tree):
    return {(c.name,n.name):n for c in tree.body if isinstance(c,ast.ClassDef) for n in c.body if isinstance(n,ast.FunctionDef)}
old_methods=members(old_tree);new_methods=members(new_tree)
changed=[key for key in old_methods if ast.dump(old_methods[key],include_attributes=False)!=ast.dump(new_methods[key],include_attributes=False)]
assert changed==[('BackendPublicationBrokerTerminalV3Tests','_losing_owner_cannot_publish')],changed
assert all(ast.dump(old_methods[key],include_attributes=False)==ast.dump(node,include_attributes=False) for key,node in new_methods.items() if key[1].startswith('test_'))
helper_delta={'old':ref(broker_old_path),'current':ref('tests/test_backend_publication_broker_terminal_v3.py'),
 'changed_class_method':[list(x) for x in changed],
 'final_two_cases_receipt':focused[2]['receipt'],'all_test_method_ASTs_identical':True,
 'scope':'Only the new owner-collision helper changed to put /proc observations inside existing cleanup. Its two callers ran again on final bytes. Other original methods/helpers retain their prior exact ASTs.'}

def source_rows(source):
    if isinstance(source,dict):
        for k,v in source.items():
            if isinstance(v,dict):yield {'path':k,**v}
    else:yield from source
for ident,t in mapping['tests'].items():
    path=t['source']['path'];join=joins.get(path)
    t['original_4cb_source_semantics']=join
    t['scoped_executed_behavior']=[]
    prior=t['original_4cb']
    if prior['outcome']=='success' and join and join['CR_at_EOL_equivalent']:
        t['scoped_executed_behavior'].append({'basis':'original FAILED whole 4cb CI, individual method success','physical_bytes_equal':join['raw_equal'],'test_assertions_and_source_EOL_equivalent':True,'report_ref':'ci4cb','limit':'A matching method/file is scoped behavior evidence, not current whole-CI or transitive dependency acceptance.'})
    for f in focused:
        if ident not in f['successful_ids']:continue
        same=any(x.get('sha256')==t['source']['sha256'] and Path(x.get('path','')).name==Path(path).name for x in source_rows(f['source_before']))
        preserved=(path=='tests/test_backend_publication_broker_terminal_v3.py' and f is focused[1])
        if same or preserved:
            t['scoped_executed_behavior'].append({'basis':f['classification'],'receipt':f['receipt'],'stderr':f['stderr'],
              'current_test_bytes_equal':same,'preserved_AST_with_final_helper_regression':preserved,
              'physical_model_or_CI_acceptance':False})
    t['current_assertion_execution_available']=bool(t['scoped_executed_behavior'])

for key,s in mapping['source_anchors'].items():
    s['original_4cb_source_semantics']=joins.get(s['source']['path'])
counts={}
for r in mapping['requirements']:
    for s in r['scenarios']:
        ts=[mapping['tests'][i] for i in s['test_refs']]
        available=bool(ts) and all(t['current_assertion_execution_available'] for t in ts)
        s['scoped_execution_status']='scoped original assertion evidence linked' if available else 'manual/physical evidence or some current assertion executions pending'
        counts[s['scoped_execution_status']]=counts.get(s['scoped_execution_status'],0)+1
        s['semantic_source_join_limit']='Source equivalence joins distinguish exact raw bytes from CR-at-EOL-only content. Neither rewrites hashes nor reattests hardware. The current scenario still needs its own final applicable gate.'

head=subprocess.run(git+['rev-parse','HEAD'],capture_output=True,check=True,timeout=10).stdout.decode().strip()
assert head==mapping['current_source_commit'],'source commit moved during prepared mapping completion'
mapping['mapping_revision']=2;mapping['supersedes_for_detail_only']=ref(str((HERE/'mapping.v1.json').relative_to(ROOT)))
mapping['scoped_result_counts']=counts
mapping['focused_original_results']=focused
mapping['broker_test_AST_preservation']=helper_delta
mapping['source_semantic_joins']=joins
mapping['generator_sources']=[ref(str((HERE/p).relative_to(ROOT))) for p in ('generate_mapping_v1.py','complete_mapping_v2.py','scenario_reviews_v1.py','behavior_notes_v1.py')]
mapping['evidence']['capacity_author']=ref(BASE+'ci-4cb9-two-failure-diagnosis-v1/capacity-fixture-repair-v1/author-review.v1.json')
mapping['physical_source_changes_vs_head_limit']='Names are the original raw Git status/diff observation. Several inherited paths may differ only at CR-at-EOL. No unrelated source is normalized, staged or claimed commit-identical by this review.'
for p,d in pins.items():
    i=(ROOT/p).lstat();current=[i.st_dev,i.st_ino,i.st_mode,i.st_nlink,i.st_size,i.st_mtime_ns,i.st_ctime_ns]
    assert current==d['epoch'],p
assert time.monotonic_ns()<DEADLINE
def write(name,value):
    raw=(json.dumps(value,sort_keys=True,indent=2,ensure_ascii=True,allow_nan=False)+'\n').encode('ascii')
    assert len(raw)<8*1024*1024
    p=HERE/name
    with p.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    return {'path':str(p.relative_to(ROOT)),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
out={};out['mapping']=write('mapping.v2.json',mapping)
out['inventory']=write('source-semantic-join-inventory.v2.json',{'schema_version':1,'files':list(pins.values()),'aggregate_bytes_read':TOTAL,'all_review_fds_closed':True,'tests_executed':0,'project_imports':0,'hardware_queries':0,'elapsed_s':(time.monotonic_ns()-START)/1e9})
summary={**prior_review,'mapping_revision':2,'outputs':out,'scoped_result_counts':counts,
 'specific_remaining_gap':prior_review['specific_remaining_gap'],
 'source_semantic_join_counts':{'exact_bytes':sum(x['raw_equal'] for x in joins.values()),'CR_at_EOL_only':sum(not x['raw_equal'] and x['CR_at_EOL_equivalent'] for x in joins.values()),'changed':sum(not x['CR_at_EOL_equivalent'] for x in joins.values())},
 'focused_original_receipt_count':len(focused),'broker_helper_delta':helper_delta,
 'source_before_after_review':'All newly read metadata leaves retained exact observed epochs at final recheck, with every read FD closed. Git blobs are original 4cb contents verified against its source-before report.',
 'tool_observation_limits':['The first unpublished metadata generator invocation refused a stale evidence alias before any mapping output. A later metadata invocation returned no preserved terminal detail; process inspection found no live generator and no output. The closed generation and this supplement have their own successful result and do not claim custody of that missing tool terminal. No tests or authority work ran.'],
 'elapsed_s':(time.monotonic_ns()-START)/1e9}
out['review']=write('review.v2.json',summary)
print(json.dumps({'outputs':out,'counts':counts,'source_joins':summary['source_semantic_join_counts'],'elapsed_s':(time.monotonic_ns()-START)/1e9},sort_keys=True))
