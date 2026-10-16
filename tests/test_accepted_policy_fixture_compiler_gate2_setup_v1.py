"""Controlled setup-controller tests: never invoke Git, WSL, Docker or P0."""
import ast
import base64
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests.fixtures import accepted_policy_fixture_compiler_gate2_setup_v1 as setup


COMMIT = "a" * 40
BOOT = "12345678-1234-1234-1234-123456789abc"


def function(source, name, namespace):
    node = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == name)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), name, "exec"), namespace)
    return namespace[name]


class GateTests(unittest.TestCase):
    def world(self):
        now = [0]
        namespace = {"time": SimpleNamespace(monotonic_ns=lambda: now[0]),
                     "x": {"linux_deadline_ns": 150_000_000_000, "boot_id": BOOT},
                     "boot": lambda: BOOT, "floors": lambda liability: None}
        namespace["gate"] = function(setup.PRELUDE, "gate", namespace)
        return now, namespace

    def test_boot_floor_and_reserve_are_rechecked_after_observation(self):
        for observation in ("boot", "floors"):
            for late in (151_000_000_000, 20_000_000_000):
                with self.subTest(observation=observation, late=late):
                    now, world = self.world()
                    def observed(*args):
                        now[0] = late
                        return BOOT if observation == "boot" else None
                    world[observation] = observed
                    with self.assertRaises(AssertionError):
                        world["gate"](0, 132_000_000_000)

    def test_export_mutation_rechecks_deadline_after_floors(self):
        now = [0]
        def floors(_):
            now[0] = 11_000_000_000
        world = {"time": SimpleNamespace(monotonic_ns=lambda: now[0]),
                 "local_deadline": 10_000_000_000, "floors": floors}
        mutate = function(setup.EXPORT, "mutate_check", world)
        with self.assertRaises(AssertionError):
            mutate()

    def test_project_floor_refuses_before_first_export_allocation(self):
        now, world = self.world()
        allocations = []
        def floors(_):
            raise AssertionError("controlled project floor")
        world["floors"] = floors
        world["x"]["baseline"] = {"c_free_bytes": 70 * 1024 ** 3, "ext4_used_bytes": 1}
        world["ROOT"] = world["AUX"] = SimpleNamespace(mkdir=lambda **kwargs: allocations.append(kwargs))
        with self.assertRaises(AssertionError):
            exec(compile(setup.EXPORT[len(setup.PRELUDE):], "EXPORT", "exec"), world)
        self.assertEqual(allocations, [])

    def test_f2_late_module_or_code_validation_denies_native_dispatch(self):
        for stage in ("import", "code"):
            with self.subTest(stage=stage):
                now, world = self.world()
                called = []
                def verify(*args):
                    if stage == "code":
                        now[0] = 20_000_000_000
                c = SimpleNamespace(CODE_PATHS=(), _verify_code=verify)
                f = SimpleNamespace(recover_stopped_b1_v1=lambda **kwargs: called.append(kwargs))
                def modules():
                    if stage == "import":
                        now[0] = 20_000_000_000
                    return c, f
                world.update(modules=modules, ROOT=Path("/controlled"), growth=lambda *args: 0, measure=lambda: {})
                world["outside_funded"]=function(setup.PRELUDE,"outside_funded",world)
                world["x"].update(code={}, baseline={},outside_preexisting_quote=32768,aux_quote=setup.AUX_QUOTE)
                with self.assertRaises(AssertionError):
                    exec(compile(setup.RECOVER[len(setup.PRELUDE):], "RECOVER", "exec"), world)
                self.assertEqual(called, [])

    def test_floor_checks_actual_project_capacity_and_fragment(self):
        for fragment, available in ((8192, 10 ** 12), (4096, 1073741824 + 4096 - 1)):
            with self.subTest(fragment=fragment):
                stat = SimpleNamespace(f_frsize=fragment, f_bavail=available // fragment)
                world = {"os": SimpleNamespace(statvfs=lambda _: stat), "ROOT": SimpleNamespace(parent="/controlled"),
                         "measure": lambda: {"c_free_bytes": 70 * 1024 ** 3}}
                floors = function(setup.PRELUDE, "floors", world)
                with self.assertRaises(AssertionError):
                    floors(4096)


class WindowsBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, setup, "DEADLINE", setup.DEADLINE)
        setup.DEADLINE = 150_000_000_000
        self.now = [0]
        self.clock = patch.object(setup.time, "monotonic_ns", side_effect=lambda: self.now[0])
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def test_late_exported_import_and_late_p0_dispatch_do_not_call_collector(self):
        calls = []
        p0 = SimpleNamespace(collect_native_p0_v1=lambda *args, **kwargs: calls.append(kwargs))
        def load(_):
            self.now[0] = 110_000_000_000
        spec = SimpleNamespace(loader=SimpleNamespace(exec_module=load))
        with patch.object(setup.importlib.util, "spec_from_file_location", return_value=spec), \
                patch.object(setup.importlib.util, "module_from_spec", return_value=p0):
            with self.assertRaises(RuntimeError):
                setup._load_exported_p0_v1()
        with self.assertRaises(RuntimeError):
            setup._dispatch_p0_v1(p0, {})
        self.assertEqual(calls, [])

    def test_bytecode_is_suppressed_before_loader_executes(self):
        seen = []
        original = sys.dont_write_bytecode
        self.addCleanup(setattr, sys, "dont_write_bytecode", original)
        sys.dont_write_bytecode = False
        spec = SimpleNamespace(loader=SimpleNamespace(exec_module=lambda _: seen.append(sys.dont_write_bytecode)))
        p0 = SimpleNamespace()
        with patch.object(setup.importlib.util, "spec_from_file_location", return_value=spec), \
                patch.object(setup.importlib.util, "module_from_spec", return_value=p0):
            self.assertIs(setup._load_exported_p0_v1(), p0)
        self.assertEqual(seen, [True])

    def test_reviewed_commit_is_external_and_only_hex_can_derive_fixed_root(self):
        setup._configure_reviewed_commit_v1(COMMIT)
        self.assertEqual(setup.ROOT, "/home/s-a-balashov/work/vast-fixture-compiler-gate2-" + COMMIT + "-01")
        for commit in (None, "A" * 40, "b" * 39, "../escape", "b" * 41):
            with self.subTest(commit=commit), self.assertRaises(RuntimeError):
                setup._configure_reviewed_commit_v1(commit)


class HelperAuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.original_repo = setup.REPO
        self.addCleanup(setattr, setup, "REPO", self.original_repo)
        setup.REPO = str(self.root)
        setup._configure_reviewed_commit_v1(COMMIT)
        self.raws, self.descriptors = {}, {}
        for name in (setup.SETUP_REL, setup.CAPTURE_REL):
            raw = ("# controlled " + name + "\n").encode()
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
            self.raws[name] = raw
            self.descriptors[name] = {"path": str(path), "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "git_blob": blob}

    def git(self, args, cap=262144):
        if args[0] == "rev-parse":
            return (COMMIT + "\n").encode()
        if args[0] == "ls-tree":
            return b"".join(("100644 blob " + self.descriptors[name]["git_blob"] + "\t" + name + "\0").encode()
                            for name in (setup.SETUP_REL, setup.CAPTURE_REL))
        if args[0] == "cat-file":
            return next(self.raws[name] for name, d in self.descriptors.items() if d["git_blob"] == args[-1])
        raise AssertionError(args)

    def test_exact_head_two_git_blobs_local_bytes_and_header_descriptors(self):
        with patch.object(setup, "git", side_effect=self.git):
            self.assertEqual(setup._authenticate_helper_code_v1(self.descriptors), self.descriptors)

    def test_foreign_head_header_hash_and_changed_local_source_refuse(self):
        for changed in ("head", "header", "local"):
            with self.subTest(changed=changed):
                desc = json.loads(json.dumps(self.descriptors))
                if changed == "header":
                    desc[setup.SETUP_REL]["sha256"] = "0" * 64
                if changed == "local":
                    (self.root / setup.CAPTURE_REL).write_bytes(b"# changed\n")
                def git(args, cap=262144):
                    if changed == "head" and args[0] == "rev-parse":
                        return ("f" * 40 + "\n").encode()
                    return self.git(args, cap)
                with patch.object(setup, "git", side_effect=git), self.assertRaises(RuntimeError):
                    setup._authenticate_helper_code_v1(desc)
                (self.root / setup.CAPTURE_REL).write_bytes(self.raws[setup.CAPTURE_REL])


class AccountingTests(unittest.TestCase):
    def test_actual_setup_growth_copy_liabilities_and_final_tail_are_binding(self):
        world = {}
        requirement = function(setup.PRELUDE, "funded_requirement", world)
        baseline = {"c_free_bytes": 70 * 1024 ** 3, "ext4_used_bytes": 1000}
        after = {"c_free_bytes": baseline["c_free_bytes"] - 100000, "ext4_used_bytes": 101000}
        value = requirement(baseline, after, 200000, 4000000, 100000, 540672)
        self.assertEqual(value, 11890688 + 1048576 + 1048576 + 4000000 + 524288 + 540672)
        advanced = dict(after, c_free_bytes=baseline["c_free_bytes"] - 10000000)
        self.assertGreater(requirement(baseline, advanced, 200000, 4000000, 100000, 540672), value + 65536)
        outside = function(setup.PRELUDE, "outside_funded", {})
        outside(100000, 100000, 131072)
        with self.assertRaises(AssertionError):
            outside(400000, 100000, 131072)
        check = function(setup.PRELUDE, "assert_funded", {})
        with self.assertRaises(AssertionError):
            check(value + 65537, value + 65536)

    def test_finite_aux_quote_includes_every_retained_control_and_outer_tail(self):
        expected=4352+sum(((n+4095)//4096)*4096+256 for n in setup.AUX_CAPS.values())
        self.assertEqual(setup.AUX_QUOTE,expected)
        self.assertEqual(len(setup.AUX_CAPS),13)
        outside=function(setup.PRELUDE,"outside_funded",{})
        outside(180224,49152,setup.AUX_QUOTE+32768)
        with self.assertRaises(AssertionError):
            outside(400000,49152,setup.AUX_QUOTE+32768)


class FailureFactsTests(unittest.TestCase):
    def test_combined_large_core_facts_and_git_prefixes_fit_funded_failure_protocol(self):
        out=b"a"*262144; err=b"b"*131072
        observed={"stdout":[len(out),hashlib.sha256(out)],"stderr":[len(err),hashlib.sha256(err)]}
        event={"argv_sha256":"a"*64,"stdout_eof":True,"stderr_eof":False,"overflow":False}
        prefixes=setup.failed_prefixes_v1({"stdout":out,"stderr":err},event,observed)
        for name,raw in (("stdout",out),("stderr",err)):
            self.assertEqual(prefixes["streams"][name]["observed_bytes"],len(raw))
            self.assertEqual(prefixes["streams"][name]["observed_sha256"],setup.sha(raw))
            self.assertEqual(prefixes["streams"][name]["retained_bytes"],4096)
            self.assertTrue(prefixes["streams"][name]["discarded"])
        error=RuntimeError("controlled combined fault")
        error.causes=["write_OSError","close_OSError"]
        error.facts={"large":"x"*65536,"failed_record":{"pid":71,"returncode":None,"extent_unknown":True,
            "close_completed":False,"causes":error.causes}}
        processes=[{"pid":n+1,"returncode":0,"stdout_eof":True,"stderr_eof":True,"late":False,"unknown_closure":False}
                   for n in range(28)]
        with patch.object(setup,"FAILED_PREFIXES",prefixes),patch.object(setup,"EVENTS",processes):
            result=setup.failure_document_v1(error)
        self.assertLessEqual(len(setup.canonical(result))+1,32768)
        self.assertEqual(result["exception"]["causes"],error.causes)
        self.assertTrue(result["exception"]["facts_remainder_unknown"])
        self.assertIn({"path":"/failed_record","facts":error.facts["failed_record"]},result["exception"]["known_facts"])
        self.assertEqual(result["known_processes"],processes)
        self.assertEqual(setup.CAPTURE_RESERVE,65536)

    def test_oversized_native_p0_and_f2_actual_schema_flags_remain_in_compact_projection(self):
        p0={"pid":73,"returncode":None,"normal_exit":False,"forced_parent_termination":True,
            "parent_termination_proves_linux_child_closure":False,"linux_child_closure":"unknown",
            "eof_stdout":False,"eof_stderr":True}
        f2={"write_extent_unknown":True,"request_write_extent_unknown":False,"reply_write_extent_unknown":True,
            "written_bytes":17,"persisted_bytes":0,"flush_completed":False,"close_completed":False}
        error=RuntimeError("mixed native failures"); error.causes=["deadline","close_failed"]
        error.facts={"large":"x"*65536,"p0":p0,"f2":f2}
        result=setup.exception_detail_v1(error)
        rows={row["path"]:row["facts"] for row in result["known_facts"]}
        self.assertEqual(rows["/p0"],p0)
        self.assertEqual(rows["/f2"],f2)
        self.assertFalse(result["known_facts_remainder_unknown"])
        self.assertTrue(result["facts_remainder_unknown"])

    def test_writer_keeps_first_failure_close_secondary_and_unknown_write_extent(self):
        for initial in ("write","fsync"):
            with self.subTest(initial=initial):
                class File:
                    def write(self,raw):
                        if initial=="write": raise OSError("write first")
                        return len(raw)
                    def flush(self): pass
                    def fileno(self): return 9
                    def close(self): raise OSError("close second")
                p=SimpleNamespace(open=lambda mode,**kwargs:File())
                def fsync(fd):
                    if initial=="fsync": raise OSError("fsync first")
                with self.assertRaises(OSError) as caught:
                    setup.owned_write_v1(p,b"abc",lambda:None,fsync)
                facts=caught.exception.facts
                self.assertEqual(facts["causes"],[initial+"_OSError","close_OSError"])
                self.assertFalse(facts["close_completed"])
                self.assertEqual(facts["extent_unknown"],initial=="write")
                world={}
                embedded=function(setup.EXPORT,"owned_write_v1",world)
                with self.assertRaises(OSError) as exported:
                    embedded(p,b"abc",lambda:None,fsync)
                self.assertEqual(exported.exception.facts,facts)

    def test_writer_requires_unbuffered_file_before_claiming_known_write_extent(self):
        opened=[]
        class File:
            def write(self,raw): return len(raw)
            def flush(self): pass
            def fileno(self): return 7
            def close(self): pass
        def opening(mode,**kwargs):
            opened.append((mode,kwargs)); return File()
        setup.owned_write_v1(SimpleNamespace(open=opening),b"actualprefix",lambda:None,lambda fd:None)
        self.assertEqual(opened,[("xb",{"buffering":0})])

    def test_authority_builder_binds_actual_helper_descriptors_and_inherited_context(self):
        context={"bounded":"actual inherited context"}
        value=setup.authority_record_v1(code_commit=COMMIT,approval_reference="approved",operator_sha256="a"*64,
            helper_code={"fixed":"descriptors"},context_sha256=setup.sha(setup.canonical(context)),context=context)
        self.assertEqual(value,{"schema_version":1,"code_commit":COMMIT,"approval_reference":"approved",
            "operator_sha256":"a"*64,"helper_code":{"fixed":"descriptors"},"context_sha256":setup.sha(setup.canonical(context)),
            "context":context,"external_approval_required":True})

    def test_core_failure_without_failure_file_preserves_causes_and_unknown_write_facts(self):
        error=RuntimeError("record close failed")
        error.causes=["deadline","close_failed"]
        error.facts={"failed_record":{"written_bytes":17,"extent_unknown":True,"close_completed":False},
                     "causes":error.causes,"failure_record_persisted":False}
        observed=setup.exception_detail_v1(error)
        self.assertEqual(observed["facts"],error.facts)
        self.assertEqual(observed["causes"],error.causes)
        sink=io.BytesIO()
        world={"sys":SimpleNamespace(stderr=SimpleNamespace(buffer=sink)),"canon":setup.canonical,
               "sha":setup.sha,"base64":base64,"exception_detail_v1":setup.exception_detail_v1}
        function(setup.PRELUDE,"failed",world)(type(error),error,None)
        self.assertEqual(json.loads(sink.getvalue())["facts"],error.facts)


class PipelineTests(unittest.TestCase):
    """Execute main and the real embedded phase bodies in an owned filesystem.

    Git/WSL/native F2/native P0 are the substituted boundaries. The export,
    control persistence, packet bindings, cap arithmetic and orchestration are
    the actual controller code, never a second implementation of its pipeline.
    """
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name); self.repo=self.base/"repo"; self.repo.mkdir()
        self.root=self.base/("gate2-"+COMMIT+"-01"); self.aux=Path(str(self.root)+".operator-originals")
        self.f2=Path(str(self.root)+".f2"); self.broot=self.base/"old-b"; self.broot.mkdir()
        self.now=[1_000_000_000]; self.start=self.now[0]; self.calls=[]; self.effects=[]
        self.fail=None; self.code_raw={name:("# controlled "+name+"\n").encode() for name in setup.CODE}
        self.code_raw[setup.PLAN]=b"# controlled reviewed V8\n"
        self.helpers={}
        for name in (setup.SETUP_REL,setup.CAPTURE_REL):
            p=self.repo/name; p.parent.mkdir(parents=True,exist_ok=True)
            raw=("# fixed controlled helper "+name+"\n").encode(); p.write_bytes(raw)
            self.helpers[name]=self.desc(p,raw,blob=True)
        self.rows={name:self.blob(raw) for name,raw in self.code_raw.items()}
        self.header={"schema_version":1,"code_commit":COMMIT,"windows_start_ns":self.start,
            "windows_deadline_ns":self.start+150_000_000_000,"linux_start_ns":self.start,
            "linux_deadline_ns":self.start+150_000_000_000,"baseline":{"c_free_bytes":70*1024**3,"ext4_used_bytes":1000000},
            "boot_id":BOOT,"capture_source_sha256":self.helpers[setup.CAPTURE_REL]["sha256"],
            "capture_source_quote_bytes":8192,"operator_source_quote_bytes":8192,
            "helper_git_forms_quote_bytes":16384,"capture_all_forms_reserved_bytes":65536,"helper_code":self.helpers,
            "pre_meter_native":{"pid":42,"returncode":0,"stdout_eof":True,"stderr_eof":True,
                                "stdout_sha256":"a"*64,"stderr_sha256":setup.sha(b"")}}
        self.result_packet=None; self.p0_kwargs=None; self.f2_kwargs=None
        # Function-like ctypes callable supports its restype attribute.
        def command(): return "python -I -S -B setup.py "+COMMIT+" approved"
        self.command=command
        self.stack=contextlib.ExitStack(); self.addCleanup(self.stack.close)
        def patched(obj,name,value): self.stack.enter_context(patch.object(obj,name,value))
        patched(setup,"REPO",str(self.repo)); patched(setup,"__file__",str(self.repo/setup.SETUP_REL))
        patched(setup,"BROOT",str(self.broot)); patched(setup,"EVENTS",[]); patched(setup,"DEADLINE",None)
        patched(setup.time,"monotonic_ns",lambda:self.now[0])
        patched(setup,"os",SimpleNamespace(name="nt",environ={setup.CONTEXT_ENV:setup.canonical(self.header).decode()},fsync=os.fsync,fstat=os.fstat))
        patched(setup,"ctypes",SimpleNamespace(c_wchar_p=object,windll=SimpleNamespace(kernel32=SimpleNamespace(GetCommandLineW=command))))
        original_config=setup._configure_reviewed_commit_v1
        def configure(commit):
            original_config(commit)
            setup.ROOT=str(self.root); setup.F2ROOT=str(self.f2); setup.AUX=str(self.aux)
            setup.UNC=str(self.root); setup.UNC_AUX=str(self.aux)
        patched(setup,"_configure_reviewed_commit_v1",configure)
        patched(setup,"fixed_process",self.process)
        patched(setup.sys,"argv",[str(self.repo/setup.SETUP_REL),COMMIT,"https://github.com/lordcoudy/VAST/pull/9#issuecomment-123"])
        self.stdout=io.BytesIO(); patched(setup.sys,"stdout",SimpleNamespace(buffer=self.stdout))
        p0=SimpleNamespace(collect_native_p0_v1=self.collect_p0)
        spec=SimpleNamespace(loader=SimpleNamespace(exec_module=lambda module:self.effects.append("p0-import")))
        patched(setup.importlib.util,"spec_from_file_location",lambda name,path:spec)
        patched(setup.importlib.util,"module_from_spec",lambda spec:p0)
        self.addCleanup(setattr,sys,"path",list(sys.path))

    @staticmethod
    def blob(raw): return hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()

    def desc(self,path,raw=None,blob=False):
        raw=path.read_bytes() if raw is None else raw
        value={"path":str(path),"size_bytes":len(raw),"sha256":setup.sha(raw)}
        if blob: value["git_blob"]=self.blob(raw)
        return value

    def read(self,path,cap):
        raw=Path(path).read_bytes(); self.assertLessEqual(len(raw),cap); return raw

    def write_record(self,path,value,cap,absolute_deadline_ns,return_facts):
        self.assertLess(self.now[0],absolute_deadline_ns)
        raw=setup.canonical(value); self.assertLessEqual(len(raw),cap)
        with path.open("xb") as file: file.write(raw); file.flush(); os.fsync(file.fileno())
        return {"descriptor":self.desc(path,raw),"write_facts":{"complete":True,"close_completed":True}}

    def bound(self,desc,root,cap):
        p=Path(desc["path"]); self.assertTrue(p.is_relative_to(root))
        raw=self.read(p,cap); self.assertEqual(self.desc(p,raw),desc); return raw

    def verify_code(self,root,code):
        for name,d in code.items():
            self.assertEqual(setup.sha((root/name).read_bytes()),d["sha256"])

    def recover(self,**kwargs):
        self.effects.append("native-f2"); self.f2_kwargs=kwargs
        if self.fail=="f2":
            error=RuntimeError("controlled deadline")
            error.facts={"causes":["deadline"],"failed_record":{"extent_unknown":True},"failure_record_persisted":False}
            raise error
        self.f2.mkdir()
        account={"reserved_control_bytes":524288,"reserved_rounding_bytes":8192,"reserved_metadata_bytes":8192,
                 "physical_charge_bytes":2000000,"last":dict(self.header["baseline"])}
        supplement={"controlled":False,"identity":{"before":{"engine_id":"1e493309-3767-45fb-9078-05b838bdfd80"},
                       "after":{"engine_id":"1e493309-3767-45fb-9078-05b838bdfd80"}}}
        for name,value in (("f2.supplement.v1.json",supplement),("f2.final-accounting.v1.json",{"accounting":account}),
                           ("f2.originals.v1.json",{"originals":[]})):
            (self.f2/name).write_bytes(setup.canonical(value))
        return {"supplement":supplement,"supplement_descriptor":self.desc(self.f2/"f2.supplement.v1.json"),
                "final_accounting_descriptor":self.desc(self.f2/"f2.final-accounting.v1.json")}

    def collect_p0(self,output,binding,**kwargs):
        self.effects.append("native-p0"); self.p0_kwargs=(output,binding,kwargs)
        self.assertTrue(sys.dont_write_bytecode)
        if self.fail=="p0":
            error=RuntimeError("P0 unknown")
            error.facts={"causes":["stdout_eof_unknown"],"completion_record_persisted":False}
            raise error
        p=Path(output); p.mkdir(); raw=b'{"fixed":"completion"}'
        (p/"p0-completion.v1.json").write_bytes(raw)
        complete={"encoded_bytes":len(raw),"sha256":setup.sha(raw),"write_proof":{
            "open_completed":True,"fsync_completed":True,"close_completed":True,"completed":True,
            "late":False,"extent_unknown":False,"written_bytes":len(raw),"prefix_sha256":setup.sha(raw)}}
        result={"accepted":True,"causes":[],"controlled":False,"physical_acceptance":False,"completion_record":complete}
        if self.fail=="p0-late": self.now[0]=self.header["windows_deadline_ns"]+1
        if self.fail=="p0-refused": result.update(accepted=False,causes=["close_failed","unknown_extent"])
        return result

    def build_packet(self,**kwargs):
        self.effects.append("packet-build")
        authority=self.aux/"operator.authority.original.json"
        self.assertEqual(kwargs["review"]["evidence_sha256"],setup.sha(authority.read_bytes()))
        self.assertEqual(kwargs["review"]["commit"],COMMIT)
        self.result_packet={"initial_charged_bytes":kwargs["initial_charged_bytes"],"seed":{"fixed":True},"review":kwargs["review"]}
        return self.result_packet

    def process(self,argv,payload=b"",cap=12288):
        event={"argv_sha256":setup.sha(setup.canonical(argv)),"stdin_sha256":setup.sha(payload),"pid":73,"returncode":0,
               "stdout_eof":True,"stderr_eof":True,"late":False,"unknown_closure":False}
        setup.EVENTS.append(event)
        if argv[0]==setup.GIT:
            args=argv[argv.index("core.fsmonitor=false")+1:]
            if args[0]=="rev-parse": raw=(COMMIT+"\n").encode()
            elif args[0]=="ls-tree":
                names=args[args.index("--")+1:]
                rows={name:self.helpers[name]["git_blob"] if name in self.helpers else self.rows[name] for name in names}
                raw=b"".join(("100644 blob "+blob+"\t"+name+"\0").encode() for name,blob in rows.items())
            else:
                blob=args[-1]
                all_raw={self.blob(raw):raw for raw in self.code_raw.values()}
                all_raw.update({d["git_blob"]:Path(d["path"]).read_bytes() for d in self.helpers.values()})
                raw=all_raw[blob]
        else:
            source=argv[-1]; phase=next(name for name in ("EXPORT","RECOVER","P0_GATE","PACKET","FINAL") if source==getattr(setup,name))
            self.calls.append(phase); x=json.loads(payload)
            self.assertEqual(x["code_commit"],COMMIT)
            self.assertEqual(x["linux_deadline_ns"],self.header["linux_deadline_ns"])
            c=SimpleNamespace(CODE_PATHS=setup.CODE,_verify_code=self.verify_code,
                _b2_index_value=lambda root:{"controlled_index":True},write_record_v1=self.write_record,
                _read=self.read,_bound_descriptor=self.bound,build_packet_v1=self.build_packet,
                interval_charge_v1=lambda *args,**kwargs:0)
            f=SimpleNamespace(recover_stopped_b1_v1=self.recover,
                validate_supplement_v1=lambda **kwargs:{"complete":True},
                _outside_copy_lower_bound=lambda root:600000 if self.fail=="copies" else 49152)
            world={"x":x,"time":SimpleNamespace(monotonic_ns=lambda:self.now[0]),"ROOT":self.root,"F2ROOT":self.f2,
                "AUX":self.aux,"BROOT":self.broot,"COMMIT":COMMIT,"base64":base64,"hashlib":hashlib,"json":json,
                "os":os,"Path":Path,"boot":lambda:BOOT,"modules":lambda:(c,f),"floors":lambda liability:None,
                "measure":lambda:dict(self.header["baseline"]),"canon":setup.canonical,"sha":setup.sha,
                "allocated":lambda root:sum(((p.stat().st_size+4095)//4096)*4096+256 for p in root.rglob("*") if p.is_file())+4352}
            for name in ("owned_write_v1","growth","rounded","outside_funded","funded_requirement","assert_funded","gate"):
                function(setup.PRELUDE,name,world)
            emitted=[]; world["emit"]=lambda value:emitted.append(value)
            # Historical B originals are fixed input bytes in this controlled filesystem.
            if phase=="PACKET":
                for rel in ("outputs/B1/probe.result.original.json","outputs/B1/compiler.stdout.original",
                    "outputs/B2/probe.result.original.json","outputs/B2/compiler.stdout.original",
                    "outputs/B3/probe.result.original.json","runs/B2.originals.sha256"):
                    p=self.broot/rel; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(b"controlled original")
            exec(compile(source[len(setup.PRELUDE):],phase,"exec"),world)
            self.assertEqual(len(emitted),1); raw=setup.canonical(emitted[0])+b"\n"
            self.now[0]+=1_000_000_000
        self.assertLessEqual(len(raw),cap)
        event.update(stdout_bytes=len(raw),stderr_bytes=0,stdout_sha256=setup.sha(raw),stderr_sha256=setup.sha(b""))
        return raw,b""

    def test_complete_controlled_pipeline_binds_native_arguments_authority_and_funded_packet(self):
        setup.main()
        summary=json.loads(self.stdout.getvalue())
        self.assertEqual(self.calls,["EXPORT","RECOVER","P0_GATE","PACKET","FINAL"])
        self.assertEqual(self.effects,["native-f2","p0-import","native-p0","packet-build"])
        self.assertEqual(set(self.f2_kwargs),{"output_dir","review","b1_originals","remaining_seal_bytes","retained_elsewhere_upper_bytes"})
        self.assertEqual(self.f2_kwargs["retained_elsewhere_upper_bytes"],524288)
        self.assertEqual(self.p0_kwargs[2],{"reviewed_code_commit":COMMIT})
        self.assertEqual(self.p0_kwargs[1]["boot"]["boot_id"],BOOT)
        self.assertEqual(summary["context_sha256"],setup.sha(setup.canonical(self.header)))
        self.assertEqual(summary["packet"]["initial_charged_bytes"],summary["final_meter"]["funded_initial_charge_bytes"])
        self.assertFalse(summary["external_packet_approval"])
        self.assertFalse(summary["physical_acceptance"])
        self.assertLessEqual(len(self.stdout.getvalue()),8192)
        self.assertTrue((self.aux/"b2.corrected-index.v1.json").is_file())
        for path in self.aux.iterdir(): self.assertLessEqual(path.stat().st_size,setup.AUX_CAPS[path.name])

    def test_core_failure_cuts_later_work_and_retains_in_memory_facts_without_new_failure_file(self):
        self.fail="f2"
        with self.assertRaises(RuntimeError) as caught: setup.main()
        self.assertEqual(self.calls,["EXPORT","RECOVER"])
        self.assertEqual(setup.exception_detail_v1(caught.exception)["facts"]["failed_record"],{"extent_unknown":True})
        self.assertFalse((self.aux/"p0.return.original.json").exists())
        self.assertFalse((self.root/"gate2.packet.original.json").exists())

    def test_copy_liability_overflow_cuts_packet_write_and_final_acceptance(self):
        self.fail="copies"
        with self.assertRaises(AssertionError): setup.main()
        self.assertNotIn("packet-build",self.effects)
        self.assertFalse((self.root/"gate2.packet.original.json").exists())
        self.assertEqual(self.stdout.getvalue(),b"")

    def test_returned_p0_late_result_is_preserved_without_postdeadline_file(self):
        self.fail="p0-late"
        with self.assertRaises(RuntimeError) as caught: setup.main()
        actual=setup.exception_detail_v1(caught.exception)["facts"]["returned_p0"]
        self.assertTrue(actual["completion_record"]["write_proof"]["completed"])
        self.assertFalse((self.aux/"p0.return.original.json").exists())
        self.assertNotIn("PACKET",self.calls)

    def test_refused_p0_result_preserves_ordered_causes_and_completed_proof(self):
        self.fail="p0-refused"
        with self.assertRaises(RuntimeError) as caught: setup.main()
        actual=setup.exception_detail_v1(caught.exception)["facts"]["returned_p0"]
        self.assertEqual(actual["causes"],["close_failed","unknown_extent"])
        self.assertTrue(actual["completion_record"]["write_proof"]["close_completed"])
        self.assertNotIn("PACKET",self.calls)

    def test_context_wrong_git_quote_and_unfunded_sources_stop_before_export(self):
        self.header["helper_git_forms_quote_bytes"]+=1
        setup.os.environ[setup.CONTEXT_ENV]=setup.canonical(self.header).decode()
        with self.assertRaisesRegex(RuntimeError,"helper_git_forms_quote"): setup.main()
        self.assertEqual(self.calls,[])

    def test_original_deadline_and_header_source_hash_are_required_before_export(self):
        self.header["capture_source_sha256"]="0"*64
        setup.os.environ[setup.CONTEXT_ENV]=setup.canonical(self.header).decode()
        with self.assertRaisesRegex(RuntimeError,"capture_source_quote"): setup.main()
        self.assertEqual(self.calls,[])


if __name__ == "__main__":
    unittest.main()
