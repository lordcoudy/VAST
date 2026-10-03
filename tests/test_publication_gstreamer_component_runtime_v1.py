"""Real selected metadata and custody fixtures; no live image/model grant."""
from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import publication_gstreamer_component_runtime_v1 as target
import publication_gstreamer_component_inputs_v1 as component
import publication_policy_qualification_runtime_inputs_v2 as stock
from publication_gstreamer_component_authority_v1 import load_component_authority_v1
from publication_guardian_component_preprocessing_contract_v1 import materialize_component_guardian_preprocessing_contract_v1
from publication_operational_request_domain_v1 import canonical_json_v1, payload_with_sha256_v1
from publication_physical_io_v1 import PhysicalRootCustodyV1
from test_publication_gstreamer_component_inputs_v1 import ComponentAuthorityFixture


def descriptor(root, path):
    raw = path.read_bytes()
    return {"path": str(path.relative_to(root)), "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


class ComponentRuntimeFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vcr-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.fixture = ComponentAuthorityFixture(self.root)
        self.authority = self.root / self.fixture.authority["path"]
        self.selected = load_component_authority_v1(project_root=self.root, component_authority_path=self.authority)
        self.selected["environment"]["nvidia"] = {
            "uuid": "GPU-00000000-0000-0000-0000-000000000001", "name": "fixture", "driver_version": "1.0"}
        inventory = component._inventory(self.root, self.selected)
        fixed = {}
        for role in ("experiments_config", "device_probe", "analytics_model_manifest"):
            relative = "configs/experiments.yaml" if role == "experiments_config" else "inputs/" + role
            if not (self.root / relative).exists():
                self.fixture.binary(relative, b"fixture runtime role\n")
            fixed[role] = stock._project_pin(self.root, relative, label="explicit fixture role")
        engine_path = self.root / "inputs/original-engine"
        self.fixture.binary("inputs/original-engine", b"#!/bin/sh\nexit 0\n")
        engine_path.chmod(0o555)
        engine_pin = stock._project_pin(self.root, "inputs/original-engine", label="fixture engine only")
        self.front = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self.engine_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(self.front.close)
        self.addCleanup(self.engine_socket.close)
        self.front_path, self.engine_path = self.root / "front.sock", self.root / "engine.sock"
        self.front.bind(str(self.front_path))
        self.front.listen()
        self.engine_socket.bind(str(self.engine_path))
        self.engine_socket.listen()
        self.selected.update(inventory=inventory, fixed=fixed,
            candidate_pin=component._file(self.root, self.selected["capability_manifest_descriptor"]),
            calib_pin=component._file(self.root, self.selected["calibration_descriptor"]),
            engine_pin=engine_pin, engine_socket=stock._socket_record(self.engine_path, label="fixture engine socket"),
            support_descriptors=stock._support_descriptors(inventory, system="gstreamer_custom"),
            dataset=stock._dataset_material(inventory, "h264")[0],
            probe={"value": {"fixture": True}}, capability_hashes={"cpu": "a" * 64, "gpu": "b" * 64},
            verify_barrier=lambda: None)
        self.fixture.binary("scripts/checkpoint_deepstream_protocol_bridge.py", b"# physical proxy fixture\n")
        self.closure = self.root / self.fixture.value["execution_code_closure"]["path"]
        with patch.object(target, "load_execution_code_closure_v1", return_value={
                "fixture_only": True, "receipt_descriptor": self.fixture.value["execution_code_closure"]}):
            planned = target.prepare_component_capture_plan_v1(project_root=self.root,
                component_authority_path=self.authority, execution_code_closure_path=self.closure,
                output_dir=self.root / "operations", guardian_output_dir=self.root / "operations/guardian-capture")
        self.capture = Path(planned["descriptor"]["path"])
        self.assertTrue(self.capture.is_file(), planned)
        material = materialize_component_guardian_preprocessing_contract_v1(project_root=self.root,
            component_authority_path=self.authority,
            operational_context_path=planned["value"]["guardian_context"]["path"],
            output_dir=self.root / "preprocessing")
        self.preprocessing_contract = self.root / "preprocessing/guardian-preprocessing-contract.v1.json"
        self.preprocessing_receipt = self.root / "preprocessing/guardian-component-preprocessing-receipt.v1.json"
        self.assertTrue(self.preprocessing_contract.is_file(), material)
        self.guardian_path = self.root / "guardian-authority.json"
        self.fixture.write("guardian-authority.json", {"fixture_guardian_only": True})
        self.guardian = {"front_socket": stock._socket_record(self.front_path, label="fixture front socket")}
        self.guardian_ref = {**descriptor(self.root, self.guardian_path), "path": str(self.guardian_path)}
        self.scratch = self.root / "scratch"
        self.scratch.mkdir()
        with self.host_fixture():
            runtime = target.materialize_component_runtime_v1(project_root=self.root,
                component_authority_path=self.authority, capture_plan_path=self.capture,
                preprocessing_contract_path=self.preprocessing_contract,
                preprocessing_receipt_path=self.preprocessing_receipt, guardian_authority_path=self.guardian_path,
                analytics_socket_path=self.front_path, scratch_root=self.scratch, output_dir=self.root / "runtime")
        self.rows = runtime["receipt"]["bundles"]
        self.arguments = dict(project_root=self.root, component_authority_path=self.authority,
            capture_plan_path=self.capture, runtime_bundle_path=self.rows[0]["descriptor"]["path"],
            operation_id=self.rows[0]["operation_id"], preprocessing_contract_path=self.preprocessing_contract,
            preprocessing_receipt_path=self.preprocessing_receipt, guardian_authority_path=self.guardian_path,
            analytics_socket_path=self.front_path, scratch_root=self.scratch)

    @contextmanager
    def host_fixture(self):
        # Only unavailable live host/image/guardian observations are injected.
        # All selected metadata, capture rows, preprocessor and factory joins are real.
        @contextmanager
        def selected_fixture(**_arguments):
            yield self.selected
        with patch.object(component, "held_selected_component_inputs_v1", selected_fixture), \
             patch.object(target, "_selected_guardian_v1", return_value=(self.guardian, self.guardian_ref)):
            yield

    def test_original_pair_is_physically_planned_and_factory_reconstructed(self):
        self.assertEqual(len(self.rows), 2)
        self.assertEqual({row["operation_id"] for row in self.rows},
                         {"component-" + cell.arm_id.removeprefix("qualification-arm-v2-")
                          for cell in target.selected_cells_v1("cpu")})
        with self.host_fixture(), target.held_component_runtime_v1(**self.arguments) as held:
            self.assertEqual(held["request"].runtime_inputs["streams"], 6)
            self.assertEqual(held["request"].runtime_inputs["duration_s"], 180)
            self.assertEqual(held["engine_descriptor"]["sha256"], self.selected["engine_pin"].sha256)
        self.assertFalse(any((self.root / "operations/arms").glob("*/evidence")))

    def test_resealed_foreign_factory_fields_fail_before_native_execution(self):
        path = Path(self.arguments["runtime_bundle_path"])
        original = path.read_bytes()
        for field in ("detect_bin", "source_files", "model_files", "support_files", "ready_timeout_s", "device_binding"):
            with self.subTest(field=field):
                value = __import__("json").loads(original)
                contract = value["runtime_inputs"]["dataset"]["gstreamer_custom_publication_runtime_v3"]
                if field.endswith("_files"):
                    contract[field][0]["sha256"] = "e" * 64
                elif field == "device_binding":
                    contract[field]["fixture_foreign"] = True
                else:
                    contract[field] = "identity" if field == "detect_bin" else 301.0
                path.chmod(0o644)
                path.write_bytes(canonical_json_v1(payload_with_sha256_v1(value)) + b"\n")
                with self.host_fixture(), patch.object(target, "run_checkpoint_gstreamer_publication_runtime_v3") as native:
                    with self.assertRaisesRegex(ValueError, "exact selected original factory"):
                        target.execute_component_operation_v1(**self.arguments)
                    native.assert_not_called()
        path.write_bytes(original)

    def test_same_shaped_foreign_copied_engine_fails_before_executor(self):
        path = self.root / "runtime/container-engine/docker"
        path.chmod(0o755)
        path.write_bytes(b"#!/bin/sh\nexit 1\n")
        bundle = Path(self.arguments["runtime_bundle_path"])
        value = __import__("json").loads(bundle.read_bytes())
        ref = descriptor(self.root, path)
        value["runtime_inputs"]["dataset"]["gstreamer_custom_publication_runtime_v3"]["files"]["container_engine"].update(ref)
        bundle.chmod(0o644)
        bundle.write_bytes(canonical_json_v1(payload_with_sha256_v1(value)) + b"\n")
        with self.host_fixture(), patch.object(target, "run_checkpoint_gstreamer_publication_runtime_v3") as native:
            with self.assertRaisesRegex(ValueError, "copied engine differs"):
                target.execute_component_operation_v1(**self.arguments)
            native.assert_not_called()

    def test_execution_cannot_opt_out_of_live_guardian(self):
        with self.assertRaisesRegex(ValueError, "cannot disable"):
            target.execute_component_operation_v1(**self.arguments, live_guardian=False)

    def test_private_session_keeps_real_factory_and_custody_at_all_five_boundaries(self):
        from publication_gstreamer_component_authority_v1 import held_component_authority_v1
        import checkpoint_model_parity as parity
        images = ["sha256:" + value * 64 for value in "abcd"]
        raw = {image: {"Id": image, "RepoDigests": [], "Architecture": "amd64", "Os": "linux"}
               for image in images}
        projections = [(tuple(parity.build_image_inspect_command(image)),
            parity._inspect_image(image, lambda _argv, image=image: __import__("json").dumps(raw[image])))
            for image in images]
        entries = []
        @contextmanager
        def expensive_host_fixture(**arguments):
            entries.append(arguments)
            with held_component_authority_v1(project_root=self.root, component_authority_path=self.authority) as held:
                original = held["verify_barrier"]
                for name in ("inventory", "fixed", "candidate_pin", "calib_pin", "engine_pin", "engine_socket",
                             "support_descriptors", "dataset", "probe", "capability_hashes"):
                    held[name] = self.selected[name]
                def verify():
                    original()
                    stock._require_file_pin_unchanged(held["engine_pin"], label="original unit fixture engine")
                    self.assertEqual(stock._socket_record(self.engine_path, label="original unit fixture socket"),
                                     held["engine_socket"])
                held["verify_barrier"] = verify
                arguments["_image_observations"][:] = copy.deepcopy(projections)
                yield held
        with patch.object(component, "_held_selected_component_inputs_v1", expensive_host_fixture), \
             patch.object(component, "held_selected_component_inputs_v1") as independent, \
             patch.object(stock, "_run_json", side_effect=lambda argv, **kw: raw[argv[-1]]) as observer, \
             patch.object(target, "_selected_guardian_v1", return_value=(self.guardian, self.guardian_ref)), \
             patch.object(target, "run_checkpoint_gstreamer_publication_runtime_v3") as native:
            with component._held_selected_component_session_v1(project_root=self.root,
                    component_authority_path=self.authority) as session:
                common = {key: value for key, value in self.arguments.items()
                          if key not in {"operation_id", "runtime_bundle_path"}}
                material = target._materialize_component_runtime_from_session_v1(session,
                    **common, output_dir=self.root / "session-runtime")
                rows = material["receipt"]["bundles"]
                for boundary in ("execute", "cold"):
                    for row in rows:
                        with target._held_component_runtime_from_session_v1(session, boundary=boundary,
                                **common, operation_id=row["operation_id"],
                                runtime_bundle_path=row["descriptor"]["path"], live_guardian=boundary == "execute") as held:
                            self.assertEqual(held["request"].runtime_inputs["streams"], 6)
                            self.assertEqual(held["request"].runtime_inputs["duration_s"], 180)
                            held["execution_barrier"]()
                self.assertEqual(len(entries), 1)
                self.assertEqual(observer.call_count, 20)
                self.assertEqual([call.args[0][-1] for call in observer.call_args_list], images * 5)
                independent.assert_not_called()
                native.assert_not_called()
            with self.assertRaises(ValueError):
                target._materialize_component_runtime_from_session_v1(session,
                    **common, output_dir=self.root / "after-close")


@unittest.skipUnless(os.name == "posix", "original component custody is POSIX")
class ComponentCustodyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vcc-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_original_arm_local_cohort_ids_do_not_break_stock_schedule_pair_gate(self):
        from checkpoint_admission import schedule_fingerprint_for_records
        row = dict(stream_id=0, sequence=1, source_sha256="a" * 64, source_cycle=0,
                   access_unit_pts_ns=0, payload_sha256="b" * 64, payload_size_bytes=1, schedule_offset_ns=0)
        left = schedule_fingerprint_for_records([{**row, "run_id": "baseline", "timestamp": 10}])
        right = schedule_fingerprint_for_records([{**row, "run_id": "shared", "timestamp": 100}])
        arms = [{"cohort_id": "baseline:measurement:10:20", "schedule_sha256": left},
                {"cohort_id": "shared:measurement:100:110", "schedule_sha256": right}]
        self.assertEqual(target._pair_schedule_v1(arms), left)
        arms[1]["schedule_sha256"] = schedule_fingerprint_for_records([{**row, "source_cycle": 1}])
        with self.assertRaisesRegex(ValueError, "measurement schedules differ"):
            target._pair_schedule_v1(arms)

    def test_original_hardware_transfer_is_exact_exclusive_and_owned(self):
        source = self.root / "original.csv"
        source.write_bytes(b"time,value\n1,2\n")
        destination = self.root / "committed.csv"
        with PhysicalRootCustodyV1.open(self.root, label="real hardware transfer fixture") as custody:
            ref = target._commit_hardware_v1(custody, self.root, source, destination)
        self.assertFalse(source.exists())
        self.assertEqual(destination.read_bytes(), b"time,value\n1,2\n")
        self.assertEqual(ref["sha256"], hashlib.sha256(destination.read_bytes()).hexdigest())

    def test_same_byte_source_substitution_refuses_transfer_and_retains_both_originals(self):
        source, saved, destination = self.root / "original.csv", self.root / "retained.csv", self.root / "committed.csv"
        source.write_bytes(b"time,value\n1,2\n")
        with PhysicalRootCustodyV1.open(self.root, label="hardware substitution fixture") as custody:
            original_read = custody.read_descriptor
            def replace_before_read(path, **arguments):
                source.rename(saved)
                source.write_bytes(saved.read_bytes())
                return original_read(path, **arguments)
            with patch.object(custody, "read_descriptor", side_effect=replace_before_read):
                with self.assertRaisesRegex(ValueError, "rebound during transfer"):
                    target._commit_hardware_v1(custody, self.root, source, destination)
        self.assertTrue(source.exists() and saved.exists())
        self.assertFalse(destination.exists())

    def test_oversized_sparse_hardware_is_refused_without_publication(self):
        source = self.root / "oversized.csv"
        with source.open("wb") as output:
            output.truncate(64 * 1024 * 1024 + 1)
        with PhysicalRootCustodyV1.open(self.root, label="bounded hardware fixture") as custody:
            with self.assertRaisesRegex((ValueError, RuntimeError), "explicit byte bound"):
                target._commit_hardware_v1(custody, self.root, source, self.root / "committed.csv")
        self.assertTrue(source.exists())
        self.assertFalse((self.root / "committed.csv").exists())

    def test_all_acceptance_leaves_remain_held_after_validator_returns(self):
        from publication_policy_qualification_execution_closure_v1 import _held_operational_cold_custody_v1
        for name in (*target.CHILD_EVIDENCE_FILES, "hardware_resource_samples.csv"):
            (self.root / name).write_bytes(b"physical fixture bytes\n")
        with self.assertRaises(ValueError):
            with _held_operational_cold_custody_v1(self.root) as custody:
                target._hold_acceptance_inputs_v1(custody, self.root)
                candidate = self.root / "checkpoint_publication_candidate.json"
                replacement = self.root / "replacement.json"
                replacement.write_bytes(candidate.read_bytes())
                replacement.replace(candidate)
                custody.verify()

    def test_guardian_journals_stay_held_after_the_surrounding_join_returns(self):
        from publication_policy_qualification_execution_closure_v1 import _held_operational_cold_custody_v1
        paths = []
        for index in range(8):
            path = self.root / ("journal-" + str(index) + ".jsonl")
            path.write_bytes(b'{"original_fixture_header":true}\n')
            paths.append(path)
        with self.assertRaises(ValueError):
            with _held_operational_cold_custody_v1(self.root) as custody:
                for path in paths:
                    target._hold_guardian_journal_v1(custody, self.root,
                        {**descriptor(self.root, path), "path": str(path)})
                replacement = self.root / "replacement.jsonl"
                replacement.write_bytes(paths[-1].read_bytes())
                replacement.replace(paths[-1])
                custody.verify()

    def test_generated_preprocessing_leaves_reject_late_same_byte_replacement(self):
        from publication_policy_qualification_execution_closure_v1 import _held_operational_cold_custody_v1
        for name in ("generated-contract.json", "generated-receipt.json"):
            path = self.root / name
            path.write_bytes(b'{"nonpromoting_fixture":true}\n')
        with self.assertRaises(ValueError):
            with _held_operational_cold_custody_v1(self.root) as custody:
                for name in ("generated-contract.json", "generated-receipt.json"):
                    custody.read_descriptor(self.root / name, label="whole-pair preprocessing fixture", maximum=1024)
                path = self.root / "generated-receipt.json"
                replacement = self.root / "replacement.json"
                replacement.write_bytes(path.read_bytes())
                replacement.replace(path)
                custody.verify()

    def test_descriptive_metrics_keep_absolute_misses_drops_and_zero_denominator_reason(self):
        operation = {"deadline_ms": 100.0, "measurement_s": 180.0}
        directories, arms = [], []
        for index, values in enumerate(((10, 50, 100, 110), (5, 25, 50, 55))):
            directory = self.root / str(index)
            directory.mkdir()
            (directory / "frames.csv").write_text("e2e_latency_ms,telemetry_source\n" +
                "".join(str(value) + ",native\n" for value in values))
            metrics = target._descriptive_arm_metrics_v1(directory, operation=operation, admitted=6)
            arms.append({"operation_id": str(index), "scenario": "fixture-" + str(index), "descriptive_metrics": metrics})
            directories.append(directory)
        baseline = arms[0]["descriptive_metrics"]
        self.assertEqual(baseline["completed_deadline_misses"], 1)
        self.assertEqual(baseline["measurement_dropped"], 2)
        self.assertEqual(baseline["latency_p95_ms"], 108.5)
        self.assertEqual(baseline["completion_coverage"], 4 / 6)
        comparison = target._descriptive_comparison_v1(arms)
        self.assertEqual(comparison["latency_p95_ms"]["shared_over_baseline"], 0.5)
        self.assertEqual(comparison["completed_deadline_misses"]["shared_over_baseline"], 0)
        baseline["completed_deadline_misses"] = 0
        comparison = target._descriptive_comparison_v1(arms)
        self.assertIsNone(comparison["completed_deadline_misses"]["shared_over_baseline"])
        self.assertEqual(comparison["completed_deadline_misses"]["ratio_reason"], "baseline_is_not_positive")
        with PhysicalRootCustodyV1.open(self.root, label="descriptive export fixture") as output:
            destination = self.root / "report"
            output.ensure_directory_owned(destination, label="fresh report fixture")
            exported = target._write_descriptive_artifacts_v1(output, destination, arms, directories,
                resource="cpu", deadline_ms=100.0)
        self.assertEqual(set(exported), {"descriptive_csv", "latency_ecdf_svg"})
        import xml.etree.ElementTree as ET
        self.assertEqual(ET.parse(destination / "component_pair_latency_ecdf.svg").getroot().tag,
                         "{http://www.w3.org/2000/svg}svg")
        self.assertIn("completed_measurement_frames", (destination / "component_pair_metrics.csv").read_text())


class ColdProviderBoundaryTests(unittest.TestCase):
    def test_real_cold_provider_resolves_before_two_arm_cardinality_guard(self):
        with tempfile.TemporaryDirectory(prefix="cold-provider-") as temporary:
            root = Path(temporary).resolve()
            with self.assertRaisesRegex(ValueError, "exactly its two original arms"):
                target._cold_component_pair_from_held_v1(selected={}, project_root=root,
                    component_authority_path=root / "authority.json", capture_plan_path=root / "plan.json",
                    runtime_bundle_paths=[], arm_result_paths=[], guardian_authority_path=root / "guardian.json",
                    guardian_lifecycle_path=root / "lifecycle.json", preprocessing_contract_path=root / "contract.json",
                    preprocessing_receipt_path=root / "receipt.json", analytics_socket_path=root / "front.sock",
                    scratch_root=root / "scratch", output_dir=root / "output")

    def test_actual_operational_header_reader_binds_physical_bytes(self):
        from publication_operational_request_reconciliation_v1 import load_operational_jsonl_header_v1
        with tempfile.TemporaryDirectory(prefix="cold-header-") as temporary:
            path = Path(temporary).resolve() / "header.jsonl"
            header = payload_with_sha256_v1({"fixture_header_only": True, "schema_version": 1})
            raw = canonical_json_v1(header) + b"\n"
            with path.open("xb") as stream:
                stream.write(raw)
            entry = {"path": path, "descriptor": {"path": str(path), "size_bytes": len(raw),
                     "sha256": hashlib.sha256(raw).hexdigest()}}
            self.assertEqual(load_operational_jsonl_header_v1(entry), header)
            changed = bytearray(raw)
            changed[1] = ord("x")
            path.write_bytes(changed)
            with self.assertRaisesRegex(ValueError, "physical hash drift"):
                load_operational_jsonl_header_v1(entry)


if __name__ == "__main__":
    unittest.main()
