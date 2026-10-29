"""In-memory controls for the fixed read-only owner and census transport."""
from __future__ import annotations
import ast
import importlib.util
import io
import json
from pathlib import Path
import types
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"scripts/prepare_grok_review_volume_v1.ps1"
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


class GrokReadonlyCallerTest(unittest.TestCase):
    def load_caller(self, *, native=False):
        import importlib.util
        path = ROOT / "openspec/changes/fix-accepted-policy-preprocessing/evidence/grok-runtime-boundary-20261028-01/grok_bounded_model_driver_v1.proposed.py"
        self.assertTrue(path.is_file(), "fixed read-only caller is absent")
        spec = importlib.util.spec_from_file_location("pr9_readonly_caller_control", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        # Only this test module receives the checkout root and simulated Win32 ABI.
        # Actual native cases request native=True and remain Windows-only.
        module.ROOT = ROOT
        if not native:
            module.os = types.SimpleNamespace(**vars(module.os))
            module.os.O_BINARY, module.os.O_NOINHERIT = 0x8000, 0x80
            module.ctypes = types.SimpleNamespace(**vars(module.ctypes))
            last_error = [0]
            module.ctypes.set_last_error = lambda number: last_error.__setitem__(0, number)
            module.ctypes.get_last_error = lambda: last_error[0]
            def winerror(number=0):
                error = OSError(number, "controlled Windows error")
                error.winerror = number
                return error
            module.ctypes.WinError = winerror
            def native_tripwire(*args, **kwargs):
                raise AssertionError("pure control reached a native boundary")
            for name in ("open", "close", "read", "write", "fsync"):
                setattr(module.os, name, native_tripwire)
            module.ctypes.WinDLL = module.ctypes.CDLL = native_tripwire
        return module

    def test_import_and_default_description_have_no_execution_authority(self):
        module = self.load_caller()
        result = module.describe()
        self.assertEqual(result["scope"], "ntfs_metadata_qualification_v1")
        self.assertFalse(result["execution_authority"])
        self.assertFalse(result["capacity_accepted"])

    def test_missing_admission_refuses_without_environment_or_worker_entry(self):
        from unittest import mock
        module = self.load_caller()
        with mock.patch.object(module, "qualify_parent", side_effect=AssertionError("environment tripwire")):
            with self.assertRaises(ValueError):
                module.run_qualification({}, {}, now_tick=1000)

    def test_oversize_witness_refuses_before_file_creation(self):
        from unittest import mock
        module = self.load_caller()
        with mock.patch.object(module.os, "open", side_effect=AssertionError("allocation tripwire")):
            with self.assertRaises(ValueError):
                module.persist_witness(ROOT / "unused", b"x" * 32769)

    def test_write_failure_preserves_first_cause_and_still_flushes_and_closes(self):
        from unittest import mock
        module = self.load_caller()
        write_error = OSError("controlled write")
        flush_error = OSError("controlled flush")
        close_error = OSError("controlled close")
        with mock.patch.object(module.os, "open", return_value=17), \
             mock.patch.object(module.os, "write", side_effect=[2, write_error]), \
             mock.patch.object(module.os, "fsync", side_effect=flush_error) as flush, \
             mock.patch.object(module.os, "close", side_effect=close_error) as close:
            result = module.persist_witness(ROOT / "unused", b"abcd")
        self.assertEqual(result["known_written_bytes"], 2)
        self.assertTrue(result["write_extent_unknown"])
        self.assertFalse(result["complete"])
        self.assertEqual(result["primary"]["phase"], "write")
        self.assertEqual([row["phase"] for row in result["secondary"]], ["fsync", "close"])
        flush.assert_called_once_with(17)
        close.assert_called_once_with(17)

    def test_collision_does_not_write_flush_close_or_adopt(self):
        from unittest import mock
        module = self.load_caller()
        with mock.patch.object(module.os, "open", side_effect=FileExistsError("controlled collision")), \
             mock.patch.object(module.os, "write", side_effect=AssertionError("write tripwire")), \
             mock.patch.object(module.os, "fsync", side_effect=AssertionError("flush tripwire")), \
             mock.patch.object(module.os, "close", side_effect=AssertionError("close tripwire")):
            result = module.persist_witness(ROOT / "unused", b"abcd")
        self.assertFalse(result["complete"])
        self.assertFalse(result["created"])
        self.assertEqual(result["primary"]["phase"], "create_new")

    def test_read_access_time_change_is_not_source_identity_drift(self):
        import hashlib
        from types import SimpleNamespace
        from unittest import mock
        module = self.load_caller()
        raw = b"bounded source"
        before = SimpleNamespace(st_dev=1, st_ino=2, st_size=len(raw), st_mtime_ns=4,
                                 st_atime_ns=5, st_nlink=1, st_mode=0o100600, st_file_attributes=0)
        after = SimpleNamespace(**{**before.__dict__, "st_atime_ns": 6})
        path = mock.Mock()
        path.lstat.return_value = before
        path.is_symlink.return_value = False
        with mock.patch.object(module.os, "open", return_value=17), \
             mock.patch.object(module.os, "fstat", side_effect=[before, after]), \
             mock.patch.object(module.os, "read", side_effect=[raw, b""]), \
             mock.patch.object(module.os, "close") as close:
            module.snapshot(path, len(raw), hashlib.sha256(raw).hexdigest())
        close.assert_called_once_with(17)

    def test_ps7_policy_uses_the_actual_core_registry_root(self):
        import types
        from unittest import mock
        module = self.load_caller()
        closed = []
        def open_key(hive, name, reserved, access):
            if name == r"Software\Policies\Microsoft\PowerShellCore\Transcription":
                return 17
            raise FileNotFoundError()
        registry = types.SimpleNamespace(HKEY_LOCAL_MACHINE=1, HKEY_CURRENT_USER=2,
            KEY_WOW64_64KEY=4, KEY_WOW64_32KEY=8, KEY_READ=16, OpenKey=open_key,
            CloseKey=lambda handle: closed.append(handle))
        with mock.patch.dict(sys.modules, {"winreg": registry}), \
             mock.patch.object(module, "PSHOME", ROOT / "absent-controlled-policy-home"), \
             mock.patch.dict(module.os.environ, {"USERPROFILE": str(ROOT / "absent-controlled-policy-user")}):
            with self.assertRaises(ValueError):
                module.check_powershell_policy()
        self.assertEqual(closed, [17])

    def test_token_close_is_attempted_after_sid_memory_free_failure(self):
        from unittest import mock
        module = self.load_caller()
        first = OSError("controlled SID release")
        second = OSError("controlled token close")
        free = mock.Mock(side_effect=first)
        close = mock.Mock(side_effect=second)
        result = module.release_parent_resources(free, close, 31, 17)
        self.assertEqual(result, [first, second])
        free.assert_called_once_with(31)
        close.assert_called_once_with(17)

    def test_runtime_custody_rejects_a_different_opened_file_identity(self):
        from unittest import mock
        module = self.load_caller()
        custody = object.__new__(module.RuntimeCustody)
        custody.paths = set()
        custody.handles = []
        custody.close_causes = []
        custody.create = mock.Mock(return_value=17)
        custody.close = mock.Mock(return_value=True)
        custody.opened_identity = mock.Mock(return_value={"volume": 0, "file_index": 0,
            "bytes": 0, "links": 1, "attributes": 0})
        with self.assertRaises(ValueError):
            custody.hold(SOURCE)
        self.assertEqual(custody.handles, [17])
        self.assertEqual(custody.retire(), [])
        custody.close.assert_called_once_with(17)

    @unittest.skipUnless(sys.platform == "win32", "Windows native runtime handle control")
    def test_runtime_custody_joins_and_closes_its_actual_read_handle(self):
        module = self.load_caller(native=True)
        custody = module.RuntimeCustody()
        try:
            custody.hold(SOURCE)
            self.assertEqual(len(custody.handles), 1)
            self.assertIn(SOURCE, custody.paths)
        finally:
            errors = custody.retire()
        self.assertEqual(errors, [])
        self.assertEqual(custody.handles, [])

    def test_current_user_policy_checks_the_resolved_documents_folder(self):
        import io
        import types
        from unittest import mock
        module = self.load_caller()
        documents = ROOT / "controlled-redirected-documents"
        config = documents / "PowerShell/powershell.config.json"
        registry = types.SimpleNamespace(HKEY_LOCAL_MACHINE=1, HKEY_CURRENT_USER=2,
            KEY_WOW64_64KEY=4, KEY_WOW64_32KEY=8, KEY_READ=16,
            OpenKey=mock.Mock(side_effect=FileNotFoundError()), CloseKey=mock.Mock())
        with mock.patch.dict(sys.modules, {"winreg": registry}), \
             mock.patch.object(module, "documents_directory", return_value=documents, create=True), \
             mock.patch.object(module, "PSHOME", ROOT / "absent-controlled-policy-home"), \
             mock.patch.dict(module.os.environ, {"USERPROFILE": str(ROOT / "absent-controlled-policy-user")}), \
             mock.patch.object(Path, "exists", autospec=True, side_effect=lambda path: path == config), \
             mock.patch.object(Path, "stat", return_value=types.SimpleNamespace(st_size=66)), \
             mock.patch.object(Path, "open", return_value=io.BytesIO(b'{"PowerShellPolicies":{"Transcription":{"EnableTranscripting":true}}}')):
            with self.assertRaises(ValueError):
                module.check_powershell_policy()

    def test_returned_capture_survives_witness_persistence_failure(self):
        import base64
        import hashlib
        from types import SimpleNamespace
        from unittest import mock
        module = self.load_caller()
        fake_worker = b'''METADATA_EXECUTABLE = r"C:\\Python314\\python.exe"
class WindowsObservation:
 def tick(self): return 1000
def load_reviewed_job_definitions(raw): return object
def capture_literal(**kw): return {"facts":{"complete":True,"original_pid":17},"private_channel_bytes":[b"original metadata",b""],"private_primary":None,"private_secondary":()}
_QUARANTINED_READERS=[None,None]
'''
        sources = {"capture": fake_worker, "driver": b"d", "guard": b"g", "jobs": b"j"}
        admission = {"schema_version": 1, "scope": module.SCOPE,
            "planning_commit": "44e8cef19d70f555e2f37dd4ea07651bd9b8125f",
            "reviewed_commit": "a" * 40, "entry_approval": 103, "independent_reviews": [101, 102],
            "deadline_tick_ms": 31000, "boot_filetime": "123", "ordinary_sid": module.SID,
            "source_pins": {name: {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()} for name, raw in sources.items()}}
        custody = SimpleNamespace(paths=set(module.SOURCE_PATHS.values()) | {module.PSHOME / "pwsh.exe", Path(sys.executable)},
                                  active=True, retire=mock.Mock(return_value=[]))
        box = {"capture": None, "document_original": None, "attestation": None}
        parent = {"sid": module.SID, "elevated": True, "pid": 19, "boot_filetime": "123"}
        persistence = {"complete": False, "known_written_bytes": 3, "write_extent_unknown": True,
                       "primary": {"phase": "write", "type": "OSError"}}
        with mock.patch.object(module, "qualify_parent", return_value=parent), \
             mock.patch.object(module, "persist_witness", return_value=persistence), \
             mock.patch.object(Path, "exists", return_value=False):
            result = module.run_qualification(admission, sources, now_tick=1000, custody=custody,
                                             enclosing_result=box)
        original = base64.b64decode(result["witness_original_base64"], validate=True)
        self.assertEqual(original, box["document_original"])
        self.assertEqual(json.loads(original)["prefixes_base64"], [base64.b64encode(b"original metadata").decode(), ""])
        self.assertEqual(box["capture"]["facts"]["original_pid"], 17)
        self.assertEqual(result["attestation"]["persistence"], persistence)
        self.assertFalse(result["attestation"]["qualification_accepted"])
        self.assertFalse(result["attestation"]["capacity_accepted"])
        self.assertLessEqual(len(module.bounded_json(result["attestation"], 4096)), 4096)
        self.assertLessEqual(len(module.bounded_json(result, 65536)), 65536)
        custody.retire.assert_called_once_with()

    def metadata_fixture(self, module):
        from types import SimpleNamespace
        events = []
        api = SimpleNamespace(
            v_absent=lambda: events.append("v_namespace") or True,
            ntfs_e=lambda: events.append("ntfs_E") or {"filesystem": "NTFS"},
            file_metadata=lambda path: events.append(path) or {"path": path, "allocation": 4096})
        parent = lambda: {"sid": module.SID, "elevated": True}
        return api, parent, events

    def test_python_metadata_refuses_expired_deadline_before_parent_or_api(self):
        from unittest import mock
        module = self.load_caller()
        tripwire = mock.Mock(side_effect=AssertionError("native entry tripwire"))
        with self.assertRaises(ValueError):
            module.collect_metadata(1000, now=lambda: 1000, api_factory=tripwire, parent_check=tripwire)
        tripwire.assert_not_called()

    def test_python_metadata_executes_only_the_six_fixed_read_operations(self):
        module = self.load_caller()
        api, parent, events = self.metadata_fixture(module)
        result = module.collect_metadata(31000, now=lambda: 1000, api_factory=lambda: api, parent_check=parent)
        self.assertTrue(result["complete"])
        self.assertEqual(events, ["v_namespace", "ntfs_E", r"E:\$MFT", r"E:\$LogFile", r"E:\$Secure", r"E:\VAST-pr9"])
        self.assertEqual(len(result["records"]), 6)
        self.assertFalse(result["capacity_accepted"])
        self.assertEqual(result["storage_effects"], 0)

    def test_python_metadata_preserves_the_actual_late_return_before_stopping(self):
        module = self.load_caller()
        api, parent, events = self.metadata_fixture(module)
        clock = [1000]
        marker = {"path": r"E:\$MFT", "allocation": 8192}
        def late_read(path):
            events.append(path)
            clock[0] = 31000
            return marker
        api.file_metadata = late_read
        result = module.collect_metadata(31000, now=lambda: clock[0], api_factory=lambda: api, parent_check=parent)
        self.assertFalse(result["complete"])
        self.assertTrue(result["deadline_exceeded"])
        self.assertEqual(len(result["records"]), 3)
        self.assertIs(result["records"][-1]["facts"], marker)
        self.assertEqual(events[-1], r"E:\$MFT")

    def test_python_metadata_keeps_completed_read_when_original_handle_close_fails(self):
        from unittest import mock
        module = self.load_caller()
        api = object.__new__(module.MetadataWin32)
        api.create = mock.Mock(return_value=17)
        closing = OSError("controlled close")
        api.close = mock.Mock(side_effect=closing)
        marker = {"allocation": 4096}
        try:
            api.with_handle("controlled", 0x80, 0x02200000, lambda handle: marker)
        except BaseException as error:
            result = module.metadata_failure(error, "controlled_close")
        else:
            self.fail("expected original handle close failure")
        self.assertIs(result["returned_facts"], marker)
        self.assertTrue(result["returned_facts_available"])
        self.assertFalse(result["complete"])
        api.close.assert_called_once_with(17)

    def test_python_metadata_native_abi_extents_are_exact(self):
        import ctypes
        module = self.load_caller()
        self.assertEqual(ctypes.sizeof(module.MetadataBasic), 52)
        self.assertEqual(ctypes.sizeof(module.MetadataStandard), 24)

    def test_python_metadata_clock_failure_preserves_the_completed_read(self):
        module = self.load_caller()
        api, parent, events = self.metadata_fixture(module)
        calls = [0]
        def clock():
            calls[0] += 1
            if calls[0] >= 3:
                raise OSError("controlled observation clock")
            return 1000
        result = module.collect_metadata(31000, now=clock, api_factory=lambda: api, parent_check=parent)
        self.assertFalse(result["complete"])
        self.assertIsNone(result["deadline_exceeded"])
        self.assertEqual(result["records"][0]["facts"], {"absent": True})
        self.assertEqual(events, ["v_namespace"])
        self.assertIsNone(result["finished_tick_ms"])

    def test_python_metadata_repeated_error_identity_does_not_exhaust_causes(self):
        module = self.load_caller()
        same = OSError("controlled repeated cause")
        result = module.metadata_failure(ExceptionGroup("controlled", [same] * 32), "controlled_identity")
        self.assertFalse(result["cause_bound_exceeded"])
        self.assertEqual(sum(row["type"] == "OSError" for row in result["causes"]), 1)

    @unittest.skipUnless(sys.platform == "win32", "Windows native metadata handle control")
    def test_python_metadata_reads_only_public_source_attributes_and_closes(self):
        module = self.load_caller(native=True)
        result = module.MetadataWin32().file_metadata(str(SOURCE))
        self.assertEqual(result["eof"], SOURCE.stat().st_size)
        self.assertGreaterEqual(result["allocation"], result["eof"])
        self.assertFalse(result["directory"])
        self.assertFalse(result["delete_pending"])

    def test_python_metadata_ntfs_and_usn_buffers_and_inactive_code_are_exact(self):
        import ctypes
        from unittest import mock
        module = self.load_caller()
        api = object.__new__(module.MetadataWin32)
        api.create = mock.Mock(return_value=17)
        api.close = mock.Mock(return_value=True)
        def volume(handle, label, label_size, serial, maximum, flags, filesystem, filesystem_size):
            self.assertEqual((label_size, filesystem_size), (261, 64))
            filesystem.value = "NTFS"
            serial._obj.value = 0x12345678
            return True
        def device(handle, code, input_buffer, input_size, output, output_size, count, overlapped):
            self.assertEqual((input_buffer, input_size, overlapped), (None, 0, None))
            if code == 0x00090064:
                self.assertEqual(output_size, 96)
                count._obj.value = 96
                return True
            self.assertEqual((code, output_size), (0x000900f4, 80))
            module.ctypes.set_last_error(1179)
            return False
        api.volume = volume
        api.device = device
        result = api.ntfs_e()
        self.assertFalse(result["usn_active"])
        self.assertEqual(result["usn_query_error"], 1179)
        self.assertEqual(result["volume_serial"], "12345678")
        api.create.assert_called_once_with(r"\\.\E:", 0x80000000, 3, None, 3, 0, None)
        api.close.assert_called_once_with(17)

    def test_retired_runtime_custody_cannot_reuse_its_old_path_claims(self):
        from unittest import mock
        module = self.load_caller()
        custody = object.__new__(module.RuntimeCustody)
        custody.retired = True
        custody.handles = []
        custody.paths = {SOURCE}
        custody.create = mock.Mock(side_effect=AssertionError("native reopen tripwire"))
        with self.assertRaises(ValueError):
            custody.hold(SOURCE)
        custody.create.assert_not_called()

    def test_runtime_close_failure_fanout_is_bounded_before_append(self):
        from unittest import mock
        module = self.load_caller()
        custody = object.__new__(module.RuntimeCustody)
        custody.retired = False
        custody.handles = list(range(1, 34))
        custody.paths = set()
        custody.close_causes = []
        custody.close = mock.Mock(side_effect=OSError("controlled closure failure"))
        result = custody.retire()
        self.assertLessEqual(len(result), 16)
        self.assertEqual(custody.close_failure_count, 33)
        self.assertTrue(custody.close_cause_bound_exceeded)
        self.assertEqual(custody.close.call_count, 33)
        self.assertEqual(custody.handles, [])

    def test_persistence_facts_survive_later_retirement_and_clock_failures(self):
        import hashlib
        from types import SimpleNamespace
        from unittest import mock
        module = self.load_caller()
        for role in ("retirement", "clock"):
            with self.subTest(role=role):
                clock = b"next(ticks)" if role == "clock" else b"1000"
                code = b'''METADATA_EXECUTABLE = r"C:\\Python314\\python.exe"
ticks=iter((1000,))
class WindowsObservation:
 def tick(self): return ''' + clock + b'''
def load_reviewed_job_definitions(raw): return object
def capture_literal(**kw): return {"facts":{"complete":True},"private_channel_bytes":[b"metadata",b""],"private_primary":None,"private_secondary":()}
_QUARANTINED_READERS=[None,None]
'''
                sources = {"capture": code, "driver": b"d", "guard": b"g", "jobs": b"j"}
                admission = {"schema_version": 1, "scope": module.SCOPE, "planning_commit": "44e8cef19d70f555e2f37dd4ea07651bd9b8125f",
                    "reviewed_commit": "a" * 40, "entry_approval": 103, "independent_reviews": [101, 102],
                    "deadline_tick_ms": 31000, "boot_filetime": "123", "ordinary_sid": module.SID,
                    "source_pins": {name: {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()} for name, raw in sources.items()}}
                custody = SimpleNamespace(paths=set(module.SOURCE_PATHS.values()) | {Path(sys.executable)}, active=True,
                    retire=mock.Mock(side_effect=OSError("controlled retirement")) if role == "retirement" else mock.Mock(return_value=[]))
                box = {"capture": None, "document_original": None, "attestation": None}
                persisted = {"complete": True, "known_written_bytes": 317, "fsync_completed": True, "close_completed": True}
                with mock.patch.object(module, "qualify_parent", return_value={"boot_filetime": "123"}), \
                     mock.patch.object(module, "persist_witness", return_value=persisted), \
                     mock.patch.object(Path, "exists", return_value=False):
                    result = module.run_qualification(admission, sources, now_tick=1000, custody=custody, enclosing_result=box)
                self.assertIs(box["attestation"]["persistence"], persisted)
                self.assertFalse(result["attestation"]["qualification_accepted"])
                if role == "clock":
                    self.assertIsNone(result["attestation"]["deadline_exceeded_after_close"])
                    self.assertEqual(result["attestation"]["completion_failure"]["phase"], "completion_clock")
                else:
                    self.assertFalse(result["attestation"]["runtime_close_available"])
                    self.assertEqual(result["attestation"]["completion_failure"]["phase"], "runtime_retirement")

    def test_directory_custody_requests_real_list_access_before_claiming_custody(self):
        from unittest import mock
        module = self.load_caller()
        custody = object.__new__(module.RuntimeCustody)
        custody.retired = False
        custody.paths, custody.handles = set(), []
        before = ROOT.stat()
        custody.create = mock.Mock(return_value=17)
        custody.opened_identity = mock.Mock(return_value={"volume": before.st_dev, "file_index": before.st_ino,
            "attributes": 0x10, "bytes": before.st_size, "links": 1})
        custody.hold(ROOT, directory=True)
        self.assertEqual(custody.create.call_args.args[1:3], (0x20081, 3))

    def test_metadata_terminal_preserves_collection_after_encoding_write_and_flush_faults(self):
        import io
        module = self.load_caller()
        for role in ("encode", "write", "flush", "write_and_flush"):
            with self.subTest(role=role):
                original = {"complete": True, "records": [{"allocation": 8192}], "capacity_accepted": False}
                calls = [0]
                def encode(value, limit):
                    calls[0] += 1
                    if role == "encode" and calls[0] == 1:
                        raise OSError("controlled terminal encoding")
                    return module.bounded_json(value, limit)
                class Output(io.BytesIO):
                    def write(self, raw):
                        if role in ("write", "write_and_flush"):
                            raise OSError("controlled terminal write")
                        return super().write(raw)
                    def flush(self):
                        if role in ("flush", "write_and_flush"):
                            raise OSError("controlled terminal flush")
                        return super().flush()
                stdout, stderr = Output(), io.BytesIO()
                result = module.emit_metadata(31000, collect=lambda deadline: original, encode=encode,
                                              stdout=stdout, stderr=stderr)
                self.assertEqual(result["exit_code"], 1)
                self.assertIs(result["completed_collection"], original)
                self.assertTrue(result["fallback_completed"])
                fallback = json.loads(stderr.getvalue())
                self.assertEqual(fallback["completed_collection"], original)
                self.assertTrue(fallback["collection_returned"])
                expected = {"encode": ["encode"], "write": ["stdout_write"], "flush": ["stdout_flush"],
                            "write_and_flush": ["stdout_write", "stdout_flush"]}[role]
                self.assertEqual([row["phase"] for row in fallback["post_failures"]], expected)

    @unittest.skipUnless(sys.platform == "win32", "Windows directory sharing control")
    def test_real_directory_custody_denies_delete_access_with_a_working_baseline(self):
        import ctypes
        module = self.load_caller(native=True)
        directory = ROOT / "openspec/changes/fix-accepted-policy-preprocessing/evidence/grok-runtime-boundary-20261028-01"
        observer = module.RuntimeCustody()
        def delete_access_probe():
            handle = observer.create(str(directory), 0x10080, 7, None, 3, 0x02200000, None)
            if handle in (None, ctypes.c_void_p(-1).value):
                return False, ctypes.get_last_error()
            try:
                return True, observer.opened_identity(handle)
            finally:
                if not observer.close(handle):
                    raise ctypes.WinError(ctypes.get_last_error())
        baseline, baseline_identity = delete_access_probe()
        self.assertTrue(baseline, baseline_identity)
        observations = []
        for metadata_only in (True, False):
            holder = module.RuntimeCustody()
            native_create = holder.create
            if metadata_only:
                holder.create = lambda path, access, *args: native_create(path, 0x80, *args)
            try:
                holder.hold(directory, directory=True)
                opened, detail = delete_access_probe()
                observations.append({"metadata_only_counterfactual": metadata_only, "delete_access_opened": opened,
                                     "error": detail if not opened else None})
                self.assertEqual(opened, metadata_only)
                if not opened:
                    self.assertEqual(detail, 32)
            finally:
                errors = holder.retire()
            self.assertEqual(errors, [])
        print("CONTROLLED_DIRECTORY_SHARE_ACCESS", json.dumps({"baseline_identity": baseline_identity,
            "observations": observations, "directory_renamed": False, "directory_deleted": False}, separators=(",", ":")))

    def test_admission_identifiers_are_bounded_before_native_parent_entry(self):
        module = self.load_caller()
        base = {"schema_version": 1, "scope": module.SCOPE,
            "planning_commit": "44e8cef19d70f555e2f37dd4ea07651bd9b8125f", "reviewed_commit": "a" * 40,
            "entry_approval": 103, "independent_reviews": [101, 102], "deadline_tick_ms": 31000,
            "boot_filetime": "123", "ordinary_sid": module.SID,
            "source_pins": {name: {"bytes": 1, "sha256": "a" * 64} for name in module.SOURCE_PATHS}}
        for field, bad in (("entry_approval", 1 << 64), ("independent_reviews", [1 << 64, 102])):
            with self.subTest(field=field), self.assertRaises(ValueError):
                module.validate_admission({**base, field: bad}, 1000)



    def test_operator_finalizer_keeps_original_and_distinct_close_failure(self):
        import types
        path=ROOT/"openspec/changes/fix-accepted-policy-preprocessing/evidence/grok-runtime-boundary-20261028-01/grok_bounded_model_invocation_v1.proposed.ps1"
        self.assertTrue(path.is_file(),"fixed enclosing owner absent")
        raw=path.read_text().split("$Pr9ReadonlyController = @'\n",1)[1].split("\n'@",1)[0]
        ns={"__name__":"pr9_operator_control"}
        exec(compile(raw,"fixed-operator-control","exec"),ns)
        original=object(); first=OSError(); closing=RuntimeError()
        def run(a,b,**kw):
            kw["enclosing_result"]["capture"]=original
            raise first
        owner=types.SimpleNamespace(handles=[1],retired=False)
        def retire():
            owner.handles.pop(); owner.retired=True
            raise closing
        owner.retire=retire
        driver=types.SimpleNamespace(run_qualification=run)
        state=ns["own_qualification"](driver,{}, {},owner,lambda:1)
        self.assertIs(state["box"]["capture"],original)
        self.assertIs(state["errors"][0][1],first)
        self.assertIs(state["errors"][1][1],closing)
        self.assertEqual(state["remaining_runtime_handles"],0)

    def test_runtime_census_missing_or_bad_sources_refuse_before_io_and_import(self):
        from unittest import mock
        m=self.load_caller()
        run=getattr(m,"collect_runtime_census",None)
        self.assertTrue(callable(run),"census absent")
        p={name:{"bytes":1,"sha256":"a"*64} for name in m.SOURCE_PATHS}
        for bad in (None,{},{**p,"driver":{"bytes":True,"sha256":"a"*64}},
                    {**p,"guard":{"bytes":65537,"sha256":"a"*64}},
                    {**p,"capture":{"bytes":1,"sha256":"private"}}):
            with self.subTest(value=bad),mock.patch.object(m.os,"open",side_effect=AssertionError("file")),\
                 mock.patch("builtins.__import__",side_effect=AssertionError("import")):
                with self.assertRaisesRegex(ValueError,"source"):
                    run(bad)

    def test_runtime_census_module_overflow_refuses_before_collection_io_and_import(self):
        import types
        from unittest import mock
        m=self.load_caller()
        run=getattr(m,"collect_runtime_census",None)
        self.assertTrue(callable(run),"census absent")
        class Modules:
            def __len__(self):return 513
            def __iter__(self):raise AssertionError("collect")
        p={name:{"bytes":1,"sha256":"a"*64} for name in m.SOURCE_PATHS}
        with mock.patch.object(m,"sys",types.SimpleNamespace(modules=Modules())),\
             mock.patch.object(m.os,"open",side_effect=AssertionError("file")),\
             mock.patch("builtins.__import__",side_effect=AssertionError("import")):
            with self.assertRaisesRegex(ValueError,"m"):
                run(p)



if __name__=="__main__":
    unittest.main()
