"""Stock source equations for native and SDK capture planning, without Docker."""
from __future__ import annotations
import copy
from contextlib import ExitStack
import hashlib
import json
import socket
import tempfile
from types import SimpleNamespace
from pathlib import Path
import sys
import unittest
from unittest import mock
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from checkpoint_gstreamer_runtime import build_publication_pair_plans
import publication_operational_stock_operations_v1 as target


class StockOperationPlanningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = yaml.safe_load((ROOT / "configs/experiments.yaml").read_bytes())
        cls.datasets = yaml.safe_load((ROOT / "configs/datasets.yaml").read_bytes())["datasets"]
        cls.capabilities = {(branch, resource): {"worker_id": "actual-binding-" + branch + "-" + resource}
                            for branch in target.BRANCHES for resource in ("cpu", "gpu")}

    def test_native_ids_follow_actual_branch_and_graph_processes_for_both_codecs(self):
        for system in ("gstreamer_custom", "openvino_gva"):
            for codec in ("h264", "h265"):
                pair = build_publication_pair_plans(config=self.config, datasets=self.datasets,
                                                    system=system, codec=codec)
                for topology, plan in pair.items():
                    with self.subTest(system=system, codec=codec, topology=topology):
                        actual = target.front_workers_from_stock_plan_v1(plan, self.capabilities)
                        for branch in target.BRANCHES:
                            for resource in ("cpu", "gpu"):
                                rows = actual[branch + ":" + resource]
                                self.assertEqual([row["stream_id"] for row in rows], list(range(6)))
                                for stream, row in zip(plan["streams"], rows, strict=True):
                                    expected = (stream["graph_process"]["process_id"] if topology == "shared"
                                        else next(worker["process_id"] for worker in stream["workers"]
                                                  if worker["branch_id"] == branch))
                                    self.assertEqual(row["worker_id"], expected)

    def test_sdk_front_worker_uses_actual_binding_capability_for_each_route(self):
        for system in ("deepstream", "savant"):
            plan = build_publication_pair_plans(config=self.config, datasets=self.datasets,
                                                system=system, codec="h264")["shared"]
            actual = target.front_workers_from_stock_plan_v1(plan, self.capabilities)
            for route, rows in actual.items():
                self.assertEqual({row["worker_id"] for row in rows},
                                 {self.capabilities[tuple(route.split(":"))]["worker_id"]})
                self.assertEqual([row["stream_id"] for row in rows], list(range(6)))

    def test_incomplete_or_substituted_stock_source_never_generates_a_context(self):
        plan = build_publication_pair_plans(config=self.config, datasets=self.datasets,
                                            system="gstreamer_custom", codec="h264")["baseline"]
        missing = copy.deepcopy(plan)
        missing["streams"].pop()
        with self.assertRaises(ValueError):
            target.front_workers_from_stock_plan_v1(missing, self.capabilities)
        wrong = copy.deepcopy(plan)
        wrong["streams"][0]["workers"][0]["branch_id"] = "foreign_branch"
        with self.assertRaises(ValueError):
            target.front_workers_from_stock_plan_v1(wrong, self.capabilities)
        sdk = build_publication_pair_plans(config=self.config, datasets=self.datasets,
                                           system="savant", codec="h264")["baseline"]
        caps = copy.deepcopy(self.capabilities)
        caps[("damage", "gpu")]["worker_id"] = ""
        with self.assertRaises(ValueError):
            target.front_workers_from_stock_plan_v1(sdk, caps)


class PhysicalStockOperationPlanningSeamTests(unittest.TestCase):
    """Real planning/bytes with stock authority and image probes fixture-backed.

    This verifies composition and reservations only, never transaction, parity,
    engine/model or publication acceptance.
    """
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        import publication_policy_qualification_runtime_inputs_v2 as stock
        self.stock = stock
        sys.path.insert(0, str(ROOT / "tests"))
        from test_checkpoint_gstreamer_analytics_sidecar import _binding, _probe, _load_execution_config
        self.config = _load_execution_config()
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(self.socket.close)
        self.socket_path = self.root / "engine.sock"
        self.socket.bind(str(self.socket_path))
        self.socket.listen(2)
        (self.root / "configs").mkdir()
        (self.root / "guardian").mkdir()
        (self.root / "configs/experiments.yaml").write_bytes((ROOT / "configs/experiments.yaml").read_bytes())
        for path in ("deploy/native_gst_probe/vast_native_gst_probe.cpp",
                     "scripts/checkpoint_deepstream_protocol_bridge.py", "scripts/checkpoint_native_policy_runtime.py"):
            target_path = self.root / path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes((ROOT / path).read_bytes())
        self.candidate = self.write("candidate.json", {"fixture_only": True})
        self.model = self.write("model-authority.json", {"fixture_only": True})
        self.closure = self.write("code-closure.json", {"fixture_only": True})
        self.execution = self.write("execution-config.json", self.config)
        calibrations = {system: SimpleNamespace(path=Path(self.write(system + ".calibration.json", {"fixture_only": True})["path"]))
                        for system in stock.SYSTEMS}
        self.inputs = SimpleNamespace(root=self.root, candidate_manifest=SimpleNamespace(path=Path(self.candidate["path"])),
                                      calibrations=calibrations, pins=())
        datasets = yaml.safe_load((ROOT / "configs/datasets.yaml").read_bytes())["datasets"]
        self.inventory = SimpleNamespace(root=self.root, datasets=datasets,
            analytics_execution_pin=SimpleNamespace(path=Path(self.execution["path"])),
            analytics_bindings={(branch, resource): _binding(branch, resource, self.config)
                                for branch in target.BRANCHES for resource in ("cpu", "gpu")},
            runtime_probes={resource: _probe(resource, self.config) for resource in ("cpu", "gpu")})
        self.fixed = {"experiments_config": stock._project_pin(self.root, "configs/experiments.yaml", label="fixture config")}
        image = {"image_id": "sha256:" + "1" * 64, "repository_digest": "fixture/image@sha256:" + "2" * 64,
                 "inspect_projection_sha256": "3" * 64, "base_image_id": "sha256:" + "4" * 64}
        self.images = {system: {"contract": copy.deepcopy(image)} for system in stock.SYSTEMS}

    def write(self, relative, value):
        path = self.root / relative
        raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
        path.write_bytes(raw)
        return {"path": str(path), "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

    def prepare(self, mode, resource=None, inspect=None):
        from publication_guardian_preprocessing_contract_v1 import load_guardian_preprocessing_contract_v1
        with ExitStack() as stack:
            stack.enter_context(mock.patch.multiple(self.stock,
                _load_qualification_inputs=mock.Mock(return_value=self.inputs),
                _load_source_inventory=mock.Mock(return_value=self.inventory),
                _preflight_reachable_runtime_contracts=mock.Mock(),
                _inventory_identity=mock.Mock(return_value="fixture-only-inventory"),
                _fixed_project_pins=mock.Mock(return_value=self.fixed),
                _inspect_runtime_images=mock.Mock(side_effect=inspect) if inspect else mock.Mock(return_value=self.images)))
            stack.enter_context(mock.patch("publication_guardian_preprocessing_contract_v1.load_guardian_preprocessing_contract_v1",
                return_value={"receipt": {"model_parity_refresh_authority": {"binding_set": {"index": self.model}}}}))
            stack.enter_context(mock.patch("publication_policy_qualification_execution_code_closure_v1.load_execution_code_closure_v1",
                return_value={"receipt_descriptor": self.closure}))
            return target.prepare_stock_operational_capture_plan_v1(project_root=self.root, output_dir=self.root / "capture",
                mode=mode, candidate_index_path="fixture-index.json", candidate_manifest_path=self.candidate["path"],
                candidate_receipt_path="fixture-receipt.json", bootstrap_mapping_path="fixture-mapping.json",
                bootstrap_receipt_path="fixture-bootstrap-receipt.json", bootstrap_dir=self.root,
                transaction_receipt_path="fixture-transaction.json", preprocessing_contract_path="fixture-preproc.json",
                preprocessing_receipt_path="fixture-preproc-receipt.json", execution_code_closure_path=self.closure["path"],
                pilot_root=self.root / "pilots", guardian_output_dir=self.root / "guardian/output",
                diagnostic_resource=resource, container_engine_path=Path(sys.executable).resolve(),
                container_engine_socket_path=self.socket_path)

    def test_stock_37_source_equations_are_physically_pinned_with_exact_final_reservations(self):
        built = self.prepare(target.QUALIFICATION_MODE)
        from publication_operational_capture_plan_v1 import held_operational_capture_plan_v1
        with held_operational_capture_plan_v1(project_root=self.root, index_path=built["descriptor"]["path"]) as held:
            rows = list(held["operations_by_id"].values())
            self.assertEqual(len(rows), 37)
            self.assertEqual(sum(row["system"] in {"gstreamer_custom", "openvino_gva"} for row in rows), 20)
            self.assertEqual(len(held["qualification_contexts_by_arm"]), 32)
            self.assertEqual({row["phase"] for row in rows}, {"native_precheck", "savant_original", "qualification_cell"})
            for row in rows:
                original = json.loads(Path(row["original_operation"]["path"]).read_bytes())
                self.assertEqual(original["operation"], {key: value for key, value in row.items() if key != "original_operation"})
                output = original["outputs"]
                self.assertEqual(output["native_domain"], output["measurement_dir"] + ".operational/native_operational_requests.v1.jsonl")
                self.assertFalse(Path(output["measurement_dir"]).exists())
                self.assertFalse(Path(output["process_receipt"]).exists())
        self.assertFalse((self.root / "guardian/output").exists())

    def test_stock_native_pair_selection_preserves_two_distinct_contexts_and_mode(self):
        built = self.prepare(target.DIAGNOSTIC_MODE, "gpu")
        from publication_operational_capture_plan_v1 import held_operational_capture_plan_v1
        with held_operational_capture_plan_v1(project_root=self.root, index_path=built["descriptor"]["path"]) as held:
            rows = list(held["operations_by_id"].values())
            self.assertEqual(len(rows), 2)
            self.assertEqual({row["policy"] for row in rows}, {"gpu_only"})
            self.assertEqual({row["scenario"] for row in rows},
                {"checkpoint_video_dag_shared", "checkpoint_independent_processes_baseline"})
            self.assertEqual(held["index"]["mode"], target.DIAGNOSTIC_MODE)

    def test_source_mutation_after_stock_observation_prevents_any_capture_index(self):
        def mutate(*args, **kwargs):
            path = self.root / "configs/experiments.yaml"
            path.write_bytes(path.read_bytes() + b"\n")
            return self.images
        with self.assertRaises(RuntimeError):
            self.prepare(target.DIAGNOSTIC_MODE, "cpu", inspect=mutate)
        self.assertFalse((self.root / "capture/capture-plan/index.v1.json").exists())


if __name__ == "__main__":
    unittest.main()
