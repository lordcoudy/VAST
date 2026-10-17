"""Bounded fixture socket setup regression, not complete consumer acceptance.

Only expensive setup providers are spies. The physical sockets, production
socket pin reader and production live transport predicate remain actual.
"""
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace
import ast
import inspect
import shutil
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import publication_policy_qualification_runtime_inputs_v2 as runtime_inputs  # noqa: E402
from tests.fixtures import accepted_policy_physical_fixture_v2 as fixture  # noqa: E402


class AcceptedPolicyFixtureTransportV2Tests(unittest.TestCase):
    def test_bound_only_front_is_refused_by_actual_production_transport_reader(self):
        with tempfile.TemporaryDirectory(prefix="accepted-policy-bound-only-") as raw:
            path = Path(raw) / "front.sock"
            with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as front:
                front.bind(str(path))
                record = runtime_inputs._socket_record(path, label="fixture front")
                with self.assertRaisesRegex(
                    runtime_inputs.QualificationRuntimeInputMaterializationV2Error,
                    "fixture front is not a reachable live SOCK_SEQPACKET transport",
                ):
                    runtime_inputs._require_socket_transport(record, expected_type="0005", label="fixture front")

    def test_prepared_fixture_is_listening_before_two_actual_probes_and_drains_them(self):
        source = inspect.getsource(runtime_inputs._materialize_publication_policy_qualification_runtime_inputs_v2_held)
        probes = [node for node in ast.walk(ast.parse(source))
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                  and node.func.id == "_require_socket_transport"
                  and any(keyword.arg == "expected_type" and isinstance(keyword.value, ast.Constant)
                          and keyword.value.value == "0005" for keyword in node.keywords)]
        self.assertEqual(len(probes), 2, "fixture readiness budget must match actual materializer probes")
        with tempfile.TemporaryDirectory(prefix="accepted-policy-early-front-") as raw:
            root = Path(raw)
            output = root / "consumer"
            common = {key: root / key for key in (
                "candidate_index_path", "candidate_manifest_path", "candidate_receipt_path",
                "bootstrap_mapping_path", "bootstrap_receipt_path", "bootstrap_dir", "transaction_receipt_path",
            )}
            observed = []
            native_root = None

            @contextmanager
            def engine_setup_spy(**kwargs):
                nonlocal native_root
                native_root = kwargs["socket_path"].parent.parent
                yield SimpleNamespace(engine=SimpleNamespace(path=root / "setup-engine"),
                                      engine_socket={"path": kwargs["socket_path"]})

            @contextmanager
            def held_plan_setup_spy(**kwargs):
                yield {"setup_provider_spy": True}

            def runtime_setup_spy(**kwargs):
                path = kwargs["analytics_socket_path"]
                before = runtime_inputs._socket_record(path, label="fixture front")
                for _ in range(len(probes)):
                    runtime_inputs._require_socket_transport(before, expected_type="0005", label="fixture front")
                    observed.append(runtime_inputs._socket_record(path, label="fixture front"))
                assets = output / "setup-runtime-assets"
                assets.mkdir()
                engine_asset = assets / fixture.DOCKER_ASSET
                engine_asset.parent.mkdir(parents=True)
                engine_asset.write_bytes(b"fixture setup pin only; never executed\n")
                return {"runtime_input_root": assets, "front_pin": before}

            providers = {
                "prepare_original_fixture_engine_v1": engine_setup_spy,
                "materialize_publication_policy_qualification_transaction_v2": lambda **kwargs: common,
                "materialize_guardian_preprocessing_contract_v1": lambda **kwargs: {
                    "contract_path": root / "setup-contract", "receipt_path": root / "setup-receipt"},
                "materialize_execution_code_closure_v1": lambda **kwargs: {"setup_provider_spy": True},
                "prepare_stock_operational_capture_plan_v1": lambda **kwargs: {
                    "descriptor": {"path": root / "setup-capture-plan"}},
                "held_operational_capture_plan_v1": held_plan_setup_spy,
                "materialize_publication_policy_qualification_runtime_inputs_v2": runtime_setup_spy,
            }
            try:
                with ExitStack() as stack:
                    for name, replacement in providers.items():
                        stack.enter_context(patch.object(fixture, name, replacement))
                    with fixture.prepared_complete_fixture_inputs_v2(
                        project_root=root, output_dir=output, identity_patch_path=root / "setup-patch",
                        accepted_model_parity_manifest_path=root / "setup-manifest",
                        accepted_model_parity_assessment_path=root / "setup-assessment",
                        accepted_model_parity_receipt_path=root / "setup-parity-receipt",
                        image_inspections={}, device_probes={}, socket_prefix=".apf-ready-test",
                    ) as prepared:
                        native_root = prepared["native_socket_root"]
                        front = prepared["front_socket"]
                        self.assertEqual(observed, [prepared["runtime"]["front_pin"]] * len(probes))
                        self.assertIsNone(front.gettimeout())
                        front.setblocking(False)
                        try:
                            with self.assertRaises(BlockingIOError):
                                front.accept()
                            for _ in range(2):
                                runtime_inputs._require_socket_transport(
                                    prepared["runtime"]["front_pin"], expected_type="0005", label="fixture front")
                                connection, _ = front.accept()
                                connection.close()
                            with self.assertRaises(BlockingIOError):
                                front.accept()
                        finally:
                            front.setblocking(True)
            finally:
                if native_root is not None:
                    shutil.rmtree(native_root)


if __name__ == "__main__":
    unittest.main()
