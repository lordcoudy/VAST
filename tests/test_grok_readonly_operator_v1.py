"""In-memory controls for the fixed read-only owner and census transport."""
from __future__ import annotations
import ast
import importlib.util
import io
import json
from pathlib import Path
import types
import unittest

ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/"openspec/changes/fix-accepted-policy-preprocessing/evidence/grok-runtime-boundary-20261028-01"

def operator():
    path=HERE/"grok_bounded_model_invocation_v1.proposed.ps1"
    if path.stat().st_size>65536: raise ValueError("source ceiling")
    source=path.read_text().split("$Pr9ReadonlyController = @'\n",1)[1].split("\n'@",1)[0]
    ns={"__name__":"pr9_operator_regression"}
    exec(compile(source,"fixed-readonly-owner-control","exec"),ns)
    return ns

def driver():
    path=HERE/"grok_bounded_model_driver_v1.proposed.py"
    spec=importlib.util.spec_from_file_location("pr9_census_terminal_control",path)
    result=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

class ReadonlyOperatorTest(unittest.TestCase):
    def test_loader_drift_refuses_before_protected_inputs(self):
        ns=operator()
        S=types.SimpleNamespace
        prefix=str(ns["PYTHON_ROOT"])
        fake=S(flags=S(isolated=1,no_site=1,no_user_site=1,dont_write_bytecode=1,utf8_mode=0),
               version_info=(3,14,7),executable=str(ns["PYTHON_ROOT"]/"python.exe"),
               prefix=prefix,base_prefix=prefix,path=[prefix],
               getwindowsversion=lambda:S(platform_version=(10,0,1)))
        ns["sys"]=fake
        class Census(dict):
            def __getitem__(self,key):
                if key=="files": raise AssertionError("protected input boundary")
                return super().__getitem__(key)
        census=Census(flags={key:1 for key in ("isolated","no_site","no_user_site","dont_write_bytecode")},
                      python={"version":[3,14,7],"prefix":prefix,"base_prefix":prefix,
                              "search_paths":[prefix],"utf8_mode":0},
                      os_base={"version":[10,0,1]})
        ns["runtime_census"]=lambda *_:census
        run=lambda:ns["prepare_inputs"](None,{"source_pins":{}},{},None,b"",{}, {})
        with self.assertRaisesRegex(AssertionError,"protected input boundary"): run()
        for field in ("path","utf8_mode"):
            with self.subTest(field=field):
                if field=="path": fake.path=["different"]
                else: fake.flags.utf8_mode=1
                with self.assertRaisesRegex(ValueError,"loader"): run()
                fake.path=[prefix];fake.flags.utf8_mode=0

    def test_early_owner_failure_keeps_retirement_overflow(self):
        ns=operator()
        first=ValueError();closing=OSError()
        owner=types.SimpleNamespace(handles=[1],retired=False,close_causes=[{"type":"OSError"}]*16,
                                    close_failure_count=17,close_cause_bound_exceeded=True)
        def retire():
            owner.handles.pop();owner.retired=True
            raise closing
        owner.retire=retire
        def prepare(): raise first
        def worker(*a,**kw): raise AssertionError("worker must not start")
        state=ns["own_qualification"](types.SimpleNamespace(run_qualification=worker),{}, {},owner,lambda:0,prepare)
        self.assertIs(state["errors"][0][1],first)
        self.assertIs(state["errors"][1][1],closing)
        self.assertIs(state.get("final_runtime_close_cause_bound_exceeded"),True)
        self.assertIs(state.get("final_runtime_retired"),True)
        self.assertEqual(state.get("final_runtime_close_count"),17)
        self.assertEqual(state.get("final_runtime_close_observed_causes"),owner.close_causes)
        self.assertEqual(state["remaining_runtime_handles"],0)
        self.assertIn("close_cause_bound_exceeded",state.get("final_runtime_observed_fields",[]))

    def test_census_caller_keeps_facts_when_retirement_raises(self):
        path=HERE/"source-control-recipes.md"
        self.assertLessEqual(path.stat().st_size,65536)
        code=path.read_text().rsplit("\x60\x60\x60python\n",1)[1].split("\x60\x60\x60",1)[0]
        function=next((node for node in ast.parse(code).body
                       if isinstance(node,ast.FunctionDef) and node.name=="retire_census_custody"),None)
        self.assertIsNotNone(function,"fixed census finalizer absent")
        ns={}
        exec(compile(ast.Module(body=[function],type_ignores=[]),"census-finalizer-control","exec"),ns)
        failure=OSError()
        owner=types.SimpleNamespace(handles=[1,2],retired=False,close_causes=[{"type":"OSError"}]*16,
                                    close_failure_count=17,close_cause_bound_exceeded=True)
        def retire():
            owner.handles.pop();owner.retired=True
            raise failure
        owner.retire=retire
        errors=[]
        result=ns["retire_census_custody"](owner,lambda p,e:errors.append((p,e)))
        self.assertIs(errors[0][1],failure)
        self.assertEqual(result["close_causes"],owner.close_causes)
        self.assertEqual(result["close_failure_count"],17)
        self.assertIs(result["close_cause_bound_exceeded"],True)
        self.assertIs(result["retired"],True)
        self.assertEqual(result["remaining_handles"],1)
        self.assertIn("remaining_handles",result["available"])

class CensusTerminalTest(unittest.TestCase):
    def emitter(self):
        module=driver()
        run=getattr(module,"emit_runtime_census",None)
        self.assertTrue(callable(run),"fixed census terminal absent")
        return module,run

    def test_completed_census_precedes_late_post_return_clock(self):
        module,run=self.emitter()
        events=[]
        value={"known":"complete"}
        class Output(io.BytesIO):
            def write(self,raw):
                events.append("stdout")
                return super().write(raw)
        calls=0
        def clock():
            nonlocal calls
            calls+=1
            if calls>1: events.append("post_clock")
            return 0 if calls==1 else 200
        out=Output();err=io.BytesIO()
        result=run({},100,collect=lambda _:value,now=clock,stdout=out,stderr=err)
        self.assertIs(result["completed_collection"],value)
        self.assertEqual(result["exit_code"],1)
        self.assertEqual(json.loads(out.getvalue()),value)
        self.assertLess(events.index("stdout"),events.index("post_clock"))
        self.assertEqual(json.loads(err.getvalue())["completed_collection"],value)

    def test_terminal_faults_preserve_maximum_collection_within_caps(self):
        module,run=self.emitter()
        value={"x":"x"*(61439-8)}
        self.assertEqual(len(module.bounded_json(value,61439)),61439)
        for fault in ("encode","write_and_flush","clock"):
            with self.subTest(fault=fault):
                class Output(io.BytesIO):
                    def write(self,raw):
                        if fault=="write_and_flush": raise OSError()
                        return super().write(raw)
                    def flush(self):
                        if fault=="write_and_flush": raise RuntimeError()
                        return super().flush()
                def encode(value_,limit):
                    if fault=="encode" and value_ is value: raise LookupError()
                    return module.bounded_json(value_,limit)
                calls=0
                def clock():
                    nonlocal calls
                    calls+=1
                    if fault=="clock" and calls>1: raise ArithmeticError()
                    return 0
                out=Output();err=io.BytesIO()
                result=run({},100,collect=lambda _:value,now=clock,encode=encode,stdout=out,stderr=err)
                self.assertIs(result["completed_collection"],value)
                self.assertEqual(result["exit_code"],1)
                fallback=json.loads(err.getvalue())
                self.assertEqual(fallback["completed_collection"],value)
                self.assertTrue(fallback["post_failures"])
                self.assertLessEqual(len(out.getvalue()),65536)
                self.assertLessEqual(len(err.getvalue()),65536)

    def test_read_close_failure_keeps_returned_facts_and_causes(self):
        module,run=self.emitter()
        returned={"bytes":4,"sha256":"a"*64,"close_complete":False}
        first=module.MetadataReadCloseError(returned,OSError())
        def collect(_): raise first
        out=io.BytesIO();err=io.BytesIO()
        result=run({},100,collect=collect,now=lambda:0,stdout=out,stderr=err)
        failure=json.loads(err.getvalue())["collection_failure"]
        self.assertEqual(result["exit_code"],1)
        self.assertIs(result["collection_failure"]["returned_facts"],returned)
        self.assertEqual(failure["returned_facts"],returned)
        self.assertEqual([row["type"] for row in failure["causes"]],["MetadataReadCloseError","OSError"])


class CensusRefusalLocationTest(unittest.TestCase):
    def capture(self):
        path=HERE/"grok_bounded_model_capture_v1.proposed.py"
        spec=importlib.util.spec_from_file_location("pr9_census_location_control",path)
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(callable(getattr(module,"_runtime_census_refusal_location",None)),
                        "fixed refusal location helper absent")
        self.assertTrue(callable(getattr(module,"_emit_runtime_census_refusal_location",None)),
                        "fixed refusal location writer absent")
        return module

    def terminal(self,filename="authenticated-runtime-census-driver",depth=0):
        code=("def collect_runtime_census(n):\n"
              "    if n: return collect_runtime_census(n-1)\n"
              "    raise ValueError('sentinel-private-message')\n"
              "collect_runtime_census("+str(depth)+")\n")
        try:
            exec(compile(code,filename,"exec"),{})
        except ValueError as error:
            return {"collection_exception":error,"collection_failure":{"operation":"runtime_census"},
                    "fallback_completed":True,"stderr":{"known_written_bytes":592,
                    "write_extent_unknown":False,"write_completed":True,"flush_completed":True}}

    def test_fixed_source_filter_privacy_bounds_and_literal_copy(self):
        module=self.capture()
        raw=module._runtime_census_refusal_location(self.terminal(depth=40))
        self.assertIsInstance(raw,bytes)
        self.assertLessEqual(len(raw),4096)
        self.assertTrue(raw.endswith(b"\n"))
        self.assertNotIn(b"sentinel-private-message",raw)
        value=json.loads(raw)
        self.assertEqual(value["driver_sha256"],module.METADATA_DRIVER_SHA256)
        self.assertTrue(value["truncated"])
        self.assertTrue(0<len(value["frames"])<=8)
        self.assertTrue(all(row["function"]=="collect_runtime_census" and 1<=row["line"]<=2000
                            for row in value["frames"]))
        outside=module._runtime_census_refusal_location(self.terminal(filename="private/auth.txt"))
        self.assertNotIn(b"private/auth.txt",outside)
        self.assertTrue(json.loads(outside)["location_unavailable"])
        literal=ast.parse(module.STATIC_ARGUMENTS["runtime_census"][-1])
        source=ast.parse((HERE/"grok_bounded_model_capture_v1.proposed.py").read_text())
        for name in ("_runtime_census_refusal_location","_emit_runtime_census_refusal_location"):
            left=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name==name)
            right=next(n for n in ast.walk(literal) if isinstance(n,ast.FunctionDef) and n.name==name)
            self.assertEqual(ast.dump(left,include_attributes=False),ast.dump(right,include_attributes=False))

    def test_budget_refusals_and_unknown_or_partial_write_are_not_retried(self):
        module=self.capture()
        terminal=self.terminal()
        terminal["stderr"]["known_written_bytes"]=60928
        self.assertIsInstance(module._runtime_census_refusal_location(terminal),bytes)
        for field,bad in (("known_written_bytes",60929),("known_written_bytes",True),
                          ("write_extent_unknown",True),("write_completed",False),("flush_completed",False)):
            with self.subTest(field=field,bad=bad):
                value=self.terminal();value["stderr"][field]=bad
                self.assertIsNone(module._runtime_census_refusal_location(value))
        calls=[]
        failure=OSError()
        def broken(descriptor,raw):
            calls.append((descriptor,len(raw)))
            raise failure
        value=self.terminal()
        result=module._emit_runtime_census_refusal_location(value,write=broken)
        self.assertEqual(len(calls),1)
        self.assertIs(result["error"],failure)
        self.assertTrue(result["write_extent_unknown"])
        self.assertFalse(result["write_completed"])
        calls.clear()
        def short(descriptor,raw):
            calls.append((descriptor,len(raw)))
            return 3
        result=module._emit_runtime_census_refusal_location(self.terminal(),write=short)
        self.assertEqual(len(calls),1)
        self.assertEqual(result["known_written_bytes"],3)
        self.assertFalse(result["write_extent_unknown"])
        self.assertFalse(result["write_completed"])


class CensusWindowsFileIdentityTest(unittest.TestCase):
    def test_creation_time_joins_path_and_descriptor_without_dropping_provenance(self):
        import hashlib
        import stat
        source=ast.parse((HERE/"grok_bounded_model_driver_v1.proposed.py").read_text())
        collector=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=="collect_runtime_census")
        functions=[n for n in collector.body if isinstance(n,ast.FunctionDef)
                   and n.name in ("identity","metadata","read_bound")]
        self.assertEqual(len(functions),3)
        module=driver()
        common={"st_dev":1,"st_ino":2,"st_size":4,"st_mtime_ns":5,"st_ctime_ns":6,
                "st_birthtime_ns":6,"st_file_attributes":32,"st_nlink":1,"st_mode":stat.S_IFREG|0o600}
        for changed in (None,"st_ino","st_birthtime_ns","st_file_attributes","st_nlink","st_mtime_ns","path_metadata","missing_birth"):
            with self.subTest(changed=changed):
                before=types.SimpleNamespace(**common)
                fd=types.SimpleNamespace(**{**common,"st_ctime_ns":99})
                if changed=="missing_birth":
                    delattr(fd,"st_birthtime_ns");fd.st_ctime_ns=6
                elif changed not in (None,"path_metadata"):
                    setattr(fd,changed,getattr(fd,changed)+1)
                closed=[];reads=[];parts=[b"data",b""]
                class PathFixture:
                    calls=0
                    def lstat(self):
                        self.calls+=1
                        return types.SimpleNamespace(**{**common,"st_file_attributes":0}) if changed=="path_metadata" and self.calls>1 else before
                path=PathFixture()
                def read(descriptor,maximum):
                    self.assertTrue(0<maximum<=65536)
                    reads.append(descriptor)
                    return parts.pop(0)
                fake=types.SimpleNamespace(O_RDONLY=0,O_BINARY=0,O_NOINHERIT=0,
                     open=lambda *_:99,fstat=lambda _:fd,read=read,close=lambda descriptor:closed.append(descriptor))
                ns={"os":fake,"stat":stat,"hashlib":hashlib,"MetadataReadCloseError":module.MetadataReadCloseError}
                exec(compile(ast.Module(body=functions,type_ignores=[]),"fixed-census-reader-control","exec"),ns)
                expected=ns["metadata"](path)
                try:
                    if changed is None:
                        try:
                            result,raw=ns["read_bound"](path,expected,hashlib.sha256(b"data").hexdigest(),True)
                        except ValueError:
                            self.fail("same creation time was refused because descriptor ctime is change time")
                        self.assertEqual(result,{"bytes":4,"sha256":hashlib.sha256(b"data").hexdigest(),"close_complete":True})
                        self.assertEqual(raw,b"data")
                    else:
                        with self.assertRaises((ValueError,AttributeError)):
                            ns["read_bound"](path,expected,hashlib.sha256(b"data").hexdigest(),True)
                        if changed!="path_metadata":self.assertEqual(reads,[])
                finally:
                    self.assertEqual(closed,[99])


    def test_operator_identity_requires_matching_creation_time(self):
        ns=operator()
        common={"st_dev":1,"st_ino":2,"st_size":4,"st_mtime_ns":5,"st_ctime_ns":6,
                "st_birthtime_ns":6,"st_file_attributes":32,"st_nlink":1}
        path=types.SimpleNamespace(**common)
        descriptor=types.SimpleNamespace(**{**common,"st_ctime_ns":99})
        self.assertEqual(ns["file_identity"](path),ns["file_identity"](descriptor))
        descriptor.st_birthtime_ns=7
        self.assertNotEqual(ns["file_identity"](path),ns["file_identity"](descriptor))


class MetadataInheritedDeadlineTest(unittest.TestCase):
    @unittest.skipUnless(__import__("shutil").which("pwsh"),"PowerShell is required")
    def test_expired_inherited_deadline_refuses_before_controller_launch(self):
        import base64
        import shutil
        import subprocess
        source=str(HERE/"grok_bounded_model_invocation_v1.proposed.ps1").replace("'","''")
        admission=base64.b64encode(b'{"deadline_tick_ms":0}').decode("ascii")
        command=(". '"+source+"'; Invoke-Pr9ReadonlyMetadata -AdmissionBase64 '"+admission+
                 "' -InvocationBytes 1 -InvocationSha256 '"+("a"*64)+
                 "' -ContractBytes 1 -ContractSha256 '"+("a"*64)+"' -OriginalDeadlineTickMs 1")
        result=subprocess.run([shutil.which("pwsh"),"-NoLogo","-NoProfile","-NonInteractive","-Command",command],
            stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=ROOT,timeout=15)
        self.assertLessEqual(len(result.stdout),4096)
        self.assertLessEqual(len(result.stderr),16384)
        self.assertEqual(result.returncode,0,result.stderr.decode("utf-8","replace"))
        receipt=json.loads(result.stdout.decode("utf-8-sig"))
        self.assertFalse(receipt["started"])
        self.assertIsNone(receipt["original_pid"])
        self.assertEqual(receipt["original_deadline_tick_ms"],1)
        self.assertTrue(receipt["causes"])


class MetadataConsoleBoundaryTest(unittest.TestCase):
    def test_normal_frame_reserves_its_final_lf_or_uses_full_fallback(self):
        ns=operator()
        state={"box":{"capture":None,"document_original":b"x",
                       "attestation":{"persistence":{"complete":True},"padding":""}},
               "errors":[],"error_count":0,"cause_overflow":False,"parent":None,
               "remaining_runtime_handles":0,"final_runtime_close_causes":[],
               "final_runtime_close_count":0,"final_runtime_close_observed_causes":[],
               "final_runtime_close_cause_bound_exceeded":False,"final_runtime_retired":True,
               "final_runtime_observed_fields":[],"final_runtime_close_return_available":True}
        admission={"deadline_tick_ms":100,"entry_approval":1}
        baseline=ns["make_frame"](state,admission,True,lambda:0)
        state["box"]["attestation"]["padding"]="x"*(4096-len(baseline))
        raw=ns["make_frame"](state,admission,True,lambda:0)
        value=json.loads(raw)
        if len(raw)+1>4096:
            self.assertEqual(value.get("witness_original_base64"),"eA==")
            self.assertTrue(value["outer"]["errors"])
        self.assertLessEqual(len(raw)+1,65536)

if __name__=="__main__":
    unittest.main()
