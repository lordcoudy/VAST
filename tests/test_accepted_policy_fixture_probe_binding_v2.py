"""Bounded real-ELF/default-probe setup checks, not consumer acceptance.

Only expensive upstream setup providers are spies. The actual fixture ELF,
production default probe command/reader and live socket predicate remain real.
All image/probe/patch inputs here are explicitly artificial schema projections.
"""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import publication_policy_qualification_runtime_inputs_v2 as runtime_inputs  # noqa: E402
from tests.fixtures import accepted_policy_physical_fixture_v2 as fixture  # noqa: E402


def artificial_reply_inputs_v2():
    systems = ("openvino_gva", "gstreamer_custom")
    patch_value, inspections, probes = {"systems": {}}, {}, {}
    for number, system in enumerate(systems, 1):
        image_id = "sha256:" + str(number) * 64
        patch_value["systems"][system] = {
            "physical_identity": {"image_id": image_id}, "fragment_identity": {"image_id": image_id},
        }
        inspections[image_id] = {"Id": image_id, "RepoTags": ["fixture/" + system + ":only"],
            "RepoDigests": ["fixture/" + system + "@" + image_id],
            "Config": {"Labels": {"fixture_only": "true"}, "Entrypoint": ["/fixture/" + system]}}
        probes[system] = {"schema_version": 1, "artifact_kind": "vast_openvino_checkpoint_device_probe",
            "openvino_version": "explicit-artificial-" + system, "available_devices": [{"device_id": "CPU"}],
            "gstreamer_elements": {"identity": {"available": True, "factory": "identity"}}}
    for number in range(3, 7):
        image_id = "sha256:" + str(number) * 64
        inspections[image_id] = {"Id": image_id, "RepoTags": ["fixture/other-" + str(number) + ":only"],
            "RepoDigests": ["fixture/other-" + str(number) + "@" + image_id]}
    return patch_value, inspections, probes


@contextmanager
def bounded_prepared_setup_v2(root, patch_path, inspections, probes, observed):
    output = root / "consumer"
    common = {key: root / key for key in (
        "candidate_index_path", "candidate_manifest_path", "candidate_receipt_path",
        "bootstrap_mapping_path", "bootstrap_receipt_path", "bootstrap_dir", "transaction_receipt_path",
    )}
    native_root = None

    @contextmanager
    def held_plan_spy(**kwargs):
        yield {"setup_provider_spy": True}

    def runtime_setup_spy(**kwargs):
        nonlocal native_root
        engine_path = kwargs["container_engine_path"]
        engine_socket = Path(kwargs["container_engine_socket_path"])
        native_root = engine_socket.parent.parent
        patch_value = json.loads(patch_path.read_bytes())
        for system in ("openvino_gva", "gstreamer_custom"):
            image = patch_value["systems"][system]["physical_identity"]["image_id"]
            try:
                value = runtime_inputs._default_probe_openvino_device(engine_path, engine_socket, root, image, system)
            except runtime_inputs.QualificationRuntimeInputMaterializationV2Error:
                # Preserve the actual ELF status alongside the default reader's refusal.
                result = subprocess.run([str(engine_path), "--host=unix://" + str(engine_socket), "run", image,
                    "/workspace/project/deploy/openvino/checkpoint/probe_openvino_devices.py"], capture_output=True)
                print(json.dumps({"bounded_probe_red": True, "system": system,
                    "actual_elf_exit_code": result.returncode, "stdout_bytes": len(result.stdout),
                    "stderr_bytes": len(result.stderr)}), file=sys.stderr, flush=True)
                raise
            observed[system] = value
            if value != probes[system]:
                raise AssertionError("actual default probe did not return the unchanged system payload")
        with unittest.TestCase().assertRaisesRegex(
            runtime_inputs.QualificationRuntimeInputMaterializationV2Error, "fixture_unknown OpenVINO device probe failed closed",
        ):
            runtime_inputs._default_probe_openvino_device(
                engine_path, engine_socket, root, "sha256:" + "f" * 64, "fixture_unknown")
        pin = runtime_inputs._socket_record(kwargs["analytics_socket_path"], label="fixture front")
        for _ in range(2):
            runtime_inputs._require_socket_transport(pin, expected_type="0005", label="fixture front")
        assets = output / "setup-runtime-assets"
        engine_asset = assets / fixture.DOCKER_ASSET
        engine_asset.parent.mkdir(parents=True)
        engine_asset.write_bytes(b"fixture setup pin only; never executed\n")
        return {"runtime_input_root": assets}

    providers = {
        "materialize_publication_policy_qualification_transaction_v2": lambda **kwargs: common,
        "materialize_guardian_preprocessing_contract_v1": lambda **kwargs: {
            "contract_path": root / "setup-contract", "receipt_path": root / "setup-receipt"},
        "materialize_execution_code_closure_v1": lambda **kwargs: {"setup_provider_spy": True},
        "prepare_stock_operational_capture_plan_v1": lambda **kwargs: {"descriptor": {"path": root / "setup-plan"}},
        "held_operational_capture_plan_v1": held_plan_spy,
        "materialize_publication_policy_qualification_runtime_inputs_v2": runtime_setup_spy,
    }
    try:
        with ExitStack() as stack:
            for name, replacement in providers.items():
                stack.enter_context(patch.object(fixture, name, replacement))
            with fixture.prepared_complete_fixture_inputs_v2(
                project_root=root, output_dir=output, identity_patch_path=patch_path,
                accepted_model_parity_manifest_path=root / "setup-manifest",
                accepted_model_parity_assessment_path=root / "setup-assessment",
                accepted_model_parity_receipt_path=root / "setup-receipt", image_inspections=inspections,
                device_probes=probes, socket_prefix=".apf-probe-test",
            ) as prepared:
                native_root = prepared["native_socket_root"]
                yield prepared
    finally:
        if native_root is not None:
            shutil.rmtree(native_root)


@unittest.skipUnless(sys.platform == "linux" and shutil.which("cc"), "genuine held ELF fixture requires Linux C compiler")
class AcceptedPolicyFixtureProbeBindingV2Tests(unittest.TestCase):
    def assert_prewrite_refusal(self, transform, message):
        with tempfile.TemporaryDirectory(prefix="accepted-policy-probe-refusal-") as raw:
            root = Path(raw).resolve(strict=True)
            patch_value, inspections, probes = artificial_reply_inputs_v2()
            transform(patch_value, inspections, probes)
            patch_path = root / "identity-patch.json"
            patch_path.write_text(json.dumps(patch_value), encoding="ascii")
            output_parent = root / "must-remain-absent"
            output = output_parent / "consumer"
            self.assertFalse(output_parent.exists())
            before = (patch_path.read_bytes(), deepcopy(inspections), deepcopy(probes))
            with patch.object(fixture.tempfile, "mkdtemp") as sockets, \
                    patch.object(fixture, "prepare_original_fixture_engine_v1") as engine:
                with self.assertRaisesRegex(ValueError, message):
                    with fixture.prepared_complete_fixture_inputs_v2(
                        project_root=root, output_dir=output, identity_patch_path=patch_path,
                        accepted_model_parity_manifest_path=root / "unused-manifest",
                        accepted_model_parity_assessment_path=root / "unused-assessment",
                        accepted_model_parity_receipt_path=root / "unused-receipt",
                        image_inspections=inspections, device_probes=probes,
                    ):
                        self.fail("malformed command replies reached prepared yield")
                sockets.assert_not_called()
                engine.assert_not_called()
            self.assertFalse(output.exists())
            self.assertFalse(output_parent.exists())
            self.assertEqual((patch_path.read_bytes(), inspections, probes), before)

    def test_missing_system_probe_is_refused_before_writes(self):
        self.assert_prewrite_refusal(lambda patch_value, images, probes: probes.pop("openvino_gva"),
            "fixture device probe map requires exactly two system objects")

    def test_foreign_system_probe_is_refused_before_writes(self):
        self.assert_prewrite_refusal(lambda patch_value, images, probes: probes.update({"foreign": {}}),
            "fixture device probe map requires exactly two system objects")

    def test_nonobject_probe_is_refused_before_writes(self):
        self.assert_prewrite_refusal(lambda patch_value, images, probes: probes.update({"openvino_gva": "bad"}),
            "fixture device probe map requires exactly two system objects")

    def test_missing_captured_image_is_refused_before_writes(self):
        self.assert_prewrite_refusal(lambda patch_value, images, probes: images.pop("sha256:" + "1" * 64),
            "fixture device probe image is missing from captured inspections")

    def test_captured_image_id_mismatch_is_refused_before_writes(self):
        self.assert_prewrite_refusal(lambda patch_value, images, probes: images["sha256:" + "1" * 64].update(
            {"Id": "sha256:" + "f" * 64}), "captured fixture image key and Id must agree exactly")

    def test_fragment_image_id_mismatch_is_refused_before_writes(self):
        self.assert_prewrite_refusal(lambda patch_value, images, probes:
            patch_value["systems"]["openvino_gva"]["fragment_identity"].update({"image_id": "sha256:" + "f" * 64}),
            "fixture device probe physical and fragment image IDs disagree")

    def test_malformed_patch_image_id_is_refused_before_writes(self):
        self.assert_prewrite_refusal(lambda patch_value, images, probes:
            patch_value["systems"]["openvino_gva"]["physical_identity"].update({"image_id": True}),
            "fixture device probe physical and fragment image IDs disagree")

    def test_missing_patch_identity_is_refused_before_writes(self):
        self.assert_prewrite_refusal(lambda patch_value, images, probes:
            patch_value["systems"]["openvino_gva"].pop("fragment_identity"),
            "fixture device probe identity patch is malformed")

    def test_shared_system_image_id_is_refused_before_writes(self):
        def shared(patch_value, images, probes):
            for kind in ("physical_identity", "fragment_identity"):
                patch_value["systems"]["gstreamer_custom"][kind]["image_id"] = "sha256:" + "1" * 64
        self.assert_prewrite_refusal(shared, "fixture device probe systems share one image ID")

    def test_conflicting_captured_alias_is_refused_before_writes(self):
        self.assert_prewrite_refusal(lambda patch_value, images, probes: images["sha256:" + "2" * 64].update(
            {"RepoTags": images["sha256:" + "1" * 64]["RepoTags"]}), "captured image inspection aliases disagree")

    def test_malformed_captured_alias_is_refused_before_writes(self):
        self.assert_prewrite_refusal(lambda patch_value, images, probes: images["sha256:" + "1" * 64].update(
            {"RepoDigests": "not-a-list"}), "captured fixture image aliases are malformed")

    def test_falsey_nonlist_captured_aliases_are_refused_before_writes(self):
        for value in (False, 0, ""):
            with self.subTest(value=value):
                self.assert_prewrite_refusal(lambda patch_value, images, probes:
                    images["sha256:" + "1" * 64].update({"RepoTags": value}),
                    "captured fixture image aliases are malformed")

    def test_empty_maps_remain_explicit_transport_only_boundary(self):
        self.assertEqual(fixture._fixture_command_replies_v2(
            identity_patch_path=ROOT / "does-not-exist-empty-transport-patch", image_inspections={}, device_probes={}), ({}, {}))

    def test_reply_maps_require_explicit_objects(self):
        with self.assertRaisesRegex(ValueError, "fixture command reply maps must be explicit objects"):
            fixture._fixture_command_replies_v2(identity_patch_path=ROOT / "unused-patch",
                image_inspections=[], device_probes={})

    def test_prepared_context_binds_system_probes_to_exact_patch_image_ids(self):
        with tempfile.TemporaryDirectory(prefix="accepted-policy-probe-binding-") as raw:
            root = Path(raw).resolve(strict=True)
            patch_value, inspections, probes = artificial_reply_inputs_v2()
            patch_path = root / "identity-patch.json"
            patch_path.write_text(json.dumps(patch_value), encoding="ascii")
            before_patch, before_inspections, before_probes = patch_path.read_bytes(), deepcopy(inspections), deepcopy(probes)
            observed = {}
            with bounded_prepared_setup_v2(root, patch_path, inspections, probes, observed) as prepared:
                self.assertEqual(observed, probes)
                self.assertFalse(prepared["engine"].state_path.exists())
                source = (prepared["output_dir"] / "command-boundary/immutable/engine.c").read_text(encoding="ascii")
                for system in probes:
                    image_id = patch_value["systems"][system]["physical_identity"]["image_id"]
                    self.assertIn('{"' + image_id + '",', source)
                    self.assertNotIn('{"' + system + '",', source)
                front = prepared["front_socket"]
                front.setblocking(False)
                try:
                    with self.assertRaises(BlockingIOError):
                        front.accept()
                finally:
                    front.setblocking(True)
            self.assertEqual(patch_path.read_bytes(), before_patch)
            self.assertEqual(inspections, before_inspections)
            self.assertEqual(probes, before_probes)


if __name__ == "__main__":
    unittest.main()
