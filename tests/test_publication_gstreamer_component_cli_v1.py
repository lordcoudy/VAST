"""Local orchestration fixtures; no Docker, guardian, model or hardware acceptance."""
from __future__ import annotations

import contextlib
import importlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


class ComponentCliTests(unittest.TestCase):
    def test_original_pair_retains_bounded_phase_starts_and_real_terminals(self):
        self.cli.run_component_pair_v1(**self.arguments, _dependencies=self.dependencies())
        path = self.root / "result/component_pair_timing.v1.jsonl"
        self.assertTrue(path.is_file(), "original pair must persist its bounded phase timeline")
        self.assertLessEqual(path.stat().st_size, 16 * 1024)
        rows = [json.loads(line) for line in path.read_bytes().splitlines()]
        starts = {row["phase"]: row for row in rows if row["event"] == "start"}
        terminals = {row["phase"]: row for row in rows if row["event"] == "terminal"}
        self.assertLessEqual(len(starts), 12)
        self.assertEqual(set(starts), set(terminals))
        self.assertTrue({"source", "runtime", "arm_baseline", "arm_shared", "cold"} <= set(starts))
        for name, terminal in terminals.items():
            self.assertEqual(terminal["status"], "complete")
            self.assertEqual(terminal["elapsed_ns"], terminal["monotonic_ns"] - starts[name]["monotonic_ns"])
        self.assertEqual(self.calls.count("source"), 1)

    def test_failed_original_arm_timeline_does_not_invent_later_phases(self):
        with self.assertRaisesRegex(RuntimeError, "original baseline inference failed"):
            self.cli.run_component_pair_v1(**self.arguments, _dependencies=self.dependencies(fail_operation="baseline"))
        path = self.root / "result/component_pair_timing.v1.jsonl"
        self.assertTrue(path.is_file(), "failed original must retain real phase facts")
        rows = [json.loads(line) for line in path.read_bytes().splitlines()]
        terminals = {row["phase"]: row for row in rows if row["event"] == "terminal"}
        self.assertEqual(terminals["arm_baseline"]["status"], "failed")
        self.assertEqual(terminals["arm_baseline"]["error_type"], "RuntimeError")
        self.assertNotIn("arm_shared", {row["phase"] for row in rows})
        self.assertNotIn("cold", {row["phase"] for row in rows})
        self.assertTrue(self.guardian.closed)

    def test_default_cli_owns_one_private_context_through_original_cold_and_stop(self):
        import publication_gstreamer_component_inputs_v1 as inputs
        import publication_gstreamer_component_runtime_v1 as runtime
        deps = self.dependencies()
        private_token, session_events = object(), []
        @contextlib.contextmanager
        def session(**arguments):
            session_events.append("open")
            self.assertEqual(arguments["project_root"], self.root)
            self.assertTrue(Path(arguments["component_authority_path"]).is_file())
            try:
                yield private_token
            finally:
                session_events.append("close")
                self.assertTrue(self.guardian.closed)
                self.assertIn("cold", self.calls)
        def route(method):
            def call(token, **arguments):
                self.assertIs(token, private_token)
                self.assertEqual(session_events, ["open"])
                return method(**arguments)
            return call
        sidecar = self.root / "scripts/checkpoint_gstreamer_analytics_sidecar.py"
        sidecar.parent.mkdir()
        sidecar.write_bytes(b"# original unavailable guardian fixture\n")
        with mock.patch.object(self.cli, "_dependencies", return_value=deps), \
             mock.patch.object(inputs, "_held_selected_component_session_v1", session), \
             mock.patch.object(runtime, "_materialize_component_runtime_from_session_v1", side_effect=route(deps.runtime)), \
             mock.patch.object(runtime, "_execute_component_operation_from_session_v1", side_effect=route(deps.execute)), \
             mock.patch.object(runtime, "_cold_component_pair_from_session_v1", side_effect=route(deps.cold)):
            self.cli.run_component_pair_v1(**self.arguments)
        self.assertEqual(session_events, ["open", "close"])
        rows = [json.loads(line) for line in (self.root / "result/component_pair_timing.v1.jsonl").read_bytes().splitlines()]
        self.assertTrue(all(row["explicit_fixture_dependencies"] is False for row in rows))
        # This route test mocks unavailable model/native actions explicitly;
        # the real held-context/factory tests establish the physical checks.

    def test_timing_terminal_write_failure_keeps_start_and_performs_owned_cleanup(self):
        original_write, timeline_fds = os.write, []
        original_init = self.cli._PhaseTimelineV1.__init__
        def initialized(timeline, *arguments, **keywords):
            original_init(timeline, *arguments, **keywords)
            timeline_fds.append(timeline.fd)
        def write(fd, raw):
            if b'"phase":"arm_baseline"' in raw and b'"event":"terminal"' in raw:
                raise OSError("original phase terminal storage failure")
            return original_write(fd, raw)
        dependencies = self.dependencies()
        dependencies.reserve = self.cli._scratch_reserve_v1
        with mock.patch.object(self.cli._PhaseTimelineV1, "__init__", initialized), \
             mock.patch.object(os, "write", side_effect=write), \
             mock.patch.object(self.cli, "RESERVE_BYTES", 4096), \
             mock.patch.object(self.cli, "FREE_FLOOR_BYTES", 4096):
            with self.assertRaisesRegex(OSError, "original phase terminal storage failure"):
                self.cli.run_component_pair_v1(**self.arguments, _dependencies=dependencies)
        self.assertTrue(self.guardian.closed)
        self.assertNotIn("execute_shared", self.calls)
        self.assertNotIn("cold", self.calls)
        rows = [json.loads(line) for line in (self.root / "result/component_pair_timing.v1.jsonl").read_bytes().splitlines()]
        self.assertTrue(any(row["phase"] == "arm_baseline" and row["event"] == "start" for row in rows))
        self.assertFalse(any(row["phase"] == "arm_baseline" and row["event"] == "terminal" for row in rows))
        terminal = json.loads((self.root / "result" / self.cli.TERMINAL_FILENAME).read_bytes())
        self.assertEqual(terminal["status"], "failed")
        self.assertIsNone(terminal["phase_timing"])
        self.assertTrue(terminal["capacity_reservation"]["released"])
        self.assertFalse(Path(terminal["capacity_reservation"]["path"]).exists())
        for fd in timeline_fds:
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_timeline_has_exact_fixed_names_and_rejects_oversize_before_write(self):
        with self.cli.PhysicalRootCustodyV1.open(self.root, label="timing-only unit fixture") as custody:
            output = self.root / "timing"
            custody.ensure_directory_owned(output, label="fresh timing-only fixture")
            timeline = self.cli._PhaseTimelineV1(custody, output, fixture=True)
            for name in sorted(timeline.NAMES):
                with timeline.phase(name):
                    pass
            for name in ("source", "foreign"):
                with self.assertRaises(RuntimeError), timeline.phase(name):
                    pass
            descriptor = timeline.close()
            self.assertLessEqual(descriptor["size_bytes"], 16 * 1024)
            self.assertEqual(len(timeline.path.read_bytes().splitlines()), 24)
            other = self.root / "timing-overflow"
            custody.ensure_directory_owned(other, label="fresh overflow fixture")
            overflow = self.cli._PhaseTimelineV1(custody, other, fixture=True)
            with self.assertRaises(RuntimeError):
                overflow._emit({"padding": "x" * (16 * 1024)})
            self.assertEqual(overflow.path.stat().st_size, 0)
            with self.assertRaises(Exception):
                overflow.close()
            with self.assertRaises(OSError):
                os.fstat(overflow.fd)

    def setUp(self):
        self.cli = importlib.import_module("publication_gstreamer_component_cli_v1")
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.scratch = self.root / "scratch-base"
        self.scratch.mkdir()
        self.calls = []
        self.input_paths = {}
        for name in ("capability_manifest_path", "calibration_path", "model_parity_receipt_path",
                     "runtime_image_receipt_path", "worker_freeze_receipt_path", "execution_code_closure_path"):
            path = self.root / (name + ".json")
            path.write_text("{}\n")
            self.input_paths[name] = path
        self.arguments = {"project_root": self.root, "resource": "cpu", "output_dir": self.root / "result",
                          "scratch_root": self.scratch, **self.input_paths}
        self.guardian = self.Guardian(self)

    class Guardian:
        def __init__(self, test):
            self.test = test
            self.authority_path = None
            self.lifecycle_path = None
            self.started = False
            self.closed = False
            self.fail_close = False

        def start(self):
            self.test.calls.append("guardian_start")
            self.started = True
            return self.authority_path

        def check(self):
            self.test.calls.append("guardian_check")

        def close(self):
            self.test.calls.append("guardian_stop")
            self.closed = True
            if self.fail_close:
                raise RuntimeError("original guardian stop failed")
            return {"authenticated_stop": True, "process_quiescent": True, "container_cleanup_verified": True,
                    "returncode": 0, "stdout": b"original guardian stdout\n", "stderr": b""}

    @contextlib.contextmanager
    def reserve(self, **arguments):
        self.calls.append("reserve")
        yield {"reserved_bytes": self.cli.RESERVE_BYTES, "size_bytes": self.cli.RESERVE_BYTES,
               "allocated_bytes": self.cli.RESERVE_BYTES, "released": True}
        self.calls.append("release_reserve")

    def dependencies(self, fail_operation=None, fail_cold=False):
        def source(**arguments):
            self.calls.append("source")
            path = arguments["output_dir"] / "authority.json"
            path.parent.mkdir(parents=True)
            path.write_text("{}\n")
            return {"authority_path": path, "descriptor": {"path": str(path)}}

        def capture(**arguments):
            self.calls.append("capture")
            path = arguments["output_dir"] / "index.json"
            path.parent.mkdir(parents=True)
            path.write_text("{}\n")
            context = path.parent / "guardian-context.json"
            context.write_text("{}\n")
            return {"descriptor": {"path": str(path)}, "value": {"guardian_context": {"path": str(context)},
                "native_contexts": [{"operation_id":"baseline"},{"operation_id":"shared"}]}}

        def preprocessing(**arguments):
            self.calls.append("preprocessing")
            output = arguments["output_dir"]
            output.mkdir()
            contract, receipt = output / "contract.json", output / "receipt.json"
            contract.write_text("{}\n"); receipt.write_text("{}\n")
            return {"contract_path": contract, "receipt_path": receipt}

        def guardian_factory(**arguments):
            self.calls.append("guardian_factory")
            self.guardian.authority_path = arguments["evidence_root"] / "service_authority.v1.json"
            self.guardian.lifecycle_path = arguments["evidence_root"] / "service_lifecycle.v1.json"
            self.guardian.authority_path.parent.mkdir()
            self.guardian.authority_path.write_text("{}\n")
            self.guardian.lifecycle_path.write_text("{}\n")
            return self.guardian

        def runtime(**arguments):
            self.calls.append("runtime")
            self.assertEqual(arguments["guardian_authority_path"], self.guardian.authority_path)
            output = arguments["output_dir"]
            output.mkdir()
            records = []
            for name in ("baseline", "shared"):
                path = output / (name + ".json")
                path.write_text("{}\n")
                records.append({"operation_id": name, "descriptor": {"path": str(path)}})
            return {"receipt": {"bundles": records}}

        def execute(**arguments):
            operation = arguments["operation_id"]
            self.calls.append("execute_" + operation)
            if operation == fail_operation:
                raise RuntimeError("original " + operation + " inference failed")
            path = self.root / "result" / (operation + "-arm.json")
            path.write_text("{}\n")
            return {"descriptor": {"path": str(path)}}

        def cold(**arguments):
            self.calls.append("cold")
            self.assertTrue(self.guardian.closed)
            self.assertEqual(len(arguments["runtime_bundle_paths"]), 2)
            self.assertEqual(len(arguments["arm_result_paths"]), 2)
            if fail_cold:
                raise RuntimeError("original cold identity mismatch")
            path = arguments["output_dir"] / "pair.json"
            path.parent.mkdir()
            path.write_text("{}\n")
            return {"descriptor": {"path": str(path)}, "receipt": {"component_pairs": 1}}

        return SimpleNamespace(source=source, capture=capture, preprocessing=preprocessing,
                               guardian=guardian_factory, runtime=runtime, execute=execute, cold=cold,
                               reserve=self.reserve)

    def test_absolute_cli_inputs_cross_real_stock_source_pin_boundary(self):
        import publication_policy_qualification_runtime_inputs_v2 as stock
        dependencies = self.dependencies()
        original_source = dependencies.source
        original_capture = dependencies.capture
        observed = {}
        rejected = []

        def strict_source(**arguments):
            # Real stock filesystem pinning for every one of the six roles;
            # subsequent source/model/guardian work remains an explicit fixture.
            for name in self.cli.INPUT_NAMES:
                try:
                    pin = stock._project_pin(arguments["project_root"], arguments[name],
                                             label="selected component original input")
                    observed[name] = pin
                except stock.QualificationRuntimeInputMaterializationV2Error as error:
                    rejected.append(error)
            if rejected:
                raise rejected[0]
            return original_source(**arguments)

        def absolute_capture(**arguments):
            self.assertEqual(arguments["execution_code_closure_path"],
                             self.input_paths["execution_code_closure_path"])
            self.assertTrue(arguments["execution_code_closure_path"].is_absolute())
            return original_capture(**arguments)

        dependencies.source = strict_source
        dependencies.capture = absolute_capture
        result = self.cli.run_component_pair_v1(**self.arguments, _dependencies=dependencies)
        self.assertEqual(set(observed), set(self.cli.INPUT_NAMES))
        self.assertEqual(rejected, [])
        for name, pin in observed.items():
            self.assertEqual(pin.path, self.input_paths[name])
            self.assertEqual(pin.relative, self.input_paths[name].relative_to(self.root).as_posix())
        terminal = json.loads(Path(result["terminal_path"]).read_bytes())
        for name, path in self.input_paths.items():
            self.assertEqual(terminal["input_pins"][name]["descriptor"]["path"], str(path))
        self.assertEqual(terminal["status"], "component_pair_complete")

    def test_exact_two_original_operations_one_guardian_stop_before_cold(self):
        result = self.cli.run_component_pair_v1(**self.arguments, _dependencies=self.dependencies())
        self.assertEqual(self.calls.count("guardian_start"), 1)
        self.assertEqual([call for call in self.calls if call.startswith("execute_")],
                         ["execute_baseline", "execute_shared"])
        self.assertLess(self.calls.index("guardian_stop"), self.calls.index("cold"))
        self.assertEqual(self.calls[-1], "release_reserve")
        terminal = json.loads(Path(result["terminal_path"]).read_bytes())
        self.assertEqual(terminal["status"], "component_pair_complete")
        self.assertFalse(terminal["publication_ready"])
        self.assertEqual(terminal["full_arms"], 0)

    def test_original_failure_no_second_operation_and_authenticated_stop(self):
        with self.assertRaisesRegex(RuntimeError, "original baseline inference failed"):
            self.cli.run_component_pair_v1(**self.arguments, _dependencies=self.dependencies(fail_operation="baseline"))
        self.assertTrue(self.guardian.closed)
        self.assertNotIn("execute_shared", self.calls)
        self.assertNotIn("cold", self.calls)
        terminal = json.loads((self.root / "result" / self.cli.TERMINAL_FILENAME).read_bytes())
        self.assertEqual(terminal["status"], "failed")
        self.assertEqual(terminal["component_pairs"], 0)
        self.assertEqual((self.root / "result" / "guardian.stdout.log").read_bytes(), b"original guardian stdout\n")

    def test_stop_failure_preserves_original_body_cause_and_is_not_clean(self):
        self.guardian.fail_close = True
        with self.assertRaisesRegex(RuntimeError, "original baseline inference failed") as caught:
            self.cli.run_component_pair_v1(**self.arguments, _dependencies=self.dependencies(fail_operation="baseline"))
        self.assertTrue(any("original guardian stop failed" in note for note in caught.exception.__notes__))
        terminal = json.loads((self.root / "result" / self.cli.TERMINAL_FILENAME).read_bytes())
        self.assertFalse(terminal["guardian_cleanup_verified"])
        self.assertNotIn("cold", self.calls)

    def test_occupied_output_rejects_before_reserve_or_source(self):
        self.arguments["output_dir"].mkdir()
        with self.assertRaisesRegex(RuntimeError, "occupied"):
            self.cli.run_component_pair_v1(**self.arguments, _dependencies=self.dependencies())
        self.assertEqual(self.calls, [])

    def test_symlink_input_rejects_before_source(self):
        original = self.input_paths["calibration_path"]
        link = self.root / "alias.json"
        link.symlink_to(original)
        self.arguments["calibration_path"] = link
        with self.assertRaises(RuntimeError):
            self.cli.run_component_pair_v1(**self.arguments, _dependencies=self.dependencies())
        self.assertNotIn("source", self.calls)

    def test_source_mutation_before_receipt_last_is_failure(self):
        dependencies = self.dependencies()
        real_cold = dependencies.cold
        def drift(**arguments):
            result = real_cold(**arguments)
            self.input_paths["calibration_path"].write_text('{"changed":true}\n')
            return result
        dependencies.cold = drift
        with self.assertRaises((RuntimeError, ValueError)):
            self.cli.run_component_pair_v1(**self.arguments, _dependencies=dependencies)
        terminal = json.loads((self.root / "result" / self.cli.TERMINAL_FILENAME).read_bytes())
        self.assertEqual(terminal["status"], "failed")

    @unittest.skipUnless(hasattr(os, "posix_fallocate"), "POSIX allocation required")
    def test_real_bounded_reserve_release_checks_original_inode(self):
        with mock.patch.object(self.cli, "RESERVE_BYTES", 4096), mock.patch.object(self.cli, "FREE_FLOOR_BYTES", 4096):
            with self.cli._scratch_reserve_v1(project_root=self.root, scratch_namespace=self.scratch / "owned",
                                              output_dir=self.root) as evidence:
                path = Path(evidence["path"])
                self.assertEqual(path.stat().st_size, 4096)
                self.assertGreaterEqual(path.stat().st_blocks * 512, 4096)
                self.assertFalse(evidence["released"])
            self.assertTrue(evidence["released"])
            self.assertFalse(path.exists())

    @unittest.skipUnless(hasattr(os, "posix_fallocate"), "POSIX allocation required")
    def test_reserve_replacement_is_preserved_and_fails(self):
        with mock.patch.object(self.cli, "RESERVE_BYTES", 4096), mock.patch.object(self.cli, "FREE_FLOOR_BYTES", 4096):
            with self.assertRaises(RuntimeError):
                with self.cli._scratch_reserve_v1(project_root=self.root, scratch_namespace=self.scratch / "owned",
                                                  output_dir=self.root) as evidence:
                    path = Path(evidence["path"])
                    path.rename(path.with_suffix(".original"))
                    path.write_bytes(b"replacement")
            self.assertEqual(path.read_bytes(), b"replacement")

    @unittest.skipUnless(hasattr(os, "pidfd_open"), "original Linux child required")
    def test_original_pre_authority_child_exit_retains_logs_and_unknown_worker_cleanup(self):
        guardian = self.cli._GuardianProcess.__new__(self.cli._GuardianProcess)
        guardian.argv = [sys.executable, "-I", "-B", "-c", "print('original child bytes',flush=True);raise SystemExit(7)"]
        guardian.authority_path = self.root / "absent-authority.json"
        guardian.lifecycle_path = self.root / "absent-lifecycle.json"
        guardian.deadline = time.monotonic() + 5
        guardian.process = None; guardian.pidfd = -1; guardian.readers = []
        guardian.authority = None; guardian.owner = None; guardian.authority_pin = None
        guardian.last_observation = {}
        with self.assertRaisesRegex(RuntimeError, "guardian exited"):
            guardian.start()
        observed = guardian.close()
        self.assertEqual(observed["returncode"], 7)
        self.assertTrue(observed["process_quiescent"])
        self.assertFalse(observed["authenticated_stop"])
        self.assertFalse(observed["container_cleanup_verified"])
        self.assertEqual(observed["stdout"], b"original child bytes\n")
        self.assertTrue(all(not reader.thread.is_alive() for reader in guardian.readers))

    def test_oversized_authority_is_rejected_before_full_read(self):
        path = self.root / "too-large.json"
        with path.open("wb") as stream:
            stream.truncate(self.cli.METADATA_BYTES + 1)
        with self.assertRaisesRegex(RuntimeError, "bounded/unique"):
            self.cli._pin_file(path, self.cli.METADATA_BYTES)

    @unittest.skipUnless(hasattr(os, "posix_fallocate"), "POSIX allocation required")
    def test_reserve_cleanup_never_overwrites_original_body_failure(self):
        with mock.patch.object(self.cli, "RESERVE_BYTES", 4096), mock.patch.object(self.cli, "FREE_FLOOR_BYTES", 4096):
            with self.assertRaisesRegex(RuntimeError, "original body") as caught:
                with self.cli._scratch_reserve_v1(project_root=self.root, scratch_namespace=self.scratch / "owned",
                                                  output_dir=self.root) as evidence:
                    path = Path(evidence["path"])
                    path.rename(path.with_suffix(".original"))
                    path.write_bytes(b"replacement")
                    raise RuntimeError("original body failed")
            self.assertTrue(any("reserve" in note for note in caught.exception.__notes__))
            self.assertEqual(path.read_bytes(), b"replacement")
            self.assertFalse(evidence["released"])

    def test_reordered_runtime_pair_rejects_before_inference(self):
        deps = self.dependencies()
        original = deps.runtime
        def reordered(**arguments):
            result = original(**arguments)
            result["receipt"]["bundles"].reverse()
            return result
        deps.runtime = reordered
        with self.assertRaisesRegex(RuntimeError, "paired execution order"):
            self.cli.run_component_pair_v1(**self.arguments, _dependencies=deps)
        self.assertTrue(self.guardian.closed)
        self.assertFalse(any(call.startswith("execute_") for call in self.calls))

    @unittest.skipUnless(hasattr(os, "pidfd_open"), "original Linux child required")
    def test_pidfd_open_failure_still_reaps_only_original_child(self):
        guardian = self.cli._GuardianProcess.__new__(self.cli._GuardianProcess)
        guardian.argv = [sys.executable, "-I", "-B", "-c", "import time;print('owned child',flush=True);time.sleep(30)"]
        guardian.authority_path = self.root / "absent-authority.json"
        guardian.lifecycle_path = self.root / "absent-lifecycle.json"
        guardian.deadline = time.monotonic() + 5
        guardian.process = None; guardian.pidfd = -1; guardian.readers = []
        guardian.authority = None; guardian.owner = None; guardian.authority_pin = None
        guardian.last_observation = {}
        try:
            with mock.patch.object(os, "pidfd_open", side_effect=OSError("original pidfd failure")):
                with self.assertRaisesRegex(OSError, "original pidfd failure"):
                    guardian.start()
            observation = guardian.close()
            self.assertIsNotNone(guardian.process.returncode)
            self.assertTrue(observation["process_quiescent"])
            self.assertFalse(observation["container_cleanup_verified"])
        finally:
            if guardian.process.poll() is None:
                guardian.process.kill()
                guardian.process.wait(timeout=2)
            for stream in (guardian.process.stdout, guardian.process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()

    def test_source_drift_during_original_terminal_commit_creates_failed_companion(self):
        original = self.cli.PhysicalRootCustodyV1.write_exclusive
        def write(custody, path, payload, **arguments):
            result = original(custody, path, payload, **arguments)
            if Path(path).name == self.cli.TERMINAL_FILENAME:
                self.input_paths["calibration_path"].write_text('{"late":true}\n')
            return result
        with mock.patch.object(self.cli.PhysicalRootCustodyV1, "write_exclusive", write):
            with self.assertRaises((RuntimeError, ValueError)):
                self.cli.run_component_pair_v1(**self.arguments, _dependencies=self.dependencies())
        companion = json.loads((self.root / "result" / "component_cli_late_failure.v1.json").read_bytes())
        self.assertEqual(companion["status"], "failed")
        self.assertFalse(companion["publication_ready"])


if __name__ == "__main__":
    unittest.main()
