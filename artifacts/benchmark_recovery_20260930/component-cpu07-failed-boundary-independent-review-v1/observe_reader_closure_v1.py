"""Two genuine later host-process scans; no container inference."""
from pathlib import Path
import hashlib,json,os,time
OUT=Path(__file__).parent;START=time.monotonic();held=[];report={}
def scan(ids):
    members=[];errors=[]
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():continue
        try:
            v=(p/'stat').read_text().rsplit(')',1)[1].split()
            if int(p.name) in ids or int(v[2]) in ids or int(v[3]) in ids:
                members.append({'pid':int(p.name),'ppid':int(v[1]),'pgid':int(v[2]),'session':int(v[3]),'startticks':int(v[19]),'state':v[0]})
        except FileNotFoundError:pass
        except (OSError,ValueError) as e:errors.append({'pid':int(p.name),'type':type(e).__name__,'errno':getattr(e,'errno',None)})
    return {'at_ns':time.time_ns(),'members':members,'errors':errors,'pids_absent':{str(i):not Path('/proc',str(i)).exists() for i in sorted(ids)}}
launch=json.loads((OUT/'launch.v1.json').read_bytes());raw=(OUT/'review.v1.json').read_bytes()
assert len(raw)==16997 and hashlib.sha256(raw).hexdigest()=='85b668c7510641ab3d7fd2455b1f7cd0f9e7b83ae9ef37531a6949ed46403d3d'
v=json.loads(raw);assert v['reviewer_fds_released'] and v['close_errors']==[] and v['fd_before']==v['fd_after']==6
boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();assert boot==launch['boot_id']
ids={launch['pid'],launch['ppid'],launch['pgid']};ids.update(int(x) for x in v['fresh_two_actual_process_scans'][0]['pids_absent'])
scans=[scan(ids),scan(ids)];assert all(not s['members'] and not s['errors'] and all(s['pids_absent'].values()) for s in scans)
assert time.monotonic()-START<10
report={'schema_version':1,'status':'closed_failed_original_host_processes_and_review_FDs_released','original_review':{'path':str(OUT/'review.v1.json'),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()},'original_reader_launch':launch,'two_actual_later_scans':scans,'same_boot_id':boot,'original95_hold_release':True,'container_quiescence_verified':False,'task_18_8_complete':False,'active_worker_container_absence_not_inferred':True,'scanner_pid':os.getpid(),'scanner_ppid':os.getppid(),'elapsed_s':time.monotonic()-START}
raw=(json.dumps(report,sort_keys=True,indent=2)+'\n').encode();p=OUT/'process-closure.v1.json'
with p.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
assert time.monotonic()-START<10
print(json.dumps({'path':str(p),'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}),flush=True)
