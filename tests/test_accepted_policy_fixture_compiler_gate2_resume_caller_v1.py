"""Controlled inline outer-writer proof; this module is not a runtime helper."""
import base64
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
import zlib
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
FIXED_REPO = 'C:/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/'
PREFIX = 'tests/fixtures/accepted_policy_fixture_compiler'
COMPONENT = PREFIX + '_component_v1.py'
OPERATOR = PREFIX + '_gate2_resume_v1.py'
TARGET = ('openspec/changes/fix-accepted-policy-preprocessing/evidence/compiler-component-01/'
          'gate2-p0-exception.outer-tool.original.json')

# The initial persistent Node caller owns this exact static source/carrier.
# Selected bytes are sent later through stdin, never embedded in its launch code.
WRITER_READY = '''import os,sys,time
_ready=time.monotonic_ns()
try:
 _line=b'{"ready":true,"schema_version":1}\\n'
 if os.write(1,_line)!=len(_line):raise RuntimeError('ready_write')
except BaseException:raise SystemExit(1)
'''
WRITER_BODY = r'''import base64,hashlib,json,re,shutil,stat,types
from pathlib import Path
R='C:/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/'
P='tests/fixtures/accepted_policy_fixture_compiler'
S={P+'_component_v1.py':(32730,'da997d0a2a79e72778bcfd374871a1fdf9fc5173d41419ed68713dddc5650436'),P+'_gate2_resume_v1.py':(32765,'4f241178efb2352ba64a622f9f3fd98a4bf92bec2715d741a7622d1c994234ab')}
T='openspec/changes/fix-accepted-policy-preprocessing/evidence/compiler-component-01/gate2-p0-exception.outer-tool.original.json'
def canon(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')
def sha(b):return hashlib.sha256(b).hexdigest()
def need(ok,cause,facts=None):
 if not ok:
  e=RuntimeError(cause);e.facts={} if facts is None else facts;raise e
def pairs(rows):
 d={}
 for k,v in rows:need(k not in d,'ack_duplicate');d[k]=v
 return d
def epoch(s,cross=False):return (s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,None if cross and os.name=='nt' else s.st_ctime_ns,getattr(s,'st_birthtime_ns',None))
def read(p,cap):
 p=Path(p);a=p.lstat()
 need(p.is_absolute() and p.resolve(strict=True)==p and stat.S_ISREG(a.st_mode) and a.st_nlink==1 and 0<a.st_size<=cap,'source_kind')
 gate();fd=os.open(p,os.O_RDONLY|getattr(os,'O_NONBLOCK',0)|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0));first=None;b=b'';facts={'close_completed':False,'unknown_closure':True}
 try:
  gate();s=os.fstat(fd);need(epoch(s,True)==epoch(a,True),'source_open_drift')
  while len(b)<a.st_size:
   gate();part=os.read(fd,a.st_size-len(b));need(bool(part),'source_short');b+=part
  gate();need(os.read(fd,1)==b'' and epoch(os.fstat(fd))==epoch(s) and epoch(p.lstat())==epoch(a),'source_drift')
 except BaseException as e:first=e
 try:os.close(fd);facts.update(close_completed=True,unknown_closure=False)
 except BaseException as e:
  facts['secondary']=['source_close_'+type(e).__name__]
  first=first or e
 if first is not None:
  facts.update(read_bytes=len(b),read_sha256=sha(b));e=RuntimeError(str(first));e.facts=facts;raise e from first
 gate();return b
def module(raw,name,path):
 gate();m=types.ModuleType(name);m.__file__=path;exec(compile(raw,path,'exec'),m.__dict__);gate();return m
gate=None;denied=False
def run():
 global gate,denied
 raw=sys.stdin.buffer.readline(16385)
 need(len(raw)<=16384 and raw.endswith(b'\n'),'ack_bound')
 x=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:need(False,'ack_nonfinite'))
 need(type(x) is dict and set(x)=={'remaining_ms','size_bytes','sha256','selected_base64','sources'} and canon(x)+b'\n'==raw,'ack_shape')
 n=x['remaining_ms'];need(type(n) is int and 0<n<=150000,'ack_remaining')
 end=_ready+n*1000000;last=[_ready]
 def gate():
  global denied
  try:
   now=time.monotonic_ns();need(last[0]<=now<end,'writer_deadline');last[0]=now
   free=shutil.disk_usage('C:/').free
   need(type(free) is int and free>=43620761600+24576,'writer_floor')
   now=time.monotonic_ns();need(last[0]<=now<end,'writer_deadline');last[0]=now
  except BaseException:denied=True;raise
 gate();need(sys.stdin.buffer.read(1)==b'','ack_trailing');gate()
 need(type(x['size_bytes']) is int and 0<x['size_bytes']<=8192 and type(x['sha256']) is str and re.fullmatch('[0-9a-f]{64}',x['sha256']) and type(x['selected_base64']) is str,'payload_shape')
 selected=base64.b64decode(x['selected_base64'],validate=True)
 need(len(selected)==x['size_bytes'] and sha(selected)==x['sha256'] and base64.b64encode(selected).decode('ascii')==x['selected_base64'],'payload_binding')
 need(type(x['sources']) is dict and set(x['sources'])==set(S),'source_set')
 mods=[]
 for i,(rel,(size,digest)) in enumerate(S.items()):
  b=read(R+rel,32768);d={'size_bytes':len(b),'sha256':sha(b),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
  need((len(b),sha(b))==(size,digest) and canon(d)==canon(x['sources'][rel]),'source_binding')
  mods.append(module(b,'_fixed_writer_'+str(i),R+rel))
 comp,op=mods
 path=Path(R+T);gate();need(path.parent.resolve(strict=True)==path.parent,'target_parent')
 result=op.write_fixed_v1(path,selected,8192,gate,comp);gate()
 return {'completed':True,'external_terminal_required':True,'descriptor':result['descriptor'],'write_facts':result['write_facts'],'deadline_ns':end}
try:
 value=run();code=0
except BaseException as e:
 if gate is None or denied:raise SystemExit(1)
 facts=getattr(e,'facts',{});facts=facts if type(facts) is dict else {}
 cause=str(e).encode('ascii','backslashreplace')[:80].decode('ascii')
 value={'completed':False,'external_terminal_required':True,'cause':cause,'known':facts,'omitted_or_unknown':True};code=1
 try:
  encoded=canon(value)
  if len(encoded)>1800:raise ValueError()
 except BaseException:
  value={'completed':False,'external_terminal_required':True,'cause':cause,'omitted_or_unknown':True,'known_serialization_unknown':True}
out=canon(value)+b'\n'
try:
 gate()
 need(len(out)<=2048,'terminal_bound')
 if os.write(1,out)!=len(out):raise RuntimeError('terminal_write')
 gate()
except BaseException:raise SystemExit(1)
raise SystemExit(code)
'''
WRITER_SOURCE = WRITER_READY + WRITER_BODY
WRITER_COMPRESSED = base64.b85encode(zlib.compress(WRITER_BODY.encode('ascii'), 9)).decode('ascii')
WRITER_CARRIER = WRITER_READY + "import base64,zlib\ntry:exec(zlib.decompress(base64.b85decode(" + repr(WRITER_COMPRESSED) + ")) )\nexcept SystemExit:raise\nexcept BaseException:raise SystemExit(1)\n"
QUALIFIED_REUSE_SOURCE = WRITER_SOURCE

# The current candidate uses no project imports or source reads in the final
# interval. Its exact stdlib-only source is bound once in the initial caller.
WRITER_BODY = r'''import base64,ctypes,hashlib,json,re,shutil,stat,msvcrt
from pathlib import Path
from ctypes import wintypes
T='C:/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/openspec/changes/fix-accepted-policy-preprocessing/evidence/compiler-component-01/gate2-p0-exception.outer-tool.original.json'
gate=None;denied=False
def canon(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')
def sha(b):return hashlib.sha256(b).hexdigest()
def need(ok,cause):
 if not ok:raise RuntimeError(cause)
def pairs(rows):
 d={}
 for k,v in rows:need(k not in d,'ack_duplicate');d[k]=v
 return d
def epoch(s,cross=False):return (s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_gid,s.st_nlink,s.st_size,s.st_mtime_ns,None if cross else s.st_ctime_ns,s.st_birthtime_ns)
class Standard(ctypes.Structure):
 _fields_=[('allocation',ctypes.c_longlong),('size',ctypes.c_longlong),('links',wintypes.DWORD),('pending',ctypes.c_ubyte),('directory',ctypes.c_ubyte)]
def allocated(fd,s):
 gate();call=ctypes.WinDLL('kernel32',use_last_error=True).GetFileInformationByHandleEx
 call.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD];call.restype=wintypes.BOOL
 value=Standard();ok=call(msvcrt.get_osfhandle(fd),1,ctypes.byref(value),ctypes.sizeof(value));gate()
 need(ok and value.size==s.st_size and value.links==1 and not value.pending and not value.directory and 0<=value.allocation<=8192,'writer_allocation')
 return value.allocation
def write_fixed_v1(p,raw):
 gate();need(p.parent.resolve(strict=True)==p.parent,'target_parent');gate()
 fd=os.open(p,os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_BINARY,0o600)
 facts={'open_completed':True,'written_bytes':0,'extent_unknown':False,'fsync_completed':False,'close_completed':False,'unknown_closure':True};first=None
 try:
  while facts['written_bytes']<len(raw):
   gate()
   try:n=os.write(fd,raw[facts['written_bytes']:])
   except BaseException:facts['extent_unknown']=True;raise
   need(type(n) is int and 0<n<=len(raw)-facts['written_bytes'],'writer_short');facts['written_bytes']+=n
  gate();os.fsync(fd);facts['fsync_completed']=True;gate()
  s=os.fstat(fd);need(stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_size==len(raw),'writer_fd')
  a=allocated(fd,s);facts['allocated_bytes']=a
  gate();before=p.lstat();need(epoch(before,True)==epoch(s,True),'writer_path')
  gate();os.lseek(fd,0,os.SEEK_SET);back=b''
  while len(back)<=len(raw):
   gate();part=os.read(fd,len(raw)+1-len(back))
   if not part:break
   back+=part
  gate();need(back==raw,'writer_readback');facts['readback_completed']=True
  after=os.fstat(fd);gate();need(epoch(after)==epoch(s) and allocated(fd,after)==a,'writer_fd_drift')
  gate();need(epoch(p.lstat())==epoch(before),'writer_path_drift');gate()
 except BaseException as e:first=e
 try:os.close(fd);facts.update(close_completed=True,unknown_closure=False)
 except BaseException as e:
  facts['secondary']=['close_'+type(e).__name__];first=first or e
 if first is not None:
  e=RuntimeError(str(first));e.facts=facts;raise e from first
 gate();return facts
def run():
 global gate,denied
 need(os.name=='nt','writer_platform')
 raw=sys.stdin.buffer.readline(16385);need(len(raw)<=16384 and raw.endswith(b'\n'),'ack_bound')
 x=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:need(False,'ack_nonfinite'))
 need(type(x) is dict and set(x)=={'remaining_ms','size_bytes','sha256','selected_base64'} and canon(x)+b'\n'==raw,'ack_shape')
 n=x['remaining_ms'];need(type(n) is int and 0<n<=150000,'ack_remaining');end=_ready+n*1000000;last=[_ready]
 def gate():
  global denied
  try:
   t=time.monotonic_ns();need(last[0]<=t<end,'writer_deadline');last[0]=t
   f=shutil.disk_usage('C:/').free;need(type(f) is int and f>=43620761600+24576,'writer_floor')
   t=time.monotonic_ns();need(last[0]<=t<end,'writer_deadline');last[0]=t
  except BaseException:denied=True;raise
 gate();need(sys.stdin.buffer.read(1)==b'','ack_trailing');gate()
 need(type(x['size_bytes']) is int and 0<x['size_bytes']<=8192 and type(x['sha256']) is str and re.fullmatch('[0-9a-f]{64}',x['sha256']) and type(x['selected_base64']) is str,'payload_shape')
 b=base64.b64decode(x['selected_base64'],validate=True)
 need(len(b)==x['size_bytes'] and sha(b)==x['sha256'] and base64.b64encode(b).decode('ascii')==x['selected_base64'],'payload_binding')
 f=write_fixed_v1(Path(T),b);gate()
 q=(len(b)+4095)//4096*4096
 return {'completed':True,'external_terminal_required':True,'size_bytes':len(b),'sha256':sha(b),'write_facts':f,'deadline_ns':end,'all_forms_quote_bytes':max(f['allocated_bytes'],q)+q+8192}
try:value=run();code=0
except BaseException as e:
 if gate is None or denied:raise SystemExit(1)
 value={'completed':False,'external_terminal_required':True,'cause':str(e).encode('ascii','backslashreplace')[:80].decode('ascii'),'known':getattr(e,'facts',{}),'omitted_or_unknown':True};code=1
try:
 out=canon(value)+b'\n';gate();need(len(out)<=2048,'terminal_bound')
 if os.write(1,out)!=len(out):raise RuntimeError('terminal_write')
 gate()
except BaseException:raise SystemExit(1)
raise SystemExit(code)
'''
WRITER_SOURCE = (WRITER_READY + 'try:\n' + ''.join(' ' + line + '\n' for line in WRITER_BODY.splitlines())
                 + 'except SystemExit:raise\nexcept BaseException:raise SystemExit(1)\n')
WRITER_COMPRESSED = base64.b85encode(zlib.compress(WRITER_BODY.encode('ascii'), 9)).decode('ascii')
WRITER_CARRIER = WRITER_READY + "import base64,zlib\ntry:exec(zlib.decompress(base64.b85decode(" + repr(WRITER_COMPRESSED) + ")) )\nexcept SystemExit:raise\nexcept BaseException:raise SystemExit(1)\n"
STANDALONE_WRITER_SOURCE, STANDALONE_WRITER_BODY = WRITER_SOURCE, WRITER_BODY
STANDALONE_WRITER_CARRIER, STANDALONE_WRITER_COMPRESSED = WRITER_CARRIER, WRITER_COMPRESSED

# Current thin writer: fixed reviewed descriptors are argv authority; source
# bytes travel through the already-owned pipe, never a path reread/new file.
PYTHON_CLOCK_HEAD = 'import time\n_ready=time.monotonic_ns()\n'
WRITER_READY = PYTHON_CLOCK_HEAD + '''import os,sys
try:
 _line=b'{"ready":true,"schema_version":1}\\n'
 if os.write(1,_line)!=len(_line):raise RuntimeError('ready_write')
except BaseException:raise SystemExit(1)
'''
WRITER_HEAD = 'SOURCE_ARG=1\nWORK_RESERVE_NS=0\nMIN_SELECTED_BYTES=1\nMAX_SELECTED_BYTES=12288\nACK_CAP=24576\n'
SETUP_COMMON_HEAD = 'SOURCE_ARG=3\nWORK_RESERVE_NS=10000000000\nMIN_SELECTED_BYTES=0\nMAX_SELECTED_BYTES=0\nACK_CAP=16384\n'
WRITER_COMMON_SOURCE = r'''import base64,hashlib,json,re,shutil,types
from pathlib import Path
R='C:/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/'
P='tests/fixtures/accepted_policy_fixture_compiler'
gate=None;denied=False;facts={'stdin_eof':False,'stdin_extent_unknown':False,'source_bytes':[],'source_sha256':[]}
def canon(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')
def sha(b):return hashlib.sha256(b).hexdigest()
def need(ok,cause):
 if not ok:raise RuntimeError(cause)
def pairs(rows):
 d={}
 for k,v in rows:need(k not in d,'input_duplicate');d[k]=v
 return d
def prepare():
 global gate,denied,facts
 need(os.name=='nt','writer_platform')
 a=sys.argv[SOURCE_ARG];need(type(a) is str and a.isascii() and len(a)<=1024,'source_args_bound')
 d=json.loads(a,object_pairs_hook=pairs)
 need(type(d) is list and len(d)==2 and canon(d).decode('ascii')==a,'source_args')
 for v in d:
  need(type(v) is dict and set(v)=={'size_bytes','sha256','git_blob'} and type(v['size_bytes']) is int and 0<v['size_bytes']<=32768 and type(v['sha256']) is str and re.fullmatch('[0-9a-f]{64}',v['sha256']) and type(v['git_blob']) is str and re.fullmatch('[0-9a-f]{40}',v['git_blob']),'source_descriptor')
 raw=sys.stdin.buffer.readline(ACK_CAP+1);need(len(raw)<=ACK_CAP and raw.endswith(b'\n'),'ack_bound')
 x=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:need(False,'ack_nonfinite'))
 need(type(x) is dict and set(x)=={'remaining_ms','size_bytes','sha256','selected_base64'} and canon(x)+b'\n'==raw,'ack_shape')
 n=x['remaining_ms'];need(type(n) is int and 0<n<=150000,'ack_remaining');end=_ready+n*1000000;last=[_ready]
 def gate():
  global denied
  try:
   t=time.monotonic_ns();need(last[0]<=t<end-WORK_RESERVE_NS,'writer_deadline');last[0]=t
   f=shutil.disk_usage('C:/').free;need(type(f) is int and f>=43620761600+32768,'writer_floor')
   t=time.monotonic_ns();need(last[0]<=t<end-WORK_RESERVE_NS,'writer_deadline');last[0]=t
  except BaseException:denied=True;raise
 gate();need(type(x['size_bytes']) is int and MIN_SELECTED_BYTES<=x['size_bytes']<=MAX_SELECTED_BYTES and type(x['sha256']) is str and re.fullmatch('[0-9a-f]{64}',x['sha256']) and type(x['selected_base64']) is str,'payload_shape')
 b=base64.b64decode(x['selected_base64'],validate=True)
 need(len(b)==x['size_bytes'] and sha(b)==x['sha256'] and base64.b64encode(b).decode('ascii')==x['selected_base64'],'payload_binding')
 buffers=[]
 for desc in d:
  source=b'';facts['source_bytes'].append(0);facts['source_sha256'].append(sha(source))
  while len(source)<desc['size_bytes']:
   gate()
   try:part=sys.stdin.buffer.read(desc['size_bytes']-len(source))
   except BaseException:facts['stdin_extent_unknown']=True;raise
   need(type(part) is bytes and len(part)<=desc['size_bytes']-len(source),'source_read_shape')
   need(bool(part),'source_eof');source+=part;facts['source_bytes'][-1]=len(source);facts['source_sha256'][-1]=sha(source)
  buffers.append(source)
 gate()
 try:tail=sys.stdin.buffer.read(1)
 except BaseException:facts['stdin_extent_unknown']=True;raise
 need(tail==b'','source_trailing');facts['stdin_eof']=True;gate()
 for source,desc in zip(buffers,d):
  need(canon({'size_bytes':len(source),'sha256':sha(source),'git_blob':hashlib.sha1(b'blob '+str(len(source)).encode()+b'\0'+source).hexdigest()})==canon(desc),'source_binding')
 gate();return b,end,buffers
def module(source,i):
 gate();m=types.ModuleType('_held_writer_'+str(i));m.__file__=R+P+('_component_v1.py','_gate2_resume_v1.py')[i];exec(compile(source,m.__file__,'exec'),m.__dict__);gate();return m
'''
WRITER_TAIL = r'''T=R+'openspec/changes/fix-accepted-policy-preprocessing/evidence/compiler-component-01/gate2-p0-exception.outer-tool.original.json'
def run():
 b,end,buffers=prepare()
 modules=[]
 for i,source in enumerate(buffers):modules.append(module(source,i))
 comp,op=modules;p=Path(T);gate();need(p.parent.resolve(strict=True)==p.parent,'target_parent');gate()
 try:result=op.write_fixed_v1(p,b,12288,gate,comp)
 except BaseException as e:
  facts.update(getattr(e,'facts',{}));facts['unknown_closure']=not facts.get('close_completed',False);raise
 facts.update(result['write_facts']);facts['unknown_closure']=not facts['close_completed'];gate()
 need(type(facts['allocated_bytes']) is int and 0<=facts['allocated_bytes']<=12288,'writer_allocation')
 q=(len(b)+4095)//4096*4096
 return {'completed':True,'external_terminal_required':True,'size_bytes':len(b),'sha256':sha(b),'write_facts':facts,'deadline_ns':end,'all_forms_quote_bytes':max(facts['allocated_bytes'],q)+q+8192}
try:value=run();code=0
except BaseException as e:
 if gate is None or denied:raise SystemExit(1)
 value={'completed':False,'external_terminal_required':True,'cause':str(e).encode('ascii','backslashreplace')[:80].decode('ascii'),'known':facts,'omitted_or_unknown':True};code=1
try:
 out=canon(value)+b'\n';gate();need(len(out)<=2048,'terminal_bound')
 if os.write(1,out)!=len(out):raise RuntimeError('terminal_write')
 gate()
except BaseException:raise SystemExit(1)
raise SystemExit(code)
'''
WRITER_BODY = WRITER_HEAD + WRITER_COMMON_SOURCE + WRITER_TAIL
WRITER_SOURCE = (WRITER_READY + 'try:\n' + ''.join(' ' + line + '\n' for line in WRITER_BODY.splitlines())
                 + 'except SystemExit:raise\nexcept BaseException:raise SystemExit(1)\n')
WRITER_COMPRESSED = base64.b85encode(zlib.compress(WRITER_BODY.encode('ascii'), 9)).decode('ascii')
WRITER_CARRIER = WRITER_READY + "import base64,zlib\ntry:exec(zlib.decompress(base64.b85decode(" + repr(WRITER_COMPRESSED) + ")) )\nexcept SystemExit:raise\nexcept BaseException:raise SystemExit(1)\n"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode('ascii')


class WriterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.sources = {}
        for relative in (COMPONENT, OPERATOR):
            raw = (REPO / relative).read_bytes()
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            self.sources[relative] = {'size_bytes': len(raw),
                'sha256': hashlib.sha256(raw).hexdigest(),
                'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}
        self.target = self.root / TARGET
        self.target.parent.mkdir(parents=True)
        self.selected = canonical({'call': {'tool': 'controlled', 'codes': ['fixed']},
                                   'frames': [{'output': 'known raw uint64 18446744073709551615'}]})
        self.test_mode = 'ACTUAL_NT_FILESTANDARDINFO' if os.name == 'nt' else 'CONTROLLED_SIMULATED_NT_REAL_OWNED_FD'

    def ack(self, **changes):
        value = {'remaining_ms': 1000, 'size_bytes': len(self.selected),
                 'sha256': hashlib.sha256(self.selected).hexdigest(),
                 'selected_base64': base64.b64encode(self.selected).decode('ascii')}
        value.update(changes)
        return canonical(value) + b'\n'

    def invoke(self, ack=None, *, source=None, clock=None, write_effect=None,
               read_effect=None, close_effect=None, fsync_effect=None, trailing=b'',
               disk_free=100_000_000_000, expect_absent=True, disk_effect=None,
               lseek_effect=None, nt_effect=None, output_effect=None, return_raw=False,
               import_failure=None, windows_adapter=True, held_input=b'', argv_descriptor=None,
               input_chunk=None, compile_effect=None, input_effect=None, argv_prefix=(), line_caps=None):
        import builtins
        import ctypes
        real_import, real_write = builtins.__import__, os.write
        output, opened, paths = bytearray(), [], {}
        owner = self
        class Input:
            buffer = None
            def __init__(self):
                self.buffer = self
                raw = owner.ack(sources=owner.sources) if ack is None and source == QUALIFIED_REUSE_SOURCE else owner.ack() if ack is None else ack
                self.held = io.BytesIO(raw + held_input + trailing)
            def readline(self, cap):
                if line_caps is not None: line_caps.append(cap)
                owner.assertTrue(output.startswith(b'{"ready":true,"schema_version":1}\n'))
                if expect_absent: owner.assertFalse(owner.target.exists())
                return self.held.readline(cap)
            def read(self, cap):
                count = min(cap, input_chunk) if input_chunk else cap
                return input_effect(self.held, count) if input_effect else self.held.read(count)
        def observed(s):
            if os.name == 'nt': return s
            return types.SimpleNamespace(**{name: getattr(s, name) for name in dir(s) if name.startswith('st_')},
                                         st_birthtime_ns=None)
        class ControlledPath:
            """Linux-only API adapter; identity/storage still come from this real owned path."""
            def __init__(self, value): self.actual = Path(value)
            def __fspath__(self): return os.fspath(self.actual)
            def __str__(self): return str(self.actual)
            def __eq__(self, other): return self.actual == (other.actual if isinstance(other, ControlledPath) else other)
            def is_absolute(self): return self.actual.is_absolute()
            def resolve(self, **kwargs): return ControlledPath(self.actual.resolve(**kwargs))
            @property
            def parent(self): return ControlledPath(self.actual.parent)
            def lstat(self): return observed(self.actual.lstat())
        def path(value):
            value = str(value)
            result = self.root / value[len(FIXED_REPO):] if value.startswith(FIXED_REPO) else Path(value)
            return ControlledPath(result) if os.name != 'nt' else result
        class ControlledOS:
            name = 'nt' if windows_adapter else 'posix'
            O_BINARY = getattr(os, 'O_BINARY', 0)
            def __getattr__(self, name):
                if name == 'fstat': return lambda fd: observed(os.fstat(fd))
                return getattr(os, name)
        class ControlledCall:
            def __call__(self, handle, kind, pointer, size):
                s = os.fstat(handle)
                value = pointer._obj
                # A declared simulated NT API, never native NT evidence on Linux.
                value.allocation = max(s.st_blocks * 512, (s.st_size + 4095) // 4096 * 4096)
                value.size, value.links, value.pending, value.directory = s.st_size, s.st_nlink, 0, 0
                return nt_effect(value, 1) if nt_effect else 1
        controlled_ctypes = types.SimpleNamespace(**{name: getattr(ctypes, name) for name in
            ('Structure', 'c_longlong', 'c_ubyte', 'c_int', 'c_void_p', 'byref', 'sizeof')},
            wintypes=types.SimpleNamespace(DWORD=ctypes.c_uint32, HANDLE=ctypes.c_void_p, BOOL=ctypes.c_int32),
            WinDLL=lambda *a, **k: types.SimpleNamespace(GetFileInformationByHandleEx=ControlledCall()))
        def imported(name, globals=None, locals=None, fromlist=(), level=0):
            if name == import_failure and globals and globals.get('__name__') == '__main__':
                raise ImportError('controlled_missing_stdlib')
            if name == 'pathlib' and globals and globals.get('__name__') == '__main__':
                return types.SimpleNamespace(Path=path)
            if name == 'os' and globals and globals.get('__name__') in ('__main__', '_held_writer_0') and (os.name != 'nt' or not windows_adapter):
                return ControlledOS()
            if os.name != 'nt' and globals and globals.get('__name__') in ('__main__', '_held_writer_0'):
                if name == 'msvcrt': return types.SimpleNamespace(get_osfhandle=lambda fd: fd)
                if name == 'ctypes': return controlled_ctypes
            return real_import(name, globals, locals, fromlist, level)
        def write(fd, raw):
            if fd == 1:
                if output_effect: return output_effect(raw, output)
                output.extend(raw)
                return len(raw)
            return write_effect(fd, raw, real_write) if write_effect else real_write(fd, raw)
        real_open, real_read, real_close, real_fsync, real_lseek = os.open, os.read, os.close, os.fsync, os.lseek
        def opened_fd(path, flags, *args):
            opened.append((str(path), flags))
            fd = real_open(path, flags, *args)
            paths[fd] = str(path)
            return fd
        def read(fd, count):
            return read_effect(fd, count, paths.get(fd), real_read) if read_effect else real_read(fd, count)
        def close(fd):
            return close_effect(fd, paths.get(fd), real_close) if close_effect else real_close(fd)
        def fsync(fd):
            return fsync_effect(fd, paths.get(fd), real_fsync) if fsync_effect else real_fsync(fd)
        def lseek(fd, offset, whence):
            return lseek_effect(fd, offset, whence, real_lseek) if lseek_effect else real_lseek(fd, offset, whence)
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch('builtins.__import__', side_effect=imported))
            stack.enter_context(mock.patch('sys.stdin', Input()))
            stack.enter_context(mock.patch('sys.argv', ['-c', *argv_prefix, argv_descriptor or canonical(
                [self.sources[COMPONENT], self.sources[OPERATOR]]).decode('ascii')]))
            stack.enter_context(mock.patch('os.write', side_effect=write))
            stack.enter_context(mock.patch('os.open', side_effect=opened_fd))
            stack.enter_context(mock.patch('os.read', side_effect=read))
            stack.enter_context(mock.patch('os.close', side_effect=close))
            stack.enter_context(mock.patch('os.fsync', side_effect=fsync))
            stack.enter_context(mock.patch('os.lseek', side_effect=lseek))
            stack.enter_context(mock.patch('shutil.disk_usage', side_effect=(disk_effect if disk_effect else
                lambda _: types.SimpleNamespace(free=disk_free))))
            if clock is not None: stack.enter_context(mock.patch('time.monotonic_ns', side_effect=clock))
            if compile_effect is not None:
                real_compile = builtins.compile
                def compiled(source, filename, *args, **kwargs):
                    compile_effect(source, filename)
                    return real_compile(source, filename, *args, **kwargs)
                stack.enter_context(mock.patch('builtins.compile', side_effect=compiled))
            if nt_effect is not None and os.name == 'nt':
                real_dll = ctypes.WinDLL
                def dll(*args, **kwargs):
                    native = real_dll(*args, **kwargs).GetFileInformationByHandleEx
                    class Call:
                        def __setattr__(self, name, value): setattr(native, name, value)
                        def __call__(self, handle, kind, pointer, size):
                            value = native(handle, kind, pointer, size)
                            return nt_effect(pointer._obj, value)
                    return types.SimpleNamespace(GetFileInformationByHandleEx=Call())
                stack.enter_context(mock.patch('ctypes.WinDLL', side_effect=dll))
            try:
                exec(compile(source or STANDALONE_WRITER_SOURCE, '<fixed-inline-outer-writer>', 'exec'),
                     {'__name__': '__main__'})
                code = 0
            except SystemExit as error:
                code = error.code
        lines = bytes(output).splitlines()
        if return_raw: return code, bytes(output), opened
        return code, [json.loads(line) for line in lines], opened

    def test_actual_literal_ready_ack_same_fd_success(self):
        code, lines, opened = self.invoke()
        self.assertEqual(code, 0)
        self.assertEqual(lines[0], {'ready': True, 'schema_version': 1})
        result = lines[-1]
        self.assertTrue(result['completed'])
        self.assertTrue(result['external_terminal_required'])
        self.assertNotIn('own_terminal_verified', result)
        self.assertEqual(self.target.read_bytes(), self.selected)
        self.assertTrue(result['write_facts']['fsync_completed'])
        self.assertTrue(result['write_facts']['close_completed'])
        self.assertLessEqual(result['write_facts']['allocated_bytes'], 8192)
        self.assertEqual(sum(bool(flags & os.O_EXCL) for _, flags in opened), 1)

    def test_ack_hash_refuses_before_any_target_allocation(self):
        code, lines, opened = self.invoke(self.ack(sha256='0' * 64))
        self.assertEqual(code, 1)
        self.assertFalse(lines[-1]['completed'])
        self.assertFalse(self.target.exists())
        self.assertFalse(any(flags & os.O_CREAT for _, flags in opened))

    def test_carrier_roundtrip_and_real_writer_execution(self):
        import ast
        self.assertEqual(zlib.decompress(base64.b85decode(STANDALONE_WRITER_COMPRESSED)), STANDALONE_WRITER_BODY.encode())
        for source in (STANDALONE_WRITER_SOURCE, STANDALONE_WRITER_CARRIER):
            ast.parse(source, feature_version=(3, 10))
        self.assertLess(STANDALONE_WRITER_CARRIER.index('_ready=time.monotonic_ns()'),
                        STANDALONE_WRITER_CARRIER.index('zlib.decompress'))
        code, lines, _ = self.invoke(source=STANDALONE_WRITER_CARRIER)
        self.assertEqual(code, 0)
        self.assertTrue(lines[-1]['completed'])

    def test_bad_ack_types_bounds_duplicates_and_trailing_input_never_open(self):
        for change in ({'remaining_ms': True}, {'remaining_ms': 0}, {'remaining_ms': 150001},
                       {'remaining_ms': 1.0}, {'size_bytes': True}, {'size_bytes': 8193},
                       {'selected_base64': '!'}, {'sources': {}}, {'extra': 1}):
            with self.subTest(change=change):
                code, lines, opened = self.invoke(self.ack(**change))
                self.assertEqual(code, 1)
                self.assertTrue(len(lines) == 1 or not lines[-1]['completed'])
                self.assertFalse(any(flags & os.O_CREAT for _, flags in opened))
        raw = self.ack().replace(b'{', b'{"remaining_ms":1000,', 1)
        code, lines, opened = self.invoke(raw)
        self.assertEqual(code, 1)
        self.assertEqual(lines, [{'ready': True, 'schema_version': 1}])
        self.assertFalse(opened)
        code, lines, opened = self.invoke(trailing=b'x')
        self.assertEqual(code, 1)
        self.assertEqual(lines[-1]['cause'], 'ack_trailing')
        self.assertFalse(opened)

    def test_ack_delay_consumes_ready_mapping_without_allocation(self):
        ticks = iter((100, 100 + 1_000_000_000))
        code, lines, opened = self.invoke(clock=lambda: next(ticks))
        self.assertEqual(code, 1)
        self.assertEqual(lines, [{'ready': True, 'schema_version': 1}])
        self.assertFalse(opened)

    def test_clock_regression_refuses_before_source_open(self):
        ticks = iter((100, 100, 99))
        code, lines, opened = self.invoke(clock=lambda: next(ticks))
        self.assertEqual(code, 1)
        self.assertEqual(lines, [{'ready': True, 'schema_version': 1}])
        self.assertFalse(opened)

    def test_historical_qualified_source_mutation_refuses_before_exec_or_target(self):
        path = self.root / COMPONENT
        raw = path.read_bytes()
        path.write_bytes(raw.replace(b'Task 2.10', b'Task 2.11', 1))
        code, lines, opened = self.invoke(source=QUALIFIED_REUSE_SOURCE)
        self.assertEqual(code, 1)
        self.assertEqual(lines[-1]['cause'], 'source_binding')
        self.assertFalse(self.target.exists())
        self.assertFalse(any(flags & os.O_CREAT for _, flags in opened))

    def test_legal_source_short_reads_complete(self):
        def short(fd, count, path, real):
            return real(fd, min(count, 997)) if path != str(self.target) else real(fd, count)
        code, lines, _ = self.invoke(read_effect=short)
        self.assertEqual(code, 0)
        self.assertTrue(lines[-1]['completed'])

    def test_historical_source_read_and_close_keep_primary_and_secondary(self):
        closed = []
        def read(fd, count, path, real):
            raise OSError('source_read_first')
        def close(fd, path, real):
            closed.append(fd)
            real(fd)
            raise OSError('source_close_second')
        code, lines, opened = self.invoke(source=QUALIFIED_REUSE_SOURCE, read_effect=read, close_effect=close)
        self.assertEqual(code, 1)
        self.assertEqual(lines[-1]['cause'], 'source_read_first')
        self.assertEqual(lines[-1]['known']['secondary'], ['source_close_OSError'])
        self.assertTrue(lines[-1]['known']['unknown_closure'])
        self.assertEqual(len(closed), 1)
        self.assertFalse(any(flags & os.O_CREAT for _, flags in opened))

    def test_target_fsync_and_close_keep_first_and_known_extent(self):
        close_calls = []
        def fsync(fd, path, real):
            raise OSError('target_fsync_first')
        def close(fd, path, real):
            real(fd)
            if path == str(self.target):
                close_calls.append(fd)
                raise OSError('target_close_second')
        code, lines, _ = self.invoke(fsync_effect=fsync, close_effect=close)
        self.assertEqual(code, 1)
        self.assertEqual(lines[-1]['cause'], 'target_fsync_first')
        facts = lines[-1]['known']
        self.assertEqual(facts['written_bytes'], len(self.selected))
        self.assertFalse(facts['extent_unknown'])
        self.assertFalse(facts['fsync_completed'])
        self.assertFalse(facts['close_completed'])
        self.assertTrue(facts['unknown_closure'])
        self.assertEqual(facts['secondary'], ['close_OSError'])
        self.assertEqual(len(close_calls), 1)
        self.assertEqual(self.target.read_bytes(), self.selected)

    def test_unreturned_write_extent_stays_unknown_and_prefix_preserved(self):
        def write(fd, raw, real):
            real(fd, raw[:3])
            raise OSError('unreturned_write')
        code, lines, _ = self.invoke(write_effect=write)
        self.assertEqual(code, 1)
        self.assertEqual(self.target.read_bytes(), self.selected[:3])
        facts = lines[-1]['known']
        self.assertEqual(facts['written_bytes'], 0)
        self.assertTrue(facts['extent_unknown'])
        self.assertTrue(facts['close_completed'])
        self.assertFalse(facts['fsync_completed'])

    def test_positive_short_os_writes_finish_on_same_exclusive_fd(self):
        calls = []
        def write(fd, raw, real):
            calls.append(fd)
            return real(fd, raw[:7])
        code, lines, _ = self.invoke(write_effect=write)
        self.assertEqual(code, 0)
        self.assertGreater(len(calls), 1)
        self.assertEqual(len(set(calls)), 1)
        self.assertEqual(lines[-1]['write_facts']['written_bytes'], len(self.selected))

    def test_existing_selected_original_is_not_overwritten(self):
        self.target.write_bytes(b'original')
        code, lines, _ = self.invoke(expect_absent=False)
        self.assertEqual(code, 1)
        self.assertFalse(lines[-1]['completed'])
        self.assertEqual(self.target.read_bytes(), b'original')

    def test_expired_mapping_has_no_new_terminal_document_after_ready(self):
        ticks = iter((100, 1_000_000_100))
        code, lines, opened = self.invoke(clock=lambda: next(ticks))
        self.assertEqual(code, 1)
        self.assertEqual(lines, [{'ready': True, 'schema_version': 1}])
        self.assertFalse(opened)

    def test_floor_denial_has_no_new_terminal_document_or_target(self):
        code, lines, opened = self.invoke(disk_free=43_620_761_600 + 24576 - 1)
        self.assertEqual(code, 1)
        self.assertEqual(lines, [{'ready': True, 'schema_version': 1}])
        self.assertFalse(opened)

    def test_late_floor_cannot_authorize_exclusive_open(self):
        import inspect
        now = [100]
        def floor(_):
            for frame in inspect.stack():
                if frame.function == 'write_fixed_v1' and 'facts' not in frame.frame.f_locals:
                    now[0] += 1_000_000_000
            return types.SimpleNamespace(free=100_000_000_000)
        code, lines, opened = self.invoke(clock=lambda: now[0], disk_effect=floor)
        self.assertEqual(code, 1)
        self.assertEqual(lines, [{'ready': True, 'schema_version': 1}])
        self.assertFalse(self.target.exists())
        self.assertFalse(any(flags & os.O_CREAT for _, flags in opened))

    def test_late_floor_cannot_authorize_write_after_owned_open(self):
        import inspect
        now = [100]
        def floor(_):
            for frame in inspect.stack():
                if frame.function == 'write_fixed_v1' and 'facts' in frame.frame.f_locals:
                    now[0] += 1_000_000_000
            return types.SimpleNamespace(free=100_000_000_000)
        code, lines, _ = self.invoke(clock=lambda: now[0], disk_effect=floor)
        self.assertEqual(code, 1)
        self.assertEqual(lines, [{'ready': True, 'schema_version': 1}])
        self.assertEqual(self.target.read_bytes(), b'')

    def test_late_lseek_has_no_subsequent_read(self):
        now, reads = [100], []
        def lseek(fd, offset, whence, real):
            result = real(fd, offset, whence)
            now[0] += 1_000_000_000
            return result
        def read(fd, count, path, real):
            reads.append((fd, count))
            return real(fd, count)
        code, lines, _ = self.invoke(clock=lambda: now[0], lseek_effect=lseek, read_effect=read)
        self.assertEqual(code, 1)
        self.assertEqual(lines, [{'ready': True, 'schema_version': 1}])
        self.assertEqual(reads, [])
        self.assertEqual(self.target.read_bytes(), self.selected)

    def test_nt_failure_negative_allocation_and_wrong_length_refuse(self):
        for mode in ('failed', 'negative', 'length', 'links', 'directory', 'pending', 'excess'):
            with self.subTest(mode=mode):
                def nt(value, ok):
                    self.assertTrue(ok, 'Positive underlying NT call must really succeed.')
                    if mode == 'failed': return 0
                    if mode == 'negative': value.allocation = -1
                    if mode == 'length': value.size += 1
                    if mode == 'links': value.links = 2
                    if mode == 'directory': value.directory = 1
                    if mode == 'pending': value.pending = 1
                    if mode == 'excess': value.allocation = 8193
                    return ok
                code, lines, _ = self.invoke(nt_effect=nt)
                self.assertEqual(code, 1)
                self.assertEqual(lines[-1]['cause'], 'writer_allocation')
                self.assertTrue(lines[-1]['known']['close_completed'])
                self.assertEqual(self.target.read_bytes(), self.selected)
                self.target.unlink()  # Owned controlled fixture only; each subcase gets a fresh target.

    def test_creator_fd_reread_mismatch_refuses_without_rewrite(self):
        calls = []
        def read(fd, count, path, real):
            calls.append(count)
            raw = real(fd, count)
            return (bytes([raw[0] ^ 1]) + raw[1:]) if raw else raw
        code, lines, opened = self.invoke(read_effect=read)
        self.assertEqual(code, 1)
        self.assertEqual(lines[-1]['cause'], 'writer_readback')
        self.assertEqual(self.target.read_bytes(), self.selected)
        self.assertEqual(sum(bool(flags & os.O_EXCL) for _, flags in opened), 1)
        self.assertTrue(calls)

    def test_maximum_raw_extent_and_inclusive_two_forms_quote(self):
        self.selected = b'x' * 8192
        code, lines, _ = self.invoke()
        self.assertEqual(code, 0)
        self.assertEqual(self.target.read_bytes(), self.selected)
        self.assertEqual(lines[-1]['size_bytes'], 8192)
        self.assertEqual(lines[-1]['all_forms_quote_bytes'], 24576)
        self.assertLessEqual(lines[-1]['write_facts']['allocated_bytes'], 8192)

    def test_late_fsync_and_close_do_not_start_terminal_write(self):
        for operation in ('fsync', 'close'):
            with self.subTest(operation=operation):
                now = [100]
                def fsync(fd, path, real):
                    result = real(fd)
                    if operation == 'fsync': now[0] += 1_000_000_000
                    return result
                def close(fd, path, real):
                    result = real(fd)
                    if operation == 'close': now[0] += 1_000_000_000
                    return result
                code, lines, _ = self.invoke(clock=lambda: now[0], fsync_effect=fsync, close_effect=close)
                self.assertEqual(code, 1)
                self.assertEqual(lines, [{'ready': True, 'schema_version': 1}])
                self.assertEqual(self.target.read_bytes(), self.selected)
                self.target.unlink()

    def test_terminal_short_write_is_single_attempt_no_fallback(self):
        calls = []
        def output(raw, held):
            calls.append(raw)
            if len(calls) == 1:
                held.extend(raw)
                return len(raw)
            held.extend(raw[:13])
            return 13
        code, raw, _ = self.invoke(output_effect=output, return_raw=True)
        self.assertEqual(code, 1)
        self.assertEqual(len(calls), 2)  # READY plus exactly one terminal attempt.
        self.assertEqual(raw, calls[0] + calls[1][:13])
        self.assertEqual(self.target.read_bytes(), self.selected)

    def test_actual_terminal_delay_is_external_and_cannot_reemit(self):
        now, calls = [100], []
        def output(raw, held):
            calls.append(raw)
            held.extend(raw)
            if len(calls) == 2: now[0] += 1_000_000_000
            return len(raw)
        code, raw, _ = self.invoke(clock=lambda: now[0], output_effect=output, return_raw=True)
        self.assertEqual(code, 1)
        self.assertTrue(json.loads(raw.splitlines()[-1])['completed'])
        self.assertEqual(len(calls), 2)
        # The earlier completed document is insufficient: actual terminal status is failure.

    def test_missing_ack_and_unknown_clock_have_no_failure_persistence(self):
        code, lines, opened = self.invoke(b'')
        self.assertEqual((code, lines, opened), (1, [{'ready': True, 'schema_version': 1}], []))
        ticks = iter((100, OSError('clock_unknown')))
        def clock():
            value = next(ticks)
            if isinstance(value, BaseException): raise value
            return value
        code, lines, opened = self.invoke(clock=clock)
        self.assertEqual((code, lines, opened), (1, [{'ready': True, 'schema_version': 1}], []))

    def test_failed_stdlib_import_after_ready_has_no_traceback_fallback(self):
        code, lines, opened = self.invoke(import_failure='ctypes')
        self.assertEqual((code, lines, opened), (1, [{'ready': True, 'schema_version': 1}], []))

    def test_actual_non_windows_runtime_guard_is_preserved(self):
        code, lines, opened = self.invoke(windows_adapter=False)
        self.assertEqual((code, lines, opened), (1, [{'ready': True, 'schema_version': 1}], []))

    def test_unknown_or_noninteger_floor_never_allocates(self):
        for free in (True, 100_000_000_000.0, -1, None):
            with self.subTest(free=free):
                code, lines, opened = self.invoke(disk_free=free)
                self.assertEqual((code, lines, opened), (1, [{'ready': True, 'schema_version': 1}], []))
        def failed(_): raise OSError('floor_unknown')
        code, lines, opened = self.invoke(disk_effect=failed)
        self.assertEqual((code, lines, opened), (1, [{'ready': True, 'schema_version': 1}], []))

    def test_real_creator_fd_epoch_change_refuses(self):
        changed = []
        def read(fd, count, path, real):
            raw = real(fd, count)
            if raw and not changed:
                s = self.target.stat()
                os.utime(self.target, ns=(s.st_atime_ns, s.st_mtime_ns + 1_000_000))
                changed.append(True)
            return raw
        code, lines, _ = self.invoke(read_effect=read)
        self.assertEqual(code, 1)
        self.assertEqual(lines[-1]['cause'], 'writer_fd_drift')
        self.assertTrue(lines[-1]['known']['close_completed'])
        self.assertEqual(self.target.read_bytes(), self.selected)

    def test_nt_allocation_drift_between_creator_fd_observations_refuses(self):
        calls = []
        def drift(value, ok):
            calls.append(value.allocation)
            if len(calls) == 2: value.allocation += 4096
            return ok
        code, lines, _ = self.invoke(nt_effect=drift)
        self.assertEqual(code, 1)
        self.assertEqual(lines[-1]['cause'], 'writer_fd_drift')
        self.assertEqual(len(calls), 2)
        self.assertTrue(lines[-1]['known']['close_completed'])

    def test_close_only_failure_keeps_completed_prefix_and_unknown_closure(self):
        calls = []
        def close(fd, path, real):
            real(fd)
            calls.append(fd)
            raise OSError('only_close_failure')
        code, lines, _ = self.invoke(close_effect=close)
        self.assertEqual(code, 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(lines[-1]['cause'], 'only_close_failure')
        facts = lines[-1]['known']
        self.assertTrue(facts['fsync_completed'])
        self.assertTrue(facts['readback_completed'])
        self.assertTrue(facts['unknown_closure'])
        self.assertFalse(facts['close_completed'])
        self.assertEqual(self.target.read_bytes(), self.selected)


class CommonFragmentTests(unittest.TestCase):
    setUp = WriterTests.setUp
    ack = WriterTests.ack

    def invoke_role(self, *, setup, phase_now=100, selected=b'', remaining_ms=150000, line_caps=None):
        head = SETUP_COMMON_HEAD if setup else WRITER_HEAD
        tail = r'''try:
 b,end,buffers=prepare();gate()
 value={'end':end,'selected_bytes':len(b),'source_bytes':[len(v) for v in buffers]}
 out=canon(value)+b'\n'
 if os.write(1,out)!=len(out):raise RuntimeError('test_terminal')
 gate()
except BaseException:raise SystemExit(1)
'''
        self.selected = selected
        source = WRITER_READY + head + WRITER_COMMON_SOURCE + tail
        compiled = []
        ticks = iter((100,))
        code, lines, opened = WriterTests.invoke(self, self.ack(remaining_ms=remaining_ms), source=source,
            held_input=b''.join((self.root / n).read_bytes() for n in (COMPONENT, OPERATOR)),
            argv_prefix=('fixed_commit', 'fixed_approval') if setup else (),
            line_caps=line_caps,
            clock=lambda: next(ticks, phase_now),
            compile_effect=lambda raw, filename: compiled.append(filename))
        self.assertFalse(any(p.startswith(FIXED_REPO) for p in compiled),
                         'Shared preparation must authenticate both buffers without executing either.')
        self.assertEqual(opened, [])
        return code, lines

    def test_setup_empty_payload_and_third_source_arg_authenticate_without_exec(self):
        code, lines = self.invoke_role(setup=True)
        self.assertEqual(code, 0)
        self.assertEqual(lines[-1]['selected_bytes'], 0)
        self.assertEqual(lines[-1]['source_bytes'],
                         [self.sources[COMPONENT]['size_bytes'], self.sources[OPERATOR]['size_bytes']])

    def test_setup_uses_original_end_minus_ten_seconds(self):
        code, lines = self.invoke_role(setup=True, phase_now=140_000_000_100)
        self.assertEqual((code, lines), (1, [{'ready': True, 'schema_version': 1}]))

    def test_writer_keeps_original_end_without_setup_reserve(self):
        code, lines = self.invoke_role(setup=False, selected=b'x', phase_now=140_000_000_100)
        self.assertEqual(code, 0)
        self.assertEqual(lines[-1]['end'], 100 + 150_000_000_000)
        self.assertEqual(lines[-1]['selected_bytes'], 1)

    def test_fixed_role_heads_keep_setup_ack_16384_and_writer_ack_24576(self):
        for setup, expected in ((True, 16385), (False, 24577)):
            with self.subTest(setup=setup):
                observed = []
                code, _ = self.invoke_role(setup=setup, selected=b'' if setup else b'x', line_caps=observed)
                self.assertEqual(code, 0)
                self.assertEqual(observed, [expected])


class HeldWriterTests(unittest.TestCase):
    setUp = WriterTests.setUp
    ack = WriterTests.ack

    def invoke(self, ack=None, **kwargs):
        kwargs.setdefault('source', WRITER_SOURCE)
        kwargs.setdefault('held_input', b''.join((self.root / name).read_bytes() for name in (COMPONENT, OPERATOR)))
        return WriterTests.invoke(self, ack, **kwargs)

    def test_exact_held_buffers_then_eof_are_authenticated_before_same_fd_write(self):
        code, lines, opened = self.invoke()
        self.assertEqual(code, 0)
        self.assertTrue(lines[-1]['completed'])
        self.assertEqual(self.target.read_bytes(), self.selected)
        self.assertEqual(sum(bool(flags & os.O_EXCL) for _, flags in opened), 1)
        self.assertEqual(len(opened), 1, 'Held source transport must not reread project paths.')

    def test_twelve_kibibyte_selected_json_and_maximum_canonical_ack_are_accepted(self):
        value = {'call': {'tool': 'controlled', 'codes': ['fixed']}, 'frames': [{'output': ''}]}
        value['frames'][0]['output'] = 'x' * (12288 - len(canonical(value)))
        self.selected = canonical(value)
        self.assertEqual(len(self.selected), 12288)
        ack = self.ack(remaining_ms=150000)
        self.assertEqual(len(ack), 16524)
        code, lines, opened = self.invoke(ack)
        self.assertEqual(code, 0)
        self.assertEqual(self.target.read_bytes(), self.selected)
        self.assertEqual(lines[-1]['size_bytes'], 12288)
        self.assertEqual(lines[-1]['all_forms_quote_bytes'], 32768)
        self.assertLessEqual(lines[-1]['write_facts']['allocated_bytes'], 12288)
        self.assertEqual(len(opened), 1)

    def test_payload_12289_and_ack_24577_refuse_before_exec_or_exclusive_open(self):
        self.selected = b'x' * 12289
        for ack in (self.ack(), b' ' * 24576 + b'\n'):
            with self.subTest(ack_bytes=len(ack)):
                compiled, caps = [], []
                code, lines, opened = self.invoke(ack, line_caps=caps,
                    compile_effect=lambda raw, name: compiled.append(name))
                self.assertEqual(code, 1)
                self.assertEqual(caps, [24577])
                self.assertFalse(self.target.exists())
                self.assertEqual(opened, [])
                self.assertFalse(any(name.startswith(FIXED_REPO) for name in compiled))
                self.assertTrue(len(lines) == 1 or lines[-1]['completed'] is False)

    def test_new_writer_floor_includes_full_32768_forms_before_open(self):
        code, lines, opened = self.invoke(disk_free=43620761600 + 32768 - 1)
        self.assertEqual((code, lines, opened), (1, [{'ready': True, 'schema_version': 1}], []))
        code, lines, opened = self.invoke(disk_free=43620761600 + 32768)
        self.assertEqual(code, 0)
        self.assertTrue(lines[-1]['completed'])
        self.assertEqual(len(opened), 1)

    def test_new_ack_duplicates_types_and_noncanonical_input_never_compile_or_open(self):
        variants = [self.ack(**change) for change in (
            {'remaining_ms': True}, {'remaining_ms': 1.0}, {'size_bytes': True}, {'size_bytes': 1.0},
            {'selected_base64': '!'}, {'sha256': 'A' * 64}, {'extra': 1})]
        variants += [self.ack().replace(b'{', b'{"remaining_ms":1000,', 1), b' ' + self.ack()]
        for ack in variants:
            with self.subTest(ack=ack[:60]):
                compiled = []
                code, lines, opened = self.invoke(ack,
                    compile_effect=lambda raw, name: compiled.append(name))
                self.assertEqual(code, 1)
                self.assertEqual(opened, [])
                self.assertFalse(any(name.startswith(FIXED_REPO) for name in compiled))
                self.assertTrue(len(lines) == 1 or lines[-1]['completed'] is False)

    def test_new_nt_allocation_12289_refuses_with_known_closed_full_prefix(self):
        def nt(value, ok):
            self.assertTrue(ok)
            value.allocation = 12289
            return ok
        code, lines, _ = self.invoke(nt_effect=nt)
        self.assertEqual(code, 1)
        self.assertEqual(lines[-1]['cause'], 'write_allocation')
        self.assertTrue(lines[-1]['known']['close_completed'])
        self.assertEqual(lines[-1]['known']['allocated_bytes'], 12289)
        self.assertEqual(self.target.read_bytes(), self.selected)

    def test_twelve_kibibyte_fsync_then_close_fault_keeps_primary_and_full_source_facts(self):
        self.selected = b'x' * 12288
        def fsync(fd, path, real): raise OSError('max_fsync_first')
        closed = []
        def close(fd, path, real):
            closed.append(fd);real(fd);raise OSError('max_close_second')
        code, lines, _ = self.invoke(fsync_effect=fsync, close_effect=close)
        self.assertEqual(code, 1)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[-1]['cause'], 'max_fsync_first')
        self.assertEqual(lines[-1]['known']['secondary'], ['close_failed'])
        self.assertEqual(lines[-1]['known']['written_bytes'], 12288)
        self.assertTrue(lines[-1]['known']['stdin_eof'])
        self.assertTrue(lines[-1]['known']['unknown_closure'])
        self.assertEqual(len(closed), 1)
        self.assertEqual(self.target.read_bytes(), self.selected)

    def test_carrier_exact_rebuild_and_actual_held_execution(self):
        import ast
        self.assertEqual(zlib.decompress(base64.b85decode(WRITER_COMPRESSED)), WRITER_BODY.encode())
        for source in (WRITER_SOURCE, WRITER_CARRIER): ast.parse(source, feature_version=(3, 10))
        code, lines, _ = self.invoke(source=WRITER_CARRIER)
        self.assertEqual(code, 0)
        self.assertTrue(lines[-1]['completed'])

    def test_both_held_hashes_git_and_sizes_validate_before_either_executes(self):
        raw = b''.join((self.root / name).read_bytes() for name in (COMPONENT, OPERATOR))
        for position in (0, len(raw) - 1):
            with self.subTest(position=position):
                changed = raw[:position] + bytes([raw[position] ^ 1]) + raw[position + 1:]
                compiled = []
                code, lines, opened = self.invoke(held_input=changed, compile_effect=lambda b, p: compiled.append(p))
                self.assertEqual(code, 1)
                self.assertEqual(lines[-1]['cause'], 'source_binding')
                self.assertFalse(any(p.startswith(FIXED_REPO) for p in compiled))
                self.assertEqual(opened, [])
                self.assertTrue(lines[-1]['known']['stdin_eof'])

    def test_source_args_are_independent_canonical_typed_authority(self):
        original = [self.sources[COMPONENT], self.sources[OPERATOR]]
        variants = [[], [original[0]], dict(source=original), [dict(original[0], size_bytes=True), original[1]],
                    [dict(original[0], size_bytes=1.0), original[1]], [dict(original[0], extra=1), original[1]],
                    [dict(original[0], git_blob='A' * 40), original[1]]]
        for variant in variants:
            with self.subTest(variant=variant):
                compiled = []
                code, lines, opened = self.invoke(argv_descriptor=canonical(variant).decode(),
                    compile_effect=lambda b, p: compiled.append(p))
                self.assertEqual(code, 1)
                self.assertEqual(lines, [{'ready': True, 'schema_version': 1}])
                self.assertFalse(any(p.startswith(FIXED_REPO) for p in compiled))
                self.assertEqual(opened, [])

    def test_truncated_or_trailing_held_input_keeps_counts_and_refuses_before_exec(self):
        raw = b''.join((self.root / name).read_bytes() for name in (COMPONENT, OPERATOR))
        for value in (raw[:-7], raw + b'x'):
            with self.subTest(length=len(value)):
                compiled = []
                code, lines, opened = self.invoke(held_input=value, compile_effect=lambda b, p: compiled.append(p))
                self.assertEqual(code, 1)
                self.assertIn(lines[-1]['cause'], ('source_eof', 'source_trailing'))
                self.assertEqual(sum(lines[-1]['known']['source_bytes']), min(len(value), len(raw)))
                self.assertFalse(lines[-1]['known']['stdin_eof'])
                self.assertEqual(opened, [])
                self.assertFalse(any(p.startswith(FIXED_REPO) for p in compiled))

    def test_legal_short_held_pipe_reads_accumulate_without_reread_paths(self):
        code, lines, opened = self.invoke(input_chunk=997)
        self.assertEqual(code, 0)
        self.assertEqual(lines[-1]['write_facts']['source_bytes'],
                         [self.sources[COMPONENT]['size_bytes'], self.sources[OPERATOR]['size_bytes']])
        self.assertTrue(lines[-1]['write_facts']['stdin_eof'])
        self.assertEqual(len(opened), 1)

    def test_failed_held_read_preserves_confirmed_prefix_and_unknown_extent(self):
        calls = []
        def read(stream, count):
            calls.append(count)
            if len(calls) == 2: raise OSError('held_read_unknown')
            return stream.read(min(19, count))
        code, lines, opened = self.invoke(input_effect=read)
        self.assertEqual(code, 1)
        self.assertEqual(lines[-1]['cause'], 'held_read_unknown')
        self.assertEqual(lines[-1]['known']['source_bytes'], [19])
        self.assertTrue(lines[-1]['known']['stdin_extent_unknown'])
        self.assertFalse(lines[-1]['known']['stdin_eof'])
        self.assertEqual(opened, [])

    def test_failed_final_eof_read_preserves_full_prefix_and_unknown_unreturned_extent(self):
        def read(stream, count):
            if count == 1: raise OSError('held_eof_unknown')
            return stream.read(count)
        compiled = []
        code, lines, opened = self.invoke(input_effect=read,
            compile_effect=lambda raw, filename: compiled.append(filename))
        self.assertEqual(code, 1)
        self.assertEqual(lines[-1]['cause'], 'held_eof_unknown')
        known = lines[-1]['known']
        self.assertEqual(known['source_bytes'],
                         [self.sources[COMPONENT]['size_bytes'], self.sources[OPERATOR]['size_bytes']])
        self.assertEqual(known['source_sha256'],
                         [self.sources[COMPONENT]['sha256'], self.sources[OPERATOR]['sha256']])
        self.assertTrue(known['stdin_extent_unknown'])
        self.assertFalse(known['stdin_eof'])
        self.assertEqual(opened, [])
        self.assertFalse(any(p.startswith(FIXED_REPO) for p in compiled))

    def test_qualified_fsync_and_close_keep_first_secondary_and_source_receipt(self):
        def fsync(fd, path, real): raise OSError('held_fsync_first')
        closed = []
        def close(fd, path, real):
            closed.append(fd);real(fd);raise OSError('held_close_second')
        code, lines, _ = self.invoke(fsync_effect=fsync, close_effect=close)
        self.assertEqual(code, 1)
        self.assertEqual(lines[-1]['cause'], 'held_fsync_first')
        self.assertEqual(lines[-1]['known']['secondary'], ['close_failed'])
        self.assertTrue(lines[-1]['known']['unknown_closure'])
        self.assertTrue(lines[-1]['known']['stdin_eof'])
        self.assertEqual(lines[-1]['known']['written_bytes'], len(self.selected))
        self.assertEqual(len(closed), 1)

    def test_held_read_late_floor_and_original_delay_start_no_target_or_terminal(self):
        now = [100]
        def read(stream, count):
            raw = stream.read(count);now[0] += 1_000_000_000;return raw
        code, lines, opened = self.invoke(input_effect=read, clock=lambda: now[0])
        self.assertEqual((code, lines, opened), (1, [{'ready': True, 'schema_version': 1}], []))

    def test_held_prefix_does_not_promote_unreturned_write_or_terminal_failure(self):
        def write(fd, raw, real): real(fd, raw[:3]);raise OSError('held_write_unknown')
        code, lines, _ = self.invoke(write_effect=write)
        self.assertEqual(code, 1)
        self.assertTrue(lines[-1]['known']['extent_unknown'])
        self.assertEqual(lines[-1]['known']['written_bytes'], 0)
        self.assertEqual(self.target.read_bytes(), self.selected[:3])


def resume_node_tests():
    """Load the separately owned controlled core without registering its cases here."""
    import importlib.util
    path = REPO / 'tests/test_accepted_policy_fixture_compiler_gate2_resume_v1.py'
    spec = importlib.util.spec_from_file_location('_resume_node_controlled_tests', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# These inert definitions are installed once in the existing deferred P0 writer
# call. Each separately approved stage retains its actual begin/poll collection.
# The upstream-retention test fixture is a declared prerequisite, not a P0 claim.
CD_FACTORY_SOURCE = r"""var cdCore=gate2Resume;
if(Object.hasOwn(cdCore,'cd'))throw Error('cd_install_once');
var cdSaved={now:cdCore.now,track:cdCore.track,send:cdCore.send,snapshot:cdCore.snapshot,writerProof:cdCore.writerProof,decode:cdCore.decode,hash:cdCore.hash,canon:cdCore.canon,view:cdCore.view,keys:cdCore.keys,uint:cdCore.uint,sha:cdCore.sha,setupView:cdCore.setupView};
var cdSource,cdHeld,cdWriter,cdSpawn,cdHash,cdPins,cdIndex=0,cdState=null,cdStatePins,cdExternal,cdExternalSHA,cdPrepared=cdCore.last_setup;
function cdGate(s){let n=cdSaved.now();if(n>=s.end)throw Error('cd_original_deadline');return n;}
function cdRecord(v){
 if(v===null||typeof v!=='object')return false;
 let p=Object.getPrototypeOf(v);if(p!==null&&p!==Object.prototype)return false;
 for(let k of Reflect.ownKeys(v)){if(typeof k!=='string')return false;let d=Object.getOwnPropertyDescriptor(v,k);if(!d||d.enumerable!==true||!Object.hasOwn(d,'value'))return false;}return true;
}
function cdStopped(s,role,phase,error){
 let child=s[role+'_child'],f=s[role+'_failure']={cause:'cd_'+role+'_'+phase,initiating_message:String(error?.message??error).replace(/[^\x20-\x7e]/g,'?').slice(0,80),[role+'_attempted']:true,pid:Number.isSafeInteger(child?.pid)?child.pid:null,tracking_completed:false,unknown_closure:true,stdin_extent_unknown:true,stdin_error_handler_installed:false,stdin_close_attempted:false,stdin_close_returned:false,secondary:[],omitted_or_unknown:true};
 if(child){
  let note=label=>{try{if(!f.secondary.includes(label)&&f.secondary.length<9)f.secondary.push(label);}catch(e){}};
  for(let [name,emitter] of [['child',child],['stdin',child.stdin],['stdout',child.stdout],['stderr',child.stderr]])if(emitter&&typeof emitter.on==='function')try{emitter.on('error',()=>note('cd_'+role+'_'+name+'_error'));if(name==='stdin')f.stdin_error_handler_installed=true;}catch(e){note('cd_'+role+'_'+name+'_error_handler');}else if(name==='stdin')note('cd_'+role+(emitter?'_stdin_error_handler_missing':'_stdin_missing'));
  try{if(f.stdin_error_handler_installed&&child.stdin&&typeof child.stdin.end==='function'&&child.stdin.writableEnded!==true){f.stdin_close_attempted=true;child.stdin.end();f.stdin_close_returned=true;}}catch(closeError){note('cd_'+role+'_stdin_close');}
 }
 let stopped=Error(cdSaved.canon(f));stopped.facts=f;return stopped;
}
function cdAuth(){
 if(cdCore.retention_complete!==true||cdCore.setup_success!==true||cdCore.selected.sha256!==cdPins[0]||cdCore.factory_sha256!==cdPins[1]||cdCore.cd_factory_sha256!==cdPins[2]||Object.keys(cdSaved).some(k=>cdCore[k]!==cdSaved[k]))throw Error('cd_core_drift');
 for(let [i,b] of cdHeld.entries()){let d=cdSource[i][1];if(b.length!==d.size_bytes||cdCore.hash(b)!==d.sha256||cdHash('sha1').update('blob '+b.length+'\0').update(b).digest('hex')!==d.git_blob||!cdCore.held[i].equals(b))throw Error('cd_source_binding');}
}
function cdOnce(s,a,b){if(s.split(a).length!==2)throw Error('cd_writer_source');return s.replace(a,b);}
function cdWriterFor(stage){
 let s=cdOnce(cdWriter,'MAX_SELECTED_BYTES=12288','MAX_SELECTED_BYTES=4096');
 s=cdOnce(s,'ACK_CAP=24576','ACK_CAP=16384');s=cdOnce(s,'p,b,12288,gate,comp','p,b,4096,gate,comp');
 s=cdOnce(s,"allocated_bytes']<=12288","allocated_bytes']<=4096");
 return cdOnce(s,'gate2-p0-exception.outer-tool.original.json','gate2-'+stage.toLowerCase()+'.outer-tool.original.json');
}
function cdNative(s){try{
 let raw=s.snapshot.raw[0],k=cdSaved.keys,u=cdSaved.uint;
 if(!s.snapshot.facts.completed||!raw.length||raw.at(-1)!==10||!raw.every(x=>x<128))return false;
 let v=cdSaved.view(raw.subarray(0,-1).toString('ascii'));
 if(s.stage==='D'){
  if(!k(v,'stage,receipt_sha256,receipt_size_bytes,final_measurement,ledger,deadline_ns,finished_ns,control_bytes,aggregate_bytes,passed,finalization_complete,controlled,external_return_required')||v.stage!=='D'||!cdSaved.sha(v.receipt_sha256)||!u(v.receipt_size_bytes,20480n)||v.receipt_size_bytes===0n||v.passed!==true||v.finalization_complete!==true||v.controlled!==false||v.external_return_required!==true||!u(v.control_bytes,524288n)||!u(v.aggregate_bytes,2097152n)||v.aggregate_bytes<v.control_bytes||!u(v.deadline_ns)||!u(v.finished_ns)||v.finished_ns>=v.deadline_ns)return false;
  let m=v.final_measurement,l=v.ledger;return k(m,'c_free_bytes,ext4_used_bytes,project_free_bytes')&&Object.values(m).every(x=>u(x))&&m.c_free_bytes>=43620761600n&&m.project_free_bytes>=1073741824n&&k(l,'remaining_before,charge_bytes,remaining_after')&&Object.values(l).every(x=>u(x,536870912n))&&l.charge_bytes<=2097152n&&l.remaining_before-l.charge_bytes===l.remaining_after;
 }
 if(!k(v,'descriptor,write_facts,completion_deadline_ns,external_approval')||v.external_approval!==false||!u(v.completion_deadline_ns)||v.completion_deadline_ns===0n)return false;
 let d=v.descriptor,q=v.write_facts,path='/home/s-a-balashov/work/vast-fixture-compiler-gate2-465ab7986939c67ae3594344ee3b6266cd2abd7a-01/r1/outputs/'+s.stage+'/outer.invocation.original.json';
 return k(d,'path,size_bytes,sha256')&&d.path===path&&cdSaved.sha(d.sha256)&&u(d.size_bytes,8192n)&&d.size_bytes>0n&&k(q,'path,open_completed,written_bytes,write_extent_unknown,flush_completed,fsync_completed,close_completed,directory_persisted,complete,deadline_failed,failure_causes')&&q.path===path&&q.written_bytes===d.size_bytes&&['open_completed','flush_completed','fsync_completed','close_completed','directory_persisted','complete'].every(k=>q[k]===true)&&q.write_extent_unknown===false&&q.deadline_failed===false&&Array.isArray(q.failure_causes)&&q.failure_causes.length===0;
}catch(e){return false;}}
cdCore.cd={
 begin:async(stage,args,selectedSHA,coreSHA,factorySHA,external)=>{
  let started=cdSaved.now(),pins=[selectedSHA,coreSHA,factorySHA];
  if(pins.some(v=>typeof v!=='string'||!/^[0-9a-f]{64}$/.test(v))||cdCore.retention_complete!==true||cdCore.setup_success!==true||cdCore.selected.sha256!==selectedSHA||cdCore.factory_sha256!==coreSHA||cdCore.cd_factory_sha256!==factorySHA)throw Error('cd_prior_retention');
  if(!['C1','C2','C3','C4','C5','C6','D'].includes(stage)||stage!==['C1','C2','C3','C4','C5','C6','D'][cdIndex]||cdState&&(!cdState.nativeSuccess||!cdState.retained))throw Error('cd_stage_order');
  let s=cdState={stage,start:started,end:started+(stage==='D'?10000:150000),calls:0,retained:false,nativeSuccess:false};
  cdGate(s);
  if(!Array.isArray(args)||args.length!==4||args.some(x=>typeof x!=='string')||!/^[0-9a-f]{40}$/.test(args[0])||!/^[1-9][0-9]{0,4}$/.test(args[1])||+args[1]>32768||!/^[0-9a-f]{64}$/.test(args[2]))throw Error('cd_arguments');
  let prior=args[3]==='-'?[]:args[3].split(',');
  if(prior.length!==cdIndex||prior.some(x=>!/^[1-9][0-9]{0,3}:[0-9a-f]{64}$/.test(x)||+x.split(':')[0]>8192))throw Error('cd_completions');
  if(cdIndex&&cdCore.canon(args.slice(0,3))!==cdCore.canon(cdStatePins))throw Error('cd_packet_drift');
  if(!cdIndex)cdStatePins=args.slice(0,3);
  if(Object.keys(cdSaved).some(k=>cdCore[k]!==cdSaved[k])||cdCore.last_setup!==cdPrepared)throw Error('cd_core_drift');
  if(!cdIndex){
   if(!cdRecord(external))throw Error('cd_external_delivery');
   let k=cdSaved.keys,h=cdSaved.hash,c=cdSaved.canon,sha=cdSaved.sha,r=external.receipt,a=external.approval;
   if(!cdRecord(r)||!cdRecord(a))throw Error('cd_external_delivery');
   if(!k(external,'receipt,approval')||!k(r,'version,context_sha256,record_size_bytes,record_sha256,executor_call_sha256,max_output_tokens,terminal,tool_reference')||r.version!==1||!Number.isSafeInteger(r.record_size_bytes)||r.record_size_bytes<1||r.record_size_bytes>65536||!sha(r.record_sha256)||!sha(r.executor_call_sha256)||r.max_output_tokens!==100000||r.terminal!=='complete_untruncated'||typeof r.tool_reference!=='string'||!/^[\x20-\x7e]{1,96}$/.test(r.tool_reference)||r.context_sha256!==h(c(['vast.gate2.external-delivery.v1',args[0],Number(args[1]),args[2],...pins]))||!k(a,'reference,body_sha256,receipt_sha256')||typeof a.reference!=='string'||a.reference.length>96||!/^https:\/\/github\.com\/lordcoudy\/VAST\/pull\/9#issuecomment-[1-9][0-9]*$/.test(a.reference)||!sha(a.body_sha256)||a.receipt_sha256!==h(c(r)))throw Error('cd_external_delivery');
   let prepared=cdSaved.setupView(cdPrepared);if(prepared.code_commit!==args[0]||prepared.packet.size_bytes!==BigInt(args[1])||prepared.packet.sha256!==args[2])throw Error('cd_prepared_packet');
   cdExternal=c(external);cdExternalSHA=h(cdExternal);
  }else if(typeof external!=='string'||!/^[0-9a-f]{64}$/.test(external)||external!==cdExternalSHA)throw Error('cd_external_delivery');
  if(!cdSource){cdPins=pins;
   ({spawn:cdSpawn}=await import('node:child_process'));cdGate(s);({createHash:cdHash}=await import('node:crypto'));cdGate(s);
   cdSource=cdCore.sources.map(r=>[r[0],{...r[1]}]);cdHeld=cdCore.held.map(b=>Buffer.from(b));cdWriter=cdCore.writer;
  }
  if(cdCore.canon(pins)!==cdCore.canon(cdPins))throw Error('cd_core_drift');cdAuth();cdGate(s);
  let source=cdHeld[1].toString('utf8'),match=source.match(/NATIVE_BOOTSTRAP\s*=\s*r'''([\s\S]*?)'''/);
  if(!match||Buffer.byteLength(match[1])>2048)throw Error('cd_bootstrap');
  let header=Buffer.from(cdCore.canon({current:{[cdSource[1][0].split('/VAST/')[1]]:cdSource[1][1]}})+'\n');
  cdGate(s);let nativePhase='spawn';s.native_attempted=true;
  try{s.native_child=cdSpawn('C:/Windows/System32/wsl.exe',['-d','Ubuntu','-u','s-a-balashov','--cd','/','--exec','/usr/bin/python3','-I','-S','-B','-c',match[1],stage,...args],{cwd:'C:/',stdio:['pipe','pipe','pipe'],windowsHide:true});nativePhase='track';cdGate(s);
   s.child=cdCore.track(s.native_child,[2048,768],s.end);
  }catch(error){throw cdStopped(s,'native',nativePhase,error);}
  cdGate(s);cdCore.send(s.child,header);cdGate(s);return cdCore.cd.poll(1000);
 },
 poll:async(cap=30000)=>{
  let s=cdState;cdGate(s);if(s.final||!Number.isSafeInteger(cap)||cap<1||cap>30000||++s.calls>6)throw Error('cd_poll_state');
  if(!s.child.closed&&!s.child.causes.length)await new Promise(done=>{let timer=setTimeout(done,Math.min(cap,s.end-cdCore.now()));s.child.wake=()=>{clearTimeout(timer);done();};});
  let now=cdCore.now();cdGate(s);
  if(!s.child.closed&&!s.child.causes.length&&s.calls<6){nodeRepl.write(JSON.stringify([0,s.stage,s.child.pid,s.child.returncode]));return;}
  s.final=true;s.snapshot=cdCore.snapshot(s.child,2,[s.start,s.end],now,s.end);s.nativeSuccess=cdNative(s);
  nodeRepl.write(s.snapshot.text);
 },
 finish:async selected=>{
  let s=cdState;if(!s||!s.final||s.writer_attempted)throw Error('cd_writer_once');s.writer_attempted=true;cdGate(s);cdAuth();
  if(typeof selected!=='string'||selected.length<1||selected.length>4096||/[^\x00-\x7f]/.test(selected))throw Error('cd_selected_bound');
  let x=JSON.parse(selected);if(cdCore.canon(x)!==selected||!x.call||x.call.tool!=='mcp__node_repl__js'||x.call.timeout_ms!==32000||!Array.isArray(x.call.codes)||!Array.isArray(x.frames)||x.frames.length!==s.calls||x.frames.length>6||x.call.codes.length!==x.frames.length||x.call.codes.some(v=>typeof v!=='string')||x.frames.at(-1)?.content?.[0]?.text!==s.snapshot.text)throw Error('cd_selected_binding');
  if(x.frames.some((r,i)=>r?.isError!==false||!Array.isArray(r.content)||r.content.length!==1||r.content[0]?.type!=='text'||typeof r.content[0]?.text!=='string'||i<x.frames.length-1&&!r.content[0].text.startsWith('[0,')))throw Error('cd_selected_provider');
  let b=Buffer.from(selected,'ascii');s.selected={size_bytes:b.length,sha256:cdCore.hash(b),selected_base64:b.toString('base64')};
  let program=cdWriterFor(s.stage),sent=false;cdGate(s);
  let writerPhase='spawn';
  try{
  s.writer_child=cdSpawn('C:/Python314/python.exe',['-I','-S','-B','-c',program,cdCore.canon(cdSource.map(r=>r[1]))],{cwd:'C:/',stdio:['pipe','pipe','pipe'],windowsHide:true});writerPhase='track';cdGate(s);
  s.writer=cdCore.track(s.writer_child,[2112,2112],s.end,(state,i,row)=>{
   if(i!==0||sent)return;let line=Buffer.concat(row.raw).toString('latin1');if(line.length>64)throw Error('cd_writer_ready');if(!line.endsWith('\n'))return;
   if(line!=='{"ready":true,"schema_version":1}\n')throw Error('cd_writer_ready');cdGate(s);let remaining=Math.floor(s.end-cdCore.now());if(remaining<1||remaining>150000)throw Error('cd_writer_remaining');
   sent=true;state.ack_ms=remaining;cdCore.send(state,Buffer.concat([Buffer.from(cdCore.canon({remaining_ms:remaining,...s.selected})+'\n'),...cdHeld]));
  });
  }catch(error){throw cdStopped(s,'writer',writerPhase,error);}
  if(!s.writer.closed&&!s.writer.causes.length)await new Promise(done=>{let timer=setTimeout(done,s.end-cdCore.now());s.writer.wake=()=>{clearTimeout(timer);done();};});
  let now=cdCore.now();cdGate(s);s.writerSnapshot=cdCore.snapshot(s.writer,2,[s.start,s.end],now,s.end);nodeRepl.write(s.writerSnapshot.text);
 },
 verifyReturn:delivered=>{
  let s=cdState;cdGate(s);cdAuth();if(s.retained)throw Error('cd_verify_once');cdSaved.writerProof(delivered,s.writerSnapshot,s.selected,s.writer,4096,16384);let after=cdGate(s);
  s.retained=true;if(s.nativeSuccess)cdIndex++;nodeRepl.write(JSON.stringify([3,s.stage,after,s.end,s.nativeSuccess,true,s.selected.sha256]));
 }
};"""

# Kept as an explicit alias for the historical RED34 carrier measurement only.
CD_EXTENSION = CD_FACTORY_SOURCE

CD_HARNESS = r"""const vm=require('node:vm'),{EventEmitter}=require('node:events'),crypto=require('node:crypto'),zlib=require('node:zlib');
const test=JSON.parse(require('node:fs').readFileSync(0,'utf8'));let clock=200000,clockReads=0,spawned=[],attempts=[],timers=[],writes=[],reads=[],sent=[],killed=0,imports=[],activeStep=null,stepReads=0,verifySamples=[];
class Pipe extends EventEmitter{
 constructor(){super();this.raw=Buffer.alloc(0);}
 read(n){reads.push(n);if(!this.raw.length)return null;let b=this.raw.subarray(0,n);this.raw=this.raw.subarray(b.length);return b;}
 feed(b){this.raw=Buffer.concat([this.raw,Buffer.from(b)]);this.emit('readable');}
 end(){this.emit('end');this.emit('close');}
}
function child(file,args,options){attempts.push({file,args,options});if(file==='C:/Python314/python.exe'&&test.writer_spawn_throw)throw Error('controlled_writer_spawn');let p=new EventEmitter();p.pid=4294967295-spawned.length;p.stdout=new Pipe();p.stderr=new Pipe();p.stdin=new EventEmitter();let fallback=file==='C:/Python314/python.exe'&&test.writer_track_throw||file.endsWith('wsl.exe')&&test.native_track_throw;p.stdin.end=b=>{sent.push(Buffer.from(b||'').toString('base64'));if(test.fallback_stdin_fault&&fallback)queueMicrotask(()=>p.stdin.emit('error',Error('controlled_unhandled_EPIPE')));if(test.fallback_emit_errors&&fallback)queueMicrotask(()=>{for(let [label,emitter] of [['child',p],['stdin',p.stdin],['stdout',p.stdout],['stderr',p.stderr]])for(let i=0;i<2;i++)emitter.emit('error',Error('controlled_'+label));});if(file==='C:/Python314/python.exe'&&test.writer_close_throw||file.endsWith('wsl.exe')&&test.native_close_throw)throw Error('controlled_stdin_close');if(test.stdin_error)p.stdin.emit('error',Error('controlled'));p.stdin.emit('finish');p.stdin.emit('close');};if(fallback&&test.fallback_stdin_fault==='missing')p.stdin=undefined;else if(fallback&&test.fallback_stdin_fault==='missing_on')p.stdin.on=undefined;else if(fallback&&test.fallback_stdin_fault==='throwing_on')p.stdin.on=()=>{throw Error('controlled_stdin_listener');};if(file==='C:/Python314/python.exe'&&test.writer_track_throw)p.once=()=>{throw Error('controlled_writer_track');};if(file.endsWith('wsl.exe')&&test.native_track_throw)p.once=()=>{throw Error('controlled_native_track');};p.kill=()=>{killed++;throw Error('kill_forbidden');};spawned.push({file,args,options,p});return p;}
const context=vm.createContext({Buffer,console,performance:{now:()=>{clockReads++;if(activeStep?.capture_clock){stepReads++;if(stepReads>=activeStep.clock_after_reads)clock=activeStep.clock_value;verifySamples.push(clock);}return clock;}},nodeRepl:{write:x=>writes.push(String(x))},setTimeout:(f,n)=>{let t={f,n};timers.push(t);return t;},clearTimeout:t=>t.off=true},test.code_generation_disabled===true?{codeGeneration:{strings:false,wasm:false}}:{});
const importModuleDynamically=async name=>{imports.push(name);let values=name==='node:crypto'?crypto:name==='node:perf_hooks'?{performance:{now:()=>clock}}:name==='node:zlib'?{...zlib,brotliDecompressSync:b=>{clock+=test.decode_delay||0;return zlib.brotliDecompressSync(b);}}:name==='node:fs/promises'?{}:name==='node:child_process'?(clock+=test.import_delay||0,{spawn:child}):null;if(!values)throw Error('unknown_import');let m=new vm.SyntheticModule(Object.keys(values),function(){for(let k of Object.keys(values))this.setExport(k,values[k]);},{context});await m.link(()=>{});await m.evaluate();return m;};
async function evaluate(code,action){let last=spawned.length,settled=false,error=null,promise=vm.runInContext('(async()=>{var g2=globalThis.gate2Resume;'+code+'})()',context,{importModuleDynamically});promise.then(()=>settled=true,e=>{settled=true;error=String(e.message);});
 for(let i=0;i<5000&&!settled&&spawned.length===last;i++)await Promise.resolve();for(let i=0;i<100;i++)await Promise.resolve();let p=spawned.at(-1)?.p;
 if(p&&(action==='normal'||action==='failure'||action==='unknown'||action==='overflow'||action==='late')){
  if(action==='late')clock+=150000;
  p.stdout.feed(action==='overflow'?'x'.repeat(3000):test.output||'{}\n');
  if(action==='failure')p.stderr.feed(test.stderr||'{"cause":"controlled"}\n');
  p.stdout.end();p.stderr.end();if(action!=='unknown')p.emit('exit',action==='failure'?1:0,null);p.emit('close');
 }
 if(action==='writer'){
  p.stdout.feed(test.writer_ready?Buffer.from(test.writer_ready,'base64'):'{"ready":true,"schema_version":1}\n');for(let i=0;i<100;i++)await Promise.resolve();
  if(Buffer.from(sent.at(-1),'base64').length===0){p.stdout.end();p.stderr.end();p.emit('exit',1,null);p.emit('close');await promise;return error;}
  let raw=Buffer.from(sent.at(-1),'base64'),a=JSON.parse(raw.subarray(0,raw.indexOf(10))),round=Math.ceil(a.size_bytes/4096)*4096;
  let f={stdin_eof:true,stdin_extent_unknown:false,source_bytes:test.sources.map(r=>Buffer.from(r[1],'base64').length),source_sha256:test.sources.map(r=>crypto.createHash('sha256').update(Buffer.from(r[1],'base64')).digest('hex')),open_completed:true,written_bytes:a.size_bytes,extent_unknown:false,fsync_completed:true,close_completed:true,allocated_bytes:round,completed:true,sha256:a.sha256,unknown_closure:false};
  let v={completed:true,external_terminal_required:true,size_bytes:a.size_bytes,sha256:a.sha256,write_facts:f,deadline_ns:1755772592209100+a.remaining_ms*1000000,all_forms_quote_bytes:round*2+8192};
  if(test.writer_fault==='extent')f.extent_unknown=true;if(test.writer_fault==='source')f.source_sha256[1]='0'.repeat(64);
  const canon=x=>Array.isArray(x)?'['+x.map(canon).join(',')+']':x&&typeof x==='object'?'{'+Object.keys(x).sort().map(k=>JSON.stringify(k)+':'+canon(x[k])).join(',')+'}':JSON.stringify(x);
  p.stdout.feed(canon(v)+'\n');p.stdout.end();p.stderr.end();p.emit('exit',0,null);p.emit('close');
 }
 for(let i=0;i<100;i++)await Promise.resolve();for(let t of timers.splice(0))if(!t.off){clock+=t.n;t.f();}
 await promise;return error;
}
(async()=>{let error=null,error_name=null;try{
 await evaluate(test.core,'none');
 let before=[clockReads,imports.length,spawned.length,sent.length];
 context.fixtureSetup=test.setup_output;
 await evaluate("g2.last_setup={facts:{completed:true,unknown_closure:false,ack_ms:150000},raw:[Buffer.from(fixtureSetup),Buffer.alloc(0),Buffer.from('1755772592209100\\n')]};",'none');
 context.factorySHA=crypto.createHash('sha256').update(test.factory).digest('hex');
 await evaluate('g2.cd_factory_sha256=factorySHA;'+test.factory,'none');
 context.inertInstall=[before,[clockReads,imports.length,spawned.length,sent.length]];
 context.fixtureSources=test.sources;context.fixtureWriter=test.writer;
 await evaluate("g2.held=fixtureSources.map(r=>Buffer.from(r[1],'base64'));g2.writer=fixtureWriter;g2.retention_complete="+(test.prior_missing?'false':'true')+";g2.setup_success="+(test.setup_failed?'false':'true')+";g2.selected={sha256:'a'.repeat(64)};g2.factory_sha256='b'.repeat(64);",'none');
 if(test.source_tamper)await evaluate('g2.held[1][0]^=1;','none');
 await evaluate(test.code,test.action||'normal');
 for(let step of test.steps||[]){activeStep=step;stepReads=0;if(step.clock!==undefined)clock=step.clock;if(step.output!==undefined)test.output=step.output;if(step.stderr!==undefined)test.stderr=step.stderr;let code=step.code.replaceAll('__DELIVERED__',JSON.stringify(writes.at(-1)));await evaluate(code,step.action||'none');activeStep=null;}
 }catch(e){error=String(e.message);error_name=String(e.name);}
 console.log(JSON.stringify({error,error_name,writes,clock,killed,reads,sent,attempts,imports,verifySamples,inertInstall:context.inertInstall,spawned:spawned.map(({file,args,options})=>({file,args,options}))}));})().catch(e=>{console.error(e);process.exitCode=1;});"""


class LaterStageCallerTests(unittest.TestCase):
    FINISH = ("var last=__DELIVERED__;await g2.cd.finish(g2.canon({call:{tool:'mcp__node_repl__js',"
              "timeout_ms:32000,codes:['controlled actual call']},frames:[{content:[{type:'text',text:last}],isError:false}]}));")
    def node(self, *, action='normal', steps=(), code=None, **extra):
        import shutil, subprocess
        module = resume_node_tests()
        fixture = module.ResumeNodeCaller('runTest')
        core = fixture.code().split('var g2options=', 1)[0]
        core += "\nvar {brotliDecompressSync:g2d}=await import('node:zlib');\n" + module.NODE_WRITER_VALIDATORS
        core += "\ng2.commit='"+'c'*40+"';\n"
        setup=json.loads(fixture.success_output())
        setup['code_commit']='c'*40
        setup['packet'].update(size_bytes=32768,sha256='d'*64)
        values = dict(core=core, factory=CD_FACTORY_SOURCE, code=code or self.initial_code(), action=action,
                      steps=list(steps), writer=WRITER_SOURCE, output=self.native_outputs('C1')[1][1].decode('ascii'),
                      setup_output=canonical(setup).decode('ascii')+'\n',
                      sources=[[FIXED_REPO + name, base64.b64encode((REPO / name).read_bytes()).decode()]
                               for name in (COMPONENT, OPERATOR)])
        values.update(extra)
        result = subprocess.run([shutil.which('node') or shutil.which('node.exe'),
            '--experimental-vm-modules', '--no-warnings', '-e', CD_HARNESS],
            input=canonical(values), capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        return json.loads(result.stdout)

    def initial_code(self, args=None):
        args = args or ['c' * 40, '32768', 'd' * 64, '-']
        return self.begin_code('C1', args)

    def external(self,args):
        pins = ['a'*64, 'b'*64, hashlib.sha256(CD_FACTORY_SOURCE.encode()).hexdigest()]
        receipt={'version':1,'context_sha256':hashlib.sha256(canonical(
            ['vast.gate2.external-delivery.v1',args[0],int(args[1]),args[2],*pins])).hexdigest(),
            'record_size_bytes':65536,'record_sha256':'e'*64,'executor_call_sha256':'f'*64,
            'max_output_tokens':100000,'terminal':'complete_untruncated','tool_reference':'\\'*96}
        digest=hashlib.sha256(canonical(receipt)).hexdigest()
        approval_body={'version':1,'kind':'vast_gate2_external_delivery_approval_v1','receipt_sha256':digest,
            'context_sha256':receipt['context_sha256'],'code_commit':args[0],'packet_size_bytes':int(args[1]),
            'packet_sha256':args[2],'selected_sha256':pins[0],'core_sha256':pins[1],
            'factory_sha256':pins[2],'decision':'approved_for_C1'}
        prefix='https://github.com/lordcoudy/VAST/pull/9#issuecomment-'
        return {'receipt':receipt,'approval':{'reference':prefix+'9'*(96-len(prefix)),
            'body_sha256':hashlib.sha256(canonical(approval_body)).hexdigest(),'receipt_sha256':digest}}

    def begin_code(self, stage, args, external=Ellipsis):
        pins = ['a'*64, 'b'*64, hashlib.sha256(CD_FACTORY_SOURCE.encode()).hexdigest()]
        if external is Ellipsis:
            external=self.external(args)
            if stage!='C1':external=hashlib.sha256(canonical(external)).hexdigest()
        return 'await gate2Resume.cd.begin('+','.join(canonical(v).decode() for v in [stage,args,*pins,external])+');'

    def carrier_code(self):
        import shutil, subprocess
        raw = CD_EXTENSION.encode('ascii')
        program = ("const z=require('node:zlib'),b=require('node:fs').readFileSync(0),"
                   "p=z.brotliCompressSync(b,{params:{[z.constants.BROTLI_PARAM_QUALITY]:11}});"
                   "if(!z.brotliDecompressSync(p).equals(b))throw Error('carrier_roundtrip');"
                   "console.log(p.toString('base64'));_")[:-1]
        packed = subprocess.run([shutil.which('node') or shutil.which('node.exe'), '-e', program],
                                input=raw, capture_output=True, check=True).stdout.decode().strip()
        return ("var {brotliDecompressSync:cdDecode}=await import('node:zlib');"
            "var cdBytes=cdDecode(Buffer.from('" + packed + "','base64'),{maxOutputLength:32768});"
            "if(cdBytes.length!==" + str(len(raw)) + "||gate2Resume.hash(cdBytes)!=='" +
            hashlib.sha256(raw).hexdigest() + "')throw Error('cd_carrier_binding');"
            "await eval('(async()=>{'+cdBytes.toString('ascii')+'})()');")

    def facts(self, text):
        module = resume_node_tests()
        row = json.loads(text.split('\n', 1)[0])
        value = dict(zip(module.NODE_FIELDS, row[1:]))
        value['pipes'] = [dict(zip(module.NODE_PIPE_FIELDS, item)) for item in value['pipes']]
        return value

    def test_restricted_harness_denies_unchanged_extension_carrier(self):
        value=self.node(code=self.carrier_code(),action='none',code_generation_disabled=True)
        self.assertEqual(value['error'],'Code generation from strings disallowed for this context')
        self.assertEqual(value['error_name'],'EvalError')
        self.assertFalse(value['spawned'])
        self.assertFalse(value['sent'])
        self.assertFalse(value['writes'])

    def test_restricted_harness_static_factory_is_inert_and_keeps_stage_predicates(self):
        inert=self.node(code='void 0;',action='none',prior_missing=True,code_generation_disabled=True)
        self.assertIsNone(inert['error'])
        self.assertEqual(inert['inertInstall'][0],inert['inertInstall'][1])
        self.assertFalse(inert['spawned'])
        self.assertFalse(inert['writes'])
        value=self.node(code_generation_disabled=True)
        self.assertIsNone(value['error'])
        self.assertEqual(len(value['spawned']),1)
        self.assertEqual(value['killed'],0)
        facts=self.facts(value['writes'][-1])
        self.assertEqual(facts['clock'],[200000,350000])
        self.assertTrue(facts['completed'])
        self.assertFalse(facts['unknown_closure'])
        self.assertEqual(value['spawned'][0]['args'][-5:],['C1','c'*40,'32768','d'*64,'-'])

    def test_extension_installs_only_after_retention_and_binds_the_exact_core(self):
        code = self.initial_code().replace('b'*64, 'e'*64, 1)
        refused = self.node(code=code)
        self.assertEqual(refused['error'], 'cd_prior_retention')
        self.assertFalse(refused['spawned'])
        repeated = self.node(steps=[{'code': CD_FACTORY_SOURCE}])
        self.assertEqual(repeated['error'], 'cd_install_once')
        self.assertEqual(len(repeated['spawned']), 1)

    def test_c1_requires_typed_external_receipt_and_approval_before_stage_import_or_spawn(self):
        args=['c'*40,'32768','d'*64,'-']
        good=self.external(args)
        invalid=[('missing',None),('flags_only',{'delivered':True,'approved':True})]
        for section,key,value in (
            ('receipt','version',True),('receipt','version',1.5),
            ('receipt','record_size_bytes',0),('receipt','record_size_bytes',65537),
            ('receipt','record_size_bytes',True),('receipt','record_size_bytes',1.5),
            ('receipt','max_output_tokens',99999),('receipt','max_output_tokens',True),
            ('receipt','terminal','complete'),('receipt','tool_reference',''),
            ('receipt','tool_reference','x'*97),('receipt','tool_reference','\u00e9'),
            ('receipt','context_sha256','0'*64),('receipt','record_sha256','x'*64),
            ('receipt','executor_call_sha256','f'*63),
            ('approval','reference','https://github.com/lordcoudy/VAST/pull/8#issuecomment-1'),
            ('approval','reference','https://github.com/lordcoudy/VAST/pull/9#issuecomment-'),
            ('approval','reference','x'*97),('approval','body_sha256',True),
            ('approval','body_sha256','a'*63),('approval','receipt_sha256','0'*64)):
            bad=json.loads(canonical(good));bad[section][key]=value
            if section=='receipt':bad['approval']['receipt_sha256']=hashlib.sha256(canonical(bad['receipt'])).hexdigest()
            invalid.append((section+'.'+key,bad))
        for section in ('receipt','approval'):
            bad=json.loads(canonical(good));bad[section]['extra']=False
            bad['approval']['receipt_sha256']=hashlib.sha256(canonical(bad['receipt'])).hexdigest()
            invalid.append((section+'.extra',bad))
            bad=json.loads(canonical(good));del bad[section][next(iter(bad[section]))]
            bad['approval']['receipt_sha256']=hashlib.sha256(canonical(bad['receipt'])).hexdigest()
            invalid.append((section+'.missing',bad))
        bad=json.loads(canonical(good));bad['extra']=False;invalid.append(('external.extra',bad))
        for label,external in invalid:
            with self.subTest(case=label):
                code=self.begin_code('C1',args,external)
                if label=='missing':code=code.rsplit(',null',1)[0]+');'
                value=self.node(code=code,action='none')
                self.assertEqual(value['error'],'cd_external_delivery')
                self.assertFalse(value['spawned'])
                self.assertEqual(len(value['imports']),value['inertInstall'][1][1])

    def test_c1_external_context_and_actual_saved_setup_packet_are_both_required(self):
        args=['c'*40,'32768','d'*64,'-']
        fixture=resume_node_tests().ResumeNodeCaller('runTest')
        for kind in ('commit','size','sha','saved_function','snapshot'):
            with self.subTest(kind=kind):
                setup=json.loads(fixture.success_output());setup['code_commit']='c'*40
                setup['packet'].update(size_bytes=32768,sha256='d'*64)
                if kind=='commit':setup['code_commit']='e'*40
                elif kind=='size':setup['packet']['size_bytes']=32767
                elif kind=='sha':setup['packet']['sha256']='e'*64
                code=self.begin_code('C1',args)
                if kind=='saved_function':code='g2.setupView=()=>{throw Error("untrusted replacement");};'+code
                elif kind=='snapshot':code='g2.last_setup={...g2.last_setup};'+code
                value=self.node(code=code,action='none',setup_output=canonical(setup).decode('ascii')+'\n')
                self.assertIn(value['error'],('cd_prepared_packet','setup_schema','cd_core_drift'))
                self.assertFalse(value['spawned'])
                self.assertEqual(len(value['imports']),value['inertInstall'][1][1])

    def test_later_stage_requires_exact_frozen_external_hash_without_replacement(self):
        args=['c'*40,'32768','d'*64,'8192:'+'e'*64]
        for replacement in (None,'0'*64,self.external(args),True):
            with self.subTest(replacement=replacement):
                code=self.begin_code('C2',args,replacement)
                if replacement is None:code=code.rsplit(',null',1)[0]+');'
                value=self.node(steps=[{'code':self.FINISH,'action':'writer'},
                    {'code':'g2.cd.verifyReturn(__DELIVERED__);'},{'code':code}])
                self.assertEqual(value['error'],'cd_external_delivery')
                self.assertEqual(len(value['spawned']),2)

    def test_valid_external_is_canonically_frozen_and_later_uses_only_its_hash(self):
        args=['c'*40,'32768','d'*64,'-'];external=self.external(args)
        initial=self.begin_code('C1',args,external).replace(canonical(external).decode(),'delivery')
        initial='let delivery='+canonical(external).decode()+';'+initial+'delivery.receipt.record_sha256="0".repeat(64);'
        next_args=[*args[:3],'8192:'+'e'*64]
        value=self.node(code=initial,steps=[{'code':self.FINISH,'action':'writer'},
            {'code':'g2.cd.verifyReturn(__DELIVERED__);'},
            {'code':self.begin_code('C2',next_args),'action':'normal'}])
        self.assertIsNone(value['error'])
        self.assertEqual(len(value['spawned']),3)

    def observe_delivery_record(self,transform):
        args=['c'*40,'32768','d'*64,'-']
        external=self.external(args)
        text=canonical(external).decode('ascii')
        begin=self.begin_code('C1',args,external).replace(text,'delivery')
        code=('let delivery='+text+',getter_reads=0;'+transform+
              'let admission_error=null;try{'+begin+'}catch(e){admission_error=String(e.message);}'
              'nodeRepl.write(JSON.stringify({admission_error,getter_reads}));')
        value=self.node(code=code,action='normal')
        self.assertIsNone(value['error'])
        return value,json.loads(value['writes'][-1])

    def assert_delivery_record_denied(self,transform):
        value,result=self.observe_delivery_record(transform)
        self.assertEqual(result['admission_error'],'cd_external_delivery')
        self.assertEqual(result['getter_reads'],0)
        self.assertFalse(value['spawned'])
        self.assertEqual(len(value['imports']),value['inertInstall'][1][1])

    def test_delivery_boxed_and_custom_prototypes_refuse_before_fields_imports_or_spawn(self):
        for record in ('delivery','delivery.receipt','delivery.approval'):
            for kind in ('boxed','custom'):
                with self.subTest(record=record,kind=kind):
                    transform=(record+'=Object.assign(new String(""),'+record+');' if kind=='boxed'
                        else 'Object.setPrototypeOf('+record+',{unrequested:true});')
                    self.assert_delivery_record_denied(transform)

    def test_delivery_accessors_hidden_properties_and_symbols_refuse_without_getters(self):
        for record,key in (('delivery','receipt'),('delivery.receipt','record_sha256'),('delivery.approval','body_sha256')):
            for kind in ('accessor','nonenumerable','symbol'):
                with self.subTest(record=record,kind=kind):
                    if kind=='accessor':
                        transform=('let saved='+record+'['+json.dumps(key)+'];Object.defineProperty('+record+','+
                            json.dumps(key)+',{enumerable:true,configurable:true,get(){getter_reads++;return saved;}});')
                    elif kind=='nonenumerable':transform='Object.defineProperty('+record+',"hidden",{value:true,enumerable:false});'
                    else:transform=record+'[Symbol("hidden")]=true;'
                    self.assert_delivery_record_denied(transform)

    def test_delivery_plain_and_null_prototype_data_records_remain_valid(self):
        for records in ((),('delivery',),('delivery.receipt',),('delivery.approval',),
                        ('delivery','delivery.receipt','delivery.approval')):
            with self.subTest(records=records):
                value,result=self.observe_delivery_record(''.join('Object.setPrototypeOf('+record+',null);' for record in records))
                self.assertIsNone(result['admission_error'])
                self.assertEqual(result['getter_reads'],0)
                self.assertEqual(len(value['spawned']),1)
                self.assertEqual(value['killed'],0)

    def test_extension_owns_fixed_stage_clocks_and_never_uses_setup_phase_helpers(self):
        code = ("gate2Resume.wait=gate2Resume.output=gate2Resume.finish=()=>{throw Error('setup_helper');};"
                + self.initial_code())
        value = self.node(code=code)
        self.assertIsNone(value['error'])
        self.assertEqual(self.facts(value['writes'][-1])['clock'], [200000, 350000])

    def test_extension_has_a_separate_four_kibibyte_writer_and_six_frame_limit(self):
        steps = [{'code': 'await g2.cd.poll(1);'} for _ in range(6)]
        value = self.node(action='none', steps=steps)
        self.assertEqual(value['error'], 'cd_poll_state')
        self.assertEqual(len(value['writes']), 6)
        self.assertFalse(self.facts(value['writes'][-1])['completed'])
        self.assertEqual(len(value['spawned']), 1)

    def test_actual_core_new_stage_begins_after_expired_setup_with_own_absolute_clock(self):
        value = self.node(output='{"native":"controlled"}\n')
        self.assertIsNone(value['error'])
        facts = self.facts(value['writes'][-1])
        self.assertEqual(facts['clock'], [200000, 350000])
        self.assertTrue(facts['completed'])
        self.assertFalse(facts['unknown_closure'])
        self.assertEqual(facts['pid'], 4294967295)
        self.assertEqual(value['killed'], 0)
        self.assertEqual(len(value['spawned']), 1)
        call = value['spawned'][0]
        self.assertEqual(call['file'], 'C:/Windows/System32/wsl.exe')
        self.assertEqual(call['args'][:12], ['-d', 'Ubuntu', '-u', 's-a-balashov', '--cd', '/',
                                          '--exec', '/usr/bin/python3', '-I', '-S', '-B', '-c'])
        self.assertEqual(call['args'][-5:], ['C1', 'c' * 40, '32768', 'd' * 64, '-'])
        header = json.loads(base64.b64decode(value['sent'][0]))
        self.assertEqual(set(header['current']), {OPERATOR})

    def test_missing_prior_or_changed_held_source_refuses_before_spawn(self):
        for kwargs, cause in (({'prior_missing': True}, 'cd_prior_retention'),
                              ({'setup_failed': True}, 'cd_prior_retention'),
                              ({'source_tamper': True}, 'cd_source_binding')):
            with self.subTest(cause=cause):
                value = self.node(**kwargs)
                self.assertEqual(value['error'], cause)
                self.assertEqual(value['spawned'], [])

    def test_unknown_or_nonzero_or_overflow_cannot_be_success(self):
        for action in ('unknown', 'failure', 'overflow'):
            with self.subTest(action=action):
                value = self.node(action=action)
                self.assertIsNone(value['error'])
                facts = self.facts(value['writes'][-1])
                self.assertFalse(facts['completed'])
                if action == 'unknown':
                    self.assertIsNone(facts['returncode'])
                    self.assertTrue(facts['unknown_closure'])
                if action == 'overflow':
                    self.assertEqual(facts['pipes'][0]['bytes'], 2049)
                    self.assertTrue(facts['pipes'][0]['remainder_unknown'])

    def test_original_clock_expiry_refuses_without_writer_or_reexecution(self):
        value = self.node(action='late')
        self.assertEqual(value['error'], 'cd_original_deadline')
        self.assertEqual(len(value['spawned']), 1)
        self.assertEqual(value['writes'], [])
        self.assertEqual(value['killed'], 0)

    def test_closed_argv_and_c1_prior_minus_reject_before_native_spawn(self):
        for args in (['c'*40, '32769', 'd'*64, '-'], ['c'*40, '1', 'd'*64, '8192:'+'e'*64],
                     ['c'*40, '1', 'd'*64, '-', 'extra']):
            with self.subTest(args=args):
                value = self.node(code=self.initial_code(args))
                self.assertIn(value['error'], ('cd_arguments', 'cd_completions'))
                self.assertFalse(value['spawned'])

    def test_selected_overbound_refuses_before_windows_writer_spawn(self):
        value = self.node(steps=[{'code': "await g2.cd.finish('x'.repeat(4097));"}])
        self.assertEqual(value['error'], 'cd_selected_bound')
        self.assertEqual(len(value['spawned']), 1)

    def test_provider_error_or_unknown_content_cannot_start_writer_or_advance(self):
        for old,new in (("isError:false", "isError:true"),
                        ("type:'text'", "type:'unknown'")):
            with self.subTest(change=new):
                value = self.node(steps=[{'code':self.FINISH.replace(old,new)}])
                self.assertEqual(value['error'],'cd_selected_provider')
                self.assertEqual(len(value['spawned']),1)

    def test_writer_same_core_proof_and_causal_post_actual_return_have_distinct_completion(self):
        value = self.node(steps=[{'code': self.FINISH, 'action': 'writer'},
                                {'code': 'g2.cd.verifyReturn(__DELIVERED__);'}])
        self.assertIsNone(value['error'])
        self.assertEqual(len(value['spawned']), 2)
        self.assertEqual(value['spawned'][1]['file'], 'C:/Python314/python.exe')
        program = value['spawned'][1]['args'][4]
        self.assertIn('MAX_SELECTED_BYTES=4096', program)
        self.assertIn('ACK_CAP=16384', program)
        self.assertIn('gate2-c1.outer-tool.original.json', program)
        self.assertNotIn('gate2-p0-exception.outer-tool.original.json', program)
        writer = self.facts(value['writes'][-2])
        self.assertTrue(writer['completed'])
        verified = json.loads(value['writes'][-1])
        self.assertEqual(verified[:2], [3, 'C1'])
        self.assertEqual(verified[4:6], [True, True])
        ack = base64.b64decode(value['sent'][1]).split(b'\n', 1)[0]
        self.assertEqual(canonical(json.loads(ack)), ack)
        self.assertLessEqual(len(ack) + 1, 16384)

    def writer_attempts(self, **fault):
        code=("let selected=g2.canon({call:{tool:'mcp__node_repl__js',timeout_ms:32000,codes:['controlled actual call']},"
              "frames:[{content:[{type:'text',text:__DELIVERED__}],isError:false}]}),errors=[];"
              "for(let i=0;i<2;i++)try{await g2.cd.finish(selected);}catch(e){errors.push({message:e.message,facts:e.facts??null});}"
              "nodeRepl.write(JSON.stringify({writer_errors:errors}));")
        value=self.node(steps=[{'code':code}],**fault)
        self.assertIsNone(value['error'])
        return value,json.loads(value['writes'][-1])['writer_errors']

    def test_synchronous_writer_spawn_failure_is_one_attempt_and_never_retried(self):
        value,errors=self.writer_attempts(writer_spawn_throw=True)
        self.assertEqual(len(value['attempts']),2)
        self.assertEqual(len(value['spawned']),1)
        self.assertEqual(len(errors),2)
        self.assertEqual(errors[1]['message'],'cd_writer_once')
        facts=errors[0]['facts']
        self.assertTrue(facts['writer_attempted'])
        self.assertIsNone(facts['pid'])
        self.assertTrue(facts['unknown_closure'])
        self.assertEqual(value['killed'],0)

    def test_known_writer_child_survives_tracking_fault_with_single_eof_and_ordered_close_facts(self):
        for close_fault in (False,True):
            with self.subTest(close_fault=close_fault):
                value,errors=self.writer_attempts(writer_track_throw=True,writer_close_throw=close_fault)
                self.assertEqual(len(value['attempts']),2)
                self.assertEqual(len(value['spawned']),2)
                self.assertEqual(errors[1]['message'],'cd_writer_once')
                facts=errors[0]['facts']
                self.assertEqual(facts['pid'],4294967294)
                self.assertEqual(facts['cause'],'cd_writer_track')
                self.assertEqual(facts['initiating_message'],'controlled_writer_track')
                self.assertTrue(facts['writer_attempted'])
                self.assertTrue(facts['unknown_closure'])
                self.assertFalse(facts['tracking_completed'])
                self.assertTrue(facts['stdin_close_attempted'])
                self.assertEqual(facts['stdin_close_returned'],not close_fault)
                self.assertEqual(facts['secondary'],['cd_writer_stdin_close'] if close_fault else [])
                self.assertEqual([base64.b64decode(b) for b in value['sent'][1:]],[b''])
                self.assertEqual(value['killed'],0)

    def test_known_native_child_is_adopted_before_track_and_never_respawned_or_sent_boot(self):
        for close_fault in (False,True):
            with self.subTest(close_fault=close_fault):
                begin=self.initial_code()
                code=('let errors=[];for(let i=0;i<2;i++)try{'+begin+
                      '}catch(e){errors.push({message:e.message,facts:e.facts??null});}'
                      'nodeRepl.write(JSON.stringify({native_errors:errors}));')
                value=self.node(code=code,action='none',native_track_throw=True,native_close_throw=close_fault)
                self.assertIsNone(value['error'])
                self.assertEqual(len(value['attempts']),1)
                self.assertEqual(len(value['spawned']),1)
                errors=json.loads(value['writes'][-1])['native_errors']
                self.assertEqual(errors[1]['message'],'cd_stage_order')
                facts=errors[0]['facts']
                self.assertEqual(facts['pid'],4294967295)
                self.assertEqual(facts['cause'],'cd_native_track')
                self.assertEqual(facts['initiating_message'],'controlled_native_track')
                self.assertTrue(facts['native_attempted'])
                self.assertFalse(facts['tracking_completed'])
                self.assertTrue(facts['unknown_closure'])
                self.assertEqual(facts['stdin_close_returned'],not close_fault)
                self.assertEqual(facts['secondary'],['cd_native_stdin_close'] if close_fault else [])
                self.assertEqual([base64.b64decode(b) for b in value['sent']],[b''])
                self.assertEqual(value['killed'],0)

    def test_partial_tracking_fallback_owns_repeated_async_errors_on_all_four_emitters(self):
        for role in ('native','writer'):
            with self.subTest(role=role):
                if role=='writer':
                    value,errors=self.writer_attempts(writer_track_throw=True,fallback_emit_errors=True)
                else:
                    begin=self.initial_code()
                    code=('let errors=[];try{'+begin+'}catch(e){errors.push({message:e.message,facts:e.facts??null});}'
                          'nodeRepl.write(JSON.stringify({native_errors:errors}));')
                    value=self.node(code=code,action='none',native_track_throw=True,fallback_emit_errors=True)
                    self.assertIsNone(value['error'])
                    errors=json.loads(value['writes'][-1])['native_errors']
                facts=errors[0]['facts']
                self.assertEqual(facts['cause'],'cd_'+role+'_track')
                self.assertEqual(facts['initiating_message'],'controlled_'+role+'_track')
                self.assertEqual(facts['secondary'],['cd_'+role+'_'+label+'_error'
                    for label in ('child','stdin','stdout','stderr')])
                self.assertTrue(facts['unknown_closure'])
                self.assertFalse(facts['tracking_completed'])
                self.assertEqual(value['killed'],0)

    def test_fallback_skips_eof_without_a_successfully_installed_stdin_error_listener(self):
        labels={'missing':'stdin_missing','missing_on':'stdin_error_handler_missing',
                'throwing_on':'stdin_error_handler'}
        for role in ('native','writer'):
            for fault,label in labels.items():
                with self.subTest(role=role,fault=fault):
                    if role=='writer':
                        value,errors=self.writer_attempts(writer_track_throw=True,fallback_stdin_fault=fault)
                        sent=value['sent'][1:]
                        retry='cd_writer_once'
                    else:
                        begin=self.initial_code()
                        code=('let errors=[];for(let i=0;i<2;i++)try{'+begin+
                              '}catch(e){errors.push({message:e.message,facts:e.facts??null});}'
                              'nodeRepl.write(JSON.stringify({native_errors:errors}));')
                        value=self.node(code=code,action='none',native_track_throw=True,fallback_stdin_fault=fault)
                        self.assertIsNone(value['error'])
                        errors=json.loads(value['writes'][-1])['native_errors']
                        sent=value['sent']
                        retry='cd_stage_order'
                    facts=errors[0]['facts']
                    self.assertEqual(errors[1]['message'],retry)
                    self.assertEqual(facts['cause'],'cd_'+role+'_track')
                    self.assertEqual(facts['initiating_message'],'controlled_'+role+'_track')
                    self.assertEqual(facts['pid'],4294967294 if role=='writer' else 4294967295)
                    self.assertEqual(facts['secondary'],['cd_'+role+'_'+label])
                    self.assertTrue(facts['unknown_closure'])
                    self.assertTrue(facts['stdin_extent_unknown'])
                    self.assertFalse(facts['stdin_error_handler_installed'])
                    self.assertFalse(facts['stdin_close_attempted'])
                    self.assertFalse(facts['stdin_close_returned'])
                    self.assertEqual(sent,[])
                    self.assertEqual(len(value['attempts']),2 if role=='writer' else 1)
                    self.assertEqual(value['killed'],0)

    def test_failure_can_be_retained_but_cannot_advance_to_the_next_stage(self):
        args = ['c'*40, '32768', 'd'*64, '8192:'+'e'*64]
        value = self.node(action='failure', steps=[{'code': self.FINISH, 'action': 'writer'},
            {'code': 'g2.cd.verifyReturn(__DELIVERED__);'},
            {'code': self.begin_code('C2', args)}])
        self.assertEqual(value['error'], 'cd_stage_order')
        self.assertEqual(json.loads(value['writes'][-1])[4:6], [False, True])
        self.assertEqual(len(value['spawned']), 2)

    def test_known_wrong_writer_proof_or_late_actual_return_never_verifies(self):
        for fault in ('extent', 'source'):
            value = self.node(writer_fault=fault, steps=[{'code': self.FINISH, 'action': 'writer'},
                {'code': 'g2.cd.verifyReturn(__DELIVERED__);'}])
            self.assertEqual(value['error'], 'writer_write_facts')
            self.assertEqual(len(value['writes']), 2)
        value = self.node(steps=[{'code': self.FINISH, 'action': 'writer'},
            {'clock': 350000, 'code': 'g2.cd.verifyReturn(__DELIVERED__);'}])
        self.assertEqual(value['error'], 'cd_original_deadline')
        self.assertEqual(len(value['writes']), 2)

    def test_emitted_verification_reuses_its_checked_time_without_unchecked_late_state_advance(self):
        value=self.node(steps=[{'code':self.FINISH,'action':'writer'},
            {'code':'g2.cd.verifyReturn(__DELIVERED__);','capture_clock':True,
             'clock_after_reads':3,'clock_value':350000}])
        self.assertIsNone(value['error'])
        proof=json.loads(value['writes'][-1])
        self.assertLess(value['verifySamples'][-1],350000)
        self.assertEqual(proof[2],value['verifySamples'][-1])
        self.assertTrue(proof[5])

    def test_post_proof_clock_at_end_never_advances_or_starts_next_stage(self):
        next_call=self.begin_code('C2',['c'*40,'32768','d'*64,'8192:'+'e'*64])
        verify=("let failures=[];try{g2.cd.verifyReturn(__DELIVERED__);}catch(e){failures.push(e.message);}"
                "try{"+next_call+"}catch(e){failures.push(e.message);}nodeRepl.write(JSON.stringify({failures}));")
        value=self.node(steps=[{'code':self.FINISH,'action':'writer'},
            {'code':verify,'capture_clock':True,'clock_after_reads':2,'clock_value':350000}])
        self.assertIsNone(value['error'])
        self.assertEqual(json.loads(value['writes'][-1])['failures'],['cd_original_deadline','cd_stage_order'])
        self.assertEqual(len(value['spawned']),2)

    def test_high_bit_writer_ready_is_rejected_before_ack_or_dependent_write(self):
        ready=b'{"ready":true,"schema_version":1}\n'
        bad=bytes([ready[0]|128])+ready[1:]
        value=self.node(writer_ready=base64.b64encode(bad).decode(),
                        steps=[{'code':self.FINISH,'action':'writer'}])
        self.assertIsNone(value['error'])
        self.assertEqual(len(value['sent']),2)
        self.assertEqual(base64.b64decode(value['sent'][-1]),b'')
        facts=self.facts(value['writes'][-1])
        self.assertFalse(facts['completed'])
        self.assertIn('cd_writer_ready',facts['causes'])
        self.assertEqual(facts['stdin_bytes'],0)

    def test_malformed_or_extra_native_stdout_can_be_retained_but_never_advances(self):
        _, outputs = self.native_outputs('C1')
        good = outputs[1].decode('ascii')
        for output in ('{}\n','{"native":"\u00e9"}\n',good+'extra\n',
                       good.replace('"external_approval":false','"external_approval":true')):
            with self.subTest(output=output[:80]):
                value = self.node(output=output,steps=[{'code':self.FINISH,'action':'writer'},
                    {'code':'g2.cd.verifyReturn(__DELIVERED__);'},
                    {'code':self.begin_code('C2',['c'*40,'32768','d'*64,'8192:'+'e'*64])}])
                self.assertEqual(json.loads(value['writes'][-1])[4:6],[False,True])
                self.assertEqual(value['error'],'cd_stage_order')
                self.assertEqual(len(value['spawned']),2)

    def test_all_six_completed_c_stages_then_d_owns_ten_seconds_with_same_five_native_args(self):
        steps = []
        for index, stage in enumerate(('C1','C2','C3','C4','C5','C6','D')):
            if index:
                args = ['c'*40, '32768', 'd'*64,
                        ','.join('8192:'+('%064x'%n) for n in range(1,index+1))]
                steps.append({'code': self.begin_code(stage, args),
                              'action': 'normal','output':self.native_outputs(stage)[1][1].decode('ascii')})
            steps.extend([{'code': self.FINISH, 'action': 'writer'},
                          {'code': 'g2.cd.verifyReturn(__DELIVERED__);'}])
        value = self.node(steps=steps)
        self.assertIsNone(value['error'])
        self.assertEqual(len(value['spawned']), 14)
        d = self.facts(value['writes'][-3])
        self.assertEqual(d['clock'][1]-d['clock'][0], 10000)
        self.assertTrue(d['completed'])
        self.assertEqual(value['spawned'][-2]['args'][-5], 'D')
        self.assertEqual(len(value['spawned'][-2]['args'][-1].split(',')), 6)

    def test_generated_stage_writer_runs_same_real_fd_path_with_strict_four_kibibyte_profile(self):
        value = self.node(steps=[{'code': self.FINISH, 'action': 'writer'}])
        self.assertIsNone(value['error'])
        program = value['spawned'][1]['args'][4]
        fixture = HeldWriterTests('runTest');fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.target = fixture.root / TARGET.replace('gate2-p0-exception', 'gate2-c1')
        fixture.selected = b'x'*4096
        result, lines, opened = fixture.invoke(source=program)
        self.assertEqual(result, 0)
        self.assertEqual(lines[-1]['all_forms_quote_bytes'], 16384)
        self.assertEqual(fixture.target.read_bytes(), fixture.selected)
        self.assertEqual(len(opened), 1)
        fixture.target.unlink()
        fixture.selected += b'x'
        result, lines, opened = fixture.invoke(source=program)
        self.assertEqual(result, 1)
        self.assertEqual(lines[-1]['cause'], 'payload_shape')
        self.assertEqual(opened, [])

    def test_stage_ack_and_actual_allocation_overbounds_preserve_the_fixed_profile(self):
        value = self.node(steps=[{'code':self.FINISH,'action':'writer'}])
        self.assertIsNone(value['error'])
        program = value['spawned'][1]['args'][4]
        for kind in ('ack','allocation'):
            with self.subTest(kind=kind):
                fixture = HeldWriterTests('runTest');fixture.setUp();self.addCleanup(fixture.doCleanups)
                fixture.target = fixture.root / TARGET.replace('gate2-p0-exception','gate2-c1')
                fixture.selected = b'x'*4096
                def nt(value, ok):value.allocation=4097;return ok
                code,lines,opened = fixture.invoke(source=program,**(
                    {'ack':b' '*16384+b'\n'} if kind=='ack' else {'nt_effect':nt}))
                self.assertEqual(code,1)
                if kind=='ack':
                    self.assertEqual(lines,[{'ready':True,'schema_version':1}])
                    self.assertEqual(opened,[])
                else:
                    self.assertEqual(lines[-1]['cause'],'write_allocation')
                    self.assertEqual(lines[-1]['known']['allocated_bytes'],4097)
                    self.assertTrue(lines[-1]['known']['close_completed'])
                    self.assertEqual(fixture.target.read_bytes(),fixture.selected)

    def test_exact_inert_installer_does_no_stage_work_and_import_time_consumes_own_clock(self):
        raw = self.node(code='void 0;', action='none', prior_missing=True)
        self.assertIsNone(raw['error'])
        self.assertEqual(raw['inertInstall'][0], raw['inertInstall'][1])
        self.assertEqual(raw['spawned'], [])
        self.assertEqual(raw['writes'], [])
        late = self.node(import_delay=150001)
        self.assertEqual(late['error'], 'cd_original_deadline')
        self.assertEqual(late['spawned'], [])

    def test_complete_c1_install_and_six_actual_provider_frames_fit_four_kibibytes(self):
        code = self.initial_code()
        polls = [{'code': 'await gate2Resume.cd.poll(1);', 'action': 'none'} for _ in range(4)]
        polls.append({'code': 'await gate2Resume.cd.poll(1);', 'action': 'normal'})
        value = self.node(code=code, action='none', steps=polls,
                          output='{"native":"controlled terminal"}\n')
        self.assertIsNone(value['error'])
        self.assertEqual(len(value['writes']), 6)
        calls = [code] + ['await gate2Resume.cd.poll(1);']*5
        frames = [{'content': [{'type': 'text', 'text': text}], 'isError': False,
                   '_meta': {'actual_ordinal': i+1, 'resource': {'uri': 'controlled:retained'}},
                   'resource': {'mimeType': 'application/json'}} for i,text in enumerate(value['writes'])]
        selected = {'call': {'tool': 'mcp__node_repl__js', 'timeout_ms': 32000, 'codes': calls},
                    'frames': frames}
        encoded = canonical(selected)
        expanded = {'calls': [{'tool': selected['call']['tool'], 'args': {
            'code': item, 'timeout_ms': selected['call']['timeout_ms']}} for item in calls], 'frames': frames}
        held = json.loads(encoded)
        self.assertEqual({'calls': [{'tool': held['call']['tool'], 'args': {
            'code': item, 'timeout_ms': held['call']['timeout_ms']}} for item in held['call']['codes']],
            'frames': held['frames']}, expanded)
        print('CONTROLLED_LATER_C1_COMPLETE_GEOMETRY', json.dumps({
            'externally_retained_factory_bytes': len(CD_FACTORY_SOURCE.encode()), 'begin_call_bytes': len(code.encode()),
            'frame_count': len(frames), 'complete_selected_bytes': len(encoded),
            'limit': 4096, 'upstream_retention_fixture_only': True}, sort_keys=True))
        self.assertLessEqual(len(encoded), 4096)

    def native_outputs(self, stage, *, fail_after_stdout=False):
        """Actual frozen native formatter, controlled operations and owned writer FD."""
        import sys
        with mock.patch.object(sys, 'path', [str(REPO/'scripts'), str(REPO), *sys.path]):
            from tests.fixtures import accepted_policy_fixture_compiler_gate2_c_v1 as c
            from tests.fixtures import accepted_policy_fixture_compiler_gate2_d_v1 as d
        root = c.RESUME_OWNER_ROOT_V1.as_posix() + '/r1'
        self.assertEqual(len(root), 98)
        deadline = 2**64-1
        args = ['c'*40, '32768', 'd'*64,
                '-' if stage == 'C1' else ','.join('8192:'+('%064x'%n)
                    for n in range(1, 7 if stage == 'D' else int(stage[1:])))]
        kwargs = {'project_root': root, 'expected_packet_sha256': args[2],
                  'expected_code_commit': args[0]}
        outputs = {1: b'', 2: b''}
        def write(fd, raw):
            outputs[fd] += raw
            return len(raw)
        with tempfile.TemporaryDirectory() as temp:
            own = Path(temp).resolve()
            output = own/'outputs'/stage
            output.mkdir(parents=True)
            record = c._invocation_record_v1(stage if stage != 'D' else 'C6', args[0], args[2],
                                             'e'*64, 'f'*64, None if stage == 'C1' else 'a'*64)
            with mock.patch.object(c.compiler, '_compiler_directory_sync_v1'):
                persisted = c.write_record_v1(output/'outer.invocation.original.json', record,
                    cap=8192, absolute_deadline_ns=deadline, return_facts=True)
            def native_paths(value):
                if isinstance(value, dict): return {k: native_paths(v) for k,v in value.items()}
                if isinstance(value, list): return [native_paths(v) for v in value]
                if isinstance(value, str): return value.replace(str(own), root).replace('\\','/')
                return value
            completed = dict(native_paths(persisted), completion_deadline_ns=deadline, external_approval=False)
            value = {'controlled': False, 'receipt_descriptor': {'path': str(Path(root)/'outputs/D/controls/d.result.original.json'),
                'size_bytes': 20480, 'sha256': 'e'*64}, 'evaluation': {'passed': True, 'finalization_complete': True},
                'final_measurement_after_receipt': {key: 2**64-1 for key in
                    ('c_free_bytes','ext4_used_bytes','project_free_bytes')},
                'ledger_after_receipt': {'remaining_before': 536870912, 'charge_bytes': 2097152,
                                         'remaining_after': 534773760},
                'absolute_deadline_ns': deadline, 'finished_ns': deadline-1,
                'control_bytes': 524288, 'aggregate_accounted_bytes': 2097152}
            with contextlib.ExitStack() as stack:
                stack.enter_context(mock.patch.object(c, 'parse_native_invocation_v1', return_value=kwargs))
                stack.enter_context(mock.patch.object(c, 'run_c_v1', return_value={}))
                stack.enter_context(mock.patch.object(c, 'complete_c_invocation_v1', return_value=completed))
                stack.enter_context(mock.patch.object(d, 'run_d_v1', return_value=value))
                stack.enter_context(mock.patch.object(c.os, 'write', side_effect=write))
                stack.enter_context(mock.patch.object(c.sys,'stdout',types.SimpleNamespace(fileno=lambda:1,flush=lambda:None)))
                stack.enter_context(mock.patch.object(c.time, 'monotonic_ns',
                    **({'side_effect': [deadline-1,deadline]} if fail_after_stdout else {'return_value': deadline-1})))
                status = c.native_main_v1([stage, *args])
            self.assertEqual(status, int(fail_after_stdout), (stage,outputs[2]))
            self.assertTrue(outputs[1])
            self.assertEqual(bool(outputs[2]), fail_after_stdout)
            return args, outputs

    def test_authentic_98_character_native_c1_c6_d_outputs_and_complete_six_frame_geometry(self):
        maxima = []
        ordered = ('C1','C2','C3','C4','C5','C6','D')
        positives = {stage: self.native_outputs(stage) for stage in ordered}
        for stage in ('C1','C6','D'):
            for failure in (False,True):
                with self.subTest(stage=stage, poststdout_failure=failure):
                    args, outputs = self.native_outputs(stage, fail_after_stdout=failure)
                    steps = []
                    for prior in ordered[:ordered.index(stage)]:
                        if prior != 'C1':
                            prior_args, prior_output = positives[prior]
                            steps.append({'code': self.begin_code(prior,prior_args),'action':'normal',
                                          'output':prior_output[1].decode('ascii'),'stderr':''})
                        steps += [{'code':self.FINISH,'action':'writer'},
                                  {'code':'g2.cd.verifyReturn(__DELIVERED__);'}]
                    if stage != 'C1':
                        steps.append({'code':self.begin_code(stage,args),'action':'none'})
                    steps += [{'code': 'await gate2Resume.cd.poll(1);'} for _ in range(4)]
                    steps.append({'code': 'await gate2Resume.cd.poll(1);',
                                  'action': 'failure' if failure else 'normal',
                                  'output':outputs[1].decode('ascii'),'stderr':outputs[2].decode('ascii')})
                    result = self.node(action='none' if stage=='C1' else 'normal', steps=steps,
                        output=(outputs if stage=='C1' else positives['C1'][1])[1].decode('ascii'))
                    self.assertIsNone(result['error'])
                    frames = [{'content': [{'type':'text','text':text}], 'isError':False,
                               '_meta': {'actual_ordinal':n+1,'resource':{'uri':'controlled:retained'}},
                               'resource': {'mimeType':'application/json'}} for n,text in enumerate(result['writes'][-6:])]
                    calls = [self.begin_code(stage,args)] + ['await gate2Resume.cd.poll(1);']*5
                    collection = {'call': {'tool':'mcp__node_repl__js','timeout_ms':32000,'codes':calls},
                                  'frames':frames}
                    raw = canonical(collection)
                    self.assertEqual(json.loads(raw), collection)
                    self.assertLessEqual(len(raw),4096)
                    facts = self.facts(result['writes'][-1])
                    self.assertEqual(facts['clock'][1]-facts['clock'][0],10000 if stage=='D' else 150000)
                    self.assertEqual(result['spawned'][-1]['args'][-5:], [stage,*args])
                    self.assertEqual(facts['completed'], not failure)
                    self.assertEqual(sum(p['bytes'] for p in facts['pipes']),sum(map(len,outputs.values())))
                    maxima.append({'stage':stage,'poststdout_failure':failure,'stdout':len(outputs[1]),
                                   'stderr':len(outputs[2]),'complete_bytes':len(raw)})
        print('CONTROLLED_AUTHENTIC_LATER_SIX_FRAME_GEOMETRY', json.dumps(maxima,sort_keys=True))

    def test_dual_channel_sentinels_stay_below_four_kibibytes_and_preserve_unknown(self):
        result = self.node(action='failure', output='x'*3000, stderr='y'*3000)
        self.assertIsNone(result['error'])
        facts = self.facts(result['writes'][-1])
        self.assertEqual([p['bytes'] for p in facts['pipes']], [2049,769])
        self.assertEqual(sum(p['bytes'] for p in facts['pipes']),2818)
        self.assertLessEqual(sum(p['bytes'] for p in facts['pipes']),4097)
        self.assertTrue(all(p['remainder_unknown'] for p in facts['pipes']))
        self.assertFalse(facts['completed'])
        self.assertEqual(result['killed'],0)


if __name__ == '__main__':
    unittest.main()
