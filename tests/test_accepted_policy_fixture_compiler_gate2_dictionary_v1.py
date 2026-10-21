"""Ordinary authored D27 codec TEST source; no geometry admission is implied."""

import hashlib
import json
from pathlib import Path
import types


D27_WIRE_CODEC = r'''function gate2WireBudget(now,cause,end=Infinity){
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
function gate2WireDecode(wire,tag,sha,canon,guard){
const b=guard;gate2WireInput(wire);
const x=b.phase(()=>{try{return JSON.parse(wire);}catch{gate2F('shape');}});
b.phase(()=>{
if(!x||typeof x!=='object'||Array.isArray(x)||Object.keys(x).sort().join(',')!=='encoding,expanded_sha256,expanded_size_bytes,payload'||tag!=='gate2-selected-lzw-v4'&&tag!=='gate2-observed-lzw-v4'||x.encoding!==tag||typeof x.payload!=='string'||x.payload.length>12288||typeof x.expanded_sha256!=='string'||!/^[0-9a-f]{64}$/.test(x.expanded_sha256)||!Number.isSafeInteger(x.expanded_size_bytes))gate2F('shape');
});
const spell=b.phase(()=>{try{return canon(x,12288);}catch{gate2F('shape');}});
if(spell!==wire)gate2F('shape');
if(x.expanded_size_bytes<1||x.expanded_size_bytes>32768)gate2F('bound');
const text=b.phase(()=>{
const p=x.payload,pairs=p.length/2;if(!p.length||p.length%2)gate2F('token');
function rank(i){b.work();const c=p.charCodeAt(i);b.work();if(c<32||c>126||c===34||c===92)gate2F('token');return c-32-(c>34)-(c>92);}
function pair(q){const v=rank(q*2)*93+rank(q*2+1);b.work();if(v>8191)gate2F('token');return v;}
for(let q=0;q<pairs;q++){b.work();pair(q);}
if(pairs<2)gate2F('token');let ci=-1,value=0;
function bit(i){b.work();if(i<0||i>=13*pairs)gate2F('token');const q=Math.floor(i/13);b.work();if(q!==ci){value=pair(q);ci=q;}b.work();return Math.floor(value/2**(12-i%13))%2;}
let bits=0;for(let i=0;i<24;i++){b.work();bits=bits*2+bit(i);}
const size=3+Math.ceil(bits/8);if(!bits||size>9984||p.length!==2*Math.ceil(8*size/13))gate2F('token');
for(let i=24+bits;i<8*size;i++){b.work();if(bit(i))gate2F('token');}
for(let i=8*size;i<13*pairs;i++){b.work();if(bit(i))gate2F('token');}
b();const pre=new Uint16Array(8192);b();const suf=new Uint8Array(8192);b();const stk=new Uint8Array(8192);b();
let at=0,nx=95,prev=0,have=false;const out=[];
function wid(n){let w=7;while(2**w<n){b.work();w++;}b.work();return w;}
function read(n){b.work();if(at+n>bits)gate2F('token');let v=0;for(let i=0;i<n;i++){b.work();v=v*2+bit(24+at);at++;}return v;}
function expand(code){let top=0;while(code>=95){b.work();if(code>=nx||top>=8192)gate2F('token');b.work();const s=suf[code];b.work();stk[top++]=s;b.work();const old=pre[code];if(old>=code)gate2F('token');code=old;}b.work();if(code<0||code>=95||top>=8192)gate2F('token');b.work();stk[top++]=code;return top;}
while(at<bits){
 const code=read(wid(Math.min(nx+(have?1:0),8192)));b.work();
 if(!have&&code>=95||code>nx||code===nx&&(!have||nx>=8192))gate2F('token');
 const kw=code===nx,n=expand(kw?prev:code);b.work();const first=stk[n-1],length=n+(kw?1:0);
 b.work();if(out.length+length>x.expanded_size_bytes||out.length+length>32768)gate2F('expansion');
 for(let i=n-1;i>=0;i--){b.work();const c=stk[i];b.work();out.push(String.fromCharCode(c+32));}
 if(kw){b.work();out.push(String.fromCharCode(first+32));}
 if(have){b.work();if(nx>=8192)gate2F('bound');b.work();pre[nx]=prev;b.work();suf[nx]=first;nx++;}
 prev=code;have=true;
}
for(let i=0;i<out.length;i++)b.work();return out.join('');
});
if(text.length!==x.expanded_size_bytes)gate2F('binding');
const digest=b.phase(()=>sha(text));if(digest!==x.expanded_sha256)gate2F('binding');
const value=b.phase(()=>{try{return JSON.parse(text);}catch{gate2F('binding');}});
const rc=b.phase(()=>{try{return canon(value,32768);}catch{gate2F('binding');}});
if(rc!==text)gate2F('binding');return {text,value};
}
function gate2WireEncode(text,tag,sha,canon,guard){
const b=guard;
function dig(n){return String.fromCharCode(n+32+(n>=2)+(n>=59));}
if(typeof text!=='string'||text.length<1||text.length>32768||/[^\x20-\x7e]/.test(text))throw Error('selected_wire_input');
const digest=b.phase(()=>{if(tag!=='gate2-selected-lzw-v4'&&tag!=='gate2-observed-lzw-v4')gate2F('shape');const v=sha(text);if(typeof v!=='string'||!/^[0-9a-f]{64}$/.test(v))gate2F('shape');return v;});
const head=b.phase(()=>{try{return canon({encoding:tag,expanded_sha256:digest,expanded_size_bytes:text.length,payload:''},12288).length;}catch(e){if(e&&e.message==='canonical_bound')gate2F('bound');throw e;}});
function bound(bits){b.work();const n=3+Math.ceil(bits/8);if(n>9984||head+2*Math.ceil(8*n/13)>12288)gate2F('bound');}
function wid(n){let w=7;while(2**w<n){b.work();w++;}b.work();return w;}
function walk(emit){b();const map=new Map();b();let nx=95;b.work();let cur=text.charCodeAt(0)-32;
for(let i=1;i<text.length;i++){b.work();const c=text.charCodeAt(i)-32,key=cur*95+c;b.work();const hit=map.get(key);if(hit!==undefined){cur=hit;}else{emit(cur,wid(nx));b.work();if(nx>=8192)gate2F('bound');b.work();map.set(key,nx++);cur=c;}}
emit(cur,wid(nx));return nx;}
let bits=0,ct=0,cn=0;
b.phase(()=>{bound(0);cn=walk((code,w)=>{b.work();const n=bits+w;bound(n);for(let i=0;i<w;i++)b.work();bits=n;ct++;});});
const size=3+Math.ceil(bits/8),length=2*Math.ceil(8*size/13),chars=b.phase(()=>{bound(bits);b();const a=new Array(length);b();return a;});
let at=0,pend=0,g=0,f=0,wr=0;
b.phase(()=>{
function feed(v,n){for(let i=n-1;i>=0;i--){b.work();g=g*2+Math.floor(v/2**i)%2;pend++;at++;if(pend===13){b.work();if(f+2>length)gate2F('token');b.work();chars[f++]=dig(Math.floor(g/93));b.work();chars[f++]=dig(g%93);pend=0;g=0;}}}
feed(bits,24);const wn=walk((code,w)=>{b.work();wr++;if(at+w>24+bits)gate2F('token');feed(code,w);});
if(at!==24+bits||wr!==ct||wn!==cn)gate2F('token');
while(at<8*size)feed(0,1);if(at!==8*size)gate2F('token');while(pend)feed(0,1);
if(at!==13*length/2||f!==length||g!==0)gate2F('token');
});
const payload=b.phase(()=>{for(let i=0;i<chars.length;i++)b.work();return chars.join('');});
return b.phase(()=>{bound(bits);try{return canon({encoding:tag,expanded_sha256:digest,expanded_size_bytes:text.length,payload},12288);}catch(e){if(e&&e.message==='canonical_bound')gate2F('bound');throw e;}});
}
'''

D27_CODEC_TEST_DRIVER = r'''const fs=require('node:fs'),crypto=require('node:crypto');
const R={schema_version:1,case:null,node_version:process.versions.node,completed:false,cause:null,checks:[],measurements:[]};
const S='gate2-selected-lzw-v4',O='gate2-observed-lzw-v4';
function sha(s){return crypto.createHash('sha256').update(s,'ascii').digest('hex');}
function canon(v,cap){return gate2Canonical(v,cap);}
function check(id,ok){R.checks.push({id,ok:!!ok});if(!ok)throw Error('d27_driver_assertion');}
function want(id,fn,expected){let actual=null;try{fn();}catch(e){actual=e&&e.message;}check(id,actual===expected);}
function budget(){return gate2WireBudget(()=>0,'selected_wire_deadline');}
function decode(w,tag=S,b=budget()){return gate2WireDecode(w,tag,sha,canon,b);}
function encode(t,tag=S,b=budget()){return gate2WireEncode(t,tag,sha,canon,b);}
function width(n){for(let w=7;w<=13;w++)if(n<=2**w)return w;throw Error('d27_driver_assertion');}
function digits(v){return String.fromCharCode(32+v+(v>=2)+(v>=59));}
function packed(bits,declared=bits.length,byteFlip=false,groupFlip=false){
const raw=[];for(let i=23;i>=0;i--)raw.push(Math.floor(declared/2**i)%2);
raw.push(...bits);const byteStart=raw.length;while(raw.length%8)raw.push(0);const byteEnd=raw.length;
if(byteFlip){if(byteStart===byteEnd)throw Error('d27_driver_assertion');raw[byteStart]=1;}
const groupStart=raw.length;while(raw.length%13)raw.push(0);
if(groupFlip){if(groupStart===raw.length)throw Error('d27_driver_assertion');raw[groupStart]=1;}
let s='';for(let i=0;i<raw.length;i+=13){let v=0;for(let j=0;j<13;j++)v=v*2+raw[i+j];s+=digits(Math.floor(v/93))+digits(v%93);}
return {payload:s,bytePad:byteEnd-byteStart,groupPad:raw.length-groupStart};
}
function codeBits(codes){const a=[];for(let i=0;i<codes.length;i++){const w=width(95+i);for(let j=w-1;j>=0;j--)a.push(Math.floor(codes[i]/2**j)%2);}return a;}
function literalBits(text){return codeBits(Array.from(text,c=>c.charCodeAt(0)-32));}
function envelope(text,bits=literalBits(text),size=text.length,digest=sha(text),p=null){
return canon({encoding:S,expanded_sha256:digest,expanded_size_bytes:size,payload:p===null?packed(bits).payload:p},12288);
}
function oracle(wire){
const x=JSON.parse(wire),p=x.payload,raw=[];
function rank(c){const n=c.charCodeAt(0);return n-32-(n>34)-(n>92);}
for(let i=0;i<p.length;i+=2){const v=rank(p[i])*93+rank(p[i+1]);for(let j=12;j>=0;j--)raw.push(Math.floor(v/2**j)%2);}
let t=0;for(let i=0;i<24;i++)t=t*2+raw[i];
const d=Array.from({length:95},(_,i)=>String.fromCharCode(i+32)),widths=new Set();
let at=24,out='',prev=null;
while(at<24+t){
const n=d.length+(prev===null?0:1),w=width(n);widths.add(w);let code=0;
for(let i=0;i<w;i++)code=code*2+raw[at++];
const word=code<d.length?d[code]:code===d.length&&prev!==null?prev+prev[0]:null;
if(word===null||at>24+t)throw Error('d27_driver_assertion');
out+=word;if(prev!==null)d.push(prev+word[0]);prev=word;
}
return {text:out,widths};
}
function changed(w,p){return canon(Object.assign(JSON.parse(w),p),32768);}
function same(id,text,wire=envelope(text)){check(id,decode(wire).text===text);}
function vectors(){
const values=[{message:'D27 dictionary round trip'},{nested:[true,null,7,{a:'\\~"'}]},'', 'AAA',String.fromCharCode(...Array.from({length:95},(_,i)=>i+32)),{unicode:'\u00e9\u2028'}];
for(let i=0;i<values.length;i++)for(const [name,tag] of [['selected',S],['observed',O]]){
const text=canon(values[i],32768),wire=encode(text,tag),r=decode(wire,tag);
check(name+'_round_trip_'+i,r.text===text&&canon(r.value,32768)===text);
}
const wide=canon('A'.repeat(4100),32768);same('literal_widths_7_through_13',wide);
for(const [oldN,newN] of [[128,129],[256,257],[512,513],[1024,1025],[2048,2049],[4096,4097]])
check('width_'+oldN+'_'+newN,width(oldN)+1===width(newN)&&newN-95<wide.length);
let ds='';for(let i=0;i<93;i++){ds+=digits(i);for(let j=i+1;j<93;j++)ds+=digits(i)+digits(j);}
for(const n of [34,35,162,163,418,419,930,931,1954,1955,4002,4003]){
const text=canon(ds.slice(0,n-2),32768),pairs=new Set();
for(let i=1;i<text.length;i++)pairs.add(text.slice(i-1,i+1));
check('unique_literal_pairs_'+n,pairs.size===text.length-1);
same('eof_at_code_count_'+n,text);
check('encoder_exact_literal_packet_'+n,encode(text)===envelope(text));
}
same('kwkwk_legal_previous_plus_first','"AAA"',envelope('"AAA"',codeBits([2,33,96,2])));
const max=canon('A'.repeat(32766),32768);same('original_exact_32768',max,encode(max));
check('fresh_dictionaries_deterministic',encode(wide)===encode(wide));
let state=20260323,s='';for(let i=0;i<5500;i++){state=(Math.imul(state,1664525)+1013904223)>>>0;s+=String.fromCharCode(32+state%95);}
const alphabet=canon(s,32768),packet=packed(literalBits(alphabet)),seen=new Set();
for(let i=1;i<packet.payload.length;i+=2)seen.add(packet.payload[i]);
same('all_low_radix_digits_positive_packet',alphabet,envelope(alphabet,[],alphabet.length,sha(alphabet),packet.payload));
for(let i=0;i<93;i++)check('radix_low_digit_'+i,seen.has(digits(i)));
const q=oracle(encode(alphabet));
check('encoder_independent_phrase_oracle',q.text===alphabet);
check('encoder_actual_widths_7_through_13',[7,8,9,10,11,12,13].every(w=>q.widths.has(w)));
const bs=new Set(),gs=new Set();
for(let n=0;n<512&&(bs.size<8||gs.size<13);n++){
const text=canon('B'.repeat(n),32768),bits=literalBits(text),p=packed(bits);
if(!bs.has(p.bytePad)){bs.add(p.bytePad);same('byte_pad_'+p.bytePad,text);if(p.bytePad)want('byte_pad_nonzero_'+p.bytePad,()=>decode(envelope(text,[],text.length,sha(text),packed(bits,bits.length,true).payload)),'selected_wire_token');}
if(!gs.has(p.groupPad)){gs.add(p.groupPad);same('group_pad_'+p.groupPad,text);if(p.groupPad)want('group_pad_nonzero_'+p.groupPad,()=>decode(envelope(text,[],text.length,sha(text),packed(bits,bits.length,false,true).payload)),'selected_wire_token');}
}
check('all_byte_padding_extents',bs.size===8);check('all_group_padding_extents',gs.size===13);
const large=canon('C'.repeat(6500),32768),bits=literalBits(large),n=3+Math.ceil(bits.length/8),wire=envelope(large,bits);
check('positive_virtual_N_above_9216',n>9216&&n<=9984&&wire.length<=12288);same('decode_virtual_N_above_9216',large,wire);
}
function malformed(){
const text='"A"',valid=envelope(text),bad=changed(valid,{payload:'!'});
for(const [id,value] of [['empty',''],['type',null],['control','\n'],['wire_limit',' '.repeat(12289)]])want('input_'+id,()=>decode(value),'selected_wire_input');
for(const [id,value] of [['parse','{'],['array','[]'],['extra',changed(valid,{extra:1})],['tag',changed(valid,{encoding:O})],['hash',changed(valid,{expanded_sha256:'A'.repeat(64)})],['fraction',changed(valid,{expanded_size_bytes:1.5})],['boolean',changed(valid,{expanded_size_bytes:true})],['unsafe',valid.replace('"expanded_size_bytes":3','"expanded_size_bytes":9007199254740992')],['spelling',valid.replace('"expanded_size_bytes":3','"expanded_size_bytes":3e0')]])want('shape_'+id,()=>decode(value),'selected_wire_shape');
for(const n of [0,-1,32769])want('declared_bound_'+(n+1),()=>decode(changed(bad,{expanded_size_bytes:n})),'selected_wire_bound');
for(const [id,p] of [['empty',''],['odd','!'],['short2','  '],['short4','    '],['quote','" '],['backslash','\\ '],['tab','\t '],['newline','\n '],['del',String.fromCharCode(127)+' '],['unicode','\u00e9 '],['suffix',JSON.parse(valid).payload+'  ']])
want('transport_'+id,()=>decode(changed(valid,{payload:p})),'selected_wire_token');
const cc=String.prototype.charCodeAt;let pp=null,reads=0,rd=false;
String.prototype.charCodeAt=function(i){if(rd&&String(this)===pp)reads++;return cc.call(this,i);};
try{for(let v=8192;v<8649;v++){
const p=JSON.parse(valid).payload,fbd=digits(Math.floor(v/93))+digits(v%93);
pp=p.slice(0,-2)+fbd;reads=0;
let caught=null,n=0;const b=budget(),phase=b.phase;b.phase=fn=>phase(()=>{n++;rd=n===4;try{return fn();}finally{rd=false;}});try{decode(changed(valid,{payload:pp}),S,b);}catch(e){caught=e&&e.message;}
if(caught!=='selected_wire_token'||reads!==pp.length)throw Error('d27_driver_assertion');
}}finally{String.prototype.charCodeAt=cc;}
check('all_457_forbidden_pairs_before_tokens',true);
const cases=[
['first_must_be_literal',codeBits([95])],['first_forward',codeBits([127])],
['forward_after_literal',codeBits([2,97])],['partial_first',[0,0,0,0,0,0]],
['partial_final',codeBits([2]).concat([0])],['invalid_next_before_expansion',codeBits([2,127])]
];
for(const [id,bits] of cases)want(id,()=>decode(envelope(text,bits,1)),'selected_wire_token');
want('valid_next_expansion',()=>decode(changed(valid,{expanded_size_bytes:2})),'selected_wire_expansion');
want('short_complete_binding',()=>decode(changed(valid,{expanded_size_bytes:4})),'selected_wire_binding');
want('digest_binding',()=>decode(changed(valid,{expanded_sha256:'0'.repeat(64)})),'selected_wire_binding');
want('recovered_json_binding',()=>decode(envelope('A')),'selected_wire_binding');
want('recovered_spelling_binding',()=>decode(envelope('1 ')),'selected_wire_binding');
want('unsafe_recovered_integer_binding',()=>decode(envelope('9007199254740992')),'selected_wire_binding');
same('bmp_astral_codepoint_key_order','{"\\ue000":1,"\\ud800\\udc00":2}',encode('{"\\ue000":1,"\\ud800\\udc00":2}'));
want('zero_T',()=>decode(changed(valid,{payload:packed([],0).payload})),'selected_wire_token');
want('impossible_header_extent',()=>decode(changed(valid,{payload:packed([0],16777215).payload})),'selected_wire_token');
want('swapped_selected_tag',()=>decode(encode(text,O)),'selected_wire_shape');
const ec=[2,33,33];for(let i=0;i<6633;i++)ec.push(i<3363?96:33);ec.push(2);
const et=canon('A'.repeat(9998),32768),exact=envelope(et,codeBits(ec));
check('wire_exact_12288_extent',exact.length===12288);same('wire_exact_12288_positive',et,exact);
want('wire_12289_input',()=>decode(exact+' '),'selected_wire_input');
want('encoder_original_32769_input',()=>encode('A'.repeat(32769)),'selected_wire_input');
}
function overflow(){
const kw=envelope('"AAAAAAAA"',codeBits([2,33,96,97,96,2]));
let work=0,last=-1,cg=true,alloc=[];
const g=()=>0;g.work=()=>{work++;};g.phase=fn=>{g();const v=fn();g();return v;};
const U8=globalThis.Uint8Array,U16=globalThis.Uint16Array;
function wrap(C,kind,n){alloc.push([kind,n]);return new Proxy(new C(n),{
get(t,k){if(/^[0-9]+$/.test(String(k))){if(work<=last)cg=false;last=work;}return Reflect.get(t,k,t);},
set(t,k,v){if(/^[0-9]+$/.test(String(k))){if(work<=last)cg=false;last=work;}return Reflect.set(t,k,v,t);}
});}
try{
globalThis.Uint8Array=function(n){return wrap(U8,'u8',n);};
globalThis.Uint16Array=function(n){return wrap(U16,'u16',n);};
check('observed_kwkwk_result',decode(kw,S,g).text==='"AAAAAAAA"');
}finally{globalThis.Uint8Array=U8;globalThis.Uint16Array=U16;}
check('each_dictionary_stack_access_separately_charged',cg);
check('exact_three_dictionary_arrays',JSON.stringify(alloc)===JSON.stringify([['u16',8192],['u8',8192],['u8',8192]]));
let calls=0;const b=gate2WireBudget(()=>{calls++;return 0;},'selected_wire_deadline');
for(let i=0;i<256;i++)b.work();check('at_most_256_work_between_samples',calls===1);b.work();check('sample_before_257th_work',calls===2);
for(const [id,now,end] of [['nonfinite',()=>NaN,Infinity],['expiry',()=>5000,5000],['invalid_end',()=>0,NaN]])
want('clock_'+id,()=>decode(kw,S,gate2WireBudget(now,'selected_wire_deadline',end)),'selected_wire_deadline');
let tick=0;want('clock_regression',()=>{const b=gate2WireBudget(()=>tick++===0?1:0,'selected_wire_deadline');return decode(kw,S,b);},'selected_wire_deadline');
tick=0;want('post_throw_clock_precedence',()=>{const b=gate2WireBudget(()=>tick++===0?0:5000,'selected_wire_deadline');return decode('{',S,b);},'selected_wire_deadline');
want('primitive_before_clock',()=>decode('',S,gate2WireBudget(()=>NaN,'selected_wire_deadline')),'selected_wire_input');
for(const kind of ['encode','decode']){
let clock=0;const b=gate2WireBudget(()=>clock,'selected_wire_deadline'),t='"A"';
if(kind==='encode')encode(t,S,b);else decode(envelope(t),S,b);
clock=5000;
want('shared_selected_observed_'+kind,()=>kind==='encode'?encode(t,O,b):decode(changed(envelope(t),{encoding:O}),O,b),'selected_wire_deadline');
}
let tv=0,A=globalThis.Array,M=globalThis.Map,cp=0;
function CA(...args){tv++;return new A(...args);}CA.isArray=A.isArray;CA.prototype=A.prototype;
class CM extends M{set(k,v){cp++;return super.set(k,v);}}
let random=1,s='';for(let i=0;i<32768;i++){random=(Math.imul(random,1103515245)+12345)>>>0;s+=String.fromCharCode(32+random%95);}
try{globalThis.Array=CA;globalThis.Map=CM;want('wire_bound_before_capacity',()=>encode(s),'selected_wire_bound');}
finally{globalThis.Array=A;globalThis.Map=M;}
check('zero_premature_payload_vectors',tv===0);check('wire_refusal_before_dictionary_saturation',cp<8097);
const ch=String.prototype.charCodeAt;
for(const [label,text] of [['zero','"A"'],['nonzero',canon('D'.repeat(400),32768)]]){
const wire=envelope(text),p=JSON.parse(wire).payload,reads=[],ws=[];let work=0,phase=0,rd=false;
const trace=()=>0;trace.work=()=>{work++;};trace.phase=fn=>{phase++;rd=phase===4;try{return fn();}finally{rd=false;}};
String.prototype.charCodeAt=function(i){if(rd&&String(this)===p){reads.push(i);ws.push(work);}return ch.call(this,i);};
try{check('cache_decode_'+label,decode(wire,S,trace).text===text);}finally{String.prototype.charCodeAt=ch;}
const scan=Array.from({length:p.length},(_,i)=>i);
check('cache_every_actual_read_has_fresh_work_'+label,ws.every((v,i)=>i===0||v>ws[i-1]));
const h=(p.charCodeAt(0)-32-(p.charCodeAt(0)>34)-(p.charCodeAt(0)>92))*93+p.charCodeAt(1)-32-(p.charCodeAt(1)>34)-(p.charCodeAt(1)>92);
check('cache_header_value_'+label,label==='zero'?h===0:h>0);
check('cache_complete_scan_'+label,reads.slice(0,p.length).join(',')===scan.join(','));
check('cache_first_actual_pair0_load_'+label,reads[p.length]===0&&reads[p.length+1]===1);
check('cache_true_header_hits_'+label,reads[p.length+2]===2&&reads[p.length+3]===3);
check('cache_backward_body_reload_'+label,reads.slice(p.length+4).some((x,i,a)=>i>0&&x<a[i-1]));
}
const encoder=34*7+128*8+256*9+512*10+1024*11+2048*12+4095*13,decoder=encoder+13;
check('saturation_impossibility_arithmetic',encoder===97761&&decoder===97774&&79848<encoder);
}
try{
const input=JSON.parse(fs.readFileSync(0,'utf8'));
if(!input||Object.keys(input).sort().join(',')!=='case,data'||!['codec_vectors','codec_malformed','codec_overflow'].includes(input.case)||!input.data||typeof input.data!=='object'||Array.isArray(input.data)||Object.keys(input.data).length)throw Error('d27_driver_input');
R.case=input.case;
if(process.versions.node!=='25.2.1')throw Error('d27_node_version');
if(typeof gate2WireEncode!=='function'||typeof gate2WireDecode!=='function'||typeof gate2WireBudget!=='function')throw Error('d27_codec_absent');
if(input.case==='codec_vectors')vectors();else if(input.case==='codec_malformed')malformed();else overflow();
R.completed=true;
}catch(error){const allowed=['d27_codec_absent','d27_driver_assertion','d27_driver_input','d27_driver_error','d27_node_version'];R.cause=allowed.includes(error&&error.message)?error.message:'d27_driver_error';}
let raw;try{raw=canon(R,32767);}catch{process.exit(1);}
process.stdout.write(raw+'\n');
'''


def d27_node_driver_v1():
    """Return one fixed ordinary codec TEST driver; DATA cannot choose source."""
    return D27_WIRE_CODEC+'\n'+ROOT_ENCODER+'\n'+D27_CODEC_TEST_DRIVER


# Fixed ordinary authored closure port; no old TEST module is executed.
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

NODE_WRITER_HEAD=WRITER_READY+'try:\n'+_indent_python(WRITER_HEAD)

NODE_WRITER_TAIL=_indent_python(WRITER_TAIL)+'except SystemExit:raise\nexcept BaseException:raise SystemExit(1)\n'
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
def _d27_finalizer_base_v1(initial, deferred, codec, main, caller):
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

def _d27_root_wire_base_v1(codec):
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
def _d27_caller_module_v1():
    """Resolve only the held new caller and its fixed DATA compression getter."""
    import sys
    names=('tests.test_accepted_policy_fixture_compiler_gate2_dictionary_caller_v1',
           'test_accepted_policy_fixture_compiler_gate2_dictionary_caller_v1')
    expected=Path(__file__).with_name('test_accepted_policy_fixture_compiler_gate2_dictionary_caller_v1.py').absolute()
    present=[(name,sys.modules[name]) for name in names if name in sys.modules]
    if not present:raise RuntimeError('d27_held_caller_unavailable')
    selected_name,selected=present[0]
    for name,module in present:
        if type(module) is not types.ModuleType:raise RuntimeError('d27_held_caller_unavailable')
        ns=vars(module)
        if (ns.get('__name__')!=name and module is not selected or type(ns.get('__file__')) is not str or Path(ns['__file__']).absolute()!=expected):
            raise RuntimeError('d27_held_caller_unavailable')
    ns=vars(selected);getter=ns.get('d27_compress_data_v1')
    if (ns.get('__name__')!=selected_name or type(getter) is not types.FunctionType
            or getter.__name__!='d27_compress_data_v1' or getter.__module__!=selected_name
            or getter.__globals__ is not ns or Path(getter.__code__.co_filename).absolute()!=expected):
        raise RuntimeError('d27_held_caller_unavailable')
    return selected

class D27PhaseConstructionError(RuntimeError):
    def __init__(self,cause,metadata):
        super().__init__(cause)
        self.metadata=metadata
        self.capture=metadata


def d27_phase_initial_v1(deadline):
    """Build one unpooled phase source in RAM; no geometry or behavior acceptance."""
    import base64
    import math
    import time
    import zlib

    compression = None

    def refuse(cause):
        raise D27PhaseConstructionError(cause,compression)

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
        caller = _d27_caller_module_v1()
        packed, compression = caller.d27_compress_data_v1(raw, end)
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
def d27_geometry_driver_v1():
    import sys
    import types
    from pathlib import Path
    names = ('tests.test_accepted_policy_fixture_compiler_gate2_dictionary_caller_v1',
             'test_accepted_policy_fixture_compiler_gate2_dictionary_caller_v1')
    expected = Path(__file__).with_name('test_accepted_policy_fixture_compiler_gate2_dictionary_caller_v1.py').absolute()
    present = [(name, sys.modules[name]) for name in names if name in sys.modules]
    if not present:
        raise RuntimeError('d27_held_caller_unavailable')
    selected_name, selected = present[0]
    for name, module in present:
        if type(module) is not types.ModuleType:
            raise RuntimeError('d27_held_caller_unavailable')
        namespace = vars(module)
        if (namespace.get('__name__') != name and module is not selected
                or type(namespace.get('__file__')) is not str
                or Path(namespace['__file__']).absolute() != expected):
            raise RuntimeError('d27_held_caller_unavailable')
    namespace = vars(selected)
    getter = namespace.get('_d27_geometry_program_v1')
    if (namespace.get('__name__') != selected_name or type(getter) is not types.FunctionType
            or getter.__name__ != '_d27_geometry_program_v1' or getter.__module__ != selected_name
            or getter.__globals__ is not namespace or Path(getter.__code__.co_filename).absolute() != expected):
        raise RuntimeError('d27_held_caller_unavailable')
    return getter()

D27_CODEC_SOURCE_PINS = ((6779, '071da76e6b0c03ef7d01f82fb552f25807720787e1d863543934416165ddbeee'), (4397, '6d59e7482bcf92b620ccf758152bdfb76dddf99738329d47250171b49712a657'), (2382, '479e56d80c86221b3630a014439c46073685689b0d435407aea87fd4071bcaae'))

D27_GEOMETRY_MODEL = 'function d23Geometry(d,report){\n const z=require(\'node:zlib\'),hash=b=>require(\'node:crypto\').createHash(\'sha256\').update(b).digest(\'hex\'),canon=v=>gate2Canonical(v,262144),ascii=s=>typeof s===\'string\'&&!/[^\\x00-\\x7f]/.test(s);\n const held=d.held.map(s=>Buffer.from(s,\'base64\'));\n function bound(id,ok){report.checks.push({id,ok});}\n function keep(id,text,cap){measure(id,text);bound(id+\'_bound\',text.length<=cap);}\n function provider(text,n){return {content:[{type:\'text\',text}],isError:false,_meta:{actual_ordinal:n,resource:{uri:\'controlled:retained\'}},resource:{mimeType:\'application/json\'}};}\n const start=Number.MAX_SAFE_INTEGER-1500000,work=start+140000,end=start+150000,clock=[start,work,end],poll=\'await gate2Resume.poll();\',ready=\'1755772592209100\\n\',ack_ms=149000;\n const setupInput=Buffer.concat([Buffer.from(canon({remaining_ms:ack_ms,selected_base64:\'\',sha256:hash(\'\'),size_bytes:0})+\'\\n\'),...held]);\n function snapshot(id,kind,raw,input,changes={},n=start+130000,ownClock=null,ack=ack_ms,pid=4294967295){\n  let pieces=[],pipes=raw.map((b,i)=>{\n   let encoding=b.every(x=>x<128)?\'ascii\':\'base64\',v=b.toString(encoding),compressed=z.brotliCompressSync(b,{maxOutputLength:4096}).toString(\'base64\');\n   check(id+\'_pipe\'+i+\'_inverse\',z.brotliDecompressSync(Buffer.from(compressed,\'base64\'),{maxOutputLength:2113}).equals(b));\n   if(JSON.stringify([\'br64\',compressed.length,compressed]).length<JSON.stringify([encoding,v.length,v]).length){encoding=\'br64\';v=compressed;}\n   pieces.push(v);let p={bytes:b.length,sha256:hash(b),eof:true,closed:true,error:false,encoding,chars:v.length,remainder_unknown:false};\n   if(changes.partial&&i===0)Object.assign(p,{eof:false,closed:false,error:true,remainder_unknown:true});\n   return d.pipe_fields.map(k=>p[k]);\n  });\n  let f={pid,returncode:0,signal:null,exited:true,closed:true,pipes,causes:[],unknown_closure:false,completed:true,terminal_observed_ms:n,physical_acceptance:false,clock:ownClock,ack_ms:ack,stdin_finished:true,stdin_closed:true,stdin_bytes:input.length,stdin_sha256:hash(input),stdin_extent_unknown:false,source_facts:null};\n  if(changes.failure)Object.assign(f,{returncode:1,completed:false});\n  if(changes.partial)Object.assign(f,{closed:false,causes:[\'pipe_error\'],unknown_closure:true,completed:false});\n  if(changes.unknown)Object.assign(f,{returncode:null,exited:false,unknown_closure:true,completed:false});\n  if(raw[1].length)f.completed=false;\n  return JSON.stringify([kind,...d.fields.map(k=>f[k])])+\'\\n\'+pieces.join(\'\');\n }\n function writer(id,selected,remaining,cap,formsCap,ownClock,n){\n  const selectedSHA=hash(selected),header=canon({remaining_ms:remaining,selected_base64:Buffer.from(selected).toString(\'base64\'),sha256:selectedSHA,size_bytes:selected.length})+\'\\n\',input=Buffer.concat([Buffer.from(header),...held]),q=Math.ceil(selected.length/4096)*4096,forms=Math.max(cap,q)+q+8192;\n  const facts={stdin_eof:true,stdin_extent_unknown:false,source_bytes:held.map(b=>b.length),source_sha256:held.map(hash),open_completed:true,written_bytes:selected.length,extent_unknown:false,fsync_completed:true,close_completed:true,allocated_bytes:cap,completed:true,sha256:selectedSHA,unknown_closure:false};\n  let receipt=canon({completed:true,external_terminal_required:true,size_bytes:selected.length,sha256:selectedSHA,write_facts:facts,deadline_ns:0,all_forms_quote_bytes:forms})+\'\\n\';\n  check(id+\'_uint64\',receipt.split(\'"deadline_ns":0\').length===2);receipt=receipt.replace(\'"deadline_ns":0\',\'"deadline_ns":18446744073709551615\');\n  const raw=Buffer.from(\'{"ready":true,"schema_version":1}\\n\'+receipt);\n  return {header,input,raw,text:snapshot(id+\'_writer\',2,[raw,Buffer.alloc(0)],input,{},n,ownClock,remaining,4294967294),forms,formsOK:forms<=formsCap,selectedSHA};\n }\n const executor=d.executor_prefix+JSON.stringify(d.initial)+\',\'+JSON.stringify(d.finalizer)+d.executor_suffix;\n const marker=\'const g2factory=function(gate2Resume,nodeRepl){\\n\',at=d.finalizer.indexOf(marker),factorySize=13073;\n check(\'source_bindings\',held.length===2&&ascii(executor)&&executor.length===d.executor_pin.size_bytes&&hash(executor)===d.executor_pin.sha256&&at>=0&&d.finalizer.indexOf(marker,at+1)<0&&hash(d.finalizer.slice(at+marker.length,at+marker.length+factorySize))===d.factory_sha256&&d.finalizer.startsWith(\'\\n};\',at+marker.length+factorySize));\n keep(\'initial_source\',d.initial,262144);keep(\'finalizer_source\',d.finalizer,262144);keep(\'executor_source\',executor,262144);\n function fullChain(id,root){\n  let c=JSON.parse(canon(d.chain)),a=c[0].call,b=c[0].result,w=c[1].call,t=c[1].result;\n  let valid=c.length===2&&a.input===\'\'&&t.output.length===2&&t.output[1].text===\'\'&&a.call_id!==w.call_id&&b.call_id===a.call_id&&t.call_id===w.call_id;\n  const wrapper=/^Script (completed|running with cell ID ([A-Za-z0-9_-]{1,64}))\\nWall time [0-9]{1,12}(?:\\.[0-9]{1,9})? seconds\\nOutput:\\n$/,first=wrapper.exec(b.output),last=wrapper.exec(t.output[0].text);\n  valid=valid&&first&&first[2]&&last&&last[1]===\'completed\'&&b.output.length<=256&&t.output[0].text.length<=256;\n  const wa=JSON.parse(w.arguments);\n  valid=valid&&canon(wa)===w.arguments&&wa.cell_id===first[2]&&wa.max_tokens===100000&&wa.yield_time_ms>=1&&wa.yield_time_ms<=60000;\n  a.input=executor;t.output[1].text=root;\n  check(id+\'_chain_join\',valid&&t.output.slice(1).map(r=>r.text).join(\'\')===root&&typeof b.output===\'string\');\n  return {text:canon(c),reference:\'functions.exec/\'+first[2]};\n }\n check(\'six_setup_forms\',d.forms.length===6&&d.forms.filter(x=>x.success===true).length===1);\n let upstream=null;\n for(const form of d.forms){\n  const id=form.id;check(id+\'_setup\',ascii(form.stdout)&&ascii(form.stderr)&&(!form.success||!form.failure&&!form.partial&&!form.unknown&&!form.stderr));\n  const raw=[Buffer.from(form.stdout),Buffer.from(form.stderr),Buffer.from(ready)];\n  check(id+\'_provider_pipes\',raw[0].length<=2048&&raw[1].length<=2048&&raw[2].length<=32);\n  const terminal=snapshot(id,1,raw,setupInput,form),codes=[d.initial,...Array(5).fill(poll)],frames=codes.map((code,i)=>provider(i===5?terminal:JSON.stringify(i===0?[0,...clock,4294967295,null]:[0,4294967295,null]),i+1));\n  let selected,observed;\n  try{\n   const guard=budget(\'selected_wire_root_deadline\');\n   function original(value){try{return guard.phase(()=>gate2Canonical(value,32768));}catch(e){if(e&&e.message===\'canonical_bound\')throw Error(\'selected_wire_input\');throw e;}}\n   const selectedOriginal=original({call:{tool:\'mcp__node_repl__js\',timeout_ms:32000,codes},frames});\n   keep(id+\'_selected_original\',selectedOriginal,32768);selected=encoded(selectedOriginal,\'gate2-selected-lzw-v4\',guard);\n   const observedOriginal=original({calls:codes.map(code=>({code,timeout_ms:32000})),frames});\n   keep(id+\'_observed_original\',observedOriginal,32768);observed=encoded(observedOriginal,\'gate2-observed-lzw-v4\',guard);\n   keep(id+\'_selected_wire\',selected,12288);keep(id+\'_observed_wire\',observed,12288);\n   const receive=budget(\'selected_wire_receive_deadline\');check(id+\'_full_roundtrip\',decoded(selected,\'gate2-selected-lzw-v4\',receive).text===selectedOriginal&&decoded(observed,\'gate2-observed-lzw-v4\',receive).text===observedOriginal);\n  }catch(e){bound(id+\'_wire_geometry\',false);measure(id+\'_wire_refusal\',String(e.message));continue;}\n  const w=writer(id,selected,19000,12288,32768,clock,start+131000);\n  keep(id+\'_ack\',w.header,24576);keep(id+\'_writer_stdout\',w.raw.toString(\'ascii\'),2112);\n  bound(id+\'_writer_input_bound\',w.input.length<=90112);bound(id+\'_forms_bound\',w.formsOK);\n  const context=form.success?[\'vast.gate2.external-delivery.v1\',d.commit,32768,d.packet_sha256,w.selectedSHA,hash(d.initial),d.factory_sha256]:null,verification=JSON.stringify([3,start+132000,end,form.success,true,w.selectedSHA,context]);\n  const record={completed:form.success,setup_success:form.success,retention_complete:true,physical_acceptance:false,output_profile:{max_output_tokens:100000,max_record_bytes:65536},setup:{observed,selected},writer_call:{code:d.finalizer+\'\\nawait gate2Resume.finish(\'+JSON.stringify(selected)+\');\',timeout_ms:11000},writer:provider(w.text,7),verification_call:{code:\'gate2Resume.verifyReturn(\'+JSON.stringify(w.text)+\');\',timeout_ms:1000},verification:provider(verification,8),context,selected_sha256:w.selectedSHA};\n  const root=canon(record)+\'\\n\',chain=fullChain(id,root);keep(id+\'_root\',root,65536);keep(id+\'_chain\',chain.text,262144);\n  if(form.success&&root.length<=65536&&chain.text.length<=262144&&w.raw.length<=2112&&w.input.length<=90112&&w.formsOK){\n   const receipt={version:1,context_sha256:hash(canon(context)),record_size_bytes:root.length,record_sha256:hash(root),executor_call_sha256:hash(chain.text),max_output_tokens:100000,terminal:\'complete_untruncated\',tool_reference:chain.reference},receiptSHA=hash(canon(receipt));\n   const body=JSON.parse(canon(d.approval_template));check(\'approval_slots\',Object.values(body).filter(v=>v===null).length===3&&[\'receipt_sha256\',\'context_sha256\',\'selected_sha256\'].every(k=>body[k]===null));Object.assign(body,{receipt_sha256:receiptSHA,context_sha256:receipt.context_sha256,selected_sha256:w.selectedSHA});\n   const external={receipt,approval:{reference:d.approval_reference,body_sha256:hash(canon(body)+\'\\n\'),receipt_sha256:receiptSHA}};\n   upstream={pins:[w.selectedSHA,hash(d.initial),d.factory_sha256],external,externalSHA:hash(canon(external))};\n  }\n }\n check(\'six_later_forms\',d.later.length===6&&new Set(d.later.map(x=>x.stage+\':\'+x.failure)).size===6);\n bound(\'later_measured_upstream\',!!upstream);if(!upstream)return;\n for(const form of d.later){\n  let stage=form.stage,id=form.id,args=form.args,duration=stage===\'D\'?10000:150000;\n  check(id+\'_later\',[\'C1\',\'C6\',\'D\'].includes(stage)&&form.duration_ms===duration&&args.length===4&&args[0]===d.commit&&args[1]===\'32768\'&&args[2]===d.packet_sha256&&ascii(form.native_input));\n  const native=[Buffer.from(form.stdout),Buffer.from(form.stderr)],input=Buffer.from(form.native_input),stageStart=start+(stage===\'D\'?1200000:Number(stage.slice(1))*160000),stageEnd=stageStart+duration;\n  check(id+\'_pipe_limits\',native[0].length<=2048&&native[1].length<=768&&native[0].length+native[1].length<=4096);\n  const external=stage===\'C1\'?upstream.external:upstream.externalSHA,begin=\'await gate2Resume.cd.begin(\'+[stage,args,...upstream.pins,external].map(canon).join(\',\')+\');\',next=\'await gate2Resume.cd.poll(1);\';\n  const text=snapshot(id,2,native,input,{failure:form.failure},stageEnd-3000,[stageStart,stageEnd],null),codes=[begin,...Array(5).fill(next)],frames=codes.map((code,i)=>provider(i===5?text:JSON.stringify([0,stage,4294967295,null]),i+1));\n  const selected=canon({call:{tool:\'mcp__node_repl__js\',timeout_ms:32000,codes},frames});keep(id+\'_selected\',selected,4096);keep(id+\'_native_input\',form.native_input,32768);\n  if(selected.length>4096)continue;\n  const w=writer(id,selected,2000,4096,16384,[stageStart,stageEnd],stageEnd-2000);keep(id+\'_ack\',w.header,16384);keep(id+\'_writer_stdout\',w.raw.toString(\'ascii\'),2112);\n  bound(id+\'_writer_forms_bound\',w.formsOK);bound(id+\'_writer_input_bound\',w.input.length<=81920);\n }\n}\n'

D27_GEOMETRY_STDIO = "'use strict';\nlet chunks=[],inputBytes=0,failed=false;\nconst report={schema_version:1,case:'geometry',node_version:process.versions.node,completed:false,cause:null,checks:[],measurements:[]};\nfunction check(id,ok){report.checks.push({id,ok:!!ok});if(!ok)throw Error('d27_driver_assertion');}\nfunction measure(id,text){if(typeof text!=='string'||/[^\\x00-\\x7f]/.test(text)||text.length>262144)throw Error('d27_driver_assertion');report.measurements.push({id,size_bytes:text.length,sha256:gate2SHA256(text)});}\nfunction budget(cause='selected_wire_deadline',now=()=>performance.now(),end=Infinity){return gate2WireBudget(now,cause,end);}\nfunction decoded(text,tag='gate2-selected-lzw-v4',guard=budget()){return gate2WireDecode(text,tag,gate2SHA256,gate2Canonical,guard);}\nfunction encoded(text,tag='gate2-selected-lzw-v4',guard=budget('selected_wire_root_deadline')){return gate2WireEncode(text,tag,gate2SHA256,gate2Canonical,guard);}\nfunction finish(cause){if(failed)return;failed=true;report.cause=cause;process.stdout.write(gate2Canonical(report,32767)+'\\n');}\nprocess.stdin.on('error',()=>finish('d27_driver_input'));\nprocess.stdin.on('data',b=>{if(failed)return;inputBytes+=b.length;if(inputBytes>262144){finish('d27_driver_input');process.stdin.destroy();return;}chunks.push(b);});\nprocess.stdin.on('end',()=>{if(failed)return;try{\n const bytes=Buffer.concat(chunks);chunks=[];if(bytes.some(x=>x>127))throw Error('d27_driver_input');\n const text=bytes.toString('ascii'),request=JSON.parse(text);\n if(!request||typeof request!=='object'||Array.isArray(request)||Object.keys(request).sort().join()!=='case,data'||request.case!=='geometry'||gate2Canonical(request,262144)!==text)throw Error('d27_driver_input');\n if(process.versions.node!=='25.2.1')throw Error('d27_node_version');\n if(typeof gate2WireEncode!=='function'||typeof gate2WireDecode!=='function'||typeof gate2WireBudget!=='function')throw Error('d27_codec_absent');\n d23Geometry(request.data,report);\n if(report.checks.every(row=>row.ok)){report.completed=true;finish(null);}else finish('d27_geometry_hold');\n }catch(e){finish(new Set(['d27_codec_absent','d27_driver_assertion','d27_driver_input','d27_node_version']).has(e.message)?e.message:'d27_driver_error');}});\n"

D27_GEOMETRY_SOURCE_PINS = ((11065, 'c9e308fc544252984ed3e68df409539b621ada5590b76f976901f9bad76acc4f'), (2231, '3e6bdae5fca3837444a5ab4913e281cf427a72a296dec5fd909ae7aa836b7744'))
