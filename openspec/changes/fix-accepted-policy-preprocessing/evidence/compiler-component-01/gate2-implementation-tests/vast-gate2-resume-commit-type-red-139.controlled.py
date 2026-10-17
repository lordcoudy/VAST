import pathlib,hashlib,shutil,subprocess,json,sys
root=pathlib.Path('C:/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST')
path=root/'tests/test_accepted_policy_fixture_compiler_gate2_resume_v1.py'
before=path.read_bytes();assert len(before)==182690 and hashlib.sha256(before).hexdigest()=='c7edd00c6a0e27b46eb56941ab486e3d2a4c6b797c2b957840b7027f8f8e5909'
sys.path.insert(0,str(root))
from tests import test_accepted_policy_fixture_compiler_gate2_resume_v1 as t
node=shutil.which('node') or shutil.which('node.exe');assert node
body=r"""(async()=>{
let output=[],profile={max_output_tokens:100000,max_record_bytes:65536};
for(let label of ['BigInt40','StringWrapper40','CoercibleObject40','Number1e39','ValidString40']){
 let coerced=0,value=label==='BigInt40'?BigInt('1'.repeat(40)):label==='StringWrapper40'?new String('1'.repeat(40)):label==='CoercibleObject40'?{toString(){coerced++;return '1'.repeat(40);}}:label==='Number1e39'?1e39:'1'.repeat(40);
 let calls=0,refused=false,cause=null,result;
 try{result=await gate2Complete({mcp__node_repl__js:async()=>{calls++;throw Error('controlled_provider_stub');}},'initial','finalizer',profile,{code_commit:value,core_sha256:gate2SHA256('initial'),factory_sha256:gate2SHA256('factory')});cause=result.cause;}catch(e){refused=true;cause=String(e.message);}
 let prior=coerced,contextCause=null;
 try{gate2Context({code_commit:value,packet_size_bytes:1,packet_sha256:gate2SHA256('packet'),selected_sha256:gate2SHA256('selected'),core_sha256:gate2SHA256('initial'),factory_sha256:gate2SHA256('factory')});}catch(e){contextCause=String(e.message);}
 output.push({label,calls,refused,cause,precall_coercions:prior,context_coercions:coerced-prior,contextCause});
}
console.log(JSON.stringify(output));if(output.some(r=>r.label!=='ValidString40'&&(r.calls!==0||!r.refused||r.precall_coercions!==0||r.context_coercions!==0)))process.exitCode=1;
})().catch(e=>{console.error(e);process.exitCode=1;});"""
source=t.ROOT_ENCODER+'\n'+t.ROOT_SHA256+'\n'+t.ROOT_ORCHESTRATOR+'\n'+t.ROOT_RECEIVER+'\n'+body
r=subprocess.run([node,'-e',source],capture_output=True)
print('CONTROLLED_NODE',node,subprocess.run([node,'--version'],capture_output=True,check=True).stdout.decode().strip())
print(r.stdout.decode('utf-8'),end='');print(r.stderr.decode('utf-8'),end='')
after=path.read_bytes();assert before==after;print('FROZEN_MAIN_UNCHANGED',len(after),hashlib.sha256(after).hexdigest())
raise SystemExit(r.returncode)
