"""Context pinning and separate output custody; no physical workload authority."""
from __future__ import annotations
import copy
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from publication_operational_request_domain_v1 import (
    canonical_json_v1, payload_with_sha256_v1, write_native_domain_v1,
)
from publication_operational_runtime_context_v1 import (
    CAPTURE_ROLE, copy_operational_child_v1, load_native_operational_context_v1,
    operational_runtime_scratch_v1, prepare_operational_child_dir_v1,
    require_operational_execution_window_v1, runtime_file_roles_v1,
)
from tests.test_publication_operational_request_domain_v1 import authority, native_fixture, native_header


class OperationalRuntimeContextTests(unittest.TestCase):
    def context(self, root, **changes):
        runtime, records = native_fixture()
        header = native_header(runtime, records)
        header["counts"] = {key: 0 for key in header["counts"]}
        header = payload_with_sha256_v1(header)
        value = {"schema_version": 1, "artifact_kind": "vast_native_operational_capture_context_v1",
                 "mode": "bounded_native_diagnostic_operational_v1", "native_header": header,
                 "admission_limits": {"max_admissions_per_stream": 241,
                                      "min_schedule_step_ns": 999_999_600}}
        value.update(changes)
        path = root / "context.json"
        path.write_bytes(canonical_json_v1(payload_with_sha256_v1(value)) + b"\n")
        output = root / "capture"
        output.mkdir()
        identity = {"run_id": runtime.run_id, "system": runtime.system,
                    "scenario": runtime.scenario, "codec": runtime.codec,
                    "policy": runtime.policy, "deadline_ms": runtime.deadline_ms}
        return path, output, identity

    def test_context_preserves_original_header_and_checks_frozen_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, output, identity = self.context(Path(tmp))
            context, limits = load_native_operational_context_v1(path, output, **identity)
            self.assertEqual(context["output_dir"], output)
            self.assertEqual(limits["max_admissions_per_stream"], 241)
            require_operational_execution_window_v1(context, warmup_s=30.0, measurement_s=180.0,
                drain_timeout_s=10.0, streams=6, branches=4)
            with self.assertRaises(ValueError):
                require_operational_execution_window_v1(context, warmup_s=0, measurement_s=180.0,
                    drain_timeout_s=10.0, streams=6, branches=4)

    def test_context_drift_or_longer_deadline_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, output, identity = self.context(Path(tmp))
            identity["run_id"] = "foreign-original-run"
            with self.assertRaises(ValueError):
                load_native_operational_context_v1(path, output, **identity)
            value = path.read_bytes()
            path.write_bytes(value[:-1])
            identity["run_id"] = "foreign-original-run"
            with self.assertRaises(ValueError):
                load_native_operational_context_v1(path, output, **identity)

    def test_relaxed_admission_limits_and_implicit_activation_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, output, identity = self.context(Path(tmp), admission_limits={
                "max_admissions_per_stream": 281, "min_schedule_step_ns": 999_999_600})
            with self.assertRaises(ValueError):
                load_native_operational_context_v1(path, output, **identity)
            with self.assertRaises(ValueError):
                load_native_operational_context_v1(path, None, **identity)
            self.assertEqual(load_native_operational_context_v1(None, None, **identity), (None, None))

    def test_runtime_reserves_exact_separate_output_and_explicit_file_role(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = SimpleNamespace(output_dir=root / "legacy")
            raw = {"operational_capture": {"mode": "bounded_native_diagnostic_operational_v1",
                                           "output_dir": str(root / "legacy.operational")}}
            self.assertEqual(runtime_file_roles_v1(request, raw, {"model"}), {"model", CAPTURE_ROLE})
            foreign = copy.deepcopy(raw)
            foreign["operational_capture"]["output_dir"] = str(root / "legacy")
            with self.assertRaises(ValueError):
                runtime_file_roles_v1(request, foreign, {"model"})
            (root / "legacy.operational").mkdir()
            with self.assertRaises(ValueError):
                runtime_file_roles_v1(request, raw, {"model"})

    def test_frozen_output_rule_is_resolved_from_original_request_without_mutating_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = SimpleNamespace(output_dir=root / "original-pilot")
            raw = {"operational_capture": {"mode": "bounded_native_diagnostic_operational_v1",
                                           "output_dir": "request_output_dir_sibling_v1"}}
            original = canonical_json_v1(raw)
            self.assertEqual(runtime_file_roles_v1(request, raw, {"model"}), {"model", CAPTURE_ROLE})
            self.assertEqual(canonical_json_v1(raw), original)
            self.assertEqual(request.output_dir, root / "original-pilot")
            raw["operational_capture"]["output_dir"] = "request_output_dir_sibling_v2"
            with self.assertRaises(ValueError):
                runtime_file_roles_v1(request, raw, {"model"})

    def test_operational_copy_preserves_bytes_outside_legacy_exact_namespace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = SimpleNamespace(project_root=root, output_dir=root / "legacy")
            request.output_dir.mkdir()
            (request.output_dir / "unchanged.txt").write_text("original", encoding="ascii")
            raw = {"operational_capture": {"mode": "bounded_native_diagnostic_operational_v1",
                                           "output_dir": str(root / "legacy.operational")}}
            stage = root / "scratch"
            stage.mkdir()
            runtime_output = stage / "run"
            runtime_output.mkdir()
            operational = prepare_operational_child_dir_v1(raw, runtime_output)
            runtime, records = native_fixture()
            source = operational / "native_operational_requests.v1.jsonl"
            descriptor = write_native_domain_v1(source, native_header(runtime, records), records,
                                               original_authority_validator=authority)
            copy_operational_child_v1(raw, runtime_output, request)
            target = root / "legacy.operational/native_operational_requests.v1.jsonl"
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), descriptor["sha256"])
            self.assertEqual({p.name for p in request.output_dir.iterdir()}, {"unchanged.txt"})

    def test_failed_partial_capture_is_preserved_and_original_failure_is_propagated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = {"operational_capture": {"mode": "bounded_native_diagnostic_operational_v1",
                                           "output_dir": str(root / "legacy.operational")}}
            with self.assertRaisesRegex(RuntimeError, "original child exit"):
                with operational_runtime_scratch_v1(raw, prefix="capture-", dir=root) as name:
                    capture = Path(name) / "operational"
                    capture.mkdir()
                    (capture / "native_operational_requests.v1.jsonl").write_bytes(b'{"partial":')
                    raise RuntimeError("original child exit")
            target = root / "legacy.operational.failed/native_operational_requests.v1.jsonl"
            self.assertEqual(target.read_bytes(), b'{"partial":')
            self.assertEqual(list(root.glob("capture-*")), [])


if __name__ == "__main__":
    unittest.main()
