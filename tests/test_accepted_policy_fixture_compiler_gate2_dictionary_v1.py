"""Ordinary authored D27 codec TEST source; no geometry admission is implied."""

D27_CODEC_TEST_DRIVER = r'''const fs=require('node:fs'),crypto=require('node:crypto');
const result={schema_version:1,case:null,node_version:process.versions.node,completed:false,cause:null,checks:[],measurements:[]};
function sha(s){return crypto.createHash('sha256').update(s,'ascii').digest('hex');}
function canon(v,cap){const s=JSON.stringify(v,Object.keys(v).sort());if(s.length>cap)throw Error('canonical_bound');return s;}
function check(id,ok){result.checks.push({id,ok:!!ok});if(!ok)throw Error('d27_driver_assertion');}
try{
 const input=JSON.parse(fs.readFileSync(0,'utf8'));
 if(!input||Object.keys(input).sort().join(',')!=='case,data'||input.case!=='codec_vectors'||!input.data||typeof input.data!=='object'||Array.isArray(input.data)||Object.keys(input.data).length)throw Error('d27_driver_input');
 result.case=input.case;
 if(process.versions.node!=='25.2.1')throw Error('d27_node_version');
 if(typeof gate2WireEncode!=='function'||typeof gate2WireDecode!=='function'||typeof gate2WireBudget!=='function')throw Error('d27_codec_absent');
 const original=canon({message:'D27 dictionary round trip'},32768);
 for(const [id,tag] of [['selected','gate2-selected-lzw-v4'],['observed','gate2-observed-lzw-v4']]){
  const wire=gate2WireEncode(original,tag,sha,canon,gate2WireBudget(()=>0,'selected_wire_deadline'));
  const recovered=gate2WireDecode(wire,tag,sha,canon,gate2WireBudget(()=>0,'selected_wire_deadline'));
  check(id+'_round_trip',recovered.text===original&&recovered.value.message==='D27 dictionary round trip');
 }
 result.completed=true;
}catch(error){const allowed=['d27_codec_absent','d27_driver_assertion','d27_driver_input','d27_driver_error','d27_node_version'];result.cause=allowed.includes(error&&error.message)?error.message:'d27_driver_error';}
const raw=JSON.stringify(result);if(Buffer.byteLength(raw,'ascii')+1>32768)process.exit(1);process.stdout.write(raw+'\n');
'''


def d27_node_driver_v1():
    """Return one fixed ordinary codec TEST driver; DATA cannot choose source."""
    return D27_CODEC_TEST_DRIVER
