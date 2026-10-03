"""Retain one completed original hosted run; GCM credentials/redirect URLs stay in memory."""
import hashlib,json,os,pathlib,stat,subprocess,time,urllib.request,urllib.parse,zipfile
ROOT=pathlib.Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
OUT=ROOT/'artifacts/benchmark_recovery_20260930/ci-9d47-original-host-retention-v1'
RUN=36802923013
CPU=110181019042
HOST=110181019292
EXPECTED='9d47e99b623df44816f7b0a0b73b249a940f7723'
START=time.monotonic();END=START+180
class Redirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):
  result=super().redirect_request(req,fp,code,msg,headers,newurl)
  if urllib.parse.urlsplit(newurl).hostname!='api.github.com':result.remove_header('Authorization')
  return result
def clock():
 if time.monotonic()>=END:raise TimeoutError('original hosted retention180s')
def save(name,value):
 raw=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode();assert len(raw)<=8*1024*1024
 with (OUT/name).open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
 return {'path':str((OUT/name).relative_to(ROOT)),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
rows=[];first=None
try:
 environment=dict(os.environ,GIT_TERMINAL_PROMPT='0',GCM_INTERACTIVE='Never')
 credential=subprocess.run(['/mnt/c/Program Files/Git/cmd/git.exe','credential','fill'],input=b'protocol=https\nhost=github.com\n\n',stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=environment,timeout=20,check=True)
 fields=dict(line.split(b'=',1) for line in credential.stdout.splitlines() if b'=' in line);token=fields[b'password'].decode();del credential,fields
 opener=urllib.request.build_opener(Redirect())
 def request(suffix):
  return urllib.request.Request('https://api.github.com/repos/lordcoudy/VAST/'+suffix,headers={'Authorization':'Bearer '+token,'User-Agent':'VAST-readonly-original-CI-capture','Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'})
 def data(suffix,cap):
  clock();parts=[];count=0
  with opener.open(request(suffix),timeout=min(45,END-time.monotonic())) as response:
   while block:=response.read(65536):clock();count+=len(block);assert count<=cap;parts.append(block)
  return b''.join(parts)
 run=json.loads(data('actions/runs/'+str(RUN),1048576));assert run['id']==RUN and run['head_sha']==EXPECTED and run['status']=='completed' and run['conclusion']=='success'
 jobs=json.loads(data('actions/runs/'+str(RUN)+'/jobs?per_page=100',4*1024*1024));assert {j['id'] for j in jobs['jobs']}=={CPU,HOST} and all(j['run_id']==RUN and j['conclusion']=='success' for j in jobs['jobs'])
 artifacts=json.loads(data('actions/runs/'+str(RUN)+'/artifacts?per_page=100',1048576));assert len(artifacts['artifacts'])==artifacts['total_count'] and 0<len(artifacts['artifacts'])<=8
 metadata=save('original-provider-metadata.v1.json',{'run':run,'jobs':jobs,'artifacts':artifacts})
 for job in (CPU,HOST):
  raw=data('actions/jobs/'+str(job)+'/logs',32*1024*1024)
  with (OUT/('job-'+str(job)+'.original.log')).open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
  rows.append({'kind':'original_job_log','job_id':job,'path':str((OUT/('job-'+str(job)+'.original.log')).relative_to(ROOT)),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
 for artifact in artifacts['artifacts']:
  assert not artifact['expired'] and artifact['workflow_run']['id']==RUN and artifact['workflow_run']['head_sha']==EXPECTED
  aid=artifact['id'];raw=data('actions/artifacts/'+str(aid)+'/zip',8*1024*1024)
  assert len(raw)==artifact['size_in_bytes'] and artifact['digest']=='sha256:'+hashlib.sha256(raw).hexdigest()
  destination=OUT/('artifact-'+str(aid)+'.original.zip')
  with destination.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
  members=[];decoded=0;names=set()
  with zipfile.ZipFile(destination) as archive:
   assert len(archive.infolist())<=4096
   for item in archive.infolist():
    name=pathlib.PurePosixPath(item.filename);assert item.filename not in names and not name.is_absolute() and '..' not in name.parts and '\\' not in item.filename and ':' not in item.filename
    mode=item.external_attr>>16;assert not stat.S_ISLNK(mode) and (not mode or stat.S_IFMT(mode) in (0,stat.S_IFREG,stat.S_IFDIR));names.add(item.filename)
    decoded+=item.file_size;assert decoded<=64*1024*1024
    h=hashlib.sha256();count=0
    with archive.open(item) as stream:
     while block:=stream.read(65536):clock();count+=len(block);h.update(block)
    assert count==item.file_size;members.append({'name':item.filename,'size_bytes':count,'sha256':h.hexdigest(),'crc32':item.CRC})
  rows.append({'kind':'original_artifact','artifact_id':aid,'artifact_name':artifact['name'],'path':str(destination.relative_to(ROOT)),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'provider_digest_matched':True,'all_member_crc_verified':True,'member_count':len(members),'decoded_size_bytes':decoded,'members':members})
 del token
 terminal={'schema_version':1,'status':'originals_retained','run_id':RUN,'source_commit':EXPECTED,'metadata':metadata,'originals':rows,'elapsed_s':time.monotonic()-START,'temporary_signed_URL_or_token_saved':False,'workflow_action':None,'provider_run_success':True,'evidence_acceptance_reviewed':False}
except BaseException as error:
 first={'exception_type':type(error).__name__,'http_status':getattr(error,'code',None)}
 terminal={'schema_version':1,'status':'failed_original_retention','run_id':RUN,'first_failure':first,'originals':rows,'elapsed_s':time.monotonic()-START,'temporary_signed_URL_or_token_saved':False,'workflow_action':None,'evidence_acceptance_reviewed':False}
save('original-retention-terminal.v1.json',terminal)
print(json.dumps({'run_id':RUN,'status':terminal['status'],'retained_count':len(rows),'elapsed_s':terminal['elapsed_s']}),flush=True)
raise SystemExit(0 if first is None and time.monotonic()<END else 1)
