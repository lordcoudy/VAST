"""Controlled exception tests. No WSL, Docker, P0 or physical stage is launched."""
import hashlib
import io
import importlib
import json
import os
import tempfile
from types import SimpleNamespace
from pathlib import Path
import unittest
from contextlib import contextmanager,ExitStack
from unittest.mock import patch


def subject():
    importlib.import_module('tests.fixtures.accepted_policy_fixture_compiler_component_v1')
    return importlib.import_module('tests.fixtures.accepted_policy_fixture_compiler_gate2_resume_v1')


def formatter():
    import sys
    path=str(Path(__file__).resolve().parents[1]/'scripts')
    sys.path.insert(0,path)
    try:return importlib.import_module('tests.fixtures.accepted_policy_fixture_compiler_gate2_c_v1').resume_terminal_v1
    finally:sys.path.remove(path)

WINDOWS_CALLER = """import time
w0=time.monotonic_ns()
status=1;raw=None;secondary=[];failure=None
try:
 import os,sys,stat,hashlib,types,pathlib,json
 p=pathlib.Path('C:/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/tests/fixtures/accepted_policy_fixture_compiler_gate2_resume_v1.py')
 def check():
  if time.monotonic_ns()>=w0+140000000000:raise RuntimeError('bootstrap_deadline')
 def epoch(s,cross=False):
  return (s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,getattr(s,'st_birthtime_ns',None),None if cross else s.st_ctime_ns)
 check();before=p.lstat()
 if p.resolve(strict=True)!=p or not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or not 0<before.st_size==int(sys.argv[3])<=32768:raise RuntimeError('bootstrap_kind_bound')
 check();fd=os.open(p,os.O_RDONLY|os.O_BINARY)
 try:
  check();opened=os.fstat(fd)
  if epoch(opened,True)!=epoch(before,True):raise RuntimeError('bootstrap_open_drift')
  raw=os.read(fd,32769);check()
  if len(raw)!=before.st_size or hashlib.sha256(raw).hexdigest()!=sys.argv[4] or epoch(os.fstat(fd))!=epoch(opened) or epoch(p.lstat())!=epoch(before):raise RuntimeError('bootstrap_binding')
 except BaseException as error:failure=error
 try:os.close(fd);check()
 except BaseException as error:
  if failure is None:failure=error
  else:secondary.append('bootstrap_close_'+type(error).__name__)
 if failure is not None:raise failure
 m=types.ModuleType('gate2_reviewed_operator');m.__file__=str(p)
 check();exec(compile(raw,str(p),'exec'),m.__dict__)
 status=m.main(sys.argv[1],sys.argv[2],_original_start_ns=w0)
except BaseException as error:
 try:
  value={'completed':False,'physical_acceptance':False,'causes':[str(error).encode('ascii','backslashreplace')[:48].decode('ascii')]+secondary,'omitted_or_unknown':True,'windows_start_ns':w0}
  if type(raw) is bytes:value.update(source_bytes=len(raw),source_sha256=hashlib.sha256(raw).hexdigest())
  output=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')+b'\\n'
  if len(output)<=2048:check();os.write(1,output);check()
 except BaseException:pass
raise SystemExit(status)
"""

NODE_WINDOWS_PREFIX = r"""import time
_g2_anchor=time.monotonic_ns()
import os,sys,json
_g2_first=None;_g2_secondary=[];_g2_written=0;_g2_extent=False;_g2_closed=False
_g2_ready=(str(_g2_anchor)+'\n').encode('ascii')
try:
 if not 0<_g2_anchor<2**64 or len(_g2_ready)>32:raise RuntimeError('ready_anchor')
 while _g2_written<len(_g2_ready):
  try:_g2_n=os.write(3,_g2_ready[_g2_written:])
  except BaseException:_g2_extent=True;raise
  if type(_g2_n) is not int or not 0<_g2_n<=len(_g2_ready)-_g2_written:
   _g2_extent=True;raise RuntimeError('ready_short')
  _g2_written+=_g2_n
except BaseException as _g2_error:_g2_first='bridge_ready_'+type(_g2_error).__name__
try:os.close(3);_g2_closed=True
except BaseException as _g2_error:
 _g2_label='bridge_close_'+type(_g2_error).__name__
 if _g2_first is None:_g2_first=_g2_label
 else:_g2_secondary.append(_g2_label)
try:
 _g2_ack=sys.stdin.buffer.readline(8)
 if not _g2_ack.endswith(b'\n') or not _g2_ack[:-1].isdigit():raise ValueError()
 _g2_ms=int(_g2_ack[:-1])
 if not 0<_g2_ms<=150000 or (str(_g2_ms)+'\n').encode('ascii')!=_g2_ack :raise ValueError()
 w0=_g2_anchor+_g2_ms*1000000-150000000000
 _g2_now=time.monotonic_ns()
 if not _g2_anchor<=_g2_now<w0+140000000000:raise ValueError()
except BaseException:raise SystemExit(1)
if _g2_first is not None:
 try:
  _g2_out=json.dumps({'completed':False,'physical_acceptance':False,'causes':[_g2_first]+_g2_secondary,'ready_written_bytes':_g2_written,'ready_extent_unknown':_g2_extent,'ready_close_completed':_g2_closed,'omitted_or_unknown':True},sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('ascii')+b'\n'
  if len(_g2_out)>600 or not _g2_anchor<=time.monotonic_ns()<w0+140000000000:raise ValueError()
  if os.write(1,_g2_out)!=len(_g2_out):raise ValueError()
 except BaseException:pass
 raise SystemExit(1)
"""
from tests.test_accepted_policy_fixture_compiler_gate2_resume_caller_v1 import (
    PYTHON_CLOCK_HEAD, WRITER_COMMON_SOURCE, WRITER_HEAD, WRITER_TAIL, SETUP_COMMON_HEAD, WRITER_READY, WRITER_SOURCE as CURRENT_WRITER_SOURCE)
def _indent_python(text):return ''.join(' '+line+'\n' for line in text.splitlines())
NODE_SHARED_PYTHON=_indent_python(WRITER_COMMON_SOURCE)
NODE_SETUP_HEAD=PYTHON_CLOCK_HEAD+'try:\n import os,sys\n'+_indent_python(SETUP_COMMON_HEAD)
NODE_SETUP_TAIL=r"""first=None;secondary=[];written=0;extent=False;closed=False;entered=False
try:
 ready=(str(_ready)+'\n').encode('ascii')
 if not 0<_ready<2**64 or len(ready)>32:raise RuntimeError('ready_anchor')
 while written<len(ready):
  try:n=os.write(3,ready[written:])
  except BaseException:extent=True;raise
  if type(n) is not int or not 0<n<=len(ready)-written:extent=True;raise RuntimeError('ready_short')
  written+=n
except BaseException as e:first='bridge_ready_'+type(e).__name__
try:os.close(3);closed=True
except BaseException as e:
 if first:secondary.append('bridge_close_'+type(e).__name__)
 else:first='bridge_close_'+type(e).__name__
try:
 selected,end,buffers=prepare()
 if first:raise RuntimeError(first)
 op=module(buffers[1],1);gate();entered=True
 status=op.main(sys.argv[1],sys.argv[2],_original_start_ns=end-150000000000);gate()
except BaseException as e:
 if entered or gate is None or denied:raise SystemExit(1)
 try:
  out=canon({'completed':False,'physical_acceptance':False,'causes':[str(e)[:48]]+secondary,'known':facts,'ready_written_bytes':written,'ready_extent_unknown':extent,'ready_close_completed':closed,'omitted_or_unknown':True})+b'\n'
  gate()
  if len(out)<=600:os.write(1,out);gate()
 except BaseException:pass
 raise SystemExit(1)
raise SystemExit(status)
"""
NODE_SETUP_TAIL=_indent_python(NODE_SETUP_TAIL)+'except SystemExit:raise\nexcept BaseException:raise SystemExit(1)\n'
NODE_WINDOWS_PROGRAM=NODE_SETUP_HEAD+NODE_SHARED_PYTHON+NODE_SETUP_TAIL
NODE_WRITER_HEAD=WRITER_READY+'try:\n'+_indent_python(WRITER_HEAD)
NODE_WRITER_TAIL=_indent_python(WRITER_TAIL)+'except SystemExit:raise\nexcept BaseException:raise SystemExit(1)\n'
assert NODE_WRITER_HEAD+NODE_SHARED_PYTHON+NODE_WRITER_TAIL==CURRENT_WRITER_SOURCE

# Exact persistent Node caller text is tested with controlled module/OS boundaries.
NODE_FIELDS = ('pid','returncode','signal','exited','closed','pipes','causes','unknown_closure',
               'completed','terminal_observed_ms','physical_acceptance','clock','ack_ms',
               'stdin_finished','stdin_closed','stdin_bytes','stdin_sha256','stdin_extent_unknown','source_facts')
NODE_PIPE_FIELDS = ('bytes','sha256','eof','closed','error','encoding','chars','remainder_unknown')
NODE_CONTROLLER = r"""if(Object.hasOwn(globalThis,'gate2Resume'))throw Error('state_exists');
var g2p=globalThis.performance;if(!g2p||typeof g2p.now!=='function')throw Error('monotonic_unavailable');
var g2t=g2p.now();if(!Number.isFinite(g2t)||g2t<0||g2t>Number.MAX_SAFE_INTEGER-150000)throw Error('original_clock');
var {spawn:g2s}=await import('node:child_process'),{createHash:g2h}=await import('node:crypto'),{brotliCompressSync:g2c}=await import('node:zlib'),g2fs=await import('node:fs/promises');var g2py=__COMMON__;
var g2=globalThis.gate2Resume={start_ms:g2t,work_ms:g2t+140000,end_ms:g2t+150000,last:g2t,calls:0,fields:__FIELDS__,pipe_fields:__PIPE_FIELDS__,sources:__SOURCES__};
g2.python_common=g2py;
__VALIDATORS__
g2.now=()=>{let n=g2p.now();if(!Number.isFinite(n)||n<g2.last)throw Error('clock_regression');return g2.last=n;};
g2.held=[];g2.source_facts=[];
g2.auth=async()=>{for(let [path,d] of g2.sources){if(Object.keys(d).sort().join()!=='git_blob,sha256,size_bytes'||!Number.isSafeInteger(d.size_bytes)||d.size_bytes<1||d.size_bytes>32768||!/^([0-9a-f]{64})$/.test(d.sha256)||!/^([0-9a-f]{40})$/.test(d.git_blob))throw Error('source_descriptor');let f=null,first=null,secondary=[],raw=Buffer.alloc(d.size_bytes+1),n=0,closed=false;
 let epoch=(s,cross=false)=>[s.dev,s.ino,s.mode,s.nlink,s.size,s.mtimeNs,s.birthtimeNs,cross?null:s.ctimeNs,s.blocks].map(String).join(','),gate=()=>{if(g2.now()>=g2.work_ms)throw Error('source_deadline');};
 try{gate();let a=await g2fs.lstat(path,{bigint:true});gate();if(!Number.isSafeInteger(d.size_bytes)||d.size_bytes<1||d.size_bytes>32768||!a.isFile()||a.nlink!==1n||a.size!==BigInt(d.size_bytes)||(await g2fs.realpath(path)).replaceAll('\\','/').replace(/^c:/,'C:')!==path)throw Error('source_kind');
 gate();f=await g2fs.open(path,g2fs.constants.O_RDONLY|(g2fs.constants.O_NOFOLLOW||0)|(g2fs.constants.O_NONBLOCK||0));gate();let b=await f.stat({bigint:true});if(epoch(a,true)!==epoch(b,true))throw Error('source_open_drift');
 while(n<d.size_bytes){gate();let r=await f.read(raw,n,d.size_bytes+1-n,null);gate();if(!Number.isSafeInteger(r.bytesRead)||r.bytesRead<=0)throw Error('source_eof');n+=r.bytesRead;if(n>d.size_bytes)throw Error('source_bound');}
 gate();if(epoch(await f.stat({bigint:true}))!==epoch(b)||epoch(await g2fs.lstat(path,{bigint:true}))!==epoch(a)||g2h('sha256').update(raw.subarray(0,n)).digest('hex')!==d.sha256||g2h('sha1').update('blob '+n+'\0').update(raw.subarray(0,n)).digest('hex')!==d.git_blob)throw Error('source_binding');gate();
 }catch(e){first=String(e.message).slice(0,32);}
 if(f)try{await f.close();closed=true;}catch(e){if(first)secondary.push('source_close');else first='source_close';}
 g2.source_facts.push({cause:first,secondary,read_bytes:n,read_sha256:g2h('sha256').update(raw.subarray(0,n)).digest('hex'),open_completed:!!f,close_completed:closed,unknown_closure:!!f&&!closed});if(first)throw Error(first);gate();g2.held.push(raw.subarray(0,n));
}};
g2.send=(s,raw)=>{if(s.stdin_attempted)throw Error('stdin_once');s.stdin_attempted=true;s.stdin_bytes=Buffer.byteLength(raw);s.stdin_sha256=g2h('sha256').update(raw).digest('hex');s.stdin_extent_unknown=true;try{s.child.stdin.end(raw);}catch(e){s.stdin_failed=true;throw e;}};
g2.track=(p,limits,end,data,eof)=>{
 let s={child:p,pid:p?.pid??null,returncode:null,signal:null,exited:false,closed:false,causes:[],rows:[],ack_ms:null,stdin_finished:false,stdin_closed:false,stdin_bytes:0,stdin_sha256:null,stdin_extent_unknown:false};if(!p)return s;
 p.once('exit',(r,z)=>{s.returncode=r;s.signal=z;s.exited=true;});p.once('close',()=>{s.closed=true;s.wake?.();});p.once('error',()=>{s.causes.push('child_error');s.wake?.();});
 p.stdin.once('finish',()=>{s.stdin_finished=true;s.stdin_extent_unknown=!!s.stdin_failed;});p.stdin.once('close',()=>{s.stdin_closed=true;});p.stdin.once('error',()=>{s.stdin_failed=s.stdin_extent_unknown=true;s.causes.push('stdin_error');s.wake?.();});
 for(let [i,pipe] of [p.stdout,p.stderr,...(limits.length===3?[p.stdio[3]]:[])].entries()){
  let r={bytes:0,hash:g2h('sha256'),raw:[],eof:false,closed:false,error:false,stopped:false};s.rows.push(r);
  function fail(e){r.error=r.stopped=true;s.causes.push(String(e.message).slice(0,32));if(!s.stdin_attempted)try{g2.send(s,'');}catch(e){s.causes.push('stdin_close');}s.wake?.();}
  pipe.on('readable',()=>{if(r.stopped)return;try{for(;;){if(g2.now()>=end)throw Error('pipe_deadline');let b=pipe.read(Math.min(4096,limits[i]+1-r.bytes));if(b===null)break;r.bytes+=b.length;r.hash.update(b);r.raw.push(b);if(r.bytes>limits[i])throw Error('pipe_overflow');data?.(s,i,r);}}catch(e){fail(e);}});
  pipe.once('end',()=>{r.eof=true;try{eof?.(s,i,r);}catch(e){fail(e);}});pipe.once('close',()=>{r.closed=true;});pipe.once('error',()=>fail(Error('pipe_error')));
 }
 return s;
};
g2.adopt=(p,...args)=>{try{return g2.track(p,...args);}catch(e){let s=g2.track(null);s.child=p;s.pid=p?.pid??null;s.causes.push(String(e.message).slice(0,32));s.stdin_extent_unknown=true;if(p){let input=false;for(let [emitter,label] of [[p,'child_error'],[p.stdin,'stdin_error'],[p.stdout,'stdout_error'],[p.stderr,'stderr_error'],[p.stdio?.[3],'ready_error']])if(emitter)try{emitter.on('error',()=>{if(!s.causes.includes(label))s.causes.push(label);});if(label==='stdin_error')input=true;}catch(e){let v=label==='stdin_error'?'stdin_listener_failed':'listener_error';if(!s.causes.includes(v))s.causes.push(v);}if(!input){if(!s.causes.includes('stdin_listener_failed'))s.causes.push('stdin_listener_failed');}else try{g2.send(s,'');}catch(e){s.causes.push('stdin_close');}}return s;}};
g2.wait=async(s,end,cap)=>{let n=g2.now();if(n>=g2.end_ms)throw Error('original_deadline');if(n<end&&!s.closed&&!s.causes.length)await new Promise(done=>{let t=setTimeout(done,Math.min(cap,end-n));s.wake=()=>{clearTimeout(t);done();};});return g2.now();};
g2.snapshot=(s,kind,clock,n,cutoff)=>{
 let raw=[],pipes=s.rows.map(r=>{let b=Buffer.concat(r.raw),encoding=b.every(v=>v<128)?'ascii':'base64',v=b.toString(encoding),z=g2c(b,{maxOutputLength:4096}).toString('base64');if(JSON.stringify(['br64',z.length,z]).length<JSON.stringify([encoding,v.length,v]).length){encoding='br64';v=z;}raw.push(v);return {bytes:r.bytes,sha256:r.hash.copy().digest('hex'),eof:r.eof,closed:r.closed,error:r.error,encoding,chars:v.length,remainder_unknown:!r.eof||r.error||r.stopped};});
 let unknown=!s.exited||!s.closed||!s.stdin_finished||!s.stdin_closed||s.stdin_extent_unknown||s.rows.length!==(kind===1?3:2)||pipes.some(r=>r.remainder_unknown||!r.closed);
 let f={...s,pipes:pipes.map(r=>g2.pipe_fields.map(k=>r[k])),unknown_closure:unknown,completed:!unknown&&!s.causes.length&&s.returncode===0&&pipes[1].bytes===0&&n<cutoff,terminal_observed_ms:n,physical_acceptance:false,clock};
 let header=JSON.stringify([kind,...g2.fields.map(k=>f[k])]),a=JSON.parse(header),text=header+'\n'+raw.join('');
 return {text,facts:Object.fromEntries(g2.fields.map((k,i)=>[k,a[i+1]])),raw:s.rows.map(r=>Buffer.concat(r.raw))};
};
g2.output=(s,kind,clock)=>{
 let n=g2.now();if(kind===1&&n>=g2.end_ms)throw Error('original_deadline');let snapshot=g2.snapshot(s,kind,clock,n,kind===1?g2.work_ms:g2.end_ms);
 if(kind===1){g2.last_setup=snapshot;g2.setup_success=false;try{g2.setupView(snapshot);g2.setup_success=true;}catch(e){g2.setup_refusal=String(e.message);}}else g2.last_writer=snapshot;
 nodeRepl.write(snapshot.text);
};
var g2options={cwd:'C:/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST',stdio:['pipe','pipe','pipe','pipe'],windowsHide:true};g2.options=g2options;
try{
 await g2.auth();if(g2.now()>=g2.work_ms)throw Error('spawn_late');
 g2.setup=g2.adopt(g2s('C:/Python314/python.exe',['-I','-S','-B','-c',__SETUP_HEAD__+g2py+__SETUP_TAIL__,__COMMIT__,__APPROVAL__,JSON.stringify(g2.sources.map(r=>r[1]))],g2options),[2048,2048,32],g2.work_ms,null,(s,i,r)=>{if(i===2){let v=Buffer.concat(r.raw).toString('latin1'),n=Math.floor(g2.end_ms-g2.now());if(r.error||r.stopped||!/^\d{1,20}\n$/.test(v)||n<=10000)throw Error('ready_bound');s.ack_ms=n;g2.send(s,Buffer.concat([Buffer.from(JSON.stringify({remaining_ms:n,selected_base64:'',sha256:g2h('sha256').update('').digest('hex'),size_bytes:0})+'\n'),...g2.held]));}});
}catch(e){g2.setup=g2.track(null);g2.setup.causes.push(String(e.message).slice(0,32));g2.setup.source_facts=g2.source_facts;}
g2.poll=async(cap=30000)=>{
 if(g2.final||++g2.calls>6)throw Error('poll_state');let s=g2.setup,n=await g2.wait(s,g2.work_ms,cap),clock=g2.calls===1?[g2.start_ms,g2.work_ms,g2.end_ms]:null;
 if(!s.closed&&!s.causes.length&&n<g2.work_ms&&g2.calls<6){nodeRepl.write(JSON.stringify([0,...(clock||[]),s.pid,s.returncode]));return;}g2.final=true;g2.output(s,1,clock);
};
await gate2Resume.poll(1000);"""

NODE_FINISH_BODY = r"""g2.verifyReturn=delivered=>{let n=g2.now();if(n>=g2.end_ms)throw Error('writer_return_unknown');g2.writerView(delivered);let context=null;if(g2.setup_success){let v=g2.setupView(g2.last_setup);context=['vast.gate2.external-delivery.v1',v.code_commit,Number(v.packet.size_bytes),v.packet.sha256,g2.selected.sha256,g2.factory_sha256,g2.cd_factory_sha256];}let after=g2.now();if(after>=g2.end_ms)throw Error('writer_return_unknown');g2.retention_complete=true;nodeRepl.write(JSON.stringify([3,after,g2.end_ms,g2.setup_success,true,g2.selected.sha256,context]));};
g2.finish=async selected=>{
 if(!g2.final||g2.writer_started||g2.now()>=g2.end_ms)throw Error('writer_state');g2.writer_started=true;
 g2.selectedView(selected);let b=Buffer.from(selected,'ascii'),x=g2.selected={selected_base64:b.toString('base64'),size_bytes:b.length,sha256:g2.hash(b)};
 g2.need(g2.held.length===2&&g2.source_facts.length===2&&g2.source_facts.every(f=>f.cause===null&&f.open_completed===true&&f.close_completed===true&&f.unknown_closure===false)&&g2.held.every((b,i)=>b.length===g2.sources[i][1].size_bytes&&g2.hash(b)===g2.sources[i][1].sha256),'writer_sources_unavailable');
 let sent=false,s=g2.adopt(g2s('C:/Python314/python.exe',['-I','-S','-B','-c',g2.writer,JSON.stringify(g2.sources.map(r=>r[1]))],{...g2.options,stdio:['pipe','pipe','pipe']}),[2112,2112],g2.end_ms,(s,i,r)=>{if(i===0&&!sent){let v=Buffer.concat(r.raw).toString('latin1');if(v.length>64)throw Error('writer_ready');if(v.endsWith('\n')){if(v!=='{"ready":true,"schema_version":1}\n')throw Error('writer_ready');let n=Math.floor(g2.end_ms-g2.now());if(n<=0)throw Error('writer_deadline');sent=true;s.ack_ms=n;g2.send(s,Buffer.concat([Buffer.from(JSON.stringify({remaining_ms:n,selected_base64:x.selected_base64,sha256:x.sha256,size_bytes:x.size_bytes})+'\n'),...g2.held]));}}});
 g2.writer_state=s;await g2.wait(s,g2.end_ms,g2.end_ms-g2.now());g2.output(s,2,[g2.start_ms,g2.work_ms,g2.end_ms]);
};
"""

def _inert_control_source():
    """Build only the fixed D18 control; no operational input or source is read."""
    import base64,zlib
    data=b'{"probe":1}'
    packed=zlib.compress(data,9)
    body='return gate2Resume.value===1&&nodeRepl.write(gate2Resume)===2;'
    prefix='function(gate2Resume,nodeRepl){'
    wrapper=prefix+body+'}'
    source=r"""{
const clock=performance;
if(!clock||typeof clock.now!=='function')throw Error('clock_unavailable');
const first=clock.now();
if(!Number.isFinite(first)||first<0)throw Error('clock_sample');
const publisher=nodeRepl;
const {createHash}=await import('node:crypto');
const {inflateSync}=await import('node:zlib');
const sha=raw=>createHash('sha256').update(raw).digest('hex');
const encoded=__ENCODED__;
if(encoded.length!==__ENCODED_SIZE__||!/^[A-Za-z0-9+/]+={0,2}$/.test(encoded))throw Error('data_input');
const packed=Buffer.from(encoded,'base64');
if(packed.length!==__PACKED_SIZE__||packed.toString('base64')!==encoded||sha(packed)!==__PACKED_SHA__)throw Error('data_compressed');
const raw=inflateSync(packed,{maxOutputLength:11});
if(raw.length!==11||sha(raw)!==__RAW_SHA__||raw.some(b=>b>127))throw Error('data_decoded');
const data=JSON.parse(raw.toString('latin1'));
if(!data||Object.getPrototypeOf(data)!==Object.prototype||Object.keys(data).join(',')!=='probe'||typeof data.probe!=='number'||data.probe!==1)throw Error('data_shape');
const state=Object.freeze({value:1});
const stubWrite=Object.freeze(function(value){return value===state?2:0;});
const stubPublisher=Object.freeze({write:stubWrite});
const wrapper=__WRAPPER__;
const expectedWrapper=wrapper,expectedState=state,expectedPublisher=stubPublisher;
const intrinsic=Function.prototype.toString;
if(typeof intrinsic!=='function')throw Error('intrinsic_unavailable');
if(wrapper!==expectedWrapper||state!==expectedState||stubPublisher!==expectedPublisher||stubPublisher.write!==stubWrite||!Object.isFrozen(state)||!Object.isFrozen(stubPublisher))throw Error('closure_identity');
const text=intrinsic.call(wrapper);
if(typeof text!=='string'||text.length!==__WRAPPER_SIZE__||/[^\x20-\x7e]/.test(text)||!text.startsWith('function(gate2Resume,nodeRepl){')||!text.endsWith('}'))throw Error('intrinsic_shape');
const body=text.slice(__PREFIX_SIZE__,-1);
if(body.length!==__BODY_SIZE__||sha(Buffer.from(body,'ascii'))!==__BODY_SHA__)throw Error('intrinsic_binding');
if(wrapper(state,stubPublisher)!==true)throw Error('closure_call');
if(typeof JSON.rawJSON!=='function'||JSON.stringify(JSON.rawJSON('1'))!=='1')throw Error('raw_json_feature');
let lexeme=null;
const integer=JSON.parse('1',(key,value,context)=>{if(key==='')lexeme=context&&context.source;return value;});
if(integer!==1||lexeme!=='1')throw Error('parse_source_feature');
const last=clock.now();
if(!Number.isFinite(last)||last<0||last<first)throw Error('clock_sample');
publisher.write(__OUTPUT__);
}"""
    values={'ENCODED':json.dumps(base64.b64encode(packed).decode('ascii')),
            'ENCODED_SIZE':str(len(base64.b64encode(packed))),'PACKED_SIZE':str(len(packed)),
            'PACKED_SHA':json.dumps(hashlib.sha256(packed).hexdigest()),
            'RAW_SHA':json.dumps(hashlib.sha256(data).hexdigest()),'WRAPPER':wrapper,
            'WRAPPER_SIZE':str(len(wrapper)),'PREFIX_SIZE':str(len(prefix)),'BODY_SIZE':str(len(body)),
            'BODY_SHA':json.dumps(hashlib.sha256(body.encode('ascii')).hexdigest()),
            'OUTPUT':json.dumps(INERT_CONTROL_EXPECTED)}
    for key,value in values.items():source=source.replace('__'+key+'__',value)
    assert source.isascii() and '__' not in source and len(source)<=8192
    return source


INERT_CONTROL_EXPECTED = json.dumps(dict(control='vast.gate2.inert-static.v1',data_authenticated=True,
    intrinsic_source=True,json_parse_source=True,json_raw_integer=True,lexical_closure=True,
    operational_authority=False,packet_qualified=False,performance_clock=True,physical_acceptance=False,
    production_bindings_qualified=False,retention_qualified=False,setup_qualified=False),
    sort_keys=True,separators=(',',':'))+'\n'
INERT_CONTROL_SOURCE = _inert_control_source()


def inert_control_cases():
    """Fixed fault derivatives for both controlled contexts, never submitted controls."""
    import base64,zlib
    def change(old,new):
        assert INERT_CONTROL_SOURCE.count(old)==1,old
        return INERT_CONTROL_SOURCE.replace(old,new)
    result=[('intrinsic_missing',INERT_CONTROL_SOURCE,{'inert_fault':'intrinsic_missing'},'intrinsic_unavailable'),
            ('intrinsic_tampered',INERT_CONTROL_SOURCE,{'inert_fault':'intrinsic_tampered'},'intrinsic_shape'),
            ('intrinsic_transformed',INERT_CONTROL_SOURCE,{'inert_fault':'intrinsic_transformed'},'intrinsic_shape'),
            ('raw_json_missing',INERT_CONTROL_SOURCE,{'inert_fault':'raw_json_missing'},'raw_json_feature'),
            ('raw_json_wrong',INERT_CONTROL_SOURCE,{'inert_fault':'raw_json_wrong'},'raw_json_feature'),
            ('parse_source_missing',INERT_CONTROL_SOURCE,{'inert_fault':'parse_source_missing'},'parse_source_feature'),
            ('performance_missing',INERT_CONTROL_SOURCE,{'inert_fault':'performance_missing'},'clock_unavailable'),
            ('clock_negative',INERT_CONTROL_SOURCE,{'inert_samples':[-1,10]},'clock_sample'),
            ('clock_nonfinite',INERT_CONTROL_SOURCE,{'inert_samples':['nan',10]},'clock_sample'),
            ('clock_infinity',INERT_CONTROL_SOURCE,{'inert_samples':[10,'infinity']},'clock_sample'),
            ('clock_regression',INERT_CONTROL_SOURCE,{'inert_samples':[10,9]},'clock_sample'),
            ('wrapper_identity',change('expectedWrapper=wrapper','expectedWrapper=Object.freeze(function(){})'),{},'closure_identity'),
            ('state_identity',change('expectedState=state','expectedState=Object.freeze({value:1})'),{},'closure_identity'),
            ('publisher_identity',change('expectedPublisher=stubPublisher','expectedPublisher=Object.freeze({write:stubWrite})'),{},'closure_identity'),
            ('wrapper_body',change('return gate2Resume.value===1','return gate2Resume.value===2'),{},'intrinsic_binding'),
            ('direct_call_identity',change('wrapper(state,stubPublisher)','wrapper(Object.freeze({value:1}),stubPublisher)'),{},'closure_call'),
            ('compressed_hash',change('sha(packed)!==','sha(packed)==='),{},'data_compressed'),
            ('data_hash',change('sha(raw)!==','sha(raw)==='),{},'data_decoded')]
    for label,raw,error in [('data_type',b'{"probe":true}','data_shape'),('data_extra',b'{"extra":0,"probe":1}','data_shape'),
                            ('data_one_byte_over',b'{"probe":1} ','Cannot create a Buffer larger than 11 bytes')]:
        original=zlib.compress(b'{"probe":1}',9);packed=zlib.compress(raw,9)
        code=INERT_CONTROL_SOURCE.replace(base64.b64encode(original).decode(),base64.b64encode(packed).decode()).replace(
            'encoded.length!=='+str(len(base64.b64encode(original))),'encoded.length!=='+str(len(base64.b64encode(packed)))).replace(
            'packed.length!=='+str(len(original)),'packed.length!=='+str(len(packed))).replace(
            hashlib.sha256(original).hexdigest(),hashlib.sha256(packed).hexdigest())
        if label!='data_one_byte_over':
            code=code.replace(hashlib.sha256(b'{"probe":1}').hexdigest(),hashlib.sha256(raw).hexdigest()).replace(
                'maxOutputLength:11','maxOutputLength:'+str(len(raw))).replace('raw.length!==11','raw.length!=='+str(len(raw)))
        result.append((label,code,{},error))
    return result


INERT_HARNESS = r"""async function gate2InertHarness(test){
const vm=require('node:vm'),crypto=require('node:crypto'),zlib=require('node:zlib');
const writes=[],imports=[],effects={state_reads:0,state_writes:0,files:0,sources:0,children:0,timers:0};
let error=null,error_name=null,clock_reads=0,context,before,sandbox;
try{
 if(test.code_generation_disabled!==true)throw Error('code_generation_disabled');
 const samples=test.inert_samples||[10,11],performance={now:function(){if(this!==performance)throw Error('clock_receiver');let sample=samples[clock_reads++];return sample==='nan'?NaN:sample==='infinity'?Infinity:sample;}};
 sandbox={Buffer,performance:test.inert_fault==='performance_missing'?undefined:performance,nodeRepl:{write:value=>writes.push(String(value))},
  setTimeout:()=>{effects.timers++;throw Error('inert_timer');},clearTimeout:()=>{effects.timers++;throw Error('inert_timer');}};
 Object.defineProperty(sandbox,'gate2Resume',{get:()=>{effects.state_reads++;throw Error('inert_state_read');},set:()=>{effects.state_writes++;throw Error('inert_state_write');},enumerable:true,configurable:false});
 before=Object.getOwnPropertyDescriptor(sandbox,'gate2Resume');
 context=vm.createContext(sandbox,{codeGeneration:{strings:false,wasm:false}});
 const faults={intrinsic_missing:'Function.prototype.toString=undefined;',intrinsic_tampered:"Function.prototype.toString=function(){return 'tampered';};",
  intrinsic_transformed:"const originalSource=Function.prototype.toString;Function.prototype.toString=function(){return originalSource.call(this).replace('return ','return  ');};",
  raw_json_missing:'JSON.rawJSON=undefined;',raw_json_wrong:"JSON.rawJSON=function(){return {rawJSON:'2'};};",
  parse_source_missing:'const originalParse=JSON.parse;JSON.parse=(text,reviver)=>originalParse(text,(key,value)=>reviver?reviver(key,value):value);'};
 if(faults[test.inert_fault])vm.runInContext(faults[test.inert_fault],context);
 const importModuleDynamically=async name=>{imports.push(name);let values;
  if(name==='node:crypto')values=crypto;else if(name==='node:zlib')values=zlib;
  else{if(name.startsWith('node:fs'))effects.files++;else if(name==='node:child_process')effects.children++;else effects.sources++;throw Error('inert_import');}
  const mod=new vm.SyntheticModule(Object.keys(values),function(){for(const key of Object.keys(values))this.setExport(key,values[key]);},{context});
  await mod.link(()=>{throw Error('inert_static_import');});await mod.evaluate();return mod;};
 await vm.runInContext('(async()=>{'+test.code+'})()',context,{importModuleDynamically});
 if(Object.values(effects).some(value=>value!==0))throw Error('inert_effect');
}catch(e){error=String(e.message);error_name=String(e.name);}
const after=sandbox&&Object.getOwnPropertyDescriptor(sandbox,'gate2Resume');
console.log(JSON.stringify({writes,error,error_name,inert:{imports,clock_reads,effects,
 state_descriptor_unchanged:!!before&&!!after&&before.get===after.get&&before.set===after.set&&before.enumerable===after.enumerable&&before.configurable===after.configurable,
 existence_nonaccess_proof:'exact_control_source_only'}}));
}"""


NODE_HARNESS = r"""const vm=require('node:vm'),{EventEmitter}=require('node:events'),crypto=require('node:crypto');
const test=JSON.parse(require('node:fs').readFileSync(0,'utf8'));if(test.inert_control_only===true){void gate2InertHarness(test);}else{
let clock=10,spawned=0,killed=0,timers=[],writes=[],reads=[[],[],[]],stdinEnds=[0,0],inputErrorEvents=0,ready_sent=false,setup_ack=null,verifying=false,verify_reads=0;
class Pipe extends EventEmitter{
 constructor(i){super();this.i=i;this.raw=Buffer.alloc(0);this.finished=false;this.closed=false;}
 read(n){reads[this.i].push(n);if(!this.raw.length)return null;let b=this.raw.subarray(0,n);this.raw=this.raw.subarray(b.length);return b;}
 feed(raw){this.raw=Buffer.concat([this.raw,Buffer.from(raw)]);this.emit('readable');}
 end(){this.finished=true;this.emit('end');this.closed=true;this.emit('close');}
}
function fallbackErrors(p,which){if(test.track_throw!==which||!test.fallback_errors)return;queueMicrotask(()=>{for(let name of test.fallback_errors){let emitter=name==='child'?p:name==='ready'?p.stdio[3]:p[name];if(name==='stdin')inputErrorEvents++;emitter.emit('error',Error('controlled '+name));}});}
const child=new EventEmitter();child.pid=4321;child.stdout=new Pipe(0);child.stderr=new Pipe(1);child.kill=()=>{killed++;throw Error('kill forbidden');};
child.stdin=new EventEmitter();child.stdin.end=raw=>{stdinEnds[0]++;setup_ack=Buffer.from(raw||'').toString('base64');if(test.stdin_end_throw===1)throw Error('controlled_stdin');fallbackErrors(child,1);if(test.stdin_async_error===1)queueMicrotask(()=>child.stdin.emit('error',Error('controlled async input')));if(test.stdin_error)child.stdin.emit('error',Error('controlled input'));child.stdin.emit('finish');child.stdin.emit('close');};child.stdio=[child.stdin,child.stdout,child.stderr,new Pipe(2)];
const writer=new EventEmitter();writer.pid=5678;writer.stdout=new Pipe(0);writer.stderr=new Pipe(1);writer.stdin=new EventEmitter();let writer_ack=null;
writer.stdin.end=raw=>{stdinEnds[1]++;writer_ack=Buffer.from(raw||'').toString('base64');if(test.stdin_end_throw===2)throw Error('controlled_stdin');fallbackErrors(writer,2);queueMicrotask(()=>{
 if(!Buffer.from(raw||'').length){writer.stdout.end();writer.stderr.end();writer.emit('exit',1,null);writer.emit('close',1,null);return;}
 let a=JSON.parse(Buffer.from(raw).subarray(0,Buffer.from(raw).indexOf(10)).toString('latin1')),round=Math.ceil(a.size_bytes/4096)*4096;
 let facts={stdin_eof:true,stdin_extent_unknown:false,source_bytes:test.sources.map(r=>Buffer.from(r[1],'base64').length),source_sha256:test.sources.map(r=>crypto.createHash('sha256').update(Buffer.from(r[1],'base64')).digest('hex')),open_completed:true,written_bytes:a.size_bytes,extent_unknown:false,fsync_completed:true,close_completed:true,allocated_bytes:round,completed:true,sha256:a.sha256,unknown_closure:false};
 let value={completed:true,external_terminal_required:true,size_bytes:a.size_bytes,sha256:a.sha256,write_facts:facts,deadline_ns:1755772592209100+a.remaining_ms*1000000,all_forms_quote_bytes:round*2+8192};
 if(test.writer_fault==='source')facts.source_sha256[1]='0'.repeat(64);if(test.writer_fault==='extent')facts.extent_unknown=true;if(test.writer_fault==='allocation')facts.allocated_bytes=-1;if(test.writer_fault==='extra')facts.readback_completed=true;
 if(test.writer_fault==='stdin_eof')facts.stdin_eof=false;if(test.writer_fault==='stdin_extent')facts.stdin_extent_unknown=true;if(test.writer_fault==='source_bytes')facts.source_bytes[0]++;
 if(test.writer_fault==='fsync')facts.fsync_completed=false;if(test.writer_fault==='close')facts.close_completed=false;if(test.writer_fault==='written')facts.written_bytes++;
 if(test.writer_fault==='bool_allocation')facts.allocated_bytes=true;if(test.writer_fault==='float_allocation')facts.allocated_bytes=4096.5;if(test.writer_fault==='forms')value.all_forms_quote_bytes++;
 function canonical(v){if(Array.isArray(v))return '['+v.map(canonical).join(',')+']';if(v&&typeof v==='object')return '{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}';return JSON.stringify(v);}
 let document=test.writer_result??canonical(value)+'\n';if(test.writer_deadline_lexeme)document=document.replace(/"deadline_ns":[0-9]+/,'"deadline_ns":'+test.writer_deadline_lexeme);let output=Buffer.from(document);if(test.writer_highbit)output[0]|=128;
 if(test.writer_input_error)writer.stdin.emit('error',Error('controlled writer input'));writer.stdin.emit('finish');writer.stdin.emit('close');writer.stdout.feed(output);writer.stdout.end();writer.stderr.end();writer.emit('exit',0,null);writer.emit('close',0,null);});};
let samples=0;const calls=[],context=vm.createContext({Buffer,console,performance:test.no_performance?undefined:{now:()=>{if(++samples===1&&test.bad_initial_clock)return test.bad_initial_clock==='nan'?NaN:test.bad_initial_clock==='infinity'?Infinity:Number.MAX_SAFE_INTEGER;if(verifying&&++verify_reads===2)clock+=test.verify_delay||0;return clock;}},setTimeout:(f,n)=>{let t={f,n};timers.push(t);return t;},clearTimeout:t=>{t.off=true;},
 nodeRepl:{write:value=>writes.push(String(value))}},test.code_generation_disabled===true?{codeGeneration:{strings:false,wasm:false}}:{});
const sourceCalls=[];let sourceClose=0,sourceRead=0;
function sourceStat(i,changed=false){return {dev:1n,ino:BigInt(i+1),mode:33188n,nlink:1n,size:BigInt(Buffer.from(test.sources[i][1],'base64').length),mtimeNs:changed?2n:1n,ctimeNs:1n,birthtimeNs:1n,blocks:64n,isFile:()=>!test.source_special};}
const fakeFS={constants:{O_RDONLY:0,O_NOFOLLOW:0x20000,O_NONBLOCK:0x800},realpath:async p=>p,lstat:async p=>sourceStat(test.sources.findIndex(r=>r[0]===p)),open:async(p,flags)=>{const i=test.sources.findIndex(r=>r[0]===p);sourceCalls.push([p,flags]);let offset=0,stats=0;return {stat:async()=>sourceStat(i,test.source_race&&++stats>1),read:async(b,o,n)=>{sourceRead++;if(test.source_readfail&&sourceRead>1)throw Error('source_read_failed');let raw=Buffer.from(test.sources[i][1],'base64');if(test.source_tamper)raw[0]^=1;let k=Math.min(n,raw.length-offset,test.source_short?7:Infinity);if(k>0)raw.copy(b,o,offset,offset+k);offset+=k;return {bytesRead:k};},close:async()=>{sourceClose++;if(test.source_close)throw Error('controlled_close');}};}};
const imports=async name=>name==='node:fs/promises'?fakeFS:name==='node:perf_hooks'?{performance:{now:()=>clock}}:
 name==='node:zlib'?(clock+=spawned?test.finalizer_import_delay||0:0,{brotliCompressSync:require('node:zlib').brotliCompressSync,inflateSync:(raw,options)=>{clock+=test.finalizer_decode_delay||test.decode_delay||0;return require('node:zlib').inflateSync(raw,options);},brotliDecompressSync:(raw,options)=>{clock+=test.decode_delay||0;return require('node:zlib').brotliDecompressSync(raw,options);}}):
 name==='node:crypto'?crypto:name==='node:child_process'?(clock+=test.import_delay||0,{spawn:(file,args,options)=>{spawned++;calls.push({file,args,options});let p=spawned===1?child:writer;if(test.track_throw===spawned){p.once=()=>{throw Error('controlled_track');};if(test.stdin_listener_fault==='absent')p.stdin=null;else if(test.stdin_listener_fault==='missing_on')p.stdin.on=undefined;else if(test.stdin_listener_fault==='throwing_on')p.stdin.on=()=>{throw Error('controlled_on');};}return p;}}):Promise.reject(Error('unknown import'));
const importModuleDynamically=async name=>{const values=await imports(name);const mod=new vm.SyntheticModule(Object.keys(values),function(){for(const key of Object.keys(values))this.setExport(key,values[key]);},{context});await mod.link(()=>{throw Error('static import');});await mod.evaluate();return mod;};
if(test.missing_raw_json)vm.runInContext('JSON.rawJSON=undefined;',context);
if(test.missing_source_context)vm.runInContext('var p=JSON.parse;JSON.parse=(s,f)=>p(s,(k,v)=>f?f(k,v):v);',context);
async function call(code,action){if(action==='afterend')clock=150010;let value=vm.runInContext('(async()=>{'+code+'})()',context,{importModuleDynamically});let settled=false;value.then(()=>settled=true,()=>settled=true);for(let i=0;i<100000&&!spawned&&!settled;i++)await Promise.resolve();for(let i=0;i<100;i++)await Promise.resolve();
 if(spawned===1&&!ready_sent&&action!=='noready'){ready_sent=true;let b=Buffer.from((test.ready_decimal||'1755772592209100')+'\n');if(test.ready_highbit)b[0]|=128;child.stdio[3].feed(b);child.stdio[3].end();}
 if(action==='normal'){let b=Buffer.from(test.output);if(test.output_highbit)b[0]|=128;child.stdout.feed(b);child.stdout.end();child.stderr.feed(test.stderr_output||'');child.stderr.end();child.emit('exit',test.returncode??0,null);child.emit('close',test.returncode??0,null);}
 if(action==='overflow'){child.stdout.feed('x'.repeat(5000));child.stderr.end();child.emit('exit',0,null);}
 if(action==='readerror'){child.stdout.emit('error',Error('controlled'));child.stderr.end();child.emit('exit',0,null);}
 if(action==='late'){clock=140011;child.stdout.end();child.stderr.end();child.emit('exit',0,null);child.emit('close',0,null);}
 if(action==='exitonly'){child.stdout.feed(test.output);child.emit('exit',0,null);}
 if(action==='closeonly'){child.emit('close',0,null);}
 if(action==='error'){child.emit('error',Error('controlled'));}
 if(action==='errorend'){child.stdout.feed('known');child.stdout.emit('error',Error('controlled'));child.stdout.end();child.stderr.end();child.emit('exit',0,null);child.emit('close',0,null);}
 if(action==='writernormal'){let b=Buffer.from('{"ready":true,"schema_version":1}\n');if(test.writer_ready_highbit)b[0]|=128;writer.stdout.feed(b);}
 for(let i=0;i<100;i++)await Promise.resolve();
 for(let t of timers.splice(0)){if(!t.off){clock+=t.n;t.f();}}
 if(action==='regress')clock=1;
 return await value;
}
(async()=>{let error=null,error_name=null,root=null,root_export=null,root_export_error=null,providerCalls=[],providerResults=[];try{
 if(test.root_flow){let setups=0;const tools={mcp__node_repl__js:async args=>{
  providerCalls.push(args);if(providerCalls.length===test.provider_throw_at)throw Error('controlled_provider_throw');let setup=args.code===test.code||args.code==='await gate2Resume.poll();',writer=args.code.includes('await gate2Resume.finish('),action=setup?(++setups<=test.root_pending?'pending':test.root_terminal_action||'normal'):writer?'writernormal':'pending',before=writes.length;
  verifying=!setup&&!writer;verify_reads=0;await call(args.code,action);verifying=false;
  if(writes.length!==before+1)throw Error('actual_node_output_count');
  const r={content:[{type:'text',text:writes.at(-1)}],isError:false,_meta:{actual_ordinal:providerCalls.length,resource:{uri:'controlled:retained'}},resource:{mimeType:'application/json'}};
  if(providerCalls.length===(test.provider_fault_at||1)){if(test.provider_fault==='unsafe')r._meta.unsafe=9007199254740992;if(test.provider_fault==='truncated')r.isError=true;if(test.provider_fault==='metadata_bound')r._meta.extra='x'.repeat(12289);if(test.provider_fault==='old_six_field_success')r.content[0].text=JSON.stringify(JSON.parse(r.content[0].text).slice(0,6));}providerResults.push(r);
  if(writer)clock+=test.writer_delivery_delay||0;return r;
 }};
 const run=eval('(async(tools,first,finalizer,profile,expected)=>{'+test.root_source+';const record=await gate2Complete(tools,first,finalizer,profile,expected);let output=null,error=null;try{output=gate2Export(record,profile);}catch(e){error=String(e.message);}return {record,output,error};})');let result=await run(tools,test.code,test.finalizer,test.output_profile,test.expected);root=result.record;root_export=result.output;root_export_error=result.error;
 }else{await call(test.code,test.action);for(let action of test.polls||[])await call(test.poll.replaceAll('__DELIVERED_WRITER_TEXT__',JSON.stringify(writes.at(-1))),action);}
}catch(e){error=String(e.message);error_name=String(e.name);}console.log(JSON.stringify({writes,spawned,killed,reads,stdinEnds,inputErrorEvents,calls,error,error_name,clock,writer_ack,setup_ack,sourceCalls,sourceClose,sourceRead,root,root_export,root_export_error,providerCalls,providerResults}));})().catch(e=>{console.error(e);process.exitCode=1;});}
"""

NODE_DECODE = r"""const {brotliDecompressSync}=require('node:zlib'),{createHash}=require('node:crypto');
const x=JSON.parse(process.argv[1]),text=x.text,split=text.indexOf('\n');
if(Buffer.byteLength(text)>8192||split<0||split>2048)throw Error('frame_bound');
const a=JSON.parse(text.slice(0,split));if(!Array.isArray(a)||![1,2].includes(a[0])||a.length!==x.fields.length+1)throw Error('header');
if(JSON.stringify(a)!==text.slice(0,split))throw Error('header_canonical');
const facts=Object.fromEntries(x.fields.map((k,i)=>[k,a[i+1]])),body=text.slice(split+1);let offset=0,result=[];
if(!Array.isArray(facts.pipes)||facts.pipes.length!==(a[0]===1?3:2))throw Error('pipes');
for(const [i,row] of facts.pipes.entries()){
 if(!Array.isArray(row)||row.length!==x.pipe_fields.length)throw Error('pipe_shape');
 const r=Object.fromEntries(x.pipe_fields.map((k,n)=>[k,row[n]])),limit=a[0]===2?2113:i===2?33:2049;
 if(!Number.isSafeInteger(r.bytes)||r.bytes<0||r.bytes>limit||!Number.isSafeInteger(r.chars)||r.chars<0||r.chars>5464||typeof r.sha256!=='string'||!/^([0-9a-f]{64})$/.test(r.sha256))throw Error('pipe_bound');
 const s=body.slice(offset,offset+r.chars);offset+=r.chars;if(s.length!==r.chars)throw Error('encoded_length');let b;
 if(r.encoding==='ascii'){if([...s].some(v=>v.charCodeAt(0)>127))throw Error('ascii');b=Buffer.from(s,'ascii');}
 else if(r.encoding==='base64'||r.encoding==='br64'){const c=Buffer.from(s,'base64');if(c.toString('base64')!==s)throw Error('base64');b=r.encoding==='br64'?brotliDecompressSync(c,{maxOutputLength:limit}):c;}
 else throw Error('encoding');
 if(b.length!==r.bytes||createHash('sha256').update(b).digest('hex')!==r.sha256)throw Error('decoded_binding');
 result.push(b.toString('base64'));
}
if(offset!==body.length)throw Error('trailing_bytes');console.log(JSON.stringify(result));
"""


ROOT_ENCODER = r"""function gate2Canonical(value,cap){
 if(!Number.isSafeInteger(cap)||cap<1||cap>262144)throw Error('canonical_cap');
 let total=0,plan=[],active=new Set(),todo=[{value}],literal=s=>{if((total+=s.length)>cap)throw Error('canonical_bound');plan.push({literal:s});};
 function size(s){let n=2;for(let i=0;i<s.length;i++){let c=s.charCodeAt(i);n+=c===34||c===92||[8,9,10,12,13].includes(c)?2:c<32||c>126?6:1;if(total+n>cap)throw Error('canonical_bound');}return n;}
 function string(s){let n=size(s);if((total+=n)>cap)throw Error('canonical_bound');plan.push({string:s});}
 function order(a,b){let x=[...a],y=[...b];for(let i=0;i<Math.min(x.length,y.length);i++){let d=x[i].codePointAt(0)-y[i].codePointAt(0);if(d)return d;}return x.length-y.length;}
 while(todo.length){let task=todo.pop();if(task.exit){active.delete(task.exit);continue;}if(task.literal!==undefined){literal(task.literal);continue;}if(task.string!==undefined){string(task.string);continue;}
 let v=task.value;
 if(v===null){literal('null');continue;}if(typeof v==='boolean'){literal(String(v));continue;}if(typeof v==='string'){string(v);continue;}
 if(typeof v==='number'){if(!Number.isFinite(v)||Object.is(v,-0)||Number.isInteger(v)&&!Number.isSafeInteger(v))throw Error('canonical_number');literal(String(v));continue;}
 if(typeof v!=='object'||active.has(v))throw Error('canonical_kind_cycle');let array=Array.isArray(v),proto=Object.getPrototypeOf(v);
 if(proto!==(array?Array.prototype:Object.prototype)&&proto!==null)throw Error('canonical_prototype');
 let keys=Reflect.ownKeys(v);if(keys.length>cap||keys.some(k=>typeof k!=='string'))throw Error('canonical_keys');let pairs=[];
 if(array){let length=Object.getOwnPropertyDescriptor(v,'length');if(!length||!('value'in length)||length.value>cap||keys.length!==length.value+1)throw Error('canonical_array');
 for(let i=0;i<length.value;i++){let d=Object.getOwnPropertyDescriptor(v,String(i));if(!d||!d.enumerable||!('value'in d))throw Error('canonical_accessor');pairs.push([String(i),d.value]);}}
 else{for(let k of keys){let d=Object.getOwnPropertyDescriptor(v,k);if(!d.enumerable||!('value'in d))throw Error('canonical_accessor');size(k);pairs.push([k,d.value]);}pairs.sort((a,b)=>order(a[0],b[0]));}
 active.add(v);todo.push({exit:v});todo.push({literal:array?']':'}'});
 for(let i=pairs.length-1;i>=0;i--){todo.push({value:pairs[i][1]});if(!array){todo.push({literal:':'});todo.push({string:pairs[i][0]});}if(i)todo.push({literal:','});}literal(array?'[':'{');
 }
 return plan.map(t=>t.literal!==undefined?t.literal:JSON.stringify(t.string).replace(/[\u007f-\uffff]/g,c=>'\\u'+c.charCodeAt(0).toString(16).padStart(4,'0'))).join('');
}"""

NODE_INNER_VIEW = r"""function gate2Ascii(v){
 function order(a,b){let x=[...a],y=[...b];for(let i=0;i<Math.min(x.length,y.length);i++){let d=x[i].codePointAt(0)-y[i].codePointAt(0);if(d)return d;}return x.length-y.length;}
 function s(v){if(typeof v==='bigint')return JSON.stringify(JSON.rawJSON(v.toString()));if(typeof v==='number'&&(!Number.isFinite(v)||Object.is(v,-0)||Number.isInteger(v)&&!Number.isSafeInteger(v)))throw Error('provider_number');if(Array.isArray(v))return '['+v.map(s).join(',')+']';if(v&&typeof v==='object')return '{'+Object.keys(v).sort(order).map(k=>JSON.stringify(k)+':'+s(v[k])).join(',')+'}';return JSON.stringify(v);}
 return s(v).replace(/[\u007f-\uffff]/g,c=>'\\u'+c.charCodeAt(0).toString(16).padStart(4,'0'));
}
function gate2View(text){
 if(typeof text!=='string'||text.length>2048||/[^\x20-\x7e]/.test(text)||typeof JSON.rawJSON!=='function')throw Error('inner_bound_feature');
 let observed=false,v=JSON.parse(text,(k,v,c)=>{if(typeof v==='number'){if(!c||typeof c.source!=='string'||! /^-?(0|[1-9][0-9]*)$/.test(c.source)||c.source==='-0')throw Error('integer_lexeme');observed=true;return BigInt(c.source);}return v;});
 if(!observed&&JSON.parse('1',(k,v,c)=>c?.source)!=='1')throw Error('parse_source_feature');
 if(gate2Ascii(v)!==text)throw Error('inner_noncanonical');return v;
}"""

NODE_VALIDATORS = NODE_INNER_VIEW+r"""
g2.commit=__COMMIT__;g2.root=__ROOT__;
g2.need=(v,c)=>{if(!v)throw Error(c);};
g2.keys=(v,k)=>v!==null&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).sort().join()===k.split(',').sort().join();
g2.uint=(v,max=18446744073709551615n)=>typeof v==='bigint'&&v>=0n&&v<=max;
g2.sha=v=>typeof v==='string'&&/^[0-9a-f]{64}$/.test(v);
g2.hash=b=>g2h('sha256').update(b).digest('hex');
g2.canon=gate2Ascii;g2.view=gate2View;
g2.need(typeof JSON.rawJSON==='function'&&JSON.parse('1',(k,v,c)=>c?.source)==='1','parse_source_feature');
g2.setupView=s=>{
 let f=s.facts;g2.need(f.completed===true&&f.unknown_closure===false,'setup_transport');let b=s.raw[0];g2.need(b.length<=2048&&b.at(-1)===10,'setup_line');let v=gate2View(b.subarray(0,-1).toString('latin1'));
 g2.need(g2.keys(v,'completed,physical_acceptance,external_terminal_and_packet_review_required,native_raw_originals_retained,code_commit,packet,authority,events,final_meter,final_return,windows_start_ns,absolute_deadline_ns,c_or_d_invoked')&&v.completed===true&&v.physical_acceptance===false&&v.external_terminal_and_packet_review_required===true&&v.native_raw_originals_retained===0n&&v.c_or_d_invoked===false&&v.code_commit===g2.commit,'setup_schema');
 let desc=(d,path,cap)=>g2.keys(d,'path,size_bytes,sha256')&&d.path===path&&g2.uint(d.size_bytes,cap)&&d.size_bytes>0n&&g2.sha(d.sha256);
 g2.need(desc(v.packet,g2.root+'/gate2.packet.original.json',32768n)&&desc(v.authority,g2.root+'.operator-originals/operator.authority.original.json',8192n)&&desc(v.events,g2.root+'.operator-originals/resume.events.original.json',8192n),'setup_descriptors');
 let ready=s.raw[2].toString('latin1');g2.need(/^[1-9][0-9]{0,19}\n$/.test(ready)&&Number.isSafeInteger(f.ack_ms)&&f.ack_ms>10000&&f.ack_ms<=150000,'setup_anchor');let end=BigInt(ready.slice(0,-1))+BigInt(f.ack_ms)*1000000n;
 g2.need(g2.uint(v.windows_start_ns)&&g2.uint(v.absolute_deadline_ns)&&v.absolute_deadline_ns===end&&v.windows_start_ns===end-150000000000n,'setup_clock');
 let r=v.final_return;g2.need(Array.isArray(r)&&r.length===8&&g2.uint(r[0])&&r[0]>0n&&r[1]===0n&&r[2]===true&&r[3]===true&&g2.uint(r[4],16384n)&&r[4]>0n&&g2.sha(r[5])&&r[6]===0n&&r[7]===g2.hash(''),'setup_final_return');
 let m=v.final_meter;g2.need(g2.keys(m,'native_pid,fresh_interval_N,native_bytes,outside_bytes,active_f2_debit,outstanding_tail_bytes,historical_closing_meter_available,physical_acceptance,final_measurement')&&g2.uint(m.native_pid)&&m.native_pid>0n&&g2.uint(m.fresh_interval_N,2650112n)&&m.active_f2_debit===5345280n+m.fresh_interval_N&&g2.uint(m.native_bytes,1048576n)&&g2.uint(m.outside_bytes,524288n)&&m.outstanding_tail_bytes===45312n&&m.historical_closing_meter_available===false&&m.physical_acceptance===false,'setup_meter');
 let q=m.final_measurement;g2.need(g2.keys(q,'c_free_bytes,ext4_used_bytes,project_free_bytes,fragment_bytes,backing_device')&&Object.values(q).every(x=>g2.uint(x))&&q.fragment_bytes===4096n&&q.backing_device>0n&&q.c_free_bytes>=43620761600n&&q.project_free_bytes>=1073741824n,'setup_measurement');return v;
};
"""

NODE_WRITER_VALIDATORS = r"""g2.decode=(text,kind)=>{
 g2.need(typeof text==='string'&&Buffer.byteLength(text)<=8192,'frame_bound');let at=text.indexOf('\n');g2.need(at>=0&&at<=2048,'frame_header');let a=JSON.parse(text.slice(0,at));g2.need(Array.isArray(a)&&a[0]===kind&&a.length===g2.fields.length+1&&JSON.stringify(a)===text.slice(0,at),'frame_canonical');let f=Object.fromEntries(g2.fields.map((k,i)=>[k,a[i+1]])),body=text.slice(at+1),offset=0,raw=[];
 g2.need(Array.isArray(f.pipes)&&f.pipes.length===(kind===1?3:2),'frame_pipes');
 for(let [i,row] of f.pipes.entries()){g2.need(Array.isArray(row)&&row.length===g2.pipe_fields.length,'pipe_shape');let p=Object.fromEntries(g2.pipe_fields.map((k,n)=>[k,row[n]])),max=kind===2?2113:i===2?33:2049;
 g2.need(Number.isSafeInteger(p.bytes)&&p.bytes>=0&&p.bytes<=max&&Number.isSafeInteger(p.chars)&&p.chars>=0&&p.chars<=5464&&g2.sha(p.sha256)&&['eof','closed','error','remainder_unknown'].every(k=>typeof p[k]==='boolean'),'pipe_bound');let s=body.slice(offset,offset+p.chars);offset+=p.chars;g2.need(s.length===p.chars,'pipe_length');let b;
 if(p.encoding==='ascii'){g2.need(!/[^\x00-\x7f]/.test(s),'pipe_ascii');b=Buffer.from(s,'ascii');}else{g2.need(p.encoding==='base64'||p.encoding==='br64','pipe_encoding');let c=Buffer.from(s,'base64');g2.need(c.toString('base64')===s,'pipe_base64');b=p.encoding==='br64'?g2d(c,{maxOutputLength:max}):c;}g2.need(b.length===p.bytes&&g2.hash(b)===p.sha256,'pipe_binding');raw.push(b);}
 g2.need(offset===body.length,'frame_trailing');return {facts:f,raw};
};
g2.selectedView=text=>{
 g2.need(typeof text==='string'&&text.length>0&&text.length<=12288&&!/[^\x00-\x7f]/.test(text),'selected_bound');let x=JSON.parse(text);g2.need(g2.canon(x)===text&&g2.keys(x,'call,frames')&&Array.isArray(x.frames)&&x.frames.length>=1&&x.frames.length<=6&&g2.keys(x.call,'tool,timeout_ms,codes')&&x.call.tool==='mcp__node_repl__js'&&x.call.timeout_ms===32000&&Array.isArray(x.call.codes)&&x.call.codes.length===x.frames.length&&x.call.codes.every(c=>typeof c==='string'&&c.length>0),'selected_shape');
 for(let [i,r] of x.frames.entries()){g2.need(r&&r.isError===false&&Array.isArray(r.content)&&r.content.length===1&&r.content[0].type==='text'&&typeof r.content[0].text==='string','selected_provider');if(i<x.frames.length-1)g2.need(r.content[0].text.startsWith('[0,'),'selected_pending');}
 g2.need(g2.last_setup&&x.frames.at(-1).content[0].text===g2.last_setup.text,'selected_terminal_binding');g2.factory_sha256=g2.hash(x.call.codes[0]);g2.need(g2.factory_sha256===g2.expected_initial_sha256,'initial_core_binding');g2.setup_success=false;try{g2.setupView(g2.last_setup);g2.setup_success=true;}catch(e){g2.setup_refusal=String(e.message);}return x;
};
g2.writerProof=(text,snapshot,x,state,cap,forms)=>{
 g2.need((cap===12288&&forms===32768||cap===4096&&forms===16384)&&x&&Number.isSafeInteger(x.size_bytes)&&x.size_bytes>0&&x.size_bytes<=cap&&snapshot&&text===snapshot.text,'writer_delivered_binding');let s=g2.decode(text,2),f=s.facts;g2.need(f.completed===true&&f.unknown_closure===false&&f.pid===state.pid&&f.returncode===0&&f.exited===true&&f.closed===true&&f.stdin_finished===true&&f.stdin_closed===true&&f.stdin_extent_unknown===false&&s.raw[1].length===0&&Number.isSafeInteger(f.ack_ms)&&f.ack_ms>0&&f.ack_ms<=150000,'writer_transport');
 let ack=Buffer.concat([Buffer.from(JSON.stringify({remaining_ms:f.ack_ms,selected_base64:x.selected_base64,sha256:x.sha256,size_bytes:x.size_bytes})+'\n'),...g2.held]);g2.need(f.stdin_bytes===ack.length&&f.stdin_sha256===g2.hash(ack),'writer_input');
 let b=s.raw[0],ready='{"ready":true,"schema_version":1}\n';g2.need(b.subarray(0,ready.length).toString('latin1')===ready&&b.at(-1)===10,'writer_lines');let v=g2.view(b.subarray(ready.length,-1).toString('latin1'));
 g2.need(g2.keys(v,'completed,external_terminal_required,size_bytes,sha256,write_facts,deadline_ns,all_forms_quote_bytes')&&v.completed===true&&v.external_terminal_required===true&&v.size_bytes===BigInt(x.size_bytes)&&v.sha256===x.sha256&&g2.uint(v.deadline_ns)&&v.deadline_ns>0n,'writer_schema');let q=v.write_facts;
 g2.need(q&&g2.uint(q.allocated_bytes,BigInt(cap))&&g2.canon(q)===g2.canon({stdin_eof:true,stdin_extent_unknown:false,source_bytes:g2.held.map(b=>BigInt(b.length)),source_sha256:g2.held.map(g2.hash),open_completed:true,written_bytes:BigInt(x.size_bytes),extent_unknown:false,fsync_completed:true,close_completed:true,allocated_bytes:q.allocated_bytes,completed:true,sha256:x.sha256,unknown_closure:false}),'writer_write_facts');
 let round=BigInt(Math.ceil(x.size_bytes/4096)*4096),quote=(q.allocated_bytes>round?q.allocated_bytes:round)+round+8192n;g2.need(v.all_forms_quote_bytes===quote&&quote<=BigInt(forms),'writer_forms');return v;
};
g2.writerView=text=>g2.writerProof(text,g2.last_writer,g2.selected,g2.writer_state,12288,32768);
"""

ROOT_SHA256 = r"""function gate2SHA256(text){
 if(typeof text!=='string'||text.length>262144||/[^\x00-\x7f]/.test(text))throw Error('sha256_ascii_bound');
 let h=[0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19],
 k=[0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2],r=(x,n)=>(x>>>n)|(x<<(32-n)),length=text.length,total=Math.ceil((length+9)/64)*64;
 for(let offset=0;offset<total;offset+=64){let w=Array(64).fill(0);
  for(let i=0;i<64;i++){let at=offset+i,v=at<length?text.charCodeAt(at):at===length?128:0;w[i>>>2]|=v<<(24-(i%4)*8);}if(offset+64===total){w[14]=0;w[15]=length*8;}
  for(let i=16;i<64;i++){let a=w[i-15],b=w[i-2];w[i]=((r(a,7)^r(a,18)^(a>>>3))+w[i-16]+(r(b,17)^r(b,19)^(b>>>10))+w[i-7])|0;}
  let [a,b,c,d,e,f,g,j]=h;for(let i=0;i<64;i++){let t=(j+(r(e,6)^r(e,11)^r(e,25))+((e&f)^(~e&g))+k[i]+w[i])|0,u=((r(a,2)^r(a,13)^r(a,22))+((a&b)^(a&c)^(b&c)))|0;j=g;g=f;f=e;e=(d+t)|0;d=c;c=b;b=a;a=(t+u)|0;}h=h.map((v,i)=>(v+[a,b,c,d,e,f,g,j][i])|0);
 }return h.map(v=>(v>>>0).toString(16).padStart(8,'0')).join('');
}"""

ROOT_ORCHESTRATOR = r"""function gate2Record(value,cap){if(value===null||typeof value!=='object'||Array.isArray(value))return false;try{gate2Canonical(value,cap);return true;}catch{return false;}}
function gate2Profile(profile){if(!gate2Record(profile,128)||Object.keys(profile).sort().join()!=='max_output_tokens,max_record_bytes'||profile.max_output_tokens!==100000||profile.max_record_bytes!==65536)throw Error('external_output_profile');}
function gate2Export(record,profile){gate2Profile(profile);return gate2Canonical(record,65535)+'\n';}
async function gate2Run(tools,first,poll,timeout){
 if(typeof first!=='string'||typeof poll!=='string'||!Number.isSafeInteger(timeout)||timeout<1||timeout>32000)throw Error('root_arguments');
 let frames=[],codes=[],text,observed={calls:[],frames};
 try{for(let n=0;n<6;n++){
  let code=n?poll:first,args={code,timeout_ms:timeout};observed.calls.push(args);codes.push(code);let r=await tools.mcp__node_repl__js(args);frames.push(r);
  gate2Canonical(r,12288);
  if(r.isError!==false||!Array.isArray(r.content)||r.content.length!==1||r.content[0].type!=='text'||typeof r.content[0].text!=='string')throw Error('provider_unavailable');
  text=r.content[0].text;
  if(text.startsWith('[1,'))return {observed,selected:gate2Canonical({call:{tool:'mcp__node_repl__js',timeout_ms:timeout,codes},frames},12288)};
  if(!text.startsWith('[0,')&&text!=='[0]')throw Error('provider_terminal');
 }
 throw Error('setup_frame_limit');}catch(e){return {observed,cause:String(e.message).slice(0,80)};}
}
async function gate2Complete(tools,first,finalizer,profile,expected){
 gate2Profile(profile);if(!gate2Record(expected,512)||Object.keys(expected).sort().join()!=='code_commit,core_sha256,factory_sha256'||typeof expected.code_commit!=='string'||! /^[0-9a-f]{40}$/.test(expected.code_commit)||['core_sha256','factory_sha256'].some(k=>typeof expected[k]!=='string'||! /^[0-9a-f]{64}$/.test(expected[k]))||gate2SHA256(first)!==expected.core_sha256)throw Error('external_expected_pins');let result={completed:false,setup_success:null,retention_complete:false,physical_acceptance:false,output_profile:profile},r;
 function delivered(x){gate2Canonical(x,12288);if(x.isError!==false||!Array.isArray(x.content)||x.content.length!==1||x.content[0].type!=='text'||typeof x.content[0].text!=='string')throw Error('provider_unavailable');return x.content[0].text;}
 try{
  if(typeof finalizer!=='string'||!finalizer.length)throw Error('writer_literal');
  result.setup=await gate2Run(tools,first,'await gate2Resume.poll();',32000);
  if(!result.setup.selected)throw Error(result.setup.cause||'setup_unavailable');
  result.writer_call={code:finalizer+'\nawait gate2Resume.finish('+JSON.stringify(result.setup.selected)+');',timeout_ms:11000};r=await tools.mcp__node_repl__js(result.writer_call);result.writer=r;let text=delivered(r);
  result.verification_call={code:'gate2Resume.verifyReturn('+JSON.stringify(text)+');',timeout_ms:1000};r=await tools.mcp__node_repl__js(result.verification_call);result.verification=r;let proof=JSON.parse(delivered(r));
  if(!Array.isArray(proof)||proof.length!==7||proof[0]!==3||!Number.isFinite(proof[1])||!Number.isFinite(proof[2])||proof[1]>=proof[2]||typeof proof[3]!=='boolean'||proof[4]!==true||typeof proof[5]!=='string'||!/^[0-9a-f]{64}$/.test(proof[5])||proof[5]!==gate2SHA256(result.setup.selected))throw Error('return_proof');
  let c=proof[6];if(proof[3]?( !Array.isArray(c)||c.length!==7||c[0]!=='vast.gate2.external-delivery.v1'||c[1]!==expected.code_commit||!Number.isSafeInteger(c[2])||c[2]<1||c[2]>32768||typeof c[3]!=='string'||! /^[0-9a-f]{64}$/.test(c[3])||c[4]!==proof[5]||c[5]!==expected.core_sha256||c[6]!==expected.factory_sha256):c!==null)throw Error('return_context');result.context=c;
  result.setup_success=proof[3];result.retention_complete=true;result.completed=proof[3]===true;result.selected_sha256=proof[5];
 }catch(e){result.cause=String(e.message).slice(0,80);}
 return result;
}"""

ROOT_RECEIVER = r"""function gate2Context(context){
 let keys='code_commit,core_sha256,factory_sha256,packet_sha256,packet_size_bytes,selected_sha256';
 if(!gate2Record(context,1024)||Object.keys(context).sort().join()!==keys||typeof context.code_commit!=='string'||! /^[0-9a-f]{40}$/.test(context.code_commit)||!Number.isSafeInteger(context.packet_size_bytes)||context.packet_size_bytes<1||context.packet_size_bytes>32768||['packet_sha256','selected_sha256','core_sha256','factory_sha256'].some(k=>typeof context[k]!=='string'||! /^[0-9a-f]{64}$/.test(context[k])))throw Error('delivery_context');
 return gate2SHA256(gate2Canonical(['vast.gate2.external-delivery.v1',context.code_commit,context.packet_size_bytes,context.packet_sha256,context.selected_sha256,context.core_sha256,context.factory_sha256],1024));
}
function gate2ExecutorDocument(chain,expectedSourceSHA,toolReference){
 let need=(v,c)=>{if(!v)throw Error(c);},record=v=>v!==null&&typeof v==='object'&&!Array.isArray(v),token=v=>typeof v==='string'&&/^[A-Za-z0-9_-]{1,128}$/.test(v);
 need(Array.isArray(chain)&&chain.length>=1&&chain.length<=64,'executor_chain');let chainASCII=gate2Canonical(chain,262144),fragments='',cell=null,complete=false,ids=new Set();
 need(typeof expectedSourceSHA==='string'&&/^[0-9a-f]{64}$/.test(expectedSourceSHA),'executor_source_binding');
 for(let [i,item] of chain.entries()){
  need(record(item)&&Object.keys(item).sort().join()==='call,result'&&record(item.call)&&record(item.result),'executor_shape');let call=item.call,result=item.result;
  need(token(call.call_id)&&!ids.has(call.call_id)&&token(call.id)&&token(result.id)&&result.call_id===call.call_id,'executor_call_binding');ids.add(call.call_id);
  if(i===0){
   need(call.type==='custom_tool_call'&&call.name==='exec'&&call.status==='completed'&&result.type==='custom_tool_call_output'&&typeof call.input==='string'&&gate2SHA256(call.input)===expectedSourceSHA,'executor_source_binding');
   let line=/^\/\/ @exec:\s*(\{[^\n]+\})\r?\n/.exec(call.input);need(line,'executor_pragma');let profile=JSON.parse(line[1]);
   need(gate2Record(profile,128)&&Object.keys(profile).sort().join()==='max_output_tokens,yield_time_ms'&&profile.max_output_tokens===100000&&Number.isSafeInteger(profile.yield_time_ms)&&profile.yield_time_ms>=1&&profile.yield_time_ms<=60000,'executor_output_profile');
  }else{
   need(!complete&&call.type==='function_call'&&call.name==='wait'&&result.type==='function_call_output'&&typeof call.arguments==='string'&&call.arguments.length<=256,'executor_wait_binding');
   let args=JSON.parse(call.arguments);need(gate2Record(args,256)&&gate2Canonical(args,256)===call.arguments&&Object.keys(args).sort().join()==='cell_id,max_tokens,yield_time_ms'&&args.cell_id===cell&&args.max_tokens===100000&&Number.isSafeInteger(args.yield_time_ms)&&args.yield_time_ms>=1&&args.yield_time_ms<=60000,'executor_wait_binding');
  }
  let payload=result.output,wrapperText;
  if(typeof payload==='string'){wrapperText=payload;payload=[];}else{
   need(Array.isArray(payload)&&payload.length>=1&&payload.length<=64&&payload.every(block=>record(block)&&block.type==='input_text'&&typeof block.text==='string'),'executor_blocks');wrapperText=payload[0].text;payload=payload.slice(1);
  }
  need(typeof wrapperText==='string'&&wrapperText.length<=256,'executor_wrapper');let wrapper=/^Script (completed|running with cell ID ([A-Za-z0-9_-]{1,64}))\nWall time ([0-9]{1,12}(?:\.[0-9]{1,9})?) seconds\nOutput:\n$/.exec(wrapperText);need(wrapper,'executor_wrapper');
  complete=wrapper[1]==='completed';if(!complete){need(cell===null||cell===wrapper[2],'executor_cell');cell=wrapper[2];}need(!complete||i===chain.length-1,'executor_premature_complete');
  for(let block of payload){need(block.text.length<=65536-fragments.length,'executor_fragment_bound');fragments+=block.text;}
 }
 need(complete,'executor_complete_tail');let reference=cell===null?'functions.exec':'functions.exec/'+cell;
 need(typeof toolReference==='string'&&toolReference.length<=96&&toolReference===reference,'executor_reference');return {text:fragments,sha256:gate2SHA256(chainASCII)};
}
function gate2Receive(recordText,chain,context,toolReference,expectedExecutorSourceSHA){
 let contextSHA=gate2Context(context),need=(v,c)=>{if(!v)throw Error(c);},keys=(v,s)=>v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).sort().join()===s.split(',').sort().join(),same=(a,b)=>gate2Canonical(a,65535)===gate2Canonical(b,65535);
 need(typeof recordText==='string'&&recordText.length>=2&&recordText.length<=65536&&!/[^\x00-\x7f]/.test(recordText)&&recordText.endsWith('\n')&&!recordText.endsWith('\n\n'),'delivery_record_bound');
 let record=JSON.parse(recordText);need(gate2Canonical(record,65535)+'\n'===recordText,'delivery_record_canonical');
 let executor=gate2ExecutorDocument(chain,expectedExecutorSourceSHA,toolReference);need(executor.text===recordText,'executor_complete_tail');
 gate2Profile(record.output_profile);need(record.completed===true&&record.setup_success===true&&record.retention_complete===true&&record.physical_acceptance===false,'delivery_setup_failed');
 let setup=record.setup;need(keys(setup,'observed,selected')&&keys(setup.observed,'calls,frames')&&typeof setup.selected==='string'&&setup.selected.length<=12288&&gate2SHA256(setup.selected)===context.selected_sha256&&record.selected_sha256===context.selected_sha256,'delivery_selected');
 let selected=JSON.parse(setup.selected);need(gate2Canonical(selected,12288)===setup.selected&&keys(selected,'call,frames')&&keys(selected.call,'tool,timeout_ms,codes')&&selected.call.tool==='mcp__node_repl__js'&&selected.call.timeout_ms===32000&&Array.isArray(selected.frames)&&selected.frames.length>=1&&selected.frames.length<=6&&Array.isArray(selected.call.codes)&&selected.call.codes.length===selected.frames.length&&selected.call.codes.every(c=>typeof c==='string')&&gate2SHA256(selected.call.codes[0])===context.core_sha256,'delivery_core');
 need(same(selected.frames,setup.observed.frames)&&same(selected.call.codes.map(code=>({code,timeout_ms:32000})),setup.observed.calls),'delivery_actual_setup_calls');
 function text(r){need(r&&r.isError===false&&Array.isArray(r.content)&&r.content.length===1&&r.content[0]&&r.content[0].type==='text'&&typeof r.content[0].text==='string','delivery_provider');return r.content[0].text;}
 for(let [i,r] of selected.frames.entries())need(text(r).startsWith(i===selected.frames.length-1?'[1,':'[0,'),'delivery_setup_order');
 let writer=text(record.writer),verification=text(record.verification);
 need(keys(record.writer_call,'code,timeout_ms')&&record.writer_call.timeout_ms===11000&&typeof record.writer_call.code==='string'&&record.writer_call.code.endsWith('\nawait gate2Resume.finish('+JSON.stringify(setup.selected)+');')&&record.writer_call.code.includes('g2.expected_initial_sha256='+JSON.stringify(context.core_sha256)+';'),'delivery_writer_call');
 need(keys(record.verification_call,'code,timeout_ms')&&record.verification_call.timeout_ms===1000&&record.verification_call.code==='gate2Resume.verifyReturn('+JSON.stringify(writer)+');','delivery_causal_call');
 let proof=JSON.parse(verification);need(Array.isArray(proof)&&proof.length===7&&proof[0]===3&&Number.isFinite(proof[1])&&Number.isFinite(proof[2])&&proof[1]>=0&&proof[1]<proof[2]&&proof[3]===true&&proof[4]===true&&proof[5]===context.selected_sha256,'delivery_return_proof');
 need(same(proof[6],['vast.gate2.external-delivery.v1',context.code_commit,context.packet_size_bytes,context.packet_sha256,context.selected_sha256,context.core_sha256,context.factory_sha256])&&same(record.context,proof[6]),'delivery_context_binding');
 let at=writer.indexOf('\n');need(at>0&&at<=2048,'delivery_writer_header');let f=JSON.parse(writer.slice(0,at));need(Array.isArray(f)&&f.length===20&&f[0]===2&&JSON.stringify(f)===writer.slice(0,at)&&Number.isSafeInteger(f[1])&&f[1]>0&&f[2]===0&&f[3]===null&&f[4]===true&&f[5]===true&&Array.isArray(f[7])&&f[7].length===0&&f[8]===false&&f[9]===true&&f[11]===false&&f[14]===true&&f[15]===true&&f[18]===false&&Number.isSafeInteger(f[13])&&f[13]>0&&f[13]<=150000&&Number.isSafeInteger(f[16])&&f[16]>0&&f[16]<=90112&&typeof f[17]==='string'&&/^[0-9a-f]{64}$/.test(f[17]),'delivery_writer_status');
 need(Array.isArray(f[12])&&f[12].length===3&&f[12].every(Number.isFinite)&&f[12][1]===f[12][0]+140000&&f[12][2]===f[12][0]+150000&&f[12][2]===proof[2]&&Number.isFinite(f[10])&&f[10]>=0&&f[10]<=proof[1]&&f[10]<proof[2]&&Array.isArray(f[6])&&f[6].length===2&&f[6].every(r=>Array.isArray(r)&&r.length===8&&Number.isSafeInteger(r[0])&&r[0]>=0&&r[0]<=2113&&typeof r[1]==='string'&&/^[0-9a-f]{64}$/.test(r[1])&&r[2]===true&&r[3]===true&&r[4]===false&&r[7]===false)&&f[6][1][0]===0&&f[6][1][1]===gate2SHA256(''),'delivery_writer_closure');
 return {version:1,context_sha256:contextSHA,record_size_bytes:recordText.length,record_sha256:gate2SHA256(recordText),executor_call_sha256:executor.sha256,max_output_tokens:100000,terminal:'complete_untruncated',tool_reference:toolReference};
}
function gate2Approve(receipt,context,observation){
 let contextSHA=gate2Context(context),keys=(v,k)=>v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).sort().join()===k.split(',').sort().join();
 if(!keys(receipt,'version,context_sha256,record_size_bytes,record_sha256,executor_call_sha256,max_output_tokens,terminal,tool_reference')||receipt.version!==1||receipt.context_sha256!==contextSHA||!Number.isSafeInteger(receipt.record_size_bytes)||receipt.record_size_bytes<1||receipt.record_size_bytes>65536||receipt.max_output_tokens!==100000||receipt.terminal!=='complete_untruncated'||['record_sha256','executor_call_sha256'].some(k=>typeof receipt[k]!=='string'||! /^[0-9a-f]{64}$/.test(receipt[k]))||typeof receipt.tool_reference!=='string'||! /^functions\.exec(?:\/[A-Za-z0-9_-]{1,64})?$/.test(receipt.tool_reference))throw Error('approval_receipt');
 if(!keys(observation,'reference,body')||typeof observation.reference!=='string'||observation.reference.length>96||! /^https:\/\/github\.com\/lordcoudy\/VAST\/pull\/9#issuecomment-[1-9][0-9]{0,19}$/.test(observation.reference)||typeof observation.body!=='string'||observation.body.length>8192||!observation.body.endsWith('\n'))throw Error('approval_observation');
 let receiptSHA=gate2SHA256(gate2Canonical(receipt,2048)),body=JSON.parse(observation.body);
 if(typeof body.independent_review_reference!=='string'||body.independent_review_reference.length>96||! /^https:\/\/github\.com\/lordcoudy\/VAST\/pull\/9#issuecomment-[1-9][0-9]{0,19}$/.test(body.independent_review_reference)||body.independent_review_reference===observation.reference)throw Error('approval_independent_review_reference');
 let expected={version:1,kind:'vast_gate2_external_delivery_approval_v1',receipt_sha256:receiptSHA,context_sha256:contextSHA,...context,decision:'approved_for_C1',approval_type:'delegated_agent_self_approval',independent_review_reference:body.independent_review_reference};
 if(gate2Canonical(body,8191)+'\n'!==observation.body||gate2Canonical(body,8191)!==gate2Canonical(expected,8191))throw Error('approval_body_binding');
 return {receipt,approval:{reference:observation.reference,body_sha256:gate2SHA256(observation.body),receipt_sha256:receiptSHA}};
}"""

EXECUTOR_INERT_JOURNAL = r"""{"timestamp":"2026-10-17T03:10:11.134Z","ordinal":22881,"type":"response_item","payload":{"type":"custom_tool_call","id":"ctc_0ea3ffc61cb9d677016ad2e7127fc881918f1ed1e22427428e","status":"completed","call_id":"call_ff8e9134a8224584b38d013008e78576","name":"exec","input":"// @exec: {\"yield_time_ms\": 1, \"max_output_tokens\": 100000}\ntext(\"gate2.inert.profile.fragment.1\");\nawait new Promise(resolve=>setTimeout(resolve,80));\ntext(\"gate2.inert.profile.fragment.2\");\n","internal_chat_message_metadata_passthrough":{"turn_id":"01a145ff-abae-77e3-b14b-a30674a2e325","create_time":1792206610.5025494}}}
{"timestamp":"2026-10-17T03:10:11.188Z","ordinal":22883,"type":"response_item","payload":{"type":"custom_tool_call_output","id":"ctco_01a147d6-a2f4-7822-91d8-0bc441287fec","call_id":"call_ff8e9134a8224584b38d013008e78576","output":[{"type":"input_text","text":"Script running with cell ID 1368\nWall time 0.0 seconds\nOutput:\n"},{"type":"input_text","text":"gate2.inert.profile.fragment.1"}],"internal_chat_message_metadata_passthrough":{"turn_id":"01a145ff-abae-77e3-b14b-a30674a2e325","create_time":1792206611.1884632}},"metadata":{"client_authored":false,"fallback_token_limit_override":12000}}
{"timestamp":"2026-10-17T03:10:14.497Z","ordinal":22885,"type":"response_item","payload":{"type":"function_call","id":"fc_0ea3ffc61cb9d677016ad2e71650d48191be8ce5d909af01ac","name":"wait","arguments":"{\"cell_id\":\"1368\",\"max_tokens\":100000,\"yield_time_ms\":1000}","call_id":"call_b75b2a4aacc048fba4082f32a48df26e","internal_chat_message_metadata_passthrough":{"turn_id":"01a145ff-abae-77e3-b14b-a30674a2e325","create_time":1792206614.3225687}},"metadata":{"client_authored":false,"user_input_order":2298}}
{"timestamp":"2026-10-17T03:10:14.578Z","ordinal":22887,"type":"response_item","payload":{"type":"function_call_output","id":"fco_01a147d6-b032-7ba1-a3a9-1903bdecdd11","call_id":"call_b75b2a4aacc048fba4082f32a48df26e","output":[{"type":"input_text","text":"Script completed\nWall time 0.0 seconds\nOutput:\n"},{"type":"input_text","text":"gate2.inert.profile.fragment.2"}],"internal_chat_message_metadata_passthrough":{"turn_id":"01a145ff-abae-77e3-b14b-a30674a2e325","create_time":1792206614.5783863}},"metadata":{"client_authored":false,"fallback_token_limit_override":12000}}
"""

class ResumeRootCaller(unittest.TestCase):
    @staticmethod
    def executor_fixture():
        return [json.loads(line) for line in EXECUTOR_INERT_JOURNAL.splitlines()]

    @classmethod
    def executor_chain(cls,record,source):
        rows=cls.executor_fixture()
        chain=[{'call':rows[0]['payload'],'result':rows[1]['payload']},{'call':rows[2]['payload'],'result':rows[3]['payload']}]
        chain[0]['call']['input']=source
        chain[0]['result']['output']=chain[0]['result']['output'][:1]
        chain[1]['result']['output'][1]['text']=record
        return chain

    def test_actual_outer_journal_blocks_raw_arguments_and_metadata_are_retained(self):
        self.assertEqual(len(EXECUTOR_INERT_JOURNAL.encode('utf-8')),2299)
        self.assertEqual(hashlib.sha256(EXECUTOR_INERT_JOURNAL.encode('utf-8')).hexdigest(),'f183bfa6c801e991e47efc67e1a095c705de329354f99043058e09c26d0d530c')
        rows=self.executor_fixture();chain=[{'call':rows[0]['payload'],'result':rows[1]['payload']},{'call':rows[2]['payload'],'result':rows[3]['payload']}]
        self.assertIsInstance(chain[1]['call']['arguments'],str)
        self.assertEqual(len(chain[0]['call']['input'].encode('ascii')),192)
        self.assertEqual(len(chain[1]['call']['arguments'].encode('ascii')),59)
        expected=chain[0]['result']['output'][1]['text']+chain[1]['result']['output'][1]['text']
        value=self.js("console.log(JSON.stringify(gate2ExecutorDocument(input.chain,input.expectedSourceSHA,input.reference)));",{'chain':chain,'expectedSourceSHA':hashlib.sha256(chain[0]['call']['input'].encode('ascii')).hexdigest(),'reference':'functions.exec/1368'})
        self.assertEqual(value,{'text':expected,'sha256':hashlib.sha256(subject().canonical(chain)).hexdigest()})

    def test_actual_outer_blocks_refuse_reconstruction_ids_order_and_raw_arg_changes(self):
        import copy
        rows=self.executor_fixture();base={'chain':[{'call':rows[0]['payload'],'result':rows[1]['payload']},{'call':rows[2]['payload'],'result':rows[3]['payload']}],'expectedSourceSHA':hashlib.sha256(rows[0]['payload']['input'].encode('ascii')).hexdigest(),'reference':'functions.exec/1368'};cases=[]
        def add(change):
            value=copy.deepcopy(base);change(value);cases.append(value)
        add(lambda x:x['chain'][0].update(result='Script running with cell ID 1368\nWall time 0.0 seconds\nOutput:\n'))
        add(lambda x:x['chain'][1]['call'].update(arguments=json.loads(x['chain'][1]['call']['arguments'])))
        add(lambda x:x['chain'].reverse())
        add(lambda x:x['chain'][1]['result'].update(call_id='other'))
        add(lambda x:x['chain'][1]['call'].update(call_id=x['chain'][0]['call']['call_id']))
        add(lambda x:x['chain'][1]['call'].update(name='exec'))
        add(lambda x:x['chain'][1]['result'].update(type='custom_tool_call_output'))
        add(lambda x:x['chain'][0]['result']['output'].reverse())
        add(lambda x:x['chain'][1]['result'].update(output=[]))
        add(lambda x:x['chain'][1]['result']['output'][1].update(type='text'))
        add(lambda x:x['chain'][1]['result']['output'][0].update(text=x['chain'][1]['result']['output'][0]['text']+'embedded body'))
        add(lambda x:x['chain'][1]['call'].update(arguments='{"cell_id":"1368","max_tokens":10000,"yield_time_ms":1000}'))
        add(lambda x:x['chain'][1]['call'].update(arguments='{"cell_id":"wrong","max_tokens":100000,"yield_time_ms":1000}'))
        add(lambda x:x['chain'][1]['call'].update(arguments='{"cell_id":"1368","max_tokens":100000,"max_tokens":100000,"yield_time_ms":1000}'))
        add(lambda x:x['chain'][0]['result']['output'][0].update(text='Script completed\nWall time 0.0 seconds\nOutput:\n'))
        add(lambda x:x['chain'].pop())
        add(lambda x:x['chain'][0]['call'].update(input=x['chain'][0]['call']['input']+'text("altered");'))
        value=self.js("console.log(JSON.stringify(input.map(x=>{try{gate2ExecutorDocument(x.chain,x.expectedSourceSHA,x.reference);return false;}catch(e){return true;}})));",cases)
        self.assertTrue(all(value),value)

    def test_observed_original_wrapper_only_string_has_no_embedded_payload_fallback(self):
        import copy
        sample=self.delivery_sample();chain=sample['chain']
        chain[0]['result']['output']='Script running with cell ID 1463\nWall time 0.0 seconds\nOutput:\n'
        chain[1]['call']['arguments']=chain[1]['call']['arguments'].replace('1368','1463')
        sample['reference']='functions.exec/1463'
        self.assertEqual(len(chain[0]['result']['output'].encode('ascii')),63)
        value=self.js("console.log(JSON.stringify(gate2Receive(input.record,input.chain,input.context,input.reference,input.expectedExecutorSourceSHA)));",sample)
        self.assertEqual(value['record_sha256'],hashlib.sha256(sample['record'].encode('ascii')).hexdigest())
        self.assertEqual(value['executor_call_sha256'],hashlib.sha256(subject().canonical(chain)).hexdigest())
        cases=[]
        for wrapper in (chain[0]['result']['output']+'embedded payload',chain[0]['result']['output']+'\n',chain[0]['result']['output'].replace('Output:','Unknown:'),'Unavailable',chain[0]['result']['output'].replace('running with cell ID 1463','completed')):
            changed=copy.deepcopy(sample);changed['chain'][0]['result']['output']=wrapper;cases.append(changed)
        changed=copy.deepcopy(sample);changed['chain'][1]['result']['output']='Script completed\nWall time 0.0 seconds\nOutput:\n'+sample['record'];cases.append(changed)
        changed=copy.deepcopy(sample);changed['expectedExecutorSourceSHA']='0'*64;cases.append(changed)
        values=self.js("console.log(JSON.stringify(input.map(x=>{try{gate2Receive(x.record,x.chain,x.context,x.reference,x.expectedExecutorSourceSHA);return false;}catch(e){return true;}})));",cases)
        self.assertTrue(all(values),values)

    def test_actual_full_host_recorded_transport_is_structural_only_with_old_pin_refusal(self):
        base=Path(__file__).parents[1]/'openspec/changes/fix-accepted-policy-preprocessing/evidence/compiler-component-01/gate2-implementation-tests'
        def read(name,size,digest):
            raw=(base/name).read_bytes();self.assertEqual(len(raw),size);self.assertEqual(hashlib.sha256(raw).hexdigest(),digest);return raw
        raw_chain=read('vast-gate2-inert-full-transport-151.payload-chain.derived.json',54423,'d4ec324635186004cb61c6b2e1d2525f8ca5c78378cd098d2a0da5736677b588')
        journal=read('vast-gate2-inert-full-transport-151.journal-excerpt.original.jsonl',54956,'14b5dffabf1c62e61b303ac33f8b8b277f9a5f86f26ad1ce2d6f8839d98375ef')
        record=read('vast-gate2-synthetic-root-max-u64-149.export.original.json',50956,'254bf909ad3d7c007415e43dafb497dac87ce5762a88aebb16feb57895fa2e2d').decode('ascii')
        context=json.loads(read('vast-gate2-synthetic-root-max-u64-149.context.derived.json',1709,'555acccc7890a97b00bce033692263e175933a9015a98a5e642e1834d8a8e9eb'))['context']
        rows=[json.loads(line) for line in journal.splitlines()];chain=json.loads(raw_chain)
        self.assertEqual(chain,[{'call':rows[0]['payload'],'result':rows[1]['payload']},{'call':rows[2]['payload'],'result':rows[3]['payload']}])
        self.assertIsInstance(chain[0]['result']['output'],str)
        self.assertEqual(len(chain[0]['result']['output'].encode('ascii')),63)
        observed_sha=hashlib.sha256(chain[0]['call']['input'].encode('ascii')).hexdigest()
        self.assertEqual(observed_sha,'aa586219ba76920962db99b3f0192497aea07b48daee70ca87d98ec3504bc73f')
        old_pin='553824e5b6351eaa1788e8377fa105cdd5481077b31eda6c27d20ecc9df43336'
        # Observed-source parsing proves host-recorded bytes only; it cannot repair the original prepin.
        value=self.js("let view=gate2ExecutorDocument(input.chain,input.observed_sha,input.reference),cause=null;try{gate2Receive(input.record,input.chain,input.context,input.reference,input.old_pin);}catch(e){cause=e.message;}console.log(JSON.stringify({same:view.text===input.record,size:view.text.length,sha256:gate2SHA256(view.text),chain_sha256:view.sha256,cause}));",{'chain':chain,'record':record,'context':context,'observed_sha':observed_sha,'old_pin':old_pin,'reference':'functions.exec/1463'})
        self.assertEqual(value,{'same':True,'size':50956,'sha256':'254bf909ad3d7c007415e43dafb497dac87ce5762a88aebb16feb57895fa2e2d','chain_sha256':hashlib.sha256(subject().canonical(chain)).hexdigest(),'cause':'executor_source_binding'})

    def test_executor_expected_source_pin_includes_exact_single_final_lf(self):
        sample=self.delivery_sample();source=sample['chain'][0]['call']['input']
        self.assertTrue(source.endswith('\n'));self.assertFalse(source.endswith('\n\n'))
        self.assertEqual(sample['expectedExecutorSourceSHA'],hashlib.sha256(source.encode('ascii')).hexdigest())
        sample['expectedExecutorSourceSHA']=hashlib.sha256(source[:-1].encode('ascii')).hexdigest()
        cause=self.js("let cause=null;try{gate2Receive(input.record,input.chain,input.context,input.reference,input.expectedExecutorSourceSHA);}catch(e){cause=e.message;}console.log(JSON.stringify(cause));",sample)
        self.assertEqual(cause,'executor_source_binding')

    def js(self,body,values=None):
        import shutil,subprocess
        node=shutil.which('node') or shutil.which('node.exe')
        source=ROOT_ENCODER+'\n'+ROOT_SHA256+'\n'+ROOT_ORCHESTRATOR+'\n'+ROOT_RECEIVER+"\nconst input=JSON.parse(require('node:fs').readFileSync(0,'utf8'));\n"+body
        r=subprocess.run([node,'-e',source],input=json.dumps(values).encode(),capture_output=True)
        self.assertEqual(r.returncode,0,r.stderr.decode(errors='replace'))
        return json.loads(r.stdout)

    def delivery_sample(self):
        import copy
        if not hasattr(type(self),'_delivery_sample'):
            caller=ResumeNodeCaller();code=caller.carrier(caller.code())
            value=caller.node(code,root_flow=True,root_pending=5,output=caller.success_output())
            self.assertTrue(value['root']['completed'],value['root']);self.assertIsNone(value['root_export_error'])
            record=value['root_export'];context=dict(zip(('code_commit','packet_size_bytes','packet_sha256','selected_sha256','core_sha256','factory_sha256'),value['root']['context'][1:]))
            profile={'max_output_tokens':100000,'max_record_bytes':65536}
            suffix='\nawait gate2Resume.finish('+json.dumps(value['root']['setup']['selected'],separators=(',',':'))+');'
            finalizer=value['root']['writer_call']['code'][:-len(suffix)]
            source='// @exec: {"yield_time_ms":1,"max_output_tokens":100000}\n'+ROOT_ENCODER+'\n'+ROOT_SHA256+'\n'+ROOT_ORCHESTRATOR+'\nconst profile='+json.dumps(profile,separators=(',',':'))+';const record=await gate2Complete(tools,'+json.dumps(code)+','+json.dumps(finalizer)+',profile,'+json.dumps({k:context[k] for k in ('code_commit','core_sha256','factory_sha256')},separators=(',',':'))+');text(gate2Export(record,profile));\n'
            chain=self.executor_chain(record,source)
            type(self)._delivery_sample={'record':record,'chain':chain,'context':context,'reference':'functions.exec/1368','expectedExecutorSourceSHA':hashlib.sha256(source.encode('ascii')).hexdigest()}
        return copy.deepcopy(type(self)._delivery_sample)

    def test_external_export_exact_64k_ascii_lf_and_one_byte_over(self):
        profile={'max_output_tokens':100000,'max_record_bytes':65536}
        value={'x':''};value['x']='a'*(65535-len(subject().canonical(value)))
        result=self.js("console.log(JSON.stringify(gate2Export(input.value,input.profile)));",{'value':value,'profile':profile})
        self.assertEqual(len(result.encode('ascii')),65536);self.assertEqual(result[-1],'\n');self.assertFalse(result.endswith('\n\n'))
        value['x']+='a'
        self.assertTrue(self.js("let refused=false;try{gate2Export(input.value,input.profile);}catch(e){refused=true;}console.log(JSON.stringify(refused));",{'value':value,'profile':profile}))

    def test_external_receiver_hashes_complete_actual_record_and_executor_chain(self):
        sample=self.delivery_sample()
        result=self.js("console.log(JSON.stringify(gate2Receive(input.record,input.chain,input.context,input.reference,input.expectedExecutorSourceSHA)));",sample)
        context=sample['context'];m=subject()
        self.assertEqual(result,{'version':1,'context_sha256':m.sha(m.canonical(['vast.gate2.external-delivery.v1',context['code_commit'],context['packet_size_bytes'],context['packet_sha256'],context['selected_sha256'],context['core_sha256'],context['factory_sha256']])),
          'record_size_bytes':len(sample['record']),'record_sha256':m.sha(sample['record'].encode('ascii')),'executor_call_sha256':m.sha(m.canonical(sample['chain'])),
          'max_output_tokens':100000,'terminal':'complete_untruncated','tool_reference':'functions.exec/1368'})
        self.assertGreater(len(m.canonical(sample['chain'])),65536)
        import copy
        first=copy.deepcopy(sample['chain'][0]);first['result']['output']=[{'type':'input_text','text':'Script completed\nWall time 0.1 seconds\nOutput:\n'},{'type':'input_text','text':sample['record']}]
        immediate=dict(sample,chain=[first],reference='functions.exec')
        other=self.js("console.log(JSON.stringify(gate2Receive(input.record,input.chain,input.context,input.reference,input.expectedExecutorSourceSHA)));",immediate)
        self.assertEqual(other['tool_reference'],'functions.exec');self.assertEqual(other['record_sha256'],result['record_sha256'])
        self.assertEqual(other['executor_call_sha256'],m.sha(m.canonical(immediate['chain'])))
        annotated=self.delivery_sample();record=json.loads(annotated['record'])
        record['writer']['content'][0]['annotations']={'audience':['assistant'],'priority':0.5}
        record['verification']['content'][0]['_meta']={'actual_extra':'retained'}
        annotated['record']=m.canonical(record).decode()+'\n';annotated['chain'][1]['result']['output'][1]['text']=annotated['record'];annotated['chain'][0]['call']['actual_extra']={'nested':'preserved'};annotated['chain'][1]['result']['output'][1]['_meta']={'annotation':'kept'}
        extra=self.js("console.log(JSON.stringify(gate2Receive(input.record,input.chain,input.context,input.reference,input.expectedExecutorSourceSHA)));",annotated)
        self.assertEqual(extra['record_sha256'],m.sha(annotated['record'].encode('ascii')))
        self.assertNotEqual(extra['record_sha256'],result['record_sha256'])

    def test_external_receiver_refuses_missing_truncated_budget_context_and_causal_changes(self):
        import copy
        base=self.delivery_sample();cases=[]
        def add(change):
            x=copy.deepcopy(base);change(x);cases.append(x)
        add(lambda x:x.update(record=x['record'][:-1]))
        add(lambda x:x.pop('expectedExecutorSourceSHA'))
        add(lambda x:x['chain'][0]['call'].update(input='// @exec: {"yield_time_ms":1,"max_output_tokens":100000}\ntext("forgedRecord");'))
        add(lambda x:x['chain'].pop())
        add(lambda x:x['chain'][1]['call'].update(arguments=' {"cell_id":"1368","max_tokens":10000,"yield_time_ms":1000}'))
        add(lambda x:x['chain'][1]['call'].update(arguments='{"cell_id":"other","max_tokens":100000,"yield_time_ms":1000}'))
        add(lambda x:x['chain'][0]['call'].update(input=x['chain'][0]['call']['input'].replace('"max_output_tokens":100000','"max_output_tokens":10000',1)))
        add(lambda x:x['chain'][0]['result']['output'][0].update(text='Script completed\nWall time 0.0 seconds\nOutput:\n'))
        add(lambda x:x['chain'][1]['result']['output'][1].update(text=x['chain'][1]['result']['output'][1]['text'][:-12]+'[truncated]'))
        add(lambda x:x['chain'][1]['result']['output'][0].update(text='Unavailable\n'+x['chain'][1]['result']['output'][0]['text']))
        for key in ('code_commit','packet_sha256','selected_sha256','core_sha256','factory_sha256'):
            add(lambda x,k=key:x['context'].update({k:('0'*40 if k=='code_commit' else '0'*64)}))
        add(lambda x:x['context'].update(packet_size_bytes=1))
        for field in ('setup_success','verification_call','actual_setup_call','actual_proof','old_six_field_proof'):
            x=copy.deepcopy(base);record=json.loads(x['record'])
            if field=='setup_success':record['setup_success']=False
            elif field=='verification_call':record['verification_call']['code']='gate2Resume.verifyReturn("other");'
            elif field=='actual_setup_call':record['setup']['observed']['calls'][0]['timeout_ms']=31000
            elif field=='old_six_field_proof':record['verification']['content'][0]['text']=json.dumps(json.loads(record['verification']['content'][0]['text'])[:6],separators=(',',':'))
            else:record['verification']['content'][0]['text']=json.dumps([3,1,150010,False,True,record['selected_sha256'],record['context']],separators=(',',':'))
            x['record']=subject().canonical(record).decode()+'\n';x['chain'][1]['result']['output'][1]['text']=x['record'];cases.append(x)
        result=self.js("console.log(JSON.stringify(input.map(x=>{try{gate2Receive(x.record,x.chain,x.context,x.reference,x.expectedExecutorSourceSHA);return false;}catch(e){return true;}})));",cases)
        self.assertTrue(all(result),result)

    def test_external_approval_requires_actual_closed_body_bindings_not_url_alone(self):
        sample=self.delivery_sample();receipt=self.js("console.log(JSON.stringify(gate2Receive(input.record,input.chain,input.context,input.reference,input.expectedExecutorSourceSHA)));",sample)
        m=subject();context=sample['context'];digest=m.sha(m.canonical(receipt))
        body={'version':1,'kind':'vast_gate2_external_delivery_approval_v1','receipt_sha256':digest,'context_sha256':receipt['context_sha256'],**context,'decision':'approved_for_C1',
          'approval_type':'delegated_agent_self_approval','independent_review_reference':'https://github.com/lordcoudy/VAST/pull/9#issuecomment-6228893328'}
        observation={'reference':'https://github.com/lordcoudy/VAST/pull/9#issuecomment-6228893329','body':m.canonical(body).decode()+'\n'}
        value={'receipt':receipt,'context':context,'observation':observation}
        result=self.js("console.log(JSON.stringify(gate2Approve(input.receipt,input.context,input.observation)));",value)
        self.assertEqual(result,{'receipt':receipt,'approval':{'reference':observation['reference'],'body_sha256':m.sha(observation['body'].encode()),'receipt_sha256':digest}})
        cases=[]
        for key in ('receipt_sha256','context_sha256','packet_sha256','code_commit','decision','approval_type'):
            changed=dict(body);changed[key]='changed';cases.append({**value,'observation':dict(observation,body=m.canonical(changed).decode()+'\n')})
        cases.append({**value,'observation':dict(observation,body='{}\n')})
        cases.append({**value,'observation':dict(observation,reference='https://github.com/lordcoudy/VAST/pull/10#issuecomment-6228893329')})
        for reference in (observation['reference'],'https://github.com/lordcoudy/VAST/pull/10#issuecomment-6228893328'):
            changed=dict(body,independent_review_reference=reference);cases.append({**value,'observation':dict(observation,body=m.canonical(changed).decode()+'\n')})
        result=self.js("console.log(JSON.stringify(input.map(x=>{try{gate2Approve(x.receipt,x.context,x.observation);return false;}catch(e){return true;}})));",cases)
        self.assertTrue(all(result),result)

    def test_pure_ascii_sha256_matches_standard_and_padding_boundary_vectors(self):
        values=['','abc','a'*55,'b'*56,'c'*63,'d'*64,'e'*65,'f'*119,'g'*128,'0123456789abcdef'*64]
        result=self.js("console.log(JSON.stringify(input.map(gate2SHA256)));",values)
        self.assertEqual(result,[hashlib.sha256(s.encode('ascii')).hexdigest() for s in values])

    def test_required_external_output_profile_refuses_before_any_provider_call(self):
        body=ROOT_ORCHESTRATOR+r"""
let observed=[];for(let profile of [null,{}, {max_output_tokens:10000,max_record_bytes:65536},{max_output_tokens:100000,max_record_bytes:65535},{max_output_tokens:100000,max_record_bytes:65536,extra:true}]){
 let calls=0,refused=false;try{await gate2Complete({mcp__node_repl__js:async()=>{calls++;throw Error('must_not_call');}},'initial','finalizer',profile);}catch(e){refused=true;}observed.push({calls,refused});}
console.log(JSON.stringify(observed));"""
        result=self.js('(async()=>{'+body+'})().catch(e=>{console.error(e);process.exitCode=1;});')
        self.assertTrue(all(v=={'calls':0,'refused':True} for v in result))

    def test_required_precall_review_pins_refuse_before_any_provider_call(self):
        body=r"""let profile={max_output_tokens:100000,max_record_bytes:65536},good={code_commit:'1234567890abcdef1234567890abcdef12345678',core_sha256:gate2SHA256('initial'),factory_sha256:'0123456789abcdef'.repeat(4)},observed=[];
for(let expected of [null,{}, {...good,extra:true},{...good,code_commit:'wrong'},{...good,core_sha256:'0'.repeat(64)},{...good,factory_sha256:null}]){let calls=0,refused=false;try{await gate2Complete({mcp__node_repl__js:async()=>{calls++;throw Error('must_not_call');}},'initial','finalizer',profile,expected);}catch(e){refused=true;}observed.push({calls,refused});}console.log(JSON.stringify(observed));"""
        result=self.js('(async()=>{'+body+'})().catch(e=>{console.error(e);process.exitCode=1;});')
        self.assertTrue(all(v=={'calls':0,'refused':True} for v in result))

    def test_commit_types_refuse_before_provider_or_commit_coercion(self):
        body=r"""let good='1234567890123456789012345678901234567890',profile={max_output_tokens:100000,max_record_bytes:65536},observed=[];
for(let [label,make] of [['bigint',()=>BigInt(good)],['wrapper',()=>new String(good)],['coercible',counter=>({toString(){counter.n++;return good;}})],['number',()=>1e39],['null',()=>null],['undefined',()=>undefined],['array',()=>[good]]]){
 let pre={n:0},context={n:0},calls=0,cause=null,contextCause=null;
 try{await gate2Complete({mcp__node_repl__js:async()=>{calls++;throw Error('must_not_call');}},'initial','finalizer',profile,{code_commit:make(pre),core_sha256:gate2SHA256('initial'),factory_sha256:'0123456789abcdef'.repeat(4)});}catch(e){cause=e.message;}
 try{gate2Context({code_commit:make(context),packet_size_bytes:10,packet_sha256:'0123456789abcdef'.repeat(4),selected_sha256:'123456789abcdef0'.repeat(4),core_sha256:gate2SHA256('initial'),factory_sha256:'23456789abcdef01'.repeat(4)});}catch(e){contextCause=e.message;}
 observed.push({label,calls,cause,contextCause,preCoercions:pre.n,contextCoercions:context.n});
}
let validCalls=0;await gate2Complete({mcp__node_repl__js:async()=>{validCalls++;throw Error('controlled_stop');}},'initial','finalizer',profile,{code_commit:good,core_sha256:gate2SHA256('initial'),factory_sha256:'0123456789abcdef'.repeat(4)});
let validContext=gate2Context({code_commit:good,packet_size_bytes:10,packet_sha256:'0123456789abcdef'.repeat(4),selected_sha256:'123456789abcdef0'.repeat(4),core_sha256:gate2SHA256('initial'),factory_sha256:'23456789abcdef01'.repeat(4)});
console.log(JSON.stringify({observed,validCalls,validContext}));"""
        value=self.js('(async()=>{'+body+'})().catch(e=>{console.error(e);process.exitCode=1;});')
        self.assertEqual(len(value['observed']),7)
        for result in value['observed']:
            with self.subTest(label=result['label']):
                self.assertEqual(result['calls'],0)
                self.assertEqual(result['cause'],'external_expected_pins')
                self.assertEqual(result['contextCause'],'delivery_context')
                self.assertEqual(result['preCoercions'],0)
                self.assertEqual(result['contextCoercions'],0)
        self.assertEqual(value['validCalls'],1)
        self.assertRegex(value['validContext'],r'^[0-9a-f]{64}$')

    def test_closed_records_refuse_nonrecords_before_provider_or_getter(self):
        body=r"""let good={profile:{max_output_tokens:100000,max_record_bytes:65536},pins:{code_commit:'1234567890123456789012345678901234567890',core_sha256:gate2SHA256('initial'),factory_sha256:gate2SHA256('factory')},context:{code_commit:'1234567890123456789012345678901234567890',packet_size_bytes:1,packet_sha256:gate2SHA256('packet'),selected_sha256:gate2SHA256('selected'),core_sha256:gate2SHA256('initial'),factory_sha256:gate2SHA256('factory')}},observed=[];
for(let label of ['array','function','boxed_string','custom_prototype','accessor','plain','null_prototype'])for(let role of ['profile','pins','context']){
 let record=label==='array'?[]:label==='function'?function(){}:label==='boxed_string'?new String(''):label==='custom_prototype'?Object.create({}):label==='null_prototype'?Object.create(null):{};
 Object.assign(record,good[role]);let calls=0,getters=0,cause=null;
 if(label==='accessor'){let key=role==='profile'?'max_output_tokens':'code_commit';Object.defineProperty(record,key,{enumerable:true,get(){getters++;return good[role][key];}});}
 try{if(role==='context')gate2Context(record);else await gate2Complete({mcp__node_repl__js:async()=>{calls++;throw Error('controlled_stop');}},'initial','finalizer',role==='profile'?record:good.profile,role==='pins'?record:good.pins);}catch(e){cause=e.message;}
 observed.push({label,role,calls,getters,cause});
}console.log(JSON.stringify(observed));"""
        values=self.js('(async()=>{'+body+'})().catch(e=>{console.error(e);process.exitCode=1;});')
        self.assertEqual(len(values),21)
        for value in values:
            with self.subTest(label=value['label'],role=value['role']):
                allowed=value['label'] in ('plain','null_prototype')
                self.assertEqual(value['calls'],int(allowed and value['role']!='context'))
                self.assertEqual(value['getters'],0)
                self.assertEqual(value['cause'],None if allowed else {'profile':'external_output_profile','pins':'external_expected_pins','context':'delivery_context'}[value['role']])

    def test_two_pass_complete_provider_encoder_matches_ascii_and_12k_boundary(self):
        x={'call':{'code':'fixed "\\\n'},'frames':[{'content':[{'type':'text','text':'{'+str(2**64-1)+'}'}],
          'isError':False,'unknown_meta':{'\U0001f600':'\ud800\n\\"','resource':{'uri':'fixed:reference'}}}]}
        expected=subject().canonical(x).decode()
        value=self.js("console.log(JSON.stringify(gate2Canonical(input,12288)));",x)
        self.assertEqual(value,expected)
        base={'x':''};n=12288-len(subject().canonical(base));base['x']='a'*n
        self.assertEqual(len(self.js("console.log(JSON.stringify(gate2Canonical(input,12288)));",base)),12288)
        base['x']+='a'
        self.assertTrue(self.js("let refused=false;try{gate2Canonical(input,12288);}catch(e){refused=true;}console.log(JSON.stringify(refused));",base))

    def test_provider_encoder_refuses_unsupported_without_getters_or_early_encoding(self):
        body=r"""let results=[],getter=0;
for(let x of [NaN,Infinity,-0,9007199254740992,1n,undefined,()=>0]){try{gate2Canonical({x},12288);results.push(false);}catch(e){results.push(true);}}
let a={};a.self=a;try{gate2Canonical(a,12288);results.push(false);}catch(e){results.push(true);}
a={};Object.defineProperty(a,'x',{enumerable:true,get(){getter++;return 1;}});try{gate2Canonical(a,12288);results.push(false);}catch(e){results.push(true);}
const old=JSON.stringify;let encoded=0;JSON.stringify=(...a)=>{encoded++;return old(...a);};try{gate2Canonical({x:'x'.repeat(12289)},12288);results.push(false);}catch(e){results.push(true);}JSON.stringify=old;
console.log(JSON.stringify({results,getter,encoded}));"""
        value=self.js(body)
        self.assertTrue(all(value['results']));self.assertEqual(value['getter'],0);self.assertEqual(value['encoded'],0)

    def test_pinned_lossless_integer_view_uses_original_lexemes_and_rejects_duplicates(self):
        body=NODE_INNER_VIEW+r"""
let a=gate2View('{"a":18446744073709551615,"b":[true,null,"opaque"]}');
let bad=[];for(let x of ['{"a":1,"a":1}','{"a":1.0}','{"a":1e2}','{"a":-0}','{"b":2,"a":1}','{"a":NaN}']){try{gate2View(x);bad.push(false);}catch(e){bad.push(true);}}
console.log(JSON.stringify({type:typeof a.a,exact:a.a.toString(),bad,raw:JSON.stringify({a:JSON.rawJSON(a.a.toString())})}));"""
        value=self.js(body)
        self.assertEqual(value['type'],'bigint');self.assertEqual(value['exact'],str(2**64-1))
        self.assertTrue(all(value['bad']));self.assertEqual(value['raw'],'{"a":18446744073709551615}')

    def test_inner_canonical_numeric_and_unicode_keys_preserve_scalar_sorting(self):
        values=[{'10':10,'2':2},{'\ue000':2,'\U00010000':3},{'__proto__':{'constructor':str(2**64-1)}}]
        for value in values:
            raw=subject().canonical(value).decode()
            result=self.js(NODE_INNER_VIEW+"\nlet v=gate2View(input);console.log(JSON.stringify(gate2Ascii(v)));",raw)
            self.assertEqual(result,raw)
        result=self.js(NODE_INNER_VIEW+r"""
let refused=[];for(let s of ['{"2":2,"10":10}','{"a":1,"\\u0061":1}','{"a":1e0}','{"a":1.0}','{"a":-0}']){try{gate2View(s);refused.push(false);}catch(e){refused.push(true);}}console.log(JSON.stringify(refused));""")
        self.assertTrue(all(result))

    def test_fixed_orchestrator_preserves_complete_provider_objects_and_exact_args(self):
        body=ROOT_ORCHESTRATOR+r"""
let args=[],n=0,clock=7;
const r=[{content:[{type:'text',text:'[0,0]'}],isError:false,_meta:{resource:{uri:'held:1'}}},
 {content:[{type:'text',text:'[1,0]'}],isError:false,resource:{mimeType:'application/octet-stream'},unknown:['18446744073709551615']}];
const tools={mcp__node_repl__js:async x=>{args.push(x);return r[n++];}};
const state=await gate2Run(tools,'FIRST','POLL',32000);
console.log(JSON.stringify({state,args,r}));"""
        value=self.js('(async()=>{'+body+'})().catch(e=>{console.error(e);process.exitCode=1;});')
        self.assertEqual(value['args'],[{'code':'FIRST','timeout_ms':32000},{'code':'POLL','timeout_ms':32000}])
        selected=json.loads(value['state']['selected'])
        self.assertEqual(selected['frames'],value['r'])
        self.assertEqual(selected['call'],{'tool':'mcp__node_repl__js','timeout_ms':32000,'codes':['FIRST','POLL']})

# Explicit traversal is bounded for host-decoded JSON. Engine enumeration internals
# and huge unsupported hidden/exotic objects remain an ambient allocation boundary;
# this is not a universal heap guarantee. The unchanged encoder rejects hidden keys.
INERT_CONTROL_CAPTURE = r"""const gate2InertCodeSHA=__CODE_SHA__,gate2InertExpected=__EXPECTED__;
function gate2InertBound(value,cap){
 let todo=[{value,depth:0}],active=new Set(),nodes=0,keys=0,work=0,units=0;
 function push(task){if(todo.length>=cap)throw Error('inert_frontier');todo.push(task);}
 while(todo.length){if(++work>cap*4)throw Error('inert_work');let task=todo.pop();if(task.exit){active.delete(task.exit);continue;}
  if(++nodes>cap||task.depth>64)throw Error('inert_structure');let v=task.value;
  if(typeof v==='string'){if((units+=v.length)>cap)throw Error('inert_string');continue;}
  if(v===null||typeof v==='boolean'||typeof v==='number')continue;
  if(typeof v!=='object'||active.has(v))throw Error('inert_kind_cycle');
  let array=Array.isArray(v),proto=Object.getPrototypeOf(v);if(proto!==(array?Array.prototype:Object.prototype)&&proto!==null)throw Error('inert_prototype');
  let length=0;if(array){let d=Object.getOwnPropertyDescriptor(v,'length');if(!d||!('value'in d)||!Number.isSafeInteger(d.value)||d.value<0||d.value>cap)throw Error('inert_array');length=d.value;}
  active.add(v);push({exit:v});let count=0;
  for(let key in v){if(++work>cap*4)throw Error('inert_work');if(!Object.prototype.hasOwnProperty.call(v,key))continue;
   if(++keys>cap||(units+=key.length)>cap)throw Error('inert_keys');let d=Object.getOwnPropertyDescriptor(v,key);if(!d||!d.enumerable||!('value'in d))throw Error('inert_descriptor');
   if(array&&(!/^(0|[1-9][0-9]*)$/.test(key)||Number(key)>=length))throw Error('inert_array');count++;push({value:d.value,depth:task.depth+1});
  }
  if(array&&count!==length)throw Error('inert_array');
 }
 return gate2Canonical(value,cap);
}
function gate2InertArgs(args){
 gate2InertBound(args,16384);
 if(!args||Array.isArray(args)||Object.keys(args).sort().join()!=='code,timeout_ms'||typeof args.code!=='string'||args.code.length<1||args.code.length>8192||/[^\x00-\x7f]/.test(args.code)||args.timeout_ms!==10000||gate2SHA256(args.code)!==gate2InertCodeSHA)throw Error('arguments');
}
function gate2InertProvider(r){
 if(!r||typeof r!=='object'||Array.isArray(r)||('isError'in r&&r.isError!==false))throw Error('provider_unavailable');
 if(Object.keys(r).some(k=>!['content','isError','_meta'].includes(k)))throw Error('provider_fields');
 if(!Array.isArray(r.content)||r.content.length!==1||!r.content[0]||r.content[0].type!=='text'||typeof r.content[0].text!=='string')throw Error('provider_shape');
 if(Object.keys(r.content[0]).some(k=>!['type','text','annotations','_meta'].includes(k)))throw Error('provider_fields');
 if(r.content[0].text!==gate2InertExpected)throw Error('provider_result');
}
async function gate2InertCapture(tools,args){
 let record={version:1,scope:'vast.gate2.inert-control.transport.v1',observation:'failed',arguments:null,code_sha256:null,provider:null,cause:'arguments',unknown_original:true},r;
 try{gate2InertBound(args,16384);record.arguments=args;gate2InertArgs(args);record.code_sha256=gate2InertCodeSHA;Object.freeze(args);}catch{return gate2InertBound(record,32767)+'\n';}
 try{r=await tools.mcp__node_repl__js(args);}catch{record.cause='provider_throw';return gate2InertBound(record,32767)+'\n';}
 try{gate2InertBound(r,16384);}catch{record.cause='provider_bound';return gate2InertBound(record,32767)+'\n';}
 record.provider=r;record.unknown_original=false;
 try{gate2InertProvider(r);record.observation='matched';record.cause=null;}catch(e){record.cause=e.message;}
 try{return gate2InertBound(record,32767)+'\n';}catch{record.provider=null;record.observation='failed';record.cause='transport_bound';record.unknown_original=true;return gate2InertBound(record,32767)+'\n';}
}""".replace('__CODE_SHA__',json.dumps(hashlib.sha256(INERT_CONTROL_SOURCE.encode('ascii')).hexdigest())).replace('__EXPECTED__',json.dumps(INERT_CONTROL_EXPECTED))

INERT_CONTROL_RECEIVER = r"""function gate2InertReceive(chain,expectedSourceSHA,toolReference){
 let need=(v,c)=>{if(!v)throw Error(c);};
 need(Array.isArray(chain)&&chain.length>=1&&chain.length<=3,'inert_pairs');gate2InertBound(chain,131072);
 let first=chain[0]&&chain[0].call&&chain[0].call.input;
 need(typeof first==='string'&&first.length>=1&&first.length<=16384&&!/[^\x00-\x7f]/.test(first)&&first.endsWith('\n')&&!first.endsWith('\n\n'),'inert_source_bound');
 need(first.startsWith('// @exec: {"yield_time_ms":10000,"max_output_tokens":100000}\n'),'inert_exec_profile');let payloadBytes=0;
 for(let [i,row] of chain.entries()){
  if(i){let raw=row&&row.call&&row.call.arguments;need(typeof raw==='string'&&raw.length<=256,'inert_wait_profile');let args=JSON.parse(raw);need(gate2InertBound(args,256)===raw&&Object.keys(args).sort().join()==='cell_id,max_tokens,yield_time_ms'&&args.max_tokens===100000&&args.yield_time_ms===60000,'inert_wait_profile');}
  let output=row&&row.result&&row.result.output;if(Array.isArray(output)){need(output.length>=1&&output.length<=64,'inert_output_shape');for(let n=1;n<output.length;n++){let text=output[n]&&output[n].text;need(typeof text==='string'&&!/[^\x00-\x7f]/.test(text)&&text.length<=32768-payloadBytes,'inert_document_bound');payloadBytes+=text.length;}}
 }
 let executor=gate2ExecutorDocument(chain,expectedSourceSHA,toolReference),text=executor.text;
 need(text.length>=2&&text.length<=32768&&text.endsWith('\n')&&!text.endsWith('\n\n')&&!/[^\x00-\x7f]/.test(text),'inert_document_bound');
 let record=JSON.parse(text);need(gate2InertBound(record,32767)+'\n'===text,'inert_document_canonical');
 need(record&&Object.keys(record).sort().join()==='arguments,cause,code_sha256,observation,provider,scope,unknown_original,version'&&record.version===1&&record.scope==='vast.gate2.inert-control.transport.v1','inert_record');
 need(record.observation==='matched'&&record.cause===null&&record.unknown_original===false,'inert_observation');
 gate2InertArgs(record.arguments);need(record.code_sha256===gate2InertCodeSHA,'inert_code_binding');gate2InertBound(record.provider,16384);gate2InertProvider(record.provider);
 return {version:1,scope:'vast.gate2.inert-control.capture.v1',record_size_bytes:text.length,record_sha256:gate2SHA256(text),executor_chain_sha256:executor.sha256,node_code_sha256:gate2InertCodeSHA,tool_reference:toolReference};
}"""


def inert_control_executor():
    """The sole fixed call is rendered in RAM; this builder never invokes a tool."""
    args=json.dumps(dict(code=INERT_CONTROL_SOURCE,timeout_ms=10000),sort_keys=True,separators=(',',':'),ensure_ascii=True)
    source='// @exec: {"yield_time_ms":10000,"max_output_tokens":100000}\n'+ROOT_ENCODER+'\n'+ROOT_SHA256+'\n'+INERT_CONTROL_CAPTURE+'\nconst args='+args+';\nconst observation=await gate2InertCapture(tools,args);\nstore("gate2-d18-inert-control-observation",observation);text(observation);\n'
    assert source.isascii() and len(source)<=16384 and source.endswith('\n') and not source.endswith('\n\n')
    return source


class InertControlTransportTests(unittest.TestCase):
    def js(self,body,values=None):
        return ResumeRootCaller('runTest').js(INERT_CONTROL_CAPTURE+'\n'+INERT_CONTROL_RECEIVER+'\n'+body,values)

    def args(self):
        return dict(code=INERT_CONTROL_SOURCE,timeout_ms=10000)

    def provider(self):
        return {'content':[{'type':'text','text':INERT_CONTROL_EXPECTED,'annotations':{'audience':['user']},'_meta':{'item':1}}],
                'isError':False,'_meta':{'trace':'controlled','resource':{'uri':'controlled:metadata'}}}

    def chain(self,record,source,pairs=1):
        canonical=lambda value:json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True)
        text=canonical(record)+'\n';rows=[]
        for i in range(pairs):
            call={'call_id':'call_'+str(i),'id':'id_'+str(i),'type':'custom_tool_call' if not i else 'function_call','name':'exec' if not i else 'wait','_meta':{'kept':i}}
            if i:call['arguments']=canonical({'cell_id':'controlled_cell','max_tokens':100000,'yield_time_ms':60000})
            else:call.update(status='completed',input=source)
            wrapper='Script '+('completed' if i==pairs-1 else 'running with cell ID controlled_cell')+'\nWall time 0.0 seconds\nOutput:\n'
            output=[{'type':'input_text','text':wrapper,'_meta':{'header':True}}]
            if i==pairs-1:output.append({'type':'input_text','text':text,'_meta':{'payload':True}})
            rows.append({'call':call,'result':{'call_id':call['call_id'],'id':'result_'+str(i),'type':'custom_tool_call_output' if not i else 'function_call_output','output':output,'_meta':{'kept':True}}})
        return rows

    def test_capture_changed_args_refuse_before_the_single_tool_call(self):
        args=self.args();args['timeout_ms']=10001
        result=self.js("(async()=>{let calls=0;try{let text=await gate2InertCapture({mcp__node_repl__js:async()=>{calls++;return input.provider;}},input.args);console.log(JSON.stringify({calls,record:JSON.parse(text)}));}catch(e){console.log(JSON.stringify({calls,error:e.message}));}})();",{'args':args,'provider':self.provider()})
        self.assertEqual(result['calls'],0)
        self.assertEqual(result['record']['observation'],'failed')
        self.assertEqual(result['record']['cause'],'arguments')

    def test_control_profile_rejects_historical_generic_first_yield(self):
        source='// @exec: {"yield_time_ms":1,"max_output_tokens":100000}\ntext("historical functions-only fixture");\n'
        chain=self.chain({},source)
        result=self.js("let generic=gate2ExecutorDocument(input.chain,input.sha,'functions.exec');let cause=null;try{gate2InertReceive(input.chain,input.sha,'functions.exec');}catch(e){cause=e.message;}console.log(JSON.stringify({generic:generic.text,cause}));",{'chain':chain,'sha':hashlib.sha256(source.encode('ascii')).hexdigest()})
        self.assertEqual(result['generic'],'{}\n')
        self.assertEqual(result['cause'],'inert_exec_profile')

    def capture(self):
        return self.js("(async()=>{let calls=0;let text=await gate2InertCapture({mcp__node_repl__js:async()=>{calls++;return input.provider;}},input.args);console.log(JSON.stringify({calls,text,record:JSON.parse(text)}));})();",{'args':self.args(),'provider':self.provider()})

    def test_exact_rendered_executor_calls_once_and_stores_only_guarded_full_observation(self):
        source=inert_control_executor()
        result=self.js("(async()=>{let calls=0,passed=null,frozen=false,outputs=[],stored=[];const tools={mcp__node_repl__js:async args=>{calls++;passed=args;frozen=Object.isFrozen(args);return input.provider;}},store=(key,value)=>stored.push([key,value]),text=value=>outputs.push(value);await eval('(async()=>{'+input.source+'})()');console.log(JSON.stringify({calls,passed,frozen,outputs,stored}));})();",{'source':source,'provider':self.provider()})
        self.assertEqual(result['calls'],1);self.assertTrue(result['frozen'])
        self.assertEqual(result['passed'],self.args())
        self.assertEqual(len(result['outputs']),1);self.assertEqual(len(result['stored']),1)
        self.assertEqual(result['outputs'][0],result['stored'][0][1])
        record=json.loads(result['outputs'][0]);self.assertEqual(record['provider'],self.provider())
        self.assertEqual(record['arguments'],self.args());self.assertEqual(record['observation'],'matched')
        self.assertFalse(record['unknown_original']);self.assertIsNone(record['cause'])
        self.assertLessEqual(len(source.encode('ascii')),16384)
        self.assertTrue(source.endswith('\n'));self.assertFalse(source.endswith('\n\n'))
        self.assertEqual(source.count('await tools.mcp__node_repl__js(args)'),1)
        self.assertNotIn('physical_acceptance',record)

    def test_bounded_error_and_unsupported_provider_observations_never_retry(self):
        result=self.js("""(async()=>{let rows=[];for(let kind of ['throw','isError','extra_text','wrong_text','missing_text','structured','resource','unknown_top','unknown_block','accessor','cycle','unsafe','negative_zero','bigint','function','symbol','hidden','prototype','sparse']){
 let r=JSON.parse(JSON.stringify(input.provider)),calls=0,getters=0;
 if(kind==='isError')r.isError=true;if(kind==='extra_text')r.content.push({type:'text',text:'extra'});if(kind==='wrong_text')r.content[0].text+='x';if(kind==='missing_text')r.content=[];
 if(kind==='structured')r.structuredContent={extra:true};if(kind==='resource')r.resource={uri:'controlled:extra-output'};if(kind==='unknown_top')r.extra='unsupported';if(kind==='unknown_block')r.content[0].extra='unsupported';
 if(kind==='accessor')Object.defineProperty(r,'bad',{enumerable:true,get(){getters++;return 1;}});if(kind==='cycle')r.self=r;
 if(kind==='unsafe')r.bad=9007199254740992;if(kind==='negative_zero')r.bad=-0;if(kind==='bigint')r.bad=1n;if(kind==='function')r.bad=()=>1;
 if(kind==='symbol')r[Symbol('bad')]=1;if(kind==='hidden')Object.defineProperty(r,'bad',{value:1});if(kind==='prototype')Object.setPrototypeOf(r,{bad:1});if(kind==='sparse')r.bad=Array(2);
 let text=await gate2InertCapture({mcp__node_repl__js:async()=>{calls++;if(kind==='throw')throw Error('controlled provider');return r;}},input.args);
 rows.push({kind,calls,getters,size:text.length,record:JSON.parse(text)});
 }console.log(JSON.stringify(rows));})();""",{'args':self.args(),'provider':self.provider()})
        for row in result:
            with self.subTest(kind=row['kind']):
                self.assertEqual(row['calls'],1);self.assertEqual(row['getters'],0)
                self.assertLessEqual(row['size'],32768);self.assertEqual(row['record']['observation'],'failed')
                retained=row['kind'] in ('isError','extra_text','wrong_text','missing_text','structured','resource','unknown_top','unknown_block')
                self.assertEqual(row['record']['provider'] is not None,retained)
                self.assertEqual(row['record']['unknown_original'],not retained)

    def test_args_structural_and_code_binding_refusals_have_zero_tool_effects(self):
        result=self.js("""(async()=>{let rows=[];for(let kind of ['title','timeout','code','nonascii','overflow','accessor','array','cycle']){
 let args={...input.args},calls=0,getters=0;
 if(kind==='title')args.title='extra';if(kind==='timeout')args.timeout_ms=1;if(kind==='code')args.code+=' ';if(kind==='nonascii')args.code='é';if(kind==='overflow')args.code='x'.repeat(8193);
 if(kind==='accessor')Object.defineProperty(args,'code',{enumerable:true,get(){getters++;return input.args.code;}});if(kind==='array')args=Object.assign([],args);if(kind==='cycle')args.self=args;
 let record=JSON.parse(await gate2InertCapture({mcp__node_repl__js:async()=>{calls++;return input.provider;}},args));rows.push({kind,calls,getters,record});
 }console.log(JSON.stringify(rows));})();""",{'args':self.args(),'provider':self.provider()})
        for row in result:
            with self.subTest(kind=row['kind']):
                self.assertEqual(row['calls'],0);self.assertEqual(row['getters'],0)
                self.assertEqual(row['record']['observation'],'failed');self.assertEqual(row['record']['cause'],'arguments')

    def test_provider_frame_exact_cap_and_one_byte_over_preserve_unicode_metadata(self):
        result=self.js("""(async()=>{let r=input.provider;r._meta.unicode=['é',String.fromCharCode(0),'😀'].join('');r._meta.pad='';let n=16384-gate2InertBound(r,16384).length;r._meta.pad='x'.repeat(n);let width=gate2InertBound(r,16384).length;
 let calls=0,tools={mcp__node_repl__js:async()=>{calls++;return r;}};let exact=JSON.parse(await gate2InertCapture(tools,input.args));r._meta.pad+='x';let over=JSON.parse(await gate2InertCapture(tools,input.args));console.log(JSON.stringify({width,calls,exact,over}));})();""",{'args':self.args(),'provider':self.provider()})
        self.assertEqual(result['width'],16384);self.assertEqual(result['calls'],2)
        self.assertEqual(result['exact']['observation'],'matched')
        self.assertEqual(result['exact']['provider']['_meta']['unicode'],'é'+chr(0)+'😀')
        self.assertEqual(result['over']['cause'],'provider_bound');self.assertIsNone(result['over']['provider'])
        self.assertTrue(result['over']['unknown_original'])

    def test_large_enumerable_deep_and_escaped_inputs_refuse_before_encoding_copy(self):
        result=self.js("""(async()=>{let rows=[];for(let kind of ['enumerable','aggregate_keys','depth','escaped']){
 let r=JSON.parse(JSON.stringify(input.provider)),calls=0,reflections=0,escapes=0,long='\\\\'.repeat(16384);
 if(kind==='enumerable')for(let i=0;i<16385;i++)r['k'+i]=0;
 if(kind==='aggregate_keys')for(let i=0;i<100;i++)r['k'+i+'x'.repeat(200)]=0;
 if(kind==='depth'){let p=r;for(let i=0;i<70;i++)p=p.next={};}if(kind==='escaped')r.bad=long;
 const own=Reflect.ownKeys,stringify=JSON.stringify;Reflect.ownKeys=v=>{if(v===r)reflections++;return own(v);};JSON.stringify=(v,...rest)=>{if(v===long)escapes++;return stringify(v,...rest);};
 let text=await gate2InertCapture({mcp__node_repl__js:async()=>{calls++;return r;}},input.args);Reflect.ownKeys=own;JSON.stringify=stringify;
 rows.push({kind,calls,reflections,escapes,record:JSON.parse(text)});
 }console.log(JSON.stringify(rows));})();""",{'args':self.args(),'provider':self.provider()})
        for row in result:
            with self.subTest(kind=row['kind']):
                self.assertEqual(row['calls'],1);self.assertEqual(row['record']['cause'],'provider_bound')
                self.assertIsNone(row['record']['provider']);self.assertEqual(row['escapes'],0)
                if row['kind']!='escaped':self.assertEqual(row['reflections'],0)

    def test_exact_control_record_and_all_public_payload_fields_survive_one_to_three_pairs(self):
        capture=self.capture();source=inert_control_executor();sha=hashlib.sha256(source.encode('ascii')).hexdigest()
        for pairs in (1,2,3):
            with self.subTest(pairs=pairs):
                chain=self.chain(capture['record'],source,pairs)
                reference='functions.exec' if pairs==1 else 'functions.exec/controlled_cell'
                receipt=self.js("console.log(JSON.stringify(gate2InertReceive(input.chain,input.sha,input.reference)));",dict(chain=chain,sha=sha,reference=reference))
                self.assertEqual(receipt['record_size_bytes'],len(capture['text']))
                self.assertEqual(receipt['record_sha256'],hashlib.sha256(capture['text'].encode('ascii')).hexdigest())
                canonical=json.dumps(chain,sort_keys=True,separators=(',',':'),ensure_ascii=True)
                self.assertEqual(receipt['executor_chain_sha256'],hashlib.sha256(canonical.encode('ascii')).hexdigest())
                self.assertNotIn('retention_complete',receipt)

    def test_control_profile_source_wait_tail_and_inner_mutations_refuse(self):
        import copy
        capture=self.capture();source=inert_control_executor();sha=hashlib.sha256(source.encode('ascii')).hexdigest();base=self.chain(capture['record'],source,3);cases=[]
        def add(name,change,chain=None):
            value=copy.deepcopy(base if chain is None else chain);change(value);cases.append(dict(name=name,chain=value,sha=sha))
        add('four_pairs',lambda x:None,self.chain(capture['record'],source,4))
        add('wait_profile',lambda x:x[1]['call'].update(arguments=json.dumps(dict(cell_id='controlled_cell',max_tokens=100000,yield_time_ms=1),sort_keys=True,separators=(',',':'))))
        add('wait_object',lambda x:x[1]['call'].update(arguments={}))
        add('wait_over',lambda x:x[1]['call'].update(arguments=' '*257))
        add('wrong_cell',lambda x:x[1]['call'].update(arguments=x[1]['call']['arguments'].replace('controlled_cell','other')))
        add('source_lf',lambda x:x[0]['call'].update(input=source[:-1]))
        add('missing_tail',lambda x:x.pop())
        add('wrong_id',lambda x:x[1]['result'].update(call_id='wrong'))
        add('embedded_string_body',lambda x:x[-1]['result'].update(output='Script completed\nWall time 0.0 seconds\nOutput:\n'+capture['text']))
        for name,change in [('failed_provider',lambda r:r['provider'].update(isError=True)),('changed_args',lambda r:r['arguments'].update(timeout_ms=1)),('extra_claim',lambda r:r.update(physical_acceptance=False)),('different_result',lambda r:r['provider']['content'][0].update(text='different'))]:
            r=copy.deepcopy(capture['record']);change(r);add(name,lambda x:None,self.chain(r,source,3))
        cases.append(dict(name='wrong_source_sha',chain=base,sha='0'*64))
        causes=self.js("let rows=input.map(x=>{let cause=null;try{gate2InertReceive(x.chain,x.sha,'functions.exec/controlled_cell');}catch(e){cause=e.message;}return {name:x.name,cause};});console.log(JSON.stringify(rows));",cases)
        self.assertTrue(all(row['cause'] for row in causes),causes)

    def test_client_chain_and_document_prebounds_are_stricter_than_generic_receiver(self):
        capture=self.capture();source=inert_control_executor();chain=self.chain(capture['record'],source,3)
        result=self.js("""let chain=input.chain;for(let row of chain){row.call._meta.pad='';row.result._meta.pad='';}let room=131072-gate2InertBound(chain,131072).length;let slots=chain.flatMap(row=>[row.call._meta,row.result._meta]);for(let [i,slot] of slots.entries()){let n=Math.floor(room/(slots.length-i));slot.pad='x'.repeat(n);room-=n;}
let exact=gate2InertReceive(chain,input.sha,'functions.exec/controlled_cell'),width=gate2InertBound(chain,131072).length;slots[0].pad+='x';let over=null;try{gate2InertReceive(chain,input.sha,'functions.exec/controlled_cell');}catch(e){over=e.message;}
let max=gate2InertBound({pad:'x'.repeat(32757)},32767)+String.fromCharCode(10),docOver=null;let docChain=input.docChain;docChain.at(-1).result.output[1].text='x'.repeat(32769);try{gate2InertReceive(docChain,input.sha,'functions.exec/controlled_cell');}catch(e){docOver=e.message;}
console.log(JSON.stringify({width,exact,over,maxWidth:max.length,docOver}));""",dict(chain=chain,docChain=self.chain(capture['record'],source,3),sha=hashlib.sha256(source.encode('ascii')).hexdigest()))
        self.assertEqual(result['width'],131072);self.assertIsNotNone(result['over'])
        self.assertEqual(result['maxWidth'],32768);self.assertEqual(result['docOver'],'inert_document_bound')


class ResumeNodeCaller(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import shutil,subprocess
        executable=shutil.which('node') or shutil.which('node.exe')
        if executable is None:raise AssertionError('The CI-pinned Node runtime is required')
        version=subprocess.run([executable,'--version'],capture_output=True,check=True).stdout.decode().strip()
        print('CONTROLLED_NODE_RUNTIME',executable,version)

    def node(self, code, action='normal', output='{}\n', polls=(), **extra):
        import shutil,subprocess
        executable=shutil.which('node') or shutil.which('node.exe')
        self.assertIsNotNone(executable,'The CI-pinned Node runtime is required for controlled JS tests')
        if extra.get('inert_control_only') is True:
            self.assertIs(extra.get('code_generation_disabled'),True,'inert_control_only requires code_generation_disabled=True')
            value=dict(extra,code=code)
            result=subprocess.run([executable,'--experimental-vm-modules','--no-warnings','-e',INERT_HARNESS+'\n'+NODE_HARNESS],input=json.dumps(value).encode(),capture_output=True,check=False)
            self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
            return json.loads(result.stdout)
        import base64
        m=subject();sources=[(m.CODE[1],Path(m.REPO_WIN/m.CODE[1]).read_bytes()),(m.OPERATOR,Path(m.__file__).read_bytes())] if os.name=='nt' else [(m.CODE[1],Path(__file__).parents[1].joinpath(m.CODE[1]).read_bytes()),(m.OPERATOR,Path(m.__file__).read_bytes())]
        if extra.get('root_flow'):
            extra.setdefault('root_source',ROOT_ENCODER+'\n'+ROOT_SHA256+'\n'+ROOT_ORCHESTRATOR)
            extra.setdefault('finalizer',self.writer_code(expected_initial_sha256=hashlib.sha256(code.encode('ascii')).hexdigest()))
            extra.setdefault('output_profile',{'max_output_tokens':100000,'max_record_bytes':65536})
            from tests.test_accepted_policy_fixture_compiler_gate2_resume_caller_v1 import CD_FACTORY_SOURCE
            extra.setdefault('expected',{'code_commit':hashlib.sha1(b'controlled-current-review').hexdigest(),'core_sha256':hashlib.sha256(code.encode('ascii')).hexdigest(),'factory_sha256':hashlib.sha256(CD_FACTORY_SOURCE.encode('ascii')).hexdigest()})
        for key in ('poll','finalizer'):
            if key in extra:extra[key]=extra[key].replace('__G2_INITIAL_SHA256__',hashlib.sha256(code.encode('ascii')).hexdigest()).replace('__G2_ACTUAL_INITIAL_CODE__',json.dumps(code))
        value=dict({'sources':[[str(m.REPO_WIN.as_posix()+'/'+name),base64.b64encode(raw).decode()] for name,raw in sources],'code':code,'poll':'await gate2Resume.poll();','action':action,'output':output,'polls':list(polls)},**extra)
        result=subprocess.run([executable,'--experimental-vm-modules','--no-warnings','-e',NODE_HARNESS],input=json.dumps(value).encode(),capture_output=True,check=False)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
        return json.loads(result.stdout)

    def test_inert_control_same_source_isolated_before_operational_preparation(self):
        with patch(__name__+'.subject',side_effect=AssertionError('operational preparation forbidden')):
            value=self.node(INERT_CONTROL_SOURCE,inert_control_only=True,code_generation_disabled=True,root_flow=True,polls=('normal',))
        self.assertIsNone(value['error'])
        self.assertEqual(value['writes'],[INERT_CONTROL_EXPECTED])
        self.assertEqual(value['inert']['imports'],['node:crypto','node:zlib'])
        self.assertEqual(value['inert']['clock_reads'],2)
        self.assertEqual(value['inert']['effects'],dict(state_reads=0,state_writes=0,files=0,sources=0,children=0,timers=0))
        self.assertTrue(value['inert']['state_descriptor_unchanged'])
        wrapper='function(gate2Resume,nodeRepl){return gate2Resume.value===1&&nodeRepl.write(gate2Resume)===2;}'
        self.assertEqual(INERT_CONTROL_SOURCE.count('gate2Resume'),4)
        self.assertNotIn('gate2Resume',INERT_CONTROL_SOURCE.replace(wrapper,'').replace("'function(gate2Resume,nodeRepl){'",''))
        self.assertNotIn('globalThis',INERT_CONTROL_SOURCE)
        self.assertNotIn('hasOwn',INERT_CONTROL_SOURCE)
        self.assertNotIn('Reflect',INERT_CONTROL_SOURCE)

    def test_inert_control_requires_explicit_disabled_generation_before_preparation(self):
        with patch(__name__+'.subject',side_effect=AssertionError('operational preparation forbidden')):
            for flag in (None,False,1):
                with self.subTest(flag=flag),self.assertRaisesRegex(AssertionError,'code_generation_disabled'):
                    self.node(INERT_CONTROL_SOURCE,inert_control_only=True,code_generation_disabled=flag)

    def test_inert_control_fixed_faults_refuse_without_emission_or_operational_effects(self):
        for name,code,options,error in inert_control_cases():
            with self.subTest(name=name):
                value=self.node(code,inert_control_only=True,code_generation_disabled=True,**options)
                self.assertEqual(value['error'],error)
                self.assertFalse(value['writes'])
                self.assertEqual(value['inert']['effects'],dict(state_reads=0,state_writes=0,files=0,sources=0,children=0,timers=0))
        source=INERT_CONTROL_SOURCE.replace('const intrinsic=Function.prototype.toString;',"Object.defineProperty(wrapper,'toString',{value:()=>{throw Error('own_toString_forbidden');}});const intrinsic=Function.prototype.toString;")
        value=self.node(source,inert_control_only=True,code_generation_disabled=True)
        self.assertEqual(value['writes'],[INERT_CONTROL_EXPECTED])

    def test_inert_control_harness_state_and_effect_canaries_are_observable(self):
        for code,key in [("void globalThis.gate2Resume;",'state_reads'),("globalThis.gate2Resume=1;",'state_writes'),("setTimeout(()=>{},1);",'timers'),("await import('node:fs');",'files'),("await import('node:child_process');",'children'),("await import('controlled:source');",'sources')]:
            with self.subTest(key=key):
                value=self.node(code,inert_control_only=True,code_generation_disabled=True)
                self.assertIsNotNone(value['error'])
                self.assertEqual(value['inert']['effects'][key],1)
                self.assertFalse(value['writes'])

    def source_rows(self):
        m=subject();root=Path(__file__).parents[1]
        return [[m.REPO_WIN.as_posix()+'/'+name,m.source_descriptor_v1(root.joinpath(name).read_bytes())] for name in (m.CODE[1],m.OPERATOR)]

    def code(self,writer=''):
        writer_expr=json.dumps(NODE_WRITER_HEAD)+'+g2py+'+json.dumps(NODE_WRITER_TAIL) if writer==CURRENT_WRITER_SOURCE else json.dumps(writer)
        return NODE_CONTROLLER.replace('__VALIDATORS__',NODE_VALIDATORS).replace('__ROOT__',json.dumps(subject().ROOT.as_posix())).replace('__COMMON__',json.dumps(NODE_SHARED_PYTHON)).replace('__SETUP_HEAD__',json.dumps(NODE_SETUP_HEAD)).replace('__SETUP_TAIL__',json.dumps(NODE_SETUP_TAIL)).replace('__COMMIT__',json.dumps(hashlib.sha1(b'controlled-current-review').hexdigest())).replace(
            '__APPROVAL__',json.dumps('https://github.com/lordcoudy/VAST/pull/9#issuecomment-1234567890')).replace('__WRITER_EXPR__',writer_expr).replace(
            '__FIELDS__',json.dumps(NODE_FIELDS)).replace('__PIPE_FIELDS__',json.dumps(NODE_PIPE_FIELDS)).replace('__SOURCES__',json.dumps(self.source_rows(),sort_keys=True,separators=(',',':')))

    def success_output(self,anchor=1755772592209100):
        m=subject();desc=lambda name:{'path':m.AUX.as_posix()+'/'+name,'size_bytes':4096,'sha256':hashlib.sha256(name.encode()).hexdigest()}
        meter={'native_pid':4194304,'fresh_interval_N':2650112,'native_bytes':1048576,'outside_bytes':524288,
            'active_f2_debit':7995392,'outstanding_tail_bytes':45312,'historical_closing_meter_available':False,
            'physical_acceptance':False,'final_measurement':{'c_free_bytes':99685629952,'ext4_used_bytes':313124622336,
            'project_free_bytes':100000000000,'fragment_bytes':4096,'backing_device':2112}}
        return formatter()(result={'code_commit':hashlib.sha1(b'controlled-current-review').hexdigest(),
            'packet':{'path':m.ROOT.as_posix()+'/gate2.packet.original.json','size_bytes':32768,'sha256':hashlib.sha256(b'packet').hexdigest()},
            'authority':desc('operator.authority.original.json'),'events':desc('resume.events.original.json'),'final_meter':meter,
            'final_return':[4294967295,0,True,True,4096,hashlib.sha256(b'final-return').hexdigest(),0,hashlib.sha256(b'').hexdigest()],
            'windows_start_ns':anchor,'absolute_deadline_ns':anchor+150000000000,'c_or_d_invoked':False}).decode()+'\n'

    def failure_output(self,unicode=False):
        import base64
        rows=[{'stdout_sha256':hashlib.sha256(('stdout'+str(i)).encode()).hexdigest(),
               'stderr_sha256':hashlib.sha256(('stderr'+str(i)).encode()).hexdigest(),
               'stdout_prefix_base64':base64.b64encode(hashlib.sha512(('prefix'+str(i)).encode()).digest()[:48]).decode(),
               'linux_child_closure':'unknown_'+hashlib.sha256(('closure'+str(i)).encode()).hexdigest()[:56]} for i in range(4)]
        candidates=[]
        for n in range(1,65):
            facts={'failure_facts':rows,'causes':[hashlib.sha256(('cause'+str(i)).encode()).hexdigest()[:n] for i in range(4)],
              'completion_record':{'write_proof':{'returncode':None,'eof_stdout':True,'eof_stderr':True,'close_completed':False,'write_extent_unknown':True}}}
            if unicode:facts['failure_facts'][0]['linux_child_closure']='\U0001f4a5'*n
            candidates.append(formatter()(error=subject().ResumeRefusal(('\U0001f4a5' if unicode else 'observed_failure_')*n,facts)).decode()+'\n')
        return max(candidates,key=len)

    def finish_code(self,writer='fixed'):
        return self.writer_code(writer)+"\nawait gate2Resume.finish(gate2Resume.canon({call:{tool:'mcp__node_repl__js',timeout_ms:32000,codes:[__G2_ACTUAL_INITIAL_CODE__]},frames:[{content:[{type:'text',text:gate2Resume.last_setup.text}],isError:false}]}));"

    def writer_code(self,writer=CURRENT_WRITER_SOURCE,*,expected_initial_sha256=None,body_digest=None):
        import base64,zlib
        from tests.test_accepted_policy_fixture_compiler_gate2_resume_caller_v1 import CD_FACTORY_SOURCE
        expression=json.dumps(NODE_WRITER_HEAD)+'+g2.python_common+'+json.dumps(NODE_WRITER_TAIL) if writer==CURRENT_WRITER_SOURCE else json.dumps(writer)
        factory="\nvar cdLiteral="+json.dumps(CD_FACTORY_SOURCE)+";if(g2.now()>=g2.end_ms||g2.hash(cdLiteral)!=="+json.dumps(hashlib.sha256(CD_FACTORY_SOURCE.encode('ascii')).hexdigest())+")throw Error('cd_factory_binding');g2.cd_factory_sha256=g2.hash(cdLiteral);eval(cdLiteral);if(g2.now()>=g2.end_ms)throw Error('cd_factory_late');"
        body="var {spawn:g2s}=await import('node:child_process'),{brotliDecompressSync:g2d}=await import('node:zlib');if(g2.now()>=g2.end_ms)throw Error('writer_install');g2.writer="+expression+';\n'+NODE_WRITER_VALIDATORS+NODE_FINISH_BODY+factory
        raw=body.encode('ascii');compressed=base64.b64encode(zlib.compress(raw,9)).decode('ascii')
        digest=body_digest or hashlib.sha256(raw).hexdigest();initial=expected_initial_sha256 or '__G2_INITIAL_SHA256__'
        return "var g2=globalThis.gate2Resume;if(!g2||g2.writer_installed||g2.now()>=g2.end_ms)throw Error('writer_install');g2.writer_installed=true;var {inflateSync:g2inflate}=await import('node:zlib');if(g2.now()>=g2.end_ms)throw Error('writer_install');var g2final=g2inflate(Buffer.from("+json.dumps(compressed)+",'base64'),{maxOutputLength:"+str(len(raw))+"});if(g2.now()>=g2.end_ms)throw Error('writer_install');if(g2final.length!=="+str(len(raw))+"||g2.hash(g2final)!=="+json.dumps(digest)+")throw Error('finalizer_binding');g2.expected_initial_sha256="+json.dumps(initial)+";g2.finalizer_sha256="+json.dumps(digest)+";await eval('(async()=>{'+g2final.toString('latin1')+'})()');if(g2.now()>=g2.end_ms)throw Error('writer_install');"

    def facts(self,text):
        value=json.loads(text.split('\n',1)[0])
        if isinstance(value,dict):return value
        self.assertIn(value[0],(0,1,2))
        if value[0]==0:
            self.assertIn(len(value),(3,6))
            return dict(pending=True,pid=value[-2],returncode=value[-1],clock=value[1:4] if len(value)==6 else None)
        self.assertEqual(len(value),len(NODE_FIELDS)+1)
        facts=dict(zip(NODE_FIELDS,value[1:]))
        facts['pipes']=[dict(zip(NODE_PIPE_FIELDS,row)) for row in facts['pipes']]
        if value[0]==2:
            facts.update(role='writer',original_end_ms=facts['clock'][2])
        return facts

    def decode(self,text,refuses=False,reason=None):
        import base64,shutil,subprocess
        value={'text':text,'fields':NODE_FIELDS,'pipe_fields':NODE_PIPE_FIELDS}
        executable=shutil.which('node') or shutil.which('node.exe')
        result=subprocess.run([executable,'-e',NODE_DECODE,json.dumps(value)],capture_output=True)
        if refuses:
            self.assertNotEqual(result.returncode,0)
            if reason:self.assertIn(reason,result.stderr.decode(errors='replace'))
            return
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
        return [base64.b64decode(s) for s in json.loads(result.stdout)]

    def carrier(self,code):
        import base64,zlib
        prefix="if(Object.hasOwn(globalThis,'gate2Resume'))throw Error('state_exists');\nvar g2p=globalThis.performance;if(!g2p||typeof g2p.now!=='function')throw Error('monotonic_unavailable');\n"
        clock="var g2t=g2p.now();if(!Number.isFinite(g2t)||g2t<0||g2t>Number.MAX_SAFE_INTEGER-150000)throw Error('original_clock');\n"
        self.assertTrue(code.startswith(prefix+clock))
        body=code[len(prefix+clock):]
        expanded='(async()=>{'+body+'})()'
        # Produce the fixed stdlib Brotli carrier in Node; this never runs a child program.
        import shutil,subprocess
        executable=shutil.which('node') or shutil.which('node.exe')
        script="const z=require('node:zlib'),b=require('node:fs').readFileSync(0),c=z.brotliCompressSync(b,{params:{[z.constants.BROTLI_PARAM_QUALITY]:11}});if(!z.brotliDecompressSync(c).equals(b))throw Error('roundtrip');console.log(c.toString('base64'));"
        result=subprocess.run([executable,'-e',script],input=expanded.encode('ascii'),capture_output=True,check=True)
        compressed=result.stdout.decode('ascii').strip()
        return prefix+clock+"var {brotliDecompressSync:g2z}=await import('node:zlib');await eval(g2z(Buffer.from("+json.dumps(compressed)+",'base64')).toString('utf8'));"

    def test_restricted_harness_denies_unchanged_initial_carrier_before_source_or_child(self):
        value=self.node(self.carrier(self.code()),action='pending',code_generation_disabled=True)
        self.assertEqual(value['error'],'Code generation from strings disallowed for this context')
        self.assertEqual(value['error_name'],'EvalError')
        self.assertEqual(value['spawned'],0)
        self.assertFalse(value['sourceCalls'])
        self.assertFalse(value['writes'])

    def test_restricted_harness_denies_unchanged_deferred_writer_after_static_setup(self):
        value=self.node(self.code(),output=self.success_output(),polls=['pending'],
                        poll=self.writer_code(),code_generation_disabled=True)
        self.assertEqual(value['error'],'Code generation from strings disallowed for this context')
        self.assertEqual(value['error_name'],'EvalError')
        self.assertEqual(value['spawned'],1)
        self.assertEqual(len(value['writes']),1)
        self.assertTrue(self.facts(value['writes'][0])['completed'])
        self.assertEqual(value['sourceClose'],2)

    def test_restricted_harness_static_initial_keeps_clock_and_owned_closure(self):
        value=self.node(self.code(),output=self.success_output(),code_generation_disabled=True)
        self.assertIsNone(value['error'])
        self.assertEqual(value['spawned'],1)
        self.assertEqual(value['sourceClose'],2)
        self.assertEqual(value['killed'],0)
        facts=self.facts(value['writes'][0])
        self.assertEqual(facts['clock'],[10,140010,150010])
        self.assertTrue(facts['completed'])
        self.assertFalse(facts['unknown_closure'])
        self.assertTrue(facts['stdin_finished'])
        self.assertTrue(facts['stdin_closed'])

    def test_source_read_then_close_preserves_first_secondary_and_confirmed_prefix(self):
        import base64
        value=self.node(self.code(),source_short=True,source_readfail=True,source_close=True)
        self.assertEqual(value['spawned'],0);f=self.facts(value['writes'][0]);known=f['source_facts'][0]
        self.assertEqual(known['cause'],'source_read_failed');self.assertEqual(known['secondary'],['source_close'])
        self.assertEqual(known['read_bytes'],7);self.assertFalse(known['close_completed']);self.assertTrue(known['unknown_closure'])
        raw=Path(__file__).parents[1].joinpath(subject().CODE[1]).read_bytes()[:7]
        self.assertEqual(known['read_sha256'],hashlib.sha256(raw).hexdigest())

    def test_thin_setup_authenticates_held_bytes_before_exec_and_keeps_original_mapped_clock(self):
        import sys
        anchor=1755772592209100
        component=b"raise AssertionError('component_must_not_execute')\n"
        source=b"def main(c,a,*,_original_start_ns):\n assert c=='commit' and a=='approval'\n assert _original_start_ns==1755771592209100\n return 0\n"
        descriptors=[subject().source_descriptor_v1(b) for b in (component,source)]
        ack={'remaining_ms':149000,'selected_base64':'','sha256':hashlib.sha256(b'').hexdigest(),'size_bytes':0}
        for kind in ('normal','tamper','truncated','trailing','wronggit','late'):
            d=[dict(v) for v in descriptors];wire=subject().canonical(ack)+b'\n'+component+source;writes=[];times=[anchor]
            if kind=='tamper':wire=wire[:-1]+b'x'
            if kind=='truncated':wire=wire[:-1]
            if kind=='trailing':wire+=b'x'
            if kind=='wronggit':d[1]['git_blob']='0'*40
            def now():
                times.append(anchor+(140000000000 if kind=='late' and len(times)>2 else 0));return times[-1]
            def write(fd,b):writes.append((fd,b));return len(b)
            with self.subTest(kind=kind),patch.object(sys,'argv',['fixed','commit','approval',subject().canonical(d).decode()]),\
                 patch.object(sys,'stdin',SimpleNamespace(buffer=io.BytesIO(wire))),patch.object(os,'write',side_effect=write),\
                 patch.object(os,'close'),patch('time.monotonic_ns',side_effect=now),patch.object(os,'name','nt'),\
                 patch('shutil.disk_usage',return_value=SimpleNamespace(free=100000000000)):
                scope={}
                with self.assertRaises(SystemExit) as result:exec(NODE_WINDOWS_PROGRAM,scope)
            if kind=='normal':self.assertEqual(result.exception.code,0);self.assertEqual(scope['buffers'],[component,source])
            else:self.assertEqual(result.exception.code,1)
            if kind=='late':self.assertTrue(all(fd==3 for fd,_ in writes))
            if kind in ('tamper','wronggit','truncated','trailing'):self.assertNotIn('op',scope)

    def test_held_source_positive_shortreads_one_fd_and_stdin_contains_the_exact_authenticated_buffer(self):
        import base64
        value=self.node(self.code(),source_short=True)
        self.assertIsNone(value['error']);self.assertEqual(value['spawned'],1)
        self.assertEqual(len(value['sourceCalls']),2);self.assertEqual(value['sourceClose'],2)
        self.assertGreater(value['sourceRead'],2)
        wire=base64.b64decode(value['setup_ack']);line,held=wire.split(b'\n',1)
        self.assertEqual(json.loads(line)['remaining_ms'],150000);comp=Path(__file__).parents[1].joinpath(subject().CODE[1]).read_bytes();op=Path(subject().__file__).read_bytes();self.assertEqual(held,comp+op)
        d=json.loads(value['calls'][0]['args'][7]);self.assertEqual(d,[subject().source_descriptor_v1(comp),subject().source_descriptor_v1(op)])

    def test_held_source_tamper_or_close_error_prevents_any_child(self):
        for fault in ('source_tamper','source_close','source_race','source_special'):
            with self.subTest(fault=fault):
                value=self.node(self.code(),**{fault:True})
                self.assertEqual(value['spawned'],0)
                self.assertTrue(value['error'] or value['writes'])

    def test_node_owns_one_exact_python_child_and_closes_each_channel(self):
        observed=self.node(self.code())
        self.assertEqual(observed['spawned'],1)
        self.assertEqual(observed['killed'],0)
        call=observed['calls'][0]
        self.assertEqual(call['file'],'C:/Python314/python.exe')
        self.assertEqual(call['args'][:4],['-I','-S','-B','-c'])
        self.assertEqual(call['args'][4],NODE_WINDOWS_PROGRAM)
        self.assertEqual(call['options']['cwd'],subject().REPO_WIN.as_posix())
        header,raw=observed['writes'][0].split('\n',1)
        facts=self.facts(header)
        self.assertEqual((facts['pid'],facts['returncode']),(4321,0))
        self.assertTrue(facts['completed']);self.assertFalse(facts['unknown_closure'])
        self.assertEqual(self.decode(observed['writes'][0]),[b'{}\n',b'',b'1755772592209100\n'])
        import base64
        wire=base64.b64decode(observed['setup_ack']);line,held=wire.split(b'\n',1);self.assertEqual(json.loads(line),{'remaining_ms':150000,'selected_base64':'','sha256':hashlib.sha256(b'').hexdigest(),'size_bytes':0});self.assertEqual(held,Path(__file__).parents[1].joinpath(subject().CODE[1]).read_bytes()+Path(subject().__file__).read_bytes())

    def test_node_sentinel_stops_before_a_second_read_and_preserves_observed_hash(self):
        value=self.node(self.code(),action='overflow')
        facts,raw=value['writes'][0].split('\n',1);facts=self.facts(facts)
        self.assertEqual(value['reads'][0],[2049])
        observed=self.decode(value['writes'][0])[0]
        self.assertEqual(observed,b'x'*2049)
        self.assertEqual(facts['pipes'][0]['sha256'],hashlib.sha256(observed).hexdigest())
        self.assertTrue(facts['pipes'][0]['remainder_unknown']);self.assertFalse(facts['pipes'][0]['eof'])
        self.assertEqual(facts['returncode'],0);self.assertTrue(facts['unknown_closure']);self.assertFalse(facts['completed'])
        self.assertEqual(value['killed'],0)

    def test_node_exit_is_distinct_from_eof_and_late_completion_never_resets_clock(self):
        for action in ('late','exitonly','closeonly','readerror','error'):
            with self.subTest(action=action):
                value=self.node(self.code(),action=action,polls=['pending']*5 if action=='exitonly' else ())
                facts=self.facts(value['writes'][-1])
                self.assertFalse(facts['completed']);self.assertEqual(value['spawned'],1);self.assertEqual(value['killed'],0)
                if action!='late':self.assertTrue(facts['unknown_closure'])
        value=self.node(self.code(),import_delay=140001)
        self.assertEqual(value['spawned'],0)
        facts=self.facts(value['writes'][0]);self.assertFalse(facts['completed'])

    def test_node_same_state_six_calls_original_remaining_and_no_respawn(self):
        value=self.node(self.code(),action='pending',polls=['pending']*5)
        self.assertEqual(value['spawned'],1);self.assertEqual(value['killed'],0)
        self.assertEqual(len(value['writes']),6)
        final=self.facts(value['writes'][-1])
        self.assertEqual(value['clock'],140010);self.assertFalse(final['completed']);self.assertTrue(final['unknown_closure'])
        overflow=self.node(self.code(),action='pending',polls=['pending']*6)
        self.assertEqual(overflow['error'],'poll_state');self.assertEqual(overflow['spawned'],1)
        absent=self.node('await gate2Resume.poll();',action='pending')
        self.assertIn('gate2Resume',absent['error']);self.assertEqual(absent['spawned'],0)
        regression=self.node(self.code(),action='regress')
        self.assertEqual(regression['error'],'clock_regression');self.assertEqual(regression['spawned'],1)

    def test_node_complete_six_call_collection_geometry(self):
        from tests.test_accepted_policy_fixture_compiler_gate2_resume_caller_v1 import WRITER_SOURCE
        m=subject();raw_code=self.code(WRITER_SOURCE);code=self.carrier(raw_code)
        calls=[{'code':body,'timeout_ms':32000} for body in [code]+['await gate2Resume.poll();']*5]
        call={'tool':'mcp__node_repl__js','timeout_ms':32000,'codes':[item['code'] for item in calls]}
        desc=lambda name:{'path':str(m.AUX/name),'size_bytes':8192,'sha256':hashlib.sha256(name.encode()).hexdigest()}
        final={'native_pid':4194304,'fresh_interval_N':2650112,'native_bytes':1048576,'outside_bytes':524288,
            'active_f2_debit':7995392,'outstanding_tail_bytes':37120,'historical_closing_meter_available':False,
            'physical_acceptance':False,'final_measurement':{'c_free_bytes':99685629952,'ext4_used_bytes':313124622336,
            'project_free_bytes':100000000000,'fragment_bytes':4096,'backing_device':2112}}
        success={'code_commit':hashlib.sha1(b'actual-controlled-review-entropy').hexdigest(),'packet':{'path':str(m.ROOT/'gate2.packet.original.json'),'size_bytes':32768,'sha256':hashlib.sha256(b'controlled-packet').hexdigest()},
            'authority':desc('operator.authority.original.json'),'events':desc('resume.events.original.json'),
            'final_meter':final,'final_return':[4294967295,0,True,True,4096,hashlib.sha256(b'actual-final-return').hexdigest(),0,hashlib.sha256(b'').hexdigest()],
            'windows_start_ns':1746145610106100,'absolute_deadline_ns':1746295610106100,'c_or_d_invoked':False}
        for output in (formatter()(result=success).decode()+'\n',
                       formatter()(error=m.ResumeRefusal('💥'*64,{'returncode':None,'eof_stdout':True,
                         'eof_stderr':True,'causes':['💥'*64]*4,'padding':'x'*40000})).decode()+'\n'):
            observed=self.node(code,action='pending',polls=['pending']*4+['normal'],output=output)
            frames=[{'content':[{'type':'text','text':s}],'isError':False} for s in observed['writes']]
            self.assertEqual(len(frames),6)
            print('CONTROLLED_NODE_QUOTE',len(raw_code.encode()),len(code.encode()),len(WRITER_SOURCE.encode()),len(output.encode()),len(m.canonical({'call':call,'frames':frames})))
            full=m.outer_collection_v1(call,frames)
            self.assertEqual(json.loads(full),{'call':call,'frames':frames})
            self.assertEqual([{'code':body,'timeout_ms':call['timeout_ms']} for body in call['codes']],calls)
            self.assertLessEqual(len(full),12288)
            print('CONTROLLED_NODE_GEOMETRY',len(raw_code.encode()),len(code.encode()),len(WRITER_SOURCE.encode()),len(output.encode()),len(full))

    def test_fixed_node_carrier_is_byte_exact_and_decode_uses_original_clock(self):
        code=self.carrier(self.code())
        value=self.node(code)
        self.assertEqual(value['spawned'],1)
        facts=self.facts(value['writes'][0]);self.assertEqual(facts['clock'],[10,140010,150010])
        for delay in ('decode_delay','import_delay'):
            value=self.node(code,**{delay:140001})
            self.assertEqual(value['spawned'],0)
            facts=self.facts(value['writes'][0]);self.assertFalse(facts['completed'])

    def test_node_duplicate_initial_call_cannot_replace_held_child_or_clock(self):
        code=self.code()
        value=self.node(code,action='pending',polls=['pending'],poll=code)
        self.assertEqual(value['spawned'],1)
        self.assertEqual(value['error'],'state_exists')

    def test_node_error_then_eof_keeps_unknown_prefix_and_expired_poll_never_waits(self):
        value=self.node(self.code(),action='errorend')
        facts=self.facts(value['writes'][0])
        self.assertEqual(facts['returncode'],0);self.assertTrue(facts['pipes'][0]['eof'])
        self.assertTrue(facts['pipes'][0]['error']);self.assertTrue(facts['pipes'][0]['remainder_unknown'])
        self.assertTrue(facts['unknown_closure']);self.assertFalse(facts['completed'])

    def test_node_expired_poll_never_waits_or_emits_a_new_capture(self):
        late=self.node(self.code(),action='pending',polls=['afterend'])
        self.assertEqual(late['error'],'original_deadline');self.assertEqual(len(late['writes']),1)

    def test_node_writer_uses_same_original_end_and_distinct_actual_terminal(self):
        import base64
        code=self.carrier(self.code('fixed reviewed writer'))
        value=self.node(code,action='normal',polls=['writernormal'],poll=self.finish_code('fixed reviewed writer'))
        self.assertIsNone(value['error'])
        self.assertEqual(value['spawned'],2);self.assertEqual(value['killed'],0)
        self.assertEqual(value['calls'][1]['args'][4],'fixed reviewed writer')
        self.assertEqual(value['calls'][0]['args'][4],NODE_WINDOWS_PROGRAM)
        wire=base64.b64decode(value['writer_ack']);line,held=wire.split(b'\n',1);ack=json.loads(line)
        self.assertEqual(line.decode(),json.dumps(ack,sort_keys=True,separators=(',',':')))
        self.assertEqual(held,Path(__file__).parents[1].joinpath(subject().CODE[1]).read_bytes()+Path(subject().__file__).read_bytes())
        selected=base64.b64decode(ack['selected_base64']);self.assertEqual(json.loads(selected)['frames'][0]['content'][0]['text'],value['writes'][0])
        self.assertEqual(ack['remaining_ms'],150000);self.assertEqual(ack['size_bytes'],len(selected));self.assertEqual(ack['sha256'],hashlib.sha256(selected).hexdigest())
        facts,encoded=value['writes'][-1].split('\n',1);facts=self.facts(facts)
        self.assertEqual((facts['role'],facts['pid'],facts['returncode']),('writer',5678,0))
        self.assertTrue(facts['completed']);self.assertFalse(facts['unknown_closure'])
        self.assertEqual(facts['original_end_ms'],150010);self.assertLess(facts['terminal_observed_ms'],150010)
        self.assertTrue(facts['stdin_finished']);self.assertTrue(facts['stdin_closed'])
        self.assertNotIn('role',json.loads(value['writes'][0].split('\n',1)[0]))

    def test_known_setup_child_is_retained_when_tracking_throws_and_stdin_closes_once(self):
        value=self.node(self.carrier(self.code()),action='pending',track_throw=1)
        self.assertIsNone(value['error']);self.assertEqual(value['spawned'],1)
        facts=self.facts(value['writes'][-1])
        self.assertEqual(facts['pid'],4321);self.assertIn('controlled_track',','.join(facts['causes']))
        self.assertTrue(facts['unknown_closure']);self.assertFalse(facts['completed'])
        self.assertEqual(value['setup_ack'],'');self.assertEqual(value['killed'],0)
        self.assertEqual(value['stdinEnds'],[1,0])
        value=self.node(self.carrier(self.code()),action='pending',track_throw=1,stdin_end_throw=1)
        facts=self.facts(value['writes'][-1]);self.assertEqual(facts['causes'],['controlled_track','stdin_close'])
        self.assertEqual(facts['pid'],4321);self.assertTrue(facts['stdin_extent_unknown']);self.assertEqual(value['stdinEnds'],[1,0])
        value=self.node(self.carrier(self.code()),action='pending',track_throw=1,stdin_async_error=1)
        facts=self.facts(value['writes'][-1]);self.assertEqual(facts['causes'],['controlled_track','stdin_error'])
        self.assertEqual(facts['pid'],4321);self.assertTrue(facts['stdin_extent_unknown']);self.assertEqual(value['stdinEnds'],[1,0])

    def test_known_writer_child_survives_tracking_failure_and_second_finish_is_denied(self):
        poll='if(!gate2Resume.writer_started){'+self.finish_code()+'}else await gate2Resume.finish("unused");'
        value=self.node(self.carrier(self.code()),output=self.success_output(),polls=['writernormal','pending'],poll=poll,track_throw=2)
        self.assertEqual(value['spawned'],2);self.assertEqual(value['error'],'writer_state')
        facts=self.facts(value['writes'][-1]);self.assertEqual(facts['pid'],5678)
        self.assertIn('controlled_track',','.join(facts['causes']));self.assertTrue(facts['unknown_closure'])
        self.assertFalse(facts['completed']);self.assertEqual(value['writer_ack'],'')
        self.assertEqual(value['stdinEnds'],[1,1])

    def test_tracking_fallback_owns_async_repeated_errors_from_only_its_fixed_emitters(self):
        code=self.carrier(self.code())
        for stage in (1,2):
            names=['child','stdin','stdout','stderr']+(['ready'] if stage==1 else [])
            for errors in ([name,name] for name in names):
                with self.subTest(stage=stage,errors=errors):
                    kwargs={'action':'pending'} if stage==1 else {'output':self.success_output(),'polls':['writernormal'],'poll':self.finish_code()}
                    value=self.node(code,track_throw=stage,fallback_errors=errors,**kwargs)
                    self.assertIsNone(value['error']);facts=self.facts(value['writes'][-1])
                    label='ready_error' if errors[0]=='ready' else errors[0]+'_error'
                    self.assertEqual(facts['causes'],['controlled_track',label])
                    self.assertEqual(facts['pid'],4321 if stage==1 else 5678)
                    self.assertTrue(facts['unknown_closure']);self.assertFalse(facts['completed'])
                    self.assertEqual(value['stdinEnds'],[1,0] if stage==1 else [1,1]);self.assertEqual(value['killed'],0)

    def test_tracking_fallback_skips_eof_when_owned_stdin_listener_is_unavailable(self):
        code=self.carrier(self.code())
        for stage in (1,2):
            for fault in ('absent','missing_on','throwing_on'):
                with self.subTest(stage=stage,fault=fault):
                    kwargs={'action':'pending'} if stage==1 else {'output':self.success_output(),'polls':['writernormal'],'poll':self.finish_code()}
                    value=self.node(code,track_throw=stage,stdin_listener_fault=fault,fallback_errors=['stdin'],**kwargs)
                    self.assertIsNone(value['error']);facts=self.facts(value['writes'][-1])
                    self.assertEqual(facts['pid'],4321 if stage==1 else 5678)
                    self.assertEqual(facts['causes'],['controlled_track','stdin_listener_failed'])
                    self.assertTrue(facts['unknown_closure']);self.assertTrue(facts['stdin_extent_unknown'])
                    self.assertFalse(facts['stdin_closed']);self.assertFalse(facts['stdin_finished']);self.assertFalse(facts['completed'])
                    self.assertEqual(value['stdinEnds'],[0,0] if stage==1 else [1,0])
                    self.assertEqual(value['inputErrorEvents'],0);self.assertEqual(value['killed'],0)

    def test_inner_lossless_encoding_keeps_u64_bytes_and_refuses_corrupt_or_large_decode(self):
        import base64,copy,shutil,subprocess
        output='{"exact":18446744073709551615,"unicode":"'+'\\ud83d\\ude00'*90+'"}\n'
        observed=self.node(self.carrier(self.code()),output=output)
        text=observed['writes'][0];facts=self.facts(text)
        self.assertEqual(facts['pipes'][0]['encoding'],'br64')
        self.assertEqual(self.decode(text)[0],output.encode('ascii'))
        header,body=text.split('\n',1);value=json.loads(header);rows_at=1+NODE_FIELDS.index('pipes')
        for key,replacement in (('encoding','unknown'),('sha256','0'*64),('bytes',2049),('chars',1)):
            bad=copy.deepcopy(value);bad[rows_at][0][NODE_PIPE_FIELDS.index(key)]=replacement
            self.decode(json.dumps(bad,separators=(',',':'))+'\n'+body,refuses=True)
        executable=shutil.which('node') or shutil.which('node.exe')
        packed=subprocess.run([executable,'-e',"console.log(require('node:zlib').brotliCompressSync(Buffer.alloc(65536)).toString('base64'));"],capture_output=True,check=True).stdout.decode().strip()
        bad=copy.deepcopy(value);first=bad[rows_at][0];old=first[NODE_PIPE_FIELDS.index('chars')]
        first[NODE_PIPE_FIELDS.index('chars')]=len(packed);first[NODE_PIPE_FIELDS.index('bytes')]=2049
        self.decode(json.dumps(bad,separators=(',',':'))+'\n'+packed+body[old:],refuses=True,reason='ERR_BUFFER_TOO_LARGE')

    def test_fd3_prefix_maps_earlier_start_and_never_authenticates_bad_or_late_ack(self):
        import sys
        anchor=1755772592209100
        for kind,ack in (('normal',b'149000\n'),('leading_zero',b'0149000\n'),('expired',b'10000\n'),('late',b'149000\n'),('write_close',b'149000\n')):
            writes=[];closes=[];calls=[];scope={};status=None
            def now():calls.append(1);return anchor+(140000000000 if kind=='late' and len(calls)>1 else 0)
            def write(fd,raw):
                if fd==3 and kind=='write_close':raise OSError('controlled ready')
                writes.append((fd,raw));return len(raw)
            def close(fd):
                closes.append(fd)
                if kind=='write_close':raise OSError('controlled close')
            with self.subTest(kind=kind),patch.object(os,'write',side_effect=write),patch.object(os,'close',side_effect=close),\
                 patch('time.monotonic_ns',side_effect=now),patch.object(sys,'stdin',SimpleNamespace(buffer=io.BytesIO(ack))):
                try:exec(NODE_WINDOWS_PREFIX+'\n_entered_project_auth=True\n',scope)
                except SystemExit as error:status=error.code
            self.assertEqual(closes,[3])
            if kind=='normal':
                self.assertIsNone(status);self.assertTrue(scope['_entered_project_auth'])
                self.assertEqual(scope['w0'],anchor-1000000000)
                self.assertEqual(writes,[(3,(str(anchor)+'\n').encode())])
            else:
                self.assertEqual(status,1);self.assertNotIn('_entered_project_auth',scope)
                if kind=='write_close':
                    value=json.loads(writes[-1][1]);self.assertEqual(writes[-1][0],1)
                    self.assertEqual(value['causes'],['bridge_ready_OSError','bridge_close_OSError'])
                    self.assertFalse(value['ready_close_completed']);self.assertTrue(value['ready_extent_unknown'])
                else:self.assertTrue(all(fd==3 for fd,_ in writes))

    def test_writer_return_is_only_bounded_by_a_later_same_runtime_clock(self):
        poll='if(!gate2Resume.writer_started){'+self.finish_code()+'}else gate2Resume.verifyReturn(__DELIVERED_WRITER_TEXT__);'
        value=self.node(self.carrier(self.code('fixed')),action='normal',polls=['writernormal','pending'],poll=poll)
        self.assertIsNone(value['error']);self.assertEqual(value['spawned'],2)
        self.assertEqual(json.loads(value['writes'][-1])[:5],[3,10,150010,False,True])
        late=self.node(self.carrier(self.code('fixed')),action='normal',polls=['writernormal','afterend'],poll=poll)
        self.assertEqual(late['error'],'writer_return_unknown');self.assertEqual(late['spawned'],2)

    def test_strict_setup_view_and_writer_proof_keep_retention_separate_from_acceptance(self):
        poll='if(!gate2Resume.writer_started){'+self.finish_code()+'}else gate2Resume.verifyReturn(__DELIVERED_WRITER_TEXT__);'
        for output,accepted in ((self.success_output(),True),('{}\n',False),
                (formatter()(error=subject().ResumeRefusal('controlled_failure',{'returncode':None,'eof_stdout':True})).decode()+'\n',False)):
            with self.subTest(accepted=accepted,output=output[:40]):
                value=self.node(self.carrier(self.code('fixed')),output=output,polls=['writernormal','pending'],poll=poll)
                self.assertIsNone(value['error']);proof=json.loads(value['writes'][-1]);self.assertEqual(proof[3:5],[accepted,True])
                self.assertEqual(value['spawned'],2)

    def test_actual_root_orchestrator_six_complete_frames_writer_and_causal_return(self):
        value=self.node(self.carrier(self.code()),root_flow=True,root_pending=5,output=self.success_output())
        self.assertIsNone(value['error']);root=value['root'];self.assertNotIn('cause',root)
        self.assertTrue(root['setup_success']);self.assertTrue(root['retention_complete']);self.assertFalse(root['physical_acceptance'])
        selected=root['setup']['selected'];self.assertLessEqual(len(selected.encode()),12288)
        raw=json.loads(selected);self.assertEqual(len(raw['frames']),6)
        self.assertEqual(raw['frames'],value['providerResults'][:6])
        self.assertEqual([{'code':c,'timeout_ms':raw['call']['timeout_ms']} for c in raw['call']['codes']],value['providerCalls'][:6])
        self.assertEqual(len(value['providerCalls']),8);self.assertEqual(value['spawned'],2);self.assertEqual(value['killed'],0)
        self.assertEqual(root['selected_sha256'],hashlib.sha256(selected.encode()).hexdigest())
        self.assertEqual(root['writer'],value['providerResults'][6]);self.assertEqual(root['verification'],value['providerResults'][7])
        self.assertEqual(root['writer_call'],value['providerCalls'][6]);self.assertEqual(root['verification_call'],value['providerCalls'][7])
        self.assertIn(json.dumps(value['providerResults'][6]['content'][0]['text']),value['providerCalls'][7]['code'])
        print('CONTROLLED_ROOT_SIX_FRAME',len(selected.encode()),len(value['providerCalls'][6]['code'].encode()),len(value['providerCalls'][7]['code'].encode()))
        print('CONTROLLED_COMPLETE_EXTERNAL_RECORD',len(subject().canonical(root)))

    def test_root_retains_the_exact_writer_call_even_when_transport_throws(self):
        value=self.node(self.carrier(self.code()),root_flow=True,root_pending=0,output=self.success_output(),provider_throw_at=2)
        self.assertEqual(value['root']['cause'],'controlled_provider_throw')
        self.assertEqual(value['root']['writer_call'],value['providerCalls'][1])
        self.assertEqual(value['root']['setup']['observed']['frames'],value['providerResults'])
        self.assertFalse(value['root']['retention_complete']);self.assertIsNone(value['root']['setup_success'])
        self.assertEqual(value['spawned'],1);self.assertNotIn('writer',value['root'])

    def test_deferred_factory_installs_definitions_once_without_starting_c_or_d(self):
        poll='if(!gate2Resume.writer_started){'+self.finish_code()+"}else nodeRepl.write(JSON.stringify({factory:gate2Resume.cd_factory_sha256,methods:Object.keys(gate2Resume.cd).sort(),spawned:gate2Resume.writer_state.pid,setup:gate2Resume.setup_success}));"
        v=self.node(self.carrier(self.code()),output=self.success_output(),polls=['writernormal','pending'],poll=poll)
        self.assertIsNone(v['error']);proof=json.loads(v['writes'][-1]);self.assertEqual(v['spawned'],2)
        from tests.test_accepted_policy_fixture_compiler_gate2_resume_caller_v1 import CD_FACTORY_SOURCE
        self.assertEqual(proof['factory'],hashlib.sha256(CD_FACTORY_SOURCE.encode()).hexdigest())
        self.assertEqual(proof['methods'],['begin','finish','poll','verifyReturn']);self.assertTrue(proof['setup'])

    def test_deferred_finalizer_binds_initial_argument_and_decoded_body_before_writer(self):
        code=self.carrier(self.code())
        for finalizer,reason in ((self.writer_code(expected_initial_sha256='0'*64),'initial_core_binding'),
                                  (self.writer_code(body_digest='0'*64),'finalizer_binding')):
            with self.subTest(reason=reason):
                value=self.node(code,root_flow=True,root_pending=0,output=self.success_output(),finalizer=finalizer)
                self.assertFalse(value['root']['retention_complete']);self.assertEqual(value['spawned'],1)
                self.assertIn(reason,value['root']['cause']);self.assertEqual(len(value['providerCalls']),2)

    def test_deferred_finalizer_reinstall_and_late_import_or_decode_cannot_spawn_writer(self):
        code=self.carrier(self.code())
        value=self.node(code,polls=['pending','pending'],poll=self.writer_code())
        self.assertEqual(value['error'],'writer_install');self.assertEqual(value['spawned'],1)
        for fault in ('finalizer_import_delay','finalizer_decode_delay'):
            with self.subTest(fault=fault):
                value=self.node(code,polls=['pending'],poll=self.writer_code(),**{fault:150000})
                self.assertEqual(value['error'],'writer_install');self.assertEqual(value['spawned'],1)
                self.assertEqual(len(value['writes']),1)

    def test_root_rejects_unsafe_unavailable_and_unfit_before_writer_and_late_postreturn(self):
        code=self.carrier(self.code())
        for fault in ('unsafe','truncated','metadata_bound'):
            with self.subTest(fault=fault):
                v=self.node(code,root_flow=True,root_pending=0,output=self.success_output(),provider_fault=fault)
                self.assertFalse(v['root']['retention_complete']);self.assertEqual(v['spawned'],1);self.assertEqual(len(v['providerCalls']),1)
        for fault in ('writer_delivery_delay','verify_delay'):
            with self.subTest(fault=fault):
                v=self.node(code,root_flow=True,root_pending=0,output=self.success_output(),**{fault:150000})
                self.assertFalse(v['root']['retention_complete']);self.assertEqual(v['spawned'],2);self.assertIn('writer_return_unknown',v['root']['cause'])

    def test_root_retains_every_completed_call_and_provider_result_before_third_result_refusal(self):
        value=self.node(self.carrier(self.code()),root_flow=True,root_pending=5,output=self.success_output(),provider_fault='unsafe',provider_fault_at=3)
        self.assertFalse(value['root']['retention_complete']);self.assertEqual(value['spawned'],1)
        observed=value['root']['setup']['observed']
        self.assertEqual(observed['calls'],value['providerCalls']);self.assertEqual(observed['frames'],value['providerResults'])
        self.assertEqual(len(observed['frames']),3);self.assertNotIn('selected',value['root']['setup'])

    def test_root_does_not_turn_unverified_setup_into_a_known_failure_when_writer_fails(self):
        v=self.node(self.carrier(self.code()),root_flow=True,root_pending=0,output=self.success_output(),writer_fault='fsync')
        self.assertIsNone(v['root']['setup_success']);self.assertFalse(v['root']['retention_complete']);self.assertFalse(v['root']['completed'])
        self.assertEqual(json.loads(self.decode(v['providerResults'][0]['content'][0]['text'])[0])['completed'],True)
        failed=self.node(self.carrier(self.code()),root_flow=True,root_pending=0,output=self.failure_output())
        self.assertEqual((failed['root']['setup_success'],failed['root']['retention_complete'],failed['root']['completed']),(False,True,False))

    def test_actual_root_rejects_delivered_old_six_field_success_proof(self):
        value=self.node(self.carrier(self.code()),root_flow=True,root_pending=5,output=self.success_output(),provider_fault='old_six_field_success',provider_fault_at=8)
        self.assertFalse(value['root']['completed']);self.assertFalse(value['root']['retention_complete']);self.assertIsNone(value['root']['setup_success'])
        self.assertEqual(value['root']['cause'],'return_proof');self.assertEqual(len(json.loads(value['root']['verification']['content'][0]['text'])),6)
        self.assertEqual(value['spawned'],2);self.assertEqual(value['root']['verification'],value['providerResults'][7])

    def test_authentic_max_failure_unicode_partial_and_unknown_six_frames_are_retained_honestly(self):
        code=self.carrier(self.code())
        failures=[self.failure_output(),self.failure_output(unicode=True)]
        self.assertTrue(all(1900<=len(x.encode())<=2048 for x in failures))
        cases=[(failures[0],{},False),(failures[1],{},False),
            (self.success_output()[:811],{'returncode':1},False),
            (self.success_output(),{'root_terminal_action':'exitonly'},False),
            (self.success_output(),{'stderr_output':'unexpected bounded stderr\n'},False)]
        for output,extra,accepted in cases:
            with self.subTest(length=len(output),extra=extra):
                value=self.node(code,root_flow=True,root_pending=5,output=output,**extra)
                self.assertIsNone(value['error']);self.assertTrue(value['root']['retention_complete'],value['root'])
                self.assertEqual(value['root']['setup_success'],accepted)
                raw=value['root']['setup']['selected'];self.assertLessEqual(len(raw.encode()),12288)
                self.assertEqual(json.loads(raw)['frames'],value['providerResults'][:6])
                print('CONTROLLED_ROOT_VARIANT',len(output.encode()),len(raw.encode()),len(subject().canonical(value['root'])),extra)

    def test_snapshot_uses_emitted_facts_and_no_performance_means_no_source_or_child(self):
        inspect="gate2Resume.setup.causes.push('after_emit');gate2Resume.setup.returncode=9;gate2Resume.setup.rows[0].raw[0][0]^=1;nodeRepl.write(JSON.stringify({setup:!!gate2Resume.setupView(gate2Resume.last_setup),rc:gate2Resume.last_setup.facts.returncode,causes:gate2Resume.last_setup.facts.causes}));"
        value=self.node(self.code(),output=self.success_output(),polls=['pending'],poll=inspect)
        self.assertIsNone(value['error']);self.assertEqual(json.loads(value['writes'][-1]),{'setup':True,'rc':0,'causes':[]})
        value=self.node(self.code(),no_performance=True)
        self.assertEqual(value['error'],'monotonic_unavailable');self.assertEqual(value['spawned'],0);self.assertFalse(value['sourceCalls'])

    def test_unknown_or_unusable_original_clock_refuses_before_import_source_or_spawn(self):
        for bad in ('nan','infinity','unsafe'):
            with self.subTest(bad=bad):
                value=self.node(self.carrier(self.code()),bad_initial_clock=bad)
                self.assertEqual(value['spawned'],0);self.assertFalse(value['sourceCalls']);self.assertTrue(value['error'])
        for fault in ('missing_raw_json','missing_source_context'):
            value=self.node(self.code(),**{fault:True})
            self.assertEqual(value['error'],'parse_source_feature');self.assertEqual(value['spawned'],0);self.assertFalse(value['sourceCalls'])

    def test_raw_high_bit_document_and_ready_bytes_cannot_be_masked_to_ascii_success(self):
        code=self.carrier(self.code())
        for fault in ('output_highbit','ready_highbit'):
            with self.subTest(fault=fault):
                v=self.node(code,root_flow=True,root_pending=0,output=self.success_output(),**{fault:True})
                self.assertFalse(v['root']['setup_success'])
        for fault in ('writer_highbit','writer_ready_highbit'):
            with self.subTest(fault=fault):
                v=self.node(code,root_flow=True,root_pending=0,output=self.success_output(),**{fault:True})
                self.assertFalse(v['root']['retention_complete'])

    def test_kind2_decoder_preserves_uint64_lexemes_and_binds_actual_observed_bytes(self):
        import base64
        anchor=2**64-150000000001
        value=self.node(self.carrier(self.code()),root_flow=True,root_pending=5,output=self.success_output(anchor),
            ready_decimal=str(anchor),writer_deadline_lexeme=str(2**64-1))
        self.assertTrue(value['root']['retention_complete'],value['root']);self.assertTrue(value['root']['setup_success'])
        selected=value['root']['setup']['selected'];self.assertLessEqual(len(selected),12288)
        text=value['root']['writer']['content'][0]['text'];raw=self.decode(text)
        self.assertEqual(len(raw),2);self.assertFalse(raw[1]);self.assertIn(str(2**64-1).encode(),raw[0])
        self.assertEqual(json.loads(raw[0].split(b'\n')[1])['deadline_ns'],2**64-1)
        self.assertEqual(hashlib.sha256(raw[0]).hexdigest(),self.facts(text)['pipes'][0]['sha256'])
        self.assertIn(str(anchor),self.decode(value['providerResults'][5]['content'][0]['text'])[0].decode())
        print('CONTROLLED_ROOT_UINT64',len(selected.encode()),len(raw[0]),len(subject().canonical(value['root'])))

    def test_writer_inner_input_sources_and_exact_delivered_text_are_all_mandatory(self):
        poll='if(!gate2Resume.writer_started){'+self.finish_code()+'}else gate2Resume.verifyReturn(__DELIVERED_WRITER_TEXT__);'
        for fault in ('source','extent','allocation','extra','stdin_eof','stdin_extent','source_bytes','fsync','close','written','bool_allocation','float_allocation','forms'):
            with self.subTest(fault=fault):
                value=self.node(self.carrier(self.code('fixed')),output=self.success_output(),polls=['writernormal','pending'],poll=poll,writer_fault=fault)
                self.assertTrue(value['error']);self.assertEqual(value['spawned'],2)
        value=self.node(self.carrier(self.code('fixed')),polls=['writernormal','pending'],poll=poll,writer_input_error=True)
        self.assertEqual(value['error'],'writer_transport')
        value=self.node(self.carrier(self.code('fixed')),polls=['writernormal','pending'],poll='if(!gate2Resume.writer_started){'+self.finish_code()+"}else gate2Resume.verifyReturn('changed actual result');")
        self.assertEqual(value['error'],'writer_delivered_binding')

    def test_actual_extra_provider_metadata_or_unfit_observed_prefix_refuses_before_writer_launch(self):
        m=subject();value=self.node(self.code(),output=''.join(hashlib.sha256(str(i).encode()).hexdigest() for i in range(32)))
        frames=[{'content':[{'type':'text','text':value['writes'][0]}],'isError':False,'_meta':{'actual_extra':''.join(hashlib.sha256(str(i).encode()).hexdigest() for i in range(130))}}]
        with self.assertRaises(m.ResumeRefusal):m.outer_collection_v1({'tool':'mcp__node_repl__js','codes':[self.code()]},frames)
        self.assertEqual(value['spawned'],1)

    def test_node_stdin_error_is_sticky_even_if_finish_and_close_follow(self):
        observed=self.node(self.carrier(self.code()),stdin_error=True)
        facts=self.facts(observed['writes'][0])
        self.assertTrue(facts['stdin_finished']);self.assertTrue(facts['stdin_closed'])
        self.assertEqual(facts['returncode'],0)
        self.assertTrue(facts['stdin_extent_unknown']);self.assertTrue(facts['unknown_closure'])
        self.assertFalse(facts['completed'])


class ResumeBoundaries(unittest.TestCase):
    def test_owned_process_thread_start_failure_preserves_pid_and_one_stdin_close(self):
        m=subject()
        for fail_at in (1,2):
            for close_failure in (False,True):
                starts=[];closes=[];writes=[];polls=[]
                class Input:
                    def write(self,raw):writes.append(raw);raise AssertionError('send after failed reader startup')
                    def flush(self):pass
                    def close(self):
                        closes.append(1)
                        if close_failure:raise OSError('controlled close')
                class Thread:
                    def __init__(self,*,target,args,daemon):self.target,self.args=target,args;self.daemon=daemon
                    def start(self):
                        starts.append(self.daemon)
                        if len(starts)==fail_at:raise RuntimeError('thread_start_failed')
                        self.target(*self.args)
                def poll():polls.append(1);return None
                p=SimpleNamespace(pid=531,stdin=Input(),stdout=io.BytesIO(b'known-prefix'),stderr=io.BytesIO(),poll=poll)
                with patch.object(m.time,'monotonic_ns',return_value=1),\
                     patch.object(m.subprocess,'Popen',return_value=p) as opened,\
                     patch.object(m.threading,'Thread',Thread):
                    with self.assertRaises(m.ResumeRefusal) as caught:m._Run(1).process(['controlled'],b'not-sent',100,100)
                facts=caught.exception.facts
                self.assertEqual(facts['pid'],531);self.assertIsNone(facts['returncode']);self.assertTrue(facts['unknown_closure'])
                self.assertEqual(facts['causes'],['thread_start_failed']+(['stdin_close_failed'] if close_failure else []))
                self.assertEqual(facts['stdin_bytes'],0);self.assertEqual(facts['stdin_sha256'],m.sha(b''))
                self.assertEqual(facts['stdin_closed'],not close_failure);self.assertFalse(facts['stdin_extent_unknown'])
                self.assertEqual(starts,[True]*fail_at);self.assertEqual(closes,[1]);self.assertFalse(writes)
                self.assertEqual(polls,[]);opened.assert_called_once()
                self.assertEqual(facts['stdout_bytes'],0 if fail_at==1 else len(b'known-prefix'))
                self.assertEqual(facts['stdout_eof'],fail_at==2);self.assertFalse(facts['stderr_eof'])

    def test_poll_failure_keeps_last_observed_status_and_never_repolls_after_refusal(self):
        m=subject()
        for observed_zero in (False,True):
            for close_failure in (False,True):
                polls=[];closes=[]
                class Input:
                    def write(self,raw):return len(raw)
                    def flush(self):pass
                    def close(self):
                        closes.append(1)
                        if close_failure:raise OSError('controlled close')
                def poll():
                    polls.append(1)
                    if observed_zero and len(polls)==1:return 0
                    raise OSError('controlled_poll_failed')
                p=SimpleNamespace(pid=532,stdin=Input(),stdout=io.BytesIO(),stderr=io.BytesIO(),poll=poll)
                thread=lambda **kwargs:SimpleNamespace(start=lambda:None)
                with patch.object(m.time,'monotonic_ns',return_value=1),patch.object(m.time,'sleep'),\
                     patch.object(m.subprocess,'Popen',return_value=p),patch.object(m.threading,'Thread',side_effect=thread):
                    with self.assertRaises(m.ResumeRefusal) as caught:m._Run(1).process(['controlled'],b'',100,100,ready=lambda _: {})
                facts=caught.exception.facts
                self.assertEqual(facts['pid'],532);self.assertEqual(facts['returncode'],0 if observed_zero else None)
                self.assertTrue(facts['unknown_closure']);self.assertEqual(len(polls),2 if observed_zero else 1)
                self.assertEqual(closes,[1]);self.assertEqual(facts['stdin_closed'],not close_failure)
                self.assertEqual(facts['causes'],['controlled_poll_failed']+(['stdin_close_failed'] if close_failure else []))

    def test_amended_complete_original_12k_exact_and_one_byte_over(self):
        m=subject();x={'call':{'fixed':'reviewed'},'frames':[{'content':[],'isError':False}]}
        n=12288-len(m.canonical(x))-len(',"padding":""')
        call=dict(x['call'],padding='x'*n)
        # Derive the exact padding from the current complete wrapper, not a guessed header length.
        call['padding']=''
        call['padding']='x'*(12288-len(m.canonical({'call':call,'frames':x['frames']})))
        self.assertEqual(len(m.outer_collection_v1(call,x['frames'])),12288)
        call['padding']+='x'
        with self.assertRaises(m.ResumeRefusal):m.outer_collection_v1(call,x['frames'])

    def test_writer_unknown_negative_boolean_allocation_refuses_with_actual_known_value(self):
        m=subject();comp=importlib.import_module('tests.fixtures.accepted_policy_fixture_compiler_component_v1')
        for allocated in (-1,None,False):
            with self.subTest(allocated=allocated),tempfile.TemporaryDirectory() as directory,\
                 patch.object(comp,'_resume_fd_allocation_v1',return_value=allocated):
                with self.assertRaises(m.ResumeRefusal) as failure:
                    m.write_fixed_v1(Path(directory)/'owned',b'known',8192,lambda:None,comp)
                self.assertEqual(failure.exception.facts['allocated_bytes'],allocated)
                self.assertTrue(failure.exception.facts['close_completed'])

    def test_late_read_stat_or_allocation_does_not_start_the_next_io(self):
        m=subject();comp=importlib.import_module('tests.fixtures.accepted_policy_fixture_compiler_component_v1')
        actual_read,actual_stat,actual_alloc,actual_pathstat=m.os.read,m.os.fstat,comp._resume_fd_allocation_v1,Path.lstat
        for kind in ('read','stat','allocation','second_stat'):
            clock=[1];stats=[];allocs=[];late_paths=[]
            def gate():
                if clock[0]>=100:raise m.ResumeRefusal('original_deadline')
            def read(fd,n):
                result=actual_read(fd,n)
                if kind=='read':clock[0]=100
                return result
            def stat(fd):
                stats.append(clock[0]);result=actual_stat(fd)
                if kind=='stat' or kind=='second_stat' and len(stats)==2:clock[0]=100
                return result
            def allocation(fd,info):
                allocs.append(clock[0]);result=actual_alloc(fd,info)
                if kind=='allocation':clock[0]=100
                return result
            def pathstat(path,*args,**kwargs):
                if clock[0]>=100:late_paths.append(str(path))
                return actual_pathstat(path,*args,**kwargs)
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as directory:
                with patch.object(m.os,'read',side_effect=read),patch.object(m.os,'fstat',side_effect=stat),\
                     patch.object(comp,'_resume_fd_allocation_v1',side_effect=allocation),patch.object(Path,'lstat',pathstat):
                    with self.assertRaises(m.ResumeRefusal) as last_error:m.write_fixed_v1(Path(directory)/'owned',b'known',100,gate,comp)
                if kind=='read':self.assertEqual(stats,[])
                if kind=='stat':self.assertEqual(allocs,[])
                if kind=='allocation':
                    self.assertEqual(len(stats),1)
                    self.assertGreater(last_error.exception.facts['allocated_bytes'],0)
                if kind=='second_stat':self.assertEqual(late_paths,[])

    def test_late_creator_fd_seek_never_starts_readback_after_original_deadline(self):
        m=subject();clock=[1];reads=[];seek=m.os.lseek;read=m.os.read
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'exclusive'
            def late(fd,*args):
                value=seek(fd,*args);clock[0]=100;return value
            def gate():
                if clock[0]>=100:raise m.ResumeRefusal('original_deadline')
            def observed(fd,n):reads.append(n);return read(fd,n)
            with patch.object(m.os,'lseek',side_effect=late),patch.object(m.os,'read',side_effect=observed):
                with self.assertRaises(m.ResumeRefusal):
                    m.write_fixed_v1(path,b'known',100,gate,importlib.import_module('tests.fixtures.accepted_policy_fixture_compiler_component_v1'))
        self.assertEqual(reads,[])

    def test_failed_send_keeps_unknown_status_without_a_new_poll(self):
        m=subject();polls=[]
        class Input(io.BytesIO):
            def write(self,raw):raise OSError('controlled input failure')
        def poll():polls.append(None if not polls else 0);return polls[-1]
        process=SimpleNamespace(pid=23,stdin=Input(),stdout=io.BytesIO(),stderr=io.BytesIO(),poll=poll)
        with patch.object(m.time,'monotonic_ns',return_value=1),patch.object(m.subprocess,'Popen',return_value=process):
            with self.assertRaises(m.ResumeRefusal) as caught:m._Run(1).process(['controlled'],b'x',100,100)
        self.assertEqual(polls,[])
        self.assertIsNone(caught.exception.facts['returncode'])
        self.assertTrue(caught.exception.facts['unknown_closure'])

    def test_guarded_dependency_read_and_close_failure_preserves_read_refusal(self):
        m=subject();close=m.os.close
        class ShortReader:
            def __init__(self,fd):self.fd=fd
            def __enter__(self):return self
            def __exit__(self,*args):self.close()
            def fileno(self):return self.fd
            def read(self,count):return b'short'
            def close(self):close(self.fd);raise OSError('controlled close')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'source.py';path.write_bytes(b'complete-source')
            with patch.object(m.os,'fdopen',side_effect=lambda fd,*a,**k:ShortReader(fd)):
                with self.assertRaises(m.ResumeRefusal) as caught:m.read_fixed_v1(path,100)
        self.assertEqual(caught.exception.cause,'read_drift')
        self.assertEqual(caught.exception.facts['secondary'],['read_close_failed'])

    def test_ready_ack_full_stdin_hash_and_write_close_failure_facts(self):
        m=subject();ready={'linux_ready_ns':10,'boot_id':'b'*36};result={'native_pid':99}
        output=m.canonical(ready)+b'\n'+m.canonical(result)+b'\n'
        for fail in (False,True):
            class Input(io.BytesIO):
                calls=0
                def write(self,raw):
                    self.calls+=1
                    if fail and self.calls==2:raise OSError('ack_write_failed')
                    return super().write(raw)
                def close(self):
                    self.observed=self.getvalue()
                    if fail:raise OSError('close failed')
                    super().close()
            input_pipe=Input();p=SimpleNamespace(pid=55,stdin=input_pipe,stdout=io.BytesIO(output),stderr=io.BytesIO(),poll=lambda:0)
            with self.subTest(fail=fail),patch.object(m.time,'monotonic_ns',return_value=1),\
                 patch.object(m.subprocess,'Popen',return_value=p):
                run=m._Run(1)
                if fail:
                    with self.assertRaises(m.ResumeRefusal) as caught:m.phase_v1(run,'PRE',{'current':{}})
                    facts=caught.exception.facts
                    self.assertEqual(facts['causes'],['ack_write_failed','stdin_close_failed'])
                    self.assertTrue(facts['stdin_extent_unknown']);self.assertFalse(facts['stdin_closed'])
                    self.assertTrue(facts['unknown_closure']);self.assertEqual(facts['stdin_bytes'],len(m.canonical({'current':{}}))+1)
                else:
                    self.assertEqual(m.phase_v1(run,'PRE',{'current':{}}),result)
                    facts=run.events[0]
                    self.assertEqual(facts['stdin_sha256'],m.sha(input_pipe.observed))
                    self.assertEqual(facts['stdin_bytes'],len(input_pipe.observed));self.assertTrue(facts['stdin_closed'])
                    self.assertEqual(facts['native_pid'],99)
                    self.assertEqual(facts['clock_anchor']['global_deadline_ns'],140000000010)

    def test_decoded_native_missing_or_boolean_pid_keeps_completed_process_facts(self):
        m=subject();facts={'pid':55,'returncode':0,'stdout_eof':True,'stderr_eof':True}
        for value in ({},{'native_pid':True},{'native_pid':0}):
            run=SimpleNamespace(check=lambda *a:1,work=140000000001,events=[],
                anchor={'l0':10,'w1':1,'global_deadline_ns':140000000010},process=lambda *a:(m.canonical(value)+b'\n',facts))
            with self.subTest(value=value):
                with self.assertRaises(m.ResumeRefusal) as caught:m.phase_v1(run,'FINAL',{})
                self.assertEqual(caught.exception.facts['process'],facts)

    def test_exact_windows_caller_hash_close_and_original_clock_failures(self):
        m=subject();self.assertEqual(len(WINDOWS_CALLER.encode('ascii')),2144)
        import stat,sys,pathlib,builtins
        good=b"def main(a,b,*,_original_start_ns):\n import time\n return int(time.monotonic_ns()>=_original_start_ns+140000000000)\n"
        class Fixed:
            def lstat(self):return info
            def resolve(self,strict):return self
            def __str__(self):return 'fixed-reviewed-operator.py'
        info=SimpleNamespace(st_dev=1,st_ino=2,st_mode=stat.S_IFREG|0o600,st_nlink=1,st_size=len(good),
            st_mtime_ns=1,st_ctime_ns=2,st_birthtime_ns=3)
        original_compile=builtins.compile
        for kind in ('normal','binding+close','latecompile'):
            clock=[1];writes=[];closes=[]
            def close(fd):
                closes.append(fd)
                if kind=='binding+close':raise OSError('controlled close')
            def compile_late(*args,**kwargs):
                value=original_compile(*args,**kwargs)
                if kind=='latecompile':clock[0]=140000000002
                return value
            argv=['python','a'*40,'https://github.com/lordcoudy/VAST/pull/9#issuecomment-1234567890',str(len(good)),
                m.sha(good) if kind!='binding+close' else '0'*64]
            with self.subTest(kind=kind),patch.object(m.time,'monotonic_ns',side_effect=lambda:clock[0]),\
                 patch.object(pathlib,'Path',return_value=Fixed()),patch.object(sys,'argv',argv),\
                 patch.object(m.os,'O_BINARY',0,create=True),patch.object(m.os,'open',return_value=99),\
                 patch.object(m.os,'fstat',return_value=info),patch.object(m.os,'read',return_value=good),\
                 patch.object(m.os,'close',side_effect=close),\
                 patch.object(m.os,'write',side_effect=lambda fd,b:writes.append((fd,b)) or len(b)),\
                 patch.object(builtins,'compile',side_effect=compile_late):
                with self.assertRaises(SystemExit) as done:exec(WINDOWS_CALLER,{'__name__':'controlled_caller'})
            self.assertEqual(closes,[99])
            if kind=='normal':self.assertEqual(done.exception.code,0);self.assertEqual(writes,[])
            elif kind=='latecompile':self.assertEqual(done.exception.code,1);self.assertEqual(writes,[])
            else:
                self.assertEqual(done.exception.code,1);self.assertEqual([fd for fd,b in writes],[1])
                value=json.loads(writes[0][1]);self.assertEqual(value['causes'],['bootstrap_binding','bootstrap_close_OSError'])
                self.assertLessEqual(len(writes[0][1]),2048)

    def test_actual_six_frame_call_and_escaped_terminal_geometry_is_complete(self):
        m=subject();source=Path(m.__file__).read_bytes();commit='a'*40
        approval='https://github.com/lordcoudy/VAST/pull/9#issuecomment-1234567890'
        cmd="$p=@'\n"+WINDOWS_CALLER+"'@\n& C:/Python314/python.exe -I -S -B -c $p '"+commit+"' '"+approval+"' '"+str(len(source))+"' '"+m.sha(source)+"'\nexit $LASTEXITCODE"
        args={'cmd':cmd,'workdir':str(m.REPO_WIN).replace('/','\\'),'login':False,'yield_time_ms':1000,'max_output_tokens':4096}
        code="const r=await tools.exec_command("+m.canonical(args).decode()+");store('gate2-p0-exception-actual-first-frame',r);text(r);"
        waits=[min(30000,remaining) for remaining in (139000,109000,79000,49000,19000)]
        poll_codes=['text(await tools.write_stdin({session_id:999999,yield_time_ms:'+str(wait)+'}));' for wait in waits]
        calls=[{'tool':'functions.exec','code':body} for body in [code]+poll_codes]
        call={'tool':'functions.exec','codes':[item['code'] for item in calls]}
        for output in (formatter()(result={'code_commit':commit,'packet':{'path':str(m.ROOT/'gate2.packet.original.json'),
                         'size_bytes':20516,'sha256':'d'*64},'c_or_d_invoked':False})+b'\n',
                       formatter()(error=m.ResumeRefusal('💥'*64,{'returncode':None,'eof_stdout':True,'eof_stderr':True,
                           'causes':['💥'*64]*4,'padding':'x'*40000}))+b'\n',
                       (b'"\\'*1023)+b'\n'):
            frames=[{'chunk_id':'abcdef','wall_time_seconds':30.123456789012345,'session_id':999999,
                     'output':'','original_token_count':0} for _ in range(5)]
            frames.append({'chunk_id':'fedcba','wall_time_seconds':1.123456789012345,'exit_code':1,
                'output':output.decode('ascii'),'original_token_count':len(output)})
            raw=m.outer_collection_v1(call,frames);held=json.loads(raw)
            self.assertEqual(held,{'call':call,'frames':frames});self.assertLessEqual(len(raw),8192)
            expanded_calls=[{'tool':held['call']['tool'],'code':body} for body in held['call']['codes']]
            self.assertEqual(expanded_calls,calls)
            actual_args=json.loads(expanded_calls[0]['code'].split('tools.exec_command(',1)[1].split(");store(",1)[0])
            self.assertEqual(actual_args,args);self.assertIn(WINDOWS_CALLER,actual_args['cmd'])
            self.assertEqual([item['code'] for item in expanded_calls[1:]],poll_codes)
            self.assertTrue(all(0<wait<=30000 for wait in waits))
            print('CONTROLLED_GEOMETRY',len(WINDOWS_CALLER.encode()),len(m.canonical(call)),len(output),len(raw))
        extra=12288-len(raw)
        boundary=dict(call,padding='x'*(extra-len(',"padding":""')))
        self.assertEqual(len(m.outer_collection_v1(boundary,frames)),12288)
        boundary['padding']+='x'
        with self.assertRaises(m.ResumeRefusal):m.outer_collection_v1(boundary,frames)
        frames[-1]['output']='💥'*1000
        with self.assertRaises(m.ResumeRefusal):m.outer_collection_v1(call,frames)

    def test_terminal_short_or_late_emit_never_emits_a_second_document(self):
        m=subject()
        for kind in ('short','late'):
            clock=[1];writes=[]
            def emit(fd,raw):
                writes.append((fd,raw))
                if kind=='late':clock[0]=140000000002
                return len(raw)-(kind=='short')
            with self.subTest(kind=kind),patch.object(m,'windows_v1',return_value=True),\
                 patch.object(m.time,'monotonic_ns',side_effect=lambda:clock[0]),\
                 patch.object(m,'authenticate_v1',side_effect=m.ResumeRefusal('git_exit',{'pid':8,'returncode':None,
                     'stdout_eof':True,'stderr_eof':False,'unknown_closure':True})),\
                 patch.object(m.os,'write',side_effect=emit):
                status=m.main('a'*40,'https://github.com/lordcoudy/VAST/pull/9#issuecomment-1234567890',_original_start_ns=1)
            self.assertEqual(status,1);self.assertEqual([fd for fd,b in writes],[1]);self.assertLessEqual(len(writes[0][1]),2048)
            self.assertFalse(json.loads(writes[0][1])['completed'])

    def test_native_bootstrap_binding_and_close_failure_preserve_primary_and_secondary(self):
        m=subject();raw=Path(m.__file__).read_bytes();d=m.source_descriptor_v1(raw);d['sha256']='0'*64
        import sys
        writes=[];close=m.os.close
        def fail_close(fd):close(fd);raise OSError('controlled close')
        with self.native_files(m),patch.object(sys,'argv',['python','PRE']),\
             patch.object(sys,'stdin',SimpleNamespace(buffer=io.BytesIO(m.canonical({'current':{m.OPERATOR:d}})+b'\n'))),\
             patch.object(m.os,'close',side_effect=fail_close),\
             patch.object(m.os,'write',side_effect=lambda fd,b:writes.append((fd,b)) or len(b)):
            with self.assertRaises(SystemExit):exec(m.NATIVE_BOOTSTRAP,{'__name__':'controlled_bad_bootstrap'})
        self.assertEqual([fd for fd,b in writes],[2])
        value=json.loads(writes[0][1]);self.assertEqual(value['cause'],'AssertionError()')
        self.assertEqual(value['causes'],['close_failed']);self.assertTrue(value['unknown_closure'])
        self.assertLessEqual(len(writes[0][1]),768)

    @contextmanager
    def native_files(self,m,namespace=None):
        repo=Path(__file__).resolve().parents[1]
        old_lstat,old_stat,old_open=m.os.lstat,m.os.stat,m.os.open
        old_resolve=Path.resolve
        def translated(path):
            value=os.fspath(path)
            for fixed,actual in ((str(m.REPO_LINUX),repo),(str(m.ROOT),namespace)):
                if actual is not None and (value==fixed or value.startswith(fixed+'/')):
                    return Path(actual)/value[len(fixed):].lstrip('/')
            return path
        def resolve(path,*args,**kwargs):
            actual=translated(path)
            if actual!=path:
                self.assertEqual(old_resolve(actual,*args,**kwargs),actual)
                return path
            return old_resolve(path,*args,**kwargs)
        with ExitStack() as stack:
            stack.enter_context(patch.object(m.os,'lstat',side_effect=lambda p,*a,**k:old_lstat(translated(p),*a,**k)))
            stack.enter_context(patch.object(m.os,'stat',side_effect=lambda p,*a,**k:old_stat(p if isinstance(p,int) else translated(p),*a,**k)))
            stack.enter_context(patch.object(m.os,'open',side_effect=lambda p,*a,**k:old_open(translated(p),*a,**k)))
            stack.enter_context(patch.object(Path,'resolve',resolve))
            yield

    def test_actual_guarded_source_reads_cover_complete_large_regular_files(self):
        m=subject();repo=Path(__file__).resolve().parents[1]
        for name in m.SOURCE_PATHS:
            with self.subTest(source=name):
                raw,info=m.read_fixed_v1(repo/name,131072)
                self.assertEqual(raw,(repo/name).read_bytes())
                self.assertEqual(len(raw),info.st_size)

    def test_actual_main_verified_closure_p0_api_write_order_and_single_terminal(self):
        m=subject();repo=Path(__file__).resolve().parents[1]
        sources={name:(repo/name).read_bytes() for name in m.SOURCE_PATHS}
        cur={name:m.source_descriptor_v1(raw) for name,raw in sources.items()}
        index=json.loads((repo/m.INDEX).read_bytes());idx=m.source_descriptor_v1((repo/m.INDEX).read_bytes())
        from tests.test_accepted_policy_fixture_compiler_gate2_p0_v1 import ControlledEffects,success_scripts
        from tests.test_accepted_policy_fixture_compiler_gate2_c_v1 import ResumeInfoTests
        effects=ControlledEffects(success_scripts());effects.controlled=False
        info,rpc,request,reply=ResumeInfoTests.native_shaped_info(self)
        current_c=formatter().__globals__
        pre_info=current_c['resume_info_v1'](info=info,rpc_facts=rpc,request_raw=request,reply_raw=reply)
        rpc=current_c['_rpc_json_facts_v1'](rpc)
        prior={'index_sha256':'a'*64,'source_rows_sha256':'b'*64,'node_count':28,'native_quote_bytes':633856,
            'windows_quote_bytes':32768,'transcript_quote_bytes':12288,'owned_upper_bytes':2102272,
            'old_f2_upper_bytes':333056,'physical_acceptance':False}
        retention={'schema':'vast_gate2_resume_retention_receipt_v1','index_sha256':idx['sha256'],
            'source_versions_sha256':'c'*64,'prior':prior,'native':{'node_count':70,'native_code_quote_bytes':586240,
            'parent_growth_bytes':8192,'f2_quote_bytes':4372992,'aux_quote_bytes':39424,'windows_capture_quote_bytes':32768,
            'diagnostic_quote_bytes':16384,'diagnostic_sha256':m.DIAGNOSTIC_SHA,'manifest_sha256':m.MANIFEST_SHA,
            'physical_acceptance':False},'physical_acceptance':False}
        import sys
        saved=dict(sys.modules);order=[];outputs=[];emitted=[];real_load=m.load_verified_v1;real_write=m.write_fixed_v1;os_write=m.os.write
        def load(src,desc,root):
            modules=real_load(src,desc,root);p0=modules[m.CODE[7]];collect=p0.collect_native_p0_v1
            def controlled(*args,**kwargs):
                order.append('P0')
                with patch.object(p0,'windows_native_p0_effects',return_value=effects),\
                     patch.object(p0.os,'name','nt'),patch.object(p0.time,'monotonic',effects.monotonic):
                    return collect(*args,**kwargs)
            p0.collect_native_p0_v1=controlled
            return modules
        def process(run,argv,payload,deadline,cap=8192,ready=None):
            phase=argv[-1];order.append(phase);x=json.loads(payload)
            if phase=='PRE':
                ack=ready({'linux_ready_ns':10,'boot_id':'b'*36})
                self.assertLess(ack['phase_deadline_ns'],ack['global_deadline_ns'])
                value={'native_pid':99,'boot_id':'b'*36,'retention':retention,'baseline':{'c_free_bytes':99000000000,
                    'ext4_used_bytes':313000000000,'project_free_bytes':100000000000,'fragment_bytes':4096,'backing_device':2112},
                    'pre_info':pre_info,'rpc_facts':rpc}
                raw=m.canonical({'linux_ready_ns':10,'boot_id':'b'*36})+b'\n'+m.canonical(value)+b'\n'
                self.assertLessEqual(len(m.canonical(value)),7168)
            elif phase=='PACKET':
                self.assertEqual(order[-4:],['operator.command.original.json','P0','p0.return.original.json','PACKET'])
                self.assertEqual(x['authority']['path'],str(m.AUX/'operator.authority.original.json'))
                value={'native_pid':100,'packet':{'path':str(m.ROOT/'gate2.packet.original.json'),'size_bytes':20516,'sha256':'d'*64}}
                raw=m.canonical(value)+b'\n'
            else:
                self.assertEqual(order[-2:],[ 'resume.events.original.json','FINAL'])
                self.assertEqual(x['events']['path'],str(m.AUX/'resume.events.original.json'))
                value={'native_pid':101,'fresh_interval_N':200000,'native_bytes':1019136,'outside_bytes':508160,
                    'active_f2_debit':5545280,'outstanding_tail_bytes':37120,'historical_closing_meter_available':False,
                    'physical_acceptance':False,'final_measurement':{'c_free_bytes':99000000000,'ext4_used_bytes':313000000000,
                    'project_free_bytes':100000000000,'fragment_bytes':4096,'backing_device':2112}}
                raw=m.canonical(value)+b'\n'
            facts={'pid':44,'returncode':0,'stdout_eof':True,'stderr_eof':True,'stdout_bytes':len(raw),
                'stdout_sha256':m.sha(raw),'stderr_bytes':0,'stderr_sha256':m.sha(b''),'stdin_closed':True,
                'stdin_extent_unknown':False,'stdin_bytes':len(payload),'stdin_sha256':m.sha(payload),'unknown_closure':False}
            return raw,facts
        try:
            for name in ('tests','tests.fixtures')+tuple(name for name,_ in m.MODULES):sys.modules.pop(name,None)
            with tempfile.TemporaryDirectory() as directory:
                def write(path,raw,cap,check,component):
                    order.append(Path(path).name);outputs.append((Path(path).name,raw))
                    return real_write(Path(directory)/Path(path).name,raw,cap,check,component)
                with patch.object(m,'windows_v1',return_value=True),patch.object(m,'REPO_WIN',repo),\
                     patch.object(m.time,'monotonic_ns',return_value=1),\
                     patch.object(m,'authenticate_v1',return_value=(sources,cur,index,idx,{})),\
                     patch.object(m,'load_verified_v1',side_effect=load),patch.object(m._Run,'process',process),\
                     patch.object(m.shutil,'disk_usage',return_value=SimpleNamespace(free=200000000000)),\
                     patch.object(m,'write_fixed_v1',side_effect=write),\
                     patch.object(m.os,'write',side_effect=lambda fd,raw:(emitted.append((fd,raw)) or len(raw)) if fd==1 else os_write(fd,raw)):
                    status=m.main('a'*40,'https://github.com/lordcoudy/VAST/pull/9#issuecomment-1234567890',_original_start_ns=1)
            self.assertEqual(status,0,emitted)
            self.assertEqual([fd for fd,raw in emitted],[1])
            self.assertLessEqual(len(emitted[0][1]),2048)
            value=json.loads(emitted[0][1]);self.assertTrue(value['completed']);self.assertFalse(value['physical_acceptance'])
            self.assertEqual(order,['PRE','operator.authority.original.json','operator.command.original.json','P0',
                'p0.return.original.json','PACKET','resume.events.original.json','FINAL'])
            self.assertEqual(len(effects.scripts),3)
            events=json.loads(dict(outputs)['resume.events.original.json'])
            self.assertEqual([row['phase'] for row in events['processes']],['PRE','PACKET'])
            self.assertLessEqual(len(dict(outputs)['resume.events.original.json']),8192)
            print('CONTROLLED_MAIN_FORMS',[(name,len(body)) for name,body in outputs])
        finally:
            for name in set(sys.modules)-set(saved):sys.modules.pop(name,None)
            sys.modules.update(saved)

    def test_native_failure_producer_through_process_preserves_ordered_causes(self):
        m=subject();f=formatter();c=SimpleNamespace(**f.__globals__)
        failure=c.Gate2Refusal('resume_pre_transport',{'failure_facts':{
            'causes':['request_write_failed','socket_close_failed'],'write_extent_unknown':True}})
        raw=c.native_failure_bytes_v1(failure)
        p=SimpleNamespace(pid=51,stdin=io.BytesIO(),stdout=io.BytesIO(),stderr=io.BytesIO(raw),poll=lambda:1)
        with patch.object(m.time,'monotonic_ns',return_value=1),patch.object(m.subprocess,'Popen',return_value=p):
            with self.assertRaises(m.ResumeRefusal) as caught:m._Run(1).process(m.native_argv_v1('PRE'),b'',100)
        value=json.loads(f(error=caught.exception))
        self.assertEqual(value['causes'][:4],['process_refused','resume_pre_transport','request_write_failed','socket_close_failed'])
        self.assertEqual(caught.exception.facts['stderr_sha256'],m.sha(raw))

    def test_actual_native_bootstrap_authenticates_buffers_and_refuses_expired_phase_without_effects(self):
        m=subject();root=Path(__file__).resolve().parents[1]
        sources={name:(root/name).read_bytes() for name in m.SOURCE_PATHS}
        current={name:m.source_descriptor_v1(raw) for name,raw in sources.items()}
        x={'current':current,'global_deadline_ns':0,'phase_deadline_ns':0,'context':{'boot_id':'unused'}}
        import sys
        saved=dict(sys.modules);out=[]
        try:
            for name in ('tests','tests.fixtures')+tuple(name for name,_ in m.MODULES):sys.modules.pop(name,None)
            with self.native_files(m),patch.object(sys,'stdin',SimpleNamespace(buffer=io.BytesIO(m.canonical(x)+b'\n'))),\
                 patch.object(sys,'argv',['python','FINAL']),\
                 patch.object(m.os,'write',side_effect=lambda fd,raw:out.append((fd,raw)) or len(raw)),\
                 patch.object(m.subprocess,'Popen',side_effect=AssertionError('native process effect')):
                with self.assertRaises(SystemExit) as done:exec(m.NATIVE_BOOTSTRAP,{'__name__':'controlled_bootstrap'})
            self.assertEqual(done.exception.code,1)
            self.assertIn('tests.fixtures.'+Path(m.CODE[0]).stem,sys.modules)
            c=sys.modules['tests.fixtures.'+Path(m.CODE[0]).stem]
            d=sys.modules['tests.fixtures.'+Path(m.CODE[8]).stem]
            child=sys.modules['tests.fixtures.'+Path(m.CODE[9]).stem]
            self.assertIs(c.component,d.recipe);self.assertIs(child.stage,d)
            self.assertEqual([fd for fd,raw in out],[2])
            self.assertLessEqual(len(out[0][1]),768)
            self.assertEqual(json.loads(out[0][1])['cause'],'native_late_boot')
        finally:
            for name in set(sys.modules)-set(saved):sys.modules.pop(name,None)
            sys.modules.update(saved)

    def test_rc_zero_overflow_and_pipe_close_failure_remain_unknown(self):
        m=subject()
        class BadClose(io.BytesIO):
            def close(self):raise OSError('close failed')
        for out in (io.BytesIO(b'overflow'),BadClose(b'')):
            p=SimpleNamespace(pid=43,stdin=io.BytesIO(),stdout=out,stderr=io.BytesIO(),poll=lambda:0)
            with self.subTest(kind=type(out).__name__),patch.object(m.time,'monotonic_ns',return_value=1),\
                 patch.object(m.subprocess,'Popen',return_value=p):
                with self.assertRaises(m.ResumeRefusal) as caught:m._Run(1).process(['controlled'],b'',100,2)
            self.assertEqual(caught.exception.facts['returncode'],0)
            self.assertTrue(caught.exception.facts['unknown_closure'])

    def test_closed_c_d_route_authenticates_fixed_packet_before_dependency_execution(self):
        m=subject();root=Path(__file__).resolve().parents[1]
        sources={name:(root/name).read_bytes() for name in m.SOURCE_PATHS}
        current={name:m.source_descriptor_v1(raw) for name,raw in sources.items()}
        commit='a'*40
        packet={'code_commit':commit,'code':{p:current[p] for p in m.CODE},'resume_context':{
            'operator':current[m.OPERATOR],'consumer_plan':current[m.PLAN]}}
        raw=m.canonical(packet);args=[commit,str(len(raw)),m.sha(raw),'-']
        def read(path,cap):
            if str(path)==str(m.ROOT/'gate2.packet.original.json'):return raw,None
            return sources[str(path).removeprefix(str(m.REPO_LINUX)+'/')],None
        c=SimpleNamespace(native_main_v1=lambda a:0)
        with patch.object(m.sys,'argv',['python','D']+args),patch.object(m,'read_fixed_v1',side_effect=read),\
             patch.object(m,'load_verified_v1',return_value={m.CODE[0]:c}) as loader,\
             patch.object(c,'native_main_v1',return_value=0) as native:
            with self.assertRaises(SystemExit) as done:m.native_entry_v1('D',{'current':{m.OPERATOR:current[m.OPERATOR]}})
            self.assertEqual(done.exception.code,0)
            self.assertEqual(loader.call_args.args[1],current)
            native.assert_called_once_with(['D']+args)
        with patch.object(m.sys,'argv',['python','C1']+args),\
             patch.object(m,'read_fixed_v1',return_value=(raw+b' ',None)),\
             patch.object(m,'load_verified_v1',side_effect=AssertionError('dependent execution')) as loader:
            with self.assertRaises(m.ResumeRefusal):m.native_entry_v1('C1',{})
            loader.assert_not_called()
        for header in ({},{'current':{m.OPERATOR:dict(current[m.OPERATOR],sha256='0'*64)}},
                       {'current':{m.OPERATOR:dict(current[m.OPERATOR],size_bytes=float(current[m.OPERATOR]['size_bytes']))}}):
            with self.subTest(header=header),patch.object(m.sys,'argv',['python','D']+args),\
                 patch.object(m,'read_fixed_v1',return_value=(raw,None)),\
                 patch.object(m,'load_verified_v1',side_effect=AssertionError('dependent execution')) as loader:
                with self.assertRaises((m.ResumeRefusal,KeyError)):m.native_entry_v1('D',header)
                loader.assert_not_called()

    def test_actual_c_d_bootstrap_uses_packet_bound_canonical_unchanged_d_entry(self):
        m=subject();repo=Path(__file__).resolve().parents[1]
        current={p:m.source_descriptor_v1((repo/p).read_bytes()) for p in m.SOURCE_PATHS}
        commit='a'*40
        packet={'schema_version':1,'artifact_kind':'vast_fixture_compiler_gate2_packet_v1',
            'code_commit':commit,'project_root':str(m.ROOT),'code':{p:current[p] for p in m.CODE},
            'resume_context':{'schema_version':1,'producer_commit':m.PRODUCER,'consumer_commit':commit,
            'owner_project_root':str(m.OWNER),'project_root':str(m.ROOT),'operator':current[m.OPERATOR],
            'consumer_plan':current[m.PLAN]}}
        raw=m.canonical(packet);prior=','.join(['512:'+('b'*64)]*6)
        argv=['python','D',commit,str(len(raw)),m.sha(raw),prior]
        header={'current':{m.OPERATOR:current[m.OPERATOR]}}
        import sys
        saved=dict(sys.modules);seen=[];writes=[]
        def trace(frame,event,arg):
            if event=='call' and frame.f_code.co_name=='native_main_v1' and frame.f_globals.get('__name__')=='tests.fixtures.'+Path(m.CODE[8]).stem:
                seen.append(frame.f_code)
                def no_physical(**kwargs):
                    seen.append(kwargs)
                    raise frame.f_globals['StageDRefusal']('controlled_run_boundary')
                frame.f_globals['run_d_v1']=no_physical
            return trace
        try:
            for name in ('tests','tests.fixtures')+tuple(name for name,_ in m.MODULES):sys.modules.pop(name,None)
            with tempfile.TemporaryDirectory() as directory:
                (Path(directory)/'gate2.packet.original.json').write_bytes(raw)
                with self.native_files(m,Path(directory)),patch.object(sys,'argv',argv),\
                     patch.object(sys,'stdin',SimpleNamespace(buffer=io.BytesIO(m.canonical(header)+b'\n'))),\
                     patch.object(m.os,'write',side_effect=lambda fd,b:writes.append((fd,b)) or len(b)),\
                     patch.object(m.subprocess,'Popen',side_effect=AssertionError('physical process')):
                    sys.setprofile(trace)
                    try:
                        with self.assertRaises(SystemExit) as done:exec(m.NATIVE_BOOTSTRAP,{'__name__':'controlled_cd_bootstrap'})
                    finally:sys.setprofile(None)
            self.assertEqual(done.exception.code,1)
            d=sys.modules['tests.fixtures.'+Path(m.CODE[8]).stem]
            c=sys.modules['tests.fixtures.'+Path(m.CODE[0]).stem]
            child=sys.modules['tests.fixtures.'+Path(m.CODE[9]).stem]
            self.assertIs(seen[0],d.native_main_v1.__code__);self.assertIs(child.stage,d);self.assertIs(c.component,d.recipe)
            self.assertEqual(seen[1]['project_root'],str(m.ROOT))
            self.assertEqual(seen[1]['expected_packet_sha256'],m.sha(raw))
            self.assertEqual(set(seen[1]['completion_authorities']),{'C'+str(i) for i in range(1,7)})
            self.assertEqual([fd for fd,b in writes],[2])
            self.assertEqual(json.loads(writes[0][1])['cause'],'controlled_run_boundary')
        finally:
            for name in set(sys.modules)-set(saved):sys.modules.pop(name,None)
            sys.modules.update(saved)

    def test_pipe_reader_stops_at_single_overflow_sentinel_and_keeps_unknown_remainder(self):
        m=subject();reads=[]
        class Overflow:
            def read(self,count):
                reads.append(count)
                if len(reads)>1:raise AssertionError('unbounded drain continued')
                return b'x'*count
        process=SimpleNamespace(pid=41,stdin=io.BytesIO(),stdout=Overflow(),stderr=io.BytesIO(),poll=lambda:None)
        with patch.object(m.time,'monotonic_ns',return_value=1),patch.object(m.subprocess,'Popen',return_value=process):
            with self.assertRaises(m.ResumeRefusal) as caught:m._Run(1).process(['controlled'],b'',100,8)
        self.assertEqual(reads,[9])
        facts=caught.exception.facts
        self.assertEqual(facts['stdout_bytes'],9)
        self.assertEqual(facts['stdout_sha256'],m.sha(b'x'*9))
        self.assertFalse(facts['stdout_eof']);self.assertTrue(facts['unknown_closure'])
        self.assertTrue(facts['omitted_or_unknown'])

    def test_actual_verified_buffers_have_canonical_c_d_child_identity_without_reopen(self):
        m=subject();root=Path(__file__).resolve().parents[1]
        sources={name:(root/name).read_bytes() for name in m.SOURCE_PATHS}
        desc={name:m.source_descriptor_v1(raw) for name,raw in sources.items()}
        import sys
        saved=dict(sys.modules)
        try:
            for name in ('tests','tests.fixtures')+tuple(name for name,_ in m.MODULES):sys.modules.pop(name,None)
            with patch.object(m,'read_fixed_v1',side_effect=AssertionError('source path reopened')):
                modules=m.load_verified_v1(sources,desc,root)
            comp,compiler,c,d,child=(modules[m.CODE[i]] for i in (1,2,0,8,9))
            self.assertIs(c.component,comp);self.assertIs(c.compiler,compiler)
            self.assertIs(d.recipe,comp);self.assertIs(child.stage,d);self.assertIs(child.compiler,compiler)
            self.assertIs(compiler.canonical_json_v1,modules[m.CODE[5]].canonical_json_v1)
            canonical_operator=sys.modules['tests.fixtures.'+Path(m.OPERATOR).stem]
            self.assertIsNot(canonical_operator,m)
            self.assertEqual(canonical_operator.main.__code__.co_filename,str(root/m.OPERATOR))
            self.assertIs(c.resume_terminal_v1.__globals__,c.__dict__)
            with patch.object(d,'native_main_v1',return_value=7) as native:
                self.assertEqual(c.native_main_v1(['D','a'*40,'1','b'*64,'-']),7)
                native.assert_called_once_with(['a'*40,'1','b'*64,'-'])
            self.assertEqual(sys.modules['tests'].__path__,[])
            self.assertEqual(sys.modules['tests.fixtures'].__path__,[])
        finally:
            for name in set(sys.modules)-set(saved):sys.modules.pop(name,None)
            sys.modules.update(saved)

    def test_preload_fallback_preserves_negative_git_status_and_ordered_secondary(self):
        m=subject()
        facts={'pid':23,'returncode':-15,'stdout_eof':True,'stderr_eof':True,'stdin_closed':False,
            'stdin_extent_unknown':True,'stdout_bytes':16,'stderr_bytes':4,'stdout_sha256':'a'*64,
            'stderr_sha256':'b'*64,'stdout_prefix_base64':'YQ==','stderr_prefix_base64':'Yg==',
            'causes':['deadline'],'secondary':['close_failed']}
        raw=m.terminal_v1(m.ResumeRefusal('deadline',facts));v=json.loads(raw)
        self.assertLessEqual(len(raw)+1,2048)
        known={row['path']:row['value'] for row in v['known']}
        self.assertEqual(known['returncode'],-15);self.assertEqual(known['pid'],23)
        self.assertEqual(known['stdout_sha256'],'a'*64)
        self.assertTrue(known['stdin_extent_unknown'])
        self.assertEqual(v['causes'],['deadline','close_failed'])
    def test_missing_future_or_expired_original_clock_never_starts_authentication(self):
        m=subject()
        for origin in (None,True,101,1):
            now=200000000000 if origin==1 else 100
            with self.subTest(origin=origin),patch.object(m,'windows_v1',return_value=True),\
                 patch.object(m.time,'monotonic_ns',return_value=now),\
                 patch.object(m,'authenticate_v1',side_effect=AssertionError('unexpected authentication')) as auth,\
                 patch.object(m.os,'write',return_value=1):
                self.assertEqual(m.main('a'*40,'https://github.com/lordcoudy/VAST/pull/9#issuecomment-1',
                    _original_start_ns=origin),1)
                auth.assert_not_called()
    def test_counterfeit_package_marker_is_rejected_without_getattr_or_project_execution(self):
        m=subject();seen=[]
        class Counterfeit:
            def __getattr__(self,name):seen.append(name);return True
        sources={name:b'raise AssertionError("project executed")\n' for name in m.SOURCE_PATHS}
        descriptors={name:m.source_descriptor_v1(raw) for name,raw in sources.items()}
        import sys
        with patch.dict(sys.modules,{'tests':Counterfeit()}):
            with self.assertRaises(m.ResumeRefusal) as caught:m.load_verified_v1(sources,descriptors,Path('/controlled'))
        self.assertEqual(str(caught.exception),'ambient_project_package')
        self.assertEqual(seen,[])
    def test_late_p0_return_keeps_actual_null_status_and_completion_proof(self):
        m=subject()
        result={'accepted':False,'commands':[{'returncode':None,'eof_stdout':True,'eof_stderr':True,
            'linux_child_closure':'unknown'}],'completion_record':{'write_proof':{'completed':False}}}
        p0=SimpleNamespace(collect_native_p0_v1=lambda *args,**kwargs:result)
        def late():raise m.ResumeRefusal('original_deadline')
        with self.assertRaises(m.ResumeRefusal) as caught:m.dispatch_p0_v1(p0,'controlled',{},'a'*40,late)
        self.assertEqual(str(caught.exception),'original_deadline')
        self.assertIs(caught.exception.facts['returned_p0'],result)

    def test_post_eof_late_process_and_malformed_phase_keep_known_status(self):
        m=subject();clock=[1]
        class Pipe(io.BytesIO):
            def close(self):super().close();clock[0]=20000000
        process=SimpleNamespace(pid=23,stdin=io.BytesIO(),stdout=Pipe(b'known'),stderr=io.BytesIO(),poll=lambda:0)
        with patch.object(m.time,'monotonic_ns',side_effect=lambda:clock[0]),\
             patch.object(m.subprocess,'Popen',return_value=process):
            run=m._Run(1)
            with self.assertRaises(m.ResumeRefusal) as caught:run.process(['controlled'],b'',10000000,100)
        self.assertEqual(caught.exception.facts['returncode'],0)
        self.assertTrue(caught.exception.facts['stdout_eof'])
        facts={'pid':5,'returncode':0,'stdout_eof':True,'stderr_eof':True,'stdout_bytes':7,'stdout_sha256':'a'*64}
        run=SimpleNamespace(check=lambda *args:0,work=140000000000,events=[],
            anchor={'l0':0,'w1':0,'global_deadline_ns':140000000000},
            process=lambda *args:(b'notJSON',facts))
        with self.assertRaises(m.ResumeRefusal) as caught:m.phase_v1(run,'FINAL',{})
        self.assertEqual(caught.exception.facts['process'],facts)
        self.assertEqual(run.events[0]['returncode'],0)
    def test_controlled_process_unknown_status_preserves_eof_counts_and_does_not_terminate(self):
        m=subject();clock=[0]
        def now():clock[0]+=1000000;return clock[0]
        process=SimpleNamespace(pid=23,stdin=io.BytesIO(),stdout=io.BytesIO(b'known'),stderr=io.BytesIO(),poll=lambda:None)
        with patch.object(m.time,'monotonic_ns',side_effect=now),patch.object(m.time,'sleep'),\
             patch.object(m.subprocess,'Popen',return_value=process):
            run=m._Run(1)
            with self.assertRaises(m.ResumeRefusal) as caught:
                run.process(['controlled'],b'',12000000,100)
        self.assertIsNone(caught.exception.facts['returncode'])
        self.assertTrue(caught.exception.facts['unknown_closure'])
        self.assertTrue(caught.exception.facts['stdout_eof'])
        self.assertEqual(caught.exception.facts['stdout_bytes'],5)

    def test_partial_writer_fsync_and_close_failures_keep_both_causes_and_prefix(self):
        m=subject()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'exclusive'
            realclose=os.close
            def close(fd):realclose(fd);raise OSError('close fault')
            with patch.object(m.os,'fsync',side_effect=OSError('fsync fault')),patch.object(m.os,'close',side_effect=close):
                with self.assertRaises(m.ResumeRefusal) as caught:
                    m.write_fixed_v1(path,b'known-prefix',100,lambda:None,
                        importlib.import_module('tests.fixtures.accepted_policy_fixture_compiler_component_v1'))
            self.assertEqual(path.read_bytes(),b'known-prefix')
            self.assertEqual(str(caught.exception),'fsync fault')
            self.assertEqual(caught.exception.facts['secondary'],['close_failed'])
            self.assertEqual(caught.exception.facts['written_bytes'],12)
            self.assertFalse(caught.exception.facts['close_completed'])

    def retained_world(self, directory, inflated=False):
        m,index,originals=self.inventory()
        owner=Path(directory)/'owner';owner.mkdir()
        roots={'code':owner,'f2':Path(str(owner)+'.f2'),'aux':Path(str(owner)+'.operator-originals')}
        for path in roots.values():path.mkdir(exist_ok=True)
        for row in originals['originals']:
            raw=b'controlled HTTP'
            row.update(size_bytes=len(raw),sha256=m.sha(raw))
            (roots['f2']/row['relative_path']).write_bytes(raw)
        for slot,n in enumerate(dict(index['historical_bindings'])['producer465'][:11]):
            raw=('controlled export '+str(slot)).encode()
            index['source_versions'][n][2:]=[len(raw),m.sha(raw)]
            path=roots['code']/(m.CODE[slot] if slot<10 else 'physical-plan.v8.md')
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        for row in index['native_extras']:
            raw=(m.canonical(originals) if row[1]=='f2.originals.v1.json' else
                 b'' if 'stderr.original' in row[1] else ('controlled '+row[1]).encode())
            row[2:]=[len(raw),m.sha(raw)]
            path=roots[row[0]]/row[1];path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        files,dirs=m.native_table_v1(index,originals)
        slots=[];groups=[]
        for group,path,_,_ in files+[(g,p,None,None) for g,p in dirs]:
            s=(roots[group]/path).lstat();identity=[s.st_dev,s.st_mode,s.st_uid,s.st_gid,s.st_nlink]
            if identity not in groups:groups.append(identity)
            slots.append([groups.index(identity),s.st_ino,s.st_blocks*512,s.st_mtime_ns,s.st_ctime_ns,None])
        diagnostic={'all_expected_matched':True,'observation_complete':True,'manifest_sha256':m.MANIFEST_SHA,
            'groups':groups,'slots':slots+[[0,1,0,0,0,None]]*16}
        held={'tool_result':{'exit_code':0,'output':m.canonical(diagnostic).decode()},'manifest_sha256':m.MANIFEST_SHA,'padding':''}
        held['padding']='x'*(8645-len(m.canonical(held)))
        heldraw=m.canonical(held)
        oldhash=m.sha
        def digest(raw):
            if raw==b'x'*6392:return 'a901390e93fb9fb2be6fa88f6c81b41286681251ddfc652773b0b9bee489f476'
            if raw==b'y'*3609:return '7fc5ef24fb7d226b33a88cab6a57643ef8c86eb774f99cb6e655bb3c69663079'
            return oldhash(raw)
        def read(path,cap):
            path=Path(path)
            if str(path).endswith('held-tool-return.original.json'):return heldraw,None,12288
            if '.driver.stdout.original' in str(path):return b'',None,0
            if '.driver.stderr.original' in str(path):return b'x'*6392,None,16384 if inflated else 8192
            if path.name=='gate2-successor-465a.outer-tool.original.json':return b'y'*3609,None,4096
            raw,s=m.read_fixed_v1(path,cap);return raw,s,s.st_blocks*512
        return m,index,owner,heldraw,digest,read

    def test_retained_70_nodes_include_both_old_outer_forms_and_refuse_capture_inflation(self):
        for inflated in (False,True):
            with tempfile.TemporaryDirectory() as directory:
                m,index,owner,held,digest,read=self.retained_world(directory,inflated)
                with patch.object(m,'OWNER',owner),patch.object(m,'DIAGNOSTIC_SHA',hashlib.sha256(held).hexdigest()),\
                     patch.object(m,'sha',side_effect=digest),patch.object(m,'_actual_read',side_effect=read):
                    if inflated:
                        with self.assertRaises(m.ResumeRefusal):m.verify_retained_v1(Path(directory),index=index)
                    else:
                        result=m.verify_retained_v1(Path(directory),index=index)
                        self.assertEqual(result['node_count'],70)
                        self.assertEqual(result['windows_capture_quote_bytes'],32768)
    def inventory(self):
        m=subject()
        root=Path(__file__).resolve().parents[1]
        index=json.loads((root/m.INDEX).read_bytes())
        originals={'schema_version':1,'originals':[{'relative_path':'RPC%02d.%s.original'%(n,role),
            'size_bytes':17,'sha256':'a'*64} for n in range(1,20) for role in ('reply','request')]}
        return m,index,originals

    def test_native_table_derives_exact_63_files_and_7_directories_without_windows_slots(self):
        m,index,originals=self.inventory()
        files,dirs=m.native_table_v1(index,originals)
        self.assertEqual(len(files),63);self.assertEqual(len(dirs),7)
        self.assertEqual(sum(g=='code' for g,_,_,_ in files),13)
        self.assertFalse(any('setup_v1' in row[1] or 'capture_v1' in row[1] for row in files))
        for mutate in (lambda: originals['originals'][0].update(relative_path='../outside'),
                       lambda: index['native_extras'][0].__setitem__(0,'arbitrary')):
            mutate()
            with self.assertRaises(m.ResumeRefusal): m.native_table_v1(index,originals)

    def test_windows_positive_loader_executes_fixed_authenticated_closure_without_initializer(self):
        m = subject()
        sources = {name: b'VALUE=17\n' for name in m.SOURCE_PATHS}
        sources[m.OPERATOR] = Path(m.__file__).read_bytes()
        for name in (m.CODE[1],m.CODE[7]): sources[name] = b'VALUE=17\n'
        descriptors = {name:m.source_descriptor_v1(raw) for name,raw in sources.items()}
        import sys
        saved = dict(sys.modules)
        try:
            for name in ('tests','tests.fixtures') + tuple(name for name,_ in m.MODULES): sys.modules.pop(name,None)
            with patch.object(m,'windows_v1',return_value=True,create=True):
                modules = m.load_verified_v1(sources,descriptors,Path('/controlled'))
            self.assertEqual(set(modules),{relative for _,relative in m.MODULES})
            self.assertEqual(modules[m.CODE[7]].VALUE,17)
        finally:
            for name in set(sys.modules)-set(saved): sys.modules.pop(name,None)
            sys.modules.update(saved)

    def test_canonical_operator_executes_authenticated_bytes_not_existing_own_globals(self):
        m=subject()
        sources={name:b'VALUE=17\n' for name in m.SOURCE_PATHS}
        sources[m.OPERATOR]=b'VALUE="fresh reviewed bytes"\n'
        descriptors={name:m.source_descriptor_v1(raw) for name,raw in sources.items()}
        import sys
        saved=dict(sys.modules)
        try:
            for name in ('tests','tests.fixtures')+tuple(name for name,_ in m.MODULES):sys.modules.pop(name,None)
            with patch.object(m,'windows_v1',return_value=True):
                m.load_verified_v1(sources,descriptors,Path('/controlled'))
            canonical_operator=sys.modules['tests.fixtures.'+Path(m.OPERATOR).stem]
            self.assertEqual(canonical_operator.VALUE,'fresh reviewed bytes')
            self.assertIsNot(canonical_operator,m)
        finally:
            for name in set(sys.modules)-set(saved):sys.modules.pop(name,None)
            sys.modules.update(saved)
    def test_ready_ack_mapping_deducts_observed_roundtrip_without_launch_credit(self):
        m = subject()
        self.assertEqual(m.map_deadline_v1(100, 70, 200), 230)
        for values in ((100, 200, 200), (True, 70, 200), (100, 201, 200)):
            with self.subTest(values=values), self.assertRaises(m.ResumeRefusal):
                m.map_deadline_v1(*values)


    def test_complete_tool_collection_keeps_all_frames_call_and_escaped_output(self):
        m = subject()
        call = {'cmd': 'fixed ' + '\\"\n' * 15, 'yield_time_ms': 1000}
        frames = [{'output': 'partial\u0401', 'session_id': 7}] * 5 + [{'output': 'final', 'exit_code': 0}]
        raw = m.outer_collection_v1(call, frames)
        self.assertEqual(json.loads(raw), {'call': call, 'frames': frames})
        self.assertIn(b'\\u0401', raw)
        with self.assertRaises(m.ResumeRefusal):
            m.outer_collection_v1(call, frames + [frames[-1]])
        with self.assertRaises(m.ResumeRefusal):
            m.outer_collection_v1(call, [{'output': '\u0401' * 2200, 'exit_code': 0}])

    def test_terminal_preserves_known_null_status_and_never_exceeds_2048(self):
        m = subject()
        error = m.ResumeRefusal('first', {'returncode': None, 'stdout_eof': True,
            'stderr_eof': False, 'close_completed': False, 'secondary': ['write', 'close'],
            'payload': '\U0001f600' * 10000})
        raw = formatter()(error=error)
        self.assertLessEqual(len(raw) + 1, 2048)
        value = json.loads(raw)
        self.assertFalse(value['completed'])
        self.assertEqual(value['causes'][0], 'first')
        self.assertIn(None, [row['value'] for row in value['known']])
        self.assertTrue(value['omitted_or_unknown'])

    def test_actual_nested_p0_failure_preserves_status_eof_and_extent_facts(self):
        m = subject()
        facts = {'returned_p0':{'commands':[{'returncode':None,'eof_stdout':True,
            'eof_stderr':True,'normal_exit':False,'forced_parent_termination':False,
            'linux_child_closure':'unknown','stdout':{'persistence':{'write_extent_unknown':True,
            'close_completed':False}}}], 'causes':['deadline_late','persistence_incomplete'],
            'padding':'x'*40000}}
        value=json.loads(formatter()(error=m.ResumeRefusal('p0_native_refused',facts)))
        keys={row['path'].split('/')[-1]:row['value'] for row in value['known']}
        self.assertIsNone(keys['returncode'])
        self.assertTrue(keys['eof_stdout']);self.assertTrue(keys['eof_stderr'])
        self.assertEqual(keys['linux_child_closure'],'unknown')
        self.assertTrue(keys['write_extent_unknown'])
        self.assertEqual(value['causes'],['p0_native_refused','deadline_late','persistence_incomplete'])

    def test_loader_authenticates_entire_closure_before_executing_any_project_byte(self):
        m = subject()
        sources = {name: b'raise AssertionError("unreviewed executed")\n' for name in m.SOURCE_PATHS}
        descriptors = {name: m.source_descriptor_v1(raw) for name, raw in sources.items()}
        descriptors[m.CODE[0]]['sha256'] = '0' * 64
        with self.assertRaises(m.ResumeRefusal) as caught:
            m.load_verified_v1(sources, descriptors, Path('/controlled'))
        self.assertEqual(str(caught.exception), 'source_binding')


# D22 additive construction only. These pure lexical definitions are copied from
# authenticated D17 source22845/29a4fb53fe3125e814236913b9ab457585077c7ddf4649129959df16e3976ea6.
# No historical helper entry, acquired tool, generated program or operational path runs.
def d22_sha(raw):return hashlib.sha256(raw).hexdigest()

def d22_canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')

D22_PREFIX="if(Object.hasOwn(globalThis,'gate2Resume'))throw Error('state_exists');\nvar g2p=globalThis.performance;if(!g2p||typeof g2p.now!=='function')throw Error('monotonic_unavailable');\nvar g2t=g2p.now();if(!Number.isFinite(g2t)||g2t<0||g2t>Number.MAX_SAFE_INTEGER-150000)throw Error('original_clock');\n"

D22_IMPORTS="var {spawn:g2s}=await import('node:child_process'),{createHash:g2h}=await import('node:crypto'),{brotliCompressSync:g2c}=await import('node:zlib'),g2fs=await import('node:fs/promises');var g2py=__COMMON__;"

def d22_build_plain(data):
 import base64,zlib
 raw=d22_canonical(data);packed=zlib.compress(raw,9);encoded=base64.b64encode(packed).decode('ascii')
 digest=d22_sha(raw)
 decoder=("var g2before=g2t;function g2dataGate(){let n=g2p.now();if(!Number.isFinite(n)||n<g2before||n>=g2t+140000)throw Error('data_deadline');g2before=n;}\n"
  "var {inflateSync:g2inflate,brotliCompressSync:g2c}=await import('node:zlib');g2dataGate();\n"
  "var {createHash:g2h}=await import('node:crypto');g2dataGate();\n"
  "var g2packed="+json.dumps(encoded)+";if(g2packed.length!=="+str(len(encoded))+"||!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(g2packed))throw Error('data_input');\n"
  "var g2compressed=Buffer.from(g2packed,'base64');if(g2compressed.length!=="+str(len(packed))+")throw Error('data_input');g2dataGate();\n"
  "var g2raw=g2inflate(g2compressed,{maxOutputLength:"+str(len(raw))+"});g2dataGate();if(g2raw.length!=="+str(len(raw))+"||!g2raw.every(v=>v<128)||g2h('sha256').update(g2raw).digest('hex')!=="+json.dumps(digest)+")throw Error('data_binding');\n"
  "var g2data=JSON.parse(g2raw.toString('latin1'));g2dataGate();\n"
  "if(g2data===null||typeof g2data!=='object'||Array.isArray(g2data)||Object.keys(g2data).sort().join(',')!=='approval,commit,common,fields,pipe_fields,root,setup_head,setup_tail,sources'||JSON.stringify(g2data)!==g2raw.toString('latin1'))throw Error('data_shape');\n"
  "if(!['approval','commit','common','root','setup_head','setup_tail'].every(k=>typeof g2data[k]==='string')||!/^([0-9a-f]{40})$/.test(g2data.commit)||!g2data.approval.startsWith('https://github.com/lordcoudy/VAST/pull/9#issuecomment-')||! /^[0-9]{1,20}$/.test(g2data.approval.slice(54))||!Array.isArray(g2data.fields)||g2data.fields.length!=="+str(len(NODE_FIELDS))+"||!g2data.fields.every(k=>typeof k==='string')||!Array.isArray(g2data.pipe_fields)||g2data.pipe_fields.length!=="+str(len(NODE_PIPE_FIELDS))+"||!g2data.pipe_fields.every(k=>typeof k==='string')||!Array.isArray(g2data.sources)||g2data.sources.length!==2||!g2data.sources.every(r=>Array.isArray(r)&&r.length===2&&typeof r[0]==='string'&&r[1]!==null&&typeof r[1]==='object'&&!Array.isArray(r[1])&&Object.keys(r[1]).sort().join(',')==='git_blob,sha256,size_bytes'&&Number.isSafeInteger(r[1].size_bytes)&&r[1].size_bytes>0&&r[1].size_bytes<=32768&&/^([0-9a-f]{64})$/.test(r[1].sha256)&&/^([0-9a-f]{40})$/.test(r[1].git_blob)))throw Error('data_shape');g2dataGate();\n")
 body=NODE_CONTROLLER[len(D22_PREFIX):].replace(D22_IMPORTS,"var {spawn:g2s}=await import('node:child_process');g2dataGate();var g2fs=await import('node:fs/promises');g2dataGate();var g2py=g2data.common;")
 replacements={'__VALIDATORS__':NODE_VALIDATORS,'__ROOT__':'g2data.root','__COMMON__':'g2data.common','__SETUP_HEAD__':'g2data.setup_head','__SETUP_TAIL__':'g2data.setup_tail','__COMMIT__':'g2data.commit','__APPROVAL__':'g2data.approval','__WRITER_EXPR__':"''",'__FIELDS__':'g2data.fields','__PIPE_FIELDS__':'g2data.pipe_fields','__SOURCES__':'g2data.sources'}
 for old,new in replacements.items():body=body.replace(old,new)
 body=body.replace('last:g2t,calls:0','last:g2before,calls:0')
 assert not any(key in body for key in replacements)
 code=D22_PREFIX+decoder+body
 assert code.startswith(D22_PREFIX) and 'eval(' not in code and 'Function(' not in code and 'vm.' not in code
 return code,{'data_bytes':len(raw),'data_sha256':d22_sha(raw),'compressed_data_bytes':len(packed),'base64_data_bytes':len(encoded),'candidate_bytes':len(code.encode('ascii')),'candidate_sha256':d22_sha(code.encode('ascii')),'original_prefix_bytes':295}

D22_OPS=sorted(['===','!==','>>>','**=','&&=','||=','??=','=>','==','!=','<=','>=','++','--','&&','||','??','?.','+=','-=','*=','/=','%=','<<','>>','**','...'],key=len,reverse=True)

D22_NON_END={'return','throw','new','typeof','void','delete','in','instanceof','case','await','yield','else','of'}

def d22_lex(source):
 out=[];i=0;n=len(source)
 while i<n:
  if source[i].isspace():i+=1;continue
  start=i;ch=source[i]
  if ch in "'\"":
   quote=ch;i+=1
   while i<n:
    if source[i]=='\\':i+=2;continue
    if source[i]==quote:i+=1;break
    if source[i] in '\r\n':raise AssertionError('unescaped string newline')
    i+=1
   else:raise AssertionError('unterminated string')
   kind='string'
  elif ch=='`':raise AssertionError('unsupported template literal')
  elif ch=='/' and source[i:i+2] in ('//','/*'):raise AssertionError('unexpected comment in fixed candidate')
  elif ch=='/' and (not out or out[-1][0]=='id' and out[-1][1] in D22_NON_END or out[-1][0]=='punct' and out[-1][1] not in (')',']','}','++','--')):
   i+=1;group=False
   while i<n:
    if source[i]=='\\':i+=2;continue
    if source[i]=='[':group=True
    elif source[i]==']':group=False
    elif source[i]=='/' and not group:i+=1;break
    if source[i] in '\r\n':raise AssertionError('regex newline')
    i+=1
   else:raise AssertionError('unterminated regex')
   while i<n and source[i].isalpha():i+=1
   kind='regex'
  elif ch.isalpha() or ch in '_$':
   i+=1
   while i<n and (source[i].isalnum() or source[i] in '_$'):i+=1
   kind='id'
  elif ch.isdigit():
   i+=1
   while i<n and (source[i].isalnum() or source[i] in '._'):i+=1
   kind='number'
  else:
   op=next((v for v in D22_OPS if source.startswith(v,i)),None)
   if op:i+=len(op)
   elif ch in '{}[]().,:;?+-*/%!~&|^<>=':i+=1
   else:raise AssertionError('unsupported token '+repr(ch))
   kind='punct'
  out.append((kind,source[start:i],start,i))
 return out

def d22_pairs(tokens):return [(kind,text) for kind,text,*_ in tokens]

def d22_join_tokens(tokens,original):
 result=[];last=None
 for token in tokens:
  kind,text,start,end=token
  if last:
   gap=original[last[3]:start] if start>=last[3] else ''
   if '\n' in gap:result.append('\n')
   elif ((last[0] in ('id','number') and kind in ('id','number')) or last[0]=='regex' and kind in ('id','number') or last[0]=='number' and text.startswith('.') or last[1][-1:]=='/' and text[:1] in ('/','*') or any((last[1]+text).startswith(op) and op!=last[1] for op in D22_OPS)):
    result.append(' ')
  result.append(text);last=token
 value=''.join(result)
 assert d22_pairs(d22_lex(value))==d22_pairs(tokens),'lexical rejoin changed token identities'
 return value

D22_PROPERTY_ALLOWLIST=frozenset(['size_bytes','stdin_extent_unknown','unknown_closure','physical_acceptance','returncode','source_facts','open_completed','close_completed','read_bytes','read_sha256','stdin_attempted','stdin_bytes','stdin_sha256','stdin_finished','stdin_closed','stdin_failed','remainder_unknown','terminal_observed_ms','isSafeInteger','MAX_SAFE_INTEGER','isFinite','isArray','replaceAll','charCodeAt','padStart','codePointAt','toString','getOwnPropertyDescriptor','getPrototypeOf'])

D22_PRIVATE_MAP={'g2dataGate':'J','g2before':'L','g2packed':'P','g2compressed':'C','g2raw':'R','g2data':'D','epoch':'E','gate':'G','first':'F','secondary':'S','snapshot':'W','observed':'O','encoding':'N','unknown':'U','pipes':'I','text':'T','raw':'V'}

def d22_transform_body(source,literal_allowlist,properties,aliases):
 old=d22_lex(source);new=[];i=0;scope=[];changes={'literal_refs':0,'computed_member_keys':0,'private_refs':0,'reified_shorthands':0}
 while i<len(old):
  token=old[i];kind,text,start,end=token;previous=old[i-1][1] if i else '';following=old[i+1][1] if i+1<len(old) else ''
  if text=='{':scope.append(('object' if previous in ('=','return','(',',','[',':','?','var','let','const') else 'block','}'))
  elif text in ('(','['):scope.append(('other',')' if text=='(' else ']'))
  elif text in ('}',')',']'):
   assert scope and scope[-1][1]==text,(text,scope)
   scope.pop()
  if text in ('.','?.') and i+1<len(old) and old[i+1][0]=='id' and old[i+1][1] in properties:
   assert text=='.','optional access not supported by fixed computed-key transform'
   key=old[i+1][1];replacement='['+aliases[key]+']'
   new.extend((k,v,start,old[i+1][3]) for k,v,*_ in d22_lex(replacement));changes['computed_member_keys']+=1;i+=2;continue
  if kind=='string' and '\\' not in text[1:-1] and text[1:-1] in literal_allowlist:
   new.append(('id',aliases[text[1:-1]],start,end));changes['literal_refs']+=1
  elif kind=='id' and text in D22_PRIVATE_MAP and previous not in ('.','?.'):
   object_key=scope and scope[-1][0]=='object' and previous in ('{',',')
   if object_key and following==':':new.append(token)
   elif object_key and following in (',','}'):
    replacement=text+':'+D22_PRIVATE_MAP[text]
    new.extend((k,v,start,end) for k,v,*_ in d22_lex(replacement));changes['private_refs']+=1;changes['reified_shorthands']+=1
   else:new.append(('id',D22_PRIVATE_MAP[text],start,end));changes['private_refs']+=1
  else:new.append(token)
  i+=1
 assert not scope
 return d22_join_tokens(new,source),changes

def d22_shorten_private_prefix(source):
 tokens=d22_lex(source);changed=[]
 for i,(kind,text,start,end) in enumerate(tokens):
  previous=tokens[i-1][1] if i else '';following=tokens[i+1][1] if i+1<len(tokens) else ''
  if kind=='id' and text in D22_PRIVATE_MAP and previous not in ('.','?.') and following!=':':text=D22_PRIVATE_MAP[text]
  changed.append((kind,text,start,end))
 return d22_join_tokens(changed,source)


def d22_phase_initial_v1(deadline):
    """One baseline_all derivation in RAM; a source-width result is never acceptance."""
    import base64,time,zlib
    from tests.test_accepted_policy_fixture_compiler_gate2_resume_caller_v1 import d22_compress_data_v1
    def gate():
        if time.monotonic() >= deadline - 5:raise RuntimeError('d22_construction_deadline')
    gate()
    root=Path(__file__).resolve().parents[1]
    rows=[]
    fixtures=(('tests/fixtures/accepted_policy_fixture_compiler_component_v1.py',32732,
               '329fb13f2c6dcee0872e5a29ec1fd769dc6e57ce92ee1076fef6737f1da86d88',
               '5a342c2c2efa44aa5add3f91ae94518c143acece'),
              ('tests/fixtures/accepted_policy_fixture_compiler_gate2_resume_v1.py',32739,
               '5fd7d2d6ee62ff584d2a4662757ca804a3d3300d30bb966319901870c4c85670',
               'cc9b6a1b7e6e6ff2f9b750ea67b20cf7213d09b0'))
    for name,size,digest,blob in fixtures:
        gate()
        with root.joinpath(name).open('rb') as handle:raw=handle.read(32769)
        gate()
        actual_blob=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        if (len(raw),d22_sha(raw),actual_blob)!=(size,digest,blob):
            raise RuntimeError('d22_fixture_binding')
        rows.append(['C:/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/'+name,
                     {'size_bytes':len(raw),'sha256':d22_sha(raw),
                      'git_blob':actual_blob}])
    data={'approval':'https://github.com/lordcoudy/VAST/pull/9#issuecomment-1234567890',
          'commit':hashlib.sha1(b'controlled-current-review').hexdigest(),
          'common':NODE_SHARED_PYTHON,'fields':list(NODE_FIELDS),'pipe_fields':list(NODE_PIPE_FIELDS),
          'root':'/home/s-a-balashov/work/vast-fixture-compiler-gate2-465ab7986939c67ae3594344ee3b6266cd2abd7a-01/r1',
          'setup_head':NODE_SETUP_HEAD,'setup_tail':NODE_SETUP_TAIL,'sources':rows}
    plain,_=d22_build_plain(data)
    marker="var {spawn:g2s}=await import('node:child_process');"
    ts=d22_lex(plain[plain.index(marker):])
    literals=frozenset(t[1][1:-1] for t in ts
                      if t[0]=='string' and '\\' not in t[1][1:-1] and len(t[1][1:-1])>=8)
    properties={t[1] for i,t in enumerate(ts) if t[0]=='id' and i and ts[i-1][1] in ('.','?.')
                and t[1] in D22_PROPERTY_ALLOWLIST}
    pool=sorted(literals|properties)
    if len(pool)!=74 or len(literals)!=53:raise RuntimeError('d22_original_pool')
    aliases={v:('$'+chr(97+i) if i<26 else '$'+chr(65+i-26) if i<52 else '$x'+str(i))
             for i,v in enumerate(pool)}
    if set(aliases.values()) & {t[1] for t in d22_lex(plain) if t[0]=='id'}:
        raise RuntimeError('d22_alias_collision')
    data={**data,'strings':pool};raw=d22_canonical(data)
    if len(raw)!=8369 or d22_sha(raw)!='7ecdc75899f600d71c728639ac33eb3090eb08d99fb85d914a9def761733a23c':
        raise RuntimeError('d22_original_data_binding')
    gate();packed,compression=d22_compress_data_v1(raw,deadline);gate()
    if len(packed)!=2948 or d22_sha(packed)!='524b55cec5a004998fe0d0fee591d209ef0a52e07897d10ddc140f2debf4dbd6':
        raise RuntimeError('d22_original_compressed_data_binding')
    encoded=base64.b64encode(packed).decode('ascii')
    original,_=d22_build_plain(data);at=original.index(marker)
    pre=original[len(D22_PREFIX):at]
    oldkeys="'approval,commit,common,fields,pipe_fields,root,setup_head,setup_tail,sources'"
    if pre.count(oldkeys)!=1:raise RuntimeError('d22_data_shape_site')
    pre=pre.replace(oldkeys,"'approval,commit,common,fields,pipe_fields,root,setup_head,setup_tail,sources,strings'")
    pre+="if(!Array.isArray(g2data.strings)||g2data.strings.length!==74||!g2data.strings.every(v=>typeof v==='string'&&v.length<=512))throw Error('data_strings');\nconst["+','.join(aliases[v] for v in pool)+"]=g2data.strings;\n"
    zpacked=zlib.compress(raw,9);previous=base64.b64encode(zpacked).decode('ascii')
    pre=pre.replace(json.dumps(previous),json.dumps(encoded)).replace('g2packed.length!=='+str(len(previous)),
                'g2packed.length!=='+str(len(encoded))).replace('g2compressed.length!=='+str(len(zpacked)),
                'g2compressed.length!=='+str(len(packed))).replace('inflateSync:g2inflate','brotliDecompressSync:g2inflate')
    baseline_body=original[at:]
    def render(body):
        transformed,_=d22_transform_body(body,literals,properties,aliases)
        return D22_PREFIX+d22_shorten_private_prefix(pre)+'\n'+transformed
    historical=render(baseline_body)
    if len(historical)!=17014 or d22_sha(historical.encode('ascii'))!='e61180deba849f94f1cf223b4d42a217eb5d2ef664d81d1da3e0d11fd8b10d08':
        raise RuntimeError('d22_historical_source_binding')
    validators=NODE_VALIDATORS.replace('__COMMIT__','g2data.commit').replace('__ROOT__','g2data.root')
    early="g2.commit=g2data.commit;g2.root=g2data.root;\ng2.need=(v,c)=>{if(!v)throw Error(c);};\n"
    feature="g2.need(typeof JSON.rawJSON==='function'&&JSON.parse('1',(k,v,c)=>c?.source)==='1','parse_source_feature');\n"
    capture="Object.defineProperty(g2,'_gate2CreateHash',{value:g2h,enumerable:false,writable:false,configurable:false});\n"
    old_output='g2.last_setup=snapshot;g2.setup_success=false;try{g2.setupView(snapshot);g2.setup_success=true;}catch(e){g2.setup_refusal=String(e.message);}'
    new_output='g2.last_setup=snapshot;g2.setup_success=null;'
    if baseline_body.count(validators)!=1 or validators.count(early)!=1 or validators.count(feature)!=1 or baseline_body.count(old_output)!=1:
        raise RuntimeError('d22_phase_source_sites')
    deferred=validators.replace(early,'').replace(feature,'')
    phase_body=baseline_body.replace(validators,early+feature+capture).replace(old_output,new_output)
    inverse_body=phase_body.replace(early+feature+capture,validators).replace(new_output,old_output)
    if inverse_body!=baseline_body:raise RuntimeError('d22_inverse_source')
    initial=render(phase_body);restored=render(inverse_body);gate()
    escaped=len(d22_canonical(initial));fit=escaped<=12288
    facts={'kind':'d22_initial_source_only_v1','source_bytes':len(initial),
           'source_sha256':d22_sha(initial.encode('ascii')),'escaped_source_bytes':escaped,
           'historical_bytes':len(historical),'historical_sha256':d22_sha(historical.encode('ascii')),
           'prefix_bytes':len(D22_PREFIX),'prefix_sha256':d22_sha(D22_PREFIX.encode('ascii')),
           'canonical_data_bytes':len(raw),'canonical_data_sha256':d22_sha(raw),
           'compressed_data_bytes':len(packed),'compressed_data_sha256':d22_sha(packed),
           'pool_entries':len(pool),'literal_entries':len(literals),
           'deferred_definition_bytes':len(deferred),'deferred_definition_sha256':d22_sha(deferred.encode('ascii')),
           'exact_inverse_source':restored==historical,'source_contribution_fits':fit,
           'source_only_over_cap_by':max(0,escaped-12288),'complete_geometry_qualified':False,
           'behavior_conformance_complete':False,'finalizer_implemented':False,
           'generated_operational_program_executed':False,'generated_full_subject_files_written':False,
           'status':'UNQUALIFIED' if fit else 'HOLD_SOURCE_CONTRIBUTION_OVER_CAP',
           'task_2_10_complete':False,'compression':compression}
    if len(d22_canonical(facts))>32768:raise RuntimeError('d22_metadata_bound')
    return initial,historical,{'phase_body':phase_body,'restored':restored,'deferred':deferred},facts


class D22StaticPhaseConstructionTests(unittest.TestCase):
    """The first risk slice proves derivation and width, not operational fitness."""

    def test_changed_fixture_or_data_refuses_before_compression(self):
        import time
        from tests import test_accepted_policy_fixture_compiler_gate2_resume_caller_v1 as caller
        requests=[]
        class Sentinel(io.BytesIO):
            def read(self, size=-1):
                requests.append(size)
                return super().read(size)
        with patch.object(Path,'open',return_value=Sentinel(b'x'*32770)), \
                patch.object(caller,'d22_compress_data_v1') as compress:
            with self.assertRaisesRegex(RuntimeError,'d22_fixture_binding'):
                d22_phase_initial_v1(time.monotonic()+20)
        self.assertEqual(compress.call_count,0)
        self.assertTrue(bool(requests) and all(0<size<=32769 for size in requests),
                        'fixture input must be bounded before allocation')
        with patch.dict(globals(),NODE_SHARED_PYTHON=NODE_SHARED_PYTHON+' '), \
                patch.object(caller,'d22_compress_data_v1') as compress:
            with self.assertRaisesRegex(RuntimeError,'d22_original_data_binding'):
                d22_phase_initial_v1(time.monotonic()+20)
        self.assertEqual(compress.call_count,0)

    def test_phase_initial_preserves_baseline_and_unclassified_setup(self):
        import time
        initial, historical, parts, facts = d22_phase_initial_v1(
            globals().get('D22_TEST_DEADLINE', time.monotonic() + 295))
        self.assertEqual(len(historical.encode('ascii')), 17014)
        self.assertEqual(hashlib.sha256(historical.encode('ascii')).hexdigest(),
                         'e61180deba849f94f1cf223b4d42a217eb5d2ef664d81d1da3e0d11fd8b10d08')
        self.assertTrue(parts['restored'] == historical, 'historical inverse source differs')
        self.assertEqual(initial[:295], NODE_CONTROLLER[:295])
        early = "g2.need(typeof JSON.rawJSON==='function'&&JSON.parse('1',(k,v,c)=>c?.source)==='1','parse_source_feature');"
        body = parts['phase_body']
        self.assertLess(body.index(early), body.index("Object.defineProperty(g2,'_gate2CreateHash'"))
        self.assertLess(body.index("Object.defineProperty(g2,'_gate2CreateHash'"), body.index('await g2.auth();'))
        self.assertFalse('g2.setupView=' in body, 'setup validator was not deferred')
        self.assertFalse('function gate2Ascii(' in body, 'canonical validator was not deferred')
        self.assertFalse('g2.setup_success=false;try{g2.setupView(snapshot);' in body,
                         'initial snapshot was classified')
        self.assertTrue('g2.last_setup=snapshot;g2.setup_success=null;' in body,
                        'unclassified initial snapshot is missing')
        self.assertEqual(facts['pool_entries'], 74)
        escaped = len(json.dumps(initial, ensure_ascii=True, separators=(',', ':')).encode('ascii'))
        self.assertEqual(facts['escaped_source_bytes'], escaped)
        self.assertEqual(facts['source_contribution_fits'], escaped <= 12288)
        self.assertFalse(facts['complete_geometry_qualified'])
        self.assertFalse(facts['behavior_conformance_complete'])
        report = json.dumps(facts, sort_keys=True, separators=(',', ':'))
        self.assertLessEqual(len(report.encode('ascii')), 32768)
        print('D22_INITIAL_SOURCE_ONLY', report)


D23_WIRE_CODEC = r"""function gate2WireBudget(now,cause,end=Infinity){
 let origin=null,last=null,limit=null,units=0,failed=false;
 function stop(){failed=true;throw Error(cause);}
 function guard(){
  if(failed)throw Error(cause);
  let n;try{n=now();}catch{stop();}
  if(typeof n!=='number'||!Number.isFinite(n)||last!==null&&n<last)stop();
  if(origin===null){
   if(typeof end!=='number'||!Number.isFinite(end)&&end!==Infinity)stop();
   origin=n;limit=Math.min(n+5000,end);
  }
  last=n;if(n>=limit)stop();units=0;return n;
 }
 guard.work=()=>{if(failed)throw Error(cause);if(origin===null||units===256)guard();units++;};
 guard.phase=fn=>{
  guard();let value,error,threw=false;
  try{value=fn();}catch(e){error=e;threw=true;}
  guard();if(threw)throw error;return value;
 };
 return guard;
}
function gate2WireInput(wire){
 if(typeof wire!=='string'||wire.length<1||wire.length>12288||/[^\x20-\x7e]/.test(wire))throw Error('selected_wire_input');
 return wire;
}
function gate2WireDecode(wire,tag,sha,canon,guard){
 gate2WireInput(wire);
 const x=guard.phase(()=>{try{return JSON.parse(wire);}catch{throw Error('selected_wire_shape');}});
 guard.phase(()=>{
  if(!x||typeof x!=='object'||Array.isArray(x)||Object.keys(x).sort().join(',')!=='encoding,expanded_sha256,expanded_size_bytes,payload'||
   tag!=='gate2-selected-lz77-v1'&&tag!=='gate2-observed-lz77-v1'||x.encoding!==tag||
   typeof x.payload!=='string'||x.payload.length>12288||/[^\x20-\x7e]/.test(x.payload)||
   typeof x.expanded_sha256!=='string'||!/^[0-9a-f]{64}$/.test(x.expanded_sha256)||!Number.isSafeInteger(x.expanded_size_bytes))throw Error('selected_wire_shape');
 });
 const spelling=guard.phase(()=>{try{return canon(x,12288);}catch{throw Error('selected_wire_shape');}});
 if(spelling!==wire)throw Error('selected_wire_shape');
 if(x.expanded_size_bytes<1||x.expanded_size_bytes>32768)throw Error('selected_wire_bound');
 const text=guard.phase(()=>{
  const output=[],payload=x.payload;let at=0;
  function index(c){let n=c.charCodeAt(0);return n>=65&&n<=90?n-65:n>=97&&n<=122?n-71:n>=48&&n<=57?n+4:n===43?62:n===47?63:-1;}
  function append(c){guard.work();if(output.length>=x.expanded_size_bytes||output.length>=32768)throw Error('selected_wire_expansion');output.push(c);}
  while(at<payload.length){
   guard.work();const c=payload[at++];
   if(c!=='~'){append(c);continue;}
   if(at>=payload.length)throw Error('selected_wire_token');
   if(payload[at]==='~'){at++;append('~');continue;}
   if(at+3>payload.length)throw Error('selected_wire_token');
   const a=index(payload[at]),b=index(payload[at+1]),z=index(payload[at+2]);at+=3;
   if(a<0||b<0||z<0)throw Error('selected_wire_token');
   const distance=1+64*a+b,length=5+z;
   if(distance>4096||distance>output.length)throw Error('selected_wire_token');
   for(let n=0;n<length;n++)append(output[output.length-distance]);
  }
  return output.join('');
 });
 if(text.length!==x.expanded_size_bytes)throw Error('selected_wire_binding');
 const digest=guard.phase(()=>sha(text));
 if(digest!==x.expanded_sha256)throw Error('selected_wire_binding');
 const value=guard.phase(()=>{try{return JSON.parse(text);}catch{throw Error('selected_wire_binding');}});
 const recovered=guard.phase(()=>{try{return canon(value,32768);}catch{throw Error('selected_wire_binding');}});
 if(recovered!==text)throw Error('selected_wire_binding');
 return {text,value};
}
function gate2WireEncode(text,tag,sha,canon,guard){
 // ROOT canonicalizes each independently captured original before this primitive.
 if(typeof text!=='string'||text.length<1||text.length>32768||/[^\x20-\x7e]/.test(text))throw Error('selected_wire_input');
 const digest=guard.phase(()=>{
  if(tag!=='gate2-selected-lz77-v1'&&tag!=='gate2-observed-lz77-v1')throw Error('selected_wire_shape');
  const value=sha(text);if(typeof value!=='string'||!/^[0-9a-f]{64}$/.test(value))throw Error('selected_wire_shape');return value;
 });
 const payload=guard.phase(()=>{
  const alphabet='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/',dictionary=new Map(),overhead=158+String(text.length).length;
  let result='',escaped=0,at=0;
  function emit(part){
   for(let n=0;n<part.length;n++){
    guard.work();const c=part[n],cost=c==='"'||c==='\\'?2:1;
    if(overhead+escaped+cost>12288)throw Error('selected_wire_bound');
    result+=c;escaped+=cost;
   }
  }
  function insert(position){
   if(position+5>text.length)return;
   guard.work();const key=text.slice(position,position+5);let row=dictionary.get(key);
   if(!row){guard.work();row=[];dictionary.set(key,row);}
   if(row.length===8){guard.work();row.shift();}
   guard.work();row.push(position);
  }
  // Every full-prefix position is inserted once, so keys and live entries are
  // each <=text.length-4<=32764; every individual row retains at most eight.
  while(at<text.length){
   guard.work();let best=0,distance=0;
   if(at+5<=text.length){
    guard.work();const row=dictionary.get(text.slice(at,at+5));
    if(row){
     while(row.length&&at-row[0]>4096){guard.work();row.shift();}
     for(const position of row){
      guard.work();let length=0;
      while(length<68&&at+length<text.length){guard.work();if(text[position+length]!==text[at+length])break;length++;}
      const d=at-position;
      if(length>=5&&(length>best||length===best&&d<distance)){best=length;distance=d;}
     }
    }
   }
   const consumed=best>=5?best:1;
   if(best>=5){const d=distance-1;emit('~'+alphabet[d>>6]+alphabet[d&63]+alphabet[best-5]);}
   else emit(text[at]==='~'?'~~':text[at]);
   for(let position=at;position<at+consumed;position++)insert(position);
   at+=consumed;
  }
  return result;
 });
 return guard.phase(()=>{
  try{return canon({encoding:tag,expanded_sha256:digest,expanded_size_bytes:text.length,payload},12288);}
  catch(e){if(e&&e.message==='canonical_bound')throw Error('selected_wire_bound');throw e;}
 });
}
"""


# D23 is additive: the raw D22 source/HOLD and every legacy method stay intact.
# The fixed local driver emits metadata only; recovered strings never execute.
D23_DATA_DRIVER = r"""'use strict';
let chunks=[],inputBytes=0,failed=false;
const cases=new Set(['codec_vectors','codec_malformed','codec_overflow','geometry']);
const report={schema_version:1,case:'codec_vectors',node_version:process.versions.node,completed:false,cause:null,checks:[],measurements:[]};
function check(id,ok){report.checks.push({id,ok:!!ok});if(!ok)throw Error('d23_driver_assertion');}
function measure(id,text){report.measurements.push({id,size_bytes:text.length,sha256:gate2SHA256(text)});}
function expected(id,fn,cause){let seen=null;try{fn();}catch(e){seen=e.message;}check(id,seen===cause);}
function wire(payload,original,tag='gate2-selected-lz77-v1',size=original.length,hash=gate2SHA256(original)){
 return gate2Canonical({encoding:tag,expanded_sha256:hash,expanded_size_bytes:size,payload},32768);
}
function budget(cause='selected_wire_deadline',now=()=>performance.now(),end=Infinity){return gate2WireBudget(now,cause,end);}
function decoded(text,tag='gate2-selected-lz77-v1',guard=budget()){return gate2WireDecode(text,tag,gate2SHA256,gate2Canonical,guard);}
function encoded(text,tag='gate2-selected-lz77-v1',guard=budget('selected_wire_root_deadline')){return gate2WireEncode(text,tag,gate2SHA256,gate2Canonical,guard);}
function referencePayload(text){
 const alphabet='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';let result='',at=0;
 while(at<text.length){let candidates=[];
  for(let p=Math.max(0,at-4096);p<at;p++)if(text.slice(p,p+5)===text.slice(at,at+5)&&at+5<=text.length)candidates.push(p);
  let best=0,distance=0;
  for(let p of candidates.slice(-8)){let n=0;while(n<68&&at+n<text.length&&text[p+n]===text[at+n])n++;let d=at-p;if(n>best||n===best&&d<distance){best=n;distance=d;}}
  if(best>=5){let d=distance-1;result+='~'+alphabet[d>>6]+alphabet[d&63]+alphabet[best-5];at+=best;}
  else{result+=text[at]==='~'?'~~':text[at];at++;}
 }
 return result;
}
function vectors(){
 const manual=[['minimum','"aaaaaa"','"a~AAA"'],['maximum','"'+'a'.repeat(69)+'"','"a~AA/"'],
 ['tilde','"'+'~'.repeat(6)+'"','"~~~AAA"'],['quotes',JSON.stringify('"'.repeat(4)),'"\\"~ABB"'],
 ['backslashes',JSON.stringify('\\'.repeat(3)),'"\\~AAA"']];
 for(let [id,original,payload] of manual){let w=wire(payload,original);check(id+'_decode',decoded(w).text===original);check(id+'_deterministic',encoded(original)===encoded(original));measure(id+'_wire',w);}
 for(let [id,original] of [['repeats',JSON.stringify('abcde'.repeat(200))],['bucket',JSON.stringify(Array.from({length:12},(_,i)=>'abcde'+String(i)+'abcde'+String(i)+'Z').join(''))],['skipped',JSON.stringify('abcdefgh'.repeat(110)+'abcdeXYZabcdeUVWabcdeXYZ')]]){
  let w=encoded(original),x=JSON.parse(w);check(id+'_oracle',x.payload===referencePayload(original));check(id+'_roundtrip',decoded(w).text===original);
 }
 const edge=JSON.stringify('ABCDE'+'Z'.repeat(4091)+'ABCDE'),outside=JSON.stringify('ABCDE'+'Z'.repeat(4092)+'ABCDE');
 check('window_4096',JSON.parse(encoded(edge)).payload.endsWith('~//A"'));
 check('window_4097_excluded',JSON.parse(encoded(outside)).payload.endsWith('ABCDE"'));
 const selected=encoded(edge),observed=encoded(edge,'gate2-observed-lz77-v1');
 check('separate_tags',selected!==observed&&JSON.parse(selected).payload===JSON.parse(observed).payload);
 check('observed_roundtrip',decoded(observed,'gate2-observed-lz77-v1').text===edge);
 expected('swapped_tag',()=>decoded(observed),'selected_wire_shape');
 let clock=0,g=budget('selected_wire_receive_deadline',()=>clock);decoded(selected,'gate2-selected-lz77-v1',g);clock=5000;
 expected('one_receive_budget',()=>decoded(observed,'gate2-observed-lz77-v1',g),'selected_wire_receive_deadline');
}
function malformed(){
 for(let [id,value] of [['null',null],['number',1],['empty',''],['nonprint','\n'],['too_long','x'.repeat(12289)]])expected('input_'+id,()=>decoded(value),'selected_wire_input');
 const good=wire('"a"','"a"'),base=JSON.parse(good);
 for(let [id,value] of [['parse','{'],['array','[]'],['extra',gate2Canonical({...base,extra:1},32768)],['tag',gate2Canonical({...base,encoding:'wrong'},32768)],['hash',gate2Canonical({...base,expanded_sha256:'A'.repeat(64)},32768)],['bool',gate2Canonical({...base,expanded_size_bytes:true},32768)],['fraction',gate2Canonical({...base,expanded_size_bytes:1.5},32768)],['exponent',good.replace('"expanded_size_bytes":3','"expanded_size_bytes":3e0')],['negative_zero',good.replace('"expanded_size_bytes":3','"expanded_size_bytes":-0')],['space',good+' ']])expected('shape_'+id,()=>decoded(value),'selected_wire_shape');
 for(let n of [-1,0,32769])expected('range_'+String(n).replace('-','minus'),()=>decoded(wire('"a"','"a"',undefined,n)),'selected_wire_bound');
 for(let [id,payload] of [['dangling','~'],['truncated','~AA'],['alphabet','~A?A'],['distance','~AAA'],['window','"a~//A']])expected('token_'+id,()=>decoded(wire(payload,'"a"')),'selected_wire_token');
 expected('token_before_expansion',()=>decoded(wire('~AAA','"a"',undefined,1)),'selected_wire_token');
 expected('bad_hash',()=>decoded(wire('"a"','"a"',undefined,3,'0'.repeat(64))),'selected_wire_binding');
 expected('short_output',()=>decoded(wire('"a"','"a"',undefined,4)),'selected_wire_binding');
 for(let [id,text] of [['invalid_json','abc'],['noncanonical','{ "a":1}']])expected('recovered_'+id,()=>decoded(wire(text,text)),'selected_wire_binding');
 const nested=encoded('"a"');check('no_recursive_decode',decoded(encoded(nested)).text===nested);
}
function overflow(){
 const maximum=JSON.stringify('a'.repeat(32766)),w=encoded(maximum);check('expanded_exact',maximum.length===32768&&decoded(w).text===maximum);measure('expanded_max_wire',w);
 expected('encoder_expanded_plus_one',()=>encoded(maximum+' '),'selected_wire_input');
 const changed=JSON.parse(w);changed.payload+='a';expected('decoder_expansion_plus_one',()=>decoded(gate2Canonical(changed,32768)),'selected_wire_expansion');
 const exact=JSON.stringify('a'.repeat(12121)),edge=wire(exact,exact);check('wire_exact',edge.length===12288&&decoded(edge).text===exact);measure('wire_exact',edge);
 const over=JSON.stringify('a'.repeat(12122));expected('wire_plus_one',()=>decoded(wire(over,over)),'selected_wire_input');
 expected('declared_over',()=>decoded(wire('"a"','"a"',undefined,32769)),'selected_wire_bound');
 let state=0x12345678,text='';const a='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
 for(let i=0;i<32766;i++){state^=state<<13;state^=state>>>17;state^=state<<5;text+=a[(state>>>0)%a.length];}
 expected('escaped_encoder_bound',()=>encoded(JSON.stringify(text)),'selected_wire_bound');
 expected('valid_literal_overflow',()=>decoded(wire('"a"','"a"',undefined,2)),'selected_wire_expansion');
}
function finish(cause){if(failed)return;failed=true;report.cause=cause;process.stdout.write(gate2Canonical(report,32767)+'\n');}
process.stdin.on('error',()=>finish('d23_driver_input'));
process.stdin.on('data',b=>{if(failed)return;inputBytes+=b.length;if(inputBytes>262144){finish('d23_driver_input');process.stdin.destroy();return;}chunks.push(b);});
process.stdin.on('end',()=>{if(failed)return;try{
 const bytes=Buffer.concat(chunks);chunks=[];if(bytes.some(x=>x>127))throw Error('d23_driver_input');
 const text=bytes.toString('ascii'),request=JSON.parse(text);
 if(!request||typeof request!=='object'||Array.isArray(request)||Object.keys(request).sort().join()!=='case,data'||!cases.has(request.case)||gate2Canonical(request,262144)!==text)throw Error('d23_driver_input');report.case=request.case;
 if(process.versions.node!=='25.2.1')throw Error('d23_node_version');
 if(typeof gate2WireEncode!=='function'||typeof gate2WireDecode!=='function'||typeof gate2WireBudget!=='function')throw Error('d23_codec_absent');
 if(request.case==='codec_vectors')vectors();else if(request.case==='codec_malformed')malformed();else if(request.case==='codec_overflow')overflow();else d23Geometry(request.data,report);
 report.completed=true;finish(null);
 }catch(e){finish(new Set(['d23_codec_absent','d23_driver_assertion','d23_driver_input','d23_node_version']).has(e.message)?e.message:'d23_driver_error');}});
"""


def d23_node_driver_v1():
    # One fixed DATA driver; the original codec-absence RED remains preserved.
    return ROOT_ENCODER+'\n'+ROOT_SHA256+'\n'+globals().get('D23_WIRE_CODEC','')+'\n'+D23_DATA_DRIVER


class D23WireCodecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import time
        cls.deadline=globals().get('D23_TEST_DEADLINE',time.monotonic()+295)

    def run_case(self,case):
        from tests.test_accepted_policy_fixture_compiler_gate2_resume_caller_v1 import d23_run_case_v1
        value,capture=d23_run_case_v1(case,b'{}',self.deadline)
        metadata=json.dumps({'case':case,'report':value,'capture':capture},sort_keys=True,separators=(',',':'))
        self.assertLessEqual(len(metadata.encode('ascii')),32768,'combined case metadata bound')
        print('D23_CASE_METADATA',metadata)
        self.assertTrue(capture['parent_observed_completion'],'bounded original child/protocol incomplete')
        self.assertTrue(value['completed'],'D23 controlled case failed: '+str(value['cause']))
        self.assertIsNone(value['cause'])
        self.assertTrue(value['checks'] and all(row['ok'] for row in value['checks']))
        self.assertEqual(capture['descendant_quiescence'],'UNKNOWN')

    def test_independent_vectors_and_deterministic_history(self):
        self.run_case('codec_vectors')

    def test_malformed_wire_keeps_ordered_causes(self):
        self.run_case('codec_malformed')

    def test_exact_and_one_byte_overflow_boundaries(self):
        self.run_case('codec_overflow')


def d23_finalizer_source_v1(initial, deferred, codec, main, caller):
    import hashlib
    import json

    def digest(text):
        return hashlib.sha256(text.encode('ascii')).hexdigest()

    def once(text, before, after):
        if text.count(before) != 1:
            raise RuntimeError('d23_finalizer_source_site')
        return text.replace(before, after)

    factory = caller.CD_FACTORY_SOURCE
    if (len(factory), digest(factory)) != (
            13073, '997579f8ffcc50d6e05ae859dd9164b1dc08ce5a71e82a1d8070633c3cdf3677'):
        raise RuntimeError('d23_factory_source_binding')
    wrapper_prefix = 'function(gate2Resume,nodeRepl){\n'
    wrapper_suffix = '\n}'
    header = """const g2=globalThis.gate2Resume,g2publisher=globalThis.nodeRepl;
if(!g2||g2.writer_installed||g2.now()>=g2.end_ms)throw Error('writer_install');
g2.writer_installed=true;
const g2intrinsic=Function.prototype.toString;
const g2hd=Object.getOwnPropertyDescriptor(g2,'_gate2CreateHash');
if(!g2hd||typeof g2hd.value!=='function'||g2hd.writable!==false||g2hd.configurable!==false||g2hd.enumerable!==false)throw Error('writer_install');
const g2h=g2hd.value;
const {spawn:g2s}=await import('node:child_process');
if(g2.now()>=g2.end_ms)throw Error('writer_install');
const {brotliDecompressSync:g2d}=await import('node:zlib');
if(g2.now()>=g2.end_ms)throw Error('writer_install');
"""
    validators = once(main.NODE_WRITER_VALIDATORS,
                      'g2.selectedView=text=>{', 'g2.expandedSelectedView=text=>{')
    validators = once(validators, 'text.length<=12288', 'text.length<=32768')
    selected = """g2.selectedView=(text,guard)=>{
 const expanded=gate2WireDecode(text,'gate2-selected-lz77-v1',g2.hash,gate2Canonical,guard);
 return guard.phase(()=>g2.expandedSelectedView(expanded.text));
};
"""
    finish = once(main.NODE_FINISH_BODY,
                  'g2.selectedView(selected);let b=Buffer.from(selected,\'ascii\'),x=g2.selected={selected_base64:b.toString(\'base64\'),size_bytes:b.length,sha256:g2.hash(b)};',
                  "const guard=gate2WireBudget(()=>g2.now(),'selected_wire_deadline',g2.end_ms);"
                  "g2.selectedView(selected,guard);"
                  "const x=guard.phase(()=>{const b=Buffer.from(selected,'ascii');return g2.selected={selected_base64:b.toString('base64'),size_bytes:b.length,sha256:g2.hash(b)};});")
    finish = once(finish, ' let sent=false,s=g2.adopt(',
                  " if(g2.now()>=g2.end_ms)throw Error('writer_state');\n let sent=false,s=g2.adopt(")
    python = (json.dumps(main.NODE_WRITER_HEAD, ensure_ascii=True, separators=(',', ':'))
              + '+g2.python_common+'
              + json.dumps(main.NODE_WRITER_TAIL, ensure_ascii=True, separators=(',', ':')))
    body = (header + main.ROOT_ENCODER + '\n' + codec + '\n' + deferred + '\n'
            + validators + '\n' + selected + '\n' + 'g2.writer=' + python + ';\n'
            + 'g2.expected_initial_sha256=' + json.dumps(digest(initial)) + ';\n'
            + finish)
    wrapper = 'const g2factory=' + wrapper_prefix + factory + wrapper_suffix + ';\n'
    authenticate = (
        "if(g2.now()>=g2.end_ms)throw Error('cd_factory_late');\n"
        "if(globalThis.gate2Resume!==g2||globalThis.nodeRepl!==g2publisher)throw Error('cd_factory_objects');\n"
        "const g2source=g2intrinsic.call(g2factory);\n"
        "if(typeof g2source!=='string'||g2source.length!==" + str(len(wrapper_prefix) + len(factory) + len(wrapper_suffix))
        + "||!g2source.startsWith(" + json.dumps(wrapper_prefix)
        + ")||!g2source.endsWith(" + json.dumps(wrapper_suffix)
        + ")||g2.hash(g2source.slice(" + str(len(wrapper_prefix)) + ','
        + str(len(wrapper_prefix) + len(factory)) + '))!==' + json.dumps(digest(factory))
        + ")throw Error('cd_factory_binding');\n"
        + 'g2.cd_factory_sha256=' + json.dumps(digest(factory)) + ';\n'
        + 'g2factory(g2,g2publisher);\n'
        + "if(g2.now()>=g2.end_ms)throw Error('cd_factory_late');\n")
    finalizer = body + wrapper + authenticate
    facts = {'initial_size_bytes': len(initial), 'initial_sha256': digest(initial),
             'finalizer_size_bytes': len(finalizer), 'finalizer_sha256': digest(finalizer),
             'factory_size_bytes': len(factory), 'factory_sha256': digest(factory),
             'wrapper_prefix_size_bytes': len(wrapper_prefix), 'wrapper_suffix_size_bytes': len(wrapper_suffix),
             'python_head_size_bytes': len(main.NODE_WRITER_HEAD),
             'python_head_sha256': digest(main.NODE_WRITER_HEAD),
             'python_tail_size_bytes': len(main.NODE_WRITER_TAIL),
             'python_tail_sha256': digest(main.NODE_WRITER_TAIL),
             'python_common_size_bytes': len(main.NODE_SHARED_PYTHON),
             'python_common_sha256': digest(main.NODE_SHARED_PYTHON),
             'generated_operational_program_execution': False,
             'generated_full_subject_files_written': False}
    return finalizer, facts


def d23_root_wire_sources_v1(codec):
    """Return only new direct-static ROOT variants; retain both legacy constants."""
    assert type(codec) is str and codec and codec.isascii(), 'fixed codec source required'
    sources = {'orchestrator': ROOT_ORCHESTRATOR, 'receiver': ROOT_RECEIVER}
    expected = {
        'orchestrator': (3945, '498aa3c7e6f4a441deb5f8cf08cfff8845a08c6f898967189c941500afd97baf'),
        'receiver': (11208, 'e2a04079a1ef36a2bad984b1c979201cb07f38c78ac3a4411a1f6e3612e8cd88'),
    }
    for role, source in sources.items():
        assert type(source) is str and source.isascii(), 'legacy ROOT source kind'
        raw = source.encode('ascii')
        assert (len(raw), hashlib.sha256(raw).hexdigest()) == expected[role], 'legacy ROOT source binding'

    def replace_once(source, before, after):
        assert source.count(before) == 1, 'fixed ROOT replacement cardinality'
        return source.replace(before, after, 1)

    old_run = r"""async function gate2Run(tools,first,poll,timeout){
 if(typeof first!=='string'||typeof poll!=='string'||!Number.isSafeInteger(timeout)||timeout<1||timeout>32000)throw Error('root_arguments');
 let frames=[],codes=[],text,observed={calls:[],frames};
 try{for(let n=0;n<6;n++){
  let code=n?poll:first,args={code,timeout_ms:timeout};observed.calls.push(args);codes.push(code);let r=await tools.mcp__node_repl__js(args);frames.push(r);
  gate2Canonical(r,12288);
  if(r.isError!==false||!Array.isArray(r.content)||r.content.length!==1||r.content[0].type!=='text'||typeof r.content[0].text!=='string')throw Error('provider_unavailable');
  text=r.content[0].text;
  if(text.startsWith('[1,'))return {observed,selected:gate2Canonical({call:{tool:'mcp__node_repl__js',timeout_ms:timeout,codes},frames},12288)};
  if(!text.startsWith('[0,')&&text!=='[0]')throw Error('provider_terminal');
 }
 throw Error('setup_frame_limit');}catch(e){return {observed,cause:String(e.message).slice(0,80)};}
}"""
    new_run = r"""function gate2RootClock(){
 let p=globalThis.performance,read,start,last,denied=false;
 try{if(!p||typeof p.now!=='function')throw Error();read=p.now;start=read.call(p);if(!Number.isFinite(start)||start<0||start>Number.MAX_SAFE_INTEGER-150000)throw Error();last=start;}catch{throw Error('selected_wire_root_deadline');}
 function now(total=false){
  if(denied)throw Error('selected_wire_root_deadline');
  try{let n=read.call(p);if(!Number.isFinite(n)||n<last||n>=start+(total?150000:140000))throw Error();last=n;return n;}catch{denied=true;throw Error('selected_wire_root_deadline');}
 }
 now.work_end=start+140000;
 now.phase=(fn,total=false)=>{now(total);let value,error,failed=false;try{value=fn();}catch(e){error=e;failed=true;}now(total);if(failed)throw error;return value;};
 return now;
}
async function gate2Run(tools,first,poll,timeout,root){
 if(typeof first!=='string'||typeof poll!=='string'||!Number.isSafeInteger(timeout)||timeout<1||timeout>32000)throw Error('root_arguments');
 let frames=[],codes=[],text,observed={calls:[],frames};
 try{for(let n=0;n<6;n++){
  let code=n?poll:first,args={code,timeout_ms:timeout};observed.calls.push(args);codes.push(code);root();let r=await tools.mcp__node_repl__js(args);frames.push(r);root();
  root.phase(()=>gate2Canonical(r,12288));
  if(r.isError!==false||!Array.isArray(r.content)||r.content.length!==1||r.content[0].type!=='text'||typeof r.content[0].text!=='string')throw Error('provider_unavailable');
  text=r.content[0].text;
  if(text.startsWith('[1,')){
   let guard=gate2WireBudget(root,'selected_wire_root_deadline',root.work_end);
   function original(value){try{return guard.phase(()=>gate2Canonical(value,32768));}catch(e){if(e&&e.message==='canonical_bound')throw Error('selected_wire_input');throw e;}}
   let selectedText=original({call:{tool:'mcp__node_repl__js',timeout_ms:timeout,codes},frames});
   let selected=gate2WireEncode(selectedText,'gate2-selected-lz77-v1',gate2SHA256,gate2Canonical,guard);
   let observedText=original(observed);
   let observedWire=gate2WireEncode(observedText,'gate2-observed-lz77-v1',gate2SHA256,gate2Canonical,guard);
   return {observed:observedWire,selected};
  }
  if(!text.startsWith('[0,')&&text!=='[0]')throw Error('provider_terminal');
 }
 throw Error('setup_frame_limit');}catch(e){return {observed,cause:String(e.message).slice(0,80)};}
}"""
    orchestrator = replace_once(sources['orchestrator'], old_run, new_run)
    orchestrator = replace_once(
        orchestrator,
        "  result.setup=await gate2Run(tools,first,'await gate2Resume.poll();',32000);",
        "  let poll='await gate2Resume.poll();',timeout=32000;if(typeof first!=='string'||typeof poll!=='string'||!Number.isSafeInteger(timeout)||timeout<1||timeout>32000)throw Error('root_arguments');let root=gate2RootClock();result.setup=await gate2Run(tools,first,poll,timeout,root);",
    )
    orchestrator = replace_once(
        orchestrator,
        "  result.writer_call={code:finalizer+'\\nawait gate2Resume.finish('+JSON.stringify(result.setup.selected)+');',timeout_ms:11000};r=await tools.mcp__node_repl__js(result.writer_call);result.writer=r;let text=delivered(r);",
        "  root.phase(()=>{result.writer_call={code:finalizer+'\\nawait gate2Resume.finish('+JSON.stringify(result.setup.selected)+');',timeout_ms:11000};});root();r=await tools.mcp__node_repl__js(result.writer_call);result.writer=r;root(true);let text=root.phase(()=>delivered(r),true);",
    )
    orchestrator = replace_once(
        orchestrator,
        "  result.verification_call={code:'gate2Resume.verifyReturn('+JSON.stringify(text)+');',timeout_ms:1000};r=await tools.mcp__node_repl__js(result.verification_call);result.verification=r;let proof=JSON.parse(delivered(r));",
        "  root.phase(()=>{result.verification_call={code:'gate2Resume.verifyReturn('+JSON.stringify(text)+');',timeout_ms:1000};},true);root(true);r=await tools.mcp__node_repl__js(result.verification_call);result.verification=r;root(true);let proof=root.phase(()=>JSON.parse(delivered(r)),true);\n  let c=root.phase(()=>{",
    )
    orchestrator = replace_once(
        orchestrator,
        "c!==null)throw Error('return_context');result.context=c;",
        "c!==null)throw Error('return_context');return c;},true);root(true);result.context=c;",
    )

    old_receive = r""" let setup=record.setup;need(keys(setup,'observed,selected')&&keys(setup.observed,'calls,frames')&&typeof setup.selected==='string'&&setup.selected.length<=12288&&gate2SHA256(setup.selected)===context.selected_sha256&&record.selected_sha256===context.selected_sha256,'delivery_selected');
 let selected=JSON.parse(setup.selected);need(gate2Canonical(selected,12288)===setup.selected&&keys(selected,'call,frames')&&keys(selected.call,'tool,timeout_ms,codes')&&selected.call.tool==='mcp__node_repl__js'&&selected.call.timeout_ms===32000&&Array.isArray(selected.frames)&&selected.frames.length>=1&&selected.frames.length<=6&&Array.isArray(selected.call.codes)&&selected.call.codes.length===selected.frames.length&&selected.call.codes.every(c=>typeof c==='string')&&gate2SHA256(selected.call.codes[0])===context.core_sha256,'delivery_core');
 need(same(selected.frames,setup.observed.frames)&&same(selected.call.codes.map(code=>({code,timeout_ms:32000})),setup.observed.calls),'delivery_actual_setup_calls');"""
    new_receive = r""" let setup=record.setup;need(keys(setup,'observed,selected'),'delivery_selected');
 gate2WireInput(setup.selected);
 let guard=gate2WireBudget(()=>globalThis.performance.now(),'selected_wire_receive_deadline');
 let selectedWireSHA=guard.phase(()=>gate2SHA256(setup.selected));
 need(selectedWireSHA===context.selected_sha256&&record.selected_sha256===context.selected_sha256,'delivery_selected');
 let recovered=gate2WireDecode(setup.selected,'gate2-selected-lz77-v1',gate2SHA256,gate2Canonical,guard),selected=recovered.value;
 guard.phase(()=>need(gate2Canonical(selected,32768)===recovered.text&&keys(selected,'call,frames')&&keys(selected.call,'tool,timeout_ms,codes')&&selected.call.tool==='mcp__node_repl__js'&&selected.call.timeout_ms===32000&&Array.isArray(selected.frames)&&selected.frames.length>=1&&selected.frames.length<=6&&Array.isArray(selected.call.codes)&&selected.call.codes.length===selected.frames.length&&selected.call.codes.every(c=>typeof c==='string')&&gate2SHA256(selected.call.codes[0])===context.core_sha256,'delivery_core'));
 let observed=gate2WireDecode(setup.observed,'gate2-observed-lz77-v1',gate2SHA256,gate2Canonical,guard).value;
 guard.phase(()=>need(keys(observed,'calls,frames')&&Array.isArray(observed.calls)&&Array.isArray(observed.frames)&&observed.calls.length>=1&&observed.calls.length<=6&&observed.frames.length===observed.calls.length&&observed.calls.every(call=>keys(call,'code,timeout_ms')&&typeof call.code==='string'&&call.code.length>0&&call.timeout_ms===32000),'delivery_observed'));
 guard.phase(()=>need(same(selected.frames,observed.frames)&&same(selected.call.codes.map(code=>({code,timeout_ms:32000})),observed.calls),'delivery_actual_setup_calls'));
 return guard.phase(()=>{"""
    receiver = replace_once(sources['receiver'], old_receive, new_receive)
    receiver = replace_once(
        receiver,
        " return {version:1,context_sha256:contextSHA,record_size_bytes:recordText.length,record_sha256:gate2SHA256(recordText),executor_call_sha256:executor.sha256,max_output_tokens:100000,terminal:'complete_untruncated',tool_reference:toolReference};\n}\nfunction gate2Approve",
        " return {version:1,context_sha256:contextSHA,record_size_bytes:recordText.length,record_sha256:gate2SHA256(recordText),executor_call_sha256:executor.sha256,max_output_tokens:100000,terminal:'complete_untruncated',tool_reference:toolReference};\n });\n}\nfunction gate2Approve",
    )
    return {'orchestrator': orchestrator, 'receiver': receiver}


def d23_inert_bundle_v1(deadline):
    import base64
    import sys
    import time
    from tests import test_accepted_policy_fixture_compiler_gate2_resume_caller_v1 as caller

    def gate():
        if time.monotonic() >= deadline - 5:
            raise RuntimeError('d23_construction_deadline')

    def canonical(value):
        return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                          allow_nan=False).encode('ascii')

    def digest(value):
        return hashlib.sha256(value).hexdigest()

    gate()
    initial, historical, parts, source_facts = d22_phase_initial_v1(deadline)
    compressed = source_facts['compression']
    if (compressed['parent_observed_completion'] is not True or compressed['causes']
            or compressed['returncode'] != 0 or compressed['timed_out']
            or compressed['kill_requested'] or not compressed['reaped']
            or not compressed['threads_joined']
            or compressed['started_monotonic'] + compressed['elapsed_seconds']
               >= compressed['cleanup_deadline']
            or any(not compressed[name]['eof'] or compressed[name]['overflow']
                   or compressed[name]['io_error'] is not None
                   or compressed[name]['unknown_remainder'] for name in ('stdout', 'stderr'))):
        refusal = RuntimeError('d23_compression_capture_incomplete')
        refusal.metadata = compressed
        raise refusal
    if (len(initial), digest(initial.encode('ascii'))) != (
            13841, '242f28752079f1d2b50a410d0f2606a3097899b8ca95e2add43068483609cff5'):
        raise RuntimeError('d23_initial_binding')
    gate()
    finalizer, finalizer_facts = d23_finalizer_source_v1(
        initial, parts['deferred'], D23_WIRE_CODEC, sys.modules[__name__], caller)
    root_sources = d23_root_wire_sources_v1(D23_WIRE_CODEC)
    commit = hashlib.sha1(b'controlled-current-review').hexdigest()
    packet_sha = digest(b'packet')
    factory_sha = digest(caller.CD_FACTORY_SOURCE.encode('ascii'))
    profile = {'max_output_tokens': 100000, 'max_record_bytes': 65536}
    expected = {'code_commit': commit, 'core_sha256': digest(initial.encode('ascii')),
                'factory_sha256': factory_sha}
    prefix = ('// @exec: {"yield_time_ms":1,"max_output_tokens":100000}\n'
              + ROOT_ENCODER + '\n' + ROOT_SHA256 + '\n' + D23_WIRE_CODEC + '\n'
              + root_sources['orchestrator'] + '\n' + root_sources['receiver']
              + '\nconst profile=' + canonical(profile).decode('ascii')
              + ';const record=await gate2Complete(tools,')
    suffix = (',profile,' + canonical(expected).decode('ascii')
              + ');text(gate2Export(record,profile));\n')
    # Factor only the fixed TEST transport. The complete executor below is
    # independently pinned, and the fixed driver reconstructs exactly these
    # bytes in RAM for full-chain measurement. Operational wires stay complete.
    executor = (prefix + json.dumps(initial, ensure_ascii=True, separators=(',', ':'))
                + ',' + json.dumps(finalizer, ensure_ascii=True, separators=(',', ':')) + suffix)
    executor_pin = {'size_bytes': len(executor), 'sha256': digest(executor.encode('ascii'))}
    root = Path(__file__).resolve().parents[1]
    descriptors = (
        ('tests/fixtures/accepted_policy_fixture_compiler_component_v1.py', 32732,
         '329fb13f2c6dcee0872e5a29ec1fd769dc6e57ce92ee1076fef6737f1da86d88',
         '5a342c2c2efa44aa5add3f91ae94518c143acece'),
        ('tests/fixtures/accepted_policy_fixture_compiler_gate2_resume_v1.py', 32739,
         '5fd7d2d6ee62ff584d2a4662757ca804a3d3300d30bb966319901870c4c85670',
         'cc9b6a1b7e6e6ff2f9b750ea67b20cf7213d09b0'))
    held = []
    source_rows = []
    for rel, size, sha, blob in descriptors:
        gate()
        with (root / rel).open('rb') as handle:
            raw = handle.read(32769)
        gate()
        if (len(raw), digest(raw), hashlib.sha1(b'blob ' + str(len(raw)).encode()
                + b'\0' + raw).hexdigest()) != (size, sha, blob):
            raise RuntimeError('d23_fixture_binding')
        held.append(base64.b64encode(raw).decode('ascii'))
        source_rows.append({'size_bytes': size, 'sha256': sha, 'git_blob': blob})
    fixture = ResumeNodeCaller('runTest')
    success = fixture.success_output()
    structured = fixture.failure_output()
    unicode_failure = fixture.failure_output(unicode=True)
    forms = [
        {'id': 'success', 'stdout': success, 'stderr': '', 'success': True},
        {'id': 'structured_failure', 'stdout': '', 'stderr': structured,
         'success': False, 'failure': True},
        {'id': 'unicode_failure', 'stdout': '', 'stderr': unicode_failure,
         'success': False, 'failure': True},
        {'id': 'partial_emission', 'stdout': success[:1024], 'stderr': '',
         'success': False, 'partial': True},
        {'id': 'unknown_closure', 'stdout': success, 'stderr': '',
         'success': False, 'unknown': True},
        {'id': 'setup_refusal', 'stdout': '{}\n', 'stderr': '', 'success': False}]
    gate()
    # This is a DECLARED FUTURE CONTROLLED chain model with every field present.
    # No historical output is filtered or claimed to be a new acquired original.
    chain = [
        {'call': {'type': 'custom_tool_call', 'id': 'd23_exec', 'status': 'completed',
                  'call_id': 'd23_exec_call', 'name': 'exec', 'input': '',
                  'internal_chat_message_metadata_passthrough': {'turn_id': 'd23_controlled_geometry',
                                                              'create_time': 1792314000.25}},
         'result': {'type': 'custom_tool_call_output', 'id': 'd23_exec_output',
                    'call_id': 'd23_exec_call',
                    'output': 'Script running with cell ID d23geometry\nWall time 0.0 seconds\nOutput:\n',
                    'internal_chat_message_metadata_passthrough': {'turn_id': 'd23_controlled_geometry',
                                                                'create_time': 1792314000.5}}},
        {'call': {'type': 'function_call', 'id': 'd23_wait', 'name': 'wait',
                  'arguments': canonical({'cell_id': 'd23geometry', 'max_tokens': 100000,
                                          'yield_time_ms': 1000}).decode('ascii'),
                  'call_id': 'd23_wait_call',
                  'internal_chat_message_metadata_passthrough': {'turn_id': 'd23_controlled_geometry',
                                                              'create_time': 1792314001.25}},
         'result': {'type': 'function_call_output', 'id': 'd23_wait_output',
                    'call_id': 'd23_wait_call',
                    'output': [{'type': 'input_text',
                                'text': 'Script completed\nWall time 0.0 seconds\nOutput:\n'},
                               {'type': 'input_text', 'text': ''}],
                    'internal_chat_message_metadata_passthrough': {'turn_id': 'd23_controlled_geometry',
                                                                'create_time': 1792314001.5}}}]
    # Pure canonical native-format DATA, including the genuine C failure
    # formatter. No native_main, writer, temporary directory or stage is called.
    c = importlib.import_module('tests.fixtures.accepted_policy_fixture_compiler_gate2_c_v1')
    native_root = c.RESUME_OWNER_ROOT_V1.as_posix() + '/r1'
    if len(native_root) != 98:
        raise RuntimeError('d23_native_model_root')
    maximum = 2**64 - 1
    completions = []
    later = []
    native_input = canonical({'current': {descriptors[1][0]: source_rows[1]}}).decode('ascii') + '\n'
    for stage in ('C1', 'C2', 'C3', 'C4', 'C5', 'C6'):
        gate()
        previous = None if stage == 'C1' else completions[-1]['descriptor']['sha256']
        record = c._invocation_record_v1(stage, commit, packet_sha, digest(stage.encode()),
                                         digest(('accounting-' + stage).encode()), previous)
        raw = canonical(record)
        path = native_root + '/outputs/' + stage + '/outer.invocation.original.json'
        complete = {'descriptor': {'path': path, 'size_bytes': len(raw), 'sha256': digest(raw)},
                    'write_facts': {'path': path, 'open_completed': True, 'written_bytes': len(raw),
                                    'write_extent_unknown': False, 'flush_completed': True,
                                    'fsync_completed': True, 'close_completed': True,
                                    'directory_persisted': True, 'complete': True,
                                    'deadline_failed': False, 'failure_causes': []},
                    'completion_deadline_ns': maximum, 'external_approval': False}
        args = [commit, '32768', packet_sha,
                '-' if not completions else ','.join(
                    str(row['descriptor']['size_bytes']) + ':' + row['descriptor']['sha256']
                    for row in completions)]
        completions.append(complete)
        if stage in ('C1', 'C6'):
            stdout = c.component.canonical_json_v1(complete).decode('ascii') + '\n'
            failure = c.native_failure_bytes_v1(c.Gate2Refusal('native_stdout_deadline',
                {'written_bytes': len(stdout), 'write_extent_unknown': False,
                 'flush_completed': False})).decode('ascii')
            if len(stdout.encode('ascii')) > 2048 or len(failure.encode('ascii')) > 768:
                raise RuntimeError('d23_c_model_pipe_bound')
            for failed in (False, True):
                later.append({'id': stage + ('_failure' if failed else '_success'),
                              'stage': stage, 'args': args, 'stdout': stdout,
                              'stderr': failure if failed else '', 'failure': failed,
                              'duration_ms': 150000, 'native_input': native_input})
    summary = {'stage': 'D', 'receipt_sha256': digest(b'controlled-D-receipt'),
               'receipt_size_bytes': 20480,
               'final_measurement': {key: maximum for key in
                                     ('c_free_bytes', 'ext4_used_bytes', 'project_free_bytes')},
               'ledger': {'remaining_before': 536870912, 'charge_bytes': 2097152,
                          'remaining_after': 534773760},
               'deadline_ns': maximum, 'finished_ns': maximum - 1,
               'control_bytes': 524288, 'aggregate_bytes': 2097152, 'passed': True,
               'finalization_complete': True, 'controlled': False, 'external_return_required': True}
    d_stdout = c.component.canonical_json_v1(summary).decode('ascii') + '\n'
    d_failure = c.native_failure_bytes_v1(c.Gate2Refusal('native_stdout_deadline',
        {'written_bytes': len(d_stdout), 'write_extent_unknown': False,
         'flush_completed': False})).decode('ascii')
    if len(d_stdout.encode('ascii')) > 768 or len(d_failure.encode('ascii')) > 768:
        raise RuntimeError('d23_d_model_pipe_bound')
    d_args = [commit, '32768', packet_sha, ','.join(
        str(row['descriptor']['size_bytes']) + ':' + row['descriptor']['sha256']
        for row in completions)]
    for failed in (False, True):
        later.append({'id': 'D_failure' if failed else 'D_success', 'stage': 'D',
                      'args': d_args, 'stdout': d_stdout, 'stderr': d_failure if failed else '',
                      'failure': failed, 'duration_ms': 10000, 'native_input': native_input})
    approval_template = {
        'version': 1, 'kind': 'vast_gate2_external_delivery_approval_v1',
        'receipt_sha256': None, 'context_sha256': None, 'code_commit': commit,
        'packet_size_bytes': 32768, 'packet_sha256': packet_sha, 'selected_sha256': None,
        'core_sha256': expected['core_sha256'], 'factory_sha256': factory_sha,
        'decision': 'approved_for_C1', 'approval_type': 'delegated_agent_self_approval',
        'independent_review_reference': 'https://github.com/lordcoudy/VAST/pull/9#issuecomment-6248000252'}
    approval_reference = 'https://github.com/lordcoudy/VAST/pull/9#issuecomment-' + '9' * 20
    data = {'initial': initial, 'finalizer': finalizer,
            'executor_prefix': prefix, 'executor_suffix': suffix, 'executor_pin': executor_pin,
            'fields': list(NODE_FIELDS), 'pipe_fields': list(NODE_PIPE_FIELDS), 'held': held,
            'commit': commit, 'packet_sha256': packet_sha, 'factory_sha256': factory_sha,
            'forms': forms, 'chain': chain, 'later': later,
            'approval_template': approval_template, 'approval_reference': approval_reference}
    gate()
    encoded = canonical(data)
    facts = {'kind': 'd23_inert_source_construction_metadata_v1',
             'initial': source_facts, 'finalizer': finalizer_facts, 'executor': executor_pin,
             'input_data_size_bytes': len(encoded), 'input_data_sha256': digest(encoded),
             'modeled_setup_form_count': len(forms), 'modeled_later_form_count': len(later),
             'controlled_synthetic_geometry_only': True,
             'independent_actual_acquisition_proven': False,
             'generated_operational_program_execution': False,
             'generated_full_subject_files_written': False,
             'behavior_conformance_complete': False, 'physical_acceptance': False}
    if len(canonical(facts)) > 32768:
        raise RuntimeError('d23_source_metadata_bound')
    return encoded, facts


D23_GEOMETRY_DRIVER = r"""function d23Geometry(d,report){
 const z=require('node:zlib'),hash=b=>require('node:crypto').createHash('sha256').update(b).digest('hex'),canon=v=>gate2Canonical(v,262144),ascii=s=>typeof s==='string'&&!/[^\x00-\x7f]/.test(s);
 const held=d.held.map(s=>Buffer.from(s,'base64'));
 function bound(id,ok){report.checks.push({id,ok});}
 function keep(id,text,cap){measure(id,text);bound(id+'_bound',text.length<=cap);}
 function provider(text,n){return {content:[{type:'text',text}],isError:false,_meta:{actual_ordinal:n,resource:{uri:'controlled:retained'}},resource:{mimeType:'application/json'}};}
 const start=Number.MAX_SAFE_INTEGER-1500000,work=start+140000,end=start+150000,clock=[start,work,end],poll='await gate2Resume.poll();',ready='1755772592209100\n',ack_ms=149000;
 const setupInput=Buffer.concat([Buffer.from(canon({remaining_ms:ack_ms,selected_base64:'',sha256:hash(''),size_bytes:0})+'\n'),...held]);
 function snapshot(id,kind,raw,input,changes={},n=start+130000,ownClock=null,ack=ack_ms,pid=4294967295){
  let pieces=[],pipes=raw.map((b,i)=>{
   let encoding=b.every(x=>x<128)?'ascii':'base64',v=b.toString(encoding),compressed=z.brotliCompressSync(b,{maxOutputLength:4096}).toString('base64');
   check(id+'_pipe'+i+'_inverse',z.brotliDecompressSync(Buffer.from(compressed,'base64'),{maxOutputLength:2113}).equals(b));
   if(JSON.stringify(['br64',compressed.length,compressed]).length<JSON.stringify([encoding,v.length,v]).length){encoding='br64';v=compressed;}
   pieces.push(v);let p={bytes:b.length,sha256:hash(b),eof:true,closed:true,error:false,encoding,chars:v.length,remainder_unknown:false};
   if(changes.partial&&i===0)Object.assign(p,{eof:false,closed:false,error:true,remainder_unknown:true});
   return d.pipe_fields.map(k=>p[k]);
  });
  let f={pid,returncode:0,signal:null,exited:true,closed:true,pipes,causes:[],unknown_closure:false,completed:true,terminal_observed_ms:n,physical_acceptance:false,clock:ownClock,ack_ms:ack,stdin_finished:true,stdin_closed:true,stdin_bytes:input.length,stdin_sha256:hash(input),stdin_extent_unknown:false,source_facts:null};
  if(changes.failure)Object.assign(f,{returncode:1,completed:false});
  if(changes.partial)Object.assign(f,{closed:false,causes:['pipe_error'],unknown_closure:true,completed:false});
  if(changes.unknown)Object.assign(f,{returncode:null,exited:false,unknown_closure:true,completed:false});
  if(raw[1].length)f.completed=false;
  return JSON.stringify([kind,...d.fields.map(k=>f[k])])+'\n'+pieces.join('');
 }
 function writer(id,selected,remaining,cap,formsCap,ownClock,n){
  const selectedSHA=hash(selected),header=canon({remaining_ms:remaining,selected_base64:Buffer.from(selected).toString('base64'),sha256:selectedSHA,size_bytes:selected.length})+'\n',input=Buffer.concat([Buffer.from(header),...held]),q=Math.ceil(selected.length/4096)*4096,forms=Math.max(cap,q)+q+8192;
  const facts={stdin_eof:true,stdin_extent_unknown:false,source_bytes:held.map(b=>b.length),source_sha256:held.map(hash),open_completed:true,written_bytes:selected.length,extent_unknown:false,fsync_completed:true,close_completed:true,allocated_bytes:cap,completed:true,sha256:selectedSHA,unknown_closure:false};
  let receipt=canon({completed:true,external_terminal_required:true,size_bytes:selected.length,sha256:selectedSHA,write_facts:facts,deadline_ns:0,all_forms_quote_bytes:forms})+'\n';
  check(id+'_uint64',receipt.split('"deadline_ns":0').length===2);receipt=receipt.replace('"deadline_ns":0','"deadline_ns":18446744073709551615');
  const raw=Buffer.from('{"ready":true,"schema_version":1}\n'+receipt);
  return {header,input,raw,text:snapshot(id+'_writer',2,[raw,Buffer.alloc(0)],input,{},n,ownClock,remaining,4294967294),forms,formsOK:forms<=formsCap,selectedSHA};
 }
 const executor=d.executor_prefix+JSON.stringify(d.initial)+','+JSON.stringify(d.finalizer)+d.executor_suffix;
 const marker='const g2factory=function(gate2Resume,nodeRepl){\n',at=d.finalizer.indexOf(marker),factorySize=13073;
 check('source_bindings',held.length===2&&ascii(executor)&&executor.length===d.executor_pin.size_bytes&&hash(executor)===d.executor_pin.sha256&&at>=0&&d.finalizer.indexOf(marker,at+1)<0&&hash(d.finalizer.slice(at+marker.length,at+marker.length+factorySize))===d.factory_sha256&&d.finalizer.startsWith('\n};',at+marker.length+factorySize));
 keep('initial_source',d.initial,262144);keep('finalizer_source',d.finalizer,262144);keep('executor_source',executor,262144);
 function fullChain(id,root){
  let c=JSON.parse(canon(d.chain)),a=c[0].call,b=c[0].result,w=c[1].call,t=c[1].result;
  let valid=c.length===2&&a.input===''&&t.output.length===2&&t.output[1].text===''&&a.call_id!==w.call_id&&b.call_id===a.call_id&&t.call_id===w.call_id;
  const wrapper=/^Script (completed|running with cell ID ([A-Za-z0-9_-]{1,64}))\nWall time [0-9]{1,12}(?:\.[0-9]{1,9})? seconds\nOutput:\n$/,first=wrapper.exec(b.output),last=wrapper.exec(t.output[0].text);
  valid=valid&&first&&first[2]&&last&&last[1]==='completed'&&b.output.length<=256&&t.output[0].text.length<=256;
  const wa=JSON.parse(w.arguments);
  valid=valid&&canon(wa)===w.arguments&&wa.cell_id===first[2]&&wa.max_tokens===100000&&wa.yield_time_ms>=1&&wa.yield_time_ms<=60000;
  a.input=executor;t.output[1].text=root;
  check(id+'_chain_join',valid&&t.output.slice(1).map(r=>r.text).join('')===root&&typeof b.output==='string');
  return {text:canon(c),reference:'functions.exec/'+first[2]};
 }
 check('six_setup_forms',d.forms.length===6&&d.forms.filter(x=>x.success===true).length===1);
 let upstream=null;
 for(const form of d.forms){
  const id=form.id;check(id+'_setup',ascii(form.stdout)&&ascii(form.stderr)&&(!form.success||!form.failure&&!form.partial&&!form.unknown&&!form.stderr));
  const raw=[Buffer.from(form.stdout),Buffer.from(form.stderr),Buffer.from(ready)];
  check(id+'_provider_pipes',raw[0].length<=2048&&raw[1].length<=2048&&raw[2].length<=32);
  const terminal=snapshot(id,1,raw,setupInput,form),codes=[d.initial,...Array(5).fill(poll)],frames=codes.map((code,i)=>provider(i===5?terminal:JSON.stringify(i===0?[0,...clock,4294967295,null]:[0,4294967295,null]),i+1));
  let selected,observed;
  try{
   const guard=budget('selected_wire_root_deadline');
   function original(value){try{return guard.phase(()=>gate2Canonical(value,32768));}catch(e){if(e&&e.message==='canonical_bound')throw Error('selected_wire_input');throw e;}}
   const selectedOriginal=original({call:{tool:'mcp__node_repl__js',timeout_ms:32000,codes},frames});
   keep(id+'_selected_original',selectedOriginal,32768);selected=encoded(selectedOriginal,'gate2-selected-lz77-v1',guard);
   const observedOriginal=original({calls:codes.map(code=>({code,timeout_ms:32000})),frames});
   keep(id+'_observed_original',observedOriginal,32768);observed=encoded(observedOriginal,'gate2-observed-lz77-v1',guard);
   keep(id+'_selected_wire',selected,12288);keep(id+'_observed_wire',observed,12288);
   const receive=budget('selected_wire_receive_deadline');check(id+'_full_roundtrip',decoded(selected,'gate2-selected-lz77-v1',receive).text===selectedOriginal&&decoded(observed,'gate2-observed-lz77-v1',receive).text===observedOriginal);
  }catch(e){bound(id+'_wire_geometry',false);measure(id+'_wire_refusal',String(e.message));continue;}
  const w=writer(id,selected,19000,12288,32768,clock,start+131000);
  keep(id+'_ack',w.header,24576);keep(id+'_writer_stdout',w.raw.toString('ascii'),2112);
  bound(id+'_writer_input_bound',w.input.length<=90112);bound(id+'_forms_bound',w.formsOK);
  const context=form.success?['vast.gate2.external-delivery.v1',d.commit,32768,d.packet_sha256,w.selectedSHA,hash(d.initial),d.factory_sha256]:null,verification=JSON.stringify([3,start+132000,end,form.success,true,w.selectedSHA,context]);
  const record={completed:form.success,setup_success:form.success,retention_complete:true,physical_acceptance:false,output_profile:{max_output_tokens:100000,max_record_bytes:65536},setup:{observed,selected},writer_call:{code:d.finalizer+'\nawait gate2Resume.finish('+JSON.stringify(selected)+');',timeout_ms:11000},writer:provider(w.text,7),verification_call:{code:'gate2Resume.verifyReturn('+JSON.stringify(w.text)+');',timeout_ms:1000},verification:provider(verification,8),context,selected_sha256:w.selectedSHA};
  const root=canon(record)+'\n',chain=fullChain(id,root);keep(id+'_root',root,65536);keep(id+'_chain',chain.text,262144);
  if(form.success&&root.length<=65536&&chain.text.length<=262144&&w.raw.length<=2112&&w.input.length<=90112&&w.formsOK){
   const receipt={version:1,context_sha256:hash(canon(context)),record_size_bytes:root.length,record_sha256:hash(root),executor_call_sha256:hash(chain.text),max_output_tokens:100000,terminal:'complete_untruncated',tool_reference:chain.reference},receiptSHA=hash(canon(receipt));
   const body=JSON.parse(canon(d.approval_template));check('approval_slots',Object.values(body).filter(v=>v===null).length===3&&['receipt_sha256','context_sha256','selected_sha256'].every(k=>body[k]===null));Object.assign(body,{receipt_sha256:receiptSHA,context_sha256:receipt.context_sha256,selected_sha256:w.selectedSHA});
   const external={receipt,approval:{reference:d.approval_reference,body_sha256:hash(canon(body)+'\n'),receipt_sha256:receiptSHA}};
   upstream={pins:[w.selectedSHA,hash(d.initial),d.factory_sha256],external,externalSHA:hash(canon(external))};
  }
 }
 check('six_later_forms',d.later.length===6&&new Set(d.later.map(x=>x.stage+':'+x.failure)).size===6);
 bound('later_measured_upstream',!!upstream);if(!upstream)return;
 for(const form of d.later){
  let stage=form.stage,id=form.id,args=form.args,duration=stage==='D'?10000:150000;
  check(id+'_later',['C1','C6','D'].includes(stage)&&form.duration_ms===duration&&args.length===4&&args[0]===d.commit&&args[1]==='32768'&&args[2]===d.packet_sha256&&ascii(form.native_input));
  const native=[Buffer.from(form.stdout),Buffer.from(form.stderr)],input=Buffer.from(form.native_input),stageStart=start+(stage==='D'?1200000:Number(stage.slice(1))*160000),stageEnd=stageStart+duration;
  check(id+'_pipe_limits',native[0].length<=2048&&native[1].length<=768&&native[0].length+native[1].length<=4096);
  const external=stage==='C1'?upstream.external:upstream.externalSHA,begin='await gate2Resume.cd.begin('+[stage,args,...upstream.pins,external].map(canon).join(',')+');',next='await gate2Resume.cd.poll(1);';
  const text=snapshot(id,2,native,input,{failure:form.failure},stageEnd-3000,[stageStart,stageEnd],null),codes=[begin,...Array(5).fill(next)],frames=codes.map((code,i)=>provider(i===5?text:JSON.stringify([0,stage,4294967295,null]),i+1));
  const selected=canon({call:{tool:'mcp__node_repl__js',timeout_ms:32000,codes},frames});keep(id+'_selected',selected,4096);keep(id+'_native_input',form.native_input,32768);
  if(selected.length>4096)continue;
  const w=writer(id,selected,2000,4096,16384,[stageStart,stageEnd],stageEnd-2000);keep(id+'_ack',w.header,16384);keep(id+'_writer_stdout',w.raw.toString('ascii'),2112);
  bound(id+'_writer_forms_bound',w.formsOK);bound(id+'_writer_input_bound',w.input.length<=81920);
 }
}
"""


D23_GEOMETRY_STDIO = r"""'use strict';
let chunks=[],inputBytes=0,failed=false;
const report={schema_version:1,case:'geometry',node_version:process.versions.node,completed:false,cause:null,checks:[],measurements:[]};
function check(id,ok){report.checks.push({id,ok:!!ok});if(!ok)throw Error('d23_driver_assertion');}
function measure(id,text){if(typeof text!=='string'||/[^\x00-\x7f]/.test(text)||text.length>262144)throw Error('d23_driver_assertion');report.measurements.push({id,size_bytes:text.length,sha256:gate2SHA256(text)});}
function budget(cause='selected_wire_deadline',now=()=>performance.now(),end=Infinity){return gate2WireBudget(now,cause,end);}
function decoded(text,tag='gate2-selected-lz77-v1',guard=budget()){return gate2WireDecode(text,tag,gate2SHA256,gate2Canonical,guard);}
function encoded(text,tag='gate2-selected-lz77-v1',guard=budget('selected_wire_root_deadline')){return gate2WireEncode(text,tag,gate2SHA256,gate2Canonical,guard);}
function finish(cause){if(failed)return;failed=true;report.cause=cause;process.stdout.write(gate2Canonical(report,32767)+'\n');}
process.stdin.on('error',()=>finish('d23_driver_input'));
process.stdin.on('data',b=>{if(failed)return;inputBytes+=b.length;if(inputBytes>262144){finish('d23_driver_input');process.stdin.destroy();return;}chunks.push(b);});
process.stdin.on('end',()=>{if(failed)return;try{
 const bytes=Buffer.concat(chunks);chunks=[];if(bytes.some(x=>x>127))throw Error('d23_driver_input');
 const text=bytes.toString('ascii'),request=JSON.parse(text);
 if(!request||typeof request!=='object'||Array.isArray(request)||Object.keys(request).sort().join()!=='case,data'||request.case!=='geometry'||gate2Canonical(request,262144)!==text)throw Error('d23_driver_input');
 if(process.versions.node!=='25.2.1')throw Error('d23_node_version');
 if(typeof gate2WireEncode!=='function'||typeof gate2WireDecode!=='function'||typeof gate2WireBudget!=='function')throw Error('d23_codec_absent');
 d23Geometry(request.data,report);
 if(report.checks.every(row=>row.ok)){report.completed=true;finish(null);}else finish('d23_geometry_hold');
 }catch(e){finish(new Set(['d23_codec_absent','d23_driver_assertion','d23_driver_input','d23_node_version']).has(e.message)?e.message:'d23_driver_error');}});
"""


def d23_geometry_driver_v1():
    return (ROOT_ENCODER + '\n' + ROOT_SHA256 + '\n' + D23_WIRE_CODEC
            + '\n' + D23_GEOMETRY_DRIVER + '\n' + D23_GEOMETRY_STDIO)


class D23CompleteGeometryTests(unittest.TestCase):
    def test_complete_form_bounds_preserve_hold(self):
        # Historical DATA-only observation, not another construction/run or fit proof.
        # The two original descriptors identify retained external evidence; this
        # portable test authenticates the embedded metadata, without Temp reads.
        originals = {
            'stdout': ('vast-d23-geometry-complete-01-20261018-01.stdout.original.txt',
                       16587, 'e057f904a2ff342de53066c8755f191629db289ca780b42424099b6e69645560'),
            'derived': ('vast-d23-geometry-complete-01-20261018-01.derived.json',
                        3034, 'd5818a23c90fa634355b4b8a358c5f7401509be2c326b644f4d881234038b431')}
        report_text = r'''{"case":"geometry","cause":"d23_geometry_hold","checks":[{"id":"source_bindings","ok":true},{"id":"initial_source_bound","ok":true},{"id":"finalizer_source_bound","ok":true},{"id":"executor_source_bound","ok":true},{"id":"six_setup_forms","ok":true},{"id":"success_setup","ok":true},{"id":"success_provider_pipes","ok":true},{"id":"success_pipe0_inverse","ok":true},{"id":"success_pipe1_inverse","ok":true},{"id":"success_pipe2_inverse","ok":true},{"id":"success_selected_original_bound","ok":true},{"id":"success_wire_geometry","ok":false},{"id":"structured_failure_setup","ok":true},{"id":"structured_failure_provider_pipes","ok":true},{"id":"structured_failure_pipe0_inverse","ok":true},{"id":"structured_failure_pipe1_inverse","ok":true},{"id":"structured_failure_pipe2_inverse","ok":true},{"id":"structured_failure_selected_original_bound","ok":true},{"id":"structured_failure_wire_geometry","ok":false},{"id":"unicode_failure_setup","ok":true},{"id":"unicode_failure_provider_pipes","ok":true},{"id":"unicode_failure_pipe0_inverse","ok":true},{"id":"unicode_failure_pipe1_inverse","ok":true},{"id":"unicode_failure_pipe2_inverse","ok":true},{"id":"unicode_failure_selected_original_bound","ok":true},{"id":"unicode_failure_wire_geometry","ok":false},{"id":"partial_emission_setup","ok":true},{"id":"partial_emission_provider_pipes","ok":true},{"id":"partial_emission_pipe0_inverse","ok":true},{"id":"partial_emission_pipe1_inverse","ok":true},{"id":"partial_emission_pipe2_inverse","ok":true},{"id":"partial_emission_selected_original_bound","ok":true},{"id":"partial_emission_observed_original_bound","ok":true},{"id":"partial_emission_selected_wire_bound","ok":true},{"id":"partial_emission_observed_wire_bound","ok":true},{"id":"partial_emission_full_roundtrip","ok":true},{"id":"partial_emission_uint64","ok":true},{"id":"partial_emission_writer_pipe0_inverse","ok":true},{"id":"partial_emission_writer_pipe1_inverse","ok":true},{"id":"partial_emission_ack_bound","ok":true},{"id":"partial_emission_writer_stdout_bound","ok":true},{"id":"partial_emission_writer_input_bound","ok":true},{"id":"partial_emission_forms_bound","ok":true},{"id":"partial_emission_chain_join","ok":true},{"id":"partial_emission_root_bound","ok":false},{"id":"partial_emission_chain_bound","ok":true},{"id":"unknown_closure_setup","ok":true},{"id":"unknown_closure_provider_pipes","ok":true},{"id":"unknown_closure_pipe0_inverse","ok":true},{"id":"unknown_closure_pipe1_inverse","ok":true},{"id":"unknown_closure_pipe2_inverse","ok":true},{"id":"unknown_closure_selected_original_bound","ok":true},{"id":"unknown_closure_wire_geometry","ok":false},{"id":"setup_refusal_setup","ok":true},{"id":"setup_refusal_provider_pipes","ok":true},{"id":"setup_refusal_pipe0_inverse","ok":true},{"id":"setup_refusal_pipe1_inverse","ok":true},{"id":"setup_refusal_pipe2_inverse","ok":true},{"id":"setup_refusal_selected_original_bound","ok":true},{"id":"setup_refusal_observed_original_bound","ok":true},{"id":"setup_refusal_selected_wire_bound","ok":true},{"id":"setup_refusal_observed_wire_bound","ok":true},{"id":"setup_refusal_full_roundtrip","ok":true},{"id":"setup_refusal_uint64","ok":true},{"id":"setup_refusal_writer_pipe0_inverse","ok":true},{"id":"setup_refusal_writer_pipe1_inverse","ok":true},{"id":"setup_refusal_ack_bound","ok":true},{"id":"setup_refusal_writer_stdout_bound","ok":true},{"id":"setup_refusal_writer_input_bound","ok":true},{"id":"setup_refusal_forms_bound","ok":true},{"id":"setup_refusal_chain_join","ok":true},{"id":"setup_refusal_root_bound","ok":false},{"id":"setup_refusal_chain_bound","ok":true},{"id":"six_later_forms","ok":true},{"id":"later_measured_upstream","ok":false}],"completed":false,"measurements":[{"id":"initial_source","sha256":"242f28752079f1d2b50a410d0f2606a3097899b8ca95e2add43068483609cff5","size_bytes":13841},{"id":"finalizer_source","sha256":"d189b35ea0689b04f512420efe4a4d0aabd13fc3c5a5d4c3ffff94f5350e05ba","size_bytes":36323},{"id":"executor_source","sha256":"1f83e0fb4755a802dee800e907f89272ff7f37b63c79d167e76427babb96b26d","size_bytes":79021},{"id":"success_selected_original","sha256":"220b19487bd779e29af883f07594aa6a2f3ce445817e7c9cb6e8b5b3fdbcedfe","size_bytes":16747},{"id":"success_wire_refusal","sha256":"17f54ba84e38766575c165a616f7755840343aa043663bd0f9f2f833393831a6","size_bytes":19},{"id":"structured_failure_selected_original","sha256":"146339a54bbff1088e7686b32c28d8e0a9d6486b7c0a3896113fe337846d9f6d","size_bytes":16973},{"id":"structured_failure_wire_refusal","sha256":"17f54ba84e38766575c165a616f7755840343aa043663bd0f9f2f833393831a6","size_bytes":19},{"id":"unicode_failure_selected_original","sha256":"96bc0da40e2487ca04873f90551579fcd428bbbf0b8f283e795e15d93b7f4fca","size_bytes":16873},{"id":"unicode_failure_wire_refusal","sha256":"17f54ba84e38766575c165a616f7755840343aa043663bd0f9f2f833393831a6","size_bytes":19},{"id":"partial_emission_selected_original","sha256":"aa26d15d63d3183995a6527a4119256f2afe336cb62db392f0f37cef15326f61","size_bytes":16466},{"id":"partial_emission_observed_original","sha256":"1fdd77c65ddd76a1d42e6757aa8db67ca21538d3b0b23029e398fcc5098be461","size_bytes":16578},{"id":"partial_emission_selected_wire","sha256":"6313c06656667d6b0217d530939cf5f440bf0b8243f32e969c7340e79a167e9f","size_bytes":12199},{"id":"partial_emission_observed_wire","sha256":"07caed1f4fe194eee19049ea7e372bca8086f9a0004785c009969ebcb574a134","size_bytes":12185},{"id":"partial_emission_ack","sha256":"da51ed393ef69aa92e936e818e05fbe59a83cd3c05adb96025bb46e16779e0df","size_bytes":16407},{"id":"partial_emission_writer_stdout","sha256":"c64a544cafeb10e147177aeba9c21b7eaddaaaf41bb4dff032b9d497be099c96","size_bytes":744},{"id":"partial_emission_root","sha256":"3af449b2f86b83f55847c89dbf7aae83f8d6e33b43620203a1408214a779acf2","size_bytes":77125},{"id":"partial_emission_chain","sha256":"71d787f842bf5e7973860de77ca546c9ee6165720d8975a8b3eaeb15fbef10f7","size_bytes":160722},{"id":"unknown_closure_selected_original","sha256":"aea82127424e8b49efe6a0eda442f871b80f56d86886182322718d7f50f95d50","size_bytes":16751},{"id":"unknown_closure_wire_refusal","sha256":"17f54ba84e38766575c165a616f7755840343aa043663bd0f9f2f833393831a6","size_bytes":19},{"id":"setup_refusal_selected_original","sha256":"f1061cb0c6fdbc6d14a9911c7a6701d9e209018e9670e67276fed1d409901d3e","size_bytes":15827},{"id":"setup_refusal_observed_original","sha256":"76244359a759d33ec8bdd32801ad6111eab84a1f9468930deb965d90fbd0c3ec","size_bytes":15939},{"id":"setup_refusal_selected_wire","sha256":"5a2ceecac71f7f425c658f8cbfca21a7047862fd768129719729e8ed23092d99","size_bytes":11535},{"id":"setup_refusal_observed_wire","sha256":"9514e01d9ae965abacdd5fb621972d18a351c776d47c145426569f91be96a934","size_bytes":11521},{"id":"setup_refusal_ack","sha256":"87119479c1ae8beddd57870c2086bdf29ec4e14be698ff4898f2d9f7f3ef4067","size_bytes":15519},{"id":"setup_refusal_writer_stdout","sha256":"101fcaa5c6cacc9209345cada97971fadf114cbfe54a4da2124ae5812b2b0a52","size_bytes":744},{"id":"setup_refusal_root","sha256":"61aa7626e09187dcee77a98ac33e3c836851f06e67f8f5239dce33ec1748b201","size_bytes":75063},{"id":"setup_refusal_chain","sha256":"14c38adfe2b7a09055fa1a956f334ae77ebf4e71d1e85d7153fc7007407e7f70","size_bytes":158548}],"node_version":"25.2.1","schema_version":1}
'''
        derived_text = r'''{"channels":{"stderr":{"close_attempted":true,"closed":true,"closure_unknown":false,"eof":true,"error":null,"observed_bytes":0,"overflow":false,"remainder_unknown":false,"secondary":[],"sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","size_bytes":0},"stdout":{"close_attempted":true,"closed":true,"closure_unknown":false,"eof":true,"error":null,"observed_bytes":16587,"overflow":false,"remainder_unknown":false,"secondary":[],"sha256":"e057f904a2ff342de53066c8755f191629db289ca780b42424099b6e69645560","size_bytes":16587}},"child_completion_before_cleanup_end":true,"child_completion_before_total_end":true,"child_completion_observed_at":1882888.7578236,"child_total_deadline":1882918.1639225,"child_total_seconds":30,"child_work_seconds":27,"cleanup_deadline":1882891.7578086,"deadline_seconds":300,"descendant_quiescence":"UNKNOWN","elapsed_before_report_write_s":0.6135428000707179,"forced_test_child":false,"generated_operational_program_execution":false,"geometry_fully_measured":false,"geometry_risk_passed":false,"geometry_source_kind":"d23_inert_source_construction_metadata_v1","held_driver_loader_binding_validated":true,"io_failure":false,"kind":"d23_local_inert_geometry_test_parent_observation_v1","ordered_causes":[],"parent_observed_test_transport_complete":true,"protocol_error_type":null,"python":"3.14.7","returncode":1,"selected_class":"D23CompleteGeometryTests","self_report_persistence_or_whole_process_attested":false,"source_binding_policy":"both_held_test_buffers_before_either_compile","source_binding_record_validated":true,"source_execution_reopens_paths":false,"source_pins":[{"path":"tests/test_accepted_policy_fixture_compiler_gate2_resume_v1.py","sha256":"29aa4615838ac5fc32fa73db05cbde6d39a028ec9791860325e2d276019a69a6","size_bytes":325957},{"path":"tests/test_accepted_policy_fixture_compiler_gate2_resume_caller_v1.py","sha256":"769c0ee4887e44f4cda1e3dbbfc9c908e3ff8d450f5b86ea98b8c018bb2abc09","size_bytes":223289}],"suite_mode":"geometry","test_summary":{"descendant_quiescence":"UNKNOWN","errors":0,"event":"test_summary","expected_failures":0,"expected_metadata_records":2,"failures":1,"generated_operational_program_execution":false,"geometry_case_records":1,"geometry_source_records":1,"issue_events":1,"parent_outcomes":{"failure":1},"selected_class":"D23CompleteGeometryTests","skips":0,"subtest_callbacks":0,"successes":0,"successful":false,"test_streams":{"stderr":{"geometry_case_records":0,"geometry_source_records":0,"metadata_records":0,"observed_bytes":0,"raw_values_retained":false,"sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","unexpected_or_unterminated":false},"stdout":{"geometry_case_records":1,"geometry_source_records":1,"metadata_records":2,"observed_bytes":13738,"raw_values_retained":false,"sha256":"0df85d8310461fe84bc89af03c53e2dcc77ed1cf040e415223a1ff3de10b9f72","unexpected_or_unterminated":false}},"tests_run":1,"unexpected_successes":0},"threads_joined":true,"timed_out":false,"work_deadline":1882915.1639225}
'''
        for text, size, digest in (
                (report_text, 7282, '102efcf2b9254c2e17a65aae31d2a92a39ae0d7a2f2aaecb7bb41907729dc0e3'),
                (derived_text, originals['derived'][1], originals['derived'][2])):
            raw = text.encode('ascii')
            self.assertLessEqual(len(raw), 32768)
            self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()), (size, digest))
        report = json.loads(report_text)
        observation = json.loads(derived_text)
        expected_measurements = ('initial_source', 'finalizer_source', 'executor_source', 'success_selected_original', 'success_wire_refusal', 'structured_failure_selected_original', 'structured_failure_wire_refusal', 'unicode_failure_selected_original', 'unicode_failure_wire_refusal', 'partial_emission_selected_original', 'partial_emission_observed_original', 'partial_emission_selected_wire', 'partial_emission_observed_wire', 'partial_emission_ack', 'partial_emission_writer_stdout', 'partial_emission_root', 'partial_emission_chain', 'unknown_closure_selected_original', 'unknown_closure_wire_refusal', 'setup_refusal_selected_original', 'setup_refusal_observed_original', 'setup_refusal_selected_wire', 'setup_refusal_observed_wire', 'setup_refusal_ack', 'setup_refusal_writer_stdout', 'setup_refusal_root', 'setup_refusal_chain')
        expected_checks = ('source_bindings', 'initial_source_bound', 'finalizer_source_bound', 'executor_source_bound', 'six_setup_forms', 'success_setup', 'success_provider_pipes', 'success_pipe0_inverse', 'success_pipe1_inverse', 'success_pipe2_inverse', 'success_selected_original_bound', 'success_wire_geometry', 'structured_failure_setup', 'structured_failure_provider_pipes', 'structured_failure_pipe0_inverse', 'structured_failure_pipe1_inverse', 'structured_failure_pipe2_inverse', 'structured_failure_selected_original_bound', 'structured_failure_wire_geometry', 'unicode_failure_setup', 'unicode_failure_provider_pipes', 'unicode_failure_pipe0_inverse', 'unicode_failure_pipe1_inverse', 'unicode_failure_pipe2_inverse', 'unicode_failure_selected_original_bound', 'unicode_failure_wire_geometry', 'partial_emission_setup', 'partial_emission_provider_pipes', 'partial_emission_pipe0_inverse', 'partial_emission_pipe1_inverse', 'partial_emission_pipe2_inverse', 'partial_emission_selected_original_bound', 'partial_emission_observed_original_bound', 'partial_emission_selected_wire_bound', 'partial_emission_observed_wire_bound', 'partial_emission_full_roundtrip', 'partial_emission_uint64', 'partial_emission_writer_pipe0_inverse', 'partial_emission_writer_pipe1_inverse', 'partial_emission_ack_bound', 'partial_emission_writer_stdout_bound', 'partial_emission_writer_input_bound', 'partial_emission_forms_bound', 'partial_emission_chain_join', 'partial_emission_root_bound', 'partial_emission_chain_bound', 'unknown_closure_setup', 'unknown_closure_provider_pipes', 'unknown_closure_pipe0_inverse', 'unknown_closure_pipe1_inverse', 'unknown_closure_pipe2_inverse', 'unknown_closure_selected_original_bound', 'unknown_closure_wire_geometry', 'setup_refusal_setup', 'setup_refusal_provider_pipes', 'setup_refusal_pipe0_inverse', 'setup_refusal_pipe1_inverse', 'setup_refusal_pipe2_inverse', 'setup_refusal_selected_original_bound', 'setup_refusal_observed_original_bound', 'setup_refusal_selected_wire_bound', 'setup_refusal_observed_wire_bound', 'setup_refusal_full_roundtrip', 'setup_refusal_uint64', 'setup_refusal_writer_pipe0_inverse', 'setup_refusal_writer_pipe1_inverse', 'setup_refusal_ack_bound', 'setup_refusal_writer_stdout_bound', 'setup_refusal_writer_input_bound', 'setup_refusal_forms_bound', 'setup_refusal_chain_join', 'setup_refusal_root_bound', 'setup_refusal_chain_bound', 'six_later_forms', 'later_measured_upstream')

        def dimensions(document):
            # Missing/duplicate/changed metadata is refusal, never a smaller
            # apparently passing collection after unavailable dimensions vanish.
            if set(document) != {'schema_version', 'case', 'node_version', 'completed',
                                 'cause', 'checks', 'measurements'}:
                raise ValueError('report_shape')
            measures = document['measurements']
            tests = document['checks']
            if not isinstance(measures, list) or not isinstance(tests, list):
                raise ValueError('row_shape')
            for row in measures:
                if (not isinstance(row, dict) or set(row) != {'id', 'size_bytes', 'sha256'}
                        or not isinstance(row['id'], str)
                        or type(row['size_bytes']) is not int or row['size_bytes'] <= 0
                        or not isinstance(row['sha256'], str)
                        or len(row['sha256']) != 64
                        or any(c not in '0123456789abcdef' for c in row['sha256'])):
                    raise ValueError('measurement_shape')
            for row in tests:
                if (not isinstance(row, dict) or set(row) != {'id', 'ok'}
                        or not isinstance(row['id'], str) or type(row['ok']) is not bool):
                    raise ValueError('check_shape')
            if tuple(row['id'] for row in measures) != expected_measurements:
                raise ValueError('measurement_dimension')
            if tuple(row['id'] for row in tests) != expected_checks:
                raise ValueError('check_dimension')
            return ({row['id']: row for row in measures},
                    {row['id']: row['ok'] for row in tests})

        measurements, checks = dimensions(report)
        self.assertEqual((len(measurements), len(checks)), (27, 75))
        self.assertEqual((report['schema_version'], report['case'], report['node_version']),
                         (1, 'geometry', '25.2.1'))
        self.assertIs(report['completed'], False)
        self.assertEqual(report['cause'], 'd23_geometry_hold')
        self.assertIs(observation['geometry_fully_measured'], False)
        self.assertIs(observation['geometry_risk_passed'], False)
        self.assertTrue(observation['parent_observed_test_transport_complete'])
        self.assertEqual(observation['returncode'], 1)
        self.assertFalse(observation['forced_test_child'])
        self.assertFalse(observation['timed_out'])
        self.assertTrue(observation['threads_joined'])
        self.assertEqual(observation['descendant_quiescence'], 'UNKNOWN')
        self.assertFalse(observation['generated_operational_program_execution'])
        self.assertFalse(observation['self_report_persistence_or_whole_process_attested'])
        self.assertEqual((observation['test_summary']['tests_run'],
                          observation['test_summary']['failures'],
                          observation['test_summary']['errors']), (1, 1, 0))
        self.assertEqual((observation['channels']['stdout']['size_bytes'],
                          observation['channels']['stdout']['sha256']), originals['stdout'][1:])
        for channel in observation['channels'].values():
            self.assertTrue(channel['eof'])
            self.assertTrue(channel['closed'])
            self.assertFalse(channel['overflow'])
            self.assertFalse(channel['closure_unknown'])
            self.assertFalse(channel['remainder_unknown'])

        # A refusal fingerprint is an observed cause, not a measured wire extent.
        refused = ('success', 'structured_failure', 'unicode_failure', 'unknown_closure')
        refusal_sha = '17f54ba84e38766575c165a616f7755840343aa043663bd0f9f2f833393831a6'
        self.assertEqual(hashlib.sha256(b'selected_wire_bound').hexdigest(), refusal_sha)
        for form in refused:
            self.assertEqual(measurements[form + '_wire_refusal'],
                             {'id': form + '_wire_refusal', 'size_bytes': 19,
                              'sha256': refusal_sha})
            self.assertFalse(checks[form + '_wire_geometry'])
            for suffix in ('selected_wire', 'observed_wire', 'observed_original',
                           'ack', 'writer_stdout', 'root', 'chain'):
                self.assertNotIn(form + '_' + suffix, measurements)
            self.assertLessEqual(measurements[form + '_selected_original']['size_bytes'], 32768)

        # These are the only measured wire/ROOT paths. Their ROOT overruns remain
        # failures even though both wire forms and the full public chains fit.
        for form, wire_sizes, root_size, overrun, chain_size in (
                ('partial_emission', (12199, 12185), 77125, 11589, 160722),
                ('setup_refusal', (11535, 11521), 75063, 9527, 158548)):
            self.assertEqual(tuple(measurements[form + '_' + suffix]['size_bytes']
                                   for suffix in ('selected_wire', 'observed_wire')), wire_sizes)
            self.assertTrue(all(size <= 12288 for size in wire_sizes))
            self.assertEqual(measurements[form + '_root']['size_bytes'], root_size)
            self.assertEqual(root_size - 65536, overrun)
            self.assertFalse(checks[form + '_root_bound'])
            self.assertEqual(measurements[form + '_chain']['size_bytes'], chain_size)
            self.assertLessEqual(chain_size, 262144)
            self.assertTrue(checks[form + '_chain_bound'])
            self.assertTrue(checks[form + '_chain_join'])
        self.assertFalse(checks['later_measured_upstream'])
        later = ('C1_success', 'C1_failure', 'C6_success', 'C6_failure', 'D_success', 'D_failure')
        self.assertTrue(checks['six_later_forms'])  # declaration count only
        for form in later:
            self.assertFalse(any(name.startswith(form + '_') for name in measurements))

        # Complete geometry requires all original/wire/ROOT/chain dimensions for
        # six setup forms plus actual selected/native-input dimensions for all
        # six later alternatives. Deleting negatives cannot manufacture that.
        required = {'initial_source', 'finalizer_source', 'executor_source'}
        for form in refused + ('partial_emission', 'setup_refusal'):
            required.update(form + '_' + suffix for suffix in (
                'selected_original', 'observed_original', 'selected_wire', 'observed_wire',
                'ack', 'writer_stdout', 'root', 'chain'))
        for form in later:
            required.update(form + '_' + suffix for suffix in ('selected', 'native_input'))
        fully_measured = required <= set(measurements) and all(
            ok or name.endswith('_bound') for name, ok in checks.items())
        risk_passed = fully_measured and all(checks.values()) and report['completed']
        self.assertFalse(fully_measured)
        self.assertFalse(risk_passed)
        self.assertEqual(fully_measured, observation['geometry_fully_measured'])
        self.assertEqual(risk_passed, observation['geometry_risk_passed'])

        # Meaningful metadata-corruption controls, with no source construction,
        # subprocess, codec or operational program execution.
        for dimension in ('partial_emission_root', 'setup_refusal_chain', 'initial_source'):
            changed = json.loads(report_text)
            changed['measurements'] = [row for row in changed['measurements']
                                       if row['id'] != dimension]
            with self.assertRaisesRegex(ValueError, '^measurement_dimension$'):
                dimensions(changed)
        for dimension in ('success_wire_geometry', 'later_measured_upstream'):
            changed = json.loads(report_text)
            changed['checks'] = [row for row in changed['checks'] if row['id'] != dimension]
            with self.assertRaisesRegex(ValueError, '^check_dimension$'):
                dimensions(changed)
        trimmed = json.loads(report_text)
        trimmed['checks'] = [row for row in trimmed['checks'] if row['ok']]
        self.assertTrue(all(row['ok'] for row in trimmed['checks']))
        with self.assertRaisesRegex(ValueError, '^check_dimension$'):
            dimensions(trimmed)


if __name__ == '__main__':
    unittest.main()


def d24_phase_initial_v1(deadline):
    """Build one unpooled phase source in RAM; no geometry or behavior acceptance."""
    import base64
    import math
    import time
    import zlib

    compression = None

    def refuse(cause):
        error = RuntimeError(cause)
        error.metadata = compression
        error.capture = compression
        raise error

    if type(deadline) not in (int, float):
        refuse('d24_construction_deadline')
    try:
        end = float(deadline)
    except (OverflowError, ValueError):
        refuse('d24_construction_deadline')
    if not math.isfinite(end) or end - time.monotonic() > 300:
        refuse('d24_construction_deadline')

    def gate():
        if time.monotonic() >= end - 5:
            refuse('d24_construction_deadline')

    def replace_once(text, before, after, cause):
        if text.count(before) != 1:
            refuse(cause)
        changed = text.replace(before, after, 1)
        if changed.count(after) != 1:
            refuse(cause)
        return changed

    gate()
    if (type(D22_PREFIX) is not str or len(D22_PREFIX) != 295 or not D22_PREFIX.isascii()
            or d22_sha(D22_PREFIX.encode('ascii')) !=
            'ea63175835e2149d61c71d52696c62033d17b908f76ca0a20cf25e32b18f142b'):
        refuse('d24_prefix_binding')
    root = Path(__file__).resolve().parents[1]
    rows = []
    fixtures = (
        ('tests/fixtures/accepted_policy_fixture_compiler_component_v1.py', 32732,
         '329fb13f2c6dcee0872e5a29ec1fd769dc6e57ce92ee1076fef6737f1da86d88',
         '5a342c2c2efa44aa5add3f91ae94518c143acece'),
        ('tests/fixtures/accepted_policy_fixture_compiler_gate2_resume_v1.py', 32739,
         '5fd7d2d6ee62ff584d2a4662757ca804a3d3300d30bb966319901870c4c85670',
         'cc9b6a1b7e6e6ff2f9b750ea67b20cf7213d09b0'))
    for name, size, digest, blob in fixtures:
        gate()
        with (root / name).open('rb') as handle:
            held = handle.read(32769)
        gate()
        actual_blob = hashlib.sha1(b'blob ' + str(len(held)).encode() + b'\0' + held).hexdigest()
        if (len(held), d22_sha(held), actual_blob) != (size, digest, blob):
            refuse('d24_fixture_binding')
        rows.append(['C:/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/' + name,
                     {'size_bytes': len(held), 'sha256': d22_sha(held), 'git_blob': actual_blob}])
    data = {
        'approval': 'https://github.com/lordcoudy/VAST/pull/9#issuecomment-1234567890',
        'commit': hashlib.sha1(b'controlled-current-review').hexdigest(),
        'common': NODE_SHARED_PYTHON, 'fields': list(NODE_FIELDS),
        'pipe_fields': list(NODE_PIPE_FIELDS),
        'root': '/home/s-a-balashov/work/vast-fixture-compiler-gate2-465ab7986939c67ae3594344ee3b6266cd2abd7a-01/r1',
        'setup_head': NODE_SETUP_HEAD, 'setup_tail': NODE_SETUP_TAIL, 'sources': rows}
    expected_keys = ('approval', 'commit', 'common', 'fields', 'pipe_fields', 'root',
                     'setup_head', 'setup_tail', 'sources')
    raw = d22_canonical(data)
    if (tuple(sorted(data)) != expected_keys or not raw.isascii()
            or not 0 < len(raw) <= 16384
            or json.dumps(json.loads(raw), sort_keys=True, separators=(',', ':'),
                          ensure_ascii=True, allow_nan=False).encode('ascii') != raw):
        refuse('d24_original_data_binding')
    raw_digest = d22_sha(raw)
    gate()
    plain, _ = d22_build_plain(data)
    gate()
    marker = "var {spawn:g2s}=await import('node:child_process');"
    if (type(plain) is not str or not plain.isascii() or len(D22_PREFIX) != 295
            or not plain.startswith(D22_PREFIX) or plain.count(marker) != 1):
        refuse('d24_original_builder_binding')
    at = plain.index(marker)
    original_decoder = plain[len(D22_PREFIX):at]
    baseline_body = plain[at:]
    try:
        from tests.test_accepted_policy_fixture_compiler_gate2_resume_caller_v1 import d22_compress_data_v1
        packed, compression = d22_compress_data_v1(raw, end)
    except Exception as error:
        compression = getattr(error, 'metadata', getattr(error, 'capture', None))
        refuse('d24_compression_refusal')
    gate()
    if type(packed) is not bytes or not 0 < len(packed) <= 32768:
        refuse('d24_compressed_data_binding')
    try:
        observed = compression['started_monotonic'] + compression['elapsed_seconds']
        complete = (
            type(compression) is dict and compression['parent_observed_completion'] is True
            and compression['causes'] == [] and type(compression['returncode']) is int
            and compression['returncode'] == 0 and compression['timed_out'] is False
            and compression['kill_requested'] is False and compression['reaped'] is True
            and compression['threads_joined'] is True
            and compression['stdin_complete'] is True and compression['stdin_closed'] is True
            and compression['stdin_extent_unknown'] is False
            and compression['stdin_write_in_flight'] is False
            and compression['stdin_bytes'] == len(raw)
            and compression['input_bytes'] == len(raw) and compression['input_sha256'] == raw_digest
            and compression['packed_bytes'] == len(packed)
            and compression['packed_sha256'] == d22_sha(packed)
            and compression['node_version'] == '25.2.1'
            and type(compression['quality']) is int and compression['quality'] == 11
            and compression['roundtrip'] is True and compression['data_only'] is True
            and compression['finished_before_deadline'] is True
            and compression['child_completion_observed_before_deadline'] is True
            and compression['caller_deadline'] == end
            and math.isfinite(observed) and compression['elapsed_seconds'] >= 0
            and observed < compression['cleanup_deadline']
            and observed < compression['child_total_deadline'] and observed < end
            and compression['descendant_quiescence'] == 'UNKNOWN'
            and all(compression[name]['eof'] is True and compression[name]['closed'] is True
                    and compression[name]['overflow'] is False
                    and compression[name]['io_error'] is None
                    and compression[name]['unknown_remainder'] is False
                    for name in ('stdout', 'stderr'))
            and compression['stderr']['retained_bytes'] == 0
            and compression['stderr_prefix_b64'] == '')
    except (KeyError, TypeError, ValueError, OverflowError):
        complete = False
    if not complete:
        refuse('d24_compression_capture_incomplete')
    encoded = base64.b64encode(packed).decode('ascii')
    zpacked = zlib.compress(raw, 9)
    previous = base64.b64encode(zpacked).decode('ascii')
    substitutions = (
        (json.dumps(previous), json.dumps(encoded)),
        ('if(g2packed.length!==' + str(len(previous)) + '||',
         'if(g2packed.length!==' + str(len(encoded)) + '||'),
        ('if(g2compressed.length!==' + str(len(zpacked)) + ')',
         'if(g2compressed.length!==' + str(len(packed)) + ')'),
        ('inflateSync:g2inflate', 'brotliDecompressSync:g2inflate'))
    decoder = original_decoder
    for before, after in substitutions:
        decoder = replace_once(decoder, before, after, 'd24_decoder_source_site')
    inverse_decoder = decoder
    for before, after in reversed(substitutions):
        inverse_decoder = replace_once(inverse_decoder, after, before, 'd24_decoder_inverse_site')
    if inverse_decoder != original_decoder:
        refuse('d24_decoder_inverse')
    if NODE_VALIDATORS.count('__COMMIT__') != 1 or NODE_VALIDATORS.count('__ROOT__') != 1:
        refuse('d24_validator_placeholder_sites')
    validators = NODE_VALIDATORS.replace('__COMMIT__', 'g2data.commit', 1).replace('__ROOT__', 'g2data.root', 1)
    if validators.replace('g2data.commit', '__COMMIT__', 1).replace('g2data.root', '__ROOT__', 1) != NODE_VALIDATORS:
        refuse('d24_validator_placeholder_inverse')
    early = "g2.commit=g2data.commit;g2.root=g2data.root;\ng2.need=(v,c)=>{if(!v)throw Error(c);};\n"
    feature = "g2.need(typeof JSON.rawJSON==='function'&&JSON.parse('1',(k,v,c)=>c?.source)==='1','parse_source_feature');\n"
    capture = "Object.defineProperty(g2,'_gate2CreateHash',{value:g2h,enumerable:false,writable:false,configurable:false});\n"
    old_output = 'g2.last_setup=snapshot;g2.setup_success=false;try{g2.setupView(snapshot);g2.setup_success=true;}catch(e){g2.setup_refusal=String(e.message);}'
    new_output = 'g2.last_setup=snapshot;g2.setup_success=null;'
    if validators.count(early) != 1 or validators.count(feature) != 1:
        refuse('d24_phase_definition_sites')
    deferred = validators.replace(early, '', 1).replace(feature, '', 1)
    phase_body = replace_once(baseline_body, validators, early + feature + capture,
                              'd24_phase_source_site')
    phase_body = replace_once(phase_body, old_output, new_output, 'd24_phase_output_site')
    inverse_body = replace_once(phase_body, new_output, old_output, 'd24_phase_output_inverse_site')
    inverse_body = replace_once(inverse_body, early + feature + capture, validators,
                                'd24_phase_inverse_site')
    if inverse_body != baseline_body:
        refuse('d24_phase_inverse')
    # No separator, pooling, lexical rewriting, shortening or source loader.
    baseline = D22_PREFIX + decoder + baseline_body
    initial = D22_PREFIX + decoder + phase_body
    restored = D22_PREFIX + decoder + inverse_body
    if restored != baseline or D22_PREFIX + inverse_decoder + inverse_body != plain:
        refuse('d24_full_inverse_source')
    gate()
    escaped = len(d22_canonical(initial))
    fit = escaped <= 12288
    facts = {
        'kind': 'd24_initial_source_only_v1',
        'source_bytes': len(initial), 'source_sha256': d22_sha(initial.encode('ascii')),
        'escaped_source_bytes': escaped,
        'baseline_bytes': len(baseline), 'baseline_sha256': d22_sha(baseline.encode('ascii')),
        'original_builder_bytes': len(plain), 'original_builder_sha256': d22_sha(plain.encode('ascii')),
        'baseline_body_bytes': len(baseline_body),
        'baseline_body_sha256': d22_sha(baseline_body.encode('ascii')),
        'prefix_bytes': len(D22_PREFIX), 'prefix_sha256': d22_sha(D22_PREFIX.encode('ascii')),
        'decoder_bytes': len(decoder), 'decoder_sha256': d22_sha(decoder.encode('ascii')),
        'canonical_data_bytes': len(raw), 'canonical_data_sha256': raw_digest,
        'compressed_data_bytes': len(packed), 'compressed_data_sha256': d22_sha(packed),
        'base64_data_bytes': len(encoded), 'base64_data_sha256': d22_sha(encoded.encode('ascii')),
        'data_fields': len(data), 'strings_field_absent': 'strings' not in data,
        'deferred_definition_bytes': len(deferred),
        'deferred_definition_sha256': d22_sha(deferred.encode('ascii')),
        'exact_decoder_inverse': inverse_decoder == original_decoder,
        'exact_phase_inverse': inverse_body == baseline_body, 'exact_inverse_source': restored == baseline,
        'source_contribution_fits': fit, 'source_only_over_cap_by': max(0, escaped - 12288),
        'complete_geometry_qualified': False, 'behavior_conformance_complete': False,
        'finalizer_implemented': False, 'generated_operational_program_executed': False,
        'generated_full_subject_files_written': False,
        'status': 'UNQUALIFIED_SOURCE_ONLY' if fit else 'HOLD_SOURCE_CONTRIBUTION_OVER_CAP',
        'task_2_10_complete': False, 'compression': compression}
    if len(d22_canonical(facts)) > 32768:
        refuse('d24_metadata_bound')
    gate()
    return initial, baseline, {'phase_body': phase_body, 'restored': restored, 'deferred': deferred}, facts


def d24_node_codec_v1(codec):
    """Return the exact reviewed decoder role; ROOT must retain the full codec."""
    if type(codec) is not str or len(codec) != 5865 or not codec.isascii():
        raise RuntimeError('d24_codec_source_kind')
    raw = codec.encode('ascii')
    if (len(raw), d22_sha(raw)) != (
            5865, '56708c18c942acfb6e8153971a0013ca79c955e4182efff590ad7ae3a2ba2432'):
        raise RuntimeError('d24_codec_source_binding')
    marker = 'function gate2WireEncode(text,tag,sha,canon,guard){'
    count = codec.count(marker)
    if count != 1:
        raise RuntimeError('d24_codec_marker')
    at = codec.index(marker)
    prefix, excluded = codec[:at], codec[at:]
    if ((len(prefix), d22_sha(prefix.encode('ascii'))) != (
            3370, 'b993f35b4901e9dea83d2cef52434da60d289b6ea32185a0cf7303ec9a4b11d2')
            or (len(excluded), d22_sha(excluded.encode('ascii'))) != (
            2495, '9334f515e2fec133093cac0c409031eaae43630e83ffd723e51e0e6911ea4cdd')
            or prefix + excluded != codec):
        raise RuntimeError('d24_codec_role_binding')
    facts = {
        'kind': 'd24_node_codec_role_v1',
        'full_codec_bytes': len(raw), 'full_codec_sha256': d22_sha(raw),
        'node_codec_bytes': len(prefix), 'node_codec_sha256': d22_sha(prefix.encode('ascii')),
        'excluded_encoder_bytes': len(excluded),
        'excluded_encoder_sha256': d22_sha(excluded.encode('ascii')),
        'marker_occurrences': count, 'role_is_exact_prefix': True, 'encoder_excluded': True}
    return prefix, facts


def d24_inert_bundle_v1(deadline):
    import base64
    import math
    import sys
    import time
    from tests import test_accepted_policy_fixture_compiler_gate2_resume_caller_v1 as caller

    last = None
    def gate():
        nonlocal last
        now = time.monotonic()
        if (type(deadline) not in (int, float) or not math.isfinite(deadline)
                or not math.isfinite(now) or deadline - now > 300
                or (last is not None and now < last)
                or now >= deadline - 5):
            raise RuntimeError('d24_construction_deadline')
        last = now

    def canonical(value):
        return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                          allow_nan=False).encode('ascii')

    def digest(value):
        return hashlib.sha256(value).hexdigest()

    gate()
    node_codec, role_facts = d24_node_codec_v1(D23_WIRE_CODEC)
    root = Path(__file__).resolve().parents[1]
    descriptors = (
        ('tests/fixtures/accepted_policy_fixture_compiler_component_v1.py', 32732,
         '329fb13f2c6dcee0872e5a29ec1fd769dc6e57ce92ee1076fef6737f1da86d88',
         '5a342c2c2efa44aa5add3f91ae94518c143acece'),
        ('tests/fixtures/accepted_policy_fixture_compiler_gate2_resume_v1.py', 32739,
         '5fd7d2d6ee62ff584d2a4662757ca804a3d3300d30bb966319901870c4c85670',
         'cc9b6a1b7e6e6ff2f9b750ea67b20cf7213d09b0'))
    held = []
    source_rows = []
    for rel, size, sha, blob in descriptors:
        gate()
        with (root / rel).open('rb') as handle:
            raw = handle.read(32769)
        gate()
        if (len(raw), digest(raw), hashlib.sha1(b'blob ' + str(len(raw)).encode()
                + b'\0' + raw).hexdigest()) != (size, sha, blob):
            raise RuntimeError('d24_fixture_binding')
        held.append(base64.b64encode(raw).decode('ascii'))
        source_rows.append({'size_bytes': size, 'sha256': sha, 'git_blob': blob})
    gate()
    initial, baseline, parts, source_facts = d24_phase_initial_v1(deadline)
    compressed = source_facts['compression']
    if (compressed['parent_observed_completion'] is not True or compressed['causes']
            or compressed['returncode'] != 0 or compressed['timed_out']
            or compressed['kill_requested'] or not compressed['reaped']
            or not compressed['threads_joined']
            or compressed['started_monotonic'] + compressed['elapsed_seconds']
               >= compressed['cleanup_deadline']
            or any(not compressed[name]['eof'] or compressed[name]['overflow']
                   or compressed[name]['io_error'] is not None
                   or compressed[name]['unknown_remainder'] for name in ('stdout', 'stderr'))):
        refusal = RuntimeError('d24_compression_capture_incomplete')
        refusal.metadata = compressed
        raise refusal
    if (set(source_facts) != set('kind source_bytes source_sha256 escaped_source_bytes baseline_bytes baseline_sha256 original_builder_bytes original_builder_sha256 baseline_body_bytes baseline_body_sha256 prefix_bytes prefix_sha256 decoder_bytes decoder_sha256 canonical_data_bytes canonical_data_sha256 compressed_data_bytes compressed_data_sha256 base64_data_bytes base64_data_sha256 data_fields strings_field_absent deferred_definition_bytes deferred_definition_sha256 exact_decoder_inverse exact_phase_inverse exact_inverse_source source_contribution_fits source_only_over_cap_by complete_geometry_qualified behavior_conformance_complete finalizer_implemented generated_operational_program_executed generated_full_subject_files_written status task_2_10_complete compression'.split())
            or source_facts['kind'] != 'd24_initial_source_only_v1'
            or set(role_facts) != set('kind full_codec_bytes full_codec_sha256 node_codec_bytes node_codec_sha256 excluded_encoder_bytes excluded_encoder_sha256 marker_occurrences role_is_exact_prefix encoder_excluded'.split())
            or set(parts) != {'phase_body', 'restored', 'deferred'}
            or parts['restored'] != baseline
            or (len(initial), digest(initial.encode('ascii'))) !=
               (source_facts['source_bytes'], source_facts['source_sha256'])
            or (len(baseline), digest(baseline.encode('ascii'))) !=
               (source_facts['baseline_bytes'], source_facts['baseline_sha256'])
            or (len(parts['deferred']), digest(parts['deferred'].encode('ascii'))) !=
               (source_facts['deferred_definition_bytes'], source_facts['deferred_definition_sha256'])
            or not initial.startswith(D22_PREFIX) or source_facts['data_fields'] != 9
            or source_facts['strings_field_absent'] is not True
            or any(source_facts[name] is not True for name in
                   ('exact_decoder_inverse', 'exact_phase_inverse', 'exact_inverse_source'))):
        raise RuntimeError('d24_initial_binding')
    gate()
    finalizer, finalizer_facts = d23_finalizer_source_v1(
        initial, parts['deferred'], node_codec, sys.modules[__name__], caller)
    if (finalizer.count(node_codec) != 1 or D23_WIRE_CODEC in finalizer
            or 'function gate2WireEncode(text,tag,sha,canon,guard){' in finalizer
            or finalizer.count(ROOT_ENCODER) != 1):
        raise RuntimeError('d24_finalizer_codec_role')
    root_sources = d23_root_wire_sources_v1(D23_WIRE_CODEC)
    commit = hashlib.sha1(b'controlled-current-review').hexdigest()
    packet_sha = digest(b'packet')
    factory_sha = digest(caller.CD_FACTORY_SOURCE.encode('ascii'))
    profile = {'max_output_tokens': 100000, 'max_record_bytes': 65536}
    expected = {'code_commit': commit, 'core_sha256': digest(initial.encode('ascii')),
                'factory_sha256': factory_sha}
    prefix = ('// @exec: {"yield_time_ms":1,"max_output_tokens":100000}\n'
              + ROOT_ENCODER + '\n' + ROOT_SHA256 + '\n' + D23_WIRE_CODEC + '\n'
              + root_sources['orchestrator'] + '\n' + root_sources['receiver']
              + '\nconst profile=' + canonical(profile).decode('ascii')
              + ';const record=await gate2Complete(tools,')
    suffix = (',profile,' + canonical(expected).decode('ascii')
              + ');text(gate2Export(record,profile));\n')
    # Factor only the fixed TEST transport. The complete executor below is
    # independently pinned, and the fixed driver reconstructs exactly these
    # bytes in RAM for full-chain measurement. Operational wires stay complete.
    executor = (prefix + json.dumps(initial, ensure_ascii=True, separators=(',', ':'))
                + ',' + json.dumps(finalizer, ensure_ascii=True, separators=(',', ':')) + suffix)
    executor_pin = {'size_bytes': len(executor), 'sha256': digest(executor.encode('ascii'))}
    fixture = ResumeNodeCaller('runTest')
    success = fixture.success_output()
    structured = fixture.failure_output()
    unicode_failure = fixture.failure_output(unicode=True)
    forms = [
        {'id': 'success', 'stdout': success, 'stderr': '', 'success': True},
        {'id': 'structured_failure', 'stdout': '', 'stderr': structured,
         'success': False, 'failure': True},
        {'id': 'unicode_failure', 'stdout': '', 'stderr': unicode_failure,
         'success': False, 'failure': True},
        {'id': 'partial_emission', 'stdout': success[:1024], 'stderr': '',
         'success': False, 'partial': True},
        {'id': 'unknown_closure', 'stdout': success, 'stderr': '',
         'success': False, 'unknown': True},
        {'id': 'setup_refusal', 'stdout': '{}\n', 'stderr': '', 'success': False}]
    gate()
    # This is a DECLARED FUTURE CONTROLLED chain model with every field present.
    # No historical output is filtered or claimed to be a new acquired original.
    chain = [
        {'call': {'type': 'custom_tool_call', 'id': 'd24_exec', 'status': 'completed',
                  'call_id': 'd24_exec_call', 'name': 'exec', 'input': '',
                  'internal_chat_message_metadata_passthrough': {'turn_id': 'd24_controlled_geometry',
                                                              'create_time': 1792314000.25}},
         'result': {'type': 'custom_tool_call_output', 'id': 'd24_exec_output',
                    'call_id': 'd24_exec_call',
                    'output': 'Script running with cell ID d24geometry\nWall time 0.0 seconds\nOutput:\n',
                    'internal_chat_message_metadata_passthrough': {'turn_id': 'd24_controlled_geometry',
                                                                'create_time': 1792314000.5}}},
        {'call': {'type': 'function_call', 'id': 'd24_wait', 'name': 'wait',
                  'arguments': canonical({'cell_id': 'd24geometry', 'max_tokens': 100000,
                                          'yield_time_ms': 1000}).decode('ascii'),
                  'call_id': 'd24_wait_call',
                  'internal_chat_message_metadata_passthrough': {'turn_id': 'd24_controlled_geometry',
                                                              'create_time': 1792314001.25}},
         'result': {'type': 'function_call_output', 'id': 'd24_wait_output',
                    'call_id': 'd24_wait_call',
                    'output': [{'type': 'input_text',
                                'text': 'Script completed\nWall time 0.0 seconds\nOutput:\n'},
                               {'type': 'input_text', 'text': ''}],
                    'internal_chat_message_metadata_passthrough': {'turn_id': 'd24_controlled_geometry',
                                                                'create_time': 1792314001.5}}}]
    # Pure canonical native-format DATA, including the genuine C failure
    # formatter. No native_main, writer, temporary directory or stage is called.
    c = importlib.import_module('tests.fixtures.accepted_policy_fixture_compiler_gate2_c_v1')
    native_root = c.RESUME_OWNER_ROOT_V1.as_posix() + '/r1'
    if len(native_root) != 98:
        raise RuntimeError('d24_native_model_root')
    maximum = 2**64 - 1
    completions = []
    later = []
    native_input = canonical({'current': {descriptors[1][0]: source_rows[1]}}).decode('ascii') + '\n'
    for stage in ('C1', 'C2', 'C3', 'C4', 'C5', 'C6'):
        gate()
        previous = None if stage == 'C1' else completions[-1]['descriptor']['sha256']
        record = c._invocation_record_v1(stage, commit, packet_sha, digest(stage.encode()),
                                         digest(('accounting-' + stage).encode()), previous)
        raw = canonical(record)
        path = native_root + '/outputs/' + stage + '/outer.invocation.original.json'
        complete = {'descriptor': {'path': path, 'size_bytes': len(raw), 'sha256': digest(raw)},
                    'write_facts': {'path': path, 'open_completed': True, 'written_bytes': len(raw),
                                    'write_extent_unknown': False, 'flush_completed': True,
                                    'fsync_completed': True, 'close_completed': True,
                                    'directory_persisted': True, 'complete': True,
                                    'deadline_failed': False, 'failure_causes': []},
                    'completion_deadline_ns': maximum, 'external_approval': False}
        args = [commit, '32768', packet_sha,
                '-' if not completions else ','.join(
                    str(row['descriptor']['size_bytes']) + ':' + row['descriptor']['sha256']
                    for row in completions)]
        completions.append(complete)
        if stage in ('C1', 'C6'):
            stdout = c.component.canonical_json_v1(complete).decode('ascii') + '\n'
            failure = c.native_failure_bytes_v1(c.Gate2Refusal('native_stdout_deadline',
                {'written_bytes': len(stdout), 'write_extent_unknown': False,
                 'flush_completed': False})).decode('ascii')
            if len(stdout.encode('ascii')) > 2048 or len(failure.encode('ascii')) > 768:
                raise RuntimeError('d24_c_model_pipe_bound')
            for failed in (False, True):
                later.append({'id': stage + ('_failure' if failed else '_success'),
                              'stage': stage, 'args': args, 'stdout': stdout,
                              'stderr': failure if failed else '', 'failure': failed,
                              'duration_ms': 150000, 'native_input': native_input})
    summary = {'stage': 'D', 'receipt_sha256': digest(b'controlled-D-receipt'),
               'receipt_size_bytes': 20480,
               'final_measurement': {key: maximum for key in
                                     ('c_free_bytes', 'ext4_used_bytes', 'project_free_bytes')},
               'ledger': {'remaining_before': 536870912, 'charge_bytes': 2097152,
                          'remaining_after': 534773760},
               'deadline_ns': maximum, 'finished_ns': maximum - 1,
               'control_bytes': 524288, 'aggregate_bytes': 2097152, 'passed': True,
               'finalization_complete': True, 'controlled': False, 'external_return_required': True}
    d_stdout = c.component.canonical_json_v1(summary).decode('ascii') + '\n'
    d_failure = c.native_failure_bytes_v1(c.Gate2Refusal('native_stdout_deadline',
        {'written_bytes': len(d_stdout), 'write_extent_unknown': False,
         'flush_completed': False})).decode('ascii')
    if len(d_stdout.encode('ascii')) > 768 or len(d_failure.encode('ascii')) > 768:
        raise RuntimeError('d24_d_model_pipe_bound')
    d_args = [commit, '32768', packet_sha, ','.join(
        str(row['descriptor']['size_bytes']) + ':' + row['descriptor']['sha256']
        for row in completions)]
    for failed in (False, True):
        later.append({'id': 'D_failure' if failed else 'D_success', 'stage': 'D',
                      'args': d_args, 'stdout': d_stdout, 'stderr': d_failure if failed else '',
                      'failure': failed, 'duration_ms': 10000, 'native_input': native_input})
    approval_template = {
        'version': 1, 'kind': 'vast_gate2_external_delivery_approval_v1',
        'receipt_sha256': None, 'context_sha256': None, 'code_commit': commit,
        'packet_size_bytes': 32768, 'packet_sha256': packet_sha, 'selected_sha256': None,
        'core_sha256': expected['core_sha256'], 'factory_sha256': factory_sha,
        'decision': 'approved_for_C1', 'approval_type': 'delegated_agent_self_approval',
        'independent_review_reference': 'https://github.com/lordcoudy/VAST/pull/9#issuecomment-6249762191'}
    approval_reference = 'https://github.com/lordcoudy/VAST/pull/9#issuecomment-' + '9' * 20
    data = {'initial': initial, 'finalizer': finalizer,
            'executor_prefix': prefix, 'executor_suffix': suffix, 'executor_pin': executor_pin,
            'fields': list(NODE_FIELDS), 'pipe_fields': list(NODE_PIPE_FIELDS), 'held': held,
            'commit': commit, 'packet_sha256': packet_sha, 'factory_sha256': factory_sha,
            'forms': forms, 'chain': chain, 'later': later,
            'approval_template': approval_template, 'approval_reference': approval_reference}
    gate()
    encoded = canonical(data)
    facts = {'kind': 'd24_inert_source_construction_metadata_v1',
             'initial': source_facts, 'node_codec': role_facts,
             'finalizer': finalizer_facts, 'executor': executor_pin,
             'input_data_size_bytes': len(encoded), 'input_data_sha256': digest(encoded),
             'modeled_setup_form_count': len(forms), 'modeled_later_form_count': len(later),
             'controlled_synthetic_geometry_only': True,
             'independent_actual_acquisition_proven': False,
             'generated_operational_program_execution': False,
             'generated_full_subject_files_written': False,
             'behavior_conformance_complete': False, 'physical_acceptance': False}
    if len(canonical(facts)) > 32768:
        raise RuntimeError('d24_source_metadata_bound')
    return encoded, facts

class D24CompleteGeometryTests(unittest.TestCase):
    def test_complete_form_bounds_preserve_hold(self):
        # Fixed metadata from the ONE consumed D24 risk; no source construction.
        import copy
        import hashlib
        import json

        stdout = b'{"both_buffers_verified_before_either_compile":true,"event":"source_bindings","execution_reopens_test_paths":false,"held_driver_loader_bound":true,"held_driver_module":"tests.test_accepted_policy_fixture_compiler_gate2_resume_v1","sources":[{"path":"tests/test_accepted_policy_fixture_compiler_gate2_resume_v1.py","sha256":"191ffc23e1b62b2fd8ef0a2ccce8444c59f7fc78f54b269841c9ea8551abf4a6","size_bytes":380856},{"path":"tests/test_accepted_policy_fixture_compiler_gate2_resume_caller_v1.py","sha256":"a855e2b749fe891ed23be93b8bd9cbb850bf03dab0be30e2899a3ac3fe578a3b","size_bytes":223288}]}\n{"event":"test_started","test_id":"tests.test_accepted_policy_fixture_compiler_gate2_resume_v1.D24CompleteGeometryTests.test_complete_form_bounds_preserve_hold"}\nD24_GEOMETRY_SOURCE_METADATA {"behavior_conformance_complete":false,"controlled_synthetic_geometry_only":true,"executor":{"sha256":"573c863b02c12eae26293a3b481da6520df3c7ddd31af564c52f0976e59a907e","size_bytes":76788},"finalizer":{"factory_sha256":"997579f8ffcc50d6e05ae859dd9164b1dc08ce5a71e82a1d8070633c3cdf3677","factory_size_bytes":13073,"finalizer_sha256":"6f23bd21e1b955872b3c6a068444775eb967016072b0091b1df2586fb3fbb8fe","finalizer_size_bytes":33828,"generated_full_subject_files_written":false,"generated_operational_program_execution":false,"initial_sha256":"4032a534147aada87931734f3b06cde67988d62c75851b959945399843a3770d","initial_size_bytes":14162,"python_common_sha256":"f56a723316fd5e1d21b7425320959977703cedf4b82dae3511cb28d6f1c1d0a8","python_common_size_bytes":3674,"python_head_sha256":"3ced26dc51155909cd4cd8fbd441db7145dd0241cd0b2bd4de29a10a6cc3efc7","python_head_size_bytes":314,"python_tail_sha256":"fe7e134bb04da2e1c994c9cd2e788ace8b9003f4f567b65a46b6382fa3d655e3","python_tail_size_bytes":1544,"wrapper_prefix_size_bytes":32,"wrapper_suffix_size_bytes":2},"generated_full_subject_files_written":false,"generated_operational_program_execution":false,"independent_actual_acquisition_proven":false,"initial":{"base64_data_bytes":3156,"base64_data_sha256":"1703bd103a438c34c66fe18d82c5cd035d18262632055ab7428a73e13fd7125e","baseline_body_bytes":12732,"baseline_body_sha256":"c40686a051a53f5b6443c414e45833fd5765b904bac971c8ba6f1eb9d365e613","baseline_bytes":18321,"baseline_sha256":"8e045e64625562cded6903492fbdcf440ddbb9a7f30f20d3774faed53dcd8019","behavior_conformance_complete":false,"canonical_data_bytes":6566,"canonical_data_sha256":"8ca48e37f97d03af660960f75afab79db162e8f8997f39f6c1c5c55dd896c97e","complete_geometry_qualified":false,"compressed_data_bytes":2365,"compressed_data_sha256":"a7caf17aa8d2d5d6beb60880d415e7328947d188623bf5fa0d1ad566e1fd2f2f","compression":{"caller_deadline":1887145.833925,"causes":[],"child_completion_observed_before_deadline":true,"child_total_deadline":1887140.833925,"child_total_limit_seconds":30,"child_work_limit_seconds":27,"cleanup_deadline":1887122.0968221,"cleanup_limit_seconds":3,"command_options":["--max-old-space-size=256","--input-type=commonjs","-e"],"data_only":true,"descendant_quiescence":"UNKNOWN","elapsed_seconds":0.08711199997924268,"environment_keys":["PATH","SystemRoot"],"final_reserve_seconds":5,"finished_before_deadline":true,"input_bytes":6566,"input_sha256":"8ca48e37f97d03af660960f75afab79db162e8f8997f39f6c1c5c55dd896c97e","kill_requested":false,"node_executable":"C:\\\\Program Files\\\\nodejs\\\\node.exe","node_version":"25.2.1","packed_bytes":2365,"packed_sha256":"a7caf17aa8d2d5d6beb60880d415e7328947d188623bf5fa0d1ad566e1fd2f2f","parent_observed_completion":true,"pid":23216,"program_sha256":"1b247b18c586bad5fe381de140410ee63fbe66e770cdbd2a52fe4540d1208c11","quality":11,"reaped":true,"returncode":0,"roundtrip":true,"schema_version":1,"spawned":true,"started_monotonic":1887119.0098538,"stderr":{"closed":true,"eof":true,"io_error":null,"observed_bytes":0,"overflow":false,"prefix_sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","retained_bytes":0,"unknown_remainder":false},"stderr_prefix_b64":"","stdin_bytes":6566,"stdin_closed":true,"stdin_complete":true,"stdin_extent_unknown":false,"stdin_write_attempted":true,"stdin_write_in_flight":false,"stdout":{"closed":true,"eof":true,"io_error":null,"observed_bytes":3228,"overflow":false,"prefix_sha256":"2f8a5164f43d19033a72018652e92813d3105fd1cb70fbac569f16b9b1824e8f","retained_bytes":3228,"unknown_remainder":false},"threads_joined":true,"threads_started":3,"timed_out":false,"work_deadline":1887137.833925},"data_fields":9,"decoder_bytes":5294,"decoder_sha256":"4b2260bb177b12668b0a4407711258aa3c1eb1c8d1702b6bd5e089502a399823","deferred_definition_bytes":4172,"deferred_definition_sha256":"dbf54523ecfa1299d7f3dd6392aa1a8f90468112cdd619adcc5466eb8e60e966","escaped_source_bytes":14243,"exact_decoder_inverse":true,"exact_inverse_source":true,"exact_phase_inverse":true,"finalizer_implemented":false,"generated_full_subject_files_written":false,"generated_operational_program_executed":false,"kind":"d24_initial_source_only_v1","original_builder_bytes":18676,"original_builder_sha256":"bcfc55d551057f85aa3cd74f0d15d94e1e0aba932d7f079c18c7c9cbc8ac0dd3","prefix_bytes":295,"prefix_sha256":"ea63175835e2149d61c71d52696c62033d17b908f76ca0a20cf25e32b18f142b","source_bytes":14162,"source_contribution_fits":false,"source_only_over_cap_by":1955,"source_sha256":"4032a534147aada87931734f3b06cde67988d62c75851b959945399843a3770d","status":"HOLD_SOURCE_CONTRIBUTION_OVER_CAP","strings_field_absent":true,"task_2_10_complete":false},"input_data_sha256":"4e0db3ad33c8149e96f58638a27fffac0569ac609d9c82ce26924c485acb53a2","input_data_size_bytes":186552,"kind":"d24_inert_source_construction_metadata_v1","modeled_later_form_count":6,"modeled_setup_form_count":6,"node_codec":{"encoder_excluded":true,"excluded_encoder_bytes":2495,"excluded_encoder_sha256":"9334f515e2fec133093cac0c409031eaae43630e83ffd723e51e0e6911ea4cdd","full_codec_bytes":5865,"full_codec_sha256":"56708c18c942acfb6e8153971a0013ca79c955e4182efff590ad7ae3a2ba2432","kind":"d24_node_codec_role_v1","marker_occurrences":1,"node_codec_bytes":3370,"node_codec_sha256":"b993f35b4901e9dea83d2cef52434da60d289b6ea32185a0cf7303ec9a4b11d2","role_is_exact_prefix":true},"physical_acceptance":false}\nD24_CASE_METADATA {"capture":{"caller_deadline":1887145.833925,"case":"geometry","case_cause":"d23_geometry_hold","case_completed":false,"causes":[],"checks_count":127,"child_completion_observed_before_deadline":true,"child_total_deadline":1887140.833925,"child_total_limit_seconds":30,"child_work_limit_seconds":27,"cleanup_deadline":1887122.3890891,"cleanup_limit_seconds":3,"command_options":["--max-old-space-size=256","--input-type=commonjs","-e"],"data_bytes":186552,"data_only":true,"data_sha256":"4e0db3ad33c8149e96f58638a27fffac0569ac609d9c82ce26924c485acb53a2","descendant_quiescence":"UNKNOWN","elapsed_seconds":0.1970675999764353,"environment_keys":["PATH","SystemRoot"],"final_reserve_seconds":5,"finished_before_deadline":true,"input_bytes":186579,"input_sha256":"f569970eccf26ba5fb501e580564a57ba97e3a3e933a9d91b0857e35934860ab","kill_requested":false,"measurements_count":51,"node_executable":"C:\\\\Program Files\\\\nodejs\\\\node.exe","node_version":"25.2.1","parent_observed_completion":true,"pid":56716,"program_sha256":"18b005bdbab33dea7787f6f3bb5014e28f925a6905b26ce9372b565d7d5beed6","reaped":true,"report_bytes":12979,"report_sha256":"87220e59ce897335c67142d16d7ea0f640af3f880f212779d866909cfda08ebe","returncode":0,"schema_version":1,"spawned":true,"started_monotonic":1887119.1924061,"stderr":{"closed":true,"eof":true,"io_error":null,"observed_bytes":0,"overflow":false,"prefix_sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","retained_bytes":0,"unknown_remainder":false},"stdin_bytes":186579,"stdin_closed":true,"stdin_complete":true,"stdin_extent_unknown":false,"stdin_write_attempted":true,"stdin_write_in_flight":false,"stdout":{"closed":true,"eof":true,"io_error":null,"observed_bytes":12979,"overflow":false,"prefix_sha256":"87220e59ce897335c67142d16d7ea0f640af3f880f212779d866909cfda08ebe","retained_bytes":12979,"unknown_remainder":false},"threads_joined":true,"threads_started":3,"timed_out":false,"work_deadline":1887137.833925},"case":"geometry","report":{"case":"geometry","cause":"d23_geometry_hold","checks":[{"id":"source_bindings","ok":true},{"id":"initial_source_bound","ok":true},{"id":"finalizer_source_bound","ok":true},{"id":"executor_source_bound","ok":true},{"id":"six_setup_forms","ok":true},{"id":"success_setup","ok":true},{"id":"success_provider_pipes","ok":true},{"id":"success_pipe0_inverse","ok":true},{"id":"success_pipe1_inverse","ok":true},{"id":"success_pipe2_inverse","ok":true},{"id":"success_selected_original_bound","ok":true},{"id":"success_observed_original_bound","ok":true},{"id":"success_selected_wire_bound","ok":true},{"id":"success_observed_wire_bound","ok":true},{"id":"success_full_roundtrip","ok":true},{"id":"success_uint64","ok":true},{"id":"success_writer_pipe0_inverse","ok":true},{"id":"success_writer_pipe1_inverse","ok":true},{"id":"success_ack_bound","ok":true},{"id":"success_writer_stdout_bound","ok":true},{"id":"success_writer_input_bound","ok":true},{"id":"success_forms_bound","ok":true},{"id":"success_chain_join","ok":true},{"id":"success_root_bound","ok":false},{"id":"success_chain_bound","ok":true},{"id":"structured_failure_setup","ok":true},{"id":"structured_failure_provider_pipes","ok":true},{"id":"structured_failure_pipe0_inverse","ok":true},{"id":"structured_failure_pipe1_inverse","ok":true},{"id":"structured_failure_pipe2_inverse","ok":true},{"id":"structured_failure_selected_original_bound","ok":true},{"id":"structured_failure_observed_original_bound","ok":true},{"id":"structured_failure_selected_wire_bound","ok":true},{"id":"structured_failure_observed_wire_bound","ok":true},{"id":"structured_failure_full_roundtrip","ok":true},{"id":"structured_failure_uint64","ok":true},{"id":"structured_failure_writer_pipe0_inverse","ok":true},{"id":"structured_failure_writer_pipe1_inverse","ok":true},{"id":"structured_failure_ack_bound","ok":true},{"id":"structured_failure_writer_stdout_bound","ok":true},{"id":"structured_failure_writer_input_bound","ok":true},{"id":"structured_failure_forms_bound","ok":true},{"id":"structured_failure_chain_join","ok":true},{"id":"structured_failure_root_bound","ok":false},{"id":"structured_failure_chain_bound","ok":true},{"id":"unicode_failure_setup","ok":true},{"id":"unicode_failure_provider_pipes","ok":true},{"id":"unicode_failure_pipe0_inverse","ok":true},{"id":"unicode_failure_pipe1_inverse","ok":true},{"id":"unicode_failure_pipe2_inverse","ok":true},{"id":"unicode_failure_selected_original_bound","ok":true},{"id":"unicode_failure_observed_original_bound","ok":true},{"id":"unicode_failure_selected_wire_bound","ok":true},{"id":"unicode_failure_observed_wire_bound","ok":true},{"id":"unicode_failure_full_roundtrip","ok":true},{"id":"unicode_failure_uint64","ok":true},{"id":"unicode_failure_writer_pipe0_inverse","ok":true},{"id":"unicode_failure_writer_pipe1_inverse","ok":true},{"id":"unicode_failure_ack_bound","ok":true},{"id":"unicode_failure_writer_stdout_bound","ok":true},{"id":"unicode_failure_writer_input_bound","ok":true},{"id":"unicode_failure_forms_bound","ok":true},{"id":"unicode_failure_chain_join","ok":true},{"id":"unicode_failure_root_bound","ok":false},{"id":"unicode_failure_chain_bound","ok":true},{"id":"partial_emission_setup","ok":true},{"id":"partial_emission_provider_pipes","ok":true},{"id":"partial_emission_pipe0_inverse","ok":true},{"id":"partial_emission_pipe1_inverse","ok":true},{"id":"partial_emission_pipe2_inverse","ok":true},{"id":"partial_emission_selected_original_bound","ok":true},{"id":"partial_emission_observed_original_bound","ok":true},{"id":"partial_emission_selected_wire_bound","ok":true},{"id":"partial_emission_observed_wire_bound","ok":true},{"id":"partial_emission_full_roundtrip","ok":true},{"id":"partial_emission_uint64","ok":true},{"id":"partial_emission_writer_pipe0_inverse","ok":true},{"id":"partial_emission_writer_pipe1_inverse","ok":true},{"id":"partial_emission_ack_bound","ok":true},{"id":"partial_emission_writer_stdout_bound","ok":true},{"id":"partial_emission_writer_input_bound","ok":true},{"id":"partial_emission_forms_bound","ok":true},{"id":"partial_emission_chain_join","ok":true},{"id":"partial_emission_root_bound","ok":false},{"id":"partial_emission_chain_bound","ok":true},{"id":"unknown_closure_setup","ok":true},{"id":"unknown_closure_provider_pipes","ok":true},{"id":"unknown_closure_pipe0_inverse","ok":true},{"id":"unknown_closure_pipe1_inverse","ok":true},{"id":"unknown_closure_pipe2_inverse","ok":true},{"id":"unknown_closure_selected_original_bound","ok":true},{"id":"unknown_closure_observed_original_bound","ok":true},{"id":"unknown_closure_selected_wire_bound","ok":true},{"id":"unknown_closure_observed_wire_bound","ok":true},{"id":"unknown_closure_full_roundtrip","ok":true},{"id":"unknown_closure_uint64","ok":true},{"id":"unknown_closure_writer_pipe0_inverse","ok":true},{"id":"unknown_closure_writer_pipe1_inverse","ok":true},{"id":"unknown_closure_ack_bound","ok":true},{"id":"unknown_closure_writer_stdout_bound","ok":true},{"id":"unknown_closure_writer_input_bound","ok":true},{"id":"unknown_closure_forms_bound","ok":true},{"id":"unknown_closure_chain_join","ok":true},{"id":"unknown_closure_root_bound","ok":false},{"id":"unknown_closure_chain_bound","ok":true},{"id":"setup_refusal_setup","ok":true},{"id":"setup_refusal_provider_pipes","ok":true},{"id":"setup_refusal_pipe0_inverse","ok":true},{"id":"setup_refusal_pipe1_inverse","ok":true},{"id":"setup_refusal_pipe2_inverse","ok":true},{"id":"setup_refusal_selected_original_bound","ok":true},{"id":"setup_refusal_observed_original_bound","ok":true},{"id":"setup_refusal_selected_wire_bound","ok":true},{"id":"setup_refusal_observed_wire_bound","ok":true},{"id":"setup_refusal_full_roundtrip","ok":true},{"id":"setup_refusal_uint64","ok":true},{"id":"setup_refusal_writer_pipe0_inverse","ok":true},{"id":"setup_refusal_writer_pipe1_inverse","ok":true},{"id":"setup_refusal_ack_bound","ok":true},{"id":"setup_refusal_writer_stdout_bound","ok":true},{"id":"setup_refusal_writer_input_bound","ok":true},{"id":"setup_refusal_forms_bound","ok":true},{"id":"setup_refusal_chain_join","ok":true},{"id":"setup_refusal_root_bound","ok":false},{"id":"setup_refusal_chain_bound","ok":true},{"id":"six_later_forms","ok":true},{"id":"later_measured_upstream","ok":false}],"completed":false,"measurements":[{"id":"initial_source","sha256":"4032a534147aada87931734f3b06cde67988d62c75851b959945399843a3770d","size_bytes":14162},{"id":"finalizer_source","sha256":"6f23bd21e1b955872b3c6a068444775eb967016072b0091b1df2586fb3fbb8fe","size_bytes":33828},{"id":"executor_source","sha256":"573c863b02c12eae26293a3b481da6520df3c7ddd31af564c52f0976e59a907e","size_bytes":76788},{"id":"success_selected_original","sha256":"46fdb4a08fc1898e57d6c2b942a28aebdebe49b1f4b5bbe11c44177f2cce628e","size_bytes":17067},{"id":"success_observed_original","sha256":"3470343a39d00b427d76423a2a27c700e37bc53e2a5473413ac374bdc2f2090c","size_bytes":17179},{"id":"success_selected_wire","sha256":"c49a4871367dcf9e81097f14d15f167997853b3b75d7ff783f4dd45637dbc9b2","size_bytes":11870},{"id":"success_observed_wire","sha256":"e12be9d1addac230ab0595bf296a6ea908ebf7fa8043040f989f52e56511a6f8","size_bytes":11856},{"id":"success_ack","sha256":"1cb453af91a5a274e601b535d45c611b9c36734ddde7997b8619456d652ea2a4","size_bytes":15967},{"id":"success_writer_stdout","sha256":"dc1bdca335af53a7f268ed9d4c00e4336f1191d098ca275651eab1a104fbdd6a","size_bytes":744},{"id":"success_root","sha256":"11a72490cd284f74b1aacb5c1c73b36110da3ef0656adb869f16f5eda489740b","size_bytes":74200},{"id":"success_chain","sha256":"df1b188ec47b0166e55ce0d003f205fb8d50f7a3da12d9e75a69d5411ac0ee01","size_bytes":155329},{"id":"structured_failure_selected_original","sha256":"e8cf9b26009ff462152eff45d59343793f7ee5216f1e6f00197b6256ec0d310c","size_bytes":17293},{"id":"structured_failure_observed_original","sha256":"f49efc94394c0e3bbd13a717ec6ef594515cda7730434629fd437b9d2de8d220","size_bytes":17405},{"id":"structured_failure_selected_wire","sha256":"6cdcf1f541186faea2360435a90ba233d8871f774f1152b2cb68d979d682edaa","size_bytes":12092},{"id":"structured_failure_observed_wire","sha256":"453c54230f53236bcf39711f34204a3dce706998d07b534f092e0520c3c64345","size_bytes":12078},{"id":"structured_failure_ack","sha256":"7ae3f3cab51190c7d0e227ba6b8e440bcb942e9970526f655ca69f9ba95872ac","size_bytes":16263},{"id":"structured_failure_writer_stdout","sha256":"90f24572d90931a265eea205cd59b089c21c747dbe87488acc2bd04555491c12","size_bytes":744},{"id":"structured_failure_root","sha256":"0af8ad84f4d682aed1f7d98051c0e869ac13ce72cd6713f42d25840c44babb2b","size_bytes":74169},{"id":"structured_failure_chain","sha256":"78d9bf651ec2ae38212f51231633f39fe506e0bd880c6f5bd7b5519e95146123","size_bytes":155262},{"id":"unicode_failure_selected_original","sha256":"84e2bf9ea93cf982623ef86d9eeb398f4e468eb80656efdf57f206541b55d563","size_bytes":17193},{"id":"unicode_failure_observed_original","sha256":"db156b1b0e543fba376793091e583fceec9ba6a84f76d20a11f3feb5fa07e0ae","size_bytes":17305},{"id":"unicode_failure_selected_wire","sha256":"de67812611488cc609b04fba66f030e0184a09dac2c5c16039e400cae784d4b1","size_bytes":11995},{"id":"unicode_failure_observed_wire","sha256":"5bc9ada9ba8167a3be9ae60bab4f04ff8cd1ee9c2663de72bc4e647214dea443","size_bytes":11981},{"id":"unicode_failure_ack","sha256":"cc89912ce97aca8e5a7cb6210c243af9c73e83468f19ee225928660994822374","size_bytes":16135},{"id":"unicode_failure_writer_stdout","sha256":"40d25b7d2c1823b7710e4f1db1d0f94ca41886e705de4f5be3eb83eb3a6030e9","size_bytes":744},{"id":"unicode_failure_root","sha256":"a6c85cfceb75df6f9dfe4eae89e9e6211035626a8ef1097d7cf1eedb7e759d06","size_bytes":73870},{"id":"unicode_failure_chain","sha256":"86f566b5be0bc87cc660e8714160db6fb7617c611f8dc5842983dbbb764f982c","size_bytes":154963},{"id":"partial_emission_selected_original","sha256":"79ea8cf1b2d66bc2431f4175baabd65338946aff50e3b104d64ce986f8087297","size_bytes":16786},{"id":"partial_emission_observed_original","sha256":"dfe2389e27df0708f2c34794efe813f36cc09b926fbbd137db999d930d585982","size_bytes":16898},{"id":"partial_emission_selected_wire","sha256":"7de0157a0c6ed76122db714de018912626358d45b738400864ddcb4f4dc74d91","size_bytes":11606},{"id":"partial_emission_observed_wire","sha256":"e7f228f1a5e76f52ab8f4249eb7e44959419e82af455e907101a666f80cfeb39","size_bytes":11592},{"id":"partial_emission_ack","sha256":"db07518469eb054f4c4623f5ecbd93c222ee16e62408c961974c231790817983","size_bytes":15615},{"id":"partial_emission_writer_stdout","sha256":"2ab4bb41b7c82474b814b252bcef9d238e38982abad243c67a3275218ae15d72","size_bytes":744},{"id":"partial_emission_root","sha256":"13ce100290d08b5af27668f4867aece89c0fcc86e3b0581773f899150339e381","size_bytes":72763},{"id":"partial_emission_chain","sha256":"ff3ca11a527c61d3ee5037b6346191fee694d88c93e6dc678592a3cf19b9691c","size_bytes":153952},{"id":"unknown_closure_selected_original","sha256":"628eaa305921b541a5502e476b5c6d3ad4dbf5d452625a8ca547de7b1e1afff4","size_bytes":17071},{"id":"unknown_closure_observed_original","sha256":"047f56c910c64269216bc489bfcd1cfa04f513fa1d7eaa0551afc1569e26e282","size_bytes":17183},{"id":"unknown_closure_selected_wire","sha256":"b7e3685bdcd4c4bc35571fc14796b9eef9eb94650bee1bd0ed51c9da8b8d70ca","size_bytes":11870},{"id":"unknown_closure_observed_wire","sha256":"a844b12e9335bd43976b7fc409edd3da95e5134fb47b3502f5c677d1f461ec1d","size_bytes":11856},{"id":"unknown_closure_ack","sha256":"9b1afe4026cc4ae3311c09afc56ef7a6a0fa728c6836a7839d9bcb85b2df511e","size_bytes":15967},{"id":"unknown_closure_writer_stdout","sha256":"e6f25fce6536f24bb2a7e8c76242b6ff1a8884cd3247e475f7575a564f4f0dd9","size_bytes":744},{"id":"unknown_closure_root","sha256":"46c7f797a62db4da17ebf2f3a7814a4db2f7fdc2834a6cf93493570a409c3217","size_bytes":73511},{"id":"unknown_closure_chain","sha256":"fe752d7156c0b1d62a4110dd879884625d4ed5d733e407ed0ab4629a72f778b5","size_bytes":154604},{"id":"setup_refusal_selected_original","sha256":"6beffafc4f5629b627f40ace16448fea4ca0e16e57cea746c602759262e53429","size_bytes":16147},{"id":"setup_refusal_observed_original","sha256":"1bd0876ec6ae223539bdb9043a101618d86cc147b3447812d39837787ffc7332","size_bytes":16259},{"id":"setup_refusal_selected_wire","sha256":"932f0c5116ab5391842630c9a87348e459d98493354a7d8599dff828281fd546","size_bytes":10942},{"id":"setup_refusal_observed_wire","sha256":"3c92e549455b60a64306de47abb5d0026f1e7c31f23e7fcf613947c73b91e5b1","size_bytes":10928},{"id":"setup_refusal_ack","sha256":"de5be563d25c1d71ecfdd1f6f8f90812c99c24adf0d71fda292ef51e75ab495b","size_bytes":14731},{"id":"setup_refusal_writer_stdout","sha256":"a7b587987c2aa1d58d447d2e010d8308ad96b394cf2f29edacd57750fb0b93a3","size_bytes":744},{"id":"setup_refusal_root","sha256":"29f36669b77780eee33c4a2b1f3eb4be473f65cf37d0306c91ab7257590707e3","size_bytes":70717},{"id":"setup_refusal_chain","sha256":"d73ceaf67682c38d277355d32af115adbd75f8929f69f7b9ba2b0d9f99c39b86","size_bytes":151794}],"node_version":"25.2.1","schema_version":1}}\n{"error_type":"AssertionError","event":"parent_issue","exception_capture":{"capture":null,"capture_metadata_sha256":"74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b","capture_metadata_size_bytes":4,"capture_metadata_unavailable":true},"issue_index":1,"message_sha256":"6eb054b641c8926702a6da74e88b8bc8758395cacf8fc96e25d107d6a66015e0","message_size_bytes":8444,"outcome":"failure","subtest_ordinal":null,"test_id":"tests.test_accepted_policy_fixture_compiler_gate2_resume_v1.D24CompleteGeometryTests.test_complete_form_bounds_preserve_hold"}\n{"error_type":"AssertionError","event":"test_terminal","exception_capture":{"capture":null,"capture_metadata_sha256":"74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b","capture_metadata_size_bytes":4,"capture_metadata_unavailable":true},"issue_counts":{"parent_issue":1,"subtest_issue":0},"message_sha256":"6eb054b641c8926702a6da74e88b8bc8758395cacf8fc96e25d107d6a66015e0","message_size_bytes":8444,"outcome":"failure","subtest_callbacks":0,"test_id":"tests.test_accepted_policy_fixture_compiler_gate2_resume_v1.D24CompleteGeometryTests.test_complete_form_bounds_preserve_hold"}\n{"descendant_quiescence":"UNKNOWN","errors":0,"event":"test_summary","expected_failures":0,"expected_metadata_records":2,"failures":1,"generated_operational_program_execution":false,"geometry_case_records":1,"geometry_source_records":1,"issue_events":1,"parent_outcomes":{"failure":1},"selected_class":"D24CompleteGeometryTests","skips":0,"subtest_callbacks":0,"successes":0,"successful":false,"test_streams":{"stderr":{"geometry_case_records":0,"geometry_source_records":0,"metadata_records":0,"observed_bytes":0,"raw_values_retained":false,"sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","unexpected_or_unterminated":false},"stdout":{"geometry_case_records":1,"geometry_source_records":1,"metadata_records":2,"observed_bytes":20417,"raw_values_retained":false,"sha256":"13c811a503a53a6abc201158d882411902f4f0c88e39a5ca56d6ed487a70bd04","unexpected_or_unterminated":false}},"tests_run":1,"unexpected_successes":0}\n'
        parent_raw = b'{"channels":{"stderr":{"close_attempted":true,"closed":true,"closure_unknown":false,"eof":true,"error":null,"observed_bytes":0,"overflow":false,"remainder_unknown":false,"secondary":[],"sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","size_bytes":0},"stdout":{"close_attempted":true,"closed":true,"closure_unknown":false,"eof":true,"error":null,"observed_bytes":23266,"overflow":false,"remainder_unknown":false,"secondary":[],"sha256":"801b55f2bcf8eebb2c394315e978f12dc79fbf30eb04f052c52698fd123854ad","size_bytes":23266}},"child_completion_before_cleanup_end":true,"child_completion_before_total_end":true,"child_completion_observed_at":1887119.4068788,"child_total_deadline":1887148.833925,"child_total_seconds":30,"child_work_seconds":27,"cleanup_deadline":1887122.4068628,"deadline_seconds":300,"descendant_quiescence":"UNKNOWN","elapsed_before_report_write_s":0.5940271001309156,"forced_test_child":false,"generated_operational_program_execution":false,"geometry_fully_measured":false,"geometry_risk_passed":false,"geometry_source_kind":"d24_inert_source_construction_metadata_v1","held_driver_loader_binding_validated":true,"io_failure":false,"kind":"d24_local_inert_geometry_test_parent_observation_v1","ordered_causes":[],"parent_observed_test_transport_complete":true,"protocol_error_type":null,"python":"3.14.7","returncode":1,"selected_class":"D24CompleteGeometryTests","self_report_persistence_or_whole_process_attested":false,"source_binding_policy":"both_held_test_buffers_before_either_compile","source_binding_record_validated":true,"source_execution_reopens_paths":false,"source_pins":[{"path":"tests/test_accepted_policy_fixture_compiler_gate2_resume_v1.py","sha256":"191ffc23e1b62b2fd8ef0a2ccce8444c59f7fc78f54b269841c9ea8551abf4a6","size_bytes":380856},{"path":"tests/test_accepted_policy_fixture_compiler_gate2_resume_caller_v1.py","sha256":"a855e2b749fe891ed23be93b8bd9cbb850bf03dab0be30e2899a3ac3fe578a3b","size_bytes":223288}],"suite_mode":"geometry","test_summary":{"descendant_quiescence":"UNKNOWN","errors":0,"event":"test_summary","expected_failures":0,"expected_metadata_records":2,"failures":1,"generated_operational_program_execution":false,"geometry_case_records":1,"geometry_source_records":1,"issue_events":1,"parent_outcomes":{"failure":1},"selected_class":"D24CompleteGeometryTests","skips":0,"subtest_callbacks":0,"successes":0,"successful":false,"test_streams":{"stderr":{"geometry_case_records":0,"geometry_source_records":0,"metadata_records":0,"observed_bytes":0,"raw_values_retained":false,"sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","unexpected_or_unterminated":false},"stdout":{"geometry_case_records":1,"geometry_source_records":1,"metadata_records":2,"observed_bytes":20417,"raw_values_retained":false,"sha256":"13c811a503a53a6abc201158d882411902f4f0c88e39a5ca56d6ed487a70bd04","unexpected_or_unterminated":false}},"tests_run":1,"unexpected_successes":0},"threads_joined":true,"timed_out":false,"work_deadline":1887145.833925}\n'
        self.assertEqual((len(stdout), hashlib.sha256(stdout).hexdigest()),
                         (23266, '801b55f2bcf8eebb2c394315e978f12dc79fbf30eb04f052c52698fd123854ad'))
        self.assertEqual((len(parent_raw), hashlib.sha256(parent_raw).hexdigest()),
                         (3032, '4d0c0d73a7dd4a1b7bee0306e0c08dbf84ae1076cee0e5d61a7361bf0fa9c61f'))
        self.assertTrue(stdout.endswith(b'\n'))
        self.assertTrue(parent_raw.endswith(b'\n'))
        lines = stdout.splitlines()
        cases = [json.loads(line[len(b'D24_CASE_METADATA '):]) for line in lines
                 if line.startswith(b'D24_CASE_METADATA ')]
        sources = [json.loads(line[len(b'D24_GEOMETRY_SOURCE_METADATA '):]) for line in lines
                   if line.startswith(b'D24_GEOMETRY_SOURCE_METADATA ')]
        self.assertEqual((len(cases), len(sources)), (1, 1))
        case, source, parent = cases[0], sources[0], json.loads(parent_raw)
        report, capture = case['report'], case['capture']
        report_raw = (json.dumps(report, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii')
        self.assertEqual((len(report_raw), hashlib.sha256(report_raw).hexdigest()),
                         (12979, '87220e59ce897335c67142d16d7ea0f640af3f880f212779d866909cfda08ebe'))
        self.assertEqual(set(report), {'schema_version', 'case', 'node_version',
                                      'completed', 'cause', 'checks', 'measurements'})
        self.assertEqual((report['schema_version'], report['case'], report['node_version']),
                         (1, 'geometry', '25.2.1'))
        self.assertIs(report['completed'], False)
        self.assertEqual(report['cause'], 'd23_geometry_hold')
        self.assertEqual(source['kind'], 'd24_inert_source_construction_metadata_v1')
        self.assertEqual(source['modeled_setup_form_count'], 6)
        self.assertEqual(source['modeled_later_form_count'], 6)
        for name in ('generated_operational_program_execution',
                     'generated_full_subject_files_written', 'behavior_conformance_complete',
                     'independent_actual_acquisition_proven', 'physical_acceptance'):
            self.assertIs(source[name], False)
        setup_forms = ('success', 'structured_failure', 'unicode_failure', 'partial_emission',
                       'unknown_closure', 'setup_refusal')
        later_forms = ('C1_success', 'C1_failure', 'C6_success', 'C6_failure', 'D_success', 'D_failure')
        roots = dict(zip(setup_forms, (74200, 74169, 73870, 72763, 73511, 70717)))
        expected_checks = {'source_bindings', 'initial_source_bound', 'finalizer_source_bound',
                           'executor_source_bound', 'six_setup_forms', 'six_later_forms',
                           'later_measured_upstream'}
        caps = {name: 262144 for name in ('initial_source', 'finalizer_source', 'executor_source')}
        for form in setup_forms:
            expected_checks.update(form + suffix for suffix in (
                '_setup', '_provider_pipes', '_pipe0_inverse', '_pipe1_inverse', '_pipe2_inverse',
                '_selected_original_bound', '_observed_original_bound', '_selected_wire_bound',
                '_observed_wire_bound', '_full_roundtrip', '_uint64',
                '_writer_pipe0_inverse', '_writer_pipe1_inverse', '_ack_bound',
                '_writer_stdout_bound', '_writer_input_bound', '_forms_bound', '_chain_join',
                '_root_bound', '_chain_bound'))
            for suffix, cap in (('selected_original', 32768), ('observed_original', 32768),
                                ('selected_wire', 12288), ('observed_wire', 12288),
                                ('ack', 24576), ('writer_stdout', 2112),
                                ('root', 65536), ('chain', 262144)):
                caps[form + '_' + suffix] = cap
        false_ids = {form + '_root_bound' for form in setup_forms} | {'later_measured_upstream'}

        def retained_dimensions(value):
            checks = {row['id']: row['ok'] for row in value['checks']}
            measures = {row['id']: row for row in value['measurements']}
            self.assertEqual((len(value['checks']), len(checks)), (127, 127))
            self.assertEqual((len(value['measurements']), len(measures)), (51, 51))
            self.assertEqual(set(checks), expected_checks)
            self.assertEqual(set(measures), set(caps))
            self.assertEqual({name for name, ok in checks.items() if not ok}, false_ids)
            for row in value['checks']:
                self.assertEqual(set(row), {'id', 'ok'})
                self.assertIs(type(row['ok']), bool)
            for name, row in measures.items():
                self.assertEqual(set(row), {'id', 'size_bytes', 'sha256'})
                self.assertIs(type(row['size_bytes']), int)
                self.assertGreater(row['size_bytes'], 0)
                self.assertRegex(row['sha256'], r'^[0-9a-f]{64}$')
                self.assertIs(checks[name + '_bound'], row['size_bytes'] <= caps[name])
            for form in setup_forms:
                self.assertEqual(measures[form + '_root']['size_bytes'], roots[form])
                self.assertGreater(measures[form + '_root']['size_bytes'] - 65536, 0)
                self.assertLessEqual(measures[form + '_selected_wire']['size_bytes'], 12288)
                self.assertLessEqual(measures[form + '_observed_wire']['size_bytes'], 12288)
                rounded = ((measures[form + '_selected_wire']['size_bytes'] + 4095) // 4096) * 4096
                self.assertIs(checks[form + '_forms_bound'], max(12288, rounded) + rounded + 8192 <= 32768)
                self.assertIs(checks[form + '_writer_input_bound'], measures[form + '_ack']['size_bytes'] + 65471 <= 90112)
            # These unavailable dimensions cannot be counted as zero or projected success.
            self.assertNotIn('approval_slots', checks)
            for form in later_forms:
                self.assertFalse(any(name.startswith(form + '_') for name in measures))
                self.assertFalse(any(name.startswith(form + '_') for name in checks))
            return checks, measures

        checks, measures = retained_dimensions(report)
        for dimension in ('success_selected_wire', 'setup_refusal_chain'):
            missing = copy.deepcopy(report)
            missing['measurements'] = [row for row in missing['measurements'] if row['id'] != dimension]
            with self.subTest(missing_dimension=dimension), self.assertRaises(AssertionError):
                retained_dimensions(missing)
        missing = copy.deepcopy(report)
        missing['checks'] = [row for row in missing['checks'] if row['id'] != 'later_measured_upstream']
        with self.assertRaises(AssertionError):
            retained_dimensions(missing)
        for name, size, sha in (
            ('initial_source', 14162, '4032a534147aada87931734f3b06cde67988d62c75851b959945399843a3770d'),
            ('finalizer_source', 33828, '6f23bd21e1b955872b3c6a068444775eb967016072b0091b1df2586fb3fbb8fe'),
            ('executor_source', 76788, '573c863b02c12eae26293a3b481da6520df3c7ddd31af564c52f0976e59a907e')):
            self.assertEqual((measures[name]['size_bytes'], measures[name]['sha256']), (size, sha))
        self.assertEqual((capture['report_bytes'], capture['report_sha256']),
                         (12979, '87220e59ce897335c67142d16d7ea0f640af3f880f212779d866909cfda08ebe'))
        self.assertEqual(capture['returncode'], 0)
        self.assertIs(capture['parent_observed_completion'], True)
        self.assertIs(capture['case_completed'], False)
        self.assertEqual(capture['case_cause'], 'd23_geometry_hold')
        self.assertIs(capture['reaped'], True)
        self.assertIs(capture['threads_joined'], True)
        self.assertIs(capture['kill_requested'], False)
        self.assertIs(capture['timed_out'], False)
        self.assertEqual(capture['descendant_quiescence'], 'UNKNOWN')
        self.assertEqual(parent['returncode'], 1)
        self.assertEqual((parent['test_summary']['tests_run'], parent['test_summary']['failures'],
                          parent['test_summary']['errors']), (1, 1, 0))
        self.assertIs(parent['parent_observed_test_transport_complete'], True)
        self.assertIs(parent['geometry_fully_measured'], False)
        self.assertIs(parent['geometry_risk_passed'], False)
        self.assertIs(parent['forced_test_child'], False)
        self.assertIs(parent['self_report_persistence_or_whole_process_attested'], False)
        self.assertEqual(parent['descendant_quiescence'], 'UNKNOWN')
        self.assertIs(parent['threads_joined'], True)
        self.assertIs(parent['timed_out'], False)
        self.assertEqual(parent['ordered_causes'], [])
        self.assertIs(parent['generated_operational_program_execution'], False)
        for channel, n, sha in (('stdout', 23266, '801b55f2bcf8eebb2c394315e978f12dc79fbf30eb04f052c52698fd123854ad'),
                                ('stderr', 0, 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855')):
            facts = parent['channels'][channel]
            self.assertEqual((facts['size_bytes'], facts['observed_bytes'], facts['sha256']), (n, n, sha))
            for name in ('eof', 'closed', 'close_attempted'):
                self.assertIs(facts[name], True)
            for name in ('overflow', 'closure_unknown', 'remainder_unknown'):
                self.assertIs(facts[name], False)
            self.assertIsNone(facts['error'])
        self.assertFalse(all(checks.values()))
        # This metadata regression passing never opens a new fit/phase/admission gate.


# Decision25 fixed DATA-only test driver. Codec intentionally absent for RED.
D25_DATA_DRIVER = r""""use strict";
let chunks=[],inputBytes=0,finished=false;
const A='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/',S='gate2-selected-lzss-v2',O='gate2-observed-lzss-v2';
const cases=new Set(['codec_vectors','codec_malformed','codec_overflow']);
const C={input:'selected_wire_input',shape:'selected_wire_shape',bound:'selected_wire_bound',token:'selected_wire_token',expansion:'selected_wire_expansion',binding:'selected_wire_binding'};
const report={schema_version:1,case:'codec_vectors',node_version:process.versions.node,completed:false,cause:null,checks:[],measurements:[]};
function ok(id,ok){if(report.checks.length>=512)throw Error('d25_driver_assertion');report.checks.push({id,ok:!!ok});if(!ok)throw Error('d25_driver_assertion');}
function measure(id,text){if(report.measurements.length>=128||typeof text!=='string'||text.length>262144||/[^\x00-\x7f]/.test(text))throw Error('d25_driver_assertion');report.measurements.push({id,size_bytes:text.length,sha256:gate2SHA256(text)});}
function expect(id,fn,cause){let seen=null;try{fn();}catch(e){seen=e.message;}ok(id,seen===cause);}
function budget(cause='selected_wire_deadline',now=()=>performance.now(),end=Infinity){return gate2WireBudget(now,cause,end);}
function dec(wire,tag=S,guard=budget()){return gate2WireDecode(wire,tag,gate2SHA256,gate2Canonical,guard);}
function enc(text,tag=S,guard=budget('selected_wire_root_deadline')){return gate2WireEncode(text,tag,gate2SHA256,gate2Canonical,guard);}
function wire(payload,text,tag=S,size=text.length,sha=gate2SHA256(text)){return gate2Canonical({encoding:tag,expanded_sha256:sha,expanded_size_bytes:size,payload},262144);}
function lit(c){let n=A.indexOf(c);return n<0?[1,c.charCodeAt(0)]:[0,n];}
function lits(text){return Array.from(text,lit);}
function packetBits(bits){if(bits.length>294912)throw Error('d25_driver_assertion');let b=Buffer.alloc(3+Math.ceil(bits.length/8));b[0]=Math.floor(bits.length/65536);b[1]=Math.floor(bits.length/256)%256;b[2]=bits.length%256;for(let i=0;i<bits.length;i++)b[3+Math.floor(i/8)]+=bits[i]*2**(7-i%8);return b.toString('base64');}
function tokenBits(tokens){let bits=[];for(let t of tokens){let n=t[0]===0?7:t[0]===1?9:25,v=t[0]===0?t[1]:t[0]===1?256+t[1]:3*2**23+(t[1]-1)*256+t[2]-3;for(let k=n-1;k>=0;k--)bits.push(Math.floor(v/2**k)%2);}return bits;}
function pack(tokens){return packetBits(tokenBits(tokens));}
function oracle(text){let tokens=[],at=0;while(at<text.length){let positions=[];if(at+3<=text.length)for(let p=Math.max(0,at-32768);p<at;p++)if(text.slice(p,p+3)===text.slice(at,at+3))positions.push(p);let best=0,d=0;for(let p of positions.slice(-8)){let n=0;while(n<258&&at+n<text.length&&text[p+n]===text[at+n])n++;if(n>=3&&(n>best||n===best&&at-p<d)){best=n;d=at-p;}}if(best>=3){tokens.push([2,d,best]);at+=best;}else tokens.push(lit(text[at++]));}return tokens;}
function repeated(tokens,n){while(n){let m=Math.min(258,n);if(m<3){for(let i=0;i<m;i++)tokens.push(lit('a'));}else tokens.push([2,1,m]);n-=m;}return tokens;}
function vectors(){
for(let i=0;i<64;i++){let text=JSON.stringify(A[i]),p=pack(lits(text));ok('common_'+i,dec(wire(p,text)).text===text&&JSON.parse(enc(text)).payload===p);}
let others=[];for(let n=32;n<=126;n++)if(!A.includes(String.fromCharCode(n)))others.push(n);ok('other_class_count',others.length===31);
for(let n of others){let text=JSON.stringify(String.fromCharCode(n)),p=pack(lits(text));ok('other_'+n,dec(wire(p,text)).text===text&&JSON.parse(enc(text)).payload===p);}
const samples=[['minimum','aaaa'],['maximum','a'.repeat(259)],['overlap','ab'.repeat(130)],['longest','abcXabcYZabcYQabcYZ'],['nearest','abcXabcYabcZ'],['last8','abcLONGer'+Array.from({length:10},(_,i)=>'abc'+i).join('')+'abcLONGer'],['consumed','abcdefgh'.repeat(110)+'abcXYZabcUVWabcXYZ'],['distance4096','ABC'+'Z'.repeat(4093)+'ABC'],['distance4097','ABC'+'Z'.repeat(4094)+'ABC']];
for(let [id,value] of samples){let text=JSON.stringify(value),w=enc(text),p=pack(oracle(text));ok(id+'_oracle',JSON.parse(w).payload===p);ok(id+'_inverse',dec(w).text===text);ok(id+'_deterministic',w===enc(text));measure(id+'_wire',w);}
ok('min3_even_at_25_vs_21',JSON.parse(enc('"aaaa"')).payload===pack([lit('"'),lit('a'),[2,1,3],lit('"')]));
ok('maximum258_overlap',JSON.parse(enc(JSON.stringify('a'.repeat(259)))).payload===pack([lit('"'),lit('a'),[2,1,258],lit('"')]));
for(let off=0;off<8;off++){let n=(1-off+8)%8+8,t=[lit('"'),...Array.from({length:n},()=>lit('a')),[2,1,3],lit('"')],text=JSON.stringify('a'.repeat(n+3));ok('bit_offset_'+off,(9+7*n)%8===off&&dec(wire(pack(t),text)).text===text);if(off===7)ok('match25_plus7_is32',(9+7*n)%8+25===32);}
let text=JSON.stringify('abc'.repeat(90)),selected=enc(text),observed=enc(text,O);ok('distinct_tags',selected!==observed&&JSON.parse(selected).payload===JSON.parse(observed).payload);ok('observed_inverse',dec(observed,O).text===text);expect('tag_swap',()=>dec(observed),C.shape);
let maxTokens=repeated([lit('"'),lit('a')],32763);maxTokens.push([2,32765,3]);let raw='"'+'a'.repeat(32764)+'"aa';ok('distance32765_encode_oracle',JSON.parse(enc(raw)).payload===pack(maxTokens));expect('distance32765_reaches_binding',()=>dec(wire(pack(maxTokens),raw)),C.binding);
ok('literal_roundtrip_nested',dec(enc(enc('"a"'))).text===enc('"a"'));
}
function malformed(){
for(let [id,value] of [['null',null],['number',1],['empty',''],['nonprint','\n'],['long','x'.repeat(12289)]])expect('input_'+id,()=>dec(value),C.input);
const plain='"a"',payload=pack(lits(plain)),good=wire(payload,plain),base=JSON.parse(good);
for(let [id,value] of [['parse','{'],['array','[]'],['extra',gate2Canonical({...base,extra:1},32768)],['tag',gate2Canonical({...base,encoding:'wrong'},32768)],['hash',gate2Canonical({...base,expanded_sha256:'A'.repeat(64)},32768)],['bool',gate2Canonical({...base,expanded_size_bytes:true},32768)],['fraction',gate2Canonical({...base,expanded_size_bytes:1.5},32768)],['exponent',good.replace('"expanded_size_bytes":3','"expanded_size_bytes":3e0')],['negative_zero',good.replace('"expanded_size_bytes":3','"expanded_size_bytes":-0')],['space',good+' ']])expect('shape_'+id,()=>dec(value),C.shape);
for(let n of [-1,0,32769])expect('range_'+String(n).replace('-','minus'),()=>dec(wire(payload,plain,S,n)),C.bound);
let canonicalTail=payload.replace(/([A-Za-z0-9+/])==$/,(_,c)=>A[A.indexOf(c)+1]+'==');ok('tail_fixture_changed',canonicalTail!==payload);
for(let [id,p] of [['empty',''],['length',payload.slice(1)],['alphabet','?'+payload.slice(1)],['whitespace',' '+payload.slice(1)],['urlsafe','_'+payload.slice(1)],['middle_padding','='+payload.slice(1)],['three_padding',payload.slice(0,-3)+'==='],['base64_tail',canonicalTail],...[9,10,127,233].map(n=>[n,String.fromCharCode(n)+payload.slice(1)]),['missing_header',Buffer.from([1,2]).toString('base64')],['zero_header','AAAA'],['no_body',Buffer.from([0,0,1]).toString('base64')]])expect('syntax_'+id,()=>dec(wire(p,plain)),C.token);
let bytes=Buffer.from(payload,'base64');for(let [id,mutate] of [['extra_byte',b=>Buffer.concat([b,Buffer.from([0])])],['header_more',b=>{b[2]++;return b;}],['header_less',b=>{b[2]--;return b;}],['body_tail',b=>{b[b.length-1]|=1;return b;}]])expect(id,()=>dec(wire(mutate(Buffer.from(bytes)).toString('base64'),plain)),C.token);
for(let [id,bits] of [['prefix1',[1]],['common_short',[0]],['other_short',[1,0,1]],['distance_short',[1,1,0]],['length_short',[1,1,...Array(15).fill(0),0]]])expect(id,()=>dec(wire(packetBits(bits),plain)),C.token);
for(let n=0;n<128;n++)if(n<32||n===127||A.includes(String.fromCharCode(n)))expect('forbidden_other_'+n,()=>dec(wire(pack([[1,n]]),plain,S,1)),C.token);
expect('distance_without_prefix',()=>dec(wire(pack([[2,1,3]]),plain,S,1)),C.token);
expect('distance_before_expansion',()=>dec(wire(pack([lit('a'),[2,2,3]]),'a',S,1)),C.token);
expect('forbidden_other_before_expansion',()=>dec(wire(pack([lit('a'),[1,65]]),'a',S,1)),C.token);
expect('malformed_next_before_expansion',()=>dec(wire(packetBits([...tokenBits([lit('a')]),1]),'a',S,1)),C.token);
expect('valid_next_expansion',()=>dec(wire(pack([lit('a'),lit('b')]),'a',S,1)),C.expansion);
expect('clean_short_binding',()=>dec(wire(payload,plain,S,4)),C.binding);
expect('hash_binding',()=>dec(wire(payload,plain,S,3,'0'.repeat(64))),C.binding);
for(let [id,text] of [['json','abc'],['canonical','{ "a":1}']])expect('recovered_'+id,()=>dec(wire(pack(lits(text)),text)),C.binding);
expect('declared_size_not_header_bound',()=>dec(wire(pack(lits('ab')),'a',S,1)),C.expansion);
let seen=0,semantic=w=>{dec(w);seen++;throw Error('fixture_semantic_refusal');};expect('wire_before_semantic',()=>semantic(wire('????',plain)),C.token);ok('semantic_not_reached',seen===0);expect('semantic_after_recovery',()=>semantic(good),'fixture_semantic_refusal');ok('semantic_reached_once',seen===1);
}
function overflow(){
const maximum=JSON.stringify('a'.repeat(32766)),w=enc(maximum);ok('expanded_exact',maximum.length===32768&&dec(w).text===maximum);measure('expanded_max_wire',w);expect('expanded_plus_one',()=>enc(maximum+' '),C.input);
let full=repeated([lit('"'),lit('a')],32765);full.push(lit('"'),[2,32768,3]);expect('distance32768_at_full_expands',()=>dec(wire(pack(full),maximum)),C.expansion);
expect('distance32768_unavailable',()=>dec(wire(pack([lit('a'),[2,32768,3]]),'a')),C.token);
const exact=wire(packetBits(Array(72744).fill(0)),'A'.repeat(99));ok('wire_exact_extent',exact.length===12288);expect('wire_exact_reaches_append',()=>dec(exact),C.expansion);expect('wire_one_byte_over',()=>dec(exact+' '),C.input);measure('wire_exact',exact);
let seq='',a=Array(4).fill(0);function db(t,p){if(t>3){if(3%p===0)for(let i=1;i<=p;i++)seq+=A[a[i]];}else{a[t]=a[t-p];db(t+1,p);for(let j=a[t-p]+1;j<32;j++){a[t]=j;db(t+1,t);}}}db(1,1);let text=JSON.stringify(seq.slice(0,32766));ok('count_fixture_extent',seq.length===32768&&text.length===32768);
let edgeText=JSON.stringify(seq.slice(0,10386)),edgeBits=tokenBits(lits(edgeText)),edgeWire=wire(packetBits(edgeBits),edgeText);ok('one_bit_wire_edge',edgeBits.length===72720&&edgeWire.length===12287&&enc(edgeText)===edgeWire&&dec(edgeWire).text===edgeText);expect('one_bit_wire_over',()=>dec(wire(packetBits([...edgeBits,0]),edgeText)),C.input);
const U=globalThis.Uint8Array;let allocations=[];globalThis.Uint8Array=new Proxy(U,{construct(T,args){allocations.push(args[0]);return Reflect.construct(T,args);}});try{expect('count_refuses_before_packet_allocation',()=>enc(text),C.bound);ok('zero_packet_allocation_on_count_refusal',allocations.length===0);}finally{globalThis.Uint8Array=U;}
let maps=0,M=globalThis.Map;globalThis.Map=new Proxy(M,{construct(T,args){maps++;return Reflect.construct(T,args);}});try{let t='"abcabcabcabc"',v=enc(t);ok('fresh_two_pass_indexes',maps===2);ok('count_write_oracle_agreement',JSON.parse(v).payload===pack(oracle(t)));}finally{globalThis.Map=M;}
for(let cause of ['selected_wire_deadline','selected_wire_root_deadline','selected_wire_receive_deadline']){let clock=0,g=budget(cause,()=>clock);g.phase(()=>true);clock=5000;expect(cause,()=>dec(w,S,g),cause);let c=0,h=budget(cause,()=>c);expect(cause+'_post_throw',()=>h.phase(()=>{c=5000;throw Error(C.token);}),cause);}
let clock=0,g=budget('selected_wire_receive_deadline',()=>clock);dec(w,S,g);clock=5000;expect('shared_receive_budget',()=>dec(enc('"a"',O),O,g),'selected_wire_receive_deadline');
clock=0;g=budget('selected_wire_root_deadline',()=>clock);enc('"a"',S,g);clock=5000;expect('shared_encode_budget',()=>enc('"a"',O,g),'selected_wire_root_deadline');
let calls=0;expect('clock_regression',()=>enc('"a"',S,budget('selected_wire_root_deadline',()=>calls++? -1:0)),'selected_wire_root_deadline');expect('clock_nonfinite',()=>dec(w,S,budget('selected_wire_receive_deadline',()=>Infinity)),'selected_wire_receive_deadline');
expect('deadline_before_bad_base64',()=>dec(wire('????','a'),S,budget('selected_wire_receive_deadline',()=>5000,5000)),'selected_wire_receive_deadline');
}
function finish(cause){if(finished)return;finished=true;report.cause=cause;process.stdout.write(gate2Canonical(report,32767)+'\n');}
process.stdin.on('error',()=>finish('d25_driver_input'));
process.stdin.on('data',b=>{if(finished)return;inputBytes+=b.length;if(inputBytes>262144){finish('d25_driver_input');process.stdin.destroy();return;}chunks.push(b);});
process.stdin.on('end',()=>{if(finished)return;try{const bytes=Buffer.concat(chunks);chunks=[];if(bytes.some(x=>x>127))throw Error('d25_driver_input');const text=bytes.toString('ascii'),request=JSON.parse(text);if(!request||typeof request!=='object'||Array.isArray(request)||Object.keys(request).sort().join()!=='case,data'||!cases.has(request.case)||gate2Canonical(request,262144)!==text)throw Error('d25_driver_input');report.case=request.case;if(process.versions.node!=='25.2.1')throw Error('d25_node_version');if(typeof gate2WireEncode!=='function'||typeof gate2WireDecode!=='function'||typeof gate2WireBudget!=='function'||typeof gate2WireInput!=='function')throw Error('d25_codec_absent');if(request.case==='codec_vectors')vectors();else if(request.case==='codec_malformed')malformed();else overflow();report.completed=true;finish(null);}catch(e){finish(new Set(['d25_codec_absent','d25_driver_assertion','d25_driver_input','d25_node_version']).has(e.message)?e.message:'d25_driver_error');}});
"""


def d25_node_driver_v1():
    return (ROOT_ENCODER + '\n' + ROOT_SHA256 + '\n'
            + globals().get('D25_WIRE_CODEC', '') + '\n' + D25_DATA_DRIVER)


class D25WireCodecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import time
        cls.deadline = globals().get('D25_TEST_DEADLINE', time.monotonic() + 295)

    def run_case(self, case):
        from tests.test_accepted_policy_fixture_compiler_gate2_resume_caller_v1 import d25_run_case_v1
        value, capture = d25_run_case_v1(case, b'{}', self.deadline)
        metadata = json.dumps({'case': case, 'report': value, 'capture': capture},
                              sort_keys=True, separators=(',', ':'), ensure_ascii=True)
        tagged = 'D25_CASE_METADATA ' + metadata
        self.assertLessEqual(len((tagged + '\n').encode('ascii')), 32768, 'tagged D25 metadata bound')
        print(tagged)
        self.assertTrue(capture['parent_observed_completion'], 'bounded D25 child/protocol incomplete')
        self.assertTrue(value['completed'], 'D25 controlled case failed: ' + str(value['cause']))
        self.assertIsNone(value['cause'])
        self.assertTrue(value['checks'] and all(row['ok'] for row in value['checks']))
        self.assertEqual(capture['descendant_quiescence'], 'UNKNOWN')

    def test_literal_dictionary_vectors_and_deterministic_parser(self):
        self.run_case('codec_vectors')

    def test_bitpacket_malformed_cause_order(self):
        self.run_case('codec_malformed')

    def test_binary_exact_caps_and_original_deadline(self):
        self.run_case('codec_overflow')


D25_WIRE_CODEC = r"""function gate2WireBudget(now,cause,end=Infinity){
 let origin=null,last=null,limit=null,units=0,failed=false;
 function stop(){failed=true;throw Error(cause);}
 function guard(){
  if(failed)throw Error(cause);
  let n;try{n=now();}catch{stop();}
  if(typeof n!=='number'||!Number.isFinite(n)||last!==null&&n<last)stop();
  if(origin===null){
   if(typeof end!=='number'||!Number.isFinite(end)&&end!==Infinity)stop();
   origin=n;limit=Math.min(n+5000,end);
  }
  last=n;if(n>=limit)stop();units=0;return n;
 }
 guard.work=()=>{if(failed)throw Error(cause);if(origin===null||units===256)guard();units++;};
 guard.phase=fn=>{
  guard();let value,error,threw=false;
  try{value=fn();}catch(e){error=e;threw=true;}
  guard();if(threw)throw error;return value;
 };
 return guard;
}
function gate2WireInput(wire){
 if(typeof wire!=='string'||wire.length<1||wire.length>12288||/[^\x20-\x7e]/.test(wire))throw Error('selected_wire_input');
 return wire;
}
function gate2Fail(c){throw Error('selected_wire_'+c);}
function gate2ABC(){return 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';}
function gate2Index(n){return n>=65&&n<=90?n-65:n>=97&&n<=122?n-71:n>=48&&n<=57?n+4:n===43?62:n===47?63:-1;}
function gate2WireDecode(wire,tag,sha,canon,guard){
gate2WireInput(wire);
const x=guard.phase(()=>{try{return JSON.parse(wire);}catch{gate2Fail('shape');}});
guard.phase(()=>{
if(!x||typeof x!=='object'||Array.isArray(x)||Object.keys(x).sort().join(',')!=='encoding,expanded_sha256,expanded_size_bytes,payload'||
tag!=='gate2-selected-lzss-v2'&&tag!=='gate2-observed-lzss-v2'||x.encoding!==tag||
typeof x.payload!=='string'||x.payload.length>12288||
typeof x.expanded_sha256!=='string'||!/^[0-9a-f]{64}$/.test(x.expanded_sha256)||!Number.isSafeInteger(x.expanded_size_bytes))gate2Fail('shape');
});
const spelling=guard.phase(()=>{try{return canon(x,12288);}catch{gate2Fail('shape');}});
if(spelling!==wire)gate2Fail('shape');
if(x.expanded_size_bytes<1||x.expanded_size_bytes>32768)gate2Fail('bound');
const text=guard.phase(()=>{
const p=x.payload,a=gate2ABC();let pad=p.endsWith('==')?2:p.endsWith('=')?1:0;
if(!p.length||p.length%4)gate2Fail('token');
for(let i=0;i<p.length;i++){guard.work();if(i>=p.length-pad?p[i]!=='=':gate2Index(p.charCodeAt(i))<0)gate2Fail('token');}
if(pad&&(guard.work(),gate2Index(p.charCodeAt(p.length-pad-1))%(pad===2?16:4)))gate2Fail('token');
const size=3*(p.length/4)-pad;if(size<3||size>9216)gate2Fail('token');
guard();const b=new Uint8Array(size);guard();let out=0;
for(let i=0;i<p.length;i+=4){let v=0;for(let j=0;j<4;j++){guard.work();v=v*64+(p[i+j]==='='?0:gate2Index(p.charCodeAt(i+j)));}for(let j=0;j<3&&out<size;j++){guard.work();b[out++]=Math.floor(v/2**(16-8*j))%256;}}
let bits=0;for(let i=0;i<3;i++){guard.work();bits=bits*256+b[i];}
if(!bits||3+Math.ceil(bits/8)!==size||bits%8&&(guard.work(),b[size-1]%2**(8-bits%8)))gate2Fail('token');
let at=0;const output=[];
function read(n){if(at+n>bits)gate2Fail('token');let v=0;for(let i=0;i<n;i++){guard.work();v=v*2+Math.floor(b[3+Math.floor(at/8)]/2**(7-at%8))%2;at++;}return v;}
function append(c){guard.work();if(output.length>=x.expanded_size_bytes||output.length>=32768)gate2Fail('expansion');output.push(c);}
while(at<bits){if(!read(1))append(a[read(6)]);else if(!read(1)){let v=read(7);if(v<32||v>126||gate2Index(v)>=0)gate2Fail('token');append(String.fromCharCode(v));}else{let d=read(15)+1,n=read(8)+3;if(d>output.length)gate2Fail('token');for(let i=0;i<n;i++)append(output[output.length-d]);}}
return output.join('');
});
if(text.length!==x.expanded_size_bytes)gate2Fail('binding');
const digest=guard.phase(()=>sha(text));if(digest!==x.expanded_sha256)gate2Fail('binding');
const value=guard.phase(()=>{try{return JSON.parse(text);}catch{gate2Fail('binding');}});
const recovered=guard.phase(()=>{try{return canon(value,32768);}catch{gate2Fail('binding');}});
if(recovered!==text)gate2Fail('binding');return {text,value};
}
function gate2WireEncode(text,tag,sha,canon,guard){
if(typeof text!=='string'||text.length<1||text.length>32768||/[^\x20-\x7e]/.test(text))throw Error('selected_wire_input');
const digest=guard.phase(()=>{if(tag!=='gate2-selected-lzss-v2'&&tag!=='gate2-observed-lzss-v2')gate2Fail('shape');const v=sha(text);if(typeof v!=='string'||!/^[0-9a-f]{64}$/.test(v))gate2Fail('shape');return v;});
const overhead=guard.phase(()=>{try{return canon({encoding:tag,expanded_sha256:digest,expanded_size_bytes:text.length,payload:''},12288).length;}catch(e){if(e&&e.message==='canonical_bound')gate2Fail('bound');throw e;}});
function bound(bits){guard.work();if(overhead+4*Math.ceil((3+Math.ceil(bits/8))/3)>12288)gate2Fail('bound');}
function walk(emit){
const index=new Map();let at=0;
function insert(p){guard.work();if(p+3>text.length)return;const k=text.slice(p,p+3);let row=index.get(k);if(!row){guard.work();row=[];index.set(k,row);}if(row.length===8){guard.work();row.shift();}guard.work();row.push(p);}
while(at<text.length){guard.work();let best=0,distance=0;
if(at+3<=text.length){guard.work();const row=index.get(text.slice(at,at+3));if(row){while(row.length&&at-row[0]>32768){guard.work();row.shift();}for(const p of row){guard.work();let n=0;while(n<258&&at+n<text.length){guard.work();if(text[p+n]!==text[at+n])break;n++;}let d=at-p;if(n>=3&&(n>best||n===best&&d<distance)){best=n;distance=d;}}}}
const n=best>=3?best:1;if(best>=3)emit(2,distance,best);else{guard.work();const c=text.charCodeAt(at),v=gate2Index(c);emit(v<0?1:0,v<0?c:v,0);}for(let p=at;p<at+n;p++)insert(p);at+=n;
}
}
let bits=0;const counted=[0,0,0];
guard.phase(()=>{bound(0);walk((k,v,n)=>{let width=k===0?7:k===1?9:25,next=bits+width;bound(next);for(let i=0;i<width;i++)guard.work();bits=next;counted[k]++;});});
const size=3+Math.ceil(bits/8);const b=guard.phase(()=>{bound(bits);return new Uint8Array(size);});
let at=0;const written=[0,0,0];
guard.phase(()=>{
for(let i=0;i<3;i++){guard.work();b[i]=Math.floor(bits/2**(16-8*i))%256;}
function write(v,n){if(at+n>bits)gate2Fail('token');for(let i=n-1;i>=0;i--){guard.work();b[3+Math.floor(at/8)]+=Math.floor(v/2**i)%2*2**(7-at%8);at++;}}
walk((k,v,n)=>{written[k]++;write(k===0?v:k===1?256+v:3*2**23+(v-1)*256+n-3,k===0?7:k===1?9:25);});
if(at!==bits||written.some((n,i)=>n!==counted[i])||bits%8&&(guard.work(),b[size-1]%2**(8-bits%8)))gate2Fail('token');
});
const payload=guard.phase(()=>{
bound(bits);const n=4*Math.ceil(size/3),a=gate2ABC();guard();const chars=new Array(n);guard();let at=0;
for(let i=0;i<size;i+=3){let v=0;for(let j=0;j<3;j++){guard.work();v=v*256+(i+j<size?b[i+j]:0);}for(let j=0;j<4;j++){guard.work();chars[at++]=j>1&&i+j-1>=size?'=':a[Math.floor(v/2**(18-6*j))%64];}}
return chars.join('');
});
return guard.phase(()=>{bound(bits);try{return canon({encoding:tag,expanded_sha256:digest,expanded_size_bytes:text.length,payload},12288);}catch(e){if(e&&e.message==='canonical_bound')gate2Fail('bound');throw e;}});
}
"""


# D25 fixed source roles and complete geometry TEST route.
D25_CODEC_SOURCE_PINS = (
    (6903, 'c65b73fe0e7d274040dda413b7871ee83c4c952f9bb2c1e74962b0e3e5f34767'),
    (3939, 'd7f478ee3e5ff65d7146c58e2a9fa078e66219cc1e35ea8547701e576295c32d'),
    (2964, '6123f11ab75ed5a4021dc038ff878cd6873d71492058e8b887d3b3c28b4fc295'),
)

def d25_node_codec_v1(codec):
    import re
    expected = globals().get('D25_CODEC_SOURCE_PINS')
    if (type(expected) is not tuple or len(expected) != 3
            or any(type(row) is not tuple or len(row) != 2
                   or type(row[0]) is not int or not 1 <= row[0] <= 6907
                   or type(row[1]) is not str or re.fullmatch(r'[0-9a-f]{64}', row[1]) is None
                   for row in expected)):
        raise RuntimeError('d25_codec_pins_absent')
    if type(codec) is not str or not 1 <= len(codec) <= 6907 or not codec.isascii():
        raise RuntimeError('d25_codec_source_kind')
    raw = codec.encode('ascii')
    if (len(raw), d22_sha(raw)) != expected[0]:
        raise RuntimeError('d25_codec_source_binding')
    old = D23_WIRE_CODEC
    if (type(old) is not str or not old.isascii() or
            (len(old), d22_sha(old.encode('ascii'))) !=
            (5865, '56708c18c942acfb6e8153971a0013ca79c955e4182efff590ad7ae3a2ba2432')):
        raise RuntimeError('d25_legacy_codec_binding')
    old_boundary = 'function gate2WireDecode(wire,tag,sha,canon,guard){'
    if old.count(old_boundary) != 1 or not codec.startswith(old[:old.index(old_boundary)]):
        raise RuntimeError('d25_budget_input_inverse')
    marker = 'function gate2WireEncode(text,tag,sha,canon,guard){'
    count = codec.count(marker)
    if count != 1:
        raise RuntimeError('d25_codec_marker')
    at = codec.index(marker)
    prefix, excluded = codec[:at], codec[at:]
    if ((len(prefix), d22_sha(prefix.encode('ascii'))) != expected[1]
            or (len(excluded), d22_sha(excluded.encode('ascii'))) != expected[2]
            or len(prefix) + len(excluded) != len(raw) or prefix + excluded != codec):
        raise RuntimeError('d25_codec_role_binding')
    facts = {
        'kind': 'd25_node_codec_role_v1',
        'full_codec_bytes': len(raw), 'full_codec_sha256': d22_sha(raw),
        'node_codec_bytes': len(prefix), 'node_codec_sha256': d22_sha(prefix.encode('ascii')),
        'excluded_encoder_bytes': len(excluded),
        'excluded_encoder_sha256': d22_sha(excluded.encode('ascii')),
        'marker_occurrences': count, 'role_is_exact_prefix': True, 'encoder_excluded': True}
    return prefix, facts


def d25_finalizer_source_v1(initial, deferred, codec, main, caller):
    # Existing construction preserves every effect/custody/clock site. The one
    # selected-view call changes version only; the supplied role is already v2.
    finalizer, old_facts = d23_finalizer_source_v1(initial, deferred, codec, main, caller)
    before = "gate2WireDecode(text,'gate2-selected-lz77-v1',g2.hash,gate2Canonical,guard)"
    after = "gate2WireDecode(text,'gate2-selected-lzss-v2',g2.hash,gate2Canonical,guard)"
    if finalizer.count(before) != 1:
        raise RuntimeError('d25_finalizer_tag_site')
    updated = finalizer.replace(before, after, 1)
    if updated.replace(after, before, 1) != finalizer or before in updated:
        raise RuntimeError('d25_finalizer_tag_inverse')
    facts = dict(old_facts)
    facts.update(finalizer_size_bytes=len(updated),
                 finalizer_sha256=hashlib.sha256(updated.encode('ascii')).hexdigest())
    return updated, facts


def d25_root_wire_sources_v1(codec):
    # The legacy builder remains unchanged. Both returned variants have exactly
    # one selected and one observed call site; no version autodetection exists.
    sources = d23_root_wire_sources_v1(codec)
    result = {}
    for role in ('orchestrator', 'receiver'):
        old = sources[role]
        new = old
        for before, after in (('gate2-selected-lz77-v1', 'gate2-selected-lzss-v2'),
                              ('gate2-observed-lz77-v1', 'gate2-observed-lzss-v2')):
            if new.count(before) != 1:
                raise RuntimeError('d25_root_tag_site')
            new = new.replace(before, after, 1)
        restored = new.replace('gate2-selected-lzss-v2', 'gate2-selected-lz77-v1').replace(
            'gate2-observed-lzss-v2', 'gate2-observed-lz77-v1')
        if restored != old or 'gate2-selected-lz77-v1' in new or 'gate2-observed-lz77-v1' in new:
            raise RuntimeError('d25_root_tag_inverse')
        result[role] = new
    return result


def d25_inert_bundle_v1(deadline):
    import base64
    import math
    import sys
    import time
    from tests import test_accepted_policy_fixture_compiler_gate2_resume_caller_v1 as caller

    last = None
    def gate():
        nonlocal last
        now = time.monotonic()
        if (type(deadline) not in (int, float) or not math.isfinite(deadline)
                or not math.isfinite(now) or deadline - now > 300
                or (last is not None and now < last)
                or now >= deadline - 5):
            raise RuntimeError('d25_construction_deadline')
        last = now

    def canonical(value):
        return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                          allow_nan=False).encode('ascii')

    def digest(value):
        return hashlib.sha256(value).hexdigest()

    gate()
    node_codec, role_facts = d25_node_codec_v1(D25_WIRE_CODEC)
    root = Path(__file__).resolve().parents[1]
    descriptors = (
        ('tests/fixtures/accepted_policy_fixture_compiler_component_v1.py', 32732,
         '329fb13f2c6dcee0872e5a29ec1fd769dc6e57ce92ee1076fef6737f1da86d88',
         '5a342c2c2efa44aa5add3f91ae94518c143acece'),
        ('tests/fixtures/accepted_policy_fixture_compiler_gate2_resume_v1.py', 32739,
         '5fd7d2d6ee62ff584d2a4662757ca804a3d3300d30bb966319901870c4c85670',
         'cc9b6a1b7e6e6ff2f9b750ea67b20cf7213d09b0'))
    held = []
    source_rows = []
    for rel, size, sha, blob in descriptors:
        gate()
        with (root / rel).open('rb') as handle:
            raw = handle.read(32769)
        gate()
        if (len(raw), digest(raw), hashlib.sha1(b'blob ' + str(len(raw)).encode()
                + b'\0' + raw).hexdigest()) != (size, sha, blob):
            raise RuntimeError('d25_fixture_binding')
        held.append(base64.b64encode(raw).decode('ascii'))
        source_rows.append({'size_bytes': size, 'sha256': sha, 'git_blob': blob})
    gate()
    initial, baseline, parts, source_facts = d24_phase_initial_v1(deadline)
    compressed = source_facts['compression']
    if (compressed['parent_observed_completion'] is not True or compressed['causes']
            or compressed['returncode'] != 0 or compressed['timed_out']
            or compressed['kill_requested'] or not compressed['reaped']
            or not compressed['threads_joined']
            or compressed['started_monotonic'] + compressed['elapsed_seconds']
               >= compressed['cleanup_deadline']
            or any(not compressed[name]['eof'] or compressed[name]['overflow']
                   or compressed[name]['io_error'] is not None
                   or compressed[name]['unknown_remainder'] for name in ('stdout', 'stderr'))):
        refusal = RuntimeError('d25_compression_capture_incomplete')
        refusal.metadata = compressed
        raise refusal
    if (set(source_facts) != set('kind source_bytes source_sha256 escaped_source_bytes baseline_bytes baseline_sha256 original_builder_bytes original_builder_sha256 baseline_body_bytes baseline_body_sha256 prefix_bytes prefix_sha256 decoder_bytes decoder_sha256 canonical_data_bytes canonical_data_sha256 compressed_data_bytes compressed_data_sha256 base64_data_bytes base64_data_sha256 data_fields strings_field_absent deferred_definition_bytes deferred_definition_sha256 exact_decoder_inverse exact_phase_inverse exact_inverse_source source_contribution_fits source_only_over_cap_by complete_geometry_qualified behavior_conformance_complete finalizer_implemented generated_operational_program_executed generated_full_subject_files_written status task_2_10_complete compression'.split())
            or source_facts['kind'] != 'd24_initial_source_only_v1'
            or set(role_facts) != set('kind full_codec_bytes full_codec_sha256 node_codec_bytes node_codec_sha256 excluded_encoder_bytes excluded_encoder_sha256 marker_occurrences role_is_exact_prefix encoder_excluded'.split())
            or set(parts) != {'phase_body', 'restored', 'deferred'}
            or parts['restored'] != baseline
            or (len(initial), digest(initial.encode('ascii'))) !=
               (source_facts['source_bytes'], source_facts['source_sha256'])
            or (len(baseline), digest(baseline.encode('ascii'))) !=
               (source_facts['baseline_bytes'], source_facts['baseline_sha256'])
            or (len(parts['deferred']), digest(parts['deferred'].encode('ascii'))) !=
               (source_facts['deferred_definition_bytes'], source_facts['deferred_definition_sha256'])
            or not initial.startswith(D22_PREFIX) or source_facts['data_fields'] != 9
            or source_facts['strings_field_absent'] is not True
            or any(source_facts[name] is not True for name in
                   ('exact_decoder_inverse', 'exact_phase_inverse', 'exact_inverse_source'))):
        raise RuntimeError('d25_initial_binding')
    expected_initial = (
        (source_facts['source_bytes'], source_facts['source_sha256'],
         14162, '4032a534147aada87931734f3b06cde67988d62c75851b959945399843a3770d'),
        (source_facts['canonical_data_bytes'], source_facts['canonical_data_sha256'],
         6566, '8ca48e37f97d03af660960f75afab79db162e8f8997f39f6c1c5c55dd896c97e'),
        (source_facts['compressed_data_bytes'], source_facts['compressed_data_sha256'],
         2365, 'a7caf17aa8d2d5d6beb60880d415e7328947d188623bf5fa0d1ad566e1fd2f2f'))
    if any((size, sha) != (expected_size, expected_sha)
           for size, sha, expected_size, expected_sha in expected_initial):
        raise RuntimeError('d25_unchanged_initial_binding')
    gate()
    program = d25_geometry_driver_v1()
    if type(program) is not str or not program.isascii() or not 0 < len(program) <= 24576:
        raise RuntimeError('d25_geometry_driver_binding')
    driver_facts = {'source_kind': 'd25_fixed_test_driver_v1', 'driver_role': 'geometry',
                    'driver_getter': 'd25_geometry_driver_v1', 'program_bytes': len(program),
                    'program_sha256': digest(program.encode('ascii'))}
    gate()
    finalizer, finalizer_facts = d25_finalizer_source_v1(
        initial, parts['deferred'], node_codec, sys.modules[__name__], caller)
    if (finalizer.count(node_codec) != 1 or D25_WIRE_CODEC in finalizer
            or 'function gate2WireEncode(text,tag,sha,canon,guard){' in finalizer
            or finalizer.count(ROOT_ENCODER) != 1):
        raise RuntimeError('d25_finalizer_codec_role')
    root_sources = d25_root_wire_sources_v1(D25_WIRE_CODEC)
    commit = hashlib.sha1(b'controlled-current-review').hexdigest()
    packet_sha = digest(b'packet')
    factory_sha = digest(caller.CD_FACTORY_SOURCE.encode('ascii'))
    profile = {'max_output_tokens': 100000, 'max_record_bytes': 65536}
    expected = {'code_commit': commit, 'core_sha256': digest(initial.encode('ascii')),
                'factory_sha256': factory_sha}
    prefix = ('// @exec: {"yield_time_ms":1,"max_output_tokens":100000}\n'
              + ROOT_ENCODER + '\n' + ROOT_SHA256 + '\n' + D25_WIRE_CODEC + '\n'
              + root_sources['orchestrator'] + '\n' + root_sources['receiver']
              + '\nconst profile=' + canonical(profile).decode('ascii')
              + ';const record=await gate2Complete(tools,')
    suffix = (',profile,' + canonical(expected).decode('ascii')
              + ');text(gate2Export(record,profile));\n')
    # Factor only the fixed TEST transport. The complete executor below is
    # independently pinned, and the fixed driver reconstructs exactly these
    # bytes in RAM for full-chain measurement. Operational wires stay complete.
    executor = (prefix + json.dumps(initial, ensure_ascii=True, separators=(',', ':'))
                + ',' + json.dumps(finalizer, ensure_ascii=True, separators=(',', ':')) + suffix)
    executor_pin = {'size_bytes': len(executor), 'sha256': digest(executor.encode('ascii'))}
    fixture = ResumeNodeCaller('runTest')
    success = fixture.success_output()
    structured = fixture.failure_output()
    unicode_failure = fixture.failure_output(unicode=True)
    forms = [
        {'id': 'success', 'stdout': success, 'stderr': '', 'success': True},
        {'id': 'structured_failure', 'stdout': '', 'stderr': structured,
         'success': False, 'failure': True},
        {'id': 'unicode_failure', 'stdout': '', 'stderr': unicode_failure,
         'success': False, 'failure': True},
        {'id': 'partial_emission', 'stdout': success[:1024], 'stderr': '',
         'success': False, 'partial': True},
        {'id': 'unknown_closure', 'stdout': success, 'stderr': '',
         'success': False, 'unknown': True},
        {'id': 'setup_refusal', 'stdout': '{}\n', 'stderr': '', 'success': False}]
    gate()
    # This is a DECLARED FUTURE CONTROLLED chain model with every field present.
    # No historical output is filtered or claimed to be a new acquired original.
    chain = [
        {'call': {'type': 'custom_tool_call', 'id': 'd25_exec', 'status': 'completed',
                  'call_id': 'd25_exec_call', 'name': 'exec', 'input': '',
                  'internal_chat_message_metadata_passthrough': {'turn_id': 'd25_controlled_geometry',
                                                              'create_time': 1792314000.25}},
         'result': {'type': 'custom_tool_call_output', 'id': 'd25_exec_output',
                    'call_id': 'd25_exec_call',
                    'output': 'Script running with cell ID d25geometry\nWall time 0.0 seconds\nOutput:\n',
                    'internal_chat_message_metadata_passthrough': {'turn_id': 'd25_controlled_geometry',
                                                                'create_time': 1792314000.5}}},
        {'call': {'type': 'function_call', 'id': 'd25_wait', 'name': 'wait',
                  'arguments': canonical({'cell_id': 'd25geometry', 'max_tokens': 100000,
                                          'yield_time_ms': 1000}).decode('ascii'),
                  'call_id': 'd25_wait_call',
                  'internal_chat_message_metadata_passthrough': {'turn_id': 'd25_controlled_geometry',
                                                              'create_time': 1792314001.25}},
         'result': {'type': 'function_call_output', 'id': 'd25_wait_output',
                    'call_id': 'd25_wait_call',
                    'output': [{'type': 'input_text',
                                'text': 'Script completed\nWall time 0.0 seconds\nOutput:\n'},
                               {'type': 'input_text', 'text': ''}],
                    'internal_chat_message_metadata_passthrough': {'turn_id': 'd25_controlled_geometry',
                                                                'create_time': 1792314001.5}}}]
    # Pure canonical native-format DATA, including the genuine C failure
    # formatter. No native_main, writer, temporary directory or stage is called.
    c = importlib.import_module('tests.fixtures.accepted_policy_fixture_compiler_gate2_c_v1')
    native_root = c.RESUME_OWNER_ROOT_V1.as_posix() + '/r1'
    if len(native_root) != 98:
        raise RuntimeError('d25_native_model_root')
    maximum = 2**64 - 1
    completions = []
    later = []
    native_input = canonical({'current': {descriptors[1][0]: source_rows[1]}}).decode('ascii') + '\n'
    for stage in ('C1', 'C2', 'C3', 'C4', 'C5', 'C6'):
        gate()
        previous = None if stage == 'C1' else completions[-1]['descriptor']['sha256']
        record = c._invocation_record_v1(stage, commit, packet_sha, digest(stage.encode()),
                                         digest(('accounting-' + stage).encode()), previous)
        raw = canonical(record)
        path = native_root + '/outputs/' + stage + '/outer.invocation.original.json'
        complete = {'descriptor': {'path': path, 'size_bytes': len(raw), 'sha256': digest(raw)},
                    'write_facts': {'path': path, 'open_completed': True, 'written_bytes': len(raw),
                                    'write_extent_unknown': False, 'flush_completed': True,
                                    'fsync_completed': True, 'close_completed': True,
                                    'directory_persisted': True, 'complete': True,
                                    'deadline_failed': False, 'failure_causes': []},
                    'completion_deadline_ns': maximum, 'external_approval': False}
        args = [commit, '32768', packet_sha,
                '-' if not completions else ','.join(
                    str(row['descriptor']['size_bytes']) + ':' + row['descriptor']['sha256']
                    for row in completions)]
        completions.append(complete)
        if stage in ('C1', 'C6'):
            stdout = c.component.canonical_json_v1(complete).decode('ascii') + '\n'
            failure = c.native_failure_bytes_v1(c.Gate2Refusal('native_stdout_deadline',
                {'written_bytes': len(stdout), 'write_extent_unknown': False,
                 'flush_completed': False})).decode('ascii')
            if len(stdout.encode('ascii')) > 2048 or len(failure.encode('ascii')) > 768:
                raise RuntimeError('d25_c_model_pipe_bound')
            for failed in (False, True):
                later.append({'id': stage + ('_failure' if failed else '_success'),
                              'stage': stage, 'args': args, 'stdout': stdout,
                              'stderr': failure if failed else '', 'failure': failed,
                              'duration_ms': 150000, 'native_input': native_input})
    summary = {'stage': 'D', 'receipt_sha256': digest(b'controlled-D-receipt'),
               'receipt_size_bytes': 20480,
               'final_measurement': {key: maximum for key in
                                     ('c_free_bytes', 'ext4_used_bytes', 'project_free_bytes')},
               'ledger': {'remaining_before': 536870912, 'charge_bytes': 2097152,
                          'remaining_after': 534773760},
               'deadline_ns': maximum, 'finished_ns': maximum - 1,
               'control_bytes': 524288, 'aggregate_bytes': 2097152, 'passed': True,
               'finalization_complete': True, 'controlled': False, 'external_return_required': True}
    d_stdout = c.component.canonical_json_v1(summary).decode('ascii') + '\n'
    d_failure = c.native_failure_bytes_v1(c.Gate2Refusal('native_stdout_deadline',
        {'written_bytes': len(d_stdout), 'write_extent_unknown': False,
         'flush_completed': False})).decode('ascii')
    if len(d_stdout.encode('ascii')) > 768 or len(d_failure.encode('ascii')) > 768:
        raise RuntimeError('d25_d_model_pipe_bound')
    d_args = [commit, '32768', packet_sha, ','.join(
        str(row['descriptor']['size_bytes']) + ':' + row['descriptor']['sha256']
        for row in completions)]
    for failed in (False, True):
        later.append({'id': 'D_failure' if failed else 'D_success', 'stage': 'D',
                      'args': d_args, 'stdout': d_stdout, 'stderr': d_failure if failed else '',
                      'failure': failed, 'duration_ms': 10000, 'native_input': native_input})
    approval_template = {
        'version': 1, 'kind': 'vast_gate2_external_delivery_approval_v1',
        'receipt_sha256': None, 'context_sha256': None, 'code_commit': commit,
        'packet_size_bytes': 32768, 'packet_sha256': packet_sha, 'selected_sha256': None,
        'core_sha256': expected['core_sha256'], 'factory_sha256': factory_sha,
        'decision': 'approved_for_C1', 'approval_type': 'delegated_agent_self_approval',
        'independent_review_reference': 'https://github.com/lordcoudy/VAST/pull/9#issuecomment-6250553343'}
    approval_reference = 'https://github.com/lordcoudy/VAST/pull/9#issuecomment-' + '9' * 20
    data = {'initial': initial, 'finalizer': finalizer,
            'executor_prefix': prefix, 'executor_suffix': suffix, 'executor_pin': executor_pin,
            'fields': list(NODE_FIELDS), 'pipe_fields': list(NODE_PIPE_FIELDS), 'held': held,
            'commit': commit, 'packet_sha256': packet_sha, 'factory_sha256': factory_sha,
            'forms': forms, 'chain': chain, 'later': later,
            'approval_template': approval_template, 'approval_reference': approval_reference}
    gate()
    encoded = canonical(data)
    facts = {'kind': 'd25_inert_source_construction_metadata_v1',
             'initial': source_facts, 'node_codec': role_facts, 'driver': driver_facts,
             'finalizer': finalizer_facts, 'executor': executor_pin,
             'input_data_size_bytes': len(encoded), 'input_data_sha256': digest(encoded),
             'modeled_setup_form_count': len(forms), 'modeled_later_form_count': len(later),
             'controlled_synthetic_geometry_only': True,
             'independent_actual_acquisition_proven': False,
             'generated_operational_program_execution': False,
             'generated_full_subject_files_written': False,
             'behavior_conformance_complete': False, 'physical_acceptance': False}
    if len(canonical(facts)) > 32768:
        raise RuntimeError('d25_source_metadata_bound')
    return encoded, facts


D25_GEOMETRY_DRIVER = 'function d23Geometry(d,report){\n const z=require(\'node:zlib\'),hash=b=>require(\'node:crypto\').createHash(\'sha256\').update(b).digest(\'hex\'),canon=v=>gate2Canonical(v,262144),ascii=s=>typeof s===\'string\'&&!/[^\\x00-\\x7f]/.test(s);\n const held=d.held.map(s=>Buffer.from(s,\'base64\'));\n function bound(id,ok){report.checks.push({id,ok});}\n function keep(id,text,cap){measure(id,text);bound(id+\'_bound\',text.length<=cap);}\n function provider(text,n){return {content:[{type:\'text\',text}],isError:false,_meta:{actual_ordinal:n,resource:{uri:\'controlled:retained\'}},resource:{mimeType:\'application/json\'}};}\n const start=Number.MAX_SAFE_INTEGER-1500000,work=start+140000,end=start+150000,clock=[start,work,end],poll=\'await gate2Resume.poll();\',ready=\'1755772592209100\\n\',ack_ms=149000;\n const setupInput=Buffer.concat([Buffer.from(canon({remaining_ms:ack_ms,selected_base64:\'\',sha256:hash(\'\'),size_bytes:0})+\'\\n\'),...held]);\n function snapshot(id,kind,raw,input,changes={},n=start+130000,ownClock=null,ack=ack_ms,pid=4294967295){\n  let pieces=[],pipes=raw.map((b,i)=>{\n   let encoding=b.every(x=>x<128)?\'ascii\':\'base64\',v=b.toString(encoding),compressed=z.brotliCompressSync(b,{maxOutputLength:4096}).toString(\'base64\');\n   check(id+\'_pipe\'+i+\'_inverse\',z.brotliDecompressSync(Buffer.from(compressed,\'base64\'),{maxOutputLength:2113}).equals(b));\n   if(JSON.stringify([\'br64\',compressed.length,compressed]).length<JSON.stringify([encoding,v.length,v]).length){encoding=\'br64\';v=compressed;}\n   pieces.push(v);let p={bytes:b.length,sha256:hash(b),eof:true,closed:true,error:false,encoding,chars:v.length,remainder_unknown:false};\n   if(changes.partial&&i===0)Object.assign(p,{eof:false,closed:false,error:true,remainder_unknown:true});\n   return d.pipe_fields.map(k=>p[k]);\n  });\n  let f={pid,returncode:0,signal:null,exited:true,closed:true,pipes,causes:[],unknown_closure:false,completed:true,terminal_observed_ms:n,physical_acceptance:false,clock:ownClock,ack_ms:ack,stdin_finished:true,stdin_closed:true,stdin_bytes:input.length,stdin_sha256:hash(input),stdin_extent_unknown:false,source_facts:null};\n  if(changes.failure)Object.assign(f,{returncode:1,completed:false});\n  if(changes.partial)Object.assign(f,{closed:false,causes:[\'pipe_error\'],unknown_closure:true,completed:false});\n  if(changes.unknown)Object.assign(f,{returncode:null,exited:false,unknown_closure:true,completed:false});\n  if(raw[1].length)f.completed=false;\n  return JSON.stringify([kind,...d.fields.map(k=>f[k])])+\'\\n\'+pieces.join(\'\');\n }\n function writer(id,selected,remaining,cap,formsCap,ownClock,n){\n  const selectedSHA=hash(selected),header=canon({remaining_ms:remaining,selected_base64:Buffer.from(selected).toString(\'base64\'),sha256:selectedSHA,size_bytes:selected.length})+\'\\n\',input=Buffer.concat([Buffer.from(header),...held]),q=Math.ceil(selected.length/4096)*4096,forms=Math.max(cap,q)+q+8192;\n  const facts={stdin_eof:true,stdin_extent_unknown:false,source_bytes:held.map(b=>b.length),source_sha256:held.map(hash),open_completed:true,written_bytes:selected.length,extent_unknown:false,fsync_completed:true,close_completed:true,allocated_bytes:cap,completed:true,sha256:selectedSHA,unknown_closure:false};\n  let receipt=canon({completed:true,external_terminal_required:true,size_bytes:selected.length,sha256:selectedSHA,write_facts:facts,deadline_ns:0,all_forms_quote_bytes:forms})+\'\\n\';\n  check(id+\'_uint64\',receipt.split(\'"deadline_ns":0\').length===2);receipt=receipt.replace(\'"deadline_ns":0\',\'"deadline_ns":18446744073709551615\');\n  const raw=Buffer.from(\'{"ready":true,"schema_version":1}\\n\'+receipt);\n  return {header,input,raw,text:snapshot(id+\'_writer\',2,[raw,Buffer.alloc(0)],input,{},n,ownClock,remaining,4294967294),forms,formsOK:forms<=formsCap,selectedSHA};\n }\n const executor=d.executor_prefix+JSON.stringify(d.initial)+\',\'+JSON.stringify(d.finalizer)+d.executor_suffix;\n const marker=\'const g2factory=function(gate2Resume,nodeRepl){\\n\',at=d.finalizer.indexOf(marker),factorySize=13073;\n check(\'source_bindings\',held.length===2&&ascii(executor)&&executor.length===d.executor_pin.size_bytes&&hash(executor)===d.executor_pin.sha256&&at>=0&&d.finalizer.indexOf(marker,at+1)<0&&hash(d.finalizer.slice(at+marker.length,at+marker.length+factorySize))===d.factory_sha256&&d.finalizer.startsWith(\'\\n};\',at+marker.length+factorySize));\n keep(\'initial_source\',d.initial,262144);keep(\'finalizer_source\',d.finalizer,262144);keep(\'executor_source\',executor,262144);\n function fullChain(id,root){\n  let c=JSON.parse(canon(d.chain)),a=c[0].call,b=c[0].result,w=c[1].call,t=c[1].result;\n  let valid=c.length===2&&a.input===\'\'&&t.output.length===2&&t.output[1].text===\'\'&&a.call_id!==w.call_id&&b.call_id===a.call_id&&t.call_id===w.call_id;\n  const wrapper=/^Script (completed|running with cell ID ([A-Za-z0-9_-]{1,64}))\\nWall time [0-9]{1,12}(?:\\.[0-9]{1,9})? seconds\\nOutput:\\n$/,first=wrapper.exec(b.output),last=wrapper.exec(t.output[0].text);\n  valid=valid&&first&&first[2]&&last&&last[1]===\'completed\'&&b.output.length<=256&&t.output[0].text.length<=256;\n  const wa=JSON.parse(w.arguments);\n  valid=valid&&canon(wa)===w.arguments&&wa.cell_id===first[2]&&wa.max_tokens===100000&&wa.yield_time_ms>=1&&wa.yield_time_ms<=60000;\n  a.input=executor;t.output[1].text=root;\n  check(id+\'_chain_join\',valid&&t.output.slice(1).map(r=>r.text).join(\'\')===root&&typeof b.output===\'string\');\n  return {text:canon(c),reference:\'functions.exec/\'+first[2]};\n }\n check(\'six_setup_forms\',d.forms.length===6&&d.forms.filter(x=>x.success===true).length===1);\n let upstream=null;\n for(const form of d.forms){\n  const id=form.id;check(id+\'_setup\',ascii(form.stdout)&&ascii(form.stderr)&&(!form.success||!form.failure&&!form.partial&&!form.unknown&&!form.stderr));\n  const raw=[Buffer.from(form.stdout),Buffer.from(form.stderr),Buffer.from(ready)];\n  check(id+\'_provider_pipes\',raw[0].length<=2048&&raw[1].length<=2048&&raw[2].length<=32);\n  const terminal=snapshot(id,1,raw,setupInput,form),codes=[d.initial,...Array(5).fill(poll)],frames=codes.map((code,i)=>provider(i===5?terminal:JSON.stringify(i===0?[0,...clock,4294967295,null]:[0,4294967295,null]),i+1));\n  let selected,observed;\n  try{\n   const guard=budget(\'selected_wire_root_deadline\');\n   function original(value){try{return guard.phase(()=>gate2Canonical(value,32768));}catch(e){if(e&&e.message===\'canonical_bound\')throw Error(\'selected_wire_input\');throw e;}}\n   const selectedOriginal=original({call:{tool:\'mcp__node_repl__js\',timeout_ms:32000,codes},frames});\n   keep(id+\'_selected_original\',selectedOriginal,32768);selected=encoded(selectedOriginal,\'gate2-selected-lzss-v2\',guard);\n   const observedOriginal=original({calls:codes.map(code=>({code,timeout_ms:32000})),frames});\n   keep(id+\'_observed_original\',observedOriginal,32768);observed=encoded(observedOriginal,\'gate2-observed-lzss-v2\',guard);\n   keep(id+\'_selected_wire\',selected,12288);keep(id+\'_observed_wire\',observed,12288);\n   const receive=budget(\'selected_wire_receive_deadline\');check(id+\'_full_roundtrip\',decoded(selected,\'gate2-selected-lzss-v2\',receive).text===selectedOriginal&&decoded(observed,\'gate2-observed-lzss-v2\',receive).text===observedOriginal);\n  }catch(e){bound(id+\'_wire_geometry\',false);measure(id+\'_wire_refusal\',String(e.message));continue;}\n  const w=writer(id,selected,19000,12288,32768,clock,start+131000);\n  keep(id+\'_ack\',w.header,24576);keep(id+\'_writer_stdout\',w.raw.toString(\'ascii\'),2112);\n  bound(id+\'_writer_input_bound\',w.input.length<=90112);bound(id+\'_forms_bound\',w.formsOK);\n  const context=form.success?[\'vast.gate2.external-delivery.v1\',d.commit,32768,d.packet_sha256,w.selectedSHA,hash(d.initial),d.factory_sha256]:null,verification=JSON.stringify([3,start+132000,end,form.success,true,w.selectedSHA,context]);\n  const record={completed:form.success,setup_success:form.success,retention_complete:true,physical_acceptance:false,output_profile:{max_output_tokens:100000,max_record_bytes:65536},setup:{observed,selected},writer_call:{code:d.finalizer+\'\\nawait gate2Resume.finish(\'+JSON.stringify(selected)+\');\',timeout_ms:11000},writer:provider(w.text,7),verification_call:{code:\'gate2Resume.verifyReturn(\'+JSON.stringify(w.text)+\');\',timeout_ms:1000},verification:provider(verification,8),context,selected_sha256:w.selectedSHA};\n  const root=canon(record)+\'\\n\',chain=fullChain(id,root);keep(id+\'_root\',root,65536);keep(id+\'_chain\',chain.text,262144);\n  if(form.success&&root.length<=65536&&chain.text.length<=262144&&w.raw.length<=2112&&w.input.length<=90112&&w.formsOK){\n   const receipt={version:1,context_sha256:hash(canon(context)),record_size_bytes:root.length,record_sha256:hash(root),executor_call_sha256:hash(chain.text),max_output_tokens:100000,terminal:\'complete_untruncated\',tool_reference:chain.reference},receiptSHA=hash(canon(receipt));\n   const body=JSON.parse(canon(d.approval_template));check(\'approval_slots\',Object.values(body).filter(v=>v===null).length===3&&[\'receipt_sha256\',\'context_sha256\',\'selected_sha256\'].every(k=>body[k]===null));Object.assign(body,{receipt_sha256:receiptSHA,context_sha256:receipt.context_sha256,selected_sha256:w.selectedSHA});\n   const external={receipt,approval:{reference:d.approval_reference,body_sha256:hash(canon(body)+\'\\n\'),receipt_sha256:receiptSHA}};\n   upstream={pins:[w.selectedSHA,hash(d.initial),d.factory_sha256],external,externalSHA:hash(canon(external))};\n  }\n }\n check(\'six_later_forms\',d.later.length===6&&new Set(d.later.map(x=>x.stage+\':\'+x.failure)).size===6);\n bound(\'later_measured_upstream\',!!upstream);if(!upstream)return;\n for(const form of d.later){\n  let stage=form.stage,id=form.id,args=form.args,duration=stage===\'D\'?10000:150000;\n  check(id+\'_later\',[\'C1\',\'C6\',\'D\'].includes(stage)&&form.duration_ms===duration&&args.length===4&&args[0]===d.commit&&args[1]===\'32768\'&&args[2]===d.packet_sha256&&ascii(form.native_input));\n  const native=[Buffer.from(form.stdout),Buffer.from(form.stderr)],input=Buffer.from(form.native_input),stageStart=start+(stage===\'D\'?1200000:Number(stage.slice(1))*160000),stageEnd=stageStart+duration;\n  check(id+\'_pipe_limits\',native[0].length<=2048&&native[1].length<=768&&native[0].length+native[1].length<=4096);\n  const external=stage===\'C1\'?upstream.external:upstream.externalSHA,begin=\'await gate2Resume.cd.begin(\'+[stage,args,...upstream.pins,external].map(canon).join(\',\')+\');\',next=\'await gate2Resume.cd.poll(1);\';\n  const text=snapshot(id,2,native,input,{failure:form.failure},stageEnd-3000,[stageStart,stageEnd],null),codes=[begin,...Array(5).fill(next)],frames=codes.map((code,i)=>provider(i===5?text:JSON.stringify([0,stage,4294967295,null]),i+1));\n  const selected=canon({call:{tool:\'mcp__node_repl__js\',timeout_ms:32000,codes},frames});keep(id+\'_selected\',selected,4096);keep(id+\'_native_input\',form.native_input,32768);\n  if(selected.length>4096)continue;\n  const w=writer(id,selected,2000,4096,16384,[stageStart,stageEnd],stageEnd-2000);keep(id+\'_ack\',w.header,16384);keep(id+\'_writer_stdout\',w.raw.toString(\'ascii\'),2112);\n  bound(id+\'_writer_forms_bound\',w.formsOK);bound(id+\'_writer_input_bound\',w.input.length<=81920);\n }\n}\n'

D25_GEOMETRY_STDIO = "'use strict';\nlet chunks=[],inputBytes=0,failed=false;\nconst report={schema_version:1,case:'geometry',node_version:process.versions.node,completed:false,cause:null,checks:[],measurements:[]};\nfunction check(id,ok){report.checks.push({id,ok:!!ok});if(!ok)throw Error('d25_driver_assertion');}\nfunction measure(id,text){if(typeof text!=='string'||/[^\\x00-\\x7f]/.test(text)||text.length>262144)throw Error('d25_driver_assertion');report.measurements.push({id,size_bytes:text.length,sha256:gate2SHA256(text)});}\nfunction budget(cause='selected_wire_deadline',now=()=>performance.now(),end=Infinity){return gate2WireBudget(now,cause,end);}\nfunction decoded(text,tag='gate2-selected-lzss-v2',guard=budget()){return gate2WireDecode(text,tag,gate2SHA256,gate2Canonical,guard);}\nfunction encoded(text,tag='gate2-selected-lzss-v2',guard=budget('selected_wire_root_deadline')){return gate2WireEncode(text,tag,gate2SHA256,gate2Canonical,guard);}\nfunction finish(cause){if(failed)return;failed=true;report.cause=cause;process.stdout.write(gate2Canonical(report,32767)+'\\n');}\nprocess.stdin.on('error',()=>finish('d25_driver_input'));\nprocess.stdin.on('data',b=>{if(failed)return;inputBytes+=b.length;if(inputBytes>262144){finish('d25_driver_input');process.stdin.destroy();return;}chunks.push(b);});\nprocess.stdin.on('end',()=>{if(failed)return;try{\n const bytes=Buffer.concat(chunks);chunks=[];if(bytes.some(x=>x>127))throw Error('d25_driver_input');\n const text=bytes.toString('ascii'),request=JSON.parse(text);\n if(!request||typeof request!=='object'||Array.isArray(request)||Object.keys(request).sort().join()!=='case,data'||request.case!=='geometry'||gate2Canonical(request,262144)!==text)throw Error('d25_driver_input');\n if(process.versions.node!=='25.2.1')throw Error('d25_node_version');\n if(typeof gate2WireEncode!=='function'||typeof gate2WireDecode!=='function'||typeof gate2WireBudget!=='function')throw Error('d25_codec_absent');\n d23Geometry(request.data,report);\n if(report.checks.every(row=>row.ok)){report.completed=true;finish(null);}else finish('d25_geometry_hold');\n }catch(e){finish(new Set(['d25_codec_absent','d25_driver_assertion','d25_driver_input','d25_node_version']).has(e.message)?e.message:'d25_driver_error');}});\n"

def d25_geometry_driver_v1():
    old_model = D23_GEOMETRY_DRIVER
    old_stdio = D23_GEOMETRY_STDIO
    if ((len(old_model), d22_sha(old_model.encode('ascii'))) !=
            (11069, '117826dbcc1bc2c3ddbb99941c5d4784c6071a166b79a3673212c066a16cf827')
            or (len(old_stdio), d22_sha(old_stdio.encode('ascii'))) !=
            (2233, '60db15aca044d31019b4479b1d30a27aadc0f4a9cf76f5eb9894c68188b89b26')):
        raise RuntimeError('d25_legacy_geometry_binding')
    if (D25_GEOMETRY_DRIVER.count('gate2-selected-lzss-v2') != 2
            or D25_GEOMETRY_DRIVER.count('gate2-observed-lzss-v2') != 2
            or D25_GEOMETRY_STDIO.count('gate2-selected-lzss-v2') != 2
            or D25_GEOMETRY_DRIVER.replace('gate2-selected-lzss-v2', 'gate2-selected-lz77-v1').replace(
                'gate2-observed-lzss-v2', 'gate2-observed-lz77-v1') != old_model
            or D25_GEOMETRY_STDIO.replace('gate2-selected-lzss-v2', 'gate2-selected-lz77-v1').replace(
                'd25_', 'd23_') != old_stdio):
        raise RuntimeError('d25_geometry_version_inverse')
    return (ROOT_ENCODER + '\n' + ROOT_SHA256 + '\n' + D25_WIRE_CODEC + '\n'
            + D25_GEOMETRY_DRIVER + '\n' + D25_GEOMETRY_STDIO)


class D25CompleteGeometryTests(unittest.TestCase):
    def test_complete_form_bounds_preserve_hold(self):
        # The ONE consumed D25 geometry risk is retained DATA, never replayed.
        import ast
        import copy
        import hashlib
        import json
        import re
        from pathlib import Path

        def require(ok, label):
            if not ok:
                raise AssertionError(label)

        def sha(raw):
            return hashlib.sha256(raw).hexdigest()

        def pairs(rows):
            result = {}
            for key, value in rows:
                require(key not in result, 'duplicate_json_key')
                result[key] = value
            return result

        def load(raw):
            return json.loads(raw, object_pairs_hook=pairs,
                              parse_constant=lambda value: require(False, 'nonfinite_json'))

        def canonical(value):
            return json.dumps(value, sort_keys=True, separators=(',', ':'),
                              ensure_ascii=True, allow_nan=False).encode('ascii')

        def read_bounded(path, limit):
            with path.open('rb') as handle:
                raw = handle.read(limit + 1)
            require(len(raw) <= limit, 'source_read_bound')
            return raw

        main_path = Path(__file__).absolute()
        caller_path = main_path.with_name('test_accepted_policy_fixture_compiler_gate2_resume_caller_v1.py')
        held = {'main': read_bounded(main_path, 524288),
                'caller': read_bounded(caller_path, 524288)}
        texts = {name: raw.decode('utf-8') for name, raw in held.items()}
        trees = {name: ast.parse(text) for name, text in texts.items()}
        data_name = '_D25_GEOMETRY_RETAINED_RESULT_V1'
        data_nodes = [node for node in trees['caller'].body
                      if isinstance(node, ast.Assign)
                      and len(node.targets) == 1
                      and isinstance(node.targets[0], ast.Name)
                      and node.targets[0].id == data_name]
        require(len(data_nodes) == 1, 'retained_assignment_identity')
        payload = ast.literal_eval(data_nodes[0].value)
        require(type(payload) is bytes and
                (len(payload), sha(payload)) ==
                (79735, '5e73ff7af9a7e7becd7d461513fbe9b8ef19c590f091ba8880990f5f63bd70db'),
                'retained_payload_pin')
        retained = load(payload)
        require(type(retained) is dict and set(retained) == {
            'schema_version', 'kind', 'disposition', 'originals',
            'original_development_class', 'source_row_format', 'protected_source_rows',
            'external_formatter_fixture_pins', 'actual_entry', 'root_tool_observation',
            'expected', 'source_guard_policy', 'limits'}, 'retained_schema')
        require(retained['schema_version'] == 1 and
                retained['kind'] == 'd25_retained_geometry_negative_v1' and
                retained['disposition'] == 'INCOMPLETE_WIRE_REFUSAL', 'retained_identity')

        def declared(node):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                return [node.name]
            if isinstance(node, ast.Import):
                return [item.asname or item.name.split('.')[0] for item in node.names]
            if isinstance(node, ast.ImportFrom):
                return [item.asname or item.name for item in node.names]
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                return sorted({item.id for target in targets for item in ast.walk(target)
                               if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store)})
            return []

        def literal(node):
            try:
                ast.literal_eval(node)
            except (ValueError, TypeError, RecursionError, OverflowError):
                require(False, 'additive_literal_required')

        def declaration(node):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                require(not node.decorator_list and not getattr(node, 'type_params', []),
                        'additive_function_modifier')
                for value in node.args.defaults + [v for v in node.args.kw_defaults if v is not None]:
                    literal(value)
                args = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
                args += [arg for arg in (node.args.vararg, node.args.kwarg) if arg is not None]
                for annotation in [arg.annotation for arg in args] + [node.returns]:
                    if annotation is not None:
                        require(isinstance(annotation, ast.Constant)
                                and type(annotation.value) is str, 'additive_annotation')
                return
            if isinstance(node, ast.ClassDef):
                require(not node.decorator_list and not node.keywords
                        and not getattr(node, 'type_params', []) and len(node.bases) == 1
                        and isinstance(node.bases[0], ast.Attribute)
                        and isinstance(node.bases[0].value, ast.Name)
                        and node.bases[0].value.id == 'unittest'
                        and node.bases[0].attr == 'TestCase', 'additive_class_modifier')
                names = set()
                for item in node.body:
                    if isinstance(item, ast.Expr) and isinstance(item.value, ast.Constant) and type(item.value.value) is str:
                        continue
                    require(isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)),
                            'additive_class_body')
                    require(item.name not in names, 'additive_class_duplicate')
                    names.add(item.name)
                    declaration(item)
                return
            require(isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name), 'additive_declaration_required')
            literal(node.value)

        def source_guard(role, text, tree, expected):
            protected = {name for row in expected for name in row[1]}
            protected.update(('D25CompleteGeometryTests', data_name))
            nodes = []
            excluded_class = excluded_data = 0
            for node in tree.body:
                if role == 'main' and isinstance(node, ast.ClassDef) and node.name == 'D25CompleteGeometryTests':
                    require(not node.decorator_list and len(node.body) == 1
                            and isinstance(node.body[0], ast.FunctionDef)
                            and node.body[0].name == 'test_complete_form_bounds_preserve_hold',
                            'replacement_class_shape')
                    excluded_class += 1
                    continue
                if role == 'caller' and declared(node) == [data_name]:
                    require(isinstance(node, ast.Assign) and len(node.targets) == 1
                            and isinstance(node.targets[0], ast.Name), 'retained_assignment_shape')
                    excluded_data += 1
                    continue
                nodes.append(node)
            require(excluded_class == (1 if role == 'main' else 0)
                    and excluded_data == (1 if role == 'caller' else 0), 'source_exclusion_identity')
            require(len(nodes) >= len(expected), 'protected_node_missing')
            for node, wanted in zip(nodes, expected):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    require(not node.decorator_list, 'protected_decorator_changed')
                segment = ast.get_source_segment(text, node)
                require(type(segment) is str, 'protected_segment_missing')
                raw = segment.encode('utf-8')
                actual = [type(node).__name__, declared(node), len(raw), sha(raw)]
                # Exact source is portable across Python minors. Stored raw AST
                # hashes are diagnostics, not a 3.14-to-3.12 comparison gate.
                require(actual == wanted[:4], 'protected_contributor_changed')
            new_names = set()
            for node in nodes[len(expected):]:
                names = declared(node)
                require(len(names) == 1 and names[0] not in protected
                        and names[0] not in new_names, 'additive_binding_reused')
                declaration(node)
                new_names.update(names)

        for role in ('main', 'caller'):
            rows = retained['protected_source_rows'][role]['ordered_rows']
            require(len(rows) == (96 if role == 'main' else 70), 'protected_row_count')
            source_guard(role, texts[role], trees[role], rows)
        root = main_path.parents[1]
        require(len(retained['external_formatter_fixture_pins']) == 4, 'formatter_pin_count')
        for pin in retained['external_formatter_fixture_pins']:
            raw = read_bounded(root / pin['path'], 262144)
            require((len(raw), sha(raw)) == (pin['size_bytes'], pin['sha256']), 'formatter_source_changed')

        def original_class(value):
            raw = value['source_utf8'].encode('utf-8')
            require((len(raw), sha(raw)) ==
                    (10891, 'c804e88a9d5c405ecd66432219fe70e54b33a71c8367b5409df15697aedf9a5d'),
                    'development_class_pin')
            tree = ast.parse(raw.decode('utf-8'))
            require(len(tree.body) == 1 and isinstance(tree.body[0], ast.ClassDef)
                    and tree.body[0].name == 'D25CompleteGeometryTests', 'development_class_shape')

        original_class(retained['original_development_class'])

        def originals(value):
            pins = (
                ('stdout', 15811, 'a4a5ab1731bacdb30596e78f5b977b59b1de9f640c35292ace928c62f65d9f43'),
                ('stderr', 0, 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'),
                ('parent', 3780, '3d31e731927dde64f42e95e8da6921c864a3d9b1bc7f9a4c2a9709e63f4e43b3'),
                ('canonical_report', 4405, '4e3b8c93c98eb7ed3715c5a939531b01b41f59f9c501ff574fce70c115532e17'))
            require(len(value) == 4, 'original_count')
            buffers = {}
            for row, (name, size, digest) in zip(value, pins):
                raw = row['bytes_ascii'].encode('ascii')
                require(row['name'] == name and (len(raw), sha(raw)) == (size, digest)
                        and (row['size_bytes'], row['sha256']) == (size, digest), 'original_pin')
                buffers[name] = raw
            return buffers

        buffers = originals(retained['originals'])
        lines = buffers['stdout'].splitlines(keepends=True)
        require(len(lines) == 7 and all(line.endswith(b'\n') and len(line) <= 32768 for line in lines), 'original_line_shape')
        binding, started = load(lines[0]), load(lines[1])
        require(lines[2].startswith(b'D25_GEOMETRY_SOURCE_METADATA ')
                and lines[3].startswith(b'D25_CASE_METADATA '), 'original_metadata_order')
        source = load(lines[2][len(b'D25_GEOMETRY_SOURCE_METADATA '):])
        case = load(lines[3][len(b'D25_CASE_METADATA '):])
        issue, terminal, summary = (load(line) for line in lines[4:])
        parent = load(buffers['parent'])
        report, capture = case['report'], case['capture']
        test_id = ('tests.test_accepted_policy_fixture_compiler_gate2_resume_v1.'
                   'D25CompleteGeometryTests.test_complete_form_bounds_preserve_hold')
        require(binding['event'] == 'source_bindings'
                and binding['both_buffers_verified_before_either_compile'] is True
                and binding['execution_reopens_test_paths'] is False
                and all(binding[name] is True for name in ('held_caller_aliases_bound',
                    'held_driver_aliases_bound', 'held_driver_loader_bound')), 'original_source_binding')
        run_sources = [{'path': row['path'], 'size_bytes': row['run_preparation_buffer_size_bytes'],
                        'sha256': row['run_preparation_buffer_sha256']}
                       for row in (retained['protected_source_rows']['main'], retained['protected_source_rows']['caller'])]
        require(binding['sources'] == parent['source_pins'] == run_sources, 'run_source_pin_join')
        require(started == {'event': 'test_started', 'test_id': test_id}
                and issue['event'] == 'parent_issue' and issue['test_id'] == test_id
                and terminal['event'] == 'test_terminal' and terminal['test_id'] == test_id
                and terminal['outcome'] == issue['outcome'] == 'failure'
                and terminal['error_type'] == issue['error_type'] == 'AssertionError'
                and terminal['issue_counts'] == {'parent_issue': 1, 'subtest_issue': 0}
                and terminal['subtest_callbacks'] == 0, 'original_failure_identity')
        require(issue['message_size_bytes'] == terminal['message_size_bytes'] == 2540
                and issue['message_sha256'] == terminal['message_sha256'] ==
                '99aa63d206d7144485e96f78b7a409e74a08cc0918e3cf282ff0a3643c008fd6', 'original_failure_pin')
        require(summary == parent['test_summary'] and summary['event'] == 'test_summary'
                and summary['tests_run'] == summary['failures'] == summary['issue_events'] == 1
                and summary['successes'] == summary['errors'] == summary['skips'] == 0
                and summary['successful'] is False and summary['parent_outcomes'] == {'failure': 1}, 'original_summary')
        require(summary['test_streams']['stdout']['observed_bytes'] == len(lines[2] + lines[3])
                and summary['test_streams']['stdout']['sha256'] == sha(lines[2] + lines[3]), 'tagged_stream_join')
        require(set(case) == {'case', 'report', 'capture'} and case['case'] == 'geometry'
                and canonical(report) + b'\n' == buffers['canonical_report'], 'canonical_report_join')
        require(set(source) == set('kind driver initial node_codec finalizer executor input_data_size_bytes input_data_sha256 modeled_setup_form_count modeled_later_form_count controlled_synthetic_geometry_only independent_actual_acquisition_proven generated_operational_program_execution generated_full_subject_files_written behavior_conformance_complete physical_acceptance'.split())
                and source['kind'] == 'd25_inert_source_construction_metadata_v1'
                and source['modeled_setup_form_count'] == source['modeled_later_form_count'] == 6
                and source['controlled_synthetic_geometry_only'] is True, 'source_metadata_shape')
        for name in ('independent_actual_acquisition_proven', 'generated_operational_program_execution',
                     'generated_full_subject_files_written', 'behavior_conformance_complete', 'physical_acceptance'):
            require(source[name] is False, 'source_authority_limit')
        driver = source['driver']
        require(set(driver) == {'source_kind', 'driver_role', 'driver_getter', 'program_bytes', 'program_sha256'}
                and driver == binding['fixed_driver'] == parent['fixed_driver_binding']
                and all(capture[key] == value for key, value in driver.items())
                and driver['source_kind'] == 'd25_fixed_test_driver_v1'
                and driver['driver_role'] == 'geometry' and driver['driver_getter'] == 'd25_geometry_driver_v1'
                and (driver['program_bytes'], driver['program_sha256']) ==
                (24572, 'f3bce3947d93f0a9d630372bd1b0d4d02fe61ecd1e47458259f3a8ccdad72265'), 'actual_driver_join')
        require(source['node_codec'] == binding['codec_role'] == parent['codec_role_binding']
                and source['node_codec']['full_codec_bytes'] == 6903
                and source['node_codec']['node_codec_bytes'] == 3939
                and source['node_codec']['excluded_encoder_bytes'] == 2964, 'actual_codec_role_join')
        initial = source['initial']
        require((initial['source_bytes'], initial['source_sha256'], initial['canonical_data_bytes'],
                 initial['canonical_data_sha256'], initial['compressed_data_bytes'], initial['compressed_data_sha256']) ==
                (14162, '4032a534147aada87931734f3b06cde67988d62c75851b959945399843a3770d',
                 6566, '8ca48e37f97d03af660960f75afab79db162e8f8997f39f6c1c5c55dd896c97e',
                 2365, 'a7caf17aa8d2d5d6beb60880d415e7328947d188623bf5fa0d1ad566e1fd2f2f')
                and initial['data_fields'] == 9 and initial['strings_field_absent'] is True
                and all(initial[name] is True for name in ('exact_decoder_inverse', 'exact_phase_inverse', 'exact_inverse_source')),
                'actual_initial_recipe')

        def complete_capture(value, report_bytes=None):
            require(value['causes'] == [] and type(value['returncode']) is int and value['returncode'] == 0
                    and value['descendant_quiescence'] == 'UNKNOWN', 'capture_status')
            require(all(value[name] is True for name in ('data_only', 'spawned', 'parent_observed_completion',
                    'finished_before_deadline', 'child_completion_observed_before_deadline', 'reaped',
                    'threads_joined', 'stdin_complete', 'stdin_closed')), 'capture_completion')
            require(all(value[name] is False for name in ('timed_out', 'kill_requested',
                    'stdin_extent_unknown', 'stdin_write_in_flight')), 'capture_unknown')
            require(value['started_monotonic'] + value['elapsed_seconds'] < value['cleanup_deadline']
                    <= value['child_total_deadline'] <= value['caller_deadline'] - 5, 'capture_deadline')
            for name in ('stdout', 'stderr'):
                channel = value[name]
                require(channel['eof'] is True and channel['closed'] is True and channel['overflow'] is False
                        and channel['io_error'] is None and channel['unknown_remainder'] is False
                        and channel['observed_bytes'] == channel['retained_bytes'], 'capture_channel')
            require(value['stderr']['retained_bytes'] == 0, 'capture_stderr')
            if report_bytes is not None:
                require((value['report_bytes'], value['report_sha256']) == (len(report_bytes), sha(report_bytes))
                        and value['stdout']['retained_bytes'] == len(report_bytes)
                        and value['stdout']['prefix_sha256'] == sha(report_bytes), 'capture_report_join')

        complete_capture(capture, buffers['canonical_report'])
        compression = initial['compression']
        complete_capture(compression)
        require(compression['quality'] == 11 and compression['roundtrip'] is True
                and (compression['input_bytes'], compression['input_sha256']) ==
                (initial['canonical_data_bytes'], initial['canonical_data_sha256'])
                and (compression['packed_bytes'], compression['packed_sha256']) ==
                (initial['compressed_data_bytes'], initial['compressed_data_sha256']), 'compression_data_join')
        require((capture['data_bytes'], capture['data_sha256']) ==
                (source['input_data_size_bytes'], source['input_data_sha256'])
                and capture['input_bytes'] == capture['stdin_bytes'] == source['input_data_size_bytes'] + 27
                and capture['case_completed'] is False and capture['case_cause'] == 'd25_geometry_hold', 'actual_case_join')

        def negative_dimensions(value, expected):
            require(set(value) == {'schema_version', 'case', 'node_version', 'completed', 'cause', 'checks', 'measurements'}
                    and value['schema_version'] == 1 and value['case'] == 'geometry'
                    and value['node_version'] == '25.2.1' and value['completed'] is False
                    and value['cause'] == 'd25_geometry_hold', 'negative_report_shape')
            checks = {row['id']: row['ok'] for row in value['checks']}
            measures = {row['id']: row for row in value['measurements']}
            require(len(checks) == len(value['checks']) == 49
                    and value['checks'] == expected['check_rows'], 'geometry_check_identity')
            require(len(measures) == len(value['measurements']) == 15
                    and value['measurements'] == expected['measurement_rows'], 'geometry_measurement_identity')
            for row in value['checks']:
                require(set(row) == {'id', 'ok'} and type(row['ok']) is bool, 'geometry_check_shape')
            for row in value['measurements']:
                require(set(row) == {'id', 'size_bytes', 'sha256'} and type(row['size_bytes']) is int
                        and row['size_bytes'] > 0 and re.fullmatch('[0-9a-f]{64}', row['sha256']), 'geometry_measure_shape')
            forms = ('success', 'structured_failure', 'unicode_failure', 'partial_emission', 'unknown_closure', 'setup_refusal')
            later = ('C1_success', 'C1_failure', 'C6_success', 'C6_failure', 'D_success', 'D_failure')
            wanted_checks = {'source_bindings', 'initial_source_bound', 'finalizer_source_bound',
                             'executor_source_bound', 'six_setup_forms', 'six_later_forms', 'later_measured_upstream'}
            wanted_measures = {'initial_source', 'finalizer_source', 'executor_source'}
            for form in forms:
                wanted_checks.update(form + suffix for suffix in ('_setup', '_provider_pipes', '_pipe0_inverse',
                    '_pipe1_inverse', '_pipe2_inverse', '_selected_original_bound', '_wire_geometry'))
                wanted_measures.update((form + '_selected_original', form + '_wire_refusal'))
                require(measures[form + '_selected_original']['size_bytes'] <= 32768
                        and checks[form + '_selected_original_bound'] is True
                        and measures[form + '_wire_refusal']['size_bytes'] == 19
                        and measures[form + '_wire_refusal']['sha256'] ==
                        '17f54ba84e38766575c165a616f7755840343aa043663bd0f9f2f833393831a6', 'selected_refusal_identity')
            require(set(checks) == wanted_checks and set(measures) == wanted_measures, 'negative_available_dimensions')
            false_ids = {form + '_wire_geometry' for form in forms} | {'later_measured_upstream'}
            require({name for name, ok in checks.items() if not ok} == false_ids
                    and sorted(false_ids) == expected['false_check_ids'], 'negative_false_identity')
            base_checks = {'source_bindings', 'six_setup_forms', 'six_later_forms', 'approval_slots', 'later_measured_upstream'}
            caps = {name: 262144 for name in ('initial_source', 'finalizer_source', 'executor_source')}
            for form in forms:
                base_checks.update(form + suffix for suffix in ('_setup', '_provider_pipes', '_pipe0_inverse',
                    '_pipe1_inverse', '_pipe2_inverse', '_full_roundtrip', '_uint64', '_writer_pipe0_inverse',
                    '_writer_pipe1_inverse', '_chain_join', '_writer_input_bound', '_forms_bound'))
                for suffix, cap in (('selected_original', 32768), ('observed_original', 32768), ('selected_wire', 12288),
                                    ('observed_wire', 12288), ('ack', 24576), ('writer_stdout', 2112), ('root', 65536), ('chain', 262144)):
                    caps[form + '_' + suffix] = cap
            for stage in later:
                caps[stage + '_selected'] = 4096
                caps[stage + '_native_input'] = 32768
                base_checks.update(stage + suffix for suffix in ('_later', '_pipe_limits', '_pipe0_inverse', '_pipe1_inverse'))
                require(not any(name.startswith(stage + '_') for name in checks)
                        and not any(name.startswith(stage + '_') for name in measures), 'later_dimensions_unavailable')
            base_checks.update(name + '_bound' for name in caps)
            require(len(base_checks) == 164 and len(caps) == 63
                    and sorted(base_checks - set(checks)) == expected['missing_always_required_check_ids']
                    and sorted(set(caps) - set(measures)) == expected['missing_always_required_measurement_ids']
                    and len(base_checks - set(checks)) == 121 and len(set(caps) - set(measures)) == 54
                    and list(later) == expected['unavailable_conditional_later_groups'], 'negative_missing_identity')
            # No later selected measurement exists, so writer-branch eligibility
            # and all observed/wire/ACK/ROOT/chain/approval dimensions stay unknown.
            require('approval_slots' not in checks and not all(checks.values())
                    and any(not ok and not name.endswith('_bound') for name, ok in checks.items()), 'negative_not_bound_only_hold')
            return measures

        measures = negative_dimensions(report, retained['expected'])
        for name, size, digest in (
                ('initial_source', source['initial']['source_bytes'], source['initial']['source_sha256']),
                ('finalizer_source', source['finalizer']['finalizer_size_bytes'], source['finalizer']['finalizer_sha256']),
                ('executor_source', source['executor']['size_bytes'], source['executor']['sha256'])):
            require((measures[name]['size_bytes'], measures[name]['sha256']) == (size, digest), 'source_measurement_join')
        require(parent['returncode'] == 1 and parent['geometry_fully_measured'] is False
                and parent['geometry_risk_passed'] is False
                and parent['parent_observed_test_transport_complete'] is True
                and parent['threads_joined'] is True and parent['forced_test_child'] is False
                and parent['timed_out'] is False and parent['io_failure'] is False
                and parent['ordered_causes'] == [] and parent['protocol_error_type'] is None
                and parent['descendant_quiescence'] == 'UNKNOWN'
                and parent['generated_operational_program_execution'] is False
                and parent['self_report_persistence_or_whole_process_attested'] is False, 'parent_negative_observation')
        require(parent['child_completion_observed_at'] < parent['cleanup_deadline']
                <= parent['child_total_deadline'], 'parent_observation_deadline')
        for name in ('stdout', 'stderr'):
            channel = parent['channels'][name]
            require((channel['size_bytes'], channel['observed_bytes'], channel['sha256']) ==
                    (len(buffers[name]), len(buffers[name]), sha(buffers[name]))
                    and all(channel[key] is True for key in ('eof', 'closed', 'close_attempted'))
                    and all(channel[key] is False for key in ('overflow', 'closure_unknown', 'remainder_unknown'))
                    and channel['error'] is None, 'parent_original_channel_join')
        require(retained['root_tool_observation'] == {
            'attribution': 'root_observed_tool_result_not_child_self_receipt',
            'tool_chunk': '20e86c', 'exit_code': 1, 'wall_time_seconds': 1.4429275}, 'outer_tool_attribution')

        def refuses(action, expected_label):
            try:
                action()
            except AssertionError as error:
                require(str(error) == expected_label, 'mutation_wrong_refusal')
            else:
                require(False, 'mutation_accepted')

        for index in range(4):
            mutated = copy.deepcopy(retained['originals'])
            mutated[index]['bytes_ascii'] += ' '
            refuses(lambda: originals(mutated), 'original_pin')
        changed_class = copy.deepcopy(retained['original_development_class'])
        changed_class['source_utf8'] += '\n'
        refuses(lambda: original_class(changed_class), 'development_class_pin')
        changed = copy.deepcopy(report)
        changed['measurements'] = changed['measurements'][:-1]
        refuses(lambda: negative_dimensions(changed, retained['expected']), 'geometry_measurement_identity')
        changed = copy.deepcopy(report)
        selected = next(row for row in changed['measurements'] if row['id'] == 'success_selected_original')
        selected['size_bytes'] -= 1
        refuses(lambda: negative_dimensions(changed, retained['expected']), 'geometry_measurement_identity')
        changed = copy.deepcopy(report)
        changed['checks'].append(copy.deepcopy(changed['checks'][0]))
        refuses(lambda: negative_dimensions(changed, retained['expected']), 'geometry_check_identity')
        changed = copy.deepcopy(retained['expected'])
        changed['missing_always_required_measurement_ids'] = changed['missing_always_required_measurement_ids'][1:]
        refuses(lambda: negative_dimensions(report, changed), 'negative_missing_identity')
        changed_capture = copy.deepcopy(capture)
        changed_capture['stdin_extent_unknown'] = True
        refuses(lambda: complete_capture(changed_capture, buffers['canonical_report']), 'capture_unknown')
        changed_capture = copy.deepcopy(capture)
        changed_capture['stdout']['unknown_remainder'] = True
        refuses(lambda: complete_capture(changed_capture, buffers['canonical_report']), 'capture_channel')
        rows = retained['protected_source_rows']['main']['ordered_rows']
        changed_rows = copy.deepcopy(rows)
        changed_rows[0][3] = '0' * 64
        refuses(lambda: source_guard('main', texts['main'], trees['main'], changed_rows), 'protected_contributor_changed')
        changed_tree = copy.deepcopy(trees['main'])
        function = next(node for node in changed_tree.body if isinstance(node, ast.FunctionDef))
        function.decorator_list = [ast.Name(id='changed_decorator', ctx=ast.Load())]
        refuses(lambda: source_guard('main', texts['main'], changed_tree, rows), 'protected_decorator_changed')
        changed_tree = copy.deepcopy(trees['main'])
        changed_tree.body.append(copy.deepcopy(changed_tree.body[0]))
        refuses(lambda: source_guard('main', texts['main'], changed_tree, rows), 'additive_binding_reused')
        changed_tree = copy.deepcopy(trees['main'])
        changed_tree.body.append(ast.Assign(targets=[ast.Name(id='ROOT_ENCODER', ctx=ast.Store())], value=ast.Constant(0)))
        refuses(lambda: source_guard('main', texts['main'], changed_tree, rows), 'additive_binding_reused')
        changed_tree = copy.deepcopy(trees['main'])
        changed_tree.body[0], changed_tree.body[1] = changed_tree.body[1], changed_tree.body[0]
        refuses(lambda: source_guard('main', texts['main'], changed_tree, rows), 'protected_contributor_changed')
        # Fixed Python AST DATA checks the append-only allowance; no source is
        # assembled, compiled or executed, and no generated JS is present.
        additive = ast.FunctionDef(name='_d25_retained_guard_additive_probe_v1',
            args=ast.arguments(posonlyargs=[], args=[], vararg=None, kwonlyargs=[],
                               kw_defaults=[], kwarg=None, defaults=[]),
            body=[ast.Pass()], decorator_list=[], returns=None, type_comment=None,
            type_params=[])
        changed_tree = copy.deepcopy(trees['main'])
        changed_tree.body.append(additive)
        source_guard('main', texts['main'], changed_tree, rows)
        additive.args.defaults = [ast.Call(func=ast.Name(id='unexpected_default', ctx=ast.Load()),
                                         args=[], keywords=[])]
        refuses(lambda: source_guard('main', texts['main'], changed_tree, rows), 'additive_literal_required')
        # CI passing here preserves INCOMPLETE/HOLD. It admits no phase execution.


# Additive D26 TEST-only RED-ready fragment; UNEXECUTED. No codec definition.

D26_DATA_DRIVER = r'''"use strict";
let chunks=[],inputBytes=0,finished=false;
const A='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/',H=Array.from({length:95},(_,i)=>String.fromCharCode(i+32)).filter(c=>c!=='"'&&c!=='\\').join(''),S='gate2-selected-lzss-v3',O='gate2-observed-lzss-v3';
const cases=new Set(['codec_vectors','codec_malformed','codec_overflow']),C={i:'selected_wire_input',s:'selected_wire_shape',b:'selected_wire_bound',t:'selected_wire_token',e:'selected_wire_expansion',h:'selected_wire_binding'};
const j=JSON.stringify,K=gate2Canonical,Q=gate2SHA256;
const E='d26_driver_assertion',I='d26_driver_input',R='selected_wire_root_deadline',V='selected_wire_receive_deadline',D='selected_wire_deadline',F='fixture_semantic_refusal',X='d26_codec_absent',N='d26_node_version';
const report={schema_version:1,case:'codec_vectors',node_version:process.versions.node,completed:false,cause:null,checks:[],measurements:[]};
function ok(id,value){if(report.checks.length>=512)throw Error(E);report.checks.push({id,ok:!!value});if(!value)throw Error(E);}
function ms(id,text){if(report.measurements.length>=128||typeof text!=='string'||text.length>262144||/[^\x00-\x7f]/.test(text))throw Error(E);report.measurements.push({id,size_bytes:text.length,sha256:Q(text)});}
function cause(fn){try{fn();return null;}catch(e){return e.message;}}
function expect(id,fn,wanted){ok(id,cause(fn)===wanted);}
function budget(c=D,now=()=>performance.now(),end=Infinity){return gate2WireBudget(now,c,end);}
function dec(w,tag=S,g=budget()){return gate2WireDecode(w,tag,Q,K,g);}
function enc(t,tag=S,g=budget(R),h=Q){return gate2WireEncode(t,tag,h,K,g);}
function wire(payload,t,tag=S,size=t.length,sha=Q(t)){return K({encoding:tag,expanded_sha256:sha,expanded_size_bytes:size,payload},262144);}
function lit(c){let n=A.indexOf(c);return n<0?[1,c.charCodeAt(0)]:[0,n];}
function lits(t){return Array.from(t,lit);}
function bitsOf(tokens){let b=[];for(let t of tokens){let n=t[0]===0?7:t[0]===1?9:25,v=t[0]===0?t[1]:t[0]===1?256+t[1]:3*2**23+(t[1]-1)*256+t[2]-3;for(let k=n-1;k>=0;k--)b.push(Math.floor(v/2**k)%2);}return b;}
function pkt(bits,count=bits.length,flip=-1){if(bits.length>294912)throw Error(E);let b=[];for(let k=23;k>=0;k--)b.push(Math.floor(count/2**k)%2);b=b.concat(bits);while(b.length%8)b.push(0);while(b.length%13)b.push(0);if(flip>=0)b[flip]^=1;let p='';for(let i=0;i<b.length;i+=13){let v=0;for(let j=0;j<13;j++)v=2*v+b[i+j];p+=H[Math.floor(v/93)]+H[v%93];}return p;}
function pack(t){return pkt(bitsOf(t));}
function oracle(t){let r=[],i=0;while(i<t.length){let b=0,d=0,ps=[];for(let j=Math.max(0,i-32768);j<i&&i+3<=t.length;j++)if(t.slice(j,j+3)===t.slice(i,i+3))ps.push(j);for(let j of ps.slice(-8)){let n=0;while(n<258&&i+n<t.length&&t[j+n]===t[i+n])n++;if(n>=3&&(n>b||n===b&&i-j<d)){b=n;d=i-j;}}r.push(b<3?lit(t[i++]):[2,d,b]);if(b>=3)i+=b;}return r;}
function rep(t,n){while(n){let m=Math.min(258,n);if(m<3)for(let i=0;i<m;i++)t.push(lit('a'));else t.push([2,1,m]);n-=m;}return t;}
function probe(p,fn){const P=String.prototype,B='charCodeAt';let reads=[],work=0,phases=0,active=false,g=budget(V,()=>0),w=g.work,f=g.phase,d=Object.getOwnPropertyDescriptor(P,B);try{g.work=()=>{w();work++;};g.phase=fn=>{active=++phases===4;try{return f(fn);}finally{active=false;}};Object.defineProperty(P,B,{...d,value:function(i){'use strict';if(active&&this===p&&(typeof i!=='number'||!Number.isInteger(i)||i<0||i>=p.length))throw Error(E);let v=Reflect.apply(d.value,this,[i]);if(active&&this===p){if(reads.length>=2048)throw Error(E);reads.push([i,work]);}return v;}});return [fn(g),reads,work,phases];}finally{try{Object.defineProperty(P,B,d);}finally{g.work=w;g.phase=f;}if(P[B]!==d.value||g.work!==w||g.phase!==f)throw Error(E);}}
function cold(n){let t=j('a'.repeat(n)),bits=bitsOf(lits(t)),p=pkt(bits),N=3+Math.ceil(bits.length/8),M=p.length/2,expected=Array.from({length:p.length},(_,i)=>i),last=-1;function visit(i){let q=Math.floor(i/13);if(q!==last){expected.push(2*q,2*q+1);last=q;}}for(let i=0;i<24;i++)visit(i);for(let i=24+bits.length;i<8*N;i++)visit(i);for(let i=8*N;i<13*M;i++)visit(i);for(let i=24;i<24+bits.length;i++)visit(i);let r=probe(p,g=>dec(wire(p,t),S,g));ok('cold_'+n,r[0].text===t&&r[3]===7);ok('reads_'+n,j(r[1].map(x=>x[0]))===j(expected));ok('work_'+n,r[1].every((x,i)=>x[1]>(i?r[1][i-1][1]:0))&&r[2]>=r[1].length+13*M+t.length);}
function vectors(){
let good=true,count=0;for(let i=32;i<=126;i++){let t=j(String.fromCharCode(i)),p=pack(lits(t));good=(dec(wire(p,t)).text===t&&JSON.parse(enc(t)).payload===p)&&good;count++;}ok('literals95',good&&count===95&&H.length===93);
let digits=new Set(),bp=new Set(),gp=new Set();good=true;for(let n=0;n<93;n++){let t=j('a'.repeat(n)),T=18+7*n,p=pack(lits(t)),N=3+Math.ceil(T/8);digits.add(H.indexOf(p[3]));bp.add((8-T%8)%8);gp.add((13-8*N%13)%13);good=(H.indexOf(p[3])===(4*T+2)%93&&dec(wire(p,t)).text===t)&&good;}ok('digits93',good&&digits.size===93);ok('two_tails',bp.size===8&&gp.size===13);
const samples=[['min','aaaa'],['max','a'.repeat(259)],['overlap','ab'.repeat(130)],['longest','abcXabcYZabcYQabcYZ'],['nearest','abcXabcYabcZ'],['last8','abcLONGer'+Array.from({length:10},(_,i)=>'abc'+i).join('')+'abcLONGer'],['consumed','abcdefgh'.repeat(110)+'abcXYZabcUVWabcXYZ'],['d4096','ABC'+'Z'.repeat(4093)+'ABC'],['d4097','ABC'+'Z'.repeat(4094)+'ABC']];
for(let [id,v] of samples){let t=j(v),w=enc(t);ok(id,JSON.parse(w).payload===pack(oracle(t))&&dec(w).text===t&&w===enc(t));ms(id,w);}
ok('min3_25_vs21',JSON.parse(enc('"aaaa"')).payload===pack([lit('"'),lit('a'),[2,1,3],lit('"')]));ok('max258',JSON.parse(enc(j('a'.repeat(259)))).payload===pack([lit('"'),lit('a'),[2,1,258],lit('"')]));
let groups=new Set(),bytes=new Set();good=true;for(let n=1;n<=13;n++){let t=j('a'.repeat(n+3)),tokens=[lit('"'),...Array.from({length:n},()=>lit('a')),[2,1,3],lit('"')];groups.add((33+7*n)%13);bytes.add((9+7*n)%8);good=dec(wire(pack(tokens),t)).text===t&&good;}ok('offsets13_8',good&&groups.size===13&&bytes.size===8);ok('pending37',groups.has(12)&&12+25===37&&bytes.has(7)&&7+25===32);
cold(1);cold(290);
let t=j('a'.repeat(11000)),T=77018,p=pack(lits(t)),w=wire(p,t);ok('virtual9631',t.length===11002&&3+Math.ceil(T/8)===9631&&p.length===11854&&w.length===12017&&dec(w).text===t);ms('v9631_wire',w);
t=j('abc'.repeat(90));let s=enc(t),o=enc(t,O);ok('tags',s!==o&&JSON.parse(s).payload===JSON.parse(o).payload&&dec(o,O).text===t);expect('tag_swap',()=>dec(o),C.s);
let tokens=rep([lit('"'),lit('a')],32763);tokens.push([2,32765,3]);t='"'+'a'.repeat(32764)+'"aa';ok('d32765',JSON.parse(enc(t)).payload===pack(tokens));expect('d32765_bind',()=>dec(wire(pack(tokens),t)),C.h);ok('nested',dec(enc(enc('"a"'))).text===enc('"a"'));
}
function malformed(){
for(let [id,v] of [['null',null],['number',1],['empty',''],['nonprint','\n'],['long','x'.repeat(12289)]])expect('input_'+id,()=>dec(v),C.i);
const t='"a"',bits=bitsOf(lits(t)),p=pkt(bits),w=wire(p,t),base=JSON.parse(w);function change(k,v){return K({...base,[k]:v},32768);}
for(let [id,v] of [['parse','{'],['array','[]'],['extra',change('extra',1)],['tag',change('encoding','wrong')],['hash',change('expanded_sha256','A'.repeat(64))],['bool',change('expanded_size_bytes',true)],['fraction',change('expanded_size_bytes',1.5)],['exponent',w.replace('"expanded_size_bytes":3','"expanded_size_bytes":3e0')],['negative_zero',w.replace('"expanded_size_bytes":3','"expanded_size_bytes":-0')],['space',w+' ']])expect('shape_'+id,()=>dec(v),C.s);
for(let n of [-1,0,32769])expect('range_'+String(n).replace('-','m'),()=>dec(wire(p,t,S,n)),C.b);
for(let [id,q] of [['empty',''],['one_pair',H[0]+H[0]],['two_pairs',pkt([],1)],['odd',p+H[0]],['suffix',p+H[0]+H[0]],['quote','"'+p.slice(1)],['slash','\\'+p.slice(1)],...[9,10,31,127,233].map(n=>[n,String.fromCharCode(n)+p.slice(1)]),['zero_header',pkt([])],['huge_header',pkt(bits,16777215)],['more_header',pkt(bits,bits.length+16)],['less_header',pkt(bits,bits.length-8)]])expect('syntax_'+id,()=>probe(q,g=>dec(wire(q,t),S,g)),C.t);
let tail=[true,true];for(let i=49;i<65;i++){let k=i<56?0:1;tail[k]=cause(()=>dec(wire(pkt(bits,bits.length,i),t,S,1)))===C.t&&tail[k];}ok('byte_pad',tail[0]);ok('group_pad',tail[1]);
let count=0,good=true;for(let v=8192;v<8649;v++){let q=p.slice(0,-2)+H[Math.floor(v/93)]+H[v%93];good=cause(()=>dec(wire(q,t,S,1)))===C.t&&good;count++;}ok('pairs457',good&&count===457);
for(let [id,b] of [['prefix1',[1]],['common_short',[0]],['other_short',[1,0,1]],['distance_short',[1,1,0]],['length_short',[1,1,...Array(15).fill(0),0]]])expect(id,()=>dec(wire(pkt(b),t)),C.t);
count=0;good=true;for(let n=0;n<128;n++)if(n<32||n===127||A.includes(String.fromCharCode(n))){good=cause(()=>dec(wire(pack([[1,n]]),t,S,1)))===C.t&&good;count++;}ok('other97',good&&count===97);
for(let [id,tokens,text,size,c] of [['no_prefix',[[2,1,3]],t,1,C.t],['distance_first',[lit('a'),[2,2,3]],'a',1,C.t],['other_first',[lit('a'),[1,65]],'a',1,C.t],['extra',[lit('a'),lit('b')],'a',1,C.e],['short',lits(t),t,4,C.h]])expect(id,()=>dec(wire(pack(tokens),text,S,size)),c);
expect('bad_next',()=>dec(wire(pkt(bitsOf([lit('a')]).concat([1])),'a',S,1)),C.t);expect('sha',()=>dec(wire(p,t,S,3,'0'.repeat(64))),C.h);
for(let [id,v] of [['json','abc'],['canonical','{ "a":1}']])expect(id,()=>dec(wire(pack(lits(v)),v)),C.h);expect('header_not_size',()=>dec(wire(pack(lits('ab')),'a',S,1)),C.e);
let seen=0,semantic=q=>{dec(q);seen++;throw Error(F);};expect('before_sem',()=>semantic(wire(H[92]+H[92],t)),C.t);ok('sem_zero',seen===0);expect('after_sem',()=>semantic(w),F);ok('sem_once',seen===1);
}
function overflow(){
const maximum=j('a'.repeat(32766)),w=enc(maximum);ok('expanded_max',maximum.length===32768&&dec(w).text===maximum);ms('max_wire',w);expect('expanded_over',()=>enc(maximum+' '),C.i);
let full=rep([lit('"'),lit('a')],32765);full.push(lit('"'),[2,32768,3]);expect('d32768_full',()=>dec(wire(pack(full),maximum)),C.e);expect('d32768_short',()=>dec(wire(pack([lit('a'),[2,32768,3]]),'a')),C.t);
const exact=wire(pkt(Array(78808).fill(0)),'A'.repeat(99));ok('wire_exact',exact.length===12288);expect('exact_expands',()=>dec(exact),C.e);expect('wire_plus1',()=>dec(exact+' '),C.i);expect('bit_quantum',()=>dec(wire(pkt(Array(78809).fill(0)),'A'.repeat(99))),C.i);ms('wire_exact',exact);
let seq='',a=Array(4).fill(0);function db(t,p){if(t>3){if(3%p===0)for(let i=1;i<=p;i++)seq+=A[a[i]];}else{a[t]=a[t-p];db(t+1,p);for(let j=a[t-p]+1;j<32;j++){a[t]=j;db(t+1,t);}}}db(1,1);const text=j(seq.slice(0,32766)),edge=j('!#$%'+seq.slice(4,11250)),eb=bitsOf(lits(edge)),ew=wire(pkt(eb),edge);ok('count',seq.length===32768&&text.length===32768);ok('enc_edge',eb.length===78776&&ew.length===12287&&enc(edge)===ew&&dec(ew).text===edge);expect('edge_bit_over',()=>dec(wire(pkt(eb.concat([0])),edge)),C.i);
const Arr=globalThis.Array,M=globalThis.Map;let ar=[],maps=0,on=false,hc=0;function hash(t){on=true;try{return Q(t);}finally{on=false;}}function log(a){if(on){if(a.length!==1||a[0]!==64)throw Error(E);hc++;}else ar.push(a[0]);}try{globalThis.Array=new Proxy(Arr,{construct(T,a){log(a);return Reflect.construct(T,a);},apply(T,x,a){log(a);return Reflect.apply(T,x,a);}});expect('count1',()=>enc(text,S,undefined,hash),C.b);ok('no_vec',ar.length===0&&hc>0);let v=enc(edge,S,undefined,hash);ok('one_vec',ar.length===1&&ar[0]===JSON.parse(v).payload.length);}finally{globalThis.Array=Arr;}try{globalThis.Map=new Proxy(M,{construct(T,args){maps++;return Reflect.construct(T,args);}});let v=enc('"abcabcabcabc"');ok('two_maps',maps===2&&JSON.parse(v).payload===pack(oracle('"abcabcabcabc"')));}finally{globalThis.Map=M;}
for(let c of [D,R,V]){let clock=0,g=budget(c,()=>clock);g.phase(()=>true);clock=5000;expect(c,()=>dec(w,S,g),c);clock=0;g=budget(c,()=>clock);expect(c+'_post_throw',()=>g.phase(()=>{clock=5000;throw Error(C.t);}),c);}
let clock=0,g=budget(V,()=>clock);dec(w,S,g);clock=5000;expect('shared_receive',()=>dec(enc('"a"',O),O,g),V);clock=0;g=budget(R,()=>clock);enc('"a"',S,g);clock=5000;expect('shared_encode',()=>enc('"a"',O,g),R);let calls=0;expect('regression',()=>enc('"a"',S,budget(R,()=>calls++?-1:0)),R);expect('nonfinite',()=>dec(w,S,budget(V,()=>Infinity)),V);expect('due_bad_pair',()=>dec(wire(H[92]+H[92],'a'),S,budget(V,()=>5000,5000)),V);
}
function finish(c){if(finished)return;finished=true;report.cause=c;process.stdout.write(K(report,32767)+'\n');}
process.stdin.on('error',()=>finish(I));
process.stdin.on('data',b=>{if(finished)return;inputBytes+=b.length;if(inputBytes>262144){finish(I);process.stdin.destroy();return;}chunks.push(b);});
process.stdin.on('end',()=>{if(finished)return;try{const b=Buffer.concat(chunks);chunks=[];if(b.some(x=>x>127))throw Error(I);const text=b.toString('ascii'),r=JSON.parse(text);if(!r||typeof r!=='object'||Array.isArray(r)||Object.keys(r).sort().join()!=='case,data'||!cases.has(r.case)||K(r,262144)!==text)throw Error(I);report.case=r.case;if(process.versions.node!=='25.2.1')throw Error(N);if(typeof gate2WireEncode!=='function'||typeof gate2WireDecode!=='function'||typeof gate2WireBudget!=='function'||typeof gate2WireInput!=='function')throw Error(X);if(r.case==='codec_vectors')vectors();else if(r.case==='codec_malformed')malformed();else overflow();report.completed=true;finish(null);}catch(e){finish(new Set([X,E,I,N]).has(e.message)?e.message:'d26_driver_error');}});
'''

def d26_node_driver_v1():
    return (ROOT_ENCODER + '\n' + ROOT_SHA256 + '\n'
            + globals().get('D26_WIRE_CODEC', '') + '\n' + D26_DATA_DRIVER)


class D26WireCodecTests(unittest.TestCase):
    def setUpClass():
        import time
        D26WireCodecTests.deadline = globals().get('D26_TEST_DEADLINE', time.monotonic() + 295)

    def run_case(self, case):
        from tests.test_accepted_policy_fixture_compiler_gate2_resume_caller_v1 import d26_run_case_v1
        value, capture = d26_run_case_v1(case, b'{}', self.deadline)
        metadata = json.dumps({'case': case, 'report': value, 'capture': capture},
                              sort_keys=True, separators=(',', ':'), ensure_ascii=True)
        tagged = 'D26_CASE_METADATA ' + metadata
        self.assertLessEqual(len((tagged + '\n').encode('ascii')), 32768, 'tagged D26 metadata bound')
        print(tagged)
        self.assertTrue(capture['parent_observed_completion'], 'bounded D26 child/protocol incomplete')
        self.assertTrue(value['completed'], 'D26 controlled case failed: ' + str(value['cause']))
        self.assertIsNone(value['cause'])
        self.assertTrue(value['checks'] and all(row['ok'] for row in value['checks']))
        self.assertEqual(capture['descendant_quiescence'], 'UNKNOWN')

    def test_radix93_vectors_and_deterministic_parser(self):
        self.run_case('codec_vectors')

    def test_radix93_malformed_cause_order(self):
        self.run_case('codec_malformed')

    def test_radix93_caps_and_original_deadline(self):
        self.run_case('codec_overflow')


# Additive D26 fixed virtual-radix93 CODEC source; UNEXECUTED.
D26_WIRE_CODEC = r'''function gate2WireBudget(now,cause,end=Infinity){
 let origin=null,last=null,limit=null,units=0,failed=false;
 function stop(){failed=true;throw Error(cause);}
 function guard(){
  if(failed)throw Error(cause);
  let n;try{n=now();}catch{stop();}
  if(typeof n!=='number'||!Number.isFinite(n)||last!==null&&n<last)stop();
  if(origin===null){
   if(typeof end!=='number'||!Number.isFinite(end)&&end!==Infinity)stop();
   origin=n;limit=Math.min(n+5000,end);
  }
  last=n;if(n>=limit)stop();units=0;return n;
 }
 guard.work=()=>{if(failed)throw Error(cause);if(origin===null||units===256)guard();units++;};
 guard.phase=fn=>{
  guard();let value,error,threw=false;
  try{value=fn();}catch(e){error=e;threw=true;}
  guard();if(threw)throw error;return value;
 };
 return guard;
}
function gate2WireInput(wire){
 if(typeof wire!=='string'||wire.length<1||wire.length>12288||/[^\x20-\x7e]/.test(wire))throw Error('selected_wire_input');
 return wire;
}
function gate2F(c){throw Error('selected_wire_'+c);}
function gate2A(){return 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';}
function gate2I(n){return n>=65&&n<=90?n-65:n>=97&&n<=122?n-71:n>=48&&n<=57?n+4:n===43?62:n===47?63:-1;}
function gate2WireDecode(wire,tag,sha,canon,guard){
gate2WireInput(wire);
const x=guard.phase(()=>{try{return JSON.parse(wire);}catch{gate2F('shape');}});
guard.phase(()=>{
if(!x||typeof x!=='object'||Array.isArray(x)||Object.keys(x).sort().join(',')!=='encoding,expanded_sha256,expanded_size_bytes,payload'||
tag!=='gate2-selected-lzss-v3'&&tag!=='gate2-observed-lzss-v3'||x.encoding!==tag||
typeof x.payload!=='string'||x.payload.length>12288||
typeof x.expanded_sha256!=='string'||!/^[0-9a-f]{64}$/.test(x.expanded_sha256)||!Number.isSafeInteger(x.expanded_size_bytes))gate2F('shape');
});
const spell=guard.phase(()=>{try{return canon(x,12288);}catch{gate2F('shape');}});
if(spell!==wire)gate2F('shape');
if(x.expanded_size_bytes<1||x.expanded_size_bytes>32768)gate2F('bound');
const text=guard.phase(()=>{
const p=x.payload,a=gate2A(),pairs=p.length/2;
if(!p.length||p.length%2)gate2F('token');
function rank(i){guard.work();const c=p.charCodeAt(i);guard.work();if(c<32||c>126||c===34||c===92)gate2F('token');return c-32-(c>34)-(c>92);}
function pair(q){const v=rank(q*2)*93+rank(q*2+1);guard.work();if(v>8191)gate2F('token');return v;}
for(let q=0;q<pairs;q++){guard.work();pair(q);}
if(pairs<2)gate2F('token');
let ci=-1,value=0;
function bit(i){guard.work();if(i<0||i>=13*pairs)gate2F('token');const q=Math.floor(i/13);guard.work();if(q!==ci){value=pair(q);ci=q;}guard.work();return Math.floor(value/2**(12-i%13))%2;}
let bits=0;for(let i=0;i<24;i++){guard.work();bits=bits*2+bit(i);}
const size=3+Math.ceil(bits/8);
if(!bits||size>9984||p.length!==2*Math.ceil(8*size/13))gate2F('token');
for(let i=24+bits;i<8*size;i++){guard.work();if(bit(i))gate2F('token');}
for(let i=8*size;i<13*pairs;i++){guard.work();if(bit(i))gate2F('token');}
let at=0;const output=[];
function read(n){guard.work();if(at+n>bits)gate2F('token');let v=0;for(let i=0;i<n;i++){guard.work();v=v*2+bit(24+at);at++;}return v;}
function append(c){guard.work();if(output.length>=x.expanded_size_bytes||output.length>=32768)gate2F('expansion');output.push(c);}
while(at<bits){if(!read(1))append(a[read(6)]);else if(!read(1)){let v=read(7);if(v<32||v>126||gate2I(v)>=0)gate2F('token');append(String.fromCharCode(v));}else{let d=read(15)+1,n=read(8)+3;if(d>output.length)gate2F('token');for(let i=0;i<n;i++)append(output[output.length-d]);}}
return output.join('');
});
if(text.length!==x.expanded_size_bytes)gate2F('binding');
const digest=guard.phase(()=>sha(text));if(digest!==x.expanded_sha256)gate2F('binding');
const value=guard.phase(()=>{try{return JSON.parse(text);}catch{gate2F('binding');}});
const rc=guard.phase(()=>{try{return canon(value,32768);}catch{gate2F('binding');}});
if(rc!==text)gate2F('binding');return {text,value};
}
function gate2WireEncode(text,tag,sha,canon,guard){
function gate2D(n){return String.fromCharCode(n+32+(n>=2)+(n>=59));}
if(typeof text!=='string'||text.length<1||text.length>32768||/[^\x20-\x7e]/.test(text))throw Error('selected_wire_input');
const digest=guard.phase(()=>{if(tag!=='gate2-selected-lzss-v3'&&tag!=='gate2-observed-lzss-v3')gate2F('shape');const v=sha(text);if(typeof v!=='string'||!/^[0-9a-f]{64}$/.test(v))gate2F('shape');return v;});
const head=guard.phase(()=>{try{return canon({encoding:tag,expanded_sha256:digest,expanded_size_bytes:text.length,payload:''},12288).length;}catch(e){if(e&&e.message==='canonical_bound')gate2F('bound');throw e;}});
function bound(bits){guard.work();const n=3+Math.ceil(bits/8);if(n>9984||head+2*Math.ceil(8*n/13)>12288)gate2F('bound');}
function walk(emit){
const index=new Map();let at=0;
function insert(p){guard.work();if(p+3>text.length)return;const k=text.slice(p,p+3);let row=index.get(k);if(!row){guard.work();row=[];index.set(k,row);}if(row.length===8){guard.work();row.shift();}guard.work();row.push(p);}
while(at<text.length){guard.work();let best=0,dist=0;
if(at+3<=text.length){guard.work();const row=index.get(text.slice(at,at+3));if(row){while(row.length&&at-row[0]>32768){guard.work();row.shift();}for(const p of row){guard.work();let n=0;while(n<258&&at+n<text.length){guard.work();if(text[p+n]!==text[at+n])break;n++;}let d=at-p;if(n>=3&&(n>best||n===best&&d<dist)){best=n;dist=d;}}}}
const n=best>=3?best:1;if(best>=3)emit(2,dist,best);else{guard.work();const c=text.charCodeAt(at),v=gate2I(c);emit(v<0?1:0,v<0?c:v,0);}for(let p=at;p<at+n;p++)insert(p);at+=n;
}
}
let bits=0;const ct=[0,0,0];
guard.phase(()=>{bound(0);walk((k,v,n)=>{guard.work();let w=k===0?7:k===1?9:25,next=bits+w;bound(next);for(let i=0;i<w;i++)guard.work();bits=next;ct[k]++;});});
const size=3+Math.ceil(bits/8),length=2*Math.ceil(8*size/13);
const chars=guard.phase(()=>{bound(bits);guard();const a=new Array(length);guard();return a;});
let at=0,pending=0,group=0,filled=0;const wr=[0,0,0];
guard.phase(()=>{
function feed(v,n){for(let i=n-1;i>=0;i--){guard.work();group=group*2+Math.floor(v/2**i)%2;pending++;at++;if(pending===13){guard.work();if(filled+2>length)gate2F('token');guard.work();chars[filled++]=gate2D(Math.floor(group/93));guard.work();chars[filled++]=gate2D(group%93);pending=0;group=0;}}}
feed(bits,24);
walk((k,v,n)=>{guard.work();wr[k]++;const w=k===0?7:k===1?9:25;if(at+w>24+bits)gate2F('token');feed(k===0?v:k===1?256+v:3*2**23+(v-1)*256+n-3,w);});
if(at!==24+bits||wr.some((n,i)=>n!==ct[i]))gate2F('token');
while(at<8*size)feed(0,1);if(at!==8*size)gate2F('token');while(pending)feed(0,1);
if(at!==13*length/2||filled!==length||group!==0)gate2F('token');
});
const payload=guard.phase(()=>chars.join(''));
return guard.phase(()=>{bound(bits);try{return canon({encoding:tag,expanded_sha256:digest,expanded_size_bytes:text.length,payload},12288);}catch(e){if(e&&e.message==='canonical_bound')gate2F('bound');throw e;}});
}
'''


D26_CODEC_SOURCE_PINS = ((6907, 'be9a631d6eaa3191237d64f80dec89024d7e098c8249b55566549321dfa907b2'), (3918, '6e1467c2d1351dba5569b5a763ba29135287c7ca946c25b9456ddbc5b3274a47'), (2989, '0ff2e403ef1b83fb1b2698b3eab078d314be45b9bdf11d7147120243e216e237'))

def d26_geometry_driver_v1():
    import sys
    import types
    from pathlib import Path
    names = ('tests.test_accepted_policy_fixture_compiler_gate2_resume_caller_v1',
             'test_accepted_policy_fixture_compiler_gate2_resume_caller_v1')
    expected = Path(__file__).with_name('test_accepted_policy_fixture_compiler_gate2_resume_caller_v1.py').absolute()
    present = [(name, sys.modules[name]) for name in names if name in sys.modules]
    if not present:
        raise RuntimeError('d26_held_caller_unavailable')
    selected_name, selected = present[0]
    for name, module in present:
        if type(module) is not types.ModuleType:
            raise RuntimeError('d26_held_caller_unavailable')
        namespace = vars(module)
        if (namespace.get('__name__') != name and module is not selected
                or type(namespace.get('__file__')) is not str
                or Path(namespace['__file__']).absolute() != expected):
            raise RuntimeError('d26_held_caller_unavailable')
    namespace = vars(selected)
    getter = namespace.get('_d26_geometry_program_v1')
    if (namespace.get('__name__') != selected_name or type(getter) is not types.FunctionType
            or getter.__name__ != '_d26_geometry_program_v1' or getter.__module__ != selected_name
            or getter.__globals__ is not namespace or Path(getter.__code__.co_filename).absolute() != expected):
        raise RuntimeError('d26_held_caller_unavailable')
    return getter()
