from __future__ import annotations

import copy
import hashlib
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import publication_policy_contract as policy  # noqa: E402
import publication_policy_qualification_bootstrap_v2 as target  # noqa: E402
from tests.test_publication_policy_contract import (  # noqa: E402
    valid_capability_manifest,
)


BRANCHES = tuple(policy.ANALYTICS_BRANCHES)
SYSTEMS = tuple(policy.PUBLISHABLE_SYSTEMS)
RESOURCE_DOCUMENTS = {
    "cpu": ("openvino_cpu", "cpu_policy_calibration"),
    "gpu": ("tensorrt_cuda", "cuda_policy_calibration"),
}


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value) + b"\n")


def descriptor(root: Path, path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


class BootstrapFixture:
    def __init__(
        self,
        root: Path,
        *,
        short_coordinate: tuple[str, str] | None = None,
        transaction_layout: bool = False,
    ):
        self.root = root
        candidate_root = root / ("inputs/candidate" if transaction_layout else "candidate")
        self.candidate_manifest_path = candidate_root / "capability.json"
        self.candidate_receipt_path = candidate_root / "receipt.json"
        self.accepted_manifest_path = root / "accepted/model-parity.yaml"
        self.accepted_assessment_path = root / "accepted/assessment.json"
        self.accepted_receipt_path = root / "accepted/receipt.json"
        self.output_dir = root / (
            "inputs/bootstrap-v2"
            if transaction_layout
            else "publication-store/bootstrap-v2"
        )
        self.output_dir.parent.mkdir(parents=True, exist_ok=True)
        self.response_paths: list[Path] = []
        self.calibration_paths: dict[tuple[str, str], Path] = {}

        self.candidate_manifest = valid_capability_manifest()
        write_json(self.candidate_manifest_path, self.candidate_manifest)
        qualification_index = root / "candidate/qualification-index.json"
        write_json(qualification_index, {"candidate": "physical-index-v2"})
        candidate_receipt = {
            "schema_version": 1,
            "artifact_kind": "vast_publication_policy_qualification_candidate_receipt",
            "status": "qualification_candidate_not_accepted",
            "accepted": False,
            "publication_ready": False,
            "scope": "forced_resource_qualification_pilots_only",
            "policy_contract_sha256": self.candidate_manifest[
                "policy_contract_sha256"
            ],
            "qualification_index": descriptor(root, qualification_index),
            "candidate_manifest": descriptor(root, self.candidate_manifest_path),
            "blockers": [
                "candidate_is_not_a_full_publication_authority",
                "requires_32_cell_native_pilot_validation_and_atomic_promotion",
            ],
        }
        candidate_receipt["sha256"] = canonical_sha(candidate_receipt)
        write_json(self.candidate_receipt_path, candidate_receipt)

        workload_slots: dict[str, object] = {}
        output_segments: list[dict[str, object]] = []
        transaction_files: list[dict[str, object]] = []
        execution_bundles: list[dict[str, object]] = []

        def add_bundle(
            *,
            branch: str,
            resource: str,
            native_resource: str,
            role: str,
            sample_index: int,
        ) -> tuple[str, str]:
            codec = "h264" if sample_index < 15 else "h265"
            codec_index = sample_index if sample_index < 15 else sample_index - 15
            sample_id = f"mp.{branch}.{role}.{codec}.{codec_index:02d}"
            request_id = f"request.{branch}.{resource}.{role}.{sample_index:02d}"
            bundle_dir = root / (
                "evidence/model_parity/v3/execution_bundles/" + request_id
            )
            input_payload = f"input:{request_id}".encode("ascii")
            output_payload = f"output:{request_id}".encode("ascii")
            tensor_sha = hashlib.sha256(input_payload).hexdigest()
            input_path = bundle_dir / "input.tensor.bin"
            output_path = bundle_dir / "output.tensor.bin"
            input_path.parent.mkdir(parents=True, exist_ok=True)
            input_path.write_bytes(input_payload)
            output_path.write_bytes(output_payload)
            request_path = bundle_dir / "request.json"
            write_json(request_path, {"request_id": request_id})

            if resource == "cpu":
                native_resource_facts = {
                    "accelerator_memory_bytes": 0,
                    "cuda_d2h_bytes": 0,
                    "cuda_h2d_bytes": 0,
                    "cuda_transfer_intervals": [],
                }
                device_api = "CPU"
                device_id = "CPU"
            else:
                h2d_ns = 100_000 + sample_index * 1_000
                d2h_ns = 50_000 + sample_index * 500
                gpu_id = "GPU-" + "1" * 32
                native_resource_facts = {
                    "accelerator_memory_bytes": 606_112,
                    "cuda_d2h_bytes": 4_000,
                    "cuda_h2d_bytes": 602_112,
                    "cuda_transfer_intervals": [
                        {
                            "bytes": 602_112,
                            "device_elapsed_ns": h2d_ns,
                            "device_id": gpu_id,
                            "direction": "h2d",
                            "host_end_monotonic_ns": 2_000_000 + sample_index,
                            "host_start_monotonic_ns": 1_000_000 + sample_index,
                            "timing_source": "cudaEventElapsedTime",
                        },
                        {
                            "bytes": 4_000,
                            "device_elapsed_ns": d2h_ns,
                            "device_id": gpu_id,
                            "direction": "d2h",
                            "host_end_monotonic_ns": 4_000_000 + sample_index,
                            "host_start_monotonic_ns": 3_000_000 + sample_index,
                            "timing_source": "cudaEventElapsedTime",
                        },
                    ],
                }
                device_api = "NVIDIA_CUDA"
                device_id = gpu_id
            response_path = bundle_dir / "response.json"
            response = {
                "schema_version": 1,
                "message_type": "infer_response",
                "request_id": request_id,
                "engine": native_resource,
                "frame": {"branch": branch},
                "provenance": {
                    "device_api": device_api,
                    "device_id": device_id,
                    "input_sha256": tensor_sha,
                },
                "resource": native_resource_facts,
            }
            write_json(response_path, response)
            self.response_paths.append(response_path)

            inventory: dict[str, dict[str, object]] = {}
            for file_role, physical_path in {
                "request": request_path,
                "response": response_path,
                "input_tensor": input_path,
                "output_tensor": output_path,
            }.items():
                record = descriptor(root, physical_path)
                inventory[file_role] = {
                    "path": physical_path.name,
                    "bytes": record["size_bytes"],
                    "sha256": record["sha256"],
                }
                transaction_files.append(record)
            manifest_core = {
                "schema_version": 1,
                "artifact_kind": "vast_analytics_execution_evidence_bundle",
                "protocol_identity_sha256": "1" * 64,
                "request_id": request_id,
                "run_id": "fixture-v3",
                "arm_id": f"fixture.{branch}.{resource}",
                "worker_id": f"fixture.{native_resource}",
                "frame": {"branch": branch},
                "capability_sha256": "2" * 64,
                "files": inventory,
            }
            manifest = {
                **manifest_core,
                "identity": {
                    "algorithm": "sha256",
                    "sha256": canonical_sha(manifest_core),
                },
            }
            manifest_path = bundle_dir / "manifest.json"
            write_json(manifest_path, manifest)
            manifest_record = descriptor(root, manifest_path)
            transaction_files.append(manifest_record)
            execution_bundles.append(
                {
                    "branch": branch,
                    "role": role,
                    "codec": codec,
                    "sample_id": sample_id,
                    "resource": native_resource,
                    "request_id": request_id,
                    "manifest": manifest_record,
                    "manifest_identity_sha256": manifest["identity"]["sha256"],
                    "request_sha256": inventory["request"]["sha256"],
                    "response_sha256": inventory["response"]["sha256"],
                    "input_tensor_sha256": inventory["input_tensor"]["sha256"],
                    "output_tensor_sha256": inventory["output_tensor"]["sha256"],
                }
            )
            output_segments.append(
                {
                    "branch": branch,
                    "resource": native_resource,
                    "sample_id": sample_id,
                    "preprocessed_tensor_sha256": tensor_sha,
                }
            )
            return sample_id, tensor_sha

        for branch_index, branch in enumerate(BRANCHES):
            evidence: dict[str, object] = {}
            for resource_index, (resource, (native_resource, evidence_name)) in enumerate(
                RESOURCE_DOCUMENTS.items()
            ):
                sample_count = (
                    29 if short_coordinate == (branch, resource) else 30
                )
                samples: list[dict[str, object]] = []
                for sample_index in range(30):
                    sample_id, _ = add_bundle(
                        branch=branch,
                        resource=resource,
                        native_resource=native_resource,
                        role="calibration",
                        sample_index=sample_index,
                    )
                    service_ms = float(
                        10 + branch_index + resource_index + sample_index / 100.0
                    )
                    if sample_index < sample_count:
                        samples.append(
                            {
                                "sample_id": sample_id,
                                "service_time_ms": service_ms,
                            }
                        )
                for sample_index in range(30):
                    add_bundle(
                        branch=branch,
                        resource=resource,
                        native_resource=native_resource,
                        role="evaluation",
                        sample_index=sample_index,
                    )

                calibration_path = root / (
                    f"evidence/model_parity/v3/documents/{branch}/"
                    f"{evidence_name}.json"
                )
                calibration = {
                    "schema_version": 2,
                    "artifact_kind": "checkpoint_model_policy_calibration",
                    "branch": branch,
                    "resource": native_resource,
                    "sample_count": sample_count,
                    "samples": samples,
                }
                write_json(calibration_path, calibration)
                self.calibration_paths[(branch, resource)] = calibration_path
                evidence[evidence_name] = {
                    "path": calibration_path.relative_to(root).as_posix(),
                    "sha256": descriptor(root, calibration_path)["sha256"],
                }
            workload_slots[branch] = {"evidence": evidence}

        transaction_files.sort(key=lambda item: str(item["path"]))
        output_segments.sort(
            key=lambda item: (
                str(item["branch"]),
                str(item["resource"]),
                str(item["sample_id"]),
            )
        )
        execution_bundles.sort(
            key=lambda item: (
                str(item["branch"]),
                str(item["resource"]),
                str(item["role"]),
                str(item["sample_id"]),
            )
        )
        transaction_index = {
            "schema_version": 2,
            "artifact_kind": "checkpoint_model_parity_materialization_transaction",
            "run_id": "v3",
            "claimed_aggregates_accepted": False,
            "synthetic_or_mock_evidence_accepted": False,
            "document_count": 32,
            "files": transaction_files,
            "files_sha256": canonical_sha(transaction_files),
            "final_materialization_path": "evidence/model_parity/v3",
            "output_segments": output_segments,
            "output_segments_sha256": canonical_sha(output_segments),
            "execution_bundle_count": len(execution_bundles),
            "execution_bundles": execution_bundles,
            "execution_bundles_sha256": canonical_sha(execution_bundles),
            "source_inventory": [],
            "source_inventory_sha256": canonical_sha([]),
        }
        transaction_index["transaction_sha256"] = canonical_sha(
            transaction_index
        )
        self.transaction_index_path = (
            root / "evidence/model_parity/v3/transaction_index.json"
        )
        write_json(self.transaction_index_path, transaction_index)

        accepted_manifest = {
            "schema_version": 3,
            "artifact_kind": "checkpoint_analytics_model_parity_manifest",
            "workload_slots": workload_slots,
        }
        write_json(self.accepted_manifest_path, accepted_manifest)
        write_json(
            self.accepted_assessment_path,
            {"artifact_kind": "fixture-accepted-assessment", "ready": True},
        )
        write_json(
            self.accepted_receipt_path,
            {"artifact_kind": "fixture-accepted-receipt", "accepted": True},
        )
        self.accepted_manifest = accepted_manifest
        self.binding = self._binding()

    def _binding(self) -> dict[str, object]:
        receipt_record = descriptor(self.root, self.accepted_receipt_path)
        manifest_record = descriptor(self.root, self.accepted_manifest_path)
        assessment_record = descriptor(self.root, self.accepted_assessment_path)
        transaction_record = descriptor(
            self.root, self.transaction_index_path
        )
        transaction = json.loads(
            self.transaction_index_path.read_text(encoding="utf-8")
        )
        transaction_binding = {
            **transaction_record,
            "transaction_sha256": transaction["transaction_sha256"],
            "files_sha256": transaction["files_sha256"],
            "output_segments_sha256": transaction["output_segments_sha256"],
            "execution_bundle_count": transaction["execution_bundle_count"],
            "execution_bundles_sha256": transaction[
                "execution_bundles_sha256"
            ],
        }
        files = [
            receipt_record,
            manifest_record,
            assessment_record,
            transaction_record,
        ]
        files.extend(
            descriptor(self.root, path)
            for path in self.calibration_paths.values()
        )
        files.sort(key=lambda item: str(item["path"]))
        value: dict[str, object] = {
            "schema_version": 2,
            "artifact_kind": "vast_verified_model_parity_acceptance_binding",
            "receipt": receipt_record,
            "accepted_manifest": manifest_record,
            "accepted_assessment": assessment_record,
            "acceptance_identity_sha256": "a" * 64,
            "accepted_manifest_content_identity_sha256": "b" * 64,
            "canonical_assessment_identity_sha256": "c" * 64,
            "evidence_count": 32,
            "evidence_sha256": "d" * 64,
            "runtime_registries_sha256": "e" * 64,
            "runtime_images_sha256": "f" * 64,
            "transaction_index": transaction_binding,
            "files": files,
            "files_sha256": canonical_sha(files),
        }
        value["binding_sha256"] = canonical_sha(value)
        return value

    def acceptance_loader(self, **kwargs: object) -> dict[str, object]:
        self.assert_loader_args(kwargs)
        return copy.deepcopy(self.binding)

    def assert_loader_args(self, kwargs: dict[str, object]) -> None:
        if Path(kwargs["project_root"]) != self.root:
            raise AssertionError("production validator project_root drifted")
        if Path(kwargs["receipt_path"]) != self.accepted_receipt_path:
            raise AssertionError("production validator receipt path drifted")

    @staticmethod
    def manifest_loader(path: Path) -> dict[str, object]:
        return json.loads(Path(path).read_text(encoding="utf-8"))


class PublicationPolicyQualificationBootstrapV2Tests(unittest.TestCase):
    def _build(
        self,
        fixture: BootstrapFixture,
        *,
        after_directory_publish_step=None,
        expected_validator_calls: int = 2,
    ):
        with mock.patch.object(
            target.model_parity_acceptance,
            "load_verified_model_parity_acceptance",
            side_effect=fixture.acceptance_loader,
        ) as validator, mock.patch.object(
            target,
            "_load_model_parity_manifest",
            side_effect=fixture.manifest_loader,
        ):
            result = target.build_qualification_bootstrap_calibration_v2(
                project_root=fixture.root,
                candidate_manifest_path=fixture.candidate_manifest_path,
                candidate_receipt_path=fixture.candidate_receipt_path,
                accepted_model_parity_manifest_path=fixture.accepted_manifest_path,
                accepted_model_parity_assessment_path=fixture.accepted_assessment_path,
                accepted_model_parity_receipt_path=fixture.accepted_receipt_path,
                output_dir=fixture.output_dir,
                after_directory_publish_step=after_directory_publish_step,
            )
        self.assertEqual(validator.call_count, expected_validator_calls)
        return result

    def test_happy_path_uses_physical_medians_and_stays_nonaccepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = BootstrapFixture(Path(tmp))
            result = self._build(fixture)
            receipt = json.loads(result["receipt_path"].read_text(encoding="utf-8"))
            mapping = json.loads(result["mapping_path"].read_text(encoding="utf-8"))

            self.assertFalse(receipt["accepted"])
            self.assertFalse(receipt["publication_ready"])
            self.assertEqual(
                receipt["scope"], "forced_resource_qualification_pilots_only"
            )
            self.assertEqual(len(receipt["physical_response_evidence"]), 240)
            self.assertFalse(mapping["accepted"])
            self.assertFalse(mapping["publication_ready"])
            self.assertEqual(set(result["calibration_paths"]), set(SYSTEMS))

            for system, path in result["calibration_paths"].items():
                calibration = json.loads(path.read_text(encoding="utf-8"))
                self.assertFalse(calibration["accepted"])
                self.assertFalse(calibration["publication_ready"])
                self.assertEqual(
                    calibration["scope"],
                    "forced_resource_qualification_pilots_only",
                )
                plate_cpu = calibration["costs"]["plate_number"]["cpu"]
                plate_gpu = calibration["costs"]["plate_number"]["gpu"]
                self.assertEqual(plate_cpu["samples"], 30)
                self.assertEqual(plate_cpu["transfer_ms"], 0.0)
                self.assertTrue(math.isclose(plate_cpu["service_ms"], 10.145))
                self.assertTrue(math.isclose(plate_gpu["service_ms"], 11.145))
                expected_transfer = ((114_500 + 57_250) / 1_000_000.0)
                self.assertTrue(
                    math.isclose(plate_gpu["transfer_ms"], expected_transfer)
                )
                self.assertEqual(
                    plate_gpu["implementation_id"],
                    fixture.candidate_manifest["systems"][system]["branches"]
                    ["plate_number"]["gpu"]["implementation_id"],
                )
                # This exercises the frozen production contract validator.
                policy.select_static_hybrid_map(
                    system, calibration, fixture.candidate_manifest
                )

    def test_sibling_bootstrap_commit_preserves_scoped_input_custody(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = BootstrapFixture(Path(tmp), transaction_layout=True)
            result = self._build(fixture)

            self.assertTrue(result["receipt_path"].is_file())
            self.assertEqual(
                result["receipt_path"].parent,
                fixture.root / "inputs/bootstrap-v2",
            )

    def test_postpublish_crash_resumes_exact_bootstrap_tree_same_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = BootstrapFixture(Path(tmp))

            def crash(step: str, path: Path) -> None:
                self.assertEqual(step, "post_publish_pre_parent_fsync")
                self.assertEqual(path, fixture.output_dir)
                raise KeyboardInterrupt("simulated hard crash")

            with self.assertRaises(KeyboardInterrupt):
                self._build(
                    fixture,
                    after_directory_publish_step=crash,
                )
            directory_inode = fixture.output_dir.stat().st_ino
            leaf_inodes = {
                path.name: path.stat().st_ino
                for path in fixture.output_dir.iterdir()
            }

            result = self._build(fixture, expected_validator_calls=1)

            self.assertEqual(fixture.output_dir.stat().st_ino, directory_inode)
            self.assertEqual(
                {
                    path.name: path.stat().st_ino
                    for path in fixture.output_dir.iterdir()
                },
                leaf_inodes,
            )
            self.assertTrue(result["receipt_path"].is_file())

    def test_candidate_manifest_and_receipt_tamper_fail_before_output(self) -> None:
        for target_name in ("candidate_manifest", "candidate_receipt"):
            with self.subTest(target_name=target_name), tempfile.TemporaryDirectory() as tmp:
                fixture = BootstrapFixture(Path(tmp))
                path = getattr(fixture, f"{target_name}_path")
                path.write_bytes(path.read_bytes() + b" ")
                with self.assertRaises(target.BootstrapCalibrationV2Error):
                    self._build(fixture)
                self.assertFalse(fixture.output_dir.exists())

    def test_parity_assessment_evidence_hash_and_sample_count_fail_closed(self) -> None:
        cases = (
            "assessment",
            "calibration_evidence",
            "physical_response",
            "transaction_hash",
            "sample_count",
        )
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                if case == "sample_count":
                    fixture = BootstrapFixture(
                        Path(tmp), short_coordinate=("plate_number", "gpu")
                    )
                else:
                    fixture = BootstrapFixture(Path(tmp))
                if case == "assessment":
                    fixture.accepted_assessment_path.write_bytes(
                        fixture.accepted_assessment_path.read_bytes() + b" "
                    )
                elif case == "calibration_evidence":
                    evidence = fixture.calibration_paths[("damage", "cpu")]
                    evidence.write_bytes(evidence.read_bytes() + b" ")
                elif case == "physical_response":
                    response = fixture.response_paths[0]
                    response.write_bytes(response.read_bytes() + b" ")
                elif case == "transaction_hash":
                    index = json.loads(
                        fixture.transaction_index_path.read_text(encoding="utf-8")
                    )
                    index["output_segments_sha256"] = "0" * 64
                    write_json(fixture.transaction_index_path, index)
                with self.assertRaises(target.BootstrapCalibrationV2Error):
                    self._build(fixture)
                self.assertFalse(fixture.output_dir.exists())

    def test_schema1_representative_transaction_is_not_bootstrap_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = BootstrapFixture(Path(tmp))
            index = json.loads(
                fixture.transaction_index_path.read_text(encoding="utf-8")
            )
            index["schema_version"] = 1
            index.pop("transaction_sha256")
            index.pop("execution_bundle_count")
            index.pop("execution_bundles")
            index.pop("execution_bundles_sha256")
            write_json(fixture.transaction_index_path, index)
            with self.assertRaisesRegex(
                target.BootstrapCalibrationV2Error,
                "schema-v2 transaction",
            ):
                self._build(fixture)
            self.assertFalse(fixture.output_dir.exists())

    def test_legacy_schema1_acceptance_binding_cannot_authorize_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = BootstrapFixture(Path(tmp))
            fixture.binding["schema_version"] = 1
            fixture.binding.pop("transaction_index")
            fixture.binding["binding_sha256"] = canonical_sha(
                {
                    key: value
                    for key, value in fixture.binding.items()
                    if key != "binding_sha256"
                }
            )
            with self.assertRaisesRegex(
                target.BootstrapCalibrationV2Error,
                "schema-v2 acceptance binding",
            ):
                self._build(fixture)
            self.assertFalse(fixture.output_dir.exists())

    def test_atomic_failure_cleans_only_private_staging(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = BootstrapFixture(Path(tmp))
            sentinel = fixture.root / "publication-store/must-survive.txt"
            sentinel.parent.mkdir(parents=True, exist_ok=True)
            sentinel.write_text("sentinel\n", encoding="utf-8")
            with mock.patch.object(
                target.model_parity_acceptance,
                "load_verified_model_parity_acceptance",
                side_effect=fixture.acceptance_loader,
            ), mock.patch.object(
                target,
                "_load_model_parity_manifest",
                side_effect=fixture.manifest_loader,
            ), mock.patch.object(
                target, "_rename_directory_noreplace", side_effect=OSError("injected")
            ):
                with self.assertRaisesRegex(
                    target.BootstrapCalibrationV2Error,
                    "atomic bootstrap calibration commit failed",
                ):
                    target.build_qualification_bootstrap_calibration_v2(
                        project_root=fixture.root,
                        candidate_manifest_path=fixture.candidate_manifest_path,
                        candidate_receipt_path=fixture.candidate_receipt_path,
                        accepted_model_parity_manifest_path=fixture.accepted_manifest_path,
                        accepted_model_parity_assessment_path=fixture.accepted_assessment_path,
                        accepted_model_parity_receipt_path=fixture.accepted_receipt_path,
                        output_dir=fixture.output_dir,
                    )
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "sentinel\n")
            self.assertFalse(fixture.output_dir.exists())
            self.assertEqual(
                list(sentinel.parent.glob(".policy-bootstrap-v2.*")), []
            )

    def test_raced_empty_destination_is_not_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = BootstrapFixture(Path(tmp))

            def collide(_source: Path, destination: Path) -> None:
                destination.mkdir()
                raise FileExistsError("injected raced destination")

            with mock.patch.object(
                target.model_parity_acceptance,
                "load_verified_model_parity_acceptance",
                side_effect=fixture.acceptance_loader,
            ), mock.patch.object(
                target,
                "_load_model_parity_manifest",
                side_effect=fixture.manifest_loader,
            ), mock.patch.object(
                target, "_rename_directory_noreplace", side_effect=collide
            ):
                with self.assertRaises(target.BootstrapCalibrationV2Error):
                    target.build_qualification_bootstrap_calibration_v2(
                        project_root=fixture.root,
                        candidate_manifest_path=fixture.candidate_manifest_path,
                        candidate_receipt_path=fixture.candidate_receipt_path,
                        accepted_model_parity_manifest_path=fixture.accepted_manifest_path,
                        accepted_model_parity_assessment_path=fixture.accepted_assessment_path,
                        accepted_model_parity_receipt_path=fixture.accepted_receipt_path,
                        output_dir=fixture.output_dir,
                    )
            self.assertTrue(fixture.output_dir.is_dir())
            self.assertEqual(list(fixture.output_dir.iterdir()), [])

    def test_cleanup_refuses_hardlinked_staging_inode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve()
            staging = Path(
                tempfile.mkdtemp(prefix=".policy-bootstrap-v2.", dir=parent)
            )
            source = staging / "payload.json"
            alias = staging / "payload.alias.json"
            source.write_text("{}\n", encoding="ascii")
            alias.hardlink_to(source)
            with self.assertRaisesRegex(
                target.BootstrapCalibrationV2Error, "unowned staging inode"
            ):
                target._cleanup_staging(
                    staging,
                    parent=parent,
                    expected_staging_identity=target._directory_identity(staging),
                    expected_parent_identity=target._directory_identity(parent),
                )
            self.assertTrue(source.exists())
            self.assertTrue(alias.exists())


if __name__ == "__main__":
    unittest.main()
