"""Bounded fixture binding contract, not complete consumer acceptance.

Only upstream preparation/lifecycle providers are stubs in the caller regression.
It stops at the closure boundary; the unchanged stock binding constructor is real.
Temporary leaf bytes are synthetic descriptor inputs, not process custody evidence.
"""
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import publication_qualification_operational_owner_v1 as owner  # noqa: E402
from publication_physical_io_v1 import PublicationPhysicalIoV1Error  # noqa: E402
from tests.fixtures import accepted_policy_checkpoint_fixture_v1 as checkpoint  # noqa: E402
from tests.fixtures import accepted_policy_consumer_fixture_v2 as fixture  # noqa: E402

OUTPUT_ROLES = ("native_domain", "process_receipt", "container_receipt",
                "measurement_decisions", "accepted_ingress")


class _BindingBoundaryReached(Exception):
    pass


class AcceptedPolicyFixtureBindingV2Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="accepted-policy-binding-contract-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve(strict=True)
        self.output = self.root / "consumer"
        self.output.mkdir()
        self.original_paths = []

        def leaf(path, content):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            self.original_paths.append(path)
            return {"path": str(path), "size_bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest()}

        self.capture_plan = leaf(self.root / "capture-plan.json", b"synthetic capture-plan leaf\n")
        self.group = leaf(self.root / "guardian-group.json", b"synthetic guardian-group leaf\n")
        operations = []
        self.expected_outputs = []
        for position in range(37):
            operation_id = f"fixture-operation-{position:02d}"
            directory = self.root / "originals" / operation_id
            captures = {role: leaf(directory / (role + ".json"),
                                   f"synthetic {operation_id} {role}\n".encode("ascii"))
                        for role in OUTPUT_ROLES[:3]}
            decisions = leaf(directory / "publication_policy_decisions.jsonl", b"synthetic decisions\n")
            ingress = leaf(directory / "ingress_ledger.csv", b"synthetic ingress\n")
            operations.append({"operation": {"operation_id": operation_id}, "capture": captures,
                               "original": {"outputs": {"measurement_dir": str(directory)}}})
            self.expected_outputs.append({"operation_id": operation_id, **captures,
                                          "measurement_decisions": decisions, "accepted_ingress": ingress})
        self.native = {"operations": operations, "native_domains": [], "capability_manifest": {}}
        self.prepared = {"root": self.root, "output_dir": self.output,
                         "capture_plan_descriptor": self.capture_plan,
                         "capture_plan": {"guardian_context": {"headers_by_route": {}}},
                         "transaction": {"candidate_manifest_path": self.root / "candidate-manifest.json",
                                         "transaction_receipt_path": self.root / "transaction.json"},
                         "preprocessing": {"contract_path": self.root / "contract.json",
                                           "receipt_path": self.root / "preprocessing-receipt.json"},
                         "runtime": {"receipt_path": self.root / "runtime.json"},
                         "pilot_root": self.root / "pilots", "front_socket": None, "control_socket": None,
                         "guardian_output_dir": self.root / "journals"}
        self.journals = {"operational_group": self.group, "lifecycle_counters": {}}

    def test_complete_fixture_binding_uses_absolute_stock_output_contract(self):
        loaded = {"authority": {}, "receipt": {"model_parity_refresh_authority": {
            "execution_config": {"path": "config.json"}, "binding_set": {"index": {"path": "bindings/index.json"}},
            "runtime_probes": {}}}}
        session = SimpleNamespace(authority={}, owner_process={}, authority_descriptor={}, close=lambda: None)

        def inspect_binding_at_closure(**kwargs):
            value = json.loads(Path(kwargs["operational_accounting_binding_path"]).read_bytes())
            stock = owner.operational_execution_binding_v1(**{
                name: value[name] for name in ("mode", "capture_plan", "guardian_companion", "operation_outputs")})
            self.assertEqual(stock, value)
            self.assertEqual(value["operation_outputs"], self.expected_outputs)
            self.assertEqual(value["capture_plan"], self.capture_plan)
            self.assertEqual(value["guardian_companion"], self.group)
            raise _BindingBoundaryReached

        providers = {
            "load_guardian_preprocessing_contract_v1": lambda **kwargs: loaded,
            "load_execution_config": lambda path: {},
            "load_materialized_binding_set": lambda *args, **kwargs: SimpleNamespace(capabilities={}),
            "runtime_expectations_from_preprocessing_receipt_v1": lambda value: {},
            "begin_fixture_guardian_lifecycle_v1": lambda **kwargs: session,
            "write_fixture_guardian_operational_journals_v1": lambda **kwargs: self.journals,
            "finalize_fixture_qualification_cells_v2": lambda **kwargs: [],
            "finish_fixture_guardian_lifecycle_v1": lambda *args, **kwargs: {},
            "materialize_publication_policy_qualification_execution_closure_v1": inspect_binding_at_closure,
        }
        with ExitStack() as stack:
            for name, replacement in providers.items():
                stack.enter_context(patch.object(fixture, name, replacement))
            stack.enter_context(patch.object(checkpoint, "write_complete_fixture_checkpoint_v1",
                                             lambda **kwargs: self.root / "checkpoint.json"))
            with self.assertRaises(_BindingBoundaryReached):
                fixture.materialize_fixture_completed_execution_v2(prepared=self.prepared, native=self.native)

    def test_shared_fixture_helper_preserves_all37_original_outputs_and_bytes(self):
        before = {str(path): path.read_bytes() for path in self.original_paths}
        native_before = copy.deepcopy(self.native)
        path = fixture._write_fixture_operational_binding_v2(
            prepared=self.prepared, native=self.native, journals=self.journals)
        value = json.loads(path.read_bytes())
        self.assertEqual(value["operation_outputs"], self.expected_outputs)
        self.assertEqual(len(value["operation_outputs"]), 37)
        self.assertEqual(value["capture_plan"], self.capture_plan)
        self.assertEqual(value["guardian_companion"], self.group)
        self.assertEqual(self.native, native_before)
        for output in value["operation_outputs"]:
            for role in OUTPUT_ROLES:
                with self.subTest(operation=output["operation_id"], role=role):
                    target = Path(output[role]["path"])
                    self.assertTrue(target.is_absolute())
                    self.assertEqual(target.resolve(strict=True), target)
                    self.assertEqual(target.stat().st_nlink, 1)
                    self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), output[role]["sha256"])
        self.assertEqual({str(path): path.read_bytes() for path in self.original_paths}, before)

    def test_stock_writer_refuses_each_relative_output_role_before_creation(self):
        before = {str(path): path.read_bytes() for path in self.original_paths}
        for role in OUTPUT_ROLES:
            with self.subTest(role=role):
                outputs = copy.deepcopy(self.expected_outputs)
                outputs[0][role]["path"] = Path(outputs[0][role]["path"]).relative_to(self.root).as_posix()
                destination = self.output / ("relative-" + role + ".json")
                with self.assertRaisesRegex(ValueError, "original binding descriptor is not absolute"):
                    owner.write_operational_execution_binding_v1(
                        project_root=self.root, binding_path=destination,
                        mode="complete_qualification_operational_identity_v1", capture_plan=self.capture_plan,
                        guardian_companion=self.group, operation_outputs=outputs)
                self.assertFalse(destination.exists())
        self.assertEqual({str(path): path.read_bytes() for path in self.original_paths}, before)

    def test_shared_fixture_helper_refuses_overwrite_and_preserves_originals(self):
        before = {str(path): path.read_bytes() for path in self.original_paths}
        path = fixture._write_fixture_operational_binding_v2(
            prepared=self.prepared, native=self.native, journals=self.journals)
        original_binding = path.read_bytes()
        with self.assertRaisesRegex(PublicationPhysicalIoV1Error, "immutable output already exists"):
            fixture._write_fixture_operational_binding_v2(
                prepared=self.prepared, native=self.native, journals=self.journals)
        self.assertEqual(path.read_bytes(), original_binding)
        self.assertEqual({str(path): path.read_bytes() for path in self.original_paths}, before)


if __name__ == "__main__":
    unittest.main()
