"""Controlled capture tests: no WSL, Docker, setup, F2, P0, C or D action."""
import hashlib
import base64
import copy
import io
import json
from pathlib import Path
import tempfile
import os
import stat
import sys
import types
import unittest
from unittest.mock import patch

from tests.fixtures import accepted_policy_fixture_compiler_gate2_capture_v1 as capture
from tests.fixtures import accepted_policy_fixture_compiler_gate2_setup_v1 as setup

COMMIT = "a" * 40
APPROVAL = "https://github.com/lordcoudy/VAST/pull/9#issuecomment-123456789"


class Pipe:
    def __init__(self, fd, *, close_error=False):
        self.fd, self.closed, self.close_error = fd, False, close_error
    def fileno(self):
        return self.fd
    def close(self):
        self.closed = True
        if self.close_error:
            raise OSError("controlled pipe close")


class Process:
    pid = 1234
    def __init__(self, code=0, *, close_error=False):
        self.code = code
        self.stdout, self.stderr = Pipe(101, close_error=close_error), Pipe(102)
    def poll(self):
        return self.code
    def terminate(self):
        raise AssertionError("no forced termination")
    def kill(self):
        raise AssertionError("no forced termination")


class ControlledCaptureTests(unittest.TestCase):
    def setUp(self):
        self.clock = [100]
        self.patches = [patch.object(capture,"START",100), patch.object(capture,"DEADLINE",10_000_000_000),
            patch.object(capture,"CAPTURE_END",None),
            patch.object(capture.time,"monotonic_ns",side_effect=lambda:self.clock[0])]
        for item in self.patches:
            item.start(); self.addCleanup(item.stop)

    def drain(self, stdout, stderr=b"", *, code=0, limits=None, files=None, close_error=False):
        data={101:io.BytesIO(stdout),102:io.BytesIO(stderr)}
        process=Process(code,close_error=close_error)
        with patch.object(capture.os,"read",side_effect=lambda fd,n:data[fd].read(n)):
            return capture.drain(process,limits=limits or {"stdout":12288,"stderr":393216},files=files)

    def test_native_status_and_both_eof_are_actual_facts(self):
        state,streams=self.drain(b"literal\x00stdout",b"literal stderr")
        self.assertEqual(state["pid"],1234)
        self.assertEqual(state["returncode"],0)
        self.assertTrue(state["stdout_eof"] and state["stderr_eof"])
        self.assertFalse(state["unknown_closure"])
        self.assertEqual(streams,{"stdout":b"literal\x00stdout","stderr":b"literal stderr"})
        self.assertEqual(state["stdout"]["sha256"],hashlib.sha256(streams["stdout"]).hexdigest())

    def test_nonzero_status_remains_nonzero_after_complete_eof(self):
        state,_=self.drain(b"",b"native failure",code=7)
        self.assertEqual(state["returncode"],7)
        self.assertFalse(state["unknown_closure"])
        self.assertTrue(state["stderr_eof"])

    def test_overflow_preserves_only_exact_cap_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            files={name:(root/name).open("xb",buffering=0) for name in ("stdout","stderr")}
            try:
                state,_=self.drain(b"abcdef",limits={"stdout":4,"stderr":8},files=files)
            finally:
                for file in files.values(): file.close()
            self.assertEqual((root/"stdout").read_bytes(),b"abcd")
            self.assertEqual(state["stdout"]["kept_bytes"],4)
            self.assertTrue(state["causes"])
            self.assertFalse(state["stdout_eof"])

    def test_pipe_close_failure_cannot_be_a_success(self):
        state,_=self.drain(b"",close_error=True)
        self.assertTrue(state["causes"])

    def test_unknown_os_return_is_never_replaced_with_zero(self):
        def advance():
            self.clock[0]+=1_000_000_000
            return self.clock[0]
        with patch.object(capture.time,"monotonic_ns",side_effect=advance), patch.object(capture.time,"sleep"):
            state,_=self.drain(b"",code=None)
        self.assertIsNone(state["returncode"])
        self.assertTrue(state["late"] and state["unknown_closure"])

    def test_shared_context_deadline_is_not_reset_for_later_io(self):
        with patch.object(capture,"CAPTURE_END",200):
            self.clock[0]=201
            with self.assertRaises(capture.CaptureRefusal): capture.check()

    def test_late_native_read_never_writes_unreturned_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); files={name:(root/name).open("xb",buffering=0) for name in ("stdout","stderr")}
            def late(fd,n):
                if fd==101: self.clock[0]=10_000_000_000; return b"late exact bytes"
                return b""
            try:
                with patch.object(capture.os,"read",side_effect=late):
                    state,_=capture.drain(Process(),limits={"stdout":12288,"stderr":393216},files=files)
            finally:
                for file in files.values(): file.close()
            self.assertEqual((root/"stdout").read_bytes(),b"")
            self.assertEqual(state["stdout"]["kept_bytes"],0)
            self.assertTrue(state["late"])
            self.assertTrue(state["causes"])

    def test_raw_fsync_failure_retains_separate_close_and_failure_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            files={name:(root/name).open("xb",buffering=0) for name in ("stdout","stderr")}
            state,_=self.drain(b"literal",files=files)
            with patch.object(capture.os,"fsync",side_effect=OSError("controlled fsync")):
                with self.assertRaises(capture.CaptureRefusal): capture.persist_raw_v1(files,state)
            self.assertFalse(state["stdout"]["fsync_completed"])
            self.assertTrue(state["stdout"]["close_completed"])
            self.assertTrue(any("fsync" in value for value in state["stdout"]["failures"]))
            self.assertEqual((root/"stdout").read_bytes(),b"literal")

    def test_fixed_meter_actual_pipe_input_status_and_output_are_bound(self):
        value={"bounded_controlled_meter":True}; raw=capture.canonical(value)+b"\n"
        streams={101:io.BytesIO(raw),102:io.BytesIO(b"")}; sent=bytearray()
        process=Process(); process.stdin=Pipe(103)
        def spawn(argv,**kwargs):
            self.assertEqual(argv[:12],[capture.WSL,"-d","Ubuntu","-u","s-a-balashov","--cd","/","--exec","/usr/bin/python3","-I","-S","-B"])
            self.assertEqual(argv[-1],capture.PRE_METER.replace("__REVIEWED_COMMIT__",COMMIT))
            self.assertFalse(kwargs["shell"])
            return process
        def write(fd,block):
            self.assertEqual(fd,103); sent.extend(block); return len(block)
        with patch.object(capture,"COMMIT",COMMIT),patch.object(capture,"FACTS",{}), \
             patch.object(capture.subprocess,"Popen",side_effect=spawn), \
             patch.object(capture.os,"read",side_effect=lambda fd,n:streams[fd].read(n)),patch.object(capture.os,"write",side_effect=write):
            actual,state=capture.meter(after=False,payload={"helper_code":{}})
        self.assertEqual(actual,value)
        self.assertEqual(bytes(sent),capture.canonical({"helper_code":{}}))
        self.assertEqual(state["stdin_sha256"],capture.sha(bytes(sent)))
        self.assertTrue(state["stdin_closed"] and state["stdout_eof"] and state["stderr_eof"])
        self.assertEqual(state["pid"],1234)
        self.assertNotIn("argv",state)

    def test_meter_popen_late_return_keeps_known_pid_and_never_restarts_window(self):
        process=Process(); process.stdin=Pipe(103)
        def spawn(*args,**kwargs): self.clock[0]=10_000_000_000; return process
        with patch.object(capture,"COMMIT",COMMIT),patch.object(capture,"FACTS",{}), \
             patch.object(capture.subprocess,"Popen",side_effect=spawn) as call:
            with self.assertRaises(capture.CaptureRefusal): capture.meter(after=False,payload={"helper_code":{}})
            state=capture.FACTS["pre_meter"]
            self.assertEqual(call.call_count,1)
            self.assertEqual(state["pid"],1234)
            self.assertTrue(state["late"])
            self.assertTrue(state["unknown_closure"])
            self.assertFalse(state["stdout_eof"])


class ReviewedSourceTests(unittest.TestCase):
    def test_failed_git_native_preserves_pid_status_eof_and_exact_prefixes_in_exception(self):
        streams={101:io.BytesIO(b"known git stdout\x00"),102:io.BytesIO(b"known git stderr")}
        with patch.object(capture,"DEADLINE",10**30),patch.object(capture,"CAPTURE_END",None), \
             patch.object(capture,"FACTS",{}),patch.object(capture.subprocess,"Popen",return_value=Process(7)), \
             patch.object(capture.os,"read",side_effect=lambda fd,n:streams[fd].read(n)):
            with self.assertRaises(capture.CaptureRefusal) as refused:
                capture.git_v1(["rev-parse","--verify","HEAD"],64)
            facts=refused.exception.facts
            self.assertEqual(facts["native"]["pid"],1234)
            self.assertEqual(facts["native"]["returncode"],7)
            self.assertTrue(facts["native"]["stdout_eof"] and facts["native"]["stderr_eof"])
            self.assertEqual(facts["retained_prefixes_base64"]["stdout"],"a25vd24gZ2l0IHN0ZG91dAA=")
            self.assertEqual(capture.FACTS["git_failure"],facts)

    def test_git_start_exception_keeps_unknown_pid_and_start_facts_without_retry(self):
        with patch.object(capture,"DEADLINE",10**30),patch.object(capture,"CAPTURE_END",None), \
             patch.object(capture,"FACTS",{}),patch.object(capture.subprocess,"Popen",side_effect=OSError("controlled start")) as start:
            with self.assertRaises(capture.CaptureRefusal) as refused:
                capture.git_v1(["rev-parse","--verify","HEAD"],64)
            self.assertIsNone(refused.exception.facts["native"]["pid"])
            self.assertEqual(refused.exception.facts["native"]["start_exception"],"OSError")
            self.assertEqual(start.call_count,1)

    def test_large_failed_git_diagnostics_keep_bounded_exact_prefix_and_full_known_counts_hash(self):
        raw=b"A"*65536; err=b"B"*4096
        streams={101:io.BytesIO(raw),102:io.BytesIO(err)}
        with patch.object(capture,"DEADLINE",10**30),patch.object(capture,"CAPTURE_END",None), \
             patch.object(capture,"FACTS",{}),patch.object(capture.subprocess,"Popen",return_value=Process(7)), \
             patch.object(capture.os,"read",side_effect=lambda fd,n:streams[fd].read(n)):
            with self.assertRaises(capture.CaptureRefusal) as refused:
                capture.git_v1(["cat-file","blob","a"*40],65536)
            facts=refused.exception.facts
            self.assertEqual(base64.b64decode(facts["retained_prefixes_base64"]["stdout"]),raw[:4096])
            self.assertEqual(facts["diagnostic_prefixes"]["stdout"]["omitted_captured_bytes"],61440)
            self.assertEqual(facts["diagnostic_prefixes"]["stdout"]["known_captured_sha256"],capture.sha(raw))
            self.assertFalse(facts["diagnostic_prefixes"]["stdout"]["remainder_unknown"])
            self.assertLessEqual(len(capture.canonical(facts)),32768)
            encoded=capture.failure_summary_v1(refused.exception)
            self.assertLessEqual(len(encoded)+1,32768)
            self.assertEqual(json.loads(encoded)["facts"]["git_failure"],facts)

    def test_commit_and_approval_syntax_are_required_but_not_approval(self):
        capture.validate_arguments_v1(COMMIT,APPROVAL)
        for commit,approval in (("A"*40,APPROVAL),("a"*39,APPROVAL),(COMMIT,"https://example.com/")):
            with self.subTest(commit=commit,approval=approval), self.assertRaises(capture.CaptureRefusal):
                capture.validate_arguments_v1(commit,approval)

    def test_both_actual_helper_bytes_must_equal_reviewed_git_blobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve(); raws={}
            for relative in capture.HELPER_PATHS:
                path=root/relative; path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(("# "+relative+"\n").encode()); raws[relative]=path.read_bytes()
            blobs={name:hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest() for name,raw in raws.items()}
            calls=[]
            def git(args,cap):
                calls.append(args)
                if args[0]=="rev-parse": return (COMMIT+"\n").encode()
                if args[0]=="ls-tree": return b"".join(("100644 blob "+blobs[name]+"\t"+name).encode()+b"\0" for name in capture.HELPER_PATHS)
                return next(raw for name,raw in raws.items() if blobs[name]==args[-1])
            with patch.object(capture,"REPO",root), patch.object(capture,"git_v1",side_effect=git), \
                 patch.object(capture,"DEADLINE",10**30), patch.object(capture,"CAPTURE_END",None):
                result=capture.authenticate_helpers_v1(COMMIT)
                self.assertEqual(set(result),set(capture.HELPER_PATHS))
                self.assertEqual(len(calls),4)
                (root/capture.HELPER_PATHS[1]).write_bytes(b"changed actual helper")
                with self.assertRaises(capture.CaptureRefusal): capture.authenticate_helpers_v1(COMMIT)

    def test_wrong_git_head_stops_before_blob_reads(self):
        with patch.object(capture,"git_v1",return_value=("b"*40+"\n").encode()) as git:
            with self.assertRaises(capture.CaptureRefusal): capture.authenticate_helpers_v1(COMMIT)
        self.assertEqual(git.call_count,1)


class OrchestrationTests(unittest.TestCase):
    """Exercise the real Windows orchestration with only native effects mocked."""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()/"repo"; self.root.mkdir()
        self.output=self.root/"capture-outputs"; self.output.mkdir()
        self.helpers={}
        for name in capture.HELPER_PATHS:
            path=self.root/name; path.parent.mkdir(parents=True,exist_ok=True)
            raw=("# controlled "+name+"\n").encode(); path.write_bytes(raw)
            self.helpers[name]={"path":str(path),"size_bytes":len(raw),"sha256":capture.sha(raw),
                "git_blob":hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()}
        self.now=[100]
        self.pre={"baseline":{"c_free_bytes":100_000_000_000,"ext4_used_bytes":300_000_000_000},
            "boot_id":"12345678-1234-1234-1234-123456789abc","linux_monotonic_ns":1_000_000_000,
            "project_free_bytes":10_000_000_000,"capture_source_quote_bytes":16384,"operator_source_quote_bytes":16384,
            "helper_git_forms_quote_bytes":16384,
            "c_fragment_bytes":4096,"root_fragment_bytes":4096}
        self.post={"measurement":{"c_free_bytes":99_999_000_000,"ext4_used_bytes":300_001_000_000},
            "boot_id":self.pre["boot_id"],"linux_monotonic_ns":2_000_000_000,"project_free_bytes":9_000_000_000,
            "required_charge_bytes":30_000_000,"funded_initial_charge_bytes":40_000_000,"remaining_funded_bytes":10_000_000,
            "capture_all_forms_upper_bytes":32768,"root_allocated_bytes":700000,"f2_allocated_bytes":2_000_000,
            "outside_upper_bytes":400000,"status_and_one_copy_reserved_bytes":16384}
        self.summary_mutation=lambda value:value
        self.code=0; self.pipe_data={}; self.phases=[]; self.raw_stdout=None; self.raw_stderr=b""
        self.text_stdout=type("Output",(),{"buffer":io.BytesIO()})()
        self.patches=[patch.object(capture,"REPO",self.root),patch.object(capture,"TEMP",self.output),
            patch.object(capture,"__file__",str(self.root/capture.HELPER_PATHS[0])),
            patch.object(capture.sys,"platform","win32"),patch.object(capture.sys,"stdout",self.text_stdout),
            patch.object(capture.time,"monotonic_ns",side_effect=lambda:self.now[0]),
            patch.object(capture,"authenticate_helpers_v1",return_value=self.helpers),
            patch.object(capture,"meter",side_effect=self.meter),
            patch.object(capture.subprocess,"Popen",side_effect=self.spawn),
            patch.object(capture.os,"read",side_effect=lambda fd,n:self.pipe_data[fd].read(n))]
        for item in self.patches:
            item.start(); self.addCleanup(item.stop)

    def native(self,value):
        raw=capture.canonical(value)+b"\n"
        return {"pid":9876,"returncode":0,"stdout_eof":True,"stderr_eof":True,"stdin_closed":True,
            "late":False,"unknown_closure":False,"causes":[],"windows_start_ns":self.now[0],"argv_sha256":"1"*64,
            "stdin_sha256":"2"*64,"stdout":{"kept_bytes":len(raw),"sha256":capture.sha(raw)},
            "stderr":{"kept_bytes":0,"sha256":capture.sha(b"")}}

    def meter(self,*,after,payload):
        self.phases.append("post-meter" if after else "pre-meter")
        if after:
            for name in ("stdout","stderr"):
                self.assertTrue(capture.FACTS["driver"][name]["fsync_completed"])
                self.assertTrue(capture.FACTS["driver"][name]["close_completed"])
        else:
            self.assertEqual(list(self.output.iterdir()),[])
            self.assertEqual(payload,{"helper_code":self.helpers})
        value=copy.deepcopy(self.post if after else self.pre); native=self.native(value)
        capture.FACTS["post_meter" if after else "pre_meter"]=native
        return value,native

    def spawn(self,argv,**kwargs):
        self.phases.append("driver")
        self.assertEqual(argv,[capture.PYTHON,"-I","-S","-B",str(self.root/capture.HELPER_PATHS[1]),COMMIT,APPROVAL])
        context=capture.strict_json(kwargs["env"]["VAST_GATE2_CAPTURE_CONTEXT_V1"].encode(),4096)
        self.context=context
        packet={"path":"/home/s-a-balashov/work/vast-fixture-compiler-gate2-"+COMMIT+"-01/gate2.packet.original.json",
            "size_bytes":123,"sha256":"3"*64}
        authority={"path":"/home/s-a-balashov/work/vast-fixture-compiler-gate2-"+COMMIT+"-01.operator-originals/operator.authority.original.json",
            "size_bytes":2048,"sha256":"4"*64}
        summary={"setup_completed":True,"physical_acceptance":False,"external_packet_approval":False,"c_or_d_invoked":False,
            "code_commit":COMMIT,"operator_sha256":self.helpers[capture.HELPER_PATHS[1]]["sha256"],
            "context_sha256":capture.sha(capture.canonical(context)),"operator_authority":authority,
            "baseline":context["baseline"],"boot_id":context["boot_id"],
            "windows_start_ns":context["windows_start_ns"],"linux_start_ns":context["linux_start_ns"],
            "linux_deadline_ns":context["linux_deadline_ns"],"absolute_deadline_ns":context["windows_deadline_ns"],
            "external_driver_status_and_eof_required":True,"outside_preexisting_quote":sum(context[k] for k in
                ("capture_source_quote_bytes","operator_source_quote_bytes","helper_git_forms_quote_bytes")),
            "capture_all_forms_reserved_bytes":65536,"packet":{"packet":packet,"initial_charged_bytes":40_000_000},
            "final_meter":{"funded_initial_charge_bytes":40_000_000,"external_return_proof_reserve_bytes":65536},
            "final_meter_process":{"returncode":0,"stdout_eof":True,"stderr_eof":True,"late":False,"unknown_closure":False}}
        summary=self.summary_mutation(summary)
        self.expected_stdout=capture.canonical(summary)+b"\n"
        self.pipe_data={101:io.BytesIO(self.expected_stdout if self.raw_stdout is None else self.raw_stdout),102:io.BytesIO(self.raw_stderr)}
        return Process(self.code)

    def test_complete_real_orchestration_preserves_exact_prefix_and_nonaccepting_status(self):
        returned=capture.run_capture_v1(COMMIT,APPROVAL)
        self.assertEqual(self.phases,["pre-meter","driver","post-meter"])
        self.assertEqual(self.context["helper_code"],self.helpers)
        self.assertEqual(self.context["windows_deadline_ns"]-self.context["windows_start_ns"],150_000_000_000)
        self.assertEqual(self.context["capture_all_forms_reserved_bytes"],65536)
        self.assertEqual(capture.STDOUT.read_bytes(),self.expected_stdout)
        self.assertEqual(capture.STDERR.read_bytes(),b"")
        status=json.loads(capture.STATUS.read_bytes())
        self.assertLessEqual(capture.STATUS.stat().st_size,4096)
        self.assertFalse(returned["physical_acceptance"])
        self.assertTrue(returned["external_wrapper_status_and_eof_required"])
        self.assertEqual(status["post_meter"],self.post)
        self.assertEqual(status["pre_meter"],self.pre)
        self.assertTrue(status["driver"]["stdout"]["close_completed"])

    def test_pre_meter_payload_must_match_actual_native_stdout_hash(self):
        original=self.native
        def forged(value):
            state=original(value); state["stdout"]["sha256"]="f"*64
            return state
        with patch.object(self,"native",side_effect=forged):
            with self.assertRaises(capture.CaptureRefusal): capture.run_capture_v1(COMMIT,APPROVAL)
        self.assertNotIn("driver",self.phases)
        self.assertEqual(list(self.output.iterdir()),[])

    def test_realistic_large_monotonic_clock_values_still_fit_fixed_status_form(self):
        self.now[0]=10**16
        self.pre["linux_monotonic_ns"]=10**16
        self.post["linux_monotonic_ns"]=10**16+10**9
        capture.run_capture_v1(COMMIT,APPROVAL)
        self.assertLessEqual(capture.STATUS.stat().st_size,4096)

    def test_source_denial_prevents_meter_allocation_and_driver(self):
        with patch.object(capture,"authenticate_helpers_v1",side_effect=capture.CaptureRefusal("source_drift")):
            with self.assertRaises(capture.CaptureRefusal): capture.run_capture_v1(COMMIT,APPROVAL)
        self.assertEqual(self.phases,[])
        self.assertEqual(list(self.output.iterdir()),[])

    def test_pre_meter_floor_fragment_and_native_denials_are_preallocation(self):
        for group,key,bad in ((None,"project_free_bytes",1),(None,"c_fragment_bytes",8192),("baseline","c_free_bytes",1)):
            value=copy.deepcopy(self.pre)
            if group: value[group][key]=bad
            else: value[key]=bad
            with self.subTest(field=key), patch.object(self,"pre",value):
                with self.assertRaises(capture.CaptureRefusal): capture.run_capture_v1(COMMIT,APPROVAL)
            self.assertEqual(list(self.output.iterdir()),[])
        self.assertNotIn("driver",self.phases)

    def test_forged_summary_stops_before_post_meter(self):
        self.summary_mutation=lambda value:dict(value,context_sha256="f"*64)
        with self.assertRaises(capture.CaptureRefusal): capture.run_capture_v1(COMMIT,APPROVAL)
        self.assertNotIn("post-meter",self.phases)
        self.assertFalse(capture.STATUS.exists())

    def test_nonzero_os_status_stops_before_post_meter_even_if_summary_claims_success(self):
        self.code=7
        with self.assertRaises(capture.CaptureRefusal): capture.run_capture_v1(COMMIT,APPROVAL)
        self.assertNotIn("post-meter",self.phases)
        self.assertFalse(capture.STATUS.exists())

    def test_combined_large_failure_prefixes_fit_admitted_all_forms_and_start_no_status_or_meter(self):
        self.code=7; self.raw_stdout=b"A"*12288; self.raw_stderr=b"B"*32768
        with self.assertRaises(capture.CaptureRefusal): capture.run_capture_v1(COMMIT,APPROVAL)
        self.assertEqual(self.context["capture_all_forms_reserved_bytes"],65536)
        self.assertEqual(capture.STDOUT.read_bytes(),self.raw_stdout)
        self.assertEqual(capture.STDERR.read_bytes(),self.raw_stderr)
        self.assertLessEqual(sum(((len(v)+4095)//4096)*4096+4096 for v in (self.raw_stdout,self.raw_stderr)),65536)
        self.assertFalse(capture.STATUS.exists())
        self.assertNotIn("post-meter",self.phases)
        self.assertEqual(capture.FACTS["driver"]["returncode"],7)
        self.assertTrue(capture.FACTS["driver"]["stdout_eof"] and capture.FACTS["driver"]["stderr_eof"])

    def test_post_meter_funded_capacity_and_capture_forms_are_independently_checked(self):
        self.post["required_charge_bytes"]=40_000_001
        with self.assertRaises(capture.CaptureRefusal): capture.run_capture_v1(COMMIT,APPROVAL)
        self.assertFalse(capture.STATUS.exists())

    def test_post_meter_floor_and_actual_form_bounds_prevent_status_write(self):
        for field,bad in (("project_free_bytes",1),("capture_all_forms_upper_bytes",32769),
                ("outside_upper_bytes",524289),("root_allocated_bytes",1048577),
                ("remaining_funded_bytes",0),("status_and_one_copy_reserved_bytes",0)):
            with self.subTest(field=field):
                value=copy.deepcopy(self.post); value[field]=bad
                self.run_denied_after_post(value)

    def run_denied_after_post(self,value):
        # Every controlled invocation owns fresh output paths; no physical retry.
        with tempfile.TemporaryDirectory(dir=self.root) as output, patch.object(capture,"TEMP",Path(output)), patch.object(self,"post",value):
            with self.assertRaises(capture.CaptureRefusal): capture.run_capture_v1(COMMIT,APPROVAL)
            self.assertFalse(capture.STATUS.exists())

    def test_late_source_read_prevents_pre_meter_and_allocation(self):
        original=capture.read_fixed
        def late(path,cap):
            value=original(path,cap); self.now[0]=capture.DEADLINE
            return value
        with patch.object(capture,"read_fixed",side_effect=late):
            with self.assertRaises(capture.CaptureRefusal): capture.run_capture_v1(COMMIT,APPROVAL)
        self.assertEqual(self.phases,[])
        self.assertEqual(list(self.output.iterdir()),[])

    def test_late_post_metric_prevents_status_open(self):
        original=self.meter
        def late(*,after,payload):
            result=original(after=after,payload=payload)
            if after: self.now[0]=capture.DEADLINE
            return result
        with patch.object(capture,"meter",side_effect=late):
            with self.assertRaises(capture.CaptureRefusal): capture.run_capture_v1(COMMIT,APPROVAL)
        self.assertFalse(capture.STATUS.exists())

    def test_incomplete_eof_and_unknown_return_prevent_post_meter(self):
        original=capture.drain
        owned=[]
        def unknown(*args,**kwargs):
            owned.extend(kwargs["files"].values())
            state,streams=original(*args,**kwargs)
            state.update(returncode=None,stdout_eof=False,unknown_closure=True)
            return state,streams
        try:
            with patch.object(capture,"drain",side_effect=unknown):
                with self.assertRaises(capture.CaptureRefusal): capture.run_capture_v1(COMMIT,APPROVAL)
        finally:
            # Controlled drain completed both threads before the injected
            # unknown facts. Test-owned handles can therefore be closed here.
            for file in owned: file.close()
        self.assertNotIn("post-meter",self.phases)
        self.assertFalse(capture.STATUS.exists())
        self.assertIsNone(capture.FACTS["driver"]["returncode"])

    def status_fault(self,kind):
        real_open=Path.open
        class FaultFile:
            def __init__(self,file): self.file=file
            def write(self,raw):
                return self.file.write(raw[:17] if kind=="short" else raw)
            def flush(self): return self.file.flush()
            def fileno(self): return self.file.fileno()
            def close(self):
                self.file.close()
                if kind=="close": raise OSError("controlled status close")
                if kind=="late-close": self_outer.now[0]=capture.DEADLINE
        self_outer=self
        def opened(path,*args,**kwargs):
            file=real_open(path,*args,**kwargs)
            return FaultFile(file) if str(path).endswith(".capture.status.original.json") and args[0]=="xb" else file
        original_fsync=capture.os.fsync
        calls=[0]
        def fsync(fd):
            calls[0]+=1
            if kind=="fsync" and calls[0]==3: raise OSError("controlled status fsync")
            return original_fsync(fd)
        with patch.object(Path,"open",opened),patch.object(capture.os,"fsync",side_effect=fsync):
            with self.assertRaises((capture.CaptureRefusal,OSError)): capture.run_capture_v1(COMMIT,APPROVAL)
        self.assertEqual(self.phases,["pre-meter","driver","post-meter"])
        self.assertTrue(capture.FACTS["status_write"]["failures"])
        self.assertEqual(self.text_stdout.buffer.getvalue(),b"")
        return capture.FACTS["status_write"]

    def test_status_short_write_keeps_confirmed_prefix_and_no_success(self):
        facts=self.status_fault("short")
        self.assertEqual(facts["written_bytes"],17)
        self.assertFalse(facts["write_extent_unknown"])
        self.assertEqual(facts["confirmed_prefix_sha256"],capture.sha(capture.STATUS.read_bytes()))
        self.assertFalse(facts["fsync_completed"])

    def test_status_fsync_failure_keeps_close_and_no_success(self):
        facts=self.status_fault("fsync")
        self.assertFalse(facts["fsync_completed"])
        self.assertTrue(facts["close_completed"])

    def test_status_close_failure_keeps_fsync_and_no_success(self):
        facts=self.status_fault("close")
        self.assertTrue(facts["fsync_completed"])
        self.assertFalse(facts["close_completed"])

    def test_status_close_after_original_deadline_cannot_return_success(self):
        facts=self.status_fault("late-close")
        self.assertTrue(facts["close_completed"])
        self.assertTrue(any("close_CaptureRefusal"==value for value in facts["failures"]))


class LiteralMeterTests(unittest.TestCase):
    """Execute the unchanged fixed meter bodies with filesystem/native effects controlled.

    Real reads/stat/hash/allocation run against this test's temp tree. Only the
    fixed absolute path mapping and UID/version/meter observations are
    controlled. No process is created; historical Temp drafts are not inputs.
    """
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.fs=Path(self.temp.name).resolve()
        self.uid=1000; self.fragment=4096; self.c_free=100_000_000_000; self.project_free=10_000_000_000
        self.ext4_used=300_000_000_000; self.now=1_000_000_000
        self.boot="12345678-1234-1234-1234-123456789abc"
        self.overrides={}
        self.root=self.path("/home/s-a-balashov/work/vast-fixture-compiler-gate2-"+COMMIT+"-01")
        self.f2=Path(str(self.root)+".f2"); self.aux=Path(str(self.root)+".operator-originals")
        for directory in (self.root,self.f2,self.aux,self.path("/mnt/c/Users/s-a-balashov/AppData/Local/Temp")):
            directory.mkdir(parents=True,exist_ok=True)
        self.write("/proc/sys/kernel/random/boot_id",(self.boot+"\n").encode())
        self.helpers={}
        for name in capture.HELPER_PATHS:
            raw=("# controlled literal meter "+name).encode()
            self.write("/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/"+name,raw)
            self.helpers[name]={"path":"C:\\fixed\\"+name,"size_bytes":len(raw),"sha256":capture.sha(raw),
                "git_blob":hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()}

    def path(self,value):
        value=str(value)
        if value.startswith(str(self.fs)): return Path(value)
        return self.fs/value.lstrip("/") if value.startswith("/") else Path(value)

    def write(self,path,raw):
        path=self.path(path); path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(raw)
        return path

    def execute(self,source,payload):
        output=io.BytesIO()
        def fstat(fd):
            actual=os.fstat(fd); values={key:getattr(actual,key) for key in ("st_mode","st_nlink","st_size","st_dev","st_ino","st_mtime_ns","st_ctime_ns","st_blocks")}
            values.update(self.overrides.get(actual.st_ino,{}))
            return types.SimpleNamespace(**values)
        def statvfs(path):
            if str(path)=="/mnt/c":
                return types.SimpleNamespace(f_frsize=self.fragment,f_bavail=self.c_free//4096)
            blocks=200_000_000
            return types.SimpleNamespace(f_frsize=4096,f_bavail=self.project_free//4096,
                f_blocks=blocks,f_bfree=blocks-self.ext4_used//4096)
        fake_os=types.SimpleNamespace(getuid=lambda:self.uid,geteuid=lambda:self.uid,getgid=lambda:self.uid,getegid=lambda:self.uid,
            fstat=fstat,statvfs=statvfs,walk=os.walk,path=os.path)
        fake_sys=types.SimpleNamespace(version_info=(3,12,3),stdin=types.SimpleNamespace(buffer=io.BytesIO(capture.canonical(payload))),
            stdout=types.SimpleNamespace(buffer=output))
        modules={"os":fake_os,"sys":fake_sys,"time":types.SimpleNamespace(monotonic_ns=lambda:self.now),
            "pathlib":types.SimpleNamespace(Path=self.path)}
        with patch.dict(sys.modules,modules):
            exec(compile(source.replace("__REVIEWED_COMMIT__",COMMIT),"<fixed-controlled-meter>","exec"),{})
        return json.loads(output.getvalue())

    def post_payload(self):
        footer={"accounting":{"reserved_control_bytes":524288,"reserved_rounding_bytes":8192,"reserved_metadata_bytes":8192}}
        footer_raw=capture.canonical(footer); (self.f2/"f2.final-accounting.v1.json").write_bytes(footer_raw)
        for name in ("f2.originals.v1.json","f2.supplement.v1.json"):
            (self.f2/name).write_bytes(b"{}")
        context={"schema_version":1,"code_commit":COMMIT,"helper_code":self.helpers,
            "capture_source_sha256":self.helpers[capture.HELPER_PATHS[0]]["sha256"]}
        operator_sha=self.helpers[capture.HELPER_PATHS[1]]["sha256"]
        authority=setup.authority_record_v1(code_commit=COMMIT,approval_reference=APPROVAL,operator_sha256=operator_sha,
            helper_code=self.helpers,context_sha256=capture.sha(capture.canonical(context)),context=context)
        authority_raw=capture.canonical(authority)
        (self.aux/"operator.authority.original.json").write_bytes(authority_raw)
        packet={"code_commit":COMMIT,"project_root":str(self.root),"initial_charged_bytes":40_000_000,
            "code_review":{"evidence_sha256":capture.sha(authority_raw),"approval_reference":APPROVAL},"evidence":{"f2_accounting":{
                "path":str(self.f2/"f2.final-accounting.v1.json"),"size_bytes":len(footer_raw),"sha256":capture.sha(footer_raw)}}}
        packet_raw=capture.canonical(packet); (self.root/"gate2.packet.original.json").write_bytes(packet_raw)
        payload={"baseline":{"c_free_bytes":self.c_free,"ext4_used_bytes":self.ext4_used},"boot_id":self.boot,
            "linux_deadline_ns":150_000_000_000,"packet":{"path":str(self.root/"gate2.packet.original.json"),
                "size_bytes":len(packet_raw),"sha256":capture.sha(packet_raw)},"operator_sha256":operator_sha,
            "operator_authority":{"path":str(self.aux/"operator.authority.original.json"),"size_bytes":len(authority_raw),"sha256":capture.sha(authority_raw)},
            "context":context,
            "approval_reference":APPROVAL,"outside_preexisting_quote":327680,"funded_initial_charge_bytes":40_000_000}
        for name,raw in (("stdout",b"{}\n"),("stderr",b"")):
            self.write("/mnt/c/Users/s-a-balashov/AppData/Local/Temp/vast-gate2-setup-"+COMMIT+".driver."+name+".original",raw)
            payload[name]={"size_bytes":len(raw),"sha256":capture.sha(raw)}
        return payload

    def test_fixed_pre_meter_authenticates_two_source_forms_without_retired_draft_inputs(self):
        result=self.execute(capture.PRE_METER,{"helper_code":self.helpers})
        self.assertNotIn("preserved_temp_source_quote_bytes",result)
        self.assertEqual(result["helper_git_forms_quote_bytes"],16384)
        self.assertEqual(result["baseline"]["c_free_bytes"],(self.c_free//4096)*4096)

    def test_pre_meter_source_drift_fragment_and_uid_refuse(self):
        self.fragment=8192
        with self.assertRaises(AssertionError): self.execute(capture.PRE_METER,{"helper_code":self.helpers})
        self.fragment=4096; self.uid=0
        with self.assertRaises(AssertionError): self.execute(capture.PRE_METER,{"helper_code":self.helpers})
        self.uid=1000
        name=capture.HELPER_PATHS[1]
        self.write("/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/"+name,b"source drift")
        with self.assertRaises(AssertionError): self.execute(capture.PRE_METER,{"helper_code":self.helpers})

    def test_fixed_post_meter_measures_actual_blocks_and_reserves_capture_copy_forms(self):
        payload=self.post_payload(); result=self.execute(capture.POST_METER,payload)
        self.assertEqual(result["capture_all_forms_upper_bytes"],28672)
        self.assertEqual(result["status_and_one_copy_reserved_bytes"],16384)
        self.assertGreater(result["outside_upper_bytes"],payload["outside_preexisting_quote"])
        self.assertEqual(result["remaining_funded_bytes"],40_000_000-result["required_charge_bytes"])

    def test_post_meter_uses_larger_physical_allocation_not_only_logical_size(self):
        payload=self.post_payload()
        raw=self.path("/mnt/c/Users/s-a-balashov/AppData/Local/Temp/vast-gate2-setup-"+COMMIT+".driver.stdout.original")
        self.overrides[raw.stat().st_ino]={"st_blocks":64}
        with self.assertRaises(AssertionError): self.execute(capture.POST_METER,payload)

    def test_post_meter_rejects_unfunded_copied_forms_before_emitting(self):
        payload=self.post_payload(); payload["outside_preexisting_quote"]=460000
        with self.assertRaises(AssertionError): self.execute(capture.POST_METER,payload)

    def test_post_meter_floors_packet_hash_drift_and_unfunded_growth_refuse(self):
        payload=self.post_payload(); self.c_free=1
        with self.assertRaises(AssertionError): self.execute(capture.POST_METER,payload)
        self.c_free=100_000_000_000; self.ext4_used+=100_000_000
        with self.assertRaises(AssertionError): self.execute(capture.POST_METER,payload)
        self.ext4_used-=100_000_000; payload["packet"]["sha256"]="f"*64
        with self.assertRaises(AssertionError): self.execute(capture.POST_METER,payload)

    def test_setup_actual_authority_schema_replaces_source_sha_as_packet_evidence(self):
        payload=self.post_payload()
        self.assertNotEqual(payload["operator_authority"]["sha256"],payload["operator_sha256"])
        self.execute(capture.POST_METER,payload)

    def test_authority_commit_approval_source_helper_and_context_mutations_refuse(self):
        payload=self.post_payload(); authority_path=self.aux/"operator.authority.original.json"
        authority=json.loads(authority_path.read_bytes())
        for field in ("code_commit","approval_reference","operator_sha256","helper_code","context_sha256","context","external_approval_required"):
            with self.subTest(field=field):
                bad=copy.deepcopy(authority)
                bad[field]=False if field=="external_approval_required" else {} if field in ("helper_code","context") else "f"*40
                raw=capture.canonical(bad); authority_path.write_bytes(raw)
                changed=copy.deepcopy(payload); changed["operator_authority"].update(size_bytes=len(raw),sha256=capture.sha(raw))
                with self.assertRaises(AssertionError): self.execute(capture.POST_METER,changed)


if __name__=="__main__":
    unittest.main()
