"""Original worker exit facts do not infer OOM or an actor from exit137."""
from __future__ import annotations
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from checkpoint_gstreamer_analytics_sidecar import DockerWorkerHandle

class Process:
    pid=123
    status=None
    def poll(self): return self.status

class TerminationTests(unittest.TestCase):
    def make(self, *, terminal_oom=False, removed=False):
        process=Process()
        state={"id":"a"*64,"image":"sha256:"+"b"*64,"pid":42,"exit_code":0,"oom_killed":False,"running":True,"started_at":"2026-09-30T00:00:00Z","finished_at":"0001-01-01T00:00:00Z"}
        def runner(command, **kwargs):
            if command[1]=="inspect":
                if command[3]=="{{.State.Pid}}": return subprocess.CompletedProcess(command,0,stdout="42",stderr="")
                if process.status is not None and removed: return subprocess.CompletedProcess(command,1,stdout="",stderr="not found")
                if process.status is not None:
                    state.update(pid=0,exit_code=137,oom_killed=terminal_oom,running=False,finished_at="2026-09-30T00:01:00Z")
                return subprocess.CompletedProcess(command,0,stdout=json.dumps(state),stderr="")
            if command[1]=="info": value="original-daemon-id"
            elif command[1]=="context": value="default"
            else: value=json.dumps({"action":"die","id":"a"*64,"timeNano":1790726460000000000})
            return subprocess.CompletedProcess(command,0,stdout=value,stderr="")
        handle=DockerWorkerHandle(process,container_name="owned-original-worker",command_runner=runner,platform_observer=lambda:{},stdout_capture=io.BytesIO(b"x"*5000),stderr_capture=io.BytesIO(b"last stderr"),worker_image_id=state["image"],route=("plate_number","cpu"))
        self.addCleanup(handle.close_diagnostics)
        self.assertEqual(handle.expected_peer_pid(0.1),42)
        process.status=137
        return handle

    def test137_engine_removed_retains_original_id_and_oom_unknown(self):
        value=self.make(removed=True).termination_facts()
        self.assertEqual(value["container_id"],"a"*64)
        self.assertEqual(value["frontend_process"]["exit_code"],137)
        self.assertIsNone(value["oom_observation"]["value"])
        self.assertEqual(value["engine_events"]["records"][0]["action"],"die")
        self.assertEqual(value["last_observed_engine_state"]["pid"],42)
        self.assertEqual(len(value["stdout_tail"]),512)
        self.assertEqual(value["kernel_observation"]["status"],"unavailable")

    def test_engine_reported_oom_true_retained_as_fact(self):
        value=self.make(terminal_oom=True).termination_facts()
        self.assertEqual(value["oom_observation"],{"status":"observed","value":True})

    def test_engine_reported_oom_false_does_not_infer_actor(self):
        value=self.make().termination_facts()
        self.assertEqual(value["oom_observation"],{"status":"observed","value":False})
        self.assertNotIn("actor",value)
        self.assertEqual(value["engine_identity"]["context"]["value"],"default")

if __name__=="__main__":unittest.main()
