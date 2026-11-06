import ast
import contextlib
import difflib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest

ROOT=Path('C:/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST')
TEMP=Path('C:/Users/s-a-balashov/AppData/Local/Temp')
CALLER=ROOT/'tests/test_accepted_policy_fixture_compiler_gate2_resume_caller_v1.py'
MAIN=ROOT/'tests/test_accepted_policy_fixture_compiler_gate2_resume_v1.py'
EXPECTED={CALLER:('fb0d558b412a055cf59ef4ce8a52c5174343de11da55e72ce1c9c961c1185d84',125086),
          MAIN:('c7edd00c6a0e27b46eb56941ab486e3d2a4c6b797c2b957840b7027f8f8e5909',182690)}
def descriptor(raw):
    return {'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def check_frozen():
    for path,(digest,size) in EXPECTED.items():
        assert descriptor(path.read_bytes())=={'size_bytes':size,'sha256':digest},path
check_frozen()
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
spec=importlib.util.spec_from_file_location('frozen_caller_record_guard_69',CALLER)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
original=m.CD_FACTORY_SOURCE
guard="""function cdRecord(v){
 if(v===null||typeof v!=='object')return false;
 let p=Object.getPrototypeOf(v);if(p!==null&&p!==Object.prototype)return false;
 for(let k of Reflect.ownKeys(v)){if(typeof k!=='string')return false;let d=Object.getOwnPropertyDescriptor(v,k);if(!d||d.enumerable!==true||!Object.hasOwn(d,'value'))return false;}return true;
}
"""
old="   let k=cdSaved.keys,h=cdSaved.hash,c=cdSaved.canon,sha=cdSaved.sha,r=external?.receipt,a=external?.approval;"
new="   if(!cdRecord(external))throw Error('cd_external_delivery');\n   let k=cdSaved.keys,h=cdSaved.hash,c=cdSaved.canon,sha=cdSaved.sha,r=external.receipt,a=external.approval;\n   if(!cdRecord(r)||!cdRecord(a))throw Error('cd_external_delivery');"
assert original.count('function cdStopped(')==1 and original.count(old)==1
candidate=original.replace('function cdStopped(',guard+'function cdStopped(',1).replace(old,new,1)
source=CALLER.read_text(encoding='utf-8')
assert source.count(original)==1
candidate_source=source.replace(original,candidate,1)
ast.parse(candidate_source,feature_version=(3,10))
patch=''.join(difflib.unified_diff(source.splitlines(True),candidate_source.splitlines(True),
    fromfile='a/tests/test_accepted_policy_fixture_compiler_gate2_resume_caller_v1.py',
    tofile='b/tests/test_accepted_policy_fixture_compiler_gate2_resume_caller_v1.py'))
patch_path=TEMP/'vast-gate2-later-caller-record-guard-69.unapplied.patch'
with patch_path.open('xb') as out:out.write(patch.encode('utf-8'))

class DataRecordTests(unittest.TestCase):
    def observe(self,transform):
        fixture=m.LaterStageCallerTests('runTest')
        args=['c'*40,'32768','d'*64,'-']
        external=fixture.external(args)
        text=m.canonical(external).decode('ascii')
        begin=fixture.begin_code('C1',args,external).replace(text,'delivery')
        code=('let delivery='+text+',getter_reads=0;'+transform+
              'let admission_error=null;try{'+begin+'}catch(e){admission_error=String(e.message);}'
              'nodeRepl.write(JSON.stringify({admission_error,getter_reads}));')
        value=fixture.node(code=code,action='normal')
        self.assertIsNone(value['error'])
        return value,json.loads(value['writes'][-1])

    def assert_denied(self,transform):
        value,result=self.observe(transform)
        self.assertEqual(result['admission_error'],'cd_external_delivery')
        self.assertEqual(result['getter_reads'],0)
        self.assertFalse(value['spawned'])
        self.assertEqual(len(value['imports']),value['inertInstall'][1][1])

    def test_boxed_and_custom_prototypes_refuse_before_fields_imports_or_spawn(self):
        for record in ('delivery','delivery.receipt','delivery.approval'):
            for kind in ('boxed','custom'):
                with self.subTest(record=record,kind=kind):
                    transform=(record+'=Object.assign(new String(""),'+record+');' if kind=='boxed'
                        else 'Object.setPrototypeOf('+record+',{unrequested:true});')
                    self.assert_denied(transform)

    def test_accessors_hidden_properties_and_symbols_refuse_without_getters(self):
        for record,key in (('delivery','receipt'),('delivery.receipt','record_sha256'),('delivery.approval','body_sha256')):
            for kind in ('accessor','nonenumerable','symbol'):
                with self.subTest(record=record,kind=kind):
                    if kind=='accessor':
                        transform=('let saved='+record+'['+json.dumps(key)+'];Object.defineProperty('+record+','+
                            json.dumps(key)+',{enumerable:true,configurable:true,get(){getter_reads++;return saved;}});')
                    elif kind=='nonenumerable':transform='Object.defineProperty('+record+',"hidden",{value:true,enumerable:false});'
                    else:transform=record+'[Symbol("hidden")]=true;'
                    self.assert_denied(transform)

    def test_plain_and_null_prototype_data_records_remain_valid(self):
        for records in ((),('delivery',),('delivery.receipt',),('delivery.approval',),
                        ('delivery','delivery.receipt','delivery.approval')):
            with self.subTest(records=records):
                value,result=self.observe(''.join('Object.setPrototypeOf('+record+',null);' for record in records))
                self.assertIsNone(result['admission_error'])
                self.assertEqual(result['getter_reads'],0)
                self.assertEqual(len(value['spawned']),1)
                self.assertEqual(value['killed'],0)

def run(path,geometry=False):
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(DataRecordTests)
    if geometry:suite.addTest(m.LaterStageCallerTests('test_authentic_98_character_native_c1_c6_d_outputs_and_complete_six_frame_geometry'))
    with path.open('xb') as raw:
        stream=io.TextIOWrapper(raw,encoding='utf-8',newline='\n',write_through=True)
        with contextlib.redirect_stdout(stream),contextlib.redirect_stderr(stream):
            print('CONTROLLED ONLY: real frozen CD_HARNESS; fake imports/spawn/streams/clock, no native/MCP operation')
            print('FACTORY',json.dumps(descriptor(m.CD_FACTORY_SOURCE.encode('ascii')),sort_keys=True))
            result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
        stream.flush();stream.detach()
    print(path.name,json.dumps(descriptor(path.read_bytes()),sort_keys=True),
          'tests',result.testsRun,'failures',len(result.failures),'errors',len(result.errors))
    return result

red=run(TEMP/'vast-gate2-later-caller-record-guard-red-69.original.txt')
assert not red.wasSuccessful() and len(red.failures)==15 and not red.errors
m.CD_FACTORY_SOURCE=m.CD_EXTENSION=candidate
green=run(TEMP/'vast-gate2-later-caller-record-guard-candidate-green-70.original.txt',geometry=True)
check_frozen()
print('FROZEN SOURCE UNCHANGED',json.dumps({p.name:descriptor(p.read_bytes()) for p in EXPECTED},sort_keys=True))
print('UNAPPLIED_PATCH',json.dumps(descriptor(patch_path.read_bytes()),sort_keys=True))
print('CANDIDATE_FACTORY',json.dumps(descriptor(candidate.encode('ascii')),sort_keys=True))
print('CANDIDATE_SOURCE_LITERAL_ONLY',json.dumps(descriptor(candidate_source.encode('utf-8')),sort_keys=True))
raise SystemExit(not green.wasSuccessful())
