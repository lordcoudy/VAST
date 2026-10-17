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


if __name__ == '__main__':
    unittest.main()
