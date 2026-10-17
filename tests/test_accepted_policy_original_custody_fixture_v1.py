"""Real custody-reader checks for artificial, noncampaign fixture processes."""

import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from publication_operational_request_domain_v1 import canonical_json_v1, payload_with_sha256_v1


@unittest.skipUnless(sys.platform == "linux" and shutil.which("cc"), "genuine held ELF fixture requires Linux C compiler")
class AcceptedPolicyOriginalCustodyFixtureTests(unittest.TestCase):
    def test_real_default_command_boundaries_read_exact_inspection_and_probe_objects(self):
        from publication_policy_qualification_runtime_inputs_v2 import (
            QualificationRuntimeInputMaterializationV2Error, _default_inspect_image, _default_probe_openvino_device,
        )
        from tests.fixtures.accepted_policy_original_custody_fixture_v1 import prepare_original_fixture_engine_v1
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve(strict=True)
            image_id = "sha256:" + "1" * 64
            image = {"Id": image_id, "RepoDigests": ["fixture/runtime@" + image_id],
                "Config": {"Labels": {"fixture_only": "true"}, "Entrypoint": ["/fixture/runtime"]}}
            probe = {"schema_version": 1, "artifact_kind": "vast_openvino_checkpoint_device_probe",
                "openvino_version": "explicit-artificial-fixture", "available_devices": [{"device_id": "CPU"}],
                "gstreamer_elements": {"identity": {"available": True, "factory": "identity"}}}
            with prepare_original_fixture_engine_v1(project_root=root, output_dir=root / "fixture-engine",
                    image_inspections={image_id: image}, device_probes={image_id: probe}) as held:
                self.assertEqual(_default_inspect_image(held.engine.path, Path(held.engine_socket["path"]), image_id), image)
                for system in ("openvino_gva", "gstreamer_custom"):
                    with self.subTest(system=system):
                        self.assertEqual(_default_probe_openvino_device(held.engine.path,
                            Path(held.engine_socket["path"]), root, image_id, system), probe)
                with self.assertRaisesRegex(QualificationRuntimeInputMaterializationV2Error, "failed closed"):
                    _default_inspect_image(held.engine.path, Path(held.engine_socket["path"]), "sha256:" + "2" * 64)
                self.assertFalse(held.state_path.exists())

    def test_two_fresh_operations_share_one_held_engine_and_run_both_real_cold_readers(self):
        from tests.fixtures.accepted_policy_original_custody_fixture_v1 import (
            capture_original_fixture_operation_v1, prepare_original_fixture_engine_v1,
        )
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve(strict=True)

            def write(path, value):
                raw = canonical_json_v1(value) + b"\n"
                path.write_bytes(raw)
                return {"path": str(path), "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

            with prepare_original_fixture_engine_v1(project_root=root, output_dir=root / "fixture-engine") as held:
                engine_descriptor = dict(held.engine_descriptor)
                observed_engines = []
                for number, system in enumerate(("gstreamer_custom", "openvino_gva"), 1):
                    operation_id = f"fresh-operation-{number}"
                    directory = root / operation_id
                    directory.mkdir()
                    context = write(directory / "context.json", {"fixture_only": True, "operation_id": operation_id})
                    image = {"image_id": "sha256:" + str(number) * 64,
                        "repository_digest": f"fixture/{system}@sha256:" + "3" * 64,
                        "inspect_projection_sha256": "4" * 64}
                    if system == "gstreamer_custom":
                        image["base_image_id"] = "sha256:" + "5" * 64
                    native = directory / "native/native_operational_requests.v1.jsonl"
                    process = directory / "process/original_engine_process_capture.v1.json"
                    container = directory / "process/container-custody/original_container_custody.v1.json"
                    original = write(directory / "original.json", payload_with_sha256_v1({
                        "schema_version": 1, "artifact_kind": "vast_original_native_operation_input_v1",
                        "operation": {"fixture_only": True, "operation_id": operation_id, "system": system},
                        "container_image": image, "outputs": {"measurement_dir": str(directory / "measurement"),
                            "native_domain": str(native), "process_receipt": str(process), "container_receipt": str(container)}}))
                    payload = canonical_json_v1({"fixture_only": True, "operation_id": operation_id,
                        "no_native_content_acceptance": True}) + b"\n"
                    result = capture_original_fixture_operation_v1(project_root=root,
                        operation_id=operation_id, original_operation_descriptor=original,
                        native_context_descriptor=context, expected_container_image=image,
                        native_domain_payload=payload, engine=held.engine, engine_socket=held.engine_socket,
                        scratch_dir=directory / "scratch", native_domain_output=native,
                        process_receipt_output=process, container_receipt_output=container)
                    self.assertEqual(native.read_bytes(), payload)
                    self.assertEqual(result["native_domain_descriptor"]["sha256"], hashlib.sha256(payload).hexdigest())
                    self.assertEqual(result["process_validation"]["receipt"]["operation_id"], operation_id)
                    self.assertTrue(result["container_validation"]["container_quiescence_verified"])
                    self.assertEqual(result["container_validation"]["container_id"], "a" * 64)
                    self.assertIsNone(result["container_validation"]["container_state"])
                    receipt = json.loads(container.read_bytes())
                    self.assertEqual(receipt["container_image"], image)
                    self.assertEqual(len(receipt["commands"]), 4)
                    measured = result["process_validation"]["measurement"]["launch"]["engine"]
                    observed_engines.append({key: measured[key] for key in ("path", "size_bytes", "sha256")})
                    self.assertFalse(result["real_docker_qualification"])
                self.assertEqual(observed_engines, [engine_descriptor, engine_descriptor])
                self.assertFalse(held.state_path.exists())


if __name__ == "__main__":
    unittest.main()
