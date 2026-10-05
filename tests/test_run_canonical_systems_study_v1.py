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
        command=["--scenario","checkpoint_video_dag_shared","--finite-study-plan","/fixture/plan",
            "--finite-study-arm","fixture-arm","--finite-study-client-mode","branch",
            "--finite-study-campaign-deadline-ns","123","--operational-request-context","/fixture/context",
            "--policy-capability-manifest","/fixture/capability","--policy-calibration","/fixture/calibration",
            "--analytics-execution-manifest","/fixture/execution","--analytics-model-manifest","/fixture/model",
            "--analytics-execution-socket","/fixture/socket","--analytics-preprocessing-contract-sha256","a"*64]
        with mock.patch.object(runtime,"_load_yaml",return_value={"software_fixture_only":True}),mock.patch.object(runtime,"run_finite_study_arm_v1") as arm:
            self.assertEqual(runtime.main(command),0)
            arm.assert_called_once()
            self.assertEqual(arm.call_args.kwargs["client_mode"],"branch-channel")
            self.assertEqual(arm.call_args.kwargs["campaign_deadline_ns"],123)

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
