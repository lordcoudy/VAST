from pathlib import Path
import ast,hashlib,shutil,subprocess
path=Path('C:/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/tests/test_accepted_policy_fixture_compiler_gate2_resume_v1.py')
before=path.read_bytes();assert len(before)==182690 and hashlib.sha256(before).hexdigest()=='c7edd00c6a0e27b46eb56941ab486e3d2a4c6b797c2b957840b7027f8f8e5909'
values={n.targets[0].id:ast.literal_eval(n.value) for n in ast.parse(before).body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id in ('ROOT_ENCODER','ROOT_SHA256','ROOT_ORCHESTRATOR','ROOT_RECEIVER')}
body=r"""(async()=>{
let out=[],plain={profile:{max_output_tokens:100000,max_record_bytes:65536},pins:{code_commit:'1234567890123456789012345678901234567890',core_sha256:gate2SHA256('initial'),factory_sha256:gate2SHA256('factory')},context:{code_commit:'1234567890123456789012345678901234567890',packet_size_bytes:1,packet_sha256:gate2SHA256('packet'),selected_sha256:gate2SHA256('selected'),core_sha256:gate2SHA256('initial'),factory_sha256:gate2SHA256('factory')}};
for(let label of ['array','function','boxed_string','custom_prototype','plain','null_prototype'])for(let role of ['profile','pins','context']){
 let target=label==='array'?[]:label==='function'?function(){}:label==='boxed_string'?new String(''):label==='custom_prototype'?Object.create({}):label==='null_prototype'?Object.create(null):{};
 Object.assign(target,plain[role]);let calls=0,refused=false,cause=null;
 try{if(role==='context')gate2Context(target);else await gate2Complete({mcp__node_repl__js:async()=>{calls++;throw Error('controlled_provider_stub');}},'initial','finalizer',role==='profile'?target:plain.profile,role==='pins'?target:plain.pins);}catch(e){refused=true;cause=String(e.message);}
 out.push({label,role,calls,refused,cause});
}
console.log(JSON.stringify(out));if(out.some(r=>!['plain','null_prototype'].includes(r.label)&&(!r.refused||r.calls!==0)))process.exitCode=1;
})().catch(e=>{console.error(e);process.exitCode=1;});"""
node=shutil.which('node') or shutil.which('node.exe');assert node
source='\n'.join(values[k] for k in ('ROOT_ENCODER','ROOT_SHA256','ROOT_ORCHESTRATOR','ROOT_RECEIVER'))+'\n'+body
r=subprocess.run([node,'-e',source],capture_output=True)
print('CONTROLLED_NODE',node,subprocess.run([node,'--version'],capture_output=True,check=True).stdout.decode().strip())
print(r.stdout.decode('utf-8'),end='');print(r.stderr.decode('utf-8'),end='')
assert path.read_bytes()==before
print('FROZEN_MAIN_UNCHANGED',len(before),hashlib.sha256(before).hexdigest())
raise SystemExit(r.returncode)
