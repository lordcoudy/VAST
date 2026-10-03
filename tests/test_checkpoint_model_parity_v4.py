from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import checkpoint_model_parity as parity_v3
import publication_qualification_image_refreeze_v1 as image_refreeze
from analytics_execution_protocol import canonical_sha256
from checkpoint_gstreamer_analytics_sidecar import load_execution_config


def _sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    ).hexdigest()


def _descriptor(path: str, marker: str) -> dict[str, object]:
    return {"path": path, "size_bytes": 1, "sha256": _sha(marker)}


def _worker(name: str, image: str, image_id: str, base_id: str) -> dict[str, object]:
    return {
        "name": name,
        "group": "analytics_worker",
        "target_reference": image,
        "image_id": image_id,
        "repo_digests": [],
        "image_inspect_sha256": _sha(name + ":inspect"),
        "base_reference": "vast/base:fixed",
        "base_image_id": base_id,
        "source_set_sha256": _sha(name + ":source"),
        "dependency_set_sha256": _sha(name + ":dependency"),
        "build_context_sha256": _sha(name + ":context"),
        "source_date_epoch": 0,
        "entrypoint": ["/opt/vast/worker"],
        "user": "worker",
        "labels": {},
        "previous_accepted_image_id": "sha256:" + "1" * 64,
        "identity_changed": True,
    }


def _patch() -> dict[str, object]:
    cpu_id = "sha256:" + "a" * 64
    gpu_id = "sha256:" + "b" * 64
    value: dict[str, object] = {
        "schema_version": 1,
        "artifact_kind": image_refreeze.PATCH_KIND,
        "authority": "derived_physical_evidence_only",
        "build_registry": {**_descriptor("configs/build.json", "build"), "registry_sha256": _sha("br")},
        "refreeze_registry": {**_descriptor("configs/refreeze.json", "refreeze"), "registry_sha256": _sha("rr")},
        "receipts": {
            "native_probe": {**_descriptor("receipts/native.json", "native"), "receipt_sha256": _sha("nr")},
            "analytics_worker": {**_descriptor("receipts/workers.json", "workers"), "receipt_sha256": _sha("wr")},
            "runtime_images": {
                system: {**_descriptor(f"receipts/{system}.json", system), "receipt_sha256": _sha(system + ":receipt")}
                for system in image_refreeze.SYSTEMS
            },
        },
        "workers": {
            "cpu": _worker("analytics_worker_openvino", "vast/analytics-openvino-worker:publication-v3", cpu_id, "sha256:" + "c" * 64),
            "gpu": _worker("analytics_worker_tensorrt", "vast/analytics-tensorrt-worker:publication-v3", gpu_id, "sha256:" + "d" * 64),
        },
        "systems": {
            system: {"fragment_identity": _sha(system + ":fragment"), "physical_identity": _sha(system + ":physical")}
            for system in image_refreeze.SYSTEMS
        },
        "candidate_binding_requirements": {
            "patch_supersedes_acceptance": False,
            "requires_bootstrap_descriptor_binding": True,
            "requires_candidate_resource_binding_equality": True,
            "requires_live_docker_inspect_equality": True,
        },
        "candidate_binding_eligible": False,
        "blockers": [
            "analytics_worker:cpu_identity_changed_requires_parity_refresh",
            "analytics_worker:gpu_identity_changed_requires_parity_refresh",
        ],
    }
    value["patch_sha256"] = image_refreeze.self_sha256(value, "patch_sha256")
    return value


class ModelParityV4Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = __import__("checkpoint_model_parity_v4")
        cls.source_path = ROOT / "configs" / "checkpoint_analytics_model_parity.yaml"
        cls.source = parity_v3.load_parity_manifest(cls.source_path)
        cls.source_descriptor = {
            "path": cls.source_path.relative_to(ROOT).as_posix(),
            "size_bytes": cls.source_path.stat().st_size,
            "sha256": hashlib.sha256(cls.source_path.read_bytes()).hexdigest(),
        }

    def _authority(self) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        patch = _patch()
        for resource, runtime_key in (("cpu", "openvino_cpu"), ("gpu", "tensorrt_cuda")):
            runtime = self.source["worker_runtime_registry"][runtime_key]
            patch["workers"][resource]["target_reference"] = runtime["image"]
            patch["workers"][resource]["base_reference"] = runtime["base_image"]
            patch["workers"][resource]["base_image_id"] = runtime["base_image_id"]
            patch["workers"][resource]["previous_accepted_image_id"] = runtime["image_id"]
        patch["patch_sha256"] = image_refreeze.self_sha256(patch, "patch_sha256")
        config = {
            **_descriptor("artifacts/model_parity/v4/execution.json", "execution"),
            "content_identity_sha256": _sha("execution-content"),
            "worker_projection_sha256": _sha("workers-projection"),
        }
        probes = {
            "cpu": {
                **_descriptor("artifacts/model_parity/v4/cpu-probe.json", "cpu-probe"),
                "worker_implementation_sha256": _sha("cpu-implementation"),
            },
            "gpu": {
                **_descriptor("artifacts/model_parity/v4/gpu-probe.json", "gpu-probe"),
                "worker_implementation_sha256": _sha("gpu-implementation"),
            },
        }
        return patch, config, probes

    def test_builds_exact_patch_bound_dynamic_manifest(self) -> None:
        patch, config, probes = self._authority()
        result = self.module.build_patch_bound_manifest_v4(
            source_manifest=self.source,
            source_manifest_descriptor=self.source_descriptor,
            image_patch=patch,
            image_patch_descriptor=_descriptor("artifacts/refreeze/image-patch.json", "patch"),
            execution_config=config,
            runtime_probes=probes,
        )
        self.assertEqual(result["schema_version"], 4)
        self.assertEqual(result["artifact_kind"], self.module.MANIFEST_KIND)
        self.assertEqual(result["refresh_authority"]["image_identity_patch"]["patch_sha256"], patch["patch_sha256"])
        self.assertEqual(result["worker_runtime_registry"]["openvino_cpu"]["image_id"], patch["workers"]["cpu"]["image_id"])
        self.assertEqual(result["worker_runtime_registry"]["tensorrt_cuda"]["worker_implementation_sha256"], probes["gpu"]["worker_implementation_sha256"])
        self.module.validate_manifest_v4(result)

    def test_rejects_any_refresh_blocker_set_drift(self) -> None:
        patch, config, probes = self._authority()
        patch["blockers"] = [patch["blockers"][0]]
        patch["patch_sha256"] = image_refreeze.self_sha256(patch, "patch_sha256")
        with self.assertRaisesRegex(self.module.ModelParityV4Error, "exact two"):
            self.module.build_patch_bound_manifest_v4(
                source_manifest=self.source,
                source_manifest_descriptor=self.source_descriptor,
                image_patch=patch,
                image_patch_descriptor=_descriptor("artifacts/refreeze/image-patch.json", "patch"),
                execution_config=config,
                runtime_probes=probes,
            )

    def test_rejects_stale_patch_self_identity(self) -> None:
        patch, config, probes = self._authority()
        patch["patch_sha256"] = "0" * 64
        with self.assertRaisesRegex(self.module.ModelParityV4Error, "self-identity"):
            self.module.build_patch_bound_manifest_v4(
                source_manifest=self.source,
                source_manifest_descriptor=self.source_descriptor,
                image_patch=patch,
                image_patch_descriptor=_descriptor("artifacts/refreeze/image-patch.json", "patch"),
                execution_config=config,
                runtime_probes=probes,
            )

    def test_rejects_wrong_worker_identity_or_unchanged_image(self) -> None:
        patch, config, probes = self._authority()
        patch["workers"]["cpu"]["name"] = "analytics_worker_tensorrt"
        patch["patch_sha256"] = image_refreeze.self_sha256(patch, "patch_sha256")
        with self.assertRaisesRegex(self.module.ModelParityV4Error, "worker coordinate"):
            self.module.build_patch_bound_manifest_v4(
                source_manifest=self.source,
                source_manifest_descriptor=self.source_descriptor,
                image_patch=patch,
                image_patch_descriptor=_descriptor("artifacts/refreeze/image-patch.json", "patch"),
                execution_config=config,
                runtime_probes=probes,
            )

    def test_refrozen_base_id_is_allowed_but_base_coordinate_is_frozen(self) -> None:
        patch, config, probes = self._authority()
        patch["workers"]["cpu"]["base_image_id"] = "sha256:" + "9" * 64
        patch["patch_sha256"] = image_refreeze.self_sha256(
            patch, "patch_sha256"
        )
        result = self.module.build_patch_bound_manifest_v4(
            source_manifest=self.source,
            source_manifest_descriptor=self.source_descriptor,
            image_patch=patch,
            image_patch_descriptor=_descriptor(
                "artifacts/refreeze/image-patch.json", "patch"
            ),
            execution_config=config,
            runtime_probes=probes,
        )
        self.assertEqual(
            result["matrix_binding"]["cpu"]["image_id"],
            patch["workers"]["cpu"]["base_image_id"],
        )

        drifted_patch = copy.deepcopy(patch)
        drifted_patch["workers"]["cpu"]["base_reference"] = (
            "vast/other-openvino-native-probe:forbidden"
        )
        drifted_patch["patch_sha256"] = image_refreeze.self_sha256(
            drifted_patch, "patch_sha256"
        )
        with self.assertRaisesRegex(
            self.module.ModelParityV4Error, "changed more"
        ):
            self.module.build_patch_bound_manifest_v4(
                source_manifest=self.source,
                source_manifest_descriptor=self.source_descriptor,
                image_patch=drifted_patch,
                image_patch_descriptor=_descriptor(
                    "artifacts/refreeze/image-patch.json", "patch"
                ),
                execution_config=config,
                runtime_probes=probes,
            )

        tampered_manifest = copy.deepcopy(result)
        tampered_manifest["matrix_binding"]["cpu"]["image_id"] = (
            "sha256:" + "8" * 64
        )
        tampered_manifest = self.module._with_identity(tampered_manifest)
        with self.assertRaisesRegex(
            self.module.ModelParityV4Error, "producer matrix/toolchain"
        ):
            self.module.validate_manifest_v4(tampered_manifest)

    def test_manifest_identity_detects_output_drift(self) -> None:
        patch, config, probes = self._authority()
        result = self.module.build_patch_bound_manifest_v4(
            source_manifest=self.source,
            source_manifest_descriptor=self.source_descriptor,
            image_patch=patch,
            image_patch_descriptor=_descriptor("artifacts/refreeze/image-patch.json", "patch"),
            execution_config=config,
            runtime_probes=probes,
        )
        tampered = copy.deepcopy(result)
        tampered["worker_runtime_registry"]["openvino_cpu"]["image_id"] = "sha256:" + "f" * 64
        with self.assertRaisesRegex(self.module.ModelParityV4Error, "identity"):
            self.module.validate_manifest_v4(tampered)

    def test_actual_attempt2_patch_allows_exact_refrozen_base_producers(self) -> None:
        patch_path = (
            ROOT
            / "artifacts/publication_image_build_v1_attempt2/"
            "qualification_image_identity_patch.v1.json"
        )
        config_path = ROOT / "configs/analytics_execution_layer.v4.json"
        probe_root = ROOT / "artifacts/model_parity_v4_refresh_20260825/runtime_probes"
        required_physical_inputs = [
            patch_path,
            config_path,
            probe_root / "cpu_runtime_probe.json",
            probe_root / "gpu_runtime_probe.json",
        ]
        if not all(path.is_file() for path in required_physical_inputs):
            self.skipTest("local physical attempt2 evidence is unavailable")
        patch = image_refreeze.load_identity_patch(
            project_root=ROOT,
            patch_path=patch_path,
            require_candidate_eligible=False,
        )
        config = load_execution_config(config_path)
        config_descriptor = {
            "path": config_path.relative_to(ROOT).as_posix(),
            "size_bytes": config_path.stat().st_size,
            "sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
            "content_identity_sha256": config["identity"]["sha256"],
            "worker_projection_sha256": canonical_sha256(config["workers"]),
        }
        probes: dict[str, dict[str, object]] = {}
        for resource in ("cpu", "gpu"):
            path = probe_root / f"{resource}_runtime_probe.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            probes[resource] = {
                "path": path.relative_to(ROOT).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "worker_implementation_sha256": document[
                    "worker_implementation_sha256"
                ],
            }
        result = self.module.build_patch_bound_manifest_v4(
            source_manifest=self.source,
            source_manifest_descriptor=self.source_descriptor,
            image_patch=patch,
            image_patch_descriptor={
                "path": patch_path.relative_to(ROOT).as_posix(),
                "size_bytes": patch_path.stat().st_size,
                "sha256": hashlib.sha256(patch_path.read_bytes()).hexdigest(),
            },
            execution_config=config_descriptor,
            runtime_probes=probes,
        )
        for resource, toolchain in (("cpu", "openvino_cpu"), ("gpu", "tensorrt_cuda")):
            expected = patch["workers"][resource]["base_image_id"]
            self.assertEqual(result["matrix_binding"][resource]["image_id"], expected)
            self.assertEqual(result["toolchain_registry"][toolchain]["image_id"], expected)
            self.assertEqual(
                result["worker_runtime_registry"][toolchain]["base_image_id"],
                expected,
            )


if __name__ == "__main__":
    unittest.main()
