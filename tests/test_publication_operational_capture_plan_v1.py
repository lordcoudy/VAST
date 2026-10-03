"""Prelaunch capture planning over physically pinned stock source plans."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import tracemalloc
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from checkpoint_runtime_plan import build_primary_pair_plans, validate_checkpoint_runtime_plan
from publication_operational_request_domain_v1 import canonical_json_v1, payload_with_sha256_v1
from publication_operational_capture_plan_v1 import (
    build_operational_capture_plan_v1, held_operational_capture_plan_v1,
)

MODE = "bounded_native_diagnostic_operational_v1"
BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
ROUTES = tuple(f"{branch}:{resource}" for branch in BRANCHES for resource in ("cpu", "gpu"))
GUARDIAN_ROLES = ("capability_manifest", "execution_config", "execution_code_closure",
                  "model_authority", "native_protocol_source", "proxy_protocol_source")
NATIVE_ROLES = ("capability_manifest", "source_plan", "model_authority", "calibration",
                "policy_request_source", "policy_coordinator_source", "execution_code_closure")


class CapturePlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = yaml.safe_load((ROOT / "configs/experiments.yaml").read_bytes())
        datasets = yaml.safe_load((ROOT / "configs/datasets.yaml").read_bytes())["datasets"]
        cls.plans = {system: build_primary_pair_plans(config=config, datasets=datasets, system=system)
                     for system in ("gstreamer_custom", "openvino_gva", "deepstream", "savant")}

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "inputs").mkdir()
        (self.root / "outputs").mkdir()
        self.guardian = {role: self.write("inputs/" + role + ".json", {"fixture_only": True, "role": role})
                         for role in GUARDIAN_ROLES}
        self.calls = []
        self.operations = [self.operation("diagnostic-baseline", "diagnostic", "gstreamer_custom", "cpu", "h264", False),
                           self.operation("diagnostic-shared", "diagnostic", "gstreamer_custom", "cpu", "h264", True)]

    def write(self, name, value):
        path = self.root / name
        raw = canonical_json_v1(value) + b"\n"
        path.write_bytes(raw)
        return {"path": str(path), "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

    def operation(self, identity, phase, system, resource, codec, shared):
        topology = "shared_video_dag" if shared else "independent_processes"
        plan = copy.deepcopy(self.plans[system]["shared" if shared else "baseline"])
        workers = {}
        for route in ROUTES:
            branch = route.split(":")[0]
            rows = []
            for stream in plan["streams"]:
                if system in {"deepstream", "savant"}:
                    worker = "fixture-route-" + route.replace(":", "-")
                elif shared:
                    worker = stream["graph_process"]["process_id"]
                else:
                    worker = next(row["process_id"] for row in stream["workers"] if row["branch_id"] == branch)
                rows.append({"worker_id": worker, "stream_id": stream["stream_id"]})
            workers[route] = rows
        slug = f"{system}-{resource}-{codec}-{topology.replace('_', '-')}"
        desc = {role: self.guardian.get(role) or self.write(f"inputs/{identity}-{role}.json", {"fixture_only": True, "role": role})
                for role in NATIVE_ROLES}
        desc["source_plan"] = self.write(f"inputs/{identity}-source-plan.json", plan)
        row = {"operation_id": identity, "phase": phase, "arm_id": f"qualification-arm-v2-{slug}",
               "run_id": f"qualification-v2-{slug}", "system": system, "scenario": plan["scenario"],
               "codec": codec, "policy": resource + "_only", "deadline_ms": 100.0,
               "warmup_s": 30.0, "measurement_s": 180.0, "drain_timeout_s": 10.0,
               "streams": 6, "branches": 4, "descriptors": desc, "front_workers_by_route": workers}
        row["original_operation"] = self.write(f"inputs/{identity}-original.json", row)
        return row

    def validator(self, row, assets):
        original = json.loads(assets[row["original_operation"]["path"]])
        self.assertEqual(original, {key: value for key, value in row.items() if key != "original_operation"})
        source = json.loads(assets[row["descriptors"]["source_plan"]["path"]])
        validate_checkpoint_runtime_plan(source)
        self.assertEqual(source["scenario"], row["scenario"])
        self.calls.append(row["operation_id"])

    def build(self, **changes):
        args = dict(project_root=self.root, output_dir=self.root / "outputs/plan", mode=MODE,
                    operations=self.operations, guardian_descriptors=self.guardian,
                    guardian_output_dir=self.root / "outputs/guardian", original_operation_validator=self.validator)
        args.update(changes)
        return build_operational_capture_plan_v1(**args)

    def load(self, built):
        return held_operational_capture_plan_v1(project_root=self.root, index_path=Path(built["descriptor"]["path"]),
                                                 expected_descriptor=built["descriptor"])

    def test_real_source_pair_builds_separately_pinned_contexts_without_cycle(self):
        built = self.build()
        self.assertEqual(self.calls, [row["operation_id"] for row in self.operations])
        self.assertFalse(built["value"]["accepted"])
        with self.load(built) as loaded:
            self.assertEqual(set(loaded["operations_by_id"]), {row["operation_id"] for row in self.operations})
            self.assertEqual(loaded["qualification_contexts_by_arm"], {})
            manifest = loaded["operation_manifest"]
            self.assertNotIn("native_contexts", manifest)
            context = loaded["native_contexts_by_id"]["diagnostic-baseline"]
            self.assertEqual(context["native_header"]["operation_input"], self.operations[0]["original_operation"])
            self.assertEqual(context["admission_limits"]["max_admissions_per_stream"], 241)
            guardian = loaded["guardian_context"]
            self.assertEqual(set(guardian["headers_by_route"]), set(ROUTES))
            for header in guardian["headers_by_route"].values():
                self.assertIsNone(header["lifecycle_id"])
                self.assertIsNone(header["owner"])
                self.assertIsNone(header["worker_capability"])
                self.assertIsNone(header["descriptors"]["service_authority"])
                self.assertEqual(len(header["bindings"]), 12)
                self.assertLessEqual(len(canonical_json_v1(header)) + 1, 65536)

    def test_modes_cardinality_and_window_are_explicit(self):
        for changes in ({"mode": "full_run"}, {"operations": self.operations[:1]},
                        {"operations": self.operations * 2}, {"original_operation_validator": None}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.build(**changes)
        for field, value in (("measurement_s", 1.0), ("streams", 5), ("deadline_ms", True)):
            rows = copy.deepcopy(self.operations)
            rows[0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.build(operations=rows)

    def test_original_validator_refusal_never_writes_authority(self):
        def refuse(row, assets):
            raise ValueError("original stock source refused")
        with self.assertRaisesRegex(ValueError, "original stock source refused"):
            self.build(original_operation_validator=refuse)
        self.assertFalse((self.root / "outputs/plan").exists())

    def test_changed_source_and_alias_are_rejected_before_build(self):
        path = Path(self.operations[0]["descriptors"]["source_plan"]["path"])
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaises(ValueError):
            self.build()
        self.assertFalse((self.root / "outputs/plan").exists())

    def test_repeated_build_cannot_overwrite_immutable_plan(self):
        self.build()
        with self.assertRaises(ValueError):
            self.build()

    def test_unknown_dynamic_wire_fields_and_worker_reference_are_rejected(self):
        for field in ("request_id", "input_frame_key", "decision_id", "trace_id"):
            rows = copy.deepcopy(self.operations)
            rows[0][field] = "invented"
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.build(operations=rows)
        rows = copy.deepcopy(self.operations)
        rows[0]["front_workers_by_route"][ROUTES[0]][0]["stream_id"] = 6
        with self.assertRaises(ValueError):
            self.build(operations=rows)

    def test_loader_rejects_semantic_reseal_with_foreign_native_context(self):
        built = self.build()
        path = Path(built["value"]["native_contexts"][0]["descriptor"]["path"])
        value = json.loads(path.read_bytes())
        value["native_header"]["run_id"] = "foreign-run"
        value["native_header"] = payload_with_sha256_v1(value["native_header"])
        value = payload_with_sha256_v1(value)
        os.chmod(path, 0o600)
        path.write_bytes(canonical_json_v1(value) + b"\n")
        # Rebind the physical index as well: rejection must come from original
        # context equality, not merely its now-stale outer file hash.
        self.reseal_index(built, path)
        with self.assertRaisesRegex(ValueError, "native context differs"):
            with self.load(built):
                pass

    def reseal_index(self, built, changed):
        raw = changed.read_bytes()
        for ref in built["value"]["native_contexts"]:
            if ref["descriptor"]["path"] == str(changed):
                ref["descriptor"] = {"path": str(changed), "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        built["value"] = payload_with_sha256_v1(built["value"])
        index = Path(built["descriptor"]["path"])
        os.chmod(index, 0o600)
        raw = canonical_json_v1(built["value"]) + b"\n"
        index.write_bytes(raw)
        built["descriptor"] = {"path": str(index), "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

    def test_loader_rechecks_original_asset_mutation_during_hold(self):
        built = self.build()
        with self.assertRaises(ValueError):
            with self.load(built):
                path = Path(self.operations[0]["descriptors"]["calibration"]["path"])
                path.write_bytes(path.read_bytes() + b" ")

    def test_declared_inputs_remain_held_while_unrelated_output_siblings_are_created(self):
        built = self.build()
        with self.load(built) as loaded:
            (self.root / "inputs/qualification-runtime-inputs").mkdir()
            (self.root / "inputs/qualification-runtime-inputs/new-output.json").write_bytes(b"{}\n")
            (self.root / "outputs/another-pilot").mkdir()
            self.assertEqual(len(loaded["runtime_contexts_by_arm"]), 2)

    def test_source_same_bytes_replacement_and_source_leaf_ABA_are_detected(self):
        built = self.build()
        path = Path(self.operations[0]["descriptors"]["source_plan"]["path"])
        original = path.read_bytes()
        with self.assertRaises(ValueError):
            with self.load(built):
                staged = path.with_name("original-temporary.json")
                path.rename(staged)
                path.write_bytes(original)
                path.unlink()
                staged.rename(path)

    def test_source_ancestor_symlink_substitution_is_detected(self):
        built = self.build()
        inputs = self.root / "inputs"
        saved = self.root / "saved-inputs"
        try:
            with self.assertRaises(ValueError):
                with self.load(built):
                    inputs.rename(saved)
                    inputs.symlink_to(saved, target_is_directory=True)
        finally:
            if inputs.is_symlink():
                inputs.unlink()
            if saved.exists():
                saved.rename(inputs)

    def qualification_operations(self):
        rows = []
        for system in ("openvino_gva", "gstreamer_custom"):
            for resource in ("cpu", "gpu"):
                rows.append(self.operation(f"precheck-{system}-{resource}", "native_precheck", system, resource, "h264", False))
        rows.append(self.operation("savant-original", "savant_original", "savant", "cpu", "h264", False))
        for system in ("deepstream", "savant", "openvino_gva", "gstreamer_custom"):
            for resource in ("cpu", "gpu"):
                for codec in ("h264", "h265"):
                    for shared in (False, True):
                        rows.append(self.operation(f"cell-{system}-{resource}-{codec}-{shared}", "qualification_cell", system, resource, codec, shared))
        return rows

    def test_exact_37_originals_preserve_reused_arms_and_deduplicate_only_wire_constants(self):
        rows = self.qualification_operations()
        built = self.build(mode="complete_qualification_operational_identity_v1", operations=rows)
        with self.load(built) as loaded:
            self.assertEqual(len(loaded["operations_by_id"]), 37)
            self.assertEqual(len(loaded["native_contexts_by_id"]), 37)
            self.assertEqual(len(loaded["runtime_contexts_by_arm"]), 32)
            self.assertEqual(len(loaded["qualification_contexts_by_arm"]), 32)
            self.assertEqual(sum(row["system"] in {"gstreamer_custom", "openvino_gva"} for row in rows), 20)
            for header in loaded["guardian_context"]["headers_by_route"].values():
                self.assertEqual(len(header["contexts"]), 32)
                self.assertEqual(len(header["bindings"]), 192)
                self.assertLessEqual(len(header["front_workers"]), 24)
            for row in rows:
                context = loaded["native_contexts_by_id"][row["operation_id"]]
                self.assertEqual(context["admission_limits"]["max_admissions_per_stream"],
                                 241 if row["system"] in {"gstreamer_custom", "openvino_gva"} else 281)

    def test_full_qualification_refuses_wrong_phase_or_stock_id(self):
        rows = self.qualification_operations()
        for field, value in (("phase", "qualification_cell"), ("run_id", "invented-original")):
            bad = copy.deepcopy(rows)
            bad[0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.build(mode="complete_qualification_operational_identity_v1", operations=bad)

    def test_alias_same_bytes_and_hardlink_are_not_original_custody(self):
        path = Path(self.operations[0]["descriptors"]["source_plan"]["path"])
        alias = path.with_name("alias-source.json")
        alias.symlink_to(path)
        rows = copy.deepcopy(self.operations)
        rows[0]["descriptors"]["source_plan"]["path"] = str(alias)
        with self.assertRaises(ValueError):
            self.build(operations=rows)
        alias.unlink()
        os.link(path, alias)
        with self.assertRaises(ValueError):
            self.build()

    def test_refusal_return_value_and_callback_mutation_are_not_authority(self):
        with self.assertRaisesRegex(ValueError, "return None"):
            self.build(original_operation_validator=lambda row, assets: False)
        def change(row, assets):
            row["policy"] = "gpu_only"
        with self.assertRaisesRegex(ValueError, "mutated"):
            self.build(original_operation_validator=change)
        self.assertFalse((self.root / "outputs/plan").exists())

    def test_context_templates_match_existing_native_loader_and_guardian_header_validator(self):
        from publication_operational_runtime_context_v1 import load_native_operational_context_v1
        from publication_guardian_operational_recorder_v1 import _header, DEFAULT_BUDGETS
        built = self.build()
        # Runtime output reservation belongs to the caller before read custody.
        for row in self.operations:
            (self.root / "outputs" / row["operation_id"]).mkdir()
        with self.load(built) as loaded:
            for row in self.operations:
                selected = loaded["runtime_contexts_by_arm"][row["arm_id"]]
                output = self.root / "outputs" / row["operation_id"]
                result, limits = load_native_operational_context_v1(Path(selected["descriptor"]["path"]), output,
                    **{key: row[key] for key in ("run_id", "system", "scenario", "codec", "policy", "deadline_ms")})
                self.assertEqual(result["header"], selected["context"]["native_header"])
                self.assertEqual(limits, selected["context"]["admission_limits"])
            for route, template in loaded["guardian_context"]["headers_by_route"].items():
                actual = copy.deepcopy(template)
                actual["lifecycle_id"] = "f" * 32
                actual["owner"] = {"uid": 1, "gid": 1, "pid": 2, "proc_stat_starttime_ticks": 3}
                actual["worker_capability"] = {"fixture_only": True}
                actual["descriptors"]["service_authority"] = built["descriptor"]
                header, lookup = _header(actual, tuple(route.split(":")), DEFAULT_BUDGETS)
                self.assertEqual(len(lookup), 12)
                self.assertLessEqual(len(canonical_json_v1(header)) + 1, 65536)

    def test_index_descriptor_cannot_name_another_same_bytes_file(self):
        built = self.build()
        foreign = self.root / "outputs/foreign-index.json"
        foreign.write_bytes(Path(built["descriptor"]["path"]).read_bytes())
        with self.assertRaisesRegex(ValueError, "descriptor path differs"):
            with held_operational_capture_plan_v1(project_root=self.root, index_path=foreign,
                                                 expected_descriptor=built["descriptor"]):
                pass

    def test_unsealed_native_context_is_rejected_after_outer_index_repin(self):
        built = self.build()
        path = Path(built["value"]["native_contexts"][0]["descriptor"]["path"])
        value = json.loads(path.read_bytes())
        value["sha256"] = "0" * 64
        os.chmod(path, 0o600)
        path.write_bytes(canonical_json_v1(value) + b"\n")
        self.reseal_index(built, path)
        with self.assertRaisesRegex(ValueError, "semantic seal"):
            with self.load(built):
                pass

    def test_cold_loader_streams_large_metadata_without_retaining_source_payload_cache(self):
        # Above the cold supplemental 32MiB budget in aggregate, while each
        # fixed input remains within its unchanged16MiB file bound. These are
        # fixture metadata only; model binaries never enter the capture plan.
        self.guardian["model_authority"] = self.write("inputs/large-model-authority.json",
            {"fixture_only": True, "metadata_padding": "x" * (7 * 1024 * 1024)})
        for index, row in enumerate(self.operations):
            row["descriptors"]["model_authority"] = self.guardian["model_authority"]
            row["descriptors"]["calibration"] = self.write(f"inputs/large-calibration-{index}.json",
                {"fixture_only": True, "metadata_padding": "x" * (14 * 1024 * 1024)})
            row["original_operation"] = self.write(f"inputs/large-original-{index}.json",
                {key: value for key, value in row.items() if key != "original_operation"})
        built = self.build()
        tracemalloc.start()
        try:
            with self.load(built) as loaded:
                self.assertEqual(len(loaded["operations_by_id"]), 2)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 32 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
