"""Real small Linux children prove original observer behavior without Docker."""
from __future__ import annotations
from contextlib import contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import socket
import shutil
import subprocess
import sys
import tempfile
import time
import tracemalloc
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from publication_operational_request_domain_v1 import canonical_json_v1, payload_with_sha256_v1
from publication_child_evidence_materializer_v1 import materialize_publication_child_evidence_group_v1
import publication_operational_process_custody_v1 as observer
import publication_policy_qualification_runtime_inputs_v2 as stock_runtime
from publication_operational_process_custody_v1 import (
    capture_original_engine_processes_v1, original_engine_phase_v1,
    engine_process_started_v1, engine_process_terminal_v1, original_process_validator_v1,
)


@unittest.skipUnless(sys.platform.startswith("linux"), "actual /proc process custody requires Linux")
class ProcessCustodyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "inputs").mkdir()
        (self.root / "outputs").mkdir()
        self.context = self.write("inputs/context.json", {"fixture_only": True, "operation_id": "original-1"})
        self.image = {"image_id": "sha256:" + "1" * 64, "repository_digest": "fixture/image@sha256:" + "2" * 64,
                      "inspect_projection_sha256": "3" * 64, "base_image_id": "sha256:" + "4" * 64}
        self.capture_count = 0
        executable = Path(sys.executable).resolve()
        self.engine_fd = os.open(executable, os.O_RDONLY)
        self.addCleanup(os.close, self.engine_fd)
        raw = executable.read_bytes()
        self.engine = SimpleNamespace(path=executable, fd=self.engine_fd, size=len(raw),
                                      sha256=hashlib.sha256(raw).hexdigest(), proc_path=f"/proc/self/fd/{self.engine_fd}")
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(self.sock.close)
        socket_path = self.root / "engine.sock"
        self.sock.bind(str(socket_path))
        info = socket_path.lstat()
        self.socket_pin = {"path": str(socket_path), "device": info.st_dev, "inode": info.st_ino,
                           "owner_uid": info.st_uid, "owner_gid": info.st_gid}

    def write(self, name, value):
        path = self.root / name
        raw = canonical_json_v1(value) + b"\n"
        path.write_bytes(raw)
        return {"path": str(path), "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

    def capture(self, **changes):
        self.capture_count += 1
        number = self.capture_count
        self.source = self.root / f"scratch-{number}" / "operational"
        self.source.mkdir(parents=True)
        self.first_target = self.root / f"outputs/native-{number}"
        final_target = changes.pop("final_target", self.first_target)
        output_dir = changes.get("output_dir", self.root / "outputs/process")
        self.original = self.write(f"inputs/original-{number}.json", payload_with_sha256_v1({
            "schema_version": 1, "artifact_kind": "vast_original_native_operation_input_v1",
            "operation": {"fixture_only": True, "operation_id": "original-1", "system": "gstreamer"},
            "container_image": self.image,
            "outputs": {"measurement_dir": str(self.root / f"outputs/measurement-{number}"),
                        "native_domain": str(final_target / "native_operational_requests.v1.jsonl"),
                        "process_receipt": str(output_dir / "original_engine_process_capture.v1.json"),
                        "container_receipt": str(self.root / f"outputs/container-{number}/container-custody.v1.json")}}))
        args = dict(project_root=self.root, output_dir=self.root / "outputs/process", operation_id="original-1",
                    original_operation_descriptor=self.original, native_context_descriptor=self.context, container_image=self.image)
        args.update(changes)
        return capture_original_engine_processes_v1(**args)

    @contextmanager
    def process(self, program):
        argv = ["-c", program]
        if observer._phase.get() == "measurement":
            argv.extend(("--mount", f"type=bind,src={self.root / 'inputs'},dst=/workspace/project,readonly",
                         "--mount", f"type=bind,src={self.source},dst=/opt/vast/operational",
                         "--operational-request-context", "/workspace/project/context.json",
                         "--operational-output-dir", "/opt/vast/operational"))
        process = subprocess.Popen([self.engine.proc_path, *argv], executable=self.engine.proc_path,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, pass_fds=(self.engine_fd,))
        try:
            yield process, argv
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate()

    def run_child(self, program="print('original output')", *, phase="measurement", timeout=None):
        with original_engine_phase_v1(phase), self.process(program) as (process, argv):
            token = engine_process_started_v1(process, self.engine, self.socket_pin, argv)
            timed_out = False
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                process.kill()
                stdout, stderr = process.communicate()
            engine_process_terminal_v1(token, process, stdout, stderr, timed_out, False, False)
            capture = observer.current_original_engine_capture_v1()
            if phase == "measurement" and process.returncode == 0 and not timed_out and capture.native_transfer is None:
                self.transfer()
            return process.pid, stdout, stderr

    def materialize(self, source, target):
        target.mkdir()
        return materialize_publication_child_evidence_group_v1(
            project_root=self.root, source_dir=source, output_dir=target,
            target_names=("native_operational_requests.v1.jsonl",),
            evidence_mapping={"native_operational_requests.v1.jsonl": "native_operational_requests.v1.jsonl"},
            allowed_preexisting_names=(), maximum_bytes=64 * 1024 * 1024, label="fixture-only native custody")

    def transfer(self):
        # These are fixture bytes, never native-policy or model acceptance.
        (self.source / "native_operational_requests.v1.jsonl").write_bytes(getattr(self, "native_payload", b'{"fixture_only":true}\n'))
        result = self.materialize(self.source, self.first_target)
        observer.record_original_native_transfer_v1(self.source, self.first_target, result)

    def validate(self, capture):
        return original_process_validator_v1(project_root=self.root, receipt_path=Path(capture.receipt_descriptor["path"]),
            expected_descriptor=capture.receipt_descriptor, operation_id="original-1", original_operation_descriptor=capture.original,
            native_context_descriptor=capture.context, expected_container_image=capture.image)

    def test_genuine_original_process_launch_and_terminal_are_physically_bound(self):
        with self.capture() as capture:
            pid, stdout, stderr = self.run_child()
        self.assertIsNotNone(capture.receipt_descriptor)
        result = self.validate(capture)
        self.assertEqual(result["measurement"]["launch"]["child"]["pid"], pid)
        self.assertEqual(result["measurement"]["terminal"]["returncode"], 0)
        self.assertEqual(result["measurement"]["terminal"]["stdout"]["sha256"], hashlib.sha256(stdout).hexdigest())
        self.assertEqual(result["measurement"]["launch"]["controller"]["pid"], os.getpid())
        self.assertFalse(result["receipt"]["container_quiescence_verified"])
        for row in result["validated_inputs"]:
            info = Path(row["descriptor"]["path"]).stat()
            self.assertEqual(row["epoch"], [info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns])

    def test_inactive_observer_changes_nothing_and_does_not_require_mock_identity(self):
        token = engine_process_started_v1(SimpleNamespace(pid=99999999), None, None, ())
        self.assertIsNone(token)
        engine_process_terminal_v1(None, None, b"", b"", False, False, False)
        self.assertFalse((self.root / "outputs/process").exists())

    def test_nonzero_and_timeout_cannot_emit_success(self):
        for ordinal, (program, timeout) in enumerate((("raise SystemExit(7)", None), ("import time;time.sleep(2)", 0.03))):
            with self.subTest(program=program), self.assertRaises(ValueError):
                with self.capture(output_dir=self.root / f"outputs/process-{ordinal}") as capture:
                    self.run_child(program, timeout=timeout)
            self.assertIsNotNone(capture.receipt_descriptor)
            with self.assertRaises(ValueError):
                self.validate(capture)

    def test_missing_phase_and_mock_pid_are_failures(self):
        with self.assertRaises(ValueError):
            with self.capture() as capture, self.process("print(1)") as (process, argv):
                engine_process_started_v1(process, self.engine, self.socket_pin, argv)
        with self.assertRaises(ValueError):
            with self.capture(output_dir=self.root / "outputs/mock") as capture, original_engine_phase_v1("measurement"):
                engine_process_started_v1(SimpleNamespace(pid=os.getpid()), self.engine, self.socket_pin, ("-c", "print(1)"))

    def test_missing_terminal_duplicate_measurement_and_source_drift_are_rejected(self):
        with self.assertRaises(ValueError):
            with self.capture() as capture, original_engine_phase_v1("measurement"), self.process("print(1)") as (process, argv):
                engine_process_started_v1(process, self.engine, self.socket_pin, argv)
                process.communicate()
        with self.assertRaises(ValueError):
            with self.capture(output_dir=self.root / "outputs/two") as capture:
                self.run_child()
                self.run_child()
        with self.assertRaises(ValueError):
            with self.capture(output_dir=self.root / "outputs/drift") as capture:
                self.run_child()
                path = Path(self.original["path"])
                path.write_bytes(path.read_bytes() + b" ")

    def test_legitimate_output_sibling_does_not_change_declared_original_custody(self):
        with self.capture() as capture:
            (self.root / "inputs/unrelated-output").mkdir()
            self.run_child()
        self.assertIsNotNone(capture.receipt_descriptor)
        self.validate(capture)

    def repin_record(self, capture, path, value):
        value = payload_with_sha256_v1(value)
        os.chmod(path, 0o600)
        raw = canonical_json_v1(value) + b"\n"
        path.write_bytes(raw)
        desc = {"path": str(path), "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        receipt_path = Path(capture.receipt_descriptor["path"])
        receipt = json.loads(receipt_path.read_bytes())
        for row in receipt["calls"]:
            for role in ("launch", "terminal"):
                if row[role]["path"] == str(path):
                    row[role] = desc
        if path == receipt_path:
            receipt = value
        receipt = payload_with_sha256_v1(receipt)
        os.chmod(receipt_path, 0o600)
        raw = canonical_json_v1(receipt) + b"\n"
        receipt_path.write_bytes(raw)
        capture.receipt_descriptor = {"path": str(receipt_path), "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

    def test_cold_validator_rejects_resealed_timeout_and_owner_substitution(self):
        with self.capture() as capture:
            self.run_child()
        receipt = json.loads(Path(capture.receipt_descriptor["path"]).read_bytes())
        terminal = Path(receipt["calls"][0]["terminal"]["path"])
        value = json.loads(terminal.read_bytes())
        value["timed_out"] = True
        self.repin_record(capture, terminal, value)
        with self.assertRaisesRegex(ValueError, "failed or capture"):
            self.validate(capture)

    def test_phase_probe_then_exactly_one_measurement_and_duplicate_terminal(self):
        with self.capture() as capture:
            self.run_child(phase="image_inspect")
            self.run_child()
        result = self.validate(capture)
        self.assertEqual(len(result["calls"]), 2)
        self.assertEqual(result["measurement"]["launch"]["phase"], "measurement")
        with self.assertRaises(ValueError):
            with self.capture(output_dir=self.root / "outputs/duplicate") as capture, original_engine_phase_v1("measurement"), self.process("print(1)") as (process, argv):
                token = engine_process_started_v1(process, self.engine, self.socket_pin, argv)
                stdout, stderr = process.communicate()
                engine_process_terminal_v1(token, process, stdout, stderr, False, False, False)
                engine_process_terminal_v1(token, process, stdout, stderr, False, False, False)

    def test_sticky_launch_persistence_failure_preserves_original_body_error(self):
        with self.assertRaisesRegex(RuntimeError, "original wrapper error"):
            with self.capture() as capture:
                with original_engine_phase_v1("measurement"), self.process("import time;time.sleep(.1)") as (process, argv):
                    with mock.patch.object(observer, "_write", side_effect=OSError("original write failed")):
                        with self.assertRaises(OSError):
                            engine_process_started_v1(process, self.engine, self.socket_pin, argv)
                    process.kill()
                    process.communicate()
                raise RuntimeError("original wrapper error")
        self.assertIsNotNone(capture.receipt_descriptor)
        with self.assertRaises(ValueError):
            self.validate(capture)

    def test_capture_bound_and_foreign_receipt_descriptor_are_rejected(self):
        with self.assertRaises(ValueError):
            with self.capture() as capture, original_engine_phase_v1("measurement"), self.process("print(1)") as (process, argv):
                token = engine_process_started_v1(process, self.engine, self.socket_pin, argv)
                stdout, stderr = process.communicate()
                engine_process_terminal_v1(token, process, stdout, stderr, False, True, False)
        with self.capture(output_dir=self.root / "outputs/valid") as capture:
            self.run_child()
        other = self.root / "outputs/foreign.json"
        other.write_bytes(Path(capture.receipt_descriptor["path"]).read_bytes())
        with self.assertRaisesRegex(ValueError, "descriptor path differs"):
            original_process_validator_v1(project_root=self.root, receipt_path=other, expected_descriptor=capture.receipt_descriptor,
                operation_id="original-1", original_operation_descriptor=self.original, native_context_descriptor=self.context,
                expected_container_image=self.image)

    def _assert_failed_measurement_raw(self, capture, stdout, stderr):
        receipt = json.loads(Path(capture.receipt_descriptor["path"]).read_bytes())
        self.assertEqual(set(receipt), observer.RECEIPT_FIELDS)
        self.assertEqual(receipt["failure"], "original_engine_terminal_failed")
        self.assertEqual(set(receipt["calls"][0]), {"call_seq", "phase", "launch", "terminal"})
        row = receipt["calls"][0]
        terminal = json.loads(Path(row["terminal"]["path"]).read_bytes())
        self.assertEqual(set(terminal), observer.TERMINAL_FIELDS)
        adjunct_path = capture.output_dir / "engine_01.failure.v1.json"
        adjunct = json.loads(adjunct_path.read_bytes())
        self.assertLessEqual(adjunct_path.stat().st_size, 4096)
        self.assertEqual(adjunct["sha256"], payload_with_sha256_v1(adjunct)["sha256"])
        self.assertEqual(adjunct["operation_id"], capture.operation_id)
        self.assertEqual((adjunct["call_seq"], adjunct["phase"]), (1, "measurement"))
        self.assertEqual(adjunct["launch_descriptor"], row["launch"])
        self.assertEqual(adjunct["terminal_descriptor"], row["terminal"])
        for key in ("returncode", "timed_out", "capture_exceeded", "capture_drain_failed"):
            self.assertEqual(adjunct[key], terminal[key])
        for channel, expected in (("stdout", stdout), ("stderr", stderr)):
            descriptor = adjunct[channel]
            path = Path(descriptor["path"])
            self.assertEqual(path.read_bytes(), expected)
            self.assertEqual(descriptor["size_bytes"], len(expected))
            self.assertEqual(descriptor["sha256"], hashlib.sha256(expected).hexdigest())
            self.assertEqual({key: descriptor[key] for key in ("size_bytes", "sha256")}, terminal[channel])
            self.assertEqual(path.stat().st_nlink, 1)
            self.assertEqual(path.stat().st_mode & 0o777, 0o444)
        self.assertFalse(adjunct["authorizing"])
        self.assertFalse(adjunct["accepted"])
        self.assertFalse(adjunct["publication_ready"])
        self.assertEqual(receipt["status"], "failed_original_cli_capture")
        with self.assertRaises(ValueError):
            self.validate(capture)
        return adjunct

    def test_failed_measurement_retains_actual_binary_channels_and_unchanged_terminal(self):
        stdout, stderr = b"\x00original-out\xff\n", b"\x00original-error\xfe\n"
        program = ("import sys;sys.stdout.buffer.write(" + repr(stdout) + ");"
                   "sys.stderr.buffer.write(" + repr(stderr) + ");raise SystemExit(7)")
        with self.assertRaisesRegex(ValueError, "original_engine_terminal_failed"):
            with self.capture() as capture:
                pid, observed_out, observed_err = self.run_child(program)
        self.assertEqual((observed_out, observed_err), (stdout, stderr))
        self.assertFalse(Path(f"/proc/{pid}").exists())
        adjunct = self._assert_failed_measurement_raw(capture, stdout, stderr)
        self.assertEqual(adjunct["returncode"], 7)
        self.assertFalse(adjunct["timed_out"])

    def test_success_and_nonmeasurement_failure_write_no_measurement_adjunct(self):
        with self.capture() as capture:
            self.run_child()
        self.validate(capture)
        self.assertEqual(list(capture.output_dir.glob("*.failure.*")), [])
        with self.assertRaises(ValueError):
            with self.capture(output_dir=self.root / "outputs/probe-failure") as capture:
                self.run_child("raise SystemExit(7)", phase="image_inspect")
        self.assertEqual(list(capture.output_dir.glob("*.failure.*")), [])

    def test_failed_measurement_empty_channels_and_actual_timeout_are_retained(self):
        for ordinal, (program, timeout) in enumerate((("raise SystemExit(7)", None),
                ("import time;time.sleep(2)", 0.03))):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                with self.capture(output_dir=self.root / f"outputs/empty-{ordinal}") as capture:
                    self.run_child(program, timeout=timeout)
            adjunct = self._assert_failed_measurement_raw(capture, b"", b"")
            self.assertEqual(adjunct["timed_out"], timeout is not None)
            self.assertEqual(adjunct["stdout"]["size_bytes"], 0)
            self.assertEqual(adjunct["stderr"]["size_bytes"], 0)

    def test_empty_failure_channel_mode_follows_custody_posix_mode_enforcement(self):
        # A 9p/drvfs root without metadata reports a created 0444 leaf as 0555.
        # The empty channel accepts it only where custody does not enforce modes.
        for ordinal, enforced in enumerate((False, True)):
            output_dir = self.root / f"outputs/empty-mode-{ordinal}"
            with self.subTest(enforced=enforced), \
                    self.assertRaises((ValueError, observer.PublicationPhysicalIoV1Error)):
                # The capture has no measurement call, so its own exit always fails.
                with self.capture(output_dir=output_dir) as capture:
                    custody = capture.custody
                    create = custody._write_exclusive_posix

                    def reported_as_0555(relative, payload, *, label, mode, create_parents):
                        self.assertEqual(mode, 0o444)
                        return create(relative, payload, label=label, mode=0o555, create_parents=create_parents)

                    path = output_dir / "engine_01.failure.stderr.raw"
                    with mock.patch.object(custody, "_posix_mode_enforced", enforced), \
                            mock.patch.object(custody, "_write_exclusive_posix", reported_as_0555):
                        if enforced:
                            with self.assertRaises((ValueError, observer.PublicationPhysicalIoV1Error)):
                                observer._write_failure_channel(capture, path, b"")
                        else:
                            try:
                                descriptor = observer._write_failure_channel(capture, path, b"")
                                capture.verify()
                            except (ValueError, observer.PublicationPhysicalIoV1Error) as error:
                                self.fail(f"unenforced 0555 empty channel was rejected: {error}")
                            self.assertEqual(descriptor, {"path": str(path), "size_bytes": 0,
                                                          "sha256": hashlib.sha256(b"").hexdigest()})
                            self.assertEqual(path.stat().st_mode & 0o777, 0o555)
                            self.assertEqual(len(capture.empty_failure_channels), 1)

    def test_failed_measurement_capture_flags_keep_original_prefix_and_bounds(self):
        # Flag transport is an explicit wrapper fixture; these are genuine
        # original children, not a claim of actual pipe overflow/drain failure.
        for ordinal, flags in enumerate(((False, True, False), (False, False, True))):
            with self.subTest(flags=flags), self.assertRaises(ValueError):
                with self.capture(output_dir=self.root / f"outputs/flags-{ordinal}") as capture, \
                        original_engine_phase_v1("measurement"), self.process("print('prefix')") as (process, argv):
                    token = engine_process_started_v1(process, self.engine, self.socket_pin, argv)
                    stdout, stderr = process.communicate()
                    engine_process_terminal_v1(token, process, stdout, stderr, *flags)
            adjunct = self._assert_failed_measurement_raw(capture, stdout, stderr)
            self.assertEqual(tuple(adjunct[key] for key in ("timed_out", "capture_exceeded", "capture_drain_failed")), flags)
        with self.assertRaisesRegex(ValueError, "captures exceed source bounds"):
            with self.capture(output_dir=self.root / "outputs/over-bound") as capture, \
                    original_engine_phase_v1("measurement"), self.process("raise SystemExit(7)") as (process, argv):
                token = engine_process_started_v1(process, self.engine, self.socket_pin, argv)
                process.communicate()
                engine_process_terminal_v1(token, process, b"x" * (observer.MAX_CAPTURE_BYTES + 1), b"", False, False, False)
        self.assertEqual(list(capture.output_dir.glob("*.failure.*")), [])

    def test_failed_measurement_exclusive_collision_preserves_primary_and_written_channel(self):
        # A nonempty and a genuinely empty already occupied raw leaf must both
        # refuse adoption; stdout written first survives the stderr collision.
        for ordinal, occupied in enumerate((b"foreign", b"")):
            with self.subTest(occupied=occupied), self.assertRaises(observer.PublicationPhysicalIoV1Error):
                with self.capture(output_dir=self.root / f"outputs/collision-{ordinal}") as capture, \
                        original_engine_phase_v1("measurement"), self.process(
                            "import sys;print('original');" + ("sys.stderr.write('original stderr');" if ordinal == 0 else "")
                            + "raise SystemExit(7)") as (process, argv):
                    token = engine_process_started_v1(process, self.engine, self.socket_pin, argv)
                    stdout, stderr = process.communicate()
                    collision = capture.output_dir / "engine_01.failure.stderr.raw"
                    collision.write_bytes(occupied)
                    engine_process_terminal_v1(token, process, stdout, stderr, False, False, False)
            self.assertEqual(collision.read_bytes(), occupied)
            self.assertEqual((capture.output_dir / "engine_01.failure.stdout.raw").read_bytes(), stdout)
            self.assertFalse((capture.output_dir / "engine_01.failure.v1.json").exists())
            receipt = json.loads(Path(capture.receipt_descriptor["path"]).read_bytes())
            self.assertEqual(receipt["failure"], "original_engine_terminal_failed")
            self.assertIsNotNone(receipt["calls"][0]["terminal"])

    def test_failed_measurement_adjunct_persistence_error_keeps_original_wrapper_error(self):
        real_write = observer._write
        def fault(custody, path, value, maximum):
            if path.name.endswith(".failure.v1.json"):
                raise OSError("actual adjunct persistence fixture")
            return real_write(custody, path, value, maximum)
        with self.assertRaisesRegex(RuntimeError, "original wrapper body"):
            with self.capture() as capture, original_engine_phase_v1("measurement"), \
                    self.process("raise SystemExit(7)") as (process, argv):
                token = engine_process_started_v1(process, self.engine, self.socket_pin, argv)
                stdout, stderr = process.communicate()
                with mock.patch.object(observer, "_write", side_effect=fault):
                    with self.assertRaisesRegex(OSError, "adjunct persistence"):
                        engine_process_terminal_v1(token, process, stdout, stderr, False, False, False)
                raise RuntimeError("original wrapper body")
        receipt = json.loads(Path(capture.receipt_descriptor["path"]).read_bytes())
        self.assertEqual(receipt["failure"], "original_engine_terminal_failed")
        self.assertEqual(receipt["body_error"]["type"], "RuntimeError")
        self.assertEqual((capture.output_dir / "engine_01.failure.stdout.raw").read_bytes(), b"")
        self.assertEqual((capture.output_dir / "engine_01.failure.stderr.raw").read_bytes(), b"")
        self.assertFalse((capture.output_dir / "engine_01.failure.v1.json").exists())

    def _capacity_ready(self, process):
        import select
        readable, _, _ = select.select([process.stdout], [], [], 5)
        if not readable or process.stdout.readline(7) != b"READY\n":
            raise RuntimeError("capacity fixture child failed before readiness")
        self.assertIsNone(process.poll())
        return b"READY\n"

    def _run_capacity_child(self, *, phase="measurement"):
        # Only the capacity loop requires a live child until real registration.
        program = ("import sys;sys.stdout.buffer.write(b'READY\\n');sys.stdout.buffer.flush();"
                   "gate=sys.stdin.buffer.read(1);"
                   "sys.exit(77) if gate!=b'G' else print('original output')")
        with original_engine_phase_v1(phase):
            argv = ["-c", program]
            if phase == "measurement":
                argv.extend(("--mount", f"type=bind,src={self.root / 'inputs'},dst=/workspace/project,readonly",
                             "--mount", f"type=bind,src={self.source},dst=/opt/vast/operational",
                             "--operational-request-context", "/workspace/project/context.json",
                             "--operational-output-dir", "/opt/vast/operational"))
            process = subprocess.Popen([self.engine.proc_path, *argv], executable=self.engine.proc_path,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, pass_fds=(self.engine_fd,))
            try:
                prefix = self._capacity_ready(process)
                token = engine_process_started_v1(process, self.engine, self.socket_pin, argv)
                # The actual observer returned before the parent releases input.
                self.assertIsNotNone(token)
                stdout, stderr = process.communicate(b"G", timeout=5)
                stdout = prefix + stdout
                engine_process_terminal_v1(token, process, stdout, stderr, False, False, False)
                capture = observer.current_original_engine_capture_v1()
                if phase == "measurement" and process.returncode == 0 and capture.native_transfer is None:
                    self.transfer()
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)

    def test_capacity_fixture_failed_ready_child_never_registers(self):
        with self.assertRaisesRegex(RuntimeError, "capacity fixture child failed before readiness"):
            with self.capture(output_dir=self.root / "outputs/failed-capacity-ready") as capture, \
                    original_engine_phase_v1("measurement"), self.process("raise SystemExit(7)") as (process, argv):
                self._capacity_ready(process)
                engine_process_started_v1(process, self.engine, self.socket_pin, argv)
        receipt = json.loads(Path(capture.receipt_descriptor["path"]).read_bytes())
        self.assertEqual(receipt["call_count"], 0)
        self.assertEqual(receipt["status"], "failed_original_cli_capture")
        self.assertIsNone(capture.native_transfer)

    def test_caught_invalid_phase_remains_sticky_and_call_capacity_is_bounded(self):
        with self.assertRaises(ValueError):
            with self.capture() as capture:
                with self.assertRaises(ValueError):
                    with original_engine_phase_v1("guessed-from-argv"):
                        pass
                with self.assertRaises(ValueError):
                    self.run_child()
        self.assertIsNotNone(capture.receipt_descriptor)
        with self.assertRaisesRegex(ValueError, "original engine phase missing or call capacity exhausted"):
            with self.capture(output_dir=self.root / "outputs/capacity") as capture:
                for _ in range(observer.MAX_CALLS - 1):
                    self._run_capacity_child(phase="image_inspect")
                self._run_capacity_child()
                self._run_capacity_child(phase="image_inspect")
        receipt = json.loads(Path(capture.receipt_descriptor["path"]).read_bytes())
        self.assertEqual(receipt["call_count"], 32)
        self.assertEqual(receipt["status"], "failed_original_cli_capture")

    def test_real_fast_zombie_preserves_actual_owner_without_inventing_executable_match(self):
        with self.capture() as capture, original_engine_phase_v1("measurement"), self.process("print('fast')") as (process, argv):
            deadline = time.monotonic() + 2.0
            while observer._owner_with_state(process.pid)[1] != "Z":
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.001)
            token = engine_process_started_v1(process, self.engine, self.socket_pin, argv)
            stdout, stderr = process.communicate()
            engine_process_terminal_v1(token, process, stdout, stderr, False, False, False)
            self.transfer()
        result = self.validate(capture)
        self.assertEqual(result["measurement"]["launch"]["executable_observation"], "exited_before_executable_observation")
        self.assertEqual(result["measurement"]["launch"]["child"]["pid"], process.pid)

    def test_stock_two_transfer_chain_accepts_retired_first_output_and_rejects_foreign_source(self):
        final = self.root / "outputs/final"
        with self.capture(final_target=final) as capture:
            self.run_child()
        self.materialize(self.first_target, final)
        shutil.rmtree(self.first_target)
        result = self.validate(capture)
        self.assertEqual(len(result["native_transfers"]), 2)
        # Re-sealing a new foreign source directory cannot replace the source
        # identity retained by the original stock first transfer receipt.
        second = result["native_transfers"][1]
        intent_path = Path(second["descriptors"]["intent"]["path"])
        intent = json.loads(intent_path.read_bytes())
        intent["source_directory_identity"][1] += 1
        intent.pop("intent_sha256")
        intent["intent_sha256"] = hashlib.sha256(canonical_json_v1(intent)).hexdigest()
        os.chmod(intent_path, 0o600)
        raw = canonical_json_v1(intent) + b"\n"
        intent_path.write_bytes(raw)
        receipt_path = Path(second["descriptors"]["receipt"]["path"])
        receipt = json.loads(receipt_path.read_bytes())
        receipt["intent_sha256"] = intent["intent_sha256"]
        receipt["intent"]["size_bytes"] = len(raw)
        receipt["intent"]["sha256"] = hashlib.sha256(raw).hexdigest()
        receipt.pop("receipt_sha256")
        receipt["receipt_sha256"] = hashlib.sha256(canonical_json_v1(receipt)).hexdigest()
        os.chmod(receipt_path, 0o600)
        receipt_path.write_bytes(canonical_json_v1(receipt) + b"\n")
        with self.assertRaisesRegex(ValueError, "not the original first output"):
            self.validate(capture)

    def test_cold_rejects_resealed_detached_context_mount_and_executable_enum(self):
        with self.capture() as capture:
            self.run_child()
        receipt = json.loads(Path(capture.receipt_descriptor["path"]).read_bytes())
        launch_path = Path(receipt["calls"][0]["launch"]["path"])
        launch = json.loads(launch_path.read_bytes())
        terminal_path = Path(receipt["calls"][0]["terminal"]["path"])
        original_terminal = json.loads(terminal_path.read_bytes())
        for field, replacement in (("executable_observation", None), ("measurement_binding", None)):
            with self.subTest(field=field):
                value = copy.deepcopy(launch)
                value[field] = replacement
                self.repin_record(capture, launch_path, value)
                current = json.loads(Path(capture.receipt_descriptor["path"]).read_bytes())
                terminal = copy.deepcopy(original_terminal)
                terminal["launch_descriptor"] = current["calls"][0]["launch"]
                self.repin_record(capture, terminal_path, terminal)
                with self.assertRaises(ValueError):
                    self.validate(capture)

    def test_actual_measurement_rejects_detached_context_bytes_before_launch_record(self):
        with self.assertRaisesRegex(ValueError, "context mount bytes"):
            with self.capture() as capture, original_engine_phase_v1("measurement"), self.process("print(1)") as (process, argv):
                self.write("inputs/foreign-context.json", {"foreign_context": True})
                changed = list(argv)
                changed[changed.index("--operational-request-context") + 1] = "/workspace/project/foreign-context.json"
                # Launch an actual child with the changed arguments; no mock
                # process/argv or trace-derived authority is used.
                process.communicate()
                child = subprocess.Popen([self.engine.proc_path, *changed], executable=self.engine.proc_path,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, pass_fds=(self.engine_fd,))
                try:
                    engine_process_started_v1(child, self.engine, self.socket_pin, changed)
                finally:
                    child.communicate()

    def test_missing_native_transfer_cannot_emit_success(self):
        with self.assertRaisesRegex(ValueError, "native_transfer_missing"):
            with self.capture() as capture, original_engine_phase_v1("measurement"), self.process("print(1)") as (process, argv):
                token = engine_process_started_v1(process, self.engine, self.socket_pin, argv)
                stdout, stderr = process.communicate()
                engine_process_terminal_v1(token, process, stdout, stderr, False, False, False)

    def test_sdk_image_contract_survives_original_capture_and_cold_validation(self):
        self.image = {"image_id": "sha256:" + "1" * 64, "repository_digest": "fixture/image@sha256:" + "2" * 64,
                      "inspect_sha256": "3" * 64, "coordinator_path": "/opt/vast/sdk/coordinator.py",
                      "required_labels": {"fixture-only": "true"}}
        with self.capture() as capture:
            self.run_child()
        self.assertEqual(self.validate(capture)["receipt"]["container_image"], self.image)

    def test_actual_stock_inspector_image_contracts_survive_original_capture(self):
        # Only Docker's inspect transport is a fixture. The stock four-system
        # projection validators and contract constructors execute unchanged.
        bindings, inspected = {}, {}
        native = {"openvino_gva": stock_runtime.openvino_runtime,
                  "gstreamer_custom": stock_runtime.gstreamer_runtime}
        for system in stock_runtime.SYSTEMS:
            if system in native:
                module = native[system]
                reference = module.EXPECTED_IMAGE_REFERENCE
                material = {"final_reference": reference, "image_id": module.EXPECTED_IMAGE_ID,
                    "repository_digest": module.EXPECTED_REPOSITORY_DIGEST,
                    "inspect_projection_sha256": module.EXPECTED_IMAGE_INSPECT_PROJECTION_SHA256}
                if system == "gstreamer_custom":
                    material["base_image_id"] = module.EXPECTED_BASE_IMAGE_ID
                raw = {"Architecture": "amd64", "Os": "linux", "Id": module.EXPECTED_IMAGE_ID,
                    "RepoDigests": [module.EXPECTED_REPOSITORY_DIGEST], "Config": {
                        "Entrypoint": [module.EXPECTED_IMAGE_ENTRYPOINT],
                        "Labels": dict(module.EXPECTED_IMAGE_LABELS), "User": module.EXPECTED_IMAGE_USER}}
                if system == "gstreamer_custom":
                    raw["Created"] = "1970-01-01T00:00:00Z"
                key = "openvino_gva_runtime_image" if system == "openvino_gva" else "gstreamer_runtime_image"
                binding = {key: material}
            else:
                module = stock_runtime.deepstream_runtime if system == "deepstream" else stock_runtime.savant_runtime
                repository = "fixture/" + system
                reference = repository + ":stock-image-shape"
                image_id = "sha256:" + "1" * 64
                digest = repository + "@sha256:" + "2" * 64
                raw = {"Architecture": "amd64", "Os": "linux", "Id": image_id,
                    "RepoDigests": [digest], "Config": {"Entrypoint": [module.EXPECTED_COORDINATOR_PATH],
                        "Labels": dict(module.REQUIRED_IMAGE_LABELS)}}
                if system == "deepstream":
                    binding = {"image_identity": {"final_reference": reference, "image_id": image_id,
                        "repository_digest": digest, "entrypoint": module.EXPECTED_COORDINATOR_PATH}}
                else:
                    binding = {"savant_runtime_image": {"identity": {"final_reference": reference,
                        "image_id": image_id, "repository_digests": [digest],
                        "entrypoint": [module.EXPECTED_COORDINATOR_PATH]}}}
            inspected[reference] = raw
            for resource in ("cpu", "gpu"):
                bindings[(system, resource)] = copy.deepcopy(binding)
        images = stock_runtime._inspect_runtime_images(SimpleNamespace(resource_bindings=bindings),
            engine=Path("/fixture/docker"), engine_socket=Path("/fixture/docker.sock"),
            dependencies=SimpleNamespace(inspect_image=lambda engine, socket, reference: copy.deepcopy(inspected[reference])))
        self.assertEqual(set(images["openvino_gva"]["contract"]),
            {"image_id", "repository_digest", "inspect_projection_sha256"})
        self.assertEqual(set(images["gstreamer_custom"]["contract"]),
            {"image_id", "repository_digest", "inspect_projection_sha256", "base_image_id"})
        for system in stock_runtime.SYSTEMS:
            with self.subTest(system=system):
                self.image = images[system]["contract"]
                with self.capture(output_dir=self.root / "outputs" / ("stock-" + system)) as capture:
                    self.run_child()
                result = self.validate(capture)
                self.assertEqual(result["receipt"]["container_image"], self.image)
                self.assertEqual(result["measurement"]["launch"]["container_image"], self.image)

    def test_gva_three_field_contract_rejects_missing_extra_and_invalid_projection(self):
        image = {"image_id": "sha256:" + "1" * 64,
            "repository_digest": "fixture/gva@sha256:" + "2" * 64,
            "inspect_projection_sha256": "3" * 64}
        for changed in ({key: value for key, value in image.items() if key != "image_id"},
                        {**image, "unknown": "fixture"}, {**image, "inspect_projection_sha256": "invalid"}):
            with self.subTest(image=changed), self.assertRaises(ValueError):
                observer._image(changed)

    def test_cold_native_transfer_hash_is_streamed_above_supplemental_memory_budget(self):
        self.native_payload = b'{"fixture_only":true}\n' * (35 * 1024 * 1024 // 22)
        with self.capture() as capture:
            self.run_child()
        tracemalloc.start()
        try:
            result = self.validate(capture)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 8 * 1024 * 1024)
        self.assertTrue(any(row["descriptor"]["size_bytes"] > 32 * 1024 * 1024 for row in result["validated_inputs"]))


if __name__ == "__main__":
    unittest.main()
