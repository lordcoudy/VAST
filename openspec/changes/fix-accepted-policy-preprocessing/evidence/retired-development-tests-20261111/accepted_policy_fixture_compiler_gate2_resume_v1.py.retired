import base64,hashlib,json,os
from pathlib import Path,PurePosixPath
import re,shutil,stat,subprocess,sys,threading,time,types
PREFIX='tests/fixtures/accepted_policy_fixture_compiler'
CODE=tuple(PREFIX+name for name in ('_gate2_c_v1.py','_component_v1.py','_v1.py',
  '_publisher_v1.py','_seccomp_v1.json'))+('scripts/publication_operational_request_domain_v1.py',)+tuple(
  PREFIX+name for name in ('_recovery_v1.py','_gate2_p0_v1.py','_gate2_d_v1.py','_gate2_d_child_v1.py'))
OPERATOR=PREFIX+'_gate2_resume_v1.py'
EVIDENCE='openspec/changes/fix-accepted-policy-preprocessing/evidence/compiler-component-01/'
PLAN=EVIDENCE+'component-admission-plan.v8.md'
INDEX=EVIDENCE+'gate2-p0-465-retention.v1.json'
OLD_INDEX=EVIDENCE+'gate2-f2-c75a-retention.v1.json'
SOURCE_PATHS=CODE+(OPERATOR,PLAN)
PRODUCER='465ab7986939c67ae3594344ee3b6266cd2abd7a'
OWNER=PurePosixPath('/home/s-a-balashov/work/vast-fixture-compiler-gate2-'+PRODUCER+'-01')
ROOT,AUX=OWNER/'r1',OWNER/'r1.operator-originals'
REPO_WIN=Path('C:/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST')
REPO_LINUX=Path('/mnt/c'+REPO_WIN.as_posix()[2:])
GIT,WSL='C:/Program Files/Git/cmd/git.exe','C:/Windows/System32/wsl.exe'
DIAGNOSTIC='C:/Users/s-a-balashov/AppData/Local/Temp/vast-gate2-465-retention-readonly-01.held-tool-return.original.json'
DIAGNOSTIC_SHA='c10bf42d132f92692ce72a37a6f3d64a944e2a90c6fa3fcc608a1e1cd4aa6780'
MANIFEST_SHA='e62f218cc56caaa5726804d22a348a42fa45d1c06645b955ba5457831a7fc757'
MODULES=(('publication_operational_request_domain_v1',CODE[5]),)+tuple(
  ('tests.fixtures.'+Path(path).stem,path) for path in (CODE[1],CODE[2],CODE[3],CODE[6],CODE[7],CODE[0],CODE[8],CODE[9]))
CAPS={'operator.authority.original.json':8192,'operator.command.original.json':4096,
    'p0.return.original.json':4096,'resume.events.original.json':8192}
PHASES=('PRE','PACKET','FINAL')
NS=10**9
RUN_NS,WORK_NS=150*NS,140*NS
class ResumeRefusal(RuntimeError):
  def __init__(self,cause,facts=None):
    super().__init__(cause)
    self.cause=cause
    self.facts={} if facts is None else facts
def need(condition,cause,facts=None):
  if not condition:
    raise ResumeRefusal(cause,facts)
def canonical(value):
  return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')
def sha(raw):
  return hashlib.sha256(raw).hexdigest()
def windows_v1():
  return os.name=='nt'
def decode(raw,cap):
  need(type(raw) is bytes and len(raw)<=cap,'json_bound')
  def pairs(rows):
    result={}
    for key,value in rows:
      need(key not in result,'json_duplicate')
      result[key]=value
    return result
  value=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _: need(False,'json_nonfinite'))
  need(canonical(value) in (raw,raw.rstrip(b'\n')) and raw.count(b'\n')<=1,'json_canonical')
  return value
def source_descriptor_v1(raw):
  return {'size_bytes':len(raw),'sha256':sha(raw),
    'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode('ascii')+b'\0'+raw).hexdigest()}
def map_deadline_v1(linux,received,cutoff):
  need(all(type(n) is int and n>=0 for n in (linux,received,cutoff))
    and received<cutoff,'clock_mapping')
  return linux+cutoff - received
def outer_collection_v1(call,frames):
  need(type(call) is dict and type(frames) is list and 1<=len(frames)<=6
    and all(type(frame) is dict for frame in frames),'outer_frames')
  raw=canonical({'call':call,'frames':frames})
  need(len(raw)<=12288,'outer_complete_bound')
  return raw
def terminal_v1(error):
  facts=getattr(error,'facts',{})
  facts=facts if type(facts) is dict else {}
  known=[]
  for key in ('pid','returncode','stdout_eof','stderr_eof','unknown_closure','stdin_closed','stdin_extent_unknown','extent_unknown',
      'stdout_bytes','stderr_bytes','stdout_sha256','stderr_sha256','stdout_prefix_base64','stderr_prefix_base64'):
    if key in facts:
      v=facts[key]
      if v is None or type(v) is bool or type(v) is int and -2**63<=v<2**64 or type(v) is str and v.isascii() and len(v)<=128:
        known.append({'path':key,'value':v})
  cause=str(error).encode('ascii','backslashreplace')[:48].decode('ascii')
  causes=[cause]
  for v in (facts.get('causes',[])+facts.get('secondary',[]))[:4]:
    if type(v) is str and v[:48] not in causes:causes.append(v.encode('ascii','backslashreplace')[:48].decode('ascii'))
  return canonical({'completed':False,'physical_acceptance':False,'causes':causes,
    'known':known,'omitted_or_unknown':True,'external_terminal_and_packet_review_required':True})
def read_fixed_v1(path,cap):
  path=Path(path)
  pre=path.lstat()
  need(path.is_absolute() and path.resolve(strict=True)==path and stat.S_ISREG(pre.st_mode)
    and pre.st_nlink==1 and 0<=pre.st_size<=cap,'read_kind_bound')
  fd=os.open(path,os.O_RDONLY|getattr(os,'O_NONBLOCK',0)|getattr(os,'O_NOFOLLOW',0)
        |getattr(os,'O_CLOEXEC',0)|getattr(os,'O_BINARY',0))
  f=None
  try:
    f=os.fdopen(fd,'rb')
    post=os.fstat(f.fileno())
    need(epoch_v1(post,True)==epoch_v1(pre,True),'read_open_drift')
    raw=f.read(cap+1)
    need(len(raw)==pre.st_size and epoch_v1(os.fstat(f.fileno()))==epoch_v1(post)
       and epoch_v1(path.lstat())==epoch_v1(pre),'read_drift')
  finally:
    first=sys.exception()
    try:f.close() if f is not None else os.close(fd)
    except BaseException as e:
      raise ResumeRefusal(str(first or e),{'secondary':['read_close_failed'],'close_completed':False}) from e
  return raw,pre
def epoch_v1(s,cross=False):
  return (s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_gid,s.st_nlink,s.st_size,
    s.st_mtime_ns,None if cross and windows_v1() else s.st_ctime_ns,getattr(s,'st_blocks',None),getattr(s,'st_birthtime_ns',None))
def load_verified_v1(src,descs,repo):
  need(type(src) is dict and set(src)==set(SOURCE_PATHS)
    and type(descs) is dict and set(descs)==set(SOURCE_PATHS),'source_inventory')
  for name in SOURCE_PATHS:
    raw=src[name]
    cap=32768 if name in (OPERATOR,CODE[1]) else 40960 if name==PLAN else 131072
    need(type(raw) is bytes and 0<len(raw)<=cap
      and canonical(source_descriptor_v1(raw))==canonical(descs[name]),'source_binding')
  need(sum(len(raw) for raw in src.values())+32768+4096<=655360,'logical_source_bound')
  for name in ('tests','tests.fixtures'):
    need(name not in sys.modules,'ambient_project_package')
  need(all(name not in sys.modules for name,_ in MODULES),'ambient_project_module')
  for name in ('tests','tests.fixtures'):
    pkg=types.ModuleType(name)
    pkg.__path__=[]
    sys.modules[name]=pkg
    if '.' in name: setattr(sys.modules['tests'],'fixtures',pkg)
  ownid='tests.fixtures.'+Path(OPERATOR).stem
  own=types.ModuleType(ownid)
  own.__file__,own.__package__=str(Path(repo)/OPERATOR),'tests.fixtures'
  sys.modules[ownid]=own
  setattr(sys.modules['tests.fixtures'],Path(OPERATOR).stem,own)
  exec(compile(src[OPERATOR],own.__file__,'exec'),own.__dict__)
  out={}
  for name,rel in MODULES:
    need(name not in sys.modules,'ambient_project_module')
    mod=types.ModuleType(name)
    mod.__file__,mod.__package__=str(Path(repo)/rel),name.rpartition('.')[0]
    sys.modules[name]=mod
    if name.startswith('tests.fixtures.'):
      setattr(sys.modules['tests.fixtures'],name.rpartition('.')[2],mod)
    exec(compile(src[rel],mod.__file__,'exec'),mod.__dict__)
    out[rel]=mod
  return out
def native_table_v1(index,rpc):
  need(index['source_slots']==list(CODE)+( [PLAN,PREFIX+'_gate2_setup_v1.py',
    PREFIX+'_gate2_capture_v1.py',OPERATOR]),'native_source_slots')
  bindings=dict(index['historical_bindings'])['producer465']
  files=[]
  for slot in range(11):
    selected,_,size,digest=index['source_versions'][bindings[slot]]
    need(type(selected) is int and selected==slot,'native_source_role')
    files.append(('code',CODE[slot] if slot<10 else 'physical-plan.v8.md',size,digest))
  extras=tuple(('aux',p) for p in sorted(('b2.corrected-index.v1.json','operator.authority.original.json',
    'operator.command.original.json')+tuple(p+'.'+s+'.original' for p in ('export','f2','p0-gate')
    for s in ('stderr','stdout'))))+(('code','p0/p0-completion.v1.json'),('code','p0/p0-control.v1.json'),
    ('f2','f2.final-accounting.v1.json'),('f2','f2.originals.v1.json'),('f2','f2.supplement.v1.json'))
  need(tuple((row[0],row[1]) for row in index['native_extras'])==extras,'native_extra_names')
  files.extend(tuple(row) for row in index['native_extras'])
  names=['RPC%02d.%s.original'%(n,role) for n in range(1,20) for role in ('reply','request')]
  need(type(rpc) is dict and set(rpc)=={'schema_version','originals'}
    and type(rpc['schema_version']) is int and rpc['schema_version']==1
    and type(rpc['originals']) is list and len(rpc['originals'])==38,'native_rpc_index')
  for name,row in zip(names,rpc['originals']):
    need(type(row) is dict and set(row)=={'relative_path','size_bytes','sha256'}
      and row['relative_path']==name,'native_rpc_name')
    files.append(('f2',name,row['size_bytes'],row['sha256']))
  need(all(type(size) is int and 0<=size<=6291456 and type(digest) is str
    and re.fullmatch('[0-9a-f]{64}',digest) for _,_,size,digest in files),'native_descriptor')
  dirs=(('aux','.'),('code','.'),('code','p0'),('code','scripts'),('code','tests'),
      ('code','tests/fixtures'),('f2','.'))
  return sorted(files),dirs
def _actual_read(path,cap):
  return sys.modules[MODULES[1][0]]._resume_read_v1(path,cap)
def _allocation(info):
  return sys.modules[MODULES[1][0]]._retention_allocation_v1(info)
def verify_retained_v1(repo_root,*,index):
  need(os.name=='posix','native_retention_requires_linux')
  diagpath=Path('/mnt/c'+DIAGNOSTIC[2:])
  raw,_,alloc=_actual_read(diagpath,8645)
  need(len(raw)==8645 and sha(raw)==DIAGNOSTIC_SHA and alloc+4096<=16384,'diagnostic_identity_allocation')
  held=decode(raw,8645)
  need(held['tool_result']['exit_code']==0 and held['manifest_sha256']==MANIFEST_SHA,'diagnostic_binding')
  diag=decode(held['tool_result']['output'].encode('ascii'),12288)
  need(diag['all_expected_matched'] is True and diag['observation_complete'] is True
    and diag['manifest_sha256']==MANIFEST_SHA and len(diag['slots'])==86,'diagnostic_slots')
  rs={'code':Path(OWNER),'f2':Path(str(OWNER)+'.f2'),'aux':Path(str(OWNER)+'.operator-originals')}
  row=next(row for row in index['native_extras'] if row[:2]==['f2','f2.originals.v1.json'])
  rpc_raw,_,_=_actual_read(rs['f2']/row[1],row[2])
  need(len(rpc_raw)==row[2] and sha(rpc_raw)==row[3],'retained_rpc_index')
  fs,dirs=native_table_v1(index,decode(rpc_raw,5194))
  nodes=[(g,p,size,digest) for g,p,size,digest in fs]+[(g,p,None,None) for g,p in dirs]
  want={}
  for group,rel,_,_ in nodes:
    if rel!='.':
      parent=str(Path(rel).parent)
      want.setdefault((group,parent),set()).add(Path(rel).name)
  for group,rel in dirs:
    dirpath=rs[group]/rel
    info=dirpath.lstat()
    need(dirpath.resolve(strict=True)==dirpath and stat.S_ISDIR(info.st_mode),'retained_directory')
    allowed=want.get((group,rel),set())
    seen=set()
    with os.scandir(dirpath) as entries:
      for entry in entries:
        if group=='code' and rel=='.' and entry.name in ('r1','r1.operator-originals'):
          need(entry.is_dir(follow_symlinks=False),'new_namespace_kind')
          continue
        need(entry.name in allowed and entry.name not in seen,'retained_extra')
        seen.add(entry.name)
    need(seen==allowed,'retained_missing')
  used=dict(code=0,f2=0,aux=0)
  ids,grow=set(),0
  for number,(group,rel,size,digest) in enumerate(nodes):
    path=rs[group]/rel
    pre=path.lstat()
    need(path.resolve(strict=True)==path,'retained_alias')
    if size is not None:
      body,obs,blocks=_actual_read(path,size)
      need(len(body)==size and sha(body)==digest,'retained_bytes')
    else:
      obs=pre
      need(stat.S_ISDIR(obs.st_mode),'retained_directory')
      blocks=_allocation(obs)-256
    slot=diag['slots'][number]
    ident=diag['groups'][slot[0]]
    actual=[obs.st_dev,obs.st_mode,obs.st_uid,obs.st_gid,obs.st_nlink]
    parent=group=='code' and rel=='.'
    need(actual[:4]==ident[:4] and obs.st_ino==slot[1] and
      (ident[4]<=actual[4]<=ident[4]+2 if parent else actual[4]==ident[4]),'retained_identity')
    need((obs.st_dev,obs.st_ino) not in ids,'retained_hard_alias')
    ids.add((obs.st_dev,obs.st_ino))
    if parent:
      grow=max(0,blocks-slot[2])
      need(grow<=8192,'retained_parent_growth')
    else:
      need(blocks==slot[2] and obs.st_mtime_ns==slot[3] and obs.st_ctime_ns==slot[4],'retained_epoch')
    need(obs.st_dev==os.stat('/').st_dev,'retained_backing_device')
    used[group] += max(blocks,((obs.st_size+4095)//4096)*4096)+256
    need(epoch_v1(path.lstat())==epoch_v1(pre),'retained_path_drift')
  cap=0
  for path,size,digest in ((Path('/mnt/c/Users/s-a-balashov/AppData/Local/Temp')/
    ('vast-gate2-setup-'+PRODUCER+'.driver.'+channel+'.original'),size,digest)
    for channel,size,digest in (('stdout',0,sha(b'')),('stderr',6392,
      'a901390e93fb9fb2be6fa88f6c81b41286681251ddfc652773b0b9bee489f476'))):
    body,_,blocks=_actual_read(path,size)
    need(len(body)==size and sha(body)==digest,'old_capture_identity')
    cap += max(blocks,((size+4095)//4096)*4096)+4096
  path=Path(repo_root)/EVIDENCE/'gate2-successor-465a.outer-tool.original.json'
  body,_,blocks=_actual_read(path,3609)
  need(len(body)==3609 and sha(body)=='7fc5ef24fb7d226b33a88cab6a57643ef8c86eb774f99cb6e655bb3c69663079','old_outer_identity')
  cap += max(blocks,4096)+4096+8192
  need(used['code']-grow<=586240 and used['f2']<=4372992
    and used['aux']<=39424 and cap<=32768,'retention_allocation')
  return {'node_count':70,'native_code_quote_bytes':used['code']-grow,
    'parent_growth_bytes':grow,'f2_quote_bytes':used['f2'],'aux_quote_bytes':used['aux'],
    'windows_capture_quote_bytes':cap,'diagnostic_quote_bytes':max(alloc,12288)+4096,
    'diagnostic_sha256':DIAGNOSTIC_SHA,'manifest_sha256':MANIFEST_SHA,'physical_acceptance':False}
class _Run:
  def __init__(self,start):
    self.last=time.monotonic_ns()
    need(type(start) is int and 0<start<=self.last<start+WORK_NS,'original_start')
    self.start=start
    self.end,self.work=self.start+RUN_NS,self.start+WORK_NS
    self.events,self.git_count,self.git_hash=[],0,hashlib.sha256()
  def check(self,deadline=None,reserve=0):
    now=time.monotonic_ns()
    need(self.last<=now<min(self.work,deadline or self.work)-reserve,'original_deadline')
    self.last=now
    return now
  def process(self,argv,data,end,cap=8192,ready=None):
    self.check(end)
    p=subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
      bufsize=0,env={'SystemRoot':'C:/Windows','WINDIR':'C:/Windows','PATH':'C:/Windows/System32;C:/Windows',
        'GIT_OPTIONAL_LOCKS':'0','GIT_NO_REPLACE_OBJECTS':'1','GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'NUL'})
    rows=[{'raw':bytearray(),'bytes':0,'hash':hashlib.sha256(),'eof':False,'error':False} for _ in range(2)]
    lock=threading.Lock()
    causes=[]
    w={'bytes':0,'hash':hashlib.sha256(),'extent_unknown':False,'close_attempted':False,'closed':False}
    def drain(pipe,row,limit):
      try:
        while True:
          chunk=pipe.read(min(4096,limit+1-row['bytes']))
          with lock:
            if not chunk: row['eof']=True;break
            row['bytes']+=len(chunk);row['hash'].update(chunk)
            row['raw'].extend(chunk[:max(0,limit-len(row['raw']))])
            if row['bytes']>limit:break
      except BaseException:
        with lock: row['error']=True
    def send(raw):
      off=0
      while off<len(raw):
        self.check(end)
        try:count=p.stdin.write(raw[off:])
        except BaseException:w['extent_unknown']=True;raise
        need(type(count) is int and 0<count<=len(raw)-off,'stdin_short_write')
        w['bytes']+=count;w['hash'].update(raw[off:off+count])
        off+=count
      p.stdin.flush();self.check(end)
    def close_stdin():
      w['close_attempted']=True
      p.stdin.close();w['closed']=True
    acked=False;rc=None
    try:
      for pipe,row,limit in zip((p.stdout,p.stderr),rows,(cap,4096)):
        threading.Thread(target=drain,args=(pipe,row,limit),daemon=True).start()
      send(data)
      if ready is None: close_stdin()
      while True:
        self.check(end)
        with lock:
          snap=[dict(raw=bytes(r['raw']),bytes=r['bytes'],sha256=r['hash'].hexdigest(),
            eof=r['eof'],error=r['error']) for r in rows]
        if ready is not None and not acked and b'\n' in snap[0]['raw']:
          send(canonical(ready(decode(snap[0]['raw'].split(b'\n',1)[0],1024)))+b'\n')
          close_stdin();acked=True
        rc=p.poll()
        if rc is not None and all(r['eof'] for r in snap):break
        if any(r['error'] or r['bytes']>limit for r,limit in zip(snap,(cap,4096))):
          raise ResumeRefusal('pipe_overflow_or_read')
        time.sleep(.001)
    except BaseException as error:
      causes.append(str(error)[:48])
    if not w['close_attempted']:
      try:close_stdin()
      except BaseException:causes.append('stdin_close_failed')
    with lock:
      facts={k+'_'+f:r['hash'].hexdigest() if f=='sha256' else r[f]
        for k,r in zip(('stdout','stderr'),rows) for f in ('eof','bytes','sha256')}
      facts.update({'pid':p.pid,'returncode':rc,
        'argv_sha256':sha(canonical(argv)),'stdin_sha256':w['hash'].hexdigest(),
        'stdin_bytes':w['bytes'],'stdin_closed':w['closed'],'stdin_extent_unknown':w['extent_unknown'],
        'unknown_closure':rc is None or not all(r['eof'] for r in rows) or not w['closed'],'native_raw_originals_retained':0})
      raw,err=bytes(rows[0]['raw']),bytes(rows[1]['raw'])
    for pipe,row in zip((p.stdout,p.stderr),rows):
      if row['eof']:
        try:pipe.close()
        except BaseException:causes.append('pipe_close_failed')
    facts['causes']=list(dict.fromkeys(causes))
    facts['unknown_closure']|=bool(causes)
    try:
      n=decode(err,768)
      need(argv[0]==WSL and facts['stderr_eof'] and n['physical_acceptance'] is False
        and n['external_status_eof_required'] is True and type(n['cause']) is str
        and type(n['causes']) is list and len(n['causes'])<=4 and all(type(v) is str for v in n['causes']),'native_diagnostic')
      facts['native_failure']=dict(n,causes=[n['cause']]+n['causes'])
    except BaseException:pass
    need(not causes and facts['returncode']==0 and facts['stdout_eof'] and facts['stderr_eof']
      and not err and len(raw)==facts['stdout_bytes'] and facts['stdout_bytes']<=cap,
      'process_refused',dict(facts,stdout_prefix_base64=base64.b64encode(raw[:48]).decode('ascii'),
        stderr_prefix_base64=base64.b64encode(err[:48]).decode('ascii'),omitted_or_unknown=True))
    try:self.check(end)
    except ResumeRefusal as error:raise ResumeRefusal(str(error),facts) from error
    return raw,facts
  def git(self,args,cap=131072):
    raw,facts=self.process([GIT,'-C',str(REPO_WIN)]+args,b'',self.work,cap)
    self.git_count+=1;self.git_hash.update(canonical(facts))
    return raw
def authenticate_v1(run,commit):
  need(run.git(['rev-parse','HEAD'],64).strip().decode()==commit,'git_head')
  raw,_=read_fixed_v1(REPO_WIN/INDEX,12288)
  index=decode(raw,12288); idx=source_descriptor_v1(raw)
  slots=index['source_slots']; rows=index['source_versions']
  old={(row[0],row[1]):row[2:] for row in rows}
  cur={}; src={}
  def tree(rev):
    value=run.git(['ls-tree','-r',rev,'--']+slots+[INDEX,OLD_INDEX],8192)
    result={}
    for line in value.decode('ascii').splitlines():
      meta,path=line.split('\t');mode,kind,blob=meta.split()
      need(mode=='100644' and kind=='blob' and path in slots+[INDEX,OLD_INDEX],'git_tree')
      result[path]=blob
    return result
  tree_now=tree(commit)
  need(tree_now[INDEX]==idx['git_blob'],'index_git')
  need(run.git(['cat-file','blob',tree_now[INDEX]])==raw,'index_full_git')
  versions=set()
  history=run.git(['log','--format=%H',index['roles']['c75']+'..'+commit,'--']+slots,4096).decode().splitlines()
  need(1<=len(history)<=32 and all(re.fullmatch('[0-9a-f]{40}',v) for v in history),'git_history_bound')
  for rev in [index['roles']['c75']]+history:
    for rel,blob in tree(rev).items():
      if rel in slots:versions.add((slots.index(rel),blob))
  for rel in SOURCE_PATHS:
    raw,_=read_fixed_v1(REPO_WIN/rel,131072)
    desc=source_descriptor_v1(raw)
    need(tree_now[rel]==desc['git_blob'],'working_git_binding')
    src[rel],cur[rel]=raw,desc
  allowed=set(old)|{(slots.index(p),d['git_blob']) for p,d in cur.items()}
  need(versions==allowed,'unindexed_git_version')
  for slot,blob in sorted(versions):
    body=run.git(['cat-file','blob',blob])
    desc=source_descriptor_v1(body)
    want=old.get((slot,blob))
    need(desc['git_blob']==blob and (want is None or [len(body),sha(body)]==want),'git_blob_binding')
    if slots[slot] in cur and cur[slots[slot]]['git_blob']==blob:
      need(canonical(desc)==canonical(cur[slots[slot]]),'git_current_full_binding')
  c75=[dict(path=slots[slot],git_blob=rows[n][1],size_bytes=rows[n][2],sha256=rows[n][3])
    for slot,n in enumerate(index['historical_bindings'][0][1])]
  oldraw,_=read_fixed_v1(REPO_WIN/OLD_INDEX,12288)
  olddesc=source_descriptor_v1(oldraw)
  need(tree_now[OLD_INDEX]==olddesc['git_blob'] and
    run.git(['cat-file','blob',olddesc['git_blob']])==oldraw,'c75_index_full_git')
  obs={'component':cur[CODE[1]],'index':olddesc,'old_git_sha256':sha(canonical(c75))}
  return src,cur,index,idx,obs
def write_fixed_v1(path,raw,cap,gate,comp):
  need(type(raw) is bytes and len(raw)<=cap,'write_bound')
  gate();fd=os.open(path,os.O_RDWR|os.O_CREAT|os.O_EXCL|getattr(os,'O_BINARY',0),0o600)
  f={'open_completed':True,'written_bytes':0,'extent_unknown':False,'fsync_completed':False,'close_completed':False}
  first=None
  try:
    while f['written_bytes']<len(raw):
      gate()
      try:n=os.write(fd,raw[f['written_bytes']:])
      except BaseException:f['extent_unknown']=True;raise
      need(type(n) is int and 0<n<=len(raw)-f['written_bytes'],'write_short')
      f['written_bytes']+=n
    gate();os.fsync(fd);f['fsync_completed']=True;gate()
    os.lseek(fd,0,os.SEEK_SET);gate()
    need(os.read(fd,len(raw)+1)==raw,'write_readback');gate()
    info=os.fstat(fd);gate()
    alloc=comp._resume_fd_allocation_v1(fd,info)
    f['allocated_bytes']=alloc;gate()
    need(type(alloc) is int and 0<=alloc<=((cap+4095)//4096)*4096 and info.st_nlink==1,'write_allocation')
    need(epoch_v1(os.fstat(fd))==epoch_v1(info),'write_fd_drift');gate()
    pi=Path(path).lstat()
    need(epoch_v1(pi,True)==epoch_v1(info,True),'write_path_drift')
    gate()
  except BaseException as error:first=error
  try:os.close(fd);f['close_completed']=True
  except BaseException:
    f['secondary']=['close_failed'];first=first or ResumeRefusal('close_failed')
  if first is not None:raise ResumeRefusal(str(first),f) from first
  try:gate()
  except BaseException as error:raise ResumeRefusal(str(error),f) from error
  f.update(completed=True,sha256=sha(raw))
  return {'descriptor':{'path':str(path),'size_bytes':len(raw),'sha256':sha(raw)},'write_facts':f}
NATIVE_BOOTSTRAP=r'''
import os,sys,json,stat,hashlib,types
ok=True;c=[]
try:
 k='tests/fixtures/accepted_policy_fixture_compiler_gate2_resume_v1.py'
 x=json.loads(sys.stdin.buffer.readline(16385));d=x['current'][k]
 p='/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/'+k
 s=os.lstat(p);assert stat.S_ISREG(s.st_mode) and s.st_nlink==1 and 0<s.st_size<=32768
 f=os.open(p,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW|os.O_CLOEXEC)
 ok=False
 try:
  e=lambda s:(s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_blocks)
  t=os.fstat(f);assert e(s)==e(t) and type(d['size_bytes'])is int
  b=os.read(f,32769);assert len(b)==d['size_bytes']==s.st_size and hashlib.sha256(b).hexdigest()==d['sha256'] and e(os.fstat(f))==e(t) and e(os.lstat(p))==e(s)
 finally:
  first=sys.exception()
  try:os.close(f);ok=True
  except BaseException:
   c=['close_failed']
   if first is None:raise
 m=types.ModuleType('gate2_verified_bootstrap');m.__file__=p;sys.modules[m.__name__]=m
 exec(compile(b,p,'exec'),m.__dict__);m.native_entry_v1(sys.argv[1],x)
except SystemExit:raise
except BaseException as e:
 a=getattr(e,'facts',{})
 os.write(2,json.dumps(dict(cause=repr(e)[:32],causes=c+a.get('secondary',[]),physical_acceptance=False,external_status_eof_required=True,unknown_closure=not ok or a.get('close_completed') is False),sort_keys=True,separators=(',',':')).encode()+b'\n');sys.exit(1)
'''
def native_argv_v1(phase):
  need(phase in PHASES,'native_phase')
  return [WSL,'-d','Ubuntu','-u','s-a-balashov','--cd','/','--exec','/usr/bin/python3','-I','-S','-B','-c',NATIVE_BOOTSTRAP,phase]
def native_program_hashes_v1():
  return {phase:sha(canonical(native_argv_v1(phase))) for phase in PHASES}
def native_entry_v1(phase,x):
  action=phase in PHASES
  need(os.name=='posix' and (action or re.fullmatch('C[1-6]|D',phase)),'native_entry')
  if not action:
    a=sys.argv[2:];need(len(a)==4 and re.fullmatch('[0-9]+',a[1]),'native_arguments')
    raw,_=read_fixed_v1(Path(ROOT)/'gate2.packet.original.json',32768)
    need(len(raw)==int(a[1]) and sha(raw)==a[2],'packet_binding')
    p=decode(raw,32768);ctx=p['resume_context']
    need(p['code_commit']==a[0] and canonical(ctx['operator'])==canonical(x['current'][OPERATOR]),'packet_commit')
    x={'current':dict(p['code'],**{OPERATOR:ctx['operator'],PLAN:ctx['consumer_plan']})}
  src={name:read_fixed_v1(REPO_LINUX/name,131072)[0] for name in SOURCE_PATHS}
  mods=load_verified_v1(src,x['current'],REPO_LINUX)
  if action:mods[CODE[0]].resume_native_entry_v1(phase,x)
  else:raise SystemExit(mods[CODE[0]].native_main_v1([phase]+a))
def phase_v1(run,key,data):
  start=run.check();end=min(run.work,start+(5 if key=='FINAL' else 15)*NS)
  link={}
  def ready(value):
    w1=run.check(end)
    need(set(value)=={'linux_ready_ns','boot_id'},'ready_shape')
    link.update(l0=value['linux_ready_ns'],w1=w1,boot_id=value['boot_id'],windows_phase_start_ns=start)
    link['global_deadline_ns']=map_deadline_v1(link['l0'],w1,run.work)
    link['phase_deadline_ns']=map_deadline_v1(link['l0'],w1,end)
    return {'global_deadline_ns':link['global_deadline_ns'],
      'phase_deadline_ns':link['phase_deadline_ns'],'boot_id':link['boot_id']}
  if key!='PRE':
    data=dict(data,global_deadline_ns=run.anchor['global_deadline_ns'],
      phase_deadline_ns=map_deadline_v1(run.anchor['l0'],run.anchor['w1'],end))
  raw,obs=run.process(native_argv_v1(key),canonical(data)+b'\n',end,8192,ready if key=='PRE' else None)
  run.events.append(dict(obs,phase=key))
  try:
    lines=raw.splitlines()
    need(len(lines)==(2 if key=='PRE' else 1),'native_extra_output')
    r=decode(lines[-1],7168)
    pid=r['native_pid'];need(type(pid) is int and pid>0,'native_pid')
  except BaseException as error:
    raise ResumeRefusal('native_result_refused',{'process':obs,'causes':[str(error)[:64]]}) from error
  if key=='PRE':run.anchor=link
  run.events[-1]['result_sha256']=sha(lines[-1])
  run.events[-1]['native_pid']=pid
  if key=='PRE':run.events[-1]['clock_anchor']=link
  return r
def dispatch_p0_v1(p0,output,binding,commit,check):
  result=p0.collect_native_p0_v1(str(output),binding,reviewed_code_commit=commit)
  try:
    check()
    need(result.get('accepted') is True and result.get('controlled') is False and result.get('physical_acceptance') is False and result.get('causes')==[],'p0_native_refused')
    done=result['completion_record'];proof=done['write_proof']
    need(all(proof.get(k) is True for k in ('open_completed','fsync_completed','close_completed','completed'))
      and proof.get('late') is False and proof.get('extent_unknown') is False
      and proof['written_bytes']==done['encoded_bytes'] and proof['prefix_sha256']==done['sha256'],
      'p0_completion_write_refused')
  except BaseException as error:
    raise ResumeRefusal(str(error),{'returned_p0':result,'post_return_failure':getattr(error,'facts',None)}) from error
  return done
def main(reviewed_commit,approval_reference,*,_original_start_ns=None):
  commit=reviewed_commit;ref=approval_reference
  run=None;fmt=None
  try:
    run=_Run(_original_start_ns)
    need(windows_v1() and re.fullmatch('[0-9a-f]{40}',commit) and
      re.fullmatch(r'https://github\.com/lordcoudy/VAST/pull/9#issuecomment-[0-9]+',ref),'fixed_authority')
    src,cur,index,idx,obs=authenticate_v1(run,commit)
    run.check()
    mods=load_verified_v1(src,cur,REPO_WIN);comp,p0=mods[CODE[1]],mods[CODE[7]]
    run.check()
    fmt=mods[CODE[0]].resume_terminal_v1
    comp.resume_code_forms_quote_v1(REPO_WIN,code={p:cur[p] for p in CODE},
      plan=cur[PLAN],operator=cur[OPERATOR],index_descriptor=idx)
    base={'current':cur,'index':idx,'git_observation':obs}
    run.check(reserve=70*NS)
    pre=phase_v1(run,'PRE',base)
    ctx={'schema_version':1,'producer_commit':PRODUCER,'producer_plan':dict(zip(
      ('git_blob','size_bytes','sha256'),index['source_versions'][dict(index['historical_bindings'])['producer465'][10]][1:])),
      'owner_project_root':str(OWNER),'project_root':str(ROOT),'retention_index':idx,
      'operator':cur[OPERATOR],'retention':pre['retention'],'prior_retention':{
        'git_observation':obs,'native':pre['retention']['prior']},'baseline':pre['baseline'],
      'boot_id':pre['boot_id'],'consumer_commit':commit,'consumer_plan':cur[PLAN],'pre_info':pre['pre_info']}
    authority={'schema_version':1,'code_commit':commit,'approval_reference':ref,
      'operator_sha256':cur[OPERATOR]['sha256'],'helper_code':{OPERATOR:dict(cur[OPERATOR],path=str(REPO_WIN/OPERATOR))},
      'context_sha256':sha(canonical(ctx)),'context':ctx,'external_approval_required':True}
    unc=lambda path:Path('//wsl.localhost/Ubuntu'+str(path))
    def gate():
      run.check()
      need(shutil.disk_usage('C:/').free>=43620761600+2650112 and
        shutil.disk_usage(unc(AUX)).free>=1073741824+2650112,'write_floors')
      run.check()
    def save(name,value):
      v=write_fixed_v1(unc(AUX)/name,canonical(value),CAPS[name],gate,comp)
      v['descriptor']['path']=str(AUX/name);return v
    auth=save('operator.authority.original.json',authority)
    save('operator.command.original.json',{'schema_version':1,'code_commit':commit,
      'approval_reference':ref,'operator_sha256':cur[OPERATOR]['sha256'],
      'phase_program_sha256':native_program_hashes_v1()})
    run.check(reserve=55*NS)
    done=dispatch_p0_v1(p0,unc(ROOT)/'p0',{'known_engine_id':pre['pre_info']['identity']['engine_id'],
      'boot':{'boot_id':pre['boot_id']},'provenance':{'source':'external','observer':'ordinary_api',
        'engine_id':pre['pre_info']['identity']['engine_id'],'boot_id':pre['boot_id']}},commit,run.check)
    save('p0.return.original.json',{'code_commit':commit,'accepted':True,'causes':[],
      'controlled':False,'physical_acceptance':False,'completion_record':done,
      'reviewed_operator_sha256':cur[OPERATOR]['sha256'],'kernel_preemption_claimed':False,
      'external_invocation_status_and_eof_required':True})
    base.update(context=ctx,authority=auth['descriptor'],review={'commit':commit,
      'approval_reference':ref,'evidence_sha256':auth['descriptor']['sha256']},
      p0={'path':str(ROOT/'p0/p0-completion.v1.json'),'size_bytes':done['encoded_bytes'],'sha256':done['sha256']})
    packet=phase_v1(run,'PACKET',base)
    events=save('resume.events.original.json',{'schema_version':1,'code_commit':commit,
      'processes':run.events,'pre_rpc':pre['rpc_facts'],'git_commands':run.git_count,'git_facts_sha256':run.git_hash.hexdigest(),
      'native_raw_originals_retained':0})
    final=phase_v1(run,'FINAL',dict(base,packet=packet['packet'],events=events['descriptor']))
    f=run.events[-1]
    raw=fmt(result={'code_commit':commit,'packet':packet['packet'],
      'authority':auth['descriptor'],'events':events['descriptor'],'final_meter':final,
      'final_return':[f[k] for k in ('pid','returncode','stdout_eof','stderr_eof','stdout_bytes','stdout_sha256','stderr_bytes','stderr_sha256')],
      'windows_start_ns':run.start,'absolute_deadline_ns':run.end,'c_or_d_invoked':False})
    status=0
  except BaseException as error:
    if run is None:return 1
    try:raw=fmt(error=error) if fmt else terminal_v1(error=error)
    except BaseException:raw=terminal_v1(error=error)
    status=1
  try:
    need(len(raw)<2048 and time.monotonic_ns()<run.work,'terminal_late')
    count=os.write(1,raw+b'\n')
    need(count==len(raw)+1 and time.monotonic_ns()<run.work,'terminal_short_or_late')
  except BaseException:return 1
  return status
if __name__=='__main__':
  raise SystemExit(main(*(sys.argv[1:] if len(sys.argv)==3 else ('',''))))
