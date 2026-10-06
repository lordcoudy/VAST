"""Software driver/CLI seams only: no engine, media, model or readiness claims."""
from __future__ import annotations
import argparse
from contextlib import redirect_stdout
import copy
import hashlib
import io
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import run_canonical_systems_study_v1 as driver

@unittest.skipUnless(os.name=="posix","finite driver requires original POSIX production route")
class FiniteStudyDriverTests(unittest.TestCase):
    def args(self,root,out):
        return ["study","--project-root",str(root),"--output-dir",str(out),"--engine","/fixture/not-an-engine",
            "--engine-socket","/fixture/not-a-socket","--front-gate",str(root/"front.avi"),"--underbody",str(root/"under.avi"),
            *[word for name in ("capability-manifest","calibration","model-parity-receipt","worker-freeze-receipt","execution-code-closure")
              for word in ("--"+name,"fixture-control")]]

    def test_single_study_cli_hands_off_actual_exclusive_descriptor_and_no_run_after_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);out=root/"study";calls=[]
            def preparation(args):
                self.assertEqual(args.output_dir,out/"prepare");args.output_dir.mkdir()
                calls.append("prepare")
                return driver.write_json(args.output_dir/"actual.json",{"software_fixture":True})
            def campaign(args):
                calls.append("run")
                self.assertEqual(args.output_dir,out/"run")
                raw=args.prepared.read_bytes()
                self.assertEqual((args.prepared_size_bytes,args.prepared_sha256),(len(raw),hashlib.sha256(raw).hexdigest()))
                self.assertEqual(args.prepared,out/"prepare"/"actual.json")
                return {"software_orchestration_only":True}
            with mock.patch.object(driver,"prepare",side_effect=preparation),mock.patch.object(driver,"run",side_effect=campaign),redirect_stdout(io.StringIO()):
                self.assertEqual(driver.main(self.args(root,out)),0)
            self.assertEqual(calls,["prepare","run"])
            with mock.patch.object(driver,"prepare",side_effect=ValueError("original prepare refusal")),mock.patch.object(driver,"run") as run:
                with self.assertRaisesRegex(ValueError,"original prepare refusal"):driver.main(self.args(root,root/"failed"))
                run.assert_not_called()
            with mock.patch.object(driver,"prepare") as prepare:
                with self.assertRaisesRegex(ValueError,"exclusive parent"):driver.main(self.args(root,out))
                prepare.assert_not_called()

    def test_isolated_executable_cli_has_study_and_missing_intake_never_runs_engine(self):
        command=[sys.executable,"-I","-B",str(ROOT/"scripts/run_canonical_systems_study_v1.py")]
        help_result=subprocess.run(command+["--help"],capture_output=True,timeout=10)
        self.assertEqual(help_result.returncode,0,help_result.stderr)
        self.assertIn(b"{prepare,run,study}",help_result.stdout)
        invalid=subprocess.run(command+["study"],capture_output=True,timeout=10)
        self.assertEqual(invalid.returncode,2)
        self.assertIn(b"required",invalid.stderr)

    def preparation_args(self,root,out,started):
        return argparse.Namespace(project_root=root,output_dir=out,
            preparation_started_monotonic_ns=started,
            preparation_boot_id=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            preparation_time_namespace=driver.actual_clock_domain_label())

    def test_original_preparation_expired_stamp_is_refused_before_output_or_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);out=root/"expired"
            args=self.preparation_args(root,out,time.monotonic_ns()-14_401_000_000_000)
            with self.assertRaisesRegex(ValueError,"original preparation clock"):
                driver.prepare(args)
            self.assertFalse(out.exists())

    def test_original_preparation_foreign_or_partial_domain_is_refused_before_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for field,value in (("preparation_boot_id","foreign-boot"),
                                ("preparation_time_namespace","time:[foreign]"),
                                ("preparation_boot_id",None)):
                out=root/(field+str(value))
                args=self.preparation_args(root,out,time.monotonic_ns())
                setattr(args,field,value)
                with self.assertRaisesRegex(ValueError,"original preparation clock"):
                    driver.prepare(args)
                self.assertFalse(out.exists())

    def test_actual_preparation_bootstrap_read_retains_original_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);out=root/"prepared";actual=root/"bootstrap.raw"
            actual.write_bytes(b"original bootstrap bytes"*65536)
            started=time.monotonic_ns()
            # Real earlier read under the same observed kernel clock, not a fake clock.
            expected=hashlib.sha256(actual.read_bytes()).hexdigest()
            args=self.preparation_args(root,out,started);captured=[]
            original=driver.Commands
            def observe(*values,**kwargs):
                commands=original(*values,**kwargs);captured.append(commands);return commands
            with mock.patch.object(driver,"Commands",side_effect=observe):
                # The temporary root intentionally lacks the first source allowlist.
                # This ends the software-only case at real original source intake.
                with self.assertRaisesRegex(ValueError,"publication image input is absent"):driver.prepare(args)
            self.assertEqual(len(captured),1)
            commands=captured[0]
            self.assertEqual(commands.deadline,(started+14_400_000_000_000)/1e9)
            self.assertEqual(commands.deadline_monotonic_ns,started+14_400_000_000_000)
            self.assertLess(commands.remaining(),14400.0)
            self.assertEqual(driver.descriptor(actual,deadline=commands.deadline)["sha256"],expected)

    def unshared_preparation_clock(self,mode):
        """Real fresh time namespace: parent stamp, then a child/grandchild in an unshared zero-offset domain."""
        code=r"""
import argparse,json,os,sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1]);import run_canonical_systems_study_v1 as driver
mode=sys.argv[2];parent=driver.preparation_clock(argparse.Namespace())
args=argparse.Namespace(preparation_started_monotonic_ns=parent["started_monotonic_ns"],
    preparation_boot_id="foreign-boot" if mode=="foreign" else parent["boot_id"],preparation_time_namespace=parent["time_namespace"])
os.unshare(os.CLONE_NEWUSER|os.CLONE_NEWTIME)
if mode=="nonzero":Path("/proc/self/timens_offsets").write_text("monotonic 7 0\n")
def attempt():
    try:return {"accepted":True,"domain":driver.preparation_clock(args)["time_namespace"]}
    except ValueError as error:return {"accepted":False,"error":str(error)}
if mode=="self":print(json.dumps(attempt()));sys.exit(0)
read,write=os.pipe();child=os.fork()
if child==0:
    os.close(read);os.write(write,json.dumps({**attempt(),"actual_ns":os.readlink("/proc/self/ns/time"),"parent_ns":parent_ns}).encode());os._exit(0)
os.close(write);raw=b""
while chunk:=os.read(read,65536):raw+=chunk
os.waitpid(child,0);print(raw.decode())
""".replace("parent_ns}",'os.readlink("/proc/%d/ns/time"%os.getppid())}')
        done=subprocess.run([sys.executable,"-I","-B","-c",code,str(ROOT/"scripts"),mode],capture_output=True,text=True,timeout=30)
        self.assertEqual(done.returncode,0,done.stderr)
        import json;return json.loads(done.stdout)

    def test_actual_fresh_zero_offset_time_namespace_is_the_same_monotonic_domain(self):
        same=self.unshared_preparation_clock("zero")
        self.assertNotEqual(same.get("actual_ns"),same.get("parent_ns"))
        self.assertTrue(same["accepted"],same)
        for mode in ("nonzero","self","foreign"):
            refused=self.unshared_preparation_clock(mode)
            self.assertFalse(refused["accepted"],(mode,refused))
            self.assertIn("original preparation clock",refused["error"])

    def test_original_preparation_invalid_stamp_and_study_parent_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for index,started in enumerate((True,0,-1,time.monotonic_ns()+60_000_000_000)):
                out=root/str(index);args=self.preparation_args(root,out,started)
                with self.assertRaisesRegex(ValueError,"original preparation clock"):
                    driver.study(args)
                self.assertFalse(out.exists())

    def test_study_cli_propagates_original_preparation_stamp_without_new_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);out=root/"study";started=time.monotonic_ns()
            boot=Path("/proc/sys/kernel/random/boot_id").read_text().strip()
            namespace=driver.actual_clock_domain_label()
            argv=self.args(root,out)+["--preparation-started-monotonic-ns",str(started),
                "--preparation-boot-id",boot,"--preparation-time-namespace",namespace]
            def prepare(args):
                self.assertEqual((args.preparation_started_monotonic_ns,args.preparation_boot_id,args.preparation_time_namespace),
                    (started,boot,namespace))
                args.output_dir.mkdir();return driver.write_json(args.output_dir/"actual.json",{"software_only":True})
            with mock.patch.object(driver,"prepare",side_effect=prepare),mock.patch.object(driver,"run",return_value={"software_only":True}),redirect_stdout(io.StringIO()):
                self.assertEqual(driver.main(argv),0)

    def test_real_partial_file_reads_keep_hash_deadline_and_reject_named_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"raw";path.write_bytes(b"abcdefg");before=len(list(Path("/proc/self/fd").iterdir()))
            original=os.pread
            with mock.patch.object(driver.os,"pread",side_effect=lambda fd,n,off:original(fd,min(n,2),off)):
                value=driver.descriptor(path,deadline=time.monotonic()+5)
            self.assertEqual(value["sha256"],hashlib.sha256(b"abcdefg").hexdigest())
            def mutate(fd,n,offset):
                raw=original(fd,n,offset)
                if os.readlink("/proc/self/fd/"+str(fd))==str(path):
                    replacement=path.with_suffix(".replacement");replacement.write_bytes(b"changed");os.replace(replacement,path)
                return raw
            with mock.patch.object(driver.os,"pread",side_effect=mutate),self.assertRaisesRegex(ValueError,"drifted"):
                driver.descriptor(path,deadline=time.monotonic()+5)
            with self.assertRaisesRegex(ValueError,"deadline"):driver.descriptor(path,deadline=time.monotonic()-1)
            self.assertEqual(len(list(Path("/proc/self/fd").iterdir())),before)

    def test_stderr_collision_closes_first_acquired_stream_without_child_or_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/"command-000.stderr.raw").write_bytes(b"original")
            commands=driver.Commands(root,time.monotonic()+60);before=len(list(Path("/proc/self/fd").iterdir()))
            with self.assertRaises(FileExistsError):commands.launch([sys.executable,"-c","raise Exception('must not launch')"])
            self.assertEqual(commands.children,[]);self.assertEqual(commands.records,[])
            self.assertEqual((root/"command-000.stderr.raw").read_bytes(),b"original")
            self.assertEqual(len(list(Path("/proc/self/fd").iterdir())),before)

    def test_actual_term_ignoring_child_is_killed_waited_and_shared_closing_clock_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            commands=driver.Commands(Path(tmp),time.monotonic()+60);before=len(list(Path("/proc/self/fd").iterdir()))
            child,record=commands.launch([sys.executable,"-I","-B","-c",
                "import signal; signal.signal(signal.SIGTERM,signal.SIG_IGN); print('READY',flush=True); signal.pause()"],stdout=subprocess.PIPE)
            try:
                self.assertEqual(child.stdout.readline(),b"READY\n")
                commands.retire()
                self.assertEqual(child.returncode,-signal.SIGKILL)
                with self.assertRaises(ChildProcessError):os.waitpid(child.pid,os.WNOHANG)
                original_end=commands.closing_deadline
                self.assertLessEqual(original_end,commands.deadline)
            finally:
                if child.poll() is None:os.killpg(child.pid,signal.SIGKILL);child.wait(timeout=3)
                child.stdout.close()
            self.assertEqual(len(list(Path("/proc/self/fd").iterdir())),before)

    def test_actual_closed_child_output_cap_refuses_retains_bytes_and_reaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            commands=driver.Commands(Path(tmp),time.monotonic()+60)
            child,record=commands.launch([sys.executable,"-I","-B","-c","print('overflow',flush=True)"])
            with self.assertRaisesRegex(ValueError,"cap"):
                commands.wait(child,record,maximum=1)
            commands.retire()
            self.assertIsNotNone(child.returncode)
            self.assertIn(b"overflow",Path(record["stdout_path"]).read_bytes())
            with self.assertRaises(ChildProcessError):os.waitpid(child.pid,os.WNOHANG)

    def test_source_inventory_binary_clock_proof_and_cid_outside_empty_arm(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);out=root/"arm";out.mkdir();commands=driver.Commands(root,time.monotonic()+60)
            with mock.patch.object(commands,"run",return_value=b""),mock.patch.object(commands,"launch",return_value=(object(),{})) as launch:
                driver._native(commands,"fixture-engine","sha256:"+"a"*64,root,out,["--checkpoint-study-au-inventory","/fixture/media",1920,1080,1],entrypoint="/usr/local/bin/vast_checkpoint_source")
            argv=launch.call_args.args[0]
            self.assertEqual(argv[argv.index("--entrypoint")+1],"/usr/local/bin/vast_checkpoint_source")
            cid=Path(argv[argv.index("--cidfile")+1]);self.assertEqual(cid.parent,root)
            self.assertEqual(list(out.iterdir()),[])
            for name in ("VAST_CHECKPOINT_PREPARATION_CLOCK_BOOT_ID","VAST_CHECKPOINT_PREPARATION_CLOCK_TIME_NAMESPACE"):
                self.assertTrue(any(word.startswith(name+"=") for word in argv))

    def test_incomplete_pilot_cannot_trigger_or_authorize_effects(self):
        pilots=[{"arm":{"topology":kind},"reduction":{"raw_reconciliation_complete":True,
            "waits":{"native_client":{"wait_ns":{"n":30},"median_wait_fraction":.10}}}} for kind in ("baseline","shared","baseline","shared")]
        self.assertTrue(driver.pilot_select_branch(pilots))
        bad=copy.deepcopy(pilots);bad[0]["reduction"]["raw_reconciliation_complete"]=False
        with self.assertRaisesRegex(ValueError,"incomplete raw"):driver.pilot_select_branch(bad)
        for row in pilots:row["reduction"]["waits"]["native_client"]["wait_ns"]["n"]=29
        self.assertFalse(driver.pilot_select_branch(pilots))

    def test_original_runtime_main_translates_branch_once_to_canonical_receipt_mode(self):
        import checkpoint_gstreamer_runtime as runtime
        from publication_policy_qualification_runtime_inputs_v2 import DETECT_BIN
        command=["--scenario","checkpoint_video_dag_shared","--finite-study-plan","/fixture/plan",
            "--finite-study-arm","fixture-arm","--finite-study-client-mode","branch",
            "--finite-study-campaign-deadline-ns","123","--operational-request-context","/fixture/context",
            "--policy-capability-manifest","/fixture/capability","--policy-calibration","/fixture/calibration",
            "--analytics-execution-manifest","/fixture/execution","--analytics-model-manifest","/fixture/model",
            "--analytics-execution-socket","/fixture/socket","--analytics-preprocessing-contract-sha256","a"*64,
            "--detect-bin",DETECT_BIN]
        with mock.patch.object(runtime,"_load_yaml",return_value={"software_fixture_only":True}),mock.patch.object(runtime,"run_finite_study_arm_v1") as arm:
            self.assertEqual(runtime.main(command),0)
            arm.assert_called_once()
            self.assertEqual(arm.call_args.kwargs["client_mode"],"branch-channel")
            self.assertEqual(arm.call_args.kwargs["campaign_deadline_ns"],123)
            self.assertEqual(arm.call_args.kwargs["detect_bin"],DETECT_BIN)

    def test_actual_x264_recipe_writes_fixed_rate_sps_and_strict_vui_refusals_are_kept(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);commands=driver.Commands(root,time.monotonic()+120);encoded=root/"derived.mp4"
            argv=driver.encode_command(64,64,encoded)
            frames=root/"frames.yuv"
            with frames.open("xb") as stream:
                for ordinal in range(442):
                    stream.write(bytes((ordinal+i)%256 for i in range(64*64))+bytes([128])*(2*32*32))
            with frames.open("rb") as stream:
                child,record=commands.launch(argv,stdin=stream);commands.wait(child,record,maximum_files=((str(encoded),driver.MAX_MEDIA),))
            packets=json.loads(commands.run(["/usr/bin/ffprobe","-v","error","-select_streams","v:0","-show_streams","-show_packets",
                "-of","json",str(encoded)],maximum=8*1024**2))
            stream=packets["streams"][0]
            self.assertEqual((stream["r_frame_rate"],stream["avg_frame_rate"],stream["time_base"],stream["has_b_frames"]),("30/1","30/1","1/600",0))
            self.assertEqual([(p["pts"],p["dts"],p["duration"],"K" in p["flags"]) for p in packets["packets"]],
                [(20*i,20*i,20,True) for i in range(442)])
            commands.run(["/usr/bin/ffmpeg","-v","verbose","-nostdin","-i",str(encoded),"-map","0:v:0","-c:v","copy",
                "-bsf:v","trace_headers","-frames:v","1","-f","null","-"])
            trace=Path(commands.records[-1]["stderr_path"]).read_text()
            fields=driver.validate_vui_trace(trace)
            self.assertEqual((fields["fixed_frame_rate_flag"],fields["num_units_in_tick"]*60),(1,fields["time_scale"]))
            self.assertLessEqual(fields["level_idc"],51)
            def field(name,value,text=trace):
                import re
                return re.sub(r"(\b"+name+r"\s+[^\r\n]*?=\s*)\d+",lambda m:m.group(1)+str(value),text)
            old=(ROOT/"openspec/changes/run-finite-component-study/evidence/physical-D-failed-v1/preparation/command-029.stderr.raw").read_text()
            for changed in (old,field("fixed_frame_rate_flag",0),field("time_scale",1200*fields["num_units_in_tick"]),
                    field("level_idc",52),field("timing_info_present_flag",0),trace.replace("fixed_frame_rate_flag","absent_flag"),
                    trace+"\n[trace_headers] fixed_frame_rate_flag 0 = 0\n"):
                with self.assertRaises(ValueError):driver.validate_vui_trace(changed)
            self.assertEqual(argv[argv.index("-x264-params")+1],"open-gop=0:threads=1:lookahead-threads=1:force-cfr=1")

    def test_finite_source_gate_emits_the_canonical_consumer_fd_map(self):
        import checkpoint_gstreamer_runtime as runtime
        from types import SimpleNamespace
        spec=SimpleNamespace(environment={},stream_id=5,source_process_id="source-5",dataset_id="kpp",source_sha256="a"*64)
        pipes={kind:(10+index,20+index) for index,kind in enumerate(("admission","ack","control","status","transport"))}
        env=runtime.finite_study_source_environment_v1(spec,pipes,startup=time.monotonic()+5,run_id="r",topology_kind="video_dag_shared")
        # Native parse_consumer_fds accepts only the compact canonical consumer FD map.
        self.assertEqual(env["VAST_CHECKPOINT_ADMISSION_CONSUMER_FDS_JSON"],'{"reference-5":24}')
        from checkpoint_runtime import canonical_consumer_fds_json
        self.assertEqual(canonical_consumer_fds_json({"b-1":3,"a-0":4}),'{"b-1":3,"a-0":4}')

    def test_finite_study_worker_writes_both_journals_into_the_arm_study_directory(self):
        import checkpoint_gstreamer_runtime as runtime
        study=Path("/arm/study")
        values=runtime.finite_study_worker_arguments_v1({"width":1920,"height":1080},"s0-plate",
            study_client_mode="global-client",study_output_root=study)
        flags=dict(zip(values[::2],values[1::2]))
        # Native refuses a study worker without both journals; decode_arm reads only <arm>/study.
        self.assertEqual(flags.get("--checkpoint-study-accounting-path"),str(study/"native-s0-plate-receives.jsonl"))
        self.assertEqual(flags.get("--checkpoint-study-waits-path"),str(study/"native-s0-plate-waits.jsonl"))

    def test_owned_sidecar_runner_has_subprocess_run_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            commands=driver.Commands(Path(tmp),time.monotonic()+60)
            runner=driver.owned_subprocess_runner(commands,"/usr/bin/docker")
            try:
                ok=runner(["/bin/sh","-c","printf ok"],check=True,capture_output=True,text=True,timeout=5)
                self.assertEqual((ok.returncode,ok.stdout),(0,"ok"))
                three=runner(["/bin/sh","-c","echo bad >&2; exit 3"],check=False,capture_output=True,text=True,timeout=5)
                self.assertEqual((three.returncode,three.stderr),(3,"bad\n"))
                with self.assertRaises(subprocess.CalledProcessError) as failed:
                    runner(["/bin/false"],check=True,capture_output=True,timeout=5)
                self.assertEqual(failed.exception.returncode,1)
                started=time.monotonic()
                with self.assertRaises(subprocess.TimeoutExpired):
                    runner(["/bin/sh","-c","sleep 30"],check=False,capture_output=True,timeout=0.5)
                self.assertLess(time.monotonic()-started,10)
                self.assertTrue(all(child.poll() is not None for child in commands.children))
            finally:commands.retire()
            (Path(tmp)/"short").mkdir()
            short=driver.Commands(Path(tmp)/"short",time.monotonic()+16.5)
            try:
                # A closing campaign clock is never a retryable SubprocessError.
                with self.assertRaises(ValueError):
                    driver.owned_subprocess_runner(short,"/usr/bin/docker")(["/bin/sh","-c","sleep 30"],check=False,timeout=30)
                self.assertTrue(all(child.poll() is not None for child in short.children))
            finally:short.retire()

    def test_native_client_wait_pairs_follow_the_native_row_contract(self):
        domain={"clock":"CLOCK_MONOTONIC","boot_id":"b","time_namespace":"t","pid":7}
        common={"kind":"client","run_id":"r","request_id":"q1","worker_id":"w","input_frame_key":"k","stream_id":0,
            "frame_id":3,"transport_pts_ns":1,"branch":"plate_number","resource":"cpu","attempt_ns":100,"clock_domain":domain}
        # Native exchange writes begin after acquisition with attempt only (0 -> null).
        begin={**common,"phase":"begin","acquired_ns":None,"reply_ns":None,"released_ns":None}
        released={**common,"phase":"released","acquired_ns":120,"reply_ns":150,"released_ns":151}
        self.assertEqual(driver.native_client_waits([begin,released]),[{**released,"kind":"native_client"}])
        unknown_reply={**released,"reply_ns":None}
        self.assertEqual(driver.native_client_waits([unknown_reply,begin]),[{**unknown_reply,"kind":"native_client"}])
        for rows in ([released],[begin],[begin,released,released],[{**begin,"acquired_ns":120},released],
                     [begin,{**released,"acquired_ns":None}],[begin,{**released,"attempt_ns":99}],
                     [begin,{**released,"input_frame_key":"other"}],[begin,{**released,"branch":"damage"}]):
            with self.assertRaises(ValueError):driver.native_client_waits(rows)

    def test_decoded_guardian_rows_do_not_repeat_the_journal_header(self):
        header={"sha256":"c"*64,"route":{"branch":"plate_number","resource":"cpu"},
            "worker_capability":{"worker_id":"w"},"template":"t"*18500}
        decoded=[{"identity":{"run_id":"r","arm_id":"wire","request_id":"q"+str(index),"input_frame_key":"k"+str(index)},
            "begin":{"seq":2*index+1},"terminal":{"seq":2*index+2,"timings":None},"original_header":header,
            "original_journal_path":"/held/plate_number-cpu.jsonl","original_terminal_offset":index} for index in range(4000)]
        rows,waits=driver.decode_guardian_rows(decoded,{"arm_id":"pilot"},"r","wire",{},{})
        self.assertEqual(waits,[])
        self.assertTrue(all("original_header" not in row and row["original_header_sha256"]==header["sha256"] and
            row["original_route"]==header["route"] and row["identity"]["arm_id"]=="pilot" for row in rows))
        with tempfile.TemporaryDirectory() as tmp:
            # 4000 rows x ~18.6 KB header would exceed the decoded role cap.
            self.assertLess(driver.write_rows(Path(tmp)/"guardian.jsonl",rows)["size_bytes"],8*1024**2)

    def test_study_storage_caps_are_the_measured_worst_case_with_margin(self):
        import publication_operational_request_domain_v1 as domain
        import publication_guardian_operational_recorder_v1 as recorder
        import reduce_canonical_systems_study_v1 as reducer
        from canonical_systems_study_plan_v1 import build_study_plan
        self.assertEqual((driver.MAX_RAW_ARM,driver.MAX_RAW_CAMPAIGN),(1024**3,24*1024**3))
        self.assertEqual((reducer.MAX_FILE_BYTES,reducer.MAX_DOCUMENT_BYTES),(192*1024**2,16*1024**2))
        scope={"kind":"finite-component-study","plan_sha256":"a"*64,"max_frame_id":441,"max_requests_per_arm":10608,"max_operations":32}
        # Only the finite study domain is re-fixed; the shared legacy domain stays 64 MiB.
        self.assertEqual((domain.native_domain_byte_limit_v1(None),domain.native_domain_byte_limit_v1(scope)),(64*1024**2,192*1024**2))
        self.assertEqual(domain.MAX_NATIVE_DOMAIN_BYTES_V1,64*1024**2)
        self.assertEqual(recorder.STUDY_BUDGET_OVERRIDES,{"max_terminal_bytes":2048,"max_group_bytes":768*1024**2})
        self.assertEqual(recorder.DEFAULT_BUDGETS["max_group_bytes"],256*1024**2)
        # Measured worst case: ~445 MiB arm directory, ~161 MiB decoded per arm, ~7 GiB campaign.
        self.assertGreaterEqual(driver.MAX_RAW_ARM,2*445*1024**2)
        self.assertGreaterEqual(reducer.MAX_FILE_BYTES,2*58*1024**2)

    def test_final_results_document_has_its_own_measured_bound(self):
        # ~16.3 MiB measured with the conditional switch; other control documents keep 16 MiB.
        completed={"kind":"finite-component-study-completed-v1","reduction":{"keys":["k"*100]*200_000}}
        with tempfile.TemporaryDirectory() as tmp:
            result=driver.write_study_results(Path(tmp),completed)
            self.assertGreater(result["size_bytes"],16*1024**2)
            with self.assertRaisesRegex(ValueError,"metadata bound"):
                driver.write_json(Path(tmp)/"control.json",completed)

    def test_stop_precedes_the_half_open_offer_boundary_by_a_plan_proven_lead(self):
        import checkpoint_runtime
        from canonical_systems_study_plan_v1 import admission_stop_lead_ns, OFFER_END_NS
        sys.path.insert(0,str(ROOT/"tests"));from test_canonical_systems_study_plan_v1 import intake_fixture,material_fixture
        from canonical_systems_study_plan_v1 import build_study_plan
        # Actual derived MP4 timeline: PTS i/30 s floored to ns (durations 33333333/33333333/33333334).
        intake=intake_fixture()
        for recording in intake["recordings"].values():
            pts=[i*10**9//30 for i in range(443)]
            for i,unit in enumerate(recording["access_units"]):
                unit.update(pts_ns=pts[i],dts_ns=pts[i],duration_ns=pts[i+1]-pts[i])
        plan=build_study_plan(intake,material_fixture())
        for rate in ("0.25","1","2"):
            self.assertEqual(admission_stop_lead_ns(plan,rate),250_000_000)
        with self.assertRaises(ValueError):admission_stop_lead_ns(plan,"2",lead_ns=300_000_000)
        # A drifting constant-duration timeline puts a planned AU 2.1 us before the offer end: refused.
        with self.assertRaises(ValueError):admission_stop_lead_ns(build_study_plan(intake_fixture(),material_fixture()),"2")
        # STOP no longer coincides with the boundary AU wake at start+210 s.
        self.assertEqual(checkpoint_runtime.synchronized_stop_monotonic_ns(1000,30.0,180.0,250_000_000),1000+OFFER_END_NS-250_000_000)
        self.assertEqual(checkpoint_runtime.synchronized_stop_monotonic_ns(1000,30.0,180.0,0),1000+OFFER_END_NS)
        for lead in (-1,180_000_000_000,True):
            with self.assertRaises(Exception):checkpoint_runtime.synchronized_stop_monotonic_ns(1000,30.0,180.0,lead)

    def test_source_gate_fails_fast_on_a_capture_error_after_stop(self):
        import checkpoint_gstreamer_runtime as runtime
        child=subprocess.Popen(["/bin/sh","-c","sleep 30"],start_new_session=True)
        try:
            errors=[ValueError("study admission differs from the original planned AU before ACK")]
            started=time.monotonic()
            with self.assertRaisesRegex(Exception,"planned AU"):
                runtime.wait_finite_study_sources_after_stop({"s0":child},errors,threading.Lock(),until_monotonic=time.monotonic()+10)
            self.assertLess(time.monotonic()-started,2)
        finally:
            child.kill();child.wait()
        done=subprocess.Popen(["/bin/true"]);done.wait()
        runtime.wait_finite_study_sources_after_stop({"s0":done},[],threading.Lock(),until_monotonic=time.monotonic()+5)

    def test_control_failure_still_closes_actual_service_thread_and_preserves_primary(self):
        with tempfile.TemporaryDirectory() as tmp:
            commands=driver.Commands(Path(tmp),time.monotonic()+60);stop=threading.Event();thread=threading.Thread(target=stop.wait);thread.start()
            class Service:
                def stop(self):stop.set();thread.join(timeout=2);return {"status":"failed_stop_nonpublication","failure":"original","cleanup_errors":[]}
            original=ValueError("actual control refused")
            try:
                with mock.patch("checkpoint_gstreamer_analytics_sidecar.request_publication_sidecar_guardian_stop_v1",side_effect=original):
                    with self.assertRaises(ValueError) as caught:driver.stop_pool(commands,Service(),{},Path(tmp),"global-client")
                self.assertIs(caught.exception,original);self.assertFalse(thread.is_alive())
            finally:stop.set();thread.join(timeout=2)

if __name__=="__main__":unittest.main()
