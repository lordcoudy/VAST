from __future__ import annotations

import copy
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

import checkpoint_model_parity_acceptance as target  # noqa: E402


BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
EVIDENCE_NAMES = (
    "cpu_execution_probe", "cuda_execution_probe", "calibration_corpus",
    "evaluation_corpus", "cpu_policy_calibration", "cuda_policy_calibration",
    "cpu_raw_output_bundle", "cuda_raw_output_bundle",
)


def canonical_sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def identified(value: dict[str, object]) -> dict[str, object]:
    result = copy.deepcopy(value)
    result["identity"] = {
        "schema_version": 2,
        "algorithm": "sha256",
        "canonicalization": "sorted_compact_json_utf8_v2",
        "sha256": canonical_sha(result),
    }
    return result


def image_id(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        (self.root / "configs").mkdir(parents=True)
        (self.root / "evidence/model_parity/v3").mkdir(parents=True)
        (self.root / "accepted").mkdir(parents=True)
        self.manifest_path = self.root / "configs/checkpoint_analytics_model_parity.accepted.yaml"
        self.assessment_path = self.root / "accepted/model_parity_assessment.json"
        self.receipt_path = self.root / "accepted/model_parity_acceptance_receipt.json"
        self.evidence_paths: dict[tuple[str, str], Path] = {}
        for branch in BRANCHES:
            for name in EVIDENCE_NAMES:
                path = self.root / f"evidence/model_parity/v3/{branch}/{name}.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"branch": branch, "kind": name}, sort_keys=True) + "\n")
                self.evidence_paths[(branch, name)] = path
        self.manifest_path.write_text("schema_version: 3\nfixture: accepted\n")
        self.manifest = self.build_manifest()

    def build_manifest(self) -> dict[str, object]:
        slots = {}
        for branch in BRANCHES:
            slots[branch] = {"evidence": {
                name: {
                    "path": self.evidence_paths[(branch, name)].relative_to(self.root).as_posix(),
                    "sha256": hashlib.sha256(self.evidence_paths[(branch, name)].read_bytes()).hexdigest(),
                }
                for name in EVIDENCE_NAMES
            }}
        base = {
            "schema_version": 3,
            "artifact_kind": "checkpoint_analytics_model_parity_manifest",
            "manifest_id": "physical-accepted-model-parity-v3",
            "matrix_binding": {
                "cpu": {"image": "vast/openvino:accepted", "image_id": image_id("cpu-base")},
                "gpu": {"image": "vast/tensorrt:accepted", "image_id": image_id("gpu-base")},
            },
            "toolchain_registry": {
                "openvino_cpu": {"image": "vast/openvino:accepted", "image_id": image_id("cpu-base")},
                "tensorrt_cuda": {"image": "vast/tensorrt:accepted", "image_id": image_id("gpu-base")},
            },
            "worker_runtime_registry": {
                "openvino_cpu": {"image": "vast/ov-worker:accepted", "image_id": image_id("cpu-worker"), "base_image_id": image_id("cpu-base"), "worker_implementation_sha256": hashlib.sha256(b"cpu-worker").hexdigest()},
                "tensorrt_cuda": {"image": "vast/trt-worker:accepted", "image_id": image_id("gpu-worker"), "base_image_id": image_id("gpu-base"), "worker_implementation_sha256": hashlib.sha256(b"gpu-worker").hexdigest()},
            },
            "workload_slots": slots,
        }
        return identified(base)

    def assessment(self) -> dict[str, object]:
        value = {
            "schema_version": 3,
            "artifact_kind": "checkpoint_analytics_model_parity_assessment",
            "manifest_identity_sha256": self.manifest["identity"]["sha256"],
            "claim_scope": "cpu_openvino_vs_nvidia_cuda_tensorrt",
            "semantic_claim": "topology_load_proxy_only",
            "publication_ready": True,
            "openvino_gpu_counted_as_nvidia_cuda": False,
            "network_or_download_performed": False,
            "permitted_external_command": "docker image inspect only",
            "claimed_aggregate_metrics_accepted": False,
            "raw_per_sample_outputs_recomputed": True,
            "runtime_images": {
                resource: {
                    "reference": self.manifest["matrix_binding"][resource]["image"],
                    "image_id": self.manifest["matrix_binding"][resource]["image_id"],
                    "repo_digests": [self.manifest["matrix_binding"][resource]["image"] + "@" + self.manifest["matrix_binding"][resource]["image_id"]],
                    "architecture": "amd64", "os": "linux",
                }
                for resource in ("cpu", "gpu")
            },
            "local_model_inventory": {".onnx": 4, ".xml": 4, ".bin": 4, ".engine": 4, ".plan": 0},
            "branches": {branch: {"ready": True, "blockers": []} for branch in BRANCHES},
            "blockers": [],
        }
        return identified(value)

    def patches(self, assessment: dict[str, object] | None = None):
        return (
            mock.patch.object(target, "_load_parity_manifest", side_effect=lambda _path: copy.deepcopy(self.manifest)),
            mock.patch.object(target, "_assess_model_parity", side_effect=lambda _path, _root: copy.deepcopy(assessment if assessment is not None else self.assessment())),
        )

    def promote(self, assessment: dict[str, object] | None = None):
        loader, assessor = self.patches(assessment)
        with loader, assessor:
            return target.promote_model_parity_acceptance(
                project_root=self.root,
                accepted_manifest_path=self.manifest_path,
                accepted_assessment_path=self.assessment_path,
                acceptance_receipt_path=self.receipt_path,
            )

    def load(self):
        loader, assessor = self.patches()
        with loader, assessor:
            return target.load_verified_model_parity_acceptance(project_root=self.root, receipt_path=self.receipt_path)


class ModelParityAcceptanceTests(unittest.TestCase):
    def fixture(self):
        temporary = tempfile.TemporaryDirectory()
        return temporary, Fixture(Path(temporary.name))

    def test_physical_accepted_fixture_promotes_and_revalidates(self) -> None:
        temporary, fixture = self.fixture()
        with temporary:
            result = fixture.promote()
            self.assertEqual(result["evidence_count"], 32)
            self.assertEqual(len(result["files"]), 35)
            self.assertEqual(
                len(
                    [
                        item
                        for item in result["files"]
                        if item["path"].startswith("evidence/model_parity/v3/")
                    ]
                ),
                32,
            )
            self.assertEqual(fixture.load()["binding_sha256"], result["binding_sha256"])

    def test_null_evidence_reference_cannot_authorize(self) -> None:
        temporary, fixture = self.fixture()
        with temporary:
            fixture.manifest["workload_slots"]["damage"]["evidence"]["cuda_raw_output_bundle"]["sha256"] = None
            loader, assessor = fixture.patches()
            with loader, assessor, self.assertRaisesRegex(target.ModelParityAcceptanceError, "identity|non-null|SHA-256"):
                target.promote_model_parity_acceptance(project_root=fixture.root, accepted_manifest_path=fixture.manifest_path, accepted_assessment_path=fixture.assessment_path, acceptance_receipt_path=fixture.receipt_path)
            self.assertFalse(fixture.receipt_path.exists())

    def test_fake_ready_or_assessor_identity_drift_is_rejected(self) -> None:
        temporary, fixture = self.fixture()
        with temporary:
            fake = fixture.assessment()
            fake["raw_per_sample_outputs_recomputed"] = False
            with self.assertRaisesRegex(target.ModelParityAcceptanceError, "identity|raw per-sample"):
                fixture.promote(fake)
            with self.assertRaises(target.ModelParityAcceptanceError):
                fixture.promote({"publication_ready": True, "blockers": []})

    def test_receipt_and_assessment_are_self_hashed(self) -> None:
        temporary, fixture = self.fixture()
        with temporary:
            fixture.promote()
            for path, field in ((fixture.receipt_path, "receipt_sha256"), (fixture.assessment_path, "assessment_sha256")):
                value = json.loads(path.read_text())
                self.assertEqual(value[field], canonical_sha({key: item for key, item in value.items() if key != field}))

    def test_manifest_assessment_evidence_tamper_and_descriptor_swap_fail(self) -> None:
        for mode in ("manifest", "assessment", "evidence", "swap"):
            with self.subTest(mode=mode):
                temporary, fixture = self.fixture()
                with temporary:
                    fixture.promote()
                    if mode == "manifest":
                        fixture.manifest_path.write_bytes(fixture.manifest_path.read_bytes() + b"tamper\n")
                    elif mode == "assessment":
                        fixture.assessment_path.chmod(0o600)
                        fixture.assessment_path.write_bytes(fixture.assessment_path.read_bytes() + b" ")
                    elif mode == "evidence":
                        path = fixture.evidence_paths[("plate_number", "cpu_execution_probe")]
                        path.write_bytes(path.read_bytes() + b"tamper")
                    else:
                        fixture.receipt_path.chmod(0o600)
                        receipt = json.loads(fixture.receipt_path.read_text())
                        receipt["evidence"][0], receipt["evidence"][1] = receipt["evidence"][1], receipt["evidence"][0]
                        receipt["receipt_sha256"] = canonical_sha({key: item for key, item in receipt.items() if key != "receipt_sha256"})
                        fixture.receipt_path.write_text(json.dumps(receipt, sort_keys=True))
                    with self.assertRaises(target.ModelParityAcceptanceError):
                        fixture.load()

    def test_hardlink_and_symlink_evidence_are_rejected(self) -> None:
        temporary, fixture = self.fixture()
        with temporary:
            first = fixture.evidence_paths[("plate_number", "cpu_execution_probe")]
            second = fixture.evidence_paths[("plate_number", "cuda_execution_probe")]
            second.unlink()
            os.link(first, second)
            fixture.manifest = fixture.build_manifest()
            with self.assertRaisesRegex(target.ModelParityAcceptanceError, "hardlink|alias"):
                fixture.promote()

        temporary, fixture = self.fixture()
        with temporary:
            first = fixture.evidence_paths[("plate_number", "cpu_execution_probe")]
            second = fixture.evidence_paths[("plate_number", "cuda_execution_probe")]
            second.unlink()
            try:
                second.symlink_to(first)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable")
            fixture.manifest = fixture.build_manifest()
            with self.assertRaisesRegex(target.ModelParityAcceptanceError, "symlink|reparse|alias"):
                fixture.promote()

    def test_second_load_detects_drift_after_first_verified_load(self) -> None:
        temporary, fixture = self.fixture()
        with temporary:
            fixture.promote()
            fixture.load()
            path = fixture.evidence_paths[("foreign_object", "cuda_raw_output_bundle")]
            path.write_bytes(path.read_bytes() + b"post-load-drift")
            with self.assertRaises(target.ModelParityAcceptanceError):
                fixture.load()


if __name__ == "__main__":
    unittest.main()
