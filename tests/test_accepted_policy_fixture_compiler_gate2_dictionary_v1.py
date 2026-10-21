"""Ordinary authored D27 codec TEST source; no geometry admission is implied."""

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
const result={schema_version:1,case:null,node_version:process.versions.node,completed:false,cause:null,checks:[],measurements:[]};
const selected='gate2-selected-lzw-v4',observed='gate2-observed-lzw-v4';
function sha(s){return crypto.createHash('sha256').update(s,'ascii').digest('hex');}
function canon(v,cap){
 function enc(x){
  if(x===null||typeof x==='boolean')return JSON.stringify(x);
  if(typeof x==='number'){if(!Number.isFinite(x))throw Error('canonical_number');return JSON.stringify(x);}
  if(typeof x==='string')return JSON.stringify(x).replace(/[\u007f-\uffff]/g,c=>'\\u'+c.charCodeAt(0).toString(16).padStart(4,'0'));
  if(Array.isArray(x))return '['+x.map(enc).join(',')+']';
  if(x&&typeof x==='object')return '{'+Object.keys(x).sort().map(k=>enc(k)+':'+enc(x[k])).join(',')+'}';
  throw Error('canonical_type');
 }
 const s=enc(v);if(s.length>cap)throw Error('canonical_bound');return s;
}
function check(id,ok){result.checks.push({id,ok:!!ok});if(!ok)throw Error('d27_driver_assertion');}
function want(id,fn,expected){let actual=null;try{fn();}catch(e){actual=e&&e.message;}check(id,actual===expected);}
function budget(){return gate2WireBudget(()=>0,'selected_wire_deadline');}
function decode(w,tag=selected,b=budget()){return gate2WireDecode(w,tag,sha,canon,b);}
function encode(t,tag=selected,b=budget()){return gate2WireEncode(t,tag,sha,canon,b);}
function width(n){for(let w=7;w<=13;w++)if(n<=2**w)return w;throw Error('d27_driver_assertion');}
function digits(v){return String.fromCharCode(32+v+(v>=2)+(v>=59));}
// Independent hand-packet oracle belongs only to ordinary TEST, never codec source.
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
 return canon({encoding:selected,expanded_sha256:digest,expanded_size_bytes:size,payload:p===null?packed(bits).payload:p},12288);
}
// Independent decoder oracle may use phrase strings in TEST only.
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
 for(let i=0;i<values.length;i++)for(const [name,tag] of [['selected',selected],['observed',observed]]){
  const text=canon(values[i],32768),wire=encode(text,tag),r=decode(wire,tag);
  check(name+'_round_trip_'+i,r.text===text&&canon(r.value,32768)===text);
 }
 const wide=canon('A'.repeat(4100),32768);same('literal_widths_7_through_13',wide);
 for(const [oldN,newN] of [[128,129],[256,257],[512,513],[1024,1025],[2048,2049],[4096,4097]])
  check('width_'+oldN+'_'+newN,width(oldN)+1===width(newN)&&newN-95<wide.length);
 let distinct='';for(let i=0;i<93;i++){distinct+=digits(i);for(let j=i+1;j<93;j++)distinct+=digits(i)+digits(j);}
 for(const n of [34,35,162,163,418,419,930,931,1954,1955,4002,4003]){
  const text=canon(distinct.slice(0,n-2),32768),pairs=new Set();
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
 const independent=oracle(encode(alphabet));
 check('encoder_independent_phrase_oracle',independent.text===alphabet);
 check('encoder_actual_widths_7_through_13',[7,8,9,10,11,12,13].every(w=>independent.widths.has(w)));
 const byteSeen=new Set(),groupSeen=new Set();
 for(let n=0;n<512&&(byteSeen.size<8||groupSeen.size<13);n++){
  const text=canon('B'.repeat(n),32768),bits=literalBits(text),p=packed(bits);
  if(!byteSeen.has(p.bytePad)){byteSeen.add(p.bytePad);same('byte_pad_'+p.bytePad,text);if(p.bytePad)want('byte_pad_nonzero_'+p.bytePad,()=>decode(envelope(text,[],text.length,sha(text),packed(bits,bits.length,true).payload)),'selected_wire_token');}
  if(!groupSeen.has(p.groupPad)){groupSeen.add(p.groupPad);same('group_pad_'+p.groupPad,text);if(p.groupPad)want('group_pad_nonzero_'+p.groupPad,()=>decode(envelope(text,[],text.length,sha(text),packed(bits,bits.length,false,true).payload)),'selected_wire_token');}
 }
 check('all_byte_padding_extents',byteSeen.size===8);check('all_group_padding_extents',groupSeen.size===13);
 // Deliberately positive virtual N above the protected v2 9216 domain, below actual wire cap.
 const large=canon('C'.repeat(6500),32768),bits=literalBits(large),n=3+Math.ceil(bits.length/8),wire=envelope(large,bits);
 check('positive_virtual_N_above_9216',n>9216&&n<=9984&&wire.length<=12288);same('decode_virtual_N_above_9216',large,wire);
}
function malformed(){
 const text='"A"',valid=envelope(text),bad=changed(valid,{payload:'!'});
 for(const [id,value] of [['empty',''],['type',null],['control','\n'],['wire_limit',' '.repeat(12289)]])want('input_'+id,()=>decode(value),'selected_wire_input');
 for(const [id,value] of [['parse','{'],['array','[]'],['extra',changed(valid,{extra:1})],['tag',changed(valid,{encoding:observed})],['hash',changed(valid,{expanded_sha256:'A'.repeat(64)})],['fraction',changed(valid,{expanded_size_bytes:1.5})],['boolean',changed(valid,{expanded_size_bytes:true})],['unsafe',changed(valid,{expanded_size_bytes:9007199254740992})],['spelling',valid.replace('"expanded_size_bytes":3','"expanded_size_bytes":3e0')]])want('shape_'+id,()=>decode(value),'selected_wire_shape');
 for(const n of [0,-1,32769])want('declared_bound_'+(n+1),()=>decode(changed(bad,{expanded_size_bytes:n})),'selected_wire_bound');
 for(const [id,p] of [['empty',''],['odd','!'],['short2','  '],['short4','    '],['quote','" '],['backslash','\\ '],['tab','\t '],['newline','\n '],['del',String.fromCharCode(127)+' '],['unicode','\u00e9 '],['suffix',JSON.parse(valid).payload+'  ']])
  want('transport_'+id,()=>decode(changed(valid,{payload:p})),'selected_wire_token');
 const nativeChar=String.prototype.charCodeAt;let current=null,reads=0;
 String.prototype.charCodeAt=function(i){if(String(this)===current)reads++;return nativeChar.call(this,i);};
 try{for(let v=8192;v<8649;v++){
  const p=JSON.parse(valid).payload,forbidden=digits(Math.floor(v/93))+digits(v%93);
  current=p.slice(0,-2)+forbidden;reads=0;
  let caught=null;try{decode(changed(valid,{payload:current}));}catch(e){caught=e&&e.message;}
  if(caught!=='selected_wire_token'||reads!==current.length)throw Error('d27_driver_assertion');
 }}finally{String.prototype.charCodeAt=nativeChar;}
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
 want('zero_T',()=>decode(changed(valid,{payload:packed([],0).payload})),'selected_wire_token');
 want('impossible_header_extent',()=>decode(changed(valid,{payload:packed([0],16777215).payload})),'selected_wire_token');
 want('swapped_selected_tag',()=>decode(encode(text,observed)),'selected_wire_shape');
 const exactCodes=[2,33,33];for(let i=0;i<6633;i++)exactCodes.push(i<3363?96:33);exactCodes.push(2);
 const exactText=canon('A'.repeat(9998),32768),exact=envelope(exactText,codeBits(exactCodes));
 check('wire_exact_12288_extent',exact.length===12288);same('wire_exact_12288_positive',exactText,exact);
 want('wire_12289_input',()=>decode(exact+' '),'selected_wire_input');
 want('encoder_original_32769_input',()=>encode('A'.repeat(32769)),'selected_wire_input');
}
function overflow(){
 const kw=envelope('"AAAAAAAA"',codeBits([2,33,96,97,96,2]));
 let work=0,last=-1,charged=true,alloc=[];
 const g=()=>0;g.work=()=>{work++;};g.phase=fn=>{g();const v=fn();g();return v;};
 const U8=globalThis.Uint8Array,U16=globalThis.Uint16Array;
 function wrap(C,kind,n){alloc.push([kind,n]);return new Proxy(new C(n),{
  get(t,k){if(/^[0-9]+$/.test(String(k))){if(work<=last)charged=false;last=work;}return Reflect.get(t,k,t);},
  set(t,k,v){if(/^[0-9]+$/.test(String(k))){if(work<=last)charged=false;last=work;}return Reflect.set(t,k,v,t);}
 });}
 try{
  globalThis.Uint8Array=function(n){return wrap(U8,'u8',n);};
  globalThis.Uint16Array=function(n){return wrap(U16,'u16',n);};
  check('observed_kwkwk_result',decode(kw,selected,g).text==='"AAAAAAAA"');
 }finally{globalThis.Uint8Array=U8;globalThis.Uint16Array=U16;}
 check('each_dictionary_stack_access_separately_charged',charged);
 check('exact_three_dictionary_arrays',JSON.stringify(alloc)===JSON.stringify([['u16',8192],['u8',8192],['u8',8192]]));
 let calls=0;const b=gate2WireBudget(()=>{calls++;return 0;},'selected_wire_deadline');
 for(let i=0;i<256;i++)b.work();check('at_most_256_work_between_samples',calls===1);b.work();check('sample_before_257th_work',calls===2);
 for(const [id,now,end] of [['nonfinite',()=>NaN,Infinity],['expiry',()=>5000,5000],['invalid_end',()=>0,NaN]])
  want('clock_'+id,()=>decode(kw,selected,gate2WireBudget(now,'selected_wire_deadline',end)),'selected_wire_deadline');
 let tick=0;want('clock_regression',()=>{const b=gate2WireBudget(()=>tick++===0?1:0,'selected_wire_deadline');return decode(kw,selected,b);},'selected_wire_deadline');
 tick=0;want('post_throw_clock_precedence',()=>{const b=gate2WireBudget(()=>tick++===0?0:5000,'selected_wire_deadline');return decode('{',selected,b);},'selected_wire_deadline');
 want('primitive_before_clock',()=>decode('',selected,gate2WireBudget(()=>NaN,'selected_wire_deadline')),'selected_wire_input');
 for(const kind of ['encode','decode']){
  let clock=0;const b=gate2WireBudget(()=>clock,'selected_wire_deadline'),t='"A"';
  if(kind==='encode')encode(t,selected,b);else decode(envelope(t),selected,b);
  clock=5000;
  want('shared_selected_observed_'+kind,()=>kind==='encode'?encode(t,observed,b):decode(changed(envelope(t),{encoding:observed}),observed,b),'selected_wire_deadline');
 }
 let touched=0,A=globalThis.Array,M=globalThis.Map,capacity=0;
 function CountArray(...args){touched++;return new A(...args);}CountArray.isArray=A.isArray;
 class CountMap extends M{set(k,v){capacity++;return super.set(k,v);}}
 let random=1,s='';for(let i=0;i<32768;i++){random=(Math.imul(random,1103515245)+12345)>>>0;s+=String.fromCharCode(32+random%95);}
 try{globalThis.Array=CountArray;globalThis.Map=CountMap;want('wire_bound_before_capacity',()=>encode(s),'selected_wire_bound');}
 finally{globalThis.Array=A;globalThis.Map=M;}
 check('zero_premature_payload_vectors',touched===0);check('wire_refusal_before_dictionary_saturation',capacity<8097);
 // Observe actual payload reads: scan, cold pair0 load, header hits, end-pad jump, backward token reload.
 const charCode=String.prototype.charCodeAt;
 for(const [label,text] of [['zero','"A"'],['nonzero',canon('D'.repeat(400),32768)]]){
  const wire=envelope(text),p=JSON.parse(wire).payload,reads=[],stamps=[];let work=0;
  const trace=()=>0;trace.work=()=>{work++;};trace.phase=fn=>fn();
  String.prototype.charCodeAt=function(i){if(String(this)===p){reads.push(i);stamps.push(work);}return charCode.call(this,i);};
  try{check('cache_decode_'+label,decode(wire,selected,trace).text===text);}finally{String.prototype.charCodeAt=charCode;}
  const scan=Array.from({length:p.length},(_,i)=>i);
  check('cache_every_actual_read_has_fresh_work_'+label,stamps.every((v,i)=>i===0||v>stamps[i-1]));
  const h=(p.charCodeAt(0)-32-(p.charCodeAt(0)>34)-(p.charCodeAt(0)>92))*93+p.charCodeAt(1)-32-(p.charCodeAt(1)>34)-(p.charCodeAt(1)>92);
  check('cache_header_value_'+label,label==='zero'?h===0:h>0);
  check('cache_complete_scan_'+label,reads.slice(0,p.length).join(',')===scan.join(','));
  check('cache_first_actual_pair0_load_'+label,reads[p.length]===0&&reads[p.length+1]===1);
  check('cache_true_header_hits_'+label,reads[p.length+2]===2&&reads[p.length+3]===3);
  check('cache_backward_body_reload_'+label,reads.slice(p.length+4).some((x,i,a)=>i>0&&x<a[i-1]));
 }
 // Saturation is unreachable; this is source/arithmetic, not a public full-table witness.
 const encoder=34*7+128*8+256*9+512*10+1024*11+2048*12+4095*13,decoder=encoder+13;
 check('saturation_impossibility_arithmetic',encoder===97761&&decoder===97774&&79848<encoder);
}
try{
 const input=JSON.parse(fs.readFileSync(0,'utf8'));
 if(!input||Object.keys(input).sort().join(',')!=='case,data'||!['codec_vectors','codec_malformed','codec_overflow'].includes(input.case)||!input.data||typeof input.data!=='object'||Array.isArray(input.data)||Object.keys(input.data).length)throw Error('d27_driver_input');
 result.case=input.case;
 if(process.versions.node!=='25.2.1')throw Error('d27_node_version');
 if(typeof gate2WireEncode!=='function'||typeof gate2WireDecode!=='function'||typeof gate2WireBudget!=='function')throw Error('d27_codec_absent');
 if(input.case==='codec_vectors')vectors();else if(input.case==='codec_malformed')malformed();else overflow();
 result.completed=true;
}catch(error){const allowed=['d27_codec_absent','d27_driver_assertion','d27_driver_input','d27_driver_error','d27_node_version'];result.cause=allowed.includes(error&&error.message)?error.message:'d27_driver_error';}
let raw;try{raw=canon(result,32767);}catch{process.exit(1);}
process.stdout.write(raw+'\n');
'''


def d27_node_driver_v1():
    """Return one fixed ordinary codec TEST driver; DATA cannot choose source."""
    return D27_WIRE_CODEC+D27_CODEC_TEST_DRIVER
