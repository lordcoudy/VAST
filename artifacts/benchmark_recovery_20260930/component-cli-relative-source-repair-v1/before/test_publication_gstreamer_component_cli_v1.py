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
