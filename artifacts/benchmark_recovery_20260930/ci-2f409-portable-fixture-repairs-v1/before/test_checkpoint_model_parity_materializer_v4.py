from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from analytics_execution_protocol import ENGINE_OPENVINO_CPU, ENGINE_TENSORRT_CUDA, PROTOCOL_IDENTITY_SHA256
import checkpoint_model_parity as parity_v3
import checkpoint_model_parity_v4 as parity_v4
from checkpoint_gstreamer_analytics_sidecar import load_execution_config
import publication_qualification_image_refreeze_v1 as image_refreeze

from tests.test_checkpoint_model_parity_v4 import _descriptor, _patch, _sha


def _probe(resource: str, implementation: str) -> dict[str, object]:
    cpu = resource == "cpu"
    return {
        "schema_version": 1,
        "artifact_kind": "vast_analytics_execution_worker_runtime_probe",
        "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
        "engine": ENGINE_OPENVINO_CPU if cpu else ENGINE_TENSORRT_CUDA,
        "runtime_name": "OpenVINO" if cpu else "TensorRT",
        "runtime_version": "test-physical-v1",
        "device_api": "CPU" if cpu else "NVIDIA_CUDA",
        "device_id": "Intel test CPU" if cpu else "GPU-00bb784b-60f3-8bf6-bbd3-5a0c09805266",
        "native_inference_api": "openvino.CompiledModel.__call__" if cpu else "nvinfer1::IExecutionContext::enqueueV3",
        "execution_path": "openvino_cpu_native" if cpu else "tensorrt_cuda_native",
        "worker_implementation_sha256": implementation,
        "socket_seqpacket": True,
        "scm_rights": True,
        "memfd_sealing": True,
        "model_loaded": False,
        "inference_performed": False,
    }


class MaterializerV4FoundationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = __import__("checkpoint_model_parity_materializer_v4")
        cls.source_manifest_path = ROOT / "configs" / "checkpoint_analytics_model_parity.yaml"
        cls.source_manifest = parity_v3.load_parity_manifest(cls.source_manifest_path)
        cls.source_config_path = ROOT / "configs" / "analytics_execution_layer.yaml"
        cls.source_config = load_execution_config(cls.source_config_path)

    def _patch_projection(self) -> tuple[dict[str, object], dict[str, object]]:
        patch = _patch()
        for resource, runtime_key in (("cpu", "openvino_cpu"), ("gpu", "tensorrt_cuda")):
            runtime = self.source_manifest["worker_runtime_registry"][runtime_key]
            row = patch["workers"][resource]
            row["target_reference"] = runtime["image"]
            row["base_reference"] = runtime["base_image"]
            row["base_image_id"] = runtime["base_image_id"]
            row["previous_accepted_image_id"] = runtime["image_id"]
            row["entrypoint"] = [self.source_config["workers"][resource]["entrypoint"]]
        patch["patch_sha256"] = image_refreeze.self_sha256(patch, "patch_sha256")
        return patch, parity_v4.validate_refresh_patch_v4(patch)

    def test_live_probes_precede_and_bind_versioned_config(self) -> None:
        patch, projection = self._patch_projection()
        implementations = {"cpu": _sha("cpu-v4"), "gpu": _sha("gpu-v4")}

        def runner(command: list[str]) -> str:
            image = next(worker["image"] for worker in projection["workers"].values() if worker["image"] in command)
            resource = "cpu" if image == projection["workers"]["cpu"]["image"] else "gpu"
            if command[1:3] == ["image", "inspect"]:
                return json.dumps([{"Id": projection["workers"][resource]["image_id"], "Architecture": "amd64", "Os": "linux"}])
            self.assertIn("--capability", command)
            return json.dumps(_probe(resource, implementations[resource]))

        with tempfile.TemporaryDirectory(prefix="model-parity-v4-test-", dir=ROOT / "staging") as temporary:
            work = Path(temporary)
            probe_authority = self.module.capture_live_runtime_probes_v4(
                project_root=ROOT,
                patch_projection=projection,
                source_execution_config=self.source_config,
                output_dir=work / "probes",
                command_runner=runner,
            )
            config, authority = self.module.build_versioned_execution_config_v4(
                project_root=ROOT,
                source_execution_config=self.source_config,
                patch_projection=projection,
                runtime_probes=probe_authority,
                model_parity_manifest_path=work / "model-parity-v4.yaml",
                output_path=work / "execution-v4.json",
            )
            self.assertEqual(config["workers"]["cpu"]["image_id"], projection["workers"]["cpu"]["image_id"])
            self.assertEqual(config["workers"]["gpu"]["worker_implementation_sha256"], implementations["gpu"])
            self.assertEqual(authority["content_identity_sha256"], config["identity"]["sha256"])
            loaded = load_execution_config(work / "execution-v4.json")
            self.assertEqual(loaded, config)

    def test_live_probe_adoption_rebind_before_cleanup_preserves_final(self) -> None:
        _patch_value, projection = self._patch_projection()
        implementations = {"cpu": _sha("cpu-v4"), "gpu": _sha("gpu-v4")}

        def runner(command: list[str]) -> str:
            image = next(
                worker["image"]
                for worker in projection["workers"].values()
                if worker["image"] in command
            )
            resource = (
                "cpu"
                if image == projection["workers"]["cpu"]["image"]
                else "gpu"
            )
            if command[1:3] == ["image", "inspect"]:
                return json.dumps(
                    [
                        {
                            "Id": projection["workers"][resource]["image_id"],
                            "Architecture": "amd64",
                            "Os": "linux",
                        }
                    ]
                )
            return json.dumps(_probe(resource, implementations[resource]))

        with tempfile.TemporaryDirectory(
            prefix="model-parity-v4-rebind-", dir=ROOT / "staging"
        ) as temporary:
            output = Path(temporary) / "probes"
            expected = self.module.capture_live_runtime_probes_v4(
                project_root=ROOT,
                patch_projection=projection,
                source_execution_config=self.source_config,
                output_dir=output,
                command_runner=runner,
            )
            final_identity = output.stat().st_dev, output.stat().st_ino
            final_payloads = {
                path.name: path.read_bytes() for path in output.iterdir()
            }
            real_commit = self.module.commit_or_adopt_immutable_directory_v1
            rebound: list[tuple[Path, Path]] = []

            def adopt_then_rebind(**kwargs):
                result = real_commit(**kwargs)
                staging = Path(kwargs["staging"])
                stolen = staging.with_name(staging.name + ".stolen")
                os.replace(staging, stolen)
                staging.mkdir()
                (staging / "FOREIGN").write_text("foreign\n", encoding="utf-8")
                rebound.append((staging, stolen))
                return result

            with (
                mock.patch.object(
                    self.module,
                    "commit_or_adopt_immutable_directory_v1",
                    side_effect=adopt_then_rebind,
                ),
                self.assertRaisesRegex(
                    self.module.ModelParityMaterializerV4Error,
                    "mutated|rebound|changed",
                ),
            ):
                self.module.capture_live_runtime_probes_v4(
                    project_root=ROOT,
                    patch_projection=projection,
                    source_execution_config=self.source_config,
                    output_dir=output,
                    command_runner=runner,
                )

            self.assertEqual(len(rebound), 1)
            foreign, stolen = rebound[0]
            self.assertEqual((output.stat().st_dev, output.stat().st_ino), final_identity)
            self.assertEqual(
                {path.name: path.read_bytes() for path in output.iterdir()},
                final_payloads,
            )
            self.assertEqual(
                self.module.capture_live_runtime_probes_v4(
                    project_root=ROOT,
                    patch_projection=projection,
                    source_execution_config=self.source_config,
                    output_dir=output,
                    command_runner=runner,
                ),
                expected,
            )
            self.assertEqual((foreign / "FOREIGN").read_text(), "foreign\n")
            self.assertTrue(stolen.is_dir())

    def test_wrong_live_image_id_fails_before_probe_commit(self) -> None:
        _patch_value, projection = self._patch_projection()

        def runner(command: list[str]) -> str:
            if command[1:3] == ["image", "inspect"]:
                return json.dumps([{"Id": "sha256:" + "e" * 64, "Architecture": "amd64", "Os": "linux"}])
            self.fail("capability probe must not run after image identity mismatch")

        with tempfile.TemporaryDirectory(prefix="model-parity-v4-test-", dir=ROOT / "staging") as temporary:
            output = Path(temporary) / "probes"
            with self.assertRaisesRegex(self.module.ModelParityMaterializerV4Error, "image identity"):
                self.module.capture_live_runtime_probes_v4(
                    project_root=ROOT,
                    patch_projection=projection,
                    source_execution_config=self.source_config,
                    output_dir=output,
                    command_runner=runner,
                )
            self.assertFalse(output.exists())

    def test_v4_candidate_rebind_before_cleanup_preserves_final_and_foreign(self) -> None:
        v3 = self.module.materializer_v3
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "configs").mkdir()
            materialization = root / "evidence" / "model_parity" / "run"
            materialization.mkdir(parents=True)
            base = root / "configs" / "base.yaml"
            base.write_bytes(b"base\n")
            base_record = v3.verify_physical_file(
                root,
                "configs/base.yaml",
                expected_sha256=hashlib.sha256(b"base\n").hexdigest(),
                label="base",
            )
            promoted = {"schema_version": 4, "artifact_kind": "fixture"}
            collection = v3.ProductionCollection(
                v3._PRODUCTION_TOKEN,
                project_root=root,
                materialization_dir=materialization,
                base_manifest_record=base_record,
                base_manifest={},
                evidence_refs={},
                promoted_manifest=promoted,
            )
            accepted = root / "configs" / "accepted-v4.yaml"
            candidate = accepted.parent / f".{accepted.name}.candidate.{os.getpid()}"
            stolen = candidate.with_name(candidate.name + ".stolen")

            def rebind_candidate(step: str) -> None:
                if step != "post_publish_pre_parent_fsync":
                    return
                os.replace(candidate, stolen)
                candidate.write_bytes(b"foreign\n")

            with (
                mock.patch.object(v3, "_verify_collection_final_paths"),
                mock.patch.object(
                    self.module.parity_v4,
                    "load_parity_manifest_v4",
                    return_value={**promoted, "identity": {"sha256": "0" * 64}},
                ),
                mock.patch.object(
                    self.module.parity_v4,
                    "assess_model_parity_v4",
                    return_value={"publication_ready": True, "blockers": []},
                ),
                self.assertRaisesRegex(
                    self.module.ModelParityMaterializerV4Error,
                    "mutated|rebound|changed",
                ),
            ):
                self.module.promote_model_parity_evidence_v4(
                    collection,
                    accepted_manifest_path=accepted,
                    after_manifest_publish_step=rebind_candidate,
                )

            self.assertTrue(accepted.is_file())
            final_identity = accepted.stat().st_dev, accepted.stat().st_ino
            self.assertEqual(candidate.read_bytes(), b"foreign\n")
            self.assertTrue(stolen.is_file())
            self.assertNotEqual(
                (candidate.stat().st_dev, candidate.stat().st_ino), final_identity
            )
            self.assertNotEqual(
                (stolen.stat().st_dev, stolen.stat().st_ino), final_identity
            )

    def test_binding_authority_rejects_wrong_worker_image(self) -> None:
        _patch_value, projection = self._patch_projection()
        with self.assertRaisesRegex(self.module.ModelParityMaterializerV4Error, "worker image"):
            self.module.validate_resolved_worker_projection_v4(
                patch_projection=projection,
                execution_config={
                    "workers": {
                        "cpu": {"image": projection["workers"]["cpu"]["image"], "image_id": "sha256:" + "f" * 64, "worker_implementation_sha256": _sha("cpu")},
                        "gpu": {"image": projection["workers"]["gpu"]["image"], "image_id": projection["workers"]["gpu"]["image_id"], "worker_implementation_sha256": _sha("gpu")},
                    }
                },
                runtime_probes={
                    "cpu": {"worker_implementation_sha256": _sha("cpu")},
                    "gpu": {"worker_implementation_sha256": _sha("gpu")},
                },
            )

    def test_versioned_leaf_adopts_all_three_atomic_crash_windows(self) -> None:
        payload = b"{\"versioned\":true}\n"
        for step in (
            "mid_write",
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        ):
            with self.subTest(step=step), tempfile.TemporaryDirectory(
                prefix="model-parity-v4-leaf-", dir=ROOT / "staging"
            ) as temporary:
                root = Path(temporary).resolve()
                output = root / "versioned.json"

                def crash(observed: str) -> None:
                    if observed == step:
                        raise RuntimeError("injected physical crash")

                with self.assertRaisesRegex(RuntimeError, "injected physical crash"):
                    self.module._write_new_bytes(
                        root,
                        output,
                        payload,
                        "versioned leaf",
                        _fault_hook=crash,
                    )
                expected = self.module._write_new_bytes(
                    root, output, payload, "versioned leaf"
                )
                identity = output.stat().st_dev, output.stat().st_ino
                self.assertEqual(
                    self.module._write_new_bytes(
                        root, output, payload, "versioned leaf"
                    ),
                    expected,
                )
                self.assertEqual((output.stat().st_dev, output.stat().st_ino), identity)


if __name__ == "__main__":
    unittest.main()
