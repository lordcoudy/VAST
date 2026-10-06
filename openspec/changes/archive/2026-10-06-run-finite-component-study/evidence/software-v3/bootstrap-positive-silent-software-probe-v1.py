import ast,json,os,selectors,signal,subprocess,sys,tempfile,time
from pathlib import Path
p=Path(__file__).with_name('bootstrap-private-current-root-v1.py')
tree=ast.parse(p.read_bytes());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run')
with tempfile.TemporaryDirectory(prefix='vast-bootstrap-pipes-software-') as tmp:
    control=Path(tmp);records=[];clock={'deadline_monotonic_ns':time.monotonic_ns()+25_000_000_000}
    def remaining():return (clock['deadline_monotonic_ns']-time.monotonic_ns())/1e9-15
    scope={**globals(),'control':control,'records':records,'clock':clock,'remaining':remaining}
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(p),'exec'),scope)
    out=scope['run']([sys.executable,'-I','-B','-c',"import os;os.write(1,b'o'*131072);os.write(2,b'e'*131072)"],'real-positive')
    assert out.read_bytes()==b'o'*131072 and (control/'real-positive.stderr.original').read_bytes()==b'e'*131072
    assert records[-1]['returncode']==0 and records[-1]['owned_child_reaped']
    clock['deadline_monotonic_ns']=time.monotonic_ns()+15_250_000_000;started=time.monotonic()
    refused=False
    try:scope['run']([sys.executable,'-I','-B','-c',"import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(100)"],'real-silent')
    except AssertionError:refused=True
    elapsed=time.monotonic()-started
    assert refused and records[-1]['owned_child_reaped'] and records[-1]['returncode']==-signal.SIGKILL
    assert elapsed<5.5 and not Path('/proc/'+str(records[-1]['pid'])).exists()
    print(json.dumps({'software_only':True,'positive_two_full_pipes':True,'silent_TERM_ignore_KILL_wait_reaped':True,'elapsed_s':elapsed,'records':records,'model_media_engine':0}),flush=True)
