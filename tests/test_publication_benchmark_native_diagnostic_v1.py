"""Adapter delegation tests; mocked stock authorities grant no acceptance."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import tempfile
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

import publication_benchmark_native_diagnostic_v1 as diagnostic
from checkpoint_publication_launcher_adapter_v3 import NativePublicationOutcomeV3
from publication_operational_request_domain_v1 import canonical_json_v1


class NativeDiagnosticDelegationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.events = []
        self.directory = self.root / "diagnostic/evidence"
        self.process_dir = self.root / "process"
        self.original = {"outputs": {"measurement_dir": str(self.directory),
            "native_domain": str(self.directory) + ".operational/native_operational_requests.v1.jsonl",
            "process_receipt": str(self.process_dir / "original_engine_process_capture.v1.json"),
            "container_receipt": str(self.process_dir / "container-custody/original_container_custody.v1.json")}}
        self.source = self.file("original.json", {"fixture_only": True})
        self.witness_descriptors = [self.source]
        self.context = self.file("context.json", {"fixture_only": True})
        self.plan = self.file("plan.json", {"fixture_only": True})
        self.cell = SimpleNamespace(run_id="run", arm_id="arm", system="gstreamer_custom",
            resource="cpu", scenario="baseline", codec="h264", policy="cpu_only", deadline_ms=100,
            topology_kind="independent_processes")
        self.request = object()
        self.kwargs = {key: self.root / (key + ".json") for key in (
            "runtime_bundle_path", "candidate_index_path", "preprocessing_contract_path", "preprocessing_receipt_path",
            "runtime_materialization_receipt_path", "guardian_authority_path", "transaction_receipt_path",
            "bootstrap_mapping_path", "bootstrap_receipt_path")}
        self.kwargs.update(project_root=self.root, capture_plan_path=Path(self.plan["path"]), operation_id="original-1")
        self.held = {"request": self.request, "cell": self.cell, "inputs": SimpleNamespace(root=self.root),
            "operational": object(), "original": self.original, "operation": {"operation_id": "original-1"},
            "original_operation_descriptor": self.source, "native_context_descriptor": self.context,
            "container_image": {"fixture_only": True}, "engine_descriptor": self.source,
            "finalizer_kwargs": {"fixture_original_kwargs": self.request},
            "execution_barrier": lambda: self.events.append("barrier")}
        self.collector = mock.Mock()
        self.collector.is_alive.return_value = False
        self.collector.start.side_effect = lambda: self.events.append("collector_start")
        self.collector.stop.side_effect = lambda: self.events.append("collector_stop")
        self.capture = SimpleNamespace(receipt_descriptor=None, container_receipt_descriptor=None)

    def file(self, path, value):
        path = self.root / path
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = canonical_json_v1(value) + b"\n"
        path.write_bytes(raw)
        return {"path": str(path), "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

    @contextmanager
    def scope(self, **kwargs):
        self.assertEqual(kwargs, self.kwargs)
        yield self.held

    @contextmanager
    def capture_scope(self, **kwargs):
        self.assertEqual(kwargs["output_dir"], self.process_dir)
        self.assertEqual(kwargs["original_operation_descriptor"], self.source)
        self.events.append("capture_enter")
        try:
            yield self.capture
        finally:
            self.capture.receipt_descriptor = self.file("process/original_engine_process_capture.v1.json", {"fixture_only": True})
            self.capture.container_receipt_descriptor = self.file("process/container-custody/original_container_custody.v1.json", {"fixture_only": True})
            self.events.append("capture_exit")

    def runtime(self, request):
        self.assertIs(request, self.request)
        self.events.append("runtime")
        for name in diagnostic.pilot.CHILD_EVIDENCE_FILES:
            self.file(self.directory / name, {"fixture_only": True})
        self.file(self.original["outputs"]["native_domain"], {"fixture_only": True})
        return NativePublicationOutcomeV3(0)

    def factory(self, path, *, run_id, interval_s):
        self.assertEqual(run_id, self.cell.run_id)
        self.assertEqual(interval_s, 1.0)
        self.file(path, {"fixture_only": True})
        return self.collector

    def custody_summary(self, **kwargs):
        self.events.append("cold_custody")
        witnesses = []
        for descriptor in self.witness_descriptors:
            info = Path(descriptor["path"]).lstat()
            witnesses.append({"descriptor": descriptor, "epoch": [info.st_dev, info.st_ino, info.st_mode,
                info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns]})
        return {"container_quiescence_verified": True, "validated_inputs": witnesses}

    def process_summary(self, **kwargs):
        return {**self.custody_summary(**kwargs), "measurement": {"launch": {"engine": self.held["engine_descriptor"]}}}

    def finalizer(self, **kwargs):
        self.assertEqual(kwargs, self.held["finalizer_kwargs"])
        self.events.append("finalizer")
        self.file(self.directory / diagnostic.pilot.ACCEPTANCE_FILENAME, {"fixture_only": True})
        return {"fixture_only": True}

    def patches(self):
        from contextlib import ExitStack
        stack = ExitStack()
        self.addCleanup(stack.close)
        for module, name, value in ((diagnostic, "held_stock_operational_request_v1", self.scope),
            (diagnostic, "capture_original_engine_processes_v1", self.capture_scope),
            (diagnostic, "run_checkpoint_gstreamer_publication_runtime_v3", self.runtime),
            (diagnostic, "HardwareResourceCollector", self.factory),
            (diagnostic, "original_process_validator_v1", self.process_summary),
            (diagnostic, "original_container_validator_v1", self.custody_summary),
            (diagnostic, "finalize_checkpoint_qualification_pilot_acceptance_v1", self.finalizer),
            (diagnostic, "validate_checkpoint_qualification_pilot_acceptance_v1", lambda **kw: {"fixture_only": True}),
            (diagnostic.pilot, "_validate_pending_candidate", lambda *a, **kw: None),
            (diagnostic.pilot, "_validate_request", lambda *a, **kw: None),
            (diagnostic.pilot, "_expected_operational_binding", lambda **kw: {}),
            (diagnostic.pilot, "_validate_final_namespace", lambda *a, **kw: None)):
            stack.enter_context(mock.patch.object(module, name, side_effect=value))
        return stack

    def test_stock_delegation_stops_collector_and_validates_original_before_finalization(self):
        self.patches()
        result = diagnostic.execute_native_diagnostic_operation_v1(**self.kwargs)
        self.assertEqual(self.events.count("runtime"), 1)
        self.assertLess(self.events.index("collector_stop"), self.events.index("finalizer"))
        self.assertLess(self.events.index("capture_exit"), self.events.index("finalizer"))
        self.assertLess(self.events.index("cold_custody"), self.events.index("finalizer"))
        self.collector.wait_until_ready.assert_called_once_with(timeout_s=60.0)
        self.collector.join.assert_called_once_with(timeout=30.0)
        self.assertFalse(result["receipt"]["accepted"])
        self.assertFalse(result["receipt"]["publication_ready"])
        self.assertFalse(result["receipt"]["authorization_eligible"])
        self.assertNotIn(Path(result["descriptor"]["path"]).parent, (self.directory, Path(str(self.directory) + ".operational")))
        self.assertNotIn(diagnostic.pilot.PRODUCTION_ACCEPTANCE_FILENAME, {p.name for p in self.directory.iterdir()})

    def test_original_failure_stops_collector_and_writes_no_completion(self):
        self.patches()
        with mock.patch.object(diagnostic, "run_checkpoint_gstreamer_publication_runtime_v3", side_effect=OSError("original fixture failure")) as runtime:
            with self.assertRaisesRegex(OSError, "original fixture failure"):
                diagnostic.execute_native_diagnostic_operation_v1(**self.kwargs)
        runtime.assert_called_once_with(self.request)
        self.collector.stop.assert_called_once()
        self.collector.join.assert_called_once_with(timeout=30.0)
        self.assertNotIn("finalizer", self.events)
        self.assertFalse((self.directory.parent / diagnostic.RECEIPT_FILENAME).exists())

    def test_ready_failure_stops_collector_before_any_original_launch(self):
        self.patches()
        self.collector.wait_until_ready.side_effect = RuntimeError("fixture readiness failed")
        with self.assertRaisesRegex(RuntimeError, "fixture readiness failed"):
            diagnostic.execute_native_diagnostic_operation_v1(**self.kwargs)
        self.collector.stop.assert_called_once()
        self.collector.join.assert_called_once_with(timeout=30.0)
        self.assertNotIn("runtime", self.events)
        self.assertNotIn("finalizer", self.events)

    def test_native_outcome_zero_cannot_replace_original_process_container_proof(self):
        self.patches()
        with mock.patch.object(diagnostic, "original_container_validator_v1", side_effect=ValueError("original process ownership missing")):
            with self.assertRaisesRegex(ValueError, "original process ownership missing"):
                diagnostic.execute_native_diagnostic_operation_v1(**self.kwargs)
        self.assertEqual(self.events.count("runtime"), 1)
        self.assertNotIn("finalizer", self.events)

    def test_occupied_operation_fails_without_new_launch(self):
        self.patches()
        self.directory.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, "occupied"):
            diagnostic.execute_native_diagnostic_operation_v1(**self.kwargs)
        self.assertNotIn("runtime", self.events)
        self.collector.start.assert_not_called()

    def test_collector_cleanup_error_keeps_original_runtime_cause(self):
        self.patches()
        self.collector.stop.side_effect = OSError("fixture collector stop failed")
        with mock.patch.object(diagnostic, "run_checkpoint_gstreamer_publication_runtime_v3", side_effect=OSError("original fixture failure")):
            with self.assertRaisesRegex(OSError, "original fixture failure") as raised:
                diagnostic.execute_native_diagnostic_operation_v1(**self.kwargs)
        self.collector.join.assert_called_once_with(timeout=30.0)
        self.assertTrue(any("collector stop failed" in note for note in raised.exception.__notes__))
        self.assertNotIn("finalizer", self.events)

    def test_cold_witness_drift_during_finalizer_blocks_complete_receipt(self):
        self.patches()
        def mutate_source(**kwargs):
            result = self.finalizer(**kwargs)
            Path(self.source["path"]).write_text("changed fixture source\n")
            return result
        with mock.patch.object(diagnostic, "finalize_checkpoint_qualification_pilot_acceptance_v1", side_effect=mutate_source):
            with self.assertRaises(ValueError):
                diagnostic.execute_native_diagnostic_operation_v1(**self.kwargs)
        self.assertFalse((self.directory.parent / diagnostic.RECEIPT_FILENAME).exists())

    def test_designated_external_engine_and_empty_capture_use_shared_held_custody(self):
        self.patches()
        path = Path(sys.executable).resolve()
        raw = path.read_bytes()
        engine = {"path": str(path), "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        self.held["engine_descriptor"] = engine
        empty = self.root / "original.stdout"
        empty.write_bytes(b"")
        self.witness_descriptors.extend([engine, {"path": str(empty), "size_bytes": 0,
            "sha256": hashlib.sha256(b"").hexdigest()}])
        result = diagnostic.execute_native_diagnostic_operation_v1(**self.kwargs)
        self.assertFalse(result["receipt"]["accepted"])


if __name__ == "__main__":
    unittest.main()
