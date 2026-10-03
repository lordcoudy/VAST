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

    def test_real_shared_capture_offset_is_preserved_for_the_original_writer(self):
        import os
        import tempfile
        with tempfile.TemporaryFile("w+b") as capture:
            capture.write(b"prefix-" + b"x" * 2048 + b"-tail")
            capture.flush()
            writer = os.dup(capture.fileno())
            try:
                os.lseek(writer, 3, os.SEEK_SET)
                observed = DockerWorkerHandle._capture_tail(capture, maximum_bytes=5)
                self.assertEqual(observed, "-tail")
                self.assertEqual(os.lseek(writer, 0, os.SEEK_CUR), 3)
                os.write(writer, b"XYZ")
                self.assertEqual(os.pread(capture.fileno(), 6, 0), b"preXYZ")
            finally:
                os.close(writer)

    def test_bytesio_capture_does_not_change_fixture_cursor_and_pipe_is_unavailable(self):
        import os
        capture = io.BytesIO(b"fixture-tail")
        capture.seek(2)
        self.assertEqual(DockerWorkerHandle._capture_tail(capture, maximum_bytes=4), "tail")
        self.assertEqual(capture.tell(), 2)
        read_fd, write_fd = os.pipe()
        try:
            with os.fdopen(read_fd, "rb", buffering=0) as pipe:
                self.assertEqual(DockerWorkerHandle._capture_tail(pipe), "capture_unavailable")
        finally:
            os.close(write_fd)

    def test_terminal_event_argv_is_original_cid_only_and_unchanged_bounded(self):
        from unittest import mock
        handle = self.make()
        with mock.patch.object(handle, "_command_runner", wraps=handle._command_runner) as runner:
            facts = handle.termination_facts()
        calls = [item for item in runner.call_args_list if item.args[0][1] == "events"]
        self.assertEqual(len(calls), 1)
        command = calls[0].args[0]
        filters = [command[index + 1] for index, item in enumerate(command[:-1]) if item == "--filter"]
        self.assertEqual(filters, ["type=container", "container=" + "a" * 64,
                                   "event=die", "event=oom", "event=kill", "event=destroy"])
        self.assertEqual(calls[0].kwargs["timeout"], 2.0)
        self.assertEqual(facts["engine_events"]["records"][0]["action"], "die")
        self.assertLessEqual(len(json.dumps(facts).encode()), 16384)

    def test_live_frontend_is_snapshot_and_healthcheck_event_is_not_terminal(self):
        from unittest import mock
        handle = self.make()
        handle._process.status = None
        original = handle._command_runner
        def runner(command, **kwargs):
            if command[1] == "events":
                return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"action": "exec_start", "id": "a" * 64, "timeNano": 1}), stderr="")
            return original(command, **kwargs)
        with mock.patch.object(handle, "_command_runner", side_effect=runner):
            facts = handle.termination_facts()
        self.assertIsNone(facts["frontend_process"]["exit_code"])
        self.assertTrue(facts["engine_state"]["facts"]["running"])
        self.assertIsNone(facts["oom_observation"]["value"])
        self.assertEqual(facts["engine_events"]["status"], "unavailable")
        self.assertEqual(facts["engine_events"]["records"], [])

if __name__=="__main__":unittest.main()
