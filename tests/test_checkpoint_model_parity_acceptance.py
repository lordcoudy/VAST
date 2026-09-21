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


class InjectedCrash(RuntimeError):
    pass


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
        self.evidence_root = self.root / "evidence/model_parity/v3"
        self.evidence_root.mkdir(parents=True)
        (self.root / "accepted").mkdir(parents=True)
        self.manifest_path = self.root / "configs/checkpoint_analytics_model_parity.accepted.yaml"
        self.assessment_path = self.root / "accepted/model_parity_assessment.json"
        self.receipt_path = self.root / "accepted/model_parity_acceptance_receipt.json"
        self.evidence_paths: dict[tuple[str, str], Path] = {}
        for branch in BRANCHES:
            for name in EVIDENCE_NAMES:
                path = self.evidence_root / f"documents/{branch}/{name}.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"branch": branch, "kind": name}, sort_keys=True) + "\n")
                self.evidence_paths[(branch, name)] = path
        self.transaction_path = self._write_transaction()
        self.manifest_path.write_text("schema_version: 3\nfixture: accepted\n")
        self.manifest = self.build_manifest()

    def _descriptor(self, path: Path) -> dict[str, object]:
        payload = path.read_bytes()
        return {
            "path": path.relative_to(self.root).as_posix(),
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }

    def _write_transaction(self) -> Path:
        files = [self._descriptor(path) for path in self.evidence_paths.values()]
        segments: list[dict[str, object]] = []
        bundles: list[dict[str, object]] = []
        for branch in BRANCHES:
            for resource in ("openvino_cpu", "tensorrt_cuda"):
                for index in range(60):
                    role = "calibration" if index < 30 else "evaluation"
                    codec = "h264" if index % 30 < 15 else "h265"
                    sample_id = f"mp.{branch}.{role}.{codec}.{index:02d}"
                    request_id = f"mp-v2-{branch}-{resource}-{index:02d}"
                    manifest_path = (
                        self.evidence_root
                        / "execution_bundles"
                        / request_id
                        / "manifest.json"
                    )
                    manifest_path.parent.mkdir(parents=True)
                    manifest_path.write_text(
                        json.dumps({"request_id": request_id}, sort_keys=True) + "\n"
                    )
                    manifest = self._descriptor(manifest_path)
                    files.append(manifest)
                    input_sha = hashlib.sha256(sample_id.encode()).hexdigest()
                    output_sha = hashlib.sha256(request_id.encode()).hexdigest()
                    segments.append(
                        {
                            "branch": branch,
                            "resource": resource,
                            "sample_id": sample_id,
                            "preprocessed_tensor_sha256": input_sha,
                        }
                    )
                    bundles.append(
                        {
                            "branch": branch,
                            "role": role,
                            "codec": codec,
                            "sample_id": sample_id,
                            "resource": resource,
                            "request_id": request_id,
                            "manifest": manifest,
                            "manifest_identity_sha256": hashlib.sha256(
                                (request_id + ":manifest").encode()
                            ).hexdigest(),
                            "request_sha256": hashlib.sha256(
                                (request_id + ":request").encode()
                            ).hexdigest(),
                            "response_sha256": hashlib.sha256(
                                (request_id + ":response").encode()
                            ).hexdigest(),
                            "input_tensor_sha256": input_sha,
                            "output_tensor_sha256": output_sha,
                        }
                    )
        files.sort(key=lambda item: str(item["path"]))
        transaction = {
            "schema_version": 2,
            "artifact_kind": "checkpoint_model_parity_materialization_transaction",
            "run_id": "v3",
            "final_materialization_path": "evidence/model_parity/v3",
            "document_count": 32,
            "files": files,
            "files_sha256": canonical_sha(files),
            "source_inventory": [],
            "source_inventory_sha256": canonical_sha([]),
            "output_segments": segments,
            "output_segments_sha256": canonical_sha(segments),
            "execution_bundle_count": 480,
            "execution_bundles": bundles,
            "execution_bundles_sha256": canonical_sha(bundles),
            "claimed_aggregates_accepted": False,
            "synthetic_or_mock_evidence_accepted": False,
        }
        transaction["transaction_sha256"] = canonical_sha(transaction)
        path = self.evidence_root / "transaction_index.json"
        path.write_text(json.dumps(transaction, sort_keys=True, separators=(",", ":")) + "\n")
        return path

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
            self.assertEqual(result["schema_version"], 2)
            self.assertEqual(result["evidence_count"], 32)
            self.assertEqual(len(result["files"]), 36)
            self.assertEqual(
                result["transaction_index"]["execution_bundle_count"], 480
            )
            self.assertEqual(
                len(
                    [
                        item
                        for item in result["files"]
                        if item["path"].startswith("evidence/model_parity/v3/")
                    ]
                ),
                33,
            )
            self.assertEqual(fixture.load()["binding_sha256"], result["binding_sha256"])

    def test_transaction_index_or_bundle_tamper_cannot_authorize(self) -> None:
        for mode in ("index", "bundle"):
            with self.subTest(mode=mode):
                temporary, fixture = self.fixture()
                with temporary:
                    if mode == "index":
                        transaction = json.loads(fixture.transaction_path.read_text())
                        transaction["execution_bundle_count"] = 479
                        transaction["transaction_sha256"] = canonical_sha(
                            {
                                key: value
                                for key, value in transaction.items()
                                if key != "transaction_sha256"
                            }
                        )
                        fixture.transaction_path.write_text(
                            json.dumps(transaction, sort_keys=True, separators=(",", ":"))
                            + "\n"
                        )
                    else:
                        bundle = next(
                            fixture.evidence_root.glob(
                                "execution_bundles/*/manifest.json"
                            )
                        )
                        bundle.write_bytes(bundle.read_bytes() + b"tamper\n")
                    with self.assertRaisesRegex(
                        target.ModelParityAcceptanceError,
                        "transaction|bundle|coverage|descriptor",
                    ):
                        fixture.promote()

    def test_existing_schema_v1_receipt_remains_read_only_loadable(self) -> None:
        temporary, fixture = self.fixture()
        with temporary:
            fixture.promote()
            assessment = json.loads(fixture.assessment_path.read_text())
            assessment.pop("transaction_index")
            assessment["schema_version"] = 1
            assessment["assessment_sha256"] = canonical_sha(
                {
                    key: value
                    for key, value in assessment.items()
                    if key != "assessment_sha256"
                }
            )
            fixture.assessment_path.chmod(0o600)
            fixture.assessment_path.write_text(
                json.dumps(assessment, sort_keys=True, separators=(",", ":")) + "\n"
            )
            receipt = json.loads(fixture.receipt_path.read_text())
            receipt.pop("transaction_index")
            receipt["schema_version"] = 1
            receipt["accepted_assessment"] = fixture._descriptor(
                fixture.assessment_path
            )
            receipt["accepted_assessment_identity_sha256"] = assessment[
                "assessment_sha256"
            ]
            receipt["receipt_sha256"] = canonical_sha(
                {
                    key: value
                    for key, value in receipt.items()
                    if key != "receipt_sha256"
                }
            )
            fixture.receipt_path.chmod(0o600)
            fixture.receipt_path.write_text(
                json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n"
            )

            legacy = fixture.load()
            self.assertEqual(legacy["schema_version"], 1)
            self.assertNotIn("transaction_index", legacy)

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


    def test_immutable_json_commit_adopts_all_three_crash_windows(self) -> None:
        document = {"schema_version": 1, "value": "durable"}
        for step in (
            "mid_write",
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        ):
            with self.subTest(step=step), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary).resolve() / "accepted.json"

                def crash(observed: str) -> None:
                    if observed == step:
                        raise InjectedCrash(step)

                with self.assertRaises(InjectedCrash):
                    target._write_new_json(
                        path, document, "atomic acceptance test", _fault_hook=crash
                    )
                expected = target._write_new_json(
                    path, document, "atomic acceptance test"
                )
                identity = (path.stat().st_dev, path.stat().st_ino)
                self.assertEqual(
                    target._write_new_json(path, document, "atomic acceptance test"),
                    expected,
                )
                self.assertEqual((path.stat().st_dev, path.stat().st_ino), identity)
                path.chmod(0o600)
                path.write_bytes(b"foreign\n")
                with self.assertRaisesRegex(Exception, "atomic commit/adoption"):
                    target._write_new_json(path, document, "atomic acceptance test")


if __name__ == "__main__":
    unittest.main()
