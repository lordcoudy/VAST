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
const test=JSON.parse(require('node:fs').readFileSync(0,'utf8'));if(test.inert_control_only===true){void gate2InertHarness(test);}else{
let clock=200000,clockReads=0,spawned=[],attempts=[],timers=[],writes=[],reads=[],sent=[],killed=0,imports=[],activeStep=null,stepReads=0,verifySamples=[];
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
 console.log(JSON.stringify({error,error_name,writes,clock,killed,reads,sent,attempts,imports,verifySamples,inertInstall:context.inertInstall,spawned:spawned.map(({file,args,options})=>({file,args,options}))}));})().catch(e=>{console.error(e);process.exitCode=1;});}"""


class LaterStageCallerTests(unittest.TestCase):
    FINISH = ("var last=__DELIVERED__;await g2.cd.finish(g2.canon({call:{tool:'mcp__node_repl__js',"
              "timeout_ms:32000,codes:['controlled actual call']},frames:[{content:[{type:'text',text:last}],isError:false}]}));")
    def node(self, *, action='normal', steps=(), code=None, **extra):
        import shutil, subprocess
        module = resume_node_tests()
        if extra.get('inert_control_only') is True:
            self.assertIs(extra.get('code_generation_disabled'),True,'inert_control_only requires code_generation_disabled=True')
            values=dict(extra,code=module.INERT_CONTROL_SOURCE if code is None else code)
            result=subprocess.run([shutil.which('node') or shutil.which('node.exe'),'--experimental-vm-modules','--no-warnings','-e',module.INERT_HARNESS+'\n'+CD_HARNESS],input=canonical(values),capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
            return json.loads(result.stdout)
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

    def test_inert_control_same_source_skips_core_factory_sources_and_stages(self):
        module=resume_node_tests()
        with mock.patch.object(module,'subject',side_effect=AssertionError('operational preparation forbidden')),mock.patch.object(self,'native_outputs',side_effect=AssertionError('native preparation forbidden')):
            value=self.node(code=module.INERT_CONTROL_SOURCE,inert_control_only=True,code_generation_disabled=True,steps=({'code':'throw Error("operational stage forbidden");'},))
        self.assertIsNone(value['error'])
        self.assertEqual(value['writes'],[module.INERT_CONTROL_EXPECTED])
        self.assertEqual(value['inert']['imports'],['node:crypto','node:zlib'])
        self.assertEqual(value['inert']['clock_reads'],2)
        self.assertEqual(value['inert']['effects'],dict(state_reads=0,state_writes=0,files=0,sources=0,children=0,timers=0))
        self.assertTrue(value['inert']['state_descriptor_unchanged'])

    def test_inert_control_requires_explicit_disabled_generation_before_preparation(self):
        module=resume_node_tests()
        with mock.patch.object(module,'subject',side_effect=AssertionError('operational preparation forbidden')):
            for flag in (None,False,1):
                with self.subTest(flag=flag),self.assertRaisesRegex(AssertionError,'code_generation_disabled'):
                    self.node(code=module.INERT_CONTROL_SOURCE,inert_control_only=True,code_generation_disabled=flag)

    def test_inert_control_shared_faults_and_own_to_string_use_restricted_context(self):
        module=resume_node_tests()
        for name,code,options,error in module.inert_control_cases():
            with self.subTest(name=name):
                value=self.node(code=code,inert_control_only=True,code_generation_disabled=True,**options)
                self.assertEqual(value['error'],error)
                self.assertFalse(value['writes'])
                self.assertEqual(value['inert']['effects'],dict(state_reads=0,state_writes=0,files=0,sources=0,children=0,timers=0))
        source=module.INERT_CONTROL_SOURCE.replace('const intrinsic=Function.prototype.toString;',"Object.defineProperty(wrapper,'toString',{value:()=>{throw Error('own_toString_forbidden');}});const intrinsic=Function.prototype.toString;")
        value=self.node(code=source,inert_control_only=True,code_generation_disabled=True)
        self.assertEqual(value['writes'],[module.INERT_CONTROL_EXPECTED])

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


_D22_BROTLI_DATA_PROGRAM = r"""'use strict';
const z=require('node:zlib');let chunks=[],size=0,failed=false;
function fail(c){if(!failed){failed=true;process.stderr.write(c+'\n');process.exitCode=2;}}
if(process.versions.node!=='25.2.1'){fail('d22_node_version');process.stdin.resume();}
process.stdin.on('error',()=>fail('d22_stdin_error'));
process.stdin.on('data',b=>{if(failed)return;size+=b.length;if(size>262144){fail('d22_input_limit');process.stdin.destroy();return;}chunks.push(b);});
process.stdin.on('end',()=>{if(failed)return;try{
 const raw=Buffer.concat(chunks);chunks=[];
 if(raw.length>16384||raw.some(v=>v>127)){fail('d22_ascii_data');return;}
 const packed=z.brotliCompressSync(raw,{params:{[z.constants.BROTLI_PARAM_QUALITY]:11}});
 const back=z.brotliDecompressSync(packed,{maxOutputLength:16384});
 if(!back.equals(raw)){fail('d22_roundtrip');return;}
 process.stdout.write(JSON.stringify({node_version:process.versions.node,packed_b64:packed.toString('base64'),quality:11,roundtrip:true})+'\n');
}catch(e){fail('d22_brotli_error');}});
"""


class D22CompressionError(RuntimeError):
    def __init__(self, metadata):
        self.metadata = metadata
        super().__init__('D22 DATA compression refused: ' + metadata['causes'][0])


def d22_compress_data_v1(raw, deadline):
    """Compress ASCII DATA in a fixed builtin-only child; never evaluate the DATA.

    Returns (packed bytes, bounded metadata). Refusals raise D22CompressionError
    carrying the same bounded metadata schema. The absolute caller deadline is
    never reset; eight seconds remain for cleanup and the caller's final return.
    """
    import copy
    import math
    import shutil
    import subprocess
    import threading
    import time

    started = time.monotonic()
    buffers = {'stdout': bytearray(), 'stderr': bytearray()}
    channels = {name: {'observed_bytes': 0, 'retained_bytes': 0, 'eof': False,
                       'overflow': False, 'io_error': None, 'closed': False,
                       'unknown_remainder': True} for name in buffers}
    facts = {'schema_version': 1, 'data_only': True, 'spawned': False, 'pid': None,
             'returncode': None, 'timed_out': False, 'kill_requested': False,
             'stdin_bytes': 0, 'stdin_closed': False, 'stdin_complete': False,
             'stdin_extent_unknown': False, 'stdin_write_attempted': False,
             'stdin_write_in_flight': False, 'threads_started': 0, 'reaped': False,
             'threads_joined': False, 'causes': [], 'node_version': None,
             'quality': 11, 'roundtrip': False, 'parent_observed_completion': False,
             'descendant_quiescence': 'UNKNOWN', 'input_bytes': None,
             'input_sha256': None, 'packed_bytes': None, 'packed_sha256': None,
             'environment_keys': [], 'program_sha256': hashlib.sha256(_D22_BROTLI_DATA_PROGRAM.encode('ascii')).hexdigest()}
    lock = threading.RLock()
    def cause(value):
        with lock:
            if value not in facts['causes']:
                facts['causes'].append(value)
    def has_causes():
        with lock:
            return bool(facts['causes'])
    def finish(packed=None):
        # Capture related facts, channels, causes and byte prefixes at one shared
        # lock boundary. Later worker changes cannot mix these captured values.
        with lock:
            snapshot = copy.deepcopy(facts)
            captured_channels = {name: dict(channel) for name, channel in channels.items()}
            prefixes = {name: bytes(buffer) for name, buffer in buffers.items()}
        for name, channel in captured_channels.items():
            prefix = prefixes[name]
            snapshot[name] = {**channel, 'retained_bytes': len(prefix),
                              'prefix_sha256': hashlib.sha256(prefix).hexdigest(),
                              'unknown_remainder': not channel['eof'] or channel['overflow'] or channel['io_error'] is not None}
        snapshot['stderr_prefix_b64'] = base64.b64encode(prefixes['stderr']).decode('ascii')
        observed = time.monotonic()
        snapshot['elapsed_seconds'] = observed - started
        snapshot['finished_before_deadline'] = observed < end if end is not None else False
        snapshot['child_completion_observed_before_deadline'] = (
            snapshot['spawned'] and child_total_end is not None and observed < child_total_end)
        if snapshot['spawned'] and not snapshot['child_completion_observed_before_deadline']:
            if 'child_completion_late' not in snapshot['causes']:
                snapshot['causes'].append('child_completion_late')
        if not snapshot['finished_before_deadline'] and 'parent_deadline' not in snapshot['causes']:
            snapshot['causes'].append('parent_deadline')
        snapshot['parent_observed_completion'] = packed is not None and not snapshot['causes']
        encoded = canonical(snapshot)
        if len(encoded) > 32768:
            raise RuntimeError('D22 compression metadata bound')
        # Publication is immutable; the shared capture does not establish
        # continuous custody or quiescence of unjoined workers/descendants.
        frozen = json.loads(encoded)
        if frozen['causes']:
            raise D22CompressionError(frozen)
        return packed, frozen
    end = None
    child_total_end = None
    if type(deadline) not in (int, float):
        cause('deadline_invalid');return finish()
    try:
        end = float(deadline)
    except (OverflowError, ValueError):
        cause('deadline_invalid');return finish()
    if not math.isfinite(end):
        end = None;cause('deadline_invalid');return finish()
    if type(raw) is not bytes:
        cause('input_type');return finish()
    if len(raw) > 16384:
        cause('input_limit');return finish()
    if not raw.isascii():
        cause('input_ascii');return finish()
    with lock:
        facts.update(input_bytes=len(raw), input_sha256=hashlib.sha256(raw).hexdigest())
    work_end = min(started + 27, end - 8)
    child_total_end = min(started + 30, end - 5)
    cleanup_end = min(child_total_end, work_end + 3)
    with lock:
        facts.update(started_monotonic=started, caller_deadline=end, work_deadline=work_end,
                     child_total_deadline=child_total_end, cleanup_deadline=cleanup_end, child_total_limit_seconds=30,
                     child_work_limit_seconds=27, cleanup_limit_seconds=3, final_reserve_seconds=5)
    if time.monotonic() >= work_end:
        cause('deadline_no_window');return finish()
    node = shutil.which('node') or shutil.which('node.exe')
    if node is None:
        cause('node_unavailable');return finish()
    try:
        node = str(Path(node).resolve(strict=True))
        environment = {'PATH': str(Path(node).parent)}
        if os.name == 'nt':
            environment['SystemRoot'] = os.environ['SystemRoot']
        argv = [node, '--max-old-space-size=256', '--input-type=commonjs', '-e', _D22_BROTLI_DATA_PROGRAM]
        with lock:
            facts.update(node_executable=node, command_options=argv[1:4], environment_keys=sorted(environment))
        if time.monotonic() >= work_end:
            cause('deadline_before_spawn');return finish()
        process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, env=environment, bufsize=0,
                                   start_new_session=os.name != 'nt',
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, KeyError, ValueError) as error:
        cause('spawn_' + type(error).__name__);return finish()
    with lock:
        facts.update(spawned=True, pid=process.pid)
    if time.monotonic() >= work_end:
        with lock:
            facts['timed_out'] = True;cause('deadline_after_spawn')
    def read_channel(name, pipe, limit):
        channel = channels[name]
        try:
            while True:
                with lock:
                    read_size = min(4096, limit + 1 - len(buffers[name]))
                part = pipe.read(read_size)
                with lock:
                    if not part:
                        channel['eof'] = True;break
                    channel['observed_bytes'] += len(part)
                    room = limit - len(buffers[name])
                    buffers[name].extend(part[:room])
                    if len(part) > room:
                        channel['overflow'] = True;cause(name + '_overflow');break
        except (OSError, ValueError) as error:
            with lock:
                channel['io_error'] = type(error).__name__;cause(name + '_read_error')
        finally:
            try:
                pipe.close()
                with lock:
                    channel['closed'] = True
            except (OSError, ValueError):
                cause(name + '_close_error')
    def write_input():
        try:
            while True:
                with lock:
                    offset = facts['stdin_bytes']
                    if offset >= len(raw):
                        break
                    if time.monotonic() >= work_end:
                        cause('stdin_deadline');break
                    remaining = len(raw) - offset
                    facts.update(stdin_write_attempted=True, stdin_write_in_flight=True,
                                 stdin_extent_unknown=True)
                count = process.stdin.write(raw[offset:])
                with lock:
                    facts['stdin_write_in_flight'] = False
                    if type(count) is not int or not 0 < count <= remaining:
                        cause('stdin_short_write');break
                    facts['stdin_bytes'] += count
                    facts['stdin_extent_unknown'] = False
                if time.monotonic() >= work_end:
                    cause('stdin_deadline');break
            with lock:
                facts['stdin_complete'] = (facts['stdin_bytes'] == len(raw)
                                           and not facts['stdin_extent_unknown'])
        except (OSError, ValueError):
            with lock:
                facts.update(stdin_write_in_flight=False, stdin_extent_unknown=True)
                cause('stdin_write_error')
        finally:
            try:
                process.stdin.close()
                with lock:
                    facts['stdin_closed'] = True
            except (OSError, ValueError):
                cause('stdin_close_error')
    threads = [threading.Thread(target=read_channel, args=('stdout', process.stdout, 1048576), daemon=True),
               threading.Thread(target=read_channel, args=('stderr', process.stderr, 16384), daemon=True),
               threading.Thread(target=write_input, daemon=True)]
    started_threads = []
    for thread in threads:
        if has_causes():
            break
        if time.monotonic() >= work_end:
            with lock:
                facts['timed_out'] = True;cause('worker_start_deadline')
            break
        try:
            thread.start()
            started_threads.append(thread)
            if time.monotonic() >= work_end:
                with lock:
                    facts['timed_out'] = True;cause('worker_start_late')
                break
        except RuntimeError:
            if thread.ident is not None:
                started_threads.append(thread)
            cause('thread_start_error');break
    with lock:
        facts['threads_started'] = len(started_threads)
    def status():
        try:
            return process.poll()
        except (OSError, ValueError):
            cause('child_status_error');return None
    while True:
        if time.monotonic() >= work_end:
            with lock:
                facts['timed_out'] = True;cause('child_timeout')
            break
        if has_causes() or (status() is not None and all(not thread.is_alive() for thread in started_threads)):
            break
        time.sleep(min(.005, max(0, work_end - time.monotonic())))
    cleanup_end = min(cleanup_end, time.monotonic() + 3)
    with lock:
        facts['cleanup_deadline'] = cleanup_end
    if status() is None:
        with lock:
            facts['kill_requested'] = True
        try:
            process.kill()
        except OSError:
            cause('child_kill_error')
    for thread, pipe, name in zip(threads, (process.stdout, process.stderr, process.stdin), ('stdout', 'stderr', 'stdin')):
        if thread not in started_threads:
            try:
                pipe.close()
                with lock:
                    if name == 'stdin':
                        facts['stdin_closed'] = True
                    else:
                        channels[name]['closed'] = True
            except (OSError, ValueError):
                cause(name + '_unstarted_close_error')
    try:
        returned = process.wait(timeout=max(0, cleanup_end - time.monotonic()))
        with lock:
            facts['reaped'] = type(returned) is int
            if not facts['reaped']:
                cause('child_reap_unknown')
    except (OSError, ValueError, subprocess.TimeoutExpired):
        cause('child_reap_unknown')
    for thread in started_threads:
        try:
            thread.join(max(0, cleanup_end - time.monotonic()))
        except RuntimeError:
            cause('thread_join_error')
    returned_status = status()
    joined = len(started_threads) == len(threads) and all(not thread.is_alive() for thread in started_threads)
    with lock:
        facts.update(returncode=returned_status, threads_joined=joined)
        if not facts['threads_joined']:
            cause('pipe_completion_unknown')
        if facts['returncode'] != 0:
            cause('child_status')
        if not facts['stdin_complete'] or not facts['stdin_closed'] or not all(c['eof'] for c in channels.values()):
            cause('io_completion_unknown')
        stdout_data, stderr_data = bytes(buffers['stdout']), bytes(buffers['stderr'])
    if has_causes():
        return finish()
    if stderr_data:
        cause('unexpected_stderr');return finish()
    try:
        def unique_pairs(rows):
            result = dict(rows)
            if len(result) != len(rows):
                raise ValueError('duplicate DATA result field')
            return result
        result = json.loads(stdout_data, object_pairs_hook=unique_pairs)
        if (type(result) is not dict or set(result) != {'node_version', 'packed_b64', 'quality', 'roundtrip'}
                or result['node_version'] != '25.2.1' or type(result['quality']) is not int
                or result['quality'] != 11 or result['roundtrip'] is not True
                or type(result['packed_b64']) is not str or stdout_data != canonical(result) + b'\n'):
            raise ValueError('invalid DATA result')
        if len(result['packed_b64']) > 4 * ((32768 + 2) // 3):
            raise ValueError('DATA encoding bound')
        packed = base64.b64decode(result['packed_b64'], validate=True)
        if len(packed) > 32768 or base64.b64encode(packed).decode('ascii') != result['packed_b64']:
            raise ValueError('invalid DATA encoding')
    except (ValueError, TypeError, RecursionError, OverflowError):
        cause('child_protocol');return finish()
    with lock:
        facts.update(node_version=result['node_version'], roundtrip=True,
                     packed_bytes=len(packed), packed_sha256=hashlib.sha256(packed).hexdigest())
    return finish(packed)


class D22DataCompressionTests(unittest.TestCase):
    observations = []

    def _capture(self, call):
        try:
            result = call()
        except D22CompressionError as error:
            self.observations.append(error.metadata)
            return None, error.metadata
        self.observations.append(result[1])
        return result

    def _fake_process(self, stdout=b'', stderr=b'', status=0, blocked=False):
        import threading
        stopped = threading.Event()
        state = {'status': None if blocked else status}
        class Reader(io.BytesIO):
            def read(self, size=-1):
                if blocked:
                    stopped.wait(2)
                return super().read(size)
        def kill():
            state['status'] = -9
            stopped.set()
        def wait(timeout=None):
            import subprocess
            if state['status'] is None:
                stopped.wait(timeout)
            if state['status'] is None:
                raise subprocess.TimeoutExpired('controlled DATA child', timeout)
            return state['status']
        return types.SimpleNamespace(pid=12345, stdin=io.BytesIO(), stdout=Reader(stdout),
                                     stderr=Reader(stderr), poll=lambda: state['status'], kill=kill, wait=wait)

    def test_data_roundtrip_and_closed_child_environment(self):
        import time
        with mock.patch.dict(os.environ, {'NODE_OPTIONS': '--require=forbidden',
                                         'NODE_PATH': 'forbidden', 'NODE_REPL_HISTORY': 'forbidden'}):
            packed, facts = self._capture(lambda: d22_compress_data_v1(b'{"data":"' + b'x' * 4096 + b'"}', time.monotonic() + 40))
        self.assertTrue(bool(packed), 'bounded DATA compression must return bytes')
        self.assertTrue(facts['parent_observed_completion'])
        self.assertEqual(facts['node_version'], '25.2.1')
        self.assertEqual(facts['quality'], 11)
        self.assertTrue(facts['roundtrip'])
        self.assertTrue(facts['stdout']['eof'] and facts['stderr']['eof'])
        self.assertFalse(set(facts['environment_keys']) & {'NODE_OPTIONS', 'NODE_PATH', 'NODE_REPL_HISTORY'})

    def test_bad_data_and_expired_budget_refuse_before_spawn(self):
        import time
        for raw, deadline in ((None, time.monotonic() + 40), (b'\xff', time.monotonic() + 40),
                              (b'x' * 16385, time.monotonic() + 40), (b'{}', time.monotonic() - 1)):
            with self.subTest(kind=type(raw).__name__), mock.patch('subprocess.Popen') as spawn:
                packed, facts = self._capture(lambda: d22_compress_data_v1(raw, deadline))
                self.assertIsNone(packed)
                self.assertFalse(facts['parent_observed_completion'])
                self.assertFalse(facts['spawned'])
                self.assertFalse(facts['stdin_write_attempted'] or facts['stdin_write_in_flight']
                                 or facts['stdin_extent_unknown'])
                spawn.assert_not_called()

    def test_stdout_overflow_preserves_prefix_and_unknown_remainder(self):
        import time
        process = self._fake_process(stdout=b'x' * (1048576 + 1))
        with mock.patch('subprocess.Popen', return_value=process):
            packed, facts = self._capture(lambda: d22_compress_data_v1(b'{}', time.monotonic() + 40))
        self.assertIsNone(packed)
        self.assertIn('stdout_overflow', facts['causes'])
        self.assertEqual(facts['stdout']['retained_bytes'], 1048576)
        self.assertTrue(facts['stdout']['unknown_remainder'])

    def test_channel_io_failure_is_not_eof_or_completion(self):
        import time
        process = self._fake_process()
        class BrokenReader(io.BytesIO):
            def read(self, size=-1):
                raise OSError('controlled read refusal')
        process.stdout = BrokenReader()
        with mock.patch('subprocess.Popen', return_value=process):
            packed, facts = self._capture(lambda: d22_compress_data_v1(b'{}', time.monotonic() + 40))
        self.assertIsNone(packed)
        self.assertIn('stdout_read_error', facts['causes'])
        self.assertFalse(facts['stdout']['eof'])
        self.assertTrue(facts['stdout']['unknown_remainder'])

    def test_deadline_preserves_forced_status_and_nonacceptance(self):
        import time
        process = self._fake_process(blocked=True)
        with mock.patch('subprocess.Popen', return_value=process):
            packed, facts = self._capture(lambda: d22_compress_data_v1(b'{}', time.monotonic() + 8.15))
        self.assertIsNone(packed)
        self.assertTrue(facts['timed_out'] and facts['kill_requested'])
        self.assertEqual(facts['returncode'], -9)
        self.assertFalse(facts['parent_observed_completion'])

    def test_nonzero_status_keeps_bounded_stderr_original(self):
        import time
        process = self._fake_process(stderr=b'd22_data_refused\n', status=2)
        with mock.patch('subprocess.Popen', return_value=process):
            packed, facts = self._capture(lambda: d22_compress_data_v1(b'{}', time.monotonic() + 40))
        self.assertIsNone(packed)
        self.assertIn('child_status', facts['causes'])
        self.assertEqual(facts['returncode'], 2)
        self.assertTrue(base64.b64decode(facts['stderr_prefix_b64']) == b'd22_data_refused\n')

    def test_partial_thread_start_has_three_second_cleanup_and_known_unknowns(self):
        import threading
        import time
        process = self._fake_process(blocked=True)
        original_start, original_join = threading.Thread.start, threading.Thread.join
        calls, waits = [], []
        def start(thread):
            calls.append(thread)
            if len(calls) == 2:
                raise RuntimeError('controlled partial startup')
            original_start(thread)
        def join(thread, timeout=None):
            waits.append(timeout)
            original_join(thread, timeout)
        with mock.patch('subprocess.Popen', return_value=process), \
                mock.patch('threading.Thread.start', start), mock.patch('threading.Thread.join', join):
            packed, facts = self._capture(lambda: d22_compress_data_v1(b'{}', time.monotonic() + 295))
        self.assertIsNone(packed)
        self.assertIn('thread_start_error', facts['causes'])
        self.assertEqual(facts['threads_started'], 1)
        self.assertTrue(facts['kill_requested'] and facts['reaped'])
        self.assertFalse(facts['threads_joined'])
        self.assertTrue(facts['stderr']['closed'] and facts['stderr']['unknown_remainder'])
        self.assertTrue(bool(waits) and all(0 <= value <= 3 for value in waits))
        self.assertLessEqual(facts['cleanup_deadline'], facts['work_deadline'] + 3)
        self.assertLessEqual(facts['work_deadline'], facts['started_monotonic'] + 27)
        self.assertLessEqual(facts['cleanup_deadline'], facts['started_monotonic'] + 30)
        self.assertEqual((facts['child_total_limit_seconds'], facts['child_work_limit_seconds'],
                          facts['cleanup_limit_seconds'], facts['final_reserve_seconds']), (30, 27, 3, 5))

    def test_late_node_resolution_cannot_spawn(self):
        import shutil
        import time
        node = shutil.which('node') or shutil.which('node.exe')
        def delayed_resolution(name):
            time.sleep(.15)
            return node
        with mock.patch('shutil.which', delayed_resolution), mock.patch('subprocess.Popen') as spawn:
            packed, facts = self._capture(lambda: d22_compress_data_v1(b'{}', time.monotonic() + 8.1))
        self.assertIsNone(packed)
        self.assertIn('deadline_before_spawn', facts['causes'])
        spawn.assert_not_called()

    def test_late_spawn_starts_no_worker_or_stdin_write(self):
        process = self._fake_process(blocked=True)
        writes, clock = [], [1000.0]
        class Input(io.BytesIO):
            def write(self, value):
                writes.append(len(value))
                return len(value)
        process.stdin = Input()
        def spawn(*args, **kwargs):
            clock[0] = 1027.0
            return process
        with mock.patch('time.monotonic', side_effect=lambda: clock[0]), \
                mock.patch('subprocess.Popen', spawn), mock.patch('threading.Thread.start') as start:
            packed, facts = self._capture(lambda: d22_compress_data_v1(b'{}', 1040.0))
        self.assertIsNone(packed)
        self.assertIn('deadline_after_spawn', facts['causes'])
        self.assertTrue(facts['spawned'] and facts['kill_requested'] and facts['reaped'])
        self.assertEqual(facts['threads_started'], 0)
        self.assertTrue(not writes and facts['stdin_bytes'] == 0)
        self.assertTrue(facts['stdout']['unknown_remainder'] and facts['stderr']['unknown_remainder'])
        self.assertEqual(facts['returncode'], -9)
        start.assert_not_called()

    def test_each_worker_start_has_pre_and_post_work_guards(self):
        for mode, expected in (('post', 'worker_start_late'), ('next', 'worker_start_deadline')):
            with self.subTest(boundary=mode):
                clock, starts, reads = [1000.0], [], [0]
                process = self._fake_process()
                class InlineThread:
                    ident = None
                    def __init__(self, target, args=(), daemon=None):
                        self.target, self.args = target, args
                    def start(self):
                        starts.append(self)
                        self.ident = 1
                        self.target(*self.args)
                    def join(self, timeout=None):
                        return None
                    def is_alive(self):
                        return False
                def now():
                    if starts:
                        reads[0] += 1
                        if mode == 'post' or reads[0] >= 2:
                            clock[0] = 1027.0
                    return clock[0]
                with mock.patch('time.monotonic', now), mock.patch('threading.Thread', InlineThread), \
                        mock.patch('subprocess.Popen', return_value=process):
                    packed, facts = self._capture(lambda: d22_compress_data_v1(b'{}', 1040.0))
                self.assertIsNone(packed)
                self.assertIn(expected, facts['causes'])
                self.assertEqual(len(starts), 1)
                self.assertEqual(facts['stdin_bytes'], 0)
                self.assertFalse(facts['stdin_complete'])

    def test_late_wait_join_or_status_cannot_publish_completion(self):
        output = canonical({'node_version': '25.2.1', 'packed_b64': 'eA==', 'quality': 11, 'roundtrip': True}) + b'\n'
        for phase in ('wait', 'join', 'status'):
            with self.subTest(observation=phase):
                clock, polls = [1000.0], [0]
                process = self._fake_process(stdout=output)
                class InlineThread:
                    ident = None
                    def __init__(self, target, args=(), daemon=None):
                        self.target, self.args = target, args
                    def start(self):
                        self.ident = 1
                        self.target(*self.args)
                    def join(self, timeout=None):
                        if phase == 'join':
                            clock[0] = 1030.0
                    def is_alive(self):
                        return False
                def status():
                    polls[0] += 1
                    if phase == 'status' and polls[0] >= 2:
                        clock[0] = 1030.0
                    return 0
                def wait(timeout=None):
                    if phase == 'wait':
                        clock[0] = 1030.0
                    return 0
                process.poll, process.wait = status, wait
                with mock.patch('time.monotonic', side_effect=lambda: clock[0]), \
                        mock.patch('threading.Thread', InlineThread), mock.patch('subprocess.Popen', return_value=process):
                    packed, facts = self._capture(lambda: d22_compress_data_v1(b'{}', 1040.0))
                self.assertIsNone(packed)
                self.assertIn('child_completion_late', facts['causes'])
                self.assertTrue(facts['finished_before_deadline'])
                self.assertFalse(facts['child_completion_observed_before_deadline'])
                self.assertFalse(facts['parent_observed_completion'])
                self.assertEqual(facts['descendant_quiescence'], 'UNKNOWN')

    def test_failed_snapshot_does_not_follow_late_worker_mutation(self):
        import threading
        import time
        process = self._fake_process(blocked=True)
        process.poll = lambda: -9
        process.wait = lambda timeout=None: -9
        original_start, original_join = threading.Thread.start, threading.Thread.join
        workers = []
        def start(thread):
            workers.append(thread)
            if len(workers) == 3:
                raise RuntimeError('controlled third startup')
            original_start(thread)
        with mock.patch('subprocess.Popen', return_value=process), \
                mock.patch('threading.Thread.start', start), mock.patch('threading.Thread.join', return_value=None):
            packed, facts = self._capture(lambda: d22_compress_data_v1(b'{}', time.monotonic() + 40))
        before = canonical(facts)
        for worker in workers[:2]:
            original_join(worker, 3)
        self.assertIsNone(packed)
        self.assertTrue(canonical(facts) == before, 'published refusal snapshot must stay fixed')
        self.assertFalse(facts['stdout']['eof'])
        self.assertTrue(facts['stdout']['unknown_remainder'])

    def test_unjoined_reader_capture_binds_prefix_counters_eof_and_causes(self):
        import threading
        import time
        for terminal in ('eof', 'error'):
            with self.subTest(reader_terminal=terminal):
                released, closed = threading.Event(), threading.Event()
                process = self._fake_process()
                process.poll = lambda: -9
                process.wait = lambda timeout=None: -9
                class LateReader(io.BytesIO):
                    def read(self, size=-1):
                        if not released.wait(2):
                            raise OSError('controlled release deadline')
                        part = super().read(size)
                        if not part and terminal == 'error':
                            raise OSError('controlled late read refusal')
                        return part
                    def close(self):
                        super().close()
                        closed.set()
                process.stdout = LateReader(b'bounded DATA')
                original_start, original_join = threading.Thread.start, threading.Thread.join
                original_sha256 = hashlib.sha256
                workers, triggered, settled = [], [], []
                def start(thread):
                    if len(workers) == 2:
                        raise RuntimeError('controlled third startup')
                    workers.append(thread)
                    original_start(thread)
                def hash_after_capture(value=b'', *args, **kwargs):
                    if value == b'' and not triggered:
                        triggered.append(True)
                        released.set()
                        settled.append(closed.wait(2))
                    return original_sha256(value, *args, **kwargs)
                try:
                    with mock.patch('subprocess.Popen', return_value=process), \
                            mock.patch('threading.Thread.start', start), \
                            mock.patch('threading.Thread.join', return_value=None), \
                            mock.patch('hashlib.sha256', hash_after_capture):
                        packed, facts = self._capture(lambda: d22_compress_data_v1(b'{}', time.monotonic() + 40))
                    before = canonical(facts)
                finally:
                    released.set()
                    for worker in workers:
                        original_join(worker, 3)
                self.assertIsNone(packed)
                self.assertTrue(bool(triggered) and settled == [True], 'controlled reader must finish during prefix hashing')
                self.assertEqual((facts['stdout']['observed_bytes'], facts['stdout']['retained_bytes']), (0, 0))
                self.assertEqual(facts['stdout']['prefix_sha256'], original_sha256(b'').hexdigest())
                self.assertFalse(facts['stdout']['eof'] or facts['stdout']['closed'])
                self.assertIsNone(facts['stdout']['io_error'])
                self.assertTrue(facts['stdout']['unknown_remainder'])
                self.assertEqual(set(facts['causes']), {'thread_start_error', 'pipe_completion_unknown',
                                                       'child_status', 'io_completion_unknown'})
                self.assertTrue(canonical(facts) == before, 'captured refusal must stay fixed after late reader completion')

    def test_blocked_second_write_keeps_known_count_and_pending_unknown_extent(self):
        import threading
        import time
        blocked, released = threading.Event(), threading.Event()
        process = self._fake_process()
        process.poll = lambda: -9
        process.wait = lambda timeout=None: -9
        writes = []
        class PendingInput(io.BytesIO):
            def write(self, value):
                writes.append(len(value))
                if len(writes) == 1:
                    return 1
                blocked.set()
                if not released.wait(2):
                    raise OSError('controlled write release deadline')
                return len(value)
        class RefusalAfterWrite(io.BytesIO):
            def read(self, size=-1):
                if not blocked.wait(2):
                    raise OSError('controlled write entry deadline')
                raise OSError('controlled capture refusal')
        process.stdin, process.stdout = PendingInput(), RefusalAfterWrite()
        original_start, original_join = threading.Thread.start, threading.Thread.join
        workers = []
        def start(thread):
            workers.append(thread)
            original_start(thread)
        try:
            with mock.patch('subprocess.Popen', return_value=process), \
                    mock.patch('threading.Thread.start', start), \
                    mock.patch('threading.Thread.join', return_value=None):
                packed, facts = self._capture(lambda: d22_compress_data_v1(b'{}', time.monotonic() + 40))
            before = canonical(facts)
        finally:
            released.set()
            for worker in workers:
                original_join(worker, 3)
        self.assertIsNone(packed)
        self.assertEqual(writes, [2, 1])
        self.assertEqual(facts['stdin_bytes'], 1)
        self.assertTrue(facts['stdin_write_attempted'] and facts['stdin_write_in_flight']
                        and facts['stdin_extent_unknown'])
        self.assertFalse(facts['stdin_complete'] or facts['stdin_closed'] or facts['parent_observed_completion'])
        self.assertIn('stdout_read_error', facts['causes'])
        self.assertIn('pipe_completion_unknown', facts['causes'])
        self.assertTrue(canonical(facts) == before, 'pending-write snapshot must stay fixed after a valid late count')

    def test_decoder_recursion_and_packed_bound_refuse_as_metadata(self):
        import time
        oversized = canonical({'node_version': '25.2.1', 'packed_b64': base64.b64encode(b'x' * 32769).decode(),
                               'quality': 11, 'roundtrip': True}) + b'\n'
        for output in (b'[' * 1100 + b'0' + b']' * 1100, oversized):
            with self.subTest(kind='bounded protocol'), mock.patch('subprocess.Popen', return_value=self._fake_process(stdout=output)):
                packed, facts = self._capture(lambda: d22_compress_data_v1(b'{}', time.monotonic() + 40))
            self.assertIsNone(packed)
            self.assertIn('child_protocol', facts['causes'])

    def test_invalid_stdin_count_preserves_unknown_extent(self):
        import time
        process = self._fake_process()
        class InvalidCount(io.BytesIO):
            def write(self, value):
                return len(value) + 1
        process.stdin = InvalidCount()
        with mock.patch('subprocess.Popen', return_value=process):
            packed, facts = self._capture(lambda: d22_compress_data_v1(b'{}', time.monotonic() + 40))
        self.assertIsNone(packed)
        self.assertIn('stdin_short_write', facts['causes'])
        self.assertTrue(facts['stdin_extent_unknown'])
        self.assertFalse(facts['stdin_complete'])


if __name__ == '__main__':
    unittest.main()


# D23 fixed DATA-driver transport is additive. Existing D22 behavior is untouched.
_D23_CASES = frozenset(('codec_vectors', 'codec_malformed', 'codec_overflow', 'geometry'))
_D23_DRIVER_CAUSES = frozenset(('d23_codec_absent', 'd23_driver_assertion',
                              'd23_driver_input', 'd23_driver_error', 'd23_node_version'))


class D23CaseError(RuntimeError):
    def __init__(self, metadata):
        self.metadata = metadata
        super().__init__('D23 fixed case transport refused: ' + metadata['causes'][0])


class D23FixedDriverTransportTests(unittest.TestCase):
    observations = []

    def setUp(self):
        import sys
        self.fixed_program = "'use strict';/* fixed DATA transport fixture, never executed */"
        self.loader = mock.patch(__name__ + '.resume_node_tests', return_value=types.SimpleNamespace(
            d23_node_driver_v1=lambda: self.fixed_program))
        self.loaded = self.loader.start()
        self.resolver = mock.patch('shutil.which', return_value=sys.executable)
        self.resolver.start()
        self.addCleanup(self.resolver.stop)
        self.addCleanup(self.loader.stop)

    def _capture(self, call):
        try:
            result = call()
        except D23CaseError as error:
            self.observations.append(error.metadata)
            return None, error.metadata
        self.observations.append(result[1])
        return result

    def _wire(self, data=None, case='codec_vectors'):
        return canonical({'case': case, 'data': {} if data is None else data})

    def _output(self, case='codec_vectors', completed=True, cause=None):
        return canonical({'schema_version': 1, 'case': case, 'node_version': '25.2.1',
            'completed': completed, 'cause': cause,
            'checks': [{'id': 'transport_fixture', 'ok': completed}], 'measurements': []}) + b'\n'

    def _fake_process(self, stdout=b'', stderr=b'', status=0, blocked=False):
        import threading
        stopped = threading.Event()
        state = {'status': None if blocked else status}
        class Reader(io.BytesIO):
            def read(self, size=-1):
                if blocked:
                    stopped.wait(2)
                return super().read(size)
        def kill():
            state['status'] = -9
            stopped.set()
        def wait(timeout=None):
            import subprocess
            if state['status'] is None:
                stopped.wait(timeout)
            if state['status'] is None:
                raise subprocess.TimeoutExpired('controlled DATA child', timeout)
            return state['status']
        return types.SimpleNamespace(pid=12345, stdin=io.BytesIO(), stdout=Reader(stdout),
                                     stderr=Reader(stderr), poll=lambda: state['status'], kill=kill, wait=wait)

    def test_fixed_driver_and_behavioral_failure_have_separate_completion_facts(self):
        import time
        for case in sorted(_D23_CASES):
            for completed, cause in ((True, None), (False, 'd23_codec_absent')):
                output = self._output(case, completed, cause)
                with self.subTest(case=case, completed=completed), mock.patch('subprocess.Popen',
                        return_value=self._fake_process(stdout=output)) as spawn, mock.patch.dict(
                        os.environ, {'NODE_OPTIONS': 'forbidden', 'NODE_PATH': 'forbidden',
                                     'NODE_REPL_HISTORY': 'forbidden'}):
                    report, facts = self._capture(lambda: d23_run_case_v1(case, b'{}', time.monotonic() + 40))
                self.assertTrue(facts['parent_observed_completion'])
                self.assertIs(facts['case_completed'], completed)
                self.assertIs(report['completed'], completed)
                self.assertEqual(facts['case_cause'], cause)
                self.assertEqual(facts['program_sha256'], hashlib.sha256(self.fixed_program.encode('ascii')).hexdigest())
                argv = spawn.call_args.args[0]
                self.assertEqual(argv[1:], ['--max-old-space-size=256', '--input-type=commonjs', '-e', self.fixed_program])
                self.assertFalse(set(spawn.call_args.kwargs['env']) - {'PATH', 'SystemRoot'})
                self.assertFalse(any(k in facts for k in ('stderr_prefix_b64', 'stdout_data', 'stderr_data')))
                self.assertLessEqual(len(canonical(facts)), 32768)

    def test_invalid_input_and_budget_refuse_before_driver_loading_or_spawn(self):
        import time
        now = time.monotonic()
        cases = [('unknown', b'{}', now + 40), (True, b'{}', now + 40),
                 ('codec_vectors', None, now + 40), ('codec_vectors', b'\xff', now + 40),
                 ('codec_vectors', b'x' * 262145, now + 40), ('codec_vectors', b'{', now + 40),
                 ('codec_vectors', b'{"x":1,"x":2}', now + 40), ('codec_vectors', b'NaN', now + 40),
                 ('codec_vectors', b'1e9999', now + 40),
                 ('codec_vectors', b'[' * 1100 + b'0', now + 40)]
        cases += [('codec_vectors', b'{}', end) for end in (True, None, float('nan'), float('inf'), now - 1, now + 301)]
        for case, raw, end in cases:
            with self.subTest(kind=type(raw).__name__), mock.patch('subprocess.Popen') as spawn:
                report, facts = self._capture(lambda: d23_run_case_v1(case, raw, end))
                self.assertIsNone(report)
                self.assertFalse(facts['spawned'] or facts['stdin_write_attempted'] or facts['stdin_extent_unknown'])
                self.assertFalse(facts['parent_observed_completion'])
                self.loaded.assert_not_called()
                spawn.assert_not_called()

    def test_full_envelope_exact_limit_and_one_byte_over(self):
        import time
        overhead = len(self._wire('', 'codec_vectors'))
        data = 'x' * (262144 - overhead)
        raw = canonical(data)
        self.assertEqual(len(self._wire(data)), 262144)
        with mock.patch('subprocess.Popen', return_value=self._fake_process(stdout=self._output())):
            report, facts = self._capture(lambda: d23_run_case_v1('codec_vectors', raw, time.monotonic() + 40))
        self.assertTrue(facts['parent_observed_completion'])
        self.assertEqual(facts['input_bytes'], 262144)
        self.loaded.reset_mock()
        with mock.patch('subprocess.Popen') as spawn:
            report, facts = self._capture(lambda: d23_run_case_v1('codec_vectors', canonical(data + 'x'), time.monotonic() + 40))
        self.assertIn('input_envelope_limit', facts['causes'])
        self.loaded.assert_not_called()
        spawn.assert_not_called()

    def test_fixed_driver_kind_ascii_and_size_are_bounded_before_spawn(self):
        import time
        for program, expected in ((None, 'driver_source_kind'), ('x' * 24577, 'driver_source_limit'),
                                  ('', 'driver_source_limit'), ('\u0080', 'driver_source_ascii')):
            with self.subTest(cause=expected), mock.patch(__name__ + '.resume_node_tests',
                    return_value=types.SimpleNamespace(d23_node_driver_v1=lambda: program)), mock.patch('subprocess.Popen') as spawn:
                report, facts = self._capture(lambda: d23_run_case_v1('codec_vectors', b'{}', time.monotonic() + 40))
            self.assertIn(expected, facts['causes'])
            spawn.assert_not_called()

    def test_channel_overflow_status_errors_and_stderr_never_publish_raw_data(self):
        import time
        secret = b'GENERATED_SOURCE_MUST_STAY_RAM'
        variants = [(self._fake_process(stdout=b'x' * 1048577), 'stdout_overflow'),
                    (self._fake_process(stderr=secret * 600), 'stderr_overflow'),
                    (self._fake_process(stdout=self._output(), stderr=secret), 'unexpected_stderr'),
                    (self._fake_process(stdout=self._output(), status=7), 'child_status')]
        class RefusingReader(io.BytesIO):
            def read(self, size=-1):raise OSError('GENERATED_SOURCE_MUST_STAY_RAM')
        broken = self._fake_process();broken.stdout = RefusingReader()
        variants.append((broken, 'stdout_read_error'))
        class UnknownEOFReader(io.BytesIO):
            def read(self, size=-1):return None
        no_eof = self._fake_process();no_eof.stdout = UnknownEOFReader()
        variants.append((no_eof, 'stdout_read_error'))
        def unavailable_status():raise OSError('GENERATED_SOURCE_MUST_STAY_RAM')
        no_status = self._fake_process(stdout=self._output());no_status.poll = unavailable_status
        variants.append((no_status, 'child_status_error'))
        for process, expected in variants:
            with self.subTest(cause=expected), mock.patch('subprocess.Popen', return_value=process):
                report, facts = self._capture(lambda: d23_run_case_v1('codec_vectors', b'{}', time.monotonic() + 40))
            self.assertIsNone(report)
            self.assertIn(expected, facts['causes'])
            self.assertFalse(facts['parent_observed_completion'])
            self.assertTrue(secret not in canonical(facts), 'raw child DATA must never enter retained metadata')
            self.assertLessEqual(len(canonical(facts)), 32768)

    def test_report_schema_and_report_extent_are_independently_bounded(self):
        import time
        base = json.loads(self._output())
        invalid = []
        for key, value in [('schema_version', True), ('case', 'geometry'), ('node_version', '0'),
                           ('completed', 1), ('cause', 'unbounded error text'), ('extra', None),
                           ('checks', [{'id': 'bad-id', 'ok': True}]),
                           ('checks', [{'id': 'ok', 'ok': 1}]),
                           ('checks', [{'id': 'x', 'ok': True}] * 513),
                           ('measurements', [{'id': 'x', 'size_bytes': True, 'sha256': '0' * 64}]),
                           ('measurements', [{'id': 'x', 'size_bytes': 262145, 'sha256': '0' * 64}]),
                           ('measurements', [{'id': 'x', 'size_bytes': 0, 'sha256': 'X' * 64}]),
                           ('measurements', [{'id': 'x', 'size_bytes': 0, 'sha256': '0' * 64}] * 129)]:
            value_report = dict(base);value_report[key] = value;invalid.append(canonical(value_report))
        invalid += [b'{"case":"codec_vectors","case":"codec_vectors"}', b'[' * 1100 + b'0' + b']' * 1100,
                    self._output() + b'{}', self._output() + b' ' * 32768]
        for output in invalid:
            with self.subTest(kind='closed bounded report'), mock.patch('subprocess.Popen', return_value=self._fake_process(stdout=output)):
                report, facts = self._capture(lambda: d23_run_case_v1('codec_vectors', b'{}', time.monotonic() + 40))
            self.assertIsNone(report)
            self.assertIn('child_protocol', facts['causes'])
        output = self._output();output += b' ' * (32768 - len(output))
        with mock.patch('subprocess.Popen', return_value=self._fake_process(stdout=output)):
            report, facts = self._capture(lambda: d23_run_case_v1('codec_vectors', b'{}', time.monotonic() + 40))
        self.assertTrue(facts['parent_observed_completion'])
        self.assertEqual(facts['report_bytes'], 32768)

    def test_late_driver_or_node_resolution_cannot_spawn(self):
        for phase in ('driver', 'node'):
            clock = [1000.0]
            def driver():
                if phase == 'driver':clock[0] = 1027.0
                return self.fixed_program
            def resolve(name):
                import sys
                if phase == 'node':clock[0] = 1027.0
                return sys.executable
            with self.subTest(phase=phase), mock.patch('time.monotonic', side_effect=lambda: clock[0]), \
                    mock.patch(__name__ + '.resume_node_tests', return_value=types.SimpleNamespace(d23_node_driver_v1=driver)), \
                    mock.patch('shutil.which', resolve), mock.patch('subprocess.Popen') as spawn:
                report, facts = self._capture(lambda: d23_run_case_v1('codec_vectors', b'{}', 1040.0))
            self.assertIn('deadline_before_spawn', facts['causes'])
            spawn.assert_not_called()

    def test_driver_loading_failure_is_bounded_and_never_exposes_its_message(self):
        import time
        with mock.patch(__name__ + '.resume_node_tests', side_effect=RuntimeError('GENERATED_SOURCE_MUST_STAY_RAM')), \
                mock.patch('subprocess.Popen') as spawn:
            report, facts = self._capture(lambda: d23_run_case_v1('codec_vectors', b'{}', time.monotonic() + 40))
        self.assertIsNone(report)
        self.assertEqual(facts['causes'], ['driver_source_error'])
        self.assertTrue(b'GENERATED_SOURCE_MUST_STAY_RAM' not in canonical(facts))
        spawn.assert_not_called()

    def test_report_accepts_boundary_measurements_without_behavioral_pass_inference(self):
        import time
        value = json.loads(self._output(completed=False, cause='d23_driver_assertion'))
        value['measurements'] = [{'id': 'x' * 64, 'size_bytes': size, 'sha256': '0' * 64}
                                 for size in (0, 262144)]
        with mock.patch('subprocess.Popen', return_value=self._fake_process(stdout=canonical(value) + b'\n')):
            report, facts = self._capture(lambda: d23_run_case_v1('codec_vectors', b'{}', time.monotonic() + 40))
        self.assertTrue(facts['parent_observed_completion'])
        self.assertFalse(facts['case_completed'])
        self.assertEqual(facts['measurements_count'], 2)
        self.assertFalse(report['completed'])

    def test_work_timeout_keeps_channel_and_stdin_unknowns_nonaccepting(self):
        clock, started, after_start = [1000.0], [], [0]
        process = self._fake_process(blocked=True)
        class PendingThread:
            ident = None
            def __init__(self, target, args=(), daemon=None):pass
            def start(self):
                self.ident = 1
                started.append(self)
            def join(self, timeout=None):return None
            def is_alive(self):return True
        def now():
            if len(started) == 3:
                after_start[0] += 1
                if after_start[0] >= 2:clock[0] = 1027.0
            return clock[0]
        with mock.patch('threading.Thread', PendingThread), mock.patch('time.monotonic', now), \
                mock.patch('subprocess.Popen', return_value=process):
            report, facts = self._capture(lambda: d23_run_case_v1('codec_vectors', b'{}', 1040.0))
        self.assertIsNone(report)
        self.assertIn('child_timeout', facts['causes'])
        self.assertTrue(facts['timed_out'] and facts['kill_requested'])
        self.assertFalse(facts['stdout']['eof'] or facts['stderr']['eof'] or facts['stdin_complete'])
        self.assertFalse(facts['parent_observed_completion'])
        self.assertLessEqual(facts['cleanup_deadline'], facts['started_monotonic'] + 30)

    def test_partial_thread_start_has_three_second_cleanup_and_known_unknowns(self):
        import threading
        import time
        process = self._fake_process(blocked=True)
        original_start, original_join = threading.Thread.start, threading.Thread.join
        calls, waits = [], []
        def start(thread):
            calls.append(thread)
            if len(calls) == 2:
                raise RuntimeError('controlled partial startup')
            original_start(thread)
        def join(thread, timeout=None):
            waits.append(timeout)
            original_join(thread, timeout)
        with mock.patch('subprocess.Popen', return_value=process), \
                mock.patch('threading.Thread.start', start), mock.patch('threading.Thread.join', join):
            report, facts = self._capture(lambda: d23_run_case_v1('codec_vectors', b'{}', time.monotonic() + 295))
        self.assertIsNone(report)
        self.assertIn('thread_start_error', facts['causes'])
        self.assertEqual(facts['threads_started'], 1)
        self.assertTrue(facts['kill_requested'] and facts['reaped'])
        self.assertFalse(facts['threads_joined'])
        self.assertTrue(facts['stderr']['closed'] and facts['stderr']['unknown_remainder'])
        self.assertTrue(bool(waits) and all(0 <= value <= 3 for value in waits))
        self.assertLessEqual(facts['cleanup_deadline'], facts['work_deadline'] + 3)
        self.assertLessEqual(facts['work_deadline'], facts['started_monotonic'] + 27)
        self.assertLessEqual(facts['cleanup_deadline'], facts['started_monotonic'] + 30)
        self.assertEqual((facts['child_total_limit_seconds'], facts['child_work_limit_seconds'],
                          facts['cleanup_limit_seconds'], facts['final_reserve_seconds']), (30, 27, 3, 5))

    def test_late_spawn_starts_no_worker_or_stdin_write(self):
        process = self._fake_process(blocked=True)
        writes, clock = [], [1000.0]
        class Input(io.BytesIO):
            def write(self, value):
                writes.append(len(value))
                return len(value)
        process.stdin = Input()
        def spawn(*args, **kwargs):
            clock[0] = 1027.0
            return process
        with mock.patch('time.monotonic', side_effect=lambda: clock[0]), \
                mock.patch('subprocess.Popen', spawn), mock.patch('threading.Thread.start') as start:
            report, facts = self._capture(lambda: d23_run_case_v1('codec_vectors', b'{}', 1040.0))
        self.assertIsNone(report)
        self.assertIn('deadline_after_spawn', facts['causes'])
        self.assertTrue(facts['spawned'] and facts['kill_requested'] and facts['reaped'])
        self.assertEqual(facts['threads_started'], 0)
        self.assertTrue(not writes and facts['stdin_bytes'] == 0)
        self.assertTrue(facts['stdout']['unknown_remainder'] and facts['stderr']['unknown_remainder'])
        self.assertEqual(facts['returncode'], -9)
        start.assert_not_called()

    def test_each_worker_start_has_pre_and_post_work_guards(self):
        for mode, expected in (('post', 'worker_start_late'), ('next', 'worker_start_deadline')):
            with self.subTest(boundary=mode):
                clock, starts, reads = [1000.0], [], [0]
                process = self._fake_process()
                class InlineThread:
                    ident = None
                    def __init__(self, target, args=(), daemon=None):
                        self.target, self.args = target, args
                    def start(self):
                        starts.append(self)
                        self.ident = 1
                        self.target(*self.args)
                    def join(self, timeout=None):
                        return None
                    def is_alive(self):
                        return False
                def now():
                    if starts:
                        reads[0] += 1
                        if mode == 'post' or reads[0] >= 2:
                            clock[0] = 1027.0
                    return clock[0]
                with mock.patch('time.monotonic', now), mock.patch('threading.Thread', InlineThread), \
                        mock.patch('subprocess.Popen', return_value=process):
                    report, facts = self._capture(lambda: d23_run_case_v1('codec_vectors', b'{}', 1040.0))
                self.assertIsNone(report)
                self.assertIn(expected, facts['causes'])
                self.assertEqual(len(starts), 1)
                self.assertEqual(facts['stdin_bytes'], 0)
                self.assertFalse(facts['stdin_complete'])

    def test_late_wait_join_or_status_cannot_publish_completion(self):
        output = self._output()
        for phase in ('wait', 'join', 'status'):
            with self.subTest(observation=phase):
                clock, polls = [1000.0], [0]
                process = self._fake_process(stdout=output)
                class InlineThread:
                    ident = None
                    def __init__(self, target, args=(), daemon=None):
                        self.target, self.args = target, args
                    def start(self):
                        self.ident = 1
                        self.target(*self.args)
                    def join(self, timeout=None):
                        if phase == 'join':
                            clock[0] = 1030.0
                    def is_alive(self):
                        return False
                def status():
                    polls[0] += 1
                    if phase == 'status' and polls[0] >= 2:
                        clock[0] = 1030.0
                    return 0
                def wait(timeout=None):
                    if phase == 'wait':
                        clock[0] = 1030.0
                    return 0
                process.poll, process.wait = status, wait
                with mock.patch('time.monotonic', side_effect=lambda: clock[0]), \
                        mock.patch('threading.Thread', InlineThread), mock.patch('subprocess.Popen', return_value=process):
                    report, facts = self._capture(lambda: d23_run_case_v1('codec_vectors', b'{}', 1040.0))
                self.assertIsNone(report)
                self.assertIn('child_completion_late', facts['causes'])
                self.assertTrue(facts['finished_before_deadline'])
                self.assertFalse(facts['child_completion_observed_before_deadline'])
                self.assertFalse(facts['parent_observed_completion'])
                self.assertEqual(facts['descendant_quiescence'], 'UNKNOWN')

    def test_unjoined_reader_capture_binds_prefix_counters_eof_and_causes(self):
        import threading
        import time
        for terminal in ('eof', 'error'):
            with self.subTest(reader_terminal=terminal):
                released, closed = threading.Event(), threading.Event()
                process = self._fake_process()
                process.poll = lambda: -9
                process.wait = lambda timeout=None: -9
                class LateReader(io.BytesIO):
                    def read(self, size=-1):
                        if not released.wait(2):
                            raise OSError('controlled release deadline')
                        part = super().read(size)
                        if not part and terminal == 'error':
                            raise OSError('controlled late read refusal')
                        return part
                    def close(self):
                        super().close()
                        closed.set()
                process.stdout = LateReader(b'bounded DATA')
                original_start, original_join = threading.Thread.start, threading.Thread.join
                original_sha256 = hashlib.sha256
                workers, triggered, settled = [], [], []
                def start(thread):
                    if len(workers) == 2:
                        raise RuntimeError('controlled third startup')
                    workers.append(thread)
                    original_start(thread)
                def hash_after_capture(value=b'', *args, **kwargs):
                    if value == b'' and not triggered:
                        triggered.append(True)
                        released.set()
                        settled.append(closed.wait(2))
                    return original_sha256(value, *args, **kwargs)
                try:
                    with mock.patch('subprocess.Popen', return_value=process), \
                            mock.patch('threading.Thread.start', start), \
                            mock.patch('threading.Thread.join', return_value=None), \
                            mock.patch('hashlib.sha256', hash_after_capture):
                        report, facts = self._capture(lambda: d23_run_case_v1('codec_vectors', b'{}', time.monotonic() + 40))
                    before = canonical(facts)
                finally:
                    released.set()
                    for worker in workers:
                        original_join(worker, 3)
                self.assertIsNone(report)
                self.assertTrue(bool(triggered) and settled == [True], 'controlled reader must finish during prefix hashing')
                self.assertEqual((facts['stdout']['observed_bytes'], facts['stdout']['retained_bytes']), (0, 0))
                self.assertEqual(facts['stdout']['prefix_sha256'], original_sha256(b'').hexdigest())
                self.assertFalse(facts['stdout']['eof'] or facts['stdout']['closed'])
                self.assertIsNone(facts['stdout']['io_error'])
                self.assertTrue(facts['stdout']['unknown_remainder'])
                self.assertEqual(set(facts['causes']), {'thread_start_error', 'pipe_completion_unknown',
                                                       'child_status', 'io_completion_unknown'})
                self.assertTrue(canonical(facts) == before, 'captured refusal must stay fixed after late reader completion')

    def test_blocked_second_write_keeps_known_count_and_pending_unknown_extent(self):
        import threading
        import time
        blocked, released = threading.Event(), threading.Event()
        process = self._fake_process()
        process.poll = lambda: -9
        process.wait = lambda timeout=None: -9
        writes = []
        class PendingInput(io.BytesIO):
            def write(self, value):
                writes.append(len(value))
                if len(writes) == 1:
                    return 1
                blocked.set()
                if not released.wait(2):
                    raise OSError('controlled write release deadline')
                return len(value)
        class RefusalAfterWrite(io.BytesIO):
            def read(self, size=-1):
                if not blocked.wait(2):
                    raise OSError('controlled write entry deadline')
                raise OSError('controlled capture refusal')
        process.stdin, process.stdout = PendingInput(), RefusalAfterWrite()
        original_start, original_join = threading.Thread.start, threading.Thread.join
        workers = []
        def start(thread):
            workers.append(thread)
            original_start(thread)
        try:
            with mock.patch('subprocess.Popen', return_value=process), \
                    mock.patch('threading.Thread.start', start), \
                    mock.patch('threading.Thread.join', return_value=None):
                report, facts = self._capture(lambda: d23_run_case_v1('codec_vectors', b'{}', time.monotonic() + 40))
            before = canonical(facts)
        finally:
            released.set()
            for worker in workers:
                original_join(worker, 3)
        self.assertIsNone(report)
        self.assertEqual(writes, [len(self._wire()), len(self._wire()) - 1])
        self.assertEqual(facts['stdin_bytes'], 1)
        self.assertTrue(facts['stdin_write_attempted'] and facts['stdin_write_in_flight']
                        and facts['stdin_extent_unknown'])
        self.assertFalse(facts['stdin_complete'] or facts['stdin_closed'] or facts['parent_observed_completion'])
        self.assertIn('stdout_read_error', facts['causes'])
        self.assertIn('pipe_completion_unknown', facts['causes'])
        self.assertTrue(canonical(facts) == before, 'pending-write snapshot must stay fixed after a valid late count')

    def test_invalid_stdin_count_preserves_unknown_extent(self):
        import time
        process = self._fake_process()
        class InvalidCount(io.BytesIO):
            def write(self, value):
                return len(value) + 1
        process.stdin = InvalidCount()
        with mock.patch('subprocess.Popen', return_value=process):
            report, facts = self._capture(lambda: d23_run_case_v1('codec_vectors', b'{}', time.monotonic() + 40))
        self.assertIsNone(report)
        self.assertIn('stdin_short_write', facts['causes'])
        self.assertTrue(facts['stdin_extent_unknown'])
        self.assertFalse(facts['stdin_complete'])



    def test_early_cleanup_wait_join_or_status_lateness_refuses_before_child_total_end(self):
        for phase in ('wait', 'join', 'status'):
            with self.subTest(observation=phase):
                clock, polls = [1000.0], [0]
                process = self._fake_process(stdout=self._output())
                class InlineThread:
                    ident = None
                    def __init__(self, target, args=(), daemon=None):
                        self.target, self.args = target, args
                    def start(self):
                        self.ident = 1
                        self.target(*self.args)
                    def join(self, timeout=None):
                        if phase == 'join':clock[0] = 1003.0
                    def is_alive(self):return False
                def status():
                    polls[0] += 1
                    if phase == 'status' and polls[0] >= 3:clock[0] = 1003.0
                    return 0
                def wait(timeout=None):
                    if phase == 'wait':clock[0] = 1003.0
                    return 0
                process.poll, process.wait = status, wait
                with mock.patch('time.monotonic', side_effect=lambda: clock[0]), \
                        mock.patch('threading.Thread', InlineThread), mock.patch('subprocess.Popen', return_value=process):
                    report, facts = self._capture(lambda: d23_run_case_v1('codec_vectors', b'{}', 1040.0))
                self.assertIsNone(report)
                self.assertEqual(facts['causes'], ['cleanup_late'])
                self.assertEqual(facts['cleanup_deadline'], 1003.0)
                self.assertLess(clock[0], facts['child_total_deadline'])
                self.assertTrue(facts['finished_before_deadline'])
                self.assertTrue(facts['child_completion_observed_before_deadline'])
                self.assertFalse(facts['parent_observed_completion'])
                self.assertEqual(facts['returncode'], 0)
                self.assertTrue(facts['reaped'] and facts['threads_joined'])
                self.assertTrue(facts['stdout']['eof'] and facts['stderr']['eof'])
                self.assertEqual(facts['descendant_quiescence'], 'UNKNOWN')

    def test_geometry_fixed_driver_binding_and_hold_cause_stay_separate(self):
        import time
        raw = canonical({'case': 'geometry'})
        geometry_program = "'use strict';/* separate fixed geometry DATA fixture, never executed */"
        module = self.loaded.return_value
        codec_getter = mock.Mock(return_value=self.fixed_program)
        geometry_getter = mock.Mock(return_value=geometry_program)
        with mock.patch.object(module, 'd23_node_driver_v1', codec_getter), mock.patch.object(
                module, 'd23_geometry_driver_v1', geometry_getter, create=True):
            # A geometry name in both ordinary case/DATA cannot select a program.
            with mock.patch('subprocess.Popen', return_value=self._fake_process(
                    stdout=self._output('geometry'))) as spawn:
                report, codec = self._capture(lambda: d23_run_case_v1(
                    'geometry', raw, time.monotonic() + 40))
                self.assertTrue(codec['parent_observed_completion'])
                self.assertTrue(report['completed'])
                codec_getter.assert_called_once_with()
                geometry_getter.assert_not_called()
                argv = spawn.call_args.args[0]
                self.assertEqual(argv[1:], ['--max-old-space-size=256',
                    '--input-type=commonjs', '-e', self.fixed_program])
                self.assertEqual(codec['program_sha256'],
                    hashlib.sha256(argv[-1].encode('ascii')).hexdigest())
                self.assertEqual(codec['input_sha256'], hashlib.sha256(
                    self._wire({'case': 'geometry'}, case='geometry')).hexdigest())
            codec_getter.reset_mock()
            with mock.patch('subprocess.Popen', return_value=self._fake_process(
                    stdout=self._output('geometry', False, 'd23_geometry_hold'))) as spawn:
                report, geometry = self._capture(lambda: d23_run_geometry_v1(
                    raw, time.monotonic() + 40))
                self.assertIsNotNone(report)
                self.assertTrue(geometry['parent_observed_completion'])
                self.assertFalse(geometry['case_completed'])
                self.assertFalse(report['completed'])
                self.assertEqual(report['cause'], 'd23_geometry_hold')
                self.assertEqual(geometry['case_cause'], 'd23_geometry_hold')
                self.assertEqual(geometry['causes'], [])
                codec_getter.assert_not_called()
                geometry_getter.assert_called_once_with()
                argv = spawn.call_args.args[0]
                self.assertEqual(argv[1:], ['--max-old-space-size=256',
                    '--input-type=commonjs', '-e', geometry_program])
                self.assertEqual(geometry['program_sha256'],
                    hashlib.sha256(argv[-1].encode('ascii')).hexdigest())
                self.assertNotEqual(geometry['program_sha256'], codec['program_sha256'])
                self.assertEqual(geometry['input_sha256'], codec['input_sha256'])
            geometry_getter.reset_mock()
            with mock.patch('subprocess.Popen', return_value=self._fake_process(
                    stdout=self._output('geometry', False, 'd23_geometry_hold'))) as spawn:
                report, refused = self._capture(lambda: d23_run_case_v1(
                    'geometry', raw, time.monotonic() + 40))
                self.assertIsNone(report)
                self.assertFalse(refused['parent_observed_completion'])
                self.assertIn('child_protocol', refused['causes'])
                codec_getter.assert_called_once_with()
                geometry_getter.assert_not_called()
                self.assertEqual(spawn.call_args.args[0][-1], self.fixed_program)
                self.assertEqual(refused['program_sha256'], codec['program_sha256'])
            for facts in (codec, geometry, refused):
                self.assertFalse(any(key in facts for key in (
                    'stderr_prefix_b64', 'stdout_data', 'stderr_data', 'program', 'raw')))
                self.assertLessEqual(len(canonical(facts)), 32768)

    def test_invalid_geometry_mode_refuses_before_loading_or_spawn(self):
        import time
        end = time.monotonic() + 40
        for case, geometry in (('geometry', 1), ('geometry', None), ('codec_vectors', True)):
            with self.subTest(case=case, mode_type=type(geometry).__name__), mock.patch(
                    'subprocess.Popen') as spawn:
                report, facts = self._capture(lambda: _d23_run_fixed_driver_v1(
                    case, b'{}', end, geometry=geometry))
                self.assertIsNone(report)
                self.assertEqual(facts['causes'], ['geometry_invalid'])
                self.assertFalse(facts['spawned'] or facts['stdin_write_attempted']
                                 or facts['stdin_extent_unknown'])
                self.assertFalse(facts['parent_observed_completion'])
                self.loaded.assert_not_called()
                spawn.assert_not_called()


def _d23_run_fixed_driver_v1(case, raw, deadline, geometry=False):
    """Run one closed DATA case in the fixed D23 driver with bounded capture.

    A valid completed:false driver report returns normally. Only transport or
    protocol refusal raises D23CaseError with immutable metadata, never raw DATA.
    The original finite caller deadline also bounds startup, cleanup and return.
    """
    import copy
    import math
    import shutil
    import subprocess
    import threading
    import time

    started = time.monotonic()
    buffers = {'stdout': bytearray(), 'stderr': bytearray()}
    channels = {name: {'observed_bytes': 0, 'retained_bytes': 0, 'eof': False,
                       'overflow': False, 'io_error': None, 'closed': False,
                       'unknown_remainder': True} for name in buffers}
    facts = {'schema_version': 1, 'data_only': True, 'spawned': False, 'pid': None,
             'returncode': None, 'timed_out': False, 'kill_requested': False,
             'stdin_bytes': 0, 'stdin_closed': False, 'stdin_complete': False,
             'stdin_extent_unknown': False, 'stdin_write_attempted': False,
             'stdin_write_in_flight': False, 'threads_started': 0, 'reaped': False,
             'threads_joined': False, 'causes': [], 'node_version': None,
             'case': case if type(case) is str and case in _D23_CASES else None,
             'case_completed': None, 'case_cause': None, 'parent_observed_completion': False,
             'descendant_quiescence': 'UNKNOWN', 'input_bytes': None,
             'input_sha256': None, 'data_bytes': None, 'data_sha256': None,
             'report_bytes': None, 'report_sha256': None, 'checks_count': None,
             'measurements_count': None, 'environment_keys': [], 'program_sha256': None}
    lock = threading.RLock()
    def cause(value):
        with lock:
            if value not in facts['causes']:
                facts['causes'].append(value)
    def has_causes():
        with lock:
            return bool(facts['causes'])
    def finish(report=None):
        # Capture related facts, channels, causes and byte prefixes at one shared
        # lock boundary. Later worker changes cannot mix these captured values.
        with lock:
            snapshot = copy.deepcopy(facts)
            captured_channels = {name: dict(channel) for name, channel in channels.items()}
            prefixes = {name: bytes(buffer) for name, buffer in buffers.items()}
        for name, channel in captured_channels.items():
            prefix = prefixes[name]
            snapshot[name] = {**channel, 'retained_bytes': len(prefix),
                              'prefix_sha256': hashlib.sha256(prefix).hexdigest(),
                              'unknown_remainder': not channel['eof'] or channel['overflow'] or channel['io_error'] is not None}
        observed = time.monotonic()
        snapshot['elapsed_seconds'] = observed - started
        snapshot['finished_before_deadline'] = observed < end if end is not None else False
        snapshot['child_completion_observed_before_deadline'] = (
            snapshot['spawned'] and child_total_end is not None and observed < child_total_end)
        if snapshot['spawned'] and not snapshot['child_completion_observed_before_deadline']:
            if 'child_completion_late' not in snapshot['causes']:
                snapshot['causes'].append('child_completion_late')
        if not snapshot['finished_before_deadline'] and 'parent_deadline' not in snapshot['causes']:
            snapshot['causes'].append('parent_deadline')
        if snapshot['spawned'] and observed >= cleanup_end:
            if 'cleanup_late' not in snapshot['causes']:
                snapshot['causes'].append('cleanup_late')
        snapshot['parent_observed_completion'] = report is not None and not snapshot['causes']
        encoded = canonical(snapshot)
        if len(encoded) > 32768:
            raise RuntimeError('D23 capture metadata bound')
        # Publication is immutable; the shared capture does not establish
        # continuous custody or quiescence of unjoined workers/descendants.
        frozen = json.loads(encoded)
        if frozen['causes']:
            raise D23CaseError(frozen)
        return report, frozen
    end = None
    child_total_end = None
    if type(deadline) not in (int, float):
        cause('deadline_invalid');return finish()
    try:
        end = float(deadline)
    except (OverflowError, ValueError):
        cause('deadline_invalid');return finish()
    if not math.isfinite(end):
        end = None;cause('deadline_invalid');return finish()
    if end - started > 300:
        cause('deadline_limit');return finish()
    if type(case) is not str or case not in _D23_CASES:
        cause('case_invalid');return finish()
    if type(geometry) is not bool or geometry and case != 'geometry':
        cause('geometry_invalid');return finish()
    if type(raw) is not bytes:
        cause('input_type');return finish()
    if len(raw) > 262144:
        cause('input_limit');return finish()
    if not raw.isascii():
        cause('input_ascii');return finish()
    if time.monotonic() >= end - 8:
        cause('deadline_no_window');return finish()
    try:
        def unique_input(rows):
            value = dict(rows)
            if len(value) != len(rows):
                raise ValueError('duplicate DATA field')
            return value
        def reject_constant(value):
            raise ValueError('nonfinite DATA')
        data = json.loads(raw, object_pairs_hook=unique_input, parse_constant=reject_constant)
        wire = canonical({'case': case, 'data': data})
        if len(wire) > 262144:
            cause('input_envelope_limit');return finish()
    except (ValueError, TypeError, RecursionError, OverflowError):
        cause('input_json');return finish()
    with lock:
        facts.update(data_bytes=len(raw), data_sha256=hashlib.sha256(raw).hexdigest(),
                     input_bytes=len(wire), input_sha256=hashlib.sha256(wire).hexdigest())
    raw = wire
    work_end = min(started + 27, end - 8)
    child_total_end = min(started + 30, end - 5)
    cleanup_end = min(child_total_end, work_end + 3)
    with lock:
        facts.update(started_monotonic=started, caller_deadline=end, work_deadline=work_end,
                     child_total_deadline=child_total_end, cleanup_deadline=cleanup_end, child_total_limit_seconds=30,
                     child_work_limit_seconds=27, cleanup_limit_seconds=3, final_reserve_seconds=5)
    if time.monotonic() >= work_end:
        cause('deadline_no_window');return finish()
    try:
        module = resume_node_tests()
        program = module.d23_geometry_driver_v1() if geometry else module.d23_node_driver_v1()
    except Exception:
        cause('driver_source_error');return finish()
    if type(program) is not str:
        cause('driver_source_kind');return finish()
    if not 0 < len(program) <= 24576:
        cause('driver_source_limit');return finish()
    try:
        program_bytes = program.encode('ascii')
    except UnicodeEncodeError:
        cause('driver_source_ascii');return finish()
    # Hold one exact immutable source/argv buffer; DATA never selects a program.
    program = program_bytes.decode('ascii')
    with lock:
        facts['program_sha256'] = hashlib.sha256(program_bytes).hexdigest()
    node = shutil.which('node') or shutil.which('node.exe')
    if node is None:
        cause('node_unavailable');return finish()
    try:
        node = str(Path(node).resolve(strict=True))
        environment = {'PATH': str(Path(node).parent)}
        if os.name == 'nt':
            environment['SystemRoot'] = os.environ['SystemRoot']
        argv = [node, '--max-old-space-size=256', '--input-type=commonjs', '-e', program]
        if os.name == 'nt' and len(subprocess.list2cmdline(argv)) > 32767:
            cause('driver_command_limit');return finish()
        with lock:
            facts.update(node_executable=node, command_options=argv[1:4], environment_keys=sorted(environment))
        if time.monotonic() >= work_end:
            cause('deadline_before_spawn');return finish()
        process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, env=environment, bufsize=0,
                                   start_new_session=os.name != 'nt',
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, KeyError, ValueError) as error:
        cause('spawn_' + type(error).__name__);return finish()
    with lock:
        facts.update(spawned=True, pid=process.pid)
    if time.monotonic() >= work_end:
        with lock:
            facts['timed_out'] = True;cause('deadline_after_spawn')
    def read_channel(name, pipe, limit):
        channel = channels[name]
        try:
            while True:
                with lock:
                    read_size = min(4096, limit + 1 - len(buffers[name]))
                part = pipe.read(read_size)
                with lock:
                    if type(part) is not bytes:
                        channel['io_error'] = 'invalid_read';cause(name + '_read_error');break
                    if part == b'':
                        channel['eof'] = True;break
                    channel['observed_bytes'] += len(part)
                    room = limit - len(buffers[name])
                    buffers[name].extend(part[:room])
                    if len(part) > room:
                        channel['overflow'] = True;cause(name + '_overflow');break
        except (OSError, ValueError) as error:
            with lock:
                channel['io_error'] = type(error).__name__;cause(name + '_read_error')
        finally:
            try:
                pipe.close()
                with lock:
                    channel['closed'] = True
            except (OSError, ValueError):
                cause(name + '_close_error')
    def write_input():
        try:
            while True:
                with lock:
                    offset = facts['stdin_bytes']
                    if offset >= len(raw):
                        break
                    if time.monotonic() >= work_end:
                        cause('stdin_deadline');break
                    remaining = len(raw) - offset
                    facts.update(stdin_write_attempted=True, stdin_write_in_flight=True,
                                 stdin_extent_unknown=True)
                count = process.stdin.write(raw[offset:])
                with lock:
                    facts['stdin_write_in_flight'] = False
                    if type(count) is not int or not 0 < count <= remaining:
                        cause('stdin_short_write');break
                    facts['stdin_bytes'] += count
                    facts['stdin_extent_unknown'] = False
                if time.monotonic() >= work_end:
                    cause('stdin_deadline');break
            with lock:
                facts['stdin_complete'] = (facts['stdin_bytes'] == len(raw)
                                           and not facts['stdin_extent_unknown'])
        except (OSError, ValueError):
            with lock:
                facts.update(stdin_write_in_flight=False, stdin_extent_unknown=True)
                cause('stdin_write_error')
        finally:
            try:
                process.stdin.close()
                with lock:
                    facts['stdin_closed'] = True
            except (OSError, ValueError):
                cause('stdin_close_error')
    threads = [threading.Thread(target=read_channel, args=('stdout', process.stdout, 1048576), daemon=True),
               threading.Thread(target=read_channel, args=('stderr', process.stderr, 16384), daemon=True),
               threading.Thread(target=write_input, daemon=True)]
    started_threads = []
    for thread in threads:
        if has_causes():
            break
        if time.monotonic() >= work_end:
            with lock:
                facts['timed_out'] = True;cause('worker_start_deadline')
            break
        try:
            thread.start()
            started_threads.append(thread)
            if time.monotonic() >= work_end:
                with lock:
                    facts['timed_out'] = True;cause('worker_start_late')
                break
        except RuntimeError:
            if thread.ident is not None:
                started_threads.append(thread)
            cause('thread_start_error');break
    with lock:
        facts['threads_started'] = len(started_threads)
    def status():
        try:
            return process.poll()
        except (OSError, ValueError):
            cause('child_status_error');return None
    while True:
        if time.monotonic() >= work_end:
            with lock:
                facts['timed_out'] = True;cause('child_timeout')
            break
        if has_causes() or (status() is not None and all(not thread.is_alive() for thread in started_threads)):
            break
        time.sleep(min(.005, max(0, work_end - time.monotonic())))
    cleanup_end = min(cleanup_end, time.monotonic() + 3)
    with lock:
        facts['cleanup_deadline'] = cleanup_end
    if status() is None:
        with lock:
            facts['kill_requested'] = True
        try:
            process.kill()
        except OSError:
            cause('child_kill_error')
    for thread, pipe, name in zip(threads, (process.stdout, process.stderr, process.stdin), ('stdout', 'stderr', 'stdin')):
        if thread not in started_threads:
            try:
                pipe.close()
                with lock:
                    if name == 'stdin':
                        facts['stdin_closed'] = True
                    else:
                        channels[name]['closed'] = True
            except (OSError, ValueError):
                cause(name + '_unstarted_close_error')
    try:
        returned = process.wait(timeout=max(0, cleanup_end - time.monotonic()))
        with lock:
            facts['reaped'] = type(returned) is int
            if not facts['reaped']:
                cause('child_reap_unknown')
    except (OSError, ValueError, subprocess.TimeoutExpired):
        cause('child_reap_unknown')
    for thread in started_threads:
        try:
            thread.join(max(0, cleanup_end - time.monotonic()))
        except RuntimeError:
            cause('thread_join_error')
    returned_status = status()
    joined = len(started_threads) == len(threads) and all(not thread.is_alive() for thread in started_threads)
    with lock:
        facts.update(returncode=returned_status, threads_joined=joined)
        if not facts['threads_joined']:
            cause('pipe_completion_unknown')
        if type(facts['returncode']) is not int or facts['returncode'] != 0:
            cause('child_status')
        if facts['kill_requested']:
            cause('child_forced')
        if not facts['stdin_complete'] or not facts['stdin_closed'] or not all(c['eof'] for c in channels.values()):
            cause('io_completion_unknown')
        stdout_data, stderr_data = bytes(buffers['stdout']), bytes(buffers['stderr'])
    if has_causes():
        return finish()
    if stderr_data:
        cause('unexpected_stderr');return finish()
    try:
        if len(stdout_data) > 32768 or not stdout_data.isascii():
            raise ValueError('report extent')
        def unique_pairs(rows):
            result = dict(rows)
            if len(result) != len(rows):
                raise ValueError('duplicate report field')
            return result
        result = json.loads(stdout_data, object_pairs_hook=unique_pairs, parse_constant=reject_constant)
        if (type(result) is not dict or set(result) != {'schema_version', 'case', 'node_version',
                'completed', 'cause', 'checks', 'measurements'}
                or type(result['schema_version']) is not int or result['schema_version'] != 1
                or result['case'] != case or type(result['case']) is not str
                or result['node_version'] != '25.2.1' or type(result['completed']) is not bool
                or result['cause'] is not None and (type(result['cause']) is not str
                    or result['cause'] not in _D23_DRIVER_CAUSES and not (geometry
                        and case == 'geometry' and result['cause'] == 'd23_geometry_hold'))
                or type(result['checks']) is not list or len(result['checks']) > 512
                or type(result['measurements']) is not list or len(result['measurements']) > 128):
            raise ValueError('report shape')
        import re
        def identifier(value):
            return type(value) is str and re.fullmatch(r'[A-Za-z0-9_]{1,64}', value) is not None
        for item in result['checks']:
            if (type(item) is not dict or set(item) != {'id', 'ok'}
                    or not identifier(item['id']) or type(item['ok']) is not bool):
                raise ValueError('report check')
        for item in result['measurements']:
            if (type(item) is not dict or set(item) != {'id', 'size_bytes', 'sha256'}
                    or not identifier(item['id']) or type(item['size_bytes']) is not int
                    or not 0 <= item['size_bytes'] <= 262144
                    or type(item['sha256']) is not str
                    or re.fullmatch(r'[0-9a-f]{64}', item['sha256']) is None):
                raise ValueError('report measurement')
    except (ValueError, TypeError, RecursionError, OverflowError):
        cause('child_protocol');return finish()
    with lock:
        facts.update(node_version=result['node_version'], case_completed=result['completed'],
                     case_cause=result['cause'], report_bytes=len(stdout_data),
                     report_sha256=hashlib.sha256(stdout_data).hexdigest(),
                     checks_count=len(result['checks']), measurements_count=len(result['measurements']))
    return finish(result)


def d23_run_case_v1(case, raw, deadline):
    """Use the original fixed codec DATA driver; input never selects a program."""
    return _d23_run_fixed_driver_v1(case, raw, deadline, False)


def d23_run_geometry_v1(raw, deadline):
    """Use only the separate fixed geometry DATA driver, with no source execution."""
    return _d23_run_fixed_driver_v1('geometry', raw, deadline, True)


# D25 additive fixed TEST-driver transport. Existing helpers/defaults stay unchanged.
_D25_CASES = frozenset(('codec_vectors', 'codec_malformed', 'codec_overflow', 'geometry'))
_D25_DRIVER_CAUSES = frozenset(('d25_codec_absent', 'd25_driver_assertion',
                              'd25_driver_input', 'd25_driver_error', 'd25_node_version'))


class D25CaseError(RuntimeError):
    def __init__(self, metadata):
        self.metadata = metadata
        super().__init__('D25 fixed case transport refused: ' + metadata['causes'][0])



class D25FixedDriverTransportTests(unittest.TestCase):
    observations = []

    def setUp(self):
        import sys
        self.fixed_loader = _d25_main_module_v1
        self.fixed_program = "'use strict';/* fixed DATA transport fixture, never executed */"
        self.loader = mock.patch(__name__ + '._d25_main_module_v1', return_value=types.SimpleNamespace(
            d25_node_driver_v1=lambda: self.fixed_program))
        self.loaded = self.loader.start()
        self.resolver = mock.patch('shutil.which', return_value=sys.executable)
        self.resolver.start()
        self.addCleanup(self.resolver.stop)
        self.addCleanup(self.loader.stop)

    def _capture(self, call):
        try:
            result = call()
        except D25CaseError as error:
            self.observations.append(error.metadata)
            return None, error.metadata
        self.observations.append(result[1])
        return result

    def _wire(self, data=None, case='codec_vectors'):
        return canonical({'case': case, 'data': {} if data is None else data})

    def _output(self, case='codec_vectors', completed=True, cause=None):
        return canonical({'schema_version': 1, 'case': case, 'node_version': '25.2.1',
            'completed': completed, 'cause': cause,
            'checks': [{'id': 'transport_fixture', 'ok': completed}], 'measurements': []}) + b'\n'

    def _fake_process(self, stdout=b'', stderr=b'', status=0, blocked=False):
        import threading
        stopped = threading.Event()
        state = {'status': None if blocked else status}
        class Reader(io.BytesIO):
            def read(self, size=-1):
                if blocked:
                    stopped.wait(2)
                return super().read(size)
        def kill():
            state['status'] = -9
            stopped.set()
        def wait(timeout=None):
            import subprocess
            if state['status'] is None:
                stopped.wait(timeout)
            if state['status'] is None:
                raise subprocess.TimeoutExpired('controlled DATA child', timeout)
            return state['status']
        return types.SimpleNamespace(pid=12345, stdin=io.BytesIO(), stdout=Reader(stdout),
                                     stderr=Reader(stderr), poll=lambda: state['status'], kill=kill, wait=wait)

    def test_fixed_driver_and_behavioral_failure_have_separate_completion_facts(self):
        import time
        for case in sorted(_D25_CASES - {'geometry'}):
            for completed, cause in ((True, None), (False, 'd25_codec_absent')):
                output = self._output(case, completed, cause)
                with self.subTest(case=case, completed=completed), mock.patch('subprocess.Popen',
                        return_value=self._fake_process(stdout=output)) as spawn, mock.patch.dict(
                        os.environ, {'NODE_OPTIONS': 'forbidden', 'NODE_PATH': 'forbidden',
                                     'NODE_REPL_HISTORY': 'forbidden'}):
                    report, facts = self._capture(lambda: d25_run_case_v1(case, b'{}', time.monotonic() + 40))
                self.assertTrue(facts['parent_observed_completion'])
                self.assertIs(facts['case_completed'], completed)
                self.assertIs(report['completed'], completed)
                self.assertEqual(facts['case_cause'], cause)
                self.assertEqual(facts['program_sha256'], hashlib.sha256(self.fixed_program.encode('ascii')).hexdigest())
                self.assertEqual(facts['source_kind'], 'd25_fixed_test_driver_v1')
                self.assertEqual(facts['driver_role'], 'codec')
                self.assertEqual(facts['driver_getter'], 'd25_node_driver_v1')
                self.assertEqual(facts['program_bytes'], len(self.fixed_program.encode('ascii')))
                argv = spawn.call_args.args[0]
                self.assertEqual(argv[1:], ['--max-old-space-size=256', '--input-type=commonjs', '-e', self.fixed_program])
                self.assertFalse(set(spawn.call_args.kwargs['env']) - {'PATH', 'SystemRoot'})
                self.assertFalse(any(k in facts for k in ('stderr_prefix_b64', 'stdout_data', 'stderr_data')))
                self.assertLessEqual(len(canonical(facts)), 32768)

    def test_invalid_input_and_budget_refuse_before_driver_loading_or_spawn(self):
        import time
        now = time.monotonic()
        cases = [('unknown', b'{}', now + 40), (True, b'{}', now + 40),
                 ('codec_vectors', None, now + 40), ('codec_vectors', b'\xff', now + 40),
                 ('codec_vectors', b'x' * 262145, now + 40), ('codec_vectors', b'{', now + 40),
                 ('codec_vectors', b'{"x":1,"x":2}', now + 40), ('codec_vectors', b'NaN', now + 40),
                 ('codec_vectors', b'1e9999', now + 40),
                 ('codec_vectors', b'[' * 1100 + b'0', now + 40)]
        cases += [('codec_vectors', b'{}', end) for end in (True, None, float('nan'), float('inf'), now - 1, now + 301)]
        for case, raw, end in cases:
            with self.subTest(kind=type(raw).__name__), mock.patch('subprocess.Popen') as spawn:
                report, facts = self._capture(lambda: d25_run_case_v1(case, raw, end))
                self.assertIsNone(report)
                self.assertFalse(facts['spawned'] or facts['stdin_write_attempted'] or facts['stdin_extent_unknown'])
                self.assertFalse(facts['parent_observed_completion'])
                self.loaded.assert_not_called()
                spawn.assert_not_called()

    def test_full_envelope_exact_limit_and_one_byte_over(self):
        import time
        overhead = len(self._wire('', 'codec_vectors'))
        data = 'x' * (262144 - overhead)
        raw = canonical(data)
        self.assertEqual(len(self._wire(data)), 262144)
        with mock.patch('subprocess.Popen', return_value=self._fake_process(stdout=self._output())):
            report, facts = self._capture(lambda: d25_run_case_v1('codec_vectors', raw, time.monotonic() + 40))
        self.assertTrue(facts['parent_observed_completion'])
        self.assertEqual(facts['input_bytes'], 262144)
        self.loaded.reset_mock()
        with mock.patch('subprocess.Popen') as spawn:
            report, facts = self._capture(lambda: d25_run_case_v1('codec_vectors', canonical(data + 'x'), time.monotonic() + 40))
        self.assertIn('input_envelope_limit', facts['causes'])
        self.loaded.assert_not_called()
        spawn.assert_not_called()

    def test_fixed_driver_kind_ascii_and_size_are_bounded_before_spawn(self):
        import time
        for program, expected in ((None, 'driver_source_kind'), ('x' * 24577, 'driver_source_limit'),
                                  ('', 'driver_source_limit'), ('\u0080', 'driver_source_ascii')):
            with self.subTest(cause=expected), mock.patch(__name__ + '._d25_main_module_v1',
                    return_value=types.SimpleNamespace(d25_node_driver_v1=lambda: program)), mock.patch('subprocess.Popen') as spawn:
                report, facts = self._capture(lambda: d25_run_case_v1('codec_vectors', b'{}', time.monotonic() + 40))
            self.assertIn(expected, facts['causes'])
            spawn.assert_not_called()

    def test_channel_overflow_status_errors_and_stderr_never_publish_raw_data(self):
        import time
        secret = b'GENERATED_SOURCE_MUST_STAY_RAM'
        variants = [(self._fake_process(stdout=b'x' * 1048577), 'stdout_overflow'),
                    (self._fake_process(stderr=secret * 600), 'stderr_overflow'),
                    (self._fake_process(stdout=self._output(), stderr=secret), 'unexpected_stderr'),
                    (self._fake_process(stdout=self._output(), status=7), 'child_status')]
        class RefusingReader(io.BytesIO):
            def read(self, size=-1):raise OSError('GENERATED_SOURCE_MUST_STAY_RAM')
        broken = self._fake_process();broken.stdout = RefusingReader()
        variants.append((broken, 'stdout_read_error'))
        class UnknownEOFReader(io.BytesIO):
            def read(self, size=-1):return None
        no_eof = self._fake_process();no_eof.stdout = UnknownEOFReader()
        variants.append((no_eof, 'stdout_read_error'))
        def unavailable_status():raise OSError('GENERATED_SOURCE_MUST_STAY_RAM')
        no_status = self._fake_process(stdout=self._output());no_status.poll = unavailable_status
        variants.append((no_status, 'child_status_error'))
        for process, expected in variants:
            with self.subTest(cause=expected), mock.patch('subprocess.Popen', return_value=process):
                report, facts = self._capture(lambda: d25_run_case_v1('codec_vectors', b'{}', time.monotonic() + 40))
            self.assertIsNone(report)
            self.assertIn(expected, facts['causes'])
            self.assertFalse(facts['parent_observed_completion'])
            self.assertTrue(secret not in canonical(facts), 'raw child DATA must never enter retained metadata')
            self.assertLessEqual(len(canonical(facts)), 32768)

    def test_report_schema_and_report_extent_are_independently_bounded(self):
        import time
        base = json.loads(self._output())
        invalid = []
        for key, value in [('schema_version', True), ('case', 'geometry'), ('node_version', '0'),
                           ('completed', 1), ('cause', 'unbounded error text'), ('extra', None),
                           ('checks', [{'id': 'bad-id', 'ok': True}]),
                           ('checks', [{'id': 'ok', 'ok': 1}]),
                           ('checks', [{'id': 'x', 'ok': True}] * 513),
                           ('measurements', [{'id': 'x', 'size_bytes': True, 'sha256': '0' * 64}]),
                           ('measurements', [{'id': 'x', 'size_bytes': 262145, 'sha256': '0' * 64}]),
                           ('measurements', [{'id': 'x', 'size_bytes': 0, 'sha256': 'X' * 64}]),
                           ('measurements', [{'id': 'x', 'size_bytes': 0, 'sha256': '0' * 64}] * 129)]:
            value_report = dict(base);value_report[key] = value;invalid.append(canonical(value_report))
        invalid += [b'{"case":"codec_vectors","case":"codec_vectors"}', b'[' * 1100 + b'0' + b']' * 1100,
                    self._output() + b'{}', self._output() + b' ' * 32768]
        for output in invalid:
            with self.subTest(kind='closed bounded report'), mock.patch('subprocess.Popen', return_value=self._fake_process(stdout=output)):
                report, facts = self._capture(lambda: d25_run_case_v1('codec_vectors', b'{}', time.monotonic() + 40))
            self.assertIsNone(report)
            self.assertIn('child_protocol', facts['causes'])
        output = self._output();output += b' ' * (32768 - len(output))
        with mock.patch('subprocess.Popen', return_value=self._fake_process(stdout=output)):
            report, facts = self._capture(lambda: d25_run_case_v1('codec_vectors', b'{}', time.monotonic() + 40))
        self.assertTrue(facts['parent_observed_completion'])
        self.assertEqual(facts['report_bytes'], 32768)

    def test_late_driver_or_node_resolution_cannot_spawn(self):
        for phase in ('driver', 'node'):
            clock = [1000.0]
            def driver():
                if phase == 'driver':clock[0] = 1027.0
                return self.fixed_program
            def resolve(name):
                import sys
                if phase == 'node':clock[0] = 1027.0
                return sys.executable
            with self.subTest(phase=phase), mock.patch('time.monotonic', side_effect=lambda: clock[0]), \
                    mock.patch(__name__ + '._d25_main_module_v1', return_value=types.SimpleNamespace(d25_node_driver_v1=driver)), \
                    mock.patch('shutil.which', resolve), mock.patch('subprocess.Popen') as spawn:
                report, facts = self._capture(lambda: d25_run_case_v1('codec_vectors', b'{}', 1040.0))
            self.assertIn('deadline_before_spawn', facts['causes'])
            spawn.assert_not_called()

    def test_driver_loading_failure_is_bounded_and_never_exposes_its_message(self):
        import time
        with mock.patch(__name__ + '._d25_main_module_v1', side_effect=RuntimeError('GENERATED_SOURCE_MUST_STAY_RAM')), \
                mock.patch('subprocess.Popen') as spawn:
            report, facts = self._capture(lambda: d25_run_case_v1('codec_vectors', b'{}', time.monotonic() + 40))
        self.assertIsNone(report)
        self.assertEqual(facts['causes'], ['driver_source_error'])
        self.assertTrue(b'GENERATED_SOURCE_MUST_STAY_RAM' not in canonical(facts))
        spawn.assert_not_called()

    def test_report_accepts_boundary_measurements_without_behavioral_pass_inference(self):
        import time
        value = json.loads(self._output(completed=False, cause='d25_driver_assertion'))
        value['measurements'] = [{'id': 'x' * 64, 'size_bytes': size, 'sha256': '0' * 64}
                                 for size in (0, 262144)]
        with mock.patch('subprocess.Popen', return_value=self._fake_process(stdout=canonical(value) + b'\n')):
            report, facts = self._capture(lambda: d25_run_case_v1('codec_vectors', b'{}', time.monotonic() + 40))
        self.assertTrue(facts['parent_observed_completion'])
        self.assertFalse(facts['case_completed'])
        self.assertEqual(facts['measurements_count'], 2)
        self.assertFalse(report['completed'])

    def test_work_timeout_keeps_channel_and_stdin_unknowns_nonaccepting(self):
        clock, started, after_start = [1000.0], [], [0]
        process = self._fake_process(blocked=True)
        class PendingThread:
            ident = None
            def __init__(self, target, args=(), daemon=None):pass
            def start(self):
                self.ident = 1
                started.append(self)
            def join(self, timeout=None):return None
            def is_alive(self):return True
        def now():
            if len(started) == 3:
                after_start[0] += 1
                if after_start[0] >= 2:clock[0] = 1027.0
            return clock[0]
        with mock.patch('threading.Thread', PendingThread), mock.patch('time.monotonic', now), \
                mock.patch('subprocess.Popen', return_value=process):
            report, facts = self._capture(lambda: d25_run_case_v1('codec_vectors', b'{}', 1040.0))
        self.assertIsNone(report)
        self.assertIn('child_timeout', facts['causes'])
        self.assertTrue(facts['timed_out'] and facts['kill_requested'])
        self.assertFalse(facts['stdout']['eof'] or facts['stderr']['eof'] or facts['stdin_complete'])
        self.assertFalse(facts['parent_observed_completion'])
        self.assertLessEqual(facts['cleanup_deadline'], facts['started_monotonic'] + 30)

    def test_partial_thread_start_has_three_second_cleanup_and_known_unknowns(self):
        import threading
        import time
        process = self._fake_process(blocked=True)
        original_start, original_join = threading.Thread.start, threading.Thread.join
        calls, waits = [], []
        def start(thread):
            calls.append(thread)
            if len(calls) == 2:
                raise RuntimeError('controlled partial startup')
            original_start(thread)
        def join(thread, timeout=None):
            waits.append(timeout)
            original_join(thread, timeout)
        with mock.patch('subprocess.Popen', return_value=process), \
                mock.patch('threading.Thread.start', start), mock.patch('threading.Thread.join', join):
            report, facts = self._capture(lambda: d25_run_case_v1('codec_vectors', b'{}', time.monotonic() + 295))
        self.assertIsNone(report)
        self.assertIn('thread_start_error', facts['causes'])
        self.assertEqual(facts['threads_started'], 1)
        self.assertTrue(facts['kill_requested'] and facts['reaped'])
        self.assertFalse(facts['threads_joined'])
        self.assertTrue(facts['stderr']['closed'] and facts['stderr']['unknown_remainder'])
        self.assertTrue(bool(waits) and all(0 <= value <= 3 for value in waits))
        self.assertLessEqual(facts['cleanup_deadline'], facts['work_deadline'] + 3)
        self.assertLessEqual(facts['work_deadline'], facts['started_monotonic'] + 27)
        self.assertLessEqual(facts['cleanup_deadline'], facts['started_monotonic'] + 30)
        self.assertEqual((facts['child_total_limit_seconds'], facts['child_work_limit_seconds'],
                          facts['cleanup_limit_seconds'], facts['final_reserve_seconds']), (30, 27, 3, 5))

    def test_late_spawn_starts_no_worker_or_stdin_write(self):
        process = self._fake_process(blocked=True)
        writes, clock = [], [1000.0]
        class Input(io.BytesIO):
            def write(self, value):
                writes.append(len(value))
                return len(value)
        process.stdin = Input()
        def spawn(*args, **kwargs):
            clock[0] = 1027.0
            return process
        with mock.patch('time.monotonic', side_effect=lambda: clock[0]), \
                mock.patch('subprocess.Popen', spawn), mock.patch('threading.Thread.start') as start:
            report, facts = self._capture(lambda: d25_run_case_v1('codec_vectors', b'{}', 1040.0))
        self.assertIsNone(report)
        self.assertIn('deadline_after_spawn', facts['causes'])
        self.assertTrue(facts['spawned'] and facts['kill_requested'] and facts['reaped'])
        self.assertEqual(facts['threads_started'], 0)
        self.assertTrue(not writes and facts['stdin_bytes'] == 0)
        self.assertTrue(facts['stdout']['unknown_remainder'] and facts['stderr']['unknown_remainder'])
        self.assertEqual(facts['returncode'], -9)
        start.assert_not_called()

    def test_each_worker_start_has_pre_and_post_work_guards(self):
        for mode, expected in (('post', 'worker_start_late'), ('next', 'worker_start_deadline')):
            with self.subTest(boundary=mode):
                clock, starts, reads = [1000.0], [], [0]
                process = self._fake_process()
                class InlineThread:
                    ident = None
                    def __init__(self, target, args=(), daemon=None):
                        self.target, self.args = target, args
                    def start(self):
                        starts.append(self)
                        self.ident = 1
                        self.target(*self.args)
                    def join(self, timeout=None):
                        return None
                    def is_alive(self):
                        return False
                def now():
                    if starts:
                        reads[0] += 1
                        if mode == 'post' or reads[0] >= 2:
                            clock[0] = 1027.0
                    return clock[0]
                with mock.patch('time.monotonic', now), mock.patch('threading.Thread', InlineThread), \
                        mock.patch('subprocess.Popen', return_value=process):
                    report, facts = self._capture(lambda: d25_run_case_v1('codec_vectors', b'{}', 1040.0))
                self.assertIsNone(report)
                self.assertIn(expected, facts['causes'])
                self.assertEqual(len(starts), 1)
                self.assertEqual(facts['stdin_bytes'], 0)
                self.assertFalse(facts['stdin_complete'])

    def test_late_wait_join_or_status_cannot_publish_completion(self):
        output = self._output()
        for phase in ('wait', 'join', 'status'):
            with self.subTest(observation=phase):
                clock, polls = [1000.0], [0]
                process = self._fake_process(stdout=output)
                class InlineThread:
                    ident = None
                    def __init__(self, target, args=(), daemon=None):
                        self.target, self.args = target, args
                    def start(self):
                        self.ident = 1
                        self.target(*self.args)
                    def join(self, timeout=None):
                        if phase == 'join':
                            clock[0] = 1030.0
                    def is_alive(self):
                        return False
                def status():
                    polls[0] += 1
                    if phase == 'status' and polls[0] >= 2:
                        clock[0] = 1030.0
                    return 0
                def wait(timeout=None):
                    if phase == 'wait':
                        clock[0] = 1030.0
                    return 0
                process.poll, process.wait = status, wait
                with mock.patch('time.monotonic', side_effect=lambda: clock[0]), \
                        mock.patch('threading.Thread', InlineThread), mock.patch('subprocess.Popen', return_value=process):
                    report, facts = self._capture(lambda: d25_run_case_v1('codec_vectors', b'{}', 1040.0))
                self.assertIsNone(report)
                self.assertIn('child_completion_late', facts['causes'])
                self.assertTrue(facts['finished_before_deadline'])
                self.assertFalse(facts['child_completion_observed_before_deadline'])
                self.assertFalse(facts['parent_observed_completion'])
                self.assertEqual(facts['descendant_quiescence'], 'UNKNOWN')

    def test_unjoined_reader_capture_binds_prefix_counters_eof_and_causes(self):
        import threading
        import time
        for terminal in ('eof', 'error'):
            with self.subTest(reader_terminal=terminal):
                released, closed = threading.Event(), threading.Event()
                process = self._fake_process()
                process.poll = lambda: -9
                process.wait = lambda timeout=None: -9
                class LateReader(io.BytesIO):
                    def read(self, size=-1):
                        if not released.wait(2):
                            raise OSError('controlled release deadline')
                        part = super().read(size)
                        if not part and terminal == 'error':
                            raise OSError('controlled late read refusal')
                        return part
                    def close(self):
                        super().close()
                        closed.set()
                process.stdout = LateReader(b'bounded DATA')
                original_start, original_join = threading.Thread.start, threading.Thread.join
                original_sha256 = hashlib.sha256
                workers, triggered, settled = [], [], []
                def start(thread):
                    if len(workers) == 2:
                        raise RuntimeError('controlled third startup')
                    workers.append(thread)
                    original_start(thread)
                def hash_after_capture(value=b'', *args, **kwargs):
                    if value == b'' and not triggered:
                        triggered.append(True)
                        released.set()
                        settled.append(closed.wait(2))
                    return original_sha256(value, *args, **kwargs)
                try:
                    with mock.patch('subprocess.Popen', return_value=process), \
                            mock.patch('threading.Thread.start', start), \
                            mock.patch('threading.Thread.join', return_value=None), \
                            mock.patch('hashlib.sha256', hash_after_capture):
                        report, facts = self._capture(lambda: d25_run_case_v1('codec_vectors', b'{}', time.monotonic() + 40))
                    before = canonical(facts)
                finally:
                    released.set()
                    for worker in workers:
                        original_join(worker, 3)
                self.assertIsNone(report)
                self.assertTrue(bool(triggered) and settled == [True], 'controlled reader must finish during prefix hashing')
                self.assertEqual((facts['stdout']['observed_bytes'], facts['stdout']['retained_bytes']), (0, 0))
                self.assertEqual(facts['stdout']['prefix_sha256'], original_sha256(b'').hexdigest())
                self.assertFalse(facts['stdout']['eof'] or facts['stdout']['closed'])
                self.assertIsNone(facts['stdout']['io_error'])
                self.assertTrue(facts['stdout']['unknown_remainder'])
                self.assertEqual(set(facts['causes']), {'thread_start_error', 'pipe_completion_unknown',
                                                       'child_status', 'io_completion_unknown'})
                self.assertTrue(canonical(facts) == before, 'captured refusal must stay fixed after late reader completion')

    def test_blocked_second_write_keeps_known_count_and_pending_unknown_extent(self):
        import threading
        import time
        blocked, released = threading.Event(), threading.Event()
        process = self._fake_process()
        process.poll = lambda: -9
        process.wait = lambda timeout=None: -9
        writes = []
        class PendingInput(io.BytesIO):
            def write(self, value):
                writes.append(len(value))
                if len(writes) == 1:
                    return 1
                blocked.set()
                if not released.wait(2):
                    raise OSError('controlled write release deadline')
                return len(value)
        class RefusalAfterWrite(io.BytesIO):
            def read(self, size=-1):
                if not blocked.wait(2):
                    raise OSError('controlled write entry deadline')
                raise OSError('controlled capture refusal')
        process.stdin, process.stdout = PendingInput(), RefusalAfterWrite()
        original_start, original_join = threading.Thread.start, threading.Thread.join
        workers = []
        def start(thread):
            workers.append(thread)
            original_start(thread)
        try:
            with mock.patch('subprocess.Popen', return_value=process), \
                    mock.patch('threading.Thread.start', start), \
                    mock.patch('threading.Thread.join', return_value=None):
                report, facts = self._capture(lambda: d25_run_case_v1('codec_vectors', b'{}', time.monotonic() + 40))
            before = canonical(facts)
        finally:
            released.set()
            for worker in workers:
                original_join(worker, 3)
        self.assertIsNone(report)
        self.assertEqual(writes, [len(self._wire()), len(self._wire()) - 1])
        self.assertEqual(facts['stdin_bytes'], 1)
        self.assertTrue(facts['stdin_write_attempted'] and facts['stdin_write_in_flight']
                        and facts['stdin_extent_unknown'])
        self.assertFalse(facts['stdin_complete'] or facts['stdin_closed'] or facts['parent_observed_completion'])
        self.assertIn('stdout_read_error', facts['causes'])
        self.assertIn('pipe_completion_unknown', facts['causes'])
        self.assertTrue(canonical(facts) == before, 'pending-write snapshot must stay fixed after a valid late count')

    def test_invalid_stdin_count_preserves_unknown_extent(self):
        import time
        process = self._fake_process()
        class InvalidCount(io.BytesIO):
            def write(self, value):
                return len(value) + 1
        process.stdin = InvalidCount()
        with mock.patch('subprocess.Popen', return_value=process):
            report, facts = self._capture(lambda: d25_run_case_v1('codec_vectors', b'{}', time.monotonic() + 40))
        self.assertIsNone(report)
        self.assertIn('stdin_short_write', facts['causes'])
        self.assertTrue(facts['stdin_extent_unknown'])
        self.assertFalse(facts['stdin_complete'])



    def test_early_cleanup_wait_join_or_status_lateness_refuses_before_child_total_end(self):
        for phase in ('wait', 'join', 'status'):
            with self.subTest(observation=phase):
                clock, polls = [1000.0], [0]
                process = self._fake_process(stdout=self._output())
                class InlineThread:
                    ident = None
                    def __init__(self, target, args=(), daemon=None):
                        self.target, self.args = target, args
                    def start(self):
                        self.ident = 1
                        self.target(*self.args)
                    def join(self, timeout=None):
                        if phase == 'join':clock[0] = 1003.0
                    def is_alive(self):return False
                def status():
                    polls[0] += 1
                    if phase == 'status' and polls[0] >= 3:clock[0] = 1003.0
                    return 0
                def wait(timeout=None):
                    if phase == 'wait':clock[0] = 1003.0
                    return 0
                process.poll, process.wait = status, wait
                with mock.patch('time.monotonic', side_effect=lambda: clock[0]), \
                        mock.patch('threading.Thread', InlineThread), mock.patch('subprocess.Popen', return_value=process):
                    report, facts = self._capture(lambda: d25_run_case_v1('codec_vectors', b'{}', 1040.0))
                self.assertIsNone(report)
                self.assertEqual(facts['causes'], ['cleanup_late'])
                self.assertEqual(facts['cleanup_deadline'], 1003.0)
                self.assertLess(clock[0], facts['child_total_deadline'])
                self.assertTrue(facts['finished_before_deadline'])
                self.assertTrue(facts['child_completion_observed_before_deadline'])
                self.assertFalse(facts['parent_observed_completion'])
                self.assertEqual(facts['returncode'], 0)
                self.assertTrue(facts['reaped'] and facts['threads_joined'])
                self.assertTrue(facts['stdout']['eof'] and facts['stderr']['eof'])
                self.assertEqual(facts['descendant_quiescence'], 'UNKNOWN')

    def test_fixed_main_aliases_use_canonical_priority_without_reopening(self):
        import sys
        names = ('tests.test_accepted_policy_fixture_compiler_gate2_resume_v1',
                 'test_accepted_policy_fixture_compiler_gate2_resume_v1')
        expected = Path(__file__).with_name('test_accepted_policy_fixture_compiler_gate2_resume_v1.py').absolute()
        first = types.ModuleType(names[0]);other = types.ModuleType(names[1])
        for module in (first, other):
            module.__file__ = str(expected)
            module.d25_node_driver_v1 = types.FunctionType(
                (lambda: None).__code__.replace(co_filename=str(expected)), vars(module), 'd25_node_driver_v1')
        for mode in ('canonical', 'discovery', 'same', 'different', 'absent', 'wrong_type', 'wrong_origin', 'bad_canonical'):
            with self.subTest(mode=mode), mock.patch.dict(sys.modules), mock.patch(
                    'builtins.open', side_effect=AssertionError('fixed alias must not reopen')), mock.patch.object(
                    Path, 'open', side_effect=AssertionError('fixed alias must not reopen')):
                for name in names:sys.modules.pop(name, None)
                if mode in ('canonical', 'same', 'different', 'wrong_origin'):sys.modules[names[0]] = first
                if mode == 'same':sys.modules[names[1]] = first
                if mode in ('discovery', 'different', 'bad_canonical'):sys.modules[names[1]] = other
                if mode in ('wrong_type', 'bad_canonical'):sys.modules[names[0]] = types.SimpleNamespace(__name__=names[0])
                if mode == 'wrong_origin':first.__file__ = str(expected.with_name('wrong.py'))
                try:
                    if mode in ('canonical', 'discovery', 'same', 'different'):
                        self.assertIs(self.fixed_loader(), other if mode == 'discovery' else first)
                    else:
                        with self.assertRaisesRegex(RuntimeError, '^d25_held_main_unavailable$'):
                            self.fixed_loader()
                finally:first.__file__ = str(expected)


    def test_geometry_fixed_driver_binding_and_hold_cause_stay_separate(self):
        import time
        raw = canonical({'case': 'geometry'})
        geometry_program = "'use strict';/* separate fixed geometry DATA fixture, never executed */"
        module = self.loaded.return_value
        codec_getter = mock.Mock(return_value=self.fixed_program)
        geometry_getter = mock.Mock(return_value=geometry_program)
        with mock.patch.object(module, 'd25_node_driver_v1', codec_getter), mock.patch.object(
                module, 'd25_geometry_driver_v1', geometry_getter, create=True):
            with mock.patch('subprocess.Popen', return_value=self._fake_process(
                    stdout=self._output('codec_vectors'))) as spawn:
                report, codec = self._capture(lambda: d25_run_case_v1(
                    'codec_vectors', raw, time.monotonic() + 40))
                self.assertTrue(codec['parent_observed_completion'])
                self.assertTrue(report['completed'])
                codec_getter.assert_called_once_with()
                geometry_getter.assert_not_called()
                self.assertEqual(spawn.call_args.args[0][-1], self.fixed_program)
                self.assertEqual(codec['source_kind'], 'd25_fixed_test_driver_v1')
                self.assertEqual(codec['driver_role'], 'codec')
                self.assertEqual(codec['driver_getter'], 'd25_node_driver_v1')
                self.assertEqual(codec['program_bytes'], len(self.fixed_program))
                self.assertEqual(codec['program_sha256'], hashlib.sha256(self.fixed_program.encode('ascii')).hexdigest())
            codec_getter.reset_mock()
            with mock.patch('subprocess.Popen', return_value=self._fake_process(
                    stdout=self._output('geometry', False, 'd25_geometry_hold'))) as spawn:
                report, geometry = self._capture(lambda: d25_run_geometry_v1(
                    raw, time.monotonic() + 40))
                self.assertIsNotNone(report)
                self.assertTrue(geometry['parent_observed_completion'])
                self.assertFalse(geometry['case_completed'])
                self.assertEqual(geometry['case_cause'], 'd25_geometry_hold')
                self.assertEqual(geometry['causes'], [])
                codec_getter.assert_not_called()
                geometry_getter.assert_called_once_with()
                self.assertEqual(spawn.call_args.args[0][-1], geometry_program)
                self.assertEqual(geometry['source_kind'], 'd25_fixed_test_driver_v1')
                self.assertEqual(geometry['driver_role'], 'geometry')
                self.assertEqual(geometry['driver_getter'], 'd25_geometry_driver_v1')
                self.assertEqual(geometry['program_bytes'], len(geometry_program))
                self.assertEqual(geometry['program_sha256'], hashlib.sha256(geometry_program.encode('ascii')).hexdigest())
                self.assertNotEqual(geometry['program_sha256'], codec['program_sha256'])
                self.assertNotEqual(geometry['input_sha256'], codec['input_sha256'])
            geometry_getter.reset_mock()
            with mock.patch('subprocess.Popen', return_value=self._fake_process(
                    stdout=self._output('codec_vectors', False, 'd25_geometry_hold'))) as spawn:
                report, refused = self._capture(lambda: d25_run_case_v1(
                    'codec_vectors', raw, time.monotonic() + 40))
                self.assertIsNone(report)
                self.assertFalse(refused['parent_observed_completion'])
                self.assertIn('child_protocol', refused['causes'])
                codec_getter.assert_called_once_with()
                geometry_getter.assert_not_called()
                self.assertEqual(refused['program_sha256'], codec['program_sha256'])
            for facts in (codec, geometry, refused):
                self.assertFalse(any(key in facts for key in (
                    'stderr_prefix_b64', 'stdout_data', 'stderr_data', 'program', 'raw')))
                self.assertLessEqual(len(canonical(facts)), 32768)

    def test_invalid_geometry_mode_refuses_before_loading_or_spawn(self):
        import time
        end = time.monotonic() + 40
        for case, geometry in (('geometry', 1), ('geometry', None), ('codec_vectors', True), ('geometry', False)):
            with self.subTest(case=case, mode_type=type(geometry).__name__), mock.patch(
                    'subprocess.Popen') as spawn:
                report, facts = self._capture(lambda: _d25_run_fixed_driver_v1(
                    case, b'{}', end, geometry=geometry))
                self.assertIsNone(report)
                self.assertEqual(facts['causes'], ['geometry_invalid'])
                self.assertFalse(facts['spawned'] or facts['stdin_write_attempted']
                                 or facts['stdin_extent_unknown'])
                self.assertFalse(facts['parent_observed_completion'])
                self.loaded.assert_not_called()
                spawn.assert_not_called()



def _d25_main_module_v1():
    """Use canonical first, otherwise discovery, with no import or source reopening."""
    import sys
    names = ('tests.test_accepted_policy_fixture_compiler_gate2_resume_v1',
             'test_accepted_policy_fixture_compiler_gate2_resume_v1')
    expected = Path(__file__).with_name('test_accepted_policy_fixture_compiler_gate2_resume_v1.py').absolute()
    present = [(name, sys.modules[name]) for name in names if name in sys.modules]
    if not present:
        raise RuntimeError('d25_held_main_unavailable')
    selected_name, selected = present[0]
    for name, module in present:
        if type(module) is not types.ModuleType:
            raise RuntimeError('d25_held_main_unavailable')
        namespace = vars(module)
        if (namespace.get('__name__') != name and module is not selected
                or type(namespace.get('__file__')) is not str
                or Path(namespace['__file__']).absolute() != expected):
            raise RuntimeError('d25_held_main_unavailable')
    namespace = vars(selected)
    getter = namespace.get('d25_node_driver_v1')
    if (namespace.get('__name__') != selected_name or type(getter) is not types.FunctionType
            or getter.__name__ != 'd25_node_driver_v1' or getter.__module__ != selected_name
            or getter.__globals__ is not namespace or Path(getter.__code__.co_filename).absolute() != expected):
        raise RuntimeError('d25_held_main_unavailable')
    return selected


def _d25_run_fixed_driver_v1(case, raw, deadline, geometry=False):
    """Run one closed DATA case in the fixed D25 driver with bounded capture.

    A valid completed:false driver report returns normally. Only transport or
    protocol refusal raises D25CaseError with immutable metadata, never raw DATA.
    The original finite caller deadline also bounds startup, cleanup and return.
    """
    import copy
    import math
    import shutil
    import subprocess
    import threading
    import time

    started = time.monotonic()
    buffers = {'stdout': bytearray(), 'stderr': bytearray()}
    channels = {name: {'observed_bytes': 0, 'retained_bytes': 0, 'eof': False,
                       'overflow': False, 'io_error': None, 'closed': False,
                       'unknown_remainder': True} for name in buffers}
    facts = {'schema_version': 1, 'data_only': True, 'spawned': False, 'pid': None,
             'returncode': None, 'timed_out': False, 'kill_requested': False,
             'stdin_bytes': 0, 'stdin_closed': False, 'stdin_complete': False,
             'stdin_extent_unknown': False, 'stdin_write_attempted': False,
             'stdin_write_in_flight': False, 'threads_started': 0, 'reaped': False,
             'threads_joined': False, 'causes': [], 'node_version': None,
             'case': case if type(case) is str and case in _D25_CASES else None,
             'case_completed': None, 'case_cause': None, 'parent_observed_completion': False,
             'descendant_quiescence': 'UNKNOWN', 'input_bytes': None,
             'input_sha256': None, 'data_bytes': None, 'data_sha256': None,
             'report_bytes': None, 'report_sha256': None, 'checks_count': None,
             'measurements_count': None, 'environment_keys': [], 'program_sha256': None,
             'source_kind': 'd25_fixed_test_driver_v1', 'program_bytes': None,
             'driver_role': ('geometry' if geometry else 'codec') if type(geometry) is bool else None,
             'driver_getter': ('d25_geometry_driver_v1' if geometry else 'd25_node_driver_v1') if type(geometry) is bool else None}
    lock = threading.RLock()
    def cause(value):
        with lock:
            if value not in facts['causes']:
                facts['causes'].append(value)
    def has_causes():
        with lock:
            return bool(facts['causes'])
    def finish(report=None):
        # Capture related facts, channels, causes and byte prefixes at one shared
        # lock boundary. Later worker changes cannot mix these captured values.
        with lock:
            snapshot = copy.deepcopy(facts)
            captured_channels = {name: dict(channel) for name, channel in channels.items()}
            prefixes = {name: bytes(buffer) for name, buffer in buffers.items()}
        for name, channel in captured_channels.items():
            prefix = prefixes[name]
            snapshot[name] = {**channel, 'retained_bytes': len(prefix),
                              'prefix_sha256': hashlib.sha256(prefix).hexdigest(),
                              'unknown_remainder': not channel['eof'] or channel['overflow'] or channel['io_error'] is not None}
        observed = time.monotonic()
        snapshot['elapsed_seconds'] = observed - started
        snapshot['finished_before_deadline'] = observed < end if end is not None else False
        snapshot['child_completion_observed_before_deadline'] = (
            snapshot['spawned'] and child_total_end is not None and observed < child_total_end)
        if snapshot['spawned'] and not snapshot['child_completion_observed_before_deadline']:
            if 'child_completion_late' not in snapshot['causes']:
                snapshot['causes'].append('child_completion_late')
        if not snapshot['finished_before_deadline'] and 'parent_deadline' not in snapshot['causes']:
            snapshot['causes'].append('parent_deadline')
        if snapshot['spawned'] and observed >= cleanup_end:
            if 'cleanup_late' not in snapshot['causes']:
                snapshot['causes'].append('cleanup_late')
        snapshot['parent_observed_completion'] = report is not None and not snapshot['causes']
        encoded = canonical(snapshot)
        if len(encoded) > 32768:
            raise RuntimeError('D25 capture metadata bound')
        # Publication is immutable; the shared capture does not establish
        # continuous custody or quiescence of unjoined workers/descendants.
        frozen = json.loads(encoded)
        if frozen['causes']:
            raise D25CaseError(frozen)
        return report, frozen
    end = None
    child_total_end = None
    if type(deadline) not in (int, float):
        cause('deadline_invalid');return finish()
    try:
        end = float(deadline)
    except (OverflowError, ValueError):
        cause('deadline_invalid');return finish()
    if not math.isfinite(end):
        end = None;cause('deadline_invalid');return finish()
    if end - started > 300:
        cause('deadline_limit');return finish()
    if type(case) is not str or case not in _D25_CASES:
        cause('case_invalid');return finish()
    if type(geometry) is not bool or geometry != (case == 'geometry'):
        cause('geometry_invalid');return finish()
    if type(raw) is not bytes:
        cause('input_type');return finish()
    if len(raw) > 262144:
        cause('input_limit');return finish()
    if not raw.isascii():
        cause('input_ascii');return finish()
    if time.monotonic() >= end - 8:
        cause('deadline_no_window');return finish()
    try:
        def unique_input(rows):
            value = dict(rows)
            if len(value) != len(rows):
                raise ValueError('duplicate DATA field')
            return value
        def reject_constant(value):
            raise ValueError('nonfinite DATA')
        data = json.loads(raw, object_pairs_hook=unique_input, parse_constant=reject_constant)
        wire = canonical({'case': case, 'data': data})
        if len(wire) > 262144:
            cause('input_envelope_limit');return finish()
    except (ValueError, TypeError, RecursionError, OverflowError):
        cause('input_json');return finish()
    with lock:
        facts.update(data_bytes=len(raw), data_sha256=hashlib.sha256(raw).hexdigest(),
                     input_bytes=len(wire), input_sha256=hashlib.sha256(wire).hexdigest())
    raw = wire
    work_end = min(started + 27, end - 8)
    child_total_end = min(started + 30, end - 5)
    cleanup_end = min(child_total_end, work_end + 3)
    with lock:
        facts.update(started_monotonic=started, caller_deadline=end, work_deadline=work_end,
                     child_total_deadline=child_total_end, cleanup_deadline=cleanup_end, child_total_limit_seconds=30,
                     child_work_limit_seconds=27, cleanup_limit_seconds=3, final_reserve_seconds=5)
    if time.monotonic() >= work_end:
        cause('deadline_no_window');return finish()
    try:
        module = _d25_main_module_v1()
        program = module.d25_geometry_driver_v1() if geometry else module.d25_node_driver_v1()
    except Exception:
        cause('driver_source_error');return finish()
    if type(program) is not str:
        cause('driver_source_kind');return finish()
    if not 0 < len(program) <= 24576:
        cause('driver_source_limit');return finish()
    try:
        program_bytes = program.encode('ascii')
    except UnicodeEncodeError:
        cause('driver_source_ascii');return finish()
    # Hold one exact immutable source/argv buffer; DATA never selects a program.
    program = program_bytes.decode('ascii')
    with lock:
        facts.update(program_bytes=len(program_bytes), program_sha256=hashlib.sha256(program_bytes).hexdigest())
    node = shutil.which('node') or shutil.which('node.exe')
    if node is None:
        cause('node_unavailable');return finish()
    try:
        node = str(Path(node).resolve(strict=True))
        environment = {'PATH': str(Path(node).parent)}
        if os.name == 'nt':
            environment['SystemRoot'] = os.environ['SystemRoot']
        argv = [node, '--max-old-space-size=256', '--input-type=commonjs', '-e', program]
        if os.name == 'nt' and len(subprocess.list2cmdline(argv)) > 32767:
            cause('driver_command_limit');return finish()
        with lock:
            facts.update(node_executable=node, command_options=argv[1:4], environment_keys=sorted(environment))
        if time.monotonic() >= work_end:
            cause('deadline_before_spawn');return finish()
        process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, env=environment, bufsize=0,
                                   start_new_session=os.name != 'nt',
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, KeyError, ValueError) as error:
        cause('spawn_' + type(error).__name__);return finish()
    with lock:
        facts.update(spawned=True, pid=process.pid)
    if time.monotonic() >= work_end:
        with lock:
            facts['timed_out'] = True;cause('deadline_after_spawn')
    def read_channel(name, pipe, limit):
        channel = channels[name]
        try:
            while True:
                with lock:
                    read_size = min(4096, limit + 1 - len(buffers[name]))
                part = pipe.read(read_size)
                with lock:
                    if type(part) is not bytes:
                        channel['io_error'] = 'invalid_read';cause(name + '_read_error');break
                    if part == b'':
                        channel['eof'] = True;break
                    channel['observed_bytes'] += len(part)
                    room = limit - len(buffers[name])
                    buffers[name].extend(part[:room])
                    if len(part) > room:
                        channel['overflow'] = True;cause(name + '_overflow');break
        except (OSError, ValueError) as error:
            with lock:
                channel['io_error'] = type(error).__name__;cause(name + '_read_error')
        finally:
            try:
                pipe.close()
                with lock:
                    channel['closed'] = True
            except (OSError, ValueError):
                cause(name + '_close_error')
    def write_input():
        try:
            while True:
                with lock:
                    offset = facts['stdin_bytes']
                    if offset >= len(raw):
                        break
                    if time.monotonic() >= work_end:
                        cause('stdin_deadline');break
                    remaining = len(raw) - offset
                    facts.update(stdin_write_attempted=True, stdin_write_in_flight=True,
                                 stdin_extent_unknown=True)
                count = process.stdin.write(raw[offset:])
                with lock:
                    facts['stdin_write_in_flight'] = False
                    if type(count) is not int or not 0 < count <= remaining:
                        cause('stdin_short_write');break
                    facts['stdin_bytes'] += count
                    facts['stdin_extent_unknown'] = False
                if time.monotonic() >= work_end:
                    cause('stdin_deadline');break
            with lock:
                facts['stdin_complete'] = (facts['stdin_bytes'] == len(raw)
                                           and not facts['stdin_extent_unknown'])
        except (OSError, ValueError):
            with lock:
                facts.update(stdin_write_in_flight=False, stdin_extent_unknown=True)
                cause('stdin_write_error')
        finally:
            try:
                process.stdin.close()
                with lock:
                    facts['stdin_closed'] = True
            except (OSError, ValueError):
                cause('stdin_close_error')
    threads = [threading.Thread(target=read_channel, args=('stdout', process.stdout, 1048576), daemon=True),
               threading.Thread(target=read_channel, args=('stderr', process.stderr, 16384), daemon=True),
               threading.Thread(target=write_input, daemon=True)]
    started_threads = []
    for thread in threads:
        if has_causes():
            break
        if time.monotonic() >= work_end:
            with lock:
                facts['timed_out'] = True;cause('worker_start_deadline')
            break
        try:
            thread.start()
            started_threads.append(thread)
            if time.monotonic() >= work_end:
                with lock:
                    facts['timed_out'] = True;cause('worker_start_late')
                break
        except RuntimeError:
            if thread.ident is not None:
                started_threads.append(thread)
            cause('thread_start_error');break
    with lock:
        facts['threads_started'] = len(started_threads)
    def status():
        try:
            return process.poll()
        except (OSError, ValueError):
            cause('child_status_error');return None
    while True:
        if time.monotonic() >= work_end:
            with lock:
                facts['timed_out'] = True;cause('child_timeout')
            break
        if has_causes() or (status() is not None and all(not thread.is_alive() for thread in started_threads)):
            break
        time.sleep(min(.005, max(0, work_end - time.monotonic())))
    cleanup_end = min(cleanup_end, time.monotonic() + 3)
    with lock:
        facts['cleanup_deadline'] = cleanup_end
    if status() is None:
        with lock:
            facts['kill_requested'] = True
        try:
            process.kill()
        except OSError:
            cause('child_kill_error')
    for thread, pipe, name in zip(threads, (process.stdout, process.stderr, process.stdin), ('stdout', 'stderr', 'stdin')):
        if thread not in started_threads:
            try:
                pipe.close()
                with lock:
                    if name == 'stdin':
                        facts['stdin_closed'] = True
                    else:
                        channels[name]['closed'] = True
            except (OSError, ValueError):
                cause(name + '_unstarted_close_error')
    try:
        returned = process.wait(timeout=max(0, cleanup_end - time.monotonic()))
        with lock:
            facts['reaped'] = type(returned) is int
            if not facts['reaped']:
                cause('child_reap_unknown')
    except (OSError, ValueError, subprocess.TimeoutExpired):
        cause('child_reap_unknown')
    for thread in started_threads:
        try:
            thread.join(max(0, cleanup_end - time.monotonic()))
        except RuntimeError:
            cause('thread_join_error')
    returned_status = status()
    joined = len(started_threads) == len(threads) and all(not thread.is_alive() for thread in started_threads)
    with lock:
        facts.update(returncode=returned_status, threads_joined=joined)
        if not facts['threads_joined']:
            cause('pipe_completion_unknown')
        if type(facts['returncode']) is not int or facts['returncode'] != 0:
            cause('child_status')
        if facts['kill_requested']:
            cause('child_forced')
        if not facts['stdin_complete'] or not facts['stdin_closed'] or not all(c['eof'] for c in channels.values()):
            cause('io_completion_unknown')
        stdout_data, stderr_data = bytes(buffers['stdout']), bytes(buffers['stderr'])
    if has_causes():
        return finish()
    if stderr_data:
        cause('unexpected_stderr');return finish()
    try:
        if len(stdout_data) > 32768 or not stdout_data.isascii():
            raise ValueError('report extent')
        def unique_pairs(rows):
            result = dict(rows)
            if len(result) != len(rows):
                raise ValueError('duplicate report field')
            return result
        result = json.loads(stdout_data, object_pairs_hook=unique_pairs, parse_constant=reject_constant)
        if (type(result) is not dict or set(result) != {'schema_version', 'case', 'node_version',
                'completed', 'cause', 'checks', 'measurements'}
                or type(result['schema_version']) is not int or result['schema_version'] != 1
                or result['case'] != case or type(result['case']) is not str
                or result['node_version'] != '25.2.1' or type(result['completed']) is not bool
                or result['cause'] is not None and (type(result['cause']) is not str
                    or result['cause'] not in _D25_DRIVER_CAUSES and not (geometry
                        and case == 'geometry' and result['cause'] == 'd25_geometry_hold'))
                or type(result['checks']) is not list or len(result['checks']) > 512
                or type(result['measurements']) is not list or len(result['measurements']) > 128):
            raise ValueError('report shape')
        import re
        def identifier(value):
            return type(value) is str and re.fullmatch(r'[A-Za-z0-9_]{1,64}', value) is not None
        for item in result['checks']:
            if (type(item) is not dict or set(item) != {'id', 'ok'}
                    or not identifier(item['id']) or type(item['ok']) is not bool):
                raise ValueError('report check')
        for item in result['measurements']:
            if (type(item) is not dict or set(item) != {'id', 'size_bytes', 'sha256'}
                    or not identifier(item['id']) or type(item['size_bytes']) is not int
                    or not 0 <= item['size_bytes'] <= 262144
                    or type(item['sha256']) is not str
                    or re.fullmatch(r'[0-9a-f]{64}', item['sha256']) is None):
                raise ValueError('report measurement')
    except (ValueError, TypeError, RecursionError, OverflowError):
        cause('child_protocol');return finish()
    with lock:
        facts.update(node_version=result['node_version'], case_completed=result['completed'],
                     case_cause=result['cause'], report_bytes=len(stdout_data),
                     report_sha256=hashlib.sha256(stdout_data).hexdigest(),
                     checks_count=len(result['checks']), measurements_count=len(result['measurements']))
    return finish(result)



def d25_run_case_v1(case, raw, deadline):
    """Use the original fixed codec DATA driver; input never selects a program."""
    return _d25_run_fixed_driver_v1(case, raw, deadline, False)



def d25_run_geometry_v1(raw, deadline):
    """Use only the separate fixed geometry DATA driver, with no source execution."""
    return _d25_run_fixed_driver_v1('geometry', raw, deadline, True)

# Full bounded original metadata DATA from the ONE consumed D25 risk.
# This constant does not execute or reconstruct any operational subject.
_D25_GEOMETRY_RETAINED_RESULT_V1 = b'{"actual_entry":{"path_basename":"vast-d25-geometry-local-driver-20261018-02.py","sha256":"d9ba5c51229b8ba50e33d10c46a7246392bfc75b939d03fcdb28a472bedc760a","size_bytes":73759},"disposition":"INCOMPLETE_WIRE_REFUSAL","expected":{"check_count":49,"check_rows":[{"id":"source_bindings","ok":true},{"id":"initial_source_bound","ok":true},{"id":"finalizer_source_bound","ok":true},{"id":"executor_source_bound","ok":true},{"id":"six_setup_forms","ok":true},{"id":"success_setup","ok":true},{"id":"success_provider_pipes","ok":true},{"id":"success_pipe0_inverse","ok":true},{"id":"success_pipe1_inverse","ok":true},{"id":"success_pipe2_inverse","ok":true},{"id":"success_selected_original_bound","ok":true},{"id":"success_wire_geometry","ok":false},{"id":"structured_failure_setup","ok":true},{"id":"structured_failure_provider_pipes","ok":true},{"id":"structured_failure_pipe0_inverse","ok":true},{"id":"structured_failure_pipe1_inverse","ok":true},{"id":"structured_failure_pipe2_inverse","ok":true},{"id":"structured_failure_selected_original_bound","ok":true},{"id":"structured_failure_wire_geometry","ok":false},{"id":"unicode_failure_setup","ok":true},{"id":"unicode_failure_provider_pipes","ok":true},{"id":"unicode_failure_pipe0_inverse","ok":true},{"id":"unicode_failure_pipe1_inverse","ok":true},{"id":"unicode_failure_pipe2_inverse","ok":true},{"id":"unicode_failure_selected_original_bound","ok":true},{"id":"unicode_failure_wire_geometry","ok":false},{"id":"partial_emission_setup","ok":true},{"id":"partial_emission_provider_pipes","ok":true},{"id":"partial_emission_pipe0_inverse","ok":true},{"id":"partial_emission_pipe1_inverse","ok":true},{"id":"partial_emission_pipe2_inverse","ok":true},{"id":"partial_emission_selected_original_bound","ok":true},{"id":"partial_emission_wire_geometry","ok":false},{"id":"unknown_closure_setup","ok":true},{"id":"unknown_closure_provider_pipes","ok":true},{"id":"unknown_closure_pipe0_inverse","ok":true},{"id":"unknown_closure_pipe1_inverse","ok":true},{"id":"unknown_closure_pipe2_inverse","ok":true},{"id":"unknown_closure_selected_original_bound","ok":true},{"id":"unknown_closure_wire_geometry","ok":false},{"id":"setup_refusal_setup","ok":true},{"id":"setup_refusal_provider_pipes","ok":true},{"id":"setup_refusal_pipe0_inverse","ok":true},{"id":"setup_refusal_pipe1_inverse","ok":true},{"id":"setup_refusal_pipe2_inverse","ok":true},{"id":"setup_refusal_selected_original_bound","ok":true},{"id":"setup_refusal_wire_geometry","ok":false},{"id":"six_later_forms","ok":true},{"id":"later_measured_upstream","ok":false}],"false_check_ids":["later_measured_upstream","partial_emission_wire_geometry","setup_refusal_wire_geometry","structured_failure_wire_geometry","success_wire_geometry","unicode_failure_wire_geometry","unknown_closure_wire_geometry"],"geometry_fully_measured":false,"geometry_risk_passed":false,"measurement_count":15,"measurement_rows":[{"id":"initial_source","sha256":"4032a534147aada87931734f3b06cde67988d62c75851b959945399843a3770d","size_bytes":14162},{"id":"finalizer_source","sha256":"fcca4065d75430e87e6f8e1f4df3be68bd084421da0ca7266218a5f801e8eb1a","size_bytes":34397},{"id":"executor_source","sha256":"9104621cfe1b7e0931f1dca52ecf216c4f2874233803abcff621db1b9077ae45","size_bytes":78392},{"id":"success_selected_original","sha256":"46fdb4a08fc1898e57d6c2b942a28aebdebe49b1f4b5bbe11c44177f2cce628e","size_bytes":17067},{"id":"success_wire_refusal","sha256":"17f54ba84e38766575c165a616f7755840343aa043663bd0f9f2f833393831a6","size_bytes":19},{"id":"structured_failure_selected_original","sha256":"e8cf9b26009ff462152eff45d59343793f7ee5216f1e6f00197b6256ec0d310c","size_bytes":17293},{"id":"structured_failure_wire_refusal","sha256":"17f54ba84e38766575c165a616f7755840343aa043663bd0f9f2f833393831a6","size_bytes":19},{"id":"unicode_failure_selected_original","sha256":"84e2bf9ea93cf982623ef86d9eeb398f4e468eb80656efdf57f206541b55d563","size_bytes":17193},{"id":"unicode_failure_wire_refusal","sha256":"17f54ba84e38766575c165a616f7755840343aa043663bd0f9f2f833393831a6","size_bytes":19},{"id":"partial_emission_selected_original","sha256":"79ea8cf1b2d66bc2431f4175baabd65338946aff50e3b104d64ce986f8087297","size_bytes":16786},{"id":"partial_emission_wire_refusal","sha256":"17f54ba84e38766575c165a616f7755840343aa043663bd0f9f2f833393831a6","size_bytes":19},{"id":"unknown_closure_selected_original","sha256":"628eaa305921b541a5502e476b5c6d3ad4dbf5d452625a8ca547de7b1e1afff4","size_bytes":17071},{"id":"unknown_closure_wire_refusal","sha256":"17f54ba84e38766575c165a616f7755840343aa043663bd0f9f2f833393831a6","size_bytes":19},{"id":"setup_refusal_selected_original","sha256":"6beffafc4f5629b627f40ace16448fea4ca0e16e57cea746c602759262e53429","size_bytes":16147},{"id":"setup_refusal_wire_refusal","sha256":"17f54ba84e38766575c165a616f7755840343aa043663bd0f9f2f833393831a6","size_bytes":19}],"missing_always_required_check_ids":["C1_failure_later","C1_failure_native_input_bound","C1_failure_pipe0_inverse","C1_failure_pipe1_inverse","C1_failure_pipe_limits","C1_failure_selected_bound","C1_success_later","C1_success_native_input_bound","C1_success_pipe0_inverse","C1_success_pipe1_inverse","C1_success_pipe_limits","C1_success_selected_bound","C6_failure_later","C6_failure_native_input_bound","C6_failure_pipe0_inverse","C6_failure_pipe1_inverse","C6_failure_pipe_limits","C6_failure_selected_bound","C6_success_later","C6_success_native_input_bound","C6_success_pipe0_inverse","C6_success_pipe1_inverse","C6_success_pipe_limits","C6_success_selected_bound","D_failure_later","D_failure_native_input_bound","D_failure_pipe0_inverse","D_failure_pipe1_inverse","D_failure_pipe_limits","D_failure_selected_bound","D_success_later","D_success_native_input_bound","D_success_pipe0_inverse","D_success_pipe1_inverse","D_success_pipe_limits","D_success_selected_bound","approval_slots","partial_emission_ack_bound","partial_emission_chain_bound","partial_emission_chain_join","partial_emission_forms_bound","partial_emission_full_roundtrip","partial_emission_observed_original_bound","partial_emission_observed_wire_bound","partial_emission_root_bound","partial_emission_selected_wire_bound","partial_emission_uint64","partial_emission_writer_input_bound","partial_emission_writer_pipe0_inverse","partial_emission_writer_pipe1_inverse","partial_emission_writer_stdout_bound","setup_refusal_ack_bound","setup_refusal_chain_bound","setup_refusal_chain_join","setup_refusal_forms_bound","setup_refusal_full_roundtrip","setup_refusal_observed_original_bound","setup_refusal_observed_wire_bound","setup_refusal_root_bound","setup_refusal_selected_wire_bound","setup_refusal_uint64","setup_refusal_writer_input_bound","setup_refusal_writer_pipe0_inverse","setup_refusal_writer_pipe1_inverse","setup_refusal_writer_stdout_bound","structured_failure_ack_bound","structured_failure_chain_bound","structured_failure_chain_join","structured_failure_forms_bound","structured_failure_full_roundtrip","structured_failure_observed_original_bound","structured_failure_observed_wire_bound","structured_failure_root_bound","structured_failure_selected_wire_bound","structured_failure_uint64","structured_failure_writer_input_bound","structured_failure_writer_pipe0_inverse","structured_failure_writer_pipe1_inverse","structured_failure_writer_stdout_bound","success_ack_bound","success_chain_bound","success_chain_join","success_forms_bound","success_full_roundtrip","success_observed_original_bound","success_observed_wire_bound","success_root_bound","success_selected_wire_bound","success_uint64","success_writer_input_bound","success_writer_pipe0_inverse","success_writer_pipe1_inverse","success_writer_stdout_bound","unicode_failure_ack_bound","unicode_failure_chain_bound","unicode_failure_chain_join","unicode_failure_forms_bound","unicode_failure_full_roundtrip","unicode_failure_observed_original_bound","unicode_failure_observed_wire_bound","unicode_failure_root_bound","unicode_failure_selected_wire_bound","unicode_failure_uint64","unicode_failure_writer_input_bound","unicode_failure_writer_pipe0_inverse","unicode_failure_writer_pipe1_inverse","unicode_failure_writer_stdout_bound","unknown_closure_ack_bound","unknown_closure_chain_bound","unknown_closure_chain_join","unknown_closure_forms_bound","unknown_closure_full_roundtrip","unknown_closure_observed_original_bound","unknown_closure_observed_wire_bound","unknown_closure_root_bound","unknown_closure_selected_wire_bound","unknown_closure_uint64","unknown_closure_writer_input_bound","unknown_closure_writer_pipe0_inverse","unknown_closure_writer_pipe1_inverse","unknown_closure_writer_stdout_bound"],"missing_always_required_measurement_ids":["C1_failure_native_input","C1_failure_selected","C1_success_native_input","C1_success_selected","C6_failure_native_input","C6_failure_selected","C6_success_native_input","C6_success_selected","D_failure_native_input","D_failure_selected","D_success_native_input","D_success_selected","partial_emission_ack","partial_emission_chain","partial_emission_observed_original","partial_emission_observed_wire","partial_emission_root","partial_emission_selected_wire","partial_emission_writer_stdout","setup_refusal_ack","setup_refusal_chain","setup_refusal_observed_original","setup_refusal_observed_wire","setup_refusal_root","setup_refusal_selected_wire","setup_refusal_writer_stdout","structured_failure_ack","structured_failure_chain","structured_failure_observed_original","structured_failure_observed_wire","structured_failure_root","structured_failure_selected_wire","structured_failure_writer_stdout","success_ack","success_chain","success_observed_original","success_observed_wire","success_root","success_selected_wire","success_writer_stdout","unicode_failure_ack","unicode_failure_chain","unicode_failure_observed_original","unicode_failure_observed_wire","unicode_failure_root","unicode_failure_selected_wire","unicode_failure_writer_stdout","unknown_closure_ack","unknown_closure_chain","unknown_closure_observed_original","unknown_closure_observed_wire","unknown_closure_root","unknown_closure_selected_wire","unknown_closure_writer_stdout"],"unavailable_conditional_later_groups":["C1_success","C1_failure","C6_success","C6_failure","D_success","D_failure"]},"external_formatter_fixture_pins":[{"path":"tests/fixtures/accepted_policy_fixture_compiler_component_v1.py","sha256":"329fb13f2c6dcee0872e5a29ec1fd769dc6e57ce92ee1076fef6737f1da86d88","size_bytes":32732},{"path":"tests/fixtures/accepted_policy_fixture_compiler_gate2_resume_v1.py","sha256":"5fd7d2d6ee62ff584d2a4662757ca804a3d3300d30bb966319901870c4c85670","size_bytes":32739},{"path":"tests/fixtures/accepted_policy_fixture_compiler_gate2_c_v1.py","sha256":"5a6c4b08ce3d381c355cbf72f93057c991b4adcb9d6ca8c43a638acd64f2ecf9","size_bytes":130783},{"path":"tests/fixtures/accepted_policy_fixture_compiler_v1.py","sha256":"1e40d4786fd03543ac43df7fe0e42a4349d55bad9288ead28f5d2a6ad87bcb03","size_bytes":103925}],"kind":"d25_retained_geometry_negative_v1","limits":["Retained negative regression only; never builds, invokes, imports, parses as JS or replays any generated operational subject or geometry.","Source-file pins identify actual consumed risk inputs; current contributor correspondence is not whole-current-file runtime custody.","All missing dimensions remain absent/unknown; a passing regression cannot admit phases, images, native/physical gates, task closure or merge."],"original_development_class":{"end_line":5249,"method_AST_sha256":"2b73adc3d1cd77a7d611508bc6c7d319c6fb0d415a5a94957e325ce698e15ace","method_sha256":"b71dc65d7c4eb984c474f79d1afb23c010c6f8ef387ec5830aae73ec608eedf9","method_size_bytes":10836,"path":"tests/test_accepted_policy_fixture_compiler_gate2_resume_v1.py","sha256":"c804e88a9d5c405ecd66432219fe70e54b33a71c8367b5409df15697aedf9a5d","size_bytes":10891,"source_utf8":"class D25CompleteGeometryTests(unittest.TestCase):\\n    def test_complete_form_bounds_preserve_hold(self):\\n        import time\\n        import io\\n        import sys\\n        from unittest import mock\\n        from tests.test_accepted_policy_fixture_compiler_gate2_resume_caller_v1 import d25_run_geometry_v1\\n        from tests import test_accepted_policy_fixture_compiler_gate2_resume_caller_v1 as caller\\n\\n        deadline = globals().get(\'D25_TEST_DEADLINE\', time.monotonic() + 295)\\n        try:\\n            module = sys.modules[__name__]\\n            with mock.patch.object(module, \'d24_phase_initial_v1\') as phase, mock.patch.object(Path, \'open\', side_effect=AssertionError(\'d24_unexpected_fixture_read\')) as opened:\\n                with self.assertRaisesRegex(RuntimeError, \'d25_construction_deadline\'):\\n                    d25_inert_bundle_v1(time.monotonic() - 1)\\n                phase.assert_not_called()\\n                opened.assert_not_called()\\n            with mock.patch.object(module, \'D25_WIRE_CODEC\', D25_WIRE_CODEC + \' \'), mock.patch.object(module, \'d24_phase_initial_v1\') as phase, mock.patch.object(Path, \'open\', side_effect=AssertionError(\'d24_unexpected_fixture_read\')) as opened:\\n                with self.assertRaises(RuntimeError):\\n                    d25_inert_bundle_v1(deadline)\\n                phase.assert_not_called()\\n                opened.assert_not_called()\\n            with mock.patch.object(module, \'D22_PREFIX\', \'x\' + D22_PREFIX[1:]), mock.patch.object(Path, \'open\', side_effect=AssertionError(\'d24_unexpected_fixture_read\')) as opened, mock.patch.object(caller, \'d22_compress_data_v1\', side_effect=AssertionError(\'d24_unexpected_compression\')) as compressed:\\n                with self.assertRaisesRegex(RuntimeError, \'d24_prefix_binding\'):\\n                    d24_phase_initial_v1(deadline)\\n                opened.assert_not_called()\\n                compressed.assert_not_called()\\n            with mock.patch.object(Path, \'open\', return_value=io.BytesIO(b\'invalid\')), mock.patch.object(module, \'d24_phase_initial_v1\') as phase:\\n                with self.assertRaisesRegex(RuntimeError, \'d25_fixture_binding\'):\\n                    d25_inert_bundle_v1(deadline)\\n                phase.assert_not_called()\\n            raw, facts = d25_inert_bundle_v1(deadline)\\n            self.assertEqual(facts[\'initial\'][\'data_fields\'], 9)\\n            self.assertTrue(facts[\'initial\'][\'strings_field_absent\'])\\n            for name in (\'exact_decoder_inverse\', \'exact_phase_inverse\', \'exact_inverse_source\'):\\n                self.assertIs(facts[\'initial\'][name], True)\\n            self.assertEqual((facts[\'node_codec\'][\'node_codec_bytes\'], facts[\'node_codec\'][\'node_codec_sha256\']), D25_CODEC_SOURCE_PINS[1])\\n            self.assertIs(facts[\'node_codec\'][\'role_is_exact_prefix\'], True)\\n            self.assertIs(facts[\'node_codec\'][\'encoder_excluded\'], True)\\n        except Exception as error:\\n            message = str(error).encode(\'utf-8\', \'backslashreplace\')\\n            retained = getattr(error, \'metadata\', None)\\n            retained_bytes = json.dumps(retained, sort_keys=True, separators=(\',\', \':\')).encode(\'ascii\')\\n            failure = {\'kind\': \'d25_construction_failure_metadata_v1\',\\n                       \'error_type\': type(error).__name__,\\n                       \'message_size_bytes\': len(message),\\n                       \'message_sha256\': hashlib.sha256(message).hexdigest(),\\n                       \'capture\': retained if len(retained_bytes) <= 30000 else None,\\n                       \'capture_metadata_unavailable\': retained is None or len(retained_bytes) > 30000,\\n                       \'capture_metadata_size_bytes\': len(retained_bytes),\\n                       \'capture_metadata_sha256\': hashlib.sha256(retained_bytes).hexdigest(),\\n                       \'generated_operational_program_execution\': False,\\n                       \'generated_full_subject_files_written\': False,\\n                       \'physical_acceptance\': False}\\n            encoded = json.dumps(failure, sort_keys=True, separators=(\',\', \':\'))\\n            self.assertLessEqual(len((\'D25_GEOMETRY_SOURCE_METADATA \' + encoded + \'\\\\n\').encode(\'ascii\')), 32768)\\n            print(\'D25_GEOMETRY_SOURCE_METADATA\', encoded)\\n            raise\\n        source_metadata = json.dumps(facts, sort_keys=True, separators=(\',\', \':\'))\\n        self.assertLessEqual(len((\'D25_GEOMETRY_SOURCE_METADATA \' + source_metadata + \'\\\\n\').encode(\'ascii\')), 32768)\\n        print(\'D25_GEOMETRY_SOURCE_METADATA\', source_metadata)\\n        value, capture = d25_run_geometry_v1(raw, deadline)\\n        metadata = json.dumps({\'case\': \'geometry\', \'report\': value, \'capture\': capture},\\n                              sort_keys=True, separators=(\',\', \':\'))\\n        self.assertLessEqual(len((\'D25_CASE_METADATA \' + metadata + \'\\\\n\').encode(\'ascii\')), 32768)\\n        print(\'D25_CASE_METADATA\', metadata)\\n        self.assertTrue(capture[\'parent_observed_completion\'])\\n        self.assertFalse(facts[\'generated_operational_program_execution\'])\\n        self.assertFalse(facts[\'generated_full_subject_files_written\'])\\n        self.assertFalse(facts[\'behavior_conformance_complete\'])\\n        self.assertFalse(facts[\'physical_acceptance\'])\\n        self.assertEqual(facts[\'modeled_setup_form_count\'], 6)\\n        self.assertEqual(facts[\'modeled_later_form_count\'], 6)\\n        self.assertEqual(capture[\'descendant_quiescence\'], \'UNKNOWN\')\\n        self.assertEqual(set(facts[\'driver\']), {\'source_kind\', \'driver_role\', \'driver_getter\',\\n                                              \'program_bytes\', \'program_sha256\'})\\n        for key in facts[\'driver\']:\\n            self.assertEqual(capture[key], facts[\'driver\'][key])\\n        actual_program = d25_geometry_driver_v1().encode(\'ascii\')\\n        self.assertEqual((facts[\'driver\'][\'program_bytes\'], facts[\'driver\'][\'program_sha256\']),\\n                         (len(actual_program), hashlib.sha256(actual_program).hexdigest()))\\n        measurements = {row[\'id\']: row for row in value[\'measurements\']}\\n        self.assertEqual(len(measurements), len(value[\'measurements\']))\\n        checks = {row[\'id\']: row[\'ok\'] for row in value[\'checks\']}\\n        self.assertEqual(len(checks), len(value[\'checks\']))\\n        self.assertTrue(checks)\\n        for row in value[\'measurements\']:\\n            self.assertGreater(row[\'size_bytes\'], 0)\\n            self.assertRegex(row[\'sha256\'], r\'^[0-9a-f]{64}$\')\\n        caps = {name: 262144 for name in (\'initial_source\', \'finalizer_source\', \'executor_source\')}\\n        required = {\'source_bindings\', \'six_setup_forms\', \'six_later_forms\',\\n                    \'approval_slots\', \'later_measured_upstream\'}\\n        setup_forms = (\'success\', \'structured_failure\', \'unicode_failure\', \'partial_emission\',\\n                       \'unknown_closure\', \'setup_refusal\')\\n        later_forms = (\'C1_success\', \'C1_failure\', \'C6_success\', \'C6_failure\', \'D_success\', \'D_failure\')\\n        for prefix in setup_forms:\\n            required.update(prefix + suffix for suffix in (\\n                \'_setup\', \'_provider_pipes\', \'_pipe0_inverse\', \'_pipe1_inverse\', \'_pipe2_inverse\',\\n                \'_full_roundtrip\', \'_uint64\', \'_writer_pipe0_inverse\', \'_writer_pipe1_inverse\',\\n                \'_chain_join\'))\\n            for suffix, cap in ((\'selected_original\', 32768), (\'observed_original\', 32768),\\n                                (\'selected_wire\', 12288), (\'observed_wire\', 12288),\\n                                (\'ack\', 24576), (\'writer_stdout\', 2112),\\n                                (\'root\', 65536), (\'chain\', 262144)):\\n                caps[prefix + \'_\' + suffix] = cap\\n        for stage in later_forms:\\n            caps[stage + \'_selected\'] = 4096\\n            caps[stage + \'_native_input\'] = 32768\\n            required.update(stage + suffix for suffix in (\\n                \'_later\', \'_pipe_limits\', \'_pipe0_inverse\', \'_pipe1_inverse\'))\\n            self.assertIn(stage + \'_selected\', measurements)\\n            if measurements[stage + \'_selected\'][\'size_bytes\'] <= 4096:\\n                caps[stage + \'_ack\'] = 16384\\n                caps[stage + \'_writer_stdout\'] = 2112\\n                required.update(stage + suffix for suffix in (\\n                    \'_uint64\', \'_writer_pipe0_inverse\', \'_writer_pipe1_inverse\'))\\n        self.assertEqual(set(measurements), set(caps))\\n        for name, cap in caps.items():\\n            self.assertIn(name + \'_bound\', checks)\\n            self.assertIs(checks[name + \'_bound\'], measurements[name][\'size_bytes\'] <= cap)\\n        required.update(name + \'_bound\' for name in caps)\\n        for prefix in setup_forms:\\n            selected_size = measurements[prefix + \'_selected_wire\'][\'size_bytes\']\\n            rounded = ((selected_size + 4095) // 4096) * 4096\\n            expected = {\\n                prefix + \'_writer_input_bound\': measurements[prefix + \'_ack\'][\'size_bytes\'] + 65471 <= 90112,\\n                prefix + \'_forms_bound\': max(12288, rounded) + rounded + 8192 <= 32768}\\n            for name, ok in expected.items():\\n                self.assertIn(name, checks)\\n                self.assertIs(checks[name], ok)\\n            required.update(expected)\\n        for stage in later_forms:\\n            selected_size = measurements[stage + \'_selected\'][\'size_bytes\']\\n            if selected_size <= 4096:\\n                rounded = ((selected_size + 4095) // 4096) * 4096\\n                expected = {\\n                    stage + \'_writer_input_bound\': measurements[stage + \'_ack\'][\'size_bytes\'] + 65471 <= 81920,\\n                    stage + \'_writer_forms_bound\': max(4096, rounded) + rounded + 8192 <= 16384}\\n                for name, ok in expected.items():\\n                    self.assertIn(name, checks)\\n                    self.assertIs(checks[name], ok)\\n                required.update(expected)\\n        self.assertEqual(set(checks), required)\\n        source_pins = (\\n            (\'initial_source\', facts[\'initial\'][\'source_bytes\'], facts[\'initial\'][\'source_sha256\']),\\n            (\'finalizer_source\', facts[\'finalizer\'][\'finalizer_size_bytes\'], facts[\'finalizer\'][\'finalizer_sha256\']),\\n            (\'executor_source\', facts[\'executor\'][\'size_bytes\'], facts[\'executor\'][\'sha256\']))\\n        for name, size, sha in source_pins:\\n            self.assertEqual(measurements[name][\'size_bytes\'], size)\\n            self.assertEqual(measurements[name][\'sha256\'], sha)\\n        if all(checks.values()):\\n            self.assertTrue(value[\'completed\'])\\n            self.assertIsNone(value[\'cause\'])\\n        else:\\n            # A fully measured bound-only HOLD preserves the negative risk\\n            # result. Missing mandatory evidence fails before reaching here.\\n            self.assertFalse(value[\'completed\'])\\n            self.assertEqual(value[\'cause\'], \'d25_geometry_hold\')\\n            self.assertTrue(any(not ok and name.endswith(\'_bound\') for name, ok in checks.items()))\\n            self.assertTrue(all(ok or name.endswith(\'_bound\') for name, ok in checks.items()))","start_line":5090},"originals":[{"bytes_ascii":"{\\"both_buffers_verified_before_either_compile\\":true,\\"codec_role\\":{\\"encoder_excluded\\":true,\\"excluded_encoder_bytes\\":2964,\\"excluded_encoder_sha256\\":\\"6123f11ab75ed5a4021dc038ff878cd6873d71492058e8b887d3b3c28b4fc295\\",\\"full_codec_bytes\\":6903,\\"full_codec_sha256\\":\\"c65b73fe0e7d274040dda413b7871ee83c4c952f9bb2c1e74962b0e3e5f34767\\",\\"kind\\":\\"d25_node_codec_role_v1\\",\\"marker_occurrences\\":1,\\"node_codec_bytes\\":3939,\\"node_codec_sha256\\":\\"d7f478ee3e5ff65d7146c58e2a9fa078e66219cc1e35ea8547701e576295c32d\\",\\"role_is_exact_prefix\\":true},\\"event\\":\\"source_bindings\\",\\"execution_reopens_test_paths\\":false,\\"fixed_driver\\":{\\"driver_getter\\":\\"d25_geometry_driver_v1\\",\\"driver_role\\":\\"geometry\\",\\"program_bytes\\":24572,\\"program_sha256\\":\\"f3bce3947d93f0a9d630372bd1b0d4d02fe61ecd1e47458259f3a8ccdad72265\\",\\"source_kind\\":\\"d25_fixed_test_driver_v1\\"},\\"held_caller_aliases_bound\\":true,\\"held_driver_aliases_bound\\":true,\\"held_driver_loader_bound\\":true,\\"held_driver_module\\":\\"tests.test_accepted_policy_fixture_compiler_gate2_resume_v1\\",\\"sources\\":[{\\"path\\":\\"tests/test_accepted_policy_fixture_compiler_gate2_resume_v1.py\\",\\"sha256\\":\\"3dcea0ea515be7c33cd95486adf9b818b63ce39894d9cbe48c8318ec4fd02b39\\",\\"size_bytes\\":476378},{\\"path\\":\\"tests/test_accepted_policy_fixture_compiler_gate2_resume_caller_v1.py\\",\\"sha256\\":\\"77946ffadc24d7fd3759186417eb5ae330edd306f7a3170d5370f7e44b4e61b4\\",\\"size_bytes\\":281307}]}\\n{\\"event\\":\\"test_started\\",\\"test_id\\":\\"tests.test_accepted_policy_fixture_compiler_gate2_resume_v1.D25CompleteGeometryTests.test_complete_form_bounds_preserve_hold\\"}\\nD25_GEOMETRY_SOURCE_METADATA {\\"behavior_conformance_complete\\":false,\\"controlled_synthetic_geometry_only\\":true,\\"driver\\":{\\"driver_getter\\":\\"d25_geometry_driver_v1\\",\\"driver_role\\":\\"geometry\\",\\"program_bytes\\":24572,\\"program_sha256\\":\\"f3bce3947d93f0a9d630372bd1b0d4d02fe61ecd1e47458259f3a8ccdad72265\\",\\"source_kind\\":\\"d25_fixed_test_driver_v1\\"},\\"executor\\":{\\"sha256\\":\\"9104621cfe1b7e0931f1dca52ecf216c4f2874233803abcff621db1b9077ae45\\",\\"size_bytes\\":78392},\\"finalizer\\":{\\"factory_sha256\\":\\"997579f8ffcc50d6e05ae859dd9164b1dc08ce5a71e82a1d8070633c3cdf3677\\",\\"factory_size_bytes\\":13073,\\"finalizer_sha256\\":\\"fcca4065d75430e87e6f8e1f4df3be68bd084421da0ca7266218a5f801e8eb1a\\",\\"finalizer_size_bytes\\":34397,\\"generated_full_subject_files_written\\":false,\\"generated_operational_program_execution\\":false,\\"initial_sha256\\":\\"4032a534147aada87931734f3b06cde67988d62c75851b959945399843a3770d\\",\\"initial_size_bytes\\":14162,\\"python_common_sha256\\":\\"f56a723316fd5e1d21b7425320959977703cedf4b82dae3511cb28d6f1c1d0a8\\",\\"python_common_size_bytes\\":3674,\\"python_head_sha256\\":\\"3ced26dc51155909cd4cd8fbd441db7145dd0241cd0b2bd4de29a10a6cc3efc7\\",\\"python_head_size_bytes\\":314,\\"python_tail_sha256\\":\\"fe7e134bb04da2e1c994c9cd2e788ace8b9003f4f567b65a46b6382fa3d655e3\\",\\"python_tail_size_bytes\\":1544,\\"wrapper_prefix_size_bytes\\":32,\\"wrapper_suffix_size_bytes\\":2},\\"generated_full_subject_files_written\\":false,\\"generated_operational_program_execution\\":false,\\"independent_actual_acquisition_proven\\":false,\\"initial\\":{\\"base64_data_bytes\\":3156,\\"base64_data_sha256\\":\\"1703bd103a438c34c66fe18d82c5cd035d18262632055ab7428a73e13fd7125e\\",\\"baseline_body_bytes\\":12732,\\"baseline_body_sha256\\":\\"c40686a051a53f5b6443c414e45833fd5765b904bac971c8ba6f1eb9d365e613\\",\\"baseline_bytes\\":18321,\\"baseline_sha256\\":\\"8e045e64625562cded6903492fbdcf440ddbb9a7f30f20d3774faed53dcd8019\\",\\"behavior_conformance_complete\\":false,\\"canonical_data_bytes\\":6566,\\"canonical_data_sha256\\":\\"8ca48e37f97d03af660960f75afab79db162e8f8997f39f6c1c5c55dd896c97e\\",\\"complete_geometry_qualified\\":false,\\"compressed_data_bytes\\":2365,\\"compressed_data_sha256\\":\\"a7caf17aa8d2d5d6beb60880d415e7328947d188623bf5fa0d1ad566e1fd2f2f\\",\\"compression\\":{\\"caller_deadline\\":1895903.4914154,\\"causes\\":[],\\"child_completion_observed_before_deadline\\":true,\\"child_total_deadline\\":1895898.4914154,\\"child_total_limit_seconds\\":30,\\"child_work_limit_seconds\\":27,\\"cleanup_deadline\\":1895879.7526522,\\"cleanup_limit_seconds\\":3,\\"command_options\\":[\\"--max-old-space-size=256\\",\\"--input-type=commonjs\\",\\"-e\\"],\\"data_only\\":true,\\"descendant_quiescence\\":\\"UNKNOWN\\",\\"elapsed_seconds\\":0.06852049985900521,\\"environment_keys\\":[\\"PATH\\",\\"SystemRoot\\"],\\"final_reserve_seconds\\":5,\\"finished_before_deadline\\":true,\\"input_bytes\\":6566,\\"input_sha256\\":\\"8ca48e37f97d03af660960f75afab79db162e8f8997f39f6c1c5c55dd896c97e\\",\\"kill_requested\\":false,\\"node_executable\\":\\"C:\\\\\\\\Program Files\\\\\\\\nodejs\\\\\\\\node.exe\\",\\"node_version\\":\\"25.2.1\\",\\"packed_bytes\\":2365,\\"packed_sha256\\":\\"a7caf17aa8d2d5d6beb60880d415e7328947d188623bf5fa0d1ad566e1fd2f2f\\",\\"parent_observed_completion\\":true,\\"pid\\":61992,\\"program_sha256\\":\\"1b247b18c586bad5fe381de140410ee63fbe66e770cdbd2a52fe4540d1208c11\\",\\"quality\\":11,\\"reaped\\":true,\\"returncode\\":0,\\"roundtrip\\":true,\\"schema_version\\":1,\\"spawned\\":true,\\"started_monotonic\\":1895876.6842682,\\"stderr\\":{\\"closed\\":true,\\"eof\\":true,\\"io_error\\":null,\\"observed_bytes\\":0,\\"overflow\\":false,\\"prefix_sha256\\":\\"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855\\",\\"retained_bytes\\":0,\\"unknown_remainder\\":false},\\"stderr_prefix_b64\\":\\"\\",\\"stdin_bytes\\":6566,\\"stdin_closed\\":true,\\"stdin_complete\\":true,\\"stdin_extent_unknown\\":false,\\"stdin_write_attempted\\":true,\\"stdin_write_in_flight\\":false,\\"stdout\\":{\\"closed\\":true,\\"eof\\":true,\\"io_error\\":null,\\"observed_bytes\\":3228,\\"overflow\\":false,\\"prefix_sha256\\":\\"2f8a5164f43d19033a72018652e92813d3105fd1cb70fbac569f16b9b1824e8f\\",\\"retained_bytes\\":3228,\\"unknown_remainder\\":false},\\"threads_joined\\":true,\\"threads_started\\":3,\\"timed_out\\":false,\\"work_deadline\\":1895895.4914154},\\"data_fields\\":9,\\"decoder_bytes\\":5294,\\"decoder_sha256\\":\\"4b2260bb177b12668b0a4407711258aa3c1eb1c8d1702b6bd5e089502a399823\\",\\"deferred_definition_bytes\\":4172,\\"deferred_definition_sha256\\":\\"dbf54523ecfa1299d7f3dd6392aa1a8f90468112cdd619adcc5466eb8e60e966\\",\\"escaped_source_bytes\\":14243,\\"exact_decoder_inverse\\":true,\\"exact_inverse_source\\":true,\\"exact_phase_inverse\\":true,\\"finalizer_implemented\\":false,\\"generated_full_subject_files_written\\":false,\\"generated_operational_program_executed\\":false,\\"kind\\":\\"d24_initial_source_only_v1\\",\\"original_builder_bytes\\":18676,\\"original_builder_sha256\\":\\"bcfc55d551057f85aa3cd74f0d15d94e1e0aba932d7f079c18c7c9cbc8ac0dd3\\",\\"prefix_bytes\\":295,\\"prefix_sha256\\":\\"ea63175835e2149d61c71d52696c62033d17b908f76ca0a20cf25e32b18f142b\\",\\"source_bytes\\":14162,\\"source_contribution_fits\\":false,\\"source_only_over_cap_by\\":1955,\\"source_sha256\\":\\"4032a534147aada87931734f3b06cde67988d62c75851b959945399843a3770d\\",\\"status\\":\\"HOLD_SOURCE_CONTRIBUTION_OVER_CAP\\",\\"strings_field_absent\\":true,\\"task_2_10_complete\\":false},\\"input_data_sha256\\":\\"423dd27140a3e9189795ae199b37094f663168f757f15d6c2c8b3c74b217a164\\",\\"input_data_size_bytes\\":188127,\\"kind\\":\\"d25_inert_source_construction_metadata_v1\\",\\"modeled_later_form_count\\":6,\\"modeled_setup_form_count\\":6,\\"node_codec\\":{\\"encoder_excluded\\":true,\\"excluded_encoder_bytes\\":2964,\\"excluded_encoder_sha256\\":\\"6123f11ab75ed5a4021dc038ff878cd6873d71492058e8b887d3b3c28b4fc295\\",\\"full_codec_bytes\\":6903,\\"full_codec_sha256\\":\\"c65b73fe0e7d274040dda413b7871ee83c4c952f9bb2c1e74962b0e3e5f34767\\",\\"kind\\":\\"d25_node_codec_role_v1\\",\\"marker_occurrences\\":1,\\"node_codec_bytes\\":3939,\\"node_codec_sha256\\":\\"d7f478ee3e5ff65d7146c58e2a9fa078e66219cc1e35ea8547701e576295c32d\\",\\"role_is_exact_prefix\\":true},\\"physical_acceptance\\":false}\\nD25_CASE_METADATA {\\"capture\\":{\\"caller_deadline\\":1895903.4914154,\\"case\\":\\"geometry\\",\\"case_cause\\":\\"d25_geometry_hold\\",\\"case_completed\\":false,\\"causes\\":[],\\"checks_count\\":49,\\"child_completion_observed_before_deadline\\":true,\\"child_total_deadline\\":1895898.4914154,\\"child_total_limit_seconds\\":30,\\"child_work_limit_seconds\\":27,\\"cleanup_deadline\\":1895879.9829615,\\"cleanup_limit_seconds\\":3,\\"command_options\\":[\\"--max-old-space-size=256\\",\\"--input-type=commonjs\\",\\"-e\\"],\\"data_bytes\\":188127,\\"data_only\\":true,\\"data_sha256\\":\\"423dd27140a3e9189795ae199b37094f663168f757f15d6c2c8b3c74b217a164\\",\\"descendant_quiescence\\":\\"UNKNOWN\\",\\"driver_getter\\":\\"d25_geometry_driver_v1\\",\\"driver_role\\":\\"geometry\\",\\"elapsed_seconds\\":0.13510000007227063,\\"environment_keys\\":[\\"PATH\\",\\"SystemRoot\\"],\\"final_reserve_seconds\\":5,\\"finished_before_deadline\\":true,\\"input_bytes\\":188154,\\"input_sha256\\":\\"0421d214971adcb6e19c3f34d642962511b043215c908e82e0f44b0361c210b3\\",\\"kill_requested\\":false,\\"measurements_count\\":15,\\"node_executable\\":\\"C:\\\\\\\\Program Files\\\\\\\\nodejs\\\\\\\\node.exe\\",\\"node_version\\":\\"25.2.1\\",\\"parent_observed_completion\\":true,\\"pid\\":37808,\\"program_bytes\\":24572,\\"program_sha256\\":\\"f3bce3947d93f0a9d630372bd1b0d4d02fe61ecd1e47458259f3a8ccdad72265\\",\\"reaped\\":true,\\"report_bytes\\":4405,\\"report_sha256\\":\\"4e3b8c93c98eb7ed3715c5a939531b01b41f59f9c501ff574fce70c115532e17\\",\\"returncode\\":0,\\"schema_version\\":1,\\"source_kind\\":\\"d25_fixed_test_driver_v1\\",\\"spawned\\":true,\\"started_monotonic\\":1895876.8481243,\\"stderr\\":{\\"closed\\":true,\\"eof\\":true,\\"io_error\\":null,\\"observed_bytes\\":0,\\"overflow\\":false,\\"prefix_sha256\\":\\"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855\\",\\"retained_bytes\\":0,\\"unknown_remainder\\":false},\\"stdin_bytes\\":188154,\\"stdin_closed\\":true,\\"stdin_complete\\":true,\\"stdin_extent_unknown\\":false,\\"stdin_write_attempted\\":true,\\"stdin_write_in_flight\\":false,\\"stdout\\":{\\"closed\\":true,\\"eof\\":true,\\"io_error\\":null,\\"observed_bytes\\":4405,\\"overflow\\":false,\\"prefix_sha256\\":\\"4e3b8c93c98eb7ed3715c5a939531b01b41f59f9c501ff574fce70c115532e17\\",\\"retained_bytes\\":4405,\\"unknown_remainder\\":false},\\"threads_joined\\":true,\\"threads_started\\":3,\\"timed_out\\":false,\\"work_deadline\\":1895895.4914154},\\"case\\":\\"geometry\\",\\"report\\":{\\"case\\":\\"geometry\\",\\"cause\\":\\"d25_geometry_hold\\",\\"checks\\":[{\\"id\\":\\"source_bindings\\",\\"ok\\":true},{\\"id\\":\\"initial_source_bound\\",\\"ok\\":true},{\\"id\\":\\"finalizer_source_bound\\",\\"ok\\":true},{\\"id\\":\\"executor_source_bound\\",\\"ok\\":true},{\\"id\\":\\"six_setup_forms\\",\\"ok\\":true},{\\"id\\":\\"success_setup\\",\\"ok\\":true},{\\"id\\":\\"success_provider_pipes\\",\\"ok\\":true},{\\"id\\":\\"success_pipe0_inverse\\",\\"ok\\":true},{\\"id\\":\\"success_pipe1_inverse\\",\\"ok\\":true},{\\"id\\":\\"success_pipe2_inverse\\",\\"ok\\":true},{\\"id\\":\\"success_selected_original_bound\\",\\"ok\\":true},{\\"id\\":\\"success_wire_geometry\\",\\"ok\\":false},{\\"id\\":\\"structured_failure_setup\\",\\"ok\\":true},{\\"id\\":\\"structured_failure_provider_pipes\\",\\"ok\\":true},{\\"id\\":\\"structured_failure_pipe0_inverse\\",\\"ok\\":true},{\\"id\\":\\"structured_failure_pipe1_inverse\\",\\"ok\\":true},{\\"id\\":\\"structured_failure_pipe2_inverse\\",\\"ok\\":true},{\\"id\\":\\"structured_failure_selected_original_bound\\",\\"ok\\":true},{\\"id\\":\\"structured_failure_wire_geometry\\",\\"ok\\":false},{\\"id\\":\\"unicode_failure_setup\\",\\"ok\\":true},{\\"id\\":\\"unicode_failure_provider_pipes\\",\\"ok\\":true},{\\"id\\":\\"unicode_failure_pipe0_inverse\\",\\"ok\\":true},{\\"id\\":\\"unicode_failure_pipe1_inverse\\",\\"ok\\":true},{\\"id\\":\\"unicode_failure_pipe2_inverse\\",\\"ok\\":true},{\\"id\\":\\"unicode_failure_selected_original_bound\\",\\"ok\\":true},{\\"id\\":\\"unicode_failure_wire_geometry\\",\\"ok\\":false},{\\"id\\":\\"partial_emission_setup\\",\\"ok\\":true},{\\"id\\":\\"partial_emission_provider_pipes\\",\\"ok\\":true},{\\"id\\":\\"partial_emission_pipe0_inverse\\",\\"ok\\":true},{\\"id\\":\\"partial_emission_pipe1_inverse\\",\\"ok\\":true},{\\"id\\":\\"partial_emission_pipe2_inverse\\",\\"ok\\":true},{\\"id\\":\\"partial_emission_selected_original_bound\\",\\"ok\\":true},{\\"id\\":\\"partial_emission_wire_geometry\\",\\"ok\\":false},{\\"id\\":\\"unknown_closure_setup\\",\\"ok\\":true},{\\"id\\":\\"unknown_closure_provider_pipes\\",\\"ok\\":true},{\\"id\\":\\"unknown_closure_pipe0_inverse\\",\\"ok\\":true},{\\"id\\":\\"unknown_closure_pipe1_inverse\\",\\"ok\\":true},{\\"id\\":\\"unknown_closure_pipe2_inverse\\",\\"ok\\":true},{\\"id\\":\\"unknown_closure_selected_original_bound\\",\\"ok\\":true},{\\"id\\":\\"unknown_closure_wire_geometry\\",\\"ok\\":false},{\\"id\\":\\"setup_refusal_setup\\",\\"ok\\":true},{\\"id\\":\\"setup_refusal_provider_pipes\\",\\"ok\\":true},{\\"id\\":\\"setup_refusal_pipe0_inverse\\",\\"ok\\":true},{\\"id\\":\\"setup_refusal_pipe1_inverse\\",\\"ok\\":true},{\\"id\\":\\"setup_refusal_pipe2_inverse\\",\\"ok\\":true},{\\"id\\":\\"setup_refusal_selected_original_bound\\",\\"ok\\":true},{\\"id\\":\\"setup_refusal_wire_geometry\\",\\"ok\\":false},{\\"id\\":\\"six_later_forms\\",\\"ok\\":true},{\\"id\\":\\"later_measured_upstream\\",\\"ok\\":false}],\\"completed\\":false,\\"measurements\\":[{\\"id\\":\\"initial_source\\",\\"sha256\\":\\"4032a534147aada87931734f3b06cde67988d62c75851b959945399843a3770d\\",\\"size_bytes\\":14162},{\\"id\\":\\"finalizer_source\\",\\"sha256\\":\\"fcca4065d75430e87e6f8e1f4df3be68bd084421da0ca7266218a5f801e8eb1a\\",\\"size_bytes\\":34397},{\\"id\\":\\"executor_source\\",\\"sha256\\":\\"9104621cfe1b7e0931f1dca52ecf216c4f2874233803abcff621db1b9077ae45\\",\\"size_bytes\\":78392},{\\"id\\":\\"success_selected_original\\",\\"sha256\\":\\"46fdb4a08fc1898e57d6c2b942a28aebdebe49b1f4b5bbe11c44177f2cce628e\\",\\"size_bytes\\":17067},{\\"id\\":\\"success_wire_refusal\\",\\"sha256\\":\\"17f54ba84e38766575c165a616f7755840343aa043663bd0f9f2f833393831a6\\",\\"size_bytes\\":19},{\\"id\\":\\"structured_failure_selected_original\\",\\"sha256\\":\\"e8cf9b26009ff462152eff45d59343793f7ee5216f1e6f00197b6256ec0d310c\\",\\"size_bytes\\":17293},{\\"id\\":\\"structured_failure_wire_refusal\\",\\"sha256\\":\\"17f54ba84e38766575c165a616f7755840343aa043663bd0f9f2f833393831a6\\",\\"size_bytes\\":19},{\\"id\\":\\"unicode_failure_selected_original\\",\\"sha256\\":\\"84e2bf9ea93cf982623ef86d9eeb398f4e468eb80656efdf57f206541b55d563\\",\\"size_bytes\\":17193},{\\"id\\":\\"unicode_failure_wire_refusal\\",\\"sha256\\":\\"17f54ba84e38766575c165a616f7755840343aa043663bd0f9f2f833393831a6\\",\\"size_bytes\\":19},{\\"id\\":\\"partial_emission_selected_original\\",\\"sha256\\":\\"79ea8cf1b2d66bc2431f4175baabd65338946aff50e3b104d64ce986f8087297\\",\\"size_bytes\\":16786},{\\"id\\":\\"partial_emission_wire_refusal\\",\\"sha256\\":\\"17f54ba84e38766575c165a616f7755840343aa043663bd0f9f2f833393831a6\\",\\"size_bytes\\":19},{\\"id\\":\\"unknown_closure_selected_original\\",\\"sha256\\":\\"628eaa305921b541a5502e476b5c6d3ad4dbf5d452625a8ca547de7b1e1afff4\\",\\"size_bytes\\":17071},{\\"id\\":\\"unknown_closure_wire_refusal\\",\\"sha256\\":\\"17f54ba84e38766575c165a616f7755840343aa043663bd0f9f2f833393831a6\\",\\"size_bytes\\":19},{\\"id\\":\\"setup_refusal_selected_original\\",\\"sha256\\":\\"6beffafc4f5629b627f40ace16448fea4ca0e16e57cea746c602759262e53429\\",\\"size_bytes\\":16147},{\\"id\\":\\"setup_refusal_wire_refusal\\",\\"sha256\\":\\"17f54ba84e38766575c165a616f7755840343aa043663bd0f9f2f833393831a6\\",\\"size_bytes\\":19}],\\"node_version\\":\\"25.2.1\\",\\"schema_version\\":1}}\\n{\\"error_type\\":\\"AssertionError\\",\\"event\\":\\"parent_issue\\",\\"exception_capture\\":{\\"capture\\":null,\\"capture_metadata_sha256\\":\\"74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b\\",\\"capture_metadata_size_bytes\\":4,\\"capture_metadata_unavailable\\":true},\\"issue_index\\":1,\\"message_sha256\\":\\"99aa63d206d7144485e96f78b7a409e74a08cc0918e3cf282ff0a3643c008fd6\\",\\"message_size_bytes\\":2540,\\"outcome\\":\\"failure\\",\\"subtest_ordinal\\":null,\\"test_id\\":\\"tests.test_accepted_policy_fixture_compiler_gate2_resume_v1.D25CompleteGeometryTests.test_complete_form_bounds_preserve_hold\\"}\\n{\\"error_type\\":\\"AssertionError\\",\\"event\\":\\"test_terminal\\",\\"exception_capture\\":{\\"capture\\":null,\\"capture_metadata_sha256\\":\\"74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b\\",\\"capture_metadata_size_bytes\\":4,\\"capture_metadata_unavailable\\":true},\\"issue_counts\\":{\\"parent_issue\\":1,\\"subtest_issue\\":0},\\"message_sha256\\":\\"99aa63d206d7144485e96f78b7a409e74a08cc0918e3cf282ff0a3643c008fd6\\",\\"message_size_bytes\\":2540,\\"outcome\\":\\"failure\\",\\"subtest_callbacks\\":0,\\"test_id\\":\\"tests.test_accepted_policy_fixture_compiler_gate2_resume_v1.D25CompleteGeometryTests.test_complete_form_bounds_preserve_hold\\"}\\n{\\"descendant_quiescence\\":\\"UNKNOWN\\",\\"errors\\":0,\\"event\\":\\"test_summary\\",\\"expected_failures\\":0,\\"expected_metadata_records\\":2,\\"failures\\":1,\\"generated_operational_program_execution\\":false,\\"geometry_case_records\\":1,\\"geometry_source_records\\":1,\\"issue_events\\":1,\\"parent_outcomes\\":{\\"failure\\":1},\\"selected_class\\":\\"D25CompleteGeometryTests\\",\\"skips\\":0,\\"subtest_callbacks\\":0,\\"successes\\":0,\\"successful\\":false,\\"test_streams\\":{\\"stderr\\":{\\"geometry_case_records\\":0,\\"geometry_source_records\\":0,\\"metadata_records\\":0,\\"observed_bytes\\":0,\\"raw_values_retained\\":false,\\"sha256\\":\\"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855\\",\\"unexpected_or_unterminated\\":false},\\"stdout\\":{\\"geometry_case_records\\":1,\\"geometry_source_records\\":1,\\"metadata_records\\":2,\\"observed_bytes\\":12199,\\"raw_values_retained\\":false,\\"sha256\\":\\"e2cb98ce5df1df0b35f009a3675a7332e6a1c81148358911e1924e666ccfbbab\\",\\"unexpected_or_unterminated\\":false}},\\"tests_run\\":1,\\"unexpected_successes\\":0}\\n","name":"stdout","original_filename":"vast-d25-geometry-complete-01-20261018-01.stdout.original.txt","sha256":"a4a5ab1731bacdb30596e78f5b977b59b1de9f640c35292ace928c62f65d9f43","size_bytes":15811},{"bytes_ascii":"","name":"stderr","original_filename":"vast-d25-geometry-complete-01-20261018-01.stderr.original.txt","sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","size_bytes":0},{"bytes_ascii":"{\\"channels\\":{\\"stderr\\":{\\"close_attempted\\":true,\\"closed\\":true,\\"closure_unknown\\":false,\\"eof\\":true,\\"error\\":null,\\"observed_bytes\\":0,\\"overflow\\":false,\\"remainder_unknown\\":false,\\"secondary\\":[],\\"sha256\\":\\"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855\\",\\"size_bytes\\":0},\\"stdout\\":{\\"close_attempted\\":true,\\"closed\\":true,\\"closure_unknown\\":false,\\"eof\\":true,\\"error\\":null,\\"observed_bytes\\":15811,\\"overflow\\":false,\\"remainder_unknown\\":false,\\"secondary\\":[],\\"sha256\\":\\"a4a5ab1731bacdb30596e78f5b977b59b1de9f640c35292ace928c62f65d9f43\\",\\"size_bytes\\":15811}},\\"child_completion_before_cleanup_end\\":true,\\"child_completion_before_total_end\\":true,\\"child_completion_observed_at\\":1895877.0014977,\\"child_total_deadline\\":1895906.4914154,\\"child_total_seconds\\":30,\\"child_work_seconds\\":27,\\"cleanup_deadline\\":1895880.0014809,\\"codec_role_binding\\":{\\"encoder_excluded\\":true,\\"excluded_encoder_bytes\\":2964,\\"excluded_encoder_sha256\\":\\"6123f11ab75ed5a4021dc038ff878cd6873d71492058e8b887d3b3c28b4fc295\\",\\"full_codec_bytes\\":6903,\\"full_codec_sha256\\":\\"c65b73fe0e7d274040dda413b7871ee83c4c952f9bb2c1e74962b0e3e5f34767\\",\\"kind\\":\\"d25_node_codec_role_v1\\",\\"marker_occurrences\\":1,\\"node_codec_bytes\\":3939,\\"node_codec_sha256\\":\\"d7f478ee3e5ff65d7146c58e2a9fa078e66219cc1e35ea8547701e576295c32d\\",\\"role_is_exact_prefix\\":true},\\"deadline_seconds\\":300,\\"descendant_quiescence\\":\\"UNKNOWN\\",\\"elapsed_before_report_write_s\\":0.5301765000913292,\\"fixed_driver_binding\\":{\\"driver_getter\\":\\"d25_geometry_driver_v1\\",\\"driver_role\\":\\"geometry\\",\\"program_bytes\\":24572,\\"program_sha256\\":\\"f3bce3947d93f0a9d630372bd1b0d4d02fe61ecd1e47458259f3a8ccdad72265\\",\\"source_kind\\":\\"d25_fixed_test_driver_v1\\"},\\"forced_test_child\\":false,\\"generated_operational_program_execution\\":false,\\"geometry_fully_measured\\":false,\\"geometry_risk_passed\\":false,\\"geometry_source_kind\\":\\"d25_inert_source_construction_metadata_v1\\",\\"held_driver_loader_binding_validated\\":true,\\"io_failure\\":false,\\"kind\\":\\"d25_local_inert_geometry_test_parent_observation_v1\\",\\"ordered_causes\\":[],\\"parent_observed_test_transport_complete\\":true,\\"protocol_error_type\\":null,\\"python\\":\\"3.14.7\\",\\"returncode\\":1,\\"selected_class\\":\\"D25CompleteGeometryTests\\",\\"self_report_persistence_or_whole_process_attested\\":false,\\"source_binding_policy\\":\\"both_held_test_buffers_before_either_compile\\",\\"source_binding_record_validated\\":true,\\"source_execution_reopens_paths\\":false,\\"source_pins\\":[{\\"path\\":\\"tests/test_accepted_policy_fixture_compiler_gate2_resume_v1.py\\",\\"sha256\\":\\"3dcea0ea515be7c33cd95486adf9b818b63ce39894d9cbe48c8318ec4fd02b39\\",\\"size_bytes\\":476378},{\\"path\\":\\"tests/test_accepted_policy_fixture_compiler_gate2_resume_caller_v1.py\\",\\"sha256\\":\\"77946ffadc24d7fd3759186417eb5ae330edd306f7a3170d5370f7e44b4e61b4\\",\\"size_bytes\\":281307}],\\"suite_mode\\":\\"geometry\\",\\"test_child_command_chars\\":30083,\\"test_summary\\":{\\"descendant_quiescence\\":\\"UNKNOWN\\",\\"errors\\":0,\\"event\\":\\"test_summary\\",\\"expected_failures\\":0,\\"expected_metadata_records\\":2,\\"failures\\":1,\\"generated_operational_program_execution\\":false,\\"geometry_case_records\\":1,\\"geometry_source_records\\":1,\\"issue_events\\":1,\\"parent_outcomes\\":{\\"failure\\":1},\\"selected_class\\":\\"D25CompleteGeometryTests\\",\\"skips\\":0,\\"subtest_callbacks\\":0,\\"successes\\":0,\\"successful\\":false,\\"test_streams\\":{\\"stderr\\":{\\"geometry_case_records\\":0,\\"geometry_source_records\\":0,\\"metadata_records\\":0,\\"observed_bytes\\":0,\\"raw_values_retained\\":false,\\"sha256\\":\\"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855\\",\\"unexpected_or_unterminated\\":false},\\"stdout\\":{\\"geometry_case_records\\":1,\\"geometry_source_records\\":1,\\"metadata_records\\":2,\\"observed_bytes\\":12199,\\"raw_values_retained\\":false,\\"sha256\\":\\"e2cb98ce5df1df0b35f009a3675a7332e6a1c81148358911e1924e666ccfbbab\\",\\"unexpected_or_unterminated\\":false}},\\"tests_run\\":1,\\"unexpected_successes\\":0},\\"threads_joined\\":true,\\"timed_out\\":false,\\"work_deadline\\":1895903.4914154}\\n","name":"parent","original_filename":"vast-d25-geometry-complete-01-20261018-01.derived.json","sha256":"3d31e731927dde64f42e95e8da6921c864a3d9b1bc7f9a4c2a9709e63f4e43b3","size_bytes":3780},{"acquisition":"canonical_report_plus_LF_bound_to_original_child_capture_hash_not_separate_direct_Node_file","bytes_ascii":"{\\"case\\":\\"geometry\\",\\"cause\\":\\"d25_geometry_hold\\",\\"checks\\":[{\\"id\\":\\"source_bindings\\",\\"ok\\":true},{\\"id\\":\\"initial_source_bound\\",\\"ok\\":true},{\\"id\\":\\"finalizer_source_bound\\",\\"ok\\":true},{\\"id\\":\\"executor_source_bound\\",\\"ok\\":true},{\\"id\\":\\"six_setup_forms\\",\\"ok\\":true},{\\"id\\":\\"success_setup\\",\\"ok\\":true},{\\"id\\":\\"success_provider_pipes\\",\\"ok\\":true},{\\"id\\":\\"success_pipe0_inverse\\",\\"ok\\":true},{\\"id\\":\\"success_pipe1_inverse\\",\\"ok\\":true},{\\"id\\":\\"success_pipe2_inverse\\",\\"ok\\":true},{\\"id\\":\\"success_selected_original_bound\\",\\"ok\\":true},{\\"id\\":\\"success_wire_geometry\\",\\"ok\\":false},{\\"id\\":\\"structured_failure_setup\\",\\"ok\\":true},{\\"id\\":\\"structured_failure_provider_pipes\\",\\"ok\\":true},{\\"id\\":\\"structured_failure_pipe0_inverse\\",\\"ok\\":true},{\\"id\\":\\"structured_failure_pipe1_inverse\\",\\"ok\\":true},{\\"id\\":\\"structured_failure_pipe2_inverse\\",\\"ok\\":true},{\\"id\\":\\"structured_failure_selected_original_bound\\",\\"ok\\":true},{\\"id\\":\\"structured_failure_wire_geometry\\",\\"ok\\":false},{\\"id\\":\\"unicode_failure_setup\\",\\"ok\\":true},{\\"id\\":\\"unicode_failure_provider_pipes\\",\\"ok\\":true},{\\"id\\":\\"unicode_failure_pipe0_inverse\\",\\"ok\\":true},{\\"id\\":\\"unicode_failure_pipe1_inverse\\",\\"ok\\":true},{\\"id\\":\\"unicode_failure_pipe2_inverse\\",\\"ok\\":true},{\\"id\\":\\"unicode_failure_selected_original_bound\\",\\"ok\\":true},{\\"id\\":\\"unicode_failure_wire_geometry\\",\\"ok\\":false},{\\"id\\":\\"partial_emission_setup\\",\\"ok\\":true},{\\"id\\":\\"partial_emission_provider_pipes\\",\\"ok\\":true},{\\"id\\":\\"partial_emission_pipe0_inverse\\",\\"ok\\":true},{\\"id\\":\\"partial_emission_pipe1_inverse\\",\\"ok\\":true},{\\"id\\":\\"partial_emission_pipe2_inverse\\",\\"ok\\":true},{\\"id\\":\\"partial_emission_selected_original_bound\\",\\"ok\\":true},{\\"id\\":\\"partial_emission_wire_geometry\\",\\"ok\\":false},{\\"id\\":\\"unknown_closure_setup\\",\\"ok\\":true},{\\"id\\":\\"unknown_closure_provider_pipes\\",\\"ok\\":true},{\\"id\\":\\"unknown_closure_pipe0_inverse\\",\\"ok\\":true},{\\"id\\":\\"unknown_closure_pipe1_inverse\\",\\"ok\\":true},{\\"id\\":\\"unknown_closure_pipe2_inverse\\",\\"ok\\":true},{\\"id\\":\\"unknown_closure_selected_original_bound\\",\\"ok\\":true},{\\"id\\":\\"unknown_closure_wire_geometry\\",\\"ok\\":false},{\\"id\\":\\"setup_refusal_setup\\",\\"ok\\":true},{\\"id\\":\\"setup_refusal_provider_pipes\\",\\"ok\\":true},{\\"id\\":\\"setup_refusal_pipe0_inverse\\",\\"ok\\":true},{\\"id\\":\\"setup_refusal_pipe1_inverse\\",\\"ok\\":true},{\\"id\\":\\"setup_refusal_pipe2_inverse\\",\\"ok\\":true},{\\"id\\":\\"setup_refusal_selected_original_bound\\",\\"ok\\":true},{\\"id\\":\\"setup_refusal_wire_geometry\\",\\"ok\\":false},{\\"id\\":\\"six_later_forms\\",\\"ok\\":true},{\\"id\\":\\"later_measured_upstream\\",\\"ok\\":false}],\\"completed\\":false,\\"measurements\\":[{\\"id\\":\\"initial_source\\",\\"sha256\\":\\"4032a534147aada87931734f3b06cde67988d62c75851b959945399843a3770d\\",\\"size_bytes\\":14162},{\\"id\\":\\"finalizer_source\\",\\"sha256\\":\\"fcca4065d75430e87e6f8e1f4df3be68bd084421da0ca7266218a5f801e8eb1a\\",\\"size_bytes\\":34397},{\\"id\\":\\"executor_source\\",\\"sha256\\":\\"9104621cfe1b7e0931f1dca52ecf216c4f2874233803abcff621db1b9077ae45\\",\\"size_bytes\\":78392},{\\"id\\":\\"success_selected_original\\",\\"sha256\\":\\"46fdb4a08fc1898e57d6c2b942a28aebdebe49b1f4b5bbe11c44177f2cce628e\\",\\"size_bytes\\":17067},{\\"id\\":\\"success_wire_refusal\\",\\"sha256\\":\\"17f54ba84e38766575c165a616f7755840343aa043663bd0f9f2f833393831a6\\",\\"size_bytes\\":19},{\\"id\\":\\"structured_failure_selected_original\\",\\"sha256\\":\\"e8cf9b26009ff462152eff45d59343793f7ee5216f1e6f00197b6256ec0d310c\\",\\"size_bytes\\":17293},{\\"id\\":\\"structured_failure_wire_refusal\\",\\"sha256\\":\\"17f54ba84e38766575c165a616f7755840343aa043663bd0f9f2f833393831a6\\",\\"size_bytes\\":19},{\\"id\\":\\"unicode_failure_selected_original\\",\\"sha256\\":\\"84e2bf9ea93cf982623ef86d9eeb398f4e468eb80656efdf57f206541b55d563\\",\\"size_bytes\\":17193},{\\"id\\":\\"unicode_failure_wire_refusal\\",\\"sha256\\":\\"17f54ba84e38766575c165a616f7755840343aa043663bd0f9f2f833393831a6\\",\\"size_bytes\\":19},{\\"id\\":\\"partial_emission_selected_original\\",\\"sha256\\":\\"79ea8cf1b2d66bc2431f4175baabd65338946aff50e3b104d64ce986f8087297\\",\\"size_bytes\\":16786},{\\"id\\":\\"partial_emission_wire_refusal\\",\\"sha256\\":\\"17f54ba84e38766575c165a616f7755840343aa043663bd0f9f2f833393831a6\\",\\"size_bytes\\":19},{\\"id\\":\\"unknown_closure_selected_original\\",\\"sha256\\":\\"628eaa305921b541a5502e476b5c6d3ad4dbf5d452625a8ca547de7b1e1afff4\\",\\"size_bytes\\":17071},{\\"id\\":\\"unknown_closure_wire_refusal\\",\\"sha256\\":\\"17f54ba84e38766575c165a616f7755840343aa043663bd0f9f2f833393831a6\\",\\"size_bytes\\":19},{\\"id\\":\\"setup_refusal_selected_original\\",\\"sha256\\":\\"6beffafc4f5629b627f40ace16448fea4ca0e16e57cea746c602759262e53429\\",\\"size_bytes\\":16147},{\\"id\\":\\"setup_refusal_wire_refusal\\",\\"sha256\\":\\"17f54ba84e38766575c165a616f7755840343aa043663bd0f9f2f833393831a6\\",\\"size_bytes\\":19}],\\"node_version\\":\\"25.2.1\\",\\"schema_version\\":1}\\n","name":"canonical_report","original_filename":null,"sha256":"4e3b8c93c98eb7ed3715c5a939531b01b41f59f9c501ff574fce70c115532e17","size_bytes":4405}],"protected_source_rows":{"caller":{"excluded_replaced_class":null,"ordered_rows":[["Expr",[],80,"664f1276b0c65446318a967025c6a4d9568976116aa7373c42dc282d0c85eb16","f319dc3b92a3f2ba6e5bc05cb7cc104b42aa550b8989b795c971acf0c8ce3dbe"],["Import",["base64"],13,"f30aabd4a95e13b98c9537425bb02f63ac9631f1e6311b7f0ab80d85f88f61b8","99ccd02cb758ed604ff1bc1c067c06e1543524012de4421d7b80e9b7ad7717e7"],["Import",["contextlib"],17,"3ddb26968cc6251bdb984fa36c0441bbc314139a828d706fea21a8c502e5dcf8","dc298a564522c0894fe46a3cdb7c31e40f8408b4dbf1dd28469c587a6f0a7b5f"],["Import",["hashlib"],14,"ada1d9e0a360cda0fd1c8757d297aa74a4fc8d7193a69d3c28b43afc6950e9f9","092cb77ae0770f1627b29bf41b2732722fbcc3a0e1d77a79674801800a2721d1"],["Import",["io"],9,"b000f4590d6af9cfe633ffe0faae301a05dde8e4ca7757d7566f899d61f240b8","eb75a54c5d0d93fbb694f468951613f2f071166afbbe97a52903fa47a7cef914"],["Import",["json"],11,"ff3e4d4dcf7250cae8d622d77c9a6d69aefcf4ab04ef9920218fafe93c0f1991","211ee42757705c7e350e70e36b762987a737f5e9c268f2a343e2dbfcb8fbea75"],["Import",["os"],9,"de2abade832c8e350a1bdc98cfcdb1e202ac4749c5fc51a4a970d41736b6df5c","ac3a74d6dd975a8e8fe4b7f85fce794793a9355595b850e3926964913948d386"],["ImportFrom",["Path"],24,"6d69f2ac09017b8a49d050ab336e953b8fa02ae08c24396916ea7ea42418e627","59051b17634cdcb5a576ceb58fdc0a4e5652ed3b60d66667e92ddefd931abeca"],["Import",["tempfile"],15,"09d25239ae3d62e91c70b74fa5baa1d52a22c5c2397a785935889e61f91a8557","81dafa7a7cf16b83e7a7cafd7a6702e15f4b4d576a43463dc14beb05d48e72d0"],["Import",["types"],12,"9ba0ef4a2880daedd15b0e74d296458ac4dd0295c9a24bee6a3b486d4a963833","5fc62d8a32deca3631b4cf444b2d5eb1a9d861eaf4d371ab1f2139e0ee13500c"],["Import",["unittest"],15,"a3133fe783a48c83eae67900c7bba9f417b6367ab7d4708836feaa3b2c88e60c","c2989ab60afe692e3752cff01ca6c5975c26cf4d65ed0ff66c3e1ddd0062fe42"],["Import",["zlib"],11,"fb13e8690a2e9705e04cad7ad4a2958269186f6bc24bff331f76f8f01f9e5875","02de0820630aca0acec134c03e1eb366c46443b45b7a9410ae6ef721d7245fcb"],["ImportFrom",["mock"],25,"1386c1111eba21a088c0f150cd37c9688432ad5a380151e4faafb8ebd4d135f5","28c41628e362acf9f34ed052a8994c052db26ae684f23c3cabeee952b098a86d"],["Assign",["REPO"],42,"2ef3c9ab35eb9d9a70565b0f58f06576278721a072aa56c85bc611bf44e65953","94064ab90ac0aba038dd70c75863cfd04d56dc8cd6d2e1682e5cf64fd7d7650f"],["Assign",["FIXED_REPO"],93,"a7db5de2c19c2aa295136cd1c625815467716132155059ef8cf7e336b38c1967","0afda0cb27c11c811d12eed9640e34513a77e024ef0465100599bc4601d0ea5e"],["Assign",["PREFIX"],58,"573490013374c04b92300de35aa2d354950bd4b1451179080868a3fdfaf15716","a258a2f125fef23a3eb236b8f7d1e47f68c9801a39d3faa3c679392a20c925e5"],["Assign",["COMPONENT"],39,"940e0ee722eb651a6f18912ce11c83c7e928df673879f3c0a7b91043375a9aa8","9bd796a15311c2404c98b1c29800a7fe831ab1c7fd45e808b75f651a9e6810c8"],["Assign",["OPERATOR"],41,"ed172ade28eea7260025c1620b81bb9a285a988eb0d6796984d3469f01ce047e","ffafc4884134b007344eeb46c98ac40d79715670e45a977da8f7b59a78251885"],["Assign",["TARGET"],151,"54a5e24cd586400478c1db7894d293a7bc4f71779a88d1b147ee7f4a4954aeb0","8bd3ff3305ae07cb16598a06d40ebf63376105607436cf20a6caccdbc70cbb6f"],["Assign",["WRITER_READY"],228,"3927299011dbfa8e2c100572e4a2ecb877efd638d165ad82dc60bd7aef50df77","de6ec76cb46fc6b9f79fd8bc41692dfcd26773c48696b6574ea3f4fa1c63a0ec"],["Assign",["WRITER_BODY"],5146,"67174fbe6e6d06c992dfc34ccf865d93829ceae80a3252ce058b7cb1d6f99188","ba6fc5ed89a759796100a50931a58f22b3dd1b9b1a3b63f669547f6dba18b3e7"],["Assign",["WRITER_SOURCE"],42,"35eddffa293fc5a22f6ae92a40c40e45f83aeadd1bdcc175b176a240deeb5d11","df0e4e7bef27940a39adac752817f40c6b6abc50f8e8b00b713655024a90e2d1"],["Assign",["WRITER_COMPRESSED"],99,"cff01114564c8711f806f46137e2f82170f4365f4d4d9e29652cbc3e7b1410c5","799f0ff6ec1f14bbc4ab3fe8ccd13b2682bdfb238c8a9c5190120fc2cdea3032"],["Assign",["WRITER_CARRIER"],200,"299e78b0e9362acf22a9b93cefaf669eeeaf81ac171ab84716d6d2848c1e3ae2","a1b7f5ec7ec24c0f6ceaea0d0da8aad9e0508df080503711e6d833ccdf49e713"],["Assign",["QUALIFIED_REUSE_SOURCE"],38,"0b86a07e0d317b4e2d0feb554e4d2cb1adf3124256a271b4f49218e53e3805af","35fc964bb533d4a758aa5e269c362a4bb402fa7a653a052f370da62712d7959d"],["Assign",["WRITER_BODY"],5148,"099080fcd2f9aafe0ca57e247277f11c0af9c655cc57294bee6b40e7cab3688f","e9896b64fb6f30619993b2c7c4802d99561ecc1b60c3e934858a0c1a0265b349"],["Assign",["WRITER_SOURCE"],196,"392b4dc7a19b7d7fda6939846aa89c1c59648150a4a1ff288bb06bca498bb693","50b90bad0899cdb97506ae1339a95b5a2f1d2e8fee3c2c426eb0a736f4af4656"],["Assign",["WRITER_COMPRESSED"],99,"cff01114564c8711f806f46137e2f82170f4365f4d4d9e29652cbc3e7b1410c5","799f0ff6ec1f14bbc4ab3fe8ccd13b2682bdfb238c8a9c5190120fc2cdea3032"],["Assign",["WRITER_CARRIER"],200,"299e78b0e9362acf22a9b93cefaf669eeeaf81ac171ab84716d6d2848c1e3ae2","a1b7f5ec7ec24c0f6ceaea0d0da8aad9e0508df080503711e6d833ccdf49e713"],["Assign",["STANDALONE_WRITER_BODY","STANDALONE_WRITER_SOURCE"],77,"7a1794879b42a36a47780fb33f87c0dbecf4cef1484edde6587113514f7a321e","d73522b2c23257511daa415b9b0905d0dcbf55aa01ea854e0c75e5df5b8155d5"],["Assign",["STANDALONE_WRITER_CARRIER","STANDALONE_WRITER_COMPRESSED"],91,"ab0d814da420722555a8a9c0098c3a1cdd6752ba2b0006f6bf96f74fc97920e0","d4e130a23c1022b44fd566418476a455eb34494a3ae55b42e0a790bd93dc4ac6"],["Assign",["PYTHON_CLOCK_HEAD"],63,"b0bccd3bbf077bbd1983b82890acecb9f108da4fbc3bf7a4e1bf1a7a9f6af9a7","e02e221028a51179157be7780d7fe880f0b16318604c9ae087c2b5e6ae3c59c1"],["Assign",["WRITER_READY"],216,"646bc05c189677de2ac6ba71b464c2e8af3598ccfa41da385432f6d3197d7806","1054f55a62592e320cf63aba7e1572589913d66f5f05f21b0cdc67f961604e2d"],["Assign",["WRITER_HEAD"],112,"54a6111b988f24baf737cefcca24ac702584e948a5cd31a7d3787fc2a833ce36","592283a8c22702d96095c218875d2049f67ea2948ecaa6bd456795735961e4f4"],["Assign",["SETUP_COMMON_HEAD"],124,"ed63ea6e756cc0f701c2966f95408825b902c3fdb98e13ba24604416b4e04b41","d7820486ca254d8deaa0e7e19e1b5efec80517dd82fb171876b9d20301b735e7"],["Assign",["WRITER_COMMON_SOURCE"],3650,"fd79d90e544ef6c061a50f2e4ffcb63ce9da3d3b0c2e94cf76aa470dab67fbfa","67e2782c85fb8380591e9c2fd5f2cbc26f5ee6f4a1d8d9e82e5e56495c745eca"],["Assign",["WRITER_TAIL"],1477,"376f76cef2fc7961822d4715c6af765f1ccb5f68f1c69245750307a479204b2a","f4de0f1d9df844f0246faa4299fb41d7f0f57beb73fb8324ad93c3b98981551e"],["Assign",["WRITER_BODY"],62,"648a0f0fdd3c0c01ba0179f77de296590c694ce49a228726956294ab61960b1d","97ecc7ded6363305aec2caa4b6059b979d7ad7d4d5d5f64134d10f672d1e07b0"],["Assign",["WRITER_SOURCE"],196,"392b4dc7a19b7d7fda6939846aa89c1c59648150a4a1ff288bb06bca498bb693","50b90bad0899cdb97506ae1339a95b5a2f1d2e8fee3c2c426eb0a736f4af4656"],["Assign",["WRITER_COMPRESSED"],99,"cff01114564c8711f806f46137e2f82170f4365f4d4d9e29652cbc3e7b1410c5","799f0ff6ec1f14bbc4ab3fe8ccd13b2682bdfb238c8a9c5190120fc2cdea3032"],["Assign",["WRITER_CARRIER"],200,"299e78b0e9362acf22a9b93cefaf669eeeaf81ac171ab84716d6d2848c1e3ae2","a1b7f5ec7ec24c0f6ceaea0d0da8aad9e0508df080503711e6d833ccdf49e713"],["FunctionDef",["canonical"],163,"ef77bbf713bec30cf506858d88defd32365f45657afb797e99ae3835b8624186","56c13467459a519ed23beae122070837f894408f8ab7b6244314562ad4a4b77c"],["ClassDef",["WriterTests"],28081,"a4de1cbc3fa3ac6bc892abd6cb6477d876686ba94c13996457d9fa2e6409a5ab","5a2f19bbcb4b5bf7cdb366e917e8678e9b9a4c7d80f9216370f82ac629291c35"],["ClassDef",["CommonFragmentTests"],2733,"7d81bcd4478d841c6a9b94da20693e049bda8c6ae998ccf87636c12b324129dc","fa7b62dd1a7d26f361dc7486cf81f63a5f28356d3cff0087ada7cc909d748900"],["ClassDef",["HeldWriterTests"],12097,"eef4067e24a1d99f3f4a00a9fabc083d39c991574056eb6d596f6829b145ccbe","7bfdf20dd17e50b009ec3b0be4f407c9ada11af502fec05fb9dbbbca619f8f66"],["FunctionDef",["resume_node_tests"],415,"e7ff3bb27c77bd892ad5bb14f0e72a56038ab391f968abd4128cb005f06314bb","32cb9b4adbd9bc54f5db4d7649f59d7c15a8f500abe10cf4520bd310facbeaba"],["Assign",["CD_FACTORY_SOURCE"],13100,"b61813f70435a53cb9f6af1acb42b755b664bf1f979f4da7f3a142e1f4ee8354","3ba21d5d1af48fea98115c517b26326ef74a3bcc12629124fbbf9a4f8db903eb"],["Assign",["CD_EXTENSION"],32,"d79c4144ef027f67aafb5370474c73bf7c8a895a0ece5a165c57466756b6b19c","75c756c6a5bb8eaac7456c6d81bca80c0534dea60b212e5d07cc57de961b9782"],["Assign",["CD_HARNESS"],7770,"f1fb058c7ebb02801594a877a29e467396786c2ecc5fb7175d41aae44aea4348","c6bc43645bc1e2c8fae744a67ceb9f39e3c69787a1399008520a3c2b03957a4b"],["ClassDef",["LaterStageCallerTests"],49519,"4ecc1a9ccb7f76e84f84b3e4affb4fb7fe7c0d8fa6af38cbc1ff6e4404705cb4","fc7ea12edcf16db5764f455992bf0f0ba719cb041b21aacaa4044370e5faa8ca"],["Assign",["_D22_BROTLI_DATA_PROGRAM"],1062,"35f372dde5954be615231b1f48847c143a504d3b996733834c3ca2b65c77e097","0a9bbe79319cbcee1be2662ec65929e1abc54f73fb14c6b76b037817c71c91cb"],["ClassDef",["D22CompressionError"],190,"f086ca4a8285ea48db8f52884136f9b475c13216051e38c63aacee277c3881f8","6bc8886fa32a5cbb09ccaf38cb33700dac3c6da4a512c2f8a79058b6d711739b"],["FunctionDef",["d22_compress_data_v1"],14226,"a3c6d7495965066c91bc69c103a9ff6ea3607501795785abaef689be59f75841","7c4ea14c3da0e0dad9f9f0925d53e47d2dc3bf3615f26e3e5a772b906fae9a1e"],["ClassDef",["D22DataCompressionTests"],20858,"17bd46d29b8f22f1585d8eadb157676e50f1c6f58ee0c9eb29c31258667a9c75","963f654e6ce27ef97324d240a841b16b4f44cfdf3f13f8ef31efb5569e2e84dc"],["If",[],46,"adc075326e2b2c4151fa6bf03092887599f5f2ca5c53c46ecedfe045dc002c3e","444eddf8b0e49cc0b0fec1a7214dc0d852a2ac320c4e5f4e792895ff744a0420"],["Assign",["_D23_CASES"],90,"d1ccc92b3cb2874b6f4d8387e849750130c26fd5af1c4601bbc47ac6f0c36835","70fb1c104c2ae9219283cf053642a2f165fbb7edc3a5fbae58e9f703197ab98e"],["Assign",["_D23_DRIVER_CAUSES"],166,"a3f45b0588f8629d12ed98051bc55f9bd64f2af846ffaefc6580ffa1c740b798","19d07b09bf61aae84d2de52da0262fd63588af5e35edcfbaf5221bc2cfa95c4b"],["ClassDef",["D23CaseError"],187,"e53da0d70e6adba73391e2bbb166d35a23e7f60572764f87b9e4e275b9c1494b","2756fa9dcfd2c742b744e903452f0c9baae2bd90ee3434ba758bb2786464f003"],["ClassDef",["D23FixedDriverTransportTests"],34747,"86c0eb57b2c1a926315895b9f4039c250a89b1a9c16cbab14d4dbf5adb27fbf4","d1f7a45b7e7ed43e7e195955813aa1500cdc2c553af2de2f6972d0455153fd6e"],["FunctionDef",["_d23_run_fixed_driver_v1"],18006,"ffabfbc344b5025a1a8fc4136e6ee5126e54838722eb676471962f0acb9ff3f4","f2eb1ec43077f710bc0165d0cc3e38cbde9f8a826a0de0167569a9ebc77ca64b"],["FunctionDef",["d23_run_case_v1"],188,"2f4f89a7130f0c3ce54ff1451197cc2f772b208d175b6cc4d8ea9a2856b4b745","6b46120f71ad36468847feed4c6501fa6f073180a5eebdd1cb879ec54b57d0f2"],["FunctionDef",["d23_run_geometry_v1"],194,"6f341fd460c231b8aebcc5dced0ecfc7647899fc8416b7beda58f063bff8a804","091ed5fab5d7cb2eddf65d2f3bcfdc1dd9331371b07df5fcfb64718f6b2b15d9"],["Assign",["_D25_CASES"],90,"cce85803b7b76ce6d956c4a3b4421f61eca0c6704e2b9598371a8dbce420fa63","84b4e19d4ae29b540275b0e95a3984d253cd8ee2e1ef921461c1ba6b17b88e4d"],["Assign",["_D25_DRIVER_CAUSES"],166,"0648342962749298a7ced1ac44af6e247ec980fc9af112f14f9b4da06b231ae6","e5ee2eb3b686eb52653f51180d70cd971685336665b24e0ba0b9d12d044dbde8"],["ClassDef",["D25CaseError"],187,"68e8e2946ccbed4a98706d9dd5dbcaf31c389e5d13afc45145ab16bce7ff4af5","819e236a50e63b1d0550b808434e4922aa5532fcfacf3ecc32d476b4071997d5"],["ClassDef",["D25FixedDriverTransportTests"],37238,"6b1f2fc74679392263cdd2d78b441af65d50883dd7191c88e82b1946fdacfafe","34a09191666b1c534a45d137a0f40ca05bf48af5292de92c77b1b2ea4695daa8"],["FunctionDef",["_d25_main_module_v1"],1483,"0703151df5a51a36989d94027b0e2e3d3db1abf92c184815cc9a2bddba6d4266","a3271ba84ccd2d384ede392e98507f125d1e62137fb84bd70098236fcd26eaec"],["FunctionDef",["_d25_run_fixed_driver_v1"],18360,"57a1984b93812a2b71c78df7fc2919cd679d05ca8b5594fdcaad759d5f522b2b","d0c6cd5c024b2ade97ca9c98e74e99f4897d0112fec959898978dd62ca47aaa6"],["FunctionDef",["d25_run_case_v1"],188,"9dc8e23b53a829f506641e71187127c9cc76fc0780600f763a34d18920e7ea14","d229c829f2d9faf766c31b63e25f765c388256bdd46f5b03613be013d203f7c0"],["FunctionDef",["d25_run_geometry_v1"],194,"cd2cc0cd4529500e8a70b71c2cd1289ea6864b337d837e16e481ef31b706d4aa","62f3c220f6536d846302a4acc70818423e922c12d80d85a4bd8ba12bc9a03c27"]],"ordered_rows_sha256":"3f11dacd4c12f311a4c103d84eeb50917d7d7e58ee82efb8d578872c7c17c1b5","path":"tests/test_accepted_policy_fixture_compiler_gate2_resume_caller_v1.py","run_preparation_buffer_sha256":"77946ffadc24d7fd3759186417eb5ae330edd306f7a3170d5370f7e44b4e61b4","run_preparation_buffer_size_bytes":281307},"main":{"excluded_replaced_class":"D25CompleteGeometryTests","ordered_rows":[["Expr",[],83,"ea93def14fdf75254774e5405f5d3bdcf8bd95619275df28cb534bc9d96fbced","1ca4454741e887ca1b0eb661a0d9f6237663802a33f1443e5eb037e557b643e0"],["Import",["hashlib"],14,"ada1d9e0a360cda0fd1c8757d297aa74a4fc8d7193a69d3c28b43afc6950e9f9","092cb77ae0770f1627b29bf41b2732722fbcc3a0e1d77a79674801800a2721d1"],["Import",["io"],9,"b000f4590d6af9cfe633ffe0faae301a05dde8e4ca7757d7566f899d61f240b8","eb75a54c5d0d93fbb694f468951613f2f071166afbbe97a52903fa47a7cef914"],["Import",["importlib"],16,"856a29a936ceb53098a8d45c076bcb67d3b911d9303db4f7bca5b423ded40744","20dd306b163f704835a4d8a0b38ad62a3a816de1a848abef67a957450ae3afab"],["Import",["json"],11,"ff3e4d4dcf7250cae8d622d77c9a6d69aefcf4ab04ef9920218fafe93c0f1991","211ee42757705c7e350e70e36b762987a737f5e9c268f2a343e2dbfcb8fbea75"],["Import",["os"],9,"de2abade832c8e350a1bdc98cfcdb1e202ac4749c5fc51a4a970d41736b6df5c","ac3a74d6dd975a8e8fe4b7f85fce794793a9355595b850e3926964913948d386"],["Import",["tempfile"],15,"09d25239ae3d62e91c70b74fa5baa1d52a22c5c2397a785935889e61f91a8557","81dafa7a7cf16b83e7a7cafd7a6702e15f4b4d576a43463dc14beb05d48e72d0"],["ImportFrom",["SimpleNamespace"],33,"8b0a598b55e130e14987b275b2591e44a0aa9c53dea319ad51960b301df278e4","271cd8a5819453f6952690fd43e9ce152386df249c8de9a1999907454b0006b7"],["ImportFrom",["Path"],24,"6d69f2ac09017b8a49d050ab336e953b8fa02ae08c24396916ea7ea42418e627","59051b17634cdcb5a576ceb58fdc0a4e5652ed3b60d66667e92ddefd931abeca"],["Import",["unittest"],15,"a3133fe783a48c83eae67900c7bba9f417b6367ab7d4708836feaa3b2c88e60c","c2989ab60afe692e3752cff01ca6c5975c26cf4d65ed0ff66c3e1ddd0062fe42"],["ImportFrom",["contextmanager","ExitStack"],47,"c9cd8e36f19a542d5ed8ad61537e2d1a4c6b9258a6a2b9796896575b359b2090","d22cf07e9f53ee8b93c2bc711ecf3045f4ee535e4d409292cd952fad428ad930"],["ImportFrom",["patch"],31,"db6bbcaebdfb0f0644d49c0fd8832e64978afd6f50d08a54da1a8e1a0630e7c4","4337bb2ad9c9b8e6d80fa1b5afcef1e5d4531beaa533830f57d17fa8c1fbfed0"],["FunctionDef",["subject"],208,"acd1bdd385da32e06c71b2bbb12be814661d3b25177ebebb423b8951f973c8dc","d5f4e9c4f1b1cafaad1459c8b6704d2fadb865524d04722fa5109112031585f3"],["FunctionDef",["formatter"],273,"3461789e74b632116e2e4f28daf223fc279393da4e2d8fe1b6391588e29e318a","87258097f1101a631af47aa11f6a196226d24b5f2cfee852a6e5beebaf84b122"],["Assign",["WINDOWS_CALLER"],2168,"7f38fcd038d01a0e246a59154904b9d5556ded9830fdcf106f7fd31c508a15ee","cc7d248da2b6f9e0beb1c2bf61fcb7f36cf9afc1d91e3fb4b68cbeeb9dbd15bd"],["Assign",["NODE_WINDOWS_PREFIX"],1828,"e636c14cb2ba7795e6fa82e11dab1fdbfe9c256e401a4aea7d6fc5ffcd304cf0","369cb4fcedd59d807390160d264a5b9a8ef997ee7b4770f533090c2fab81bfea"],["ImportFrom",["PYTHON_CLOCK_HEAD","WRITER_COMMON_SOURCE","WRITER_HEAD","WRITER_TAIL","SETUP_COMMON_HEAD","WRITER_READY","CURRENT_WRITER_SOURCE"],224,"5bf4857f55a3f6168af3fa5eec0f15ecad52517674854a07eb59cac9bb191320","c2f066e751c5970fe8d22260d10a24651336e9a652fd3499a42a0bc640e3856c"],["FunctionDef",["_indent_python"],84,"bb2d70f5e44904c8f47bcb49c80488af00e2f22c01a6431fc030069ce5880313","6376f9aadaa7fd4aa39d4466f31cf13e5d64e0d34f43e643aa74229341d43eaa"],["Assign",["NODE_SHARED_PYTHON"],55,"46bebe5dc4c1bfa07d7e58a5ca5f287a67e2f47697dd90cba3679ad2aa8e96a0","6d51d339c2eb32bc892d6f12b9ce9c785a45633e56adbb746b055f929d931b08"],["Assign",["NODE_SETUP_HEAD"],92,"dd46a0d48c4c0c9b1a4b6b1f93adcc9db68a68e423f31e4725e00c388aa96a08","18ca0c18c72eeea93784bdba0366c0d1b1a791e686e78f5bc0950b5ba58b5fc0"],["Assign",["NODE_SETUP_TAIL"],1311,"9602690a610a304e55ad343a7aa84419c80cd48cc48461f05aabfde02f0cc48b","49488543423082ea11cfaf53a660078a6690a1428cccf3a6f307d06a7aa8324e"],["Assign",["NODE_SETUP_TAIL"],117,"1a437d758896cb511420cb32f601554d1acd1a2dc1ef8133111bcc5d926aac77","ea66a77de7cfdcc194887bac038883ca14ec3bec8f620ed2272d22c90dd1be12"],["Assign",["NODE_WINDOWS_PROGRAM"],71,"f35f1503db7c9e9d9537a40682f7d379dfb3f23d01ba59687f9c1ef25b56d11f","918f695ad171ef9e077bd6f869d5acd86fcbb93f3696194b110026fcc89836ae"],["Assign",["NODE_WRITER_HEAD"],66,"72d82322551277e8f9a4245406515c49b690d9c308190fc8312a6c0e479e0b89","c508669cc3652a523c78bf9a62c49164f0a2a6cd5610bd00012832b2384733b0"],["Assign",["NODE_WRITER_TAIL"],114,"64cf75b9a1741b3dbd9d38d5eea4bcb9386e45b9f13ef694daa396076b911996","02172aa12c8f81df4cda990dd22181b5191139cbe5980b472fb8343b9bee3ccc"],["Assert",[],82,"c5dff9c134a7d428595f32c651d3a1ebd5335c428a0c12b6e502ceaf0c80d4be","4c80074d8771649bb55c79efb88c64734df15156146cfa8cd4d7c28c199bb344"],["Assign",["NODE_FIELDS"],301,"9c081ff36e0be3e501b120f30049258d1e2baa37c81da3fb30849a2c84a899d4","f53035d74db2cbaffe2b9c737b8966fe4fb0b50f7ee0431c63c5635b8583ae59"],["Assign",["NODE_PIPE_FIELDS"],99,"3744367d550eb9c611f377b4ad2eafc39d17973f16956bdd997ea77498272573","647fbda326368caa2ccda236ff7240f8e0f9a0e59dce865242c420d2adbca145"],["Assign",["NODE_CONTROLLER"],8738,"0dfa650625273068d1ced5d2b484351bf6c9210f853ab71bc3828c077dfc3898","aac87d2734b4fdaee2b7cef6fb59b22ccbb574e39409c8632219ab8c119c04f8"],["Assign",["NODE_FINISH_BODY"],1976,"272d0b346cc63e59becc245479a45a5ed81c3871174eca1393eabdb0602a0597","2e8fb66d0fe9c72d92102549d30b4c2f98707d4192fc7cf7b2560bc05cefc988"],["FunctionDef",["_inert_control_source"],3636,"76dd72b1a4d8eeae94e097aec05c35e30d47654f4d09c5d5108ee96ec7502eba","4b3d450e742a4c07a9f7974458407e4e05862596fc3208b5d15f925237896726"],["Assign",["INERT_CONTROL_EXPECTED"],436,"e22f6728c55424e1dc289f9c48436e2e3da52bc11ba43fd6017040e067e6ec04","897694ac774bd292d2c8083bff0ed08350e5572315e0c863867a9188697f22ac"],["Assign",["INERT_CONTROL_SOURCE"],46,"14ae9c81454ed1185b2e3c1fbc7938a17d4f80807ff9ea4acada88056e23562e","cda6efcff302955d254b0d393e38fcf69e75b89f45f23c422839d6898ca478f2"],["FunctionDef",["inert_control_cases"],3418,"57582cdc06005b82fda9d62d247590c3174bfc417f2580ac70d73f9ac6e2a2d1","277cea6129011207384f923689d921dc5a806d40bcbb7b452556ce087c1df41a"],["Assign",["INERT_HARNESS"],3138,"c62e22de834128495defc1e1706986945893e4d3895010a4dacdbe401d6607de","34a95d2a996e7f71d646d80b5d4e482d963c68bd5af3257954614f6eb3e34016"],["Assign",["NODE_HARNESS"],12117,"3dc5cc015c73c2af9c8955387da0dd1050c21301241cf29c87d3985d9d382e11","4f02a29a0c6417323e755f3b0404e9161135ee8d3cb9299ebf78536da0f21fe1"],["Assign",["NODE_DECODE"],1832,"17a52317d9fe94c2a53871282b5269d8d3e99879f513688b41c22f13b0c4a3b4","696afd5fd3745bb0ba5a96d68dfa8093e924461d3658ad5715afef5cac9140c5"],["Assign",["ROOT_ENCODER"],2683,"0fd891ebc644f959e569b01799052d83b44cfed2771145017966ea590fddf9f3","ec594cfe4972cd80cbe45680e898f327a3047e02cf61dca8d54cef73033dcd5d"],["Assign",["NODE_INNER_VIEW"],1327,"6c3f35e6a3cb832c77553cefcf903a1bebc10e48438cbc14e3ab9d76db359244","5387b6fa64ac93dee77c68423f3be65deb00012cd4f3cfeda5188415e01ca559"],["Assign",["NODE_VALIDATORS"],3098,"b7bebb8ae64df8ddade1c600bb7959ca0534e598b4de04ca620c421f613b5f5c","320cba936fe30fb9f28d9a76b48724d42c01e546ed5a5a5bec52cbedae828d41"],["Assign",["NODE_WRITER_VALIDATORS"],4847,"77b368e563206b5a0fcce9d3912240d08b0f640f86bbe5439a8a946284f2eb7e","66306f0ef96be20a0c94a54bd7b1d191ff3bad7fb09e7123cf50560766abc56d"],["Assign",["ROOT_SHA256"],1723,"2202455ca5b1f50605e9a22a7d3967186cbbb66d6605ba93fada8e2c01a18f4c","1be696395a15211aa61defd05bc84aa2db9239a5d3530e2027e5609db55865c0"],["Assign",["ROOT_ORCHESTRATOR"],3972,"952592ab9d3181ec370cb13ecd27a180e39684fa0f1674a5e76b629ef1e1c0f9","8e1b5a74eec21ff317873166fdf72223ba40f34dda45e454d133cfd4f19e9e3d"],["Assign",["ROOT_RECEIVER"],11231,"6c2e19d046b423ac7295061731ebc577515de259df4d41dab24c3281ac0ad16b","99635e4b09a66c22b075061eea3310c2c57016f73614da6d69a886c6b043f71d"],["Assign",["EXECUTOR_INERT_JOURNAL"],2331,"b4dda89921010a1b934f1958e246b0f1d23f2bd2428c0c5f895b004c4ff667e6","389b8a128426d22de1b78cfdb4713d4ea33067d0241cef5544b60639b1bafe06"],["ClassDef",["ResumeRootCaller"],30374,"c7a01ebf6042aaccf33d8de1cc6c8e6fd074a96ede589c5cd9a56057fca8e0ca","aa07ea6870decb2a3b5cc11178978c1bc6d4e71024c8256a3357b1ea497b23ff"],["Assign",["INERT_CONTROL_CAPTURE"],3826,"2d76d1992ff70cdf7be3708bc62eca79618b48eed2168e8d5224f3e58da9d186","29b77343190347a7186c093842af198225851093ae386e1a9cd61026b5776aa3"],["Assign",["INERT_CONTROL_RECEIVER"],2400,"066d87973d742782ad9e942f704d7c8cd3c350c1a24f2658d09a271e22a91af2","67580a4083a9651cd2451e0bcba8493e17d54fa5a350db2a75e4713d4dba6d51"],["FunctionDef",["inert_control_executor"],658,"122f218bfb7498484cc677183c2d80ca7bcd463168a0d01da2698686221c298e","601af4c88ec51e9a3c92133a703b30a64a80c132d1ffe6c3b7d07ff15f7d68d7"],["ClassDef",["InertControlTransportTests"],15315,"18f2ff44724183ffe37892b4dded4b41174f84e4bb3d672a566146008daf29af","bfa886521a0fc01fb7a90d3dc7d2256c8c60c0020021f36b584163a8b19f9818"],["ClassDef",["ResumeNodeCaller"],54248,"15a22aceb16a82fac89c05fa5af3df5c81fc5f1bf18f3916e6cf268a5720e8be","e5a44e2ad30e9d1708342db596f5ceaf8aa51d72208674c08ed624303b36cfae"],["ClassDef",["ResumeBoundaries"],58347,"bdd4c8722f5f9cf228e9252de9face349d53d37e755736fd1f2c0f1dcb1bdc1f","67076b39ab307d846b2949777093e94debff303a2ced5e05a38d3ff8a4b56916"],["FunctionDef",["d22_sha"],55,"721db2d8288fd1b192071b762bd90cf3b0564a29d6c965131671951a1502e4ef","91b4de13c7757a1f065feccda4c1edd0c34cb747f91db33fa2bf9f1f4f2b19a5"],["FunctionDef",["d22_canonical"],140,"c4b0bcf386b0f22437f616213f4f723be3d04677193b47b2d0f82f5fa7ba79b1","16dc7dac764073b5d0374a5885706a2a3361c2b9feab7db646d0ef5de0f0a7a2"],["Assign",["D22_PREFIX"],311,"68d5e147ff8e6c10240077949c1ed6af2adab087b81594d5404cdf82cd54c30b","b75654ea920a3d87d6d773efb9194f1f186ffb273b8c6f34279df722789fb848"],["Assign",["D22_IMPORTS"],219,"6574e5b157e60d3362290c8a7a0bb71acac676b32a78e8c354b976d8e4bcc419","daab94cb981481406d839bf8d92a99f149214e238324e4aa8e59b1f87c02d741"],["FunctionDef",["d22_build_plain"],3590,"7d7c0a586e495ec7f2070ce476f2dd4eb89de40fb8e994fcc4777799b9467b8b","afdf734f5ea09e37082127b37c116bdd3b189c17e304c594815749f1200dbbfb"],["Assign",["D22_OPS"],181,"1eec6dbf6f1e5e277c629a6e1eed1a5a2fbd1d3925e8959324fbcffaf528cd92","2a4c42d9344614ecf238a089513e861516af46a99dd073e92e9f874f51326425"],["Assign",["D22_NON_END"],114,"0d5a07910d32762c7bdae1a036081b0784f6503dcb4f08a2a6f4ff707c9b4feb","386aca9d33bfce0883b002c01bf6d507ffd78b58cb974c9a5d14bc31176ffa30"],["FunctionDef",["d22_lex"],1597,"b512aca7c9d9aee5dcb9188102a82a98cb5d12b3a17d7e83a6a50691689ec02d","2adc7443166f1c7d5c34ab842a686a2bbeb01e92428a7b49af883ee56916e27d"],["FunctionDef",["d22_pairs"],69,"78b835201408cc00c5919847a5144d927815170627c5444f7803f7db5dc569bc","256ffbc0e0f3368095ed854e5007cdb7e9b2d48341eb33fd09dc4c814c6d35ba"],["FunctionDef",["d22_join_tokens"],683,"a86c3632fc64c05ef952b629bb375700d601f1229cdf5fc7c219e685ffea279f","812233b87daa295605992ad71e9540e73434894d524d3b36f400ee5d2196d97b"],["Assign",["D22_PROPERTY_ALLOWLIST"],500,"047418f9f886a689e1cd455255887d27baedd9624ff7a3a7614f7ae65f25395b","393ab42277513b0ea40bb99cd8452e793d1a0860a083d4d46bfe36969a1b6961"],["Assign",["D22_PRIVATE_MAP"],251,"c7cd41f4cfcf5d8665ed7bfd6cb7f166a7199f683bcee42567a1ede5605162f4","e4f71dec148d14d4dcc965d9a84a4257af69af846d318b4e0aff3847f44cc691"],["FunctionDef",["d22_transform_body"],1762,"82f4d8428582c4759275db736d92f1a7e2ba0880f7b18901a57e6b80cba32139","96d9a7f4b3904227b2e3009b6ef6319a6dd4e8a672e99bd732682343c39df9d0"],["FunctionDef",["d22_shorten_private_prefix"],417,"bb21df2fd4bd4d872c5bb2626e016b2e246b9ff01d72e5170d47ab34dd7c1ee2","755335bbbb00acf8c8039b8e50c1fe88d158c538ba5d71b299c40497351ef5e2"],["FunctionDef",["d22_phase_initial_v1"],7509,"e0a028a01a21949622059803b62dccf7493d430d1d00124a2f631b1e9c6d36d0","87f72de20ac341000a8753fbfdc3b4a0a2c65a0ab231a9576bd5a4ee55e37558"],["ClassDef",["D22StaticPhaseConstructionTests"],3437,"8c6f87ccc96d3ab842a41ba3a663ff801e3ab5427e5fce70d360529338c7b341","9ce2ed33ff6588941b635d5e2ab71baf6651f479b6558dd65ca5639b202afb6a"],["Assign",["D23_WIRE_CODEC"],5889,"b9b04bddcd571b0a48b478b339a15fbf48f47b0b91a4ba2afebf2338b4805c5a","71de5f58d1821a00ad311350b9db4ab9f68780cc26ab8fbc3f9cd16c376ae8a2"],["Assign",["D23_DATA_DRIVER"],8102,"69bfd41dd811a8d0047e9e08c64b2156b34824ad688beb2b7fbf9b4456b86450","75f264688e08f17442d13f526f24608ee2ebec2639b932d28e069eec49174ac0"],["FunctionDef",["d23_node_driver_v1"],206,"a08505e632d12380a3460b891605f27977e68c4833162f15a50cbb4e9b5a921a","29bb3defe80190c870679a5e49bdddac82f28c3fe7b2f16961c3a83ac021263f"],["ClassDef",["D23WireCodecTests"],1337,"0d72e2a55ea3d2ff87585ce81f7877cc758f2d1cab761622a506bd4e1a1c9e0a","4772937caf6e4ae890c48a63d0e34bed4cf2a812ba49c9eb80f715960a7dd702"],["FunctionDef",["d23_finalizer_source_v1"],4969,"fd1c46d44200d3c5281c9ad85d60381fa2ab905708f4ffecd5b4ea3a4d2d6e30","33957ed3ce1a423dcab18174c05c61a129bfbbbd68e0b3d0dac359fff1200e9d"],["FunctionDef",["d23_root_wire_sources_v1"],9830,"44644acf9d0c4c25d9baab564f50b0ec3fe06b8c8e7a4b244db277c6d3de6ffb","4fc5b6a4eef02ac484fdbc2c547b08b2259fba66a07ab1871e303656907c0a59"],["FunctionDef",["d23_inert_bundle_v1"],13423,"8bf937c543d6296b952e1baddcd98378ba2b86b17faad3c4db641c2f4afdeb51","6ba2778d8347d1da18965e96e95f2e629f8b32cf67fb5dbb75c66b75c48d3548"],["Assign",["D23_GEOMETRY_DRIVER"],11098,"b2b3609610211d9514474350843ce54dcc71afd7255ad0c59daf62f5c6c9918c","3ff3771fe68869ca8953d3e9f2efb09bab008af07b90e4547875253cad44661c"],["Assign",["D23_GEOMETRY_STDIO"],2261,"9c1ee0a899345e40ad9953f09e3058673baa58f27e21fcd286e9d9c6f275db88","bc85ea4ea843310332227a1f9ce917f3552b09b1e37d59c32e86a17ccb643926"],["FunctionDef",["d23_geometry_driver_v1"],169,"bea5477f2ce5a3998ef38f14e555c35e11260636accd38524031d46780f1d449","b4543a621e8000508343aa817c7160df58726fdc5bd2a43c2209b7d510a05700"],["ClassDef",["D23CompleteGeometryTests"],23145,"17fe12460e3b7031f8d83388453fee01a065f52559c6249c75c4b99476b0cd98","e3e19ddabe03c418e83f53d34ac8817db7e025fd5e357cf9c2c25d140cb8093d"],["If",[],46,"adc075326e2b2c4151fa6bf03092887599f5f2ca5c53c46ecedfe045dc002c3e","444eddf8b0e49cc0b0fec1a7214dc0d852a2ac320c4e5f4e792895ff744a0420"],["FunctionDef",["d24_phase_initial_v1"],11838,"8284e6485edda6d9f8b65056c57c0d2a8ee3f4ca052e96cc6baa23c369fcdeef","9799dd267c388a1ef37938c9d161386ddf8d438f9dded4fb8bbda7f775772520"],["FunctionDef",["d24_node_codec_v1"],1552,"36d68281b8d62bb217e903310d44f8f6297211a4e73df121dcf42c6f2c4b4cd8","4325ed9c32089c950077acd684a6de2d48bca6f5cd1c0076ba072cadb5c43f81"],["FunctionDef",["d24_inert_bundle_v1"],15926,"ab0d46817a5925080ff5a80062539cc83e043b201c256d1aa3f26d9376f91c67","906111c7bc3748ea531543ff6d321d9faa664a47964b22cec5252f27b8049f8d"],["ClassDef",["D24CompleteGeometryTests"],36198,"65f0c1e198fc463910d4faa60d187b9abb07b4826701dfd24d3456534ebce219","b3f6ddf4a52b63293e6ee0474c2189e944716982d36b243959df9baf60716ca0"],["Assign",["D25_DATA_DRIVER"],13306,"dff6560146ac5173c5e4f2dfa2be9109ed42223977bcb495c7635f5f445a4057","ae37bfa67c65d43a5a02fe8e5f22e7d22ac0d16d198be0fe602febdc12c5fe89"],["FunctionDef",["d25_node_driver_v1"],154,"20339a2670b45fb754283fbaf9207486387ed1a738319ff0a1d15b2026fa625a","2829224bb0fb5994e6962a31aadd683b1b572225217f5cbb58fc8489515edb2f"],["ClassDef",["D25WireCodecTests"],1443,"2317ad9fe8c3bb47726b23fff678193e3177b09995783855e79ee3c0999bebf4","bb86fa945c2785b9be3baca20ca66e8ea14168b61dee09aa7e887e26bd73b87b"],["Assign",["D25_WIRE_CODEC"],6927,"b90c240ab681ff11f49b0c5712e96f9eb08309250678da2f65218e87ab3a4ff5","7668aa6a27c641ebc96478e67d0d98c63833e001969734702d50e91fb5c3efe9"],["Assign",["D25_CODEC_SOURCE_PINS"],267,"c2f9ff6ee3038e2182d558299e326fe8863648d3c88c034de725101c081d0f94","edfba8861053fd2d9cfe35d181d98e85811db4777fc6959203da93cdc6ddb945"],["FunctionDef",["d25_node_codec_v1"],2238,"1211d4016aea5991d208382cf80d19b931edff7e4dde69977ad6cf8ca4c27d97","ac9bf831b83069b4c11f2bc2ad362f0b9ec1189b784e08c53e405ed71eeed5c9"],["FunctionDef",["d25_finalizer_source_v1"],964,"b0a9b0f05ecc10fe2cfa064255f1aa5f9738f1867093712aa1eaf8fde6d48ceb","73adf517dc636124504c662b52edbe8ae286304ba197b2845d0044c451b381fb"],["FunctionDef",["d25_root_wire_sources_v1"],1016,"032379feeb1ddad1968058f47ec8b579721e5d0095b56cdcaf6dc5fbcb8de440","6d99d45015a46579b6e0165b86071b4f4c07a6b341431f000b5230e3cbe3d528"],["FunctionDef",["d25_inert_bundle_v1"],17118,"b2c65789a59beb69ba9cf68a4bbde3b85887d5f40d3406fa81aa3fbaa4e36ad7","8c570e17a1e5ddf700f7837a2cce296f86f589236591254b39e32052d3b27fbe"],["Assign",["D25_GEOMETRY_DRIVER"],11425,"5409ee9730a62af2423d9fa380185b1dfda15f11979ef50ef350915ca270680d","410ca3efa16fc2cdb2baf3d605a4b431b2fa7d23a3621da4dc00e454bc3f51d2"],["Assign",["D25_GEOMETRY_STDIO"],2279,"075d1aac0b5e035a15507604fe0b076dbf0d9ea7bd35084b56932e8fa048290e","d0a83542e9466c45af922c3db568cd10de251ae70a3b12f37878b24855658690"],["FunctionDef",["d25_geometry_driver_v1"],1212,"e20bc08b1ca6a13250c6471322725e0f3827c88a68490b23b79c6f9d5043964e","3035bec91deee2eaa7ffa7391e11d56e788d3031cd003d489ffc7e0d2646ef6e"]],"ordered_rows_sha256":"041c6a7318a4af8d4b917f6bc0fd16d1807d956292c9e9dcc3cdaabb86c78a11","path":"tests/test_accepted_policy_fixture_compiler_gate2_resume_v1.py","run_preparation_buffer_sha256":"3dcea0ea515be7c33cd95486adf9b818b63ce39894d9cbe48c8318ec4fd02b39","run_preparation_buffer_size_bytes":476378}},"root_tool_observation":{"attribution":"root_observed_tool_result_not_child_self_receipt","exit_code":1,"tool_chunk":"20e86c","wall_time_seconds":1.4429275},"schema_version":1,"source_guard_policy":{"allowed_future_extra_nodes":"append_only_unique_undecorated_declarations_or_literal_simple_assignments_no_protected_binding_reuse","future_assignment_name":"_D25_GEOMETRY_RETAINED_RESULT_V1","protected_top_level_decorators_absent":true,"raw_AST_hash_diagnostic_only":true,"source_text_authoritative":true},"source_row_format":["AST_node_kind","bound_names","source_segment_size_bytes","source_segment_sha256","author_runtime_AST_diagnostic_sha256"]}\n'
