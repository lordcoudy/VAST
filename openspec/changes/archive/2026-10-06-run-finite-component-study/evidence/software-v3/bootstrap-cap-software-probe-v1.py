import ast,json,os,selectors,signal,subprocess,sys,tempfile,time
from pathlib import Path
p=Path(__file__).with_name('bootstrap-private-current-root-v1.py')
tree=ast.parse(p.read_bytes());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run')
with tempfile.TemporaryDirectory(prefix='vast-bootstrap-cap-software-') as tmp:
    control=Path(tmp);records=[];clock={'deadline_monotonic_ns':time.monotonic_ns()+25_000_000_000}
    def remaining():return (clock['deadline_monotonic_ns']-time.monotonic_ns())/1e9-15
    scope={**globals(),'control':control,'records':records,'clock':clock,'remaining':remaining}
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(p),'exec'),scope)
    refused=False
    try:scope['run']([sys.executable,'-I','-B','-c',"import os;block=b'x'*65536\nfor i in range(258): os.write(2,block)"],'real-stderr-cap')
    except AssertionError:refused=True
    assert refused,'real cap-excess child must be refused'
    size=(control/'real-stderr-cap.stderr.original').stat().st_size
    print(json.dumps({'software_only':True,'real_stderr_bytes_retained':size,'cap':16*1024**2,'refused':refused,'within_write_cap':size<=16*1024**2,'model_media_engine':0}),flush=True)
    assert size<=16*1024**2,'original run wrote beyond cap before refusal'
