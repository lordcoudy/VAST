from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import full_publication_identity_artifacts as target  # noqa: E402


SYSTEMS = target.SYSTEMS
RESOURCES = target.RESOURCES
CODECS = target.CODECS
TOPOLOGIES = target.TOPOLOGIES
BRANCHES = target.BRANCHES


def canonical_sha(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()
    return hashlib.sha256(payload).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode() + b"\n")


def descriptor(root: Path, path: Path, *, base: Path | None = None) -> dict[str, object]:
    payload = path.read_bytes()
    return {"path": path.relative_to(root if base is None else base).as_posix(), "size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def self_hashed(value: dict[str, object], field: str = "sha256") -> dict[str, object]:
    result = copy.deepcopy(value)
    result[field] = canonical_sha(result)
    return result


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.output = root / "accepted"
        self.output.mkdir(parents=True, exist_ok=True)
        self.dataset_sha = hashlib.sha256(b"datasets").hexdigest()
        self.policy_contract_sha = hashlib.sha256(b"policy-contract").hexdigest()
        self.parity_identity = hashlib.sha256(b"parity-content").hexdigest()
        self.execution_identity = hashlib.sha256(b"execution-content").hexdigest()
        self._write_all()

    def parity_loader(self, path: Path) -> dict[str, object]:
        return {"artifact_kind": "checkpoint_analytics_model_parity_manifest", "identity": {"sha256": self.parity_identity}}

    def parity_acceptance_loader(self, *, project_root: Path, receipt_path: Path) -> dict[str, object]:
        self.assert_root(project_root)
        if receipt_path.resolve() != self.parity_receipt.resolve():
            raise RuntimeError("unexpected parity receipt")
        return copy.deepcopy(self.parity_acceptance)

    def assert_root(self, value: Path) -> None:
        if value.resolve() != self.root.resolve():
            raise RuntimeError("parity acceptance project root drift")

    def execution_loader(self, path: Path) -> dict[str, object]:
        return {"artifact_kind": "vast_analytics_execution_layer_config", "identity": {"sha256": self.execution_identity}}

    def policy_assessor(self, value: object) -> dict[str, object]:
        return {"passed": isinstance(value, dict) and value.get("policy_contract_sha256") == self.policy_contract_sha, "blockers": []}

    def _write_content_inputs(self) -> tuple[Path, Path]:
        parity = self.root / "configs/checkpoint_analytics_model_parity.accepted.yaml"
        execution = self.root / "configs/analytics_execution_layer.yaml"
        parity.parent.mkdir(parents=True, exist_ok=True)
        parity.write_text("parity-content\n", encoding="utf-8")
        execution.write_text("execution-content\n", encoding="utf-8")
        evidence = []
        for branch in BRANCHES:
            for name in (
                "cpu_execution_probe", "cuda_execution_probe", "calibration_corpus",
                "evaluation_corpus", "cpu_policy_calibration", "cuda_policy_calibration",
                "cpu_raw_output_bundle", "cuda_raw_output_bundle",
            ):
                path = self.root / f"evidence/model_parity/v3/{branch}/{name}.json"
                write_json(path, {"branch": branch, "evidence_name": name})
                evidence.append(descriptor(self.root, path))
        self.parity_assessment = self.output / "checkpoint_model_parity_accepted_assessment.json"
        self.parity_receipt = self.output / "checkpoint_model_parity_acceptance_receipt.json"
        write_json(self.parity_assessment, {"accepted": True})
        write_json(self.parity_receipt, {"accepted": True})
        parity_files = sorted(
            [
                descriptor(self.root, parity),
                descriptor(self.root, self.parity_assessment),
                descriptor(self.root, self.parity_receipt),
                *evidence,
            ],
            key=lambda item: item["path"],
        )
        self.parity_acceptance = {
            "schema_version": 1,
            "artifact_kind": "vast_verified_model_parity_acceptance_binding",
            "receipt": descriptor(self.root, self.parity_receipt),
            "accepted_manifest": descriptor(self.root, parity),
            "accepted_assessment": descriptor(self.root, self.parity_assessment),
            "acceptance_identity_sha256": hashlib.sha256(b"parity-acceptance").hexdigest(),
            "accepted_manifest_content_identity_sha256": self.parity_identity,
            "canonical_assessment_identity_sha256": hashlib.sha256(b"canonical-assessment").hexdigest(),
            "evidence_count": 32,
            "evidence_sha256": canonical_sha(evidence),
            "runtime_registries_sha256": hashlib.sha256(b"runtime-registries").hexdigest(),
            "runtime_images_sha256": hashlib.sha256(b"runtime-images").hexdigest(),
            "files": parity_files,
            "files_sha256": canonical_sha(parity_files),
        }
        self.parity_acceptance["binding_sha256"] = canonical_sha(self.parity_acceptance)
        return parity, execution

    def _policy(self) -> tuple[Path, Path, Path]:
        systems = {}
        for system in SYSTEMS:
            branches = {}
            for branch in BRANCHES:
                resources = {}
                for resource in RESOURCES:
                    stem = f"{system}-{branch}-{resource}"
                    resources[resource] = {
                        "status": "implemented_and_native_evidence_bound",
                        "implementation_id": f"implementation-{stem}",
                        "implementation_sha256": hashlib.sha256((stem + "-impl").encode()).hexdigest(),
                        "runtime_binding": f"runtime-binding-{stem}",
                        "runtime_identity": {"runtime_backend": f"backend-{system}", "device_api": f"device-api-{resource}", "worker_image_digest": "sha256:" + hashlib.sha256((stem + "-image").encode()).hexdigest(), "implementation_version": f"version-{stem}"},
                        "native_evidence": {"status": "accepted_native_runtime_emitter", "telemetry_source": "native", "emitter_id": f"emitter-{stem}", "emitter_sha256": hashlib.sha256((stem + "-emitter").encode()).hexdigest(), "implementation_id_field": "implementation_id", "resource_field": "selected_resource"},
                    }
                branches[branch] = resources
            systems[system] = {"branches": branches}
        capability = {"schema_version": 1, "artifact_kind": "vast_publication_policy_capability_manifest", "policy_scope": "analytics_only", "policy_contract_sha256": self.policy_contract_sha, "systems": systems}
        capability_path = self.output / "checkpoint_policy_capability_manifest.json"
        write_json(capability_path, capability)
        calibration = {"schema_version": 1, "artifact_kind": "vast_publication_policy_calibration_mapping", "policy_contract_sha256": self.policy_contract_sha, "aggregation_rule": "median_of_balanced_native_codec_topology_cells_v1", "minimum_samples_per_branch_cell": 30, "calibrations": {system: {"system": system} for system in SYSTEMS}}
        calibration_path = self.output / "checkpoint_policy_calibration_mapping.json"
        write_json(calibration_path, calibration)
        receipt = {
            "schema_version": 1, "artifact_kind": "vast_publication_policy_qualification_receipt", "status": "accepted_evidence_driven_policy_qualification",
            "policy_contract_sha256": self.policy_contract_sha, "qualification_index_sha256": hashlib.sha256(b"policy-index").hexdigest(), "dataset_manifest_sha256": self.dataset_sha,
            "coverage": {"binding_count": 32, "pilot_cell_count": 32, "accepted_sample_count": 3840, "minimum_samples_per_branch_cell": 30},
            "outputs": {"capability_manifest": descriptor(self.root, capability_path, base=self.output), "calibration_mapping": descriptor(self.root, calibration_path, base=self.output)},
        }
        receipt_path = self.output / "checkpoint_policy_qualification_receipt.json"
        write_json(receipt_path, self_hashed(receipt))
        return receipt_path, capability_path, calibration_path

    def _resource(self) -> tuple[Path, Path]:
        contract = {"contract_version": 2, "publication_scope": target.PUBLICATION_SCOPE, "full_resource_validator_sha256": hashlib.sha256(b"full-validator").hexdigest(), "interval_validator_sha256": hashlib.sha256(b"interval-validator").hexdigest()}
        datasets = {codec: {"dataset_name": f"kpp_real_{codec}", "manifest_identity_sha256": hashlib.sha256((codec + "-manifest").encode()).hexdigest(), "source_sha256": sorted(hashlib.sha256((codec + str(i)).encode()).hexdigest() for i in (1, 2)), "annotation_sha256": hashlib.sha256((codec + "-annotations").encode()).hexdigest()} for codec in CODECS}
        systems = {}
        for system in SYSTEMS:
            resources = {}
            for resource in RESOURCES:
                stem = f"{system}-{resource}"
                emitters = {role: {"status": "native_emitter_implementation_bound", "emitter_id": f"{role}-{stem}", "artifact_sha256": hashlib.sha256((role + stem).encode()).hexdigest(), "telemetry_source": "native"} for role in ("resource_intervals", "hardware_resource_samples", "fanout_work_counters")}
                resources[resource] = {"status": "implemented_and_pre_run_pilot_required", "implementation_id": f"resource-implementation-{stem}", "implementation_sha256": hashlib.sha256((stem + "-impl").encode()).hexdigest(), "runtime_binding": f"resource-runtime-binding-{stem}", "runtime_identity": {"runtime_backend": f"backend-{system}", "analytics_device_api": f"analytics-api-{resource}", "decoder_device_api": "NVIDIA-NVDEC", "worker_image_digest": "sha256:" + hashlib.sha256((stem + "-image").encode()).hexdigest(), "implementation_version": f"resource-version-{stem}", "hardware_binding_id": f"hardware-binding-{stem}"}, "emitters": emitters}
            systems[system] = {"resources": resources}
        pilots = []
        for coordinate in sorted((system, resource, codec, topology) for system in SYSTEMS for resource in RESOURCES for codec in CODECS for topology in TOPOLOGIES):
            system, resource, codec, topology = coordinate
            stem = "-".join(coordinate)
            samples = {branch: 30 for branch in BRANCHES}
            pilots.append({"system": system, "resource": resource, "codec": codec, "topology_kind": topology, "run_id": f"accepted-pilot-{stem}", "dataset_name": f"kpp_real_{codec}", "source_sha256": datasets[codec]["source_sha256"], "evidence_sha256": {role: hashlib.sha256((stem + role).encode()).hexdigest() for role in ("checkpoint_acceptance", "frames", "frame_events", "ingress_ledger", "topology_events", "resource_intervals", "hardware_resource_samples", "fanout_work_counters")}, "resource_summary": {"resource_contract_version": 2, "evidence_accepted": True, "publication_bundle_bound": True, "full_resource_coverage_complete": True, "nvdec_busy_equivalent_ns": 1, "nvdec_counter_scope": "device_sample", "fanout_thread_cpu_time_ns": 1 if topology == "shared_video_dag" else 0, "fanout_work_units": 1 if topology == "shared_video_dag" else 0, "fanout_counter_scope": "per_trace_resource_work"}, "accepted_samples_by_branch": samples, "accepted_branch_sample_count": 120})
        coverage = {"binding_count": 8, "pilot_cell_count": 32, "accepted_branch_sample_count": 3840, "minimum_samples_per_branch_coordinate": 30, "systems": 4, "resources": 2, "codecs": 2, "topology_kinds": 2, "branches": 4}
        capability = {"schema_version": 1, "artifact_kind": "vast_pre_run_full_resource_capability_manifest", "qualification_scope": "pre_run_hardware_and_emitter_capability_only", "publication_scope": target.PUBLICATION_SCOPE, "resource_contract": contract, "resource_contract_identity_sha256": canonical_sha(contract), "dataset_manifest_sha256": self.dataset_sha, "datasets": datasets, "systems": systems, "pilot_cells": pilots, "coverage": coverage, "post_run_per_arm_evidence": {"required": True, "acceptance_artifact_kind": "checkpoint_publication_runtime_acceptance", "validator": "validate_full_resource_evidence", "configuration_evidence_accepted_mutated": False}}
        capability = self_hashed(capability, "content_sha256")
        capability_path = self.output / "checkpoint_full_resource_capability_manifest.json"
        write_json(capability_path, capability)
        receipt = {"schema_version": 1, "artifact_kind": "vast_pre_run_full_resource_capability_qualification_receipt", "status": "accepted_pre_run_resource_capability_qualification", "qualification_index_sha256": hashlib.sha256(b"resource-index").hexdigest(), "dataset_manifest_sha256": self.dataset_sha, "resource_contract_identity_sha256": capability["resource_contract_identity_sha256"], "capability_manifest_content_sha256": capability["content_sha256"], "coverage": coverage, "post_run_per_arm_evidence_required": True, "configuration_evidence_accepted_mutated": False, "outputs": {"capability_manifest": descriptor(self.root, capability_path, base=self.output)}}
        receipt_path = self.output / "checkpoint_full_resource_qualification_receipt.json"
        write_json(receipt_path, self_hashed(receipt))
        return receipt_path, capability_path

    def _backends(self, policy_receipt: Path, resource_receipt: Path) -> tuple[Path, dict[str, Path]]:
        common = {
            "qualification_index_sha256": hashlib.sha256(b"backend-index-source").hexdigest(),
            "dataset_manifest_sha256": self.dataset_sha,
            "policy_contract_sha256": self.policy_contract_sha,
            "policy_qualification_receipt_sha256": descriptor(self.root, policy_receipt)["sha256"],
            "resource_contract_identity_sha256": json.loads(resource_receipt.read_text())["resource_contract_identity_sha256"],
            "resource_qualification_receipt_sha256": descriptor(self.root, resource_receipt)["sha256"],
            "analytics_execution_config_identity_sha256": self.execution_identity,
            "model_parity_manifest_identity_sha256": self.parity_identity,
        }
        receipts = {}
        receipt_descriptors = {}
        for system in SYSTEMS:
            receipt = {
                "schema_version": 1,
                "artifact_kind": "vast_backend_runtime_qualification_receipt",
                "status": "accepted_pre_run_backend_runtime_qualification",
                "qualification_scope": "backend_native_runtime_hardware_capability_only",
                "system": system,
                **common,
                "runtime_binding_identity_sha256": hashlib.sha256((system + "-binding").encode()).hexdigest(),
                "coverage": target._backend_coverage(),
                "post_run_per_arm_evidence_required": True,
                "configuration_evidence_accepted_mutated": False,
            }
            path = self.output / f"checkpoint_{system}_backend_runtime_qualification_receipt.json"
            write_json(path, self_hashed(receipt))
            receipts[system] = path
            receipt_descriptors[system] = descriptor(self.root, path, base=self.output)
        index = {
            "schema_version": 1,
            "artifact_kind": "vast_backend_runtime_qualification_binding_index",
            "status": "accepted_pre_run_backend_runtime_qualification_set",
            "qualification_index_sha256": common["qualification_index_sha256"],
            "systems": list(SYSTEMS),
            "receipts": receipt_descriptors,
            "coverage": target._backend_coverage(system_count=4),
            "post_run_per_arm_evidence_required": True,
            "configuration_evidence_accepted_mutated": False,
        }
        index_path = self.output / "checkpoint_backend_runtime_qualification_binding_index.json"
        write_json(index_path, self_hashed(index))
        return index_path, receipts

    def _write_all(self) -> None:
        parity, execution = self._write_content_inputs()
        policy_receipt, policy_capability, policy_calibration = self._policy()
        resource_receipt, resource_capability = self._resource()
        backend_index, backend_receipts = self._backends(policy_receipt, resource_receipt)
        manifest = {
            "schema_version": 2,
            "artifact_kind": target.MANIFEST_KIND,
            "bindings": {
                "analytics_model_parity": {
                    "receipt": descriptor(self.root, self.parity_receipt),
                    "accepted_manifest": descriptor(self.root, parity),
                    "accepted_assessment": descriptor(self.root, self.parity_assessment),
                },
                "analytics_execution_layer": {"artifact": descriptor(self.root, execution), "content_identity_sha256": self.execution_identity},
                "policy_qualification": {"receipt": descriptor(self.root, policy_receipt), "outputs": {"capability_manifest": descriptor(self.root, policy_capability), "calibration_mapping": descriptor(self.root, policy_calibration)}},
                "resource_qualification": {"receipt": descriptor(self.root, resource_receipt), "outputs": {"capability_manifest": descriptor(self.root, resource_capability)}},
                "backend_runtime_qualification": {"binding_index": descriptor(self.root, backend_index), "receipts": {system: descriptor(self.root, path) for system, path in backend_receipts.items()}},
            },
        }
        self.manifest_path = self.root / "configs/full_publication_identity_artifacts.json"
        write_json(self.manifest_path, manifest)

    def load(self) -> dict[str, object]:
        return target.load_full_publication_identity_artifacts(
            project_root=self.root,
            manifest_path=self.manifest_path,
            parity_loader=self.parity_loader,
            parity_acceptance_loader=self.parity_acceptance_loader,
            execution_loader=self.execution_loader,
            policy_capability_assessor=self.policy_assessor,
        )


class FullPublicationIdentityArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.fixture = Fixture(self.root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_accepted_artifacts_form_canonical_binding_and_guard_file_set(self) -> None:
        result = self.fixture.load()
        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["artifact_kind"], target.BINDING_KIND)
        self.assertRegex(result["binding_sha256"], r"^[0-9a-f]{64}$")
        paths = {record["path"] for record in result["files"]}
        self.assertIn("configs/full_publication_identity_artifacts.json", paths)
        self.assertIn("accepted/checkpoint_policy_qualification_receipt.json", paths)
        self.assertIn("accepted/checkpoint_full_resource_qualification_receipt.json", paths)
        self.assertIn("accepted/checkpoint_model_parity_acceptance_receipt.json", paths)
        self.assertEqual(result["bindings"]["analytics_model_parity"]["evidence_count"], 32)
        self.assertEqual(len(result["bindings"]["backend_runtime_qualification"]["receipts"]), 4)

    def test_descriptor_drift_and_unaccepted_receipt_fail_closed(self) -> None:
        calibration = self.fixture.output / "checkpoint_policy_calibration_mapping.json"
        calibration.write_bytes(calibration.read_bytes() + b"drift")
        with self.assertRaisesRegex(target.IdentityArtifactError, "size/SHA drift"):
            self.fixture.load()

        self.fixture = Fixture(self.root)
        receipt = self.fixture.output / "checkpoint_policy_qualification_receipt.json"
        value = json.loads(receipt.read_text())
        value.pop("sha256")
        value["status"] = "engineering_canary_only"
        write_json(receipt, self_hashed(value))
        manifest = json.loads(self.fixture.manifest_path.read_text())
        manifest["bindings"]["policy_qualification"]["receipt"] = descriptor(self.root, receipt)
        write_json(self.fixture.manifest_path, manifest)
        with self.assertRaisesRegex(target.IdentityArtifactError, "status is not accepted"):
            self.fixture.load()

    def test_content_identity_and_hardlink_alias_fail_closed(self) -> None:
        self.fixture.parity_acceptance["accepted_manifest_content_identity_sha256"] = "0" * 64
        with self.assertRaisesRegex(target.IdentityArtifactError, "self-hash drift"):
            self.fixture.load()

        self.fixture = Fixture(self.root)
        parity = self.root / "configs/checkpoint_analytics_model_parity.accepted.yaml"
        alias = self.root / "configs/parity-hardlink.yaml"
        try:
            os.link(parity, alias)
        except OSError as error:
            self.skipTest(f"hardlinks unavailable: {error}")
        manifest = json.loads(self.fixture.manifest_path.read_text())
        manifest["bindings"]["analytics_model_parity"]["accepted_manifest"] = descriptor(self.root, alias)
        write_json(self.fixture.manifest_path, manifest)
        with self.assertRaisesRegex(target.IdentityArtifactError, "hardlink alias"):
            self.fixture.load()

    def test_resource_coverage_accepts_more_than_the_minimum_when_totals_bind(self) -> None:
        capability = (
            self.fixture.output / "checkpoint_full_resource_capability_manifest.json"
        )
        value = json.loads(capability.read_text())
        value.pop("content_sha256")
        value["pilot_cells"][0]["accepted_samples_by_branch"][BRANCHES[0]] = 31
        value["pilot_cells"][0]["accepted_branch_sample_count"] = 121
        value["coverage"]["accepted_branch_sample_count"] = 3841
        write_json(capability, self_hashed(value, "content_sha256"))

        receipt = self.fixture.output / "checkpoint_full_resource_qualification_receipt.json"
        receipt_value = json.loads(receipt.read_text())
        receipt_value.pop("sha256")
        receipt_value["capability_manifest_content_sha256"] = json.loads(
            capability.read_text()
        )["content_sha256"]
        receipt_value["coverage"]["accepted_branch_sample_count"] = 3841
        receipt_value["outputs"]["capability_manifest"] = descriptor(
            self.root, capability, base=self.fixture.output
        )
        write_json(receipt, self_hashed(receipt_value))

        manifest = json.loads(self.fixture.manifest_path.read_text())
        resource_binding = manifest["bindings"]["resource_qualification"]
        resource_binding["receipt"] = descriptor(self.root, receipt)
        resource_binding["outputs"]["capability_manifest"] = descriptor(
            self.root, capability
        )
        backend = manifest["bindings"]["backend_runtime_qualification"]
        for system, raw_descriptor in backend["receipts"].items():
            path = self.root / raw_descriptor["path"]
            backend_receipt = json.loads(path.read_text())
            backend_receipt.pop("sha256")
            backend_receipt["resource_qualification_receipt_sha256"] = descriptor(
                self.root, receipt
            )["sha256"]
            write_json(path, self_hashed(backend_receipt))
            backend["receipts"][system] = descriptor(self.root, path)
        index_path = self.root / backend["binding_index"]["path"]
        index = json.loads(index_path.read_text())
        index.pop("sha256")
        index["receipts"] = {
            system: descriptor(self.root, self.root / item["path"], base=index_path.parent)
            for system, item in backend["receipts"].items()
        }
        write_json(index_path, self_hashed(index))
        backend["binding_index"] = descriptor(self.root, index_path)
        write_json(self.fixture.manifest_path, manifest)

        self.assertEqual(
            self.fixture.load()["bindings"]["resource_qualification"]["receipt"][
                "sha256"
            ],
            descriptor(self.root, receipt)["sha256"],
        )

    def test_missing_default_manifest_is_an_explicit_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(target.IdentityArtifactError, "manifest is missing"):
                target.load_full_publication_identity_artifacts(project_root=root)


if __name__ == "__main__":
    unittest.main()
