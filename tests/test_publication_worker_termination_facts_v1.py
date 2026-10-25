"""Original worker exit facts do not infer OOM or an actor from exit137."""
from __future__ import annotations
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from checkpoint_gstreamer_analytics_sidecar import DockerWorkerHandle
from checkpoint_gstreamer_analytics_sidecar import (
    DockerWorkerProcessFactory, ENGINE_OPENVINO_CPU, GStreamerAnalyticsSidecar,
    SidecarError, WorkerLaunchSpec,
)
from checkpoint_model_parity_materializer import NativeEndpointRunner, MaterializerError
from publication_guardian_preprocessing_contract_v1 import DirectoryFdCustodyV1
import checkpoint_gstreamer_analytics_sidecar as sidecar

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

class WorkerOutputBoundsTests(unittest.TestCase):
    def start_writer(self, root, program):
        project, bindings, runtime = (root / name for name in ("project", "bindings", "runtime"))
        for directory in (project, bindings, runtime):
            directory.mkdir()
        binding = bindings / "damage.json"
        binding.write_text("{}\n", encoding="ascii")
        worker = {"engine": ENGINE_OPENVINO_CPU, "image": "fixture-worker",
                  "image_id": "sha256:" + "b" * 64, "entrypoint": "/worker"}

        def popen(command, **kwargs):
            if "--cidfile" in command:
                Path(command[command.index("--cidfile") + 1]).write_text("a" * 64, encoding="ascii")
            return subprocess.Popen([sys.executable, "-I", "-S", "-B", "-c", program], **kwargs)

        def runner(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, stdout="fixture-daemon\n", stderr="")

        factory = DockerWorkerProcessFactory(project_root=project, binding_set_root=bindings,
                                             runtime_dir=runtime, command_runner=runner,
                                             popen_factory=popen)
        return factory.start(WorkerLaunchSpec(
            branch="damage", resource="cpu", engine=ENGINE_OPENVINO_CPU,
            binding_path=binding, socket_path=runtime / "damage.sock",
            container_binding_path="/run/vast/bindings/damage.json",
            container_socket_path="/run/vast/analytics/damage.sock",
            worker_config=worker, max_requests=1, lifecycle_id="c" * 32))

    @staticmethod
    def retained_bytes(capture):
        try:
            descriptor = capture.fileno()
        except (AttributeError, OSError, ValueError):
            return len(capture.getvalue())
        return os.fstat(descriptor).st_size

    def test_worker_output_does_not_allocate_diagnostic_disk_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch("checkpoint_gstreamer_analytics_sidecar.tempfile.TemporaryFile",
                            side_effect=AssertionError("worker output must not allocate a disk capture")):
                handle = self.start_writer(Path(temporary), "print('small output')")
            try:
                self.assertEqual(handle.wait(5.0), 0)
                self.assertIn("small output", handle.failure_diagnostic())
            finally:
                if handle.poll() is None:
                    handle._process.kill()
                    handle._process.wait(timeout=2)
                handle.close_diagnostics()

    def test_real_child_floods_both_channels_without_deadlock_or_unbounded_retention(self):
        program = """
import os, threading
def write(fd, byte, suffix):
    payload = byte * (1024 * 1024) + suffix
    while payload:
        payload = payload[os.write(fd, payload):]
threads = [threading.Thread(target=write, args=(1, b'O', b'stdout-final')),
           threading.Thread(target=write, args=(2, b'E', b'stderr-final'))]
for thread in threads: thread.start()
for thread in threads: thread.join()
"""
        with tempfile.TemporaryDirectory() as temporary:
            handle = self.start_writer(Path(temporary), program)
            try:
                self.assertEqual(handle.wait(8.0), 0)
                for capture, byte, suffix in ((handle._stdout_capture, "O", "stdout-final"),
                                               (handle._stderr_capture, "E", "stderr-final")):
                    self.assertLessEqual(self.retained_bytes(capture), 2048)
                    self.assertEqual(DockerWorkerHandle._capture_tail(capture),
                                     byte * (2048 - len(suffix)) + suffix)
            finally:
                if handle.poll() is None:
                    handle._process.kill()
                    handle._process.wait(timeout=2)
                handle.close_diagnostics()


class _OwnedEngine:
    """Finite external Docker boundary; never starts a container or a model."""
    cid = "a" * 64
    image = "sha256:" + "b" * 64

    def __init__(self):
        self.running = True
        self.labels = {}
        self.mutations = []
        self.probe_timeout = False
        self.daemon = "original-fixture-daemon"
        self.client_exit = 7
        self.lifecycle_id = "c" * 32
        self.stop_timeout = False
        self.kill_timeout = False

    def register(self, command):
        self.labels = dict(command[i + 1].split("=", 1) for i, item in enumerate(command)
                           if item == "--label")
        if "--cidfile" in command:
            Path(command[command.index("--cidfile") + 1]).write_text(self.cid, encoding="ascii")

    def runner(self, command, **kwargs):
        operation = command[1]
        status, output = 0, ""
        if operation == "info":
            output = self.daemon + "\n"
        elif operation == "run":
            self.register(command)
            if self.probe_timeout:
                raise subprocess.TimeoutExpired(command, kwargs.get("timeout", 120))
            output = json.dumps({"schema_version": 1,
                "artifact_kind": "vast_analytics_execution_worker_runtime_probe",
                "protocol_identity_sha256": sidecar.PROTOCOL_IDENTITY_SHA256,
                "engine": ENGINE_OPENVINO_CPU, "runtime_name": "OpenVINO",
                "runtime_version": "2026.1", "device_api": "CPU", "device_id": "original CPU",
                "native_inference_api": "openvino.CompiledModel.__call__",
                "execution_path": "openvino_cpu_native", "worker_implementation_sha256": "d" * 64,
                "socket_seqpacket": True, "scm_rights": True, "memfd_sealing": True,
                "model_loaded": False, "inference_performed": False})
            self.running = False
        elif operation == "inspect":
            if not self.running:
                status = 1
            elif command[3] == "{{.State.Pid}}":
                output = "42"
            elif '"labels"' in command[3]:
                output = json.dumps({"id": self.cid, "image": self.image,
                                     "labels": self.labels, "running": True})
            else:
                output = json.dumps({"id": self.cid, "image": self.image, "pid": 42,
                    "exit_code": 0, "oom_killed": False, "running": True,
                    "started_at": "2026-10-25T00:00:00Z", "finished_at": "0001-01-01T00:00:00Z"})
        elif operation == "ps":
            output = self.cid + "\n" if self.running else ""
        elif operation in {"stop", "kill", "rm"}:
            self.mutations.append(command)
            if command[-1] != self.cid:
                raise AssertionError("container mutation must target the original full CID")
            if (operation == "stop" and self.stop_timeout) or (operation == "kill" and self.kill_timeout):
                raise subprocess.TimeoutExpired(command, kwargs.get("timeout", 1))
            self.running = False
        else:
            raise AssertionError(command)
        return subprocess.CompletedProcess(command, status, stdout=output, stderr="")

    def factory(self, root):
        for name in ("project", "bindings", "runtime"):
            (root / name).mkdir()
        def popen(command, **kwargs):
            self.register(command)
            program = "raise SystemExit(0)" if self.client_exit == 0 else "raise SystemExit(7)"
            return subprocess.Popen([sys.executable, "-I", "-S", "-B", "-c", program], **kwargs)
        return DockerWorkerProcessFactory(project_root=root / "project", binding_set_root=root / "bindings",
                                         runtime_dir=root / "runtime", command_runner=self.runner,
                                         popen_factory=popen)

    def start(self, root, branch="damage"):
        factory = self.factory(root)
        binding = root / "bindings/damage.json"
        binding.write_text("{}\n", encoding="ascii")
        handle = factory.start(WorkerLaunchSpec(branch=branch, resource="cpu", engine=ENGINE_OPENVINO_CPU,
            binding_path=binding, socket_path=root / "runtime/damage.sock",
            container_binding_path="/run/vast/bindings/damage.json",
            container_socket_path="/run/vast/analytics/damage.sock",
            worker_config={"engine": ENGINE_OPENVINO_CPU, "image": "frozen-worker",
                           "image_id": self.image, "entrypoint": "/worker"},
            max_requests=1, lifecycle_id=self.lifecycle_id))
        handle._process.wait(timeout=3)
        return handle


class OwnedDockerCleanupTests(unittest.TestCase):
    @staticmethod
    def parity_owner(handle):
        # Isolate the real close operation from model loading and inference.
        owner = object.__new__(NativeEndpointRunner)
        owner._sockets, owner._clients, owner._listeners = {}, {}, {}
        owner._handles = {("damage", "cpu"): handle}
        owner._shutdown_timeout_s = 1.0
        owner._runtime_directory_custody = None
        owner._socket_retirement_directory_custody = None
        return owner

    def guardian_owner(self, root, handle):
        owner = object.__new__(GStreamerAnalyticsSidecar)
        owner._runtime_directory_custody = DirectoryFdCustodyV1.open_existing(
            root / "runtime", label="fixture guardian runtime")
        self.addCleanup(owner._runtime_directory_custody.close)
        owner.runtime_dir = root / "runtime"
        facts = owner.runtime_dir.stat()
        import stat
        owner._runtime_directory_identity = (facts.st_dev, facts.st_ino, stat.S_IFMT(facts.st_mode))
        owner._production = False
        owner._stop = threading.Event()
        owner._front_connections_lock = threading.Lock()
        owner._front_connections = set()
        owner._owned_sockets = []
        owner._bridge = None
        owner._connections = {}
        owner._handles = {("damage", "cpu"): handle}
        owner.shutdown_timeout_s = 1.0
        return owner

    def test_both_owners_retire_a_live_engine_after_its_client_exits_and_keep_failure(self):
        for kind in ("parity", "guardian"):
            with self.subTest(owner=kind), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                engine = _OwnedEngine()
                handle = engine.start(root)
                self.addCleanup(handle.close_diagnostics)
                if kind == "parity":
                    owner = self.parity_owner(handle)
                    try:
                        owner.close(require_clean=True)
                    except MaterializerError as error:
                        errors = [str(error)]
                    else:
                        errors = []
                else:
                    errors = self.guardian_owner(root, handle)._shutdown()
                self.assertFalse(engine.running, "client exit left the owned engine running")
                self.assertTrue(engine.mutations)
                self.assertTrue(errors, "forced engine cleanup cannot establish clean acceptance")
                text = "; ".join(errors)
                self.assertLess(text.index("worker_nonzero:7"), text.index("container_required_stop"))

    def test_probe_timeout_retires_its_owned_container(self):
        with tempfile.TemporaryDirectory() as temporary:
            engine = _OwnedEngine()
            engine.probe_timeout = True
            factory = engine.factory(Path(temporary))
            worker = {"engine": ENGINE_OPENVINO_CPU, "image": "frozen-worker",
                      "image_id": engine.image, "entrypoint": "/worker"}
            with self.assertRaises(SidecarError):
                factory.probe("cpu", worker)
            self.assertFalse(engine.running, "probe timeout stranded the owned container")
            self.assertTrue(engine.mutations)

    def test_parity_primary_error_survives_secondary_cleanup_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            engine = _OwnedEngine()
            handle = engine.start(Path(temporary))
            self.addCleanup(handle.close_diagnostics)
            caught = None
            try:
                with self.parity_owner(handle):
                    raise ValueError("original parity failure")
            except BaseException as error:
                caught = error
            self.assertIsInstance(caught, ValueError)
            self.assertEqual(str(caught), "original parity failure")
            self.assertTrue(getattr(caught, "__notes__", []), "cleanup failure must remain attached")
            self.assertFalse(engine.running)

    def test_clean_client_and_authenticated_rm_absence_succeed_for_both_owners(self):
        for kind in ("parity", "guardian"):
            with self.subTest(owner=kind), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                engine = _OwnedEngine()
                engine.client_exit = 0
                handle = engine.start(root)
                self.addCleanup(handle.close_diagnostics)
                engine.running = False
                if kind == "parity":
                    self.parity_owner(handle).close(require_clean=True)
                else:
                    self.assertEqual(self.guardian_owner(root, handle)._shutdown(), [])
                self.assertEqual(engine.mutations, [])
                self.assertFalse(handle._owned_container.cid_path.is_relative_to(root / "runtime"))

    def test_unknown_daemon_foreign_image_and_bad_cid_receipts_never_authorize_mutation(self):
        for fault in ("daemon", "image", "label", "cid", "malformed", "hardlink", "symlink", "missing"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                engine = _OwnedEngine()
                handle = engine.start(root)
                self.addCleanup(handle.close_diagnostics)
                receipt = handle._owned_container.cid_path
                if fault == "daemon": engine.daemon = "different-daemon"
                elif fault == "image": engine.image = "sha256:" + "e" * 64
                elif fault == "label": engine.labels["org.vast.worker.lifecycle"] = "e" * 32
                elif fault == "cid": receipt.write_text("e" * 64, encoding="ascii")
                elif fault == "malformed": receipt.write_text("invalid", encoding="ascii")
                elif fault == "hardlink": os.link(receipt, root / "foreign-link")
                elif fault == "symlink":
                    target = root / "foreign-cid"
                    target.write_text(engine.cid, encoding="ascii")
                    receipt.unlink()
                    receipt.symlink_to(target)
                else: receipt.unlink()
                with self.assertRaises(MaterializerError):
                    self.parity_owner(handle).close(require_clean=True)
                self.assertTrue(engine.running)
                self.assertEqual(engine.mutations, [])

    def test_unknown_first_worker_does_not_prevent_retiring_another_owned_engine(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first, second = root / "first", root / "second"
            first.mkdir(); second.mkdir()
            engine_a, engine_b = _OwnedEngine(), _OwnedEngine()
            engine_b.cid, engine_b.lifecycle_id = "e" * 64, "d" * 32
            a, b = engine_a.start(first), engine_b.start(second, branch="plate_number")
            self.addCleanup(a.close_diagnostics); self.addCleanup(b.close_diagnostics)
            a._owned_container.cid_path.write_text("invalid", encoding="ascii")
            owner = self.parity_owner(a)
            owner._handles[("plate_number", "cpu")] = b
            with self.assertRaises(MaterializerError):
                owner.close(require_clean=True)
            self.assertTrue(engine_a.running)
            self.assertEqual(engine_a.mutations, [])
            self.assertFalse(engine_b.running)
            self.assertTrue(engine_b.mutations)

    def test_cleanup_failure_and_original_deadline_remain_sticky(self):
        with tempfile.TemporaryDirectory() as temporary:
            engine = _OwnedEngine()
            handle = engine.start(Path(temporary))
            self.addCleanup(handle.close_diagnostics)
            owner = self.parity_owner(handle)
            with self.assertRaises(MaterializerError): owner.close(require_clean=True)
            deadline = owner._worker_cleanup_deadline
            with self.assertRaises(MaterializerError): owner.close(require_clean=False)
            self.assertEqual(owner._worker_cleanup_deadline, deadline)

    def test_probe_keeps_complete_json_and_preserves_cid_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            engine = _OwnedEngine()
            factory = engine.factory(root)
            result = factory.probe("cpu", {"engine": ENGINE_OPENVINO_CPU, "image": "frozen-worker",
                "image_id": engine.image, "entrypoint": "/worker"})
            self.assertIs(result["model_loaded"], False)
            self.assertIs(result["inference_performed"], False)
            self.assertEqual(engine.mutations, [])
            receipts = list(root.rglob("*.cid"))
            self.assertEqual(len(receipts), 1)
            self.assertEqual(receipts[0].read_text(encoding="ascii"), engine.cid)
            self.assertFalse(receipts[0].is_relative_to(root / "runtime"))

    def test_stop_and_kill_timeouts_remain_failed_and_do_not_reset_cleanup_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            engine = _OwnedEngine()
            engine.stop_timeout = engine.kill_timeout = True
            handle = engine.start(Path(temporary))
            self.addCleanup(handle.close_diagnostics)
            owner = self.parity_owner(handle)
            started = time.monotonic()
            with self.assertRaises(MaterializerError): owner.close(require_clean=True)
            self.assertLess(time.monotonic() - started, 1.5)
            self.assertEqual([command[1] for command in engine.mutations], ["stop", "kill"])
            self.assertTrue(engine.running)

    def test_output_reader_startup_failure_retires_the_created_client_and_engine(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            engine = _OwnedEngine()
            factory = engine.factory(root)
            original_popen = factory._popen_factory
            clients = []
            class BrokenStream:
                def __init__(self, stream): self.stream = stream
                def fileno(self): raise OSError("original output reader failure")
                def close(self): self.stream.close()
            def popen(command, **kwargs):
                client = original_popen(command, **kwargs)
                clients.append(client)
                client.stdout = BrokenStream(client.stdout)
                return client
            factory._popen_factory = popen
            binding = root / "bindings/damage.json"
            binding.write_text("{}\n", encoding="ascii")
            with self.assertRaisesRegex(SidecarError, "reader could not start") as caught:
                factory.start(WorkerLaunchSpec(branch="damage", resource="cpu", engine=ENGINE_OPENVINO_CPU,
                    binding_path=binding, socket_path=root / "runtime/damage.sock",
                    container_binding_path="/run/vast/bindings/damage.json",
                    container_socket_path="/run/vast/analytics/damage.sock",
                    worker_config={"engine": ENGINE_OPENVINO_CPU, "image": "frozen-worker",
                                   "image_id": engine.image, "entrypoint": "/worker"},
                    max_requests=1, lifecycle_id=engine.lifecycle_id))
            self.assertIsInstance(caught.exception.__cause__, OSError)
            self.assertFalse(engine.running)
            self.assertTrue(clients and all(client.poll() is not None for client in clients))


class BoundedEngineCaptureTests(unittest.TestCase):
    def test_worker_pid_lookup_refuses_oversized_complete_response(self):
        def runner(command, **kwargs):
            if command[1] == "inspect" and command[3] == "{{.State.Pid}}":
                output = " " * 9000 + "42"
            elif command[1] == "inspect":
                output = json.dumps({"id": "a" * 64, "image": "sha256:" + "b" * 64,
                    "pid": 42, "exit_code": 0, "oom_killed": False, "running": True,
                    "started_at": "2026-10-25T00:00:00Z", "finished_at": "0001-01-01T00:00:00Z"})
            else:
                output = "original-daemon"
            return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")
        handle = DockerWorkerHandle(Process(), container_name="original-worker",
            command_runner=runner, platform_observer=lambda: {},
            stdout_capture=io.BytesIO(), stderr_capture=io.BytesIO())
        self.addCleanup(handle.close_diagnostics)
        with self.assertRaisesRegex(SidecarError, "bounded capture"):
            handle.expected_peer_pid(0.1)

    def test_secondary_failure_notes_do_not_require_python311_exception_methods(self):
        class OlderRuntimeError(Exception):
            add_note = None
        primary = OlderRuntimeError("original failure")
        sidecar._note_failure(primary, "distinct cleanup failure")
        self.assertEqual(str(primary), "original failure")
        self.assertEqual(sidecar._failure_text(primary), "original failure; distinct cleanup failure")

    def test_complete_protocol_response_rejects_invalid_utf8(self):
        program = "import os; os.write(1, b'{\"padding\":\"' + bytes([255]) + b'\"}')"
        with self.assertRaises(UnicodeDecodeError):
            sidecar._bounded_engine_observation(
                [sys.executable, "-I", "-S", "-B", "-c", program], timeout=3.0)

    def test_complete_response_preserves_prefix_and_refuses_overflow(self):
        program = "import json; print(json.dumps({'padding': 'x' * 5000}))"
        result = sidecar._bounded_engine_observation(
            [sys.executable, "-I", "-S", "-B", "-c", program], timeout=3.0)
        self.assertEqual(json.loads(result.stdout), {"padding": "x" * 5000})
        with self.assertRaisesRegex(SidecarError, "bounded capture"):
            sidecar._bounded_engine_observation(
                [sys.executable, "-I", "-S", "-B", "-c", "import os; os.write(1, b'x' * 20000)"],
                timeout=3.0)

    def test_held_open_pipe_is_bounded_failed_and_actual_readers_retire(self):
        import signal
        real_popen, real_capture = subprocess.Popen, sidecar._BoundedPipeCapture
        processes, captures = [], []
        def popen(*args, **kwargs):
            process = real_popen(*args, start_new_session=True, **kwargs)
            processes.append(process)
            return process
        def capture(*args, **kwargs):
            value = real_capture(*args, **kwargs)
            captures.append(value)
            return value
        program = "import os,time; child=os.fork(); time.sleep(30) if child==0 else None; os._exit(0)"
        started = time.monotonic()
        try:
            with mock.patch.object(sidecar.subprocess, "Popen", side_effect=popen), \
                    mock.patch.object(sidecar, "_BoundedPipeCapture", side_effect=capture):
                with self.assertRaisesRegex(SidecarError, "retirement"):
                    sidecar._bounded_engine_observation(
                        [sys.executable, "-I", "-S", "-B", "-c", program], timeout=0.3)
            self.assertLess(time.monotonic() - started, 1.5)
            self.assertTrue(captures)
            self.assertTrue(all(not value._thread.is_alive() for value in captures))
        finally:
            for process in processes:
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                process.wait(timeout=1)


if __name__=="__main__":unittest.main()
